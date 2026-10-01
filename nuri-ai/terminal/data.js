// 누리 차트 터미널 — 데이터 연결 (백엔드 없음: 브라우저 모듈로 바로)
// - 캔들: ../trade.js exchanges(apiBase, webGet).candles (빠른 첫 화면) · ../history.js historyCandles (전체 과거, IndexedDB 캐시)
// - 실시간: 바이낸스 웹소켓(kline) → 실패하면 REST 폴링 (apiBase 경유, 실행기 연결 시 프록시)
// - 흐름: ../flow.js flowSnapshot(호가 벽 · 고래 · 선물 흐름 · 흐름 점수) · liquidationEstimate(청산 구간 추정)
// 차트 캔들 형식: {time: 초(UTC), open, high, low, close, volume}  ← quant.js/history.js 형식 {t: ms, o, h, l, c, v} 에서 변환
import { apiBase, webGet, LAUNCHER, detectLauncher } from "../engine.js";
import { exchanges, US_LIST, KR_LIST, GFUT_LIST, IDX_LIST } from "../trade.js";

export const IVS = [["1m", "1분"], ["3m", "3분"], ["5m", "5분"], ["6m", "6분"], ["8m", "8분"], ["10m", "10분"], ["15m", "15분"], ["1h", "1시간"], ["4h", "4시간"], ["1d", "1일"], ["1w", "1주"]];
export const IV_LABEL = Object.fromEntries(IVS);
export const IV_SEC = { "1m": 60, "3m": 180, "5m": 300, "6m": 360, "8m": 480, "10m": 600, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800 };
const TF = { "1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D", "1w": "W" };
const TF_BACK = { "1": "1m", "3": "3m", "5": "5m", "6": "6m", "8": "8m", "10": "10m", "15": "15m", "60": "1h", "240": "4h", "D": "1d", "1D": "1d", "W": "1w", "1W": "1w", "1d": "1d", "1w": "1w" };

/* ---------- 3·6·8·10분봉: 거래소가 직접 주면 그대로, 아니면 작은 봉을 묶어서 만든다 ---------- */
// 바이낸스: 3분 그대로 · 6·8분은 1분봉, 10분은 5분봉을 묶음 / 업비트: 3·10분 그대로 · 6분은 3분봉, 8분은 1분봉 / 야후: 3분은 1분봉, 6·8분은 2분봉, 10분은 5분봉
const CUSTOM = {
  "3m":  { binance: ["3m", 1], upbit: ["3", 1], yahoo: ["1m", 3, "5d"] },
  "6m":  { binance: ["1m", 6], upbit: ["3", 2], yahoo: ["2m", 3, "1mo"] },
  "8m":  { binance: ["1m", 8], upbit: ["1", 8], yahoo: ["2m", 4, "1mo"] },
  "10m": { binance: ["5m", 2], upbit: ["10", 1], yahoo: ["5m", 2, "1mo"] },
};
export const isCustomIv = (iv) => !!CUSTOM[iv];
// 같은 시각 구간(유닉스 시간 기준 sec 단위)으로 묶기 — 마지막 구간은 진행 중인 봉
export function aggregate(bars, sec) {
  const out = []; let cur = null;
  for (const b of bars) {
    const t = Math.floor(b.time / sec) * sec;
    if (!cur || cur.time !== t) { cur = { time: t, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume || 0 }; out.push(cur); }
    else { cur.high = Math.max(cur.high, b.high); cur.low = Math.min(cur.low, b.low); cur.close = b.close; cur.volume += b.volume || 0; }
  }
  return out;
}
// 바이낸스 klines 를 뒤로 넘기며 count 개까지
async function binanceKlines(exchange, symbol, iv, count) {
  const path = exchange === "binancef" ? "/fapi/v1/klines" : "/klines", lim = exchange === "binancef" ? 1500 : 1000;
  let end = null, rows = [];
  while (rows.length < count) {
    const r = await fetch(`${apiBase(exchange)}${path}?symbol=${encodeURIComponent(symbol)}&interval=${iv}&limit=${Math.min(lim, count - rows.length)}${end ? `&endTime=${end}` : ""}`, { headers: { accept: "application/json" } });
    if (!r.ok) throw new Error("시세 " + r.status);
    const j = await r.json(); if (!Array.isArray(j) || !j.length) break;
    const page = j.map((k) => ({ time: Math.floor(k[0] / 1000), open: +k[1], high: +k[2], low: +k[3], close: +k[4], volume: +k[5] }));
    rows = [...page, ...rows]; end = j[0][0] - 1;
    if (j.length < Math.min(lim, count)) break;
  }
  return clean(rows);
}
async function yahooBars(symbol, iv, range) {
  let err = null;
  for (const s of _yRes.has(symbol) ? [_yRes.get(symbol)] : yCands(symbol)) {
    try {
      const j = await webGet(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(s)}?interval=${iv}&range=${range}&includePrePost=false`, "json");
      const res = j?.chart?.result?.[0], q = res?.indicators?.quote?.[0] || {};
      const rows = (res?.timestamp || []).map((t, i) => ({ time: t, open: q.open?.[i], high: q.high?.[i], low: q.low?.[i], close: q.close?.[i], volume: q.volume?.[i] || 0 })).filter((b) => b.open != null && b.close != null && b.high != null && b.low != null);
      if (!rows.length) throw new Error("야후 데이터가 비어 있습니다: " + s);
      _yRes.set(symbol, s);
      return { rows: clean(rows), currency: res.meta?.currency, name: res.meta?.shortName || res.meta?.longName, resolved: s };
    } catch (e) { err = e; }
  }
  throw err || new Error("종목을 찾을 수 없습니다: " + symbol);
}
// 3·6·8·10분봉 캔들 (want: 원하는 봉 개수)
async function customCandles({ exchange, symbol, interval }, want = 1500) {
  const sec = IV_SEC[interval], c = CUSTOM[interval];
  if (exchange === "binance" || exchange === "binancef") {
    const [iv, n] = c.binance;
    return { candles: aggregate(await binanceKlines(exchange, symbol, iv, Math.min(want * n, 12000)), sec), currency: "USDT" };
  }
  if (exchange === "upbit") {
    const [tf, n] = c.upbit;
    return { candles: aggregate(clean((await ex().upbit.candles(symbol, tf, Math.min(800 * n, 3200))).map(toBar)), sec), currency: "KRW" };
  }
  const [iv, , range] = c.yahoo, r = await yahooBars(symbol, iv, range);
  return { candles: aggregate(r.rows, sec), currency: r.currency || "USD", name: r.name, resolved: r.resolved };
}
export const normIv = (iv) => IV_SEC[iv] ? iv : TF_BACK[String(iv)] || TF_BACK[String(iv).toUpperCase()] || "1h";

export const EXCHANGES = [["binancef", "바이낸스 선물 (USDT-M)"], ["binance", "바이낸스 현물"], ["upbit", "업비트 (KRW)"], ["yahoo", "주식·지수·선물 (야후)"]];
export const EX_SHORT = { binancef: "바이낸스 선물", binance: "바이낸스 현물", upbit: "업비트", yahoo: "야후" };
export const isCrypto = (ex) => ex !== "yahoo";

// 기본 종목 (검색창 프리셋)
export const PRESETS = [
  ["BTCUSDT", "binancef", "비트코인 무기한"], ["ETHUSDT", "binancef", "이더리움 무기한"], ["SOLUSDT", "binancef", "솔라나 무기한"], ["XRPUSDT", "binancef", "리플 무기한"],
  ["KRW-BTC", "upbit", "비트코인 (원화)"],
  ["NVDA", "yahoo", "엔비디아"], ["TSLA", "yahoo", "테슬라"], ["AAPL", "yahoo", "애플"], ["QQQ", "yahoo", "나스닥100 ETF"], ["SPY", "yahoo", "S&P500 ETF"],
  ["005930", "yahoo", "삼성전자"], ["000660", "yahoo", "SK하이닉스"],
  ["^KS11", "yahoo", "코스피"], ["^KS200", "yahoo", "코스피200"], ["^GSPC", "yahoo", "S&P 500"], ["^IXIC", "yahoo", "나스닥 종합"],
  ["ES=F", "yahoo", "S&P500 선물"], ["NQ=F", "yahoo", "나스닥100 선물"], ["CL=F", "yahoo", "WTI 원유 선물"], ["GC=F", "yahoo", "금 선물"], ["SI=F", "yahoo", "은 선물"],
];
// 검색용 야후 종목 전체 (trade.js 목록 + 프리셋)
export const YAHOO_ALL = [...IDX_LIST, ...KR_LIST.map(([s, n]) => [s.replace(/\.K[SQ]$/, ""), n]), ...US_LIST, ...GFUT_LIST, ["^KS200", "코스피200"]];

let EX = null, _launch = null;
const ex = () => EX || (EX = exchanges(apiBase, webGet));
export async function ensureLauncher() { if (LAUNCHER.on) return true; return _launch || (_launch = detectLauncher().catch(() => false)); }

// 종목 · 거래소 정리
export function normSymbol(exchange, s) {
  s = String(s || "").trim();
  if (exchange === "upbit") return /^[A-Z]+-[A-Z0-9]+$/i.test(s) ? s.toUpperCase() : "KRW-" + s.toUpperCase().replace(/(USDT|KRW)$/, "");
  if (exchange === "binance" || exchange === "binancef") { s = s.toUpperCase().replace(/^KRW-/, "").replace(/[/_-]/g, ""); return /(USDT|USDC|FDUSD)$/.test(s) ? s : s + "USDT"; }
  return s.toUpperCase();
}
export function guessExchange(sym, cur = "binancef") {
  const s = String(sym || "").trim().toUpperCase();
  const p = PRESETS.find((x) => x[0] === s);
  if (p) return p[1];
  if (/^KRW-/.test(s)) return "upbit";
  if (/(USDT|USDC|FDUSD)$/.test(s)) return cur === "binance" ? "binance" : "binancef";
  if (isCrypto(cur) && /^[A-Z]{2,10}$/.test(s) && !YAHOO_ALL.some((x) => x[0] === s)) return cur;   // 'ETH' 처럼 코인 이름만
  return "yahoo";
}
export function nameOf(exchange, symbol) {
  const p = PRESETS.find((x) => x[0] === symbol && x[1] === exchange);
  if (p) return p[2];
  if (exchange === "yahoo") return (YAHOO_ALL.find((x) => x[0] === symbol || x[0] === symbol.replace(/\.K[SQ]$/, "")) || [])[1] || "";
  return "";
}

const toBar = (b) => ({ time: Math.floor(+b.t / 1000), open: +b.o, high: +b.h, low: +b.l, close: +b.c, volume: +b.v || 0 });
export const toQuant = (c) => c.map((b) => ({ t: b.time * 1000, o: b.open, h: b.high, l: b.low, c: b.close, v: b.volume }));
// 시간 오름차순 · 중복 제거 · 숫자 아닌 봉 제거 (lightweight-charts 는 같은 시각을 받지 않는다)
export function clean(rows) {
  const m = new Map();
  for (const b of rows) if ([b.open, b.high, b.low, b.close].every(Number.isFinite) && Number.isFinite(b.time)) m.set(b.time, b);
  return [...m.values()].sort((a, b) => a.time - b.time);
}

// 야후: 국내 6자리 코드는 .KS → .KQ 순서로
const yCands = (s) => /^\d{6}$/.test(s) ? [s + ".KS", s + ".KQ"] : [s];
const _yRes = new Map();
async function yahooCandles(symbol, interval, total) {
  let err = null;
  for (const s of _yRes.has(symbol) ? [_yRes.get(symbol)] : yCands(symbol)) {
    try {
      const rows = await ex().yahoo.candles(s, TF[interval], total);
      if (!rows.length) throw new Error("야후 데이터가 비어 있습니다: " + s);
      _yRes.set(symbol, s);
      return { rows, currency: rows.currency, name: rows.name, resolved: s };
    } catch (e) { err = e; }
  }
  throw err || new Error("종목을 찾을 수 없습니다: " + symbol);
}

// 첫 화면 캔들 (빠르게 1,000~1,500봉)
export async function loadCandles({ exchange, symbol, interval }) {
  await ensureLauncher();
  if (CUSTOM[interval]) {
    const r = await customCandles({ exchange, symbol, interval });
    if (!r.candles.length) throw new Error(`${EX_SHORT[exchange]}에 ${symbol} ${IV_LABEL[interval]} 봉이 없습니다`);
    return { candles: r.candles, meta: { currency: r.currency, name: r.name || nameOf(exchange, symbol), resolved: r.resolved || symbol, source: EX_SHORT[exchange] + (CUSTOM[interval][exchange === "binancef" ? "binance" : exchange]?.[1] > 1 ? " · 작은 봉을 묶어 만든 봉" : "") } };
  }
  if (exchange === "yahoo") {
    const r = await yahooCandles(symbol, interval, 5000);
    return { candles: clean(r.rows.map(toBar)), meta: { currency: r.currency || "USD", name: r.name || nameOf(exchange, symbol), resolved: r.resolved, source: "야후 파이낸스" } };
  }
  const E = ex()[exchange];
  if (!E) throw new Error("지원하지 않는 거래소: " + exchange);
  const total = exchange === "upbit" ? 800 : exchange === "binance" ? 1000 : 1500;
  const rows = await E.candles(symbol, TF[interval], total);
  if (!rows.length) throw new Error(`${EX_SHORT[exchange]}에 ${symbol} ${IV_LABEL[interval]} 봉이 없습니다`);
  return { candles: clean(rows.map(toBar)), meta: { currency: exchange === "upbit" ? "KRW" : "USDT", name: nameOf(exchange, symbol), resolved: symbol, source: EX_SHORT[exchange] } };
}

// 최신 몇 봉 (폴링)
const Y_LIVE = { "1m": ["1m", "1d"], "5m": ["5m", "1d"], "15m": ["15m", "5d"], "1h": ["60m", "5d"], "1d": ["1d", "5d"], "1w": ["1wk", "1mo"] };
export async function latestBars({ exchange, symbol, interval }) {
  if (CUSTOM[interval]) {   // 진행 중인 봉까지 다시 묶어서 마지막 2개
    const c = CUSTOM[interval], sec = IV_SEC[interval];
    if (exchange === "binance" || exchange === "binancef") { const [iv, n] = c.binance; return aggregate(await binanceKlines(exchange, symbol, iv, n * 2 + 1), sec).slice(-2); }
    if (exchange === "upbit") { const [tf, n] = c.upbit; return aggregate(clean((await ex().upbit.candles(symbol, tf, n * 2 + 1)).map(toBar)), sec).slice(-2); }
    const [iv] = c.yahoo; return aggregate((await yahooBars(symbol, iv, "1d")).rows, sec).slice(-2);
  }
  if (exchange === "binancef" || exchange === "binance") {
    const path = exchange === "binancef" ? "/fapi/v1/klines" : "/klines";
    const r = await fetch(`${apiBase(exchange)}${path}?symbol=${encodeURIComponent(symbol)}&interval=${interval}&limit=3`, { headers: { accept: "application/json" } });
    if (!r.ok) throw new Error("시세 " + r.status);
    return clean((await r.json()).map((k) => ({ time: Math.floor(k[0] / 1000), open: +k[1], high: +k[2], low: +k[3], close: +k[4], volume: +k[5] })));
  }
  if (exchange === "upbit") return clean((await ex().upbit.candles(symbol, TF[interval], 2)).map(toBar));
  const y = Y_LIVE[interval];
  if (!y) return [];                                     // 야후 4시간봉은 60분봉을 묶은 값이라 실시간 갱신 안 함
  const sym = _yRes.get(symbol) || yCands(symbol)[0];
  const j = await webGet(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=${y[0]}&range=${y[1]}&includePrePost=false`, "json");
  const res = j?.chart?.result?.[0], q = res?.indicators?.quote?.[0] || {};
  const rows = (res?.timestamp || []).map((t, i) => ({ t: t * 1000, o: q.open?.[i], h: q.high?.[i], l: q.low?.[i], c: q.close?.[i], v: q.volume?.[i] || 0 }))
    .filter((b) => b.o != null && b.h != null && b.l != null && b.c != null);
  return clean(rows.slice(-3).map(toBar));
}

// 바이낸스 실시간 kline 웹소켓. onBar(bar) · onFail(reason). 반환: close()
// 한 번도 열리지 못하면(방화벽·프록시) 10분 동안은 다시 시도하지 않고 바로 폴링
let wsBlockedUntil = 0;
export function klineSocket({ exchange, symbol, interval }, onBar, onFail) {
  if (exchange !== "binancef" && exchange !== "binance") return null;
  if (CUSTOM[interval] && interval !== "3m") return null;   // 묶어 만든 봉은 폴링으로 갱신
  if (typeof WebSocket !== "function" || Date.now() < wsBlockedUntil) return null;
  const s = symbol.toLowerCase(), url = exchange === "binancef" ? `wss://fstream.binance.com/ws/${s}@kline_${interval}` : `wss://stream.binance.com:9443/ws/${s}@kline_${interval}`;
  let ws, closed = false, opened = false;
  try { ws = new WebSocket(url); } catch (e) { onFail?.("웹소켓 열기 실패"); return null; }
  const timer = setTimeout(() => { if (!opened && !closed) { try { ws.close(); } catch (e) { /* 무시 */ } } }, 6000);
  ws.onopen = () => { opened = true; clearTimeout(timer); };
  ws.onmessage = (e) => {
    try {
      const k = JSON.parse(e.data)?.k;
      if (k) onBar({ time: Math.floor(k.t / 1000), open: +k.o, high: +k.h, low: +k.l, close: +k.c, volume: +k.v });
    } catch (err) { /* 무시 */ }
  };
  ws.onerror = () => {};
  ws.onclose = () => { clearTimeout(timer); if (!closed) { closed = true; if (!opened) wsBlockedUntil = Date.now() + 600000; onFail?.(opened ? "웹소켓 끊김" : "웹소켓 연결 안 됨"); } };
  return { close() { closed = true; clearTimeout(timer); try { ws.close(); } catch (e) { /* 무시 */ } }, get open() { return opened && !closed; } };
}

// 전체 과거 (history.js · IndexedDB 캐시)
export async function fullHistory({ exchange, symbol, interval, resolved }, onProgress) {
  await ensureLauncher();
  const { historyCandles } = await import("../history.js");
  const market = exchange === "yahoo" ? (resolved || symbol) : symbol;
  if (CUSTOM[interval]) {   // 묶어 만드는 봉: 작은 봉 전체 과거를 받아 묶는다 (바이낸스·업비트)
    if (exchange === "yahoo") { const r = await customCandles({ exchange, symbol, interval }); return { candles: r.candles, note: "야후 분봉은 최근 한 달까지만 제공됩니다", complete: false, currency: r.currency }; }
    const base = { binance: { "3m": "3m", "6m": "1m", "8m": "1m", "10m": "5m" }, upbit: { "3m": "3m", "6m": "3m", "8m": "1m", "10m": "5m" } }[exchange === "upbit" ? "upbit" : "binance"][interval];
    const r = await historyCandles({ market, exchange, interval: base, maxBars: 50000 * Math.round(IV_SEC[interval] / IV_SEC[base] || 1), onProgress });
    return { candles: aggregate(clean(r.candles.map(toBar)), IV_SEC[interval]), note: r.note, complete: r.complete, truncated: r.truncated, currency: r.currency };
  }
  const r = await historyCandles({ market, exchange, interval, maxBars: 50000, onProgress });
  return { candles: clean(r.candles.map(toBar)), note: r.note, complete: r.complete, truncated: r.truncated, currency: r.currency };
}

// 흐름 (코인만)
let _flow = null;
const flowMod = () => _flow || (_flow = import("../flow.js"));
export async function flowSnapshot({ exchange, symbol }) {
  const F = await flowMod();
  return (await F.flowSnapshot({ symbol, exchange: exchange === "upbit" ? "upbit" : exchange })).data;
}
export async function liquidation({ symbol }) {
  const F = await flowMod();
  return (await F.liquidationEstimate({ symbol, exchange: "binancef" })).data;
}
