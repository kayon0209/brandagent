'use client'

/**
 * useDeepResearch — Phase 6 深度调研 hook (user-approved 2026-09-08).
 *
 * Owns the full client lifecycle: start (with pre-flight estimate),
 * SSE progress subscription (same Last-Event-ID cursor discipline as
 * useConsumerProjectEvents), cooperative cancel, and the 加入素材
 * action. State machine is deliberately explicit so the UI can never
 * render "running" for a run that already reached a terminal state.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import {
  cancelDeepResearch,
  getDeepResearch,
  joinResearchCard,
  startDeepResearch,
  type JoinCardResult,
  type ResearchCandidateCard,
  type ResearchRun,
} from '@/lib/api/research'

export type ResearchPhase =
  | 'idle' // entry button only
  | 'starting' // request in flight, nothing billed yet
  | 'running' // run accepted; progress via SSE
  | 'succeeded'
  | 'failed'
  | 'canceled'

export interface ResearchProgress {
  directions: string[]
  completedDirections: number
  searchCalls: number
}

export interface UseDeepResearchResult {
  phase: ResearchPhase
  run: ResearchRun | null
  progress: ResearchProgress
  busy: boolean
  message: string | null
  start: (question: string, audience: string, scope: string) => Promise<void>
  cancel: () => Promise<void>
  reset: () => void
  joinCard: (cardIndex: number, taskId?: string | null) => Promise<JoinCardResult | null>
  joinedCards: Set<number>
}

const RESEARCH_EVENT = /^consumer\.research\./

export function useDeepResearch(): UseDeepResearchResult {
  const [phase, setPhase] = useState<ResearchPhase>('idle')
  const [run, setRun] = useState<ResearchRun | null>(null)
  const [progress, setProgress] = useState<ResearchProgress>({
    directions: [],
    completedDirections: 0,
    searchCalls: 0,
  })
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [joinedCards, setJoinedCards] = useState<Set<number>>(new Set())

  const runIdRef = useRef<string | null>(null)
  const stoppedRef = useRef(false)
  const lastEventIdRef = useRef(0)

  useEffect(() => {
    return () => {
      stoppedRef.current = true
    }
  }, [])

  const applyRun = useCallback((next: ResearchRun) => {
    setRun(next)
    if (next.status === 'succeeded') setPhase('succeeded')
    else if (next.status === 'failed') setPhase('failed')
    else if (next.status === 'canceled') setPhase('canceled')
    else if (next.status === 'running' || next.status === 'planned') setPhase('running')
    if (next.planned_directions?.length) {
      setProgress(prev => ({
        ...prev,
        directions: next.planned_directions ?? prev.directions,
        completedDirections: next.directions_completed ?? prev.completedDirections,
        searchCalls: next.search_calls ?? prev.searchCalls,
      }))
    }
  }, [])

  const subscribe = useCallback(
    (runId: string) => {
      let attempt = 0
      const poll = async () => {
        while (!stoppedRef.current && runIdRef.current === runId) {
          try {
            const response = await fetch(
              `/api/brandagent/api/v1/consumer/research/${runId}/events`,
              {
                headers: { 'Last-Event-ID': String(lastEventIdRef.current) },
              },
            )
            if (!response.ok || !response.body) throw new Error(`EVENT_STREAM_${response.status}`)
            attempt = 0
            const reader = response.body.getReader()
            const decoder = new TextDecoder()
            let buffer = ''
            let sawTerminal = false
            while (true) {
              const { done, value } = await reader.read()
              if (done) break
              buffer += decoder.decode(value, { stream: true })
              const frames = buffer.split('\n\n')
              buffer = frames.pop() ?? ''
              for (const frame of frames) {
                if (frame.startsWith(':')) continue
                const id = Number(frame.match(/^id: (.+)$/m)?.[1] ?? NaN)
                const type = frame.match(/^event: (.+)$/m)?.[1] ?? 'message'
                const raw = frame.match(/^data: (.+)$/m)?.[1]
                if (!Number.isFinite(id) || !raw) continue
                lastEventIdRef.current = Math.max(lastEventIdRef.current, id)
                if (!RESEARCH_EVENT.test(type)) continue
                let payload: Record<string, unknown> = {}
                try {
                  payload = (JSON.parse(raw) as { data?: Record<string, unknown> })?.data ?? {}
                } catch {
                  payload = {}
                }
                if (type.startsWith('consumer.research.planned')) {
                  setProgress(prev => ({
                    ...prev,
                    directions: (payload.directions as string[]) ?? prev.directions,
                  }))
                } else if (type.startsWith('consumer.research.direction_done')) {
                  setProgress(prev => ({ ...prev, completedDirections: prev.completedDirections + 1 }))
                } else if (
                  type.startsWith('consumer.research.completed') ||
                  type.startsWith('consumer.research.failed') ||
                  type.startsWith('consumer.research.canceled')
                ) {
                  sawTerminal = true
                  const fresh = await getDeepResearch(runId)
                  applyRun(fresh)
                  if (type.includes('failed')) {
                    setMessage('调研中断，已完成的部分已保留。')
                  } else if (type.includes('canceled')) {
                    setMessage('调研已取消。已完成方向的结果已保留。')
                  }
                  return
                }
              }
            }
            // the stream ended without a terminal event (server restart,
            // proxy timeout): poll the run once; a terminal state stops
            // the loop, otherwise the reconnect backoff below applies —
            // never a tight refetch loop against a closed stream.
            const settled = await getDeepResearch(runId)
            if (['succeeded', 'failed', 'canceled'].includes(settled.status)) {
              applyRun(settled)
              return
            }
            if (sawTerminal) return
          } catch {
            if (stoppedRef.current || runIdRef.current !== runId) return
            const delay = Math.min(30_000, 1_000 * 2 ** attempt)
            attempt += 1
            await new Promise<void>(resolve => setTimeout(resolve, delay))
          }
        }
      }
      void poll()
    },
    [applyRun],
  )

  const start = useCallback(
    async (question: string, audience: string, scope: string) => {
      if (busy || phase === 'running' || phase === 'starting') return
      setBusy(true)
      setMessage(null)
      setPhase('starting')
      setProgress({ directions: [], completedDirections: 0, searchCalls: 0 })
      setJoinedCards(new Set())
      // reset() parks the SSE loop via stoppedRef; a later start() must
      // revive it or the new run's subscription exits before the first event
      stoppedRef.current = false
      try {
        const key = `research-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
        const created = await startDeepResearch(question, audience, scope, key)
        runIdRef.current = created.run_id
        lastEventIdRef.current = 0
        setRun(created)
        setPhase('running')
        setMessage(
          `调研已开始，预计消耗约 ${(created.estimated_tokens / 1000).toFixed(0)}K 额度，通常几分钟内完成。期间可以随时取消。`,
        )
        subscribe(created.run_id)
      } catch (error) {
        setPhase('idle')
        setMessage(error instanceof Error ? error.message : '调研发起失败，请稍后再试。')
      } finally {
        setBusy(false)
      }
    },
    [busy, phase, subscribe],
  )

  const cancel = useCallback(async () => {
    const runId = runIdRef.current
    if (!runId || busy) return
    setBusy(true)
    try {
      const key = `cancel-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
      const canceled = await cancelDeepResearch(runId, key)
      // the SSE loop may already be gone; apply directly
      if (canceled.status === 'canceled' || canceled.status === 'succeeded') {
        applyRun(canceled)
      }
      setMessage('正在取消——已完成方向的结果会保留。')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '取消失败，请重试。')
    } finally {
      setBusy(false)
    }
  }, [applyRun, busy])

  const joinCard = useCallback(
    async (cardIndex: number, taskId?: string | null) => {
      const runId = runIdRef.current
      if (!runId) return null
      if (joinedCards.has(cardIndex)) return null
      setBusy(true)
      try {
        const key = `join-${Date.now()}-${cardIndex}`
        const result = await joinResearchCard(runId, cardIndex, taskId ?? null, key)
        setJoinedCards(prev => new Set(prev).add(cardIndex))
        return result
      } catch (error) {
        setMessage(error instanceof Error ? error.message : '加入素材失败，请重试。')
        return null
      } finally {
        setBusy(false)
      }
    },
    [joinedCards],
  )

  const reset = useCallback(() => {
    stoppedRef.current = true
    runIdRef.current = null
    setPhase('idle')
    setRun(null)
    setProgress({ directions: [], completedDirections: 0, searchCalls: 0 })
    setJoinedCards(new Set())
    setMessage(null)
    setBusy(false)
  }, [])

  return { phase, run, progress, busy, message, start, cancel, reset, joinCard, joinedCards }
}

export type { ResearchCandidateCard, ResearchRun }
