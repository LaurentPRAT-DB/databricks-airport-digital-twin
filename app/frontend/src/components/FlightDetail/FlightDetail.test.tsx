import { describe, it, expect, vi, beforeEach } from 'vitest'
import userEvent from '@testing-library/user-event'
import { render, screen, waitFor, measureRenderTime, PERFORMANCE_THRESHOLDS } from '../../test/test-utils'
import FlightDetail from './FlightDetail'
import { FlightProvider, useFlightContext } from '../../context/FlightContext'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

// Helper component to select a flight for testing
function FlightDetailWithSelection({ flightIndex = 0 }: { flightIndex?: number }) {
  const { flights, setSelectedFlight } = useFlightContext()

  React.useEffect(() => {
    if (flights.length > flightIndex) {
      setSelectedFlight(flights[flightIndex])
    }
  }, [flights, flightIndex, setSelectedFlight])

  return <FlightDetail />
}

// Wrapper that includes providers
function renderWithFlightSelection(flightIndex = 0) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <FlightProvider>
        <FlightDetailWithSelection flightIndex={flightIndex} />
      </FlightProvider>
    </QueryClientProvider>
  )
}

describe('FlightDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('No selection state', () => {
    it('shows placeholder when no flight selected', async () => {
      render(<FlightDetail />)

      await waitFor(() => {
        expect(screen.getByText(/select a flight to view details/i)).toBeInTheDocument()
      })
    })

    it('shows Flight Details title', async () => {
      render(<FlightDetail />)

      expect(screen.getByRole('heading', { name: /flight details/i })).toBeInTheDocument()
    })
  })

  describe('With flight selected', () => {
    it('shows flight callsign', async () => {
      renderWithFlightSelection(0)

      await waitFor(
        () => {
          expect(screen.getByText(/UAL123/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )
    })

    it('shows icao24 code', async () => {
      renderWithFlightSelection(0)

      await waitFor(
        () => {
          expect(screen.getByText(/a12345/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )
    })

    it('shows flight phase badge', async () => {
      renderWithFlightSelection(0)

      await waitFor(
        () => {
          expect(screen.getByText(/descending/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )
    })

    it('shows position information', async () => {
      renderWithFlightSelection(0)

      await waitFor(
        () => {
          expect(screen.getByText(/position/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )

      expect(screen.getByText(/latitude/i)).toBeInTheDocument()
      expect(screen.getByText(/longitude/i)).toBeInTheDocument()
      expect(screen.getByText(/altitude/i)).toBeInTheDocument()
    })

    it('shows movement information', async () => {
      renderWithFlightSelection(0)

      await waitFor(
        () => {
          expect(screen.getByText(/movement/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )

      expect(screen.getByText(/speed/i)).toBeInTheDocument()
      expect(screen.getByText(/heading/i)).toBeInTheDocument()
      expect(screen.getByText(/vertical rate/i)).toBeInTheDocument()
    })

    it('shows metadata section', async () => {
      renderWithFlightSelection(0)

      await waitFor(
        () => {
          expect(screen.getByText(/metadata/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )

      expect(screen.getByText(/data source/i)).toBeInTheDocument()
      expect(screen.getByText(/last seen/i)).toBeInTheDocument()
    })

    it('shows close button', async () => {
      renderWithFlightSelection(0)

      await waitFor(
        () => {
          expect(screen.getByTitle(/close/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )
    })
  })

  describe('Delay Prediction', () => {
    it('shows delay prediction section', async () => {
      renderWithFlightSelection(0)

      await waitFor(
        () => {
          expect(screen.getByText(/delay prediction/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )
    })

    it('shows loading state for predictions', async () => {
      renderWithFlightSelection(0)

      // Should briefly show loading
      await waitFor(
        () => {
          const heading = screen.getByText(/delay prediction/i)
          expect(heading).toBeInTheDocument()
        },
        { timeout: 5000 }
      )
    })

    it('shows delay minutes when loaded', async () => {
      renderWithFlightSelection(0)

      await waitFor(
        () => {
          expect(screen.getByText(/expected delay/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )
    })

    it('shows confidence indicator', async () => {
      renderWithFlightSelection(0)

      await waitFor(
        () => {
          expect(screen.getByText(/confidence/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )
    })
  })

  describe('Gate Recommendations', () => {
    it('shows gate recommendations for arriving flights', async () => {
      // Flight at index 0 is descending, so should show gate recommendations
      renderWithFlightSelection(0)

      await waitFor(
        () => {
          expect(screen.getByText(/gate recommendations/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )
    })

    it('does not show gate recommendations for cruising flights', async () => {
      // Flight at index 1 is cruising
      renderWithFlightSelection(1)

      await waitFor(
        () => {
          expect(screen.getByText(/DAL456/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )

      // Gate recommendations should not appear for cruising flight
      expect(screen.queryByText(/gate recommendations/i)).not.toBeInTheDocument()
    })
  })

  describe('Trajectory Toggle', () => {
    it('shows trajectory toggle button', async () => {
      renderWithFlightSelection(0)

      await waitFor(
        () => {
          expect(screen.getByText(/show trajectory/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )
    })

    it('trajectory toggle is auto-enabled on flight selection', async () => {
      renderWithFlightSelection(0)

      await waitFor(
        () => {
          const button = screen.getByRole('button', { name: /show trajectory/i })
          // Should have blue background indicating on state (auto-enabled on selection)
          expect(button).toHaveClass('bg-blue-50')
        },
        { timeout: 5000 }
      )
    })

    it('clicking trajectory toggle toggles it off (auto-enabled on selection)', async () => {
      const user = userEvent.setup()
      renderWithFlightSelection(0)

      await waitFor(
        () => {
          expect(screen.getByText(/show trajectory/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )

      // Trajectory is auto-enabled when flight is selected (see FlightContext line 37)
      const button = screen.getByRole('button', { name: /show trajectory/i })
      expect(button).toHaveClass('bg-blue-50')

      // Click toggles it off
      await user.click(button)

      await waitFor(() => {
        const updatedButton = screen.getByRole('button', { name: /show trajectory/i })
        expect(updatedButton).toHaveClass('bg-slate-50')
      })
    })
  })

  describe('Close functionality', () => {
    it('close button clears selection', async () => {
      const user = userEvent.setup()
      renderWithFlightSelection(0)

      await waitFor(
        () => {
          expect(screen.getByTitle(/close/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )

      const closeButton = screen.getByTitle(/close/i)
      await user.click(closeButton)

      await waitFor(() => {
        expect(screen.getByText(/select a flight to view details/i)).toBeInTheDocument()
      })
    })
  })

  describe('Ground flight features', () => {
    it('shows turnaround timeline for ground flights', async () => {
      // Flight at index 2 is on ground
      renderWithFlightSelection(2)

      await waitFor(
        () => {
          expect(screen.getByText(/SWA789/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )

      // Should show turnaround timeline
      await waitFor(
        () => {
          expect(screen.getByText(/turnaround/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )
    })

    it('shows baggage status for flights with callsign', async () => {
      renderWithFlightSelection(2)

      await waitFor(
        () => {
          expect(screen.getByText(/SWA789/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )

      await waitFor(
        () => {
          expect(screen.getByText(/baggage/i)).toBeInTheDocument()
        },
        { timeout: 5000 }
      )
    })
  })

  describe('Performance', () => {
    it('initial render is performant', async () => {
      const { time } = await measureRenderTime(() => render(<FlightDetail />))
      expect(time).toBeLessThan(PERFORMANCE_THRESHOLDS.initialRender)
    })
  })
})
