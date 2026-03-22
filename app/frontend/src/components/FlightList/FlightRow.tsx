import { Flight } from '../../types/flight';
import { PHASE_BG_CLASSES, PHASE_SHORT_LABELS } from '../../utils/phaseUtils';

interface FlightRowProps {
  flight: Flight;
  isSelected: boolean;
  onClick: () => void;
}

export default function FlightRow({ flight, isSelected, onClick }: FlightRowProps) {
  const callsign = flight.callsign?.trim() || flight.icao24.toUpperCase();
  const altitude = flight.altitude !== null ? `${Math.round(flight.altitude)}ft` : '--';
  const velocity = flight.velocity !== null ? `${Math.round(flight.velocity)}kts` : '--';

  return (
    <button
      onClick={onClick}
      className={`
        w-full text-left px-3 py-2 border-b border-slate-200 dark:border-slate-700
        transition-colors duration-150 hover:bg-slate-100 dark:hover:bg-slate-700
        ${isSelected ? 'bg-blue-50 dark:bg-blue-900/30 border-l-4 border-l-blue-500' : ''}
      `}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className={`w-2 h-2 rounded-full ${PHASE_BG_CLASSES[flight.flight_phase] ?? 'bg-gray-500'}`}
            title={flight.flight_phase}
          />
          <span className="font-mono font-medium text-slate-800 dark:text-slate-200">
            {callsign}
          </span>
        </div>
        <span className={`
          text-xs px-1.5 py-0.5 rounded font-medium
          ${PHASE_BG_CLASSES[flight.flight_phase] ?? 'bg-gray-500'} text-white
        `}>
          {PHASE_SHORT_LABELS[flight.flight_phase] ?? flight.flight_phase}
        </span>
      </div>
      <div className="flex items-center gap-4 mt-1 text-xs text-slate-500 dark:text-slate-400">
        <span title="Altitude">ALT: {altitude}</span>
        <span title="Velocity">SPD: {velocity}</span>
      </div>
    </button>
  );
}
