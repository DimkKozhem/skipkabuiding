import { useEffect, useRef, useState } from "react";
import { factNumber, fmtDay, markersByControlDate, planFloorsFromRow, typeLabel } from "../labels";
import type { AlertListItem, Observation, TimelineRow } from "../types";
import { EvidenceViewer } from "./EvidenceViewer";
export function FloorsRail({
  rows,
  alerts,
  observations,
  showFrame = true
}: {
  rows: TimelineRow[];
  alerts?: AlertListItem[];
  observations?: Observation[];
  showFrame?: boolean;
}) {
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const plot = useRef<HTMLDivElement>(null);
  const [plotWidth, setPlotWidth] = useState(620);
  useEffect(() => {
    if (!plot.current) return;
    const observer = new ResizeObserver(([entry]) => setPlotWidth(entry.contentRect.width));
    observer.observe(plot.current);
    return () => observer.disconnect();
  }, [rows.length]);
  const ordered = [...rows].sort((a, b) => a.date.localeCompare(b.date));
  if (!ordered.length) return <div className="empty-state">Пока нет хронологии наблюдений.</div>;
  const index = Math.max(0, selectedDate ? ordered.findIndex(row => row.date === selectedDate) : ordered.length - 1);
  const selected = ordered[index];
  const plans = ordered.map(planFloorsFromRow);
  const facts = ordered.map(row => factNumber(row.actual, "floors"));
  const hasFloors = [...plans, ...facts].some(value => value != null);
  const maximum = Math.max(1, ...[...plans, ...facts].filter((value): value is number => value != null));
  const minimumWidth = Math.max(620, ordered.length * 100);
  const w = Math.max(minimumWidth, plotWidth);
  const x = (i: number) => (i + .5) * w / ordered.length;
  const y = (n: number) => 154 - n / maximum * 116;
  const path = (values: Array<number | null>) => values.map((value, i) => value == null ? "" : `${i === 0 || values[i - 1] == null ? "M" : "L"}${x(i)},${y(value)}`).join(" ");
  const marks = markersByControlDate(alerts);
  const markers = marks[selected.date] || [...new Set((selected.alerts || []).map(alert => alert.type))];
  const shots = (observations || []).filter(obs => obs.timestamp.slice(0, 10) === selected.date);
  return <div className="progress-workspace">
    <div className="progress-head">
      <div>
        <span className="eyebrow">{hasFloors ? "Этажность на контрольных датах" : "Контрольные наблюдения"}</span>
        <h3>{fmtDay(ordered[0].date)} — {fmtDay(ordered.at(-1)?.date)}</h3>
      </div>
      {hasFloors && <div className="chart-legend">
        <span className="legend-plan">План</span>
        <span className="legend-fact">Факт</span>
      </div>}
    </div>
    <div className="progress-scroll">
      <div ref={plot} className="progress-plot" style={{
        minWidth: minimumWidth
      }}>
        {hasFloors && <svg viewBox={`0 0 ${w} 180`} role="img" aria-label="Сравнение этажности по контрольным датам. Значения доступны в кнопках под графиком.">
          {[0, .5, 1].map(t => <g key={t}>
            <line x1="28" x2={w - 28} y1={y(t * maximum)} y2={y(t * maximum)} className="chart-grid" />
            <text x="0" y={y(t * maximum) + 4} className="chart-axis">{Number((maximum * t).toFixed(1))}</text>
          </g>)}
          <line x1={x(index)} x2={x(index)} y1="16" y2="164" className="chart-selection" />
          <path d={path(plans)} className="chart-plan" />
          <path d={path(facts)} className="chart-fact" />
          {ordered.map((row, i) => <g key={row.date}>{plans[i] != null && <circle cx={x(i)} cy={y(plans[i]!)} r={i === index ? 5 : 3} className="point-plan" />}{facts[i] != null && <circle cx={x(i)} cy={y(facts[i]!)} r={i === index ? 6 : 4} className="point-fact" />}</g>)}
        </svg>}
        <div className="date-track">{ordered.map((row, i) => <button type="button" key={row.date} aria-pressed={i === index} onClick={() => setSelectedDate(row.date)} className={i === index ? "active" : ""}>
            <strong>{fmtDay(row.date)}</strong>
            <span>{hasFloors ? `План ${plans[i] ?? "—"} · факт ${facts[i] ?? "—"}` : row.stage_label || "Наблюдение"}</span>
          </button>)}</div>
      </div>
    </div>
    {showFrame && <div className="selected-observation">
      <div className="section-head">
        <h3>Наблюдение · {fmtDay(selected.date)}</h3>
        <span className="caption">{markers.length ? markers.map(typeLabel).join(" · ") : "Сигналов на эту дату нет"}</span>
      </div>
      <EvidenceViewer key={selected.date} items={shots} empty="На эту дату кадр недоступен." />
    </div>}
  </div>;
}
export function FloorSequence({
  rows
}: {
  rows: TimelineRow[];
}) {
  return <div className="comparison-sequence">
    <div>
      <span>План</span>
      <b>{rows.map(row => planFloorsFromRow(row) ?? "—").join(" → ")}</b>
    </div>
    <div>
      <span>Факт</span>
      <b>{rows.map(row => factNumber(row.actual, "floors") ?? "—").join(" → ")}</b>
    </div>
  </div>;
}
export function TimelineTrack(props: {
  rows: TimelineRow[];
  alerts?: AlertListItem[];
  observations?: Observation[];
}) {
  return <FloorsRail {...props} />;
}
