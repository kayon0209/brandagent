'use client'

import styles from './consumer-editor.module.css'

interface CoreIdeaBlockProps {
  coreIdea: string
}

export function CoreIdeaBlock({ coreIdea }: CoreIdeaBlockProps) {
  return (
    <section
      data-testid="core-idea-block"
      data-gap="32"
      className={styles.coreIdea}
      style={{ marginBottom: '32px' }}
    >
      <p className={styles.coreIdeaLabel}>核心观点</p>
      <p className={styles.coreIdeaText}>{coreIdea}</p>
    </section>
  )
}
