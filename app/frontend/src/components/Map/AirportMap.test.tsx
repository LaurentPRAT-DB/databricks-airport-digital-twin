import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';

// ── MapLibre mocks ──────────────────────────────────────────────────
const mockFitBounds = vi.fn();
const mockFlyTo = vi.fn();
const mockJumpTo = vi.fn();
const mockGetCenter = vi.fn(() => ({ lat: 37.62, lng: -122.38 }));
const mockGetZoom = vi.fn(() => 13);
const mockGetMap = vi.fn(() => ({ style: { map: {} } }));
const mockOn = vi.fn();
const mockOff = vi.fn();

const mockMapRef = {
  fitBounds: mockFitBounds,
  flyTo: mockFlyTo,
  jumpTo: mockJumpTo,
  getCenter: mockGetCenter,
  getZoom: mockGetZoom,
  getMap: mockGetMap,
  on: mockOn,
  off: mockOff,
  panTo: vi.fn(),
};

vi.mock('react-map-gl/maplibre', () => {
  const MapMock = ({ children }: { children: React.ReactNode }) => (
    <div data-testid="map-container">{children}</div>
  );

  return {
    default: MapMock,
    Source: ({ children }: { children?: React.ReactNode }) => <div data-testid="source">{children}</div>,
    Layer: () => <div data-testid="layer" />,
    Marker: () => null,
    Popup: () => null,
    useMap: () => ({ current: mockMapRef }),
  };
});

vi.mock('maplibre-gl/dist/maplibre-gl.css', () => ({}));

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

  it('calls fitBounds with SFO bounds on initial render', () => {
    render(<AirportMap />);
    expect(mockFitBounds).toHaveBeenCalledTimes(1);
    const [bounds] = mockFitBounds.mock.calls[0];
    // MapLibre bounds: [[swLng, swLat], [neLng, neLat]]
    expect(bounds[0][1]).toBeLessThan(37.62);  // south bound lat
    expect(bounds[1][1]).toBeGreaterThan(37.60);  // north bound lat
    expect(bounds[0][0]).toBeLessThan(-122.37);  // west bound lng
  });

  it('recenters map to LHR when airport switches from KSFO to EGLL', () => {
    const { rerender } = render(<AirportMap />);
    mockFitBounds.mockClear();

    mockCurrentAirport = 'EGLL';
    mockGetGates.mockReturnValue(LHR_GATES);
    rerender(<AirportMap />);

    expect(mockFitBounds).toHaveBeenCalledTimes(1);
    const [bounds] = mockFitBounds.mock.calls[0];
    // LHR bounds lat > 51
    expect(bounds[0][1]).toBeGreaterThan(51.0);
    expect(bounds[1][1]).toBeGreaterThan(51.0);
  });

  it('does NOT stay on SFO coordinates after switching to a different airport', () => {
    const { rerender } = render(<AirportMap />);

    mockCurrentAirport = 'EGLL';
    mockGetGates.mockReturnValue(LHR_GATES);
    rerender(<AirportMap />);

    const lastCall = mockFitBounds.mock.calls[mockFitBounds.mock.calls.length - 1];
    const [bounds] = lastCall;
    expect(bounds[0][1]).not.toBeCloseTo(37.62, 0);
    expect(bounds[0][1]).toBeGreaterThan(51);
  });

  it('recenters even when sharedViewport has old SFO coordinates', () => {
    const sfoViewport = {
      center: { lat: 37.62, lon: -122.38 },
      zoom: 14,
      bearing: 0,
    };

    const { rerender } = render(<AirportMap sharedViewport={sfoViewport} />);
    mockFitBounds.mockClear();
    mockJumpTo.mockClear();

    mockCurrentAirport = 'EGLL';
    mockGetGates.mockReturnValue(LHR_GATES);
    rerender(<AirportMap sharedViewport={sfoViewport} />);

    expect(mockFitBounds).toHaveBeenCalled();
    const [bounds] = mockFitBounds.mock.calls[0];
    expect(bounds[0][1]).toBeGreaterThan(51.0);
  });

  it('prioritizes bounds over sharedViewport on initial render', () => {
    const sfoViewport = {
      center: { lat: 37.63, lon: -122.39 },
      zoom: 15,
      bearing: 0,
    };

    render(<AirportMap sharedViewport={sfoViewport} />);

    expect(mockFitBounds).toHaveBeenCalledTimes(1);
    expect(mockJumpTo).not.toHaveBeenCalled();
  });

  it('supports switching through multiple airports sequentially', () => {
    const { rerender } = render(<AirportMap />);
    mockFitBounds.mockClear();

    mockCurrentAirport = 'EGLL';
    mockGetGates.mockReturnValue(LHR_GATES);
    mockGetTerminals.mockReturnValue([]);
    rerender(<AirportMap />);

    expect(mockFitBounds).toHaveBeenCalledTimes(1);
    let [bounds] = mockFitBounds.mock.calls[0];
    expect(bounds[0][1]).toBeGreaterThan(51.0);
    mockFitBounds.mockClear();

    mockCurrentAirport = 'LFPG';
    mockGetGates.mockReturnValue([]);
    mockGetTerminals.mockReturnValue(CDG_TERMINALS);
    rerender(<AirportMap />);

    expect(mockFitBounds).toHaveBeenCalledTimes(1);
    [bounds] = mockFitBounds.mock.calls[0];
    expect(bounds[0][1]).toBeGreaterThan(48.0);
    expect(bounds[0][0]).toBeGreaterThan(2.0);
  });

  it('handles airport with no gates or terminals gracefully', () => {
    const { rerender } = render(<AirportMap />);
    mockFitBounds.mockClear();

    mockCurrentAirport = 'XXXX';
    mockGetGates.mockReturnValue([]);
    mockGetTerminals.mockReturnValue([]);
    rerender(<AirportMap />);
  });

  it('does not permanently lock recentering after switch with no bounds', () => {
    const { rerender } = render(<AirportMap />);
    mockFitBounds.mockClear();
    mockFlyTo.mockClear();

    mockCurrentAirport = 'EGLL';
    mockGetGates.mockReturnValue([]);
    mockGetTerminals.mockReturnValue([]);
    rerender(<AirportMap />);

    expect(mockFlyTo).toHaveBeenCalled();
    expect(mockFitBounds).not.toHaveBeenCalled();
    mockFlyTo.mockClear();

    mockCurrentAirport = 'LFPG';
    mockGetGates.mockReturnValue([]);
    mockGetTerminals.mockReturnValue(CDG_TERMINALS);
    rerender(<AirportMap />);

    expect(mockFitBounds).toHaveBeenCalledTimes(1);
    const [bounds] = mockFitBounds.mock.calls[0];
    expect(bounds[0][1]).toBeGreaterThan(48.0);
  });
});
