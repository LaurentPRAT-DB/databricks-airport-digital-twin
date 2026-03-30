import { useState, useCallback, useRef } from 'react';
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
  onOpenChat?: () => void;
}

export default function MobileHeader({ onShowFIDS, onOpenChat }: MobileHeaderProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const headerRef = useRef<HTMLElement>(null);
  const { isLoading, error, setSelectedFlight, selectedFlight, showTrajectory, setShowTrajectory } = useFlightContext();
  const { currentAirport, isLoading: isLoadingAirport, error: airportError, loadAirport, switchProgress } = useAirportConfigContext();
  const { isDark, toggle: toggleTheme } = useTheme();

  const handleAirportChange = useCallback((icaoCode: string) => {
    setSelectedFlight(null);
    return loadAirport(icaoCode);
  }, [setSelectedFlight, loadAirport]);

  return (
    <>
      {/* Airport switch progress overlay — only show when phased progress arrives from backend */}
      {switchProgress && (!switchProgress.done || switchProgress.error) && (
        <div className="fixed inset-0 bg-black/50 z-[2000] flex items-center justify-center">
          <AirportSwitchProgress
            progress={switchProgress}
            error={switchProgress.error ? (airportError || switchProgress.message) : undefined}
          />
        </div>
      )}

      <header ref={headerRef} className="bg-slate-800 text-white px-3 py-2 flex items-center justify-between shadow-lg z-[1002] relative">
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

        {/* Right: Weather + Hamburger menu */}
        <div className="flex items-center gap-2">
          <WeatherWidget station={currentAirport || undefined} />
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
        </div>
      </header>

      {/* Dropdown menu */}
      {menuOpen && (
        <>
          <div className="fixed inset-0 z-[1001]" onClick={() => setMenuOpen(false)} />
          <div
            className="fixed left-0 right-0 bg-slate-800 border-b border-slate-700 shadow-xl z-[1002] p-4 space-y-4 overflow-y-auto"
            style={{
              top: headerRef.current ? headerRef.current.offsetHeight : 52,
              maxHeight: `calc(100vh - ${headerRef.current ? headerRef.current.offsetHeight : 52}px)`,
            }}
          >
            {/* Actions — uniform vertical menu */}
            <div className="flex flex-col mobile-menu-items">
              {onShowFIDS && (
                <button
                  onClick={() => { onShowFIDS(); setMenuOpen(false); }}
                  className="mobile-menu-item"
                >
                  <svg className="w-5 h-5 text-slate-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7" />
                  </svg>
                  <span>Flight Information Display</span>
                </button>
              )}

              <button onClick={toggleTheme} className="mobile-menu-item">
                {isDark ? (
                  <svg className="w-5 h-5 text-amber-300 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" clipRule="evenodd" />
                  </svg>
                ) : (
                  <svg className="w-5 h-5 text-slate-300 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
                  </svg>
                )}
                <span>{isDark ? 'Light Mode' : 'Dark Mode'}</span>
              </button>

              {/* Trajectory toggle — only when a flight is selected */}
              {selectedFlight && (
                <button
                  onClick={() => setShowTrajectory(!showTrajectory)}
                  className="mobile-menu-item"
                >
                  <svg className={`w-5 h-5 flex-shrink-0 ${showTrajectory ? 'text-blue-400' : 'text-slate-400'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                  </svg>
                  <span>Trajectory Line</span>
                  <div className={`ml-auto w-10 h-6 rounded-full p-1 transition-colors ${
                    showTrajectory ? 'bg-blue-500' : 'bg-slate-600'
                  }`}>
                    <div className={`w-4 h-4 rounded-full bg-white shadow transition-transform ${
                      showTrajectory ? 'translate-x-4' : 'translate-x-0'
                    }`} />
                  </div>
                </button>
              )}

              {/* PhaseFilter & PlatformLinks: force their internal buttons to match */}
              <div className="mobile-menu-embedded">
                <PhaseFilter />
              </div>
              <div className="mobile-menu-embedded">
                <PlatformLinks />
              </div>

              {onOpenChat && (
                <button
                  onClick={() => { onOpenChat(); setMenuOpen(false); }}
                  className="mobile-menu-item"
                >
                  <svg className="w-5 h-5 text-blue-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                  </svg>
                  <span>Chat Assistant</span>
                </button>
              )}
            </div>

            {/* Inline styles to normalize embedded component buttons */}
            <style>{`
              .mobile-menu-item {
                display: flex;
                align-items: center;
                gap: 12px;
                width: 100%;
                padding: 10px 12px;
                border-radius: 8px;
                font-size: 14px;
                color: #e2e8f0;
                transition: background-color 150ms;
              }
              .mobile-menu-item:hover, .mobile-menu-item:active {
                background-color: rgba(51, 65, 85, 0.7);
              }
              .mobile-menu-embedded {
                width: 100%;
              }
              .mobile-menu-embedded > div {
                width: 100%;
              }
              .mobile-menu-embedded button:first-child,
              .mobile-menu-embedded > div > button {
                display: flex !important;
                align-items: center !important;
                gap: 12px !important;
                width: 100% !important;
                padding: 10px 12px !important;
                border-radius: 8px !important;
                font-size: 14px !important;
                color: #e2e8f0 !important;
                background: transparent !important;
                justify-content: flex-start !important;
                transition: background-color 150ms !important;
              }
              .mobile-menu-embedded button:first-child:hover,
              .mobile-menu-embedded > div > button:hover {
                background-color: rgba(51, 65, 85, 0.7) !important;
              }
            `}</style>

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
