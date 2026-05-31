/**
 * Configurable company logo for the header top-right.
 * Tries /company-logo.svg first, falls back to /company-logo.jpeg (generic).
 * When brand.companyName is set, displays it next to the logo (useful for tall/vertical logos).
 */

import { useState } from 'react';
import { brand } from '../../../brands';

export function CompanyLogo() {
  const [useFallback, setUseFallback] = useState(false);

  return (
    <div className="flex items-center gap-2 h-10">
      <img
        src={useFallback ? '/company-logo.jpeg' : '/company-logo.svg'}
        alt="Company Logo"
        className="h-full max-w-[160px] object-contain"
        onError={() => { if (!useFallback) setUseFallback(true); }}
      />
      {brand.companyName && (
        <span className="text-sm font-medium text-white whitespace-nowrap">{brand.companyName}</span>
      )}
    </div>
  );
}
