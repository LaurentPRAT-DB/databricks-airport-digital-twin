import { describe, it, expect, vi, beforeEach } from 'vitest'
import userEvent from '@testing-library/user-event'
import { render, screen, waitFor } from '../../test/test-utils'
import GenieChat from './GenieChat'

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
      expect(screen.getByText(/ask me anything about airport operations/i)).toBeInTheDocument()
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
      const mockResponse = {
        conversation_id: 'conv-1',
        message_id: 'msg-1',
        status: 'COMPLETED',
        sql: 'SELECT COUNT(*) FROM flights',
        columns: ['count'],
        data: [[42]],
        row_count: 1,
        text_response: 'There are 42 flights.',
        error: null,
      }

      vi.spyOn(global, 'fetch').mockResolvedValue({
        json: () => Promise.resolve(mockResponse),
        ok: true,
      } as Response)

      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      await user.type(screen.getByTestId('genie-input'), 'How many flights?')
      await user.click(screen.getByTestId('genie-send'))

      expect(screen.getByText('How many flights?')).toBeInTheDocument()
    })

    it('displays assistant response', async () => {
      const mockResponse = {
        conversation_id: 'conv-1',
        message_id: 'msg-1',
        status: 'COMPLETED',
        sql: 'SELECT COUNT(*) FROM flights',
        columns: ['count'],
        data: [[42]],
        row_count: 1,
        text_response: 'There are 42 flights.',
        error: null,
      }

      vi.spyOn(global, 'fetch').mockResolvedValue({
        json: () => Promise.resolve(mockResponse),
        ok: true,
      } as Response)

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
      const genieCalls: string[] = []
      const originalFetch = global.fetch
      const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((input, init?) => {
        const url = typeof input === 'string' ? input : (input as Request).url
        if (url.startsWith('/api/genie/')) {
          genieCalls.push(url)
          const responseNum = genieCalls.length
          return Promise.resolve({
            json: () => Promise.resolve({
              conversation_id: 'conv-1',
              message_id: `msg-${responseNum}`,
              status: 'COMPLETED',
              sql: null,
              columns: null,
              data: null,
              row_count: 0,
              text_response: `Answer ${responseNum}`,
              error: null,
            }),
            ok: true,
          } as Response)
        }
        // Let other fetches (providers, etc.) pass through or return empty
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

      expect(genieCalls[0]).toBe('/api/genie/ask')

      // Second message — should use followup since conversation_id is set
      await user.type(screen.getByTestId('genie-input'), 'Follow up')
      await user.click(screen.getByTestId('genie-send'))

      await waitFor(() => {
        expect(screen.getByText('Answer 2')).toBeInTheDocument()
      })

      expect(genieCalls).toHaveLength(2)
      expect(genieCalls[1]).toBe('/api/genie/followup')

      fetchSpy.mockRestore()
    })
  })

  describe('Error handling', () => {
    it('shows error message when fetch fails', async () => {
      vi.spyOn(global, 'fetch').mockRejectedValue(new Error('Network error'))

      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      await user.type(screen.getByTestId('genie-input'), 'test')
      await user.click(screen.getByTestId('genie-send'))

      await waitFor(() => {
        expect(screen.getByText(/failed to connect to genie/i)).toBeInTheDocument()
      })
    })
  })

  describe('Sample questions', () => {
    it('sends message when sample question is clicked', async () => {
      vi.spyOn(global, 'fetch').mockResolvedValue({
        json: () => Promise.resolve({
          conversation_id: 'conv-1',
          message_id: 'msg-1',
          status: 'COMPLETED',
          sql: null,
          columns: null,
          data: null,
          row_count: 0,
          text_response: 'Answer',
          error: null,
        }),
        ok: true,
      } as Response)

      const user = userEvent.setup()
      render(<GenieChat />)

      await user.click(screen.getByTestId('genie-fab'))
      const questions = screen.getAllByTestId('sample-question')
      await user.click(questions[0])

      // User message should appear
      expect(screen.getByText(/how many flights are approaching/i)).toBeInTheDocument()
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
})
