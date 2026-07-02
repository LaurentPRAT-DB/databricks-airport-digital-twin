import { describe, it, expect, vi, beforeEach } from 'vitest'
import userEvent from '@testing-library/user-event'
import { render, screen, waitFor } from '../../test/test-utils'
import AirportSelector from './AirportSelector'

const mockAirports = [
  { icao: 'KSFO', iata: 'SFO', name: 'San Francisco International', city: 'San Francisco', region: 'Americas', cached: true },
  { icao: 'KJFK', iata: 'JFK', name: 'John F Kennedy International', city: 'New York', region: 'Americas', cached: true },
  { icao: 'EGLL', iata: 'LHR', name: 'Heathrow', city: 'London', region: 'Europe', cached: false },
]

describe('AirportSelector', () => {
  const onAirportChange = vi.fn().mockResolvedValue(undefined)

  beforeEach(() => {
    vi.clearAllMocks()
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ airports: mockAirports }),
    })
  })

  it('renders current airport code', async () => {
    render(<AirportSelector currentAirport="KSFO" onAirportChange={onAirportChange} />)
    await waitFor(() => {
      expect(screen.getByText('KSFO (SFO)')).toBeInTheDocument()
    })
  })

  it('shows placeholder when no airport selected', () => {
    render(<AirportSelector onAirportChange={onAirportChange} />)
    expect(screen.getByText('Select Airport')).toBeInTheDocument()
  })

  it('opens dropdown on click', async () => {
    const user = userEvent.setup()
    render(<AirportSelector currentAirport="KSFO" onAirportChange={onAirportChange} />)

    await user.click(screen.getByRole('button', { name: /ksfo/i }))

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/search airport/i)).toBeInTheDocument()
    })
  })

  it('displays airports grouped by region', async () => {
    const user = userEvent.setup()
    render(<AirportSelector currentAirport="KSFO" onAirportChange={onAirportChange} />)

    await user.click(screen.getByRole('button', { name: /ksfo/i }))

    await waitFor(() => {
      expect(screen.getByText('Americas')).toBeInTheDocument()
      expect(screen.getByText('Europe')).toBeInTheDocument()
    })
  })

  it('calls onAirportChange with selected ICAO', async () => {
    const user = userEvent.setup()
    render(<AirportSelector currentAirport="KSFO" onAirportChange={onAirportChange} />)

    await user.click(screen.getByRole('button', { name: /ksfo/i }))

    await waitFor(() => {
      expect(screen.getByText('KJFK')).toBeInTheDocument()
    })

    await user.click(screen.getByText('KJFK'))

    expect(onAirportChange).toHaveBeenCalledWith('KJFK')
  })

  it('filters airports by search input', async () => {
    const user = userEvent.setup()
    render(<AirportSelector currentAirport="KSFO" onAirportChange={onAirportChange} />)

    await user.click(screen.getByRole('button', { name: /ksfo/i }))

    const input = await screen.findByPlaceholderText(/search airport/i)
    await user.type(input, 'LHR')

    await waitFor(() => {
      expect(screen.getByText('EGLL')).toBeInTheDocument()
      expect(screen.queryByText('KJFK')).not.toBeInTheDocument()
    })
  })

  it('disables button when isLoading is true', () => {
    render(<AirportSelector currentAirport="KSFO" onAirportChange={onAirportChange} isLoading />)
    const btn = screen.getByRole('button', { name: /ksfo/i })
    expect(btn).toBeDisabled()
  })

  it('shows loading spinner when isLoading', () => {
    const { container } = render(
      <AirportSelector currentAirport="KSFO" onAirportChange={onAirportChange} isLoading />
    )
    expect(container.querySelector('.animate-spin')).toBeInTheDocument()
  })

  it('shows error message on failed airport change', async () => {
    const failingChange = vi.fn().mockRejectedValue(new Error('OSM timeout'))
    const user = userEvent.setup()
    render(<AirportSelector currentAirport="KSFO" onAirportChange={failingChange} />)

    await user.click(screen.getByRole('button', { name: /ksfo/i }))
    await waitFor(() => expect(screen.getByText('KJFK')).toBeInTheDocument())
    await user.click(screen.getByText('KJFK'))

    await waitFor(() => {
      expect(screen.getByText('OSM timeout')).toBeInTheDocument()
    })
  })

  it('submits custom ICAO via Enter key', async () => {
    const user = userEvent.setup()
    render(<AirportSelector currentAirport="KSFO" onAirportChange={onAirportChange} />)

    await user.click(screen.getByRole('button', { name: /ksfo/i }))
    const input = await screen.findByPlaceholderText(/search airport/i)
    await user.type(input, 'RJTT{enter}')

    expect(onAirportChange).toHaveBeenCalledWith('RJTT')
  })

  it('shows airport count in footer', async () => {
    const user = userEvent.setup()
    render(<AirportSelector currentAirport="KSFO" onAirportChange={onAirportChange} />)

    await user.click(screen.getByRole('button', { name: /ksfo/i }))

    await waitFor(() => {
      expect(screen.getByText('3 airports cached')).toBeInTheDocument()
    })
  })
})
