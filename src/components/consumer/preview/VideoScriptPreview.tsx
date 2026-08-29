'use client'

import styles from './consumer-preview.module.css'

interface VideoScriptPreviewProps {
  data: { duration_seconds: number; lines: string[] }
}

/** Evenly distribute the script lines across the clip duration. */
function timecode(index: number, total: number, durationSeconds: number): string {
  const per = durationSeconds / Math.max(total, 1)
  const at = Math.round(index * per)
  return `${String(Math.floor(at / 60)).padStart(2, '0')}:${String(at % 60).padStart(2, '0')}`
}

export function VideoScriptPreview({ data }: VideoScriptPreviewProps) {
  return (
    <article data-testid="video-script-preview" className={styles.videoScript}>
      <p className={styles.videoDuration}>时长约 {data.duration_seconds} 秒</p>
      <ol data-testid="video-script-lines" className={styles.videoLines}>
        {data.lines.map((line, index) => (
          <li key={line} className={styles.videoLine}>
            <span className={styles.videoTime}>{timecode(index, data.lines.length, data.duration_seconds)}</span>
            <span className={styles.videoText}>{line}</span>
          </li>
        ))}
      </ol>
    </article>
  )
}
