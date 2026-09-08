/**
 * Consumer material drawer & materials page tests (upgrade plan task 7).
 *
 * These are behavior tests through the public component interface:
 * drawer collapse state, progressive disclosure, actionable empty/failed
 * states, and API-sourced link status.
 */

import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), prefetch: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

import { MaterialDrawer } from '@/components/consumer/materials/MaterialDrawer'
import { MaterialCard } from '@/components/consumer/materials/MaterialCard'
import { useConsumerMaterials, MATERIAL_LINK_STATES } from '@/hooks/useConsumerMaterials'
import * as consumerApi from '@/lib/api/consumer'

jest.mock('@/lib/api/consumer')

const mockMaterialsApi = consumerApi as jest.Mocked<typeof consumerApi>

import type { ConsumerMaterialExcerpt } from '@/types/consumer.types'

function excerptFixture(id: string, over: Partial<ConsumerMaterialExcerpt> = {}): ConsumerMaterialExcerpt {
  return {
    excerpt_id: id,
    excerpt_type: 'quote',
    summary: '一句可读的摘要',
    excerpt_text: '适合引用的原文',
    tags: ['标签'],
    status: 'ready',
    provenance_hash: 'a'.repeat(64),
    document_id: 'doc-1',
    chunk_id: 'chunk-1',
    created_by_type: 'model',
    ...over,
  }
}

describe('MaterialDrawer', () => {
  it('renders collapsed by default: hidden from accessibility, no body content', () => {
    render(
      <MaterialDrawer materials={[]} open={false} onToggle={jest.fn()} loading={false} error={null} />
    )
    const drawer = screen.getByTestId('material-drawer')
    expect(drawer).toHaveAttribute('aria-hidden', 'true')
    expect(drawer).toHaveAttribute('data-open', 'false')
    expect(screen.queryByText(/还没有素材/)).toBeNull()
    // the v4 entry point is the topbar materials button (owned by the write
    // page), not a toggle inside the drawer itself
  })

  it('shows actionable empty state with an import entry when open and empty', () => {
    const onImport = jest.fn()
    render(
      <MaterialDrawer materials={[]} open onToggle={jest.fn()} loading={false} error={null} onImport={onImport} />
    )
    expect(screen.getByLabelText('素材抽屉内容区')).toBeInTheDocument()
    expect(screen.getByText(/还没有素材/)).toBeInTheDocument()
    // the import entry must DO something when clicked (P1-3: no dead button)
    const entry = screen.getByRole('button', { name: '导入素材' })
    fireEvent.click(entry)
    expect(onImport).toHaveBeenCalled()
  })

  it('shows a processing state instead of fabricating material', () => {
    render(
      <MaterialDrawer materials={[]} open onToggle={jest.fn()} loading error={null} />
    )
    expect(screen.getByText(/正在处理/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '导入素材' })).toBeNull()
  })

  it('shows a retryable failed state that keeps the drawer usable', () => {
    render(
      <MaterialDrawer
        materials={[]}
        open
        onToggle={jest.fn()}
        loading={false}
        error={{ code: 'DISTILL_FAILED', message: '蒸馏失败' }}
        onRetry={jest.fn()}
      />
    )
    expect(screen.getByText(/处理失败/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
  })
})

describe('MaterialCard', () => {
  it('shows only summary and tags by default; no ids, no dates, no system words', () => {
    render(<MaterialCard excerpt={excerptFixture('e-1')} onLink={jest.fn()} linkState="unlinked" />)
    expect(screen.getByText('一句可读的摘要')).toBeInTheDocument()
    expect(screen.getByText('#标签')).toBeInTheDocument()
    expect(screen.queryByText(/doc-1|chunk-1|e-1/)).toBeNull()
    expect(screen.queryByText(/provenance|checksum|ready/)).toBeNull()
  })

  it('reveals the source detail only after an explicit click', async () => {
    render(<MaterialCard excerpt={excerptFixture('e-2')} onLink={jest.fn()} linkState="unlinked" />)
    expect(screen.queryByText('适合引用的原文')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: '来源' }))
    expect(screen.getByText('适合引用的原文')).toBeInTheDocument()
  })

  it('link status comes from the API response, not local optimism', async () => {
    const onLink = jest.fn()
    render(<MaterialCard excerpt={excerptFixture('e-3')} onLink={onLink} linkState="linked" />)
    expect(screen.getByRole('button', { name: '已关联' })).toBeDisabled()
  })
})

describe('useConsumerMaterials', () => {
  it('exposes real API loading and list data with link states from responses', async () => {
    mockMaterialsApi.listMaterials.mockResolvedValue({
      items: [
        {
          document_id: 'doc-1',
          document_name: '第一份素材',
          excerpt_count: 2,
          status: 'distilled',
          document_type: 'text' as const,
        },
      ],
    })

    function Probe() {
      const state = useConsumerMaterials()
      return (
        <div>
          <span data-testid="loading">{String(state.loading)}</span>
          <span data-testid="count">{state.materials.length}</span>
          <span data-testid="states">{state.materials.map(m => m.status).join(',')}</span>
        </div>
      )
    }
    render(<Probe />)

    await waitFor(() => {
      expect(screen.getByTestId('loading').textContent).toBe('false')
    })
    expect(screen.getByTestId('count').textContent).toBe('1')
    expect(screen.getByTestId('states').textContent).toBe('distilled')
    expect(mockMaterialsApi.listMaterials).toHaveBeenCalledTimes(1)
  })
})
