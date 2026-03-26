import { useMemo, useState, useRef, useEffect } from 'react';
import { useCongestion } from '../../hooks/usePredictions';
import { useAirportConfigContext } from '../../context/AirportConfigContext';
import { useFlightContext } from '../../context/FlightContext';
import { useCongestionFilter } from '../../context/CongestionFilterContext';
import { CongestionArea, Flight } from '../../types/flight';
import { OSMGate } from '../../types/airportFormats';
import { isGroundPhase, isArrivalPhase } from '../../utils/phaseUtils';

type GateStatusLabel = 'ON STAND' | 'TAXI IN' | 'INBOUND' | 'VACANT';

interface Gate {
  id: string;
  ref: string;
  terminal: string;
  isRemoteStand: boolean;
  status: GateStatusLabel;
  flight: Flight | null;
}

// Congestion level colors
const congestionColors: Record<string, { bg: string; text: string; border: string }> = {
  low: { bg: 'bg-green-100', text: 'text-green-700', border: 'border-green-300' },
  moderate: { bg: 'bg-yellow-100', text: 'text-yellow-700', border: 'border-yellow-300' },
  high: { bg: 'bg-orange-100', text: 'text-orange-700', border: 'border-orange-300' },
  critical: { bg: 'bg-red-100', text: 'text-red-700', border: 'border-red-300' },
};

const gateStatusColors: Record<GateStatusLabel, { bg: string; text: string; hover: string }> = {
  'ON STAND': { bg: 'bg-red-200 dark:bg-red-500/40', text: 'text-red-800 dark:text-red-200', hover: 'hover:bg-red-300 dark:hover:bg-red-500/60' },
  'TAXI IN': { bg: 'bg-amber-200 dark:bg-amber-500/40', text: 'text-amber-800 dark:text-amber-200', hover: 'hover:bg-amber-300 dark:hover:bg-amber-500/60' },
  'INBOUND': { bg: 'bg-amber-200 dark:bg-amber-500/40', text: 'text-amber-800 dark:text-amber-200', hover: 'hover:bg-amber-300 dark:hover:bg-amber-500/60' },
  'VACANT': { bg: 'bg-green-100 dark:bg-slate-700/60', text: 'text-green-700 dark:text-slate-400', hover: 'hover:bg-green-200 dark:hover:bg-slate-600' },
};

const statusBadgeColors: Record<GateStatusLabel, string> = {
  'ON STAND': 'bg-red-500 text-white',
  'TAXI IN': 'bg-amber-500 text-white',
  'INBOUND': 'bg-amber-500 text-white',
  'VACANT': 'bg-green-500 text-white',
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
function inferTerminal(ref: string, isRemoteStand: boolean): string {
  if (isRemoteStand) return 'PP';
  // Letter prefix: "A12" → "Terminal A"
  const letterMatch = ref.match(/^([A-Za-z]+)/);
  if (letterMatch) {
    return `Terminal ${letterMatch[1].toUpperCase()}`;
  }
  // Numeric prefix: "17B" or "4" → "Terminal 1" (first digit = terminal)
  // Common at JFK (Terminal 1,2,4,5,7,8) and some international airports
  const digitMatch = ref.match(/^(\d)/);
  if (digitMatch) {
    return `Terminal ${digitMatch[1]}`;
  }
  return 'Other';
}

// Classify the status of a flight at a gate
function classifyGateStatus(flight: Flight): GateStatusLabel {
  if (isGroundPhase(flight.flight_phase)) {
    const vel = Number(flight.velocity) || 0;
    return vel === 0 ? 'ON STAND' : 'TAXI IN';
  }
  if (isArrivalPhase(flight.flight_phase)) {
    return 'INBOUND';
  }
  // Departing/enroute with a gate assigned — treat as on stand (pre-departure)
  return 'ON STAND';
}

// Build a lookup: gate ref → flight + status
function buildGateFlightMap(flights: Flight[]): Map<string, { flight: Flight; status: GateStatusLabel }> {
  const map = new Map<string, { flight: Flight; status: GateStatusLabel }>();
  for (const f of flights) {
    if (f.assigned_gate) {
      const ref = f.assigned_gate;
      const existing = map.get(ref);
      // Prefer ON STAND > TAXI IN > INBOUND (closest to gate wins)
      const status = classifyGateStatus(f);
      const priority: Record<GateStatusLabel, number> = { 'ON STAND': 3, 'TAXI IN': 2, 'INBOUND': 1, 'VACANT': 0 };
      if (!existing || priority[status] > priority[existing.status]) {
        map.set(ref, { flight: f, status });
      }
    }
  }
  return map;
}

// Build gates from OSM data, enriched with flight data
function buildGates(osmGates: OSMGate[], gateFlightMap: Map<string, { flight: Flight; status: GateStatusLabel }>): Gate[] {
  if (osmGates.length > 0) {
    const osmRefs = new Set<string>();
    const gates: Gate[] = osmGates.map((g) => {
      const ref = g.ref || g.id;
      const isRemoteStand = !!g.is_remote_stand;
      osmRefs.add(ref);
      const info = gateFlightMap.get(ref);
      return {
        id: g.id,
        ref,
        terminal: g.terminal || inferTerminal(ref, isRemoteStand),
        isRemoteStand,
        status: info?.status ?? 'VACANT',
        flight: info?.flight ?? null,
      };
    });

    // Include flight-assigned gates not present in OSM data
    for (const [ref, info] of gateFlightMap) {
      if (!osmRefs.has(ref)) {
        gates.push({
          id: ref,
          ref,
          terminal: inferTerminal(ref, false),
          isRemoteStand: false,
          status: info.status,
          flight: info.flight,
        });
      }
    }

    gates.sort((a, b) => naturalSort(a.ref, b.ref));
    return gates;
  }

  // Fallback: derive gates from flights that have assigned gates
  const gates: Gate[] = [];
  for (const [ref, info] of gateFlightMap) {
    gates.push({
      id: ref,
      ref,
      terminal: inferTerminal(ref, false),
      isRemoteStand: false,
      status: info.status,
      flight: info.flight,
    });
  }
  // Sort naturally so A1, A2, A14 etc. are in order
  gates.sort((a, b) => naturalSort(a.ref, b.ref));
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
function CongestionIndicator({ congestion, onClick }: { congestion?: CongestionArea; onClick?: (area: CongestionArea) => void }) {
  if (!congestion) return null;
  const colors = congestionColors[congestion.level] || congestionColors.low;
  const levelLabel = congestion.level.charAt(0).toUpperCase() + congestion.level.slice(1);
  const Tag = onClick ? 'button' : 'span';
  return (
    <Tag
      className={`ml-2 px-1.5 py-0.5 rounded text-[10px] border ${colors.bg} ${colors.text} ${colors.border} ${onClick ? 'cursor-pointer hover:ring-1 hover:ring-blue-400' : ''}`}
      onClick={onClick ? (e) => { e.stopPropagation(); onClick(congestion); } : undefined}
      title={onClick ? 'Click to see congestion details' : undefined}
    >
      {levelLabel}
      {congestion.wait_minutes > 0 && <span className="ml-1">({congestion.wait_minutes}m)</span>}
    </Tag>
  );
}

// Gate detail card shown when a gate is clicked
function GateDetailCard({
  gate,
  onSelectFlight,
  onClose,
}: {
  gate: Gate;
  onSelectFlight: (flight: Flight) => void;
  onClose: () => void;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    cardRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
  }, []);

  const colors = statusBadgeColors[gate.status];

  return (
    <div
      ref={cardRef}
      className="mt-2 p-2.5 bg-slate-50 dark:bg-slate-700 rounded-lg border border-slate-200 dark:border-slate-600 text-xs"
    >
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-slate-700 dark:text-slate-200">Gate {gate.ref}</span>
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${colors}`}>
            {gate.status}
          </span>
        </div>
        <button
          className="text-slate-400 hover:text-slate-600 text-sm leading-none"
          onClick={onClose}
          aria-label="Close gate detail"
        >
          ×
        </button>
      </div>

      {gate.flight ? (
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <button
              className="font-mono font-semibold text-blue-600 hover:text-blue-800 hover:underline"
              onClick={() => onSelectFlight(gate.flight!)}
              title="Select flight on map"
            >
              {gate.flight.callsign || gate.flight.icao24}
            </button>
            {gate.flight.aircraft_type && (
              <span className="text-slate-500">{gate.flight.aircraft_type}</span>
            )}
          </div>
          {(gate.flight.origin_airport || gate.flight.destination_airport) && (
            <div className="text-slate-500">
              {gate.flight.origin_airport || '???'} → {gate.flight.destination_airport || '???'}
            </div>
          )}
          <div className="text-slate-400 capitalize">{gate.flight.flight_phase}</div>
        </div>
      ) : (
        <div className="text-slate-400">No flight assigned</div>
      )}
    </div>
  );
}

// Congestion detail card — shown when an area is selected on the map
function CongestionDetailCard({
  area,
  onClose,
}: {
  area: CongestionArea;
  onClose: () => void;
}) {
  const colors = congestionColors[area.level] || congestionColors.low;
  const levelLabel = area.level.charAt(0).toUpperCase() + area.level.slice(1);
  const areaLabel = area.area_id.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  const utilization = area.capacity > 0 ? Math.round((area.flight_count / area.capacity) * 100) : 0;

  return (
    <div className="mt-2 p-3 bg-slate-50 dark:bg-slate-700 rounded-lg border border-slate-200 dark:border-slate-600 text-xs">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-slate-700 dark:text-slate-200">{areaLabel}</span>
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium border ${colors.bg} ${colors.text} ${colors.border}`}>
            {levelLabel}
          </span>
        </div>
        <button
          className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 text-sm leading-none"
          onClick={onClose}
          aria-label="Close congestion detail"
        >
          ×
        </button>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-3 gap-2 mb-2">
        <div className="text-center p-1.5 bg-white dark:bg-slate-800 rounded border border-slate-100 dark:border-slate-600">
          <div className="text-lg font-bold text-slate-700 dark:text-slate-200">{area.flight_count}</div>
          <div className="text-[9px] text-slate-400">flights</div>
        </div>
        <div className="text-center p-1.5 bg-white dark:bg-slate-800 rounded border border-slate-100 dark:border-slate-600">
          <div className="text-lg font-bold text-slate-700 dark:text-slate-200">{area.capacity}</div>
          <div className="text-[9px] text-slate-400">capacity</div>
        </div>
        <div className="text-center p-1.5 bg-white dark:bg-slate-800 rounded border border-slate-100 dark:border-slate-600">
          <div className={`text-lg font-bold ${utilization >= 90 ? 'text-red-600' : utilization >= 75 ? 'text-orange-600' : utilization >= 50 ? 'text-yellow-600' : 'text-green-600'}`}>
            {utilization}%
          </div>
          <div className="text-[9px] text-slate-400">utilization</div>
        </div>
      </div>

      {/* Utilization bar */}
      <div className="mb-2">
        <div className="w-full h-2 bg-slate-200 dark:bg-slate-600 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              utilization >= 90 ? 'bg-red-500' : utilization >= 75 ? 'bg-orange-500' : utilization >= 50 ? 'bg-yellow-500' : 'bg-green-500'
            }`}
            style={{ width: `${Math.min(utilization, 100)}%` }}
          />
        </div>
      </div>

      {area.wait_minutes > 0 && (
        <div className="text-slate-500 dark:text-slate-400 mb-2">
          Est. wait: ~{area.wait_minutes} min
        </div>
      )}

      {/* Explanation */}
      <div className="mt-2 pt-2 border-t border-slate-200 dark:border-slate-600">
        <div className="text-[10px] font-medium text-slate-500 dark:text-slate-400 mb-1">How is this calculated?</div>
        <div className="text-[10px] text-slate-400 dark:text-slate-500 leading-relaxed">
          Congestion = flights / area capacity. Thresholds: <span className="text-green-600">Low &lt;50%</span>,{' '}
          <span className="text-yellow-600">Moderate 50-75%</span>,{' '}
          <span className="text-orange-600">High 75-90%</span>,{' '}
          <span className="text-red-600">Critical &gt;90%</span>.
          Capacity is scaled by time-of-day traffic patterns.
        </div>
      </div>
    </div>
  );
}

export default function GateStatus() {
  const { getGates } = useAirportConfigContext();
  const osmGates = getGates();
  const { flights, setSelectedFlight } = useFlightContext();
  const [selectedTerminal, setSelectedTerminal] = useState<string | null>(null);
  const [selectedGateId, setSelectedGateId] = useState<string | null>(null);

  const gateFlightMap = useMemo(() => buildGateFlightMap(flights), [flights]);
  const gates = useMemo(() => buildGates(osmGates, gateFlightMap), [osmGates, gateFlightMap]);
  const terminalGroups = useMemo(() => groupByTerminal(gates), [gates]);
  const terminalNames = useMemo(
    () => Array.from(terminalGroups.keys()).sort((a, b) => naturalSort(a, b)),
    [terminalGroups]
  );

  const { congestion, isLoading: isCongestionLoading } = useCongestion();
  const { activeLevel, setActiveLevel, selectedArea, setSelectedArea } = useCongestionFilter();

  const occupiedCount = gates.filter((g) => g.status !== 'VACANT').length;
  const availableCount = gates.length - occupiedCount;

  const selectedGate = selectedGateId ? gates.find((g) => g.id === selectedGateId) ?? null : null;

  function handleGateClick(gate: Gate) {
    const toggling = selectedGateId === gate.id;
    setSelectedGateId(toggling ? null : gate.id);
    // Select/deselect the flight on the map (shows trajectory if enabled)
    if (gate.flight) {
      setSelectedFlight(toggling ? null : gate.flight);
    }
  }

  function handleSelectFlight(flight: Flight) {
    setSelectedFlight(flight);
  }

  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg shadow-sm border border-slate-200 dark:border-slate-700 p-3">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-semibold text-slate-700 dark:text-slate-200 text-sm">Gate Status</h3>
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
              : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600'
            }`}
          onClick={() => { setSelectedTerminal(null); setSelectedGateId(null); }}
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
                  : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600'
                }`}
              onClick={() => { setSelectedTerminal(name); setSelectedGateId(null); }}
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
            const occ = tGates.filter((g) => g.status !== 'VACANT').length;
            const avail = tGates.length - occ;
            const termCong = getTerminalCongestion(name, congestion);
            const matchesFilter = activeLevel && termCong?.level === activeLevel;
            const dimmedByFilter = activeLevel && !matchesFilter;
            return (
              <button
                key={name}
                className={`w-full flex items-center justify-between px-2 py-1.5 rounded transition-all text-left
                  ${matchesFilter
                    ? 'bg-blue-50 dark:bg-blue-900/30 ring-1 ring-blue-400'
                    : dimmedByFilter
                      ? 'opacity-30'
                      : 'hover:bg-slate-50 dark:hover:bg-slate-700'
                  }`}
                onClick={() => setSelectedTerminal(name)}
              >
                <div className="flex items-center">
                  <span className={`text-xs font-medium ${matchesFilter ? 'text-blue-700 dark:text-blue-300' : 'text-slate-700 dark:text-slate-300'}`}>{name}</span>
                  {!isCongestionLoading && (
                    <CongestionIndicator congestion={termCong} onClick={termCong ? (a) => setSelectedArea(selectedArea?.area_id === a.area_id ? null : a) : undefined} />
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
              <span className="text-xs font-medium text-slate-700 dark:text-slate-300">{selectedTerminal}</span>
              {!isCongestionLoading && (
                <CongestionIndicator
                  congestion={getTerminalCongestion(selectedTerminal, congestion)}
                  onClick={(a) => setSelectedArea(selectedArea?.area_id === a.area_id ? null : a)}
                />
              )}
            </div>
            <span className="text-[11px] text-slate-400">
              {(terminalGroups.get(selectedTerminal) || []).length} gates
            </span>
          </div>
          <div className="grid grid-cols-6 md:grid-cols-8 gap-1">
            {(terminalGroups.get(selectedTerminal) || []).map((gate) => {
              const colors = gateStatusColors[gate.status];
              const isSelected = selectedGateId === gate.id;
              return (
                <button
                  key={gate.id}
                  className={`
                    aspect-square flex items-center justify-center
                    text-[10px] font-medium rounded cursor-pointer
                    transition-colors duration-150
                    ${colors.bg} ${colors.text} ${colors.hover}
                    ${isSelected ? 'ring-2 ring-blue-500 ring-offset-1' : ''}
                  `}
                  title={`${gate.ref}: ${gate.status}${gate.flight ? ` — ${gate.flight.callsign || gate.flight.icao24}` : ''}`}
                  onClick={() => handleGateClick(gate)}
                >
                  {gate.ref}
                </button>
              );
            })}
          </div>

          {/* Gate detail card */}
          {selectedGate && selectedGate.terminal === selectedTerminal && (
            <GateDetailCard
              gate={selectedGate}
              onSelectFlight={handleSelectFlight}
              onClose={() => setSelectedGateId(null)}
            />
          )}
        </div>
      )}

      {/* Gate color legend */}
      <div className="mt-2 pt-2 border-t border-slate-100 dark:border-slate-700">
        <div className="text-[10px] font-medium text-slate-500 dark:text-slate-400 mb-1">Stand</div>
        <div className="flex flex-wrap gap-1.5">
          <span className="flex items-center gap-1 text-[10px]">
            <span className="w-2 h-2 rounded bg-red-400" />
            <span className="text-slate-500 dark:text-slate-400">On Stand</span>
          </span>
          <span className="flex items-center gap-1 text-[10px]">
            <span className="w-2 h-2 rounded bg-amber-400" />
            <span className="text-slate-500 dark:text-slate-400">Taxi In / Inbound</span>
          </span>
          <span className="flex items-center gap-1 text-[10px]">
            <span className="w-2 h-2 rounded bg-green-400" />
            <span className="text-slate-500 dark:text-slate-400">Vacant</span>
          </span>
        </div>
      </div>

      {/* Congestion Filter */}
      <div className="mt-2 pt-2 border-t border-slate-100 dark:border-slate-700">
        <div className="text-[10px] font-medium text-slate-500 dark:text-slate-400 mb-1">Area Congestion</div>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(congestionColors).map(([level, colors]) => {
            const isActive = activeLevel === level;
            return (
              <button
                key={level}
                onClick={() => setActiveLevel(isActive ? null : level)}
                className={`px-1.5 py-0.5 rounded text-[10px] border transition-all cursor-pointer
                  ${colors.bg} ${colors.text} ${colors.border}
                  ${isActive ? 'ring-2 ring-offset-1 ring-blue-500 font-bold scale-110' : 'opacity-80 hover:opacity-100'}
                `}
                title={isActive ? 'Click to clear filter' : `Filter by ${level} congestion`}
              >
                {level.charAt(0).toUpperCase() + level.slice(1)}
              </button>
            );
          })}
          {activeLevel && (
            <button
              onClick={() => setActiveLevel(null)}
              className="px-1.5 py-0.5 rounded text-[10px] border border-slate-300 dark:border-slate-600 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              title="Clear congestion filter"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Congestion detail card (shown when area selected on map) */}
      {selectedArea && (
        <CongestionDetailCard
          area={selectedArea}
          onClose={() => setSelectedArea(null)}
        />
      )}
    </div>
  );
}
