import { useState, lazy, Suspense } from 'react';
import { FlightProvider, useFlightContext } from './context/FlightContext';
import Header from './components/Header/Header';
import FlightList from './components/FlightList/FlightList';
import AirportMap from './components/Map/AirportMap';
import FlightDetail from './components/FlightDetail/FlightDetail';
import GateStatus from './components/GateStatus/GateStatus';
import FIDS from './components/FIDS/FIDS';

// Lazy load 3D map to reduce initial bundle size
const Map3D = lazy(() => import('./components/Map3D').then(m => ({ default: m.Map3D })));

// Loading fallback for 3D view
function Map3DLoadingFallback() {
  return (
    <div className="w-full h-full flex items-center justify-center bg-slate-900">
      <div className="text-center text-white">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-white mx-auto mb-4"></div>
        <p className="text-lg">Loading 3D View...</p>
      </div>
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
}: {
  viewMode: ViewMode;
  onToggle: (mode: ViewMode) => void;
}) {
  return (
    <div className="absolute top-4 right-4 z-[1001] flex bg-white rounded-lg shadow-md overflow-hidden">
      <button
        onClick={() => onToggle('2d')}
        className={`px-4 py-2 text-sm font-medium transition-colors ${
          viewMode === '2d'
            ? 'bg-blue-600 text-white'
            : 'bg-white text-gray-700 hover:bg-gray-100'
        }`}
      >
        2D
      </button>
      <button
        onClick={() => onToggle('3d')}
        className={`px-4 py-2 text-sm font-medium transition-colors ${
          viewMode === '3d'
            ? 'bg-blue-600 text-white'
            : 'bg-white text-gray-700 hover:bg-gray-100'
        }`}
      >
        3D
      </button>
    </div>
  );
}

function AppContent() {
  const [viewMode, setViewMode] = useState<ViewMode>('2d');
  const [showFIDS, setShowFIDS] = useState(false);
  const { flights, selectedFlight, setSelectedFlight } = useFlightContext();

  // Handler for 3D map flight selection (uses icao24 string)
  const handleFlightSelect = (icao24: string) => {
    const flight = flights.find((f) => f.icao24 === icao24);
    if (flight) {
      setSelectedFlight(flight);
    }
  };

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden">
      <Header onShowFIDS={() => setShowFIDS(true)} />
      {showFIDS && <FIDS onClose={() => setShowFIDS(false)} />}
      <main className="flex-1 flex overflow-hidden">
        {/* Left panel: Flight List */}
        <div className="w-80 flex-shrink-0 overflow-hidden">
          <FlightList />
        </div>

        {/* Center: Airport Map (2D or 3D) */}
        <div className="flex-1 overflow-hidden relative">
          <ViewToggle viewMode={viewMode} onToggle={setViewMode} />
          {viewMode === '2d' ? (
            <AirportMap />
          ) : (
            <Suspense fallback={<Map3DLoadingFallback />}>
              <Map3D
                flights={flights}
                selectedFlight={selectedFlight?.icao24 || null}
                onSelectFlight={handleFlightSelect}
              />
            </Suspense>
          )}
        </div>

        {/* Right panel: Flight Detail + Gate Status */}
        <div className="w-80 flex-shrink-0 overflow-y-auto bg-slate-50 p-4 space-y-4">
          <FlightDetail />
          <GateStatus />
        </div>
      </main>
    </div>
  );
}

function App() {
  return (
    <FlightProvider>
      <AppContent />
    </FlightProvider>
  );
}

export default App;
