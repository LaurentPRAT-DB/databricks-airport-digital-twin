import { useState, useEffect } from 'react';

interface GSEUnit {
  unit_id: string;
  gse_type: string;
  status: string;
}

interface TurnaroundStatus {
  icao24: string;
  flight_number: string | null;
  gate: string;
  current_phase: string;
  phase_progress_pct: number;
  total_progress_pct: number;
  estimated_departure: string;
  assigned_gse: GSEUnit[];
  aircraft_type: string;
}

interface TurnaroundResponse {
  turnaround: TurnaroundStatus;
}

const PHASE_LABELS: Record<string, string> = {
  arrival_taxi: 'Arrival Taxi',
  chocks_on: 'Chocks On',
  deboarding: 'Deboarding',
  unloading: 'Unloading',
  cleaning: 'Cleaning',
  catering: 'Catering',
  refueling: 'Refueling',
  loading: 'Loading',
  boarding: 'Boarding',
  chocks_off: 'Chocks Off',
  pushback: 'Pushback',
  departure_taxi: 'Departure',
  complete: 'Complete',
};

const PHASE_ORDER = [
  'arrival_taxi',
  'chocks_on',
  'deboarding',
  'cleaning',
  'refueling',
  'boarding',
  'pushback',
];

interface TurnaroundTimelineProps {
  icao24: string;
  gate?: string;
  aircraftType?: string;
}

export default function TurnaroundTimeline({
  icao24,
  gate,
  aircraftType = 'A320',
}: TurnaroundTimelineProps) {
  const [turnaround, setTurnaround] = useState<TurnaroundStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPhase, setSelectedPhase] = useState<string | null>(null);

  useEffect(() => {
    async function fetchTurnaround() {
      try {
        const params = new URLSearchParams({
          aircraft_type: aircraftType,
        });
        if (gate) params.append('gate', gate);

        const response = await fetch(`/api/turnaround/${icao24}?${params}`);
        if (!response.ok) throw new Error('Failed to fetch turnaround');

        const data: TurnaroundResponse = await response.json();
        setTurnaround(data.turnaround);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    }

    fetchTurnaround();
    // Refresh every 30 seconds
    const interval = setInterval(fetchTurnaround, 30 * 1000);
    return () => clearInterval(interval);
  }, [icao24, gate, aircraftType]);

  if (loading) {
    return (
      <div className="bg-white dark:bg-slate-800 rounded-lg shadow p-4 animate-pulse">
        <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-1/2 mb-3"></div>
        <div className="h-8 bg-slate-200 dark:bg-slate-700 rounded"></div>
      </div>
    );
  }

  if (error || !turnaround) {
    return null; // Silently hide if not at gate
  }

  const currentPhaseIndex = PHASE_ORDER.indexOf(turnaround.current_phase);
  const estDeparture = new Date(turnaround.estimated_departure);

  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg shadow p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-slate-800 dark:text-slate-200">Turnaround Progress</h3>
        <span className="text-sm text-slate-500 dark:text-slate-400">
          Gate {turnaround.gate}
        </span>
      </div>

      {/* Progress bar */}
      <div className="mb-4">
        <div className="flex justify-between text-xs text-slate-500 dark:text-slate-400 mb-1">
          <span>{PHASE_LABELS[turnaround.current_phase] || turnaround.current_phase}</span>
          <span>{turnaround.total_progress_pct}%</span>
        </div>
        <div className="h-3 bg-slate-200 dark:bg-slate-600 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 transition-all duration-500"
            style={{ width: `${turnaround.total_progress_pct}%` }}
          />
        </div>
      </div>

      {/* Phase indicators */}
      {selectedPhase && (
        <div className="text-xs text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-700 rounded px-2 py-1 mb-2 flex justify-between items-center">
          <span>
            <span className="font-medium">{PHASE_LABELS[selectedPhase]}</span>
            {' — '}
            {PHASE_ORDER.indexOf(selectedPhase) < currentPhaseIndex
              ? 'Completed'
              : selectedPhase === turnaround.current_phase
              ? `In progress (${turnaround.phase_progress_pct}%)`
              : 'Pending'}
          </span>
          <button
            onClick={() => setSelectedPhase(null)}
            className="text-slate-400 hover:text-slate-600 ml-2"
          >
            ✕
          </button>
        </div>
      )}
      <div className="flex items-center mb-4">
        {PHASE_ORDER.map((phase, idx) => {
          const isCompleted = idx < currentPhaseIndex;
          const isCurrent = phase === turnaround.current_phase;
          const isSelected = selectedPhase === phase;

          return (
            <div
              key={phase}
              className="flex flex-col items-center flex-1 min-w-0 cursor-pointer group"
              onClick={() => setSelectedPhase(prev => prev === phase ? null : phase)}
            >
              <div
                className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] shrink-0 transition-transform ${
                  isCompleted
                    ? 'bg-green-500 text-white'
                    : isCurrent
                    ? 'bg-blue-500 text-white animate-pulse'
                    : 'bg-slate-200 dark:bg-slate-600 text-slate-400'
                } ${isSelected ? 'ring-2 ring-blue-300 scale-110' : 'group-hover:scale-110'}`}
              >
                {isCompleted ? '✓' : idx + 1}
              </div>
            </div>
          );
        })}
      </div>

      {/* EST departure */}
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-500 dark:text-slate-400">Est. Departure</span>
        <span className="font-mono font-medium">
          {estDeparture.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </span>
      </div>

      {/* Active GSE */}
      {turnaround.assigned_gse.filter(g => g.status === 'servicing').length > 0 && (
        <div className="mt-3 pt-3 border-t">
          <div className="text-xs text-slate-500 dark:text-slate-400 mb-2">Active Equipment</div>
          <div className="flex flex-wrap gap-1">
            {turnaround.assigned_gse
              .filter(g => g.status === 'servicing')
              .map(gse => (
                <span
                  key={gse.unit_id}
                  className="px-2 py-0.5 bg-slate-100 dark:bg-slate-700 rounded text-xs text-slate-600 dark:text-slate-300"
                >
                  {gse.gse_type.replace('_', ' ')}
                </span>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
