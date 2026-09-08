'use client'

/**
 * P1-3: the core idea is EDITABLE on the write page. Saving goes through
 * the project PATCH API with honest feedback (saving / saved / failed +
 * retry) — a failed save never renders as saved, and the draft/variant
 * generation reads the updated project on the server, so the flow stays
 * consistent after an edit.
 */

import { useEffect, useRef, useState } from 'react'

import styles from './consumer-editor.module.css'

type SaveState = 'idle' | 'saving' | 'saved' | 'failed'

interface CoreIdeaBlockProps {
  coreIdea: string
  /** Persist the edited idea (project PATCH). Absent -> read-only display. */
  onSave?: (coreIdea: string) => Promise<void>
}

export function CoreIdeaBlock({ coreIdea, onSave }: CoreIdeaBlockProps) {
  const [text, setText] = useState(coreIdea)
  const [savedText, setSavedText] = useState(coreIdea)
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [saveError, setSaveError] = useState<string | null>(null)
  const editable = typeof onSave === 'function'
  // the server value can arrive after mount (project fetch) — sync the
  // editor buffer only while the user is NOT mid-edit
  const editingRef = useRef(false)

  useEffect(() => {
    if (!editingRef.current) {
      setText(coreIdea)
      setSavedText(coreIdea)
    }
  }, [coreIdea])

  if (!editable) {
    return (
      <section
        data-testid="core-idea-block"
        data-gap="32"
        className={styles.coreIdea}
        style={{ marginBottom: '32px' }}
      >
        <p className={styles.coreIdeaLabel}>核心观点</p>
        <p className={styles.coreIdeaText}>{coreIdea}</p>
      </section>
    )
  }

  const dirty = text !== savedText

  async function save() {
    if (!dirty || saveState === 'saving') return
    const value = text.trim()
    if (!value) {
      setSaveState('failed')
      setSaveError('核心观点不能为空。')
      return
    }
    setSaveState('saving')
    setSaveError(null)
    try {
      await onSave?.(value)
      editingRef.current = false
      setSavedText(value)
      setSaveState('saved')
    } catch {
      // keep the buffer; the server value did not change — the UI must
      // never pretend a failed PATCH succeeded
      setSaveState('failed')
      setSaveError('保存失败，请检查网络后重试。')
    }
  }

  return (
    <section
      data-testid="core-idea-block"
      data-gap="32"
      className={styles.coreIdea}
      style={{ marginBottom: '32px' }}
    >
      <p className={styles.coreIdeaLabel}>这篇内容最想让读者记住什么？</p>
      <textarea
        data-testid="core-idea-input"
        className="consumer-text-input"
        rows={2}
        value={text}
        aria-label="核心观点"
        onChange={event => {
          editingRef.current = true
          if (saveState === 'saved') setSaveState('idle')
          setText(event.target.value)
        }}
        placeholder="一句话说清这篇文章要讲什么"
      />
      <div>
        <button
          type="button"
          className="consumer-primary-button"
          disabled={saveState === 'saving' || !dirty}
          onClick={() => void save()}
        >
          {saveState === 'saving' ? '正在保存…' : dirty ? '保存' : '保存观点'}
        </button>
        {saveState === 'saved' && (
          <span role="status" data-testid="core-idea-saved">
            已保存
          </span>
        )}
        {saveState === 'failed' && (
          <span>
            <span role="alert" data-testid="core-idea-error">
              {saveError}
            </span>
            <button
              type="button"
              data-testid="core-idea-retry"
              onClick={() => void save()}
            >
              重试
            </button>
          </span>
        )}
      </div>
    </section>
  )
}
