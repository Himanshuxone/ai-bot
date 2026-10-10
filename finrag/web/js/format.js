// Labels and formatting.
//
// Plain-language wording for values the API returns. Messages follow the Design
// System: say what happened and what to do, never reveal detector internals.

export const LAWFUL_BASIS = {
  consent: "Consent (Art. 6(1)(a))",
  contract: "Contract (Art. 6(1)(b))",
  legal_obligation: "Legal obligation (Art. 6(1)(c))",
  vital_interests: "Vital interests (Art. 6(1)(d))",
  public_task: "Public task (Art. 6(1)(e))",
  legitimate_interests: "Legitimate interests (Art. 6(1)(f))",
};

export const PURPOSE = {
  financial_analysis: "Financial analysis",
  financial_reporting: "Financial reporting",
  audit_support: "Audit support",
  regulatory_compliance: "Regulatory compliance",
};

export const ART9 = {
  explicit_consent: "Explicit consent (Art. 9(2)(a))",
  employment_social_security_law: "Employment and social security law (Art. 9(2)(b))",
  legal_claims: "Legal claims (Art. 9(2)(f))",
  substantial_public_interest: "Substantial public interest (Art. 9(2)(g))",
};

// [RULE: EUAIA-ART14] Human oversight: say plainly why a person should check.
export const REVIEW_REASONS = {
  low_confidence: "The match with your documents is weak.",
  no_citations: "The answer does not cite any document.",
  invalid_citations: "The answer refers to a source that was not provided.",
  unverified_figures: "Some numbers could not be found in the cited documents.",
  advice_requested: "This looks like a request for advice. FinRAG gives information only.",
  answer_truncated: "The answer was cut short.",
};

export function label(map, key) { return map[key] || key; }

export function formatBytes(n) {
  if (n >= 1048576) return `${(n / 1048576).toFixed(n % 1048576 === 0 ? 0 : 1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

const dateFmt = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const dateTimeFmt = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function formatDate(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : dateFmt.format(d);
}
export function formatDateTime(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : dateTimeFmt.format(d);
}

/** "EMAIL x2, IBAN x1" */
export function piiSummary(counts) {
  const parts = Object.entries(counts || {}).map(([k, v]) => `${k.replaceAll("_", " ")} ×${v}`);
  return parts.length ? parts.join(", ") : "none found";
}

export function fileExtension(name) {
  const i = name.lastIndexOf(".");
  return i === -1 ? "" : name.slice(i).toLowerCase();
}
