// 익절·손절·배수 kit (owners 2026-10-12: "커스텀봇 각 매매법마다 익절구조 손절구조를 어떻게 잡았는지 ... 레버리지는 어떻게
// 적용되는거고"): an exit and the leverage rule in plain Korean, what the five accounts of a pick do differently, a pick's
// rule card (익절 · 손절 · 본전 승률 · 배수 · 지금 이 숫자면 · 실제로 쓴 배수 · 계좌 5개) and its compact box for 커스텀값 and
// 계좌 자세히. Data: /api/rules (dash.py rules_doc: the engine's own rule numbers from paperbot, the live ATRs). The words
// follow the rule bot's v4 (positions-kit ruleLine / whyBox, 용어 사전). Every string reaches the page as a text node.
import {h} from "./dom.js";
import * as fmt from "./fmt.js";
import * as ui from "./ui.js";
import * as LK from "./lk.js";
import {ROLES, ROLE_KO, ROLE_SHORT, ROLE_INFO, tfKo, lineupOn} from "./labels.js";

export const LEVS = [50, 40, 30, 20];
export const COINS6 = ["BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD"];
const TF_BAR = {"15m": "15분봉", "30m": "30분봉", "1h": "1시간봉", "4h": "4시간봉"};
const LADDER_GAP = 0.02, LADDER_STEP = 0.05;                     // config ladder_trigger_gap / ladder_step
/** A share as a percent ("0.53%"); "—" without a number. */
export const share = (x, dec = 1) => (x == null || !Number.isFinite(Number(x)) ? "—" : fmt.pct(Number(x) * 100, false, dec));
const num1 = (x) => { const v = Math.round(Number(x) * 1000) / 1000; return fmt.num(v, v % 1 ? 1 : 0); };
const coinKo = (c) => String(c || "").replace(/USDT?$/, "");
/** Coins in the league's order (BTC, ETH, SOL, DOGE, LTC, BCH). */
const byCoin = (xs) => [...xs].sort((a, b) => COINS6.indexOf(a) - COINS6.indexOf(b));
/** A link to a term of 읽는 법's 용어 사전 (#/howto?q=ATR). */
export const term = (word, label) => h("a", {class: "rl-term", href: `#/howto?q=${encodeURIComponent(word)}`, title: `${word}: 읽는 법 › 용어 사전`}, label || word);

/** The start wallet the rules doc was made for (its equity0: 5000, or 1000 in the owners' league), else the snapshot's. */
const eq0 = (r) => (r && Number(r.equity0) > 0 ? Number(r.equity0) : LK.EQUITY);

// ---------------------------------------------------------------- /api/rules, one copy per page
let RULES = null, RULES_KEY = null, rulesP = null;
/** The rules doc (cached for the snapshot it was made for); onDoc(doc) once it is here and once more when the live
 *  ATRs arrive (the server reads them in the background the first time: ?wait=1 waits for them). */
export async function loadRules(ctx, onDoc) {
  const d = LK.league();
  const key = d ? `${d.generated_ms}` : "";
  if (RULES && RULES_KEY === key && !RULES.atr_loading) { onDoc(RULES); return RULES; }
  if (!rulesP) rulesP = ctx.api("/api/rules").finally(() => { rulesP = null; });
  let doc = await rulesP;
  RULES = doc; RULES_KEY = key; if (!(d && d.equity0 > 0)) LK.setEquity(doc && doc.equity0);   // the snapshot's own equity0 wins
  if (ctx.alive()) onDoc(doc);
  if (doc && doc.atr_loading && ctx.alive()) {
    try { doc = await ctx.api("/api/rules?wait=1"); } catch (e) { return RULES; }
    RULES = doc; if (!(d && d.equity0 > 0)) LK.setEquity(doc && doc.equity0);
    if (ctx.alive()) onDoc(doc);
  }
  return RULES;
}
export const rulesNow = () => RULES;

// ---------------------------------------------------------------- the words
/** "고정 익절 3R" / "고정 익절 수익 50%" / "계단 잠금 10%부터" (short). */
export function tpShort(tp) {
  if (!tp) return "—";
  if (tp.kind === "R") return `고정 익절 ${num1(tp.val)}R`;
  if (tp.kind === "roe") return `고정 익절 증거금 대비 +${num1(tp.val * 100)}%`;
  if (tp.kind === "ladder_R") return `계단 잠금 + 익절 ${num1(tp.val)}R`;
  if (tp.kind === "struct") return `구조 익절(${num1(tp.val)}봉 스윙) + 계단 잠금`;
  return `계단 잠금 ${num1((tp.first_lock || 0.1) * 100)}%부터`;
}
/** The take-profit in a few words (the list's 익절 cell, the short answer's counts): "3R" / "증거금 대비 +50%" /
 *  "계단 잠금 10%부터"; o.long adds "(손절 거리의 3배)" to an R take-profit. */
export function tpTiny(tp, o = {}) {
  if (!tp) return "—";
  if (tp.kind === "R") return o.long ? `${num1(tp.val)}R (손절 거리의 ${num1(tp.val)}배)` : `${num1(tp.val)}R`;
  if (tp.kind === "roe") return `증거금 대비 +${num1(tp.val * 100)}%`;
  return tpShort(tp);
}
/** The exit moves after the entry (a lock exit), or never (a fixed take-profit). */
export const stopMoves = (tp) => !!tp && tp.kind !== "R" && tp.kind !== "roe";
/** The take-profit in plain words (round_trip: the fees and slippage of a round trip, a share of the position). */
export function tpWords(tp, o = {}) {
  if (!tp) return "—";
  const rt = (o && o.round_trip) ?? 0.0014;
  const lock = (first) => `증거금 대비 순수익(수수료 뺀 ROE)이 +${num1((first + LADDER_GAP) * 100)}%가 되면 손절선을 +${num1(first * 100)}% 자리로 올려 수익을 잠그고, 그 뒤로 ${num1(LADDER_STEP * 100)}%씩 따라 올립니다 (계단 잠금). 잠금선에 닿으면 수익으로 끝납니다.`;
  if (tp.kind === "R") {
    return `진입가에서 손절선까지의 거리를 1R이라 부릅니다. 가격이 유리한 쪽으로 ${num1(tp.val)}R(손절 거리의 ${num1(tp.val)}배) 가면, 들어갈 때 미리 걸어 둔 지정가 주문으로 익절합니다. 예: 손절이 1% 아래면 익절은 ${num1(tp.val)}% 위 (숏은 반대).`;
  }
  if (tp.kind === "roe") {
    const at = (lev) => share(tp.val / lev + rt, 1);
    return `증거금 대비 순수익(수수료 뺀 ROE)이 +${num1(tp.val * 100)}%가 되는 가격에 지정가로 익절합니다. 배수가 낮을수록 그 가격이 멀어집니다: ${LK.levLadder().lowTwo.map((v) => `${v}배면 약 ${at(v)}`).join(", ")} 움직여야 합니다.`;
  }
  if (tp.kind === "ladder_R") return `손절 거리의 ${num1(tp.val)}배(${num1(tp.val)}R)에 지정가 익절을 걸어 두고, 그 전에는 ${lock(tp.first_lock || 0.1)}`;
  if (tp.kind === "struct") return `직전 ${num1(tp.val)}봉 스윙 자리에 지정가 익절을 걸고, ${lock(tp.first_lock || 0.1)}`;
  return `정해 둔 익절 가격이 없습니다. ${lock(tp.first_lock || 0.1)}`;
}
/** The stop in plain words. */
export function stopWords(k, tf, tp) {
  const moves = stopMoves(tp);
  return [`들어간 봉 기준 `, term("ATR"), `(${TF_BAR[tf] || tfKo(tf)} 최근 14개의 평균 움직임 폭) × ${num1(k)}만큼 반대쪽에 손절 주문을 둡니다. `,
    moves ? "수익이 나면 계단 잠금으로 손절선이 올라갑니다." : "들어간 뒤에는 손절선이 움직이지 않습니다 (잠금 없음)."];
}
/** "4번 중 1번" for a break-even of 1 / (1 + m) with a whole 1 + m. */
const oneIn = (be) => { const k = 1 / be; return Math.abs(k - Math.round(k)) < 1e-9 && k >= 2 ? `${Math.round(k)}번 중 1번` : null; };
/** The break-even line of a pick: before costs (a fixed take-profit at m R), and with costs over today's coins. */
export function beWords(p) {
  if (!p || !p.tp) return null;
  const now = Object.values(p.now || {}).map((x) => x.be_cost).filter((x) => x != null);
  const lo = now.length ? Math.min(...now) : null, hi = now.length ? Math.max(...now) : null;
  const cost = lo == null ? null : lo === hi || share(lo, 0) === share(hi, 0) ? share(lo, 0) : `${share(lo, 0)}~${share(hi, 0)}`;
  if (p.tp.kind === "R" && p.breakeven) {
    const k = oneIn(p.breakeven);
    return [h("b", null, share(p.breakeven, 0)), ` (비용 전) · ${num1(p.tp.val)}R이면 이길 때 ${num1(p.tp.val)}만큼 벌고 질 때 1만큼 잃으니 ${k || share(p.breakeven, 0)}만 이겨도 본전입니다.`,
      cost ? [" 수수료·슬리피지(손절로 끝나면 0.14%, 지정가 익절로 끝나면 0.09%)를 넣으면 지금 손절 거리로 ", h("b", null, cost),
        " (손절이 좁은 코인일수록 비용 몫이 커서 높음)."] : null];
  }
  if (p.tp.kind === "roe") {
    return cost ? [h("b", null, cost), " (비용 포함, 지금 손절 거리와 보통 자리 배수 기준) · 익절 폭이 배수에 따라 달라 미리 한 숫자로 정해지지 않습니다."]
      : "익절 폭이 배수에 따라 달라 한 숫자로 정해지지 않습니다.";
  }
  return "계단 잠금은 이길 때 버는 폭이 정해져 있지 않아 본전 승률을 미리 셀 수 없습니다.";
}
/** Which leverage steps a pick's accounts try, in words. */
export function levWords(p) {
  if (!p) return "—";
  const L = LK.levLadder();
  if (L.on) {                                    // the floor league (min_lev): its own ladder, and the rule that a signal with no fitting step is not entered
    const how = L.normal.length > 1 ? `${L.normalArrow} 순서로 시도해 거래소 한도 안이고 두 가지 안전 검사를 모두 통과한 첫 배수로 들어갑니다`
      : `${L.normal[0]}배만 시도해 거래소 한도 안이고 두 가지 안전 검사를 모두 통과하면 들어가고, 아니면 들어가지 않습니다`;
    const end = ` 이 리그는 ${L.low}배보다 낮게는 내려가지 않아, 손절이 넓어 ${L.low}배도 안 맞는 신호는 진입하지 않습니다.`;
    if (p.best_ok) return [term("좋은 자리"), ` (진입 강도 점수가 높은 자리: 5년 신호의 약 ${share(p.p_best, 0)})면 ${L.bestArrow}, 아니면 `, term("보통 자리"), `라서 ${how}.${end}`];
    return [p.kind === "ds" ? "딥시크 매매법은 진입 강도 점수가 없어서 " : `이 칸(${tfKo(p.tf)})은 진입 강도 기준이 없어서 `, "늘 ", term("보통 자리"), `: ${how}.${end}`];
  }
  if (p.best_ok) {
    return [term("좋은 자리"), ` (진입 강도 점수가 높은 자리: 5년 신호의 약 ${share(p.p_best, 0)})면 50배 → 40배 → 30배 → 20배, 아니면 `, term("보통 자리"),
      "라서 30배 → 20배 순서로 시도해, 거래소 한도 안이고 두 가지 안전 검사를 모두 통과한 첫 배수로 들어갑니다."];
  }
  return [p.kind === "ds" ? "딥시크 매매법은 진입 강도 점수가 없어서 " : `이 칸(${tfKo(p.tf)})은 진입 강도 기준이 없어서 `, "늘 ", term("보통 자리"),
    ": 30배 → 20배 순서로 시도해 거래소 한도 안이고 두 가지 안전 검사를 모두 통과한 첫 배수로 들어갑니다."];
}
/** "30배 3 · 20배 9" of the leverages an account used ({lev: count}); null when hidden, "아직 없음" without one. */
export function usedChips(u, o = {}) {
  if (u == null) return h("span", {class: ["rl-used", "muted"], title: "딥시크 금액 숨김 설정: 배수도 보내지 않습니다"}, "숨김");
  const ks = LEVS.filter((l) => u[String(l)]);
  if (!ks.length) return h("span", {class: ["rl-used", "muted"]}, o.none || "아직 없음");
  return h("span", {class: "rl-used"}, ks.map((l) => h("span", {class: ["rl-lev", `l${l}`]}, `${l}배 `, h("b", {class: "num"}, `${fmt.int(u[String(l)])}번`))));
}
/** "40 / 30배": the leverage a long entered now gets as a 좋은 자리 / as a 보통 자리 (0: no step passes, no entry). */
export function levPair(x, bestOk) {
  if (!x) return "—";
  const one = (v) => (v == null ? "—" : v === 0 ? "못 들어감" : `${v}배`);
  if (!bestOk) return one(x.normal);
  return x.best === x.normal ? `둘 다 ${one(x.normal)}` : `${one(x.best)} / ${one(x.normal)}`;
}

// ---------------------------------------------------------------- the five accounts, what each changes
export const ROLE_RULE = {
  cand: {nums: "커스텀값", exit: "후보 것", size: "규칙봇과 같음 (증거금 = 배수%)", dir: "신호대로", why: "커스텀값 + 커스텀 익절·손절이 정말 나은가"},
  quarter: {nums: "커스텀값", exit: "후보 것", get size() { return `증거금만 1/4 (${LK.levLadder().quarterText})`; }, dir: "신호대로",
    why: "크기를 줄이면 덜 흔들리나 · 손실 검사가 4배 느슨하고 거래소 한도에도 덜 걸려서 후보보다 높은 배수가 나오기도 함"},
  exitonly: {nums: "기본값 (규칙봇 숫자)", exit: "후보 것", size: "규칙봇과 같음", dir: "신호대로", why: "좋아진 게 숫자 덕인가 익절·손절 덕인가"},
  base: {nums: "기본값 (규칙봇 숫자)", exit: "지금 규칙봇 것: 계단 잠금 10%부터 · 손절 2 ATR", size: "규칙봇과 같음", dir: "신호대로", why: "규칙봇과 같은 조건 (그 칸에 하나)"},
  flip: {nums: "후보와 같은 시각 (숫자로 고르지 않음)", exit: "후보 것", size: "규칙봇과 같음", dir: "동전 던지기 (좋은 자리 여부도 동전 방향으로 다시 봄)",
    why: "방향을 맞힌 건가 운인가"},
};
const NO_RULE = {nums: "—", exit: "—", size: "—", dir: "—", why: "—"};
/** What an account kind changes: the owner-exit league's own words (labels ROLE_INFO from the snapshot's lineup) while it
 *  runs, else the candidate league's table above. */
export const roleRule = (r) => (lineupOn() && ROLE_INFO[r]) || ROLE_RULE[r] || NO_RULE;
/** The five accounts side by side: numbers, exit, size, direction, what it is for (rows on a phone, a table on a PC). */
export function rolesTable() {
  const cols = [["nums", "진입"], ["exit", "익절·손절"], ["size", "크기 · 배수"], ["dir", "방향"], ["why", "보려는 것"]];
  return h("div", {class: "rl-roles", role: "table", "aria-label": lineupOn() ? "계좌 종류가 다른 점" : "계좌 5개가 다른 점"},
    h("div", {class: "rl-rrow rl-rhd", role: "row"}, h("span", {role: "columnheader"}, "계좌"), cols.map(([, k]) => h("span", {role: "columnheader"}, k))),
    ROLES.map((r) => h("div", {class: ["rl-rrow", `r-${r}`], role: "row"}, h("span", {class: "rl-rname", role: "rowheader"}, LK.roleChip(r)),
      cols.map(([key, k]) => h("span", {role: "cell", dataset: {k}}, roleRule(r)[key])))),
    h("p", {class: "note"}, lineupOn()
      ? `${LK.OWNER_SAME_SIGNALS} ${LK.OWNER_SAME_RULE} ${LK.OWNER_STOP_DIFF}`
      : "배수 규칙은 다섯 계좌 모두 같습니다 (아래). 같은 규칙이라도 손절 폭과 증거금이 다르면 고르는 배수가 달라집니다."));
}

// ---------------------------------------------------------------- the leverage rule (one card)
/** The coins the exchange's limit takes out of a step, in words: [{lev, coins, cap}] for the 후보 (key "") or the
 *  1/4 (key "q_") size. */
export function blockedSteps(r, key = "") {
  return ((r && r.steps) || []).map((s) => ({lev: s.lev, coins: byCoin(s[`${key}blocked`] || []), cap: s[`${key}cap`] || {}}))
    .filter((x) => x.coins.length);
}
/** "50배 LTC · BCH (거래소가 40배까지)" for the blocked steps of one size; null when none. */
export function blockedWords(r, key = "") {
  const b = blockedSteps(r, key);
  if (!b.length) return null;
  return b.map((x) => {
    const caps = [...new Set(x.coins.map((c) => x.cap[c]))];
    return `${x.lev}배 ${x.coins.map(coinKo).join(" · ")} (거래소가 ${caps.map((v) => `${v}배`).join(" · ")}까지)`;
  }).join(", ");
}
/** One size's liquidation distances of a step: "BTC 1.6% (코인 0.8~1.6%) · LTC·BCH 거래소 한도로 불가". */
function liqCell(liq, blocked) {
  const v = Object.values(liq || {}).filter((x) => x != null);
  const range = v.length ? `${share(Math.min(...v), 1)}~${share(Math.max(...v), 1)}` : null;
  const btc = liq && liq.BTCUSD != null ? `BTC ${share(liq.BTCUSD, 1)}` : null;
  const head = btc ? `${btc}${range ? ` (코인 ${range})` : ""}` : range || "—";
  return blocked && blocked.length ? [head, " · ", h("b", {class: "rl-block"}, `${byCoin(blocked).map(coinKo).join("·")} 거래소 한도로 불가`)] : head;
}
/** The steps the engine tries, the exchange's limit and the two safety checks with their numbers, and the leverages
 *  the league actually used. */
export function levRuleBody(r) {
  if (!r || !r.steps) return ui.none("준비 중");
  const c = r.costs || {};
  const owner = lineupOn();                   // the owner-exit league has no 1/4 or 기본값 account: its text names neither
  const rows = r.steps.map((s) => h("div", {class: ["rl-step", `l${s.lev}`], role: "row"},
    h("b", {class: "rl-steplev", role: "cell"}, `${s.lev}배`),
    h("span", {role: "cell", dataset: {k: "누가"}}, s.group === "best" ? "좋은 자리만" : "좋은 자리 · 보통 자리"),
    h("span", {role: "cell", class: "num", dataset: {k: "증거금"}}, owner ? share(s.margin, 0) : `${share(s.margin, 0)} · 1/4은 ${share(s.q_margin, 1)}`),
    h("span", {role: "cell", class: "num", dataset: {k: "손절 거리 한도"}}, owner ? share(s.max_stop, 2) : `${share(s.max_stop, 2)} · 1/4은 ${share(s.q_max_stop, 1)}`),
    h("span", {role: "cell", class: "num rl-liqc", dataset: {k: "진입 때 청산까지"}},
      h("span", null, owner ? null : h("small", {class: "muted"}, "후보 "), liqCell(s.liq, s.blocked)),
      !owner && s.q_liq ? h("span", null, h("small", {class: "muted"}, "1/4 "), liqCell(s.q_liq, s.q_blocked)) : null)));
  const used = r.used_all || {};
  const picks = Object.values(r.picks || {});
  const npick = picks.length, wide = picks.filter((p) => p.stop_atr >= 3).length;
  const blk = blockedWords(r, ""), qblk = blockedWords(r, "q_");
  const top = r.steps[0] || {};
  const L = LK.levLadder(), lowStep = r.steps.find((x) => x.lev === L.low) || {};
  const many = L.on ? `${L.low}배로 내려가거나 들어가지 못하는 신호가 많고, ` : "20~30배가 많고, ";
  return h("div", {class: "stack tight rl-levrule"},
    h("p", null, "배수(레버리지)는 신호가 올 때마다 엔진이 정합니다. 아래 순서대로 시도해서 ", h("b", null, "거래소 한도 안이고 두 가지 안전 검사를 모두 통과한 첫 배수"),
      "로 들어갑니다. 하나도 통과하지 못하면 그 신호는 ", h("b", null, "들어가지 않고 건너뜁니다"), "."),
    h("div", {class: "rl-steps", role: "table", "aria-label": "배수 단계"},
      h("div", {class: "rl-step rl-stephd", role: "row"}, ["배수", "누가 시도", "증거금 (잔고 중)", "손절 거리 한도 (손실 검사)", owner ? "진입 때 청산까지" : "진입 때 청산까지 (후보 · 1/4 크기)"]
        .map((t) => h("span", {role: "columnheader"}, t))),
      rows),
    h("ol", {class: "rl-checks"},
      h("li", null, h("b", null, term("거래소 한도")), ` · 거래소(바이낸스)는 주문이 클수록 허용 배수를 낮춥니다. 잔고 ${LK.usd0(eq0(r))}이면 50배 주문은 $${fmt.int(top.notional || eq0(r) * 25)}어치${owner ? "" : `(1/4 계좌는 $${fmt.int(top.q_notional || eq0(r) * 6.25)})`}. `,
        blk ? `${owner ? "이 크기" : "후보 크기"}에서는 ${blk}라서 그 코인은 다음 배수로 내려갑니다. ` : `지금 표로는 ${owner ? "이 크기" : "후보 크기"}에서 막히는 코인이 없습니다. `,
        owner ? "" : qblk ? `1/4 크기에서는 ${qblk}.` : blk ? "1/4 계좌는 주문이 작아 이 한도에 걸리지 않습니다." : ""),
      h("li", null, h("b", null, term("청산 검사")), ` · 손절선이 `, term("청산가"), `보다 안쪽에 있고, 그 사이가 1 ATR 이상(최소 진입가의 ${share(c.buffer_min, 1)})이어야 합니다. 배수가 높을수록 청산가가 가까워집니다 (위의 ‘진입 때 청산까지’${owner ? "" : ": 주문 크기에 따라 거래소 유지 증거금이 달라 후보와 1/4이 조금 다름"}).`),
      h("li", null, h("b", null, term("손실 검사")), ` · 손절에 닿았을 때 잃는 돈(수수료·슬리피지 포함)이 잔고의 ${share(c.max_loss, 0)} 이하여야 합니다. 그래서 배수마다 쓸 수 있는 `, term("손절 거리 한도"), "가 있습니다 (위의 ‘손절 거리 한도’).")),
    h("p", null, "그래서 ", h("b", null, "손절이 넓을수록 배수가 내려갑니다"), `. 예를 들어 손절이 1%면 좋은 자리라도 50배(한도 ${share((r.steps[0] || {}).max_stop, 2)})와 40배(한도 ${share((r.steps[1] || {}).max_stop, 2)})는 손실 검사에 걸려 30배로 들어갑니다. `,
      L.on ? `이 리그는 ${L.low}배보다 낮게는 내려가지 않아, 손절이 ${L.low}배 한도(${share(lowStep.max_stop, 2)})보다 넓은 신호는 들어가지 않습니다. ` : "",
      owner ? (wide ? `후보 ${fmt.int(npick)}개 중 ${fmt.int(wide)}개는 손절이 3~4 ATR로 넓어서 ‘${ROLE_KO.cand}’ 계좌는 ${many}손절을 최대 2 ATR로 좁힌 계좌(대조 · 메인)는 같은 자리에서 40·50배가 더 자주 나옵니다.`
        : "손절을 최대 2 ATR로 좁힌 계좌(대조 · 메인)는 손절이 더 넓은 계좌보다 같은 자리에서 40·50배가 더 자주 나옵니다.")
        : [wide ? `후보 ${fmt.int(npick)}개 중 ${fmt.int(wide)}개는 손절이 3~4 ATR로 넓어서 ${many}` : "", "손절 2 ATR인 기본값 계좌는, 손절이 2 ATR보다 넓은 후보와 비교하면 40·50배가 더 자주 나옵니다."]),
    h("p", null, term("증거금"), " = 그 거래에 거는 돈 (잔고 × 비율). ", term("포지션 크기"), ` = 증거금 × 배수. 예: 잔고 ${LK.usd0(eq0(r))}에서 30배면 증거금 ${LK.usd0(eq0(r) * 0.3)}, 포지션 ${LK.usd0(eq0(r) * 9)}. `,
      owner ? "" : "1/4 계좌는 증거금만 1/4이라 손실 검사가 4배 느슨하고 거래소 한도에도 덜 걸려서, 후보보다 높은 배수로 들어가기도 합니다."),
    h("div", {class: "rl-usedall"}, h("span", {class: "muted"}, "지금까지 실제로 쓴 배수 (닫힌 거래 · 계좌마다 최근 200번까지)"),
      ROLES.map((role) => h("div", {class: "rl-urow"}, LK.roleChip(role), usedChips(used[role] || {}, {none: "아직 닫힌 거래 없음"}))),
      r.hidden_accounts ? h("p", {class: "note"}, `딥시크 계좌 ${fmt.int(r.hidden_accounts)}개는 금액 숨김 설정이라 빠졌습니다.`) : null));
}

// ---------------------------------------------------------------- a pick
/** One coin's tile of "지금 이 숫자면": ATR, stop and take-profit distances, the break-even with costs, the leverage
 *  each account would get (좋은 자리 / 보통 자리). */
function coinTile(coin, x, p) {
  const ln = x.lev && x.lev.cand ? x.lev.cand.normal : null;
  return h("div", {class: "rl-coin"},
    h("div", {class: "rl-coinh"}, h("b", null, coinKo(coin)), h("span", {class: "muted num"}, `ATR ${share(x.atr_pct, 2)}`)),
    h("dl", {class: "rl-cdl"},
      h("div", null, h("dt", null, "손절 거리"), h("dd", {class: "num"}, share(x.stop_pct, 2))),
      h("div", null, h("dt", null, p.tp && p.tp.kind === "roe" ? (ln ? `익절 거리 (${ln}배면)` : "익절 거리") : "익절 거리"), h("dd", {class: "num"}, share(x.tp_pct, 2))),
      x.be_cost != null ? h("div", null, h("dt", null, "본전 (비용 포함)"), h("dd", {class: "num"}, share(x.be_cost, 0))) : null,
      h("div", {class: "rl-cdh"}, h("dt", null, "배수"), h("dd", null, p.best_ok ? "좋은 / 보통" : "보통 자리")),
      lineupOn() ? [          // the owner-exit league: the pick's own stop (지금 청산), and what the same rule gives with a 2 ATR stop (메인 · 대조 cap it there)
        h("div", null, h("dt", null, ROLE_KO.cand), h("dd", {class: "num"}, levPair(x.lev.cand, p.best_ok))),
        h("div", null, h("dt", null, "손절 2 ATR이면"), h("dd", {class: "num", title: `손절 2 ATR = ${share(x.base_stop_pct, 2)}: 대조 · 메인은 손절이 최대 2 ATR`}, levPair(x.lev.base, p.best_ok)))]
        : [h("div", null, h("dt", null, "후보"), h("dd", {class: "num"}, levPair(x.lev.cand, p.best_ok))),
          h("div", null, h("dt", null, "1/4"), h("dd", {class: "num"}, levPair(x.lev.quarter, p.best_ok))),
          h("div", null, h("dt", null, "기본값"), h("dd", {class: "num", title: `기본값 계좌의 손절 2 ATR = ${share(x.base_stop_pct, 2)}`}, levPair(x.lev.base, p.best_ok)))]));
}
/** "지금 이 숫자면": the six coins today (or why there is nothing). */
export function nowBox(p, r) {
  const now = p && p.now;
  if (!now || !Object.keys(now).length) {
    return h("p", {class: "muted"}, r && r.atr_loading ? "지금 시세로 계산하는 중 (몇 초)…" : "시세를 받지 못해 지금 숫자는 없습니다 (규칙은 위와 같음).");
  }
  return h("div", {class: "stack tight"},
    h("p", {class: "note"}, `${TF_BAR[p.tf] || tfKo(p.tf)} 마지막 닫힌 봉 기준 (${fmt.kst(r && r.atr_ms)} KST) · 지금 롱으로 들어간다면 · 잔고 ${LK.usd0(eq0(r))} · `,
      p.best_ok ? "배수는 ‘좋은 자리 / 보통 자리’ (같으면 ‘둘 다’)" : "늘 보통 자리", " · ‘못 들어감’ = 어느 배수도 거래소 한도·안전 검사를 통과 못 해서 그 신호는 건너뜀 · ",
      "본전 = 수수료·슬리피지를 넣고 이 손절·익절 거리로 본전이 되는 승률"),
    h("div", {class: "rl-coins"}, COINS6.filter((c) => now[c]).map((c) => coinTile(c, now[c], p))));
}
/** The 기본값 account's stop against the pick's, in words (the leverage follows the stop width alone). */
export function baseNote(p, r) {
  const base = (p && p.roles || {}).base;
  if (!base || !base.exit || base.exit === p.exit) return null;
  const bk = (r && r.base_tp && r.base_tp.stop_atr) || 2;
  const name = base.exit_ko || (r && r.base_exit_ko) || "계단 잠금 10%부터 · 손절 2 ATR";
  const lead = `기본값 계좌는 규칙봇의 지금 청산(${name})을 씁니다. `;
  if (p.stop_atr > bk) return `${lead}손절이 ${num1(bk)} ATR로 이 후보(${num1(p.stop_atr)} ATR)보다 좁아서, 같은 자리라면 배수가 더 높게 나오기 쉽습니다.`;
  if (p.stop_atr < bk) return `${lead}손절이 ${num1(bk)} ATR로 이 후보(${num1(p.stop_atr)} ATR)보다 넓어서, 같은 자리라면 배수가 같거나 더 낮게 나옵니다.`;
  return `${lead}손절이 이 후보와 같은 ${num1(bk)} ATR이라 같은 자리라면 배수도 같습니다. 다른 건 익절 방식(계단 잠금)과 진입 숫자입니다.`;
}
/** An account's own exit when it is not the pick's (the 기본값's lock): 익절 and 손절 in plain words. */
export function ownExitBox(a, p, r) {
  const tp = r && r.base_tp && a && a.exit === (r.base_exit || "ladder|2") ? r.base_tp : null;
  const name = (a && a.exit_ko) || (r && r.base_exit_ko) || "—";
  return h("div", {class: "rl-own"},
    h("p", {class: "rl-ownh"}, LK.roleChip(a.role), h("b", null, ` 이 계좌의 익절·손절: ${name}`)),
    tp ? h("dl", {class: "rl-kv"},
      h("div", null, h("dt", null, "익절"), h("dd", null, h("b", null, tpShort(tp)), " · ", tpWords(tp, r && r.costs))),
      h("div", null, h("dt", null, "손절"), h("dd", null, h("b", null, `${num1(tp.stop_atr)} ATR`), " · ", stopWords(tp.stop_atr, p.tf, tp)))) : null,
    h("p", {class: "note"}, lineupOn() ? `아래는 이 후보의 ‘${ROLE_KO.cand}’ 계좌의 익절·손절입니다. 배수 규칙은 모든 계좌가 같고, 손절 거리가 다르면 고르는 배수도 달라질 수 있습니다.`
      : "아래는 이 후보(후보 계좌)의 익절·손절입니다. 배수 규칙은 다섯 계좌 모두 같습니다."));
}
/** A pick's whole rule card body (the 익절·손절·배수 screen and 계좌 자세히); o.account: the account being read
 *  (계좌 자세히) when its exit is not the pick's. */
export function pickRuleBody(p, r, o = {}) {
  if (!p) return ui.none("준비 중");
  const roles = p.roles || {};
  const note = baseNote(p, r);
  return h("div", {class: "stack rl-pick"},
    o.account && o.account.exit && o.account.exit !== p.exit ? ownExitBox(o.account, p, r) : null,
    h("dl", {class: "rl-kv"},
      h("div", null, h("dt", null, "익절"), h("dd", null, h("b", null, tpShort(p.tp)), " · ", tpWords(p.tp, r && r.costs))),
      h("div", null, h("dt", null, "손절"), h("dd", null, h("b", null, `${num1(p.stop_atr)} ATR`), " · ", stopWords(p.stop_atr, p.tf, p.tp))),
      h("div", null, h("dt", null, "본전 승률"), h("dd", null, beWords(p))),
      h("div", null, h("dt", null, "배수"), h("dd", null, levWords(p))),
      h("div", null, h("dt", null, "증거금"), h("dd", null, lineupOn() ? `잔고 × 배수%: ${LK.levLadder().marginText}.` : `잔고 × 배수%: ${LK.levLadder().marginText}. 1/4 계좌는 그 1/4.`))),
    h("div", {class: "rl-sub"}, h("h3", {class: "cl-h3"}, "지금 이 숫자면"), nowBox(p, r)),
    h("div", {class: "rl-sub"}, h("h3", {class: "cl-h3"}, lineupOn() ? `이 후보의 계좌 ${fmt.int(ROLES.filter((r) => roles[r]).length)}개의 익절·손절과 실제로 쓴 배수` : `계좌 ${ROLES.length}개의 익절·손절과 실제로 쓴 배수`),
      h("div", {class: "rl-five"}, ROLES.map((role) => {
        const a = roles[role];
        if (!a) return null;
        return h("a", {class: ["rl-frow", `r-${role}`], href: `#/account/${encodeURIComponent(a.id)}`, title: `${ROLE_KO[role]} 계좌 자세히`},
          LK.roleChip(role, ROLE_SHORT[role]), h("span", {class: "rl-fexit"}, lineupOn() && role !== "cand" ? roleRule(role).exit
            : role === "base" ? (a.exit_ko || (r && r.base_exit_ko)) : a.exit_ko,
            role === "quarter" ? h("small", {class: "muted"}, " · 증거금 1/4") : null, role === "flip" ? h("small", {class: "muted"}, " · 방향은 동전") : null),
          h("span", {class: "num muted rl-fn"}, `거래 ${fmt.int(a.trades || 0)}번`),
          h("span", {class: "rl-fused"}, h("small", {class: "muted"}, "쓴 배수 "), usedChips(a.used)));
      })),
      note ? h("p", {class: "note"}, note) : null),
    o.links === false ? null : h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: `#/entries?s=${encodeURIComponent(p.name)}`}, "진입 차트"),
      h("a", {class: "btn-line", href: `#/custom?s=${encodeURIComponent(p.name)}`}, "커스텀값"), h("a", {class: "btn-line", href: "#/rules"}, "배수 규칙 전체")));
}
/** The compact box for 커스텀값 / 계좌 자세히: 익절, 손절, 본전 승률, 배수 in one short line each, and the link. */
export function ruleBox(c, r) {
  const p = r && r.picks ? r.picks[c.id] : null;
  if (!p) {
    return h("div", {class: "cl-exits"}, h("div", null, LK.roleChip("cand"), h("b", null, c.exit_ko)),
      h("a", {class: "btn-line", href: `#/rules?pick=${encodeURIComponent(c.id)}`}, "익절·손절·배수 자세히"));
  }
  const be = p.tp.kind === "R" && p.breakeven ? `${share(p.breakeven, 0)} (비용 전)` : p.tp.kind === "roe" ? "배수에 따라 다름" : "미리 셀 수 없음 (계단 잠금)";
  const tpTail = p.tp.kind === "R" ? ` = 손절 거리의 ${num1(p.tp.val)}배 가면 지정가로` : p.tp.kind === "roe" ? " = 그 순수익이 되는 가격에 지정가로" : "";
  return h("div", {class: "rl-box"},
    h("div", {class: "rl-bl"}, h("b", null, "익절"), h("span", null, tpShort(p.tp), tpTail)),
    h("div", {class: "rl-bl"}, h("b", null, "손절"), h("span", null, `${num1(p.stop_atr)} ATR = ${TF_BAR[p.tf] || tfKo(p.tf)} 평균 움직임의 ${num1(p.stop_atr)}배 · `,
      stopMoves(p.tp) ? "수익이 나면 계단 잠금으로 올라감" : "움직이지 않음")),
    h("div", {class: "rl-bl"}, h("b", null, "본전 승률"), h("span", null, be)),
    h("div", {class: "rl-bl"}, h("b", null, "배수"), h("span", null, p.best_ok ? `좋은 자리 ${LK.levLadder().bestTight} · 보통 ${LK.levLadder().normalTight}` : `늘 보통 자리 ${LK.levLadder().normalTight}`,
      " · 실제 ", usedChips(((p.roles || {}).cand || {}).used))),
    lineupOn() ? null : h("div", {class: "rl-bl muted"}, h("b", null, "기본값"), h("span", null, (r && r.base_exit_ko) || "계단 잠금 10%부터 · 손절 2 ATR")),
    h("a", {class: "btn-line", href: `#/rules?pick=${encodeURIComponent(c.id)}`}, "익절·손절·배수 자세히 (지금 코인별 배수)"));
}
