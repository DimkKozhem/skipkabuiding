import { Link } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { comparisonModeFor, controlDateIso, dynamicsCaption, eventCaption, fmtDotDate, fmtDotDateTime, planFactFromAlert, statusLabel, statusTone, typeLabel, typeLead } from "../labels";
import type { AlertDetail, InspectionBrief, InspectorConfig, ObjectPage, TimelineRow } from "../types";
import { EvidenceCompare } from "./EvidenceCompare";
import { EvidenceViewer } from "./EvidenceViewer";
import { InspectionDecision } from "./InspectionDecision";
import { PlanFactComparison } from "./PlanFactComparison";
import { StatusBadge } from "./StatusBadge";
import { FloorsRail } from "./TimelineTrack";
export function AlertPanel({
  detail,
  brief,
  config,
  actor,
  onDecided
}: {
  detail: AlertDetail;
  brief?: InspectionBrief | null;
  config: InspectorConfig;
  actor?: string;
  onDecided: () => Promise<void> | void;
}) {
  const expected = detail.expected || detail.deviation?.expected;
  const observed = detail.observed || detail.deviation?.observed;
  const control = controlDateIso(detail);
  const temporal = detail.type === "no_dynamics" || detail.type === "schedule_delay";
  const context = useAsync(async () => {
    if (!detail.project || !detail.zone || !temporal) return null;
    const [page, timeline] = await Promise.all([api.objectPage(detail.project, detail.zone) as Promise<ObjectPage>, api.timeline(detail.project, detail.zone) as Promise<TimelineRow[]>]);
    return {
      page,
      timeline: timeline.filter(row => !control || row.date <= control)
    };
  }, [detail.id, detail.project, detail.zone, temporal, control]);
  const facts = planFactFromAlert(detail.type, expected, observed);
  const evidence = [...detail.evidence].sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  return <article className="inspect-flow">
    <header className="signal-header">
      <div className="eyebrow">
        <Link to={detail.zone ? `/objects/${detail.zone}` : "/objects"}>{detail.zone_name || "Объект"}</Link>
        <span> / {fmtDotDate(control)}</span>
      </div>
      <h2>{typeLabel(detail.type)}</h2>
      <StatusBadge tone={statusTone(detail.status)}>{statusLabel(detail.status, detail.status_label)}</StatusBadge>
    </header>
    <div className="signal-investigation">
      {detail.type === "model_candidate" ? null : <PlanFactComparison items={facts} mode={comparisonModeFor(detail.type, expected, observed)} caption={detail.type === "no_dynamics" ? dynamicsCaption(observed) : undefined} />}
      <div className="signal-evidence">
        <EvidenceViewer items={evidence} />
      </div>
    </div>
    <section className="inspect-block">
      <h3>Основание сигнала</h3>
      <p>{typeLead(detail.type)}</p>
    </section>
    {evidence.length > 1 && temporal && <section className="inspect-block">
      <div className="section-head">
        <h3>Сравнение за период</h3>
        <span className="caption">Первое и последнее наблюдение</span>
      </div>
      <EvidenceCompare left={evidence[0]} right={evidence.at(-1)} />
    </section>}
    {temporal && <details className="timeline-disclosure">
      <summary>Динамика на контрольных датах</summary>
      {context.error ? <p role="alert" className="caption">Не удалось загрузить историю наблюдений.</p> : context.loading ? <p className="caption">Загрузка истории…</p> : context.data && <FloorsRail rows={context.data.timeline} alerts={context.data.page.alerts} showFrame={false} />}
    </details>}
    <section className="inspection-action">
      <div className="inspection-checks">
        <span className="eyebrow">Следующий шаг</span>
        <h3>Что проверить на площадке</h3>
        {brief?.on_site_checks?.length ? <ul className="checks">{brief.on_site_checks.map(item => <li key={item}>{item}</li>)}</ul> : <p className="caption">Сопоставьте наблюдение с условиями на площадке.</p>}
      </div>
      <InspectionDecision key={detail.id} config={config} currentStatus={detail.status} currentReason={detail.decision_reason} currentNote={detail.decision_note} actor={actor} onSubmit={async payload => {
        await api.decide(detail.id, { ...payload, actor });
        window.dispatchEvent(new Event("sitewatch:decision"));
        await onDecided();
      }} />
    </section>
    <p className="caption decision-disclaimer">{brief?.disclaimer || config.disclaimer}</p>
    <details className="tech">
      <summary>История решений · {detail.events.length}</summary>
      <div className="chronicle">{detail.events.map(item => <div className="chronicle-item" key={item.id}>
          <span className="eyebrow">{fmtDotDateTime(item.created_at)}</span>
          <p>{eventCaption(item.from_status, item.to_status, item.actor, config.reasons[item.to_status]?.[item.reason])}</p>
        </div>)}</div>
    </details>
  </article>;
}
