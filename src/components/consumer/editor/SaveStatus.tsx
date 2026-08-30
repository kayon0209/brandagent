'use client'

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
}

export function SaveStatus({ state, onResolveConflict }: SaveStatusProps) {
  return (
    <div className={styles.saveStatus} data-testid="save-status" data-state={state}>
      <span
        className={
          state === 'conflict' || state === 'error' ? styles.saveStatusIconConflict : styles.saveStatusIconSaved
        }
      >
        ●
      </span>
      <span>{LABELS[state]}</span>
      {state === 'conflict' && (
        <button type="button" className={styles.resolveButton} onClick={onResolveConflict}>
          查看最新稿
        </button>
      )}
    </div>
  )
}
