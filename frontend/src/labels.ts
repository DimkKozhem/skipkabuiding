import type { ActualState, AlertListItem, ExpectedState, SiteChange, TimelineRow, ZoneDash } from "./types";

export const TYPE_RU: Record<string, string> = {
  missing_element: "Возможное отсутствие ожидаемого элемента",
  schedule_delay: "Возможное отставание этапа",
  no_dynamics: "Нет наблюдаемой динамики",
  missing_equipment: "Признаки отсутствия техники",
  unexpected_equipment: "Нетипичная техника для этапа",
  insufficient_evidence: "Требуются дополнительные данные",
  incomparable: "План и наблюдение несопоставимы",
  measurement_unimplemented: "Метод измерения отсутствует",
  needs_capture_or_calibration: "Нужна съёмка или калибровка",
  no_observation_after: "Нет нового наблюдения после последнего кадра",
  model_candidate: "Предложение модели на проверку",
};

export const TYPE_LEAD: Record<string, string> = {
  missing_element: "Наблюдаемый конструктив не совпадает с ожидаемым на контрольную дату. Требуется проверка.",
  schedule_delay: "Выявлены признаки отставания от графика этапов. Требуется проверка.",
  no_dynamics: "Выявлены признаки отсутствия строительной динамики. Требуется проверка.",
  missing_equipment: "По кадру не видно требуемое количество техники. Это не доказательство отсутствия на площадке.",
  unexpected_equipment: "Наблюдается техника, не типичная для текущего этапа. Требуется проверка.",
  insufficient_evidence: "По имеющимся кадрам нельзя уверенно судить о ситуации. Нужны дополнительные данные.",
  incomparable: "Показатель плана и факт работы несопоставимы по смыслу или единице.",
  measurement_unimplemented: "Для планового показателя нет реализованного метода измерения.",
  needs_capture_or_calibration: "Нужна дополнительная съёмка целевого объекта или калибровка камеры.",
  no_observation_after: "После последнего кадра серии нет нового наблюдения на дату оценки.",
  model_candidate: "Модель предложила объекты на кадре. Это не отставание от графика и не подтверждённый факт. Требуется проверка.",
};

export const EQUIPMENT_RU: Record<string, { one: string; few: string; many: string }> = {
  excavator: { one: "экскаватор", few: "экскаватора", many: "экскаваторов" },
  dump_truck: { one: "самосвал", few: "самосвала", many: "самосвалов" },
  roller: { one: "каток", few: "катка", many: "катков" },
  crane_manipulator: { one: "кран-манипулятор", few: "кран-манипулятора", many: "кранов-манипуляторов" },
  concrete_mixer: { one: "бетоносмеситель", few: "бетоносмесителя", many: "бетоносмесителей" },
  bulldozer: { one: "бульдозер", few: "бульдозера", many: "бульдозеров" },
  truck: { one: "грузовик", few: "грузовика", many: "грузовиков" },
  mobile_crane: { one: "кран", few: "крана", many: "кранов" },
  tower_crane: { one: "башенный кран", few: "башенных крана", many: "башенных кранов" },
  loader: { one: "погрузчик", few: "погрузчика", many: "погрузчиков" },
  concrete_pump: { one: "бетононасос", few: "бетононасоса", many: "бетононасосов" },
};

function classKey(kind: string): string {
  return kind.trim().toLowerCase().replace(/[\s-]+/g, "_");
}

export const ELEMENT_RU: Record<string, string> = {
  foundation: "Фундамент",
  columns: "Колонны",
  column: "Колонны",
  walls: "Стены",
  wall: "Стены",
  slabs: "Плиты",
  slab: "Плиты",
  floors: "Этажи",
  windows: "Окна",
  window: "Окна",
  roof: "Кровля",
  facade: "Фасад",
  structural_levels: "Этажи",
  dividing_line_m: "Длина разделителя",
  scaffolding: "Леса",
  scaffold: "Леса",
};

/** Внутренние индикаторы наблюдения → предмет проверки. */
export const INDICATOR_RU: Record<string, string> = {
  foundation_visible: "Фундамент",
  windows_visible: "Окна",
  roof_visible: "Кровля",
  facade_visible: "Фасад",
  visible_floor_levels: "Этажность",
  structural_levels: "Этажи",
  divider_stage_sign: "Разделитель",
  dividing_line_m: "Длина разделителя",
};

export const SOURCE_RU: Record<string, string> = {
  annotation: "Разметка наблюдения",
  yolo: "Детектор",
  photo: "Фото",
  video: "Видео",
};

export const STAGE_RU: Record<string, string> = {
  excavation: "Разработка котлована",
  foundation: "Устройство фундамента",
  framing: "Каркас",
  superstructure: "Надземная часть",
  facade: "Фасад",
  finishing: "Отделка",
};

export const STATUS_FALLBACK: Record<string, string> = {
  open: "Требует проверки",
  needs_more_data: "Недостаточно данных",
  confirmed: "Подтверждено",
  rejected: "Отклонено",
};

export const DECISION_ACTION: Record<string, string> = {
  confirmed: "Подтвердить",
  rejected: "Отклонить",
  needs_more_data: "Запросить данные",
};

export const SEVERITY_RU: Record<string, string> = {
  info: "Информация",
  warning: "Внимание",
  critical: "Критично",
  ok: "Норма",
};

export const DEMO_ZONE_ORDER = ["zone_a", "zone_b", "building_01"];
export const STATUS_ORDER = ["open", "needs_more_data", "confirmed", "rejected"];
export const DECISION_STATUSES = ["confirmed", "rejected", "needs_more_data"] as const;
export const BUILDING_FACT_KEYS = ["floors", "slabs"] as const;

const HIDDEN_FACT_KEYS = new Set([
  "schedule_progress",
  "visual_change",
  "change_score",
  "same_camera",
  "camera_code",
  "n_states",
  "stable_elements",
  "observation_period_days",
  "indicator_id",
  "schedule_row_id",
  "method",
  "evidence_ids",
  "certainty",
  "coverage",
  "limitations",
  "unit",
  "confirms",
  "value",
]);

export type PlanFactItem = {
  key: string;
  label: string;
  expected: string;
  observed: string;
  mismatch: boolean;
  expectedValue?: number | null;
  observedValue?: number | null;
  expectedSecondary?: string;
  observedSecondary?: string;
};

export type Tone = "ok" | "attention" | "critical" | "info" | "muted";
export type ZoneUiStatus = "normal" | "attention" | "insufficient";
export type ComparisonMode = "expected_observed" | "plan_fact" | "dynamics";

export function typeLabel(kind: string): string {
  return TYPE_RU[kind] || "Требуется проверка";
}

export function typeLead(kind: string): string {
  return TYPE_LEAD[kind] || "Ситуация требует проверки инспектором.";
}

/** Нейтральное «не могу сопоставить»: не охра и не риск. */
export function uncertainLine(zone: {
  card_state?: string;
  freshness_label?: string;
  rank_reason?: string;
  preview_url?: string | null;
}): string {
  if (!zone.preview_url || zone.card_state === "no_frame") return "Недостаточно сопоставимых кадров";
  // stale = кадр старше порога по календарю витрины, не «плохое качество изображения».
  if (zone.card_state === "stale") return zone.rank_reason || zone.freshness_label || "Кадр устарел";
  return "";
}

export function checkIsUncertain(type?: string | null): boolean {
  return type === "insufficient_evidence";
}

export function statusLabel(status: string, fromApi?: string): string {
  if (fromApi && fromApi !== status) return fromApi;
  return STATUS_FALLBACK[status] || "Требуется проверка";
}

export function decisionAction(status: string): string {
  return DECISION_ACTION[status] || statusLabel(status);
}

export function severityLabel(severity: string): string {
  return SEVERITY_RU[severity] || "Внимание";
}

export function humanWhen(iso?: string | null): string {
  const date = parseIso(iso);
  if (!date) return "Нет данных";
  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startThat = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const dayDiff = Math.round((startToday.getTime() - startThat.getTime()) / 86400000);
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  const time = `${hh}:${mm}`;
  if (dayDiff === 0) return `Сегодня, ${time}`;
  if (dayDiff === 1) return `Вчера, ${time}`;
  const months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
  return `${date.getDate()} ${months[date.getMonth()]}${date.getFullYear() !== now.getFullYear() ? ` ${date.getFullYear()}` : ""}, ${time}`;
}

export function humanDay(iso?: string | null): string {
  const date = parseIso(iso);
  if (!date) return "—";
  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startThat = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const dayDiff = Math.round((startToday.getTime() - startThat.getTime()) / 86400000);
  if (dayDiff === 0) return "Сегодня";
  if (dayDiff === 1) return "Вчера";
  const months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
  return `${date.getDate()} ${months[date.getMonth()]}${date.getFullYear() !== now.getFullYear() ? ` ${date.getFullYear()}` : ""}`;
}

export function statusTone(status: string): Tone {
  if (status === "confirmed") return "ok";
  if (status === "rejected") return "muted";
  if (status === "needs_more_data") return "info";
  if (status === "open") return "attention";
  return "muted";
}

export function severityTone(severity: string): Tone {
  if (severity === "critical") return "critical";
  if (severity === "warning") return "attention";
  if (severity === "info") return "info";
  return "muted";
}

export function orderedZoneCodes(codes: string[]): string[] {
  const ordered = DEMO_ZONE_ORDER.filter((code) => codes.includes(code));
  ordered.push(...codes.filter((code) => !ordered.includes(code)));
  return ordered;
}

export function fmtValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "да" : "нет";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return String(value);
}

export function parseIso(iso?: string | null): Date | null {
  if (!iso) return null;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function fmtDay(iso?: string | null): string {
  const date = parseIso(iso) || (iso ? new Date(`${String(iso).slice(0, 10)}T00:00:00`) : null);
  if (!date || Number.isNaN(date.getTime())) return "—";
  const dd = String(date.getDate()).padStart(2, "0");
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  return `${dd}.${mm}`;
}

export function fmtDotDate(iso?: string | null): string {
  const date = parseIso(iso) || (iso ? new Date(`${String(iso).slice(0, 10)}T00:00:00`) : null);
  if (!date || Number.isNaN(date.getTime())) return "—";
  const dd = String(date.getDate()).padStart(2, "0");
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  return `${dd}.${mm}.${date.getFullYear()}`;
}

export function fmtDotDateTime(iso?: string | null): string {
  const date = parseIso(iso);
  if (!date) return fmtDotDate(iso);
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${fmtDotDate(iso)} ${hh}:${mm}`;
}

export function fmtTime(iso?: string | null): string {
  const date = parseIso(iso);
  if (!date) return "";
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

export function plural(n: number, one: string, few: string, many: string): string {
  const abs = Math.abs(n) % 100;
  const last = abs % 10;
  if (abs > 10 && abs < 20) return many;
  if (last === 1) return one;
  if (last >= 2 && last <= 4) return few;
  return many;
}

export function equipmentNoun(kind: string, count: number): string {
  const forms = EQUIPMENT_RU[classKey(kind)];
  if (!forms) return plural(count, "единица", "единицы", "единиц");
  return plural(count, forms.one, forms.few, forms.many);
}

export function equipmentLabel(kind: string): string {
  const forms = EQUIPMENT_RU[classKey(kind)];
  if (!forms) return "Техника";
  return forms.one.charAt(0).toUpperCase() + forms.one.slice(1);
}

export function elementLabel(kind: string): string {
  const key = classKey(kind);
  return ELEMENT_RU[key] || INDICATOR_RU[key] || "Показатель";
}

const CODE_TOKEN = /^[a-z][a-z0-9_]*$/;

/** Строка для инспектора. Внутренний код не показывается как есть. */
export function humanToken(value: unknown): string {
  if (value == null || value === "") return "Не определено";
  if (typeof value === "boolean") return value ? "есть признак" : "признака нет";
  if (typeof value === "number") return fmtValue(value);
  const text = String(value).trim();
  const key = classKey(text);
  if (INDICATOR_RU[key]) return INDICATOR_RU[key];
  if (ELEMENT_RU[key]) return ELEMENT_RU[key];
  if (EQUIPMENT_RU[key]) return equipmentLabel(key);
  if (STAGE_RU[key]) return STAGE_RU[key];
  if (TYPE_RU[key]) return TYPE_RU[key];
  if (CODE_TOKEN.test(text)) return "Показатель";
  return text;
}

export function subjectFromExpected(expected?: Record<string, unknown> | null): string {
  const id = classKey(String(expected?.indicator_id || ""));
  if (id && (INDICATOR_RU[id] || ELEMENT_RU[id])) return INDICATOR_RU[id] || ELEMENT_RU[id];
  const confirms = String(expected?.confirms || "").trim();
  if (confirms && !CODE_TOKEN.test(confirms)) {
    return confirms.charAt(0).toUpperCase() + confirms.slice(1);
  }
  return "";
}

export function inspectorDisplay(name?: string | null): string {
  const trimmed = (name || "").trim();
  if (!trimmed || /^inspector$/i.test(trimmed)) return "";
  return trimmed;
}

export function noteAuthorLabel(author?: string | null): string {
  const name = (author || "").trim();
  if (/^(sitewatch|system)$/i.test(name)) return "Система";
  if (!name || /^inspector$/i.test(name)) return "Инспектор";
  return name;
}

export function detectionKindLabel(kind: string): string {
  const key = classKey(kind);
  if (EQUIPMENT_RU[key]) return equipmentLabel(key);
  if (ELEMENT_RU[key]) return ELEMENT_RU[key];
  return "Техника";
}

export function sourceLabel(source?: string | null): string {
  if (!source) return "Источник не указан";
  return SOURCE_RU[source] || "Источник";
}

export function stageLabel(stage?: string | null, fallback?: string | null): string {
  if (fallback && !CODE_TOKEN.test(fallback.trim())) return fallback;
  if (!stage) return "Этап не указан";
  return STAGE_RU[stage] || (CODE_TOKEN.test(stage) ? "Этап" : stage);
}

export function expectedValues(expected: Record<string, unknown> | null | undefined): Record<string, unknown> {
  if (!expected) return {};
  const nested = expected.expected;
  if (nested && typeof nested === "object" && !Array.isArray(nested)) {
    return nested as Record<string, unknown>;
  }
  return expected;
}

function elementStat(actual: ActualState, key: string) {
  return actual.elements?.[key];
}

/** Этажность. 0 / нулевая уверенность без structural_levels — неизвестно, не «0 этажей». */
export function factNumber(actual: ActualState | null | undefined, key: string): number | null {
  if (!actual) return null;
  if (key === "floors") {
    const scene = actual.scene_attributes || {};
    // Proposed, disputed, or legacy numbers are not the object floor count.
    if (scene.floors_status != null && scene.floors_status !== "proven") return null;
    const storedStat = elementStat(actual, "floors");
    const stored = typeof storedStat?.count === "number" ? storedStat.count : null;
    const storedConf = typeof storedStat?.max_confidence === "number" ? storedStat.max_confidence : null;
    if (stored != null && stored > 0) return stored;
    const levels = numeric(scene.structural_levels);
    const slabs = elementStat(actual, "slabs");
    const slabCount = typeof slabs?.count === "number" ? slabs.count : null;
    const slabConfidence = typeof slabs?.max_confidence === "number" ? slabs.max_confidence : null;
    const slabDump = stored === 0 && levels != null && slabCount != null && levels === slabCount && slabConfidence === 0;
    if (slabDump) return null;
    if (typeof scene.structural_levels === "number") return scene.structural_levels;
    if (typeof scene.floors === "number" && scene.floors > 0) return scene.floors;
    // count=0 без подтверждения — нет наблюдения этажности, не факт «ноль этажей».
    if (stored === 0 && (storedConf == null || storedConf <= 0) && levels == null) return null;
    return stored != null && stored > 0 ? stored : null;
  }
  const stat = elementStat(actual, key);
  if (!stat) return null;
  if (typeof stat.count === "number") return stat.count;
  return null;
}

export function confidentFactNumber(actual: ActualState | null | undefined, key: string): number | null {
  const n = factNumber(actual, key);
  if (!n) return null;
  const confidence = actual?.elements?.[key]?.max_confidence;
  if (confidence === 0) return null;
  return n;
}

/** Убирает технический код сценария из подписи. Имена сущностей не подменяет. */
export function publicText(value?: string | null): string {
  return (value || "")
    .replace(/сценарий\s+housing_16/gi, "")
    .replace(/\bhousing_16\b/gi, "")
    .replace(/\s{2,}/g, " ")
    .replace(/\s*[,·]\s*[,·]\s*/g, ", ")
    .replace(/^[\s,·.-]+|[\s,·.-]+$/g, "")
    .trim();
}

/** Подпись источника: не дублировать «Камера · Камера котлована». */
export function frameSourceLine(origin?: string | null, camera?: string | null): string {
  const place = publicText(origin);
  const name = publicText(camera);
  if (!place) return name;
  if (!name) return place;
  const placeKey = place.toLocaleLowerCase("ru");
  const nameKey = name.toLocaleLowerCase("ru");
  if (nameKey.includes(placeKey) || placeKey.includes(nameKey)) return nameKey.length >= placeKey.length ? name : place;
  return `${place} · ${name}`;
}

export function zoneHeadline(
  zone: {
    card_state?: string;
    badge_label?: string | null;
    rank_reason?: string | null;
    stale?: boolean;
    preview_url?: string | null;
    last_expected?: unknown;
    open_alerts?: number;
    alert_counts?: Record<string, number>;
    last_actual?: ActualState | null;
  } | null | undefined,
  options?: { hasFrame?: boolean },
): { text: string; tone: Tone } {
  if (!zone) return { text: "Недостаточно данных", tone: "info" };
  const hasFrame = options?.hasFrame ?? Boolean(zone.preview_url);
  if (!hasFrame || zone.card_state === "no_frame") return { text: "Нет свежих данных", tone: "info" };
  if (zone.card_state === "confirmed") {
    return { text: zone.badge_label || zone.rank_reason || "Подтверждено", tone: "attention" };
  }
  if (zone.card_state === "possible_issue" || zone.card_state === "needs_check" || zone.badge_label) {
    return { text: zone.badge_label || zone.rank_reason || "Требует внимания", tone: "attention" };
  }
  if (zone.card_state === "stale" || zone.stale) {
    return { text: zone.rank_reason || "Нет свежих данных", tone: "info" };
  }
  if (zone.card_state === "on_plan") {
    if (!zone.last_expected) return { text: "График не задан", tone: "info" };
    return { text: "По графику", tone: "ok" };
  }
  const status = zoneUiStatus({
    open_alerts: zone.open_alerts || 0,
    alert_counts: zone.alert_counts,
    last_actual: zone.last_actual,
  });
  return { text: zoneStatusLabel(status), tone: zoneTone(status) };
}

export function factValue(actual: ActualState | null | undefined, key: string): string {
  const n = factNumber(actual, key);
  if (n != null) return countPhrase(key, n);
  if (!actual) return "—";
  const stat = actual.elements?.[key];
  if (!stat) return "—";
  if (typeof stat.detected === "boolean") return stat.detected ? "да" : "нет";
  return "—";
}

const PRESENCE_FACT: Record<string, string> = {
  facade_visible: "Фасад виден на кадре. Это наличие признака, не завершение фасада.",
  windows_visible: "Окна видны на кадре. Это наличие признака, не завершение остекления.",
  roof_visible: "Кровля видна на кадре. Это наличие признака, не завершение кровли.",
  excavation_visible: "Есть признаки изменения грунта или котлована.",
  foundation_visible: "Виден признак фундамента. Это не завершение фундамента.",
  divider_stage_sign: "Есть визуальный признак разделительной полосы. Длина в метрах отсюда не следует.",
};

export function confirmedFactNotes(actual?: ActualState | null): string[] {
  const lines: string[] = [];
  for (const row of actual?.work_facts_summary || []) {
    if (row.certainty !== "confirmed" || row.value == null || row.value === false) continue;
    if (row.indicator_id === "visible_floor_levels") {
      const n = Number(row.value);
      if (Number.isFinite(n) && n >= 0) {
        const day = String((actual?.scene_attributes?.floor_level_candidate as { observation_day?: string } | undefined)?.observation_day || "").slice(0, 10);
        const phrase = countPhrase("floors", n);
        lines.push(day ? `Подтверждено: ${phrase} (кадр ${day})` : `Подтверждено: ${phrase}`);
      }
      continue;
    }
    if (row.indicator_id.startsWith("equipment:")) {
      const kind = row.indicator_id.slice("equipment:".length);
      const count = Number(row.value);
      if (!Number.isFinite(count) || count <= 0) continue;
      lines.push(`На кадре: ${count} ${equipmentNoun(kind, count)}. Ресурсное наблюдение, не объём работ.`);
      continue;
    }
    const phrase = PRESENCE_FACT[row.indicator_id];
    if (phrase) lines.push(phrase);
  }
  return lines;
}

export function equipmentSummary(actual?: ActualState | null): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [key, stat] of Object.entries(actual?.equipment || {})) {
    out[key] = stat.count ?? 0;
  }
  return out;
}

export function equipmentInventory(actual?: ActualState | null): { key: string; count: number }[] {
  return Object.entries(equipmentSummary(actual))
    .filter(([, count]) => count > 0)
    .map(([key, count]) => ({ key, count }))
    .sort((a, b) => equipmentLabel(a.key).localeCompare(equipmentLabel(b.key), "ru"));
}

function deltaPhrase(delta: number, now: number | null, label: string): string {
  const prev = now == null ? null : now - delta;
  const sign = delta > 0 ? "+" : "−";
  const span = prev == null || now == null ? "" : ` (${prev} → ${now})`;
  return `${label} ${sign}${Math.abs(delta)}${span}`;
}

export function siteChangeLines(change?: SiteChange | null, actual?: ActualState | null): string[] {
  if (!change) {
    return ["Первое наблюдение. Изменение относительно прошлого кадра сравнивать пока не с чем."];
  }
  if (!change.comparable) {
    return ["Наблюдения не сопоставимы: другая камера или ракурс. Изменение не оценивалось."];
  }
  const gear = Object.entries(change.equipment_deltas || {});
  const structure = Object.entries(change.element_deltas || {}).filter(([key, delta]) => {
    if (key === "slabs" && change.element_deltas.floors === delta) return false;
    return elementLabel(key) !== "Показатель";
  });
  const counts = equipmentSummary(actual);
  const lines: string[] = [];
  if (!gear.length) lines.push("Количество техники с прошлого наблюдения не изменилось.");
  else {
    lines.push(
      gear
        .map(([key, delta]) => deltaPhrase(delta, counts[key] ?? 0, equipmentLabel(key).toLocaleLowerCase("ru")))
        .join("; "),
    );
  }
  if (!structure.length) lines.push("Признаков изменения конструктива не видно.");
  else {
    lines.push(
      structure
        .map(([key, delta]) => deltaPhrase(delta, factNumber(actual, key), elementLabel(key).toLocaleLowerCase("ru")))
        .join("; "),
    );
  }
  return lines;
}

export function asRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  return {};
}

export function numeric(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && !Number.isNaN(Number(value))) return Number(value);
  return null;
}

export function countPhrase(key: string, n: number): string {
  if (key === "floors" || key === "structural_levels") return `${n} ${plural(n, "этаж", "этажа", "этажей")}`;
  if (key === "slabs" || key === "slab") return `${n} ${plural(n, "плита", "плиты", "плит")}`;
  if (key === "columns" || key === "column") return `${n} ${plural(n, "колонна", "колонны", "колонн")}`;
  if (key === "dividing_line_m") return `${n} м`;
  return String(n);
}

export function valuesMismatch(expected: unknown, observed: unknown): boolean {
  const left = numeric(expected);
  const right = numeric(observed);
  if (left != null && right != null) return left !== right;
  return fmtValue(expected) !== fmtValue(observed);
}

export function comparisonModeFor(
  type?: string,
  expectedOrFlag?: boolean | Record<string, unknown> | ExpectedState | null,
  actual?: ActualState | Record<string, unknown> | null,
): ComparisonMode {
  if (type === "model_candidate") return "expected_observed";
  if (type === "no_dynamics") return "dynamics";
  if (type === "schedule_delay" || type === "missing_element") return "plan_fact";
  if (expectedOrFlag === true) return "plan_fact";
  if (expectedOrFlag && typeof expectedOrFlag === "object") {
    const nested = expectedValues(asRecord(expectedOrFlag));
    const floors = numeric(nested.floors) || factNumber(actual as ActualState, "floors") || 0;
    if (floors > 0) return "plan_fact";
  }
  return "expected_observed";
}

export function hasFloorMetrics(items: Array<{ key: string }>): boolean {
  return items.some(item => item.key === "floors" || item.key === "slabs" || item.key === "structural_levels");
}

function presentFact(value: unknown, key: string, side: "plan" | "fact"): string {
  if (value == null || value === "") return side === "fact" ? "Не определено" : "Не задан";
  if (typeof value === "boolean") {
    if (side === "plan") return value ? "ожидается" : "не требуется";
    return value ? "есть признак" : "признака нет";
  }
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    const nested = side === "plan" ? record.expected : record.observed;
    const amount = numeric(nested);
    if (amount != null) return countPhrase(key, amount);
    return side === "fact" ? "Не определено" : "Не задан";
  }
  const amount = numeric(value);
  if (amount != null) return countPhrase(key, amount);
  return humanToken(value);
}

/** Подпись план/факт для инспектора: предмет и значение, без склейки «Показатель. ожидается». */
export function planFactCaption(item: PlanFactItem, side: "plan" | "fact"): string {
  const value = side === "plan" ? item.expected : item.observed;
  const label = item.label && item.label !== "Показатель" ? item.label : "";
  if (value === "ожидается") return label ? `Ожидается признак: ${label}` : "Признак ожидается";
  if (value === "не требуется") return label ? `Не требуется: ${label}` : "Не требуется";
  if (value === "есть признак") return label ? `Наблюдается: ${label}` : "Есть признак";
  if (value === "признака нет") return label ? `Признака нет: ${label}` : "Признака нет";
  if (value === "—" && side === "fact") return "Не определено";
  if (value === "Не определено" || value === "Не задан") return value;
  if (label && !value.toLocaleLowerCase("ru").includes(label.toLocaleLowerCase("ru"))) return `${label}: ${value}`;
  return value;
}

export function planFactFromAlert(
  type: string,
  expected?: Record<string, unknown> | null,
  observed?: Record<string, unknown> | null,
): PlanFactItem[] {
  if (type === "model_candidate") return [];
  const exp = asRecord(expected);
  const obs = asRecord(observed);
  if (type === "missing_equipment" || type === "unexpected_equipment") {
    const keys = Object.keys(exp).length ? Object.keys(exp) : Object.keys(obs);
    return keys.map((key) => {
      const need = numeric(exp[key]);
      const got = numeric(obs[key]);
      return {
        key,
        label: equipmentLabel(key),
        expectedValue: need,
        observedValue: got,
        expected: type === "missing_equipment" && need != null ? `≥ ${need} ${equipmentNoun(key, need)}` : fmtValue(exp[key]),
        observed: fmtValue(got),
        mismatch: need != null && got != null && (type === "missing_equipment" ? got < need : got !== need),
      };
    });
  }
  const keys = [...Object.keys(exp), ...Object.keys(obs)].filter(
    (key, index, all) => all.indexOf(key) === index && !HIDDEN_FACT_KEYS.has(key),
  );
  const preferred = keys.filter((key) => (BUILDING_FACT_KEYS as readonly string[]).includes(key));
  const filtered = (preferred.length ? preferred : keys).filter((key) => key !== "structural_levels" || !keys.includes("floors"));
  return filtered.map((key) => {
    const left = numeric(exp[key]);
    const right = numeric(obs[key]);
    return {
      key,
      label: EQUIPMENT_RU[classKey(key)] ? equipmentLabel(key) : elementLabel(key),
      expectedValue: left,
      observedValue: right,
      expected: left != null ? countPhrase(key, left) : presentFact(exp[key], key, "plan"),
      observed: right != null ? countPhrase(key, right) : presentFact(obs[key], key, "fact"),
      mismatch: valuesMismatch(exp[key], obs[key]),
    };
  });
}

export function planFactFromZone(expected: ExpectedState | null | undefined, actual: ActualState | null | undefined): PlanFactItem[] {
  const required = expected?.required_equipment || [];
  const exp = expectedValues(expected as Record<string, unknown> | undefined);
  const floorPlan = numeric(exp.floors);
  if (floorPlan != null && floorPlan > 0) {
    const right = factNumber(actual, "floors");
    return [{
      key: "floors",
      label: elementLabel("floors"),
      expectedValue: floorPlan,
      observedValue: right,
      expected: countPhrase("floors", floorPlan),
      observed: right != null ? countPhrase("floors", right) : "Не определено",
      mismatch: right != null && right !== floorPlan,
    }];
  }
  const meters = numeric(exp.dividing_line_m);
  if (meters != null && meters > 0 && required.length === 0) {
    const sign = (actual?.work_facts_summary || []).find(
      (item) => item.indicator_id === "divider_stage_sign" && item.certainty === "confirmed",
    );
    return [{
      key: "dividing_line_m",
      label: "Длина разделителя",
      expectedValue: meters,
      observedValue: null,
      expected: countPhrase("dividing_line_m", meters),
      observed: sign
        ? "признак есть · м с кадра не измеряются"
        : "м с кадра не измеряются",
      mismatch: false,
    }];
  }
  return required.map((rule) => {
    const fact = (actual?.work_facts_summary || []).find(item => item.indicator_id === `equipment:${rule.type}`);
    const hasFacts = Boolean(actual?.work_facts_summary?.length);
    const confirmed = fact?.certainty === "confirmed" && fact.value != null ? Number(fact.value) : null;
    const legacy = !hasFacts ? equipmentSummary(actual)[rule.type] : undefined;
    const count = confirmed != null && Number.isFinite(confirmed) ? confirmed : legacy;
    return {
      key: rule.type,
      label: equipmentLabel(rule.type),
      expectedValue: rule.min_count,
      observedValue: count ?? null,
      expected: `≥ ${rule.min_count} ${equipmentNoun(rule.type, rule.min_count)}`,
      observed: !actual ? "—" : count == null ? "Не определено" : String(count),
      mismatch: Boolean(actual) && count != null && count < rule.min_count,
    };
  });
}

export function isoDay(iso?: string | null): string | null {
  if (!iso) return null;
  const day = String(iso).slice(0, 10);
  return day.length === 10 ? day : null;
}

export function controlDateIso(item: {
  related_dates?: string[] | null;
  last_observed_at?: string | null;
  latest_evidence?: { timestamp?: string } | null;
}): string | null {
  const related = (item.related_dates || []).filter(Boolean).sort();
  if (related.length) return related[related.length - 1];
  return isoDay(item.last_observed_at) || isoDay(item.latest_evidence?.timestamp);
}

export function periodLabel(item: {
  type?: string;
  observed?: Record<string, unknown> | null;
  related_dates?: string[] | null;
  first_observed_at?: string | null;
  last_observed_at?: string | null;
}): string {
  const days = numeric(item.observed?.observation_period_days);
  if (days != null) return `${Math.round(days)} ${plural(Math.round(days), "день", "дня", "дней")}`;
  const related = (item.related_dates || []).filter(Boolean).sort();
  if (related.length === 1) return `по кадрам ${fmtDotDate(related[0])}`;
  if (related.length >= 2) {
    const start = parseIso(related[0]);
    const end = parseIso(related[related.length - 1]);
    if (start && end) {
      const n = Math.max(0, Math.round((end.getTime() - start.getTime()) / 86400000));
      if (n === 0) return `по кадрам ${fmtDotDate(related[0])}`;
      return `${n} ${plural(n, "день", "дня", "дней")}`;
    }
  }
  const first = parseIso(item.first_observed_at);
  const last = parseIso(item.last_observed_at);
  if (first && last) {
    const n = Math.max(0, Math.round((last.getTime() - first.getTime()) / 86400000));
    if (n === 0) return `по кадрам ${fmtDotDate(item.last_observed_at)}`;
    return `${n} ${plural(n, "день", "дня", "дней")}`;
  }
  return "";
}

export function dynamicsCaption(observed?: Record<string, unknown> | null): string {
  const days = numeric(observed?.observation_period_days);
  const frames = numeric(observed?.n_states);
  const parts: string[] = [];
  if (days != null) parts.push(`${Math.round(days)} ${plural(Math.round(days), "день", "дня", "дней")} наблюдений`);
  if (frames != null) parts.push(`${frames} ${plural(frames, "сопоставимый кадр", "сопоставимых кадра", "сопоставимых кадров")}`);
  return parts.join(" · ");
}

export function openAlerts(alerts: AlertListItem[] | undefined): AlertListItem[] {
  return (alerts || []).filter(
    (item) => item.status === "open" && item.type !== "insufficient_evidence" && item.type !== "model_candidate",
  );
}

export function zoneUiStatus(zone: Pick<ZoneDash, "open_alerts" | "alert_counts"> & Partial<Pick<ZoneDash, "last_actual">>): ZoneUiStatus {
  if ("last_actual" in zone && !zone.last_actual) return "insufficient";
  const types = Object.fromEntries(Object.entries(zone.alert_counts || {}).filter(([key]) => key !== "model_candidate"));
  const onlyEvidence = (types.insufficient_evidence || 0) > 0 && Object.keys(types).every((key) => key === "insufficient_evidence" || !types[key]);
  if (onlyEvidence) return "insufficient";
  if ((zone.open_alerts || 0) <= 0) return "normal";
  return "attention";
}

export function zoneTone(open: AlertListItem[] | number | ZoneUiStatus): Tone {
  if (open === "normal") return "ok";
  if (open === "insufficient") return "info";
  if (open === "attention") return "attention";
  const count = typeof open === "number" ? open : open.length;
  if (count <= 0) return "ok";
  return "attention";
}

export function zoneStatusLabel(status: ZoneUiStatus | number): string {
  if (status === "normal" || status === 0) return "Проверка не требуется";
  if (status === "insufficient") return "Недостаточно данных";
  return "Требует проверки";
}

export function floorsSequence(values: Array<number | null>): string {
  return values.map((value) => (value == null ? "—" : String(value))).join(" → ");
}

export function planFloorsFromRow(row: TimelineRow): number | null {
  const expected = row.expected || {};
  return numeric(expectedValues(expected as Record<string, unknown>).floors);
}

export function floorsSeries(rows: TimelineRow[]): { plan: string; fact: string } | null {
  if (!rows.length) return null;
  const plans = rows.map(planFloorsFromRow);
  const facts = rows.map((row) => factNumber(row.actual, "floors"));
  if (!plans.some((value) => (value || 0) > 0) && !facts.some((value) => (value || 0) > 0)) return null;
  const compactPlan: Array<number | null> = [];
  const compactFact: Array<number | null> = [];
  plans.forEach((plan, idx) => {
    if (idx === 0 || plan !== plans[idx - 1]) {
      compactPlan.push(plan);
      compactFact.push(facts[idx]);
    }
  });
  return { plan: floorsSequence(compactPlan), fact: floorsSequence(compactFact) };
}

export function limitationLine(actual?: ActualState | null): string | undefined {
  const raw = actual?.scene_attributes?.limitation;
  if (typeof raw !== "string" || !raw.trim()) return undefined;
  if (/плит|slab/i.test(raw)) return "Этажность выведена из плит, это не юридический подсчёт.";
  if (!/[а-яё]/i.test(raw)) return "По кадру нельзя уверенно судить обо всех показателях.";
  return raw;
}

export function sortAttentionAlerts(alerts: AlertListItem[]): AlertListItem[] {
  const severityOrder: Record<string, number> = { critical: 0, warning: 1, info: 2 };
  const proposals = alerts.filter((item) => item.type === "model_candidate");
  const problems = alerts.filter((item) => item.type !== "model_candidate");
  const latestByZone = new Map<string | null, string>();
  for (const item of problems) {
    const date = controlDateIso(item) || "";
    if (date > (latestByZone.get(item.zone) || "")) latestByZone.set(item.zone, date);
  }
  const ranked = [...problems].sort((a, b) => {
    const severity = (severityOrder[a.severity] ?? 3) - (severityOrder[b.severity] ?? 3);
    if (severity) return severity;
    const earlier = (item: AlertListItem) => Number((controlDateIso(item) || "") < (latestByZone.get(item.zone) || ""));
    const age = earlier(a) - earlier(b);
    if (age) return age;
    const date = String(controlDateIso(b) || "").localeCompare(String(controlDateIso(a) || ""));
    if (date) return date;
    return Number(b.type === "no_dynamics") - Number(a.type === "no_dynamics");
  });
  return [...ranked, ...proposals];
}

function alertSliceKey(item: AlertListItem): string {
  const subject = classKey(String(item.expected?.indicator_id || ""));
  return `${item.zone || ""}\u0000${item.type || ""}\u0000${subject}`;
}

/** Одна семья сигналов: объект, тип и предмет. Разные предметы не склеиваются. */
export function alertFamily(item: Pick<AlertListItem, "zone" | "type" | "expected">): string {
  return alertSliceKey(item as AlertListItem);
}

export function isEarlierSlice(item: AlertListItem, all: AlertListItem[]): boolean {
  const key = alertSliceKey(item);
  const latest = all
    .filter((row) => alertSliceKey(row) === key)
    .map((row) => controlDateIso(row) || "")
    .filter(Boolean)
    .sort()
    .at(-1);
  const current = controlDateIso(item);
  return Boolean(latest && current && current !== latest);
}

export function currentAlerts(alerts: AlertListItem[]): AlertListItem[] {
  return alerts.filter((item) => !isEarlierSlice(item, alerts));
}

export type ZoneQueueGroup = {
  zone: string;
  zoneName: string;
  current: AlertListItem[];
  earlier: AlertListItem[];
};

export function groupAlertsForQueue(alerts: AlertListItem[]): ZoneQueueGroup[] {
  return groupAlertsByZone(alerts);
}

export function groupAlertsByZone(alerts: AlertListItem[]): ZoneQueueGroup[] {
  const ordered = sortAttentionAlerts(alerts);
  const groups = new Map<string, AlertListItem[]>();
  for (const item of ordered) {
    const key = item.zone || "";
    const rows = groups.get(key) || [];
    rows.push(item);
    groups.set(key, rows);
  }
  return [...groups.entries()].map(([zone, rows]) => ({
    zone,
    zoneName: rows[0]?.zone_name || zone || "Объект",
    current: rows.filter((item) => !isEarlierSlice(item, alerts)),
    earlier: rows.filter((item) => isEarlierSlice(item, alerts)),
  }));
}

export function isDemoSource(source?: string | null): boolean {
  return source === "annotation";
}

export function projectLooksSynthetic(zones: Array<{ last_source?: string | null }>): boolean {
  const sources = zones.map((zone) => zone.last_source).filter(Boolean);
  return sources.length > 0 && sources.every((source) => source === "annotation");
}

export function ksgPlanPhrase(expected?: Record<string, unknown> | null): string {
  const values = expectedValues(expected);
  const floors = numeric(values.floors);
  if (floors != null && floors > 0) return countPhrase("floors", floors);
  const required = Array.isArray(expected?.required_equipment)
    ? (expected.required_equipment as { type: string; min_count: number }[])
    : [];
  if (required.length) {
    return required.map((rule) => `≥ ${rule.min_count} ${equipmentNoun(rule.type, rule.min_count)}`).join(" · ");
  }
  const parts: string[] = [];
  for (const [key, value] of Object.entries(values)) {
    const n = numeric(value);
    if (n == null || n === 0) continue;
    parts.push(`${elementLabel(key)} ${countPhrase(key, n)}`);
  }
  return parts.join(" · ") || "—";
}

export function markersByControlDate(alerts: AlertListItem[] | undefined): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const alert of alerts || []) {
    const day = isoDay(controlDateIso(alert));
    if (!day) continue;
    out[day] = out[day] || [];
    if (!out[day].includes(alert.type)) out[day].push(alert.type);
  }
  return out;
}

export function actualHighlights(actual?: ActualState | null): string[] {
  if (!actual) return [];
  const out: string[] = [];
  const floors = factNumber(actual, "floors");
  const slabs = factNumber(actual, "slabs");
  const columns = factNumber(actual, "columns");
  if (floors) out.push(`${floors} ${plural(floors, "этаж", "этажа", "этажей")}`);
  if (slabs) out.push(`${slabs} ${plural(slabs, "плита", "плиты", "плит")}`);
  if (columns) out.push(`${columns} ${plural(columns, "колонна", "колонны", "колонн")}`);
  for (const [key, stat] of Object.entries(actual.equipment || {})) {
    const count = stat.count ?? 0;
    if (count > 0) out.push(`${equipmentLabel(key).toLowerCase()} ${count}`);
  }
  return out;
}

export function previewCaption(zone: ZoneDash): string {
  const status = zoneUiStatus(zone);
  if (status === "normal") return "норма";
  const items = planFactFromZone(zone.last_expected, zone.last_actual);
  const row = items.find((item) => item.mismatch) || items[0];
  if (!row) return zoneStatusLabel(status);
  return `${row.label.toLowerCase()} ${row.observed}`;
}

export function eventCaption(
  fromStatus: string,
  toStatus: string,
  actor: string,
  reasonLabel?: string,
): string {
  if ((!fromStatus || fromStatus === "created") && toStatus === "open") {
    return "Сигнал создан · система";
  }
  const who = actor && actor !== "system" ? actor : "система";
  const status = `${statusLabel(fromStatus || "open")} → ${statusLabel(toStatus)}`;
  return reasonLabel ? `${status} · ${reasonLabel} · ${who}` : `${status} · ${who}`;
}
