import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";
import type { InspectorConfig, ProjectDash } from "./types";

const PROJECT_KEY = "sitewatch.project";
const INSPECTOR_KEY = "sitewatch.inspector";

type WorkspaceValue = {
  projects: ProjectDash[];
  project: ProjectDash | null;
  setProjectCode: (code: string) => void;
  config: InspectorConfig | null;
  inspectorName: string;
  setInspectorName: (name: string) => void;
  loading: boolean;
  error: string;
  refresh: () => void;
  revision: number;
};

const WorkspaceContext = createContext<WorkspaceValue | null>(null);

function pickProject(rows: ProjectDash[], preferred?: string | null) {
  return rows.find(item => item.code === preferred) || rows[0] || null;
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<ProjectDash[]>([]);
  const [projectCode, setProjectCodeState] = useState(() => localStorage.getItem(PROJECT_KEY) || "");
  const [config, setConfig] = useState<InspectorConfig | null>(null);
  const [inspectorName, setInspectorNameState] = useState(() => localStorage.getItem(INSPECTOR_KEY) || "");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  const refresh = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    let alive = true;
    if (!projects.length) setLoading(true);
    Promise.all([api.projects() as Promise<ProjectDash[]>, api.inspectorConfig() as Promise<InspectorConfig>])
      .then(([rows, nextConfig]) => {
        if (!alive) return;
        setProjects(rows);
        setConfig(nextConfig);
        const preset = (nextConfig.actor_default || "").trim();
        if (!localStorage.getItem(INSPECTOR_KEY) && preset && !/^inspector$/i.test(preset)) {
          localStorage.setItem(INSPECTOR_KEY, preset);
          setInspectorNameState(preset);
        }
        setError("");
      })
      .catch(err => {
        if (alive) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [revision]);

  useEffect(() => {
    window.addEventListener("sitewatch:decision", refresh);
    window.addEventListener("sitewatch:observation", refresh);
    window.addEventListener("sitewatch:catalog", refresh);
    return () => {
      window.removeEventListener("sitewatch:decision", refresh);
      window.removeEventListener("sitewatch:observation", refresh);
      window.removeEventListener("sitewatch:catalog", refresh);
    };
  }, [refresh]);

  const setProjectCode = (code: string) => {
    localStorage.setItem(PROJECT_KEY, code);
    setProjectCodeState(code);
  };

  const setInspectorName = (name: string) => {
    localStorage.setItem(INSPECTOR_KEY, name);
    setInspectorNameState(name);
  };

  const project = pickProject(projects, projectCode);
  const value = useMemo<WorkspaceValue>(() => ({
    projects,
    project,
    setProjectCode,
    config,
    inspectorName: inspectorName && !/^inspector$/i.test(inspectorName) ? inspectorName : "",
    setInspectorName,
    loading,
    error,
    refresh,
    revision,
  }), [projects, project, config, inspectorName, loading, error, refresh, revision]);

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function pingWorkspace(kind: "decision" | "observation" | "catalog" = "catalog") {
  window.dispatchEvent(new Event(`sitewatch:${kind}`));
}

export function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("WorkspaceProvider is required");
  return value;
}
