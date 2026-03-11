import '@testing-library/jest-dom'
import { cleanup } from '@testing-library/react'
import { afterEach, vi, beforeAll, afterAll, expect } from 'vitest'
import { server } from './mocks/server'

// Start MSW server before all tests
beforeAll(() => server.listen({ onUnhandledRequest: 'warn' }))

// Reset handlers after each test
afterEach(() => {
  cleanup()
  server.resetHandlers()
})

// Close server after all tests
afterAll(() => server.close())

// Mock matchMedia for components that use it
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// Mock ResizeObserver for components that use it (like Map components)
class MockResizeObserver {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(globalThis as any).ResizeObserver = MockResizeObserver

// Mock IntersectionObserver
// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(globalThis as any).IntersectionObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}))

// Note: do NOT stub fetch globally here — MSW needs the real fetch to intercept.
// Tests that need a raw fetch mock should set it up locally (see aircraftModels.test.ts).

// Performance measurement utilities
export const measureRenderTime = async (callback: () => Promise<void>): Promise<number> => {
  const start = performance.now()
  await callback()
  return performance.now() - start
}

// Performance threshold helper
export const expectRenderTimeUnder = (time: number, threshold: number, component: string) => {
  if (time > threshold) {
    console.warn(`Performance warning: ${component} took ${time.toFixed(2)}ms (threshold: ${threshold}ms)`)
  }
  expect(time).toBeLessThan(threshold * 2) // Allow 2x threshold as hard limit
}
