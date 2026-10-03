// ai-trader-team 백테스터 — TLSRUF/ai-trader-team tools/backtest.py (MIT) 를 GH Coin 브라우저로 '실제 이식'한 것.
// SMA 상향 돌파 진입 + 고정% 손절 + 고정 R:R 목표 전략(단일 티커), 그리고 여러 티커를 한 계좌로 묶어
// 복리 수익률을 내는 aggregate_results 를 같은 공식·반올림(ROUND_HALF_EVEN)·검증 규칙으로 옮겼다.
// 원본 파이썬은 gh-coin/vendor/ai-trader-team/backtest.py 에 그대로 보관(출처 확인용). 출처: THIRD_PARTY.md
function q(v, dp){ const f = 10 ** dp, x = v * f; const out = (Math.abs(x - Math.trunc(x) - 0.5) < 1e-9) ? (Math.floor(x) % 2 === 0 ? Math.floor(x) : Math.ceil(x)) : Math.round(x); return out / f; }
const dec = v => { const n = Number(v); if (!Number.isFinite(n)) throw new Error(`숫자로 변환할 수 없습니다: ${v}`); return n; };

// closes: [{date:"YYYY-MM-DD", close:"123.45"|number}] (날짜 오름차순)
export function simulateTrendStrategy(closes, {sma_window = 20, stop_pct = 5, target_r_multiple = 2, max_hold_days = 60, friction_pct = 0} = {}){
  const sw = Math.trunc(dec(sma_window)), stopPct = dec(stop_pct), targetR = dec(target_r_multiple), maxHold = Math.trunc(dec(max_hold_days)), fric = dec(friction_pct);
  if (fric < 0) throw new Error("friction_pct는 음수일 수 없습니다.");
  if (stopPct <= 0) throw new Error("stop_pct는 0보다 커야 합니다.");
  if (targetR <= 0) throw new Error("target_r_multiple는 0보다 커야 합니다.");
  if (sw < 1) throw new Error("sma_window는 1 이상이어야 합니다.");
  if (!Array.isArray(closes) || closes.length < sw + 2) return [];
  const prices = closes.map(r => dec(r.close)), dates = closes.map(r => r.date);
  const smaAt = i => { let s = 0; for (let k = i - sw; k < i; k++) s += prices[k]; return s / sw; };
  const trades = [];
  let inPos = false, entryP = null, entryD = null, stopP = null, targetP = null, held = 0;
  for (let i = sw + 1; i < prices.length; i++){
    if (!inPos){
      const smaT = smaAt(i), smaY = smaAt(i - 1);
      if (prices[i - 1] <= smaY && prices[i] > smaT){
        inPos = true; entryP = prices[i]; entryD = dates[i]; held = 0;
        const risk = entryP * (stopPct / 100); stopP = entryP - risk; targetP = entryP + risk * targetR;
      }
      continue;
    }
    held++;
    const price = prices[i]; let exitP = null, reason = null;
    if (price <= stopP){ exitP = stopP; reason = "stop"; }
    else if (price >= targetP){ exitP = targetP; reason = "target"; }
    else if (held >= maxHold){ exitP = price; reason = "timeout"; }
    if (reason){
      const risk = entryP - stopP;
      let r = (exitP - entryP) / risk - (entryP * fric / 100) / risk;
      trades.push({entry_date: entryD, exit_date: dates[i], entry: q(entryP, 2), exit: q(exitP, 2), r_multiple: q(r, 2), reason});
      inPos = false;
    }
  }
  if (inPos){
    const risk = entryP - stopP, last = prices.length - 1;
    let r = (prices[last] - entryP) / risk - (entryP * fric / 100) / risk;
    trades.push({entry_date: entryD, exit_date: dates[last], entry: q(entryP, 2), exit: q(prices[last], 2), r_multiple: q(r, 2), reason: "end_of_data"});
  }
  return trades;
}

// 여러 티커 거래를 한 계좌로 묶어 복리 수익률 (거래당 risk_pct 를 R-멀티플만큼). max_heat_pct 로 동시 보유 한도.
export function aggregateResults(tradesByTicker, {risk_pct_per_trade = 1, max_heat_pct = null} = {}){
  const riskPct = dec(risk_pct_per_trade);
  if (riskPct <= 0) throw new Error("risk_pct_per_trade는 0보다 커야 합니다.");
  let all = [];
  for (const [ticker, trades] of Object.entries(tradesByTicker || {})) for (const t of trades) all.push({...t, ticker});
  let skipped = 0;
  if (max_heat_pct != null){
    const maxHeat = dec(max_heat_pct);
    if (maxHeat <= 0) throw new Error("max_heat_pct는 0보다 커야 합니다.");
    if (riskPct > maxHeat) throw new Error("risk_pct_per_trade가 max_heat_pct보다 커서 단 하나의 포지션도 열 수 없습니다.");
    const cand = [...all].sort((a, b) => a.entry_date < b.entry_date ? -1 : a.entry_date > b.entry_date ? 1 : (a.ticker < b.ticker ? -1 : a.ticker > b.ticker ? 1 : 0));
    let open = [], accepted = [];
    for (const t of cand){
      open = open.filter(ex => ex > t.entry_date);
      if (riskPct * open.length + riskPct <= maxHeat){ open.push(t.exit_date); accepted.push(t); }
      else skipped++;
    }
    all = accepted;
  }
  all.sort((a, b) => a.exit_date < b.exit_date ? -1 : a.exit_date > b.exit_date ? 1 : 0);
  let equity = 1, wins = 0;
  for (const t of all){ const r = dec(t.r_multiple); equity *= 1 + r * riskPct / 100; if (r > 0) wins++; }
  const n = all.length;
  return {n_trades: n, wins, win_rate_pct: q(n ? wins / n * 100 : 0, 2), total_return_pct: q((equity - 1) * 100, 2), skipped_for_heat_limit: skipped, trades: all};
}

// 기본 파라미터 그리드 (원본 DEFAULT_WALK_FORWARD_PARAM_GRID)
export const DEFAULT_PARAM_GRID = [10, 20].flatMap(sw => [3, 5].flatMap(sp => [2, 3].flatMap(tr => [60, 120].map(mh => ({sma_window: sw, stop_pct: sp, target_r_multiple: tr, max_hold_days: mh})))));
