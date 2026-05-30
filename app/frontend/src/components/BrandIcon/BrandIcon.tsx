/**
 * Bottom-left branding icon — Databricks logo.
 * Matches the PlaybackBar pause button: same size, same circle style, aligned to bar height.
 */

import { DatabricksLogo } from './DatabricksLogo';

export function BrandIcon() {
  return (
    <div
      className="fixed left-4 z-[1100] w-9 h-9 md:w-10 md:h-10 flex items-center justify-center rounded-full bg-slate-700 hover:bg-slate-600 transition-colors cursor-pointer flex-shrink-0 shadow-lg"
      style={{ bottom: 'calc(1rem + var(--tab-bar-h, 0px))' }}
      title="Powered by Databricks"
    >
      <DatabricksLogo className="w-5 h-5" />
    </div>
  );
}
