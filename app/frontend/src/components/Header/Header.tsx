import { useCallback, type ReactNode } from 'react';
import { useFlightContext } from '../../context/FlightContext';
import { useAirportConfigContext } from '../../context/AirportConfigContext';
import PlatformLinks from '../PlatformLinks/PlatformLinks';
import WeatherWidget from '../Weather/WeatherWidget';
import AirportSelector from '../AirportSelector/AirportSelector';
import AirportSwitchProgress from '../AirportSelector/AirportSwitchProgress';
import { CompanyLogo } from '../BrandIcon/CompanyLogo';

interface HeaderProps {
  onShowFIDS?: () => void;
  onShowKPI?: () => void;
  simulationControls?: ReactNode;
  dataModeToggle?: ReactNode;
  initTimings?: Record<string, number | string> | null;
}

export default function Header({ onShowFIDS, onShowKPI, simulationControls, dataModeToggle, initTimings }: HeaderProps) {
  const { error, setSelectedFlight } = useFlightContext();
  const { currentAirport, isLoading: isLoadingAirport, error: airportError, loadAirport, switchProgress } = useAirportConfigContext();

  const handleAirportChange = useCallback((icaoCode: string) => {
    setSelectedFlight(null);
    return loadAirport(icaoCode);
  }, [setSelectedFlight, loadAirport]);

  return (
    <header className="bg-slate-800 text-white px-4 flex items-center h-14 shadow-lg z-[1002] relative">
      {/* Airport switch progress overlay */}
      {switchProgress && (!switchProgress.done || switchProgress.error) && (
        <div className="fixed inset-0 bg-black/50 z-[2000] flex items-center justify-center">
          <AirportSwitchProgress
            progress={switchProgress}
            error={switchProgress.error ? (airportError || switchProgress.message) : undefined}
          />
        </div>
      )}

      {/* Left — App title */}
      <div className="flex-shrink-0 mr-4">
        <h1 className="text-lg font-bold leading-tight">Airport Digital Twin</h1>
        <div className="flex items-center gap-2">
          <span
            className="text-[10px] text-slate-500"
            title={`Built ${__BUILD_TIME__}`}
          >
            v{__APP_VERSION__}
          </span>
          {initTimings && typeof initTimings.total_ready === 'number' && (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/60 text-emerald-400 font-mono"
              title={Object.entries(initTimings)
                .map(([k, v]) => `${k}: ${typeof v === 'number' ? `${(v * 1000).toFixed(0)}ms` : v}`)
                .join('\n')}
            >
              init {(initTimings.total_ready as number).toFixed(1)}s
            </span>
          )}
        </div>
      </div>

      {/* Center — all action buttons */}
      <div className="flex-1 flex items-center justify-center gap-2">
        <AirportSelector
          currentAirport={currentAirport || undefined}
          onAirportChange={handleAirportChange}
          isLoading={isLoadingAirport}
        />

        {dataModeToggle}

        <WeatherWidget station={currentAirport || undefined} />

        {simulationControls}

        {onShowKPI && (
          <button
            onClick={onShowKPI}
            className="flex items-center gap-1.5 h-8 bg-slate-700 hover:bg-slate-600 px-3 rounded-lg text-sm transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            <span>KPI</span>
          </button>
        )}

        {onShowFIDS && (
          <button
            onClick={onShowFIDS}
            className="flex items-center gap-1.5 h-8 bg-slate-700 hover:bg-slate-600 px-3 rounded-lg text-sm transition-colors"
          >
            <span>FIDS</span>
          </button>
        )}

        <PlatformLinks />
      </div>

      {/* Right — Company logo */}
      <div className="flex-shrink-0 ml-4">
        <CompanyLogo />
      </div>

      {/* WebSocket error toast */}
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
    </header>
  );
}
