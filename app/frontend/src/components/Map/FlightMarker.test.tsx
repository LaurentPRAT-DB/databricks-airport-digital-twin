import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';
import type { Flight } from '../../types/flight';

// ── Mock react-map-gl/maplibre ─────────────────────────────────────
vi.mock('react-map-gl/maplibre', () => ({
  Marker: ({ children, longitude, latitude, onClick }: { children: React.ReactNode; longitude: number; latitude: number; onClick?: () => void }) => (
    <div data-testid="marker" data-lat={latitude} data-lng={longitude} onClick={onClick}>
      {children}
    </div>
  ),
  Popup: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="popup">{children}</div>
  ),
}));

// ── Mock flight context ────────────────────────────────────────
const mockSetSelectedFlight = vi.fn();
vi.mock('../../context/FlightContext', () => ({
  useFlightContext: () => ({
    selectedFlight: null,
    setSelectedFlight: mockSetSelectedFlight,
    flights: [],
    isLoading: false,
    error: null,
    lastUpdated: null,
  }),
}));

import FlightMarker, { createAirplaneIconHtml } from './FlightMarker';

function createFlight(overrides: Partial<Flight> = {}): Flight {
  return {
    icao24: 'abc123',
    callsign: 'UAL456',
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
    ...overrides,
  };
}

describe('FlightMarker', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── LatLng guard tests ───────────────────────────────────────
  describe('invalid coordinate guard', () => {
    it('returns null for null latitude', () => {
      const { container } = render(
        <FlightMarker flight={createFlight({ latitude: null as unknown as number })} />
      );
      expect(container.querySelector('[data-testid="marker"]')).toBeNull();
    });

    it('returns null for null longitude', () => {
      const { container } = render(
        <FlightMarker flight={createFlight({ longitude: null as unknown as number })} />
      );
      expect(container.querySelector('[data-testid="marker"]')).toBeNull();
    });

    it('returns null for NaN latitude', () => {
      const { container } = render(
        <FlightMarker flight={createFlight({ latitude: NaN })} />
      );
      expect(container.querySelector('[data-testid="marker"]')).toBeNull();
    });

    it('returns null for NaN longitude', () => {
      const { container } = render(
        <FlightMarker flight={createFlight({ longitude: NaN })} />
      );
      expect(container.querySelector('[data-testid="marker"]')).toBeNull();
    });

    it('renders marker for valid coordinates', () => {
      const { container } = render(<FlightMarker flight={createFlight()} />);
      expect(container.querySelector('[data-testid="marker"]')).not.toBeNull();
    });
  });

  // ── ARIA label tests ─────────────────────────────────────────
  describe('ARIA labels on SVG', () => {
    it('includes aria-label with callsign in SVG', () => {
      const html = createAirplaneIconHtml(270, 'approaching', false, 30, 'DAL789', 'abc123', null, undefined);
      expect(html).toContain('aria-label="Flight DAL789"');
    });

    it('falls back to icao24 when callsign is null', () => {
      const html = createAirplaneIconHtml(270, 'approaching', false, 30, null, 'xyz999', null, undefined);
      expect(html).toContain('aria-label="Flight xyz999"');
    });

    it('includes role="img" on SVG', () => {
      const html = createAirplaneIconHtml(270, 'approaching', false, 30, 'UAL456', 'abc123', null, undefined);
      expect(html).toContain('role="img"');
    });
  });

  // ── Gate label tests ─────────────────────────────────────────
  describe('gate label display', () => {
    it('shows gate label for ground phase with assigned gate', () => {
      const html = createAirplaneIconHtml(0, 'parked', false, 30, 'UAL456', 'abc123', 'A5', undefined);
      expect(html).toContain('gate-label');
      expect(html).toContain('A5');
    });

    it('does not show gate label for non-ground phase', () => {
      const html = createAirplaneIconHtml(0, 'enroute', false, 30, 'UAL456', 'abc123', 'A5', undefined);
      expect(html).not.toContain('gate-label');
    });
  });
});
