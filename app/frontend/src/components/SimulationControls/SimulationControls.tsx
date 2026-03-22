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

const MAX_LOADABLE_BYTES = 1 * 1024 * 1024 * 1024; // 1 GB

function formatFileSize(sizeBytes: number | undefined, sizeKb: number): string {
  const bytes = sizeBytes ?? sizeKb * 1024;
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(0)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

/** File picker dialog for loading job-generated simulation files. */
function FilePicker({
  files,
  isLoading,
  isFetchingFiles,
  onLoad,
  onClose,
}: {
  files: SimulationFile[];
  isLoading: boolean;
  isFetchingFiles: boolean;
  onLoad: (filename: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-slate-800 rounded-xl shadow-2xl w-[520px] max-h-[480px] overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b dark:border-slate-700">
          <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-200">Load Simulation</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 text-xl leading-none">&times;</button>
        </div>
        <div className="p-5 overflow-y-auto max-h-[380px]">
          {isFetchingFiles ? (
            <div className="flex flex-col items-center justify-center py-8 gap-3">
              <div className="w-8 h-8 border-3 border-blue-500 border-t-transparent rounded-full animate-spin" />
              <p className="text-slate-500 text-sm">Loading simulation files...</p>
            </div>
          ) : files.length === 0 ? (
            <p className="text-slate-500 text-sm">No simulation files available.</p>
          ) : (
            <div className="space-y-2">
              {files.map((f) => {
                const tooLarge = (f.size_bytes ?? f.size_kb * 1024) > MAX_LOADABLE_BYTES;
                return (
                  <button
                    key={f.filename}
                    onClick={() => !tooLarge && onLoad(f.filename)}
                    disabled={isLoading || tooLarge}
                    className={`w-full text-left px-4 py-3 rounded-lg border transition-colors ${
                      tooLarge
                        ? 'border-slate-100 dark:border-slate-700 bg-slate-50 dark:bg-slate-700 opacity-60 cursor-not-allowed'
                        : 'border-slate-200 dark:border-slate-600 hover:border-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/30 disabled:opacity-50'
                    }`}
                    title={tooLarge ? 'Too large for browser playback (>1 GB)' : f.filename}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-slate-800 dark:text-slate-200">
                        {f.scenario_name ? (
                          <>{f.airport} &mdash; {f.scenario_name}</>
                        ) : (
                          <>{f.airport} &mdash; {f.total_flights} flights</>
                        )}
                      </span>
                      <span className={`text-xs ${tooLarge ? 'text-red-400 font-medium' : 'text-slate-400'}`}>
                        {formatFileSize(f.size_bytes, f.size_kb)}
                      </span>
                    </div>
                    <div className="text-xs text-slate-500 mt-1">
                      {f.total_flights} flights &middot; {f.arrivals} arr / {f.departures} dep &middot; {f.duration_hours}h
                      {tooLarge && (
                        <span className="ml-1 text-red-400">&middot; Too large for browser playback</span>
                      )}
                    </div>
                  </button>
                );
              })}
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

const EVENT_LABELS: Record<string, string> = {
  weather: 'Weather',
  runway: 'Runway',
  ground: 'Ground Ops',
  traffic: 'Traffic',
  capacity: 'Capacity',
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

  // Collect unique visible event types for the legend
  const visibleEventTypes = [
    ...new Set(
      sim.scenarioEvents
        .filter((e) => e.event_type !== 'capacity')
        .map((e) => e.event_type)
    ),
  ];

  return (
    <div className="fixed bottom-0 left-0 right-0 z-[1500] bg-slate-900/95 backdrop-blur text-white px-4 py-2 shadow-lg">
      {/* Event legend — only shown when scenario events exist */}
      {visibleEventTypes.length > 0 && (
        <div className="flex items-center gap-3 max-w-screen-xl mx-auto mb-1.5 pl-[136px]">
          <span className="text-[10px] text-slate-500 uppercase tracking-wider">Events</span>
          {visibleEventTypes.map((type) => (
            <div key={type} className="flex items-center gap-1">
              <div className={`w-2 h-2 rounded-sm ${EVENT_COLORS[type] || 'bg-gray-400'}`} />
              <span className="text-[10px] text-slate-400">{EVENT_LABELS[type] || type}</span>
            </div>
          ))}
        </div>
      )}
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

/** Playback bar with "Simulation Paused" overlay when airport switched. */
function PausedBar({
  sim,
  pendingAirport,
  onRestart,
}: {
  sim: UseSimulationReplayResult;
  pendingAirport: string | null;
  onRestart: () => void;
}) {
  return (
    <div className="fixed bottom-0 left-0 right-0 z-[1500] bg-amber-900/95 backdrop-blur text-white px-4 py-3 shadow-lg">
      <div className="flex items-center justify-center gap-4 max-w-screen-xl mx-auto">
        <span className="text-amber-200 font-medium">Simulation Paused</span>
        {pendingAirport && (
          <button
            onClick={onRestart}
            disabled={sim.isLoading}
            className="px-4 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-sm font-medium transition-colors disabled:opacity-50"
          >
            {sim.isLoading ? 'Loading...' : `Start Simulation for ${pendingAirport}`}
          </button>
        )}
        <button
          onClick={sim.stop}
          className="px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-sm transition-colors"
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
 * - A header indicator (demo playing, paused, generating, or start button)
 * - A file picker modal for manual simulation loading
 * - A bottom playback bar during active replay
 * - Auto-starts demo when backend is ready
 * - Pauses demo on airport switch
 *
 * Exposes simulation flights to the parent via onFlightsChange callback.
 */
export function SimulationControls({
  onFlightsChange,
  onActiveChange,
  onAirportChange,
  backendReady,
  currentAirport,
  demoReady,
}: {
  onFlightsChange: (flights: import('../../types/flight').Flight[] | null) => void;
  onActiveChange: (active: boolean) => void;
  onAirportChange?: (icaoCode: string) => Promise<void>;
  backendReady?: boolean;
  currentAirport?: string | null;
  demoReady?: boolean;
}) {
  const sim = useSimulationReplay();
  const [showPicker, setShowPicker] = useState(false);
  const [pendingAirport, setPendingAirport] = useState<string | null>(null);
  const [demoAutoStarted, setDemoAutoStarted] = useState(false);

  // Fetch available files on mount (for manual simulation picker)
  useEffect(() => {
    sim.fetchFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-start demo when backend signals demo_ready
  useEffect(() => {
    if (demoReady && currentAirport && !sim.isActive && !sim.isLoading && !demoAutoStarted) {
      setDemoAutoStarted(true);
      sim.loadDemo(currentAirport);
    }
  }, [demoReady, currentAirport, sim.isActive, sim.isLoading, demoAutoStarted, sim.loadDemo]);

  // Pause demo on airport switch
  useEffect(() => {
    if (!currentAirport) return;
    // If demo is active and airport changed, pause and set pending airport
    if (sim.isActive && currentAirport !== pendingAirport) {
      // Check if the sim airport matches currentAirport (IATA vs ICAO)
      // The sim.airport is IATA (e.g. "SFO"), currentAirport is ICAO (e.g. "KSFO")
      const simAirportIcao = sim.airport && sim.airport.length === 3
        ? `K${sim.airport}`
        : sim.airport;
      if (simAirportIcao !== currentAirport) {
        sim.pauseForSwitch();
        setPendingAirport(currentAirport);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentAirport]);

  // Switch airport when simulation loads a different one (manual file load)
  useEffect(() => {
    if (sim.airport && onAirportChange && currentAirport) {
      // Only switch if the sim airport differs from the current airport
      const simAirportIcao = sim.airport.length === 3
        ? `K${sim.airport}`
        : sim.airport;
      if (simAirportIcao !== currentAirport) {
        onAirportChange(sim.airport).catch((err) => {
          console.warn('Failed to switch airport for simulation:', err);
        });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sim.airport]);

  // Push simulation flights to parent
  useEffect(() => {
    if (sim.isActive && !sim.switchPaused) {
      onFlightsChange(sim.flights);
      onActiveChange(true);
    } else {
      onFlightsChange(null);
      onActiveChange(false);
    }
  }, [sim.isActive, sim.switchPaused, sim.flights, onFlightsChange, onActiveChange]);

  const handleLoad = (filename: string) => {
    setShowPicker(false);
    sim.loadFile(filename, 0, 24);
  };

  const handleDemoRestart = () => {
    if (pendingAirport) {
      setPendingAirport(null);
      sim.loadDemo(pendingAirport);
    }
  };

  // Header button states
  const renderHeaderButton = () => {
    // Demo active & playing
    if (sim.isActive && !sim.switchPaused) {
      return (
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
      );
    }

    // Simulation paused (airport switched)
    if (sim.switchPaused) {
      return (
        <div className="flex items-center gap-2 bg-amber-600 px-3 py-1 rounded-full text-sm">
          <span className="text-amber-100">Simulation Paused</span>
        </div>
      );
    }

    // Demo generating
    if (sim.isLoading || (backendReady && !demoReady && !sim.isActive)) {
      return (
        <div className="flex items-center gap-2 bg-slate-600 px-3 py-1.5 rounded-lg text-sm opacity-80">
          <div className="w-3 h-3 border-2 border-slate-300 border-t-transparent rounded-full animate-spin" />
          <span className="text-slate-300">Preparing Simulation...</span>
        </div>
      );
    }

    // Idle — nothing to show (sim auto-starts when demo is ready)
    return null;
  };

  return (
    <>
      {renderHeaderButton()}

      {/* Load simulation file button — always visible */}
      <button
        onClick={() => {
          sim.fetchFiles();
          setShowPicker(true);
        }}
        className="flex items-center gap-1.5 bg-slate-600 hover:bg-slate-500 px-3 py-1.5 rounded-lg text-sm transition-colors"
        title="Load a simulation file"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
        </svg>
        Simulation
      </button>

      {/* File picker modal */}
      {showPicker && (
        <FilePicker
          files={sim.availableFiles}
          isLoading={sim.isLoading}
          isFetchingFiles={sim.isFetchingFiles}
          onLoad={handleLoad}
          onClose={() => setShowPicker(false)}
        />
      )}

      {/* Playback bar — active demo/sim */}
      {sim.isActive && !sim.switchPaused && <PlaybackBar sim={sim} />}

      {/* Simulation paused bar */}
      {sim.switchPaused && (
        <PausedBar sim={sim} pendingAirport={pendingAirport} onRestart={handleDemoRestart} />
      )}
    </>
  );
}

export default SimulationControls;
