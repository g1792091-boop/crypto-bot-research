// DOM helpers (a small copy of the rule bot's v4 core/dom.js). Every string that reaches the page goes in as a TEXT
// node: account names, settings, reasons, anything from the server. There is no helper that parses HTML, and nothing
// in this dashboard writes markup from strings (tests/test_demobot_dash.py checks it).

const SVG_NS = "http://www.w3.org/2000/svg";   // the SVG namespace name, never fetched

function applyAttrs(el, attrs, svg) {
  if (!attrs) return;
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class" || k === "className") {
      const c = Array.isArray(v) ? v.filter(Boolean).join(" ") : String(v);
      if (svg) el.setAttribute("class", c); else el.className = c;
    } else if (k === "style" && typeof v === "object") {
      for (const [sk, sv] of Object.entries(v)) {
        if (sv == null) continue;
        if (sk.startsWith("--")) el.style.setProperty(sk, String(sv)); else el.style[sk] = sv;
      }
    } else if (k === "dataset" && typeof v === "object") {
      for (const [dk, dv] of Object.entries(v)) if (dv != null) el.dataset[dk] = String(dv);
    } else if (/^on/i.test(k)) {
      if (typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);   // never a string handler
    } else if (/^(srcdoc|formaction)$/i.test(k)) {
      continue;
    } else if (k === "text") {
      el.textContent = String(v);
    } else if (k === "href" || k === "src" || k === "action") {
      const s = String(v);                         // same-site paths and fragments only
      if (/^(\/(?!\/)|#|\.\/|\?)/.test(s)) el.setAttribute(k, s);
    } else if (v === true) {
      el.setAttribute(k, "");
    } else {
      el.setAttribute(k, String(v));
    }
  }
}

function appendKids(el, kids) {
  for (const c of kids) {
    if (c == null || c === false || c === true) continue;
    if (Array.isArray(c)) { appendKids(el, c); continue; }
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

/** h("div", {class: "card", onclick}, "text", childNode, [more]) -> HTMLElement. Strings are text, never HTML. */
export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  if (attrs && (attrs instanceof Node || typeof attrs !== "object" || Array.isArray(attrs))) { kids.unshift(attrs); attrs = null; }
  applyAttrs(el, attrs, false);
  appendKids(el, kids);
  return el;
}

/** s("path", {d: "M0 0"}) -> SVGElement (same rules as h()). */
export function s(tag, attrs, ...kids) {
  const el = document.createElementNS(SVG_NS, tag);
  if (attrs && (attrs instanceof Node || typeof attrs !== "object" || Array.isArray(attrs))) { kids.unshift(attrs); attrs = null; }
  applyAttrs(el, attrs, true);
  appendKids(el, kids);
  return el;
}

/** Empties a node. */
export function clear(el) {
  if (el) el.replaceChildren();
  return el;
}

/** Replaces a node's children with the given ones in one step (no empty frame in between: no flicker). */
export function put(el, ...kids) {
  if (!el) return el;
  const frag = document.createDocumentFragment();
  appendKids(frag, kids);
  el.replaceChildren(frag);
  return el;
}

/** try/catch localStorage: per-viewer conveniences only (last tab, filters, the skin). */
export const local = {
  get(k, d = null) {
    try { const v = localStorage.getItem("dl-" + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; }
  },
  set(k, v) {
    try { localStorage.setItem("dl-" + k, JSON.stringify(v)); } catch (e) { /* storage blocked */ }
  },
};
