export interface IfcElement {
  ifc_guid: string;
  express_id: number;
  ifc_type: string;
  name: string | null;
  storey: string | null;
  psets: Record<string, Record<string, unknown>>;
}

export interface UploadResult {
  project_id: string;
  element_count: number;
  glb_url: string;
  elements_url: string;
}

const BASE = "/api";

export async function createProject(): Promise<string> {
  const res = await fetch(`${BASE}/projects`, { method: "POST" });
  if (!res.ok) throw new Error(`createProject failed: ${res.status}`);
  const data = await res.json();
  return data.project_id;
}

export async function uploadIfc(projectId: string, file: File): Promise<UploadResult> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${BASE}/projects/${projectId}/ifc`, {
    method: "POST",
    body: fd,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`upload failed: ${res.status} ${text}`);
  }
  return res.json();
}

export async function fetchElements(projectId: string): Promise<IfcElement[]> {
  const res = await fetch(`${BASE}/projects/${projectId}/elements`);
  if (!res.ok) throw new Error(`fetchElements failed: ${res.status}`);
  return res.json();
}

export function glbUrl(projectId: string): string {
  return `${BASE}/projects/${projectId}/model.glb`;
}
