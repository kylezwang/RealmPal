"use client";
import { useEffect, useState } from "react";
import { sendSiteFeedback, type SiteFeedbackRating } from "@/lib/api";

interface Props {
  ign?: string;
  onClose: () => void;
}

const RATINGS: { id: SiteFeedbackRating; label: string }[] = [
  { id: "great", label: "Great" },
  { id: "okay", label: "Okay" },
  { id: "rough", label: "Rough" },
];

const fieldClass =
  "w-full rounded-lg bg-[#262626] border border-[#404040] px-3 py-2 text-sm text-[#ececec] placeholder-[#525252] focus:outline-none focus:border-white transition-colors resize-y";

/**
 * Header Feedback button. A few general questions, stored in product_feedback
 * so we can scan rows in Azure Postgres.
 */
export function FeedbackModal({ ign, onClose }: Props) {
  const [rating, setRating] = useState<SiteFeedbackRating | null>(null);
  const [whatWorks, setWhatWorks] = useState("");
  const [whatToImprove, setWhatToImprove] = useState("");
  const [anythingElse, setAnythingElse] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [thanks, setThanks] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const hasText = Boolean(
    whatWorks.trim() || whatToImprove.trim() || anythingElse.trim(),
  );
  const canSubmit = Boolean(rating) && hasText && !submitting;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!rating || !hasText || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await sendSiteFeedback({
        rating,
        what_works: whatWorks.trim(),
        what_to_improve: whatToImprove.trim(),
        anything_else: anythingElse.trim(),
        ign: ign?.trim() || undefined,
      });
      setThanks(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save feedback. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="feedback-title"
    >
      <div
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="relative z-10 w-full max-w-md max-h-[80vh] overflow-y-auto rounded-2xl border border-[#404040] bg-[#1e1e1e] p-6 shadow-2xl animate-fade-in">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 rounded p-1 text-[#737373] transition-colors hover:text-[#ececec] cursor-pointer"
          aria-label="Close"
        >
          ✕
        </button>

        {thanks ? (
          <div>
            <h2 id="feedback-title" className="text-lg font-semibold text-[#ececec] mb-2">
              Thanks
            </h2>
            <p className="text-sm text-[#a3a3a3] mb-5">
              We read these regularly. This helps us pick what to fix next.
            </p>
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 rounded-lg bg-white hover:bg-[#e5e5e5] text-[#1a1a1a] text-sm font-semibold transition-colors cursor-pointer"
            >
              Close
            </button>
          </div>
        ) : (
          <form onSubmit={(event) => void handleSubmit(event)}>
            <h2 id="feedback-title" className="text-lg font-semibold text-[#ececec] mb-1">
              Feedback
            </h2>
            <p className="text-sm text-[#a3a3a3] mb-4">
              A few questions. Takes a minute.
            </p>

            <p className="text-xs font-medium text-[#ececec] mb-2">
              How has RealmPal been so far?
            </p>
            <div className="flex gap-2 mb-4" role="group" aria-label="Overall rating">
              {RATINGS.map((option) => {
                const selected = rating === option.id;
                return (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => setRating(option.id)}
                    aria-pressed={selected}
                    className={`flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition-colors cursor-pointer ${
                      selected
                        ? "border-white bg-white text-[#1a1a1a]"
                        : "border-[#404040] text-[#a3a3a3] hover:border-white hover:text-[#ececec]"
                    }`}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>

            <label htmlFor="feedback-works" className="text-xs text-[#8a8a8a] block mb-1">
              What should we keep doing?
            </label>
            <textarea
              id="feedback-works"
              value={whatWorks}
              onChange={(e) => setWhatWorks(e.target.value)}
              rows={2}
              maxLength={4000}
              className={`${fieldClass} mb-3`}
              placeholder="Builds, farm guides, item sprites..."
              disabled={submitting}
            />

            <label htmlFor="feedback-improve" className="text-xs text-[#8a8a8a] block mb-1">
              What should we fix or add?
            </label>
            <textarea
              id="feedback-improve"
              value={whatToImprove}
              onChange={(e) => setWhatToImprove(e.target.value)}
              rows={2}
              maxLength={4000}
              className={`${fieldClass} mb-3`}
              placeholder="Wrong answers, missing dungeons, confusing UI..."
              disabled={submitting}
            />

            <label htmlFor="feedback-else" className="text-xs text-[#8a8a8a] block mb-1">
              Anything else?
            </label>
            <textarea
              id="feedback-else"
              value={anythingElse}
              onChange={(e) => setAnythingElse(e.target.value)}
              rows={2}
              maxLength={4000}
              className={`${fieldClass} mb-4`}
              placeholder="Optional"
              disabled={submitting}
            />

            {error && <p className="text-xs text-red-400 mb-3">{error}</p>}

            <button
              type="submit"
              disabled={!canSubmit}
              className="px-3 py-1.5 rounded-lg bg-white hover:bg-[#e5e5e5] disabled:opacity-40 disabled:cursor-not-allowed text-[#1a1a1a] text-sm font-semibold transition-colors cursor-pointer"
            >
              {submitting ? "Sending..." : "Send feedback"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
