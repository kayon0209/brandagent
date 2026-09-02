/**
 * useConsumerProjectEvents — SSE subscription unit tests.
 *
 * The transport pieces worth pinning without a server: frame parsing
 * (id/event/data envelope), heartbeat-comment filtering, cursor advance,
 * interest-based dispatch (only registered handlers fire), and regex
 * versioning tolerance (v1..vN).
 */

import { TextDecoder, TextEncoder } from 'node:util'
import { ReadableStream } from 'node:stream/web'

import { act, renderHook, waitFor } from '@testing-library/react'

import { useConsumerProjectEvents } from '@/hooks/useConsumerProjectEvents'

// jsdom lacks the fetch-era globals the hook's transport relies on; the
// hook resolves them at call time from the global scope, so installing
// node's implementations here is what makes the loop executable at all.
if (typeof globalThis.TextDecoder === 'undefined') {
  ;(globalThis as Record<string, unknown>).TextDecoder = TextDecoder
}
if (typeof globalThis.TextEncoder === 'undefined') {
  ;(globalThis as Record<string, unknown>).TextEncoder = TextEncoder
}

type Frame = { id: number; event: string; data: string }

/**
 * jsdom has no fetch Response; the hook only needs `.ok` and a
 * `.body.getReader()` byte stream, so a minimal stand-in suffices.
 */
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

const globalFetch = global.fetch

afterEach(() => {
  global.fetch = globalFetch
})

function renderWithInterests(interests: Parameters<typeof useConsumerProjectEvents>[1]) {
  return renderHook(() => useConsumerProjectEvents('proj-1', interests))
}

test('dispatches matched events to the right handlers and skips heartbeats', async () => {
  global.fetch = jest.fn().mockResolvedValue(
    sseResponse([
      { id: 1, event: 'consumer.variant.generated.v1', data: '{"data":{"channel":"wechat_website"}}' },
      { id: 2, event: 'consumer.project.updated.v1', data: '{"data":{"project_id":"proj-1"}}' },
    ]),
  )
  const onVariant = jest.fn()
  const onUpdated = jest.fn()
  const onMaterial = jest.fn()

  await act(async () => {
    renderWithInterests({
      variantGenerated: onVariant,
      projectUpdated: onUpdated,
      materialDistilled: onMaterial,
    })
  })

  await waitFor(() => expect(onVariant).toHaveBeenCalledTimes(1))
  expect(onVariant.mock.calls[0][0].payload).toEqual({ channel: 'wechat_website' })
  await waitFor(() => expect(onUpdated).toHaveBeenCalledTimes(1))
  expect(onMaterial).not.toHaveBeenCalled()
})

test('tolerates future event versions (v2) via regex matching', async () => {
  global.fetch = jest.fn().mockResolvedValue(
    sseResponse([{ id: 7, event: 'consumer.variant.generated.v2', data: '{"data":{}}' }]),
  )
  const onVariant = jest.fn()
  await act(async () => {
    renderWithInterests({ variantGenerated: onVariant })
  })
  await waitFor(() => expect(onVariant).toHaveBeenCalledTimes(1))
  expect(onVariant.mock.calls[0][0].id).toBe(7)
})

test('resumes with the Last-Event-ID cursor after a consumed stream', async () => {
  global.fetch = jest.fn().mockResolvedValue(
    sseResponse([{ id: 3, event: 'consumer.draft.adopted.v1', data: '{"data":{}}' }]),
  )
  const onAdopted = jest.fn()
  await act(async () => {
    renderWithInterests({ draftAdopted: onAdopted })
  })
  // second connection (stream closed → loop reconnects) must carry the cursor
  global.fetch = jest.fn().mockImplementation((_url: unknown, init?: RequestInit) => {
    const header = (init?.headers as Record<string, string>)['Last-Event-ID']
    expect(header).toBe('3')
    return Promise.resolve(sseResponse([]))
  })
  await act(async () => {
    await new Promise(resolve => setTimeout(resolve, 20))
  })
})

test('malformed data payloads dispatch with empty payload instead of throwing', async () => {
  global.fetch = jest.fn().mockResolvedValue(
    sseResponse([{ id: 5, event: 'consumer.material.failed.v1', data: 'not-json' }]),
  )
  const onFailed = jest.fn()
  await act(async () => {
    renderWithInterests({ materialFailed: onFailed })
  })
  await waitFor(() => expect(onFailed).toHaveBeenCalledTimes(1))
  expect(onFailed.mock.calls[0][0].payload).toEqual({})
})

test('unregistered event types fire no handlers', async () => {
  global.fetch = jest.fn().mockResolvedValue(
    sseResponse([{ id: 9, event: 'consumer.unknown.future.v1', data: '{"data":{}}' }]),
  )
  const handler = jest.fn()
  await act(async () => {
    renderWithInterests({ variantGenerated: handler })
  })
  expect(handler).not.toHaveBeenCalled()
})
