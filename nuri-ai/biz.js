// 사업 시뮬레이션: 신사업팀이 낸 사업 아이디어의 숫자 가정으로 36개월 손익을 몬테카를로로 돌려 본다.
// 가정이 틀리면 결과도 틀린다 — '될 것 같은지'를 숫자로 빨리 걸러 내는 용도이고, 실제 사업 전에는 시장 검증이 필요하다.

// 가정 필드 (원화). 없는 값은 보수적인 기본값을 쓴다
export const BIZ_FIELDS = {
  price_krw: ["고객 1명 월 매출(원)", 30000], cogs_pct: ["매출원가 비율(%)", 30], conv_rate: ["방문자→고객 전환율(%)", 2],
  cac_krw: ["고객 1명 획득 비용(원)", 40000], churn_monthly: ["월 이탈률(%)", 6], visitors_month: ["첫 달 방문자 수", 5000],
  visitor_growth: ["방문자 월 성장률(%)", 8], fixed_cost_month: ["월 고정비(원)", 8000000], marketing_month: ["월 마케팅비(원)", 3000000],
  initial_capital: ["초기 자본(원)", 50000000], upfront_cost: ["초기 투자비(원)", 20000000], market_size: ["도달 가능한 최대 고객 수", 0], ramp_months: ["입소문이 붙기까지 개월", 6]
};
const num = (v, d) => { const n = +String(v ?? "").toString().replace(/[^\d.\-]/g, ""); return Number.isFinite(n) && String(v ?? "") !== "" ? n : d; };
export function normalizeIdea(x = {}){
  const a = {name: String(x.name || "이름 없는 사업").slice(0, 60), desc: String(x.desc || x.description || "").slice(0, 400), customer: String(x.customer || "").slice(0, 200)};
  for (const [k, [, d]] of Object.entries(BIZ_FIELDS)) a[k] = Math.max(0, num(x[k], d));
  if (!a.market_size) a.market_size = Math.round(a.visitors_month * 3);   // 모르면 보수적으로: 첫 달 방문자의 3배가 최대 고객
  a.conv_rate = Math.min(a.conv_rate, 50); a.churn_monthly = Math.min(Math.max(a.churn_monthly, 0.5), 80); a.cogs_pct = Math.min(a.cogs_pct, 95);
  return a;
}
// 결정적 난수 (같은 아이디어면 같은 결과)
function rng(seed){ let s = seed >>> 0 || 1; return () => { s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; }; }
const gauss = r => { let u = 0, v = 0; while (!u) u = r(); while (!v) v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
const hash = s => [...String(s)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);

// runs번 시뮬레이션: 전환율·이탈률·획득비용·성장률에 ±불확실성(로그정규)을 준다
export function simulate(idea, {months = 36, runs = 400} = {}){
  const a = normalizeIdea(idea), r = rng(hash(a.name + a.price_krw));
  const paths = [];
  for (let k = 0; k < runs; k++){
    const f = s => Math.exp(gauss(r) * s);
    const conv = a.conv_rate / 100 * f(0.35), churn = Math.min(0.9, a.churn_monthly / 100 * f(0.3)), cac = a.cac_krw * f(0.3), growth = a.visitor_growth / 100 * f(0.4);
    let cash = a.initial_capital - a.upfront_cost, cust = 0, visitors = a.visitors_month, cum = -a.upfront_cost, be = null, minCash = cash;
    const monthly = [];
    for (let m = 1; m <= months; m++){
      // 초반에는 인지도가 낮아 전환이 덜 되고(ramp), 고객이 시장 크기에 가까울수록 새 고객이 줄어든다(포화)
      const ramp = Math.min(1, m / Math.max(1, a.ramp_months)), room = Math.max(0, 1 - cust / a.market_size);
      const paidNew = cac > 0 ? a.marketing_month / cac : 0, organic = visitors * conv * ramp;
      cust = cust * (1 - churn) + (paidNew + organic) * room;
      const rev = cust * a.price_krw, gross = rev * (1 - a.cogs_pct / 100), profit = gross - a.fixed_cost_month - a.marketing_month;
      cash += profit; cum += profit; minCash = Math.min(minCash, cash);
      if (be == null && profit > 0) be = m;
      monthly.push({m, cust, rev, profit, cash});
      visitors = Math.min(visitors * (1 + growth), a.visitors_month * 6);   // 방문자 성장은 첫 달의 6배에서 멈춘다
    }
    paths.push({be, cum, minCash, last: monthly[months - 1], monthly});
  }
  const q = (arr, p) => { const s = [...arr].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(p * s.length))]; };
  const cums = paths.map(p => p.cum), bes = paths.map(p => p.be ?? Infinity);
  const med = paths[Math.floor(runs / 2)];
  const curve = Array.from({length: months}, (_, i) => ({m: i + 1, rev: q(paths.map(p => p.monthly[i].rev), 0.5), profit: q(paths.map(p => p.monthly[i].profit), 0.5), cash: q(paths.map(p => p.monthly[i].cash), 0.5)}));
  const res = {
    idea: a, months, runs,
    pBreakeven24: paths.filter(p => p.be && p.be <= 24).length / runs,
    breakevenMedian: q(bes, 0.5) === Infinity ? null : q(bes, 0.5),
    cumProfit: {p10: q(cums, 0.1), p50: q(cums, 0.5), p90: q(cums, 0.9)},
    pBust: paths.filter(p => p.minCash < 0).length / runs,
    revenueMonth12: q(paths.map(p => p.monthly[11]?.rev ?? 0), 0.5), revenueLast: q(paths.map(p => p.last.rev), 0.5),
    curve
  };
  res.verdict = verdict(res);
  res.promising = res.verdict.startsWith("유망");
  return res;
}
// 판정 기준 (코드): 24개월 안 흑자 전환 확률 ≥ 60%, 36개월 누적 손익 중앙값 > 0, 자금 바닥 확률 < 30%
export function verdict(r){
  if (r.pBreakeven24 >= 0.6 && r.cumProfit.p50 > 0 && r.pBust < 0.3) return "유망 — 사업계획서로 구체화할 가치가 있음";
  if (r.pBreakeven24 >= 0.35 && r.cumProfit.p90 > 0) return "보류 — 가정 몇 개(전환율·획득비용·가격)를 바꾸면 가능성 있음";
  return "탈락 — 지금 가정으로는 돈을 벌기 어려움";
}
const won = n => { const a = Math.abs(n); return (n < 0 ? "-" : "") + (a >= 1e8 ? (a / 1e8).toFixed(1) + "억" : a >= 1e4 ? Math.round(a / 1e4).toLocaleString("ko-KR") + "만" : Math.round(a).toLocaleString("ko-KR")) + "원"; };
export function bizText(r){
  const a = r.idea;
  return `[사업 시뮬레이션] ${a.name} — ${r.runs}회 × ${r.months}개월
가정: 월 ${won(a.price_krw)}/고객 · 원가 ${a.cogs_pct}% · 전환 ${a.conv_rate}% · 획득비용 ${won(a.cac_krw)} · 이탈 ${a.churn_monthly}%/월 · 고정비 ${won(a.fixed_cost_month)}/월 · 마케팅 ${won(a.marketing_month)}/월 · 초기자본 ${won(a.initial_capital)}
24개월 안 흑자 전환 확률 ${(r.pBreakeven24 * 100).toFixed(0)}% · 흑자 전환 중앙값 ${r.breakevenMedian ? r.breakevenMedian + "개월" : "36개월 안 없음"} · 자금 바닥 확률 ${(r.pBust * 100).toFixed(0)}%
36개월 누적 손익: 비관 ${won(r.cumProfit.p10)} · 중앙 ${won(r.cumProfit.p50)} · 낙관 ${won(r.cumProfit.p90)} · 12개월째 월매출 ${won(r.revenueMonth12)} · 36개월째 ${won(r.revenueLast)}
판정: ${r.verdict}`;
}
export function financialsCSV(r){
  return "month,revenue_krw,profit_krw,cash_krw\n" + r.curve.map(c => [c.m, Math.round(c.rev), Math.round(c.profit), Math.round(c.cash)].join(",")).join("\n") + "\n";
}
export const IDEA_PROMPT = `사업 아이디어 하나를 JSON으로 낸다. 형식:
{"name":"사업 이름","desc":"무엇을 누구에게 어떻게 파는지 2~3문장","customer":"핵심 고객","price_krw":고객1명월매출,"cogs_pct":매출원가%,"conv_rate":방문자→고객전환%,"cac_krw":고객획득비용,"churn_monthly":월이탈%,"visitors_month":첫달방문자,"visitor_growth":방문자월성장%,"fixed_cost_month":월고정비,"marketing_month":월마케팅비,"initial_capital":초기자본,"upfront_cost":초기투자비,"market_size":도달가능최대고객수,"ramp_months":입소문까지개월}
숫자는 업계 평균을 근거로 현실적으로(낙관 금지). 코드가 36개월 몬테카를로로 손익을 계산한다.`;
