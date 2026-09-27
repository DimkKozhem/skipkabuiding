import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { pingWorkspace } from "../workspace";
import { AlertCard } from "./AlertCard";
import { CheckDesk } from "./CheckDesk";
import { Btn } from "./Btn";
import { EvidencePreview } from "./EvidencePreview";
import { Icon } from "./Icon";
import {
  confirmedFactNotes,
  countPhrase,
  currentAlerts,
  equipmentNoun,
  alertFamily,
  frameSourceLine,
  humanDay,
  humanWhen,
  ksgPlanPhrase,
  planFactFromZone,
  siteChangeLines,
  sortAttentionAlerts,
  subjectFromExpected,
  typeLabel,
  typeLead,
} from "../labels";
import { objectPath } from "../routes";
import type { AlertListItem, ObjectPage, Observation, TimelineRow, ZoneDash } from "../types";

function candidateReason(reason?: string): string {
  const known: Record<string, string> = {
    vlm_uncertainties: "модель не уверена в границах",
    needs_open_frame_or_gt_match: "нет согласия с другим кадром",
    ambiguous_bands: "полосы неоднозначны",
  };
  const parts = String(reason || "")
    .split(";")
    .map(item => item.trim())
    .filter(Boolean)
    .map(item => known[item] || "");
  return parts.filter(Boolean).join("; ");
}

function dayOf(iso?: string | null) {
  const day = String(iso || "").slice(0, 10);
  return day.length === 10 ? day : "";
}

function observedPhrase(item?: { key: string; observed: string; observedValue?: number | null }) {
  if (!item || !item.observed || item.observed === "—") return "";
  if (item.observedValue != null && equipmentNoun(item.key, item.observedValue) !== item.key) {
    return `${item.observedValue} ${equipmentNoun(item.key, item.observedValue)}`;
  }
  return item.observed;
}

function deltaLine(key: string, expected: number | null | undefined, observed: number | null | undefined) {
  if (key === "floors" && observed == null) return "По кадру этажность не определена";
  if (expected == null || observed == null) return "Нет данных";
  const delta = observed - expected;
  if (delta === 0) return "Совпадает с планом";
  const abs = Math.abs(delta);
  const sign = delta > 0 ? "+" : "−";
  if (key === "floors" || key === "slabs" || key === "structural_levels") return `${sign}${countPhrase(key, abs)}`;
  return `${sign}${abs} ${equipmentNoun(key, abs)}`;
}

export function ObjectOverview({
  page,
  observations,
  openAlerts,
}: {
  page: ObjectPage;
  zone?: ZoneDash;
  observations: Observation[];
  openAlerts: AlertListItem[];
}) {
  const code = page.zone.code;
  const last = observations[0];
  const hasFrame = Boolean(last?.image_url || last?.viz_url);
  const primary = openAlerts[0];
  const current = (page.ksg || []).find(row => row.current);
  const metrics = planFactFromZone(page.expected, page.actual);
  const focus = metrics.find(item => item.mismatch) || metrics[0];
  const planText = focus?.expected && focus.expected !== "—"
    ? focus.expected
    : (current ? ksgPlanPhrase(current.expected) : "");
  const factText = observedPhrase(focus) || "Не определено";
  const [enlarged, setEnlarged] = useState(false);
  const capturedAt = last?.timestamp ? humanWhen(last.timestamp) : "";
  const freshness = capturedAt || "Время съёмки не указано";
  const source = frameSourceLine(page.cover_origin_label || last?.capture_origin_label, page.cover_camera_name || last?.camera_name);
  const nextDate = current?.end_date || current?.start_date;
  const planShown = planText && planText !== "—" ? planText : "";
  const factNotes = confirmedFactNotes(page.actual);
  const floorCandidate = page.actual?.scene_attributes?.floor_level_candidate as
    | { value?: number; origin?: string; reason?: string; confirmed?: boolean }
    | undefined;
  if (floorCandidate && floorCandidate.confirmed === false && floorCandidate.value != null) {
    const reason = candidateReason(floorCandidate.reason);
    factNotes.push(`Кандидат модели: ${floorCandidate.value}. Не подтверждено${reason ? `: ${reason}` : ""}.`);
  }

  return (
    <div className="object-overview">
      <div className="overview-hero-block">
        <section className="overview-photo" aria-label="Последнее наблюдение">
          {hasFrame && last ? (
            <>
              <div className="overview-photo-stage">
                <EvidencePreview
                  src={last.image_url || last.viz_url}
                  poster={last.viz_url}
                  alt={`Последний кадр: ${page.zone.name}`}
                  presentation="cover"
                  playback="inline"
                />
              </div>
              <div className="overview-photo-meta">
                <span>{[freshness, source].filter(Boolean).join(" · ")}</span>
                <span className="overview-photo-tools">
                  <button type="button" className="text-link" onClick={() => setEnlarged(true)}>Увеличить</button>
                  <a className="text-link" href={last.image_url || last.viz_url || "#"} target="_blank" rel="noreferrer">Оригинал</a>
                </span>
              </div>
            </>
          ) : (
            <div className="frame-missing overview-empty-frame">
              <strong>Нет кадра</strong>
              <span>
                {page.project.code === "housing_16"
                  ? "Снимка наблюдения ещё нет. Таймлапс открывается в источниках, сроки по кадрам — в графике."
                  : "Источник ещё не передал изображение. Время съёмки неизвестно."}
              </span>
              <Link className="btn" to={objectPath(code, "sources")}>
                {page.project.code === "housing_16" ? "Открыть источники" : "Добавить источник"}
              </Link>
            </div>
          )}
        </section>

        <aside className="state-sheet" aria-label="Что проверить">
          <p className="eyebrow">Что проверить</p>
          {primary ? (
            <div className={primary.type === "insufficient_evidence" ? "check-lead is-uncertain" : "check-lead"}>
              <p className="state-plain">{typeLabel(primary.type)}</p>
              {subjectFromExpected(primary.expected) ? <p className="check-subject">{subjectFromExpected(primary.expected)}</p> : null}
              <p className="check-why">{typeLead(primary.type)}</p>
              <Link className="btn" to={`${objectPath(code, "signals")}?check=${encodeURIComponent(primary.id)}`}>Проверить сигнал</Link>
            </div>
          ) : (
            <>
              <p className="state-plain">{focus ? deltaLine(focus.key, focus.expectedValue, focus.observedValue) : "Открытых сигналов нет"}</p>
              {hasFrame ? <Link className="btn ghost" to={objectPath(code, "history")}>Сравнить кадры</Link> : null}
            </>
          )}
          <div className="state-figure">
            <span className="eyebrow">Контрольная дата</span>
            <p className="state-plain">{nextDate ? humanDay(nextDate) : "Сроки не заданы"}</p>
          </div>
        </aside>
      </div>

      <section className="section planfact-block" aria-label="План и факт">
        <div className="planfact-sheet">
          <div>
            <span className="eyebrow">План</span>
            <p className="planfact-value numeric">{planShown || "Не задан"}</p>
            {focus?.label && planShown ? <p className="caption">{focus.label}</p> : null}
          </div>
          <div>
            <span className="eyebrow">Факт</span>
            <p className={`planfact-value numeric${factText === "Не определено" ? " is-unknown" : ""}`}>{factText === "—" ? "Не определено" : factText}</p>
            {focus?.label && factText !== "Не определено" && factText !== "—" ? <p className="caption">{focus.label}</p> : null}
          </div>
        </div>
        {factNotes.map(line => (
          <p className="state-plain" key={line}>{line}</p>
        ))}
        <Link className="text-link" to={objectPath(code, "progress")}>План и выполнение<Icon name="arrow" /></Link>
      </section>
      {enlarged && (last?.image_url || last?.viz_url) ? (
        <FrameLightbox
          src={last.image_url || last.viz_url || ""}
          alt={`Кадр: ${page.zone.name}`}
          caption={[freshness, source].filter(Boolean).join(" · ")}
          onClose={() => setEnlarged(false)}
        />
      ) : null}
    </div>
  );
}

export function RemoveFrame({
  observationId,
  when,
  onRemoved,
}: {
  observationId: string;
  when: string;
  onRemoved?: () => void;
}) {
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  return (
    <div className="chronology-shot-actions">
      {confirm ? (
        <div className="confirm-bar">
          Убрать кадр {when}? Он исчезнет из хронологии и из доказательств сигналов.
          <Btn
            variant="danger"
            title="Убрать кадр из хронологии"
            busy={busy}
            onClick={() => {
              setBusy(true);
              setError("");
              void api.deleteObservation(observationId).then(() => {
                pingWorkspace("observation");
                onRemoved?.();
              }).catch(err => {
                setError(err instanceof Error ? err.message : "Не удалось убрать кадр.");
                setBusy(false);
              });
            }}
          >
            Убрать
          </Btn>
          <Btn variant="ghost" title="Оставить кадр" onClick={() => setConfirm(false)}>Оставить</Btn>
        </div>
      ) : (
        <details className="frame-menu">
          <summary>Действия</summary>
          <button
            type="button"
            className="frame-discard"
            title="Убрать невалидный кадр из хронологии"
            onClick={() => setConfirm(true)}
          >
            Убрать кадр
          </button>
        </details>
      )}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
    </div>
  );
}

export function ChronologyFeed({
  observations,
  timeline,
  zoneCode,
}: {
  observations: Observation[];
  timeline: TimelineRow[];
  zoneCode: string;
}) {
  if (!observations.length) {
    return (
      <div className="empty-state">
        <h2>Пока нет наблюдений</h2>
        <p>После загрузки фото или кадра с камеры здесь появится история объекта.</p>
        <Link className="btn" to={`${objectPath(zoneCode, "sources")}?view=media#upload`}>Добавить материал</Link>
      </div>
    );
  }

  const byDay = new Map<string, Observation[]>();
  for (const shot of observations) {
    const day = dayOf(shot.timestamp) || shot.timestamp;
    const list = byDay.get(day) || [];
    list.push(shot);
    byDay.set(day, list);
  }

  return (
    <ol className="chronology-feed">
      {[...byDay.entries()].map(([day, shots]) => {
        const timelineRow = timeline.find(row => dayOf(row.date) === day);
        const summary = String(
          timelineRow?.summary
          || timelineRow?.actual?.scene_attributes?.observation_summary
          || "",
        );
        const change = timelineRow
          ? siteChangeLines(timelineRow.change, timelineRow.actual).find(line => line.includes("→"))
            || siteChangeLines(timelineRow.change, timelineRow.actual)[0]
          : "";
        const visible = shots.filter(shot => shot.kept !== false);
        const shown = visible.length ? visible : shots.slice(0, 1);
        return (
          <li key={day} className={shown.length === 1 ? "chronology-day is-single" : "chronology-day"}>
            <div className="chronology-rail">
              <h3><time dateTime={day}>{humanDay(day)}</time></h3>
              <p className="chronology-delta">{change || "Наблюдение"}</p>
            </div>
            {summary && summary !== change ? (
              summary.length > 180 ? (
                <details className="chronology-more">
                  <summary>Подробности наблюдения</summary>
                  <p>{summary}</p>
                </details>
              ) : <p className="chronology-summary">{summary}</p>
            ) : null}
            <div className="chronology-shots">
              {shown.map(shot => (
                <article key={shot.id} className="chronology-shot">
                  <Link
                    className="chronology-shot-open"
                    to={`${objectPath(zoneCode, "history")}?observation=${encodeURIComponent(shot.id)}&from=history`}
                  >
                    <EvidencePreview
                      src={shot.image_url || shot.viz_url}
                      poster={shot.viz_url}
                      alt=""
                      presentation="cover"
                    />
                    <span>{humanWhen(shot.timestamp)}</span>
                    <span className="caption">{frameSourceLine(shot.capture_origin_label, shot.camera_name)}</span>
                  </Link>
                  <RemoveFrame observationId={shot.id} when={humanWhen(shot.timestamp)} />
                </article>
              ))}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function FrameLightbox({
  src,
  alt,
  caption,
  onClose,
}: {
  src: string;
  alt: string;
  caption: string;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = ref.current;
    if (!node) return;
    if (!node.open) node.showModal();
    closeRef.current?.focus();
    const onCancel = (event: Event) => {
      event.preventDefault();
      onCloseRef.current();
    };
    node.addEventListener("cancel", onCancel);
    return () => {
      node.removeEventListener("cancel", onCancel);
      opener?.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="frame-lightbox"
      aria-label="Увеличенный кадр"
      onClick={event => {
        if (event.target === ref.current) onClose();
      }}
    >
      <div className="dialog-header">
        <span className="caption">Кадр</span>
        <button ref={closeRef} type="button" className="btn ghost" onClick={onClose}>Закрыть</button>
      </div>
      <img src={src} alt={alt} />
      {caption ? <p className="caption">{caption}</p> : null}
    </dialog>
  );
}

export function ObjectSignalsPanel({
  alerts,
  zoneCode,
  checkId,
  onOpen,
  onClose,
}: {
  alerts: AlertListItem[];
  zoneCode: string;
  observations?: Observation[];
  checkId?: string | null;
  onOpen: (id: string) => void;
  onClose?: () => void;
}) {
  const open = alerts.filter(item => item.status === "open" || item.status === "needs_more_data");
  const current = sortAttentionAlerts(currentAlerts(open));
  const queueRef = useRef<HTMLElement>(null);
  const scrollKey = `sitewatch.signals.scroll.${zoneCode}`;
  useEffect(() => {
    const node = queueRef.current;
    if (!node) return;
    const saved = Number(sessionStorage.getItem(scrollKey) || 0);
    if (saved > 0) node.scrollTop = saved;
    const onScroll = () => sessionStorage.setItem(scrollKey, String(node.scrollTop));
    node.addEventListener("scroll", onScroll, { passive: true });
    return () => node.removeEventListener("scroll", onScroll);
  }, [scrollKey, current.length]);
  if (!current.length && !checkId) {
    return (
      <div className="empty-state">
        <h2>Открытых сигналов нет</h2>
        <p>Когда появится возможное отклонение плана и факта, оно отобразится здесь для проверки.</p>
      </div>
    );
  }
  const picked = checkId || current[0]?.id || "";
  const selected = open.find(item => item.id === picked) || current[0];
  const history = selected
    ? open.filter(item => item.id !== selected.id && alertFamily(item) === alertFamily(selected))
    : [];
  return (
    <div className={checkId ? "object-signals is-open" : "object-signals"}>
      <aside ref={queueRef} className="object-signals-queue" aria-label="Очередь сигналов">
        <div className="queue-heading"><span>На объекте</span><b>{current.length}</b></div>
        {current.map(item => (
          <AlertCard
            key={item.id}
            alert={item}
            variant="queue"
            active={picked === item.id}
            all={open}
            onSelect={() => onOpen(item.id)}
          />
        ))}
      </aside>
      <div className="object-signals-detail">
        {picked ? (
          <CheckDesk
            alertId={picked}
            zoneCode={zoneCode}
            showBack={Boolean(checkId)}
            onClose={onClose}
            history={history}
            onOpenHistory={onOpen}
          />
        ) : (
          <p className="overview-empty">Выберите сигнал в очереди.</p>
        )}
      </div>
    </div>
  );
}
