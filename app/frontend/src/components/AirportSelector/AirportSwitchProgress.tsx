interface SwitchProgress {
  step: number;
  total: number;
  message: string;
  done: boolean;
  error?: boolean;
}

interface AirportSwitchProgressProps {
  progress: SwitchProgress;
  error?: string | null;
}

export default function AirportSwitchProgress({ progress, error }: AirportSwitchProgressProps) {
  const hasError = !!error || progress.error;
  const hasSteps = progress.step > 0;
  const pct = hasSteps ? Math.round((progress.step / progress.total) * 100) : 0;

  return (
    <div className={`${hasError ? 'bg-red-800' : 'bg-slate-700'} ${hasError ? 'border-red-600' : 'border-slate-600'} border rounded-lg px-6 py-4 shadow-2xl flex items-center gap-3 min-w-[360px]`}>
      {/* Icon: error or spinner */}
      {hasError ? (
        <svg className="w-4 h-4 text-red-300 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      ) : !progress.done && (
        <svg
          className="w-4 h-4 animate-spin text-blue-400 shrink-0"
          viewBox="0 0 24 24"
          fill="none"
        >
          <circle
            className="opacity-25"
            cx="12" cy="12" r="10"
            stroke="currentColor" strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
          />
        </svg>
      )}

      {/* Message */}
      <span className={`text-sm ${hasError ? 'text-red-200' : 'text-slate-200'} whitespace-nowrap`}>
        {error || progress.message}
      </span>

      {/* Step counter — only when real progress arrives and no error */}
      {hasSteps && !hasError && (
        <span className="text-xs text-slate-400 whitespace-nowrap">
          {progress.step}/{progress.total}
        </span>
      )}

      {/* Progress bar — hidden on error */}
      {!hasError && (
        <div className="flex-1 h-1.5 bg-slate-600 rounded-full overflow-hidden min-w-[80px]">
          {hasSteps ? (
            <div
              className="h-full bg-blue-500 rounded-full transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          ) : (
            <div className="h-full w-1/3 bg-blue-500/60 rounded-full animate-pulse" />
          )}
        </div>
      )}
    </div>
  );
}
