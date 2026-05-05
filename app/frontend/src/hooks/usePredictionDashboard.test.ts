import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { usePredictionDashboard } from './usePredictionDashboard';

const mockDashboard = {
  kpi_cards: [
    { label: 'On-Time', value: '82%', color: 'green' },
    { label: 'Avg Delay', value: '8.2m', color: 'orange' },
  ],
  congestion_areas: [
    { area_id: 'RWY28L', area_type: 'runway', level: 'high', flight_count: 12, capacity: 15, wait_minutes: 4 },
  ],
  delay_table: [
    { icao24: 'abc001', callsign: 'UAL100', delay_minutes: 12, confidence: 0.87, category: 'moderate' },
  ],
  total_flights: 45,
};

function createWrapper(opts?: { retry?: number | false }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: opts?.retry ?? false, gcTime: 0 } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
}

describe('usePredictionDashboard', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns loading state initially, then resolves with data', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify(mockDashboard), { status: 200 }))
    ) as unknown as typeof fetch;

    const { result } = renderHook(() => usePredictionDashboard(true), { wrapper: createWrapper() });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.dashboard).toBeNull();

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.dashboard).toEqual(mockDashboard);
    expect(result.current.error).toBeNull();
  });

  it('returns error when fetch fails', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(new Response('Server Error', { status: 500 }))
    ) as unknown as typeof fetch;

    // Hook has retry: 2 internally, so we need to wait for all retries to exhaust
    const { result } = renderHook(() => usePredictionDashboard(true), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.error).not.toBeNull();
    }, { timeout: 15000 });

    expect(result.current.error!.message).toBe('Failed to fetch predictions dashboard');
    expect(result.current.dashboard).toBeNull();
  }, 20000);

  it('does not fetch when enabled=false', async () => {
    const fetchFn = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify(mockDashboard), { status: 200 }))
    );
    globalThis.fetch = fetchFn as unknown as typeof fetch;

    const { result } = renderHook(() => usePredictionDashboard(false), { wrapper: createWrapper() });

    // Give React Query a chance to run
    await new Promise((r) => setTimeout(r, 50));

    expect(fetchFn).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(false);
    expect(result.current.dashboard).toBeNull();
  });

  it('retries on failure up to 2 times', async () => {
    let callCount = 0;
    globalThis.fetch = vi.fn(() => {
      callCount++;
      if (callCount <= 2) {
        return Promise.resolve(new Response('Error', { status: 500 }));
      }
      return Promise.resolve(new Response(JSON.stringify(mockDashboard), { status: 200 }));
    }) as unknown as typeof fetch;

    const { result } = renderHook(() => usePredictionDashboard(true), {
      wrapper: createWrapper({ retry: 2 }),
    });

    await waitFor(() => {
      expect(result.current.dashboard).toEqual(mockDashboard);
    }, { timeout: 15000 });

    expect(callCount).toBe(3);
  }, 20000);
});
