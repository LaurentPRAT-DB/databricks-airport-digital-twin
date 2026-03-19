import { useFlightContext } from '../../context/FlightContext';
import { Flight } from '../../types/flight';
import { useDelayPrediction, useGateRecommendations } from '../../hooks/usePredictions';
import { useTrajectory } from '../../hooks/useTrajectory';
import TurnaroundTimeline from './TurnaroundTimeline';
import BaggageStatus from '../Baggage/BaggageStatus';

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

const delayColors: Record<string, string> = {
  on_time: 'bg-green-500',
  slight: 'bg-yellow-500',
  moderate: 'bg-orange-500',
  severe: 'bg-red-500',
};

const delayLabels: Record<string, string> = {
  on_time: 'On Time',
  slight: 'Slight Delay',
  moderate: 'Moderate Delay',
  severe: 'Severe Delay',
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
  const { selectedFlight, setSelectedFlight, showTrajectory, setShowTrajectory } = useFlightContext();

  // Fetch predictions for selected flight
  const { delay, isLoading: isDelayLoading } = useDelayPrediction(
    selectedFlight?.icao24 ?? null
  );
  const { recommendations, isLoading: isGateLoading } = useGateRecommendations(
    selectedFlight?.icao24 ?? null,
    3
  );

  // Fetch trajectory when enabled
  const { data: trajectoryData, isLoading: isTrajectoryLoading } = useTrajectory(
    selectedFlight?.icao24 ?? null,
    showTrajectory
  );

  // Show gate recommendations only for descending flights (pre-arrival optimization).
  // Ground flights either have a gate (PARKED/TAXI_TO_GATE) or are departing.
  const needsGateAssignment =
    selectedFlight?.flight_phase === 'descending';

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

  const { flight_phase, callsign, icao24, latitude, longitude, altitude, velocity, heading, vertical_rate, last_seen, data_source, aircraft_type, origin_airport, destination_airport, assigned_gate } = selectedFlight;

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

      {/* Route (Origin → Destination) */}
      {(origin_airport || destination_airport) && (
        <div className="mb-4 pb-3 border-b border-slate-200">
          <div className="flex items-center justify-between">
            <div className="text-center flex-1">
              <div className="text-lg font-bold font-mono text-slate-800">
                {origin_airport || '---'}
              </div>
              <div className="text-xs text-slate-400">Origin</div>
            </div>
            <div className="px-3 text-slate-300">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
              </svg>
            </div>
            <div className="text-center flex-1">
              <div className="text-lg font-bold font-mono text-slate-800">
                {destination_airport || '---'}
              </div>
              <div className="text-xs text-slate-400">Destination</div>
            </div>
          </div>
          {aircraft_type && (
            <div className="text-center mt-1">
              <span className="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded">
                {aircraft_type}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Trajectory Toggle */}
      <div className="mb-4 pb-3 border-b border-slate-200">
        <button
          onClick={() => setShowTrajectory(!showTrajectory)}
          className={`w-full flex items-center justify-between px-3 py-2 rounded-lg border transition-colors ${
            showTrajectory
              ? 'bg-blue-50 border-blue-200 text-blue-700'
              : 'bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100'
          }`}
        >
          <div className="flex items-center gap-2">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
            <span className="font-medium text-sm">Show Trajectory</span>
          </div>
          <div className="flex items-center gap-2">
            {isTrajectoryLoading && (
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            )}
            {showTrajectory && trajectoryData && (
              <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
                {trajectoryData.count} pts
              </span>
            )}
            <div className={`w-10 h-6 rounded-full p-1 transition-colors ${
              showTrajectory ? 'bg-blue-500' : 'bg-slate-300'
            }`}>
              <div className={`w-4 h-4 rounded-full bg-white shadow transition-transform ${
                showTrajectory ? 'translate-x-4' : 'translate-x-0'
              }`} />
            </div>
          </div>
        </button>
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

      {/* Delay Prediction Section */}
      <div className="mb-4">
        <div className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-2">
          Delay Prediction
        </div>
        {isDelayLoading ? (
          <div className="text-sm text-slate-400">Loading predictions...</div>
        ) : delay ? (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span
                  className={`w-2 h-2 rounded-full ${
                    delayColors[delay.category] || 'bg-gray-500'
                  }`}
                />
                <span className="text-sm text-slate-600 font-medium">
                  {delayLabels[delay.category] || delay.category}
                </span>
              </div>
              <span className="font-mono text-slate-800 text-sm">
                +{delay.delay_minutes.toFixed(0)}m
              </span>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex-1 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-500 rounded-full"
                  style={{ width: `${delay.confidence * 100}%` }}
                />
              </div>
              <span className="font-mono text-slate-500 text-xs">
                {(delay.confidence * 100).toFixed(0)}%
              </span>
            </div>
          </div>
        ) : (
          <div className="text-sm text-slate-400">No prediction available</div>
        )}
      </div>

      {/* Gate Recommendation Section (only for arriving flights) */}
      {needsGateAssignment && (
        <div className="mb-4">
          <div className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-2">
            Gate Recommendations
          </div>
          {isGateLoading ? (
            <div className="text-sm text-slate-400">Loading recommendations...</div>
          ) : recommendations.length > 0 ? (
            <div className="space-y-2">
              {recommendations.map((rec, index) => (
                <div
                  key={rec.gate_id}
                  className={`p-2 rounded border ${
                    index === 0
                      ? 'border-blue-200 bg-blue-50'
                      : 'border-slate-100 bg-slate-50'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-mono font-semibold text-slate-800">
                      {rec.gate_id}
                    </span>
                    <span className="text-xs text-slate-500">
                      Score: {(rec.score * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="text-xs text-slate-500 mb-1">
                    Taxi time: {rec.taxi_time} min
                  </div>
                  {rec.reasons.length > 0 && (
                    <ul className="text-xs text-slate-500 list-disc list-inside">
                      {rec.reasons.slice(0, 2).map((reason, i) => (
                        <li key={i}>{reason}</li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-slate-400">No recommendations available</div>
          )}
        </div>
      )}

      {/* Turnaround Timeline (for ground flights) */}
      {flight_phase === 'ground' && (
        <div className="mb-4">
          <TurnaroundTimeline
            icao24={icao24}
            gate={assigned_gate || (recommendations.length > 0 ? recommendations[0].gate_id : undefined)}
            aircraftType={aircraft_type || 'A320'}
          />
        </div>
      )}

      {/* Baggage Status (for all flights with callsign) */}
      {callsign?.trim() && (
        <div className="mb-4">
          <BaggageStatus
            flightNumber={callsign.trim()}
            aircraftType={aircraft_type || 'A320'}
            isArrival={flight_phase === 'ground' || flight_phase === 'descending'}
          />
        </div>
      )}

      {/* Metadata Section */}
      <div>
        <div className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-2">
          Metadata
        </div>
        <DetailRow label="Data Source" value={data_source} />
        <DetailRow label="Last Seen" value={
          typeof last_seen === 'number'
            ? new Date(last_seen * 1000).toLocaleTimeString()
            : new Date(last_seen).toLocaleTimeString()
        } />
      </div>
    </div>
  );
}
