import { useState } from "react";
import { isVideoUrl, mediaKind, previewSrc } from "../media";

export function EvidencePreview({
  src,
  poster,
  alt = "кадр",
  timestamp,
  kind,
  presentation = "thumb",
  playback = "poster",
}: {
  src?: string | null;
  poster?: string | null;
  alt?: string;
  timestamp?: string;
  kind?: string | null;
  presentation?: "thumb" | "cover";
  /** poster — кадр и бейдж; inline — плеер, для героя объекта, не внутри ссылки. */
  playback?: "poster" | "inline";
}) {
  const video = mediaKind(src, kind) === "video" || isVideoUrl(src);
  const still = video ? (poster || undefined) : previewSrc(src, poster, kind);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const play = video && playback === "inline" && Boolean(src) && failedUrl !== src;
  return (
    <div className="evidence-preview">
      {play ? (
        <video
          src={src || undefined}
          poster={still}
          controls
          playsInline
          preload="metadata"
          onError={() => setFailedUrl(src || "")}
        />
      ) : still && failedUrl !== still ? (
        <img src={still} alt={alt} loading="lazy" onError={() => setFailedUrl(still)} />
      ) : video ? (
        <div className="evidence-preview-fallback">Видео</div>
      ) : presentation === "cover" ? (
        <div className="frame-missing">
          <strong>Нет кадра</strong>
          <span>Источник ещё не передал изображение.</span>
        </div>
      ) : (
        <div className="evidence-preview-fallback">Нет кадра</div>
      )}
      {video && !play ? <span className="media-badge">видео</span> : null}
      {timestamp ? <span className="evidence-preview-time">{timestamp}</span> : null}
    </div>
  );
}
