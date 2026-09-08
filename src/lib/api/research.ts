/**
 * Deep research API client (Phase 6, user-approved 2026-09-08).
 *
 * Rides the authenticated BFF like every other consumer call. The SSE
 * progress stream is consumed by the page through fetch + reader
 * (same pattern as useConsumerProjectEvents) — this module only owns
 * the request/response shapes.
 */

import { BrandFlowApiError, brandFlowRequest } from '@/lib/api/brandflow'

export interface ResearchCandidateCard {
  url: string
  title: string
  excerpt: string
  retrieved_at: string
  score?: number | null
  reachable: boolean
  excerpt_valid: boolean
}

export interface ResearchRun {
  run_id: string
  question: string
  audience: string
  scope_hint: string
  status: 'planned' | 'running' | 'succeeded' | 'failed' | 'canceled'
  planned_directions?: string[]
  candidate_cards?: ResearchCandidateCard[]
  synthesis?: string
  directions_completed?: number
  citations_valid?: number
  citations_invalid?: number
  search_calls?: number
  error?: string
  estimated_tokens?: number
  tokens_used?: number | null
  created_at?: string
  completed_at?: string | null
}

export interface StartResearchResult extends ResearchRun {
  estimated_tokens: number
}

export async function startDeepResearch(
  question: string,
  audience: string,
  scope: string,
  idempotencyKey: string,
): Promise<StartResearchResult> {
  return brandFlowRequest<StartResearchResult>(
    '/api/v1/consumer/research',
    {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ question, audience, scope }),
    },
  )
}

export async function getDeepResearch(runId: string): Promise<ResearchRun> {
  return brandFlowRequest<ResearchRun>(`/api/v1/consumer/research/${runId}`)
}

export async function listDeepResearch(): Promise<{ items: ResearchRun[] }> {
  return brandFlowRequest<{ items: ResearchRun[] }>('/api/v1/consumer/research')
}

export async function cancelDeepResearch(runId: string, idempotencyKey: string): Promise<ResearchRun> {
  return brandFlowRequest<ResearchRun>(`/api/v1/consumer/research/${runId}/cancel`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
  })
}

export interface JoinCardResult {
  document_id: string
  status: string
  url: string
  title: string
  task_id?: string
  excerpt_id?: string
}

export async function joinResearchCard(
  runId: string,
  cardIndex: number,
  taskId: string | null,
  idempotencyKey: string,
): Promise<JoinCardResult> {
  return brandFlowRequest<JoinCardResult>(
    `/api/v1/consumer/research/${runId}/cards/${cardIndex}/join`,
    {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ task_id: taskId }),
    },
  )
}

export { BrandFlowApiError }
