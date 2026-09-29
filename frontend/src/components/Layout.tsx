import { useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import wordmark from "../assets/skripka-wordmark.png";
import { api } from "../api";
import { useAsync } from "../hooks";
import { projectLooksSynthetic } from "../labels";
import { useWorkspace } from "../workspace";
import { DemoSourceBanner, ErrorState, LoadingState } from "./PageState";

/** Светлая шапка: слово «Скрипка» и тихая навигация, без тёмной панели. */
export function Layout() {
  const location = useLocation();
  const { project, loading, error, refresh } = useWorkspace();
  const guide = location.pathname === "/project" || location.pathname === "/setup";
  const queue = useAsync(async () => {
    if (!project) return 0;
    // Counts only — full /api/alerts is multi-MB and blocked the shell.
    const summary = await api.alertSummary("open", project.code) as { total?: number; by_type?: Record<string, number> };
    const byType = summary.by_type || {};
    const reviewOnly = (byType.insufficient_evidence || 0) + (byType.model_candidate || 0);
    return Math.max(0, Number(summary.total || 0) - reviewOnly);
  }, [project?.code]);
  const openSignals = queue.data || 0;

  useEffect(() => {
    if (location.pathname === "/objects") return;
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [location.pathname, location.search]);

  const synthetic = project ? projectLooksSynthetic(project.zones) : false;

  return (
    <div className="app">
      <a className="skip-link" href="#main-content">К содержимому</a>
      <header className="mast">
        <NavLink className="mast-brand" to="/objects" end>
          <img className="brand-wordmark" src={wordmark} alt="Скрипка" />
          <span className="brand-kicker">Контроль строительства</span>
        </NavLink>
        <nav className="mast-nav" aria-label="Главная навигация">
          <NavLink
            to="/objects"
            end
            className={({ isActive }) => (
              isActive || (location.pathname.startsWith("/objects/") && !location.pathname.startsWith("/objects/new"))
                ? "active"
                : undefined
            )}
          >
            Объекты
          </NavLink>
          <NavLink to="/signals">
            Сигналы
            {openSignals > 0 ? <span className="nav-count">{openSignals}</span> : null}
          </NavLink>
          <NavLink to="/objects/new">Добавить объект</NavLink>
          <NavLink to="/project">О проекте</NavLink>
        </nav>
      </header>
      <div className="workspace">
        <main id="main-content" className="page">
          {!guide && loading && !project ? (
            <LoadingState text="Загружаем объекты…" />
          ) : !guide && error && !project ? (
            <ErrorState text={error} onRetry={refresh} />
          ) : (
            <>
              {synthetic && <DemoSourceBanner />}
              <Outlet />
            </>
          )}
        </main>
      </div>
    </div>
  );
}
