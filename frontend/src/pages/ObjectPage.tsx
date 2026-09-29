import { FormEvent, useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { EvidenceViewer } from "../components/EvidenceViewer";
import { EmptyState, ErrorState, LoadingState } from "../components/PageState";
import { PageHeader } from "../components/PageHeader";
import { KsgEditor } from "../components/KsgEditor";
import { ObjectRegister } from "../components/ObjectRegister";
import { ChronologyFeed, ObjectOverview, ObjectSignalsPanel, RemoveFrame } from "../components/ObjectOverview";
import { ObjectWorkspaceHeader } from "../components/ObjectWorkspaceHeader";
import { SourcePanel } from "../components/SourcePanel";
import { ObserveForm } from "../components/ObserveForm";
import { EvidencePreview } from "../components/EvidencePreview";
import { Icon } from "../components/Icon";
import { Btn } from "../components/Btn";
import { useAsync } from "../hooks";
import {
  countPhrase,
  currentAlerts,
  equipmentNoun,
  fmtDotDate,
  fmtDotDateTime,
  humanWhen,
  ksgPlanPhrase,
  noteAuthorLabel,
  limitationLine,
  openAlerts,
  subjectFromExpected,
  planFactFromZone,
  sortAttentionAlerts,
  stageLabel,
  typeLabel,
  typeLead,
  publicText,
  zoneHeadline,
  zoneUiStatus,
} from "../labels";
import {
  OBJECTS_LIST_STATE_KEY,
  OBJECTS_SCROLL_KEY,
  LEGACY_OBJECT_SECTION,
  normalizeObjectSection,
  objectPath,
  type ObjectSection,
} from "../routes";
import type { AlertListItem, CaptureStatus, ConstructionType, KsgRow, ObjectPage, Observation, TimelineRow, ZoneNote } from "../types";
import { pingWorkspace, useWorkspace } from "../workspace";
import { HousingScheduleBlock, HousingVideoBlock } from "./HousingPage";
import { NewObjectPage } from "./NewObjectPage";
function readListState() {
  try {
    const raw = sessionStorage.getItem(OBJECTS_LIST_STATE_KEY);
    if (!raw) return { search: "", filter: "all", order: "server" };
    const parsed = JSON.parse(raw) as { search?: string; filter?: string; order?: string };
    return {
      search: parsed.search || "",
      filter: parsed.filter || "all",
      order: parsed.order || "server",
    };
  } catch {
    return { search: "", filter: "all", order: "server" };
  }
}

function writeListState(state: { search: string; filter: string; order: string }) {
  sessionStorage.setItem(OBJECTS_LIST_STATE_KEY, JSON.stringify(state));
}

export function ObjectsPage() {
  const { project } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const initial = readListState();
  const [search, setSearch] = useState(params.get("q") || initial.search);
  const [filter, setFilter] = useState(params.get("filter") || initial.filter);
  const [order, setOrder] = useState(params.get("order") || initial.order);

  useEffect(() => {
    writeListState({ search, filter, order });
    const next = new URLSearchParams();
    if (search) next.set("q", search);
    if (filter !== "all") next.set("filter", filter);
    if (order !== "server") next.set("order", order);
    const query = next.toString();
    const current = params.toString();
    if (query !== current) setParams(query ? next : {}, { replace: true });
  }, [search, filter, order]);

  useEffect(() => {
    const saved = Number(sessionStorage.getItem(OBJECTS_SCROLL_KEY) || 0);
    if (saved > 0) {
      requestAnimationFrame(() => window.scrollTo({ top: saved, behavior: "instant" }));
    }
    const onScroll = () => sessionStorage.setItem(OBJECTS_SCROLL_KEY, String(window.scrollY));
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  if (!project) {
    return (
      <div className="page-vitrine">
        <PageHeader
          title="Объекты"
          lead="Контроль строительных объектов. Последнее состояние площадок."
        />
        <EmptyState
          title="Объектов пока нет"
          text="Создайте первый объект. Пока нет реального кадра, на карточке будет честное пустое состояние."
          action={<Link className="btn" to="/objects/new">Создать первый объект</Link>}
        />
      </div>
    );
  }

  const filtered = project.zones.filter(zone => {
    const hay = `${zone.name} ${zone.description || ""} ${zone.stage_label || ""}`.toLocaleLowerCase("ru");
    const matchSearch = hay.includes(search.toLocaleLowerCase("ru"));
    const matchFilter = filter === "all" || zoneUiStatus(zone) === filter;
    return matchSearch && matchFilter;
  });
  const zones =
    order === "name" ? [...filtered].sort((a, b) => a.name.localeCompare(b.name, "ru")) : filtered;

  const editorial = filter === "all" && order === "server";
  const attention = editorial ? zones.filter(zone => zoneUiStatus(zone) === "attention") : [];
  const rest = editorial ? zones.filter(zone => zoneUiStatus(zone) !== "attention") : zones;
  const today = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long" }).format(new Date());

  return (
    <div className="page-vitrine">
      <header className="vitrine-hero">
        <p className="eyebrow">Объекты / {today}</p>
        <h1>Что происходит<br />на объектах сегодня</h1>
      </header>
      <div className="register-toolbar">
        <label className="search-field">
          <Icon name="search" />
          <input
            aria-label="Найти объект"
            placeholder="Название, описание или этап"
            value={search}
            onChange={event => setSearch(event.target.value)}
          />
        </label>
        <select aria-label="Состояние объектов" value={filter} onChange={event => setFilter(event.target.value)}>
          <option value="all">Все состояния</option>
          <option value="attention">Требует внимания</option>
          <option value="normal">Без отклонений</option>
          <option value="insufficient">Недостаточно данных</option>
        </select>
        <select aria-label="Порядок объектов" value={order} onChange={event => setOrder(event.target.value)}>
          <option value="server">По приоритету внимания</option>
          <option value="name">По названию</option>
        </select>
      </div>
      {zones.length ? (
        editorial ? (
          <>
            {attention.length ? (
              <section className="vitrine-section" aria-label="Требует проверки">
                <p className="vitrine-index">01</p>
                <h2>Требует проверки</h2>
                <ObjectRegister zones={attention} />
              </section>
            ) : null}
            {rest.length ? (
              <section className="vitrine-section" aria-label="Остальные объекты">
                <p className="vitrine-index">{attention.length ? "02" : "01"}</p>
                <h2>{attention.length ? "Остальные объекты" : "Объекты"}</h2>
                <ObjectRegister zones={rest} />
              </section>
            ) : null}
          </>
        ) : (
          <ObjectRegister zones={zones} />
        )
      ) : project.zones.length === 0 ? (
        <EmptyState
          title="Объектов пока нет"
          text="Создайте первый объект — без фейкового фото, пока не появится реальный кадр."
          action={<Link className="btn" to="/objects/new">Создать первый объект</Link>}
        />
      ) : (
        <EmptyState title="Ничего не найдено" text="Измените запрос или выберите другое состояние." />
      )}
    </div>
  );
}

function ZoneNotesPanel({ project, zone }: { project: string; zone: string }) {
  const { inspectorName, revision } = useWorkspace();
  const [notes, setNotes] = useState<ZoneNote[]>([]);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const rows = await api.zoneNotes(project, zone) as ZoneNote[];
      setNotes(rows);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [project, zone, revision]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!body.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api.createZoneNote(project, zone, { body: body.trim(), author: inspectorName });
      setBody("");
      setSaved("Заметка сохранена.");
      await load();
      pingWorkspace("catalog");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="section">
      <div className="section-head">
        <h2>Заметки инспектора</h2>
        <span className="caption">К объекту, не к отдельному сигналу</span>
      </div>
      <form className="panel-form note-form" onSubmit={onSubmit}>
        <label>
          Новая заметка
          <textarea
            value={body}
            onChange={event => {
              setBody(event.target.value);
              setSaved("");
            }}
            rows={3}
            placeholder="Например: на западном фасаде временно демонтированы леса. Повторно проверить завтра."
          />
        </label>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        {saved ? <p className="save-note" role="status">{saved}</p> : null}
        <Btn type="submit" busy={busy} disabled={!body.trim()} title="Сохранить заметку объекта">
          Сохранить заметку
        </Btn>
      </form>
      {loading ? <LoadingState text="Загружаем заметки…" /> : null}
      {!loading && notes.length === 0 ? <p className="muted">Заметок пока нет.</p> : null}
      <ul className="note-list">
        {notes.map(note => (
          <li key={note.id} className="note-item">
            <p>{note.body}</p>
            <span className="caption">
              {[noteAuthorLabel(note.author), note.created_at ? fmtDotDateTime(note.created_at) : ""]
                .filter(Boolean)
                .join(" · ")}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ZoneSettingsPanel({
  project,
  zone,
  page,
}: {
  project: string;
  zone: string;
  page: ObjectPage;
}) {
  const [name, setName] = useState(page.zone.name);
  const [description, setDescription] = useState(page.zone.description || "");
  const [typeId, setTypeId] = useState(page.zone.construction_type_id || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const { data: types } = useAsync(() => api.constructionTypes() as Promise<ConstructionType[]>, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) {
      setError("Укажите название.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.updateZone(project, zone, {
        name: name.trim(),
        description: description.trim(),
        construction_type_id: typeId || null,
      });
      setSaved("Карточка сохранена.");
      pingWorkspace("catalog");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="section" id="object">
        <div className="section-head">
          <h2>Карточка</h2>
          <span className="caption">Имя в списке и вид строительства. От вида зависит, какие работы можно добавить в график.</span>
        </div>
        <form className="settings-form object-create-form" onSubmit={onSubmit}>
          <div className="form-grid">
            <label className="span-2">
              Название
              <input value={name} onChange={event => setName(event.target.value)} required />
            </label>
            <label className="span-2">
              Вид строительства
              <select value={typeId} onChange={event => setTypeId(event.target.value)}>
                <option value="">Не выбран</option>
                {(types || []).map(item => (
                  <option key={item.id} value={item.id}>{item.name}</option>
                ))}
              </select>
            </label>
            <label className="span-2">
              Описание
              <textarea value={description} onChange={event => setDescription(event.target.value)} rows={3} placeholder="Необязательно" />
            </label>
          </div>
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          {saved ? <p className="save-note" role="status">{saved}</p> : null}
          <Btn type="submit" busy={busy} title="Сохранить название, вид и заметку">Сохранить карточку</Btn>
        </form>
      </section>
    </>
  );
}

function ZoneDelete({
  project,
  zone,
  name,
}: {
  project: string;
  zone: string;
  name: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const navigate = useNavigate();

  return (
    <section className="section settings-danger">
      <h2>Удалить объект</h2>
      <p className="caption">Вместе с объектом удалятся камеры, кадры, график и сигналы. Это нельзя отменить.</p>
      {confirmDelete ? (
        <div className="confirm-bar">
          Удалить «{name}»?
          <Btn
            variant="danger"
            title="Удалить объект"
            busy={busy}
            onClick={() => {
              setBusy(true);
              setError("");
              void api.deleteZone(project, zone).then(() => {
                pingWorkspace("catalog");
                navigate("/objects");
              }).catch(err => {
                setError(err instanceof Error ? err.message : String(err));
                setBusy(false);
              });
            }}
          >
            Удалить
          </Btn>
          <Btn variant="ghost" title="Оставить объект" onClick={() => setConfirmDelete(false)}>Оставить</Btn>
        </div>
      ) : (
        <Btn variant="ghost" title="Удалить объект" onClick={() => setConfirmDelete(true)}>Удалить объект</Btn>
      )}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
    </section>
  );
}

function workKey(row: KsgRow) {
  return `${row.start_date || row.date}|${row.stage || row.stage_label || ""}`;
}

function backTarget(zone: string, from: string | null) {
  if (from === "progress") return objectPath(zone, "progress");
  if (from === "overview") return objectPath(zone, "overview");
  if (from === "sources") return `${objectPath(zone, "settings")}#media`;
  if (from === "signals") return objectPath(zone, "signals");
  return objectPath(zone, "history");
}

function backLabel(from: string | null) {
  if (from === "progress") return "К план-факту";
  if (from === "overview") return "К обзору";
  if (from === "sources") return "К источникам";
  if (from === "signals") return "К сигналам";
  return "К хронологии";
}

function objectHeadline(
  zone: Parameters<typeof zoneHeadline>[0],
  hasFrame: boolean,
) {
  return zoneHeadline(zone, { hasFrame });
}

function dateInScheduleRow(row: KsgRow, iso?: string | null) {
  if (!iso) return false;
  const day = String(iso).slice(0, 10);
  const start = String(row.start_date || row.date).slice(0, 10);
  const end = String(row.end_date || row.start_date || row.date).slice(0, 10);
  return day >= start && day <= end;
}

function progressMark(row: KsgRow, today: string, mismatch: boolean, signal?: AlertListItem): string {
  if (row.current && mismatch) return "отклонение";
  if (row.current && signal?.status === "open") return "требует проверки";
  if (row.current) return "текущий";
  if (signal?.status === "open") return "требует проверки";
  const end = String(row.end_date || row.start_date || row.date || "").slice(0, 10);
  const start = String(row.start_date || row.date || "").slice(0, 10);
  if (end.length === 10 && end < today) return "срок прошёл";
  if (start.length === 10 && start > today) return "далее";
  return "в окне графика";
}

function ProgressWorks({
  page,
  alerts,
  onOpen,
}: {
  page: ObjectPage;
  alerts: AlertListItem[];
  onOpen: (key: string) => void;
}) {
  const rows = page.ksg || [];
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  if (!rows.length) {
    return (
      <EmptyState
        title="Графика ещё нет"
        text="Сроки не выдумываются. Загрузите КСГ или соберите график из справочника вида строительства — с датами."
        action={<Link className="btn" to={objectPath(page.zone.code, "schedule")}>Открыть график</Link>}
      />
    );
  }
  const metrics = planFactFromZone(page.expected, page.actual);
  const fact = metrics.find(item => item.mismatch) || metrics[0];
  const problems = alerts.filter(item => item.type !== "model_candidate");
  return (
    <ol className="stage-seq">
      {rows.map((row, index) => {
        const related = problems.filter(alert => dateInScheduleRow(row, alert.last_observed_at || alert.created_at));
        const signal = row.current
          ? problems.find(item => item.status === "open") || related[0]
          : related.find(item => item.status === "open") || related[0];
        const plan = ksgPlanPhrase(row.expected);
        const mark = progressMark(row, today, Boolean(row.current && fact?.mismatch), signal);
        return (
          <li key={`${row.start_date}-${row.stage || ""}-${index}`} className={row.current ? "is-current" : ""}>
            <button type="button" className="progress-row" onClick={() => onOpen(workKey(row))}>
              <span className="stage-num">{String(index + 1).padStart(2, "0")}</span>
              <span className="progress-row-copy">
                <strong>{stageLabel(row.stage, row.stage_label)}</strong>
                <span className="caption">
                  {fmtDotDate(row.start_date)}
                  {row.end_date && row.end_date !== row.start_date ? ` — ${fmtDotDate(row.end_date)}` : ""}
                  {plan ? ` · ${plan}` : ""}
                </span>
                {row.current && fact ? (
                  <span className="caption">Факт: {fact.observed === "—" || !fact.observed ? "Не определено" : fact.observed}</span>
                ) : null}
                {row.day_done ? <span className="caption">{row.day_done}</span> : null}
              </span>
              <em className={mark.includes("отклон") || mark.includes("проверк") ? "is-attention" : ""}>{mark}</em>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

function rowDates(row?: KsgRow): string {
  if (!row) return "";
  const start = fmtDotDate(row.start_date || row.date);
  const end = row.end_date && row.end_date !== row.start_date ? fmtDotDate(row.end_date) : "";
  return end ? `${start} — ${end}` : start;
}

function factDelta(key: string, expected?: number | null, observed?: number | null): string {
  if (expected == null || observed == null || expected === observed) return "";
  const delta = observed - expected;
  const amount = Math.abs(delta);
  const phrase = countPhrase(key, amount);
  const body = phrase === String(amount) ? `${amount} ${equipmentNoun(key, amount)}` : phrase;
  return `${delta > 0 ? "+" : "−"}${body}`;
}

function StageFrames({
  row,
  observations,
  openId,
  onOpen,
  onClose,
}: {
  row: KsgRow;
  observations: Observation[];
  openId: string | null;
  onOpen: (id: string) => void;
  onClose: () => void;
}) {
  const frames = observations.filter(shot => (
    dateInScheduleRow(row, shot.timestamp)
    && (shot.image_url || shot.viz_url)
    && shot.kept !== false
  ));
  const open = frames.find(shot => shot.id === openId);
  return (
    <div className="stage-frames-block">
      {open ? null : <h3>Кадры этапа</h3>}
      {open ? (
        <>
          <button type="button" className="context-back" onClick={onClose}><Icon name="arrow" />Все кадры этапа</button>
          <EvidenceViewer items={frames} focusId={open.id} onOpen={onOpen} />
        </>
      ) : frames.length ? (
        <div className="stage-frames">
          {frames.map(shot => (
            <button key={shot.id} type="button" className="stage-frame" onClick={() => onOpen(shot.id)}>
              <EvidencePreview
                src={shot.image_url || shot.viz_url}
                poster={shot.viz_url}
                alt=""
                presentation="cover"
              />
              <span>{humanWhen(shot.timestamp)}</span>
              <span className="caption">{shot.camera_name || shot.capture_origin_label || ""}</span>
            </button>
          ))}
        </div>
      ) : (
        <p className="overview-empty">В даты этого этапа кадров нет.</p>
      )}
    </div>
  );
}

function uniqueSignals(alerts: AlertListItem[]): AlertListItem[] {
  const seen = new Set<string>();
  return alerts.filter(item => {
    const key = `${item.type}:${String(item.expected?.indicator_id || item.id)}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function ProgressCompare({
  page,
  alerts,
  row,
}: {
  page: ObjectPage;
  alerts: AlertListItem[];
  row?: KsgRow;
}) {
  const current = row || (page.ksg || []).find(item => item.current);
  const comparable = !row || row.current;
  const metrics = comparable ? planFactFromZone(page.expected, page.actual) : [];
  const focus = metrics.find(item => item.mismatch) || metrics[0];
  const plan = focus?.expected && focus.expected !== "—"
    ? focus.expected
    : (current ? ksgPlanPhrase(current.expected) : "");
  const fact = focus?.key === "dividing_line_m"
    ? (focus.observed && focus.observed !== "—" ? focus.observed : "м с кадра не измеряются")
    : (focus?.observed && focus.observed !== "—" ? focus.observed : "");
  const delta = focus?.key === "dividing_line_m"
    ? "Длина в метрах с кадра не следует"
    : (focus?.mismatch ? factDelta(focus.key, focus.expectedValue, focus.observedValue) : "");
  const limit = comparable ? limitationLine(page.actual) : undefined;
  const checks = uniqueSignals(alerts);

  return (
    <div className="progress-compare">
      <h2>{current ? stageLabel(current.stage, current.stage_label) : "Пункт не задан"}</h2>
      {current ? <p className="caption">{rowDates(current)}</p> : <p className="muted">На эту дату пункт графика не задан.</p>}
      {current?.day_done ? <p className="caption">{current.day_done}</p> : null}
      {comparable ? (
        <div className="planfact-sheet">
          <div>
            <span className="eyebrow">План</span>
            <p className="planfact-value">{plan || "Не задан"}</p>
          </div>
          <div>
            <span className="eyebrow">Факт</span>
            <p className={`planfact-value${(fact || "Не определено").length > 12 ? " is-long" : ""}${fact ? "" : " is-unknown"}`}>{fact || "Не определено"}</p>
          </div>
        </div>
      ) : (
        <p className="muted">Числа план/факт на этом экране — для текущего пункта. Ниже кадры, снятые в даты этапа.</p>
      )}
      {delta ? <p className="delta-mark">{delta}</p> : null}
      {checks.length ? (
        <div className="progress-checks">
          <p className="eyebrow">Что проверить</p>
          <ul>
            {checks.map(item => (
              <li key={item.id}>
                <strong>{[subjectFromExpected(item.expected), typeLabel(item.type)].filter(Boolean).join(" · ")}</strong>
                <span>{typeLead(item.type)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : comparable ? (
        <p className="muted">Открытого сигнала по этому сопоставлению нет.</p>
      ) : null}
      {limit ? <p className="caption">{limit}</p> : null}
    </div>
  );
}


export function ObjectPageView() {
  const { zoneCode, section: sectionParam } = useParams();
  const { projects, project, setProjectCode, revision } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const zone = zoneCode || "";
  const owner = projects.find(item => item.zones.some(entry => entry.code === zone));
  const projectCode = owner?.code || project?.code || "";
  useEffect(() => {
    if (owner && owner.code !== project?.code) setProjectCode(owner.code);
  }, [owner, project?.code, setProjectCode]);
  const legacyTab = params.get("tab");
  const section: ObjectSection = normalizeObjectSection(sectionParam || legacyTab);
  const legacySection = sectionParam ? LEGACY_OBJECT_SECTION[sectionParam] : undefined;

  const { data, error, loading } = useAsync(async () => {
    if (!projectCode || !zone || zone === "new") return null;
    if (projects.length && !owner) return null;
    return api.objectPage(projectCode, zone) as Promise<ObjectPage>;
  }, [projectCode, zone, revision, projects.length, Boolean(owner)]);

  const { data: timeline } = useAsync(async () => {
    if (!projectCode || !zone || zone === "new") return [] as TimelineRow[];
    if (section !== "history") return [] as TimelineRow[];
    return api.timeline(projectCode, zone) as Promise<TimelineRow[]>;
  }, [projectCode, zone, revision, section]);

  const { data: capture } = useAsync(async () => {
    if (section !== "settings" && section !== "sources") return null;
    return api.captureStatus() as Promise<CaptureStatus>;
  }, [section, zone, revision]);

  useEffect(() => {
    if (section !== "settings") return;
    const id = window.location.hash.replace("#", "");
    if (!id) return;
    document.getElementById(id)?.scrollIntoView({ block: "start" });
  }, [section, data]);

  if (zone && zone !== "new" && legacySection) {
    const target = objectPath(zone, legacySection.section);
    const hash = legacySection.view === "media" ? "#upload" : "";
    return <Navigate to={legacySection.view && legacySection.view !== "media" ? `${target}?view=${legacySection.view}` : `${target}${hash}`} replace />;
  }
  if (zone && zone !== "new" && legacyTab) {
    return <Navigate to={objectPath(zone, normalizeObjectSection(legacyTab))} replace />;
  }

  if (zone === "new") return <NewObjectPage />;
  if (loading && !data) return <LoadingState text="Собираем карточку объекта…" />;
  if (error && !data) return <ErrorState text={error} />;
  if (!owner || !data) {
    return (
      <EmptyState
        title="Объект не найден"
        text="Выберите объект на витрине."
        action={<Link className="btn" to="/objects">Все объекты</Link>}
      />
    );
  }

  const page = data;
  const material = sortAttentionAlerts(openAlerts(page.alerts));
  const lead = material[0] || currentAlerts(page.alerts.filter(item => (item.status === "open" || item.status === "needs_more_data") && item.type !== "model_candidate"))[0];
  const dashZone = owner.zones.find(item => item.code === zone);
  const observations = [...page.observations].sort((a, b) => b.timestamp.localeCompare(a.timestamp));
  const history = timeline || [];
  const itemKey = params.get("item");
  const shotId = params.get("observation");
  const from = params.get("from");
  const focusRow = (page.ksg || []).find(row => workKey(row) === itemKey);
  const focusShot = observations.find(item => item.id === shotId) || observations[0];
  const hasFrame = Boolean(observations[0]?.image_url || observations[0]?.viz_url);
  const status = objectHeadline(dashZone, hasFrame);
  const kind = page.zone.construction_type_name || "";
  const updated = observations[0]?.timestamp
    ? humanWhen(observations[0].timestamp)
    : "Нет обновлений";
  const cameras = page.cameras || [];

  return (
    <div className="object-page">
      <ObjectWorkspaceHeader
        zoneCode={zone}
        name={page.zone.name}
        section={section}
        status={status}
        updated={updated}
        kind={kind || (owner.code === "housing_16" ? page.project.name : "")}
        place={publicText(page.project.address)}
      />

      {section === "notes" && (
        <>
          <Link className="context-back" to={objectPath(zone, "overview")}><Icon name="arrow" />К обзору</Link>
          <ZoneNotesPanel project={owner.code} zone={zone} />
        </>
      )}

      {section === "sources" && (
        <div className="sources-page">
          {params.get("created") ? (
            <p className="save-note" role="status">Объект создан. Дальше можно подключить источник или загрузить график.</p>
          ) : null}
          <SourcePanel project={owner.code} zone={zone} cameras={cameras} capture={capture} />
          {owner.code === "housing_16" ? <HousingVideoBlock /> : null}
          <section className="section" id="upload" aria-label="Свой кадр">
            <div className="section-head">
              <h2>Материалы</h2>
              <span className="caption">Фото или видео с телефона. Кадр попадёт в хронологию выбранной камеры.</span>
            </div>
            <ObserveForm project={owner} zoneCode={zone} lockZone cameras={page.cameras} mode="settings" />
          </section>
        </div>
      )}

      {section === "settings" && (
        <div className="settings-page">
          <ZoneSettingsPanel project={owner.code} zone={zone} page={page} />
          <ZoneDelete project={owner.code} zone={zone} name={page.zone.name} />
        </div>
      )}

      {section === "signals" && (
        <ObjectSignalsPanel
          alerts={page.alerts}
          zoneCode={zone}
          checkId={params.get("check")}
          onOpen={id => {
            const next = new URLSearchParams(params);
            next.set("check", id);
            setParams(next);
          }}
          onClose={() => {
            const next = new URLSearchParams(params);
            next.delete("check");
            setParams(next, { replace: true });
          }}
        />
      )}

      {section === "overview" && (
        <ObjectOverview
          page={page}
          zone={dashZone}
          observations={observations}
          openAlerts={lead ? [lead] : []}
          onChanged={() => void load()}
        />
      )}

      {section === "progress" && itemKey && focusRow && (
        <section className="section progress-detail">
          <Link className="context-back" to={objectPath(zone, "progress")}><Icon name="arrow" />К план-факту</Link>
          <ProgressCompare page={page} alerts={focusRow.current ? material : []} row={focusRow} />
          <StageFrames
            row={focusRow}
            observations={observations}
            openId={shotId}
            onOpen={id => setParams({ item: itemKey, observation: id })}
            onClose={() => setParams({ item: itemKey })}
          />
        </section>
      )}

      {section === "progress" && !(itemKey && focusRow) && (
        <div className="progress-page">
          <div className="section-head">
            <h2>План и выполнение</h2>
            <Link className="text-link" to={objectPath(zone, "schedule")}>Открыть график</Link>
          </div>
          <p className="caption progress-note">Этапы и сроки. Крупное сравнение плана с фактом остаётся на обзоре. Откройте этап, чтобы увидеть основания и кадры.</p>
          <section className="section" aria-label="Этапы">
            <h2>Этапы</h2>
            <ProgressWorks
              page={page}
              alerts={page.alerts}
              onOpen={key => setParams({ item: key })}
            />
            <p className="caption progress-note">Сравнение с фактом строится для текущего пункта. Срок сам по себе не означает, что работа выполнена.</p>
          </section>
        </div>
      )}

      {section === "history" && shotId && (
        <section className="evidence-library">
          <Link className="context-back" to={backTarget(zone, from)}><Icon name="arrow" />{backLabel(from)}</Link>
          <h2>Наблюдение</h2>
          {focusShot ? (
            <>
              <EvidenceViewer items={[focusShot]} />
              <RemoveFrame
                observationId={focusShot.id}
                when={humanWhen(focusShot.timestamp)}
                onRemoved={() => setParams({}, { replace: true })}
              />
            </>
          ) : <p className="overview-empty">Этот кадр больше не найден.</p>}
        </section>
      )}

      {section === "history" && !shotId && (
        <section className="section chronology-section" aria-label="Хронология">
          <p className="caption chronology-lead">Кадры объекта и изменения по дням</p>
          <ChronologyFeed observations={observations} timeline={history} zoneCode={zone} />
        </section>
      )}

      {section === "schedule" && (
        <>
          {owner.code === "housing_16" ? <HousingScheduleBlock /> : null}
          <KsgEditor
          project={owner.code}
          zone={zone}
          rows={page.ksg || []}
          constructionTypeId={page.zone.construction_type_id}
          constructionTypeName={page.zone.construction_type_name}
          onSetConstructionType={async typeId => {
            await api.updateZone(owner.code, zone, { construction_type_id: typeId });
            pingWorkspace("catalog");
          }}
        />
        </>
      )}
    </div>
  );
}
