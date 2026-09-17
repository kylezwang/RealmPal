/** Encode RotMG screenshots for the chat composer and Claude vision. */

import type { ClipboardEvent, DragEvent } from "react";

export const CHAT_IMAGE_ACCEPT = "image/png,image/jpeg,image/webp,image/gif";
export const CHAT_IMAGE_MAX = 4;
export const CHAT_IMAGE_MAX_BYTES = 4_000_000;
const MAX_EDGE = 1600;
const THUMB_EDGE = 96;

const ALLOWED = new Set(["image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"]);

export type ChatImagePayload = {
  filename: string;
  media_type: string;
  data: string;
};

export type ChatImageView = {
  name: string;
  thumb: string;
  src?: string;
};

export type PendingChatImage = {
  id: string;
  name: string;
  thumb: string;
  mediaType: string;
  data: string;
  error?: string;
};

export function chatImagePreviewUrl(image: {
  thumb: string;
  src?: string;
  mediaType?: string;
  data?: string;
}): string {
  if (image.src) return image.src;
  if (image.data && image.mediaType) return `data:${image.mediaType};base64,${image.data}`;
  return image.thumb;
}

export function isChatImageFile(file: File): boolean {
  return ALLOWED.has((file.type || "").toLowerCase());
}

function readAsDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("Could not read image"));
    reader.readAsDataURL(blob);
  });
}

function splitDataUrl(dataUrl: string): { mediaType: string; data: string } {
  const match = dataUrl.match(/^data:([^;]+);base64,(.+)$/);
  if (!match) throw new Error("Could not read image");
  return { mediaType: match[1], data: match[2] };
}

function canvasToBlob(canvas: HTMLCanvasElement, type: string, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("Could not compress image"))),
      type,
      quality,
    );
  });
}

async function drawScaled(file: Blob, edge: number): Promise<HTMLCanvasElement> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, edge / Math.max(bitmap.width, bitmap.height, 1));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    bitmap.close();
    throw new Error("Could not read image");
  }
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return canvas;
}

async function compressForChat(file: File): Promise<{ blob: Blob; mediaType: string }> {
  const type = file.type === "image/jpg" ? "image/jpeg" : file.type;
  if (file.size <= CHAT_IMAGE_MAX_BYTES && ALLOWED.has(type)) {
    return { blob: file, mediaType: type };
  }
  const canvas = await drawScaled(file, MAX_EDGE);
  let quality = 0.82;
  let blob = await canvasToBlob(canvas, "image/jpeg", quality);
  if (blob.size > CHAT_IMAGE_MAX_BYTES) {
    quality = 0.6;
    blob = await canvasToBlob(canvas, "image/jpeg", quality);
  }
  if (blob.size > CHAT_IMAGE_MAX_BYTES) {
    throw new Error("Image is too large");
  }
  return { blob, mediaType: "image/jpeg" };
}

export async function encodeChatImage(file: File): Promise<PendingChatImage> {
  if (!isChatImageFile(file)) {
    throw new Error("Attach a PNG, JPEG, WebP, or GIF");
  }
  const compressed = await compressForChat(file);
  const dataUrl = await readAsDataUrl(compressed.blob);
  const { mediaType, data } = splitDataUrl(dataUrl);
  const thumbCanvas = await drawScaled(compressed.blob, THUMB_EDGE);
  const thumb = thumbCanvas.toDataURL("image/jpeg", 0.72);
  return {
    id: crypto.randomUUID(),
    name: file.name || "screenshot.png",
    thumb,
    mediaType: mediaType || compressed.mediaType,
    data,
  };
}

export function filesFromClipboard(event: ClipboardEvent): File[] {
  const fromFiles = Array.from(event.clipboardData.files || []).filter(isChatImageFile);
  if (fromFiles.length) return fromFiles;
  const extras: File[] = [];
  for (const item of Array.from(event.clipboardData.items || [])) {
    if (!item.type.startsWith("image/")) continue;
    const file = item.getAsFile();
    if (file && isChatImageFile(file)) extras.push(file);
  }
  return extras;
}

export function filesFromDrop(event: DragEvent): File[] {
  return Array.from(event.dataTransfer?.files || []).filter(isChatImageFile);
}
