/**
 * Airport Selector Component
 *
 * Dropdown for selecting airports by ICAO code.
 * Provides a list of well-known airports and a custom ICAO input.
 * Loads airport data from OpenStreetMap via the backend.
 */

import { useState, useEffect, useRef } from 'react';

interface AirportEntry {
  icao: string;
  iata: string;
  name: string;
  city: string;
}

const WELL_KNOWN_AIRPORTS: AirportEntry[] = [
  { icao: 'KSFO', iata: 'SFO', name: 'San Francisco International', city: 'San Francisco, CA' },
  { icao: 'KJFK', iata: 'JFK', name: 'John F. Kennedy International', city: 'New York, NY' },
  { icao: 'KLAX', iata: 'LAX', name: 'Los Angeles International', city: 'Los Angeles, CA' },
  { icao: 'KORD', iata: 'ORD', name: "O'Hare International", city: 'Chicago, IL' },
  { icao: 'KATL', iata: 'ATL', name: 'Hartsfield-Jackson Atlanta', city: 'Atlanta, GA' },
  { icao: 'EGLL', iata: 'LHR', name: 'London Heathrow', city: 'London, UK' },
  { icao: 'LFPG', iata: 'CDG', name: 'Charles de Gaulle', city: 'Paris, France' },
  { icao: 'OMAA', iata: 'AUH', name: 'Abu Dhabi International', city: 'Abu Dhabi, UAE' },
  { icao: 'OMDB', iata: 'DXB', name: 'Dubai International', city: 'Dubai, UAE' },
  { icao: 'RJTT', iata: 'HND', name: 'Tokyo Haneda', city: 'Tokyo, Japan' },
  { icao: 'VHHH', iata: 'HKG', name: 'Hong Kong International', city: 'Hong Kong' },
  { icao: 'WSSS', iata: 'SIN', name: 'Singapore Changi', city: 'Singapore' },
];

interface AirportSelectorProps {
  currentAirport?: string;
  onAirportChange: (icaoCode: string) => Promise<void>;
  isLoading?: boolean;
}

export default function AirportSelector({
  currentAirport,
  onAirportChange,
  isLoading = false,
}: AirportSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [customIcao, setCustomIcao] = useState('');
  const [loadError, setLoadError] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSelect = async (icaoCode: string) => {
    if (icaoCode === currentAirport) {
      setIsOpen(false);
      return;
    }
    setLoadError(null);
    setIsOpen(false);
    try {
      await onAirportChange(icaoCode);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load airport');
    }
  };

  const handleCustomSubmit = async () => {
    const code = customIcao.trim().toUpperCase();
    if (code.length >= 3) {
      setCustomIcao('');
      await handleSelect(code);
    }
  };

  // Find current airport info
  const currentInfo = WELL_KNOWN_AIRPORTS.find((a) => a.icao === currentAirport);
  const displayName = currentInfo
    ? `${currentInfo.icao} (${currentInfo.iata})`
    : currentAirport || 'Select Airport';

  return (
    <div ref={dropdownRef} className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        disabled={isLoading}
        className={`
          flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium
          transition-colors
          ${isLoading
            ? 'bg-slate-600 text-slate-400 cursor-wait'
            : 'bg-blue-600 hover:bg-blue-700 text-white'
          }
        `}
        title={currentInfo?.name || currentAirport || 'Select Airport'}
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        <span>{displayName}</span>
        {isLoading && (
          <span className="w-3 h-3 rounded-full border-2 border-slate-400 border-t-transparent animate-spin" />
        )}
        <svg
          className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && (
        <div className="absolute top-full left-0 mt-1 w-80 bg-white rounded-lg shadow-xl border border-slate-200 overflow-hidden z-[1100]">
          {/* Custom ICAO input */}
          <div className="p-2 border-b border-slate-100 bg-slate-50">
            <div className="flex gap-1">
              <input
                type="text"
                value={customIcao}
                onChange={(e) => setCustomIcao(e.target.value.toUpperCase())}
                onKeyDown={(e) => e.key === 'Enter' && handleCustomSubmit()}
                placeholder="Enter ICAO code..."
                maxLength={4}
                className="flex-1 px-2 py-1 text-sm border border-slate-300 rounded font-mono text-slate-800 placeholder:text-slate-400"
              />
              <button
                onClick={handleCustomSubmit}
                disabled={customIcao.trim().length < 3}
                className="px-2 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-slate-300 disabled:text-slate-500"
              >
                Load
              </button>
            </div>
          </div>

          {loadError && (
            <div className="px-3 py-2 bg-red-50 text-red-600 text-xs border-b border-red-100">
              {loadError}
            </div>
          )}

          {/* Airport list */}
          <div className="max-h-64 overflow-y-auto">
            {WELL_KNOWN_AIRPORTS.map((airport) => (
              <button
                key={airport.icao}
                onClick={() => handleSelect(airport.icao)}
                className={`
                  w-full text-left px-3 py-2 hover:bg-blue-50 transition-colors
                  ${airport.icao === currentAirport ? 'bg-blue-100' : ''}
                `}
              >
                <div className="flex items-center justify-between">
                  <div>
                    <span className="font-mono font-bold text-slate-800">{airport.icao}</span>
                    <span className="ml-1 text-slate-500 text-sm">({airport.iata})</span>
                  </div>
                  {airport.icao === currentAirport && (
                    <svg className="w-4 h-4 text-blue-600" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd"
                        d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                        clipRule="evenodd" />
                    </svg>
                  )}
                </div>
                <div className="text-sm text-slate-600 truncate">{airport.name}</div>
                <div className="text-xs text-slate-400">{airport.city}</div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
