import { useFlightContext } from '../../context/FlightContext';
import { Flight } from '../../types/flight';

const phaseColors: Record<Flight['flight_phase'], string> = {
  ground: 'bg-gray-500',
  climbing: 'bg-green-500',
  descending: 'bg-orange-500',
  cruising: 'bg-blue-500',
};

const phaseLabels: Record<Flight['flight_phase'], string> = {
  ground: 'Ground',
  climbing: 'Climbing',
  descending: 'Descending',
  cruising: 'Cruising',
};

interface DetailRowProps {
  label: string;
  value: string | number | null | undefined;
  unit?: string;
}

function DetailRow({ label, value, unit }: DetailRowProps) {
  const displayValue = value !== null && value !== undefined ? value : '--';
  return (
    <div className="flex justify-between items-center py-1.5 border-b border-slate-100 last:border-b-0">
      <span className="text-slate-500 text-sm">{label}</span>
      <span className="font-mono text-slate-800 text-sm">
        {displayValue}
        {unit && value !== null && value !== undefined && (
          <span className="text-slate-400 ml-1">{unit}</span>
        )}
      </span>
    </div>
  );
}

export default function FlightDetail() {
  const { selectedFlight, setSelectedFlight } = useFlightContext();

  if (!selectedFlight) {
    return (
      <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
        <h3 className="font-semibold text-slate-700 mb-3">Flight Details</h3>
        <div className="text-center text-slate-400 py-8">
          <svg
            className="w-12 h-12 mx-auto mb-2 text-slate-300"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M5 13l4 4L19 7"
            />
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M12 4v1m6 6h1m-2.5-5.5l.707.707M6.343 17.657l-.707.707M4 12H3m2.5-5.5l-.707.707M17.657 17.657l.707.707"
            />
          </svg>
          <p className="text-sm">Select a flight to view details</p>
        </div>
      </div>
    );
  }

  const { flight_phase, callsign, icao24, latitude, longitude, altitude, velocity, heading, vertical_rate, last_seen, data_source } = selectedFlight;

  return (
    <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-slate-700">Flight Details</h3>
        <button
          onClick={() => setSelectedFlight(null)}
          className="text-slate-400 hover:text-slate-600 transition-colors"
          title="Close"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Callsign and Phase Badge */}
      <div className="flex items-center justify-between mb-4 pb-3 border-b border-slate-200">
        <div>
          <div className="text-2xl font-bold font-mono text-slate-800">
            {callsign?.trim() || icao24.toUpperCase()}
          </div>
          <div className="text-xs text-slate-400 mt-0.5">ICAO: {icao24}</div>
        </div>
        <span className={`
          px-3 py-1 rounded-full text-sm font-medium text-white
          ${phaseColors[flight_phase]}
        `}>
          {phaseLabels[flight_phase]}
        </span>
      </div>

      {/* Position Section */}
      <div className="mb-4">
        <div className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-2">
          Position
        </div>
        <DetailRow label="Latitude" value={latitude?.toFixed(4)} />
        <DetailRow label="Longitude" value={longitude?.toFixed(4)} />
        <DetailRow label="Altitude" value={altitude !== null ? Math.round(altitude) : null} unit="ft" />
      </div>

      {/* Movement Section */}
      <div className="mb-4">
        <div className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-2">
          Movement
        </div>
        <DetailRow label="Speed" value={velocity !== null ? Math.round(velocity) : null} unit="kts" />
        <DetailRow label="Heading" value={heading !== null ? Math.round(heading) : null} unit="deg" />
        <DetailRow label="Vertical Rate" value={vertical_rate !== null ? Math.round(vertical_rate) : null} unit="ft/min" />
      </div>

      {/* Metadata Section */}
      <div>
        <div className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-2">
          Metadata
        </div>
        <DetailRow label="Data Source" value={data_source} />
        <DetailRow label="Last Seen" value={new Date(last_seen).toLocaleTimeString()} />
      </div>
    </div>
  );
}
