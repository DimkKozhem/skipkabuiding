import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { WorkTree } from "../components/WorkTree";
import { ErrorState, LoadingState } from "../components/PageState";
import { PageHeader } from "../components/PageHeader";
import { Btn } from "../components/Btn";
import { useAsync } from "../hooks";
import type { ConstructionType, ConstructionWorksResponse } from "../types";
import { pingWorkspace, useWorkspace } from "../workspace";

async function ensureProjectCode(
  project: { code: string } | null,
  setProjectCode: (code: string) => void,
) {
  if (project) return project.code;
  const code = `site_${Date.now().toString(36)}`;
  const created = await api.createProject({ code, name: "Скрипка", address: "" }) as { code?: string };
  const resolved = created.code || code;
  setProjectCode(resolved);
  pingWorkspace("catalog");
  return resolved;
}

export function NewObjectPage() {
  const { project, setProjectCode } = useWorkspace();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [typeId, setTypeId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [nameError, setNameError] = useState("");
  const [typeError, setTypeError] = useState("");
  const [works, setWorks] = useState<ConstructionWorksResponse | null>(null);
  const [worksLoading, setWorksLoading] = useState(false);

  const { data: types, error: typesError, loading: typesLoading } = useAsync(
    () => api.constructionTypes() as Promise<ConstructionType[]>,
    [],
  );

  useEffect(() => {
    if (!typeId) {
      setWorks(null);
      return;
    }
    let cancelled = false;
    setWorksLoading(true);
    setWorks(null);
    api.constructionWorks(typeId)
      .then(payload => {
        if (!cancelled) setWorks(payload as ConstructionWorksResponse);
      })
      .catch(err => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Не удалось загрузить работы.");
      })
      .finally(() => {
        if (!cancelled) setWorksLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [typeId]);

  if (typesLoading && !types) return <LoadingState text="Загружаем виды строительства…" />;
  if (typesError && !types) return <ErrorState text={typesError} />;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setNameError(name.trim() ? "" : "Укажите название объекта.");
    setTypeError(typeId ? "" : "Выберите вид строительства.");
    if (!name.trim() || !typeId) return;
    setBusy(true);
    try {
      const projectCode = await ensureProjectCode(project, setProjectCode);
      const created = await api.createZone(projectCode, {
        name: name.trim(),
        description: description.trim(),
        construction_type_id: typeId,
      }) as { code: string };
      pingWorkspace("catalog");
      navigate(`/objects/${created.code}/sources?created=1`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать объект.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="new-object-page">
      <PageHeader
        title="Новый объект"
        lead="Название, описание и вид строительства. Источник, график и кадры подключаются уже внутри объекта."
      />
      <form className="panel-form object-create-form" onSubmit={onSubmit}>
        <div className="form-grid">
          <label className="span-2">
            Название
            <input value={name} onChange={event => { setName(event.target.value); setNameError(""); }} required maxLength={256} placeholder="Корпус 3" aria-invalid={nameError ? true : undefined} />
            {nameError ? <span className="form-error" role="alert">{nameError}</span> : null}
          </label>
          <label className="span-2">
            Описание <span className="caption">необязательно</span>
            <textarea
              value={description}
              onChange={event => setDescription(event.target.value)}
              rows={3}
              maxLength={2000}
              placeholder="Кратко: расположение, что важно инспектору"
            />
          </label>
          <label className="span-2">
            Вид строительства
            <select
              value={typeId}
              onChange={event => { setTypeId(event.target.value); setTypeError(""); }}
              required
              aria-invalid={typeError ? true : undefined}
              aria-label="Вид строительства"
            >
              <option value="">Выберите вид</option>
              {(types || []).map(item => (
                <option key={item.id} value={item.id}>{item.name}</option>
              ))}
            </select>
            {typeError ? <span className="form-error" role="alert">{typeError}</span> : null}
          </label>
        </div>
        {typeId && (
          <section className="section">
            <div className="section-head">
              <h2>Работы вида «{(types || []).find(item => item.id === typeId)?.name || typeId}»</h2>
              <span className="caption">Справочник, не календарный план</span>
            </div>
            {worksLoading ? <LoadingState text="Загружаем справочник работ…" /> : <WorkTree data={works} mode="preview" />}
          </section>
        )}
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="inline">
          <Btn type="submit" busy={busy} title="Создать объект и открыть рабочее пространство">
            Создать объект
          </Btn>
          <Link className="btn ghost" to="/objects">Отмена</Link>
        </div>
      </form>
    </div>
  );
}
