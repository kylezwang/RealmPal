"use client";
import { useEffect, useState } from "react";
import Image from "next/image";
import { fetchPlayer, type PlayerProfile } from "@/lib/api";

interface Props {
  username: string;
  onClose?: () => void;
}

export function PlayerCard({ username, onClose }: Props) {
  const [profile, setProfile] = useState<PlayerProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetching in the render body (the previous "auto-load on mount" approach)
  // is a side effect during render | React can invoke render more than once
  // (e.g. Strict Mode) and it never re-fetches if `username` changes on an
  // already-mounted card. useEffect fixes both.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchPlayer(username)
      .then((data) => {
        if (!cancelled) setProfile(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load player");
          setProfile(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [username]);

  return (
    <div
      className="rounded-xl border border-[#404040] bg-[#262626] p-4 text-sm animate-slide-up"
      role="region"
      aria-label={`Player card for ${username}`}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-[#ececec] text-base">{username}</h3>
        {onClose && (
          <button
            onClick={onClose}
            className="text-[#737373] hover:text-[#ececec] transition-colors p-1 rounded"
            aria-label="Close player card"
          >
            ✕
          </button>
        )}
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-[#a3a3a3]">
          <div className="w-4 h-4 border-2 border-[#404040] border-t-white rounded-full animate-spin" />
          <span>Loading from Realmeye...</span>
        </div>
      )}

      {error && (
        <p className="text-red-400 text-xs">{error}</p>
      )}

      {profile && (
        <div className="space-y-2">
          {profile.guild && (
            <div className="flex justify-between">
              <span className="text-[#737373]">Guild</span>
              <span className="text-[#ececec]">{profile.guild} · {profile.guild_rank}</span>
            </div>
          )}
          {profile.fame != null && (
            <div className="flex justify-between">
              <span className="text-[#737373]">Character Fame</span>
              <span className="text-white font-semibold">{profile.fame.toLocaleString()}</span>
            </div>
          )}
          {profile.characters.length > 0 && (
            <div>
              <span className="text-[#737373] block mb-1">Characters</span>
              <div className="flex flex-wrap gap-1">
                {profile.characters.slice(0, 8).map((c, i) => (
                  <span
                    key={i}
                    className="bg-[#303030] text-[#ececec] rounded px-2 py-0.5 text-xs"
                  >
                    {c.class_name}
                  </span>
                ))}
                {profile.characters.length > 8 && (
                  <span className="text-[#737373] text-xs">+{profile.characters.length - 8} more</span>
                )}
              </div>
            </div>
          )}
          {profile.top_pet && (
            <div className="flex items-center justify-between mt-2 pt-2 border-t border-[#404040]">
              <span className="text-[#737373]">Top Pet</span>
              <div className="flex items-center gap-2">
                {profile.top_pet.sprite_url && (
                  <Image
                    src={profile.top_pet.sprite_url}
                    alt={profile.top_pet.name}
                    width={24}
                    height={24}
                    className="sprite-inline"
                    unoptimized
                  />
                )}
                <span className="text-[#ececec]">
                  {profile.top_pet.name}
                  {profile.top_pet.tier && <span className="text-[#737373] ml-1">({profile.top_pet.tier})</span>}
                </span>
              </div>
            </div>
          )}
          <p className="text-[#525252] text-xs mt-1">
            via realmeye.com · {new Date(profile.scraped_at).toLocaleDateString()}
          </p>
        </div>
      )}
    </div>
  );
}
