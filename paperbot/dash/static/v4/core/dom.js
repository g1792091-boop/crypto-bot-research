// DOM helpers. Every string that reaches the page goes in as a TEXT node (h() / s() / text()): model text, staff
// messages, account names, anything from the server. There is no helper that parses HTML. The only innerHTML writes in
// the v4 files are clear(el) (empties a node) and none other; tests/test_dash_v4.py enforces it.

const SVG_NS = "http://www.w3.org/2000/svg";

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
      // handlers are functions only: a string would become inline script, so it is dropped
      if (typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    } else if (/^(srcdoc|formaction)$/i.test(k)) {
      continue;                                   // never set: both can carry markup or script
    } else if (k === "text") {
      el.textContent = String(v);
    } else if (k === "href" || k === "src") {
      // only same-site links, fragment links and http(s) links: never "javascript:" or "data:", and never a
      // protocol-relative "//other.host" (a leading "/" must be a path on this site)
      const s = String(v);
      if (/^(https?:|\/(?!\/)|#|\.\/|\?)/i.test(s)) el.setAttribute(k, s);
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

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/** Empties a node. */
export function clear(el) {
  if (el) el.innerHTML = "";
  return el;
}

/** Replaces a node's children with the given ones. */
export function put(el, ...kids) {
  clear(el);
  appendKids(el, kids);
  return el;
}

/** Sets text (never HTML). */
export function text(el, v) {
  if (el) el.textContent = v == null ? "" : String(v);
  return el;
}

/** addEventListener that returns its own remover (ctx.track() it in a screen). */
export function on(el, ev, fn, opts) {
  if (!el) return () => {};
  el.addEventListener(ev, fn, opts);
  return () => el.removeEventListener(ev, fn, opts);
}

/** Escape for the rare attribute or title built as a string (prefer h()). */
export function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}

/** A stable hue (0-359) from a string: avatars and figures of people without a team colour. */
export function hueOf(str) {
  let x = 7;
  for (const ch of String(str)) x = (x * 31 + ch.charCodeAt(0)) % 360;
  return x;
}

/** try/catch localStorage (private windows, blocked storage): per-viewer conveniences only. */
export const local = {
  get(k, d = null) {
    try { const v = localStorage.getItem("pb4-" + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; }
  },
  set(k, v) {
    try { localStorage.setItem("pb4-" + k, JSON.stringify(v)); } catch (e) { /* storage blocked */ }
  },
  del(k) {
    try { localStorage.removeItem("pb4-" + k); } catch (e) { /* storage blocked */ }
  },
};
