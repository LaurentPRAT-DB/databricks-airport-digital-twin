import { useState, useEffect } from 'react';
import { useFlightContext } from '../../context/FlightContext';

interface CloudLayer {
  coverage: string;
  altitude_ft: number;
}

interface METAR {
  station: string;
  wind_direction: number | null;
  wind_speed_kts: number;
  wind_gust_kts: number | null;
  visibility_sm: number;
  clouds: CloudLayer[];
  temperature_c: number;
  dewpoint_c: number;
  flight_category: 'VFR' | 'MVFR' | 'IFR' | 'LIFR';
  raw_metar: string;
}

interface WeatherData {
  metar: METAR;
  station: string;
}

const FLIGHT_CATEGORY_COLORS = {
  VFR: 'bg-green-500',
  MVFR: 'bg-blue-500',
  IFR: 'bg-red-500',
  LIFR: 'bg-purple-500',
};

const FLIGHT_CATEGORY_LABELS = {
  VFR: 'VFR - Clear',
  MVFR: 'MVFR - Marginal',
  IFR: 'IFR - Instrument',
  LIFR: 'LIFR - Low Instrument',
};

const CLOUD_MEANINGS: Record<string, string> = {
  SKC: 'Sky clear', CLR: 'Clear below 12,000 ft',
  FEW: 'Few (1-2 oktas)', SCT: 'Scattered (3-4 oktas)',
  BKN: 'Broken (5-7 oktas)', OVC: 'Overcast (8 oktas)',
};

function parseMetarParts(raw: string): { token: string; meaning: string }[] {
  const parts: { token: string; meaning: string }[] = [];
  const tokens = raw.split(/\s+/);

  for (const t of tokens) {
    // Station
    if (/^[A-Z]{4}$/.test(t)) {
      parts.push({ token: t, meaning: `Station ${t}` });
    // Date/time
    } else if (/^\d{6}Z$/.test(t)) {
      const day = t.slice(0, 2);
      const hh = t.slice(2, 4);
      const mm = t.slice(4, 6);
      parts.push({ token: t, meaning: `Day ${day}, ${hh}:${mm} UTC` });
    // Wind
    } else if (/^\d{3}\d{2,3}(G\d{2,3})?KT$/.test(t)) {
      const dir = t.slice(0, 3);
      const gustMatch = t.match(/(\d{2,3})G(\d{2,3})KT/);
      if (gustMatch) {
        parts.push({ token: t, meaning: `Wind ${dir}° at ${gustMatch[1]} kt, gusting ${gustMatch[2]} kt` });
      } else {
        const spd = t.match(/\d{3}(\d{2,3})KT/)?.[1];
        parts.push({ token: t, meaning: `Wind from ${dir}° at ${spd} knots` });
      }
    } else if (t === 'VRB') {
      parts.push({ token: t, meaning: 'Variable wind direction' });
    // Visibility
    } else if (/^\d+SM$/.test(t)) {
      parts.push({ token: t, meaning: `Visibility ${t.replace('SM', '')} statute miles` });
    // Cloud layers
    } else if (/^(SKC|CLR|FEW|SCT|BKN|OVC)\d{0,3}$/.test(t)) {
      const cov = t.slice(0, 3);
      const alt = t.slice(3);
      const covText = CLOUD_MEANINGS[cov] || cov;
      parts.push({ token: t, meaning: alt ? `${covText} at ${Number(alt) * 100} ft` : covText });
    // Temp/dewpoint
    } else if (/^M?\d{2}\/M?\d{2}$/.test(t)) {
      const [temp, dew] = t.split('/').map(v => v.startsWith('M') ? `-${v.slice(1)}` : v);
      parts.push({ token: t, meaning: `Temp ${temp}°C / Dewpoint ${dew}°C` });
    // Altimeter
    } else if (/^A\d{4}$/.test(t)) {
      const val = `${t.slice(1, 3)}.${t.slice(3)}`;
      parts.push({ token: t, meaning: `Altimeter ${val} inHg` });
    }
  }
  return parts;
}

function MetarLegend({ raw }: { raw: string }) {
  const [show, setShow] = useState(false);
  const parts = show ? parseMetarParts(raw) : [];

  return (
    <div className="pt-2 border-t border-slate-700">
      <button onClick={() => setShow(!show)} className="text-slate-400 text-xs hover:text-slate-300 transition-colors">
        {show ? 'Hide' : 'Explain'} METAR {show ? '▲' : '▼'}
      </button>
      {show && parts.length > 0 && (
        <div className="text-[10px] text-slate-500 leading-relaxed mt-1 space-y-0.5">
          {parts.map(({ token, meaning }) => (
            <div key={token}><span className="text-slate-400 font-mono font-medium">{token}</span> — {meaning}</div>
          ))}
        </div>
      )}
    </div>
  );
}

function DewpointInfo({ temp, dewpoint }: { temp: number; dewpoint: number }) {
  const [show, setShow] = useState(false);
  const spread = temp - dewpoint;

  return (
    <div className="relative">
      <div className="flex items-center gap-1">
        <span className="text-slate-400">Dewpoint</span>
        <button
          onClick={() => setShow(!show)}
          className="w-3.5 h-3.5 rounded-full bg-slate-600 text-[9px] text-slate-300 hover:bg-slate-500 flex items-center justify-center leading-none"
        >?</button>
      </div>
      <div className="font-mono">{dewpoint}°C <span className="text-slate-500 text-xs">({spread}° spread)</span></div>
      {show && (
        <div className="absolute left-0 top-full mt-1 w-56 bg-slate-900 border border-slate-600 rounded p-2 text-[10px] text-slate-400 leading-relaxed z-50 shadow-lg">
          <p className="mb-1">Temperature at which air saturates and condensation forms (dew/fog).</p>
          <ul className="space-y-0.5 list-disc pl-3">
            <li><span className="text-slate-300">Close to temp</span> — moderate humidity, low cloud bases</li>
            <li><span className="text-slate-300">Equal to temp</span> — fog/mist likely (100% humidity)</li>
            <li><span className="text-slate-300">Far below temp</span> — dry air, good visibility</li>
          </ul>
        </div>
      )}
    </div>
  );
}

interface WeatherWidgetProps {
  station?: string;
}

export default function WeatherWidget({ station }: WeatherWidgetProps) {
  const [weather, setWeather] = useState<WeatherData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const { dataMode } = useFlightContext();

  useEffect(() => {
    const controller = new AbortController();

    async function fetchWeather() {
      try {
        const params = new URLSearchParams();
        if (station) params.set('station', station);
        if (dataMode === 'live') params.set('live', 'true');
        const url = `/api/weather/current${params.toString() ? '?' + params.toString() : ''}`;
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) throw new Error('Failed to fetch weather');
        const data = await response.json();
        setWeather(data);
        setError(null);
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }

    fetchWeather();
    const interval = setInterval(fetchWeather, 5 * 60 * 1000);
    return () => {
      controller.abort();
      clearInterval(interval);
    };
  }, [station, dataMode]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 bg-slate-700 px-2 sm:px-3 py-1.5 rounded-lg text-xs sm:text-sm animate-pulse">
        <span className="text-slate-400">Weather...</span>
      </div>
    );
  }

  if (error || !weather) {
    return (
      <div className="flex items-center gap-2 bg-red-900 px-2 sm:px-3 py-1.5 rounded-lg text-xs sm:text-sm">
        <span className="text-red-300">No weather</span>
      </div>
    );
  }

  const { metar } = weather;
  const categoryColor = FLIGHT_CATEGORY_COLORS[metar.flight_category];
  const categoryLabel = FLIGHT_CATEGORY_LABELS[metar.flight_category];

  // Format wind string
  const windStr = metar.wind_gust_kts
    ? `${metar.wind_direction || 'VRB'}@${metar.wind_speed_kts}G${metar.wind_gust_kts}kt`
    : `${metar.wind_direction || 'VRB'}@${metar.wind_speed_kts}kt`;

  return (
    <div className="relative">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 sm:gap-2 bg-slate-700 hover:bg-slate-600 px-2 sm:px-3 py-1.5 rounded-lg text-sm transition-colors"
      >
        {/* Flight category indicator */}
        <span className={`w-2 h-2 sm:w-2.5 sm:h-2.5 rounded-full ${categoryColor}`} />

        {/* Temperature */}
        <span className="font-mono text-xs sm:text-sm">{metar.temperature_c}°C</span>

        {/* Wind — hidden on small screens */}
        <span className="hidden sm:inline text-slate-300">{windStr}</span>

        {/* Visibility — hidden on small screens */}
        <span className="hidden sm:inline text-slate-400">{metar.visibility_sm}SM</span>
      </button>

      {/* Expanded dropdown */}
      {expanded && (
        <div className="absolute top-full right-0 mt-2 w-72 bg-slate-800 rounded-lg shadow-xl border border-slate-700 z-50">
          <div className="p-4 space-y-3">
            {/* Station and category */}
            <div className="flex items-center justify-between">
              <span className="font-bold text-lg">{metar.station}</span>
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${categoryColor} text-white`}>
                {metar.flight_category}
              </span>
            </div>

            <div className="text-xs text-slate-400">{categoryLabel}</div>

            {/* Weather details */}
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div>
                <span className="text-slate-400">Wind</span>
                <div className="font-mono">{windStr}</div>
              </div>
              <div>
                <span className="text-slate-400">Visibility</span>
                <div className="font-mono">{metar.visibility_sm} SM</div>
              </div>
              <div>
                <span className="text-slate-400">Temperature</span>
                <div className="font-mono">{metar.temperature_c}°C</div>
              </div>
              <DewpointInfo temp={metar.temperature_c} dewpoint={metar.dewpoint_c} />
              <div>
                <span className="text-slate-400">Clouds</span>
                <div className="font-mono text-xs">
                  {metar.clouds.length > 0
                    ? metar.clouds.map((c, i) => (
                        <span key={i}>{c.coverage}{Math.round(c.altitude_ft / 100).toString().padStart(3, '0')} </span>
                      ))
                    : 'SKC'}
                </div>
              </div>
            </div>

            {/* Raw METAR */}
            <div className="pt-2 border-t border-slate-700">
              <span className="text-slate-400 text-xs">Raw METAR</span>
              <div className="font-mono text-xs text-slate-300 break-all">
                {metar.raw_metar}
              </div>
            </div>

            {/* METAR legend */}
            <MetarLegend raw={metar.raw_metar} />
          </div>
        </div>
      )}
    </div>
  );
}
