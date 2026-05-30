/**
 * Databricks logo mark (diamond/lakehouse icon) as inline SVG.
 */

interface Props {
  className?: string;
}

export function DatabricksLogo({ className = 'w-6 h-6' }: Props) {
  return (
    <svg
      className={className}
      viewBox="0 0 36 36"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="Databricks"
    >
      <path
        d="M18 2L3 10.5V13.5L18 22L33 13.5V10.5L18 2Z"
        fill="#FF3621"
      />
      <path
        d="M18 22L3 13.5V18.5L18 27L33 18.5V13.5L18 22Z"
        fill="#FF3621"
        opacity="0.7"
      />
      <path
        d="M18 27L3 18.5V23.5L18 32L33 23.5V18.5L18 27Z"
        fill="#FF3621"
        opacity="0.4"
      />
    </svg>
  );
}
