/**
 * Airport Format Types
 *
 * TypeScript interfaces for industry-standard airport formats:
 * - AIXM (Aeronautical Information Exchange Model)
 * - IFC (Industry Foundation Classes / BIM)
 * - AIDM (IATA Airport Industry Data Model)
 */

// ============================================================================
// Common Types
// ============================================================================

export interface Position3D {
  x: number;
  y: number;
  z: number;
}

export interface GeoPosition {
  latitude: number;
  longitude: number;
  altitude?: number;
}

export interface Dimensions3D {
  width: number;
  height: number;
  depth: number;
}

// ============================================================================
// AIXM Types (Aeronautical Information)
// ============================================================================

export type RunwaySurfaceType =
  | 'ASPH'  // Asphalt
  | 'CONC'  // Concrete
  | 'GRASS'
  | 'GRVL'  // Gravel
  | 'SAND'
  | 'WATER'
  | 'BITU'  // Bituminous
  | 'COMP'; // Composite

export type NavaidType =
  | 'VOR'
  | 'VOR_DME'
  | 'TACAN'
  | 'NDB'
  | 'ILS'
  | 'ILS_DME'
  | 'LOC'
  | 'GP'
  | 'MKR'
  | 'DME';

export interface AIXMRunwayDirection {
  designator: string;
  bearing: number | null;
}

export interface AIXMRunway {
  id: string;
  start: Position3D;
  end: Position3D;
  width: number;
  color: number;
  length?: number;
  surfaceType?: RunwaySurfaceType;
  directions?: AIXMRunwayDirection[];
}

export interface AIXMTaxiway {
  id: string;
  points: Position3D[];
  width: number;
  color: number;
}

export interface AIXMApron {
  id: string;
  name?: string;
  position: Position3D;
  dimensions: Dimensions3D;
  polygon: Position3D[];
  color: number;
}

export interface AIXMNavaid {
  id: string;
  designator: string;
  type: NavaidType;
  position: Position3D;
  frequency?: number;
}

export interface AIXMConfig {
  source: 'AIXM';
  version: string;
  airport?: {
    icaoCode?: string;
    iataCode?: string;
    name: string;
    elevation?: number;
  };
  runways: AIXMRunway[];
  taxiways: AIXMTaxiway[];
  aprons: AIXMApron[];
  navaids: AIXMNavaid[];
}

// ============================================================================
// IFC Types (Building Information)
// ============================================================================

export type IFCElementType =
  | 'IfcBuilding'
  | 'IfcBuildingStorey'
  | 'IfcSpace'
  | 'IfcWall'
  | 'IfcWallStandardCase'
  | 'IfcSlab'
  | 'IfcRoof'
  | 'IfcColumn'
  | 'IfcBeam'
  | 'IfcDoor'
  | 'IfcWindow'
  | 'IfcStair'
  | 'IfcRamp'
  | 'IfcCurtainWall'
  | 'IfcCovering'
  | 'IfcFurnishingElement';

export interface IFCStorey {
  name?: string;
  elevation: number;
  height?: number;
  spaceCount: number;
  elementCount: number;
}

export interface IFCBuilding {
  id: string;
  name?: string;
  type: string;
  position: Position3D;
  dimensions: Dimensions3D;
  rotation: number;
  storeys: IFCStorey[];
  sourceGlobalId: string;
}

export interface IFCElement {
  id: string;
  name?: string;
  type: IFCElementType;
  position: Position3D;
  dimensions: Dimensions3D;
  rotation: Position3D;
  color: number;
  material?: string;
}

export interface IFCConfig {
  source: 'IFC';
  version: string;
  buildings: IFCBuilding[];
  elements: IFCElement[];
}

// ============================================================================
// AIDM Types (Operational Data)
// ============================================================================

export type AIDMFlightStatus =
  | 'scheduled'
  | 'en_route'
  | 'boarding'
  | 'final_call'
  | 'gate_closed'
  | 'departed'
  | 'landed'
  | 'at_gate'
  | 'taxiing'
  | 'cancelled'
  | 'diverted'
  | 'delayed';

export type AIDMResourceType =
  | 'GATE'
  | 'STAND'
  | 'BAGGAGE_CLAIM'
  | 'CHECK_IN'
  | 'SECURITY'
  | 'BOARDING'
  | 'RUNWAY'
  | 'TAXIWAY'
  | 'DEICING';

export interface AIDMFlight {
  icao24: string;
  callsign: string;
  latitude: number;
  longitude: number;
  altitude: number;
  velocity: number;
  heading: number;
  verticalRate?: number;
  onGround: boolean;
  timestamp: number;
  origin: string;
  destination: string;
  aircraftType?: string;
  registration?: string;
  flightPhase?: string;
  gate?: string;
  status: AIDMFlightStatus;
}

export interface AIDMScheduledFlight {
  flightNumber: string;
  airline: string;
  airlineName?: string;
  origin: string;
  destination: string;
  scheduledTime?: string;
  estimatedTime?: string;
  actualTime?: string;
  status: AIDMFlightStatus;
  terminal?: string;
  gate?: string;
  aircraftType?: string;
  isArrival: boolean;
  remarks?: string;
}

export interface AIDMResource {
  type: AIDMResourceType;
  id: string;
  terminal?: string;
  startTime?: string;
  endTime?: string;
  gateType?: string;
  position?: GeoPosition;
}

export interface AIDMEvent {
  id: string;
  type: string;
  timestamp: string;
  description?: string;
  source?: string;
}

export interface AIDMConfig {
  source: 'AIDM';
  version: string;
  airport?: string;
  timestamp?: string;
  flights: AIDMFlight[];
  scheduledFlights: AIDMScheduledFlight[];
  resources: AIDMResource[];
  events: AIDMEvent[];
}

// ============================================================================
// Combined Airport Configuration
// ============================================================================

export interface AirportConfig {
  // Source tracking
  sources: Array<'AIXM' | 'IFC' | 'AIDM' | 'OSM' | 'FAA' | 'default'>;
  lastUpdated?: string;

  // Geometry (from AIXM/IFC)
  runways: AIXMRunway[];
  taxiways: AIXMTaxiway[];
  aprons: AIXMApron[];
  navaids: AIXMNavaid[];
  buildings: IFCBuilding[];

  // Operational data (from AIDM)
  aidmFlights?: AIDMFlight[];
  aidmScheduled?: AIDMScheduledFlight[];
  aidmResources?: AIDMResource[];
  aidmEvents?: AIDMEvent[];
}

// ============================================================================
// API Response Types
// ============================================================================

export interface ImportResponse {
  success: boolean;
  format: string;
  elementsImported: Record<string, number>;
  warnings: string[];
  timestamp: string;
}

export interface AIDMImportResponse {
  success: boolean;
  flightsImported: number;
  resourcesImported: number;
  eventsImported: number;
  warnings: string[];
  timestamp: string;
}

export interface ConfigResponse {
  config: Partial<AirportConfig>;
  lastUpdated: string | null;
  elementCounts: Record<string, number>;
}

export interface OSMImportResponse {
  success: boolean;
  icaoCode: string;
  gatesImported: number;
  terminalsImported: number;
  taxiwaysImported: number;
  apronsImported: number;
  warnings: string[];
  timestamp: string;
}

export interface FAAImportResponse {
  success: boolean;
  facilityId: string;
  runwaysImported: number;
  warnings: string[];
  timestamp: string;
}
