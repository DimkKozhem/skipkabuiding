import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { EmptyState, LoadingState } from "./PageState";
import { Icon } from "./Icon";
import type { CameraRef, ProjectDash, UploadResult } from "../types";
import { pingWorkspace } from "../workspace";

function localStamp(date = new Date()) {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function toIso(local: string) {
  const date = new Date(local);
  if (Number.isNaN(date.getTime())) return local;
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function ObserveForm({
  project,
  zoneCode,
  lockZone = false,
  cameras,
  onUploaded,
  mode = "page",
}: {
  project: ProjectDash;
  zoneCode: string;
  lockZone?: boolean;
  cameras?: CameraRef[];
  onUploaded?: (result: UploadResult) => void;
  mode?: "page" | "settings";
}) {
  const [zone, setZone] = useState(zoneCode || project.zones[0]?.code || "");
  const zoneCameras = useMemo(
    () => cameras || project.zones.find(item => item.code === zone)?.cameras || [],
    [project, zone, cameras],
  );
  const [camera, setCamera] = useState(zoneCameras[0]?.code || "");
  const [timestamp, setTimestamp] = useState(localStamp);
  const [file, setFile] = useState<File | null>(null);
  const [analyze, setAnalyze] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<UploadResult | null>(null);

  useEffect(() => {
    if (lockZone) setZone(zoneCode);
  }, [lockZone, zoneCode]);

  useEffect(() => {
    if (!zone && project.zones[0]) setZone(project.zones[0].code);
  }, [project, zone]);

  useEffect(() => {
    if (!zoneCameras.some(item => item.code === camera)) setCamera(zoneCameras[0]?.code || "");
  }, [zoneCameras, camera]);

  if (!zoneCameras.length) {
    if (mode === "settings") {
      return <p className="overview-empty">Сначала добавьте камеру выше. Загруженный кадр нужно к ней отнести.</p>;
    }
    return (
      <EmptyState
        title="Нет источника"
        text="Сначала подключите источник на объекте, затем загрузите кадр."
        action={<Link className="btn" to={`/objects/${zone || zoneCode}/settings#cameras`}>К камерам</Link>}
      />
    );
  }

  return (
    <div className="observe-embed">
      <form
        className={mode === "settings" ? "settings-form observe-form" : "observe-form"}
        onSubmit={async event => {
          event.preventDefault();
          setError("");
          setResult(null);
          if (!file) {
            setError("Выберите файл наблюдения.");
            return;
          }
          if (!zone || !camera) {
            setError("Укажите объект и камеру.");
            return;
          }
          const body = new FormData();
          body.set("file", file);
          body.set("project", project.code);
          body.set("zone", zone);
          body.set("camera", camera);
          body.set("timestamp", toIso(timestamp));
          body.set("run_analysis", analyze ? "true" : "false");
          setBusy(true);
          try {
            const uploaded = await api.uploadObservation(body) as UploadResult;
            setResult(uploaded);
            pingWorkspace("observation");
            onUploaded?.(uploaded);
          } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        {!lockZone && (
          <label>
            Объект
            <select aria-label="Объект" value={zone} onChange={event => setZone(event.target.value)}>
              {project.zones.map(item => <option key={item.code} value={item.code}>{item.name}</option>)}
            </select>
          </label>
        )}
        <label>
          {mode === "settings" ? "К какой камере отнести" : "Камера"}
          <select aria-label="Камера" value={camera} onChange={event => setCamera(event.target.value)}>
            {zoneCameras.map(item => <option key={item.code} value={item.code}>{item.name || "Камера"}</option>)}
          </select>
        </label>
        <label>
          Когда снято
          <input type="datetime-local" value={timestamp} onChange={event => setTimestamp(event.target.value)} />
        </label>
        <label>
          Файл
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp,video/mp4,video/webm,video/quicktime"
            onChange={event => setFile(event.target.files?.[0] || null)}
          />
        </label>
        <label className="check-row">
          <input type="checkbox" checked={analyze} onChange={event => setAnalyze(event.target.checked)} />
          {mode === "settings" ? "Сразу сравнить кадр с графиком" : "Пересчитать сигналы по этой дате"}
        </label>
        {error ? <div className="inline-error" role="alert">{error}</div> : null}
        <button className="btn" disabled={busy} type="submit" title="Сохранить кадр как наблюдение">
          {busy ? "Сохраняем…" : <>{mode === "settings" ? "Загрузить кадр" : "Записать наблюдение"}<Icon name="plus" /></>}
        </button>
      </form>
      {busy && <LoadingState text="Сохраняем кадр и считаем фактическое состояние…" />}
      {result && (
        <div className="observe-result">
          <h2>Наблюдение записано</h2>
          <p>
            Найдено объектов на кадре: {result.n_detections}.
            {result.alert_ids.length ? ` Открытых или обновлённых сигналов: ${result.alert_ids.length}.` : " Новых сигналов нет."}
          </p>
          {result.n_detections === 0 && result.detector === "annotation" && (
            <p className="caption">
              Для этого файла нет готовой разметки, поэтому объекты на кадре не отмечены. Это не доказательство отсутствия работ на площадке.
            </p>
          )}
          {!lockZone && (
            <div className="inline">
              <Link className="btn" to={`/objects/${result.zone}`}>Открыть объект</Link>
              {result.alert_ids[0] && <Link className="btn ghost" to={`/signals/${result.alert_ids[0]}`}>К сигналу</Link>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
