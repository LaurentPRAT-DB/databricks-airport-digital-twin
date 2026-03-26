import { createContext, useContext, useState, ReactNode } from 'react';
import { CongestionArea } from '../types/flight';

interface CongestionFilterState {
  /** Active congestion level filter (null = show all) */
  activeLevel: string | null;
  setActiveLevel: (level: string | null) => void;
  /** Selected congestion area (clicked on map or panel) */
  selectedArea: CongestionArea | null;
  setSelectedArea: (area: CongestionArea | null) => void;
}

const CongestionFilterContext = createContext<CongestionFilterState>({
  activeLevel: null,
  setActiveLevel: () => {},
  selectedArea: null,
  setSelectedArea: () => {},
});

export function CongestionFilterProvider({ children }: { children: ReactNode }) {
  const [activeLevel, setActiveLevel] = useState<string | null>(null);
  const [selectedArea, setSelectedArea] = useState<CongestionArea | null>(null);
  return (
    <CongestionFilterContext.Provider value={{ activeLevel, setActiveLevel, selectedArea, setSelectedArea }}>
      {children}
    </CongestionFilterContext.Provider>
  );
}

export function useCongestionFilter() {
  return useContext(CongestionFilterContext);
}
