// 💾 데모 기록 자동 백업·복구 — 앱 저장소(브라우저 localStorage·IndexedDB)가 날아가도 되살릴 수 있게 파일로 남긴다.
//   왜: 2026-10-05 창 두 개·강제 종료로 실험 리그 전략과 데모 장부가 사라진 적이 있다(복구 수단 없었음).
//   무엇을: localStorage 의 GH Coin 키(coin* · neutron* · nuri:term:*) + IndexedDB 의 데모 장부(coin:paper)·사무실 기록(coin:log)·보고서.
//   어디에: 문서/GHNano 사무실/neutron/backup/ — latest.json(1시간마다) · day-YYYY-MM-DD.json(하루 1개) · before-restore.json(복구 직전 상태)
//   API 키·비밀번호 같은 설정(nuri:settings 등)은 백업하지 않는다.
import { LAUNCHER, codeCall, idb } from "../nuri-ai/engine.js";
import { onLeader } from "./leader.js";

const DIR = "neutron/backup", LS_RE = /^(coin|neutron|nuri:term:)/i, IDB_KEYS = ["coin:paper", "coin:log"];
let last = { t: 0, bytes: 0, err: "" }, timer = 0;
export const backupState = () => ({ ...last, on: !!LAUNCHER.on });

async function snapshot() {
  const ls = {}; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k && LS_RE.test(k)) ls[k] = localStorage.getItem(k); }
  const db = {}; for (const k of IDB_KEYS) { try { const v = await idb.all(k); if (v?.length) db[k] = v[0]; } catch (e) {} }
  return { app: "GH Coin", v: 1, t: Date.now(), ls, idb: db };
}
const W = (path, content) => codeCall("write", { ws: "office", path, content });
export async function backupNow(why = "자동") {
  if (!LAUNCHER.on) throw new Error("백업은 GHCoin.exe 로 실행했을 때만 됩니다(파일 저장).");
  const S = await snapshot(), txt = JSON.stringify(S), day = new Date().toLocaleDateString("sv-SE");
  await W(`${DIR}/latest.json`, txt); await W(`${DIR}/day-${day}.json`, txt);
  last = { t: Date.now(), bytes: txt.length, err: "", why, keys: Object.keys(S.ls).length, paper: S.idb["coin:paper"]?.strategies?.length ?? null };
  return last;
}
/** 백업 파일 목록(새 것부터) */
export async function listBackups() {
  if (!LAUNCHER.on) return [];
  try { const r = await codeCall("ls", { ws: "office", path: DIR, depth: 1 }); return (r.entries || []).map(l => { const m = String(l).match(/([^/\\]+\.json) \(([^)]+)\)$/); return m ? { name: m[1], size: m[2] } : null; }).filter(Boolean).sort((a, b) => b.name.localeCompare(a.name)); }
  catch (e) { return []; }
}
/** 복구: 지금 상태를 before-restore.json 에 남긴 뒤, 고른 백업으로 덮어쓴다. 끝나면 새로고침이 필요하다. */
export async function restore(name = "latest.json") {
  if (!LAUNCHER.on) throw new Error("복구는 GHCoin.exe 로 실행했을 때만 됩니다.");
  if (!/^[\w.-]+\.json$/.test(name)) throw new Error("백업 파일 이름이 이상합니다.");
  const raw = (await codeCall("raw", { ws: "office", path: `${DIR}/${name}` })).content || "";
  let S; try { S = JSON.parse(raw); } catch (e) { throw new Error("백업 파일을 읽지 못했습니다."); }
  if (S?.app !== "GH Coin" || !S.ls) throw new Error("GH Coin 백업 파일이 아닙니다.");
  await W(`${DIR}/before-restore.json`, JSON.stringify(await snapshot()));
  for (const [k, v] of Object.entries(S.ls)) if (LS_RE.test(k) && typeof v === "string") localStorage.setItem(k, v);
  for (const [k, v] of Object.entries(S.idb || {})) if (IDB_KEYS.includes(k)) await idb.put(k, v);
  return { t: S.t, keys: Object.keys(S.ls).length, paper: S.idb?.["coin:paper"]?.strategies?.length ?? null };
}
/** 엔진 주인 창에서만: 시작 3분 뒤 첫 백업, 이후 1시간마다 */
export function startBackup() { onLeader(() => { if (timer || !LAUNCHER.on) return; const run = () => backupNow().catch(e => { last = { ...last, err: String(e?.message || e).slice(0, 80) }; });
  setTimeout(run, 3 * 60e3); timer = setInterval(run, 60 * 60e3); }); }
