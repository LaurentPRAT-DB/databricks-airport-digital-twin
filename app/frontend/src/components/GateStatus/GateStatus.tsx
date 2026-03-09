import { useMemo, useState } from 'react';
import { useCongestion } from '../../hooks/usePredictions';
import { useAirportConfigContext } from '../../context/AirportConfigContext';
import { CongestionArea } from '../../types/flight';
import { OSMGate } from '../../types/airportFormats';

interface Gate {
  id: string;
  ref: string;
  terminal: string;
  isOccupied: boolean;
}

// Congestion level colors
const congestionColors: Record<string, { bg: string; text: string; border: string }> = {
  low: { bg: 'bg-green-100', text: 'text-green-700', border: 'border-green-300' },
  moderate: { bg: 'bg-yellow-100', text: 'text-yellow-700', border: 'border-yellow-300' },
  high: { bg: 'bg-orange-100', text: 'text-orange-700', border: 'border-orange-300' },
  critical: { bg: 'bg-red-100', text: 'text-red-700', border: 'border-red-300' },
};

// Natural sort comparator: A1, A2, A10 (not A1, A10, A2)
function naturalSort(a: string, b: string): number {
  const re = /(\d+)|(\D+)/g;
  const aParts = a.match(re) || [];
  const bParts = b.match(re) || [];
  for (let i = 0; i < Math.max(aParts.length, bParts.length); i++) {
    const ap = aParts[i] || '';
    const bp = bParts[i] || '';
    const an = parseInt(ap, 10);
    const bn = parseInt(bp, 10);
    if (!isNaN(an) && !isNaN(bn)) {
      if (an !== bn) return an - bn;
    } else {
      const cmp = ap.localeCompare(bp);
      if (cmp !== 0) return cmp;
    }
  }
  return 0;
}

// Infer terminal from gate ref prefix when terminal field is missing
function inferTerminal(ref: string): string {
  const match = ref.match(/^([A-Za-z]+)/);
  if (match) {
    return `Terminal ${match[1].toUpperCase()}`;
  }
  return 'Other';
}

// Build gates from OSM data, falling back to hardcoded defaults
function buildGates(osmGates: OSMGate[]): Gate[] {
  if (osmGates.length > 0) {
    return osmGates.map((g) => ({
      id: g.id,
      ref: g.ref || g.id,
      terminal: g.terminal || inferTerminal(g.ref || g.id),
      isOccupied: Math.random() > 0.6, // ~40% occupied (demo)
    }));
  }

  // Fallback: hardcoded defaults
  const gates: Gate[] = [];
  for (let i = 1; i <= 10; i++) {
    gates.push({ id: `A${i}`, ref: `A${i}`, terminal: 'Terminal A', isOccupied: Math.random() > 0.6 });
  }
  for (let i = 1; i <= 10; i++) {
    gates.push({ id: `B${i}`, ref: `B${i}`, terminal: 'Terminal B', isOccupied: Math.random() > 0.6 });
  }
  return gates;
}

// Group gates by terminal name, sorting gates naturally within each group
function groupByTerminal(gates: Gate[]): Map<string, Gate[]> {
  const groups = new Map<string, Gate[]>();
  for (const gate of gates) {
    const existing = groups.get(gate.terminal) || [];
    existing.push(gate);
    groups.set(gate.terminal, existing);
  }
  // Sort gates within each group
  for (const [key, gateList] of groups) {
    groups.set(key, gateList.sort((a, b) => naturalSort(a.ref, b.ref)));
  }
  return groups;
}

// Get congestion for a terminal (try exact match, then normalized match)
function getTerminalCongestion(
  terminalName: string,
  congestion: CongestionArea[]
): CongestionArea | undefined {
  const normalized = terminalName.toLowerCase().replace(/\s+/g, '_');
  return congestion.find((c) => {
    const cNorm = c.area_id.toLowerCase();
    return cNorm === normalized || cNorm === `${normalized}_apron` || cNorm.includes(normalized);
  });
}

// Congestion indicator component
function CongestionIndicator({ congestion }: { congestion?: CongestionArea }) {
  if (!congestion) return null;
  const colors = congestionColors[congestion.level] || congestionColors.low;
  const levelLabel = congestion.level.charAt(0).toUpperCase() + congestion.level.slice(1);
  return (
    <span className={`ml-2 px-1.5 py-0.5 rounded text-[10px] border ${colors.bg} ${colors.text} ${colors.border}`}>
      {levelLabel}
      {congestion.wait_minutes > 0 && <span className="ml-1">({congestion.wait_minutes}m)</span>}
    </span>
  );
}

export default function GateStatus() {
  const { getGates } = useAirportConfigContext();
  const osmGates = getGates();
  const [selectedTerminal, setSelectedTerminal] = useState<string | null>(null);

  const gates = useMemo(() => buildGates(osmGates), [osmGates]);
  const terminalGroups = useMemo(() => groupByTerminal(gates), [gates]);
  const terminalNames = useMemo(
    () => Array.from(terminalGroups.keys()).sort((a, b) => naturalSort(a, b)),
    [terminalGroups]
  );

  const { congestion, isLoading: isCongestionLoading } = useCongestion();

  const occupiedCount = gates.filter((g) => g.isOccupied).length;
  const availableCount = gates.length - occupiedCount;

  return (
    <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-3">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-semibold text-slate-700 text-sm">Gate Status</h3>
        <div className="flex items-center gap-2 text-[11px]">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-green-500" />
            {availableCount} Available
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-red-500" />
            {occupiedCount} Occupied
          </span>
        </div>
      </div>

      {/* Terminal filter pills */}
      <div className="flex flex-wrap gap-1 mb-2" role="tablist">
        <button
          role="tab"
          aria-selected={selectedTerminal === null}
          className={`px-2 py-0.5 rounded-full text-[11px] font-medium transition-colors
            ${selectedTerminal === null
              ? 'bg-blue-600 text-white'
              : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          onClick={() => setSelectedTerminal(null)}
        >
          All
        </button>
        {terminalNames.map((name) => {
          const short = name.replace(/^Terminal\s*/i, '');
          return (
            <button
              key={name}
              role="tab"
              aria-selected={selectedTerminal === name}
              className={`px-2 py-0.5 rounded-full text-[11px] font-medium transition-colors
                ${selectedTerminal === name
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              onClick={() => setSelectedTerminal(name)}
            >
              {short}
            </button>
          );
        })}
      </div>

      {/* Summary view (All selected) */}
      {selectedTerminal === null && (
        <div className="space-y-1">
          {terminalNames.map((name) => {
            const tGates = terminalGroups.get(name) || [];
            const occ = tGates.filter((g) => g.isOccupied).length;
            const avail = tGates.length - occ;
            return (
              <button
                key={name}
                className="w-full flex items-center justify-between px-2 py-1.5 rounded hover:bg-slate-50 transition-colors text-left"
                onClick={() => setSelectedTerminal(name)}
              >
                <div className="flex items-center">
                  <span className="text-xs font-medium text-slate-700">{name}</span>
                  {!isCongestionLoading && (
                    <CongestionIndicator congestion={getTerminalCongestion(name, congestion)} />
                  )}
                </div>
                <div className="flex items-center gap-2 text-[11px]">
                  <span className="text-green-600">{avail} free</span>
                  <span className="text-slate-300">|</span>
                  <span className="text-red-500">{occ} used</span>
                  <span className="text-slate-400">/ {tGates.length}</span>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* Terminal detail view (specific terminal selected) */}
      {selectedTerminal !== null && (
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <div className="flex items-center">
              <span className="text-xs font-medium text-slate-700">{selectedTerminal}</span>
              {!isCongestionLoading && (
                <CongestionIndicator congestion={getTerminalCongestion(selectedTerminal, congestion)} />
              )}
            </div>
            <span className="text-[11px] text-slate-400">
              {(terminalGroups.get(selectedTerminal) || []).length} gates
            </span>
          </div>
          <div className="grid grid-cols-8 gap-1">
            {(terminalGroups.get(selectedTerminal) || []).map((gate) => (
              <div
                key={gate.id}
                className={`
                  aspect-square flex items-center justify-center
                  text-[10px] font-medium rounded cursor-pointer
                  transition-colors duration-150
                  ${gate.isOccupied
                    ? 'bg-red-100 text-red-700 hover:bg-red-200'
                    : 'bg-green-100 text-green-700 hover:bg-green-200'
                  }
                `}
                title={`${gate.ref}: ${gate.isOccupied ? 'Occupied' : 'Available'}`}
              >
                {gate.ref}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Congestion Legend */}
      <div className="mt-2 pt-2 border-t border-slate-100">
        <div className="text-[10px] font-medium text-slate-500 mb-1">Area Congestion</div>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(congestionColors).map(([level, colors]) => (
            <span
              key={level}
              className={`px-1.5 py-0.5 rounded text-[10px] ${colors.bg} ${colors.text}`}
            >
              {level.charAt(0).toUpperCase() + level.slice(1)}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
