// 🔬 전략 분석 5항목 — 사용자 제공 프롬프트 3-5 의 분석 틀을 '코드가 잰 숫자'로 채운다. AI 는 이 숫자를 받아 해설만 한다.
//   ① 시장 레짐 적합성(추세/횡보/고변동성 중 어디에 맞나) ② 리스크 노출(레버리지·집중도·꼬리 위험) ③ 과최적화 가능성(값 개수 대비 거래 수)
//   ④ 실행 현실성(비용·지연) ⑤ 개선 방향(레짐 필터 등 — 사후 시험 숫자와 함께)
// 레짐 정의는 터미널 chartread.js 와 같다: HIGH_VOL = ATR% 가 최근 200봉 상위 15% · TREND = ADX 25↑ · 그 외 RANGE.
export const pf = tr => { let g = 0, l = 0; for (const t of tr) t.pnl > 0 ? g += t.pnl : l -= t.pnl; return l ? g / l : (g ? 9 : 0); };
const r2 = v => v == null || !Number.isFinite(+v) ? null : +(+v).toFixed(2);
const KO = { TREND: "추세장", RANGE: "횡보장", HIGH_VOL: "고변동성장" };
// 봉마다 레짐 표시
export function regimeSeries(Q, cs) {
  const n = cs.length, out = new Array(n).fill(null); let adx = [], atr = [];
  try { adx = Q.computeInd(cs, "adx", { length: 14 }).adx; atr = Q.computeInd(cs, "atr", { length: 14 }).value; } catch (e) { return out; }
  const pctArr = cs.map((b, i) => atr[i] && b.c ? atr[i] / b.c * 100 : null), win = [];
  for (let i = 0; i < n; i++) { const p = pctArr[i]; if (p == null) continue; win.push(p); if (win.length > 200) win.shift();
    const rank = win.filter(x => x <= p).length / win.length; out[i] = win.length >= 30 && rank >= 0.85 ? "HIGH_VOL" : (adx[i] ?? 0) >= 25 ? "TREND" : "RANGE"; }
  return out;
}
function countParams(spec) {
  let k = 0; for (const i of spec.indicators || []) for (const [key, v] of Object.entries(i)) if (!["id", "type", "source", "expr"].includes(key) && Number.isFinite(+v)) k++;
  for (const i of spec.indicators || []) if (i.expr) k += (String(i.expr).match(/\d+(\.\d+)?/g) || []).length;
  for (const g of ["long_entry", "short_entry", "long_exit", "short_exit"]) for (const c of spec[g]?.conditions || []) if (/^-?\d+(\.\d+)?$/.test(String(c.right)) || /\*\s*\d/.test(String(c.right))) k++;
  const r = spec.risk || {}; for (const key of ["stop_loss_pct", "take_profit_pct", "atr_stop_mult", "atr_tp_mult", "trailing_stop_pct"]) if (r[key] != null) k++;
  return Math.max(1, k);
}
/** 전략 분석. cs = [{t,o,h,l,c,v}] */
export function review(Q, spec0, cs, opts = {}) {
  const spec = Q.normalizeSpec(spec0), bt = Q.backtest(spec, cs, opts), wf = Q.walkForward(spec, cs, opts), tr = bt.trades || [], n = tr.length, risk = spec.risk || {};
  // ① 레짐 적합성
  const rs = regimeSeries(Q, cs), idxOf = t => { let lo = 0, hi = cs.length - 1; while (lo < hi) { const m = (lo + hi + 1) >> 1; if (cs[m].t <= t) lo = m; else hi = m - 1; } return lo; };
  const byR = { TREND: [], RANGE: [], HIGH_VOL: [] }; for (const t of tr) { const k = rs[Math.max(0, idxOf(t.entryT) - 1)]; if (k) byR[k].push(t); }
  const share = { TREND: 0, RANGE: 0, HIGH_VOL: 0 }; let cnt = 0; for (const k of rs) if (k) { share[k]++; cnt++; }
  const regRows = Object.entries(byR).map(([k, a]) => ({ key: k, ko: KO[k], n: a.length, pf: r2(pf(a)), wr: a.length ? Math.round(a.filter(t => t.pnl > 0).length / a.length * 100) : null, pnl: r2(a.reduce((s, t) => s + t.pnl, 0)), time_share: cnt ? Math.round(share[k] / cnt * 100) : null }));
  const scored = regRows.filter(r => r.n >= 8), best = [...scored].sort((a, b) => b.pf - a.pf)[0] || null, worst = [...scored].sort((a, b) => a.pf - b.pf)[0] || null;
  const regime = { rows: regRows, best: best?.key || null, worst: worst && worst !== best ? worst.key : null,
    verdict: !scored.length ? "거래가 적어 레짐별 판단 불가" : best.pf < 1 ? "어느 레짐에서도 이익이 아님" : `${best.ko}에 적합(손익비 ${best.pf})${worst && worst !== best && worst.pf < 1 ? ` · ${worst.ko}에서 손실(손익비 ${worst.pf})` : ""}` };
  // ② 리스크 노출
  const lev = +risk.leverage || 1, slPct = risk.stop_loss_pct != null ? +risk.stop_loss_pct : null, liqDist = 100 / lev * 0.95;
  let streak = 0, maxStreak = 0; for (const t of tr) { if (t.pnl <= 0) { streak++; maxStreak = Math.max(maxStreak, streak); } else streak = 0; }
  const pcts = tr.map(t => t.pnlPct).sort((a, b) => a - b), tailN = Math.max(1, Math.floor(n * 0.05)), tail = n ? pcts.slice(0, tailN).reduce((s, x) => s + x, 0) / tailN : null;
  const span = cs.length ? cs[cs.length - 1].t - cs[0].t : 1, inMkt = tr.reduce((s, t) => s + (t.exitT - t.entryT), 0), longs = tr.filter(t => t.side === "long").length;
  const riskX = { leverage: lev, stop_loss_pct: slPct, liq_distance_pct: r2(liqDist), stop_vs_liq: slPct != null ? r2(slPct / liqDist) : null, max_loss_streak: maxStreak, worst_trade_pct: n ? r2(pcts[0]) : null, tail5_avg_pct: r2(tail), max_dd_pct: r2(bt.stats?.max_dd_pct), time_in_market_pct: Math.round(inMkt / span * 100), long_share_pct: n ? Math.round(longs / n * 100) : null,
    verdict: [slPct != null && slPct / liqDist > 0.6 ? "손절이 청산가에 너무 가까움" : null, maxStreak >= 8 ? `연속 손실 ${maxStreak}회(심리·자금 압박)` : null, (bt.stats?.max_dd_pct ?? 0) >= 40 ? `최대 낙폭 ${r2(bt.stats.max_dd_pct)}%` : null, n && (longs / n > 0.85 || longs / n < 0.15) ? "한 방향에 치우침" : null].filter(Boolean).join(" · ") || "특이 위험 없음" };
  // ③ 과최적화 가능성
  const params = countParams(spec), tpp = n / params, isPF = r2(wf.is?.profit_factor), oosPF = r2(wf.oos?.profit_factor), decay = isPF && oosPF != null ? r2(oosPF / isPF) : null;
  const overfit = { params, trades: n, trades_per_param: r2(tpp), is_pf: isPF, oos_pf: oosPF, oos_vs_is: decay,
    verdict: tpp < 10 ? `값 ${params}개에 거래 ${n}건 — 값 하나당 ${r2(tpp)}건으로 부족(10건 미만 = 과최적화 위험 큼)` : decay != null && decay < 0.6 ? `처음 보는 구간 손익비가 학습 구간의 ${Math.round(decay * 100)}% — 과최적화 의심` : `값 하나당 거래 ${r2(tpp)}건 · 처음 보는 구간 유지율 ${decay != null ? Math.round(decay * 100) + "%" : "—"} — 양호` };
  // ④ 실행 현실성: 비용 2배 · 신호 1봉 지연
  let pf2 = null, pfDelay = null;
  try { pf2 = r2(Q.backtest({ ...spec, risk: { ...risk, fee_pct: (risk.fee_pct ?? 0.04) * 2, slippage_pct: (risk.slippage_pct ?? 0.01) * 2 } }, cs, opts).stats?.profit_factor); } catch (e) {}
  if (opts.scenarios) try { const sc = opts.scenarios.runScenarios(spec, cs, opts), d1 = (sc.stress || []).find(x => x.key === "delay_1"); if (d1) pfDelay = r2(d1.profit_factor ?? d1.pf); } catch (e) {}
  const avgAbs = n ? tr.reduce((s, t) => s + Math.abs((t.exitP - t.entryP) / t.entryP * 100), 0) / n : null, cost = ((risk.fee_pct ?? 0.04) + (risk.slippage_pct ?? 0.01)) * 2, days = span / 864e5 || 1;
  const exec = { avg_move_pct: r2(avgAbs), round_trip_cost_pct: r2(cost), cost_share_pct: avgAbs ? Math.round(cost / avgAbs * 100) : null, pf_base: r2(bt.stats?.profit_factor), pf_cost_x2: pf2, pf_delay_1bar: pfDelay, trades_per_day: r2(n / days),
    verdict: avgAbs && cost / avgAbs > 0.25 ? `거래당 평균 움직임 ${r2(avgAbs)}% 중 비용이 ${Math.round(cost / avgAbs * 100)}% — 비용에 취약` : pf2 != null && pf2 < 1 && (bt.stats?.profit_factor ?? 0) >= 1 ? "비용이 2배면 손실로 바뀜 — 체결 품질에 민감" : "비용·지연에 비교적 견딤" };
  // ⑤ 개선 방향(사후 시험 숫자와 함께 — 사후 필터는 그 자체가 과최적화일 수 있어 '참고'로만)
  const improve = [], base = r2(pf(tr));
  if (regime.worst && byR[regime.worst].length >= 8) { const kept = tr.filter(t => rs[Math.max(0, idxOf(t.entryT) - 1)] !== regime.worst); improve.push({ idea: `레짐 필터: ${KO[regime.worst]}에서는 진입하지 않기`, before_pf: base, after_pf: r2(pf(kept)), trades: kept.length, note: "사후 시험(참고)" }); }
  if (regime.best && byR[regime.best].length >= 15 && regRows.filter(r => r.n >= 8).length >= 2) improve.push({ idea: `${KO[regime.best]} 전용으로 좁히기`, before_pf: base, after_pf: r2(pf(byR[regime.best])), trades: byR[regime.best].length, note: "사후 시험(참고)" });
  if (riskX.max_loss_streak >= 6) improve.push({ idea: "동적 사이징: 연속 손실 3회 뒤 크기 절반(보호장치)", note: `연속 손실 최대 ${riskX.max_loss_streak}회` });
  if (overfit.trades_per_param < 10) improve.push({ idea: "값(파라미터) 줄이기 또는 여러 코인 묶음으로 거래 수 늘려 검증", note: overfit.verdict });
  if (exec.cost_share_pct != null && exec.cost_share_pct > 25) improve.push({ idea: "더 긴 시간봉 또는 더 먼 익절로 거래당 움직임 키우기", note: exec.verdict });
  if (!improve.length) improve.push({ idea: "앙상블: 성격이 다른 전략(추세 + 되돌림)과 묶어 낙폭 줄이기", note: "단일 전략 기준 뚜렷한 약점 없음" });
  const flags = [regime.best && (regRows.find(r => r.key === regime.best)?.pf ?? 0) >= 1.1, !/가까움|연속 손실|낙폭|치우침/.test(riskX.verdict), !/부족|의심/.test(overfit.verdict), !/취약|민감/.test(exec.verdict)];
  return { name: spec.name, symbol: spec.symbol, interval: spec.interval, trades: n, all: { pf: r2(bt.stats?.profit_factor), ret: r2(bt.stats?.return_pct), dd: r2(bt.stats?.max_dd_pct), win: r2(bt.stats?.win_rate) }, wf_pass: !!wf.pass,
    regime, risk: riskX, overfit, exec, improve, score: flags.filter(Boolean).length, score_max: 4 };
}
export function reviewRows(R) {
  return [
    ["① 레짐 적합성", R.regime.rows.map(r => `${r.ko} ${r.n}건 손익비 ${r.pf ?? "—"}`).join(" · "), R.regime.verdict],
    ["② 리스크 노출", `${R.risk.leverage}배 · 손절 ${R.risk.stop_loss_pct ?? "—"}% (청산거리 ${R.risk.liq_distance_pct}%) · 연속 손실 최대 ${R.risk.max_loss_streak}회 · 최악 거래 ${R.risk.worst_trade_pct ?? "—"}% · 하위 5% 평균 ${R.risk.tail5_avg_pct ?? "—"}% · 낙폭 ${R.risk.max_dd_pct ?? "—"}%`, R.risk.verdict],
    ["③ 과최적화 가능성", `값 ${R.overfit.params}개 · 거래 ${R.overfit.trades}건 · 학습 손익비 ${R.overfit.is_pf ?? "—"} → 처음 보는 구간 ${R.overfit.oos_pf ?? "—"}`, R.overfit.verdict],
    ["④ 실행 현실성", `거래당 평균 움직임 ${R.exec.avg_move_pct ?? "—"}% · 왕복 비용 ${R.exec.round_trip_cost_pct}% · 손익비 ${R.exec.pf_base ?? "—"} → 비용 2배 ${R.exec.pf_cost_x2 ?? "—"}${R.exec.pf_delay_1bar != null ? ` · 1봉 지연 ${R.exec.pf_delay_1bar}` : ""} · 하루 ${R.exec.trades_per_day}건`, R.exec.verdict],
    ["⑤ 개선 방향", R.improve.map(x => `${x.idea}${x.after_pf != null ? ` (손익비 ${x.before_pf} → ${x.after_pf}, ${x.trades}건)` : ""}`).join(" / "), R.improve.some(x => x.after_pf != null) ? "사후 시험 숫자는 참고용 — 채택하려면 처음 보는 구간에서 다시 검증" : ""],
  ];
}
