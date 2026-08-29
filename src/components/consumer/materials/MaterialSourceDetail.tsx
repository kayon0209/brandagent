'use client'

/**
 * Consumer material source detail (upgrade plan task 7).
 *
 * Shows where an excerpt came from — on demand only. The default card shows
 * the summary; this panel is the explicit "看来源" step.
 */

import type { ConsumerMaterialExcerpt } from '@/types/consumer.types'
import styles from './consumer-materials.module.css'

interface MaterialSourceDetailProps {
  excerpt: ConsumerMaterialExcerpt
}

export function MaterialSourceDetail({ excerpt }: MaterialSourceDetailProps) {
  return (
    <div className={styles.sourceDetail}>
      <h4>来源</h4>
      <blockquote>{excerpt.excerpt_text}</blockquote>
      <p className={styles.provenance}>
        溯源编号已验证：{excerpt.provenance_hash.slice(0, 8)}…
      </p>
    </div>
  )
}
