// 📈 스윙 라인 — 일봉 추세추종(시계열 모멘텀) 뼈대 + 묶음(6코인) 검증.
// 왜 있나: 2026-10-05 실제 바이낸스 선물 데이터로 직접 시험한 결과
//   · 1시간·4시간봉 고전 지표 매매법 216개(추세 120 + 되돌림 96) × 6코인: 학습 구간에서 좋았던 것도 처음 보는 구간 묶음 손익비 평균 0.84 (나머지 0.83과 차이 없음) → 우위 없음
//   · '직전 구간에 잘 된 매매법으로 갈아타기'도 다음 구간 손익비 0.75~0.97 로 오히려 나쁨
//   · 일봉 추세추종(넓은 ATR 손절 · 3배 · 익절 고정 없이 추세가 꺾일 때 청산)만 4년 묶음 손익비 1.1~1.9, 9개 뼈대 전부 1 초과
// 그래서 데모 장부에 '검증된 뼈대'를 코드가 직접 올린다(AI 설계가 아니라 코드 검증). 개념은 널리 알려진 터틀/돈치안·이동평균 추세추종 — 코드 복사 없음.
// 주의: 추세추종은 6~8개월씩 잃는 구간이 있다(구간별 손익비 0.2~0.5). 과거 성과가 미래를 보장하지 않는다. 데모 전용.
const c = (left, op, right) => ({ left, op, right: String(right) }), G = (L) => ({ logic: "all", conditions: L });
export const RISK = { leverage: 3, position_pct: 20, atr_stop_mult: 3, allow_reverse: false, risk_pct: 1 };
export const SEEDS = [
  { key: "sma50_long", name: "스윙 · 50일선 위 추세(롱 전용)", why: "종가가 50일 이동평균을 넘으면 사고, 아래로 내려가면 판다",
    indicators: [{ id: "s", type: "sma", length: 50 }], long_entry: G([c("close", "crosses_above", "s")]), short_entry: null, long_exit: G([c("close", "<", "s")]), short_exit: null },
  { key: "st_long", name: "스윙 · 슈퍼트렌드 상승 전환(롱 전용)", why: "일봉 슈퍼트렌드가 상승으로 바뀌면 사고, 하락으로 바뀌면 판다",
    indicators: [{ id: "st", type: "supertrend", length: 10, mult: 3 }], long_entry: G([c("st.trend", "crosses_above", 0)]), short_entry: null, long_exit: G([c("st.trend", "<", 0)]), short_exit: null },
  { key: "don20_long", name: "스윙 · 20일 신고가 돌파(롱 전용)", why: "20일 최고가를 넘으면 사고, 10일 최저가를 깨면 판다(터틀 방식)",
    indicators: [{ id: "hh", type: "highest", length: 20 }, { id: "l10", type: "lowest", length: 10 }], long_entry: G([c("close", ">", "hh[1]")]), short_entry: null, long_exit: G([c("close", "<", "l10[1]")]), short_exit: null },
  { key: "ema20_50_long", name: "스윙 · EMA 20/50 골든크로스(롱 전용)", why: "20일 EMA가 50일 EMA를 넘으면 사고, 다시 내려가면 판다",
    indicators: [{ id: "f", type: "ema", length: 20 }, { id: "s", type: "ema", length: 50 }], long_entry: G([c("f", "crosses_above", "s")]), short_entry: null, long_exit: G([c("f", "<", "s")]), short_exit: null },
  { key: "don55_ls", name: "스윙 · 55일 돌파(롱·숏)", why: "55일 최고가 돌파에 롱, 55일 최저가 이탈에 숏 · 20일 반대 돌파에 청산",
    indicators: [{ id: "hh", type: "highest", length: 55 }, { id: "ll", type: "lowest", length: 55 }, { id: "h20", type: "highest", length: 20 }, { id: "l20", type: "lowest", length: 20 }],
    long_entry: G([c("close", ">", "hh[1]")]), short_entry: G([c("close", "<", "ll[1]")]), long_exit: G([c("close", "<", "l20[1]")]), short_exit: G([c("close", ">", "h20[1]")]) },
  { key: "st_ls", name: "스윙 · 슈퍼트렌드 전환(롱·숏)", why: "일봉 슈퍼트렌드 방향대로 롱·숏",
    indicators: [{ id: "st", type: "supertrend", length: 10, mult: 3 }], long_entry: G([c("st.trend", "crosses_above", 0)]), short_entry: G([c("st.trend", "crosses_below", 0)]), long_exit: G([c("st.trend", "<", 0)]), short_exit: G([c("st.trend", ">", 0)]) },
  { key: "ema20_50_ls", name: "스윙 · EMA 20/50 교차(롱·숏)", why: "20일 EMA와 50일 EMA 교차 방향대로 롱·숏",
    indicators: [{ id: "f", type: "ema", length: 20 }, { id: "s", type: "ema", length: 50 }], long_entry: G([c("f", "crosses_above", "s")]), short_entry: G([c("f", "crosses_below", "s")]), long_exit: G([c("f", "<", "s")]), short_exit: G([c("f", ">", "s")]) },
];
export const pf = tr => { let g = 0, l = 0; for (const t of tr) t.pnl > 0 ? g += t.pnl : l -= t.pnl; return l ? g / l : (g ? 9 : 0); };
export function specOf(seed, symbol, costs = {}) {
  return { name: seed.name, description: seed.why, symbol, interval: "1d", indicators: seed.indicators, long_entry: seed.long_entry, short_entry: seed.short_entry, long_exit: seed.long_exit, short_exit: seed.short_exit, risk: { ...RISK, ...costs } };
}
// 묶음 검증: 뼈대마다 모든 코인의 거래를 한데 모아 손익비·운일 확률·전반/후반·이익 난 코인 수를 본다.
//   통과 = 묶음 손익비 ≥ 1.3 · 거래 60건↑ · 이익 난 코인 ≥ 2/3 · 전반·후반 둘 다 손익비 > 1 · 운일 확률 p ≤ 0.2
export function audit(Q, RB, data, costs = {}) {
  const coins = Object.keys(data), rows = [];
  for (const seed of SEEDS) {
    const all = [], per = []; let pos = 0;
    for (const sym of coins) { try {
      const cs = data[sym]; if (!cs || cs.length < 300) continue;
      const spec = Q.normalizeSpec(specOf(seed, sym, costs)), bt = Q.backtest(spec, cs), sum = bt.trades.reduce((a, t) => a + t.pnl, 0);
      all.push(...bt.trades); if (sum > 0) pos++; per.push({ sym, ret: +(bt.stats.return_pct ?? 0), n: bt.trades.length, pf: +pf(bt.trades).toFixed(2), dd: +(bt.stats.max_dd_pct ?? 0) });
    } catch (e) { per.push({ sym, err: String(e.message || e).slice(0, 60) }); } }
    all.sort((a, b) => a.entryT - b.entryT);
    const half = Math.floor(all.length / 2), p = all.length >= 10 ? RB.permutationTest(all.map(t => t.pnl)).p : null;
    const r = { key: seed.key, name: seed.name, why: seed.why, n: all.length, pf: +pf(all).toFixed(2), pf1: +pf(all.slice(0, half)).toFixed(2), pf2: +pf(all.slice(half)).toFixed(2), recent: +pf(all.slice(-Math.max(12, Math.floor(all.length / 6)))).toFixed(2),
      pos, coins: per.filter(x => !x.err).length, p: p == null ? null : +p.toFixed(2), per, ls: !!seed.short_entry };
    r.pass = r.n >= 60 && r.pf >= 1.3 && r.pos >= Math.ceil(r.coins * 2 / 3) && r.pf1 > 1 && r.pf2 > 1 && (r.p == null || r.p <= 0.2);
    rows.push(r);
  }
  rows.sort((a, b) => (b.pass - a.pass) || (b.pf - a.pf));
  return rows;
}
// 지금 일봉 추세(손매매·뉴럴 데스크 참고용): 50일선 위/아래 + 슈퍼트렌드 방향 + 20일 돌파 위치
export function dailyTrend(Q, cs) {
  if (!cs || cs.length < 80) return null;
  const n = cs.length, close = cs[n - 1].c;
  const sma = (len) => { let s = 0; for (let i = n - len; i < n; i++) s += cs[i].c; return s / len; };
  const s50 = sma(50), s20 = sma(20);
  let st = 0; try { const o = Q.computeInd(cs, "supertrend", { length: 10, mult: 3 }), tr = o?.trend; st = tr ? Math.sign(tr[tr.length - 1] || 0) : 0; } catch (e) {}
  let hh = -Infinity, ll = Infinity; for (let i = n - 21; i < n - 1; i++) { hh = Math.max(hh, cs[i].h); ll = Math.min(ll, cs[i].l); }
  const above = close > s50 ? 1 : -1, votes = above + (st || 0) + (s20 > s50 ? 1 : -1);
  const dir = votes >= 2 ? 1 : votes <= -2 ? -1 : 0;
  return { dir, label: dir > 0 ? "상승" : dir < 0 ? "하락" : "혼조", close, sma50: s50, distPct: +((close / s50 - 1) * 100).toFixed(1), st, breakout: close > hh ? 1 : close < ll ? -1 : 0, t: Date.now() };
}
