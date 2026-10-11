// 순위표 (RANK builder): the screen's own numbers and its top blocks, copied from the rule bot's v4 board
// (paperbot/dash/static/v4/screens/home-shared.js groupCards, board.js renderStats) and fitted to the 후보 리그:
//   the four 묶음 cards  후보 · 기존 36 / 후보 · 딥시크 / 비교 계좌 (1/4 · 청산만 · 기본값) / 동전 던지기, each with the
//                        median 잔고 수익률 (D-3: the wallet against the $5,000 start, closed trades only), the 참고
//                        comparisons on 한 번 평균 (the checkpoints' unit) and 파산 · 포지션
//   the four tiles       계좌 · 포지션 중 · 시작보다 많은 계좌 · 파산 of the chosen 묶음
// and the helpers the other rank-*.js files share (which accounts a 묶음 holds, hidden DeepSeek money, the ranking).
// DOM only through h() / put() (text nodes). HONESTY: DeepSeek money is shown only when the snapshot allows it
// (league.json ds_money, DS_MONEY_STRICT on the server); hidden accounts are counted, never priced, ranked or averaged.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as K4 from "../v4kit.js";
import * as LK from "../lk.js";
import {ROLE_KO, ROLE_SHORT, KIND_KO, tfKo} from "../labels.js";
import {openAfter, afterOn} from "../after.js";

export const EQUITY = 5000;
export const SMALL = 30;                         // 표본 적음 below the checkpoints' own floor (30 closed trades)
export const CMP_ROLES = ["quarter", "exitonly", "base"];
export const GROUPS = [
  {id: "core", ko: "후보 · 기존 36", short: "기존 36 후보", title: "기존 36 매매법의 후보 계좌 (커스텀값 + 커스텀 익절·손절)"},
  {id: "ds", ko: "후보 · 딥시크", short: "딥시크 후보", title: "딥시크 매매법의 후보 계좌 (커스텀값 + 커스텀 익절·손절)"},
  {id: "cmp", ko: "비교 계좌", short: "비교 계좌", title: "같은 후보에서 갈라진 1/4 크기 · 청산만 바꾼 기본값 · 기본값 계좌"},
  {id: "flip", ko: "동전 던지기", short: "동전", title: "후보와 같은 시각에 들어가되 방향만 동전으로 고른 계좌 (비교 기준, 판정 안 함)"},
];
export const GROUP_IDS = [...GROUPS.map((g) => g.id), "all"];
export const okGroup = (g) => (GROUP_IDS.includes(g) ? g : null);
export const okSub = (s) => (CMP_ROLES.includes(s) ? s : "all");
/** "기존 36 후보", "비교 계좌 · 1/4", "전체". */
export function groupKo(g, sub) {
  if (g === "all") return "전체";
  const x = GROUPS.find((y) => y.id === g);
  const base = x ? x.short : String(g);
  return g === "cmp" && sub && sub !== "all" ? `${base} · ${ROLE_SHORT[sub]}` : base;
}

// ---------------------------------------------------------------- money rules
/** True when this account's money is hidden (a DeepSeek account while the snapshot hides DeepSeek money): it is then
 *  counted only. Same rule as lk.js dsHidden, read from the given snapshot (and safe when the wallet is missing). */
export const hidden = (a, d) => !!a && a.kind === "ds" && (!(d && d.ds_money) || a.wallet == null);
/** 잔고 수익률 (a fraction): wallet / 5,000 - 1; null when hidden or unknown. */
export function walletRet(a, d) {
  if (!a || hidden(a, d) || a.wallet == null || !Number.isFinite(Number(a.wallet))) return null;
  return Number(a.wallet) / EQUITY - 1;
}
/** "+12.3%" of a 잔고 수익률 fraction. */
export const retPct = (r) => (r == null ? "—" : fmt.pct(r * 100, true, 1));
/** The pooled mean per trade (every closed trade counted once: the checkpoints' unit) of the shown accounts; null when
 *  none has a trade. */
export function pooled(accts, d) {
  let n = 0, s = 0;
  for (const a of accts) {
    if (hidden(a, d) || a.mean_ret == null || !a.trades) continue;
    n += a.trades;
    s += a.trades * a.mean_ret;
  }
  return n ? s / n : null;
}

// ---------------------------------------------------------------- which accounts a 묶음 holds
export function inGroup(a, g, sub = "all") {
  if (!a) return false;
  if (g === "all") return true;
  if (g === "core" || g === "ds") return a.role === "cand" && a.kind === g;
  if (g === "cmp") return CMP_ROLES.includes(a.role) && (!sub || sub === "all" || a.role === sub);
  if (g === "flip") return a.role === "flip";
  return false;
}
export const groupRows = (d, g, sub) => ((d && d.accounts) || []).filter((a) => inGroup(a, g, sub));

/**
 * ranking(d, rows) -> {shown, waiting, hid, rank}: shown = the ranked accounts by 잔고 수익률 (best first; ties by
 * 한 번 평균, then id), waiting = no closed trade and no open position yet (no rank: "첫 거래 뒤부터 순위"), hid = the
 * hidden DeepSeek accounts (counted only, never ranked), rank = Map(id -> rank).
 */
export function ranking(d, rows) {
  const shown = [], waiting = [], hid = [];
  for (const a of rows || []) {
    if (hidden(a, d)) hid.push(a);
    else if ((!a.trades && !a.open) || walletRet(a, d) == null) waiting.push(a);
    else shown.push(a);
  }
  shown.sort((x, y) => walletRet(y, d) - walletRet(x, d) || (y.mean_ret ?? -1e9) - (x.mean_ret ?? -1e9) || (x.id < y.id ? -1 : 1));
  const byName = (x, y) => `${LK.stratKo(x.name)} ${x.tf} ${x.id}`.localeCompare(`${LK.stratKo(y.name)} ${y.tf} ${y.id}`, "ko");
  waiting.sort(byName);
  hid.sort(byName);
  return {shown, waiting, hid, rank: new Map(shown.map((a, i) => [a.id, i + 1]))};
}

// ---------------------------------------------------------------- comparisons (참고, on 한 번 평균)
/** The pick's judge labels (counts and yes / no only; also for a hidden DeepSeek pick once it has 30 trades). */
const judgeOf = (d, id) => ((d && d.judge) || {})[id] || null;
/** cand vs its own 동전 (flip) / 기본값 (base) account on 한 번 평균: true / false / null. A hidden pick uses its judge
 *  label (30 trades or more), never a number. */
export function candVs(d, ix, c, role) {
  if (!c) return null;
  if (hidden(c, d)) {
    const j = judgeOf(d, c.id);
    const k = role === "flip" ? "beats_flip" : "beats_base";
    return j && j.verdict && j.verdict !== "early" && typeof j[k] === "boolean" ? j[k] : null;
  }
  const set = ix.sets[c.id] || {};
  const o = set[role];
  if (!o || hidden(o, d)) return null;
  return LK.better(c, o);
}
/** A comparison account vs its own 후보: 청산만 / 기본값 on 한 번 평균, 1/4 on 최대 낙폭 (it is a size check: its
 *  per-trade result is on another scale). true = better than the 후보. */
export function cmpVsCand(d, ix, a) {
  const pk = LK.pickOf(a, ix);
  if (!a || !pk || pk.id === a.id || hidden(a, d) || hidden(pk, d)) return null;
  if (a.role === "quarter") {
    return a.max_dd != null && pk.max_dd != null && a.trades && pk.trades ? a.max_dd < pk.max_dd : null;
  }
  return LK.better(a, pk);
}
/** An account vs its pick's 동전 account (lk.js vsFlip, 한 번 평균): null for a flip, a 1/4 (other scale) or hidden. */
export function rowVsFlip(d, ix, a) {
  if (!a || a.role === "flip" || a.role === "quarter") return null;
  if (hidden(a, d)) return a.role === "cand" ? candVs(d, ix, a, "flip") : null;
  const pk = LK.pickOf(a, ix);
  const flip = pk ? (ix.sets[pk.id] || {}).flip : null;
  if (!flip || hidden(flip, d)) return null;
  return LK.better(a, flip);
}
const tally = (xs) => ({up: xs.filter((v) => v === true).length, n: xs.filter((v) => v != null).length});

// ---------------------------------------------------------------- one card's numbers
/**
 * cardData(d, ix, id) -> {id, n, shown, hiddenN, med, bust, open, pool, ...} for one of the four 묶음 cards.
 * med: the median 잔고 수익률 (a fraction) of the shown accounts (null when all are hidden).
 */
export function cardData(d, ix, id) {
  const accts = groupRows(d, id);
  const shown = accts.filter((a) => !hidden(a, d));
  const out = {id, n: accts.length, shown: shown.length, hiddenN: accts.length - shown.length,
    med: K4.median(shown.map((a) => walletRet(a, d))), bust: accts.filter((a) => a.bust).length,
    open: accts.filter((a) => openAfter(a)).length, strategies: new Set(accts.map((a) => a.name)).size,
    pool: pooled(accts, d)};
  if (id === "core" || id === "ds") {
    out.vsFlip = tally(accts.map((c) => candVs(d, ix, c, "flip")));
    out.vsBase = tally(accts.map((c) => candVs(d, ix, c, "base")));
    const c2 = (((d && d.watch && d.watch.pools) || {})[id] || {}).c2 || null;
    out.poolFlip = c2 && typeof c2.beats_flip === "boolean" ? c2.beats_flip : null;
    out.poolBase = c2 && typeof c2.beats_base === "boolean" ? c2.beats_base : null;
  } else if (id === "cmp") {
    out.byRole = Object.fromEntries(CMP_ROLES.map((r) => {
      const xs = accts.filter((a) => a.role === r);
      return [r, {n: xs.length, vs: tally(xs.map((a) => cmpVsCand(d, ix, a))), pool: pooled(xs, d)}];
    }));
  }
  return out;
}

const glyph = (v, what) => (v == null ? null : h("span", {class: "k4-vs", title: `참고 · 묶음 한 번 평균이 ${what}보다 ${v ? "위" : "아래"} (점검과 같은 단위, 판정 아님)`},
  `${what} `, h("b", null, v ? "▲" : "▼")));
const retTxt = (x) => LK.retTxt(x, 2);

/**
 * rankCards({onPick}) -> a div (.k4-groups) with .update(d, ix, sel): the four 묶음 cards, built once and updated in
 * place (the median counts to its new value on real data only; focus stays). The chosen card is outlined.
 */
export function rankCards(o = {}) {
  const el = h("div", {class: "k4-groups rk-groups", role: "group", "aria-label": "묶음 고르기"});
  const made = new Map();
  for (const g of GROUPS) {
    const cnt = h("span", {class: "gc"});
    const med = K4.liveNum(null, {format: K4.pctFmt(1), tone: true, cls: "gm", flash: true});
    const hid = h("b", {class: "gm rk-hid", hidden: true, title: "딥시크 금액 숨김 설정: 개수와 라벨만 보입니다"});
    const medK = h("small", null, "중앙값");
    const vs = h("span", {class: "gs"}), vs2 = h("span", {class: "gs rk-gs2"}), foot = h("span", {class: "gb"}), pool = h("span", {class: "rk-pool"});
    const btn = h("button", {type: "button", class: "k4-gcard rk-gcard", "aria-pressed": "false", title: g.title,
      dataset: {kind: g.id === "flip" ? "flip" : g.id, group: g.id}, onclick: () => o.onPick && o.onPick(g.id)},
    h("span", {class: "gn"}, g.ko), cnt, h("span", {class: "gmw"}, med, hid, medK), vs, vs2, foot, pool);
    made.set(g.id, {btn, cnt, med, hid, medK, vs, vs2, foot, pool});
    el.append(btn);
  }
  el.update = (d, ix, sel) => {
    for (const g of GROUPS) {
      const c = made.get(g.id);
      const x = cardData(d, ix, g.id);
      const allHidden = x.n > 0 && x.shown === 0;
      c.med.hidden = allHidden;
      c.hid.hidden = !allHidden;
      c.hid.textContent = allHidden ? "숨김" : "";
      c.medK.textContent = allHidden ? "금액 숨김" : "중앙값";
      if (!allHidden) c.med.update(x.med == null ? null : x.med * 100);
      const hidNote = x.hiddenN && !allHidden ? ` · 딥시크 ${fmt.int(x.hiddenN)}개 숨김 (중앙값에서 뺌)` : "";
      if (g.id === "core" || g.id === "ds") {
        c.cnt.textContent = `${fmt.int(x.n)}계좌 · 매매법 ${fmt.int(x.strategies)}개 · ${allHidden ? "금액 숨김 (개수·라벨만)" : "잔고 수익률"}${hidNote}`;
        const ref = K4.pill("", "ref", "같은 후보의 동전 계좌와 거래 한 번 평균 비교: 참고 (판정 아님)");
        if (allHidden && !x.vsFlip.n) {
          put(c.vs, "후보마다 비교: 30번 넘으면 라벨로 ", ref);
          c.vs2.textContent = "금액 숨김 설정 · 개수와 라벨만";
        } else {
          const lab = allHidden ? " (라벨)" : "";
          put(c.vs, `동전보다 위 ${fmt.int(x.vsFlip.up)}/${fmt.int(x.vsFlip.n)}${lab} `, ref);
          c.vs2.textContent = `기본값보다 위 ${fmt.int(x.vsBase.up)}/${fmt.int(x.vsBase.n)}${lab}`;
        }
        put(c.pool, h("span", null, `묶음 한 번 평균 ${allHidden ? "숨김" : retTxt(x.pool)}`), glyph(x.poolFlip, "동전"), glyph(x.poolBase, "기본값"));
        c.pool.title = "이 묶음 후보 계좌들의 모든 거래를 모은 한 번 평균 (점검과 같은 계산) · ▲▼ = 같은 묶음의 동전·기본값 계좌보다 위·아래";
      } else if (g.id === "cmp") {
        const r = x.byRole;
        c.cnt.textContent = `${fmt.int(x.n)}계좌 · 1/4 ${fmt.int(r.quarter.n)} · 청산만 ${fmt.int(r.exitonly.n)} · 기본값 ${fmt.int(r.base.n)}${hidNote}`;
        c.vs.textContent = `후보보다 나음 · 청산만 ${fmt.int(r.exitonly.vs.up)}/${fmt.int(r.exitonly.vs.n)} · 기본값 ${fmt.int(r.base.vs.up)}/${fmt.int(r.base.vs.n)}`;
        c.vs2.textContent = `1/4가 후보보다 덜 흔들림 ${fmt.int(r.quarter.vs.up)}/${fmt.int(r.quarter.vs.n)}`;
        put(c.pool, `한 번 평균 · 1/4 ${retTxt(r.quarter.pool)} · 청산만 ${retTxt(r.exitonly.pool)} · 기본값 ${retTxt(r.base.pool)}`);
        c.pool.title = "역할마다 모든 거래를 모은 한 번 평균 (점검과 같은 계산; 숨긴 딥시크 계좌는 뺌)";
      } else {
        c.cnt.textContent = `${fmt.int(x.n)}계좌 · 후보마다 1개 (방향만 동전)${hidNote}`;
        c.vs.textContent = "비교 기준 (판정 안 함)";
        c.vs2.textContent = "";
        put(c.pool, `묶음 한 번 평균 ${retTxt(x.pool)}`);
        c.pool.title = "동전 계좌들의 모든 거래를 모은 한 번 평균 (숨긴 딥시크 계좌는 뺌)";
      }
      c.vs2.hidden = !c.vs2.textContent;
      c.foot.textContent = `파산 ${fmt.int(x.bust)} · 포지션 ${fmt.int(x.open)}${afterOn() ? " (설치\u00a0뒤만)" : ""}`;
      c.btn.setAttribute("aria-pressed", String(g.id === sel));
    }
  };
  return el;
}

// ---------------------------------------------------------------- the four tiles
/** rankTiles() -> div.stats.s4 with .update(d, rows, label): 계좌 · 포지션 중 · 시작보다 많은 계좌 · 파산. A count that
 *  really changed counts to its new value with a soft tint (never on a 묶음 switch). */
export function rankTiles() {
  const cnt = [0, 1, 2, 3].map(() => K4.liveNum(null, {format: (v) => fmt.int(v), flash: "accent"}));
  const sub = [h("span", {class: "s"}), h("span", {class: "s"}, "지금 열린 포지션 (엔진 기준)"), h("span", {class: "s"}),
    h("span", {class: "s"}, "잔고 10 USDT 미만, 정지")];
  const el = h("div", {class: "stats s4 rk-stats"}, K4.stat("계좌", cnt[0], sub[0]), K4.stat("포지션 중", cnt[1], sub[1]),
    K4.stat("시작보다 많은 계좌", cnt[2], sub[2]), K4.stat("파산", cnt[3], sub[3]));
  let key = null;
  el.update = (d, rows, label) => {
    if (key !== label) { for (const c of cnt) delete c.dataset.v; key = label; }
    const hid = rows.filter((a) => hidden(a, d)).length;
    cnt[0].update(rows.length);
    cnt[1].update(rows.filter((a) => openAfter(a)).length);
    sub[1].textContent = afterOn() ? "설치 뒤만 · 지금 열린 포지션 (엔진 기준)" : "지금 열린 포지션 (엔진 기준)";
    cnt[2].update(rows.filter((a) => !hidden(a, d) && a.wallet != null && Number(a.wallet) > EQUITY).length);
    cnt[3].update(rows.filter((a) => a.bust).length);
    sub[0].textContent = hid ? `${label} · 딥시크 ${fmt.int(hid)}개 금액 숨김` : label;
    sub[2].textContent = hid ? `잔고 ${fmt.int(EQUITY)} 넘음 (숨긴 ${fmt.int(hid)}개 빼고)` : `잔고 ${fmt.int(EQUITY)} 넘음`;
  };
  return el;
}

// ---------------------------------------------------------------- small shared pieces
/** The account's name for a row: pixel character, timeframe chip, Korean strategy name (+ "2순위"), and the role chip
 *  when the list mixes roles. */
export function nameBits(a, o = {}) {
  return [LK.fig(a, o.size || 20),
    h("span", {class: "an"}, h("span", {class: "an-tf"}, tfKo(a.tf)), h("span", {class: "an-n"}, LK.stratKo(a.name))),
    a.source && a.source.rank > 1 ? h("small", {class: "rk-r2"}, `${a.source.rank}순위`) : null,
    o.role && a.role !== "cand" ? LK.roleChip(a.role, ROLE_SHORT[a.role]) : null];
}
export const kindKo = (k) => KIND_KO[k] || String(k || "");
export const roleKo = (r) => ROLE_KO[r] || String(r || "");
