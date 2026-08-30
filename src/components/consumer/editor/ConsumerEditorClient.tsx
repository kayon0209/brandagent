'use client'

/**
 * Browser-only loader for the tiptap manuscript editor.
 *
 * SSR cannot construct a tiptap Editor (no window), so the write page
 * imports this wrapper via next/dynamic with ssr:false (audit fix).
 */

import dynamic from 'next/dynamic'

import type { ConsumerEditorHandle, EditorStatusPayload } from './ConsumerEditor'
import type { ConsumerDraftApi } from '@/hooks/useConsumerDraft'

const Inner = dynamic(
  () => import('./ConsumerEditor').then(module_ => ({ default: module_.ConsumerEditor })),
  { ssr: false, loading: () => <p>正在打开稿纸…</p> },
)

export function ConsumerEditorClient(props: {
  projectId: string
  coreIdea: string
  api: ConsumerDraftApi
  handleRef: React.Ref<ConsumerEditorHandle>
  onAdopted?: () => void
  onStatus?: (status: EditorStatusPayload) => void
}) {
  const { handleRef, ...rest } = props
  return <Inner {...rest} ref={handleRef} />
}
