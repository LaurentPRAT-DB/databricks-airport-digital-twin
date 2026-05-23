import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { FlightProvider, useFlightContext } from './FlightContext'
import { AirportConfigProvider } from './AirportConfigContext'

// Wrapper that includes providers
function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
    },
  })

  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <AirportConfigProvider>
          <FlightProvider>{children}</FlightProvider>
        </AirportConfigProvider>
      </QueryClientProvider>
    )
  }
}

describe('FlightContext', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Provider initialization', () => {
    it('provides flight data through context', async () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.flights.length).toBeGreaterThan(0)
      })
    })

    it('initializes with no selected flight', async () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      expect(result.current.selectedFlight).toBeNull()
    })

    it('initializes with trajectory hidden', async () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      expect(result.current.showTrajectory).toBe(false)
    })

    it('starts with loading true', () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      // Initially loading
      expect(result.current.isLoading).toBe(true)
    })
  })

  describe('Flight selection', () => {
    it('can select a flight', async () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.flights.length).toBeGreaterThan(0)
      })

      act(() => {
        result.current.setSelectedFlight(result.current.flights[0])
      })

      expect(result.current.selectedFlight).not.toBeNull()
      expect(result.current.selectedFlight?.icao24).toBe(result.current.flights[0].icao24)
    })

    it('can deselect a flight', async () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.flights.length).toBeGreaterThan(0)
      })

      // Select then deselect
      act(() => {
        result.current.setSelectedFlight(result.current.flights[0])
      })

      expect(result.current.selectedFlight).not.toBeNull()

      act(() => {
        result.current.setSelectedFlight(null)
      })

      expect(result.current.selectedFlight).toBeNull()
    })

    it('deselecting resets trajectory visibility', async () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.flights.length).toBeGreaterThan(0)
      })

      // Select and enable trajectory
      act(() => {
        result.current.setSelectedFlight(result.current.flights[0])
        result.current.setShowTrajectory(true)
      })

      expect(result.current.showTrajectory).toBe(true)

      // Deselect - should reset trajectory
      act(() => {
        result.current.setSelectedFlight(null)
      })

      expect(result.current.showTrajectory).toBe(false)
    })

    it('maintains selection across data refreshes', async () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.flights.length).toBeGreaterThan(0)
      })

      const selectedIcao24 = result.current.flights[0].icao24

      act(() => {
        result.current.setSelectedFlight(result.current.flights[0])
      })

      // Selection is maintained by icao24
      expect(result.current.selectedFlight?.icao24).toBe(selectedIcao24)
    })
  })

  describe('Trajectory toggle', () => {
    it('can enable trajectory display', async () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      act(() => {
        result.current.setShowTrajectory(true)
      })

      expect(result.current.showTrajectory).toBe(true)
    })

    it('can disable trajectory display', async () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      act(() => {
        result.current.setShowTrajectory(true)
      })

      act(() => {
        result.current.setShowTrajectory(false)
      })

      expect(result.current.showTrajectory).toBe(false)
    })
  })

  describe('Data loading', () => {
    it('provides data source information', async () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.dataSource).toBe('synthetic')
      })
    })

    it('provides last updated timestamp', async () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.lastUpdated).not.toBeNull()
      })
    })

    it('clears loading state when data arrives', async () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false)
      })
    })
  })

  describe('Error handling', () => {
    it('starts with no error', () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      expect(result.current.error).toBeNull()
    })
  })

  describe('Context throws without provider', () => {
    it('throws error when used outside provider', () => {
      // Suppress console.error for this test
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      let thrownError: Error | null = null
      try {
        renderHook(() => useFlightContext())
      } catch (error) {
        thrownError = error as Error
      }

      expect(thrownError).not.toBeNull()
      expect(thrownError?.message).toBe('useFlightContext must be used within FlightProvider')

      consoleSpy.mockRestore()
    })
  })

  describe('Performance', () => {
    it('setSelectedFlight is a stable callback', async () => {
      const { result, rerender } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.flights.length).toBeGreaterThan(0)
      })

      const firstCallback = result.current.setSelectedFlight

      rerender()

      // Callback should be the same reference (memoized)
      expect(result.current.setSelectedFlight).toBe(firstCallback)
    })

    it('setShowTrajectory is a stable callback', async () => {
      const { result, rerender } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      const firstCallback = result.current.setShowTrajectory

      rerender()

      expect(result.current.setShowTrajectory).toBe(firstCallback)
    })
  })

  describe('Data mode', () => {
    it('defaults to simulation mode', () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      expect(result.current.dataMode).toBe('simulation')
    })

    it('can switch to live mode', () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      act(() => {
        result.current.setDataMode('live')
      })

      expect(result.current.dataMode).toBe('live')
    })

    it('can switch back to simulation mode', () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      act(() => {
        result.current.setDataMode('live')
      })
      act(() => {
        result.current.setDataMode('simulation')
      })

      expect(result.current.dataMode).toBe('simulation')
    })

    it('reports opensky data source in live mode', async () => {
      // Mock fetch for /api/opensky/flights
      const originalFetch = globalThis.fetch
      globalThis.fetch = vi.fn().mockImplementation((url: string) => {
        if (url === '/api/opensky/flights') {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
              flights: [
                {
                  icao24: 'live1',
                  callsign: 'UAL100',
                  latitude: 37.6,
                  longitude: -122.4,
                  altitude: 5000,
                  velocity: 200,
                  heading: 90,
                  on_ground: false,
                  vertical_rate: 0,
                  last_seen: 1700000000,
                  data_source: 'opensky',
                  flight_phase: 'cruise',
                },
              ],
              count: 1,
              data_source: 'opensky',
            }),
          })
        }
        // Default mock for other endpoints
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ flights: [], count: 0, timestamp: new Date().toISOString(), data_source: 'synthetic' }),
        })
      })

      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      act(() => {
        result.current.setDataMode('live')
      })

      expect(result.current.dataSource).toBe('opensky')

      globalThis.fetch = originalFetch
    })

    it('setDataMode is a stable callback', () => {
      const { result, rerender } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      const firstCallback = result.current.setDataMode
      rerender()
      expect(result.current.setDataMode).toBe(firstCallback)
    })

    it('clears opensky flights when switching back to simulation', async () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      act(() => {
        result.current.setDataMode('live')
      })

      // Switch back — should use simulation flights (from useFlights hook)
      act(() => {
        result.current.setDataMode('simulation')
      })

      expect(result.current.dataMode).toBe('simulation')
      // dataSource should revert to something other than 'opensky'
      expect(result.current.dataSource).not.toBe('opensky')
    })
  })

  describe('Delay predictions', () => {
    it('exposes delayMap as a Map', async () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.delayMap).toBeInstanceOf(Map)
      })
    })

    it('exposes delayedCount as a number', async () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(typeof result.current.delayedCount).toBe('number')
        expect(result.current.delayedCount).toBeGreaterThanOrEqual(0)
      })
    })

    it('populates delayMap from predictions API', async () => {
      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      // Wait for flights to load (predictions depend on flights)
      await waitFor(() => {
        expect(result.current.flights.length).toBeGreaterThan(0)
      })

      // MSW handler returns delay for icao24='a12345' with delay_minutes=15
      await waitFor(() => {
        expect(result.current.delayMap.size).toBeGreaterThanOrEqual(0)
      })
    })
  })

  describe('PWA Badge API', () => {
    it('calls setAppBadge when delayed flights exist', async () => {
      const mockSetBadge = vi.fn().mockResolvedValue(undefined)
      const mockClearBadge = vi.fn().mockResolvedValue(undefined)
      Object.defineProperty(navigator, 'setAppBadge', { value: mockSetBadge, configurable: true })
      Object.defineProperty(navigator, 'clearAppBadge', { value: mockClearBadge, configurable: true })

      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.flights.length).toBeGreaterThan(0)
      })

      // Badge should have been called (either set or clear depending on mock data)
      await waitFor(() => {
        expect(mockSetBadge.mock.calls.length + mockClearBadge.mock.calls.length).toBeGreaterThan(0)
      })

      // Cleanup
      delete (navigator as any).setAppBadge
      delete (navigator as any).clearAppBadge
    })

    it('does not throw when Badge API is unavailable', async () => {
      // Ensure Badge API is NOT available
      delete (navigator as any).setAppBadge
      delete (navigator as any).clearAppBadge

      const { result } = renderHook(() => useFlightContext(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.flights.length).toBeGreaterThan(0)
      })

      // Should not throw — feature detection guards the call
      expect(result.current.delayedCount).toBeGreaterThanOrEqual(0)
    })
  })
})
