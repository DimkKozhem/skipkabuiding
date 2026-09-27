import { fmtDotDate } from "../labels";
import { previewSrc } from "../media";
import type { EvidenceItem, Observation } from "../types";
import { EvidencePreview } from "./EvidencePreview";

type Shot = {
  title: string;
  timestamp?: string;
  mediaUrl?: string;
  vizUrl?: string;
  caption?: string;
};

function fromItem(item?: EvidenceItem | Observation | null): { mediaUrl?: string; vizUrl?: string; timestamp?: string } {
  if (!item) return {};
  if ("media_url" in item || "media_path" in item) {
    const evidence = item as EvidenceItem;
    return { mediaUrl: evidence.media_url, vizUrl: evidence.viz_url, timestamp: evidence.timestamp };
  }
  const obs = item as Observation;
  return { mediaUrl: obs.image_url, vizUrl: obs.viz_url, timestamp: obs.timestamp };
}

export function EvidenceCompare({
  left,
  right,
  leftCaption,
  rightCaption,
}: {
  left?: EvidenceItem | Observation | Shot | null;
  right?: EvidenceItem | Observation | Shot | null;
  leftCaption?: string;
  rightCaption?: string;
}) {
  const a = left && "title" in left ? left : { title: "Первое наблюдение", ...fromItem(left as EvidenceItem | Observation | null) };
  const b = right && "title" in right ? right : { title: "Последнее наблюдение", ...fromItem(right as EvidenceItem | Observation | null) };
  if (!a.mediaUrl && !a.vizUrl && !b.mediaUrl && !b.vizUrl) return null;
  return (
    <div className="compare">
      <ShotCol shot={a} fallbackTitle="Первое наблюдение" caption={leftCaption} />
      <ShotCol shot={b} fallbackTitle="Последнее наблюдение" caption={rightCaption} />
    </div>
  );
}

function ShotCol({
  shot,
  fallbackTitle,
  caption,
}: {
  shot: Shot;
  fallbackTitle: string;
  caption?: string;
}) {
  const src = previewSrc(shot.mediaUrl, shot.vizUrl);
  return (
    <div className="compare-col">
      <div className="planfact-kicker">{shot.title || fallbackTitle}</div>
      <div className="caption">{fmtDotDate(shot.timestamp)}</div>
      <EvidencePreview src={src} alt={shot.title || fallbackTitle} />
      {caption ? <p className="caption">{caption}</p> : null}
    </div>
  );
}
