import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Model, type Version } from "../api";

export function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [models, setModels] = useState<Model[] | null>(null);
  const [versionsByModel, setVersionsByModel] = useState<Record<string, Version[]>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    api.models(projectId).then(setModels).catch((e) => setError(String(e)));
  }, [projectId]);

  async function loadVersions(modelId: string) {
    if (!projectId) return;
    if (versionsByModel[modelId]) return;
    const vs = await api.versions(projectId, modelId);
    setVersionsByModel((m) => ({ ...m, [modelId]: vs }));
  }

  if (error) return <div style={{ padding: 24, color: "#f88" }}>Error: {error}</div>;
  if (!models) return <div style={{ padding: 24 }}>Loading models…</div>;

  return (
    <div style={{ padding: 24 }}>
      <Link to="/projects" style={{ color: "#9cf" }}>
        ← All projects
      </Link>
      <h2>Models</h2>
      {models.length === 0 && <p style={{ color: "#888" }}>No models in this project.</p>}
      {models.map((m) => (
        <details
          key={m.id}
          style={{
            padding: "8px 0",
            borderBottom: "1px solid #2a2a2a",
          }}
          onToggle={(e) => {
            if ((e.target as HTMLDetailsElement).open) void loadVersions(m.id);
          }}
        >
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>
            {m.name || "(unnamed model)"}{" "}
            <span style={{ color: "#888", fontWeight: 400, fontSize: 12 }}>
              {m.id}
            </span>
          </summary>
          <div style={{ paddingLeft: 16, paddingTop: 8 }}>
            {!versionsByModel[m.id] && <div style={{ color: "#888" }}>Loading…</div>}
            {versionsByModel[m.id]?.length === 0 && (
              <div style={{ color: "#888" }}>No versions yet.</div>
            )}
            {versionsByModel[m.id]?.map((v) => (
              <div
                key={v.id}
                style={{ padding: "4px 0", display: "flex", gap: 12, alignItems: "center" }}
              >
                <Link
                  to={`/projects/${projectId}/models/${m.id}/versions/${v.id}`}
                  style={{ color: "#9cf" }}
                >
                  {v.id}
                </Link>
                <span style={{ color: "#888", fontSize: 12 }}>
                  {v.sourceApplication ?? "—"} · {new Date(v.createdAt).toLocaleString()}
                  {v.message ? ` · ${v.message}` : ""}
                </span>
              </div>
            ))}
          </div>
        </details>
      ))}
    </div>
  );
}
