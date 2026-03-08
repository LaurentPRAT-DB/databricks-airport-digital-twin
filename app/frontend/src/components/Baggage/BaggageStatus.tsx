import { useState, useEffect } from 'react';

interface FlightBaggageStats {
  flight_number: string;
  total_bags: number;
  loaded: number;
  unloaded: number;
  on_carousel: number;
  loading_progress_pct: number;
  connecting_bags: number;
  misconnects: number;
  carousel: number | null;
}

interface BaggageResponse {
  stats: FlightBaggageStats;
}

interface BaggageStatusProps {
  flightNumber: string;
  aircraftType?: string;
  isArrival?: boolean;
}

export default function BaggageStatus({
  flightNumber,
  aircraftType = 'A320',
  isArrival = true,
}: BaggageStatusProps) {
  const [stats, setStats] = useState<FlightBaggageStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchBaggage() {
      try {
        const params = new URLSearchParams({
          aircraft_type: aircraftType,
        });

        const response = await fetch(`/api/baggage/flight/${flightNumber}?${params}`);
        if (!response.ok) throw new Error('Failed to fetch baggage');

        const data: BaggageResponse = await response.json();
        setStats(data.stats);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    }

    if (flightNumber) {
      fetchBaggage();
      // Refresh every 30 seconds
      const interval = setInterval(fetchBaggage, 30 * 1000);
      return () => clearInterval(interval);
    }
  }, [flightNumber, aircraftType]);

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow p-4 animate-pulse">
        <div className="h-4 bg-slate-200 rounded w-1/3 mb-3"></div>
        <div className="h-6 bg-slate-200 rounded"></div>
      </div>
    );
  }

  if (error || !stats) {
    return null;
  }

  const hasMisconnects = stats.misconnects > 0;

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-slate-800">Baggage Status</h3>
        {stats.carousel && (
          <span className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-sm font-mono">
            Carousel {stats.carousel}
          </span>
        )}
      </div>

      {/* Progress bar */}
      <div className="mb-3">
        <div className="flex justify-between text-xs text-slate-500 mb-1">
          <span>{isArrival ? 'Delivered' : 'Loaded'}</span>
          <span>{stats.loading_progress_pct}%</span>
        </div>
        <div className="h-2 bg-slate-200 rounded-full overflow-hidden">
          <div
            className={`h-full transition-all duration-500 ${
              hasMisconnects ? 'bg-yellow-500' : 'bg-green-500'
            }`}
            style={{ width: `${stats.loading_progress_pct}%` }}
          />
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="bg-slate-50 rounded p-2">
          <div className="text-lg font-bold text-slate-800">{stats.total_bags}</div>
          <div className="text-xs text-slate-500">Total</div>
        </div>
        <div className="bg-slate-50 rounded p-2">
          <div className="text-lg font-bold text-slate-800">
            {isArrival ? stats.on_carousel || stats.unloaded : stats.loaded}
          </div>
          <div className="text-xs text-slate-500">
            {isArrival ? 'Delivered' : 'Loaded'}
          </div>
        </div>
        <div className="bg-slate-50 rounded p-2">
          <div className="text-lg font-bold text-blue-600">{stats.connecting_bags}</div>
          <div className="text-xs text-slate-500">Connecting</div>
        </div>
      </div>

      {/* Misconnect alert */}
      {hasMisconnects && (
        <div className="mt-3 p-2 bg-yellow-50 border border-yellow-200 rounded flex items-center gap-2">
          <span className="text-yellow-600 text-lg">!</span>
          <div>
            <div className="text-sm font-medium text-yellow-800">
              {stats.misconnects} bag{stats.misconnects > 1 ? 's' : ''} at risk
            </div>
            <div className="text-xs text-yellow-600">
              Tight connection time
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
