import { useState } from 'react';
import { usePredictionDashboard, type KPICard, type CongestionRow, type DelayRow } from '../../hooks/usePredictionDashboard';

const COLOR_MAP: Record<string, { bg: string; text: string }> = {
  green: { bg: 'bg-green-50 border-green-200', text: 'text-green-600' },
  orange: { bg: 'bg-orange-50 border-orange-200', text: 'text-orange-600' },
  red: { bg: 'bg-red-50 border-red-200', text: 'text-red-600' },
  yellow: { bg: 'bg-yellow-50 border-yellow-200', text: 'text-yellow-600' },
  blue: { bg: 'bg-blue-50 border-blue-200', text: 'text-blue-600' },
  slate: { bg: 'bg-slate-50 border-slate-200', text: 'text-slate-600' },
};

const LEVEL_COLORS: Record<string, string> = {
  low: 'bg-green-100 text-green-700',
  moderate: 'bg-yellow-100 text-yellow-700',
  high: 'bg-orange-100 text-orange-700',
  critical: 'bg-red-100 text-red-700',
};

const CATEGORY_COLORS: Record<string, string> = {
  on_time: 'bg-green-100 text-green-700',
  slight: 'bg-yellow-100 text-yellow-700',
  moderate: 'bg-orange-100 text-orange-700',
  severe: 'bg-red-100 text-red-700',
};

const CATEGORY_LABELS: Record<string, string> = {
  on_time: 'On Time',
  slight: 'Slight',
  moderate: 'Moderate',
  severe: 'Severe',
};

function KPICardComponent({ card }: { card: KPICard }) {
  const colors = COLOR_MAP[card.color] || COLOR_MAP.slate;
  return (
    <div className={`rounded-lg border p-4 text-center ${colors.bg}`}>
      <div className={`text-2xl font-bold ${colors.text}`}>{card.value}</div>
      <div className="text-xs text-slate-500 font-medium uppercase tracking-wider mt-1">{card.label}</div>
    </div>
  );
}

function CongestionTable({ areas }: { areas: CongestionRow[] }) {
  if (areas.length === 0) return <div className="text-sm text-slate-400 py-4 text-center">No congestion data</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left">
            <th className="py-2 px-3 text-xs font-medium text-slate-500 uppercase">Area</th>
            <th className="py-2 px-3 text-xs font-medium text-slate-500 uppercase">Type</th>
            <th className="py-2 px-3 text-xs font-medium text-slate-500 uppercase">Level</th>
            <th className="py-2 px-3 text-xs font-medium text-slate-500 uppercase text-right">Flights</th>
            <th className="py-2 px-3 text-xs font-medium text-slate-500 uppercase text-right">Capacity</th>
            <th className="py-2 px-3 text-xs font-medium text-slate-500 uppercase text-right">Wait</th>
          </tr>
        </thead>
        <tbody>
          {areas.map((a) => (
            <tr key={a.area_id} className="border-b border-slate-100 hover:bg-slate-50">
              <td className="py-2 px-3 font-mono text-slate-700">{a.area_id}</td>
              <td className="py-2 px-3 text-slate-500 capitalize">{a.area_type}</td>
              <td className="py-2 px-3">
                <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${LEVEL_COLORS[a.level] || ''}`}>
                  {a.level}
                </span>
              </td>
              <td className="py-2 px-3 text-right font-mono">{a.flight_count}</td>
              <td className="py-2 px-3 text-right font-mono text-slate-400">{a.capacity}</td>
              <td className="py-2 px-3 text-right font-mono">{a.wait_minutes}m</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DelayTable({ delays }: { delays: DelayRow[] }) {
  if (delays.length === 0) return <div className="text-sm text-slate-400 py-4 text-center">No delay predictions</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left">
            <th className="py-2 px-3 text-xs font-medium text-slate-500 uppercase">Flight</th>
            <th className="py-2 px-3 text-xs font-medium text-slate-500 uppercase">Category</th>
            <th className="py-2 px-3 text-xs font-medium text-slate-500 uppercase text-right">Delay</th>
            <th className="py-2 px-3 text-xs font-medium text-slate-500 uppercase text-right">Confidence</th>
          </tr>
        </thead>
        <tbody>
          {delays.map((d) => (
            <tr key={d.icao24} className="border-b border-slate-100 hover:bg-slate-50">
              <td className="py-2 px-3 font-mono font-medium text-slate-700">{d.callsign || d.icao24}</td>
              <td className="py-2 px-3">
                <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${CATEGORY_COLORS[d.category] || ''}`}>
                  {CATEGORY_LABELS[d.category] || d.category}
                </span>
              </td>
              <td className="py-2 px-3 text-right font-mono">{d.delay_minutes != null && !isNaN(d.delay_minutes) ? (d.delay_minutes > 0 ? `+${d.delay_minutes}m` : '0m') : '—'}</td>
              <td className="py-2 px-3 text-right">
                <div className="flex items-center justify-end gap-2">
                  <div className="w-16 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                    <div className="h-full bg-blue-500 rounded-full" style={{ width: `${d.confidence * 100}%` }} />
                  </div>
                  <span className="font-mono text-slate-500 text-xs w-8 text-right">{Math.round(d.confidence * 100)}%</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Tab = 'overview' | 'congestion' | 'delays';

export default function KPIDashboard({ onClose }: { onClose: () => void }) {
  const { dashboard, isLoading, error } = usePredictionDashboard(true);
  const [activeTab, setActiveTab] = useState<Tab>('overview');
  const [isFullscreen, setIsFullscreen] = useState(false);

  const modalClass = isFullscreen
    ? 'fixed inset-4 z-[1100]'
    : 'fixed inset-x-8 top-16 bottom-8 z-[1100] max-w-5xl mx-auto';

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-[1099]" onClick={onClose} />
      <div className={`${modalClass} bg-white rounded-xl shadow-2xl flex flex-col overflow-hidden`}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
          <div>
            <h2 className="text-xl font-bold text-slate-800">ML Predictions Dashboard</h2>
            <p className="text-sm text-slate-500 mt-0.5">
              Real-time predictions across {dashboard?.total_flights ?? '...'} active flights
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setIsFullscreen(!isFullscreen)}
              className="p-2 text-slate-400 hover:text-slate-600 transition-colors"
              title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                {isFullscreen ? (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 9L4 4m0 0v4m0-4h4m6 10l5 5m0 0v-4m0 4h-4" />
                ) : (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5v-4m0 4h-4m4 0l-5-5" />
                )}
              </svg>
            </button>
            <button onClick={onClose} className="p-2 text-slate-400 hover:text-slate-600 transition-colors">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 px-6 pt-3 border-b border-slate-200">
          {(['overview', 'congestion', 'delays'] as Tab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                activeTab === tab
                  ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50/50'
                  : 'text-slate-500 hover:text-slate-700 hover:bg-slate-50'
              }`}
            >
              {tab === 'overview' ? 'Overview' : tab === 'congestion' ? 'Congestion' : 'Delay Forecast'}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {isLoading && (
            <div className="flex items-center justify-center h-40">
              <div className="flex items-center gap-3 text-slate-400">
                <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Loading predictions...
              </div>
            </div>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
              Failed to load predictions: {error.message}
            </div>
          )}

          {dashboard && !isLoading && (
            <>
              {/* KPI Cards — always visible */}
              <div className="grid grid-cols-4 lg:grid-cols-8 gap-3 mb-6">
                {dashboard.kpi_cards.map((card) => (
                  <KPICardComponent key={card.label} card={card} />
                ))}
              </div>

              {activeTab === 'overview' && (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider mb-3">Congestion Areas</h3>
                    <CongestionTable areas={dashboard.congestion_areas.slice(0, 10)} />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider mb-3">Delay Forecast</h3>
                    <DelayTable delays={dashboard.delay_table.slice(0, 10)} />
                  </div>
                </div>
              )}

              {activeTab === 'congestion' && (
                <div>
                  <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider mb-3">
                    All Congestion Areas ({dashboard.congestion_areas.length})
                  </h3>
                  <CongestionTable areas={dashboard.congestion_areas} />
                </div>
              )}

              {activeTab === 'delays' && (
                <div>
                  <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider mb-3">
                    All Flight Delay Predictions ({dashboard.delay_table.length})
                  </h3>
                  <DelayTable delays={dashboard.delay_table} />
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
