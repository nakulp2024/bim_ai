import { Uploader } from "./components/Uploader";
import { Viewer } from "./components/Viewer";
import { ElementSidebar } from "./components/ElementSidebar";
import { glbUrl } from "./api";
import { useAppStore } from "./store";

export function App() {
  const projectId = useAppStore((s) => s.projectId);
  const status = useAppStore((s) => s.status);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "320px 1fr",
        gridTemplateRows: "auto auto 1fr",
        height: "100vh",
        width: "100vw",
      }}
    >
      <div
        style={{
          gridColumn: "1 / span 2",
          padding: "8px 12px",
          background: "#111",
          borderBottom: "1px solid #333",
          display: "flex",
          alignItems: "center",
          gap: 16,
        }}
      >
        <strong>BIM AI — M1 Viewer</strong>
        <span style={{ color: "#888" }}>{status}</span>
      </div>

      <div style={{ gridColumn: "1 / span 2" }}>
        <Uploader />
      </div>

      <div style={{ borderRight: "1px solid #333", overflow: "hidden" }}>
        <ElementSidebar />
      </div>

      <div style={{ position: "relative" }}>
        <Viewer glbUrl={projectId ? glbUrl(projectId) : null} />
      </div>
    </div>
  );
}
