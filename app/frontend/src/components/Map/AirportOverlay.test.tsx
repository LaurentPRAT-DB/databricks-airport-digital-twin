import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { OSMGate, OSMTerminal, OSMTaxiway, OSMRunway } from '../../types/airportFormats'

// Mock react-map-gl/maplibre
vi.mock('react-map-gl/maplibre', () => ({
  Source: ({ children, id, data }: { children?: React.ReactNode; id: string; data?: unknown }) => (
    <div data-testid={`source-${id}`} data-geojson={JSON.stringify(data)}>
      {children}
    </div>
  ),
  Layer: ({ id }: { id?: string }) => (
    <div data-testid={id ? `layer-${id}` : 'layer'} />
  ),
  Marker: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="marker">{children}</div>
  ),
  Popup: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="popup">{children}</div>
  ),
  useMap: () => ({ current: { on: vi.fn(), off: vi.fn(), getZoom: () => 14 } }),
}))

// Mock airport config context
const mockGates: OSMGate[] = [
  {
    id: 'gate-A1',
    osmId: 1001,
    ref: 'A1',
    terminal: 'Terminal A',
    name: 'Gate A1',
    position: { x: 0, y: 0, z: 0 },
    geo: { latitude: 37.6150, longitude: -122.3910, altitude: 0 },
  },
  {
    id: 'gate-B2',
    osmId: 1002,
    ref: 'B2',
    terminal: 'Terminal B',
    position: { x: 10, y: 0, z: 0 },
    geo: { latitude: 37.6160, longitude: -122.3920, altitude: 0 },
  },
]

const mockContextValue = {
  getGates: vi.fn(() => mockGates),
  getTerminals: vi.fn((): OSMTerminal[] => []),
  getTaxiways: vi.fn((): OSMTaxiway[] => []),
  getAprons: vi.fn(() => []),
  getOSMRunways: vi.fn((): OSMRunway[] => []),
}

vi.mock('../../context/AirportConfigContext', () => ({
  useAirportConfigContext: () => mockContextValue,
}))

vi.mock('../../hooks/usePredictions', () => ({
  useCongestion: () => ({ congestion: [], bottlenecks: [], isLoading: false, error: null }),
}))

vi.mock('../../context/CongestionFilterContext', () => ({
  useCongestionFilter: () => ({ activeLevel: null, setActiveLevel: () => {}, selectedArea: null, setSelectedArea: () => {} }),
}))

// Import after mocks
import AirportOverlay, { getGateDotRadius, GATE_LABEL_ZOOM } from './AirportOverlay'

describe('AirportOverlay', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockContextValue.getGates.mockReturnValue(mockGates)
    mockContextValue.getTerminals.mockReturnValue([])
    mockContextValue.getTaxiways.mockReturnValue([])
    mockContextValue.getAprons.mockReturnValue([])
    mockContextValue.getOSMRunways.mockReturnValue([])
  })

  describe('Gate rendering', () => {
    it('renders gates source with circle layer', () => {
      const { getByTestId } = render(<AirportOverlay />)
      expect(getByTestId('source-gates')).toBeTruthy()
      expect(getByTestId('layer-gates-circle')).toBeTruthy()
    })

    it('includes gate coordinates in GeoJSON data', () => {
      const { getByTestId } = render(<AirportOverlay />)
      const sourceEl = getByTestId('source-gates')
      const data = JSON.parse(sourceEl.dataset.geojson || '{}')
      expect(data.features).toHaveLength(2)
      // MapLibre GeoJSON uses [lng, lat] order
      expect(data.features[0].geometry.coordinates[0]).toBeCloseTo(-122.391)
      expect(data.features[0].geometry.coordinates[1]).toBeCloseTo(37.615)
    })

    it('includes gate labels in feature properties', () => {
      const { getByTestId } = render(<AirportOverlay />)
      const sourceEl = getByTestId('source-gates')
      const data = JSON.parse(sourceEl.dataset.geojson || '{}')
      expect(data.features[0].properties.label).toBe('A1')
      expect(data.features[1].properties.label).toBe('B2')
    })
  })

  describe('Empty data behavior', () => {
    it('does not render gate source when no gates available', () => {
      mockContextValue.getGates.mockReturnValue([])
      const { queryByTestId } = render(<AirportOverlay />)
      expect(queryByTestId('source-gates')).not.toBeInTheDocument()
    })
  })

  describe('OSM feature rendering', () => {
    it('renders terminals source with fill layer', () => {
      mockContextValue.getTerminals.mockReturnValue([{
        id: 't1', name: 'Terminal 1', geoPolygon: [
          { latitude: 37.615, longitude: -122.391, altitude: 0 },
          { latitude: 37.616, longitude: -122.391, altitude: 0 },
          { latitude: 37.616, longitude: -122.392, altitude: 0 },
        ],
      }] as Partial<OSMTerminal>[] as OSMTerminal[])
      const { getByTestId } = render(<AirportOverlay />)
      expect(getByTestId('source-terminals')).toBeTruthy()
      expect(getByTestId('layer-terminals-fill')).toBeTruthy()
    })

    it('renders taxiways source with line layer', () => {
      mockContextValue.getTaxiways.mockReturnValue([{
        id: 'tw1', name: 'A', geoPoints: [
          { latitude: 37.615, longitude: -122.391, altitude: 0 },
          { latitude: 37.616, longitude: -122.392, altitude: 0 },
        ],
      }] as Partial<OSMTaxiway>[] as OSMTaxiway[])
      const { getByTestId } = render(<AirportOverlay />)
      expect(getByTestId('source-taxiways')).toBeTruthy()
      expect(getByTestId('layer-taxiways-line')).toBeTruthy()
    })

    it('renders runways source with line layer', () => {
      mockContextValue.getOSMRunways.mockReturnValue([{
        id: 'rw1', name: '28L', geoPoints: [
          { latitude: 37.615, longitude: -122.391, altitude: 0 },
          { latitude: 37.620, longitude: -122.380, altitude: 0 },
        ],
      }] as Partial<OSMRunway>[] as OSMRunway[])
      const { getByTestId } = render(<AirportOverlay />)
      expect(getByTestId('source-runways')).toBeTruthy()
      expect(getByTestId('layer-runways-line')).toBeTruthy()
    })
  })
})

describe('getGateDotRadius', () => {
  it('returns 2 for zoom <= 12', () => {
    expect(getGateDotRadius(10)).toBe(2)
    expect(getGateDotRadius(12)).toBe(2)
  })

  it('returns 3 for zoom 14 (default)', () => {
    expect(getGateDotRadius(14)).toBe(3)
  })

  it('returns 4 for zoom 15', () => {
    expect(getGateDotRadius(15)).toBe(4)
  })

  it('returns 5 for zoom 16', () => {
    expect(getGateDotRadius(16)).toBe(5)
  })

  it('returns 7 for zoom >= 18', () => {
    expect(getGateDotRadius(18)).toBe(7)
    expect(getGateDotRadius(20)).toBe(7)
  })

  it('scales monotonically from zoom 12 to 18', () => {
    let prev = 0
    for (let z = 12; z <= 18; z++) {
      const r = getGateDotRadius(z)
      expect(r).toBeGreaterThanOrEqual(prev)
      prev = r
    }
  })
})

describe('GATE_LABEL_ZOOM', () => {
  it('is 17', () => {
    expect(GATE_LABEL_ZOOM).toBe(17)
  })
})
