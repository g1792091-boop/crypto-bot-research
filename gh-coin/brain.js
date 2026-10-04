// 🧠 자체 뇌 — 코인 선물 신경 데스크의 '영속 집단 기억'.
// 모델들이 복기·거래·설계에서 배운 것을 쌓고(learn), 다음 판단에 관련 기억을 꺼내 쓴다(recall, RAG식 회상).
// 세션을 넘어 누적되며, 결과가 좋은 기억은 강화(reinforce)되고 쓸모없으면 쇠퇴·삭제된다.
// 아이디어(코드 복사 없이 개념만): memvid/claude-brain · toroleapinc/claude-brain · OoneBreath/project-brain ·
//   AgriciDaniel/claude-obsidian · ArcInstitute/brain-agent-template.
const KEY = "coin:brain";
let B = null;
function load() { if (!B) { try { B = JSON.parse(localStorage.getItem(KEY)) || { mem: [], n: 0 }; } catch (e) { B = { mem: [], n: 0 }; } } return B; }
function save() { try { localStorage.setItem(KEY, JSON.stringify({ mem: B.mem.slice(0, 400), n: B.n })); } catch (e) {} }

// 시장 국면(regime) — 피처로 간단히 분류. 기억을 상황별로 꺼내 쓰기 위한 키.
export function regimeOf(feat = {}) {
  const tr = feat["추세(EMA)"] || 0, mom = feat["모멘텀"] || 0, vol = feat["변동성"] || 0;
  if (vol < -0.3) return "고변동";
  if (Math.abs(tr) < 0.2 && Math.abs(mom) < 0.2) return "횡보";
  return (tr + mom) > 0 ? "상승추세" : "하락추세";
}

// 기억 추가/병합. type: 교훈·패턴·전략·관찰
export function learn({ type = "관찰", coin = "", regime = "", text = "", model = "", w = 1 } = {}) {
  load(); text = String(text).replace(/\s+/g, " ").trim(); if (text.length < 4) return;
  const key = (coin + "|" + regime + "|" + text).slice(0, 140);
  const ex = B.mem.find(m => m.key === key);
  if (ex) { ex.w = Math.min(5, ex.w + 0.5); ex.t = Date.now(); ex.hits = (ex.hits || 1) + 1; }
  else { B.mem.unshift({ id: ++B.n, key, type, coin, regime, text: text.slice(0, 140), model, w, hits: 1, t: Date.now() }); }
  B.mem.sort((a, b) => b.w - a.w || b.t - a.t); B.mem = B.mem.slice(0, 400); save();
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
  return { n: B.mem.length, total: B.n, byType, top: B.mem.slice(0, 12).map(m => ({ type: m.type, coin: m.coin, regime: m.regime, text: m.text, w: +m.w.toFixed(1), hits: m.hits, model: m.model })) };
}
export function reset() { B = { mem: [], n: 0 }; save(); }
export function recallText(coin, regime, n = 4) {
  const r = recall(coin, regime, n); if (!r.length) return "";
  return r.map(m => `(${m.regime || "일반"}) ${m.text}`).join(" / ");
}
