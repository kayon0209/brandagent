'use client'

import { use } from 'react'

import { ConsumerEditor } from '@/components/consumer/editor/ConsumerEditor'
import {
  acceptConsumerSuggestion,
  getConsumerDraft,
  proposeConsumerSuggestion,
  saveConsumerDraft,
} from '@/lib/api/consumer-drafts'
import type { ConsumerDraftApi } from '@/hooks/useConsumerDraft'

const api: ConsumerDraftApi = {
  getDraft: getConsumerDraft,
  saveDraft: saveConsumerDraft,
  proposeSuggestion: proposeConsumerSuggestion as unknown as ConsumerDraftApi['proposeSuggestion'],
  acceptSuggestion: acceptConsumerSuggestion as unknown as ConsumerDraftApi['acceptSuggestion'],
}

export default function ProjectWritePage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = use(params)
  // core idea arrives from the project payload; MVP reads it from URL state 'idea'
  const coreIdea = decodeURIComponent(typeof window !== 'undefined' ? window.location.hash.slice(1) : '') || '我的核心观点'

  return <ConsumerEditor projectId={projectId} coreIdea={coreIdea} api={api} />
}
