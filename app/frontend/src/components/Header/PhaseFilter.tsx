import { useEffect, useRef, useState } from 'react';
import { useFlightContext } from '../../context/FlightContext';
import { PHASE_BG_CLASSES, PHASE_LABELS } from '../../utils/phaseUtils';

/** Phase groups with descriptions for the legend panel. */
const PHASE_GROUPS: { label: string; description: string; phases: { key: string; description: string }[] }[] = [
  {
    label: 'Ground',
    description: 'Aircraft on the airport surface',
    phases: [
      { key: 'parked', description: 'At gate, loading/unloading' },
      { key: 'pushback', description: 'Pushed back from gate, engines starting' },
      { key: 'taxi_out', description: 'Taxiing to departure runway' },
      { key: 'taxi_in', description: 'Taxiing from runway to gate after landing' },
    ],
  },
  {
    label: 'Departure',
    description: 'Aircraft leaving the airport',
    phases: [
      { key: 'takeoff', description: 'Accelerating on runway, lifting off' },
      { key: 'departing', description: 'Climbing away from the airport' },
    ],
  },
  {
    label: 'Arrival',
    description: 'Aircraft arriving at the airport',
    phases: [
      { key: 'approaching', description: 'Descending toward the airport' },
      { key: 'landing', description: 'On final approach or touching down' },
    ],
  },
  {
    label: 'Cruise',
    description: 'Aircraft in transit',
    phases: [
      { key: 'enroute', description: 'Flying at cruise altitude between airports' },
    ],
  },
];

const ALL_PHASES = PHASE_GROUPS.flatMap(g => g.phases.map(p => p.key));

export default function PhaseFilter() {
  const { hiddenPhases, togglePhase, setHiddenPhases } = useFlightContext();
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setIsOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [isOpen]);

  const visibleCount = ALL_PHASES.length - hiddenPhases.size;
  const allVisible = hiddenPhases.size === 0;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setIsOpen(o => !o)}
        className="flex items-center gap-1.5 bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors cursor-pointer"
        title="Flight phase legend and visibility filter"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4 text-slate-300">
          <path fillRule="evenodd" d="M2 3.5A1.5 1.5 0 0 1 3.5 2h9A1.5 1.5 0 0 1 14 3.5v11.75A2.75 2.75 0 0 0 16.75 18h-12A2.75 2.75 0 0 1 2 15.25V3.5Zm3.75 7a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5h-4.5Zm0 3a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5h-4.5ZM5 5.75A.75.75 0 0 1 5.75 5h4.5a.75.75 0 0 1 .75.75v2.5a.75.75 0 0 1-.75.75h-4.5A.75.75 0 0 1 5 8.25v-2.5Z" clipRule="evenodd" />
          <path d="M16.5 6.5h-1v8.75a1.25 1.25 0 1 0 2.5 0V8a1.5 1.5 0 0 0-1.5-1.5Z" />
        </svg>
        <span>Legend</span>
        {!allVisible && (
          <span className="bg-blue-600 text-white px-1.5 rounded-full text-[10px] leading-4">
            {visibleCount}/{ALL_PHASES.length}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="absolute top-full mt-1 right-0 bg-slate-800 rounded-lg shadow-xl border border-slate-600 p-4 z-50 w-[340px]">
          <div className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3">Flight Phases</div>
          <p className="text-[11px] text-slate-400 mb-3">
            Click any phase to show/hide flights on the map.
          </p>

          {PHASE_GROUPS.map(group => (
            <div key={group.label} className="mb-3 last:mb-0">
              <div className="text-[11px] font-semibold text-slate-300 mb-0.5">{group.label}</div>
              <div className="text-[10px] text-slate-500 mb-1.5">{group.description}</div>
              <div className="space-y-1">
                {group.phases.map(phase => {
                  const hidden = hiddenPhases.has(phase.key);
                  return (
                    <button
                      key={phase.key}
                      onClick={() => togglePhase(phase.key)}
                      className={`w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-left transition-all cursor-pointer ${
                        hidden
                          ? 'opacity-40 hover:opacity-60'
                          : 'hover:bg-slate-700/50'
                      }`}
                    >
                      <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${hidden ? 'bg-slate-600' : PHASE_BG_CLASSES[phase.key]}`} />
                      <span className={`text-xs font-medium min-w-[70px] ${hidden ? 'text-slate-500 line-through' : 'text-slate-200'}`}>
                        {PHASE_LABELS[phase.key]}
                      </span>
                      <span className={`text-[11px] ${hidden ? 'text-slate-600' : 'text-slate-400'}`}>
                        {phase.description}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}

          <div className="flex gap-3 mt-3 pt-2.5 border-t border-slate-700">
            <button
              onClick={() => setHiddenPhases(new Set())}
              className="text-xs text-blue-400 hover:text-blue-300 transition-colors cursor-pointer"
            >
              Show All
            </button>
            <button
              onClick={() => setHiddenPhases(new Set(ALL_PHASES))}
              className="text-xs text-blue-400 hover:text-blue-300 transition-colors cursor-pointer"
            >
              Hide All
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
