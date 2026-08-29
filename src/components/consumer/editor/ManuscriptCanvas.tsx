'use client'

import { EditorContent } from '@tiptap/react'

import styles from './consumer-editor.module.css'

interface ManuscriptCanvasProps {
  editor: unknown
  zoom: number
}

export function ManuscriptCanvas({ editor, zoom }: ManuscriptCanvasProps) {
  return (
    <div
      data-testid="manuscript-canvas"
      className={styles.manuscriptCanvas}
      style={{ maxWidth: '720px', zoom: String(zoom) }}
    >
      <div className={styles.draftProse}>
        <EditorContent editor={editor as never} />
      </div>
    </div>
  )
}
