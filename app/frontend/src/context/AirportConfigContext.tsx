/**
 * Airport Configuration Context
 *
 * Provides airport configuration state across the application.
 * Wraps useAirportConfig hook for global access.
 */

import { createContext, useContext, ReactNode } from 'react';
import { useAirportConfig } from '../hooks/useAirportConfig';
import type { SwitchProgress } from '../hooks/useAirportConfig';
import type { AirportConfig, OSMTerminal, OSMGate, OSMTaxiway, OSMApron, OSMRunway } from '../types/airportFormats';
import type { RunwayConfig, TaxiwayConfig } from '../constants/airport3D';
import type { BuildingPlacement } from '../config/buildingModels';

interface AirportConfigContextValue {
  config: AirportConfig;
  currentAirport: string | null;
  isLoading: boolean;
  error: string | null;
  switchProgress: SwitchProgress | null;
  loadAirport: (icaoCode: string) => Promise<void>;
  refresh: () => Promise<void>;
  getRunwayConfigs: () => RunwayConfig[];
  getTaxiwayConfigs: () => TaxiwayConfig[];
  getBuildingPlacements: () => BuildingPlacement[];
  getTerminals: () => OSMTerminal[];
  getGates: () => OSMGate[];
  getTaxiways: () => OSMTaxiway[];
  getAprons: () => OSMApron[];
  getAirportCenter: () => { lat: number; lon: number };
  getOSMRunways: () => OSMRunway[];
}

const AirportConfigContext = createContext<AirportConfigContextValue | null>(null);

export function AirportConfigProvider({ children }: { children: ReactNode }) {
  const airportConfig = useAirportConfig();

  return (
    <AirportConfigContext.Provider value={airportConfig}>
      {children}
    </AirportConfigContext.Provider>
  );
}

export function useAirportConfigContext() {
  const context = useContext(AirportConfigContext);
  if (!context) {
    throw new Error('useAirportConfigContext must be used within AirportConfigProvider');
  }
  return context;
}

export default AirportConfigContext;
