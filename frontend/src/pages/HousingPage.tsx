import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { api } from "../api";
import { EmptyState, ErrorState, LoadingState } from "../components/PageState";
import { StatusBadge } from "../components/StatusBadge";
import { Icon } from "../components/Icon";
import { useAsync } from "../hooks";
import { type Tone } from "../labels";
import { objectPath } from "../routes";
import type { HousingRowStatus, HousingSchedule, HousingScheduleRow, HousingVideo } from "../types";

const PROJECT_ID = "housing_16";

const STATUS_LABEL: Record<HousingRowStatus, string> = {
  planned: "План",
  done: "По кадрам",
  attention: "Требует проверки",
};

const STATUS_TONE: Record<HousingRowStatus, Tone> = {
  planned: "muted",
  done: "ok",
  attention: "attention",
};

function factCell(value: number | null | undefined) {
  if (value === null || value === undefined) return "Не определено";
  return String(value);
}

function fmtClock(iso: string): { day: string; hm: string } | null {
  const [dayPart, timePart] = iso.split("T");
  if (!dayPart || !timePart) return null;
  const [year, month, day] = dayPart.split("-");
  return { day: `${day}.${month}.${year}`, hm: timePart.slice(0, 5) };
}

function fmtFrameSlot(start: string, end: string) {
  const a = fmtClock(start);
  const b = fmtClock(end);
  if (!a || !b) return start;
  if (a.day === b.day) return `${a.day} ${a.hm}–${b.hm}`;
  return `${a.day} ${a.hm} – ${b.day} ${b.hm}`;
}

function fmtDotDateTime(iso: string) {
  const clock = fmtClock(iso);
  if (!clock) return iso;
  return `${clock.day} ${clock.hm}`;
}

function statusBadge(status: HousingRowStatus) {
  return <StatusBadge tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</StatusBadge>;
}

export function HousingScheduleBlock() {
  return <HousingBody part="schedule" />;
}

export function HousingVideoBlock() {
  return <HousingBody part="video" />;
}

/** Старый адрес сценария ведёт в карточку корпуса, без отдельной оболочки. */
export function HousingPage() {
  return <Navigate to={objectPath("corpus_01", "sources")} replace />;
}

function HousingBody({ part }: { part: "schedule" | "video" }) {
  const { data, error, loading, setData } = useAsync(
    () => api.housingSchedule(PROJECT_ID) as Promise<HousingSchedule>,
    [],
  );
  const [file, setFile] = useState<File | null>(null);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [runBusy, setRunBusy] = useState(false);
  const [runError, setRunError] = useState("");
  const [missingIds, setMissingIds] = useState<string[]>([]);

  if (loading && !data) return <LoadingState text="Загружаем график жилого дома…" />;
  if (error && !data) return <ErrorState text={error} />;
  if (!data) {
    return (
      <EmptyState
        title="Нет графика"
        text="Загрузите CSV графика строительства для сценария жилого дома."
      />
    );
  }

  const interval = data.frame_interval_minutes ?? 30;
  const signals = data.run?.signals || [];
  const clips: HousingVideo[] = data.videos?.length
    ? data.videos
    : data.video_url
      ? [{ id: "primary", title: "Таймлапс корпуса", url: data.video_url, runs_pipeline: true }]
      : [];

  return (
    <div className="housing-embed">
      {part === "schedule" ? (
        <div className="stack">
          <div className="section-head">
            <div>
              <h2>График по кадрам</h2>
              <p className="caption">Между соседними кадрами {interval} минут. Сроки относятся к этому ролику, не к сегодняшней дате.</p>
            </div>
            <Link className="text-link" to={objectPath("corpus_01", "sources")}>Таймлапс</Link>
          </div>
          <section className="housing-upload">
            <form
              className="observe-form"
              onSubmit={async event => {
                event.preventDefault();
                setUploadError("");
                if (!file) {
                  setUploadError("Выберите CSV-файл графика.");
                  return;
                }
                const body = new FormData();
                body.set("file", file);
                setUploadBusy(true);
                try {
                  const next = await api.housingUploadSchedule(body, PROJECT_ID) as HousingSchedule;
                  setData(next);
                  setFile(null);
                } catch (err) {
                  setUploadError(err instanceof Error ? err.message : String(err));
                } finally {
                  setUploadBusy(false);
                }
              }}
            >
              <label>
                Файл графика (CSV)
                <input
                  type="file"
                  accept=".csv,text/csv"
                  onChange={event => setFile(event.target.files?.[0] || null)}
                />
              </label>
              {uploadError ? <div className="inline-error" role="alert">{uploadError}</div> : null}
              <button className="btn" type="submit" disabled={uploadBusy} title="Загрузить CSV графика">
                {uploadBusy ? "Загружаем…" : <>Загрузить график<Icon name="upload" /></>}
              </button>
            </form>
          </section>

          {data.rows.length ? (
            <div className="table-scroll">
              <table className="object-table housing-table ksg-table">
                <thead>
                  <tr>
                    <th>Время кадра</th>
                    <th>Код</th>
                    <th>Название</th>
                    <th>План этажей</th>
                    <th>Факт этажей</th>
                    <th>Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row: HousingScheduleRow, index) => (
                    <tr key={`${row.stage}-${row.date_start}-${row.plan_floors}-${index}`}>
                      <td>{fmtFrameSlot(row.date_start, row.date_end)}</td>
                      <td>{row.catalog_code || "—"}</td>
                      <td>
                        {row.title}
                        {row.fact_note ? <p className="caption">{row.fact_note}</p> : null}
                      </td>
                      <td>{row.plan_floors}</td>
                      <td>{factCell(row.fact_floors)}</td>
                      <td>{statusBadge(row.status)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="housing-empty caption">График пуст. Загрузите CSV.</p>
          )}
        </div>
      ) : (
        <aside className="stack">
          <div className="section-head">
            <h2>Таймлапс</h2>
            <Link className="text-link" to={objectPath("corpus_01", "schedule")}>График по кадрам</Link>
          </div>
          {clips.length === 0 ? (
            <div className="housing-video-missing">Видео ещё не положили в папку video</div>
          ) : (
            clips.map(clip =>
              missingIds.includes(clip.id) || !clip.url ? (
                <div key={clip.id} className="housing-video-missing">
                  {clip.title ? `${clip.title}: ` : ""}видео ещё не положили в папку video
                </div>
              ) : (
                <figure key={clip.id} className="housing-video">
                  <video
                    controls
                    preload="metadata"
                    src={clip.url}
                    onError={() =>
                      setMissingIds(prev => (prev.includes(clip.id) ? prev : [...prev, clip.id]))
                    }
                  >
                    Видео ещё не положили в папку video
                  </video>
                  <figcaption>{clip.title}</figcaption>
                </figure>
              ),
            )
          )}

          <div className="housing-run">
            <button
              className="btn"
              type="button"
              disabled={runBusy}
              title="Прогнать таймлапс и заполнить факт по этапам"
              onClick={async () => {
                setRunError("");
                setRunBusy(true);
                try {
                  const next = await api.housingRun(PROJECT_ID) as HousingSchedule;
                  setData(next);
                  setMissingIds([]);
                } catch (err) {
                  setRunError(err instanceof Error ? err.message : String(err));
                } finally {
                  setRunBusy(false);
                }
              }}
            >
              {runBusy ? "Обрабатываем кадры…" : <>Прогнать видео<Icon name="camera" /></>}
            </button>
            {runError ? <div className="inline-error" role="alert">{runError}</div> : null}
            {data.run ? (
              <p className="caption">
                Обработано кадров: {data.run.frames_processed}. Интервал: {data.run.frame_interval_minutes} мин.
                Длительность ролика: {Math.round(data.run.video_duration_sec)} с.
              </p>
            ) : null}
          </div>

          {signals.length > 0 ? (
            <ul className="housing-signal-list">
              {signals.map((signal, index) => (
                <li key={`${signal.type}-${signal.at}-${index}`}>
                  <p>{signal.text}</p>
                  <span className="caption">{fmtDotDateTime(signal.at)}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </aside>
      )}
    </div>
  );
}
