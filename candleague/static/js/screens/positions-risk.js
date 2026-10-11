// 포지션 › 위험 사다리 (copied and adapted from the rule bot's paperbot/dash/static/v4/screens/positions-risk.js): every
// open position ranked by how far the mark price is from its liquidation price and from its stop / lock line, as bars
// that move with the 5-second mark. A row pulses only for danger: within 0.5 % of its liquidation, or of a stop that would
// close at a loss. A lock line (the stop already on the profit side) is drawn in the up colour as '잠금까지'.
// While the engine catches up (or its record is old) the live distances mean nothing: the rows then show the
// distances AT THE ENTRY (from the entry price), and say so; a lock line has no entry-time distance (it sits past the
// entry on the profit side by design), so it reads "잠금 중" and ranks by its liquidation distance only. A hidden
// DeepSeek position (D11: no prices) is not in the
// list; the note counts it. Rows open the 터미널 on that position (its entry / stop lines). The list comes filtered by the
// screen (설치 뒤 진입만, js/after.js); the head says so while the switch is on.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as K4 from "../v4kit.js";
import {gap} from "../poskit.js";
import {markOf} from "../live.js";
import {coinShort} from "../labels.js";
import {sideTag, nameNode, kindKo} from "./positions-card.js";
import {afterSuffix} from "../after.js";

export const LIQ_CAP = 0.10;       // a bar is empty at 10 % or more away from the liquidation price, full at 0
export const STOP_CAP = 0.05;      // the stop bar: full at 0, empty at 5 % or more
export const NEAR = 0.005;         // within 0.5 % of the liquidation or a losing stop: the row pulses
export const MAX_ROWS = 12;

/** How full a bar is: 1 at the line, 0 at cap or farther. */
export const closeness = (d, cap) => (d == null ? 0 : Math.max(0, Math.min(1, 1 - d / cap)));
/** Whether a row is in danger: near the liquidation, or near a stop that is not a lock. */
export const danger = (x) => (x.dLiq != null && x.dLiq < NEAR) || (!x.p.stop_is_lock && x.dStop != null && x.dStop < NEAR);

/** The ranking: closest to liquidation first, unknown distances last; hidden positions left out. live: distances from
 *  the mark now (markFn(coin)); otherwise from the entry price (the entry-time distances), where a lock line gets no
 *  distance (lockIdle: from the entry it would always read "닿음"). */
export function rankRisk(list, markFn = markOf, live = true) {
  return (list || []).filter((p) => !p.hidden && p.entry != null).map((p) => {
    const m = live ? markFn(p.coin) : Number(p.entry);
    const lockIdle = !live && !!p.stop_is_lock;
    return {p, lockIdle, dLiq: gap(p.side, m, p.liq), dStop: lockIdle ? null : gap(p.side, m, p.stop)};
  }).sort((a, b) => (a.dLiq ?? 9) - (b.dLiq ?? 9) || String(a.p.id).localeCompare(String(b.p.id)));
}

/** riskLadder(ctx) -> {el, set(list, markFn, live, why), loading(text)}: the side card. */
export function riskLadder(ctx, o = {}) {
  const max = o.max || MAX_ROWS;
  const listEl = h("div", {class: "ps-risk-list", role: "list", "aria-label": "청산까지 가까운 순"});
  const more = h("p", {class: "pos-note"});
  const sub = h("span", {class: "sub"}, "청산가·손절선까지 남은 거리 · 가까운 순");
  const el = h("section", {class: "card ps-risk", "aria-label": "위험 사다리"},
    h("div", {class: "card-h"}, K4.plate("위험 사다리"), sub),
    h("div", {class: "ps-risk-key"}, h("span", null, h("i", {class: "liq"}), "청산가까지"), h("span", null, h("i", {class: "stop"}), "손절선까지"),
      h("span", null, h("i", {class: "lock"}), "잠금선까지 (닿으면 수익으로 끝남)"),
      h("span", {class: "muted"}, "막대가 찰수록 가까움 · 청산가나 손절선 0.5% 안이면 깜빡임")),
    listEl, more);
  const rows = new Map();          // account id -> {key, row, fills, texts}
  const href = (p) => (ctx && ctx.href ? ctx.href("terminal", null, {acct: p.id, coin: p.coin}) : `#/terminal?acct=${encodeURIComponent(p.id)}&coin=${p.coin}`);
  const rowOf = (x) => {
    const p = x.p;
    const key = [p.coin, p.since, p.liq, p.stop, p.stop_is_lock].join("|");
    let r = rows.get(p.id);
    if (r && r.key === key) return r;
    const lock = !!p.stop_is_lock;
    const liqFill = h("i", {class: "liq"}), stopFill = h("i", {class: lock ? "lock" : "stop"});
    const liqTxt = h("b", {class: "num"}, "—"), stopTxt = h("b", {class: "num"}, "—");
    const row = h("a", {class: "ps-risk-row", role: "listitem", href: href(p), title: `${p.id} · 터미널에서 보기`},
      h("span", {class: "ps-risk-h"}, sideTag(p.side), h("b", null, coinShort(p.coin)), h("span", {class: "muted"}, fmt.lev(p.lev)),
        h("span", {class: "ps-risk-n"}, nameNode(p)), h("span", {class: "ps-risk-g muted"}, kindKo(p))),
      h("span", {class: "ps-risk-b"}, h("span", {class: "ps-risk-bar"}, liqFill), h("span", {class: "ps-risk-t"}, "청산 ", liqTxt)),
      h("span", {class: ["ps-risk-b", lock ? "lock" : ""]}, h("span", {class: "ps-risk-bar"}, stopFill),
        h("span", {class: "ps-risk-t"}, lock ? "잠금까지 " : "손절 ", stopTxt)));
    r = {key, row, liqFill, stopFill, liqTxt, stopTxt};
    rows.set(p.id, r);
    return r;
  };
  const paintRow = (r, x) => {
    r.liqFill.style.width = `${(closeness(x.dLiq, LIQ_CAP) * 100).toFixed(1)}%`;
    r.stopFill.style.width = `${(closeness(x.dStop, STOP_CAP) * 100).toFixed(1)}%`;
    r.liqTxt.textContent = x.dLiq == null ? "—" : fmt.pct(x.dLiq * 100, false, 2);
    r.stopTxt.textContent = x.dStop == null ? (x.lockIdle ? "잠금 중" : "—") : x.dStop <= 0 ? "닿음" : fmt.pct(x.dStop * 100, false, 2);
    r.row.classList.toggle("near", danger(x));
  };
  let order = "";
  /** list: /api/positions entries (already filtered by the screen); live false: entry-time distances (why: the reason);
   *  before: how many the screen's 설치 뒤 진입만 left out (said when the ladder is empty). */
  const set = (list, markFn = markOf, live = true, why = "엔진이 따라잡는 중", before = 0) => {
    const ranked = rankRisk(list, markFn, live);
    const shown = ranked.slice(0, max);
    const ids = shown.map((x) => x.p.id).join(",") + (live ? "" : "|e") + (shown.length ? "" : `|b${before}`);
    const rs = shown.map((x) => { const r = rowOf(x); paintRow(r, x); r.row.classList.toggle("entry", !live); return r.row; });
    const hid = (list || []).filter((p) => p.hidden).length;
    if (ids !== order) {
      order = ids;
      put(listEl, rs.length ? rs : h("p", {class: "empty"}, hid ? `딥시크 ${fmt.int(hid)}개는 가격이 숨겨져 사다리에 없습니다 (개수만)`
        : before ? `설치 뒤에 들어간 열린 포지션이 없습니다 · 설치 전 진입 ${fmt.int(before)}개는 숨김 (설치 뒤 진입만)` : "열린 포지션이 없습니다"));
    }
    for (const id of [...rows.keys()]) if (!list.some((p) => p.id === id)) rows.delete(id);
    sub.textContent = (live ? "청산가·손절선까지 남은 거리 · 가까운 순" : `진입 때 거리 (${why}이라 지금 가격 기준은 감춤)`) + afterSuffix();
    more.textContent = (ranked.length > max ? `가까운 ${fmt.int(max)}개만 · 전체 ${fmt.int(ranked.length)}개 · ` : "") +
      (live ? "거리 = 지금 마크 가격에서 그 가격까지 (%) · 5초마다 서버 시세로 움직임." : "거리 = 진입가에서 그 가격까지 (%).") +
      (hid ? ` 딥시크 ${fmt.int(hid)}개는 가격이 숨겨져 빠짐 (개수만).` : "") + " 누르면 터미널에서 그 포지션.";
  };
  /** Before the first answer (or while the engine has written nothing): the words instead of a list. */
  const loading = (text) => { order = "\0wait"; put(listEl, h("p", {class: "empty"}, text)); more.textContent = ""; };
  return {el, set, loading};
}
