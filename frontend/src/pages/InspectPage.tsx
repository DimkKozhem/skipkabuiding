import { Navigate } from "react-router-dom";
import { SignalsPage } from "./SignalsPage";

export function InspectPage() {
  return <SignalsPage />;
}

export function AlertsPage() {
  return <Navigate to="/signals" replace />;
}

export function QueuePage() {
  return <Navigate to="/signals" replace />;
}
