// 🧪 표본외(처음 보는 기간·코인) 검증 — 뉴럴 데스크 '전체 체계'를 스캘핑·단타·스윙별로 다시 돌린다.
//   왜: 관망 규칙집 기본값과 '익절 풀고 추적'은 2025-09~2026-10 1년(6코인)으로 골랐다. 같은 데이터로 확인하면 좋게 나오는 게 당연하다.
//   그래서 그 이전 기간(2023-01~2025-09)과 고를 때 안 쓴 코인 4개(ADA·AVAX·LINK·LTC)에서 똑같이 돌려 본다.
//   재연하는 것: ① 매매법 신호(strategies.js LIB) ② 워크포워드 선별(그 매매법의 직전 20건 평균 > +0.1R, 5·15분은 15건↑·+0.15R) ③ 관망 규칙집 기본값
//   ④ 코인당 1포지션·동시 4개 ⑤ 청산: 고정 익절 vs +1R 뒤 익절 풀고 ATR×3 추적 ⑥ 운 보정(운범위면 리스크 절반 → 'R×리스크' 로도 집계)
// 쓰는 법: node tools/oos-check.mjs <캔들 폴더(kl_<코인>_<봉>.json)> [스타일=all|scalp|day|swing]
globalThis.window = globalThis; globalThis.localStorage = { getItem() { return null; }, setItem() {} };
import fs from "fs";
const root = new URL("../", import.meta.url).href;
const Q = await import(root + "nuri-ai/quant.js"), E = await import(root + "gh-coin/strategies.js"), HR = await import(root + "gh-coin/lib/holdrules.js"), RB = await import(root + "gh-coin/lib/robust.js");
const { FW, frameworkPlan, regimeAt, htfAllows, htfBiasAt, atrFloorSL } = E;
const DIR = process.argv[2], ONLY = process.argv[3] || "all";
const OLD = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT"], NEW = ["ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT"];
const IS_FROM = Date.UTC(2025, 8, 25);   // 앱이 기본값을 고를 때 쓴 1년의 시작
const ld = (s, iv) => { const f = `${DIR}/kl_${s}_${iv}.json`; return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, "utf8")) : null; };
const MS = { "5": 300e3, "15": 900e3, "60": 3600e3, "240": 14400e3 }, IVN = { "5": "5m", "15": "15m", "60": "1h", "240": "4h" }, HTF = { "5": "60", "15": "60", "60": "240", "240": null };
const trendDir = (I, i) => { const e20 = I.ema20[i], e50 = I.ema50[i], c = I.c[i]; return e20 > e50 && c > e50 ? 1 : e20 < e50 && c < e50 ? -1 : 0; };
const lastClosed = (cs, step, t) => { let lo = 0, hi = cs.length - 1, k = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (cs[m].t + step <= t) { k = m; lo = m + 1; } else hi = m - 1; } return k; };
// 매매법 하나를 끝까지 굴려 거래 목록(청산 방식 두 가지)
function sim(rule, I, cs, H, sym, run) {
  if (rule.prep) rule.prep(cs); const tr = []; let pos = null;
  for (let i = 210; i < I.n - 1; i++) {
    if (pos) { const hi = I.h[i], lo = I.l[i]; let ex = null;
      if (pos.side > 0 ? lo <= pos.sl : hi >= pos.sl) ex = pos.sl; else if (pos.tp != null && (pos.side > 0 ? hi >= pos.tp : lo <= pos.tp)) ex = pos.tp;
      else if (rule.exit && rule.exit(I, i, pos.side)) ex = I.c[i]; else if (i - pos.i >= rule.hold * (pos.run ? 4 : 1)) ex = I.c[i];
      if (ex == null) { const fav = pos.side > 0 ? hi - pos.entry : pos.entry - lo;
        if (!pos.be && fav >= pos.rDist) { pos.sl = pos.side > 0 ? pos.entry * (1 + FW.fee) : pos.entry * (1 - FW.fee); pos.be = true; if (run) { pos.tp = null; pos.run = true; } }
        if (pos.run && I.atr[i]) { const n = I.c[i] - pos.side * 3 * I.atr[i]; if ((n - pos.sl) * pos.side > 0) pos.sl = n; } }
      else { const pret = (ex - pos.entry) / pos.entry * pos.side - FW.fee; tr.push({ R: Math.max(-pos.margin, pos.notional * pret) / pos.risk, t: cs[pos.i].t, t1: cs[i].t, side: pos.side, si: pos.si }); pos = null; }
      continue; }
    const s = rule.sig(I, i); if (!s) continue; const reg = regimeAt(I, i); if (rule.regimes && !rule.regimes.includes(reg.key)) continue;
    if (H && !htfAllows(rule, s.side, htfBiasAt(H, cs[i].t))) continue; s.sl = atrFloorSL(rule, I, i, s.side, s.sl, 1.0);
    const entry = I.o[i + 1]; const plan = frameworkPlan({ sym, entry, side: s.side, slPrice: s.sl, cat: rule.cat, rr: rule.rr, riskPct: FW.baseRisk, equity: 1000 }); if (!plan || plan.skip) continue;
    pos = { side: s.side, entry, sl: plan.sl, tp: plan.tp, margin: plan.margin, notional: plan.notional, risk: plan.risk, rDist: Math.abs(entry - plan.sl), be: false, i: i + 1, si: i }; }
  return tr;
}
const STY = { scalp: { ko: "스캘핑(5·15분)", tfs: ["15", "5"] }, day: { ko: "단타(1시간)", tfs: ["60"] }, swing: { ko: "스윙(4시간)", tfs: ["240"] } };
function build(style, coins, run) {
  const T = [];
  for (const s of coins) for (const tf of STY[style].tfs) {
    const cs = ld(s, IVN[tf]); if (!cs || cs.length < 600) continue; const I = E.prepare(Q, cs);
    const hcs = HTF[tf] ? ld(s, IVN[HTF[tf]]) : null, H = hcs ? E.prepareHTF(Q, hcs) : null;
    const c4 = ld(s, "4h"), I4 = c4 && (tf === "5" || tf === "15") ? E.prepare(Q, c4) : null, lowIv = { "60": "15", "15": "5" }[tf], lcs = lowIv ? ld(s, IVN[lowIv]) : null, IL = lcs ? E.prepare(Q, lcs) : null;
    const rules = E.LIB.filter(r => (tf === "240" ? r.tf === "240" : r.tf !== "240")).map(r => ({ ...r, tf, hold: r.tf === tf ? r.hold : tf === "60" ? 48 : tf === "15" ? (r.tf === "5" ? r.hold : r.hold * 4) : r.hold * 12 }));
    for (const r of rules) for (const t of sim(r, I, cs, H, s, run)) { const i = t.si, tc = cs[i].t + MS[tf];
      const k4 = I4 ? lastClosed(c4, MS["240"], tc) : -1, kl = IL ? lastClosed(lcs, MS[lowIv], tc) : -1;
      T.push({ s, key: r.key + "@" + tf, low: tf === "5" || tf === "15", t: t.t, t1: t.t1, R: t.R, ...HR.ctxAt(E, I, i, H, t.side, tc, { up2: k4 >= 60 ? trendDir(I4, k4) : null, small: tf === "5" || tf === "15", ltf: kl >= 60 ? trendDir(IL, kl) : null }) }); } }
  return T;
}
// 데스크 재연: 워크포워드 선별(그 매매법의 직전 20건 — 진입 시점에 이미 청산된 것만) + 관망 규칙집 + 포지션 한도 + 운 보정
function desk(T, { book = HR.defaultBook(), wf = true, K = 40 } = {}) {
  const X = [...T].sort((a, b) => a.t - b.t), hist = {}, byClose = [...T].sort((a, b) => a.t1 - b.t1); let ci = 0;
  const open = [], closed = [], taken = []; let rest = 0;
  for (const x of X) {
    while (ci < byClose.length && byClose[ci].t1 <= x.t) { const c = byClose[ci++]; (hist[c.key] ||= []).push(c.R); }
    let ch = false; for (let k = open.length - 1; k >= 0; k--) if (open[k].t1 <= x.t) { closed.push(open[k]); open.splice(k, 1); ch = true; }
    if (ch) { closed.sort((a, b) => a.t1 - b.t1); rest = Math.max(rest, HR.restUntil(book, closed)); }
    if (open.length >= 4 || open.some(o => o.s === x.s) || x.t < rest || HR.check(book, x)) continue;
    const h = (hist[x.key] || []).slice(-20), n = h.length, m = n ? h.reduce((a, b) => a + b, 0) / n : 0;
    if (wf && !(x.low ? n >= 15 && m > 0.15 : n >= 8 && m > 0.1)) continue;
    const sd = n > 1 ? Math.sqrt(h.reduce((a, b) => a + (b - m) ** 2, 0) / (n - 1)) : 0, luck = m < RB.luckBar(K, sd, n);
    open.push(x); taken.push({ ...x, w: luck ? 0.5 : 1 }); }
  return taken;
}
const stat = a => { const n = a.length; if (!n) return "거래 0"; const m = a.reduce((x, t) => x + t.R, 0) / n, w = a.reduce((x, t) => x + t.R * (t.w ?? 1), 0) / a.reduce((x, t) => x + (t.w ?? 1), 0);
  const mc = RB.ruinMC({ equity: [{ v: 1000 }], trades: a.map(t => ({ pnl: t.R * 5 * (t.w ?? 1) })) });   // 1R = 자본 0.5%
  return `${n}건 · 승률 ${Math.round(a.filter(t => t.R > 0).length / n * 100)}% · 평균 ${m >= 0 ? "+" : ""}${m.toFixed(3)}R · 운보정 가중 ${w >= 0 ? "+" : ""}${w.toFixed(3)}R · 합 ${(a.reduce((x, t) => x + t.R * (t.w ?? 1), 0)).toFixed(0)}R${mc ? ` · 낙폭95% ${mc.dd95}%` : ""}`; };
const periods = [["표본외 2023-01~2025-09 (기존 6코인)", t => t < IS_FROM, OLD], ["고를 때 쓴 1년 2025-09~ (기존 6코인)", t => t >= IS_FROM, OLD], ["처음 보는 코인 4개 2023-01~", () => true, NEW]];
for (const style of Object.keys(STY)) { if (ONLY !== "all" && ONLY !== style) continue;
  console.log(`\n══ ${STY[style].ko} ══`);
  for (const run of [false, true]) { const Tall = { OLD: build(style, OLD, run), NEW: build(style, NEW, run) };
    for (const [lab, f, coins] of periods) { const T = (coins === OLD ? Tall.OLD : Tall.NEW).filter(x => f(x.t)); if (!T.length) { console.log(lab, "자료 없음"); continue; }
      const none = HR.defaultBook(); for (const k in none.rules) none.rules[k].on = false;
      console.log(`[${run ? "익절 풀고 추적" : "고정 익절"}] ${lab}\n   매매법 전부(선별·규칙 없음): ${stat(desk(T, { book: none, wf: false }))}\n   워크포워드 선별만:          ${stat(desk(T, { book: none }))}\n   선별 + 관망 규칙집(앱 그대로): ${stat(desk(T))}`); } } }
