import { useMemo } from 'react';
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

// Build gates from OSM data, falling back to hardcoded defaults
function buildGates(osmGates: OSMGate[]): Gate[] {
  if (osmGates.length > 0) {
    return osmGates.map((g) => ({
      id: g.id,
      ref: g.ref || g.id,
      terminal: g.terminal || 'Unknown',
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

// Group gates by terminal name
function groupByTerminal(gates: Gate[]): Map<string, Gate[]> {
  const groups = new Map<string, Gate[]>();
  for (const gate of gates) {
    const existing = groups.get(gate.terminal) || [];
    existing.push(gate);
    groups.set(gate.terminal, existing);
  }
  return groups;
}

// Get congestion for a terminal (try exact match, then normalized match)
function getTerminalCongestion(
  terminalName: string,
  congestion: CongestionArea[]
): CongestionArea | undefined {
  // Try exact area_id match first
  const normalized = terminalName.toLowerCase().replace(/\s+/g, '_');
  return congestion.find((c) => {
    const cNorm = c.area_id.toLowerCase();
    return cNorm === normalized || cNorm === `${normalized}_apron` || cNorm.includes(normalized);
  });
}

// Congestion indicator component
function CongestionIndicator({ congestion }: { congestion?: CongestionArea }) {
  if (!congestion) {
    return null;
  }

  const colors = congestionColors[congestion.level] || congestionColors.low;
  const levelLabel = congestion.level.charAt(0).toUpperCase() + congestion.level.slice(1);

  return (
    <div
      className={`ml-2 px-2 py-0.5 rounded text-xs border ${colors.bg} ${colors.text} ${colors.border}`}
    >
      {levelLabel}
      {congestion.wait_minutes > 0 && (
        <span className="ml-1">({congestion.wait_minutes} min wait)</span>
      )}
    </div>
  );
}

// Pick adaptive grid columns based on gate count
function gridColsClass(count: number): string {
  if (count <= 5) return 'grid-cols-5';
  if (count <= 8) return 'grid-cols-8';
  if (count <= 10) return 'grid-cols-10';
  if (count <= 12) return 'grid-cols-12';
  // For large counts, cap at 15 per row
  return 'grid-cols-[repeat(15,minmax(0,1fr))]';
}

export default function GateStatus() {
  const { getGates } = useAirportConfigContext();
  const osmGates = getGates();

  // Memoize gates so they don't change on every render (stable per osmGates reference)
  const gates = useMemo(() => buildGates(osmGates), [osmGates]);
  const terminalGroups = useMemo(() => groupByTerminal(gates), [gates]);

  // Fetch congestion data
  const { congestion, isLoading: isCongestionLoading } = useCongestion();

  const occupiedCount = gates.filter((g) => g.isOccupied).length;
  const availableCount = gates.length - occupiedCount;

  return (
    <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-slate-700">Gate Status</h3>
        <div className="flex items-center gap-3 text-xs">
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

      {/* Dynamic terminal sections */}
      {Array.from(terminalGroups.entries()).map(([terminalName, terminalGates], idx) => (
        <div key={terminalName} className={idx < terminalGroups.size - 1 ? 'mb-4' : ''}>
          <div className="flex items-center mb-2">
            <span className="text-xs font-medium text-slate-500">{terminalName}</span>
            {!isCongestionLoading && (
              <CongestionIndicator congestion={getTerminalCongestion(terminalName, congestion)} />
            )}
          </div>
          <div className={`grid ${gridColsClass(terminalGates.length)} gap-1`}>
            {terminalGates.map((gate) => (
              <div
                key={gate.id}
                className={`
                  aspect-square flex items-center justify-center
                  text-xs font-medium rounded cursor-pointer
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
      ))}

      {/* Congestion Legend */}
      <div className="mt-3 pt-3 border-t border-slate-100">
        <div className="text-xs font-medium text-slate-500 mb-2">Area Congestion</div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(congestionColors).map(([level, colors]) => (
            <span
              key={level}
              className={`px-2 py-0.5 rounded text-xs ${colors.bg} ${colors.text}`}
            >
              {level.charAt(0).toUpperCase() + level.slice(1)}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
