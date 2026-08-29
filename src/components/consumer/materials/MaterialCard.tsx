'use client'

/**
 * Consumer material card (upgrade plan task 7).
 *
 * Progressive disclosure: summary + tags by default; the source excerpt and
 * traceability detail appear only after an explicit click.
 */

import { useState } from 'react'

import type { ConsumerMaterialExcerpt, MaterialLinkState } from '@/types/consumer.types'

interface MaterialCardProps {
  excerpt: ConsumerMaterialExcerpt
  onLink?: (excerptId: string) => void
  linkState: MaterialLinkState
}

const LINK_LABELS: Record<MaterialLinkState, string> = {
  unlinked: '关联到项目',
  linking: '关联中…',
  linked: '已关联',
  failed: '关联失败，重试',
}

export function MaterialCard({ excerpt, onLink, linkState }: MaterialCardProps) {
  const [sourceOpen, setSourceOpen] = useState(false)

  return (
    <article className="consumer-material-card" data-excerpt-id={excerpt.excerpt_id}>
      <p className="consumer-material-summary">{excerpt.summary}</p>

      {excerpt.tags.length > 0 && (
        <ul className="consumer-material-tags">
          {excerpt.tags.map(tag => (
            <li key={tag}>#{tag}</li>
          ))}
        </ul>
      )}

      <div className="consumer-material-actions">
        <button
          type="button"
          className="consumer-material-source-toggle"
          aria-expanded={sourceOpen}
          onClick={() => setSourceOpen(open => !open)}
        >
          来源
        </button>

        {onLink && (
          <button
            type="button"
            className="consumer-material-link"
            disabled={linkState === 'linked' || linkState === 'linking'}
            onClick={() => onLink(excerpt.excerpt_id)}
          >
            {LINK_LABELS[linkState]}
          </button>
        )}
      </div>

      {sourceOpen && (
        <div className="consumer-material-source">
          <blockquote>{excerpt.excerpt_text}</blockquote>
        </div>
      )}
    </article>
  )
}
