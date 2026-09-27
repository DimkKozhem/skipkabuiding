import { useState } from "react";
import { controlDateIso, fmtDotDate, plural, subjectFromExpected, typeLabel } from "../labels";
import type { AlertListItem } from "../types";

const PAGE = 5;

/** Прежние срезы наблюдения. Решения инспектора сюда не входят. */
export function SliceHistory({
  items,
  activeId,
  onOpen,
}: {
  items: AlertListItem[];
  activeId?: string | null;
  onOpen: (id: string) => void;
}) {
  const [count, setCount] = useState(0);
  if (!items.length) return null;
  const sorted = [...items].sort((a, b) => String(controlDateIso(b) || "").localeCompare(String(controlDateIso(a) || "")));
  const start = controlDateIso(sorted.at(-1) || sorted[0]);
  const end = controlDateIso(sorted[0]);
  const shown = sorted.slice(0, count);
  return (
    <section className="slice-history" aria-label="Прежние наблюдения">
      <h3>Прежние наблюдения</h3>
      <p className="caption">
        {sorted.length} {plural(sorted.length, "срез", "среза", "срезов")}
        {start && end ? ` с ${fmtDotDate(start)} по ${fmtDotDate(end)}` : ""}.
        Это прошлые наблюдения того же предмета, не смена статуса и не решение инспектора.
      </p>
      {count === 0 ? (
        <button type="button" className="text-link" onClick={() => setCount(PAGE)}>Показать историю</button>
      ) : (
        <>
          <ul className="slice-history-list">
            {shown.map(item => {
              const subject = subjectFromExpected(item.expected);
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    className={item.id === activeId ? "is-on" : ""}
                    onClick={() => onOpen(item.id)}
                  >
                    <time dateTime={controlDateIso(item) || undefined}>{fmtDotDate(controlDateIso(item))}</time>
                    <span>{subject || typeLabel(item.type)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
          {count < sorted.length ? (
            <button type="button" className="text-link" onClick={() => setCount(value => value + PAGE)}>
              Показать ещё
            </button>
          ) : (
            <p className="caption">Показаны все {sorted.length}.</p>
          )}
        </>
      )}
    </section>
  );
}
