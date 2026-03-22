import { useState, useEffect } from 'react';

const MOBILE_BREAKPOINT = '(max-width: 767px)';

export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === 'undefined') return false;
    const matches = window.matchMedia(MOBILE_BREAKPOINT).matches;
    console.log(`[useIsMobile] init: viewport=${window.innerWidth}x${window.innerHeight}, matches=${matches}, userAgent=${navigator.userAgent.slice(0, 80)}`);
    return matches;
  });

  useEffect(() => {
    const mql = window.matchMedia(MOBILE_BREAKPOINT);
    const handler = (e: MediaQueryListEvent) => {
      console.log(`[useIsMobile] changed: matches=${e.matches}, viewport=${window.innerWidth}x${window.innerHeight}`);
      setIsMobile(e.matches);
    };
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, []);

  return isMobile;
}
