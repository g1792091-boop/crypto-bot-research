// 🧠 자체 뇌 — 코인 선물 신경 데스크의 '영속 집단 기억'.
// 모델들이 복기·거래·설계에서 배운 것을 쌓고(learn), 다음 판단에 관련 기억을 꺼내 쓴다(recall, RAG식 회상).
// 세션을 넘어 누적되며, 결과가 좋은 기억은 강화(reinforce)되고 쓸모없으면 쇠퇴·삭제된다.
// 아이디어(코드 복사 없이 개념만):
//   · 영속 기억/회상: memvid · toroleapinc/claude-brain · OoneBreath/project-brain · AgriciDaniel/claude-obsidian · ArcInstitute/brain-agent-template
//   · 위키링크[[ ]]·백링크·그래프 뷰: obsidianmd/obsidian-api · obsidian-help · obsidian-sample-plugin · obsidian-releases
//   · 지식 그래프 파일 포맷(.canvas 내보내기): obsidianmd/jsoncanvas (JSON Canvas 오픈 스펙)
//   · 원자 노트로 정제(distill): obsidianmd/obsidian-clipper
const KEY = "coin:brain";
let B = null;
function load() {
  if (!B) { try { B = JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { B = {}; } }
  if (!B.mem) B.mem = []; if (!B.n) B.n = 0;
  if (!B.iq) B.iq = { w: {}, acc: { hit: 0, tot: 0 }, brier: 0.25, n: 0 };   // 지능: 국면별 학습 가중치 + 자기 정확도
  if (!B.traps) B.traps = [];                                                  // 손절 함정(안티패턴)
  if (!B.risk) B.risk = {};                                                    // 국면별 최적 레버리지·시드·손절·익절 (결과로 학습)
  if (!B.hours) B.hours = {};                                                  // 시간대별 성적 (0~23시)
  if (!B.vol) B.vol = { calm: { pnl: 0, n: 0, wins: 0 }, spike: { pnl: 0, n: 0, wins: 0 } };   // 평온 vs 급변동(뉴스성) 성적
  if (!B.st) B.st = { lessons: 0, traps: 0, promoted: 0, forgot: 0, avoided: 0, softened: 0, lastC: 0 };   // 학습 라인 누적 카운터
  return B;
}
function save() { try { localStorage.setItem(KEY, JSON.stringify({ mem: B.mem.slice(0, 400), n: B.n, iq: B.iq, traps: B.traps.slice(0, 60), risk: B.risk, hours: B.hours, vol: B.vol, st: B.st })); } catch (e) {} }
const IQLR = 0.08;
const FEATS = ["모멘텀", "추세(EMA)", "RSI", "거래흐름", "호가압력", "변동성"];
function cos(a = {}, b = {}) { let d = 0, na = 0, nb = 0; for (const k of FEATS) { const x = a[k] || 0, y = b[k] || 0; d += x * y; na += x * x; nb += y * y; } return (na && nb) ? d / Math.sqrt(na * nb) : 0; }
function strongKeys(f = {}) { return Object.entries(f).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 2).map(([k, v]) => k + (v >= 0 ? "↑" : "↓")).join("·") || "—"; }

// 시장 국면(regime) — 피처로 간단히 분류. 기억을 상황별로 꺼내 쓰기 위한 키.
export function regimeOf(feat = {}) {
  const tr = feat["추세(EMA)"] || 0, mom = feat["모멘텀"] || 0, vol = feat["변동성"] || 0;
  if (vol < -0.3) return "고변동";
  if (Math.abs(tr) < 0.2 && Math.abs(mom) < 0.2) return "횡보";
  return (tr + mom) > 0 ? "상승추세" : "하락추세";
}

// 기억 추가/병합. type: 교훈·패턴·전략·관찰·핵심
// links: 이 기억이 가리키는 다른 기억 id들(obsidian 위키링크 [[ ]] 개념). 없으면 같은 코인·국면 기억에 자동 연결.
export function learn({ type = "관찰", coin = "", regime = "", text = "", model = "", w = 1, links = [], key: k0 = "" } = {}) {
  load(); text = String(text).replace(/\s+/g, " ").trim(); if (text.length < 4) return null;
  const key = k0 || (coin + "|" + regime + "|" + text).slice(0, 140);
  const ex = B.mem.find(m => m.key === key);
  if (ex) { ex.w = Math.min(5, Math.max(ex.w + (k0 ? 0 : 0.5), k0 ? w : 0)); ex.t = Date.now(); ex.hits = (ex.hits || 1) + 1; if (k0) { ex.text = text.slice(0, 140); ex.type = type; } if (links.length) ex.links = [...new Set([...(ex.links || []), ...links])].slice(0, 8); save(); return ex; }
  if (type === "교훈") B.st.lessons++;
  // 자동 연결: 같은 코인·국면의 가장 센 기억 2개에 링크(지식들이 서로 이어지며 그래프가 자란다)
  if (!links.length) links = B.mem.filter(m => (m.coin === coin && coin) || (m.regime === regime && regime)).sort((a, b) => b.w - a.w).slice(0, 2).map(m => m.id);
  const m = { id: ++B.n, key, type, coin, regime, text: text.slice(0, 140), model, w, hits: 1, t: Date.now(), links: [...new Set(links)].slice(0, 8) };
  B.mem.unshift(m);
  B.mem.sort((a, b) => b.w - a.w || b.t - a.t); B.mem = B.mem.slice(0, 400); save(); return m;
}

// 지금 상황(coin+regime)에 가장 관련 있는 기억 N개를 꺼낸다 (RAG식 회상)
export function recall(coin, regime, n = 4) {
  load();
  return B.mem
    .map(m => ({ m, s: (m.coin === coin ? 2 : 0) + (m.regime === regime ? 2 : 0) + m.w * 0.6 + (Date.now() - m.t < 864e5 ? 0.5 : 0) }))
    .sort((a, b) => b.s - a.s).slice(0, n).map(x => x.m);
}

// 결과 피드백: 그 상황의 기억들을 강화/약화 (좋으면 ↑ 나쁘면 ↓, 바닥이면 삭제)
export function reinforce(coin, regime, good) {
  load();
  for (const m of B.mem) if ((m.coin === coin || !m.coin) && m.regime === regime) m.w = Math.max(0.05, Math.min(5, m.w + (good ? 0.2 : -0.2)));
  B.mem = B.mem.filter(m => m.w > 0.12); save();
}

export function brainState() {
  load();
  const byType = {}; for (const m of B.mem) byType[m.type] = (byType[m.type] || 0) + 1;
  const row = m => ({ type: m.type, coin: m.coin, regime: m.regime, text: m.text, w: +m.w.toFixed(1), hits: m.hits, model: m.model, t: m.t });
  return { n: B.mem.length, total: B.n, byType, iq: iqScore(), traps: B.traps.length, st: { ...B.st }, top: B.mem.slice(0, 12).map(row),
    rules: B.mem.filter(m => m.type === "핵심").slice(0, 8).map(row), lessons: B.mem.filter(m => m.type === "교훈").sort((a, b) => b.t - a.t).slice(0, 6).map(row),
    trapList: B.traps.slice(0, 6).map(t => ({ coin: t.coin, regime: t.regime, dir: t.dir, hits: t.hits, w: +t.w.toFixed(1), roe: t.roe, keys: strongKeys(t.feat), t: t.t })) };
}
export function reset() { B = { mem: [], n: 0 }; save(); }
// 뉴트론 MCP·옵시디언 내보내기용 전체 덤프 (읽기 전용 사본)
export function dump() { load(); return { mem: B.mem.map(m => ({ id: m.id, type: m.type, coin: m.coin, regime: m.regime, text: m.text, model: m.model, w: +(+m.w).toFixed(2), hits: m.hits || 1, t: m.t, links: m.links || [] })),
  iq: iqScore(), traps: (B.traps || []).slice(0, 60), risk: B.risk, hours: B.hours, vol: B.vol, st: B.st }; }

// 자체 학습(consolidate): 뇌가 스스로 ① 오래 안 쓴 기억을 잊고(망각) ② 자주 확인된 패턴을 '핵심 규칙'으로 승격한다.
// 핵심 규칙은 근거가 된 패턴 기억들에 링크된다 → 그래프에서 허브(연결 많은 큰 노드)로 자란다.
// 망각은 '시간'으로 계산(호출 빈도와 무관): 오래 안 쓰인 기억만 시간당 조금씩 약해진다. 교훈·함정은 더 오래 간다, 핵심은 잊지 않는다.
const DECAY = { "관찰": [6, 0.06], "지식": [24, 0.02], "매매법": [24, 0.02], "전략": [24, 0.02], "패턴": [24, 0.02], "교훈": [48, 0.01] };
const dirOf = t => /롱/.test(t) ? "롱" : /숏/.test(t) ? "숏" : null;
export function consolidate() {
  load(); const now = Date.now(), hrs = B.st.lastC ? Math.min(3, (now - B.st.lastC) / 3600e3) : 0; B.st.lastC = now; let changed = hrs > 0;
  for (const m of B.mem) { const d = DECAY[m.type]; if (!d) continue; if (now - m.t > d[0] * 3600e3) m.w = Math.max(0.05, m.w - d[1] * hrs); }
  const before = B.mem.length; B.mem = B.mem.filter(m => m.w > 0.12); if (B.mem.length !== before) { B.st.forgot += before - B.mem.length; changed = true; }
  // ── 규칙 승격(핵심): 같은 국면·방향에서 반복 확인된 것만. 문장이 바뀌어도 같은 규칙(key)으로 갱신 → 중복 없음 ──
  const grp = {};
  for (const m of B.mem) { if (m.type !== "패턴" && m.type !== "교훈") continue; const d = dirOf(m.text); if (!d) continue; const k = (m.regime || "일반") + "|" + d; const g = grp[k] ||= { win: [], loss: [], wh: 0, lh: 0 };
    if (m.type === "패턴") { g.win.push(m.id); g.wh += m.hits || 1; } else { g.loss.push(m.id); g.lh += m.hits || 1; } }
  const promote = (key, text, links, w = 3) => { const had = B.mem.some(m => m.key === key); learn({ type: "핵심", text, model: "뇌", w, links, key }); if (!had) B.st.promoted++; changed = true; };
  for (const [k, g] of Object.entries(grp)) { const [regime, dir] = k.split("|");
    if (g.wh >= 3 && g.wh >= g.lh * 1.5) promote("core:win:" + k, `${regime}에선 ${dir}이 통함 — 익절 ${g.wh}회 · 손절 ${g.lh}회`, g.win.slice(0, 8));
    else if (g.lh >= 3 && g.lh >= g.wh * 1.5) promote("core:loss:" + k, `${regime}에서 ${dir} 조심 — 손절 ${g.lh}회 · 익절 ${g.wh}회 (리스크 절반)`, g.loss.slice(0, 8));
    else { const old = B.mem.filter(m => m.key === "core:win:" + k || m.key === "core:loss:" + k); if (old.length) { B.mem = B.mem.filter(m => !old.includes(m)); changed = true; } } }   // 증거가 엇갈리면 규칙 해제
  // 반복 확인된 단일 기억(4회↑·강도 3↑) → 핵심
  for (const m of [...B.mem]) if (m.type !== "핵심" && m.type !== "관찰" && (m.hits || 1) >= 4 && m.w >= 3) promote("core:m:" + m.id, `${m.coin ? m.coin + " " : ""}${m.text}`.slice(0, 120) + ` (${m.hits}회 확인)`, [m.id]);
  // 3번 이상 반복된 손절 함정 → 핵심
  for (const t of B.traps) if (t.hits >= 3) promote("core:trap:" + t.id, `함정: ${t.regime || "일반"} ${t.dir > 0 ? "롱" : "숏"} · ${strongKeys(t.feat)} — 손절 ${t.hits}회 (진입 차단)`, []);
  // 손절 함정: 24시간 넘게 다시 안 걸리면 천천히 약화(시장이 변함) → 바닥이면 삭제
  for (const t of B.traps) if (now - t.t > 24 * 3600e3) t.w = Math.max(0.1, t.w - 0.05 * hrs);
  const bt = B.traps.length; B.traps = B.traps.filter(t => t.w > 0.25); if (B.traps.length !== bt) { B.st.forgot += bt - B.traps.length; changed = true; }
  if (changed) save();
  return changed;
}
// 진입 전 뇌 점검: 손절 함정과 닮았는지 + 핵심 '조심' 규칙 → 차단/리스크 절반. 실제로 피하면 avoided 카운트.
export function gateCheck(feat = {}, regime = "", dir = 0) {
  load(); const risk = trapRisk(feat, regime, dir), d = dir > 0 ? "롱" : "숏";
  const rule = B.mem.find(m => m.key === "core:loss:" + (regime || "일반") + "|" + d);
  if (risk >= 0.6) { B.st.avoided++; save(); return { block: true, mul: 0, why: `뇌 함정 회피(과거 손절과 ${Math.round(risk * 100)}% 닮음)` }; }
  if (risk >= 0.4 || rule) { B.st.softened++; save(); return { block: false, mul: 0.5, why: rule ? `뇌 규칙: ${rule.text.slice(0, 40)}` : `뇌 함정 유사 ${Math.round(risk * 100)}% → 리스크 절반` }; }
  return { block: false, mul: 1, why: "" };
}

// 지식 그래프: 노드(기억) + 엣지. 엣지 = 명시적 링크(위키링크) + 같은 코인·국면·유형. degree(연결 수)로 노드 크기 결정(obsidian 그래프 뷰).
export function graph(max = 80) {
  load();
  const nodes = B.mem.slice(0, max).map(m => ({ id: m.id, type: m.type, coin: m.coin, regime: m.regime, w: m.w, text: m.text, t: m.t, model: m.model }));
  const idx = new Map(nodes.map((n, i) => [n.id, i]));
  const seen = new Set(), edges = [];
  const add = (i, j, kind) => { if (i === j || i == null || j == null) return; const k = i < j ? i + ":" + j : j + ":" + i; if (seen.has(k)) return; seen.add(k); edges.push([Math.min(i, j), Math.max(i, j), kind]); };
  // ① 명시적 링크(위키링크) — 가장 강한 연결
  for (let i = 0; i < nodes.length; i++) for (const lid of (B.mem[i]?.links || [])) add(i, idx.get(lid), "link");
  // ② 같은 코인·국면·유형(노드당 상한)
  for (let i = 0; i < nodes.length; i++) { let c = 0;
    for (let j = i + 1; j < nodes.length && c < 3; j++) { const a = nodes[i], b = nodes[j];
      if ((a.coin && a.coin === b.coin) || (a.regime && a.regime === b.regime) || a.type === b.type) { add(i, j, "attr"); c++; } } }
  const deg = nodes.map(() => 0); for (const [i, j] of edges) { deg[i]++; deg[j]++; }
  nodes.forEach((n, i) => n.deg = deg[i]);
  return { nodes, edges };
}

// JSON Canvas(.canvas) 내보내기 — obsidianmd/jsoncanvas 오픈 스펙. 실제 Obsidian에서 이 파일을 열 수 있다.
export function toCanvas(max = 120) {
  const g = graph(max);
  const COL = { "교훈": "3", "패턴": "4", "전략": "6", "핵심": "1", "관찰": "5" };   // JSON Canvas 프리셋 색(1~6)
  const R = 360, cx = 0, cy = 0;
  const nodes = g.nodes.map((n, i) => {
    const ang = (i / Math.max(1, g.nodes.length)) * Math.PI * 2, rad = R + (i % 5) * 46;
    const w = 220, h = 70 + Math.min(60, (n.deg || 0) * 8);
    return { id: "n" + n.id, type: "text", x: Math.round(cx + Math.cos(ang) * rad - w / 2), y: Math.round(cy + Math.sin(ang) * rad - h / 2), width: w, height: h, color: COL[n.type] || "0", text: `**[${n.type}] ${n.coin || ""} ${n.regime || ""}**\n${n.text}${n.model ? "\n— " + n.model : ""}` };
  });
  const edges = g.edges.map(([i, j, kind], k) => ({ id: "e" + k, fromNode: "n" + g.nodes[i].id, toNode: "n" + g.nodes[j].id, ...(kind === "link" ? { color: "1", label: "링크" } : {}) }));
  return { nodes, edges };
}
export function reset_links() { load(); for (const m of B.mem) m.links = []; save(); }   // 테스트/초기화용

// ════════ 🧠 지능(자가학습 예측기) — 거래 결과로 국면별 가중치를 스스로 고친다(온라인 퍼셉트론) ════════
// 뇌가 피처(보조지표 신호)로 '지금 롱이 이득일까 숏이 이득일까'를 예측하고, 실제 손익으로 틀리면 바로 교정한다.
export function predict(feat = {}, regime = "") {
  load(); const w = B.iq.w[regime || "일반"] || {};
  let s = 0; for (const k of FEATS) s += (w[k] || 0) * (feat[k] || 0);
  s = Math.tanh(s);
  const acc = B.iq.acc.tot ? B.iq.acc.hit / B.iq.acc.tot : 0.5;
  const trust = Math.max(0, (acc - 0.5) * 2) * Math.min(1, B.iq.acc.tot / 40);   // 정확도·표본이 쌓여야 신뢰
  return { dir: s > 0.08 ? 1 : s < -0.08 ? -1 : 0, s: +s.toFixed(3), conf: Math.round(Math.abs(s) * trust * 100), trust: +trust.toFixed(2) };
}
// 거래 하나 끝날 때마다 호출 → 가중치·정확도 갱신 (pnl은 수익률 분수, +면 이득)
export function learnOutcome({ coin = "", regime = "", feat = {}, dir = 0, pnl = 0 } = {}) {
  load(); if (!dir || !feat) return;
  const key = regime || "일반", w = B.iq.w[key] || (B.iq.w[key] = {});
  let s = 0; for (const k of FEATS) s += (w[k] || 0) * (feat[k] || 0); s = Math.tanh(s);
  const truth = pnl >= 0 ? dir : -dir;                      // 실제로 옳았던 방향
  const err = truth - s;
  for (const k of FEATS) w[k] = Math.max(-3, Math.min(3, (w[k] || 0) + IQLR * err * (feat[k] || 0)));
  B.iq.n++; B.iq.acc.tot++; const pdir = s > 0 ? 1 : s < 0 ? -1 : 0; if (pdir === truth) B.iq.acc.hit++;
  const p = s * 0.5 + 0.5, y = truth > 0 ? 1 : 0;           // 롱 확률 추정 vs 정답 → 칼리브레이션(Brier)
  B.iq.brier = (B.iq.brier * (B.iq.acc.tot - 1) + (p - y) ** 2) / B.iq.acc.tot;
  save();
}
export function iqScore() {
  load(); const t = B.iq.acc.tot, acc = t ? B.iq.acc.hit / t : 0, sample = Math.min(1, t / 60), cal = 1 - Math.min(1, B.iq.brier * 2);
  const score = Math.round((Math.max(0, acc - 0.5) * 2 * 0.6 + sample * 0.2 + cal * 0.2) * 100);
  return { score, acc: +(acc * 100).toFixed(0), n: t, brier: +B.iq.brier.toFixed(3) };
}

// ════════ 🛑 손절 함정(안티패턴) — "왜 손절났는지" 기억하고, 비슷한 자리면 다음엔 피한다 ════════
export function learnLoss({ coin = "", regime = "", feat = {}, dir = 0, roe = 0 } = {}) {
  load();
  const ex = B.traps.find(t => t.dir === dir && (!t.regime || t.regime === regime) && cos(t.feat, feat) > 0.85);
  if (ex) { ex.hits++; ex.w = Math.min(5, ex.w + 0.5); ex.t = Date.now(); for (const k of FEATS) ex.feat[k] = (ex.feat[k] || 0) * 0.7 + (feat[k] || 0) * 0.3; }
  else { B.traps.unshift({ id: ++B.n, coin, regime, dir, feat: { ...feat }, roe: +roe.toFixed(1), hits: 1, w: 1.2, t: Date.now() }); B.st.traps++; }
  B.traps.sort((a, b) => b.w - a.w); B.traps = B.traps.slice(0, 60);
  learn({ type: "교훈", coin, regime, text: `${regime} ${dir > 0 ? "롱" : "숏"} 손절 ${roe.toFixed(1)}% — ${strongKeys(feat)}에서 진입 금지`, model: "뇌", w: 2 });
  save();
}
// 지금 들어가려는 자리가 과거 손절과 얼마나 닮았나 (0~1). 높으면 진입 피해라.
export function trapRisk(feat = {}, regime = "", dir = 0) {
  load(); let r = 0;
  for (const t of B.traps) { if (t.dir !== dir) continue; if (t.regime && regime && t.regime !== regime) continue; const sim = cos(t.feat, feat); if (sim > 0.8) r = Math.max(r, sim * Math.min(1, t.w / 3)); }
  return +r.toFixed(2);
}

// ════════ 🔗 에이전트 팀 ↔ 옵시디언(뇌) ↔ 모델 브리지 ════════
// 에이전트 팀/외부(.canvas)가 넣은 결과를 뇌가 받아 지식화(ingest) → 지능으로 '이득 날만하게' 다듬어 돌려줌(refineForProfit)
export function ingest({ coin = "", regime = "", text = "", type = "관찰", feat = null, dir = 0, outcome = null, model = "에이전트팀" } = {}) {
  const m = learn({ type, coin, regime, text, model, w: 1.3 });
  if (outcome != null && feat && dir) { learnOutcome({ coin, regime, feat, dir, pnl: outcome }); if (outcome < 0) learnLoss({ coin, regime, feat, dir, roe: outcome * 100 }); }
  return m;
}
// 뇌가 누적 지식+지능으로 코인 선물에서 '이득 날만한' 방향·주의를 정제해 반환 (에이전트 팀/모델에 인계)
export function refineForProfit(coin = "", regime = "") {
  load(); const w = B.iq.w[regime || "일반"] || {}, iq = iqScore();
  const bias = Object.entries(w).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 3);
  const trapN = B.traps.filter(t => !regime || t.regime === regime).length;
  const rule = bias.length ? bias.map(([k, v]) => `${k} 강할수록 ${v >= 0 ? "롱" : "숏"}`).join(", ") : "표본 부족";
  return { coin, regime, iq: iq.score, acc: iq.acc, n: iq.n, cautions: trapN, keyFeatures: bias.map(([k, v]) => `${k}${v >= 0 ? "+" : ""}${v.toFixed(2)}`),
    memory: recallText(coin, regime, 3),
    text: `[${regime} 국면] 뇌 지능 ${iq.score}/100(정확도 ${iq.acc}%·표본 ${iq.n}): ${rule}. 손절패턴 ${trapN}개는 회피.` };
}

// ════════ 💹 리스크 자가학습: 국면별 '레버리지·시드·손절·익절'을 결과로 스스로 조정 ════════
// 이익나면 그때 쓴 값 쪽으로, 손실나면 레버리지·시드를 낮추는 쪽으로 EMA. 고배/중배도 쓰되 통하는 수위를 찾는다.
export function learnRisk({ regime = "일반", lev, seed, sl, tp, pnl = 0 } = {}) {
  load(); const k = regime || "일반", r = B.risk[k] || (B.risk[k] = { lev: 8, seed: 15, sl: 2, tp: 4, n: 0, wins: 0 });
  const win = pnl >= 0, a = 0.18;
  if (win) { if (lev) r.lev = r.lev * (1 - a) + lev * a; if (seed) r.seed = r.seed * (1 - a) + seed * a; if (sl) r.sl = r.sl * (1 - a) + sl * a; if (tp) r.tp = r.tp * (1 - a) + tp * a; r.wins++; }
  else { r.lev = Math.max(2, r.lev * 0.9); r.seed = Math.max(4, r.seed * 0.93); if (sl) r.sl = r.sl * 0.85 + sl * 0.15; }   // 손실 = 레버·시드 낮추고 손절폭 조정
  r.lev = Math.min(200, r.lev); r.seed = Math.min(90, r.seed); r.n++; save();
}
export function suggestRisk(regime) {
  load(); const r = B.risk[regime || "일반"] || B.risk["일반"]; if (!r || r.n < 3) return null;
  return { lev: Math.max(1, Math.round(r.lev)), seed: Math.max(1, Math.round(r.seed)), sl: +r.sl.toFixed(1), tp: +r.tp.toFixed(1), n: r.n, wr: r.n ? Math.round(r.wins / r.n * 100) : 0 };
}
// ════════ 🕐 시간대 학습: 어느 시간에 매매가 잘/안 되는지 (0~23시) ════════
export function learnTime(hour, pnl = 0) { load(); const h = B.hours[hour] || (B.hours[hour] = { pnl: 0, n: 0, wins: 0 }); h.pnl += pnl; h.n++; if (pnl >= 0) h.wins++; save(); }
export function timeAdvice(hour) { load(); const h = B.hours[hour]; if (!h || h.n < 4) return null; const wr = Math.round(h.wins / h.n * 100); return { wr, n: h.n, avg: +(h.pnl / h.n).toFixed(2), good: wr >= 50 && h.pnl >= 0 }; }
// ════════ 📰 뉴스성 급변동 학습: 급변동(뉴스 반응) 구간에 매매가 득인지 실인지 ════════
export function learnEvent(spike, pnl = 0) { load(); const b = B.vol[spike ? "spike" : "calm"]; b.pnl += pnl; b.n++; if (pnl >= 0) b.wins++; save(); }
export function eventAdvice(spike) { load(); const b = B.vol[spike ? "spike" : "calm"]; if (!b || b.n < 4) return null; const wr = Math.round(b.wins / b.n * 100); return { wr, n: b.n, avg: +(b.pnl / b.n).toFixed(2), good: wr >= 50 && b.pnl >= 0 }; }
// UI/프롬프트용 요약
export function riskState() {
  load();
  const hrs = Object.entries(B.hours).filter(([, h]) => h.n >= 3).map(([hr, h]) => ({ hr: +hr, wr: Math.round(h.wins / h.n * 100), n: h.n, avg: +(h.pnl / h.n).toFixed(2) })).sort((a, b) => b.avg - a.avg);
  return { risk: Object.entries(B.risk).map(([rg, r]) => ({ regime: rg, lev: Math.round(r.lev), seed: Math.round(r.seed), sl: +r.sl.toFixed(1), tp: +r.tp.toFixed(1), n: r.n, wr: r.n ? Math.round(r.wins / r.n * 100) : 0 })),
    bestHours: hrs.slice(0, 3), worstHours: hrs.slice(-3).reverse(), vol: { calm: B.vol.calm, spike: B.vol.spike } };
}

export function recallText(coin, regime, n = 4) {
  const r = recall(coin, regime, n); if (!r.length) return "";
  return r.map(m => `(${m.regime || "일반"}) ${m.text}`).join(" / ");
}
// 특정 유형(매매법·지식 등) 상위 기억 — 설계/판단에 지식베이스를 직접 꺼내 쓰기
export function recallBy(prefix, n = 3, coin = "") { load(); return B.mem.filter(m => String(m.model || "").startsWith(prefix) && (!coin || !m.coin || m.coin === coin)).slice(0, n).map(m => m.text); }
export function recallType(type, n = 3, coin = "") { load(); return B.mem.filter(m => m.type === type && (!coin || !m.coin || m.coin === coin)).slice(0, n).map(m => m.text); }
