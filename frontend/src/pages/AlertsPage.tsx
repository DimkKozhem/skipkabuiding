import { Navigate, useParams, useSearchParams } from "react-router-dom";

export function AlertsPage() {
  const { alertId } = useParams();
  return <Navigate to={alertId ? `/signals/${alertId}` : "/signals"} replace />;
}

export function QueuePage() {
  return <Navigate to="/signals" replace />;
}

export function TimelinePage() {
  const [params] = useSearchParams();
  const zone = params.get("zone") || "building_01";
  return <Navigate to={`/objects/${zone}/history`} replace />;
}
