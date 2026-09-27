import { Link, NavLink } from "react-router-dom";
import type { Tone } from "../labels";
import { OBJECT_TABS, objectPath, type ObjectSection } from "../routes";
import { Icon } from "./Icon";
import { StatusBadge } from "./StatusBadge";

/** Шапка объекта + вкладки. Навигация разделов только здесь, не в sidebar. */
export function ObjectWorkspaceHeader({
  zoneCode,
  name,
  section,
  status,
  updated,
  kind,
  place,
}: {
  zoneCode: string;
  name: string;
  section: ObjectSection;
  status: { text: string; tone: Tone };
  updated: string;
  kind?: string;
  place?: string;
}) {
  return (
    <header className="object-workspace-header">
      <div className="object-workspace-top">
        <Link className="context-back" to="/objects">
          <Icon name="arrow" />
          Все объекты
        </Link>
      </div>
      <div className="object-workspace-title">
        <div>
          <h1>{name}</h1>
          <p className="object-freshness">
            {[kind, place, updated !== "Нет обновлений" ? `кадр ${updated}` : "кадра ещё нет"].filter(Boolean).join(" · ")}
          </p>
        </div>
        <div className="object-workspace-meta">
          <StatusBadge tone={status.tone}>{status.text}</StatusBadge>
        </div>
      </div>
      <nav className="object-tabs" aria-label="Разделы объекта">
          {OBJECT_TABS.map(tab => {
            const to = objectPath(zoneCode, tab.section);
            const active = section === tab.section;
            return (
              <NavLink
                key={tab.section}
                to={to}
                end={tab.section === "overview"}
                className={({ isActive }) => (isActive || active ? "active" : undefined)}
                aria-current={active ? "page" : undefined}
              >
                {tab.label}
              </NavLink>
            );
          })}
        </nav>
    </header>
  );
}
