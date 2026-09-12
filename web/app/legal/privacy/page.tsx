"use client";
import { useRouter } from "next/navigation";

export default function PrivacyPage() {
  const router = useRouter();
  return (
    <div className="min-h-screen bg-[#1a1a1a] text-[#ececec] flex items-center justify-center p-4">
      <div className="w-full max-w-md rounded-2xl border border-[#404040] bg-[#1e1e1e] p-6">
        <h1 className="text-lg font-semibold mb-2">Privacy Policy</h1>
        <p className="text-sm text-[#a3a3a3] mb-5">
          We use your email to run your account. Uploaded images may be used
          anonymously to improve RealmPal when Train on my data is on. Images
          are deleted automatically after a few days.
        </p>
        <button
          type="button"
          onClick={() => router.back()}
          className="text-sm font-medium text-white hover:underline cursor-pointer"
        >
          Back
        </button>
      </div>
    </div>
  );
}
