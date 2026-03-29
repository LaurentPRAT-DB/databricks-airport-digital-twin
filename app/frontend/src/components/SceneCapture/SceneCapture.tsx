import { useState, useCallback } from 'react';
import { captureCurrentView, downloadDataUrl, formatTimeForFilename } from '../../utils/sceneCapture';

interface SceneCaptureProps {
  viewMode?: '2d' | '3d';
  airport: string | null;
  simTime: string | null;
}

export function SceneCapture({ viewMode, airport, simTime }: SceneCaptureProps) {
  const [capturing, setCapturing] = useState(false);
  const [showToast, setShowToast] = useState(false);

  const handleCapture = useCallback(async () => {
    setCapturing(true);
    try {
      const dataUrl = await captureCurrentView(simTime, airport, viewMode);

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
