/** Канонические пути UI. Backend Zone ↔ UI «объект», id = zoneCode. */

export const OBJECT_SECTIONS = [
  "overview",
  "progress",
  "schedule",
  "sources",
  "history",
  "signals",
  "notes",
  "settings",
] as const;

export type ObjectSection = (typeof OBJECT_SECTIONS)[number];

/** Вкладки рабочего пространства объекта (основная навигация). */
export const OBJECT_TABS: { section: ObjectSection; label: string }[] = [
  { section: "overview", label: "Обзор" },
  { section: "progress", label: "План и выполнение" },
  { section: "schedule", label: "График" },
  { section: "history", label: "Хронология" },
  { section: "signals", label: "Сигналы" },
  { section: "sources", label: "Источники" },
  { section: "notes", label: "Заметки" },
  { section: "settings", label: "Настройки" },
];

/** Старые ?tab= / section → канонический section. */
const TAB_ALIASES: Record<string, ObjectSection> = {
  state: "overview",
  overview: "overview",
  progress: "progress",
  schedule: "schedule",
  sources: "sources",
  media: "sources",
  cameras: "sources",
  history: "history",
  observations: "history",
  evidence: "history",
  timeline: "history",
  signals: "signals",
  notes: "notes",
  settings: "settings",
};

export function normalizeObjectSection(raw: string | null | undefined): ObjectSection {
  if (!raw) return "overview";
  return TAB_ALIASES[raw] || (OBJECT_SECTIONS.includes(raw as ObjectSection) ? (raw as ObjectSection) : "overview");
}

export function objectsListPath(query?: string) {
  return query ? `/objects?${query.replace(/^\?/, "")}` : "/objects";
}

export function objectPath(zoneCode: string, section: ObjectSection = "overview") {
  if (section === "overview") return `/objects/${zoneCode}`;
  return `/objects/${zoneCode}/${section}`;
}

export function isObjectWorkspacePath(pathname: string): { zoneCode: string; section: ObjectSection } | null {
  const match = pathname.match(/^\/objects\/([^/]+)(?:\/([^/]+))?\/?$/);
  if (!match) return null;
  const zoneCode = match[1];
  if (zoneCode === "new") return null;
  return { zoneCode, section: normalizeObjectSection(match[2]) };
}

/** @deprecated используйте OBJECT_TABS; оставлено для совместимости импортов. */
export const OBJECT_NAV = OBJECT_TABS.map(item => ({
  ...item,
  icon:
    item.section === "overview" ? "overview"
    : item.section === "sources" ? "camera"
    : item.section === "progress" ? "signal"
    : item.section === "history" ? "clock"
    : "signal",
}));

/** Старый section в адресе → канонический путь и локальная вкладка. */
export const LEGACY_OBJECT_SECTION: Record<string, { section: ObjectSection; view?: string }> = {
  media: { section: "sources", view: "media" },
  cameras: { section: "sources" },
  observations: { section: "history" },
  evidence: { section: "history" },
  timeline: { section: "history" },
  state: { section: "overview" },
};

export const OBJECTS_LIST_STATE_KEY = "sitewatch.objects.list";
export const OBJECTS_SCROLL_KEY = "sitewatch.objects.scroll";
