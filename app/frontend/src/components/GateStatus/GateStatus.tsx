import { useMemo } from 'react';

interface Gate {
  id: string;
  terminal: 'A' | 'B';
  number: number;
  isOccupied: boolean;
}

// Generate gates with random occupancy for demo
// In Phase 3, this will use ML predictions
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

export default function GateStatus() {
  // Memoize gates so they don't change on every render
  // In production, this would come from an API
  const gates = useMemo(() => generateGates(), []);

  const terminalA = gates.filter((g) => g.terminal === 'A');
  const terminalB = gates.filter((g) => g.terminal === 'B');

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

      {/* Terminal A */}
      <div className="mb-4">
        <div className="text-xs font-medium text-slate-500 mb-2">Terminal A</div>
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
        <div className="text-xs font-medium text-slate-500 mb-2">Terminal B</div>
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

      <div className="mt-3 text-xs text-slate-400 text-center">
        Demo data - ML predictions in Phase 3
      </div>
    </div>
  );
}
