"use client";
import { useEffect, useState } from "react";
import Image from "next/image";
import { useSearchParams, useRouter } from "next/navigation";
import { setAuthToken } from "@/lib/api";
import { SWORD_SPRITE } from "@/lib/sprites";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Magic link verification page.
 * User arrives here from the email link after paying.
 * Exchanges the magic link token for a JWT and redirects to home.
 */
export default function VerifyPage() {
  const params = useSearchParams();
  const router = useRouter();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [paid, setPaid] = useState(false);

  useEffect(() => {
    const token = params.get("token");
    if (!token) {
      setStatus("error");
      return;
    }

    fetch(`${API_URL}/payments/verify?token=${encodeURIComponent(token)}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.token) {
          setAuthToken(data.token);
          setPaid(Boolean(data.paid));
          setStatus("success");
          setTimeout(() => router.push("/"), 1500);
        } else {
          setStatus("error");
        }
      })
      .catch(() => setStatus("error"));
  }, [params, router]);

  return (
    <div className="min-h-screen bg-[#1a1a1a] flex items-center justify-center">
      <div className="text-center">
        {status === "loading" && (
          <>
            <div className="w-8 h-8 border-2 border-[#404040] border-t-white rounded-full animate-spin mx-auto mb-4" />
            <p className="text-[#a3a3a3]">Verifying your subscription...</p>
          </>
        )}
        {status === "success" && (
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
            <p className="text-[#ececec] font-semibold text-lg">
              {paid ? "Welcome to RealmPal Pro!" : "You're signed in!"}
            </p>
            <p className="text-[#737373] text-sm mt-1">Redirecting you back...</p>
          </>
        )}
        {status === "error" && (
          <>
            <p className="text-red-400 font-semibold">Invalid or expired link</p>
            <button
              onClick={() => router.push("/")}
              className="mt-4 text-sm text-white hover:underline"
            >
              Return home
            </button>
          </>
        )}
      </div>
    </div>
  );
}
