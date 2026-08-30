'use client'

/**
 * consumer BFF client for project/draft/suggestion routes (task 8/9/10).
 * All calls go through the Next BFF envelope helper — never straight to FastAPI.
 */

import { brandFlowRequest } from '@/lib/api/brandflow'

export interface ServerDraft {
  task_id: string
  revision: number
  document: { blocks: unknown[] }
  plain_text: string
}

export async function getConsumerDraft(projectId: string): Promise<ServerDraft> {
  const payload = await brandFlowRequest<{ task_id: string; revision: number; document: { blocks: unknown[] }; plain_text: string }>(
    `/api/v1/consumer/projects/${projectId}/draft`,
  )
  return payload
}

export async function saveConsumerDraft(
  projectId: string,
  payload: { document: { blocks: unknown[] }; plainText: string; baseRevision: number },
): Promise<{ revision: number }> {
  return brandFlowRequest<{ revision: number }>(`/api/v1/consumer/projects/${projectId}/draft`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function proposeConsumerSuggestion(input: {
  projectId: string
  action: string
  selectedText: string
  blockId: string
  startOffset: number
  endOffset: number
  baseRevision: number
}): Promise<{ suggestion_id: string; suggested_text: string }> {
  return brandFlowRequest<{ suggestion_id: string; suggested_text: string }>(
    `/api/v1/consumer/projects/${input.projectId}/suggestions`,
    {
      method: 'POST',
      body: JSON.stringify({
        action: input.action,
        selectedText: input.selectedText,
        blockId: input.blockId,
        startOffset: input.startOffset,
        endOffset: input.endOffset,
        baseRevision: input.baseRevision,
      }),
    },
  )
}

export async function acceptConsumerSuggestion(input: {
  projectId: string
  suggestionId: string
  baseRevision: number
}): Promise<{ revision: number }> {
  return brandFlowRequest<{ revision: number }>(
    `/api/v1/consumer/projects/${input.projectId}/suggestions/${input.suggestionId}/accept`,
    {
      method: 'POST',
      body: JSON.stringify({ baseRevision: input.baseRevision }),
    },
  )
}

export interface DraftCandidate {
  content_version_id: string
  task_id: string
  content: string
}

export async function generateDraftCandidate(
  projectId: string,
  idempotencyKey: string,
): Promise<{ candidate: DraftCandidate; base_revision: number }> {
  return brandFlowRequest<{ candidate: DraftCandidate; base_revision: number }>(
    `/api/v1/consumer/projects/${projectId}/draft/generate`,
    {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
    },
  )
}

export async function applyDraftCandidate(
  projectId: string,
  contentVersionId: string,
  baseRevision: number,
): Promise<{ revision: number; task_id: string }> {
  return brandFlowRequest<{ revision: number; task_id: string }>(
    `/api/v1/consumer/projects/${projectId}/draft/apply-candidate`,
    {
      method: 'POST',
      body: JSON.stringify({ contentVersionId, baseRevision }),
    },
  )
}
