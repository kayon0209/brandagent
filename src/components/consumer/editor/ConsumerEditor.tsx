'use client'

/**
 * Consumer manuscript editor (upgrade plan task 10).
 *
 * Wires the tiptap editor to the useConsumerDraft autosave state machine,
 * hosts the selection toolbar anchored to the real selection, and the
 * suggestion flow (propose -> popover -> atomic accept).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Editor } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'

import { CoreIdeaBlock } from './CoreIdeaBlock'
import { ManuscriptCanvas } from './ManuscriptCanvas'
import { SaveStatus } from './SaveStatus'
import { SelectionToolbar, type AssistAction } from './SelectionToolbar'
import { SuggestionPopover } from './SuggestionPopover'
import { ZoomControl } from './ZoomControl'
import { useConsumerDraft, type ConsumerDraftApi } from '@/hooks/useConsumerDraft'
import styles from './consumer-editor.module.css'

const ACTION_LABELS: Record<AssistAction, string> = {
  expand: '展开',
  replace_example: '换例子',
  shorten: '精简',
}

interface ConsumerEditorProps {
  projectId: string
  coreIdea: string
  api: ConsumerDraftApi
}

export function ConsumerEditor({ projectId, coreIdea, api }: ConsumerEditorProps) {
  const draft = useConsumerDraft(projectId, api)
  const [zoom, setZoom] = useState(1)
  const [toolbarHidden, setToolbarHidden] = useState(false)
  const [selectionInfo, setSelectionInfo] = useState<{ from: number; to: number; empty: boolean; text: string } | null>(null)
  const [suggesting, setSuggesting] = useState<AssistAction | null>(null)
  const [suggestion, setSuggestion] = useState<{ text: string; suggestionId: string } | null>(null)
  const [selectionRect, setSelectionRect] = useState<{ getBoundingClientRect(): DOMRect } | null>(null)
  const editorRef = useRef<Editor | null>(null)

  const markDirtyRef = useRef(draft.markDirty)
  markDirtyRef.current = draft.markDirty

  const editor = useMemo(() => {
    const created = new Editor({
      extensions: [
        StarterKit,
        Placeholder.configure({ placeholder: '从这里开始写下你的想法…' }),
      ],
      content: '<p></p>',
      onUpdate: ({ editor: current }) => {
        const text = current.getText()
        markDirtyRef.current({ blocks: [{ block_id: 'b1', block_type: 'paragraph', text }] }, text)
      },
      onSelectionUpdate: ({ editor: current }) => {
        const { from, to, empty } = current.state.selection
        const text = current.state.doc.textBetween(from, to, ' ')
        setSelectionInfo({ from, to, empty, text })
        setToolbarHidden(false)
        if (!empty) {
          const selection = window.getSelection()
          if (selection && selection.rangeCount > 0) {
            setSelectionRect(selection.getRangeAt(0).cloneRange())
          }
        } else {
          setSelectionRect(null)
        }
      },
      onBlur: () => setToolbarHidden(true),
    })
    editorRef.current = created
    return created
  }, [])

  useEffect(() => {
    return () => {
      editor.destroy()
    }
  }, [editor])

  // seed the editor once the server draft arrives (first paint only)
  useEffect(() => {
    const current = editorRef.current
    if (draft.document && current && !current.isDestroyed && !current.state.doc.textContent) {
      const first = (draft.document.blocks as Array<{ text?: string }>)[0]
      if (first?.text) {
        current.commands.setContent(`<p>${first.text}</p>`, { emitUpdate: false })
      }
    }
  }, [draft.document])

  // Escape hides the toolbar and dismisses any suggestion
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setToolbarHidden(true)
        setSuggestion(null)
        setSuggesting(null)
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [])

  const currentSelection = useMemo(
    () => ({
      selection: { from: selectionInfo?.from ?? 0, to: selectionInfo?.to ?? 0, empty: selectionInfo?.empty ?? true },
    }),
    [selectionInfo],
  )

  const handleToolbarAction = useCallback(
    async (action: AssistAction) => {
      if (!selectionInfo || selectionInfo.empty || !selectionInfo.text) return
      setSuggesting(action)
      try {
        const result = (await api.proposeSuggestion({
          projectId,
          action,
          selectedText: selectionInfo.text,
          blockId: 'b1',
          baseRevision: draft.revision,
        })) as { suggestion_id?: string; suggested_text?: string }
        if (!result?.suggested_text) {
          setSuggestion(null)
          return
        }
        setSuggestion({ text: result.suggested_text, suggestionId: result.suggestion_id ?? '' })
      } catch {
        setSuggestion(null)
      }
    },
    [api, draft.revision, projectId, selectionInfo],
  )

  const handleAccept = useCallback(async () => {
    if (!suggestion) return
    try {
      await api.acceptSuggestion({
        projectId,
        suggestionId: suggestion.suggestionId,
        baseRevision: draft.revision,
      })
      await draft.reload()
    } catch {
      /* conflict keeps the local draft; status shows recovery entry */
    } finally {
      setSuggestion(null)
      setSuggesting(null)
    }
  }, [api, draft, projectId, suggestion])

  return (
    <div className={styles.shell}>
      <header data-testid="consumer-header" className={styles.header}>
        <span className={styles.headerTitle}>{coreIdea}</span>
      </header>

      <div className={styles.main}>
        <div className={styles.manuscriptColumn}>
          <CoreIdeaBlock coreIdea={coreIdea} />
          <ManuscriptCanvas editor={editor} zoom={zoom} />
        </div>
      </div>

      <SelectionToolbar
        editorState={currentSelection}
        rangeRect={selectionRect ?? undefined}
        hidden={toolbarHidden}
        onAction={handleToolbarAction}
        busy={suggesting !== null}
      />

      {suggestion && selectionRect && (
        <SuggestionPopover
          actionLabel={suggesting ? ACTION_LABELS[suggesting] : ''}
          suggestedText={suggestion.text}
          busy={false}
          position={{ x: 80, y: 80 }}
          onAccept={() => void handleAccept()}
          onDismiss={() => {
            setSuggestion(null)
            setSuggesting(null)
          }}
        />
      )}

      <SaveStatus state={draft.status} onResolveConflict={() => void draft.resolveConflict()} />
      <ZoomControl zoom={zoom} onZoomChange={setZoom} />
    </div>
  )
}
