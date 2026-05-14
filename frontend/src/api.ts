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

export const api = {
  me: () => call<Me>("/me"),
  projects: () => call<Project[]>("/speckle/projects"),
  models: (projectId: string) =>
    call<Model[]>(`/speckle/projects/${projectId}/models`),
  versions: (projectId: string, modelId: string) =>
    call<Version[]>(`/speckle/projects/${projectId}/models/${modelId}/versions`),
};

export function loginUrl(): string {
  return `${BASE}/auth/speckle/start`;
}
