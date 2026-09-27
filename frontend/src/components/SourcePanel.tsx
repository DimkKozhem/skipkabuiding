import { useState } from "react";
import { api } from "../api";
import { fmtDotDateTime, publicText } from "../labels";
import type { CameraRef, CaptureStatus } from "../types";
import { pingWorkspace } from "../workspace";
import { Btn } from "./Btn";

const KINDS: Record<string, { label: string; address: string; placeholder: string; help: string }> = {
  stream: {
    label: "Видеопоток",
    address: "Адрес потока",
    placeholder: "rtsp://192.168.0.10/stream",
    help: "Камера отдаёт картинку по RTSP или HTTP. Кадр снимается с этого адреса.",
  },
  folder: {
    label: "Папка с кадрами",
    address: "Путь к папке",
    placeholder: "/data/cameras/building_01",
    help: "Берётся самый новый фото- или видеофайл в папке.",
  },
  photo: {
    label: "Фото",
    address: "Путь к файлу",
    placeholder: "/data/cameras/fasad.jpg",
    help: "Один снимок на диске.",
  },
  video: {
    label: "Видеофайл",
    address: "Путь к файлу",
    placeholder: "/data/cameras/obhod.mp4",
    help: "Один ролик на диске.",
  },
};

const FILE_KINDS = ["folder", "photo", "video"] as const;

function kindOf(camera: CameraRef) {
  return KINDS[camera.source_type || "photo"] || KINDS.photo;
}

function CameraEdit({
  camera,
  busy,
  pending,
  onSave,
  onDelete,
  onAskDelete,
  onKeep,
}: {
  camera: CameraRef;
  busy: string;
  pending: boolean;
  onSave: (fields: Record<string, unknown>) => void;
  onDelete: () => void;
  onAskDelete: () => void;
  onKeep: () => void;
}) {
  const [kindCode, setKindCode] = useState(camera.source_type || "photo");
  const kind = KINDS[kindCode] || KINDS.photo;
  return (
    <form
      className="settings-form settings-source-edit"
      onSubmit={event => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        onSave({
          name: form.get("name"),
          location: form.get("location"),
          uri: form.get("uri"),
          interval_minutes: Number(form.get("interval_minutes") || 30),
          source_type: kindCode,
        });
      }}
    >
      <div className="form-grid">
        <label>
          Название
          <input name="name" defaultValue={camera.name} required />
        </label>
        <label>
          Что это
          <select name="source_type" value={kindCode} onChange={event => setKindCode(event.target.value)}>
            {Object.entries(KINDS).map(([code, item]) => (
              <option key={code} value={code}>{item.label}</option>
            ))}
          </select>
        </label>
        <label className="span-2">
          Где стоит
          <input name="location" defaultValue={camera.location || ""} placeholder="Башенный кран, южный фасад" />
        </label>
        <label className="span-2">
          {kind.address}
          <input name="uri" defaultValue={camera.uri || ""} placeholder={kind.placeholder} />
          <span className="field-hint">{kind.help}</span>
        </label>
        <label>
          Проверять каждые, минут
          <input name="interval_minutes" type="number" min="5" max="1440" defaultValue={camera.interval_minutes || 30} />
        </label>
      </div>
      <div className="inline">
        <Btn type="submit" title="Сохранить камеру" busy={busy === `save-${camera.code}`}>Сохранить</Btn>
        {pending ? (
          <span className="confirm-bar">
            Удалить? Если уже есть кадры, камеру можно только поставить на паузу.
            <Btn variant="danger" title="Удалить камеру" busy={busy === `del-${camera.code}`} onClick={onDelete}>Удалить</Btn>
            <Btn variant="ghost" title="Оставить камеру" onClick={onKeep}>Оставить</Btn>
          </span>
        ) : (
          <Btn variant="ghost" title="Удалить камеру, если по ней ещё нет кадров" onClick={onAskDelete}>Удалить</Btn>
        )}
      </div>
    </form>
  );
}

function statusLine(camera: CameraRef) {
  if (camera.enabled === false) return "На паузе";
  if (!camera.uri) return "Адрес не указан — кадры сами не придут";
  if (camera.last_error) return "Последний кадр не получился";
  return "Включена";
}

export function SourcePanel({
  project,
  zone,
  cameras,
  capture,
}: {
  project: string;
  zone: string;
  cameras: CameraRef[];
  capture?: CaptureStatus | null;
}) {
  const [adding, setAdding] = useState<"stream" | "files" | null>(null);
  const [fileKind, setFileKind] = useState<(typeof FILE_KINDS)[number]>("folder");
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [conflictCamera, setConflictCamera] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const loopOn = Boolean(capture?.loop);
  const draftKind = adding === "stream" ? "stream" : fileKind;
  const draft = KINDS[draftKind];

  async function run(label: string, action: () => Promise<unknown>) {
    setBusy(label);
    setError("");
    setConflictCamera(null);
    try {
      await action();
      pingWorkspace("catalog");
      pingWorkspace("observation");
      setAdding(null);
      setEditing(null);
      setPending(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      if (label.startsWith("del-") && message.includes("отключить")) {
        setConflictCamera(label.replace("del-", ""));
        setPending(null);
      }
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="section" id="cameras">
      <div className="section-head">
        <div>
          <h2>Камеры</h2>
          <p className="caption">
            {loopOn
              ? `Включённые источники проверяются сами, примерно раз в ${capture?.interval_default_minutes || 30} мин.`
              : "Автосъёмка выключена. Адрес можно сохранить, а кадр взять кнопкой «Снять кадр»."}
          </p>
        </div>
        <Btn
          title="Подключить видеопоток, папку или файл"
          onClick={() => { setAdding(adding ? null : "files"); setEditing(null); }}
        >
          {adding ? "Закрыть" : "Добавить"}
        </Btn>
      </div>
      {error ? (
        <div className="inline-error" role="alert">
          <p>{error}</p>
          {conflictCamera ? (
            <Btn
              variant="ghost"
              title="Отключить источник вместо удаления"
              busy={busy === `toggle-${conflictCamera}`}
              onClick={() => run(`toggle-${conflictCamera}`, () => api.updateCamera(conflictCamera, { enabled: false }))}
            >
              Поставить на паузу
            </Btn>
          ) : null}
        </div>
      ) : null}
      {adding ? (
        <form
          className="settings-form"
          onSubmit={event => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const sourceType = adding === "stream" ? "stream" : String(form.get("source_type") || fileKind);
            void run("add", () => api.createCamera(project, zone, {
              code: `cam-${Date.now().toString(36)}`,
              name: form.get("name"),
              location: form.get("location"),
              uri: form.get("uri"),
              interval_minutes: Number(form.get("interval_minutes") || 30),
              enabled: true,
              source_type: sourceType,
            }));
          }}
        >
          <div className="settings-choice" role="group" aria-label="Что подключаем">
            <button type="button" className={adding === "files" ? "is-on" : ""} onClick={() => setAdding("files")}>
              <strong>Папка или файл</strong>
              <span>Снимки и ролики, которые уже лежат на диске.</span>
            </button>
            <button type="button" className={adding === "stream" ? "is-on" : ""} onClick={() => setAdding("stream")}>
              <strong>Видеопоток</strong>
              <span>Камера отдаёт картинку по адресу.</span>
            </button>
          </div>
          <div className="form-grid">
            <label className="span-2">
              Как назвать
              <input name="name" required placeholder="Север фасада" />
            </label>
            <label className="span-2">
              Где стоит
              <input name="location" placeholder="Башенный кран, южный фасад" />
            </label>
            {adding === "files" ? (
              <label className="span-2">
                Что лежит на диске
                <select name="source_type" value={fileKind} onChange={event => setFileKind(event.target.value as (typeof FILE_KINDS)[number])}>
                  {FILE_KINDS.map(code => <option key={code} value={code}>{KINDS[code].label}</option>)}
                </select>
              </label>
            ) : null}
            <label className="span-2">
              {draft.address}
              <input name="uri" required placeholder={draft.placeholder} />
              <span className="field-hint">{draft.help}</span>
            </label>
            <label>
              Проверять каждые, минут
              <input name="interval_minutes" type="number" min="5" max="1440" defaultValue={30} />
              <span className="field-hint">От 5 минут до суток. Имеет смысл, когда автосъёмка включена.</span>
            </label>
          </div>
          <div className="inline">
            <Btn type="submit" title="Сохранить камеру или поток" busy={busy === "add"}>Подключить</Btn>
            <Btn variant="ghost" title="Закрыть форму" onClick={() => setAdding(null)}>Отменить</Btn>
          </div>
        </form>
      ) : null}
      <div className="settings-sources">
        {cameras.map(camera => {
          const enabled = camera.enabled !== false;
          const kind = kindOf(camera);
          const open = editing === camera.code;
          return (
            <article key={camera.code} className="settings-source">
              <div>
                <strong>{publicText(camera.name) || camera.name}</strong>
                <span className="caption">
                  {kind.label}
                  {camera.location ? ` · ${camera.location}` : ""}
                </span>
              </div>
              <p className="caption">
                {statusLine(camera)}
                {camera.last_captured_at ? ` · последний кадр ${fmtDotDateTime(camera.last_captured_at)}` : ""}
              </p>
              <div className="settings-source-actions">
                <Btn
                  variant="ghost"
                  title="Изменить название, адрес и как часто снимать"
                  onClick={() => { setEditing(open ? null : camera.code); setAdding(null); setPending(null); }}
                >
                  {open ? "Скрыть" : "Изменить"}
                </Btn>
                <Btn
                  variant="ghost"
                  title={enabled ? "Временно не брать кадры" : "Снова брать кадры"}
                  busy={busy === `toggle-${camera.code}`}
                  onClick={() => run(`toggle-${camera.code}`, () => api.updateCamera(camera.code, { enabled: !enabled }))}
                >
                  {enabled ? "Пауза" : "Включить"}
                </Btn>
                <Btn
                  title="Снять кадр с этого адреса сейчас"
                  disabled={!camera.uri}
                  hint="Сначала укажите адрес и сохраните"
                  busy={busy === `shot-${camera.code}`}
                  onClick={() => run(`shot-${camera.code}`, () => api.captureRun({ camera: camera.code, force: true }))}
                >
                  Снять кадр
                </Btn>
              </div>
              {open ? (
                <CameraEdit
                  camera={camera}
                  busy={busy}
                  pending={pending === camera.code}
                  onSave={fields => run(`save-${camera.code}`, () => api.updateCamera(camera.code, fields))}
                  onDelete={() => run(`del-${camera.code}`, () => api.deleteCamera(camera.code))}
                  onAskDelete={() => setPending(camera.code)}
                  onKeep={() => setPending(null)}
                />
              ) : null}
            </article>
          );
        })}
        {!cameras.length && !adding ? (
          <p className="overview-empty">Камер ещё нет. Добавьте видеопоток или папку, откуда брать кадры.</p>
        ) : null}
      </div>
    </section>
  );
}
