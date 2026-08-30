'use client'

/**
 * Write page — the connected consumer journey (plan tasks 7-12 + audit
 * fixes for the "never wired" main loop):
 * - the core idea comes from the SERVER project (the URL hash carrier was
 *   removed: direct opens and bookmarks used to show a stale/fallback idea);
 * - the material drawer is rendered with real excerpts and can link one
 *   to this project (it previously existed only in its own test file);
 * - an empty draft offers real first-draft generation from the core idea
 *   and linked materials (POST /draft/generate + apply-candidate);
 * - the pre-publish review bubbles come from the preview endpoint's
 *   deterministic review rows (the page used to hard-wire bubbles={[]}).
 */

import { useParams } from 'next/navigation'
import { useCallback, useEffect, useRef, useState } from 'react'

import { ConsumerEditorClient } from '@/components/consumer/editor/ConsumerEditorClient'
import type { ConsumerEditorHandle } from '@/components/consumer/editor/ConsumerEditor'
import { MaterialDrawer } from '@/components/consumer/materials/MaterialDrawer'
import { PlatformPreview } from '@/components/consumer/preview/PlatformPreview'
import { PrePublishReview, type ReviewBubble } from '@/components/consumer/preview/PrePublishReview'
import { PrimaryActionBar } from '@/components/consumer/preview/PrimaryActionBar'
import { getConsumerProject } from '@/lib/api/consumer'
import {
  acceptConsumerSuggestion,
  getConsumerDraft,
  proposeConsumerSuggestion,
  saveConsumerDraft,
  generateDraftCandidate,
  applyDraftCandidate,
} from '@/lib/api/consumer-drafts'
import { brandFlowRequest } from '@/lib/api/brandflow'
import type { ConsumerDraftApi } from '@/hooks/useConsumerDraft'
import { usePlatformVariants } from '@/hooks/usePlatformVariants'
import { useConsumerMaterials } from '@/hooks/useConsumerMaterials'
import styles from '@/components/consumer/editor/consumer-editor.module.css'
import materialStyles from '@/components/consumer/materials/consumer-materials.module.css'

const api: ConsumerDraftApi = {
  getDraft: getConsumerDraft,
  saveDraft: saveConsumerDraft,
  proposeSuggestion: proposeConsumerSuggestion as unknown as ConsumerDraftApi['proposeSuggestion'],
  acceptSuggestion: acceptConsumerSuggestion as unknown as ConsumerDraftApi['acceptSuggestion'],
}

function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export default function ProjectWritePage() {
  const routeParams = useParams<{ projectId: string }>()
  const projectId = routeParams.projectId
  const editorRef = useRef<ConsumerEditorHandle>(null)
  const variants = usePlatformVariants(projectId)
  const materials = useConsumerMaterials()

  const [project, setProject] = useState<{ title: string; core_idea: string } | null>(null)
  const [projectError, setProjectError] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [draftText, setDraftText] = useState('')
  const [generating, setGenerating] = useState(false)
  const [generateError, setGenerateError] = useState<string | null>(null)

  // the project payload is the authority for the core idea
  useEffect(() => {
    let cancelled = false
    getConsumerProject(projectId)
      .then(data => {
        if (!cancelled) setProject({ title: data.title, core_idea: data.core_idea })
      })
      .catch(error => {
        if (!cancelled) setProjectError(error instanceof Error ? error.message : '项目暂时打不开。')
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  // track draft emptiness so the empty state can offer real generation
  useEffect(() => {
    let cancelled = false
    getConsumerDraft(projectId)
      .then(data => {
        if (!cancelled) setDraftText((data.plain_text ?? '').trim())
      })
      .catch(() => {
        /* draft may not exist yet; the editor creates one on first save */
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  // the drawer lists every ready excerpt in the workspace
  useEffect(() => {
    void materials.loadAllExcerpts()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const generateFirstDraft = useCallback(async () => {
    setGenerating(true)
    setGenerateError(null)
    try {
      const { candidate, base_revision: baseRevision } = await generateDraftCandidate(projectId, newIdempotencyKey())
      // revision compare-and-swap: if the user typed while generating,
      // the server keeps the user's newer draft and reports a conflict
      await applyDraftCandidate(projectId, candidate.content_version_id, baseRevision)
      await editorRef.current?.reloadDraft()
      setDraftText('applied')
    } catch (error) {
      const message = error instanceof Error ? error.message : '生成暂时不可用，稍后再试。'
      setGenerateError(message.includes('REVISION_CONFLICT') || message.includes('稿件在别处有更新')
        ? '你刚编辑过稿纸，初稿已存为候选。继续编辑你的版本，或刷新后选择应用候选稿。'
        : message)
    } finally {
      setGenerating(false)
    }
  }, [projectId])

  const linkExcerpt = useCallback(
    (excerptId: string) => {
      void materials.linkToProject(projectId, excerptId)
    },
    [materials, projectId],
  )

  const handleAdopt = async () => {
    await editorRef.current?.adoptCurrent()
    await variants.reload()
  }

  const reviewBubbles: ReviewBubble[] = variants.state.reviewBubbles ?? []

  if (projectError) {
    return (
      <div className={styles.writeLayout}>
        <div className={materialStyles.state} role="alert">
          <p>{projectError}</p>
        </div>
      </div>
    )
  }

  return (
    <div className={styles.writeLayout} data-testid="write-layout">
      <ConsumerEditorClient
        handleRef={editorRef}
        projectId={projectId}
        coreIdea={project?.core_idea ?? ''}
        api={api}
      />
      <aside className={styles.writeRail} data-testid="write-rail">
        <MaterialDrawer
          materials={materials.excerpts}
          open={drawerOpen}
          onToggle={() => setDrawerOpen(previous => !previous)}
          loading={materials.loading}
          error={materials.error ? { code: materials.error.code, message: materials.error.message } : null}
          onRetry={() => void materials.refresh()}
          onLink={linkExcerpt}
          linkStates={materials.linkStates}
        />
        {draftText === '' && (
          <section className={materialStyles.state}>
            <p>稿纸还是空的。基于核心观点和已关联素材，先生成一版初稿试试。</p>
            <button
              type="button"
              className="consumer-primary-button"
              disabled={generating}
              onClick={() => void generateFirstDraft()}
            >
              {generating ? '正在写初稿…' : '生成初稿'}
            </button>
            {generateError && <p role="alert">{generateError}</p>}
          </section>
        )}
        <PlatformPreview
          state={variants.state}
          onGenerate={() => void variants.generate()}
          onRegenerate={channel => void variants.regenerate(channel)}
          onAdopt={() => void handleAdopt()}
        />
        <PrePublishReview bubbles={reviewBubbles} />
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
