'use client'

import { use } from 'react'

import { ConsumerEditor } from '@/components/consumer/editor/ConsumerEditor'
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

async function adoptDraft(projectId: string, baseRevision: number) {
  return brandFlowRequest(`/api/v1/consumer/projects/${projectId}/draft/adopt`, {
    method: 'POST',
    body: JSON.stringify({ baseRevision }),
  })
}

export default function ProjectWritePage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = use(params)
  // core idea arrives from the project payload; MVP reads it from URL hash
  const coreIdea = decodeURIComponent(typeof window !== 'undefined' ? window.location.hash.slice(1) : '') || '我的核心观点'
  const variants = usePlatformVariants(projectId)

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 340px', gap: '32px', alignItems: 'start' }}>
      <ConsumerEditor projectId={projectId} coreIdea={coreIdea} api={api} />
      <aside className={styles.shell} style={{ padding: '16px 0', background: 'transparent', minHeight: 'auto' }}>
        <PlatformPreview
          state={variants.state}
          onGenerate={() => void variants.generate()}
          onRegenerate={channel => void variants.regenerate(channel)}
          onAdopt={() => void adoptDraft(projectId, 0)}
        />
        <PrePublishReview bubbles={[]} />
        <PrimaryActionBar
          onAdopt={() => void adoptDraft(projectId, 0)}
          onRegenerate={() => void variants.regenerate()}
          onPrepareExport={() =>
            void brandFlowRequest(`/api/v1/consumer/projects/${projectId}/export/prepare`, { method: 'POST' })
          }
        />
      </aside>
    </div>
  )
}
