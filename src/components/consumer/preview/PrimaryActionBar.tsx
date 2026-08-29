'use client'

import styles from './consumer-preview.module.css'

interface PrimaryActionBarProps {
  onAdopt(): void
  onRegenerate(): void
  onPrepareExport(): void
}

export function PrimaryActionBar({ onAdopt, onRegenerate, onPrepareExport }: PrimaryActionBarProps) {
  return (
    <div className={styles.actionBar} data-testid="primary-action-bar">
      <button type="button" className={styles.primaryRed} onClick={onAdopt}>
        采用这版
      </button>
      <button type="button" className={styles.secondary} onClick={onRegenerate} style={{ marginLeft: 'auto' }}>
        重新生成
      </button>
      <button type="button" className={styles.inkSecondary} onClick={onPrepareExport}>
        准备发布
      </button>
    </div>
  )
}
