/**
 * Consumer C-end view models (upgrade plan task 7).
 *
 * These are UI-facing types: Chinese semantics, no task/workflow/approval
 * vocabulary leaks from the B2B domain.
 */

export interface ConsumerMaterialDocument {
  document_id: string
  document_name: string
  status: 'distilled' | 'duplicate' | 'needs_distillation' | 'needs_review' | 'processing'
}

export interface ConsumerMaterialExcerpt {
  excerpt_id: string
  excerpt_type: 'quote' | 'claim' | 'example' | 'voice_sample'
  summary: string
  excerpt_text: string
  tags: string[]
  status: 'ready' | 'needs_review' | 'rejected'
  provenance_hash: string
  document_id: string
  chunk_id: string
  created_by_type: 'human' | 'model'
}

export interface ConsumerMaterialDocumentView {
  document: ConsumerMaterialDocument & {
    document_type: string
    version: string
    authority_level: string
    checksum: string
  }
  chunks: Array<{ chunk_id: string; chunk_index: number; content: string }>
  excerpts: ConsumerMaterialExcerpt[]
}

export type MaterialLinkState = 'unlinked' | 'linking' | 'linked' | 'failed'
