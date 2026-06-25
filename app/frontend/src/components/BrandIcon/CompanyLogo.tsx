/**
 * Configurable company logo for the header top-right.
 * Loads /company-logo.svg (copied from brand folder by deploy.sh).
 * Cache-busted with build time to avoid stale logos after brand switch.
 */

import { useState } from 'react';
import { brand } from '../../../brands';

export function CompanyLogo() {
  const [hasError, setHasError] = useState(false);
  const cacheBust = `?v=${encodeURIComponent(__BUILD_TIME__)}`;

  return (
    <div className="flex items-center gap-2 h-10">
      {!hasError && (
        <img
          src={`/company-logo.svg${cacheBust}`}
          alt="Company Logo"
          className="h-full max-w-[160px] object-contain"
          onError={() => setHasError(true)}
        />
      )}
      {brand.companyName && (
        <span className="text-sm font-medium text-white whitespace-nowrap">{brand.companyName}</span>
      )}
    </div>
  );
}
