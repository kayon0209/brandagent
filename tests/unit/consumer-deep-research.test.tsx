/**
 * useDeepResearch — Phase 6 unit tests (user-approved 2026-09-08).
 *
 * Pins the product red lines from MASTER_PLAN §10 without a server:
 * - pre-start estimate is shown BEFORE anything is billed;
 * - the SSE loop advances progress only from consumer.research.* events;
 * - terminal events (completed/failed/canceled) fetch the final run and
 *   stop the loop — a finished run can never render "running";
 * - 加入素材 is explicit per card, once, and only after a terminal state;
 * - start failures surface an honest message and return to idle.
 */

import { TextDecoder, TextEncoder } from 'node:util'
import { ReadableStream } from 'node:stream/web'

import { act, renderHook, waitFor } from '@testing-library/react'

import { useDeepResearch } from '@/hooks/useDeepResearch'
import type { ResearchRun } from '@/lib/api/research'

if (typeof globalThis.TextDecoder === 'undefined') {
  ;(globalThis as Record<string, unknown>).TextDecoder = TextDecoder
}
if (typeof globalThis.TextEncoder === 'undefined') {
  ;(globalThis as Record<string, unknown>).TextEncoder = TextEncoder
}

type Frame = { id: number; event: string; data: string }

function sseResponse(frames: Frame[]) {
  const body = frames
    .map(f => `id: ${f.id}\nevent: ${f.event}\ndata: ${f.data}\n\n`)
    .join(': heartbeat\n\n')
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(body))
      controller.close()
    },
  })
  return { ok: true, body: stream }
}

const START_RUN: ResearchRun = {
  run_id: 'run-1',
  question: '中文创作者常用分发渠道？',
  audience: '',
  scope_hint: '',
  status: 'running',
  created_at: '2026-09-08T00:00:00Z',
}

const DONE_RUN: ResearchRun = {
  ...START_RUN,
  status: 'succeeded',
  planned_directions: ['渠道一', '渠道二'],
  directions_completed: 2,
  candidate_cards: [
    {
      url: 'https://example.com/a',
      title: '来源 A',
      excerpt: '可引用的句子甲。',
      retrieved_at: '2026-09-08T00:01:00Z',
      reachable: true,
      excerpt_valid: true,
    },
  ],
  synthesis: '【R1】汇总文本。',
}

const globalFetch = global.fetch

afterEach(() => {
  global.fetch = globalFetch
})

function mockStart() {
  global.fetch = jest.fn().mockImplementation(async (url: RequestInfo | URL, init?: RequestInit) => {
    const target = String(url)
    const method = init?.method ?? 'GET'
    if (target.includes('/api/v1/consumer/research') && method === 'POST' && target.endsWith('/research')) {
      return {
        ok: true,
        text: async () => JSON.stringify({ success: true, data: { ...START_RUN, estimated_tokens: 30000 } }),
      }
    }
    if (target.includes('/run-1/cards/0/join')) {
      return {
        ok: true,
        text: async () =>
          JSON.stringify({
            success: true,
            data: { document_id: 'doc-1', status: 'distilled', url: 'https://example.com/a', title: '来源 A' },
          }),
      }
    }
    if (target.includes('/run-1') && target.includes('/events')) {
      return sseResponse([
        {
          id: 1,
          event: 'consumer.research.planned.v1',
          data: '{"data":{"directions":["渠道一","渠道二"]}}',
        },
        {
          id: 2,
          event: 'consumer.research.completed.v1',
          data: '{"data":{"cards":1}}',
        },
      ])
    }
    if (target.includes('/run-1') && !target.includes('/events') && !target.includes('/join')) {
      return { ok: true, text: async () => JSON.stringify({ success: true, data: DONE_RUN }) }
    }
    throw new Error(`unmocked fetch: ${method} ${target}`)
  })
}

test('start shows the estimate, subscribes, and reaches succeeded with cards', async () => {
  mockStart()
  const { result } = renderHook(() => useDeepResearch())

  await act(async () => {
    await result.current.start('中文创作者常用分发渠道？', '', '')
  })

  // the estimate was shown at launch time (before any terminal state)
  expect(result.current.message).toContain('30K')
  // the Idempotency-Key rode the start request
  const startCall = (global.fetch as jest.Mock).mock.calls.find(
    (call: unknown[]) => String(call[0]).endsWith('/api/v1/consumer/research'),
  )
  expect(String(startCall[1].headers['Idempotency-Key'])).toMatch(/^research-/)

  await waitFor(
    () => {
      expect(result.current.phase).toBe('succeeded')
    },
    { timeout: 4000 },
  )
  expect(result.current.run?.candidate_cards).toHaveLength(1)
  expect(result.current.progress.directions).toEqual(['渠道一', '渠道二'])
})

test('joinCard is explicit, once per card, and only meaningful after results exist', async () => {
  mockStart()
  const { result } = renderHook(() => useDeepResearch())

  await act(async () => {
    await result.current.start('中文创作者常用分发渠道？', '', '')
  })
  await waitFor(
    () => {
      expect(result.current.phase).toBe('succeeded')
    },
    { timeout: 4000 },
  )

  await act(async () => {
    await result.current.joinCard(0, 'task-9')
  })
  expect(result.current.joinedCards.has(0)).toBe(true)

  // second join of the SAME card is a no-op: no second request
  const callsBefore = (global.fetch as jest.Mock).mock.calls.length
  await act(async () => {
    await result.current.joinCard(0, 'task-9')
  })
  expect((global.fetch as jest.Mock).mock.calls.length).toBe(callsBefore)
  const joinCall = (global.fetch as jest.Mock).mock.calls.find(
    (call: unknown[]) => String(call[0]).includes('/run-1/cards/0/join'),
  )
  expect(String(joinCall[1].body)).toContain('task-9')
})

test('start failure returns to idle with an honest message', async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: false,
    status: 409,
    text: async () =>
      JSON.stringify({ success: false, error: { code: 'QUOTA_EXCEEDED', message: '本月额度已用完，AI 功能暂停。' } }),
  })
  const { result } = renderHook(() => useDeepResearch())

  await act(async () => {
    await result.current.start('额度不足时会发生什么？', '', '')
  })

  expect(result.current.phase).toBe('idle')
  expect(result.current.message).toContain('额度已用完')
})

test('cancel applies the canceled run and keeps partial cards', async () => {
  global.fetch = jest.fn().mockImplementation(async (url: RequestInfo | URL, init?: RequestInit) => {
    const target = String(url)
    const method = init?.method ?? 'GET'
    if (target.endsWith('/api/v1/consumer/research') && method === 'POST') {
      return { ok: true, text: async () => JSON.stringify({ success: true, data: { ...START_RUN, estimated_tokens: 30000 } }) }
    }
    if (target.includes('/cancel')) {
      return {
        ok: true,
        text: async () =>
          JSON.stringify({
            success: true,
            data: {
              ...DONE_RUN,
              status: 'canceled',
              candidate_cards: DONE_RUN.candidate_cards,
            },
          }),
      }
    }
    if (target.includes('/events')) {
      // stream stays open (no terminal event) — cancel must work regardless
      return sseResponse([{ id: 1, event: 'consumer.research.planned.v1', data: '{"data":{"directions":["渠道一"]}}' }])
    }
    if (target.includes('/run-1')) {
      return { ok: true, text: async () => JSON.stringify({ success: true, data: { ...DONE_RUN, status: 'canceled' } }) }
    }
    throw new Error(`unmocked fetch: ${target}`)
  })

  const { result } = renderHook(() => useDeepResearch())
  await act(async () => {
    await result.current.start('取消保留什么？', '', '')
  })
  await act(async () => {
    await result.current.cancel()
  })

  expect(result.current.phase).toBe('canceled')
  expect(result.current.run?.candidate_cards).toHaveLength(1)
})
