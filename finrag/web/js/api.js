// API client.
//
// The API key lives in sessionStorage: it is cleared when the tab closes and is
// never written to localStorage, cookies or URLs. The page's Content-Security-Policy
// (same-origin scripts only, no inline code) limits what could read it.
//   [RULE: SEC-AUTHN] Key sent in the X-API-Key header on every request.
//   [RULE: SEC-SECRETS] Key never logged, never put in a URL, cleared on sign-out.
//   [RULE: OWASP-LLM10] Client-side timeout so a stuck request cannot hang the UI.

const KEY_NAME = "finrag.apiKey";
let apiKey = null;
try { apiKey = sessionStorage.getItem(KEY_NAME); } catch { /* storage may be blocked */ }

let onUnauthorised = () => {};

export function setUnauthorisedHandler(fn) { onUnauthorised = fn; }
export function hasKey() { return Boolean(apiKey); }
export function setKey(key) {
  apiKey = key || null;
  try {
    if (apiKey) sessionStorage.setItem(KEY_NAME, apiKey);
    else sessionStorage.removeItem(KEY_NAME);
  } catch { /* the in-memory key still works for this page view */ }
}

export class ApiError extends Error {
  constructor(status, message, extra = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    Object.assign(this, extra);
  }
}

const STATUS_MESSAGES = {
  401: "Your key was not accepted. Check it and try again.",
  403: "Your role does not allow this action.",
  413: "That file is too large.",
  429: "Too many requests. Wait a minute and try again.",
  503: "The answer service is temporarily unavailable. Try again shortly.",
};

async function request(path, { method = "GET", json, form, timeoutMs = 130000, text = false, auth = true } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const headers = {};
  if (auth && apiKey) headers["X-API-Key"] = apiKey;
  let body;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  else if (form) body = form;

  let response;
  try {
    response = await fetch(path, { method, headers, body, signal: controller.signal,
      credentials: "omit", cache: "no-store" });
  } catch (err) {
    const timeout = err && err.name === "AbortError";
    throw new ApiError(0, timeout ? "The request took too long." : "Could not reach the server.",
      { kind: timeout ? "timeout" : "network" });
  } finally {
    clearTimeout(timer);
  }

  if (!response.ok) {
    let detail = "";
    try { const data = await response.json(); detail = typeof data.detail === "string" ? data.detail : ""; }
    catch { /* non-JSON error body */ }
    if (response.status === 401 && auth) onUnauthorised();
    // 422 detail strings are written by the server and never echo user data.
    const message = response.status === 422 && detail ? detail
      : STATUS_MESSAGES[response.status] || detail || "Something went wrong. Try again.";
    throw new ApiError(response.status, message, { detail });
  }
  return text ? response.text() : response.json();
}

export const api = {
  me: () => request("/v1/me"),
  transparency: () => request("/v1/transparency", { auth: false }),
  query: (question, reidentify) => request("/v1/query", { method: "POST", json: { question, reidentify } }),
  listDocuments: () => request("/v1/documents"),
  deleteDocument: (id) => request(`/v1/documents/${encodeURIComponent(id)}`, { method: "DELETE" }),
  upload: (file, fields) => {
    const form = new FormData();
    form.append("file", file, file.name);
    for (const [k, v] of Object.entries(fields)) if (v !== undefined && v !== "") form.append(k, v);
    return request("/v1/documents", { method: "POST", form });
  },
  exportSubject: (identifier, format) =>
    request("/v1/gdpr/export", { method: "POST", json: { identifier, format }, text: true }),
  eraseSubject: (identifier) =>
    request("/v1/gdpr/erasure", { method: "POST", json: { identifier, format: "json" } }),
  purge: () => request("/v1/admin/purge", { method: "POST" }),
  auditVerify: () => request("/v1/audit/verify"),
  ropa: () => request("/v1/gdpr/ropa"),
};
