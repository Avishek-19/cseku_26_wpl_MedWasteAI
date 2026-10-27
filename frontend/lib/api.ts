// In deployed environments API calls default to the same-origin /api/v1 proxy.
// Set NEXT_PUBLIC_API_URL explicitly for a separate API host. Never silently
// direct production visitors to their own localhost:8000.
const API_URL = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "";

export const ACTIVE_ORG_STORAGE_KEY = 'medwaste:active-organization';
export const ACTIVE_ORG_CHANGE_EVENT = 'medwaste:organization-changed';

export function activeOrganizationId(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(ACTIVE_ORG_STORAGE_KEY);
}

export function setActiveOrganizationId(id: string | null): void {
  if (typeof window === 'undefined') return;
  if (id) window.localStorage.setItem(ACTIVE_ORG_STORAGE_KEY, id);
  else window.localStorage.removeItem(ACTIVE_ORG_STORAGE_KEY);
  window.dispatchEvent(new Event(ACTIVE_ORG_CHANGE_EVENT));
}

function detailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) =>
    typeof item === "object" && item !== null && "msg" in item
      ? String(item.msg)
      : String(item)
  ).join("; ") || fallback;
  if (detail && typeof detail === "object" && "message" in detail)
    return String(detail.message);
  return fallback || "Request failed";
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(activeOrganizationId() ? { "X-Organization-ID": activeOrganizationId()! } : {}),
      ...options.headers,
    },
  });

  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = detailMessage(body.detail, message);
    } catch {
      // response had no JSON body — fall back to statusText
    }
    throw new ApiError(res.status, message);
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

async function requestRaw(path: string, options: RequestInit = {}): Promise<Response> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options, credentials: "include",
    headers: { ...(activeOrganizationId() ? { 'X-Organization-ID': activeOrganizationId()! } : {}), ...options.headers },
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = detailMessage(body.detail, message);
    } catch {
      // response had no JSON body — fall back to statusText
    }
    throw new ApiError(res.status, message);
  }
  return res;
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  upload: async <T>(path: string, file: File): Promise<T> => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await requestRaw(path, { method: "POST", body: formData });
    return res.json() as Promise<T>;
  },
};

export function apiFileUrl(path: string): string {
  return `${API_URL}${path}`;
}
