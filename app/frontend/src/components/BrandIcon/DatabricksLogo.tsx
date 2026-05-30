/**
 * Databricks logo mark (diamond/lakehouse icon) as inline SVG.
 * Geometry vertically centered: visual mass center at y=12 in 24x24 box.
 */

interface Props {
  className?: string;
}

export function DatabricksLogo({ className = 'w-5 h-5' }: Props) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="Databricks"
    >
      <path
        d="M12 3L4 7.5v2l8 5 8-5v-2L12 3Z"
        fill="#FF3621"
      />
      <path
        d="M12 14.5L4 9.5v3l8 5 8-5v-3l-8 5Z"
        fill="#FF3621"
        opacity="0.7"
      />
      <path
        d="M12 19.5L4 14.5v3l8 5 8-5v-3l-8 5Z"
        fill="#FF3621"
        opacity="0.4"
      />
    </svg>
  );
}
