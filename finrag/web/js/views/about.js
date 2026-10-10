// "About" screen: transparency information for users of the AI system.
//
//   [RULE: EUAIA-ART13] Intended purpose, limitations, accuracy measures, oversight.
//   [RULE: EUAIA-ART50] Plain statement that the user is interacting with AI.
//   [RULE: EUAIA-ART4]  Guidance that supports staff AI literacy.
//   [RULE: GDPR-ART13]  Privacy notice: purposes, recipients, retention, rights.

import { h, icon, clear } from "../dom.js";
import { keyValues } from "./privacy.js";

export function renderAbout(root, ctx) {
  const body = h("div", { class: "section", "aria-live": "polite" },
    h("div", { class: "skeleton", role: "status", "aria-label": "Loading" }, h("i"), h("i"), h("i")));
  root.append(h("section", { class: "view" },
    h("div", { class: "view-head" },
      h("h1", { text: "About this AI system" }),
      h("p", { class: "muted", text: "What FinRAG is for, what it cannot do, and how your data is handled." })),
    body));

  ctx.api.transparency().then(({ model_card: card, privacy_notice: notice }) => {
    clear(body);
    const offline = ctx.me.provider === "offline";
    body.append(
      h("div", { class: "banner info", role: "note" }, icon("info"),
        h("div", {}, h("strong", { text: "You are interacting with an AI system" }), card.ai_disclosure)),
      h("div", { class: "card section" }, h("h2", { text: "Current mode" }),
        h("p", {}, offline
          ? "Offline mode: answers are quoted from your documents on this server. Nothing is sent to an AI provider."
          : `AI mode: excerpts with personal data masked are sent to ${card.model.provider} (${card.model.name}) to write answers.`)),
      section("Intended purpose", h("p", { text: card.intended_purpose })),
      section("Not supported", list(card.excluded_uses)),
      section("Known limitations", list(card.known_limitations)),
      section("How answers are checked", h("p", { text: card.how_it_works }), list(card.accuracy_measures)),
      section("Human oversight", h("p", { text: card.human_oversight })),
      section("Using it well", list(card.user_guidance)),
      h("div", { class: "card section" }, h("h2", { text: "Privacy notice" }), keyValues(notice)));
  }).catch((err) => {
    clear(body).append(h("div", { class: "banner danger", role: "alert" }, icon("xcircle"),
      h("div", {}, h("strong", { text: "Could not load this page" }), err.message)));
  });
  return null;
}

const section = (title, ...content) => h("div", { class: "card section" }, h("h2", { text: title }), ...content);
const list = (items) => h("ul", {}, items.map((t) => h("li", { text: t })));
