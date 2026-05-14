import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Viewer,
  DefaultViewerParams,
  SpeckleLoader,
  UrlHelper,
  CameraController,
  SelectionExtension,
} from "@speckle/viewer";
import { useStore } from "../store";

export function ViewerPage() {
  const { projectId, modelId, versionId } = useParams<{
    projectId: string;
    modelId: string;
    versionId: string;
  }>();
  const me = useStore((s) => s.me);
  const containerRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState("Initialising viewer…");

  useEffect(() => {
    if (!containerRef.current || !me || !projectId || !modelId || !versionId) return;
    const container = containerRef.current;
    let viewer: Viewer | null = null;
    let cancelled = false;

    (async () => {
      viewer = new Viewer(container, DefaultViewerParams);
      await viewer.init();
      viewer.createExtension(CameraController);
      viewer.createExtension(SelectionExtension);

      const resource = `${me.speckle_public_url}/projects/${projectId}/models/${modelId}@${versionId}`;
      setStatus("Resolving resource…");
      const urls = await UrlHelper.getResourceUrls(resource, me.speckle_token);
      if (cancelled) return;

      setStatus(`Loading ${urls.length} object(s)…`);
      for (const url of urls) {
        if (cancelled) return;
        await viewer.loadObject(
          new SpeckleLoader(viewer.getWorldTree(), url, me.speckle_token)
        );
      }
      if (!cancelled) setStatus("");
    })().catch((e) => {
      // eslint-disable-next-line no-console
      console.error(e);
      setStatus(`Error: ${e}`);
    });

    return () => {
      cancelled = true;
      try {
        viewer?.dispose();
      } catch {
        // ignore
      }
    };
  }, [me, projectId, modelId, versionId]);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateRows: "auto 1fr",
        height: "100vh",
        width: "100vw",
      }}
    >
      <div
        style={{
          padding: "8px 12px",
          background: "#111",
          borderBottom: "1px solid #333",
          display: "flex",
          gap: 12,
          alignItems: "center",
        }}
      >
        <Link to={`/projects/${projectId}`} style={{ color: "#9cf" }}>
          ← back
        </Link>
        <span style={{ color: "#888", fontSize: 12 }}>
          {projectId} / {modelId} @ {versionId}
        </span>
        <Link
          to={`/projects/${projectId}/models/${modelId}/versions/${versionId}/schedule`}
          style={{ color: "#9cf", marginLeft: "auto" }}
        >
          Schedule →
        </Link>
        <span style={{ color: "#888", fontSize: 12 }}>{status}</span>
      </div>
      <div ref={containerRef} style={{ position: "relative", overflow: "hidden" }} />
    </div>
  );
}
