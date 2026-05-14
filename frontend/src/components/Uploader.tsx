import { useRef, useState } from "react";
import { createProject, fetchElements, uploadIfc } from "../api";
import { useAppStore } from "../store";

export function Uploader() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const setProjectId = useAppStore((s) => s.setProjectId);
  const setElements = useAppStore((s) => s.setElements);
  const setStatus = useAppStore((s) => s.setStatus);

  const onPick = async (file: File) => {
    setBusy(true);
    try {
      setStatus("Creating project…");
      const projectId = await createProject();
      setStatus(`Uploading & parsing ${file.name} (this may take a minute)…`);
      const result = await uploadIfc(projectId, file);
      setStatus(`Parsed ${result.element_count} elements. Loading viewer…`);
      const els = await fetchElements(projectId);
      setElements(els);
      setProjectId(projectId);
      setStatus(`Ready. ${result.element_count} elements.`);
    } catch (e) {
      setStatus(`Error: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ padding: "8px 12px", borderBottom: "1px solid #333" }}>
      <input
        ref={inputRef}
        type="file"
        accept=".ifc"
        style={{ display: "none" }}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void onPick(f);
          e.target.value = "";
        }}
      />
      <button
        disabled={busy}
        onClick={() => inputRef.current?.click()}
        style={{
          background: busy ? "#444" : "#3a7",
          color: "#fff",
          border: "none",
          padding: "8px 14px",
          borderRadius: 4,
          cursor: busy ? "wait" : "pointer",
        }}
      >
        {busy ? "Processing…" : "Upload IFC"}
      </button>
    </div>
  );
}
