"use client";

export interface SuggestHit {
  name: string;
  kind: string;
}

interface Props {
  hits: SuggestHit[];
  onPick: (name: string) => void;
}

export function applySuggest(input: string, insert: string): string {
  const flags = input.match(/^((?:(?:all\s+)?(?:shiny|divine)\s+)+)/i);
  return flags ? `${flags[1]}${insert}` : insert;
}

export function ComposerSuggest({ hits, onPick }: Props) {
  if (!hits.length) return null;
  return (
    <div
      className="flex flex-wrap gap-1.5 px-4 pt-3"
      role="listbox"
      aria-label="Name suggestions"
    >
      {hits.map((hit, i) => (
        <button
          key={`${hit.kind}:${hit.name}`}
          type="button"
          role="option"
          aria-selected={i === 0}
          onMouseDown={(e) => {
            e.preventDefault();
            onPick(hit.name);
          }}
          className={`rounded-full border px-2.5 py-1 text-xs ${
            i === 0
              ? "border-[#737373] bg-[#303030] text-[#ececec]"
              : "border-[#404040] text-[#a3a3a3] hover:border-[#525252] hover:text-[#ececec]"
          }`}
        >
          {hit.name}
          {i === 0 ? (
            <span className="ml-1.5 text-[10px] uppercase tracking-wide text-[#737373]">
              Tab
            </span>
          ) : null}
        </button>
      ))}
    </div>
  );
}
