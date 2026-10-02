// 배운 것(경험 학습) 메모리 — NousResearch/hermes-agent(MIT)의 '경험에서 스킬을 만들고, 쓰면서 개선하고,
// 과거를 검색해 다시 쓴다'는 자기개선 루프를 GH Coin 트레이딩 에이전트용으로 다시 만든 것(코드 복사 없음).
// 공격·보안 요소 없음 — 순수하게 '우리 팀이 리서치하며 배운 교훈'을 쌓고, 반복될수록 강화하고, 상황에 맞게 떠올린다.
// 저장소 주입식({get,set}) → 테스트 쉽고, 브라우저에서는 localStorage('coinLessons') 를 쓴다.
import { tokenize } from "./ragstore.js";

const keyOf = t => String(t || "").toLowerCase().replace(/\s+/g, " ").trim().slice(0, 70);
const weight = x => x.uses * (0.5 + 0.5 * (x.conf || 0));   // 많이 맞은 교훈일수록 무게가 크다

export function makeLessons(store, {key = "coinLessons", max = 120} = {}){
  const read = () => { try { const v = store.get(key, []); return Array.isArray(v) ? v : []; } catch(e){ return []; } };
  const write = l => { try { store.set(key, l.slice(-max)); } catch(e){} };
  return {
    // 교훈 추가 — 같은 교훈이 이미 있으면 '강화'(사용 횟수·신뢰도 갱신), 없으면 새로 만든다 (스킬 생성/개선 루프)
    learn(text, {job = "", ok = true} = {}){
      const t = String(text || "").trim(); if (t.length < 6) return null;
      const list = read(), k = keyOf(t), i = list.findIndex(x => x.k === k);
      if (i >= 0){ const it = list[i]; it.uses++; if (ok) it.ok = (it.ok || 0) + 1; it.conf = Math.min(1, (it.ok || 0) / Math.max(1, it.uses)); it.t = Date.now(); write(list); return {...it, reinforced: true}; }
      const item = {id: Date.now().toString(36), k, text: t.slice(0, 200), job, uses: 1, ok: ok ? 1 : 0, conf: ok ? 1 : 0.5, t: Date.now()};
      list.push(item); write(list); return item;
    },
    // 상황(context)에 맞는 교훈을 떠올린다 — 토큰 겹침 × 강화 무게
    recall(context, n = 5){
      const q = new Set(tokenize(context || "")); if (!q.size) return this.top(n);
      const scored = read().map(x => { let ov = 0; for (const w of tokenize(x.text)) if (q.has(w)) ov++; return {x, s: ov * (1 + Math.log(1 + x.uses)) * (0.5 + 0.5 * (x.conf || 0))}; }).filter(r => r.s > 0);
      scored.sort((a, b) => b.s - a.s); return scored.slice(0, n).map(r => r.x);
    },
    top(n = 5){ return [...read()].sort((a, b) => weight(b) - weight(a)).slice(0, n); },
    all(){ return read(); },
    count(){ return read().length; }
  };
}
