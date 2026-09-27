import type { TimelineRow } from "../types";
import { factNumber, fmtDay, planFloorsFromRow, typeLabel } from "../labels";

function daySignals(row: TimelineRow): string {
  const seen = new Set<string>();
  const labels: string[] = [];
  for (const item of row.alerts || []) {
    if (!item.type || seen.has(item.type)) continue;
    seen.add(item.type);
    labels.push(typeLabel(item.type));
  }
  return labels.join(", ") || "—";
}

export function PlanFactTable({ rows }: { rows: TimelineRow[] }) {
  if (!rows.length) return null;
  return (
    <div className="card">
      <h2>План / факт / динамика</h2>
      <p className="caption">Этажи по контрольным датам</p>
      <table>
        <thead>
          <tr>
            <th>дата</th>
            <th>этап</th>
            <th>план</th>
            <th>факт</th>
            <th>сигналы дня</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const plan = planFloorsFromRow(row);
            const fact = factNumber(row.actual, "floors");
            return (
              <tr key={row.date}>
                <td>{fmtDay(row.date)}</td>
                <td>{row.stage_label || row.stage || "—"}</td>
                <td>{plan}</td>
                <td>{fact}</td>
                <td>{daySignals(row)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
