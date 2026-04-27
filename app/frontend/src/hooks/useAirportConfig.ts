/**
 * Airport Configuration Hook
 *
 * Manages airport configuration state and supports dynamic loading
 * from the API. Falls back to static configuration if no imports.
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import {
  AirportConfig,
  ConfigResponse,
  ImportResponse,
  AIDMImportResponse,
  OSMImportResponse,
  FAAImportResponse,
  OSMTerminal,
  OSMGate,
  OSMTaxiway,
  OSMApron,
  OSMRunway,
} from '../types/airportFormats';
import { RunwayConfig, TaxiwayConfig } from '../constants/airport3D';
import { BuildingPlacement } from '../config/buildingModels';
import { DEFAULT_CENTER_LAT, DEFAULT_CENTER_LON } from '../constants/defaults';
import { getCachedConfig, setCachedConfig } from '../utils/airportConfigCache';

const API_BASE = import.meta.env.VITE_API_URL || '';

export interface SwitchProgress {
  step: number;
  total: number;
  message: string;
  done: boolean;
  error?: boolean;
}

interface UseAirportConfigReturn {
  /** Current merged configuration */
  config: AirportConfig;

  /** Current airport ICAO code */
  currentAirport: string | null;

  /** Whether config is loading */
  isLoading: boolean;

  /** Last error message */
  error: string | null;

  /** Airport switch progress from WebSocket */
  switchProgress: SwitchProgress | null;

  /** Whether the demo simulation is ready for the current airport */
  demoReady: boolean;

  /** Import AIXM data */
  importAIXM: (file: File, options?: ImportOptions) => Promise<ImportResponse>;

  /** Import IFC data */
  importIFC: (file: File, options?: ImportOptions) => Promise<ImportResponse>;

  /** Import AIDM data */
  importAIDM: (file: File, localAirport?: string) => Promise<AIDMImportResponse>;

  /** Import OSM data for an airport by ICAO code */
  importOSM: (icaoCode: string, options?: OSMImportOptions) => Promise<OSMImportResponse>;

  /** Import FAA runway data for a US airport */
  importFAA: (facilityId: string, merge?: boolean) => Promise<FAAImportResponse>;

  /** Load airport from lakehouse */
  loadAirport: (icaoCode: string) => Promise<void>;

  /** Fetch default airport from backend config and load it */
  initializeDefaultAirport: () => Promise<void>;

  /** Reload configuration from API */
  refresh: () => Promise<void>;

  /** Reset to default configuration */
  reset: () => void;

  /** Get runway configs for 3D view */
  getRunwayConfigs: () => RunwayConfig[];

  /** Get taxiway configs for 3D view */
  getTaxiwayConfigs: () => TaxiwayConfig[];

  /** Get building placements for 3D view */
  getBuildingPlacements: () => BuildingPlacement[];

  /** Get OSM terminals for 3D view */
  getTerminals: () => OSMTerminal[];

  /** Get OSM gates for 2D map */
  getGates: () => OSMGate[];

  /** Get OSM taxiways for 2D map */
  getTaxiways: () => OSMTaxiway[];

  /** Get OSM aprons for 2D map */
  getAprons: () => OSMApron[];

  /** Get airport center coordinates for 3D view */
  getAirportCenter: () => { lat: number; lon: number };

  /** Get OSM runways */
  getOSMRunways: () => OSMRunway[];
}

interface ImportOptions {
  referenceLat?: number;
  referenceLon?: number;
  merge?: boolean;
  includeGeometry?: boolean;
}

interface OSMImportOptions {
  includeGates?: boolean;
  includeTerminals?: boolean;
  includeTaxiways?: boolean;
  includeAprons?: boolean;
  merge?: boolean;
}

/**
 * Create default configuration from static constants
 */
function createDefaultConfig(): AirportConfig {
  return {
    sources: ['default'],
    runways: [],
    taxiways: [],
    aprons: [],
    navaids: [],
    buildings: [],
  };
}

/**
 * Hook for managing airport configuration
 */
// Per-airport config cache (shared across hook instances via module scope)
const configCache = new Map<string, ConfigResponse>();

/** Clear the module-level config cache (for test isolation). */
export function _resetConfigCache() {
  configCache.clear();
}

export function useAirportConfig(): UseAirportConfigReturn {
  const [config, setConfig] = useState<AirportConfig>(createDefaultConfig);
  const [currentAirport, setCurrentAirport] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [switchProgress, setSwitchProgress] = useState<SwitchProgress | null>(null);
  const [demoReady, setDemoReady] = useState(false);
  const demoReadyRef = useRef(false);
  const currentAirportRef = useRef<string | null>(null);
  const progressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Safety timeout to clear isLoading if WS airport_switch_complete is missed
  const loadingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Track previous airport for rollback on error
  const prevAirportRef = useRef<string | null>(null);

  // Keep currentAirportRef in sync (for use inside useEffect closures)
  useEffect(() => {
    currentAirportRef.current = currentAirport;
  }, [currentAirport]);

  // Listen for airport_switch_progress and airport_switch_complete via WS
  // with automatic reconnection on disconnect.
  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsBase = API_BASE
      ? API_BASE.replace(/^http/, 'ws')
      : `${protocol}//${window.location.host}`;

    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectDelay = 1000;
    let disposed = false;

    function handleMessage(event: MessageEvent) {
      try {
        const msg = JSON.parse(event.data);

        if (msg.type === 'airport_switch_complete') {
          if (loadingTimeoutRef.current) {
            clearTimeout(loadingTimeoutRef.current);
            loadingTimeoutRef.current = null;
          }
          const data = msg.data ?? {};
          if (data.config && Object.keys(data.config).length > 0) {
            setConfig((prev) => ({
              ...prev,
              ...data.config,
              sources: (data.config.sources as AirportConfig['sources']) || prev.sources,
              lastUpdated: new Date().toISOString(),
            }));
            if (data.icaoCode) {
              setCurrentAirport(data.icaoCode);
              prevAirportRef.current = data.icaoCode;
              configCache.set(data.icaoCode, { config: data.config, lastUpdated: new Date().toISOString() } as ConfigResponse);
              setCachedConfig(data.icaoCode, data.config).catch(() => {});
            }
          }
          setIsLoading(false);
          return;
        }

        if (msg.type === 'demo_ready') {
          const icao = msg.data?.icao;
          if (!icao || icao === currentAirportRef.current) {
            demoReadyRef.current = true;
            setDemoReady(true);
          }
          return;
        }

        if (msg.type === 'airport_switch_progress') {
          const data = msg.data as SwitchProgress;
          setSwitchProgress(data);
          if (data.error && data.message) {
            setError(data.message);
            setIsLoading(false);
            if (loadingTimeoutRef.current) {
              clearTimeout(loadingTimeoutRef.current);
              loadingTimeoutRef.current = null;
            }
            if (prevAirportRef.current) {
              setCurrentAirport(prevAirportRef.current);
            }
          }
          if (data.done) {
            if (progressTimerRef.current) clearTimeout(progressTimerRef.current);
            progressTimerRef.current = setTimeout(() => setSwitchProgress(null), data.error ? 3000 : 1500);
          }
        }
      } catch {
        // ignore non-JSON or irrelevant messages
      }
    }

    function connect() {
      if (disposed) return;
      ws = new WebSocket(`${wsBase}/ws/flights`);
      ws.onopen = () => { reconnectDelay = 1000; };
      ws.onmessage = handleMessage;
      ws.onclose = () => {
        if (!disposed) {
          reconnectTimer = setTimeout(connect, reconnectDelay);
          reconnectDelay = Math.min(reconnectDelay * 2, 30_000);
        }
      };
    }

    connect();

    const demoPoll = setInterval(async () => {
      if (demoReadyRef.current) return;
      try {
        const res = await fetch(`${API_BASE}/api/ready`);
        if (res.ok) {
          const data = await res.json();
          if (data.demo_ready && data.demo_ready_icao === currentAirportRef.current) {
            demoReadyRef.current = true;
            setDemoReady(true);
          }
        }
      } catch {
        // ignore
      }
    }, 2000);

    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) ws.close();
      clearInterval(demoPoll);
      if (progressTimerRef.current) clearTimeout(progressTimerRef.current);
      if (loadingTimeoutRef.current) clearTimeout(loadingTimeoutRef.current);
    };
  }, []);

  /**
   * Fetch current configuration from API
   */
  // Instance-level guard to deduplicate concurrent refresh() calls
  const inflightRef = useRef<Promise<void> | null>(null);
  const defaultInitializedRef = useRef(false);

  const refresh = useCallback(async () => {
    // Deduplicate: if a refresh is already in-flight, reuse it
    if (inflightRef.current) return inflightRef.current;

    const doRefresh = async () => {
      // Check cache first
      if (currentAirport && configCache.has(currentAirport)) {
        const cached = configCache.get(currentAirport)!;
        const configData = cached.config as AirportConfig & { icaoCode?: string };
        if (configData && Object.keys(configData).length > 0) {
          setConfig((prev) => ({
            ...prev,
            ...configData,
            sources: configData.sources || prev.sources,
            lastUpdated: cached.lastUpdated || undefined,
          }));
          if (configData.icaoCode) {
            setCurrentAirport(configData.icaoCode);
          }
        }
        inflightRef.current = null;
        return;
      }

      setIsLoading(true);
      setError(null);

      try {
        const response = await fetch(`${API_BASE}/api/airport/config`);
        if (!response.ok) {
          throw new Error(`Failed to fetch config: ${response.statusText}`);
        }

        const data: ConfigResponse = await response.json();

        if (data.config && Object.keys(data.config).length > 0) {
          const configData = data.config as AirportConfig & { icaoCode?: string };
          setConfig((prev) => ({
            ...prev,
            ...configData,
            sources: configData.sources || prev.sources,
            lastUpdated: data.lastUpdated || undefined,
          }));
          // Update current airport from config
          if (configData.icaoCode) {
            setCurrentAirport(configData.icaoCode);
            configCache.set(configData.icaoCode, data);
          } else if (currentAirport) {
            configCache.set(currentAirport, data);
          }
        }
      } catch (err) {
        // API might not have config yet, fall back to default
        console.warn('Failed to load config from API, using defaults:', err);
      } finally {
        setIsLoading(false);
        inflightRef.current = null;
      }
    };

    inflightRef.current = doRefresh();
    return inflightRef.current;
  }, []);

  /**
   * Load airport (lakehouse first, OSM fallback, auto-persists)
   */
  const loadAirport = useCallback(async (icaoCode: string) => {
    // Reset demo state — new airport needs its own demo
    demoReadyRef.current = false;
    setDemoReady(false);

    // Apply cached frontend config optimistically (shows airport geometry instantly)
    // but always go through the backend activation flow for proper WS progress/errors.
    let hasCachedConfig = false;

    if (configCache.has(icaoCode)) {
      const cached = configCache.get(icaoCode)!;
      const configData = cached.config as AirportConfig & { icaoCode?: string };
      if (configData && Object.keys(configData).length > 0) {
        setConfig((prev) => ({
          ...prev,
          ...configData,
          sources: configData.sources || prev.sources,
          lastUpdated: cached.lastUpdated || undefined,
        }));
        hasCachedConfig = true;
      }
    }

    if (!hasCachedConfig) {
      try {
        const idbCached = await getCachedConfig(icaoCode);
        if (idbCached && typeof idbCached === 'object') {
          const configData = idbCached as AirportConfig & { icaoCode?: string };
          if (Object.keys(configData).length > 0) {
            setConfig((prev) => ({
              ...prev,
              ...configData,
              sources: configData.sources || prev.sources,
              lastUpdated: new Date().toISOString(),
            }));
            configCache.set(icaoCode, { config: configData, lastUpdated: new Date().toISOString() } as ConfigResponse);
            hasCachedConfig = true;
          }
        }
      } catch {
        // IndexedDB not available — proceed to network
      }
    }

    // Always activate via network — backend needs to switch gates, ML, flights
    if (!hasCachedConfig) configCache.delete(icaoCode);
    setIsLoading(true);
    setError(null);
    setCurrentAirport(icaoCode);

    // Save previous airport for rollback on error
    prevAirportRef.current = currentAirport;

    try {
      // Activate endpoint: returns 202 immediately, does work in background
      const response = await fetch(`${API_BASE}/api/airports/${icaoCode}/activate`, {
        method: 'POST',
      });

      if (response.status === 200) {
        // Already active — backend returned the normalized ICAO code.
        // Update currentAirport to the canonical ICAO code and stop loading.
        const data = await response.json();
        const normalizedIcao = data.icaoCode || icaoCode;
        setCurrentAirport(normalizedIcao);
        prevAirportRef.current = normalizedIcao;
        setIsLoading(false);
        return;
      }

      if (response.status === 202) {
        // Async activation: backend is working in background.
        // Config will arrive via WS `airport_switch_complete` message.
        // Keep isLoading=true; WS handler will clear it.
        // Use the normalized ICAO code from the response.
        const respData = await response.json();
        const normalizedIcao = respData.icaoCode || icaoCode;
        setCurrentAirport(normalizedIcao);
        // Safety timeout: if WS confirmation never arrives, try REST fallback
        // then revert so the user can retry.
        if (loadingTimeoutRef.current) clearTimeout(loadingTimeoutRef.current);
        loadingTimeoutRef.current = setTimeout(async () => {
          loadingTimeoutRef.current = null;
          // REST fallback: check if backend actually switched
          try {
            const res = await fetch(`${API_BASE}/api/airport/config`);
            if (res.ok) {
              const data = await res.json();
              const cfg = data?.config;
              if (cfg && Object.keys(cfg).length > 0) {
                setConfig((prev) => ({ ...prev, ...cfg, lastUpdated: new Date().toISOString() }));
                setCurrentAirport(normalizedIcao);
                prevAirportRef.current = normalizedIcao;
                configCache.set(normalizedIcao, data);
                setCachedConfig(normalizedIcao, cfg).catch(() => {});
                setIsLoading(false);
                return;
              }
            }
          } catch { /* fallthrough to revert */ }
          setIsLoading(false);
          if (prevAirportRef.current) {
            setCurrentAirport(prevAirportRef.current);
          }
        }, 60_000);
        return;
      }

      if (!response.ok) {
        let detail = `Failed to activate airport: ${response.statusText}`;
        try {
          const errorData = await response.json();
          if (errorData.detail) detail = errorData.detail;
        } catch {
          // Response body wasn't JSON (e.g., proxy error)
          const text = await response.text().catch(() => '');
          if (text) detail = text.slice(0, 200);
        }
        throw new Error(detail);
      }

      setIsLoading(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to activate airport';
      setError(message);
      setIsLoading(false);
      // Revert to previous airport on failure
      if (prevAirportRef.current && prevAirportRef.current !== icaoCode) {
        setCurrentAirport(prevAirportRef.current);
      }
      throw err;
    }
  }, [currentAirport]);

  /**
   * Fetch default airport from backend config and load it.
   * Called once when the backend becomes ready.
   */
  const initializeDefaultAirport = useCallback(async () => {
    if (defaultInitializedRef.current) return;
    defaultInitializedRef.current = true;
    try {
      const res = await fetch(`${API_BASE}/api/config`);
      if (res.ok) {
        const data = await res.json();
        const defaultIcao = data.default_airport_icao;
        if (defaultIcao) {
          await loadAirport(defaultIcao);
          return;
        }
      }
    } catch {
      // Fall through to fallback
    }
    // Fallback if /api/config is unavailable or missing the field
    await loadAirport('KSFO');
  }, [loadAirport]);

  /**
   * Import AIXM data
   */
  const importAIXM = useCallback(
    async (file: File, options?: ImportOptions): Promise<ImportResponse> => {
      setIsLoading(true);
      setError(null);

      try {
        const params = new URLSearchParams();
        if (options?.referenceLat) params.set('reference_lat', options.referenceLat.toString());
        if (options?.referenceLon) params.set('reference_lon', options.referenceLon.toString());
        if (options?.merge !== undefined) params.set('merge', options.merge.toString());

        const buffer = await file.arrayBuffer();

        const response = await fetch(
          `${API_BASE}/api/airport/import/aixm?${params.toString()}`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/octet-stream' },
            body: buffer,
          }
        );

        if (!response.ok) {
          const error = await response.json();
          throw new Error(error.detail || 'AIXM import failed');
        }

        const result: ImportResponse = await response.json();

        // Refresh config after successful import
        await refresh();

        return result;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'AIXM import failed';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [refresh]
  );

  /**
   * Import IFC data
   */
  const importIFC = useCallback(
    async (file: File, options?: ImportOptions): Promise<ImportResponse> => {
      setIsLoading(true);
      setError(null);

      try {
        const params = new URLSearchParams();
        if (options?.referenceLat) params.set('reference_lat', options.referenceLat.toString());
        if (options?.referenceLon) params.set('reference_lon', options.referenceLon.toString());
        if (options?.merge !== undefined) params.set('merge', options.merge.toString());
        if (options?.includeGeometry !== undefined) {
          params.set('include_geometry', options.includeGeometry.toString());
        }

        const buffer = await file.arrayBuffer();

        const response = await fetch(
          `${API_BASE}/api/airport/import/ifc?${params.toString()}`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/octet-stream' },
            body: buffer,
          }
        );

        if (!response.ok) {
          const error = await response.json();
          throw new Error(error.detail || 'IFC import failed');
        }

        const result: ImportResponse = await response.json();

        await refresh();

        return result;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'IFC import failed';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [refresh]
  );

  /**
   * Import AIDM data
   */
  const importAIDM = useCallback(
    async (file: File, localAirport: string = 'SFO'): Promise<AIDMImportResponse> => {
      setIsLoading(true);
      setError(null);

      try {
        const params = new URLSearchParams({ local_airport: localAirport });
        const buffer = await file.arrayBuffer();

        const response = await fetch(
          `${API_BASE}/api/airport/import/aidm?${params.toString()}`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/octet-stream' },
            body: buffer,
          }
        );

        if (!response.ok) {
          const error = await response.json();
          throw new Error(error.detail || 'AIDM import failed');
        }

        const result: AIDMImportResponse = await response.json();

        await refresh();

        return result;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'AIDM import failed';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [refresh]
  );

  /**
   * Import OSM data for an airport
   */
  const importOSM = useCallback(
    async (icaoCode: string, options?: OSMImportOptions): Promise<OSMImportResponse> => {
      setIsLoading(true);
      setError(null);

      try {
        const params = new URLSearchParams();
        params.set('icao_code', icaoCode);
        if (options?.includeGates !== undefined)
          params.set('include_gates', options.includeGates.toString());
        if (options?.includeTerminals !== undefined)
          params.set('include_terminals', options.includeTerminals.toString());
        if (options?.includeTaxiways !== undefined)
          params.set('include_taxiways', options.includeTaxiways.toString());
        if (options?.includeAprons !== undefined)
          params.set('include_aprons', options.includeAprons.toString());
        if (options?.merge !== undefined) params.set('merge', options.merge.toString());

        const response = await fetch(
          `${API_BASE}/api/airport/import/osm?${params.toString()}`,
          {
            method: 'POST',
          }
        );

        if (!response.ok) {
          const error = await response.json();
          throw new Error(error.detail || 'OSM import failed');
        }

        const result: OSMImportResponse = await response.json();

        await refresh();

        return result;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'OSM import failed';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [refresh]
  );

  /**
   * Import FAA runway data
   */
  const importFAA = useCallback(
    async (facilityId: string, merge: boolean = true): Promise<FAAImportResponse> => {
      setIsLoading(true);
      setError(null);

      try {
        const params = new URLSearchParams();
        params.set('facility_id', facilityId);
        params.set('merge', merge.toString());

        const response = await fetch(
          `${API_BASE}/api/airport/import/faa?${params.toString()}`,
          {
            method: 'POST',
          }
        );

        if (!response.ok) {
          const error = await response.json();
          throw new Error(error.detail || 'FAA import failed');
        }

        const result: FAAImportResponse = await response.json();

        await refresh();

        return result;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'FAA import failed';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [refresh]
  );

  /**
   * Reset to default configuration
   */
  const reset = useCallback(() => {
    setConfig(createDefaultConfig());
    setError(null);
  }, []);

  /**
   * Get runway configs for 3D view (convert from imported format)
   */
  const getRunwayConfigs = useCallback((): RunwayConfig[] => {
    return config.runways.map((r) => ({
      id: r.id,
      start: r.start,
      end: r.end,
      width: r.width,
      color: r.color,
    }));
  }, [config.runways]);

  /**
   * Get taxiway configs for 3D view
   */
  const getTaxiwayConfigs = useCallback((): TaxiwayConfig[] => {
    return config.taxiways.map((t) => ({
      id: t.id,
      points: t.points,
      width: t.width,
      color: t.color,
    }));
  }, [config.taxiways]);

  /**
   * Get building placements for 3D view
   */
  const getBuildingPlacements = useCallback((): BuildingPlacement[] => {
    // Convert IFC buildings to BuildingPlacement format
    const ifcBuildings: BuildingPlacement[] = config.buildings.map((b) => ({
      id: b.id,
      type: (b.type as BuildingPlacement['type']) || 'terminal',
      position: b.position,
      rotation: b.rotation,
    }));

    return ifcBuildings;
  }, [config.buildings, config.sources]);

  /**
   * Get OSM terminals for 3D view
   */
  const getTerminals = useCallback((): OSMTerminal[] => {
    return config.terminals || [];
  }, [config.terminals]);

  /**
   * Get OSM gates for 2D map view
   */
  const getGates = useCallback((): OSMGate[] => {
    return config.gates || [];
  }, [config.gates]);

  /**
   * Get OSM taxiways for 2D map view
   */
  const getTaxiways = useCallback((): OSMTaxiway[] => {
    return config.osmTaxiways || [];
  }, [config.osmTaxiways]);

  /**
   * Get OSM aprons for 2D map view
   */
  const getAprons = useCallback((): OSMApron[] => {
    return config.osmAprons || [];
  }, [config.osmAprons]);

  /**
   * Get OSM runways
   */
  const getOSMRunways = useCallback((): OSMRunway[] => {
    return config.osmRunways || [];
  }, [config.osmRunways]);

  /**
   * Get airport center from OSM gate/terminal geo data, falling back to SFO defaults
   */
  const getAirportCenter = useCallback((): { lat: number; lon: number } => {
    // Try gates first (most numerous, good centroid)
    // Note: Number() coercion required because backend may serialize coords as strings
    const gates = config.gates || [];
    if (gates.length > 0) {
      const sumLat = gates.reduce((s, g) => s + Number(g.geo.latitude), 0);
      const sumLon = gates.reduce((s, g) => s + Number(g.geo.longitude), 0);
      return { lat: sumLat / gates.length, lon: sumLon / gates.length };
    }

    // Try terminals
    const terminals = config.terminals || [];
    if (terminals.length > 0) {
      const sumLat = terminals.reduce((s, t) => s + Number(t.geo.latitude), 0);
      const sumLon = terminals.reduce((s, t) => s + Number(t.geo.longitude), 0);
      return { lat: sumLat / terminals.length, lon: sumLon / terminals.length };
    }

    // Fallback to SFO defaults
    return { lat: DEFAULT_CENTER_LAT, lon: DEFAULT_CENTER_LON };
  }, [config.gates, config.terminals]);

  // Load config on mount (selected airport only — no pre-warm of others)
  useEffect(() => {
    refresh();
  }, [refresh]);

  return {
    config,
    currentAirport,
    isLoading,
    error,
    switchProgress,
    demoReady,
    importAIXM,
    importIFC,
    importAIDM,
    importOSM,
    importFAA,
    loadAirport,
    initializeDefaultAirport,
    refresh,
    reset,
    getRunwayConfigs,
    getTaxiwayConfigs,
    getBuildingPlacements,
    getTerminals,
    getGates,
    getTaxiways,
    getAprons,
    getAirportCenter,
    getOSMRunways,
  };
}

export default useAirportConfig;
