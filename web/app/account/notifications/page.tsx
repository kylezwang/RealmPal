export default function AccountNotificationsPage() {
  return (
    <div className="min-h-screen bg-[#1a1a1a] text-[#ececec] flex items-center justify-center p-4">
      <div className="max-w-sm text-center">
        <p className="text-sm text-[#ececec]">
          Admin notifications open from the account menu, not this page.
        </p>
        <a href="/" className="mt-4 inline-block text-sm text-[#a3a3a3] underline">
          Back to chat
        </a>
      </div>
    </div>
  );
}
