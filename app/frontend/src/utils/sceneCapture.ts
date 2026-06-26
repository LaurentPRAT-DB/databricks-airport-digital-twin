/**
 * Scene capture utilities for 2D (MapLibre) and 3D (Three.js) views.
 * Shared between the SceneCapture button and SimulationReport generator.
 */

/** Auto-detect view mode from DOM. */
export function detectViewMode(): '2d' | '3d' {
  const r3fCanvas = document.querySelector('canvas[data-engine]');
  if (r3fCanvas && (r3fCanvas as HTMLElement).offsetParent !== null) {
    return '3d';
  }
  return '2d';
}

/** Download a data URL as a file. */
export function downloadDataUrl(dataUrl: string, filename: string) {
  const a = document.createElement('a');
  a.href = dataUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

/** Format sim time for filename: "2026-03-15T14:30:00" -> "20260315_1430" */
export function formatTimeForFilename(iso: string | null): string {
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
export function addWatermark(canvas: HTMLCanvasElement, simTime: string | null, airport: string | null): HTMLCanvasElement {
  const out = document.createElement('canvas');
  out.width = canvas.width;
  out.height = canvas.height;
  const ctx = out.getContext('2d');
  if (!ctx) return canvas;

  ctx.drawImage(canvas, 0, 0);

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
export function capture3D(simTime: string | null, airport: string | null): string | null {
  const canvas = document.querySelector('canvas[data-engine]') as HTMLCanvasElement
    ?? document.querySelector('.react-three-fiber canvas') as HTMLCanvasElement
    ?? document.querySelector('canvas') as HTMLCanvasElement;

  if (!canvas) return null;

  const watermarked = addWatermark(canvas, simTime, airport);
  return watermarked.toDataURL('image/png');
}

/** Capture the 2D map via MapLibre's WebGL canvas. */
export async function capture2D(simTime: string | null, airport: string | null): Promise<string | null> {
  // MapLibre renders everything (tiles, overlays, markers) on a single WebGL canvas
  const mapCanvas = document.querySelector('.maplibregl-canvas') as HTMLCanvasElement
    ?? document.querySelector('.mapboxgl-canvas') as HTMLCanvasElement;

  if (mapCanvas) {
    const watermarked = addWatermark(mapCanvas, simTime, airport);
    try {
      return watermarked.toDataURL('image/png');
    } catch {
      // Canvas may be tainted if preserveDrawingBuffer is false
    }
  }

  // Fallback: try to find any map container and use html2canvas-style approach
  const mapContainer = document.querySelector('.maplibregl-map') as HTMLElement
    ?? document.querySelector('[class*="map"]') as HTMLElement;
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

  // Try drawing the map canvas
  const canvas = mapContainer.querySelector('canvas');
  if (canvas) {
    try {
      ctx.drawImage(canvas, 0, 0, rect.width, rect.height);
    } catch {
      ctx.fillStyle = '#aad3df';
      ctx.fillRect(0, 0, rect.width, rect.height);
    }
  } else {
    ctx.fillStyle = '#aad3df';
    ctx.fillRect(0, 0, rect.width, rect.height);
  }

  // Draw HTML marker overlays (flight markers are div elements above the canvas)
  const markerContainer = mapContainer.querySelector('.maplibregl-marker');
  if (markerContainer) {
    const markers = mapContainer.querySelectorAll('.maplibregl-marker');
    for (const marker of markers) {
      const markerEl = marker as HTMLElement;
      const markerRect = markerEl.getBoundingClientRect();
      const mx = markerRect.left - rect.left;
      const my = markerRect.top - rect.top;

      const innerSvg = markerEl.querySelector('svg');
      if (innerSvg) {
        try {
          const clone = innerSvg.cloneNode(true) as SVGSVGElement;
          clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
          clone.setAttribute('width', String(markerRect.width));
          clone.setAttribute('height', String(markerRect.height));
          const svgData = new XMLSerializer().serializeToString(clone);
          const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
          const url = URL.createObjectURL(svgBlob);
          const img = new Image();
          await new Promise<void>((resolve, reject) => {
            img.onload = () => resolve();
            img.onerror = () => reject();
            img.src = url;
          });
          ctx.drawImage(img, mx, my, markerRect.width, markerRect.height);
          URL.revokeObjectURL(url);
        } catch { /* skip */ }
      }
    }
  }

  const watermarked = addWatermark(out, simTime, airport);
  try {
    return watermarked.toDataURL('image/png');
  } catch {
    return null;
  }
}

/** Capture current view (auto-detects 2D vs 3D). */
export async function captureCurrentView(
  simTime: string | null,
  airport: string | null,
  viewMode?: '2d' | '3d',
): Promise<string | null> {
  const mode = viewMode ?? detectViewMode();
  if (mode === '3d') {
    return capture3D(simTime, airport);
  }
  return capture2D(simTime, airport);
}
