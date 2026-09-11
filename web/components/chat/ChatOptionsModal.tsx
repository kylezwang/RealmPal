"use client";
import { useState } from "react";

interface Props {
  title: string;
  onRename: (newTitle: string) => void;
  onDelete: () => void;
  onClose: () => void;
}

/**
 * Modal opened from a chat-history item's "..." button.
 * Lets the user rename the conversation or delete it (two-click confirm).
 */
export function ChatOptionsModal({ title, onRename, onDelete, onClose }: Props) {
  const [name, setName] = useState(title);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  function handleSave() {
    const trimmed = name.trim();
    if (trimmed) onRename(trimmed);
    onClose();
  }

  function handleDeleteClick() {
    if (!confirmingDelete) {
      setConfirmingDelete(true);
      return;
    }
    onDelete();
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="chat-options-title"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Card */}
      <div className="relative z-10 w-full max-w-sm rounded-2xl bg-[#1e1e1e] border border-[#404040] p-6 shadow-2xl animate-slide-up">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-[#737373] hover:text-[#ececec] transition-colors p-1 rounded"
          aria-label="Close"
        >
          ✕
        </button>

        <h2 id="chat-options-title" className="text-sm font-semibold text-[#ececec] mb-4">
          Chat options
        </h2>

        <label htmlFor="chat-rename-input" className="text-xs text-[#737373] mb-1 block">
          Name
        </label>
        <div className="flex gap-2 mb-5">
          <input
            id="chat-rename-input"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSave()}
            className="flex-1 rounded-lg bg-[#262626] border border-[#404040] px-3 py-2 text-sm text-[#ececec] placeholder-[#525252] focus:outline-none focus:border-white transition-colors"
            aria-label="Chat name"
            autoFocus
          />
          <button
            onClick={handleSave}
            className="px-3 rounded-lg bg-white hover:bg-[#e5e5e5] text-[#1a1a1a] text-sm font-semibold transition-colors cursor-pointer"
          >
            Save
          </button>
        </div>

        <div className="border-t border-[#303030] pt-4">
          <button
            onClick={handleDeleteClick}
            className={`w-full rounded-lg py-2 text-sm font-semibold transition-colors cursor-pointer ${
              confirmingDelete
                ? "bg-red-500 hover:bg-red-600 text-white"
                : "bg-[#262626] hover:bg-[#3a1f1f] border border-[#404040] hover:border-red-500/50 text-red-400"
            }`}
          >
            {confirmingDelete ? "Click again to confirm delete" : "Delete conversation"}
          </button>
        </div>
      </div>
    </div>
  );
}
