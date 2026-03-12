import { useState, useEffect, useRef, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Flight, FlightsResponse } from '../types/flight';

async function fetchFlights(): Promise<FlightsResponse> {
  const response = await fetch('/api/flights', {
    credentials: 'include',
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch flights: ${response.statusText}`);
  }
  return response.json();
}

export interface UseFlightsResult {
  flights: Flight[];
  isLoading: boolean;
  error: Error | null;
  lastUpdated: string | null;
  dataSource: 'live' | 'cached' | 'synthetic' | null;
}

/** Build the WebSocket URL from the current page origin. */
function getWsUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws/flights`;
}

interface WsFullMessage {
  type: 'initial' | 'flight_update';
  data: {
    flights: Flight[];
    count: number;
    timestamp: string;
  };
}

interface WsDeltaMessage {
  type: 'flight_delta';
  data: {
    deltas: Partial<Flight & { icao24: string }>[];
    removed: string[];
    count: number;
    timestamp: string;
  };
}

type WsFlightMessage = WsFullMessage | WsDeltaMessage | { type: 'airport_switch_progress'; data: unknown };

export function useFlights(): UseFlightsResult {
  const [wsData, setWsData] = useState<FlightsResponse | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectCount = useRef(0);
  const flightsMapRef = useRef<Map<string, Flight>>(new Map());
  const MAX_RECONNECT = 5;

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const ws = new WebSocket(getWsUrl());

      ws.onopen = () => {
        setWsConnected(true);
        reconnectCount.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const msg: WsFlightMessage = JSON.parse(event.data);
          if (msg.type === 'initial' || msg.type === 'flight_update') {
            const fullMsg = msg as WsFullMessage;
            // Full update — replace map entirely
            const map = new Map<string, Flight>();
            for (const f of fullMsg.data.flights) {
              map.set(f.icao24, f);
            }
            flightsMapRef.current = map;
            setWsData({
              flights: fullMsg.data.flights,
              count: fullMsg.data.count,
              timestamp: fullMsg.data.timestamp,
              data_source: 'synthetic',
            });
          } else if (msg.type === 'flight_delta') {
            const deltaMsg = msg as WsDeltaMessage;
            const map = flightsMapRef.current;

            // Remove departed flights
            for (const id of deltaMsg.data.removed) {
              map.delete(id);
            }

            // Merge deltas into existing flights
            for (const delta of deltaMsg.data.deltas) {
              const icao24 = delta.icao24!;
              const existing = map.get(icao24);
              if (existing) {
                map.set(icao24, { ...existing, ...delta } as Flight);
              } else {
                // New flight — delta contains full data
                map.set(icao24, delta as Flight);
              }
            }

            flightsMapRef.current = map;
            setWsData({
              flights: Array.from(map.values()),
              count: deltaMsg.data.count,
              timestamp: deltaMsg.data.timestamp,
              data_source: 'synthetic',
            });
          }
        } catch {
          // Ignore non-JSON or unexpected messages
        }
      };

      ws.onclose = () => {
        setWsConnected(false);
        wsRef.current = null;
        // Reconnect with back-off
        if (reconnectCount.current < MAX_RECONNECT) {
          reconnectCount.current += 1;
          const delay = Math.min(1000 * 2 ** reconnectCount.current, 10000);
          reconnectTimer.current = setTimeout(connect, delay);
        }
      };

      ws.onerror = () => {
        // onclose will fire after onerror — reconnect handled there
      };

      wsRef.current = ws;
    } catch {
      // WebSocket constructor can throw in some environments
      setWsConnected(false);
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        wsRef.current.onclose = null; // prevent reconnect on unmount
        wsRef.current.close();
      }
    };
  }, [connect]);

  // HTTP polling fallback — only active when WebSocket is not connected
  const { data: httpData, isLoading: httpLoading, error: httpError } = useQuery<FlightsResponse, Error>({
    queryKey: ['flights'],
    queryFn: fetchFlights,
    refetchInterval: wsConnected ? false : 5000, // Disable polling when WS is active
    staleTime: 4000,
    retry: 3,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10000),
    enabled: !wsConnected, // Don't fetch at all when WS is providing data
  });

  // Prefer WebSocket data when available
  const data = wsData ?? httpData;
  const isLoading = !data && httpLoading;
  const error = wsConnected ? null : (httpError ?? null);

  return {
    flights: data?.flights ?? [],
    isLoading,
    error,
    lastUpdated: data?.timestamp ?? null,
    dataSource: data?.data_source ?? null,
  };
}
