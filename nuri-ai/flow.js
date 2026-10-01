// 주문 흐름: 호가 벽 · 고래 체결 · 선물 포지션 흐름 · 파생 이력 · 청산 구간 추정
// 모든 숫자는 코드가 계산하고, AI에게는 짧은 한국어 설명(text, 1,800자 미만)과 한 줄 요약(summary)만 넘긴다.
// 반환: {data, text, summary}. 시험할 때는 opts.fetchJson(url) · opts.apiBase(name) 를 주입한다.
// 거래소 주소는 engine.js 의 apiBase 를 쓴다 (실행기 연결 시 프록시 경유).

/* ============ 공용 ============ */
const DIRECT = {upbit: "https://api.upbit.com/v1", binance: "https://api.binance.com/api/v3", binancef: "https://fapi.binance.com"};
const LABEL = {binancef: "바이낸스 선물", binance: "바이낸스 현물", upbit: "업비트"};
const MAX_TEXT = 1790;
let engBase = null;
async function defaultFetch(url){
  const r = await fetch(url, {headers: {accept: "application/json"}});
  if (!r.ok){
    let msg = ""; try { const j = await r.json(); msg = j?.msg || j?.error?.message || ""; } catch(e){}
    const e = new Error(`거래소 요청 실패 (${r.status}${msg ? " · " + msg : ""})`); e.status = r.status; throw e;
  }
  return r.json();
}
// 주입한 fetchJson·apiBase 가 있으면 그것을, 없으면 engine.js(브라우저) → 직접 주소 순서로
function mkIO(a = {}, o = {}){
  const fetchJson = o.fetchJson || a.fetchJson || defaultFetch, apiBase = o.apiBase || a.apiBase;
  const baseOf = async ex => {
    if (apiBase) return apiBase(ex);
    if (!engBase){ try { engBase = (await import("./engine.js")).apiBase; } catch(e){ engBase = n => DIRECT[n]; } }
    return engBase(ex);
  };
  return {fetchJson, get: async (ex, path) => fetchJson(await baseOf(ex) + path), pauseMs: o.pauseMs ?? a.pauseMs ?? 120, now: o.now ?? a.now};
}
const sleep = ms => ms > 0 ? new Promise(r => setTimeout(r, ms)) : Promise.resolve();
const exOf = e => {
  const s = String(e || "binancef").toLowerCase().replace(/[\s_-]/g, "");
  if (/^(binancef|binancefutures|futures|usdm|fapi|선물)$/.test(s)) return "binancef";
  if (/^(binance|binancespot|spot|현물)$/.test(s)) return "binance";
  if (/^(upbit|업비트)$/.test(s)) return "upbit";
  throw new Error("지원하지 않는 거래소입니다: " + e + " (binancef · binance · upbit)");
};
// 심볼 변환: KRW-BTC ↔ BTCUSDT
const QUOTES = /(USDT|USDC|BUSD|FDUSD|TUSD|BTC|ETH|BNB|EUR|TRY)$/;
const binSymbol = s => {
  s = String(s || "BTCUSDT").toUpperCase().trim();
  if (/^[A-Z]+-/.test(s)) return s.split("-")[1] + "USDT";
  s = s.replace(/[/_-]/g, "");
  const m = QUOTES.exec(s); return m && s.length > m[1].length ? s : s + "USDT";
};
const upbitMarket = s => {
  s = String(s || "BTCUSDT").toUpperCase().trim();
  if (/^[A-Z]+-[A-Z0-9]+$/.test(s)) return s;
  const b = s.replace(/[/_-]/g, "").replace(/(USDT|USDC|BUSD|FDUSD|TUSD|KRW|USD)$/, "");
  return "KRW-" + (b || "BTC");
};
const clamp = (v, lo = -1, hi = 1) => Math.max(lo, Math.min(hi, v));
const num = v => { const x = +v; return Number.isFinite(x) ? x : null; };
const r2 = (v, d = 2) => v == null || !Number.isFinite(v) ? null : Math.round(v * 10 ** d) / 10 ** d;
const px = v => v == null ? "–" : v.toLocaleString("ko-KR", {maximumFractionDigits: v >= 1000 ? 0 : v >= 100 ? 1 : v >= 1 ? 3 : 6});
const sp = (v, d = 2) => v == null || !Number.isFinite(v) ? "–" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(d) + "%";
const money = (v, q = "USDT") => {
  if (v == null || !Number.isFinite(v)) return "–";
  const a = Math.abs(v), s = v < 0 ? "−" : "", ko = x => x.toLocaleString("ko-KR");
  if (q === "KRW") return s + (a >= 1e12 ? (a / 1e12).toFixed(2) + "조" : a >= 1e8 ? (a / 1e8).toFixed(1) + "억" : a >= 1e4 ? ko(Math.round(a / 1e4)) + "만" : ko(Math.round(a))) + " 원";
  return s + (a >= 1e8 ? (a / 1e8).toFixed(2) + "억" : a >= 1e4 ? ko(Math.round(a / 1e4)) + "만" : ko(Math.round(a))) + " 달러";
};
const kst = (t, full) => { const s = new Date(+t + 9 * 36e5).toISOString(); return full ? s.slice(5, 16).replace("T", " ") : s.slice(11, 19); };
// 줄 단위로 잘라 글자 수 제한을 지킨다
function clipLines(text, max = MAX_TEXT){
  if (text.length <= max) return text;
  const out = []; let n = 0;
  for (const ln of text.split("\n")){ if (n + ln.length + 1 > max) break; out.push(ln); n += ln.length + 1; }
  return out.length ? out.join("\n") : text.slice(0, max);
}
const done = (data, lines, summary) => ({data, text: clipLines(lines.filter(Boolean).join("\n")), summary});
// 하위 호출 하나가 실패해도 나머지는 계속
const safe = p => p.then(v => ({ok: true, v}), e => ({ok: false, err: e?.message || String(e)}));

/* ============ 1. 호가 (벽 · 밴드 · 불균형) ============ */
const FUT_DEPTH = [5, 10, 20, 50, 100, 500, 1000], SPOT_DEPTH = [5, 10, 20, 50, 100, 500, 1000, 5000];
const snapDepth = (d, list) => list.find(x => x >= d) || list[list.length - 1];
const BANDS = [0.5, 1, 2];

function analyzeBook(bidsIn, asksIn, {exchange, symbol, quote}){
  const bids = bidsIn.filter(([p, q]) => p > 0 && q > 0).sort((a, b) => b[0] - a[0]);
  const asks = asksIn.filter(([p, q]) => p > 0 && q > 0).sort((a, b) => a[0] - b[0]);
  if (!bids.length || !asks.length) throw new Error("호가가 비어 있습니다: " + symbol);
  const bb = bids[0][0], ba = asks[0][0], mid = (bb + ba) / 2;
  const spreadBps = (ba - bb) / mid * 1e4;
  const cover = {bidPct: (1 - bids[bids.length - 1][0] / mid) * 100, askPct: (asks[asks.length - 1][0] / mid - 1) * 100};
  // ±b% 안쪽 명목금액(가격×수량)과 불균형 = (매수−매도)/(매수+매도)
  const bands = BANDS.map(b => {
    const bid = bids.reduce((s, [p, q]) => p >= mid * (1 - b / 100) ? s + p * q : s, 0);
    const ask = asks.reduce((s, [p, q]) => p <= mid * (1 + b / 100) ? s + p * q : s, 0);
    return {band: b, bid, ask, ratio: ask ? bid / ask : null, imbalance: bid + ask ? (bid - ask) / (bid + ask) : 0,
      complete: cover.bidPct >= b && cover.askPct >= b};
  });
  // 벽: 중간가의 0.1% 폭 버킷으로 묶어 명목금액이 큰 순서 5개
  const walls = levels => {
    const w = mid * 0.001, m = new Map();
    for (const [p, q] of levels){
      const k = Math.floor(p / w), g = m.get(k) || {qty: 0, pq: 0, notional: 0, levels: 0};
      g.qty += q; g.pq += p * q; g.notional += p * q; g.levels++; m.set(k, g);
    }
    const all = [...m.values()], avg = all.reduce((s, g) => s + g.notional, 0) / (all.length || 1);
    return all.sort((a, b) => b.notional - a.notional).slice(0, 5).map(g => {
      const price = g.pq / g.qty;
      return {price, qty: g.qty, notional: g.notional, distPct: (price / mid - 1) * 100, xAvg: avg ? g.notional / avg : null, levels: g.levels};
    });
  };
  const bidWalls = walls(bids), askWalls = walls(asks);
  // 해석
  const b1 = bands[1], notes = [];
  const wb = bidWalls[0], wa = askWalls[0];
  if (wb) notes.push(`매수벽 ${px(wb.price)}(${sp(wb.distPct)})에 ${money(wb.notional, quote)}`);
  if (wa) notes.push(`매도벽 ${px(wa.price)}(${sp(wa.distPct)})에 ${money(wa.notional, quote)}`);
  const imb = b1.imbalance;
  notes.push(imb > 0.2 ? "±1% 안 매도 쪽이 얇음(매수 우위)" : imb < -0.2 ? "±1% 안 매수 쪽이 얇음(매도 우위)" : "±1% 안 양쪽이 비슷함");
  const i2 = bands[2].imbalance;
  if (Math.abs(i2) > 0.3 && (Math.abs(imb) <= 0.2 || Math.sign(i2) !== Math.sign(imb))) notes.push(`±2%까지는 ${i2 > 0 ? "매수" : "매도"} 쪽이 두꺼움(${sp(i2 * 100, 0)}${bands[2].complete ? "" : ", 부분 집계"})`);
  if (spreadBps > 5) notes.push(`스프레드 ${spreadBps.toFixed(1)}bp로 넓음(유동성 약함)`);
  const interpretation = notes.join(" · ");
  const data = {exchange, symbol, quote, mid, bestBid: bb, bestAsk: ba, spreadBps, coverage: cover, bands, bidWalls, askWalls,
    levels: {bids: bids.length, asks: asks.length}, interpretation, t: Date.now()};
  const wl = ws => ws.map(w => `${px(w.price)}(${sp(w.distPct)}) ${money(w.notional, quote)}${w.xAvg ? ` ×${w.xAvg.toFixed(1)}` : ""}`).join(" · ");
  const lines = [
    `[호가] ${LABEL[exchange]} ${symbol} · 중간가 ${px(mid)} · 스프레드 ${spreadBps.toFixed(2)}bp · 집계 범위 매수 ${sp(-cover.bidPct)} / 매도 ${sp(cover.askPct)} (${bids.length}/${asks.length}호가)`,
    ...bands.map(b => `±${b.band}%: 매수 ${money(b.bid, quote)} / 매도 ${money(b.ask, quote)} · 비율 ${b.ratio == null ? "–" : b.ratio.toFixed(2)} · 불균형 ${sp(b.imbalance * 100, 0)}${b.complete ? "" : " (호가 범위 밖, 부분 집계)"}`),
    `매수벽(0.1% 묶음, ×평균): ${wl(bidWalls)}`,
    `매도벽: ${wl(askWalls)}`,
    `해석: ${interpretation}`
  ];
  const summary = `호가 ${symbol}: ±1% 불균형 ${sp(imb * 100, 0)}${wb ? ` · 최대 매수벽 ${px(wb.price)}` : ""}${wa ? ` · 최대 매도벽 ${px(wa.price)}` : ""}`;
  return done(data, lines, summary);
}

export async function orderBook({symbol = "BTCUSDT", exchange = "binancef", depth = 500, ...a} = {}, opts = {}){
  const io = mkIO(a, opts), ex = exOf(exchange);
  if (ex === "upbit"){
    const mk = upbitMarket(symbol), j = await io.get("upbit", `/orderbook?markets=${mk}`);
    const u = (Array.isArray(j) ? j[0] : j)?.orderbook_units;
    if (!u?.length) throw new Error("업비트 호가가 비어 있습니다: " + mk);
    return analyzeBook(u.map(x => [+x.bid_price, +x.bid_size]), u.map(x => [+x.ask_price, +x.ask_size]), {exchange: ex, symbol: mk, quote: "KRW"});
  }
  const sym = binSymbol(symbol), lim = snapDepth(+depth || 500, ex === "binancef" ? FUT_DEPTH : SPOT_DEPTH);
  const j = await io.get(ex, ex === "binancef" ? `/fapi/v1/depth?symbol=${sym}&limit=${lim}` : `/depth?symbol=${sym}&limit=${lim}`);
  if (!j?.bids || !j?.asks) throw new Error("호가 응답 형식이 다릅니다: " + sym);
  return analyzeBook(j.bids.map(([p, q]) => [+p, +q]), j.asks.map(([p, q]) => [+p, +q]), {exchange: ex, symbol: sym, quote: "USDT"});
}

/* ============ 2. 고래 체결 ============ */
// 바이낸스 aggTrades: m(isBuyerMaker)=true → 시장가 매도. 업비트 ticks: ask_bid "BID" → 시장가 매수.
// 업비트는 원화라서 minUsd × krwRate(기본 1,380원/달러)를 기준 금액으로 쓴다. 업비트 ticks 는 한 번에 최대 500건.
// pages(기본 1, 최대 10): 바이낸스는 fromId 로 더 오래된 체결을 이어 받아 관찰 시간을 늘린다.
export async function whaleTrades({symbol = "BTCUSDT", exchange = "binancef", minUsd = 500000, limit = 1000, krwRate = 1380, pages = 1, ...a} = {}, opts = {}){
  const io = mkIO(a, opts), ex = exOf(exchange);
  let trades = [], sym, quote = "USDT";
  if (ex === "upbit"){
    sym = upbitMarket(symbol); quote = "KRW";
    const j = await io.get("upbit", `/trades/ticks?market=${sym}&count=${Math.max(1, Math.min(500, +limit || 500))}`);
    trades = (j || []).map(x => ({t: +x.timestamp, p: +x.trade_price, q: +x.trade_volume, side: x.ask_bid === "BID" ? "buy" : "sell"}));
  } else {
    sym = binSymbol(symbol);
    const lim = Math.max(1, Math.min(1000, +limit || 1000)), path = ex === "binancef" ? "/fapi/v1/aggTrades" : "/aggTrades";
    let raw = await io.get(ex, `${path}?symbol=${sym}&limit=${lim}`);
    for (let k = 1; k < Math.min(10, +pages || 1) && raw.length; k++){
      const first = Math.min(...raw.map(x => +x.a)); if (first <= 0) break;
      await sleep(io.pauseMs);
      const older = await io.get(ex, `${path}?symbol=${sym}&fromId=${Math.max(0, first - lim)}&limit=${lim}`);
      const seen = new Set(raw.map(x => +x.a)); raw = [...older.filter(x => !seen.has(+x.a)), ...raw];
    }
    trades = raw.map(x => ({t: +x.T, p: +x.p, q: +x.q, side: x.m ? "sell" : "buy", id: +x.a}));
  }
  trades = trades.filter(x => x.p > 0 && x.q > 0).sort((x, y) => x.t - y.t);
  if (!trades.length) throw new Error("체결 내역이 비어 있습니다: " + sym);
  const usdK = quote === "KRW" ? 1 / (+krwRate || 1380) : 1, threshold = quote === "KRW" ? minUsd * (+krwRate || 1380) : minUsd;
  let buy = 0, sell = 0; for (const x of trades){ x.notional = x.p * x.q; if (x.side === "buy") buy += x.notional; else sell += x.notional; }
  const whales = trades.filter(x => x.notional >= threshold);
  const wb = whales.filter(x => x.side === "buy"), ws = whales.filter(x => x.side === "sell");
  const wBuy = wb.reduce((s, x) => s + x.notional, 0), wSell = ws.reduce((s, x) => s + x.notional, 0);
  const windowMin = (trades[trades.length - 1].t - trades[0].t) / 6e4;
  const top = [...whales].sort((x, y) => y.notional - x.notional).slice(0, 10).map(x => ({t: x.t, time: kst(x.t), side: x.side, price: x.p, qty: x.q, notional: x.notional, usd: x.notional * usdK}));
  const ratio = sell ? buy / sell : null, net = wBuy - wSell;
  const data = {exchange: ex, symbol: sym, quote, minUsd, threshold, krwRate: quote === "KRW" ? +krwRate : null, trades: trades.length, from: trades[0].t, to: trades[trades.length - 1].t, windowMin,
    takerBuy: buy, takerSell: sell, takerBuySellRatio: ratio,
    whale: {count: whales.length, buyCount: wb.length, sellCount: ws.length, buy: wBuy, sell: wSell, net, netUsd: net * usdK, netPct: wBuy + wSell ? net / (wBuy + wSell) * 100 : 0, shareOfVolume: buy + sell ? (wBuy + wSell) / (buy + sell) * 100 : 0},
    top};
  const notes = [];
  if (!whales.length) notes.push(`${windowMin.toFixed(1)}분 동안 ${money(minUsd)} 이상 체결 없음`);
  else notes.push(net > 0 ? `고래 순매수 ${money(net, quote)}` : net < 0 ? `고래 순매도 ${money(-net, quote)}` : "고래 매수·매도 균형");
  if (ratio != null) notes.push(ratio > 1.15 ? "시장가 매수 우세" : ratio < 0.87 ? "시장가 매도 우세" : "시장가 매수·매도 비슷");
  if (windowMin < 3) notes.push("관찰 시간이 짧아 참고용");
  data.interpretation = notes.join(" · ");
  const usdNote = quote === "KRW" ? ` (≈${money(net * usdK)}, ${(+krwRate).toLocaleString()}원/달러)` : "";
  const lines = [
    `[고래 체결] ${LABEL[ex]} ${sym} · 최근 ${trades.length.toLocaleString()}건 · ${windowMin.toFixed(1)}분 (${kst(trades[0].t)}~${kst(trades[trades.length - 1].t)} KST)`,
    `시장가 매수 ${money(buy, quote)} / 매도 ${money(sell, quote)} · 매수/매도 비율 ${ratio == null ? "–" : ratio.toFixed(2)}`,
    `고래(≥${money(threshold, quote)}) ${whales.length}건 (매수 ${wb.length} · 매도 ${ws.length}) · 매수 ${money(wBuy, quote)} / 매도 ${money(wSell, quote)} · 순 ${money(net, quote)}${usdNote} · 거래대금의 ${data.whale.shareOfVolume.toFixed(0)}%`,
    top.length ? "큰 체결: " + top.slice(0, 6).map(x => `${x.time} ${x.side === "buy" ? "매수" : "매도"} ${money(x.notional, quote)}@${px(x.price)}`).join(" · ") : "",
    `해석: ${data.interpretation}`
  ];
  return done(data, lines, `고래 ${sym}: ${whales.length}건 · 순 ${money(net, quote)} · 시장가 매수/매도 ${ratio == null ? "–" : ratio.toFixed(2)} (${windowMin.toFixed(0)}분)`);
}

/* ============ 3. 선물 포지션 흐름 (바이낸스 USDT-M 공개 데이터) ============ */
const PERIOD_H = {"5m": 1 / 12, "15m": 0.25, "30m": 0.5, "1h": 1, "2h": 2, "4h": 4, "6h": 6, "12h": 12, "1d": 24};
const ratioSide = rows => {
  const r = (rows || []).map(x => ({t: +x.timestamp, ratio: +x.longShortRatio, long: +(x.longAccount ?? x.longPosition)})).filter(x => Number.isFinite(x.ratio)).sort((a, b) => a.t - b.t);
  if (!r.length) return null;
  const f = r[0], l = r[r.length - 1];
  return {latest: l.ratio, longPct: l.long * 100, first: f.ratio, firstLongPct: f.long * 100, changeLongPp: (l.long - f.long) * 100, t: l.t, n: r.length};
};
// 펀딩 간격(시간)을 실제 기록 간격으로 (대부분 8시간, 일부 종목 4·1시간)
const fundInterval = rows => { if (rows.length < 2) return 8; const d = (rows[rows.length - 1].t - rows[rows.length - 2].t) / 36e5; return d > 0.5 && d < 24.5 ? Math.round(d) : 8; };

export async function futuresFlow({symbol = "BTCUSDT", period = "1h", limit = 48, ...a} = {}, opts = {}){
  const io = mkIO(a, opts), sym = binSymbol(symbol);
  if (!PERIOD_H[period]) period = "1h";
  limit = Math.max(2, Math.min(500, +limit || 48));
  const fundLimit = Math.max(3, Math.min(100, Math.ceil(PERIOD_H[period] * limit / 8) + 1));
  const q = `?symbol=${sym}&period=${period}&limit=${limit}`, g = p => safe(io.get("binancef", p));
  const [topPos, topAcc, glob, taker, oiH, fund, prem] = await Promise.all([
    g("/futures/data/topLongShortPositionRatio" + q), g("/futures/data/topLongShortAccountRatio" + q), g("/futures/data/globalLongShortAccountRatio" + q),
    g("/futures/data/takerlongshortRatio" + q), g("/futures/data/openInterestHist" + q), g(`/fapi/v1/fundingRate?symbol=${sym}&limit=${fundLimit}`), g(`/fapi/v1/premiumIndex?symbol=${sym}`)]);
  const parts = {topPos, topAcc, glob, taker, oiH, fund, prem}, errors = {};
  for (const [k, r] of Object.entries(parts)) if (!r.ok) errors[k] = r.err;
  if (Object.keys(errors).length === 7) throw new Error("선물 데이터를 하나도 받지 못했습니다: " + Object.values(errors)[0]);
  const d = {symbol: sym, period, limit, windowH: PERIOD_H[period] * limit, errors};
  d.topPosition = topPos.ok ? ratioSide(topPos.v) : null;
  d.topAccount = topAcc.ok ? ratioSide(topAcc.v) : null;
  d.global = glob.ok ? ratioSide(glob.v) : null;
  if (taker.ok && taker.v?.length){
    const r = taker.v.map(x => ({t: +x.timestamp, r: +x.buySellRatio, b: +x.buyVol, s: +x.sellVol})).sort((x, y) => x.t - y.t), rec = r.slice(-6);
    const sb = r.reduce((s, x) => s + x.b, 0), ss = r.reduce((s, x) => s + x.s, 0);
    d.taker = {latest: r[r.length - 1].r, recentAvg: rec.reduce((s, x) => s + x.r, 0) / rec.length, windowRatio: ss ? sb / ss : null, buyVol: sb, sellVol: ss, n: r.length};
  }
  if (oiH.ok && oiH.v?.length){
    const r = oiH.v.map(x => ({t: +x.timestamp, q: +x.sumOpenInterest, v: +x.sumOpenInterestValue})).filter(x => x.q > 0).sort((x, y) => x.t - y.t);
    if (r.length){
      const f = r[0], l = r[r.length - 1], pf = f.v / f.q, pl = l.v / l.q;
      d.oi = {latestValue: l.v, latestQty: l.q, firstValue: f.v, changePct: (l.v / f.v - 1) * 100, qtyChangePct: (l.q / f.q - 1) * 100, priceChangePct: (pl / pf - 1) * 100, t: l.t, n: r.length};
    }
  }
  if (fund.ok && fund.v?.length){
    const r = fund.v.map(x => ({t: +x.fundingTime, rate: +x.fundingRate})).filter(x => Number.isFinite(x.rate)).sort((x, y) => x.t - y.t);
    const ih = fundInterval(r), perYear = 24 / ih * 365, avg = r.reduce((s, x) => s + x.rate, 0) / r.length, latest = r[r.length - 1].rate;
    d.funding = {latestPct: latest * 100, avgPct: avg * 100, latestAnnPct: latest * perYear * 100, avgAnnPct: avg * perYear * 100, intervalH: ih, n: r.length, t: r[r.length - 1].t};
  }
  if (prem.ok && prem.v){
    const p = Array.isArray(prem.v) ? prem.v[0] : prem.v, mark = num(p.markPrice), index = num(p.indexPrice), nf = num(p.lastFundingRate);
    d.premium = {markPrice: mark, indexPrice: index, basisBps: mark && index ? (mark / index - 1) * 1e4 : null, nextFundingPct: nf == null ? null : nf * 100,
      nextFundingAnnPct: nf == null ? null : nf * (24 / (d.funding?.intervalH || 8)) * 365 * 100, nextFundingTime: num(p.nextFundingTime)};
  }
  // 상위 트레이더(포지션) − 전체 계정 롱 비중 (%p): +면 고수가 군중보다 롱
  d.divergencePp = d.topPosition && d.global ? d.topPosition.longPct - d.global.longPct : null;
  // 해석: OI·가격 4분면, 과밀(펀딩+군중 쏠림), 고수 vs 군중, 시장가 공격성
  const notes = [], fa = d.funding?.avgAnnPct ?? d.premium?.nextFundingAnnPct, gl = d.global?.longPct, oc = d.oi?.changePct, pc = d.oi?.priceChangePct;
  if (oc != null && pc != null){
    const up = oc > 2, dn = oc < -2;
    notes.push(up && pc >= 0 ? "OI 증가+가격 상승 → 신규 롱 유입" : up && pc < 0 ? "OI 증가+가격 하락 → 신규 숏 유입" : dn && pc >= 0 ? "OI 감소+가격 상승 → 숏 커버링" : dn && pc < 0 ? "OI 감소+가격 하락 → 롱 청산·디레버리징" : "OI 큰 변화 없음");
  }
  let squeeze = "낮음", crowd = 0;
  if (fa != null && gl != null){
    if (fa > 30 && gl > 60){ crowd = 1; squeeze = "롱 스퀴즈(급락) 위험 높음"; }
    else if (fa > 15 && gl > 55){ crowd = 0.5; squeeze = "롱 쏠림 — 하락 시 연쇄 청산 주의"; }
    else if (fa < 0 && gl < 45){ crowd = -1; squeeze = "숏 스퀴즈(급등) 위험 높음"; }
    else if (fa < 3 && gl < 50){ crowd = -0.5; squeeze = "숏 쏠림 — 상승 시 숏 커버링 주의"; }
    if (crowd && oc > 5) squeeze += " (OI 급증으로 연료 증가)";
  }
  d.crowding = crowd; d.squeezeRisk = squeeze; notes.push("과밀: " + squeeze);
  if (d.divergencePp != null && Math.abs(d.divergencePp) >= 5) notes.push(d.divergencePp > 0 ? `상위 트레이더가 군중보다 롱 (${sp(d.divergencePp, 1).replace("%", "%p")})` : `상위 트레이더가 군중보다 숏 (${sp(d.divergencePp, 1).replace("%", "%p")})`);
  if (d.taker) notes.push(d.taker.recentAvg > 1.1 ? "최근 시장가 매수 공격적" : d.taker.recentAvg < 0.9 ? "최근 시장가 매도 공격적" : "시장가 공격성 중립");
  d.interpretation = notes.join(" · ");
  const rs = (s, n) => s ? `${n} 롱 ${s.longPct.toFixed(1)}% (비율 ${s.latest.toFixed(2)}, ${sp(s.changeLongPp, 1).replace("%", "%p")})` : "";
  const lines = [
    `[선물 흐름] 바이낸스 ${sym} · ${period}×${limit} (${d.windowH.toFixed(0)}시간)`,
    d.oi ? `미결제약정 ${money(d.oi.latestValue)} · ${sp(d.oi.changePct)} (수량 ${sp(d.oi.qtyChangePct)}) · 같은 기간 가격 ${sp(d.oi.priceChangePct)}` : "",
    d.funding ? `펀딩 최근 ${d.funding.latestPct.toFixed(4)}%/${d.funding.intervalH}h (연 ${d.funding.latestAnnPct.toFixed(1)}%) · 평균 연 ${d.funding.avgAnnPct.toFixed(1)}%` : "",
    d.premium ? `마크 ${px(d.premium.markPrice)} · 베이시스 ${d.premium.basisBps?.toFixed(1)}bp · 다음 펀딩 예상 ${d.premium.nextFundingPct?.toFixed(4)}%${d.premium.nextFundingTime ? ` (${kst(d.premium.nextFundingTime, 1)} KST)` : ""}` : "",
    [rs(d.topPosition, "상위 포지션"), rs(d.topAccount, "상위 계정"), rs(d.global, "전체 계정")].filter(Boolean).join(" · "),
    d.taker ? `시장가 매수/매도 최근 ${d.taker.latest.toFixed(2)} · 최근 6봉 ${d.taker.recentAvg.toFixed(2)} · 기간 ${d.taker.windowRatio?.toFixed(2)}` : "",
    `해석: ${d.interpretation}`,
    Object.keys(errors).length ? `일부 실패: ${Object.keys(errors).join(", ")}` : ""
  ];
  const summary = `선물 ${sym}: OI ${sp(d.oi?.changePct)} · 펀딩 연 ${fa == null ? "–" : fa.toFixed(1) + "%"} · ${squeeze}`;
  return done(d, lines, summary);
}

/* ============ 4. 파생 이력 (quant.js buildSeries 의 deriv) ============ */
// deriv = {funding:[{t,value}], oi:[{t,value}], long_short:[{t,value}]} · t 는 ms (캔들 t 와 같음)
//   funding: 펀딩비 % (0.01 = 0.01%) — /fapi/v1/fundingRate 를 startTime 으로 넘기며 1,000건씩, 상장 시점(BTC 2019-09)까지
//   oi: 미결제약정 USD (sumOpenInterestValue) · long_short: 전체 계정 롱/숏 비율 — 바이낸스가 최근 30일만 주므로 days 는 최대 30
// 펀딩 이력은 모듈 안에 저장해 두고 다음 호출 때 새 기록만 이어 받는다.
const FUND_CACHE = new WeakMap();
const FUND_START = Date.UTC(2019, 0, 1);
async function fundingAll(io, sym, from){
  let byFetch = FUND_CACHE.get(io.fetchJson); if (!byFetch) FUND_CACHE.set(io.fetchJson, byFetch = new Map());
  const c = byFetch.get(sym), rows = c && c.from <= from ? c.rows.slice() : [];
  let start = rows.length ? rows[rows.length - 1].t + 1 : from;
  for (let k = 0; k < 60; k++){
    const part = await io.get("binancef", `/fapi/v1/fundingRate?symbol=${sym}&startTime=${start}&limit=1000`);
    if (!part?.length) break;
    for (const x of part){ const t = +x.fundingTime, v = +x.fundingRate; if (t >= start && Number.isFinite(v)) rows.push({t, value: v * 100}); }
    if (part.length < 1000) break;
    start = Math.max(...part.map(x => +x.fundingTime)) + 1;
    await sleep(io.pauseMs);
  }
  const m = new Map(rows.map(r => [r.t, r])), out = [...m.values()].sort((a, b) => a.t - b.t);
  byFetch.set(sym, {from: c && c.from <= from ? c.from : from, rows: out});
  return out.filter(r => r.t >= from);
}
// 30일 한도 데이터: 500건 창으로 앞에서부터 나눠 받는다
async function histWindows(io, path, sym, period, start, end, pick){
  const pms = PERIOD_H[period] * 36e5, chunk = 500 * pms, out = new Map();
  for (let s = start, k = 0; s < end && k < 40; s += chunk, k++){
    const part = await io.get("binancef", `${path}?symbol=${sym}&period=${period}&limit=500&startTime=${Math.floor(s)}&endTime=${Math.floor(Math.min(end, s + chunk - 1))}`);
    for (const x of part || []){ const v = pick(x); if (Number.isFinite(v)) out.set(+x.timestamp, {t: +x.timestamp, value: v}); }
    if (s + chunk < end) await sleep(io.pauseMs);
  }
  return [...out.values()].sort((a, b) => a.t - b.t);
}
export async function derivHistory({symbol = "BTCUSDT", days = 30, period = "1h", fundingDays = null, ...a} = {}, opts = {}){
  const io = mkIO(a, opts), sym = binSymbol(symbol), now = io.now ?? Date.now();
  if (!PERIOD_H[period] || PERIOD_H[period] < 0.25) period = "1h";
  const hd = Math.max(1, Math.min(30, +days || 30)), hStart = now - hd * 864e5 + 36e5;   // 30일 경계는 1시간 여유
  const fStart = fundingDays ? Math.max(FUND_START, now - fundingDays * 864e5) : FUND_START;
  const [f, oi, ls] = await Promise.all([
    safe(fundingAll(io, sym, fStart)),
    safe(histWindows(io, "/futures/data/openInterestHist", sym, period, hStart, now, x => +x.sumOpenInterestValue)),
    safe(histWindows(io, "/futures/data/globalLongShortAccountRatio", sym, period, hStart, now, x => +x.longShortRatio))]);
  const deriv = {}, errors = {};
  for (const [k, r] of [["funding", f], ["oi", oi], ["long_short", ls]]){ if (r.ok && r.v.length) deriv[k] = r.v; else errors[k] = r.ok ? "데이터 없음" : r.err; }
  if (!Object.keys(deriv).length) throw new Error("파생 이력을 받지 못했습니다: " + Object.values(errors)[0]);
  const day = t => new Date(t).toISOString().slice(0, 10), rng = a => a ? `${a.length.toLocaleString()}건 ${day(a[0].t)}~${day(a[a.length - 1].t)}` : "없음";
  const note = `펀딩 ${rng(deriv.funding)} · OI·롱숏 ${period} ${rng(deriv.oi)} / ${rng(deriv.long_short)} (바이낸스는 OI·롱숏 이력을 최근 30일만 제공 → 그 이전 봉은 해당 조건이 거짓)`
    + (Object.keys(errors).length ? ` · 실패: ${Object.entries(errors).map(([k, v]) => k + " " + v).join(", ")}` : "");
  const data = {symbol: sym, period, days: hd, counts: Object.fromEntries(Object.entries(deriv).map(([k, v]) => [k, v.length])), errors};
  return {deriv, note, data, text: clipLines(`[파생 이력] ${sym} · ${note}`), summary: `파생 이력 ${sym}: 펀딩 ${deriv.funding?.length || 0} · OI ${deriv.oi?.length || 0} · 롱숏 ${deriv.long_short?.length || 0}건`};
}

/* ============ 5. 청산 구간 추정 ============ */
// 공개 REST 에 과거 청산 내역이 없어 추정한다 (실제 청산 데이터 아님).
//   진입가: 최근 72시간 OI 이력에서 OI 가 늘어난 봉의 평균가(= OI 금액 ÷ 수량)에 그만큼 새 포지션이 생겼다고 본다 (이력 실패 시 현재가)
//   레버리지 비중(가정): 10배 35% · 25배 30% · 50배 20% · 100배 15% · 롱/숏 나눔은 전체 계정 롱 비중
//   청산가 ≈ 진입가 × (1 ∓ 1/레버리지 ± 유지증거금률 0.4%) — 격리 기준. 이후 가격이 이미 지나간 청산가는 뺀다.
//   0.5% 폭으로 묶어 큰 구간 5개씩, 같은 쪽 호가 벽(±0.3% 안)과 짝짓는다.
const LEV_TIERS = [[10, 0.35], [25, 0.30], [50, 0.20], [100, 0.15]], MMR = 0.004;
export async function liquidationEstimate({symbol = "BTCUSDT", exchange = "binancef", ...a} = {}, opts = {}){
  const io = mkIO(a, opts), sym = binSymbol(symbol), ex = exOf(exchange);
  const [prem, oiNow, oiH, glob, book] = await Promise.all([
    safe(io.get("binancef", `/fapi/v1/premiumIndex?symbol=${sym}`)), safe(io.get("binancef", `/fapi/v1/openInterest?symbol=${sym}`)),
    safe(io.get("binancef", `/futures/data/openInterestHist?symbol=${sym}&period=1h&limit=72`)), safe(io.get("binancef", `/futures/data/globalLongShortAccountRatio?symbol=${sym}&period=1h&limit=1`)),
    safe(orderBook({symbol, exchange: ex === "upbit" ? "binancef" : ex, depth: 1000}, {...a, ...opts}))]);
  const p0 = prem.ok ? (Array.isArray(prem.v) ? prem.v[0] : prem.v) : null;
  const price = num(p0?.markPrice) || (book.ok ? book.v.data.mid : null);
  if (!price) throw new Error("현재가를 알 수 없어 청산 구간을 추정할 수 없습니다: " + (prem.err || book.err));
  const oiQty = oiNow.ok ? num(oiNow.v.openInterest) : null, oiUsd = oiQty ? oiQty * price : null;
  const g = glob.ok && glob.v?.length ? glob.v[glob.v.length - 1] : null, longShare = g ? clamp(+g.longAccount, 0.05, 0.95) : 0.5;
  // 진입 묶음
  let entries = [];
  if (oiH.ok && oiH.v?.length > 1){
    const r = oiH.v.map(x => ({t: +x.timestamp, q: +x.sumOpenInterest, v: +x.sumOpenInterestValue})).filter(x => x.q > 0).sort((x, y) => x.t - y.t);
    for (let i = 1; i < r.length; i++){
      const dq = r[i].q - r[i - 1].q, p = r[i].v / r[i].q;
      if (dq <= 0) continue;
      const later = r.slice(i + 1).map(x => x.v / x.q).concat(price);
      entries.push({p, usd: dq * p, lo: Math.min(...later), hi: Math.max(...later)});
    }
  }
  const basis = entries.length ? "OI 증가 구간" : "현재가 가정";
  if (!entries.length) entries = [{p: price, usd: oiUsd ? oiUsd * 0.1 : 1, lo: price, hi: price}];
  const tiers = LEV_TIERS.map(([L]) => ({lev: L, long: price * (1 - 1 / L + MMR), short: price * (1 + 1 / L - MMR)}));
  const w = price * 0.005, longB = new Map(), shortB = new Map();
  const add = (m, liq, usd, L) => { const k = Math.floor(liq / w), b = m.get(k) || {usd: 0, pu: 0, lev: {}}; b.usd += usd; b.pu += liq * usd; b.lev[L] = (b.lev[L] || 0) + usd; m.set(k, b); };
  for (const e of entries) for (const [L, wt] of LEV_TIERS){
    const lq = e.p * (1 - 1 / L + MMR), sq = e.p * (1 + 1 / L - MMR);
    if (lq < price && e.lo > lq) add(longB, lq, e.usd * wt * longShare, L);          // 아직 안 닿은 롱 청산가 (현재가 아래)
    if (sq > price && e.hi < sq) add(shortB, sq, e.usd * wt * (1 - longShare), L);   // 아직 안 닿은 숏 청산가 (현재가 위)
  }
  const walls = book.ok ? book.v.data : null;
  const clusters = (m, side) => [...m.values()].sort((x, y) => y.usd - x.usd).slice(0, 5).map(b => {
    const p = b.pu / b.usd, lev = +Object.entries(b.lev).sort((x, y) => y[1] - x[1])[0][0];
    const pool = walls ? (side === "long" ? walls.bidWalls : walls.askWalls) : [];
    const wall = pool.find(x => Math.abs(x.price / p - 1) <= 0.003) || null;
    return {price: p, distPct: (p / price - 1) * 100, estUsd: b.usd, mainLev: lev, wall: wall ? {price: wall.price, notional: wall.notional} : null};
  }).sort((x, y) => side === "long" ? y.price - x.price : x.price - y.price);
  const longs = clusters(longB, "long"), shorts = clusters(shortB, "short");
  const sumL = longs.reduce((s, x) => s + x.estUsd, 0), sumS = shorts.reduce((s, x) => s + x.estUsd, 0);
  const nearL = longs[0], nearS = shorts[0], notes = [];
  if (nearL) notes.push(`가까운 롱 청산대 ${px(nearL.price)}(${sp(nearL.distPct)})${nearL.wall ? " — 매수벽과 겹침(지지 가능)" : ""}`);
  if (nearS) notes.push(`가까운 숏 청산대 ${px(nearS.price)}(${sp(nearS.distPct)})${nearS.wall ? " — 매도벽과 겹침(저항 가능)" : ""}`);
  if (sumL && sumS) notes.push(sumL > sumS * 1.3 ? "아래쪽 롱 청산 물량이 더 많음 → 급락 시 연쇄 위험" : sumS > sumL * 1.3 ? "위쪽 숏 청산 물량이 더 많음 → 급등 시 숏 스퀴즈 위험" : "위·아래 청산 물량 비슷");
  const data = {estimate: true, symbol: sym, price, openInterest: {qty: oiQty, usd: oiUsd}, longShare, entryBasis: basis, entries: entries.length, mmr: MMR, levTiers: LEV_TIERS, tiers,
    longClusters: longs, shortClusters: shorts, errors: Object.fromEntries(Object.entries({prem, oiNow, oiH, glob, book}).filter(([, r]) => !r.ok).map(([k, r]) => [k, r.err])), interpretation: notes.join(" · ")};
  const cl = xs => xs.map(x => `${px(x.price)}(${sp(x.distPct)}) ~${money(x.estUsd)} ${x.mainLev}배${x.wall ? " +벽" : ""}`).join(" · ") || "없음";
  const lines = [
    `[청산 구간 추정 — 실제 청산 데이터 아님] 바이낸스 선물 ${sym} · 현재 ${px(price)} · OI ${money(oiUsd)} · 롱 비중 ${(longShare * 100).toFixed(0)}% · 진입가 근거: ${basis}`,
    `레버리지별 청산가(현재가 진입 가정): ${tiers.map(t => `${t.lev}배 롱 ${px(t.long)}/숏 ${px(t.short)}`).join(" · ")}`,
    `롱 청산대(아래): ${cl(longs)}`,
    `숏 청산대(위): ${cl(shorts)}`,
    `해석: ${data.interpretation || "추정할 구간이 부족함"} (레버리지 비중·유지증거금은 가정값)`,
    Object.keys(data.errors).length ? `일부 실패: ${Object.keys(data.errors).join(", ")}` : ""
  ];
  return done(data, lines, `청산 추정 ${sym}: 롱 ${nearL ? px(nearL.price) : "–"} · 숏 ${nearS ? px(nearS.price) : "–"} (추정)`);
}

/* ============ 6. 흐름 종합 + 흐름 점수 ============ */
// 흐름 점수(−100~+100, +면 매수 압력). 있는 요인만 더해 그 요인들의 만점 합으로 나눠 100점 환산:
//   호가 ±1% 불균형        25점 × clamp(불균형 / 0.5)
//   고래 순매수 비중       25점 × (고래 매수−매도)/(매수+매도) (고래 없으면 0)
//   체결 시장가 매수/매도  15점 × clamp((비율 − 1) / 0.3)
//   선물 시장가 최근 6봉   15점 × clamp((비율 − 1) / 0.3)
//   상위 트레이더 롱 비중  10점 × clamp((롱% − 50) / 15)
//   펀딩 과열(역발상)      10점 × −clamp((연환산 펀딩% − 10.95) / 30)  (0.01%/8h 기본값보다 높을수록 감점)
export async function flowSnapshot({symbol = "BTCUSDT", exchange = "binancef", ...a} = {}, opts = {}){
  const o = {...a, ...opts}, ex = exOf(exchange);
  const [ob, wt, ff] = await Promise.all([safe(orderBook({symbol, exchange: ex}, o)), safe(whaleTrades({symbol, exchange: ex}, o)), safe(futuresFlow({symbol}, o))]);
  if (!ob.ok && !wt.ok && !ff.ok) throw new Error("흐름 데이터를 하나도 받지 못했습니다: " + ob.err);
  const f = [], add = (label, max, x, note) => { if (x == null || !Number.isFinite(x)) return; f.push({label, max, pts: Math.round(max * clamp(x) * 10) / 10, note}); };
  if (ob.ok){ const b = ob.v.data.bands[1]; add("호가 ±1% 불균형", 25, b.imbalance / 0.5, sp(b.imbalance * 100, 0)); }
  if (wt.ok){ const w = wt.v.data.whale; add("고래 순매수", 25, w.count ? w.netPct / 100 : 0, w.count ? `${w.count}건 ${sp(w.netPct, 0)}` : "고래 없음");
    if (wt.v.data.takerBuySellRatio != null) add("체결 매수/매도", 15, (wt.v.data.takerBuySellRatio - 1) / 0.3, wt.v.data.takerBuySellRatio.toFixed(2)); }
  if (ff.ok){ const d = ff.v.data;
    if (d.taker) add("선물 시장가 6봉", 15, (d.taker.recentAvg - 1) / 0.3, d.taker.recentAvg.toFixed(2));
    if (d.topPosition) add("상위 트레이더 롱", 10, (d.topPosition.longPct - 50) / 15, d.topPosition.longPct.toFixed(1) + "%");
    const fa = d.funding?.avgAnnPct ?? d.premium?.nextFundingAnnPct;
    if (fa != null) add("펀딩 과열(역)", 10, -(fa - 10.95) / 30, `연 ${fa.toFixed(1)}%`); }
  const max = f.reduce((s, x) => s + x.max, 0) || 1;
  const score = Math.max(-100, Math.min(100, Math.round(f.reduce((s, x) => s + x.pts, 0) / max * 100)));
  const label = score >= 50 ? "강한 매수 압력" : score >= 20 ? "매수 우위" : score > -20 ? "중립" : score > -50 ? "매도 우위" : "강한 매도 압력";
  const errors = Object.fromEntries([["orderBook", ob], ["whaleTrades", wt], ["futuresFlow", ff]].filter(([, r]) => !r.ok).map(([k, r]) => [k, r.err]));
  const data = {symbol, exchange: ex, score, label, factors: f, orderBook: ob.ok ? ob.v.data : null, whaleTrades: wt.ok ? wt.v.data : null, futuresFlow: ff.ok ? ff.v.data : null, errors};
  const head = [`[흐름 점수] ${score > 0 ? "+" : ""}${score} (${label}) — ${f.map(x => `${x.label} ${x.pts > 0 ? "+" : ""}${x.pts}/${x.max} (${x.note})`).join(" · ")}`,
    Object.keys(errors).length ? `실패: ${Object.entries(errors).map(([k, v]) => `${k} ${v}`).join(" · ")}` : ""].filter(Boolean).join("\n");
  const parts = [ob, wt, ff].filter(r => r.ok).map(r => r.v.text), room = Math.floor((MAX_TEXT - head.length - 2 * parts.length) / (parts.length || 1));
  const text = clipLines([head, ...parts.map(t => clipLines(t, room))].join("\n\n"));
  const ffd = ff.ok ? ff.v.data : null;
  return {data, text, summary: `흐름 ${symbol}: ${score > 0 ? "+" : ""}${score} ${label}${ffd ? ` · ${ffd.squeezeRisk}` : ""}`};
}
