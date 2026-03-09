import { useEffect, useMemo } from 'react';
import { MapContainer, TileLayer, useMap } from 'react-leaflet';
import { AIRPORT_CENTER, DEFAULT_ZOOM } from '../../constants/airportLayout';
import AirportOverlay from './AirportOverlay';
import FlightMarker from './FlightMarker';
import TrajectoryLine from './TrajectoryLine';
import { useFlightContext } from '../../context/FlightContext';
import { useAirportConfigContext } from '../../context/AirportConfigContext';

/**
 * Recenters the map when the airport config changes (e.g., gate positions move).
 */
function MapRecenter() {
  const map = useMap();
  const { getGates, getTerminals, currentAirport } = useAirportConfigContext();

  const center = useMemo((): [number, number] | null => {
    // Compute center from terminals or gates
    const terminals = getTerminals();
    const gates = getGates();
    const items = terminals.length > 0 ? terminals : gates;

    if (items.length === 0) return null;

    let sumLat = 0, sumLon = 0, count = 0;
    for (const item of items) {
      const geo = (item as { geo?: { latitude?: number | string; longitude?: number | string } }).geo;
      const lat = Number(geo?.latitude);
      const lon = Number(geo?.longitude);
      if (lat && lon && !isNaN(lat) && !isNaN(lon)) {
        sumLat += lat;
        sumLon += lon;
        count++;
      }
    }
    if (count === 0) return null;
    return [sumLat / count, sumLon / count];
  }, [getGates, getTerminals]);

  useEffect(() => {
    if (center) {
      map.flyTo(center, DEFAULT_ZOOM, { duration: 1.5 });
    }
  }, [center, map, currentAirport]);

  return null;
}

export default function AirportMap() {
  const { flights, isLoading, error, lastUpdated } = useFlightContext();

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
        <MapRecenter />
        <AirportOverlay />
        <TrajectoryLine />
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
