/**
 * Configurable company logo for the header top-right.
 * Tries /company-logo.svg first, falls back to /company-logo.jpeg (generic).
 */

import { useState } from 'react';

export function CompanyLogo() {
  const [useFallback, setUseFallback] = useState(false);

  return (
    <div className="flex items-center px-3 py-1.5 h-8">
      <img
        src={useFallback ? '/company-logo.jpeg' : '/company-logo.svg'}
        alt="Company Logo"
        className="h-full object-contain"
        onError={() => { if (!useFallback) setUseFallback(true); }}
      />
    </div>
  );
}
