import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, act } from '@testing-library/react';
import React from 'react';
import type { Flight } from '../../types/flight';

// ── Mock react-map-gl/maplibre — capture rendered HTML for rotation ───
let lastRenderedHtml = '';
vi.mock('react-map-gl/maplibre', () => ({
  Marker: ({ children, longitude, latitude }: { children: React.ReactNode; longitude: number; latitude: number }) => (
    <div data-testid="marker" data-lat={latitude} data-lng={longitude}>
      {children}
    </div>
  ),
  Popup: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="popup">{children}</div>
  ),
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

function getRotationFromContainer(container: HTMLElement): number {
  const markerDiv = container.querySelector('.flight-marker');
  if (!markerDiv) return 0;
  const html = markerDiv.innerHTML;
  const match = html.match(/rotate\(([\d.]+)deg\)/);
  return match ? parseFloat(match[1]) : 0;
}

describe('FlightMarker heading alignment', () => {
  beforeEach(() => {
    lastRenderedHtml = '';
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
      const { container } = render(<FlightMarker flight={createFlight({ heading: 45 })} />);
      expect(getRotationFromContainer(container)).toBeCloseTo(45, 0);
    });

    it('rotates to match northward movement', () => {
      const startLat = 37.6200;
      const startLon = -122.3800;
      const endLat = 37.6210;
      const endLon = -122.3800;

      const { container, rerender } = render(
        <FlightMarker flight={createFlight({ latitude: startLat, longitude: startLon, heading: 90 })} />
      );

      act(() => {
        rerender(
          <FlightMarker flight={createFlight({ latitude: endLat, longitude: endLon, heading: 90 })} />
        );
      });

      expect(getRotationFromContainer(container)).toBeCloseTo(0, 0);
    });

    it('rotates to match eastward movement', () => {
      const startLat = 37.6200;
      const startLon = -122.3800;
      const endLat = 37.6200;
      const endLon = -122.3790;

      const { container, rerender } = render(
        <FlightMarker flight={createFlight({ latitude: startLat, longitude: startLon, heading: 0 })} />
      );

      act(() => {
        rerender(
          <FlightMarker flight={createFlight({ latitude: endLat, longitude: endLon, heading: 0 })} />
        );
      });

      expect(getRotationFromContainer(container)).toBeCloseTo(90, 0);
    });

    it('rotates to match southwestward movement', () => {
      const startLat = 37.6200;
      const startLon = -122.3800;
      const endLat = 37.6190;
      const endLon = -122.3810;

      const { container, rerender } = render(
        <FlightMarker flight={createFlight({ latitude: startLat, longitude: startLon, heading: 0 })} />
      );

      act(() => {
        rerender(
          <FlightMarker flight={createFlight({ latitude: endLat, longitude: endLon, heading: 0 })} />
        );
      });

      const rotation = getRotationFromContainer(container);
      expect(rotation).toBeGreaterThan(200);
      expect(rotation).toBeLessThan(250);
    });

    it('keeps previous bearing when movement is below threshold', () => {
      const startLat = 37.6200;
      const startLon = -122.3800;

      const { container, rerender } = render(
        <FlightMarker flight={createFlight({ latitude: startLat, longitude: startLon, heading: 45 })} />
      );

      act(() => {
        rerender(
          <FlightMarker flight={createFlight({ latitude: startLat, longitude: startLon + 0.001, heading: 45 })} />
        );
      });
      expect(getRotationFromContainer(container)).toBeCloseTo(90, 0);

      act(() => {
        rerender(
          <FlightMarker flight={createFlight({ latitude: startLat + 0.0000001, longitude: startLon + 0.001, heading: 45 })} />
        );
      });
      expect(getRotationFromContainer(container)).toBeCloseTo(90, 0);
    });

    it('updates bearing through a turn sequence', () => {
      const { container, rerender } = render(
        <FlightMarker flight={createFlight({ latitude: 37.6200, longitude: -122.3800, heading: 0 })} />
      );

      act(() => {
        rerender(
          <FlightMarker flight={createFlight({ latitude: 37.6210, longitude: -122.3800, heading: 0 })} />
        );
      });
      expect(getRotationFromContainer(container)).toBeCloseTo(0, 0);

      act(() => {
        rerender(
          <FlightMarker flight={createFlight({ latitude: 37.6210, longitude: -122.3790, heading: 0 })} />
        );
      });
      expect(getRotationFromContainer(container)).toBeCloseTo(90, 0);

      act(() => {
        rerender(
          <FlightMarker flight={createFlight({ latitude: 37.6200, longitude: -122.3790, heading: 0 })} />
        );
      });
      expect(getRotationFromContainer(container)).toBeCloseTo(180, 0);
    });
  });
});
