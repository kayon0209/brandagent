'use client'

import { useState } from 'react'

import styles from './consumer-preview.module.css'

export interface ReviewBubble {
  kind: 'needs_fix' | 'blocking' | 'hint'
  text: string
  /** N13: when the finding is grounded in a material excerpt, show the
      source verbatim — trust machinery the user can SEE, not just read
      about. Optional: deterministic mappers fill it when applicable. */
  sourceExcerpt?: string
}

interface PrePublishReviewProps {
  bubbles: ReviewBubble[]
}

export function PrePublishReview({ bubbles }: PrePublishReviewProps) {
  return (
    <section className={styles.reviewSection} aria-label="发布前再看一眼">
      <h3 className={styles.reviewTitle}>发布前再看一眼</h3>
      {bubbles.length === 0 ? (
        /* N7: the empty state must say the check RAN and what it covered —
           'nothing found' alone reads as 'nothing checked' to a suspicious
           user, and this product's whole pitch is earned suspicion */
        <p className={styles.reviewEmpty} data-testid="review-empty">
          已按渠道规格完成长度与禁用词检查，没有需要你确认的点。真正发布仍由你在平台后台操作。
        </p>
      ) : (
        bubbles.map(bubble => (
          <Bubble key={bubble.text} bubble={bubble} />
        ))
      )}
    </section>
  )
}

function Bubble({ bubble }: { bubble: ReviewBubble }) {
  const [sourceOpen, setSourceOpen] = useState(false)
  return (
    <div>
      <p
        data-testid="review-bubble"
        className={bubble.kind === 'blocking' ? styles.blocking : styles.needsFix}
      >
        {bubble.text}
      </p>
      {bubble.sourceExcerpt && (
        <div>
          <button
            type="button"
            className={styles.reviewSourceToggle}
            aria-expanded={sourceOpen}
            onClick={() => setSourceOpen(previous => !previous)}
          >
            {sourceOpen ? '收起来源' : '查看来源'}
          </button>
          {sourceOpen && (
            <blockquote className={styles.reviewSourceQuote} data-testid="review-source">
              {bubble.sourceExcerpt}
            </blockquote>
          )}
        </div>
      )}
    </div>
  )
}
