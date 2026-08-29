'use client'

import styles from './consumer-preview.module.css'

export interface ReviewBubble {
  kind: 'needs_fix' | 'blocking' | 'hint'
  text: string
}

interface PrePublishReviewProps {
  bubbles: ReviewBubble[]
}

export function PrePublishReview({ bubbles }: PrePublishReviewProps) {
  return (
    <section className={styles.reviewSection} aria-label="发布前再看一眼">
      <h3 className={styles.reviewTitle}>发布前再看一眼</h3>
      {bubbles.length === 0 ? (
        <p className={styles.reviewEmpty}>暂未发现需要你确认的地方。</p>
      ) : (
        bubbles.map(bubble => (
          <p
            key={bubble.text}
            data-testid="review-bubble"
            className={bubble.kind === 'blocking' ? styles.blocking : styles.needsFix}
          >
            {bubble.text}
          </p>
        ))
      )}
    </section>
  )
}
