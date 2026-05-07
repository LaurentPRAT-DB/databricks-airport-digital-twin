import { useState, useEffect } from 'react';

export function MaintenanceOverlay() {
  const [dotCount, setDotCount] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => setDotCount((d) => (d + 1) % 4), 400);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="fixed inset-0 z-[9999] flex flex-col items-center justify-center bg-slate-900 text-white">
      {/* Radar sweep animation */}
      <div className="relative w-32 h-32 mb-6">
        <div className="absolute inset-0 rounded-full border-2 border-slate-600" />
        <div className="absolute inset-4 rounded-full border border-slate-700" />
        <div className="absolute inset-8 rounded-full border border-slate-700" />
        <div className="absolute inset-[3.5rem] rounded-full bg-amber-500 shadow-[0_0_12px_rgba(245,158,11,0.6)]" />
        <div
          className="absolute inset-0 origin-center"
          style={{ animation: 'maintenance-sweep 3s linear infinite' }}
        >
          <div
            className="absolute left-1/2 bottom-1/2 w-0.5 h-1/2 origin-bottom"
            style={{
              background: 'linear-gradient(to top, rgba(245,158,11,0.8), transparent)',
            }}
          />
        </div>
      </div>

      <h1 className="text-2xl font-bold mb-2">System Update in Progress</h1>
      <p className="text-sm text-slate-400 mb-1">
        The application is being updated. This usually takes 1-2 minutes.
      </p>
      <p className="text-sm text-slate-500">
        Reconnecting automatically{'.'.repeat(dotCount)}
      </p>

      <style>{`
        @keyframes maintenance-sweep {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
