import { useEffect, useMemo, useState } from "react";
import { DECISION_STATUSES, decisionAction, statusLabel } from "../labels";
import type { InspectorConfig } from "../types";

const CHOICE_HINT: Record<string, string> = {
  confirmed: "Признаки подтверждены осмотром",
  rejected: "Сигнал не подтвердился",
  needs_more_data: "Кадра или ракурса недостаточно",
};

export function InspectionDecision({
  config,
  currentStatus,
  currentReason,
  currentNote,
  actor,
  onSubmit,
}: {
  config: InspectorConfig;
  currentStatus: string;
  currentReason?: string;
  currentNote?: string;
  actor?: string;
  onSubmit: (payload: { status: string; reason: string; note: string; actor?: string }) => Promise<void>;
}) {
  const [status, setStatus] = useState(DECISION_STATUSES.some(code => code === currentStatus) ? currentStatus : "");
  const [reason, setReason] = useState(currentReason || "");
  const [note, setNote] = useState(currentNote || "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState("");
  const reasons = useMemo(() => (status ? config.reasons[status] || {} : {}), [config, status]);

  useEffect(() => {
    setStatus(DECISION_STATUSES.some(code => code === currentStatus) ? currentStatus : "");
    setReason(currentReason || "");
    setNote(currentNote || "");
    setDone("");
  }, [currentStatus, currentReason, currentNote]);

  return (
    <form
      className="form"
      onSubmit={async (event) => {
        event.preventDefault();
        setError("");
        setDone("");
        if (!status) {
          setError("Выберите решение.");
          return;
        }
        if (!reason) {
          setError("Укажите причину решения.");
          return;
        }
        setBusy(true);
        try {
          await onSubmit({ status, reason, note });
          setDone("Решение зафиксировано.");
        } catch (err) {
          setError(err instanceof Error ? err.message : String(err));
        } finally {
          setBusy(false);
        }
      }}
    >
      <div className="section-head">
        <h2>Решение инспектора</h2>
      </div>
      {currentStatus !== "open" ? (
        <p className="caption">
          Сейчас: {statusLabel(currentStatus, config.statuses[currentStatus])}
          {currentReason ? ` · ${config.reasons[currentStatus]?.[currentReason] || currentReason}` : ""}
        </p>
      ) : (
        <p className="caption">
          Система не принимает юридический вердикт. Решение записывает {actor || "инспектор"}.
        </p>
      )}
      <div className="choice-grid">
        {DECISION_STATUSES.map((code) => (
          <button
            type="button"
            key={code}
            className={`choice ${status === code ? "active" : ""}`}
            aria-pressed={status === code}
            onClick={() => {
              setStatus(code);
              setReason("");
            }}
          >
            <b>{decisionAction(code)}</b>
            <span>{CHOICE_HINT[code]}</span>
          </button>
        ))}
      </div>
      {status ? (
        <>
          <label>Причина</label>
          <div className="chips">
            {Object.entries(reasons).map(([code, label]) => (
              <button
                type="button"
                key={code}
                className={`chip ${reason === code ? "active" : ""}`}
                aria-pressed={reason === code}
                onClick={() => setReason(code)}
              >
                {label}
              </button>
            ))}
          </div>
        </>
      ) : null}
      <label htmlFor="decision-note">Комментарий</label>
      <textarea id="decision-note" value={note} onChange={(event) => setNote(event.target.value)} placeholder="Результат осмотра или уточнение · необязательно" rows={2} />
      {error ? <div className="inline-error" role="alert">{error}</div> : null}
      {done ? <p className="ok" role="status">{done}</p> : null}
      <button className="btn" disabled={busy || !status || !reason} type="submit">
        {busy ? "Сохраняем…" : "Зафиксировать решение"}
      </button>
    </form>
  );
}
