import { useState, useCallback } from 'react';

interface SceneCaptureProps {
  viewMode?: '2d' | '3d';
  airport: string | null;
  simTime: string | null;
}

/** Auto-detect view mode from DOM if not provided. */
function detectViewMode(): '2d' | '3d' {
  // R3F canvases have data-engine attribute
  const r3fCanvas = document.querySelector('canvas[data-engine]');
  if (r3fCanvas && (r3fCanvas as HTMLElement).offsetParent !== null) {
    return '3d';
  }
  return '2d';
}

/** Download a data URL as a file. */
function downloadDataUrl(dataUrl: string, filename: string) {
  const a = document.createElement('a');
  a.href = dataUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

/** Format sim time for filename: "2026-03-15T14:30:00" -> "20260315_1430" */
function formatTimeForFilename(iso: string | null): string {
  if (!iso) return 'unknown';
  try {
    const d = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}`;
  } catch {
    return 'unknown';
  }
}

/** Add a timestamp watermark to a canvas. */
function addWatermark(canvas: HTMLCanvasElement, simTime: string | null, airport: string | null): HTMLCanvasElement {
  const out = document.createElement('canvas');
  out.width = canvas.width;
  out.height = canvas.height;
  const ctx = out.getContext('2d');
  if (!ctx) return canvas;

  ctx.drawImage(canvas, 0, 0);

  // Watermark in bottom-left
  const text = `${airport || 'SIM'} | ${simTime ? new Date(simTime).toLocaleString() : '--'}`;
  ctx.font = `bold ${Math.max(14, Math.round(canvas.height / 50))}px monospace`;
  ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
  const metrics = ctx.measureText(text);
  const padding = 8;
  const x = padding;
  const y = canvas.height - padding;
  ctx.fillRect(
    x - padding / 2,
    y - parseInt(ctx.font) - padding / 2,
    metrics.width + padding,
    parseInt(ctx.font) + padding,
  );
  ctx.fillStyle = '#ffffff';
  ctx.fillText(text, x, y - padding / 2);

  return out;
}

/** Capture the 3D scene (WebGL canvas with preserveDrawingBuffer). */
function capture3D(simTime: string | null, airport: string | null): string | null {
  // Find the R3F canvas inside the 3D container
  const canvas = document.querySelector('canvas[data-engine]') as HTMLCanvasElement
    ?? document.querySelector('.react-three-fiber canvas') as HTMLCanvasElement
    ?? document.querySelector('canvas') as HTMLCanvasElement;

  if (!canvas) return null;

  const watermarked = addWatermark(canvas, simTime, airport);
  return watermarked.toDataURL('image/png');
}

/** Capture the 2D map by compositing Leaflet tile canvases and SVG overlays. */
async function capture2D(simTime: string | null, airport: string | null): Promise<string | null> {
  const mapContainer = document.querySelector('.leaflet-container') as HTMLElement;
  if (!mapContainer) return null;

  const rect = mapContainer.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = rect.width * dpr;
  const h = rect.height * dpr;

  const out = document.createElement('canvas');
  out.width = w;
  out.height = h;
  const ctx = out.getContext('2d');
  if (!ctx) return null;
  ctx.scale(dpr, dpr);

  // 1. Draw tile layer canvases (background map)
  const tileCanvases = mapContainer.querySelectorAll('.leaflet-tile-pane canvas');
  if (tileCanvases.length > 0) {
    for (const tc of tileCanvases) {
      const canvas = tc as HTMLCanvasElement;
      const tileRect = canvas.getBoundingClientRect();
      const x = tileRect.left - rect.left;
      const y = tileRect.top - rect.top;
      try {
        ctx.drawImage(canvas, x, y, tileRect.width, tileRect.height);
      } catch {
        // CORS-tainted tile, skip
      }
    }
  } else {
    // Fallback: fill with dark background if no tile canvases
    ctx.fillStyle = '#1e293b';
    ctx.fillRect(0, 0, rect.width, rect.height);
  }

  // 2. Draw SVG overlays (flight markers, paths, etc.)
  const svgs = mapContainer.querySelectorAll('.leaflet-overlay-pane svg, .leaflet-marker-pane svg');
  for (const svg of svgs) {
    const svgEl = svg as SVGSVGElement;
    const svgRect = svgEl.getBoundingClientRect();
    try {
      const svgData = new XMLSerializer().serializeToString(svgEl);
      const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(svgBlob);
      const img = new Image();
      await new Promise<void>((resolve, reject) => {
        img.onload = () => resolve();
        img.onerror = () => reject();
        img.src = url;
      });
      const x = svgRect.left - rect.left;
      const y = svgRect.top - rect.top;
      ctx.drawImage(img, x, y, svgRect.width, svgRect.height);
      URL.revokeObjectURL(url);
    } catch {
      // SVG serialization failed, skip
    }
  }

  const watermarked = addWatermark(out, simTime, airport);
  return watermarked.toDataURL('image/png');
}

export function SceneCapture({ viewMode, airport, simTime }: SceneCaptureProps) {
  const [capturing, setCapturing] = useState(false);
  const [showToast, setShowToast] = useState(false);

  const handleCapture = useCallback(async () => {
    setCapturing(true);
    try {
      let dataUrl: string | null = null;
      const mode = viewMode ?? detectViewMode();

      if (mode === '3d') {
        dataUrl = capture3D(simTime, airport);
      } else {
        dataUrl = await capture2D(simTime, airport);
      }

      if (dataUrl) {
        const filename = `sim_capture_${airport || 'unknown'}_${formatTimeForFilename(simTime)}.png`;
        downloadDataUrl(dataUrl, filename);
        setShowToast(true);
        setTimeout(() => setShowToast(false), 2000);
      }
    } catch (err) {
      console.error('Scene capture failed:', err);
    } finally {
      setCapturing(false);
    }
  }, [viewMode, airport, simTime]);

  return (
    <>
      <button
        onClick={handleCapture}
        disabled={capturing}
        className="px-2 py-1 rounded text-xs font-medium bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors disabled:opacity-50 flex items-center gap-1"
        title="Capture current view as PNG"
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
          <circle cx="12" cy="13" r="3" stroke="currentColor" strokeWidth={2} fill="none" />
        </svg>
        {capturing ? '...' : ''}
      </button>

      {/* Toast notification */}
      {showToast && (
        <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-[3000] bg-green-600 text-white px-4 py-2 rounded-lg shadow-lg text-sm font-medium animate-fade-in">
          Captured!
        </div>
      )}
    </>
  );
}
