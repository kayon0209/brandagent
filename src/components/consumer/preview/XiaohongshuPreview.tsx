'use client'

import styles from './consumer-preview.module.css'

interface XiaohongshuPreviewProps {
  data: { title: string; body: string; tags: string[] }
}

export function XiaohongshuPreview({ data }: XiaohongshuPreviewProps) {
  return (
    <article data-testid="xiaohongshu-preview" className={styles.xiaohongshu}>
      <h3 className={styles.xiaohongshuTitle}>{data.title}</h3>
      <p className={styles.xiaohongshuBody}>{data.body}</p>
      <ul data-testid="xiaohongshu-tags" className={styles.xiaohongshuTags}>
        {data.tags.map(tag => (
          <li key={tag}>#{tag}</li>
        ))}
      </ul>
    </article>
  )
}
