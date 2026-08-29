'use client'

/**
 * Consumer material drawer (upgrade plan task 7).
 *
 * Collapsed by default; when open it shows real material cards, actionable
 * empty/processing/failed states, and never fabricates material entries.
 */

import type { ConsumerMaterialExcerpt, MaterialLinkState } from '@/types/consumer.types'
import { MaterialCard } from './MaterialCard'
import styles from './consumer-materials.module.css'

interface MaterialDrawerProps {
  materials: ConsumerMaterialExcerpt[]
  open: boolean
  onToggle: () => void
  loading: boolean
  error: { code: string; message: string } | null
  onImport?: () => void
  onRetry?: () => void
  onLink?: (excerptId: string) => void
  linkStates?: Record<string, MaterialLinkState>
}

export function MaterialDrawer({
  materials,
  open,
  onToggle,
  loading,
  error,
  onImport,
  onRetry,
  onLink,
  linkStates = {},
}: MaterialDrawerProps) {
  return (
    <aside className={styles.drawer} data-open={open}>
      <button
        type="button"
        className={styles.toggle}
        aria-expanded={open}
        onClick={onToggle}
      >
        {open ? '收起素材抽屉' : '展开素材抽屉'}
      </button>

      {open && (
        <div className={styles.body} aria-label="素材抽屉内容区">
          <h3 className={styles.title}>素材</h3>

          {error && !loading && (
            <div className={styles.state} role="alert">
              <p>处理失败：{error.message}</p>
              <button type="button" onClick={() => onRetry?.()}>
                重试
              </button>
            </div>
          )}

          {!error && loading && (
            <div className={styles.state}>
              <p>正在处理你的素材…</p>
            </div>
          )}

          {!error && !loading && materials.length === 0 && (
            <div className={styles.state}>
              <p>还没有素材。从一篇笔记、一段录音稿或一个链接开始。</p>
              <button type="button" onClick={() => onImport?.()}>
                导入素材
              </button>
            </div>
          )}

          {!loading &&
            materials.map(excerpt => (
              <MaterialCard
                key={excerpt.excerpt_id}
                excerpt={excerpt}
                onLink={onLink}
                linkState={linkStates[excerpt.excerpt_id] ?? 'unlinked'}
              />
            ))}
        </div>
      )}
    </aside>
  )
}
