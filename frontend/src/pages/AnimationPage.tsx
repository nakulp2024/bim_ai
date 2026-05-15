import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Viewer,
  DefaultViewerParams,
  SpeckleLoader,
  UrlHelper,
  CameraController,
  FilteringExtension,
} from "@speckle/viewer";
import { api, type AnimationView } from "../api";
import { useStore } from "../store";
import { AnimationPlayer } from "../animation/Player";

const SPEEDS = [0.5, 1, 2, 4, 8];

export function AnimationPage() {
  const { projectId, modelId, versionId, scheduleId } = useParams<{
    projectId: string;
    modelId: string;
    versionId: string;
    scheduleId: string;
  }>();
  const me = useStore((s) => s.me);
  const containerRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<AnimationPlayer | null>(null);
  const playingRef = useRef(false);
  const lastTickRef = useRef<number | null>(null);
  const speedRef = useRef(1);
  const [animation, setAnimation] = useState<AnimationView | null>(null);
  const [day, setDay] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [status, setStatus] = useState("Loading animation…");

  // Fetch animation script.
  useEffect(() => {
    if (!scheduleId) return;
    api.animation(scheduleId).then(setAnimation).catch((e) => setStatus(String(e)));
  }, [scheduleId]);

  // Boot viewer + player.
  useEffect(() => {
    if (!containerRef.current || !me || !animation || !animation.script) return;
    const container = containerRef.current;
    let viewer: Viewer | null = null;
    let frameHandle: number | null = null;
    let cancelled = false;

    (async () => {
      viewer = new Viewer(container, DefaultViewerParams);
      await viewer.init();
      viewer.createExtension(CameraController);
      const filtering = viewer.createExtension(FilteringExtension);

      const resource = `${me.speckle_public_url}/projects/${animation.speckle_project_id}/models/${animation.speckle_model_id}@${animation.speckle_version_id}`;
      setStatus("Resolving model resource…");
      const urls = await UrlHelper.getResourceUrls(resource, me.speckle_token);
      if (cancelled) return;
      setStatus(`Loading ${urls.length} object(s)…`);
      for (const url of urls) {
        if (cancelled) return;
        await viewer.loadObject(
          new SpeckleLoader(viewer.getWorldTree(), url, me.speckle_token),
        );
      }
      if (cancelled) return;

      const player = new AnimationPlayer({
        filtering,
        script: animation.script!,
        taskToSpeckle: animation.task_to_speckle ?? {},
      });
      playerRef.current = player;
      player.seek(0, true);
      setStatus("");

      const loop = (now: number) => {
        if (cancelled) return;
        if (playingRef.current) {
          if (lastTickRef.current != null) {
            const dt = (now - lastTickRef.current) / 1000; // seconds
            const next = (playerRef.current?.day ?? 0) + dt * speedRef.current;
            if (next >= player.duration) {
              playerRef.current?.seek(player.duration, true);
              playingRef.current = false;
              setPlaying(false);
              setDay(player.duration);
            } else {
              playerRef.current?.seek(next);
              setDay(next);
            }
          }
          lastTickRef.current = now;
        } else {
          lastTickRef.current = null;
        }
        frameHandle = requestAnimationFrame(loop);
      };
      frameHandle = requestAnimationFrame(loop);
    })().catch((e) => {
      // eslint-disable-next-line no-console
      console.error(e);
      setStatus(`Error: ${e}`);
    });

    return () => {
      cancelled = true;
      if (frameHandle != null) cancelAnimationFrame(frameHandle);
      try {
        playerRef.current?.reset();
      } catch {
        // ignore
      }
      playerRef.current = null;
      try {
        viewer?.dispose();
      } catch {
        // ignore
      }
    };
  }, [me, animation]);

  const onTogglePlay = () => {
    const next = !playing;
    setPlaying(next);
    playingRef.current = next;
  };

  const onScrub = (n: number) => {
    setDay(n);
    playerRef.current?.seek(n, true);
  };

  const onSpeed = (s: number) => {
    setSpeed(s);
    speedRef.current = s;
  };

  const script = animation?.script ?? null;
  const startDate = script?.start_date ? new Date(script.start_date) : null;
  const currentDate = startDate
    ? new Date(startDate.getTime() + Math.floor(day) * 86400_000)
    : null;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateRows: "auto 1fr auto",
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
        <Link
          to={`/projects/${projectId}/models/${modelId}/versions/${versionId}/schedule`}
          style={{ color: "#9cf" }}
        >
          ← back
        </Link>
        <span style={{ color: "#888", fontSize: 12 }}>
          schedule {scheduleId} · {script?.tasks.length ?? 0} tasks
        </span>
        <span style={{ color: "#888", fontSize: 12, marginLeft: "auto" }}>
          {status}
        </span>
      </div>

      <div ref={containerRef} style={{ position: "relative", overflow: "hidden" }} />

      {script && (
        <div
          style={{
            padding: 12,
            background: "#0f1318",
            borderTop: "1px solid #333",
            display: "grid",
            gridTemplateColumns: "auto 1fr auto auto",
            gap: 12,
            alignItems: "center",
          }}
        >
          <button
            onClick={onTogglePlay}
            style={{
              background: playing ? "#7a3a3a" : "#3a7",
              color: "#fff",
              border: "none",
              padding: "6px 14px",
              borderRadius: 4,
              cursor: "pointer",
              minWidth: 80,
            }}
          >
            {playing ? "Pause" : "Play"}
          </button>
          <input
            type="range"
            min={0}
            max={script.duration_days}
            step={1}
            value={Math.floor(day)}
            onChange={(e) => onScrub(Number(e.target.value))}
            style={{ width: "100%" }}
          />
          <div style={{ minWidth: 220, color: "#ccc", fontSize: 12, textAlign: "right" }}>
            day {Math.floor(day)} / {script.duration_days}
            {currentDate && ` · ${currentDate.toISOString().slice(0, 10)}`}
          </div>
          <div style={{ display: "flex", gap: 4 }}>
            {SPEEDS.map((s) => (
              <button
                key={s}
                onClick={() => onSpeed(s)}
                style={{
                  background: speed === s ? "#3a7" : "transparent",
                  color: "#fff",
                  border: "1px solid #333",
                  padding: "4px 8px",
                  borderRadius: 3,
                  cursor: "pointer",
                  fontSize: 12,
                }}
              >
                {s}×
              </button>
            ))}
          </div>

          <div
            style={{
              gridColumn: "1 / -1",
              display: "flex",
              gap: 10,
              flexWrap: "wrap",
              alignItems: "center",
              fontSize: 12,
            }}
          >
            {script.phases.map((p) => (
              <div key={p.name} style={{ display: "flex", gap: 4, alignItems: "center" }}>
                <span
                  style={{
                    width: 12,
                    height: 12,
                    background: p.color_hex,
                    display: "inline-block",
                    borderRadius: 2,
                  }}
                />
                <span style={{ color: "#bbb" }}>
                  {p.name} ({p.task_ids.length})
                </span>
              </div>
            ))}
            <span style={{ color: "#666", marginLeft: "auto" }}>
              orange = in-progress
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
