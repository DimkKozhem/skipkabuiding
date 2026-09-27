import {
  countPhrase, EQUIPMENT_RU, equipmentNoun,
  type ComparisonMode, type PlanFactItem,
} from "../labels";

function Metric({ item, side }: { item: PlanFactItem; side: "expected" | "observed" }) {
  const value = side === "expected" ? item.expectedValue : item.observedValue;
  const text = item[side];
  const unit = value == null ? "" : EQUIPMENT_RU[item.key]
    ? equipmentNoun(item.key, value)
    : text.replace(/^[≥≤]?\s*-?\d+(?:[.,]\d+)?\s*/, "");
  const max = Math.max(item.expectedValue ?? 0, item.observedValue ?? 0, 1);

  return (
    <div className={`comparison-metric ${side}`}>
      <span className="eyebrow">{side === "expected" ? "План" : "Факт"}</span>
      <div className="metric-number">
        {value != null ? (
          <>{text.startsWith("≥") && <small>≥</small>}{value}</>
        ) : <span className="metric-text">{text}</span>}
      </div>
      <span className="metric-unit">{unit || item.label.toLocaleLowerCase("ru")}</span>
      {value != null && (
        <div className="measure-bar" aria-hidden="true">
          <span style={{ width: `${Math.max(0, value) / max * 100}%` }} />
        </div>
      )}
    </div>
  );
}

type ComparisonProps = {
  items: PlanFactItem[];
  mode?: ComparisonMode;
  sequence?: { plan: string; fact: string } | null;
  limitation?: string;
  caption?: string;
};

export function PlanFactComparison({
  items, mode = "expected_observed", sequence, limitation, caption,
}: ComparisonProps) {
  const primary = items.find(item => item.mismatch) || items[0];
  if (!primary) {
    return <div className="empty-state compact-state">Нет сопоставимых показателей плана и факта.</div>;
  }

  const rest = items.filter(item => item !== primary);
  const known = primary.expected !== "—" && primary.observed !== "—";
  const delta = primary.expectedValue != null && primary.observedValue != null
    ? primary.observedValue - primary.expectedValue : null;
  const difference = delta == null ? "" : EQUIPMENT_RU[primary.key]
    ? `${Math.abs(delta)} ${equipmentNoun(primary.key, Math.abs(delta))}`
    : countPhrase(primary.key, Math.abs(delta));
  const headline = !known ? "Нет данных"
    : delta != null && primary.mismatch ? `${delta > 0 ? "+" : "−"}${difference}`
    : primary.mismatch ? "Расхождение" : "В пределах плана";

  return (
    <div className={`planfact ${primary.mismatch && known ? "is-gap" : "is-match"}`}>
      <div className="comparison-heading">
        <span>{primary.label}</span>
        <span className="eyebrow">
          {mode === "expected_observed" ? "Состав на площадке" : "По графику строительства"}
        </span>
      </div>
      <div className="comparison-values">
        <Metric item={primary} side="expected" />
        <Metric item={primary} side="observed" />
      </div>
      <div className={`comparison-delta ${primary.mismatch && known ? "attention-text" : ""}`}>
        <strong>{headline}</strong>
        <span>
          {!known ? "Нужно наблюдение для сравнения"
            : primary.mismatch ? "относительно плана · требуется проверка"
            : "по сопоставимому показателю"}
        </span>
      </div>
      {rest.length > 0 && (
        <div className="comparison-rest">
          {rest.map(item => (
            <div key={item.key}>
              <span>{item.label}</span><span>{item.expected}</span>
              <strong className={item.mismatch ? "attention-text" : ""}>{item.observed}</strong>
            </div>
          ))}
        </div>
      )}
      {sequence && (
        <div className="comparison-sequence">
          <div><span>План</span><b>{sequence.plan}</b></div>
          <div><span>Факт</span><b>{sequence.fact}</b></div>
        </div>
      )}
      {(caption || limitation) && (
        <div className="comparison-note">
          {caption && <p>{caption}</p>}
          {limitation && <p>{limitation}</p>}
        </div>
      )}
    </div>
  );
}
