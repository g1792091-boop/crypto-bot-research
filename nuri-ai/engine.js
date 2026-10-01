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
  device:"auto", ctx:8192, maxTokens:1024, temp:0.7, think:false, rag:true, last:null, autoload:true,
  brain:"auto", nvKey:"", nvModel:"qwen/qwen3-235b-a22b", olModel:"hf.co/unsloth/Qwen3.5-4B-GGUF:Q4_K_M", olOk:false,
  instructions:"", permission:"ask", keys:{}, provModels:{}, pinModel:{}, memory:[], skills:[], aiName:"GH Nano", nvSkills:true, nvAuto:true
}, ls.get("settings", {}));
if (settings.nvKey && !settings.keys.nvidia) settings.keys.nvidia = settings.nvKey;   // 예전 설정 옮기기
if (!settings.ctxV){ if (settings.ctx === 4096) settings.ctx = 8192; settings.ctxV = 2; }       // 지시문이 길어져 기본 기억 길이를 늘림
if (!settings.keys) settings.keys = {};
export const saveSettings = () => { ls.set("settings", settings); emit("engine"); };

/* ============ 내 기기 AI (wllama = 브라우저 속 llama.cpp) ============ */
export const CATALOG = [
  {id:"qwen3.5-2b", name:"Qwen3.5 2B", repo:"unsloth/Qwen3.5-2B-GGUF", quant:"Q4_K_M", gb:1.3, tags:["추천","2026","다국어"], lic:"Apache-2.0", desc:"2026년 3월 공개된 최신 소형 모델. RTX 3050 노트북에서 가볍게 돕니다. 직접 학습 바탕 모델로도 추천."},
  {id:"qwen3.5-0.8b", name:"Qwen3.5 0.8B", repo:"unsloth/Qwen3.5-0.8B-GGUF", quant:"Q4_K_M", gb:0.6, tags:["2026","가장 가벼움"], lic:"Apache-2.0", desc:"아주 가볍고 빠릅니다. 저사양 노트북·로컬 학습용."},
  {id:"exaone4-1.2b", name:"EXAONE 4.0 1.2B", repo:"LGAI-EXAONE/EXAONE-4.0-1.2B-GGUF", quant:"Q4_K_M", gb:0.8, tags:["한국어 특화","추론 모드"], lic:"EXAONE(비상업)", desc:"LG AI연구원 최신 소형 모델. 한국어가 자연스럽습니다. 개인·연구·교육용."},
  {id:"qwen3-1.7b", name:"Qwen3 1.7B", repo:"unsloth/Qwen3-1.7B-GGUF", quant:"Q4_K_M", gb:1.1, tags:["추천","다국어","깊게 생각"], lic:"Apache-2.0", desc:"성능과 크기의 균형이 좋습니다."},
  {id:"exaone-2.4b", name:"EXAONE 3.5 2.4B", repo:"LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct-GGUF", quant:"Q4_K_M", gb:1.6, tags:["한국어 특화"], lic:"EXAONE(비상업)", desc:"LG AI연구원 모델. 한국어가 자연스럽습니다."},
  {id:"qwen2.5-0.5b", name:"Qwen2.5 0.5B", repo:"Qwen/Qwen2.5-0.5B-Instruct-GGUF", quant:"Q4_K_M", gb:0.4, tags:["가장 가벼움"], lic:"Apache-2.0", desc:"저사양·휴대폰용. 답이 단순합니다."},
  {id:"qwen2.5-1.5b", name:"Qwen2.5 1.5B", repo:"Qwen/Qwen2.5-1.5B-Instruct-GGUF", quant:"Q4_K_M", gb:1.1, tags:["안정적"], lic:"Apache-2.0", desc:"생각 모드 없이 바로 답합니다."},
  {id:"r1-1.5b", name:"DeepSeek-R1 Distill 1.5B", repo:"unsloth/DeepSeek-R1-Distill-Qwen-1.5B-GGUF", quant:"Q4_K_M", gb:1.1, tags:["추론"], lic:"MIT", desc:"수학·논리용. 답하기 전에 생각을 길게 해서 기억 길이를 많이 쓰고, 도구 사용과 한국어는 약합니다. 일상 대화는 Qwen3.5를 추천."},
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
      else if (src.kind === "opfs") await w.loadModel(await opfsFiles(src.dir), params);
      else await w.loadModel(src.files, params);
      return w;
    };
    let w;
    try { w = await attempt(useGpu); eng.gpu = useGpu; }
    catch (e){ if (!useGpu) throw e; eng.phase = "GPU로 실행하지 못해 CPU로 다시 시도합니다"; emit("engine"); w = await attempt(false); eng.gpu = false; }
    eng.w = w;
    try { const ci = w.getLoadedContextInfo() || {}; eng.ctx = Math.min(ci.n_ctx || settings.ctx, ci.n_ctx_train || Infinity); } catch(e){ eng.ctx = settings.ctx; }   // 모델이 배운 길이보다 길게는 못 씀
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
// 내가 학습한 모델: 브라우저 저장소(OPFS)에 보관해 다음 실행 때 자동으로 켠다 (Ollama 없이)
const opfsRoot = async () => (await navigator.storage.getDirectory()).getDirectoryHandle("models", {create: true});
export async function opfsSave(name, files, onPhase){
  try { await navigator.storage.persist?.(); } catch(e){}
  const dir = await (await opfsRoot()).getDirectoryHandle(name, {create: true});
  for (const f of files){
    onPhase?.(`${f.name} 저장 중…`);
    const h = await dir.getFileHandle(f.name, {create: true}), w = await h.createWritable();
    await f.stream().pipeTo(w);
  }
  return name;
}
export async function opfsFiles(name){
  const dir = await (await opfsRoot()).getDirectoryHandle(name);
  const out = []; for await (const [n, h] of dir.entries()) if (h.kind === "file" && /\.gguf$/i.test(n)) out.push(await h.getFile());
  if (!out.length) throw new Error("저장된 모델 파일이 없습니다: " + name);
  return out.sort((a, b) => a.name.localeCompare(b.name));
}
export async function opfsList(){
  try { const root = await opfsRoot(), out = []; for await (const [n, h] of root.entries()) if (h.kind === "directory"){ let size = 0; for await (const [, f] of h.entries()) if (f.kind === "file") size += (await f.getFile()).size; out.push({name: n, size}); } return out; }
  catch(e){ return []; }
}
export async function opfsRemove(name){ await (await opfsRoot()).removeEntry(name, {recursive: true}); }
export async function unloadModel(){ if (eng.w){ try { await eng.w.exit(); } catch(e){} } eng.w = null; eng.loaded = null; emit("engine"); }

/* ============ 실행기(exe) 연결 ============ */
export const LAUNCHER = {on:false};
export async function detectLauncher(){ try { const r = await fetch("/__nuri/ping", {cache:"no-store"}); LAUNCHER.on = r.ok && (await r.text()) === "nuri"; } catch(e){ LAUNCHER.on = false; } return LAUNCHER.on; }
const DIRECT = {nvidia:"https://integrate.api.nvidia.com/v1", nvgenai:"https://ai.api.nvidia.com/v1/genai", ollama:"http://127.0.0.1:11434", upbit:"https://api.upbit.com/v1", binance:"https://api.binance.com/api/v3", binancef:"https://fapi.binance.com", tavily:"https://api.tavily.com", brave:"https://api.search.brave.com/res/v1"};
export const apiBase = name => LAUNCHER.on ? `/__nuri/proxy/${name}` : DIRECT[name];
export async function codeCall(action, body = {}){
  if (!LAUNCHER.on) throw new Error("코드 모드는 GHNano.exe로 실행했을 때만 쓸 수 있습니다.");
  const r = await fetch("/__nuri/code/" + action, {method:"POST", headers:{"content-type":"application/json", "X-Nuri-Token": window.__NURI_TOKEN || ""}, body: JSON.stringify(body)});
  if (r.status === 403) throw new Error("권한이 없습니다. GHNano.exe를 다시 실행하세요.");
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || "실패");
  return j;
}

/* ============ 두뇌: 여러 AI 회사 + 자동 선택 ============ */
// 키만 넣으면 회사를 알아보고, 질문 종류에 맞는 모델을 고르며, 막히면 다른 곳으로 바꾼다
export const PROVIDERS = {
  nvidia:     {name:"NVIDIA", proxy:"nvidia", base:"https://integrate.api.nvidia.com/v1", key:/^nvapi-/, url:"https://build.nvidia.com", note:"대형 오픈모델 다수 · 무료 한도", bias:0,
               defaults:["qwen/qwen3-235b-a22b","deepseek-ai/deepseek-v3.1","deepseek-ai/deepseek-r1","openai/gpt-oss-120b","openai/gpt-oss-20b","moonshotai/kimi-k2-instruct","qwen/qwen3-coder-480b-a35b-instruct",
                 "nvidia/llama-3.3-nemotron-super-49b-v1.5","nvidia/nvidia-nemotron-nano-9b-v2","meta/llama-4-maverick-17b-128e-instruct","meta/llama-3.3-70b-instruct","meta/llama-3.2-90b-vision-instruct",
                 "google/gemma-3-27b-it","mistralai/mistral-medium-3-instruct","microsoft/phi-4-multimodal-instruct","nvidia/llama-3.2-nv-embedqa-1b-v2","nvidia/llama-3.2-nv-rerankqa-1b-v2"]},
  groq:       {name:"Groq", proxy:"groq", base:"https://api.groq.com/openai/v1", key:/^gsk_/, url:"https://console.groq.com/keys", note:"매우 빠름 · 무료 한도", bias:1,
               defaults:["openai/gpt-oss-120b","llama-3.3-70b-versatile","qwen/qwen3-32b","moonshotai/kimi-k2-instruct","llama-3.1-8b-instant"]},
  cerebras:   {name:"Cerebras", proxy:"cerebras", base:"https://api.cerebras.ai/v1", key:/^csk-/, url:"https://cloud.cerebras.ai", note:"매우 빠름 · 무료 한도", bias:1,
               defaults:["qwen-3-235b-a22b-instruct-2507","gpt-oss-120b","llama-3.3-70b","qwen-3-coder-480b"]},
  gemini:     {name:"Google Gemini", proxy:"gemini", base:"https://generativelanguage.googleapis.com/v1beta/openai", key:/^AIza/, url:"https://aistudio.google.com/apikey", note:"무료 한도", bias:2,
               defaults:["gemini-2.5-pro","gemini-2.5-flash","gemini-2.0-flash"]},
  openrouter: {name:"OpenRouter", proxy:"openrouter", base:"https://openrouter.ai/api/v1", key:/^sk-or-/, url:"https://openrouter.ai/keys", note:"':free' 모델은 무료", bias:3,
               defaults:["deepseek/deepseek-chat-v3-0324:free","qwen/qwen3-235b-a22b:free","deepseek/deepseek-r1:free","meta-llama/llama-3.3-70b-instruct:free"]},
  hf:         {name:"Hugging Face", proxy:"hf", base:"https://router.huggingface.co/v1", key:/^hf_/, url:"https://huggingface.co/settings/tokens", note:"월 무료 크레딧", bias:4,
               defaults:["Qwen/Qwen3-235B-A22B","deepseek-ai/DeepSeek-V3-0324","meta-llama/Llama-3.3-70B-Instruct"]},
  mistral:    {name:"Mistral", proxy:"mistral", base:"https://api.mistral.ai/v1", key:null, url:"https://console.mistral.ai/api-keys", note:"무료 체험 요금제", bias:4, defaults:["mistral-large-latest","codestral-latest","mistral-small-latest"]},
  deepseek:   {name:"DeepSeek", proxy:"deepseek", base:"https://api.deepseek.com", key:/^sk-[a-f0-9]{32}$/, url:"https://platform.deepseek.com/api_keys", note:"유료(저렴)", bias:3, defaults:["deepseek-chat","deepseek-reasoner"]},
  together:   {name:"Together", proxy:"together", base:"https://api.together.xyz/v1", key:/^tgp_/, url:"https://api.together.ai/settings/api-keys", note:"일부 무료 모델", bias:4, defaults:["meta-llama/Llama-3.3-70B-Instruct-Turbo-Free","deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free"]},
  sambanova:  {name:"SambaNova", proxy:"sambanova", base:"https://api.sambanova.ai/v1", key:null, url:"https://cloud.sambanova.ai/apis", note:"무료 한도", bias:3, defaults:["DeepSeek-V3-0324","Meta-Llama-3.3-70B-Instruct","DeepSeek-R1"]}
};
export const SEARCH_KEYS = {tavily:{name:"Tavily 검색", key:/^tvly-/, url:"https://app.tavily.com"}, brave:{name:"Brave 검색", key:/^BSA/, url:"https://brave.com/search/api/"}};
const NOT_CHAT = /embed|rerank|guard|safety|reward|whisper|tts|speech|audio|vision-?only|clip|parse|retriever|ocr|flux|sdxl|stable-diffusion|image|moderation|nemoretriever|nv-embed|paligemma|kosmos|deplot|fuyu|neva|vila|cosmos/i;
// 이미지를 볼 수 있는 모델
export const VISION_RE = /llama-4|vision|[-_.]vl\b|-vl-|qwen\d?(\.\d)?-?vl|gemma-3-(4|12|27)b|gemma-4|gemini|phi-4-multimodal|phi-3\.5-vision|kimi-vl|pixtral|mistral-small-3|mistral-medium-3|nemotron.*vl|cosmos-reason|qwen3\.5/i;
// 모델 종류 (모델 탐색기에 표시)
export function modelKind(id){
  id = String(id);
  if (/embed|retriever|nv-embed|arctic-embed|bge-|e5-/i.test(id)) return "embed";
  if (/rerank/i.test(id)) return "rerank";
  if (/flux|stable-diffusion|sdxl|sd3|sana|consistory|edify|image-gen|kandinsky/i.test(id)) return "image";
  if (/whisper|asr|parakeet|canary|tts|speech|audio|fastpitch|riva/i.test(id)) return "speech";
  if (/guard|safety|shield|nemoguard|content-safety|jailbreak/i.test(id)) return "safety";
  if (/reward/i.test(id)) return "reward";
  if (VISION_RE.test(id)) return "vision";
  if (/coder|codestral|starcoder|codellama|deepseek-coder|devstral/i.test(id)) return "code";
  if (/r1|reason|think|qwq|o1|o3|magistral/i.test(id)) return "reason";
  return "chat";
}
export const KIND_KO = {chat: "대화", code: "코딩", reason: "추론", vision: "이미지 이해", image: "이미지 생성", embed: "임베딩", rerank: "재정렬", speech: "음성", safety: "안전 필터", reward: "보상 모델"};
const ROLE_RANK = {
  vision:  [/llama-4-maverick/i, /qwen3\.5|qwen3-vl/i, /gemini-2\.5-pro/i, /llama-4-scout/i, /qwen2\.5-vl-72b|qwen2\.5-vl/i, /gemma-4|gemma-3-27b/i, /llama-3\.2-90b-vision/i, /mistral-medium-3|pixtral/i, /gemini/i, /phi-4-multimodal/i, /kimi-vl/i, /./],
  general: [/qwen3-235b|qwen-3-235b/i, /deepseek-(v3|chat)/i, /kimi-k2/i, /gpt-oss-120b/i, /gemini-2\.5-pro/i, /llama-?4|llama-3\.3-70b|llama-3\.1-405b/i, /gemini-2\.5-flash/i, /mistral-large/i, /qwen3-32b|qwen-?2\.5-72b/i, /nemotron.*(super|ultra)/i, /gemini/i, /qwen/i, /llama/i, /./],
  code:    [/qwen3-coder|qwen-3-coder/i, /kimi-k2/i, /deepseek-(v3|chat)/i, /gpt-oss-120b/i, /codestral/i, /qwen2\.5-coder/i, /qwen3-235b|qwen-3-235b/i, /gemini-2\.5-pro/i, /llama-3\.3-70b/i, /./],
  reason:  [/deepseek-r1|deepseek-reasoner/i, /gpt-oss-120b/i, /qwen3-235b|qwen-3-235b/i, /gemini-2\.5-pro/i, /qwq/i, /kimi-k2/i, /deepseek-(v3|chat)/i, /./],
  fast:    [/gpt-oss-120b/i, /llama-3\.3-70b/i, /qwen3-32b/i, /gemini-2\.5-flash|gemini-2\.0-flash/i, /llama-3\.1-8b/i, /./]
};
export function rankModel(id, role = "general"){ if (role === "vision"){ if (!VISION_RE.test(id) || /embed|rerank|guard|safety|reward/i.test(id)) return 999; } else if (NOT_CHAT.test(id)) return 999; const r = ROLE_RANK[role] || ROLE_RANK.general; const k = r.findIndex(re => re.test(id)); return k < 0 ? 900 : k; }
export function detectKeyKind(key){
  key = String(key || "").trim();
  for (const [id, p] of Object.entries(SEARCH_KEYS)) if (p.key.test(key)) return {kind:"search", id};
  for (const [id, p] of Object.entries(PROVIDERS)) if (p.key && p.key.test(key)) return {kind:"ai", id};
  return null;
}
const provBase = id => LAUNCHER.on ? `/__nuri/proxy/${PROVIDERS[id].proxy}` : PROVIDERS[id].base;
export async function listProviderModels(id, key = settings.keys[id]){
  const r = await fetch(provBase(id) + "/models", {headers: {authorization: "Bearer " + key}});
  if (!r.ok){ const e = new Error(`${PROVIDERS[id].name} ${r.status}`); e.status = r.status; throw e; }
  const j = await r.json();
  return (j.data || j.models || []).map(m => String(m.id || m.name || "").replace(/^models\//, "")).filter(Boolean);   // 모든 모델 (종류는 modelKind로 구분)
}
// 키를 붙여넣으면 어느 회사 것인지 알아내고 모델 목록을 받아 둔다
export async function addApiKey(raw){
  const key = String(raw || "").trim(); if (!key) throw new Error("키를 붙여넣으세요");
  const d = detectKeyKind(key);
  if (d && d.kind === "search"){ settings.keys[d.id] = key; saveSettings(); return {kind:"search", id:d.id, name:SEARCH_KEYS[d.id].name}; }
  const order = d ? [d.id] : Object.keys(PROVIDERS).filter(id => !PROVIDERS[id].key || id === "deepseek");
  let lastErr = null;
  for (const id of order){
    try {
      const models = await listProviderModels(id, key);
      settings.keys[id] = key; settings.provModels[id] = models.length ? models : PROVIDERS[id].defaults;
      if (!settings.brain || settings.brain === "local" && !eng.w) settings.brain = "auto";
      saveSettings(); return {kind:"ai", id, name:PROVIDERS[id].name, models: settings.provModels[id].length};
    } catch(e){ lastErr = e; if (d) break; }
  }
  if (d){ settings.keys[d.id] = key; settings.provModels[d.id] = PROVIDERS[d.id].defaults; if (!settings.brain || settings.brain === "local") settings.brain = "auto"; saveSettings(); return {kind:"ai", id:d.id, name:PROVIDERS[d.id].name, models:0, warn: lastErr ? lastErr.message : ""}; }
  throw new Error("어느 회사 키인지 알 수 없거나 연결에 실패했습니다" + (lastErr ? ` (${lastErr.message})` : ""));
}
export function removeApiKey(id){ delete settings.keys[id]; delete settings.provModels[id]; delete settings.pinModel[id]; if (settings.brain === id) settings.brain = "auto"; saveSettings(); }
const cooldown = {};
const connected = () => Object.keys(PROVIDERS).filter(id => settings.keys[id]);
// 후보 목록: 회사마다 그 역할에 가장 맞는 모델 하나씩, 순위 순
export function routeCandidates(role = "general"){
  const out = [];
  for (const id of connected()){
    const models = settings.pinModel[id] ? [settings.pinModel[id]] : (settings.provModels[id] && settings.provModels[id].length ? settings.provModels[id] : PROVIDERS[id].defaults);
    let pool = models;
    if (id === "openrouter"){ const free = models.filter(m => /:free$/.test(m)); if (free.length) pool = free; }
    const best = pool.map(m => ({m, r: rankModel(m, role)})).filter(x => x.r < 999).sort((a, b) => a.r - b.r)[0];
    if (best) out.push({id, model: best.m, score: best.r * 10 + PROVIDERS[id].bias});
  }
  // 방금 한도·오류에 걸린 곳은 잠시 뒤로 미룬다
  const now = Date.now();
  out.forEach(c => { if ((cooldown[c.id] || 0) > now) c.score += 10000; });
  out.sort((a, b) => a.score - b.score);
  if (settings.olModel && settings.olOk) out.push({id:"ollama", model: settings.olModel, score: 5000});
  if (eng.w) out.push({id:"local", model: eng.loaded?.name || "local", score: 9000});
  return out;
}
export const BRAINS = {
  auto:   {get name(){ return settings.aiName || "GH Nano"; }, where:"여러 AI", desc:"모든 모델·스킬을 하나로 묶은 내 AI · 질문마다 알맞은 모델을 고르고 막히면 바꿈"},
  local:  {name:"내 기기 AI", where:"이 기기", desc:"오프라인 · 소형 모델"},
  ollama: {name:"내 PC 대형 모델", where:"Ollama", desc:"오프라인 · 고사양 PC"}
};
export const OL_MODELS = [
  ["hf.co/unsloth/Qwen3.5-4B-GGUF:Q4_K_M", "Qwen3.5 4B · 약 2.7GB · RTX 3050 추천(가장 똑똑)"],
  ["hf.co/unsloth/Qwen3.5-2B-GGUF:Q4_K_M", "Qwen3.5 2B · 약 1.3GB · RTX 3050 빠름"],
  ["hf.co/unsloth/gemma-4-E2B-it-GGUF:Q4_K_M", "Gemma 4 E2B · 약 3GB · 다국어"],
  ["hf.co/LGAI-EXAONE/EXAONE-4.0-1.2B-GGUF:Q4_K_M", "EXAONE 4.0 1.2B · 한국어 · 비상업"],
  ["hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M", "Qwen3.5 9B · 약 5.5GB · 4GB 그래픽카드는 느림"],
  ["hf.co/unsloth/gemma-4-E4B-it-GGUF:Q4_K_M", "Gemma 4 E4B · 약 5GB · 고사양"],
  ["qwen3:14b", "Qwen3 14B · 약 9GB · 고사양 PC"], ["gpt-oss:20b", "gpt-oss 20B · 약 14GB · 고사양 PC"]
];
// Ollama: 모델 받기(진행률) · 내가 학습한 GGUF 등록
export async function ollamaPull(model, onProgress, signal){
  const r = await fetch(apiBase("ollama") + "/api/pull", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify({model, stream: true}), signal});
  if (!r.ok) throw new Error("Ollama 응답 오류 " + r.status + " (Ollama가 켜져 있는지 확인하세요)");
  const reader = r.body.getReader(), dec = new TextDecoder(); let buf = "", last = null;
  for (;;){
    const {value, done} = await reader.read(); if (done) break;
    buf += dec.decode(value, {stream: true}); let n;
    while ((n = buf.indexOf("\n")) >= 0){ const line = buf.slice(0, n).trim(); buf = buf.slice(n + 1); if (!line) continue; try { last = JSON.parse(line); } catch(e){ continue; } if (last.error) throw new Error(last.error); onProgress?.(last); }
  }
  return last;
}
export async function ollamaImportGGUF(file, name, onPhase){
  onPhase?.("파일 지문(SHA-256) 계산 중…");
  const hex = [...new Uint8Array(await crypto.subtle.digest("SHA-256", await file.arrayBuffer()))].map(b => b.toString(16).padStart(2, "0")).join("");
  const digest = "sha256:" + hex, base = apiBase("ollama");
  const head = await fetch(base + "/api/blobs/" + digest, {method: "HEAD"});
  if (head.status !== 200){
    onPhase?.("Ollama로 옮기는 중…");
    const up = await fetch(base + "/api/blobs/" + digest, {method: "POST", body: file});
    if (!up.ok) throw new Error("Ollama에 파일을 올리지 못했습니다 (" + up.status + ")");
  }
  onPhase?.("모델 등록 중…");
  const r = await fetch(base + "/api/create", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify({model: name, files: {[file.name]: digest}, stream: false})});
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.error) throw new Error("등록 실패: " + (j.error || r.status));
  return name;
}
export const NV_MODELS = PROVIDERS.nvidia.defaults.map(m => [m, m]);
export let lastRoute = null;
export function brainReady(b = settings.brain){
  if (b === "local") return !!eng.w;
  if (b === "ollama") return !!(settings.olModel && settings.olOk);
  if (b === "auto") return routeCandidates().length > 0;
  return !!(PROVIDERS[b] && settings.keys[b]);
}
export function brainLabel(b = settings.brain){
  if (b === "local") return eng.loaded ? eng.loaded.name : "내 기기 AI";
  if (b === "ollama") return settings.olModel || "Ollama";
  if (b === "auto"){ const c = routeCandidates(); return (settings.aiName || "GH Nano") + (c.length ? " · " + shortModel(c[0].model) : ""); }
  if (PROVIDERS[b]) return shortModel(settings.pinModel[b] || routeCandidates().find(c => c.id === b)?.model || PROVIDERS[b].name);
  return b;
}
export const shortModel = m => String(m || "").split("/").pop().replace(/:free$/, "").replace(/-instruct(-\d+)?$/i, "");
// 실제로 답할 곳 (자동 선택인데 연결된 회사가 없으면 내 기기 AI가 답한다)
export const effectiveBrain = (role = "general") => settings.brain === "auto" ? (routeCandidates(role)[0]?.id || "auto") : settings.brain;
export const brainCtx = (role) => { const b = effectiveBrain(role); return b === "local" ? (eng.ctx || settings.ctx) : b === "ollama" ? 8192 : 32768; };
export const brainAnswerLen = (role) => { const b = effectiveBrain(role); return b === "local" ? Math.min(settings.maxTokens, Math.floor(brainCtx(role) / 3)) : b === "ollama" ? 2048 : 8192; };
// 토큰 수 어림: 한글은 글자당 1토큰 이상 들기 때문에 넉넉하게 센다 (예전 '글자÷1.6'은 한국어를 절반 이하로 셌다)
export function estTokens(s){ s = String(s || ""); const ko = (s.match(/[\u3131-\u318e\uac00-\ud7a3]/g) || []).length; return Math.ceil(ko * 1.4 + (s.length - ko) / 2.8) + 4; }

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
function stripImages(messages, why){ return messages.map(m => m.images?.length ? {role: m.role, content: m.content + `\n[이미지 ${m.images.length}장이 첨부됐지만 ${why}]`} : {role: m.role, content: m.content}); }
let localLock = Promise.resolve();
async function streamLocal({messages, maxTokens, temperature, signal, onContent, onThink, onStats, think, stop}){
  if (!eng.w) throw new Error("내 기기 AI 모델을 먼저 불러오세요. (설정 → AI 두뇌)");
  const go1 = async () => {
    messages = stripImages(messages, "이 모델은 이미지를 볼 수 없습니다");
    const params = {messages, stream: true, max_tokens: Math.min(maxTokens, Math.floor((eng.ctx || settings.ctx) / 3)), temperature, abortSignal: signal, chat_template_kwargs: {enable_thinking: !!think}};
    if (stop) params.stop = stop;
    if (window.__nuriGenExtra) Object.assign(params, window.__nuriGenExtra);
    try {
      const stream = await eng.w.createChatCompletion(params);
      for await (const ch of stream){
        const d = ch.choices?.[0]?.delta || {};
        if (d.reasoning_content) onThink?.(d.reasoning_content);
        if (d.content) onContent?.(d.content);
        if (ch.timings?.predicted_per_second) onStats?.({tps: ch.timings.predicted_per_second});
        if (ch.choices?.[0]?.finish_reason === "length") onStats?.({cut: true});
      }
    } catch (e){
      if (signal?.aborted) throw e;
      const m = String(e?.message || e);
      const ctxM = m.match(/\((\d+) tokens\) exceeds the available context size \((\d+) tokens\)/);
      if (ctxM || /exceed_context/i.test(m)) throw new Error(`질문·지시문이 이 모델의 기억 길이(${ctxM ? ctxM[2] : eng.ctx}토큰)를 넘었습니다${ctxM ? ` (필요 ${ctxM[1]}토큰)` : ""}. 새 대화로 시작하거나, 설정 → 내 기기 모델에서 '대화 기억 길이'를 늘린 뒤 모델을 다시 불러오세요.`);
      // (ABORT) = llama.cpp 엔진이 멈춤(기억 길이·메모리 초과 등). 엔진을 버리고 모델을 다시 불러온다
      if (/\(ABORT\)|abort\(|RuntimeError|memory access out of bounds|unreachable/i.test(m)){
        const last = settings.last; try { await eng.w.exit(); } catch(x){}
        eng.w = null; eng.loaded = null; emit("engine");
        if (last && last.kind !== "file") setTimeout(() => loadModel(last), 200);
        throw new Error(`내 기기 AI 엔진이 멈췄습니다(기억 길이나 메모리를 넘었을 가능성이 큽니다). ${last && last.kind !== "file" ? "모델을 자동으로 다시 불러오는 중이니 잠시 뒤 '다시 생성'을 누르세요." : "모델을 다시 불러오세요."} 긴 답이 필요하면 설정 → 내 기기 모델에서 '대화 기억 길이'를 늘리거나, API 키를 넣어 클라우드 모델을 쓰세요.`);
      }
      throw e;
    }
  };
  const p = localLock.then(go1, go1); localLock = p.catch(() => {}); return p;
}
// OpenAI 호환 스트리밍 (각 회사 · Ollama)
async function streamOAI(target, {messages, maxTokens, temperature, signal, onContent, onThink, onStats, stop}){
  const isOl = target.id === "ollama";
  const url = isOl ? apiBase("ollama") + "/v1/chat/completions" : provBase(target.id) + "/chat/completions";
  const headers = {"content-type": "application/json", accept: "text/event-stream"};
  if (!isOl) headers.authorization = "Bearer " + settings.keys[target.id];
  if (target.id === "openrouter"){ headers["HTTP-Referer"] = "https://nuri.local"; headers["X-Title"] = "Nuri AI"; }
  const canSee = VISION_RE.test(target.model);
  const msgs = canSee ? messages.map(m => m.images?.length ? {role: m.role, content: [{type: "text", text: m.content}, ...m.images.map(url => ({type: "image_url", image_url: {url}}))]} : {role: m.role, content: m.content}) : stripImages(messages, `${shortModel(target.model)}는 이미지를 볼 수 없습니다`);
  const body = {model: target.model, messages: msgs, stream: true, max_tokens: maxTokens, temperature};
  if (stop && target.id !== "gemini") body.stop = stop;
  let res;
  try { res = await fetch(url, {method: "POST", headers, signal, body: JSON.stringify(body)}); }
  catch (e){
    if (signal?.aborted) throw e;
    const err = new Error(!LAUNCHER.on ? "웹 버전에서는 브라우저 보안정책 때문에 외부 AI에 바로 연결할 수 없습니다. GHNano.exe로 실행하세요." : isOl ? "Ollama에 연결하지 못했습니다." : `${PROVIDERS[target.id].name}에 연결하지 못했습니다.`);
    err.retry = true; throw err;
  }
  if (!res.ok){
    let m = ""; try { const j = await res.json(); m = j.error?.message || j.detail || j.message || (typeof j.error === "string" ? j.error : ""); } catch(e){}
    const name = isOl ? "Ollama" : PROVIDERS[target.id].name;
    const err = new Error(res.status === 401 || res.status === 403 ? `${name} 키가 올바르지 않거나 권한이 없습니다.` : res.status === 404 ? `${name}에 '${target.model}' 모델이 없습니다.` : res.status === 429 ? `${name} 사용 한도에 걸렸습니다.` : `${name} 오류 ${res.status} ${String(m).slice(0, 140)}`);
    err.status = res.status; err.retry = true; throw err;
  }
  for await (const ev of sse(res)){
    const ch = ev.choices?.[0], d = ch?.delta || {};
    if (d.reasoning_content || d.reasoning) onThink?.(d.reasoning_content || d.reasoning);
    if (d.content) onContent?.(d.content);
    if (ch?.finish_reason === "length") onStats?.({cut: true});
  }
}
// role: general | code | reason | fast
export async function brainStream(opts){
  const role = opts.role || (opts.think ? "reason" : "general");
  const b = settings.brain;
  if (b === "local" && !opts.target) return streamLocal(opts);
  let cands;
  if (b === "auto") cands = routeCandidates(role);
  else if (b === "ollama") cands = [{id:"ollama", model: settings.olModel}];
  else if (PROVIDERS[b]) cands = routeCandidates(role).filter(c => c.id === b).concat(routeCandidates(role).filter(c => c.id !== b));
  else cands = [];
  if (opts.only) cands = (opts.only === "ollama" ? [{id:"ollama", model: settings.olModel}] : routeCandidates(role)).filter(c => c.id === opts.only);
  if (opts.target) cands = opts.fallback ? [opts.target, ...cands.filter(c => c.id !== opts.target.id || c.model !== opts.target.model)] : [opts.target];   // 특정 회사·모델을 꼭 집어 부를 때 (fallback이면 막혔을 때 다른 AI로)
  if (!cands.length && role === "vision"){ cands = routeCandidates("general"); emit("activity", {kind: "fallback", text: "이미지를 볼 수 있는 모델이 연결되어 있지 않아 글로만 답합니다 (NVIDIA·Gemini 키를 넣으면 이미지 이해 가능)"}); if (b === "local") return streamLocal(opts); }
  if (!cands.length) throw new Error("연결된 AI가 없습니다. 설정 → AI 두뇌에서 API 키를 넣거나 모델을 내려받으세요.");
  let lastErr = null;
  for (let i = 0; i < cands.length; i++){
    const c = cands[i];
    let got = false;
    const wrapped = {...opts, onContent: d => { got = true; opts.onContent?.(d); }, onThink: d => { got = true; opts.onThink?.(d); }};
    lastRoute = c; emit("activity", {kind:"route", text:`${c.id === "local" ? "내 기기" : c.id === "ollama" ? "Ollama" : PROVIDERS[c.id].name} · ${shortModel(c.model)}`, role, route: c});
    try { if (c.id === "local") await streamLocal(wrapped); else await streamOAI(c, wrapped); return c; }
    catch (e){
      if (opts.signal?.aborted || got || !e.retry) throw e;
      lastErr = e;
      if (c.id !== "local" && c.id !== "ollama" && (e.status === 429 || e.status >= 500 || !e.status)) cooldown[c.id] = Date.now() + (e.status === 429 ? 90e3 : 30e3);
      if (i + 1 < cands.length) emit("activity", {kind:"fallback", text:`${e.message} → 다른 AI로 바꿉니다`});
    }
  }
  throw lastErr || new Error("응답할 수 있는 AI가 없습니다");
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

/* ============ 인터넷: 가져오기 · 검색 · 페이지 읽기 ============ */
export async function webGet(url, as = "text"){
  let r;
  if (LAUNCHER.on) r = await fetch("/__nuri/fetch?url=" + encodeURIComponent(url), {headers: {"X-Nuri-Token": window.__NURI_TOKEN || ""}});
  else r = await fetch(url).catch(() => { throw new Error("웹 버전에서는 인터넷 자료를 직접 가져올 수 없습니다. GHNano.exe로 실행하세요."); });
  const status = +(r.headers.get("X-Upstream-Status") || r.status);
  if (!r.ok || status >= 400){ const e = new Error(`가져오기 실패 (${status}) ${url.slice(0, 80)}`); e.status = status; throw e; }
  return as === "json" ? r.json() : r.text();
}
function cleanUrl(href){
  try {
    if (href.startsWith("//")) href = "https:" + href;
    const u = new URL(href, "https://duckduckgo.com");
    if (/duckduckgo\.com$/.test(u.hostname) && u.searchParams.get("uddg")) return u.searchParams.get("uddg");
    if (/bing\.com$/.test(u.hostname) && u.pathname === "/ck/a"){ const k = u.searchParams.get("u"); if (k && k.startsWith("a1")) return atob(k.slice(2).replace(/-/g, "+").replace(/_/g, "/")); }
    return u.href;
  } catch(e){ return href; }
}
export async function webSearch(q, n = 8){
  if (settings.keys.tavily){
    const r = await fetch(apiBase("tavily") + "/search", {method:"POST", headers:{"content-type":"application/json", authorization:"Bearer " + settings.keys.tavily}, body: JSON.stringify({query:q, max_results:n, search_depth:"advanced", include_answer:false})});
    if (r.ok){ const j = await r.json(); return {engine:"Tavily", results:(j.results || []).map(x => ({title:x.title, url:x.url, snippet:(x.content || "").slice(0, 400), date:x.published_date || ""}))}; }
  }
  if (settings.keys.brave){
    const r = await fetch(apiBase("brave") + "/web/search?count=" + n + "&q=" + encodeURIComponent(q), {headers:{"X-Subscription-Token": settings.keys.brave, accept:"application/json"}});
    if (r.ok){ const j = await r.json(); return {engine:"Brave", results:(j.web?.results || []).map(x => ({title:x.title, url:x.url, snippet:(x.description || "").replace(/<[^>]+>/g, ""), date:x.age || ""}))}; }
  }
  const parse = html => new DOMParser().parseFromString(html, "text/html");
  try {
    const d = parse(await webGet("https://html.duckduckgo.com/html/?kl=kr-kr&q=" + encodeURIComponent(q)));
    const res = [...d.querySelectorAll(".result")].map(el => { const a = el.querySelector("a.result__a"); return a ? {title:a.textContent.trim(), url:cleanUrl(a.getAttribute("href") || ""), snippet:(el.querySelector(".result__snippet")?.textContent || "").trim()} : null; }).filter(x => x && /^https?:/.test(x.url) && !/duckduckgo\.com\/y\.js/.test(x.url));
    if (res.length) return {engine:"DuckDuckGo", results:res.slice(0, n)};
  } catch(e){}
  const d = parse(await webGet("https://www.bing.com/search?setlang=ko&cc=KR&q=" + encodeURIComponent(q)));
  const res = [...d.querySelectorAll("li.b_algo")].map(el => { const a = el.querySelector("h2 a"); return a ? {title:a.textContent.trim(), url:cleanUrl(a.getAttribute("href") || ""), snippet:(el.querySelector(".b_caption p, p")?.textContent || "").trim()} : null; }).filter(Boolean);
  return {engine:"Bing", results:res.slice(0, n)};
}
const BLOCK = new Set(["P","DIV","SECTION","ARTICLE","LI","TR","H1","H2","H3","H4","H5","H6","BR","TABLE","UL","OL","BLOCKQUOTE","PRE","HEADER","FOOTER","DD","DT"]);
export async function readPage(url, max = 12000){
  const raw = await webGet(url);
  if (/^\s*[\[{]/.test(raw)) return {title:url, url, text:raw.slice(0, max)};
  const d = new DOMParser().parseFromString(raw, "text/html");
  d.querySelectorAll("script,style,noscript,svg,nav,footer,header,aside,form,iframe,[aria-hidden=true],.ad,.ads,.advertisement").forEach(n => n.remove());
  const root = d.querySelector("article") || d.querySelector("main") || d.querySelector("#content, .content, #main") || d.body;
  let out = "";
  const walk = n => { for (const c of n.childNodes){ if (c.nodeType === 3) out += c.nodeValue.replace(/\s+/g, " "); else if (c.nodeType === 1){ if (BLOCK.has(c.tagName)) out += "\n"; walk(c); if (BLOCK.has(c.tagName)) out += "\n"; } } };
  if (root) walk(root);
  const text = out.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  const date = d.querySelector('meta[property="article:published_time"], meta[name="date"], time[datetime]');
  return {title:(d.querySelector("title")?.textContent || url).trim().slice(0, 160), url, date: date ? (date.getAttribute("content") || date.getAttribute("datetime") || "") : "", text:text.slice(0, max), truncated:text.length > max};
}
