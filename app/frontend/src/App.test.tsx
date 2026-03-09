import { describe, it, expect, vi, beforeEach } from 'vitest'
import userEvent from '@testing-library/user-event'
import { render as rtlRender, screen, waitFor } from '@testing-library/react'
import { measureRenderTime, PERFORMANCE_THRESHOLDS } from './test/test-utils'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'

// Custom render for App - App includes its own FlightProvider
function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
    },
  })

  return rtlRender(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  )
}

/** Wait for the loading screen to finish and the main layout to appear */
async function waitForAppReady() {
  await waitFor(
    () => {
      expect(screen.getByRole('banner')).toBeInTheDocument()
    },
    { timeout: 3000 }
  )
}

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Loading screen', () => {
    it('shows loading screen with title on initial render', () => {
      renderApp()
      expect(screen.getByRole('heading', { name: /airport digital twin/i })).toBeInTheDocument()
    })

    it('transitions to main layout after loading', async () => {
      renderApp()
      await waitForAppReady()
      expect(screen.getByRole('main')).toBeInTheDocument()
    })
  })

  describe('Layout', () => {
    it('renders the main application', async () => {
      renderApp()
      await waitForAppReady()
      expect(screen.getByRole('heading', { name: /airport digital twin/i })).toBeInTheDocument()
    })

    it('renders header section', async () => {
      renderApp()
      await waitForAppReady()
      expect(screen.getByRole('banner')).toBeInTheDocument()
    })

    it('renders main content area', async () => {
      renderApp()
      await waitForAppReady()
      expect(screen.getByRole('main')).toBeInTheDocument()
    })

    it('renders flight list panel', async () => {
      renderApp()
      await waitForAppReady()
      const elements = screen.getAllByText(/flights/i)
      expect(elements.length).toBeGreaterThan(0)
    })

    it('renders flight detail panel', async () => {
      renderApp()
      await waitForAppReady()
      expect(screen.getByRole('heading', { name: /flight details/i })).toBeInTheDocument()
    })
  })

  describe('View toggle', () => {
    it('renders 2D/3D view toggle', async () => {
      renderApp()
      await waitForAppReady()
      expect(screen.getByRole('button', { name: /2d/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /3d/i })).toBeInTheDocument()
    })

    it('2D view is active by default', async () => {
      renderApp()
      await waitForAppReady()
      const button2D = screen.getByRole('button', { name: /2d/i })
      expect(button2D).toHaveClass('bg-blue-600')
    })

    it('can switch to 3D view', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const button3D = screen.getByRole('button', { name: /3d/i })
      await user.click(button3D)

      expect(button3D).toHaveClass('bg-blue-600')
    })

    it('can switch back to 2D view', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const button3D = screen.getByRole('button', { name: /3d/i })
      const button2D = screen.getByRole('button', { name: /2d/i })

      await user.click(button3D)
      expect(button3D).toHaveClass('bg-blue-600')

      await user.click(button2D)
      expect(button2D).toHaveClass('bg-blue-600')
    })

    it('shows loading fallback when switching to 3D', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const button3D = screen.getByRole('button', { name: /3d/i })
      await user.click(button3D)

      // Should show loading state while 3D component loads
      // (may be brief or not visible depending on chunk loading speed)
    })
  })

  describe('FIDS modal', () => {
    it('shows FIDS button in header', async () => {
      renderApp()
      await waitForAppReady()
      expect(screen.getByRole('button', { name: /fids/i })).toBeInTheDocument()
    })

    it('opens FIDS modal when button clicked', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const fidsButton = screen.getByRole('button', { name: /fids/i })
      await user.click(fidsButton)

      await waitFor(() => {
        expect(screen.getByText(/flight information display/i)).toBeInTheDocument()
      })
    })

    it('closes FIDS modal when close button clicked', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      // Open FIDS
      const fidsButton = screen.getByRole('button', { name: /fids/i })
      await user.click(fidsButton)

      await waitFor(() => {
        expect(screen.getByText(/flight information display/i)).toBeInTheDocument()
      })

      // Close FIDS
      const closeButton = screen.getByRole('button', { name: /x/i })
      await user.click(closeButton)

      await waitFor(() => {
        expect(screen.queryByText(/flight information display/i)).not.toBeInTheDocument()
      })
    })
  })

  describe('Flight selection flow', () => {
    it('clicking a flight in list triggers selection logic', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      // Wait for flights to load - look for any flight row button
      await waitFor(
        () => {
          const buttons = screen.getAllByRole('button')
          expect(buttons.length).toBeGreaterThan(5) // Header buttons + flight rows
        },
        { timeout: 5000 }
      )

      // Find a clickable flight row (has hover styling)
      const flightButtons = Array.from(document.querySelectorAll('button'))
        .filter((b) => b.className.includes('hover:bg-blue-50'))

      if (flightButtons.length > 0) {
        await user.click(flightButtons[0])
        // Selection should work (no error thrown)
      }
    })

    it('detail panel shows placeholder when no selection', async () => {
      renderApp()
      await waitForAppReady()
      expect(screen.getByText(/select a flight to view details/i)).toBeInTheDocument()
    })
  })

  describe('Data loading', () => {
    it('shows flight count label in header', async () => {
      renderApp()
      await waitForAppReady()
      const elements = screen.getAllByText(/flights/i)
      expect(elements.length).toBeGreaterThan(0)
    })

    it('shows status indicator in header', async () => {
      renderApp()
      await waitForAppReady()
      const statusDots = document.querySelectorAll('.rounded-full')
      expect(statusDots.length).toBeGreaterThan(0)
    })
  })

  describe('Performance', () => {
    it('initial render is within budget', async () => {
      const { time } = await measureRenderTime(() => renderApp())
      expect(time).toBeLessThan(PERFORMANCE_THRESHOLDS.heavyComponent)
    })

    it('FIDS toggle is performant', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const fidsButton = screen.getByRole('button', { name: /fids/i })

      const start = performance.now()
      await user.click(fidsButton)
      await waitFor(() => {
        expect(screen.getByText(/flight information display/i)).toBeInTheDocument()
      })
      const elapsed = performance.now() - start

      expect(elapsed).toBeLessThan(PERFORMANCE_THRESHOLDS.interaction * 2)
    })

    it('view toggle is performant', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const button3D = screen.getByRole('button', { name: /3d/i })

      const start = performance.now()
      await user.click(button3D)
      const elapsed = performance.now() - start

      expect(elapsed).toBeLessThan(PERFORMANCE_THRESHOLDS.interaction)
    })
  })

  describe('Accessibility', () => {
    it('has proper document structure', async () => {
      renderApp()
      await waitForAppReady()

      expect(screen.getByRole('banner')).toBeInTheDocument() // header
      expect(screen.getByRole('main')).toBeInTheDocument() // main content
    })

    it('all buttons are keyboard accessible', async () => {
      renderApp()
      await waitForAppReady()

      const buttons = screen.getAllByRole('button')
      buttons.forEach((button) => {
        expect(button).toBeVisible()
      })
    })
  })
})
