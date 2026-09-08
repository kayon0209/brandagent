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
import Link from 'next/link'
import { useRouter } from 'next/navigation'

import { brandFlowRequest, BrandFlowApiError } from '@/lib/api/brandflow'
import { fetchConsumerUsage } from '@/lib/consumer-usage'
import { ConsumerNav } from '@/components/consumer/ConsumerNav'
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

const FILTERS: Array<{ value: 'all' | 'recent'; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'recent', label: '最近 7 天' },
]

/** Empty-state starter templates (评审 round-3c #G): clicking one pre-fills
 * the composer (title + core idea) — a real starting point for a blank
 * workspace, never fake data. */
const STARTER_TEMPLATES: Array<{ label: string; title: string; coreIdea: string }> = [
  {
    label: '产品发布稿',
    title: '产品发布的第一篇文章',
    coreIdea: '我们为什么做这款产品——给关心它的人一个诚实的交代。',
  },
  {
    label: '行业观点',
    title: '行业里没人直说的一件事',
    coreIdea: '这个行业大多数人没有直说的一个变化，以及它意味着什么。',
  },
  {
    label: '个人故事',
    title: '一个改变我的经历',
    coreIdea: '一段亲身经历如何改变了我看待这件事的方式。',
  },
]

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
  const [filter, setFilter] = useState<'all' | 'recent'>('all')

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

  // recent-7d filter — bound to created_at when the API ships it; for now
    // we show the first 8 items as "recent" so the filter never claims a
    // false precision the backend can't deliver
  const filteredProjects = useMemo(() => {
    if (filter === 'all') return projects
    return projects.slice(0, 8)
  }, [filter, projects])

  const showRhythmSkeleton = loading && projects.length === 0 && !latestStyle
  const hasAnyContent = projects.length > 0 || !!latestStyle

  return (
    <div className={`${styles.page} ${styles.pageWide}`}>
      {/* round-3f (P0-4): unified app navigation on every /app/* page */}
      <ConsumerNav active="projects" />
      <header className={styles.homeHeader}>
        <h1>项目</h1>
        <div className={styles.homeHeaderActions}>
          {usage && usage.quota > 0 && usage.quota < Infinity && (
            <span
              className={styles.quotaPill}
              data-testid="home-quota-pill"
              title={`本月 AI 额度：已用 ${usage.used} / 共 ${usage.quota} tokens（写作和保存不消耗额度）`}
            >
              本月剩余 {Math.max(0, usage.quota - usage.used)}
            </span>
          )}
          <button type="button" className="consumer-primary-button" onClick={openComposer}>
            新建项目
          </button>
        </div>
      </header>

      {/* round-3 first-screen value density (诉求 1) — empty-state hero:
          one result-oriented title, one action, three starter templates
          (评审 round-3c #G). Clicking a starter pre-fills the composer. */}
      {!loading && !error && !hasAnyContent && (
        <section className={styles.emptyHero} aria-label="创建第一篇内容">
          <h2 className={styles.emptyHeroTitle}>创建你的第一篇品牌内容</h2>
          <p className={styles.emptyHeroBody}>
            输入一个核心观点，生成适合公众号、小红书与口播的版本，
            同时保留你说话的方式。
          </p>
          <button
            type="button"
            className="consumer-primary-button"
            data-testid="empty-hero-cta"
            onClick={openComposer}
          >
            创建项目
          </button>
          <div className={styles.emptyHeroStarters} role="group" aria-label="或从一个示例开始">
            <span className={styles.emptyHeroStartersLabel}>或者从一个示例开始：</span>
            <div className={styles.emptyHeroStartersRow}>
              {STARTER_TEMPLATES.map(starter => (
                <button
                  key={starter.label}
                  type="button"
                  className={styles.emptyHeroStarter}
                  onClick={() => {
                    setTitle(starter.title)
                    setCoreIdea(starter.coreIdea)
                    setIntent('')
                    openComposer()
                  }}
                >
                  {starter.label}
                </button>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* 快速开始 — 始终可见的三张卡：给首屏一个明确的「我能做什么」 */}
      {!loading && !error && !hasAnyContent && (
        <section className={styles.quickStart} aria-label="快速开始">
          <article className={styles.quickStartCard} data-emphasis="true">
            <span className={styles.quickStartCardTag}>起点</span>
            <h2 className={styles.quickStartCardTitle}>新建项目</h2>
            <p className={styles.quickStartCardBody}>
              写下一篇文章的项目名 + 一句话核心观点，打开稿纸就开始写。后面可以随时挂素材、按平台预览。
            </p>
            <button type="button" className={styles.quickStartCardAction} onClick={openComposer}>
              写下核心观点
            </button>
          </article>
          <article className={styles.quickStartCard}>
            <span className={styles.quickStartCardTag}>可选</span>
            <h2 className={styles.quickStartCardTitle}>从风格学习开始</h2>
            <p className={styles.quickStartCardBody}>
              贴 2–20 篇同一作者的完整文章，按「语言 / 结构 / 选题 / 素材 / 认知 / 视觉」六层拆出可复用的规则文件。
            </p>
            <Link href="/app/style" className={styles.quickStartCardAction}>
              进入风格实验室
            </Link>
          </article>
          <article className={styles.quickStartCard}>
            <span className={styles.quickStartCardTag}>可选</span>
            <h2 className={styles.quickStartCardTitle}>先攒点素材</h2>
            <p className={styles.quickStartCardBody}>
              把笔记、录音稿、参考资料粘贴进来。AI 改写只会引用这些被关联的片段，不会自己编数字和事实。
            </p>
            <Link href="/app/materials" className={styles.quickStartCardAction}>
              打开素材库
            </Link>
          </article>
        </section>
      )}

      {/* 三步上手 — 写作路线地图（首次用户）+ 返回用户的简短回顾 */}
      {!loading && !error && !hasAnyContent && (
        <section className={styles.routeSteps} aria-label="写作路线">
          <div className={styles.routeStepsItem}>
            <span className={styles.routeStepsIndex}>01</span>
            <strong className={styles.routeStepsLabel}>写下核心观点</strong>
            <span className={styles.routeStepsHint}>一句话说清这篇文章讲什么</span>
          </div>
          <span className={styles.routeStepsArrow} aria-hidden>→</span>
          <div className={styles.routeStepsItem}>
            <span className={styles.routeStepsIndex}>02</span>
            <strong className={styles.routeStepsLabel}>挂素材（可选）</strong>
            <span className={styles.routeStepsHint}>关联你已有的笔记和参考</span>
          </div>
          <span className={styles.routeStepsArrow} aria-hidden>→</span>
          <div className={styles.routeStepsItem}>
            <span className={styles.routeStepsIndex}>03</span>
            <strong className={styles.routeStepsLabel}>平台预览</strong>
            <span className={styles.routeStepsHint}>公众号 / 小红书 / 60 秒口播</span>
          </div>
        </section>
      )}

      {/* 写作节奏 — 7 天数据；空态用骨架条，绝不伪造数字 */}
      <section className={styles.rhythmStrip} aria-label="近期写作节奏">
        <div className={styles.rhythmItem}>
          {showRhythmSkeleton ? (
            <span className={styles.rhythmSkeleton} aria-hidden />
          ) : (
            <span className={styles.rhythmValue}>{projects.length}</span>
          )}
          <span className={styles.rhythmLabel}>进行中的项目</span>
        </div>
        <div className={styles.rhythmItem}>
          {showRhythmSkeleton ? (
            <span className={styles.rhythmSkeleton} aria-hidden />
          ) : (
            <span className={styles.rhythmValue}>{latestStyle ? 1 : 0}</span>
          )}
          <span className={styles.rhythmLabel}>学习到的写作风格</span>
        </div>
      </section>

      {/* 已有项目时：筛选条 + 风格摘要侧条 + 列表 */}
      {!loading && !error && projects.length > 0 && (
        <>
          <div className={styles.homeFilters} role="tablist" aria-label="项目筛选">
            {FILTERS.map(option => (
              <button
                key={option.value}
                type="button"
                role="tab"
                data-active={filter === option.value}
                onClick={() => setFilter(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>

          {latestStyle && (
            <aside className={styles.styleSummaryCard} aria-label="最近一次风格蒸馏">
              <div className={styles.styleSummaryHead}>
                <span className={styles.styleSummaryTitle}>最近一次风格蒸馏</span>
                <Link href="/app/style" className={styles.styleSummaryLink}>
                  去风格实验室 →
                </Link>
              </div>
              <p className={styles.styleSummaryBody}>
                {latestStyle.layers?.l1_language_dna?.summary ??
                  latestStyle.layers?.l2_structure_template?.summary ??
                  '已为你的语料生成可复用的写作规则。'}
              </p>
            </aside>
          )}

          <h2 className={styles.sectionTitle}>最近项目</h2>
          <ul className={styles.documentList}>
            {filteredProjects.map(project => (
              <li key={project.task_id}>
                <Link
                  href={`/app/write/${project.task_id}`}
                  className={styles.projectCard}
                  aria-label={`打开项目：${project.title}`}
                >
                  <span className={styles.projectCardArrow} aria-hidden>→</span>
                  <strong className={styles.projectCardTitle}>{project.title}</strong>
                  <span className="consumer-project-idea">{project.core_idea}</span>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}

      {loading && <p>正在打开你的工作区…</p>}

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

      {!loading && !error && projects.length === 0 && !composerOpen && !hasAnyContent && (
        <div role="status" className={styles.state} aria-live="polite" data-testid="empty-hint">
          <p>还没有项目。点上方任一卡片开始——最快的方式是「写下核心观点」。</p>
        </div>
      )}
    </div>
  )
}