'use client'

/**
 * Xiaohongshu note preview (round-3 WYSIWYG rework).
 *
 * Mimics the XHS app card: image-cover block with the note title
 * overlaid, author row with avatar dot + name, emoji-dense body at app
 * type scale, tag chips at the bottom — the shape a reader actually
 * scrolls past in the feed.
 *
 * Round-3b (2026-09-05, 诉求 2 — 所见即所得): empty content renders the
 * platform skeleton — cover gradient with no text, title slot, author
 * row, 3 paragraph placeholders, 2 tag chips, action bar. The creator
 * always sees the destination shape, even before writing.
 */

import styles from './consumer-preview.module.css'
import { deriveTitle } from './deriveTitle'

interface XiaohongshuPreviewProps {
  data: { content: string }
}

export function XiaohongshuPreview({ data }: XiaohongshuPreviewProps) {
  const trimmed = (data.content ?? '').trim()

  if (!trimmed) {
    return (
      <article
        data-testid="xiaohongshu-preview"
        data-state="skeleton"
        className={styles.xhsShell}
        aria-label="小红书预览骨架"
      >
        <div className={styles.xhsCard}>
          <div className={styles.xhsCoverArea} aria-hidden>
            <span className={styles.xhsCoverText} />
          </div>
          <div className={styles.xhsContent}>
            <div className={styles.skeletonBadge}>版式示意图 · 小红书</div>
            <div className={styles.xiaohongshuTitleSkeleton} aria-hidden />
            <div className={styles.xhsAuthorRow}>
              <span className={styles.xhsAvatar} aria-hidden />
              <span className={styles.xhsAuthorName}>你的小红书</span>
              <span className={styles.xhsFollow}>关注</span>
            </div>
            <div className={styles.xhsBody}>
              <div className={styles.xhsParagraphSkeleton} aria-hidden style={{ width: '88%' }} />
              <div className={styles.xhsParagraphSkeleton} aria-hidden style={{ width: '70%' }} />
              <div className={styles.xhsParagraphSkeleton} aria-hidden style={{ width: '82%' }} />
            </div>
            <ul className={styles.xiaohongshuTags}>
              <li className={styles.xiaohongshuTagSkeleton} aria-hidden># </li>
              <li className={styles.xiaohongshuTagSkeleton} aria-hidden># </li>
            </ul>
            <div className={styles.xhsActionBar} aria-hidden>
              <span>♡ 赞</span>
              <span>💬 评论</span>
              <span>⭐ 收藏</span>
            </div>
          </div>
        </div>
      </article>
    )
  }

  const lines = trimmed.split('\n').map(line => line.trim()).filter(Boolean)
  const title = deriveTitle(trimmed, '小红书笔记')
  const tags = (trimmed.match(/#[^\s#]+/g) ?? []).map(tag => tag.slice(1))
  const bodyLines = lines
    .slice(1)
    .join(' ')
    .replace(/#[^\s#]+/g, '')
    .trim()
  const bodySentences = bodyLines
    .split(/(?<=[。！？!?])/)
    .map(s => s.trim())
    .filter(Boolean)
  // cover copy = first body sentence, visually CLIPPED (like real cover
  // text). When the source is too short to differ from the body text,
  // the cover stays a pure gradient image area — a textless image cover
  // is exactly what real notes do, and it keeps text queries unambiguous.
  const coverSource = bodySentences[0] ?? ''
  const coverText = coverSource.length > 16 ? `${coverSource.slice(0, 16)}…` : coverSource.length === 16 ? coverSource : ''

  return (
    <article data-testid="xiaohongshu-preview" data-state="live" className={styles.xhsShell}>
      <div className={styles.xhsCard}>
        <div className={styles.xhsCoverArea} aria-hidden>
          <span className={styles.xhsCoverText}>{coverText}</span>
        </div>
        <div className={styles.xhsContent}>
          <h3 className={styles.xiaohongshuTitle}>{title}</h3>
          <div className={styles.xhsAuthorRow}>
            <span className={styles.xhsAvatar} aria-hidden />
            <span className={styles.xhsAuthorName}>你的小红书</span>
            <span className={styles.xhsFollow}>关注</span>
          </div>
          <div data-testid="xiaohongshu-body" className={styles.xhsBody}>
            {bodySentences.map((sentence, index) => (
              <p key={index}>{sentence}</p>
            ))}
          </div>
          {tags.length > 0 && (
            <ul data-testid="xiaohongshu-tags" className={styles.xiaohongshuTags}>
              {tags.map(tag => (
                <li key={tag}>#{tag}</li>
              ))}
            </ul>
          )}
          <div className={styles.xhsActionBar} aria-hidden>
            <span>♡ 赞</span>
            <span>💬 评论</span>
            <span>⭐ 收藏</span>
          </div>
        </div>
      </div>
    </article>
  )
}