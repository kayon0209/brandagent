'use client'

/**
 * Consumer material drawer (upgrade plan task 7).
 *
 * Collapsed by default; when open it shows real material cards, actionable
 * empty/processing/failed states, and never fabricates material entries.
 */

import Link from 'next/link'

import type { ConsumerMaterialExcerpt, MaterialLinkState } from '@/types/consumer.types'
import { DeepResearchPanel } from '@/components/consumer/research/DeepResearchPanel'
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
  /** N2: owner-project context for the fallback link so a cold drawer still
      returns the user to THIS project's materials flow, not a dead end */
  projectId?: string
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
  projectId,
}: MaterialDrawerProps) {
  return (
    <aside className={styles.drawer} data-open={open} aria-hidden={!open} data-testid="material-drawer">
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
              {onImport ? (
                <button type="button" onClick={() => onImport?.()}>
                  导入素材
                </button>
              ) : (
                // no dead buttons (P1-3): without an import handler the drawer
                // points at the materials page instead of doing nothing —
                // N2: client-side Link carrying THIS project as the return
                // context, matching the write page's navigation contract
                <Link href={projectId ? `/app/materials?from=${projectId}` : '/app/materials'}>
                  去素材库导入
                </Link>
              )}
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

          {/* Phase 6 深度调研 (user-approved 2026-09-08): the drawer is the
              in-project entry — a joined card lands in this project's
              material flow without leaving the writing desk. */}
          <DeepResearchPanel taskId={projectId ?? null} />
        </div>
      )}
    </aside>
  )
}
