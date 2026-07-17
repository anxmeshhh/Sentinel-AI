const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Module-level rather than passed per-call: every existing page already
// calls `api.get(...)`/`api.post(...)` without a workspace argument, and
// making the workspace switcher work shouldn't mean touching every call
// site. WorkspaceProvider calls setActiveWorkspaceId() whenever the user
// switches, and every subsequent request picks it up automatically.
let activeWorkspaceId: string | null = null;

export function setActiveWorkspaceId(id: string | null): void {
  activeWorkspaceId = id;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (activeWorkspaceId) headers["X-Workspace-Id"] = activeWorkspaceId;

  const res = await fetch(`${BASE_URL}${path}`, { headers, ...init });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? `Request failed: ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  delete: (path: string) => request<void>(path, { method: "DELETE" }),
};
