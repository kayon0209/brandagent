'use client'

/**
 * Write page (consumption plan tasks 9-10 + Phase 5 review fixes):
 * - "采用这版" adopts through the editor handle so the REAL post-flush
 *   revision is used (review P0: hardcoded baseRevision:0 broke adopt);
 * - the right rail follows the warm baseline with a soft left divider.
 */

import { use, useRef } from 'react'

import { ConsumerEditor, type ConsumerEditorHandle } from '@/components/consumer/editor/ConsumerEditor'
import { PlatformPreview } from '@/components/consumer/preview/PlatformPreview'
import { PrePublishReview } from '@/components/consumer/preview/PrePublishReview'
import { PrimaryActionBar } from '@/components/consumer/preview/PrimaryActionBar'
import {
  acceptConsumerSuggestion,
  getConsumerDraft,
  proposeConsumerSuggestion,
  saveConsumerDraft,
} from '@/lib/api/consumer-drafts'
import { brandFlowRequest } from '@/lib/api/brandflow'
import type { ConsumerDraftApi } from '@/hooks/useConsumerDraft'
import { usePlatformVariants } from '@/hooks/usePlatformVariants'
import styles from '@/components/consumer/editor/consumer-editor.module.css'

const api: ConsumerDraftApi = {
  getDraft: getConsumerDraft,
  saveDraft: saveConsumerDraft,
  proposeSuggestion: proposeConsumerSuggestion as unknown as ConsumerDraftApi['proposeSuggestion'],
  acceptSuggestion: acceptConsumerSuggestion as unknown as ConsumerDraftApi['acceptSuggestion'],
}

export default function ProjectWritePage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = use(params)
  const editorRef = useRef<ConsumerEditorHandle>(null)
  const variants = usePlatformVariants(projectId)
  // core idea arrives from the project payload; MVP reads it from URL hash
  const coreIdea = decodeURIComponent(typeof window !== 'undefined' ? window.location.hash.slice(1) : '') || '我的核心观点'

  const handleAdopt = async () => {
    // flushes pending autosave, adopts the real revision, reloads the draft
    await editorRef.current?.adoptCurrent()
    await variants.reload()
  }

  return (
    <div className={styles.writeLayout} data-testid="write-layout">
      <ConsumerEditor
        ref={editorRef}
        projectId={projectId}
        coreIdea={coreIdea}
        api={api}
      />
      <aside className={styles.writeRail} data-testid="write-rail">
        <PlatformPreview
          state={variants.state}
          onGenerate={() => void variants.generate()}
          onRegenerate={channel => void variants.regenerate(channel)}
          onAdopt={() => void handleAdopt()}
        />
        <PrePublishReview bubbles={[]} />
        <PrimaryActionBar
          onAdopt={() => void handleAdopt()}
          onRegenerate={() => void variants.regenerate()}
          onPrepareExport={() =>
            void brandFlowRequest(`/api/v1/consumer/projects/${projectId}/export/prepare`, { method: 'POST' })
          }
        />
      </aside>
    </div>
  )
}
