/**
 * Databricks full logo (icon + wordmark) for header branding.
 * Official brand color #FF3621, white text for dark backgrounds.
 */

interface Props {
  className?: string;
  height?: number;
}

export function DatabricksWordmark({ className = '', height = 24 }: Props) {
  return (
    <svg
      className={className}
      height={height}
      viewBox="0 0 180 28"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="Databricks"
    >
      {/* Icon mark — 3-layer diamond */}
      <path d="M14 2L4 7.5v2.5l10 6 10-6V7.5L14 2Z" fill="#FF3621" />
      <path d="M14 16L4 10v4l10 6 10-6v-4L14 16Z" fill="#FF3621" opacity="0.7" />
      <path d="M14 22L4 16v4l10 6 10-6v-4L14 22Z" fill="#FF3621" opacity="0.4" />

      {/* Wordmark — "databricks" */}
      <text
        x="32"
        y="20"
        fontFamily="DM Sans, system-ui, sans-serif"
        fontSize="16"
        fontWeight="700"
        fill="currentColor"
        letterSpacing="-0.3"
      >
        databricks
      </text>
    </svg>
  );
}
