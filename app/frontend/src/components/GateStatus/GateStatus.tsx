import { useMemo } from 'react';
import { useCongestion } from '../../hooks/usePredictions';
import { CongestionArea } from '../../types/flight';

interface Gate {
  id: string;
  terminal: 'A' | 'B';
  number: number;
  isOccupied: boolean;
}

// Congestion level colors
const congestionColors: Record<string, { bg: string; text: string; border: string }> = {
  low: { bg: 'bg-green-100', text: 'text-green-700', border: 'border-green-300' },
  moderate: { bg: 'bg-yellow-100', text: 'text-yellow-700', border: 'border-yellow-300' },
  high: { bg: 'bg-orange-100', text: 'text-orange-700', border: 'border-orange-300' },
  critical: { bg: 'bg-red-100', text: 'text-red-700', border: 'border-red-300' },
};

// Generate gates with random occupancy for demo
function generateGates(): Gate[] {
  const gates: Gate[] = [];

  // Terminal A: A1-A10
  for (let i = 1; i <= 10; i++) {
    gates.push({
      id: `A${i}`,
      terminal: 'A',
      number: i,
      isOccupied: Math.random() > 0.6, // ~40% occupied
    });
  }

  // Terminal B: B1-B10
  for (let i = 1; i <= 10; i++) {
    gates.push({
      id: `B${i}`,
      terminal: 'B',
      number: i,
      isOccupied: Math.random() > 0.6, // ~40% occupied
    });
  }

  return gates;
}

// Get congestion for a terminal apron
function getTerminalCongestion(
  terminal: 'A' | 'B',
  congestion: CongestionArea[]
): CongestionArea | undefined {
  const areaId = `terminal_${terminal}_apron`;
  return congestion.find((c) => c.area_id === areaId);
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

export default function GateStatus() {
  // Memoize gates so they don't change on every render
  const gates = useMemo(() => generateGates(), []);

  // Fetch congestion data
  const { congestion, isLoading: isCongestionLoading } = useCongestion();

  const terminalA = gates.filter((g) => g.terminal === 'A');
  const terminalB = gates.filter((g) => g.terminal === 'B');

  const occupiedCount = gates.filter((g) => g.isOccupied).length;
  const availableCount = gates.length - occupiedCount;

  // Get congestion for each terminal
  const terminalACongestion = getTerminalCongestion('A', congestion);
  const terminalBCongestion = getTerminalCongestion('B', congestion);

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

      {/* Terminal A */}
      <div className="mb-4">
        <div className="flex items-center mb-2">
          <span className="text-xs font-medium text-slate-500">Terminal A</span>
          {!isCongestionLoading && <CongestionIndicator congestion={terminalACongestion} />}
        </div>
        <div className="grid grid-cols-10 gap-1">
          {terminalA.map((gate) => (
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
              title={`${gate.id}: ${gate.isOccupied ? 'Occupied' : 'Available'}`}
            >
              {gate.number}
            </div>
          ))}
        </div>
      </div>

      {/* Terminal B */}
      <div>
        <div className="flex items-center mb-2">
          <span className="text-xs font-medium text-slate-500">Terminal B</span>
          {!isCongestionLoading && <CongestionIndicator congestion={terminalBCongestion} />}
        </div>
        <div className="grid grid-cols-10 gap-1">
          {terminalB.map((gate) => (
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
              title={`${gate.id}: ${gate.isOccupied ? 'Occupied' : 'Available'}`}
            >
              {gate.number}
            </div>
          ))}
        </div>
      </div>

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
