'use client'

import styles from './consumer-editor.module.css'

const MIN_ZOOM = 0.6
const MAX_ZOOM = 1.6
const STEP = 0.1

interface ZoomControlProps {
  zoom: number
  onZoomChange(zoom: number): void
}

export function ZoomControl({ zoom, onZoomChange }: ZoomControlProps) {
  const round = (value: number) => Math.round(value * 10) / 10
  return (
    <div className={styles.zoomControl} data-testid="zoom-control">
      <button
        type="button"
        aria-label="缩小"
        className={styles.zoomButton}
        disabled={round(zoom - STEP) < MIN_ZOOM}
        onClick={() => onZoomChange(round(zoom - STEP))}
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
        disabled={round(zoom + STEP) > MAX_ZOOM}
        onClick={() => onZoomChange(round(zoom + STEP))}
      >
        +
      </button>
    </div>
  )
}
