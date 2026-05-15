import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  api,
  type ColumnMapping,
  type JobStatus,
  type JoinStrategy,
  type MappingProposalBody,
  type MappingView,
  type Role,
} from "../api";

interface ResolutionStats {
  total_links: number;
  matched_tasks: number;
}

const ROLES: Role[] = [
  "task_id",
  "name",
  "start",
  "end",
  "wbs",
  "phase",
  "join_key",
  "activity",
  "ignored",
];

const JOIN_STRATEGIES: JoinStrategy[] = [
  "application_id",
  "category_and_level",
  "type_and_level",
  "name_fuzzy",
  "wbs_pattern",
];

export function SchedulePage() {
  const { projectId, modelId, versionId } = useParams<{
    projectId: string;
    modelId: string;
    versionId: string;
  }>();
  const [scheduleId, setScheduleId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [mapping, setMapping] = useState<MappingView | null>(null);
  const [edited, setEdited] = useState<MappingProposalBody | null>(null);
  const [status, setStatus] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [confirmedAt, setConfirmedAt] = useState<string | null>(null);
  const [resolveJob, setResolveJob] = useState<JobStatus | null>(null);
  const [resolution, setResolution] = useState<ResolutionStats | null>(null);
  const [generating, setGenerating] = useState(false);
  const [genJob, setGenJob] = useState<JobStatus | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const nav = useNavigate();

  // Poll the job until ready/failed.
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const j = await api.job(jobId);
        if (cancelled) return;
        setJob(j);
        if (j.state === "ready") {
          const m = await api.mapping(scheduleId!);
          if (cancelled) return;
          setMapping(m);
          setEdited(m.proposed);
          setConfirmedAt(m.confirmed_at ?? null);
          setStatus("");
          return;
        }
        if (j.state === "failed") {
          setStatus(`Job failed: ${j.error ?? "unknown error"}`);
          return;
        }
        setTimeout(tick, 1500);
      } catch (e) {
        setStatus(`Polling error: ${(e as Error).message}`);
      }
    };
    void tick();
    return () => {
      cancelled = true;
    };
  }, [jobId, scheduleId]);

  const onPick = async (file: File) => {
    if (!projectId || !modelId || !versionId) return;
    setStatus("Uploading schedule…");
    setMapping(null);
    setEdited(null);
    setConfirmedAt(null);
    setJob(null);
    try {
      const r = await api.uploadSchedule({
        file,
        speckle_project_id: projectId,
        speckle_model_id: modelId,
        speckle_version_id: versionId,
      });
      setScheduleId(r.schedule_id);
      setJobId(r.job_id);
      setStatus(
        `Uploaded ${file.name}: ${r.row_count} rows, ${r.headers.length} columns. Mapping…`,
      );
    } catch (e) {
      setStatus(`Upload failed: ${(e as Error).message}`);
    }
  };

  const updateMapping = (idx: number, patch: Partial<ColumnMapping>) => {
    if (!edited) return;
    const next = { ...edited, mapping: edited.mapping.slice() };
    next.mapping[idx] = { ...next.mapping[idx], ...patch };
    setEdited(next);
  };

  const onConfirm = async () => {
    if (!scheduleId || !edited) return;
    setConfirming(true);
    setResolution(null);
    setResolveJob(null);
    try {
      const r = await api.confirmMapping(scheduleId, edited);
      setConfirmedAt(new Date().toISOString());
      setStatus("Mapping saved. Resolving rows…");
      void pollResolveJob(r.job_id);
    } catch (e) {
      setStatus(`Save failed: ${(e as Error).message}`);
    } finally {
      setConfirming(false);
    }
  };

  const pollResolveJob = async (jId: string) => {
    while (true) {
      try {
        const j = await api.job(jId);
        setResolveJob(j);
        if (j.state === "ready") {
          if (scheduleId) setResolution(await api.resolution(scheduleId));
          setStatus("Resolution complete.");
          return;
        }
        if (j.state === "failed") {
          setStatus(`Resolution failed: ${j.error ?? "unknown"}`);
          return;
        }
      } catch (e) {
        setStatus(`Polling error: ${(e as Error).message}`);
        return;
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
  };

  const onGenerateAnimation = async () => {
    if (!scheduleId) return;
    setGenerating(true);
    setGenJob(null);
    try {
      const r = await api.triggerAnimation(scheduleId);
      setStatus("Generating animation…");
      void pollAnimationJob(r.job_id);
    } catch (e) {
      setStatus(`Animation kick-off failed: ${(e as Error).message}`);
    } finally {
      setGenerating(false);
    }
  };

  const pollAnimationJob = async (jId: string) => {
    while (true) {
      try {
        const j = await api.job(jId);
        setGenJob(j);
        if (j.state === "ready") {
          setStatus("Animation ready.");
          if (projectId && modelId && versionId && scheduleId) {
            nav(
              `/projects/${projectId}/models/${modelId}/versions/${versionId}/schedule/${scheduleId}/animation`,
            );
          }
          return;
        }
        if (j.state === "failed") {
          setStatus(`Animation failed: ${j.error ?? "unknown"}`);
          return;
        }
      } catch (e) {
        setStatus(`Polling error: ${(e as Error).message}`);
        return;
      }
      await new Promise((r) => setTimeout(r, 2000));
    }
  };

  return (
    <div style={{ padding: 24, maxWidth: 1100, margin: "0 auto" }}>
      <Link to={`/projects/${projectId}/models/${modelId}/versions/${versionId}`} style={{ color: "#9cf" }}>
        ← Back to viewer
      </Link>
      <h2 style={{ marginTop: 12 }}>Schedule mapping</h2>
      <p style={{ color: "#888" }}>
        Upload an Excel or CSV schedule. Claude will propose how the columns map
        to the Speckle model; review and confirm.
      </p>

      <div style={{ margin: "12px 0", display: "flex", gap: 12, alignItems: "center" }}>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.xlsx,.xls"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void onPick(f);
            e.target.value = "";
          }}
        />
        <button
          onClick={() => inputRef.current?.click()}
          style={{
            background: "#3a7",
            color: "#fff",
            border: "none",
            padding: "8px 14px",
            borderRadius: 4,
            cursor: "pointer",
          }}
        >
          Upload schedule
        </button>
        <span style={{ color: "#888" }}>{status}</span>
      </div>

      {job && job.state !== "ready" && (
        <div style={{ padding: 12, background: "#181d22", borderRadius: 4, marginBottom: 16 }}>
          <div style={{ color: "#888", fontSize: 12 }}>Job: {job.state}</div>
          <div style={{ fontSize: 13 }}>{job.message}</div>
          {typeof job.progress === "number" && (
            <div
              style={{
                background: "#222",
                height: 4,
                borderRadius: 2,
                marginTop: 6,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  background: "#3a7",
                  height: "100%",
                  width: `${Math.round(job.progress * 100)}%`,
                  transition: "width 200ms ease",
                }}
              />
            </div>
          )}
        </div>
      )}

      {mapping && edited && (
        <div>
          <div
            style={{
              display: "flex",
              gap: 16,
              alignItems: "center",
              marginBottom: 12,
            }}
          >
            <strong>Proposed mapping</strong>
            <span
              style={{
                padding: "2px 8px",
                background:
                  (mapping.confidence ?? 0) >= 0.7 ? "#1d6f3c" : "#7a5300",
                borderRadius: 10,
                fontSize: 12,
              }}
            >
              confidence {((mapping.confidence ?? 0) * 100).toFixed(0)}%
            </span>
            <select
              value={edited.join_strategy}
              onChange={(e) =>
                setEdited({ ...edited, join_strategy: e.target.value as JoinStrategy })
              }
              style={{
                background: "#111",
                color: "#eee",
                border: "1px solid #333",
                padding: "4px 8px",
                borderRadius: 3,
              }}
            >
              {JOIN_STRATEGIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          {mapping.rationale && (
            <details style={{ marginBottom: 12 }}>
              <summary style={{ cursor: "pointer", color: "#888" }}>
                Claude's rationale
              </summary>
              <div style={{ padding: 8, fontSize: 13, color: "#ccc" }}>
                {mapping.rationale}
              </div>
            </details>
          )}

          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #333", color: "#888" }}>
                <th style={{ textAlign: "left", padding: 6 }}>Column</th>
                <th style={{ textAlign: "left", padding: 6 }}>Role</th>
                <th style={{ textAlign: "left", padding: 6 }}>Speckle property</th>
                <th style={{ textAlign: "left", padding: 6 }}>Notes</th>
              </tr>
            </thead>
            <tbody>
              {edited.mapping.map((m, i) => (
                <tr key={m.column} style={{ borderBottom: "1px solid #222" }}>
                  <td style={{ padding: 6, fontWeight: 600 }}>{m.column}</td>
                  <td style={{ padding: 6 }}>
                    <select
                      value={m.role}
                      onChange={(e) =>
                        updateMapping(i, { role: e.target.value as Role })
                      }
                      style={{
                        background: "#111",
                        color: "#eee",
                        border: "1px solid #333",
                        padding: "3px 6px",
                        borderRadius: 3,
                      }}
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td style={{ padding: 6 }}>
                    <input
                      value={m.speckle_property ?? ""}
                      onChange={(e) =>
                        updateMapping(i, { speckle_property: e.target.value || null })
                      }
                      placeholder="e.g. applicationId"
                      style={{
                        width: "100%",
                        background: "#111",
                        color: "#eee",
                        border: "1px solid #333",
                        padding: "3px 6px",
                        borderRadius: 3,
                      }}
                    />
                  </td>
                  <td style={{ padding: 6, color: "#888" }}>{m.notes ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {edited.unmapped_columns.length > 0 && (
            <div style={{ marginTop: 8, fontSize: 12, color: "#888" }}>
              Unmapped: {edited.unmapped_columns.join(", ")}
            </div>
          )}

          <div style={{ marginTop: 16, display: "flex", gap: 12, alignItems: "center" }}>
            <button
              onClick={onConfirm}
              disabled={confirming}
              style={{
                background: "#3a7",
                color: "#fff",
                border: "none",
                padding: "8px 14px",
                borderRadius: 4,
                cursor: confirming ? "wait" : "pointer",
              }}
            >
              {confirming ? "Saving…" : "Save mapping"}
            </button>
            {confirmedAt && (
              <span style={{ color: "#888", fontSize: 12 }}>
                Saved {new Date(confirmedAt).toLocaleString()}
              </span>
            )}
          </div>

          {resolveJob && resolveJob.state !== "ready" && (
            <div style={{ marginTop: 16, padding: 10, background: "#181d22", borderRadius: 4 }}>
              <div style={{ color: "#888", fontSize: 12 }}>
                Resolving rows · {resolveJob.state}
              </div>
              <div style={{ fontSize: 13 }}>{resolveJob.message}</div>
            </div>
          )}

          {resolution && (
            <div
              style={{
                marginTop: 16,
                padding: 12,
                background: "#15201a",
                border: "1px solid #1d6f3c",
                borderRadius: 4,
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: 6 }}>
                Matched {resolution.matched_tasks} task(s) to{" "}
                {resolution.total_links} Speckle element(s).
              </div>
              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <button
                  onClick={onGenerateAnimation}
                  disabled={generating || resolution.total_links === 0}
                  style={{
                    background: "#3a7",
                    color: "#fff",
                    border: "none",
                    padding: "8px 14px",
                    borderRadius: 4,
                    cursor: generating ? "wait" : "pointer",
                  }}
                >
                  {generating ? "Starting…" : "Generate animation →"}
                </button>
                {genJob && (
                  <span style={{ color: "#888", fontSize: 12 }}>
                    {genJob.state}: {genJob.message}
                  </span>
                )}
              </div>
            </div>
          )}

          {mapping.catalog_summary && (
            <details style={{ marginTop: 24 }}>
              <summary style={{ cursor: "pointer", color: "#888" }}>
                Speckle catalog summary used for this mapping
              </summary>
              <pre
                style={{
                  background: "#0d1014",
                  padding: 12,
                  fontSize: 12,
                  overflow: "auto",
                  maxHeight: 300,
                }}
              >
                {JSON.stringify(mapping.catalog_summary, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
