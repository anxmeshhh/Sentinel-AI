const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Module-level rather than passed per-call: every existing page already
// calls `api.get(...)`/`api.post(...)` without a workspace/auth argument,
// and making the switcher (or login) work shouldn't mean touching every
// call site. Providers call these setters whenever the value changes, and
// every subsequent request picks it up automatically.
let activeWorkspaceId: string | null = null;
let authToken: string | null = null;

export function setActiveWorkspaceId(id: string | null): void {
  activeWorkspaceId = id;
}

export function setAuthToken(token: string | null): void {
  authToken = token;
}

async function request<T>(path: string, init?: RequestInit, workspaceIdOverride?: string): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  // The override exists for pages that operate on a specific workspace
  // regardless of which one is globally active (e.g. a Channel page reached
  // cross-workspace from "My Channels") - silently *switching* the global
  // active workspace instead was a real bug: it made the user's Mail page
  // go blank because their Gmail lives in the Personal workspace.
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

async function postStream(path: string, body: unknown, onEvent: (data: unknown) => void): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (activeWorkspaceId) headers["X-Workspace-Id"] = activeWorkspaceId;
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

  const res = await fetch(`${BASE_URL}${path}`, { method: "POST", headers, body: JSON.stringify(body) });
  if (!res.ok || !res.body) {
    const errBody = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, errBody.detail ?? `Request failed: ${res.status}`);
  }

  // EventSource can't carry the Authorization header this app's auth needs,
  // so this reads the same SSE framing (`data: {...}\n\n`) by hand off a
  // plain fetch() stream instead - see connections_ai.py's stream endpoint.
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
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
  get: <T>(path: string, opts?: { workspaceId?: string }) => request<T>(path, undefined, opts?.workspaceId),
  post: <T>(path: string, body?: unknown, opts?: { workspaceId?: string }) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }, opts?.workspaceId),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  // PUT for idempotent replace-in-place, which is what setting a policy is:
  // "this action is enabled here" has one correct final state regardless of
  // how many times it is sent.
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  postStream,
  // Generic with a `void` default: most DELETEs return 204, but some return
  // the updated resource (unlinking a commitment returns the recomputed
  // goal), and callers of those need the body rather than a second fetch.
  delete: <T = void>(path: string) => request<T>(path, { method: "DELETE" }),
};
