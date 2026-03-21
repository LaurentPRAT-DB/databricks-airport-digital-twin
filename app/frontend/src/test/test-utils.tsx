import React, { ReactElement } from 'react'
import { render, RenderOptions, RenderResult } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { FlightProvider } from '../context/FlightContext'
import { AirportConfigProvider } from '../context/AirportConfigContext'

// Create a new QueryClient for each test
function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false, // Don't retry in tests
        gcTime: 0, // Don't cache in tests
        staleTime: 0,
      },
    },
  })
}

interface AllTheProvidersProps {
  children: React.ReactNode
}

function AllTheProviders({ children }: AllTheProvidersProps) {
  const queryClient = createTestQueryClient()

  return (
    <QueryClientProvider client={queryClient}>
      <AirportConfigProvider>
        <FlightProvider>{children}</FlightProvider>
      </AirportConfigProvider>
    </QueryClientProvider>
  )
}

// Only QueryClient provider (no FlightProvider)
function QueryOnlyProvider({ children }: AllTheProvidersProps) {
  const queryClient = createTestQueryClient()
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

// Custom render function that wraps with all providers
function customRender(
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'>
): RenderResult {
  return render(ui, { wrapper: AllTheProviders, ...options })
}

// Render with only QueryClient (useful for testing hooks)
function renderWithQuery(
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'>
): RenderResult {
  return render(ui, { wrapper: QueryOnlyProvider, ...options })
}

// Performance utilities
export const measureRenderTime = async (
  renderFn: () => RenderResult
): Promise<{ result: RenderResult; time: number }> => {
  const start = performance.now()
  const result = renderFn()
  const time = performance.now() - start
  return { result, time }
}

export const PERFORMANCE_THRESHOLDS = {
  initialRender: 100, // ms
  rerender: 50, // ms
  interaction: 200, // ms
  heavyComponent: 500, // ms (for 3D, maps)
  apiResponse: 1000, // ms
}

// Mock flight factory for tests
export function createMockFlight(overrides = {}) {
  return {
    icao24: 'test123',
    callsign: 'TEST123',
    latitude: 37.6213,
    longitude: -122.379,
    altitude: 5000,
    velocity: 200,
    heading: 270,
    vertical_rate: 0,
    on_ground: false,
    last_seen: Date.now(),
    data_source: 'synthetic' as const,
    flight_phase: 'enroute' as const,
    aircraft_type: 'B737',
    ...overrides,
  }
}

// Wait for loading states to resolve
export const waitForLoadingToFinish = async (
  findByText: (text: string | RegExp) => Promise<HTMLElement>
) => {
  try {
    await findByText(/loading/i)
  } catch {
    // Loading already finished
  }
}

// Re-export everything from React Testing Library
export * from '@testing-library/react'
export { customRender as render, renderWithQuery }
