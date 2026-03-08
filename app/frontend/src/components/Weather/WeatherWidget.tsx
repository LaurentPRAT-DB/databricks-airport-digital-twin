import { useState, useEffect } from 'react';

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

export default function WeatherWidget() {
  const [weather, setWeather] = useState<WeatherData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    async function fetchWeather() {
      try {
        const response = await fetch('/api/weather/current');
        if (!response.ok) throw new Error('Failed to fetch weather');
        const data = await response.json();
        setWeather(data);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    }

    fetchWeather();
    // Refresh every 5 minutes
    const interval = setInterval(fetchWeather, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center gap-2 bg-slate-700 px-3 py-1 rounded-full text-sm animate-pulse">
        <span className="text-slate-400">Loading weather...</span>
      </div>
    );
  }

  if (error || !weather) {
    return (
      <div className="flex items-center gap-2 bg-red-900 px-3 py-1 rounded-full text-sm">
        <span className="text-red-300">Weather unavailable</span>
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
        className="flex items-center gap-2 bg-slate-700 hover:bg-slate-600 px-3 py-1 rounded-full text-sm transition-colors"
      >
        {/* Flight category indicator */}
        <span className={`w-2.5 h-2.5 rounded-full ${categoryColor}`} />

        {/* Temperature */}
        <span className="font-mono">{metar.temperature_c}°C</span>

        {/* Wind */}
        <span className="text-slate-300">{windStr}</span>

        {/* Visibility */}
        <span className="text-slate-400">{metar.visibility_sm}SM</span>
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
          </div>
        </div>
      )}
    </div>
  );
}
