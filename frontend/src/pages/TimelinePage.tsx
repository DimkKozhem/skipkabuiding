import { Navigate, useSearchParams } from "react-router-dom";

/** Legacy alias → история объекта. */
export function TimelinePage() {
  const [params] = useSearchParams();
  const zone = params.get("zone") || "building_01";
  return <Navigate to={`/objects/${zone}/history`} replace />;
}
