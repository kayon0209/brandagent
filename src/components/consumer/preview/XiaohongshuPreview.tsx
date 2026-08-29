'use client'

import styles from './consumer-preview.module.css'
import { deriveTitle } from './deriveTitle'

interface XiaohongshuPreviewProps {
  data: { content: string }
}

export function XiaohongshuPreview({ data }: XiaohongshuPreviewProps) {
  const lines = data.content.split('\n').map(line => line.trim()).filter(Boolean)
  const title = deriveTitle(data.content, '小红书笔记')
  const body = lines.length > 1
    ? lines.slice(1).join(' ').replace(/#[^\s#]+/g, '').trim()
    : ''
  const tags = (data.content.match(/#[^\s#]+/g) ?? []).map(tag => tag.slice(1))
  return (
    <article data-testid="xiaohongshu-preview" className={styles.xiaohongshu}>
      {/* decorative two-character cover block, distinct from the title text */}
      <div className={styles.xhsCover} aria-hidden>
        {title.slice(0, 2)}
      </div>
      <h3 className={styles.xiaohongshuTitle}>{title}</h3>
      {body && <p className={styles.xiaohongshuBody}>{body}</p>}
      <ul data-testid="xiaohongshu-tags" className={styles.xiaohongshuTags}>
        {tags.map(tag => (
          <li key={tag}>#{tag}</li>
        ))}
      </ul>
    </article>
  )
}
