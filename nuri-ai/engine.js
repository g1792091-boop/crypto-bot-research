// 누리 AI 엔진: 저장소 · 내 기기 AI(wllama) · 두뇌 연결(NVIDIA/Ollama) · 내 지식 검색 · 마크다운
import { Wllama } from "./vendor/wllama/index.js";

/* ============ 공용 ============ */
export const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
export const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
export const fmtN = n => Number(n).toLocaleString("ko-KR");
export const fmtGB = b => b >= 1e9 ? (b/1e9).toFixed(2) + "GB" : Math.max(1, Math.round(b/1e6)) + "MB";
export const ls = {
  get(k, d){ try { const v = localStorage.getItem("nuri:"+k); return v ? JSON.parse(v) : d; } catch(e){ return d; } },
  set(k, v){ try { localStorage.setItem("nuri:"+k, JSON.stringify(v)); } catch(e){} }
};
export const bus = new EventTarget();
const emit = (type, detail) => bus.dispatchEvent(new CustomEvent(type, {detail}));

export const idb = (() => {
  let dbp = null; const mem = new Map();
  const open = () => dbp || (dbp = new Promise((res, rej) => {
    try { const r = indexedDB.open("nuri-ai", 1); r.onupgradeneeded = () => r.result.createObjectStore("kv"); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); }
    catch(e){ rej(e); }
  }));
  const tx = async (mode, fn) => { const db = await open(); return new Promise((res, rej) => { const t = db.transaction("kv", mode); const out = fn(t.objectStore("kv")); t.oncomplete = () => res(out && out.result); t.onerror = () => rej(t.error); }); };
  return {
    async put(k, v){ try { await tx("readwrite", s => s.put(v, k)); } catch(e){ mem.set(k, v); } },
    async del(k){ try { await tx("readwrite", s => s.delete(k)); } catch(e){ mem.delete(k); } },
    async all(prefix){
      try {
        const db = await open();
        return await new Promise((res, rej) => { const out = []; const c = db.transaction("kv").objectStore("kv").openCursor(IDBKeyRange.bound(prefix, prefix + "￿")); c.onsuccess = () => { const cur = c.result; if (cur){ out.push(cur.value); cur.continue(); } else res(out); }; c.onerror = () => rej(c.error); });
      } catch(e){ return [...mem].filter(([k]) => k.startsWith(prefix)).map(([,v]) => v); }
    }
  };
})();

/* ============ 설정 ============ */
export const settings = Object.assign({
  device:"auto", ctx:4096, maxTokens:1024, temp:0.7, think:false, rag:true, last:null, autoload:true,
  brain:"local", nvKey:"", nvModel:"qwen/qwen3-235b-a22b", olModel:"qwen3:14b", olOk:false,
  instructions:"", permission:"ask"
}, ls.get("settings", {}));
export const saveSettings = () => { ls.set("settings", settings); emit("engine"); };

/* ============ 내 기기 AI (wllama = 브라우저 속 llama.cpp) ============ */
export const CATALOG = [
  {id:"qwen3-1.7b", name:"Qwen3 1.7B", repo:"unsloth/Qwen3-1.7B-GGUF", quant:"Q4_K_M", gb:1.1, tags:["추천","다국어","깊게 생각"], lic:"Apache-2.0", desc:"성능과 크기의 균형이 좋습니다."},
  {id:"exaone-2.4b", name:"EXAONE 3.5 2.4B", repo:"LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct-GGUF", quant:"Q4_K_M", gb:1.6, tags:["한국어 특화"], lic:"EXAONE(비상업)", desc:"LG AI연구원 모델. 한국어가 자연스럽습니다."},
  {id:"qwen2.5-0.5b", name:"Qwen2.5 0.5B", repo:"Qwen/Qwen2.5-0.5B-Instruct-GGUF", quant:"Q4_K_M", gb:0.4, tags:["가장 가벼움"], lic:"Apache-2.0", desc:"저사양·휴대폰용. 답이 단순합니다."},
  {id:"qwen2.5-1.5b", name:"Qwen2.5 1.5B", repo:"Qwen/Qwen2.5-1.5B-Instruct-GGUF", quant:"Q4_K_M", gb:1.1, tags:["안정적"], lic:"Apache-2.0", desc:"생각 모드 없이 바로 답합니다."},
  {id:"r1-1.5b", name:"DeepSeek-R1 Distill 1.5B", repo:"unsloth/DeepSeek-R1-Distill-Qwen-1.5B-GGUF", quant:"Q4_K_M", gb:1.1, tags:["추론"], lic:"MIT", desc:"수학·논리용. 한국어는 약합니다."},
  {id:"gemma3-1b", name:"Gemma 3 1B", repo:"unsloth/gemma-3-1b-it-GGUF", quant:"Q4_K_M", gb:0.8, tags:["가벼움"], lic:"Gemma 약관", desc:"Google의 소형 모델."},
  {id:"llama3.2-1b", name:"Llama 3.2 1B", repo:"bartowski/Llama-3.2-1B-Instruct-GGUF", quant:"Q4_K_M", gb:0.8, tags:["영어"], lic:"Llama 3.2 커뮤니티", desc:"Meta의 소형 모델."}
];
const WASM = {default: new URL("./vendor/wllama/wllama.wasm", location.href).href};
export const eng = {w:null, loaded:null, loading:false, progress:0, phase:"", error:"", gpu:false, ctx:0};
let probe = null;
const newWllama = () => new Wllama(WASM, {suppressNativeLog:true, allowOffline:true, parallelDownloads:3});
export const getProbe = () => probe || (probe = newWllama());
export const gpuSupported = () => { try { return getProbe().isSupportWebGPU(); } catch(e){ return false; } };
export let cacheList = [];
export async function refreshCache(){ try { cacheList = await getProbe().cacheManager.list(); } catch(e){ cacheList = []; } return cacheList; }

export async function loadModel(src){
  if (eng.loading) return;
  eng.loading = true; eng.progress = 0; eng.error = ""; eng.phase = "준비 중"; emit("engine");
  try {
    if (eng.w){ try { await eng.w.exit(); } catch(e){} eng.w = null; eng.loaded = null; }
    const useGpu = settings.device === "gpu" || (settings.device === "auto" && gpuSupported());
    const attempt = async gpu => {
      const w = newWllama();
      const params = {n_ctx: settings.ctx, progressCallback: ({loaded, total}) => { eng.progress = total ? loaded/total : 0; eng.phase = `내려받는 중 ${fmtGB(loaded)} / ${total ? fmtGB(total) : "?"}`; emit("engine"); }};
      if (!gpu) params.n_gpu_layers = 0;
      eng.phase = src.kind === "file" ? "파일 읽는 중" : "모델 확인 중"; emit("engine");
      if (src.kind === "hf") await w.loadModelFromHF({repo: src.repo, quant: src.quant, file: src.file}, params);
      else if (src.kind === "url") await w.loadModelFromUrl(src.url, params);
      else await w.loadModel(src.files, params);
      return w;
    };
    let w;
    try { w = await attempt(useGpu); eng.gpu = useGpu; }
    catch (e){ if (!useGpu) throw e; eng.phase = "GPU로 실행하지 못해 CPU로 다시 시도합니다"; emit("engine"); w = await attempt(false); eng.gpu = false; }
    eng.w = w;
    try { eng.ctx = w.getLoadedContextInfo()?.n_ctx || settings.ctx; } catch(e){ eng.ctx = settings.ctx; }
    eng.loaded = {name: src.name, kind: src.kind, id: src.id || null};
    if (src.kind !== "file"){ settings.last = {...src, files: undefined}; ls.set("settings", settings); }
  } catch (e){
    const m = String(e && (e.message || e)) || "";
    eng.error = /Failed to fetch|NetworkError|network/i.test(m) ? "모델 파일을 내려받지 못했습니다. 인터넷 연결을 확인하세요."
      : /No GGUF/i.test(m) ? "저장소에서 GGUF 파일을 찾지 못했습니다."
      : /memory|OOM|allocate|RangeError/i.test(m) ? "메모리가 부족합니다. 더 작은 모델을 고르세요."
      : "불러오기 실패: " + m.slice(0, 200);
  } finally { eng.loading = false; eng.phase = ""; await refreshCache(); emit("engine"); }
}
export async function unloadModel(){ if (eng.w){ try { await eng.w.exit(); } catch(e){} } eng.w = null; eng.loaded = null; emit("engine"); }

/* ============ 실행기(exe) 연결 ============ */
export const LAUNCHER = {on:false};
export async function detectLauncher(){ try { const r = await fetch("/__nuri/ping", {cache:"no-store"}); LAUNCHER.on = r.ok && (await r.text()) === "nuri"; } catch(e){ LAUNCHER.on = false; } return LAUNCHER.on; }
const DIRECT = {nvidia:"https://integrate.api.nvidia.com/v1", ollama:"http://127.0.0.1:11434", upbit:"https://api.upbit.com/v1", binance:"https://api.binance.com/api/v3"};
export const apiBase = name => LAUNCHER.on ? `/__nuri/proxy/${name}` : DIRECT[name];
export async function codeCall(action, body = {}){
  if (!LAUNCHER.on) throw new Error("코드 모드는 NuriAI.exe로 실행했을 때만 쓸 수 있습니다.");
  const r = await fetch("/__nuri/code/" + action, {method:"POST", headers:{"content-type":"application/json", "X-Nuri-Token": window.__NURI_TOKEN || ""}, body: JSON.stringify(body)});
  if (r.status === 403) throw new Error("권한이 없습니다. NuriAI.exe를 다시 실행하세요.");
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || "실패");
  return j;
}

/* ============ 두뇌 ============ */
export const NV_MODELS = [
  ["qwen/qwen3-235b-a22b", "Qwen3 235B · 한국어·종합 (추천)"],
  ["deepseek-ai/deepseek-r1", "DeepSeek-R1 · 깊은 추론"],
  ["openai/gpt-oss-120b", "gpt-oss 120B · 추론"],
  ["meta/llama-3.3-70b-instruct", "Llama 3.3 70B · 빠름"],
  ["moonshotai/kimi-k2-instruct", "Kimi K2 · 코딩·도구 사용"]
];
export const OL_MODELS = [
  ["qwen3:14b", "Qwen3 14B · 약 9GB"],
  ["qwen3:30b", "Qwen3 30B (MoE) · 약 19GB"],
  ["gpt-oss:20b", "gpt-oss 20B · 약 14GB"],
  ["exaone3.5:7.8b", "EXAONE 3.5 7.8B · 한국어"],
  ["qwen2.5-coder:14b", "Qwen2.5 Coder 14B · 코딩"]
];
export const BRAINS = {
  local: {name:"내 기기 AI", where:"이 기기", desc:"오프라인 · 소형 모델"},
  nvidia: {name:"고성능 오픈모델", where:"NVIDIA 클라우드", desc:"가장 똑똑함 · 무료 한도"},
  ollama: {name:"내 PC 대형 모델", where:"Ollama", desc:"오프라인 · 고사양 PC"}
};
export function brainReady(b = settings.brain){ return b === "local" ? !!eng.w : b === "nvidia" ? !!(settings.nvKey && settings.nvModel) : !!(settings.olModel && settings.olOk); }
export function brainLabel(b = settings.brain){ return b === "local" ? (eng.loaded ? eng.loaded.name : "내 기기 AI") : b === "nvidia" ? settings.nvModel.split("/").pop() : (settings.olModel || "Ollama"); }
export const brainCtx = () => settings.brain === "local" ? (eng.ctx || settings.ctx) : settings.brain === "nvidia" ? 32768 : 8192;
export const brainAnswerLen = () => settings.brain === "local" ? Math.min(settings.maxTokens, Math.floor(brainCtx() / 3)) : settings.brain === "nvidia" ? 8192 : 2048;

async function* sse(res){
  const reader = res.body.getReader(), dec = new TextDecoder(); let buf = "";
  for (;;){
    const {value, done} = await reader.read(); if (done) break;
    buf += dec.decode(value, {stream:true});
    let n;
    while ((n = buf.indexOf("\n")) >= 0){
      const line = buf.slice(0, n).replace(/\r$/, ""); buf = buf.slice(n + 1);
      if (line.startsWith("data:")){ const d = line.slice(5).trim(); if (d && d !== "[DONE]"){ try { yield JSON.parse(d); } catch(e){} } }
    }
  }
}
let localLock = Promise.resolve();
export async function brainStream({messages, maxTokens, temperature = 0.6, signal, onContent, onThink, onStats, think, stop}){
  const b = settings.brain;
  if (b === "local"){
    if (!eng.w) throw new Error("내 기기 AI 모델을 먼저 불러오세요. (설정 → AI 두뇌)");
    const go1 = async () => {
      const params = {messages, stream: true, max_tokens: maxTokens, temperature, abortSignal: signal, chat_template_kwargs: {enable_thinking: !!think}};
      if (stop) params.stop = stop;
      if (window.__nuriGenExtra) Object.assign(params, window.__nuriGenExtra);
      const stream = await eng.w.createChatCompletion(params);
      for await (const ch of stream){
        const d = ch.choices?.[0]?.delta || {};
        if (d.reasoning_content) onThink?.(d.reasoning_content);
        if (d.content) onContent?.(d.content);
        if (ch.timings?.predicted_per_second) onStats?.({tps: ch.timings.predicted_per_second});
        if (ch.choices?.[0]?.finish_reason === "length") onStats?.({cut: true});
      }
    };
    const p = localLock.then(go1, go1); localLock = p.catch(() => {}); return p;
  }
  const model = b === "nvidia" ? settings.nvModel : settings.olModel;
  const url = b === "nvidia" ? apiBase("nvidia") + "/chat/completions" : apiBase("ollama") + "/v1/chat/completions";
  const headers = {"content-type": "application/json", accept: "text/event-stream"};
  if (b === "nvidia") headers.authorization = "Bearer " + settings.nvKey;
  const body = {model, messages, stream: true, max_tokens: maxTokens, temperature};
  if (stop) body.stop = stop;
  let res;
  try { res = await fetch(url, {method: "POST", headers, signal, body: JSON.stringify(body)}); }
  catch (e){
    if (signal?.aborted) throw e;
    throw new Error(!LAUNCHER.on ? "웹 버전에서는 브라우저 보안정책 때문에 외부 AI에 바로 연결할 수 없습니다. NuriAI.exe로 실행하세요."
      : b === "ollama" ? "Ollama에 연결하지 못했습니다. Ollama 앱이 켜져 있는지 확인하세요." : "NVIDIA 서버에 연결하지 못했습니다. 인터넷 연결을 확인하세요.");
  }
  if (!res.ok){
    let m = ""; try { const j = await res.json(); m = j.error?.message || j.detail || j.message || j.error || ""; } catch(e){}
    throw new Error(res.status === 401 || res.status === 403 ? "API 키가 올바르지 않습니다. 설정 → AI 두뇌에서 키를 확인하세요."
      : res.status === 404 ? `모델 '${model}'을(를) 찾을 수 없습니다. 설정에서 모델을 다시 고르세요.`
      : res.status === 429 ? "무료 사용 한도나 속도 제한에 걸렸습니다. 잠시 뒤 다시 시도하세요."
      : `AI 서버 오류 ${res.status} ${String(m).slice(0, 160)}`);
  }
  for await (const ev of sse(res)){
    const ch = ev.choices?.[0], d = ch?.delta || {};
    if (d.reasoning_content || d.reasoning) onThink?.(d.reasoning_content || d.reasoning);
    if (d.content) onContent?.(d.content);
    if (ch?.finish_reason === "length") onStats?.({cut: true});
  }
}
export function splitThink(text){
  const t = String(text || ""), s = t.indexOf("<think>");
  if (s === -1){ const e0 = t.indexOf("</think>"); return e0 === -1 ? {think:"", body:t} : {think:t.slice(0, e0).trim(), body:t.slice(e0+8).trim()}; }
  const e = t.indexOf("</think>", s);
  if (e === -1) return {think:t.slice(s+7), body:t.slice(0, s), open:true};
  return {think:t.slice(s+7, e).trim(), body:(t.slice(0, s) + t.slice(e+8)).trim()};
}
// 건축 AI처럼 다른 화면이 누리의 두뇌를 빌려 쓸 수 있게 공개
window.NuriBrain = {
  ready: () => brainReady(),
  label: () => brainLabel(),
  async text(messages, {onText, signal, maxTokens, temperature = 0.4} = {}){
    let content = "";
    await brainStream({messages, maxTokens: maxTokens || Math.min(brainAnswerLen(), 4096), temperature, signal, onContent: d => { content += d; onText?.(splitThink(content).body); }});
    return splitThink(content).body.trim();
  }
};

/* ============ 내 지식 (문서 검색, BM25) ============ */
export let docs = [];
const idx = {chunks:[], df:new Map(), avg:1};
export function tokenize(s){
  const out = []; const t = String(s).toLowerCase();
  for (const m of t.matchAll(/[가-힣]+|[a-z0-9]+|[぀-ヿ一-鿿]+/g)){
    const w = m[0];
    if (/^[a-z0-9]+$/.test(w)){ if (w.length >= 2) out.push(w); continue; }
    if (w.length === 1){ out.push(w); continue; }
    for (let i = 0; i < w.length - 1; i++) out.push(w.slice(i, i+2));
  }
  return out;
}
export function chunkText(text, size = 700, overlap = 120){
  const clean = text.replace(/\r/g, "").replace(/\n{3,}/g, "\n\n").trim();
  const paras = clean.split(/\n\s*\n/); const chunks = []; let cur = "";
  for (const p of paras){
    if ((cur + "\n\n" + p).length > size && cur){ chunks.push(cur); cur = cur.slice(-overlap) + "\n\n" + p; }
    else cur = cur ? cur + "\n\n" + p : p;
    while (cur.length > size * 1.6){ chunks.push(cur.slice(0, size)); cur = cur.slice(size - overlap); }
  }
  if (cur.trim()) chunks.push(cur);
  return chunks;
}
function rebuildIndex(){
  idx.chunks = []; idx.df = new Map(); let total = 0;
  for (const d of docs) d.chunks.forEach((text, i) => {
    const tf = new Map(); const toks = tokenize(d.name + " " + text);
    for (const t of toks) tf.set(t, (tf.get(t) || 0) + 1);
    for (const t of tf.keys()) idx.df.set(t, (idx.df.get(t) || 0) + 1);
    idx.chunks.push({doc:d.id, name:d.name, i, text, tf, len:toks.length}); total += toks.length;
  });
  idx.avg = idx.chunks.length ? total / idx.chunks.length : 1;
}
export function search(q, k = 4){
  const qt = [...new Set(tokenize(q))]; if (!qt.length || !idx.chunks.length) return [];
  const N = idx.chunks.length, k1 = 1.2, b = 0.75;
  const scored = idx.chunks.map(c => {
    let s = 0;
    for (const t of qt){ const f = c.tf.get(t); if (!f) continue; const df = idx.df.get(t) || 0; const idf = Math.log(1 + (N - df + .5)/(df + .5)); s += idf * f * (k1+1) / (f + k1*(1 - b + b*c.len/idx.avg)); }
    return {c, s};
  }).filter(x => x.s > 0).sort((a,b) => b.s - a.s);
  if (!scored.length) return [];
  const top = scored[0].s;
  return scored.filter(x => x.s >= top * 0.35).slice(0, k).map(x => ({...x.c, score:x.s}));
}
export async function loadDocs(){ docs = await idb.all("doc:"); rebuildIndex(); return docs; }
export async function addDoc(name, text){
  const d = {id: uid(), name: name.slice(0, 80), size: text.length, added: Date.now(), chunks: chunkText(text)};
  if (!d.chunks.length) return null;
  docs.push(d); await idb.put("doc:" + d.id, d); rebuildIndex(); return d;
}
export async function removeDoc(id){ docs = docs.filter(d => d.id !== id); await idb.del("doc:" + id); rebuildIndex(); }
export function htmlToText(s){ const d = new DOMParser().parseFromString(s, "text/html"); d.querySelectorAll("script,style,noscript").forEach(n => n.remove()); return d.body ? d.body.innerText || d.body.textContent : s; }
export async function readTextFile(f){
  if (f.size > 5e6) throw new Error(f.name + ": 5MB 이하 텍스트 파일만 읽을 수 있습니다");
  let text = await f.text();
  if (/\u0000/.test(text.slice(0, 2000))) throw new Error(f.name + ": 텍스트 형식이 아닙니다");
  if (/\.html?$/i.test(f.name)) text = htmlToText(text);
  return text;
}

/* ============ 마크다운 + 코드 강조 ============ */
const KW = /\b(function|return|const|let|var|if|else|for|while|class|import|from|export|def|async|await|try|catch|except|finally|new|in|of|and|or|not|True|False|None|true|false|null|undefined|public|private|static|void|int|string|fn|pub|use|struct|type|interface|package|func|go|defer|select|with|as|lambda|yield|raise|switch|case|break|continue|SELECT|FROM|WHERE|JOIN|GROUP|BY|ORDER|INSERT|UPDATE|DELETE)\b/g;
export function highlight(code){
  const out = []; let last = 0;
  const re = /(\/\/[^\n]*|#[^\n]*|\/\*[\s\S]*?\*\/|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`|\b\d+(?:\.\d+)?\b)/g;
  let m;
  while ((m = re.exec(code))){
    out.push(esc(code.slice(last, m.index)).replace(KW, '<span class="k">$1</span>'));
    const t = m[0], cls = /^(\/\/|#|\/\*)/.test(t) ? "c" : /^\d/.test(t) ? "n" : "s";
    out.push(`<span class="${cls}">${esc(t)}</span>`); last = m.index + t.length;
  }
  out.push(esc(code.slice(last)).replace(KW, '<span class="k">$1</span>'));
  return out.join("");
}
function inline(s){
  const codes = [];
  s = s.replace(/`([^`\n]+)`/g, (_, c) => { codes.push(c); return "\u0000" + (codes.length-1) + "\u0000"; });
  s = esc(s);
  s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>").replace(/__([^_\n]+)__/g, "<strong>$1</strong>")
       .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>").replace(/~~([^~\n]+)~~/g, "<del>$1</del>")
       .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
       .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => "<code>" + esc(codes[+i]) + "</code>");
}
export function md(src){
  const lines = String(src).replace(/\r/g, "").split("\n"), out = [];
  let i = 0;
  const isSep = l => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
  const cells = l => l.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
  const blockStart = /^(#{1,6}\s|\s*```|\s*~~~|\s*>|\s*([-*+]|\d+[.)])\s)/;
  while (i < lines.length){
    const l = lines[i];
    const fence = l.match(/^\s*(```|~~~)\s*([\w+#.-]*)/);
    if (fence){
      const buf = []; i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) buf.push(lines[i++]);
      i++;
      out.push(`<div class="codebox"><div class="bar"><span>${esc(fence[2] || "code")}</span><button data-copy>복사</button></div><pre><code>${highlight(buf.join("\n"))}</code></pre></div>`);
      continue;
    }
    if (/^\s*$/.test(l)){ i++; continue; }
    const h = l.match(/^(#{1,6})\s+(.*)$/);
    if (h){ const n = Math.min(4, h[1].length); out.push(`<h${n}>${inline(h[2])}</h${n}>`); i++; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(l)){ out.push("<hr>"); i++; continue; }
    if (l.includes("|") && i+1 < lines.length && isSep(lines[i+1])){
      const head = cells(l); i += 2; const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(cells(lines[i++]));
      out.push(`<div class="tbl"><table><thead><tr>${head.map(c => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      continue;
    }
    if (/^\s*>/.test(l)){ const buf = []; while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, "")); out.push(`<blockquote>${md(buf.join("\n"))}</blockquote>`); continue; }
    const li = l.match(/^(\s*)([-*+]|\d+[.)])\s+/);
    if (li){
      const ordered = /\d/.test(li[2]), items = [];
      while (i < lines.length){
        const m = lines[i].match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
        if (m && m[1].length <= li[1].length + 1){ items.push([m[3]]); i++; continue; }
        if (items.length && /^\s{2,}\S/.test(lines[i])){ items[items.length-1].push(lines[i].trim()); i++; continue; }
        break;
      }
      out.push(`<${ordered?"ol":"ul"}>${items.map(it => `<li>${it.length > 1 && /^([-*+]|\d+[.)])\s/.test(it[1]) ? inline(it[0]) + md(it.slice(1).join("\n")) : inline(it.join(" "))}</li>`).join("")}</${ordered?"ol":"ul"}>`);
      continue;
    }
    const buf = [];
    while (i < lines.length && lines[i].trim() && !blockStart.test(lines[i]) && !(lines[i].includes("|") && i+1 < lines.length && isSep(lines[i+1]))) buf.push(lines[i++]);
    if (!buf.length) buf.push(lines[i++]);
    out.push(`<p>${buf.map(inline).join("<br>")}</p>`);
  }
  return out.join("");
}
