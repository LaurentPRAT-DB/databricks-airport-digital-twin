import { useFlightContext } from '../context/FlightContext';
import { DelayPrediction } from '../types/flight';

export function useDelayMap(): { delayMap: Map<string, DelayPrediction>; delayedCount: number } {
  const { delayMap, delayedCount } = useFlightContext();
  return { delayMap, delayedCount };
}
