'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import styles from './consumer-editor.module.css'

type SaveState = 'idle' | 'saving' | 'saved' | 'failed'

interface CoreIdeaBlockProps {
  coreIdea: string
  onSave?: (coreIdea: string) => Promise<void>
  onOpenMaterials?: () => void
  onGenerateDraft?: () => void
  generating?: boolean
  generationDisabled?: boolean
}

export function CoreIdeaBlock({
  coreIdea,
  onSave,
  onOpenMaterials,
  onGenerateDraft,
  generating = false,
  generationDisabled = false,
}: CoreIdeaBlockProps) {
  const [text, setText] = useState(coreIdea)
  const [savedText, setSavedText] = useState(coreIdea)
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [saveError, setSaveError] = useState<string | null>(null)
  const textRef = useRef(text)
  const previousCoreIdeaRef = useRef(coreIdea)
  const editable = typeof onSave === 'function'

  useEffect(() => { textRef.current = text }, [text])
  useEffect(() => {
    // Only respond to a genuinely newer server prop. A successful local
    // autosave updates savedText first; treating that state change as a
    // server refresh would briefly restore the old prop and lose the edit.
    if (coreIdea === previousCoreIdeaRef.current) return
    previousCoreIdeaRef.current = coreIdea
    if (textRef.current === savedText) {
      setText(coreIdea)
      setSavedText(coreIdea)
    }
  }, [coreIdea, savedText])

  const save = useCallback(async (value: string) => {
    if (!onSave || !value.trim()) {
      if (!value.trim()) {
        setSaveState('failed')
        setSaveError('核心观点不能为空。')
      }
      return
    }
    setSaveState('saving')
    setSaveError(null)
    try {
      await onSave(value)
      setSavedText(value)
      setSaveState('saved')
    } catch {
      // A failed save never replaces the creator's local buffer.
      setSaveState('failed')
      setSaveError('保存失败，请检查网络后重试。')
    }
  }, [onSave])

  useEffect(() => {
    if (!editable || text === savedText || saveState === 'saving') return
    const value = text.trim()
    if (!value) return
    const timer = window.setTimeout(() => { void save(value) }, 600)
    return () => window.clearTimeout(timer)
  }, [editable, save, saveState, savedText, text])

  const dirty = text !== savedText

  if (!editable) {
    return (
      <section data-testid="core-idea-block" data-gap="24" className={styles.coreIdea}>
        <div className={styles.coreIdeaHeading}>
          <p className={styles.coreIdeaLabel}>核心观点</p>
          <span>这篇内容想让读者记住什么？</span>
        </div>
        <p className={styles.coreIdeaText}>{coreIdea}</p>
      </section>
    )
  }

  return (
    <section data-testid="core-idea-block" data-gap="24" className={styles.coreIdea}>
      <div className={styles.coreIdeaHeading}>
        <p className={styles.coreIdeaLabel}>核心观点</p>
        <span>这篇内容想让读者记住什么？</span>
      </div>
      <textarea
        data-testid="core-idea-input"
        className="consumer-text-input"
        rows={2}
        value={text}
        aria-label="核心观点"
        onChange={event => {
          setSaveError(null)
          if (saveState === 'saved' || saveState === 'failed') setSaveState('idle')
          setText(event.target.value)
        }}
        placeholder="一句话说清这篇文章要讲什么"
      />
      <div className={styles.coreIdeaActions}>
        {onOpenMaterials && <button type="button" className={styles.materialAction} onClick={onOpenMaterials}>+ 添加素材</button>}
        {onGenerateDraft && (
          <button
            type="button"
            className={styles.generateDraftAction}
            disabled={generating || generationDisabled || !text.trim()}
            title={generationDisabled ? '本月额度已用完，写作与保存仍可用' : undefined}
            onClick={onGenerateDraft}
          >
            {generating ? '正在生成…' : '生成初稿'} <span aria-hidden>→</span>
          </button>
        )}
        <button
          type="button"
          disabled={!dirty || saveState === 'saving' || !text.trim()}
          /* X9 (09-10 bug report): the button is disabled whenever the
           * 600ms autosave already landed — without an explanation it
           * reads as a dead/fake button. Speak the reason. */
          title={
            !text.trim()
              ? '先写一句核心观点'
              : dirty
                ? '保存这次修改'
                : '改动已自动保存，无需手动保存'
          }
          onClick={() => void save(text.trim())}
        >
          保存
        </button>
        <span className={styles.ideaSaveStatus} aria-live="polite">
          {saveState === 'saving' && '正在保存'}
          {saveState === 'saved' && !dirty && <span data-testid="core-idea-saved">已自动保存</span>}
        </span>
        {saveState === 'failed' && (
          <span className={styles.ideaSaveFailure}>
            <span role="alert" data-testid="core-idea-error">{saveError}</span>
            <button type="button" data-testid="core-idea-retry" onClick={() => void save(text.trim())}>重试</button>
          </span>
        )}
      </div>
    </section>
  )
}
