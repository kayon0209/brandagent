'use client'

/**
 * WeChat Official-Article preview (round-3 WYSIWYG rework).
 *
 * Mimics the in-article reading page of a 公众号 article: centered white
 * card, serif-feeling title with meta line (author placeholder +
 * publish-ish date), 15px/1.75 body paragraphs, blockquote styling for
 * quoted lines, and the classic WeChat footer hint — what the creator
 * sees is what their reader will see.
 *
 * Round-3b (2026-09-05, 诉求 2 — 所见即所得): when the content is empty,
 * render the platform's structural skeleton (title slot, meta line,
 * paragraph placeholders, END marker) so the creator sees the destination
 * shape even BEFORE writing. A blank right rail with no preview had been
 * the biggest reason the page felt "功能指向不明" — the tabs sat there
 * inert and the user had no signal what the platform would look like.
 */

import styles from './consumer-preview.module.css'
import { deriveTitle } from './deriveTitle'

interface WeChatPreviewProps {
  data: { content: string }
}

export function WeChatPreview({ data }: WeChatPreviewProps) {
  const trimmed = (data.content ?? '').trim()

  if (!trimmed) {
    // structural skeleton — gray placeholders show where text will land
    return (
      <article
        data-testid="wechat-preview"
        data-state="skeleton"
        className={styles.wechatShell}
        aria-label="公众号预览骨架"
      >
        <div className={styles.wechatCard}>
          <div className={styles.skeletonBadge}>版式示意图 · 公众号</div>
          <div className={styles.wechatTitleSkeleton} aria-hidden />
          <div className={styles.wechatMeta}>
            <span className={styles.wechatAuthor}>BrandAgent</span>
            <span aria-hidden>·</span>
            <span>今天</span>
            <span aria-hidden>·</span>
            <span>图文</span>
          </div>
          <div className={styles.wechatBody} data-testid="wechat-paragraphs">
            <div className={styles.wechatParagraphSkeleton} aria-hidden style={{ width: '92%' }} />
            <div className={styles.wechatParagraphSkeleton} aria-hidden style={{ width: '78%' }} />
            <div className={styles.wechatQuoteSkeleton} aria-hidden />
            <div className={styles.wechatParagraphSkeleton} aria-hidden style={{ width: '85%' }} />
            <div className={styles.wechatParagraphSkeleton} aria-hidden style={{ width: '60%' }} />
          </div>
          <div className={styles.wechatFooter}>
            <span aria-hidden>·</span> END <span aria-hidden>·</span>
          </div>
        </div>
      </article>
    )
  }

  const paragraphs = trimmed.split('\n').map(p => p.trim()).filter(Boolean)
  const title = deriveTitle(trimmed, '公众号文章')
  // body excludes the title line when there is more than one line; a
  // single-line draft is the LIVE-TYPING norm in draft mode, and an empty
  // body area there reads as a broken panel — the one real line renders.
  const body = paragraphs.length > 1 ? paragraphs.slice(1) : paragraphs

  const isQuote = (text: string) => text.startsWith('「') || text.startsWith('“') || text.startsWith('"')

  return (
    <article data-testid="wechat-preview" data-state="live" className={styles.wechatShell}>
      <div className={styles.wechatCard}>
        <h3 data-testid="wechat-preview-title" className={styles.wechatTitle}>
          {title}
        </h3>
        <div className={styles.wechatMeta}>
          <span className={styles.wechatAuthor}>BrandAgent</span>
          <span aria-hidden>·</span>
          <span>今天</span>
          <span aria-hidden>·</span>
          <span>图文</span>
        </div>
        <div data-testid="wechat-paragraphs" className={styles.wechatBody}>
          {body.map((paragraph, index) =>
            isQuote(paragraph) ? (
              <blockquote key={index} className={styles.wechatQuote}>
                {paragraph}
              </blockquote>
            ) : (
              <p key={index} className={styles.wechatParagraph}>
                {paragraph}
              </p>
            ),
          )}
        </div>
        <div className={styles.wechatFooter}>
          <span aria-hidden>·</span> END <span aria-hidden>·</span>
        </div>
      </div>
    </article>
  )
}