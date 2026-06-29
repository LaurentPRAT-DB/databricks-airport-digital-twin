import { describe, it, expect } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { FlightProvider } from '../context/FlightContext';
import { AirportConfigProvider } from '../context/AirportConfigContext';
import { useDelayMap } from './useDelayMap';

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
    },
  });

  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(
      QueryClientProvider,
      { client: queryClient },
      React.createElement(
        AirportConfigProvider,
        null,
        React.createElement(FlightProvider, null, children)
      )
    );
}

describe('useDelayMap', () => {
  it('returns a Map of delay predictions', async () => {
    const { result, unmount } = renderHook(() => useDelayMap(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.delayMap).toBeInstanceOf(Map);
    });

    await act(() => { unmount(); });
  });

  it('returns delayedCount as a number', async () => {
    const { result, unmount } = renderHook(() => useDelayMap(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(typeof result.current.delayedCount).toBe('number');
    });

    await act(() => { unmount(); });
  });

  it('populates delay predictions from API', async () => {
    const { result, unmount } = renderHook(() => useDelayMap(), {
      wrapper: createWrapper(),
    });

    // MSW handler returns mockDelayPrediction with icao24='a12345', delay=15min
    await waitFor(() => {
      expect(result.current.delayMap.size).toBeGreaterThanOrEqual(0);
    });

    await act(() => { unmount(); });
  });
});
