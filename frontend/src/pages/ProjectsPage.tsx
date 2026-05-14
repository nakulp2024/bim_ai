import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Project } from "../api";

export function ProjectsPage() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.projects().then(setProjects).catch((e) => setError(String(e)));
  }, []);

  if (error) return <div style={{ padding: 24, color: "#f88" }}>Error: {error}</div>;
  if (!projects) return <div style={{ padding: 24 }}>Loading projects…</div>;

  return (
    <div style={{ padding: 24 }}>
      <h2>Your Speckle projects</h2>
      {projects.length === 0 && (
        <p style={{ color: "#888" }}>
          No projects yet. Create one in Speckle and push a model.
        </p>
      )}
      <ul style={{ listStyle: "none", padding: 0 }}>
        {projects.map((p) => (
          <li
            key={p.id}
            style={{
              padding: 12,
              borderBottom: "1px solid #2a2a2a",
            }}
          >
            <Link
              to={`/projects/${p.id}`}
              style={{ color: "#9cf", textDecoration: "none", fontWeight: 600 }}
            >
              {p.name}
            </Link>
            <div style={{ color: "#888", fontSize: 12 }}>
              {p.id} · updated {new Date(p.updatedAt).toLocaleString()}
              {p.role ? ` · ${p.role}` : ""}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
