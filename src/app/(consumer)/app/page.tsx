'use client'

// Clerk-protected, data-driven page: prerender has no session, so a
// static export would bake the interception shell (prod 404 root
// cause). Render per-request like the middleware expects.
export const dynamic = 'force-dynamic'


/**
 * Consumer home (/app) — the personal projects list (plan §3.1 step 1).
 * Shown only for signed-in users; Clerk middleware routes anonymous visitors
 * to sign-in.
 *
 * UX review rework (U1/U2/U3): returning users open this page to FIND their
 * work, not to fill a form — the project list now owns the first screen,
 * 新建写作项目 is a header action that expands an inline composer, and the
 * materials entry is a proper button with a count (U2), matching the write
 * page's visual language instead of a bare text link.
 */

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'

import { brandFlowRequest, BrandFlowApiError } from '@/lib/api/brandflow'
import { fetchConsumerUsage } from '@/lib/consumer-usage'
import buttonStyles from '@/components/consumer/editor/consumer-editor.module.css'
import styles from '@/components/consumer/materials/consumer-materials.module.css'

interface ConsumerProject {
  task_id: string
  title: string
  core_idea: string
  writing_intent: string
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
  const [usage, setUsage] = useState<{ used: number; quota: number } | null>(null)

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
        body: JSON.stringify({ title, core_idea: coreIdea, writing_intent: '' }),
      })
      setTitle('')
      setCoreIdea('')
      // X8: client-side navigation — a full reload lands the user on a
      // blank boot instead of straight onto the manuscript
      void router.push(`/app/write/${created.task_id}`)
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : '创建失败，请重试。')
      setCreating(false)
    }
  }, [coreIdea, router, title])

  const openComposer = () => {
    setComposerOpen(true)
    setError(null)
  }

  return (
    <div className={styles.page}>
      <header className={styles.homeHeader}>
        <h1>我的写作</h1>
        <div className={styles.homeHeaderActions}>
          {usage && usage.quota > 0 && usage.quota < Infinity && (
            <span
              className={styles.quotaPill}
              data-testid="home-quota-pill"
              title={`本月 AI 额度：已用 ${usage.used} / 共 ${usage.quota} tokens（写作和保存不消耗额度）`}
            >
              额度 {Math.max(0, usage.quota - usage.used)}
            </span>
          )}
          {/* U2: the materials entry is a real button with a count, the
              same visual language as the write page — not a bare link */}
          <Link
            href="/app/materials"
            data-testid="materials-entry"
            className={buttonStyles.materialsButton}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
              <path d="M4 5h16v14H4z" />
              <path d="M8 9h8M8 13h6" />
            </svg>
            <span>素材库</span>
          </Link>
          <button type="button" className="consumer-primary-button" onClick={openComposer}>
            新建写作项目
          </button>
        </div>
      </header>

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

      {!loading && !error && projects.length === 0 && !composerOpen && (
        <section className={styles.state}>
          <p>还没有项目。写下项目名称和核心观点，开始第一篇。</p>
          <button type="button" className="consumer-primary-button" onClick={openComposer}>
            新建写作项目
          </button>
        </section>
      )}

      {!loading && !error && projects.length > 0 && (
        <ul className={styles.documentList}>
          {projects.map(project => (
            <li key={project.task_id}>
              <Link href={`/app/write/${project.task_id}`} className={styles.projectCard}>
                <strong className={styles.projectCardTitle}>{project.title}</strong>
                <span className="consumer-project-idea">{project.core_idea}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
