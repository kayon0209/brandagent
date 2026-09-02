'use client'

/**
 * useConsumerProjectEvents — SSE subscription for one consumer project
 * (upgrade plan §7.4: long tasks surface progress via task_events + SSE;
 * the page reacts by precisely invalidating the affected slice — variants,
 * materials, drafts — never by blind full refresh).
 *
 * Transport contract mirrors the BrandFlow task stream: `id:` cursor with
 * Last-Event-ID resume, versioned envelope in `data:`, 5s heartbeat
 * comments from the server. Reconnect uses exponential backoff (1s → 30s)
 * with the cursor, so a dropped connection replays only what was missed.
 */

import { useEffect, useRef } from 'react'

export type ConsumerProjectEvent = {
  id: number
  type: string
  payload: Record<string, unknown>
}

const EVENT_TYPES = {
  // event names are the constants written by agent-api application layer:
  // consumer_projects.py / draft_generation.py / drafts.py /
  // platform_variants.py / materials.py — update BOTH sides on change.
  draftCandidateReady: /^consumer\.draft\.candidate_ready\.v\d+$/,
  draftAdopted: /^consumer\.draft\.adopted\.v\d+$/,
  excerptLinked: /^consumer\.project\.excerpt\.linked\.v\d+$/,
  excerptUnlinked: /^consumer\.project\.excerpt\.unlinked\.v\d+$/,
  projectUpdated: /^consumer\.project\.updated\.v\d+$/,
  materialDistilled: /^consumer\.material\.distilled\.v\d+$/,
  materialImported: /^consumer\.material\.imported\.v\d+$/,
  materialFailed: /^consumer\.material\.failed\.v\d+$/,
  variantGenerated: /^consumer\.variant\.generated\.v\d+$/,
  variantFailed: /^consumer\.variant\.failed\.v\d+$/,
} as const

export type ConsumerEventInterest = keyof typeof EVENT_TYPES

function parseFrame(frame: string): ConsumerProjectEvent | null {
  const id = Number(frame.match(/^id: (.+)$/m)?.[1] ?? NaN)
  const type = frame.match(/^event: (.+)$/m)?.[1] ?? 'message'
  const raw = frame.match(/^data: (.+)$/m)?.[1]
  if (!Number.isFinite(id) || !raw) return null
  let payload: Record<string, unknown> = {}
  try {
    const envelope = JSON.parse(raw) as { data?: Record<string, unknown> }
    payload = envelope?.data ?? {}
  } catch {
    payload = {}
  }
  return { id, type, payload }
}

export function useConsumerProjectEvents(
  projectId: string,
  interests: Partial<Record<ConsumerEventInterest, (event: ConsumerProjectEvent) => void>>,
) {
  const handlersRef = useRef(interests)
  handlersRef.current = interests

  useEffect(() => {
    if (!projectId) return
    const controller = new AbortController()
    let lastEventId = 0
    let attempt = 0
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let stopped = false

    const run = async () => {
      while (!stopped) {
        try {
          const response = await fetch(
            `/api/brandagent/api/v1/consumer/projects/${projectId}/events`,
            {
              headers: { 'Last-Event-ID': String(lastEventId) },
              signal: controller.signal,
            },
          )
          if (!response.ok || !response.body) throw new Error(`EVENT_STREAM_${response.status}`)
          attempt = 0
          const reader = response.body.getReader()
          const decoder = new TextDecoder()
          let buffer = ''
          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            buffer += decoder.decode(value, { stream: true })
            const frames = buffer.split('\n\n')
            buffer = frames.pop() ?? ''
            for (const frame of frames) {
              if (frame.startsWith(':')) continue // heartbeat comment
              const event = parseFrame(frame)
              if (!event) continue
              lastEventId = Math.max(lastEventId, event.id)
              const handlers = handlersRef.current
              for (const key of Object.keys(EVENT_TYPES) as ConsumerEventInterest[]) {
                if (EVENT_TYPES[key].test(event.type)) handlers[key]?.(event)
              }
            }
          }
        } catch {
          if (stopped) return
          // exponential backoff 1s → 30s; the cursor keeps missed events replayable
          const delay = Math.min(30_000, 1_000 * 2 ** attempt)
          attempt += 1
          await new Promise<void>(resolve => {
            retryTimer = setTimeout(resolve, delay)
          })
        }
      }
    }

    void run()
    return () => {
      stopped = true
      controller.abort()
      if (retryTimer) clearTimeout(retryTimer)
    }
  }, [projectId])
}
