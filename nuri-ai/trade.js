// 누리 AI · 코인 트레이딩 룸
// 시세 → 지표 계산 → 퀀트 점수 → AI 해석 → 백테스트 → 모의투자
// 지표·점수·백테스트는 코드로 계산하고, AI는 계산된 숫자를 해석하는 역할만 맡는다.

/* ================= 지표 ================= */
export const sma = (a, n) => a.map((_, i) => { if (i < n - 1) return null; let s = 0; for (let j = i - n + 1; j <= i; j++) s += a[j]; return s / n; });
export const ema = (a, n) => { const k = 2 / (n + 1); const out = []; let prev = null; a.forEach((v, i) => { if (i < n - 1){ out.push(null); return; } if (prev === null){ let s = 0; for (let j = i - n + 1; j <= i; j++) s += a[j]; prev = s / n; } else prev = v * k + prev * (1 - k); out.push(prev); }); return out; };
export function rsi(c, n = 14){
  const out = Array(c.length).fill(null); if (c.length <= n) return out;
  let g = 0, l = 0;
  for (let i = 1; i <= n; i++){ const d = c[i] - c[i-1]; if (d > 0) g += d; else l -= d; }
  g /= n; l /= n; out[n] = l === 0 ? 100 : 100 - 100 / (1 + g / l);
  for (let i = n + 1; i < c.length; i++){ const d = c[i] - c[i-1]; g = (g * (n-1) + Math.max(d, 0)) / n; l = (l * (n-1) + Math.max(-d, 0)) / n; out[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l); }
  return out;
}
export function macd(c, f = 12, s = 26, sig = 9){
  const ef = ema(c, f), es = ema(c, s);
  const line = c.map((_, i) => ef[i] == null || es[i] == null ? null : ef[i] - es[i]);
  const start = line.findIndex(v => v != null);
  const sigArr = Array(c.length).fill(null);
  if (start >= 0){ const e = ema(line.slice(start), sig); e.forEach((v, i) => sigArr[start + i] = v); }
  return {line, signal: sigArr, hist: line.map((v, i) => v == null || sigArr[i] == null ? null : v - sigArr[i])};
}
export function boll(c, n = 20, k = 2){
  const mid = sma(c, n);
  const sd = c.map((_, i) => { if (mid[i] == null) return null; let s = 0; for (let j = i - n + 1; j <= i; j++) s += (c[j] - mid[i]) ** 2; return Math.sqrt(s / n); });
  return {mid, up: mid.map((m, i) => m == null ? null : m + k * sd[i]), lo: mid.map((m, i) => m == null ? null : m - k * sd[i])};
}
export function atr(cs, n = 14){
  const tr = cs.map((x, i) => i === 0 ? x.h - x.l : Math.max(x.h - x.l, Math.abs(x.h - cs[i-1].c), Math.abs(x.l - cs[i-1].c)));
  const out = Array(cs.length).fill(null); if (cs.length <= n) return out;
  let a = tr.slice(1, n + 1).reduce((s, v) => s + v, 0) / n; out[n] = a;
  for (let i = n + 1; i < cs.length; i++){ a = (a * (n - 1) + tr[i]) / n; out[i] = a; }
  return out;
}
export function levels(cs, price, k = 4){
  // 스윙 고점·저점을 모아 0.8% 안쪽끼리 묶어 지지·저항대로 정리
  const piv = [];
  for (let i = k; i < cs.length - k; i++){
    let hi = true, lo = true;
    for (let j = i - k; j <= i + k; j++){ if (cs[j].h > cs[i].h) hi = false; if (cs[j].l < cs[i].l) lo = false; }
    if (hi) piv.push(cs[i].h); if (lo) piv.push(cs[i].l);
  }
  piv.sort((a, b) => a - b);
  const groups = [];
  for (const p of piv){ const g = groups[groups.length - 1]; if (g && (p - g.avg) / g.avg < 0.008){ g.n++; g.sum += p; g.avg = g.sum / g.n; } else groups.push({n:1, sum:p, avg:p}); }
  const strong = groups.sort((a, b) => b.n - a.n).slice(0, 12).map(g => ({p:g.avg, n:g.n}));
  return {
    res: strong.filter(g => g.p > price * 1.002).sort((a, b) => a.p - b.p).slice(0, 3),
    sup: strong.filter(g => g.p < price * 0.998).sort((a, b) => b.p - a.p).slice(0, 3)
  };
}
export function computeAll(cs){
  const c = cs.map(x => x.c), v = cs.map(x => x.v);
  return {ma20: sma(c, 20), ma60: sma(c, 60), ma120: sma(c, 120), rsi: rsi(c), macd: macd(c), bb: boll(c), atr: atr(cs), vma: sma(v, 20)};
}
const last = a => { for (let i = a.length - 1; i >= 0; i--) if (a[i] != null) return a[i]; return null; };
export function quantScore(cs, ind){
  const n = cs.length - 1, p = cs[n].c, f = [];
  const add = (label, pts, note, max = 10) => f.push({label, pts, note, max});
  for (const [k, lab] of [["ma20","20선"],["ma60","60선"],["ma120","120선"]]){ const m = ind[k][n]; if (m != null) add(`가격 ${p >= m ? "≥" : "<"} ${lab}`, p >= m ? 10 : -10, `${lab} ${fmtNum(m)}`); }
  if (ind.ma20[n] != null && ind.ma20[n-5] != null){ const sl = (ind.ma20[n] / ind.ma20[n-5] - 1) * 100; add(`20선 ${sl >= 0 ? "상승" : "하락"} 기울기`, sl >= 0.3 ? 10 : sl <= -0.3 ? -10 : 0, `${sl.toFixed(2)}% / 5봉`); }
  const r = ind.rsi[n];
  if (r != null) add(`RSI ${r.toFixed(0)}`, r >= 70 ? 5 : r >= 50 ? 10 : r >= 30 ? -10 : -5, r >= 70 ? "과열권" : r <= 30 ? "과매도권" : r >= 50 ? "상승 모멘텀" : "하락 모멘텀");
  const h = ind.macd.hist[n], hp = ind.macd.hist[n-1];
  if (h != null && hp != null) add(`MACD ${h >= 0 ? "양" : "음"}의 히스토그램`, (h >= 0 ? 10 : -10) + (h > hp ? 5 : -5), h > hp ? "모멘텀 강해지는 중" : "모멘텀 약해지는 중", 15);
  const vm = ind.vma[n];
  if (vm){ const ratio = cs[n].v / vm; if (ratio >= 1.5) add(`거래량 ${ratio.toFixed(1)}배`, cs[n].c >= cs[n].o ? 10 : -10, cs[n].c >= cs[n].o ? "거래량 실린 양봉" : "거래량 실린 음봉"); }
  const up = ind.bb.up[n], lo = ind.bb.lo[n];
  if (up != null){ const pb = (p - lo) / (up - lo); if (pb > 1) add("볼린저 상단 돌파", -5, "단기 과열 가능"); else if (pb < 0) add("볼린저 하단 이탈", 5, "단기 반등 가능"); }
  const max = f.reduce((s, x) => s + x.max, 0) || 1;
  const score = Math.max(-100, Math.min(100, Math.round(f.reduce((s, x) => s + x.pts, 0) / max * 100)));
  const label = score >= 50 ? "강한 상승 우위" : score >= 20 ? "상승 우위" : score > -20 ? "중립" : score > -50 ? "하락 우위" : "강한 하락 우위";
  return {score, label, factors: f};
}

/* ================= 백테스트 ================= */
export const STRATS = {
  ma: {name:"이동평균 골든/데드 크로스", params:[["fast","단기선",20,2,100],["slow","장기선",60,5,300]], desc:"단기선이 장기선을 위로 뚫으면 사고, 아래로 뚫으면 판다."},
  rsi:{name:"RSI 역추세", params:[["low","매수 RSI",30,5,50],["high","매도 RSI",70,50,95]], desc:"RSI가 과매도에서 올라오면 사고, 과열권에 닿으면 판다."},
  bb: {name:"볼린저 밴드 회귀", params:[["n","기간",20,5,100],["k","폭(표준편차)",2,1,4]], desc:"하단 밴드 아래로 떨어지면 사고, 중심선 위로 오면 판다."},
  macd:{name:"MACD 크로스", params:[["f","단기",12,2,50],["s","장기",26,5,100],["g","시그널",9,2,50]], desc:"MACD선이 시그널선을 위로 뚫으면 사고, 아래로 뚫으면 판다."}
};
export function backtest(cs, key, P, opt){
  const c = cs.map(x => x.c), n = cs.length;
  let sig; // +1 매수, -1 매도 (i번째 봉 종가 기준, 다음 봉 시가에 체결)
  if (key === "ma"){ const a = sma(c, P.fast), b = sma(c, P.slow); sig = c.map((_, i) => i && a[i] != null && b[i] != null && a[i-1] != null && b[i-1] != null ? (a[i-1] <= b[i-1] && a[i] > b[i] ? 1 : a[i-1] >= b[i-1] && a[i] < b[i] ? -1 : 0) : 0); }
  if (key === "rsi"){ const r = rsi(c); sig = c.map((_, i) => i && r[i] != null && r[i-1] != null ? (r[i-1] < P.low && r[i] >= P.low ? 1 : r[i] >= P.high ? -1 : 0) : 0); }
  if (key === "bb"){ const b = boll(c, P.n, P.k); sig = c.map((_, i) => b.lo[i] == null ? 0 : c[i] < b.lo[i] ? 1 : c[i] > b.mid[i] ? -1 : 0); }
  if (key === "macd"){ const m = macd(c, P.f, P.s, P.g); sig = c.map((_, i) => i && m.line[i] != null && m.signal[i] != null && m.line[i-1] != null && m.signal[i-1] != null ? (m.line[i-1] <= m.signal[i-1] && m.line[i] > m.signal[i] ? 1 : m.line[i-1] >= m.signal[i-1] && m.line[i] < m.signal[i] ? -1 : 0) : 0); }
  const fee = opt.fee / 100, sl = opt.sl / 100, tp = opt.tp / 100;
  const start = sig.findIndex((_, i) => i > 0) || 1;
  let cash = 1, qty = 0, entry = 0, entryT = 0, peak = 1, mdd = 0, bars = 0;
  const eq = [], trades = [], marks = [];
  const sell = (i, px, why) => { cash = qty * px * (1 - fee); trades.push({t0: entryT, t1: cs[i].t, entry, exit: px, ret: px * (1 - fee) / (entry / (1 - fee)) - 1, why}); marks.push({i, side:"sell"}); qty = 0; };
  for (let i = 0; i < n; i++){
    if (qty > 0){
      bars++;
      if (sl && cs[i].l <= entry * (1 - sl)) sell(i, Math.min(cs[i].o, entry * (1 - sl)), "손절");
      else if (tp && cs[i].h >= entry * (1 + tp)) sell(i, Math.max(cs[i].o, entry * (1 + tp)), "익절");
    }
    const s = sig[i - 1] || 0; // 전 봉 신호를 이번 봉 시가에 체결
    if (i > 0 && s === 1 && qty === 0){ entry = cs[i].o; entryT = cs[i].t; qty = cash * (1 - fee) / entry; cash = 0; marks.push({i, side:"buy"}); }
    else if (i > 0 && s === -1 && qty > 0) sell(i, cs[i].o, "신호");
    const e = cash + qty * cs[i].c; eq.push(e); peak = Math.max(peak, e); mdd = Math.max(mdd, 1 - e / peak);
  }
  const wins = trades.filter(t => t.ret > 0), losses = trades.filter(t => t.ret <= 0);
  const gp = wins.reduce((s, t) => s + t.ret, 0), gl = -losses.reduce((s, t) => s + t.ret, 0);
  let hpeak = c[0], hmdd = 0; for (const v of c){ hpeak = Math.max(hpeak, v); hmdd = Math.max(hmdd, 1 - v / hpeak); }
  return {
    ret: eq[n-1] - 1, hold: c[n-1] / c[0] - 1, mdd, holdMdd: hmdd, trades, marks, eq, open: qty > 0,
    win: trades.length ? wins.length / trades.length : 0, pf: gl ? gp / gl : (gp ? Infinity : 0), exposure: bars / n, start
  };
}

/* ================= 공용 ================= */
export function fmtNum(v, quote){
  if (v == null || !isFinite(v)) return "–";
  const a = Math.abs(v);
  const d = quote === "USDT" ? (a >= 1000 ? 2 : a >= 1 ? 4 : 6) : (a >= 100 ? 0 : a >= 1 ? 2 : 4);
  return v.toLocaleString("ko-KR", {minimumFractionDigits: d > 0 && quote === "USDT" ? Math.min(2, d) : 0, maximumFractionDigits: d});
}
const pct = (v, d = 2) => (v >= 0 ? "+" : "") + (v * 100).toFixed(d) + "%";
const bigKRW = v => v >= 1e12 ? (v/1e12).toFixed(2) + "조" : v >= 1e8 ? (v/1e8).toFixed(0) + "억" : v >= 1e4 ? (v/1e4).toFixed(0) + "만" : Math.round(v).toLocaleString();
const bigUSD = v => v >= 1e9 ? (v/1e9).toFixed(2) + "B" : v >= 1e6 ? (v/1e6).toFixed(1) + "M" : v >= 1e3 ? (v/1e3).toFixed(1) + "K" : v.toFixed(0);
const TFS = [["1","1분"],["5","5분"],["15","15분"],["60","1시간"],["240","4시간"],["D","일"],["W","주"]];
const TF_MS = {"1":6e4,"5":3e5,"15":9e5,"60":36e5,"240":144e5,"D":864e5,"W":6048e5};

/* ================= 트레이딩 룸 ================= */
export function initTrade(ctx){
  const {root, brain, apiBase, toast, md, esc, ls} = ctx;
  const S = {
    ex: ls.get("tr:ex", "upbit"), market: null, tf: ls.get("tr:tf", "60"), total: ls.get("tr:total", 200),
    cs: [], ind: null, q: null, lv: null, list: [], tick: new Map(), filter: "",
    view: {count: 120, off: 0}, show: Object.assign({ma:true, bb:true, lv:true}, ls.get("tr:show", {})),
    hover: -1, bt: null, btKey: ls.get("tr:bt", "ma"), btP: ls.get("tr:btp", {}), btOpt: Object.assign({fee:0.05, sl:0, tp:0}, ls.get("tr:bto", {})),
    tab: "bt", side: "buy", timers: [], visible: false, loading: false, err: "", aiCtl: null, ai: null, aiRaw: ""
  };
  S.market = ls.get("tr:mkt:" + S.ex, S.ex === "upbit" ? "KRW-BTC" : "BTCUSDT");

  const EX = {
    upbit: {
      label: "업비트", quote: "KRW", fee: 0.05,
      async list(){
        const mk = (await get("upbit", "/market/all?isDetails=false")).filter(m => m.market.startsWith("KRW-"));
        const names = new Map(mk.map(m => [m.market, m.korean_name]));
        const ids = mk.map(m => m.market), out = [];
        for (let i = 0; i < ids.length; i += 100) out.push(...await get("upbit", "/ticker?markets=" + ids.slice(i, i+100).join(",")));
        return out.map(t => ({id: t.market, sym: t.market.slice(4), name: names.get(t.market) || t.market, price: t.trade_price, chg: t.signed_change_rate, vol: t.acc_trade_price_24h, hi: t.high_price, lo: t.low_price}));
      },
      async tickers(ids){ const out = await get("upbit", "/ticker?markets=" + ids.join(",")); return out.map(t => ({id: t.market, price: t.trade_price, chg: t.signed_change_rate, vol: t.acc_trade_price_24h, hi: t.high_price, lo: t.low_price})); },
      async candles(id, tf, total){
        const path = tf === "D" ? "/candles/days" : tf === "W" ? "/candles/weeks" : `/candles/minutes/${tf}`;
        const rows = []; let to = "";
        while (rows.length < total){
          const part = await get("upbit", `${path}?market=${id}&count=${Math.min(200, total - rows.length)}${to ? "&to=" + encodeURIComponent(to) : ""}`);
          if (!part.length) break;
          rows.push(...part); to = part[part.length - 1].candle_date_time_utc + "Z";
          if (part.length < 200) break;
          await new Promise(r => setTimeout(r, 120));
        }
        const m = new Map();
        for (const r of rows) m.set(Date.parse(r.candle_date_time_utc + "Z"), {t: Date.parse(r.candle_date_time_utc + "Z"), o: r.opening_price, h: r.high_price, l: r.low_price, c: r.trade_price, v: r.candle_acc_trade_volume});
        return [...m.values()].sort((a, b) => a.t - b.t);
      }
    },
    binance: {
      label: "바이낸스", quote: "USDT", fee: 0.1,
      async list(){
        const all = await get("binance", "/ticker/24hr");
        return all.filter(t => t.symbol.endsWith("USDT") && !/(UP|DOWN|BULL|BEAR)USDT$/.test(t.symbol) && +t.quoteVolume > 0)
          .sort((a, b) => b.quoteVolume - a.quoteVolume).slice(0, 120)
          .map(t => ({id: t.symbol, sym: t.symbol.replace(/USDT$/, ""), name: t.symbol.replace(/USDT$/, ""), price: +t.lastPrice, chg: +t.priceChangePercent / 100, vol: +t.quoteVolume, hi: +t.highPrice, lo: +t.lowPrice}));
      },
      async tickers(ids){ const out = await get("binance", "/ticker/24hr?symbols=" + encodeURIComponent(JSON.stringify(ids))); return out.map(t => ({id: t.symbol, price: +t.lastPrice, chg: +t.priceChangePercent / 100, vol: +t.quoteVolume, hi: +t.highPrice, lo: +t.lowPrice})); },
      async candles(id, tf, total){
        const iv = {"1":"1m","5":"5m","15":"15m","60":"1h","240":"4h","D":"1d","W":"1w"}[tf];
        const rows = await get("binance", `/klines?symbol=${id}&interval=${iv}&limit=${Math.min(1000, total)}`);
        return rows.map(r => ({t: r[0], o: +r[1], h: +r[2], l: +r[3], c: +r[4], v: +r[5]}));
      }
    }
  };
  const X = () => EX[S.ex];
  async function get(ex, path){
    const r = await fetch(apiBase(ex) + path, {headers: {accept: "application/json"}});
    if (!r.ok){ const e = new Error(`${EX[ex].label} ${r.status}`); e.status = r.status; throw e; }
    return r.json();
  }
  const fmt = v => fmtNum(v, X().quote);
  const big = v => X().quote === "KRW" ? bigKRW(v) : bigUSD(v);
  const cur = () => S.list.find(m => m.id === S.market) || {id: S.market, sym: S.market, name: S.market};

  /* ---------- 레이아웃 ---------- */
  root.innerHTML = `
  <div class="tr">
    <div class="tr-head">
      <div class="tr-title"><select class="sel" id="tr-ex" aria-label="거래소">${Object.entries(EX).map(([k, e]) => `<option value="${k}">${e.label}</option>`).join("")}</select><div><b id="tr-name">—</b><span id="tr-id" class="small"></span></div></div>
      <div class="tr-price"><span id="tr-px" class="num">—</span><span id="tr-chg" class="chg num">—</span></div>
      <div class="tr-stats" id="tr-stats"></div>
    </div>
    <div class="tr-grid">
      <aside class="card tr-list"><div class="body" style="padding:10px;gap:8px"><input class="search" id="tr-q" type="search" placeholder="코인 검색 (이름·기호)" aria-label="코인 검색"><div class="tr-rows" id="tr-rows"><p class="empty">시세를 불러오는 중…</p></div></div></aside>
      <section class="card tr-chart">
        <div class="tr-tools">
          <div class="seg" id="tr-tf">${TFS.map(([k, l]) => `<button data-tf="${k}">${l}</button>`).join("")}</div>
          <div class="seg" id="tr-show"><button data-show="ma">이동평균</button><button data-show="bb">볼린저</button><button data-show="lv">지지·저항</button></div>
          <select class="sel" id="tr-total" aria-label="캔들 개수"><option value="200">캔들 200개</option><option value="500">500개</option><option value="1000">1,000개</option></select>
          <span class="small" id="tr-upd"></span>
        </div>
        <div class="tr-canvas" id="tr-cv-wrap"><canvas id="tr-cv" aria-label="가격 차트"></canvas><div class="tr-tip" id="tr-tip" hidden></div><div class="tr-msg" id="tr-msg" hidden></div></div>
        <div class="tr-legend small"><span><i style="background:var(--ma1)"></i>MA20</span><span><i style="background:var(--ma2)"></i>MA60</span><span><i style="background:var(--ma3)"></i>MA120</span><span>휠: 확대 · 드래그: 이동 · 더블클릭: 처음으로</span></div>
      </section>
      <aside class="tr-side">
        <div class="card"><h3>퀀트 점수 <small>지표 기반 · 투자 조언 아님</small></h3><div class="body" id="tr-score"></div></div>
        <div class="card"><h3>AI 분석 <small id="tr-ai-brain"></small></h3><div class="body" id="tr-ai"><p class="empty">현재 차트와 지표를 AI가 해석합니다.</p><button class="btn primary" id="tr-ai-go">AI 분석 실행</button></div></div>
      </aside>
    </div>
    <div class="card tr-bottom">
      <div class="tr-tabs"><button data-tab="bt">전략 백테스트</button><button data-tab="paper">모의투자</button></div>
      <div class="body" id="tr-bt" hidden></div>
      <div class="body" id="tr-paper" hidden></div>
    </div>
    <p class="small tr-note">시세: ${"업비트·바이낸스 공개 API"}. 모든 지표와 AI 분석은 과거 데이터에 기반하며 미래 가격을 보장하지 않습니다. 투자 판단과 책임은 본인에게 있습니다.</p>
  </div>`;
  const $ = s => root.querySelector(s);
  $("#tr-ex").value = S.ex; $("#tr-total").value = String(S.total);

  /* ---------- 데이터 ---------- */
  async function loadList(){
    try { S.list = await X().list(); S.list.sort((a, b) => b.vol - a.vol); S.list.forEach(m => S.tick.set(m.id, m)); S.err = ""; }
    catch (e){ S.err = netErr(e); }
    renderList(); renderHead();
  }
  async function loadCandles(){
    S.loading = true; msg("차트를 불러오는 중…");
    try {
      S.cs = await X().candles(S.market, S.tf, S.total);
      if (S.cs.length < 30) throw new Error("캔들 데이터가 부족합니다");
      recompute(); S.view.off = 0; S.view.count = Math.min(S.cs.length, 120); S.bt = null; S.ai = null; S.aiRaw = "";
      msg(""); S.err = "";
    } catch (e){ S.cs = []; S.ind = null; S.q = null; msg(netErr(e), true); }
    S.loading = false; renderAll();
  }
  function recompute(){
    S.ind = computeAll(S.cs);
    S.q = quantScore(S.cs, S.ind);
    S.lv = levels(S.cs.slice(-150), S.cs[S.cs.length - 1].c);
  }
  async function refresh(){
    if (!S.visible || S.loading) return;
    if (!S.list.length) await loadList();          // 처음 연결에 실패했으면 다시 시도
    if (!S.cs.length){ if (S.list.length || !S.err) await loadCandles(); return; }
    try {
      const ids = [S.market, ...S.list.slice(0, 30).map(m => m.id)].filter((v, i, a) => a.indexOf(v) === i).slice(0, 30);
      for (const t of await X().tickers(ids)){ const m = S.list.find(x => x.id === t.id); if (m) Object.assign(m, t); S.tick.set(t.id, {...(S.tick.get(t.id) || {}), ...t}); }
      if (S.cs.length){
        const fresh = await X().candles(S.market, S.tf, 3);
        for (const k of fresh){ const i = S.cs.findIndex(x => x.t === k.t); if (i >= 0) S.cs[i] = k; else if (k.t > S.cs[S.cs.length-1].t) S.cs.push(k); }
        recompute();
      }
      $("#tr-upd").textContent = "갱신 " + new Date().toLocaleTimeString("ko-KR", {hour:"2-digit", minute:"2-digit", second:"2-digit"});
      renderHead(); renderList(); renderScore(); draw(); if (S.tab === "paper") renderPaper();
    } catch (e){ $("#tr-upd").textContent = "갱신 실패 · 잠시 뒤 다시 시도"; }
  }
  function netErr(e){
    if (e instanceof TypeError) return ctx.launcher() ? "거래소에 연결하지 못했습니다. 인터넷 연결을 확인하세요." : "브라우저 보안정책 때문에 거래소 시세를 직접 받을 수 없습니다. NuriAI.exe로 실행하면 됩니다.";
    if (e.status === 429) return "요청이 너무 많습니다. 잠시 뒤 다시 시도하세요.";
    if (e.status === 502) return `${X().label}에 연결하지 못했습니다. 인터넷 연결이나 방화벽·백신 프로그램이 NuriAI.exe의 인터넷 접속을 막고 있는지 확인하세요.`;
    return "시세를 불러오지 못했습니다: " + (e.message || e);
  }
  function msg(t, retry){
    const m = $("#tr-msg"); m.hidden = !t;
    m.innerHTML = t ? `<div class="tr-msg-box"><span>${esc(t)}</span>${retry ? `<button class="btn primary" id="tr-retry">다시 시도</button><span class="small">10초마다 자동으로 다시 시도합니다</span>` : ""}</div>` : "";
  }

  /* ---------- 상단·목록 ---------- */
  function renderHead(){
    const m = {...cur(), ...(S.tick.get(S.market) || {})};
    const px = m.price ?? (S.cs.length ? S.cs[S.cs.length-1].c : null);
    $("#tr-name").textContent = m.name || S.market; $("#tr-id").textContent = m.name && m.name !== S.market ? " " + S.market : "";
    $("#tr-px").textContent = fmt(px) + (X().quote === "KRW" ? "원" : "");
    const chg = $("#tr-chg"); chg.textContent = m.chg != null ? pct(m.chg) : ""; chg.className = "chg num " + (m.chg > 0 ? "up" : m.chg < 0 ? "down" : "");
    $("#tr-px").className = "num " + (m.chg > 0 ? "up" : m.chg < 0 ? "down" : "");
    const a = S.ind ? last(S.ind.atr) : null;
    $("#tr-stats").innerHTML = [
      ["24시간 고가", fmt(m.hi)], ["24시간 저가", fmt(m.lo)], ["24시간 거래대금", m.vol ? big(m.vol) : "–"],
      ["RSI(14)", S.ind ? (last(S.ind.rsi) ?? 0).toFixed(1) : "–"], ["변동성(ATR)", a && px ? (a / px * 100).toFixed(2) + "%" : "–"]
    ].map(([l, v]) => `<div><label>${l}</label><span class="num">${v}</span></div>`).join("");
    $("#tr-ai-brain").textContent = brain.ready() ? brain.label() : "AI 두뇌 필요";
  }
  function renderList(){
    const q = S.filter.trim().toLowerCase();
    const rows = S.list.filter(m => !q || m.name.toLowerCase().includes(q) || m.sym.toLowerCase().includes(q)).slice(0, 80);
    $("#tr-rows").innerHTML = S.err && !S.list.length ? `<p class="err">${esc(S.err)}</p><button class="btn" id="tr-retry2">다시 시도</button>` : rows.map(m => `<button class="tr-row${m.id === S.market ? " on" : ""}" data-mkt="${esc(m.id)}"><span class="nm"><b>${esc(m.name)}</b><span class="small">${esc(m.sym)}</span></span><span class="num px">${fmt(m.price)}</span><span class="num chg ${m.chg > 0 ? "up" : m.chg < 0 ? "down" : ""}">${pct(m.chg || 0)}</span></button>`).join("") || `<p class="empty">검색 결과가 없습니다.</p>`;
  }
  $("#tr-rows").addEventListener("click", e => { const b = e.target.closest("[data-mkt]"); if (!b || b.dataset.mkt === S.market) return; S.market = b.dataset.mkt; ls.set("tr:mkt:" + S.ex, S.market); renderList(); renderHead(); loadCandles(); });
  $("#tr-q").addEventListener("input", e => { S.filter = e.target.value; renderList(); });
  $("#tr-ex").addEventListener("change", async e => { S.ex = e.target.value; ls.set("tr:ex", S.ex); S.market = ls.get("tr:mkt:" + S.ex, S.ex === "upbit" ? "KRW-BTC" : "BTCUSDT"); S.list = []; S.tick.clear(); renderList(); await loadList(); await loadCandles(); });
  $("#tr-tf").addEventListener("click", e => { const b = e.target.closest("[data-tf]"); if (!b) return; S.tf = b.dataset.tf; ls.set("tr:tf", S.tf); syncTools(); loadCandles(); });
  $("#tr-show").addEventListener("click", e => { const b = e.target.closest("[data-show]"); if (!b) return; S.show[b.dataset.show] = !S.show[b.dataset.show]; ls.set("tr:show", S.show); syncTools(); draw(); });
  $("#tr-total").addEventListener("change", e => { S.total = +e.target.value; ls.set("tr:total", S.total); loadCandles(); });
  function syncTools(){
    root.querySelectorAll("[data-tf]").forEach(b => b.setAttribute("aria-pressed", b.dataset.tf === S.tf));
    root.querySelectorAll("[data-show]").forEach(b => b.setAttribute("aria-pressed", !!S.show[b.dataset.show]));
    root.querySelectorAll("[data-tab]").forEach(b => b.setAttribute("aria-pressed", b.dataset.tab === S.tab));
    $("#tr-bt").hidden = S.tab !== "bt"; $("#tr-paper").hidden = S.tab !== "paper";
  }

  /* ---------- 차트 ---------- */
  const cv = $("#tr-cv"), wrap = $("#tr-cv-wrap"), tip = $("#tr-tip");
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  let geo = null;
  function draw(){
    const w = wrap.clientWidth, h = wrap.clientHeight; if (!w || !h) return;
    const dpr = Math.min(2, devicePixelRatio || 1);
    cv.width = w * dpr; cv.height = h * dpr; cv.style.width = w + "px"; cv.style.height = h + "px";
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    if (!S.cs.length || !S.ind) return;
    const C = {up: css("--up"), down: css("--down"), ink: css("--ink"), muted: css("--muted"), line: css("--line"), ma1: css("--ma1"), ma2: css("--ma2"), ma3: css("--ma3"), acc: css("--accent"), panel: css("--panel")};
    const mono = css("--f-mono") || "monospace";
    const padT = 8, timeH = 20;
    const N = S.cs.length, cnt = Math.min(S.view.count, N), end = N - S.view.off, beg = Math.max(0, end - cnt);
    const vis = S.cs.slice(beg, end);
    const mainH = (h - timeH) * 0.64, rsiH = (h - timeH) * 0.16, macdH = (h - timeH) * 0.20;
    const mainT = padT, rsiT = mainH + 4, macdT = rsiT + rsiH + 4;
    let hi = -Infinity, lo = Infinity;
    for (let i = beg; i < end; i++){
      hi = Math.max(hi, S.cs[i].h); lo = Math.min(lo, S.cs[i].l);
      if (S.show.bb && S.ind.bb.up[i] != null){ hi = Math.max(hi, S.ind.bb.up[i]); lo = Math.min(lo, S.ind.bb.lo[i]); }
    }
    const pad = (hi - lo) * 0.06 || hi * 0.01; hi += pad; lo -= pad;
    g.font = `11px ${mono}`;
    const axisW = Math.ceil(Math.max(g.measureText(fmt(hi)).width, g.measureText(fmt(lo)).width, 40)) + 16; // 가격 자릿수에 맞춰 축 너비 결정
    const plotW = w - axisW, bw = plotW / cnt;
    const volH = (mainH - padT) * 0.18;
    const y = v => mainT + (hi - v) / (hi - lo) * (mainH - padT - volH);
    const x = i => (i - beg) * bw + bw / 2;
    geo = {beg, end, bw, plotW, y, x, mainT, mainH, hi, lo, rsiT, rsiH, macdT, macdH, axisW, w, h, timeH, volH};
    // 격자 + 가격축
    g.font = `11px ${mono}`; g.textBaseline = "middle"; g.textAlign = "left";
    const step = niceStep((hi - lo) / 6);
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step){
      const yy = Math.round(y(v)) + .5; if (yy > mainT + mainH - volH) continue;
      g.strokeStyle = C.line; g.globalAlpha = .6; g.beginPath(); g.moveTo(0, yy); g.lineTo(plotW, yy); g.stroke(); g.globalAlpha = 1;
      g.fillStyle = C.muted; g.fillText(fmt(v), plotW + 6, yy);
    }
    // 볼린저 밴드
    if (S.show.bb){
      g.fillStyle = C.acc; g.globalAlpha = .07; g.beginPath(); let started = false;
      for (let i = beg; i < end; i++){ const v = S.ind.bb.up[i]; if (v == null) continue; if (!started){ g.moveTo(x(i), y(v)); started = true; } else g.lineTo(x(i), y(v)); }
      for (let i = end - 1; i >= beg; i--){ const v = S.ind.bb.lo[i]; if (v == null) continue; g.lineTo(x(i), y(v)); }
      g.closePath(); g.fill(); g.globalAlpha = .5;
      line(g, S.ind.bb.up, C.acc, 1); line(g, S.ind.bb.lo, C.acc, 1); g.globalAlpha = 1;
    }
    // 거래량
    const vmax = Math.max(...vis.map(k => k.v)) || 1;
    for (let i = beg; i < end; i++){ const k = S.cs[i], vh = k.v / vmax * volH; g.fillStyle = k.c >= k.o ? C.up : C.down; g.globalAlpha = .28; g.fillRect(x(i) - bw * .35, mainT + mainH - padT - vh, Math.max(1, bw * .7), vh); }
    g.globalAlpha = 1;
    // 캔들
    for (let i = beg; i < end; i++){
      const k = S.cs[i], upc = k.c >= k.o, col = upc ? C.up : C.down, cx = x(i);
      g.strokeStyle = col; g.fillStyle = col; g.lineWidth = 1;
      g.beginPath(); g.moveTo(Math.round(cx) + .5, y(k.h)); g.lineTo(Math.round(cx) + .5, y(k.l)); g.stroke();
      const t = y(Math.max(k.o, k.c)), bh = Math.max(1, Math.abs(y(k.o) - y(k.c)));
      g.fillRect(cx - bw * .36, t, Math.max(1, bw * .72), bh);
    }
    // 이동평균
    if (S.show.ma){ line(g, S.ind.ma20, C.ma1, 1.5); line(g, S.ind.ma60, C.ma2, 1.5); line(g, S.ind.ma120, C.ma3, 1.5); }
    // 지지·저항
    if (S.show.lv && S.lv){
      g.setLineDash([4, 4]); g.lineWidth = 1;
      const used = [];
      for (const [arr, col, lab] of [[S.lv.res, C.up, "저항"], [S.lv.sup, C.down, "지지"]]) for (const l of arr){
        if (l.p < lo || l.p > hi) continue;
        const yy = Math.round(y(l.p)) + .5; g.strokeStyle = col; g.globalAlpha = .7; g.beginPath(); g.moveTo(0, yy); g.lineTo(plotW, yy); g.stroke(); g.globalAlpha = 1;
        if (used.some(u => Math.abs(u - yy) < 14)) continue; // 글자가 겹치면 선만 그림
        used.push(yy); g.fillStyle = col; g.textAlign = "left"; g.font = `11px ${css("--f-body")}`; g.fillText(`${lab} ${fmt(l.p)}`, 6, yy - 8);
      }
      g.setLineDash([]); g.font = `11px ${mono}`;
    }
    // 백테스트 매매 표시
    if (S.bt) for (const mk of S.bt.marks){
      if (mk.i < beg || mk.i >= end) continue;
      const k = S.cs[mk.i], cx = x(mk.i), buy = mk.side === "buy";
      const yy = buy ? y(k.l) + 12 : y(k.h) - 12;
      g.fillStyle = buy ? C.up : C.down; g.beginPath();
      if (buy){ g.moveTo(cx, yy - 6); g.lineTo(cx - 5, yy + 3); g.lineTo(cx + 5, yy + 3); } else { g.moveTo(cx, yy + 6); g.lineTo(cx - 5, yy - 3); g.lineTo(cx + 5, yy - 3); }
      g.fill();
    }
    // 현재가 표시
    const lastK = S.cs[end - 1], ly = y(lastK.c);
    g.fillStyle = lastK.c >= lastK.o ? C.up : C.down; g.fillRect(plotW, ly - 9, axisW, 18);
    g.fillStyle = "#fff"; g.fillText(fmt(lastK.c), plotW + 6, ly);
    g.strokeStyle = g.fillStyle = lastK.c >= lastK.o ? C.up : C.down; g.globalAlpha = .5; g.setLineDash([2, 3]); g.beginPath(); g.moveTo(0, Math.round(ly) + .5); g.lineTo(plotW, Math.round(ly) + .5); g.stroke(); g.setLineDash([]); g.globalAlpha = 1;
    // RSI
    panelFrame(g, rsiT, rsiH, "RSI 14", C, plotW);
    const ry = v => rsiT + (100 - v) / 100 * rsiH;
    g.fillStyle = C.muted; g.globalAlpha = .08; g.fillRect(0, ry(70), plotW, ry(30) - ry(70)); g.globalAlpha = 1;
    for (const lv of [30, 70]){ g.strokeStyle = C.line; g.setLineDash([3, 3]); g.beginPath(); g.moveTo(0, Math.round(ry(lv)) + .5); g.lineTo(plotW, Math.round(ry(lv)) + .5); g.stroke(); g.setLineDash([]); g.fillStyle = C.muted; g.fillText(String(lv), plotW + 6, ry(lv)); }
    lineY(g, S.ind.rsi, C.ma2, 1.5, ry);
    // MACD
    panelFrame(g, macdT, macdH, "MACD 12·26·9", C, plotW);
    let mm = 0; for (let i = beg; i < end; i++) for (const a of [S.ind.macd.line, S.ind.macd.signal, S.ind.macd.hist]) if (a[i] != null) mm = Math.max(mm, Math.abs(a[i]));
    mm = mm || 1; const my = v => macdT + macdH / 2 - v / mm * (macdH / 2 - 6);
    for (let i = beg; i < end; i++){ const v = S.ind.macd.hist[i]; if (v == null) continue; g.fillStyle = v >= 0 ? C.up : C.down; g.globalAlpha = .55; g.fillRect(x(i) - bw * .3, Math.min(my(0), my(v)), Math.max(1, bw * .6), Math.abs(my(v) - my(0))); }
    g.globalAlpha = 1; lineY(g, S.ind.macd.line, C.ma1, 1.3, my); lineY(g, S.ind.macd.signal, C.ma3, 1.3, my);
    // 시간축
    g.fillStyle = C.muted; g.textAlign = "center"; g.textBaseline = "alphabetic";
    const every = Math.max(1, Math.ceil(90 / bw));
    for (let i = beg; i < end; i += every) g.fillText(tlabel(S.cs[i].t), x(i), h - 5);
    // 십자선
    if (S.hover >= beg && S.hover < end){
      const hx = Math.round(x(S.hover)) + .5; g.strokeStyle = C.muted; g.globalAlpha = .6; g.setLineDash([3, 3]);
      g.beginPath(); g.moveTo(hx, 0); g.lineTo(hx, h - timeH); g.stroke(); g.setLineDash([]); g.globalAlpha = 1;
    }
    function line(gg, arr, col, lw){ lineY(gg, arr, col, lw, y); }
    function lineY(gg, arr, col, lw, fy){ gg.strokeStyle = col; gg.lineWidth = lw; gg.beginPath(); let st = false; for (let i = beg; i < end; i++){ const v = arr[i]; if (v == null){ st = false; continue; } if (!st){ gg.moveTo(x(i), fy(v)); st = true; } else gg.lineTo(x(i), fy(v)); } gg.stroke(); gg.lineWidth = 1; }
  }
  function panelFrame(g, t, h, label, C, plotW){ g.strokeStyle = C.line; g.beginPath(); g.moveTo(0, Math.round(t) + .5); g.lineTo(plotW + 200, Math.round(t) + .5); g.stroke(); g.fillStyle = C.muted; g.textAlign = "left"; g.fillText(label, 6, t + 10); }
  function niceStep(r){ const p = Math.pow(10, Math.floor(Math.log10(r))); const f = r / p; return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p; }
  function tlabel(t){ const d = new Date(t); const p = n => String(n).padStart(2, "0"); return S.tf === "D" || S.tf === "W" ? `${d.getFullYear() % 100}.${p(d.getMonth()+1)}.${p(d.getDate())}` : `${p(d.getMonth()+1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; }
  // 상호작용
  let drag = null;
  cv.addEventListener("pointerdown", e => { cv.setPointerCapture(e.pointerId); drag = {x: e.clientX, off: S.view.off}; });
  cv.addEventListener("pointermove", e => {
    if (!geo) return;
    const r = cv.getBoundingClientRect(), mx = e.clientX - r.left;
    if (drag){ const d = Math.round((e.clientX - drag.x) / geo.bw); S.view.off = Math.max(0, Math.min(S.cs.length - S.view.count, drag.off + d)); }
    const i = geo.beg + Math.floor(mx / geo.bw);
    S.hover = mx < geo.plotW ? i : -1; draw(); showTip(e, r);
  });
  cv.addEventListener("pointerup", () => drag = null);
  cv.addEventListener("pointerleave", () => { S.hover = -1; tip.hidden = true; draw(); });
  cv.addEventListener("wheel", e => { e.preventDefault(); S.view.count = Math.max(30, Math.min(S.cs.length, Math.round(S.view.count * (e.deltaY > 0 ? 1.12 : 0.89)))); S.view.off = Math.min(S.view.off, Math.max(0, S.cs.length - S.view.count)); draw(); }, {passive: false});
  cv.addEventListener("dblclick", () => { S.view.off = 0; S.view.count = Math.min(120, S.cs.length); draw(); });
  new ResizeObserver(() => draw()).observe(wrap);
  function showTip(e, r){
    const i = S.hover; if (i < 0 || !S.cs[i]){ tip.hidden = true; return; }
    const k = S.cs[i], d = k.c - k.o, I = S.ind;
    tip.hidden = false;
    tip.innerHTML = `<b>${tlabel(k.t)}</b><span>시 ${fmt(k.o)}</span><span>고 ${fmt(k.h)}</span><span>저 ${fmt(k.l)}</span><span class="${d >= 0 ? "up" : "down"}">종 ${fmt(k.c)} (${pct(k.c / k.o - 1)})</span><span>거래량 ${big(k.v)}</span>${I.rsi[i] != null ? `<span>RSI ${I.rsi[i].toFixed(1)}</span>` : ""}`;
    const mx = e.clientX - r.left, left = mx > r.width / 2 ? mx - tip.offsetWidth - 14 : mx + 14;
    tip.style.left = left + "px"; tip.style.top = "10px";
  }

  /* ---------- 퀀트 점수 ---------- */
  function renderScore(){
    const el = $("#tr-score");
    if (!S.q){ el.innerHTML = `<p class="empty">차트를 불러오면 계산합니다.</p>`; return; }
    const {score, label, factors} = S.q, pos = (score + 100) / 2;
    const cls = score >= 20 ? "up" : score <= -20 ? "down" : "";
    el.innerHTML = `
      <div class="gauge"><div class="gauge-top"><span class="num gauge-v ${cls}">${score > 0 ? "+" : ""}${score}</span><span class="pill ${cls}">${label}</span></div>
        <div class="gauge-bar"><i style="left:${pos}%"></i></div><div class="gauge-lab small"><span>하락 우위</span><span>중립</span><span>상승 우위</span></div></div>
      <div class="factors">${factors.map(f => `<div class="factor"><span>${esc(f.label)}<span class="small"> · ${esc(f.note)}</span></span><span class="num ${f.pts > 0 ? "up" : f.pts < 0 ? "down" : ""}">${f.pts > 0 ? "+" : ""}${f.pts}</span></div>`).join("")}</div>
      ${S.lv ? `<div class="lvls"><div><label class="small">저항</label>${S.lv.res.map(l => `<span class="num up">${fmt(l.p)}</span>`).join("") || "<span class='small'>–</span>"}</div><div><label class="small">지지</label>${S.lv.sup.map(l => `<span class="num down">${fmt(l.p)}</span>`).join("") || "<span class='small'>–</span>"}</div></div>` : ""}`;
  }

  /* ---------- AI 분석 ---------- */
  function snapshot(){
    const n = S.cs.length - 1, I = S.ind, p = S.cs[n].c, m = {...cur(), ...(S.tick.get(S.market) || {})};
    const r = v => v == null ? null : +(+v).toPrecision(6);
    return {
      거래소: X().label, 종목: `${m.name} (${S.market})`, 봉: TFS.find(t => t[0] === S.tf)[1], 현재가: r(p), 통화: X().quote,
      "24시간_변동률": m.chg != null ? +(m.chg * 100).toFixed(2) : null,
      지표: {MA20: r(I.ma20[n]), MA60: r(I.ma60[n]), MA120: r(I.ma120[n]), RSI14: r(I.rsi[n]), MACD: r(I.macd.line[n]), MACD시그널: r(I.macd.signal[n]), MACD히스토그램: r(I.macd.hist[n]), 볼린저상단: r(I.bb.up[n]), 볼린저하단: r(I.bb.lo[n]), "ATR_%": I.atr[n] ? +(I.atr[n] / p * 100).toFixed(2) : null, 거래량_20평균대비: I.vma[n] ? +(S.cs[n].v / I.vma[n]).toFixed(2) : null},
      퀀트점수: {점수: S.q.score, 판단: S.q.label, 근거: S.q.factors.map(f => `${f.label}(${f.pts > 0 ? "+" : ""}${f.pts})`)},
      저항: S.lv.res.map(l => r(l.p)), 지지: S.lv.sup.map(l => r(l.p)),
      최근_종가_40개: S.cs.slice(-40).map(k => r(k.c)),
      기간_고가: r(Math.max(...S.cs.map(k => k.h))), 기간_저가: r(Math.min(...S.cs.map(k => k.l))),
      백테스트: S.bt ? {전략: STRATS[S.btKey].name, 수익률: +(S.bt.ret * 100).toFixed(2), 보유수익률: +(S.bt.hold * 100).toFixed(2), 최대낙폭: +(S.bt.mdd * 100).toFixed(2), 승률: +(S.bt.win * 100).toFixed(1), 거래수: S.bt.trades.length} : null
    };
  }
  async function runAI(){
    const el = $("#tr-ai");
    if (!S.cs.length){ toast("차트를 먼저 불러오세요"); return; }
    if (!brain.ready()){ el.innerHTML = `<p class="err">AI 두뇌가 준비되지 않았습니다. 'AI 모델' 메뉴에서 모델을 켜세요. 복잡한 분석은 '고성능 오픈모델' 두뇌를 추천합니다.</p><button class="btn primary" data-go="models">AI 모델 열기</button>`; return; }
    S.aiCtl?.abort(); S.aiCtl = new AbortController();
    el.innerHTML = `<div class="ai-wait"><span class="spin"></span><span>${esc(brain.label())}가 차트를 읽는 중…</span></div><pre class="ai-stream" id="tr-ai-stream"></pre><button class="btn" id="tr-ai-stop">멈추기</button>`;
    const data = snapshot();
    const messages = [
      {role: "system", content: "너는 신중한 암호화폐 기술적 분석가다. 주어진 숫자 데이터만 근거로 분석하고, 데이터에 없는 뉴스·사건은 지어내지 않는다. 확률적 표현을 쓰고 확신하지 않는다. 가격은 데이터의 통화 단위로 적는다. 반드시 JSON 하나만 출력한다."},
      {role: "user", content: `다음 시장 데이터를 분석해 아래 JSON 형식으로만 답하라.\n\n데이터:\n${JSON.stringify(data)}\n\n형식:\n{"headline":"한 줄 결론(30자 이내)","trend":"상승|하락|횡보","summary":"3~4문장 요약","bull":{"trigger":"상승 시나리오가 맞으려면 필요한 조건","target":가격},"bear":{"trigger":"하락 시나리오 조건","target":가격},"plan":{"entry":"진입 고려 구간 설명","stop":가격,"targets":[가격,가격]},"risks":["위험 요인1","위험 요인2"],"confidence":0~100 정수}`}
    ];
    let raw = "";
    try {
      raw = await brain.text(messages, {signal: S.aiCtl.signal, temperature: 0.3, onText: t => { const s = root.querySelector("#tr-ai-stream"); if (s){ s.textContent = t.slice(-600); } }});
      S.aiRaw = raw; S.ai = parseJSON(raw); S.aiAt = Date.now();
    } catch (e){
      if (S.aiCtl.signal.aborted){ el.innerHTML = `<p class="empty">분석을 멈췄습니다.</p><button class="btn primary" id="tr-ai-go">AI 분석 실행</button>`; return; }
      S.ai = null; S.aiRaw = ""; el.innerHTML = `<p class="err">${esc(e.message || "AI 분석 실패")}</p><button class="btn primary" id="tr-ai-go">다시 시도</button>`; return;
    }
    renderAI();
  }
  function parseJSON(t){
    const s = String(t || "").replace(/<think>[\s\S]*?<\/think>/g, "");
    const tries = [s, (s.match(/```(?:json)?\s*([\s\S]*?)```/) || [])[1], s.slice(s.indexOf("{"), s.lastIndexOf("}") + 1)];
    for (const x of tries){ if (!x) continue; try { const o = JSON.parse(x); if (o && typeof o === "object") return o; } catch(e){} }
    return null;
  }
  function renderAI(){
    const el = $("#tr-ai"), a = S.ai;
    if (!a){
      el.innerHTML = S.aiRaw ? `<div class="md">${md(S.aiRaw)}</div><p class="small">형식에 맞지 않는 답이라 원문을 표시했습니다. 작은 모델보다 고성능 두뇌가 정확합니다.</p><button class="btn" id="tr-ai-go">다시 분석</button>` : `<p class="empty">현재 차트와 지표를 AI가 해석합니다.</p><button class="btn primary" id="tr-ai-go">AI 분석 실행</button>`;
      return;
    }
    const conf = Math.max(0, Math.min(100, +a.confidence || 0));
    const tcls = /상승/.test(a.trend) ? "up" : /하락/.test(a.trend) ? "down" : "";
    const v = x => typeof x === "number" ? fmt(x) : esc(x ?? "–");
    el.innerHTML = `
      <div class="ai-head"><span class="pill ${tcls}">${esc(a.trend || "–")}</span><b>${esc(a.headline || "")}</b></div>
      <p class="ai-sum">${esc(a.summary || "")}</p>
      <div class="scen"><div class="up-b"><label>상승 시나리오</label><p>${esc(a.bull?.trigger || "–")}</p><span class="num up">목표 ${v(a.bull?.target)}</span></div>
        <div class="down-b"><label>하락 시나리오</label><p>${esc(a.bear?.trigger || "–")}</p><span class="num down">목표 ${v(a.bear?.target)}</span></div></div>
      <div class="plan"><div><label>진입 고려</label><span>${esc(a.plan?.entry || "–")}</span></div><div><label>손절</label><span class="num down">${v(a.plan?.stop)}</span></div><div><label>목표</label><span class="num up">${(a.plan?.targets || []).map(v).join(" · ") || "–"}</span></div></div>
      ${(a.risks || []).length ? `<ul class="risks">${a.risks.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
      <div class="conf"><label class="small">AI 확신도 ${conf}%</label><div class="progress"><i style="width:${conf}%"></i></div></div>
      <div class="row"><button class="btn" id="tr-ai-go">다시 분석</button><span class="small">${esc(brain.label())} · ${new Date(S.aiAt).toLocaleTimeString("ko-KR", {hour:"2-digit", minute:"2-digit"})}</span></div>`;
  }
  root.addEventListener("click", e => {
    if (e.target.id === "tr-ai-go") runAI();
    if (e.target.id === "tr-retry" || e.target.id === "tr-retry2"){ (async () => { if (!S.list.length) await loadList(); await loadCandles(); })(); }
    if (e.target.id === "tr-ai-stop") S.aiCtl?.abort();
    const tb = e.target.closest("[data-tab]"); if (tb){ S.tab = tb.dataset.tab; syncTools(); S.tab === "bt" ? renderBT() : renderPaper(); }
  });

  /* ---------- 백테스트 ---------- */
  function btParams(){ const st = STRATS[S.btKey]; const saved = S.btP[S.btKey] || {}; return Object.fromEntries(st.params.map(([k, , d]) => [k, saved[k] ?? d])); }
  function renderBT(){
    const el = $("#tr-bt"), st = STRATS[S.btKey], P = btParams(), r = S.bt;
    el.innerHTML = `
      <div class="bt-grid">
        <div class="bt-form">
          <div class="form" style="grid-template-columns:1fr">
            <label>전략<select id="bt-key">${Object.entries(STRATS).map(([k, s]) => `<option value="${k}"${k === S.btKey ? " selected" : ""}>${s.name}</option>`).join("")}</select></label>
          </div>
          <p class="small">${esc(st.desc)} 신호가 난 다음 봉 시가에 체결, 한 번에 전액 매수·매도합니다.</p>
          <div class="form">
            ${st.params.map(([k, l, , mn, mx]) => `<label>${l}<input type="number" data-bp="${k}" value="${P[k]}" min="${mn}" max="${mx}" step="${k === "k" ? 0.5 : 1}"></label>`).join("")}
            <label>수수료 %(편도)<input type="number" data-bo="fee" value="${S.btOpt.fee}" min="0" max="1" step="0.01"></label>
            <label>손절 % (0=안 씀)<input type="number" data-bo="sl" value="${S.btOpt.sl}" min="0" max="50" step="0.5"></label>
            <label>익절 % (0=안 씀)<input type="number" data-bo="tp" value="${S.btOpt.tp}" min="0" max="200" step="0.5"></label>
          </div>
          <div class="row"><button class="btn primary" id="bt-run" ${S.cs.length ? "" : "disabled"}>백테스트 실행</button><span class="small">${S.cs.length ? `${S.cs.length}개 캔들 · ${tlabel(S.cs[0].t)} ~ ${tlabel(S.cs[S.cs.length-1].t)}` : "차트 데이터 없음"}</span></div>
        </div>
        <div class="bt-out">${r ? `
          <div class="kpis bt-kpis">
            <div class="kpi"><label>전략 수익률</label><span class="v ${r.ret >= 0 ? "up" : "down"}">${pct(r.ret)}</span><span class="s">그냥 보유 ${pct(r.hold)}</span></div>
            <div class="kpi"><label>초과 성과</label><span class="v ${r.ret - r.hold >= 0 ? "up" : "down"}">${pct(r.ret - r.hold)}</span><span class="s">전략 − 보유</span></div>
            <div class="kpi"><label>최대 낙폭</label><span class="v down">${pct(-r.mdd)}</span><span class="s">보유 시 ${pct(-r.holdMdd)}</span></div>
            <div class="kpi"><label>승률</label><span class="v">${(r.win * 100).toFixed(0)}%</span><span class="s">거래 ${r.trades.length}회${r.open ? " · 보유 중" : ""}</span></div>
            <div class="kpi"><label>손익비</label><span class="v">${r.pf === Infinity ? "∞" : r.pf.toFixed(2)}</span><span class="s">이익 합 ÷ 손실 합</span></div>
          </div>
          <div class="chart" id="bt-eq"></div>
          <div class="legend-row small"><span><i style="background:var(--accent)"></i>전략 자산</span><span><i style="background:var(--muted)"></i>그냥 보유</span><span>차트의 ▲▼는 매수·매도 지점입니다.</span></div>
          ${r.trades.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>매수</th><th>매도</th><th class="r">매수가</th><th class="r">매도가</th><th class="r">수익률</th><th>사유</th></tr></thead><tbody>${r.trades.slice(-12).reverse().map(t => `<tr><td class="num">${tlabel(t.t0)}</td><td class="num">${tlabel(t.t1)}</td><td class="r num">${fmt(t.entry)}</td><td class="r num">${fmt(t.exit)}</td><td class="r num ${t.ret >= 0 ? "up" : "down"}">${pct(t.ret)}</td><td>${t.why}</td></tr>`).join("")}</tbody></table></div>` : `<p class="empty">이 기간에는 매매 신호가 없었습니다.</p>`}
          <p class="small">과거 성과는 미래 수익을 보장하지 않습니다. 슬리피지와 체결 지연은 반영하지 않았습니다.</p>` : `<p class="empty">전략과 조건을 정하고 실행하면, 지금 차트 데이터로 과거에 이 전략을 썼을 때의 결과를 계산합니다.</p>`}</div>
      </div>`;
    if (r) drawEquity($("#bt-eq"), r);
  }
  $("#tr-bt").addEventListener("change", e => {
    const t = e.target;
    if (t.id === "bt-key"){ S.btKey = t.value; ls.set("tr:bt", S.btKey); S.bt = null; renderBT(); draw(); }
    if (t.dataset.bp){ S.btP[S.btKey] = {...btParams(), [t.dataset.bp]: +t.value}; ls.set("tr:btp", S.btP); }
    if (t.dataset.bo){ S.btOpt[t.dataset.bo] = +t.value; ls.set("tr:bto", S.btOpt); }
  });
  $("#tr-bt").addEventListener("click", e => {
    if (e.target.id !== "bt-run") return;
    S.bt = backtest(S.cs, S.btKey, btParams(), S.btOpt); renderBT(); draw(); ctx.onStat?.("backtest");
  });
  function drawEquity(el, r){
    const W = 640, H = 170, pl = 44, pr = 8, pt = 10, pb = 22;
    const n = r.eq.length, c0 = S.cs[0].c, hold = S.cs.map(k => k.c / c0);
    const all = [...r.eq, ...hold], mx = Math.max(...all), mn = Math.min(...all);
    const X = i => pl + i / (n - 1) * (W - pl - pr), Y = v => pt + (mx - v) / ((mx - mn) || 1) * (H - pt - pb);
    const path = arr => arr.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join("");
    const ticks = [mn, (mn + mx) / 2, mx];
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="자산 곡선">
      ${ticks.map(v => `<line x1="${pl}" x2="${W-pr}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)" stroke-dasharray="2 3"/><text x="${pl-6}" y="${Y(v)+4}" text-anchor="end" font-size="10.5" fill="var(--muted)" font-family="var(--f-mono)">${pct(v - 1, 0)}</text>`).join("")}
      <line x1="${pl}" x2="${W-pr}" y1="${Y(1)}" y2="${Y(1)}" stroke="var(--muted)" stroke-width="1"/>
      <path d="${path(hold)}" fill="none" stroke="var(--muted)" stroke-width="1.5" opacity=".7"/>
      <path d="${path(r.eq)} L${X(n-1)},${Y(mn)} L${X(0)},${Y(mn)} Z" fill="var(--accent)" opacity=".08"/>
      <path d="${path(r.eq)}" fill="none" stroke="var(--accent)" stroke-width="2"/>
      <circle cx="${X(n-1)}" cy="${Y(r.eq[n-1])}" r="4" fill="var(--accent)"/>
      <text x="${pl}" y="${H-6}" font-size="10.5" fill="var(--muted)">${tlabel(S.cs[0].t)}</text><text x="${W-pr}" y="${H-6}" text-anchor="end" font-size="10.5" fill="var(--muted)">${tlabel(S.cs[n-1].t)}</text>
    </svg>`;
  }

  /* ---------- 모의투자 ---------- */
  const acctKey = () => "tr:acct:" + S.ex;
  const START = () => X().quote === "KRW" ? 10_000_000 : 10_000;
  function acct(){ return ls.get(acctKey(), null) || {cash: START(), pos: {}, hist: [], start: START(), created: Date.now()}; }
  function saveAcct(a){ ls.set(acctKey(), a); }
  function priceOf(id){ const t = S.tick.get(id); if (t && t.price) return t.price; if (id === S.market && S.cs.length) return S.cs[S.cs.length-1].c; return null; }
  function renderPaper(){
    const a = acct(), el = $("#tr-paper"), fee = X().fee / 100;
    const rows = Object.entries(a.pos).map(([id, p]) => { const px = priceOf(id) ?? p.avg; return {id, ...p, px, val: p.qty * px, pnl: px / p.avg - 1}; });
    const total = a.cash + rows.reduce((s, r) => s + r.val, 0), ret = total / a.start - 1;
    const here = a.pos[S.market], px = priceOf(S.market);
    el.innerHTML = `
      <div class="bt-grid">
        <div class="bt-form">
          <div class="seg side-seg"><button data-side="buy" aria-pressed="${S.side === "buy"}">매수</button><button data-side="sell" aria-pressed="${S.side === "sell"}">매도</button></div>
          <div class="order">
            <div class="line"><span class="small">종목</span><b>${esc(cur().name)} <span class="small">${esc(S.market)}</span></b></div>
            <div class="line"><span class="small">현재가</span><span class="num">${fmt(px)}</span></div>
            <div class="line"><span class="small">${S.side === "buy" ? "주문 가능" : "보유 수량"}</span><span class="num">${S.side === "buy" ? fmt(a.cash) + " " + X().quote : (here ? here.qty.toFixed(8).replace(/\.?0+$/, "") : "0")}</span></div>
            <div class="form" style="grid-template-columns:1fr"><label>${S.side === "buy" ? `주문 금액 (${X().quote})` : "매도 비율 (%)"}<input type="number" id="pp-amt" min="0" step="any" value="${S.side === "buy" ? Math.floor(a.cash * 0.25) : 100}"></label></div>
            <div class="row pct-row">${[10, 25, 50, 100].map(p => `<button class="btn" data-pp="${p}">${p}%</button>`).join("")}</div>
            <button class="btn ${S.side === "buy" ? "buy" : "sell"}" id="pp-go" ${px ? "" : "disabled"}>${S.side === "buy" ? "모의 매수" : "모의 매도"}</button>
            <p class="small">수수료 ${X().fee}% 적용 · 실제 돈이 오가지 않는 연습용입니다.</p>
          </div>
        </div>
        <div class="bt-out">
          <div class="kpis bt-kpis">
            <div class="kpi"><label>총 자산</label><span class="v">${fmt(total)}</span><span class="s">${X().quote} · 시작 ${fmt(a.start)}</span></div>
            <div class="kpi"><label>수익률</label><span class="v ${ret >= 0 ? "up" : "down"}">${pct(ret)}</span><span class="s">${fmt(total - a.start)} ${X().quote}</span></div>
            <div class="kpi"><label>현금</label><span class="v">${fmt(a.cash)}</span><span class="s">${(a.cash / total * 100).toFixed(0)}% 비중</span></div>
            <div class="kpi"><label>거래 횟수</label><span class="v">${a.hist.length}</span><span class="s">${a.hist.length ? "최근 " + tlabel(a.hist[a.hist.length-1].t) : "아직 없음"}</span></div>
          </div>
          ${rows.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>종목</th><th class="r">수량</th><th class="r">평균가</th><th class="r">현재가</th><th class="r">평가금액</th><th class="r">수익률</th></tr></thead><tbody>${rows.map(r => `<tr><td><button class="link" data-mkt2="${esc(r.id)}">${esc(r.id)}</button></td><td class="r num">${r.qty.toPrecision(6)}</td><td class="r num">${fmt(r.avg)}</td><td class="r num">${fmt(r.px)}</td><td class="r num">${fmt(r.val)}</td><td class="r num ${r.pnl >= 0 ? "up" : "down"}">${pct(r.pnl)}</td></tr>`).join("")}</tbody></table></div>` : `<p class="empty">보유 중인 코인이 없습니다. 왼쪽에서 모의 매수를 해 보세요.</p>`}
          ${a.hist.length ? `<details class="hist"><summary class="small">거래 내역 ${a.hist.length}건</summary><div class="tbl-wrap"><table class="tbl"><tbody>${a.hist.slice(-20).reverse().map(h => `<tr><td class="num">${tlabel(h.t)}</td><td class="${h.side === "buy" ? "up" : "down"}">${h.side === "buy" ? "매수" : "매도"}</td><td>${esc(h.id)}</td><td class="r num">${fmt(h.price)}</td><td class="r num">${h.qty.toPrecision(6)}</td></tr>`).join("")}</tbody></table></div></details>` : ""}
          <div class="row"><button class="btn danger" id="pp-reset">계좌 초기화</button></div>
        </div>
      </div>`;
  }
  $("#tr-paper").addEventListener("click", e => {
    const t = e.target, a = acct(), px = priceOf(S.market), fee = X().fee / 100;
    if (t.dataset.side){ S.side = t.dataset.side; renderPaper(); }
    if (t.dataset.pp){ const p = +t.dataset.pp / 100; $("#pp-amt").value = S.side === "buy" ? Math.floor(a.cash * p) : Math.round(p * 100); }
    if (t.dataset.mkt2){ S.market = t.dataset.mkt2; ls.set("tr:mkt:" + S.ex, S.market); renderList(); renderHead(); loadCandles(); }
    if (t.id === "pp-go" && px){
      const v = +$("#pp-amt").value;
      if (S.side === "buy"){
        if (!(v > 0) || v > a.cash + 1e-9){ toast("주문 금액을 확인하세요"); return; }
        const qty = v * (1 - fee) / px, p = a.pos[S.market] || {qty: 0, avg: 0};
        p.avg = (p.avg * p.qty + px * qty) / (p.qty + qty); p.qty += qty; a.pos[S.market] = p; a.cash -= v;
        a.hist.push({t: Date.now(), id: S.market, side: "buy", price: px, qty}); toast(`${S.market} ${fmt(v)} 모의 매수`);
      } else {
        const p = a.pos[S.market]; if (!p){ toast("보유 수량이 없습니다"); return; }
        const qty = p.qty * Math.min(100, Math.max(0, v)) / 100; if (!(qty > 0)){ toast("매도 비율을 확인하세요"); return; }
        a.cash += qty * px * (1 - fee); p.qty -= qty; if (v >= 100 || p.qty <= 1e-12) delete a.pos[S.market];
        a.hist.push({t: Date.now(), id: S.market, side: "sell", price: px, qty}); toast(`${S.market} 모의 매도`);
      }
      saveAcct(a); renderPaper(); ctx.onStat?.("paper");
    }
    if (t.id === "pp-reset"){ if (t.dataset.c !== "1"){ t.dataset.c = "1"; t.textContent = "한 번 더 누르면 초기화"; return; } ls.set(acctKey(), null); renderPaper(); toast("모의투자 계좌를 초기화했습니다"); }
  });

  /* ---------- 전체 ---------- */
  function renderAll(){ renderHead(); renderScore(); renderAI(); syncTools(); S.tab === "bt" ? renderBT() : renderPaper(); draw(); }
  let booted = false;
  return {
    async show(){
      S.visible = true; syncTools(); draw();
      if (!booted){ booted = true; renderAll(); await loadList(); await loadCandles(); }
      clearInterval(S.t1); S.t1 = setInterval(refresh, 10000);
    },
    hide(){ S.visible = false; clearInterval(S.t1); },
    summary(){ const out = {}; for (const ex of Object.keys(EX)){ const a = ls.get("tr:acct:" + ex, null); if (a){ let v = a.cash; for (const [id, p] of Object.entries(a.pos)) v += p.qty * p.avg; out[ex] = {quote: EX[ex].quote, start: a.start, total: v, trades: a.hist.length}; } } return out; },
    state: S
  };
}
