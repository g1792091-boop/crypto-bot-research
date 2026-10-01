// 모의투자: 사무실 팀이 검증(앞 70% 개발 · 뒤 30% 검증)을 통과시킨 전략을 실제 시세로 가상 운용한다.
// 주문은 내지 않는다. 가상 계좌(전략마다 10,000 USDT)에서 신호·손절·익절·청산을 코드가 계산해 기록한다.
import { idb, uid } from "./engine.js";
import { candlesFor } from "./agent.js";

const KEY = "paper:book", START = 10000, MAX_ACTIVE = 8;
let BOOK = null;
export async function loadBook(){
  if (!BOOK){ const v = await idb.all(KEY).catch(() => []); BOOK = v[0] && v[0].strategies ? v[0] : {strategies: [], updated: 0}; }
  return BOOK;
}
const save = () => idb.put(KEY, BOOK);
export const TFS = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"};
const tfOf = iv => TFS[iv] || (Object.values(TFS).includes(String(iv)) ? String(iv) : "60");

// 새 전략을 모의투자에 올린다 (활성 전략이 많으면 성과가 가장 나쁜 것을 내린다)
export async function addStrategy({spec, market, exchange = "binancef", tf, author = "", wf = null, cls = "crypto", mname = ""}){
  await loadBook();
  const s = {id: uid(), name: spec.name || "이름 없는 전략", spec, market: market || spec.symbol || "BTCUSDT", mname: mname || market, cls, exchange, tf: tfOf(tf || spec.interval), author, wf,
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
export const equityOf = s => s.equity.at(-1)?.v ?? START;

function closePos(s, price, t, reason){
  const p = s.pos; if (!p) return null;
  const dir = p.side === "long" ? 1 : -1;
  const fee = (s.spec.risk?.fee_pct ?? 0.04) / 100 + (s.spec.risk?.slippage_pct ?? 0.01) / 100;
  const pnlPct = dir * (price - p.entry) / p.entry;                       // 가격 기준
  const pnl = p.notional * pnlPct - p.notional * fee * 2;
  const ret = {side: p.side, entryT: p.t, entryP: p.entry, exitT: t, exitP: price, pnl, roe: p.margin ? pnl / p.margin * 100 : 0, reason};
  s.cash = Math.max(0, s.cash + pnl); s.trades.push(ret); if (s.trades.length > 200) s.trades.splice(0, s.trades.length - 200);
  s.pos = null;
  return ret;
}
function openPos(s, side, price, t, atr){
  const r = s.spec.risk || {}, lev = Math.max(1, Math.min(200, +r.leverage || 3)), pct = Math.max(1, Math.min(100, +r.position_pct || 20));
  const margin = s.cash * pct / 100, notional = margin * lev, dir = side === "long" ? 1 : -1;
  const sl = r.stop_loss_pct ? price * (1 - dir * r.stop_loss_pct / 100) : r.atr_stop_mult && atr ? price - dir * atr * r.atr_stop_mult : null;
  const tp = r.take_profit_pct ? price * (1 + dir * r.take_profit_pct / 100) : r.atr_tp_mult && atr ? price + dir * atr * r.atr_tp_mult : null;
  const liq = price * (1 - dir * (1 / lev) * 0.95);
  s.pos = {side, entry: price, t, margin, notional, lev, sl, tp, liq, best: price, trail: r.trailing_stop_pct || null};
  return s.pos;
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
        let ev = null;
        if (hitLiq) ev = closePos(s, p.liq, last.t, "강제청산");
        else if (hitSl) ev = closePos(s, p.sl, last.t, "손절");
        else if (hitTrail) ev = closePos(s, trailStop, last.t, "추적 손절");
        else if (hitTp) ev = closePos(s, p.tp, last.t, "익절");
        if (ev) events.push({kind: "close", s, trade: ev});
      }
      const sig = Q.liveSignal(s.spec, cs, {position: s.pos?.side || null});
      s.lastSignal = sig ? {action: sig.action, why: sig.why, t: Date.now()} : null;
      if (sig && sig.t && sig.t !== s.lastBar){
        s.lastBar = sig.t;
        const want = sig.action;
        if ((want === "exit_long" && s.pos?.side === "long") || (want === "exit_short" && s.pos?.side === "short")){
          const ev = closePos(s, price, last.t, "청산 신호"); if (ev) events.push({kind: "close", s, trade: ev, why: sig.why});
        }
        if (want === "long" || want === "short"){
          if (s.pos && s.pos.side !== want && s.spec.risk?.allow_reverse !== false){ const ev = closePos(s, price, last.t, "반대 신호"); if (ev) events.push({kind: "close", s, trade: ev}); }
          if (!s.pos && s.cash > 1){ const p = openPos(s, want, price, last.t, atrOf(cs)); events.push({kind: "open", s, pos: p, why: sig.why}); }
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
