import { useState, useEffect, useMemo } from 'react';
import { useFlightContext } from '../../context/FlightContext';
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
  departed: 'text-slate-500',
  arrived: 'text-slate-500',
  cancelled: 'text-red-400',
};

const STATUS_LABELS: Record<string, string> = {
  on_time: 'On Time',
  scheduled: 'Scheduled',
  delayed: 'Delayed',
  boarding: 'Boarding',
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
}

export default function FIDS({ onClose }: FIDSProps) {
  const [activeTab, setActiveTab] = useState<'arrivals' | 'departures'>('arrivals');
  const [arrivals, setArrivals] = useState<ScheduledFlight[]>([]);
  const [departures, setDepartures] = useState<ScheduledFlight[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Get tracked flights for linking
  const { flights: trackedFlights, setSelectedFlight } = useFlightContext();

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

  useEffect(() => {
    async function fetchSchedule() {
      try {
        setLoading(true);
        const [arrivalsRes, departuresRes] = await Promise.all([
          fetch('/api/schedule/arrivals'),
          fetch('/api/schedule/departures'),
        ]);

        if (!arrivalsRes.ok || !departuresRes.ok) {
          throw new Error('Failed to fetch schedule');
        }

        const arrivalsData: ScheduleResponse = await arrivalsRes.json();
        const departuresData: ScheduleResponse = await departuresRes.json();

        setArrivals(arrivalsData.flights);
        setDepartures(departuresData.flights);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    }

    fetchSchedule();
    // Refresh every minute
    const interval = setInterval(fetchSchedule, 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  const flights = activeTab === 'arrivals' ? arrivals : departures;

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 rounded-lg shadow-2xl w-full max-w-4xl max-h-[80vh] flex flex-col">
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
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white text-2xl font-light"
          >
            x
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto">
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
                  return (
                  <tr
                    key={`${flight.flight_number}-${index}`}
                    className={`text-white hover:bg-slate-800/50 ${
                      isTracked ? 'cursor-pointer hover:bg-blue-900/30' : ''
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
                          <span className="px-1.5 py-0.5 bg-blue-600 text-[10px] rounded uppercase">
                            Live
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-slate-400">{flight.airline}</div>
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
          {flights.length} {activeTab} | Auto-refresh: 1 min | Synthetic data for demo
        </div>
      </div>
    </div>
  );
}
