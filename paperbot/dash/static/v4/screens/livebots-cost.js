// 실거래 › 비용 (#/livebots/cost, owners 10/19): how far each live executor's trades fall behind (or ahead of) the paper
// trades they followed (/api/v4/livebots/costs, dash/more/livebots.py costs()). Per exchange: the trades matched with their
// paper partner, the entry price against the paper's (in the trade's favour positive), fees and funding as the exchange
// charged them, the live P&L minus the paper P&L scaled to the live size (total and per trade), the ROE gap, the trades
// whose P&L is still a wallet estimate; the last 20 matched trades as paired bars (페이퍼 크기 맞춤 vs 실거래); per coin;
// the paper trades it did not follow and why; then the newest live trades, 10 a page.
// Why no waterfall (paper -> slip -> fees -> funding -> live): the paper P&L the server sends is already after the
// paper's own assumed fees and funding, and a slip in USDT needs the trade's size; neither is in this answer, so a
// split of the gap by cause would be invented. The bars show only what is measured.
// 체결 비교 (owners 10/19 night): per exchange the entry fill and the exit fill against the paper's (price %, and net ROE
// points at the trade's leverage), the fee really paid per side against the paper's 0.05 % (+ 0.02 % slippage), and the
// sum per trade (``gaps``, livebots.py fill_gaps on the executor's own fills). 진입 방식 판단: how many entries are measured
// against the 10-20 the owners want before deciding whether the executors enter at the signal time instead of following
// the paper fill, the average entry gap in ROE points and the share of a +10 % win it eats (``entry_judge``; numbers only,
// 판단은 두 분이).
// 수수료 줄이기 (owners 10/21 night: the 추세판단 봇's replay was about break-even before costs, the costs took ~4.5 %p a trade;
// the server's ``fees``, dash/more/livefees.py): per exchange, since the trend bot's start or all of its trades (one switch,
// each labelled), the fees really paid (entry / exit, from the fills), the slippage against the price the executor saw when
// it decided, before costs -> net per trade in net-ROE points, the share of the before-cost profit the costs took, and
// "지정가(메이커)로 들어갔다면 (가상)": the same trades at the documented maker rate (entry only; both sides as the most it
// could be), a maker rate nobody documented = 모름; the paper bot at its assumed rates; the rates with their sources. Every
// line says a limit may not fill (not in the number) and that the order type is the owners' decision.
// HONESTY: real money (실거래 · 진짜 돈) next to paper money (페이퍼 · 연습) always named; a number that is not there is
// '—' or its reason (체결 기록 전), never 0; ≈ marks a wallet estimate; a failed refresh keeps the last answer dimmed with
// its age. The pure functions below are tested in node.
import {h, s, put, ui, fmt, local, motion} from "../core/pb.js";
import {acctKo, acctTag, sourceState} from "./livebots-kit.js";

export const COST_API = "/api/v4/livebots/costs";
const REFRESH_MS = 30 * 1000;
const EX = ["bybit", "mexc"];
const BARS_N = 20;
export const EMPTY_KO = "실거래 거래가 아직 없어요 · 첫 거래가 닫히면 채워져요";

// ================================================================ pure functions (node tests)
const f1 = (v) => (Math.round(v * 10) / 10).toFixed(1);
const has = (x) => x != null && Number.isFinite(Number(x));

/** An entry slip (a fraction: 0.0005 = 0.05 %, in the trade's favour positive) in words: {text, tone, ko}. */
export function slipWords(x) {
  if (!has(x)) return {text: "—", tone: "", ko: "짝 맞춘 거래 없음"};
  const shown = fmt.pct(x, 3);
  return {text: shown, tone: fmt.tone(x, shown), ko: !/[1-9]/.test(shown) ? "페이퍼와 같음" : x > 0 ? "페이퍼보다 유리" : "페이퍼보다 불리"};
}
/** A win-rate / ROE gap (a ratio) as percentage points: -0.042 -> "−4.2%p". */
export const pp = (x, dec = 1) => (has(x) ? `${fmt.num(Number(x) * 100, dec, true)}%p` : "—");

/** The tiles of an exchange card (k, v, sub, tone), every unknown said as such (never a zero). */
export function costTiles(a) {
  const sl = slipWords(a.slip_avg), sw = slipWords(a.slip_worst);
  return [
    {id: "slip", k: "진입 미끄러짐 평균", v: sl.text, tone: sl.tone, sub: has(a.slip_avg) ? `${sl.ko} · +는 페이퍼보다 유리` : "+는 페이퍼보다 유리"},
    {id: "worst", k: "가장 불리했던 진입", v: sw.text, tone: sw.tone, sub: has(a.slip_worst) ? sw.ko : "짝 맞춘 거래 없음"},
    {id: "fees", k: "수수료 합", v: has(a.fees) ? fmt.money(a.fees) : "체결 기록 전", tone: "", sub: has(a.fees) ? "USDT · 거래소에 낸 돈" : "체결을 읽은 거래가 없어요"},
    {id: "funding", k: "펀딩 합", v: has(a.funding) ? fmt.money(a.funding, true) : "—", tone: has(a.funding) ? fmt.tone(a.funding, fmt.money(a.funding)) : "",
      sub: has(a.funding) ? "USDT · +는 받음, −는 냄" : "기록 없음"},
    {id: "roe", k: "ROE 차이 평균", v: pp(a.roe_gap_avg), tone: has(a.roe_gap_avg) ? fmt.tone(a.roe_gap_avg, pp(a.roe_gap_avg)) : "",
      sub: "실거래 − 페이퍼 (같은 거래)"},
  ];
}

/** The last n matched trades (rows newest first) oldest first, for the paired bars: {key, t, sym, side, paper, live, diff, est}. */
export function pairBars(rows, n = BARS_N) {
  return (rows || []).filter((r) => has(r.paper_scaled) && has(r.pnl)).slice(0, n).reverse()
    .map((r) => ({key: r.key, t: r.exit_time, sym: r.symbol, side: r.side, paper: Number(r.paper_scaled), live: Number(r.pnl),
      diff: has(r.diff) ? Number(r.diff) : Number(r.pnl) - Number(r.paper_scaled), est: !!r.est}));
}
/** Sums of the paired bars: {n, paper, live, diff}. */
export function sumPairs(items) {
  const add = (k) => items.reduce((a, x) => a + x[k], 0);
  return {n: items.length, paper: add("paper"), live: add("live"), diff: add("diff")};
}
/** The paired bars in pixels for a W x H box: the zero line, and per trade a paper bar (ghost) and a live bar. */
export function barGeom(items, W = 520, H = 150) {
  const pad = {l: 8, r: 8, t: 10, b: 10};
  const vals = items.flatMap((x) => [x.paper, x.live]);
  const hi = Math.max(0, ...vals), lo = Math.min(0, ...vals);
  const span = hi - lo || 1;
  const Y = (v) => pad.t + ((hi - v) / span) * (H - pad.t - pad.b);
  // a few trades sit at the right end (the newest last), a group never wider than 40 px
  const n = Math.max(1, items.length), gw = Math.min(40, (W - pad.l - pad.r) / n), x0 = W - pad.r - gw * n;
  const bw = Math.max(3, Math.min(12, gw * 0.34));
  const bar = (x, v) => ({x, y: Math.min(Y(v), Y(0)), w: bw, h: Math.max(1, Math.abs(Y(v) - Y(0)))});
  return {W, H, pad, zero: Y(0), hi, lo, gw,
    bars: items.map((it, i) => {
      const cx = x0 + gw * (i + 0.5);
      return {...it, cx, p: bar(cx - bw - 1, it.paper), l: bar(cx + 1, it.live)};
    })};
}
/** How many paper trades an executor did not follow, in all. */
export const missedTotal = (a) => (a && a.missed ? a.missed.reduce((t, m) => t + (Number(m.n) || 0), 0) : 0);

/** 체결 비교 tiles of one exchange (the server's ``gaps``): entry, exit, fee per side, the sum per trade; every unknown
 *  said as such (체결 기록 전), never 0. Gaps: + = in the trade's favour (the 비용 tab's own sign). */
export function gapTiles(g) {
  if (!g || g.state !== "ok") return [];
  const a = g.assumed || {};
  const gap = (x, roe, n, what) => ({v: has(x) ? fmt.pct(x, 3) : "체결 기록 전", tone: has(roe) ? fmt.tone(roe, pp(roe)) : "",
    sub: has(x) ? `순ROE ${pp(roe)} · ${fmt.int(n)}번 잼 · ${what}` : `${what} · 체결을 읽은 거래가 없어요`});
  return [
    {id: "in", k: "진입 체결 차이 평균", ...gap(g.entry_gap, g.entry_roe, g.entry_n, "+는 페이퍼보다 유리")},
    {id: "out", k: "청산 체결 차이 평균", ...gap(g.exit_gap, g.exit_roe, g.exit_n, "+는 페이퍼보다 유리")},
    {id: "fee", k: "수수료 (한쪽)", v: has(g.fee_rate) ? fmt.pct(g.fee_rate, 3, false) : "체결 기록 전", tone: "",
      sub: `가정 ${fmt.pct(a.taker, 2, false)} + 미끄러짐 ${fmt.pct(a.slip, 2, false)} · 거래소 기본 ${fmt.pct(a.exchange_fee, 3, false)}`
        + (has(g.fee_roe) ? ` · 순ROE ${pp(g.fee_roe)}` : "")},
    {id: "sum", k: "거래당 합 (순ROE)", v: has(g.total_roe) ? pp(g.total_roe) : "—", tone: has(g.total_roe) ? fmt.tone(g.total_roe, pp(g.total_roe)) : "",
      sub: has(g.total_roe) ? `진입 + 청산 + 수수료 중 잰 것 ${fmt.int(g.total_parts)}개 · −면 실거래가 덜 벎` : "잰 것이 아직 없어요"},
  ];
}

/** 진입 방식 판단, one exchange in words: {n, of, pct (0..1 of the 20), roe, share, ko}. */
export function judgeRow(r, need = [10, 20]) {
  const n = Number((r && r.n) || 0), hi = need[1] || 20;
  const roe = r && has(r.entry_roe) ? Number(r.entry_roe) : null, share = r && has(r.share_of_win) ? Number(r.share_of_win) : null;
  let ko = "잰 진입이 아직 없어요";
  if (roe != null) {
    ko = roe < 0 ? `진입이 평균 순ROE ${pp(roe)} 불리 · +10% 이긴 거래의 ${fmt.pct(share, 0, false)}를 먹어요`
      : roe > 0 ? `진입이 평균 순ROE ${pp(roe)} 유리 (페이퍼보다 좋게 들어감)` : "진입이 페이퍼와 같아요";
  }
  return {n, need, pct: Math.min(1, n / hi), roe, share, ko, ready: n >= (need[0] || 10)};
}

// ---------------------------------------------------------------- 수수료 줄이기 (owners 10/21 night: livefees.py)
export const FEE_SPANS = [{id: "since", label: "추세판단 봇 시작부터"}, {id: "all", label: "전체 거래"}];
/** A cost in net-ROE points of the margin (+ = paid): 0.032 -> "3.2%p"; unknown "—". */
export const ptsKo = (x, dec = 1) => (has(x) ? `${fmt.num(Number(x) * 100, dec)}%p` : "—");
/** A fee rate a side, trailing zeros dropped: 0.00055 -> "0.055%", 0.0002 -> "0.02%"; unknown "모름" (never invented). */
export const rateKo = (x) => (has(x) ? fmt.pct(x, 3, false).replace(/(\.\d*?)0+%$/, "$1%").replace(/\.%$/, "%") : "모름");
/** The span shown: "since" (the trend bot's start) when the server has that start, else "all". */
export const spanOf = (f, want) => (want === "since" && f && f.since != null ? "since" : "all");

/** What the costs took of one result (USDT or ROE points alike), in words; an unmeasured one says so (never a 0). */
export function shareWords(before, fee, slip) {
  if (!has(before) || !has(fee)) return "비용 못 잼";
  const b = Number(before), fe = Number(fee), sl = has(slip) ? Number(slip) : 0, cost = fe + sl;
  if (b > 0 && cost < b) return `비용 전 이익의 ${fmt.pct(fe / b, 0, false)}는 수수료 · ${fmt.pct(sl / b, 0, false)}는 미끄러짐`;
  if (b > 0) return `비용이 비용 전 이익의 ${fmt.pct(cost / b, 0, false)} · 이익이 손실로 바뀜`;
  return "비용 전에도 손실 · 비용이 손실을 더 키움";
}

/** The tiles of one exchange's span (the server's block): fees, slippage, per trade before -> net, the share. */
export function feeTiles(b) {
  if (!b || !b.measured) return [];
  const usd = (x) => (has(x) ? `${fmt.money(x)} USDT` : "—");
  const split = (a, c, n) => (n ? `진입 ${fmt.money(a)} · 청산 ${fmt.money(c)}` : "진입·청산으로 못 나눔");
  const fund = has(b.funding_roe) && Math.abs(b.funding_roe) >= 0.0005 ? ` · 펀딩 ${ptsKo(-b.funding_roe)}` : "";
  const share = has(b.fee_share) ? b.fee_share + (has(b.slip_share) ? b.slip_share : 0) : null;
  return [
    {id: "fee", k: "낸 수수료", v: usd(b.fee), tone: "",
      sub: `${split(b.fee_in, b.fee_out, b.fee_split_n)}${has(b.fee_rate) ? ` · 실제 한쪽 ${rateKo(b.fee_rate)}` : ""}`},
    {id: "slip", k: "미끄러짐", v: usd(b.slip), tone: has(b.slip) && b.slip > 0 ? "down" : has(b.slip) && b.slip < 0 ? "up" : "",
      sub: `${split(b.slip_in, b.slip_out, b.slip_split_n)} · 주문 직전 본 가격 대비 (+는 불리)`},
    {id: "per", k: "거래당 순ROE", v: `${fmt.pct(b.before_roe, 1)} → ${fmt.pct(b.net_roe, 1)}`, tone: fmt.tone(b.net_roe, fmt.pct(b.net_roe, 1)),
      sub: `비용 전 → 순 · 수수료 ${ptsKo(b.fee_roe)} · 미끄러짐 ${ptsKo(b.slip_roe)}${fund}`},
    {id: "share", k: "비용이 가져간 몫", v: has(share) ? fmt.pct(share, 0, false) : has(b.before) ? "이익 없음" : "—", tone: "",
      sub: shareWords(b.before, b.fee, b.slip)},
  ];
}

/** 지정가(메이커)로 들어갔다면 (가상), one exchange's span: {known, rate, ko, lines: [{id, k, v, tone, sub}]}; without a
 *  documented maker rate nothing is worked out (known false, ko 모름 + where to find it). */
export function makerLines(b, rates) {
  const mk = rates ? rates.maker : null;
  if (!has(mk)) return {known: false, rate: null, lines: [], ko: `메이커 요율 모름 · ${(rates && rates.src_ko) || "이 거래소의 요율은 문서에 없어요"}`};
  const line = (id, k, x) => (!x ? {id, k, v: "—", tone: "", sub: "체결을 읽은 거래가 없어요"}
    : {id, k, v: `${fmt.money(x.save, true)} USDT`, tone: fmt.tone(x.save, fmt.money(x.save)),
      sub: `수수료 ${fmt.money(x.fee + x.save)} → ${fmt.money(x.fee)} · 거래당 순ROE ${fmt.num(x.save_roe * 100, 1, true)}%p · 순손익 합 `
        + `${fmt.money(x.pnl_paid, true)} → ${fmt.money(x.pnl, true)} USDT · ${fmt.int(x.n)}번`});
  return {known: true, rate: mk, ko: null,
    lines: [line("in", `진입만 지정가 (메이커 ${rateKo(mk)})`, b && b.maker_in), line("both", "청산까지 지정가 (최대치)", b && b.maker_both)]};
}

/** The paper bot's tiles at its assumed rates (the server's fees.paper). */
export function paperFeeTiles(pa) {
  if (!pa || pa.state !== "ok" || !pa.measured) return [];
  const share = has(pa.fee_share) ? pa.fee_share + (has(pa.slip_share) ? pa.slip_share : 0) : null;
  return [
    {id: "per", k: "거래당 순ROE", v: `${fmt.pct(pa.before_roe, 1)} → ${fmt.pct(pa.net_roe, 1)}`, tone: fmt.tone(pa.net_roe, fmt.pct(pa.net_roe, 1)),
      sub: "비용 전 → 순"},
    {id: "fee", k: "수수료 (가정)", v: ptsKo(pa.fee_roe), tone: "", sub: `${fmt.money(pa.fee)} USDT · 테이커 ${rateKo(pa.taker)} 양쪽`},
    {id: "slip", k: "미끄러짐 (가정)", v: ptsKo(pa.slip_roe), tone: "", sub: `${fmt.money(pa.slip)} USDT · 한쪽 ${rateKo(pa.slip_rate)}`},
    {id: "share", k: "비용이 가져간 몫", v: has(share) ? fmt.pct(share, 0, false) : has(pa.before) ? "이익 없음" : "—", tone: "",
      sub: shareWords(pa.before, pa.fee, pa.slip)},
  ];
}

/** The documented rates of the exchanges on the page (each once): [{id, name, taker, maker, src}]. */
export function rateRows(f) {
  const seen = new Set();
  return ((f && f.execs) || []).filter((x) => x.rates && !seen.has(x.exchange) && seen.add(x.exchange)).map((x) => {
    const r = x.rates;
    return {id: x.id, name: x.name_ko || acctKo(x.id), taker: `테이커 ${rateKo(r.taker)}${has(r.taker_disc) ? ` (할인 ${rateKo(r.taker_disc)})` : ""}`,
      maker: `메이커 ${rateKo(r.maker)}`, src: [r.src_ko, r.src].filter(Boolean).join(" · ")};
  });
}

/** The replay's costs a trade in one line (7/1~10/20, 가상), null without the file. */
export function replayFeeKo(rp) {
  if (!rp || rp.state !== "ok") return null;
  const md = (s) => (s ? s.slice(5).split("-").map(Number).join("/") : "?");
  return `재현(${md((rp.window_kst || [])[0])}~${md((rp.window_kst || [])[1])}, 가상): 비용 전 거래당 ${fmt.pct(rp.before, 1)} → `
    + `미끄러짐 ${ptsKo(rp.slip)} · 수수료 ${ptsKo(rp.fee)} → 순 ${fmt.pct(rp.net, 1)}${has(rp.lev_mean) ? ` (평균 ${fmt.num(rp.lev_mean, 0)}배)` : ""}`;
}

// ================================================================ the view
/** costView(ctx) -> {el, set()}: its own endpoint, read now and every 30 s. */
export function costView(ctx) {
  const st = {d: null, okAt: 0, sig: "", acct: local.get("lbk-acct", "bybit")};
  if (!EX.includes(st.acct)) st.acct = "bybit";
  const stateSlot = h("div", {class: "lb-slot"});
  const paperSlot = h("div", {class: "lb-slot"});
  const cards = h("div", {class: "lbk-cards"});
  const seg = ui.seg(EX.map((id) => ({id, label: acctKo(id)})), st.acct, (id) => { st.acct = id; local.set("lbk-acct", id); drawList(true); },
    {label: "실행기 고르기"});
  const judge = h("div", {class: "lbk-judge"});
  const listSum = h("div", {class: "lbk-lsum"});
  const listSlot = h("div", {class: "lb-slot"});
  const listHead = h("div", {class: "lbk-row lbk-rhead", "aria-hidden": "true", hidden: true}, h("span", null, "닫힌 때"), h("span", null, "코인 · 매매법 · 청산"),
    ...["페이퍼 ×비율", "실거래", "차이", "미끄러짐", "수수료"].map((t) => h("span", {class: "lbk-rv"}, t)));
  const pg = ui.pager({size: 10, row: (r) => rowOf(r), empty: () => (st.d ? ui.empty(EMPTY_KO) : motion.shimmer(3))});
  st.span = local.get("lbk-fee-span", "since");
  const feeSeg = ui.seg(FEE_SPANS, st.span, (id) => { st.span = id; local.set("lbk-fee-span", id); drawFees(); }, {label: "기간 고르기"});
  const feeBox = h("div", {class: "lbk-fee"});
  const body = h("div", {class: "lbk-body stack"},
    h("div", {class: "lbk-intro"}, h("b", null, "실거래(진짜 돈)는 페이퍼(연습)보다 얼마나 덜 버나"),
      h("span", {class: "muted"}, " · 같은 거래끼리 견줘요: 페이퍼 손익을 실거래 크기로 줄여서 (코인·방향이 같고 진입이 5분 안)")),
    paperSlot, cards,
    ui.card({title: "수수료 줄이기", sub: "실거래 체결로 잰 수수료·미끄러짐 · 지정가였다면 (가상)", cls: "lbk-feecard", acts: [feeSeg]}, feeBox),
    ui.card({title: "진입 방식 판단", sub: "페이퍼 체결을 따라가기 vs 신호 때 바로 들어가기 · 숫자만", cls: "lbk-jcard"}, judge),
    ui.card({title: "최근 실거래", sub: "닫힌 거래 · 새것부터 10개씩 · 한국 시간", cls: "lbk-listcard", acts: [seg]}, listSlot, listSum,
      listHead, pg.el),
    h("div", {class: "lb-foot"}, ui.assumeLive("바이비트 · WOO X Pro · ≈ = 체결 기록 전 지갑 변화로 어림"),
      ui.assumeLine(["closed"], "페이퍼(연습) 손익은 실거래 크기(설정의 크기 비율)로 줄여 견줌")));
  const el = h("div", {class: "lbk stack"}, stateSlot, body);

  const usd = (x, est) => (has(x) ? `${fmt.money(x, true)}${est ? "≈" : ""}` : "—");
  function tile(t) {
    return h("div", {class: ["lbk-tile", "k-" + t.id]}, h("span", {class: "k"}, t.k), h("b", {class: ["num", t.tone]}, t.v), h("span", {class: "s"}, t.sub));
  }
  function bars(a) {
    const items = pairBars(a.rows, BARS_N);
    if (!items.length) return h("p", {class: "lbk-nobar"}, "짝 맞춘 거래가 생기면 거래마다 막대 두 개가 그려져요 (페이퍼 · 실거래)");
    const box = h("div", {class: "lbk-bars"});
    const draw = () => {
      const W = Math.max(260, Math.round(box.clientWidth || 520));
      const g = barGeom(items, W, 150);
      put(box, s("svg", {class: "lbk-svg", viewBox: `0 0 ${W} ${g.H}`, width: W, height: g.H, role: "img",
        "aria-label": `최근 ${items.length}번: 페이퍼(크기 맞춤)와 실거래 손익`},
      s("line", {class: "zero", x1: g.pad.l, x2: W - g.pad.r, y1: f1(g.zero), y2: f1(g.zero)}),
      g.bars.map((b) => s("g", {class: "pair"},
        s("title", null, `${fmt.kst(b.t)} ${fmt.coin(b.sym)} ${fmt.sideKo(b.side)} · 페이퍼(크기 맞춤) ${fmt.money(b.paper, true)} · 실거래 ${usd(b.live, b.est)} · 차이 ${fmt.money(b.diff, true)}`),
        s("rect", {class: "hit", x: f1(b.cx - g.gw / 2), y: 0, width: f1(g.gw), height: g.H}),
        s("rect", {class: ["p", b.paper >= 0 ? "up" : "down"], x: f1(b.p.x), y: f1(b.p.y), width: f1(b.p.w), height: f1(b.p.h), rx: 1.5}),
        s("rect", {class: ["l", b.live >= 0 ? "up" : "down", b.est ? "est" : ""], x: f1(b.l.x), y: f1(b.l.y), width: f1(b.l.w), height: f1(b.l.h), rx: 1.5})))));
    };
    box.redraw = draw;
    const sm = sumPairs(items);
    return h("div", {class: "lbk-chart"},
      h("div", {class: "lbk-ch"}, h("span", {class: "lbk-ct"}, `최근 ${fmt.int(sm.n)}번 · 거래마다`),
        h("span", {class: "lbk-lg"}, h("i", {class: "p", "aria-hidden": "true"}), "페이퍼(크기 맞춤)"), h("span", {class: "lbk-lg"}, h("i", {class: "l", "aria-hidden": "true"}), "실거래")),
      box,
      h("p", {class: "lbk-sum"}, "합: 페이퍼 ", h("b", {class: ["num", fmt.tone(sm.paper, fmt.money(sm.paper))]}, fmt.money(sm.paper, true)),
        " → 실거래 ", h("b", {class: ["num", fmt.tone(sm.live, fmt.money(sm.live))]}, fmt.money(sm.live, true)),
        " · 차이 ", h("b", {class: ["num", fmt.tone(sm.diff, fmt.money(sm.diff))]}, fmt.money(sm.diff, true)), " USDT"));
  }
  function coinsEl(a) {
    if (!a.coins || !a.coins.length) return null;
    return h("div", {class: "lbk-sub"}, h("h3", {class: "lbk-h3"}, "코인별 (짝 맞춘 거래)"),
      h("div", {class: "lbk-coins", role: "list"},
        h("div", {class: "lbk-crow head", "aria-hidden": "true"}, h("span", null, "코인"), h("span", null, "거래"), h("span", null, "미끄러짐"), h("span", null, "차이 USDT")),
        a.coins.map((c) => {
          const sl = slipWords(c.slip_avg);
          return h("div", {class: "lbk-crow", role: "listitem"}, h("b", null, fmt.coin(c.symbol)), h("span", {class: "num"}, `${fmt.int(c.n)}번`),
            h("span", {class: ["num", sl.tone], title: sl.ko}, sl.text), h("b", {class: ["num", fmt.tone(c.diff, fmt.money(c.diff))]}, usd(c.diff)));
        })));
  }
  function missedEl(a) {
    const paperOk = st.d && st.d.paper && st.d.paper.state === "ok";
    const tot = missedTotal(a);
    const mx = Math.max(1, ...(a.missed || []).map((m) => m.n));
    return h("div", {class: "lbk-sub"}, h("h3", {class: "lbk-h3"}, "따라가지 못한 페이퍼 거래", paperOk && tot ? h("span", {class: "num lbk-mt"}, ` ${fmt.int(tot)}번`) : null),
      !paperOk ? ui.note("페이퍼 기록이 없어서 알 수 없어요")
        : !tot ? h("p", {class: "lbk-none"}, "놓친 페이퍼 거래 없음 (실행기가 켜진 뒤)")
          : h("div", {class: "lbk-miss", role: "list"}, a.missed.map((m) => h("div", {class: "lbk-mrow", role: "listitem"},
            h("span", {class: "lbk-mk"}, m.ko), h("span", {class: "lbk-mbar"}, h("i", {style: {width: `${((m.n / mx) * 100).toFixed(1)}%`}})),
            h("b", {class: "num"}, `${fmt.int(m.n)}번`)))));
  }
  function gapsEl(a) {
    const g = a.gaps;
    if (!g) return null;
    if (g.state !== "ok") return h("div", {class: "lbk-sub"}, h("h3", {class: "lbk-h3"}, "체결 비교"), sourceState(g, "체결 기록"));
    return h("div", {class: "lbk-sub lbk-gaps"}, h("h3", {class: "lbk-h3"}, "체결 비교", h("span", {class: "num lbk-mt"}, ` ${fmt.int(g.matched)}번 짝`)),
      h("div", {class: "lbk-tiles"}, gapTiles(g).map(tile)),
      h("p", {class: "lbk-gnote"}, "차이 = 실거래 체결가 − 페이퍼 체결가 (페이퍼 체결가에는 미끄러짐 0.02%가 이미 들어 있어요) · 순ROE = 차이 × 그 거래의 배수"));
  }
  function judgeEl(d) {
    const j = d.entry_judge;
    if (!j) return ui.note("서버가 진입 방식 숫자를 보내지 않았어요");
    const need = j.need || [10, 20];
    return [h("div", {class: "lbk-jrows", role: "list"}, (j.rows || []).map((r) => {
      const w = judgeRow(r, need);
      if (r.state && r.state !== "ok") return h("div", {class: "lbk-jrow", role: "listitem"}, acctTag(r.id), sourceState({state: r.state}, `${acctKo(r.id)} 실행기 DB`));
      return h("div", {class: "lbk-jrow", role: "listitem"}, acctTag(r.id),
        h("span", {class: "lbk-jn"}, h("b", {class: "num"}, `${fmt.int(w.n)}번`), h("small", null, ` / ${fmt.int(need[0])}~${fmt.int(need[1])}번 잼`)),
        h("span", {class: "lbk-jbar", role: "img", "aria-label": `${fmt.int(w.n)} / ${fmt.int(need[1])}`},
          h("i", {style: {width: `${Math.round(w.pct * 1000) / 10}%`}}), h("em", {style: {left: `${Math.round((need[0] / need[1]) * 1000) / 10}%`}})),
        h("span", {class: ["lbk-jko", w.roe != null && w.roe < 0 ? "down" : w.roe != null && w.roe > 0 ? "up" : ""]}, w.ko),
        r.entry_source ? h("small", {class: "lbk-jsrc"}, `지금: ${r.entry_source === "paper" ? "페이퍼 체결을 따라감" : "신호 때 바로 들어감"}`) : null);
    })), h("p", {class: "lbk-jwho"}, j.who_ko || "판단은 두 분이 해요")];
  }
  function exCard(id) {
    const a = (st.d.accts || {})[id];
    const head = [acctTag(id), h("span", {class: "lbk-real"}, "실거래 · 진짜 돈")];
    if (!a || a.state !== "ok") {
      return h("section", {class: ["card", "lbk-card", "off", "lbk-a-" + id], "aria-label": acctKo(id)},
        h("div", {class: "lbk-head"}, ...head), sourceState(a, `${acctKo(id)} 실행기 DB`));
    }
    const top = h("div", {class: "lbk-head"}, ...head,
      h("span", {class: "lbk-match", title: "페이퍼에 같은 거래(같은 코인·방향, 진입 5분 안)가 있는 실거래"}, "짝 맞춘 거래 ",
        h("b", {class: "num"}, `${fmt.int(a.matched)} / ${fmt.int(a.n)}`)));
    if (!a.n) {
      return h("section", {class: ["card", "lbk-card", "nolive", "lbk-a-" + id], "aria-label": acctKo(id)}, top,
        h("div", {class: "lbk-wait"}, h("b", null, "실거래 거래가 아직 없어요"), h("span", null, "첫 거래가 닫히면 채워져요")), missedEl(a));
    }
    const dt = a.diff_total, dtTxt = has(dt) ? fmt.money(dt, true) : "—";
    const hero = h("div", {class: ["lbk-hero", fmt.tone(dt, dtTxt)]},
      h("span", {class: "k"}, "실거래 − 페이퍼(크기 맞춤) · 짝 맞춘 거래 합"),
      h("div", {class: "lbk-big"}, h("b", {class: "num"}, dtTxt), h("span", {class: "u"}, has(dt) ? "USDT" : "짝 맞춘 거래 없음")),
      h("span", {class: "s"}, "거래당 ", h("b", {class: ["num", fmt.tone(a.diff_avg, fmt.money(a.diff_avg))]}, has(a.diff_avg) ? `${fmt.money(a.diff_avg, true)} USDT` : "—"),
        has(a.qty_scale) ? ` · 페이퍼 크기 × ${fmt.num(a.qty_scale, 2)}` : "",
        has(dt) ? (dt < 0 ? " · 실거래가 덜 벌었어요" : dt > 0 ? " · 실거래가 더 벌었어요" : "") : ""));
    return h("section", {class: ["card", "lbk-card", "lbk-a-" + id], "aria-label": acctKo(id)}, top, hero,
      h("div", {class: "lbk-tiles"}, costTiles(a).map(tile)), gapsEl(a),
      a.est_n ? h("p", {class: "lbk-est"}, `≈ 체결 기록 전이라 지갑 변화로 어림한 거래 ${fmt.int(a.est_n)}개 (체결을 읽으면 정확한 값으로 바뀌어요)`) : null,
      bars(a), coinsEl(a), missedEl(a));
  }
  function rowOf(r) {
    const sl = slipWords(r.slip_vs_paper);
    return h("div", {class: ["lbk-row", r.est ? "est" : ""], role: "listitem"},
      h("span", {class: "lbk-rt num muted"}, fmt.kst(r.exit_time)),
      h("span", {class: "lbk-rc"}, h("b", null, fmt.coin(r.symbol)), ui.sideTag(r.side),
        h("span", {class: "lbk-rs muted"}, r.strategy_id ? `${fmt.stratKo(r.strategy_id)} · ${fmt.tfKo(r.timeframe)}` : "짝 페이퍼 없음"),
        r.reason_ko ? h("span", {class: "lbk-rr"}, r.reason_ko) : null),
      h("span", {class: "lbk-rv"}, h("small", null, "페이퍼"), h("b", {class: "num"}, usd(r.paper_scaled))),
      h("span", {class: "lbk-rv"}, h("small", null, "실거래"), h("b", {class: ["num", fmt.tone(r.pnl, fmt.money(r.pnl))]}, usd(r.pnl, r.est))),
      h("span", {class: "lbk-rv"}, h("small", null, "차이"), h("b", {class: ["num", fmt.tone(r.diff, fmt.money(r.diff))]}, usd(r.diff))),
      h("span", {class: "lbk-rv"}, h("small", null, "미끄러짐"), h("b", {class: ["num", sl.tone], title: sl.ko}, sl.text)),
      h("span", {class: "lbk-rv"}, h("small", null, "수수료"), h("b", {class: "num"}, has(r.commission) ? fmt.money(r.commission) : r.est ? "체결 전" : "—")));
  }
  function drawList(user) {
    seg.set(st.acct);
    const d = st.d;
    const a0 = d && (d.accts || {})[st.acct];
    listHead.hidden = !(a0 && a0.state === "ok" && (a0.rows || []).length);
    if (!d) { put(listSlot); put(listSum); pg.set(undefined); return; }
    const a = (d.accts || {})[st.acct];
    if (!a || a.state !== "ok") { put(listSlot, sourceState(a, `${acctKo(st.acct)} 실행기 DB`)); put(listSum); pg.set([]); return; }
    put(listSlot);
    const rows = a.rows || [];
    put(listSum, rows.length ? [h("span", null, `${acctKo(st.acct)} 닫힌 거래 `), h("b", {class: "num"}, `${fmt.int(a.n)}번`),
      a.n > rows.length ? h("span", {class: "muted"}, ` · 새것 ${fmt.int(rows.length)}번만`) : null,
      h("span", {class: "muted"}, " · 페이퍼 = 짝 페이퍼 손익 × 크기 비율")] : null);
    pg.set(rows, !user);
  }
  // ---------------------------------------------------------------- 수수료 줄이기
  function feeRowEl(r) {
    const cell = (k, v, tone) => h("span", {class: "lbk-fv"}, h("small", null, k), h("b", {class: ["num", tone || ""]}, v));
    const pc = (x) => fmt.pct(x, 1);
    return h("div", {class: ["lbk-frow", r.measured ? "" : "unk"], role: "listitem"},
      h("span", {class: "lbk-rt num muted"}, fmt.kst(r.exit_time)),
      h("span", {class: "lbk-rc"}, h("b", null, fmt.coin(r.symbol)), ui.sideTag(r.side), has(r.leverage) ? h("span", {class: "muted"}, fmt.lev(r.leverage)) : null),
      r.measured
        ? [cell("비용 전", pc(r.before_roe), fmt.tone(r.before_roe, pc(r.before_roe))), cell("수수료", ptsKo(r.fee_roe)),
          cell("미끄러짐", ptsKo(r.slip_roe), r.slip_roe > 0 ? "down" : r.slip_roe < 0 ? "up" : ""), cell("순", pc(r.roe), fmt.tone(r.roe, pc(r.roe))),
          h("span", {class: "lbk-fs"}, shareWords(r.before, r.fee, r.slip))]
        : h("span", {class: "lbk-fs"}, r.why === "est" ? "체결 기록 전 · 지갑 변화로 어림한 거래라 비용을 못 나눠요"
          : "체결로 비용을 못 잼 (기준가가 없거나 체결 수량이 안 맞음)"));
  }
  function feeExEl(x, span) {
    // an executor on the other paper bot (owners 10/23, the server's since_ko): its "since" is that bot's, from its move
    const own = span === "since" && x.since_ko ? `${x.since_ko}${has(x.since_ms) ? ` (${fmt.kst(x.since_ms)})` : ""}` : null;
    const head = h("div", {class: "lbk-fhead"}, acctTag(x.id),
      h("span", {class: "lbk-real"}, x.state === "ok" && x.real === false ? "테스트넷 · 진짜 돈 아님" : "실거래 · 진짜 돈"),
      own ? h("small", {class: "muted"}, own) : null);
    const box = (...kids) => h("section", {class: ["lbk-fex", x.state === "ok" ? "" : "off", "lbk-a-" + x.id], "aria-label": acctKo(x.id)}, head, ...kids);
    if (x.state !== "ok") return box(sourceState(x, `${acctKo(x.id)} 실행기 DB`));
    const b = x[span];
    if (!b || !b.n) {
      return box(h("p", {class: "lbk-none"}, span !== "since" ? "닫힌 거래가 아직 없어요"
        : x.since_ko ? `${x.since_ko} 닫힌 거래가 아직 없어요` : "추세판단 봇 시작 뒤 닫힌 거래가 아직 없어요"));
    }
    const left = [b.est ? `지갑 변화로 어림한 거래 ${fmt.int(b.est)}번` : "", b.unmeasured ? `비용을 못 잰 거래 ${fmt.int(b.unmeasured)}번` : ""].filter(Boolean);
    const count = h("p", {class: "lbk-fcount"}, `닫힌 거래 ${fmt.int(b.n)}번 · 체결로 비용을 잰 거래 `, h("b", {class: "num"}, `${fmt.int(b.measured)}번`),
      left.length ? ` · ${left.join(" · ")}은 합에서 뺐어요` : "", " ", ui.smallSample(b.measured, (st.d.fees || {}).small_n || 20));
    if (!b.measured) return box(count, h("p", {class: "lbk-none"}, "체결 기록으로 비용을 잰 거래가 아직 없어요 (체결을 읽으면 채워져요)"));
    const mk = makerLines(b, x.rates);
    const mkEl = h("div", {class: "lbk-fmk"}, h("h3", {class: "lbk-h3"}, "지정가(메이커)로 들어갔다면 ", h("span", {class: "lbk-ftag"}, "가상")),
      mk.known ? h("div", {class: "lbk-tiles"}, mk.lines.map(tile)) : h("p", {class: "lbk-fno"}, mk.ko),
      mk.known && has(b.slip_in) ? h("p", {class: "lbk-gnote"}, `지정가가 그 가격에 채워지면 진입 미끄러짐(합 ${fmt.money(b.slip_in, true)} USDT)도 없겠지만, `
        + "그건 이 숫자에 넣지 않았어요 · 수수료만 바꾼 계산이에요") : null);
    const rows = b.rows || [];
    return box(count, h("div", {class: "lbk-tiles"}, feeTiles(b).map(tile)), mkEl,
      rows.length ? h("div", {class: "lbk-sub"}, h("h3", {class: "lbk-h3"}, "거래마다 (새것부터, 순ROE)"),
        h("div", {class: "lbk-frows", role: "list"}, rows.map(feeRowEl))) : null);
  }
  function feePaperEl(pa, f) {
    const head = h("div", {class: "lbk-fhead"}, acctTag("paper"), h("span", {class: "lbk-fpk"}, "모의 · 가정 요율"),
      h("small", {class: "muted"}, f.since != null ? `${f.since_ko || "추세판단 봇 시작부터"}` : "전체 거래"));
    const box = (...kids) => h("section", {class: ["lbk-fex", "lbk-fpaper", pa && pa.state === "ok" ? "" : "off"], "aria-label": "페이퍼(연습)"}, head, ...kids);
    if (!pa || pa.state !== "ok") return box(sourceState(pa, "페이퍼 DB"));
    if (!pa.measured) return box(h("p", {class: "lbk-none"}, pa.n ? "비용을 나눌 숫자가 없는 거래뿐이에요" : "추세판단 봇 시작 뒤 닫힌 거래가 아직 없어요"));
    return box(h("p", {class: "lbk-fcount"}, `닫힌 거래 ${fmt.int(pa.measured)}번 `, ui.smallSample(pa.measured, f.small_n || 20)),
      h("div", {class: "lbk-tiles"}, paperFeeTiles(pa).map(tile)), h("p", {class: "lbk-gnote"}, pa.note_ko || ""));
  }
  function ratesEl(f) {
    const rows = rateRows(f);
    if (!rows.length) return null;
    return h("div", {class: "lbk-sub lbk-frates"}, h("h3", {class: "lbk-h3"}, "거래소 요율 (한쪽)"),
      h("div", {class: "lbk-frl", role: "list"}, rows.map((r) => h("div", {class: "lbk-frr", role: "listitem"}, h("b", null, r.name),
        h("span", {class: "num"}, r.taker), h("span", {class: ["num", /모름/.test(r.maker) ? "lbk-funk" : ""]}, r.maker), h("small", null, r.src)))),
      h("p", {class: "lbk-gnote"}, f.rates_ko || ""));
  }
  function drawFees() {
    const d = st.d;
    if (!d) { feeSeg.hidden = true; put(feeBox, motion.shimmer(3)); return; }
    const f = d.fees;
    if (!f) { feeSeg.hidden = true; put(feeBox, ui.note("서버가 수수료 숫자를 보내지 않았어요")); return; }
    const span = spanOf(f, st.span);
    feeSeg.hidden = f.since == null;
    feeSeg.set(span);
    const rp = replayFeeKo(f.replay);
    put(feeBox,
      h("p", {class: "lbk-fintro"}, span === "since" ? `${f.since_ko || "추세판단 봇 시작부터"} (${fmt.kst(f.since)}) 닫힌 거래` : (f.all_ko || "전체 거래"),
        h("span", {class: "muted"}, " · 거래소 체결 기록으로 잰 값 · 순ROE의 %p = 그 거래 증거금 대비")),
      f.not_trend_ko ? ui.note(f.not_trend_ko) : null,
      rp ? h("p", {class: "lbk-fref"}, rp) : null,
      h("div", {class: "lbk-fcards"}, (f.execs || []).map((x) => feeExEl(x, span)), feePaperEl(f.paper, f)),
      ratesEl(f),
      h("div", {class: "lbk-fwarn"}, h("p", null, f.limit_ko || ""), h("p", null, f.exit_ko || ""), h("b", null, f.who_ko || "")));
  }
  function draw() {
    const d = st.d;
    if (!d) { put(cards, motion.shimmer(4, true)); put(judge, motion.shimmer(2)); drawFees(); drawList(false); return; }
    const p = d.paper || {};
    put(paperSlot, p.state && p.state !== "ok" ? sourceState(p, "페이퍼 DB (짝 맞출 페이퍼 거래)") : null);
    put(cards, EX.map(exCard));
    drawFees();
    put(judge, judgeEl(d));
    cards.querySelectorAll(".lbk-bars").forEach((b) => b.redraw && b.redraw());
    drawList(false);
  }
  async function load() {
    let d;
    try { d = await ctx.api(COST_API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      // a refresh that fails keeps the last answer on screen, dimmed, with its age (never silently stale)
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      ui.dim(body, !!st.d);
      throw e;
    }
    if (!ctx.alive()) return;
    st.okAt = Date.now();
    put(stateSlot);
    ui.dim(body, false);
    const sig = JSON.stringify({...d, now_ms: 0});         // the same records again redraw nothing (the page stays put)
    if (st.d && sig === st.sig) return;
    st.d = d; st.sig = sig;
    draw();
  }
  draw();
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  if (typeof ResizeObserver === "function") {
    let w0 = 0;
    const ro = new ResizeObserver(() => {
      const w = cards.clientWidth;
      if (st.d && Math.abs(w - w0) > 8) { w0 = w; cards.querySelectorAll(".lbk-bars").forEach((b) => b.redraw && b.redraw()); }
    });
    ro.observe(cards);
    ctx.track(() => ro.disconnect());
  }
  return {el, set() {}};
}
