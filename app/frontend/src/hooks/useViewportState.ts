/**
 * Shared viewport state for 2D↔3D view synchronization.
 *
 * Stores the logical viewport (center lat/lon, zoom level, bearing)
 * so that switching between 2D and 3D views preserves the user's
 * position and zoom area.
 */

import { useState, useCallback, useRef } from 'react';

export interface SharedViewport {
  center: { lat: number; lon: number };
  zoom: number;    // Leaflet zoom level (0-20)
  bearing: number; // rotation angle in degrees (0 for 2D, free in 3D)
}

export interface UseViewportStateReturn {
  /** Current shared viewport (null if never set) */
  viewport: SharedViewport | null;
  /** Save viewport state (called on view unmount, null to reset) */
  setViewport: (vp: SharedViewport | null) => void;
  /** Source of last viewport update ('2d' | '3d' | null) */
  lastSource: '2d' | '3d' | null;
  /** Record which view last saved the viewport */
  setLastSource: (source: '2d' | '3d') => void;
}

/**
 * Hook that holds shared viewport state between 2D and 3D views.
 * Lives in App.tsx so both views can read/write it.
 */
export function useViewportState(): UseViewportStateReturn {
  const [viewport, setViewportState] = useState<SharedViewport | null>(null);
  const lastSourceRef = useRef<'2d' | '3d' | null>(null);

  const setViewport = useCallback((vp: SharedViewport | null) => {
    setViewportState(vp);
  }, []);

  const setLastSource = useCallback((source: '2d' | '3d') => {
    lastSourceRef.current = source;
  }, []);

  return {
    viewport,
    setViewport,
    lastSource: lastSourceRef.current,
    setLastSource,
  };
}
