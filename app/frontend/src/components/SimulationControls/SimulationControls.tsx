import { useState, useEffect, useRef } from 'react';
import {
  useSimulationReplay,
  UseSimulationReplayResult,
  PlaybackSpeed,
  SimulationFile,
  SimulationMetadata,
  ScenarioEvent,
  RecordingFile,
} from '../../hooks/useSimulationReplay';
import { useFlightContext } from '../../context/FlightContext';
import type { DataMode } from '../../context/FlightContext';
import { TimeWindowPicker } from './TimeWindowPicker';
import { SceneCapture } from '../SceneCapture/SceneCapture';
import { SimulationReport } from './SimulationReport';

const SPEED_OPTIONS: PlaybackSpeed[] = [0.25, 0.5, 1, 2, 4, 10, 30, 60];

/** Format ISO timestamp to h:MM AM/PM — makes it obvious this is a real-world clock. */
function formatSimTime(iso: string | null): string {
  if (!iso) return '--:--';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('en-US', { hour12: true, hour: 'numeric', minute: '2-digit' });
  } catch {
    return '--:--';
  }
}

/** Format ISO timestamp to short date like "Mar 23". */
function formatSimDate(iso: string | null): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch {
    return '';
  }
}

/** Format elapsed seconds as "Xm Ys". */
function formatElapsed(seconds: number): string {
  if (seconds < 0) return '0s';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  if (m === 0) return `${s}s`;
  return `${m}m ${s}s`;
}

const MAX_LOADABLE_BYTES = 1 * 1024 * 1024 * 1024; // 1 GB

function formatFileSize(sizeBytes: number | undefined, sizeKb: number): string {
  const bytes = sizeBytes ?? sizeKb * 1024;
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(0)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

const LARGE_FILE_THRESHOLD = 100 * 1024 * 1024; // 100 MB — suggest time window

/** File picker dialog for loading job-generated simulation files. */
function FilePicker({
  files,
  isLoading,
  isFetchingFiles,
  onLoad,
  onSelectForWindow,
  onClose,
}: {
  files: SimulationFile[];
  isLoading: boolean;
  isFetchingFiles: boolean;
  onLoad: (filename: string) => void;
  onSelectForWindow: (filename: string) => void;
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
                const sizeBytes = f.size_bytes ?? f.size_kb * 1024;
                const tooLarge = sizeBytes > MAX_LOADABLE_BYTES;
                const isLarge = sizeBytes > LARGE_FILE_THRESHOLD;
                return (
                  <button
                    key={f.filename}
                    onClick={() => {
                      if (tooLarge || isLarge) {
                        onSelectForWindow(f.filename);
                      } else {
                        onLoad(f.filename);
                      }
                    }}
                    disabled={isLoading}
                    className={`w-full text-left px-4 py-3 rounded-lg border transition-colors ${
                      tooLarge
                        ? 'border-amber-200 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 hover:border-amber-400 disabled:opacity-50'
                        : 'border-slate-200 dark:border-slate-600 hover:border-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/30 disabled:opacity-50'
                    }`}
                    title={tooLarge ? 'Large file — select a time window to load' : f.filename}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-slate-800 dark:text-slate-200">
                        {f.scenario_name ? (
                          <>{f.airport} &mdash; {f.scenario_name}</>
                        ) : (
                          <>{f.airport} &mdash; {f.total_flights} flights</>
                        )}
                      </span>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-blue-500 dark:text-blue-400">
                          {f.duration_hours}h
                        </span>
                        <span className={`text-xs ${tooLarge ? 'text-amber-500 font-medium' : isLarge ? 'text-amber-400' : 'text-slate-400'}`}>
                          {formatFileSize(f.size_bytes, f.size_kb)}
                        </span>
                      </div>
                    </div>
                    <div className="text-xs text-slate-500 mt-1">
                      {f.total_flights} flights &middot; {f.arrivals} arr / {f.departures} dep
                      {isLarge && (
                        <span className="ml-1 text-amber-500">&middot; Select time window</span>
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

export const EVENT_COLORS: Record<string, string> = {
  weather: 'bg-amber-400',
  runway: 'bg-red-500',
  ground: 'bg-orange-400',
  traffic: 'bg-blue-400',
  capacity: 'bg-purple-400',
  cancellation: 'bg-rose-400',
  go_around: 'bg-yellow-400',
  diversion: 'bg-cyan-400',
};

export const EVENT_LABELS: Record<string, string> = {
  weather: 'Weather',
  runway: 'Runway',
  ground: 'Ground Ops',
  traffic: 'Traffic',
  capacity: 'Capacity',
  cancellation: 'Cancellations',
  go_around: 'Go-Arounds',
  diversion: 'Diversions',
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

interface EventCluster {
  events: ScenarioEvent[];
  position: number;
}

function clusterEvents(
  events: ScenarioEvent[],
  startTime: string | null,
  endTime: string | null,
  thresholdPct = 1.5,
): EventCluster[] {
  const positioned = events
    .map(e => ({ event: e, pos: getEventPosition(e, startTime, endTime) }))
    .filter((p): p is { event: ScenarioEvent; pos: number } => p.pos !== null)
    .sort((a, b) => a.pos - b.pos);

  const clusters: EventCluster[] = [];
  for (const { event, pos } of positioned) {
    const last = clusters[clusters.length - 1];
    if (last && Math.abs(pos - last.position) < thresholdPct) {
      last.events.push(event);
      last.position = (last.position * (last.events.length - 1) + pos) / last.events.length;
    } else {
      clusters.push({ events: [event], position: pos });
    }
  }
  return clusters;
}

/** Playback control bar shown at the bottom of the screen during simulation replay. */
function PlaybackBar({ sim, isRecorded = false }: { sim: UseSimulationReplayResult; isRecorded?: boolean }) {
  const barRef = useRef<HTMLDivElement>(null);

  // Publish bar height as CSS variable so other panels can add matching bottom padding
  useEffect(() => {
    const el = barRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      document.documentElement.style.setProperty('--playbar-h', `${entry.contentRect.height + 16}px`);
    });
    observer.observe(el);
    return () => {
      observer.disconnect();
      document.documentElement.style.removeProperty('--playbar-h');
    };
  }, []);

  const [showReport, setShowReport] = useState(false);
  const progressPct = sim.totalFrames > 0
    ? (sim.currentFrameIndex / (sim.totalFrames - 1)) * 100
    : 0;

  // Track elapsed real time since playback started
  const playStartRef = useRef<number | null>(null);
  const elapsedBeforePauseRef = useRef(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    if (sim.isPlaying) {
      playStartRef.current = Date.now();
      const tick = setInterval(() => {
        const since = (Date.now() - (playStartRef.current ?? Date.now())) / 1000;
        setElapsedSeconds(elapsedBeforePauseRef.current + since);
      }, 500);
      return () => {
        elapsedBeforePauseRef.current += (Date.now() - (playStartRef.current ?? Date.now())) / 1000;
        clearInterval(tick);
      };
    }
  }, [sim.isPlaying]);

  // Reset elapsed when seeking to start or stopping
  useEffect(() => {
    if (sim.currentFrameIndex === 0) {
      elapsedBeforePauseRef.current = 0;
      setElapsedSeconds(0);
    }
  }, [sim.currentFrameIndex === 0]); // eslint-disable-line react-hooks/exhaustive-deps

  // Collect unique visible event types for the legend
  const visibleEventTypes = [
    ...new Set(
      sim.scenarioEvents
        .filter((e) => e.event_type !== 'capacity')
        .map((e) => e.event_type)
    ),
  ];

  return (
    <div ref={barRef} className={`fixed left-0 right-0 z-[1500] backdrop-blur text-white px-4 py-2 shadow-lg bottom-12 md:bottom-0 ${isRecorded ? 'bg-slate-900/95 border-t-2 border-amber-500/60' : 'bg-slate-900/95'}`}>
      {/* Event legend — hidden on mobile */}
      {visibleEventTypes.length > 0 && (
        <div className="hidden md:flex items-center gap-3 max-w-screen-xl mx-auto mb-1.5 pl-[136px]">
          <span className="text-[10px] text-slate-500 uppercase tracking-wider">Events</span>
          {visibleEventTypes.map((type) => (
            <div key={type} className="flex items-center gap-1">
              <div className={`w-2 h-2 rounded-sm ${EVENT_COLORS[type] || 'bg-gray-400'}`} />
              <span className="text-[10px] text-slate-400">{EVENT_LABELS[type] || type}</span>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2 md:gap-4 max-w-screen-xl mx-auto">
        {/* Play/Pause */}
        <button
          onClick={sim.togglePlayPause}
          className="w-9 h-9 md:w-10 md:h-10 flex items-center justify-center rounded-full bg-blue-600 hover:bg-blue-500 transition-colors flex-shrink-0"
          title={sim.isPlaying ? 'Pause' : 'Play'}
        >
          {sim.isPlaying ? (
            <svg className="w-4 h-4 md:w-5 md:h-5" fill="currentColor" viewBox="0 0 20 20">
              <rect x="5" y="4" width="3" height="12" rx="1" />
              <rect x="12" y="4" width="3" height="12" rx="1" />
            </svg>
          ) : (
            <svg className="w-4 h-4 md:w-5 md:h-5 ml-0.5" fill="currentColor" viewBox="0 0 20 20">
              <polygon points="6,4 16,10 6,16" />
            </svg>
          )}
        </button>

        {/* Sim time + date + elapsed */}
        <div className="flex-shrink-0 text-center min-w-[100px]">
          <div className="text-base md:text-lg font-mono font-bold tracking-tight">
            {formatSimTime(sim.currentSimTime)}
          </div>
          <div className="flex items-center justify-center gap-1.5 -mt-0.5">
            <span className="text-[10px] text-blue-300 font-medium uppercase tracking-wider">Local Time</span>
            <span className="text-[10px] text-slate-600">|</span>
            <span className="text-[10px] text-slate-400">{formatSimDate(sim.currentSimTime)}</span>
            <span className="text-[10px] text-slate-600">|</span>
            <span className="text-[10px] text-slate-500 font-mono">{formatElapsed(elapsedSeconds)}</span>
          </div>
        </div>

        {/* Progress bar — hidden on mobile */}
        <div className="hidden md:block flex-1 relative group cursor-pointer" onClick={(e) => {
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
          {/* Scenario event markers (clustered when overlapping) */}
          {clusterEvents(
            sim.scenarioEvents.filter((e) => e.event_type !== 'capacity'),
            sim.simStartTime,
            sim.simEndTime,
          ).map((cluster, ci) => {
            const mainColor = EVENT_COLORS[cluster.events[0].event_type] || 'bg-gray-400';
            const tooltip = cluster.events.map(e => `${EVENT_LABELS[e.event_type] || e.event_type}: ${e.description}`).join('\n');
            return (
              <div
                key={`cluster-${ci}`}
                className="absolute top-0 -translate-x-1/2 cursor-pointer z-10"
                style={{ left: `${cluster.position}%` }}
                title={tooltip}
                onClick={(e) => {
                  e.stopPropagation();
                  sim.seekToTime(cluster.events[0].time);
                }}
              >
                {cluster.events.length === 1 ? (
                  <div className={`w-1.5 h-3 rounded-sm ${mainColor} opacity-80 hover:opacity-100 hover:scale-150 transition-all`} />
                ) : (
                  <div className="relative">
                    {cluster.events.slice(0, 4).map((evt, j) => {
                      const color = EVENT_COLORS[evt.event_type] || 'bg-gray-400';
                      return (
                        <div
                          key={j}
                          className={`w-1.5 h-3 rounded-sm ${color} opacity-80`}
                          style={{ position: j === 0 ? 'relative' : 'absolute', top: `${j * 4}px`, left: 0 }}
                        />
                      );
                    })}
                    <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-slate-800 text-[8px] text-white font-bold rounded-full w-3.5 h-3.5 flex items-center justify-center ring-1 ring-slate-600">
                      {cluster.events.length}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {/* Frame info tooltip on hover */}
          <div className="absolute -top-6 left-1/2 -translate-x-1/2 text-[10px] text-slate-400 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">
            Frame {sim.currentFrameIndex + 1} / {sim.totalFrames}
          </div>
        </div>

        {/* Speed selector */}
        <div className="flex items-center gap-0.5 md:gap-1 flex-shrink-0 ml-auto md:ml-0 overflow-x-auto">
          {SPEED_OPTIONS.map((s) => (
            <button
              key={s}
              onClick={() => sim.setSpeed(s)}
              className={`px-1.5 md:px-2 py-1 rounded text-xs font-medium transition-colors ${
                sim.speed === s
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
              }`}
            >
              {s === 0.25 ? '¼x' : s === 0.5 ? '½x' : `${s}x`}
            </button>
          ))}
        </div>

        {/* Window navigation — shown when a time window is active */}
        {sim.currentWindow && sim.metadata && (
          <div className="hidden md:flex items-center gap-1 flex-shrink-0">
            <button
              onClick={() => {
                if (!sim.currentWindow || !sim.loadedFile) return;
                const start = new Date(sim.currentWindow.startTime);
                const end = new Date(sim.currentWindow.endTime);
                const windowMs = end.getTime() - start.getTime();
                const newStart = new Date(start.getTime() - windowMs);
                const newEnd = new Date(end.getTime() - windowMs);
                sim.loadWindow(sim.loadedFile, newStart.toISOString(), newEnd.toISOString());
              }}
              className="px-2 py-1 rounded text-xs font-medium bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors"
              title="Load previous time window"
            >
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </button>
            <span className="text-[10px] text-slate-400 px-1">
              {formatSimTime(sim.currentWindow.startTime)}-{formatSimTime(sim.currentWindow.endTime)}
            </span>
            <button
              onClick={() => {
                if (!sim.currentWindow || !sim.loadedFile) return;
                const start = new Date(sim.currentWindow.startTime);
                const end = new Date(sim.currentWindow.endTime);
                const windowMs = end.getTime() - start.getTime();
                const newStart = new Date(start.getTime() + windowMs);
                const newEnd = new Date(end.getTime() + windowMs);
                sim.loadWindow(sim.loadedFile, newStart.toISOString(), newEnd.toISOString());
              }}
              className="px-2 py-1 rounded text-xs font-medium bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors"
              title="Load next time window"
            >
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
          </div>
        )}

        {/* Flight count — hidden on mobile */}
        <div className="hidden md:block flex-shrink-0 text-sm text-slate-400">
          <span className="font-mono font-medium text-white">{sim.flights.length}</span> flights
        </div>

        {/* Scene capture button — hidden on mobile */}
        <div className="hidden md:block flex-shrink-0">
          <SceneCapture airport={sim.airport} simTime={sim.currentSimTime} />
        </div>

        {/* Report generator button — hidden on mobile */}
        <button
          onClick={() => setShowReport(true)}
          className="hidden md:flex flex-shrink-0 px-2 py-1 rounded text-xs font-medium bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors items-center gap-1"
          title="Generate simulation report"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          Report
        </button>

        {/* Stop button — hidden on mobile */}
        <button
          onClick={sim.stop}
          className="hidden md:block flex-shrink-0 px-3 py-1.5 rounded-lg bg-red-600/80 hover:bg-red-600 text-sm transition-colors"
          title="Exit simulation"
        >
          Exit
        </button>
      </div>

      {/* Report modal */}
      {showReport && <SimulationReport sim={sim} onClose={() => setShowReport(false)} />}
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
    <div className="fixed bottom-0 left-0 right-0 z-[1500] bg-amber-900/95 backdrop-blur text-white px-4 py-3 shadow-lg max-md:bottom-12">
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

/** Minimal status bar shown in Live (OpenSky) mode. */
function LiveBar({ flightCount, lastUpdated }: { flightCount: number; lastUpdated: string | null }) {
  const timeStr = lastUpdated
    ? new Date(lastUpdated).toLocaleTimeString('en-US', { hour12: true, hour: 'numeric', minute: '2-digit', second: '2-digit' })
    : '--:--';


  return (
    <div className="fixed left-0 right-0 z-[1500] bg-emerald-900/95 backdrop-blur text-white px-4 py-2 shadow-lg bottom-12 md:bottom-0">
      <div className="flex items-center gap-4 max-w-screen-xl mx-auto">
        {/* Live indicator */}
        <div className="flex items-center gap-2">
          <div className="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse" />
          <span className="text-sm font-semibold uppercase tracking-wider text-emerald-200">Live</span>
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Flight count */}
        <div className="text-sm text-slate-300">
          <span className="font-mono font-medium text-white">{flightCount}</span> aircraft
        </div>

        {/* Last updated */}
        <div className="hidden md:block text-xs text-slate-400">
          Updated {timeStr}
        </div>

        {/* Data source badge */}
        <div className="hidden md:flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-800/60 text-xs text-emerald-300">
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
          OpenSky ADS-B
        </div>
      </div>
    </div>
  );
}

/** Format a date string for display. */
function formatRecordingDate(dateStr: string): string {
  try {
    const d = new Date(dateStr + 'T00:00:00');
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return dateStr;
  }
}

/** Format duration in minutes. */
function formatDuration(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)}min`;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

/** Recording picker dialog for loading recorded OpenSky data. */
function RecordingPicker({
  recordings,
  isLoading,
  isFetching,
  onLoad,
  onClose,
}: {
  recordings: RecordingFile[];
  isLoading: boolean;
  isFetching: boolean;
  onLoad: (airport: string, date: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-slate-800 rounded-xl shadow-2xl w-[560px] max-h-[520px] overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b dark:border-slate-700">
          <div>
            <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-200">Recorded ADS-B Data</h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Real aircraft positions captured from the OpenSky Network
            </p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 text-xl leading-none">&times;</button>
        </div>
        <div className="p-5 overflow-y-auto max-h-[420px]">
          {isFetching ? (
            <div className="flex flex-col items-center justify-center py-8 gap-3">
              <div className="w-8 h-8 border-3 border-amber-500 border-t-transparent rounded-full animate-spin" />
              <p className="text-slate-500 text-sm">Loading recordings from lakehouse...</p>
            </div>
          ) : recordings.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-slate-500 text-sm">No recorded data available.</p>
              <p className="text-slate-400 text-xs mt-2">
                Use <code className="bg-slate-100 dark:bg-slate-700 px-1 rounded">scripts/opensky_collector.py</code> to capture live ADS-B data,
                then upload to the lakehouse.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {recordings.map((r) => (
                <button
                  key={`${r.airport_icao}_${r.date}`}
                  onClick={() => onLoad(r.airport_icao, r.date)}
                  disabled={isLoading}
                  className="w-full text-left px-4 py-3 rounded-lg border border-amber-200 dark:border-amber-700/50 hover:border-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/20 transition-colors disabled:opacity-50"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-slate-800 dark:text-slate-200">
                      {r.airport_icao} &mdash; {formatRecordingDate(r.date)}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-amber-600 dark:text-amber-400">
                        {formatDuration(r.duration_minutes)}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-slate-500 mt-1">
                    <span>{r.aircraft_count} aircraft tracked</span>
                    <span>&middot;</span>
                    <span>{r.state_count.toLocaleString()} position snapshots</span>
                    <span>&middot;</span>
                    <span className="text-amber-500">OpenSky ADS-B</span>
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


/** Toggle button for switching between Simulation, Live, and Recorded data modes. */
export function DataModeToggle({ mode, onChange, showLive = true }: { mode: DataMode; onChange: (mode: DataMode) => void; showLive?: boolean }) {
  return (
    <div className="flex items-center bg-slate-700 rounded-lg p-0.5">
      <button
        onClick={() => onChange('simulation')}
        className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
          mode === 'simulation'
            ? 'bg-indigo-600 text-white shadow-sm'
            : 'text-slate-300 hover:text-white'
        }`}
      >
        Simulation
      </button>
      {showLive && (
        <button
          onClick={() => onChange('live')}
          className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
            mode === 'live'
              ? 'bg-emerald-600 text-white shadow-sm'
              : 'text-slate-300 hover:text-white'
          }`}
        >
          Live
        </button>
      )}
      <button
        onClick={() => onChange('recorded')}
        className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
          mode === 'recorded'
            ? 'bg-amber-600 text-white shadow-sm'
            : 'text-slate-300 hover:text-white'
        }`}
        title="Replay recorded real ADS-B data from OpenSky Network"
      >
        Recorded
      </button>
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
  onTrajectoryProviderChange,
  onFlightLogProviderChange,
  onSimTimeChange,
  backendReady,
  currentAirport,
  demoReady,
}: {
  onFlightsChange: (flights: import('../../types/flight').Flight[] | null) => void;
  onActiveChange: (active: boolean) => void;
  onAirportChange?: (icaoCode: string) => Promise<void>;
  onTrajectoryProviderChange?: (provider: ((icao24: string) => import('../../hooks/useSimulationReplay').SimTrajectoryPoint[]) | null) => void;
  onFlightLogProviderChange?: (provider: ((icao24: string) => import('../../hooks/useSimulationReplay').PositionSnapshot[]) | null) => void;
  onSimTimeChange?: (simTime: string | null) => void;
  backendReady?: boolean;
  currentAirport?: string | null;
  demoReady?: boolean;
}) {
  const sim = useSimulationReplay();
  const { dataMode, flights: contextFlights, lastUpdated: contextLastUpdated } = useFlightContext();
  const [showPicker, setShowPicker] = useState(false);
  const [showWindowPicker, setShowWindowPicker] = useState(false);
  const [windowPickerFile, setWindowPickerFile] = useState<string | null>(null);
  const [windowPickerMetadata, setWindowPickerMetadata] = useState<SimulationMetadata | null>(null);
  const [pendingAirport, setPendingAirport] = useState<string | null>(null);
  const [demoAutoStarted, setDemoAutoStarted] = useState(false);
  const [showRecordingPicker, setShowRecordingPicker] = useState(false);
  const [showBatchReport, setShowBatchReport] = useState(false);
  // Track airport-switching so we push [] (empty) instead of null (WS fallback) to the parent
  const airportSwitchingRef = useRef(false);
  // Track previous airport to detect actual changes (not initial mount)
  const prevAirportRef = useRef(currentAirport);

  // Fetch available files on mount (for manual simulation picker)
  useEffect(() => {
    sim.fetchFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-start demo when backend signals demo_ready (only in simulation mode)
  useEffect(() => {
    if (dataMode !== 'simulation') return;
    if (demoReady && currentAirport && !sim.isActive && !sim.isLoading && !demoAutoStarted) {
      setDemoAutoStarted(true);
      sim.loadDemo(currentAirport);
    }
  }, [demoReady, currentAirport, sim.isActive, sim.isLoading, demoAutoStarted, sim.loadDemo, dataMode]);

  // Reset auto-start flag when airport changes so demo auto-starts for the new airport
  useEffect(() => {
    setDemoAutoStarted(false);
  }, [currentAirport]);

  // Stop simulation on airport switch — clears old flights and allows auto-start for new airport
  useEffect(() => {
    if (!currentAirport) return;
    // Only trigger on actual airport changes, not initial mount
    if (prevAirportRef.current === currentAirport) return;
    prevAirportRef.current = currentAirport;
    if (dataMode !== 'simulation') return;
    if (sim.isActive) {
      airportSwitchingRef.current = true;
      sim.stop();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentAirport]);

  // Switch airport when simulation loads a different one (manual file load)
  useEffect(() => {
    if (sim.airport && onAirportChange && currentAirport) {
      // Skip for demo/recording loads — these are always for the current airport
      if (sim.loadedFile?.startsWith('demo_') || sim.loadedFile?.startsWith('recording_')) return;
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
      airportSwitchingRef.current = false;
      onFlightsChange(sim.flights);
      onActiveChange(true);
    } else if (airportSwitchingRef.current) {
      // Airport switching: push empty array so stale WS flights don't show
      onFlightsChange([]);
      onActiveChange(false);
    } else {
      onFlightsChange(null);
      onActiveChange(false);
    }
  }, [sim.isActive, sim.switchPaused, sim.flights, onFlightsChange, onActiveChange]);

  // Push simulation trajectory provider to parent
  useEffect(() => {
    if (onTrajectoryProviderChange) {
      onTrajectoryProviderChange(sim.isActive && !sim.switchPaused ? sim.getFlightTrajectory : null);
    }
  }, [sim.isActive, sim.switchPaused, sim.getFlightTrajectory, onTrajectoryProviderChange]);

  // Push simulation flight log provider to parent (for CSV export)
  useEffect(() => {
    if (onFlightLogProviderChange) {
      onFlightLogProviderChange(sim.isActive && !sim.switchPaused ? sim.getFlightLog : null);
    }
  }, [sim.isActive, sim.switchPaused, sim.getFlightLog, onFlightLogProviderChange]);

  // Push simulation time to parent (for FIDS alignment)
  useEffect(() => {
    if (onSimTimeChange) {
      onSimTimeChange(sim.isActive && !sim.switchPaused ? sim.currentSimTime : null);
    }
  }, [sim.isActive, sim.switchPaused, sim.currentSimTime, onSimTimeChange]);

  const handleLoad = (filename: string) => {
    setShowPicker(false);
    sim.loadFile(filename, 0, 24);
  };

  const handleSelectForWindow = async (filename: string) => {
    setShowPicker(false);
    setWindowPickerFile(filename);
    setShowWindowPicker(true);
    // Fetch metadata for the time window picker
    const meta = await sim.fetchMetadata(filename);
    setWindowPickerMetadata(meta);
  };

  const handleWindowLoad = async (filename: string, startTime: string, endTime: string) => {
    const isBatch = windowPickerMetadata?.total_frames === 0;
    // Keep modal open while loading — sim.isLoading drives the spinner in TimeWindowPicker
    await sim.loadWindow(filename, startTime, endTime);
    setShowWindowPicker(false);
    setWindowPickerFile(null);
    setWindowPickerMetadata(null);
    if (isBatch) {
      setShowBatchReport(true);
    }
  };

  const handleWindowBack = () => {
    setShowWindowPicker(false);
    setWindowPickerFile(null);
    setWindowPickerMetadata(null);
    setShowPicker(true);
  };

  const handleDemoRestart = () => {
    if (pendingAirport) {
      setPendingAirport(null);
      sim.loadDemo(pendingAirport);
    }
  };

  // Header button states
  const renderHeaderButton = () => {
    // Demo active & playing — PlaybackBar at the bottom already shows time/speed
    if (sim.isActive && !sim.switchPaused) {
      return null;
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

    // Idle — offer restart when demo was previously running
    if (demoAutoStarted && currentAirport && !sim.isLoading) {
      return (
        <button
          onClick={() => sim.loadDemo(currentAirport)}
          className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 px-3 py-1.5 rounded-lg text-sm transition-colors"
          title="Restart simulation"
        >
          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
            <polygon points="6,4 16,10 6,16" />
          </svg>
          Start Simulation
        </button>
      );
    }

    return null;
  };

  // React to dataMode changes (toggle now lives in Header)
  const prevDataMode = useRef(dataMode);
  useEffect(() => {
    if (prevDataMode.current === dataMode) return;
    prevDataMode.current = dataMode;
    if (dataMode !== 'simulation' && sim.isActive) {
      sim.stop();
    }
    if (dataMode === 'recorded') {
      sim.fetchRecordings();
      setShowRecordingPicker(true);
    }
  }, [dataMode, sim]);

  const handleLoadRecording = (airport: string, date: string) => {
    setShowRecordingPicker(false);
    // Switch airport immediately so map updates in parallel with recording fetch
    if (onAirportChange && currentAirport) {
      const icao = airport.length === 3 ? `K${airport}` : airport;
      if (icao !== currentAirport) {
        onAirportChange(airport).catch((err) => {
          console.warn('Failed to switch airport for recording:', err);
        });
      }
    }
    sim.loadRecording(airport, date);
  };

  return (
    <>
      {/* Simulation controls — only in simulation mode */}
      {dataMode === 'simulation' && (
        <>
          {renderHeaderButton()}

          {/* Load simulation file button */}
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
        </>
      )}

      {/* File picker modal */}
      {showPicker && (
        <FilePicker
          files={sim.availableFiles}
          isLoading={sim.isLoading}
          isFetchingFiles={sim.isFetchingFiles}
          onLoad={handleLoad}
          onSelectForWindow={handleSelectForWindow}
          onClose={() => setShowPicker(false)}
        />
      )}

      {/* Time window picker modal */}
      {showWindowPicker && windowPickerFile && (
        windowPickerMetadata ? (
          <TimeWindowPicker
            metadata={windowPickerMetadata}
            filename={windowPickerFile}
            isLoading={sim.isLoading}
            onLoad={handleWindowLoad}
            onBack={handleWindowBack}
          />
        ) : (
          <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/50">
            <div className="bg-white dark:bg-slate-800 rounded-xl shadow-2xl w-[400px] p-8 text-center">
              <div className="w-8 h-8 border-3 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
              <p className="text-slate-500 text-sm">Loading simulation metadata...</p>
              <button
                onClick={handleWindowBack}
                className="mt-4 text-sm text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
              >
                Cancel
              </button>
            </div>
          </div>
        )
      )}

      {/* Batch mode report — auto-shown when loading a file with no position data */}
      {showBatchReport && <SimulationReport sim={sim} onClose={() => setShowBatchReport(false)} />}

      {/* Playback bar — active replay in simulation or recorded mode */}
      {dataMode !== 'live' && sim.isActive && !sim.switchPaused && <PlaybackBar sim={sim} isRecorded={dataMode === 'recorded'} />}

      {/* Simulation paused bar */}
      {dataMode !== 'live' && sim.switchPaused && (
        <PausedBar sim={sim} pendingAirport={pendingAirport} onRestart={handleDemoRestart} />
      )}

      {/* Live status bar — shown in live mode */}
      {dataMode === 'live' && (
        <LiveBar flightCount={contextFlights.length} lastUpdated={contextLastUpdated} />
      )}

      {/* Recorded mode controls */}
      {dataMode === 'recorded' && (
        <>
          {/* Loading indicator while fetching recording data */}
          {sim.isLoading && (
            <div className="flex items-center gap-2 px-3 py-1.5 text-sm text-amber-300">
              <div className="w-4 h-4 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
              Loading recording...
            </div>
          )}

          {/* Load recording button (shown when no recording is playing and not loading) */}
          {!sim.isActive && !sim.isLoading && (
            <button
              onClick={() => {
                sim.fetchRecordings();
                setShowRecordingPicker(true);
              }}
              className="flex items-center gap-1.5 bg-amber-600 hover:bg-amber-500 px-3 py-1.5 rounded-lg text-sm transition-colors"
              title="Load recorded ADS-B data"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
              Load Recording
            </button>
          )}

        </>
      )}

      {/* Recording picker modal */}
      {showRecordingPicker && (
        <RecordingPicker
          recordings={sim.availableRecordings}
          isLoading={sim.isLoading}
          isFetching={sim.isFetchingRecordings}
          onLoad={handleLoadRecording}
          onClose={() => setShowRecordingPicker(false)}
        />
      )}
    </>
  );
}

export default SimulationControls;
