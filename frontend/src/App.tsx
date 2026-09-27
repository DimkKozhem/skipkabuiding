import { BrowserRouter, Navigate, Route, Routes, useParams, useSearchParams } from "react-router-dom";
import { Layout } from "./components/Layout";
import { HousingPage } from "./pages/HousingPage";
import { NewObjectPage } from "./pages/NewObjectPage";
import { ObjectPageView, ObjectsPage } from "./pages/ObjectPage";
import { SetupPage } from "./pages/SetupPage";
import { SignalsPage } from "./pages/SignalsPage";
import { normalizeObjectSection, objectPath } from "./routes";
import { WorkspaceProvider, useWorkspace } from "./workspace";

export function App() {
  return (
    <WorkspaceProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Navigate to="/objects" replace />} />
            <Route path="/objects" element={<ObjectsPage />} />
            <Route path="/objects/new" element={<NewObjectPage />} />
            <Route path="/objects/:zoneCode/:section" element={<ObjectPageView />} />
            <Route path="/objects/:zoneCode" element={<ObjectPageView />} />
            <Route path="/signals" element={<SignalsPage />} />
            <Route path="/signals/:alertId" element={<SignalsPage />} />
            <Route path="/project" element={<SetupPage />} />
            <Route path="/setup" element={<Navigate to="/project" replace />} />
            <Route path="/observe" element={<ObserveRedirect />} />
            <Route path="/housing" element={<HousingPage />} />
            <Route path="/alerts" element={<Navigate to="/signals" replace />} />
            <Route path="/alerts/:alertId" element={<SignalAlias />} />
            <Route path="/inspect" element={<Navigate to="/signals" replace />} />
            <Route path="/inspect/:alertId" element={<SignalAlias />} />
            <Route path="/queue" element={<Navigate to="/signals" replace />} />
            <Route path="/dashboard" element={<Navigate to="/objects" replace />} />
            <Route path="/object" element={<ObjectRedirect />} />
            <Route path="/timeline" element={<ObjectRedirect section="observations" />} />
            <Route path="*" element={<Navigate to="/objects" replace />} />          </Route>
        </Routes>
      </BrowserRouter>
    </WorkspaceProvider>
  );
}

function ObserveRedirect() {
  const [params] = useSearchParams();
  const zone = params.get("zone");
  if (!zone) return <Navigate to="/objects" replace />;
  return <Navigate to={{ pathname: objectPath(zone, "settings"), hash: "media" }} replace />;
}

function SignalAlias() {
  const { alertId } = useParams();
  return <Navigate to={`/signals/${alertId}`} replace />;
}

function ObjectRedirect({ section }: { section?: string }) {
  const [params] = useSearchParams();
  const { project } = useWorkspace();
  const zone = params.get("zone") || project?.zones[0]?.code;
  if (!zone) return <Navigate to="/objects" replace />;
  const fromTab = params.get("tab");
  const resolved = normalizeObjectSection(section || fromTab);
  return <Navigate to={objectPath(zone, resolved)} replace />;
}
