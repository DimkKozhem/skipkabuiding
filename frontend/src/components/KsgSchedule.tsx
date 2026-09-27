import { fmtDotDate, ksgPlanPhrase, stageLabel } from "../labels";
import type { KsgRow } from "../types";

export function KsgSchedule({ rows }: { rows?: KsgRow[] | null }) {
  if (!rows?.length) return null;
  return (
    <section className="section">
      <div className="section-head">
        <h2>Календарь КСГ</h2>
        <span className="caption">План работ по контрольным датам, не юридический график</span>
      </div>
      <div className="table-scroll">
        <table className="object-table">
          <thead>
            <tr>
              <th>Срок</th>
              <th>Этап</th>
              <th>План</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr key={`${row.start_date}-${row.stage || ""}`}>
                <td className="numeric">
                  {fmtDotDate(row.start_date)}
                  {row.end_date && row.end_date !== row.start_date ? ` — ${fmtDotDate(row.end_date)}` : ""}
                </td>
                <td>{stageLabel(row.stage, row.stage_label)}</td>
                <td>{ksgPlanPhrase(row.expected)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
