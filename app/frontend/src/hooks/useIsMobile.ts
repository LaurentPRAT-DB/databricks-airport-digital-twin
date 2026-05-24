import { useState } from 'react';

function detectMobile(): boolean {
  if (typeof window === 'undefined') return false;
  const hasTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
  const coarsePointer = window.matchMedia('(pointer: coarse)').matches;
  const narrow = window.matchMedia('(max-width: 767px)').matches;
  return (hasTouch && coarsePointer) || narrow;
}

export function useIsMobile(): boolean {
  const [isMobile] = useState(detectMobile);
  return isMobile;
}
