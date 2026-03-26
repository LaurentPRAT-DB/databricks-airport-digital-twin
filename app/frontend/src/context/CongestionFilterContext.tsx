import { createContext, useContext, useState, ReactNode } from 'react';

interface CongestionFilterState {
  /** Active congestion level filter (null = show all) */
  activeLevel: string | null;
  setActiveLevel: (level: string | null) => void;
}

const CongestionFilterContext = createContext<CongestionFilterState>({
  activeLevel: null,
  setActiveLevel: () => {},
});

export function CongestionFilterProvider({ children }: { children: ReactNode }) {
  const [activeLevel, setActiveLevel] = useState<string | null>(null);
  return (
    <CongestionFilterContext.Provider value={{ activeLevel, setActiveLevel }}>
      {children}
    </CongestionFilterContext.Provider>
  );
}

export function useCongestionFilter() {
  return useContext(CongestionFilterContext);
}
