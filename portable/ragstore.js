// 자체 RAG 저장소 — 외부 서비스 없이 브라우저/Node 안에서 도는 가벼운 검색(TF-IDF + 코사인).
// Dify·Flowise·AnythingLLM 의 '내 문서 지식으로 답하기(RAG)' 개념을 코드 복사 없이 아주 작게 다시 만든 것.
// 한국어는 띄어쓰기가 불규칙해서 어절 토큰 + 글자 2-그램(bigram)을 함께 써서 잘 걸리게 한다.
// 임베딩 모델/외부 벡터DB 없이 동작 → '완전 자체'. 문서 수백 개 규모에 충분하다.

const HANGUL = /[가-힣]+/g, WORD = /[a-z0-9]+/g;

export function tokenize(text){
  const s = String(text || "").toLowerCase();
  const toks = [];
  for (const m of s.match(WORD) || []) if (m.length >= 2 || /[0-9]/.test(m)) toks.push(m);
  for (const h of s.match(HANGUL) || []){
    if (h.length <= 3) toks.push(h);                         // 짧은 단어는 통째로
    for (let i = 0; i < h.length - 1; i++) toks.push(h.slice(i, i + 2));   // 글자 2-그램
  }
  return toks;
}

const tf = toks => { const m = new Map(); for (const t of toks) m.set(t, (m.get(t) || 0) + 1); return m; };
const norm = vec => { let s = 0; for (const v of vec.values()) s += v * v; return Math.sqrt(s) || 1; };

export function buildIndex(docs = []){
  const items = docs.filter(d => d && (d.text || d.title)).map(d => ({id: d.id, title: d.title || "", meta: d.meta || {}, text: d.text || "", tf: tf(tokenize((d.title ? d.title + " " + d.title + " " : "") + (d.text || "")))}));
  const df = new Map(), N = items.length || 1;
  for (const it of items) for (const t of it.tf.keys()) df.set(t, (df.get(t) || 0) + 1);
  const idf = t => Math.log((N + 1) / ((df.get(t) || 0) + 1)) + 1;
  for (const it of items){ it.vec = new Map(); for (const [t, c] of it.tf) it.vec.set(t, (1 + Math.log(c)) * idf(t)); it.norm = norm(it.vec); }
  return {items, idf, N, df};
}

export function search(index, query, k = 5){
  if (!index || !index.items.length) return [];
  const q = tf(tokenize(query)), qv = new Map();
  for (const [t, c] of q) qv.set(t, (1 + Math.log(c)) * index.idf(t));
  const qn = norm(qv);
  const scored = index.items.map(it => {
    let dot = 0; for (const [t, w] of qv) { const dw = it.vec.get(t); if (dw) dot += w * dw; }
    return {id: it.id, title: it.title, text: it.text, meta: it.meta, score: dot / (qn * it.norm)};
  }).filter(r => r.score > 0);
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, k);
}

// 검색 결과를 LLM 컨텍스트/추출 답변용 텍스트로
export function contextOf(hits, {maxChars = 2800} = {}){
  let out = "", i = 0;
  for (const h of hits){
    const block = `[${++i}] ${h.title ? h.title + " — " : ""}${(h.text || "").replace(/\s+/g, " ").trim()}`.slice(0, 700);
    if (out.length + block.length > maxChars) break;
    out += block + "\n";
  }
  return out.trim();
}
