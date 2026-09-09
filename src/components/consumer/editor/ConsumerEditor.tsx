'use client'

/**
 * Consumer manuscript editor (upgrade plan task 10 + Phase 5 review fixes).
 *
 * - tiptap paragraphs map 1:1 to document blocks (no more single-b1 collapse);
 * - the editor re-seeds from the server document whenever seedVersion bumps
 *   (accepted suggestions and conflict recovery are never silently reverted);
 * - the suggestion popover anchors to the real selection rect;
 * - zoom is 75%—150% persisted in localStorage (plan L152) and only scales
 *   the manuscript canvas; the status bar carries the word count.
 */

import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { Editor } from '@tiptap/core'
import { useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'

import { CoreIdeaBlock } from './CoreIdeaBlock'
import { ManuscriptCanvas } from './ManuscriptCanvas'
import { SelectionToolbar, type AssistAction } from './SelectionToolbar'
import { SuggestionPopover } from './SuggestionPopover'
import { useConsumerDraft, type ConsumerDraftApi } from '@/hooks/useConsumerDraft'
import styles from './consumer-editor.module.css'
import { newIdempotencyKey } from '@/lib/idempotency'

const ACTION_LABELS: Record<AssistAction, string> = {
  expand: '展开说说',
  replace_example: '换个例子',
  shorten: '短一点',
}

const ZOOM_MIN = 0.75
const ZOOM_MAX = 1.5
const ZOOM_STEP = 0.1
const ZOOM_STORAGE_KEY = 'brandagent:zoom'
const SEED_RADIUS = 120


interface Block {
  block_id: string
  block_type: string
  text: string
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function blocksToHtml(blocks: Block[]): string {
  return (
    blocks
      .map(block => `<p>${escapeHtml(block.text ?? '')}</p>`)
      .join('\n') || '<p></p>'
  )
}

function editorToBlocks(editor: Editor): Block[] {
  const blocks: Block[] = []
  editor.state.doc.forEach((node, _, index) => {
    if (node.isTextblock) {
      blocks.push({ block_id: `b${index + 1}`, block_type: 'paragraph', text: node.textContent })
    }
  })
  return blocks.length ? blocks : [{ block_id: 'b1', block_type: 'paragraph', text: '' }]
}

/** Resolve the selection to its real block id and character offsets
 * inside that block's text (the plan's block anchor contract:
 * blockId + block-local offsets + text hash — never plain_text.find). */
function resolveSelectionAnchor(
  editor: Editor,
  from: number,
  to: number,
): { blockId: string; startOffset: number; endOffset: number } | null {
  let resolved: { blockId: string; startOffset: number; endOffset: number } | null = null
  editor.state.doc.forEach((node, pos, index) => {
    if (resolved || !node.isTextblock) return
    const blockEnd = pos + node.nodeSize
    if (from >= pos && from <= blockEnd && to <= blockEnd) {
      resolved = {
        blockId: `b${index + 1}`,
        startOffset: from - pos - 1,
        endOffset: to - pos - 2,
      }
    }
  })
  return resolved
}

export interface ConsumerEditorHandle {
  /** Adopt the CURRENT draft: flush pending edits first, then send the
   * real revision (review P0: hardcoded baseRevision:0 broke the lifecycle). */
  adoptCurrent(): Promise<void>
  /** Re-seed the editor from the server draft (used after a first-draft
   * candidate is applied outside the editor, e.g. the empty-state button). */
  reloadDraft(): Promise<void>
  /** round-3g A3: secondary action bar hook — runs an assist action on the
   * CURRENT selection (or speaks the no-selection guidance). Returns the
   * spoken outcome so the page layer never guesses editor internals. */
  triggerAssist(action: AssistAction | 'change_tone'): Promise<string>
}

/** Live statusbar payload: the page owns the v4 statusbar chrome, the
 * editor owns the state behind it (save machine, word count, zoom). */
export interface EditorStatusPayload {
  saveState: 'loading' | 'saved' | 'dirty' | 'saving' | 'conflict' | 'error'
  wordCount: number
  zoom: number
  resolveConflict(): void
  /** N4: surfaced so the status bar can offer an explicit save retry */
  retrySave(): void
  changeZoom(zoom: number): void
  /** 诉求 2 (WYSIWYG, round-3b): the live plain-text view of the draft,
   * updated on every keystroke, so the platform preview rail can render
   * the creator's writing in the destination's layout in real time. */
  plainText: string
}

interface ConsumerEditorProps {
  projectId: string
  coreIdea: string
  api: ConsumerDraftApi
  onAdopted?(): void
  onStatus?(status: EditorStatusPayload): void
  onSaveCoreIdea?(coreIdea: string): Promise<void>
  onOpenMaterials?(): void
  onGenerateDraft?(): void
  generating?: boolean
  generationDisabled?: boolean
}

export const ConsumerEditor = forwardRef<ConsumerEditorHandle, ConsumerEditorProps>(
  function ConsumerEditor({ projectId, coreIdea, api, onAdopted, onStatus, onSaveCoreIdea, onOpenMaterials, onGenerateDraft, generating, generationDisabled }, ref) {
  const draft = useConsumerDraft(projectId, api)
  const [zoom, setZoom] = useState(() => {
    try {
      const stored = window.localStorage.getItem(ZOOM_STORAGE_KEY)
      const value = stored ? Number(stored) : 1
      return Number.isFinite(value) ? Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, value)) : 1
    } catch {
      return 1
    }
  })
  const [wordCount, setWordCount] = useState(0)
  // 诉求 2 (WYSIWYG): mirror the draft's plain text so the page can hand
  // it to the platform preview rail. Empty when there is no content yet.
  const [plainText, setPlainText] = useState('')
  const [toolbarHidden, setToolbarHidden] = useState(false)
  const [selectionInfo, setSelectionInfo] = useState<{ from: number; to: number; empty: boolean; text: string } | null>(null)
  const [suggesting, setSuggesting] = useState<AssistAction | null>(null)
  const [suggestion, setSuggestion] = useState<{ text: string; suggestionId: string } | null>(null)
  // free-intent panel (agentization P1): refused intents surface as spoken
  // guidance; proposed ones reuse the suggestion popover flow
  const [intentBusy, setIntentBusy] = useState(false)
  const [intentMessage, setIntentMessage] = useState<string | null>(null)
  const [intentLabel, setIntentLabel] = useState<string | null>(null)
  const [selectionRect, setSelectionRect] = useState<{ getBoundingClientRect(): DOMRect } | null>(null)
  const editorRef = useRef<Editor | null>(null)
  const seededSeedRef = useRef(-1)

  const markDirtyRef = useRef(draft.markDirty)
  markDirtyRef.current = draft.markDirty

  // tiptap v3: the mount protocol between Editor and EditorContent only
  // works through useEditor — a raw `new Editor()` renders an empty <div>
  // with zero errors (this round's P0 finding). Component is ssr:false.
  const editor = useEditor({
    extensions: [
      StarterKit,
      Placeholder.configure({ placeholder: '从这里开始写下你的想法…' }),
    ],
    content: '<p></p>',
    onUpdate: ({ editor: current }: { editor: Editor }) => {
      const blocks = editorToBlocks(current)
      const text = current.getText()
      markDirtyRef.current({ blocks }, text)
      setWordCount(text.length)
      // 诉求 2: publish the live draft text alongside the word count so the
      // page can stream it into the platform preview rail
      setPlainText(text)
    },
    onSelectionUpdate: ({ editor: current }: { editor: Editor }) => {
      const { from, to, empty } = current.state.selection
      // N10: a collapsed selection accompanies EVERY keystroke — pushing it
      // through setState re-renders the whole editor tree on each character
      // of typing. Only REAL (non-empty) selections matter to the UI, so a
      // collapsed selection just clears existing state once.
      if (empty) {
        setSelectionInfo(previous => (previous === null || !previous.empty ? null : previous))
        setSelectionRect(null)
        return
      }
      const text = current.state.doc.textBetween(from, to, ' ')
      setSelectionInfo({ from, to, empty, text })
      setToolbarHidden(false)
      const selection = window.getSelection()
      if (selection && selection.rangeCount > 0) {
        setSelectionRect(selection.getRangeAt(0).cloneRange())
      }
    },
    onBlur: () => setToolbarHidden(true),
  })
  editorRef.current = editor

  // seed / re-seed the editor from the server document whenever a fresh
  // load bumps seedVersion — accepted suggestions and recovered drafts
  // overwrite the local buffer (review P1)
  useEffect(() => {
    const current = editorRef.current
    if (!draft.document || !current || draft.seedVersion === seededSeedRef.current) return
    seededSeedRef.current = draft.seedVersion
    const blocks = (draft.document.blocks ?? []) as Block[]
    if (blocks.length) {
      current.commands.setContent(blocksToHtml(blocks), { emitUpdate: false })
      const seedText = current.getText()
      setWordCount(seedText.length)
      // 诉求 2: publish seeded text so the preview rail reflects an already
      // saved draft immediately on first paint
      setPlainText(seedText)
    }
  }, [draft.document, draft.seedVersion])

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

  // keep zoom in the plan range and persist it
  const changeZoom = useCallback((next: number) => {
    const clamped = Math.round(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next)) * 100) / 100
    setZoom(clamped)
    try {
      window.localStorage.setItem(ZOOM_STORAGE_KEY, String(clamped))
    } catch {
      /* storage may be unavailable */
    }
  }, [])

  // push the live statusbar payload to the page whenever any of it moves
  const resolveConflictRef = useRef(() => {})
  resolveConflictRef.current = () => void draft.resolveConflict()
  const retrySaveRef = useRef(() => {})
  retrySaveRef.current = () => void draft.flush()
  useEffect(() => {
    onStatus?.({
      saveState: draft.status,
      wordCount,
      zoom,
      resolveConflict: () => resolveConflictRef.current(),
      retrySave: () => retrySaveRef.current(),
      changeZoom,
      // 诉求 2 (WYSIWYG): live draft text for the right-rail preview
      plainText,
    })
  }, [onStatus, draft.status, wordCount, zoom, changeZoom, plainText])

  const currentSelection = useMemo(
    () => ({
      selection: { from: selectionInfo?.from ?? 0, to: selectionInfo?.to ?? 0, empty: selectionInfo?.empty ?? true },
    }),
    [selectionInfo],
  )

  const popoverPosition = useMemo(() => {
    if (!selectionRect) return null
    const rect = selectionRect.getBoundingClientRect()
    // centered on the selection, clamped into the viewport (plan L505).
    // N3: the lower bound is the common case — rewriting the closing
    // sentence sits near the viewport bottom, and an unclamped popover
    // put its action buttons out of reach
    const halfWidth = SEED_RADIUS
    const x = Math.min(Math.max(rect.left + rect.width / 2 - halfWidth, 12), window.innerWidth - SEED_RADIUS * 2 - 12)
    const POPOVER_HEIGHT = 220
    const y = Math.min(Math.max(rect.top - 8 - POPOVER_HEIGHT, 12), window.innerHeight - POPOVER_HEIGHT - 12)
    return { x, y }
  }, [selectionRect])

  const handleToolbarAction = useCallback(
    async (action: AssistAction) => {
      if (!selectionInfo || selectionInfo.empty || !selectionInfo.text) return
      const editor = editorRef.current
      if (!editor) return
      const anchor = resolveSelectionAnchor(editor, selectionInfo.from, selectionInfo.to)
      if (!anchor) return
      setSuggesting(action)
      // P1-2: one toolbar action = one idempotency key; the same action's
      // automatic retries reuse it so the model is never called twice
      const idempotencyKey = newIdempotencyKey()
      try {
        const result = (await api.proposeSuggestion({
          projectId,
          action,
          selectedText: selectionInfo.text,
          blockId: anchor.blockId,
          startOffset: anchor.startOffset,
          endOffset: anchor.endOffset,
          baseRevision: draft.revision,
          idempotencyKey,
        })) as { suggestion_id?: string; suggested_text?: string }
        if (!result?.suggested_text) {
          // X2: a guard refusal must be VISIBLE — a silent no-op after a
          // click reads as "the button is broken"
          setSuggestion(null)
          setIntentMessage('这句话里出现了没法核实的新事实，AI 按规则拒绝改写。换一句或先关联素材再试。')
          return
        }
        setIntentMessage(null)
        setSuggestion({ text: result.suggested_text, suggestionId: result.suggestion_id ?? '' })
      } catch {
        // A lost provider response leaves execution uncertain. Never promise
        // that a new user action is free: the ledger conservatively retains
        // the estimated quota for the original request.
        setSuggestion(null)
        setIntentMessage('这次生成没有返回结果，你的稿子没有任何改动。提供方可能已执行请求，预估额度可能已计入；再次生成会作为一次新请求。')
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
      // reload re-seeds the editor with the accepted text (seedVersion bump)
      await draft.reload()
    } catch {
      /* conflict keeps the local draft; status shows the recovery entry */
    } finally {
      setSuggestion(null)
      setSuggesting(null)
      setIntentLabel(null)
    }
  }, [api, draft, projectId, suggestion])

  // Free-intent propose: classify -> anchored propose -> suggestion
  // popover; refusals are normal outcomes shown as guidance in the panel
  const handleIntentAction = useCallback(
    async (intent: string) => {
      if (!selectionInfo || selectionInfo.empty || !selectionInfo.text) return
      const editor = editorRef.current
      if (!editor) return
      const anchor = resolveSelectionAnchor(editor, selectionInfo.from, selectionInfo.to)
      if (!anchor) return
      setIntentBusy(true)
      setIntentMessage(null)
      // one intent ask = one idempotency key (P1-2 contract)
      const idempotencyKey = newIdempotencyKey()
      try {
        const { proposeConsumerIntent } = await import('@/lib/api/consumer-drafts')
        const result = await proposeConsumerIntent({
          projectId,
          intent,
          selectedText: selectionInfo.text,
          blockId: anchor.blockId,
          startOffset: anchor.startOffset,
          endOffset: anchor.endOffset,
          baseRevision: draft.revision,
          idempotencyKey,
        })
        if (result.status === 'proposed' && result.suggested_text) {
          setSuggesting('expand') // keeps the popover busy-label slot non-empty
          setIntentLabel('按你的想法')
          setIntentMessage(null) // a later success clears earlier guidance
          setSuggestion({ text: result.suggested_text, suggestionId: result.suggestion_id ?? '' })
        } else {
          setSuggestion(null)
          setSuggesting(null)
          // X6: refusals end with a next step, never a dead end — the
          // panel stays open with the user's intent editable
          setIntentMessage(
            result.message ??
              '这个改法我帮不了：只能展开、换个说法或精简。改一下描述再点生成试试？'
          )
        }
      } catch {
        // AI failures never modify the draft; guide the user to retry
        setSuggestion(null)
        setSuggesting(null)
        setIntentMessage('这次生成没成功，你的稿子没有任何改动。可以再试一次。')
      } finally {
        setIntentBusy(false)
      }
    },
    [draft.revision, projectId, selectionInfo],
  )

  // adopt uses the REAL post-flush revision (review P0 fix): draft.revision
  // is React state captured when this closure was built — after flush() it
  // is stale. latestRevision() reads the ref the flush actually updated.
  useImperativeHandle(
    ref,
    () => ({
      adoptCurrent: async () => {
        await draft.flush()
        const { brandFlowRequest } = await import('@/lib/api/brandflow')
        await brandFlowRequest(`/api/v1/consumer/projects/${projectId}/draft/adopt`, {
          method: 'POST',
          body: JSON.stringify({ baseRevision: draft.latestRevision() }),
        })
        await draft.reload()
        onAdopted?.()
      },
      reloadDraft: async () => {
        await draft.reload()
      },
      triggerAssist: async (action: AssistAction | 'change_tone') => {
        // round-3g A3: the page-level secondary bar delegates here; the
        // editor owns selection truth, so guidance words come from it
        if (!selectionInfo || selectionInfo.empty || !selectionInfo.text) {
          return '先选中一句话，或告诉我你想改哪里。'
        }
        if (action === 'change_tone') {
          // the free-intent panel is the tone path; open it by speaking the
          // route — the toolbar's 说说怎么改 toggle owns that panel
          return '换个语气：打开选区工具栏里的「说说怎么改」，描述你想要的语气（如「更口语」「更正式」）。'
        }
        await handleToolbarAction(action)
        return '已对选中句子发起改写，建议稍后出现在选区上方。'
      },
    }),
    [draft, onAdopted, projectId, selectionInfo, handleToolbarAction],
  )

  return (
    <div className={styles.editorSurface} data-testid="consumer-editor">
      <div className={styles.main}>
        <div className={styles.manuscriptColumn}>
          <ManuscriptCanvas editor={editor} zoom={zoom} wordCount={wordCount}>
            <CoreIdeaBlock
              coreIdea={coreIdea}
              onSave={onSaveCoreIdea}
              onOpenMaterials={onOpenMaterials}
              onGenerateDraft={onGenerateDraft}
              generating={generating}
              generationDisabled={generationDisabled}
            />
          </ManuscriptCanvas>
        </div>
      </div>

      <SelectionToolbar
        editorState={currentSelection}
        rangeRect={selectionRect ?? undefined}
        hidden={toolbarHidden}
        onAction={handleToolbarAction}
        onIntent={intent => void handleIntentAction(intent)}
        intentMessage={intentMessage}
        busy={suggesting !== null || intentBusy}
      />

      {suggestion && popoverPosition && (
        <SuggestionPopover
          actionLabel={intentLabel ?? (suggesting ? ACTION_LABELS[suggesting] : '')}
          suggestedText={suggestion.text}
          busy={false}
          position={popoverPosition}
          onAccept={() => void handleAccept()}
          onDismiss={() => {
            setSuggestion(null)
            setSuggesting(null)
            setIntentLabel(null)
          }}
        />
      )}
    </div>
  )
}
)

/**
 * Ref-object variant for the next/dynamic boundary (P0-2 regression fix):
 * Next 14's dynamic() drops refs, so ConsumerEditorClient passes a ref
 * OBJECT as a plain prop instead. Same contract, same imperative handle —
 * the page reads editorHandle.current exactly as before.
 */
export function ConsumerEditorWithHandle(
  props: Omit<ConsumerEditorProps, never> & { handleRefObj?: { current: ConsumerEditorHandle | null } },
) {
  const { handleRefObj, ...rest } = props
  const innerRef = useRef<ConsumerEditorHandle>(null)
  useEffect(() => {
    if (handleRefObj) handleRefObj.current = innerRef.current
    return () => {
      if (handleRefObj) handleRefObj.current = null
    }
  })
  return <ConsumerEditor {...rest} ref={innerRef} />
}
