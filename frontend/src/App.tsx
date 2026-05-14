import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api } from "./api";
import { clearToken, getToken } from "./auth";
import { useStore } from "./store";
import { AuthCallbackPage } from "./pages/AuthCallbackPage";
import { LoginPage } from "./pages/LoginPage";
import { ProjectPage } from "./pages/ProjectPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ViewerPage } from "./pages/ViewerPage";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const me = useStore((s) => s.me);
  const setMe = useStore((s) => s.setMe);
  const [checking, setChecking] = useState(!me);
  const nav = useNavigate();

  useEffect(() => {
    if (me) return;
    const tok = getToken();
    if (!tok) {
      nav("/", { replace: true });
      return;
    }
    api
      .me()
      .then((m) => {
        setMe(m);
        setChecking(false);
      })
      .catch(() => {
        clearToken();
        nav("/", { replace: true });
      });
  }, [me, nav, setMe]);

  if (checking) return <div style={{ padding: 24 }}>Loading…</div>;
  return <>{children}</>;
}

function Topbar() {
  const me = useStore((s) => s.me);
  const setMe = useStore((s) => s.setMe);
  const nav = useNavigate();
  if (!me) return null;
  return (
    <div
      style={{
        padding: "6px 12px",
        background: "#0f1318",
        borderBottom: "1px solid #222",
        display: "flex",
        gap: 12,
        alignItems: "center",
        fontSize: 13,
      }}
    >
      <strong>BIM AI</strong>
      <span style={{ color: "#888", marginLeft: "auto" }}>
        {me.name ?? me.email ?? me.speckle_user_id}
      </span>
      <button
        onClick={() => {
          clearToken();
          setMe(null);
          nav("/", { replace: true });
        }}
        style={{
          background: "transparent",
          border: "1px solid #333",
          color: "#ccc",
          padding: "4px 10px",
          borderRadius: 3,
          cursor: "pointer",
        }}
      >
        Sign out
      </button>
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<LoginPage />} />
      <Route path="/auth/callback" element={<AuthCallbackPage />} />
      <Route
        path="/projects"
        element={
          <RequireAuth>
            <div>
              <Topbar />
              <ProjectsPage />
            </div>
          </RequireAuth>
        }
      />
      <Route
        path="/projects/:projectId"
        element={
          <RequireAuth>
            <div>
              <Topbar />
              <ProjectPage />
            </div>
          </RequireAuth>
        }
      />
      <Route
        path="/projects/:projectId/models/:modelId/versions/:versionId"
        element={
          <RequireAuth>
            <ViewerPage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
