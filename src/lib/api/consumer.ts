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
  MaterialImportKind,
} from '@/types/consumer.types'
import { BrandFlowApiError, brandFlowRequest } from '@/lib/api/brandflow'

export interface MaterialListItem extends ConsumerMaterialDocument {
  excerpt_count: number
  created_at?: string
  /** round-3g D6: import kind + provenance */
  document_type: MaterialImportKind
  source_url?: string | null
  original_filename?: string | null
  /** round-3g D6: last time an excerpt of this material was linked to a project */
  last_used_at?: string | null
  /** v4 P1-1: first 120 chars of the first chunk, verbatim — for the card preview */
  excerpt_preview?: string | null
  /** v4 P1-1: number of distinct projects that have linked an excerpt of this doc */
  linked_projects_count?: number
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
      excerpt_count?: number
      last_used_at?: string | null
      document_type?: MaterialImportKind
      source_url?: string | null
      original_filename?: string | null
      excerpt_preview?: string | null
      linked_projects_count?: number
    }>
  }>('/api/v1/consumer/materials')

  return {
    items: documents.items.map(document => ({
      document_id: document.document_id,
      document_name: document.document_name,
      status: document.status as MaterialListItem['status'], // real server status passthrough
      // round-3g D6: excerpt_count / last_used_at are derived server-side
      // from the project_material_links join — never faked on the client
      excerpt_count: document.excerpt_count ?? 0,
      last_used_at: document.last_used_at ?? null,
      created_at: document.created_at,
      // round-3g D6: import kind + provenance passthrough (legacy rows read as text)
      document_type: (document.document_type ?? 'text') as MaterialImportKind,
      source_url: document.source_url ?? null,
      original_filename: document.original_filename ?? null,
      // v4 P1-1: card preview + linkage — derived server-side, never faked
      excerpt_preview: document.excerpt_preview ?? null,
      linked_projects_count: document.linked_projects_count ?? 0,
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

/** round-3g D6: file import — multipart to the /upload endpoint; the
 * server stamps document_type=file with original_filename provenance. */
export async function importMaterialFile(
  filename: string,
  content: string,
  idempotencyKey: string
): Promise<MaterialImportResult> {
  const form = new FormData()
  form.append('file', new Blob([content], { type: 'text/plain' }), filename)
  return brandFlowRequest<MaterialImportResult>('/api/v1/consumer/materials/upload', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: form,
  })
}

/** round-3g D6: save-a-link — the server fetches the page and stores the
 * readable text with the URL as provenance; failures are honest errors. */
export async function importMaterialUrl(
  url: string,
  idempotencyKey: string
): Promise<MaterialImportResult> {
  return brandFlowRequest<MaterialImportResult>('/api/v1/consumer/materials/url', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ url }),
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
