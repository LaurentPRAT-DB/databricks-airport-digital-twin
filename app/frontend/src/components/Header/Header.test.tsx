import { describe, it, expect, vi, beforeEach } from 'vitest'
import userEvent from '@testing-library/user-event'
import { render, screen, waitFor, measureRenderTime, PERFORMANCE_THRESHOLDS } from '../../test/test-utils'
import Header from './Header'

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

    it('displays version and build number', () => {
      render(<Header />)
      // vitest.config.ts defines __APP_VERSION__ = '0.0.0-test' and __BUILD_NUMBER__ = '0'
      expect(screen.getByText(/v0\.0\.0-test/)).toBeInTheDocument()
      expect(screen.getByText(/#0/)).toBeInTheDocument()
    })

    it('shows build time in title tooltip', () => {
      render(<Header />)
      const versionEl = screen.getByTitle(/Built 2026/)
      expect(versionEl).toBeInTheDocument()
    })
  })

  describe('Dark mode toggle', () => {
    it('renders dark mode toggle button', () => {
      render(<Header />)
      expect(screen.getByTitle(/switch to dark mode/i)).toBeInTheDocument()
    })
  })

  describe('Connection status', () => {
    it('shows green indicator dot when connected', async () => {
      render(<Header />)

      await waitFor(() => {
        const indicator = document.querySelector('.bg-green-500')
        expect(indicator).toBeInTheDocument()
      })
    })

    it('shows connection info in tooltip', async () => {
      render(<Header />)

      await waitFor(() => {
        const indicator = document.querySelector('.bg-green-500')
        expect(indicator).toBeInTheDocument()
        expect(indicator?.getAttribute('title')).toMatch(/connected/i)
      })
    })
  })

  describe('Legend / Phase filter', () => {
    it('renders Legend button', async () => {
      render(<Header />)
      expect(screen.getByRole('button', { name: /legend/i })).toBeInTheDocument()
    })

    it('opens dropdown on click showing phase names and descriptions', async () => {
      const user = userEvent.setup()
      render(<Header />)

      await user.click(screen.getByRole('button', { name: /legend/i }))

      expect(screen.getByText(/parked/i)).toBeInTheDocument()
      expect(screen.getByText(/takeoff/i)).toBeInTheDocument()
      expect(screen.getByText(/approaching/i)).toBeInTheDocument()
      expect(screen.getByText(/enroute/i)).toBeInTheDocument()
    })

    it('shows Show All and Hide All buttons in dropdown', async () => {
      const user = userEvent.setup()
      render(<Header />)

      await user.click(screen.getByRole('button', { name: /legend/i }))

      expect(screen.getByText(/show all/i)).toBeInTheDocument()
      expect(screen.getByText(/hide all/i)).toBeInTheDocument()
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
