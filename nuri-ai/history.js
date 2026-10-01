// 과거 전체 캔들: 거래소·야후에서 '가능한 가장 오래된 봉'부터 지금까지 이어 붙인다.
// - 캔들: [{t: ms, o, h, l, c, v}] 오래된 것 먼저 (quant.js 와 같은 형식)
// - 바이낸스 선물/현물: startTime=0 으로 첫 봉(상장일)을 찾고 앞으로 페이지 (동시 3개, 429 면 Retry-After 만큼 쉬고 1번 재시도)
// - 업비트: 최신 봉부터 to(UTC) 로 뒤로 페이지 (최신 먼저 오므로 뒤집는다)
// - 야후: range=max (일·주·월봉). 분·시간봉은 야후가 최근 730일(1시간)·60일·7일만 준다
// - IndexedDB(engine.js idb) 에 "hist:<거래소>:<종목>:<간격>" 으로 캐시하고, 다음엔 마지막 봉 이후만 받는다
// - 네트워크·저장소는 주입할 수 있다 (fetchJson · store · apiBase) → Node 테스트에서 가짜로 바꿔 끼운다
import { INTERVAL_SECONDS, INTERVALS } from "./quant.js";

const DAY = 86400000;
const iso = t => new Date(t).toISOString().slice(0, 10);
const fmtN = n => Number(n).toLocaleString("ko-KR");

/* ============ 의존성 (기본: engine.js · 주입 가능) ============ */
let _eng = null;
const engine = async () => _eng || (_eng = await import("./engine.js"));   // Node 에서는 못 읽으므로 필요할 때만
// 기본 fetchJson: 거래소 API 는 fetch, 야후는 webGet (실행기 프록시 경유). 실패하면 status · retryAfter(초) 를 붙여 throw
const realFetchJson = E => async (url, via = "api") => {
  if (via === "web") return E.webGet(url, "json");
  const r = await fetch(url, {headers: {accept: "application/json"}});
  if (!r.ok){
    const e = new Error(`HTTP ${r.status} ${url.slice(0, 90)}`);
    e.status = r.status; e.retryAfter = +(r.headers.get("retry-after") || 0);
    throw e;
  }
  return r.json();
};
async function deps(o){
  const E = !o.fetchJson || !o.apiBase || o.store === undefined ? await engine() : null;
  return {
    fetchJson: o.fetchJson || realFetchJson(E),
    apiBase: o.apiBase || E.apiBase,
    store: o.store === undefined ? E.idb : o.store,          // null 이면 캐시 안 씀
    sleep: o.sleep || (ms => new Promise(r => setTimeout(r, ms))),
    now: o.now ?? Date.now(),
  };
}
// 429(요청 과다)면 Retry-After 만큼 (없으면 2초, 최대 60초) 쉬고 한 번만 다시. 418(IP 차단)은 재시도 안 함
async function retry(ctx, fn){
  try { return await fn(); }
  catch(e){
    if (e.status !== 429) throw e;
    await ctx.sleep(Math.min(60, e.retryAfter || 2) * 1000);
    return fn();
  }
}
// 작은 동시 실행 풀 (순서 유지, 하나라도 실패하면 throw)
async function pool(items, n, fn){
  const out = new Array(items.length); let k = 0;
  await Promise.all(Array.from({length: Math.min(n, items.length)}, async () => { while (k < items.length){ const i = k++; out[i] = await fn(items[i], i); } }));
  return out;
}

/* ============ 캔들 이어 붙이기 ============ */
// 같은 시각은 새 것이 이기고, 오래된 순 정렬. 반 봉보다 가까운 두 봉(야후의 '진행 중 봉' 시각 차이)은 하나로 합친다.
export function mergeBars(old, fresh, stepMs){
  const m = new Map();
  for (const b of old || []) m.set(b.t, b);
  for (const b of fresh || []) m.set(b.t, b);
  const s = [...m.values()].sort((a, b) => a.t - b.t), out = [];
  for (const b of s){
    const p = out[out.length - 1];
    if (p && stepMs && b.t - p.t < stepMs / 2) out[out.length - 1] = {...b, t: p.t};   // 시각은 앞 봉(정렬된 쪽), 값은 최신
    else out.push(b);
  }
  return out;
}
// 캐시와 새로 받은 봉이 겹치는 구간(마지막 캐시 봉 제외 — 그건 진행 중이었을 수 있다)의 종가가 1% 넘게 다르면
// 액면분할·수정주가가 바뀐 것 → 캐시를 버리고 전체를 다시 받는다
function consistent(cached, fresh){
  if (!cached.length) return true;
  const lastT = cached[cached.length - 1].t, m = new Map(cached.map(b => [b.t, b.c]));
  return fresh.every(b => b.t >= lastT || !m.has(b.t) || Math.abs(b.c / m.get(b.t) - 1) <= 0.01);
}

/* ============ 바이낸스 (선물 /fapi/v1/klines · 현물 /api/v3/klines) ============ */
// 한도: 선물 limit 최대 1500 (가중치 10, IP 당 분당 2400) · 현물 limit 최대 1000 (가중치 2, 분당 6000)
const BN = {binancef: {path: "/fapi/v1/klines", limit: 1500, label: "바이낸스 USDT-M 선물"}, binance: {path: "/klines", limit: 1000, label: "바이낸스 현물"}};
const bnBar = r => ({t: +r[0], o: +r[1], h: +r[2], l: +r[3], c: +r[4], v: +r[5]});
async function binanceHist(ctx, {exchange, market, interval, maxBars, since, onProgress}){
  const cfg = BN[exchange], L = cfg.limit, step = INTERVAL_SECONDS[interval] * 1000, now = ctx.now;
  const base = `${ctx.apiBase(exchange)}${cfg.path}?symbol=${encodeURIComponent(market)}&interval=${interval}`;
  const get = q => retry(ctx, () => ctx.fetchJson(base + q, "api"));
  let start = since, genesis = null;
  if (start == null){
    const first = await get("&startTime=0&limit=1");                    // 상장 후 첫 봉
    if (!Array.isArray(first) || !first.length) throw new Error(`${cfg.label}에 ${market} ${interval} 봉이 없습니다`);
    genesis = +first[0][0];
    start = Math.max(genesis, now - maxBars * step);                     // 너무 길면 최근 maxBars 만 받는다
  }
  const start0 = start;
  const rows = [];
  // 고정 간격이고 여러 페이지면: 시작 시각을 미리 나눠 동시 3개로 받는다 (endTime 으로 페이지끼리 겹치지 않게)
  if (interval !== "1M" && (now - start) / step > L){
    const starts = [];
    for (let s = start; s <= now; s += L * step) starts.push(s);
    let done = 0;
    const parts = await pool(starts, 3, async (s, i) => {
      if (i >= 3) await ctx.sleep(120);                                  // 분당 가중치 한도 여유
      const p = await get(`&startTime=${s}&endTime=${s + L * step - 1}&limit=${L}`);
      onProgress?.({phase: "download", done: ++done, total: starts.length, bars: rows.length});
      return p;
    });
    for (const p of parts) rows.push(...p.map(bnBar));
    start = rows.length ? rows[rows.length - 1].t + 1 : start;
  }
  // 꼬리(또는 짧은 요청·증분 갱신): 다 찰 때까지 순서대로
  for (let k = 0; k < 1000; k++){
    const p = await get(`&startTime=${start}&limit=${L}`);
    if (!Array.isArray(p) || !p.length) break;
    rows.push(...p.map(bnBar));
    onProgress?.({phase: "download", bars: rows.length});
    if (p.length < L) break;
    start = +p[p.length - 1][0] + 1;
    await ctx.sleep(120);
  }
  return {rows, genesis, label: cfg.label, truncated: genesis != null && start0 > genesis};
}

/* ============ 업비트 (/candles/...) ============ */
// 한도: count 최대 200, 시세 조회 초당 10회 → 요청 사이 110ms. to 는 '그 시각 이전' (해당 시각 미포함)
const UP_PATH = {"1m": "/candles/minutes/1", "3m": "/candles/minutes/3", "5m": "/candles/minutes/5", "15m": "/candles/minutes/15", "30m": "/candles/minutes/30",
  "1h": "/candles/minutes/60", "4h": "/candles/minutes/240", "1d": "/candles/days", "1w": "/candles/weeks", "1M": "/candles/months"};
const upMarket = m => /-/.test(m) ? m.toUpperCase() : "KRW-" + String(m).toUpperCase().replace(/(USDT|KRW)$/, "");
async function upbitHist(ctx, {market, interval, maxBars, since, onProgress}){
  const path = UP_PATH[interval];
  if (!path) throw new Error(`업비트는 ${interval} 봉을 주지 않습니다 (가능: ${Object.keys(UP_PATH).join(", ")})`);
  const get = q => retry(ctx, () => ctx.fetchJson(ctx.apiBase("upbit") + path + q, "api"));
  const rows = []; let to = "", reachedStart = false;
  while (rows.length < maxBars){
    const part = await get(`?market=${market}&count=200${to ? "&to=" + encodeURIComponent(to) : ""}`);
    if (!Array.isArray(part) || !part.length){ reachedStart = true; break; }
    for (const r of part){
      const t = Date.parse(r.candle_date_time_utc + "Z");
      rows.push({t, o: +r.opening_price, h: +r.high_price, l: +r.low_price, c: +r.trade_price, v: +r.candle_acc_trade_volume});
    }
    to = part[part.length - 1].candle_date_time_utc + "Z";              // 최신 먼저 → 마지막이 가장 오래된 봉
    onProgress?.({phase: "download", bars: rows.length});
    if (part.length < 200){ reachedStart = true; break; }
    if (since != null && Date.parse(to) <= since) break;                // 증분: 캐시 끝까지 내려오면 멈춤
    await ctx.sleep(110);
  }
  rows.reverse();
  return {rows, genesis: reachedStart && rows.length ? rows[0].t : null, label: "업비트", truncated: since == null && !reachedStart};
}

/* ============ 야후 파이낸스 (/v8/finance/chart) ============ */
// [야후 interval, range, 묶을 개수]. 야후 한도: 1시간봉 최근 730일 · 5~30분봉 60일 · 1분봉 7일. 2h/4h 는 60분봉을 UTC 기준으로 묶는다
const Y_IV = {"1d": ["1d", "max", 1], "1w": ["1wk", "max", 1], "1M": ["1mo", "max", 1], "1h": ["60m", "730d", 1], "2h": ["60m", "730d", 2],
  "4h": ["60m", "730d", 4], "30m": ["30m", "60d", 1], "15m": ["15m", "60d", 1], "5m": ["5m", "60d", 1], "1m": ["1m", "7d", 1]};
const Y_LIMIT_DAYS = {"730d": 729, "60d": 59, "7d": 6};
const Y_MAX_PERIOD1 = -2208988800;                                       // 1900-01-01 (range=max 가 해상도를 낮춰 줄 때 대신 씀)
const Y_ALIAS = {"코스피": "^KS11", "KOSPI": "^KS11", "코스피200": "^KS200", "코스닥": "^KQ11", "S&P500": "^GSPC", "SP500": "^GSPC", "나스닥": "^IXIC", "NASDAQ": "^IXIC"};
async function yahooChart(ctx, sym, iv, q){
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=${iv}&${q}&includePrePost=false`;
  const j = await retry(ctx, () => ctx.fetchJson(url, "web"));
  const r = j?.chart?.result?.[0];
  if (!r || !r.timestamp?.length) throw new Error(j?.chart?.error?.description || "야후에서 종목을 찾을 수 없습니다: " + sym);
  return r;
}
function yahooRows(r){
  const q = r.indicators?.quote?.[0] || {}, ts = r.timestamp || [];
  // 휴장·결측 행(null)은 버린다
  return ts.map((t, i) => ({t: t * 1000, o: q.open?.[i], h: q.high?.[i], l: q.low?.[i], c: q.close?.[i], v: q.volume?.[i] ?? 0}))
    .filter(b => [b.o, b.h, b.l, b.c].every(x => x !== null && x !== undefined && Number.isFinite(+x)))
    .map(b => ({t: b.t, o: +b.o, h: +b.h, l: +b.l, c: +b.c, v: +b.v || 0}));
}
function aggregate(rows, k, hourMs = 3600000){
  if (k <= 1) return rows;
  const out = [], size = k * hourMs;
  for (const b of rows){
    const t = Math.floor(b.t / size) * size, p = out[out.length - 1];
    if (p && p.t === t){ p.h = Math.max(p.h, b.h); p.l = Math.min(p.l, b.l); p.c = b.c; p.v += b.v; }
    else out.push({...b, t});
  }
  return out;
}
async function yahooHist(ctx, {market, interval, maxBars, since}){
  const spec = Y_IV[interval];
  if (!spec) throw new Error(`야후는 ${interval} 봉을 주지 않습니다 (가능: ${Object.keys(Y_IV).join(", ")})`);
  const [iv, range, agg] = spec, now = ctx.now;
  let sym = Y_ALIAS[String(market).toUpperCase()] || Y_ALIAS[market] || market;
  const cands = /^\d{6}$/.test(sym) ? [sym + ".KS", sym + ".KQ"] : [sym];   // 국내 6자리 코드: 코스피 → 코스닥 순
  const lim = Y_LIMIT_DAYS[range];
  let q;
  if (since != null){
    const p1 = Math.floor(Math.max(since, lim ? now - lim * DAY : -Infinity) / 1000);
    q = `period1=${p1}&period2=${Math.ceil(now / 1000)}`;
  } else q = `range=${range}`;
  let r = null, err = null;
  for (const s of cands){
    try { r = await yahooChart(ctx, s, iv, q); sym = s; break; } catch(e){ err = e; }
  }
  if (!r) throw err;
  // range=max 가 해상도를 낮춰(예: 3mo) 주면 period1=1900 으로 다시
  if (range === "max" && since == null && r.meta?.dataGranularity && r.meta.dataGranularity !== iv)
    r = await yahooChart(ctx, sym, iv, `period1=${Y_MAX_PERIOD1}&period2=${Math.ceil(now / 1000)}`);
  let rows = aggregate(yahooRows(r), agg);
  const genesis = !lim && since == null ? rows[0]?.t ?? null : null, truncated = rows.length > maxBars;
  if (truncated) rows = rows.slice(-maxBars);
  const first = r.meta?.firstTradeDate;
  const notes = [];
  if (lim) notes.push(`야후는 ${iv} 봉을 최근 ${range.replace("d", "")}일만 제공합니다 (그 이전 과거는 일봉으로 보세요)`);
  if (agg > 1) notes.push(`${interval} 봉은 60분봉 ${agg}개를 UTC 기준으로 묶은 값`);
  if (/^1(d|wk|mo)$/.test(iv)) notes.push("가격은 분할 반영·배당 미반영(가격 수익률)");
  return {rows, genesis, truncated, label: "야후 파이낸스", market: sym,
    currency: r.meta?.currency, firstTrade: first ? first * 1000 : null, extraNote: notes.join(" · ")};
}

/* ============ 진입점 ============ */
const SOURCES = {binancef: binanceHist, binance: binanceHist, upbit: upbitHist, yahoo: yahooHist};
const normMarket = (exchange, m) => {
  m = String(m || "").trim();
  if (exchange === "upbit") return upMarket(m);
  if (exchange === "binance" || exchange === "binancef") return /USDT$|USDC$|BUSD$/i.test(m) ? m.toUpperCase() : m.toUpperCase().replace(/^KRW-/, "") + "USDT";
  return m;
};
// 전체 과거 캔들. opts: {market, exchange("binancef"|"binance"|"upbit"|"yahoo"), interval("1h","4h","1d","1w" …), maxBars=60000,
//   onProgress({phase, done, total, bars}), maxAgeMs=60000(이 안에 받은 캐시는 그대로 씀), fresh(캐시 무시),
//   fetchJson(url, "api"|"web"), store(idb 호환 {put, all} · null 이면 캐시 안 함), apiBase(name), sleep(ms), now}
// 반환: {candles, from, to, source, note, market, exchange, interval, bars, cached, complete, truncated, currency}
export async function historyCandles(opts = {}){
  const {exchange = "binancef", interval = "1d", maxBars = 60000, onProgress} = opts;
  if (!SOURCES[exchange]) throw new Error(`지원하지 않는 거래소: ${exchange} (binancef, binance, upbit, yahoo)`);
  if (!INTERVALS.includes(interval)) throw new Error(`지원하지 않는 봉 간격: ${interval} (가능: ${INTERVALS.join(", ")})`);
  const ctx = await deps(opts), market = normMarket(exchange, opts.market || (exchange === "yahoo" ? "^GSPC" : "BTCUSDT"));
  const step = INTERVAL_SECONDS[interval] * 1000, key = `hist:${exchange}:${market}:${interval}`;
  // 1) 캐시
  let cache = null;
  if (ctx.store && !opts.fresh){
    try { cache = (await ctx.store.all(key)).find(v => v && v.key === key) || null; } catch(e){ cache = null; }
    // 예전에 maxBars 보다 짧게 잘라 저장했는데 지금 더 길게 원하면 처음부터 다시
    if (cache && !cache.complete && cache.candles.length < maxBars && cache.truncated) cache = null;
  }
  const finish = (candles, meta, cached) => {
    const truncated = !!meta.truncated, from = candles[0]?.t ?? null, to = candles[candles.length - 1]?.t ?? null;
    const years = from !== null ? (to - from) / (365.25 * DAY) : 0;
    const head = meta.complete ? "상장(데이터 시작) 이후 전체" : truncated ? `최근 ${fmtN(candles.length)}봉만 (maxBars 한도 — 더 오래된 과거는 큰 봉 간격으로 보세요)` : "제공되는 범위 전체";
    const note = `${meta.label} ${meta.market} ${interval} · ${from !== null ? iso(from) : "?"} ~ ${to !== null ? iso(to) : "?"} · ${fmtN(candles.length)}봉 (${years.toFixed(1)}년, ${head})`
      + (meta.extraNote ? " · " + meta.extraNote : "") + (cached ? " · 캐시 사용" : "");
    return {candles, from, to, source: meta.source, note, market: meta.market, exchange, interval, bars: candles.length,
      cached, complete: !!meta.complete, truncated, currency: meta.currency || null};
  };
  if (cache && ctx.now - cache.t < (opts.maxAgeMs ?? 60000)) return finish(cache.candles, cache, true);
  // 2) 받기: 캐시가 있으면 마지막 봉 3개 앞부터만 (겹치는 봉으로 분할·수정 여부 확인)
  const fetchFrom = async since => {
    onProgress?.({phase: since == null ? "full" : "incremental", bars: 0});
    return SOURCES[exchange](ctx, {exchange, market, interval, maxBars, since, onProgress});
  };
  let res, candles, complete;
  if (cache && cache.candles.length){
    const since = cache.candles[Math.max(0, cache.candles.length - 3)].t;
    res = await fetchFrom(since);
    if (consistent(cache.candles, res.rows)){
      candles = mergeBars(cache.candles, res.rows, step);
      complete = cache.complete;
    } else { onProgress?.({phase: "resync"}); cache = null; }
  }
  if (!candles){
    res = await fetchFrom(null);
    candles = mergeBars([], res.rows, step);
    complete = res.genesis != null && candles.length && candles[0].t <= res.genesis;
  }
  if (!candles.length) throw new Error(`${market} ${interval} 캔들을 받지 못했습니다`);
  let truncated = !!res.truncated || candles.length > maxBars || (!complete && !!cache?.truncated);
  if (candles.length > maxBars){ candles = candles.slice(-maxBars); complete = false; truncated = true; }
  const meta = {label: res.label, market: res.market || market, source: `${exchange}:${res.market || market}:${interval}`,
    complete, truncated, extraNote: res.extraNote || "", currency: res.currency || cache?.currency || null};
  // 3) 캐시 저장 (최대 maxBars 봉)
  if (ctx.store){
    try { await ctx.store.put(key, {key, t: ctx.now, exchange, market, interval, candles, ...meta}); } catch(e){ /* 저장 실패는 무시 */ }
  }
  return finish(candles, meta, false);
}

// 원하는 기간(년)에 맞는 봉 간격. 봉 수가 budget(기본 16000)을 넘지 않는 가장 촘촘한 간격.
//   코인: 1년 이하 1h · 8년 이하 4h · 그 이상 1d (budget 16000 기준)
//   야후: 1시간봉은 최근 730일만 → 1년 이하 1h · 2년 이하 4h · 그 이상 1d (100년이어도 일봉 ~2.5만 개)
export function bestInterval(exchange, wantYears, budget = 16000){
  const y = Math.max(0, +wantYears || 0);
  if (exchange === "yahoo") return y <= 1 ? "1h" : y <= 2 ? "4h" : "1d";
  const perYear = iv => 365.25 * 86400 / INTERVAL_SECONDS[iv];
  for (const iv of ["1h", "4h", "1d"]) if (y * perYear(iv) <= budget) return iv;
  return y * perYear("1d") <= budget * 2 ? "1d" : "1w";
}

// 긴 과거 백테스트용 추천 종목 (since 는 대략적인 데이터 시작 연도)
const ML = (market, exchange, name, assetClass, since) => ({market, exchange, name, assetClass, since});
export function listMarketsForHistory(){
  return [
    ML("BTCUSDT", "binancef", "비트코인 무기한", "crypto", 2019), ML("ETHUSDT", "binancef", "이더리움 무기한", "crypto", 2019),
    ML("SOLUSDT", "binancef", "솔라나 무기한", "crypto", 2020), ML("XRPUSDT", "binancef", "리플 무기한", "crypto", 2020),
    ML("BTC-USD", "yahoo", "비트코인 (2014년부터, 2017년 이전 과거용)", "crypto", 2014),
    ML("SPY", "yahoo", "S&P500 ETF", "us_stock", 1993), ML("QQQ", "yahoo", "나스닥100 ETF", "us_stock", 1999),
    ML("NVDA", "yahoo", "엔비디아", "us_stock", 1999), ML("AAPL", "yahoo", "애플", "us_stock", 1980), ML("TSLA", "yahoo", "테슬라", "us_stock", 2010),
    ML("^GSPC", "yahoo", "S&P 500 지수 (1927년부터)", "index", 1927), ML("^IXIC", "yahoo", "나스닥 종합 지수", "index", 1971),
    ML("^KS11", "yahoo", "코스피 지수", "index", 1996), ML("^KS200", "yahoo", "코스피200 지수", "index", 1990),
    ML("005930.KS", "yahoo", "삼성전자", "kr_stock", 2000), ML("000660.KS", "yahoo", "SK하이닉스", "kr_stock", 2000),
    ML("ES=F", "yahoo", "S&P500 선물", "futures", 2000), ML("NQ=F", "yahoo", "나스닥100 선물", "futures", 2000),
    ML("CL=F", "yahoo", "WTI 원유 선물", "futures", 2000), ML("GC=F", "yahoo", "금 선물", "futures", 2000),
    ML("SI=F", "yahoo", "은 선물", "futures", 2000), ML("NG=F", "yahoo", "천연가스 선물", "futures", 2000),
    ML("ZN=F", "yahoo", "미 10년 국채 선물", "futures", 2000),
  ];
}
// 종목·거래소 → 자산군
export function assetClassOf(market, exchange){
  if (exchange !== "yahoo") return "crypto";
  const m = String(market || "");
  if (/-USD$|-USDT$/.test(m)) return "crypto";
  if (/=F$/.test(m)) return "futures";
  if (/^\^/.test(m)) return "index";
  if (/\.K[SQ]$/.test(m) || /^\d{6}$/.test(m)) return "kr_stock";
  return "us_stock";
}
// 자산군별 기본 비용 (편도 %). 현실적인 시뮬레이션용 기본값이며 spec.risk 에 덮어쓴다.
//   crypto: 바이낸스 무기한 테이커 0.04 · 슬리피지 0.01 · 8시간 펀딩 0.01 / 주식: 온라인 증권사 0.015 · 0.02 / 선물·지수: 0.01 · 0.01
//   국내 주식은 매도 시 증권거래세(약 0.15~0.2%)가 따로 붙는다 — 반영하려면 fee_pct 에 편도 0.09 정도를 더한다
const COSTS = {
  crypto: {fee_pct: 0.04, slippage_pct: 0.01, funding_rate_8h_pct: 0.01},
  us_stock: {fee_pct: 0.015, slippage_pct: 0.02, funding_rate_8h_pct: 0},
  kr_stock: {fee_pct: 0.015, slippage_pct: 0.02, funding_rate_8h_pct: 0},
  futures: {fee_pct: 0.01, slippage_pct: 0.01, funding_rate_8h_pct: 0},
  index: {fee_pct: 0.01, slippage_pct: 0.01, funding_rate_8h_pct: 0},
};
export function assetCosts(assetClass){
  const k = assetClass === "stock" ? "us_stock" : assetClass;
  return {...(COSTS[k] || COSTS.crypto)};
}
