// What the league's numbers say beyond the means (the rule bot's v4 pieces, adapted to the 후보 리그's data; nothing
// imported from it): 왜 이 성적인가 (screens/account-why.js: where the result stands, the closed trades' P&L before and
// after fees + funding, by exit reason, the win rate against the one the average win / loss needs, the leverages used,
// the three largest losses), 연패 맥락 (analysis-streak.js: the longest losing run against what the account's own win
// rate makes usual), 운 vs 실력 (luck-kit: how many picks beat their 동전 / 기본값 against the range luck alone gives),
// and 5년 시험 vs 지금 (vs5y-kit: the trade pace of the 5-year test period against the league's; an upper bound: the
// test counted every signal of the six coins (research/fullgrid/PREREG.md 5, no position limit) while a league account
// holds one position at a time (paperbot Settings.single_position), so the league trades fewer by design).
// Data: /api/insight (dash.py, summary.account_insight: each account's newest 200 trades) and the shared snapshot.
// HONESTY: small samples say so; a hidden DeepSeek account shows counts and labels only (ds_hidden).
import {h} from "./dom.js";
import * as fmt from "./fmt.js";
import * as ui from "./ui.js";
import * as LK from "./lk.js";
import {reasonKo, coinOf, coinShort, sideKo} from "./labels.js";

const DAY = 86400000;
/** The 5-year study's test period: 2024-01-01 .. 2026-10-01 UTC (research/fullgrid/PREREG.md), in days. */
export const TEST_DAYS = 1004;
const REASONS = ["SL", "LOCK", "TP", "LIQ"];
const share = (x, dec = 0) => (x == null || !Number.isFinite(Number(x)) ? "—" : fmt.pct(Number(x) * 100, false, dec));

// ---------------------------------------------------------------- /api/insight, one copy per snapshot
let INS = null, INS_KEY = null, insP = null;
export async function loadInsight(ctx) {
  const d = LK.league();
  const key = d ? `${d.generated_ms}` : "";
  if (INS && INS_KEY === key) return INS;
  if (!insP) insP = ctx.api("/api/insight").finally(() => { insP = null; });
  INS = await insP;
  INS_KEY = key;
  return INS;
}

// ---------------------------------------------------------------- 운 vs 실력
/** P(X <= k) of a binomial(n, p). */
export function binomCdf(k, n, p) {
  if (k < 0) return 0;
  if (k >= n) return 1;
  let term = Math.pow(1 - p, n), sum = term;
  for (let i = 1; i <= k; i++) { term *= ((n - i + 1) / i) * (p / (1 - p)); sum += term; }
  return Math.min(1, sum);
}
/** [lo, hi]: the counts out of n that luck alone (each a chance p) gives nine times in ten (5% below lo, 5% above hi). */
export function binomRange(n, p, tail = 0.05) {
  if (!(n > 0)) return [0, 0];
  if (p <= 0) return [0, 0];
  if (p >= 1) return [n, n];
  let lo = 0;
  while (lo < n && binomCdf(lo, n, p) <= tail) lo++;
  let hi = n;
  while (hi > 0 && 1 - binomCdf(hi - 1, n, p) <= tail) hi--;
  return [lo, hi];
}
/** One luck row: k of n against luck's range; tone: "above" (more than luck's range), "inside", "below". */
export function luckRow(k, n, p) {
  const [lo, hi] = binomRange(n, p);
  return {k, n, p, lo, hi, expect: n * p, tone: !n ? null : k > hi ? "above" : k < lo ? "below" : "inside"};
}
/** The luck rows of a snapshot: picks beating their 동전 / 기본값 (한 번 평균, LK.better), and the warning lights. */
export function luckRows(d) {
  const ix = LK.index(d);
  const cmp = (role) => {
    const xs = ix.cands.map((c) => LK.better(c, ix.sets[c.id][role])).filter((v) => v != null);
    return luckRow(xs.filter(Boolean).length, xs.length, 0.5);
  };
  const lit = ix.cands.filter((c) => (ix.judge[c.id] || {}).band);
  return {flip: cmp("flip"), base: cmp("base"), light: luckRow(lit.filter((c) => ix.judge[c.id].band.below).length, lit.length, 0.05)};
}
const toneKo = {above: "운으로 나오는 범위보다 많음", inside: "운만으로도 나오는 범위 안", below: "운으로 나오는 범위보다 적음"};
const toneShort = {above: "그 범위보다 많음", inside: "그 범위 안", below: "그 범위보다 적음"};
/** "동전보다 나은 후보 12 / 20 · 운만으로도 6~14개" as a row with a small bar (the range shaded, the count marked). */
export function luckLine(label, r, o = {}) {
  if (!r.n) return h("div", {class: ["lu-row", "empty"]}, h("b", null, label), h("span", {class: "muted"}, o.empty || "아직 비교할 후보가 없습니다"));
  const pos = (x) => `${((100 * x) / r.n).toFixed(1)}%`;
  return h("div", {class: ["lu-row", r.tone ? `t-${r.tone}` : ""]},
    h("b", null, label),
    h("span", {class: "num lu-k"}, `${fmt.int(r.k)} / ${fmt.int(r.n)}`),
    h("span", {class: "lu-bar", role: "img", "aria-label": `${r.k}개, 운만으로 ${r.lo}~${r.hi}개`},
      h("i", {class: "lu-band", style: {left: pos(r.lo), width: `calc(${pos(r.hi - r.lo)} + 2px)`}}),
      h("i", {class: "lu-mark", style: {left: pos(Math.min(r.k, r.n))}})),
    h("span", {class: "lu-t"}, `운만으로 ${fmt.int(r.lo)}~${fmt.int(r.hi)}개 (평균 ${fmt.num(r.expect, 1)}) · `, h("b", null, toneKo[r.tone])));
}
/** The 운 vs 실력 card body (점검 진행). */
export function luckBody(d) {
  const L = luckRows(d);
  return h("div", {class: "stack tight lu"},
    luckLine("동전보다 나은 후보", L.flip),
    luckLine("기본값보다 나은 후보", L.base),
    luckLine("경고등 켜진 후보", L.light, {empty: "아직 경고등 기준(10번)에 닿은 후보가 없습니다"}),
    h("p", {class: "note"}, "후보를 여러 개 세우면 아무 실력이 없어도 절반쯤은 동전·기본값보다 낫게 나옵니다. 막대의 색칠한 칸이 ‘운만으로 10번 중 9번 나오는 범위’이고, ",
      "그보다 많아야 운보다 낫다고 볼 수 있습니다. 후보들이 같은 코인·같은 시각에 들어가는 일이 많아 서로 독립이 아니라서, 진짜 운의 범위는 이보다 넓습니다. 판정은 점검 날 미리 정한 계산으로 합니다."));
}
/** The 요약 one-liner: "동전보다 나은 후보 12/20 · 운만으로도 6~14개". */
export function luckShort(d) {
  const r = luckRows(d).flip;
  if (!r.n) return null;
  return h("p", {class: ["note", "lu-short", r.tone === "above" ? "" : "muted"]}, `동전보다 나은 후보 ${fmt.int(r.k)} / ${fmt.int(r.n)} · 운만으로도 ${fmt.int(r.lo)}~${fmt.int(r.hi)}개 (`,
    toneShort[r.tone], ") · ", h("a", {href: "#/check"}, "운 vs 실력"));
}

// ---------------------------------------------------------------- 5년 시험 vs 지금
/** The trade pace of a pick: the 5-year test period's (test_n over TEST_DAYS) against the league's since its start.
 *  The test pace is an UPPER BOUND for the league: the test counted every signal on every coin at once (PREREG 5, no
 *  position limit), a league account holds one position at a time, so fewer trades are normal (never a warning).
 *  {rate, days, expect (most trades by now), actual, ratio, at: [{ko, ms, n}] (the most at each checkpoint), day30
 *  (the earliest date 30 trades can come), past30 (that date is past and the pick has fewer), actualRate}; null
 *  without a test count. */
export function pace5y(c, d) {
  const n5 = c && c.source && c.source.test_n;
  if (!n5 || !d || !d.start_ms) return null;
  const rate = n5 / TEST_DAYS;
  const days = Math.max(0, (d.done_ms - d.start_ms) / DAY);
  const expect = rate * days;
  const cps = ((d.watch || {}).checkpoints || []).map((cp) => ({ko: cp.ko, ms: cp.ms, n: rate * Math.max(0, (cp.ms - d.start_ms) / DAY)}));
  const day30 = d.start_ms + (30 / rate) * DAY;
  return {rate, days, expect, actual: c.trades || 0, ratio: expect >= 1 ? (c.trades || 0) / expect : null, at: cps,
    day30, past30: (c.trades || 0) < 30 && day30 <= d.done_ms, actualRate: days >= 1 ? (c.trades || 0) / days : null};
}
/** Why the league trades fewer than the 5-year pace (one sentence, every place the pace shows). */
export const PACE_WHY = "5년 시험은 여섯 코인의 신호를 모두 셌고(동시에 여러 개도), 리그 계좌는 한 번에 포지션 하나만 들고 있어서 그동안 온 신호는 건너뜁니다. 그래서 이 속도는 ‘많아야’ 숫자이고, 실제가 더 적은 게 보통입니다.";
/** "하루 약 0.3번 → 지금쯤 많아야 약 3번 (실제 2번) · 11/11까지 많아야 약 10번 · 30번은 빨라도 01/15쯤" (after a
 *  "5년 시험 속도(많아야) vs 지금" label). */
export function paceLine5y(c, d) {
  const p = pace5y(c, d);
  if (!p) return h("span", {class: "muted"}, "5년 시험 거래 수 없음");
  const first = p.at[0];
  return h("span", {class: "pc-line", title: PACE_WHY}, `하루 약 ${fmt.num(p.rate, 2)}번 → 지금쯤 많아야 약 ${fmt.num(p.expect, p.expect < 10 ? 1 : 0)}번 (실제 ${fmt.int(p.actual)}번)`,
    first ? ` · ${fmt.mmdd(first.ms)}까지 많아야 약 ${fmt.int(Math.round(first.n))}번` : "",
    p.actual >= 30 ? " · 30번 넘음" : p.past30 ? ` · 30번은 빨라도 ${fmt.mmdd(p.day30)}쯤이었음 (지남)` : ` · 30번은 빨라도 ${fmt.mmdd(p.day30)}쯤`,
    p.ratio != null && p.ratio > 2 ? h("b", {class: "warn"}, " · 시험 때보다 꽤 빠름") : null,
    h("small", {class: "muted pc-why"}, ` · 한 번에 포지션 하나라 실제는 더 적은 게 보통`));
}

// ---------------------------------------------------------------- 연패 맥락
/** "최장 연패 9번 · 지금 2번 연속 손실 · 이 승률(30%)로 60번이면 보통 최장 7번, 10번 중 9번은 11번 이하". */
export function streakLine(ins, o = {}) {
  if (!ins || !ins.n) return h("span", {class: "muted"}, "아직 닫힌 거래가 없습니다");
  const st = ins.streak || {};
  const wr = ins.n ? ins.wins / ins.n : null;
  const rare = st.rare != null && st.max > st.rare;
  return h("span", {class: ["sk-line", rare ? "rare" : ""]},
    `최장 연패 `, h("b", {class: "num"}, `${fmt.int(st.max)}번`), ` · 지금 ${st.cur ? `${fmt.int(st.cur)}번 연속 손실` : "연패 아님"}`,
    ins.n >= 10 && wr != null && wr > 0 ? [` · 이 승률(${share(wr)})로 ${fmt.int(ins.n)}번이면 보통 최장 ${fmt.int(st.usual)}번, 10번 중 9번은 ${fmt.int(st.rare)}번 이하`,
      rare ? h("b", {class: "warn"}, " · 드문 연패") : " · 흔한 범위"] : ins.n < 10 ? h("small", {class: "muted"}, " · 10번 전이라 맥락은 아직") : null,
    ins.capped ? h("small", {class: "muted"}, ` · 최근 ${fmt.int(ins.n)}번 기준`) : null);
}

/** The 연패 맥락 note for an account's exit (engine exit name: "tp3R|4", "tp2R|2", "roe50|4", "ladder|2", ...). */
export function streakNote(exit) {
  const tail = " 보통 범위 안의 연패로 매매법을 판단하지 않습니다.";
  const m = /^tp(\d+(?:\.\d+)?)R\|/.exec(String(exit || ""));
  if (m) {
    const r = Number(m[1]);
    const k = 1 + r;
    const one = Math.abs(k - Math.round(k)) < 1e-9 ? `${Math.round(k)}번 중 1번만` : `${share(1 / k)}만`;
    return `익절이 손절의 ${fmt.num(r, r % 1 ? 1 : 0)}배인 ${fmt.num(r, r % 1 ? 1 : 0)}R은 ${one} 이겨도 본전(비용 전)이라 이기는 비율이 낮고${r === 3 ? "(보통 30~35%)" : ""}, 연달아 지는 일이 흔합니다.${tail}`;
  }
  if (/^roe/.test(String(exit || ""))) return `증거금 대비 익절은 이길 때 버는 폭이 배수에 따라 달라서, 본전은 위의 ‘본전에 필요한 비율’로 봅니다. 연패가 ‘보통’ 범위 안이면 이상한 일이 아닙니다.${tail}`;
  if (/^(ladder|swing)/.test(String(exit || ""))) return `계단 잠금은 작게 자주 이기는 방식이라 이기는 비율이 높아야 본전이고, 그만큼 긴 연패는 드문 편입니다. 연패가 ‘보통’ 범위 안이면 이상한 일이 아닙니다.${tail}`;
  return `연패가 ‘보통’ 범위 안이면 이상한 일이 아닙니다.${tail}`;
}

// ---------------------------------------------------------------- 왜 이 성적인가 (계좌 자세히)
/** The waterfall steps (USDT): before costs → fees + funding → what the closed trades really made. */
export function waterfall(ins) {
  const a = ins.gross, c = ins.net;
  return [{key: "gross", label: "수수료·펀딩 전", from: 0, to: a}, {key: "cost", label: "수수료·펀딩", from: a, to: c},
    {key: "net", label: "실제 손익", from: 0, to: c}];
}
function fallRow(st, lo, hi) {
  const span = hi - lo || 1;
  const x0 = (Math.min(st.from, st.to) - lo) / span, x1 = (Math.max(st.from, st.to) - lo) / span;
  const d = st.to - st.from;
  const val = st.key === "cost" ? fmt.money(d, true) : fmt.money(st.to, true);
  const tone = st.key === "cost" ? "cost" : fmt.tone(st.to);
  return h("div", {class: "wy-frow"}, h("span", {class: "wy-fk"}, st.label),
    h("span", {class: "wy-ftrack"}, h("i", {class: ["wy-fbar", tone], style: {left: `${(x0 * 100).toFixed(2)}%`, width: `${Math.max(0.8, (x1 - x0) * 100).toFixed(2)}%`}}),
      lo < 0 && hi > 0 ? h("i", {class: "wy-fzero", style: {left: `${((-lo / span) * 100).toFixed(2)}%`}}) : null),
    h("b", {class: ["num", "wy-fv", st.key === "cost" ? "down" : fmt.tone(st.to)]}, val));
}
/** Why the money's break-even sits above the rule's: the size comes from the leverage and the margin, not from the
 *  stop, so a win on a narrow-stop coin can be smaller in dollars than a loss on a wide-stop coin. */
export function sizeNote(tp) {
  const m = tp && tp.kind === "R" && tp.val ? `${fmt.num(tp.val, tp.val % 1 ? 1 : 0)}배` : "규칙만큼";
  return `규칙보다 높은 이유: 포지션 크기는 손절 폭이 아니라 배수·증거금으로 정해져서, 손절이 좁은 코인에서 이기고 넓은 코인에서 지면 돈으로는 ${m}가 안 됩니다 (거래가 적을 때 흔함).`;
}
/**
 * The card. a: the account row; ins: its /api/insight row; o: {flip: the pick's 동전 account row, rule: the pick's
 * /api/rules row (the rule's own break-even), href(trade): a chart link for a trade}.
 */
export function whyCard(a, ins, o = {}) {
  const ret = LK.walletRet(a);
  const plate = ret != null && !ins?.hidden ? `왜 ${fmt.pct(ret * 100, true, 1)}인가` : "왜 이 결과인가";
  if (!ins || !ins.n) return ui.card({plate, cls: "wy"}, ui.empty("아직 닫힌 거래가 없습니다 · 첫 거래가 끝나면 이유가 채워집니다"));
  const cap = ins.capped ? h("p", {class: "note"}, `최근 ${fmt.int(ins.n)}번 기준 (전체 ${fmt.int(ins.total)}번 중) · 잔고와 수익률은 전체 기준`) : null;
  const reasons = Object.entries(ins.reasons || {}).sort((x, y) => (REASONS.indexOf(x[0]) + 1 || 9) - (REASONS.indexOf(y[0]) + 1 || 9));
  const chips = h("div", {class: "wy-reasons"}, reasons.map(([k, n]) => h("span", {class: ["wy-chip", k === "LIQ" ? "bad" : ""],
    title: ins.reason_pnl && ins.reason_pnl[k] != null ? `${reasonKo(k)} ${n}번 합계 ${fmt.money(ins.reason_pnl[k], true)}` : null},
  `${reasonKo(k)} ${fmt.int(n)}번`, ins.reason_pnl && ins.reason_pnl[k] != null ? [" ", h("b", {class: ["num", fmt.tone(ins.reason_pnl[k])]}, fmt.money(ins.reason_pnl[k], true))] : null)));
  const streak = h("div", {class: "wy-sec"}, h("p", {class: "wy-k"}, "연패 맥락"), h("p", {class: "wy-line"}, streakLine(ins)),
    h("p", {class: "note"}, streakNote(a.exit)));
  if (ins.hidden) {
    return ui.card({plate: "나간 이유", cls: "wy", sub: `닫힌 거래 ${fmt.int(ins.n)}번 · 딥시크 금액 숨김 설정이라 개수만`},
      h("div", {class: "wy-body"}, h("div", {class: "wy-sec"}, chips), streak), cap);
  }
  const secs = [];
  // ① where it stands: start → now, and the pick's 동전 account (same times, same exit, a coin's direction)
  const fr = o.flip && o.flip.id !== a.id ? LK.walletRet(o.flip) : null;
  const head = h("div", {class: "wy-head"},
    h("p", {class: "wy-big"}, h("span", {class: "num"}, fmt.money(LK.EQUITY)), " → ", h("b", {class: ["num", fmt.tone(ret)]}, a.wallet == null ? "—" : fmt.money(a.wallet)),
      ret != null ? h("span", {class: ["num", fmt.tone(ret)]}, ` (${fmt.pct(ret * 100, true, 1)})`) : null),
    fr != null ? h("p", {class: "wy-line"}, "같은 후보의 동전 계좌 (같은 시각 · 같은 익절·손절 · 방향만 동전) ", h("b", {class: ["num", fmt.tone(fr)]}, fmt.pct(fr * 100, true, 1)),
      " · 차이 ", h("b", {class: "num"}, `${fmt.num((ret - fr) * 100, 1, true)}%p`), " · 판정 아님") : null);
  // ② the waterfall
  if (ins.gross != null && ins.costs != null) {
    const steps = waterfall(ins);
    const vals = steps.flatMap((x) => [x.from, x.to]);
    const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
    secs.push(h("div", {class: "wy-sec"}, h("p", {class: "wy-k"}, "닫힌 거래의 손익이 어디로 갔나"),
      h("div", {class: "wy-fall", role: "img", "aria-label": steps.map((x) => `${x.label} ${fmt.money(x.key === "cost" ? x.to - x.from : x.to, true)}`).join(", ")},
        steps.map((x) => fallRow(x, lo, hi))),
      h("p", {class: "note"}, `수수료·펀딩 = (가격 움직임 × 배수 − 실제 증거금 대비 손익) × 증거금, 거래마다 (${fmt.int(ins.cost_n)}번). 수수료는 들어갈 때와 나올 때, 펀딩은 8시간마다 열린 포지션에서 나갑니다.`)));
  }
  // ③ by exit reason
  secs.push(h("div", {class: "wy-sec"}, h("p", {class: "wy-k"}, "나간 이유별"), chips));
  // ④ win rate vs the break-even rate
  const wr = ins.n ? ins.wins / ins.n : null, be = ins.breakeven, rb = o.rule && o.rule.breakeven;
  secs.push(h("div", {class: "wy-sec"}, h("p", {class: "wy-k"}, "이긴 비율과 본전에 필요한 비율"),
    h("p", {class: "wy-line"}, "이긴 비율 ", h("b", {class: "num"}, share(wr)), be != null ? [" · 본전에 필요한 비율 ", h("b", {class: "num"}, share(be))] : null,
      rb != null ? h("small", {class: "muted"}, ` · 규칙대로라면 ${share(rb)} (비용 전)`) : null, " ", LK.smallN(ins.n)),
    be != null ? h("div", {class: "wy-wr", role: "img", "aria-label": `이긴 비율 ${share(wr)}, 본전에 필요한 비율 ${share(be)}`},
      h("i", {class: ["wy-wrbar", wr >= be ? "up" : "down"], style: {width: `${(Math.max(0, Math.min(1, wr)) * 100).toFixed(1)}%`}}),
      h("i", {class: "wy-wrmark", style: {left: `${(Math.max(0, Math.min(1, be)) * 100).toFixed(1)}%`}, title: "본전에 필요한 비율"})) : null,
    h("p", {class: "note"}, ins.avg_win != null && ins.avg_loss != null
      ? `평균 이익 ${fmt.money(ins.avg_win, true)} · 평균 손실 ${fmt.money(-ins.avg_loss, true)}: 질 때 잃는 돈이 이길 때 버는 돈의 ${fmt.num(ins.avg_loss / (ins.avg_win || 1), 2)}배라 ${share(be)}는 이겨야 본전입니다.`
      : ins.wins ? "아직 진 거래가 없습니다." : "아직 이긴 거래가 없습니다."),
    be != null && rb != null && be > rb + 0.1 ? h("p", {class: "note"}, sizeNote(o.rule && o.rule.tp)) : null));
  // ⑤ leverages used
  secs.push(h("div", {class: "wy-sec"}, h("p", {class: "wy-k"}, "실제로 쓴 배수"), h("div", {class: "wy-levs"},
    Object.entries(ins.lev || {}).sort((x, y) => Number(y[0]) - Number(x[0])).map(([l, n]) => h("span", {class: "wy-chip"}, `${l}배 `, h("b", {class: "num"}, `${fmt.int(n)}번`)))),
  h("a", {class: "linkish", href: o.pick && o.pick.id ? `#/rules?pick=${encodeURIComponent(o.pick.id)}` : "#/rules"}, "왜 이 배수인가 (배수 규칙)")));
  // ⑥ the largest losses
  if (ins.big && ins.big.length) {
    const all = (ins.losses != null && ins.losses <= 3) || ins.big.length < 3;
    secs.push(h("div", {class: "wy-sec"}, h("p", {class: "wy-k"}, all ? `손실 ${fmt.int(ins.big.length)}번 (큰 순서)`
      : [`가장 큰 손실 ${fmt.int(ins.big.length)}번이 전체 손실의 `, h("b", {class: "num"}, share(ins.big_share))]),
      h("div", {class: "wy-big3", role: "list"}, ins.big.map((t) => h("div", {class: "wy-brow", role: "listitem"},
        h("span", {class: "num muted"}, fmt.kst(t.exit_time)), h("span", null, `${coinShort(coinOf(t.symbol))} ${sideKo(t.side)} · ${reasonKo(t.exit_reason)} · ${fmt.int(t.leverage)}배`),
        h("b", {class: "num down"}, fmt.money(t.pnl, true)),
        o.href ? h("a", {class: "wy-replay", href: o.href(t), title: "이 거래를 차트에서 보기"}, "차트") : null)))));
  }
  secs.push(streak);
  return ui.card({plate, cls: "wy", sub: `닫힌 거래 ${fmt.int(ins.n)}번으로 계산 · 손익은 거래마다 수수료·펀딩 뒤`},
    head, h("div", {class: "wy-body"}, secs), cap);
}
/** The 5계좌 비교 one-liner of an account: "손절 9 · 익절 3 · 비용 −$123 · 최장 연패 6". */
export function whyShort(ins) {
  if (!ins || !ins.n) return null;
  const r = ins.reasons || {};
  const parts = REASONS.filter((k) => r[k]).map((k) => `${reasonKo(k)} ${fmt.int(r[k])}`);
  if (ins.costs != null) parts.push(`수수료·펀딩 ${fmt.money(-ins.costs, true)}`);
  parts.push(`최장 연패 ${fmt.int((ins.streak || {}).max || 0)}`);
  return h("small", {class: "wy-short muted", title: ins.capped ? `최근 ${ins.n}번 기준` : null}, parts.join(" · "));
}
