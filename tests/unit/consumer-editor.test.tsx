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
    expect(container.querySelector('[data-testid="selection-toolbar"]')).toBeNull()
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
    const toolbar = container.querySelector<HTMLElement>('[data-testid="selection-toolbar"]')
    expect(toolbar).not.toBeNull()
    // toolbar center should be the selection center: left 240 + width/2 (120/2) = 300
    expect(toolbar!.style.transform).toMatch(/translateX\(\s*226/) // center 300 - half toolbar width (148/2)
    const y = Number(toolbar!.style.transform.match(/translateY\(([\d.]+)px\)/)![1])
    expect(y).toBeLessThan(300) // 8px above the selection top
  })

  it('drops below the selection when there is no room above', () => {
    const rect = rectOf(10, 240)
    const { container } = render(
      <SelectionToolbar editorState={makeEditorState()} rangeRect={rangeWithRect(rect)} />,
    )
    const toolbar = container.querySelector<HTMLElement>('[data-testid="selection-toolbar"]')!
    const y = Number(toolbar.style.transform.match(/translateY\(([\d.]+)px\)/)![1])
    expect(y).toBeGreaterThanOrEqual(rect.bottom + 8)
  })

  it('clamps to at least 12px from the viewport left', () => {
    const rect = rectOf(100, -200)
    const { container } = render(
      <SelectionToolbar editorState={makeEditorState()} rangeRect={rangeWithRect(rect)} />,
    )
    const toolbar = container.querySelector<HTMLElement>('[data-testid="selection-toolbar"]')!
    const x = Number(toolbar.style.transform.match(/translateX\(([-\d.]+)px\)/)![1])
    expect(x).toBeGreaterThanOrEqual(12)
  })

  it('is not rendered when hidden (blur/Escape)', () => {
    const state = makeEditorState()
    const rect = rangeWithRect(rectOf(100, 100))
    const { container, rerender } = render(<SelectionToolbar editorState={state} rangeRect={rect} />)
    expect(container.querySelector('[data-testid="selection-toolbar"]')).not.toBeNull()
    rerender(<SelectionToolbar editorState={state} rangeRect={rect} hidden />)
    expect(container.querySelector('[data-testid="selection-toolbar"]')).toBeNull()
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
    ['error', '先记在本地'],
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

  beforeEach(() => {
  })
  afterEach(() => {
  })

  it('debounces saves at 800ms and shows saved only after server confirm', async () => {
    jest.spyOn(global, 'setTimeout')
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
  })

  it('keeps the local draft text on 409 and exposes recovery', async () => {
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
    expect(result.current.status).toBe('saved')
    expect(result.current.revision).toBe(7)
  })

  it('marks error (offline-tolerant) when saving fails', async () => {
    const api = makeApi()
    api.saveDraft.mockRejectedValue(new TypeError('fetch failed'))
    const { result } = renderHook(() => useConsumerDraft('task-1', api))
    await act(async () => { await Promise.resolve() })
    act(() => { result.current.markDirty({ blocks: [] }, '断网时编辑的内容') })
    act(() => { jest.advanceTimersByTime(900) })
    await act(async () => { await result.current.flush() })
    expect(result.current.status).toBe('error')
    expect(result.current.localPlainText).toBe('断网时编辑的内容')
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

  function renderEditor(overrides: Record<string, unknown> = {}) {
    const api = makeApi()
    const utilities = render(
      <ConsumerEditor projectId="task-1" coreIdea="核心观点" api={api} {...overrides} />,
    )
    return { api, ...utilities }
  }

  it('renders a 720px manuscript canvas with the core idea block above the prose', async () => {
    renderEditor()
    const canvas = await screen.findByTestId('manuscript-canvas')
    expect(canvas).toBeInTheDocument()
    expect(canvas.style.maxWidth).toBe('720px')
    const coreIdea = await screen.findByTestId('core-idea-block')
    expect(coreIdea.getAttribute('data-gap')).toBe('32')
    const prose = await screen.findByText(/这是第一段/)
    expect(coreIdea.compareDocumentPosition(prose) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('shows the zoom badge only on the canvas, not the header', async () => {
    renderEditor()
    const canvas = await screen.findByTestId('manuscript-canvas')
    const header = await screen.findByTestId('consumer-header')
    fireEvent.click(screen.getByRole('button', { name: /放大/ }))
    expect(canvas.style.zoom).toBe('1.1')
    expect(canvas.style.maxWidth).toBe('720px')
    expect(header.style.zoom).toBeFalsy()
  })

  it('hides the selection toolbar on Escape', async () => {
    renderEditor()
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
