/**
 * Configurable company logo for the header top-right.
 * Reads from brand.config.ts — defaults to official Databricks wordmark.
 */

import { brand } from '../../config/brand.config';

export function CompanyLogo() {
  if (brand.logo.companyLogo === 'databricks-wordmark') {
    return (
      <img
        src="/databricks-logo.svg"
        alt="Databricks"
        className="h-5"
      />
    );
  }

  return (
    <img
      src={brand.logo.companyLogo}
      alt="Company"
      className="h-5 object-contain"
    />
  );
}
