'use client'

import styles from './consumer-editor.module.css'

interface SuggestionPopoverProps {
  actionLabel: string
  suggestedText: string
  busy?: boolean
  position: { x: number; y: number } | null
  onAccept(): void
  onDismiss(): void
}

export function SuggestionPopover({
  actionLabel,
  suggestedText,
  busy,
  position,
  onAccept,
  onDismiss,
}: SuggestionPopoverProps) {
  if (!position || busy) return null
  return (
    <div
      className={styles.suggestionPopover}
      data-testid="suggestion-popover"
      style={{ transform: `translateX(${position.x}px) translateY(${position.y}px)` }}
    >
      <p className={styles.suggestionLabel}>{actionLabel}建议</p>
      <p className={styles.suggestionText}>{suggestedText}</p>
      <div className={styles.suggestionActions}>
        <button type="button" className={styles.accentButton} onClick={onAccept}>
          接受改写
        </button>
        <button type="button" className={styles.ghostButton} onClick={onDismiss}>
          不改了
        </button>
      </div>
    </div>
  )
}
