/**
 * Configurable company logo for the header top-right.
 * Reads from brand.config.ts — defaults to Databricks wordmark.
 */

import { brand } from '../../config/brand.config';
import { DatabricksWordmark } from './DatabricksWordmark';

export function CompanyLogo() {
  if (brand.logo.companyLogo === 'databricks-wordmark') {
    return <DatabricksWordmark height={22} className="text-white" />;
  }

  // For custom logos: render as <img> from path
  return (
    <img
      src={brand.logo.companyLogo}
      alt="Company"
      className="h-6 object-contain"
    />
  );
}
