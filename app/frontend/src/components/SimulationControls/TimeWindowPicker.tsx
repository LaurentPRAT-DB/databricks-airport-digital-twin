import { useState, useEffect, useCallback } from 'react';
import type { SimulationMetadata } from '../../hooks/useSimulationReplay';

const DEFAULT_WINDOW_HOURS = 6;

/** Format a date string like "2026-03-15" to "Mar 15" */
function formatDay(dateStr: string): string {
  try {
    const d = new Date(dateStr + 'T00:00:00');
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch {
    return dateStr;
  }
}

/** Format hour (0-24) to "6:00 AM" style */
function formatHour(hour: number): string {
  const h = Math.floor(hour);
  const m = Math.round((hour - h) * 60);
  const period = h < 12 ? 'AM' : 'PM';
  const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
  return m === 0 ? `${h12}:00 ${period}` : `${h12}:${String(m).padStart(2, '0')} ${period}`;
}

export function TimeWindowPicker({
  metadata,
  filename,
  isLoading,
  onLoad,
  onBack,
}: {
  metadata: SimulationMetadata;
  filename: string;
  isLoading: boolean;
  onLoad: (filename: string, startTime: string, endTime: string) => void;
  onBack: () => void;
}) {
  const days = metadata.days;
  const [selectedDayIndex, setSelectedDayIndex] = useState(0);
  const [startHour, setStartHour] = useState(0);
  const [endHour, setEndHour] = useState(Math.min(DEFAULT_WINDOW_HOURS, 24));

  // Reset time range when day changes
  useEffect(() => {
    setStartHour(0);
    setEndHour(Math.min(DEFAULT_WINDOW_HOURS, 24));
  }, [selectedDayIndex]);

  // Compute absolute ISO times from selected day + hour range
  const getAbsoluteTimes = useCallback((): { startTime: string; endTime: string } => {
    const dayStr = days[selectedDayIndex] || days[0];
    const baseDate = new Date(dayStr + 'T00:00:00Z');
    const start = new Date(baseDate.getTime() + startHour * 3600_000);
    const end = new Date(baseDate.getTime() + endHour * 3600_000);
    return {
      startTime: start.toISOString(),
      endTime: end.toISOString(),
    };
  }, [days, selectedDayIndex, startHour, endHour]);

  // Estimate frames and data size for the selected window
  const windowHours = endHour - startHour;
  const estimatedFrames = Math.round(metadata.estimated_frames_per_hour * windowHours);
  const estimatedSizeMB = metadata.total_snapshots > 0 && metadata.total_frames > 0
    ? Math.round((estimatedFrames / metadata.total_frames) * (metadata.total_snapshots * 200) / (1024 * 1024))
    : 0;

  const handleLoad = () => {
    const { startTime, endTime } = getAbsoluteTimes();
    onLoad(filename, startTime, endTime);
  };

  // Handle range slider drag
  const handleStartChange = (value: number) => {
    const clamped = Math.min(value, endHour - 1);
    setStartHour(Math.max(0, clamped));
  };

  const handleEndChange = (value: number) => {
    const clamped = Math.max(value, startHour + 1);
    setEndHour(Math.min(24, clamped));
  };

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-slate-800 rounded-xl shadow-2xl w-[520px] max-h-[560px] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b dark:border-slate-700">
          <div className="flex items-center gap-2">
            <button
              onClick={onBack}
              className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
              title="Back to file list"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </button>
            <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-200">Select Time Window</h3>
          </div>
          <button onClick={onBack} className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 text-xl leading-none">&times;</button>
        </div>

        <div className="p-5 space-y-5">
          {/* Simulation info */}
          <div className="text-sm text-slate-500 dark:text-slate-400">
            <span className="font-medium text-slate-700 dark:text-slate-300">
              {(metadata.config as Record<string, unknown>)?.airport as string || '?'}
            </span>
            {' '}&middot; {metadata.duration_hours}h &middot; {metadata.total_frames} frames &middot;{' '}
            {(metadata.summary as Record<string, unknown>)?.total_flights as number || '?'} flights
          </div>

          {/* Day selector — only show when multi-day */}
          {days.length > 1 && (
            <div>
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-2 uppercase tracking-wider">
                Day
              </label>
              <div className="flex gap-1.5 flex-wrap">
                {days.map((day, i) => (
                  <button
                    key={day}
                    onClick={() => setSelectedDayIndex(i)}
                    className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                      selectedDayIndex === i
                        ? 'bg-blue-600 text-white'
                        : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600'
                    }`}
                  >
                    {formatDay(day)}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Time range */}
          <div>
            <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-2 uppercase tracking-wider">
              Time Range
            </label>
            <div className="flex items-center gap-3 mb-2">
              <span className="text-sm font-mono font-medium text-slate-700 dark:text-slate-300 min-w-[80px]">
                {formatHour(startHour)}
              </span>
              <span className="text-slate-400">to</span>
              <span className="text-sm font-mono font-medium text-slate-700 dark:text-slate-300 min-w-[80px]">
                {formatHour(endHour)}
              </span>
              <span className="text-xs text-slate-400 ml-auto">
                {windowHours}h window
              </span>
            </div>
            {/* Dual range sliders */}
            <div className="relative h-8">
              {/* Track background */}
              <div className="absolute top-3 left-0 right-0 h-2 bg-slate-200 dark:bg-slate-600 rounded-full" />
              {/* Active range */}
              <div
                className="absolute top-3 h-2 bg-blue-500 rounded-full"
                style={{
                  left: `${(startHour / 24) * 100}%`,
                  right: `${100 - (endHour / 24) * 100}%`,
                }}
              />
              {/* Start handle */}
              <input
                type="range"
                min={0}
                max={24}
                step={1}
                value={startHour}
                onChange={(e) => handleStartChange(Number(e.target.value))}
                className="absolute top-0 left-0 w-full h-8 appearance-none bg-transparent pointer-events-none [&::-webkit-slider-thumb]:pointer-events-auto [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-blue-600 [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-white [&::-webkit-slider-thumb]:shadow [&::-webkit-slider-thumb]:cursor-pointer [&::-moz-range-thumb]:pointer-events-auto [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-blue-600 [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-white [&::-moz-range-thumb]:shadow [&::-moz-range-thumb]:cursor-pointer"
              />
              {/* End handle */}
              <input
                type="range"
                min={0}
                max={24}
                step={1}
                value={endHour}
                onChange={(e) => handleEndChange(Number(e.target.value))}
                className="absolute top-0 left-0 w-full h-8 appearance-none bg-transparent pointer-events-none [&::-webkit-slider-thumb]:pointer-events-auto [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-blue-600 [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-white [&::-webkit-slider-thumb]:shadow [&::-webkit-slider-thumb]:cursor-pointer [&::-moz-range-thumb]:pointer-events-auto [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-blue-600 [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-white [&::-moz-range-thumb]:shadow [&::-moz-range-thumb]:cursor-pointer"
              />
            </div>
            {/* Hour labels */}
            <div className="flex justify-between text-[10px] text-slate-400 mt-1 px-0.5">
              <span>0:00</span>
              <span>6:00</span>
              <span>12:00</span>
              <span>18:00</span>
              <span>24:00</span>
            </div>
          </div>

          {/* Estimate */}
          <div className="bg-slate-50 dark:bg-slate-700/50 rounded-lg px-4 py-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-500 dark:text-slate-400">Estimated load</span>
              <span className="font-medium text-slate-700 dark:text-slate-300">
                ~{estimatedFrames.toLocaleString()} frames
                {estimatedSizeMB > 0 && ` (~${estimatedSizeMB} MB)`}
              </span>
            </div>
          </div>

          {/* Quick presets */}
          <div className="flex gap-2">
            <span className="text-xs text-slate-400 self-center">Quick:</span>
            {[
              { label: 'Morning', start: 6, end: 12 },
              { label: 'Afternoon', start: 12, end: 18 },
              { label: 'Evening', start: 18, end: 24 },
              { label: 'Full Day', start: 0, end: 24 },
            ].map(({ label, start, end }) => (
              <button
                key={label}
                onClick={() => { setStartHour(start); setEndHour(end); }}
                className="px-2.5 py-1 rounded text-xs font-medium bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
              >
                {label}
              </button>
            ))}
          </div>

          {/* Load button */}
          <button
            onClick={handleLoad}
            disabled={isLoading || windowHours <= 0}
            className="w-full py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLoading ? (
              <span className="flex items-center justify-center gap-2">
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Loading...
              </span>
            ) : (
              `Load ${days.length > 1 ? formatDay(days[selectedDayIndex]) + ' ' : ''}${formatHour(startHour)} - ${formatHour(endHour)}`
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
