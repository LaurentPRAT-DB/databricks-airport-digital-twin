import { useState, useEffect, useRef } from 'react';

interface UseConnectionHealthOptions {
  enabled: boolean;
  interval?: number;
  failureThreshold?: number;
}

interface UseConnectionHealthResult {
  isDown: boolean;
  wasDown: boolean;
}

export function useConnectionHealth({
  enabled,
  interval = 10_000,
  failureThreshold = 2,
}: UseConnectionHealthOptions): UseConnectionHealthResult {
  const [isDown, setIsDown] = useState(false);
  const [wasDown, setWasDown] = useState(false);
  const failCountRef = useRef(0);
  const wasDownRef = useRef(false);

  useEffect(() => {
    if (!enabled) return;

    const check = async () => {
      try {
        const res = await fetch('/health', { signal: AbortSignal.timeout(5000) });
        if (res.ok) {
          if (failCountRef.current >= failureThreshold) {
            wasDownRef.current = true;
            setWasDown(true);
          }
          failCountRef.current = 0;
          setIsDown(false);
        } else {
          failCountRef.current += 1;
          if (failCountRef.current >= failureThreshold) {
            setIsDown(true);
          }
        }
      } catch {
        failCountRef.current += 1;
        if (failCountRef.current >= failureThreshold) {
          setIsDown(true);
        }
      }
    };

    const timer = setInterval(check, interval);
    return () => clearInterval(timer);
  }, [enabled, interval, failureThreshold]);

  return { isDown, wasDown };
}
