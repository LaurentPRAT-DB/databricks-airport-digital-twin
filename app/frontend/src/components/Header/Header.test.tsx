import { describe, it, expect, vi, beforeEach } from 'vitest'
import userEvent from '@testing-library/user-event'
import { render, screen, waitFor, measureRenderTime, PERFORMANCE_THRESHOLDS } from '../../test/test-utils'
import Header from './Header'
import { mockFlights } from '../../test/mocks/handlers'

describe('Header', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Title and branding', () => {
    it('renders the application title', async () => {
      render(<Header />)
      expect(screen.getByRole('heading', { name: /airport digital twin/i })).toBeInTheDocument()
    })

    it('title is h1 level', async () => {
      render(<Header />)
      const title = screen.getByRole('heading', { level: 1 })
      expect(title).toHaveTextContent(/airport digital twin/i)
    })

    it('displays version and build hash', () => {
      render(<Header />)
      // vitest.config.ts defines __APP_VERSION__ = '0.0.0-test' and __BUILD_HASH__ = 'test'
      expect(screen.getByText(/v0\.0\.0-test/)).toBeInTheDocument()
      expect(screen.getByText(/test/)).toBeInTheDocument()
    })

    it('shows build time in title tooltip', () => {
      render(<Header />)
      const versionEl = screen.getByTitle(/Built 2026/)
      expect(versionEl).toBeInTheDocument()
    })
  })

  describe('Flight count', () => {
    it('displays flight count', async () => {
      render(<Header />)

      await waitFor(() => {
        expect(screen.getByText(/flights:/i)).toBeInTheDocument()
      })
    })

    it('updates flight count when data loads', async () => {
      render(<Header />)

      await waitFor(() => {
        expect(screen.getByText(mockFlights.length.toString())).toBeInTheDocument()
      })
    })
  })

  describe('Data source indicator', () => {
    it('shows demo mode badge for synthetic data', async () => {
      render(<Header />)

      await waitFor(() => {
        expect(screen.getByText(/demo mode/i)).toBeInTheDocument()
      })
    })

    it('shows data source type', async () => {
      render(<Header />)

      await waitFor(() => {
        expect(screen.getByText(/synthetic/i)).toBeInTheDocument()
      })
    })
  })

  describe('Connection status', () => {
    it('shows connected status when data loaded', async () => {
      render(<Header />)

      await waitFor(() => {
        expect(screen.getByText(/connected/i)).toBeInTheDocument()
      })
    })

    it('shows green indicator when connected', async () => {
      render(<Header />)

      await waitFor(() => {
        const indicator = document.querySelector('.bg-green-500')
        expect(indicator).toBeInTheDocument()
      })
    })

    it('shows timestamp of last update', async () => {
      render(<Header />)

      await waitFor(() => {
        // Time format like "12:34:56 PM"
        const timeRegex = /\d{1,2}:\d{2}:\d{2}/
        const timeElement = screen.getByText(timeRegex)
        expect(timeElement).toBeInTheDocument()
      })
    })
  })

  describe('Flight phase legend', () => {
    it('shows Ground phase indicator', async () => {
      render(<Header />)
      expect(screen.getByText(/ground/i)).toBeInTheDocument()
    })

    it('shows Climbing phase indicator', async () => {
      render(<Header />)
      expect(screen.getByText(/climbing/i)).toBeInTheDocument()
    })

    it('shows Descending phase indicator', async () => {
      render(<Header />)
      expect(screen.getByText(/descending/i)).toBeInTheDocument()
    })

    it('shows Cruising phase indicator', async () => {
      render(<Header />)
      expect(screen.getByText(/cruising/i)).toBeInTheDocument()
    })

    it('has correct color for each phase', async () => {
      render(<Header />)

      // Check legend indicators
      const grayIndicator = document.querySelector('.bg-gray-500')
      const orangeIndicator = document.querySelector('.bg-orange-500')

      expect(grayIndicator).toBeInTheDocument()
      expect(orangeIndicator).toBeInTheDocument()
    })
  })

  describe('FIDS button', () => {
    it('renders FIDS button when callback provided', async () => {
      const onShowFIDS = vi.fn()
      render(<Header onShowFIDS={onShowFIDS} />)

      expect(screen.getByRole('button', { name: /fids/i })).toBeInTheDocument()
    })

    it('does not render FIDS button when no callback', async () => {
      render(<Header />)
      expect(screen.queryByRole('button', { name: /fids/i })).not.toBeInTheDocument()
    })

    it('calls onShowFIDS when clicked', async () => {
      const user = userEvent.setup()
      const onShowFIDS = vi.fn()
      render(<Header onShowFIDS={onShowFIDS} />)

      const fidsButton = screen.getByRole('button', { name: /fids/i })
      await user.click(fidsButton)

      expect(onShowFIDS).toHaveBeenCalledTimes(1)
    })
  })

  describe('Weather widget integration', () => {
    it('renders weather widget', async () => {
      render(<Header />)

      // Weather widget shows loading initially
      await waitFor(() => {
        // Should show temperature after loading
        expect(screen.getByText(/°C/)).toBeInTheDocument()
      })
    })
  })

  describe('Platform links integration', () => {
    it('renders platform links component', async () => {
      render(<Header />)

      // Platform links has a button for dropdown
      await waitFor(() => {
        expect(screen.getByText(/platform/i)).toBeInTheDocument()
      })
    })
  })

  describe('Performance', () => {
    it('renders within performance threshold', async () => {
      const { time } = await measureRenderTime(() => render(<Header />))
      expect(time).toBeLessThan(PERFORMANCE_THRESHOLDS.initialRender)
    })
  })
})
