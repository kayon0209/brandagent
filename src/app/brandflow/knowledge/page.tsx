'use client'

import { useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { useBrandFlow } from '@/hooks/useBrandFlow'
import { AlertTriangle, BookOpen, Check, FileCheck2, FileText, Loader2, Search } from 'lucide-react'
import Link from 'next/link'
import { BrandFlowApiError } from '@/lib/api/brandflow'
import styles from '@/styles/brandflow'

const tabItems = ['产品事实', '品牌规范', '渠道规范', '已批准内容', '禁止声明'] as const

export default function BrandFlowKnowledge() {
  const searchParams = useSearchParams()
  const flow = useBrandFlow()
  const [activeTab, setActiveTab] = useState(0)
  const [search, setSearch] = useState('')
  const [knowledgeItems, setKnowledgeItems] = useState<Array<Record<string, unknown>>>([])
  const [knowledgeLoaded, setKnowledgeLoaded] = useState(false)
  const [knowledgeError, setKnowledgeError] = useState(false)

  const tabKeys = ['product_facts', 'brand_guidelines', 'channel_guidelines', 'approved_content', 'forbidden_claims'] as const

  useEffect(() => {
    const q = searchParams.get('search')
    if (q) {
      setSearch(q)
    }
  }, [searchParams])

  useEffect(() => {
    setKnowledgeLoaded(false)
    setKnowledgeError(false)
    const tab = tabKeys[activeTab]
    flow.command<{ items: Array<Record<string, unknown>> }>(`/api/v1/knowledge/${tab}`, {}, 'GET')
      .then((data) => {
        setKnowledgeItems(data.items || [])
        setKnowledgeLoaded(true)
      })
      .catch(() => {
        setKnowledgeError(true)
        setKnowledgeLoaded(true)
      })
  }, [activeTab]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!flow.isLoaded || flow.loading) {
    return (
      <main className={styles.centered}>
        <div><Loader2 className={styles.spin} size={24} /></div>
        <h1>正在加载知识库</h1>
        <p>获取权威知识与文档索引。</p>
      </main>
    )
  }

  return (
    <main className={styles.main}>
      <header className={styles.topbar}>
        <div>
          <span>BrandFlow / Knowledge</span>
          <h1>权威知识与文档</h1>
        </div>
      </header>
      {flow.error && <RecoveryBanner error={flow.error} onRetry={flow.refreshTasks} />}

      <div className={styles.filterBar}>
        <div className={styles.searchField}>
          <Search size={16} />
          <input
            aria-label="搜索知识"
            placeholder="搜索文档、事实或术语"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      <div className={styles.knowledgeLayout}>
        <aside className={styles.knowledgeTabs}>
          {tabItems.map((label, index) => (
            <button
              key={label}
              className={index === activeTab ? styles.activeKnowledgeTab : undefined}
              onClick={() => setActiveTab(index)}
            >
              {label}
            </button>
          ))}
        </aside>

        <section className={styles.areaCard}>
          <div className={styles.areaCardHeader}>
            <div>
              <span className={styles.panelLabel}>{tabItems[activeTab].toUpperCase()}</span>
              <h2>{tabItems[activeTab]}</h2>
            </div>
          </div>
          {!knowledgeLoaded ? (
            <div className={styles.knowledgeEmpty}>
              <Loader2 className={styles.spin} size={24} />
              <p>正在加载知识数据…</p>
            </div>
          ) : knowledgeError || knowledgeItems.length === 0 ? (
            <div className={styles.knowledgeEmpty}>
              <BookOpen size={48} />
              <h3>知识库为空 — 创建任务即可自动填充</h3>
              <p>
                1. 在任务中心创建一个内容任务；2. 任务运行时会自动通过 MCP 检索产品事实、品牌规范和渠道规范，
                并写入知识库索引；3. 通常在任务启动后 1-2 分钟内即可在此看到对应数据。
              </p>
              <Link href="/brandflow/tasks" className={styles.primary}>
                前往任务中心
              </Link>
              <button
                className={styles.secondary}
                onClick={() => flow.command('/api/v1/tasks/demo', {})}
              >
                创建演示任务
              </button>
            </div>
          ) : (
            <ul className={styles.knowledgeList}>
              {knowledgeItems.map((item, i) => (
                <li key={i} className={styles.taskRow}>
                  <span><b>{String(item.title ?? '未命名')}</b></span>
                  <small>{String(item.source ?? '')}</small>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  )
}

function RecoveryBanner({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <div className={styles.recovery} role="alert">
      <AlertTriangle />
      <span><b>数据加载失败</b><small>{error.message}</small></span>
      <button onClick={onRetry}>重试</button>
    </div>
  )
}
