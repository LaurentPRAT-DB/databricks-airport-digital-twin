import { useState, useEffect, useRef, useCallback } from 'react';

interface UseWebSocketOptions {
  url: string;
  reconnectAttempts?: number;
  reconnectInterval?: number;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (error: Event) => void;
}

interface UseWebSocketResult<T> {
  lastMessage: T | null;
  isConnected: boolean;
  error: Event | null;
  send: (data: string | object) => void;
  reconnect: () => void;
}

export function useWebSocket<T = unknown>({
  url,
  reconnectAttempts = 5,
  reconnectInterval = 10000,
  onOpen,
  onClose,
  onError,
}: UseWebSocketOptions): UseWebSocketResult<T> {
  const [lastMessage, setLastMessage] = useState<T | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<Event | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectCountRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const permanentFailureRef = useRef(false);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    if (permanentFailureRef.current) {
      return;
    }

    try {
      wsRef.current = new WebSocket(url);

      wsRef.current.onopen = () => {
        setIsConnected(true);
        setError(null);
        reconnectCountRef.current = 0;
        permanentFailureRef.current = false;
        onOpen?.();
      };

      wsRef.current.onclose = (event) => {
        setIsConnected(false);
        onClose?.();

        // 403 = permanent auth/proxy error, don't retry
        if (event.code === 1006 || event.code === 403) {
          // Check if we got a 403-like rejection (WebSocket proxy rejection
          // often manifests as code 1006 with no prior open)
          if (!event.wasClean && reconnectCountRef.current === 0) {
            // First unclean close without ever connecting — likely proxy rejection
            permanentFailureRef.current = true;
            console.warn('WebSocket connection rejected (likely 403/proxy). Retries disabled.');
            return;
          }
        }

        // Attempt to reconnect with exponential backoff
        if (reconnectCountRef.current < reconnectAttempts && !permanentFailureRef.current) {
          const backoff = Math.min(
            reconnectInterval * Math.pow(2, reconnectCountRef.current),
            60000
          );
          reconnectCountRef.current += 1;
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, backoff);
        } else if (reconnectCountRef.current >= reconnectAttempts) {
          console.warn(`WebSocket: max reconnect attempts (${reconnectAttempts}) reached. Giving up.`);
        }
      };

      wsRef.current.onerror = (event) => {
        setError(event);
        onError?.(event);
      };

      wsRef.current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as T;
          setLastMessage(data);
        } catch {
          // If not JSON, set raw data
          setLastMessage(event.data as T);
        }
      };
    } catch (err) {
      console.error('WebSocket connection error:', err);
    }
  }, [url, reconnectAttempts, reconnectInterval, onOpen, onClose, onError]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  const send = useCallback((data: string | object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const message = typeof data === 'string' ? data : JSON.stringify(data);
      wsRef.current.send(message);
    } else {
      console.warn('WebSocket is not connected');
    }
  }, []);

  const reconnect = useCallback(() => {
    disconnect();
    reconnectCountRef.current = 0;
    permanentFailureRef.current = false;
    connect();
  }, [connect, disconnect]);

  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return {
    lastMessage,
    isConnected,
    error,
    send,
    reconnect,
  };
}
