import { useState, useEffect } from 'react';

interface FlightBaggageStats {
  flight_number: string;
  total_bags: number;
  loaded: number;
  unloaded: number;
  on_carousel: number;
  claimed: number;
  delivered: number;
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
      <div className="bg-white dark:bg-slate-800 rounded-lg shadow p-4 animate-pulse">
        <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-1/3 mb-3"></div>
        <div className="h-6 bg-slate-200 dark:bg-slate-700 rounded"></div>
      </div>
    );
  }

  if (error || !stats) {
    return null;
  }

  const hasMisconnects = stats.misconnects > 0;

  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg shadow p-3">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200">Baggage Status</h3>
        {stats.carousel && (
          <span className="px-1.5 py-px bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 rounded text-[10px] font-mono">
            C{stats.carousel}
          </span>
        )}
      </div>

      {/* Progress bar */}
      <div className="mb-2">
        <div className="flex justify-between text-[10px] text-slate-500 dark:text-slate-400 mb-0.5">
          <span>{isArrival ? 'Delivered' : 'Loaded'}</span>
          <span>{stats.loading_progress_pct}%</span>
        </div>
        <div className="h-1.5 bg-slate-200 dark:bg-slate-600 rounded-full overflow-hidden">
          <div
            className={`h-full transition-all duration-500 ${
              hasMisconnects ? 'bg-amber-500' : 'bg-green-500'
            }`}
            style={{ width: `${stats.loading_progress_pct}%` }}
          />
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-1.5 text-center">
        <div className="bg-slate-50 dark:bg-slate-700/50 rounded px-1 py-1.5">
          <div className="text-sm font-bold text-slate-800 dark:text-slate-200">{stats.total_bags}</div>
          <div className="text-[10px] text-slate-500 dark:text-slate-400">Total</div>
        </div>
        <div className="bg-slate-50 dark:bg-slate-700/50 rounded px-1 py-1.5">
          <div className="text-sm font-bold text-green-600 dark:text-green-400">
            {isArrival ? (stats.delivered || stats.claimed || stats.on_carousel || 0) : stats.loaded}
          </div>
          <div className="text-[10px] text-slate-500 dark:text-slate-400">
            {isArrival ? 'Delivered' : 'Loaded'}
          </div>
        </div>
        <div className="bg-slate-50 dark:bg-slate-700/50 rounded px-1 py-1.5">
          <div className="text-sm font-bold text-blue-600 dark:text-blue-400">{stats.connecting_bags}</div>
          <div className="text-[10px] text-slate-500 dark:text-slate-400">Connecting</div>
        </div>
      </div>

      {/* Misconnect alert */}
      {hasMisconnects && (
        <div className="mt-2 p-1.5 bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-700 rounded flex items-center gap-1.5">
          <span className="text-amber-500 dark:text-amber-400 text-xs font-bold">!</span>
          <div>
            <div className="text-[11px] font-medium text-amber-800 dark:text-amber-300">
              {stats.misconnects} bag{stats.misconnects > 1 ? 's' : ''} at risk
            </div>
            <div className="text-[10px] text-amber-600 dark:text-amber-400/70">
              Tight connection time
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
