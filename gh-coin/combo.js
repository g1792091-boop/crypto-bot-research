// 실시간 종합 지표 타점팀 엔진: 차트 터미널(terminal/ind.js)의 모든 보조지표를 한꺼번에 계산해
// ① 지표마다 상승·하락·중립 표를 던지고 ② 시간대(5분·15분·1시간·4시간)별 점수를 내고 ③ 큰 추세 + 작은 타이밍이 맞을 때 타점(진입·손절·익절)을 잡는다.
// 숫자는 전부 코드가 계산한다(AI 없음). 실제 주문은 하지 않는다 — 타점은 '기록장'에 남겨 적중률을 스스로 검증한다.
import { INDICATORS } from "../nuri-ai/terminal/ind.js";

// 외부 데이터가 필요한 지표(OI·펀딩·청산 등)는 캔들만으로 계산할 수 없어 뺀다 (흐름 점수로 따로 본다)
const SKIP = new Set(["vp", "session_vp", "oi", "oi_delta", "funding", "long_short", "taker", "liq", "cb_premium", "rs_btc", "corr_btc"]);
// 방향이 아니라 '장세(추세장·횡보장)·변동성'을 알려 주는 지표 → 표 대신 필터로 쓴다
const FILTER = new Set(["atr", "bbw", "chop", "stdev", "hv", "mass", "vix_fix", "ulcer", "rvix", "chaikin_vol", "vhf", "hurst", "fdi", "vol_est", "vol_rank", "skew_kurt", "autocorr", "r2", "volume", "rvol", "vol_osc", "gator"]);
const LEVEL_GROUP = /레벨|프로파일/;
export const TF_LIST = ["5", "15", "60", "240"];
export const TF_NAME = {"5": "5분", "15": "15분", "60": "1시간", "240": "4시간"};

export const comboIds = () => Object.keys(INDICATORS).filter(id => !SKIP.has(id) && !INDICATORS[id].remote);
export const toBars = cs => cs.map(b => ({time: Math.floor(b.t / 1000), open: b.o, high: b.h, low: b.l, close: b.c, volume: b.v}));

const num = v => v != null && Number.isFinite(+v) ? +v : null;
const lastIdx = arr => { for (let i = arr.length - 1; i >= 0; i--) if (num(arr[i]) != null) return i; return -1; };
const sgn = v => v > 0 ? 1 : v < 0 ? -1 : 0;
const SECOND = /시그널|트리거|%D|추적선|신호|평균|EMA|WT2|Down|-DI|VI-/;

// 신호(화살표)형 plot: 가장 최근 신호의 방향과 몇 봉 전인지
function lastSignal(plots, n){
  let best = null;
  for (const pl of plots) if (pl.type === "signals" && Array.isArray(pl.data)){
    for (let i = pl.data.length - 1; i >= Math.max(0, pl.data.length - 30); i--){
      const v = pl.data[i];
      if (v && typeof v === "object" && Number.isFinite(+v.dir) && +v.dir !== 0){ if (!best || i > best.i) best = {i, dir: sgn(+v.dir), text: v.text || ""}; break; }
    }
  }
  return best ? {...best, ago: n - 1 - best.i} : null;
}

// 지표 1개 → 표 {dir: +1 상승 / -1 하락 / 0 중립, w: 무게, tag: 과매수·과매도·새 신호}
export function voteOf(id, d, r, bars){
  const n = bars.length, price = bars[n - 1].close, plots = (r.plots || []).filter(p => Array.isArray(p.data));
  const val = (p, k = 0) => { const i = lastIdx(p.data) - k; return i >= 0 ? num(p.data[i]) : null; };
  const lines = plots.filter(p => p.type === "line" || p.type === "dots" || p.type === "hist");
  const L = Array.isArray(r.levels) ? r.levels.filter(x => Number.isFinite(+x)).map(Number) : [];
  const out = {id, name: d.name.split(" (")[0], group: d.group, dir: 0, w: 1, tag: ""};
  // 특별 규칙 (선 순서만으로는 뜻이 안 나오는 지표)
  const P = k => lines[k] ? val(lines[k]) : null;
  if (id === "adx"){ const a = P(0), pd = P(1), md = P(2); if (pd != null && md != null){ out.dir = sgn(pd - md); out.w = a > 25 ? 1.5 : a > 20 ? 1 : 0.5; } out.adx = a; return out; }
  if (id === "aroon" || id === "vortex" || id === "nvi_pvi"){ const a = P(0), b = P(1); if (a != null && b != null) out.dir = sgn(a - b); return out; }
  if (id === "elder"){ const a = P(0), b = P(1); if (a != null && b != null) out.dir = sgn(a + b); return out; }
  const sig = lastSignal(plots, n);
  let lineDir = 0, has = false;
  if (d.pane === "main"){
    // 가격 위에 겹치는 선들: 선들의 평균보다 가격이 위면 상승, 평균선이 오르고 있으면 더 확실
    const ls = plots.filter(p => p.type === "line" || p.type === "dots");
    const avgAt = k => { const v = ls.map(p => num(p.data[n - 1 - k])).filter(x => x != null); return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null; };
    const a0 = avgAt(0), a5 = avgAt(5);
    if (a0 != null){ has = true; lineDir = sgn(price - a0); if (a5 != null && sgn(a0 - a5) !== lineDir) out.w = 0.6; }
  } else if (lines.length){
    const f = lines[0], v = val(f);
    if (v != null){
      has = true;
      const mid = L.length ? (L.length % 2 ? L[(L.length - 1) / 2] : L.length === 2 ? (L[0] + L[1]) / 2 : 0) : null;
      let d1 = f.type === "hist" ? sgn(v - (L.includes(0) || !L.length ? 0 : mid)) : mid != null ? sgn(v - mid) : sgn(v - (val(f, 10) ?? v));
      const s2 = lines.slice(1).find(p => p.type === "line" && SECOND.test(p.name || "")), v2 = s2 ? val(s2) : null;
      const d2 = v2 != null && f.type !== "hist" ? sgn(v - v2) : 0;
      lineDir = sgn(d1 + d2 * 0.5);
      if (L.length >= 2 && /오실레이터|신호/.test(d.group) && f.type === "line"){ if (v >= Math.max(...L)) out.tag = "과매수"; else if (v <= Math.min(...L)) out.tag = "과매도"; }
    }
  }
  if (sig){
    const fresh = sig.ago <= 5;
    if (!has){ out.dir = sig.ago <= 12 ? sig.dir : 0; out.w = fresh ? 1.5 : 1; }
    else { out.dir = sgn(lineDir + sig.dir * (fresh ? 1.5 : 0.5)); if (fresh) out.w = 1.5; }
    if (fresh) out.tag = (out.tag ? out.tag + " · " : "") + `새 신호 ${sig.dir > 0 ? "▲" : "▼"}${sig.text ? " " + String(sig.text).slice(0, 14) : ""} (${sig.ago}봉 전)`;
  } else out.dir = lineDir;
  return out;
}

// 필터 지표 → 장세 판정 (추세장 / 횡보장, 변동성)
function regimeOf(F){
  let tr = 0, rg = 0; const why = [];
  const vote = (cond, yes, no) => { if (cond == null) return; if (cond){ tr++; why.push(yes); } else { rg++; why.push(no); } };
  if (F.chop != null) vote(F.chop < 50, `초피니스 ${F.chop.toFixed(0)}`, `초피니스 ${F.chop.toFixed(0)}`);
  if (F.hurst != null) vote(F.hurst > 0.5, `허스트 ${F.hurst.toFixed(2)}`, `허스트 ${F.hurst.toFixed(2)}`);
  if (F.vhf != null) vote(F.vhf > 0.35, "VHF 추세", "VHF 횡보");
  if (F.r2 != null) vote(F.r2 > 0.5, `R² ${F.r2.toFixed(2)}`, `R² ${F.r2.toFixed(2)}`);
  if (F.adx != null) vote(F.adx > 22, `ADX ${F.adx.toFixed(0)}`, `ADX ${F.adx.toFixed(0)}`);
  if (F.fdi != null) vote(F.fdi < 1.5, "FDI 추세", "FDI 횡보");
  return {trend: tr > rg, label: tr + rg === 0 ? "?" : tr > rg ? "추세장" : "횡보장", tr, rg, volRank: F.vol_rank, rvol: F.rvol};
}

const tick = () => new Promise(r => { try { const ch = new MessageChannel(); ch.port1.onmessage = () => { ch.port1.close(); r(); }; ch.port2.postMessage(0); } catch (e) { setTimeout(r, 0); } });   // 창이 가려져도 밀리지 않는 양보(setTimeout 0 은 숨은 창에서 1분에 한 번으로 묶임)
// 한 시간대의 모든 지표 계산 → 점수·표·레벨
export async function analyzeTF(cs, {yieldEvery = 24} = {}){
  const bars = toBars(cs), n = bars.length, price = bars[n - 1].close, votes = [], levels = [], F = {};
  let k = 0;
  for (const id of comboIds()){
    const d = INDICATORS[id];
    if (++k % yieldEvery === 0) await tick();    // 화면이 멈추지 않게 틈틈이 쉰다
    let r; try { r = d.compute(bars, {...(d.params || {})}, {}) || {}; } catch(e){ continue; }
    const plots = (r.plots || []).filter(p => Array.isArray(p.data));
    // 레벨형 지표(피봇·피보나치·전일 고저·VWAP 밴드·라운드 넘버…)와 채널 상·하단 → 지지·저항 후보
    if (d.pane === "main" && (LEVEL_GROUP.test(d.group) || /^(bb|keltner|donchian|envelope|structure|nwe|range_filter|chandelier|atr_stop|supertrend)$/.test(id))){
      for (const p of plots) if (p.type === "line"){ const i = lastIdx(p.data); if (i >= n - 3){ const v = num(p.data[i]); if (v > 0 && Math.abs(v / price - 1) < 0.25) levels.push({name: `${d.name.split(" (")[0]} ${p.name || ""}`.trim(), price: v}); } }
      if (LEVEL_GROUP.test(d.group)) continue;
    }
    if (FILTER.has(id)){ const p = plots.find(x => x.type !== "signals"), i = p ? lastIdx(p.data) : -1; if (i >= 0) F[id] = num(p.data[i]); continue; }
    const v = voteOf(id, d, r, bars);
    if (v.adx != null) F.adx = v.adx;
    votes.push(v);
  }
  const act = votes.filter(v => v.dir !== 0), W = votes.reduce((s, v) => s + v.w, 0) || 1;
  const score = votes.reduce((s, v) => s + v.w * v.dir, 0) / W;   // -1 ~ +1
  const osc = votes.filter(v => /오실레이터/.test(v.group));
  const groups = {};
  for (const v of votes){ const g = groups[v.group] ||= {up: 0, dn: 0, flat: 0}; v.dir > 0 ? g.up++ : v.dir < 0 ? g.dn++ : g.flat++; }
  // ATR(14)
  let atr = 0; { const tr = bars.map((b, i) => i ? Math.max(b.high - b.low, Math.abs(b.high - bars[i - 1].close), Math.abs(b.low - bars[i - 1].close)) : b.high - b.low); let a = tr.slice(0, 14).reduce((s, x) => s + x, 0) / 14; for (let i = 14; i < n; i++) a = (a * 13 + tr[i]) / 14; atr = a; }
  // 스윙 고저 (좌우 3봉)
  for (let i = n - 4, c = 0; i >= 3 && c < 8; i--){
    const w = bars.slice(i - 3, i + 4);
    if (bars[i].high === Math.max(...w.map(b => b.high))){ levels.push({name: "스윙 고점", price: bars[i].high}); c++; }
    else if (bars[i].low === Math.min(...w.map(b => b.low))){ levels.push({name: "스윙 저점", price: bars[i].low}); c++; }
  }
  return {price, atr, score, up: act.filter(v => v.dir > 0).length, dn: act.filter(v => v.dir < 0).length, flat: votes.length - act.length, total: votes.length + Object.keys(F).length,
    ob: osc.filter(v => /과매수/.test(v.tag)).length, os: osc.filter(v => /과매도/.test(v.tag)).length, oscN: osc.length,
    fresh: votes.filter(v => /새 신호/.test(v.tag)).map(v => ({name: v.name, dir: v.dir, tag: v.tag})), groups, votes, levels, regime: regimeOf(F), filters: F, t: cs[n - 1].t};
}

export const verdict = s => s >= 0.35 ? "강한 상승" : s >= 0.12 ? "상승" : s <= -0.35 ? "강한 하락" : s <= -0.12 ? "하락" : "횡보";
export const pct = s => (s >= 0 ? "+" : "") + Math.round(s * 100);

// 가까운 레벨끼리 묶어 '여러 지표가 겹치는 가격대'(강한 지지·저항)를 찾는다
export function clusterLevels(levels, price, atr){
  const L = levels.filter(x => x.price > 0).sort((a, b) => a.price - b.price), out = [], tol = Math.max(atr * 0.35, price * 0.0015);
  for (const x of L){ const c = out.at(-1); if (c && x.price - c.hi <= tol){ c.items.push(x); c.hi = x.price; } else out.push({items: [x], lo: x.price, hi: x.price}); }
  return out.map(c => ({price: c.items.reduce((s, x) => s + x.price, 0) / c.items.length, n: c.items.length, names: [...new Set(c.items.map(x => x.name))].slice(0, 4)}));
}

// 시간대 점수들 → 큰 추세 · 타이밍 · 타점
export function planOf(tf){
  const s = k => tf[k]?.score ?? 0, base = tf["15"] || tf["5"] || tf["60"];
  const big = 0.6 * s("240") + 0.4 * s("60"), small = 0.6 * s("15") + 0.4 * s("5");
  const price = (tf["5"] || base).price, atr = base.atr || price * 0.004;
  const cl = clusterLevels([...(tf["15"]?.levels || []), ...(tf["60"]?.levels || []), ...(tf["240"]?.levels || [])], price, atr);
  const below = cl.filter(c => c.price < price - atr * 0.15).sort((a, b) => b.price - a.price), above = cl.filter(c => c.price > price + atr * 0.15).sort((a, b) => a.price - b.price);
  // 가까운 것 중 '겹침'이 많은 레벨을 우선 (3개 안에서)
  const pick = arr => arr.slice(0, 3).sort((a, b) => b.n - a.n || 0)[0] || null;
  const sup = pick(below), res = pick(above);
  const b15 = tf["15"] || base, obR = b15.oscN ? b15.ob / b15.oscN : 0, osR = b15.oscN ? b15.os / b15.oscN : 0;
  const agreeUp = TF_LIST.filter(k => tf[k] && tf[k].score > 0.05).length, agreeDn = TF_LIST.filter(k => tf[k] && tf[k].score < -0.05).length;
  const regime = (tf["60"] || base).regime;
  let state = "wait", side = 0, why = "";
  if (big >= 0.12 && small >= 0.2 && obR < 0.5){ state = "long"; side = 1; why = "큰 추세 상승 + 작은 봉 타이밍 상승"; }
  else if (big <= -0.12 && small <= -0.2 && osR < 0.5){ state = "short"; side = -1; why = "큰 추세 하락 + 작은 봉 타이밍 하락"; }
  else if (big >= 0.12){ state = "longWait"; side = 1; why = small < 0.2 ? "큰 추세는 상승, 작은 봉은 아직 눌림 — 지지에서 반등 확인 대기" : "상승이지만 오실레이터 과열 — 눌림 대기"; }
  else if (big <= -0.12){ state = "shortWait"; side = -1; why = small > -0.2 ? "큰 추세는 하락, 작은 봉은 반등 중 — 저항에서 꺾임 확인 대기" : "하락이지만 과매도 — 반등 후 대기"; }
  else if (!regime.trend && osR >= 0.4 && sup && price - sup.price < atr * 0.8){ state = "long"; side = 1; why = "횡보장 박스 하단 + 오실레이터 과매도"; }
  else if (!regime.trend && obR >= 0.4 && res && res.price - price < atr * 0.8){ state = "short"; side = -1; why = "횡보장 박스 상단 + 오실레이터 과매수"; }
  else why = "큰 추세가 뚜렷하지 않음 — 관망";
  // 진입·손절·익절 (지지·저항 + ATR)
  let entry = null, sl = null, tp1 = null, tp2 = null;
  const clampSL = (e, lvl, dir) => { let d = lvl != null ? Math.abs(e - lvl) + atr * 0.25 : atr * 1.5; d = Math.min(Math.max(d, atr * 0.8), atr * 3); return e - dir * d; };
  if (side){
    const wait = /Wait/.test(state);
    entry = wait ? (side > 0 ? (sup ? sup.price + atr * 0.1 : price - atr) : (res ? res.price - atr * 0.1 : price + atr)) : price;
    const lvlSL = side > 0 ? below.find(c => c.price < entry - atr * 0.2)?.price : above.find(c => c.price > entry + atr * 0.2)?.price;
    sl = clampSL(entry, lvlSL ?? null, side);
    const R = Math.abs(entry - sl);
    tp1 = entry + side * R * 1.5;
    const tgt = (side > 0 ? above : below).find(c => side > 0 ? c.price > tp1 && c.price <= entry + R * 4 : c.price < tp1 && c.price >= entry - R * 4);
    tp2 = tgt ? tgt.price : entry + side * R * 3;
  }
  const conf = Math.round(Math.min(1, Math.abs(big) * 0.5 + Math.abs(small) * 0.5 + (Math.max(agreeUp, agreeDn) - 2) * 0.08) * 100);
  return {state, side, why, big, small, price, atr, entry, sl, tp1, tp2, rr: entry && sl ? Math.abs(tp2 - entry) / Math.abs(entry - sl) : null,
    sup, res, conf: Math.max(0, conf), agree: side >= 0 ? agreeUp : agreeDn, regime, obR, osR};
}
export const STATE_KO = {long: "🟢 롱 타점", short: "🔴 숏 타점", longWait: "🟡 롱 대기", shortWait: "🟠 숏 대기", wait: "⚪ 관망"};

// 타점 기록장: 잡은 타점이 익절1(성공)·손절(실패)·24시간 만료 중 무엇이 됐는지 코드가 채점한다
export function gradeCall(call, cs){
  if (call.result) return call;
  const after = cs.filter(b => b.t > call.t);
  for (const b of after){
    const hitSL = call.side > 0 ? b.l <= call.sl : b.h >= call.sl, hitTP = call.side > 0 ? b.h >= call.tp1 : b.l <= call.tp1;
    if (hitSL){ return {...call, result: "loss", r: -1, end: b.t}; }      // 같은 봉에 둘 다 닿으면 보수적으로 손절
    if (hitTP){ return {...call, result: "win", r: 1.5, end: b.t}; }
  }
  const last = cs.at(-1);
  if (last && last.t - call.t > 24 * 3600e3){ const r = call.side * (last.c - call.entry) / Math.abs(call.entry - call.sl); return {...call, result: "expire", r: Math.round(r * 100) / 100, end: last.t}; }
  return call;
}
export function callStats(calls){
  const done = calls.filter(c => c.result), win = done.filter(c => (c.r || 0) > 0).length;   // 수익으로 끝난 것 = 적중
  return {n: calls.length, open: calls.length - done.length, done: done.length, win, rate: done.length ? win / done.length : null, sumR: Math.round(done.reduce((s, c) => s + (c.r || 0), 0) * 100) / 100};
}
