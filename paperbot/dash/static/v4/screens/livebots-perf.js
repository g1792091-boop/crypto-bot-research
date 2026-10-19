// 실거래 › 성적 (#/livebots/perf): how the three accounts are doing (/api/v4/livebots/perf). The rolling win share of the
// last 20 and 40 closed trades as a line against the start guide's reference lines (백테스트 91 % · 흔들기 시험 84~86 % ·
// 본전 약 78 %, all 참고: earlier tests, not a promise), the 40-trade checkpoint the owners set (나아가기 88 % 이상 늘리기
// 검토 / 82~88 % 지켜보기 / 82 % 미만 멈추고 다시 생각; nothing is judged before 40), and the record by strategy, coin,
// timeframe, 롱 / 숏 and Korea-time hour, each row with 표본 적음 under 20 (and under 40), and the coin-flip twin of the paper
// (참고: the same moments with a random side). Then 매매법 성적표 and 개선 후보 장부 (livebots-score.js: liveimprove's
// scorecard per strategy with its status words, and its improvement ledger with the exact commands, read-only).
// HONESTY: closed trades only; small samples say so; the reference lines are labelled 참고, and drawn only for the config
// they were made for (refs null + refs_ko, checkpoint.rule_ko: another config's, so neither the lines nor 88 / 82 %); no
// pass / fail word before 40 (the scorecard's words are liveimprove's own test against the backtest, not the 40-trade
// decision).
import {h, s, put, ui, fmt, local, motion} from "../core/pb.js";
import {acctKo, sourceState} from "./livebots-kit.js";
import {smallFloor} from "./livebots-calc.js";
import {scoreView, ledgerView} from "./livebots-score.js";

const IDS = ["paper", "bybit", "mexc"];
const REFRESH_MS = 60 * 1000;
const BREAK = [{id: "by_strategy", label: "매매법"}, {id: "by_coin", label: "코인"}, {id: "by_tf", label: "봉"}, {id: "by_side", label: "롱·숏"}, {id: "by_hour", label: "시간(한국)"}];
const LO = 0.5, HI = 1;

const keyKo = (b, k) => (b === "by_strategy" ? fmt.stratKo(k) : b === "by_coin" ? fmt.coin(k) : b === "by_tf" ? fmt.tfKo(k)
  : b === "by_side" ? fmt.sideKo(k) : b === "by_hour" ? `${String(k).padStart(2, "0")}시` : String(k));

/** The rolling win share chart (inline SVG drawn at the box's real width W, so its labels keep their token size): the 20 and
 *  40 lines and the reference lines. */
export function rollChart(acc, refs, W = 640) {
  const H = 220, pl = 40, pr = 8, pt = 10, pb = 22;
  const all = [...(acc.roll20 || []), ...(acc.roll40 || [])];
  if (!all.length) return null;
  const t0 = Math.min(...all.map((p) => p[0])), t1 = Math.max(...all.map((p) => p[0]));
  const X = (t) => pl + (t1 > t0 ? (t - t0) / (t1 - t0) : 1) * (W - pl - pr);
  const Y = (v) => pt + (1 - (Math.max(LO, Math.min(HI, v)) - LO) / (HI - LO)) * (H - pt - pb);
  const path = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
  const R = refs || {};
  const sh = R.shake || [];
  return s("svg", {class: "lb-roll", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": "최근 20번 · 40번 승률 흐름과 참고선"},
    [0.5, 0.6, 0.7, 0.8, 0.9, 1].map((v) => s("g", null, s("line", {class: "grid", x1: pl, x2: W - pr, y1: Y(v), y2: Y(v)}),
      s("text", {class: "ax", x: pl - 6, y: Y(v) + 4}, `${Math.round(v * 100)}%`))),
    sh.length === 2 ? s("rect", {class: "band", x: pl, width: W - pl - pr, y: Y(sh[1]), height: Math.max(1, Y(sh[0]) - Y(sh[1]))}) : null,
    R.backtest != null ? s("line", {class: "ref bt", x1: pl, x2: W - pr, y1: Y(R.backtest), y2: Y(R.backtest)}) : null,
    R.breakeven != null ? s("line", {class: "ref be", x1: pl, x2: W - pr, y1: Y(R.breakeven), y2: Y(R.breakeven)}) : null,
    (acc.roll40 || []).length ? s("path", {class: "r40", d: path(acc.roll40)}) : null,
    (acc.roll20 || []).length ? s("path", {class: "r20", d: path(acc.roll20)}) : null,
    s("text", {class: "ax", x: pl, y: H - 6}, fmt.mmdd(t0)), s("text", {class: "ax end", x: W - pr, y: H - 6}, fmt.mmdd(t1)));
}

/** perfView(ctx) -> {el, set()} */
export function perfView(ctx) {
  const st = {acct: local.get("lb-pacct", "paper"), brk: local.get("lb-pbrk", "by_strategy"), d: null, okAt: 0};
  if (!IDS.includes(st.acct)) st.acct = "paper";
  if (!BREAK.some((b) => b.id === st.brk)) st.brk = "by_strategy";
  const seg = ui.seg(IDS.map((id) => ({id, label: acctKo(id)})), st.acct, (id) => { st.acct = id; local.set("lb-pacct", id); draw(); }, {label: "계좌 고르기"});
  const bseg = ui.seg(BREAK, st.brk, (id) => { st.brk = id; local.set("lb-pbrk", id); drawBreak(true); }, {label: "나눠 보기", scroll: true});
  const stateSlot = h("div", {class: "lb-slot"});
  const head = h("div", {class: "lb-phead"});
  const chart = h("div", {class: "lb-rollbox"});
  const cp = h("div", {class: "lb-cp"});
  const flip = h("div", {class: "lb-flip"});
  const pg = ui.pager({size: 10, row: (r) => brow(r), empty: () => (st.d ? ui.empty("닫힌 거래가 아직 없어요") : motion.shimmer(3))});
  const legend = h("div", {class: "lb-legend", role: "list"});
  const score = scoreView(ctx), ledger = ledgerView();
  const el = h("div", {class: "lb-perf stack"},
    h("div", {class: "lb-tbar"}, seg), stateSlot,
    ui.card({title: "승률 흐름", sub: "최근 20번 · 40번 닫힌 거래의 이긴 비율", cls: "lb-rollcard"}, head, chart, legend),
    ui.card({title: "40번 판단까지", sub: "페이퍼 닫힌 거래 기준 · 두 분이 정하는 자리", cls: "lb-cpcard"}, cp),
    score.el, ledger.el,
    ui.card({title: "나눠 보기", sub: "표본 적음 = 20번 미만 (40번 미만도 조심)", cls: "lb-brkcard", acts: [bseg]}, pg.el),
    ui.card({title: "동전 쌍둥이 (참고)", sub: "같은 순간 같은 신호에 방향만 동전으로 정한 페이퍼 계좌", cls: "lb-flipcard"}, flip),
    h("div", {class: "lb-foot"}, ui.assumeLive("바이비트 · MEXC"), ui.assumeLine(["closed"], "페이퍼 · 동전 쌍둥이 · 매매법 성적표")));

  function brow(r) {
    const fl = smallFloor(r.trades);
    return h("div", {class: "lb-brow", role: "listitem"}, h("b", {class: "lb-bk"}, keyKo(st.brk, r.key)),
      h("span", {class: "num"}, `${fmt.int(r.trades)}번`), h("span", {class: "num"}, r.win_rate == null ? "—" : fmt.pct(r.win_rate, 0, false)),
      h("b", {class: ["num", fmt.tone(r.pnl)]}, fmt.money(r.pnl, true)), fl ? ui.smallSample(r.trades, fl) : h("span"));
  }
  function drawBreak(user) {
    const a = st.d && st.d.accts[st.acct];
    pg.set(a && a.state === "ok" ? a[st.brk] || [] : st.d ? [] : undefined, !user);
  }
  function draw() {
    seg.set(st.acct);
    const d = st.d;
    if (!d) { put(chart, motion.shimmer(3)); drawBreak(false); score.set(null); ledger.set(null); return; }
    score.set(d.scorecard || {state: "missing", reason_ko: "서버가 성적표를 보내지 않았어요"});
    ledger.set(d.ledger || {state: "missing", reason_ko: "서버가 장부를 보내지 않았어요"});
    const a = d.accts[st.acct];
    if (!a || a.state !== "ok") { put(stateSlot, sourceState(a, acctKo(st.acct))); put(head); put(chart); put(legend); drawBreak(false); }
    else {
      put(stateSlot);
      const x = a.stats, fl = smallFloor(x.trades);
      put(head, h("span", null, `${acctKo(st.acct)} · ${fmt.int(x.trades)}번 · 승률 `), h("b", null, x.win_rate == null ? "—" : fmt.pct(x.win_rate, 1, false)),
        " · 손익 ", h("b", {class: ["num", fmt.tone(x.pnl)]}, `${fmt.money(x.pnl, true)} USDT`), fl ? ui.smallSample(x.trades, fl) : null);
      const c = rollChart(a, d.refs, Math.max(280, Math.round(chart.clientWidth || 600)));
      put(chart, c || h("p", {class: "lb-flat"}, `최근 20번 승률은 닫힌 거래가 20번이 되면 그려져요 (지금 ${fmt.int(x.trades)}번)`));
      const R = d.refs || {};
      const li = (...k) => h("span", {class: "lb-li", role: "listitem"}, ...k);
      // no refs (refs_ko): the start guide's lines are another config's, so none is drawn or named
      put(legend, li(h("i", {class: "lb-key r20"}), "최근 20번"), li(h("i", {class: "lb-key r40"}), "최근 40번"),
        ...(d.refs ? [li(h("i", {class: "lb-key bt"}), `백테스트 ${fmt.pct(R.backtest, 0, false)}`),
          li(h("i", {class: "lb-key band"}), `흔들기 시험 ${fmt.pct((R.shake || [])[0], 0, false)}~${fmt.pct((R.shake || [])[1], 0, false)}`),
          li(h("i", {class: "lb-key be"}), `본전 약 ${fmt.pct(R.breakeven, 0, false)}`), li(ui.pill("", "ref"), " 지나간 시험의 숫자, 약속 아님")]
          : [li(ui.pill("", "ref"), ` ${d.refs_ko || "참고선 없음"}`)]));
    }
    const k = d.checkpoint;
    if (!k) put(cp, sourceState(d.accts.paper, "페이퍼 DB"));
    else {
      const pct = Math.min(1, k.n / k.trades);
      put(cp, h("div", {class: "lb-cpbar", role: "img", "aria-label": `${k.n} / ${k.trades}`}, h("i", {style: {width: `${(pct * 100).toFixed(1)}%`}})),
        h("p", {class: "lb-cpn"}, h("b", {class: "num"}, `${fmt.int(k.n)} / ${fmt.int(k.trades)}번`),
          k.ready ? h("span", null, ` · 마지막 40번 승률 ${fmt.pct(k.last_win_rate, 1, false)}`) : h("span", {class: "muted"}, ` · ${fmt.int(k.left)}번 남음`)),
        h("ul", {class: "lb-cprules"}, (k.rule_ko ? [["none", k.rule_ko]] : [["up", k.up_ko], ["mid", k.mid_ko], ["low", k.low_ko]])
          .map(([z, t]) => h("li", {class: ["lb-cpz", z, k.zone === z ? "on" : ""]}, t))),
        ui.note(k.ready ? "40번이 됐어요: 두 분이 정할 때예요 (이 화면은 숫자만 보여 드려요)"
          : `지금 승률 ${k.win_rate == null ? "—" : fmt.pct(k.win_rate, 1, false)}는 참고예요: 40번 전에는 판단하지 않아요`));
    }
    const f = d.flip, p = d.accts.paper;
    put(flip, f && p && p.state === "ok" ? [h("div", {class: "lb-recs"},
      h("div", {class: "lb-rec"}, h("b", null, "페이퍼"), ui.kv([["거래", fmt.int(p.stats.trades)], ["승률", p.stats.win_rate == null ? "—" : fmt.pct(p.stats.win_rate, 1, false)],
        ["손익", fmt.money(p.stats.pnl, true)]])),
      h("div", {class: "lb-rec"}, h("b", null, "동전 쌍둥이"), ui.kv([["거래", fmt.int(f.stats.trades)], ["승률", f.stats.win_rate == null ? "—" : fmt.pct(f.stats.win_rate, 1, false)],
        ["손익", fmt.money(f.stats.pnl, true)]]))),
      h("p", {class: "note"}, ui.pill("", "ref"), " 비교일 뿐 실력의 증거가 아니에요. 거래가 적을 때 차이는 우연일 수 있어요", ui.smallSample(p.stats.trades, 40))]
      : ui.notYet("수집 전", "동전 쌍둥이 기록이 아직 없어요"));
    drawBreak(false);
  }
  async function load() {
    try { st.d = await ctx.api("/api/v4/livebots/perf"); st.okAt = Date.now(); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      throw e;
    }
    if (ctx.alive()) draw();
  }
  draw();
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  if (typeof ResizeObserver === "function") {
    let w0 = 0;
    const ro = new ResizeObserver(() => { const w = chart.clientWidth; if (st.d && Math.abs(w - w0) > 8) { w0 = w; draw(); } });
    ro.observe(chart); ctx.track(() => ro.disconnect());
  }
  return {el, set() {}};
}
