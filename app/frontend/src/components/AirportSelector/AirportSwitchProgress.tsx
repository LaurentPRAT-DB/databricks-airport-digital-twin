interface SwitchProgress {
  step: number;
  total: number;
  message: string;
  done: boolean;
}

interface AirportSwitchProgressProps {
  progress: SwitchProgress;
}

export default function AirportSwitchProgress({ progress }: AirportSwitchProgressProps) {
  const hasSteps = progress.step > 0;
  const pct = hasSteps ? Math.round((progress.step / progress.total) * 100) : 0;

  return (
    <div className="absolute top-full left-0 right-0 bg-slate-700 border-t border-slate-600 px-4 py-2 shadow-lg z-[1001] flex items-center gap-3">
      {/* Spinner */}
      {!progress.done && (
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
      <span className="text-sm text-slate-200 whitespace-nowrap">
        {progress.message}
      </span>

      {/* Step counter — only when real progress arrives */}
      {hasSteps && (
        <span className="text-xs text-slate-400 whitespace-nowrap">
          {progress.step}/{progress.total}
        </span>
      )}

      {/* Progress bar — indeterminate pulse when waiting, determinate when steps arrive */}
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
    </div>
  );
}
