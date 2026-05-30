/**
 * Configurable company logo for the header top-right.
 * Logo file is copied from brands/<brand>/logo.svg to public/company-logo.svg at build time.
 */

export function CompanyLogo() {
  return (
    <img
      src="/company-logo.svg"
      alt="Company Logo"
      className="h-5"
    />
  );
}
