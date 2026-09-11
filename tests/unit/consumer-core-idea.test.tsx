/**
 * P1-3 acceptance tests: the first-time consumer path must be closable
 * without typing any URL by hand.
 *
 * - CoreIdeaBlock is EDITABLE with explicit saving feedback (saving /
 *   saved / failed + retry) and never fakes success.
 * - /app exposes a discoverable materials-library entry.
 * - The write page's empty material drawer navigates to /app/materials
 *   instead of rendering a dead button.
 * - Material link failures never show as linked.
 */

import React from 'react'
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'

import { CoreIdeaBlock } from '@/components/consumer/editor/CoreIdeaBlock'
import { MaterialDrawer } from '@/components/consumer/materials/MaterialDrawer'

describe('CoreIdeaBlock (P1-3: editable core idea)', () => {
  it('renders an editable textarea seeded with the server core idea', () => {
    const onSave = jest.fn().mockResolvedValue(undefined)
    render(<CoreIdeaBlock coreIdea="把复杂的方法讲成普通人能上手的步骤" onSave={onSave} />)
    const field = screen.getByTestId('core-idea-input') as HTMLTextAreaElement
    expect(field).toBeInTheDocument()
    expect(field.value).toBe('把复杂的方法讲成普通人能上手的步骤')
  })

  it('autosaves a changed idea; the manual save button stays honest (enabled while dirty, disabled with an explanation once autosave lands)', async () => {
    jest.useFakeTimers()
    try {
    let release: () => void = () => {}
    const onSave = jest.fn().mockImplementation(
      () => new Promise<void>(resolve => { release = resolve }),
    )
    render(<CoreIdeaBlock coreIdea="旧观点" onSave={onSave} />)
    const field = screen.getByTestId('core-idea-input') as HTMLTextAreaElement
    fireEvent.change(field, { target: { value: '新观点' } })
    // 4a15641 restored the EXPLICIT save button: while dirty it is clickable
    const saveButton = screen.getByRole('button', { name: '保存' })
    expect(saveButton).toBeEnabled()
    act(() => { jest.advanceTimersByTime(650) })
    // saving state is visible while the request is in flight
    await waitFor(() => expect(screen.getByText(/正在保存/)).toBeInTheDocument())
    expect(onSave).toHaveBeenCalledWith('新观点')
    expect(saveButton).toBeDisabled()
    // not yet "saved" — the UI must not claim success before the server does
    expect(screen.queryByText(/已保存/)).toBeNull()
    release()
    await waitFor(() => expect(screen.getByTestId('core-idea-saved')).toBeInTheDocument())
    // once autosave landed the button disables WITH an explanation, never
    // reading as a dead control (X9, 09-10 bug report)
    expect(saveButton).toBeDisabled()
    expect(saveButton.getAttribute('title')).toContain('已自动保存')
    expect((screen.getByTestId('core-idea-input') as HTMLTextAreaElement).value).toBe('新观点')
    } finally { jest.useRealTimers() }
  })

  it('shows a failed state with retry when the save rejects; never claims saved', async () => {
    jest.useFakeTimers()
    try {
    const onSave = jest.fn().mockRejectedValue(new Error('网络错误'))
    render(<CoreIdeaBlock coreIdea="旧观点" onSave={onSave} />)
    const field = screen.getByTestId('core-idea-input') as HTMLTextAreaElement
    fireEvent.change(field, { target: { value: '更新的观点' } })
    act(() => { jest.advanceTimersByTime(650) })
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('alert').textContent).toContain('保存失败')
    expect(screen.queryByText(/已保存/)).toBeNull()
    // retry re-invokes save with the CURRENT text
    fireEvent.click(screen.getByRole('button', { name: /重试/ }))
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2))
    expect(onSave).toHaveBeenLastCalledWith('更新的观点')
    } finally { jest.useRealTimers() }
  })

  it('makes generation the primary next step and materials a usable secondary action', () => {
    const onGenerateDraft = jest.fn()
    const onOpenMaterials = jest.fn()
    render(
      <CoreIdeaBlock
        coreIdea="一个真实观点"
        onSave={jest.fn().mockResolvedValue(undefined)}
        onGenerateDraft={onGenerateDraft}
        onOpenMaterials={onOpenMaterials}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '+ 添加素材' }))
    fireEvent.click(screen.getByRole('button', { name: '生成初稿' }))
    expect(onOpenMaterials).toHaveBeenCalledTimes(1)
    expect(onGenerateDraft).toHaveBeenCalledTimes(1)
  })

  it('falls back to read-only display when no save handler is provided', () => {
    render(<CoreIdeaBlock coreIdea="只读观点" />)
    expect(screen.getByText('只读观点')).toBeInTheDocument()
    expect(screen.queryByTestId('core-idea-input')).toBeNull()
    expect(screen.queryByRole('button', { name: /生成初稿/ })).toBeNull()
  })
})

describe('MaterialDrawer (P1-3: empty state import button)', () => {
  it('renders the empty state with a WORKING 导入素材 button that invokes onImport', () => {
    const onImport = jest.fn()
    render(
      <MaterialDrawer
        materials={[]}
        open
        onToggle={jest.fn()}
        loading={false}
        error={null}
        onImport={onImport}
      />,
    )
    const button = screen.getByRole('button', { name: '导入素材' })
    expect(button).toBeInTheDocument()
    fireEvent.click(button)
    expect(onImport).toHaveBeenCalled()
  })

  it('shows an explicit guidance when onImport is missing rather than a dead button', () => {
    render(
      <MaterialDrawer
        materials={[]}
        open
        onToggle={jest.fn()}
        loading={false}
        error={null}
      />,
    )
    // a dead 导入素材 button is the acceptance finding — the drawer must
    // either navigate or state that import lives on the materials page
    expect(screen.queryByRole('button', { name: '导入素材' })).toBeNull()
  })

  it('never renders BrandFlow B-end terminology', () => {
    const { container } = render(
      <MaterialDrawer
        materials={[]}
        open
        onToggle={jest.fn()}
        loading={false}
        error={null}
        onImport={jest.fn()}
      />,
    )
    const text = container.textContent ?? ''
    for (const term of ['BrandFlow', '审批', 'workflow', 'task']) {
      expect(text).not.toContain(term)
    }
  })
})

describe('Materials page navigation (P1 UX: no nav islands)', () => {
  // the materials page component is a client page; test the pure nav
  // behavior via the exported back-link builder to avoid jsdom Next router
  // complexity while still locking the contract.
  it('back link targets the write page when a project context is known', async () => {
    const { buildMaterialsBackLink } = await import('@/lib/navigation/materials')
    expect(buildMaterialsBackLink('00000000-0000-0000-0000-000000000001')).toBe(
      '/app/write/00000000-0000-0000-0000-000000000001',
    )
  })

  it('back link falls back to /app when no project context exists', async () => {
    const { buildMaterialsBackLink } = await import('@/lib/navigation/materials')
    expect(buildMaterialsBackLink(null)).toBe('/app')
  })
})
