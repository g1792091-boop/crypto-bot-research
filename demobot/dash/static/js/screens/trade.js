// #/trade/<account id>/<trade key> 거래 차트 (CONTRACT 8.6): one trade on the coin's candles. The window runs about
// 3 days before the entry to 1 day after the exit (or now); price lines for the entry, the stop and (fixed
// "익절 xR · 손절 yATR" exits only) the target; markers at the entry and the exit. Beside it every fact of the trade,
// the same entry's P&L on the other leverage lines, the measured cost and the market at entry.
// acct/<id>.json (the trade) + /api/bars (the candles; 30m bars are paired from 15m on the server).
// Round 5 stage 2: the rule bot's v4 chart / account trade look: the head card with the account's pixel character and
// timeframe chip, the result as LED digits (R and P&L), side / leverage / hold / reason chips; the facts in key-value
// blocks, the four leverage lines in the v4 table style.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {candleChart} from "../chart.js";
import {LEVS, reasonKo, sideKo, tfKo, targetR} from "../labels.js";

const ID_RE = /^[A-Za-z0-9-]{3,40}$/;
const DAY = 86400000;
const TF_MS = {"15m": 900000, "30m": 1800000};
const MAX_BARS = 3000;
const priceDec = (p) => { const a = Math.abs(Number(p) || 0); return a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1; };
const px = (p) => (fmt.bad(p) ? "—" : fmt.num(p, priceDec(p)));

export async function mount(el, ctx) {
  const id = ctx.params.arg || "";
  const key = ctx.params.arg2 || "";
  const FROM = {trades: ["#/trades", "← 거래 기록"], positions: ["#/positions", "← 포지션"], terminal: ["#/terminal", "← 터미널"]};
  const from = FROM[ctx.params.query.from];
  const back = h("a", {class: "btn-line", href: from ? from[0] : ctx.href("account", id)}, from ? from[1] : "← 계좌");
  ctx.setTitle("거래 차트");
  if (!ID_RE.test(id) || !key || key.length > 120) {
    el.append(ui.screenHead("거래 차트"), h("div", {class: "row wrap"}, back), ui.missing("이 거래의 주소"));
    return;
  }
  const head = ui.screenHead("거래 차트", "불러오는 중");
  const sub = head.querySelector(".sub");
  const say = h("div");
  const chartBox = h("div", {class: "dl-chart dl-tchart", role: "img", "aria-label": "거래 차트: 봉, 진입, 손절, 청산"});
  const chartNote = h("p", {class: "note"});
  const facts = h("div"), levBox = h("div"), costBox = h("div");
  let tf = null;
  const tfSeg = ui.seg([{id: "15m", label: "15분봉"}, {id: "30m", label: "30분봉"}], "15m", (v) => { tf = v; drawBars(); }, {label: "봉"});
  const legend = h("div", {class: "dl-legend"},
    h("span", {class: "dl-lg"}, h("i", {class: "dl-li-acc"}), "진입"),
    h("span", {class: "dl-lg"}, h("i", {class: "dl-li-down dl-dash"}), "손절"),
    h("span", {class: "dl-lg"}, h("i", {class: "dl-li-up dl-dash"}), "목표 (고정 익절만)"),
    h("span", {class: "dl-lg"}, h("i", {class: "dl-li-ink dl-dot"}), "청산"));
  const chartCard = ui.card({plate: "차트", sub: "진입 3일 전부터 청산 1일 뒤까지 · 한국 시간", acts: tfSeg}, chartBox, legend, chartNote);
  const factRow = h("div", {class: "s2a-wrap even"},
    ui.card({plate: "이 거래"}, facts),
    h("div", {class: "stack"}, ui.card({plate: "배수마다", sub: "같은 진입을 배수 4줄이 각자 냅니다"}, levBox),
      ui.card({plate: "비용과 시장"}, costBox)));
  chartCard.hidden = true;                      // shown once the trade is found
  factRow.hidden = true;
  el.append(head, h("div", {class: "row wrap"}, back, h("a", {class: "btn-line", href: ctx.href("account", id)}, "이 계좌 보기")),
    say, chartCard, factRow,
    ui.note("모의 거래입니다. 봉은 바이낸스 실제 시세(15분봉, 30분봉은 15분봉 두 개를 합친 것)입니다. 주문은 넣지 않습니다."));

  let acct;
  try { acct = await ctx.api(`/api/account/${encodeURIComponent(id)}`); } catch (e) {
    if (e && e.name === "AbortError") return;
    put(say, ui.errorBox(e, () => location.reload()));
    return;
  }
  if (isMissing(acct)) { put(say, ui.missing("이 계좌의 자료")); return; }
  const trades = acct.trades || [];
  // a position (positions.json has no key) comes with its derived key and its entry time (?at=): the time decides
  const at = Number(ctx.params.query.at), kp = key.split("|");
  const t = trades.find((x) => x.key === key) || (Number.isFinite(at) && at > 0
    ? trades.find((x) => Number(x.entry_ms) === at && x.coin === kp[0] && String(x.side) === kp[3] && String(x.L) === kp[4]) : undefined);
  sub.textContent = acct.name || id;
  if (!t) {
    put(say, ui.card({}, h("p", {class: "dl-vline"}, "기록 없음"),
      ui.note("이 거래는 계좌 파일에 더 이상 없습니다 (최근 600건만 남깁니다). 계좌 화면에서 다른 거래를 골라 보세요.")));
    return;
  }
  ctx.setTitle(`${fmt.coin(t.coin)} ${sideKo(t.side)} · ${acct.name || id}`);
  chartCard.hidden = false;
  factRow.hidden = false;
  tf = acct.tf === "30m" ? "30m" : "15m";
  tfSeg.set(tf);

  const open = t.status === "open";
  const tgtR = targetR(t.exit_ko);
  const dist = Math.abs(Number(t.entry) - Number(t.stop));
  const target = tgtR != null && Number.isFinite(dist) ? Number(t.entry) + Number(t.side) * tgtR * dist : null;
  const win = Number(t.pnl) > 0;
  const holdS = ((open ? Date.now() : Number(t.exit_ms)) - Number(t.entry_ms)) / 1000;
  const rT = fmt.r(t.R), pT = fmt.money(t.pnl, true);
  const fig = {id, name: acct.name || id, kind: acct.kind, tf: acct.tf, short: acct.short};
  put(say, ui.card({hero: true, plate: `${fmt.coin(t.coin)} · ${sideKo(t.side)} · ${fmt.lev(t.L)}`, cls: "dl-tsay s2a-tsay"},
    h("div", {class: "s2a-candn"}, h("a", {class: "s2a-nm", href: ctx.href("account", id), title: id}, K4.acctFig(fig, 26), K4.acctName(fig)),
      h("span", {class: ["side", Number(t.side) > 0 ? "long" : "short"]}, sideKo(t.side)),
      h("span", {class: "dl-levtag", dataset: {lev: t.L}}, fmt.lev(t.L)),
      open ? ui.pill("열림", "accent") : ui.pill(reasonKo(t.reason), win ? "good" : "bad"),
      ui.pill(`보유 ${fmt.dur(holdS)}`, "thin")),
    h("p", {class: "dl-vline"}, open
      ? `${fmt.kst(t.entry_ms)}에 ${sideKo(t.side)}으로 들어가 아직 열려 있습니다.`
      : `${fmt.kst(t.entry_ms)}에 ${sideKo(t.side)}으로 들어가 ${fmt.kst(t.exit_ms)}에 ${reasonKo(t.reason)}(으)로 나왔습니다.`),
    h("div", {class: "pnl s2a-ledbox"},
      h("div", null, h("span", {class: "k"}, open ? "지금 R" : "결과 R"), h("b", {class: ["led-num", "num", fmt.tone(t.R, rT)]}, rT)),
      h("div", {class: "r"}, h("span", {class: "k"}, open ? "미실현 손익" : "손익"), h("b", {class: ["led-sm", "num", fmt.tone(t.pnl, pT)]}, pT)))));

  const pct = (a, b) => (fmt.bad(a) || fmt.bad(b) || Number(b) === 0 ? null : (Number(a) - Number(b)) / Number(b) * 100);
  const stopPct = pct(t.stop, t.entry);
  put(facts, ui.kv([
    ["코인", fmt.coin(t.coin)],
    ["방향", sideKo(t.side)],
    ["배수", fmt.lev(t.L)],
    ["들어간 때", fmt.kst(t.entry_ms)],
    ["진입가", px(t.entry)],
    ["손절가", stopPct == null ? px(t.stop) : `${px(t.stop)} (${fmt.pct(stopPct, true, 2)})`],
    target != null ? ["목표가", `${px(target)} (${fmt.num(tgtR, 1)}R)`] : ["목표가", "없음 (고정 익절이 아님)"],
    ["나간 때", open ? "아직 열림" : fmt.kst(t.exit_ms)],
    ["청산가", open ? "—" : px(t.exit)],
    ["이유", open ? "열림" : reasonKo(t.reason)],
    ["R", rT],
    ["손익", pT],
    ["증거금", fmt.money(t.margin)],
    ["포지션 크기", fmt.money(t.notional)],
    ["수수료·슬리피지", fmt.money(t.fee)],
    ["펀딩", open ? "열린 동안은 0" : fmt.money(t.funding, true)],
    ["설정", t.setting_ko || "—"],
    ["청산 방식", t.exit_ko || "—"],
  ]));

  // the same entry on the four lines: the key without its "|L" end
  const stem = String(t.key).split("|").slice(0, 4).join("|");
  const same = Object.fromEntries(trades.filter((x) => String(x.key).split("|").slice(0, 4).join("|") === stem).map((x) => [String(x.L), x]));
  put(levBox, ui.table([
    {label: "배수", l: true, get: (L) => h("span", {class: "dl-levtag", dataset: {lev: L}}, `${L}배`)},
    {label: "손익", get: (L) => { const x = same[L]; if (!x) return h("span", {class: "muted"}, "안 들어감"); const v = fmt.money(x.pnl, true); return ui.signed(v, fmt.tone(x.pnl, v)); }},
    {label: "증거금 대비", get: (L) => { const x = same[L]; if (!x) return "—"; const v = fmt.ratio(x.roe); return ui.signed(v, fmt.tone(x.roe, v)); }},
    {label: "이유", get: (L) => (same[L] ? (same[L].status === "open" ? "열림" : reasonKo(same[L].reason)) : "—")},
  ], LEVS.map(String), {cls: "s2a-tbl", rowCls: (L) => (String(t.L) === L ? "dl-marked" : "")}),
  ui.note("안 들어감 = 그 배수에서는 진입 검사(강제청산 여유·증거금·코인당 1개)에 걸려 건너뛰었거나, 계좌 파일의 최근 600건 밖입니다."));

  const maker = t.through_bps != null || t.maker === true;
  const costRow = maker
    ? (t.through_bps == null ? "기록 없음" : Number(t.through_bps) < 1
      ? `지정가 진입: 봉이 지정가를 ${fmt.num(t.through_bps, 2)}bp만 넘음 (닿기만 함: 실제로는 체결이 안 됐을 수 있음)`
      : `지정가 진입: 봉이 지정가를 ${fmt.num(t.through_bps, 1)}bp 넘어감 (체결됐다고 봐도 됨)`)
    : t.cost_bps == null ? "기록 없음 (호가를 재기 전 거래이거나 아직 준비 중)"
      : `${fmt.num(t.cost_bps, 2)}bp · 가정 2bp보다 ${Number(t.cost_bps) > 2 ? "비쌈" : "쌈"} (${fmt.num(Number(t.cost_bps) - 2, 2, true)}bp)`;
  put(costBox, ui.kv([
    [maker ? "체결 확인" : "실제 진입 비용", costRow],
    ["들어갈 때 시장", ui.regimeChips(t.trend, t.vol)],
  ]), ui.note("실제 진입 비용 = 그 크기의 시장가 주문이 호가창에서 낸 비용 (스프레드 절반 포함). 봇은 한쪽에 2bp(0.02%)를 가정합니다."));

  // ---------------------------------------------------------------- the candles
  let chart = null;
  const t0 = Number(t.entry_ms) - 3 * DAY;
  // the server clamps the range to its file, so the browser's clock never empties the window
  const t1 = (open ? Math.max(Date.now(), Number(t.entry_ms)) : Number(t.exit_ms)) + DAY;
  async function drawBars() {
    let useTf = tf;
    if ((t1 - t0) / TF_MS[useTf] > MAX_BARS && useTf === "15m") { useTf = "30m"; tfSeg.set("30m"); }
    let d;
    try {
      d = await ctx.api(`/api/bars?${new URLSearchParams({coin: t.coin, tf: useTf, from: String(Math.max(0, Math.floor(t0))), to: String(Math.floor(t1))})}`);
    } catch (e) {
      if (e && e.name === "AbortError") return;
      put(chartBox, ui.errorBox(e, drawBars));
      return;
    }
    if (isMissing(d) || !d.bars || !d.bars.length) {
      if (chart) { chart.dispose(); chart = null; }
      chartBox.classList.add("is-empty");
      legend.hidden = true;
      put(chartBox, h("div", {class: "dl-missing"}, h("b", null, "준비 중"), h("span", null, " · 이 코인의 봉 파일이 아직 없거나 이 기간의 봉이 없습니다.")));
      chartNote.textContent = "";
      return;
    }
    chartBox.classList.remove("is-empty");
    legend.hidden = false;
    try {
      if (!chart) { put(chartBox); chart = await candleChart(chartBox); ctx.signal.addEventListener("abort", () => chart && chart.dispose()); }
      if (!ctx.alive()) return;
      chart.set(d.bars, {side: t.side, entry: t.entry, stop: t.stop, target, exit: open ? null : t.exit, entry_ms: t.entry_ms,
        exit_ms: open ? null : t.exit_ms, win, exit_label: open ? "" : reasonKo(t.reason)});
    } catch (e) {
      put(chartBox, ui.empty("차트를 그리지 못했습니다."));
      return;
    }
    chartNote.textContent = `${tfKo(useTf)}봉 ${fmt.int(d.n)}개 · ${fmt.kst(d.from_ms)} ~ ${fmt.kst(d.to_ms)}`
      + (d.truncated ? " · 봉이 많아 최근 것만 보입니다" : "") + " · 끌어서 앞뒤를 볼 수 있습니다.";
  }
  await drawBars();
  return () => { if (chart) chart.dispose(); };
}
