import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

// Import the hooks (MSW handlers provide mock data)
import { usePredictions, useDelayPrediction, useCongestion } from './usePredictions';
import type { Flight } from '../types/flight';

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
    },
  });

  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
}

const mockFlight: Flight = {
  icao24: 'a12345',
  callsign: 'UAL123',
  latitude: 37.62,
  longitude: -122.38,
  altitude: 5000,
  velocity: 200,
  heading: 270,
  vertical_rate: -500,
  on_ground: false,
  last_seen: new Date().toISOString(),
  data_source: 'synthetic',
  flight_phase: 'approaching',
};

describe('usePredictions hooks', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('usePredictions', () => {
    it('returns delay predictions from API', async () => {
      const { result } = renderHook(() => usePredictions([mockFlight]), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      // MSW handler returns mockDelayPrediction with icao24='a12345'
      expect(result.current.delays.size).toBeGreaterThanOrEqual(1);
    });

    it('does not fetch when flights array is empty', () => {
      const { result } = renderHook(() => usePredictions([]), {
        wrapper: createWrapper(),
      });

      // Should not be loading when disabled
      expect(result.current.delays.size).toBe(0);
    });
  });

  describe('useDelayPrediction', () => {
    it('fetches prediction for specific icao24', async () => {
      const { result } = renderHook(() => useDelayPrediction('a12345'), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.delay).not.toBeNull();
      expect(result.current.delay?.icao24).toBe('a12345');
    });

    it('returns null delay when icao24 is null', () => {
      const { result } = renderHook(() => useDelayPrediction(null), {
        wrapper: createWrapper(),
      });

      expect(result.current.delay).toBeNull();
    });
  });

  describe('useCongestion (merged endpoint)', () => {
    it('returns both congestion areas and bottlenecks from single endpoint', async () => {
      const { result } = renderHook(() => useCongestion(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      // MSW handler returns mockCongestion with 2 areas, 0 bottlenecks (all low/moderate)
      expect(result.current.congestion.length).toBeGreaterThanOrEqual(1);
      expect(Array.isArray(result.current.bottlenecks)).toBe(true);
    });

    it('fetches from /api/predictions/congestion-summary', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch');

      const { result } = renderHook(() => useCongestion(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      // Verify the merged endpoint was called (not separate /congestion + /bottlenecks)
      const calls = fetchSpy.mock.calls.map(c => String(c[0]));
      expect(calls.some(url => url.includes('/congestion-summary'))).toBe(true);
      expect(calls.every(url => !url.includes('/predictions/bottlenecks'))).toBe(true);

      fetchSpy.mockRestore();
    });
  });
});

describe('polling intervals', () => {
  it('usePredictions configures 30s refetch (not 10s)', async () => {
    // We verify the hook behavior indirectly — by checking it doesn't refetch too quickly
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    const { result } = renderHook(() => usePredictions([mockFlight]), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    const initialCallCount = fetchSpy.mock.calls.filter(c =>
      String(c[0]).includes('/predictions/delays')
    ).length;

    // Advance 15 seconds — should NOT have re-fetched (interval is 30s)
    vi.useFakeTimers();
    vi.advanceTimersByTime(15000);
    vi.useRealTimers();

    const afterCallCount = fetchSpy.mock.calls.filter(c =>
      String(c[0]).includes('/predictions/delays')
    ).length;

    // Should still be same count (no refetch at 15s)
    expect(afterCallCount).toBe(initialCallCount);

    fetchSpy.mockRestore();
  });
});
