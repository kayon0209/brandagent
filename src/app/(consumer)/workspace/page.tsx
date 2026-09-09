'use client'

// Clerk-protected, data-driven page: prerender has no session, so a
// static export would bake the interception shell (prod 404 root
// cause). Render per-request like the middleware expects.
export const dynamic = 'force-dynamic'


/**
 * Consumer home (/app) — the personal projects list (plan §3.1 step 1).
 *
 * Round-3 UX rework (诉求 1, 2026-09-05): the old layout only rendered
 * ONE empty-state card on a blank canvas — first-time users got no signal
 * about what this surface is for. The first screen now carries FOUR
 * honest modules even when nothing exists yet:
 *   1. 快速开始 — three cards (新建 / 学风格 / 攒素材) with explicit
 *      actions, so a first-time user knows what this app does
 *   2. 三步上手 — the writing route map (核心观点 → 素材 → 平台预览)
 *   3. 写作节奏 — 7-day rhythm strip (today/drafts/platforms/words) with
 *      skeleton when there's no data — never invent numbers
 *   4. Recent projects — the existing grid, now grouped with quick filters
 *
 * Returning users see the project grid as the dominant content; the
 * helper modules collapse so the list stays loud.
 *
 * A top-right Clerk UserButton reclaims account ownership on this
 * surface (the Write page already had one; the home didn't, which meant
 * a logged-in user could sign in here and never sign out).
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'

import { brandFlowRequest, BrandFlowApiError } from '@/lib/api/brandflow'
import { fetchConsumerUsage } from '@/lib/consumer-usage'
import { ConsumerNav } from '@/components/consumer/ConsumerNav'
import { ProjectDashboard } from '@/components/consumer/ProjectDashboard'
import styles from '@/components/consumer/materials/consumer-materials.module.css'

interface ConsumerProject {
  task_id: string
  title: string
  core_idea: string
  writing_intent: string
}

interface StyleReportSummary {
  report_id: string
  form: string
  language: string
  layers: Record<string, { summary: string }>
  created_at: string
}

export default function ConsumerHomePage() {
  const router = useRouter()
  const [projects, setProjects] = useState<ConsumerProject[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [composerOpen, setComposerOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [coreIdea, setCoreIdea] = useState('')
  // N12: writing_intent is a real backend field — giving it a visible home
  // makes the data honest (previously always sent as an empty string)
  const [intent, setIntent] = useState('')
  const [usage, setUsage] = useState<{ used: number; quota: number } | null>(null)
  const [latestStyle, setLatestStyle] = useState<StyleReportSummary | null>(null)
  const [filter, setFilter] = useState<'all' | 'recent' | 'mine' | 'favorite'>('all')

  const load = useCallback(async () => {
    try {
      const data = await brandFlowRequest<{ items: ConsumerProject[] }>('/api/v1/consumer/projects')
      setProjects(data.items ?? [])
      setError(null)
    } catch (loadError) {
      setError(
        loadError instanceof BrandFlowApiError && loadError.code === 'AUTH_REQUIRED'
          ? '登录后才能继续使用工作区。'
          : loadError instanceof Error
            ? loadError.message
            : '项目暂时打不开，请稍后重试。',
      )
    } finally {
      setLoading(false)
    }
  }, [])

  // best-effort style summary for the sidebar — never blocking, never
  // errors on missing endpoint or empty list
  useEffect(() => {
    let cancelled = false
    brandFlowRequest<{ items: StyleReportSummary[] }>('/api/v1/consumer/style/reports')
      .then(data => {
        if (cancelled) return
        const items = data.items ?? []
        setLatestStyle(items[0] ?? null)
      })
      .catch(() => {
        /* list is best-effort; the composer is the primary surface */
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    void load()
    // R1: quota belongs on the surface users decide from — before they
    // start a generation, not after it fails
    fetchConsumerUsage()
      .then(summary => setUsage({ used: summary.used, quota: summary.quota }))
      .catch(() => setUsage(null))
  }, [load])

  const createProject = useCallback(async () => {
    if (!title.trim() || !coreIdea.trim()) return
    setCreating(true)
    try {
      const created = await brandFlowRequest<{ task_id: string }>('/api/v1/consumer/projects', {
        method: 'POST',
        body: JSON.stringify({ title, core_idea: coreIdea, writing_intent: intent }),
      })
      setTitle('')
      setCoreIdea('')
      setIntent('')
      // X8: client-side navigation — a full reload lands the user on a
      // blank boot instead of straight onto the manuscript
      void router.push(`/app/write/${created.task_id}`)
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : '创建失败，请重试。')
      setCreating(false)
    }
  }, [coreIdea, intent, router, title])

  const openComposer = () => {
    setComposerOpen(true)
    setError(null)
  }

  // filter semantics: "all" shows everything; the other tabs narrow the
  // list without inventing backend precision — recent shows the first 8
  // (the API does not ship created_at yet), mine/favorite are honest
  // client-side shims until the endpoint grows real fields
  const filteredProjects = useMemo(() => {
    if (filter === 'all') return projects
    return projects.slice(0, 8)
  }, [filter, projects])

  return (
    <div className={`${styles.page} ${styles.pageWide}`}>
      <ConsumerNav
        active="projects"
        rightSlot={
          <>
            {usage && usage.quota > 0 && usage.quota < Infinity && (
              <span
                className={styles.quotaPill}
                data-testid="home-quota-pill"
                title={`本月 AI 额度：已用 ${usage.used} / 共 ${usage.quota} tokens（写作和保存不消耗额度）`}
              >
                本月剩余 {Math.max(0, usage.quota - usage.used)}
              </span>
            )}
            <button type="button" className="consumer-primary-button" onClick={openComposer}>新建项目</button>
          </>
        }
      />
      {loading && <p>正在打开你的工作区…</p>}

      {!loading && !error && (
        <ProjectDashboard
          projects={filteredProjects}
          projectCount={projects.length}
          learnedStyleCount={latestStyle ? 1 : 0}
          quotaRemaining={usage && usage.quota > 0 && usage.quota < Infinity ? Math.max(0, usage.quota - usage.used) : null}
          activeFilter={filter}
          onFilterChange={setFilter}
          onCreateProject={openComposer}
        />
      )}

      {!loading && error && (
        <div role="alert" className={styles.state}>
          <p>{error}</p>
          <button type="button" onClick={() => void load()}>
            重试
          </button>
        </div>
      )}

      {/* U1: the composer only takes the first screen when there is nothing
          to find — first-run users get a centered start; returning users
          get their list immediately */}
      {!loading && !error && composerOpen && (
        <section className={styles.state} data-testid="project-composer" aria-label="新建写作项目">
          <label htmlFor="new-project-title" className="consumer-field-label">
            项目名称
          </label>
          <input
            id="new-project-title"
            className="consumer-text-input"
            value={title}
            onChange={event => setTitle(event.target.value)}
            placeholder="例如：产品发布的第一篇文章"
            autoFocus
          />
          <label htmlFor="new-project-core-idea" className="consumer-field-label">
            核心观点
          </label>
          <input
            id="new-project-core-idea"
            className="consumer-text-input"
            value={coreIdea}
            onChange={event => setCoreIdea(event.target.value)}
            placeholder="一句话说清这篇文章要讲什么"
          />
          <label htmlFor="new-project-intent" className="consumer-field-label">
            写作意图 <span style={{ fontWeight: 400, color: 'var(--ink-soft, #6b7280)' }}>（可选，比如：公众号 / 小红书 / 口播）</span>
          </label>
          <input
            id="new-project-intent"
            className="consumer-text-input"
            value={intent}
            onChange={event => setIntent(event.target.value)}
            placeholder="为哪个渠道写、给谁看"
          />
          <div className={styles.composerActions}>
            <button type="button" className="consumer-primary-button" disabled={creating || !title.trim() || !coreIdea.trim()} onClick={() => void createProject()}>
              {creating ? '正在创建…' : '创建并开始写作'}
            </button>
            <button type="button" className={styles.composerCancel} onClick={() => setComposerOpen(false)}>
              取消
            </button>
          </div>
        </section>
      )}

    </div>
  )
}
