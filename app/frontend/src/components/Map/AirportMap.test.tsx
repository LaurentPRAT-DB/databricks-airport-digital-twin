import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';

// ── Leaflet mocks ──────────────────────────────────────────────────
const mockSetView = vi.fn();
const mockFlyTo = vi.fn();
const mockGetCenter = vi.fn(() => ({ lat: 37.62, lng: -122.38 }));
const mockGetZoom = vi.fn(() => 13);
const mockMap = {
  setView: mockSetView,
  flyTo: mockFlyTo,
  getCenter: mockGetCenter,
  getZoom: mockGetZoom,
};

vi.mock('react-leaflet', () => {
  const LayersControlMock = ({ children }: { children: React.ReactNode }) => (
    <div data-testid="layers-control">{children}</div>
  );
  LayersControlMock.BaseLayer = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  LayersControlMock.Overlay = ({ children }: { children: React.ReactNode }) => <>{children}</>;

  return {
    MapContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="map-container">{children}</div>
    ),
    TileLayer: () => <div data-testid="tile-layer" />,
    LayersControl: LayersControlMock,
    useMap: () => mockMap,
    GeoJSON: () => null,
    CircleMarker: () => null,
    Tooltip: () => null,
    Polygon: () => null,
    Polyline: () => null,
    useMapEvents: () => null,
  };
});

// ── Airport config context mock ────────────────────────────────────
let mockCurrentAirport = 'KSFO';
const mockGetGates = vi.fn((): Array<{ id: string; ref?: string; name: string; geo: { latitude: number; longitude: number } }> => []);
const mockGetTerminals = vi.fn((): Array<{ id: string; name: string; geo: { latitude: number; longitude: number } }> => []);

vi.mock('../../context/AirportConfigContext', () => ({
  useAirportConfigContext: () => ({
    currentAirport: mockCurrentAirport,
    getGates: mockGetGates,
    getTerminals: mockGetTerminals,
    getOSMTaxiways: () => [],
    getAprons: () => [],
    getOSMRunways: () => [],
    getAirportCenter: () => ({ lat: 37.62, lon: -122.38 }),
    config: {},
    isLoading: false,
    error: null,
    switchProgress: null,
    refresh: vi.fn(),
    loadAirport: vi.fn(),
    importAIXM: vi.fn(),
    importOSM: vi.fn(),
    importIFC: vi.fn(),
    importFAA: vi.fn(),
  }),
}));

// ── Flight context mock ────────────────────────────────────────────
vi.mock('../../context/FlightContext', () => ({
  useFlightContext: () => ({
    flights: [],
    filteredFlights: [],
    hiddenPhases: new Set(),
    togglePhase: vi.fn(),
    setHiddenPhases: vi.fn(),
    selectedFlight: null,
    setSelectedFlight: vi.fn(),
    isLoading: false,
    error: null,
    lastUpdated: null,
  }),
}));

// ── Mock child components ──────────────────────────────────────────
vi.mock('./AirportOverlay', () => ({ default: () => null }));
vi.mock('./FlightMarker', () => ({ default: () => null }));
vi.mock('./TrajectoryLine', () => ({ default: () => null }));

import AirportMap from './AirportMap';

// SFO coordinates
const SFO_GATES = [
  { id: 'A1', ref: 'A1', name: 'Gate A1', geo: { latitude: 37.6155, longitude: -122.3817 } },
  { id: 'A2', ref: 'A2', name: 'Gate A2', geo: { latitude: 37.6160, longitude: -122.3820 } },
];

// LHR coordinates (~51.47, -0.46)
const LHR_GATES = [
  { id: 'B32', ref: 'B32', name: 'Gate B32', geo: { latitude: 51.4710, longitude: -0.4543 } },
  { id: 'B33', ref: 'B33', name: 'Gate B33', geo: { latitude: 51.4715, longitude: -0.4550 } },
];

// CDG coordinates (~49.01, 2.55)
const CDG_TERMINALS = [
  { id: 'T1', name: 'Terminal 1', geo: { latitude: 49.0097, longitude: 2.5479 } },
  { id: 'T2', name: 'Terminal 2', geo: { latitude: 49.0050, longitude: 2.5710 } },
];

describe('AirportMap — airport switch recentering', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCurrentAirport = 'KSFO';
    mockGetGates.mockReturnValue(SFO_GATES);
    mockGetTerminals.mockReturnValue([]);
  });

  it('calls flyTo with SFO center on initial render', () => {
    render(<AirportMap />);
    expect(mockFlyTo).toHaveBeenCalledTimes(1);
    const [center] = mockFlyTo.mock.calls[0];
    // SFO center should be near 37.6, -122.38
    expect(center[0]).toBeCloseTo(37.6157, 2);
    expect(center[1]).toBeCloseTo(-122.3818, 2);
  });

  it('recenters map to LHR when airport switches from KSFO to EGLL', () => {
    const { rerender } = render(<AirportMap />);
    mockFlyTo.mockClear();

    // Switch to LHR
    mockCurrentAirport = 'EGLL';
    mockGetGates.mockReturnValue(LHR_GATES);
    rerender(<AirportMap />);

    expect(mockFlyTo).toHaveBeenCalledTimes(1);
    const [center] = mockFlyTo.mock.calls[0];
    // LHR center should be near 51.47, -0.45
    expect(center[0]).toBeCloseTo(51.4712, 2);
    expect(center[1]).toBeCloseTo(-0.4546, 2);
  });

  it('does NOT stay on SFO coordinates after switching to a different airport', () => {
    const { rerender } = render(<AirportMap />);

    // Switch to LHR
    mockCurrentAirport = 'EGLL';
    mockGetGates.mockReturnValue(LHR_GATES);
    rerender(<AirportMap />);

    // Get the last flyTo call
    const lastCall = mockFlyTo.mock.calls[mockFlyTo.mock.calls.length - 1];
    const [center] = lastCall;
    // Must NOT be SFO coordinates
    expect(center[0]).not.toBeCloseTo(37.62, 0);
    expect(center[1]).not.toBeCloseTo(-122.38, 0);
    // Must be LHR coordinates
    expect(center[0]).toBeGreaterThan(51);
    expect(center[1]).toBeGreaterThan(-1);
  });

  it('recenters even when sharedViewport has old SFO coordinates', () => {
    const sfoViewport = {
      center: { lat: 37.62, lon: -122.38 },
      zoom: 14,
      bearing: 0,
    };

    const { rerender } = render(<AirportMap sharedViewport={sfoViewport} />);
    mockFlyTo.mockClear();
    mockSetView.mockClear();

    // Switch to LHR — sharedViewport still has SFO coords
    mockCurrentAirport = 'EGLL';
    mockGetGates.mockReturnValue(LHR_GATES);
    rerender(<AirportMap sharedViewport={sfoViewport} />);

    // Must use flyTo (not setView with old SFO coords)
    expect(mockFlyTo).toHaveBeenCalled();
    const [center] = mockFlyTo.mock.calls[0];
    expect(center[0]).toBeCloseTo(51.4712, 2);
  });

  it('uses sharedViewport when NOT switching airports', () => {
    const sfoViewport = {
      center: { lat: 37.63, lon: -122.39 },
      zoom: 15,
      bearing: 0,
    };

    render(<AirportMap sharedViewport={sfoViewport} />);

    // On initial render (no airport change), sharedViewport should be used
    expect(mockSetView).toHaveBeenCalledWith(
      [37.63, -122.39],
      15,
      { animate: false }
    );
  });

  it('supports switching through multiple airports sequentially', () => {
    const { rerender } = render(<AirportMap />);
    mockFlyTo.mockClear();

    // Switch to LHR
    mockCurrentAirport = 'EGLL';
    mockGetGates.mockReturnValue(LHR_GATES);
    mockGetTerminals.mockReturnValue([]);
    rerender(<AirportMap />);

    expect(mockFlyTo).toHaveBeenCalledTimes(1);
    let [center] = mockFlyTo.mock.calls[0];
    expect(center[0]).toBeCloseTo(51.4712, 2);
    mockFlyTo.mockClear();

    // Switch to CDG
    mockCurrentAirport = 'LFPG';
    mockGetGates.mockReturnValue([]);
    mockGetTerminals.mockReturnValue(CDG_TERMINALS);
    rerender(<AirportMap />);

    expect(mockFlyTo).toHaveBeenCalledTimes(1);
    [center] = mockFlyTo.mock.calls[0];
    // CDG center should be near 49.0, 2.56
    expect(center[0]).toBeCloseTo(49.0073, 2);
    expect(center[1]).toBeCloseTo(2.5594, 2);
  });

  it('handles airport with no gates or terminals gracefully', () => {
    const { rerender } = render(<AirportMap />);
    mockFlyTo.mockClear();

    // Switch to airport with no data
    mockCurrentAirport = 'XXXX';
    mockGetGates.mockReturnValue([]);
    mockGetTerminals.mockReturnValue([]);
    rerender(<AirportMap />);

    // Should not crash; flyTo should not be called (no center to compute)
    // The map just stays where it is
  });
});
