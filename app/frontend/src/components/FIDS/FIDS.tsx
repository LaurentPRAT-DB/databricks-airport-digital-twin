import { useState, useEffect, useMemo, useRef } from 'react';
import { useFlightContext } from '../../context/FlightContext';
import { useAirportConfigContext } from '../../context/AirportConfigContext';
import { Flight } from '../../types/flight';

interface ScheduledFlight {
  flight_number: string;
  airline: string;
  airline_code: string;
  origin: string;
  destination: string;
  scheduled_time: string;
  estimated_time: string | null;
  actual_time: string | null;
  gate: string | null;
  status: string;
  delay_minutes: number;
  aircraft_type: string;
  flight_type: 'arrival' | 'departure';
}

/** Buffered arrival entry — keeps landed flights visible on the FIDS board. */
interface StickyArrival {
  entry: ScheduledFlight;
  lastSeenMs: number; // sim-time epoch ms when last in trackedFlights
}

/** How long (sim-time ms) a landed flight stays on the arrivals board. */
const ARRIVAL_RETENTION_MS = 30 * 60_000; // 30 minutes

interface ScheduleResponse {
  flights: ScheduledFlight[];
  count: number;
  airport: string;
  flight_type: string;
}

const STATUS_COLORS: Record<string, string> = {
  on_time: 'text-green-400',
  scheduled: 'text-slate-300',
  delayed: 'text-yellow-400',
  boarding: 'text-blue-400',
  final_call: 'text-orange-400',
  gate_closed: 'text-red-400',
  departed: 'text-slate-500',
  arrived: 'text-slate-500',
  cancelled: 'text-red-400',
};

const STATUS_LABELS: Record<string, string> = {
  on_time: 'On Time',
  scheduled: 'Scheduled',
  delayed: 'Delayed',
  boarding: 'Boarding',
  final_call: 'Final Call',
  gate_closed: 'Gate Closed',
  departed: 'Departed',
  arrived: 'Arrived',
  cancelled: 'Cancelled',
};

function formatTime(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

interface FIDSProps {
  onClose: () => void;
  simTime?: string | null;
}

export default function FIDS({ onClose, simTime }: FIDSProps) {
  const [activeTab, setActiveTab] = useState<'arrivals' | 'departures'>('arrivals');
  const [arrivals, setArrivals] = useState<ScheduledFlight[]>([]);
  const [departures, setDepartures] = useState<ScheduledFlight[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  // Get current airport so we re-fetch when it changes
  const { currentAirport } = useAirportConfigContext();

  // Get tracked flights for linking and sim-replay detection
  const { flights: trackedFlights, setSelectedFlight, dataSource } = useFlightContext();

  // Create callsign → tracked flight mapping
  const callsignToFlight = useMemo(() => {
    const map = new Map<string, Flight>();
    trackedFlights.forEach(flight => {
      if (flight.callsign?.trim()) {
        // Map both with and without spaces
        map.set(flight.callsign.trim().toUpperCase(), flight);
      }
    });
    return map;
  }, [trackedFlights]);

  // Handle flight click - select tracked flight and close FIDS
  const handleFlightClick = (flightNumber: string) => {
    const tracked = callsignToFlight.get(flightNumber.toUpperCase());
    if (tracked) {
      setSelectedFlight(tracked);
      onClose();
    }
  };

  // Keep a ref to simTime so the interval always uses the latest value
  // without re-triggering the effect on every frame.
  const simTimeRef = useRef(simTime);
  simTimeRef.current = simTime;

  // Sticky buffer: keeps recently-arrived flights visible on the FIDS board
  // even after they leave the simulation's tracked flights list.
  const stickyArrivals = useRef<Map<string, StickyArrival>>(new Map());

  // Airline name lookup (ICAO 3-letter codes)
  const AIRLINE_NAMES: Record<string, string> = useMemo(() => ({
    UAL: 'United Airlines', DAL: 'Delta Air Lines', AAL: 'American Airlines',
    SWA: 'Southwest Airlines', JBU: 'JetBlue Airways', ASA: 'Alaska Airlines',
    FFT: 'Frontier Airlines', NKS: 'Spirit Airlines', SKW: 'SkyWest Airlines',
    RPA: 'Republic Airways', ENY: 'Envoy Air', PDT: 'Piedmont Airlines',
    UAE: 'Emirates', BAW: 'British Airways', AFR: 'Air France', DLH: 'Lufthansa',
    ANA: 'All Nippon Airways', JAL: 'Japan Airlines', CPA: 'Cathay Pacific',
    QFA: 'Qantas', SIA: 'Singapore Airlines', KAL: 'Korean Air',
    AMX: 'Aeromexico', ACA: 'Air Canada', WJA: 'WestJet',
  }), []);

  // Derive FIDS schedule entries from map flights only during simulation replay.
  // In live mode, the REST API provides schedule data (with delays, background flights, etc.)
  const isSimReplay = dataSource === 'simulation';

  // Deterministic hash for stable per-flight values (times, origins) across frames
  const hashStr = (s: string): number => {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    return Math.abs(h);
  };

  // Common origin airports for realistic FIDS display
  const ORIGIN_AIRPORTS = [
    'LAX', 'JFK', 'ORD', 'DFW', 'DEN', 'ATL', 'SEA', 'BOS', 'MIA', 'PHX',
    'IAH', 'MSP', 'DTW', 'EWR', 'LAS', 'MCO', 'CLT', 'PHL', 'SAN', 'PDX',
    'SLC', 'IAD', 'BWI', 'TPA', 'AUS', 'BNA', 'RDU', 'HNL', 'OAK', 'SJC',
  ];

  // Anchor to the start of the current hour so scheduled times are FIXED
  // (real FIDS show fixed ETAs; only the clock moves, not the schedule)
  const hourAnchor = useMemo(() => {
    if (!simTime) return null;
    const t = new Date(simTime);
    t.setMinutes(0, 0, 0);
    return t.getTime();
  }, [simTime]);

  // Current sim time for the clock display (formatted)
  const simClockDisplay = useMemo(() => {
    if (!simTime) return null;
    return new Date(simTime).toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    });
  }, [simTime]);

  const derivedSchedule = useMemo(() => {
    if (!isSimReplay || trackedFlights.length === 0) return null;

    const anchor = hourAnchor || new Date().setMinutes(0, 0, 0);
    const arrivingPhases = new Set(['approaching', 'landing', 'taxi_in']);
    const departingPhases = new Set(['pushback', 'taxi_out', 'takeoff', 'departing']);

    const arr: ScheduledFlight[] = [];
    const dep: ScheduledFlight[] = [];

    for (const f of trackedFlights) {
      const callsign = f.callsign?.trim() || '';
      if (!callsign) continue;
      const code = callsign.slice(0, 3).toUpperCase();
      const airline = AIRLINE_NAMES[code] || code;
      const phase = f.flight_phase;
      const icao = currentAirport || 'KSFO';
      const localIata = icao.startsWith('K') && icao.length === 4 ? icao.slice(1) : icao;

      // Deterministic hash for this flight (stable across frames)
      const h = hashStr(callsign);

      let isArrival: boolean;
      if (arrivingPhases.has(phase)) isArrival = true;
      else if (departingPhases.has(phase)) isArrival = false;
      else if (phase === 'parked') {
        isArrival = f.destination_airport === localIata || !f.destination_airport;
      } else {
        isArrival = (f.destination_airport === localIata) ||
                    (!!f.origin_airport && !f.destination_airport);
      }

      // Map phase to FIDS status
      let status: string;
      if (phase === 'parked') status = isArrival ? 'arrived' : 'scheduled';
      else if (phase === 'approaching') status = 'on_time';
      else if (phase === 'landing') status = 'final_call';
      else if (phase === 'taxi_in') status = 'arrived';
      else if (phase === 'pushback' || phase === 'taxi_out') status = 'gate_closed';
      else if (phase === 'takeoff' || phase === 'departing') status = 'departed';
      else if (phase === 'enroute') status = isArrival ? 'scheduled' : 'departed';
      else status = 'on_time';

      // Compute ETA / scheduled time from flight physics.
      // "scheduled_time" = the original schedule (fixed per flight via hash).
      // "estimated_time" = current ETA based on real-time state (may differ → delay).
      const now = simTime ? new Date(simTime).getTime() : Date.now();
      let schedTime: Date;       // Original schedule (fixed, hash-based)
      let estimatedTime: Date | null = null;  // Real-time ETA (if different from schedule)
      let delayMin = 0;

      if (phase === 'approaching') {
        // Real ETA from altitude: descend at ~1500 ft/min + 5 min for approach pattern
        const alt = Number(f.altitude) || 0;
        const vRate = Math.abs(Number(f.vertical_rate) || 1500); // ft/min
        const etaMin = Math.max(2, Math.round(alt / vRate + 5));
        // Round ETA to nearest minute for stability
        const etaMs = Math.round(etaMin) * 60000;
        estimatedTime = new Date(now + etaMs);
        // Scheduled time = hash-based original time (what the schedule said)
        schedTime = new Date(anchor + (45 + (h % 20)) * 60000);
        // Delay = how much later than scheduled
        delayMin = Math.max(0, Math.round((estimatedTime.getTime() - schedTime.getTime()) / 60000));
        if (delayMin > 0) status = 'delayed';
      } else if (phase === 'landing') {
        // Landing now — ETA is now
        estimatedTime = new Date(now);
        schedTime = new Date(anchor + (40 + (h % 15)) * 60000);
        status = 'arrived';
      } else if (phase === 'taxi_in') {
        // Taxiing to gate — arrived, at gate in ~5 min
        estimatedTime = new Date(now);
        schedTime = new Date(anchor + (40 + (h % 15)) * 60000);
      } else if (phase === 'parked' && isArrival) {
        // Arrived and parked — spread across the past hour
        schedTime = new Date(anchor + (h % 50) * 60000);
      } else if (phase === 'pushback' || phase === 'taxi_out') {
        // Departing — scheduled time is hash-based, show "Gate Closed"
        schedTime = new Date(anchor + (45 + (h % 15)) * 60000);
      } else if (phase === 'takeoff' || phase === 'departing') {
        schedTime = new Date(anchor + (35 + (h % 20)) * 60000);
      } else if (phase === 'parked' && !isArrival) {
        // Departure waiting at gate
        schedTime = new Date(anchor + (60 + (h % 59)) * 60000);
      } else if (phase === 'enroute' && isArrival) {
        // Enroute: ETA from speed + rough distance
        const alt = Number(f.altitude) || 20000;
        const etaMin = Math.max(10, Math.round(alt / 500 + 10));
        estimatedTime = new Date(now + etaMin * 60000);
        schedTime = new Date(anchor + (60 + (h % 59)) * 60000);
        delayMin = Math.max(0, Math.round((estimatedTime.getTime() - schedTime.getTime()) / 60000));
        if (delayMin > 0) status = 'delayed';
      } else {
        schedTime = new Date(anchor + (h % 119) * 60000);
      }

      // Use actual origin/dest if available, otherwise derive from hash
      const origin = f.origin_airport || (isArrival ? ORIGIN_AIRPORTS[h % ORIGIN_AIRPORTS.length] : localIata);
      const destination = f.destination_airport || (isArrival ? localIata : ORIGIN_AIRPORTS[(h >> 4) % ORIGIN_AIRPORTS.length]);

      const entry: ScheduledFlight = {
        flight_number: callsign,
        airline,
        airline_code: code,
        origin,
        destination,
        scheduled_time: schedTime.toISOString(),
        estimated_time: estimatedTime ? estimatedTime.toISOString() : null,
        actual_time: (status === 'arrived' || status === 'departed') ? (estimatedTime || schedTime).toISOString() : null,
        gate: f.assigned_gate || null,
        status,
        delay_minutes: delayMin,
        aircraft_type: f.aircraft_type || 'A320',
        flight_type: isArrival ? 'arrival' : 'departure',
      };

      if (isArrival) arr.push(entry);
      else dep.push(entry);
    }

    // ── Sticky arrival buffer ──────────────────────────────────────
    // Real FIDS keep landed flights visible for ~30 min so passengers
    // at the arrivals hall can still see them.
    const nowMs = simTime ? new Date(simTime).getTime() : Date.now();
    const buffer = stickyArrivals.current;
    const currentCallsigns = new Set(arr.map(a => a.flight_number));

    // Update buffer: refresh timestamp for every arrival currently tracked
    for (const a of arr) {
      buffer.set(a.flight_number, { entry: { ...a, status: a.status }, lastSeenMs: nowMs });
    }

    // Inject buffered arrivals that left the tracked list but are still within retention
    for (const [callsign, sticky] of buffer) {
      if (currentCallsigns.has(callsign)) continue; // still tracked — already in list
      if (nowMs - sticky.lastSeenMs > ARRIVAL_RETENTION_MS) {
        buffer.delete(callsign); // expired — evict
        continue;
      }
      // Re-add with "Arrived" status (flight has landed and left the sim)
      arr.push({ ...sticky.entry, status: 'arrived' });
    }

    arr.sort((a, b) => a.scheduled_time.localeCompare(b.scheduled_time));
    dep.sort((a, b) => a.scheduled_time.localeCompare(b.scheduled_time));
    return { arrivals: arr, departures: dep };
  }, [trackedFlights, hourAnchor, currentAirport, isSimReplay, AIRLINE_NAMES, simTime]);

  // When in simulation replay mode, use derived schedule from map flights.
  // In live mode, fetch from the REST API.
  useEffect(() => {
    if (derivedSchedule) {
      setArrivals(derivedSchedule.arrivals);
      setDepartures(derivedSchedule.departures);
      setLoading(false);
      setError(null);
    }
  }, [derivedSchedule]);

  useEffect(() => {
    // Skip API fetch when we have derived schedule from simulation
    if (derivedSchedule) return;

    let cancelled = false;

    async function fetchSchedule() {
      try {
        const st = simTimeRef.current;
        const params = st ? `?sim_time=${encodeURIComponent(st)}` : '';
        const [arrivalsRes, departuresRes] = await Promise.all([
          fetch(`/api/schedule/arrivals${params}`),
          fetch(`/api/schedule/departures${params}`),
        ]);

        if (cancelled) return;

        if (!arrivalsRes.ok || !departuresRes.ok) {
          throw new Error('Failed to fetch schedule');
        }

        const arrivalsData: ScheduleResponse = await arrivalsRes.json();
        const departuresData: ScheduleResponse = await departuresRes.json();

        if (!cancelled) {
          setArrivals(arrivalsData.flights);
          setDepartures(departuresData.flights);
          setError(null);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unknown error');
          setLoading(false);
        }
      }
    }

    fetchSchedule();
    // Refresh every 15 seconds to stay in sync with live sim flights
    const interval = setInterval(fetchSchedule, 15 * 1000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [currentAirport, derivedSchedule]);

  const allFlights = activeTab === 'arrivals' ? arrivals : departures;
  const flights = useMemo(() => {
    if (!search.trim()) return allFlights;
    const q = search.trim().toLowerCase();
    return allFlights.filter(f =>
      f.flight_number.toLowerCase().includes(q) ||
      f.airline.toLowerCase().includes(q) ||
      f.origin.toLowerCase().includes(q) ||
      f.destination.toLowerCase().includes(q) ||
      (f.gate && f.gate.toLowerCase().includes(q))
    );
  }, [allFlights, search]);

  return (
    <div className="fixed inset-0 bg-black/50 z-[1003] flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-slate-900 rounded-lg shadow-2xl w-full max-w-4xl max-h-[100vh] md:max-h-[80vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-700">
          <div className="flex items-center gap-4">
            <h2 className="text-xl font-bold text-white">Flight Information Display</h2>
            <div className="flex rounded-lg overflow-hidden">
              <button
                onClick={() => setActiveTab('arrivals')}
                className={`px-4 py-2 text-sm font-medium transition-colors ${
                  activeTab === 'arrivals'
                    ? 'bg-blue-600 text-white'
                    : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                }`}
              >
                Arrivals
              </button>
              <button
                onClick={() => setActiveTab('departures')}
                className={`px-4 py-2 text-sm font-medium transition-colors ${
                  activeTab === 'departures'
                    ? 'bg-blue-600 text-white'
                    : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                }`}
              >
                Departures
              </button>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <input
              type="text"
              placeholder="Search flights..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 w-48"
            />
            <button
              onClick={onClose}
              className="text-slate-400 hover:text-white text-2xl font-light"
              aria-label="Close FIDS"
            >
              x
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto overscroll-contain">
          {loading ? (
            <div className="flex items-center justify-center h-64">
              <div className="text-slate-400">Loading schedule...</div>
            </div>
          ) : error ? (
            <div className="flex items-center justify-center h-64">
              <div className="text-red-400">{error}</div>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-slate-800 sticky top-0">
                <tr className="text-left text-slate-400 uppercase text-xs">
                  <th className="px-4 py-3">Time</th>
                  <th className="px-4 py-3">Flight</th>
                  <th className="px-4 py-3">{activeTab === 'arrivals' ? 'From' : 'To'}</th>
                  <th className="px-4 py-3">Gate</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Remarks</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {flights.map((flight, index) => {
                  const isTracked = callsignToFlight.has(flight.flight_number.toUpperCase());
                  const trackedFlight = isTracked ? callsignToFlight.get(flight.flight_number.toUpperCase()) : undefined;
                  const flightPhase = trackedFlight?.flight_phase;
                  return (
                  <tr
                    key={`${flight.flight_number}-${index}`}
                    className={`text-white hover:bg-slate-800/50 ${
                      isTracked ? 'cursor-pointer bg-blue-900/20 hover:bg-blue-900/40 border-l-2 border-l-blue-500' : ''
                    }`}
                    onClick={isTracked ? () => handleFlightClick(flight.flight_number) : undefined}
                  >
                    <td className="px-4 py-3 font-mono">
                      <div className={flight.delay_minutes > 0 ? 'line-through text-slate-500' : ''}>
                        {formatTime(flight.scheduled_time)}
                      </div>
                      {flight.estimated_time && flight.delay_minutes > 0 && (
                        <div className="text-yellow-400 text-xs font-bold">
                          Est: {formatTime(flight.estimated_time)}
                        </div>
                      )}
                      {flight.estimated_time && flight.delay_minutes === 0 && flight.status !== 'arrived' && flight.status !== 'departed' && (
                        <div className="text-green-400 text-xs">
                          ETA {formatTime(flight.estimated_time)}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-bold flex items-center gap-2">
                        {flight.flight_number}
                        {isTracked && (
                          <span className="px-1.5 py-0.5 bg-blue-600 text-[10px] rounded uppercase font-semibold animate-pulse">
                            Live
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-slate-400">
                        {flight.airline}
                        {flightPhase && (
                          <span className="ml-1 text-blue-400">
                            ({flightPhase.replace(/_/g, ' ')})
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 font-mono">
                      {activeTab === 'arrivals' ? flight.origin : flight.destination}
                    </td>
                    <td className="px-4 py-3 font-mono text-blue-400">
                      {flight.gate || '-'}
                    </td>
                    <td className="px-4 py-3">
                      <span className={STATUS_COLORS[flight.status] || 'text-slate-300'}>
                        {STATUS_LABELS[flight.status] || flight.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-xs text-slate-400">
                      {flight.delay_minutes > 0 && (
                        <span className="text-yellow-400">
                          +{flight.delay_minutes} min
                        </span>
                      )}
                      {flight.actual_time && (
                        <span className="ml-2">
                          {formatTime(flight.actual_time)}
                        </span>
                      )}
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-slate-700 text-xs text-slate-500 flex items-center justify-between">
          <span>{flights.length} {activeTab} | Auto-refresh: 15s</span>
          {simClockDisplay && (
            <span className="font-mono text-slate-300 text-sm">{simClockDisplay}</span>
          )}
          <span>Synthetic data for demo</span>
        </div>
      </div>
    </div>
  );
}
