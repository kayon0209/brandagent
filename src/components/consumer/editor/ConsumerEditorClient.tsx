'use client'

/**
 * Browser-only loader for the tiptap manuscript editor.
 *
 * SSR cannot construct a tiptap Editor (no window), so the write page
 * imports this wrapper (audit fix). P0-2 regression fix: Next 14's
 * next/dynamic does not forward refs to the loaded function component,
 * which silently dropped the whole editor subtree (no .ProseMirror, no
 * core-idea block) with zero console errors. Fix: mount the dynamic
 * component WITHOUT a ref, and expose the imperative handle through a
 * ref-object prop instead — the page reads editorHandle.current.
 */

import dynamic from 'next/dynamic'
import { useEffect, useRef, type RefObject } from 'react'

import type { ConsumerEditorHandle, EditorStatusPayload } from './ConsumerEditor'
import type { ConsumerDraftApi } from '@/hooks/useConsumerDraft'

const Inner = dynamic(
  () => import('./ConsumerEditor').then(module_ => {
    // wrap so the dynamically loaded tree receives the handle ref-object
    // directly as a prop (refs never cross the next/dynamic boundary)
    function WithHandle(props: Omit<ConsumerEditorClientProps, 'handleRef'> & {
      handleRefObj?: RefObject<ConsumerEditorHandle | null>
    }) {
      const { handleRefObj, ...rest } = props
      return <module_.ConsumerEditorWithHandle {...rest} handleRefObj={handleRefObj} />
    }
    return { default: WithHandle }
  }),
  { ssr: false, loading: () => <p>正在打开稿纸…</p> },
)

export interface ConsumerEditorClientProps {
  projectId: string
  coreIdea: string
  api: ConsumerDraftApi
  handleRef: React.RefObject<ConsumerEditorHandle | null>
  onAdopted?: () => void
  onStatus?: (status: EditorStatusPayload) => void
  onSaveCoreIdea?: (coreIdea: string) => Promise<void>
}

export function ConsumerEditorClient(props: ConsumerEditorClientProps) {
  const { handleRef, ...rest } = props
  return <Inner {...rest} handleRefObj={handleRef} />
}
