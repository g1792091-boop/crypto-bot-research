// 리서치 플래너 — Autumn-27/ARTEX 의 범용 멀티에이전트 설계(planner + 공유 todolist + 워커가 결과를 공유 보드에 축적)를
// '보안 공격(레드팀)용 기능은 전부 빼고' 코인 트레이딩 리서치에만 맞게 다시 만든 것. 그런 기능은 일절 없고, 쓰는 것은
// 기존 코인 데이터·백테스트·자체 AI 판단 같은 '우리 앱이 이미 하는 일'뿐이다. (출처·범위: THIRD_PARTY.md)
//
// ARTEX 개념 → 여기 대응:
//   · planner(상황 보고 다음 의도만 던짐)        → planTodolist(state): 지금 무엇을 리서치할지 우선순위 목록
//   · worker(의도 하나 받아 실제 도구로 실행)     → pickNext() 가 고른 intent 를 기존 job 으로 실행(coin-office plannerJob)
//   · 의존 있는 다단계(선행 → 후속)              → intent.deps (예: 봇 자동개선은 '활성 봇' 선행 필요)
//   · 중복/오순서 방지(공유 todolist)             → recent 키로 디듀프 + deps 충족 검사
//
// 순수 함수(상태 객체만 받음) → 테스트 쉽다.

const key = it => `${it.job}:${it.target || "-"}`;

// 상태에서 '충족된 선행조건' 집합을 만든다
export function capabilities(state = {}){
  const s = state.strategies || [], caps = new Set();
  if (s.some(x => x.status === "active")) caps.add("has_active_strategy");
  if (s.some(x => x.status === "active" && x.isBot)) caps.add("has_active_bot");
  if (s.some(x => x.gateEligible && !x.live)) caps.add("has_gate_ready");
  if ((state.coins || []).length) caps.add("has_coins");
  return caps;
}

// 지금 할 리서치 의도 목록(우선순위 내림차순). 각 intent: {id, job, target, targetName, why, prio, deps[]}
export function planTodolist(state = {}){
  const coins = state.coins || [], strat = state.strategies || [], alerts = state.alerts || [], out = [];
  const add = (job, prio, deps, why, target = "", targetName = "") => out.push({id: `${job}:${target || "all"}`, job, target, targetName, why, prio, deps});

  // 1) 이벤트 구동(가장 높음): 성과 악화 경보 → 그 전략 점검/최적화
  for (const a of alerts.slice(0, 3)) add("opt", 9, ["has_active_strategy"], `경보: ${a.kind || "성과 악화"} → 최적화로 점검`, a.target || "", a.targetName || a.target || "");

  // 2) 관문 통과했는데 아직 실거래 연결 안 된 전략 → 실거래 연결 점검(사용자 승인 필요, 주문은 안 냄)
  if (capabilities(state).has("has_gate_ready")) add("promote", 7, ["has_gate_ready"], "관문 통과 전략 실거래 승격 심사(연결은 사용자 승인)", "", "");

  // 3) 전략이 하나도 없으면 먼저 만든다(모든 후속의 뿌리)
  if (!capabilities(state).has("has_active_strategy")) add("dev", 8, ["has_coins"], "데모 전략이 없음 → 매매법 개발·백테스트부터", "", "");

  // 4) 활성 봇이 있으면 자동개선(선행: 봇 존재)
  add("botopt", 5, ["has_active_bot"], "데모 봇 보조지표·위험값 자동개선(하이퍼옵트)", "", "");
  // 5) 활성 전략이 있으면 성과 이동 감지
  add("drift", 4, ["has_active_strategy"], "데모 전략 성과 이동 감지(런 차트)", "", "");

  // 6) 상시 리서치(선행 없음): 자체 AI 순위 → 변동성 큰 코인 추세 → 종합 타점 → 지표 → 봇 전략 발굴
  add("selfai", 6, [], "자체 AI 데스크 방향·확신도 순위", "", "");
  const topCoin = coins[0];
  if (topCoin) add("trend", 3, ["has_coins"], `${topCoin.ko} 다중 시간대 추세 점검`, topCoin.sym, topCoin.ko);
  add("combo", 3, ["has_coins"], "실시간 종합 지표 타점", "", "");
  add("bot", 2, ["has_coins"], "새 봇 전략 백테스트 발굴", "", "");
  add("ind", 1, ["has_coins"], "보조지표 해석 갱신", "", "");

  // 최근에 한 것은 우선순위를 낮춘다(공유 todolist 디듀프)
  const recent = new Set(state.recent || []);
  for (const it of out) if (recent.has(key(it))) it.prio -= 5;
  out.sort((a, b) => b.prio - a.prio || a.job.localeCompare(b.job));
  return out;
}

// todolist 에서 '지금 바로 실행 가능한' 최우선 의도를 고른다: 선행조건 충족 + 최근 안 한 것
export function pickNext(state = {}, {avoid = []} = {}){
  const todolist = planTodolist(state), caps = capabilities(state), recent = new Set([...(state.recent || []), ...avoid]);
  for (const it of todolist){
    if (!(it.deps || []).every(d => caps.has(d))) continue;   // 선행조건 미충족 → 건너뜀(오순서 방지)
    if (recent.has(key(it)) && it.prio < 6) continue;         // 최근 한 저우선 작업은 건너뜀(중복 방지)
    return it;
  }
  return todolist.find(it => (it.deps || []).every(d => caps.has(d))) || null;
}

export const intentKey = key;
