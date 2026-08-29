'use client'

import styles from './consumer-preview.module.css'
import { deriveTitle } from './deriveTitle'

interface WeChatPreviewProps {
  data: { content: string }
}

export function WeChatPreview({ data }: WeChatPreviewProps) {
  const paragraphs = data.content.split('\n').map(p => p.trim()).filter(Boolean)
  const [title, ...body] = paragraphs
  return (
    <article data-testid="wechat-preview" className={styles.wechat}>
      <h3 className={styles.wechatTitle}>{deriveTitle(data.content, '公众号文章')}</h3>
      <div data-testid="wechat-paragraphs">
        {body.map(paragraph => (
          <p key={paragraph} className={styles.wechatParagraph}>
            {paragraph}
          </p>
        ))}
      </div>
    </article>
  )
}
