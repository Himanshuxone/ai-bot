// "Documents" screen: upload financial documents and manage the library.
//
// Uploading follows the privacy workflow of the API: every document needs a
// lawful basis and an approved purpose, has an expiry, and may require an Art. 9(2)
// condition. The form asks for these up front (no silent legal defaults) and the
// server remains the authority: client checks only save a round trip.
//
//   [RULE: GDPR-ART6]     Lawful basis is a required field with no default.
//   [RULE: GDPR-ART5-1B]  Purpose is a required field from the approved list.
//   [RULE: GDPR-ART7]     Consent reference collected when consent is chosen.
//   [RULE: GDPR-ART9]     Special-category condition offered when needed.
//   [RULE: GDPR-ART5-1E]  Retention period is shown and editable per upload.
//   [RULE: SEC-FILE-UPLOAD] Type and size are checked before sending.
//   [RULE: GDPR-ART17]    Deleting a document is explicit and confirmed.

import { h, icon, clear, setButton } from "../dom.js";
import { LAWFUL_BASIS, PURPOSE, ART9, label, formatBytes, formatDate, formatDateTime,
  piiSummary, fileExtension } from "../format.js";

export function renderDocuments(root, ctx) {
  const opts = ctx.me.options;
  const canUpload = ctx.has("ingest");
  const canList = ctx.has("list_documents");
  /** @type {{id:number,file:File,status:string,message?:string,report?:object}[]} */
  let queue = [];
  let seq = 1;
  let uploading = false;

  const view = h("section", { class: "view wide" },
    h("div", { class: "view-head" },
      h("h1", { text: "Documents" }),
      h("p", { class: "muted", text: "Upload financial documents, then ask questions about them. Personal data is masked before anything is stored." })));
  root.append(view);

  // ------------------------------------------------------------------ upload
  if (canUpload) {
    const fileInput = h("input", { type: "file", id: "files", multiple: true,
      accept: opts.extensions.join(","), "aria-describedby": "file-help file-error" });
    const dropzone = h("label", { class: "dropzone", for: "files" },
      icon("upload"),
      h("strong", { text: "Drop files here or choose files" }),
      h("span", { id: "file-help", class: "small muted",
        text: `PDF, Excel (.xlsx), CSV, text or Markdown · up to ${formatBytes(opts.max_upload_bytes)} each` }),
      fileInput);
    const fileError = h("p", { id: "file-error", class: "error-text", role: "alert", hidden: true });
    const queueEl = h("ul", { class: "queue", "aria-label": "Files to upload" });

    const lawful = select("lawful_basis", "Lawful basis", opts.lawful_bases, LAWFUL_BASIS, true,
      "The GDPR ground your organisation relies on. If unsure, ask your data protection officer.");
    const purpose = select("purpose", "Purpose", opts.purposes, PURPOSE, true,
      "What the documents will be used for. Questions outside this purpose are not supported.");
    const retention = field("retention_days", "Keep for (days)", "number", false,
      `Documents are deleted automatically afterwards. Leave empty for the default of ${opts.default_retention_days} days.`,
      { min: 1, max: 3650, inputmode: "numeric", placeholder: String(opts.default_retention_days) });
    const consent = field("consent_reference", "Consent record reference", "text", true,
      "Where the consent is recorded, so it can be demonstrated later.", { maxlength: 128 });
    const art9 = select("special_category_condition", "Condition for special-category data", opts.art9_conditions, ART9, false,
      "Only needed if the documents contain health, religion, union membership or similar data. Leave empty otherwise.");
    consent.wrap.hidden = true;
    const art9Details = h("details", {}, h("summary", { text: "Special-category personal data" }), art9.wrap);

    const submit = h("button", { type: "submit", class: "btn btn-primary", disabled: true });
    const form = h("form", { novalidate: true, class: "section" },
      dropzone, fileError, queueEl,
      h("fieldset", {}, h("legend", { text: "How this data will be processed" }),
        h("div", { class: "field-grid two" }, lawful.wrap, purpose.wrap, retention.wrap, consent.wrap),
        art9Details),
      h("div", { class: "actions" }, submit));

    view.append(h("div", { class: "section" }, h("h2", { text: "Upload" }),
      ctx.me.demo ? h("div", { class: "banner warning", role: "note" }, icon("warn"),
        h("div", {}, h("strong", { text: "Public demo: use synthetic data only" }),
          "Your workspace is temporary and separate from other visitors, but do not upload real personal or confidential files.")) : null,
      form));

    // ---- queue handling
    const setFileError = (msg) => { clear(fileError); if (msg) fileError.append(icon("xcircle"), document.createTextNode(msg)); fileError.hidden = !msg; };

    function addFiles(fileList) {
      setFileError("");
      queue = queue.filter((q) => q.status === "queued" || q.status === "error" || q.status === "uploading");
      const problems = [];
      for (const file of fileList) {
        const ext = fileExtension(file.name);
        if (!opts.extensions.includes(ext)) problems.push(`${file.name}: type ${ext || "(none)"} is not supported.`);
        else if (file.size === 0) problems.push(`${file.name}: the file is empty.`);
        else if (file.size > opts.max_upload_bytes) problems.push(`${file.name}: larger than ${formatBytes(opts.max_upload_bytes)}.`);
        else if (!queue.some((q) => q.file.name === file.name && q.file.size === file.size)) {
          queue.push({ id: seq++, file, status: "queued" });
        }
      }
      if (problems.length) setFileError(problems.join(" "));
      paintQueue();
    }
    fileInput.addEventListener("change", () => { addFiles([...fileInput.files]); fileInput.value = ""; });
    for (const ev of ["dragenter", "dragover"]) dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("over"); });
    for (const ev of ["dragleave", "drop"]) dropzone.addEventListener(ev, () => dropzone.classList.remove("over"));
    dropzone.addEventListener("drop", (e) => { e.preventDefault(); addFiles([...e.dataTransfer.files]); });

    function paintQueue() {
      clear(queueEl);
      for (const item of queue) {
        const statusIcon = { queued: ["file", "status-wait"], uploading: ["loader", "status-wait"],
          done: ["check", "status-ok"], duplicate: ["info", "status-wait"], error: ["xcircle", "status-bad"] }[item.status];
        const ic = icon(statusIcon[0], { spin: item.status === "uploading" });
        ic.classList.add(statusIcon[1]);
        const remove = item.status === "queued" || item.status === "error"
          ? h("button", { type: "button", class: "btn btn-ghost btn-icon", "aria-label": `Remove ${item.file.name}`,
              on: { click: () => { queue = queue.filter((q) => q.id !== item.id); paintQueue(); } } }, icon("x"))
          : null;
        queueEl.append(h("li", {}, ic,
          h("div", { class: "grow" },
            h("strong", { text: item.file.name }),
            h("span", { class: "muted small", text: ` · ${formatBytes(item.file.size)}` }),
            item.message ? h("div", { class: `small ${item.status === "error" ? "status-bad" : item.status === "done" ? "" : "muted"}`, text: item.message }) : null,
            item.report && item.report.quarantined_chunks > 0
              ? h("div", { class: "small status-warn" }, icon("warn"), ` ${item.report.quarantined_chunks} section(s) contained instruction-like text and were excluded from answers.`) : null),
          remove));
      }
      const pending = queue.filter((q) => q.status === "queued" || q.status === "error").length;
      submit.disabled = uploading || pending === 0;
      clear(submit);
      if (uploading) submit.append(icon("loader", { spin: true }), document.createTextNode("Uploading…"));
      else setButton(submit, "upload", pending > 1 ? `Upload ${pending} files` : "Upload file");
    }
    paintQueue();

    // ---- validation
    lawful.input.addEventListener("change", () => {
      consent.wrap.hidden = lawful.input.value !== "consent";
      if (consent.wrap.hidden) consent.clearError();
    });

    function validate() {
      let first = null;
      const fail = (f, msg) => { f.setError(msg); first = first || f.input; };
      lawful.clearError(); purpose.clearError(); retention.clearError(); consent.clearError(); art9.clearError();
      if (!lawful.input.value) fail(lawful, "Choose a lawful basis.");
      if (!purpose.input.value) fail(purpose, "Choose a purpose.");
      const days = retention.input.value.trim();
      if (days && !(/^\d+$/.test(days) && +days >= 1 && +days <= 3650)) fail(retention, "Enter a whole number of days from 1 to 3650.");
      if (lawful.input.value === "consent" && !consent.input.value.trim()) fail(consent, "Enter where the consent is recorded.");
      if (first) first.focus();
      return !first;
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (uploading) return;
      if (!queue.some((q) => q.status === "queued" || q.status === "error")) { setFileError("Choose at least one file."); fileInput.focus(); return; }
      if (!validate()) return;
      uploading = true;
      const fields = {
        lawful_basis: lawful.input.value, purpose: purpose.input.value,
        retention_days: retention.input.value.trim(), consent_reference: consent.input.value.trim(),
        special_category_condition: art9.input.value,
      };
      let ok = 0, failed = 0;
      for (const item of queue.filter((q) => q.status === "queued" || q.status === "error")) {
        item.status = "uploading"; item.message = "Reading, masking personal data and indexing…"; paintQueue();
        try {
          const report = await ctx.api.upload(item.file, fields);
          item.report = report;
          item.status = report.duplicate ? "duplicate" : "done";
          item.message = report.duplicate ? "Already uploaded. Not stored again."
            : `${report.chunks} sections indexed · personal data masked: ${piiSummary(report.pii_redacted)} · deleted on ${formatDate(report.expires_at)}`;
          ok++;
        } catch (err) {
          item.status = "error"; item.message = err.message; failed++;
          if (/Art\. 9/.test(err.message)) {
            // Progressive disclosure: reveal the field that fixes this error.
            art9Details.open = true; art9.setError("Choose the condition that applies, then upload again."); art9.input.focus();
          }
          if (err.status === 429) break; // stop hammering a rate-limited API
        }
        paintQueue();
      }
      uploading = false;
      paintQueue();
      const summary = `${ok} uploaded${failed ? `, ${failed} failed` : ""}.`;
      ctx.announce(summary);
      ctx.toast(summary, failed ? "error" : "success");
      if (ok && canList) loadLibrary();
    });
  }

  // ----------------------------------------------------------------- library
  const libraryBody = h("div", {});
  if (canList) {
    const refresh = h("button", { type: "button", class: "btn btn-sm", on: { click: () => loadLibrary() } }, icon("refresh"), "Refresh");
    view.append(h("div", { class: "section" },
      h("div", { class: "meta-row" }, h("h2", { text: "Library" }), h("span", { class: "flex-1" }), refresh),
      libraryBody));
    loadLibrary();
  } else {
    view.append(h("div", { class: "banner info", role: "note" }, icon("info"),
      h("div", {}, h("strong", { text: "Document list not available" }), "Your role can upload but not list documents.")));
  }

  async function loadLibrary() {
    clear(libraryBody);
    libraryBody.append(h("div", { class: "skeleton", role: "status", "aria-label": "Loading documents" }, h("i"), h("i"), h("i")));
    try {
      const docs = (await ctx.api.listDocuments()).sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at));
      paintLibrary(docs);
    } catch (err) {
      clear(libraryBody).append(h("div", { class: "banner danger", role: "alert" }, icon("xcircle"),
        h("div", {}, h("strong", { text: "Could not load documents" }), err.message, " ",
          h("button", { type: "button", class: "btn btn-sm", on: { click: loadLibrary } }, icon("refresh"), "Try again"))));
    }
  }

  function paintLibrary(docs) {
    clear(libraryBody);
    if (!docs.length) {
      libraryBody.append(h("div", { class: "empty" }, icon("file"),
        h("strong", { text: "No documents yet" }),
        h("p", { class: "muted", text: canUpload ? "Upload your first financial document above." : "Ask an analyst to upload documents." })));
      return;
    }
    const canDelete = ctx.has("delete_document");
    const rows = docs.map((d) => h("tr", {},
      h("td", { dataset: { label: "Document" } }, h("strong", { class: "fname", text: d.filename }), " ",
        h("span", { class: "badge", text: d.file_type.toUpperCase() })),
      h("td", { dataset: { label: "Uploaded" } }, h("time", { datetime: d.uploaded_at, text: formatDateTime(d.uploaded_at) }),
        h("div", { class: "muted", text: `by ${d.uploaded_by}` }),
        h("div", { class: "muted" }, "Deleted on ", h("time", { datetime: d.expires_at, text: formatDate(d.expires_at) }))),
      h("td", { dataset: { label: "Basis and purpose" } }, label(LAWFUL_BASIS, d.lawful_basis), h("div", { class: "muted", text: label(PURPOSE, d.purpose) })),
      h("td", { dataset: { label: "Privacy" } },
        h("div", { text: `Masked: ${piiSummary(d.pii_counts)}` }),
        d.special_categories && d.special_categories.length
          ? h("div", { class: "status-warn" }, icon("warn"), ` Special-category terms: ${d.special_categories.join(", ")}`) : null,
        d.quarantined_chunks > 0
          ? h("div", { class: "status-warn" }, icon("warn"), ` ${d.quarantined_chunks} section(s) excluded from answers`) : null),
      canDelete ? h("td", { class: "col-actions" }, h("button", { type: "button", class: "btn btn-sm", "aria-label": `Delete ${d.filename}`,
        on: { click: () => deleteDoc(d) } }, icon("trash"), "Delete")) : null));
    libraryBody.append(h("div", { class: "table-wrap" }, h("table", {},
      h("caption", { class: "visually-hidden", text: "Uploaded documents" }),
      h("thead", {}, h("tr", {}, ["Document", "Uploaded", "Basis and purpose", "Privacy"].map((t) => h("th", { scope: "col", text: t })),
        canDelete ? h("th", { scope: "col" }, h("span", { class: "visually-hidden", text: "Actions" })) : null)),
      h("tbody", {}, rows))));
  }

  async function deleteDoc(d) {
    const yes = await ctx.confirm({
      title: `Delete ${d.filename}?`,
      body: "This permanently removes the document, its indexed sections and any personal-data mappings used only by it. It cannot be undone.",
      confirmText: "Delete document",
    });
    if (!yes) return;
    try {
      await ctx.api.deleteDocument(d.doc_id);
      ctx.toast(`${d.filename} deleted.`, "success");
      ctx.announce(`${d.filename} deleted.`);
      loadLibrary();
    } catch (err) { ctx.toast(err.message, "error"); }
  }

  return null;
}

// ------------------------------------------------------------- form helpers
let uid = 0;

/** A labelled text/number input with helper text and an inline error slot. */
function field(name, text, type, required, help, attrs = {}) {
  const id = `f-${name}-${++uid}`;
  const input = h("input", { id, name, type, "aria-describedby": `${id}-help ${id}-err`, ...attrs });
  return fieldWrap(id, text, required, help, input);
}

function select(name, text, values, labels, required, help) {
  const id = `f-${name}-${++uid}`;
  const input = h("select", { id, name, "aria-describedby": `${id}-help ${id}-err` },
    h("option", { value: "", text: required ? "Select…" : "Not applicable" }),
    values.map((v) => h("option", { value: v, text: label(labels, v) })));
  return fieldWrap(id, text, required, help, input);
}

function fieldWrap(id, text, required, help, input) {
  const err = h("p", { id: `${id}-err`, class: "error-text", role: "alert", hidden: true });
  const wrap = h("div", { class: "field" },
    h("label", { for: id }, text, required ? h("span", { class: "req", "aria-hidden": "true", text: " *" }) : null),
    input, h("p", { id: `${id}-help`, class: "help", text: help }), err);
  if (required) input.setAttribute("required", "");
  return {
    wrap, input,
    setError(msg) { clear(err); err.append(icon("xcircle"), document.createTextNode(msg)); err.hidden = false; input.setAttribute("aria-invalid", "true"); },
    clearError() { err.hidden = true; input.removeAttribute("aria-invalid"); },
  };
}
