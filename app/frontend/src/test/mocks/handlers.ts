import { http, HttpResponse, delay } from 'msw'

// Mock flight data
export const mockFlights = [
  {
    icao24: 'a12345',
    callsign: 'UAL123',
    latitude: 37.6213,
    longitude: -122.379,
    altitude: 5000,
    velocity: 200,
    heading: 270,
    vertical_rate: -500,
    on_ground: false,
    last_seen: new Date().toISOString(),
    data_source: 'synthetic',
    flight_phase: 'descending' as const,
    aircraft_type: 'B737',
    origin_airport: 'LAX',
    destination_airport: 'SFO',
    assigned_gate: 'A3',
  },
  {
    icao24: 'b67890',
    callsign: 'DAL456',
    latitude: 37.5100,
    longitude: -122.250,
    altitude: 35000,
    velocity: 450,
    heading: 180,
    vertical_rate: 0,
    on_ground: false,
    last_seen: new Date().toISOString(),
    data_source: 'synthetic',
    flight_phase: 'cruising' as const,
    aircraft_type: 'A320',
    origin_airport: 'JFK',
    destination_airport: 'SFO',
  },
  {
    icao24: 'c11111',
    callsign: 'SWA789',
    latitude: 37.6150,
    longitude: -122.390,
    altitude: 0,
    velocity: 0,
    heading: 90,
    vertical_rate: 0,
    on_ground: true,
    last_seen: new Date().toISOString(),
    data_source: 'synthetic',
    flight_phase: 'ground' as const,
    aircraft_type: 'B738',
    origin_airport: 'DEN',
    destination_airport: 'SFO',
    assigned_gate: 'A5',
  },
]

// Mock weather data
export const mockWeather = {
  metar: {
    station: 'KSFO',
    observation_time: new Date().toISOString(),
    wind_direction: 280,
    wind_speed_kts: 12,
    wind_gust_kts: null,
    visibility_sm: 10,
    temperature_c: 18,
    dewpoint_c: 12,
    altimeter_inhg: 30.05,
    flight_category: 'VFR',
    clouds: [{ coverage: 'SCT', altitude_ft: 4500 }],
    raw_metar: 'KSFO 281856Z 28012KT 10SM SCT045 18/12 A3005',
  },
  station: 'KSFO',
  timestamp: new Date().toISOString(),
}

// Mock delay prediction
export const mockDelayPrediction = {
  delays: [
    {
      icao24: 'a12345',
      delay_minutes: 15,
      confidence: 0.75,
      category: 'slight',
    },
  ],
  count: 1,
  timestamp: new Date().toISOString(),
}

// Mock gate recommendations
export const mockGateRecommendations = [
  { gate_id: 'A1', score: 0.95, reasons: ['Available', 'Near terminal'], taxi_time: 3 },
  { gate_id: 'A3', score: 0.85, reasons: ['Available'], taxi_time: 5 },
  { gate_id: 'B2', score: 0.70, reasons: ['Far from terminal'], taxi_time: 8 },
]

// Mock congestion data
export const mockCongestion = {
  areas: [
    { area_id: 'runway_28L', area_type: 'runway', level: 'low', flight_count: 1, wait_minutes: 0 },
    { area_id: 'taxiway_A', area_type: 'taxiway', level: 'moderate', flight_count: 3, wait_minutes: 5 },
  ],
  count: 2,
  timestamp: new Date().toISOString(),
}

// Mock trajectory data
export const mockTrajectory = {
  icao24: 'a12345',
  callsign: 'UAL123',
  points: [
    { icao24: 'a12345', callsign: 'UAL123', latitude: 37.50, longitude: -122.50, altitude: 10000, velocity: 250, heading: 90, vertical_rate: -500, on_ground: false, flight_phase: 'descending', timestamp: (Date.now() - 300000) / 1000 },
    { icao24: 'a12345', callsign: 'UAL123', latitude: 37.55, longitude: -122.45, altitude: 8000, velocity: 230, heading: 95, vertical_rate: -400, on_ground: false, flight_phase: 'descending', timestamp: (Date.now() - 240000) / 1000 },
    { icao24: 'a12345', callsign: 'UAL123', latitude: 37.58, longitude: -122.42, altitude: 6000, velocity: 210, heading: 100, vertical_rate: -300, on_ground: false, flight_phase: 'descending', timestamp: (Date.now() - 180000) / 1000 },
    { icao24: 'a12345', callsign: 'UAL123', latitude: 37.60, longitude: -122.40, altitude: 5000, velocity: 200, heading: 270, vertical_rate: -500, on_ground: false, flight_phase: 'descending', timestamp: (Date.now() - 120000) / 1000 },
    { icao24: 'a12345', callsign: 'UAL123', latitude: 37.62, longitude: -122.38, altitude: 5000, velocity: 200, heading: 270, vertical_rate: -500, on_ground: false, flight_phase: 'descending', timestamp: Date.now() / 1000 },
  ],
  count: 5,
  start_time: (Date.now() - 300000) / 1000,
  end_time: Date.now() / 1000,
}

// Mock turnaround data
export const mockTurnaround = {
  turnaround: {
    icao24: 'c11111',
    gate: 'A5',
    aircraft_type: 'B738',
    current_phase: 'boarding',
    phase_progress_pct: 65,
    total_progress_pct: 80,
    estimated_departure: new Date(Date.now() + 30 * 60000).toISOString(),
    assigned_gse: ['TUG-001', 'FUEL-003'],
  },
  timestamp: new Date().toISOString(),
}

// Mock baggage data
export const mockBaggageStats = {
  stats: {
    flight_number: 'SWA789',
    total_bags: 120,
    loaded: 95,
    loading_progress_pct: 79,
    connecting_bags: 15,
    misconnects: 1,
  },
  bags: [],
  timestamp: new Date().toISOString(),
}

// Mock schedule data
export const mockArrivals = {
  flights: [
    {
      flight_number: 'UAL123', // Matches mockFlights callsign
      airline: 'United Airlines',
      airline_code: 'UAL',
      origin: 'LAX',
      destination: 'SFO',
      scheduled_time: new Date(Date.now() + 30 * 60000).toISOString(),
      estimated_time: null,
      actual_time: null,
      status: 'on_time',
      gate: 'B5',
      delay_minutes: 0,
      flight_type: 'arrival',
    },
    {
      flight_number: 'DAL456', // Matches mockFlights callsign
      airline: 'Delta Air Lines',
      airline_code: 'DAL',
      origin: 'JFK',
      destination: 'SFO',
      scheduled_time: new Date(Date.now() + 60 * 60000).toISOString(),
      estimated_time: new Date(Date.now() + 75 * 60000).toISOString(),
      actual_time: null,
      status: 'delayed',
      gate: 'A3',
      delay_minutes: 15,
      flight_type: 'arrival',
    },
  ],
  count: 2,
  airport: 'KSFO',
  flight_type: 'arrival',
  timestamp: new Date().toISOString(),
}

export const handlers = [
  // Flights endpoint
  http.get('/api/flights', async () => {
    await delay(50) // Simulate network latency
    return HttpResponse.json({
      flights: mockFlights,
      count: mockFlights.length,
      timestamp: new Date().toISOString(),
      data_source: 'synthetic',
    })
  }),

  // Single flight endpoint
  http.get('/api/flights/:icao24', async ({ params }) => {
    await delay(30)
    const flight = mockFlights.find((f) => f.icao24 === params.icao24)
    if (!flight) {
      return HttpResponse.json({ detail: 'Flight not found' }, { status: 404 })
    }
    return HttpResponse.json(flight)
  }),

  // Trajectory endpoint
  http.get('/api/flights/:icao24/trajectory', async ({ params }) => {
    await delay(100)
    if (params.icao24 === 'a12345') {
      return HttpResponse.json(mockTrajectory)
    }
    return HttpResponse.json({ icao24: params.icao24, callsign: null, points: [], count: 0, start_time: null, end_time: null })
  }),

  // Weather endpoint
  http.get('/api/weather/current', async () => {
    await delay(30)
    return HttpResponse.json(mockWeather)
  }),

  // Delay predictions
  http.get('/api/predictions/delays', async ({ request }) => {
    await delay(50)
    const url = new URL(request.url)
    const icao24 = url.searchParams.get('icao24')

    if (icao24) {
      const prediction = mockDelayPrediction.delays.find((d) => d.icao24 === icao24)
      return HttpResponse.json({
        delays: prediction ? [prediction] : [],
        count: prediction ? 1 : 0,
        timestamp: new Date().toISOString(),
      })
    }
    return HttpResponse.json(mockDelayPrediction)
  }),

  // Gate recommendations
  http.get('/api/predictions/gates/:icao24', async ({ request }) => {
    await delay(50)
    const url = new URL(request.url)
    const topK = parseInt(url.searchParams.get('top_k') || '3', 10)
    return HttpResponse.json(mockGateRecommendations.slice(0, topK))
  }),

  // Congestion
  http.get('/api/predictions/congestion', async () => {
    await delay(40)
    return HttpResponse.json(mockCongestion)
  }),

  // Bottlenecks (kept for backward compat)
  http.get('/api/predictions/bottlenecks', async () => {
    await delay(40)
    const bottlenecks = mockCongestion.areas.filter((a: { level: string }) => ['high', 'critical'].includes(a.level));
    return HttpResponse.json({
      areas: bottlenecks,
      count: bottlenecks.length,
      timestamp: new Date().toISOString(),
    })
  }),

  // Congestion summary (merged endpoint used by frontend)
  http.get('/api/predictions/congestion-summary', async () => {
    await delay(40)
    const bottlenecks = mockCongestion.areas.filter((a: { level: string }) => ['high', 'critical'].includes(a.level));
    return HttpResponse.json({
      areas: mockCongestion.areas,
      bottlenecks,
      areas_count: mockCongestion.areas.length,
      bottlenecks_count: bottlenecks.length,
    })
  }),

  // Schedule - arrivals
  http.get('/api/schedule/arrivals', async () => {
    await delay(50)
    return HttpResponse.json(mockArrivals)
  }),

  // Schedule - departures
  http.get('/api/schedule/departures', async () => {
    await delay(50)
    return HttpResponse.json({
      ...mockArrivals,
      flight_type: 'departure',
      flights: mockArrivals.flights.map((f) => ({ ...f, flight_type: 'departure' })),
    })
  }),

  // Turnaround
  http.get('/api/turnaround/:icao24', async () => {
    await delay(50)
    return HttpResponse.json(mockTurnaround)
  }),

  // Baggage stats
  http.get('/api/baggage/stats', async () => {
    await delay(40)
    return HttpResponse.json({
      total_bags_today: 15000,
      bags_in_system: 2500,
      misconnect_rate_pct: 1.2,
      avg_processing_time_min: 25,
      timestamp: new Date().toISOString(),
    })
  }),

  // Flight baggage
  http.get('/api/baggage/flight/:flightNumber', async () => {
    await delay(50)
    return HttpResponse.json(mockBaggageStats)
  }),

  // Baggage alerts
  http.get('/api/baggage/alerts', async () => {
    await delay(30)
    return HttpResponse.json({
      alerts: [],
      count: 0,
      timestamp: new Date().toISOString(),
    })
  }),

  // GSE status
  http.get('/api/gse/status', async () => {
    await delay(40)
    return HttpResponse.json({
      total_units: 50,
      available: 30,
      in_service: 15,
      maintenance: 5,
      units: [
        { unit_id: 'TUG-001', gse_type: 'pushback_tug', status: 'servicing' },
        { unit_id: 'FUEL-003', gse_type: 'fuel_truck', status: 'servicing' },
      ],
      timestamp: new Date().toISOString(),
    })
  }),

  // Airport preload status
  http.get('/api/airports/preload/status', () => {
    return HttpResponse.json({
      airports: [
        { icao: 'KSFO', iata: 'SFO', name: 'San Francisco International', city: 'San Francisco, CA', region: 'Americas', cached: true },
        { icao: 'KJFK', iata: 'JFK', name: 'John F. Kennedy International', city: 'New York, NY', region: 'Americas', cached: false },
        { icao: 'KLAX', iata: 'LAX', name: 'Los Angeles International', city: 'Los Angeles, CA', region: 'Americas', cached: false },
        { icao: 'KORD', iata: 'ORD', name: "O'Hare International", city: 'Chicago, IL', region: 'Americas', cached: false },
        { icao: 'KATL', iata: 'ATL', name: 'Hartsfield-Jackson Atlanta', city: 'Atlanta, GA', region: 'Americas', cached: false },
        { icao: 'KDFW', iata: 'DFW', name: 'Dallas/Fort Worth International', city: 'Dallas, TX', region: 'Americas', cached: false },
        { icao: 'KDEN', iata: 'DEN', name: 'Denver International', city: 'Denver, CO', region: 'Americas', cached: false },
        { icao: 'KMIA', iata: 'MIA', name: 'Miami International', city: 'Miami, FL', region: 'Americas', cached: false },
        { icao: 'KSEA', iata: 'SEA', name: 'Seattle-Tacoma International', city: 'Seattle, WA', region: 'Americas', cached: false },
        { icao: 'SBGR', iata: 'GRU', name: 'Guarulhos International', city: 'Sao Paulo, BR', region: 'Americas', cached: false },
        { icao: 'MMMX', iata: 'MEX', name: 'Mexico City International', city: 'Mexico City, MX', region: 'Americas', cached: false },
        { icao: 'EGLL', iata: 'LHR', name: 'London Heathrow', city: 'London, UK', region: 'Europe', cached: false },
        { icao: 'LFPG', iata: 'CDG', name: 'Charles de Gaulle', city: 'Paris, FR', region: 'Europe', cached: false },
        { icao: 'EHAM', iata: 'AMS', name: 'Amsterdam Schiphol', city: 'Amsterdam, NL', region: 'Europe', cached: false },
        { icao: 'EDDF', iata: 'FRA', name: 'Frankfurt Airport', city: 'Frankfurt, DE', region: 'Europe', cached: false },
        { icao: 'LEMD', iata: 'MAD', name: 'Adolfo Suarez Madrid-Barajas', city: 'Madrid, ES', region: 'Europe', cached: false },
        { icao: 'LIRF', iata: 'FCO', name: 'Leonardo da Vinci (Fiumicino)', city: 'Rome, IT', region: 'Europe', cached: false },
        { icao: 'OMAA', iata: 'AUH', name: 'Abu Dhabi International', city: 'Abu Dhabi, AE', region: 'Middle East', cached: false },
        { icao: 'OMDB', iata: 'DXB', name: 'Dubai International', city: 'Dubai, AE', region: 'Middle East', cached: false },
        { icao: 'RJTT', iata: 'HND', name: 'Tokyo Haneda', city: 'Tokyo, JP', region: 'Asia-Pacific', cached: false },
        { icao: 'VHHH', iata: 'HKG', name: 'Hong Kong International', city: 'Hong Kong', region: 'Asia-Pacific', cached: false },
        { icao: 'WSSS', iata: 'SIN', name: 'Singapore Changi', city: 'Singapore', region: 'Asia-Pacific', cached: false },
        { icao: 'ZBAA', iata: 'PEK', name: 'Beijing Capital International', city: 'Beijing, CN', region: 'Asia-Pacific', cached: false },
        { icao: 'RKSI', iata: 'ICN', name: 'Incheon International', city: 'Seoul, KR', region: 'Asia-Pacific', cached: false },
        { icao: 'VTBS', iata: 'BKK', name: 'Suvarnabhumi Airport', city: 'Bangkok, TH', region: 'Asia-Pacific', cached: false },
        { icao: 'FAOR', iata: 'JNB', name: 'O.R. Tambo International', city: 'Johannesburg, ZA', region: 'Africa', cached: false },
        { icao: 'GMMN', iata: 'CMN', name: 'Mohammed V International', city: 'Casablanca, MA', region: 'Africa', cached: false },
      ],
    })
  }),

  // Airport preload trigger
  http.post('/api/airports/preload', async () => {
    await delay(100)
    return HttpResponse.json({ preloaded: [], already_cached: ['KSFO'], failed: [] })
  }),

  // User pre-warm endpoint
  http.post('/api/user/prewarm', () => {
    return HttpResponse.json({ status: 'ok', user: 'anonymous', airports: ['KSFO'], already_cached: 1, warming: 0 })
  }),

  // Simulation files endpoint
  http.get('/api/simulation/files', () => {
    return HttpResponse.json({ files: [] })
  }),

  // Airport config endpoint
  http.get('/api/airport/config', async () => {
    await delay(30)
    // 20 gates across Terminal A (A1-A10) and Terminal B (B1-B10)
    const mockGates = [
      ...Array.from({ length: 10 }, (_, i) => ({
        id: `gate-a${i + 1}`,
        ref: `A${i + 1}`,
        terminal: 'Terminal A',
        geo: { latitude: 37.6150 + i * 0.0002, longitude: -122.3900 + i * 0.0003 },
      })),
      ...Array.from({ length: 10 }, (_, i) => ({
        id: `gate-b${i + 1}`,
        ref: `B${i + 1}`,
        terminal: 'Terminal B',
        geo: { latitude: 37.6130 + i * 0.0002, longitude: -122.3880 + i * 0.0003 },
      })),
    ]
    return HttpResponse.json({
      config: {
        sources: ['osm'],
        runways: [],
        taxiways: [],
        aprons: [],
        navaids: [],
        buildings: [],
        gates: mockGates,
        terminals: [],
        icaoCode: 'KSFO',
      },
      lastUpdated: new Date().toISOString(),
      elementCounts: { gates: 120, terminals: 8, taxiways: 244, aprons: 17 },
    })
  }),

  // Airport activate endpoint
  http.post('/api/airports/:icaoCode/activate', async ({ params }) => {
    await delay(50)
    return HttpResponse.json({
      config: {
        sources: ['osm'],
        runways: [],
        taxiways: [],
        aprons: [],
        navaids: [],
        buildings: [],
        gates: [],
        terminals: [],
        icaoCode: params.icaoCode,
      },
      source: 'osm',
      icaoCode: params.icaoCode,
      elementCounts: { gates: 120, terminals: 8, taxiways: 244, aprons: 17 },
      dataReady: true,
      gatesLoaded: 120,
      gateRecommenderCount: 120,
      stateReset: { cleared_flights: 0, cleared_gates: 0, status: 'reset_complete' },
    })
  }),

  // Readiness endpoint (backend startup status)
  http.get('/api/ready', async () => {
    return HttpResponse.json({ ready: true, status: 'Ready' })
  }),

  // Health check
  http.get('/health', async () => {
    return HttpResponse.json({ status: 'healthy' })
  }),
]
