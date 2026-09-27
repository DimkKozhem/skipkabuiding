import { useMemo, useState } from "react";
import { api } from "../api";
import { detectionKindLabel, fmtDotDateTime } from "../labels";
import type { AlertDetail, ModelLayer } from "../types";

const VERDICT_LABEL = {
  correct: "Верно",
  incorrect: "Неверно",
  indeterminate: "Нельзя определить",
} as const;

export function CandidateReview({
  detail,
  actor,
  onSaved,
}: {
  detail: AlertDetail;
  actor?: string;
  onSaved: () => Promise<void> | void;
}) {
  const layers = detail.model_layers || [];
  const [source, setSource] = useState(layers[0]?.source || "yoloe_26l");
  const [wrongType, setWrongType] = useState("");
  const [missed, setMissed] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  const layer = layers.find(item => item.source === source) || layers[0];
  const frame = detail.evidence[0];
  const reviews = (detail.candidate_reviews || []).filter(item => item.source === (layer?.source || source));
  const names = useMemo(() => {
    const unique = [...new Set((layer?.boxes || []).map(box => detectionKindLabel(box.class_name)))];
    return unique;
  }, [layer]);

  async function send(verdict: "correct" | "incorrect" | "indeterminate") {
    if (!layer) return;
    setBusy(true);
    setError("");
    try {
      await api.reviewCandidate(detail.id, {
        source: layer.source,
        verdict,
        wrong_type: wrongType,
        missed_object: missed,
        actor,
      });
      setWrongType("");
      setMissed("");
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить проверку.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="inspect-block candidate-review">
      <h3>Предположение модели</h3>
      <p className="caption">
        Это не подтверждённый факт и не отклонение от графика. Отметка относится к выбранной модели.
        Несколько отметок не являются полной разметкой всех объектов кадра.
      </p>
      <div className="page-tabs" role="tablist" aria-label="Модель">
        {(layers.length ? layers : [{ source: "yoloe_26l", label: "YOLOE-26L", boxes: [] }, { source: "grounding_dino", label: "Grounding DINO", boxes: [] }]).map(item => (
          <button
            key={item.source}
            type="button"
            className={item.source === (layer?.source || source) ? "active" : ""}
            aria-pressed={item.source === (layer?.source || source)}
            onClick={() => {
              setSource(item.source);
              setSize(null);
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
      <LayerFrame layer={layer} mediaUrl={frame?.media_url} timestamp={frame?.timestamp} size={size} onSize={setSize} />
      <p>
        {layer && layer.boxes.length
          ? `Предположение модели: ${names.join(", ")}.`
          : "Модель не предложила объекты. Это не ноль техники в факте."}
      </p>
      {layer?.error ? <p className="caption" role="status">Ответ модели: {layer.error}</p> : null}
      <div className="candidate-actions">
        <button type="button" className="btn" disabled={busy || !layer} onClick={() => send("correct")}>Верно</button>
        <button type="button" className="btn ghost" disabled={busy || !layer} onClick={() => send("incorrect")}>Неверно</button>
        <button type="button" className="btn ghost" disabled={busy || !layer} onClick={() => send("indeterminate")}>Нельзя определить</button>
      </div>
      <label className="field">
        <span>Ошибочный тип, если он указан неверно</span>
        <input value={wrongType} onChange={event => setWrongType(event.target.value)} placeholder="Например, самосвал вместо экскаватора" />
      </label>
      <label className="field">
        <span>Пропущенный объект</span>
        <input value={missed} onChange={event => setMissed(event.target.value)} placeholder="Что на кадре есть, а модель не отметила" />
      </label>
      {error ? <p role="alert" className="caption">{error}</p> : null}
      {reviews.length ? (
        <ul className="checks">
          {reviews.map(item => (
            <li key={item.id}>
              {VERDICT_LABEL[item.verdict]} · {fmtDotDateTime(item.created_at)}
              {item.wrong_type ? ` · тип: ${item.wrong_type}` : ""}
              {item.missed_object ? ` · пропуск: ${item.missed_object}` : ""}
              {" · точечная проверка"}
            </li>
          ))}
        </ul>
      ) : null}
      <details className="tech">
        <summary>Служебные поля</summary>
        <p className="caption">
          Карточка {detail.diagnostics?.alert_id || detail.id}. Наблюдение {(detail.diagnostics?.observation_ids || []).join(", ") || "—"}.
        </p>
        <ul className="checks">
          {(detail.diagnostics?.layers || []).map(item => (
            <li key={item.source}>
              {item.source} · {item.model || "модель"} · {item.model_version || "версия"} · рамок {item.n_boxes ?? 0}
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}

function LayerFrame({
  layer,
  mediaUrl,
  timestamp,
  size,
  onSize,
}: {
  layer?: ModelLayer;
  mediaUrl?: string;
  timestamp?: string;
  size: { width: number; height: number } | null;
  onSize: (size: { width: number; height: number }) => void;
}) {
  if (!mediaUrl) return <p className="caption">Кадр недоступен.</p>;
  const boxes = (layer?.boxes || []).filter(box => box.bbox.length === 4);
  return (
    <div className="frame-stage">
      <div className="frame-image">
        <img
          src={mediaUrl}
          alt={timestamp ? `Кадр ${fmtDotDateTime(timestamp)}` : "Кадр кандидата"}
          onLoad={event => onSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}
        />
        {size && boxes.length ? (
          <svg className="detection-overlay" viewBox={`0 0 ${size.width} ${size.height}`} aria-label="Рамки выбранной модели">
            {boxes.map((box, index) => {
              const [x1, y1, x2, y2] = box.bbox;
              return (
                <g key={box.evidence_id || index}>
                  <title>{`${detectionKindLabel(box.class_name)} · ${Math.round(box.confidence * 100)}%`}</title>
                  <rect x={x1} y={y1} width={Math.max(0, x2 - x1)} height={Math.max(0, y2 - y1)} />
                  <text x={x1 + 4} y={Math.max(14, y1 - 5)}>{detectionKindLabel(box.class_name)}</text>
                </g>
              );
            })}
          </svg>
        ) : null}
      </div>
    </div>
  );
}
