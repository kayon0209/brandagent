'use client'

import type { Editor } from '@tiptap/core'
import type { ReactNode } from 'react'
import { EditorContent } from '@tiptap/react'

import styles from './consumer-editor.module.css'

interface ManuscriptCanvasProps {
  editor: Editor | null
  zoom: number
  wordCount: number
  /** Renders between the toolbar and the prose — the core-idea card sits
   * INSIDE the paper per the desktop reference, not floating above it. */
  children?: ReactNode
}

export function ManuscriptCanvas({ editor, zoom, wordCount, children }: ManuscriptCanvasProps) {
  return (
    <article data-testid="manuscript-canvas" className={styles.manuscriptCanvas} style={{ maxWidth: '840px', zoom: String(zoom) }}>
      <div className={styles.documentToolbar} role="toolbar" aria-label="稿件格式">
        <span className={styles.toolbarLabel}>正文</span>
        <ToolbarButton editor={editor} label="加粗" active={editor?.isActive('bold') ?? false} command={() => editor?.chain().focus().toggleBold().run()}><strong>B</strong></ToolbarButton>
        <ToolbarButton editor={editor} label="斜体" active={editor?.isActive('italic') ?? false} command={() => editor?.chain().focus().toggleItalic().run()}><em>I</em></ToolbarButton>
        <ToolbarButton editor={editor} label="下划线" active={editor?.isActive('underline') ?? false} command={() => editor?.chain().focus().toggleUnderline?.().run()}><u>U</u></ToolbarButton>
        <ToolbarButton editor={editor} label="引用" active={editor?.isActive('blockquote') ?? false} command={() => editor?.chain().focus().toggleBlockquote().run()}>❝</ToolbarButton>
        <span className={styles.toolbarDivider} aria-hidden />
        <ToolbarButton editor={editor} label="项目符号列表" active={editor?.isActive('bulletList') ?? false} command={() => editor?.chain().focus().toggleBulletList().run()}>•≡</ToolbarButton>
        <ToolbarButton editor={editor} label="有序列表" active={editor?.isActive('orderedList') ?? false} command={() => editor?.chain().focus().toggleOrderedList().run()}>1≡</ToolbarButton>
        <span className={styles.toolbarSpacer} />
        <ToolbarButton editor={editor} label="撤销" command={() => editor?.chain().focus().undo().run()} disabled={!editor?.can().undo()}>↶</ToolbarButton>
        <ToolbarButton editor={editor} label="重做" command={() => editor?.chain().focus().redo().run()} disabled={!editor?.can().redo()}>↷</ToolbarButton>
        <span className={styles.toolbarDivider} aria-hidden />
        <button type="button" className={styles.suggestButton} title="选中一句话后，这里提供 AI 改写建议" onClick={() => editor?.chain().focus().run()}>
          ✨ 写作建议
        </button>
      </div>
      {children}
      <div className={styles.draftProse}>
        <EditorContent editor={editor} />
      </div>
      {wordCount === 0 && <p className={styles.emptyDraftHint}>开始生成内容，或直接写下你的草稿……</p>}
      <div className={styles.canvasMetaRow}>
        <span className={styles.canvasHint}>选中句子，可让 AI 展开或改写</span>
        <span className={styles.canvasCount}>共 {wordCount.toLocaleString('zh-CN')} 字</span>
      </div>
    </article>
  )
}

function ToolbarButton({
  editor,
  label,
  active = false,
  disabled = false,
  command,
  children,
}: {
  editor: Editor | null
  label: string
  active?: boolean
  disabled?: boolean
  command(): void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      className={styles.documentToolbarButton}
      aria-label={label}
      aria-pressed={active || undefined}
      disabled={!editor || disabled}
      onClick={command}
    >
      {children}
    </button>
  )
}
