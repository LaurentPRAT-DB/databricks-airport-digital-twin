/**
 * Bottom-right floating control stack: Legend + Dark Mode toggle.
 * Positioned to align vertically with the GenieChat FAB below.
 * All icons use same w-10 h-10 rounded-full to match the brand icon (bottom-left).
 */

import { useState, useRef, useEffect } from 'react';
import { useTheme } from '../../context/ThemeContext';
import { useFlightContext } from '../../context/FlightContext';
import { PHASE_BG_CLASSES, PHASE_LABELS } from '../../utils/phaseUtils';

const PHASE_GROUPS: { label: string; phases: { key: string; description: string }[] }[] = [
  {
    label: 'Ground',
    phases: [
      { key: 'parked', description: 'At gate' },
      { key: 'pushback', description: 'Pushed back' },
      { key: 'taxi_out', description: 'Taxi to runway' },
      { key: 'taxi_in', description: 'Taxi to gate' },
    ],
  },
  {
    label: 'Departure',
    phases: [
      { key: 'takeoff', description: 'Lifting off' },
      { key: 'departing', description: 'Climbing out' },
    ],
  },
  {
    label: 'Arrival',
    phases: [
      { key: 'approaching', description: 'Descending' },
      { key: 'landing', description: 'Final / touchdown' },
    ],
  },
  {
    label: 'Cruise',
    phases: [
      { key: 'enroute', description: 'At altitude' },
    ],
  },
];

const ALL_PHASES = PHASE_GROUPS.flatMap(g => g.phases.map(p => p.key));

export function BottomRightControls() {
  const { isDark, toggle: toggleTheme } = useTheme();
  const { hiddenPhases, togglePhase, setHiddenPhases } = useFlightContext();
  const [legendOpen, setLegendOpen] = useState(false);
  const legendRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!legendOpen) return;
    const handler = (e: MouseEvent) => {
      if (legendRef.current && !legendRef.current.contains(e.target as Node)) setLegendOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [legendOpen]);

  const allVisible = hiddenPhases.size === 0;
  const visibleCount = ALL_PHASES.length - hiddenPhases.size;

  return (
    <div
      className="fixed right-4 z-[1100] flex flex-col items-center gap-3"
      style={{ bottom: 'calc(4.5rem + var(--tab-bar-h, 0px))' }}
    >
      {/* Legend */}
      <div ref={legendRef} className="relative">
        <button
          onClick={() => setLegendOpen(o => !o)}
          className="w-10 h-10 flex items-center justify-center rounded-full bg-slate-700 hover:bg-slate-600 transition-colors text-white shadow-lg"
          title="Flight phase legend"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
            <path fillRule="evenodd" d="M2 3.5A1.5 1.5 0 0 1 3.5 2h9A1.5 1.5 0 0 1 14 3.5v11.75A2.75 2.75 0 0 0 16.75 18h-12A2.75 2.75 0 0 1 2 15.25V3.5Zm3.75 7a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5h-4.5Zm0 3a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5h-4.5ZM5 5.75A.75.75 0 0 1 5.75 5h4.5a.75.75 0 0 1 .75.75v2.5a.75.75 0 0 1-.75.75h-4.5A.75.75 0 0 1 5 8.25v-2.5Z" clipRule="evenodd" />
            <path d="M16.5 6.5h-1v8.75a1.25 1.25 0 1 0 2.5 0V8a1.5 1.5 0 0 0-1.5-1.5Z" />
          </svg>
          {!allVisible && (
            <span className="absolute -top-1 -right-1 bg-blue-600 text-white text-[9px] w-4 h-4 flex items-center justify-center rounded-full font-bold">
              {visibleCount}
            </span>
          )}
        </button>

        {legendOpen && (
          <div className="absolute bottom-full mb-2 right-0 bg-slate-800 rounded-lg shadow-xl border border-slate-600 p-4 z-50 w-[300px]">
            <div className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3">Flight Phases</div>
            {PHASE_GROUPS.map(group => (
              <div key={group.label} className="mb-3 last:mb-0">
                <div className="text-[11px] font-semibold text-slate-300 mb-1">{group.label}</div>
                <div className="space-y-0.5">
                  {group.phases.map(phase => {
                    const visible = !hiddenPhases.has(phase.key);
                    return (
                      <label
                        key={phase.key}
                        className="w-full flex items-center gap-2 px-2 py-1 rounded cursor-pointer hover:bg-slate-700/50 transition-colors"
                      >
                        <input
                          type="checkbox"
                          checked={visible}
                          onChange={() => togglePhase(phase.key)}
                          className="sr-only peer"
                        />
                        <span className={`w-3.5 h-3.5 rounded flex-shrink-0 border-2 flex items-center justify-center transition-colors ${
                          visible ? 'border-blue-500 bg-blue-500' : 'border-slate-500 bg-transparent'
                        }`}>
                          {visible && (
                            <svg className="w-2 h-2 text-white" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2">
                              <path d="M2 6l3 3 5-5" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                          )}
                        </span>
                        <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${visible ? PHASE_BG_CLASSES[phase.key] : 'bg-slate-600'}`} />
                        <span className={`text-xs ${visible ? 'text-slate-200' : 'text-slate-500'}`}>
                          {PHASE_LABELS[phase.key]}
                        </span>
                        <span className={`text-[10px] ml-auto ${visible ? 'text-slate-400' : 'text-slate-600'}`}>
                          {phase.description}
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>
            ))}
            <div className="flex gap-3 mt-3 pt-2 border-t border-slate-700">
              <button onClick={() => setHiddenPhases(new Set())} className="text-xs text-blue-400 hover:text-blue-300 cursor-pointer">Show All</button>
              <button onClick={() => setHiddenPhases(new Set(ALL_PHASES))} className="text-xs text-blue-400 hover:text-blue-300 cursor-pointer">Hide All</button>
            </div>
          </div>
        )}
      </div>

      {/* Dark mode toggle */}
      <button
        onClick={toggleTheme}
        className="w-10 h-10 flex items-center justify-center rounded-full bg-slate-700 hover:bg-slate-600 transition-colors text-white shadow-lg"
        title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      >
        {isDark ? (
          <svg className="w-5 h-5 text-amber-300" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" clipRule="evenodd" />
          </svg>
        ) : (
          <svg className="w-5 h-5 text-slate-300" fill="currentColor" viewBox="0 0 20 20">
            <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
          </svg>
        )}
      </button>
    </div>
  );
}
