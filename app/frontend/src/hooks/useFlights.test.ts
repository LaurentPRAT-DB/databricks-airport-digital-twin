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

    it('ignores airport_switch_progress messages', async () => {
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
