// "Privacy and audit" screen: data-subject requests, retention and audit tools.
//
// Each section appears only if the signed-in role holds the permission; the server
// enforces the same permissions regardless of what the UI shows.
//
//   [RULE: GDPR-ART15] Export everything that mentions a person.
//   [RULE: GDPR-ART20] JSON or CSV, machine-readable.
//   [RULE: GDPR-ART17] Erase one identifier across the organisation's documents.
//   [RULE: GDPR-ART5-1E] Run retention enforcement on demand.
//   [RULE: GDPR-ART30]  Record of processing activities.
//   [RULE: SEC-LOGGING] Verify the tamper-evident audit log.
//   [RULE: PII-LOG-SCRUB] The identifier typed here is never stored by the UI.

import { h, icon, clear } from "../dom.js";

export function renderPrivacy(root, ctx) {
  const view = h("section", { class: "view" },
    h("div", { class: "view-head" },
      h("h1", { text: "Privacy and audit" }),
      h("p", { class: "muted", text: "Handle data-subject requests, enforce retention and check the audit trail. Every action here is recorded." })));
  root.append(view);

  // ------------------------------------------------- data-subject requests
  if (ctx.has("export_subject") || ctx.has("erase_subject")) {
    const input = h("input", { id: "subject", type: "text", autocomplete: "off", spellcheck: "false",
      "aria-describedby": "subject-help subject-err", maxlength: 256 });
    const formatSel = h("select", { id: "fmt" }, h("option", { value: "json", text: "JSON" }), h("option", { value: "csv", text: "CSV" }));
    const err = h("p", { id: "subject-err", class: "error-text", role: "alert", hidden: true });
    const result = h("div", { class: "section", "aria-live": "polite" });

    const showError = (msg) => { clear(err); if (msg) err.append(icon("xcircle"), document.createTextNode(msg)); err.hidden = !msg;
      if (msg) input.setAttribute("aria-invalid", "true"); else input.removeAttribute("aria-invalid"); };
    const identifier = () => {
      const value = input.value.trim();
      if (value.length < 3) { showError("Enter at least 3 characters, exactly as they appear in the documents."); input.focus(); return null; }
      showError(""); return value;
    };

    const exportBtn = h("button", { type: "button", class: "btn btn-primary", on: { click: doExport } }, icon("download"), "Export data");
    const eraseBtn = h("button", { type: "button", class: "btn btn-danger", on: { click: doErase } }, icon("trash"), "Erase data");
    view.append(h("div", { class: "card section" },
      h("h2", { text: "Data-subject requests" }),
      h("div", { class: "field" },
        h("label", { for: "subject" }, "Identifier ", h("span", { class: "req", "aria-hidden": "true", text: "*" })),
        input,
        h("p", { id: "subject-help", class: "help", text: "An e-mail address, IBAN, phone number or name as written in the documents. It is not stored; the audit log keeps a redacted copy." }),
        err),
      ctx.has("export_subject") ? h("div", { class: "field" }, h("label", { for: "fmt", text: "Export format" }), formatSel) : null,
      h("div", { class: "actions" }, ctx.has("export_subject") ? exportBtn : null, ctx.has("erase_subject") ? eraseBtn : null),
      result));

    async function doExport() {
      const id = identifier(); if (!id) return;
      busy(exportBtn, true);
      try {
        const text = await ctx.api.exportSubject(id, formatSel.value);
        const empty = text.trim() === "[]" || text.trim() === "";
        clear(result).append(
          h("div", { class: `banner ${empty ? "info" : "success"}`, role: "note" }, icon(empty ? "info" : "check"),
            h("div", {}, h("strong", { text: empty ? "Nothing found" : "Export ready" }),
              empty ? "No stored excerpts mention this identifier." : "Excerpts show privacy placeholders where the original values were masked, restored for this export.")),
          empty ? null : h("pre", { class: "result", tabindex: "0", "aria-label": "Export result", text: text }),
          empty ? null : h("div", { class: "actions" }, h("button", { type: "button", class: "btn",
            on: { click: () => download(text, formatSel.value) } }, icon("download"), "Download file")));
        ctx.announce(empty ? "Nothing found." : "Export ready.");
      } catch (e) { ctx.toast(e.message, "error"); }
      busy(exportBtn, false, "download", "Export data");
    }

    async function doErase() {
      const id = identifier(); if (!id) return;
      const yes = await ctx.confirm({ title: "Erase this identifier?",
        body: "The stored mapping is destroyed and every occurrence in indexed documents is replaced with [ERASED]. This cannot be undone.",
        confirmText: "Erase data" });
      if (!yes) return;
      busy(eraseBtn, true);
      try {
        const r = await ctx.api.eraseSubject(id);
        clear(result).append(h("div", { class: "banner success", role: "note" }, icon("check"),
          h("div", {}, h("strong", { text: "Erasure complete" }),
            `${r.chunks_updated} section(s) updated · ${r.vault_entries_destroyed} stored mapping(s) destroyed.`)));
        ctx.announce("Erasure complete.");
        input.value = "";
      } catch (e) { ctx.toast(e.message, "error"); }
      busy(eraseBtn, false, "trash", "Erase data");
    }
  }

  // --------------------------------------------------------------- retention
  if (ctx.has("purge")) {
    const out = h("div", { "aria-live": "polite" });
    const btn = h("button", { type: "button", class: "btn", on: { click: run } }, icon("trash"), "Delete expired documents");
    view.append(h("div", { class: "card section" },
      h("h2", { text: "Retention" }),
      h("p", { class: "muted", text: "Every document has a deletion date. This removes all documents past theirs. Schedule it daily in production." }),
      h("div", { class: "actions" }, btn), out));
    async function run() {
      const yes = await ctx.confirm({ title: "Delete expired documents?",
        body: "All documents past their deletion date will be permanently removed.", confirmText: "Delete expired" });
      if (!yes) return;
      busy(btn, true);
      try {
        const { purged } = await ctx.api.purge();
        clear(out).append(h("div", { class: "banner success", role: "note" }, icon("check"),
          h("div", {}, h("strong", { text: purged.length ? `${purged.length} document(s) deleted` : "Nothing to delete" }),
            purged.length ? "They were past their retention date." : "No documents have passed their deletion date.")));
      } catch (e) { ctx.toast(e.message, "error"); }
      busy(btn, false, "trash", "Delete expired documents");
    }
  }

  // ------------------------------------------------------------------- audit
  if (ctx.has("view_audit")) {
    const out = h("div", { class: "section", "aria-live": "polite" });
    const verifyBtn = h("button", { type: "button", class: "btn", on: { click: verify } }, icon("shield"), "Verify audit log");
    const ropaBtn = h("button", { type: "button", class: "btn", on: { click: ropa } }, icon("file"), "Show processing record");
    view.append(h("div", { class: "card section" },
      h("h2", { text: "Audit and records" }),
      h("p", { class: "muted", text: "The audit log is chained so any edit or deletion is detectable. The processing record (GDPR Art. 30) describes what this system does with personal data." }),
      h("div", { class: "actions" }, verifyBtn, ropaBtn), out));

    async function verify() {
      busy(verifyBtn, true);
      try {
        const r = await ctx.api.auditVerify();
        clear(out).append(h("div", { class: `banner ${r.valid ? "success" : "danger"}`, role: r.valid ? "note" : "alert" },
          icon(r.valid ? "check" : "xcircle"),
          h("div", {}, h("strong", { text: r.valid ? "Audit log is intact" : "Audit log failed verification" }),
            r.valid ? `${r.events} event(s) checked.` : `${r.error || "The chain is broken."} Treat this as a possible security incident.`)));
        ctx.announce(r.valid ? "Audit log is intact." : "Audit log failed verification.");
      } catch (e) { ctx.toast(e.message, "error"); }
      busy(verifyBtn, false, "shield", "Verify audit log");
    }

    async function ropa() {
      busy(ropaBtn, true);
      try { clear(out).append(h("h3", { text: "Record of processing activities" }), keyValues(await ctx.api.ropa())); }
      catch (e) { ctx.toast(e.message, "error"); }
      busy(ropaBtn, false, "file", "Show processing record");
    }
  }
  return null;
}

// ----------------------------------------------------------------- helpers
function busy(btn, on, iconName, text) {
  btn.disabled = on;
  if (on) { btn.dataset.html = "1"; clear(btn).append(icon("loader", { spin: true }), document.createTextNode("Working…")); }
  else if (iconName) { clear(btn).append(icon(iconName), document.createTextNode(text)); }
}

function download(text, format) {
  const type = format === "csv" ? "text/csv" : "application/json";
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = h("a", { href: url, download: `data-subject-export.${format}` });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Render an object as a definition list (nested arrays and objects become lists). */
export function keyValues(obj) {
  const dl = h("dl", { class: "kv" });
  for (const [k, v] of Object.entries(obj)) {
    dl.append(h("dt", { text: k.replaceAll("_", " ") }), h("dd", {}, value(v)));
  }
  return dl;
}
function value(v) {
  if (Array.isArray(v)) return h("ul", {}, v.map((x) => h("li", {}, value(x))));
  if (v && typeof v === "object") return keyValues(v);
  return String(v);
}
