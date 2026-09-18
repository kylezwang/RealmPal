"use client";

export interface SuggestHit {
  name: string;
  kind: string;
  alias?: string;
}

export function lastSuggestToken(input: string): { lead: string; last: string } {
  const match = input.match(/^(.*?)(\S+)$/);
  if (!match) return { lead: input, last: "" };
  return { lead: match[1], last: match[2] };
}

function completionsFor(hit: SuggestHit): string[] {
  return [hit.alias, hit.name].filter((value): value is string => Boolean(value));
}

function completeLastWord(last: string, cand: string): string | null {
  const lower = last.toLowerCase();
  if (last.length < 2) return null;
  if (cand.toLowerCase().startsWith(lower) && cand.length > last.length) {
    return last + cand.slice(last.length);
  }
  for (const word of cand.split(/\s+/)) {
    if (word.toLowerCase().startsWith(lower) && word.length > last.length) {
      return last + word.slice(last.length);
    }
  }
  return null;
}

/** Keep the sentence. Fill only the word the user is on. */
export function applySuggest(input: string, hit: SuggestHit): string {
  const { lead, last } = lastSuggestToken(input);
  if (last.length < 2) return input;
  for (const cand of completionsFor(hit)) {
    const done = completeLastWord(last, cand);
    if (done) return lead + done;
  }
  return input;
}

export function ghostRemainder(input: string, hit: SuggestHit): string {
  const next = applySuggest(input, hit);
  if (!next.toLowerCase().startsWith(input.toLowerCase())) return "";
  if (next.length <= input.length) return "";
  return next.slice(input.length);
}

export function pickGhostHit(input: string, hits: SuggestHit[]): SuggestHit | undefined {
  return hits.find((hit) => ghostRemainder(input, hit).length > 0);
}

interface Props {
  input: string;
  hit?: SuggestHit;
}

/** Grey remainder of the current word, painted over the composer. */
export function ComposerSuggest({ input, hit }: Props) {
  const rest = hit ? ghostRemainder(input, hit) : "";
  if (!rest) return null;
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0 z-10 overflow-hidden whitespace-pre-wrap break-words text-base leading-5 md:text-sm"
    >
      <span className="text-[#ececec]">{input}</span>
      <span className="text-[#737373]">{rest}</span>
    </div>
  );
}
