import type {
  Baseline,
  FilterReport,
  GeometryManifest,
  Job,
  LevelPrediction,
  ModelProfile,
  ParseReport,
  ProgressEntryInput,
  ProgressView,
  Project,
  RatesResponse,
  Schedule,
  ScheduleRequest,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
      ...init,
    });
  } catch (cause) {
    throw new ApiError(
      "Could not reach the API. Is the backend running on port 8000?",
      0,
    );
  }

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail)) {
        detail = body.detail.map((d: { msg?: string }) => d.msg ?? "invalid input").join("; ");
      }
    } catch {
      /* keep the status line */
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ status: string; llm_enabled: boolean }>("/api/health"),

  listProjects: () => request<{ projects: Project[] }>("/api/projects"),

  createProject: (name: string) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name }) }),

  getProject: (id: number) => request<Project>(`/api/projects/${id}`),

  deleteProject: (id: number) =>
    request<{ deleted: number }>(`/api/projects/${id}`, { method: "DELETE" }),

  upload: (id: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ job_id: string; bytes: number }>(`/api/projects/${id}/upload`, {
      method: "POST",
      body: form,
    });
  },

  getJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}`),

  getProfile: (id: number) =>
    request<{ project: Project; profile: ModelProfile; parse_report: ParseReport }>(
      `/api/projects/${id}/profile`,
    ),

  lodPreview: (id: number, zoneSplit: string | null) =>
    request<{ levels: LevelPrediction[]; filter: FilterReport }>(
      `/api/projects/${id}/lod-preview`,
      { method: "POST", body: JSON.stringify({ zone_split: zoneSplit }) },
    ),

  generate: (id: number, payload: ScheduleRequest) =>
    request<{ job_id: string }>(`/api/projects/${id}/schedule`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getSchedule: (id: number) => request<Schedule>(`/api/projects/${id}/schedule`),

  updateTask: (
    id: number,
    taskId: string,
    payload: Partial<{
      label: string;
      duration_days: number;
      crew: number;
      work_package: string;
      predecessors: { id: string; type: string; lag: number }[];
    }>,
  ) =>
    request<Schedule>(`/api/projects/${id}/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  deleteTask: (id: number, taskId: string) =>
    request<Schedule>(`/api/projects/${id}/tasks/${taskId}`, { method: "DELETE" }),

  createLink: (
    id: number,
    payload: { predecessor_id: string; successor_id: string; type: string; lag: number },
  ) =>
    request<Schedule>(`/api/projects/${id}/links`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  deleteLink: (id: number, predecessorId: string, successorId: string) =>
    request<Schedule>(
      `/api/projects/${id}/links?predecessor_id=${encodeURIComponent(
        predecessorId,
      )}&successor_id=${encodeURIComponent(successorId)}`,
      { method: "DELETE" },
    ),

  updateCalendar: (
    id: number,
    payload: { start_date?: string; work_days?: number[]; holidays?: string[] },
  ) =>
    request<Schedule>(`/api/projects/${id}/calendar`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  getRates: (id: number) => request<RatesResponse>(`/api/projects/${id}/rates`),

  updateRates: (
    id: number,
    rules: { id: string; output_per_crew_day?: number; default_crew?: number }[],
  ) =>
    request<{ overrides: Record<string, unknown>; repriced_tasks: number }>(
      `/api/projects/${id}/rates`,
      { method: "PUT", body: JSON.stringify({ rules, recalculate: true }) },
    ),

  exportUrl: (id: number, fmt: string) => `${BASE}/api/projects/${id}/export/${fmt}`,

  // --- progress --------------------------------------------------------------

  getProgress: (id: number) => request<ProgressView>(`/api/projects/${id}/progress`),

  reportProgress: (id: number, entries: ProgressEntryInput[], reportedOn?: string) =>
    request<ProgressView>(`/api/projects/${id}/progress`, {
      method: "POST",
      body: JSON.stringify({ entries, reported_on: reportedOn ?? null }),
    }),

  clearProgress: (id: number, taskId: string) =>
    request<ProgressView>(`/api/projects/${id}/progress/${encodeURIComponent(taskId)}`, {
      method: "DELETE",
    }),

  setDataDate: (id: number, dataDate: string) =>
    request<{ data_date: string }>(`/api/projects/${id}/data-date`, {
      method: "PUT",
      body: JSON.stringify({ data_date: dataDate }),
    }),

  listBaselines: (id: number) =>
    request<{ baselines: Baseline[] }>(`/api/projects/${id}/baselines`),

  createBaseline: (id: number, name?: string) =>
    request<Baseline>(`/api/projects/${id}/baselines`, {
      method: "POST",
      body: JSON.stringify({ name: name ?? null }),
    }),

  activateBaseline: (id: number, baselineId: number) =>
    request<Baseline>(`/api/projects/${id}/baselines/${baselineId}/activate`, {
      method: "POST",
    }),

  // --- geometry --------------------------------------------------------------

  buildGeometry: (id: number, force = false) =>
    request<{ job_id: string | null; status: string }>(
      `/api/projects/${id}/geometry${force ? "?force=true" : ""}`,
      { method: "POST" },
    ),

  getGeometryManifest: (id: number) =>
    request<GeometryManifest>(`/api/projects/${id}/geometry`),

  /** Versioned by build id, so a rebuild never meets a stale cached buffer. */
  getGeometryBuffer: async (id: number, buildId: string): Promise<ArrayBuffer> => {
    const response = await fetch(
      `${BASE}/api/projects/${id}/geometry/buffer?v=${encodeURIComponent(buildId)}`,
    );
    if (!response.ok) {
      throw new ApiError(`Could not load model geometry (${response.status})`, response.status);
    }
    return response.arrayBuffer();
  },
};

/** Poll a background job until it finishes, reporting progress as it goes. */
export async function pollJob(
  jobId: string,
  onProgress: (job: Job) => void,
  intervalMs = 400,
): Promise<Job> {
  for (;;) {
    const job = await api.getJob(jobId);
    onProgress(job);
    if (job.status === "done" || job.status === "failed") return job;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}
