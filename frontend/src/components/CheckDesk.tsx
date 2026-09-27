import { Link } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { checkIsUncertain, humanDay, inspectorDisplay, planFactCaption, planFactFromAlert, subjectFromExpected, typeLabel, typeLead } from "../labels";
import type { AlertDetail, AlertEvent, AlertListItem, EvidenceItem, InspectionBrief } from "../types";
import { objectPath } from "../routes";
import { useWorkspace } from "../workspace";
import { ErrorState, LoadingState } from "./PageState";
import { EvidencePreview } from "./EvidencePreview";
import { InspectionDecision } from "./InspectionDecision";
import { SliceHistory } from "./SliceHistory";

function pickFrames(items: EvidenceItem[]): EvidenceItem[] {
  const sorted = [...items].sort((a, b) => String(a.timestamp).localeCompare(String(b.timestamp)));
  if (sorted.length <= 4) return sorted;
  const picks = [
    sorted[0],
    sorted[Math.floor(sorted.length / 3)],
    sorted[Math.floor((2 * sorted.length) / 3)],
    sorted[sorted.length - 1],
  ];
  const seen = new Set<string>();
  return picks.filter(item => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
}

function trailText(event: AlertEvent, type: string, reasonLabel?: string): { actor: string; text: string } {
  const system = !event.actor || event.actor === "system" || event.action === "created";
  if (system && (!event.from_status || event.action === "created")) {
    return { actor: "Система", text: typeLead(type) };
  }
  const who = inspectorDisplay(event.actor) || "Инспектор";
  const reason = reasonLabel ? ` Причина: ${reasonLabel}.` : "";
  const note = event.note ? ` ${event.note}` : "";
  if (event.to_status === "needs_more_data") {
    return { actor: who, text: `Запрошены дополнительные данные.${reason}${note}` };
  }
  if (event.to_status === "rejected") {
    return { actor: who, text: `Сигнал отклонён.${reason}${note}` };
  }
  if (event.to_status === "confirmed") {
    return { actor: who, text: `Признаки подтверждены осмотром.${reason}${note}` };
  }
  if (event.to_status === "open") {
    return { actor: who, text: "Проверка снова открыта." };
  }
  return { actor: who, text: note.trim() || typeLead(type) };
}

export function CheckDesk({
  alertId,
  zoneCode,
  onClose,
  showBack = true,
  history = [],
  onOpenHistory,
}: {
  alertId: string;
  zoneCode: string;
  onClose?: () => void;
  showBack?: boolean;
  history?: AlertListItem[];
  onOpenHistory?: (id: string) => void;
}) {
  const { config, inspectorName, revision } = useWorkspace();
  const detail = useAsync(async () => {
    const [alert, brief] = await Promise.all([
      api.alert(alertId) as Promise<AlertDetail>,
      api.brief(alertId) as Promise<InspectionBrief>,
    ]);
    return { alert, brief };
  }, [alertId, revision]);

  if (!config || detail.loading) return <LoadingState text="Загрузка проверки…" />;
  if (detail.error || !detail.data) return <ErrorState text={detail.error || "Проверка не найдена"} />;

  const alert = detail.data.alert;
  const uncertain = checkIsUncertain(alert.type);
  const facts = planFactFromAlert(alert.type, alert.expected || alert.deviation?.expected, alert.observed || alert.deviation?.observed);
  const frames = pickFrames(alert.evidence || []);
  const from = alert.first_observed_at || frames[0]?.timestamp;
  const to = alert.last_observed_at || frames.at(-1)?.timestamp;
  const events = [...(alert.events || [])].sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));

  return (
    <article className={uncertain ? "check-desk is-uncertain" : "check-desk"}>
      {showBack ? (
        onClose ? (
          <button type="button" className="text-link check-back" onClick={onClose}>К списку проверок</button>
        ) : (
          <Link className="text-link check-back" to={objectPath(zoneCode, "signals")}>К списку проверок</Link>
        )
      ) : null}

      <header>
        <p className="eyebrow">Что проверить</p>
        <h2>{subjectFromExpected(alert.expected || alert.deviation?.expected) || typeLabel(alert.type)}</h2>
        {subjectFromExpected(alert.expected || alert.deviation?.expected) ? <p className="check-subject">{typeLabel(alert.type)}</p> : null}
      </header>

      <section>
        <h3>Почему система это показала</h3>
        <p className={checkIsUncertain(alert.type) ? "check-why is-uncertain" : "check-why"}>{typeLead(alert.type)}</p>
        {facts.length ? (
          <ul className="check-facts">
            {facts.map(item => (
              <li key={item.key}>
                <span>План: {planFactCaption(item, "plan")}</span>
                <span>Факт: {planFactCaption(item, "fact")}</span>
              </li>
            ))}
          </ul>
        ) : null}
        {from || to ? (
          <p className="caption">Интервал наблюдения: {humanDay(from)} — {humanDay(to)}</p>
        ) : null}
        {(() => {
          const confirms = String((alert.expected || alert.deviation?.expected || {}).confirms || "").trim();
          const limits = alert.observed?.limitations || alert.deviation?.observed?.limitations;
          const reason = Array.isArray(limits) ? limits.find(item => typeof item === "string" && item.trim() && !/^[a-z0-9_]+$/.test(item.trim())) : "";
          const line = [confirms && !/^[a-z0-9_]+$/.test(confirms) ? confirms : "", typeof reason === "string" ? reason : ""].filter(Boolean).join(" ");
          return line ? <p className="check-why">{line}</p> : null;
        })()}
        {checkIsUncertain(alert.type) ? (
          <p className="check-why is-uncertain">Качество наблюдения недостаточно для уверенного сопоставления.</p>
        ) : null}
      </section>

      <section>
        <h3>Доказательства</h3>
        {frames.length ? (
          <div className="check-frames">
            {frames.map(frame => {
              const shot = frame.observation_id
                ? `${objectPath(zoneCode, "history")}?observation=${encodeURIComponent(frame.observation_id)}&from=signals`
                : objectPath(zoneCode, "history");
              return (
                <Link key={frame.id} to={shot}>
                  <EvidencePreview
                    src={frame.media_url || frame.viz_url}
                    poster={frame.viz_url}
                    alt=""
                    presentation="cover"
                  />
                  <span className="caption">{humanDay(frame.timestamp)}</span>
                </Link>
              );
            })}
          </div>
        ) : (
          <p className="caption">К этой проверке ещё не привязаны кадры.</p>
        )}
      </section>

      <SliceHistory
        items={history.filter(item => item.id !== alert.id)}
        activeId={alert.id}
        onOpen={id => onOpenHistory?.(id)}
      />

      <InspectionDecision
        key={`${alert.id}:${alert.status}:${alert.decided_at || ""}`}
        config={config}
        currentStatus={alert.status}
        currentReason={alert.decision_reason}
        currentNote={alert.decision_note}
        actor={inspectorName}
        onSubmit={async payload => {
          await api.decide(alert.id, { ...payload, actor: inspectorName });
          window.dispatchEvent(new Event("sitewatch:decision"));
        }}
      />

      {events.length ? (
        <section>
          <h3>Решения и статусы</h3>
          {frames[0]?.observation_id ? (
            <Link className="text-link" to={`${objectPath(zoneCode, "history")}?observation=${encodeURIComponent(frames[0].observation_id)}&from=signals`}>
              Кадры, на которых основана проверка
            </Link>
          ) : null}
          <ol className="check-trail">
            {events.map(event => {
              const reasonLabel = config.reasons[event.to_status]?.[event.reason];
              const line = trailText(event, alert.type, reasonLabel);
              return (
                <li key={event.id}>
                  <div>
                    <time dateTime={event.created_at}>{humanDay(event.created_at)}</time>
                    <span className="who">{line.actor}</span>
                  </div>
                  <p>{line.text}</p>
                </li>
              );
            })}
          </ol>
        </section>
      ) : null}
    </article>
  );
}
