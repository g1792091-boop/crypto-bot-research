// 저장소 이전(마이그레이션) — obevo(goldmansachs) 의 'DB 변경 배포' 방식을 브라우저 저장소(localStorage/IndexedDB)에 맞게 다시 만든 것.
// 변경(change)마다 이름·순서·내용 체크섬을 두고, 적용 기록표(deploy log)에 남긴다.
//   · 이미 적용된 변경은 다시 하지 않는다 (같은 이름 + 같은 체크섬)
//   · 적용된 변경의 내용이 바뀌면(체크섬 불일치) 멈추고 알린다 — 몰래 다시 돌리지 않는다
//   · 적용 전 대상 키를 백업하고, 실패하면 그 백업으로 되돌린다(rollback)
//   · baseline: 기존 사용자는 이미 반영된 것으로 표시만 하고 건너뛸 수 있다
const LOG = "coinDeployLog";
const hash = s => { let h = 2166136261; for (let i = 0; i < s.length; i++){ h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0).toString(16).padStart(8, "0"); };
export const deployLog = () => { try { return JSON.parse(localStorage.getItem(LOG) || "[]"); } catch(e){ return []; } };
const saveLog = l => { try { localStorage.setItem(LOG, JSON.stringify(l.slice(-200))); } catch(e){} };
// changes: [{name, keys:[백업할 localStorage 키], up: () => void, note}]
export function migrate(changes, {baseline = false} = {}){
  const log = deployLog(), out = [];
  for (const c of changes){
    const sum = hash(c.name + "|" + String(c.up));
    const done = log.find(x => x.name === c.name);
    if (done){ if (done.sum !== sum && !done.warned){ done.warned = true; out.push({name: c.name, status: "checksum-mismatch"}); } else out.push({name: c.name, status: "already"}); continue; }
    if (baseline){ log.push({name: c.name, sum, t: Date.now(), status: "baseline"}); out.push({name: c.name, status: "baseline"}); continue; }
    const backup = {}; for (const k of c.keys || []) backup[k] = localStorage.getItem(k);
    try { c.up(); log.push({name: c.name, sum, t: Date.now(), status: "ok", note: c.note || ""}); out.push({name: c.name, status: "ok"}); }
    catch(e){
      for (const [k, v] of Object.entries(backup)){ try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch(e2){} }
      log.push({name: c.name, sum, t: Date.now(), status: "rolled-back", err: String(e.message || e).slice(0, 120)}); out.push({name: c.name, status: "rolled-back", err: e.message});
      break;   // 뒤 변경은 앞 변경에 기대므로 멈춘다
    }
  }
  saveLog(log); return out;
}
