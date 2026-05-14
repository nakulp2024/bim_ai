import { getToken, clearToken } from "./auth";

const BASE = "/api";

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const tok = getToken();
  const headers = new Headers(init.headers);
  if (tok) headers.set("authorization", `Bearer ${tok}`);
  const res = await fetch(BASE + path, { ...init, headers });
  if (res.status === 401) {
    clearToken();
    throw new Error("unauthorized");
  }
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export interface Me {
  id: string;
  speckle_user_id: string;
  name: string | null;
  email: string | null;
  avatar: string | null;
  speckle_token: string;
  speckle_public_url: string;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  updatedAt: string;
  role: string | null;
}

export interface Model {
  id: string;
  name: string;
  updatedAt: string;
}

export interface Version {
  id: string;
  referencedObject: string;
  message: string | null;
  sourceApplication: string | null;
  createdAt: string;
}

export type Role =
  | "task_id"
  | "name"
  | "start"
  | "end"
  | "wbs"
  | "phase"
  | "join_key"
  | "activity"
  | "ignored";

export type JoinStrategy =
  | "application_id"
  | "category_and_level"
  | "type_and_level"
  | "name_fuzzy"
  | "wbs_pattern";

export interface ColumnMapping {
  column: string;
  role: Role;
  speckle_property?: string | null;
  notes?: string | null;
}

export interface MappingProposalBody {
  mapping: ColumnMapping[];
  join_strategy: JoinStrategy;
  confidence: number;
  rationale: string;
  unmapped_columns: string[];
}

export interface JobStatus {
  id: string;
  kind: string;
  state: "queued" | "running" | "ready" | "failed";
  progress: number | null;
  message: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface UploadResult {
  schedule_id: string;
  job_id: string;
  row_count: number;
  headers: string[];
}

export interface MappingView {
  schedule_id: string;
  proposal_id?: string;
  proposed: MappingProposalBody | null;
  join_strategy?: JoinStrategy;
  confidence?: number;
  rationale?: string;
  confirmed?: MappingProposalBody | null;
  confirmed_at?: string | null;
  headers?: string[];
  sample_rows?: Record<string, string | null>[];
  catalog_summary?: {
    total_elements?: number;
    by_category?: Record<string, number>;
    by_level?: Record<string, number>;
  };
}

export const api = {
  me: () => call<Me>("/me"),
  projects: () => call<Project[]>("/speckle/projects"),
  models: (projectId: string) =>
    call<Model[]>(`/speckle/projects/${projectId}/models`),
  versions: (projectId: string, modelId: string) =>
    call<Version[]>(`/speckle/projects/${projectId}/models/${modelId}/versions`),

  uploadSchedule: async (params: {
    file: File;
    speckle_project_id: string;
    speckle_model_id: string;
    speckle_version_id: string;
  }): Promise<UploadResult> => {
    const fd = new FormData();
    fd.append("file", params.file);
    fd.append("speckle_project_id", params.speckle_project_id);
    fd.append("speckle_model_id", params.speckle_model_id);
    fd.append("speckle_version_id", params.speckle_version_id);
    const tok = getToken();
    const headers: Record<string, string> = {};
    if (tok) headers["authorization"] = `Bearer ${tok}`;
    const res = await fetch(`${BASE}/schedules`, {
      method: "POST",
      headers,
      body: fd,
    });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.json();
  },

  job: (jobId: string) => call<JobStatus>(`/jobs/${jobId}`),
  mapping: (scheduleId: string) =>
    call<MappingView>(`/schedules/${scheduleId}/mapping`),
  confirmMapping: (scheduleId: string, payload: MappingProposalBody) =>
    call<{ ok: boolean; proposal_id: string }>(
      `/schedules/${scheduleId}/mapping/confirm`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
};

export function loginUrl(): string {
  return `${BASE}/auth/speckle/start`;
}
