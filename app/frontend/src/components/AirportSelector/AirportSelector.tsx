/**
 * Airport Selector Component
 *
 * Dropdown for selecting airports by ICAO code.
 * Fetches airport list and cache status from backend.
 * Groups airports by region with cache status indicators.
 */

import { useState, useEffect, useRef, useCallback } from 'react';

interface AirportInfo {
  icao: string;
  iata: string;
  name: string;
  city: string;
  region: string;
  cached: boolean;
}

const REGION_ORDER = ['Americas', 'Europe', 'Middle East', 'Asia-Pacific', 'Africa'];

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
  const [airports, setAirports] = useState<AirportInfo[]>([]);
  const [preloading, setPreloading] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const errorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Auto-dismiss error toast after 8 seconds
  useEffect(() => {
    if (loadError && !isOpen) {
      if (errorTimerRef.current) clearTimeout(errorTimerRef.current);
      errorTimerRef.current = setTimeout(() => setLoadError(null), 8000);
    }
    return () => { if (errorTimerRef.current) clearTimeout(errorTimerRef.current); };
  }, [loadError, isOpen]);

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

  // AbortController to cancel in-flight fetches on unmount
  const abortRef = useRef<AbortController | null>(null);

  const fetchCacheStatus = useCallback(async () => {
    // Cancel any previous in-flight fetch
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const res = await fetch('/api/airports/preload/status', { signal: controller.signal });
      if (res.ok) {
        const data = await res.json();
        if (!controller.signal.aborted) {
          setAirports(data.airports || []);
        }
      }
    } catch {
      // Silently fail — abort errors and network errors both land here
    }
  }, []);

  // Fetch on mount for button label, then refresh each time dropdown opens
  useEffect(() => {
    fetchCacheStatus();
    return () => { abortRef.current?.abort(); };
  }, [fetchCacheStatus]);

  useEffect(() => {
    if (isOpen) {
      fetchCacheStatus();
    }
  }, [isOpen, fetchCacheStatus]);

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

  const handlePreloadAll = async () => {
    setPreloading(true);
    try {
      const res = await fetch('/api/airports/preload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(null),
      });
      if (res.ok) {
        // Refresh cache status after preload
        await fetchCacheStatus();
      }
    } catch {
      // Silently fail
    } finally {
      setPreloading(false);
    }
  };

  // Group airports by region
  const groupedAirports = REGION_ORDER.reduce<Record<string, AirportInfo[]>>((acc, region) => {
    const regionAirports = airports.filter((a) => a.region === region);
    if (regionAirports.length > 0) {
      acc[region] = regionAirports;
    }
    return acc;
  }, {});

  // Find current airport info
  const currentInfo = airports.find((a) => a.icao === currentAirport);
  const displayName = currentInfo
    ? `${currentInfo.icao} (${currentInfo.iata})`
    : currentAirport || 'Select Airport';

  const cachedCount = airports.filter((a) => a.cached).length;
  const totalCount = airports.length;

  return (
    <div ref={dropdownRef} className="relative">
      <button
        onClick={() => { if (!isOpen) setLoadError(null); setIsOpen(!isOpen); }}
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

      {/* Error toast — visible even when dropdown is closed */}
      {loadError && !isOpen && (
        <div className="absolute top-full left-0 mt-1 w-80 bg-red-50 border border-red-200 rounded-lg shadow-lg px-3 py-2 z-[1100] flex items-center gap-2">
          <svg className="w-4 h-4 text-red-500 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <span className="text-red-700 text-xs flex-1">{loadError}</span>
          <button onClick={() => setLoadError(null)} className="text-red-400 hover:text-red-600 text-xs font-bold">
            ✕
          </button>
        </div>
      )}

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

          {/* Airport list grouped by region */}
          <div className="max-h-72 overflow-y-auto">
            {Object.entries(groupedAirports).map(([region, regionAirports]) => (
              <div key={region}>
                <div className="px-3 py-1 bg-slate-100 text-xs font-semibold text-slate-500 uppercase tracking-wider sticky top-0">
                  {region}
                </div>
                {regionAirports.map((airport) => (
                  <button
                    key={airport.icao}
                    onClick={() => handleSelect(airport.icao)}
                    className={`
                      w-full text-left px-3 py-2 hover:bg-blue-50 transition-colors
                      ${airport.icao === currentAirport ? 'bg-blue-100' : ''}
                    `}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span
                          className={`w-2 h-2 rounded-full flex-shrink-0 ${airport.cached ? 'bg-green-500' : 'bg-slate-300'}`}
                          title={airport.cached ? 'Cached (fast switch)' : 'Not cached (will fetch from OSM)'}
                        />
                        <span className="font-mono font-bold text-slate-800">{airport.icao}</span>
                        <span className="text-slate-500 text-sm">({airport.iata})</span>
                      </div>
                      {airport.icao === currentAirport && (
                        <svg className="w-4 h-4 text-blue-600" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd"
                            d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                            clipRule="evenodd" />
                        </svg>
                      )}
                    </div>
                    <div className="text-sm text-slate-600 truncate ml-4">{airport.name}</div>
                    <div className="text-xs text-slate-400 ml-4">{airport.city}</div>
                  </button>
                ))}
              </div>
            ))}
          </div>

          {/* Pre-load all button */}
          <div className="p-2 border-t border-slate-100 bg-slate-50">
            <button
              onClick={handlePreloadAll}
              disabled={preloading || cachedCount === totalCount}
              className="w-full px-3 py-1.5 text-xs font-medium rounded transition-colors
                bg-slate-200 hover:bg-slate-300 text-slate-700
                disabled:bg-slate-100 disabled:text-slate-400 disabled:cursor-not-allowed
                flex items-center justify-center gap-2"
            >
              {preloading ? (
                <>
                  <span className="w-3 h-3 rounded-full border-2 border-slate-400 border-t-transparent animate-spin" />
                  Pre-loading...
                </>
              ) : cachedCount === totalCount && totalCount > 0 ? (
                <>All {totalCount} airports cached</>
              ) : (
                <>Pre-load All ({cachedCount}/{totalCount} cached)</>
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
