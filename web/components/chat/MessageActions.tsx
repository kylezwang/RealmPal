"use client";
import { useEffect, useId, useState } from "react";
import { sendFeedback, type FeedbackRating } from "@/lib/api";

interface Props {
  messageId: string;
  content: string;
  prompt?: string;
  rating?: FeedbackRating;
  onRated: (rating: FeedbackRating) => void;
}

function CopyIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function ThumbsUpIcon({ filled }: { filled?: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M7 10v12" />
      <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
    </svg>
  );
}

function ThumbsDownIcon({ filled }: { filled?: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M17 14V2" />
      <path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z" />
    </svg>
  );
}

const iconBtn =
  "w-7 h-7 rounded-md text-[#737373] hover:text-[#ececec] hover:bg-[#2a2a2a] disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center transition-colors cursor-pointer";

export function MessageActions({ messageId, content, prompt, rating, onRated }: Props) {
  const formId = useId();
  const [copied, setCopied] = useState(false);
  const [askingDown, setAskingDown] = useState(false);
  const [whatWentWrong, setWhatWentWrong] = useState("");
  const [improvement, setImprovement] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [thanks, setThanks] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(id);
  }, [copied]);

  useEffect(() => {
    if (!thanks) return;
    const id = window.setTimeout(() => setThanks(false), 2200);
    return () => window.clearTimeout(id);
  }, [thanks]);

  async function copyResponse() {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
    } catch {
      setError("Couldn't copy that response.");
    }
  }

  async function submit(next: FeedbackRating, notes?: { what_went_wrong?: string; improvement?: string }) {
    setSubmitting(true);
    setError(null);
    try {
      await sendFeedback({
        rating: next,
        message_id: messageId,
        response: content,
        prompt,
        what_went_wrong: notes?.what_went_wrong,
        improvement: notes?.improvement,
      });
      onRated(next);
      setThanks(true);
      setAskingDown(false);
      setWhatWentWrong("");
      setImprovement("");
    } catch {
      setError("Couldn't save feedback. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  function handleUp() {
    if (submitting) return;
    setAskingDown(false);
    if (rating === "up") return;
    void submit("up");
  }

  function handleDown() {
    if (submitting) return;
    setError(null);
    setAskingDown((open) => !open);
  }

  function handleDownSubmit(event: React.FormEvent) {
    event.preventDefault();
    const wentWrong = whatWentWrong.trim();
    const howToImprove = improvement.trim();
    if (!wentWrong && !howToImprove) {
      setError("Tell us what went wrong or how we could improve.");
      return;
    }
    void submit("down", {
      what_went_wrong: wentWrong || undefined,
      improvement: howToImprove || undefined,
    });
  }

  const canSubmitDown = Boolean(whatWentWrong.trim() || improvement.trim());

  return (
    <div className="mt-3">
      <div className="flex items-center gap-0.5">
        <button
          type="button"
          onClick={() => void copyResponse()}
          className={iconBtn}
          aria-label={copied ? "Copied" : "Copy response"}
          title={copied ? "Copied" : "Copy"}
        >
          {copied ? <CheckIcon /> : <CopyIcon />}
        </button>
        <button
          type="button"
          onClick={handleUp}
          disabled={submitting}
          className={`${iconBtn} ${rating === "up" ? "text-white" : ""}`}
          aria-label="Good response"
          aria-pressed={rating === "up"}
          title="Good response"
        >
          <ThumbsUpIcon filled={rating === "up"} />
        </button>
        <button
          type="button"
          onClick={handleDown}
          disabled={submitting}
          className={`${iconBtn} ${rating === "down" || askingDown ? "text-white" : ""}`}
          aria-label="Bad response"
          aria-pressed={rating === "down"}
          aria-expanded={askingDown}
          aria-controls={askingDown ? formId : undefined}
          title="Bad response"
        >
          <ThumbsDownIcon filled={rating === "down"} />
        </button>
        {thanks && !askingDown && (
          <span className="ml-2 text-[11px] text-[#a3a3a3]">Thanks for the feedback</span>
        )}
      </div>

      {askingDown && (
        <form
          id={formId}
          onSubmit={handleDownSubmit}
          className="mt-2 rounded-xl bg-[#212121] border border-[#333333] p-3 max-w-md"
        >
          <p className="text-xs font-medium text-[#ececec] mb-2">
            What went wrong, and how could we improve?
          </p>
          <label htmlFor={`${formId}-wrong`} className="text-[11px] text-[#8a8a8a] block mb-1">
            What went wrong with this response?
          </label>
          <textarea
            id={`${formId}-wrong`}
            value={whatWentWrong}
            onChange={(e) => setWhatWentWrong(e.target.value)}
            rows={2}
            className="w-full rounded-lg bg-[#262626] border border-[#404040] px-2.5 py-2 text-xs text-[#ececec] placeholder-[#525252] focus:outline-none focus:border-white transition-colors resize-y mb-2"
            placeholder="Inaccurate, missing details, not what I asked…"
            disabled={submitting}
          />
          <label htmlFor={`${formId}-improve`} className="text-[11px] text-[#8a8a8a] block mb-1">
            How could we improve?
          </label>
          <textarea
            id={`${formId}-improve`}
            value={improvement}
            onChange={(e) => setImprovement(e.target.value)}
            rows={2}
            className="w-full rounded-lg bg-[#262626] border border-[#404040] px-2.5 py-2 text-xs text-[#ececec] placeholder-[#525252] focus:outline-none focus:border-white transition-colors resize-y mb-3"
            placeholder="What would a better answer have included?"
            disabled={submitting}
          />
          <div className="flex items-center gap-2">
            <button
              type="submit"
              disabled={submitting || !canSubmitDown}
              className="px-3 py-1.5 rounded-lg bg-white hover:bg-[#e5e5e5] disabled:opacity-40 disabled:cursor-not-allowed text-[#1a1a1a] text-xs font-semibold transition-colors cursor-pointer"
            >
              {submitting ? "Sending…" : "Submit"}
            </button>
            <button
              type="button"
              onClick={() => {
                setAskingDown(false);
                setError(null);
              }}
              disabled={submitting}
              className="px-3 py-1.5 rounded-lg text-xs text-[#a3a3a3] hover:text-[#ececec] transition-colors cursor-pointer"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {error && <p className="text-[11px] text-red-400 mt-1.5">{error}</p>}
    </div>
  );
}
