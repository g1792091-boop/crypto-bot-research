// 모의투자: 사무실 팀이 검증(앞 70% 개발 · 뒤 30% 검증)을 통과시킨 전략을 실제 시세로 가상 운용한다.
// 주문은 내지 않는다. 가상 계좌(전략마다 10,000 USDT)에서 신호·손절·익절·청산을 코드가 계산해 기록한다.
import { idb, uid } from "./engine.js";
import { candlesFor } from "./agent.js";

let KEY = "paper:book", MAX_ACTIVE = 8;
const START = 10000;
let BOOK = null;
// 다른 앱(GH Coin)은 자기 장부를 따로 쓴다: setBookKey("coin:paper", 16)
export function setBookKey(key, maxActive){ if (key && key !== KEY){ KEY = key; BOOK = null; } if (maxActive) MAX_ACTIVE = maxActive; }
export async function loadBook(){
  if (!BOOK){ const v = await idb.all(KEY).catch(() => []); BOOK = v[0] && v[0].strategies ? v[0] : {strategies: [], updated: 0}; }
  return BOOK;
}
const save = () => idb.put(KEY, BOOK);
export const TFS = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"};
const tfOf = iv => TFS[iv] || (Object.values(TFS).includes(String(iv)) ? String(iv) : "60");

// 새 전략을 모의투자에 올린다 (활성 전략이 많으면 성과가 가장 나쁜 것을 내린다)
export async function addStrategy({spec, market, exchange = "binancef", tf, author = "", wf = null, cls = "crypto", mname = "", lane = "", robust = null, crossCoin = null}){
  await loadBook();
  const s = {id: uid(), name: spec.name || "이름 없는 전략", spec, market: market || spec.symbol || "BTCUSDT", mname: mname || market, cls, exchange, tf: tfOf(tf || spec.interval), author, wf, lane, robust, crossCoin,
    status: "active", created: Date.now(), cash: START, pos: null, trades: [], equity: [{t: Date.now(), v: START}], lastBar: 0, lastSignal: null};
  BOOK.strategies.push(s);
  const active = BOOK.strategies.filter(x => x.status === "active");
  if (active.length > MAX_ACTIVE){
    const worst = active.filter(x => x.id !== s.id).sort((a, b) => equityOf(a) - equityOf(b))[0];
    if (worst){ worst.status = "retired"; worst.retiredWhy = "새 전략에 자리를 내줌(성과 최하위)"; }
  }
  await save();
  return s;
}
export async function setStatus(id, status){ await loadBook(); const s = BOOK.strategies.find(x => x.id === id); if (s){ s.status = status; await save(); } }
// 전략 메타(앙상블 비중·이동감지 축소 등) 저장 — 다음 진입 크기에 실제로 반영된다
export async function setMeta(id, patch){ await loadBook(); const s = BOOK.strategies.find(x => x.id === id); if (s){ Object.assign(s, patch); await save(); } return s; }
// 진입 관문 훅: 앱(GH Coin 사무실)이 리스크 결정표·투자위원회·심리·뉴스 판정을 여기 연결한다 → {ok, mul, why}
let GATE = null;
export function setEntryGate(fn){ GATE = typeof fn === "function" ? fn : null; }
const TF_MS = {"1": 60e3, "5": 300e3, "15": 900e3, "60": 3600e3, "240": 14400e3, "D": 86400e3};
export const equityOf = s => s.equity.at(-1)?.v ?? START;

function closePos(s, price, t, reason){
  const p = s.pos; if (!p) return null;
  const dir = p.side === "long" ? 1 : -1;
  const fee = (s.spec.risk?.fee_pct ?? 0.04) / 100 + (s.spec.risk?.slippage_pct ?? 0.01) / 100;
  const pnlPct = dir * (price - p.entry) / p.entry;                       // 가격 기준
  const pnl = p.notional * pnlPct - p.notional * fee * 2;
  const ret = {side: p.side, entryT: p.t, entryP: p.entry, exitT: t, exitP: price, pnl, roe: p.margin ? pnl / p.margin * 100 : 0, lev: p.lev, reason};
  s.cash = Math.max(0, s.cash + pnl); s.trades.push(ret); if (s.trades.length > 200) s.trades.splice(0, s.trades.length - 200);
  s.pos = null;
  return ret;
}
function openPos(s, side, price, t, atr, mul = 1){
  const r = s.spec.risk || {}, lev = Math.max(1, Math.min(200, +r.leverage || 3)), pct = Math.max(1, Math.min(100, +r.position_pct || 20));
  const k = Math.max(0, Math.min(1.5, mul * (s.weightMul ?? 1) * (s.sizeMul ?? 1)));   // 관문·앙상블 비중·이동감지 축소가 실제 크기를 바꾼다
  let margin = s.cash * pct / 100 * k, dir = side === "long" ? 1 : -1;
  // 고정 리스크 상한(nautilus fixedRiskQty): 손절 시 손실이 계좌의 risk_pct(기본 2%)를 넘지 않게 증거금을 줄인다
  const slDist = r.stop_loss_pct ? r.stop_loss_pct / 100 : (r.atr_stop_mult && atr ? atr * r.atr_stop_mult / price : null);
  if (slDist){ const maxLoss = s.cash * (+r.risk_pct || 2) / 100, loss = margin * lev * (slDist + 0.001); if (loss > maxLoss) margin *= maxLoss / loss; }
  const notional = margin * lev;
  const sl = r.stop_loss_pct ? price * (1 - dir * r.stop_loss_pct / 100) : r.atr_stop_mult && atr ? price - dir * atr * r.atr_stop_mult : null;
  const tp = r.take_profit_pct ? price * (1 + dir * r.take_profit_pct / 100) : r.atr_tp_mult && atr ? price + dir * atr * r.atr_tp_mult : null;
  const liq = price * (1 - dir * (1 / lev) * 0.95);
  s.pos = {side, entry: price, t, margin, notional, lev, sl, tp, liq, best: price, trail: r.trailing_stop_pct || null};
  return s.pos;
}
function protect(s, t){
  const P = s.spec.risk?.protections; if (!Array.isArray(P) || !P.length) return;
  const bar = TF_MS[s.tf] || 3600e3, defN = Math.max(1, Math.ceil(3600e3 / bar));
  for (const pr of P){
    const look = (pr.lookback_candles || defN) * bar, stop = (pr.stop_candles || defN) * bar;
    const win = s.trades.filter(x => x.exitT > t - look && x.exitT <= t); if (!win.length) continue;
    const ratio = x => (x.roe || 0) / 100 / (x.lev || 1);
    let hit = false, why = "";
    if (pr.method === "StoplossGuard"){ const n = win.filter(x => /손절|청산/.test(x.reason) && ratio(x) < (pr.required_profit_pct || 0) / 100).length; hit = n >= (pr.trade_limit || 2); why = `손절 ${n}회`; }
    else if (pr.method === "MaxDrawdown"){ if (win.length >= (pr.trade_limit || 3)){ let cum = 0, peak = 0, dd = 0; for (const x of win){ cum += ratio(x); peak = Math.max(peak, cum); dd = Math.max(dd, peak - cum); } hit = dd * 100 > (pr.max_allowed_drawdown_pct || 10); why = `창 안 낙폭 ${(dd * 100).toFixed(1)}%`; } }
    else if (pr.method === "CooldownPeriod"){ hit = true; why = "청산 직후 쉬기"; }
    else if (pr.method === "LowProfitPairs"){ if (win.length >= (pr.trade_limit || 2)){ const sum = win.reduce((a, x) => a + ratio(x), 0); hit = sum < (pr.required_profit_pct || 0) / 100; why = `창 안 수익 ${(sum * 100).toFixed(1)}%`; } }
    if (hit){ const until = Math.max(...win.map(x => x.exitT)) + stop; if (until > (s.lockedUntil || 0)){ s.lockedUntil = until; s.lockWhy = `${pr.method}: ${why}`; } }
  }
}
const atrOf = (cs, n = 14) => { if (cs.length < n + 1) return null; let sum = 0; for (let i = cs.length - n; i < cs.length; i++){ const a = cs[i], b = cs[i - 1]; sum += Math.max(a.h - a.l, Math.abs(a.h - b.c), Math.abs(a.l - b.c)); } return sum / n; };

// 3분마다: 활성 전략마다 최신 캔들 → 손절·익절·청산 확인 → 신호대로 진입·청산 (같은 봉은 한 번만)
export async function step(onEvent){
  await loadBook();
  const Q = await import("./quant.js");
  const active = BOOK.strategies.filter(s => s.status === "active");
  const events = [];
  const cache = {};
  for (const s of active){
    try {
      const key = s.exchange + s.market + s.tf;
      const cs = cache[key] || (cache[key] = (await candlesFor({market: s.market, exchange: s.exchange, timeframe: s.tf}, 400)).cs);
      const last = cs[cs.length - 1], price = last.c;
      // 열린 포지션: 이번 봉 고가·저가로 청산·손절·익절 확인
      if (s.pos){
        const p = s.pos, long = p.side === "long";
        p.best = long ? Math.max(p.best, last.h) : Math.min(p.best, last.l);
        const trailStop = p.trail ? (long ? p.best * (1 - p.trail / 100) : p.best * (1 + p.trail / 100)) : null;
        const hitLiq = long ? last.l <= p.liq : last.h >= p.liq;
        const hitSl = p.sl != null && (long ? last.l <= p.sl : last.h >= p.sl);
        const hitTrail = trailStop != null && (long ? last.l <= trailStop : last.h >= trailStop);
        const hitTp = p.tp != null && (long ? last.h >= p.tp : last.l <= p.tp);
        const r = s.spec.risk || {}, dir = long ? 1 : -1;
        // freqtrade 시간별 목표수익표: 보유 N분 이상이면 증거금 수익(수수료 포함)이 표 값을 넘을 때 익절 — 백테스트와 같은 규칙으로 데모에서도 실제 적용
        let roiPx = null;
        if (r.minimal_roi && typeof r.minimal_roi === "object"){ const age = Math.floor((last.t - p.t) / 60000), ks = Object.keys(r.minimal_roi).map(Number).filter(k => k <= age);
          if (ks.length){ const need = r.minimal_roi[String(Math.max(...ks))] / 100, fees = 2 * ((r.fee_pct ?? 0.04) / 100) * p.lev; roiPx = p.entry * (1 + dir * (need + fees) / p.lev); } }
        const hitRoi = roiPx != null && (long ? last.h >= roiPx : last.l <= roiPx);
        // 수익 오프셋 이후 추적손절(trailing_stop_positive)
        let posTrail = null;
        if (r.trailing_stop_positive_pct && r.trailing_stop_positive_offset_pct && dir * (p.best / p.entry - 1) * 100 >= r.trailing_stop_positive_offset_pct) posTrail = long ? p.best * (1 - r.trailing_stop_positive_pct / 100) : p.best * (1 + r.trailing_stop_positive_pct / 100);
        const hitPosTrail = posTrail != null && (long ? last.l <= posTrail : last.h >= posTrail);
        let ev = null;
        if (hitLiq) ev = closePos(s, p.liq, last.t, "강제청산");
        else if (hitSl) ev = closePos(s, p.sl, last.t, "손절");
        else if (hitTrail) ev = closePos(s, trailStop, last.t, "추적 손절");
        else if (hitTp) ev = closePos(s, p.tp, last.t, "익절");
        else if (hitPosTrail) ev = closePos(s, posTrail, last.t, "수익 추적손절");
        else if (hitRoi) ev = closePos(s, roiPx, last.t, "목표수익(ROI표)");
        if (ev){ events.push({kind: "close", s, trade: ev}); protect(s, last.t); }
      }
      const sig = Q.liveSignal(s.spec, cs, {position: s.pos?.side || null});
      s.lastSignal = sig ? {action: sig.action, why: sig.why, t: Date.now()} : null;
      if (sig && sig.t && sig.t !== s.lastBar){
        s.lastBar = sig.t;
        const want = sig.action;
        if ((want === "exit_long" && s.pos?.side === "long") || (want === "exit_short" && s.pos?.side === "short")){
          const ev = closePos(s, price, last.t, "청산 신호"); if (ev){ events.push({kind: "close", s, trade: ev, why: sig.why}); protect(s, last.t); }
        }
        if (want === "long" || want === "short"){
          if (s.pos && s.pos.side !== want && s.spec.risk?.allow_reverse !== false){ const ev = closePos(s, price, last.t, "반대 신호"); if (ev) events.push({kind: "close", s, trade: ev}); }
          if (!s.pos && s.cash > 1){
            // 진입 관문: 보호장치 잠금 → 앱의 판정(리스크 결정표·투자위원회·심리·뉴스)
            let g = {ok: true, mul: 1, why: ""};
            if ((s.lockedUntil || 0) > last.t) g = {ok: false, why: `보호장치 잠금 — ${s.lockWhy || ""}`};
            else if (GATE){ try { g = {ok: true, mul: 1, why: "", ...(await GATE({s, side: want, price, cs}) || {})}; } catch(e){} }
            if (!g.ok){ s.lastBlock = {t: Date.now(), why: g.why, side: want}; events.push({kind: "blocked", s, side: want, why: g.why}); }
            else { const p = openPos(s, want, price, last.t, atrOf(cs), g.mul ?? 1); events.push({kind: "open", s, pos: p, why: sig.why + (g.why ? ` · 관문: ${g.why}` : "")}); }
          }
        }
      }
      // 평가금액
      const pos = s.pos, unreal = pos ? (pos.side === "long" ? 1 : -1) * (price - pos.entry) / pos.entry * pos.notional : 0;
      s.mark = {price, t: Date.now(), unreal};
      s.equity.push({t: Date.now(), v: s.cash + unreal}); if (s.equity.length > 500) s.equity.splice(0, s.equity.length - 500);
      if (s.cash <= 1 && !s.pos){ s.status = "retired"; s.retiredWhy = "가상 계좌 파산"; events.push({kind: "bust", s}); }
    } catch(e){ events.push({kind: "error", s, error: e.message}); }
  }
  BOOK.updated = Date.now();
  await save();
  for (const ev of events) onEvent?.(ev);
  return events;
}
const fmt = n => Number(n).toLocaleString("ko-KR", {maximumFractionDigits: 2});
export async function bookText(){
  await loadBook();
  const act = BOOK.strategies.filter(s => s.status === "active"), old = BOOK.strategies.filter(s => s.status !== "active");
  if (!BOOK.strategies.length) return "아직 모의투자 중인 전략이 없습니다. 퀀트 연구소가 검증을 통과한 전략을 올리면 여기서 운용합니다.";
  const line = s => { const eq = equityOf(s), r = (eq / START - 1) * 100, w = s.trades.filter(t => t.pnl > 0).length;
    return `- ${s.name} (${s.mname || s.market} ${s.tf}, 레버리지 ${s.spec?.risk?.leverage ?? "?"}배, ${s.author}) · 평가 ${fmt(eq)} (${r >= 0 ? "+" : ""}${r.toFixed(2)}%) · 거래 ${s.trades.length}회 승 ${w}${s.pos ? ` · 보유 ${s.pos.side === "long" ? "롱" : "숏"} ${fmt(s.pos.entry)} (x${s.pos.lev})` : " · 무포지션"}${s.status !== "active" ? ` · ${s.retiredWhy || "중지"}` : ""}`; };
  const tot = act.reduce((a, s) => a + equityOf(s), 0), base = act.length * START;
  return `운용 중 ${act.length}개 (코인·주식·선물, 전략마다 가상 10,000) · 합계 ${fmt(tot)} (${base ? ((tot / base - 1) * 100).toFixed(2) : 0}%)\n${act.map(line).join("\n")}${old.length ? "\n\n내린 전략:\n" + old.slice(-5).map(line).join("\n") : ""}`;
}
