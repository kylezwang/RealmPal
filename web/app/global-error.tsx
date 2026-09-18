"use client";
import { useEffect, useState } from "react";

/**
 * A deploy (or a dev-server restart) replaces the hashed chunk filenames an
 * already-open tab still asks for. When one of those fetches fails nothing
 * hydrates, so the page looks fully alive but every button is dead - the
 * only hint is "a client-side exception has occurred" in the console. One
 * reload picks up the new filenames, so do that instead of stranding the user.
 */
const STALE_CHUNK =
  /ChunkLoadError|Loading chunk|Failed to load chunk|dynamically imported module|importing a module script failed/i;
const RELOAD_KEY = "rp-chunk-reload-at";
/** Long enough that a genuinely broken build shows the card instead of looping. */
const RELOAD_COOLDOWN_MS = 60_000;

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const [reloading, setReloading] = useState(false);

  useEffect(() => {
    if (!STALE_CHUNK.test(`${error?.name || ""} ${error?.message || ""}`)) return;
    let lastAttempt = 0;
    try {
      lastAttempt = Number(sessionStorage.getItem(RELOAD_KEY) || 0);
    } catch {
      // Private-mode storage denial: fall through to the card.
      return;
    }
    if (Date.now() - lastAttempt < RELOAD_COOLDOWN_MS) return;
    try {
      sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
    } catch {
      return;
    }
    setReloading(true);
    window.location.reload();
  }, [error]);

  return (
    <html lang="en" className="dark">
      <body
        className="antialiased"
        style={{ backgroundColor: "#1a1a1a", color: "#ececec" }}
      >
        <div className="min-h-screen flex items-center justify-center p-4">
          <div className="w-full max-w-sm rounded-2xl border border-[#404040] bg-[#1e1e1e] p-6 text-center shadow-2xl">
            <h1 className="text-lg font-semibold text-[#ececec]">
              {reloading ? "Updating RealmPal" : "RealmPal hit an error"}
            </h1>
            <p className="mt-2 text-sm text-[#a3a3a3]">
              {reloading
                ? "A new version shipped while this tab was open. Reloading now."
                : "Reloading usually fixes it. Your chats are saved."}
            </p>
            {!reloading && error?.message ? (
              <p className="mt-3 break-words text-xs text-[#737373]">{error.message}</p>
            ) : null}
            <div className="mt-5 flex flex-col gap-2">
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="w-full rounded-lg bg-white py-2.5 text-sm font-semibold text-[#1a1a1a] hover:bg-[#e5e5e5] cursor-pointer"
              >
                Reload
              </button>
              <button
                type="button"
                onClick={reset}
                className="w-full rounded-lg border border-[#404040] py-2.5 text-sm font-medium text-[#ececec] hover:bg-[#2a2a2a] cursor-pointer"
              >
                Try again without reloading
              </button>
            </div>
          </div>
        </div>
      </body>
    </html>
  );
}
