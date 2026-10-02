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
// 행마다 앞 행의 해시를 이어 붙인다(해시 사슬) — 기록이 몰래 바뀌면 verify() 에서 끊긴 곳이 드러난다
const h32 = s => { let h = 2166136261; for (let i = 0; i < s.length; i++){ h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0).toString(16).padStart(8, "0"); };
const sealOf = r => h32([r.entity, r.id, r.from, r.thru, r.in, JSON.stringify(r.data), r.who, r.why, r.prev].join("|"));
function push(rows, r){ r.seq = rows.length; r.prev = rows.length ? rows[rows.length - 1].hash : "0"; r.hash = sealOf(r); rows.push(r); return r; }
export function verify(){ const rows = load(); for (let i = 0; i < rows.length; i++){ const r = rows[i]; if (r.prev !== (i ? rows[i - 1].hash : "0") || r.hash !== sealOf(r)) return {ok: false, at: i, n: rows.length}; } return {ok: true, n: rows.length}; }
// 감사 전용(audit-only) 기록: 거래·결정처럼 '업무 시간'이 따로 없는 사실 — 지금 시점부터 유효, 옛 행은 처리 시간만 닫힘
export function audit(entity, id, data, {who = "", why = ""} = {}){
  const t = now(), rows = load();
  for (const r of live(entity, id)) r.out = t;
  const row = push(rows, {entity, id, data, from: t, thru: INF, in: t, out: INF, who, why}); save(); return row;
}
// 현재(처리 시간 기준 살아 있는) 행들
const live = (entity, id) => load().filter(r => r.entity === entity && r.id === id && r.out === INF);

// 새 사실을 기록 (업무 시간 from 부터 유효). 같은 개체의 현재 유효 행은 업무 시간을 from 에서 끊는다.
export function record(entity, id, data, {from = now(), who = "", why = ""} = {}){
  const t = now(), rows = load();
  for (const r of live(entity, id)){
    if (r.thru > from && r.from < from){
      r.out = t;                                                        // 옛 행은 처리 시간 종료
      push(rows, {...r, thru: from, in: t, out: INF}); // 앞부분만 남긴 새 행
    } else if (r.from >= from && r.thru === INF){ r.out = t; }          // 같은 시점 이후를 덮어쓰는 경우
  }
  const row = push(rows, {entity, id, data, from, thru: INF, in: t, out: INF, who, why}); save(); return row;
}
// 과거 사실을 정정 (업무 시간 구간 [from, thru) 의 값을 바꿈) — 옛 기록은 처리 시간만 닫히고 남는다
export function correct(entity, id, data, {from, thru = INF, who = "", why = "정정"} = {}){
  const t = now(), rows = load();
  for (const r of live(entity, id)){
    if (r.from < thru && r.thru > from){
      r.out = t;
      if (r.from < from) push(rows, {...r, thru: from, in: t, out: INF});
      if (r.thru > thru) push(rows, {...r, from: thru, in: t, out: INF});
    }
  }
  push(rows, {entity, id, data, from, thru, in: t, out: INF, who, why}); save();
}
// 개체 종료 (업무 시간 끝) — 예: 전략 은퇴
export function terminate(entity, id, {at = now(), who = "", why = "종료"} = {}){
  const t = now(), rows = load();
  for (const r of live(entity, id)) if (r.thru > at){ r.out = t; push(rows, {...r, thru: at, in: t, out: INF, who, why}); }
  save();
}
// "업무 시점 b 에 무엇이 사실이었나 — 처리 시점 p 에 알던 기준으로" (기본: 지금 알고 있는 기준)
export function asOf(entity, id, b = now(), p = now()){
  return load().filter(r => r.entity === entity && r.id === id && r.from <= b && b < r.thru && r.in <= p && p < r.out).sort((a, b2) => b2.in - a.in)[0] || null;
}
export function history(entity, id){ return load().filter(r => r.entity === entity && (id == null || r.id === id)).sort((a, b) => a.in - b.in || a.seq - b.seq); }
export function recent(n = 30, entity){ return load().filter(r => !entity || r.entity === entity).slice(-n).reverse(); }
export const fmtT = t => t >= INF ? "∞" : new Date(t).toLocaleString("ko-KR", {month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false});
