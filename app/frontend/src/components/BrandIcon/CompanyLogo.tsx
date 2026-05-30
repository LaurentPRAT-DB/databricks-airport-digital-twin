/**
 * Configurable company logo for the header top-right.
 * Reads from brand.config.ts — defaults to Databricks wordmark.
 * Sized to match header buttons (px-3 py-1.5 height).
 */

import { brand } from '../../config/brand.config';
import { DatabricksWordmark } from './DatabricksWordmark';

export function CompanyLogo() {
  if (brand.logo.companyLogo === 'databricks-wordmark') {
    return (
      <div className="flex items-center px-2 py-1">
        <DatabricksWordmark height={28} className="text-white" />
      </div>
    );
  }

  return (
    <div className="flex items-center px-2 py-1">
      <img
        src={brand.logo.companyLogo}
        alt="Company"
        className="h-7 object-contain"
      />
    </div>
  );
}
