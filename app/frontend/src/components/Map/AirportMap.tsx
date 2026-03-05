import { MapContainer, TileLayer } from 'react-leaflet';
import { AIRPORT_CENTER, DEFAULT_ZOOM } from '../../constants/airportLayout';
import AirportOverlay from './AirportOverlay';
import FlightMarker from './FlightMarker';
import { useFlights } from '../../hooks/useFlights';

export default function AirportMap() {
  const { flights, isLoading, error, lastUpdated } = useFlights();

  return (
    <div className="relative h-full w-full">
      <MapContainer
        center={AIRPORT_CENTER}
        zoom={DEFAULT_ZOOM}
        className="h-full w-full"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <AirportOverlay />
        {flights.map((flight) => (
          <FlightMarker key={flight.icao24} flight={flight} />
        ))}
      </MapContainer>

      {/* Status overlay */}
      <div className="absolute bottom-4 left-4 bg-white/90 backdrop-blur-sm rounded-lg shadow-lg p-3 z-[1000]">
        <div className="text-sm">
          <div className="flex items-center gap-2">
            <span className="font-medium">Flights:</span>
            <span className="font-mono">{flights.length}</span>
            {isLoading && (
              <span className="text-blue-500 animate-pulse">Updating...</span>
            )}
          </div>
          {lastUpdated && (
            <div className="text-gray-500 text-xs mt-1">
              Last updated: {new Date(lastUpdated).toLocaleTimeString()}
            </div>
          )}
          {error && (
            <div className="text-red-500 text-xs mt-1">
              Error: {error.message}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
