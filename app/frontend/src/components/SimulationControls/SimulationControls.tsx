import { useState, useEffect } from 'react';
import {
  useSimulationReplay,
  UseSimulationReplayResult,
  PlaybackSpeed,
  SimulationFile,
  ScenarioEvent,
} from '../../hooks/useSimulationReplay';

const SPEED_OPTIONS: PlaybackSpeed[] = [1, 2, 5, 10, 30, 60];

/** Format ISO timestamp to short time display. */
function formatSimTime(iso: string | null): string {
  if (!iso) return '--:--:--';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('en-US', { hour12: false });
  } catch {
    return '--:--:--';
  }
}

/** File picker dialog shown when simulation mode is not active. */
function FilePicker({
  files,
  isLoading,
  onLoad,
  onClose,
}: {
  files: SimulationFile[];
  isLoading: boolean;
  onLoad: (filename: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-xl shadow-2xl w-[480px] max-h-[400px] overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <h3 className="text-lg font-semibold text-slate-800">Load Simulation</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-xl leading-none">&times;</button>
        </div>
        <div className="p-5 overflow-y-auto max-h-[300px]">
          {files.length === 0 ? (
            <p className="text-slate-500 text-sm">
              No simulation files found. Run a simulation first:
              <code className="block mt-2 bg-slate-100 p-2 rounded text-xs">
                python -m src.simulation.cli --config configs/simulation_sfo_50.yaml
              </code>
            </p>
          ) : (
            <div className="space-y-2">
              {files.map((f) => (
                <button
                  key={f.filename}
                  onClick={() => onLoad(f.filename)}
                  disabled={isLoading}
                  className="w-full text-left px-4 py-3 rounded-lg border border-slate-200 hover:border-blue-400 hover:bg-blue-50 transition-colors disabled:opacity-50"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-slate-800">
                      {f.airport} &mdash; {f.total_flights} flights
                    </span>
                    <span className="text-xs text-slate-400">{f.size_kb} KB</span>
                  </div>
                  <div className="text-xs text-slate-500 mt-1">
                    {f.arrivals} arr / {f.departures} dep &middot; {f.duration_hours}h &middot; {f.filename}
                    {f.scenario_name && (
                      <span className="ml-1 text-amber-600">
                        &middot; {f.scenario_name}
                      </span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const EVENT_COLORS: Record<string, string> = {
  weather: 'bg-amber-400',
  runway: 'bg-red-500',
  ground: 'bg-orange-400',
  traffic: 'bg-blue-400',
  capacity: 'bg-purple-400',
};

function getEventPosition(event: ScenarioEvent, startTime: string | null, endTime: string | null): number | null {
  if (!startTime || !endTime) return null;
  const first = new Date(startTime).getTime();
  const last = new Date(endTime).getTime();
  const range = last - first;
  if (range <= 0) return null;
  const eventTime = new Date(event.time).getTime();
  const pct = ((eventTime - first) / range) * 100;
  return Math.max(0, Math.min(100, pct));
}

/** Playback control bar shown at the bottom of the screen during simulation replay. */
function PlaybackBar({ sim }: { sim: UseSimulationReplayResult }) {
  const progressPct = sim.totalFrames > 0
    ? (sim.currentFrameIndex / (sim.totalFrames - 1)) * 100
    : 0;

  return (
    <div className="fixed bottom-0 left-0 right-0 z-[1500] bg-slate-900/95 backdrop-blur text-white px-4 py-2 shadow-lg">
      <div className="flex items-center gap-4 max-w-screen-xl mx-auto">
        {/* Play/Pause */}
        <button
          onClick={sim.togglePlayPause}
          className="w-10 h-10 flex items-center justify-center rounded-full bg-blue-600 hover:bg-blue-500 transition-colors flex-shrink-0"
          title={sim.isPlaying ? 'Pause' : 'Play'}
        >
          {sim.isPlaying ? (
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
              <rect x="5" y="4" width="3" height="12" rx="1" />
              <rect x="12" y="4" width="3" height="12" rx="1" />
            </svg>
          ) : (
            <svg className="w-5 h-5 ml-0.5" fill="currentColor" viewBox="0 0 20 20">
              <polygon points="6,4 16,10 6,16" />
            </svg>
          )}
        </button>

        {/* Sim time */}
        <div className="flex-shrink-0 w-24 text-center">
          <div className="text-lg font-mono font-bold tracking-tight">
            {formatSimTime(sim.currentSimTime)}
          </div>
          <div className="text-[10px] text-slate-400 -mt-0.5">SIM TIME</div>
        </div>

        {/* Progress bar with scenario event markers */}
        <div className="flex-1 relative group cursor-pointer" onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const pct = ((e.clientX - rect.left) / rect.width) * 100;
          sim.seekToPercent(pct);
        }}>
          <div className="h-2 bg-slate-700 rounded-full overflow-hidden relative">
            <div
              className="h-full bg-blue-500 rounded-full transition-[width] duration-100"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          {/* Scenario event markers */}
          {sim.scenarioEvents
            .filter((e) => e.event_type !== 'capacity')
            .map((event, i) => {
              const pos = getEventPosition(event, sim.simStartTime, sim.simEndTime);
              if (pos === null) return null;
              const colorClass = EVENT_COLORS[event.event_type] || 'bg-gray-400';
              return (
                <div
                  key={`${event.time}-${i}`}
                  className="absolute top-0 -translate-x-1/2"
                  style={{ left: `${pos}%` }}
                  title={`${event.event_type}: ${event.description}`}
                >
                  <div className={`w-1.5 h-3 rounded-sm ${colorClass} opacity-80 hover:opacity-100 transition-opacity`} />
                </div>
              );
            })}
          {/* Frame info tooltip on hover */}
          <div className="absolute -top-6 left-1/2 -translate-x-1/2 text-[10px] text-slate-400 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">
            Frame {sim.currentFrameIndex + 1} / {sim.totalFrames}
          </div>
        </div>

        {/* Speed selector */}
        <div className="flex items-center gap-1 flex-shrink-0">
          {SPEED_OPTIONS.map((s) => (
            <button
              key={s}
              onClick={() => sim.setSpeed(s)}
              className={`px-2 py-1 rounded text-xs font-medium transition-colors ${
                sim.speed === s
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
              }`}
            >
              {s}x
            </button>
          ))}
        </div>

        {/* Flight count */}
        <div className="flex-shrink-0 text-sm text-slate-400">
          <span className="font-mono font-medium text-white">{sim.flights.length}</span> flights
        </div>

        {/* Stop button */}
        <button
          onClick={sim.stop}
          className="flex-shrink-0 px-3 py-1.5 rounded-lg bg-red-600/80 hover:bg-red-600 text-sm transition-colors"
          title="Exit simulation"
        >
          Exit
        </button>
      </div>
    </div>
  );
}

/**
 * SimulationControls — manages the full simulation replay lifecycle.
 *
 * Renders:
 * - A "Simulation" button in the header area (via headerButton)
 * - A file picker modal when clicked
 * - A bottom playback bar during active replay
 *
 * Exposes simulation flights to the parent via onFlightsChange callback.
 */
export function SimulationControls({
  onFlightsChange,
  onActiveChange,
}: {
  onFlightsChange: (flights: import('../../types/flight').Flight[] | null) => void;
  onActiveChange: (active: boolean) => void;
}) {
  const sim = useSimulationReplay();
  const [showPicker, setShowPicker] = useState(false);

  // Fetch available files on mount
  useEffect(() => {
    sim.fetchFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Push simulation flights to parent
  useEffect(() => {
    if (sim.isActive) {
      onFlightsChange(sim.flights);
      onActiveChange(true);
    } else {
      onFlightsChange(null);
      onActiveChange(false);
    }
  }, [sim.isActive, sim.flights, onFlightsChange, onActiveChange]);

  const handleLoad = (filename: string) => {
    setShowPicker(false);
    sim.loadFile(filename, 0, 24);
  };

  return (
    <>
      {/* Header button */}
      {!sim.isActive && (
        <button
          onClick={() => setShowPicker(true)}
          className="flex items-center gap-1.5 bg-indigo-600 hover:bg-indigo-500 px-3 py-1.5 rounded-lg text-sm transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          Simulation
        </button>
      )}

      {/* Active simulation indicator in header */}
      {sim.isActive && (
        <div className="flex items-center gap-2 bg-indigo-600/80 px-3 py-1 rounded-full text-sm">
          <span className="w-2 h-2 rounded-full bg-indigo-300 animate-pulse" />
          <span>SIM: {formatSimTime(sim.currentSimTime)}</span>
          <span className="text-indigo-200">{sim.speed}x</span>
          {sim.scenarioName && (
            <span className="text-amber-200 text-xs truncate max-w-[120px]" title={sim.scenarioName}>
              {sim.scenarioName}
            </span>
          )}
        </div>
      )}

      {/* File picker modal */}
      {showPicker && (
        <FilePicker
          files={sim.availableFiles}
          isLoading={sim.isLoading}
          onLoad={handleLoad}
          onClose={() => setShowPicker(false)}
        />
      )}

      {/* Playback bar */}
      {sim.isActive && <PlaybackBar sim={sim} />}
    </>
  );
}

export default SimulationControls;
