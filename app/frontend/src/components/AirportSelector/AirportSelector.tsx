/**
 * Airport Selector Component
 *
 * Dropdown for selecting airports by ICAO code.
 * Fetches airport list and cache status from backend.
 * Groups airports by region with cache status indicators.
 */

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';

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
  const [reloading, setReloading] = useState(false);
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
    if (icaoCode === currentAirport && !isLoading) {
      setIsOpen(false);
      return;
    }
    setLoadError(null);
    setIsOpen(false);
    try {
      await onAirportChange(icaoCode);
      // Refresh list — newly loaded airports appear in the cache
      await fetchCacheStatus();
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

  const handleReload = async () => {
    if (!currentAirport || reloading) return;
    setReloading(true);
    setLoadError(null);
    try {
      const res = await fetch(`/api/airports/${currentAirport}/reload`, { method: 'POST' });
      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: 'Reload failed' }));
        throw new Error(data.detail || `Reload failed (${res.status})`);
      }
      // Re-activate airport to pick up new config
      await onAirportChange(currentAirport);
      await fetchCacheStatus();
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Reload failed');
    } finally {
      setReloading(false);
    }
  };

  // Search filter
  const [filter, setFilter] = useState('');
  const filterInputRef = useRef<HTMLInputElement>(null);

  // Reset filter when dropdown opens, focus input
  useEffect(() => {
    if (isOpen) {
      setFilter('');
      setTimeout(() => filterInputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  // Filtered airports based on search input
  const filteredAirports = useMemo(() => {
    if (!filter.trim()) return airports;
    const q = filter.trim().toLowerCase();
    return airports.filter(
      (a) =>
        a.icao.toLowerCase().includes(q) ||
        a.iata.toLowerCase().includes(q) ||
        a.name.toLowerCase().includes(q) ||
        a.city.toLowerCase().includes(q)
    );
  }, [airports, filter]);

  // Group airports by region
  const groupedAirports = REGION_ORDER.reduce<Record<string, AirportInfo[]>>((acc, region) => {
    const regionAirports = filteredAirports.filter((a) => a.region === region);
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

  const totalCount = airports.length;

  return (
    <div ref={dropdownRef} className="relative flex items-center gap-1">
      <button
        onClick={() => { if (!isOpen) setLoadError(null); setIsOpen(!isOpen); }}
        disabled={isLoading}
        className={`
          flex items-center gap-2 h-8 min-w-[180px] px-3 rounded-lg text-sm font-medium
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

      {/* Reload button */}
      {currentAirport && (
        <button
          onClick={handleReload}
          disabled={isLoading || reloading}
          className={`
            h-8 w-8 flex items-center justify-center rounded-lg transition-colors
            ${reloading
              ? 'bg-slate-600 text-slate-400 cursor-wait'
              : 'bg-slate-700 hover:bg-slate-600 text-slate-300 hover:text-white'
            }
          `}
          title="Reload airport from OSM (force refresh)"
        >
          <svg
            className={`w-4 h-4 ${reloading ? 'animate-spin' : ''}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
      )}

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
        <div className="absolute top-full left-0 mt-1 w-80 bg-white dark:bg-slate-800 rounded-lg shadow-xl border border-slate-200 dark:border-slate-700 overflow-hidden z-[1100]">
          {/* Search / custom ICAO input */}
          <div className="p-2 border-b border-slate-100 dark:border-slate-700 bg-slate-50 dark:bg-slate-900">
            <div className="flex gap-1">
              <div className="relative flex-1">
                <svg className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                <input
                  ref={filterInputRef}
                  type="text"
                  value={filter || customIcao}
                  onChange={(e) => {
                    const v = e.target.value.toUpperCase();
                    setFilter(v);
                    setCustomIcao(v);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      if (filteredAirports.length === 1) {
                        handleSelect(filteredAirports[0].icao);
                      } else {
                        handleCustomSubmit();
                      }
                    }
                  }}
                  placeholder="Search airport or enter ICAO..."
                  className="w-full pl-7 pr-2 py-1 text-sm border border-slate-300 dark:border-slate-600 rounded text-slate-800 dark:text-slate-200 bg-white dark:bg-slate-800 placeholder:text-slate-400"
                />
              </div>
              {customIcao.trim().length >= 3 && filteredAirports.length === 0 && (
                <button
                  onClick={handleCustomSubmit}
                  className="px-2 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700"
                >
                  Load
                </button>
              )}
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
                <div className="px-3 py-1 bg-slate-100 dark:bg-slate-900 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider sticky top-0">
                  {region}
                </div>
                {regionAirports.map((airport) => (
                  <button
                    key={airport.icao}
                    onClick={() => handleSelect(airport.icao)}
                    className={`
                      w-full text-left px-3 py-2 hover:bg-blue-50 dark:hover:bg-blue-900/30 transition-colors
                      ${airport.icao === currentAirport ? 'bg-blue-100 dark:bg-blue-900/40' : ''}
                    `}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-bold text-slate-800 dark:text-slate-200">{airport.icao}</span>
                        {airport.iata && <span className="text-slate-500 dark:text-slate-400 text-sm">({airport.iata})</span>}
                      </div>
                      {airport.icao === currentAirport && (
                        <svg className="w-4 h-4 text-blue-600" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd"
                            d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                            clipRule="evenodd" />
                        </svg>
                      )}
                    </div>
                    <div className="text-sm text-slate-600 dark:text-slate-300 truncate ml-4">{airport.name}</div>
                    <div className="text-xs text-slate-400 dark:text-slate-500 ml-4">{airport.city}</div>
                  </button>
                ))}
              </div>
            ))}
          </div>

          {/* Footer with airport count */}
          <div className="p-2 border-t border-slate-100 dark:border-slate-700 bg-slate-50 dark:bg-slate-900">
            <div className="text-xs text-slate-500 dark:text-slate-400 text-center">
              {totalCount} airport{totalCount !== 1 ? 's' : ''} cached
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
