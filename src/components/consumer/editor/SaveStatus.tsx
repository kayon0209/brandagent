'use client'

/**
 * Statusbar save segment (v4 baseline .status-copy): the save dot and
 * copy live INSIDE the bottom statusbar, not a floating card.
 */

import styles from './consumer-editor.module.css'

export type SaveState = 'loading' | 'saved' | 'dirty' | 'saving' | 'conflict' | 'error'

const LABELS: Record<SaveState, string> = {
  loading: '正在载入稿件…',
  saved: '已保存',
  dirty: '未保存',
  saving: '正在保存…',
  conflict: '稿件在别处有更新',
  error: '保存失败，先记在本地',
}

interface SaveStatusProps {
  state: SaveState
  onResolveConflict(): void
  /** N4: an error state needs an exit — the local backup kept the text,
      so the only missing affordance is an explicit retry */
  onRetrySave?(): void
}

export function SaveStatus({ state, onResolveConflict, onRetrySave }: SaveStatusProps) {
  return (
    <span className={styles.statusCopy} data-testid="save-status" data-state={state}>
      <span
        aria-hidden
        className={`${styles.saveDot} ${
          state === 'conflict' || state === 'error' ? styles.saveDotConflict : styles.saveDotSaved
        }`}
      >
        ●
      </span>
      <span className={styles.saveText}>{LABELS[state]}</span>
      {state === 'conflict' && (
        <button type="button" className={styles.resolveButton} onClick={onResolveConflict}>
          查看最新稿
        </button>
      )}
      {state === 'error' && onRetrySave && (
        <button type="button" className={styles.resolveButton} data-testid="save-retry" onClick={onRetrySave}>
          重试保存
        </button>
      )}
    </span>
  )
}
