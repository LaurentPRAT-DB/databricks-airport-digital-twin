import { useEffect, useRef, useState } from 'react';
import { useFlightContext } from '../../context/FlightContext';
import { PHASE_BG_CLASSES, PHASE_LABELS } from '../../utils/phaseUtils';

/** Phase groups for the dropdown layout. */
const PHASE_GROUPS: { label: string; phases: string[] }[] = [
  { label: 'Ground', phases: ['parked', 'pushback', 'taxi_out', 'taxi_in'] },
  { label: 'Departure', phases: ['takeoff', 'departing'] },
  { label: 'Arrival', phases: ['approaching', 'landing'] },
  { label: 'Cruise', phases: ['enroute'] },
];

const ALL_PHASES = PHASE_GROUPS.flatMap(g => g.phases);

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
        className="flex items-center gap-1.5 bg-slate-700 hover:bg-slate-600 px-2.5 py-0.5 rounded-full text-xs font-medium transition-colors cursor-pointer"
        title="Filter flights by phase"
      >
        <span>Phases</span>
        {!allVisible && (
          <span className="bg-blue-600 text-white px-1.5 rounded-full text-[10px] leading-4">
            {visibleCount}/{ALL_PHASES.length}
          </span>
        )}
        <span className="text-slate-400 text-[10px]">{isOpen ? '\u25B4' : '\u25BE'}</span>
      </button>

      {isOpen && (
        <div className="absolute top-full mt-1 left-0 bg-slate-800 rounded-lg shadow-xl border border-slate-600 p-3 z-50 min-w-[260px]">
          {PHASE_GROUPS.map(group => (
            <div key={group.label} className="mb-2 last:mb-0">
              <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">{group.label}</div>
              <div className="flex flex-wrap gap-1.5">
                {group.phases.map(phase => {
                  const hidden = hiddenPhases.has(phase);
                  return (
                    <button
                      key={phase}
                      onClick={() => togglePhase(phase)}
                      className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium transition-all cursor-pointer border ${
                        hidden
                          ? 'border-slate-600 text-slate-500 line-through opacity-50'
                          : 'border-slate-500 text-slate-200'
                      }`}
                    >
                      <span className={`w-2 h-2 rounded-full ${hidden ? 'bg-slate-600' : PHASE_BG_CLASSES[phase]}`} />
                      {PHASE_LABELS[phase]}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}

          <div className="flex gap-2 mt-3 pt-2 border-t border-slate-700">
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
