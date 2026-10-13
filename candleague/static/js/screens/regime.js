// #/regime 시장 국면: the market state the league's two gates look at, computed in the BROWSER from /api/klines (one 4-hour request per coin; no server change, no snapshot block).
//   g1 (candleague/rulex.py gate_g1): the BTC 4h trend = the last CLOSED BTC 4h bar's close against its EMA50 (pandas ewm span 50, adjust=False): above = 상승, below = 하락, equal = 횡보;
//      a long needs 상승, a short needs 하락 (the first 50 bars are cold: unknown).
//   g2 (gate_g2): the ATR% (Wilder ATR14 / close) of the last closed bar against its last 200 bars, itself included, ties not counted: between the 20% and 80% percentile = 보통 범위.
// The league applies g2 on each PICK's own chart (15m .. 4h); this screen reads the 4h chart of each coin, so it is the market's state, not a pick's exact gate. Words, not colour alone;
// a missing number is "—"; an unreachable or switched-off price feed is a calm box with a retry, never an error page. No advice.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {hero, legend, ruleBox} from "./kit4.js";

export const css = ["scr/kinds.css", "scr/s4.css"];
export const COINS = ["BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD"];
export const EMA_N = 50, WINDOW = 200, LO = 0.2, HI = 0.8, ATR_N = 14, TF_MS = 4 * 3600 * 1000, BARS = 300, POLL_MS = 300000;
export const RULES = [
  "무엇을 보여 주나: 이 리그의 두 필터(g1 · g2)가 보는 시장 상태를 지금 시세로 보여 줍니다. 숫자만 보여 주고 무엇을 하라는 말은 없습니다.",
  `g1 BTC 추세: 마지막으로 닫힌 BTC 4시간 봉의 종가가 EMA${EMA_N}보다 위면 상승, 아래면 하락입니다. 롱은 상승일 때만, 숏은 하락일 때만 들어갑니다.`,
  `g2 변동성: 마지막 닫힌 4시간 봉의 ATR%가 최근 ${WINDOW}봉 가운데 하위 ${LO * 100}%에서 상위 ${(1 - HI) * 100}% 사이(보통 범위)일 때만 들어갑니다.`,
  "리그의 g2는 각 전략이 쓰는 차트(15분~4시간)로 계산합니다. 여기서는 코인마다 4시간 봉으로 계산하므로 시장의 대략적인 상태입니다.",
];
const num = (x) => (fmt.bad(x) ? null : Number(x));

// ---------------------------------------------------------------- the two numbers (pure; the tests compare them with rulex.py)
/** The closed bars of a /api/klines answer: columns {t, o, h, l, c}; the newest bar is dropped while it is still forming (its open + 4h is after ``nowMs``). */
export function closedBars(d, nowMs) {
  const b = d && d.bars;
  if (!b || !Array.isArray(b.t)) return null;
  const n = b.t.length;
  const col = (k) => (Array.isArray(b[k]) && b[k].length === n ? b[k].map(Number) : null);
  const out = {t: b.t.map(Number), h: col("h"), l: col("l"), c: col("c")};
  if (!out.h || !out.l || !out.c || !n) return null;
  const keep = n - (out.t[n - 1] + TF_MS > nowMs ? 1 : 0);
  return {t: out.t.slice(0, keep), h: out.h.slice(0, keep), l: out.l.slice(0, keep), c: out.c.slice(0, keep)};
}
/** g1: {sign (1 / -1 / 0 / null when cold), close, ema, gap}. EMA(span 50, adjust=False) over all the closes; the first EMA_N bars are cold (rulex.gate_g1_arrays). */
export function trendOf(c) {
  const n = c.length;
  if (!n || c.some((x) => !Number.isFinite(x))) return {sign: null, close: null, ema: null, gap: null};
  const a = 2 / (EMA_N + 1);
  let y = c[0];
  for (let k = 1; k < n; k++) y = (1 - a) * y + a * c[k];
  const sign = n - 1 < EMA_N ? null : Math.sign(c[n - 1] - y);
  return {sign, close: c[n - 1], ema: y, gap: y ? c[n - 1] / y - 1 : null};
}
/** g2: {atrPct, pct (share of the last WINDOW ATR% values below the newest one), band ("low" | "normal" | "high" | null), n}; null values while fewer than WINDOW bars. */
export function volOf(hi, lo, c) {
  const n = c.length;
  const none = {atrPct: null, pct: null, band: null, n};
  if (n < WINDOW || [hi, lo, c].some((a) => a.some((x) => !Number.isFinite(x)))) return none;
  const k = 1 / ATR_N;
  let y = null;
  const series = [];
  for (let i = 0; i < n; i++) {
    const tr = i === 0 ? hi[i] - lo[i] : Math.max(hi[i] - lo[i], Math.abs(hi[i] - c[i - 1]), Math.abs(lo[i] - c[i - 1]));
    y = y == null ? tr : (1 - k) * y + k * tr;
    series.push(y / c[i]);
  }
  const w = series.slice(n - WINDOW), last = w[w.length - 1];
  if (!Number.isFinite(last)) return none;
  const pct = w.filter((x) => x < last).length / WINDOW;
  return {atrPct: last, pct, band: pct < LO ? "low" : pct > HI ? "high" : "normal", n};
}
export const TREND_KO = {1: "상승", "-1": "하락", 0: "횡보"};
export const BAND_KO = {low: "너무 조용", normal: "보통 범위", high: "너무 거침"};
const BAND_TONE = {low: "thin", normal: "good", high: "warn"};

/** The market state from the answers {coin: klines doc | null}: {btc, coins: [{coin, ok, atrPct, pct, band, close, closeMs}], ok}. */
export function analyze(answers, nowMs) {
  const coins = COINS.map((coin) => {
    const d = answers[coin];
    const row = {coin, ok: false, why: d && d.off ? "off" : "none", atrPct: null, pct: null, band: null, close: null, closeMs: null, trend: null};
    if (!d || d.off || d.unavailable) return row;
    const bars = closedBars(d, num(d.generated_ms) ?? nowMs);
    if (!bars || !bars.c.length) return row;
    const v = volOf(bars.h, bars.l, bars.c);
    return {...row, ok: true, why: "", ...v, close: bars.c[bars.c.length - 1], closeMs: bars.t[bars.t.length - 1] + TF_MS, trend: coin === "BTCUSD" ? trendOf(bars.c) : null};
  });
  const btc = coins.find((x) => x.coin === "BTCUSD");
  return {coins, btc: btc && btc.ok ? btc.trend : null, btcMs: btc && btc.ok ? btc.closeMs : null, ok: coins.some((x) => x.ok), off: coins.every((x) => x.why === "off")};
}

// ---------------------------------------------------------------- the page
function sentence(A) {
  const word = A.btc && A.btc.sign != null ? TREND_KO[A.btc.sign] : null;
  const known = A.coins.filter((x) => x.band);
  const normal = known.filter((x) => x.band === "normal").length;
  const part1 = word ? `BTC 4시간 추세는 ${word}입니다` : "BTC 4시간 추세는 아직 알 수 없습니다";
  const part2 = known.length ? `${fmt.int(known.length)}개 코인 중 ${fmt.int(normal)}개가 변동성 보통 범위입니다` : "변동성 보통 범위는 아직 알 수 없습니다";
  return `${part1}, ${part2}.`;
}
function allowed(sign) {
  if (sign == null) return "—";
  return sign > 0 ? "g1은 지금 롱만 통과시킵니다" : sign < 0 ? "g1은 지금 숏만 통과시킵니다" : "g1은 지금 롱도 숏도 통과시키지 않습니다 (종가가 EMA와 같음)";
}
function btcCard(A) {
  const t = A.btc;
  const word = t && t.sign != null ? `${TREND_KO[t.sign]}` : "—";
  return ui.card({plate: "BTC 4시간 추세 (g1)", sub: A.btcMs ? `${fmt.kst(A.btcMs)} KST까지 닫힌 봉` : "", cls: "kd-tcard s4-card rg-btc", id: "rg-btc"},
    h("div", {class: "rg-big"}, h("b", {class: ["rg-word", t && t.sign > 0 ? "up" : t && t.sign < 0 ? "down" : ""]}, word), t && t.sign != null ? h("span", {class: "muted"}, "추세") : null),
    h("p", {class: "dl-vline"}, t ? allowed(t.sign) : "BTC 4시간 봉을 받지 못했습니다"),
    h("dl", {class: "kd-kgrid s4-facts"},
      h("div", null, h("dt", null, "마지막 종가"), h("dd", {class: "num"}, t && t.close != null ? fmt.price(t.close) : "—")),
      h("div", null, h("dt", null, `EMA${EMA_N}`), h("dd", {class: "num"}, t && t.ema != null ? fmt.price(t.ema) : "—")),
      h("div", null, h("dt", null, "종가가 EMA보다"), h("dd", {class: "num"}, t && t.gap != null ? `${fmt.pct(Math.abs(t.gap) * 100, false, 2)} ${t.gap > 0 ? "위" : t.gap < 0 ? "아래" : "같음"}` : "—"))));
}
function bandBar(pct) {
  const label = pct == null ? "위치를 알 수 없음" : `최근 ${WINDOW}봉 중 하위 ${Math.round(pct * 100)}% 위치 (보통 범위 ${LO * 100}~${HI * 100}%)`;
  return h("span", {class: "rg-bar", role: "img", "aria-label": label}, h("i", {class: "rg-ok", style: {left: `${LO * 100}%`, width: `${(HI - LO) * 100}%`}}),
    pct == null ? null : h("i", {class: "rg-mark", style: {left: `${Math.min(99, Math.max(0, pct * 100))}%`}}));
}
function coinCard(x) {
  const c = fmt.coin(x.coin);
  return h("article", {class: ["kd-kcard", "rg-coin", x.band === "normal" ? "rg-normal" : ""], "aria-label": c, dataset: {coin: c, band: x.band || ""}},
    h("div", {class: "kd-kh"}, h("b", null, c), x.band ? ui.pill(BAND_KO[x.band], BAND_TONE[x.band], "마지막 닫힌 4시간 봉의 ATR%가 최근 200봉 가운데 어디쯤인지") : ui.pill("자료 없음", "thin")),
    h("div", {class: "kd-kbig"}, h("span", {class: "kd-kl"}, "변동성 ATR%"), h("b", {class: "num"}, x.atrPct == null ? "—" : fmt.pct(x.atrPct * 100, false, 2))),
    bandBar(x.pct),
    h("p", {class: "rv-sn s4-cs"}, x.pct == null ? (x.ok ? `봉이 ${WINDOW}개 미만이라 위치를 알 수 없습니다` : "이 코인의 4시간 봉을 받지 못했습니다") : `최근 ${WINDOW}봉 중 하위 ${Math.round(x.pct * 100)}% 위치`),
    h("p", {class: "s4-cs"}, x.close == null ? "" : `마지막 종가 ${fmt.price(x.close)}`));
}
function missing(A, retry) {
  return ui.card({plate: A.off ? "꺼짐" : "시장 자료 준비 중"}, h("p", {class: "dl-vline"}, A.off ? "실시간 시세가 꺼져 있어 시장 국면을 계산하지 못합니다." : "시세 자료를 아직 받지 못했습니다. 잠시 뒤 다시 시도합니다."),
    h("p", {class: "note"}, "리그 기록에는 영향이 없습니다. 이 화면은 시세가 있을 때만 숫자를 보여 줍니다."), h("button", {class: "btn-line", type: "button", onclick: retry}, "다시 불러오기"));
}
export async function mount(el, ctx) {
  el.classList.add("kd");
  const root = h("div", {class: "kd-root"});
  el.append(ui.screenHead("시장 국면", "리그의 두 필터가 보는 지금의 시장 상태"), root);
  let busy = false, state = "loading", A = null;
  function paint() {
    const rules = ruleBox(null, RULES, "지금 시세로 계산 · 권유하지 않습니다");
    if (state === "loading") { put(root, rules, h("div", {class: "dl-missing"}, h("b", null, "불러오는 중"), h("span", null, " · 코인 6개의 4시간 봉을 받고 있습니다"))); return; }
    if (!A || !A.ok) { put(root, rules, missing(A || {off: false}, load)); return; }
    put(root, rules, hero(sentence(A), "4시간 봉 기준 · 두 필터가 무엇을 뜻하는지는 아래 낱말 뜻에 있습니다", "지금 시세로 계산한 상태입니다. 앞으로를 약속하지 않고, 어떤 행동도 권하지 않습니다."), btcCard(A),
      ui.card({plate: "코인별 변동성 (g2)", sub: `마지막 닫힌 4시간 봉의 ATR%가 최근 ${WINDOW}봉 중 어디쯤인가`, cls: "kd-tcard s4-card", id: "rg-coins"},
        h("p", {class: "note"}, `띠의 색칠된 구간이 보통 범위(하위 ${LO * 100}%~${HI * 100}%)이고 세로선이 지금 위치입니다.`), h("div", {class: "kd-cards rg-cards"}, A.coins.map(coinCard))),
      legend([
        ["g1 BTC 추세 필터", "비트코인이 오르는 중이면 롱만, 내리는 중이면 숏만 들어가게 하는 필터입니다. 추세는 4시간 봉 종가가 50봉 평균선(EMA50) 위인지 아래인지로 정합니다."],
        ["g2 변동성 필터", "그 코인이 너무 조용하거나 너무 거칠 때는 들어가지 않게 하는 필터입니다. 최근 200봉과 비교해 중간 60% 안에 있을 때만 통과합니다."],
        ["ATR%", "봉 하나가 보통 얼마나 움직이는지를 가격에 대한 비율로 나타낸 것입니다. 클수록 거칩니다."],
        ["EMA", "최근 가격에 더 무게를 둔 이동평균선입니다. 가격이 선 위에 있으면 오르는 중, 아래에 있으면 내리는 중으로 봅니다."],
        ["하위 N%", "최근 200봉 가운데 N%의 봉은 지금보다 덜 움직였다는 뜻입니다. 50%이면 중간입니다."]]));
  }
  async function load() {
    if (busy) return;
    busy = true;
    try {
      const got = await Promise.allSettled(COINS.map((c) => ctx.api(`/api/klines?${new URLSearchParams({coin: c, tf: "4h", limit: String(BARS)})}`)));
      if (!ctx.alive()) return;
      const answers = {};
      COINS.forEach((c, i) => { answers[c] = got[i].status === "fulfilled" ? got[i].value : null; });
      A = analyze(answers, Date.now());
      state = "done";
    } catch (e) { A = null; state = "done"; } finally { busy = false; }
    paint();
  }
  paint();
  ctx.every(POLL_MS, load);
  await load();
}
