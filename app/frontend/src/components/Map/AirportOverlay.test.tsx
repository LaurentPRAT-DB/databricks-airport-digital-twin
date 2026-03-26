import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { OSMGate, OSMTerminal, OSMTaxiway, OSMRunway } from '../../types/airportFormats'

// Mock react-leaflet — must be before importing the component
vi.mock('react-leaflet', () => ({
  GeoJSON: ({ data }: { data: unknown }) => (
    <div data-testid="geojson">{JSON.stringify(data)}</div>
  ),
  CircleMarker: ({ center, radius, children }: { center: number[]; radius: number; children?: React.ReactNode }) => (
    <div data-testid="circle-marker" data-radius={radius} data-center={center.join(',')}>
      {children}
    </div>
  ),
  Tooltip: ({ children, permanent, className }: { children?: React.ReactNode; permanent?: boolean; className?: string }) => (
    <div
      data-testid="tooltip"
      data-permanent={permanent ? 'true' : 'false'}
      data-classname={className || ''}
    >
      {children}
    </div>
  ),
  Polygon: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="polygon">{children}</div>
  ),
  Polyline: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="polyline">{children}</div>
  ),
  useMapEvents: () => null,
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

vi.mock('../../constants/airportLayout', () => ({
  airportLayout: { type: 'FeatureCollection', features: [] },
  getFeaturesByType: () => [],
}))

vi.mock('../../hooks/usePredictions', () => ({
  useCongestion: () => ({ congestion: [], bottlenecks: [], isLoading: false, error: null }),
}))

vi.mock('../../context/CongestionFilterContext', () => ({
  useCongestionFilter: () => ({ activeLevel: null, setActiveLevel: () => {} }),
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
    it('renders OSM gates as circle markers', () => {
      const { getAllByTestId } = render(<AirportOverlay />)
      const markers = getAllByTestId('circle-marker')
      expect(markers).toHaveLength(2)
    })

    it('uses correct gate coordinates from OSM data', () => {
      const { getAllByTestId } = render(<AirportOverlay />)
      const markers = getAllByTestId('circle-marker')
      expect(markers[0].dataset.center).toBe('37.615,-122.391')
      expect(markers[1].dataset.center).toBe('37.616,-122.392')
    })

    it('displays gate ref as label text', () => {
      const { getAllByTestId } = render(<AirportOverlay />)
      const tooltips = getAllByTestId('tooltip')
      expect(tooltips[0].textContent).toContain('A1')
      expect(tooltips[1].textContent).toContain('B2')
    })

    it('at default zoom (14) shows hover-only tooltips with Gate prefix', () => {
      // Default useState(14) < GATE_LABEL_ZOOM, so labels are hover-only
      const { getAllByTestId } = render(<AirportOverlay />)
      const tooltips = getAllByTestId('tooltip')
      tooltips.forEach((t) => {
        expect(t.dataset.permanent).toBe('false')
      })
      expect(tooltips[0].textContent).toBe('Gate A1')
      expect(tooltips[1].textContent).toBe('Gate B2')
    })

    it('at default zoom (14) uses radius 3', () => {
      const { getAllByTestId } = render(<AirportOverlay />)
      const markers = getAllByTestId('circle-marker')
      expect(markers[0].dataset.radius).toBe('3')
    })
  })

  describe('Fallback behavior', () => {
    it('does not render hardcoded GeoJSON when OSM terminals present', () => {
      mockContextValue.getTerminals.mockReturnValue([{
        id: 't1', name: 'T1', geoPolygon: [
          { latitude: 37.615, longitude: -122.391, altitude: 0 },
          { latitude: 37.616, longitude: -122.391, altitude: 0 },
          { latitude: 37.616, longitude: -122.392, altitude: 0 },
        ],
      }] as Partial<OSMTerminal>[] as OSMTerminal[])
      const { queryByTestId } = render(<AirportOverlay />)
      expect(queryByTestId('geojson')).not.toBeInTheDocument()
    })

    it('renders hardcoded GeoJSON when no OSM data at all', () => {
      mockContextValue.getGates.mockReturnValue([])
      const { getByTestId } = render(<AirportOverlay />)
      expect(getByTestId('geojson')).toBeInTheDocument()
    })

    it('does not render gate markers when no gates available', () => {
      mockContextValue.getGates.mockReturnValue([])
      const { queryAllByTestId } = render(<AirportOverlay />)
      expect(queryAllByTestId('circle-marker')).toHaveLength(0)
    })
  })

  describe('OSM feature rendering', () => {
    it('renders terminals as polygons', () => {
      mockContextValue.getTerminals.mockReturnValue([{
        id: 't1', name: 'Terminal 1', geoPolygon: [
          { latitude: 37.615, longitude: -122.391, altitude: 0 },
          { latitude: 37.616, longitude: -122.391, altitude: 0 },
          { latitude: 37.616, longitude: -122.392, altitude: 0 },
        ],
      }] as Partial<OSMTerminal>[] as OSMTerminal[])
      const { getAllByTestId } = render(<AirportOverlay />)
      expect(getAllByTestId('polygon')).toHaveLength(1)
    })

    it('renders taxiways as polylines', () => {
      // Need terminals too so hasOSMData is true and hardcoded is hidden
      mockContextValue.getTerminals.mockReturnValue([{
        id: 't1', name: 'T1', geoPolygon: [
          { latitude: 37.615, longitude: -122.391, altitude: 0 },
          { latitude: 37.616, longitude: -122.391, altitude: 0 },
          { latitude: 37.616, longitude: -122.392, altitude: 0 },
        ],
      }] as Partial<OSMTerminal>[] as OSMTerminal[])
      mockContextValue.getTaxiways.mockReturnValue([{
        id: 'tw1', name: 'A', geoPoints: [
          { latitude: 37.615, longitude: -122.391, altitude: 0 },
          { latitude: 37.616, longitude: -122.392, altitude: 0 },
        ],
      }] as Partial<OSMTaxiway>[] as OSMTaxiway[])
      const { getAllByTestId } = render(<AirportOverlay />)
      expect(getAllByTestId('polyline').length).toBeGreaterThanOrEqual(1)
    })

    it('renders runways as polylines', () => {
      mockContextValue.getOSMRunways.mockReturnValue([{
        id: 'rw1', name: '28L', geoPoints: [
          { latitude: 37.615, longitude: -122.391, altitude: 0 },
          { latitude: 37.620, longitude: -122.380, altitude: 0 },
        ],
      }] as Partial<OSMRunway>[] as OSMRunway[])
      const { getAllByTestId } = render(<AirportOverlay />)
      expect(getAllByTestId('polyline').length).toBeGreaterThanOrEqual(1)
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
