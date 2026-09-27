export type MediaKind = "image" | "video" | "unknown";

const IMAGE_EXT = /\.(jpe?g|png|webp|gif)(\?|$)/i;
const VIDEO_EXT = /\.(mp4|webm|mov)(\?|$)/i;

export function mediaKind(url?: string | null, hint?: string | null): MediaKind {
  // Slot for future API `media_kind`. `source` is the detector, not the file type.
  if (hint === "video") return "video";
  if (hint === "photo" || hint === "image") return "image";
  if (!url) return "unknown";
  if (VIDEO_EXT.test(url)) return "video";
  if (IMAGE_EXT.test(url)) return "image";
  return "unknown";
}

export function isVideoUrl(url?: string | null): boolean {
  return mediaKind(url) === "video";
}

export function previewSrc(mediaUrl?: string | null, vizUrl?: string | null, hint?: string | null): string | undefined {
  const kind = mediaKind(mediaUrl, hint);
  if (kind === "video") return vizUrl || undefined;
  return mediaUrl || vizUrl || undefined;
}
