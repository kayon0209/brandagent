'use client'

/**
 * 60s spoken-script preview (round-3 WYSIWYG rework).
 *
 * Mimics a teleprompter script sheet: header strip with duration and
 * pace (words-per-minute estimate), then timestamped rows with a play
 * cursor for the CURRENT line rendered like a recording session — the
 * exact artifact a creator hands to the camera.
 *
 * Round-3b (2026-09-05, 诉求 2 — 所见即所得): when there are no lines
 * yet, render a 60-second timeline with placeholder script rows so the
 * creator sees the pace budget and the shot-by-shot structure before
 * typing the first line.
 */

import { useState } from 'react'

import styles from './consumer-preview.module.css'

interface VideoScriptPreviewProps {
  data: { duration_seconds: number; lines: string[] }
}

const SKELETON_LINES = 6

/** Evenly distribute the script lines across the clip duration. */
function timecode(index: number, total: number, durationSeconds: number): string {
  const per = durationSeconds / Math.max(total, 1)
  const at = Math.round(index * per)
  return `${String(Math.floor(at / 60)).padStart(2, '0')}:${String(at % 60).padStart(2, '0')}`
}

export function VideoScriptPreview({ data }: VideoScriptPreviewProps) {
  const totalCharacters = data.lines.join('').length
  const wpm = data.duration_seconds > 0 ? Math.round((totalCharacters / data.duration_seconds) * 60) : 0
  const [current, setCurrent] = useState(0)

  if (!data.lines || data.lines.length === 0) {
    const skeletonCount = SKELETON_LINES
    return (
      <article
        data-testid="video-script-preview"
        data-state="skeleton"
        className={styles.teleprompter}
        aria-label="60 秒口播预览骨架"
      >
        <header className={styles.teleHeader}>
          <span className={styles.teleDuration}>{data.duration_seconds} 秒口播</span>
          <span className={styles.telePace}>语速预算 ≈ 220 字/分钟</span>
          <span className={styles.skeletonBadge}>版式示意图</span>
        </header>
        <ol className={styles.videoLines}>
          {Array.from({ length: skeletonCount }).map((_, index) => (
            <li key={index} className={styles.videoLine}>
              <span className={styles.videoTime}>
                {timecode(index, skeletonCount, data.duration_seconds)}
              </span>
              <span className={styles.videoTextSkeleton} aria-hidden style={{ width: `${70 + (index % 3) * 10}%` }} />
            </li>
          ))}
        </ol>
        <footer className={styles.teleFooter} role="status">
          骨架：等写完正文就会按时间线填入。
        </footer>
      </article>
    )
  }

  return (
    <article data-testid="video-script-preview" data-state="live" className={styles.teleprompter}>
      <header className={styles.teleHeader}>
        <span className={styles.teleDuration}>{data.duration_seconds} 秒口播</span>
        <span className={styles.telePace}>语速约 {wpm} 字/分钟{wpm > 320 ? '（偏快，注意喘气）' : wpm > 0 && wpm < 160 ? '（偏慢，可加内容）' : ''}</span>
      </header>
      <ol data-testid="video-script-lines" className={styles.videoLines}>
        {data.lines.map((line, index) => (
          <li
            key={index}
            className={`${styles.videoLine} ${index === current ? styles.videoLineActive : ''}`}
            onClick={() => setCurrent(index)}
          >
            <span className={styles.videoTime}>{timecode(index, data.lines.length, data.duration_seconds)}</span>
            <span className={styles.videoText}>{line}</span>
          </li>
        ))}
      </ol>
      <footer className={styles.teleFooter} role="status">
        第 {current + 1} / {data.lines.length} 句 · 点击任意一行可像提词器一样跟随
      </footer>
    </article>
  )
}