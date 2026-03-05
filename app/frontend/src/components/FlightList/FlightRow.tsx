import { Flight } from '../../types/flight';

interface FlightRowProps {
  flight: Flight;
  isSelected: boolean;
  onClick: () => void;
}

const phaseColors: Record<Flight['flight_phase'], string> = {
  ground: 'bg-gray-500',
  climbing: 'bg-green-500',
  descending: 'bg-orange-500',
  cruising: 'bg-blue-500',
};

const phaseLabels: Record<Flight['flight_phase'], string> = {
  ground: 'GND',
  climbing: 'CLB',
  descending: 'DSC',
  cruising: 'CRZ',
};

export default function FlightRow({ flight, isSelected, onClick }: FlightRowProps) {
  const callsign = flight.callsign?.trim() || flight.icao24.toUpperCase();
  const altitude = flight.altitude !== null ? `${Math.round(flight.altitude)}ft` : '--';
  const velocity = flight.velocity !== null ? `${Math.round(flight.velocity)}kts` : '--';

  return (
    <button
      onClick={onClick}
      className={`
        w-full text-left px-3 py-2 border-b border-slate-200
        transition-colors duration-150 hover:bg-slate-100
        ${isSelected ? 'bg-blue-50 border-l-4 border-l-blue-500' : ''}
      `}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className={`w-2 h-2 rounded-full ${phaseColors[flight.flight_phase]}`}
            title={flight.flight_phase}
          />
          <span className="font-mono font-medium text-slate-800">
            {callsign}
          </span>
        </div>
        <span className={`
          text-xs px-1.5 py-0.5 rounded font-medium
          ${phaseColors[flight.flight_phase]} text-white
        `}>
          {phaseLabels[flight.flight_phase]}
        </span>
      </div>
      <div className="flex items-center gap-4 mt-1 text-xs text-slate-500">
        <span title="Altitude">ALT: {altitude}</span>
        <span title="Velocity">SPD: {velocity}</span>
      </div>
    </button>
  );
}
