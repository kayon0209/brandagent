import { render, screen } from '@testing-library/react'

import { DeepResearchPanel } from '@/components/consumer/research/DeepResearchPanel'
import { useDeepResearch } from '@/hooks/useDeepResearch'

jest.mock('@/hooks/useDeepResearch')

const mockUseDeepResearch = useDeepResearch as jest.MockedFunction<typeof useDeepResearch>

test('unverified cards never render a live source link or an enabled join action', () => {
  mockUseDeepResearch.mockReturnValue({
    phase: 'succeeded',
    run: {
      run_id: 'run-unsafe',
      question: '测试',
      audience: '',
      scope_hint: '',
      status: 'succeeded',
      candidate_cards: [
        {
          url: 'javascript:alert(1)',
          title: '不可信来源',
          excerpt: '不得作为素材导入。',
          retrieved_at: '2026-09-09T00:00:00Z',
          reachable: false,
          excerpt_valid: false,
        },
      ],
    },
    progress: { directions: [], completedDirections: 0, searchCalls: 0 },
    busy: false,
    message: null,
    start: jest.fn(),
    cancel: jest.fn(),
    reset: jest.fn(),
    joinCard: jest.fn(),
    joinedCards: new Set<number>(),
  })

  render(<DeepResearchPanel />)

  expect(screen.queryByRole('link', { name: 'javascript:alert(1)' })).toBeNull()
  expect(screen.getByTestId('research-join-card')).toBeDisabled()
})
