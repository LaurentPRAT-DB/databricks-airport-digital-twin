import { describe, it, expect, vi, beforeEach } from 'vitest'
import userEvent from '@testing-library/user-event'
import { render, screen, waitFor, measureRenderTime, PERFORMANCE_THRESHOLDS } from '../../test/test-utils'
import FlightList from './FlightList'
import { mockFlights } from '../../test/mocks/handlers'

describe('FlightList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Rendering', () => {
    it('renders loading state initially', async () => {
      render(<FlightList />)
      expect(screen.getByText(/loading flights/i)).toBeInTheDocument()
    })

    it('renders flight list after loading', async () => {
      render(<FlightList />)
      await waitFor(() => {
        expect(screen.queryByText(/loading flights/i)).not.toBeInTheDocument()
      })
      // Flight count should be shown
      expect(screen.getByText(/flights/i)).toBeInTheDocument()
    })

    it('renders search input', async () => {
      render(<FlightList />)
      await waitFor(() => {
        expect(screen.queryByText(/loading flights/i)).not.toBeInTheDocument()
      })
      expect(screen.getByPlaceholderText(/search callsign/i)).toBeInTheDocument()
    })

    it('renders sort dropdown', async () => {
      render(<FlightList />)
      await waitFor(() => {
        expect(screen.queryByText(/loading flights/i)).not.toBeInTheDocument()
      })
      expect(screen.getByLabelText(/sort/i)).toBeInTheDocument()
    })

    it('displays correct flight count', async () => {
      render(<FlightList />)
      await waitFor(() => {
        expect(screen.getByText(`(${mockFlights.length})`)).toBeInTheDocument()
      })
    })
  })

  describe('Search functionality', () => {
    it('filters flights by callsign', async () => {
      const user = userEvent.setup()
      render(<FlightList />)

      await waitFor(() => {
        expect(screen.queryByText(/loading flights/i)).not.toBeInTheDocument()
      })

      const searchInput = screen.getByPlaceholderText(/search callsign/i)
      await user.type(searchInput, 'UAL')

      await waitFor(() => {
        expect(screen.getByText('(1)')).toBeInTheDocument() // Only UAL123 should match
      })
    })

    it('filters flights by icao24', async () => {
      const user = userEvent.setup()
      render(<FlightList />)

      await waitFor(() => {
        expect(screen.queryByText(/loading flights/i)).not.toBeInTheDocument()
      })

      const searchInput = screen.getByPlaceholderText(/search callsign/i)
      await user.type(searchInput, 'a12')

      await waitFor(() => {
        expect(screen.getByText('(1)')).toBeInTheDocument()
      })
    })

    it('shows no results message when no flights match', async () => {
      const user = userEvent.setup()
      render(<FlightList />)

      await waitFor(() => {
        expect(screen.queryByText(/loading flights/i)).not.toBeInTheDocument()
      })

      const searchInput = screen.getByPlaceholderText(/search callsign/i)
      await user.type(searchInput, 'ZZZZZ')

      await waitFor(() => {
        expect(screen.getByText(/no flights match your search/i)).toBeInTheDocument()
      })
    })

    it('clears search restores all flights', async () => {
      const user = userEvent.setup()
      render(<FlightList />)

      await waitFor(() => {
        expect(screen.queryByText(/loading flights/i)).not.toBeInTheDocument()
      })

      const searchInput = screen.getByPlaceholderText(/search callsign/i)
      await user.type(searchInput, 'UAL')

      await waitFor(() => {
        expect(screen.getByText('(1)')).toBeInTheDocument()
      })

      await user.clear(searchInput)

      await waitFor(() => {
        expect(screen.getByText(`(${mockFlights.length})`)).toBeInTheDocument()
      })
    })

    it('search is case insensitive', async () => {
      const user = userEvent.setup()
      render(<FlightList />)

      await waitFor(() => {
        expect(screen.queryByText(/loading flights/i)).not.toBeInTheDocument()
      })

      const searchInput = screen.getByPlaceholderText(/search callsign/i)
      await user.type(searchInput, 'ual') // lowercase

      await waitFor(() => {
        expect(screen.getByText('(1)')).toBeInTheDocument()
      })
    })
  })

  describe('Sorting functionality', () => {
    it('sorts by callsign by default', async () => {
      render(<FlightList />)

      await waitFor(() => {
        expect(screen.queryByText(/loading flights/i)).not.toBeInTheDocument()
      })

      const sortSelect = screen.getByLabelText(/sort/i)
      expect(sortSelect).toHaveValue('callsign')
    })

    it('can sort by altitude', async () => {
      const user = userEvent.setup()
      render(<FlightList />)

      await waitFor(() => {
        expect(screen.queryByText(/loading flights/i)).not.toBeInTheDocument()
      })

      const sortSelect = screen.getByLabelText(/sort/i)
      await user.selectOptions(sortSelect, 'altitude')

      expect(sortSelect).toHaveValue('altitude')
    })

    it('altitude sort orders highest first', async () => {
      const user = userEvent.setup()
      render(<FlightList />)

      await waitFor(() => {
        expect(screen.queryByText(/loading flights/i)).not.toBeInTheDocument()
      })

      const sortSelect = screen.getByLabelText(/sort/i)
      await user.selectOptions(sortSelect, 'altitude')

      // DAL456 has highest altitude (35000) and should be first
      const flightRows = screen.getAllByRole('button')
      // First clickable flight should be DAL456
      expect(flightRows[0]).toHaveTextContent(/DAL456/i)
    })
  })

  describe('Flight selection', () => {
    it('clicking a flight selects it', async () => {
      const user = userEvent.setup()
      render(<FlightList />)

      await waitFor(() => {
        expect(screen.queryByText(/loading flights/i)).not.toBeInTheDocument()
      })

      // Find and click a flight row
      const flightRow = screen.getByText(/UAL123/i).closest('button')
      if (flightRow) {
        await user.click(flightRow)
      }

      // The row should now have selected styling
      await waitFor(() => {
        expect(flightRow).toHaveClass('bg-blue-50')
      })
    })

    it('clicking selected flight deselects it', async () => {
      const user = userEvent.setup()
      render(<FlightList />)

      await waitFor(() => {
        expect(screen.queryByText(/loading flights/i)).not.toBeInTheDocument()
      })

      const flightRow = screen.getByText(/UAL123/i).closest('button')
      if (flightRow) {
        // Select
        await user.click(flightRow)
        await waitFor(() => {
          expect(flightRow).toHaveClass('bg-blue-50')
        })

        // Deselect
        await user.click(flightRow)
        await waitFor(() => {
          expect(flightRow).not.toHaveClass('bg-blue-50')
        })
      }
    })
  })

  describe('Performance', () => {
    it('renders within performance threshold', async () => {
      const { time } = await measureRenderTime(() => render(<FlightList />))
      expect(time).toBeLessThan(PERFORMANCE_THRESHOLDS.initialRender)
    })

    it('search filtering is performant', async () => {
      const user = userEvent.setup()
      render(<FlightList />)

      await waitFor(() => {
        expect(screen.queryByText(/loading flights/i)).not.toBeInTheDocument()
      })

      const searchInput = screen.getByPlaceholderText(/search callsign/i)

      const start = performance.now()
      await user.type(searchInput, 'UAL')
      const elapsed = performance.now() - start

      expect(elapsed).toBeLessThan(PERFORMANCE_THRESHOLDS.interaction)
    })
  })
})
