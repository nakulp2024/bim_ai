const KEY = "bim_ai_jwt";

export function getToken(): string | null {
  return localStorage.getItem(KEY);
}

export function setToken(t: string): void {
  localStorage.setItem(KEY, t);
}

export function clearToken(): void {
  localStorage.removeItem(KEY);
}
