# GH Coin 기능 — 복붙용 독립 모듈 묶음

GH Coin에서 만든 핵심 기능들을 **다른 프로젝트에 그대로 떼어 쓸 수 있게** 모은 것입니다.
전부 **순수 JavaScript(ESM) · 외부 라이브러리 0개**. 브라우저와 Node 양쪽에서 돕니다.
(의존성: `lessons.js` 만 같은 폴더의 `ragstore.js` 를 씁니다. 나머지는 완전 독립.)

## 쓰는 법
파일을 복사해 `import` 하면 끝입니다.
```js
import { fuse } from "./selfai.js";
import { analyzeNews } from "./sentiment.js";
import { positionSize, kellyCriterion, riskReward } from "./rigor.js";
```

---

## 📄 파일별 기능 · API · 예시

### `rigor.js` — 트레이딩 리스크 계산기 (결정론적)
`positionSize(account,riskPct,entry,stop)` · `kellyCriterion(winRate,avgWin,avgLoss)` · `riskReward(entry,stop,target)` · `realizedPnl/unrealizedPnl` · `portfolioHeat(riskPcts,maxHeat)` · `correlation(a,b)`
```js
positionSize(10000, 1, 100, 95)   // → {shares:20, position_value:2000, ...}
kellyCriterion(55, 200, 100)      // → {full_kelly_pct:32.5, half_kelly_pct:16.25, ...}
riskReward(100, 95, 115)          // → {direction:"long", risk_reward_ratio:3}
```

### `attbacktest.js` — SMA 돌파 백테스트 + 계좌 복리
`simulateTrendStrategy(closes, {sma_window,stop_pct,target_r_multiple,max_hold_days,friction_pct})` · `aggregateResults({ticker:trades}, {risk_pct_per_trade,max_heat_pct})`
```js
const closes = [{date:"2024-01-01", close:"100"}, ...];           // 날짜 오름차순
const trades = simulateTrendStrategy(closes, {sma_window:20, stop_pct:5, target_r_multiple:2});
aggregateResults({BTC:trades}, {risk_pct_per_trade:1});           // → {n_trades, win_rate_pct, total_return_pct, ...}
```

### `sentiment.js` — 한국어 시장 심리(감정) 엔진
`score(text)` → 한 문장 극성 · `analyzeNews([texts])` → 종합 심리 0~100 + 판정 + 분포 · `verdictOf(p)` · `lexiconSize()`
```js
score("호재 급등 신고가 돌파")      // → {polarity:1, score:100, ...}
analyzeNews(["호재 급등","해킹 폭락"]) // → {score, verdict:"...", dist:{pos,neg,neu}, top:[...]}
```

### `selfai.js` — 앙상블 방향·확신도 (여러 신호 → 하나의 판단)
`fuse({ta, tfScores, ml, alpha, ai, sent})` → `{score,-1~1 · dir · label · confidence,0~95 · parts · reasons}` **(완전 독립)**
`analyze(candlesByTf)` → 캔들에서 바로 (이건 ta_rating·combo 지표 모듈이 추가로 필요 — fuse 만 떼어 쓰는 걸 권장)
```js
fuse({ ta:0.6, tfScores:[{tf:"60",score:0.5},{tf:"240",score:0.4}],
       ml:{prob:0.7,edge:"edge"}, sent:{polarity:0.3} });
// → {label:"강한 롱", score:0.58, confidence:82, parts:[...], reasons:[...]}
```

### `ragstore.js` — 가벼운 검색(RAG, TF-IDF + 한국어 2-그램)
`buildIndex(docs)` · `search(index, query, k)` · `tokenize(text)` · `contextOf(hits)`
```js
const idx = buildIndex([{id:"a", title:"레버리지", text:"..."}, ...]);
search(idx, "레버리지 청산 위험", 3);   // → [{id,title,text,score}, ...]
```

### `planner.js` — 플래너(할 일 목록 + 선행조건 + 중복 방지)
`planTodolist(state)` → 우선순위 의도 목록 · `pickNext(state)` → 지금 실행할 의도 · `capabilities(state)`
```js
planTodolist({ coins:[...], strategies:[...], alerts:[...], recent:[...] });
```

### `board.js` — 공유 보드(발견 축적 + 디듀프 + lineage)
`makeBoard(store)` → `.add(f)` `.recent(n)` `.forTarget(t)` `.count()` (store = {get(k,d),set(k,v)})
```js
const b = makeBoard(localStorageAdapter);
b.add({intent:"trend:BTC", job:"trend", target:"BTCUSDT", text:"상승 정렬"});
```

### `lessons.js` — 경험 학습(교훈 쌓기 + 강화 + 상황별 회상) · `ragstore.js` 필요
`makeLessons(store)` → `.learn(text,{job,ok})` `.recall(context,n)` `.top(n)`
```js
const L = makeLessons(store);
L.learn("비트코인 추세 상승일 때 돌파 봇 성과 좋음", {job:"bot"});
L.recall("지금 비트코인 돌파 어때");   // → 관련 교훈들
```

---

## 출처
각 기능이 참고/이식한 오픈소스는 `../gh-coin/THIRD_PARTY.md` 참고
(rigor·attbacktest ← ai-trader-team, sentiment ← day_trading_bot + KOME, lessons ← hermes-agent, planner/board ← ARTEX 설계, ragstore ← dify/anything-llm 개념 등).
