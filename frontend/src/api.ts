async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers || {});
  const isForm = typeof FormData !== "undefined" && init?.body instanceof FormData;
  if (!isForm && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, {
    cache: "no-store",
    ...init,
    headers,
  });
  if (!response.ok) {
    const text = await response.text();
    let detail = "";
    try { detail = JSON.parse(text).detail; } catch { /* Non-JSON upstream response. */ }
    throw new Error(response.status === 404 ? "Запись больше не доступна. Обновите данные." :
      typeof detail === "string" && detail ? detail : "Не удалось получить данные. Попробуйте ещё раз.");
  }
  return response.json() as Promise<T>;
}

function alertsPath(status?: string, project?: string, type?: string, limit?: number, offset?: number) {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (project) params.set("project", project);
  if (type) params.set("type", type);
  if (limit != null) params.set("limit", String(limit));
  if (offset) params.set("offset", String(offset));
  const query = params.toString();
  return `/api/alerts${query ? `?${query}` : ""}`;
}

export const api = {
  inspectorConfig: () => request("/api/inspector/config"),
  projects: () => request("/api/projects"),
  objectPage: (project: string, zone: string) => request(`/api/projects/${project}/zones/${zone}`),
  timeline: (project: string, zone: string) => request(`/api/projects/${project}/zones/${zone}/timeline`),
  alerts: (status?: string, project?: string, type?: string, limit?: number, offset?: number) =>
    request(alertsPath(status, project, type, limit, offset)),
  alertSummary: (status?: string, project?: string) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (project) params.set("project", project);
    const query = params.toString();
    return request(`/api/alerts/summary${query ? `?${query}` : ""}`);
  },
  queue: (status = "open") => request(`/api/queue?status=${encodeURIComponent(status)}`),
  alert: (id: string) => request(`/api/alerts/${id}`),
  brief: (id: string) => request(`/api/alerts/${id}/brief`),
  decide: (id: string, body: { status: string; reason?: string; note?: string; actor?: string }) =>
    request(`/api/alerts/${id}/decision`, { method: "POST", body: JSON.stringify(body) }),
  reviewCandidate: (id: string, body: {
    source: string;
    verdict: "correct" | "incorrect" | "indeterminate";
    wrong_type?: string;
    missed_object?: string;
    actor?: string;
  }) => request(`/api/alerts/${id}/candidate-review`, { method: "POST", body: JSON.stringify(body) }),
  factReview: (project: string, zone: string, body: {
    observation_id: string;
    indicator_id?: string;
    action: "confirm" | "correct" | "reject" | "needs_other_frame";
    value?: number | string | boolean | null;
    actor?: string;
    note?: string;
  }) => request(`/api/projects/${encodeURIComponent(project)}/zones/${encodeURIComponent(zone)}/fact-review`, {
    method: "POST",
    body: JSON.stringify(body),
  }),
  uploadObservation: (body: FormData) => request("/api/observations/upload", { method: "POST", body }),
  deleteObservation: (id: string) => request(`/api/observations/${encodeURIComponent(id)}`, { method: "DELETE" }),
  catalogStages: () => request("/api/catalog/stages"),
  constructionTypes: () => request("/api/catalog/construction-types"),
  constructionWorks: (typeId: string) =>
    request(`/api/catalog/construction-types/${encodeURIComponent(typeId)}/works`),
  createProject: (body: { code: string; name: string; address?: string }) =>
    request("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  updateProject: (code: string, body: { name?: string; address?: string }) =>
    request(`/api/projects/${code}`, { method: "PATCH", body: JSON.stringify(body) }),
  createZone: (project: string, body: {
    code?: string;
    name: string;
    description?: string;
    construction_type_id?: string | null;
  }) =>
    request(`/api/projects/${project}/zones`, { method: "POST", body: JSON.stringify(body) }),
  updateZone: (project: string, zone: string, body: {
    name?: string;
    description?: string;
    construction_type_id?: string | null;
  }) =>
    request(`/api/projects/${project}/zones/${zone}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteZone: (project: string, zone: string) =>
    request(`/api/projects/${project}/zones/${zone}`, { method: "DELETE" }),
  zoneNotes: (project: string, zone: string) =>
    request(`/api/projects/${project}/zones/${zone}/notes`),
  createZoneNote: (project: string, zone: string, body: { body: string; author?: string }) =>
    request(`/api/projects/${project}/zones/${zone}/notes`, { method: "POST", body: JSON.stringify(body) }),
  createCamera: (project: string, zone: string, body: Record<string, unknown>) =>
    request(`/api/projects/${project}/zones/${zone}/cameras`, { method: "POST", body: JSON.stringify(body) }),
  updateCamera: (code: string, body: Record<string, unknown>) =>
    request(`/api/cameras/${code}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteCamera: (code: string) => request(`/api/cameras/${code}`, { method: "DELETE" }),
  createStage: (project: string, zone: string, body: Record<string, unknown>) =>
    request(`/api/projects/${project}/zones/${zone}/ksg`, { method: "POST", body: JSON.stringify(body) }),
  updateStage: (id: string, body: Record<string, unknown>) =>
    request(`/api/ksg/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteStage: (id: string) => request(`/api/ksg/${id}`, { method: "DELETE" }),
  importKsg: (project: string, zone: string, body: FormData) =>
    request(`/api/projects/${project}/zones/${zone}/ksg/import`, { method: "POST", body }),
  captureStatus: () => request("/api/capture/status"),
  captureRun: (body: { camera?: string; project?: string; zone?: string; force?: boolean }) =>
    request("/api/capture/run", { method: "POST", body: JSON.stringify(body) }),
  housingSchedule: (projectId = "housing_16") =>
    request(`/api/projects/${projectId}/schedule`),
  housingUploadSchedule: (body: FormData, projectId = "housing_16") =>
    request(`/api/projects/${projectId}/schedule`, { method: "POST", body }),
  housingRun: (projectId = "housing_16") =>
    request(`/api/projects/${projectId}/run`, { method: "POST" }),
};
