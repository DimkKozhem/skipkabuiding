import { Link } from "react-router-dom";
import {
  frameSourceLine,
  humanWhen,
  planFactFromZone,
  stageLabel,
  typeLabel,
  typeLead,
  uncertainLine,
  checkIsUncertain,
  zoneHeadline,
} from "../labels";
import { objectPath } from "../routes";
import type { ZoneDash } from "../types";
import { EvidencePreview } from "./EvidencePreview";
import { StatusBadge } from "./StatusBadge";

function SiteTrace({ ticks }: { ticks: NonNullable<ZoneDash["schedule_ticks"]> }) {
  return (
    <div className="site-trace" aria-hidden="true">
      <span className="site-trace-line" />
      {ticks.map((tick, index) => (
        <span
          key={`${tick.label}-${index}`}
          className={`site-trace-tick is-${tick.state}`}
          style={{ left: `${ticks.length === 1 ? 0 : (index / (ticks.length - 1)) * 100}%` }}
          title={tick.label}
        />
      ))}
    </div>
  );
}

function stageLine(zone: ZoneDash): string {
  const stage = stageLabel(zone.stage, zone.stage_label);
  return stage === "Этап не указан" ? "" : stage;
}

function statusCopy(zone: ZoneDash) {
  return zoneHeadline(zone);
}

function planFactLines(zone: ZoneDash): { plan: string; fact: string; delta: string; mismatch: boolean } | null {
  const metrics = planFactFromZone(zone.last_expected, zone.last_actual);
  const primary = metrics.find(item => item.mismatch) || metrics[0];
  if (!primary) return null;
  if (primary.expected === "—" && primary.observed === "—") return null;
  let delta = "";
  if (primary.mismatch && primary.expectedValue != null && primary.observedValue != null) {
    const d = primary.observedValue - primary.expectedValue;
    if (d !== 0) delta = `${d > 0 ? "+" : "−"}${Math.abs(d)}`;
  } else if (primary.mismatch) {
    delta = "Расхождение";
  }
  return {
    plan: primary.expected,
    fact: primary.observed,
    delta,
    mismatch: primary.mismatch,
  };
}

export function ZoneCard({ zone, href, layout = "row" }: { zone: ZoneDash; href: string; layout?: "feature" | "row" }) {
  const noFrame = zone.card_state === "no_frame" || !zone.preview_url;
  const stage = stageLine(zone);
  const status = statusCopy(zone);
  const pf = planFactLines(zone);
  const source = frameSourceLine(zone.cover_origin_label, zone.cover_camera_name);
  const extraBadges = (zone.badges || []).map(item => item.label).filter(label => label && label !== status.text);
  const when = zone.last_observed_at
    ? humanWhen(zone.last_observed_at)
    : (zone.freshness_label || "Нет кадра");

  return (
    <article className={`zone-card layout-${layout} state-${zone.card_state || "observation"}${status.tone === "attention" || status.tone === "critical" ? " has-signal" : ""}`}>
      <div className="zone-card-main">
        <div className="zone-card-cover">
          {noFrame ? (
            <div className="frame-missing zone-card-empty">
              <strong>Нет кадра</strong>
              <span>Источник ещё не передал изображение.</span>
            </div>
          ) : (
            <EvidencePreview
              src={zone.preview_url}
              alt={`Последний кадр: ${zone.name}`}
              presentation="cover"
            />
          )}
          {zone.prior_preview_url && !noFrame ? (
            <span className="zone-prior" aria-hidden="true">
              <img src={zone.prior_preview_url} alt="" />
              <span className="zone-split-caption"><em>Было</em><em>Стало</em></span>
            </span>
          ) : null}
        </div>
        <Link className="zone-card-body" to={href} title={`Открыть ${zone.name}`}>
          <div className="zone-card-top">
            <h3 title={zone.name}>{zone.name}</h3>
          </div>
          {zone.check ? (
            <div className={checkIsUncertain(zone.check.type) ? "check-lead is-uncertain" : "check-lead"}>
              <p className="check-title">{typeLabel(zone.check.type)}</p>
              <p className="check-why">{typeLead(zone.check.type)}</p>
            </div>
          ) : uncertainLine(zone) ? (
            <p className="check-why is-uncertain">{uncertainLine(zone)}</p>
          ) : (
            <StatusBadge tone={status.tone}>{status.text}</StatusBadge>
          )}
          {stage ? <p className="zone-card-stage">{stage}</p> : null}
          {(zone.schedule_ticks || []).length > 1 ? <SiteTrace ticks={zone.schedule_ticks || []} /> : null}
          {pf ? (
            <div className="zone-card-planfact">
              <div><span>План</span><strong>{pf.plan}</strong></div>
              <div><span>Факт</span><strong>{pf.fact}</strong></div>
              {pf.delta ? (
                <div className={pf.mismatch ? "is-gap" : ""}>
                  <span>Отклонение</span>
                  <strong>{pf.delta}</strong>
                </div>
              ) : null}
            </div>
          ) : null}
          {!noFrame && extraBadges.length ? (
            <p className={`zone-card-reason${status.tone === "attention" ? " is-attention" : ""}`}>
              {extraBadges.join(" · ")}
            </p>
          ) : null}
          {!noFrame ? (
            <p className="zone-card-meta">
              {[when, source].filter(Boolean).join(" · ")}
            </p>
          ) : null}
        </Link>
      </div>
      {zone.check ? (
        <div className="zone-card-actions">
          <Link className="btn" to={`${objectPath(zone.code, "signals")}?check=${encodeURIComponent(zone.check.id)}`}>Проверить сигнал</Link>
        </div>
      ) : null}
      {noFrame ? (
        <div className="zone-card-actions">
          <Link className="text-link" to={`${objectPath(zone.code, "sources")}?view=media#upload`} onClick={event => event.stopPropagation()}>
            Добавить фото
          </Link>
          <Link className="text-link" to={objectPath(zone.code, "sources")} onClick={event => event.stopPropagation()}>
            Проверить источник
          </Link>
        </div>
      ) : null}
    </article>
  );
}
