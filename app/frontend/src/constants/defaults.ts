/**
 * Application-wide fallback defaults.
 *
 * These values are used only when no airport config has been loaded yet.
 * Once OSM data arrives, the dynamic airport center takes over.
 */

/** Fallback latitude when no airport config is loaded (0 = equator) */
export const DEFAULT_CENTER_LAT = 0;

/** Fallback longitude when no airport config is loaded (0 = prime meridian) */
export const DEFAULT_CENTER_LON = 0;

/** Default Leaflet zoom level */
export const DEFAULT_ZOOM = 14;
