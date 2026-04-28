import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { UseSimulationReplayResult } from '../../hooks/useSimulationReplay';
import { useFlightContext } from '../../context/FlightContext';
import { downloadDataUrl } from '../../utils/sceneCapture';
import { EVENT_COLORS, EVENT_LABELS } from './SimulationControls';

type ReportTab = 'dashboard' | 'analysis';

interface SimulationReportProps {
  sim: UseSimulationReplayResult;
  onClose: () => void;
}

/** Hex colors for HTML report (matching Tailwind classes). */
const EVENT_HEX: Record<string, string> = {
  weather: '#fbbf24',
  runway: '#ef4444',
  ground: '#fb923c',
  traffic: '#60a5fa',
  capacity: '#a78bfa',
  cancellation: '#fb7185',
  go_around: '#facc15',
  diversion: '#22d3ee',
};

/** Format ISO to readable time. */
function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  } catch {
    return iso;
  }
}

/** Format ISO to readable date+time. */
function fmtDateTime(iso: string | null): string {
  if (!iso) return '--';
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short', day: 'numeric', year: 'numeric',
      hour: 'numeric', minute: '2-digit', hour12: true,
    });
  } catch {
    return iso;
  }
}

/** Get UTC hour from ISO string — avoids local-timezone shifts that break filtering. */
function getHour(iso: string): number {
  try { return new Date(iso).getUTCHours(); } catch { return 0; }
}

/** Extract a callsign from an event description (e.g. "KLM214 diverted to alternate" → "KLM214"). */
function extractCallsign(description: string): string | null {
  const match = description.match(/^([A-Z]{2,4}\d{1,5})\b/);
  return match ? match[1] : null;
}

interface EventTypeDropdownProps {
  allTypes: string[];
  selectedTypes: Set<string>;
  events: { event_type: string; time: string }[];
  fromHour: number;
  toHour: number;
  onToggle: (type: string) => void;
  onSelectAll: () => void;
  onClearAll: () => void;
}

function EventTypeDropdown({ allTypes, selectedTypes, events, fromHour, toHour, onToggle, onSelectAll, onClearAll }: EventTypeDropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const selectedCount = allTypes.filter(t => selectedTypes.has(t)).length;
  const label = selectedCount === allTypes.length
    ? 'All types'
    : selectedCount === 0
    ? 'No types'
    : `${selectedCount} of ${allTypes.length} types`;

  return (
    <div ref={ref} className="relative flex-shrink-0">
      <span className="text-xs text-slate-500 font-medium uppercase tracking-wider block mb-1">Event Types</span>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-3 py-1.5 bg-white border border-slate-300 rounded text-xs text-slate-700 hover:border-slate-400 transition-colors min-w-[160px]"
      >
        <span className="flex-1 text-left">{label}</span>
        <svg className={`w-3 h-3 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="absolute bottom-full left-0 mb-1 bg-white border border-slate-200 rounded-lg shadow-lg z-50 min-w-[200px] py-1">
          <div className="flex items-center gap-2 px-3 py-1.5 border-b border-slate-100">
            <button onClick={onSelectAll} className="text-[10px] text-blue-600 hover:text-blue-500">All</button>
            <button onClick={onClearAll} className="text-[10px] text-blue-600 hover:text-blue-500">None</button>
          </div>
          <div className="max-h-[240px] overflow-y-auto">
          {allTypes.map(type => {
            const count = events.filter(e => {
              if (e.event_type !== type) return false;
              const h = getHour(e.time);
              return h >= fromHour && h < toHour;
            }).length;
            return (
              <button
                key={type}
                onClick={() => onToggle(type)}
                className="flex items-center gap-2 w-full px-3 py-1.5 text-xs hover:bg-slate-50 transition-colors"
              >
                <div className={`w-3.5 h-3.5 rounded border flex items-center justify-center ${
                  selectedTypes.has(type) ? 'bg-blue-600 border-blue-600' : 'border-slate-300'
                }`}>
                  {selectedTypes.has(type) && (
                    <svg className="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                </div>
                <span className={`w-2 h-2 rounded-sm flex-shrink-0 ${EVENT_COLORS[type] || 'bg-gray-400'}`} />
                <span className="text-slate-700 flex-1 text-left">{EVENT_LABELS[type] || type}</span>
                <span className="text-slate-400 text-[10px]">{count}</span>
              </button>
            );
          })}
          </div>
        </div>
      )}
    </div>
  );
}

export function SimulationReport({ sim, onClose }: SimulationReportProps) {
  const [fullscreen, setFullscreen] = useState(false);
  const { filteredFlights, setSelectedFlight } = useFlightContext();

  // Handle clicking an event row — seek to event time, select matching flight, close report
  const handleEventClick = useCallback((eventTime: string, description: string) => {
    // Seek simulation to event time
    sim.seekToTime(eventTime);

    // Try to find and select the matching flight by callsign
    const callsign = extractCallsign(description);
    if (callsign) {
      const flight = filteredFlights.find(
        f => f.callsign?.replace(/\s+/g, '') === callsign
      );
      if (flight) {
        setSelectedFlight(flight);
      }
    }

    onClose();
  }, [sim, filteredFlights, setSelectedFlight, onClose]);

  // All unique event types present in the data
  const allEventTypes = useMemo(() => {
    const types = new Set(sim.scenarioEvents.map(e => e.event_type));
    return [...types].sort();
  }, [sim.scenarioEvents]);

  // Selected event types (default: all except capacity)
  const [selectedTypes, setSelectedTypes] = useState<Set<string>>(() => {
    const initial = new Set(allEventTypes);
    initial.delete('capacity');
    return initial;
  });

  // Sync selectedTypes when allEventTypes changes (handles late-arriving events)
  const allEventTypesKey = allEventTypes.join(',');
  useEffect(() => {
    setSelectedTypes(prev => {
      if (prev.size === 0 && allEventTypes.length > 0) {
        const next = new Set(allEventTypes);
        next.delete('capacity');
        return next;
      }
      return prev;
    });
  }, [allEventTypesKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Time range filter (hours)
  const startHour = sim.simStartTime ? getHour(sim.simStartTime) : 0;
  const endHour = sim.simEndTime ? getHour(sim.simEndTime) : 24;
  const [fromHour, setFromHour] = useState(startHour);
  const [toHour, setToHour] = useState(endHour === 0 ? 24 : endHour);

  // Grouping mode
  const [groupBy, setGroupBy] = useState<'time' | 'category' | 'flight'>('time');

  // Expanded flight groups (for flight grouping mode)
  const [expandedFlights, setExpandedFlights] = useState<Set<string>>(new Set());


  // Report tab (Dashboard vs Analysis Report)
  const [activeTab, setActiveTab] = useState<ReportTab>('dashboard');
  const hasAnalysisReport = sim.markdownReport != null;

  // Stable key for selectedTypes so useMemo dependencies use a primitive
  const selectedTypesKey = [...selectedTypes].sort().join(',');

  // Time-range-filtered event counts (for KPI cards — matches dropdown counts)
  const timeFilteredCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const e of sim.scenarioEvents) {
      const h = getHour(e.time);
      if (h >= fromHour && h < toHour) {
        counts[e.event_type] = (counts[e.event_type] ?? 0) + 1;
      }
    }
    return counts;
  }, [sim.scenarioEvents, fromHour, toHour]);

  // Filter events
  const filteredEvents = useMemo(() => {
    return sim.scenarioEvents.filter(e => {
      if (!selectedTypes.has(e.event_type)) return false;
      const hour = getHour(e.time);
      if (hour < fromHour || hour >= toHour) return false;
      return true;
    }).sort((a, b) => {
      if (groupBy === 'category') {
        const cmp = a.event_type.localeCompare(b.event_type);
        if (cmp !== 0) return cmp;
      }
      if (groupBy === 'flight') {
        const csA = extractCallsign(a.description) ?? '';
        const csB = extractCallsign(b.description) ?? '';
        const cmp = csA.localeCompare(csB);
        if (cmp !== 0) return cmp;
      }
      return new Date(a.time).getTime() - new Date(b.time).getTime();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sim.scenarioEvents, selectedTypesKey, fromHour, toHour, groupBy]);

  // Group events by flight callsign (for flight grouping mode)
  const flightGroups = useMemo(() => {
    if (groupBy !== 'flight') return null;
    const groups: { callsign: string; events: typeof filteredEvents }[] = [];
    const map = new Map<string, typeof filteredEvents>();
    for (const e of filteredEvents) {
      const cs = extractCallsign(e.description) ?? '(no callsign)';
      if (!map.has(cs)) {
        map.set(cs, []);
        groups.push({ callsign: cs, events: map.get(cs)! });
      }
      map.get(cs)!.push(e);
    }
    return groups;
  }, [filteredEvents, groupBy]);

  // Toggle event type
  const toggleType = useCallback((type: string) => {
    setSelectedTypes(prev => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }, []);

  // Select/clear all
  const selectAll = useCallback(() => setSelectedTypes(new Set(allEventTypes)), [allEventTypes]);
  const clearAll = useCallback(() => setSelectedTypes(new Set()), []);


  // Summary data
  const summary = sim.summary as Record<string, unknown> | null;

  // Generate and download HTML report
  const downloadReport = useCallback(() => {
    const kpis = [
      { label: 'On-Time %', value: summary?.on_time_pct != null ? `${summary.on_time_pct}%` : '--' },
      { label: 'Avg Delay', value: summary?.schedule_delay_min != null ? `${summary.schedule_delay_min} min` : '--' },
      { label: 'Cancellations', value: summary?.total_cancellations ?? '--' },
      { label: 'Go-Arounds', value: summary?.total_go_arounds ?? '--' },
      { label: 'Diversions', value: summary?.total_diversions ?? '--' },
      { label: 'Peak Flights', value: summary?.peak_simultaneous_flights ?? '--' },
      { label: 'Avg Hold', value: summary?.avg_capacity_hold_min != null ? `${summary.avg_capacity_hold_min} min` : '--' },
      { label: 'Total Flights', value: summary?.total_flights ?? '--' },
    ];

    const eventsHtml = filteredEvents.map(e => `
      <tr>
        <td style="padding:6px 10px;border-bottom:1px solid #334155;white-space:nowrap;color:#94a3b8">${fmtTime(e.time)}</td>
        <td style="padding:6px 10px;border-bottom:1px solid #334155">
          <span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${EVENT_HEX[e.event_type] || '#6b7280'};margin-right:6px;vertical-align:middle"></span>
          <span style="color:#cbd5e1">${EVENT_LABELS[e.event_type] || e.event_type}</span>
        </td>
        <td style="padding:6px 10px;border-bottom:1px solid #334155;color:#e2e8f0">${e.description}</td>
      </tr>
    `).join('');

    const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Simulation Report — ${sim.airport || 'Unknown'} — ${sim.scenarioName || ''}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; padding: 32px; max-width: 1200px; margin: 0 auto; }
  h1 { font-size: 24px; font-weight: 700; margin-bottom: 4px; }
  h2 { font-size: 18px; font-weight: 600; margin: 32px 0 12px; color: #60a5fa; }
  .meta { color: #94a3b8; font-size: 14px; margin-bottom: 24px; }
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px; margin-bottom: 24px; }
  .kpi { background: #1e293b; border-radius: 8px; padding: 16px; text-align: center; }
  .kpi-value { font-size: 24px; font-weight: 700; color: #f1f5f9; }
  .kpi-label { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 4px; }
  table { width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 8px; overflow: hidden; }
  th { text-align: left; padding: 8px 10px; background: #334155; color: #94a3b8; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
  .footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid #334155; color: #475569; font-size: 12px; text-align: center; }
  @media print {
    body { background: white; color: #1e293b; }
    .kpi { background: #f1f5f9; }
    .kpi-value { color: #0f172a; }
    table { background: #f8fafc; }
    th { background: #e2e8f0; color: #475569; }
    td { color: #334155; border-color: #e2e8f0 !important; }
  }
</style>
</head>
<body>
  <h1>${sim.scenarioName || `${sim.airport} Simulation Report`}</h1>
  <div class="meta">
    Airport: <strong>${sim.airport || 'Unknown'}</strong> &nbsp;|&nbsp;
    ${fmtDateTime(sim.simStartTime)} — ${fmtDateTime(sim.simEndTime)} &nbsp;|&nbsp;
    ${filteredEvents.length} events shown &nbsp;|&nbsp;
    Time window: ${fromHour}:00 — ${toHour}:00 UTC
  </div>

  <h2>Key Performance Indicators</h2>
  <div class="kpi-grid">
    ${kpis.map(k => `<div class="kpi"><div class="kpi-value">${k.value}</div><div class="kpi-label">${k.label}</div></div>`).join('')}
  </div>

  <h2>Event Timeline</h2>
  <table>
    <thead>
      <tr>
        <th>Time</th>
        <th>Category</th>
        <th>Description</th>
      </tr>
    </thead>
    <tbody>
      ${eventsHtml || '<tr><td colspan="3" style="padding:16px;text-align:center;color:#64748b">No events match the selected filters</td></tr>'}
    </tbody>
  </table>

  <div class="footer">
    Generated by Airport Digital Twin Simulation Platform &mdash; ${new Date().toLocaleString()}
  </div>
</body>
</html>`;

    const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const scenario = (sim.scenarioName || '').replace(/[^a-zA-Z0-9]+/g, '_').substring(0, 40);
    const filename = `report_${sim.airport || 'unknown'}_${scenario}_${new Date().toISOString().slice(0, 10)}.html`;
    downloadDataUrl(url, filename);
    URL.revokeObjectURL(url);
  }, [sim, summary, filteredEvents, fromHour, toHour]);

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/70 backdrop-blur-md p-4">
      <div className={`bg-white shadow-2xl border border-slate-200 flex flex-col overflow-hidden transition-all duration-200 ${
        fullscreen
          ? 'w-full h-full max-w-full max-h-full rounded-none'
          : 'w-[900px] max-w-[95vw] max-h-[92vh] rounded-xl'
      }`}>
        {/* Header */}
        <div className={`flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-slate-50 ${fullscreen ? '' : 'rounded-t-xl'}`}>
          <div>
            <h2 className="text-lg font-bold text-slate-900">
              {sim.scenarioName || `${sim.airport} Simulation Report`}
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              {sim.airport} &middot; {fmtDateTime(sim.simStartTime)} — {fmtDateTime(sim.simEndTime)}
            </p>
          </div>
          <div className="flex items-center gap-1">
            <button onClick={() => setFullscreen(f => !f)} className="text-slate-400 hover:text-slate-700 p-1" title={fullscreen ? 'Exit fullscreen' : 'Fullscreen'}>
              {fullscreen ? (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 9L4 4m0 0v4m0-4h4m7 11l5 5m0 0v-4m0 4h-4M9 15l-5 5m0 0v-4m0 4h4m7-11l5-5m0 0v4m0-4h-4" />
                </svg>
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-5h-4m4 0v4m0-4l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5h-4m4 0v-4m0 4l-5-5" />
                </svg>
              )}
            </button>
            <button onClick={onClose} className="text-slate-400 hover:text-slate-700 p-1" title="Close">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Tab bar */}
        <div className="flex border-b border-slate-200 px-6">
          <button
            onClick={() => setActiveTab('dashboard')}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'dashboard'
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            Dashboard
          </button>
          <button
            onClick={() => setActiveTab('analysis')}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'analysis'
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            Analysis Report
            {hasAnalysisReport && (
              <span className="ml-1.5 inline-flex items-center justify-center w-2 h-2 rounded-full bg-blue-500" />
            )}
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0 overflow-y-auto px-6 py-4">

          {/* ── Analysis Report tab ── */}
          {activeTab === 'analysis' && (
            hasAnalysisReport ? (
              <div className="overflow-y-auto markdown-report">
                <Markdown remarkPlugins={[remarkGfm]}>{sim.markdownReport!}</Markdown>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-16 text-slate-400">
                <svg className="w-12 h-12 mb-3 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <p className="text-sm font-medium">No analysis report available</p>
                <p className="text-xs mt-1">Run a batch simulation to generate a detailed analysis report.</p>
              </div>
            )
          )}

          {/* ── Dashboard tab ── */}
          {activeTab === 'dashboard' && <div className="flex flex-col gap-2">
          {/* KPI Cards — single compact row */}
          <div className="shrink-0 grid grid-cols-8 gap-1">
            {[
              { label: 'On-Time', value: summary?.on_time_pct != null ? `${summary.on_time_pct}%` : '--', color: (summary?.on_time_pct as number) >= 70 ? 'text-green-600' : 'text-red-600' },
              { label: 'Avg Delay', value: summary?.schedule_delay_min != null ? `${summary.schedule_delay_min}m` : '--', color: 'text-amber-600' },
              { label: 'Cancels', value: `${timeFilteredCounts['cancellation'] ?? 0}`, color: 'text-rose-600' },
              { label: 'Go-Arounds', value: `${timeFilteredCounts['go_around'] ?? 0}`, color: 'text-yellow-600' },
              { label: 'Diversions', value: `${timeFilteredCounts['diversion'] ?? 0}`, color: 'text-cyan-600' },
              { label: 'Peak', value: `${summary?.peak_simultaneous_flights ?? '--'}`, color: 'text-blue-600' },
              { label: 'Avg Hold', value: summary?.avg_capacity_hold_min != null ? `${summary.avg_capacity_hold_min}m` : '--', color: 'text-purple-600' },
              { label: 'Flights', value: `${summary?.total_flights ?? '--'}`, color: 'text-slate-900' },
            ].map(kpi => (
              <div key={kpi.label} className="bg-slate-100 rounded px-1 py-1 text-center">
                <div className={`text-sm font-bold leading-none ${kpi.color}`}>{kpi.value}</div>
                <div className="text-[8px] text-slate-500 uppercase tracking-wider mt-0.5">{kpi.label}</div>
              </div>
            ))}
          </div>

          {/* Filters */}
          <div className="shrink-0 flex items-end gap-6 relative z-10">
            {/* Event type filter — compact dropdown */}
            <EventTypeDropdown
              allTypes={allEventTypes}
              selectedTypes={selectedTypes}
              events={sim.scenarioEvents}
              fromHour={fromHour}
              toHour={toHour}
              onToggle={toggleType}
              onSelectAll={selectAll}
              onClearAll={clearAll}
            />

            {/* Time range filter */}
            <div className="flex-shrink-0">
              <span className="text-xs text-slate-500 font-medium uppercase tracking-wider block mb-1">Time Range</span>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  max={toHour - 1}
                  value={fromHour}
                  onChange={e => setFromHour(Number(e.target.value))}
                  className="w-14 bg-white text-slate-800 text-sm rounded px-2 py-1 border border-slate-300"
                />
                <span className="text-slate-400 text-xs">to</span>
                <input
                  type="number"
                  min={fromHour + 1}
                  max={24}
                  value={toHour}
                  onChange={e => setToHour(Number(e.target.value))}
                  className="w-14 bg-white text-slate-800 text-sm rounded px-2 py-1 border border-slate-300"
                />
                <span className="text-[10px] text-slate-400">UTC</span>
              </div>
            </div>

            {/* Group by toggle */}
            <div className="flex-shrink-0">
              <span className="text-xs text-slate-500 font-medium uppercase tracking-wider block mb-1">Group By</span>
              <div className="flex rounded overflow-hidden border border-slate-300">
                {(['time', 'category', 'flight'] as const).map(mode => (
                  <button
                    key={mode}
                    onClick={() => setGroupBy(mode)}
                    className={`px-2 py-1 text-xs ${groupBy === mode ? 'bg-blue-600 text-white' : 'bg-white text-slate-500'}`}
                  >
                    {mode === 'time' ? 'Time' : mode === 'category' ? 'Category' : 'Flight'}
                  </button>
                ))}
              </div>
            </div>

            {/* Events count — pushed right */}
            <span className="flex-1 text-[10px] text-slate-400 text-right self-end pb-0.5">
              {filteredEvents.length} events{groupBy === 'flight' && flightGroups ? ` · ${flightGroups.length} flights` : ''}
            </span>
          </div>

          {/* Event table — explicit max-height ensures scrolling regardless of flex chain */}
          <div className="rounded-lg border border-slate-200 overflow-y-auto max-h-[45vh]">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-100">
                <tr>
                  <th className="text-left px-3 py-2 text-[10px] text-slate-500 uppercase tracking-wider w-24">Time</th>
                  <th className="text-left px-3 py-2 text-[10px] text-slate-500 uppercase tracking-wider w-32">Category</th>
                  <th className="text-left px-3 py-2 text-[10px] text-slate-500 uppercase tracking-wider">Description</th>
                </tr>
              </thead>
              <tbody>
                {filteredEvents.length === 0 ? (
                  <tr><td colSpan={3} className="text-center py-6 text-slate-400">No events match filters</td></tr>
                ) : groupBy === 'flight' && flightGroups ? (
                  flightGroups.map((group) => {
                    const isExpanded = expandedFlights.has(group.callsign);
                    const typeCountMap = new Map<string, number>();
                    for (const e of group.events) {
                      typeCountMap.set(e.event_type, (typeCountMap.get(e.event_type) ?? 0) + 1);
                    }
                    const typeSummary = [...typeCountMap.entries()]
                      .map(([t, c]) => `${c} ${EVENT_LABELS[t] || t}`)
                      .join(', ');

                    return [
                      <tr
                        key={`flight-${group.callsign}`}
                        onClick={() => setExpandedFlights(prev => {
                          const next = new Set(prev);
                          if (next.has(group.callsign)) next.delete(group.callsign);
                          else next.add(group.callsign);
                          return next;
                        })}
                        className="bg-slate-50 hover:bg-blue-50 cursor-pointer border-b border-slate-200"
                      >
                        <td className="px-3 py-1.5 text-slate-500 font-mono text-xs">
                          {fmtTime(group.events[0].time)}
                        </td>
                        <td className="px-3 py-1.5">
                          <span className="flex items-center gap-1.5">
                            <svg className={`w-3 h-3 text-slate-400 transition-transform ${isExpanded ? 'rotate-90' : ''}`} fill="currentColor" viewBox="0 0 20 20">
                              <polygon points="6,4 14,10 6,16" />
                            </svg>
                            <span className="font-semibold text-slate-800 text-xs">{group.callsign}</span>
                            <span className="bg-slate-200 text-slate-600 text-[10px] px-1.5 rounded-full font-medium">{group.events.length}</span>
                          </span>
                        </td>
                        <td className="px-3 py-1.5 text-slate-500 text-xs">{typeSummary}</td>
                      </tr>,
                      ...(isExpanded ? group.events.map((event, i) => (
                        <tr
                          key={`${group.callsign}-${i}`}
                          onClick={() => handleEventClick(event.time, event.description)}
                          className="hover:bg-blue-50 cursor-pointer transition-colors border-b border-slate-100"
                          title="Click to jump to this event"
                        >
                          <td className="px-3 py-1.5 text-slate-500 font-mono text-xs pl-6">{fmtTime(event.time)}</td>
                          <td className="px-3 py-1.5">
                            <span className="flex items-center gap-1.5 pl-4">
                              <span className={`w-2 h-2 rounded-sm flex-shrink-0 ${EVENT_COLORS[event.event_type] || 'bg-gray-400'}`} />
                              <span className="text-slate-700 text-xs">{EVENT_LABELS[event.event_type] || event.event_type}</span>
                            </span>
                          </td>
                          <td className="px-3 py-1.5 text-slate-800 text-xs">{event.description}</td>
                        </tr>
                      )) : []),
                    ];
                  })
                ) : filteredEvents.map((event, i) => (
                  <tr
                    key={`${event.time}-${i}`}
                    onClick={() => handleEventClick(event.time, event.description)}
                    className="hover:bg-blue-50 cursor-pointer transition-colors border-b border-slate-100"
                    title="Click to jump to this event"
                  >
                    <td className="px-3 py-1.5 text-slate-500 font-mono text-xs">{fmtTime(event.time)}</td>
                    <td className="px-3 py-1.5">
                      <span className="flex items-center gap-1.5">
                        <span className={`w-2 h-2 rounded-sm flex-shrink-0 ${EVENT_COLORS[event.event_type] || 'bg-gray-400'}`} />
                        <span className="text-slate-700 text-xs">{EVENT_LABELS[event.event_type] || event.event_type}</span>
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-slate-800 text-xs">{event.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          </div>}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-3 border-t border-slate-200 bg-slate-50 rounded-b-xl">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-slate-200 hover:bg-slate-300 text-sm text-slate-700 transition-colors"
          >
            Close
          </button>
          <button
            onClick={downloadReport}
            className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-sm font-medium text-white transition-colors flex items-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Download Report
          </button>
        </div>
      </div>
    </div>
  );
}
