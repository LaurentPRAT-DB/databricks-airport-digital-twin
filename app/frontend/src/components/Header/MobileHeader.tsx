import { useState, useCallback, useRef } from 'react';
import { useFlightContext } from '../../context/FlightContext';
import { useAirportConfigContext } from '../../context/AirportConfigContext';
import WeatherWidget from '../Weather/WeatherWidget';
import AirportSelector from '../AirportSelector/AirportSelector';
import AirportSwitchProgress from '../AirportSelector/AirportSwitchProgress';
import PhaseFilter from './PhaseFilter';

interface MobileHeaderProps {
  onShowFIDS?: () => void;
  onShowKPI?: () => void;
  onOpenChat?: () => void;
  onGoToMap?: () => void;
}

export default function MobileHeader({ onShowFIDS, onShowKPI, onOpenChat, onGoToMap }: MobileHeaderProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const headerRef = useRef<HTMLElement>(null);
  const { isLoading, error, setSelectedFlight } = useFlightContext();
  const { currentAirport, isLoading: isLoadingAirport, error: airportError, loadAirport, switchProgress } = useAirportConfigContext();

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
        {/* Left: Airport selector + reload (tap reloads and goes to map) */}
        <div className="flex items-center gap-2">
          <AirportSelector
            currentAirport={currentAirport || undefined}
            onAirportChange={handleAirportChange}
            isLoading={isLoadingAirport}
          />
          {/* Reload / go-to-map button */}
          <button
            onClick={() => { onGoToMap?.(); }}
            className="p-1 rounded-md hover:bg-slate-700 transition-colors"
            aria-label="Return to map"
          >
            <svg className={`w-4 h-4 ${error ? 'text-red-400' : isLoading ? 'text-yellow-400 animate-spin' : 'text-green-400'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l5.447 2.724A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
            </svg>
          </button>
        </div>

        {/* Right: KPI + FIDS + Weather + Hamburger menu */}
        <div className="flex items-center gap-2">
          {onShowKPI && (
            <button
              onClick={onShowKPI}
              className="px-2 py-1 rounded bg-slate-700 text-xs font-medium text-slate-200"
            >
              KPI
            </button>
          )}
          {onShowFIDS && (
            <button
              onClick={onShowFIDS}
              className="px-2 py-1 rounded bg-slate-700 text-xs font-medium text-slate-200"
            >
              FIDS
            </button>
          )}
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
              top: headerRef.current ? headerRef.current.offsetTop + headerRef.current.offsetHeight : 52,
              maxHeight: `calc(100vh - ${headerRef.current ? headerRef.current.offsetTop + headerRef.current.offsetHeight : 52}px)`,
            }}
          >
            {/* Actions — uniform vertical menu */}
            <div className="flex flex-col mobile-menu-items">
              {/* Phase filter */}
              <div className="mobile-menu-embedded">
                <PhaseFilter />
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
              Airport Digital Twin v{__APP_VERSION__}
            </div>
          </div>
        </>
      )}
    </>
  );
}
