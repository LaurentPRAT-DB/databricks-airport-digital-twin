/**
 * Scene capture utilities for 2D (Leaflet) and 3D (Three.js) views.
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

/** Load an image with CORS and return it, or null on failure. */
function loadImage(src: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

/** Capture the 2D map by compositing Leaflet tile images and overlays. */
export async function capture2D(simTime: string | null, airport: string | null): Promise<string | null> {
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

  // 1. Draw tile images (Leaflet uses <img> elements, not <canvas>)
  const tileImages = mapContainer.querySelectorAll('.leaflet-tile-pane img.leaflet-tile');
  let tilesDrawn = 0;
  if (tileImages.length > 0) {
    // Load tiles with CORS to avoid tainted canvas
    const tilePromises = Array.from(tileImages).map(async (tile) => {
      const tileEl = tile as HTMLImageElement;
      const tileRect = tileEl.getBoundingClientRect();
      // Skip tiles outside viewport
      if (tileRect.right < rect.left || tileRect.left > rect.right ||
          tileRect.bottom < rect.top || tileRect.top > rect.bottom) return;
      try {
        // Try drawing directly first (same-origin or CORS-allowed tiles)
        const tx = tileRect.left - rect.left;
        const ty = tileRect.top - rect.top;
        ctx.drawImage(tileEl, tx, ty, tileRect.width, tileRect.height);
        tilesDrawn++;
      } catch {
        // CORS-tainted: reload with crossOrigin attribute
        const img = await loadImage(tileEl.src);
        if (img) {
          const tx = tileRect.left - rect.left;
          const ty = tileRect.top - rect.top;
          try {
            ctx.drawImage(img, tx, ty, tileRect.width, tileRect.height);
            tilesDrawn++;
          } catch { /* skip this tile */ }
        }
      }
    });
    await Promise.all(tilePromises);
  }

  // Fallback: also try canvas tiles (some tile layers use canvas renderer)
  if (tilesDrawn === 0) {
    const tileCanvases = mapContainer.querySelectorAll('.leaflet-tile-pane canvas');
    if (tileCanvases.length > 0) {
      for (const tc of tileCanvases) {
        const tileCanvas = tc as HTMLCanvasElement;
        const tileRect = tileCanvas.getBoundingClientRect();
        const tx = tileRect.left - rect.left;
        const ty = tileRect.top - rect.top;
        try {
          ctx.drawImage(tileCanvas, tx, ty, tileRect.width, tileRect.height);
          tilesDrawn++;
        } catch { /* CORS-tainted tile, skip */ }
      }
    }
  }

  // Last resort: fill with map background color
  if (tilesDrawn === 0) {
    ctx.fillStyle = '#aad3df'; // OSM water color
    ctx.fillRect(0, 0, rect.width, rect.height);
  }

  // 2. Draw SVG overlays (polylines, polygons, circles)
  const svgs = mapContainer.querySelectorAll('.leaflet-overlay-pane svg');
  for (const svg of svgs) {
    const svgEl = svg as SVGSVGElement;
    const svgRect = svgEl.getBoundingClientRect();
    try {
      const clone = svgEl.cloneNode(true) as SVGSVGElement;
      // Ensure the SVG has explicit dimensions for rendering
      clone.setAttribute('width', String(svgRect.width));
      clone.setAttribute('height', String(svgRect.height));
      const svgData = new XMLSerializer().serializeToString(clone);
      const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(svgBlob);
      const img = new Image();
      await new Promise<void>((resolve, reject) => {
        img.onload = () => resolve();
        img.onerror = () => reject();
        img.src = url;
      });
      const sx = svgRect.left - rect.left;
      const sy = svgRect.top - rect.top;
      ctx.drawImage(img, sx, sy, svgRect.width, svgRect.height);
      URL.revokeObjectURL(url);
    } catch {
      // SVG serialization failed, skip
    }
  }

  // 3. Draw marker pane elements (divIcon markers with aircraft icons)
  const markerPane = mapContainer.querySelector('.leaflet-marker-pane');
  if (markerPane) {
    const markers = markerPane.querySelectorAll('.leaflet-marker-icon');
    for (const marker of markers) {
      const markerEl = marker as HTMLElement;
      const markerRect = markerEl.getBoundingClientRect();
      const mx = markerRect.left - rect.left;
      const my = markerRect.top - rect.top;

      // Try to find an SVG inside the marker div (aircraft icons)
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
          const img = await loadImage(url);
          if (img) {
            ctx.drawImage(img, mx, my, markerRect.width, markerRect.height);
          }
          URL.revokeObjectURL(url);
        } catch { /* skip */ }
      }

      // Try to find an <img> inside the marker
      const innerImg = markerEl.querySelector('img') as HTMLImageElement;
      if (innerImg && !innerSvg) {
        try {
          ctx.drawImage(innerImg, mx, my, markerRect.width, markerRect.height);
        } catch { /* skip */ }
      }
    }
  }

  const watermarked = addWatermark(out, simTime, airport);
  return watermarked.toDataURL('image/png');
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
