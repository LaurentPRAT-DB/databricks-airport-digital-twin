import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useViewportState, SharedViewport } from './useViewportState';

const sfoViewport: SharedViewport = {
  center: { lat: 37.6213, lon: -122.379 },
  zoom: 13,
  bearing: 0,
};

const zoomedViewport: SharedViewport = {
  center: { lat: 37.625, lon: -122.381 },
  zoom: 16,
  bearing: 45,
};

describe('useViewportState', () => {
  describe('Initial state', () => {
    it('starts with null viewport', () => {
      const { result } = renderHook(() => useViewportState());
      expect(result.current.viewport).toBeNull();
    });

    it('starts with null lastSource', () => {
      const { result } = renderHook(() => useViewportState());
      expect(result.current.lastSource).toBeNull();
    });
  });

  describe('setViewport', () => {
    it('stores a viewport', () => {
      const { result } = renderHook(() => useViewportState());
      act(() => {
        result.current.setViewport(sfoViewport);
      });
      expect(result.current.viewport).toEqual(sfoViewport);
    });

    it('replaces previous viewport', () => {
      const { result } = renderHook(() => useViewportState());
      act(() => {
        result.current.setViewport(sfoViewport);
      });
      act(() => {
        result.current.setViewport(zoomedViewport);
      });
      expect(result.current.viewport).toEqual(zoomedViewport);
    });

    it('preserves all viewport fields', () => {
      const { result } = renderHook(() => useViewportState());
      act(() => {
        result.current.setViewport(zoomedViewport);
      });
      expect(result.current.viewport?.center.lat).toBe(37.625);
      expect(result.current.viewport?.center.lon).toBe(-122.381);
      expect(result.current.viewport?.zoom).toBe(16);
      expect(result.current.viewport?.bearing).toBe(45);
    });
  });

  describe('setLastSource', () => {
    it('records 2d source (ref-based, visible after viewport update triggers re-render)', () => {
      const { result } = renderHook(() => useViewportState());
      act(() => {
        result.current.setLastSource('2d');
        // Trigger re-render by also setting viewport
        result.current.setViewport(sfoViewport);
      });
      expect(result.current.lastSource).toBe('2d');
    });

    it('records 3d source', () => {
      const { result } = renderHook(() => useViewportState());
      act(() => {
        result.current.setLastSource('3d');
        result.current.setViewport(sfoViewport);
      });
      expect(result.current.lastSource).toBe('3d');
    });

    it('can be overwritten', () => {
      const { result } = renderHook(() => useViewportState());
      act(() => {
        result.current.setLastSource('2d');
        result.current.setViewport(sfoViewport);
      });
      act(() => {
        result.current.setLastSource('3d');
        result.current.setViewport(zoomedViewport);
      });
      expect(result.current.lastSource).toBe('3d');
    });
  });

  describe('Callback identity stability', () => {
    it('setViewport is referentially stable', () => {
      const { result, rerender } = renderHook(() => useViewportState());
      const firstRef = result.current.setViewport;
      rerender();
      expect(result.current.setViewport).toBe(firstRef);
    });

    it('setLastSource is referentially stable', () => {
      const { result, rerender } = renderHook(() => useViewportState());
      const firstRef = result.current.setLastSource;
      rerender();
      expect(result.current.setLastSource).toBe(firstRef);
    });
  });

  describe('Edge cases', () => {
    it('handles extreme zoom values', () => {
      const { result } = renderHook(() => useViewportState());
      act(() => {
        result.current.setViewport({ center: { lat: 0, lon: 0 }, zoom: 0, bearing: 0 });
      });
      expect(result.current.viewport?.zoom).toBe(0);

      act(() => {
        result.current.setViewport({ center: { lat: 0, lon: 0 }, zoom: 20, bearing: 0 });
      });
      expect(result.current.viewport?.zoom).toBe(20);
    });

    it('handles negative bearing', () => {
      const { result } = renderHook(() => useViewportState());
      act(() => {
        result.current.setViewport({ center: { lat: 0, lon: 0 }, zoom: 13, bearing: -90 });
      });
      expect(result.current.viewport?.bearing).toBe(-90);
    });

    it('handles 360 bearing', () => {
      const { result } = renderHook(() => useViewportState());
      act(() => {
        result.current.setViewport({ center: { lat: 0, lon: 0 }, zoom: 13, bearing: 360 });
      });
      expect(result.current.viewport?.bearing).toBe(360);
    });

    it('handles polar coordinates', () => {
      const { result } = renderHook(() => useViewportState());
      act(() => {
        result.current.setViewport({ center: { lat: 90, lon: 180 }, zoom: 5, bearing: 0 });
      });
      expect(result.current.viewport?.center.lat).toBe(90);
      expect(result.current.viewport?.center.lon).toBe(180);
    });
  });
});
