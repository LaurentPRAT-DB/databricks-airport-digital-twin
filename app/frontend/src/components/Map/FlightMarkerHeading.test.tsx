import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, act } from '@testing-library/react';
import React from 'react';
import type { Flight } from '../../types/flight';

// ── Mock react-leaflet ─────────────────────────────────────────
vi.mock('react-leaflet', () => ({
  Marker: ({ children, position }: { children: React.ReactNode; position: [number, number] }) => (
    <div data-testid="marker" data-lat={position[0]} data-lng={position[1]}>
      {children}
    </div>
  ),
  Tooltip: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="tooltip">{children}</div>
  ),
}));

// ── Mock leaflet — capture divIcon rotation ───────────────────
let lastRotation = 0;
vi.mock('leaflet', () => ({
  default: {
    divIcon: (opts: { html: string }) => {
      const match = opts.html.match(/rotate\(([\d.]+)deg\)/);
      if (match) lastRotation = parseFloat(match[1]);
      return { options: opts };
    },
  },
}));

// ── Mock flight context ────────────────────────────────────────
vi.mock('../../context/FlightContext', () => ({
  useFlightContext: () => ({
    selectedFlight: null,
    setSelectedFlight: vi.fn(),
    flights: [],
    isLoading: false,
    error: null,
    lastUpdated: null,
  }),
}));

import FlightMarker, { computeBearing } from './FlightMarker';

function createFlight(overrides: Partial<Flight> = {}): Flight {
  return {
    icao24: 'abc123',
    callsign: 'UAL456',
    latitude: 37.6200,
    longitude: -122.3800,
    altitude: 0,
    velocity: 20,
    heading: 90,
    vertical_rate: 0,
    on_ground: true,
    last_seen: new Date().toISOString(),
    data_source: 'synthetic',
    flight_phase: 'taxi_to_runway',
    ...overrides,
  };
}

describe('FlightMarker heading alignment', () => {
  beforeEach(() => {
    lastRotation = 0;
  });

  describe('computeBearing', () => {
    it('returns ~0° for due north movement', () => {
      const bearing = computeBearing(37.0, -122.0, 37.1, -122.0);
      expect(bearing).toBeCloseTo(0, 0);
    });

    it('returns ~90° for due east movement', () => {
      const bearing = computeBearing(37.0, -122.0, 37.0, -121.9);
      expect(bearing).toBeCloseTo(90, 0);
    });

    it('returns ~180° for due south movement', () => {
      const bearing = computeBearing(37.1, -122.0, 37.0, -122.0);
      expect(bearing).toBeCloseTo(180, 0);
    });

    it('returns ~270° for due west movement', () => {
      const bearing = computeBearing(37.0, -121.9, 37.0, -122.0);
      expect(bearing).toBeCloseTo(270, 0);
    });
  });

  describe('silhouette aligns with movement direction', () => {
    it('uses reported heading on first render (no movement yet)', () => {
      render(<FlightMarker flight={createFlight({ heading: 45 })} />);
      expect(lastRotation).toBeCloseTo(45, 0);
    });

    it('rotates to match northward movement', () => {
      const startLat = 37.6200;
      const startLon = -122.3800;
      const endLat = 37.6210; // moved north
      const endLon = -122.3800;

      const { rerender } = render(
        <FlightMarker flight={createFlight({ latitude: startLat, longitude: startLon, heading: 90 })} />
      );

      act(() => {
        rerender(
          <FlightMarker flight={createFlight({ latitude: endLat, longitude: endLon, heading: 90 })} />
        );
      });

      // Should rotate toward ~0° (north) based on movement, not 90° from heading
      expect(lastRotation).toBeCloseTo(0, 0);
    });

    it('rotates to match eastward movement', () => {
      const startLat = 37.6200;
      const startLon = -122.3800;
      const endLat = 37.6200;
      const endLon = -122.3790; // moved east

      const { rerender } = render(
        <FlightMarker flight={createFlight({ latitude: startLat, longitude: startLon, heading: 0 })} />
      );

      act(() => {
        rerender(
          <FlightMarker flight={createFlight({ latitude: endLat, longitude: endLon, heading: 0 })} />
        );
      });

      expect(lastRotation).toBeCloseTo(90, 0);
    });

    it('rotates to match southwestward movement', () => {
      const startLat = 37.6200;
      const startLon = -122.3800;
      const endLat = 37.6190; // moved south
      const endLon = -122.3810; // moved west

      const { rerender } = render(
        <FlightMarker flight={createFlight({ latitude: startLat, longitude: startLon, heading: 0 })} />
      );

      act(() => {
        rerender(
          <FlightMarker flight={createFlight({ latitude: endLat, longitude: endLon, heading: 0 })} />
        );
      });

      // Southwest is ~225°
      expect(lastRotation).toBeGreaterThan(200);
      expect(lastRotation).toBeLessThan(250);
    });

    it('keeps previous bearing when movement is below threshold', () => {
      const startLat = 37.6200;
      const startLon = -122.3800;

      const { rerender } = render(
        <FlightMarker flight={createFlight({ latitude: startLat, longitude: startLon, heading: 45 })} />
      );

      // Move east significantly
      act(() => {
        rerender(
          <FlightMarker flight={createFlight({ latitude: startLat, longitude: startLon + 0.001, heading: 45 })} />
        );
      });
      expect(lastRotation).toBeCloseTo(90, 0);

      // Tiny jitter — should keep the ~90° bearing, not revert to heading 45
      act(() => {
        rerender(
          <FlightMarker flight={createFlight({ latitude: startLat + 0.0000001, longitude: startLon + 0.001, heading: 45 })} />
        );
      });
      expect(lastRotation).toBeCloseTo(90, 0);
    });

    it('updates bearing through a turn sequence', () => {
      const { rerender } = render(
        <FlightMarker flight={createFlight({ latitude: 37.6200, longitude: -122.3800, heading: 0 })} />
      );

      // Move north
      act(() => {
        rerender(
          <FlightMarker flight={createFlight({ latitude: 37.6210, longitude: -122.3800, heading: 0 })} />
        );
      });
      expect(lastRotation).toBeCloseTo(0, 0);

      // Turn east
      act(() => {
        rerender(
          <FlightMarker flight={createFlight({ latitude: 37.6210, longitude: -122.3790, heading: 0 })} />
        );
      });
      expect(lastRotation).toBeCloseTo(90, 0);

      // Turn south
      act(() => {
        rerender(
          <FlightMarker flight={createFlight({ latitude: 37.6200, longitude: -122.3790, heading: 0 })} />
        );
      });
      expect(lastRotation).toBeCloseTo(180, 0);
    });
  });
});
