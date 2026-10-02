// 이중 시간(bitemporal) 감사 기록 — reladomo(goldmansachs) 의 '밀스토닝' 개념을 우리 저장소(IndexedDB/localStorage)에 맞게 다시 만든 것.
// 한 행마다 두 개의 시간축을 갖는다:
//   업무 시간(business time)  from ~ thru : 그 사실이 '실제로' 유효했던 기간 (예: 전략 v3 가 운용된 기간)
//   처리 시간(processing time) in ~ out   : 우리가 그 사실을 '기록해 알고 있던' 기간 (정정하면 옛 행은 out 이 닫히고 새 행이 생긴다)
// 아무것도 지우지 않는다(append-only). 정정·종료도 새 행으로 남겨 "그때 우리가 알던 것"과 "실제"를 모두 되짚을 수 있다.
// INF = 무한대(아직 끝나지 않음).
export const INF = 253402214400000;   // 9999-12-01
let STORE = null;
const KEY = "coinJournal";
function load(){ if (STORE) return STORE; try { STORE = JSON.parse(localStorage.getItem(KEY) || "[]"); } catch(e){ STORE = []; } return STORE; }
function save(){ try { localStorage.setItem(KEY, JSON.stringify(STORE.slice(-3000))); } catch(e){} }
export function _useMemory(rows = []){ STORE = rows; }   // 테스트용
const now = () => Date.now();
// 현재(처리 시간 기준 살아 있는) 행들
const live = (entity, id) => load().filter(r => r.entity === entity && r.id === id && r.out === INF);

// 새 사실을 기록 (업무 시간 from 부터 유효). 같은 개체의 현재 유효 행은 업무 시간을 from 에서 끊는다.
export function record(entity, id, data, {from = now(), who = "", why = ""} = {}){
  const t = now(), rows = load();
  for (const r of live(entity, id)){
    if (r.thru > from && r.from < from){
      r.out = t;                                                        // 옛 행은 처리 시간 종료
      rows.push({...r, thru: from, in: t, out: INF, seq: rows.length}); // 앞부분만 남긴 새 행
    } else if (r.from >= from && r.thru === INF){ r.out = t; }          // 같은 시점 이후를 덮어쓰는 경우
  }
  const row = {entity, id, data, from, thru: INF, in: t, out: INF, who, why, seq: rows.length};
  rows.push(row); save(); return row;
}
// 과거 사실을 정정 (업무 시간 구간 [from, thru) 의 값을 바꿈) — 옛 기록은 처리 시간만 닫히고 남는다
export function correct(entity, id, data, {from, thru = INF, who = "", why = "정정"} = {}){
  const t = now(), rows = load();
  for (const r of live(entity, id)){
    if (r.from < thru && r.thru > from){
      r.out = t;
      if (r.from < from) rows.push({...r, thru: from, in: t, out: INF, seq: rows.length});
      if (r.thru > thru) rows.push({...r, from: thru, in: t, out: INF, seq: rows.length});
    }
  }
  rows.push({entity, id, data, from, thru, in: t, out: INF, who, why, seq: rows.length}); save();
}
// 개체 종료 (업무 시간 끝) — 예: 전략 은퇴
export function terminate(entity, id, {at = now(), who = "", why = "종료"} = {}){
  const t = now(), rows = load();
  for (const r of live(entity, id)) if (r.thru > at){ r.out = t; rows.push({...r, thru: at, in: t, out: INF, who, why, seq: rows.length}); }
  save();
}
// "업무 시점 b 에 무엇이 사실이었나 — 처리 시점 p 에 알던 기준으로" (기본: 지금 알고 있는 기준)
export function asOf(entity, id, b = now(), p = now()){
  return load().filter(r => r.entity === entity && r.id === id && r.from <= b && b < r.thru && r.in <= p && p < r.out).sort((a, b2) => b2.in - a.in)[0] || null;
}
export function history(entity, id){ return load().filter(r => r.entity === entity && (id == null || r.id === id)).sort((a, b) => a.in - b.in || a.seq - b.seq); }
export function recent(n = 30, entity){ return load().filter(r => !entity || r.entity === entity).slice(-n).reverse(); }
export const fmtT = t => t >= INF ? "∞" : new Date(t).toLocaleString("ko-KR", {month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false});
