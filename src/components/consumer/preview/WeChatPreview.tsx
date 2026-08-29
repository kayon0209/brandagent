'use client'

import styles from './consumer-preview.module.css'

interface WeChatPreviewProps {
  data: { title: string; paragraphs: string[] }
}

export function WeChatPreview({ data }: WeChatPreviewProps) {
  return (
    <article data-testid="wechat-preview" className={styles.wechat}>
      <h3 className={styles.wechatTitle}>{data.title}</h3>
      <div data-testid="wechat-paragraphs">
        {data.paragraphs.map(paragraph => (
          <p key={paragraph} className={styles.wechatParagraph}>
            {paragraph}
          </p>
        ))}
      </div>
    </article>
  )
}
