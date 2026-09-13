"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchPreferences, savePreferences } from "@/lib/api";
import { ChangelogModal } from "@/components/chat/ChangelogModal";

export default function AccountSettingsPage() {
  const router = useRouter();
  const [trainOnData, setTrainOnData] = useState(true);
  const [showChangelog, setShowChangelog] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const prefs = await fetchPreferences();
        if (!cancelled) setTrainOnData(prefs.train_on_data);
      } catch {
        // Keep the default-on toggle.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleToggle() {
    const next = !trainOnData;
    setTrainOnData(next);
    setSaving(true);
    setError(null);
    try {
      await savePreferences(next);
    } catch (e) {
      setTrainOnData(!next);
      setError(e instanceof Error ? e.message : "Could not save setting");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#1a1a1a] text-[#ececec] flex items-center justify-center p-4">
      <div className="w-full max-w-md rounded-2xl border border-[#404040] bg-[#1e1e1e] p-6">
        <h1 className="text-lg font-semibold mb-1">Settings</h1>
        <p className="text-sm text-[#a3a3a3] mb-5">
          We may use uploaded images to anonymously improve RealmPal. Images
          are stored temporarily and deleted automatically after a few days
          so they do not pile up.
        </p>

        <div className="rounded-xl border border-[#404040] bg-[#262626] px-4 py-3">
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="text-sm font-medium text-[#ececec]">Train on my data</p>
              <p className="text-xs text-[#737373] mt-0.5">
                Allow anonymous use of your uploads to improve the project.
                On by default. Turn this off and new uploads stay out of
                training.
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={trainOnData}
              aria-label="Train on my data"
              disabled={saving}
              onClick={() => void handleToggle()}
              className={`relative h-6 w-11 flex-shrink-0 rounded-full transition-colors cursor-pointer disabled:opacity-60 ${
                trainOnData ? "bg-white" : "bg-[#404040]"
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full transition-transform ${
                  trainOnData ? "translate-x-5 bg-[#1a1a1a]" : "translate-x-0 bg-[#ececec]"
                }`}
              />
            </button>
          </div>
        </div>

        {error && <p className="text-sm text-red-400 mt-3">{error}</p>}

        <div className="rounded-xl border border-[#404040] bg-[#262626] px-4 py-3 mt-3 flex items-center justify-between gap-4">
          <div className="min-w-0">
            <p className="text-sm font-medium text-[#ececec]">What&rsquo;s new</p>
            <p className="text-xs text-[#737373] mt-0.5">See recent RealmPal updates.</p>
          </div>
          <button
            type="button"
            onClick={() => setShowChangelog(true)}
            className="flex-shrink-0 rounded-lg border border-[#404040] px-3 py-1.5 text-xs font-medium text-[#ececec] hover:bg-[#1a1a1a] transition-colors cursor-pointer"
          >
            Changelog
          </button>
        </div>

        <button
          type="button"
          onClick={() => router.push("/")}
          className="mt-5 text-sm font-medium text-white hover:underline cursor-pointer"
        >
          Back to chat
        </button>
      </div>

      {showChangelog && <ChangelogModal onClose={() => setShowChangelog(false)} />}
    </div>
  );
}
