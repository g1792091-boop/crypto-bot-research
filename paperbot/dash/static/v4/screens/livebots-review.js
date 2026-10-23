// 실거래 › 검토 (#/review, "2주 검토"; owners 10/21 "대시보드 화면들 더 멋있게 모든 필요한 화면 부분들 다 추가로 만들어줘"): the
// screen the owners open on the review day of the 추세판단 봇, whose rules stay frozen for two weeks from its start
// (docs/trend-bot-ko.md 5). Did the new rules work, and did each new rule help? Read-only, from
// /api/v4/livebots/trendreview (dash/more/livereview.py; every 60 s, every 15 s while virtual results are still being
// worked out) and the site's summary (/api/v4/livebots: the live wallets now, handed in by screens/livebots.js as `hub`):
//   첫 줄        규칙 고정 2주 as a ring (day N of 14, D-day, the review date); 진짜 방향 vs 동전 방향: the paper account and
//               its coin-flip twin since the start side by side (trades, 첫 잠금까지 간 비율, net P&L, net ROE sum) with
//               the band a coin leaves to luck drawn on a 0-100 % scale, in plain words; both real executors since the start
//   하루하루      per KST day: 신호 → 검사 통과 → 되돌림 닿음 (a config that waits: trend.pullback_wait; the owners' since
//               10/22 enters at once) → 진입 as one stacked bar, the day's paper P&L (and the coin's);
//               the cumulative line of both (순ROE 합 or USDT)
//   새 규칙이 도왔나? (가상)  one tile per new rule: what it is, a verdict that never overclaims (아직 판단 못 함 under 20,
//               운 범위 안 inside the band), the virtual numbers next to the bot's own, the newest rows behind 펼치기
//   나눠 보기     the record by role, member, coin, side, exit reason, entry timeframe
//   검토 날 볼 것  a checklist in plain words with where each item stands now; rule changes are the owners' decision
// HONESTY: paper money is never shown as real money (페이퍼(연습) on every paper number, the caption lines); every
// virtual result carries 가상; under 20 trades 표본 적음: 대부분 운; what could not be worked out says why (못 함 /
// 수집 전), never a zero; a failed refresh keeps the last answer dimmed with its age.
import {h, s, put, ui, fmt, serverNow, href} from "../core/pb.js";
import {acctKo, sourceState, mainFollowKo, josaObj} from "./livebots-kit.js";

const KICK = "2주 검토 · 추세판단 봇 · 바이비트 · WOO X Pro가 따라가는 페이퍼(연습)";
/** The hero's kicker: who follows the trend bot (two paper bots, owners 10/23: only its own followers; one: as before). */
export const kickKo = () => { const f = mainFollowKo(); return f ? `2주 검토 · 추세판단 봇 · ${f} 페이퍼(연습)` : KICK; };
/** An executor's other paper bot on its tile (the server's execs[].other): "지금은 VWAP 개선판을 따라가요 · 그 봇 거래 3번은 안
 *  셈"; null without one. */
export function otherKo(o) {
  if (!o) return null;
  const bot = o.bot_ko || "다른 페이퍼 봇";
  return `${o.now ? `${o.since != null ? `${fmt.kst(o.since)}부터 ` : ""}${bot}${josaObj(bot)} 따라가요` : `한때 ${bot}${josaObj(bot)} 따라갔어요`}`
    + (o.n ? ` · 그 봇 거래 ${fmt.int(o.n)}번은 안 셈` : "");
}

export const API = "/api/v4/livebots/trendreview";
const REFRESH_MS = 60 * 1000;
const BUSY_MS = 15 * 1000;                 // while virtual results are left (the server works them out a slice at a time)
const DAY = 24 * 3600 * 1000;
const KST_MS = 9 * 3600 * 1000;
const RING_R = 52;
const RING_C = 2 * Math.PI * RING_R;
const has = (x) => x != null && x !== "" && Number.isFinite(Number(x));
const SIDE = (x) => (Number(x) > 0 ? "롱" : "숏");
const DOW = "일월화수목금토";
const SPLITS = [["role", "역할"], ["member", "매매법"], ["coin", "코인"], ["side", "방향"], ["exit", "청산 이유"], ["tf", "진입 봉"]];

// ================================================================ pure (node tests: tests/test_livereview.py)
/** A ratio as percentage points: 0.308 -> "+30.8%p". */
export const pp = (x, dec = 1) => (has(x) ? `${fmt.num(Number(x) * 100, dec, true)}%p` : "—");
/** Money with its sign: "+$12.30" / "−$4.00". */
export const signed = (x) => (has(x) ? `${Number(x) >= 0 ? "+" : "−"}${fmt.usd(Math.abs(Number(x)))}` : "—");
/** A KST day's label: "10/22 (목)". */
export const dayKo = (ms) => (has(ms) ? `${fmt.mmdd(ms)} (${DOW[(Math.floor((Number(ms) + KST_MS) / DAY) + 4) % 7]})` : "—");

/** The freeze ring: {frac, dayN, days, big, sub, done}. */
export function freezeView(bot) {
  if (!bot || !has(bot.until)) return {frac: 0, dayN: null, days: 14, big: "—", sub: "규칙 고정 기간 모름", done: false};
  const days = Number(bot.days) || 14;
  if (bot.done) return {frac: 1, dayN: days, days, big: "검토할 때예요", sub: `${fmt.mmdd(bot.until)}부터 검토 · 2주 기록이 다 모였어요`, done: true};
  return {frac: Math.max(0, Math.min(1, Number(bot.frac) || 0)), dayN: Number(bot.day_n), days, big: `D-${fmt.int(bot.d_left)}`,
    sub: `${dayKo(bot.until)} 검토 · 그때까지 규칙을 바꾸지 않아요`, done: false};
}

/** The verdict chip of a what-if: {ko, cls}. */
export function verdictChip(kind) {
  return ({helped: {ko: "도운 쪽", cls: "good"}, hurt: {ko: "손해 본 쪽", cls: "bad"}, luck: {ko: "운 범위 안", cls: "accent"},
    small: {ko: "아직 판단 못 함", cls: "thin"}, none: {ko: "아직 없음", cls: "thin"}, na: {ko: "못 함", cls: "warn"},
    off: {ko: "뺀 규칙", cls: "thin"}})[kind]
    || {ko: "아직 판단 못 함", cls: "thin"};
}

/** The headline of the first block: how far, how many trades, how much to trust them. */
export function headline(d) {
  if (!d || d.state !== "ok") return "2주 검토 기록을 기다리는 중";
  const r = ((d.record || {}).real) || {};
  const fz = freezeView(d.bot);
  const when = fz.done ? "규칙 고정 2주가 끝났어요" : `새 규칙 ${fmt.int(fz.dayN)}일째`;
  if (!r.n) return `${when} · 아직 닫힌 거래가 없어요`;
  const trust = r.n < (d.small_n || 20) ? "표본 적음: 대부분 운" : r.n < 40 ? "아직 적은 편 (40번부터 조금 더 믿을 만)" : "판단에 쓸 만한 수";
  return `${when} · 거래 ${fmt.int(r.n)}번 · ${trust}`;
}

/** One day's funnel as a stacked bar: entered, touched (not entered), passed (not touched), stopped; fractions of
 *  ``top`` (the busiest day's signals). */
export function funnelParts(day, top, pull = true) {
  const n = Math.max(0, Number(day.signals) || 0), p = Math.min(n, Number(day.passed) || 0);
  const t = pull ? Math.min(p, Number(day.touched) || 0) : p, e = Math.min(t, Number(day.entered) || 0);
  const all = Math.max(1, Number(top) || n || 1);
  // 바로 진입 (pull false): a signal that passed goes in at its minute, no pullback step
  const parts = pull ? [["entered", e], ["touched", t - e], ["passed", p - t], ["stopped", n - p]]
    : [["entered", e], ["passed", p - e], ["stopped", n - p]];
  return parts.map(([k, v]) => ({k, n: v, frac: v / all}));
}
/** The answer's config waits for a pullback (trend.pullback_wait; missing = the 10/21 design: it waits), or waits came. */
export const pullOf = (d) => !d || d.pullback_wait !== false || Number((d.funnel || {}).touched) > 0;

/** The cumulative lines in a W x H box: {real, flip, zero, lo, hi, t0, t1} (SVG path data; key 1 = USDT, 2 = net ROE). */
export function curvePaths(curve, key, W, H, now) {
  const real = (curve && curve.real) || [], flip = (curve && curve.flip) || [];
  const pts = [...real, ...flip];
  if (!pts.length) return null;
  const t0 = Math.min(...pts.map((p) => p[0])), t1 = Math.max(Number(now) || 0, ...pts.map((p) => p[0]));
  let lo = Math.min(0, ...pts.map((p) => p[key])), hi = Math.max(0, ...pts.map((p) => p[key]));
  if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.08;
  lo -= pad; hi += pad;
  const X = (t) => (t1 > t0 ? ((t - t0) / (t1 - t0)) * W : 0), Y = (v) => H - ((v - lo) / (hi - lo)) * H;
  // a step line: the total holds until the next close, then jumps (and runs on to now)
  const path = (ps) => {
    if (!ps.length) return "";
    let out = `M${X(ps[0][0]).toFixed(1)} ${Y(ps[0][key]).toFixed(1)}`;
    for (let i = 1; i < ps.length; i++) out += ` H${X(ps[i][0]).toFixed(1)} V${Y(ps[i][key]).toFixed(1)}`;
    return out + ` H${X(t1).toFixed(1)}`;
  };
  return {real: path(real), flip: path(flip), zero: Y(0), lo, hi, t0, t1,
    last: {real: real.length ? real[real.length - 1][key] : null, flip: flip.length ? flip[flip.length - 1][key] : null}};
}

/** 검토 날 볼 것: the checklist with where each item stands now: [{id, ko, now, tone}]. */
export function checklist(d) {
  const ok = d && d.state === "ok";
  const r = ok ? (d.record || {}).real || {} : {};
  const luck = ok ? (d.record || {}).luck || {} : {};
  const items = ok ? ((d.whatif || {}).items || []) : [];
  const n = r.n || 0;
  const helped = items.filter((x) => (x.verdict || {}).kind === "helped").map((x) => x.ko);
  const hurt = items.filter((x) => (x.verdict || {}).kind === "hurt").map((x) => x.ko);
  const undecided = items.filter((x) => ["small", "none", "luck", "na"].includes((x.verdict || {}).kind)).length;
  return [
    {id: "enough", ko: "거래가 충분한가요? (20번 넘으면 조금, 40번 넘으면 더 믿을 만)",
      now: ok ? `지금 ${fmt.int(n)}번 · ${n < 20 ? "표본 적음: 대부분 운" : n < 40 ? "아직 적은 편" : "판단에 쓸 만한 수"}` : "기록을 기다리는 중",
      tone: !ok ? "" : n < 20 ? "warn" : n < 40 ? "" : "good"},
    {id: "coin", ko: "진짜 방향이 동전 방향보다 나은가요? (차이가 운 범위를 넘었나)",
      now: ok ? luck.ko || "아직 견줄 수 없어요" : "기록을 기다리는 중",
      tone: luck.where === "above" && !luck.small ? "good" : luck.where === "below" && !luck.small ? "bad" : ""},
    {id: "rules", ko: "어떤 새 규칙이 도왔고, 어떤 규칙이 손해였나요? (아래 가상 판정 · 아직 판단 못 함이면 미뤄요)",
      now: ok ? [helped.length ? `도운 쪽: ${helped.join(", ")}` : null, hurt.length ? `손해 본 쪽: ${hurt.join(", ")}` : null,
        undecided ? `판단 미룸 ${fmt.int(undecided)}개` : null].filter(Boolean).join(" · ") || "아직 없음" : "기록을 기다리는 중",
      tone: hurt.length ? "warn" : ""},
    {id: "cost", ko: "실거래가 페이퍼보다 얼마나 뒤처지나요? (미끄러짐 · 수수료 · 펀딩)", now: "비용 탭에서 봐요", tone: "", link: "cost"},
    {id: "decide", ko: "두 분이 정해요: 그대로 가기 · 한 가지만 바꾸기 · 멈추기",
      now: "규칙을 바꾸는 건 두 분의 결정이에요 (이 화면은 보여 주기만 해요) · 바꾼다면 한 번에 하나만 바꿔야 무엇이 효과였는지 알 수 있어요",
      tone: ""},
  ];
}

// ================================================================ the view
/** reviewView(ctx, hub) -> {el, set(summary)}: its own endpoint every 60 s (15 s while virtual results are left);
 *  ``set`` gets the site's summary (the live wallets' balance now) from screens/livebots.js. */
export function reviewView(ctx, hub) {
  const st = {d: null, s: null, okAt: 0, busy: false, sig: "", lastAt: 0, curveKey: 2, split: "role"};
  const stateSlot = h("div", {class: "lb-slot"});
  // the first block: the freeze ring, the headline, real vs coin, the executors
  const ringFill = s("circle", {class: "lrv-ring-fill", cx: 60, cy: 60, r: RING_R, "stroke-dasharray": `0 ${RING_C.toFixed(2)}`});
  const ringDot = s("g", {class: "lrv-ring-ticks"});
  const ringNum = h("b", {class: "lrv-ring-n num"}, "—");
  const ringOf = h("span", {class: "lrv-ring-of"}, "");
  const ring = h("div", {class: "lrv-ring", role: "img", "aria-label": "규칙 고정 2주"},
    s("svg", {viewBox: "0 0 120 120", "aria-hidden": "true"}, s("circle", {class: "lrv-ring-track", cx: 60, cy: 60, r: RING_R}), ringDot, ringFill),
    h("div", {class: "lrv-ring-c"}, ringNum, ringOf));
  const fzBig = h("b", {class: "lrv-fz-big"}, "—");
  const fzSub = h("span", {class: "lrv-fz-sub"}, "");
  const kick = h("p", {class: "lrv-kick"}, kickKo());
  const head = h("h2", {class: "lrv-head"}, "불러오는 중");
  const hsub = h("p", {class: "lrv-hsub"});
  const duel = h("div", {class: "lrv-duel"});
  const live = h("div", {class: "lrv-live", role: "list", "aria-label": "실거래 두 계좌"});
  const hero = h("section", {class: "lrv-hero", "aria-label": "2주 검토"},
    h("div", {class: "lrv-fz"}, ring, h("div", {class: "lrv-fz-t"}, fzBig, fzSub)),
    h("div", {class: "lrv-hmain"}, kick, head, hsub, duel), live);
  // the cards
  const daysBox = h("div", {class: "lrv-days"});
  const curveSeg = ui.seg([{id: "2", label: "순ROE 합"}, {id: "1", label: "손익 (USDT)"}], "2",
    (id) => { st.curveKey = Number(id); drawCurve(); }, {label: "누적 선 단위"});
  const curveBox = h("div", {class: "lrv-curve"});
  const rulesBox = h("div", {class: "lrv-rules"});
  const rulesHead = h("div", {class: "lrv-rhead"});
  const splitSeg = ui.seg(SPLITS.map(([id, label]) => ({id, label})), "role", (id) => { st.split = id; drawSplit(); }, {label: "나눠 보기", scroll: true});
  const splitBox = h("div", {class: "lrv-split"});
  const checkBox = h("ol", {class: "lrv-check"});
  const daysSub = h("span", null, "한국 시간 하루씩 · 신호 → 검사 통과 → 되돌림 닿음 → 진입, 그날 닫힌 거래의 페이퍼 손익");
  const cards = h("div", {class: "lrv-cards"},
    ui.card({title: "하루하루", label: "하루하루", sub: daysSub, cls: "lrv-dcard"},
      daysBox, h("div", {class: "lrv-chead"}, h("h3", {class: "lrv-h3"}, "누적 · 진짜 방향 vs 동전 방향 (페이퍼)"), curveSeg), curveBox),
    ui.card({title: "새 규칙이 도왔나?", sub: "가상 · 규칙에 걸린 신호와 감독 청산을 1분봉으로 다시 계산해 봇이 실제로 한 것과 견줘요", cls: "lrv-wcard",
      acts: [ui.pill("가상", "warn", "실제 체결이 아니라 1분봉으로 다시 계산한 결과")]}, rulesHead, rulesBox),
    h("div", {class: "lrv-two"},
      ui.card({title: "나눠 보기", sub: "페이퍼 · 새 규칙 시작 뒤 거래 · 한 칸 20번 미만은 대부분 운", cls: "lrv-scard"}, splitSeg, splitBox),
      ui.card({title: "검토 날 볼 것", sub: "순서대로 · 지금 어디쯤인지 같이 적었어요", cls: "lrv-ccard"}, checkBox)));
  const foot = h("div", {class: "lb-foot"},
    ui.assumeLine(["closed"], "페이퍼(연습) 손익은 진짜 돈이 아니에요 · 가상 = 1분봉으로 다시 계산한 결과(실제 체결 아님)"),
    ui.assumeLive("바이비트 · WOO X Pro: 새 규칙 시작 뒤 들어간 거래만 셈"));
  const body = h("div", {class: "lrv-body"}, hero, cards, foot);
  const el = h("div", {class: "lrv stack"}, stateSlot, body);

  // ---------------------------------------------------------------- parts
  function drawHero() {
    const d = st.d;
    const fz = freezeView(d && d.state === "ok" ? d.bot : null);
    ringFill.setAttribute("stroke-dasharray", `${(fz.frac * RING_C).toFixed(2)} ${RING_C.toFixed(2)}`);
    ringDot.replaceChildren(...Array.from({length: fz.days}, (_, i) => {
      const a = (i / fz.days) * 2 * Math.PI - Math.PI / 2;
      return s("circle", {class: ["lrv-ring-tick", fz.dayN != null && i < fz.dayN ? "on" : ""], cx: (60 + 44 * Math.cos(a)).toFixed(2),
        cy: (60 + 44 * Math.sin(a)).toFixed(2), r: 2.2});
    }));
    ring.setAttribute("aria-label", fz.dayN != null ? `규칙 고정 2주 중 ${fz.dayN}일째` : "규칙 고정 2주");
    ringNum.textContent = fz.dayN != null ? fmt.int(fz.dayN) : "—";
    ringOf.textContent = fz.dayN != null ? `일째 / ${fz.days}일` : "";
    fzBig.textContent = fz.big;
    fzSub.textContent = fz.sub;
    hero.className = fz.done ? "lrv-hero done" : "lrv-hero";
    head.textContent = headline(d);
    if (!d || d.state !== "ok") { put(hsub); put(duel); put(live); return; }
    const rec = d.record || {};
    const luck = rec.luck || {};
    hsub.textContent = d.since ? `새 규칙 시작 ${fmt.kst(d.since)} · 거래는 그 뒤에 들어간 것만 셌어요` : "";
    put(duel, duelOf(rec), luckOf(rec, luck));
    drawLive();
  }
  function duelOf(rec) {
    const col = (title, x, cls, tag) => h("div", {class: ["lrv-side", cls]},
      h("div", {class: "lrv-side-h"}, h("i", {class: "lrv-sw", "aria-hidden": "true"}), h("b", null, title), tag),
      x && x.n ? h("dl", {class: "lrv-nums"},
        h("div", null, h("dt", null, "거래"), h("dd", {class: "num"}, `${fmt.int(x.n)}번`)),
        h("div", null, h("dt", null, "첫 잠금까지 간 비율"), h("dd", {class: "num"}, fmt.pct(x.win_rate, 0, false), h("small", null, ` ${fmt.int(x.wins)}승 ${fmt.int(x.losses)}패`))),
        h("div", null, h("dt", null, "순손익 (페이퍼)"), h("dd", {class: ["num", fmt.tone(x.pnl, signed(x.pnl))]}, signed(x.pnl))),
        h("div", null, h("dt", null, "순ROE 합"), h("dd", {class: ["num", fmt.tone(x.roe_sum, pp(x.roe_sum))]}, pp(x.roe_sum))))
        : h("p", {class: "lrv-empty"}, "새 규칙으로 닫힌 거래가 아직 없어요"));
    return h("div", {class: "lrv-duo"},
      col("진짜 방향", rec.real, "real", ui.pill("페이퍼(연습)", "thin")),
      h("span", {class: "lrv-vs", "aria-hidden": "true"}, "vs"),
      col("동전 방향", rec.flip, "flip", ui.pill("같은 진입 · 방향만 동전", "thin", "동전 쌍둥이(COMBOFLIP@mix): 봇과 같은 때 같은 코인에 들어가고 방향만 동전으로 정한 비교용 페이퍼 계좌")));
  }
  /** The win rate on a 0-100 % scale: the coin's luck band shaded, the coin and the real side marked. */
  function luckOf(rec, luck) {
    const r = rec.real || {}, f = rec.flip || {};
    if (luck.state !== "ok") return h("p", {class: "lrv-luckw"}, luck.ko || "아직 견줄 수 없어요");
    const pos = (x) => `${(Math.max(0, Math.min(1, Number(x))) * 100).toFixed(2)}%`;
    const br = luck.band_rate || [0, 0];
    return h("div", {class: ["lrv-luck", luck.where || ""]},
      h("div", {class: "lrv-scale", role: "img", "aria-label": `진짜 방향 ${fmt.pct(r.win_rate, 0, false)} · 동전 방향 ${fmt.pct(f.win_rate, 0, false)} · 운 범위 ${fmt.pct(br[0], 0, false)}~${fmt.pct(br[1], 0, false)}`},
        h("span", {class: "lrv-band", style: {left: pos(br[0]), width: `${(Math.max(0, br[1] - br[0]) * 100).toFixed(2)}%`}}),
        h("span", {class: "lrv-mark flip", style: {left: pos(f.win_rate)}, title: `동전 방향 ${fmt.pct(f.win_rate, 0, false)}`}),
        h("span", {class: "lrv-mark real", style: {left: pos(r.win_rate)}, title: `진짜 방향 ${fmt.pct(r.win_rate, 0, false)}`})),
      h("div", {class: "lrv-scale-k"}, h("span", null, "0%"), h("span", null, "첫 잠금까지 간 비율"), h("span", null, "100%")),
      h("p", {class: "lrv-luckw"}, h("b", null, luck.ko),
        h("small", null, ` · 띠 = 동전 승률 ${fmt.pct(f.win_rate, 0, false)}에서 운만으로도 생기는 차이(±${fmt.num(Number(luck.half || 0) * 100, 0)}%p, 90%) · `
          + `진짜 ${fmt.pct(r.win_rate, 0, false)}가 띠 ${luck.where === "inside" ? "안" : luck.where === "above" ? "위" : "아래"}`)));
  }
  function drawLive() {
    const d = st.d;
    const now = (st.s && st.s.accts) || [];
    const tiles = (d.execs || []).map((x) => {
      const a = now.find((y) => y.id === x.id) || {};
      const name = acctKo(x.id) || x.name_ko;                // the site's names (the real-money strip's: 바이비트 · WOO X Pro)
      if (x.state !== "ok") {
        return h("div", {class: "lrv-tile na", role: "listitem"}, h("span", {class: "lrv-tk"}, `${name} 실거래`),
          h("b", {class: "lrv-tv"}, x.state === "missing" ? "수집 전" : "못 읽음"), h("span", {class: "lrv-ts"}, x.reason_ko || ""));
      }
      const tone = fmt.tone(x.pnl, signed(x.pnl));
      return h("div", {class: ["lrv-tile", tone, x.halted ? "bad" : ""], role: "listitem", title: x.real ? "거래소 실제 체결 기록 (진짜 돈)" : `실행기 모드 ${x.mode || "모름"}`},
        h("span", {class: "lrv-tk"}, `${name} ${x.real ? "실거래" : `실행기 · ${x.mode || "모드 모름"}`} · 새 규칙 뒤`),
        h("b", {class: "lrv-tv num"}, x.n ? signed(x.pnl) : "거래 없음"),
        h("span", {class: "lrv-ts num"}, [x.n ? `${fmt.int(x.n)}번 · ${fmt.int(x.wins)}승` : null, has(a.balance) ? `지갑 ${fmt.usd(a.balance)}` : null,
          x.open ? "포지션 있음" : null, x.halted ? "멈춤" : null, x.estimated ? `${fmt.int(x.estimated)}번은 지갑 변화로 어림` : null].filter(Boolean).join(" · ") || "새 규칙 뒤 따라간 거래만"),
        x.other ? h("span", {class: "lrv-ts lrv-other"}, otherKo(x.other)) : null);
    });
    put(live, tiles.length ? tiles : h("p", {class: "lrv-ts"}, "실행기 기록을 불러오는 중"));
  }
  function drawDays() {
    const days = st.d.days;
    if (!days) { put(daysBox, sourceState(st.d.signals_state, "신호 기록")); return; }
    const top = Math.max(1, ...days.map((x) => Number(x.signals) || 0));
    const f = st.d.funnel || {};
    const pull = pullOf(st.d);
    daysSub.textContent = `한국 시간 하루씩 · 신호 → 검사 통과 → ${pull ? "되돌림 닿음 → " : ""}진입, 그날 닫힌 거래의 페이퍼 손익`;
    put(daysBox,
      h("div", {class: "lrv-flow"}, [["신호", f.signals, "진입 매매법 신호", 0],
        ["검사 통과", f.passed, pull ? "추세 판단 · 진입 자리 검사를 통과해 되돌림을 기다림" : "추세 판단 · 진입 자리 검사를 통과해 그 분에 바로 진입", 1],
        pull ? ["되돌림 닿음", f.touched, "기다린 가격에 닿음", 2] : null, ["진입", f.entered, "페이퍼가 들어감", 3]].filter(Boolean).map(([k, n, title, i]) =>
        h("div", {class: ["lrv-fstep", "s" + i], title}, h("b", {class: "num"}, fmt.int(n || 0)), h("span", null, k)))),
      (f.blocked || []).length ? h("p", {class: "lrv-blocked"}, "걸린 곳: ", f.blocked.map((b, i) => [i ? " · " : "", `${b.ko} `, h("b", {class: "num"}, fmt.int(b.n))])) : null,
      h("ul", {class: "lrv-dlist", role: "list"}, days.slice().reverse().map((x) => h("li", {class: ["lrv-day", x.today ? "today" : ""]},
        h("span", {class: "lrv-dd num"}, dayKo(x.d0), x.today ? h("small", null, " 오늘") : null),
        h("span", {class: "lrv-dbar", role: "img", "aria-label": `신호 ${x.signals} · 통과 ${x.passed}${pull ? ` · 닿음 ${x.touched}` : ""} · 진입 ${x.entered}`},
          funnelParts(x, top, pull).filter((p) => p.n > 0).map((p) => h("i", {class: "lrv-seg-" + p.k, style: {"--v": p.frac.toFixed(4)}}))),
        h("span", {class: "lrv-dn num"}, [x.signals, x.passed, pull ? x.touched : null, x.entered].filter((v) => v != null).map((v) => fmt.int(v)).join(" → ")),
        h("span", {class: "lrv-dp"}, x.n ? h("b", {class: ["num", fmt.tone(x.pnl, signed(x.pnl))]}, signed(x.pnl)) : h("span", {class: "lrv-mute"}, "거래 없음"),
          x.n ? h("small", {class: "num"}, ` ${fmt.int(x.n)}번`) : null,
          x.flip_n ? h("small", {class: "lrv-mute num"}, ` · 동전 ${signed(x.flip_pnl)}`) : null)))),
      h("div", {class: "lrv-legend", "aria-hidden": "true"}, [["entered", "진입"], pull ? ["touched", "되돌림 닿음"] : null, ["passed", "검사 통과"], ["stopped", "걸림"]].filter(Boolean).map(([k, ko]) =>
        h("span", null, h("i", {class: "lrv-seg-" + k}), ko))));
  }
  function drawCurve() {
    const d = st.d;
    if (!d || d.state !== "ok") return;
    const W = 600, H = 180, key = st.curveKey;
    const c = curvePaths(d.curve, key, W, H, d.now_ms);
    const r = d.record || {};
    if (!c || (!(r.real || {}).n && !(r.flip || {}).n)) { put(curveBox, ui.empty("닫힌 거래가 생기면 선이 그려져요")); return; }
    const val = (v) => (key === 1 ? signed(v) : pp(v));
    put(curveBox,
      h("div", {class: "lrv-ckeys"}, h("span", {class: "real"}, h("i"), "진짜 방향 ", h("b", {class: ["num", fmt.tone(c.last.real, val(c.last.real))]}, val(c.last.real))),
        h("span", {class: "flip"}, h("i"), "동전 방향 ", h("b", {class: ["num", fmt.tone(c.last.flip, val(c.last.flip))]}, val(c.last.flip)))),
      h("div", {class: "lrv-plot"},
        h("div", {class: "lrv-yax", "aria-hidden": "true"}, h("span", {class: "num top"}, val(c.hi)),
          c.zero / H > 0.14 && c.zero / H < 0.86 ? h("span", {class: "num", style: {top: `${((c.zero / H) * 100).toFixed(2)}%`}}, "0") : null,
          h("span", {class: "num bot"}, val(c.lo))),
        h("div", {class: "lrv-svgbox"}, s("svg", {class: "lrv-svg", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
          "aria-label": `누적 ${key === 1 ? "손익" : "순ROE 합"}: 진짜 방향 ${val(c.last.real)} · 동전 방향 ${val(c.last.flip)}`},
        s("line", {class: "lrv-zero", x1: 0, x2: W, y1: c.zero.toFixed(1), y2: c.zero.toFixed(1)}),
        c.flip ? s("path", {class: "lrv-line flip", d: c.flip}) : null,
        c.real ? s("path", {class: "lrv-line real", d: c.real}) : null))),
      h("div", {class: "lrv-xlab num"}, h("span", null, fmt.kst(c.t0)), h("span", null, fmt.kst(c.t1))),
      key === 1 ? ui.note("손익(USDT)은 두 페이퍼 계좌의 크기가 달라지면 그만큼 차이가 나요 · 순ROE 합이 크기와 상관없이 견주기 좋아요") : null);
  }
  function ruleTile(x) {
    const v = x.verdict || {};
    const chip = verdictChip(v.kind);
    const pend = (x.virt || x.held || {}).pending || ((x.at || {}).pending) || 0;
    const parts = [];
    if (x.state !== "ok") {
      parts.push(h("p", {class: "lrv-na"}, x.state === "missing" ? "수집 전 · " : "못 함 · ", x.reason_ko || ""));
    } else if (x.virt) {                                  // trend / spot / nopull: the stopped signals entered (가상)
      const vv = x.virt, b = x.base || {}, a = x.actual || {};
      parts.push(h("div", {class: "lrv-count"}, h("b", {class: "num"}, `${fmt.int(x.n)}개`), " 신호가 걸림",
        h("small", null, ` · 결정 난 가상 결과 ${fmt.int(vv.decided)}개${vv.open ? ` · 아직 모름 ${fmt.int(vv.open)}` : ""}${vv.unknown ? ` · 계산 못 함 ${fmt.int(vv.unknown)}` : ""}`)),
      cmpBars([["걸린 신호 (가상)", vv.win_rate, vv.decided, vv.roe_mean, "virt"], ["봇이 탄 거래 (같은 방식 가상)", b.win_rate, b.decided, b.roe_mean, "base"]]),
      h("p", {class: "lrv-act"}, "봇 실제 (페이퍼): ", a.n ? `${fmt.int(a.n)}번 · 첫 잠금 ${fmt.pct(a.win_rate, 0, false)} · 순ROE 합 ${pp(a.roe_sum)}` : "닫힌 거래 없음"),
      x.capped ? ui.note(`신호가 많아 최근 것부터 일부만 계산했어요 (전체 ${fmt.int(x.n)}개)`) : null);
    } else if (x.id === "pull") {
      const g = x.gain || {};
      parts.push(h("div", {class: "lrv-count"}, h("b", {class: "num"}, `${fmt.int(x.n)}번`), " 되돌림으로 진입",
        h("small", null, ` · 전체 거래 ${fmt.int(x.of)}번 중`)),
      h("p", {class: "lrv-big"}, "진입가 이득 ", h("b", {class: ["num", fmt.tone(g.mean, pp(g.mean))]}, g.n ? pp(g.mean) : "—"),
        h("small", null, g.n ? ` 한 번 평균 순ROE (실제 숫자 · 합 ${pp(g.sum)})` : "")),
      cmpBars([["되돌림 가격 (가상 붙잡기)", (x.held || {}).win_rate, (x.held || {}).decided, (x.held || {}).roe_mean, "base"],
        ["신호 가격 (가상)", (x.at || {}).win_rate, (x.at || {}).decided, (x.at || {}).roe_mean, "virt"]]),
      (x.flips || {}).won_lost || (x.flips || {}).lost_won ? h("p", {class: "lrv-act"}, `결과가 갈린 거래: 되돌림 덕에 이김 ${fmt.int(x.flips.won_lost)}번 · 되돌림 탓에 짐 ${fmt.int(x.flips.lost_won)}번`) : null);
    } else {                                              // judge / time: the supervisor's exits held (가상)
      const hd = x.held || {}, a = x.actual || {};
      parts.push(h("div", {class: "lrv-count"}, h("b", {class: "num"}, `${fmt.int(x.n)}번`), " 이 규칙으로 닫음",
        h("small", null, ` · 결정 난 비교 ${fmt.int(hd.decided)}번${hd.open ? ` · 아직 모름 ${fmt.int(hd.open)}` : ""}`)),
      h("div", {class: "lrv-pair"},
        h("div", null, h("small", null, "실제 (감독 청산)"), h("b", {class: ["num", fmt.tone(a.roe_sum, pp(a.roe_sum))]}, a.decided ? pp(a.roe_sum) : "—")),
        h("div", null, h("small", null, "붙잡았다면 (가상)"), h("b", {class: ["num", fmt.tone(hd.roe_sum, pp(hd.roe_sum))]}, hd.decided ? pp(hd.roe_sum) : "—")),
        h("div", null, h("small", null, !hd.decided ? "차이" : x.delta >= 0 ? "감독 청산이 아낌" : "감독 청산이 손해"),
          h("b", {class: ["num", fmt.tone(x.delta, pp(x.delta))]}, hd.decided ? pp(x.delta) : "—"))),
      hd.decided ? h("p", {class: "lrv-act"}, `붙잡았다면 첫 잠금 ${fmt.int(hd.won)}번 · −50% 손절 ${fmt.int(hd.lost)}번`) : null);
    }
    const rows = x.rows || [];
    return h("article", {class: ["lrv-rule", "k-" + (v.kind || "none")]},
      h("div", {class: "lrv-rule-h"}, h("b", null, x.ko), ui.pill(chip.ko, chip.cls)),
      h("p", {class: "lrv-rule-r"}, x.rule_ko),
      // (the chip already says 아직 판단 못 함: the line says why)
      h("p", {class: ["lrv-verdict", v.kind || ""]}, String(v.ko || "").replace(/^아직 판단 못 함 · /, "")),
      ...parts,
      pend ? h("p", {class: "lrv-pend"}, `계산 중 ${fmt.int(pend)}개 · 다시 읽으면 이어서 계산해요`) : null,
      h("p", {class: "lrv-how"}, ui.pill("가상", "warn"), ` ${x.how_ko}`),
      rows.length ? ui.disclosure(`최근 ${fmt.int(rows.length)}개 보기`, h("ul", {class: "lrv-rows"}, rows.map((r) => rowOf(x, r)))) : null);
  }
  function cmpBars(list) {
    return h("div", {class: "lrv-bars"}, list.map(([ko, rate, n, mean, cls]) => h("div", {class: ["lrv-bar", cls]},
      h("span", {class: "lrv-bk"}, ko),
      h("span", {class: "lrv-bv num"}, has(rate) ? `첫 잠금 ${fmt.pct(rate, 0, false)}` : "—",
        h("small", null, n ? ` ${fmt.int(n)}개 · 평균 ${pp(mean)}` : " 결정 난 것 없음")),
      h("span", {class: "lrv-track"}, h("i", {style: {"--v": has(rate) ? Number(rate).toFixed(4) : "0"}})))));
  }
  function cfKo(cf) {
    if (!cf) return {ko: "—", tone: ""};
    if (cf.state === "won") return {ko: cf.floor ? `첫 잠금 넘음 (${fmt.pct(cf.roe, 1)} 이상)` : `이김 ${fmt.pct(cf.roe, 1)}`, tone: "up"};
    if (cf.state === "lost") return {ko: `손절 ${fmt.pct(cf.roe, 1)}`, tone: "down"};
    if (cf.state === "open") return {ko: `아직 모름${has(cf.roe) ? ` (지금 ${fmt.pct(cf.roe, 1)})` : ""}`, tone: ""};
    if (cf.state === "pending") return {ko: "계산 중", tone: ""};
    return {ko: `계산 못 함${cf.why_ko ? ` · ${cf.why_ko}` : ""}`, tone: ""};
  }
  function rowOf(x, r) {
    const cf = cfKo(r.cf);
    const who = h("span", {class: "lrv-rw"}, h("b", null, `${fmt.coin(r.symbol)} ${SIDE(r.side)}`), ` ${fmt.stratKo(r.strategy)} ${fmt.tfKo(r.tf)}`);
    if (x.virt) {
      return h("li", null, h("span", {class: "lrv-rt num"}, fmt.kst(r.t)), who,
        h("span", {class: ["lrv-rcf", cf.tone]}, h("small", null, "들어갔다면 "), cf.ko), r.why ? h("small", {class: "lrv-rwhy"}, r.why) : null);
    }
    if (x.id === "pull") {
      const at = cfKo(r.at);
      return h("li", null, h("span", {class: "lrv-rt num"}, fmt.kst(r.t)), who,
        h("span", {class: "lrv-rcf"}, h("small", null, "진입가 이득 "), h("b", {class: ["num", fmt.tone(r.gain, pp(r.gain))]}, pp(r.gain))),
        h("small", {class: "lrv-rwhy"}, `되돌림 가격: ${cf.ko} · 신호 가격(${fmt.price(r.sig_price)}): ${at.ko}`));
    }
    return h("li", null, h("span", {class: "lrv-rt num"}, fmt.kst(r.t)), who,
      h("span", {class: "lrv-rcf"}, h("small", null, "실제 "), h("b", {class: ["num", fmt.tone(r.roe, fmt.pct(r.roe, 1))]}, fmt.pct(r.roe, 1)),
        h("small", null, " · 붙잡았다면 "), h("span", {class: cf.tone}, cf.ko)),
      r.why ? h("small", {class: "lrv-rwhy"}, r.why) : null);
  }
  function drawRules() {
    const w = st.d.whatif || {};
    const items = w.items || [];
    const work = w.work || {};
    put(rulesHead, h("p", {class: "lrv-note"}, w.note_ko || ""),
      w.rule_db && w.rule_db.state && w.rule_db.state !== "ok" ? sourceState(w.rule_db, "규칙봇 1분봉") : null,
      work.pending ? h("p", {class: "lrv-pend"}, `가상 결과를 계산하는 중이에요 · ${fmt.int(work.pending)}개 남음 (15초마다 이어서)`) : null);
    put(rulesBox, items.length ? items.map(ruleTile) : ui.empty("가상 판정을 아직 못 만들었어요"));
  }
  function drawSplit() {
    const d = st.d;
    if (!d || d.state !== "ok") return;
    const rows = ((d.split || {})[st.split]) || [];
    const name = (r) => {
      if (st.split === "role") return r.id;
      if (st.split === "member") return h("span", null, fmt.stratKo(r.strategy), h("small", null, ` ${fmt.tfKo(r.tf)}${r.role ? ` · ${r.role}` : ""}`));
      if (st.split === "coin") return fmt.coin(r.id);
      if (st.split === "side") return SIDE(r.id);
      if (st.split === "exit") return r.ko || r.id;
      return `${fmt.tfKo(r.id)} 진입`;
    };
    put(splitBox, rows.length ? h("div", {class: "lrv-stbl", role: "table", "aria-label": "나눠 보기"},
      h("div", {class: "lrv-srow lrv-shead", role: "row"}, ["", "거래", "첫 잠금까지", "순ROE 합", "손익 (페이퍼)"].map((k) => h("span", {role: "columnheader"}, k))),
      rows.map((r) => h("div", {class: ["lrv-srow", r.n ? "" : "zero"], role: "row"},
        h("span", {class: "lrv-sname", role: "rowheader"}, name(r)),
        h("span", {class: "num", role: "cell"}, r.n ? `${fmt.int(r.n)}번` : "없음", r.n && r.small ? h("small", {class: "lrv-mute", title: "20번 미만: 대부분 운"}, " 적음") : null),
        h("span", {class: "lrv-swin", role: "cell"}, r.n ? [h("span", {class: "lrv-track"}, h("i", {style: {"--v": Number(r.win_rate || 0).toFixed(4)}})),
          h("b", {class: "num"}, fmt.pct(r.win_rate, 0, false))] : "—"),
        h("span", {class: ["num", fmt.tone(r.roe_sum, pp(r.roe_sum))], role: "cell"}, r.n ? pp(r.roe_sum) : "—"),
        h("span", {class: ["num", fmt.tone(r.pnl, signed(r.pnl))], role: "cell"}, r.n ? signed(r.pnl) : "—"))))
      : ui.empty("새 규칙으로 닫힌 거래가 아직 없어요"));
  }
  function drawCheck() {
    put(checkBox, checklist(st.d).map((c, i) => h("li", {class: ["lrv-ci", c.tone]},
      h("span", {class: "lrv-cn num", "aria-hidden": "true"}, String(i + 1)),
      h("div", {class: "lrv-cb"}, h("b", null, c.ko),
        c.link ? h("a", {class: "lrv-clink", href: (ctx.href || href)("livebots", c.link)}, `${c.now} →`) : h("span", {class: "lrv-cnow"}, c.now)))));
  }
  function draw() {
    const d = st.d;
    drawHero();
    if (!d || d.state !== "ok") {
      cards.hidden = true;
      put(stateSlot, d && d.state === "off" ? h("div", {class: "lb-state"}, ui.pill("꺼짐", "thin"), h("span", null, ` ${d.reason_ko}`))
        : sourceState(d, "추세판단 봇"));
      return;
    }
    cards.hidden = false;
    put(stateSlot);
    drawDays(); drawCurve(); drawRules(); drawSplit(); drawCheck();
  }

  const pending = () => !!(st.d && st.d.whatif && st.d.whatif.work && st.d.whatif.work.pending);
  async function load() {
    if (st.busy) return;
    st.busy = true;
    let d;
    try { d = await ctx.api(API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      if (st.d) { put(stateSlot, ui.staleNote(e, st.okAt, () => load().catch(() => {}))); ui.dim(body, true); }
      else put(stateSlot, ui.errorBox(e, () => load()));
      throw e;
    } finally { st.busy = false; st.lastAt = Date.now(); }
    if (!ctx.alive()) return;
    ui.dim(body, false);
    st.okAt = serverNow();
    const sig = JSON.stringify({...d, now_ms: 0});
    if (st.d && sig === st.sig) { put(stateSlot); return; }      // the same records: nothing redrawn
    st.d = d; st.sig = sig;
    draw();
  }
  if (hub && hub.get && hub.get()) st.s = hub.get();
  draw();
  load().catch(() => {});
  // every 60 s; every 15 s while the server still works out virtual results
  ctx.every(BUSY_MS, () => { if (pending() || Date.now() - st.lastAt >= REFRESH_MS - 500) load().catch(() => {}); }, {now: false});
  if (ctx.watch) ctx.watch("board", () => { if (st.d && st.d.state === "ok") draw(); });     // the strategies' Korean names
  return {el, set(sm) {
    if (!sm) return;
    st.s = sm;
    const kk = kickKo();
    if (kick.textContent !== kk) kick.textContent = kk;
    if (st.d && st.d.state === "ok") drawLive();
  }};
}
