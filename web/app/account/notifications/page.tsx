"use client";
import { useRouter } from "next/navigation";

export default function AccountNotificationsPage() {
  const router = useRouter();
  return (
    <div className="min-h-screen bg-[#1a1a1a] text-[#ececec] flex items-center justify-center p-4">
      <div className="w-full max-w-sm rounded-2xl border border-[#404040] bg-[#1e1e1e] p-6 text-center">
        <h1 className="text-lg font-semibold mb-2">Notifications</h1>
        <p className="text-sm text-[#a3a3a3] mb-5">
          Notification preferences are coming soon.
        </p>
        <button
          type="button"
          onClick={() => router.push("/")}
          className="text-sm font-medium text-white hover:underline cursor-pointer"
        >
          Back to chat
        </button>
      </div>
    </div>
  );
}
