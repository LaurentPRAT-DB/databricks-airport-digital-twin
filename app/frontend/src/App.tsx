import { useState, useEffect, useCallback, lazy, Suspense } from 'react';
import { FlightProvider, useFlightContext } from './context/FlightContext';
import { AirportConfigProvider, useAirportConfigContext } from './context/AirportConfigContext';
import { ThemeProvider } from './context/ThemeContext';
import Header from './components/Header/Header';
import FlightList from './components/FlightList/FlightList';
// Lazy load 2D map (Leaflet) to reduce initial bundle size — header + flight list render first
const AirportMap = lazy(() => import('./components/Map/AirportMap'));
import FlightDetail from './components/FlightDetail/FlightDetail';
import GateStatus from './components/GateStatus/GateStatus';
import FIDS from './components/FIDS/FIDS';
import GenieChat from './components/GenieChat/GenieChat';
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
function ViewToggle({
  viewMode,
  onToggle,
  satellite,
  onSatelliteToggle,
}: {
  viewMode: ViewMode;
  onToggle: (mode: ViewMode) => void;
  satellite: boolean;
  onSatelliteToggle: (on: boolean) => void;
}) {
  return (
    <div className="absolute top-4 right-4 z-[1001] flex items-center gap-2">
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
  }
}

function AppContent({ handleSimFlightsChange }: { handleSimFlightsChange: (flights: Flight[] | null) => void }) {
  const [viewMode, setViewMode] = useState<ViewMode>('2d');
  const [satellite, setSatellite] = useState(false);
  const [showFIDS, setShowFIDS] = useState(false);
  const [backendReady, setBackendReady] = useState(false);
  const [statusMessage, setStatusMessage] = useState('Initializing');
  const [, setSimulationActive] = useState(false);
  const [demoReady, setDemoReady] = useState(false);

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

  // Show loading screen until backend is ready
  if (!backendReady) {
    return <LoadingScreen airportCode={currentAirport || undefined} statusMessage={statusMessage} />;
  }

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden">
      <Header onShowFIDS={() => setShowFIDS(true)} simulationControls={
        <SimulationControls
          onFlightsChange={handleSimFlightsChange}
          onActiveChange={setSimulationActive}
          onAirportChange={loadAirport}
          backendReady={backendReady}
          currentAirport={currentAirport}
          demoReady={demoReady}
        />
      } />
      {showFIDS && <FIDS onClose={() => setShowFIDS(false)} />}
      <GenieChat />
      <main className="flex-1 flex overflow-hidden">
        {/* Left panel: Flight List */}
        <div className="w-80 flex-shrink-0 overflow-hidden">
          <FlightList />
        </div>

        {/* Center: Airport Map (2D or 3D) */}
        <div className="flex-1 overflow-hidden relative">
          <ViewToggle viewMode={viewMode} onToggle={setViewMode} satellite={satellite} onSatelliteToggle={setSatellite} />
          {/* Keep 2D map mounted (hidden) once loaded to avoid Leaflet re-init */}
          <div className={`absolute inset-0 ${viewMode === '2d' ? '' : 'invisible pointer-events-none'}`}>
            <Suspense fallback={<MapLoadingFallback label="Loading Map..." />}>
              <AirportMap
                sharedViewport={viewport}
                onViewportChange={handle2DViewportChange}
                satellite={satellite}
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
                />
              </Suspense>
            </div>
          )}
        </div>

        {/* Right panel: Flight Detail + Gate Status */}
        <div className="w-80 flex-shrink-0 overflow-y-auto bg-slate-50 dark:bg-slate-800 p-4 space-y-4">
          <FlightDetail />
          <GateStatus />
        </div>
      </main>
    </div>
  );
}

function App() {
  const [simulationFlights, setSimulationFlights] = useState<Flight[] | null>(null);

  const handleSimFlightsChange = useCallback((flights: Flight[] | null) => {
    setSimulationFlights(flights);
  }, []);

  return (
    <ThemeProvider>
      <AirportConfigProvider>
        <FlightProvider simulationFlights={simulationFlights}>
          <AppContent handleSimFlightsChange={handleSimFlightsChange} />
        </FlightProvider>
      </AirportConfigProvider>
    </ThemeProvider>
  );
}

export default App;
