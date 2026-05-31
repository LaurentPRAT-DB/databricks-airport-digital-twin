import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { UseSimulationReplayResult, ScenarioEvent } from '../../hooks/useSimulationReplay';
import { useFlightContext } from '../../context/FlightContext';
import type { Flight } from '../../types/flight';
import { downloadDataUrl } from '../../utils/sceneCapture';
import { debugLog } from '../../utils/debugLogger';
import { EVENT_COLORS, EVENT_LABELS } from './SimulationControls';

type ReportTab = 'dashboard' | 'analysis';

interface SimulationReportProps {
  sim: UseSimulationReplayResult;
  onClose: () => void;
  focusEvents?: ScenarioEvent[] | null;
  onReportGenerated?: (content: string) => void;
  savedReport?: string | null;
}

const DETAIL_SKIP_KEYS = new Set(['time', 'event_type', 'description']);

const KPI_DEFINITIONS: Record<string, string> = {
  'On-Time': 'Percentage of flights operating within 15 minutes of their scheduled time, including delays and capacity holds.',
  'Avg Delay': 'Average schedule delay across all flights, in minutes.',
  'Cancels': 'Number of flights cancelled due to weather, capacity, or operational constraints.',
  'Go-Arounds': 'Aborted landings where aircraft must circle and re-attempt the approach.',
  'Diversions': 'Flights redirected to an alternate airport due to weather or runway unavailability.',
  'Peak': 'Maximum number of aircraft simultaneously active during the simulation.',
  'Avg Hold': 'Average additional wait time per flight due to runway or airspace capacity constraints.',
  'Turnaround': 'Average turnaround time for parked aircraft from arrival to departure readiness.',
  'Flights': 'Total number of flights in the simulation schedule.',
};

const DETAIL_LABELS: Record<string, string> = {
  callsign: 'Callsign',
  icao24: 'ICAO24',
  attempt: 'Attempt',
  weather: 'Weather',
  severity: 'Severity',
  type: 'Type',
  visibility_nm: 'Visibility (nm)',
  ceiling_ft: 'Ceiling (ft)',
  runway: 'Runway',
  runway_config: 'Runway Config',
  reason: 'Reason',
  target: 'Target',
  alternate: 'Alternate',
  start: 'Start',
  end: 'End',
  wind_direction: 'Wind Dir',
};

interface ChatMessage {
  role: 'assistant' | 'user';
  content: string;
}

function EventDetailPanel({ event, onJump, isBatchMode }: { event: ScenarioEvent; onJump: () => void; isBatchMode?: boolean }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleExplain = async () => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/assistant/explain', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ event }),
      });
      if (res.ok) {
        const data = await res.json();
        setMessages([{ role: 'assistant', content: data.answer }]);
      } else {
        setMessages([{ role: 'assistant', content: 'Unable to generate explanation. Please try again.' }]);
      }
    } catch {
      setMessages([{ role: 'assistant', content: 'Failed to connect to assistant.' }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;
    const userMsg = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
    setIsLoading(true);
    try {
      const eventSummary = JSON.stringify(event, null, 2);
      const priorAnalysis = messages.filter(m => m.role === 'assistant').map(m => m.content).join('\n\n');
      const contextQuestion = `Context — this is about a simulation event:\n${eventSummary}\n\nPrevious analysis:\n${priorAnalysis}\n\nUser question: ${userMsg}`;
      const res = await fetch('/api/assistant/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ question: contextQuestion }),
      });
      if (res.ok) {
        const data = await res.json();
        setMessages(prev => [...prev, { role: 'assistant', content: data.answer }]);
      } else {
        setMessages(prev => [...prev, { role: 'assistant', content: 'Unable to respond. Please try again.' }]);
      }
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Failed to connect to assistant.' }]);
    } finally {
      setIsLoading(false);
    }
  };

  const details = Object.entries(event).filter(
    ([k, v]) => !DETAIL_SKIP_KEYS.has(k) && v !== undefined && v !== null
  );

  return (
    <tr>
      <td colSpan={3} className="px-6 py-3 bg-blue-50/50 border-b border-blue-100">
        {details.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-x-6 gap-y-2 mb-3">
            {details.map(([key, value]) => (
              <div key={key}>
                <span className="text-[10px] text-slate-400 uppercase tracking-wider">{DETAIL_LABELS[key] || key}</span>
                <div className="text-xs text-slate-800 font-medium">{String(value)}</div>
              </div>
            ))}
          </div>
        )}
        <div className="flex items-center gap-2 pt-2 border-t border-blue-100/50">
          {!isBatchMode && (
            <button
              onClick={onJump}
              className="px-3 py-1.5 rounded text-[11px] font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors flex items-center gap-1.5"
              title="Seek simulation to this event and select the flight"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              View on Map
            </button>
          )}
          {messages.length === 0 && (
            <button
              onClick={handleExplain}
              disabled={isLoading}
              className="px-3 py-1.5 rounded text-[11px] font-medium bg-slate-100 hover:bg-slate-200 text-slate-600 transition-colors flex items-center gap-1.5 disabled:opacity-50"
              title="AI-powered event explanation"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
              {isLoading ? 'Explaining...' : 'Explain'}
            </button>
          )}
        </div>
        {/* Mini-chat */}
        {messages.length > 0 && (
          <div className="mt-3 pt-3 border-t border-blue-100/50">
            <div className="max-h-48 overflow-y-auto space-y-2 mb-2">
              {messages.map((msg, i) => (
                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[85%] px-2.5 py-1.5 rounded-lg text-xs leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-blue-600 text-white'
                      : 'bg-slate-100 text-slate-700'
                  }`}>
                    {msg.role === 'assistant' ? (
                      <Markdown remarkPlugins={[remarkGfm]}>{msg.content}</Markdown>
                    ) : (
                      msg.content
                    )}
                  </div>
                </div>
              ))}
              {isLoading && (
                <div className="flex justify-start">
                  <div className="bg-slate-100 text-slate-400 px-2.5 py-1.5 rounded-lg text-xs italic">
                    Thinking...
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
            <div className="flex items-center gap-1.5">
              <input
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleSend(); }}
                placeholder="Ask a follow-up..."
                disabled={isLoading}
                className="flex-1 px-2.5 py-1.5 text-xs border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 disabled:opacity-50"
              />
              <button
                onClick={handleSend}
                disabled={isLoading || !input.trim()}
                className="px-2 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50 transition-colors"
                title="Send"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                </svg>
              </button>
            </div>
          </div>
        )}
      </td>
    </tr>
  );
}

const SUGGESTION_CHIPS = [
  'What caused the delays?',
  'How could we improve on-time performance?',
  'What if we increase traffic by 20%?',
  'Are go-around rates acceptable?',
];

function ReportChat({ sim }: { sim: UseSimulationReplayResult }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const simulationContext = useMemo(() => ({
    config: { airport: sim.airport, duration_hours: sim.simStartTime && sim.simEndTime
      ? (new Date(sim.simEndTime).getTime() - new Date(sim.simStartTime).getTime()) / 3600000 : 24,
      start_date: sim.simStartTime, scenario_name: sim.scenarioName },
    summary: sim.summary || {},
    scenario_events: sim.scenarioEvents?.slice(0, 50) || [],
    weather_snapshots: sim.scenarioEvents?.filter(e => e.event_type === 'weather').slice(0, 20) || [],
  }), [sim.airport, sim.simStartTime, sim.simEndTime, sim.scenarioName, sim.summary, sim.scenarioEvents]);

  const handleSend = async (question?: string) => {
    const q = question || input.trim();
    if (!q || isLoading) return;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: q }]);
    setIsLoading(true);
    try {
      const res = await fetch('/api/assistant/report-chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          question: q,
          messages: messages.map(m => ({ role: m.role, content: m.content })),
          simulation_context: simulationContext,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        let content = data.answer || '';
        if (data.what_if_result) {
          const r = data.what_if_result;
          content += '\n\n**What-If Comparison:**\n\n| KPI | Baseline | Modified | Delta |\n|-----|----------|----------|-------|\n';
          const labels: Record<string, string> = {
            on_time_pct: 'On-Time %', schedule_delay_min: 'Avg Delay (min)',
            avg_capacity_hold_min: 'Avg Hold (min)', peak_simultaneous_flights: 'Peak Flights',
            total_go_arounds: 'Go-Arounds', total_diversions: 'Diversions',
            cancellation_rate_pct: 'Cancel Rate %',
          };
          for (const [key, label] of Object.entries(labels)) {
            const base = r.baseline_kpis?.[key];
            const mod = r.modified_kpis?.[key];
            const delta = r.delta?.[key];
            if (base != null && mod != null) {
              const sign = delta > 0 ? '+' : '';
              content += `| ${label} | ${typeof base === 'number' ? base.toFixed(1) : base} | ${typeof mod === 'number' ? mod.toFixed(1) : mod} | ${sign}${typeof delta === 'number' ? delta.toFixed(1) : delta} |\n`;
            }
          }
        }
        setMessages(prev => [...prev, { role: 'assistant', content }]);
      } else {
        setMessages(prev => [...prev, { role: 'assistant', content: 'Unable to respond. Please try again.' }]);
      }
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Failed to connect to assistant.' }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="border-t border-slate-200 pt-4 mt-4">
      <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
        Ask about this simulation
      </div>

      {messages.length === 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {SUGGESTION_CHIPS.map(chip => (
            <button
              key={chip}
              onClick={() => handleSend(chip)}
              disabled={isLoading}
              className="px-2.5 py-1 text-[11px] bg-blue-50 text-blue-700 rounded-full border border-blue-200 hover:bg-blue-100 transition-colors disabled:opacity-50"
            >
              {chip}
            </button>
          ))}
        </div>
      )}

      {messages.length > 0 && (
        <div className="max-h-64 overflow-y-auto space-y-2 mb-3">
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[90%] px-3 py-2 rounded-lg text-xs leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-100 text-slate-700'
              }`}>
                {msg.role === 'assistant' ? (
                  <Markdown remarkPlugins={[remarkGfm]}>{msg.content}</Markdown>
                ) : msg.content}
              </div>
            </div>
          ))}
          {isLoading && (
            <div className="flex justify-start">
              <div className="bg-slate-100 text-slate-400 px-3 py-2 rounded-lg text-xs italic">
                Analyzing...
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      )}

      <div className="flex items-center gap-2">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleSend(); }}
          placeholder="Ask about KPIs, recommendations, or what-if scenarios..."
          disabled={isLoading}
          className="flex-1 px-3 py-2 text-xs border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 disabled:opacity-50"
        />
        <button
          onClick={() => handleSend()}
          disabled={isLoading || !input.trim()}
          className="px-3 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50 transition-colors"
          title="Send"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
          </svg>
        </button>
      </div>
    </div>
  );
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
        <div className="absolute top-full left-0 mt-1 bg-white border border-slate-200 rounded-lg shadow-lg z-50 min-w-[200px] py-1">
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

export function SimulationReport({ sim, onClose, focusEvents, onReportGenerated, savedReport }: SimulationReportProps) {
  const [fullscreen, setFullscreen] = useState(false);
  const { filteredFlights, setSelectedFlight } = useFlightContext();
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatedReport, setGeneratedReport] = useState<string | null>(savedReport ?? null);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const isBatchMode = sim.totalFrames === 0 && sim.scenarioEvents.length > 0;
  const flightsRef = useRef(filteredFlights);
  flightsRef.current = filteredFlights;
  const [selectedEventKey, setSelectedEventKey] = useState<string | null>(null);
  const focusRowRef = useRef<HTMLTableRowElement>(null);
  const tableScrollRef = useRef<HTMLDivElement>(null);

  const modalRef = useRef<HTMLDivElement>(null);

  // Reusable report generation logic
  const triggerGenerate = useCallback(async () => {
    if (isGenerating) return;
    setIsGenerating(true);
    setGenerateError(null);
    try {
      let res: Response;
      const isLiveOrDemo = !sim.loadedFile || sim.loadedFile.startsWith('demo_') || sim.loadedFile.startsWith('recording_');
      if (isLiveOrDemo) {
        const weatherEvents = sim.scenarioEvents.filter(e => e.event_type === 'weather');
        res = await fetch('/api/simulation/report/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            config: { airport: sim.airport, duration_hours: sim.simStartTime && sim.simEndTime
              ? (new Date(sim.simEndTime).getTime() - new Date(sim.simStartTime).getTime()) / 3600000
              : 24, start_date: sim.simStartTime },
            summary: sim.summary || {},
            schedule: sim.schedule || [],
            scenario_events: sim.scenarioEvents || [],
            weather_snapshots: weatherEvents,
          }),
        });
      } else {
        res = await fetch(`/api/simulation/report/generate/${encodeURIComponent(sim.loadedFile!)}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({}),
        });
      }
      if (res.ok) {
        const data = await res.json();
        setGeneratedReport(data.content);
        onReportGenerated?.(data.content);
      } else {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
        setGenerateError(err.detail || `Failed (${res.status})`);
      }
    } catch {
      setGenerateError('Failed to connect to server');
    } finally {
      setIsGenerating(false);
    }
  }, [isGenerating, sim.loadedFile, sim.scenarioEvents, sim.airport, sim.simStartTime, sim.simEndTime, sim.summary, sim.schedule, onReportGenerated]);

  // Auto-generate report for batch mode
  useEffect(() => {
    if (isBatchMode && !generatedReport && !isGenerating && sim.loadedFile) {
      triggerGenerate();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isBatchMode, sim.loadedFile]);

  // ── Event isolation: disable pointer events on map while report is open ──
  useEffect(() => {
    const mapEl = document.querySelector('.leaflet-container') as HTMLElement | null;
    if (mapEl) {
      const prev = mapEl.style.pointerEvents;
      mapEl.style.pointerEvents = 'none';
      debugLog('info', 'ReportEvent', 'map pointer-events disabled');
      return () => {
        mapEl.style.pointerEvents = prev;
        debugLog('info', 'ReportEvent', 'map pointer-events restored');
      };
    }
  }, []);



  // ── Full diagnostic snapshot on mount (delayed for layout to settle) ──
  useEffect(() => {
    const timer = setTimeout(() => {
      const scrollEl = tableScrollRef.current;
      const modal = modalRef.current;
      if (!scrollEl || !modal) return;

      const dims = (el: HTMLElement | null, label: string) => {
        if (!el) return { label, missing: true };
        const cs = getComputedStyle(el);
        return {
          label,
          clientH: el.clientHeight,
          scrollH: el.scrollHeight,
          offsetH: el.offsetHeight,
          boundingH: Math.round(el.getBoundingClientRect().height),
          maxH: cs.maxHeight,
          minH: cs.minHeight,
          height: cs.height,
          overflowY: cs.overflowY,
          display: cs.display,
          flexGrow: cs.flexGrow,
          flexShrink: cs.flexShrink,
          flexBasis: cs.flexBasis,
          position: cs.position,
          zIndex: cs.zIndex,
          pointerEvents: cs.pointerEvents,
        };
      };

      // Walk up from scroll container to modal, capturing each ancestor
      const chain: ReturnType<typeof dims>[] = [];
      let cursor: HTMLElement | null = scrollEl;
      let depth = 0;
      while (cursor && cursor !== modal && depth < 8) {
        chain.push(dims(cursor, `depth-${depth}(${cursor.tagName}.${cursor.className.split(' ')[0]})`));
        cursor = cursor.parentElement;
        depth++;
      }
      chain.push(dims(modal, 'modal'));

      debugLog('info', 'ReportDiag', 'mount snapshot', {
        viewport: `${window.innerWidth}x${window.innerHeight}`,
        scrollable: scrollEl.scrollHeight > scrollEl.clientHeight,
        canScrollDown: scrollEl.scrollTop + scrollEl.clientHeight < scrollEl.scrollHeight - 4,
        chain,
      });

      // Check if map is receiving pointer events through the modal
      const mapEl = document.querySelector('.leaflet-container') as HTMLElement | null;
      if (mapEl) {
        const mapCs = getComputedStyle(mapEl);
        const modalRect = modal.getBoundingClientRect();
        const mapRect = mapEl.getBoundingClientRect();
        debugLog('info', 'ReportDiag', 'layer stacking', {
          modalZ: getComputedStyle(modal).zIndex,
          mapZ: mapCs.zIndex,
          modalRect: { top: modalRect.top, left: modalRect.left, w: modalRect.width, h: modalRect.height },
          mapRect: { top: mapRect.top, left: mapRect.left, w: mapRect.width, h: mapRect.height },
          mapPointerEvents: mapCs.pointerEvents,
          overlaps: !(modalRect.right < mapRect.left || modalRect.left > mapRect.right || modalRect.bottom < mapRect.top || modalRect.top > mapRect.bottom),
        });
      }
    }, 500);
    return () => clearTimeout(timer);
  }, []);

  // Handle "View on Map" — pause, seek to a frame containing the flight, close report, select it
  const handleEventClick = useCallback((event: ScenarioEvent) => {
    const eventCallsign = (event.callsign as string) || extractCallsign(event.description) || '';
    const eventIcao24 = event.icao24 as string | undefined;

    debugLog('info', 'ReportNav', 'View on Map clicked', {
      eventType: event.event_type, eventCallsign, eventIcao24, eventTime: event.time,
    });

    // Pause so the user can inspect the flight at the event moment
    sim.pause();

    // Add time padding before the event so the user sees the lead-up
    const paddingMs = event.event_type === 'go_around' ? 120_000
      : event.event_type === 'diversion' ? 60_000
      : 30_000;
    const seekTime = new Date(new Date(event.time).getTime() - paddingMs).toISOString();

    if (eventIcao24 || eventCallsign) {
      sim.seekToFlight(seekTime, eventIcao24 || '', eventCallsign || undefined);
    } else {
      sim.seekToTime(seekTime);
    }

    onClose();

    // Select the flight immediately by icao24. FlightContext resolves the
    // actual Flight object from the flights array reactively — no need to wait
    // for the frame to settle or retry from a stale ref.
    if (eventIcao24) {
      setSelectedFlight({ icao24: eventIcao24 } as Flight);
    } else if (eventCallsign) {
      // Callsign-only: need to find the flight in the rendered list
      setTimeout(() => {
        const flights = flightsRef.current;
        const flight = flights.find(f =>
          f.callsign?.replace(/\s+/g, '') === eventCallsign
        );
        if (flight) setSelectedFlight(flight);
      }, 300);
    }
  }, [sim, setSelectedFlight, onClose]);

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

  // Time range filter (hours) — default to full 0-24 so all events are visible
  const [fromHour, setFromHour] = useState(0);
  const [toHour, setToHour] = useState(24);

  // Grouping mode
  const [groupBy, setGroupBy] = useState<'time' | 'category' | 'flight'>('time');

  // Expanded flight groups (for flight grouping mode)
  const [expandedFlights, setExpandedFlights] = useState<Set<string>>(new Set());


  // KPI help panel toggle
  const [showKpiHelp, setShowKpiHelp] = useState(false);

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

  // Build a set of focus event keys for O(1) highlight lookup
  const focusEventKeys = useMemo(() => {
    if (!focusEvents?.length) return null;
    return new Set(focusEvents.map(e => `${e.time}|${e.event_type}|${e.description}`));
  }, [focusEvents]);

  const eventKey = (e: ScenarioEvent) => `${e.time}|${e.event_type}|${e.description}`;

  // Auto-scroll to first focused event + auto-expand it
  useEffect(() => {
    if (!focusEvents?.length) return;
    setSelectedEventKey(eventKey(focusEvents[0]));
    const id = requestAnimationFrame(() => {
      focusRowRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
    return () => cancelAnimationFrame(id);
  }, [focusEvents]);

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
      { label: 'Avg Turnaround', value: summary?.avg_turnaround_min != null ? `${summary.avg_turnaround_min} min` : '--' },
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

  ${(() => {
    const analysisMarkdown = generatedReport || sim.markdownReport;
    if (!analysisMarkdown) return '';
    const analysisHtml = analysisMarkdown
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/^### (.+)$/gm, '<h3 style="font-size:15px;font-weight:600;margin:20px 0 8px;color:#93c5fd">$1</h3>')
      .replace(/^## (.+)$/gm, '<h2 style="font-size:18px;font-weight:600;margin:28px 0 10px;color:#60a5fa">$1</h2>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/^- (.+)$/gm, '<li style="margin-left:20px;margin-bottom:4px">$1</li>')
      .replace(/\n\n/g, '</p><p style="margin-bottom:12px;line-height:1.6">')
      .replace(/\n/g, '<br>');
    return '<h2>LLM Analysis Report</h2><div style="background:#1e293b;border-radius:8px;padding:24px;margin-bottom:24px;line-height:1.6"><p style="margin-bottom:12px;line-height:1.6">' + analysisHtml + '</p></div>';
  })()}

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
  }, [sim, summary, filteredEvents, fromHour, toHour, generatedReport]);

  return createPortal(
    <div ref={modalRef} className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/70 backdrop-blur-md p-4">
      <div className={`bg-white shadow-2xl border border-slate-200 flex flex-col overflow-hidden transition-all duration-200 ${
        fullscreen
          ? 'w-full h-full max-w-full max-h-full rounded-none'
          : 'w-[900px] max-w-[95vw] h-[92vh] rounded-xl'
      }`}>
        {/* Header */}
        <div className={`shrink-0 flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-slate-50 ${fullscreen ? '' : 'rounded-t-xl'}`}>
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
        <div className="shrink-0 flex border-b border-slate-200 px-6">
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
        <div ref={tableScrollRef} className="flex-1 min-h-0 px-6 py-4 overflow-y-auto flex flex-col">

          {/* ── Analysis Report tab ── */}
          {activeTab === 'analysis' && (
            hasAnalysisReport || generatedReport ? (
              <div className="flex-1 min-h-0 overflow-y-auto flex flex-col">
                <div className="markdown-report pb-4">
                  <Markdown remarkPlugins={[remarkGfm]}>{generatedReport || sim.markdownReport!}</Markdown>
                </div>
                <ReportChat sim={sim} />
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-16 text-slate-400">
                <svg className="w-12 h-12 mb-3 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <p className="text-sm font-medium">No analysis report available</p>
                <p className="text-xs mt-1 mb-4">Generate an AI-powered analysis of this simulation's KPIs, weather, and events.</p>
                {generateError && (
                  <p className="text-xs text-red-500 mb-3">{generateError}</p>
                )}
                <button
                  onClick={triggerGenerate}
                  disabled={isGenerating || (!sim.loadedFile && !sim.summary)}
                  className="px-5 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-sm font-medium text-white transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isGenerating ? (
                    <>
                      <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      Generating Report...
                    </>
                  ) : (
                    <>
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                      </svg>
                      Generate Analysis Report
                    </>
                  )}
                </button>
              </div>
            )
          )}

          {/* ── Dashboard tab ── */}
          {activeTab === 'dashboard' && <div className="flex flex-col gap-2">
          {/* KPI Cards — single compact row with info button */}
          <div className="shrink-0 flex items-stretch gap-1">
            {[
              { label: 'On-Time', value: summary?.on_time_pct != null ? `${summary.on_time_pct}%` : '--', color: (summary?.on_time_pct as number) >= 70 ? 'text-green-600' : 'text-red-600' },
              { label: 'Avg Delay', value: summary?.schedule_delay_min != null ? `${summary.schedule_delay_min}m` : '--', color: 'text-amber-600' },
              { label: 'Cancels', value: `${timeFilteredCounts['cancellation'] ?? 0}`, color: 'text-rose-600' },
              { label: 'Go-Arounds', value: `${timeFilteredCounts['go_around'] ?? 0}`, color: 'text-yellow-600' },
              { label: 'Diversions', value: `${timeFilteredCounts['diversion'] ?? 0}`, color: 'text-cyan-600' },
              { label: 'Peak', value: `${summary?.peak_simultaneous_flights ?? '--'}`, color: 'text-blue-600' },
              { label: 'Avg Hold', value: summary?.avg_capacity_hold_min != null ? `${summary.avg_capacity_hold_min}m` : '--', color: 'text-purple-600' },
              { label: 'Turnaround', value: summary?.avg_turnaround_min != null ? `${summary.avg_turnaround_min}m` : '--', color: 'text-blue-600' },
              { label: 'Flights', value: `${summary?.total_flights ?? '--'}`, color: 'text-slate-900' },
            ].map(kpi => (
              <div key={kpi.label} className="flex-1 bg-slate-100 rounded px-1 py-1 text-center">
                <div className={`text-sm font-bold leading-none ${kpi.color}`}>{kpi.value}</div>
                <div className="text-[8px] text-slate-500 uppercase tracking-wider mt-0.5">{kpi.label}</div>
              </div>
            ))}
            <button
              onClick={() => setShowKpiHelp(prev => !prev)}
              className={`flex items-center justify-center w-7 rounded text-xs font-bold transition-colors ${
                showKpiHelp ? 'bg-blue-600 text-white' : 'bg-slate-200 text-slate-500 hover:bg-slate-300'
              }`}
              title="Explain KPIs"
            >
              ?
            </button>
          </div>
          {showKpiHelp && (
            <div className="shrink-0 bg-blue-50 border border-blue-200 rounded-lg px-4 py-3">
              <div className="grid grid-cols-[auto_1fr_auto_1fr] gap-x-4 gap-y-1.5 items-baseline">
                {Object.entries(KPI_DEFINITIONS).map(([label, desc]) => [
                  <span key={`l-${label}`} className="text-[10px] font-semibold text-blue-700 uppercase tracking-wider whitespace-nowrap">{label}</span>,
                  <span key={`d-${label}`} className="text-[11px] text-slate-600 leading-tight">{desc}</span>,
                ])}
              </div>
            </div>
          )}

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

          {/* Event table */}
          <div className="rounded-lg border border-slate-200 relative">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-100 z-10">
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
                      ...(isExpanded ? group.events.flatMap((event, i) => {
                        const ek = eventKey(event);
                        const isFocused = focusEventKeys?.has(ek);
                        const isSelected = selectedEventKey === ek;
                        const isFirstFocus = isFocused && focusEvents?.[0] === event;
                        return [
                          <tr
                            key={`${group.callsign}-${i}`}
                            ref={isFirstFocus ? focusRowRef : undefined}
                            onClick={() => setSelectedEventKey(prev => prev === ek ? null : ek)}
                            className={`cursor-pointer transition-colors border-b border-slate-100 ${isFocused ? 'bg-blue-50 ring-1 ring-inset ring-blue-200' : 'hover:bg-blue-50'} ${isSelected ? 'bg-blue-100' : ''}`}
                            title="Click to expand event details"
                          >
                            <td className="px-3 py-1.5 text-slate-500 font-mono text-xs pl-6">{fmtTime(event.time)}</td>
                            <td className="px-3 py-1.5">
                              <span className="flex items-center gap-1.5 pl-4">
                                <span className={`w-2 h-2 rounded-sm flex-shrink-0 ${EVENT_COLORS[event.event_type] || 'bg-gray-400'}`} />
                                <span className="text-slate-700 text-xs">{EVENT_LABELS[event.event_type] || event.event_type}</span>
                              </span>
                            </td>
                            <td className="px-3 py-1.5 text-slate-800 text-xs flex items-center gap-2">
                              <span className="flex-1">{event.description}</span>
                              <svg className={`w-3 h-3 text-slate-400 transition-transform flex-shrink-0 ${isSelected ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                              </svg>
                            </td>
                          </tr>,
                          ...(isSelected ? [<EventDetailPanel key={`detail-${group.callsign}-${i}`} event={event} onJump={() => handleEventClick(event)} isBatchMode={isBatchMode} />] : []),
                        ];
                      }) : []),
                    ];
                  })
                ) : filteredEvents.flatMap((event, i) => {
                  const ek = eventKey(event);
                  const isFocused = focusEventKeys?.has(ek);
                  const isSelected = selectedEventKey === ek;
                  const isFirstFocus = isFocused && focusEvents?.[0] === event;
                  return [
                    <tr
                      key={`${event.time}-${i}`}
                      ref={isFirstFocus ? focusRowRef : undefined}
                      onClick={() => setSelectedEventKey(prev => prev === ek ? null : ek)}
                      className={`cursor-pointer transition-colors border-b border-slate-100 ${isFocused ? 'bg-blue-50 ring-1 ring-inset ring-blue-200' : 'hover:bg-blue-50'} ${isSelected ? 'bg-blue-100' : ''}`}
                      title="Click to expand event details"
                    >
                      <td className="px-3 py-1.5 text-slate-500 font-mono text-xs">{fmtTime(event.time)}</td>
                      <td className="px-3 py-1.5">
                        <span className="flex items-center gap-1.5">
                          <span className={`w-2 h-2 rounded-sm flex-shrink-0 ${EVENT_COLORS[event.event_type] || 'bg-gray-400'}`} />
                          <span className="text-slate-700 text-xs">{EVENT_LABELS[event.event_type] || event.event_type}</span>
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-slate-800 text-xs flex items-center gap-2">
                        <span className="flex-1">{event.description}</span>
                        <svg className={`w-3 h-3 text-slate-400 transition-transform flex-shrink-0 ${isSelected ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                      </td>
                    </tr>,
                    ...(isSelected ? [<EventDetailPanel key={`detail-${event.time}-${i}`} event={event} onJump={() => handleEventClick(event)} isBatchMode={isBatchMode} />] : []),
                  ];
                })}
              </tbody>
            </table>
          </div>

          </div>}
        </div>

        {/* Footer */}
        <div className="shrink-0 flex items-center justify-between px-6 py-3 border-t border-slate-200 bg-slate-50 rounded-b-xl">
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
    </div>,
    document.body
  );
}
