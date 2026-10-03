// 공유 리서치 보드 — ARTEX 의 '공유 사실 그래프 + 혈연 링크(어느 의도가 무엇을 낳았나)' 개념을
// 트레이딩 리서치용으로 축소 이식한 것. 워커(= 기존 job)가 낸 결과(사실·발견)를 한곳에 쌓고,
// 같은 내용은 디듀프하며, 어떤 intent(의도)에서 나왔는지 lineage 를 남긴다. 공격·정찰 요소는 없다.
// 저장소는 주입식({get,set}) → 테스트 쉽고, 브라우저에서는 localStorage 를 쓴다.

const now = () => Date.now();
const normKey = (target, text) => `${target || "-"}|${String(text || "").replace(/\s+/g, " ").trim().slice(0, 80).toLowerCase()}`;

// store: {get(key,def), set(key,val)} · key 'coinBoard'
export function makeBoard(store, {key = "coinBoard", max = 200} = {}){
  const read = () => { try { const v = store.get(key, []); return Array.isArray(v) ? v : []; } catch(e){ return []; } };
  const write = list => { try { store.set(key, list.slice(-max)); } catch(e){} };
  return {
    // 발견/사실 추가 — 같은 (target, 내용)이 최근에 있으면 건드리지 않고 timestamp 만 갱신(디듀프)
    add(f){
      const list = read(), k = normKey(f.target, f.text), i = list.findIndex(x => x.k === k);
      const item = {id: `${now().toString(36)}`, k, intent: f.intent || "", job: f.job || "", target: f.target || "", targetName: f.targetName || "", kind: f.kind || "사실", text: String(f.text || "").slice(0, 300), t: now()};
      if (i >= 0){ list[i].t = item.t; list[i].text = item.text; list[i].kind = item.kind; write(list); return {...list[i], dup: true}; }
      list.push(item); write(list); return item;
    },
    recent(n = 12){ return read().slice(-n).reverse(); },
    forTarget(target, n = 8){ return read().filter(x => x.target === target).slice(-n).reverse(); },
    all(){ return read(); },
    count(){ return read().length; },
    // 최근 실행한 intent 키들(planner 디듀프용): 'job:target'
    recentIntents(n = 10){ return [...new Set(read().slice(-n).map(x => `${x.job}:${x.target || "-"}`))]; }
  };
}
