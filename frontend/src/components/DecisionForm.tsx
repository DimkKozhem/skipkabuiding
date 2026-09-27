import { useEffect, useMemo, useState } from "react";
import type { InspectorConfig } from "../types";
import { STATUS_ORDER } from "../labels";

export function DecisionForm({
  config,
  currentStatus,
  onSubmit,
}: {
  config: InspectorConfig;
  currentStatus: string;
  onSubmit: (payload: { status: string; reason: string; note: string }) => Promise<void>;
}) {
  const [status, setStatus] = useState(currentStatus || "open");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const reasons = useMemo(() => config.reasons[status] || {}, [config, status]);

  useEffect(() => {
    setStatus(currentStatus || "open");
  }, [currentStatus]);

  return (
    <form
      className="form"
      onSubmit={async (event) => {
        event.preventDefault();
        setError("");
        setBusy(true);
        try {
          await onSubmit({ status, reason, note });
        } catch (err) {
          setError(err instanceof Error ? err.message : String(err));
        } finally {
          setBusy(false);
        }
      }}
    >
      <p className="caption">Решение инспектора, не автоматический вердикт системы.</p>
      <label>Статус</label>
      <select
        value={status}
        onChange={(event) => {
          setStatus(event.target.value);
          setReason("");
        }}
      >
        {STATUS_ORDER.map((code) => (
          <option key={code} value={code}>
            {config.statuses[code] || code}
          </option>
        ))}
      </select>
      <label>Причина</label>
      <select
        required={status !== "open"}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
      >
        <option value="">—</option>
        {Object.entries(reasons).map(([code, label]) => (
          <option key={code} value={code}>
            {label}
          </option>
        ))}
      </select>
      <label>Комментарий</label>
      <input value={note} onChange={(event) => setNote(event.target.value)} />
      {error ? <div className="error">{error}</div> : null}
      <button className="btn" disabled={busy || (status !== "open" && !reason)} type="submit">
        Зафиксировать решение
      </button>
    </form>
  );
}
