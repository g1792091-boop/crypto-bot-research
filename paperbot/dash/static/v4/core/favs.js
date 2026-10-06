// ★ 즐겨찾기 (owners 10/06, conv-b: "자주 보는 매매법·계좌·코인을 한 곳에"): a star on strategies, accounts and coins;
// the starred ones gather in the 홈 strip (screens/home-favs.js), the ★ button (core/favpop.js: the rail foot, the top bar, the strip end; a small list under or next to the
// rail), the side panel's head (core/drawer.js), 찾기 with an empty box (core/find.js), and a '즐겨찾기만' filter on the
// strategy list, 순위표 (cards and table) and the 계좌 picker.
// Per device only: one storage key "favs" through dom.js `local` (try/catch inside; a private window or blocked
// storage simply keeps nothing). Nothing is sent to the server. A change re-marks every star on the page at once and
// tells the listeners (bus "favs"), so the strip, the rail and the lists follow without a reload.
// HONESTY: a star is a bookmark, never a ranking or a signal; the places that show a starred DeepSeek / coin-flip
// account outside its own group count it only (derive.countOnlyIn), like every other mixed list.
import {h, $$, local} from "./dom.js";
import {bus} from "./api.js";

export const FAV_KEY = "favs";
export const FAV_KINDS = ["strategy", "account", "coin"];
export const FAV_KO = {strategy: "매매법", account: "계좌", coin: "코인"};
export const FAV_MAX = 40;                 // per kind (the newest stay)
const ID_RE = /^[A-Za-z0-9_.@~:\-]{1,80}$/;

/** {strategy: [ids], account: [ids], coin: [ids]}, newest first, from a stored value (anything odd is dropped). */
export function readFavs(raw) {
  const out = {strategy: [], account: [], coin: []};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  for (const k of FAV_KINDS) {
    const xs = Array.isArray(raw[k]) ? raw[k] : [];
    const seen = new Set();
    for (const x of xs) {
      const id = typeof x === "string" ? x : null;
      if (!id || !ID_RE.test(id) || seen.has(id)) continue;
      seen.add(id);
      out[k].push(id);
      if (out[k].length >= FAV_MAX) break;
    }
  }
  return out;
}
/** The value after starring (on) or un-starring one id: newest first, at most FAV_MAX per kind. */
export function withFav(cur, kind, id, on) {
  const out = readFavs(cur);
  if (!FAV_KINDS.includes(kind) || typeof id !== "string" || !ID_RE.test(id)) return out;
  out[kind] = out[kind].filter((x) => x !== id);
  if (on) out[kind] = [id, ...out[kind]].slice(0, FAV_MAX);
  return out;
}

export const favs = () => readFavs(local.get(FAV_KEY, null));
export const isFav = (kind, id) => favs()[kind]?.includes(String(id)) || false;
export const favCount = (f = favs()) => FAV_KINDS.reduce((n, k) => n + f[k].length, 0);
/** fn({kind, id, on}) after every change on this page; returns the remover (ctx.track() it in a screen). */
export const onFavs = (fn) => bus.on("favs", fn);

/** Star (on = true) or un-star one strategy / account / coin. Returns the new state. */
export function setFav(kind, id, on) {
  id = String(id);
  const next = withFav(favs(), kind, id, !!on);
  local.set(FAV_KEY, next);
  const now = next[kind] ? next[kind].includes(id) : false;
  if (typeof document !== "undefined") for (const b of $$(".favstar")) if (b.dataset.fk === kind && b.dataset.fid === id) paint(b, now);
  bus.emit("favs", {kind, id, on: now});
  return now;
}
export const toggleFav = (kind, id) => setFav(kind, id, !isFav(kind, id));

function paint(b, on) {
  b.setAttribute("aria-pressed", String(on));
  const lab = b.dataset.label || "";
  b.title = on ? `즐겨찾기에서 빼기${lab ? ` (${lab})` : ""}` : `즐겨찾기에 넣기${lab ? ` (${lab})` : ""}`;
  b.setAttribute("aria-label", b.title);
  const g = b.querySelector(".favstar-g");
  if (g) g.textContent = on ? "★" : "☆";
  const t = b.querySelector(".favstar-t");
  if (t) t.textContent = on ? "즐겨찾기 됨" : "즐겨찾기";
}

/**
 * starBtn(kind, id, {label, text, cls}) -> the ☆ / ★ toggle. text: true adds the word ('즐겨찾기' / '즐겨찾기 됨') for
 * a head row; without it the button is the star alone (32 px touch target). label: the thing's name (tooltip).
 */
export function starBtn(kind, id, o = {}) {
  const b = h("button", {type: "button", class: ["favstar", o.text ? "wtext" : "", o.cls || ""], dataset: {fk: kind, fid: String(id), label: o.label || null},
    onclick: (e) => { e.preventDefault(); e.stopPropagation(); toggleFav(kind, String(id)); }},
  h("span", {class: "favstar-g", "aria-hidden": "true"}, "☆"), o.text ? h("span", {class: "favstar-t"}, "즐겨찾기") : null);
  paint(b, isFav(kind, String(id)));
  return b;
}

/** A small non-interactive ★ for a starred row (inside a link or a row button: never a nested button). */
export const favMark = (kind, id) => (isFav(kind, String(id)) ? h("span", {class: "favmark", title: "즐겨찾기", "aria-label": "즐겨찾기"}, "★") : null);

/**
 * favFilter({memo, onChange, label}) -> the '★ 즐겨찾기만' switch of a list (aria-pressed, remembered per list on this
 * device when memo is given). .on() reads it; the count of starred things is in its title.
 */
export function favFilter(o = {}) {
  let on = o.memo ? local.get(o.memo, false) === true : false;
  const b = h("button", {type: "button", class: "favfilter", "aria-pressed": String(on), title: o.title || "별(★)을 누른 것만 보기",
    onclick: () => { on = !on; b.setAttribute("aria-pressed", String(on)); if (o.memo) local.set(o.memo, on); if (o.onChange) o.onChange(on); }},
  h("span", {"aria-hidden": "true"}, "★"), " ", o.label || "즐겨찾기만");
  b.on = () => on;
  return b;
}
