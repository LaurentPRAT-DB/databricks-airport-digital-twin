/**
 * Airport Configuration Hook
 *
 * Manages airport configuration state and supports dynamic loading
 * from the API. Falls back to static configuration if no imports.
 */

import { useState, useCallback, useEffect } from 'react';
import {
  AirportConfig,
  ConfigResponse,
  ImportResponse,
  AIDMImportResponse,
  OSMImportResponse,
  FAAImportResponse,
  OSMTerminal,
  OSMGate,
} from '../types/airportFormats';
import { AIRPORT_3D_CONFIG, RunwayConfig, TaxiwayConfig } from '../constants/airport3D';
import { BuildingPlacement } from '../config/buildingModels';

const API_BASE = import.meta.env.VITE_API_URL || '';

interface UseAirportConfigReturn {
  /** Current merged configuration */
  config: AirportConfig;

  /** Whether config is loading */
  isLoading: boolean;

  /** Last error message */
  error: string | null;

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
    runways: AIRPORT_3D_CONFIG.runways.map((r) => ({
      id: r.id,
      start: r.start,
      end: r.end,
      width: r.width,
      color: r.color,
    })),
    taxiways: AIRPORT_3D_CONFIG.taxiways.map((t) => ({
      id: t.id,
      points: t.points,
      width: t.width,
      color: t.color,
    })),
    aprons: [],
    navaids: [],
    buildings: AIRPORT_3D_CONFIG.buildings.map((b) => ({
      id: b.id,
      name: b.id,
      type: b.type,
      position: b.position,
      dimensions: { width: 50, height: 20, depth: 50 },
      rotation: b.rotation,
      storeys: [],
      sourceGlobalId: '',
    })),
  };
}

/**
 * Hook for managing airport configuration
 */
export function useAirportConfig(): UseAirportConfigReturn {
  const [config, setConfig] = useState<AirportConfig>(createDefaultConfig);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Fetch current configuration from API
   */
  const refresh = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE}/api/airport/config`);
      if (!response.ok) {
        throw new Error(`Failed to fetch config: ${response.statusText}`);
      }

      const data: ConfigResponse = await response.json();

      if (data.config && Object.keys(data.config).length > 0) {
        setConfig((prev) => ({
          ...prev,
          ...data.config,
          sources: (data.config.sources as AirportConfig['sources']) || prev.sources,
          lastUpdated: data.lastUpdated || undefined,
        }));
      }
    } catch (err) {
      // API might not have config yet, fall back to default
      console.warn('Failed to load config from API, using defaults:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

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

    // Merge with default buildings if no imports
    if (config.sources.includes('default')) {
      return AIRPORT_3D_CONFIG.buildings;
    }

    return ifcBuildings.length > 0 ? ifcBuildings : AIRPORT_3D_CONFIG.buildings;
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

  // Load config on mount
  useEffect(() => {
    refresh();
  }, [refresh]);

  return {
    config,
    isLoading,
    error,
    importAIXM,
    importIFC,
    importAIDM,
    importOSM,
    importFAA,
    refresh,
    reset,
    getRunwayConfigs,
    getTaxiwayConfigs,
    getBuildingPlacements,
    getTerminals,
    getGates,
  };
}

export default useAirportConfig;
