'use client'

import styles from './consumer-preview.module.css'

interface VideoScriptPreviewProps {
  data: { duration_seconds: number; lines: string[] }
}

export function VideoScriptPreview({ data }: VideoScriptPreviewProps) {
  return (
    <article data-testid="video-script-preview" className={styles.videoScript}>
      <p className={styles.videoDuration}>时长约 {data.duration_seconds} 秒</p>
      <ol data-testid="video-script-lines" className={styles.videoLines}>
        {data.lines.map(line => (
          <li key={line}>{line}</li>
        ))}
      </ol>
    </article>
  )
}
