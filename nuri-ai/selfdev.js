// 스스로 코드 고치기: 앱에서 난 오류를 모으고 → AI·개발팀이 최소한의 수정안을 만들고 → 코드가 검사하고 → 대표가 [적용]을 눌러야 반영된다.
// 반영은 GHNano.exe 의 '고친 파일 덮어쓰기'(문서/GHNano 사무실/app-patches)로 한다. 원본은 exe 안에 그대로 있어 언제든 되돌릴 수 있고,
// 고친 뒤 앱이 안 열리면 index.html 의 안전장치가 패치를 끄고 다시 연다.
// 실거래·API 키·안전장치·화면 틀 파일은 절대 고치지 않는다.

const ERR_KEY = "ghn:errors", PATCH_KEY = "ghn:patches";
export const PROTECTED = ["live.js", "live-ui.js", "live.css", "sw.js", "index.html", "selfdev.js", "engine.js"];
const DANGER = /실거래를 시작합니다|자동매매에 동의합니다|MAINNET|mainnet|withdraw|출금|apiKey|api_key|secret|X-MBX-APIKEY|maxNotional|maxLeverage|dailyLoss|PROMOTE|GATE\b|sessionToken|__NURI_TOKEN/;
const readJ = (k, d) => { try { const v = JSON.parse(localStorage.getItem(k) || ""); return v ?? d; } catch(e){ return d; } };
const writeJ = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch(e){} };
const uid = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);

/* ============ 오류 모으기 ============ */
const NOISE = /ResizeObserver|Failed to fetch|NetworkError|Load failed|aborted|AbortError|signal is aborted|chrome-extension|moz-extension|Script error\.?$|CORS|net::|사용 한도|키가 올바르지|연결하지 못했습니다|429|401|403/i;
// 스택에서 nuri-ai 기준 파일 경로와 줄 번호
function whereOf(stack = "", file = "", line = 0){
  const m = String(file ? `${file}:${line || 0}` : stack).match(/\/nuri-ai\/([\w\-/.]+\.js)(?:\?[^:]*)?:(\d+)/) || String(stack).match(/\/nuri-ai\/([\w\-/.]+\.js)(?:\?[^:]*)?:(\d+)/);
  return m ? {file: m[1], line: +m[2]} : {file: String(file || "").replace(/^.*\/nuri-ai\//, "").replace(/\?.*$/, ""), line: +line || 0};
}
export function recordError({msg, file, line, col, stack = "", src = ""} = {}){
  msg = String(msg || "").slice(0, 300); if (!msg || NOISE.test(msg)) return null;
  const w = whereOf(stack, file, line);
  const list = readJ(ERR_KEY, []), key = msg + "|" + w.file + "|" + w.line;
  let e = list.find(x => x.key === key);
  if (e){ e.count++; e.last = Date.now(); }
  else { e = {key, msg, file: w.file, line: w.line, col: +col || 0, stack: String(stack).slice(0, 1200), src, count: 1, first: Date.now(), last: Date.now()}; list.push(e); }
  writeJ(ERR_KEY, list.sort((a, b) => a.last - b.last).slice(-60));
  return e;
}
let captured = false;
export function captureErrors(){
  if (captured || typeof window === "undefined") return; captured = true;
  window.addEventListener("error", ev => { if (ev?.message) recordError({msg: ev.message, file: ev.filename, line: ev.lineno, col: ev.colno, stack: ev.error?.stack || "", src: "window"}); });
  window.addEventListener("unhandledrejection", ev => { const r = ev?.reason; recordError({msg: r?.message || String(r || ""), stack: r?.stack || "", src: "promise"}); });
}
// 자주 · 최근에 난 오류 순
export function recentErrors(n = 10){
  const now = Date.now();
  return readJ(ERR_KEY, []).filter(e => e.file && /\.js$/.test(e.file)).map(e => ({...e, score: e.count / (1 + (now - e.last) / 36e5)})).sort((a, b) => b.score - a.score).slice(0, n);
}
export const clearErrors = () => writeJ(ERR_KEY, []);

/* ============ 문법 검사 (실행하지 않고 해석만) ============ */
// ES 모듈 문법을 스크립트 문법으로 바꾼 뒤 new Function 으로 해석만 한다 (본문은 실행되지 않음)
export function syntaxCheck(code){
  try {
    let s = String(code);
    s = s.replace(/^\s*import\s+[^;'"]*?from\s*(['"])[^'"]+\1\s*;?/gm, "")
         .replace(/^\s*import\s*(['"])[^'"]+\1\s*;?/gm, "")
         .replace(/^\s*import\s*\{[\s\S]*?\}\s*from\s*(['"])[^'"]+\1\s*;?/gm, "")
         .replace(/^\s*export\s*\{[\s\S]*?\}\s*(from\s*(['"])[^'"]+\2)?\s*;?/gm, "")
         .replace(/^\s*export\s+\*\s+from\s*(['"])[^'"]+\1\s*;?/gm, "")
         .replace(/\bexport\s+default\s+/g, "const __d = ")
         .replace(/(^|[\s;])export\s+(?=(async\s+)?function|const|let|var|class)/g, "$1")
         .replace(/\bimport\.meta\b/g, "__meta")
         .replace(/\bimport\s*\(/g, "__imp(");
    new Function("__meta", "__imp", `"use strict";\nreturn async function(){\n${s}\n};`);
    return {ok: true, msg: "문법 이상 없음"};
  } catch(e){ return {ok: false, msg: "문법 오류: " + String(e.message || e).slice(0, 160)}; }
}

/* ============ 수정안 ============ */
export const listPatches = () => readJ(PATCH_KEY, []);
const savePatches = list => writeJ(PATCH_KEY, list.slice(-80));
function upsert(p){ const list = listPatches(), i = list.findIndex(x => x.id === p.id); if (i >= 0) list[i] = p; else list.push(p); savePatches(list); return p; }
const isProtected = f => !f || PROTECTED.includes(f) || /^vendor\//.test(f) || /\.\./.test(f) || !/\.(js|css)$/.test(f);
async function source(file){ const r = await fetch("./" + file, {cache: "no-store"}); if (!r.ok) throw new Error(`${file}을(를) 읽지 못했습니다 (${r.status})`); return r.text(); }
const count = (hay, needle) => { let n = 0, i = 0; while ((i = hay.indexOf(needle, i)) >= 0){ n++; i += needle.length || 1; } return n; };
function pickJSON(t){
  t = String(t || "").replace(/<think>[\s\S]*?<\/think>/g, "");
  const cands = [...t.matchAll(/```(?:json)?\s*([\s\S]*?)```/g)].map(m => m[1]);
  const a = t.indexOf("{"), b = t.lastIndexOf("}"); if (a >= 0 && b > a) cands.push(t.slice(a, b + 1));
  for (const c of cands){ try { const j = JSON.parse(c.replace(/[“”]/g, '"').replace(/,\s*([}\]])/g, "$1")); if (j && typeof j === "object") return j; } catch(e){} }
  return null;
}
// 수정안 하나를 검사: 보호 파일 · 찾을 글이 딱 한 번 · 위험 문구 · 크기 · 문법
function check(text, p){
  if (isProtected(p.file)) return {ok: false, msg: "보호된 파일이라 고칠 수 없습니다"};
  if (!p.find || typeof p.replace !== "string") return {ok: false, msg: "find · replace 가 없습니다"};
  if (p.find === p.replace) return {ok: false, msg: "바뀌는 내용이 없습니다"};
  if (p.find.split("\n").length > 60 || p.replace.split("\n").length > 80) return {ok: false, msg: "수정 범위가 너무 큽니다 (작게 고쳐야 함)"};
  const n = count(text, p.find); if (n !== 1) return {ok: false, msg: n ? `찾을 코드가 ${n}곳에 있어 어디를 고칠지 모릅니다` : "찾을 코드가 파일에 없습니다"};
  if (DANGER.test(p.replace) && !DANGER.test(p.find)) return {ok: false, msg: "실거래·키·안전장치 관련 코드는 고칠 수 없습니다"};
  if (DANGER.test(p.find)) return {ok: false, msg: "실거래·키·안전장치 관련 코드는 고칠 수 없습니다"};
  const patched = text.replace(p.find, () => p.replace);
  const syn = /\.js$/.test(p.file) ? syntaxCheck(patched) : {ok: true, msg: "CSS"};
  return syn.ok ? {ok: true, msg: "검사 통과 (문법 · 범위 · 보호 파일)", patched} : syn;
}
const FIX_SYS = `너는 이 웹앱(GH Nano, 순수 JavaScript ES 모듈)의 개발자다. 아래 오류를 고치는 '가장 작은' 수정 하나를 만든다.
규칙: 실거래·API 키·안전장치·한도 코드는 건드리지 않는다. 동작을 넓게 바꾸지 말고 오류 원인만 고친다(널 검사·잘못된 이름·빠진 대비 등).
답은 JSON 하나만: {"file":"파일 경로(예: office.js)","find":"파일에 있는 그대로의 코드 몇 줄(한 곳에만 있는 부분)","replace":"고친 코드","why":"한국어 한두 문장: 원인과 고친 방법"}
고칠 수 없거나 원인을 모르겠으면 {"file":"","find":"","replace":"","why":"이유"} 로 답한다.`;
// err: recentErrors() 의 항목, ask(sys, user) → 모델의 답(문자열)
export async function proposeFix(err, {ask, by = ""} = {}){
  const base = {id: uid(), t: Date.now(), error: {msg: err.msg, file: err.file, line: err.line, count: err.count || 1}, by};
  if (isProtected(err.file)) return upsert({...base, file: err.file, status: "invalid", check: {ok: false, msg: "보호된 파일에서 난 오류라 사람이 직접 봐야 합니다"}});
  let text;
  try { text = await source(err.file); } catch(e){ return upsert({...base, file: err.file, status: "invalid", check: {ok: false, msg: e.message}}); }
  const lines = text.split("\n"), at = Math.max(1, err.line || 1);
  let lo = Math.max(0, at - 40), hi = Math.min(lines.length, at + 30);
  if (!err.line){ const word = (String(err.msg).match(/[A-Za-z_$][\w$]{3,}/g) || []).find(w => text.includes(w)); const k = word ? lines.findIndex(l => l.includes(word)) : -1; if (k >= 0){ lo = Math.max(0, k - 35); hi = Math.min(lines.length, k + 35); } }
  const excerpt = lines.slice(lo, hi).map((l, i) => `${String(lo + i + 1).padStart(5)}| ${l}`).join("\n");
  const user = `오류: ${err.msg}\n파일: ${err.file}${err.line ? " " + err.line + "번째 줄" : ""} · ${err.count || 1}번 발생\n스택:\n${String(err.stack || "").slice(0, 600)}\n\n코드 (${err.file} ${lo + 1}~${hi}줄, 줄 번호와 '| '는 코드가 아님):\n${excerpt}`;
  let raw = "";
  try { raw = await ask(FIX_SYS, user); } catch(e){ return upsert({...base, file: err.file, status: "invalid", check: {ok: false, msg: "모델 오류: " + String(e.message || e).slice(0, 100)}}); }
  const j = pickJSON(raw);
  if (!j) return upsert({...base, file: err.file, status: "invalid", check: {ok: false, msg: "수정안 JSON을 받지 못했습니다"}});
  const p = {...base, file: String(j.file || err.file || "").replace(/^\.?\/?(nuri-ai\/)?/, ""), find: String(j.find || ""), replace: String(j.replace ?? ""), why: String(j.why || "").slice(0, 300)};
  if (!p.find) return upsert({...p, status: "invalid", check: {ok: false, msg: p.why || "고칠 방법을 찾지 못했습니다"}});
  if (p.file !== err.file){ try { text = await source(p.file); } catch(e){ return upsert({...p, status: "invalid", check: {ok: false, msg: e.message}}); } }
  const c = check(text, p);
  return upsert({...p, status: c.ok ? "proposed" : "invalid", check: {ok: c.ok, msg: c.msg}});
}

/* ============ 적용 · 되돌리기 (GHNano.exe 전용) ============ */
const launcherOn = () => typeof window !== "undefined" && !!window.__NURI_TOKEN;
async function ov(method, body, q = ""){
  const r = await fetch("/__nuri/override" + q, {method, headers: {"content-type": "application/json", "X-Nuri-Token": window.__NURI_TOKEN || ""}, body: body ? JSON.stringify(body) : undefined});
  const j = await r.json().catch(() => ({})); if (!r.ok || j.ok === false) throw new Error(j.error || `고친 파일 저장 실패 (${r.status})`); return j;
}
export async function overridesStatus(){ if (!launcherOn()) return {ok: false, enabled: false, files: [], web: true}; try { return await ov("GET"); } catch(e){ return {ok: false, enabled: false, files: [], error: e.message}; } }
export async function applyPatch(id){
  const list = listPatches(), p = list.find(x => x.id === id);
  if (!p) return {ok: false, why: "수정안이 없습니다"};
  if (!launcherOn()) return {ok: false, why: "GHNano.exe에서만 코드를 고칠 수 있습니다"};
  if (p.status !== "proposed") return {ok: false, why: "적용할 수 있는 상태가 아닙니다"};
  const text = await source(p.file), c = check(text, p);
  if (!c.ok){ upsert({...p, status: "invalid", check: {ok: false, msg: "지금 코드와 맞지 않음: " + c.msg}}); return {ok: false, why: c.msg}; }
  await ov("POST", {path: "nuri-ai/" + p.file, content: c.patched});
  await ov("POST", null, "/enable").catch(() => null);
  upsert({...p, status: "applied", applied: Date.now(), before: text.length < 1.5e6 ? text : null});
  return {ok: true};
}
export async function revertPatch(id){
  const p = listPatches().find(x => x.id === id);
  if (!p) return {ok: false, why: "수정안이 없습니다"};
  if (!launcherOn()) return {ok: false, why: "GHNano.exe에서만 되돌릴 수 있습니다"};
  // 같은 파일에 먼저 적용된 수정이 있으면 그 직전 상태로, 없으면 원본(exe 안 파일)으로
  const earlier = listPatches().filter(x => x.file === p.file && x.status === "applied" && x.applied < p.applied);
  if (p.before && earlier.length) await ov("POST", {path: "nuri-ai/" + p.file, content: p.before});
  else await ov("DELETE", null, "?path=" + encodeURIComponent("nuri-ai/" + p.file));
  upsert({...p, status: "reverted", reverted: Date.now()});
  return {ok: true};
}
export function rejectPatch(id){ const p = listPatches().find(x => x.id === id); if (p) upsert({...p, status: "rejected"}); return !!p; }
export const reloadSoon = (ms = 800) => setTimeout(() => location.reload(), ms);
// 웹 버전: 수정안을 글로 내려받기
export function patchText(p){ return `# ${p.file} 수정안 (${new Date(p.t).toLocaleString("ko-KR")})\n# 이유: ${p.why}\n# 오류: ${p.error?.msg}\n\n--- 찾을 코드\n${p.find}\n\n+++ 바꿀 코드\n${p.replace}\n`; }
