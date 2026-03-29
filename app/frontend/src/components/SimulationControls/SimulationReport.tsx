import { useState, useCallback, useMemo } from 'react';
import { UseSimulationReplayResult } from '../../hooks/useSimulationReplay';
import { captureCurrentView, downloadDataUrl } from '../../utils/sceneCapture';
import { EVENT_COLORS, EVENT_LABELS } from './SimulationControls';

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

/** Get hour from ISO string. */
function getHour(iso: string): number {
  try { return new Date(iso).getHours(); } catch { return 0; }
}

interface CapturedImage {
  id: string;
  dataUrl: string;
  simTime: string | null;
  label: string;
}

export function SimulationReport({ sim, onClose }: SimulationReportProps) {
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

  // Time range filter (hours)
  const startHour = sim.simStartTime ? getHour(sim.simStartTime) : 0;
  const endHour = sim.simEndTime ? getHour(sim.simEndTime) : 24;
  const [fromHour, setFromHour] = useState(startHour);
  const [toHour, setToHour] = useState(endHour === 0 ? 24 : endHour);

  // Grouping mode
  const [groupBy, setGroupBy] = useState<'time' | 'category'>('time');

  // Captured screenshots
  const [captures, setCaptures] = useState<CapturedImage[]>([]);
  const [capturing, setCapturing] = useState(false);

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
      return new Date(a.time).getTime() - new Date(b.time).getTime();
    });
  }, [sim.scenarioEvents, selectedTypes, fromHour, toHour, groupBy]);

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

  // Capture current view
  const handleCapture = useCallback(async () => {
    setCapturing(true);
    try {
      const dataUrl = await captureCurrentView(sim.currentSimTime, sim.airport);
      if (dataUrl) {
        setCaptures(prev => [...prev, {
          id: `cap-${Date.now()}`,
          dataUrl,
          simTime: sim.currentSimTime,
          label: `${sim.airport || 'SIM'} at ${fmtTime(sim.currentSimTime || '')}`,
        }]);
      }
    } finally {
      setCapturing(false);
    }
  }, [sim.currentSimTime, sim.airport]);

  // Remove capture
  const removeCapture = useCallback((id: string) => {
    setCaptures(prev => prev.filter(c => c.id !== id));
  }, []);

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

    const capturesHtml = captures.map(c => `
      <div style="margin-bottom:16px">
        <p style="color:#94a3b8;font-size:12px;margin-bottom:4px">${c.label}</p>
        <img src="${c.dataUrl}" style="max-width:100%;border-radius:8px;border:1px solid #334155" />
      </div>
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
  .captures { margin-top: 16px; }
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
    Time window: ${fromHour}:00 — ${toHour}:00
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

  ${captures.length > 0 ? `
  <h2>Scene Captures</h2>
  <div class="captures">
    ${capturesHtml}
  </div>
  ` : ''}

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
  }, [sim, summary, filteredEvents, captures, fromHour, toHour]);

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-900 rounded-xl shadow-2xl border border-slate-700 w-[900px] max-w-[95vw] max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <div>
            <h2 className="text-lg font-bold text-white">
              {sim.scenarioName || `${sim.airport} Simulation Report`}
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              {sim.airport} &middot; {fmtDateTime(sim.simStartTime)} — {fmtDateTime(sim.simEndTime)}
            </p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body — scrollable */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
          {/* KPI Cards */}
          <div className="grid grid-cols-4 gap-3">
            {[
              { label: 'On-Time', value: summary?.on_time_pct != null ? `${summary.on_time_pct}%` : '--', color: (summary?.on_time_pct as number) >= 70 ? 'text-green-400' : 'text-red-400' },
              { label: 'Avg Delay', value: summary?.schedule_delay_min != null ? `${summary.schedule_delay_min}m` : '--', color: 'text-amber-400' },
              { label: 'Cancellations', value: `${summary?.total_cancellations ?? '--'}`, color: 'text-rose-400' },
              { label: 'Go-Arounds', value: `${summary?.total_go_arounds ?? '--'}`, color: 'text-yellow-400' },
              { label: 'Diversions', value: `${summary?.total_diversions ?? '--'}`, color: 'text-cyan-400' },
              { label: 'Peak Flights', value: `${summary?.peak_simultaneous_flights ?? '--'}`, color: 'text-blue-400' },
              { label: 'Avg Hold', value: summary?.avg_capacity_hold_min != null ? `${summary.avg_capacity_hold_min}m` : '--', color: 'text-purple-400' },
              { label: 'Total Flights', value: `${summary?.total_flights ?? '--'}`, color: 'text-white' },
            ].map(kpi => (
              <div key={kpi.label} className="bg-slate-800 rounded-lg px-3 py-2 text-center">
                <div className={`text-xl font-bold ${kpi.color}`}>{kpi.value}</div>
                <div className="text-[10px] text-slate-500 uppercase tracking-wider mt-0.5">{kpi.label}</div>
              </div>
            ))}
          </div>

          {/* Filters */}
          <div className="flex items-start gap-6">
            {/* Event type filter */}
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs text-slate-400 font-medium uppercase tracking-wider">Event Types</span>
                <button onClick={selectAll} className="text-[10px] text-blue-400 hover:text-blue-300">All</button>
                <button onClick={clearAll} className="text-[10px] text-blue-400 hover:text-blue-300">Clear</button>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {allEventTypes.map(type => (
                  <button
                    key={type}
                    onClick={() => toggleType(type)}
                    className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-all ${
                      selectedTypes.has(type)
                        ? 'bg-slate-700 text-white ring-1 ring-slate-500'
                        : 'bg-slate-800 text-slate-500'
                    }`}
                  >
                    <div className={`w-2 h-2 rounded-sm ${EVENT_COLORS[type] || 'bg-gray-400'}`} />
                    {EVENT_LABELS[type] || type}
                    <span className="text-[10px] text-slate-500 ml-0.5">
                      ({sim.scenarioEvents.filter(e => e.event_type === type).length})
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {/* Time range filter */}
            <div className="flex-shrink-0 w-48">
              <span className="text-xs text-slate-400 font-medium uppercase tracking-wider block mb-2">Time Range</span>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  max={toHour - 1}
                  value={fromHour}
                  onChange={e => setFromHour(Number(e.target.value))}
                  className="w-14 bg-slate-800 text-white text-sm rounded px-2 py-1 border border-slate-600"
                />
                <span className="text-slate-500 text-xs">to</span>
                <input
                  type="number"
                  min={fromHour + 1}
                  max={24}
                  value={toHour}
                  onChange={e => setToHour(Number(e.target.value))}
                  className="w-14 bg-slate-800 text-white text-sm rounded px-2 py-1 border border-slate-600"
                />
                <span className="text-[10px] text-slate-500">h</span>
              </div>
            </div>

            {/* Group by toggle */}
            <div className="flex-shrink-0">
              <span className="text-xs text-slate-400 font-medium uppercase tracking-wider block mb-2">Group By</span>
              <div className="flex rounded overflow-hidden border border-slate-600">
                <button
                  onClick={() => setGroupBy('time')}
                  className={`px-2 py-1 text-xs ${groupBy === 'time' ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-400'}`}
                >
                  Time
                </button>
                <button
                  onClick={() => setGroupBy('category')}
                  className={`px-2 py-1 text-xs ${groupBy === 'category' ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-400'}`}
                >
                  Category
                </button>
              </div>
            </div>
          </div>

          {/* Event table */}
          <div className="max-h-64 overflow-y-auto rounded-lg border border-slate-700">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-800">
                <tr>
                  <th className="text-left px-3 py-2 text-[10px] text-slate-500 uppercase tracking-wider w-24">Time</th>
                  <th className="text-left px-3 py-2 text-[10px] text-slate-500 uppercase tracking-wider w-32">Category</th>
                  <th className="text-left px-3 py-2 text-[10px] text-slate-500 uppercase tracking-wider">Description</th>
                </tr>
              </thead>
              <tbody>
                {filteredEvents.length === 0 ? (
                  <tr><td colSpan={3} className="text-center py-6 text-slate-500">No events match filters</td></tr>
                ) : filteredEvents.map((event, i) => (
                  <tr key={`${event.time}-${i}`} className="hover:bg-slate-800/50">
                    <td className="px-3 py-1.5 text-slate-400 font-mono text-xs">{fmtTime(event.time)}</td>
                    <td className="px-3 py-1.5">
                      <span className="flex items-center gap-1.5">
                        <span className={`w-2 h-2 rounded-sm flex-shrink-0 ${EVENT_COLORS[event.event_type] || 'bg-gray-400'}`} />
                        <span className="text-slate-300 text-xs">{EVENT_LABELS[event.event_type] || event.event_type}</span>
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-slate-200 text-xs">{event.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="text-[10px] text-slate-500 text-right -mt-3">
            {filteredEvents.length} events shown
          </div>

          {/* Scene captures */}
          <div>
            <div className="flex items-center gap-3 mb-2">
              <span className="text-xs text-slate-400 font-medium uppercase tracking-wider">Scene Captures</span>
              <button
                onClick={handleCapture}
                disabled={capturing}
                className="px-2 py-1 rounded text-xs bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-50 flex items-center gap-1"
              >
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                  <circle cx="12" cy="13" r="3" stroke="currentColor" strokeWidth={2} fill="none" />
                </svg>
                {capturing ? 'Capturing...' : 'Capture Current View'}
              </button>
              <span className="text-[10px] text-slate-500">
                Scrub the simulation timeline, then capture at key moments
              </span>
            </div>
            {captures.length > 0 ? (
              <div className="grid grid-cols-3 gap-2">
                {captures.map(cap => (
                  <div key={cap.id} className="relative group">
                    <img
                      src={cap.dataUrl}
                      alt={cap.label}
                      className="w-full h-24 object-cover rounded-lg border border-slate-700"
                    />
                    <div className="absolute bottom-0 left-0 right-0 bg-black/60 text-[10px] text-white px-2 py-0.5 rounded-b-lg">
                      {cap.label}
                    </div>
                    <button
                      onClick={() => removeCapture(cap.id)}
                      className="absolute top-1 right-1 w-5 h-5 bg-red-600/80 hover:bg-red-600 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-4 text-slate-600 text-xs border border-dashed border-slate-700 rounded-lg">
                No captures yet — scrub to a key moment and click "Capture Current View"
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-3 border-t border-slate-700">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-sm text-slate-300 transition-colors"
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
