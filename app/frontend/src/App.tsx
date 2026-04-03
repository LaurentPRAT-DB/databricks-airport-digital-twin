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
import FlightDetail from './components/FlightDetail/FlightDetail';
import GateStatus from './components/GateStatus/GateStatus';
import FIDS from './components/FIDS/FIDS';
import GenieChat from './components/GenieChat/GenieChat';
import MobileTabBar, { type MobileTab } from './components/MobileTabBar/MobileTabBar';
import { useIsMobile } from './hooks/useIsMobile';
import { useViewportState, SharedViewport } from './hooks/useViewportState';
import SimulationControls from './components/SimulationControls/SimulationControls';
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
function LoadingScreen({ airportCode, statusMessage }: { airportCode?: string; statusMessage?: string }) {
  const [dotCount, setDotCount] = useState(0);

  useEffect(() => {
    const dotTimer = setInterval(() => setDotCount((d) => (d + 1) % 4), 400);
    return () => clearInterval(dotTimer);
  }, []);

  return (
    <div className="h-screen w-screen flex flex-col items-center justify-center bg-slate-900 text-white">
      {/* Radar sweep animation */}
      <div className="relative w-32 h-32 mb-8">
        {/* Outer ring */}
        <div className="absolute inset-0 rounded-full border-2 border-slate-600" />
        {/* Middle ring */}
        <div className="absolute inset-4 rounded-full border border-slate-700" />
        {/* Inner ring */}
        <div className="absolute inset-8 rounded-full border border-slate-700" />
        {/* Center dot */}
        <div className="absolute inset-[3.5rem] rounded-full bg-emerald-500 shadow-[0_0_12px_rgba(16,185,129,0.6)]" />
        {/* Sweep line */}
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
        {/* Blips */}
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
      <h1 className="text-2xl font-bold mb-2">Airport Digital Twin</h1>
      {airportCode && (
        <p className="text-lg text-slate-400 mb-6 font-mono">{airportCode}</p>
      )}

      {/* Status text */}
      <p className="text-sm text-slate-400 h-5">
        {(statusMessage || 'Initializing')}{'.'.repeat(dotCount)}
      </p>

      {/* Inline keyframes for the radar sweep */}
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

function ViewToggle({
  viewMode,
  onToggle,
  satellite,
  onSatelliteToggle,
  inpainting,
  onInpaintingToggle,
}: {
  viewMode: ViewMode;
  onToggle: (mode: ViewMode) => void;
  satellite: boolean;
  onSatelliteToggle: (on: boolean) => void;
  inpainting: boolean;
  onInpaintingToggle: (on: boolean) => void;
}) {
  const [endpointStatus, setEndpointStatus] = useState<EndpointStatus>('unknown');
  const [statusMessage, setStatusMessage] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Stop polling on unmount or when inpainting is disabled
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // Stop polling when banner is dismissed (inpainting turned off or satellite off)
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

  const checkEndpointStatus = async (): Promise<'ready' | 'not_ready' | 'error'> => {
    try {
      const resp = await fetch('/api/inpainting/status');
      if (!resp.ok) return 'error';
      const data = await resp.json();
      if (data.ready === 'READY') return 'ready';
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
        // Auto-enable inpainting
        onInpaintingToggle(true);
      }
    }, 5000);
  };

  const handleCleanTilesClick = async () => {
    // If already on, just turn off
    if (inpainting) {
      onInpaintingToggle(false);
      setEndpointStatus('unknown');
      setStatusMessage('');
      return;
    }

    // Check endpoint status first
    setEndpointStatus('checking');
    setStatusMessage('Checking endpoint...');
    const result = await checkEndpointStatus();

    if (result === 'ready') {
      setEndpointStatus('ready');
      setStatusMessage('');
      onInpaintingToggle(true);
    } else if (result === 'not_ready') {
      setEndpointStatus('not_ready');
      setStatusMessage('Inpainting endpoint is not running (scaled to zero).');
    } else {
      setEndpointStatus('error');
      setStatusMessage('Could not reach the inpainting endpoint.');
    }
  };

  const handleWakeEndpoint = async () => {
    setEndpointStatus('waking');
    setStatusMessage('Starting endpoint... This may take 2-5 minutes.');
    try {
      const resp = await fetch('/api/inpainting/wake', { method: 'POST' });
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

  const dismissBanner = () => {
    setEndpointStatus('unknown');
    setStatusMessage('');
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const showBanner = endpointStatus === 'not_ready' || endpointStatus === 'waking' || endpointStatus === 'error';

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
        {satellite && (
          <button
            onClick={handleCleanTilesClick}
            disabled={endpointStatus === 'checking'}
            className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-lg shadow-md transition-colors ${
              inpainting
                ? 'bg-emerald-600 text-white'
                : endpointStatus === 'checking'
                  ? 'bg-gray-400 text-white cursor-wait'
                  : 'bg-white dark:bg-slate-700 text-gray-700 dark:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-600'
            }`}
            title={inpainting ? 'Show original satellite tiles' : 'Remove aircraft from satellite tiles'}
          >
            {endpointStatus === 'checking' ? (
              <svg className="animate-spin w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
              </svg>
            )}
            Clean Tiles
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

function AppContent({ handleSimFlightsChange, handleTrajectoryProviderChange }: { handleSimFlightsChange: (flights: Flight[] | null) => void; handleTrajectoryProviderChange: (provider: ((icao24: string) => import('./hooks/useSimulationReplay').SimTrajectoryPoint[]) | null) => void }) {
  const isMobile = useIsMobile();
  const [viewMode, setViewMode] = useState<ViewMode>('2d');
  const [satellite, setSatellite] = useState(false);
  const [inpainting, setInpainting] = useState(false);
  const [showFIDS, setShowFIDS] = useState(false);
  const [backendReady, setBackendReady] = useState(false);
  const [statusMessage, setStatusMessage] = useState('Initializing');
  const [, setSimulationActive] = useState(false);
  const [simTime, setSimTime] = useState<string | null>(null);
  const [demoReady, setDemoReady] = useState(false);
  const [openskyAvailable, setOpenskyAvailable] = useState(false);
  const [mobileTab, setMobileTab] = useState<MobileTab>('map');
  const [showChat, setShowChat] = useState(false);

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
  const { flights, filteredFlights, selectedFlight, setSelectedFlight } = useFlightContext();
  const { currentAirport, refresh: refreshConfig, loadAirport } = useAirportConfigContext();

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

  // Poll /api/ready until backend signals readiness (and demo_ready)
  useEffect(() => {
    const poll = setInterval(async () => {
      try {
        const res = await fetch('/api/ready');
        if (res.ok) {
          const data = await res.json();
          setStatusMessage(data.status || 'Initializing');
          if (data.ready && !backendReady) {
            setBackendReady(true);
            refreshConfig();
          }
          if (data.demo_ready && !demoReady) {
            setDemoReady(true);
          }
          if (data.opensky_available === true) {
            setOpenskyAvailable(true);
          }
          // Stop polling once both are ready
          if (data.ready && data.demo_ready) {
            clearInterval(poll);
          }
        }
      } catch {
        // Backend not up yet — keep polling
      }
    }, 1500);

    // Also fire immediately on mount
    (async () => {
      try {
        const res = await fetch('/api/ready');
        if (res.ok) {
          const data = await res.json();
          setStatusMessage(data.status || 'Initializing');
          if (data.ready) {
            setBackendReady(true);
            refreshConfig();
          }
          if (data.demo_ready) {
            setDemoReady(true);
          }
          if (data.opensky_available === true) {
            setOpenskyAvailable(true);
          }
        }
      } catch {
        // ignore
      }
    })();

    return () => clearInterval(poll);
  }, [backendReady, demoReady, refreshConfig]);

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
    return <LoadingScreen airportCode={currentAirport || undefined} statusMessage={statusMessage} />;
  }

  const simulationControlsNode = (
    <SimulationControls
      onFlightsChange={handleSimFlightsChange}
      onActiveChange={setSimulationActive}
      onAirportChange={loadAirport}
      onTrajectoryProviderChange={handleTrajectoryProviderChange}
      onSimTimeChange={setSimTime}
      backendReady={backendReady}
      currentAirport={currentAirport}
      demoReady={demoReady}
      openskyAvailable={openskyAvailable}
    />
  );

  // Shared map view (used in both desktop and mobile layouts)
  const mapView = (
    <div className="flex-1 overflow-hidden relative">
      <ViewToggle viewMode={viewMode} onToggle={setViewMode} satellite={satellite} onSatelliteToggle={setSatellite} inpainting={inpainting} onInpaintingToggle={setInpainting} />
      <div className={`absolute inset-0 ${viewMode === '2d' ? '' : 'invisible pointer-events-none'}`}>
        <Suspense fallback={<MapLoadingFallback label="Loading Map..." />}>
          <AirportMap
            sharedViewport={viewport}
            onViewportChange={handle2DViewportChange}
            satellite={satellite}
            inpainting={inpainting && satellite}
            airportIcao={currentAirport ?? undefined}
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
              inpainting={inpainting && satellite}
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
      <div className="h-screen w-screen flex flex-col overflow-hidden">
        <MobileHeader
          onShowFIDS={() => setShowFIDS(true)}
          onOpenChat={() => setShowChat(true)}
        />
        {showFIDS && <FIDS onClose={() => setShowFIDS(false)} simTime={simTime} />}
        <GenieChat hideFab externalOpen={showChat} onClose={() => setShowChat(false)} />

        {/* Tab content */}
        <main className="flex-1 flex flex-col overflow-hidden">
          {mobileTab === 'map' && mapView}
          {mobileTab === 'flights' && (
            <div className="flex-1 overflow-hidden">
              <FlightList />
            </div>
          )}
          {mobileTab === 'info' && (
            <div className="flex-1 overflow-y-auto bg-slate-50 dark:bg-slate-800 p-4 space-y-4">
              <FlightDetail />
              <GateStatus />
            </div>
          )}
        </main>

        {/* Simulation controls — header buttons hidden, fixed PlaybackBar still renders */}
        <div className="h-0 overflow-hidden">{simulationControlsNode}</div>

        <MobileTabBar activeTab={mobileTab} onTabChange={setMobileTab} />
      </div>
    );
  }

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden">
      <Header onShowFIDS={() => setShowFIDS(true)} simulationControls={simulationControlsNode} />
      {showFIDS && <FIDS onClose={() => setShowFIDS(false)} simTime={simTime} />}
      <GenieChat />
      <main className="flex-1 flex overflow-hidden">
        {/* Left panel: Flight List */}
        <div className="w-64 flex-shrink-0 overflow-hidden">
          <FlightList />
        </div>

        {/* Center: Airport Map (2D or 3D) */}
        {mapView}

        {/* Right panel: Flight Detail + Gate Status */}
        <div className="w-80 flex-shrink-0 overflow-y-auto bg-slate-50 dark:bg-slate-800 p-4 pb-16 space-y-4">
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

  const handleSimFlightsChange = useCallback((flights: Flight[] | null) => {
    setSimulationFlights(flights);
  }, []);

  // Wrap in useCallback-style ref to avoid re-render loops with function state
  const handleTrajectoryProviderChange = useCallback((provider: ((icao24: string) => import('./hooks/useSimulationReplay').SimTrajectoryPoint[]) | null) => {
    setSimTrajectoryProvider(() => provider);
  }, []);

  return (
    <ThemeProvider>
      <AirportConfigProvider>
        <FlightProvider simulationFlights={simulationFlights} simTrajectoryProvider={simTrajectoryProvider}>
          <CongestionFilterProvider>
            <AppContent handleSimFlightsChange={handleSimFlightsChange} handleTrajectoryProviderChange={handleTrajectoryProviderChange} />
          </CongestionFilterProvider>
        </FlightProvider>
      </AirportConfigProvider>
    </ThemeProvider>
  );
}

export default App;
