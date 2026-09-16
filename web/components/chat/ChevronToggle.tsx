"use client";

interface Props {
  expanded: boolean;
  onToggle: () => void;
  hideLabel: string;
  showLabel: string;
}

/** Same chevron the sidebar uses to hide or show quick suggestions. */
export function ChevronToggle({ expanded, onToggle, hideLabel, showLabel }: Props) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={expanded ? hideLabel : showLabel}
      aria-expanded={expanded}
      className="flex h-5 w-6 items-center justify-center rounded text-[#525252] hover:text-[#a3a3a3] hover:bg-[#333333] transition-colors cursor-pointer"
    >
      <svg
        width="12"
        height="12"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={`transition-transform duration-150 ${expanded ? "" : "rotate-180"}`}
        aria-hidden="true"
      >
        <polyline points="6 9 12 15 18 9" />
      </svg>
    </button>
  );
}
