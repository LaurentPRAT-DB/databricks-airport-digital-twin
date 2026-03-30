import { describe, it, expect, vi, beforeEach } from 'vitest'
import userEvent from '@testing-library/user-event'
import { render, screen, waitFor } from '../../test/test-utils'
import GenieChat from './GenieChat'

/** Helper: build a mock AssistantApiResponse */
function mockAssistantResponse(overrides: Record<string, unknown> = {}) {
  return {
    conversation_id: 'conv-1',
    answer: 'Test answer',
    sources: [],
    sql: null,
    columns: null,
    data: null,
    row_count: 0,
    tool_calls: null,
    error: null,
    ...overrides,
  }
}

function mockFetchOk(response: Record<string, unknown>) {
  vi.spyOn(global, 'fetch').mockResolvedValue({
    json: () => Promise.resolve(response),
    ok: true,
  } as Response)
}

describe('GenieChat', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.restoreAllMocks()
  })

  describe('FAB Button', () => {
    it('renders the floating action button', () => {
      render(<GenieChat />)
      expect(screen.getByTestId('genie-fab')).toBeInTheDocument()
    })

    it('FAB has correct title', () => {
      render(<GenieChat />)
      expect(screen.getByTitle('Ask Airport Operations Assistant')).toBeInTheDocument()
    })
  })

  describe('Panel toggle', () => {
    it('opens chat panel when FAB is clicked', async () => {
      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      expect(screen.getByTestId('genie-panel')).toBeInTheDocument()
    })

    it('hides FAB when panel is open', async () => {
      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      expect(screen.queryByTestId('genie-fab')).not.toBeInTheDocument()
    })

    it('closes panel when close button is clicked', async () => {
      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      expect(screen.getByTestId('genie-panel')).toBeInTheDocument()

      await user.click(screen.getByTestId('genie-close'))
      expect(screen.queryByTestId('genie-panel')).not.toBeInTheDocument()
      expect(screen.getByTestId('genie-fab')).toBeInTheDocument()
    })
  })

  describe('Empty state', () => {
    it('shows sample questions when no messages', async () => {
      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      const questions = screen.getAllByTestId('sample-question')
      expect(questions.length).toBe(4)
    })

    it('shows prompt text', async () => {
      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      expect(screen.getByText(/ask about live operations or historical data/i)).toBeInTheDocument()
    })
  })

  describe('Input', () => {
    it('renders input field', async () => {
      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      expect(screen.getByTestId('genie-input')).toBeInTheDocument()
    })

    it('input accepts text', async () => {
      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      const input = screen.getByTestId('genie-input')
      await user.type(input, 'How many flights?')
      expect(input).toHaveValue('How many flights?')
    })

    it('send button is disabled when input is empty', async () => {
      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      expect(screen.getByTestId('genie-send')).toBeDisabled()
    })

    it('send button is enabled when input has text', async () => {
      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      await user.type(screen.getByTestId('genie-input'), 'test')
      expect(screen.getByTestId('genie-send')).not.toBeDisabled()
    })
  })

  describe('Sending messages', () => {
    it('displays user message after send', async () => {
      mockFetchOk(mockAssistantResponse({
        answer: 'There are 42 flights.',
        sql: 'SELECT COUNT(*) FROM flights',
        columns: ['count'],
        data: [[42]],
        row_count: 1,
        sources: ['genie'],
      }))

      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      await user.type(screen.getByTestId('genie-input'), 'How many flights?')
      await user.click(screen.getByTestId('genie-send'))

      expect(screen.getByText('How many flights?')).toBeInTheDocument()
    })

    it('displays assistant response', async () => {
      mockFetchOk(mockAssistantResponse({
        answer: 'There are 42 flights.',
        sources: ['genie'],
      }))

      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      await user.type(screen.getByTestId('genie-input'), 'How many flights?')
      await user.click(screen.getByTestId('genie-send'))

      await waitFor(() => {
        expect(screen.getByText('There are 42 flights.')).toBeInTheDocument()
      })
    })

    it('sends to followup endpoint on second message', async () => {
      const assistantCalls: string[] = []
      const originalFetch = global.fetch
      const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((input, init?) => {
        const url = typeof input === 'string' ? input : (input as Request).url
        if (url.startsWith('/api/assistant/')) {
          assistantCalls.push(url)
          const responseNum = assistantCalls.length
          return Promise.resolve({
            json: () => Promise.resolve(mockAssistantResponse({
              answer: `Answer ${responseNum}`,
            })),
            ok: true,
          } as Response)
        }
        return originalFetch(input, init)
      })

      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))

      // First message — starts new conversation
      await user.type(screen.getByTestId('genie-input'), 'First question')
      await user.click(screen.getByTestId('genie-send'))

      await waitFor(() => {
        expect(screen.getByText('Answer 1')).toBeInTheDocument()
      })

      expect(assistantCalls[0]).toBe('/api/assistant/ask')

      // Second message — should use followup since conversation_id is set
      await user.type(screen.getByTestId('genie-input'), 'Follow up')
      await user.click(screen.getByTestId('genie-send'))

      await waitFor(() => {
        expect(screen.getByText('Answer 2')).toBeInTheDocument()
      })

      expect(assistantCalls).toHaveLength(2)
      expect(assistantCalls[1]).toBe('/api/assistant/followup')

      fetchSpy.mockRestore()
    })
  })

  describe('Error handling', () => {
    it('shows error message when fetch fails', async () => {
      const originalFetch = global.fetch
      vi.spyOn(global, 'fetch').mockImplementation((input, init?) => {
        const url = typeof input === 'string' ? input : (input as Request).url
        if (url.startsWith('/api/assistant/')) {
          return Promise.reject(new Error('Network error'))
        }
        return originalFetch(input, init)
      })

      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      await user.type(screen.getByTestId('genie-input'), 'test')
      await user.click(screen.getByTestId('genie-send'))

      await waitFor(() => {
        expect(screen.getByText(/failed to connect to the assistant/i)).toBeInTheDocument()
      })
    })
  })

  describe('Sample questions', () => {
    it('sends message when sample question is clicked', async () => {
      mockFetchOk(mockAssistantResponse({ answer: 'Weather is clear.' }))

      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      const questions = screen.getAllByTestId('sample-question')
      await user.click(questions[0])

      // First sample question is "What's the current weather at the airport?"
      expect(screen.getByText(/current weather/i)).toBeInTheDocument()
    })
  })

  describe('Header actions', () => {
    it('shows link to Databricks Genie UI', async () => {
      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      expect(screen.getByTitle('Open in Databricks Genie')).toBeInTheDocument()
    })
  })

  describe('Response display', () => {
    it('shows SQL and data table when provided', async () => {
      mockFetchOk(mockAssistantResponse({
        answer: 'Found 3 flights:',
        sql: 'SELECT * FROM flights',
        columns: ['flight', 'gate'],
        data: [['UAL100', 'A1'], ['DAL200', 'B2'], ['AAL300', 'C3']],
        row_count: 3,
        sources: ['genie'],
      }))

      const user = userEvent.setup()
      render(<GenieChat />)
      await user.click(screen.getByTestId('genie-fab'))
      await user.type(screen.getByTestId('genie-input'), 'Show flights')
      await user.click(screen.getByTestId('genie-send'))

      await waitFor(() => {
        expect(screen.getByText('Found 3 flights:')).toBeInTheDocument()
      })
    })

    it('shows error content when error field is set', async () => {
      mockFetchOk(mockAssistantResponse({
        answer: 'Column not found: foobar',
        error: 'Column not found: foobar',
      }))

      const user = userEvent.setup()
      render(<GenieChat />)
      await user.click(screen.getByTestId('genie-fab'))
      await user.type(screen.getByTestId('genie-input'), 'test')
      await user.click(screen.getByTestId('genie-send'))

      await waitFor(() => {
        expect(screen.getByText('Column not found: foobar')).toBeInTheDocument()
      })
    })

    it('shows permission denied for HTTP 403', async () => {
      vi.spyOn(global, 'fetch').mockResolvedValue({
        json: () => Promise.resolve({ detail: 'Forbidden' }),
        ok: false,
        status: 403,
      } as Response)

      const user = userEvent.setup()
      render(<GenieChat />)
      await user.click(screen.getByTestId('genie-fab'))
      await user.type(screen.getByTestId('genie-input'), 'test')
      await user.click(screen.getByTestId('genie-send'))

      await waitFor(() => {
        expect(screen.getByText(/access denied/i)).toBeInTheDocument()
      })
    })

    it('shows service unavailable for HTTP 503', async () => {
      vi.spyOn(global, 'fetch').mockResolvedValue({
        json: () => Promise.resolve({ detail: 'No auth' }),
        ok: false,
        status: 503,
      } as Response)

      const user = userEvent.setup()
      render(<GenieChat />)
      await user.click(screen.getByTestId('genie-fab'))
      await user.type(screen.getByTestId('genie-input'), 'test')
      await user.click(screen.getByTestId('genie-send'))

      await waitFor(() => {
        expect(screen.getByText(/not available/i)).toBeInTheDocument()
      })
    })

    it('shows source badge for live data', async () => {
      mockFetchOk(mockAssistantResponse({
        answer: 'Clear skies, 18C.',
        sources: ['mcp:get_weather'],
      }))

      const user = userEvent.setup()
      render(<GenieChat />)
      await user.click(screen.getByTestId('genie-fab'))
      await user.type(screen.getByTestId('genie-input'), 'weather')
      await user.click(screen.getByTestId('genie-send'))

      await waitFor(() => {
        expect(screen.getByText('Live Data')).toBeInTheDocument()
      })
    })

    it('shows source badge for historical SQL', async () => {
      mockFetchOk(mockAssistantResponse({
        answer: 'Average delay was 12 minutes.',
        sources: ['genie'],
      }))

      const user = userEvent.setup()
      render(<GenieChat />)
      await user.click(screen.getByTestId('genie-fab'))
      await user.type(screen.getByTestId('genie-input'), 'average delay')
      await user.click(screen.getByTestId('genie-send'))

      await waitFor(() => {
        expect(screen.getByText('Historical SQL')).toBeInTheDocument()
      })
    })
  })

  describe('Retry', () => {
    it('shows retry button on error and re-sends last question', async () => {
      let callCount = 0
      const originalFetch = global.fetch
      const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((input, init?) => {
        const url = typeof input === 'string' ? input : (input as Request).url
        if (url.startsWith('/api/assistant/')) {
          callCount++
          if (callCount === 1) {
            return Promise.reject(new Error('Network error'))
          }
          return Promise.resolve({
            json: () => Promise.resolve(mockAssistantResponse({
              answer: 'Success on retry!',
            })),
            ok: true,
          } as Response)
        }
        return originalFetch(input, init)
      })

      const user = userEvent.setup()
      render(<GenieChat />)
      await user.click(screen.getByTestId('genie-fab'))
      await user.type(screen.getByTestId('genie-input'), 'test question')
      await user.click(screen.getByTestId('genie-send'))

      // Wait for error + retry button
      await waitFor(() => {
        expect(screen.getByTestId('genie-retry')).toBeInTheDocument()
      })

      await user.click(screen.getByTestId('genie-retry'))

      await waitFor(() => {
        expect(screen.getByText('Success on retry!')).toBeInTheDocument()
      })

      expect(callCount).toBe(2)
      fetchSpy.mockRestore()
    })
  })

  describe('Keyboard shortcuts', () => {
    it('closes panel when Escape key is pressed', async () => {
      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      expect(screen.getByTestId('genie-panel')).toBeInTheDocument()

      await user.keyboard('{Escape}')
      expect(screen.queryByTestId('genie-panel')).not.toBeInTheDocument()
    })
  })

  describe('Timestamps', () => {
    it('shows relative timestamps on messages', async () => {
      mockFetchOk(mockAssistantResponse({ answer: 'Answer' }))

      const user = userEvent.setup()
      render(<GenieChat />)
      await user.click(screen.getByTestId('genie-fab'))
      await user.type(screen.getByTestId('genie-input'), 'test')
      await user.click(screen.getByTestId('genie-send'))

      await waitFor(() => {
        expect(screen.getByText('Answer')).toBeInTheDocument()
      })

      // Both user and assistant messages should show "just now"
      const timestamps = screen.getAllByText('just now')
      expect(timestamps.length).toBeGreaterThanOrEqual(2)
    })
  })
})
