import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

interface DataOpsStats {
  timestamp: string;
  health: {
    acquisition: 'healthy' | 'degraded' | 'unhealthy';
    sync: 'healthy' | 'degraded' | 'unhealthy';
    freshness: 'healthy' | 'degraded' | 'unhealthy';
    overall: 'healthy' | 'degraded' | 'unhealthy';
  };
  summary: {
    total_acquisitions: number;
    total_records_acquired: number;
    total_syncs: number;
    records_synced: number;
    last_sync: string | null;
  };
  sync_status: {
    checked_at: string;
    delta: { record_count: number; staleness_seconds: number } | null;
    lakebase: { record_count: number; staleness_seconds: number } | null;
    in_sync: boolean;
    sync_lag_seconds: number | null;
    record_count_diff: number | null;
  };
  sources: Record<string, { count: number; records: number; errors: number }>;
  endpoints: Record<string, { count: number; records: number; errors: number }>;
  recent_acquisitions: Array<{
    timestamp: string;
    source: string;
    endpoint: string;
    record_count: number;
    latency_ms: number;
    success: boolean;
    error: string | null;
  }>;
  recent_syncs: Array<{
    timestamp: string;
    direction: string;
    records_synced: number;
    records_failed: number;
    latency_ms: number;
    success: boolean;
  }>;
}

const fetchDataOpsDashboard = async (): Promise<DataOpsStats> => {
  const response = await fetch('/api/data-ops/dashboard');
  if (!response.ok) throw new Error('Failed to fetch data ops dashboard');
  return response.json();
};

const triggerFreshnessCheck = async (): Promise<void> => {
  await fetch('/api/data-ops/check-freshness', { method: 'POST' });
};

const HealthBadge = ({ status }: { status: 'healthy' | 'degraded' | 'unhealthy' }) => {
  const colors = {
    healthy: 'bg-green-500',
    degraded: 'bg-yellow-500',
    unhealthy: 'bg-red-500',
  };

  return (
    <span className={`inline-block w-3 h-3 rounded-full ${colors[status]}`} />
  );
};

const formatTimestamp = (timestamp: string) => {
  const date = new Date(timestamp);
  return date.toLocaleTimeString();
};

const formatStaleness = (seconds: number): string => {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
};

interface DataOpsDashboardProps {
  onClose?: () => void;
}

export default function DataOpsDashboard({ onClose }: DataOpsDashboardProps) {
  const [isRefreshing, setIsRefreshing] = useState(false);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['dataOpsDashboard'],
    queryFn: fetchDataOpsDashboard,
    refetchInterval: 30000, // Auto-refresh every 30s
  });

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await triggerFreshnessCheck();
    // Wait a moment for the check to complete
    await new Promise(resolve => setTimeout(resolve, 1000));
    await refetch();
    setIsRefreshing(false);
  };

  if (isLoading) {
    return (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
        <div className="bg-slate-900 rounded-lg p-8">
          <div className="animate-pulse text-white">Loading Data Operations Dashboard...</div>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
        <div className="bg-slate-900 rounded-lg p-8">
          <div className="text-red-400">Error loading dashboard</div>
          <button
            onClick={() => refetch()}
            className="mt-4 px-4 py-2 bg-blue-600 text-white rounded"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 overflow-y-auto">
      <div className="bg-slate-900 rounded-lg w-full max-w-6xl m-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-slate-900 border-b border-slate-700 p-4 flex justify-between items-center">
          <div>
            <h2 className="text-xl font-bold text-white flex items-center gap-3">
              <HealthBadge status={data.health.overall} />
              Data Operations Dashboard
            </h2>
            <p className="text-slate-400 text-sm mt-1">
              Lakebase ↔ Unity Catalog Sync Monitoring
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleRefresh}
              disabled={isRefreshing}
              className="px-3 py-1 bg-blue-600 text-white rounded text-sm hover:bg-blue-500 disabled:opacity-50"
            >
              {isRefreshing ? 'Checking...' : 'Check Freshness'}
            </button>
            {onClose && (
              <button
                onClick={onClose}
                className="px-3 py-1 bg-slate-700 text-white rounded text-sm hover:bg-slate-600"
              >
                Close
              </button>
            )}
          </div>
        </div>

        <div className="p-4 space-y-6">
          {/* Health Summary */}
          <div className="grid grid-cols-4 gap-4">
            <div className="bg-slate-800 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <HealthBadge status={data.health.acquisition} />
                <span className="text-slate-400 text-sm">Acquisition</span>
              </div>
              <div className="text-2xl font-bold text-white">
                {data.summary.total_acquisitions}
              </div>
              <div className="text-slate-400 text-xs">
                {data.summary.total_records_acquired.toLocaleString()} records
              </div>
            </div>

            <div className="bg-slate-800 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <HealthBadge status={data.health.sync} />
                <span className="text-slate-400 text-sm">Sync</span>
              </div>
              <div className="text-2xl font-bold text-white">
                {data.summary.total_syncs}
              </div>
              <div className="text-slate-400 text-xs">
                {data.summary.records_synced.toLocaleString()} synced
              </div>
            </div>

            <div className="bg-slate-800 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <HealthBadge status={data.health.freshness} />
                <span className="text-slate-400 text-sm">Freshness</span>
              </div>
              <div className="text-2xl font-bold text-white">
                {data.sync_status.in_sync ? 'In Sync' : 'Out of Sync'}
              </div>
              <div className="text-slate-400 text-xs">
                {data.sync_status.sync_lag_seconds !== null
                  ? `Lag: ${formatStaleness(data.sync_status.sync_lag_seconds)}`
                  : 'No data'}
              </div>
            </div>

            <div className="bg-slate-800 rounded-lg p-4">
              <div className="text-slate-400 text-sm mb-2">Last Sync</div>
              <div className="text-xl font-bold text-white">
                {data.summary.last_sync
                  ? formatTimestamp(data.summary.last_sync)
                  : 'Never'}
              </div>
              <div className="text-slate-400 text-xs">
                {data.sync_status.record_count_diff !== null
                  ? `${data.sync_status.record_count_diff} record diff`
                  : ''}
              </div>
            </div>
          </div>

          {/* Sync Status Detail */}
          <div className="bg-slate-800 rounded-lg p-4">
            <h3 className="text-lg font-semibold text-white mb-4">Sync Status</h3>
            <div className="grid grid-cols-2 gap-8">
              {/* Delta (Unity Catalog) */}
              <div>
                <h4 className="text-slate-400 text-sm mb-2 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-blue-500" />
                  Unity Catalog (Delta)
                </h4>
                {data.sync_status.delta ? (
                  <div className="space-y-2">
                    <div className="flex justify-between">
                      <span className="text-slate-400">Records:</span>
                      <span className="text-white font-mono">
                        {data.sync_status.delta.record_count}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">Staleness:</span>
                      <span className={`font-mono ${
                        data.sync_status.delta.staleness_seconds > 300
                          ? 'text-yellow-400'
                          : 'text-green-400'
                      }`}>
                        {formatStaleness(data.sync_status.delta.staleness_seconds)}
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className="text-slate-500">No data available</div>
                )}
              </div>

              {/* Lakebase */}
              <div>
                <h4 className="text-slate-400 text-sm mb-2 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-green-500" />
                  Lakebase (PostgreSQL)
                </h4>
                {data.sync_status.lakebase ? (
                  <div className="space-y-2">
                    <div className="flex justify-between">
                      <span className="text-slate-400">Records:</span>
                      <span className="text-white font-mono">
                        {data.sync_status.lakebase.record_count}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">Staleness:</span>
                      <span className={`font-mono ${
                        data.sync_status.lakebase.staleness_seconds > 300
                          ? 'text-yellow-400'
                          : 'text-green-400'
                      }`}>
                        {formatStaleness(data.sync_status.lakebase.staleness_seconds)}
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className="text-slate-500">No data available</div>
                )}
              </div>
            </div>
          </div>

          {/* Data Sources */}
          <div className="bg-slate-800 rounded-lg p-4">
            <h3 className="text-lg font-semibold text-white mb-4">Data Sources</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-slate-400 border-b border-slate-700">
                    <th className="text-left py-2 px-3">Source</th>
                    <th className="text-right py-2 px-3">Calls</th>
                    <th className="text-right py-2 px-3">Records</th>
                    <th className="text-right py-2 px-3">Errors</th>
                    <th className="text-right py-2 px-3">Error Rate</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.sources).map(([source, stats]) => (
                    <tr key={source} className="border-b border-slate-700/50">
                      <td className="py-2 px-3 text-white font-mono">{source}</td>
                      <td className="py-2 px-3 text-right text-slate-300">{stats.count}</td>
                      <td className="py-2 px-3 text-right text-slate-300">
                        {stats.records.toLocaleString()}
                      </td>
                      <td className="py-2 px-3 text-right text-slate-300">{stats.errors}</td>
                      <td className="py-2 px-3 text-right">
                        <span className={stats.count > 0 && stats.errors / stats.count > 0.1
                          ? 'text-red-400'
                          : 'text-green-400'
                        }>
                          {stats.count > 0
                            ? `${((stats.errors / stats.count) * 100).toFixed(1)}%`
                            : '0%'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Recent Activity */}
          <div className="grid grid-cols-2 gap-4">
            {/* Recent Acquisitions */}
            <div className="bg-slate-800 rounded-lg p-4">
              <h3 className="text-lg font-semibold text-white mb-4">Recent Acquisitions</h3>
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {data.recent_acquisitions.length === 0 ? (
                  <div className="text-slate-500 text-sm">No recent acquisitions</div>
                ) : (
                  data.recent_acquisitions.slice(0, 10).map((acq, idx) => (
                    <div
                      key={idx}
                      className="flex items-center justify-between text-xs border-b border-slate-700/50 pb-2"
                    >
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${
                          acq.success ? 'bg-green-500' : 'bg-red-500'
                        }`} />
                        <span className="text-slate-400">
                          {formatTimestamp(acq.timestamp)}
                        </span>
                        <span className="text-white font-mono">{acq.source}</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-slate-400">
                          {acq.record_count} records
                        </span>
                        <span className="text-slate-500">
                          {Math.round(acq.latency_ms)}ms
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Recent Syncs */}
            <div className="bg-slate-800 rounded-lg p-4">
              <h3 className="text-lg font-semibold text-white mb-4">Recent Syncs</h3>
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {data.recent_syncs.length === 0 ? (
                  <div className="text-slate-500 text-sm">No sync operations recorded</div>
                ) : (
                  data.recent_syncs.map((sync, idx) => (
                    <div
                      key={idx}
                      className="flex items-center justify-between text-xs border-b border-slate-700/50 pb-2"
                    >
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${
                          sync.success ? 'bg-green-500' : 'bg-red-500'
                        }`} />
                        <span className="text-slate-400">
                          {formatTimestamp(sync.timestamp)}
                        </span>
                        <span className="text-white text-xs">{sync.direction}</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-green-400">
                          +{sync.records_synced}
                        </span>
                        {sync.records_failed > 0 && (
                          <span className="text-red-400">
                            -{sync.records_failed}
                          </span>
                        )}
                        <span className="text-slate-500">
                          {Math.round(sync.latency_ms)}ms
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="text-center text-slate-500 text-xs">
            Auto-refreshes every 30 seconds • Last updated: {formatTimestamp(data.timestamp)}
          </div>
        </div>
      </div>
    </div>
  );
}
