import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { onCLS, onINP, onLCP, onFCP, onTTFB, Metric } from 'web-vitals'
import App from './App'
import './index.css'

/**
 * Suppress known third-party console warnings that are harmless.
 * These warnings come from external libraries and don't affect functionality.
 */
const originalWarn = console.warn;
console.warn = (...args: unknown[]) => {
  const message = args[0];
  if (typeof message === 'string') {
    // THREE.Clock deprecation - internal to @react-three/drei, harmless
    if (message.includes('THREE.Clock') && message.includes('deprecated')) return;
    // GLTF extension warning - model still loads correctly with fallback
    if (message.includes('GLTFLoader') && message.includes('KHR_materials_pbrSpecularGlossiness')) return;
  }
  originalWarn.apply(console, args);
};

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      // Flight polling is managed per-hook (WS primary, HTTP fallback).
      // Other queries (config, baggage, etc.) use their own intervals.
    },
  },
})

// Check if we're in development mode
const isDev = !window.location.hostname.includes('databricksapps.com');

/**
 * Web Vitals Reporting
 *
 * Collects Core Web Vitals metrics for real user monitoring (RUM).
 * These metrics contribute to Chrome User Experience Report (CrUX).
 *
 * Metrics collected:
 * - LCP (Largest Contentful Paint): Loading performance
 * - INP (Interaction to Next Paint): Interactivity
 * - CLS (Cumulative Layout Shift): Visual stability
 * - FCP (First Contentful Paint): First content rendered
 * - TTFB (Time to First Byte): Server response time
 */
function reportWebVitals(metric: Metric) {
  // Log to console in development
  if (isDev) {
    console.log(`[Web Vitals] ${metric.name}: ${metric.value.toFixed(2)}ms (${metric.rating})`);
  }

  // Send to analytics endpoint in production (for poor/needs-improvement metrics)
  if (!isDev && metric.rating !== 'good') {
    // Report poor/needs-improvement metrics to backend
    fetch('/api/metrics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: metric.name,
        value: metric.value,
        rating: metric.rating,
        delta: metric.delta,
        id: metric.id,
        navigationType: metric.navigationType,
        timestamp: Date.now(),
      }),
    }).catch(() => {
      // Silently fail - metrics are non-critical
    });
  }
}

// Initialize Web Vitals collection
onCLS(reportWebVitals);
onINP(reportWebVitals);
onLCP(reportWebVitals);
onFCP(reportWebVitals);
onTTFB(reportWebVitals);

// Service Worker update listener — show toast when new version is available
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.addEventListener('message', (event) => {
    if (event.data?.type === 'SW_UPDATED') {
      showUpdateToast();
    }
  });

  navigator.serviceWorker.addEventListener('controllerchange', () => {
    window.location.reload();
  });
}

function showUpdateToast() {
  if (document.getElementById('sw-update-toast')) return;
  const toast = document.createElement('div');
  toast.id = 'sw-update-toast';
  toast.style.cssText = 'position:fixed;left:50%;transform:translateX(-50%);z-index:9999;background:#1e293b;color:#e2e8f0;padding:12px 20px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.4);display:flex;align-items:center;gap:12px;font-family:system-ui;font-size:14px;border:1px solid #334155;max-width:90vw;bottom:calc(16px + var(--tab-bar-h, 80px))';
  toast.innerHTML = `
    <span>New version available</span>
    <button style="background:#3b82f6;color:white;border:none;padding:6px 14px;border-radius:6px;font-size:13px;font-weight:500;cursor:pointer" onclick="navigator.serviceWorker.ready.then(r=>{if(r.waiting)r.waiting.postMessage({type:'SKIP_WAITING'})})">Update</button>
    <button style="background:none;border:none;color:#64748b;cursor:pointer;padding:4px;font-size:18px;line-height:1" onclick="this.parentElement.remove()">×</button>
  `;
  document.body.appendChild(toast);
}

// PWA Install Prompt — capture deferred prompt for in-app install banner
let deferredInstallPrompt: BeforeInstallPromptEvent | null = null;

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredInstallPrompt = e as BeforeInstallPromptEvent;
  // Show install banner after engagement (delay 60s from first load)
  setTimeout(() => {
    if (deferredInstallPrompt && !localStorage.getItem('pwa-install-dismissed')) {
      showInstallBanner();
    }
  }, 60000);
});

window.addEventListener('appinstalled', () => {
  deferredInstallPrompt = null;
  const banner = document.getElementById('pwa-install-banner');
  if (banner) banner.remove();
});

function showInstallBanner() {
  if (document.getElementById('pwa-install-banner')) return;
  const banner = document.createElement('div');
  banner.id = 'pwa-install-banner';
  banner.style.cssText = 'position:fixed;left:50%;transform:translateX(-50%);z-index:9998;background:#1e293b;color:#e2e8f0;padding:12px 20px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.4);display:flex;align-items:center;gap:12px;font-family:system-ui;font-size:14px;border:1px solid #334155;max-width:90vw;bottom:calc(16px + var(--tab-bar-h, 80px))';
  banner.innerHTML = `
    <span>Install for offline access</span>
    <button id="pwa-install-btn" style="background:#3b82f6;color:white;border:none;padding:6px 14px;border-radius:6px;font-size:13px;font-weight:500;cursor:pointer">Install</button>
    <button style="background:none;border:none;color:#64748b;cursor:pointer;padding:4px;font-size:18px;line-height:1" onclick="localStorage.setItem('pwa-install-dismissed',Date.now());this.parentElement.remove()">×</button>
  `;
  document.body.appendChild(banner);
  document.getElementById('pwa-install-btn')?.addEventListener('click', async () => {
    if (!deferredInstallPrompt) return;
    await deferredInstallPrompt.prompt();
    const { outcome } = await deferredInstallPrompt.userChoice;
    if (outcome === 'accepted') {
      banner.remove();
    }
    deferredInstallPrompt = null;
  });
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
)
