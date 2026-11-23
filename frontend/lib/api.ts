export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

export function getToken(): string | null {
  try { return localStorage.getItem("oneseller_token"); } catch { return null; }
}
export function setToken(token: string | null) {
  try { token ? localStorage.setItem("oneseller_token", token) : localStorage.removeItem("oneseller_token"); } catch {}
}

type Opts = Omit<RequestInit, "body"> & { body?: unknown; auth?: boolean; query?: Record<string, unknown> };

export async function api<T = unknown>(path: string, opts: Opts = {}): Promise<T> {
  const { body, auth = true, query, headers, ...rest } = opts;
  let url = API_URL + path;
  if (query) {
    const qs = new URLSearchParams();
    Object.entries(query).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "" && v !== false) qs.set(k, String(v));
    });
    const s = qs.toString();
    if (s) url += (url.includes("?") ? "&" : "?") + s;
  }
  const h: Record<string, string> = { ...(headers as Record<string, string>) };
  const token = auth ? getToken() : null;
  if (token) h.Authorization = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) { h["Content-Type"] = "application/json"; payload = JSON.stringify(body); }

  let res: Response;
  try {
    res = await fetch(url, { ...rest, headers: h, body: payload });
  } catch {
    throw new ApiError(0, "network_error", "Can't reach the server. Check your connection and try again.");
  }
  const text = await res.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const err = data?.error;
    if (res.status === 401 && token) setToken(null);
    throw new ApiError(res.status, err?.code || "error", err?.message || `Request failed (${res.status})`, err?.details);
  }
  return data as T;
}

export const imageSrc = (url?: string | null) => (url ? (url.startsWith("http") ? url : API_URL + url) : null);
