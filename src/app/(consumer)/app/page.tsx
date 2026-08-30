'use client'

/**
 * Consumer home (/app) — the personal projects list (plan §3.1 step 1).
 * Shown only for signed-in users; Clerk middleware routes anonymous visitors
 * to sign-in.
 */

import { useCallback, useEffect, useState } from 'react'

import { brandFlowRequest, BrandFlowApiError } from '@/lib/api/brandflow'
import styles from '@/components/consumer/materials/consumer-materials.module.css'

interface ConsumerProject {
  task_id: string
  title: string
  core_idea: string
  writing_intent: string
}

export default function ConsumerHomePage() {
  const [projects, setProjects] = useState<ConsumerProject[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [title, setTitle] = useState('')
  const [coreIdea, setCoreIdea] = useState('')

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
      window.location.assign(`/app/write/${created.task_id}`)
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : '创建失败，请重试。')
      setCreating(false)
    }
  }, [coreIdea, title])

  return (
    <div className={styles.page}>
      <h1>我的写作</h1>

      {loading && <p>正在打开你的工作区…</p>}

      {!loading && error && (
        <div role="alert" className={styles.state}>
          <p>{error}</p>
          <button type="button" onClick={() => void load()}>
            重试
          </button>
        </div>
      )}

      {!loading && !error && (
        <>
          <section className={styles.state}>
            <label htmlFor="new-project-title" className="consumer-field-label">
              项目名称
            </label>
            <input
              id="new-project-title"
              className="consumer-text-input"
              value={title}
              onChange={event => setTitle(event.target.value)}
              placeholder="例如：产品发布的第一篇文章"
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
            <button
              type="button"
              className="consumer-primary-button"
              disabled={creating || !title.trim() || !coreIdea.trim()}
              onClick={() => void createProject()}
            >
              {creating ? '正在创建…' : '新建写作项目'}
            </button>
          </section>

          {projects.length === 0 ? (
            <p>还没有项目。写下项目名称和核心观点，开始第一篇。</p>
          ) : (
            <ul className={styles.documentList}>
              {projects.map(project => (
                <li key={project.task_id}>
                  <a href={`/app/write/${project.task_id}`}>
                    {project.title}
                    <span className="consumer-project-idea">{project.core_idea}</span>
                  </a>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}
