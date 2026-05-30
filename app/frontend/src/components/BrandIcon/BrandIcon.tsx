/**
 * Bottom-left branding icon — Databricks logo.
 * Positioned to mirror the Genie chat FAB (bottom-right).
 */

import { DatabricksLogo } from './DatabricksLogo';

export function BrandIcon() {
  return (
    <div
      className="fixed bottom-4 left-4 z-[1100] w-10 h-10 rounded-full bg-slate-800/90 border border-slate-600 shadow-lg flex items-center justify-center hover:scale-105 transition-all cursor-pointer backdrop-blur"
      style={{ bottom: 'calc(1rem + var(--tab-bar-h, 0px))' }}
      title="Powered by Databricks"
    >
      <DatabricksLogo className="w-6 h-6" />
    </div>
  );
}
