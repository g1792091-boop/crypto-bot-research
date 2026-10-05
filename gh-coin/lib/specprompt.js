// 🧩 매매법 설계 지시문(로컬·작은 모델용) — "스캐폴딩 최소화, 큐레이션 최대화"
// 왜 따로 있나: 기존 설계 지시문은 형식 설명 + 지표 표 + 차트 숫자 덤프로 약 4천 토큰이었고, 작은 모델(2~3b)은 그 길이에서 형식을 지키지 못했다
//   (빈 전략 {} · 진입 조건 없음 · 없는 지표 이름). 2026-10-05 실제 Ollama 로 각 6회 측정 — 형식 통과: qwen2.5:3b 0→5 · llama3.2:3b 0→4 · gemma2:2b 2→4, 응답 시간 2~3배 빨라짐.
//   (문맥 한도에 걸려 잘린 것은 아니었다: 이 PC 의 Ollama 는 8,192~16,384 토큰까지 받는다. 원인은 길이·복잡도.)
// 적용한 원칙(사용자 제공 프롬프트 가이드 3-6): ① 명시적으로 ② 이유를 말해 주기 ③ XML 태그로 역할·규칙·예시·맥락·과제 분리 ④ 구체적인 입출력 예시(few-shot) ⑤ 짧게.
// 예시는 코드가 검증한 실제 유효 JSON 이고, 호출마다 '이번 재료'를 바꿔 같은 답만 반복하지 않게 한다.
const J = o => JSON.stringify(o);
const cond = (left, op, right) => ({ left, op, right: String(right) });
export const EXAMPLES = {
  trend: { name: "EMA 추세 + RSI 50 재돌파", indicators: [{ id: "ef", type: "ema", length: 50 }, { id: "es", type: "ema", length: 200 }, { id: "r", type: "rsi", length: 14 }],
    long_entry: { logic: "all", conditions: [cond("ef", ">", "es"), cond("r", "crosses_above", 50)] }, short_entry: { logic: "all", conditions: [cond("ef", "<", "es"), cond("r", "crosses_below", 50)] },
    long_exit: null, short_exit: null, risk: { stop_loss_pct: 1.5, take_profit_pct: 3.75 } },
  revert: { name: "볼린저 밴드 복귀 + 약한 추세", indicators: [{ id: "bb", type: "bb", length: 20, mult: 2 }, { id: "adx", type: "adx", length: 14 }],
    long_entry: { logic: "all", conditions: [cond("close", "crosses_above", "bb.lower"), cond("adx.adx", "<", 25)] }, short_entry: { logic: "all", conditions: [cond("close", "crosses_below", "bb.upper"), cond("adx.adx", "<", 25)] },
    long_exit: { logic: "any", conditions: [cond("close", ">", "bb.middle")] }, short_exit: { logic: "any", conditions: [cond("close", "<", "bb.middle")] }, risk: { stop_loss_pct: 1.5, take_profit_pct: 2.25 } },
  custom: { name: "변동성 조정 모멘텀 돌파", indicators: [{ id: "vmom", type: "custom", expr: '(close - close[20]) / (ind("atr",{length:14}) * sqrt(20))' }, { id: "e", type: "ema", length: 100 }],
    long_entry: { logic: "all", conditions: [cond("vmom", "crosses_above", 1), cond("close", ">", "e")] }, short_entry: { logic: "all", conditions: [cond("vmom", "crosses_below", -1), cond("close", "<", "e")] },
    long_exit: null, short_exit: null, risk: { stop_loss_pct: 2, take_profit_pct: 4 } },
};
// 호출마다 바꿔 주는 '이번 재료' — 같은 조합만 반복하지 않게(계열별)
const INGREDIENTS = {
  trend: [["supertrend (st.trend 가 1/-1)", "ema 200"], ["donchian (upper/lower 돌파)", "adx"], ["macd (line 과 signal 교차)", "ema 100"], ["keltner (upper/lower 돌파)", "volume_sma (거래량 확인)"], ["highest/lowest 30봉 돌파", "adx", "ema 200"], ["hma 55 방향", "roc 9"], ["ichimoku (tenkan/kijun 교차)", "ema 200"]],
  revert: [["rsi 30/70 복귀", "adx 낮을 때"], ["stochrsi (k 가 20/80 교차)", "ema 200 방향"], ["keltner 하단/상단 복귀", "adx 낮을 때"], ["cci ±100 복귀", "bb"], ["mfi 20/80 복귀", "sma 50"], ["willr -80/-20 교차", "adx 낮을 때"]],
  custom: [['zscore(close, 50) 가 ±2 에서 복귀', "adx"], ['거래량 충격: zscore(log(volume), 50) * sign(close - open)', "ema 50"], ['효율 비율: (close - close[14]) / sum(abs(close - close[1]), 14)', "ema 100"], ['가격 백분위: rank(close, 100)', 'rank(volume, 50)'], ['추세 점수: (sign(close - ema(close,50)) + sign(ema(close,20) - ema(close,50))) / 2', "adx"]],
};
const f = (v, d = 2) => v == null || !Number.isFinite(+v) ? "?" : (+v).toFixed(d);
// 차트 요약(숫자 덤프 대신 판단에 필요한 6가지만)
export function chartBrief(snap) {
  const i = snap?.ind || {}, p = snap?.price, atrPct = i.atr?.value && p ? i.atr.value / p * 100 : null;
  const regime = (i.adx?.adx ?? 0) >= 25 ? "추세장" : (i.adx?.adx ?? 0) < 18 ? "횡보장" : "약한 추세";
  return `현재가 ${p ?? "?"} · ${regime}(ADX ${f(i.adx?.adx, 0)}) · RSI ${f(i.rsi?.value, 0)} · 슈퍼트렌드 ${i.supertrend?.trend > 0 ? "상승" : i.supertrend?.trend < 0 ? "하락" : "?"} · 볼린저 폭 ${f(i.bb?.width, 1)}% · 1봉 평균 변동(ATR) ${f(atrPct, 2)}%`;
}
/** 설계 지시문 만들기 → {sys, user}
 *  fam: "trend"|"revert" · custom: 커스텀 수식 지표를 핵심으로 · tried: 최근 실패(이유 포함) 문자열 배열 · learned: 데모에서 배운 것 · note: 대표 지시 · seed: 재료 순번 */
export function build({ fam = "trend", market, mname = "", iv = "1h", tfKo = "1시간", snap = null, tried = [], learned = "", note = "", custom = false, seed = 0, persona = "" } = {}) {
  const famKo = fam === "trend" ? "추세추종" : "역추세(되돌림)", key = custom ? "custom" : fam, ing = INGREDIENTS[key][seed % INGREDIENTS[key].length];
  const ex1 = EXAMPLES[fam], ex2 = custom ? EXAMPLES.custom : EXAMPLES[fam === "trend" ? "revert" : "trend"];
  const sys = `<role>
너는 ${persona || "코인 선물 매매법 설계자"}다. 백테스트 엔진이 그대로 실행할 전략 JSON 하나를 만든다.
</role>

<why>
이 JSON 은 사람이 읽지 않고 코드가 바로 실행한다. 형식이 하나라도 틀리면 통째로 버려진다.
조건이 4개 이상이면 과거에 한 번도 진입하지 못해 '거래 0건'으로 탈락한다. 그래서 단순하고 정확한 것이 가장 좋은 답이다.
</why>

<rules>
1. 출력은 JSON 객체 하나뿐이다. 설명 문장, 코드블록 표시, 주석을 붙이지 않는다.
2. "indicators" 는 2~4개. 각 지표는 {"id": 영문 소문자 이름, "type": 종류, 파라미터}.
3. "long_entry" 와 "short_entry" 는 둘 다 반드시 채운다. 각각 조건 2~3개(4개 이상 금지).
4. 조건 하나는 {"left": 값, "op": 연산자, "right": 값}. op 는 >  <  >=  <=  crosses_above  crosses_below 만 쓴다.
   long_entry 와 short_entry 에는 각각 crosses_above 또는 crosses_below 조건을 정확히 1개 넣어 '진입하는 순간'을 정한다. 나머지 조건은 > < 로 상태만 확인한다.
   (crosses 조건이 없으면 조건이 참인 동안 매 봉마다 다시 진입해 수수료로 계좌가 0 이 된다. 실제로 그렇게 탈락한 전략이 많았다.)
5. left/right 에는 indicators 에서 선언한 id(출력이 여러 개면 "id.출력"), close/open/high/low/volume, 숫자(문자열로 "30")만 쓴다. 선언하지 않은 이름은 쓰지 않는다.
6. "risk": {"stop_loss_pct": 0.5~2 사이, "take_profit_pct": 손절의 1.5~3배}. 레버리지는 코드가 손절폭에서 계산하므로 쓰지 않아도 된다.
7. 숏 조건은 롱 조건을 뒤집은 대칭으로 만든다.
8. "name" 은 한국어로 짧게 쓴다(한자·영어 문장 금지).
</rules>

<indicators>
출력이 하나(id 만 쓰면 됨): ema, sma, hma, rsi, roc, cci, mfi, willr, atr, highest, lowest, volume_sma — 파라미터 "length"
출력이 여럿(id.출력): macd → line, signal, hist · bb(length, mult) → upper, middle, lower · adx → adx, plus_di, minus_di · stoch, stochrsi → k, d · supertrend(length, mult) → trend (1=상승, -1=하락) · donchian, keltner → upper, middle, lower · ichimoku → tenkan, kijun
직접 만드는 지표: {"id": "x", "type": "custom", "expr": "수식"} — 수식에 close, volume, close[20](20봉 전), ema(x,n), sma(x,n), zscore(x,n), rank(x,n), sum(x,n), abs, sqrt, log, sign, ind("atr",{length:14}) 를 쓸 수 있다.
</indicators>

<examples>
<example 계열="${ex1 === EXAMPLES.trend ? "추세추종" : "역추세"}">
${J(ex1)}
</example>
<example 계열="${custom ? "커스텀 지표" : ex2 === EXAMPLES.trend ? "추세추종" : "역추세"}">
${J(ex2)}
</example>
</examples>`;
  const user = `<context>
시장: ${mname || market} (${market}) · ${tfKo}봉 · 코인 선물(롱·숏 모두)
지금 차트: ${snap ? chartBrief(snap) : "요약 없음"}
${tried.length ? `최근 우리 팀이 실패한 것(같은 실수 반복 금지):\n${tried.slice(-4).map(x => "- " + x).join("\n")}\n` : ""}${learned ? `데모(실제 시세)에서 배운 것:\n${learned}\n` : ""}${note ? `대표 지시(최우선): ${note}\n` : ""}</context>

<task>
${famKo} 계열의 새 전략 JSON 하나를 예시와 같은 형식으로 출력하라.
이번 재료: ${ing.join(" + ")}${custom ? " — 직접 만든 custom 수식 지표가 진입 조건의 핵심이어야 한다." : ""}
예시를 그대로 베끼지 말고, 이번 재료를 중심으로 지표 조합과 숫자를 새로 정한다. "symbol" 은 "${market}", "interval" 은 "${iv}".
출력 전에 스스로 확인: long_entry 와 short_entry 가 모두 있고, 조건이 각각 2~3개이며, 그중 crosses 조건이 정확히 1개씩이고, 조건에 쓴 이름이 전부 indicators 에 선언돼 있는가.
</task>`;
  return { sys, user };
}

// 🩹 모양 고치기 — 작은 모델이 자주 내는 '거의 맞는' JSON 을 엔진 형식으로 바로잡는다(뜻은 바꾸지 않음). 못 고치면 그대로 돌려준다.
//   실측에서 본 오류: indicators 가 배열이 아님 · logic 값이 all/any 가 아님 · 조건이 문자열("r > 30") · 연산자 별칭(crossover, gt …) · 조건 그룹이 배열 그대로
const OPS = { ">": ">", "<": "<", ">=": ">=", "<=": "<=", "=>": ">=", "=<": "<=", gt: ">", lt: "<", gte: ">=", lte: "<=", above: ">", below: "<", greater_than: ">", less_than: "<", crosses_above: "crosses_above", crosses_below: "crosses_below",
  cross_above: "crosses_above", cross_below: "crosses_below", crossover: "crosses_above", crossunder: "crosses_below", crossabove: "crosses_above", crossbelow: "crosses_below", cross_up: "crosses_above", cross_down: "crosses_below", crosses_over: "crosses_above", crosses_under: "crosses_below", rising: "rising", falling: "falling" };
function fixCond(c) {
  if (typeof c === "string") { const m = c.trim().match(/^(.+?)\s*(>=|<=|=>|=<|>|<|crosses_above|crosses_below|cross_above|cross_below|crossover|crossunder)\s*(.+)$/i); if (!m) return null; c = { left: m[1], op: m[2], right: m[3] }; }
  if (!c || typeof c !== "object") return null;
  const left = c.left ?? c.lhs ?? c.indicator ?? c.a, right = c.right ?? c.rhs ?? c.value ?? c.b, op = OPS[String(c.op ?? c.operator ?? c.comparison ?? "").toLowerCase().trim()];
  if (left == null || right == null || !op) return null;
  return { left: String(left).trim(), op, right: String(right).trim() };
}
function fixGroup(g, any = false) {
  if (g == null) return null;
  if (Array.isArray(g)) g = { logic: any ? "any" : "all", conditions: g };
  if (typeof g !== "object") return null;
  const arr = Array.isArray(g.conditions) ? g.conditions : Array.isArray(g.rules) ? g.rules : Array.isArray(g.conds) ? g.conds : (g.left != null ? [g] : []);
  const conds = arr.map(fixCond).filter(Boolean); if (!conds.length) return null;
  const lg = String(g.logic ?? g.operator ?? "").toLowerCase();
  return { logic: lg === "any" || lg === "or" ? "any" : lg === "all" || lg === "and" ? "all" : (any ? "any" : "all"), conditions: conds };
}
export function repair(j) {
  if (!j || typeof j !== "object") return j;
  const o = { ...(j.strategy && typeof j.strategy === "object" && !j.indicators ? j.strategy : j) };
  if (o.indicators && !Array.isArray(o.indicators) && typeof o.indicators === "object") o.indicators = Object.entries(o.indicators).map(([id, v]) => (v && typeof v === "object") ? { id, ...v } : { id, type: String(v) });
  if (Array.isArray(o.indicators)) o.indicators = o.indicators.filter(i => i && typeof i === "object").map(i => { const x = { ...i }; if (x.name && !x.id) x.id = x.name; if (x.period != null && x.length == null) x.length = x.period; if (x.params && typeof x.params === "object") { Object.assign(x, x.params); delete x.params; }
    if (x.id) x.id = String(x.id).toLowerCase().replace(/[^a-z0-9_]/g, "_"); if (x.type) x.type = String(x.type).toLowerCase(); delete x.name; delete x.period; return x; });
  for (const g of ["long_entry", "short_entry"]) { const f = fixGroup(o[g] ?? o[g.replace("_entry", "")] ?? null); if (f) o[g] = f; else delete o[g]; }
  for (const g of ["long_exit", "short_exit"]) { const f = fixGroup(o[g], true); if (f) o[g] = f; else o[g] = null; }
  if (o.risk && typeof o.risk === "object") { const r = { ...o.risk }; if (r.stop_loss != null && r.stop_loss_pct == null) r.stop_loss_pct = r.stop_loss; if (r.take_profit != null && r.take_profit_pct == null) r.take_profit_pct = r.take_profit; delete r.stop_loss; delete r.take_profit; o.risk = r; }
  return o;
}
