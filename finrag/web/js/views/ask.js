// "Ask" screen: question box, conversation, answer cards.
//
// Each answer shows what the API contract requires (docs/project/Design_System.md):
//   - citations as buttons that open the matching source excerpt,
//   - a human-review banner with plain-language reasons,
//   - the AI disclosure and the not-advice disclaimer, always visible,
//   - privacy placeholders (<EMAIL_...>) shown literally, never "decoded".
//
//   [RULE: OWASP-LLM05]  Answer text is inserted as text nodes only.
//   [RULE: EUAIA-ART50]  AI disclosure + model label on every answer.
//   [RULE: EUAIA-ART14]  Review banner explains why a person should check.
//   [RULE: FIN-NO-ADVICE] Disclaimer shown with every answer.
//   [RULE: OWASP-LLM09]  Every citation is checked against the sources returned.

import { h, icon, clear, setButton } from "../dom.js";
import { REVIEW_REASONS } from "../format.js";

// The conversation lives in memory only. It survives switching tabs inside the app
// but is gone on reload or sign-out, and it is never written to storage.
//   [RULE: GDPR-ART5-1E] Storage limitation: no answers persisted in the browser.
let thread = [];
let nextId = 1;

const SUGGESTIONS = [
  "What was net income in FY2024?",
  "Compare revenue across all years",
  "What are total operating expenses?",
  "Which documents mention a refund?",
];

// [S1], [S1, S2] citations, and privacy placeholders such as <EMAIL_9f2c1a7b3e>,
// [REDACTED:IBAN] or [ERASED].
const INLINE_RE = /(\[S\d+(?:\s*,\s*S?\d+)*\])|(<[A-Z_]+_[0-9a-f]{10}>|\[REDACTED:[A-Z_]+\]|\[ERASED\])/g;

export function renderAsk(root, ctx) {
  const maxChars = ctx.me.options.max_query_chars;
  let busy = false;

  const status = h("p", { class: "muted small", id: "ask-status" });
  const list = h("ol", { class: "thread", "aria-label": "Conversation" });
  const suggestions = h("div", { class: "suggestions", role: "group", "aria-label": "Example questions" });
  const suggestionsWrap = h("div", { class: "section" },
    h("p", { class: "small muted", text: "Try one of these:" }), suggestions);
  const intro = h("div", { class: "section" });

  const textarea = h("textarea", {
    id: "question", rows: 2, maxlength: maxChars, "aria-describedby": "q-help q-error q-count",
    placeholder: "e.g. What was EBITDA in FY2024?", autocomplete: "off",
  });
  const counter = h("span", { id: "q-count", class: "small muted num", text: `0 / ${maxChars}` });
  const error = h("p", { id: "q-error", class: "error-text", role: "alert", hidden: true });
  const sendBtn = h("button", { class: "btn btn-primary", type: "submit" });
  setButton(sendBtn, "send", "Ask");

  let reidentify = null;
  const reidWrap = ctx.has("reidentify")
    ? h("label", { class: "checkbox small" },
        (reidentify = h("input", { type: "checkbox", id: "reid" })),
        h("span", {}, h("strong", { text: "Show original personal data. " }),
          "Replaces privacy placeholders with real values. Restricted to DPOs and recorded in the audit log."))
    : null;

  const form = h("form", { class: "composer", novalidate: true },
    h("label", { for: "question", class: "visually-hidden", text: "Ask a question about your documents" }),
    h("div", { class: "composer-row" }, textarea, sendBtn),
    reidWrap, error,
    h("div", { class: "foot" },
      h("span", { id: "q-help", class: "small muted hint", text: "Enter to send · Shift+Enter for a new line" }),
      counter));

  root.append(h("section", { class: "view" },
    h("div", { class: "view-head" },
      h("h1", { text: "Ask your documents" }),
      h("p", { class: "muted", text: "Questions are answered only from the documents your organisation uploaded, with sources you can check." }),
      status),
    intro, suggestionsWrap, list, form));

  // ---------------------------------------------------------------- helpers
  function autoGrow() {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
  }
  function setError(message) {
    clear(error);
    if (message) { error.append(icon("xcircle"), document.createTextNode(message)); }
    error.hidden = !message;
    if (message) textarea.setAttribute("aria-invalid", "true"); else textarea.removeAttribute("aria-invalid");
  }
  function setBusy(value) {
    busy = value;
    sendBtn.disabled = value;
    clear(sendBtn);
    if (value) sendBtn.append(icon("loader", { spin: true }), document.createTextNode("Asking…"));
    else setButton(sendBtn, "send", "Ask");
  }

  async function refreshDocCount() {
    if (!ctx.has("list_documents")) return;
    try {
      const docs = await ctx.api.listDocuments();
      clear(intro);
      if (docs.length === 0) {
        intro.append(h("div", { class: "banner info", role: "note" }, icon("info"),
          h("div", {}, h("strong", { text: "No documents yet" }),
            ctx.has("ingest") ? ["Upload a financial document first. ",
              h("a", { href: "#/documents", text: "Go to Documents" })] : "Ask an analyst to upload documents.")));
        status.textContent = "";
      } else {
        status.textContent = `Searching ${docs.length} document${docs.length === 1 ? "" : "s"}.`;
      }
    } catch { /* the count is a convenience; ignore failures */ }
  }

  function renderSuggestions() {
    clear(suggestions);
    suggestionsWrap.hidden = thread.length > 0;
    if (thread.length) return;
    for (const text of SUGGESTIONS) {
      suggestions.append(h("button", { type: "button", class: "chip", text,
        on: { click: () => { textarea.value = text; onInput(); textarea.focus(); } } }));
    }
  }

  function onInput() {
    counter.textContent = `${textarea.value.length} / ${maxChars}`;
    if (textarea.value.trim()) setError("");
    autoGrow();
  }

  // -------------------------------------------------------------- submitting
  async function ask(turn) {
    setBusy(true);
    turn.status = "loading";
    paintTurn(turn);
    try {
      turn.data = await ctx.api.query(turn.question, turn.reidentify);
      turn.status = "done";
    } catch (err) {
      turn.status = "error";
      turn.error = err;
    }
    paintTurn(turn);
    setBusy(false);
    if (turn.status === "done") {
      ctx.announce(turn.data.blocked ? "Request not processed."
        : turn.data.requires_human_review ? "Answer ready. Check it before using it." : "Answer ready.");
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (busy) return;
    const question = textarea.value.trim();
    if (!question) { setError("Enter a question."); textarea.focus(); return; }
    const turn = { id: nextId++, question, reidentify: Boolean(reidentify && reidentify.checked), status: "loading" };
    thread.push(turn);
    textarea.value = "";
    onInput();
    renderSuggestions();
    list.append(turnElement(turn));
    turn.el.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    ask(turn);
  });
  textarea.addEventListener("input", onInput);
  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); form.requestSubmit(); }
  });

  // -------------------------------------------------------------- rendering
  function turnElement(turn) {
    turn.el = h("li", { class: "turn" },
      h("div", { class: "question" }, h("span", { class: "visually-hidden", text: "You asked: " }), turn.question),
      h("div", { class: "answer-slot" }));
    paintTurn(turn);
    return turn.el;
  }

  function paintTurn(turn) {
    const slot = clear(turn.el.querySelector(".answer-slot"));
    if (turn.status === "loading") {
      slot.append(h("div", { class: "skeleton", role: "status", "aria-label": "Searching documents and writing an answer" },
        h("i"), h("i"), h("i")),
        h("p", { class: "small muted", text: "Searching your documents and writing an answer…" }));
    } else if (turn.status === "error") {
      slot.append(errorBanner(turn));
    } else {
      slot.append(answerCard(turn));
    }
  }

  function errorBanner(turn) {
    const err = turn.error;
    const retry = h("button", { type: "button", class: "btn btn-sm", on: { click: () => { if (!busy) ask(turn); } } },
      icon("refresh"), "Try again");
    return h("div", { class: "banner danger", role: "alert" }, icon("xcircle"),
      h("div", {}, h("strong", { text: err.status === 429 ? "Slow down a moment" : "Could not get an answer" }),
        err.message, " ", err.status === 403 ? "" : retry));
  }

  /** Turn answer text into DOM: bullet lists, citation buttons and placeholder chips. */
  function answerBody(text, citations, turn) {
    const known = new Map(citations.map((c) => [c.label, c]));
    const wrap = h("div", { class: "answer-text" });
    let listEl = null;
    for (const raw of text.split("\n")) {
      const line = raw.trimEnd();
      if (!line.trim()) { listEl = null; continue; }
      const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
      const target = h(bullet ? "li" : "p");
      inline(bullet ? bullet[1] : line, target, known, turn);
      if (bullet) {
        if (!listEl) { listEl = h("ul"); wrap.append(listEl); }
        listEl.append(target);
      } else { listEl = null; wrap.append(target); }
    }
    return wrap;
  }

  function inline(text, parent, known, turn) {
    let last = 0;
    for (const m of text.matchAll(INLINE_RE)) {
      parent.append(text.slice(last, m.index));
      if (m[1]) {
        // One button per cited label: [S1, S3] becomes two buttons.
        for (const lab of m[1].slice(1, -1).split(",").map((s) => s.trim().replace(/^S?/, "S"))) {
          const c = known.get(lab);
          parent.append(c
            ? h("button", { type: "button", class: "cite", text: lab,
                "aria-label": `Source ${lab.slice(1)}: ${c.filename}, ${c.location}`,
                on: { click: () => openSource(turn, lab) } })
            : h("span", { class: "cite unknown", text: lab, title: "This source was not provided" }));
        }
      } else {
        parent.append(h("span", { class: "token", text: m[0],
          title: "Privacy placeholder: the real value is not shown" }));
      }
      last = m.index + m[0].length;
    }
    parent.append(text.slice(last));
  }

  function openSource(turn, lab) {
    const details = turn.el.querySelector("details.sources");
    if (!details) return;
    details.open = true;
    const item = details.querySelector(`[data-label="${lab}"]`);
    if (item) {
      item.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      item.setAttribute("tabindex", "-1");
      item.focus({ preventScroll: true });
      item.classList.remove("flash"); void item.offsetWidth; item.classList.add("flash");
    }
  }

  function answerCard(turn) {
    const d = turn.data;
    const parts = [];

    if (d.blocked) {
      parts.push(h("div", { class: "banner danger", role: "note" }, icon("xcircle"),
        h("div", {}, h("strong", { text: "Request not processed" }), d.answer)));
    } else {
      if (d.requires_human_review) {
        const reasons = d.review_reasons.map((r) => h("li", { text: REVIEW_REASONS[r] || r }));
        parts.push(h("div", { class: "banner warning", role: "note" }, icon("warn"),
          h("div", {}, h("strong", { text: "Check this answer before using it" }),
            reasons.length ? h("ul", {}, reasons) : null)));
      } else if (d.citations.length) {
        parts.push(h("div", { class: "banner success", role: "note" }, icon("check"),
          h("div", {}, h("strong", { text: "Looks consistent" }), "Figures matched your documents.")));
      }
      parts.push(answerBody(d.answer, d.citations, turn));
    }

    if (d.citations.length && !d.blocked) {
      const items = d.citations.map((c) => h("li", { class: "source", dataset: { label: c.label } },
        h("div", {}, h("strong", { text: `${c.label} · ${c.filename}` }),
          h("span", { class: "muted small", text: ` · ${c.location} · relevance ` }),
          h("span", { class: "small num", text: c.score.toFixed(2) })),
        h("blockquote", { text: c.excerpt })));
      parts.push(h("details", { class: "sources" },
        h("summary", { text: `Sources (${d.citations.length})` }), h("ol", {}, items)));
    }

    const actions = h("div", { class: "meta-row" });
    if (!d.blocked) {
      actions.append(h("button", { type: "button", class: "btn btn-sm",
        on: { click: () => copyAnswer(d) } }, icon("copy"), "Copy answer"));
    }
    actions.append(h("span", { class: "badge", title: "Generated by an AI system" },
      icon("info"), `AI-generated · ${d.label.model}`));
    parts.push(actions);
    // [RULE: EUAIA-ART50] [RULE: FIN-NO-ADVICE] Always visible, never collapsed.
    parts.push(h("p", { class: "disclosure", text: `${d.ai_disclosure} ${d.disclaimer}` }));

    return h("article", { class: "answer", "aria-label": "Answer" }, parts);
  }

  async function copyAnswer(d) {
    // The label travels with the text so copied answers stay marked as AI-generated.
    const text = `${d.answer}\n\n— AI-generated by FinRAG (${d.label.model}). Informational only; verify against the cited sources.`;
    try { await navigator.clipboard.writeText(text); ctx.toast("Answer copied.", "success"); }
    catch { ctx.toast("Could not copy. Select the text and copy it manually.", "error"); }
  }

  // ------------------------------------------------------------------ start
  // Restore the conversation when coming back to this tab.
  for (const turn of thread) {
    if (turn.status === "loading") turn.status = "error", turn.error = { status: 0, message: "The request was interrupted." };
    list.append(turnElement(turn));
  }
  renderSuggestions();
  refreshDocCount();
  autoGrow();
  return () => { /* nothing to tear down: handlers die with the DOM */ };
}

/** Called on sign-out so a conversation never leaks to the next user. */
export function resetConversation() { thread = []; }
