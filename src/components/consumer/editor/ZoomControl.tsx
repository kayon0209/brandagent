'use client'

import styles from './consumer-editor.module.css'

interface ZoomControlProps {
  zoom: number
  minZoom?: number
  maxZoom?: number
  step?: number
  onZoomChange(zoom: number): void
}

export function ZoomControl({
  zoom,
  minZoom = 0.75,
  maxZoom = 1.5,
  step = 0.1,
  onZoomChange,
}: ZoomControlProps) {
  const round = (value: number) => Math.round(value * 100) / 100
  return (
    <div className={styles.zoomControl} data-testid="zoom-control">
      <button
        type="button"
        aria-label="缩小"
        className={styles.zoomButton}
        disabled={round(zoom - step) < minZoom}
        onClick={() => onZoomChange(round(zoom - step))}
      >
        −
      </button>
      <span aria-hidden className={styles.zoomButton} style={{ cursor: 'default' }}>
        {Math.round(zoom * 100)}%
      </span>
      <button
        type="button"
        aria-label="放大"
        className={styles.zoomButton}
        disabled={round(zoom + step) > maxZoom}
        onClick={() => onZoomChange(round(zoom + step))}
      >
        +
      </button>
    </div>
  )
}
