'use client'

/**
 * Floating toolbar that anchors to the REAL selection rect (plan task 10).
 *
 * Position algorithm (upgrade plan Step 3):
 *  1. take from/to from the editor state
 *  2. map to a DOM range (injected by the parent through `rangeRect`)
 *  3. read getBoundingClientRect
 *  4. prefer 8px above the selection; if there is no room, drop below
 *  5. clamp to at least 12px from the viewport edges
 *  6. viewport-fixed positioning; the parent recalcs on scroll/resize/selection update
 */

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

import styles from './consumer-editor.module.css'

export const ASSIST_ACTIONS = [
  { action: 'expand', label: '展开说说' },
  { action: 'replace_example', label: '换个例子' },
  { action: 'shorten', label: '短一点' },
] as const

export type AssistAction = (typeof ASSIST_ACTIONS)[number]['action']

const TOOLBAR_WIDTH = 148
const TOP_GAP = 8
const VIEWPORT_MARGIN = 12

interface SelectionToolbarProps {
  editorState: { selection: { from: number; to: number; empty: boolean } }
  rangeRect?: { getBoundingClientRect(): DOMRect }
  hidden?: boolean
  onAction?(action: AssistAction): void
  busy?: boolean
}

export function SelectionToolbar({ editorState, rangeRect, hidden, onAction, busy }: SelectionToolbarProps) {
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null)

  const selection = editorState?.selection

  useEffect(() => {
    if (!rangeRect || !selection || selection.empty) {
      setPosition(null)
      return
    }
    const rect = rangeRect.getBoundingClientRect()
    const halfWidth = TOOLBAR_WIDTH / 2
    let x = (rect.left + rect.right) / 2 - halfWidth
    let y: number
    if (rect.top - TOP_GAP - 36 >= VIEWPORT_MARGIN) {
      y = rect.top - TOP_GAP - 36
    } else {
      y = rect.bottom + TOP_GAP
    }
    x = Math.max(x, VIEWPORT_MARGIN)
    x = Math.min(x, window.innerWidth - TOOLBAR_WIDTH - VIEWPORT_MARGIN)
    // P1-4: the selection can sit outside the viewport (long page, zoom,
    // scroll) — the toolbar is position:fixed and must stay VISIBLE, so
    // clamp y into the viewport instead of following the rect off-screen.
    y = Math.max(y, VIEWPORT_MARGIN)
    y = Math.min(y, window.innerHeight - 44 - VIEWPORT_MARGIN)
    setPosition({ x, y })
  }, [rangeRect, selection])

  // P1-4: reposition on viewport changes (scroll/resize/zoom) — a stale
  // rect leaves the toolbar pinned at old coordinates
  useEffect(() => {
    if (!position) return
    const recompute = () => {
      const current = position
      setPosition({
        x: Math.min(Math.max(current.x, VIEWPORT_MARGIN), window.innerWidth - TOOLBAR_WIDTH - VIEWPORT_MARGIN),
        y: Math.min(Math.max(current.y, VIEWPORT_MARGIN), window.innerHeight - 44 - VIEWPORT_MARGIN),
      })
    }
    window.addEventListener('resize', recompute)
    window.addEventListener('scroll', recompute, true)
    return () => {
      window.removeEventListener('resize', recompute)
      window.removeEventListener('scroll', recompute, true)
    }
  }, [position])

  if (!selection || selection.empty || hidden || !position) {
    return null
  }

  // P1-4 fix: portal to document.body with top/left. A `transform` on a
  // fixed-position element makes ANCESTOR transforms/zoom (the manuscript
  // canvas uses CSS zoom) its containing block, silently pinning the
  // toolbar off-viewport (observed: transform y=368 rendered at y=926).
  // Portaling out of the zoomed tree + explicit top/left removes the
  // dependency on ancestor coordinate spaces entirely.
  return createPortal(
    <div
      data-testid="selection-toolbar"
      className={styles.toolbar}
      role="toolbar"
      style={{
        top: `${position.y}px`,
        left: `${position.x}px`,
        right: 'auto',
      }}
    >
      {ASSIST_ACTIONS.map(({ action, label }) => (
        <button
          key={action}
          type="button"
          className={busy ? styles.pillButtonBusy : styles.pillButton}
          disabled={busy}
          onMouseDown={event => event.preventDefault()} // keep the selection alive
          onClick={() => onAction?.(action)}
        >
          {label}
        </button>
      ))}
    </div>,
    document.body,
  )
}
