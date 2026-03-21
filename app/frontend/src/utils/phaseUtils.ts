import { Flight } from '../types/flight';

/** Map legacy 4-phase names to new fine-grained phases. */
const LEGACY_PHASE_MAP: Record<string, Flight['flight_phase']> = {
  ground: 'parked',
  climbing: 'departing',
  descending: 'approaching',
  cruising: 'enroute',
};

/** Normalize a phase string — maps legacy 4-phase names to new 9-phase names. */
export function normalizePhase(phase: string): Flight['flight_phase'] {
  return LEGACY_PHASE_MAP[phase] ?? (phase as Flight['flight_phase']);
}

/** True if the phase represents an aircraft on the ground. */
export function isGroundPhase(phase: Flight['flight_phase']): boolean {
  return phase === 'parked' || phase === 'pushback' || phase === 'taxi_out'
    || phase === 'taxi_in' || phase === 'takeoff'
    // Legacy
    || phase === 'ground';
}

/** True if the phase is an arrival (descending toward or arriving at airport). */
export function isArrivalPhase(phase: Flight['flight_phase']): boolean {
  return phase === 'approaching' || phase === 'landing' || phase === 'taxi_in'
    || phase === 'descending';
}

/** True if the phase is a departure (climbing away from airport). */
export function isDeparturePhase(phase: Flight['flight_phase']): boolean {
  return phase === 'takeoff' || phase === 'departing'
    || phase === 'climbing';
}

/** Hex colors for flight phase markers (2D map). */
export const PHASE_COLORS: Record<string, string> = {
  // Ground (gray family)
  parked: '#6b7280',
  pushback: '#9ca3af',
  taxi_out: '#a8a29e',
  taxi_in: '#a8a29e',
  // Departure (green family)
  takeoff: '#16a34a',
  departing: '#22c55e',
  // Arrival (orange family)
  approaching: '#f97316',
  landing: '#ea580c',
  // Cruise
  enroute: '#3b82f6',
  // Legacy aliases
  ground: '#6b7280',
  climbing: '#22c55e',
  descending: '#f97316',
  cruising: '#3b82f6',
};

/** Tailwind bg- classes for flight phase badges. */
export const PHASE_BG_CLASSES: Record<string, string> = {
  parked: 'bg-gray-500',
  pushback: 'bg-gray-400',
  taxi_out: 'bg-stone-400',
  taxi_in: 'bg-stone-400',
  takeoff: 'bg-green-600',
  departing: 'bg-green-500',
  approaching: 'bg-orange-500',
  landing: 'bg-orange-600',
  enroute: 'bg-blue-500',
  // Legacy
  ground: 'bg-gray-500',
  climbing: 'bg-green-500',
  descending: 'bg-orange-500',
  cruising: 'bg-blue-500',
};

/** Human-readable labels for flight phases. */
export const PHASE_LABELS: Record<string, string> = {
  parked: 'Parked',
  pushback: 'Pushback',
  taxi_out: 'Taxi Out',
  taxi_in: 'Taxi In',
  takeoff: 'Takeoff',
  departing: 'Departing',
  approaching: 'Approaching',
  landing: 'Landing',
  enroute: 'Enroute',
  // Legacy
  ground: 'Ground',
  climbing: 'Climbing',
  descending: 'Descending',
  cruising: 'Cruising',
};

/** Short labels for compact display (e.g. flight list badges). */
export const PHASE_SHORT_LABELS: Record<string, string> = {
  parked: 'PKD',
  pushback: 'PSH',
  taxi_out: 'TXO',
  taxi_in: 'TXI',
  takeoff: 'TKO',
  departing: 'DEP',
  approaching: 'APP',
  landing: 'LND',
  enroute: 'ENR',
  // Legacy
  ground: 'GND',
  climbing: 'CLB',
  descending: 'DSC',
  cruising: 'CRZ',
};
