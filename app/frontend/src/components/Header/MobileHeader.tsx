import { useState, useCallback, type ReactNode } from 'react';
import { useFlightContext } from '../../context/FlightContext';
import { useAirportConfigContext } from '../../context/AirportConfigContext';
import { useTheme } from '../../context/ThemeContext';
import PlatformLinks from '../PlatformLinks/PlatformLinks';
import WeatherWidget from '../Weather/WeatherWidget';
import AirportSelector from '../AirportSelector/AirportSelector';
import AirportSwitchProgress from '../AirportSelector/AirportSwitchProgress';
import PhaseFilter from './PhaseFilter';

interface MobileHeaderProps {
  onShowFIDS?: () => void;
  simulationControls?: ReactNode;
}

export default function MobileHeader({ onShowFIDS, simulationControls }: MobileHeaderProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const { isLoading, error, setSelectedFlight } = useFlightContext();
  const { currentAirport, isLoading: isLoadingAirport, error: airportError, loadAirport, switchProgress } = useAirportConfigContext();
  const { isDark, toggle: toggleTheme } = useTheme();

  const handleAirportChange = useCallback((icaoCode: string) => {
    setSelectedFlight(null);
    return loadAirport(icaoCode);
  }, [setSelectedFlight, loadAirport]);

  return (
    <>
      {/* Airport switch progress overlay */}
      {(isLoadingAirport || switchProgress) && (
        <div className="fixed inset-0 bg-black/50 z-[2000] flex items-center justify-center">
          <AirportSwitchProgress
            progress={switchProgress && (!switchProgress.done || switchProgress.error) ? switchProgress : { step: 0, total: 7, message: 'Loading airport data, please wait...', done: false }}
            error={switchProgress?.error ? (airportError || switchProgress.message) : undefined}
          />
        </div>
      )}

      <header className="bg-slate-800 text-white px-3 py-2 flex items-center justify-between shadow-lg z-[1002] relative">
        {/* Left: Airport selector */}
        <div className="flex items-center gap-2">
          <AirportSelector
            currentAirport={currentAirport || undefined}
            onAirportChange={handleAirportChange}
            isLoading={isLoadingAirport}
          />
          {/* Connection status dot */}
          <span
            className={`w-2 h-2 rounded-full flex-shrink-0 ${
              error ? 'bg-red-500' : isLoading ? 'bg-yellow-500 animate-pulse' : 'bg-green-500'
            }`}
          />
        </div>

        {/* Right: Hamburger menu */}
        <button
          onClick={() => setMenuOpen(!menuOpen)}
          className="p-2 rounded-lg hover:bg-slate-700 transition-colors"
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
        >
          {menuOpen ? (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          ) : (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          )}
        </button>
      </header>

      {/* Dropdown menu */}
      {menuOpen && (
        <>
          <div className="fixed inset-0 z-[1001]" onClick={() => setMenuOpen(false)} />
          <div className="absolute left-0 right-0 top-[44px] bg-slate-800 border-b border-slate-700 shadow-xl z-[1002] p-4 space-y-4">
            {/* Weather */}
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-400 uppercase tracking-wide">Weather</span>
              <WeatherWidget station={currentAirport || undefined} />
            </div>

            {/* Simulation Controls */}
            {simulationControls && (
              <div>
                <span className="text-xs text-slate-400 uppercase tracking-wide block mb-2">Simulation</span>
                {simulationControls}
              </div>
            )}

            {/* Actions row */}
            <div className="flex items-center gap-2 flex-wrap">
              {/* FIDS */}
              {onShowFIDS && (
                <button
                  onClick={() => { onShowFIDS(); setMenuOpen(false); }}
                  className="flex items-center gap-2 bg-slate-700 hover:bg-slate-600 px-3 py-2 rounded-lg text-sm transition-colors"
                >
                  FIDS
                </button>
              )}

              {/* Dark mode toggle */}
              <button
                onClick={toggleTheme}
                className="p-2 rounded-lg bg-slate-700 hover:bg-slate-600 transition-colors"
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

              {/* Phase filter */}
              <PhaseFilter />

              {/* Platform links */}
              <PlatformLinks />
            </div>

            {/* Version */}
            <div className="text-[10px] text-slate-500 pt-2 border-t border-slate-700">
              Airport Digital Twin v{__APP_VERSION__} · #{__BUILD_NUMBER__}
            </div>
          </div>
        </>
      )}
    </>
  );
}
