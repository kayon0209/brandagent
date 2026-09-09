'use client'

// Clerk-protected, data-driven page: prerender has no session, so a
// static export would bake the interception shell (prod 404 root
// cause). Render per-request like the middleware expects.
export const dynamic = 'force-dynamic'


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

import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useCallback, useEffect, useRef, useState } from 'react'
import { UserButton } from '@clerk/nextjs'

import { buildMaterialsHref } from '@/lib/navigation/materials'

import { ConsumerEditorClient } from '@/components/consumer/editor/ConsumerEditorClient'
import type { ConsumerEditorHandle, EditorStatusPayload } from '@/components/consumer/editor/ConsumerEditor'
import { SaveStatus, type SaveState } from '@/components/consumer/editor/SaveStatus'
import { ZoomControl } from '@/components/consumer/editor/ZoomControl'
import { MaterialDrawer } from '@/components/consumer/materials/MaterialDrawer'
import { PlatformPreview } from '@/components/consumer/preview/PlatformPreview'
import { PrePublishReview, type ReviewBubble } from '@/components/consumer/preview/PrePublishReview'
import { getConsumerProject, updateConsumerProject } from '@/lib/api/consumer'
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
import { useConsumerProjectEvents } from '@/hooks/useConsumerProjectEvents'
import styles from '@/components/consumer/editor/consumer-editor.module.css'
import materialStyles from '@/components/consumer/materials/consumer-materials.module.css'
import { newIdempotencyKey } from '@/lib/idempotency'

const api: ConsumerDraftApi = {
  getDraft: getConsumerDraft,
  saveDraft: saveConsumerDraft,
  proposeSuggestion: proposeConsumerSuggestion as unknown as ConsumerDraftApi['proposeSuggestion'],
  acceptSuggestion: acceptConsumerSuggestion as unknown as ConsumerDraftApi['acceptSuggestion'],
}

const WORKFLOW_STEPS = ['观点', '草稿', '平台优化', '发布']


export default function ProjectWritePage() {
  const routeParams = useParams<{ projectId: string }>()
  const projectId = routeParams?.projectId ?? ''
  const router = useRouter()
  const editorRef = useRef<ConsumerEditorHandle>(null)
  const variants = usePlatformVariants(projectId)
  const materials = useConsumerMaterials()

  const [project, setProject] = useState<{ title: string; core_idea: string } | null>(null)
  const [projectError, setProjectError] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [draftText, setDraftText] = useState('')
  // P1-9: one generate action = one idempotency key; the SAME action's
  // retries (timeout re-send, user retry click) reuse it so the model is
  // never called twice for one intent
  const generateKeyRef = useRef<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [generateError, setGenerateError] = useState<string | null>(null)
  const [status, setStatus] = useState<EditorStatusPayload | null>(null)
  // 诉求 2 (WYSIWYG, round-3b): the live draft text from the editor, so the
  // platform preview rail renders the creator's writing in real time
  // without waiting for "adopt → generate".
  const [liveText, setLiveText] = useState('')
  // X1/U7: honest progress narrative + success banner for first-draft
  const [generateProgress, setGenerateProgress] = useState<string | null>(null)
  const [generateBanner, setGenerateBanner] = useState<string | null>(null)
  // round-3g A3: spoken guidance from the secondary action bar
  const [assistGuidance, setAssistGuidance] = useState<string | null>(null)
  const runAssist = useCallback(
    async (action: 'expand' | 'shorten' | 'change_tone') => {
      setAssistGuidance(null)
      try {
        const message = await editorRef.current?.triggerAssist(action)
        if (message) setAssistGuidance(message)
      } catch {
        setAssistGuidance('这次操作没成功，你的稿子没有任何改动。可以再试一次。')
      }
    },
    [],
  )
  // R1: monthly quota visibility — invisible quota is quota users are
  // afraid to spend
  const [usage, setUsage] = useState<{ used: number; quota: number } | null>(null)

  const refreshUsage = useCallback(async () => {
    try {
      const { fetchConsumerUsage } = await import('@/lib/consumer-usage')
      const summary = await fetchConsumerUsage()
      setUsage({ used: summary.used, quota: summary.quota })
    } catch {
      setUsage(null) // quota display is best-effort, never blocking
    }
  }, [])

  useEffect(() => {
    void refreshUsage()
  }, [refreshUsage])

  // round-3g A4: quota urgency — <80% neutral; >=80% caramel with tooltip;
  // =100% blocks every generation-class button (writing/saving stay free)
  const usageRatio = usage && usage.quota > 0 ? usage.used / usage.quota : 0
  const quotaExhausted = usageRatio >= 1
  const quotaUrgent = usageRatio >= 0.8 && !quotaExhausted
  const quotaTooltip = quotaExhausted
    ? '本月额度已用完，写作与保存仍可用'
    : quotaUrgent
      ? `本月额度已用 ${Math.round(usageRatio * 100)}%，接近上限。写作与保存不受影响。`
      : `本月 AI 额度：已用 ${usage?.used ?? 0} / 共 ${usage?.quota ?? 0} tokens（写作和保存不消耗额度）`

  // the project payload is the authority for the core idea
  useEffect(() => {
    let cancelled = false
    getConsumerProject(projectId)
      .then(data => {
        if (cancelled) return
        setProject({ title: data.title, core_idea: data.core_idea })
        // excerpts linked on the SERVER show as linked in the drawer even
        // before this session links anything (P1-3: returning from the
        // materials page must show the real association state)
        const linked = data.linked_excerpts ?? []
        if (linked.length) {
          materials.seedLinkStates(Object.fromEntries(linked.map(e => [e.excerpt_id, 'linked' as const])))
        }
      })
      .catch(error => {
        if (!cancelled) setProjectError(error instanceof Error ? error.message : '项目暂时打不开。')
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  // N2: Esc closes the material drawer (WAI-ARIA drawer pattern); clicking
  // the manuscript area dismisses it too — an open drawer must never trap
  // the user into a second trip to the toggle button
  useEffect(() => {
    if (!drawerOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDrawerOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [drawerOpen])

  const onStatus = useCallback((payload: EditorStatusPayload) => {
    setStatus(payload)
    // 诉求 2: hand the live draft text to the platform preview rail so it
    // updates on every keystroke; the preview falls back to its own
    // skeleton when plainText is empty
    setLiveText(payload.plainText ?? '')
    // round-3g A3: the secondary action bar keys off draftText — it must
    // track LIVE typing, not just the initial load / first-draft apply
    setDraftText((payload.plainText ?? '').trim())
  }, [])

  // P1-3: explicit core-idea editing through the project PATCH API; the
  // local mirror updates ONLY after the server confirms, so generation
  // (first draft + variants) always reads the persisted value
  const saveCoreIdea = useCallback(
    async (coreIdea: string) => {
      await updateConsumerProject(projectId, { core_idea: coreIdea })
      setProject(previous => (previous ? { ...previous, core_idea: coreIdea } : previous))
    },
    [projectId],
  )

  // the empty drawer's 导入素材 navigates to the real import flow, carrying
  // this project as the return context so 素材页 can send the user back
  const importFromDrawer = useCallback(() => {
    void router.push(buildMaterialsHref(projectId))
  }, [projectId, router])

  const generateFirstDraft = useCallback(async () => {
    setGenerating(true)
    setGenerateError(null)
    setGenerateProgress(null)
    // U7: spoken progress narrative while the model reasons — the real
    // measured clean-sample latency is 1-3 minutes, so an honest
    // rotating copy beats a frozen button with no expectation
    const narrative = [
      '正在读你的核心观点和已关联素材…',
      '正在组织文章结构…',
      '正在写下第一段…',
      '还在写，长文需要一点时间…',
    ]
    let narrativeIndex = 0
    setGenerateProgress(narrative[0])
    const narrativeTimer = setInterval(() => {
      narrativeIndex = Math.min(narrativeIndex + 1, narrative.length - 1)
      setGenerateProgress(narrative[narrativeIndex])
    }, 20_000)
    try {
      // X1: the previous 60s cap misjudged normal reasoning runs (measured
      // clean-sample mean 118-157s) as failures and burned a second model
      // call on the retry. 180s bounds a genuinely stuck backend without
      // racing the normal path.
      const timeout = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('TIMEOUT')), 180_000),
      )
      if (!generateKeyRef.current) generateKeyRef.current = newIdempotencyKey()
      const result = await Promise.race([
        generateDraftCandidate(projectId, generateKeyRef.current),
        timeout,
      ])
      // P1-9 replay contract: a retry under the same key returns the
      // EXISTING candidate — adopt it instead of failing generically
      const candidate = result.candidate
      if (candidate?.content_version_id) {
        const baseRevision = result.base_revision ?? candidate.base_revision ?? 0
        // revision compare-and-swap: if the user typed while generating,
        // the server keeps the user's newer draft and reports a conflict
        await applyDraftCandidate(projectId, candidate.content_version_id, baseRevision)
        await editorRef.current?.reloadDraft()
        setDraftText('applied')
        setGenerateBanner('初稿已生成并放入稿纸。不满意可以选中任意句子让 AI 改写。')
        generateKeyRef.current = null // completed — next click is a new action
      } else {
        // replay with no recoverable candidate (e.g. the draft was adopted
        // already): just re-read the server state
        await editorRef.current?.reloadDraft()
        setDraftText('applied')
        generateKeyRef.current = null
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : ''
      // machine errors must never surface raw (English provider text,
      // stack-ish detail) — map to spoken recovery guidance instead
      if (message.includes('REVISION_CONFLICT') || message.includes('稿件在别处有更新')) {
        setGenerateError('你刚编辑过稿纸，初稿已存为候选。继续编辑你的版本，或刷新后选择应用候选稿。')
      } else if (message.includes('QUOTA_EXCEEDED') || message.includes('额度')) {
        setGenerateError('本月 AI 额度已用完。写作和保存不受影响，下个月再生成初稿。')
      } else if (message.includes('TIMEOUT')) {
        setGenerateError('这次生成未能确认结果。你的稿纸没有任何改动；提供方可能已执行请求，预估额度可能已计入。再次生成会作为一次新请求。')
      } else {
        setGenerateError('初稿生成暂时不可用，你的稿纸没有任何改动。提供方可能已执行请求，预估额度可能已计入；再次生成会作为一次新请求。')
      }
      generateKeyRef.current = null // failed+refunded — retry is a new action
    } finally {
      clearInterval(narrativeTimer)
      setGenerating(false)
      setGenerateProgress(null)
      void refreshUsage() // R1: the ledger moved — reflect it immediately
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const linkExcerpt = useCallback(
    (excerptId: string) => {
      void materials.linkToProject(projectId, excerptId)
    },
    [materials, projectId],
  )

  // §7.4 event stream: server-side progress (variant generation, material
  // distillation, draft adoption) invalidates exactly the affected slice —
  // a variant becoming ready refreshes the preview rail, a distilled
  // material refreshes the drawer; no blind full-page reloads
  useConsumerProjectEvents(projectId, {
    variantGenerated: () => void variants.reload(),
    variantFailed: () => void variants.reload(),
    draftAdopted: () => {
      void variants.reload()
    },
    materialDistilled: () => void materials.refresh(),
    materialImported: () => void materials.refresh(),
    materialFailed: () => void materials.refresh(),
  })

  const handleAdopt = async () => {
    await editorRef.current?.adoptCurrent()
    await variants.reload()
  }

  const handlePrepareExport = async () => {
    try {
      await brandFlowRequest(`/api/v1/consumer/projects/${projectId}/export/prepare`, { method: 'POST' })
      // X5: in-page banner instead of window.alert; the fail-closed
      // publish red line becomes SPOKEN policy, not hidden machinery
      setGenerateBanner(
        '导出快照已准备。真正发布到平台仍需你在渠道后台操作——BrandAgent 不会代替你发布，这是刻意的安全设计。',
      )
      document.querySelector('[data-testid="write-rail"]')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    } catch (error) {
      setGenerateError(error instanceof Error ? error.message : '导出暂时不可用，稍后再试。')
    }
  }

  const reviewBubbles: ReviewBubble[] = variants.state.reviewBubbles ?? []

  // round-3e (#3): publishable = a master exists AND at least one channel
  // has a generated variant. This gates the topbar's 准备发布 so the entry
  // never fires into an empty export.
  const publishableVariant =
    variants.state.status !== 'no_master' &&
    Object.values(variants.state.channels ?? {}).some(channel => Boolean(channel?.content?.trim()))
  const workflowStage = publishableVariant
    ? 3
    : variants.state.status !== 'no_master'
      ? 2
      : draftText.trim()
        ? 1
        : 0
  const autosaveCopy = status?.saveState === 'saved'
    ? '已自动保存'
    : status?.saveState === 'saving' || status?.saveState === 'dirty'
      ? '正在保存'
      : status?.saveState === 'error'
        ? '保存待重试'
        : '草稿'

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
          <Link href="/app" className={styles.topbarBack} data-testid="back-to-app">
            ← 返回
          </Link>
          <span className={styles.topbarDividerLine} aria-hidden />
          <span className={styles.topbarSection}>今天的写作台</span>
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

        <div className={styles.topbarCenter}>
          <span className={styles.cloudSave} data-testid="cloud-save">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <path d="M6.5 19a4.5 4.5 0 0 1-.4-8.98 6 6 0 0 1 11.6 1.4A3.8 3.8 0 0 1 17.5 19z" />
            </svg>
            <span>自动保存 · {autosaveCopy}</span>
          </span>
        </div>

        <div className={styles.topbarRight}>
          <button type="button" className={styles.previewButton} data-testid="jump-preview" onClick={() => document.querySelector('[data-testid="write-rail"]')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })}>
            预览
          </button>
          <button
            type="button"
            className={styles.preparePublish}
            disabled={!publishableVariant}
            title={publishableVariant ? undefined : '先在稿纸定稿并生成至少一个平台版本，才能准备发布'}
            onClick={() => void handlePrepareExport()}
          >
            准备发布
          </button>
          <UserButton afterSignOutUrl="/sign-in" />
        </div>
      </header>

      <div
        className={styles.workspace}
        onClick={() => {
          // N2: clicking into the manuscript dismisses an open drawer; the
          // drawer sits OUTSIDE this container so its own clicks never land
          // here — no stopPropagation games needed
          if (drawerOpen) setDrawerOpen(false)
        }}
      >
        <div className={styles.editorColumn}>
          <div className={styles.workspaceIntro} data-testid="manuscript-micro-tab">
            <div className={styles.workspaceCrumb}>
              <Link href="/app">← 返回</Link><span aria-hidden>／</span><span>今天的写作台</span>
            </div>
            <h1>{project?.title ?? '正在打开项目…'}</h1>
            {project?.core_idea && <p>{project.core_idea}</p>}
            <div className={styles.workflowStage} aria-label="内容工作流">
              {WORKFLOW_STEPS.map((step, index) => (
                <span key={step} data-active={index === workflowStage} data-complete={index < workflowStage}>
                  <i aria-hidden />{step}
                </span>
              ))}
              <small>· {autosaveCopy}</small>
            </div>
          </div>
          <ConsumerEditorClient
            handleRef={editorRef}
            projectId={projectId}
            coreIdea={project?.core_idea ?? ''}
            api={api}
            onStatus={onStatus}
            onSaveCoreIdea={saveCoreIdea}
            onOpenMaterials={() => setDrawerOpen(true)}
          />
          {/* round-3e (#4): the empty-draft + banner surfaces belong INSIDE
              the 720px paper column — a full-column white card above the
              gray desk read like a system notification. Wrap with the same
              max-width the manuscript gets. */}
          <div className={styles.editorExtras}>
            {/* round-3g A3: secondary action bar — lives with the manuscript
                once there IS a manuscript; every button has a behavior or
                an honest spoken guidance line (no dead buttons) */}
            {draftText !== '' && !generating && (
              <div className={styles.secondaryActionBar} data-testid="secondary-action-bar" role="toolbar" aria-label="稿件辅助操作">
                <button type="button" onClick={() => void runAssist('expand')}>扩写</button>
                <span aria-hidden>｜</span>
                <button type="button" onClick={() => void runAssist('shorten')}>精简</button>
                <span aria-hidden>｜</span>
                <button type="button" onClick={() => void runAssist('change_tone')}>换一种语气</button>
                <span aria-hidden>｜</span>
                <button
                  type="button"
                  disabled={quotaExhausted}
                  title={quotaExhausted ? '本月额度已用完，写作与保存仍可用' : undefined}
                  onClick={() => void variants.generate()}
                >
                  生成平台版本
                </button>
              </div>
            )}
            {assistGuidance && (
              <p role="status" className={materialStyles.generateProgress} data-testid="assist-guidance">
                {assistGuidance}
              </p>
            )}
            {generating && generateProgress && (
              <p role="status" data-testid="generate-progress" className={materialStyles.generateProgress}>
                {generateProgress}
              </p>
            )}
            {generateError && <p role="alert" className={materialStyles.generateProgress}>{generateError}</p>}
            {generateBanner && !generating && (
              <div role="status" data-testid="generate-banner" className={materialStyles.generateBanner}>
                <p>{generateBanner}</p>
                <button type="button" aria-label="关闭提示" onClick={() => setGenerateBanner(null)}>
                  ×
                </button>
              </div>
            )}
          </div>
        </div>

        <aside className={styles.writeRail} data-testid="write-rail">
          <div className={styles.railInner}>
            <PlatformPreview
              state={variants.state}
              supportedChannels={variants.state.supportedChannels}
              liveText={liveText}
              onGenerate={() => void variants.generate()}
              onRegenerate={channel => void variants.regenerate(channel)}
              onAdopt={() => void handleAdopt()}
              onRetry={() => void variants.reload()}
            />
            {variants.state.status !== 'no_master' && <PrePublishReview bubbles={reviewBubbles} />}
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
                onRetrySave={() => status.retrySave()}
              />
              <span aria-hidden>·</span>
              <span className={styles.saveText}>{status.wordCount} 字</span>
            </>
          ) : (
            <span className={styles.saveText}>正在载入稿件…</span>
          )}
        </span>
        <div className={styles.statusZoom}>
          {usage && usage.quota > 0 && usage.quota < Infinity && (
            <span
              className={`${materialStyles.quotaPill} ${
                quotaExhausted
                  ? materialStyles.quotaPillExhausted
                  : quotaUrgent
                    ? materialStyles.quotaPillUrgent
                    : ''
              }`}
              data-testid="quota-pill"
              data-urgent={quotaUrgent || undefined}
              data-exhausted={quotaExhausted || undefined}
              title={quotaTooltip}
            >
              <span
                className={materialStyles.quotaRing}
                style={{ '--quota-pct': `${Math.min(100, (usage.used / usage.quota) * 100)}%` } as React.CSSProperties}
                aria-hidden
              />
              {quotaExhausted ? '本月额度已用完' : `本月剩余 ${Math.max(0, usage.quota - usage.used)}`}
            </span>
          )}
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
        onImport={importFromDrawer}
        onLink={linkExcerpt}
        linkStates={materials.linkStates}
        projectId={projectId}
      />
    </div>
  )
}
