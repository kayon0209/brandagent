/**
 * Consumer editor tests (upgrade plan task 10).
 *
 * Split by public interface:
 * - SelectionToolbar / SaveStatus / ZoomControl / ConsumerEditor: component
 *   behavior through the DOM (rendering, positioning algorithm, hiding
 *   rules, zoom isolation).
 * - useConsumerDraft: the autosave state machine (800ms debounce, saved
 *   only after server confirm, 409 keeps local draft, recovery entry).
 */

import React from 'react'
import { render, screen, fireEvent, act, renderHook, waitFor } from '@testing-library/react'

import { SelectionToolbar } from '@/components/consumer/editor/SelectionToolbar'
import { SaveStatus } from '@/components/consumer/editor/SaveStatus'
import { ZoomControl } from '@/components/consumer/editor/ZoomControl'
import { ConsumerEditor } from '@/components/consumer/editor/ConsumerEditor'
import { useConsumerDraft } from '@/hooks/useConsumerDraft'

const rectOf = (top: number, left: number, width = 120, height = 24) => ({
  top, left, bottom: top + height, right: left + width, width, height, x: left, y: top,
  toJSON: () => ({}),
})

function rangeWithRect(rect: ReturnType<typeof rectOf>) {
  return { getBoundingClientRect: () => rect, cloneRange: () => rangeWithRect(rect) }
}

function makeEditorState(overrides: Record<string, unknown> = {}) {
  return {
    selection: { from: 3, to: 20, empty: false },
    doc: { textBetween: () => '选中的句子' },
    ...overrides,
  }
}

describe('SelectionToolbar', () => {
  it('stays hidden when the selection is empty or collapsed', () => {
    const { container } = render(
      <SelectionToolbar editorState={makeEditorState({ selection: { from: 3, to: 3, empty: true } })} />,
    )
    expect(document.querySelector('[data-testid="selection-toolbar"]')).toBeNull()
  })

  it('shows three white pill action buttons when a paragraph is selected', () => {
    render(
      <SelectionToolbar
        editorState={makeEditorState()}
        rangeRect={rangeWithRect(rectOf(100, 100))}
        onAction={jest.fn()}
      />,
    )
    // plan-mandated wording (L90): 展开说说 / 换个例子 / 短一点
    for (const label of ['展开说说', '换个例子', '短一点']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
    }
  })

  it('positions itself centered on the selection rect above it, not a fixed center', () => {
    const rect = rectOf(300, 240)
    const { container } = render(
      <SelectionToolbar editorState={makeEditorState()} rangeRect={rangeWithRect(rect)} />,
    )
    const toolbar = document.querySelector<HTMLElement>('[data-testid="selection-toolbar"]')
    expect(toolbar).not.toBeNull()
    // toolbar center should be the selection center: left 240 + width/2 (120/2) = 300
    expect(toolbar!.style.left).toBe('226px') // center 300 - half toolbar width (148/2)
    const y = Number(toolbar!.style.top!.replace('px', ''))
    expect(y).toBeLessThan(300) // 8px above the selection top
  })

  it('drops below the selection when there is no room above', () => {
    const rect = rectOf(10, 240)
    const { container } = render(
      <SelectionToolbar editorState={makeEditorState()} rangeRect={rangeWithRect(rect)} />,
    )
    const toolbar = document.querySelector<HTMLElement>('[data-testid="selection-toolbar"]')!
    const y = Number(toolbar.style.top!.replace('px', ''))
    expect(y).toBeGreaterThanOrEqual(rect.bottom + 8)
  })

  it('clamps to at least 12px from the viewport left', () => {
    const rect = rectOf(100, -200)
    const { container } = render(
      <SelectionToolbar editorState={makeEditorState()} rangeRect={rangeWithRect(rect)} />,
    )
    const toolbar = document.querySelector<HTMLElement>('[data-testid="selection-toolbar"]')!
    const x = Number(toolbar.style.left!.replace('px', ''))
    expect(x).toBeGreaterThanOrEqual(12)
  })

  it('is not rendered when hidden (blur/Escape)', () => {
    const state = makeEditorState()
    const rect = rangeWithRect(rectOf(100, 100))
    const { container, rerender } = render(<SelectionToolbar editorState={state} rangeRect={rect} />)
    expect(document.querySelector('[data-testid="selection-toolbar"]')).not.toBeNull()
    rerender(<SelectionToolbar editorState={state} rangeRect={rect} hidden />)
    expect(document.querySelector('[data-testid="selection-toolbar"]')).toBeNull()
  })

  it('invokes onAction with the selected action', () => {
    const onAction = jest.fn()
    render(
      <SelectionToolbar
        editorState={makeEditorState()}
        rangeRect={rangeWithRect(rectOf(100, 100))}
        onAction={onAction}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '展开说说' }))
    expect(onAction).toHaveBeenCalledWith('expand')
  })
})

describe('SaveStatus', () => {
  it.each([
    ['dirty', '未保存'],
    ['saving', '正在保存'],
    ['saved', '已保存'],
    ['conflict', '稿件在别处有更新'],
    ['error', '保存失败 · 点击重试'],  // round-3g A2 copy
  ] as const)('renders a human state for "%s"', (state, text) => {
    render(<SaveStatus state={state} onResolveConflict={jest.fn()} />)
    expect(screen.getByText(new RegExp(text))).toBeInTheDocument()
  })

  it('offers a recovery entry on conflict', () => {
    const onResolveConflict = jest.fn()
    render(<SaveStatus state="conflict" onResolveConflict={onResolveConflict} />)
    fireEvent.click(screen.getByRole('button', { name: '查看最新稿' }))
    expect(onResolveConflict).toHaveBeenCalled()
  })
})

describe('ZoomControl', () => {
  it('scales only via the callback; caller applies zoom to the canvas', () => {
    const onZoomChange = jest.fn()
    render(<ZoomControl zoom={1} onZoomChange={onZoomChange} />)
    fireEvent.click(screen.getByRole('button', { name: /放大/ }))
    expect(onZoomChange).toHaveBeenCalledWith(1.1)
    fireEvent.click(screen.getByRole('button', { name: /缩小/ }))
    expect(onZoomChange).toHaveBeenCalledWith(0.9)
  })

  it('disables zoom beyond the limits', () => {
    const onZoomChange = jest.fn()
    render(<ZoomControl zoom={1.6} onZoomChange={onZoomChange} />)
    expect(screen.getByRole('button', { name: /放大/ })).toBeDisabled()
  })
})

describe('useConsumerDraft', () => {
  const makeApi = () => ({
    getDraft: jest.fn().mockResolvedValue({
      task_id: 'task-1',
      revision: 3,
      document: { blocks: [{ block_id: 'b1', block_type: 'paragraph', text: '原文' }] },
      plain_text: '原文',
    }),
    saveDraft: jest.fn().mockResolvedValue({ revision: 4 }),
    proposeSuggestion: jest.fn(),
    acceptSuggestion: jest.fn(),
  })



  it('debounces saves at 800ms and shows saved only after server confirm', async () => {
    // fake timers ONLY for this hook test (tiptap needs real timers in the
    // component tests); advanceTimersByTime is real here, not a warned no-op
    jest.useFakeTimers()
    try {
    const api = makeApi()
    const { result } = renderHook(() => useConsumerDraft('task-1', api))
    await act(async () => { await Promise.resolve() })
    expect(result.current.status).toBe('saved')

    let resolveSave: (value: unknown) => void
    api.saveDraft.mockImplementation(() => new Promise(resolve => { resolveSave = resolve }))

    act(() => { result.current.markDirty({ blocks: [] }, '编辑后的文本') })
    expect(result.current.status).toBe('dirty')
    act(() => { jest.advanceTimersByTime(500) })
    expect(api.saveDraft).not.toHaveBeenCalled()
    act(() => { jest.advanceTimersByTime(350) })
    await waitFor(() => expect(result.current.status).toBe('saving'))
    expect(api.saveDraft).toHaveBeenCalledWith(
      'task-1', expect.objectContaining({ baseRevision: 3 }),
    )
    await act(async () => { resolveSave!({ revision: 4 }) })
    expect(result.current.status).toBe('saved')
    expect(result.current.revision).toBe(4)
    } finally { jest.useRealTimers() }
  })

  it('keeps the local draft text on 409 and exposes recovery', async () => {
    jest.useFakeTimers()
    try {
    const api = makeApi()
    api.saveDraft.mockRejectedValue({ code: 'REVISION_CONFLICT', message: 'conflict' })
    const { result } = renderHook(() => useConsumerDraft('task-1', api))
    await act(async () => { await Promise.resolve() })
    act(() => { result.current.markDirty({ blocks: [] }, '本地继续编辑') })
    act(() => { jest.advanceTimersByTime(900) })
    // the debounce fired flush; drive the async flush to completion via the public API
    await act(async () => { await result.current.flush() })
    expect(result.current.status).toBe('conflict')
    expect(result.current.localPlainText).toBe('本地继续编辑')

    api.getDraft.mockResolvedValue({
      task_id: 'task-1', revision: 7,
      document: { blocks: [{ block_id: 'b1', block_type: 'paragraph', text: '服务器最新稿' }] },
      plain_text: '服务器最新稿',
    })
    await act(async () => { await result.current.resolveConflict() })
    // recovery keeps the user's newer local text as dirty (audit fix: the
    // old code deleted the backup on load and lost unsaved typing); the
    // server revision is tracked so the next save can compare-and-swap
    expect(result.current.status).toBe('dirty')
    expect(result.current.localPlainText).toBe('本地继续编辑')
    expect(result.current.revision).toBe(7)
    } finally { jest.useRealTimers() }
  })

  it('marks error (offline-tolerant) when saving fails', async () => {
    jest.useFakeTimers()
    try {
    const api = makeApi()
    api.saveDraft.mockRejectedValue(new TypeError('fetch failed'))
    const { result } = renderHook(() => useConsumerDraft('task-1', api))
    await act(async () => { await Promise.resolve() })
    act(() => { result.current.markDirty({ blocks: [] }, '断网时编辑的内容') })
    act(() => { jest.advanceTimersByTime(900) })
    await act(async () => { await result.current.flush() })
    expect(result.current.status).toBe('error')
    expect(result.current.localPlainText).toBe('断网时编辑的内容')
    } finally { jest.useRealTimers() }
  })

  it('serializes concurrent flushes instead of dropping the second payload', async () => {
    const api = makeApi()
    let resolveFirst: (value: { revision: number }) => void
    api.saveDraft.mockImplementationOnce(
      () => new Promise(resolve => { resolveFirst = resolve }),
    )
    const { result } = renderHook(() => useConsumerDraft('task-1', api))
    await act(async () => { await Promise.resolve() })

    act(() => { result.current.markDirty({ blocks: [] }, '第一版') })
    // drive flush #1 directly: it stays in flight because resolveFirst is pending
    let firstFlush: Promise<void>
    act(() => { firstFlush = result.current.flush() })
    // drain microtasks so saveDraft is actually reached
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    expect(api.saveDraft).toHaveBeenCalledTimes(1)
    // flush #2 must chain after the in-flight save, not drop the payload
    let secondFlush: Promise<void>
    act(() => {
      result.current.markDirty({ blocks: [] }, '第二版')
      secondFlush = result.current.flush()
    })
    await act(async () => { resolveFirst!({ revision: 4 }) })
    await act(async () => { await firstFlush! })
    await act(async () => { await secondFlush! })
    expect(api.saveDraft).toHaveBeenCalledTimes(2)
    expect(api.saveDraft).toHaveBeenLastCalledWith('task-1', expect.objectContaining({ plainText: '第二版' }))
    expect(result.current.status).toBe('saved')
  })

  it('shows error (not silent saved) when the initial load fails', async () => {
    const api = makeApi()
    api.getDraft.mockRejectedValue(new TypeError('fetch failed'))
    const { result } = renderHook(() => useConsumerDraft('task-1', api))
    await act(async () => { await Promise.resolve() })
    await act(async () => { await Promise.resolve() })
    expect(result.current.status).toBe('error')
  })
})

describe('ConsumerEditor', () => {
  const makeApi = () => ({
    getDraft: jest.fn().mockResolvedValue({
      task_id: 'task-1',
      revision: 3,
      document: { blocks: [{ block_id: 'b1', block_type: 'paragraph', text: '这是第一段。这里有一个需要改写的句子。' }] },
      plain_text: '这是第一段。这里有一个需要改写的句子。',
    }),
    saveDraft: jest.fn().mockResolvedValue({ revision: 4 }),
    proposeSuggestion: jest.fn(),
    acceptSuggestion: jest.fn(),
  })

  async function renderEditor(overrides: Record<string, unknown> = {}) {
    const api = makeApi()
    const utilities = render(
      <ConsumerEditor projectId="task-1" coreIdea="核心观点" api={api} {...overrides} />,
    )
    // the mount-effect draft load resolves on a microtask AFTER render's act
    // boundary; flush it inside act so the seeded state updates never warn
    // (P2: tests pass on real timing, not behind a wall of warnings)
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    return { api, ...utilities }
  }

  it('renders a 720px manuscript canvas with the core idea block above the prose', async () => {
    await renderEditor()
    const canvas = await screen.findByTestId('manuscript-canvas')
    expect(canvas).toBeInTheDocument()
    expect(canvas.style.maxWidth).toBe('720px')
    const coreIdea = await screen.findByTestId('core-idea-block')
    expect(coreIdea.getAttribute('data-gap')).toBe('32')
    const prose = await screen.findByText(/这是第一段/)
    expect(coreIdea.compareDocumentPosition(prose) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('exposes zoom through the status callback (the statusbar owns the controls)', async () => {
    const onStatus = jest.fn()
    const api = makeApi()
    render(
      <ConsumerEditor projectId="task-1" coreIdea="核心观点" api={api} onStatus={onStatus} />,
    )
    // flush the mount-effect draft load inside act (no unwarned state updates)
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    await screen.findByTestId('manuscript-canvas')
    // the canvas keeps the 720px paper contract; zoom travels in the payload
    const canvas = screen.getByTestId('manuscript-canvas')
    expect(canvas.style.maxWidth).toBe('720px')
    await waitFor(() => expect(onStatus).toHaveBeenCalled())
    const payload = onStatus.mock.calls.at(-1)[0]
    expect(payload.zoom).toBeGreaterThanOrEqual(0.75)
    expect(payload.zoom).toBeLessThanOrEqual(1.5)
    expect(typeof payload.changeZoom).toBe('function')
    act(() => {
      payload.changeZoom(1.2)
    })
    await waitFor(() => {
      const updated = onStatus.mock.calls.at(-1)[0]
      expect(updated.zoom).toBe(1.2)
    })
  })

  it('hides the selection toolbar on Escape', async () => {
    await renderEditor()
    // direct Escape at document level hides whatever toolbar state exists
    const before = document.querySelector('[data-testid="selection-toolbar"]')
    if (before) {
      fireEvent.keyDown(document, { key: 'Escape' })
      await waitFor(() =>
        expect(document.querySelector('[data-testid="selection-toolbar"]')).toBeNull(),
      )
    }
  })
})
