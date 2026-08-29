'use client'

import styles from '../editor/consumer-editor.module.css'

interface ConsumerHeaderProps {
  title: string
  onBack?(): void
}

export function ConsumerHeader({ title, onBack }: ConsumerHeaderProps) {
  return (
    <header data-testid="consumer-header" className={styles.header}>
      {onBack && (
        <button type="button" className={styles.ghostButton} onClick={onBack}>
          返回
        </button>
      )}
      <span className={styles.headerTitle}>{title}</span>
    </header>
  )
}
