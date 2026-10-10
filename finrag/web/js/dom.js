// DOM helpers and icons.
//
// Everything on screen is built with createElement / textContent, never with
// innerHTML. Model output, filenames and document excerpts are untrusted, and this
// makes script injection through them impossible by construction.
//   [RULE: OWASP-LLM05] Improper output handling: LLM output is rendered as text only.
//   [RULE: SEC-INPUT-VALIDATION] Untrusted strings never reach an HTML parser.

const SVG_NS = "http://www.w3.org/2000/svg";

/**
 * Build an element. `attrs` may contain: class, text, on (map of event handlers),
 * dataset, and any other attribute (booleans toggle the attribute).
 */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key === "on") for (const [ev, fn] of Object.entries(value)) el.addEventListener(ev, fn);
    else if (key === "dataset") Object.assign(el.dataset, value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  append(el, children);
  return el;
}

export function append(parent, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return parent;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

// Lucide-style stroke icons (24x24). Each entry is a list of [tag, attributes].
const ICONS = {
  message: [["path", { d: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" }]],
  file: [["path", { d: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" }],
    ["path", { d: "M14 2v6h6" }], ["path", { d: "M16 13H8" }], ["path", { d: "M16 17H8" }]],
  shield: [["path", { d: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" }]],
  info: [["circle", { cx: 12, cy: 12, r: 10 }], ["path", { d: "M12 16v-4" }], ["path", { d: "M12 8h.01" }]],
  upload: [["path", { d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" }], ["path", { d: "M17 8l-5-5-5 5" }],
    ["path", { d: "M12 3v12" }]],
  download: [["path", { d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" }], ["path", { d: "M7 10l5 5 5-5" }],
    ["path", { d: "M12 15V3" }]],
  send: [["path", { d: "M22 2L11 13" }], ["path", { d: "M22 2l-7 20-4-9-9-4 20-7z" }]],
  trash: [["path", { d: "M3 6h18" }], ["path", { d: "M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" }],
    ["path", { d: "M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" }]],
  warn: [["path", { d: "M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" }],
    ["path", { d: "M12 9v4" }], ["path", { d: "M12 17h.01" }]],
  check: [["path", { d: "M22 11.08V12a10 10 0 1 1-5.93-9.14" }], ["path", { d: "M22 4L12 14.01l-3-3" }]],
  xcircle: [["circle", { cx: 12, cy: 12, r: 10 }], ["path", { d: "M15 9l-6 6" }], ["path", { d: "M9 9l6 6" }]],
  x: [["path", { d: "M18 6L6 18" }], ["path", { d: "M6 6l12 12" }]],
  logout: [["path", { d: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" }], ["path", { d: "M16 17l5-5-5-5" }],
    ["path", { d: "M21 12H9" }]],
  moon: [["path", { d: "M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" }]],
  sun: [["circle", { cx: 12, cy: 12, r: 5 }], ["path", { d: "M12 1v2" }], ["path", { d: "M12 21v2" }],
    ["path", { d: "M4.22 4.22l1.42 1.42" }], ["path", { d: "M18.36 18.36l1.42 1.42" }], ["path", { d: "M1 12h2" }],
    ["path", { d: "M21 12h2" }], ["path", { d: "M4.22 19.78l1.42-1.42" }], ["path", { d: "M18.36 5.64l1.42-1.42" }]],
  eye: [["path", { d: "M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" }], ["circle", { cx: 12, cy: 12, r: 3 }]],
  eyeOff: [["path", { d: "M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" }],
    ["path", { d: "M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" }],
    ["path", { d: "M1 1l22 22" }]],
  copy: [["rect", { x: 9, y: 9, width: 13, height: 13, rx: 2 }],
    ["path", { d: "M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" }]],
  loader: [["path", { d: "M21 12a9 9 0 1 1-6.219-8.56" }]],
  lock: [["rect", { x: 3, y: 11, width: 18, height: 11, rx: 2 }], ["path", { d: "M7 11V7a5 5 0 0 1 10 0v4" }]],
  refresh: [["path", { d: "M23 4v6h-6" }], ["path", { d: "M1 20v-6h6" }],
    ["path", { d: "M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" }]],
};

/** Decorative icon by default (aria-hidden); pass `label` to make it meaningful. */
export function icon(name, { label, spin = false } = {}) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon" + (spin ? " spin" : ""));
  if (label) { svg.setAttribute("role", "img"); svg.setAttribute("aria-label", label); }
  else svg.setAttribute("aria-hidden", "true");
  for (const [tag, attrs] of ICONS[name] || []) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
    svg.append(node);
  }
  return svg;
}

/** Replace a button's contents with an icon and optional visible text. */
export function setButton(btn, iconName, text) {
  clear(btn);
  if (iconName) btn.append(icon(iconName));
  if (text) btn.append(document.createTextNode(text));
}
