/**
 * SelectionToolbar free-intent panel (agentization P1).
 *
 * Pins the interaction contract: the 说说怎么改 toggle reveals the input,
 * submit fires onIntent with trimmed text and clears the field, the busy
 * state disables submission, and guidance messages from refusals render
 * under the panel.
 */

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { SelectionToolbar } from '@/components/consumer/editor/SelectionToolbar'

const NON_EMPTY_SELECTION = { selection: { from: 3, to: 8, empty: false } }

function realRect() {
  return {
    getBoundingClientRect: () =>
      ({ left: 100, right: 200, top: 100, bottom: 120, width: 100, height: 20 }) as DOMRect,
  }
}

function renderToolbar(overrides?: Partial<Parameters<typeof SelectionToolbar>[0]>) {
  const props = {
    editorState: NON_EMPTY_SELECTION,
    rangeRect: realRect(),
    onAction: jest.fn(),
    onIntent: jest.fn(),
    ...overrides,
  }
  const view = render(<SelectionToolbar {...props} />)
  return { view, props }
}

beforeEach(() => {
  jest.clearAllMocks()
})
afterEach(cleanup)

test('intent panel is hidden until the toggle is clicked', () => {
  renderToolbar()
  expect(screen.queryByTestId('intent-panel')).not.toBeInTheDocument()
  fireEvent.click(screen.getByTestId('intent-toggle'))
  expect(screen.getByTestId('intent-panel')).toBeInTheDocument()
})

test('submit fires onIntent with trimmed text and clears the input', () => {
  const { props } = renderToolbar()
  fireEvent.click(screen.getByTestId('intent-toggle'))
  fireEvent.change(screen.getByTestId('intent-input'), { target: { value: '  换个生活化的说法  ' } })
  fireEvent.click(screen.getByTestId('intent-submit'))
  expect(props.onIntent).toHaveBeenCalledWith('换个生活化的说法')
  expect(screen.getByTestId('intent-input')).toHaveValue('')
})

test('empty intent never fires onIntent', () => {
  const { props } = renderToolbar()
  fireEvent.click(screen.getByTestId('intent-toggle'))
  fireEvent.change(screen.getByTestId('intent-input'), { target: { value: '   ' } })
  expect(screen.getByTestId('intent-submit')).toBeDisabled()
  fireEvent.click(screen.getByTestId('intent-submit'))
  expect(props.onIntent).not.toHaveBeenCalled()
})

test('busy state disables the intent submit and shows the waiting label', () => {
  renderToolbar({ busy: true })
  fireEvent.click(screen.getByTestId('intent-toggle'))
  expect(screen.getByTestId('intent-submit')).toBeDisabled()
  expect(screen.getByTestId('intent-submit')).toHaveTextContent('生成中…')
})

test('refusal guidance renders under the panel', () => {
  renderToolbar({ intentMessage: '这个改法我帮不了：只能展开、换个说法或精简。' })
  expect(screen.getByTestId('intent-message')).toHaveTextContent('这个改法我帮不了')
})

test('maxlength caps free text at 200 characters', () => {
  renderToolbar()
  fireEvent.click(screen.getByTestId('intent-toggle'))
  expect(screen.getByTestId('intent-input')).toHaveAttribute('maxlength', '200')
})
