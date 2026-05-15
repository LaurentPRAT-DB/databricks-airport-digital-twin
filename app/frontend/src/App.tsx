import { useState, useEffect, useCallback, useRef, lazy, Suspense } from 'react';
import { FlightProvider, useFlightContext } from './context/FlightContext';
import { AirportConfigProvider, useAirportConfigContext } from './context/AirportConfigContext';
import { ThemeProvider } from './context/ThemeContext';
import { CongestionFilterProvider } from './context/CongestionFilterContext';
import Header from './components/Header/Header';
import MobileHeader from './components/Header/MobileHeader';
import FlightList from './components/FlightList/FlightList';
// Lazy load 2D map (Leaflet) to reduce initial bundle size — header + flight list render first
const AirportMap = lazy(() => import('./components/Map/AirportMap'));
import type { TileEvent } from './components/Map/InpaintingOverlay';
import FlightDetail from './components/FlightDetail/FlightDetail';
import GateStatus from './components/GateStatus/GateStatus';
import FIDS from './components/FIDS/FIDS';
import KPIDashboard from './components/KPIDashboard/KPIDashboard';
import GenieChat from './components/GenieChat/GenieChat';
import MobileTabBar, { type MobileTab } from './components/MobileTabBar/MobileTabBar';
import { useIsMobile } from './hooks/useIsMobile';
import { useConnectionHealth } from './hooks/useConnectionHealth';
import { useViewportState, SharedViewport } from './hooks/useViewportState';
import { debugLogger } from './utils/debugLogger';
import SimulationControls, { DataModeToggle } from './components/SimulationControls/SimulationControls';
import { MaintenanceOverlay } from './components/MaintenanceOverlay/MaintenanceOverlay';
import { Flight } from './types/flight';

// Lazy load 3D map to reduce initial bundle size
const Map3D = lazy(() => import('./components/Map3D').then(m => ({ default: m.Map3D })));

// Loading fallback for map views
function MapLoadingFallback({ label }: { label: string }) {
  return (
    <div className="w-full h-full flex items-center justify-center bg-slate-900">
      <div className="text-center text-white">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-white mx-auto mb-4"></div>
        <p className="text-lg">{label}</p>
      </div>
    </div>
  );
}

/**
 * Full-screen loading overlay shown during initial data fetch.
 * Displays an animated radar sweep, airport name, and live backend status.
 */
interface InitStep {
  phase: number;
  label: string;
  status: 'running' | 'done' | 'error';
  detail: string;
  duration_ms: number;
}

function LoadingScreen({ airportCode, statusMessage, initSteps }: {
  airportCode?: string;
  statusMessage?: string;
  initSteps?: InitStep[];
}) {
  const [dotCount, setDotCount] = useState(0);

  useEffect(() => {
    const dotTimer = setInterval(() => setDotCount((d) => (d + 1) % 4), 400);
    return () => clearInterval(dotTimer);
  }, []);

  const formatDuration = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const steps = initSteps && initSteps.length > 0 ? initSteps : null;

  return (
    <div className="h-screen w-screen flex flex-col items-center justify-center bg-slate-900 text-white">
      {/* Radar sweep animation */}
      <div className="relative w-32 h-32 mb-6">
        <div className="absolute inset-0 rounded-full border-2 border-slate-600" />
        <div className="absolute inset-4 rounded-full border border-slate-700" />
        <div className="absolute inset-8 rounded-full border border-slate-700" />
        <div className="absolute inset-[3.5rem] rounded-full bg-emerald-500 shadow-[0_0_12px_rgba(16,185,129,0.6)]" />
        <div
          className="absolute inset-0 origin-center"
          style={{ animation: 'radar-sweep 2.4s linear infinite' }}
        >
          <div
            className="absolute left-1/2 bottom-1/2 w-0.5 h-1/2 origin-bottom"
            style={{
              background: 'linear-gradient(to top, rgba(16,185,129,0.8), transparent)',
            }}
          />
        </div>
        <div className="absolute w-1.5 h-1.5 rounded-full bg-emerald-400 top-6 left-10 animate-pulse" />
        <div
          className="absolute w-1.5 h-1.5 rounded-full bg-emerald-400 top-14 right-5 animate-pulse"
          style={{ animationDelay: '0.7s' }}
        />
        <div
          className="absolute w-1 h-1 rounded-full bg-emerald-400 bottom-8 left-7 animate-pulse"
          style={{ animationDelay: '1.4s' }}
        />
      </div>

      {/* Title */}
      <h1 className="text-2xl font-bold mb-1">Airport Digital Twin</h1>
      {airportCode && (
        <p className="text-lg text-slate-400 mb-4 font-mono">{airportCode}</p>
      )}

      {/* Init steps progress */}
      {steps ? (
        <div className="w-80 max-w-[90vw] mb-4">
          {steps.map((step) => (
            <div key={step.phase} className="flex items-center gap-2 py-1 text-xs font-mono">
              {/* Status icon */}
              <span className="w-4 text-center flex-shrink-0">
                {step.status === 'done' && <span className="text-emerald-400">&#10003;</span>}
                {step.status === 'error' && <span className="text-amber-400">!</span>}
                {step.status === 'running' && (
                  <span className="inline-block w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
                )}
              </span>
              {/* Label */}
              <span className={`flex-1 truncate ${
                step.status === 'running' ? 'text-blue-300' :
                step.status === 'error' ? 'text-amber-300' :
                'text-slate-500'
              }`}>
                {step.label}
              </span>
              {/* Duration */}
              {step.status !== 'running' && step.duration_ms > 0 && (
                <span className="text-slate-600 flex-shrink-0">
                  {formatDuration(step.duration_ms)}
                </span>
              )}
            </div>
          ))}
          {/* Total init time when all steps are done */}
          {steps.every((s) => s.status !== 'running') && (
            <div className="flex items-center gap-2 py-1 text-xs font-mono border-t border-slate-700 mt-1 pt-1">
              <span className="w-4 text-center flex-shrink-0 text-emerald-400">&#8721;</span>
              <span className="flex-1 text-emerald-300">Total init</span>
              <span className="text-emerald-400 font-semibold flex-shrink-0">
                {formatDuration(steps.reduce((sum, s) => sum + (s.duration_ms || 0), 0))}
              </span>
            </div>
          )}
          {/* Detail for the latest completed or running step */}
          {(() => {
            const reversed = [...steps].reverse();
            const active = reversed.find((s: InitStep) => s.status === 'running') ||
                           reversed.find((s: InitStep) => s.status === 'done' || s.status === 'error');
            return active?.detail ? (
              <p className="text-[10px] text-slate-600 mt-1 truncate pl-6">{active.detail}</p>
            ) : null;
          })()}
        </div>
      ) : (
        <p className="text-sm text-slate-400 h-5 mb-4">
          {(statusMessage || 'Connecting to backend')}{'.'.repeat(dotCount)}
        </p>
      )}

      <style>{`
        @keyframes radar-sweep {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

type ViewMode = '2d' | '3d';

/**
 * ViewToggle Component
 * Toggle button for switching between 2D and 3D map views
 */
type EndpointStatus = 'unknown' | 'checking' | 'ready' | 'not_ready' | 'waking' | 'error';

const INPAINTING_MIN_ZOOM = 17;

function ViewToggle({
  viewMode,
  onToggle,
  satellite,
  onSatelliteToggle,
  inpainting,
  onInpaintingToggle,
  airportIcao,
  staleTileCount = 0,
  warmingUp = false,
  tileActivityLog = [],
  mapZoom = 13,
}: {
  viewMode: ViewMode;
  onToggle: (mode: ViewMode) => void;
  satellite: boolean;
  onSatelliteToggle: (on: boolean) => void;
  inpainting: boolean;
  onInpaintingToggle: (on: boolean) => void;
  airportIcao?: string;
  staleTileCount?: number;
  warmingUp?: boolean;
  tileActivityLog?: TileEvent[];
  mapZoom?: number;
}) {
  const [endpointStatus, setEndpointStatus] = useState<EndpointStatus>('unknown');
  const [statusMessage, setStatusMessage] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Cache stats state
  interface CacheStats {
    total_tiles: number;
    total_aircraft_removed: number;
    cache_size: string;
    newest_tile: string | null;
  }
  const [cacheStats, setCacheStats] = useState<CacheStats | null>(null);
  const [, setPrevTileCount] = useState<number | null>(null);
  const [processing, setProcessing] = useState(false);
  const cacheStatsRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Stop polling on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (cacheStatsRef.current) clearInterval(cacheStatsRef.current);
    };
  }, []);

  // Stop endpoint polling when banner is dismissed (inpainting turned off or satellite off)
  useEffect(() => {
    if (!satellite || inpainting) {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      if (!satellite) {
        setEndpointStatus('unknown');
        setStatusMessage('');
      }
    }
  }, [satellite, inpainting]);

  // Auto-enable inpainting when satellite is turned on and endpoint is ready
  useEffect(() => {
    if (!satellite || inpainting) return;
    let cancelled = false;
    (async () => {
      const result = await checkEndpointStatus();
      if (cancelled) return;
      if (result === 'ready') {
        setEndpointStatus('ready');
        onInpaintingToggle(true);
      } else if (result === 'scaled_to_zero') {
        setEndpointStatus('waking');
        setStatusMessage('Waking up inpainting endpoint... (2-5 min)');
        handleWakeEndpoint();
      }
    })();
    return () => { cancelled = true; };
  }, [satellite]); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll cache stats while inpainting is active
  useEffect(() => {
    if (!inpainting || !satellite) {
      if (cacheStatsRef.current) {
        clearInterval(cacheStatsRef.current);
        cacheStatsRef.current = null;
      }
      setProcessing(false);
      setPrevTileCount(null);
      return;
    }

    const fetchStats = async () => {
      try {
        const resp = await fetch(`${import.meta.env.VITE_API_URL || ''}/api/inpainting/cache-stats`);
        if (!resp.ok) return;
        const data = await resp.json();
        if (data.error) return;
        setCacheStats(data);
        setPrevTileCount(prev => {
          if (prev !== null && data.total_tiles > prev) {
            setProcessing(true);
          } else if (prev !== null && data.total_tiles === prev) {
            setProcessing(false);
          }
          return data.total_tiles;
        });
      } catch { /* ignore */ }
    };

    // Fetch immediately, then poll
    setProcessing(true);
    fetchStats();
    cacheStatsRef.current = setInterval(fetchStats, 5000);
    return () => {
      if (cacheStatsRef.current) clearInterval(cacheStatsRef.current);
    };
  }, [inpainting, satellite]);

  const checkEndpointStatus = async (): Promise<'ready' | 'scaled_to_zero' | 'not_ready' | 'error'> => {
    try {
      const resp = await fetch(`${import.meta.env.VITE_API_URL || ''}/api/inpainting/status`);
      if (!resp.ok) return 'error';
      const data = await resp.json();
      if (data.status === 'error') {
        const detail = data.error || data.http_status ? `Error ${data.http_status}: ${data.error || 'permission denied'}` : '';
        setStatusMessage(detail || 'Endpoint returned an error.');
        return 'error';
      }
      if (data.ready === 'READY') {
        if (data.scaled_to_zero) return 'scaled_to_zero';
        return 'ready';
      }
      return 'not_ready';
    } catch {
      return 'error';
    }
  };

  const startPolling = () => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      const result = await checkEndpointStatus();
      if (result === 'ready') {
        setEndpointStatus('ready');
        setStatusMessage('Endpoint is ready!');
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        onInpaintingToggle(true);
      }
    }, 5000);
  };

  const handleCleanTilesClick = async () => {
    if (inpainting) {
      onInpaintingToggle(false);
      setEndpointStatus('unknown');
      setStatusMessage('');
      return;
    }

    setEndpointStatus('checking');
    setStatusMessage('Checking endpoint...');
    const result = await checkEndpointStatus();

    if (result === 'ready') {
      setEndpointStatus('ready');
      setStatusMessage('');
      onInpaintingToggle(true);
    } else if (result === 'scaled_to_zero') {
      setEndpointStatus('waking');
      setStatusMessage('Endpoint is scaled to zero. Waking up...');
      handleWakeEndpoint();
    } else if (result === 'not_ready') {
      setEndpointStatus('not_ready');
      setStatusMessage('Inpainting endpoint is not running.');
    } else {
      setEndpointStatus('error');
      // checkEndpointStatus may have already set a detailed message (e.g. 403)
      setStatusMessage((prev) => prev || 'Could not reach the inpainting endpoint.');
    }
  };

  const handleWakeEndpoint = async () => {
    setEndpointStatus('waking');
    setStatusMessage('Starting endpoint... This may take 2-5 minutes.');
    try {
      const resp = await fetch(`${import.meta.env.VITE_API_URL || ''}/api/inpainting/wake`, { method: 'POST' });
      const data = await resp.json();
      if (data.status === 'ready') {
        setEndpointStatus('ready');
        setStatusMessage('');
        onInpaintingToggle(true);
      } else {
        startPolling();
      }
    } catch {
      setEndpointStatus('error');
      setStatusMessage('Failed to send wake-up request.');
    }
  };

  const handleRefreshTiles = async () => {
    const params = airportIcao ? `?airport_icao=${airportIcao}` : '';
    setProcessing(true);
    try {
      const resp = await fetch(`${import.meta.env.VITE_API_URL || ''}/api/inpainting/reprocess${params}`, { method: 'POST' });
      if (resp.ok) {
        const result = await resp.json();
        if (result.reprocessed > 0) {
          // Tiles updated in cache — toggle to re-fetch from cache
          setCacheStats(null);
          setPrevTileCount(null);
          onInpaintingToggle(false);
          setTimeout(() => onInpaintingToggle(true), 100);
        }
      } else {
        // Fallback: clear cache and re-fetch everything
        await fetch(`${import.meta.env.VITE_API_URL || ''}/api/inpainting/cache${params}`, { method: 'DELETE' });
        setCacheStats(null);
        setPrevTileCount(null);
        onInpaintingToggle(false);
        setTimeout(() => onInpaintingToggle(true), 100);
      }
    } catch {
      // ignore
    } finally {
      setProcessing(false);
    }
  };

  const dismissBanner = () => {
    setEndpointStatus('unknown');
    setStatusMessage('');
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const showBanner = endpointStatus === 'not_ready' || endpointStatus === 'waking' || endpointStatus === 'error';

  const formatDate = (iso: string | null) => {
    if (!iso) return null;
    try {
      const d = new Date(iso);
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    } catch { return null; }
  };

  return (
    <div className="absolute top-4 right-4 z-[1001] flex flex-col items-end gap-2">
      <div className="flex items-center gap-2">
        <div className="flex bg-white dark:bg-slate-700 rounded-lg shadow-md overflow-hidden">
          <button
            onClick={() => onToggle('2d')}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              viewMode === '2d'
                ? 'bg-blue-600 text-white'
                : 'bg-white dark:bg-slate-700 text-gray-700 dark:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-600'
            }`}
          >
            2D
          </button>
          <button
            onClick={() => onToggle('3d')}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              viewMode === '3d'
                ? 'bg-blue-600 text-white'
                : 'bg-white dark:bg-slate-700 text-gray-700 dark:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-600'
            }`}
          >
            3D
          </button>
        </div>
        <button
          onClick={() => onSatelliteToggle(!satellite)}
          className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-lg shadow-md transition-colors ${
            satellite
              ? 'bg-blue-600 text-white'
              : 'bg-white dark:bg-slate-700 text-gray-700 dark:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-600'
          }`}
          title={satellite ? 'Switch to street map' : 'Switch to satellite view'}
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
            <path fillRule="evenodd" d="M8.157 2.176a1.5 1.5 0 0 0-1.147 0l-4.084 1.69A1.5 1.5 0 0 0 2 5.25v10.877a1.5 1.5 0 0 0 2.074 1.386l3.51-1.452 4.26 1.762a1.5 1.5 0 0 0 1.147 0l4.083-1.69A1.5 1.5 0 0 0 18 14.75V3.872a1.5 1.5 0 0 0-2.073-1.386l-3.51 1.452-4.26-1.762ZM7.58 5a.75.75 0 0 1 .75.75v6.5a.75.75 0 0 1-1.5 0v-6.5A.75.75 0 0 1 7.58 5Zm5.59 2.75a.75.75 0 0 0-1.5 0v6.5a.75.75 0 0 0 1.5 0v-6.5Z" clipRule="evenodd" />
          </svg>
          Satellite
        </button>
        {satellite && mapZoom >= INPAINTING_MIN_ZOOM && (
          <button
            onClick={handleCleanTilesClick}
            disabled={endpointStatus === 'checking'}
            className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-lg shadow-md transition-colors ${
              inpainting
                ? 'bg-emerald-600 text-white hover:bg-emerald-700'
                : endpointStatus === 'checking'
                  ? 'bg-gray-400 text-white cursor-wait'
                  : 'bg-white dark:bg-slate-700 text-gray-700 dark:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-600'
            }`}
            title={inpainting ? 'Click to disable AI tile cleaning' : 'Enable AI aircraft removal from satellite tiles'}
          >
            {endpointStatus === 'checking' ? (
              <svg className="animate-spin w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : inpainting ? (
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
              </svg>
            ) : (
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
              </svg>
            )}
            {inpainting ? 'Clean Tiles ON' : 'Clean Tiles'}
          </button>
        )}
      </div>

      {/* Endpoint status banner */}
      {showBanner && (
        <div className={`flex items-center gap-2 px-3 py-2 text-sm rounded-lg shadow-md ${
          endpointStatus === 'error'
            ? 'bg-red-600/90 text-white'
            : 'bg-amber-500/90 text-white'
        }`}>
          {endpointStatus === 'waking' && (
            <svg className="animate-spin w-4 h-4 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          )}
          <span>{statusMessage}</span>
          {endpointStatus === 'not_ready' && (
            <button
              onClick={handleWakeEndpoint}
              className="ml-1 px-2 py-0.5 bg-white/20 hover:bg-white/30 rounded text-xs font-medium transition-colors"
            >
              Start Endpoint
            </button>
          )}
          <button
            onClick={dismissBanner}
            className="ml-1 p-0.5 hover:bg-white/20 rounded transition-colors"
            title="Dismiss"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
            </svg>
          </button>
        </div>
      )}

      {/* Cache status panel — shown when inpainting is active and at working zoom */}
      {inpainting && satellite && mapZoom >= INPAINTING_MIN_ZOOM && (
        <div className="bg-slate-800/90 backdrop-blur text-white rounded-lg shadow-md px-3 py-3 text-xs max-w-[300px]">
          {warmingUp && !processing && !cacheStats?.total_tiles ? (
            <div className="flex items-center gap-2">
              <svg className="animate-spin w-3.5 h-3.5 flex-shrink-0 text-amber-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span className="text-amber-300 font-medium">
                GPU endpoint warming up... (2-5 min)
              </span>
            </div>
          ) : processing ? (
            <>
              <div className="flex items-center gap-2">
                <svg className="animate-spin w-3.5 h-3.5 flex-shrink-0 text-emerald-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <span className="text-emerald-300 font-medium">
                  Removing aircraft from tiles...
                </span>
              </div>
              {cacheStats && cacheStats.total_tiles > 0 && (
                <div className="mt-1.5 text-slate-400 pl-5.5">
                  {cacheStats.total_tiles} tile{cacheStats.total_tiles !== 1 ? 's' : ''} processed so far
                </div>
              )}
            </>
          ) : cacheStats && cacheStats.total_tiles > 0 ? (
            <>
              <div className="flex items-center gap-2">
                <svg className="w-3.5 h-3.5 flex-shrink-0 text-emerald-400" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                </svg>
                <span className="text-emerald-300 font-medium">
                  {cacheStats.total_tiles} tile{cacheStats.total_tiles !== 1 ? 's' : ''} cleaned &amp; cached
                </span>
              </div>
              <div className="mt-1.5 pl-5.5 text-slate-400">
                {formatDate(cacheStats.newest_tile) && <span>Last processed {formatDate(cacheStats.newest_tile)}</span>}
                {cacheStats.cache_size && <span> · {cacheStats.cache_size}</span>}
              </div>
              {staleTileCount > 0 && (
                <div className="mt-1.5 pl-5.5 flex items-center gap-1 text-amber-400">
                  <svg className="w-3 h-3 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.168 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
                  </svg>
                  <span>{staleTileCount} tile{staleTileCount !== 1 ? 's' : ''} have newer imagery available</span>
                </div>
              )}
              <button
                onClick={handleRefreshTiles}
                className="mt-2.5 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md bg-slate-600/80 hover:bg-slate-500/80 text-slate-200 font-medium transition-colors"
                title="Clear cache and re-process all tiles with AI inpainting"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
                  <path fillRule="evenodd" d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H4.28a.75.75 0 00-.75.75v3.955a.75.75 0 001.5 0v-2.137l.312.311a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39l-.293-.006zm.038-4.848a.75.75 0 00.75-.75V1.871a.75.75 0 00-1.5 0v2.137l-.312-.311a7 7 0 00-11.712 3.138.75.75 0 001.449.39 5.5 5.5 0 019.201-2.466l.312.311H11.3a.75.75 0 000 1.5h3.955a.75.75 0 00.094.006z" clipRule="evenodd" />
                </svg>
                Re-process Tiles
              </button>
            </>
          ) : (
            <div className="flex items-center gap-2 text-slate-400">
              <svg className="w-3.5 h-3.5 flex-shrink-0 text-emerald-400" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
              </svg>
              <span>Inpainting active — pan or zoom to process tiles</span>
            </div>
          )}

          {/* Tile activity log */}
          {tileActivityLog.length > 0 && (
            <div className="mt-2 pt-2 border-t border-slate-600/50">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Recent tiles</div>
              <div className="max-h-[120px] overflow-y-auto space-y-0.5 font-mono text-[10px] leading-relaxed">
                {tileActivityLog.slice(0, 20).map((evt) => (
                  <div key={`${evt.id}-${evt.timestamp}`} className="flex items-center gap-1.5">
                    <span className={evt.cacheStatus === 'HIT' ? 'text-emerald-400' : evt.cacheStatus === 'STALE' ? 'text-amber-400' : 'text-blue-400'}>
                      {evt.cacheStatus === 'HIT' ? '●' : evt.cacheStatus === 'STALE' ? '◐' : '⚡'}
                    </span>
                    <span className="text-slate-400">{evt.zoom}/{evt.tileX}/{evt.tileY}</span>
                    <span className={evt.cacheStatus === 'HIT' ? 'text-emerald-400/80' : 'text-slate-500'}>
                      {evt.cacheStatus}
                    </span>
                    {evt.aircraftCount > 0 && (
                      <span className="text-orange-400">{evt.aircraftCount} aircraft</span>
                    )}
                    {evt.processingMs != null && (
                      <span className="text-slate-500">{evt.processingMs.toLocaleString()}ms</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// TypeScript declarations for headless video renderer control APIs
declare global {
  interface Window {
    __viewControl?: {
      setViewMode: (mode: '2d' | '3d') => void;
      getViewMode: () => '2d' | '3d';
    };
    __airportControl?: {
      loadAirport: (icaoCode: string) => Promise<void>;
      getCurrentAirport: () => string | null;
    };
    __flightControl?: {
      selectFlight: (icao24: string | null) => void;
      getSelectedFlight: () => string | null;
      getSelectedFlightPosition: () => { lat: number; lon: number; alt: number } | null;
      getFlights: () => { icao24: string; callsign: string | null; flight_phase: string }[];
    };
  }
}

function AppContent({ handleSimFlightsChange, handleTrajectoryProviderChange, handleFlightLogProviderChange }: { handleSimFlightsChange: (flights: Flight[] | null) => void; handleTrajectoryProviderChange: (provider: ((icao24: string) => import('./hooks/useSimulationReplay').SimTrajectoryPoint[]) | null) => void; handleFlightLogProviderChange: (provider: ((icao24: string) => import('./hooks/useSimulationReplay').PositionSnapshot[]) | null) => void }) {
  const isMobile = useIsMobile();
  const [viewMode, setViewMode] = useState<ViewMode>('2d');
  const [satellite, setSatellite] = useState(false);
  const [inpainting, setInpainting] = useState(false);
  const [staleTileCount, setStaleTileCount] = useState(0);
  const [inpaintingWarmingUp, setInpaintingWarmingUp] = useState(false);
  const [tileActivityLog, setTileActivityLog] = useState<TileEvent[]>([]);
  const [showFIDS, setShowFIDS] = useState(false);
  const [showKPI, setShowKPI] = useState(false);
  const [backendReady, setBackendReady] = useState(false);
  const [statusMessage, setStatusMessage] = useState('Initializing');
  const [initSteps, setInitSteps] = useState<InitStep[]>([]);
  const [initTimings, setInitTimings] = useState<Record<string, number | string> | null>(null);
  const [, setSimulationActive] = useState(false);
  const [simTime, setSimTime] = useState<string | null>(null);
  const [openskyAvailable, setOpenskyAvailable] = useState(false);
  const [mobileTab, setMobileTab] = useState<MobileTab>('map');
  const [showChat, setShowChat] = useState(false);

  // Connection health: detect backend downtime and show maintenance overlay
  const { isDown, wasDown } = useConnectionHealth({ enabled: false });

  useEffect(() => {
    if (wasDown) {
      window.location.reload();
    }
  }, [wasDown]);

  // Close FIDS when switching between 2D/3D views
  useEffect(() => {
    setShowFIDS(false);
  }, [viewMode]);

  // Expose view control API on window for headless video renderer (Playwright)
  useEffect(() => {
    window.__viewControl = {
      setViewMode,
      getViewMode: () => viewMode,
    };
    return () => {
      delete window.__viewControl;
    };
  }, [viewMode, setViewMode]);

  // Prefetch 3D bundle after initial render so it loads faster when user switches
  useEffect(() => {
    const timer = setTimeout(() => {
      import('./components/Map3D').catch(() => {});
    }, 3000);
    return () => clearTimeout(timer);
  }, []);
  const { flights, filteredFlights, selectedFlight, setSelectedFlight, dataMode, setDataMode } = useFlightContext();
  const { currentAirport, loadAirport, initializeDefaultAirport, demoReady: wsDemoReady } = useAirportConfigContext();

  // Auto-switch to Info tab when a flight is newly selected on mobile
  const prevSelectedForTab = useRef(selectedFlight);
  useEffect(() => {
    if (isMobile && selectedFlight && !prevSelectedForTab.current) {
      setMobileTab('info');
    }
    prevSelectedForTab.current = selectedFlight;
  }, [isMobile, selectedFlight]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reset stale tile count when inpainting is toggled or airport changes
  useEffect(() => {
    setStaleTileCount(0);
  }, [inpainting, currentAirport]);

  const handleStaleTileDetected = useCallback(() => {
    setStaleTileCount((prev) => prev + 1);
  }, []);

  const handleInpaintingWarmingUp = useCallback(() => {
    setInpaintingWarmingUp(true);
  }, []);

  const handleTileActivity = useCallback((event: TileEvent) => {
    if (event.phase === 'loading') return;
    setTileActivityLog((prev) => {
      const next = [event, ...prev.filter((e) => e.id !== event.id)];
      return next.slice(0, 50);
    });
  }, []);

  // Turn off clean tiles (inpainting) when switching to recorded data mode
  // to avoid tile processing competing with recording loading
  useEffect(() => {
    if (dataMode === 'recorded' && inpainting) {
      setInpainting(false);
    }
  }, [dataMode]); // eslint-disable-line react-hooks/exhaustive-deps

  // Expose airport control API on window for headless video renderer (Playwright)
  useEffect(() => {
    window.__airportControl = {
      loadAirport,
      getCurrentAirport: () => currentAirport,
    };
    return () => {
      delete window.__airportControl;
    };
  }, [loadAirport, currentAirport]);

  // Expose flight control API on window for headless video renderer (Playwright)
  useEffect(() => {
    window.__flightControl = {
      selectFlight: (icao24: string | null) => {
        if (!icao24) {
          setSelectedFlight(null);
          return;
        }
        const flight = flights.find(f => f.icao24 === icao24);
        if (flight) setSelectedFlight(flight);
      },
      getSelectedFlight: () => selectedFlight?.icao24 ?? null,
      getSelectedFlightPosition: () => {
        if (!selectedFlight?.latitude || !selectedFlight?.longitude) return null;
        return { lat: selectedFlight.latitude, lon: selectedFlight.longitude, alt: selectedFlight.altitude ?? 0 };
      },
      getFlights: () => flights.map(f => ({ icao24: f.icao24, callsign: f.callsign, flight_phase: f.flight_phase })),
    };
    return () => {
      delete window.__flightControl;
    };
  }, [flights, selectedFlight, setSelectedFlight]);

  const { viewport, setViewport, setLastSource } = useViewportState();

  // Clear shared viewport when airport changes so map recenters on new airport
  useEffect(() => {
    setViewport(null);
  }, [currentAirport, setViewport]);

  // Viewport callbacks for 2D and 3D views
  const handle2DViewportChange = useCallback((vp: SharedViewport) => {
    setViewport(vp);
    setLastSource('2d');
  }, [setViewport, setLastSource]);

  const handle3DViewportChange = useCallback((vp: SharedViewport) => {
    setViewport(vp);
    setLastSource('3d');
  }, [setViewport, setLastSource]);

  // Poll /api/ready until backend signals readiness
  useEffect(() => {
    const handleReadyResponse = (data: Record<string, unknown>) => {
      setStatusMessage((data.status as string) || 'Initializing');
      if (Array.isArray(data.init_steps) && data.init_steps.length > 0) {
        setInitSteps(data.init_steps as InitStep[]);
      }
      if (data.ready && !backendReady) {
        setBackendReady(true);
        initializeDefaultAirport();
        if (data.debug_client_logs) debugLogger.enable();
        if (data.debug_client_logs) {
          const timings = data.init_timings as Record<string, number | string> | undefined;
          if (timings) setInitTimings(timings);
          const steps = data.init_steps as InitStep[] | undefined;
          console.group('%c[Airport Digital Twin] Init timings', 'color: #10b981; font-weight: bold');
          if (steps) {
            for (const s of steps) {
              const icon = s.status === 'done' ? '✓' : s.status === 'error' ? '!' : '∙';
              const ms = s.duration_ms > 0 ? `${s.duration_ms}ms` : '';
              console.log(`  ${icon} ${s.label}: ${ms} ${s.detail || ''}`);
            }
          }
          if (timings) {
            console.log(`  ∑ Total: ${typeof timings.total_ready === 'number' ? `${(timings.total_ready * 1000).toFixed(0)}ms` : timings.total_ready}`);
          }
          console.groupEnd();
        }
      }
      if (data.opensky_available === true) {
        setOpenskyAvailable(true);
      }
    };

    const poll = setInterval(async () => {
      try {
        const res = await fetch('/api/ready');
        if (res.ok) {
          const data = await res.json();
          handleReadyResponse(data);
          if (data.ready) clearInterval(poll);
        }
      } catch {
        // Backend not up yet — keep polling
      }
    }, 1500);

    // Also fire immediately on mount
    (async () => {
      try {
        const res = await fetch('/api/ready');
        if (res.ok) handleReadyResponse(await res.json());
      } catch {
        // ignore
      }
    })();

    return () => clearInterval(poll);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendReady, initializeDefaultAirport]);

  // Handler for 3D map flight selection (uses icao24 string)
  const handleFlightSelect = (icao24: string) => {
    const flight = flights.find((f) => f.icao24 === icao24);
    if (flight) {
      setSelectedFlight(flight);
    }
  };

  // Track previous selection (kept for potential future use)
  const prevSelectedRef = useRef(selectedFlight);
  useEffect(() => {
    prevSelectedRef.current = selectedFlight;
  }, [selectedFlight]);

  // Show loading screen until backend is ready
  if (!backendReady) {
    return <LoadingScreen airportCode={currentAirport || undefined} statusMessage={statusMessage} initSteps={initSteps} />;
  }

  // Show maintenance overlay when backend goes down during an active session
  if (isDown) {
    return <MaintenanceOverlay />;
  }

  const simulationControlsNode = (
    <SimulationControls
      onFlightsChange={handleSimFlightsChange}
      onActiveChange={setSimulationActive}
      onAirportChange={loadAirport}
      onTrajectoryProviderChange={handleTrajectoryProviderChange}
      onFlightLogProviderChange={handleFlightLogProviderChange}
      onSimTimeChange={setSimTime}
      backendReady={backendReady}
      currentAirport={currentAirport}
      demoReady={wsDemoReady}
    />
  );

  const dataModeToggleNode = (
    <DataModeToggle mode={dataMode} onChange={setDataMode} showLive={openskyAvailable} />
  );

  // Shared map view (used in both desktop and mobile layouts)
  const mapView = (
    <div className="flex-1 overflow-hidden relative">
      <ViewToggle viewMode={viewMode} onToggle={setViewMode} satellite={satellite} onSatelliteToggle={setSatellite} inpainting={inpainting} onInpaintingToggle={setInpainting} airportIcao={currentAirport ?? undefined} staleTileCount={staleTileCount} warmingUp={inpaintingWarmingUp} tileActivityLog={tileActivityLog} mapZoom={viewport?.zoom ?? 13} />
      <div className={`absolute inset-0 ${viewMode === '2d' ? '' : 'invisible pointer-events-none'}`}>
        <Suspense fallback={<MapLoadingFallback label="Loading Map..." />}>
          <AirportMap
            sharedViewport={viewport}
            onViewportChange={handle2DViewportChange}
            satellite={satellite}
            inpainting={inpainting && satellite}
            airportIcao={currentAirport ?? undefined}
            onStaleDetected={handleStaleTileDetected}
            onWarmingUp={handleInpaintingWarmingUp}
            onTileActivity={handleTileActivity}
          />
        </Suspense>
      </div>
      {viewMode === '3d' && (
        <div className="absolute inset-0">
          <Suspense fallback={<MapLoadingFallback label="Loading 3D View..." />}>
            <Map3D
              flights={filteredFlights}
              selectedFlight={selectedFlight?.icao24 || null}
              onSelectFlight={handleFlightSelect}
              sharedViewport={viewport}
              onViewportChange={handle3DViewportChange}
              satellite={satellite}
              airportIcao={currentAirport ?? undefined}
            />
          </Suspense>
        </div>
      )}
    </div>
  );

  console.log(`[App] rendering layout: ${isMobile ? 'MOBILE' : 'DESKTOP'}, viewport=${window.innerWidth}x${window.innerHeight}`);

  if (isMobile) {
    return (
      <div className="h-dvh w-screen flex flex-col overflow-hidden">
        <MobileHeader
          onShowFIDS={() => setShowFIDS(true)}
          onShowKPI={() => setShowKPI(true)}
          onOpenChat={() => setShowChat(true)}
          onGoToMap={() => setMobileTab('map')}
        />
        {showFIDS && <FIDS onClose={() => setShowFIDS(false)} simTime={simTime} />}
        {showKPI && <KPIDashboard onClose={() => setShowKPI(false)} />}
        <GenieChat hideFab externalOpen={showChat} onClose={() => setShowChat(false)} />

        {/* Tab content */}
        <main className="flex-1 flex flex-col overflow-hidden">
          {mobileTab === 'map' && mapView}
          {mobileTab === 'flights' && (
            selectedFlight ? (
              <div className="flex-1 flex flex-col overflow-hidden">
                <div className="h-[40%] min-h-[200px] relative [&>div]:!h-full [&>div]:!flex-none">
                  {mapView}
                </div>
                <div className="flex-1 overflow-hidden">
                  <FlightList />
                </div>
              </div>
            ) : (
              <div className="flex-1 overflow-hidden">
                <FlightList />
              </div>
            )
          )}
          {mobileTab === 'gates' && (
            selectedFlight ? (
              /* Split view: map on top, gate status on bottom */
              <div className="flex-1 flex flex-col overflow-hidden">
                <div className="h-[40%] min-h-[200px] relative [&>div]:!h-full [&>div]:!flex-none">
                  {mapView}
                </div>
                <div className="flex-1 overflow-y-auto bg-slate-50 dark:bg-slate-800 p-4">
                  <div className="flex items-center justify-end mb-2">
                    <button
                      onClick={() => setSelectedFlight(null)}
                      className="p-1.5 rounded-lg hover:bg-slate-700 transition-colors text-slate-400 hover:text-white"
                      aria-label="Close map"
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                  <GateStatus highlightGateRef={selectedFlight?.assigned_gate} />
                </div>
              </div>
            ) : (
              <div className="flex-1 overflow-y-auto bg-slate-50 dark:bg-slate-800 p-4">
                <GateStatus />
              </div>
            )
          )}
          {mobileTab === 'info' && (
            selectedFlight ? (
              /* Split view: map on top, flight details on bottom */
              <div className="flex-1 flex flex-col overflow-hidden">
                <div className="h-[40%] min-h-[200px] relative [&>div]:!h-full [&>div]:!flex-none">
                  {mapView}
                </div>
                <div className="flex-1 overflow-y-auto bg-slate-50 dark:bg-slate-800 p-4 space-y-4">
                  <div className="flex items-center justify-between">
                    <button
                      onClick={() => { setSelectedFlight(null); setMobileTab('map'); }}
                      className="flex items-center gap-1 text-sm text-blue-400 hover:text-blue-300"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                      </svg>
                      Back to map
                    </button>
                    <button
                      onClick={() => { setSelectedFlight(null); setMobileTab('map'); }}
                      className="p-1.5 rounded-lg hover:bg-slate-700 transition-colors text-slate-400 hover:text-white"
                      aria-label="Close"
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                  <FlightDetail />
                </div>
              </div>
            ) : (
              /* No flight selected: show flight detail placeholder */
              <div className="flex-1 overflow-y-auto bg-slate-50 dark:bg-slate-800 p-4 space-y-4">
                <div className="flex items-center justify-between">
                  <button
                    onClick={() => setMobileTab('map')}
                    className="flex items-center gap-1 text-sm text-blue-400 hover:text-blue-300"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                    Back to map
                  </button>
                  <button
                    onClick={() => setMobileTab('map')}
                    className="p-1.5 rounded-lg hover:bg-slate-700 transition-colors text-slate-400 hover:text-white"
                    aria-label="Close"
                  >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
                <FlightDetail />
              </div>
            )
          )}
        </main>

        {/* Simulation controls — show PlaybackBar when map is visible */}
        <div className={(mobileTab === 'map' || selectedFlight) ? '' : 'h-0 overflow-hidden'}>
          {simulationControlsNode}
        </div>

        <MobileTabBar activeTab={mobileTab} onTabChange={setMobileTab} />
      </div>
    );
  }

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden">
      <Header onShowFIDS={() => setShowFIDS(true)} onShowKPI={() => setShowKPI(true)} simulationControls={simulationControlsNode} dataModeToggle={dataModeToggleNode} initTimings={initTimings} />
      {showFIDS && <FIDS onClose={() => setShowFIDS(false)} simTime={simTime} />}
      {showKPI && <KPIDashboard onClose={() => setShowKPI(false)} />}
      <GenieChat />
      <main className="flex-1 flex overflow-hidden">
        {/* Left panel: Flight List + recorded mode indicator */}
        <div className="w-64 flex-shrink-0 flex flex-col overflow-hidden">
          <div className="flex-1 overflow-hidden" style={{ paddingBottom: 'var(--playbar-h, 0px)' }}>
            <FlightList />
          </div>
          {dataMode === 'recorded' && (
            <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-900/95 border-t-2 border-amber-500/60 text-xs text-amber-300">
              <div className="w-2 h-2 rounded-full bg-amber-400 animate-pulse flex-shrink-0" />
              <span className="font-semibold uppercase tracking-wider">Recorded</span>
              <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-800/40 ml-auto">
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14M12 5l7 7-7 7" />
                </svg>
                <span className="whitespace-nowrap">Real ADS-B</span>
              </div>
            </div>
          )}
        </div>

        {/* Center: Airport Map (2D or 3D) */}
        {mapView}

        {/* Right panel: Flight Detail + Gate Status */}
        <div className="w-80 flex-shrink-0 overflow-y-auto bg-slate-50 dark:bg-slate-800 p-4 space-y-4" style={{ paddingBottom: 'var(--playbar-h, 4rem)' }}>
          <FlightDetail />
          <GateStatus />
        </div>
      </main>
    </div>
  );
}

function App() {
  const [simulationFlights, setSimulationFlights] = useState<Flight[] | null>(null);
  const [simTrajectoryProvider, setSimTrajectoryProvider] = useState<((icao24: string) => import('./hooks/useSimulationReplay').SimTrajectoryPoint[]) | null>(null);
  const [simFlightLogProvider, setSimFlightLogProvider] = useState<((icao24: string) => import('./hooks/useSimulationReplay').PositionSnapshot[]) | null>(null);

  const handleSimFlightsChange = useCallback((flights: Flight[] | null) => {
    setSimulationFlights(flights);
  }, []);

  // Wrap in useCallback-style ref to avoid re-render loops with function state
  const handleTrajectoryProviderChange = useCallback((provider: ((icao24: string) => import('./hooks/useSimulationReplay').SimTrajectoryPoint[]) | null) => {
    setSimTrajectoryProvider(() => provider);
  }, []);

  const handleFlightLogProviderChange = useCallback((provider: ((icao24: string) => import('./hooks/useSimulationReplay').PositionSnapshot[]) | null) => {
    setSimFlightLogProvider(() => provider);
  }, []);

  return (
    <ThemeProvider>
      <AirportConfigProvider>
        <FlightProvider simulationFlights={simulationFlights} simTrajectoryProvider={simTrajectoryProvider} simFlightLogProvider={simFlightLogProvider}>
          <CongestionFilterProvider>
            <AppContent handleSimFlightsChange={handleSimFlightsChange} handleTrajectoryProviderChange={handleTrajectoryProviderChange} handleFlightLogProviderChange={handleFlightLogProviderChange} />
          </CongestionFilterProvider>
        </FlightProvider>
      </AirportConfigProvider>
    </ThemeProvider>
  );
}

export default App;
