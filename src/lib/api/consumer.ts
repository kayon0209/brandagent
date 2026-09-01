/**
 * Consumer material API client (upgrade plan task 7).
 *
 * Rides the authenticated BFF (/api/brandagent) with the shared envelope
 * semantics. Only the endpoints the MVP drawer and materials page need.
 */

import type {
  ConsumerMaterialDocument,
  ConsumerMaterialDocumentView,
  ConsumerMaterialExcerpt,
} from '@/types/consumer.types'
import { BrandFlowApiError, brandFlowRequest } from '@/lib/api/brandflow'

export interface MaterialListItem extends ConsumerMaterialDocument {
  excerpt_count: number
  created_at?: string
}

export interface MaterialImportResult {
  status: 'distilled' | 'duplicate' | 'needs_distillation' | 'needs_review'
  document_id: string
  checksum: string
  request_id: string
}

export async function listMaterials(): Promise<{ items: MaterialListItem[] }> {
  const documents = await brandFlowRequest<{
    items: Array<{
      document_id: string
      document_name: string
      status: string
      checksum?: string
      created_at?: string
    }>
  }>('/api/v1/consumer/materials')

  return {
    items: documents.items.map(document => ({
      document_id: document.document_id,
      document_name: document.document_name,
      status: document.status as MaterialListItem['status'], // real server status passthrough
      excerpt_count: 0, // excerpt count arrives with the per-document view
      created_at: document.created_at,
    })),
  }
}

export async function getMaterialView(documentId: string): Promise<ConsumerMaterialDocumentView> {
  return brandFlowRequest<ConsumerMaterialDocumentView>(
    `/api/v1/consumer/materials/${documentId}`
  )
}

export async function getMaterialExcerpts(documentId: string): Promise<{ items: ConsumerMaterialExcerpt[] }> {
  return brandFlowRequest<{ items: ConsumerMaterialExcerpt[] }>(
    `/api/v1/consumer/materials/${documentId}/excerpts`
  )
}

export async function importMaterialText(
  text: string,
  name: string,
  idempotencyKey: string
): Promise<MaterialImportResult> {
  return brandFlowRequest<MaterialImportResult>('/api/v1/consumer/materials/text', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ text, name }),
  })
}

export async function linkMaterialToProject(
  projectId: string,
  excerptId: string,
  idempotencyKey: string
): Promise<{ linked: boolean }> {
  return brandFlowRequest<{ linked: boolean }>(
    `/api/v1/consumer/projects/${projectId}/materials/${excerptId}`,
    {
      method: 'PUT',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ pinned: false }),
    }
  )
}

export async function getConsumerProject(
  projectId: string,
): Promise<{
  task_id: string
  title: string
  core_idea: string
  writing_intent: string
  active_master_version_id: string | null
  linked_excerpts?: { excerpt_id: string }[]
}> {
  return brandFlowRequest(`/api/v1/consumer/projects/${projectId}`)
}

export async function updateConsumerProject(
  projectId: string,
  patch: { title?: string; core_idea?: string; writing_intent?: string },
): Promise<{ task_id: string; title: string; core_idea: string; writing_intent: string }> {
  return brandFlowRequest(`/api/v1/consumer/projects/${projectId}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export { BrandFlowApiError }
