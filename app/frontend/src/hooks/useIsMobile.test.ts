import { renderHook } from '@testing-library/react';
import { useIsMobile } from './useIsMobile';

describe('useIsMobile', () => {
  let matchesValue: boolean;

  beforeEach(() => {
    matchesValue = false;

    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: (query: string) => ({
        matches: matchesValue,
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }),
    });

    Object.defineProperty(navigator, 'maxTouchPoints', {
      writable: true,
      value: 0,
    });
  });

  it('returns false for desktop (no touch, wide viewport)', () => {
    matchesValue = false;
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);
  });

  it('returns true when viewport is narrow', () => {
    matchesValue = true;
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);
  });

  it('returns true for touch device with coarse pointer', () => {
    Object.defineProperty(navigator, 'maxTouchPoints', {
      writable: true,
      value: 5,
    });
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: (query: string) => ({
        matches: query === '(pointer: coarse)',
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }),
    });
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);
  });

  it('stays stable after init (no orientation flip)', () => {
    matchesValue = false;
    const { result, rerender } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);
    matchesValue = true;
    rerender();
    expect(result.current).toBe(false);
  });
});
