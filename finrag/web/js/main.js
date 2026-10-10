// App shell: sign-in, navigation, theme, toasts and confirmation dialog.
//
// Navigation uses URL hashes (#/ask, #/documents, ...) so every screen is
// deep-linkable and the browser Back button behaves predictably. The server
// enforces every permission; the UI only hides actions a role cannot use.
//   [RULE: SEC-AUTHZ] Navigation shows only what the signed-in role may do.
//   [RULE: EUAIA-ART50] AI disclosure on the sign-in screen and on every answer.

import { api, setKey, hasKey, setUnauthorisedHandler } from "./api.js";
import { h, icon, clear, setButton } from "./dom.js";
import { renderAsk, resetConversation } from "./views/ask.js";
import { renderDocuments } from "./views/documents.js";
import { renderPrivacy } from "./views/privacy.js";
import { renderAbout } from "./views/about.js";

const $ = (id) => document.getElementById(id);
const state = { me: null, cleanup: null, loggingIn: false };

// --------------------------------------------------------------- utilities
export function announce(message) {
  const live = $("live");
  live.textContent = "";
  // Re-set on the next frame so screen readers announce repeated messages.
  requestAnimationFrame(() => { live.textContent = message; });
}

function toast(message, kind = "info") {
  const box = h("div", { class: "toast", role: kind === "error" ? "alert" : "status" },
    icon(kind === "error" ? "xcircle" : kind === "success" ? "check" : "info"),
    h("span", { text: message }),
    h("button", { type: "button", "aria-label": "Dismiss message",
      on: { click: () => box.remove() } }, icon("x")));
  $("toasts").append(box);
  setTimeout(() => box.remove(), 5000);
}

/** Confirm a (usually destructive) action. Resolves to true or false. */
function confirmDialog({ title, body, confirmText = "Confirm", danger = true }) {
  const dialog = $("confirm");
  $("confirm-title").textContent = title;
  $("confirm-body").textContent = body;
  const ok = $("confirm-ok");
  ok.textContent = confirmText;
  ok.className = danger ? "btn btn-danger" : "btn btn-primary";
  return new Promise((resolve) => {
    const finish = (value) => {
      dialog.removeEventListener("close", onClose);
      ok.removeEventListener("click", onOk);
      $("confirm-cancel").removeEventListener("click", onCancel);
      if (dialog.open) dialog.close();
      resolve(value);
    };
    const onOk = () => finish(true);
    const onCancel = () => finish(false);
    const onClose = () => finish(false); // Esc key
    ok.addEventListener("click", onOk);
    $("confirm-cancel").addEventListener("click", onCancel);
    dialog.addEventListener("close", onClose);
    dialog.showModal();
    $("confirm-cancel").focus(); // safest default for destructive actions
  });
}

// ------------------------------------------------------------------- theme
function applyTheme(theme) {
  if (theme) document.documentElement.setAttribute("data-theme", theme);
  else document.documentElement.removeAttribute("data-theme");
}
function currentTheme() {
  return document.documentElement.getAttribute("data-theme")
    || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
}
function refreshThemeButton() {
  const dark = currentTheme() === "dark";
  const btn = $("theme-toggle");
  setButton(btn, dark ? "sun" : "moon");
  btn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  btn.title = btn.getAttribute("aria-label");
}
function initTheme() {
  try { applyTheme(localStorage.getItem("finrag.theme")); } catch { /* ignore */ }
  refreshThemeButton();
  $("theme-toggle").addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    applyTheme(next);
    try { localStorage.setItem("finrag.theme", next); } catch { /* ignore */ }
    refreshThemeButton();
  });
}

// ------------------------------------------------------------------ routes
const ROUTES = [
  { id: "ask", label: "Ask", icon: "message", title: "Ask", render: renderAsk,
    allowed: (has) => has("query") },
  { id: "documents", label: "Documents", icon: "file", title: "Documents", render: renderDocuments,
    allowed: (has) => has("ingest") || has("list_documents") },
  { id: "privacy", label: "Privacy", icon: "shield", title: "Privacy and audit", render: renderPrivacy,
    allowed: (has) => ["export_subject", "erase_subject", "purge", "view_audit"].some(has) },
  { id: "about", label: "About", icon: "info", title: "About this AI system", render: renderAbout,
    allowed: () => true },
];

function ctx() {
  const permissions = new Set(state.me.permissions);
  return {
    me: state.me, api, toast, announce, confirm: confirmDialog,
    has: (perm) => permissions.has(perm),
    navigate: (id) => { location.hash = `#/${id}`; },
  };
}

function allowedRoutes() {
  const permissions = new Set(state.me.permissions);
  return ROUTES.filter((r) => r.allowed((p) => permissions.has(p)));
}

function buildNav() {
  const nav = clear($("nav"));
  for (const route of allowedRoutes()) {
    nav.append(h("a", { href: `#/${route.id}`, dataset: { route: route.id } },
      icon(route.icon), h("span", { text: route.label })));
  }
}

function route() {
  if (!state.me) return;
  const routes = allowedRoutes();
  const wanted = location.hash.replace(/^#\/?/, "").split("?")[0];
  const found = routes.find((r) => r.id === wanted);
  if (!found) { location.replace(`#/${routes[0].id}`); return; }

  for (const a of $("nav").querySelectorAll("a")) {
    if (a.dataset.route === found.id) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  if (state.cleanup) { try { state.cleanup(); } catch { /* ignore */ } state.cleanup = null; }
  const main = clear($("main"));
  state.cleanup = found.render(main, ctx()) || null;
  document.title = `${found.title} · FinRAG`;
  // Move focus to the page heading so keyboard and screen-reader users land in the new view.
  const heading = main.querySelector("h1");
  if (heading) { heading.setAttribute("tabindex", "-1"); heading.focus({ preventScroll: true }); }
  window.scrollTo(0, 0);
}

// ----------------------------------------------------------------- session
function showShell(me) {
  state.me = me;
  $("login-view").hidden = true;
  $("shell").hidden = false;
  const badge = $("mode-badge");
  clear(badge);
  const offline = me.provider === "offline";
  badge.className = "badge" + (offline ? "" : " primary");
  badge.append(icon(offline ? "lock" : "info"),
    offline ? "Offline mode" : `AI: ${me.model}`);
  badge.title = offline
    ? "Answers are extracted from your documents on this server. Nothing is sent to an AI provider."
    : "Excerpts with personal data masked are sent to the AI provider to write answers.";
  const who = clear($("who"));
  who.append(h("div", { text: me.principal }),
    h("div", { class: "muted", text: `${me.tenant} · ${me.roles.join(", ") || "no role"}` }));
  setButton($("signout"), "logout");
  buildNav();
  route();
}

function signOut(message) {
  setKey(null);
  resetConversation(); // never leak one user's questions and answers to the next
  state.me = null;
  if (state.cleanup) { try { state.cleanup(); } catch { /* ignore */ } state.cleanup = null; }
  clear($("main"));
  $("shell").hidden = true;
  $("login-view").hidden = false;
  $("api-key").value = "";
  document.title = "Sign in · FinRAG";
  if (message) showLoginError(message);
  $("login-title").focus();
}

function showLoginError(message) {
  const el = $("api-key-error");
  clear(el);
  el.append(icon("xcircle"), document.createTextNode(message));
  el.hidden = false;
  $("api-key").setAttribute("aria-invalid", "true");
}

function initLogin() {
  const input = $("api-key");
  const toggle = $("toggle-key");
  setButton(toggle, "eye");
  toggle.addEventListener("click", () => {
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    toggle.setAttribute("aria-pressed", String(show));
    toggle.setAttribute("aria-label", show ? "Hide API key" : "Show API key");
    setButton(toggle, show ? "eyeOff" : "eye");
  });

  $("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = $("login-submit");
    const key = input.value.trim();
    $("api-key-error").hidden = true;
    input.removeAttribute("aria-invalid");
    if (!key) { showLoginError("Enter your API key."); input.focus(); return; }

    submit.disabled = true;
    setButton(submit, null, "");
    submit.append(icon("loader", { spin: true }), document.createTextNode("Signing in…"));
    setKey(key);
    state.loggingIn = true; // a wrong key here is reported inline, keeping what was typed
    try {
      showShell(await api.me());
    } catch (err) {
      setKey(null);
      showLoginError(err.message);
      input.focus();
    } finally {
      state.loggingIn = false;
      submit.disabled = false;
      submit.textContent = "Sign in";
    }
  });
}

// -------------------------------------------------------------------- boot
async function boot() {
  initTheme();
  initLogin();
  $("signout").addEventListener("click", () => signOut());
  setUnauthorisedHandler(() => {
    if (!state.loggingIn) signOut("Your key was not accepted or has expired. Sign in again.");
  });
  addEventListener("hashchange", route);

  if (hasKey()) {
    try { showShell(await api.me()); return; } catch { /* fall through to sign-in */ }
  }
  signOut();
}

boot();
