import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { useFlights } from './useFlights'
import { mockFlights } from '../test/mocks/handlers'
import { server } from '../test/mocks/server'
import { http, HttpResponse, delay } from 'msw'

// --- WebSocket mock ---
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  url: string;
  readyState = MockWebSocket.CONNECTING;
  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  close = vi.fn(() => { this.readyState = MockWebSocket.CLOSED; });
  send = vi.fn();

  constructor(url: string) {
    this.url = url;
    mockWsInstances.push(this);
    // Auto-open on next tick so tests can attach handlers
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN;
      this.onopen?.(new Event('open'));
    }, 0);
  }

  simulateMessage(data: object) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) }));
  }

  simulateClose() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({} as CloseEvent);
  }
}

let mockWsInstances: MockWebSocket[] = [];

// Wrapper that includes QueryClientProvider
function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
    },
  })

  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children)
  }
}

describe('useFlights', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockWsInstances = []
    vi.stubGlobal('WebSocket', MockWebSocket)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  describe('Initial state', () => {
    it('starts with loading true', () => {
      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      expect(result.current.isLoading).toBe(true)
    })

    it('starts with empty flights array', () => {
      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      expect(result.current.flights).toEqual([])
    })

    it('starts with no error', () => {
      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      expect(result.current.error).toBeNull()
    })

    it('starts with null lastUpdated', () => {
      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      expect(result.current.lastUpdated).toBeNull()
    })

    it('starts with null dataSource', () => {
      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      expect(result.current.dataSource).toBeNull()
    })
  })

  describe('WebSocket updates', () => {
    it('receives flights via WebSocket initial message', async () => {
      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      // Wait for WS to connect
      await waitFor(() => expect(mockWsInstances.length).toBe(1))

      // Send initial message
      mockWsInstances[0].simulateMessage({
        type: 'initial',
        data: {
          flights: mockFlights,
          count: mockFlights.length,
          timestamp: new Date().toISOString(),
        },
      })

      await waitFor(() => {
        expect(result.current.flights.length).toBe(mockFlights.length)
      })
    })

    it('receives flights via WebSocket flight_update message', async () => {
      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => expect(mockWsInstances.length).toBe(1))

      mockWsInstances[0].simulateMessage({
        type: 'flight_update',
        data: {
          flights: mockFlights,
          count: mockFlights.length,
          timestamp: new Date().toISOString(),
        },
      })

      await waitFor(() => {
        expect(result.current.flights.length).toBe(mockFlights.length)
      })

      expect(result.current.isLoading).toBe(false)
      expect(result.current.lastUpdated).not.toBeNull()
    })

    it('ignores in-progress airport_switch_progress messages', async () => {
      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => expect(mockWsInstances.length).toBe(1))

      mockWsInstances[0].simulateMessage({
        type: 'airport_switch_progress',
        data: { step: 1, total: 3, message: 'Loading...', icaoCode: 'KJFK', done: false },
      })

      // Should still have no flights
      expect(result.current.flights).toEqual([])
    })

    it('clears flights on airport_switch_progress done', async () => {
      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => expect(mockWsInstances.length).toBe(1))

      // Populate flights first
      mockWsInstances[0].simulateMessage({
        type: 'initial',
        data: { flights: mockFlights, count: mockFlights.length, timestamp: new Date().toISOString() },
      })

      await waitFor(() => expect(result.current.flights.length).toBe(mockFlights.length))

      // Airport switch completes — should clear old flights
      mockWsInstances[0].simulateMessage({
        type: 'airport_switch_progress',
        data: { step: 3, total: 3, message: 'Airport ready', icaoCode: 'KJFK', done: true },
      })

      await waitFor(() => expect(result.current.flights).toEqual([]))
    })
  })

  describe('HTTP fallback', () => {
    it('falls back to HTTP polling when WebSocket fails', async () => {
      // Make WS fail immediately
      vi.stubGlobal('WebSocket', class {
        constructor() { throw new Error('WS unavailable'); }
      })

      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      // Should fall back to HTTP and eventually get flights
      await waitFor(() => {
        expect(result.current.flights.length).toBe(mockFlights.length)
      }, { timeout: 5000 })
    })

    it('populates flights after loading via HTTP', async () => {
      // Disable WS so HTTP fallback kicks in
      vi.stubGlobal('WebSocket', class {
        constructor() { throw new Error('WS unavailable'); }
      })

      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.flights.length).toBe(mockFlights.length)
      })
    })

    it('provides lastUpdated timestamp via HTTP', async () => {
      vi.stubGlobal('WebSocket', class {
        constructor() { throw new Error('WS unavailable'); }
      })

      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.lastUpdated).not.toBeNull()
      })
    })

    it('provides dataSource via HTTP', async () => {
      vi.stubGlobal('WebSocket', class {
        constructor() { throw new Error('WS unavailable'); }
      })

      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.dataSource).toBe('synthetic')
      })
    })
  })

  describe('Data structure', () => {
    it('returns flights with correct structure from WS', async () => {
      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => expect(mockWsInstances.length).toBe(1))

      mockWsInstances[0].simulateMessage({
        type: 'initial',
        data: {
          flights: mockFlights,
          count: mockFlights.length,
          timestamp: new Date().toISOString(),
        },
      })

      await waitFor(() => {
        expect(result.current.flights.length).toBeGreaterThan(0)
      })

      const flight = result.current.flights[0]
      expect(flight).toHaveProperty('icao24')
      expect(flight).toHaveProperty('callsign')
      expect(flight).toHaveProperty('latitude')
      expect(flight).toHaveProperty('longitude')
      expect(flight).toHaveProperty('altitude')
    })

    it('returns correct types from WS data', async () => {
      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => expect(mockWsInstances.length).toBe(1))

      mockWsInstances[0].simulateMessage({
        type: 'initial',
        data: {
          flights: mockFlights,
          count: mockFlights.length,
          timestamp: new Date().toISOString(),
        },
      })

      await waitFor(() => {
        expect(result.current.flights.length).toBeGreaterThan(0)
      })

      const flight = result.current.flights[0]
      expect(typeof flight.icao24).toBe('string')
      expect(typeof flight.latitude).toBe('number')
      expect(typeof flight.longitude).toBe('number')
    })
  })

  describe('Delta WebSocket updates', () => {
    it('applies flight_delta to update existing flights', async () => {
      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => expect(mockWsInstances.length).toBe(1))

      // Send initial full data
      mockWsInstances[0].simulateMessage({
        type: 'initial',
        data: {
          flights: [
            { icao24: 'abc', callsign: 'UAL1', latitude: 37.0, longitude: -122.0, altitude: 5000 },
            { icao24: 'def', callsign: 'DAL2', latitude: 38.0, longitude: -121.0, altitude: 6000 },
          ],
          count: 2,
          timestamp: new Date().toISOString(),
        },
      })

      await waitFor(() => expect(result.current.flights.length).toBe(2))

      // Send delta — only update abc's position
      mockWsInstances[0].simulateMessage({
        type: 'flight_delta',
        data: {
          deltas: [{ icao24: 'abc', latitude: 37.01, longitude: -122.01 }],
          removed: [],
          count: 2,
          timestamp: new Date().toISOString(),
        },
      })

      await waitFor(() => {
        const abc = result.current.flights.find(f => f.icao24 === 'abc')
        expect(abc?.latitude).toBe(37.01)
        expect(abc?.longitude).toBe(-122.01)
      })

      // Unchanged fields should be preserved
      const abc = result.current.flights.find(f => f.icao24 === 'abc')
      expect(abc?.callsign).toBe('UAL1')
      expect(abc?.altitude).toBe(5000)

      // Other flight should be unchanged
      const def2 = result.current.flights.find(f => f.icao24 === 'def')
      expect(def2?.latitude).toBe(38.0)
    })

    it('adds new flights from delta', async () => {
      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => expect(mockWsInstances.length).toBe(1))

      // Send initial with one flight
      mockWsInstances[0].simulateMessage({
        type: 'initial',
        data: {
          flights: [{ icao24: 'abc', callsign: 'UAL1', latitude: 37.0, longitude: -122.0, altitude: 5000 }],
          count: 1,
          timestamp: new Date().toISOString(),
        },
      })

      await waitFor(() => expect(result.current.flights.length).toBe(1))

      // Delta adds a new flight
      mockWsInstances[0].simulateMessage({
        type: 'flight_delta',
        data: {
          deltas: [{ icao24: 'xyz', callsign: 'SWA5', latitude: 39.0, longitude: -120.0, altitude: 8000 }],
          removed: [],
          count: 2,
          timestamp: new Date().toISOString(),
        },
      })

      await waitFor(() => expect(result.current.flights.length).toBe(2))
      const xyz = result.current.flights.find(f => f.icao24 === 'xyz')
      expect(xyz?.callsign).toBe('SWA5')
    })

    it('removes departed flights from delta', async () => {
      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => expect(mockWsInstances.length).toBe(1))

      // Send initial with two flights
      mockWsInstances[0].simulateMessage({
        type: 'initial',
        data: {
          flights: [
            { icao24: 'abc', callsign: 'UAL1', latitude: 37.0, longitude: -122.0, altitude: 5000 },
            { icao24: 'def', callsign: 'DAL2', latitude: 38.0, longitude: -121.0, altitude: 6000 },
          ],
          count: 2,
          timestamp: new Date().toISOString(),
        },
      })

      await waitFor(() => expect(result.current.flights.length).toBe(2))

      // Delta removes one flight
      mockWsInstances[0].simulateMessage({
        type: 'flight_delta',
        data: {
          deltas: [],
          removed: ['def'],
          count: 1,
          timestamp: new Date().toISOString(),
        },
      })

      await waitFor(() => expect(result.current.flights.length).toBe(1))
      expect(result.current.flights[0].icao24).toBe('abc')
    })

    it('handles mixed add/update/remove in single delta', async () => {
      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => expect(mockWsInstances.length).toBe(1))

      // Initial: 3 flights
      mockWsInstances[0].simulateMessage({
        type: 'initial',
        data: {
          flights: [
            { icao24: 'aaa', callsign: 'F1', latitude: 1.0, longitude: 1.0, altitude: 1000 },
            { icao24: 'bbb', callsign: 'F2', latitude: 2.0, longitude: 2.0, altitude: 2000 },
            { icao24: 'ccc', callsign: 'F3', latitude: 3.0, longitude: 3.0, altitude: 3000 },
          ],
          count: 3,
          timestamp: new Date().toISOString(),
        },
      })

      await waitFor(() => expect(result.current.flights.length).toBe(3))

      // Delta: update aaa, remove bbb, add ddd
      mockWsInstances[0].simulateMessage({
        type: 'flight_delta',
        data: {
          deltas: [
            { icao24: 'aaa', latitude: 1.5 },
            { icao24: 'ddd', callsign: 'F4', latitude: 4.0, longitude: 4.0, altitude: 4000 },
          ],
          removed: ['bbb'],
          count: 3,
          timestamp: new Date().toISOString(),
        },
      })

      await waitFor(() => {
        const ids = result.current.flights.map(f => f.icao24).sort()
        expect(ids).toEqual(['aaa', 'ccc', 'ddd'])
      })

      const aaa = result.current.flights.find(f => f.icao24 === 'aaa')
      expect(aaa?.latitude).toBe(1.5)
      expect(aaa?.callsign).toBe('F1') // preserved
    })

    it('full update after delta replaces entire state', async () => {
      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      await waitFor(() => expect(mockWsInstances.length).toBe(1))

      // Initial
      mockWsInstances[0].simulateMessage({
        type: 'initial',
        data: {
          flights: [{ icao24: 'abc', callsign: 'UAL1', latitude: 37.0, longitude: -122.0, altitude: 5000 }],
          count: 1,
          timestamp: new Date().toISOString(),
        },
      })

      await waitFor(() => expect(result.current.flights.length).toBe(1))

      // Delta adds a flight
      mockWsInstances[0].simulateMessage({
        type: 'flight_delta',
        data: {
          deltas: [{ icao24: 'xyz', callsign: 'SWA5', latitude: 39.0, longitude: -120.0, altitude: 8000 }],
          removed: [],
          count: 2,
          timestamp: new Date().toISOString(),
        },
      })

      await waitFor(() => expect(result.current.flights.length).toBe(2))

      // Full flight_update replaces everything
      mockWsInstances[0].simulateMessage({
        type: 'flight_update',
        data: {
          flights: [{ icao24: 'new1', callsign: 'NEW', latitude: 40.0, longitude: -119.0, altitude: 9000 }],
          count: 1,
          timestamp: new Date().toISOString(),
        },
      })

      await waitFor(() => {
        expect(result.current.flights.length).toBe(1)
        expect(result.current.flights[0].icao24).toBe('new1')
      })
    })
  })

  describe('Network timeout (HTTP fallback)', () => {
    it('handles slow network gracefully', async () => {
      vi.stubGlobal('WebSocket', class {
        constructor() { throw new Error('WS unavailable'); }
      })

      server.use(
        http.get('/api/flights', async () => {
          await delay(2000)
          return HttpResponse.json({
            flights: mockFlights,
            count: mockFlights.length,
            timestamp: new Date().toISOString(),
            data_source: 'synthetic',
          })
        })
      )

      const { result } = renderHook(() => useFlights(), {
        wrapper: createWrapper(),
      })

      // Should still be loading after short time
      await new Promise((r) => setTimeout(r, 100))
      expect(result.current.isLoading).toBe(true)

      // Eventually should complete
      await waitFor(
        () => {
          expect(result.current.isLoading).toBe(false)
        },
        { timeout: 5000 }
      )
    })
  })
})
