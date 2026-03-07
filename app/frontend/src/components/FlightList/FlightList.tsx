import { useState, useMemo } from 'react';
import { useFlightContext } from '../../context/FlightContext';
import FlightRow from './FlightRow';

type SortOption = 'callsign' | 'altitude';

export default function FlightList() {
  const { flights, selectedFlight, setSelectedFlight, isLoading } = useFlightContext();
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState<SortOption>('callsign');

  const filteredAndSortedFlights = useMemo(() => {
    let result = flights;

    // Filter by search query
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      result = result.filter(
        (flight) =>
          flight.callsign?.toLowerCase().includes(query) ||
          flight.icao24.toLowerCase().includes(query)
      );
    }

    // Sort flights
    result = [...result].sort((a, b) => {
      if (sortBy === 'callsign') {
        const callsignA = a.callsign?.trim() || a.icao24;
        const callsignB = b.callsign?.trim() || b.icao24;
        return callsignA.localeCompare(callsignB);
      } else if (sortBy === 'altitude') {
        const altA = a.altitude ?? -1;
        const altB = b.altitude ?? -1;
        return altB - altA; // Descending order for altitude
      }
      return 0;
    });

    return result;
  }, [flights, searchQuery, sortBy]);

  return (
    <div className="flex flex-col h-full bg-white border-r border-slate-200">
      {/* Header */}
      <div className="p-3 border-b border-slate-200 bg-slate-50">
        <h2 className="font-semibold text-slate-700 mb-2">
          Flights
          <span className="ml-2 text-sm font-normal text-slate-500">
            ({filteredAndSortedFlights.length})
          </span>
        </h2>

        {/* Search input */}
        <input
          id="flight-search"
          name="flight-search"
          type="text"
          placeholder="Search callsign..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="
            w-full px-3 py-1.5 text-sm border border-slate-300 rounded
            focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
          "
        />

        {/* Sort dropdown */}
        <div className="mt-2 flex items-center gap-2 text-sm">
          <label htmlFor="sort" className="text-slate-500">Sort:</label>
          <select
            id="sort"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as SortOption)}
            className="
              flex-1 px-2 py-1 border border-slate-300 rounded text-sm
              focus:outline-none focus:ring-2 focus:ring-blue-500
            "
          >
            <option value="callsign">Callsign (A-Z)</option>
            <option value="altitude">Altitude (High-Low)</option>
          </select>
        </div>
      </div>

      {/* Flight list */}
      <div className="flex-1 overflow-y-auto">
        {isLoading && flights.length === 0 ? (
          <div className="p-4 text-center text-slate-500">
            <div className="animate-spin h-6 w-6 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-2" />
            Loading flights...
          </div>
        ) : filteredAndSortedFlights.length === 0 ? (
          <div className="p-4 text-center text-slate-500">
            {searchQuery ? 'No flights match your search' : 'No flights available'}
          </div>
        ) : (
          filteredAndSortedFlights.map((flight) => (
            <FlightRow
              key={flight.icao24}
              flight={flight}
              isSelected={selectedFlight?.icao24 === flight.icao24}
              onClick={() => setSelectedFlight(
                selectedFlight?.icao24 === flight.icao24 ? null : flight
              )}
            />
          ))
        )}
      </div>
    </div>
  );
}
