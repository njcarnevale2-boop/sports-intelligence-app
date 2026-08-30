const DEFAULT_API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "";

const MAX_PUBLIC_ERROR_LENGTH = 240;

export function buildApiUrl(path: string) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const base = DEFAULT_API_BASE_URL.replace(/\/$/, "");

  return `${base}${normalizedPath}`;
}

function sanitizePublicErrorDetail(detail: unknown): string | null {
  if (typeof detail !== "string") return null;
  const text = detail.trim();
  if (!text || text.length > MAX_PUBLIC_ERROR_LENGTH) return null;
  if (/\r|\n|\t/.test(text)) return null;

  const lower = text.toLowerCase();
  const blockedFragments = [
    "traceback",
    "stack trace",
    "file \"",
    "line ",
    "/users/",
    "\\users\\",
    "token",
    "password",
    "secret",
    "api_key",
    "apikey",
  ];

  if (blockedFragments.some((fragment) => lower.includes(fragment))) {
    return null;
  }

  return text;
}

function extractErrorDetail(payload: unknown): string | null {
  const direct = sanitizePublicErrorDetail(payload);
  if (direct) return direct;

  if (!payload || typeof payload !== "object") return null;

  const obj = payload as Record<string, unknown>;
  const candidates: unknown[] = [
    obj.detail,
    obj.message,
    obj.error,
    obj.reason,
  ];

  for (const candidate of candidates) {
    const safe = sanitizePublicErrorDetail(candidate);
    if (safe) return safe;

    if (candidate && typeof candidate === "object") {
      const nested = candidate as Record<string, unknown>;
      const nestedSafe = sanitizePublicErrorDetail(nested.message);
      if (nestedSafe) return nestedSafe;
    }

    if (Array.isArray(candidate)) {
      for (const item of candidate) {
        if (item && typeof item === "object") {
          const safeMsg = sanitizePublicErrorDetail((item as Record<string, unknown>).msg);
          if (safeMsg) return safeMsg;
        }
      }
    }
  }

  return null;
}

function handleExpiredSession(currentPath?: string) {
  if (typeof window === "undefined") return;
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  // Preserve return destination to restore after login
  const returnTo = currentPath ?? window.location.pathname;
  const loginPath = returnTo && returnTo !== "/login" ? `/login?returnTo=${encodeURIComponent(returnTo)}` : "/login";
  // Only redirect if not already on login to avoid loops
  if (!window.location.pathname.startsWith("/login")) {
    window.location.href = loginPath;
  }
}

export async function fetchJson<T>(path: string, init?: RequestInit, timeoutMs = 10000): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(buildApiUrl(path), {
      ...init,
      signal: controller.signal,
    });

    if (response.status === 401) {
      handleExpiredSession();
      throw new Error("Session expired. Please sign in again.");
    }

    if (!response.ok) {
      let errorPayload: unknown = null;
      const contentType = response.headers.get("content-type") || "";

      try {
        if (contentType.includes("application/json")) {
          errorPayload = await response.json();
        } else {
          const body = await response.text();
          errorPayload = body || null;
        }
      } catch {
        errorPayload = null;
      }

      const detail = extractErrorDetail(errorPayload);
      throw new Error(detail || `Request failed (${response.status})`);
    }

    const contentType = response.headers.get("content-type") || "";

    if (contentType.includes("application/json")) {
      return (await response.json()) as T;
    }

    const text = await response.text();
    return (text ? JSON.parse(text) : undefined) as T;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("Request timed out");
    }

    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}
