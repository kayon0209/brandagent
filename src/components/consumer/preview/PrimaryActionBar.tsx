'use client'

/**
 * @deprecated round-3f (P0-3): the mode-aware action strip now lives INSIDE
 * PlatformPreview (`.modeActions`) — draft mode offers「生成平台精修版」,
 * polished mode offers「重新生成」; publishing is topbar-only. This component
 * is kept only as a historical export; do NOT mount it in the write page.
 */

import styles from './consumer-preview.module.css'

interface PrimaryActionBarProps {
  onAdopt(): void
  onRegenerate(): void
}

export function PrimaryActionBar({ onAdopt, onRegenerate }: PrimaryActionBarProps) {
  return (
    <div className={styles.actionBar} data-testid="primary-action-bar">
      <button type="button" className={styles.primaryRed} onClick={onAdopt}>
        定稿
      </button>
      <button type="button" className={styles.secondary} onClick={onRegenerate} style={{ marginLeft: 'auto' }}>
        重新生成
      </button>
    </div>
  )
}