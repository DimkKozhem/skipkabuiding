import { Link } from "react-router-dom";
import { controlDateIso, dynamicsCaption, fmtDotDate, isEarlierSlice, planFactCaption, planFactFromAlert, statusLabel, statusTone, subjectFromExpected, typeLabel } from "../labels";
import type { AlertDetail, AlertListItem } from "../types";
import { EvidencePreview } from "./EvidencePreview";
import { StatusBadge } from "./StatusBadge";
import { Icon } from "./Icon";
export function AlertCard({
  alert,
  variant = "compact",
  stageLabel,
  to,
  onSelect,
  active,
  all
}: {
  alert: AlertListItem | AlertDetail;
  variant?: "hero" | "compact" | "queue";
  stageLabel?: string;
  sequence?: {
    plan: string;
    fact: string;
  } | null;
  extra?: string;
  to?: string;
  onSelect?: () => void;
  active?: boolean;
  all?: AlertListItem[];
}) {
  const expected = alert.expected || ("deviation" in alert ? alert.deviation?.expected : undefined);
  const observed = alert.observed || ("deviation" in alert ? alert.deviation?.observed : undefined);
  const facts = planFactFromAlert(alert.type, expected, observed);
  const primary = facts[0];
  const subject = subjectFromExpected(expected) || (primary && primary.label !== "Показатель" ? primary.label : "");
  const earlier = all && isEarlierSlice(alert, all);
  const latest = alert.latest_evidence || ("evidence" in alert ? alert.evidence.at(-1) : undefined);
  const readable = (value: unknown) => {
    if (value == null || typeof value === "object") return "";
    const text = String(value).trim();
    if (!text || text === "[object Object]") return "";
    if (/^[a-z0-9_]+(,[a-z0-9_]+)*$/.test(text)) return "";
    return text;
  };
  const queue = variant === "queue";
  const when = fmtDotDate(controlDateIso(alert));
  const stage = queue ? "" : readable(stageLabel);
  const dynamics = !queue && alert.type === "no_dynamics" ? readable(dynamicsCaption(observed)) : "";
  const title = subject || typeLabel(alert.type);
  const kind = subject ? typeLabel(alert.type) : "";
  const comparison = primary ? `${planFactCaption(primary, "plan")} → ${planFactCaption(primary, "fact")}` : "";
  const body = <>
    {queue ? null : <EvidencePreview src={latest?.media_url} poster={latest?.viz_url} alt="" />}
    <div className="signal-description">
      <span className="signal-object">{alert.zone_name || "Объект"}{earlier && <span className="earlier-label"> · ранний срез</span>}</span>
      <span className="alert-card-title">{title}</span>
      <span className="caption">{[when, kind, stage, dynamics].filter(Boolean).join(" · ")}</span>
    </div>
    {queue ? null : <div className="signal-comparison">
      {comparison && !comparison.includes("Показатель") ? <><span className="eyebrow">План → факт</span><strong>{comparison}</strong></> : null}
      <StatusBadge tone={statusTone(alert.status)}>{statusLabel(alert.status, alert.status_label)}</StatusBadge>
    </div>}
    {queue ? null : <Icon name="arrow" />}
  </>;
  const className = `alert-card ${variant}${active ? " active" : ""}`;
  return onSelect ? <button type="button" className={className} onClick={onSelect} aria-pressed={active}>{body}</button> : <Link className={className} to={to || `/signals/${alert.id}`}>{body}</Link>;
}
