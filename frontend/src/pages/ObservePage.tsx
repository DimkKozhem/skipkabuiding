import { Link, useSearchParams } from "react-router-dom";
import { EmptyState } from "../components/PageState";
import { PageHeader } from "../components/PageHeader";
import { ObserveForm } from "../components/ObserveForm";
import { useWorkspace } from "../workspace";

export function ObservePage() {
  const { project } = useWorkspace();
  const [params] = useSearchParams();
  const zoneHint = params.get("zone") || project?.zones[0]?.code || "";

  if (!project) {
    return (
      <EmptyState
        title="Нет площадки"
        text="Сначала заведите площадку и объект, затем выберите камеру."
        action={<Link className="btn" to="/setup" title="Создать площадку">Завести площадку</Link>}
      />
    );
  }

  return (
    <div>
      <PageHeader
        title="Принять кадр"
        lead="Фото или видео сохраняется как наблюдение. Сигналы считаются правилами на backend, не в браузере."
      />
      <ObserveForm project={project} zoneCode={zoneHint} />
    </div>
  );
}
