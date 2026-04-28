import { useState, useMemo, useEffect } from 'react';
import {
  useSimulationJobs,
  fetchScenarioDetail,
  type SimulationJob,
  type ScenarioInfo,
  type ScenarioDetail,
  type CreateSimulationParams,
} from '../../hooks/useSimulationJobs';
import {
  useSimulationDrafts,
  type SimulationDraft,
  type SaveDraftParams,
} from '../../hooks/useSimulationDrafts';
import type { SimulationFile } from '../../hooks/useSimulationReplay';

type Tab = 'create' | 'saved' | 'load' | 'running';

// ── Event builder types ─────────────────────────────────────────────

type EventCategory = 'weather' | 'runway' | 'ground' | 'traffic';

interface ScenarioEvent {
  id: number;
  category: EventCategory;
  fields: Record<string, string | number>;
}

const WEATHER_TYPES = ['thunderstorm', 'fog', 'snow', 'wind_shift', 'clear', 'sandstorm', 'rain', 'freezing_rain', 'ice_pellets', 'haze'];
const SEVERITY_OPTIONS = ['light', 'moderate', 'severe'];
const RUNWAY_EVENT_TYPES = ['closure', 'config_change', 'reopen'];
const GROUND_EVENT_TYPES = ['gate_failure', 'taxiway_closure', 'fuel_shortage', 'deicing_required'];
const TRAFFIC_TYPES = ['surge', 'diversion', 'cancellation', 'ground_stop'];

const CATEGORY_COLORS: Record<EventCategory, string> = {
  weather: 'bg-amber-100 border-amber-300 text-amber-800',
  runway: 'bg-red-100 border-red-300 text-red-800',
  ground: 'bg-orange-100 border-orange-300 text-orange-800',
  traffic: 'bg-blue-100 border-blue-300 text-blue-800',
};

const CATEGORY_LABELS: Record<EventCategory, string> = {
  weather: 'Weather',
  runway: 'Runway',
  ground: 'Ground',
  traffic: 'Traffic',
};

let nextEventId = 1;

function makeDefaultEvent(category: EventCategory): ScenarioEvent {
  const id = nextEventId++;
  switch (category) {
    case 'weather':
      return { id, category, fields: { time: '08:00', type: 'thunderstorm', severity: 'moderate', duration_hours: 2, visibility_nm: 1, ceiling_ft: 500, wind_speed_kt: 25 } };
    case 'runway':
      return { id, category, fields: { time: '10:00', type: 'closure', runway: '', duration_minutes: 120, reason: '' } };
    case 'ground':
      return { id, category, fields: { time: '12:00', type: 'gate_failure', target: '', duration_hours: 2 } };
    case 'traffic':
      return { id, category, fields: { time: '11:00', type: 'diversion', extra_arrivals: 6, diversion_origin: '', duration_hours: 2 } };
  }
}

// ── Event Card ──────────────────────────────────────────────────────

function EventCard({ event, onChange, onRemove }: {
  event: ScenarioEvent;
  onChange: (id: number, fields: Record<string, string | number>) => void;
  onRemove: (id: number) => void;
}) {
  const colors = CATEGORY_COLORS[event.category];

  const updateField = (key: string, value: string | number) => {
    onChange(event.id, { ...event.fields, [key]: value });
  };

  const inputClass = "w-full bg-white border border-slate-300 rounded px-2 py-1 text-xs text-slate-700";
  const labelClass = "text-[10px] text-slate-500 uppercase tracking-wider block mb-0.5";

  return (
    <div className={`rounded-lg border p-3 ${colors}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold uppercase">{CATEGORY_LABELS[event.category]}</span>
        <button onClick={() => onRemove(event.id)} className="text-slate-400 hover:text-red-500 text-xs">&times;</button>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <div>
          <label className={labelClass}>Time (HH:MM)</label>
          <input className={inputClass} value={event.fields.time} onChange={e => updateField('time', e.target.value)} />
        </div>

        {event.category === 'weather' && (
          <>
            <div>
              <label className={labelClass}>Type</label>
              <select className={inputClass} value={event.fields.type} onChange={e => updateField('type', e.target.value)}>
                {WEATHER_TYPES.map(t => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}
              </select>
            </div>
            <div>
              <label className={labelClass}>Severity</label>
              <select className={inputClass} value={event.fields.severity} onChange={e => updateField('severity', e.target.value)}>
                {SEVERITY_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className={labelClass}>Duration (h)</label>
              <input type="number" className={inputClass} value={event.fields.duration_hours} onChange={e => updateField('duration_hours', Number(e.target.value))} />
            </div>
            <div>
              <label className={labelClass}>Visibility (nm)</label>
              <input type="number" step="0.1" className={inputClass} value={event.fields.visibility_nm} onChange={e => updateField('visibility_nm', Number(e.target.value))} />
            </div>
            <div>
              <label className={labelClass}>Wind (kt)</label>
              <input type="number" className={inputClass} value={event.fields.wind_speed_kt} onChange={e => updateField('wind_speed_kt', Number(e.target.value))} />
            </div>
          </>
        )}

        {event.category === 'runway' && (
          <>
            <div>
              <label className={labelClass}>Type</label>
              <select className={inputClass} value={event.fields.type} onChange={e => updateField('type', e.target.value)}>
                {RUNWAY_EVENT_TYPES.map(t => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}
              </select>
            </div>
            <div>
              <label className={labelClass}>Runway</label>
              <input className={inputClass} value={event.fields.runway} onChange={e => updateField('runway', e.target.value)} placeholder="e.g. 28L" />
            </div>
            <div>
              <label className={labelClass}>Duration (min)</label>
              <input type="number" className={inputClass} value={event.fields.duration_minutes} onChange={e => updateField('duration_minutes', Number(e.target.value))} />
            </div>
            <div className="col-span-2">
              <label className={labelClass}>Reason</label>
              <input className={inputClass} value={event.fields.reason} onChange={e => updateField('reason', e.target.value)} placeholder="Snow accumulation" />
            </div>
          </>
        )}

        {event.category === 'ground' && (
          <>
            <div>
              <label className={labelClass}>Type</label>
              <select className={inputClass} value={event.fields.type} onChange={e => updateField('type', e.target.value)}>
                {GROUND_EVENT_TYPES.map(t => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}
              </select>
            </div>
            <div>
              <label className={labelClass}>Target</label>
              <input className={inputClass} value={event.fields.target} onChange={e => updateField('target', e.target.value)} placeholder="e.g. Gate B7" />
            </div>
            <div>
              <label className={labelClass}>Duration (h)</label>
              <input type="number" className={inputClass} value={event.fields.duration_hours} onChange={e => updateField('duration_hours', Number(e.target.value))} />
            </div>
          </>
        )}

        {event.category === 'traffic' && (
          <>
            <div>
              <label className={labelClass}>Type</label>
              <select className={inputClass} value={event.fields.type} onChange={e => updateField('type', e.target.value)}>
                {TRAFFIC_TYPES.map(t => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}
              </select>
            </div>
            <div>
              <label className={labelClass}>Extra Arrivals</label>
              <input type="number" className={inputClass} value={event.fields.extra_arrivals} onChange={e => updateField('extra_arrivals', Number(e.target.value))} />
            </div>
            <div>
              <label className={labelClass}>Origin</label>
              <input className={inputClass} value={event.fields.diversion_origin} onChange={e => updateField('diversion_origin', e.target.value)} placeholder="e.g. OAK" />
            </div>
            <div>
              <label className={labelClass}>Duration (h)</label>
              <input type="number" className={inputClass} value={event.fields.duration_hours} onChange={e => updateField('duration_hours', Number(e.target.value))} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── Status Badge ────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  PENDING: 'bg-slate-100 text-slate-600',
  QUEUED: 'bg-yellow-100 text-yellow-700',
  RUNNING: 'bg-blue-100 text-blue-700',
  BLOCKED: 'bg-orange-100 text-orange-700',
  SUCCESS: 'bg-green-100 text-green-700',
  FAILED: 'bg-red-100 text-red-700',
  CANCELED: 'bg-slate-100 text-slate-500',
  TERMINATED: 'bg-slate-100 text-slate-600',
  TIMEDOUT: 'bg-red-100 text-red-600',
};

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] || 'bg-slate-100 text-slate-600';
  return <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase ${style}`}>{status}</span>;
}

function formatElapsed(seconds: number | null): string {
  if (seconds == null || seconds < 0) return '--';
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

// ── Create Tab ──────────────────────────────────────────────────────

function CreateTab({ scenarios, isLoadingScenarios, onSubmit, isCreating, onSaveDraft, isSaving, editingDraft, onClearDraft }: {
  scenarios: ScenarioInfo[];
  isLoadingScenarios: boolean;
  onSubmit: (params: CreateSimulationParams) => void;
  isCreating: boolean;
  onSaveDraft: (params: SaveDraftParams) => void;
  isSaving: boolean;
  editingDraft: SimulationDraft | null;
  onClearDraft: () => void;
}) {
  const [airport, setAirport] = useState('SFO');
  const [arrivals, setArrivals] = useState(500);
  const [departures, setDepartures] = useState(500);
  const [durationHours, setDurationHours] = useState(24);
  const [scenarioMode, setScenarioMode] = useState<'none' | 'builtin' | 'custom'>('none');
  const [selectedScenario, setSelectedScenario] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [timeStep, setTimeStep] = useState(2.0);
  const [seed, setSeed] = useState('');
  const [skipPositions, setSkipPositions] = useState(false);
  const [draftName, setDraftName] = useState('');
  const [showSaveInput, setShowSaveInput] = useState(false);

  // Custom scenario state
  const [scenarioName, setScenarioName] = useState('Custom Scenario');
  const [scenarioDesc, setScenarioDesc] = useState('');
  const [events, setEvents] = useState<ScenarioEvent[]>([]);
  const [addMenuOpen, setAddMenuOpen] = useState(false);

  // Load editing draft into form
  useEffect(() => {
    if (!editingDraft) return;
    setAirport(editingDraft.airport);
    setArrivals(editingDraft.arrivals);
    setDepartures(editingDraft.departures);
    setDurationHours(editingDraft.duration_hours);
    setTimeStep(editingDraft.time_step_seconds);
    setSeed(editingDraft.seed != null ? String(editingDraft.seed) : '');
    setSkipPositions(editingDraft.skip_positions);
    setDraftName(editingDraft.display_name);

    if (editingDraft.custom_scenario) {
      setScenarioMode('custom');
      setScenarioName(editingDraft.custom_scenario.name || 'Custom Scenario');
      setScenarioDesc(editingDraft.custom_scenario.description || '');
      const loaded: ScenarioEvent[] = [];
      for (const e of editingDraft.custom_scenario.weather_events || [])
        loaded.push({ id: nextEventId++, category: 'weather', fields: e as Record<string, string | number> });
      for (const e of editingDraft.custom_scenario.runway_events || [])
        loaded.push({ id: nextEventId++, category: 'runway', fields: e as Record<string, string | number> });
      for (const e of editingDraft.custom_scenario.ground_events || [])
        loaded.push({ id: nextEventId++, category: 'ground', fields: e as Record<string, string | number> });
      for (const e of editingDraft.custom_scenario.traffic_modifiers || [])
        loaded.push({ id: nextEventId++, category: 'traffic', fields: e as Record<string, string | number> });
      setEvents(loaded);
    } else if (editingDraft.scenario_name) {
      setScenarioMode('builtin');
      setSelectedScenario(editingDraft.scenario_name);
    } else {
      setScenarioMode('none');
      setSelectedScenario('');
    }
  }, [editingDraft]);

  // Fetch scenario detail when a built-in scenario is selected
  const [scenarioDetail, setScenarioDetail] = useState<ScenarioDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  useEffect(() => {
    if (scenarioMode !== 'builtin' || !selectedScenario) {
      setScenarioDetail(null);
      return;
    }
    let cancelled = false;
    setLoadingDetail(true);
    fetchScenarioDetail(selectedScenario)
      .then(d => { if (!cancelled) setScenarioDetail(d); })
      .catch(() => { if (!cancelled) setScenarioDetail(null); })
      .finally(() => { if (!cancelled) setLoadingDetail(false); });
    return () => { cancelled = true; };
  }, [scenarioMode, selectedScenario]);

  const handleCustomize = () => {
    if (!scenarioDetail) return;
    setScenarioMode('custom');
    setScenarioName(scenarioDetail.name + ' (customized)');
    setScenarioDesc(scenarioDetail.description);
    const loaded: ScenarioEvent[] = [];
    for (const e of scenarioDetail.weather_events)
      loaded.push({ id: nextEventId++, category: 'weather', fields: e as Record<string, string | number> });
    for (const e of scenarioDetail.runway_events)
      loaded.push({ id: nextEventId++, category: 'runway', fields: e as Record<string, string | number> });
    for (const e of scenarioDetail.ground_events)
      loaded.push({ id: nextEventId++, category: 'ground', fields: e as Record<string, string | number> });
    for (const e of scenarioDetail.traffic_modifiers)
      loaded.push({ id: nextEventId++, category: 'traffic', fields: e as Record<string, string | number> });
    setEvents(loaded);
    setSelectedScenario('');
  };

  const addEvent = (category: EventCategory) => {
    setEvents(prev => [...prev, makeDefaultEvent(category)]);
    setAddMenuOpen(false);
  };

  const updateEvent = (id: number, fields: Record<string, string | number>) => {
    setEvents(prev => prev.map(e => e.id === id ? { ...e, fields } : e));
  };

  const removeEvent = (id: number) => {
    setEvents(prev => prev.filter(e => e.id !== id));
  };

  const handleSubmit = () => {
    const params: CreateSimulationParams = {
      airport,
      arrivals,
      departures,
      duration_hours: durationHours,
      time_step_seconds: timeStep,
      skip_positions: skipPositions,
    };
    if (seed) params.seed = Number(seed);

    if (scenarioMode === 'builtin' && selectedScenario) {
      params.scenario_name = selectedScenario;
    } else if (scenarioMode === 'custom' && events.length > 0) {
      const weatherEvents = events.filter(e => e.category === 'weather').map(e => e.fields);
      const runwayEvents = events.filter(e => e.category === 'runway').map(e => e.fields);
      const groundEvents = events.filter(e => e.category === 'ground').map(e => e.fields);
      const trafficMods = events.filter(e => e.category === 'traffic').map(e => e.fields);
      params.custom_scenario = {
        name: scenarioName,
        description: scenarioDesc,
        weather_events: weatherEvents,
        runway_events: runwayEvents,
        ground_events: groundEvents,
        traffic_modifiers: trafficMods,
      };
    }

    onSubmit(params);
  };

  const inputClass = "w-full bg-white border border-slate-300 rounded px-3 py-1.5 text-sm text-slate-700 focus:border-blue-400 focus:outline-none";
  const labelClass = "text-xs text-slate-500 font-medium uppercase tracking-wider block mb-1";

  return (
    <div className="space-y-4">
      {/* Basic config */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={labelClass}>Airport (IATA)</label>
          <input className={inputClass} value={airport} onChange={e => setAirport(e.target.value.toUpperCase())} maxLength={4} placeholder="SFO" />
        </div>
        <div>
          <label className={labelClass}>Duration (hours)</label>
          <input type="number" className={inputClass} value={durationHours} onChange={e => setDurationHours(Number(e.target.value))} min={1} max={168} />
        </div>
        <div>
          <label className={labelClass}>Arrivals</label>
          <input type="number" className={inputClass} value={arrivals} onChange={e => setArrivals(Number(e.target.value))} min={1} max={10000} />
        </div>
        <div>
          <label className={labelClass}>Departures</label>
          <input type="number" className={inputClass} value={departures} onChange={e => setDepartures(Number(e.target.value))} min={1} max={10000} />
        </div>
      </div>

      {/* Scenario selection */}
      <div>
        <label className={labelClass}>Scenario</label>
        <div className="flex gap-1 mb-2">
          {(['none', 'builtin', 'custom'] as const).map(mode => (
            <button
              key={mode}
              onClick={() => setScenarioMode(mode)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                scenarioMode === mode ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              {mode === 'none' ? 'None' : mode === 'builtin' ? 'Built-in' : 'Custom'}
            </button>
          ))}
        </div>

        {scenarioMode === 'builtin' && (
          <select
            className={inputClass}
            value={selectedScenario}
            onChange={e => setSelectedScenario(e.target.value)}
          >
            <option value="">Select a scenario...</option>
            {isLoadingScenarios ? (
              <option disabled>Loading...</option>
            ) : (
              scenarios.map(s => (
                <option key={s.filename} value={s.filename}>{s.name}</option>
              ))
            )}
          </select>
        )}

        {scenarioMode === 'builtin' && selectedScenario && (
          <div className="mt-2 space-y-2">
            <p className="text-xs text-slate-400">
              {scenarios.find(s => s.filename === selectedScenario)?.description}
            </p>

            {loadingDetail && (
              <div className="flex items-center gap-2 text-xs text-slate-400 py-2">
                <div className="w-3 h-3 border-2 border-slate-300 border-t-transparent rounded-full animate-spin" />
                Loading scenario events...
              </div>
            )}

            {scenarioDetail && (
              <div className="border border-slate-200 rounded-lg p-3 bg-slate-50 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">Events</span>
                  <button
                    onClick={handleCustomize}
                    className="px-2 py-1 bg-blue-50 hover:bg-blue-100 text-blue-600 rounded text-xs font-medium transition-colors"
                  >
                    Customize...
                  </button>
                </div>

                {scenarioDetail.weather_events.length > 0 && (
                  <div>
                    <span className="text-[10px] font-semibold uppercase text-amber-700 tracking-wider">Weather ({scenarioDetail.weather_events.length})</span>
                    <div className="space-y-1 mt-1">
                      {scenarioDetail.weather_events.map((e, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs text-slate-600 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                          <span className="font-mono text-amber-700 w-12">{String(e.time ?? '')}</span>
                          <span className="font-medium">{String(e.type ?? '').replace(/_/g, ' ')}</span>
                          {e.severity != null && <span className="text-slate-400">({String(e.severity)})</span>}
                          {e.duration_hours != null && <span className="text-slate-400">{String(e.duration_hours)}h</span>}
                          {e.visibility_nm != null && <span className="text-slate-400">vis {String(e.visibility_nm)}nm</span>}
                          {e.wind_speed_kt != null && <span className="text-slate-400">{String(e.wind_speed_kt)}kt</span>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {scenarioDetail.runway_events.length > 0 && (
                  <div>
                    <span className="text-[10px] font-semibold uppercase text-red-700 tracking-wider">Runway ({scenarioDetail.runway_events.length})</span>
                    <div className="space-y-1 mt-1">
                      {scenarioDetail.runway_events.map((e, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs text-slate-600 bg-red-50 border border-red-200 rounded px-2 py-1">
                          <span className="font-mono text-red-700 w-12">{String(e.time ?? '')}</span>
                          <span className="font-medium">{String(e.type ?? '').replace(/_/g, ' ')}</span>
                          {e.runway != null && <span className="text-slate-500">RWY {String(e.runway)}</span>}
                          {e.duration_minutes != null && <span className="text-slate-400">{String(e.duration_minutes)}min</span>}
                          {e.reason != null && <span className="text-slate-400 truncate max-w-[200px]">{String(e.reason)}</span>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {scenarioDetail.ground_events.length > 0 && (
                  <div>
                    <span className="text-[10px] font-semibold uppercase text-orange-700 tracking-wider">Ground ({scenarioDetail.ground_events.length})</span>
                    <div className="space-y-1 mt-1">
                      {scenarioDetail.ground_events.map((e, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs text-slate-600 bg-orange-50 border border-orange-200 rounded px-2 py-1">
                          <span className="font-mono text-orange-700 w-12">{String(e.time ?? '')}</span>
                          <span className="font-medium">{String(e.type ?? '').replace(/_/g, ' ')}</span>
                          {e.target != null && <span className="text-slate-500">{String(e.target)}</span>}
                          {e.duration_hours != null && <span className="text-slate-400">{String(e.duration_hours)}h</span>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {scenarioDetail.traffic_modifiers.length > 0 && (
                  <div>
                    <span className="text-[10px] font-semibold uppercase text-blue-700 tracking-wider">Traffic ({scenarioDetail.traffic_modifiers.length})</span>
                    <div className="space-y-1 mt-1">
                      {scenarioDetail.traffic_modifiers.map((e, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs text-slate-600 bg-blue-50 border border-blue-200 rounded px-2 py-1">
                          <span className="font-mono text-blue-700 w-12">{String(e.time ?? '')}</span>
                          <span className="font-medium">{String(e.type ?? '').replace(/_/g, ' ')}</span>
                          {e.extra_arrivals != null && <span className="text-slate-400">+{String(e.extra_arrivals)} arr</span>}
                          {e.diversion_origin != null && <span className="text-slate-400">from {String(e.diversion_origin)}</span>}
                          {e.duration_hours != null && <span className="text-slate-400">{String(e.duration_hours)}h</span>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {scenarioMode === 'custom' && (
          <div className="space-y-3 mt-2">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelClass}>Scenario Name</label>
                <input className={inputClass} value={scenarioName} onChange={e => setScenarioName(e.target.value)} />
              </div>
              <div>
                <label className={labelClass}>Description</label>
                <input className={inputClass} value={scenarioDesc} onChange={e => setScenarioDesc(e.target.value)} placeholder="Optional" />
              </div>
            </div>

            {/* Event cards */}
            <div className="space-y-2">
              {events.map(event => (
                <EventCard key={event.id} event={event} onChange={updateEvent} onRemove={removeEvent} />
              ))}
            </div>

            {/* Add event button */}
            <div className="relative">
              <button
                onClick={() => setAddMenuOpen(!addMenuOpen)}
                className="flex items-center gap-1 px-3 py-1.5 bg-slate-100 hover:bg-slate-200 rounded text-xs font-medium text-slate-600 transition-colors"
              >
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                Add Event
              </button>
              {addMenuOpen && (
                <div className="absolute top-full left-0 mt-1 bg-white border border-slate-200 rounded-lg shadow-lg z-20 py-1 min-w-[160px]">
                  {(['weather', 'runway', 'ground', 'traffic'] as EventCategory[]).map(cat => (
                    <button
                      key={cat}
                      onClick={() => addEvent(cat)}
                      className="w-full text-left px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50 transition-colors flex items-center gap-2"
                    >
                      <span className={`w-2 h-2 rounded-sm ${CATEGORY_COLORS[cat].split(' ')[0]}`} />
                      {CATEGORY_LABELS[cat]}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Advanced toggle */}
      <div>
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="text-xs text-slate-400 hover:text-slate-600 transition-colors flex items-center gap-1"
        >
          <svg className={`w-3 h-3 transition-transform ${showAdvanced ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          Advanced Options
        </button>
        {showAdvanced && (
          <div className="grid grid-cols-3 gap-3 mt-2">
            <div>
              <label className={labelClass}>Time Step (s)</label>
              <input type="number" step="0.5" className={inputClass} value={timeStep} onChange={e => setTimeStep(Number(e.target.value))} />
            </div>
            <div>
              <label className={labelClass}>Seed</label>
              <input type="number" className={inputClass} value={seed} onChange={e => setSeed(e.target.value)} placeholder="Random" />
            </div>
            <div className="flex items-end pb-1">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={skipPositions} onChange={e => setSkipPositions(e.target.checked)} className="rounded border-slate-300" />
                <span className="text-xs text-slate-600">Skip Positions (batch mode)</span>
              </label>
            </div>
          </div>
        )}
      </div>

      {/* Editing draft banner */}
      {editingDraft && (
        <div className="flex items-center justify-between bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          <span className="text-xs text-amber-700">Editing: <strong>{editingDraft.display_name}</strong></span>
          <button onClick={onClearDraft} className="text-xs text-amber-500 hover:text-amber-700">Clear</button>
        </div>
      )}

      {/* Save Draft input */}
      {showSaveInput && (
        <div className="flex gap-2">
          <input
            className={inputClass}
            value={draftName}
            onChange={e => setDraftName(e.target.value)}
            placeholder="Draft name..."
            autoFocus
          />
          <button
            onClick={() => {
              if (!draftName.trim()) return;
              const params: SaveDraftParams = {
                display_name: draftName.trim(),
                airport,
                arrivals,
                departures,
                duration_hours: durationHours,
                time_step_seconds: timeStep,
                seed: seed ? Number(seed) : null,
                scenario_name: scenarioMode === 'builtin' && selectedScenario ? selectedScenario : null,
                custom_scenario: scenarioMode === 'custom' && events.length > 0 ? {
                  name: scenarioName,
                  description: scenarioDesc,
                  weather_events: events.filter(e => e.category === 'weather').map(e => e.fields),
                  runway_events: events.filter(e => e.category === 'runway').map(e => e.fields),
                  ground_events: events.filter(e => e.category === 'ground').map(e => e.fields),
                  traffic_modifiers: events.filter(e => e.category === 'traffic').map(e => e.fields),
                } : null,
                skip_positions: skipPositions,
              };
              onSaveDraft(params);
              setShowSaveInput(false);
            }}
            disabled={isSaving || !draftName.trim()}
            className="px-4 py-1.5 bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white rounded text-sm font-medium whitespace-nowrap"
          >
            {isSaving ? 'Saving...' : 'Save'}
          </button>
          <button
            onClick={() => setShowSaveInput(false)}
            className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded text-sm"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-2">
        <button
          onClick={() => {
            setDraftName(editingDraft?.display_name || `${airport} ${arrivals + departures}f ${durationHours}h`);
            setShowSaveInput(true);
          }}
          disabled={isSaving || !airport}
          className="flex-1 py-2.5 bg-slate-100 hover:bg-slate-200 disabled:opacity-50 text-slate-700 rounded-lg font-medium text-sm transition-colors flex items-center justify-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
          </svg>
          Save Draft
        </button>
        <button
          onClick={handleSubmit}
          disabled={isCreating || !airport}
          className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg font-medium text-sm transition-colors flex items-center justify-center gap-2"
        >
          {isCreating ? (
            <>
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              Submitting...
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              Run Now
            </>
          )}
        </button>
      </div>
    </div>
  );
}

// ── Running Tab ─────────────────────────────────────────────────────

function RunningTab({ jobs, isLoading, onLoadResult }: {
  jobs: SimulationJob[];
  isLoading: boolean;
  onLoadResult: (filename: string) => void;
}) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8 gap-3 text-slate-400">
        <div className="w-5 h-5 border-2 border-slate-300 border-t-transparent rounded-full animate-spin" />
        Loading jobs...
      </div>
    );
  }

  if (jobs.length === 0) {
    return (
      <div className="text-center py-8 text-slate-400">
        <svg className="w-10 h-10 mx-auto mb-2 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
        </svg>
        <p className="text-sm">No simulation jobs yet</p>
        <p className="text-xs mt-1">Create a simulation to see it here</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {jobs.map(job => (
        <div key={job.run_id} className="border border-slate-200 rounded-lg px-4 py-3 hover:border-slate-300 transition-colors">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="font-medium text-sm text-slate-800">{job.airport || 'Unknown'}</span>
              <StatusBadge status={job.status} />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400 font-mono">{formatElapsed(job.elapsed_seconds)}</span>
              {job.status === 'SUCCESS' && job.output_file && (
                <button
                  onClick={() => onLoadResult(job.output_file!)}
                  className="px-2 py-1 bg-green-600 hover:bg-green-500 text-white rounded text-xs font-medium transition-colors"
                >
                  Load Result
                </button>
              )}
              {job.run_page_url && (
                <a
                  href={job.run_page_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-blue-500 hover:text-blue-600"
                  title="View in Databricks"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                  </svg>
                </a>
              )}
            </div>
          </div>
          <div className="text-xs text-slate-500 mt-1">{job.run_name}</div>
        </div>
      ))}
    </div>
  );
}

// ── Saved Tab ──────────────────────────────────────────────────────

function SavedTab({ drafts, isLoading, onEdit, onRun, onDelete, isRunning, isDeleting }: {
  drafts: SimulationDraft[];
  isLoading: boolean;
  onEdit: (draft: SimulationDraft) => void;
  onRun: (draft: SimulationDraft) => void;
  onDelete: (name: string) => void;
  isRunning: boolean;
  isDeleting: boolean;
}) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8 gap-3 text-slate-400">
        <div className="w-5 h-5 border-2 border-slate-300 border-t-transparent rounded-full animate-spin" />
        Loading drafts...
      </div>
    );
  }

  if (drafts.length === 0) {
    return (
      <div className="text-center py-8 text-slate-400">
        <svg className="w-10 h-10 mx-auto mb-2 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
        </svg>
        <p className="text-sm">No saved drafts</p>
        <p className="text-xs mt-1">Use "Save Draft" in the Create tab to save a config here</p>
      </div>
    );
  }

  const sorted = [...drafts].sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''));

  return (
    <div className="space-y-2">
      {sorted.map(draft => {
        const scenarioLabel = draft.custom_scenario
          ? 'Custom'
          : draft.scenario_name
            ? draft.scenario_name.replace('.yaml', '')
            : 'No scenario';
        const totalFlights = draft.arrivals + draft.departures;
        return (
          <div key={draft.name} className="border border-slate-200 rounded-lg px-4 py-3 hover:border-slate-300 transition-colors">
            <div className="flex items-center justify-between">
              <div>
                <span className="font-medium text-sm text-slate-800">{draft.display_name}</span>
                <span className="ml-2 text-xs text-slate-400">{draft.airport}</span>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => onEdit(draft)}
                  className="px-2 py-1 text-xs text-slate-600 hover:bg-slate-100 rounded transition-colors"
                  title="Edit"
                >
                  Edit
                </button>
                <button
                  onClick={() => onRun(draft)}
                  disabled={isRunning}
                  className="px-2 py-1 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded text-xs font-medium transition-colors"
                >
                  Run
                </button>
                <button
                  onClick={() => onDelete(draft.name)}
                  disabled={isDeleting}
                  className="px-2 py-1 text-xs text-red-500 hover:bg-red-50 rounded transition-colors"
                  title="Delete"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            </div>
            <div className="text-xs text-slate-500 mt-1">
              {totalFlights} flights &middot; {draft.duration_hours}h &middot; {scenarioLabel}
              {draft.updated_at && (
                <span className="ml-2 text-slate-400">
                  Updated {new Date(draft.updated_at).toLocaleDateString()}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Load Tab (wrapper around FilePicker content) ────────────────────

function LoadTab({ files, isLoading, isFetchingFiles, onLoad, onSelectForWindow }: {
  files: SimulationFile[];
  isLoading: boolean;
  isFetchingFiles: boolean;
  onLoad: (filename: string) => void;
  onSelectForWindow: (filename: string) => void;
}) {
  const MAX_LOADABLE_BYTES = 1 * 1024 * 1024 * 1024;
  const LARGE_FILE_THRESHOLD = 100 * 1024 * 1024;

  function formatFileSize(sizeBytes: number | undefined, sizeKb: number): string {
    const bytes = sizeBytes ?? sizeKb * 1024;
    if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(0)} MB`;
    return `${(bytes / 1024).toFixed(0)} KB`;
  }

  if (isFetchingFiles) {
    return (
      <div className="flex items-center justify-center py-8 gap-3 text-slate-400">
        <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        Loading simulation files...
      </div>
    );
  }

  if (files.length === 0) {
    return <p className="text-slate-500 text-sm text-center py-8">No simulation files available.</p>;
  }

  return (
    <div className="space-y-2 max-h-[380px] overflow-y-auto">
      {files.map(f => {
        const sizeBytes = f.size_bytes ?? f.size_kb * 1024;
        const tooLarge = sizeBytes > MAX_LOADABLE_BYTES;
        const isLarge = sizeBytes > LARGE_FILE_THRESHOLD;
        return (
          <button
            key={f.filename}
            onClick={() => {
              if (tooLarge || isLarge) onSelectForWindow(f.filename);
              else onLoad(f.filename);
            }}
            disabled={isLoading}
            className={`w-full text-left px-4 py-3 rounded-lg border transition-colors ${
              tooLarge
                ? 'border-amber-200 bg-amber-50 hover:border-amber-400 disabled:opacity-50'
                : 'border-slate-200 hover:border-blue-400 hover:bg-blue-50 disabled:opacity-50'
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="font-medium text-slate-800">
                {f.scenario_name ? <>{f.airport} &mdash; {f.scenario_name}</> : <>{f.airport} &mdash; {f.total_flights} flights</>}
              </span>
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-blue-500">{f.duration_hours}h</span>
                <span className={`text-xs ${tooLarge ? 'text-amber-500 font-medium' : isLarge ? 'text-amber-400' : 'text-slate-400'}`}>
                  {formatFileSize(f.size_bytes, f.size_kb)}
                </span>
              </div>
            </div>
            <div className="text-xs text-slate-500 mt-1">
              {f.total_flights} flights &middot; {f.arrivals} arr / {f.departures} dep
              {isLarge && <span className="ml-1 text-amber-500">&middot; Select time window</span>}
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ── Main SimulationManager Modal ────────────────────────────────────

export default function SimulationManager({
  onClose,
  onLoad,
  onSelectForWindow,
  files,
  isLoadingSimulation,
  isFetchingFiles,
}: {
  onClose: () => void;
  onLoad: (filename: string) => void;
  onSelectForWindow: (filename: string) => void;
  files: SimulationFile[];
  isLoadingSimulation: boolean;
  isFetchingFiles: boolean;
}) {
  const [activeTab, setActiveTab] = useState<Tab>('create');
  const [editingDraft, setEditingDraft] = useState<SimulationDraft | null>(null);
  const { jobs, isLoadingJobs, scenarios, isLoadingScenarios, createJob, isCreating } = useSimulationJobs();
  const {
    drafts, isLoadingDrafts,
    saveDraft, isSaving,
    updateDraft, isUpdating,
    deleteDraft, isDeleting,
  } = useSimulationDrafts();

  const activeJobCount = useMemo(
    () => jobs.filter(j => ['PENDING', 'QUEUED', 'RUNNING', 'BLOCKED'].includes(j.status)).length,
    [jobs],
  );

  const handleCreate = async (params: CreateSimulationParams) => {
    try {
      await createJob(params);
      setActiveTab('running');
    } catch {
      // Error handled by mutation state
    }
  };

  const handleSaveDraft = async (params: SaveDraftParams) => {
    try {
      if (editingDraft) {
        await updateDraft({ name: editingDraft.name, ...params });
      } else {
        await saveDraft(params);
      }
      setEditingDraft(null);
      setActiveTab('saved');
    } catch {
      // Error handled by mutation state
    }
  };

  const handleEditDraft = (draft: SimulationDraft) => {
    setEditingDraft(draft);
    setActiveTab('create');
  };

  const handleRunDraft = async (draft: SimulationDraft) => {
    const params: CreateSimulationParams = {
      airport: draft.airport,
      arrivals: draft.arrivals,
      departures: draft.departures,
      duration_hours: draft.duration_hours,
      time_step_seconds: draft.time_step_seconds,
      skip_positions: draft.skip_positions,
    };
    if (draft.seed != null) params.seed = draft.seed;
    if (draft.scenario_name) params.scenario_name = draft.scenario_name;
    if (draft.custom_scenario) params.custom_scenario = draft.custom_scenario;

    try {
      await createJob(params);
      setActiveTab('running');
    } catch {
      // Error handled by mutation state
    }
  };

  const handleDeleteDraft = async (name: string) => {
    try {
      await deleteDraft(name);
      if (editingDraft?.name === name) setEditingDraft(null);
    } catch {
      // Error handled by mutation state
    }
  };

  const handleLoadResult = (filename: string) => {
    onLoad(filename);
    onClose();
  };

  const handleLoadFile = (filename: string) => {
    onLoad(filename);
    onClose();
  };

  const handleSelectForWindow = (filename: string) => {
    onSelectForWindow(filename);
    onClose();
  };

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-[2000]" onClick={onClose} />
      <div className="fixed inset-0 z-[2001] flex items-center justify-center p-8">
        <div className="bg-white rounded-xl shadow-2xl w-[640px] max-h-[85vh] overflow-hidden flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
            <h2 className="text-lg font-bold text-slate-800">Simulation Manager</h2>
            <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-xl leading-none">&times;</button>
          </div>

          {/* Tabs */}
          <div className="flex gap-1 px-6 pt-3 border-b border-slate-200">
            {([
              { key: 'create' as Tab, label: 'Create' },
              { key: 'saved' as Tab, label: `Saved${drafts.length > 0 ? ` (${drafts.length})` : ''}` },
              { key: 'load' as Tab, label: 'Load' },
              { key: 'running' as Tab, label: `Running${activeJobCount > 0 ? ` (${activeJobCount})` : ''}` },
            ]).map(tab => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                  activeTab === tab.key
                    ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50/50'
                    : 'text-slate-500 hover:text-slate-700 hover:bg-slate-50'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto p-6">
            {activeTab === 'create' && (
              <CreateTab
                scenarios={scenarios}
                isLoadingScenarios={isLoadingScenarios}
                onSubmit={handleCreate}
                isCreating={isCreating}
                onSaveDraft={handleSaveDraft}
                isSaving={isSaving || isUpdating}
                editingDraft={editingDraft}
                onClearDraft={() => setEditingDraft(null)}
              />
            )}
            {activeTab === 'saved' && (
              <SavedTab
                drafts={drafts}
                isLoading={isLoadingDrafts}
                onEdit={handleEditDraft}
                onRun={handleRunDraft}
                onDelete={handleDeleteDraft}
                isRunning={isCreating}
                isDeleting={isDeleting}
              />
            )}
            {activeTab === 'load' && (
              <LoadTab
                files={files}
                isLoading={isLoadingSimulation}
                isFetchingFiles={isFetchingFiles}
                onLoad={handleLoadFile}
                onSelectForWindow={handleSelectForWindow}
              />
            )}
            {activeTab === 'running' && (
              <RunningTab
                jobs={jobs}
                isLoading={isLoadingJobs}
                onLoadResult={handleLoadResult}
              />
            )}
          </div>
        </div>
      </div>
    </>
  );
}
