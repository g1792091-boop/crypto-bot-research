// 익절·손절·배수 kit (owners 2026-10-12: "커스텀봇 각 매매법마다 익절구조 손절구조를 어떻게 잡았는지 ... 레버리지는 어떻게
// 적용되는거고"): an exit and the leverage rule in plain Korean, what the five accounts of a pick do differently, a pick's
// rule card (익절 · 손절 · 본전 승률 · 배수 · 지금 이 숫자면 · 실제로 쓴 배수 · 계좌 5개) and its compact box for 커스텀값 and
// 계좌 자세히. Data: /api/rules (dash.py rules_doc: the engine's own rule numbers from paperbot, the live ATRs). The words
// follow the rule bot's v4 (positions-kit ruleLine / whyBox, 용어 사전). Every string reaches the page as a text node.
import {h} from "./dom.js";
import * as fmt from "./fmt.js";
import * as ui from "./ui.js";
import * as LK from "./lk.js";
import {ROLES, ROLE_KO, ROLE_SHORT, tfKo} from "./labels.js";

export const LEVS = [50, 40, 30, 20];
export const COINS6 = ["BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD"];
const TF_BAR = {"15m": "15분봉", "30m": "30분봉", "1h": "1시간봉", "4h": "4시간봉"};
const LADDER_GAP = 0.02, LADDER_STEP = 0.05;                     // config ladder_trigger_gap / ladder_step
/** A share as a percent ("0.53%"); "—" without a number. */
export const share = (x, dec = 1) => (x == null || !Number.isFinite(Number(x)) ? "—" : fmt.pct(Number(x) * 100, false, dec));
const num1 = (x) => { const v = Math.round(Number(x) * 1000) / 1000; return fmt.num(v, v % 1 ? 1 : 0); };
const coinKo = (c) => String(c || "").replace(/USDT?$/, "");
/** A link to a term of 읽는 법's 용어 사전 (#/howto?q=ATR). */
export const term = (word, label) => h("a", {class: "rl-term", href: `#/howto?q=${encodeURIComponent(word)}`, title: `${word}: 읽는 법 › 용어 사전`}, label || word);

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
  RULES = doc; RULES_KEY = key;
  if (ctx.alive()) onDoc(doc);
  if (doc && doc.atr_loading && ctx.alive()) {
    try { doc = await ctx.api("/api/rules?wait=1"); } catch (e) { return RULES; }
    RULES = doc;
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
  if (tp.kind === "roe") return `고정 익절 수익 ${num1(tp.val * 100)}%`;
  if (tp.kind === "ladder_R") return `계단 잠금 + 익절 ${num1(tp.val)}R`;
  if (tp.kind === "struct") return `구조 익절(${num1(tp.val)}봉 스윙) + 계단 잠금`;
  return `계단 잠금 ${num1((tp.first_lock || 0.1) * 100)}%부터`;
}
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
    return `증거금 대비 순수익(수수료 뺀 ROE)이 +${num1(tp.val * 100)}%가 되는 가격에 지정가로 익절합니다. 배수가 낮을수록 그 가격이 멀어집니다: 20배면 약 ${at(20)}, 30배면 약 ${at(30)} 움직여야 합니다.`;
  }
  if (tp.kind === "ladder_R") return `손절 거리의 ${num1(tp.val)}배(${num1(tp.val)}R)에 지정가 익절을 걸어 두고, 그 전에는 ${lock(tp.first_lock || 0.1)}`;
  if (tp.kind === "struct") return `직전 ${num1(tp.val)}봉 스윙 자리에 지정가 익절을 걸고, ${lock(tp.first_lock || 0.1)}`;
  return `정해 둔 익절 가격이 없습니다. ${lock(tp.first_lock || 0.1)}`;
}
/** The stop in plain words. */
export function stopWords(k, tf, tp) {
  const moves = tp && tp.kind !== "R" && tp.kind !== "roe";
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
      cost ? [" 수수료·슬리피지(왕복 0.14%)를 넣으면 지금 손절 거리로 ", h("b", null, cost), " (손절이 좁은 코인일수록 비용 몫이 커서 높음)."] : null];
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
  if (p.best_ok) {
    return [term("좋은 자리"), ` (진입 강도 점수가 높은 자리: 5년 신호의 약 ${share(p.p_best, 0)})면 50배 → 40배 → 30배 → 20배, 아니면 `, term("보통 자리"),
      "라서 30배 → 20배 순서로 시도해, 두 가지 안전 검사를 모두 통과한 첫 배수로 들어갑니다."];
  }
  return [p.kind === "ds" ? "딥시크 매매법은 진입 강도 점수가 없어서 " : `이 칸(${tfKo(p.tf)})은 진입 강도 기준이 없어서 `, "늘 ", term("보통 자리"),
    ": 30배 → 20배 순서로 시도해 두 가지 안전 검사를 모두 통과한 첫 배수로 들어갑니다."];
}
/** "30배 3 · 20배 9" of the leverages an account used ({lev: count}); null when hidden, "아직 없음" without one. */
export function usedChips(u, o = {}) {
  if (u == null) return h("span", {class: "muted", title: "딥시크 금액 숨김 설정: 배수도 보내지 않습니다"}, "숨김");
  const ks = LEVS.filter((l) => u[String(l)]);
  if (!ks.length) return h("span", {class: "muted"}, o.none || "아직 없음");
  return h("span", {class: "rl-used"}, ks.map((l) => h("span", {class: ["rl-lev", `l${l}`]}, `${l}배 `, h("b", {class: "num"}, fmt.int(u[String(l)])))));
}
/** "40 / 30배": the leverage a long entered now gets as a 좋은 자리 / as a 보통 자리 (0: no step passes, no entry). */
export function levPair(x, bestOk) {
  if (!x) return "—";
  const one = (v) => (v == null ? "—" : v === 0 ? "못 들어감" : `${v}배`);
  return bestOk ? `${one(x.best)} / ${one(x.normal)}` : one(x.normal);
}

// ---------------------------------------------------------------- the five accounts, what each changes
export const ROLE_RULE = {
  cand: {nums: "커스텀값", exit: "후보 것", size: "규칙봇과 같음 (증거금 = 배수%)", dir: "신호대로", why: "커스텀값 + 커스텀 익절·손절이 정말 나은가"},
  quarter: {nums: "커스텀값", exit: "후보 것", size: "증거금만 1/4 (50배 12.5% · 40배 10% · 30배 7.5% · 20배 5%)", dir: "신호대로",
    why: "크기를 줄이면 덜 흔들리나 · 손실 검사가 4배 느슨해서 후보보다 높은 배수가 나오기도 함"},
  exitonly: {nums: "기본값 (규칙봇 숫자)", exit: "후보 것", size: "규칙봇과 같음", dir: "신호대로", why: "좋아진 게 숫자 덕인가 익절·손절 덕인가"},
  base: {nums: "기본값 (규칙봇 숫자)", exit: "지금 규칙봇 것: 계단 잠금 10%부터 · 손절 2 ATR", size: "규칙봇과 같음", dir: "신호대로", why: "규칙봇과 같은 조건 (그 칸에 하나)"},
  flip: {nums: "후보와 같은 시각 (숫자로 고르지 않음)", exit: "후보 것", size: "규칙봇과 같음", dir: "동전 던지기 (좋은 자리 여부도 동전 방향으로 다시 봄)",
    why: "방향을 맞힌 건가 운인가"},
};
/** The five accounts side by side: numbers, exit, size, direction, what it is for (rows on a phone, a table on a PC). */
export function rolesTable() {
  const cols = [["nums", "진입"], ["exit", "익절·손절"], ["size", "크기 · 배수"], ["dir", "방향"], ["why", "보려는 것"]];
  return h("div", {class: "rl-roles", role: "table", "aria-label": "계좌 5개가 다른 점"},
    h("div", {class: "rl-rrow rl-rhd", role: "row"}, h("span", {role: "columnheader"}, "계좌"), cols.map(([, k]) => h("span", {role: "columnheader"}, k))),
    ROLES.map((r) => h("div", {class: ["rl-rrow", `r-${r}`], role: "row"}, h("span", {class: "rl-rname", role: "rowheader"}, LK.roleChip(r)),
      cols.map(([key, k]) => h("span", {role: "cell", dataset: {k}}, ROLE_RULE[r][key])))),
    h("p", {class: "note"}, "배수 규칙은 다섯 계좌 모두 같습니다 (아래). 같은 규칙이라도 손절 폭과 증거금이 다르면 고르는 배수가 달라집니다."));
}

// ---------------------------------------------------------------- the leverage rule (one card)
/** The steps the engine tries, the two safety checks with their numbers, and the leverages the league actually used. */
export function levRuleBody(r) {
  if (!r || !r.steps) return ui.none("준비 중");
  const c = r.costs || {};
  const liqRange = (s) => {
    const v = Object.values(s.liq || {});
    return v.length ? `${share(Math.min(...v), 1)}~${share(Math.max(...v), 1)}` : "—";
  };
  const btc = (s) => (s.liq && s.liq.BTCUSD != null ? share(s.liq.BTCUSD, 1) : null);
  const rows = r.steps.map((s) => h("div", {class: ["rl-step", `l${s.lev}`], role: "row"},
    h("b", {class: "rl-steplev", role: "cell"}, `${s.lev}배`),
    h("span", {role: "cell", dataset: {k: "누가"}}, s.group === "best" ? "좋은 자리만" : "좋은 자리 · 보통 자리"),
    h("span", {role: "cell", class: "num", dataset: {k: "증거금"}}, `${share(s.margin, 0)} · 1/4은 ${share(s.q_margin, 1)}`),
    h("span", {role: "cell", class: "num", dataset: {k: "손절 거리 한도"}}, `${share(s.max_stop, 2)} · 1/4은 ${share(s.q_max_stop, 1)}`),
    h("span", {role: "cell", class: "num", dataset: {k: "진입 때 청산까지"}}, btc(s) ? `BTC ${btc(s)} (코인 ${liqRange(s)})` : liqRange(s))));
  const used = r.used_all || {};
  const picks = Object.values(r.picks || {});
  const npick = picks.length, wide = picks.filter((p) => p.stop_atr >= 3).length;
  return h("div", {class: "stack tight rl-levrule"},
    h("p", null, "배수(레버리지)는 신호가 올 때마다 엔진이 정합니다. 아래 순서대로 시도해서 ", h("b", null, "두 가지 안전 검사를 모두 통과한 첫 배수"),
      "로 들어갑니다. 하나도 통과하지 못하면 그 신호는 ", h("b", null, "들어가지 않고 건너뜁니다"), "."),
    h("div", {class: "rl-steps", role: "table", "aria-label": "배수 단계"},
      h("div", {class: "rl-step rl-stephd", role: "row"}, ["배수", "누가 시도", "증거금 (잔고 중)", "손절 거리 한도 (손실 검사)", "진입 때 청산까지"].map((t) => h("span", {role: "columnheader"}, t))),
      rows),
    h("ol", {class: "rl-checks"},
      h("li", null, h("b", null, "청산 검사"), ` · 손절선이 `, term("청산가"), `보다 안쪽에 있고, 그 사이가 1 ATR 이상(최소 진입가의 ${share(c.buffer_min, 1)})이어야 합니다. 배수가 높을수록 청산가가 가까워집니다 (위의 ‘진입 때 청산까지’).`),
      h("li", null, h("b", null, "손실 검사"), ` · 손절에 닿았을 때 잃는 돈(수수료·슬리피지 포함)이 잔고의 ${share(c.max_loss, 0)} 이하여야 합니다. 그래서 배수마다 쓸 수 있는 손절 거리에 한도가 있습니다 (위의 ‘손절 거리 한도’).`)),
    h("p", null, "그래서 ", h("b", null, "손절이 넓을수록 배수가 내려갑니다"), `. 예를 들어 손절이 1%면 좋은 자리라도 50배(한도 ${share((r.steps[0] || {}).max_stop, 2)})와 40배(한도 ${share((r.steps[1] || {}).max_stop, 2)})는 손실 검사에 걸려 30배로 들어갑니다. `,
      wide ? `후보 ${fmt.int(npick)}개 중 ${fmt.int(wide)}개는 손절이 3~4 ATR로 넓어서 20~30배가 많고, ` : "", "손절 2 ATR인 기본값 계좌는 40·50배가 더 자주 나옵니다."),
    h("p", null, term("증거금"), " = 그 거래에 거는 돈 (잔고 × 비율). ", term("포지션 크기"), " = 증거금 × 배수. 예: 잔고 $5,000에서 30배면 증거금 $1,500, 포지션 $45,000. ",
      "1/4 계좌는 증거금만 1/4이라 손실 검사가 4배 느슨하고, 그래서 후보보다 높은 배수로 들어가기도 합니다."),
    h("div", {class: "rl-usedall"}, h("span", {class: "muted"}, "지금까지 실제로 쓴 배수 (닫힌 거래 · 계좌마다 최근 200번까지)"),
      ROLES.map((role) => h("div", {class: "rl-urow"}, LK.roleChip(role), usedChips(used[role] || {}, {none: "아직 닫힌 거래 없음"}))),
      r.hidden_accounts ? h("p", {class: "note"}, `딥시크 계좌 ${fmt.int(r.hidden_accounts)}개는 금액 숨김 설정이라 빠졌습니다.`) : null));
}

// ---------------------------------------------------------------- a pick
/** One coin's tile of "지금 이 숫자면": ATR, stop and take-profit distances, the break-even with costs, the leverage
 *  each account would get (좋은 자리 / 보통 자리). */
function coinTile(coin, x, p) {
  return h("div", {class: "rl-coin"},
    h("div", {class: "rl-coinh"}, h("b", null, coinKo(coin)), h("span", {class: "muted num"}, `ATR ${share(x.atr_pct, 2)}`)),
    h("dl", {class: "rl-cdl"},
      h("div", null, h("dt", null, "손절 거리"), h("dd", {class: "num"}, share(x.stop_pct, 2))),
      h("div", null, h("dt", null, "익절 거리"), h("dd", {class: "num"}, share(x.tp_pct, 2))),
      x.be_cost != null ? h("div", null, h("dt", null, "본전 승률"), h("dd", {class: "num"}, share(x.be_cost, 0))) : null,
      h("div", null, h("dt", null, "후보 배수"), h("dd", {class: "num"}, levPair(x.lev.cand, p.best_ok))),
      h("div", null, h("dt", null, "1/4 배수"), h("dd", {class: "num"}, levPair(x.lev.quarter, p.best_ok))),
      h("div", null, h("dt", null, "기본값 배수"), h("dd", {class: "num", title: `기본값 계좌의 손절 2 ATR = ${share(x.base_stop_pct, 2)}`}, levPair(x.lev.base, p.best_ok)))));
}
/** "지금 이 숫자면": the six coins today (or why there is nothing). */
export function nowBox(p, r) {
  const now = p && p.now;
  if (!now || !Object.keys(now).length) {
    return h("p", {class: "muted"}, r && r.atr_loading ? "지금 시세로 계산하는 중 (몇 초)…" : "시세를 받지 못해 지금 숫자는 없습니다 (규칙은 위와 같음).");
  }
  return h("div", {class: "stack tight"},
    h("p", {class: "note"}, `${TF_BAR[p.tf] || tfKo(p.tf)} 마지막 닫힌 봉 기준 (${fmt.kst(r && r.atr_ms)} KST) · 지금 롱으로 들어간다면 · 잔고 $5,000 · `,
      p.best_ok ? "배수는 ‘좋은 자리 / 보통 자리’" : "늘 보통 자리", " · ‘못 들어감’ = 어느 배수도 안전 검사를 통과 못 해서 그 신호는 건너뜀"),
    h("div", {class: "rl-coins"}, COINS6.filter((c) => now[c]).map((c) => coinTile(c, now[c], p))));
}
/** A pick's whole rule card body (the 익절·손절·배수 screen and 계좌 자세히). */
export function pickRuleBody(p, r, o = {}) {
  if (!p) return ui.none("준비 중");
  const base = (p.roles || {}).base;
  const roles = p.roles || {};
  return h("div", {class: "stack rl-pick"},
    h("dl", {class: "rl-kv"},
      h("div", null, h("dt", null, "익절"), h("dd", null, h("b", null, tpShort(p.tp)), " · ", tpWords(p.tp, r && r.costs))),
      h("div", null, h("dt", null, "손절"), h("dd", null, h("b", null, `${num1(p.stop_atr)} ATR`), " · ", stopWords(p.stop_atr, p.tf, p.tp))),
      h("div", null, h("dt", null, "본전 승률"), h("dd", null, beWords(p))),
      h("div", null, h("dt", null, "배수"), h("dd", null, levWords(p))),
      h("div", null, h("dt", null, "증거금"), h("dd", null, "잔고 × 배수%: 50배면 잔고의 50%, 40배 40%, 30배 30%, 20배 20%. 1/4 계좌는 그 1/4."))),
    h("div", {class: "rl-sub"}, h("h3", {class: "cl-h3"}, "지금 이 숫자면"), nowBox(p, r)),
    h("div", {class: "rl-sub"}, h("h3", {class: "cl-h3"}, "계좌 5개의 익절·손절과 실제로 쓴 배수"),
      h("div", {class: "rl-five"}, ROLES.map((role) => {
        const a = roles[role];
        if (!a) return null;
        return h("a", {class: ["rl-frow", `r-${role}`], href: `#/account/${encodeURIComponent(a.id)}`, title: `${ROLE_KO[role]} 계좌 자세히`},
          LK.roleChip(role, ROLE_SHORT[role]), h("span", {class: "rl-fexit"}, role === "base" ? (a.exit_ko || (r && r.base_exit_ko)) : a.exit_ko,
            role === "quarter" ? h("small", {class: "muted"}, " · 증거금 1/4") : null, role === "flip" ? h("small", {class: "muted"}, " · 방향은 동전") : null),
          h("span", {class: "num muted"}, `${fmt.int(a.trades || 0)}번`), usedChips(a.used));
      })),
      base && base.exit && base.exit !== p.exit ? h("p", {class: "note"}, `기본값 계좌는 규칙봇의 지금 청산(${base.exit_ko || (r && r.base_exit_ko)})을 써서 손절이 2 ATR로 좁고, 그래서 배수가 더 높게 나오기 쉽습니다.`) : null),
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
  const be = p.tp.kind === "R" && p.breakeven ? `${share(p.breakeven, 0)} (비용 전)` : p.tp.kind === "roe" ? "배수에 따라 다름" : "—";
  return h("div", {class: "rl-box"},
    h("div", {class: "rl-bl"}, h("b", null, "익절"), h("span", null, tpShort(p.tp), p.tp.kind === "R" ? ` = 손절 거리의 ${num1(p.tp.val)}배 가면 지정가로` : "")),
    h("div", {class: "rl-bl"}, h("b", null, "손절"), h("span", null, `${num1(p.stop_atr)} ATR = ${TF_BAR[p.tf] || tfKo(p.tf)} 평균 움직임의 ${num1(p.stop_atr)}배 · 움직이지 않음`)),
    h("div", {class: "rl-bl"}, h("b", null, "본전 승률"), h("span", null, be)),
    h("div", {class: "rl-bl"}, h("b", null, "배수"), h("span", null, p.best_ok ? "좋은 자리 50→40→30→20배 · 보통 30→20배" : "늘 보통 자리 30→20배",
      " · 실제 ", usedChips(((p.roles || {}).cand || {}).used))),
    h("div", {class: "rl-bl muted"}, h("b", null, "기본값"), h("span", null, (r && r.base_exit_ko) || "계단 잠금 10%부터 · 손절 2 ATR")),
    h("a", {class: "btn-line", href: `#/rules?pick=${encodeURIComponent(c.id)}`}, "익절·손절·배수 자세히 (지금 코인별 배수)"));
}
