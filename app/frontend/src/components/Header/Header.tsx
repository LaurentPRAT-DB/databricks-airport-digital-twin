import { useCallback, type ReactNode } from 'react';
import { useFlightContext } from '../../context/FlightContext';
import { useAirportConfigContext } from '../../context/AirportConfigContext';
import PlatformLinks from '../PlatformLinks/PlatformLinks';
import WeatherWidget from '../Weather/WeatherWidget';
import AirportSelector from '../AirportSelector/AirportSelector';
import AirportSwitchProgress from '../AirportSelector/AirportSwitchProgress';
import PhaseFilter from './PhaseFilter';

interface HeaderProps {
  onShowFIDS?: () => void;
  simulationControls?: ReactNode;
}

export default function Header({ onShowFIDS, simulationControls }: HeaderProps) {
  const { isLoading, error, lastUpdated, setSelectedFlight } = useFlightContext();
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

      </div>

      <div className="flex items-center gap-6">
        {/* Weather Widget */}
        <WeatherWidget station={currentAirport || undefined} />

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

        {/* Phase filter dropdown */}
        <PhaseFilter />

        {/* Connection status — compact dot with tooltip */}
        <span
          className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
            error
              ? 'bg-red-500'
              : isLoading
              ? 'bg-yellow-500 animate-pulse'
              : 'bg-green-500'
          }`}
          title={
            error
              ? 'Connection error'
              : isLoading
              ? 'Updating...'
              : `Connected${lastUpdated ? ' · ' + new Date(lastUpdated).toLocaleTimeString() : ''}`
          }
        />

        {/* Platform Links */}
        <PlatformLinks />
      </div>
    </header>
  );
}
