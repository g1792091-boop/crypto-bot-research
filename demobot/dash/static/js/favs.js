// ★ 즐겨찾기 (round 4, like the rule bot's v4 core/favs.js): a star on screens (each screen's title) and on accounts
// (the account rows and the account page); the starred ones gather in the top bar's ★ list and come first in 찾기.
// Per device only: one storage key through dom.js `local` (try/catch inside: a private window simply keeps nothing).
// Nothing is sent to the server. A change re-marks every star on the page at once and tells the listeners.
// A star is a bookmark, never a ranking or a signal.
import {h, local} from "./dom.js";

const KEY = "favs";
export const FAV_KINDS = ["page", "account"];
const MAX = 40;
const ID_RE = /^[A-Za-z0-9-]{1,40}$/;
const fns = new Set();

/** {page: [ids], account: [ids]}, newest first; anything odd in storage is dropped. */
export function favs() {
  const raw = local.get(KEY, null);
  const out = {page: [], account: []};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  for (const k of FAV_KINDS) {
    const seen = new Set();
    for (const x of Array.isArray(raw[k]) ? raw[k] : []) {
      if (typeof x !== "string" || !ID_RE.test(x) || seen.has(x)) continue;
      seen.add(x);
      out[k].push(x);
      if (out[k].length >= MAX) break;
    }
  }
  return out;
}
export const isFav = (kind, id) => (favs()[kind] || []).includes(String(id));
export const favCount = () => FAV_KINDS.reduce((n, k) => n + favs()[k].length, 0);
/** fn() after every change; returns the remover. */
export function onFavs(fn) { fns.add(fn); return () => fns.delete(fn); }

export function setFav(kind, id, on) {
  id = String(id);
  if (!FAV_KINDS.includes(kind) || !ID_RE.test(id)) return false;
  const f = favs();
  f[kind] = f[kind].filter((x) => x !== id);
  if (on) f[kind] = [id, ...f[kind]].slice(0, MAX);
  local.set(KEY, f);
  for (const b of document.querySelectorAll(".favstar")) if (b.dataset.fk === kind && b.dataset.fid === id) paint(b, !!on);
  for (const fn of fns) { try { fn(); } catch (e) { console.error(e); } }
  return !!on;
}
export const toggleFav = (kind, id) => setFav(kind, id, !isFav(kind, id));

function paint(b, on) {
  b.setAttribute("aria-pressed", String(on));
  const lab = b.dataset.label || "";
  b.title = on ? `즐겨찾기에서 빼기${lab ? ` (${lab})` : ""}` : `즐겨찾기에 넣기${lab ? ` (${lab})` : ""}`;
  b.setAttribute("aria-label", b.title);
  b.firstChild.textContent = on ? "★" : "☆";
}

/** starBtn("page" | "account", id, {label}) -> the ☆ / ★ toggle (a 32 px button; never inside a link). */
export function starBtn(kind, id, o = {}) {
  const b = h("button", {type: "button", class: ["favstar", o.cls], dataset: {fk: kind, fid: String(id), label: o.label || null},
    onclick: (e) => { e.preventDefault(); e.stopPropagation(); toggleFav(kind, String(id)); }},
  h("span", {"aria-hidden": "true"}, "☆"));
  paint(b, isFav(kind, String(id)));
  return b;
}
