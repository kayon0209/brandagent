'use client'

/**
 * Write page — the confirmed index-v4 skeleton, fully wired:
 *
 *   topbar (60px)  brand · materials button+count · doc title · 准备发布
 *   workspace      editor column (canvas desk + 720px paper) | preview rail
 *   statusbar (28px) save state · word count | zoom controls
 *
 * Audit fixes landed here: the core idea comes from the server project
 * (no URL hash), the material drawer is a real overlay fed with workspace
 * excerpts, an empty draft offers real first-draft generation, and the
 * review bubbles come from the preview endpoint's deterministic rows.
 */

import { useParams } from 'next/navigation'
import { useCallback, useEffect, useRef, useState } from 'react'

import { ConsumerEditorClient } from '@/components/consumer/editor/ConsumerEditorClient'
import type { ConsumerEditorHandle, EditorStatusPayload } from '@/components/consumer/editor/ConsumerEditor'
import { SaveStatus, type SaveState } from '@/components/consumer/editor/SaveStatus'
import { ZoomControl } from '@/components/consumer/editor/ZoomControl'
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
  const [status, setStatus] = useState<EditorStatusPayload | null>(null)

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

  const onStatus = useCallback((payload: EditorStatusPayload) => {
    setStatus(payload)
  }, [])

  const generateFirstDraft = useCallback(async () => {
    setGenerating(true)
    setGenerateError(null)
    try {
      // bound the wait: a stuck backend must never leave the user on an
      // eternal "生成中" (runtime audit finding)
      const timeout = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('TIMEOUT')), 60_000),
      )
      const { candidate, base_revision: baseRevision } = await Promise.race([
        generateDraftCandidate(projectId, newIdempotencyKey()),
        timeout,
      ])
      // revision compare-and-swap: if the user typed while generating,
      // the server keeps the user's newer draft and reports a conflict
      await applyDraftCandidate(projectId, candidate.content_version_id, baseRevision)
      await editorRef.current?.reloadDraft()
      setDraftText('applied')
    } catch (error) {
      const message = error instanceof Error ? error.message : ''
      // machine errors must never surface raw (English provider text,
      // stack-ish detail) — map to spoken recovery guidance instead
      if (message.includes('REVISION_CONFLICT') || message.includes('稿件在别处有更新')) {
        setGenerateError('你刚编辑过稿纸，初稿已存为候选。继续编辑你的版本，或刷新后选择应用候选稿。')
      } else if (message.includes('QUOTA_EXCEEDED') || message.includes('额度')) {
        setGenerateError('本月 AI 额度已用完。写作和保存不受影响，下个月再生成初稿。')
      } else if (message.includes('TIMEOUT')) {
        setGenerateError('这次生成等得太久了，已停止等待。你的稿纸没有任何改动，可以再试一次。')
      } else {
        setGenerateError('初稿生成暂时不可用，你的稿纸没有任何改动。稍后再试一次。')
      }
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

  const handlePrepareExport = async () => {
    try {
      await brandFlowRequest(`/api/v1/consumer/projects/${projectId}/export/prepare`, { method: 'POST' })
      window.alert('导出快照已准备。发布前的最后检查请看右侧「发布前再看一眼」。')
    } catch (error) {
      window.alert(error instanceof Error ? error.message : '导出暂时不可用，稍后再试。')
    }
  }

  const reviewBubbles: ReviewBubble[] = variants.state.reviewBubbles ?? []

  if (projectError) {
    return (
      <div className={styles.shell}>
        <div className={materialStyles.state} role="alert">
          <p>{projectError}</p>
        </div>
      </div>
    )
  }

  return (
    <div className={styles.shell} data-testid="write-layout">
      <header className={styles.topbar}>
        <div className={styles.topbarLeft}>
          <span className={styles.brand}>BrandAgent</span>
          <button
            type="button"
            className={styles.materialsButton}
            aria-expanded={drawerOpen}
            onClick={() => setDrawerOpen(previous => !previous)}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
              <path d="M4 5h16v14H4z" />
              <path d="M8 9h8M8 13h6" />
            </svg>
            <span>素材</span>
            <span className={styles.materialsCount}>{materials.excerpts.length}</span>
          </button>
        </div>

        <div className={styles.documentTitle}>
          <strong className={styles.documentTitleStrong}>{project?.title ?? '…'}</strong>
          <span className={styles.documentTitleSpan}>写作台</span>
        </div>

        <div className={styles.topbarRight}>
          <button type="button" className={styles.preparePublish} onClick={() => void handlePrepareExport()}>
            准备发布
          </button>
        </div>
      </header>

      <div className={styles.workspace}>
        <div className={styles.editorColumn}>
          <ConsumerEditorClient
            handleRef={editorRef}
            projectId={projectId}
            coreIdea={project?.core_idea ?? ''}
            api={api}
            onStatus={onStatus}
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
        </div>

        <aside className={styles.writeRail} data-testid="write-rail">
          <div className={styles.railInner}>
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
              onPrepareExport={() => void handlePrepareExport()}
            />
          </div>
        </aside>
      </div>

      <footer className={styles.statusbar}>
        <span className={styles.statusCopy}>
          {status ? (
            <>
              <SaveStatus
                state={status.saveState as SaveState}
                onResolveConflict={() => status.resolveConflict()}
              />
              <span aria-hidden>·</span>
              <span className={styles.saveText}>{status.wordCount} 字</span>
            </>
          ) : (
            <span className={styles.saveText}>正在载入稿件…</span>
          )}
        </span>
        <div className={styles.statusZoom}>
          <ZoomControl
            zoom={status?.zoom ?? 1}
            minZoom={0.75}
            maxZoom={1.5}
            step={0.1}
            onZoomChange={zoom => status?.changeZoom(zoom)}
          />
        </div>
      </footer>

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
    </div>
  )
}
