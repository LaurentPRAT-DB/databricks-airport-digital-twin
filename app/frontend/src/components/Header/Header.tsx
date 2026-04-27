import { useCallback, type ReactNode } from 'react';
import { useFlightContext } from '../../context/FlightContext';
import { useAirportConfigContext } from '../../context/AirportConfigContext';
import { useTheme } from '../../context/ThemeContext';
import PlatformLinks from '../PlatformLinks/PlatformLinks';
import WeatherWidget from '../Weather/WeatherWidget';
import AirportSelector from '../AirportSelector/AirportSelector';
import AirportSwitchProgress from '../AirportSelector/AirportSwitchProgress';
import PhaseFilter from './PhaseFilter';

interface HeaderProps {
  onShowFIDS?: () => void;
  onShowKPI?: () => void;
  simulationControls?: ReactNode;
  dataModeToggle?: ReactNode;
}

export default function Header({ onShowFIDS, onShowKPI, simulationControls, dataModeToggle }: HeaderProps) {
  const { error, setSelectedFlight } = useFlightContext();
  const { currentAirport, isLoading: isLoadingAirport, error: airportError, loadAirport, switchProgress } = useAirportConfigContext();
  const { isDark, toggle: toggleTheme } = useTheme();

  // Clear flight selection before switching airports to avoid stale data
  const handleAirportChange = useCallback((icaoCode: string) => {
    setSelectedFlight(null);
    return loadAirport(icaoCode);
  }, [setSelectedFlight, loadAirport]);

  return (
    <header className="bg-slate-800 text-white px-4 py-3 flex items-center justify-between shadow-lg z-[1002] relative">
      {/* Airport switch progress overlay — only show when phased progress arrives from backend */}
      {switchProgress && (!switchProgress.done || switchProgress.error) && (
        <div className="fixed inset-0 bg-black/50 z-[2000] flex items-center justify-center">
          <AirportSwitchProgress
            progress={switchProgress}
            error={switchProgress.error ? (airportError || switchProgress.message) : undefined}
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

        {/* Data mode toggle — fixed position next to airport selector */}
        {dataModeToggle}
      </div>

      <div className="flex items-center gap-6">
        {/* Weather Widget */}
        <WeatherWidget station={currentAirport || undefined} />

        {/* Simulation Controls */}
        {simulationControls}

        {/* KPI Button */}
        {onShowKPI && (
          <button
            onClick={onShowKPI}
            className="flex items-center gap-2 bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded-lg text-sm transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            <span>KPI</span>
          </button>
        )}

        {/* FIDS Button */}
        {onShowFIDS && (
          <button
            onClick={onShowFIDS}
            className="flex items-center gap-2 bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded-lg text-sm transition-colors"
          >
            <span>FIDS</span>
          </button>
        )}

        {/* Dark mode toggle */}
        <button
          onClick={toggleTheme}
          className="p-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 transition-colors"
          title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {isDark ? (
            <svg className="w-4 h-4 text-amber-300" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" clipRule="evenodd" />
            </svg>
          ) : (
            <svg className="w-4 h-4 text-slate-300" fill="currentColor" viewBox="0 0 20 20">
              <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
            </svg>
          )}
        </button>

        {/* Phase filter dropdown */}
        <PhaseFilter />

        {/* WebSocket error toast — only for real errors */}
        {error && (
          <div className="fixed top-16 right-4 z-[2000] bg-red-900/95 border border-red-700 text-white px-4 py-3 rounded-lg shadow-xl max-w-sm animate-pulse">
            <div className="flex items-center gap-2">
              <span className="text-red-400 font-bold text-lg">!</span>
              <div>
                <div className="text-sm font-medium">Connection Error</div>
                <div className="text-xs text-red-300 mt-0.5">{error instanceof Error ? error.message : String(error)}</div>
              </div>
            </div>
          </div>
        )}

        {/* Platform Links */}
        <PlatformLinks />
      </div>
    </header>
  );
}
