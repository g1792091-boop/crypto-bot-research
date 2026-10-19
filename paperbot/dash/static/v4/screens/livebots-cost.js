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
  const body = h("div", {class: "lbk-body stack"},
    h("div", {class: "lbk-intro"}, h("b", null, "실거래(진짜 돈)는 페이퍼(연습)보다 얼마나 덜 버나"),
      h("span", {class: "muted"}, " · 같은 거래끼리 견줘요: 페이퍼 손익을 실거래 크기로 줄여서 (코인·방향이 같고 진입이 5분 안)")),
    paperSlot, cards,
    ui.card({title: "진입 방식 판단", sub: "페이퍼 체결을 따라가기 vs 신호 때 바로 들어가기 · 숫자만", cls: "lbk-jcard"}, judge),
    ui.card({title: "최근 실거래", sub: "닫힌 거래 · 새것부터 10개씩 · 한국 시간", cls: "lbk-listcard", acts: [seg]}, listSlot, listSum,
      listHead, pg.el),
    h("div", {class: "lb-foot"}, ui.assumeLive("바이비트 · MEXC · ≈ = 체결 기록 전 지갑 변화로 어림"),
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
  function draw() {
    const d = st.d;
    if (!d) { put(cards, motion.shimmer(4, true)); put(judge, motion.shimmer(2)); drawList(false); return; }
    const p = d.paper || {};
    put(paperSlot, p.state && p.state !== "ok" ? sourceState(p, "페이퍼 DB (짝 맞출 페이퍼 거래)") : null);
    put(cards, EX.map(exCard));
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
