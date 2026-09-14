"use client";
import { useEffect, useState } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { setAuthToken } from "@/lib/api";
import { completeEntraRedirect } from "@/lib/msal";
import { SWORD_SPRITE } from "@/lib/sprites";

/**
 * Entra External ID redirects here after sign-up/sign-in (see
 * NEXT_PUBLIC_ENTRA_* in web/.env.local and the SPA app registration's
 * redirect URI in docs/DEPLOYMENT_GUIDE.md PRIORITY 3 Step 3).
 *
 * The token this stores is an Entra-issued access token, not one of our
 * own HS256 session JWTs - api/dependencies.py's get_optional_user()
 * verifies both, trying Entra's JWKS first, so every existing
 * authHeaders() call site downstream needs no changes.
 */
export default function AuthCallbackPage() {
  const router = useRouter();
  const [status, setStatus] = useState<"loading" | "error">("loading");
  const [message, setMessage] = useState("Finishing sign-in...");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = await completeEntraRedirect();
        if (cancelled) return;
        if (!token) {
          setStatus("error");
          setMessage("No sign-in in progress. Go back and try again.");
          return;
        }
        setAuthToken(token);
        router.push("/");
      } catch (err) {
        if (cancelled) return;
        setStatus("error");
        setMessage(err instanceof Error ? err.message : "Sign-in failed. Try again.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <div className="min-h-screen bg-[#1a1a1a] flex items-center justify-center">
      <div className="text-center px-6">
        {status === "loading" ? (
          <>
            <div className="w-8 h-8 border-2 border-[#404040] border-t-white rounded-full animate-spin mx-auto mb-4" />
            <p className="text-[#a3a3a3]">{message}</p>
          </>
        ) : (
          <>
            <Image
              src={SWORD_SPRITE}
              alt="RealmPal"
              width={40}
              height={40}
              style={{ imageRendering: "pixelated" }}
              className="mx-auto mb-3"
              unoptimized
            />
            <p className="text-red-400 font-semibold">{message}</p>
            <button
              onClick={() => router.push("/auth/signin")}
              className="mt-4 text-sm text-white hover:underline cursor-pointer"
            >
              Back to sign in
            </button>
          </>
        )}
      </div>
    </div>
  );
}
