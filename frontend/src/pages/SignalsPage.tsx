import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { AlertCard } from "../components/AlertCard";
import { AlertPanel } from "../components/AlertPanel";
import { SliceHistory } from "../components/SliceHistory";
import { EmptyState, ErrorState, LoadingState } from "../components/PageState";
import { PageHeader } from "../components/PageHeader";
import { useAsync } from "../hooks";
import { alertFamily, groupAlertsByZone, sortAttentionAlerts, statusLabel } from "../labels";
import type { AlertDetail, AlertListItem, InspectionBrief } from "../types";
import { useWorkspace } from "../workspace";

const FILTERS = ["open", "model_candidate", "needs_more_data", "confirmed", "rejected", "all"];

export function SignalsPage() {
  const { alertId } = useParams();
  const navigate = useNavigate();
  const { project, config, inspectorName, setInspectorName } = useWorkspace();
  const [filter, setFilter] = useState(() => sessionStorage.getItem("sitewatch.signals.filter") || "open");
  const [revision, setRevision] = useState(0);
  const queueRef = useRef<HTMLElement>(null);
  const refresh = () => setRevision(value => value + 1);

  useEffect(() => {
    sessionStorage.setItem("sitewatch.signals.filter", filter);
  }, [filter]);

  const list = useAsync(async () => {
    if (!project) return [] as AlertListItem[];
    if (filter === "model_candidate") {
      return await api.alerts("open", project.code, "model_candidate", 50, 0) as AlertListItem[];
    }
    const rows = await api.alerts(filter === "all" ? undefined : filter, project.code) as AlertListItem[];
    return filter === "open" ? sortAttentionAlerts(rows) : rows;
  }, [filter, revision, project?.code]);

  const rows = list.data || [];
  const groups = (filter === "model_candidate" ? groupAlertsByZone(rows).map(group => ({ ...group, current: [...group.current, ...group.earlier], earlier: [] })) : groupAlertsByZone(rows));
  const current = groups.flatMap(group => group.current);
  const selected = alertId || current[0]?.id || rows[0]?.id;
  const selectedRow = rows.find(item => item.id === selected);
  const history = selectedRow
    ? rows.filter(item => item.id !== selectedRow.id && alertFamily(item) === alertFamily(selectedRow))
    : [];

  useEffect(() => {
    const node = queueRef.current;
    if (!node) return;
    const saved = Number(sessionStorage.getItem("sitewatch.signals.queue") || 0);
    if (saved > 0) node.scrollTop = saved;
    const onScroll = () => sessionStorage.setItem("sitewatch.signals.queue", String(node.scrollTop));
    node.addEventListener("scroll", onScroll, { passive: true });
    return () => node.removeEventListener("scroll", onScroll);
  }, [rows.length, filter]);

  const detail = useAsync(async () => {
    if (!selected) return null;
    const [alert, brief] = await Promise.all([
      api.alert(selected) as Promise<AlertDetail>,
      api.brief(selected) as Promise<InspectionBrief>,
    ]);
    return { alert, brief };
  }, [selected, revision]);

  if (!config) return <LoadingState text="Загрузка очереди сигналов…" />;
  if (list.error) return <ErrorState text={list.error} onRetry={refresh} />;
  if (!list.data) return <LoadingState text="Загрузка очереди сигналов…" />;

  return (
    <div className="signals-page">
      <PageHeader
        title="Сигналы"
        lead="От наблюдения к обоснованному решению."
        extra={(
          <label className="topbar-inspector">
            <span>Инспектор</span>
            <input
              aria-label="Имя инспектора"
              placeholder="Инспектор"
              value={inspectorName}
              onChange={event => setInspectorName(event.target.value)}
            />
          </label>
        )}
      />
      <div className="page-tabs" aria-label="Статус сигналов">
        {FILTERS.map(item => (
          <button
            type="button"
            key={item}
            aria-pressed={filter === item}
            className={filter === item ? "active" : ""}
            onClick={() => setFilter(item)}
          >
            {item === "all" ? "Все" : item === "model_candidate" ? "Кандидаты модели" : statusLabel(item, config.statuses[item])}
          </button>
        ))}
      </div>
      {list.loading ? (
        <LoadingState text="Обновляем очередь…" />
      ) : rows.length || alertId ? (
        <div className="split">
          <aside ref={queueRef} className="queue" aria-label="Очередь сигналов">
            <div className="queue-heading"><span>В очереди</span><b>{current.length}</b></div>
            {groups.map(group => (
              <div className="queue-group" key={group.zone || group.zoneName}>
                <div className="queue-group-head">{group.zoneName}</div>
                {group.current.map(item => (
                  <AlertCard
                    key={item.id}
                    alert={item}
                    variant="queue"
                    active={selected === item.id}
                    all={rows}
                    onSelect={() => navigate(`/signals/${item.id}`)}
                  />
                ))}
                {group.earlier.length > 0 ? (
                  <p className="caption queue-earlier-note">Прежние наблюдения · {group.earlier.length}. Они открываются в карточке выбранного сигнала.</p>
                ) : null}
              </div>
            ))}
            {!rows.length && <p className="caption">В выбранной категории нет сигналов.</p>}
          </aside>
          <div className="signal-workspace">
            {detail.loading ? (
              <LoadingState text="Загрузка доказательств…" />
            ) : detail.error ? (
              <ErrorState text={detail.error} onRetry={refresh} />
            ) : detail.data && (
              <>
                <AlertPanel
                  detail={detail.data.alert}
                  brief={detail.data.brief}
                  config={config}
                  actor={inspectorName}
                  onDecided={() => {
                    if (selected) navigate(`/signals/${selected}`, { replace: true });
                    refresh();
                  }}
                />
                <SliceHistory items={history} activeId={selected} onOpen={id => navigate(`/signals/${id}`)} />
              </>
            )}
          </div>
        </div>
      ) : (
        <EmptyState
          title={filter === "open" ? "Очередь пуста" : "Нет сигналов с этим статусом"}
          text="Выберите другую категорию, примите кадр или перейдите к объектам."
        />
      )}
    </div>
  );
}
