// 🧠 뉴트론 브리지 — 앱 안의 뇌(자체 뇌 + 뉴럴 데스크 + 에이전트 팀 판정)를 디스크로 내보내
//   ① Claude Code / Claudian(옵시디언) 이 MCP 로 읽고  ② 옵시디언 볼트(마크다운·위키링크)로 보고  ③ 받은 편지함으로 제안을 돌려받는다.
// 폴더: 문서/GHNano 사무실/neutron (state.json · inbox.jsonl) + 문서/GHNano 사무실/GHCoin 뇌 (옵시디언 볼트)
// 안전: 내보내기는 읽기 전용 사본. 받은 편지함은 '지식 메모 · 매매법 실험 제안 · 팀 과제' 세 가지만 받는다 — 주문·설정 변경·키는 절대 없음.
import { LAUNCHER, codeCall, webGet } from "../nuri-ai/engine.js";
import { onLeader } from "./leader.js";

const VAULT = "GHCoin 뇌", DIR = "neutron";
const VERDICT_KEYS = { riskVerdict: "coinRiskVerdict", taRating: "coinTARating", patterns: "coinPatterns", alpha: "coinAlpha", data: "coinDataV", ml: "coinML", selfAI: "coinSelfAI", calendar: "coinCalendar", sentiment: "coinSentiment", liveEntry: "coinLiveEntry", swingAudit: "coinSwingAudit", dailyTrend: "coinDailyTrend", researchFail: "coinResearchFail" };
const readJ = (k, d = null) => { try { return JSON.parse(localStorage.getItem(k) || "null") ?? d; } catch (e) { return d; } };
const W = (path, content) => codeCall("write", { ws: "office", path, content });
const day = (t = Date.now()) => new Date(t).toLocaleDateString("sv-SE");
let started = false, lastErr = "", stats = { exported: 0, vault: 0, inbox: 0, at: 0 };
export const neutronStatus = () => ({ on: started, ...stats, err: lastErr, vaultName: VAULT, path: (() => { try { return localStorage.getItem("neutronPath") || ""; } catch (e) { return ""; } })() });

// ── 상태 사본 ──
export async function snapshot() {
  const N = await import("./neural.js"), BR = await import("./brain.js"), ENG = await import("./strategies.js");
  const s = N.state(), brain = BR.dump();
  let book = []; try { const P = await import("../nuri-ai/paper.js"); book = (await P.loadBook()).strategies.map(x => ({ id: x.id, name: x.name, market: x.market, tf: x.tf, status: x.status, author: x.author, lane: x.lane || "std", trades: (x.trades || []).length, equity: Math.round(P.equityOf(x)), lev: x.spec?.risk?.leverage ?? null, sl: x.spec?.risk?.stop_loss_pct ?? null, tp: x.spec?.risk?.take_profit_pct ?? null })); } catch (e) {}
  let limits = null; try { const L = await import("../nuri-ai/live.js"); const c = L.liveCfg?.() || {}; limits = { limits: c.limits || null, halted: !!c.halted }; } catch (e) {}
  const verdicts = Object.fromEntries(Object.entries(VERDICT_KEYS).map(([k, key]) => [k, readJ(key)]));
  try { const O = await import("./coin-office.js"); verdicts.missions = O.missionState();
    const log = (await O.loadLog?.()) || [], bl = O.backlog?.() || [];
    let store = null; try { store = await O.storageProbe?.(); } catch (e) {}
    verdicts.office = { store, diagTxt: readJ("coinDiagTxt") || {}, missionLogs: (O.missions?.() || []).slice(-5).map(m => ({ text: m.text.slice(0, 60), job: m.job, status: m.status, attempts: m.attempts, log: (m.log || []).map(x => `${x.job}: ${String(x.text).slice(0, 220)}`) })), diag: Object.fromEntries(Object.entries(readJ("coinDiag") || {}).map(([k, v]) => [k, Math.round((Date.now() - v) / 1000)])), cycle: O.cycleState?.(), nextCycleSec: Math.round((O.nextCycleIn?.() || 0) / 1000), paused: O.officePaused?.() || 0, backlogTodo: bl.filter(x => x.status === "todo").length, backlogDoing: bl.filter(x => x.status === "doing").length,
      labErr: readJ("coinLabErr"), labI: +localStorage.getItem("coinLabI") || 0, lab: log.filter(e => /실험 리그/.test(String(e.text || e.title || ""))).slice(-5).map(e => ({ t: e.t, text: String(e.text || e.title || "").slice(0, 260) + (e.note ? " | " + String(e.note).slice(0, 200) : "") })),
      recent: log.slice(-14).map(e => ({ t: e.t, ch: e.ch, kind: e.kind, text: String(e.text || e.title || e.name || "").replace(/\s+/g, " ").slice(0, 150) })) }; } catch (e) {}
  verdicts.marketEntry = readJ("coinMarketEntry");
  // 📖 차트 터미널 읽기(지금 화면의 종목·봉·지표·그린 선) → MCP neutron_chart_* 도구가 읽음. 비교표는 10분마다.
  try { const CR = await import("../nuri-ai/terminal/chartread.js"), R = await CR.readChart(); verdicts.chart = { read: CR.readText(R), report: CR.reportJSON(R) };
    let cmp = readJ("coinChartCompare"); if (!cmp || Date.now() - cmp.t > 10 * 60e3) { cmp = await CR.compare(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT"], "1h"); try { localStorage.setItem("coinChartCompare", JSON.stringify(cmp)); } catch (e) {} }
    verdicts.chartCompare = cmp; } catch (e) {}
  verdicts.traderDecisions = (readJ("coinTraderDecisions") || []).slice(0, 12); verdicts.stratReviews = readJ("coinStratReviews") || [];
  return {
    v: 1, t: Date.now(), app: "GH Coin",
    neural: { equity: s.equity, bankroll: s.bankroll, pnl: s.pnl, drawdown: s.drawdown, fills: s.fills, winRate: s.winRate, heat: s.heat, dayPnl: s.dayPnl, riskMode: s.riskMode,
      positions: (s.pos || []).map(p => ({ sym: p.sym, side: p.side > 0 ? "long" : "short", lev: p.lev, entry: p.entry, sl: p.sl, tp: p.tp ?? null, running: !!p.run, strategy: p.name, riskPct: p.riskPct })),
      openAll: s.openAll || [], score: s.score || null, aiAuto: s.aiAuto || null,
      mood: s.mood || null, fng: s.fng || null, hold: s.hold ? { ver: s.hold.book?.ver, rules: s.hold.rules, eval: s.hold.eval, log: s.hold.log, prop: s.hold.prop } : null, adj: s.adj ? { stat: s.adj.stat, kind: s.adj.kind, log: s.adj.log, off: s.adj.off, schema: s.adj.schema } : null,
      regime: s.regime, news: s.news, review: s.review, review2: s.review2, research: s.research, whale: s.whale, cfg: s.cfg, dayN: s.dayN, calls: s.calls || null, engine: (s.engine || []).slice(0, 40), setups: s.setups || [], evo: s.evo, trades: (s.trades || []).slice(0, 80), feed: (s.feed || []).slice(0, 20) },
    brain, verdicts, demo: book,
    policy: { framework: ENG.FW, live: limits, rules: ["AI 는 주문하지 않는다(주문은 live.js 코드가 한도·승인 안에서만)", "실거래 기본 꺼짐 · 테스트넷 먼저", "최소 20배·손절 ≤ 청산거리 40%·1회 리스크 0.5~1%·동시 리스크 4%·일일 손실 3%"] },
    lib: { strategies: ENG.LIB.map(r => ({ key: r.key, name: r.name, cat: r.cat, tf: r.tf, rr: r.rr })), filters: Object.fromEntries(Object.entries(ENG.FILTERS).map(([k, f]) => [k, f.ko])) },
  };
}

// ── 옵시디언 볼트 (위키링크로 서로 연결된 노트) ──
const coinOf = m => (m.coin || "").replace(/USDT$/, "").toUpperCase();
const esc = t => String(t ?? "").replace(/\|/g, "/").replace(/\n/g, " ");
export function vaultNotes(S) {
  const now = new Date(S.t).toLocaleString("ko-KR"), n = S.neural, B = S.brain, out = {};
  const coins = [...new Set(["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", ...B.mem.map(coinOf).filter(Boolean)])];
  const types = [...new Set(B.mem.map(m => m.type || "관찰"))];
  out["00 홈.md"] = `# 🧠 GHCoin 뇌 (뉴트론)\n_자동 생성 · ${now} · 앱이 10분마다 다시 씀 (직접 고친 내용은 덮어써짐 → 메모는 [[받은 편지함 사용법]] 참고)_\n\n`
    + `## 지금\n- 자본 $${n.equity} (시작 $${n.bankroll}) · 낙폭 ${n.drawdown}% · 거래 ${n.fills}회 승률 ${n.winRate}% · 동시 리스크 ${n.heat}%\n- 뇌 지능 ${B.iq.score}/100 (정확도 ${B.iq.acc}% · ${B.iq.n}판) · 기억 ${B.mem.length}개\n\n`
    + `## 지도\n- 코인: ${coins.map(c => `[[코인/${c}|${c}]]`).join(" · ")}\n- 지식: ${types.map(t => `[[지식/${t}|${t}]]`).join(" · ")}\n- 뇌: [[뇌/핵심 규칙·교훈·추천 채점]] · 프롬프트: [[프롬프트/차트 분석 프롬프트]]
- 📓 매매일지: [[매매일지/00 매매일지 대시보드]] · [[매매일지/열린 포지션]] · 내 거래 기록은 [[매매일지/내 거래/사용법]]
- 관망·감정: [[뇌/관망 규칙·감정·조정 채점]]
- 매매법: [[매매법/전략 엔진]] · [[매매법/매매법 진화]] · [[매매법/검증된 셋업]]\n- 리스크: [[리스크/정책]] · [[리스크/학습된 리스크·시간대]]\n- 에이전트 팀: [[에이전트팀/데모 전략]] · [[에이전트팀/팀 판정]]\n- 일지: [[일지/${day(S.t)}]]\n- ✍ 내가 쓰는 메모(→ 뇌가 학습): [[내 메모/사용법]]\n`;
  for (const t of types) out[`지식/${t}.md`] = `# ${t}\n[[00 홈]]\n\n` + B.mem.filter(m => (m.type || "관찰") === t).slice(0, 120).map(m => `- ${m.text} ${coinOf(m) ? `[[코인/${coinOf(m)}|${coinOf(m)}]]` : ""}${m.regime ? ` #${String(m.regime).replace(/\s/g, "_")}` : ""} _(가중 ${m.w}·확인 ${m.hits}회·${m.model || "?"})_`).join("\n");
  for (const c of coins) { const sym = c + "USDT", id = c.toLowerCase(), rg = n.regime?.[sym], V = S.verdicts;
    const vd = [["리스크 결정표", V.riskVerdict?.[id]?.act], ["TA 평점", V.taRating?.[id]?.label], ["차트 패턴", V.patterns?.[id] ? `${V.patterns[id].dir > 0 ? "상승" : V.patterns[id].dir < 0 ? "하락" : "중립"} ${(V.patterns[id].names || []).join(",")}` : null],
      ["알파 순위", V.alpha?.[id] ? `${V.alpha[id].rank}/${V.alpha[id].n}` : null], ["자체 AI", V.selfAI?.[id] ? `${V.selfAI[id].dir > 0 ? "롱" : V.selfAI[id].dir < 0 ? "숏" : "중립"} ${V.selfAI[id].conf}%` : null], ["ML", V.ml?.[id] ? `상승확률 ${Math.round((V.ml[id].prob ?? 0) * 100)}%` : null]].filter(x => x[1] != null);
    out[`코인/${c}.md`] = `# ${c}\n[[00 홈]]\n\n- 국면: ${rg ? `${rg.label} (ADX ${rg.adx ?? "?"} · 4H 추세 ${rg.htf > 0 ? "상승" : rg.htf < 0 ? "하락" : "중립"})` : "판단 전"}\n${vd.map(([k, v]) => `- ${k}: ${esc(v)}`).join("\n")}\n\n## 기억\n`
      + (B.mem.filter(m => coinOf(m) === c).slice(0, 40).map(m => `- (${m.type}) ${m.text} → [[지식/${m.type}|${m.type}]]`).join("\n") || "- (아직 없음)"); }
  out["매매법/전략 엔진.md"] = `# 전략 엔진 (자체 백테스트 + 실전 최근 20건)\n[[00 홈]] · 실전 기준: 기대값 > +0.1R\n\n| 상태 | 매매법 | 봉 | 기대값 | 건수 | 승률 | 손익비 |\n|---|---|---|---|---|---|---|\n`
    + (n.engine || []).map(e => `| ${e.active ? "✅ 실전" : e.paused ? "⏸ 정지" : "대기"} | ${esc(e.name)} | ${e.tf} | ${e.mean}R | ${e.n} | ${e.wr}% | 1:${e.rr} |`).join("\n");
  out["매매법/매매법 진화.md"] = `# 🧬 매매법 진화 (개선·수정·조합)\n[[00 홈]] · 채택 ${n.evo?.n ?? 0}개 · 앞 70% 선택 → 뒤 30% 검증 통과만\n\n` + (n.evo?.log || []).map(L => `## ${new Date(L.t).toLocaleString("ko-KR")}\n변형 ${L.tested}개 → 학습구간 통과 ${L.passedIS} → 채택 ${(L.adopted || []).length}\n` + (L.adopted || []).map(a => `- [${a.src}] ${a.name}: 원본 ${a.base}R → 검증 ${a.oos}R (${a.n}건)`).join("\n")).join("\n\n");
  out["매매법/검증된 셋업.md"] = `# 검증된 셋업 순위 (기대값 × 승률 × 신뢰도)\n[[00 홈]]\n\n| 순위 | 매매법 | 봉 | 점수 | 기대값 | 승률 | 건수 |\n|---|---|---|---|---|---|---|\n` + (n.setups || []).map((x, i) => `| ${i + 1} | ${esc(x.name)} | ${x.tf} | ${x.score} | ${x.mean}R | ${x.wr}% | ${x.n} |`).join("\n");
  const P = S.policy;
  out["리스크/정책.md"] = `# 리스크 정책 (읽기 전용 — 코드에 고정, AI 가 바꿀 수 없음)\n[[00 홈]]\n\n${P.rules.map(r => "- " + r).join("\n")}\n\n## 청산공식 프레임워크\n\`\`\`json\n${JSON.stringify(P.framework, null, 2)}\n\`\`\`\n## 실거래 한도 (live.js)\n\`\`\`json\n${JSON.stringify(P.live, null, 2)}\n\`\`\``;
  const hours = Object.entries(B.hours || {}).filter(([, h]) => h.n >= 3).map(([hr, h]) => `| ${hr}시 | ${h.n} | ${Math.round(h.wins / h.n * 100)}% | ${h.pnl.toFixed(2)} |`).join("\n");
  out["리스크/학습된 리스크·시간대.md"] = `# 학습된 리스크·시간대\n[[00 홈]] · [[리스크/정책]]\n\n## 시간대별 성적\n| 시간 | 거래 | 승률 | 손익$ |\n|---|---|---|---|\n${hours || "| — | | | |"}\n\n## 손절 함정 (비슷한 자리 회피)\n` + ((B.traps || []).slice(0, 30).map(t => `- ${esc(t.coin || "")} ${esc(t.regime || "")} ${t.dir > 0 ? "롱" : "숏"} ROE ${t.roe ?? ""}`).join("\n") || "- (없음)");
  { const mem = B.mem || [], st = B.st || {}, C = n.calls || {}, ln = (t) => mem.filter(m => m.type === t).slice(0, 12).map(m => `- ${esc(m.text)} _(강도 ${m.w} · ${m.hits}회)_`).join("\n") || "- 아직 없음";
    { const H = n.hold, M = n.mood, A = n.adj, NL = "\n";
      out["뇌/관망 규칙·감정·조정 채점.md"] = `# 🧘 관망 규칙집 · 🎭 감정 · 🗂 익절·손절 조정${NL}[[00 홈]]${NL}${NL}`
        + (M ? `## 데스크 감정 (코드 계산)${NL}- 공포 ${M.fear}/10 · 탐욕 ${M.greed}/10 · 피로 ${M.fatigue}/10(${M.L}연패) · 확신 ${M.conf}/10${n.fng ? ` · 공포탐욕지수 ${n.fng.v}(${n.fng.label}, 어제 ${n.fng.y ?? "?"})` : ""}${NL}${(M.notes || []).map(x => "- " + x).join(NL)}${NL}${NL}` : "")
        + (H ? `## 관망 규칙집 v${H.ver}${NL}${(H.rules || []).map(r => `- ${r.on ? "✅" : "⬜"} ${r.on ? r.text : r.label}${r.score?.n ? ` (관망 채점: 손절 먼저 ${r.score.right}/${r.score.n})` : ""}`).join(NL)}${NL}${NL}`
          + (H.eval ? `지난 점검: 데스크 재연 ${H.eval.base.all.n}건 평균 ${H.eval.base.all.mean}R · 전반 ${H.eval.base.h1.mean} / 후반 ${H.eval.base.h2.mean}${NL}${NL}` : "")
          + `### 변경 이력${NL}${(H.log || []).map(x => `- ${new Date(x.t).toLocaleString("ko-KR")} v${x.ver} ${x.kind} (${x.src}): ${x.e} — ${x.why}`).join(NL) || "- 아직 없음"}${NL}${NL}` : "")
        + (A ? `## 익절·손절 조정 채점 (조정 안 했다면과 비교한 ΔR)${NL}${Object.entries(A.stat || {}).map(([k, v]) => `- ${k}: ${v.n}건 누적 ${v.dR}R`).join(NL) || "- 아직 없음"}${A.off ? NL + "- ⛔ AI 가격 조정 일시 중지 중(손해 누적)" : ""}${NL}` : ""); }
    out["뇌/핵심 규칙·교훈·추천 채점.md"] = `# 🧠 뇌가 진입 전에 쓰는 것\n[[00 홈]] · 누적: 교훈 ${st.lessons || 0} · 함정 ${st.traps || 0} · 승격 ${st.promoted || 0} · 진입 차단 ${st.avoided || 0} · 리스크 절반 ${st.softened || 0} · 망각 ${st.forgot || 0}\n\n## 핵심 규칙 (같은 결과 3회↑)\n${ln("핵심")}\n\n## 교훈\n${ln("교훈")}\n\n## ⚡ 손매매 추천 채점 (시장가 · 실시간 진입)\n익절1 먼저 ${C.wr ?? "—"}% · 채점 ${C.done || 0}건 · 합계 ${C.sumR || 0}R · 추적 중 ${C.open || 0}\n\n| 코인 | 방향 | 출처 | 등급 | 결과 | R |\n|---|---|---|---|---|---|\n`
      + (C.list || []).map(c => `| ${c.ko} | ${c.side > 0 ? "롱" : "숏"} | ${c.src} | ${c.grade || ""} | ${c.res || "추적 중"} | ${c.R ?? ""} |`).join("\n"); }
  out["프롬프트/차트 분석 프롬프트.md"] = `# 차트 분석 프롬프트 (Claude Code · Claudian · OpenClaw 에서 그대로 붙여 쓰기)
[[00 홈]] · 숫자는 전부 GH Coin 앱이 봉 데이터에서 계산한 값이다(이미지 판독 아님). 앱이 켜져 있어야 최신이다.

## 1. 내 차트 읽기
\`\`\`xml
<task>
neutron_chart_read 로 내 차트를 읽고 다음을 알려줘:
1. 현재 가격, 타임프레임
2. 표시된 모든 지표와 실시간 값
3. 차트의 선·라벨 레벨 (높은 순)
4. 최근 가격 흐름 한 줄 요약
도구가 준 숫자만 쓰고, 없는 값은 "없음"이라고 말해줘.
</task>
\`\`\`

## 2. 구조화 JSON 리포트
\`\`\`xml
<task>
neutron_chart_report 결과를 그대로 JSON 으로 출력해줘 (키: symbol, timeframe, chart_type, last_price, change_pct_100_bars, key_levels_from_pine, active_indicators, screenshot_path). 설명은 붙이지 마.
</task>
\`\`\`

## 3. 멀티 심볼 비교
\`\`\`xml
<task>
neutron_chart_compare 로 BTC, ETH, SOL 을 1시간 차트에서 비교해줘. 각각 마지막 가격 · 100봉 변화율(%) · RSI(14) · 거래량 확인 여부를 표로.
</task>
\`\`\`

## 4. 시니어 트레이더 결정
\`\`\`xml
<role>너는 시니어 암호화폐 파생상품 트레이더다.</role>
<task>
neutron_trader_decisions 의 최근 결정과 neutron_live_entry · neutron_chart_read 를 읽고, 그 결정이 운영 규칙(레짐 판단 → 편향 점검 → 포지션 크기 → ATR 손절·손익비 1:2 → 추적 손절·부분 익절·펀딩비 → 청산 조건)을 지켰는지 점검해줘. 어긋난 곳이 있으면 neutron_log_note 로 교훈을 남겨줘. 주문 지시는 하지 마.
</task>
\`\`\`
새 결정을 내게 하려면 앱 채팅에 "비트코인 트레이더 결정 해줘" 또는 차트 터미널 [📖 차트 AI → 트레이더 결정].

## 5. 전략 분석 5항목
\`\`\`xml
<task>
neutron_strategy_review 의 측정값으로 전략을 평가해줘.
</task>
<analysis_framework>
1. 시장 레짐 적합성: 추세장/횡보장/고변동성장 중 어디에 적합한가
2. 리스크 노출: 레버리지, 집중도, 꼬리 위험의 약점
3. 과최적화 가능성: 값 개수 대비 거래 수
4. 실행 현실성: 슬리피지, 유동성, 거래소 제약
5. 개선 방향: 레짐 필터, 앙상블, 동적 사이징 → 시험해 볼 만하면 neutron_propose_experiment 로 제안
</analysis_framework>
\`\`\`

## 요청문을 잘 쓰는 법
- 명시적으로: "차트 분석해줘" 대신 "RSI(14)와 최근 100봉 변화율로 과매수 여부와 거래량 확인 여부를 알려줘"
- 이유를 말해 주기: "목록 말고 문단으로 — 읽기 편해서"
- 태그로 나누기: \`<task>\` \`<context>\` \`<output_format>\`
- 예시 2~3개 붙이기
`;
  out["에이전트팀/데모 전략.md"] = `# 에이전트 팀 데모 전략\n[[00 홈]]\n\n| 상태 | 전략 | 코인 | 봉 | 거래 | 평가금 | 레버 | 손절/익절 | 개발 |\n|---|---|---|---|---|---|---|---|---|\n` + S.demo.map(d => `| ${d.status} | ${esc(d.name)} | [[코인/${String(d.market).replace(/USDT$/, "")}\\|${d.market}]] | ${d.tf} | ${d.trades} | ${d.equity} | ${d.lev ?? "—"} | ${d.sl ?? "—"}/${d.tp ?? "—"} | ${esc(d.author)} |`).join("\n");
  out["에이전트팀/팀 판정.md"] = `# 팀 판정 (진입 관문이 실제로 읽는 값)\n[[00 홈]]\n\n` + Object.entries(S.verdicts).map(([k, v]) => `## ${k}\n\`\`\`json\n${JSON.stringify(v, null, 1)?.slice(0, 1500)}\n\`\`\``).join("\n");
  const todays = (n.trades || []).filter(t => day(t.t || t.t1 || S.t) === day(S.t));
  out[`일지/${day(S.t)}.md`] = `# 거래 일지 ${day(S.t)}\n[[00 홈]]\n\n` + (todays.map(t => `- ${t.ko || t.sym} ${t.side > 0 ? "롱" : "숏"} ${t.lev ?? ""}x · ${esc(t.name || t.strategy || "")} · ${t.why || ""} · ${t.pnl >= 0 ? "+" : ""}${(+t.pnl || 0).toFixed(2)}$ (${(+t.R || 0).toFixed(2)}R)`).join("\n") || "- 오늘 거래 없음") + `\n\n## 최근 활동\n` + (n.feed || []).slice(0, 15).map(f => `- ${esc(f.text)}`).join("\n");
  out["받은 편지함 사용법.md"] = `# 받은 편지함 (Claude Code · Claudian → 앱)\n[[00 홈]]\n\n이 볼트의 노트는 앱이 다시 쓰므로, 앱에 전하고 싶은 것은 뉴트론 MCP 도구로 보낸다:\n- \`neutron_log_note\` — 지식 메모 → 자체 뇌에 학습\n- \`neutron_propose_experiment\` — 매매법 개선·수정·조합 실험 → 다음 자체 백테스트에서 검증, 통과해야 채택\n- \`neutron_add_task\` — 에이전트 팀 과제\n\n주문·설정 변경·키 관련 요청은 받지 않는다(안전 규칙).`;
  Object.assign(out, journalNotes(S));
  return out;
}

// ══ 📓 매매일지 (옵시디언) — 거래마다 '결정 기록' 노트 + 일간·주간 복기 + 대시보드 ══
//   개념 출처(코드 복사 없음): Decision Log 스킬(매수 논리·반증 조건·손절가를 진입 때 남겨 사후 합리화 방지) · Tradebook/LucrJournal/Journalit(거래 = 마크다운 노트 + 속성)
//   · TRADING-BRAIN 볼트 구조(trades/open·closed · performance · weekly) · alpha-ai-trader(복수 매매·과매매·연속 손실 같은 행동 점검).
//   노트 앞머리(속성)는 옵시디언 '속성'·Dataview 로 바로 표·필터를 만들 수 있게 영어 키로 쓴다. 플러그인이 없어도 본문 표로 읽힌다.
const fmtN = v => v == null || !Number.isFinite(+v) ? "—" : (+v >= 1000 ? Math.round(+v).toLocaleString() : (+v).toPrecision(6).replace(/\.?0+$/, ""));
const hm = t => new Date(t).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false });
const STY = { scalp: "스캘핑", day: "단타", swing: "스윙" };
export const tradeNotePath = t => { const d = new Date(t.t), ym = day(t.t).slice(0, 7), stamp = `${day(t.t)} ${String(d.getHours()).padStart(2, "0")}${String(d.getMinutes()).padStart(2, "0")}`; return `매매일지/거래/${ym}/${stamp} ${t.ko} ${t.side > 0 ? "롱" : "숏"}.md`; };
function weekOf(t) { const d = new Date(t); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() + 3 - ((d.getDay() + 6) % 7)); const w1 = new Date(d.getFullYear(), 0, 4); return `${d.getFullYear()}-W${String(1 + Math.round(((d - w1) / 864e5 - 3 + ((w1.getDay() + 6) % 7)) / 7)).padStart(2, "0")}`; }
// 행동 점검: 복수 매매(같은 코인 손실 청산 뒤 30분 안 재진입) · 과매매(하루 12회↑) · 연속 손실(3번↑)
function behavior(trades) {
  const T = [...trades].sort((a, b) => (a.opened || a.t) - (b.opened || b.t)), out = { revenge: [], streak: 0, maxStreak: 0, overtrade: [] };
  for (const x of T) { const prev = T.filter(y => y !== x && y.ko === x.ko && y.t <= (x.opened || x.t) && (x.opened || x.t) - y.t < 30 * 60e3 && (y.R || 0) < 0); if (prev.length) out.revenge.push(x); }
  let k = 0; for (const x of [...trades].sort((a, b) => a.t - b.t)) { k = (x.R || 0) < 0 ? k + 1 : 0; out.maxStreak = Math.max(out.maxStreak, k); }
  const byDay = {}; for (const x of trades) (byDay[day(x.opened || x.t)] ||= []).push(x); out.overtrade = Object.entries(byDay).filter(([, a]) => a.length >= 12).map(([d, a]) => `${d} ${a.length}회`);
  return out;
}
const sumUp = a => ({ n: a.length, wr: a.length ? Math.round(a.filter(t => (t.R || 0) > 0).length / a.length * 100) : 0, R: +a.reduce((x, t) => x + (t.R || 0), 0).toFixed(2), pnl: +a.reduce((x, t) => x + (t.pnl || 0), 0).toFixed(2) });
const row = t => `| ${hm(t.t)} | [[${tradeNotePath(t).replace(/\.md$/, "")}\|${t.ko} ${t.side > 0 ? "롱" : "숏"}]] | ${STY[t.style] || "—"} | ${esc(t.name || "")} | ${t.model ? esc(t.model) : "엔진"} | ${(+t.R || 0).toFixed(2)}R | ${(+t.pnl || 0) >= 0 ? "+" : ""}${(+t.pnl || 0).toFixed(2)}$ | ${esc(t.why || "")} |`;
const HEAD = `| 청산 | 거래 | 스타일 | 매매법 | 진입자 | R | 손익 | 청산 이유 |\n|---|---|---|---|---|---|---|---|\n`;
function journalNotes(S) {
  const n = S.neural || {}, trades = (n.trades || []).filter(t => t.t), out = {}, now = S.t;
  // 거래마다 결정 기록 노트
  for (const t of trades) {
    const res = (+t.R || 0) > 0.05 ? "익절" : (+t.R || 0) < -0.05 ? "손절" : "본전";
    out[tradeNotePath(t)] = `---\ndate: ${day(t.t)}\nopened: ${t.opened ? new Date(t.opened).toISOString() : ""}\nclosed: ${new Date(t.t).toISOString()}\ncoin: ${t.ko}\nside: ${t.side > 0 ? "long" : "short"}\nstyle: ${t.style || ""}\ntimeframe: ${t.tf || ""}\nstrategy: "${esc(t.name || "")}"\ntrader: "${t.model || "엔진"}"\nentry: ${t.entry}\nexit: ${t.exit}\nstop: ${t.sl0 ?? ""}\ntarget: ${t.tp0 ?? ""}\nleverage: ${t.lev ?? ""}\nR: ${t.R}\npnl: ${t.pnl}\nresult: ${res}\nexit_reason: "${esc(t.why || "")}"\ntags: [매매일지, ${t.ko}, ${STY[t.style] || "기타"}${t.model ? ", AI" : ", 엔진"}]\n---\n`
      + `# ${t.ko} ${t.side > 0 ? "롱" : "숏"} · ${res} ${(+t.R || 0) >= 0 ? "+" : ""}${(+t.R || 0).toFixed(2)}R\n[[매매일지/00 매매일지 대시보드|대시보드]] · [[매매일지/일간/${day(t.t)}|${day(t.t)} 일간]] · [[코인/${t.ko}|${t.ko}]]\n\n`
      + `## 결정 기록 (진입할 때의 생각)\n- **진입 근거**: ${esc(t.reason || "기록 없음(예전 거래)")}${t.note ? `\n- **승인·메모**: ${esc(t.note)}` : ""}\n- **무효 조건(이러면 틀린 것)**: ${t.sl0 != null ? `손절 ${fmtN(t.sl0)} 도달` : "손절가 도달(예전 거래라 가격 기록 없음)"} · 상위 추세가 반대로 돌면 조기 정리\n- **손절 / 익절**: ${t.sl0 != null ? `${fmtN(t.sl0)} / ${fmtN(t.tp0)}` : "기록 없음"} · 레버리지 ${t.lev ?? "?"}배 · 국면 ${esc(t.regime || "—")}\n\n`
      + `## 결과\n- 진입 ${fmtN(t.entry)} → 청산 ${fmtN(t.exit)} (${esc(t.why || "")}) · ${(+t.R || 0).toFixed(2)}R · ${(+t.pnl || 0) >= 0 ? "+" : ""}${(+t.pnl || 0).toFixed(2)}$ · ROE ${t.roe ?? "—"}%\n\n## 복기 (직접 써도 됩니다 — 앱은 이 노트를 다시 쓰지 않습니다)\n- \n`;
  }
  // 열린 포지션
  const open = n.openAll || [];
  out["매매일지/열린 포지션.md"] = `# 열린 포지션 (데모)\n[[매매일지/00 매매일지 대시보드|대시보드]] · 갱신 ${new Date(now).toLocaleString("ko-KR")}\n\n` + (open.map(p => `## ${p.ko} ${p.side > 0 ? "롱" : "숏"} ${p.lev}배 · ${STY[p.style] || ""} · 지금 ${p.R ?? "?"}R\n- 진입자: ${esc(p.trader || "")} · 매매법: ${esc(p.name || "")} · ${new Date(p.t).toLocaleString("ko-KR")}\n- **진입 근거**: ${esc(p.why || "")}${p.note ? ` · ${esc(p.note)}` : ""}\n- **무효 조건**: 손절 ${fmtN(p.sl)}${p.be ? "(본절로 올림)" : ""} 도달 · 상위 추세 반전\n- 진입 ${fmtN(p.entry)} · 현재 ${fmtN(p.price)} · 익절 ${fmtN(p.tp)} · 처음 손절 ${fmtN(p.sl0)}\n`).join("\n") || "지금 열린 포지션 없음\n");
  // 일간 복기(최근 7일 중 거래가 있던 날)
  const days = [...new Set(trades.map(t => day(t.t)))].sort().slice(-7);
  for (const d of days) { const a = trades.filter(t => day(t.t) === d), s = sumUp(a), b = behavior(a);
    out[`매매일지/일간/${d}.md`] = `---\ndate: ${d}\ntrades: ${s.n}\nwinrate: ${s.wr}\nR: ${s.R}\npnl: ${s.pnl}\ntags: [매매일지, 일간]\n---\n# ${d} 매매 복기\n[[매매일지/00 매매일지 대시보드|대시보드]] · [[일지/${d}|그날 활동 일지]]\n\n`
      + `**${s.n}건 · 승률 ${s.wr}% · ${s.R >= 0 ? "+" : ""}${s.R}R · ${s.pnl >= 0 ? "+" : ""}${s.pnl}$**\n\n${HEAD}${a.map(row).join("\n")}\n\n`
      + `## 행동 점검\n- 복수 매매(같은 코인 손실 뒤 30분 안 재진입): ${b.revenge.length ? b.revenge.map(x => `${x.ko} ${hm(x.opened || x.t)}`).join(", ") : "없음"}\n- 가장 긴 연속 손실: ${b.maxStreak}번${b.maxStreak >= 3 ? " → 다음 24시간 휴식 규칙 작동" : ""}\n- 과매매(하루 12회↑): ${b.overtrade.join(", ") || "없음"}\n`; }
  // 주간 복기
  const weeks = [...new Set(trades.map(t => weekOf(t.t)))].sort().slice(-4);
  for (const w of weeks) { const a = trades.filter(t => weekOf(t.t) === w), s = sumUp(a), b = behavior(a), dayP = {}; for (const t of a) dayP[day(t.t)] = (dayP[day(t.t)] || 0) + (t.pnl || 0);
    const worst = Object.entries(dayP).sort((x, y) => x[1] - y[1])[0], bySt = Object.entries(STY).map(([k, ko]) => { const x = sumUp(a.filter(t => t.style === k)); return x.n ? `| ${ko} | ${x.n} | ${x.wr}% | ${x.R}R | ${x.pnl}$ |` : ""; }).filter(Boolean).join("\n");
    const ai = sumUp(a.filter(t => t.model)), en = sumUp(a.filter(t => !t.model));
    out[`매매일지/주간/${w}.md`] = `---\nweek: ${w}\ntrades: ${s.n}\nwinrate: ${s.wr}\nR: ${s.R}\npnl: ${s.pnl}\ntags: [매매일지, 주간]\n---\n# ${w} 주간 복기\n[[매매일지/00 매매일지 대시보드|대시보드]]\n\n**${s.n}건 · 승률 ${s.wr}% · ${s.R >= 0 ? "+" : ""}${s.R}R · ${s.pnl >= 0 ? "+" : ""}${s.pnl}$** · 가장 나쁜 날 ${worst ? `${worst[0]} ${worst[1].toFixed(2)}$` : "—"}\n\n`
      + `## 스타일별\n| 스타일 | 거래 | 승률 | R | 손익 |\n|---|---|---|---|---|\n${bySt || "| — | 0 | — | — | — |"}\n\n## AI 대 엔진\n- AI 가 들어간 거래: ${ai.n}건 · 승률 ${ai.wr}% · ${ai.R}R\n- 엔진 단독: ${en.n}건 · 승률 ${en.wr}% · ${en.R}R\n\n`
      + `## 행동 점검\n- 복수 매매 ${b.revenge.length}번 · 가장 긴 연속 손실 ${b.maxStreak}번 · 과매매 ${b.overtrade.length}일\n`; }
  // 대시보드
  const sc = n.score?.styles || {}, aa = n.aiAuto;
  out["매매일지/00 매매일지 대시보드.md"] = `# 📓 매매일지 대시보드 (GH Coin 데모)\n[[00 홈]] · [[매매일지/열린 포지션|열린 포지션]] · 갱신 ${new Date(now).toLocaleString("ko-KR")}\n\n`
    + `## 스타일별 성적표 (뉴럴 데스크와 같은 숫자)\n| 스타일 | 켜짐 | 실전 | 승률 | 평균 R | 손익 | 기대(최근 20건) | 표본외 | 지금 상태 |\n|---|---|---|---|---|---|---|---|---|\n`
    + Object.entries(sc).map(([k, x]) => `| ${esc(x.ko)} | ${x.on ? "✅" : "—"} | ${x.n} | ${x.wr ?? "—"}% | ${x.avgR ?? "—"} | ${x.pnl}$ | ${x.exp ?? "—"} | ${x.oos?.r ?? "—"} | ${esc(x.status)} |`).join("\n")
    + `\n\n## 🤖 AI 자율 진입\n${aa ? `${aa.n}건 · 승률 ${aa.wr ?? "—"}% · 평균 ${aa.avgR ?? "—"}R` + (aa.by || []).map(b => `\n- ${b.model}: ${b.n}건 · 평균 ${b.avgR}R · 승률 ${b.wr}%${b.paused ? " · 쉬는 중" : ""}`).join("") + (aa.last ? `\n- 마지막 판단: ${esc(aa.last.model)} ${esc(aa.last.ko)} — ${esc(aa.last.why)}` : "") : "아직 없음"}\n\n`
    + `## 최근 거래\n${HEAD}${trades.slice(0, 15).map(row).join("\n") || "| — | 거래 없음 | | | | | | |"}\n\n`
    + `## 복기 노트\n- 일간: ${days.slice().reverse().map(d => `[[매매일지/일간/${d}|${d}]]`).join(" · ") || "—"}\n- 주간: ${weeks.slice().reverse().map(w => `[[매매일지/주간/${w}|${w}]]`).join(" · ") || "—"}\n- 내 손매매 기록: [[매매일지/내 거래/사용법|사용법]] (여기에 쓰면 앱이 읽어 자체 뇌에 학습)\n\n`
    + `## Dataview 로 보기 (Dataview 플러그인이 있으면 표가 자동으로 그려집니다)\n\`\`\`dataview\nTABLE coin, side, style, trader, R, pnl, exit_reason FROM "매매일지/거래" SORT closed DESC LIMIT 30\n\`\`\`\n\`\`\`dataview\nTABLE length(rows) AS 거래, sum(rows.R) AS 합계R FROM "매매일지/거래" GROUP BY style\n\`\`\`\n`;
  return out;
}
// 옵시디언 '매매일지/내 거래' 폴더: 사용자가 직접 한 거래를 노트로 쓰면 읽어 자체 뇌에 학습(앱은 이 폴더를 덮어쓰지 않음)
const MYT = `${VAULT}/매매일지/내 거래`;
export const MY_TRADE_TEMPLATE = "---\n날짜: 2026-10-07\n코인: BTC\n방향: 롱\n진입: 85000\n손절: 84000\n익절: 87000\n청산: \n결과R: \n---\n# BTC 롱\n\n## 진입 근거\n- \n\n## 무효 조건(이러면 틀린 것)\n- \n\n## 복기\n- \n";
export async function ingestMyTrades() {
  let files = []; try { files = ((await codeCall("glob", { ws: "office", pattern: `${MYT}/**` })).files || []).filter(f => /\.md$/i.test(f) && !/(사용법|_템플릿)\.md$/.test(f)); } catch (e) { return 0; }
  let seen = {}; try { seen = JSON.parse(localStorage.getItem("neutronMyTradeSeen") || "{}"); } catch (e) {}
  const BR = await import("./brain.js"); let n = 0;
  for (const f of files.slice(0, 40)) {
    let t = ""; try { t = (await codeCall("raw", { ws: "office", path: f })).content || ""; } catch (e) { continue; }
    const h = hashOf(t); if (seen[f] === h) continue; seen[f] = h;
    const fm = {}; for (const m of (t.match(/^---\r?\n([\s\S]*?)\r?\n---/)?.[1] || "").matchAll(/^([^:\n]+):\s*(.*)$/gm)) fm[m[1].trim()] = m[2].trim();
    const coin = String(fm["코인"] || "").toUpperCase().replace(/USDT$/, ""), R = parseFloat(fm["결과R"]); if (!coin || !Number.isFinite(R)) continue;   // 결과가 적힌 거래만 학습
    const why = (t.match(/##\s*진입 근거\s*\r?\n([\s\S]*?)(\r?\n##|$)/)?.[1] || "").replace(/^[-*\s]+/gm, " ").trim().slice(0, 80), rev = (t.match(/##\s*복기\s*\r?\n([\s\S]*?)(\r?\n##|$)/)?.[1] || "").replace(/^[-*\s]+/gm, " ").trim().slice(0, 80);
    BR.learn({ type: R < 0 ? "교훈" : "패턴", coin, text: `[내 손매매] ${coin} ${fm["방향"] || ""} ${R >= 0 ? "+" : ""}${R}R — ${why || "근거 미기록"}${rev ? " · 복기: " + rev : ""}`, model: "내 거래", w: 1.8 }); n++;
  }
  try { localStorage.setItem("neutronMyTradeSeen", JSON.stringify(seen)); } catch (e) {}
  if (n) { stats.myTrades = (stats.myTrades || 0) + n; try { (await import("./coin-office.js")).addNote("hq", `📓 옵시디언 '내 거래' ${n}건을 자체 뇌에 학습`, "뉴트론"); } catch (e) {} }
  return n;
}

const CLAUDE_MD = `# GHCoin 뇌 (뉴트론) — Claude Code · Claudian 작업 규칙

이 폴더는 GH Coin 앱이 자동으로 쓰는 옵시디언 볼트다. 사용자와는 한국어로 짧게.

- 앱 상태·뇌 기억·팀 판정·매매법 성적은 **neutron MCP 도구**로 읽는다 (neutron_status, neutron_query_knowledge, neutron_top_setups, neutron_learned_winrates, neutron_team_verdicts, neutron_risk_policy, neutron_funding_scan, brain_search_notes, brain_read_note …).
- **차트는 이미지가 아니라 값으로 읽는다**: neutron_chart_read(내 차트: 가격·지표 실시간 값·그린 선 레벨·가격 흐름) · neutron_chart_report(고정 키 JSON) · neutron_chart_compare(멀티 심볼 비교) · neutron_trader_decisions(트레이더 결정 JSON 기록) · neutron_strategy_review(전략 분석 5항목). 바로 쓸 수 있는 요청문은 [[프롬프트/차트 분석 프롬프트]] 에 있다.
- 앱에 전할 것은 neutron_log_note / neutron_propose_experiment / neutron_add_task 로만 보낸다. 노트를 직접 고쳐도 10분 뒤 앱이 덮어쓴다.
- **안전 규칙(변경 금지)**: AI 는 주문하지 않는다. 실거래 기본 꺼짐·테스트넷 먼저. 주문·레버리지 한도·API 키를 바꾸는 요청은 거절한다.
- 숫자는 도구가 준 값만 쓰고, 수익은 확률로 말한다(보장 없음).
`;

export async function installFiles(force) {
  if (!force && sessionStorage.getItem("neutronInstalled")) return;
  // MCP 서버 스크립트를 볼트 안 숨김 폴더로 복사 (exe 사용자도 저장소 없이 쓰도록)
  for (const [src, dst] of [["mcp/neutron-mcp.mjs", ".neutron/mcp/neutron-mcp.mjs"], ["lib/fundscan.js", ".neutron/lib/fundscan.js"]]) {
    const r = await fetch(new URL("./" + src, import.meta.url), { cache: "no-store" }); if (r.ok) await W(`${VAULT}/${dst}`, await r.text()); }
  let abs = ""; try { const e = await codeCall("exec", { ws: "office", command: "cd", timeout: 5 }); abs = String(e.output || "").trim().split(/\r?\n/).pop(); } catch (e) {}
  const script = abs ? `${abs}\\${VAULT}\\.neutron\\mcp\\neutron-mcp.mjs` : "./.neutron/mcp/neutron-mcp.mjs";
  await W(`${VAULT}/.mcp.json`, JSON.stringify({ mcpServers: { neutron: { command: "node", args: [script], env: abs ? { NEUTRON_DIR: abs } : {} } } }, null, 2));
  await W(`${VAULT}/CLAUDE.md`, CLAUDE_MD);
  await W(`${MYT}/사용법.md`, "# 내 손매매 기록 (옵시디언 → GH Coin)\n[[매매일지/00 매매일지 대시보드|대시보드]]\n\n이 폴더에 직접 한 거래를 노트 하나씩 쓰면, GH Coin 이 10분 안에 읽어 자체 뇌에 학습합니다(손실은 '교훈', 이익은 '패턴'). 뉴럴 데스크 AI 가 진입을 승인할 때 이 기억을 함께 봅니다.\n\n- [[매매일지/내 거래/_템플릿|_템플릿]] 을 복사해서 쓰세요. 맨 위 속성 중 **코인 · 방향 · 결과R** 이 있어야 학습합니다(결과R 은 손절 한 번 = −1).\n- '진입 근거'와 '복기'를 쓰면 그 문장이 그대로 기억이 됩니다.\n- 앱은 이 폴더의 노트를 덮어쓰지 않습니다.\n");
  try { const has = await codeCall("raw", { ws: "office", path: `${MYT}/_템플릿.md` }).then(r => !!r.content).catch(() => false); if (!has) await W(`${MYT}/_템플릿.md`, MY_TRADE_TEMPLATE); } catch (e) {}
  await W(`${MEMO}/사용법.md`, "# 내 메모 (옵시디언 → 뇌)\n\n이 폴더에 노트를 쓰면 GH Coin 이 10분 안에 읽어 자체 뇌에 학습합니다.\n- 한 줄에 하나씩 쓰면 각각 기억이 됩니다 (예: '- BTC 는 미국장 개장 직후 가짜 돌파가 많다').\n- 손절·실패·주의·금지 같은 말이 있으면 '교훈'으로, 아니면 '지식'으로 저장합니다.\n- 코인 이름(BTC·ETH…)을 쓰면 그 코인 기억에 연결됩니다.\n- 이 폴더는 앱이 덮어쓰지 않습니다.\n");
  try { sessionStorage.setItem("neutronInstalled", "1"); localStorage.setItem("neutronPath", abs); } catch (e) {}
}

export async function exportState() { const S = await snapshot(); await W(`${DIR}/state.json`, JSON.stringify(S)); stats.exported++; stats.at = Date.now(); return S; }
export async function writeVault(S) { S ||= await snapshot(); const notes = vaultNotes(S);
  let seen = {}; try { seen = JSON.parse(localStorage.getItem("neutronJournalSeen") || "{}"); } catch (e) {}
  for (const [p, c] of Object.entries(notes)) { if (p.startsWith("매매일지/거래/")) { if (seen[p]) continue; seen[p] = 1; } await W(`${VAULT}/${p}`, c); }   // 거래 노트는 한 번만 쓴다(복기 칸을 사용자가 채울 수 있게)
  try { const ks = Object.keys(seen); if (ks.length > 600) for (const k of ks.slice(0, ks.length - 600)) delete seen[k]; localStorage.setItem("neutronJournalSeen", JSON.stringify(seen)); } catch (e) {}
  stats.vault++; stats.vaultAt = Date.now(); try { await ingestMemos(); } catch (e) {} try { await ingestMyTrades(); } catch (e) {} return Object.keys(notes).length; }

// ── 옵시디언 → 뇌: 볼트의 '내 메모' 폴더에 사용자·Claudian 이 쓴 노트를 읽어 자체 뇌에 학습 (바뀐 파일만, 앱은 이 폴더를 덮어쓰지 않음) ──
const MEMO = `${VAULT}/내 메모`;
const hashOf = t => { let h = 5381; for (let i = 0; i < t.length; i++) h = ((h << 5) + h + t.charCodeAt(i)) >>> 0; return h.toString(36); };
export async function ingestMemos() {
  let files = []; try { files = ((await codeCall("glob", { ws: "office", pattern: `${MEMO}/**` })).files || []).filter(f => String(f).startsWith(MEMO + "/") && /\.md$/i.test(f) && !/사용법\.md$/.test(f)); } catch (e) { return 0; }
  let seen = {}; try { seen = JSON.parse(localStorage.getItem("neutronMemoSeen") || "{}"); } catch (e) {}
  const BR = await import("./brain.js"); let n = 0;
  for (const f of files.slice(0, 30)) {
    let t = ""; try { t = (await codeCall("raw", { ws: "office", path: f })).content || ""; } catch (e) { continue; }
    const h = hashOf(t); if (seen[f] === h) continue; seen[f] = h;
    const title = (t.match(/^#\s+(.+)$/m)?.[1] || f.split("/").pop().replace(/\.md$/i, "")).trim();
    const coin = (title + " " + t).match(/\b(BTC|ETH|SOL|XRP|DOGE|BNB)\b/i)?.[1]?.toUpperCase() || "";
    const lines = t.split(/\r?\n/).filter(l => !/^\s*(#|\||```|---)/.test(l)).map(l => l.replace(/^[-*#>\s]+/, "").replace(/\[\[([^\]|]+)(\|[^\]]+)?\]\]/g, "$1").trim()).filter(l => l.length >= 6 && !/^---/.test(l)).slice(0, 6);
    for (const l of lines) { BR.learn({ type: /손절|실패|주의|하지 마|금지/.test(l) ? "교훈" : "지식", coin, text: l.slice(0, 140), model: "옵시디언:" + title.slice(0, 20), w: 1.4 }); n++; }
  }
  try { localStorage.setItem("neutronMemoSeen", JSON.stringify(seen)); } catch (e) {}
  if (n) { stats.memos = (stats.memos || 0) + n; try { (await import("./coin-office.js")).addNote("hq", `🧠 옵시디언 '내 메모' ${n}줄을 자체 뇌에 학습`, "뉴트론"); } catch (e) {} }
  return n;
}

// ── 받은 편지함: Claude Code·Claudian 이 MCP 로 보낸 제안을 앱에 반영 (허용 3종만) ──
export async function pollInbox() {
  let raw = ""; try { raw = (await codeCall("raw", { ws: "office", path: `${DIR}/inbox.jsonl` })).content || ""; } catch (e) { return 0; }
  if (!raw.trim()) return 0;
  await W(`${DIR}/inbox.jsonl`, "");   // 먼저 비워 중복 반영 방지
  const items = raw.split(/\r?\n/).filter(Boolean).slice(0, 30).map(l => { try { return JSON.parse(l); } catch (e) { return null; } }).filter(Boolean);
  const BR = await import("./brain.js"), N = await import("./neural.js"), O = await import("./coin-office.js"), done = [];
  try { await O.loadLog?.(); } catch (e) {}
  for (const it of items) try {
    const by = String(it.by || "Claude").slice(0, 30);
    if (it.type === "note" && it.text) { BR.learn({ type: ["교훈", "패턴", "지식", "관찰", "전략"].includes(it.kind) ? it.kind : "지식", coin: String(it.coin || "").toUpperCase().slice(0, 6), text: String(it.text).slice(0, 140), model: "MCP:" + by, w: 1.2 }); done.push("메모"); }
    else if (it.type === "experiment" && it.gene?.base) { if (N.proposeEvo({ base: it.gene.base, ...(it.gene.with ? { with: it.gene.with, win: 3 } : {}), ...(Array.isArray(it.gene.filters) ? { filters: it.gene.filters.slice(0, 3) } : {}), ...(Number.isFinite(+it.gene.rr) ? { rr: Math.max(1.3, Math.min(3, +it.gene.rr)) } : {}), src: "MCP 제안" })) done.push("실험"); }
    else if (it.type === "task" && it.title) { O.addTask({ team: String(it.team || "dev").slice(0, 10), title: String(it.title).slice(0, 80), why: String(it.why || "").slice(0, 160), owner: "" }); done.push("과제"); }
  } catch (e) {}   // 그 외 종류(주문 등)는 무시
  if (done.length) { stats.inbox += done.length; try { O.addNote("hq", `🧠 뉴트론 받은 편지함: ${done.join(", ")} 반영 (Claude Code·Claudian 제안)`, "뉴트론"); } catch (e) {} }
  return done.length;
}

export function startNeutron() { onLeader(_startNeutron); return true; }   // 👑 상태 내보내기·받은 편지함도 엔진 주인 창에서만
function _startNeutron() {
  if (started || !LAUNCHER.on) return false; started = true;
  const safe = f => () => f().then(() => { lastErr = ""; }).catch(e => { lastErr = String(e?.message || e).slice(0, 80); });
  setTimeout(safe(async () => { await installFiles(); const S = await exportState(); await writeVault(S); }), 20e3);
  setInterval(safe(exportState), 60e3);
  setInterval(safe(pollInbox), 30e3);
  setInterval(safe(() => writeVault()), 10 * 60e3);
  return true;
}
// 거래소 간 펀딩 스캔 (앱 안에서 쓸 때)
export async function fundingScan(sym) { const F = await import("./lib/fundscan.js"); return F.fundingScan(sym, u => webGet(u, "json")); }
