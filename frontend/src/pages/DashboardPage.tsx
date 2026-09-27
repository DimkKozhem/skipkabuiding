import { Link } from "react-router-dom";
import { api } from "../api";
import { AlertCard } from "../components/AlertCard";
import { EmptyState, ErrorState, LoadingState } from "../components/PageState";
import { PageHeader } from "../components/PageHeader";
import { ObjectRegister } from "../components/ObjectRegister";
import { Icon } from "../components/Icon";
import { useAsync } from "../hooks";
import { currentAlerts, sortAttentionAlerts } from "../labels";
import type { AlertListItem, CaptureStatus, ZoneDash } from "../types";
import { useWorkspace } from "../workspace";

/** Агрегация полосы статуса из уже отданных зон — не пересчёт приоритета. */
function vitrineStrip(zones: ZoneDash[]) {
  const delay = zones.filter(
    zone =>
      zone.schedule_delay ||
      zone.confirmed_schedule_delay ||
      zone.primary_badge === "schedule_delay" ||
      zone.card_state === "confirmed",
  ).length;
  const noDynamics = zones.filter(
    zone => (zone.no_dynamics || 0) > 0 || zone.primary_badge === "no_dynamics" || (zone.alert_counts?.no_dynamics || 0) > 0,
  ).length;
  const stale = zones.filter(zone => zone.stale || zone.card_state === "stale" || zone.card_state === "no_frame").length;
  const onPlan = zones.filter(zone => zone.card_state === "on_plan").length;
  return { delay, noDynamics, stale, onPlan };
}

export function DashboardPage() {
  const { project } = useWorkspace();
  const { data, error, loading } = useAsync(async () => {
    if (!project) return [] as AlertListItem[];
    return sortAttentionAlerts(await api.alerts("open", project.code) as AlertListItem[]);
  }, [project?.code, project?.alert_counts?.open]);
  const { data: capture } = useAsync(async () => api.captureStatus() as Promise<CaptureStatus>, [project?.code]);

  if (!project) return (
    <EmptyState
      title="Пока нет объектов"
      text="Заведите площадку, подгрузите график и подключите источники. Сигналы появятся после первых кадров."
      action={<Link className="btn" to="/setup" title="Создать площадку и объекты">Завести площадку<Icon name="plus" /></Link>}
    />
  );
  if (loading && !data) return <LoadingState text="Собираем сводку по площадке…" />;
  if (error) return <ErrorState text={error} />;

  const alerts = currentAlerts(data || []);
  const zones = project.zones;
  const strip = vitrineStrip(zones);
  const loopOn = Boolean(capture?.loop);
  const intervalMin = capture?.interval_default_minutes ?? 30;

  return (
    <div className="overview-page">
      <PageHeader
        title={project.name}
        lead="Где сейчас требуется внимание: кадр объекта, пункт графика и признаки для проверки."
        extra={
          <div className="header-actions">
            <Link className="btn ghost" to="/objects/new" title="Создать объект">Новый объект</Link>
            <Link className="btn" to="/observe" title="Загрузить фото или видео">
              Принять кадр
              <Icon name="plus" />
            </Link>
          </div>
        }
      />

      <div className="vitrine-strip" aria-label="Состояние площадки">
        <span><strong>{zones.length}</strong> объектов</span>
        <span><strong>{strip.delay}</strong> с отставанием</span>
        <span><strong>{strip.noDynamics}</strong> без динамики</span>
        <span><strong>{strip.stale}</strong> без свежих данных</span>
        <span><strong>{strip.onPlan}</strong> по плану</span>
      </div>

      <section className="section vitrine-section" aria-label="Витрина объектов">
        <div className="section-head">
          <h2>Объекты площадки</h2>
          <Link className="text-link" to="/objects">Все объекты <Icon name="arrow" /></Link>
        </div>
        {zones.length ? (
          <ObjectRegister zones={zones} />
        ) : (
          <EmptyState
            title="Нет зон"
            text={
              loopOn
                ? `Автосъёмка включена (интервал камеры ≈ ${intervalMin} мин). Появятся кадры — зоны заполнятся.`
                : "Автосъёмка выключена. Кадр принимается вручную — загрузите фото или видео."
            }
            action={<Link className="btn ghost" to="/observe">Принять кадр</Link>}
          />
        )}
      </section>

      <section className="section signals-aside" aria-label="Сигналы">
        <div className="section-head">
          <h2>
            Сигналы
            {alerts.length ? <span className="section-count">{alerts.length}</span> : null}
          </h2>
          <Link className="text-link" to="/signals">Очередь <Icon name="arrow" /></Link>
        </div>
        {alerts.length ? (
          <div className="signal-register compact-signals">
            {alerts.slice(0, 4).map(alert => (
              <AlertCard key={alert.id} alert={alert} all={data || []} />
            ))}
          </div>
        ) : (
          <p className="caption signals-empty">
            {loopOn
              ? `Открытых сигналов нет. Камеры снимают примерно каждые ${intervalMin} мин.`
              : "Открытых сигналов нет. Автосъёмка выключена — кадр принимается вручную."}
          </p>
        )}
      </section>

      <p className="system-foot">Сигналы указывают на признаки отклонений. Итоговое решение принимает инспектор.</p>
    </div>
  );
}
