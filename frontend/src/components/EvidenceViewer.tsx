import { useEffect, useMemo, useRef, useState } from "react";
import { detectionKindLabel, fmtDotDate, fmtDotDateTime, fmtTime, frameSourceLine } from "../labels";
import { isVideoUrl, previewSrc } from "../media";
import type { Detection, EvidenceItem, Observation } from "../types";
import { Icon } from "./Icon";
import { EvidencePreview } from "./EvidencePreview";
type Frame = {
  id: string;
  timestamp: string;
  mediaUrl?: string;
  vizUrl?: string;
  source?: string;
  camera?: string;
  originLabel?: string | null;
  detections?: Detection[];
};
function toFrame(item: EvidenceItem | Observation): Frame {
  const evidence = item as EvidenceItem;
  const observation = item as Observation;
  return {
    id: item.id,
    timestamp: item.timestamp,
    mediaUrl: evidence.media_url || observation.image_url,
    vizUrl: item.viz_url,
    source: item.source,
    camera: item.camera_name || undefined,
    originLabel: observation.capture_origin_label,
    detections: item.detections
  };
}
function detectionLabel(name: string) {
  return detectionKindLabel(name);
}
function FrameView({
  frame,
  mode
}: {
  frame: Frame;
  mode: "source" | "viz";
}) {
  const [failed, setFailed] = useState(false);
  const [size, setSize] = useState<{
    width: number;
    height: number;
  } | null>(null);
  const detections = (frame.detections || []).filter(item => item.bbox.length === 4 && item.bbox.every(Number.isFinite));
  const customOverlay = !isVideoUrl(frame.mediaUrl) && Boolean(frame.mediaUrl && detections.length);
  const src = mode === "viz" && !customOverlay ? frame.vizUrl || frame.mediaUrl : frame.mediaUrl || frame.vizUrl;
  if (failed || !src) return <div className="frame-stage media-unavailable">
    <Icon name="image" />
    <strong>Кадр недоступен</strong>
    <span>Попробуйте другое наблюдение</span>
  </div>;
  if (isVideoUrl(src)) return <div className="frame-stage">
    <video src={src} controls playsInline preload="metadata" poster={frame.vizUrl} onError={() => setFailed(true)} />
  </div>;
  return <div className="frame-stage">
    <div className="frame-image">
      <img src={src} alt={`Наблюдение ${fmtDotDateTime(frame.timestamp)}`} onError={() => setFailed(true)} onLoad={event => setSize({
        width: event.currentTarget.naturalWidth,
        height: event.currentTarget.naturalHeight
      })} />
      {mode === "viz" && customOverlay && size && <svg className="detection-overlay" viewBox={`0 0 ${size.width} ${size.height}`} aria-label="Разметка обнаруженных элементов">{detections.map((item, i) => {
          const [x1, y1, x2, y2] = item.bbox;
          return <g key={item.id || i}>
          <title>{detectionLabel(item.class_name)} · {Math.round(item.confidence * 100)}%</title>
          <rect x={x1} y={y1} width={Math.max(0, x2 - x1)} height={Math.max(0, y2 - y1)} />
          <text x={x1 + 4} y={Math.max(14, y1 - 5)}>{detectionLabel(item.class_name)}</text>
        </g>;
        })}</svg>}
    </div>
  </div>;
}
/** Длинный таймлапс не рисуем целиком: края периода и окно вокруг текущего кадра. */
function visibleStrip<T extends { id: string }>(frames: T[], currentId: string, limit = 9): T[] {
  if (frames.length <= limit) return frames;
  const index = Math.max(0, frames.findIndex(frame => frame.id === currentId));
  const keep = new Set<number>([0, frames.length - 1, index]);
  for (let distance = 1; keep.size < limit; distance += 1) {
    if (index - distance >= 0) keep.add(index - distance);
    if (keep.size >= limit) break;
    if (index + distance < frames.length) keep.add(index + distance);
    if (index - distance < 0 && index + distance >= frames.length) break;
  }
  return [...keep].sort((a, b) => a - b).map(position => frames[position]);
}

export function EvidenceViewer({
  items,
  empty = "Нет кадров для этого наблюдения.",
  onOpen,
  focusId,
}: {
  items: Array<EvidenceItem | Observation>;
  empty?: string;
  onOpen?: (id: string) => void;
  focusId?: string | null;
}) {
  const frames = useMemo(() => items.map(toFrame).sort((a, b) => a.timestamp.localeCompare(b.timestamp)), [items]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<"source" | "viz">("source");
  const dialog = useRef<HTMLDialogElement>(null);
  const zoomButton = useRef<HTMLButtonElement>(null);
  const current = frames.find(frame => frame.id === (focusId || selectedId)) || frames.at(-1);
  const [zoom, setZoom] = useState(false);
  useEffect(() => {
    if (zoom) dialog.current?.showModal();else dialog.current?.close();
  }, [zoom]);
  if (!current) return <div className="empty-state">
    <Icon name="image" />
    <h3>Нет доказательств</h3>
    <p>{empty}</p>
  </div>;
  const index = frames.indexOf(current);
  const hasViz = Boolean(current.detections?.length || current.vizUrl && current.vizUrl !== current.mediaUrl);
  const effectiveMode = hasViz ? mode : "source";
  const counts = new Map<string, number>();
  for (const item of current.detections || []) {
    const label = detectionLabel(item.class_name);
    counts.set(label, (counts.get(label) || 0) + 1);
  }
  const dailyCounts = new Map<string, number>();
  for (const frame of frames) {
    const day = frame.timestamp.slice(0, 10);
    dailyCounts.set(day, (dailyCounts.get(day) || 0) + 1);
  }
  const changeFrame = (id: string) => {
    setSelectedId(id);
    setMode("source");
  };
  const strip = visibleStrip(frames, current.id);
  return <div className="evidence-stage">
    <div className="evidence-toolbar">
      <div className="segmented" aria-label="Режим кадра">
        <button type="button" aria-pressed={effectiveMode === "source"} className={effectiveMode === "source" ? "active" : ""} onClick={() => setMode("source")}>Оригинал</button>
        <button type="button" aria-pressed={effectiveMode === "viz"} disabled={!hasViz} className={effectiveMode === "viz" ? "active" : ""} onClick={() => setMode("viz")}>Разметка</button>
      </div>
      {frames.length > 1 ? <div className="evidence-steps">
        <button type="button" className="icon-button" aria-label="Предыдущий кадр" disabled={index <= 0} onClick={() => changeFrame(frames[index - 1].id)}>
          <Icon name="arrow" />
        </button>
        <button type="button" className="icon-button" aria-label="Следующий кадр" disabled={index >= frames.length - 1} onClick={() => changeFrame(frames[index + 1].id)}>
          <Icon name="arrow" />
        </button>
      </div> : null}
      <span className="caption numeric">{index + 1} / {frames.length}</span>
      <button type="button" ref={zoomButton} className="icon-button" aria-label="Увеличить кадр" onClick={() => setZoom(true)}>
        <Icon name="expand" />
      </button>
    </div>
    <FrameView key={`${current.id}-${effectiveMode}`} frame={current} mode={effectiveMode} />
    <div className="evidence-meta">
      <span>{fmtDotDateTime(current.timestamp)}</span>
      <span>{frameSourceLine(current.originLabel, current.camera) || "Кадр"}</span>
      {current.source === "annotation" && <span className="source-note">Демо · разметка по аннотациям</span>}
    </div>
      {strip.length > 1 && <div className="evidence-strip" aria-label="Выбор наблюдения">{strip.map(frame => {
        const i = frames.indexOf(frame);
        return <button type="button" className={`evidence-thumb ${frame.id === current.id ? "active" : ""}`} key={frame.id} aria-label={`Наблюдение ${i + 1}, ${fmtDotDateTime(frame.timestamp)}`} aria-pressed={frame.id === current.id} onClick={() => onOpen ? onOpen(frame.id) : changeFrame(frame.id)}>
        <EvidencePreview src={previewSrc(frame.mediaUrl, frame.vizUrl)} alt="" />
        <span>
          {fmtDotDate(frame.timestamp)}
          {(dailyCounts.get(frame.timestamp.slice(0, 10)) || 0) > 1 && <small>{fmtTime(frame.timestamp)}</small>}
        </span>
      </button>;
      })}</div>}
      {frames.length > strip.length ? <p className="caption">В сигнале {frames.length} кадров. Лента показывает края периода и соседние снимки, остальные — стрелками.</p> : null}
    {counts.size > 0 && <details className="evidence-details">
      <summary>Обнаруженные элементы <span>{current.detections?.length}</span></summary>
      <div className="detection-list">{[...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "ru")).map(([name, count]) => <span key={name}>{name} <b>{count}</b></span>)}</div>
    </details>}
    <dialog ref={dialog} className="evidence-dialog" aria-label="Просмотр кадра" onClose={() => {
      setZoom(false);
      zoomButton.current?.focus();
    }} onClick={event => {
      if (event.target === event.currentTarget) setZoom(false);
    }}>
      <div className="dialog-header">
        <strong>{fmtDotDateTime(current.timestamp)} · {effectiveMode === "viz" ? "Разметка" : "Оригинал"}</strong>
        <button type="button" className="icon-button" onClick={() => setZoom(false)} aria-label="Закрыть просмотр">
          <Icon name="close" />
        </button>
      </div>
      {zoom && <FrameView key={`${current.id}-${effectiveMode}-zoom`} frame={current} mode={effectiveMode} />}
    </dialog>
  </div>;
}
