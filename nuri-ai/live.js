// 실거래 (내 계좌): 모의투자에서 스스로 증명한 전략만, 사용자가 직접 켠 경우에만, 코드가 전략 규칙대로 주문한다.
//
// 지키는 원칙 (화면에도 그대로 보여 준다)
//  1. 기본은 꺼짐. 사용자가 켜고, 자기 API 키를 넣고, 아래 관문을 모두 통과해야만 주문이 나간다.
//  2. AI 직원(에이전트)은 주문하지 않는다. 주문은 paper.js 이벤트를 받는 이 코드만 낸다 (도구로 노출하지 않음).
//  3. 테스트넷 먼저. 실거래(메인넷)는 확인 문구를 직접 입력해야 바뀐다.
//  4. 승격 관문: 모의투자 14일 이상 · 청산 거래 20회 이상 · 손익비 1.2 이상 · 수익률 0% 초과 · 최대 낙폭 25% 미만.
//  5. 승인 모드가 기본: 주문마다 확인 창(60초 안에 승인하지 않으면 자동 취소). 자동 모드는 확인 문구 입력 후에만.
//  6. 하드 한도: 1회 주문 금액 · 레버리지 · 동시 포지션 수 · 하루 실현 손실(넘으면 그날 신규 진입 정지) · 허용 종목.
//  7. 긴급 정지: 미체결 주문 취소 + 포지션 시장가 청산(reduce-only) + 실거래 끄기.
//  8. 키는 이 브라우저(앱 설정 = localStorage)에만 저장. 비밀키는 WebCrypto 서명에만 쓰고 어디에도 보내거나 기록하지 않는다.
//  9. 모든 판단·주문·응답을 감사 기록(live:log)에 남기고 CSV로 내보낼 수 있다.
//
// 브라우저에서는 engine.js의 settings/ls/LAUNCHER를 쓴다. Node 테스트에서는 _setDeps로 fetch·저장소·시계를 주입한다.

export const MAINNET_PHRASE = "실거래를 시작합니다";
export const AUTO_PHRASE = "자동매매에 동의합니다";
export const APPROVAL_MS = 60000;
export const GATE = {days: 14, trades: 20, pf: 1.2, ret: 0, mdd: 25};
const PAPER_START = 10000;                // paper.js의 전략별 가상 원금
const FEE = 0.0005;                       // 선물 시장가 수수료 어림 (손실 한도 계산용)
const UPBIT_FEE = 0.0005, UPBIT_MIN_KRW = 5000;
const LOG_KEY = "live:log", POS_KEY = "live:pos", DAY_KEY = "live:day", LOG_MAX = 3000;
export const HOSTS = {binancef_test: "https://testnet.binancefuture.com", binancef: "https://fapi.binance.com", upbit: "https://api.upbit.com/v1"};
export const SUPPORTED = {binancef: "바이낸스 USDT-M 선물", upbit: "업비트 KRW 현물"};

export const PRINCIPLES = [
  "기본은 꺼져 있습니다. 직접 켜고, 내 API 키를 넣고, 관문을 통과한 전략만 실제 주문이 나갑니다.",
  "AI 직원은 주문하지 않습니다. 모의투자 엔진의 신호를 받은 코드만, 전략 규칙과 아래 한도대로 주문합니다.",
  "테스트넷(가짜 돈)이 기본입니다. 실거래는 확인 문구 '" + MAINNET_PHRASE + "'를 직접 입력해야 바뀝니다.",
  `승격 관문: 모의투자 ${GATE.days}일 이상 · 청산 거래 ${GATE.trades}회 이상 · 손익비 ${GATE.pf} 이상 · 수익률 0% 초과 · 최대 낙폭 ${GATE.mdd}% 미만.`,
  "승인 모드가 기본입니다. 주문마다 확인 창이 뜨고 60초 안에 승인하지 않으면 취소됩니다. 자동 모드도 한도는 그대로 지킵니다.",
  "한도를 넘는 주문(금액·레버리지·포지션 수·허용 종목)은 막고 기록합니다. 하루 실현 손실 한도에 닿으면 그날은 새 진입을 멈춥니다.",
  "'모두 정지·청산'은 미체결 주문을 취소하고 포지션을 시장가(reduce-only)로 닫은 뒤 실거래를 끕니다.",
  "API 키는 이 브라우저에만 저장되고, 비밀키는 브라우저 안에서 서명(WebCrypto)에만 쓰입니다. 기록·전송하지 않습니다.",
  "출금 권한 없는 '거래 전용' 키를 만들고 IP 제한을 거세요. 공용 PC에서는 쓰지 마세요.",
  "모든 판단·주문·응답은 감사 기록에 남고 CSV로 내보낼 수 있습니다. 과거 성과가 미래 수익을 보장하지 않습니다."
];

export const DEFAULTS = {
  enabled: false, env: "testnet", mode: "approve", marginType: "ISOLATED", keys: {}, linked: {}, halted: null,
  limits: {maxNotional: 50, orderNotional: 20, maxLeverage: 3, maxPositions: 2, maxTotalNotional: 100, dailyLoss: 20,
    symbols: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "KRW-BTC", "KRW-ETH"],
    krwMaxNotional: 70000, krwOrderNotional: 10000, krwDailyLoss: 30000}
};

/* ============ 의존성 (브라우저: engine.js, 테스트: 주입) ============ */
const D = {
  fetch: (...a) => globalThis.fetch(...a),
  now: () => Date.now(),
  crypto: globalThis.crypto,
  settings: null, saveSettings: () => {},
  store: null,                 // {get(k, d), set(k, v)}
  launcher: () => false,       // GHNano.exe 중계 사용 여부
  loadBook: null,              // async () => paper book
  approvalMs: APPROVAL_MS,
  sleep: ms => new Promise(r => setTimeout(r, ms))
};
const memStore = () => { const m = new Map(); return {get: (k, d) => m.has(k) ? structuredClone(m.get(k)) : d, set: (k, v) => m.set(k, structuredClone(v))}; };
if (typeof window !== "undefined" && typeof document !== "undefined"){
  const E = await import("./engine.js");
  Object.assign(D, {settings: E.settings, saveSettings: E.saveSettings, store: E.ls, launcher: () => E.LAUNCHER.on});
}
// 테스트 전용: 의존성 바꿔 끼우기 (캐시도 초기화)
export function _setDeps(p){ Object.assign(D, p); if (!D.settings) D.settings = {}; if (!D.store) D.store = memStore(); timeOffset = {}; rulesCache = {}; dualChecked = {}; }
const S = () => D.settings || (D.settings = {});
const store = () => D.store || (D.store = memStore());
const bookOf = async () => D.loadBook ? D.loadBook() : (await import("./paper.js")).loadBook();

/* ============ 설정 ============ */
function cfg(){
  const st = S();
  const L = st.live && typeof st.live === "object" ? st.live : (st.live = {});
  for (const [k, v] of Object.entries(DEFAULTS)) if (L[k] === undefined) L[k] = structuredClone(v);
  L.limits = {...DEFAULTS.limits, ...L.limits};
  return L;
}
const save = () => { try { D.saveSettings(); } catch(e){} emit(); };
const mask = s => s ? "…" + String(s).slice(-4) : "";
// 화면용 설정 사본: 비밀키는 절대 돌려주지 않는다
export function liveCfg(){
  const L = cfg(), keys = {};
  for (const [id, k] of Object.entries(L.keys || {})) if (k) keys[id] = {set: !!(k.key || k.access) && !!k.secret, hint: mask(k.key || k.access)};
  return {...structuredClone({...L, keys: undefined}), keys, halted: isHalted() ? L.halted : null};
}
const num = (v, lo, hi, d) => { const n = +v; return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : d; };
export class LiveError extends Error { constructor(code, msg, extra){ super(msg); this.code = code; Object.assign(this, extra || {}); } }

// 설정 바꾸기. 실거래 전환·자동 모드는 확인 문구(patch.confirm)가 맞아야 한다.
export function setLive(patch = {}){
  const L = cfg(), changed = [];
  if (patch.env !== undefined && patch.env !== L.env){
    if (!["testnet", "mainnet"].includes(patch.env)) throw new LiveError("BAD_ENV", "환경은 testnet 또는 mainnet입니다");
    if (patch.env === "mainnet" && String(patch.confirm || "").trim() !== MAINNET_PHRASE) throw new LiveError("CONFIRM", `실거래로 바꾸려면 '${MAINNET_PHRASE}'를 정확히 입력하세요`);
    L.env = patch.env; L.enabled = false; L.mode = "approve";           // 환경을 바꾸면 끄고 승인 모드로 되돌린다
    changed.push(`환경 → ${patch.env === "mainnet" ? "실거래(메인넷)" : "테스트넷"} (실거래 꺼짐·승인 모드)`);
  }
  if (patch.mode !== undefined && patch.mode !== L.mode){
    if (!["approve", "auto"].includes(patch.mode)) throw new LiveError("BAD_MODE", "모드는 approve 또는 auto입니다");
    if (patch.mode === "auto" && String(patch.confirm || "").trim() !== AUTO_PHRASE) throw new LiveError("CONFIRM", `자동 모드를 켜려면 '${AUTO_PHRASE}'를 정확히 입력하세요`);
    L.mode = patch.mode; changed.push(patch.mode === "auto" ? "자동 모드" : "승인 모드");
  }
  if (patch.keys){
    L.keys = L.keys || {};
    for (const [id, k] of Object.entries(patch.keys)){
      if (!["binancef_test", "binancef", "upbit"].includes(id)) continue;
      if (!k){ delete L.keys[id]; changed.push(`${id} 키 삭제`); continue; }
      const key = String(k.key || k.access || "").trim(), secret = String(k.secret || "").trim();
      if (!key || !secret) throw new LiveError("BAD_KEY", "API 키와 비밀키를 모두 넣으세요");
      if (/\s/.test(key + secret)) throw new LiveError("BAD_KEY", "키에 공백이 있습니다");
      L.keys[id] = id === "upbit" ? {access: key, secret} : {key, secret};
      changed.push(`${id} 키 저장(${mask(key)})`);
    }
  }
  if (patch.limits){
    const o = L.limits, p = patch.limits, n = {...o};
    if (p.maxNotional !== undefined) n.maxNotional = num(p.maxNotional, 1, 1e6, o.maxNotional);
    if (p.orderNotional !== undefined) n.orderNotional = num(p.orderNotional, 1, 1e6, o.orderNotional);
    if (p.maxLeverage !== undefined) n.maxLeverage = Math.round(num(p.maxLeverage, 1, 125, o.maxLeverage));
    if (p.maxPositions !== undefined) n.maxPositions = Math.round(num(p.maxPositions, 1, 50, o.maxPositions));
    if (p.maxTotalNotional !== undefined) n.maxTotalNotional = num(p.maxTotalNotional, 1, 1e7, o.maxTotalNotional);
    if (p.dailyLoss !== undefined) n.dailyLoss = num(p.dailyLoss, 1, 1e6, o.dailyLoss);
    if (p.krwMaxNotional !== undefined) n.krwMaxNotional = num(p.krwMaxNotional, UPBIT_MIN_KRW, 1e9, o.krwMaxNotional);
    if (p.krwOrderNotional !== undefined) n.krwOrderNotional = num(p.krwOrderNotional, UPBIT_MIN_KRW, 1e9, o.krwOrderNotional);
    if (p.krwDailyLoss !== undefined) n.krwDailyLoss = num(p.krwDailyLoss, 1000, 1e9, o.krwDailyLoss);
    if (p.symbols !== undefined){
      const arr = (Array.isArray(p.symbols) ? p.symbols : String(p.symbols).split(/[\s,]+/)).map(x => String(x).trim().toUpperCase()).filter(Boolean);
      const bad = arr.filter(x => !/^[A-Z0-9]{2,20}$|^KRW-[A-Z0-9]{1,15}$/.test(x));
      if (bad.length) throw new LiveError("BAD_SYMBOL", "종목 이름이 올바르지 않습니다: " + bad.join(", "));
      n.symbols = [...new Set(arr)];
    }
    if (n.orderNotional > n.maxNotional) throw new LiveError("BAD_LIMIT", "1회 주문 금액이 1회 최대 금액보다 큽니다");
    if (n.krwOrderNotional > n.krwMaxNotional) throw new LiveError("BAD_LIMIT", "업비트 1회 주문 금액이 1회 최대 금액보다 큽니다");
    L.limits = n; changed.push("한도 변경 " + JSON.stringify(n));
  }
  if (patch.marginType !== undefined){ L.marginType = patch.marginType === "CROSSED" ? "CROSSED" : "ISOLATED"; changed.push("마진 " + L.marginType); }
  if (patch.enabled !== undefined && !!patch.enabled !== L.enabled){
    if (patch.enabled){
      const k = L.keys || {}, bn = k[L.env === "mainnet" ? "binancef" : "binancef_test"], up = L.env === "mainnet" && k.upbit;
      if (!(bn?.key && bn?.secret) && !(up?.access && up?.secret)) throw new LiveError("NO_KEY", `${L.env === "mainnet" ? "실거래" : "테스트넷"} API 키를 먼저 넣으세요`);
    }
    L.enabled = !!patch.enabled; changed.push(L.enabled ? "실거래 켬" : "실거래 끔");
  }
  if (changed.length){ save(); log({kind: "config", msg: changed.join(" · ")}); }
  return liveCfg();
}

/* ============ 승격 관문 ============ */
export function gateFor(s, now = D.now()){
  const trades = Array.isArray(s?.trades) ? s.trades : [];
  const days = s?.created ? (now - s.created) / 864e5 : 0;
  let gains = 0, losses = 0;
  for (const t of trades){ const p = +t.pnl || 0; if (p > 0) gains += p; else losses -= p; }
  const pf = losses > 0 ? gains / losses : gains > 0 ? Infinity : 0;
  const eq = s?.equity?.at?.(-1)?.v ?? PAPER_START, ret = (eq / PAPER_START - 1) * 100;
  // 최대 낙폭: 거래 누적 손익 곡선과 (최근) 평가금액 곡선 중 더 나쁜 쪽
  const ddOf = vals => { let peak = -Infinity, dd = 0; for (const v of vals){ if (!(v > 0)) { if (peak > 0) dd = Math.max(dd, 100); continue; } peak = Math.max(peak, v); dd = Math.max(dd, (1 - v / peak) * 100); } return dd; };
  let cum = PAPER_START; const tc = [PAPER_START, ...trades.map(t => (cum += +t.pnl || 0))];
  const mdd = Math.max(ddOf(tc), ddOf((s?.equity || []).map(e => +e.v)));
  const f = (v, d = 2) => Number.isFinite(v) ? v.toFixed(d) : "∞";
  const checks = [
    {id: "days", name: "모의투자 기간", ok: days >= GATE.days, value: days, need: `${GATE.days}일 이상`, text: `${f(days, 1)}일`},
    {id: "trades", name: "청산된 거래 수", ok: trades.length >= GATE.trades, value: trades.length, need: `${GATE.trades}회 이상`, text: `${trades.length}회`},
    {id: "pf", name: "손익비(Profit Factor)", ok: pf >= GATE.pf, value: pf, need: `${GATE.pf} 이상`, text: f(pf)},
    {id: "ret", name: "모의 수익률", ok: ret > GATE.ret, value: ret, need: "0% 초과", text: `${ret >= 0 ? "+" : ""}${f(ret)}%`},
    {id: "mdd", name: "최대 낙폭(MDD)", ok: mdd < GATE.mdd, value: mdd, need: `${GATE.mdd}% 미만`, text: `${f(mdd)}%`},
    // 과최적화 방어: 전략 개발 때 저장해 둔 견고성·코인 일반화 결과를 실돈 관문에도 적용 (옛 전략은 미측정 → 통과)
    {id: "robust", name: "과최적화 검사(견고성)", ok: !s?.robust || s.robust.ok !== false, value: s?.robust?.ok, need: "통과 또는 미측정", text: s?.robust ? (s.robust.ok === false ? "미달" : "통과") : "미측정"},
    {id: "generalize", name: "여러 코인 일반화", ok: !s?.crossCoin || !s.crossCoin.total || s.crossCoin.profitable >= 1, value: s?.crossCoin || null, need: "다른 코인 1개+ 수익 또는 미측정", text: s?.crossCoin && s.crossCoin.total ? `${s.crossCoin.profitable}/${s.crossCoin.total} 코인 수익` : "미측정"},
    {id: "active", name: "모의투자 운용 중", ok: s?.status === "active", value: s?.status || "-", need: "운용 중", text: s?.status === "active" ? "운용 중" : (s?.retiredWhy || "중지")}
  ];
  return {eligible: checks.every(c => c.ok), checks};
}

// 전략을 실거래에 연결/해제. 연결은 관문을 통과한 전략만.
export async function linkStrategy(id, on, opts = {}){
  const L = cfg(), book = await bookOf(), s = book?.strategies?.find(x => x.id === id);
  if (on){
    if (!s) throw new LiveError("NO_STRATEGY", "모의투자 장부에 없는 전략입니다");
    if (!SUPPORTED[s.exchange]) throw new LiveError("UNSUPPORTED", `${s.exchange} 전략은 실거래를 지원하지 않습니다 (바이낸스 선물·업비트만)`);
    const g = gateFor(s);
    if (!g.eligible) throw new LiveError("GATE", "승격 관문 미통과: " + g.checks.filter(c => !c.ok).map(c => `${c.name} ${c.text} (필요 ${c.need})`).join(", "), {gate: g});
    const notional = opts.notional != null ? num(opts.notional, 1, 1e9, null) : null;
    L.linked[id] = {on: true, t: D.now(), name: s.name, market: s.market, exchange: s.exchange, ...(notional ? {notional} : {})};
    save(); log({kind: "config", sid: id, sname: s.name, ex: s.exchange, symbol: s.market, msg: "실거래 연결"});
  } else {
    const had = L.linked[id]; delete L.linked[id]; save();
    log({kind: "config", sid: id, sname: had?.name || s?.name, msg: "실거래 연결 해제 (열린 실거래 포지션은 그대로 — 필요하면 직접 닫거나 긴급 정지)"});
  }
  return L.linked[id] || null;
}

/* ============ 감사 기록 ============ */
const SECRET_RE = /secret|signature|apikey|api_key|access_key|authorization|^key$|token/i;
export function redact(v, depth = 0){
  if (v == null || typeof v !== "object" || depth > 6) return v;
  if (Array.isArray(v)) return v.slice(0, 50).map(x => redact(x, depth + 1));
  const o = {}; for (const [k, x] of Object.entries(v)) if (!SECRET_RE.test(k)) o[k] = redact(x, depth + 1); return o;
}
let lastError = null;
const listeners = new Set();
export const onLiveChange = fn => { listeners.add(fn); return () => listeners.delete(fn); };
function emit(entry){ for (const fn of listeners) try { fn(entry); } catch(e){} }
function log(e){
  const entry = {t: D.now(), env: cfg().env, ...redact(e)};
  if (entry.data !== undefined){ try { const s = JSON.stringify(entry.data); entry.data = s.length > 1500 ? s.slice(0, 1500) + "…" : s; } catch(x){ entry.data = String(entry.data); } }
  const arr = store().get(LOG_KEY, []) || [];
  arr.push(entry); if (arr.length > LOG_MAX) arr.splice(0, arr.length - LOG_MAX);
  store().set(LOG_KEY, arr);
  if (e.kind === "error") lastError = {t: entry.t, msg: entry.msg};
  emit(entry);
  return entry;
}
export const auditLog = (n = LOG_MAX) => (store().get(LOG_KEY, []) || []).slice(-n);
const CSV_COLS = ["t", "kind", "env", "sname", "sid", "ex", "symbol", "side", "qty", "price", "notional", "lev", "status", "msg", "data"];
export function exportCSV(){
  const q = v => { const s = v == null ? "" : String(v); return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const rows = auditLog().map(e => CSV_COLS.map(c => q(c === "t" ? new Date(e.t).toISOString() : e[c])).join(","));
  return "﻿" + ["time,kind,env,strategy,strategy_id,exchange,symbol,side,qty,price,notional,leverage,status,message,data", ...rows].join("\r\n");
}

/* ============ 서명 (WebCrypto) ============ */
const enc = new TextEncoder();
const hexOf = buf => [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
const b64url = bytes => { let s = ""; for (const b of new Uint8Array(bytes)) s += String.fromCharCode(b); return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); };
// WebCrypto(crypto.subtle)는 보안 출처(https · 127.0.0.1 · localhost)에서만 있다
const subtle = () => { const C = D.crypto?.subtle; if (!C) throw new LiveError("NO_CRYPTO", "이 페이지에서는 브라우저 서명 기능(WebCrypto)을 쓸 수 없습니다. https 주소나 GHNano.exe(127.0.0.1)로 여세요"); return C; };
const hmacRaw = async (secret, msg) => { const C = subtle(); const k = await C.importKey("raw", enc.encode(secret), {name: "HMAC", hash: "SHA-256"}, false, ["sign"]); return C.sign("HMAC", k, enc.encode(msg)); };
export const hmacHex = async (secret, msg) => hexOf(await hmacRaw(secret, msg));
export const sha512Hex = async msg => hexOf(await subtle().digest("SHA-512", enc.encode(msg)));
// 쿼리 문자열 (값이 undefined/null이면 뺀다). encode=false는 업비트 query_hash용(인코딩 안 한 원문)
export const toQuery = (p, encode = true) => Object.entries(p || {}).filter(([, v]) => v !== undefined && v !== null).map(([k, v]) => encode ? `${encodeURIComponent(k)}=${encodeURIComponent(v)}` : `${k}=${v}`).join("&");
export async function upbitJwt(access, secret, params, nonce = D.crypto.randomUUID()){
  const payload = {access_key: access, nonce};
  if (params && Object.keys(params).length){ payload.query_hash = await sha512Hex(toQuery(params, false)); payload.query_hash_alg = "SHA512"; }
  const head = b64url(enc.encode(JSON.stringify({alg: "HS256", typ: "JWT"}))), body = b64url(enc.encode(JSON.stringify(payload)));
  return `${head}.${body}.${b64url(await hmacRaw(secret, `${head}.${body}`))}`;
}

/* ============ 수량·가격 반올림 ============ */
export function decimalsOf(step){
  const s = String(step); const m = s.match(/e-(\d+)$/i); if (m) return +m[1];
  const i = s.indexOf("."); return i < 0 ? 0 : s.replace(/0+$/, "").length - i - 1;
}
const fix = (n, step) => +n.toFixed(decimalsOf(step));
export const floorStep = (x, step) => fix(Math.floor(x / step + 1e-9) * step, step);
export const ceilStep = (x, step) => fix(Math.ceil(x / step - 1e-9) * step, step);
export const roundTick = (x, tick) => fix(Math.round(x / tick) * tick, tick);
export const fmtStep = (x, step) => Number(x).toFixed(decimalsOf(step));
// 거래소 규칙(exchangeInfo 한 종목)에서 필요한 값만
export function symbolRules(info, symbol){
  const s = (info?.symbols || []).find(x => x.symbol === symbol);
  if (!s) return null;
  const F = Object.fromEntries((s.filters || []).map(f => [f.filterType, f]));
  const lot = F.MARKET_LOT_SIZE && +F.MARKET_LOT_SIZE.stepSize > 0 ? F.MARKET_LOT_SIZE : F.LOT_SIZE || {};
  return {symbol, status: s.status, step: +lot.stepSize || +(F.LOT_SIZE?.stepSize) || 0.001, minQty: +lot.minQty || 0, maxQty: +lot.maxQty || Infinity,
    tick: +(F.PRICE_FILTER?.tickSize) || 0.01, minNotional: +(F.MIN_NOTIONAL?.notional ?? F.MIN_NOTIONAL?.minNotional ?? 0) || 0};
}
// 목표 금액 → 거래소 단위에 맞춘 수량. 단위를 맞추느라 1회 최대 금액을 넘으면 막는다.
export function sizeOrder({notional, price, rules, maxNotional}){
  if (!(price > 0)) return {ok: false, why: "가격을 알 수 없습니다"};
  if (!rules) return {ok: false, why: "거래소에 없는 종목입니다"};
  if (rules.status && rules.status !== "TRADING") return {ok: false, why: `거래 중이 아닌 종목입니다 (${rules.status})`};
  let qty = floorStep(notional / price, rules.step);
  if (qty < rules.minQty) qty = ceilStep(rules.minQty, rules.step);
  if (qty * price < rules.minNotional) qty = ceilStep(rules.minNotional / price, rules.step);
  const n = qty * price;
  if (!(qty > 0)) return {ok: false, why: "주문 수량이 0입니다"};
  if (qty > rules.maxQty) return {ok: false, why: `최대 수량(${rules.maxQty}) 초과`};
  if (n > maxNotional * (1 + 1e-9)) return {ok: false, why: `거래소 최소 단위(수량 ${fmtStep(qty, rules.step)} ≈ ${n.toFixed(2)} USDT, 최소 금액 ${rules.minNotional})가 1회 최대 금액 ${maxNotional} USDT를 넘습니다`, qty, notional: n};
  return {ok: true, qty, qtyStr: fmtStep(qty, rules.step), notional: n};
}

/* ============ 한도 검사 (순수 함수) ============ */
// o: {ex, env, symbol, side, notional, lev}, st: {limits, halted, openCount, hasSymbolPos, lossToday}
export function checkLimits(o, st){
  const L = st.limits, krw = o.ex === "upbit", reasons = [];
  if (st.halted) reasons.push(`하루 손실 한도 도달로 오늘 신규 진입 정지 (${st.halted})`);
  if (!L.symbols.includes(o.symbol)) reasons.push(`허용 종목이 아닙니다: ${o.symbol} (허용: ${L.symbols.join(", ") || "없음"})`);
  if (krw){
    if (o.env !== "mainnet") reasons.push("업비트는 테스트넷이 없어 실거래(메인넷) 환경에서만 주문합니다");
    if (o.side !== "long") reasons.push("업비트 현물은 롱(매수)만 가능합니다");
    if (o.notional > L.krwMaxNotional) reasons.push(`1회 최대 금액 초과: ${Math.round(o.notional)}원 > ${L.krwMaxNotional}원`);
    if (o.notional < UPBIT_MIN_KRW) reasons.push(`업비트 최소 주문 금액 ${UPBIT_MIN_KRW}원 미만`);
  } else {
    if (o.notional > L.maxNotional * (1 + 1e-9)) reasons.push(`1회 최대 금액 초과: ${(+o.notional).toFixed(2)} > ${L.maxNotional} USDT`);
    if (o.lev > L.maxLeverage) reasons.push(`레버리지 한도 초과: ${o.lev}배 > ${L.maxLeverage}배`);
  }
  // 데이터 신선도: 신호의 근거가 된 봉이 너무 오래됐으면(피드 지연·중단) 실주문을 막는다 — 오래된 값으로 실돈을 넣지 않게
  if (st.dataLagMs != null && st.barMs){
    const maxLag = Math.max(st.barMs * 2, 120000);   // 봉 2개 또는 2분 중 큰 값
    if (st.dataLagMs > maxLag) reasons.push(`시세 데이터가 오래됨(${Math.round(st.dataLagMs / 1000)}초 전) — 피드 지연/중단 의심으로 신규 진입 보류`);
  }
  if (st.hasSymbolPos) reasons.push(`${o.symbol}에 이미 포지션이 있습니다 (한 종목 한 포지션)`);
  if (st.openCount >= L.maxPositions) reasons.push(`동시 포지션 한도: ${st.openCount}/${L.maxPositions}`);
  // 포트폴리오 쏠림 방지: 열린 포지션 총 명목가 + 이번 주문이 총 노출 한도를 넘으면 막는다 (코인은 대부분 같이 움직임)
  if (!krw && st.openNotional != null){
    const cap = L.maxTotalNotional ?? (L.maxNotional * L.maxPositions);
    if (st.openNotional + o.notional > cap * (1 + 1e-9)) reasons.push(`총 노출(쏠림) 한도 초과: 열린 ${(+st.openNotional).toFixed(0)} + 이번 ${(+o.notional).toFixed(0)} > ${cap} USDT`);
  }
  return {ok: !reasons.length, reasons};
}

/* ============ 하루 손익 · 자동 정지 ============ */
const today = () => new Date(D.now()).toLocaleDateString("sv-SE");
const dayStart = () => { const d = new Date(D.now()); d.setHours(0, 0, 0, 0); return d.getTime(); };
function dayRec(){
  let d = store().get(DAY_KEY, null);
  if (!d || d.day !== today()){ d = {day: today(), usdt: 0, krw: 0, exUsdt: null}; store().set(DAY_KEY, d); }
  return d;
}
const addDay = (k, v) => { const d = dayRec(); d[k] = (d[k] || 0) + v; store().set(DAY_KEY, d); return d; };
export function isHalted(){ const h = cfg().halted; return !!(h && h.day === today()); }
// 오늘 실현 손익 (로컬 추적과 거래소 기록 중 더 나쁜 값)
export function dayPnl(){ const d = dayRec(); return {day: d.day, usdt: d.exUsdt == null ? d.usdt : Math.min(d.usdt, d.exUsdt), krw: d.krw, local: d.usdt, exchange: d.exUsdt}; }
function checkHalt(){
  const L = cfg(), p = dayPnl();
  if (isHalted()) return L.halted.why;
  let why = null;
  if (-p.usdt >= L.limits.dailyLoss) why = `오늘 실현 손실 ${(-p.usdt).toFixed(2)} USDT ≥ 한도 ${L.limits.dailyLoss} USDT`;
  else if (-p.krw >= L.limits.krwDailyLoss) why = `오늘 업비트 실현 손실 ${Math.round(-p.krw)}원 ≥ 한도 ${L.limits.krwDailyLoss}원`;
  if (why){ L.halted = {day: today(), why, t: D.now()}; save(); log({kind: "halt", msg: "자동 정지: " + why + " — 오늘은 새 진입을 하지 않습니다 (청산은 계속)"}); }
  return why;
}
async function refreshDaily(env){
  if (!hasBnKey(env)) return;
  try {
    const rows = await bnSigned(env, "GET", "/fapi/v1/income", {startTime: dayStart(), limit: 1000});
    const sum = (rows || []).filter(r => ["REALIZED_PNL", "COMMISSION", "FUNDING_FEE"].includes(r.incomeType) && (r.asset || "USDT") === "USDT").reduce((a, r) => a + (+r.income || 0), 0);
    const d = dayRec(); d.exUsdt = sum; store().set(DAY_KEY, d);
  } catch(e){ log({kind: "warn", msg: "오늘 손익(거래소 기록)을 못 읽음: " + e.message}); }
}

/* ============ 바이낸스 USDT-M 선물 ============ */
let timeOffset = {}, rulesCache = {}, dualChecked = {};
const bnName = env => env === "mainnet" ? "binancef" : "binancef_test";
const bnBase = env => D.launcher() ? `/__nuri/proxy/${bnName(env)}` : HOSTS[bnName(env)];
const bnKey = env => (cfg().keys || {})[bnName(env)];
const hasBnKey = env => { const k = bnKey(env); return !!(k?.key && k?.secret); };
const BN_HINT = {"-2015": "키·IP 제한·선물 권한을 확인하세요", "-2014": "API 키 형식이 틀렸습니다", "-1022": "서명이 맞지 않습니다(비밀키 확인)", "-2019": "증거금이 부족합니다",
  "-4164": "최소 주문 금액 미달", "-2021": "손절/익절 가격이 이미 지나 즉시 체결될 가격입니다", "-4061": "포지션 모드(단방향/양방향)가 맞지 않습니다", "-1021": "PC 시계가 거래소와 맞지 않습니다"};
function bnErr(status, j, path){
  const code = j && typeof j.code === "number" ? j.code : null;
  const msg = `바이낸스 오류 ${code ?? status}${j?.msg ? ": " + j.msg : ""}${code != null && BN_HINT[code] ? ` (${BN_HINT[code]})` : ""}`;
  return new LiveError(code ?? status, msg, {status, path});
}
async function readJson(r){ try { return await r.json(); } catch(e){ return null; } }
async function bnPublic(env, path){
  let r; try { r = await D.fetch(bnBase(env) + path, {headers: {accept: "application/json"}}); }
  catch(e){ throw new LiveError("NET", `바이낸스${env === "mainnet" ? "" : " 테스트넷"}에 연결하지 못했습니다${D.launcher() ? "" : " (웹 버전은 브라우저 보안정책으로 막힐 수 있습니다 — GHNano.exe로 실행하세요)"}`); }
  const j = await readJson(r);
  if (!r.ok) throw bnErr(r.status, j, path);
  return j;
}
export async function syncTime(env = cfg().env){
  const t0 = D.now(), j = await bnPublic(env, "/fapi/v1/time"), t1 = D.now();
  timeOffset[env] = Math.round(+j.serverTime - (t0 + t1) / 2);
  log({kind: "info", msg: `거래소 시간에 맞춤 (차이 ${timeOffset[env]}ms)`});
  return timeOffset[env];
}
// 서명 요청: 쿼리 문자열(timestamp·recvWindow 포함)을 HMAC-SHA256으로 서명. 모든 값은 쿼리로 보낸다.
async function bnSigned(env, method, path, params = {}, retried = false){
  const k = bnKey(env);
  if (!k?.key || !k?.secret) throw new LiveError("NO_KEY", `${env === "mainnet" ? "실거래" : "테스트넷"} 바이낸스 API 키가 없습니다`);
  const qs = toQuery({...params, recvWindow: 5000, timestamp: Math.round(D.now() + (timeOffset[env] || 0))});
  const sig = await hmacHex(k.secret, qs);
  let r;
  try { r = await D.fetch(`${bnBase(env)}${path}?${qs}&signature=${sig}`, {method, headers: {"X-MBX-APIKEY": k.key, accept: "application/json"}}); }
  catch(e){ throw new LiveError("NET", `바이낸스에 연결하지 못했습니다${D.launcher() ? "" : " (웹 버전은 GHNano.exe로 실행해야 할 수 있습니다)"}`); }
  const j = await readJson(r);
  if (!r.ok || (j && typeof j.code === "number" && j.code < 0)){
    if (j?.code === -1021 && !retried){ await syncTime(env); return bnSigned(env, method, path, params, true); }
    throw bnErr(r.status, j, path);
  }
  return j;
}
async function rulesFor(env, symbol){
  const c = rulesCache[env];
  if (!c || D.now() - c.t > 6 * 3600e3) rulesCache[env] = {t: D.now(), info: await bnPublic(env, "/fapi/v1/exchangeInfo")};
  return symbolRules(rulesCache[env].info, symbol);
}
const markPrice = async (env, symbol) => +(await bnPublic(env, "/fapi/v1/premiumIndex?symbol=" + encodeURIComponent(symbol))).markPrice;
async function bnPositions(env){
  const rows = await bnSigned(env, "GET", "/fapi/v2/positionRisk");
  return (rows || []).filter(p => +p.positionAmt !== 0);
}
async function ensureOneWay(env){
  if (dualChecked[env]) return;
  const j = await bnSigned(env, "GET", "/fapi/v1/positionSide/dual");
  if (j?.dualSidePosition === true || j?.dualSidePosition === "true") throw new LiveError("HEDGE", "계정이 양방향(Hedge) 포지션 모드입니다. 바이낸스 선물 설정에서 단방향(One-way) 모드로 바꾼 뒤 다시 시도하세요");
  dualChecked[env] = true;
}
const opp = side => side === "long" ? "SELL" : "BUY";
const cid = () => "nuri_" + D.now().toString(36) + Math.random().toString(36).slice(2, 7);
async function bnMarketClose(env, symbol, side, qtyStr){
  return bnSigned(env, "POST", "/fapi/v1/order", {symbol, side: opp(side), type: "MARKET", quantity: qtyStr, reduceOnly: "true", newOrderRespType: "RESULT", newClientOrderId: cid()});
}
// 손절·익절: 거래소에 걸어 두는 조건부 주문 (closePosition). 일반 주문 경로가 막혀 있으면 Algo 주문 경로로 다시 시도.
async function bnProtect(env, symbol, side, type, stopPrice){
  const p = {symbol, side: opp(side), type, stopPrice, closePosition: "true", workingType: "MARK_PRICE", priceProtect: "true", newClientOrderId: cid()};
  try { return await bnSigned(env, "POST", "/fapi/v1/order", p); }
  catch(e){
    if (e.code !== -4120 && !/algo/i.test(e.message)) throw e;
    const {stopPrice: tp, newClientOrderId, ...rest} = p;
    return bnSigned(env, "POST", "/fapi/v1/algoOrder", {...rest, algoType: "CONDITIONAL", triggerPrice: tp, clientAlgoId: newClientOrderId});
  }
}
async function bnCancelAll(env, symbol){
  const out = await bnSigned(env, "DELETE", "/fapi/v1/allOpenOrders", {symbol});
  try { await bnSigned(env, "DELETE", "/fapi/v1/algoOpenOrders", {symbol}); } catch(e){}   // Algo 조건부 주문 (없으면 무시)
  return out;
}

/* ============ 업비트 KRW 현물 (메인넷 전용, 롱만) ============ */
const upBase = () => D.launcher() ? "/__nuri/proxy/upbit" : HOSTS.upbit;
const upKey = () => (cfg().keys || {}).upbit;
const hasUpKey = () => { const k = upKey(); return !!(k?.access && k?.secret); };
async function upReq(method, path, params = {}){
  const k = upKey(); if (!k?.access || !k?.secret) throw new LiveError("NO_KEY", "업비트 API 키가 없습니다");
  const token = await upbitJwt(k.access, k.secret, params);
  const has = Object.keys(params).length, opts = {method, headers: {authorization: "Bearer " + token, accept: "application/json"}};
  let url = upBase() + path;
  if (method === "GET" || method === "DELETE"){ if (has) url += "?" + toQuery(params); }
  else { opts.headers["content-type"] = "application/json; charset=utf-8"; opts.body = JSON.stringify(params); }
  let r; try { r = await D.fetch(url, opts); } catch(e){ throw new LiveError("NET", "업비트에 연결하지 못했습니다" + (D.launcher() ? "" : " (GHNano.exe로 실행하세요)")); }
  const j = await readJson(r);
  if (!r.ok) throw new LiveError(j?.error?.name || r.status, `업비트 오류 ${r.status}${j?.error?.message ? ": " + j.error.message : ""}`, {status: r.status});
  return j;
}
const upPrice = async market => { const r = await D.fetch(upBase() + "/ticker?markets=" + encodeURIComponent(market), {headers: {accept: "application/json"}}); const j = await readJson(r); if (!r.ok || !j?.[0]) throw new LiveError("PRICE", "업비트 시세를 못 읽음"); return +j[0].trade_price; };

/* ============ 승인 ============ */
let approver = null;
// fn(preview, {signal, ms}) → Promise<boolean>. signal은 60초가 지나면 abort된다(창 닫기용).
export function setApprover(fn){ approver = typeof fn === "function" ? fn : null; }
async function requestApproval(preview){
  if (!approver) return "no_approver";
  const ac = new AbortController(); let timer;
  const timeout = new Promise(res => { timer = setTimeout(() => res("timeout"), D.approvalMs); });
  let r;
  try { r = await Promise.race([Promise.resolve().then(() => approver(preview, {signal: ac.signal, ms: D.approvalMs})).then(v => v === true ? "approved" : "rejected"), timeout]); }
  catch(e){ r = "rejected"; }
  finally { clearTimeout(timer); }
  if (r === "timeout") ac.abort();
  return r;
}
const APPROVAL_KO = {approved: "승인", rejected: "거절", timeout: "60초 시간 초과로 자동 취소", no_approver: "승인 창이 없어 주문하지 않음 (실거래 화면을 연 적이 없음)"};
async function gate(preview){
  const L = cfg();
  if (L.mode === "auto"){ log({kind: "approval", ...pv(preview), status: "auto", msg: "자동 모드: 한도 통과 → 승인 없이 실행"}); return true; }
  const r = await requestApproval(preview);
  log({kind: "approval", ...pv(preview), status: r, msg: APPROVAL_KO[r]});
  if (r !== "approved") return false;
  if (!cfg().enabled){ log({kind: "block", ...pv(preview), msg: "승인 대기 중 실거래가 꺼져 주문하지 않음"}); return false; }
  return true;
}
const pv = p => ({sid: p.sid, sname: p.strategy, ex: p.ex, symbol: p.symbol, side: p.side, qty: p.qty, price: p.price, notional: p.notional, lev: p.lev});

/* ============ 실거래 포지션 (이 모듈이 연 것) ============ */
const livePos = () => store().get(POS_KEY, {}) || {};
const setPos = (sid, v) => { const m = livePos(); if (v) m[sid] = v; else delete m[sid]; store().set(POS_KEY, m); emit(); };

/* ============ 모의투자 이벤트 → 실거래 ============ */
let chain = Promise.resolve();
// paper.js step()의 onEvent에서 그대로 넘긴다: {kind:"open"|"close", s, pos|trade, why}
// 이벤트는 순서대로 하나씩 처리한다(반대 신호 = 청산 후 진입). 결과 객체를 돌려준다.
export function onPaperEvent(ev){
  const p = chain.then(() => handle(ev)).catch(e => { log({kind: "error", sid: ev?.s?.id, sname: ev?.s?.name, msg: e.message, data: {code: e.code}}); return {ok: false, error: e.message, code: e.code}; });
  chain = p.then(() => {}, () => {});
  return p;
}
async function handle(ev){
  if (!ev || !ev.s || !["open", "close"].includes(ev.kind)) return {ok: false, skipped: "event"};
  const L = cfg();
  if (!L.enabled) return {ok: false, skipped: "disabled"};
  if (!L.linked[ev.s.id]?.on) return {ok: false, skipped: "not_linked"};
  // 이벤트 속 객체를 믿지 않고 장부에서 같은 id의 전략을 다시 찾는다
  const book = await bookOf(), s = book?.strategies?.find(x => x.id === ev.s.id);
  if (!s){ log({kind: "block", sid: ev.s.id, msg: "장부에 없는 전략의 이벤트 → 무시"}); return {ok: false, blocked: true, reasons: ["장부에 없는 전략"]}; }
  if (!SUPPORTED[s.exchange]){ log({kind: "block", sid: s.id, sname: s.name, ex: s.exchange, msg: "지원하지 않는 거래소"}); return {ok: false, blocked: true, reasons: ["지원하지 않는 거래소: " + s.exchange]}; }
  const side = ev.kind === "open" ? ev.pos?.side : ev.trade?.side;
  log({kind: "decision", sid: s.id, sname: s.name, ex: s.exchange, symbol: s.market, side, msg: `모의투자 ${ev.kind === "open" ? "진입" : "청산"} 신호${ev.why ? ": " + ev.why : ev.trade?.reason ? ": " + ev.trade.reason : ""}`});
  if (ev.kind === "open") return s.exchange === "upbit" ? upOpen(s, ev) : bnOpen(s, ev);
  return s.exchange === "upbit" ? upClose(s, ev) : bnClose(s, ev);
}
const blocked = (s, o, reasons) => { log({kind: "block", sid: s.id, sname: s.name, ex: s.exchange, symbol: o.symbol, side: o.side, notional: o.notional, lev: o.lev, msg: "주문 막음: " + reasons.join(" / ")}); return {ok: false, blocked: true, reasons}; };
// 모의 포지션의 손절·익절 거리(%)를 실제 체결가에 똑같이 적용
const distOf = (pos, k) => pos && pos[k] != null && pos.entry ? Math.abs(pos[k] - pos.entry) / pos.entry : null;

async function bnOpen(s, ev){
  const L = cfg(), env = L.env, lim = L.limits, symbol = s.market, side = ev.pos?.side;
  const o = {ex: "binancef", env, symbol, side, lev: Math.max(1, Math.round(+s.spec?.risk?.leverage || 3)), notional: 0};
  if (side !== "long" && side !== "short") return blocked(s, o, ["알 수 없는 방향"]);
  const g = gateFor(s); if (!g.eligible) return blocked(s, o, ["승격 관문 미달(성과 악화): " + g.checks.filter(c => !c.ok).map(c => c.name).join(", ")]);
  if (livePos()[s.id]) return blocked(s, o, ["이 전략의 실거래 포지션이 이미 있습니다"]);
  if (!hasBnKey(env)) return blocked(s, o, ["API 키 없음"]);
  await refreshDaily(env);
  const halted = checkHalt();
  await ensureOneWay(env);
  const [poss, price, rules] = await Promise.all([bnPositions(env), markPrice(env, symbol), rulesFor(env, symbol)]);
  const upCount = Object.values(livePos()).filter(p => p.ex === "upbit").length;
  const sz = sizeOrder({notional: L.linked[s.id]?.notional || lim.orderNotional, price, rules, maxNotional: lim.maxNotional});
  o.notional = sz.notional ?? (L.linked[s.id]?.notional || lim.orderNotional);
  const openNotional = poss.reduce((sum, p) => sum + Math.abs(+p.notional || (+p.positionAmt * +p.markPrice) || 0), 0);
  const barMs = {"1": 60e3, "5": 3e5, "15": 9e5, "60": 36e5, "240": 144e5, "D": 864e5, "W": 6048e5}[String(s.tf)] || null;
  const dataLagMs = ev.pos?.t ? D.now() - ev.pos.t : null;
  const chk = checkLimits(o, {limits: lim, halted, openCount: poss.length + upCount, hasSymbolPos: poss.some(p => p.symbol === symbol), openNotional, dataLagMs, barMs});
  const reasons = [...(sz.ok ? [] : [sz.why]), ...chk.reasons];
  if (reasons.length) return blocked(s, o, reasons);
  const dir = side === "long" ? 1 : -1, slD = distOf(ev.pos, "sl"), tpD = distOf(ev.pos, "tp");
  const preview = {kind: "open", sid: s.id, strategy: s.name, ex: "binancef", exName: SUPPORTED.binancef, env, symbol, side, orderSide: side === "long" ? "BUY" : "SELL",
    qty: sz.qtyStr, price, notional: +sz.notional.toFixed(2), lev: o.lev, margin: +(sz.notional / o.lev).toFixed(2), marginType: L.marginType,
    sl: slD ? roundTick(price * (1 - dir * slD), rules.tick) : null, tp: tpD ? roundTick(price * (1 + dir * tpD), rules.tick) : null,
    why: ev.why || "", warn: slD ? "" : "전략에 손절 규칙이 없어 거래소 손절 주문을 걸지 않습니다", expiresIn: D.approvalMs};
  if (!(await gate(preview))) return {ok: false, rejected: true, preview};
  // 실행
  await bnSigned(env, "POST", "/fapi/v1/leverage", {symbol, leverage: o.lev});
  if (L.marginType){ try { await bnSigned(env, "POST", "/fapi/v1/marginType", {symbol, marginType: L.marginType}); } catch(e){ if (e.code !== -4046) log({kind: "warn", sid: s.id, symbol, msg: "마진 방식 변경 실패(계속 진행): " + e.message}); } }
  log({kind: "order", ...pv(preview), status: "sent", msg: `시장가 ${preview.orderSide} ${preview.qty}`});
  const ord = await bnSigned(env, "POST", "/fapi/v1/order", {symbol, side: preview.orderSide, type: "MARKET", quantity: sz.qtyStr, newOrderRespType: "RESULT", newClientOrderId: cid()});
  const fill = +ord?.avgPrice > 0 ? +ord.avgPrice : price, qty = +ord?.executedQty > 0 ? +ord.executedQty : sz.qty;
  log({kind: "response", ...pv(preview), qty, price: fill, status: ord?.status, msg: `체결 ${ord?.status || ""} 평균가 ${fill}`, data: {orderId: ord?.orderId, status: ord?.status, avgPrice: ord?.avgPrice, executedQty: ord?.executedQty}});
  addDay("usdt", -qty * fill * FEE);
  const rec = {ex: "binancef", env, symbol, side, qty, qtyStr: fmtStep(qty, rules.step), entry: fill, lev: o.lev, t: D.now(), name: s.name};
  setPos(s.id, rec);
  const out = {ok: true, order: ord, preview};
  // 거래소 손절: 실패하면 위험하므로 즉시 청산한다
  if (slD){
    const sl = roundTick(fill * (1 - dir * slD), rules.tick);
    try { const r = await bnProtect(env, symbol, side, "STOP_MARKET", sl); rec.sl = sl; log({kind: "response", sid: s.id, sname: s.name, ex: "binancef", symbol, side, price: sl, status: "sl", msg: "손절 주문 걸림 " + sl, data: {orderId: r?.orderId ?? r?.algoId}}); }
    catch(e){
      log({kind: "error", sid: s.id, sname: s.name, ex: "binancef", symbol, msg: "손절 주문 실패 → 안전을 위해 즉시 청산: " + e.message});
      try { await bnMarketClose(env, symbol, side, rec.qtyStr); setPos(s.id, null); log({kind: "response", sid: s.id, symbol, status: "closed", msg: "비상 청산 완료"}); }
      catch(e2){ log({kind: "error", sid: s.id, symbol, msg: "비상 청산도 실패 — 거래소에서 직접 확인하세요: " + e2.message}); }
      return {ok: false, error: "손절 주문 실패로 비상 청산", order: ord};
    }
  }
  if (tpD){
    const tp = roundTick(fill * (1 + dir * tpD), rules.tick);
    try { const r = await bnProtect(env, symbol, side, "TAKE_PROFIT_MARKET", tp); rec.tp = tp; log({kind: "response", sid: s.id, sname: s.name, ex: "binancef", symbol, side, price: tp, status: "tp", msg: "익절 주문 걸림 " + tp, data: {orderId: r?.orderId ?? r?.algoId}}); }
    catch(e){ log({kind: "warn", sid: s.id, symbol, msg: "익절 주문 실패(청산 신호로 닫음): " + e.message}); }
  }
  setPos(s.id, rec);
  return {...out, sl: rec.sl ?? null, tp: rec.tp ?? null};
}

async function bnClose(s, ev){
  const lp = livePos()[s.id];
  if (!lp || lp.ex !== "binancef"){ log({kind: "info", sid: s.id, sname: s.name, msg: "이 전략의 실거래 포지션이 없어 할 일 없음"}); return {ok: true, skipped: "no_live_position"}; }
  const env = lp.env, symbol = lp.symbol;
  const p = (await bnPositions(env)).find(x => x.symbol === symbol);
  const amt = p ? +p.positionAmt : 0;
  if (!amt || (amt > 0 ? "long" : "short") !== lp.side){
    try { await bnCancelAll(env, symbol); } catch(e){ log({kind: "warn", symbol, msg: "남은 주문 취소 실패: " + e.message}); }
    setPos(s.id, null); await refreshDaily(env); checkHalt();
    log({kind: "info", sid: s.id, sname: s.name, symbol, msg: amt ? "거래소 포지션 방향이 달라 건드리지 않음(추적만 해제)" : "거래소에서 이미 청산됨(손절·익절 체결) → 남은 주문 정리"});
    return {ok: true, already: true};
  }
  const rules = await rulesFor(env, symbol);
  const qty = Math.min(Math.abs(amt), lp.qty), qtyStr = fmtStep(floorStep(qty, rules?.step || 0.001), rules?.step || 0.001), mark = +p.markPrice || lp.entry;
  const preview = {kind: "close", sid: s.id, strategy: s.name, ex: "binancef", exName: SUPPORTED.binancef, env, symbol, side: lp.side, orderSide: opp(lp.side),
    qty: qtyStr, price: mark, notional: +(qty * mark).toFixed(2), lev: lp.lev, upnl: +p.unRealizedProfit, why: ev.trade?.reason || ev.why || "청산 신호", reduceOnly: true, expiresIn: D.approvalMs};
  if (!(await gate(preview))){ log({kind: "info", sid: s.id, symbol, msg: "청산하지 않음 — 거래소 손절·익절 주문은 그대로 유지"}); return {ok: false, rejected: true, preview}; }
  log({kind: "order", ...pv(preview), status: "sent", msg: `시장가 청산 ${preview.orderSide} ${qtyStr} (reduce-only)`});
  const ord = await bnMarketClose(env, symbol, lp.side, qtyStr);
  const fill = +ord?.avgPrice > 0 ? +ord.avgPrice : mark;
  const realized = (lp.side === "long" ? 1 : -1) * (fill - (+p.entryPrice || lp.entry)) * qty - qty * fill * FEE;
  addDay("usdt", realized);
  log({kind: "response", ...pv(preview), price: fill, status: ord?.status, msg: `청산 체결 · 추정 실현손익 ${realized.toFixed(2)} USDT`, data: {orderId: ord?.orderId, status: ord?.status, avgPrice: ord?.avgPrice}});
  if (qty >= Math.abs(amt) - 1e-12){ try { await bnCancelAll(env, symbol); } catch(e){ log({kind: "warn", symbol, msg: "남은 손절·익절 주문 취소 실패: " + e.message}); } }
  setPos(s.id, null);
  await refreshDaily(env); checkHalt();
  return {ok: true, order: ord, realized, preview};
}

async function upOpen(s, ev){
  const L = cfg(), lim = L.limits, market = s.market, side = ev.pos?.side;
  const krw = Math.round(L.linked[s.id]?.notional || lim.krwOrderNotional);
  const o = {ex: "upbit", env: L.env, symbol: market, side, notional: krw, lev: 1};
  if (livePos()[s.id]) return blocked(s, o, ["이 전략의 실거래 포지션이 이미 있습니다"]);
  const pre = checkLimits(o, {limits: lim, halted: checkHalt(), openCount: Object.keys(livePos()).length, hasSymbolPos: Object.values(livePos()).some(p => p.symbol === market)});
  if (!pre.ok) return blocked(s, o, pre.reasons);
  const g = gateFor(s); if (!g.eligible) return blocked(s, o, ["승격 관문 미달(성과 악화)"]);
  if (!hasUpKey()) return blocked(s, o, ["업비트 API 키 없음"]);
  const price = await upPrice(market);
  const preview = {kind: "open", sid: s.id, strategy: s.name, ex: "upbit", exName: SUPPORTED.upbit, env: L.env, symbol: market, side: "long", orderSide: "BUY",
    qty: (krw / price).toFixed(8), price, notional: krw, quote: "KRW", lev: 1, sl: null, tp: null, why: ev.why || "",
    warn: "업비트는 거래소 손절 주문이 없어, 모의투자 손절·청산 신호가 올 때 시장가로 팝니다", expiresIn: D.approvalMs};
  if (!(await gate(preview))) return {ok: false, rejected: true, preview};
  log({kind: "order", ...pv(preview), status: "sent", msg: `시장가 매수 ${krw}원`});
  const ord = await upReq("POST", "/orders", {market, side: "bid", ord_type: "price", price: String(krw)});
  let vol = null;
  for (let i = 0; i < 3 && ord?.uuid; i++){
    await D.sleep(400);
    try { const st = await upReq("GET", "/order", {uuid: ord.uuid}); if (+st.executed_volume > 0 && st.state !== "wait"){ vol = +st.executed_volume; break; } } catch(e){}
  }
  if (vol == null) vol = +(krw * (1 - UPBIT_FEE) / price).toFixed(8);
  addDay("krw", -krw * UPBIT_FEE);
  setPos(s.id, {ex: "upbit", env: L.env, symbol: market, side: "long", qty: vol, entry: price, krw, t: D.now(), name: s.name, uuid: ord?.uuid});
  log({kind: "response", ...pv(preview), qty: vol, status: ord?.state, msg: `매수 접수 ${ord?.uuid || ""} · 수량 ${vol}`, data: {uuid: ord?.uuid, state: ord?.state}});
  return {ok: true, order: ord, preview};
}

async function upClose(s, ev){
  const lp = livePos()[s.id];
  if (!lp || lp.ex !== "upbit"){ log({kind: "info", sid: s.id, sname: s.name, msg: "이 전략의 실거래 포지션이 없어 할 일 없음"}); return {ok: true, skipped: "no_live_position"}; }
  const cur = lp.symbol.replace(/^KRW-/, "");
  const accts = await upReq("GET", "/accounts");
  const bal = +((accts || []).find(a => a.currency === cur)?.balance || 0);
  const vol = Math.min(bal, lp.qty);              // 이 모듈이 산 만큼만 판다 (원래 갖고 있던 코인은 건드리지 않음)
  if (!(vol > 0)){ setPos(s.id, null); log({kind: "info", sid: s.id, symbol: lp.symbol, msg: "팔 잔고가 없어 추적만 해제"}); return {ok: true, already: true}; }
  const price = await upPrice(lp.symbol);
  const preview = {kind: "close", sid: s.id, strategy: s.name, ex: "upbit", exName: SUPPORTED.upbit, env: lp.env, symbol: lp.symbol, side: "long", orderSide: "SELL",
    qty: vol.toFixed(8), price, notional: Math.round(vol * price), quote: "KRW", lev: 1, why: ev.trade?.reason || ev.why || "청산 신호", expiresIn: D.approvalMs};
  if (!(await gate(preview))) return {ok: false, rejected: true, preview};
  log({kind: "order", ...pv(preview), status: "sent", msg: `시장가 매도 ${preview.qty}`});
  const ord = await upReq("POST", "/orders", {market: lp.symbol, side: "ask", ord_type: "market", volume: preview.qty});
  const realized = (price - lp.entry) * vol - vol * price * UPBIT_FEE;
  addDay("krw", realized); setPos(s.id, null); checkHalt();
  log({kind: "response", ...pv(preview), status: ord?.state, msg: `매도 접수 · 추정 실현손익 ${Math.round(realized)}원`, data: {uuid: ord?.uuid, state: ord?.state}});
  return {ok: true, order: ord, realized, preview};
}

/* ============ 계좌 · 포지션 · 긴급 정지 · 상태 ============ */
export async function account(){
  const L = cfg(), env = L.env, out = {env, binance: null, upbit: null};
  if (hasBnKey(env)){
    try {
      const rows = await bnSigned(env, "GET", "/fapi/v2/balance"), u = (rows || []).find(r => r.asset === "USDT") || {};
      out.binance = {asset: "USDT", balance: +u.balance || 0, available: +u.availableBalance || 0, unrealized: +u.crossUnPnl || 0};
    } catch(e){ out.binance = {error: e.message}; }
  }
  if (env === "mainnet" && hasUpKey()){
    try { out.upbit = (await upReq("GET", "/accounts")).map(a => ({currency: a.currency, balance: +a.balance, locked: +a.locked, avg: +a.avg_buy_price})); }
    catch(e){ out.upbit = {error: e.message}; }
  }
  return out;
}
export async function positions(){
  const L = cfg(), env = L.env, lp = livePos(), owner = sym => Object.entries(lp).find(([, p]) => p.symbol === sym && p.ex === "binancef");
  const out = [];
  if (hasBnKey(env)){
    for (const p of await bnPositions(env)){
      const o = owner(p.symbol);
      out.push({ex: "binancef", symbol: p.symbol, side: +p.positionAmt > 0 ? "long" : "short", qty: Math.abs(+p.positionAmt), entry: +p.entryPrice, mark: +p.markPrice,
        upnl: +p.unRealizedProfit, lev: +p.leverage, liq: +p.liquidationPrice, marginType: p.marginType, sid: o?.[0] || null, strategy: o?.[1].name || null});
    }
  }
  for (const [sid, p] of Object.entries(lp)) if (p.ex === "upbit") out.push({ex: "upbit", symbol: p.symbol, side: "long", qty: p.qty, entry: p.entry, sid, strategy: p.name});
  return out;
}
// 모두 정지·청산: 먼저 끄고(새 주문 차단) → 미체결 취소 → 포지션 시장가 reduce-only 청산. 승인 없이 바로 실행.
export async function killSwitch(){
  const L = cfg(), env = L.env, res = {ok: true, cancelled: [], closed: [], errors: []};
  L.enabled = false; L.mode = "approve"; save();
  log({kind: "kill", msg: "긴급 정지: 실거래를 끄고 미체결 취소·포지션 청산을 시작합니다"});
  const err = (where, e) => { res.errors.push(`${where}: ${e.message}`); log({kind: "error", msg: `긴급 정지 중 오류 (${where}): ${e.message}`}); };
  if (hasBnKey(env)){
    let poss = [], orders = [];
    try { poss = await bnPositions(env); } catch(e){ err("포지션 조회", e); }
    try { orders = await bnSigned(env, "GET", "/fapi/v1/openOrders") || []; } catch(e){ err("주문 조회", e); }
    const syms = [...new Set([...orders.map(o => o.symbol), ...poss.map(p => p.symbol), ...Object.values(livePos()).filter(p => p.ex === "binancef").map(p => p.symbol)])];
    for (const sym of syms){ try { await bnCancelAll(env, sym); res.cancelled.push(sym); log({kind: "response", symbol: sym, status: "cancelled", msg: "미체결 주문 모두 취소"}); } catch(e){ err("취소 " + sym, e); } }
    for (const p of poss){
      const side = +p.positionAmt > 0 ? "long" : "short", qtyStr = String(p.positionAmt).replace("-", "");
      try { const o = await bnMarketClose(env, p.symbol, side, qtyStr); res.closed.push({symbol: p.symbol, side, qty: qtyStr}); log({kind: "response", ex: "binancef", symbol: p.symbol, side, qty: qtyStr, status: o?.status, msg: "긴급 청산 (reduce-only 시장가)"}); }
      catch(e){ err("청산 " + p.symbol, e); }
    }
    for (const [sid, p] of Object.entries(livePos())) if (p.ex === "binancef" && !res.errors.some(x => x.includes(p.symbol))) setPos(sid, null);
  }
  const ups = Object.entries(livePos()).filter(([, p]) => p.ex === "upbit");
  if (ups.length && hasUpKey()){
    let accts = [];
    try { accts = await upReq("GET", "/accounts"); } catch(e){ err("업비트 잔고", e); }
    for (const [sid, p] of ups){
      try {
        if (p.uuid){ try { await upReq("DELETE", "/order", {uuid: p.uuid}); } catch(e){} }   // 이미 체결된 주문이면 실패 = 정상
        const vol = Math.min(+((accts || []).find(a => a.currency === p.symbol.replace(/^KRW-/, ""))?.balance || 0), p.qty);
        if (vol > 0){ await upReq("POST", "/orders", {market: p.symbol, side: "ask", ord_type: "market", volume: vol.toFixed(8)}); res.closed.push({symbol: p.symbol, side: "long", qty: vol}); log({kind: "response", ex: "upbit", symbol: p.symbol, qty: vol, msg: "긴급 매도 (이 모듈이 산 수량만)"}); }
        setPos(sid, null);
      } catch(e){ err("업비트 " + p.symbol, e); }
    }
  }
  res.ok = !res.errors.length;
  log({kind: "kill", status: res.ok ? "done" : "partial", msg: `긴급 정지 완료: 취소 ${res.cancelled.length}개 종목 · 청산 ${res.closed.length}건${res.errors.length ? ` · 오류 ${res.errors.length}건 (거래소에서 직접 확인하세요)` : ""}`});
  return res;
}
export function status(){
  const L = cfg(), k = L.keys || {};
  return {enabled: L.enabled, env: L.env, mode: L.mode, halted: isHalted() ? L.halted : null, day: dayPnl(), linked: Object.values(L.linked).filter(x => x?.on).length,
    livePositions: livePos(), keys: {binancef_test: hasBnKey("testnet"), binancef: hasBnKey("mainnet"), upbit: hasUpKey()}, approver: !!approver, launcher: !!D.launcher(),
    base: bnBase(L.env), lastError};
}
