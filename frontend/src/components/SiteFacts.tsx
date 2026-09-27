import { equipmentInventory, equipmentLabel, siteChangeLines } from "../labels";
import type { ActualState, SiteChange } from "../types";

export function SiteFacts({ actual, change }: { actual?: ActualState | null; change?: SiteChange | null }) {
  const gear = equipmentInventory(actual);
  const lines = siteChangeLines(change, actual);
  return (
    <section className="site-facts">
      <h2>Техника и изменения</h2>
      <p className="caption">Состав и количество по детекциям кадра. Сравнение — с прошлым сопоставимым наблюдением той же камеры.</p>
      {gear.length ? (
        <ul className="fact-list">
          {gear.map(item => (
            <li key={item.key}>
              <span>{equipmentLabel(item.key)}</span>
              <strong>{item.count}</strong>
            </li>
          ))}
        </ul>
      ) : (
        <p>На кадре техника не обнаружена.</p>
      )}
      <h3>Что изменилось</h3>
      {lines.map(line => <p key={line}>{line}</p>)}
    </section>
  );
}
