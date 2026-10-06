// 매매법 비교 picks (conv-b): the 2-4 strategies or accounts the 비교 screen (#/compare, screens/compare.js) puts side
// by side. '비교에 추가' on a strategy page, an account page and the side panel adds one here; the screen reads the list
// (or ?ids= in its address, which wins and is saved back). Per device only: one storage key "cmp-picks" through
// dom.js `local` (try/catch inside). Coin flips are the yardstick, never a pick (their place is the 동전 봇 순위 row).
import {h, local} from "./dom.js";
import {bus} from "./api.js";
import {href} from "./routes.js";
import {toast} from "./ui.js";

export const CMP_KEY = "cmp-picks";
export const CMP_MAX = 4;
const ID_RE = /^[A-Za-z0-9_.@~:\-]{1,80}$/;
/** A coin-flip account id (RANDOM_k@tf): the yardstick, not a pick. */
export const isFlipId = (id) => /^RANDOM_/i.test(String(id || ""));

/** The picks from a stored value or a comma list: unique, valid, no coin flips, at most CMP_MAX, in order. */
export function readPicks(raw) {
  const xs = Array.isArray(raw) ? raw : typeof raw === "string" ? raw.split(",") : [];
  const out = [];
  for (const x of xs) {
    const id = typeof x === "string" ? x.trim() : "";
    if (!id || !ID_RE.test(id) || isFlipId(id) || out.includes(id)) continue;
    out.push(id);
    if (out.length >= CMP_MAX) break;
  }
  return out;
}
export const picks = () => readPicks(local.get(CMP_KEY, []));
export function setPicks(ids) {
  const v = readPicks(ids);
  local.set(CMP_KEY, v);
  bus.emit("cmp", v);
  return v;
}
/** Add one: {ok, list, full}. A full list (4) keeps its picks and says so. */
export function addPick(id) {
  const cur = picks();
  if (cur.includes(id)) return {ok: true, list: cur, full: false};
  if (cur.length >= CMP_MAX) return {ok: false, list: cur, full: true};
  const list = setPicks([...cur, id]);
  return {ok: list.includes(id), list, full: false};
}
export const removePick = (id) => setPicks(picks().filter((x) => x !== id));
export const compareHref = (ids) => href("compare", null, ids && ids.length ? {ids: ids.join(",")} : null);

/**
 * cmpBtn(id, {label}) -> '＋ 비교에 추가' (or '비교 보기 (n/4)' once it is in the list: a link to the 비교 screen).
 * Null for a coin flip.
 */
export function cmpBtn(id, o = {}) {
  if (isFlipId(id)) return null;
  const b = h("button", {type: "button", class: ["btn-line", "cmpbtn", o.cls || ""], dataset: {cmp: id}});
  const paint = () => {
    const cur = picks(), inn = cur.includes(id);
    b.textContent = inn ? `비교 보기 (${cur.length}/${CMP_MAX})` : "＋ 비교에 추가";
    b.title = inn ? "매매법 비교 화면 열기" : `${o.label || id}을(를) 비교 목록에 넣기 (최대 ${CMP_MAX}개, 이 기기에만 기억)`;
    b.setAttribute("aria-pressed", String(inn));
  };
  b.addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    if (picks().includes(id)) { location.hash = compareHref(picks()); return; }
    const r = addPick(id);
    if (r.full) toast(`비교는 ${CMP_MAX}개까지입니다. 비교 화면에서 하나를 빼 주세요.`);
    else toast(`비교에 넣었습니다 (${r.list.length}/${CMP_MAX})${r.list.length < 2 ? " · 하나 더 고르면 나란히 봅니다" : " · 매매법 › 비교"}`);
    paint();
  });
  const off = bus.on("cmp", () => { if (!b.isConnected && b.dataset.seen) { off(); return; } b.dataset.seen = "1"; paint(); });
  paint();
  return b;
}
