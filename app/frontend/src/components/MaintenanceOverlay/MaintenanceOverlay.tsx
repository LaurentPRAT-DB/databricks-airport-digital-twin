import { useState, useEffect, useRef } from 'react';

interface InitStep {
  phase: number;
  label: string;
  status: string;
  detail: string;
  duration_ms: number;
}

const TOTAL_PHASES = 5;

export function MaintenanceOverlay() {
  const [dotCount, setDotCount] = useState(0);
  const [steps, setSteps] = useState<InitStep[]>([]);
  const [statusMessage, setStatusMessage] = useState('');
  const [elapsedSec, setElapsedSec] = useState(0);
  const startRef = useRef(Date.now());

  // Animated dots
  useEffect(() => {
    const timer = setInterval(() => setDotCount((d) => (d + 1) % 4), 400);
    return () => clearInterval(timer);
  }, []);

  // Elapsed time counter
  useEffect(() => {
    const timer = setInterval(() => {
      setElapsedSec(Math.floor((Date.now() - startRef.current) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Poll /api/ready for startup progress
  useEffect(() => {
    const poll = setInterval(async () => {
      try {
        const res = await fetch('/api/ready', { signal: AbortSignal.timeout(3000) });
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data.init_steps) && data.init_steps.length > 0) {
            setSteps(data.init_steps);
          }
          if (data.status) setStatusMessage(data.status);
        }
      } catch {
        // Backend not up yet — keep showing "waiting for server"
      }
    }, 2000);
    return () => clearInterval(poll);
  }, []);

  // Compute progress percentage from completed steps
  const doneCount = steps.filter(s => s.status === 'done').length;
  const progressPct = steps.length > 0
    ? Math.round((doneCount / TOTAL_PHASES) * 100)
    : 0;

  const formatElapsed = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  };

  return (
    <div className="fixed inset-0 z-[9999] flex flex-col items-center justify-center bg-slate-900 text-white px-6">
      {/* Radar sweep animation */}
      <div className="relative w-28 h-28 mb-6">
        <div className="absolute inset-0 rounded-full border-2 border-slate-600" />
        <div className="absolute inset-4 rounded-full border border-slate-700" />
        <div className="absolute inset-8 rounded-full border border-slate-700" />
        <div className="absolute inset-[3rem] rounded-full bg-amber-500 shadow-[0_0_12px_rgba(245,158,11,0.6)]" />
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

      <h1 className="text-xl font-bold mb-2">System Update in Progress</h1>

      {/* Progress bar */}
      <div className="w-full max-w-xs mb-4">
        <div className="flex justify-between text-xs text-slate-400 mb-1">
          <span>{progressPct > 0 ? `${progressPct}%` : 'Waiting for server'}</span>
          <span>{formatElapsed(elapsedSec)}</span>
        </div>
        <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-amber-500 rounded-full transition-all duration-700 ease-out"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* Step list */}
      {steps.length > 0 ? (
        <div className="w-full max-w-xs space-y-1.5 mb-4">
          {steps.map((step) => (
            <div key={step.phase} className="flex items-center gap-2 text-xs">
              {step.status === 'done' ? (
                <svg className="w-3.5 h-3.5 text-green-400 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                </svg>
              ) : step.status === 'running' ? (
                <div className="w-3.5 h-3.5 flex-shrink-0 flex items-center justify-center">
                  <div className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                </div>
              ) : (
                <div className="w-3.5 h-3.5 flex-shrink-0 flex items-center justify-center">
                  <div className="w-1.5 h-1.5 rounded-full bg-slate-600" />
                </div>
              )}
              <span className={step.status === 'done' ? 'text-slate-400' : step.status === 'running' ? 'text-white' : 'text-slate-600'}>
                {step.label}
              </span>
              {step.status === 'done' && step.duration_ms > 0 && (
                <span className="text-slate-500 ml-auto">{step.duration_ms > 1000 ? `${(step.duration_ms / 1000).toFixed(1)}s` : `${step.duration_ms}ms`}</span>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-slate-400 mb-1">
          {statusMessage || 'Restarting application server'}
        </p>
      )}

      <p className="text-xs text-slate-500">
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
