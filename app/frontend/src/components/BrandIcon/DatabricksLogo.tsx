/**
 * Databricks logo mark (diamond/lakehouse icon) as inline SVG.
 * Geometry centered in viewBox for perfect alignment in circular containers.
 */

interface Props {
  className?: string;
}

export function DatabricksLogo({ className = 'w-6 h-6' }: Props) {
  return (
    <svg
      className={className}
      viewBox="0 1 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="Databricks"
    >
      <path
        d="M12 2L3 7.5v2.5l9 5.5 9-5.5V7.5L12 2Z"
        fill="#FF3621"
      />
      <path
        d="M12 15.5L3 10v3.5l9 5.5 9-5.5V10l-9 5.5Z"
        fill="#FF3621"
        opacity="0.7"
      />
      <path
        d="M12 21L3 15.5V19l9 5 9-5v-3.5L12 21Z"
        fill="#FF3621"
        opacity="0.4"
      />
    </svg>
  );
}
