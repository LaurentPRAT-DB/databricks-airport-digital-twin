import { useCallback, type ReactNode } from 'react';
import { useFlightContext } from '../../context/FlightContext';
import { useAirportConfigContext } from '../../context/AirportConfigContext';
import PlatformLinks from '../PlatformLinks/PlatformLinks';
import WeatherWidget from '../Weather/WeatherWidget';
import AirportSelector from '../AirportSelector/AirportSelector';
import AirportSwitchProgress from '../AirportSelector/AirportSwitchProgress';

interface HeaderProps {
  onShowFIDS?: () => void;
  simulationControls?: ReactNode;
}

export default function Header({ onShowFIDS, simulationControls }: HeaderProps) {
  const { flights, isLoading, error, lastUpdated, dataSource, setSelectedFlight } = useFlightContext();
  const { currentAirport, isLoading: isLoadingAirport, error: airportError, loadAirport, switchProgress } = useAirportConfigContext();

  // Clear flight selection before switching airports to avoid stale data
  const handleAirportChange = useCallback((icaoCode: string) => {
    setSelectedFlight(null);
    return loadAirport(icaoCode);
  }, [setSelectedFlight, loadAirport]);

  return (
    <header className="bg-slate-800 text-white px-4 py-3 flex items-center justify-between shadow-lg z-[1002] relative">
      {/* Airport switch progress overlay — full-screen to ensure visibility */}
      {(isLoadingAirport || switchProgress) && (
        <div className="fixed inset-0 bg-black/50 z-[2000] flex items-center justify-center">
          <AirportSwitchProgress
            progress={switchProgress && (!switchProgress.done || switchProgress.error) ? switchProgress : { step: 0, total: 7, message: 'Loading airport data, please wait...', done: false }}
            error={switchProgress?.error ? (airportError || switchProgress.message) : undefined}
          />
        </div>
      )}
      <div className="flex items-center gap-4">
        <h1 className="text-xl font-bold">Airport Digital Twin</h1>
        <span
          className="text-xs text-slate-500"
          title={`Built ${__BUILD_TIME__}`}
        >
          v{__APP_VERSION__} · #{__BUILD_NUMBER__}
        </span>

        {/* Airport Selector */}
        <AirportSelector
          currentAirport={currentAirport || undefined}
          onAirportChange={handleAirportChange}
          isLoading={isLoadingAirport}
        />

        <div className="flex items-center gap-2 bg-slate-700 px-3 py-1 rounded-full text-sm">
          <span className="text-slate-300">Flights:</span>
          <span className="font-mono font-medium">{flights.length}</span>
          {isLoading && (
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
          )}
        </div>
        {/* Data source indicator */}
        {dataSource && dataSource !== 'live' && (
          <div className="bg-amber-600 px-2 py-0.5 rounded-full text-xs font-medium cursor-default" title={`Using ${dataSource} data`}>
            Demo
          </div>
        )}
      </div>

      <div className="flex items-center gap-6">
        {/* Weather Widget */}
        <WeatherWidget />

        {/* Simulation Controls */}
        {simulationControls}

        {/* FIDS Button */}
        {onShowFIDS && (
          <button
            onClick={onShowFIDS}
            className="flex items-center gap-2 bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded-lg text-sm transition-colors"
          >
            <span>FIDS</span>
          </button>
        )}

        {/* Flight phase legend */}
        <div className="flex items-center gap-4 text-sm">
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-full bg-gray-500" />
            Ground
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-full bg-green-500" />
            Climbing
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-full bg-orange-500" />
            Descending
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-full bg-blue-500" />
            Cruising
          </span>
        </div>

        {/* Connection status */}
        <div className="flex items-center gap-2 text-sm">
          <span
            className={`w-2.5 h-2.5 rounded-full ${
              error
                ? 'bg-red-500'
                : isLoading
                ? 'bg-yellow-500 animate-pulse'
                : 'bg-green-500'
            }`}
          />
          <span className="text-slate-300">
            {error ? 'Error' : isLoading ? 'Updating' : 'Connected'}
          </span>
          {lastUpdated && !error && (
            <span className="text-slate-400 text-xs">
              {new Date(lastUpdated).toLocaleTimeString()}
            </span>
          )}
        </div>

        {/* Platform Links */}
        <PlatformLinks />
      </div>
    </header>
  );
}
