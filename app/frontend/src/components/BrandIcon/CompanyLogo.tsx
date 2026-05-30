/**
 * Configurable company logo for the header top-right.
 * Tries /company-logo.svg first, falls back to /company-logo.jpeg (generic).
 */

import { useState } from 'react';

export function CompanyLogo() {
  const [useFallback, setUseFallback] = useState(false);

  return (
    <img
      src={useFallback ? '/company-logo.jpeg' : '/company-logo.svg'}
      alt="Company Logo"
      className="h-5 object-contain"
      onError={() => { if (!useFallback) setUseFallback(true); }}
    />
  );
}
