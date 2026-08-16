/**
 * The HTTP client, ported unchanged in behaviour from the previous frontend.
 *
 * Auth token and active workspace live at module level rather than being
 * threaded through every call: pages call `api.get(...)` with no auth argument,
 * and the providers below push the current values in whenever they change, so
 * every subsequent request picks them up without touching a single call site.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let activeWorkspaceId: string | null = null;
let authToken: string | null = null;

export function setActiveWorkspaceId(id: string | null): void {
  activeWorkspaceId = id;
}

export function setAuthToken(token: string | null): void {
  authToken = token;
}

export function getAuthToken(): string | null {
  return authToken;
}

/** The base URL, exported because OAuth connect flows are full-page browser
 *  redirects rather than fetches - they cannot go through `request`. */
export const apiBaseUrl = BASE_URL;

async function request<T>(
  path: string,
  init?: RequestInit,
  workspaceIdOverride?: string,
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  // The override exists for pages that operate on one specific workspace
  // regardless of which is globally active (a Channel reached cross-workspace).
  // Switching the global active workspace instead was a real bug: it blanked
  // the user's Mail page, because their Gmail lives in the Personal workspace.
  const workspaceId = workspaceIdOverride ?? activeWorkspaceId;
  if (workspaceId) headers["X-Workspace-Id"] = workspaceId;
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

  const res = await fetch(`${BASE_URL}${path}`, { headers, ...init });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? `Request failed: ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

async function postStream(
  path: string,
  body: unknown,
  onEvent: (data: unknown) => void,
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (activeWorkspaceId) headers["X-Workspace-Id"] = activeWorkspaceId;
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    const errBody = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, errBody.detail ?? `Request failed: ${res.status}`);
  }

  // EventSource cannot carry the Authorization header this app's auth needs,
  // so this reads the same SSE framing (`data: {...}\n\n`) by hand off a plain
  // fetch() stream instead.
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith("data:")) continue;
      try {
        onEvent(JSON.parse(line.slice(5).trim()));
      } catch {
        // malformed chunk - skip rather than crash the stream
      }
    }
  }
}

export const api = {
  get: <T,>(path: string, opts?: { workspaceId?: string }) =>
    request<T>(path, undefined, opts?.workspaceId),
  post: <T,>(path: string, body?: unknown, opts?: { workspaceId?: string }) =>
    request<T>(
      path,
      { method: "POST", body: body ? JSON.stringify(body) : undefined },
      opts?.workspaceId,
    ),
  patch: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  put: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  postStream,
  delete: <T = void,>(path: string) => request<T>(path, { method: "DELETE" }),
};
