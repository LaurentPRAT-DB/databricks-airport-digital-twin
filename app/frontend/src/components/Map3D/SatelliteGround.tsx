/**
 * SatelliteGround — Renders satellite imagery as the 3D ground plane.
 *
 * Fetches Esri World Imagery tiles at the appropriate zoom level and
 * composites them onto a single canvas texture mapped to the ground mesh.
 * Replaces the flat green ground plane with real-world satellite imagery.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';

const TILE_SIZE = 256;
const SAT_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';

/** Convert lat/lon to tile x,y at a given zoom level */
function latLonToTile(lat: number, lon: number, zoom: number): { x: number; y: number } {
  const n = Math.pow(2, zoom);
  const x = Math.floor(((lon + 180) / 360) * n);
  const latRad = (lat * Math.PI) / 180;
  const y = Math.floor((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n);
  return { x, y };
}

/** Convert tile x,y to the NW corner lat/lon */
function tileToLatLon(x: number, y: number, zoom: number): { lat: number; lon: number } {
  const n = Math.pow(2, zoom);
  const lon = (x / n) * 360 - 180;
  const latRad = Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n)));
  const lat = (latRad * 180) / Math.PI;
  return { lat, lon };
}

export interface TileLoadingProgress {
  loaded: number;
  total: number;
  inpainting: boolean;
}

interface SatelliteGroundProps {
  size: number;
  centerLat: number;
  centerLon: number;
  /** Coordinate scale used by latLonTo3D (default 10000) */
  scale?: number;
  /** Route tiles through the inpainting proxy to remove real aircraft */
  inpainting?: boolean;
  /** Airport ICAO code for cache tagging when inpainting is enabled */
  airportIcao?: string;
  /** Called with loading progress when tiles are being fetched */
  onLoadingProgress?: (progress: TileLoadingProgress | null) => void;
}

export function SatelliteGround({
  size,
  centerLat,
  centerLon,
  scale = 10000,
  inpainting = false,
  airportIcao,
  onLoadingProgress,
}: SatelliteGroundProps) {
  const [texture, setTexture] = useState<THREE.CanvasTexture | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Determine tile coverage: the ground plane spans `size` scene units.
  // In lat/lon terms: deltaLat = size / scale, deltaLon = size / (scale * cos(lat))
  const tileConfig = useMemo(() => {
    const deltaLat = size / scale;
    const deltaLon = size / (scale * Math.cos((centerLat * Math.PI) / 180));

    // Choose zoom so we get ~4-6 tiles across for good resolution without too many fetches.
    // At zoom z, one tile covers 360/2^z degrees of longitude.
    // We want: tileCount ≈ deltaLon / (360 / 2^z) ≈ 5
    // So: 2^z ≈ 5 * 360 / deltaLon → z ≈ log2(1800 / deltaLon)
    const targetTiles = 5;
    const rawZoom = Math.log2((targetTiles * 360) / deltaLon);
    const zoom = Math.max(12, Math.min(17, Math.round(rawZoom)));

    // Tile grid bounds
    const nwLat = centerLat + deltaLat / 2;
    const nwLon = centerLon - deltaLon / 2;
    const seLat = centerLat - deltaLat / 2;
    const seLon = centerLon + deltaLon / 2;

    const nwTile = latLonToTile(nwLat, nwLon, zoom);
    const seTile = latLonToTile(seLat, seLon, zoom);

    const minTX = nwTile.x;
    const maxTX = seTile.x;
    const minTY = nwTile.y;
    const maxTY = seTile.y;

    const cols = maxTX - minTX + 1;
    const rows = maxTY - minTY + 1;

    // Geo bounds of the full tile grid
    const gridNW = tileToLatLon(minTX, minTY, zoom);
    const gridSE = tileToLatLon(maxTX + 1, maxTY + 1, zoom);

    return { zoom, minTX, maxTX, minTY, maxTY, cols, rows, gridNW, gridSE, deltaLat, deltaLon };
  }, [size, scale, centerLat, centerLon]);

  /** Load a tile image — via inpainting proxy or direct Esri URL. */
  const loadTileImage = (
    esriUrl: string,
    useInpainting: boolean,
    icao: string | undefined,
  ): Promise<HTMLImageElement> => {
    return new Promise((resolve) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';

      const loadDirect = () => {
        const directImg = new Image();
        directImg.crossOrigin = 'anonymous';
        directImg.onload = () => resolve(directImg);
        directImg.onerror = () => resolve(directImg); // still resolve — caller handles missing tiles
        directImg.src = esriUrl;
      };

      if (useInpainting) {
        const params = new URLSearchParams({ url: esriUrl });
        if (icao) params.set('airport_icao', icao);

        fetch(`/api/inpainting/clean-tile?${params.toString()}`, { method: 'POST' })
          .then((resp) => {
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            return resp.blob();
          })
          .then((blob) => {
            const objectUrl = URL.createObjectURL(blob);
            img.onload = () => {
              URL.revokeObjectURL(objectUrl);
              resolve(img);
            };
            img.onerror = () => {
              URL.revokeObjectURL(objectUrl);
              loadDirect(); // Fallback to raw Esri tile
            };
            img.src = objectUrl;
          })
          .catch(() => {
            loadDirect(); // Fallback to raw Esri tile
          });
      } else {
        img.onload = () => resolve(img);
        img.onerror = () => resolve(img);
        img.src = esriUrl;
      }
    });
  };

  // Fetch tiles and composite onto canvas
  useEffect(() => {
    const { zoom, minTX, maxTX, minTY, maxTY, cols, rows, gridNW, gridSE, deltaLat, deltaLon } = tileConfig;

    const canvasWidth = cols * TILE_SIZE;
    const canvasHeight = rows * TILE_SIZE;

    const canvas = document.createElement('canvas');
    canvas.width = canvasWidth;
    canvas.height = canvasHeight;
    canvasRef.current = canvas;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Fill with dark gray while loading
    ctx.fillStyle = '#333333';
    ctx.fillRect(0, 0, canvasWidth, canvasHeight);

    let cancelled = false;
    let loadedCount = 0;
    const totalTiles = cols * rows;

    // Signal loading start
    onLoadingProgress?.({ loaded: 0, total: totalTiles, inpainting });

    const finalize = () => {
      if (cancelled) return;
      // All tiles loaded — crop to the exact ground plane extent
      const groundNWLat = centerLat + deltaLat / 2;
      const groundNWLon = centerLon - deltaLon / 2;
      const groundSELat = centerLat - deltaLat / 2;
      const groundSELon = centerLon + deltaLon / 2;

      const gridLatSpan = gridNW.lat - gridSE.lat;
      const gridLonSpan = gridSE.lon - gridNW.lon;

      const cropX = ((groundNWLon - gridNW.lon) / gridLonSpan) * canvasWidth;
      const cropY = ((gridNW.lat - groundNWLat) / gridLatSpan) * canvasHeight;
      const cropW = ((groundSELon - groundNWLon) / gridLonSpan) * canvasWidth;
      const cropH = ((groundNWLat - groundSELat) / gridLatSpan) * canvasHeight;

      const croppedCanvas = document.createElement('canvas');
      croppedCanvas.width = 2048;
      croppedCanvas.height = 2048;
      const cropCtx = croppedCanvas.getContext('2d');
      if (cropCtx) {
        cropCtx.drawImage(canvas, cropX, cropY, cropW, cropH, 0, 0, 2048, 2048);
        cropCtx.fillStyle = 'rgba(0, 0, 0, 0.3)';
        cropCtx.fillRect(0, 0, 2048, 2048);
        const tex = new THREE.CanvasTexture(croppedCanvas);
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.minFilter = THREE.LinearMipmapLinearFilter;
        tex.magFilter = THREE.LinearFilter;
        tex.anisotropy = 4;
        setTexture(tex);
      }
    };

    for (let ty = minTY; ty <= maxTY; ty++) {
      for (let tx = minTX; tx <= maxTX; tx++) {
        const esriUrl = SAT_URL.replace('{z}', String(zoom))
          .replace('{y}', String(ty))
          .replace('{x}', String(tx));

        const px = (tx - minTX) * TILE_SIZE;
        const py = (ty - minTY) * TILE_SIZE;

        loadTileImage(esriUrl, inpainting, airportIcao).then((img) => {
          if (cancelled) return;
          ctx.drawImage(img, px, py, TILE_SIZE, TILE_SIZE);
          loadedCount++;
          onLoadingProgress?.({ loaded: loadedCount, total: totalTiles, inpainting });
          if (loadedCount === totalTiles) {
            onLoadingProgress?.(null); // done
            finalize();
          }
        });
      }
    }

    return () => {
      cancelled = true;
      onLoadingProgress?.(null);
      setTexture((prev) => {
        prev?.dispose();
        return null;
      });
    };
  }, [tileConfig, centerLat, centerLon, inpainting, airportIcao]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.1, 0]} receiveShadow>
      <planeGeometry args={[size, size]} />
      {texture ? (
        <meshBasicMaterial
          map={texture}
          side={THREE.DoubleSide}
          toneMapped={false}
        />
      ) : (
        // Fallback while loading: dark gray
        <meshBasicMaterial color={0x333333} side={THREE.DoubleSide} />
      )}
    </mesh>
  );
}
