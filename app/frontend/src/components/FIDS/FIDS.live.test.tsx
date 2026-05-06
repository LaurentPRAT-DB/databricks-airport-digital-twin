import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import FIDS from './FIDS'
import type { Flight } from '../../types/flight'

const mockSetSelectedFlight = vi.fn()

// Mock useFlightContext to simulate OpenSky live mode
vi.mock('../../context/FlightContext', () => ({
  useFlightContext: () => mockFlightContext,
}))

vi.mock('../../context/AirportConfigContext', () => ({
  useAirportConfigContext: () => ({ currentAirport: 'KSFO' }),
}))

let mockFlightContext: {
  flights: Flight[]
  setSelectedFlight: typeof mockSetSelectedFlight
  dataSource: string | null
}

function makeOpenSkyFlight(overrides: Partial<Flight>): Flight {
  return {
    icao24: 'abc123',
    callsign: 'UAL456',
    latitude: 37.6,
    longitude: -122.4,
    altitude: 3000,
    velocity: 180,
    heading: 280,
    on_ground: false,
    vertical_rate: -1200,
    last_seen: new Date().toISOString(),
    data_source: 'opensky',
    flight_phase: 'approaching',
    origin_airport: 'LAX',
    destination_airport: 'SFO',
    ...overrides,
  }
}

describe('FIDS — Live OpenSky mode', () => {
  const mockOnClose = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    mockFlightContext = {
      flights: [],
      setSelectedFlight: mockSetSelectedFlight,
      dataSource: null,
    }
  })

  it('derives arrivals from tracked flights when dataSource is opensky', async () => {
    mockFlightContext = {
      flights: [
        makeOpenSkyFlight({ icao24: 'a1', callsign: 'DAL789', flight_phase: 'approaching' }),
        makeOpenSkyFlight({ icao24: 'a2', callsign: 'AAL100', flight_phase: 'landing' }),
      ],
      setSelectedFlight: mockSetSelectedFlight,
      dataSource: 'opensky',
    }

    render(<FIDS onClose={mockOnClose} />)

    await waitFor(() => {
      expect(screen.queryByText(/loading schedule/i)).not.toBeInTheDocument()
    })

    // Derived flights should appear (callsigns as flight numbers)
    expect(screen.getByText(/DAL789/i)).toBeInTheDocument()
    expect(screen.getByText(/AAL100/i)).toBeInTheDocument()
  })

  it('derives departures from tracked flights when dataSource is opensky', async () => {
    mockFlightContext = {
      flights: [
        makeOpenSkyFlight({ icao24: 'b1', callsign: 'SWA222', flight_phase: 'pushback' }),
        makeOpenSkyFlight({ icao24: 'b2', callsign: 'JBU333', flight_phase: 'taxi_out' }),
      ],
      setSelectedFlight: mockSetSelectedFlight,
      dataSource: 'opensky',
    }

    render(<FIDS onClose={mockOnClose} />)

    await waitFor(() => {
      expect(screen.queryByText(/loading schedule/i)).not.toBeInTheDocument()
    })

    // Switch to departures tab
    const depTab = screen.getByRole('button', { name: /departures/i })
    depTab.click()

    await waitFor(() => {
      expect(screen.getByText(/SWA222/i)).toBeInTheDocument()
      expect(screen.getByText(/JBU333/i)).toBeInTheDocument()
    })
  })

  it('does not fetch schedule API when dataSource is opensky', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')

    mockFlightContext = {
      flights: [
        makeOpenSkyFlight({ icao24: 'c1', callsign: 'UAL999', flight_phase: 'approaching' }),
      ],
      setSelectedFlight: mockSetSelectedFlight,
      dataSource: 'opensky',
    }

    render(<FIDS onClose={mockOnClose} />)

    await waitFor(() => {
      expect(screen.queryByText(/loading schedule/i)).not.toBeInTheDocument()
    })

    // No schedule API calls should have been made
    const scheduleCalls = fetchSpy.mock.calls.filter(
      ([url]) => typeof url === 'string' && url.includes('/api/schedule/')
    )
    expect(scheduleCalls).toHaveLength(0)

    fetchSpy.mockRestore()
  })

  it('maps flight phases to correct FIDS statuses', async () => {
    mockFlightContext = {
      flights: [
        makeOpenSkyFlight({ icao24: 'd1', callsign: 'UAL101', flight_phase: 'approaching' }),
        makeOpenSkyFlight({ icao24: 'd2', callsign: 'UAL102', flight_phase: 'taxi_in' }),
        makeOpenSkyFlight({ icao24: 'd3', callsign: 'SWA201', flight_phase: 'takeoff' }),
      ],
      setSelectedFlight: mockSetSelectedFlight,
      dataSource: 'opensky',
    }

    render(<FIDS onClose={mockOnClose} />)

    await waitFor(() => {
      expect(screen.getByText(/UAL101/i)).toBeInTheDocument()
    })

    // Approaching → "On Time" or "Delayed"; taxi_in → "Arrived"
    expect(screen.getByText(/arrived/i)).toBeInTheDocument()
  })

  it('falls back to schedule API when dataSource is not opensky/simulation', async () => {
    mockFlightContext = {
      flights: [
        makeOpenSkyFlight({ icao24: 'e1', callsign: 'UAL555', flight_phase: 'approaching' }),
      ],
      setSelectedFlight: mockSetSelectedFlight,
      dataSource: 'synthetic',
    }

    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({
        flights: [], count: 0, airport: 'SFO', flight_type: 'arrival',
      }))
    )

    render(<FIDS onClose={mockOnClose} />)

    await waitFor(() => {
      const scheduleCalls = fetchSpy.mock.calls.filter(
        ([url]) => typeof url === 'string' && url.includes('/api/schedule/')
      )
      expect(scheduleCalls.length).toBeGreaterThan(0)
    })

    fetchSpy.mockRestore()
  })
})
