import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { fmtDotDate, ksgPlanPhrase, stageLabel } from "../labels";
import { RuDateField } from "./RuDateField";
import type {
  CatalogStage,
  ConstructionWorkNode,
  ConstructionWorksResponse,
  KsgRow,
} from "../types";
import { pingWorkspace } from "../workspace";
import { Btn } from "./Btn";
import { Icon } from "./Icon";
import { WorkTree } from "./WorkTree";
import { LoadingState } from "./PageState";

const SCHEDULE_TEMPLATE = [
  "start_date,end_date,stage,stage_label,floors,columns,slabs,walls,foundation,windows,roof,facade",
  "2026-09-01,2026-09-10,foundation,Устройство фундамента,0,0,0,0,true,0,false,false",
].join("\n");

function downloadCsv(filename: string, csv: string) {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function downloadScheduleTemplate() {
  downloadCsv("grafik-shablon.csv", SCHEDULE_TEMPLATE);
}

const EXPORT_KEYS = ["floors", "columns", "slabs", "walls", "windows", "foundation", "roof", "facade"] as const;

function csvCell(value: string) {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, "\"\"")}"` : value;
}

function exportSchedule(rows: KsgRow[]) {
  const header = ["start_date", "end_date", "stage", "stage_label", ...EXPORT_KEYS];
  const lines = [header.join(",")];
  for (const row of rows) {
    const expected = row.expected || {};
    const cells = [
      String(row.start_date || row.date || "").slice(0, 10),
      String(row.end_date || "").slice(0, 10),
      row.stage || "",
      row.stage_label || "",
      ...EXPORT_KEYS.map(key => expected[key] == null ? "" : String(expected[key])),
    ];
    lines.push(cells.map(cell => csvCell(cell)).join(","));
  }
  downloadCsv("grafik.csv", lines.join("\n"));
}

function dayStamp(iso?: string | null) {
  const day = String(iso || "").slice(0, 10);
  if (day.length !== 10) return null;
  const time = Date.parse(`${day}T00:00:00`);
  return Number.isNaN(time) ? null : time;
}

function dayCount(start?: string | null, end?: string | null) {
  const from = dayStamp(start);
  const to = dayStamp(end || start);
  if (from == null || to == null || to < from) return null;
  return Math.round((to - from) / 86400000) + 1;
}

function monthTicks(min: number, max: number, span: number) {
  const months: Date[] = [];
  const cursor = new Date(new Date(min).getFullYear(), new Date(min).getMonth(), 1);
  const last = new Date(new Date(max).getFullYear(), new Date(max).getMonth(), 1);
  while (cursor.getTime() <= last.getTime()) {
    months.push(new Date(cursor));
    cursor.setMonth(cursor.getMonth() + 1);
  }
  if (!months.length) return [];
  const slots = months.length <= 4 ? months.length : 5;
  const indexes = new Set<number>();
  if (months.length <= slots) {
    months.forEach((_, index) => indexes.add(index));
  } else {
    for (let i = 0; i < slots; i += 1) {
      indexes.add(Math.round((i * (months.length - 1)) / (slots - 1)));
    }
  }
  return [...indexes].sort((a, b) => a - b).map(index => {
    const date = months[index];
    const time = Math.min(Math.max(date.getTime(), min), max);
    return {
      left: ((time - min) / span) * 100,
      label: date.toLocaleDateString("ru-RU", { month: "short" }).replace(".", ""),
    };
  });
}

function localIsoDay(date = new Date()) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function calendarBounds(rows: KsgRow[]) {
  const stamps = rows.flatMap(row => [dayStamp(row.start_date || row.date), dayStamp(row.end_date || row.start_date || row.date)])
    .filter((value): value is number => value != null);
  if (!stamps.length) return null;
  const min = Math.min(...stamps);
  const max = Math.max(...stamps);
  const span = Math.max(max - min, 86400000);
  const ticks = monthTicks(min, max, span);
  const today = dayStamp(localIsoDay());
  const todayLeft = today != null && today >= min && today <= max ? ((today - min) / span) * 100 : null;
  return { min, span, ticks, todayLeft };
}

function barStyle(row: KsgRow, bounds: NonNullable<ReturnType<typeof calendarBounds>>) {
  const start = dayStamp(row.start_date || row.date);
  const end = dayStamp(row.end_date || row.start_date || row.date);
  if (start == null || end == null) return null;
  const left = ((Math.min(start, end) - bounds.min) / bounds.span) * 100;
  const width = Math.max(((Math.abs(end - start)) / bounds.span) * 100, 1.2);
  return { left: `${left}%`, width: `${width}%` };
}

function ScheduleDate({
  value,
  label,
  onCommit,
}: {
  value: string;
  label: string;
  onCommit: (next: string) => void;
}) {
  const current = String(value || "").slice(0, 10);
  const [draft, setDraft] = useState(current);
  useEffect(() => setDraft(current), [current]);
  return (
    <RuDateField
      className="schedule-date"
      label={label}
      value={draft}
      onChange={setDraft}
      onBlur={next => {
        if (next !== current) onCommit(next);
      }}
    />
  );
}

function asNumber(value: unknown) {
  if (value === "" || value == null) return "";
  const num = Number(value);
  return Number.isFinite(num) ? String(num) : "";
}

function expectedFromForm(form: FormData) {
  const payload: Record<string, unknown> = {};
  for (const key of ["floors", "columns", "slabs", "walls", "windows"]) {
    const raw = String(form.get(key) || "").trim();
    if (raw !== "") payload[key] = Number(raw);
  }
  for (const key of ["foundation", "roof", "facade"]) {
    if (form.get(key) === "on") payload[key] = true;
  }
  return payload;
}

function StageFields({
  stages,
  row,
  idPrefix,
}: {
  stages: CatalogStage[];
  row?: KsgRow;
  idPrefix: string;
}) {
  const expected = row?.expected || {};
  return (
    <div className="form-grid">
      <label>
        Начало этапа
        <RuDateField id={`${idPrefix}-start`} name="start_date" required defaultValue={row?.start_date || ""} label="Начало этапа" />
      </label>
      <label>
        Окончание
        <RuDateField id={`${idPrefix}-end`} name="end_date" defaultValue={row?.end_date || ""} label="Окончание" />
      </label>
      <label>
        Этап
        <select id={`${idPrefix}-stage`} name="stage" required defaultValue={row?.stage || stages[0]?.code || ""}>
          {stages.map(item => <option key={item.code} value={item.code}>{item.label}</option>)}
        </select>
      </label>
      <label>
        Подпись на экране
        <input id={`${idPrefix}-label`} name="stage_label" defaultValue={row?.stage_label || ""} placeholder="Если пусто — из справочника этапов" />
      </label>
      <label>
        Этажей в плане
        <input id={`${idPrefix}-floors`} name="floors" type="number" min="0" step="1" defaultValue={asNumber(expected.floors)} />
      </label>
      <label>
        Колонны
        <input name="columns" type="number" min="0" step="1" defaultValue={asNumber(expected.columns)} />
      </label>
      <label>
        Плиты
        <input name="slabs" type="number" min="0" step="1" defaultValue={asNumber(expected.slabs)} />
      </label>
      <label>
        Стены
        <input name="walls" type="number" min="0" step="1" defaultValue={asNumber(expected.walls)} />
      </label>
      <label className="check-row">
        <input name="foundation" type="checkbox" defaultChecked={Boolean(expected.foundation)} />
        Фундамент в плане
      </label>
      <label className="check-row">
        <input name="roof" type="checkbox" defaultChecked={Boolean(expected.roof)} />
        Кровля в плане
      </label>
      <label className="check-row">
        <input name="facade" type="checkbox" defaultChecked={Boolean(expected.facade)} />
        Фасад в плане
      </label>
    </div>
  );
}

export function KsgEditor({
  project,
  zone,
  rows,
  constructionTypeId,
  constructionTypeName,
  onSetConstructionType,
}: {
  project: string;
  zone: string;
  rows: KsgRow[];
  constructionTypeId?: string | null;
  constructionTypeName?: string | null;
  onSetConstructionType?: (typeId: string) => Promise<void>;
}) {
  const [stages, setStages] = useState<CatalogStage[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [addingCatalog, setAddingCatalog] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [works, setWorks] = useState<ConstructionWorksResponse | null>(null);
  const [worksLoading, setWorksLoading] = useState(false);
  const [picked, setPicked] = useState<ConstructionWorkNode | null>(null);
  const [catalogStart, setCatalogStart] = useState("");
  const [catalogEnd, setCatalogEnd] = useState("");
  const [typeOptions, setTypeOptions] = useState<{ id: string; name: string }[]>([]);
  const [pendingType, setPendingType] = useState("");

  useEffect(() => {
    api.catalogStages().then(value => setStages(value as CatalogStage[])).catch(err => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  useEffect(() => {
    if (!addingCatalog || !constructionTypeId) {
      setWorks(null);
      setPicked(null);
      return;
    }
    let cancelled = false;
    setWorksLoading(true);
    api.constructionWorks(constructionTypeId)
      .then(payload => {
        if (!cancelled) setWorks(payload as ConstructionWorksResponse);
      })
      .catch(err => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setWorksLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [addingCatalog, constructionTypeId]);

  useEffect(() => {
    if (constructionTypeId || !addingCatalog) return;
    api.constructionTypes()
      .then(items => setTypeOptions(items as { id: string; name: string }[]))
      .catch(err => setError(err instanceof Error ? err.message : String(err)));
  }, [addingCatalog, constructionTypeId]);

  async function run(label: string, action: () => Promise<unknown>) {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await action();
      pingWorkspace("catalog");
      if (label.startsWith("dates-") || label === "save") setNotice("Даты этапа сохранены.");
      else if (label === "add" || label === "catalog") setNotice("Этап записан в график.");
      setEditing(null);
      setAdding(false);
      setAddingCatalog(false);
      setPendingDelete(null);
      setPicked(null);
      setCatalogStart("");
      setCatalogEnd("");
    } catch (err) {
      setNotice("");
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  function rejectPeriod() {
    setNotice("");
    setError("Окончание не может быть раньше начала.");
  }

  const canSaveCatalog = Boolean(picked && catalogStart && catalogEnd);
  const bounds = calendarBounds(rows);
  const sheetRef = useRef<HTMLDivElement>(null);
  const shownDates = useRef<Record<string, { start: string; end: string }>>({});
  const stamps = rows
    .flatMap(row => [dayStamp(row.start_date || row.date), dayStamp(row.end_date || row.start_date || row.date)])
    .filter((value): value is number => value != null);
  const periodStart = stamps.length ? fmtDotDate(new Date(Math.min(...stamps)).toISOString()) : "";
  const periodEnd = stamps.length ? fmtDotDate(new Date(Math.max(...stamps)).toISOString()) : "";
  const todayInside = bounds?.todayLeft != null;
  const archive = stamps.length > 0 && Math.max(...stamps) < Date.now() - 86400000;

  function datesOf(row: KsgRow) {
    const id = row.id || "";
    return shownDates.current[id] || {
      start: String(row.start_date || row.date || "").slice(0, 10),
      end: String(row.end_date || "").slice(0, 10),
    };
  }

  function saveDates(row: KsgRow, start: string, end: string) {
    if (!row.id || !start) return;
    shownDates.current[row.id] = { start, end };
    const prevStart = String(row.start_date || row.date || "").slice(0, 10);
    const prevEnd = String(row.end_date || "").slice(0, 10);
    if (start === prevStart && end === prevEnd) return;
    if (end && end < start) {
      rejectPeriod();
      return;
    }
    void run(`dates-${row.id}`, () => api.updateStage(row.id!, {
      start_date: start,
      end_date: end || null,
    }));
  }

  return (
    <section className="section schedule-editor">
      <div className="section-head">
        <div>
          <h2>График объекта</h2>
          <p className="caption">
            Сроки правятся прямо в строке. Загрузка CSV, Excel или JSON заменяет график.             Выгрузка сохраняет текущие строки в том же формате.
          </p>
        </div>
        <div className="inline schedule-toolbar">
          <Btn
            title="Добавить этап в график объекта"
            onClick={() => { setAddingCatalog(true); setAdding(false); setEditing(null); }}
            disabled={addingCatalog}
            hint="Форма уже открыта"
          >
            Добавить этап
          </Btn>
          <details className="schedule-more">
            <summary>Файл графика</summary>
            <div className="schedule-more-menu">
              <Btn
                variant="ghost"
                title="Скачать текущий график объекта в CSV"
                onClick={() => exportSchedule(rows)}
                disabled={!rows.length}
                hint="Сначала создайте или загрузите график"
              >
                Выгрузить
              </Btn>
              <Btn variant="ghost" title="Скачать пустой CSV" onClick={downloadScheduleTemplate}>Шаблон</Btn>
              <label className="btn ghost">
                <Icon name="upload" />
                Загрузить
                <input
                  className="sr-only"
                  type="file"
                  accept=".csv,.xlsx,.xls,.json"
                  aria-label="Загрузить файл графика"
                  onChange={event => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (!file) return;
                    const body = new FormData();
                    body.set("file", file);
                    body.set("replace", "true");
                    void run("import", () => api.importKsg(project, zone, body));
                  }}
                />
              </label>
              <Btn
                variant="ghost"
                title="Добавить этап из каталога техники и этажей"
                onClick={() => { setAdding(true); setAddingCatalog(false); setEditing(null); }}
                disabled={adding}
              >
                Этап из каталога
              </Btn>
            </div>
          </details>
        </div>
      </div>
      {error ? <div className="inline-error" role="alert">{error}</div> : null}
      {notice ? <p className="save-note" role="status">{notice}</p> : null}
      {bounds ? (
        <div className="schedule-range">
          <p className="caption">Период графика: {periodStart} — {periodEnd}.</p>
          {archive ? (
            <p className="caption">Кадры и сроки этого периода не описывают сегодняшнее состояние стройки.</p>
          ) : null}
          {todayInside ? null : <p className="caption">Сегодня вне периода графика</p>}
          <div className="inline">
            <Btn
              variant="ghost"
              title="Показать график от первой до последней даты"
              onClick={() => sheetRef.current?.scrollTo({ top: 0, left: 0 })}
            >
              Весь график
            </Btn>
            {todayInside ? (
              <Btn
                variant="ghost"
                title="Показать сегодняшнюю дату на шкале графика"
                onClick={() => {
                  sheetRef.current?.querySelector(".schedule-today")?.scrollIntoView({ block: "nearest", inline: "center" });
                }}
              >
                Сегодня
              </Btn>
            ) : null}
          </div>
        </div>
      ) : null}
      <div ref={sheetRef} className="schedule-sheet" role="table" aria-label="Календарный график">
        <div className="schedule-head" role="row">
          <span />
          <span>Работа</span>
          <span>Начало</span>
          <span>Окончание</span>
          <span className="schedule-scale" aria-hidden="true">
            {bounds?.ticks.map(tick => (
              <i key={tick.label + tick.left} style={{ left: `${tick.left}%` }}>{tick.label}</i>
            ))}
          </span>
        </div>
        {!rows.length ? (
          <p className="overview-empty">Графика ещё нет. Загрузите файл или добавьте этап.</p>
        ) : rows.map((row, index) => {
          const placed = bounds ? barStyle(row, bounds) : null;
          const days = dayCount(row.start_date || row.date, row.end_date);
          const plan = ksgPlanPhrase(row.expected);
          return (
            <div key={row.id || `${row.start_date}-${row.stage}-${index}`} className={row.current ? "schedule-line is-current" : "schedule-line"} role="row">
              <span className="stage-num">{String(index + 1).padStart(2, "0")}</span>
              <div className="schedule-work">
                <strong>{stageLabel(row.stage, row.stage_label)}</strong>
                <span className="caption">
                  {days ? `${days} дн.` : "срок не задан"}
                  {plan ? ` · ${plan}` : ""}
                  {row.current ? " · текущий" : ""}
                </span>
                <details className="schedule-row-menu">
                  <summary>Действия</summary>
                  <div className="schedule-more-menu">
                    <Btn
                      variant="ghost"
                      title="Исправить этап и плановые показатели"
                      disabled={!row.id}
                      hint="У этой строки нет идентификатора — загрузите график заново"
                      onClick={() => { setEditing(editing === row.id ? null : row.id || null); setAdding(false); setAddingCatalog(false); }}
                    >
                      {editing === row.id ? "Скрыть состав" : "Состав"}
                    </Btn>
                    {pendingDelete === row.id ? (
                      <span className="confirm-bar">
                        Удалить этап? Наблюдения останутся.
                        <Btn
                          variant="danger"
                          title="Удалить строку графика. Наблюдения не удаляются"
                          busy={busy === "delete"}
                          onClick={() => row.id && run("delete", () => api.deleteStage(row.id!))}
                        >
                          Удалить
                        </Btn>
                        <Btn variant="ghost" title="Оставить этап" onClick={() => setPendingDelete(null)}>Оставить</Btn>
                      </span>
                    ) : (
                      <Btn
                        variant="ghost"
                        title="Убрать этап из графика объекта"
                        disabled={!row.id}
                        hint="Нельзя удалить строку без идентификатора"
                        onClick={() => setPendingDelete(row.id || null)}
                      >
                        Удалить этап
                      </Btn>
                    )}
                  </div>
                </details>
              </div>
              <ScheduleDate
                value={row.start_date || row.date}
                label={`Начало: ${stageLabel(row.stage, row.stage_label)}`}
                onCommit={start => saveDates(row, start, datesOf(row).end)}
              />
              <ScheduleDate
                value={row.end_date || ""}
                label={`Окончание: ${stageLabel(row.stage, row.stage_label)}`}
                onCommit={end => saveDates(row, datesOf(row).start, end)}
              />
              <div className="schedule-track" aria-hidden="true">
                {bounds?.todayLeft != null ? <span className="schedule-today" style={{ left: `${bounds.todayLeft}%` }} /> : null}
                {placed ? <span className="schedule-bar" style={placed} /> : null}
              </div>
              {editing === row.id ? (
                <form
                  className="schedule-edit panel-form"
                  onSubmit={event => {
                    event.preventDefault();
                    if (!row.id) return;
                    const form = new FormData(event.currentTarget);
                    const start = String(form.get("start_date") || "");
                    const end = String(form.get("end_date") || "");
                    if (end && end < start) {
                      rejectPeriod();
                      return;
                    }
                    void run("save", () => api.updateStage(row.id!, {
                      start_date: form.get("start_date"),
                      end_date: form.get("end_date") || null,
                      stage: form.get("stage"),
                      stage_label: form.get("stage_label"),
                      expected: expectedFromForm(form),
                    }));
                  }}
                >
                  <StageFields stages={stages} row={row} idPrefix={`edit-${row.id}`} />
                  <div className="inline">
                    <Btn type="submit" title="Сохранить состав этапа" busy={busy === "save"}>Сохранить</Btn>
                    <Btn variant="ghost" title="Закрыть без сохранения" onClick={() => setEditing(null)}>Отменить</Btn>
                  </div>
                </form>
              ) : null}
            </div>
          );
        })}
      </div>
      {addingCatalog && (
        <div className="panel-form catalog-schedule-form">
          <h3>Строка из справочника</h3>
          {!constructionTypeId ? (
            <div className="stack">
              <p className="caption">Сначала выберите вид строительства для объекта.</p>
              <label>
                Вид строительства
                <select value={pendingType} onChange={event => setPendingType(event.target.value)}>
                  <option value="">Выберите вид</option>
                  {typeOptions.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
              </label>
              <div className="inline">
                <Btn
                  title="Сохранить вид строительства на объекте"
                  disabled={!pendingType || !onSetConstructionType}
                  busy={busy === "type"}
                  onClick={() => {
                    if (!pendingType || !onSetConstructionType) return;
                    void run("type", () => onSetConstructionType(pendingType));
                  }}
                >
                  Сохранить вид
                </Btn>
                <Btn variant="ghost" title="Закрыть" onClick={() => setAddingCatalog(false)}>Отменить</Btn>
              </div>
            </div>
          ) : (
            <>
              <p className="caption">Вид: {constructionTypeName || "выбран"}. Выберите работу и укажите обе даты.</p>
              {worksLoading ? <LoadingState text="Загружаем справочник…" /> : (
                <WorkTree data={works} mode="pick" selectedId={picked?.id} onSelect={setPicked} />
              )}
              <div className="form-grid">
                <label>
                  Начало
                  <RuDateField value={catalogStart} onChange={setCatalogStart} required label="Начало" />
                </label>
                <label>
                  Окончание
                  <RuDateField value={catalogEnd} onChange={setCatalogEnd} required label="Окончание" />
                </label>
              </div>
              {picked && (
                <p className="caption">Выбрано: {picked.name}</p>
              )}
              <div className="inline">
                <Btn
                  title="Записать работу в график только с датами"
                  disabled={!canSaveCatalog}
                  hint="Нужны работа и обе даты"
                  busy={busy === "catalog"}
                  onClick={() => {
                    if (!picked || !catalogStart || !catalogEnd) return;
                    if (catalogEnd < catalogStart) {
                      rejectPeriod();
                      return;
                    }
                    void run("catalog", () => api.createStage(project, zone, {
                      start_date: catalogStart,
                      end_date: catalogEnd,
                      stage: picked.id,
                      stage_label: picked.name,
                      expected: {},
                    }));
                  }}
                >
                  Записать в график
                </Btn>
                <Btn variant="ghost" title="Закрыть без записи" onClick={() => setAddingCatalog(false)}>Отменить</Btn>
              </div>
            </>
          )}
        </div>
      )}
      {adding && (
        <form
          className="panel-form"
          onSubmit={event => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const start = String(form.get("start_date") || "");
            const end = String(form.get("end_date") || "");
            if (end && end < start) {
              rejectPeriod();
              return;
            }
            void run("add", () => api.createStage(project, zone, {
              start_date: form.get("start_date"),
              end_date: form.get("end_date") || null,
              stage: form.get("stage"),
              stage_label: form.get("stage_label"),
              expected: expectedFromForm(form),
            }));
          }}
        >
          <h3>Этап из каталога MVP</h3>
          <StageFields stages={stages} idPrefix="new-stage" />
          <div className="inline">
            <Btn type="submit" title="Добавить этап в график объекта" busy={busy === "add"}>Записать этап</Btn>
            <Btn variant="ghost" title="Закрыть форму без записи" onClick={() => setAdding(false)}>Отменить</Btn>
          </div>
        </form>
      )}
    </section>
  );
}
