"use client";

import { SpriteZoomTrigger } from "./SpriteZoom";
import { chatImagePreviewUrl, type ChatImageView, type PendingChatImage } from "@/lib/chatImages";

export function ChatImageThumb({
  name,
  thumb,
  src,
  className = "h-full w-full object-cover",
}: ChatImageView & { className?: string }) {
  const zoomSrc = chatImagePreviewUrl({ thumb, src });
  return (
    <SpriteZoomTrigger
      source={{ kind: "url", src: zoomSrc, alt: name }}
      details={{ title: name }}
      direct
      preview="image"
      className="block h-full w-full"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={thumb} alt={name} className={className} />
    </SpriteZoomTrigger>
  );
}

export function ComposerImages({
  images,
  onRemove,
}: {
  images: PendingChatImage[];
  onRemove: (id: string) => void;
}) {
  if (images.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 px-3 pt-3" aria-label="Attached screenshots">
      {images.map((image) => (
        <div
          key={image.id}
          className="relative h-14 w-[4.75rem] overflow-hidden rounded-lg border border-[#404040] bg-black"
        >
          <ChatImageThumb
            name={image.name}
            thumb={image.thumb}
            src={chatImagePreviewUrl(image)}
            className={`h-full w-full object-cover ${image.data ? "" : "opacity-60"}`}
          />
          {image.error && (
            <span className="absolute inset-0 flex items-center justify-center bg-black/70 px-1 text-center text-[10px] leading-tight text-red-300">
              {image.error}
            </span>
          )}
          <button
            type="button"
            onClick={() => onRemove(image.id)}
            className="absolute right-0.5 top-0.5 z-10 flex h-4 w-4 items-center justify-center rounded-full bg-black/70 text-[10px] text-[#ececec] hover:bg-black"
            aria-label={`Remove ${image.name}`}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
