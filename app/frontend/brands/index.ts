/**
 * Brand loader — selects brand config based on VITE_BRAND env var.
 * Default: 'databricks'. Set via deploy.sh --brand <name>.
 */

import { brand as databricks } from './databricks/brand.config';
import { brand as sita } from './sita.aero/brand.config';

// Use structural type to allow different literal values across brands
type BrandShape = {
  colors: Record<string, any>;
  typography: Record<string, any>;
  spacing: Record<string, any>;
  borderRadius: Record<string, any>;
  shadows: Record<string, any>;
  backdrop: Record<string, any>;
  logo: Record<string, string>;
  layout: Record<string, any>;
  components: Record<string, any>;
  defaultAirport?: string;
};

const BRANDS: Record<string, BrandShape> = {
  databricks,
  'sita.aero': sita,
};

const key = import.meta.env.VITE_BRAND || 'databricks';
export const brand = BRANDS[key] ?? BRANDS.databricks;
export type BrandConfig = BrandShape;
