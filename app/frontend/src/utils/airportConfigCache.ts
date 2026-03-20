/**
 * IndexedDB cache for airport configuration data.
 *
 * Provides a persistent L2 cache (behind the in-memory Map) so that
 * revisiting an airport avoids the ~16s OSM fetch on every page load.
 */

const DB_NAME = 'airport-digital-twin';
const STORE_NAME = 'airport-configs';
const DB_VERSION = 1;
const CACHE_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours

interface CacheEntry {
  icaoCode: string;
  config: unknown;
  timestamp: number;
}

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'icaoCode' });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function getCachedConfig(icaoCode: string): Promise<unknown | null> {
  try {
    const db = await openDB();
    return new Promise((resolve) => {
      const tx = db.transaction(STORE_NAME, 'readonly');
      const store = tx.objectStore(STORE_NAME);
      const req = store.get(icaoCode);
      req.onsuccess = () => {
        const entry = req.result as CacheEntry | undefined;
        if (entry && Date.now() - entry.timestamp < CACHE_TTL_MS) {
          resolve(entry.config);
        } else {
          resolve(null);
        }
      };
      req.onerror = () => resolve(null);
    });
  } catch {
    return null;
  }
}

export async function setCachedConfig(icaoCode: string, config: unknown): Promise<void> {
  try {
    const db = await openDB();
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    const entry: CacheEntry = { icaoCode, config, timestamp: Date.now() };
    store.put(entry);
    await new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    // Silently fail — cache is best-effort
  }
}

export async function clearConfigCache(): Promise<void> {
  try {
    const db = await openDB();
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    store.clear();
    await new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    // Silently fail
  }
}
