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
  const derivedSchedule = useMemo(() => {
    if (!isSimReplay || trackedFlights.length === 0) return null;

    const now = simTime ? new Date(simTime) : new Date();
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
      // currentAirport is ICAO code like "KSFO"; derive IATA by dropping leading K (US) or using as-is
      const icao = currentAirport || 'KSFO';
      const localIata = icao.startsWith('K') && icao.length === 4 ? icao.slice(1) : icao;

      let isArrival: boolean;
      if (arrivingPhases.has(phase)) isArrival = true;
      else if (departingPhases.has(phase)) isArrival = false;
      else if (phase === 'parked') {
        // Parked: check if it arrived (has origin set and dest is local)
        isArrival = f.destination_airport === localIata || !f.destination_airport;
      } else {
        // enroute or unknown: use origin/dest convention
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

      // Compute scheduled time from flight state
      let schedTime: Date;
      if (phase === 'approaching') {
        const alt = Number(f.altitude) || 0;
        const etaMin = Math.max(3, Math.round(alt / 800));
        schedTime = new Date(now.getTime() + etaMin * 60000);
      } else if (phase === 'landing' || phase === 'taxi_in') {
        schedTime = new Date(now.getTime() - 2 * 60000);
      } else if (phase === 'parked' && isArrival) {
        schedTime = new Date(now.getTime() - 10 * 60000);
      } else if (phase === 'pushback' || phase === 'taxi_out') {
        schedTime = new Date(now.getTime() - 2 * 60000);
      } else if (phase === 'takeoff' || phase === 'departing') {
        schedTime = new Date(now.getTime() - 5 * 60000);
      } else if (phase === 'enroute' && isArrival) {
        schedTime = new Date(now.getTime() + 30 * 60000);
      } else {
        schedTime = new Date(now.getTime() + 15 * 60000);
      }

      const entry: ScheduledFlight = {
        flight_number: callsign,
        airline,
        airline_code: code,
        origin: isArrival ? (f.origin_airport || '???') : localIata,
        destination: isArrival ? localIata : (f.destination_airport || '???'),
        scheduled_time: schedTime.toISOString(),
        estimated_time: null,
        actual_time: (status === 'arrived' || status === 'departed') ? now.toISOString() : null,
        gate: f.assigned_gate || null,
        status,
        delay_minutes: 0,
        aircraft_type: f.aircraft_type || 'A320',
        flight_type: isArrival ? 'arrival' : 'departure',
      };

      if (isArrival) arr.push(entry);
      else dep.push(entry);
    }

    arr.sort((a, b) => a.scheduled_time.localeCompare(b.scheduled_time));
    dep.sort((a, b) => a.scheduled_time.localeCompare(b.scheduled_time));
    return { arrivals: arr, departures: dep };
  }, [trackedFlights, simTime, currentAirport, AIRLINE_NAMES]);

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
                      <div>{formatTime(flight.scheduled_time)}</div>
                      {flight.estimated_time && flight.delay_minutes > 0 && (
                        <div className="text-yellow-400 text-xs">
                          Est: {formatTime(flight.estimated_time)}
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
        <div className="p-3 border-t border-slate-700 text-xs text-slate-500 text-center">
          {flights.length} {activeTab} | Auto-refresh: 15s | Synthetic data for demo
        </div>
      </div>
    </div>
  );
}
