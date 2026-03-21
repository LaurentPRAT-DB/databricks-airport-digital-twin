import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
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

// ── Mock leaflet ───────────────────────────────────────────────
let lastDivIconHtml = '';
vi.mock('leaflet', () => ({
  default: {
    divIcon: (opts: { html: string }) => {
      lastDivIconHtml = opts.html;
      return { options: opts };
    },
  },
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

import FlightMarker from './FlightMarker';

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
    lastDivIconHtml = '';
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
      render(<FlightMarker flight={createFlight({ callsign: 'DAL789' })} />);
      expect(lastDivIconHtml).toContain('aria-label="Flight DAL789"');
    });

    it('falls back to icao24 when callsign is null', () => {
      render(<FlightMarker flight={createFlight({ callsign: null, icao24: 'xyz999' })} />);
      expect(lastDivIconHtml).toContain('aria-label="Flight xyz999"');
    });

    it('includes role="img" on SVG', () => {
      render(<FlightMarker flight={createFlight()} />);
      expect(lastDivIconHtml).toContain('role="img"');
    });
  });

  // ── Gate label tests ─────────────────────────────────────────
  describe('gate label display', () => {
    it('shows gate label for ground phase with assigned gate', () => {
      render(
        <FlightMarker
          flight={createFlight({ flight_phase: 'parked', assigned_gate: 'A5' })}
        />
      );
      expect(lastDivIconHtml).toContain('gate-label');
      expect(lastDivIconHtml).toContain('A5');
    });

    it('does not show gate label for non-ground phase', () => {
      render(
        <FlightMarker
          flight={createFlight({ flight_phase: 'enroute', assigned_gate: 'A5' })}
        />
      );
      expect(lastDivIconHtml).not.toContain('gate-label');
    });
  });
});
