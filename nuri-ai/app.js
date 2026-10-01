// 누리 AI 화면: 채팅·코드 두 모드, 결과물 패널, 설정
import { esc, uid, fmtN, ls, idb, bus, settings, saveSettings, CATALOG, eng, loadModel, unloadModel, gpuSupported, refreshCache, cacheList,
  LAUNCHER, detectLauncher, apiBase, codeCall, OL_MODELS, BRAINS, brainReady, brainLabel, brainStream, splitThink,
  PROVIDERS, SEARCH_KEYS, addApiKey, removeApiKey, routeCandidates, shortModel, webGet,
  docs, loadDocs, addDoc, removeDoc, readTextFile, md, highlight } from "./engine.js";
import { runAgent, BUILTIN_SKILLS, TOOLS } from "./agent.js";
import { TEMPLATES } from "./templates.js";
import { initTrade } from "./trade.js";

const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const ico = (id, st = "") => `<svg class="i" style="${st}"><use href="#i-${id}"/></svg>`;
const toast = m => { const t = $("#toast"); t.textContent = m; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, 2800); };

/* ============ 상태 ============ */
let chats = [], current = null, mode = ls.get("mode", "chat"), busy = false, ctl = null, attach = [];
const byUpdated = () => chats.slice().sort((a, b) => b.updated - a.updated);
function saveChat(c){ c.updated = Date.now(); if (!chats.includes(c)) chats.push(c); idb.put("chat:" + c.id, c); }
const pendingPerm = new Map();

/* ============ 모드 ============ */
function setMode(m, keepChat){
  mode = m; ls.set("mode", m);
  $$(".modes [data-mode]").forEach(b => b.setAttribute("aria-selected", b.dataset.mode === m));
  $$(".code-only").forEach(e => e.hidden = m !== "code");
  $("#input").placeholder = m === "code" ? "무엇을 만들거나 고칠까요?" : "누리에게 무엇이든 물어보세요";
  $("#dockNote").textContent = m === "code" ? "누리 코드는 작업 폴더의 파일을 읽고 고치며 명령을 실행합니다. 바꾸기 전에 허락을 구합니다." : "누리는 실수할 수 있습니다. 중요한 정보는 확인하세요.";
  $("#permSel").value = settings.permission;
  if (!keepChat && current && (current.mode || "chat") !== m) newChat();
  renderWs();
}
$$(".modes [data-mode]").forEach(b => b.onclick = () => { if (!busy && b.dataset.mode !== mode) setMode(b.dataset.mode); });

/* ============ 대화 목록 ============ */
function renderList(){
  const q = $("#search").value.trim().toLowerCase();
  const list = byUpdated().filter(c => !q || c.title.toLowerCase().includes(q) || c.messages.some(m => (m.content || "").toLowerCase().includes(q)));
  const day = 864e5, now = new Date(); now.setHours(0,0,0,0);
  const groups = [["오늘", c => c.updated >= +now], ["지난 7일", c => c.updated >= +now - 6*day], ["지난 30일", c => c.updated >= +now - 29*day], ["이전", () => true]];
  const used = new Set(); let html = "";
  for (const [label, fn] of groups){
    const g = list.filter(c => !used.has(c.id) && fn(c)); if (!g.length) continue;
    g.forEach(c => used.add(c.id));
    html += `<div class="grp">${label}</div>` + g.map(c => `<div class="ci" role="button" tabindex="0" data-id="${c.id}" aria-current="${current && current.id === c.id}"><span class="t">${esc(c.title)}</span>${c.mode === "code" ? `<span class="tag">코드</span>` : ""}<button class="del" data-del="${c.id}" aria-label="대화 삭제">삭제</button></div>`).join("");
  }
  $("#recents").innerHTML = html || `<div class="grp" style="font-weight:400">${q ? "검색 결과가 없습니다" : "대화가 여기에 쌓입니다"}</div>`;
}
$("#recents").addEventListener("click", e => {
  const d = e.target.closest("[data-del]"); if (d){ e.stopPropagation(); deleteChat(d.dataset.del); return; }
  const it = e.target.closest(".ci"); if (it && !busy) openChat(it.dataset.id);
});
$("#recents").addEventListener("keydown", e => { if (e.key === "Enter" && e.target.classList.contains("ci")) e.target.click(); });
$("#search").addEventListener("input", renderList);
let pendingDel = null;
function deleteChat(id){
  if (pendingDel !== id){ pendingDel = id; toast("한 번 더 누르면 삭제합니다"); setTimeout(() => { if (pendingDel === id) pendingDel = null; }, 3000); return; }
  pendingDel = null; chats = chats.filter(c => c.id !== id); idb.del("chat:" + id);
  if (current && current.id === id) newChat();
  renderList(); toast("대화를 삭제했습니다");
}
function newChat(){
  current = {id: uid(), title: "새 대화", mode, created: Date.now(), updated: Date.now(), messages: [], workspace: mode === "code" ? ls.get("lastWs", "") : ""};
  closePanel(); render(); renderList(); renderWs(); closeSide(); $("#input").focus();
}
function openChat(id){
  const c = chats.find(x => x.id === id); if (!c) return newChat();
  current = c; setMode(c.mode || "chat", true); closePanel(); render(); renderList(); renderWs(); closeSide();
}
$("#newChat").onclick = () => { if (!busy) newChat(); };

/* ============ 사이드바 ============ */
const isMobile = () => matchMedia("(max-width:760px)").matches;
function closeSide(){ if (isMobile()) $("#app").classList.remove("open"); }
function syncSideBtn(){ $("#sideOpen").hidden = !isMobile() && !$("#app").classList.contains("collapsed"); }
$("#sideClose").onclick = () => { if (isMobile()) $("#app").classList.remove("open"); else { $("#app").classList.add("collapsed"); ls.set("side", 0); } syncSideBtn(); };
$("#sideOpen").onclick = () => { if (isMobile()) $("#app").classList.add("open"); else { $("#app").classList.remove("collapsed"); ls.set("side", 1); } syncSideBtn(); };
$("#scrim").onclick = () => $("#app").classList.remove("open");
if (ls.get("side", 1) === 0) $("#app").classList.add("collapsed");
addEventListener("resize", syncSideBtn);

/* ============ 대화 그리기 ============ */
const hour = new Date().getHours();
const GREET = hour < 6 ? "늦은 밤이네요" : hour < 12 ? "좋은 아침이에요" : hour < 18 ? "좋은 오후예요" : "좋은 저녁이에요";
const CHIPS = {
  chat: [["chart","비트코인 지금 분석해줘"],["chart","이번 주 경제 발표 일정과 시장 영향"],["home","대지 60평에 3층 단독주택 설계하고 견적서까지"],["search","최신 AI 뉴스 검색해서 정리해줘"],["code","할 일 관리 웹앱 만들어줘"]],
  code: [["folder","이 프로젝트 구조를 설명해줘"],["code","버그를 찾아서 고쳐줘"],["doc","README.md를 써줘"],["redo","테스트를 실행하고 실패하면 고쳐줘"]]
};
function render(){
  const th = $("#thread"), empty = !current.messages.length;
  if ($("#composer").parentElement.id !== "dock") $("#dock").prepend($("#composer")); // 다시 그리기 전에 입력창을 안전한 곳으로
  $("#title").textContent = empty ? "" : current.title;
  if (empty){
    const note = !brainReady() ? `<div class="hero-note"><b>먼저 AI 두뇌를 준비하세요.</b> 입력창의 모델 버튼에서 고르거나 <a href="#" data-open="brain" style="color:var(--accent)">설정</a>을 여세요.</div>`
      : mode === "code" && !LAUNCHER.on ? `<div class="hero-note"><b>코드 모드는 NuriAI.exe로 실행해야 쓸 수 있습니다.</b></div>`
      : mode === "code" && !current.workspace ? `<div class="hero-note">입력창의 <b>폴더 열기</b>로 작업할 폴더를 고르세요.</div>`
      : mode === "code" ? `<div class="hero-note">작업 폴더: <b>${esc(current.workspace)}</b></div>` : "";
    th.innerHTML = `<div class="hero"><h1><span class="logo">누</span>${mode === "code" ? "무엇을 만들어 볼까요?" : GREET}</h1><div class="hero-slot" id="heroSlot"></div>
      <div class="chips">${CHIPS[mode].map(([i, t]) => `<button class="chip" data-chip>${ico(i)}${esc(t)}</button>`).join("")}<button class="chip more" data-open="tpl">${ico("grid")}템플릿 더 보기</button></div>${note}</div>`;
    $("#heroSlot").appendChild($("#composer"));
    $("#dock").hidden = true;
  } else {
    $("#dock").hidden = false;
    th.innerHTML = current.messages.map((m, i) => msgHTML(m, i)).join("");
    scrollDown(true);
  }
  $("#panelToggle").hidden = !lastArtifact();
}
const aiParts = m => m.parts || [{type: "text", text: m.content || ""}];
function msgHTML(m, i){
  if (m.role === "user"){
    const files = (m.attach || []).map(a => `<span class="fchip">${ico("doc", "width:14px;height:14px")}${esc(a.name)}</span>`).join("");
    return `<div class="msg user" data-i="${i}">${files ? `<div class="files" style="justify-content:flex-end">${files}</div>` : ""}<div class="bubble">${esc(m.content)}</div>${busy ? "" : `<div class="acts"><button data-act="copy">${ico("copy","width:14px;height:14px")}복사</button><button data-act="edit">${ico("pen","width:14px;height:14px")}수정</button></div>`}</div>`;
  }
  const code = (m.mode || current.mode) === "code";
  const parts = aiParts(m).map((p, j) => p.type === "text" ? textPart(p, m, i, j) : (code ? codeTool(p) : chatTool(p))).join("");
  const skl = m.skills?.length ? `<div class="skl">${m.skills.map(s => `<span title="켜진 스킬">${esc(s.icon || "✨")} ${esc(s.name)}</span>`).join("")}</div>` : "";
  const writing = m.streaming && (!m.phase || m.phase === "답변 작성 중");
  const live = m.streaming && !writing ? `<button class="live" data-openact title="진행 상황 보기"><span class="spin"></span><span>${esc(m.phase || "생각하는 중")}</span><span class="sec">${Math.max(0, Math.round((Date.now() - (m.t0 || m.ts)) / 1000))}초</span></button>` : "";
  const srcs = !m.streaming && m.sources?.length ? `<div class="srcs">${m.sources.slice(0, 8).map((s, k) => `<a href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(s.title || s.url)}"><b>${k + 1}</b>${esc(hostOf(s.url))}</a>`).join("")}${m.sources.length > 8 ? `<button class="link" data-openact>+${m.sources.length - 8}</button>` : ""}</div>` : "";
  const who = m.route ? `${m.route.name} · ${shortModel(m.route.model)}` : (m.model || "");
  return `<div class="msg ai" data-i="${i}">${skl}${parts}${live}${writing ? `<span class="cursor" aria-label="작성 중"></span>` : ""}
    ${m.error ? `<div class="err">${esc(m.error)}</div>` : ""}${srcs}
    ${m.streaming ? "" : `<div class="acts"><button data-act="copy">${ico("copy","width:14px;height:14px")}복사</button><button data-act="regen">${ico("redo","width:14px;height:14px")}다시 생성</button><button data-openact>${ico("pulse","width:14px;height:14px")}과정</button><span class="meta">${esc(who)}${m.ms ? " · " + (m.ms/1000).toFixed(1) + "초" : ""}</span></div>`}</div>`;
}
// 글 속 <artifact> 블록 → 카드
const ART_RE = /<artifact\b([^>]*)>([\s\S]*?)(?:<\/artifact>|$)/g;
const attr = (s, k) => (s.match(new RegExp(k + `\\s*=\\s*["']([^"']*)["']`)) || [])[1] || "";
function artifactsIn(text){ const out = []; let m; ART_RE.lastIndex = 0; while ((m = ART_RE.exec(text))){ if (!m[0]) break; out.push({type: attr(m[1], "type") || "code", title: attr(m[1], "title") || "결과물", lang: attr(m[1], "lang"), content: m[2].replace(/^\n/, ""), done: /<\/artifact>$/.test(m[0])}); } return out; }
function textPart(p, m, i, j){
  const {think, body, open} = splitThink(p.text);
  const thinkAll = [p.think, think].filter(Boolean).join("\n");
  let html = "", last = 0, n = 0, mm; ART_RE.lastIndex = 0;
  while ((mm = ART_RE.exec(body))){
    if (!mm[0]) break;
    html += md(body.slice(last, mm.index));
    const a = {type: attr(mm[1], "type") || "code", title: attr(mm[1], "title") || "결과물", lang: attr(mm[1], "lang")};
    html += artCard(a.title, /<\/artifact>$/.test(mm[0]) ? artTypeLabel(a) : "작성 중…", `${i}:${j}:${n++}`, a.type);
    last = mm.index + mm[0].length;
  }
  html += md(body.slice(last));
  const thinking = m.streaming && (open || !body);
  return `${thinkAll ? `<details class="think"${thinking ? " open" : ""}><summary>${thinking ? "생각하는 중" : "생각 과정"}</summary><div class="tt">${esc(thinkAll)}</div></details>` : ""}${html ? `<div class="md">${html}</div>` : ""}`;
}
const hostOf = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch(e){ return String(u || ""); } };
const artTypeLabel = a => ({html: "웹페이지 · 클릭해서 열기", code: (a.lang || "코드") + " · 클릭해서 열기", markdown: "문서 · 클릭해서 열기", svg: "그림 · 클릭해서 열기", trading: "실시간 차트 · 클릭해서 열기", building: "3D 설계 · 클릭해서 열기", image: "이미지 · 클릭해서 열기"})[a.type] || "결과물";
const artIcon = t => ({html: "code", code: "code", markdown: "doc", svg: "pen", trading: "chart", building: "home", image: "image"})[t] || "doc";
const artCard = (title, sub, key, type) => `<button class="art-card" data-art="${key}"><span class="ic">${ico(artIcon(type))}</span><span><b>${esc(title)}</b><span>${esc(sub)}</span></span></button>`;
const ST = {running: ["run", ""], done: ["done", "✓"], error: ["error", "!"], denied: ["denied", "×"], pending: ["pending", "?"]};
function chatTool(p){
  const [cls, ch] = ST[p.status] || ST.running;
  const card = p.artifact ? artCard(p.artifact.title, artTypeLabel(p.artifact), "tool:" + p.id, p.artifact.type) : "";
  return `<div class="tool"><button class="tool-h" data-tool="${p.id}"><span class="st ${cls}">${ch}</span><span class="nm">${esc(p.label || p.name)}</span><span class="sm">${esc(p.status === "error" ? p.error : p.status === "running" ? (p.act || "실행") + " 중…" : p.summary || "")}</span>${ico("chev","width:14px;height:14px;color:var(--muted)")}</button>
    <div class="tool-b" hidden><label>입력</label><pre>${esc(JSON.stringify(p.input, null, 1))}</pre>${p.modelText ? `<label>결과</label><pre>${esc(p.modelText.slice(0, 4000))}</pre>` : ""}</div></div>${card}`;
}
function codeTool(p){
  const dt = {running: "run", done: "", error: "error", denied: "denied", pending: "pending"}[p.status] || "";
  const arg = p.input.path || p.input.command || p.input.pattern || (p.name === "todo_write" ? "" : JSON.stringify(p.input).slice(0, 80));
  let body = "";
  if (p.status === "error") body = `<div class="cc-r" style="color:var(--bad)">${esc(p.error)}</div>`;
  else if (p.status === "denied") body = `<div class="cc-r">사용자가 거부했습니다</div>`;
  else if (p.status === "running") body = `<div class="cc-r">실행 중…</div>`;
  else if (p.status === "pending"){
    const what = p.name === "run_command" ? "이 명령을 실행할까요?" : `${p.input.path} 파일을 ${p.name === "write_file" ? "저장할까요" : "고칠까요"}?`;
    body = (p.preview ? diffHTML(p.preview) : p.name === "run_command" ? `<div class="cc-out">$ ${esc(p.input.command)}</div>` : "") +
      `<div class="perm"><span>${esc(what)}</span><div class="row"><button class="btn primary" data-perm="${p.id}" data-v="yes">허용</button><button class="btn" data-perm="${p.id}" data-v="always">이 대화에서 계속 허용</button><button class="btn" data-perm="${p.id}" data-v="no">거부</button></div></div>`;
  } else {
    body = `<div class="cc-r">${esc(p.summary || "완료")}</div>`;
    if (p.diff) body += diffHTML(p.diff);
    if (p.output) body += `<div class="cc-out">${esc(p.output.slice(-6000))}</div>`;
    if (p.todos) body += `<div class="todos">${p.todos.map(t => `<div class="td ${esc(t.status)}">${t.status === "completed" ? "☒" : t.status === "in_progress" ? "▣" : "☐"} ${esc(t.content)}</div>`).join("")}</div>`;
  }
  return `<div class="cc"><div class="cc-h"><span class="dt ${dt}">●</span><b>${esc(p.label || p.name)}</b><span class="arg">${esc(arg)}</span></div>${body}</div>`;
}
// 바뀐 부분과 주변 2줄만 보여주는 줄 단위 비교
function diffHTML(d){
  const a = String(d.old || "").replace(/\r/g, "").split("\n"), b = String(d.new || "").replace(/\r/g, "").split("\n");
  if (!d.old) return `<div class="diff"><div class="fn">${esc(d.path)} · 새 파일 ${b.length}줄</div>${b.slice(0, 60).map((l, k) => `<div class="ln add"><span class="no">${k+1}</span><span>+</span><span>${esc(l)}</span></div>`).join("")}${b.length > 60 ? `<div class="gap">… ${b.length - 60}줄 더</div>` : ""}</div>`;
  let s = 0; while (s < a.length && s < b.length && a[s] === b[s]) s++;
  let ea = a.length - 1, eb = b.length - 1; while (ea >= s && eb >= s && a[ea] === b[eb]){ ea--; eb--; }
  const rows = [], C = 2;
  for (let k = Math.max(0, s - C); k < s; k++) rows.push(["", k+1, a[k]]);
  for (let k = s; k <= ea; k++) rows.push(["del", k+1, a[k]]);
  for (let k = s; k <= eb; k++) rows.push(["add", k+1, b[k]]);
  for (let k = eb + 1; k < Math.min(b.length, eb + 1 + C); k++) rows.push(["", k+1, b[k]]);
  return `<div class="diff"><div class="fn">${esc(d.path)} · <span style="color:var(--add-ink)">+${Math.max(0, eb - s + 1)}</span> <span style="color:var(--del-ink)">−${Math.max(0, ea - s + 1)}</span></div>${s > C ? `<div class="gap">… ${s - C}줄</div>` : ""}${rows.slice(0, 160).map(([c, no, l]) => `<div class="ln ${c}"><span class="no">${no}</span><span>${c === "add" ? "+" : c === "del" ? "−" : " "}</span><span>${esc(l)}</span></div>`).join("")}${rows.length > 160 ? `<div class="gap">… ${rows.length - 160}줄 더</div>` : ""}</div>`;
}
let stick = true;
$("#scroll").addEventListener("scroll", () => { const s = $("#scroll"); stick = s.scrollHeight - s.scrollTop - s.clientHeight < 90; });
function scrollDown(force){ const s = $("#scroll"); if (force || stick) s.scrollTop = s.scrollHeight; }

/* ============ 클릭 처리 ============ */
document.addEventListener("click", e => {
  const t = e.target;
  const chip = t.closest("[data-chip]"); if (chip){ $("#input").value = chip.textContent.trim(); autoGrow(); updateSend(); $("#input").focus(); return; }
  if (t.closest("[data-openact]")){ openActivity(); return; }
  const op = t.closest("[data-open]"); if (op){ e.preventDefault(); openSheet(op.dataset.open); return; }
  if (t.closest("[data-go]")){ openSheet("brain"); return; }
  const th = t.closest(".tool-h"); if (th){ const b = th.nextElementSibling; if (b) b.hidden = !b.hidden; return; }
  const cp = t.closest("[data-copy]"); if (cp){ copy(cp.closest(".codebox").querySelector("code").textContent); return; }
  const art = t.closest("[data-art]"); if (art){ openArtKey(art.dataset.art); return; }
  const pm = t.closest("[data-perm]"); if (pm){ const r = pendingPerm.get(pm.dataset.perm); if (r){ pendingPerm.delete(pm.dataset.perm); if (pm.dataset.v === "always") current.allowAll = true; r(pm.dataset.v !== "no"); } return; }
  const a = t.closest("[data-act]"); if (a && !busy){
    const i = +a.closest(".msg").dataset.i, m = current.messages[i];
    if (a.dataset.act === "copy") copy(m.role === "user" ? m.content : aiParts(m).filter(p => p.type === "text").map(p => splitThink(p.text).body).join("\n\n"));
    if (a.dataset.act === "regen"){ if (!brainReady()){ openSheet("brain"); return; } current.messages.splice(i); run(); }
    if (a.dataset.act === "edit"){ $("#input").value = m.content; current.messages.splice(i); saveChat(current); render(); autoGrow(); updateSend(); $("#input").focus(); }
  }
  if (!t.closest(".pick")){ $("#modelMenu").hidden = true; $("#wsMenu").hidden = true; }
});
async function copy(t){ try { await navigator.clipboard.writeText(t); toast("복사했습니다"); } catch(e){ toast("복사가 막혀 있습니다. 텍스트를 드래그해 복사하세요"); } }

/* ============ 입력 ============ */
const input = $("#input");
function autoGrow(){ input.style.height = "auto"; input.style.height = Math.min(240, input.scrollHeight) + "px"; }
function updateSend(){
  const s = $("#send");
  if (busy){ s.disabled = false; s.classList.add("stop"); s.innerHTML = ico("stop"); s.setAttribute("aria-label", "멈추기"); }
  else { s.classList.remove("stop"); s.innerHTML = ico("up"); s.setAttribute("aria-label", "보내기"); s.disabled = !input.value.trim() && !attach.length; }
}
input.addEventListener("input", () => { autoGrow(); updateSend(); });
input.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229){ e.preventDefault(); if (!busy) send(); } });
$("#send").onclick = () => busy ? stop() : send();
$("#thinkBtn").onclick = e => { settings.think = !settings.think; saveSettings(); e.currentTarget.setAttribute("aria-pressed", settings.think); };
$("#thinkBtn").setAttribute("aria-pressed", settings.think);
$("#permSel").onchange = e => { settings.permission = e.target.value; saveSettings(); };
$("#fileIn").addEventListener("change", async e => {
  for (const f of e.target.files){ try { attach.push({name: f.name, size: f.size, text: await readTextFile(f)}); } catch(err){ toast(err.message); } }
  e.target.value = ""; renderPending(); updateSend();
});
function renderPending(){ $("#pending").innerHTML = attach.map((a, i) => `<span class="fchip">${esc(a.name)} <button data-rm="${i}" aria-label="첨부 삭제">✕</button></span>`).join(""); }
$("#pending").addEventListener("click", e => { const r = e.target.dataset.rm; if (r == null) return; attach.splice(+r, 1); renderPending(); updateSend(); });

/* ============ 모델 고르기 ============ */
function renderModelBtn(){
  const ok = brainReady();
  $("#modelDot").className = "dot " + (ok ? "ok" : settings.brain === "local" && eng.loading ? "warn" : "bad");
  $("#modelLabel").textContent = ok ? brainLabel() : settings.brain === "local" && eng.loading ? `준비 중 ${Math.round(eng.progress * 100)}%` : "모델 설정 필요";
}
const connectedAI = () => Object.keys(PROVIDERS).filter(id => settings.keys[id]);
const brainName = id => BRAINS[id]?.name || (PROVIDERS[id] ? PROVIDERS[id].name + " 우선" : id);
const ROLE_KO = {general: "일반 대화", code: "코딩", reason: "깊은 추론", fast: "빠른 답"};
$("#modelBtn").onclick = () => {
  const m = $("#modelMenu");
  const items = [["auto", BRAINS.auto.desc], ...connectedAI().map(id => [id, "이 회사를 먼저 쓰고 막히면 다른 곳으로"]), ["ollama", BRAINS.ollama.desc], ["local", BRAINS.local.desc]];
  m.innerHTML = items.map(([id, desc]) => `<button class="mi" data-brain="${id}"><span class="ck">${settings.brain === id ? "✓" : ""}</span><span><b>${esc(brainName(id))}</b><span>${brainReady(id) ? esc(brainLabel(id)) + " · " + desc : "설정 필요 · " + desc}</span></span></button>`).join("") +
    `<hr><button class="mi" data-open="brain"><span class="ck">${ico("plus","width:15px;height:15px")}</span><span><b>API 키 추가 · AI 두뇌 설정</b><span>키를 붙여넣으면 알아서 연결</span></span></button>`;
  m.hidden = !m.hidden; $("#wsMenu").hidden = true;
};
$("#modelMenu").addEventListener("click", e => { const b = e.target.closest("[data-brain]"); if (!b) return; settings.brain = b.dataset.brain; saveSettings(); $("#modelMenu").hidden = true; if (!brainReady()) openSheet(b.dataset.brain === "local" ? "local" : "brain"); else toast(brainName(settings.brain) + " · " + brainLabel()); });

/* ============ 작업 폴더 (코드 모드) ============ */
function renderWs(){ const p = current?.workspace; $("#wsLabel").textContent = p ? p.split(/[\\/]/).filter(Boolean).pop() : "폴더 열기"; $("#wsBtn").title = p || "작업 폴더"; }
$("#wsBtn").onclick = () => {
  const m = $("#wsMenu"), recent = ls.get("recentWs", []);
  m.innerHTML = `<button class="mi" id="wsPick"><span class="ck">${ico("folder","width:16px;height:16px")}</span><span><b>폴더 선택 창 열기</b><span>탐색기에서 작업할 폴더를 고릅니다</span></span></button>
    <div style="padding:6px 8px"><input id="wsPath" placeholder="또는 경로 입력 후 Enter: C:\\Users\\나\\project" value="${esc(current.workspace || "")}"></div>
    ${recent.length ? `<hr>${recent.map(p => `<button class="mi" data-ws="${esc(p)}"><span class="ck">${current.workspace === p ? "✓" : ""}</span><span><b>${esc(p.split(/[\\/]/).filter(Boolean).pop())}</b><span>${esc(p)}</span></span></button>`).join("")}` : ""}`;
  m.hidden = !m.hidden; $("#modelMenu").hidden = true;
};
async function openWs(p){
  try {
    const r = await codeCall("open", {path: p});
    current.workspace = r.path; ls.set("lastWs", r.path); ls.set("recentWs", [r.path, ...ls.get("recentWs", []).filter(x => x !== r.path)].slice(0, 6));
    if (current.messages.length) saveChat(current);
    renderWs(); $("#wsMenu").hidden = true; toast("작업 폴더: " + r.name); if (!current.messages.length) render();
  } catch(e){ toast(e.message); }
}
$("#wsMenu").addEventListener("click", async e => {
  if (e.target.closest("#wsPick")){ try { const r = await codeCall("pick"); await openWs(r.path); } catch(err){ toast(err.message); } }
  const w = e.target.closest("[data-ws]"); if (w) openWs(w.dataset.ws);
});
$("#wsMenu").addEventListener("keydown", e => { if (e.target.id === "wsPath" && e.key === "Enter"){ e.preventDefault(); openWs(e.target.value.trim()); } });

/* ============ 보내기 · 실행 ============ */
function send(){
  const text = input.value.trim(); if (!text && !attach.length) return;
  if (!brainReady()){ toast("먼저 AI 두뇌를 준비하세요"); openSheet(settings.brain === "local" ? "local" : "brain"); return; }
  if (mode === "code"){
    if (!LAUNCHER.on){ toast("코드 모드는 NuriAI.exe로 실행해야 쓸 수 있습니다"); return; }
    if (!current.workspace){ toast("먼저 작업 폴더를 여세요"); $("#wsBtn").click(); return; }
  }
  current.mode = mode;
  current.messages.push({role: "user", content: text || "첨부한 파일을 살펴봐줘", attach: attach.length ? attach : undefined, ts: Date.now()});
  if (current.title === "새 대화") current.title = (text || attach[0].name).replace(/\s+/g, " ").slice(0, 34);
  input.value = ""; attach = []; renderPending(); autoGrow();
  saveChat(current); renderList();
  run();
}
function stop(){ ctl?.abort(); for (const [, r] of pendingPerm) r(false); pendingPerm.clear(); }
async function run(){
  const msg = {role: "assistant", parts: [], mode, model: brainLabel(), ts: Date.now(), streaming: true};
  const history = current.messages.slice();
  current.messages.push(msg);
  busy = true; updateSend(); render(); scrollDown(true);
  ctl = new AbortController();
  const t0 = performance.now(); let raf = 0;
  const idx = current.messages.length - 1;
  const paint = () => { raf = 0; const el = $(`#thread .msg[data-i="${idx}"]`); if (el){ el.outerHTML = msgHTML(msg, idx); scrollDown(); } $("#panelToggle").hidden = !lastArtifact(); };
  const update = () => { if (!raf) raf = requestAnimationFrame(() => { paint(); renderActivity(); }); };
  const onAct = e => { const d = e.detail || {}; (msg.log ||= []).push({t: Date.now(), kind: d.kind, text: d.text}); update(); };
  bus.addEventListener("activity", onAct);
  const tick = setInterval(update, 1000);
  if (!isMobile() && innerWidth >= 1100 && $("#panel").hidden && settings.autoActivity !== false) openActivity(true);
  else if (!$("#panel").hidden && panelTab === "act") renderActivity();
  try {
    if (mode === "code") await codeCall("open", {path: current.workspace});
    await runAgent({mode, history, msg, signal: ctl.signal, onUpdate: update, think: settings.think, workspace: current.workspace,
      openArtifact: (spec, wait) => openArtifact(spec, wait),
      askPermission: tp => current.allowAll ? Promise.resolve(true) : new Promise(res => { pendingPerm.set(tp.id, res); update(); })});
    if (!msg.parts.some(p => (p.type === "text" && p.text.trim()) || p.type === "tool")) msg.error = "빈 답변이 나왔습니다. 다시 생성해 보세요.";
  } catch (e){
    if (ctl.signal.aborted || e.name === "AbortError" || e.name === "WllamaAbortError"){ if (!msg.parts.length) msg.error = "답변을 멈췄습니다."; }
    else msg.error = String(e.message || e).slice(0, 300);
  } finally {
    cancelAnimationFrame(raf); clearInterval(tick); bus.removeEventListener("activity", onAct);
    msg.streaming = false; msg.ms = Math.round(performance.now() - t0);
    busy = false; ctl = null;
    saveChat(current); renderList(); updateSend(); render(); renderActivity();
    // 이번 답변에서 새로 만든 글 결과물이 있으면 패널로 연다
    const arts = aiParts(msg).flatMap((p, j) => p.type === "text" ? artifactsIn(splitThink(p.text).body).map((a, n) => `${idx}:${j}:${n}`) : []);
    if (arts.length) openArtKey(arts[arts.length - 1]);
  }
}

/* ============ 결과물 패널 ============ */
let trade = null, panelArt = null, pView = "preview", panelTab = "art";
function lastArtifact(){
  for (let i = current.messages.length - 1; i >= 0; i--){
    const m = current.messages[i]; if (m.role !== "assistant") continue;
    const parts = aiParts(m);
    for (let j = parts.length - 1; j >= 0; j--){
      const p = parts[j];
      if (p.type === "tool" && p.artifact) return "tool:" + p.id;
      if (p.type === "text"){ const a = artifactsIn(splitThink(p.text).body); if (a.length) return `${i}:${j}:${a.length - 1}`; }
    }
  }
  return null;
}
function findArt(key){
  if (key.startsWith("tool:")){ const id = key.slice(5); for (const m of current.messages) for (const p of (m.parts || [])) if (p.id === id) return p.artifact; return null; }
  const [i, j, n] = key.split(":").map(Number); const p = aiParts(current.messages[i] || {})[j]; if (!p) return null;
  return artifactsIn(splitThink(p.text).body)[n] || null;
}
function openArtKey(key){ const a = findArt(key); if (a) openArtifact(a); }
$("#panelToggle").onclick = () => { if (!$("#panel").hidden && panelTab === "art") closePanel(); else { const k = lastArtifact(); if (k) openArtKey(k); } };
$("#actToggle").onclick = () => { if (!$("#panel").hidden && panelTab === "act") closePanel(); else openActivity(); };
function setTabs(t){ panelTab = t; $$("#pTabs [data-pt]").forEach(b => b.setAttribute("aria-selected", b.dataset.pt === t)); $("#actHost").hidden = t !== "act"; }
$("#pTabs").addEventListener("click", e => {
  const b = e.target.closest("[data-pt]"); if (!b || b.dataset.pt === panelTab) return;
  if (b.dataset.pt === "act") openActivity();
  else if (panelArt) openArtifact(panelArt);
  else { const k = lastArtifact(); if (k) openArtKey(k); else { setTabs("art"); showArtEmpty(); } }
});
function showArtEmpty(){
  $("#pTitle").textContent = "결과물"; $("#pType").textContent = "웹페이지·코드·문서·차트·설계·이미지가 여기에 열립니다";
  $("#pView").hidden = $("#pCopy").hidden = $("#pSave").hidden = true; $("#tradeHost").hidden = $("#archHost").hidden = true; trade?.hide();
  $("#pContent").hidden = false; $("#pContent").innerHTML = `<p class="empty" style="padding:28px">아직 이 대화에 결과물이 없습니다.</p>`;
}
async function openArtifact(a, wait){
  panelArt = a; $("#panel").hidden = false; setTabs("art");
  $("#pTitle").textContent = a.title || "결과물";
  $("#pType").textContent = ({html: "웹페이지", code: (a.lang || "코드"), markdown: "문서", svg: "SVG 그림", trading: "실시간 차트 · 트레이딩 룸", building: "건축 설계 · 3D·평면·AutoCAD/Revit/SketchUp/루미온 내보내기", image: "AI 렌더링 이미지"})[a.type] || a.type;
  const textual = ["html", "code", "markdown", "svg"].includes(a.type);
  $("#pView").hidden = !["html", "svg", "markdown"].includes(a.type);
  $("#pCopy").hidden = !textual; $("#pSave").hidden = !textual && a.type !== "image";
  $("#pContent").hidden = !textual && a.type !== "image"; $("#tradeHost").hidden = a.type !== "trading"; $("#archHost").hidden = a.type !== "building";
  if (a.type !== "trading") trade?.hide();
  if (textual){ pView = a.type === "code" ? "code" : "preview"; renderArtBody(); }
  if (a.type === "image") $("#pContent").innerHTML = `<div class="art-img"><img alt="${esc(a.title)}" src="${esc(a.src)}">${a.prompt ? `<p class="small">${esc(a.prompt)}</p>` : ""}</div>`;
  if (a.type === "trading"){
    if (!trade) trade = initTrade({root: $("#tradeHost"), brain: window.NuriBrain, apiBase, webGet, toast, md, esc, ls, launcher: () => LAUNCHER.on});
    await trade.goto(a.ex, a.market, a.tf); trade.show();
  }
  if (a.type === "building") return loadBuilding(a.spec, wait);
}
function renderArtBody(){
  const a = panelArt, c = $("#pContent");
  $$("#pView button").forEach(b => b.setAttribute("aria-pressed", b.dataset.v === pView));
  if (pView === "code" || a.type === "code"){
    const lines = a.content.split("\n").length;
    c.innerHTML = `<div class="art-code"><div class="lnum"><div class="g">${Array.from({length: lines}, (_, k) => k + 1).join("\n")}</div><pre><code>${highlight(a.content)}</code></pre></div></div>`;
  } else if (a.type === "html"){
    c.innerHTML = ""; const f = document.createElement("iframe");
    f.setAttribute("sandbox", "allow-scripts allow-forms allow-modals allow-popups"); f.title = a.title; f.srcdoc = a.content; c.appendChild(f);
  } else if (a.type === "svg"){
    c.innerHTML = `<div style="padding:24px;display:grid;place-items:center"><img alt="${esc(a.title)}" style="max-width:100%;background:#fff;border-radius:8px" src="data:image/svg+xml;charset=utf-8,${encodeURIComponent(a.content)}"></div>`;
  } else c.innerHTML = `<div class="art-md md">${md(a.content)}</div>`;
}
$("#pView").addEventListener("click", e => { const b = e.target.closest("[data-v]"); if (!b || !panelArt) return; pView = b.dataset.v; renderArtBody(); });
$("#pCopy").onclick = () => panelArt && copy(panelArt.content);
$("#pSave").onclick = () => {
  if (!panelArt) return;
  if (panelArt.type === "image"){ const a = document.createElement("a"); a.href = panelArt.src; a.download = (panelArt.title || "render").replace(/[\\/:*?"<>|]+/g, "_") + (/^data:image\/png/.test(panelArt.src) ? ".png" : ".jpg"); document.body.append(a); a.click(); a.remove(); return; }
  const ext = {html: "html", markdown: "md", svg: "svg"}[panelArt.type] || ({python:"py", py:"py", javascript:"js", js:"js", typescript:"ts", ts:"ts", java:"java", c:"c", cpp:"cpp", go:"go", rust:"rs", sql:"sql", css:"css", bash:"sh", sh:"sh", json:"json", html:"html"}[(panelArt.lang || "").toLowerCase()] || "txt");
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([panelArt.content], {type: "text/plain;charset=utf-8"}));
  a.download = (panelArt.title || "nuri").replace(/[\\/:*?"<>|]+/g, "_") + "." + ext; document.body.append(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
};
function closePanel(){ $("#panel").hidden = true; trade?.hide(); panelArt = null; }

/* ============ 진행 상황 (지금 무엇을 하는지 실시간으로) ============ */
function openActivity(){
  $("#panel").hidden = false; setTabs("act"); trade?.hide();
  $("#pTitle").textContent = "진행 상황"; $("#pType").textContent = "누리가 지금 하는 일 · 쓴 AI · 스킬 · 도구 · 출처";
  $("#pView").hidden = $("#pCopy").hidden = $("#pSave").hidden = true;
  $("#pContent").hidden = $("#tradeHost").hidden = $("#archHost").hidden = true;
  renderActivity();
}
const fmtSec = ms => ms >= 60000 ? `${Math.floor(ms / 60000)}분 ${Math.round(ms % 60000 / 1000)}초` : `${(ms / 1000).toFixed(1)}초`;
function renderActivity(){
  if ($("#panel").hidden || panelTab !== "act" || !current) return;
  const H = $("#actHost"); let i = current.messages.length - 1; while (i >= 0 && current.messages[i].role !== "assistant") i--;
  const m = current.messages[i];
  if (!m){
    const r = routeCandidates("general")[0];
    H.innerHTML = `<div class="act"><div class="act-card"><b>대기 중</b><p class="small">질문을 보내면 어떤 AI가 답하는지, 어떤 스킬과 도구를 쓰는지, 무엇을 검색하고 읽는지가 여기에 실시간으로 보입니다.</p>
      <div class="kv"><span>사용 방식</span><b>${esc(brainName(settings.brain))}</b></div>${r ? `<div class="kv"><span>다음 답변 예상</span><b>${esc((PROVIDERS[r.id]?.name || r.id) + " · " + shortModel(r.model))}</b></div>` : ""}
      <div class="kv"><span>연결된 AI</span><b>${connectedAI().length}곳</b></div><div class="kv"><span>스킬</span><b>기본 ${BUILTIN_SKILLS.length} · 내 스킬 ${(settings.skills || []).length}</b></div></div>
      <button class="btn" data-open="tpl">${ico("grid","width:15px;height:15px")} 템플릿으로 시작하기</button></div>`;
    return;
  }
  const now = Date.now(), t0 = m.t0 || m.ts, el = (m.streaming ? now : (m.t1 || t0 + (m.ms || 0))) - t0;
  const st = m.streaming ? "run" : m.error ? "bad" : "ok";
  const items = [];
  for (const l of m.log || []) if (l.kind === "route" || l.kind === "fallback") items.push({t: l.t, cls: l.kind === "fallback" ? "warn" : "info", ic: l.kind === "fallback" ? "↻" : "◆", title: l.kind === "fallback" ? "AI 교체" : "AI 연결", sub: l.text});
  for (const p of aiParts(m)){
    if (p.type === "text"){
      const body = splitThink(p.text).body.trim(), th = [p.think, splitThink(p.text).think].filter(Boolean).join("\n").trim();
      const ft = p.tf || p.t0 || t0;
      if (th) items.push({t: ft, cls: "think", ic: "✦", title: "생각", sub: th.slice(-220), dur: p.t1 && p.t0 ? p.t1 - p.t0 : 0});
      if (body) items.push({t: ft + 1, cls: "text", ic: "✎", title: "답변 작성", sub: `${body.length.toLocaleString()}자`});
    } else if (p.type === "tool"){
      const s = {running: "run", done: "ok", error: "bad", denied: "bad", pending: "warn"}[p.status] || "run";
      items.push({t: p.t0 || t0, cls: "tl-tool " + s, ic: p.status === "done" ? "✓" : p.status === "error" || p.status === "denied" ? "!" : "•", title: p.act || p.label || p.name,
        sub: p.status === "error" ? p.error : p.status === "denied" ? "거부됨" : p.status === "pending" ? "허락을 기다리는 중" : p.status === "running" ? "실행 중…" : p.summary || "",
        dur: p.t1 && p.t0 ? p.t1 - p.t0 : p.t0 && p.status === "running" ? now - p.t0 : 0, tool: p});
    }
  }
  items.sort((a, b) => a.t - b.t);
  const arts = [];
  aiParts(m).forEach((p, j) => { if (p.type === "tool" && p.artifact) arts.push({key: "tool:" + p.id, a: p.artifact}); if (p.type === "text") artifactsIn(splitThink(p.text).body).forEach((a, n) => arts.push({key: `${i}:${j}:${n}`, a})); });
  H.innerHTML = `<div class="act">
    <div class="act-card"><div class="act-top"><span class="act-st ${st}"></span><div><b>${esc(m.streaming ? (m.phase || "작업 중") : m.error ? "멈춤" : "완료")}</b><span class="small">${fmtSec(el)}${m.parts?.filter(p => p.type === "tool").length ? ` · 도구 ${m.parts.filter(p => p.type === "tool").length}번` : ""}</span></div></div>
      ${m.route ? `<div class="kv"><span>답한 AI</span><b>${esc(m.route.name)} · ${esc(shortModel(m.route.model))}</b></div>` : ""}
      ${m.qrole ? `<div class="kv"><span>질문 종류</span><b>${esc(ROLE_KO[m.qrole] || m.qrole)}</b></div>` : ""}
      ${m.skills?.length ? `<div class="kv"><span>켜진 스킬</span><b class="chips-s">${m.skills.map(s => `<span>${esc(s.icon || "✨")} ${esc(s.name)}</span>`).join("")}</b></div>` : ""}
      ${m.error ? `<div class="err">${esc(m.error)}</div>` : ""}</div>
    ${m.todos?.length ? `<div class="act-sec"><h4>할 일</h4><div class="todos">${m.todos.map(t => `<div class="td ${esc(t.status)}">${t.status === "completed" ? "☒" : t.status === "in_progress" ? "▣" : "☐"} ${esc(t.content)}</div>`).join("")}</div></div>` : ""}
    <div class="act-sec"><h4>타임라인</h4><ol class="tl">${items.map(x => `<li class="${x.cls}"><span class="ic">${x.cls.includes("run") ? `<span class="spin"></span>` : esc(x.ic)}</span><div><div class="tt"><b>${esc(x.title)}</b>${x.dur ? `<span class="small">${fmtSec(x.dur)}</span>` : ""}</div>${x.sub ? `<div class="sb">${esc(x.sub)}</div>` : ""}${x.tool?.sources?.length ? `<div class="srcs mini">${x.tool.sources.slice(0, 5).map(s => `<a href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(s.title)}">${esc(hostOf(s.url))}</a>`).join("")}</div>` : ""}</div></li>`).join("") || `<li class="info"><span class="ic"><span class="spin"></span></span><div><b>준비 중</b></div></li>`}</ol></div>
    ${arts.length ? `<div class="act-sec"><h4>결과물</h4>${arts.map(x => artCard(x.a.title, artTypeLabel(x.a), x.key, x.a.type)).join("")}</div>` : ""}
    ${m.sources?.length ? `<div class="act-sec"><h4>출처 ${m.sources.length}개</h4><ol class="src-list">${m.sources.map(s => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title || s.url)}</a><span class="small">${esc(hostOf(s.url))}</span></li>`).join("")}</ol></div>` : ""}
  </div>`;
}
$("#pClose").onclick = closePanel;
$("#drag").addEventListener("pointerdown", e => {
  const d = $("#drag"); d.setPointerCapture(e.pointerId);
  const move = ev => { const w = Math.min(window.innerWidth * .72, Math.max(380, window.innerWidth - ev.clientX)); document.documentElement.style.setProperty("--panel-w", w + "px"); };
  const up = () => { d.removeEventListener("pointermove", move); d.removeEventListener("pointerup", up); };
  d.addEventListener("pointermove", move); d.addEventListener("pointerup", up);
});
// 건축 설계: 같은 출처 iframe의 __archai.load()로 설계를 넘기고 수치를 받는다
let archReady = null;
function loadBuilding(spec, wait){
  const f = $("#archFrame");
  if (!archReady) archReady = new Promise(res => { f.addEventListener("load", () => { const t = setInterval(() => { try { if (f.contentWindow.__archai){ clearInterval(t); res(); } } catch(e){} }, 100); }, {once: true}); f.src = "../arch-ai/"; });
  const p = archReady.then(() => { try { return f.contentWindow.__archai.load(spec); } catch(e){ return null; } });
  return wait ? Promise.race([p, new Promise(r => setTimeout(() => r(null), 15000))]) : p;
}

/* ============ 설정 ============ */
let sheetTab = "brain";
function openSheet(tab){ sheetTab = tab || sheetTab; if (tab === "tpl"){ const k = TEMPLATES.findIndex(c => (c.mode || "chat") === mode); if (mode === "code" && k >= 0) tplCat = k; else if (TEMPLATES[tplCat]?.mode === "code") tplCat = 0; } if (!$("#sheet").open) $("#sheet").showModal(); renderSheet(); $("#modelMenu").hidden = true; }
$("#openSettings").onclick = () => openSheet("brain");
$("#openKnow").onclick = () => openSheet("know");
$("#openTpl").onclick = () => openSheet("tpl");
$("#sheetClose").onclick = () => $("#sheet").close();
$("#sheet").addEventListener("click", e => { if (e.target.id === "sheet") $("#sheet").close(); });
$("#sheetNav").addEventListener("click", e => { const b = e.target.closest("[data-tab]"); if (b){ sheetTab = b.dataset.tab; renderSheet(); } });
async function renderSheet(){
  $$("#sheetNav [data-tab]").forEach(b => b.setAttribute("aria-current", b.dataset.tab === sheetTab));
  const B = $("#sheetBody");
  if (sheetTab === "brain") B.innerHTML = brainTab();
  if (sheetTab === "local"){ await refreshCache(); B.innerHTML = localTab(); $("#s-device").value = settings.device; $("#s-ctx").value = settings.ctx; }
  if (sheetTab === "know") B.innerHTML = knowTab();
  if (sheetTab === "instr") B.innerHTML = `<h3 class="h">맞춤 지침</h3><p class="sub">누리가 모든 대화에서 기억할 내용입니다. 하는 일, 관심사, 원하는 답변 스타일을 적어 두세요.</p>
    <div class="form" style="grid-template-columns:1fr"><label>지침<textarea id="instr" style="min-height:220px" placeholder="예: 나는 건축사무소를 운영하고 코인 단타를 한다. 답은 짧게 핵심만, 숫자는 표로 정리해줘.">${esc(settings.instructions)}</textarea></label></div><div class="row"><button class="btn primary" id="instrSave">저장</button></div>`;
  if (sheetTab === "about") B.innerHTML = aboutTab();
  if (sheetTab === "tpl") B.innerHTML = tplTab();
  if (sheetTab === "skills") B.innerHTML = skillsTab();
  if (sheetTab === "mem") B.innerHTML = memTab();
}
/* ---- 템플릿 ---- */
let tplCat = 0;
function tplTab(){
  const cats = TEMPLATES, c = cats[tplCat] || cats[0];
  return `<h3 class="h">템플릿</h3><p class="sub">자주 쓰는 요청을 골라 바로 시작하세요. [대괄호] 부분만 바꿔서 보내면 됩니다.</p>
    <div class="seg wrap" id="tplCats">${cats.map((x, k) => `<button data-tplcat="${k}" aria-pressed="${k === tplCat}">${esc(x.icon)} ${esc(x.name)}</button>`).join("")}</div>
    <div class="tpls">${c.items.map((t, k) => `<button class="tpl" data-tpl="${tplCat}:${k}"><b>${esc(t.title)}</b><span>${esc(t.text)}</span>${c.mode === "code" ? `<i>코드 모드</i>` : ""}</button>`).join("")}</div>`;
}
function useTemplate(key){
  const [ci, ti] = key.split(":").map(Number), c = TEMPLATES[ci], t = c?.items[ti]; if (!t) return;
  $("#sheet").close();
  if ((c.mode || "chat") !== mode && !busy) setMode(c.mode || "chat");
  input.value = t.text; autoGrow(); updateSend(); input.focus();
  const a = t.text.indexOf("["), b = t.text.indexOf("]", a); if (a >= 0 && b > a) input.setSelectionRange(a, b + 1);
}
/* ---- 스킬 ---- */
function skillsTab(){
  const off = settings.skillsOff || [], mine = settings.skills || [];
  return `<h3 class="h">스킬</h3><p class="sub">스킬은 분야별 전문가의 일하는 방식(지침)과 도구 묶음입니다. 질문 내용에 맞는 스킬이 자동으로 켜지고, '진행 상황'에서 어떤 스킬을 썼는지 보입니다. 나만의 스킬을 만들어 누리에게 일하는 방식을 가르칠 수 있습니다.</p>
    <div class="tiles">${BUILTIN_SKILLS.map(sk => { const on = !off.includes(sk.id); return `<div class="tile${on ? "" : " dim"}"><div class="hd"><b>${esc(sk.icon)} ${esc(sk.name)}</b><button class="btn" data-skoff="${sk.id}">${on ? "켜짐" : "꺼짐"}</button></div>
      <div class="meta">${(sk.tools || []).map(t => `<span class="tag">${esc(TOOLS[t]?.label || t)}</span>`).join("")}</div><details><summary class="small">지침 보기</summary><pre class="skp">${esc(sk.prompt)}</pre></details></div>`; }).join("")}</div>
    <div class="card"><h3>새 스킬 만들기</h3><div class="body"><div class="form" style="grid-template-columns:1fr">
      <label>이름<input id="skName" placeholder="예: 우리 회사 주간보고 양식"></label>
      <label>켜지는 단어 (쉼표로 구분)<input id="skKeys" placeholder="예: 주간보고, 보고서"></label>
      <label>지침 (누리가 이 일을 할 때 따를 방법)<textarea id="skPrompt" placeholder="예: 보고서는 ①요약 3줄 ②진행 현황 표 ③이슈 ④다음 주 계획 순서로 쓴다. 금액은 만원 단위."></textarea></label>
      <label class="chk"><input type="checkbox" id="skAlways"> 모든 대화에서 항상 켜기</label></div>
      <div class="row"><button class="btn primary" id="skAdd">스킬 추가</button></div></div></div>
    <div class="card"><h3>내 스킬 <small>${mine.length}개</small></h3><div class="body"><div class="list">${mine.length ? mine.map(sk => `<div><span class="t"><b>${esc(sk.name)}</b> <span class="small">${sk.always ? "항상" : esc(sk.keys || "")}</span></span><button class="btn" data-sktoggle="${sk.id}">${sk.off ? "꺼짐" : "켜짐"}</button><button class="btn danger" data-skrm="${sk.id}">삭제</button></div>`).join("") : `<p class="empty">아직 없습니다.</p>`}</div></div></div>`;
}
/* ---- 기억 ---- */
function memTab(){
  const mem = settings.memory || [];
  return `<h3 class="h">기억</h3><p class="sub">대화 중에 "기억해줘"라고 하거나 누리가 앞으로 도움이 될 정보라고 판단하면 여기에 저장되고, 이후 모든 대화에서 참고합니다. 이 컴퓨터에만 저장됩니다.</p>
    <div class="card"><div class="body"><div class="keyrow"><input id="memIn" placeholder="직접 추가: 예) 나는 경기도에서 건축사무소를 운영한다"><button class="btn primary" id="memAdd">추가</button></div></div></div>
    <div class="card"><h3>기억한 것 <small>${mem.length}개</small></h3><div class="body"><div class="list">${mem.length ? mem.map((m, k) => `<div><span class="t">${esc(m.text)}</span><span class="small">${new Date(m.t).toLocaleDateString("ko-KR")}</span><button class="btn danger" data-memrm="${k}">삭제</button></div>`).reverse().join("") : `<p class="empty">아직 없습니다.</p>`}</div></div></div>`;
}
bus.addEventListener("engine", () => { renderModelBtn(); if ($("#sheet").open && (sheetTab === "brain" || sheetTab === "local")) renderSheet(); if (current && !current.messages.length) render(); });
function brainTab(){
  const conn = connectedAI(), exeNote = LAUNCHER.on ? "" : `<p class="err small">웹 버전에서는 외부 AI 연결이 막힐 수 있습니다. NuriAI.exe로 실행하세요.</p>`;
  const opts = (list, cur) => list.map(([v, l]) => `<option value="${esc(v)}"${v === cur ? " selected" : ""}>${esc(l)}</option>`).join("") + (list.some(x => x[0] === cur) ? "" : `<option value="${esc(cur)}" selected>${esc(cur)}</option>`);
  const pickName = c => c ? `${c.id === "local" ? "내 기기" : c.id === "ollama" ? "Ollama" : PROVIDERS[c.id].name} · ${shortModel(c.model)}` : "—";
  const IMG = [["black-forest-labs/flux.1-dev", "FLUX.1 dev · 고품질"], ["black-forest-labs/flux.1-schnell", "FLUX.1 schnell · 빠름"], ["stabilityai/stable-diffusion-3-medium", "Stable Diffusion 3 Medium"]];
  return `<h3 class="h">AI 두뇌</h3><p class="sub">무료 API 키를 붙여넣기만 하면 어느 회사 키인지 알아보고 연결합니다. 여러 곳을 넣어 두면 질문 종류(일반·코딩·추론)에 가장 맞는 모델을 스스로 고르고, 한 곳이 한도에 걸리거나 막히면 자동으로 다른 곳으로 바꿉니다.</p>
  <div class="card"><div class="body"><div class="keyrow"><input type="password" id="apiKey" placeholder="API 키 붙여넣기 (nvapi-… gsk_… csk-… AIza… sk-or-… hf_… tvly-… BSA…)" autocomplete="off" aria-label="API 키"><button class="btn primary" id="apiAdd">연결</button></div>
    <span class="small" id="apiMsg">키는 이 컴퓨터에만 저장되고 해당 회사로만 전송됩니다.</span>${exeNote}</div></div>
  <div class="card"><h3>사용 방식</h3><div class="body">
    <div class="seg wrap" id="brainSeg">${[["auto", "자동 선택 (추천)"], ...conn.map(id => [id, PROVIDERS[id].name + " 우선"]), ["ollama", "Ollama (내 PC)"], ["local", "내 기기 AI"]].map(([id, l]) => `<button data-usebrain="${id}" aria-pressed="${settings.brain === id}">${esc(l)}</button>`).join("")}</div>
    <div class="routes">${["general", "code", "reason", "fast"].map(r => `<div><span>${ROLE_KO[r]}</span><b>${esc(pickName(routeCandidates(r)[0]))}</b></div>`).join("")}</div>
    <span class="small">자동 선택이 지금 고를 모델입니다. 위에서 막히면 다음 후보로 넘어갑니다.</span></div></div>
  <div class="card"><h3>연결된 AI <small>${conn.length}곳</small></h3><div class="body"><div class="list">${conn.length ? conn.map(id => { const ms = (settings.provModels[id] || PROVIDERS[id].defaults); return `<div class="prov"><span class="t"><b>${esc(PROVIDERS[id].name)}</b><span class="small">모델 ${ms.length}개 · ${esc(PROVIDERS[id].note)}</span></span>
      <select class="sel" data-pin="${id}" aria-label="${esc(PROVIDERS[id].name)} 모델"><option value="">모델 자동</option>${ms.slice().sort().map(m => `<option${settings.pinModel[id] === m ? " selected" : ""}>${esc(m)}</option>`).join("")}</select>
      <button class="btn" data-btest="${id}">테스트</button><button class="btn danger" data-rmkey="${id}">삭제</button></div>`; }).join("") : `<p class="empty">아직 없습니다. 아래에서 무료 키를 받아 위에 붙여넣으세요.</p>`}
    ${Object.entries(SEARCH_KEYS).filter(([id]) => settings.keys[id]).map(([id, p]) => `<div class="prov"><span class="t"><b>${esc(p.name)}</b><span class="small">고급 인터넷 검색</span></span><button class="btn danger" data-rmkey="${id}">삭제</button></div>`).join("")}</div></div></div>
  <div class="card"><h3>무료 키 받는 곳</h3><div class="body"><div class="provs">${Object.entries(PROVIDERS).map(([id, p]) => `<a class="pv${settings.keys[id] ? " on" : ""}" href="${p.url}" target="_blank" rel="noopener"><b>${esc(p.name)}</b><span>${esc(p.note)}</span>${settings.keys[id] ? `<i>연결됨</i>` : ""}</a>`).join("")}
    ${Object.entries(SEARCH_KEYS).map(([id, p]) => `<a class="pv${settings.keys[id] ? " on" : ""}" href="${p.url}" target="_blank" rel="noopener"><b>${esc(p.name)}</b><span>선택 · 없으면 무료 검색 사용</span>${settings.keys[id] ? `<i>연결됨</i>` : ""}</a>`).join("")}</div></div></div>
  <div class="tiles">
    <div class="tile"><div class="hd"><b>이미지 렌더링</b><span class="pill"><i class="dot ${settings.keys.nvidia ? "ok" : "bad"}"></i>${settings.keys.nvidia ? "NVIDIA 키 있음" : "NVIDIA 키 필요"}</span></div><p>건물 투시도·인테리어 렌더(루미온 스타일)를 NVIDIA 무료 이미지 AI로 만듭니다.</p><label class="small">모델<select class="sel" id="img-model">${opts(IMG, settings.imageModel || IMG[0][0])}</select></label></div>
    <div class="tile${settings.brain === "ollama" ? " active" : ""}"><div class="hd"><b>내 PC 대형 모델 (Ollama)</b><span class="pill"><i class="dot ${brainReady("ollama") ? "ok" : "bad"}"></i>${brainReady("ollama") ? "준비됨" : "설정 필요"}</span></div><p>고사양 PC라면 완전 오프라인으로. <a href="https://ollama.com/download" target="_blank" rel="noopener">Ollama</a> 설치 후 모델을 받으세요. 자동 선택에서도 후보로 씁니다.</p>
      <label class="small">모델<select class="sel" id="ol-model">${opts(OL_MODELS, settings.olModel)}</select></label><div class="row"><button class="btn" id="ol-list">받은 모델 보기</button><button class="btn" data-btest="ollama">연결 테스트</button></div></div>
    <div class="tile${settings.brain === "local" ? " active" : ""}"><div class="hd"><b>내 기기 AI</b><span class="pill"><i class="dot ${eng.w ? "ok" : "bad"}"></i>${eng.w ? "실행 중" : "모델 없음"}</span></div><p>인터넷 없이 이 컴퓨터에서 도는 소형 모델. 현재: ${esc(eng.loaded ? eng.loaded.name : "없음")}</p><div class="row"><button class="btn" data-open="local">내 기기 모델 고르기</button></div></div>
  </div>
  <div class="card"><h3>누리는 어떻게 배우나요?</h3><div class="body"><p class="small" style="margin:0">무료 API(NVIDIA 등)는 이미 학습된 모델을 '빌려 쓰는' 방식이라 모델 자체를 다시 학습시킬 수는 없습니다. 대신 누리는 <b>스킬</b>(분야별 일하는 방식), <b>기억</b>(나에 대한 정보), <b>내 지식</b>(올린 문서), <b>맞춤 지침</b>으로 매번 그것을 참고해 답하므로, 쓰면 쓸수록 나에게 맞춰집니다. 모델 자체를 미세조정하려면 GPU와 별도 학습 환경(NVIDIA NeMo, Unsloth 등)이 필요합니다.</p></div></div>`;
}
function localTab(){
  const act = eng.loaded;
  const cached = c => cacheList.find(x => x.name.toLowerCase().includes(c.quant.toLowerCase()) && x.name.toLowerCase().includes(c.name.split(" ")[0].toLowerCase().replace("-r1", "")));
  return `<h3 class="h">내 기기 모델</h3><p class="sub">오픈소스 모델을 이 컴퓨터로 내려받아 실행합니다. 처음 한 번만 내려받으면 다음부터 인터넷 없이 켜집니다.</p>
    <div class="card"><div class="body">
      <div class="row"><span class="pill"><i class="dot ${eng.w ? "ok" : eng.loading ? "warn" : "bad"}"></i>${eng.w ? "실행 중" : eng.loading ? "준비 중" : "모델 없음"}</span><b>${esc(act ? act.name : "—")}</b>${eng.w ? `<button class="btn" id="unload">메모리에서 내리기</button>` : ""}</div>
      ${eng.loading ? `<div class="progress"><i style="width:${Math.round(eng.progress*100)}%"></i></div><span class="small">${esc(eng.phase)}</span>` : ""}
      ${eng.error ? `<div class="err">${esc(eng.error)}</div>` : ""}
      <span class="small">가속: ${gpuSupported() ? "WebGPU 사용" : "CPU (느림)"} · CPU 스레드 ${self.crossOriginIsolated ? (navigator.hardwareConcurrency || 1) : 1}개</span>
    </div></div>
    <div class="tiles">${CATALOG.map(c => { const ca = cached(c), on = act && act.id === c.id; return `<div class="tile${on ? " active" : ""}"><div class="hd"><b>${esc(c.name)}</b><span class="tag${ca ? " good" : ""}">${ca ? "저장됨" : "약 " + c.gb + "GB"}</span></div><div class="meta">${c.tags.map(t => `<span class="tag">${esc(t)}</span>`).join("")}</div><p>${esc(c.desc)}</p><span class="small">라이선스: ${esc(c.lic)}</span><div class="row"><button class="btn${on ? "" : " primary"}" data-load="${c.id}" ${eng.loading || on ? "disabled" : ""}>${on ? "사용 중" : ca ? "바로 실행" : "내려받고 실행"}</button></div></div>`; }).join("")}</div>
    <div class="card"><h3>직접 불러오기 · 실행 설정</h3><div class="body"><div class="form">
      <label class="wide">내 컴퓨터의 GGUF 파일 (2GB 이하)<input type="file" id="ggufFile" accept=".gguf" multiple></label>
      <label class="wide">GGUF 파일 주소(URL)<input type="text" id="ggufUrl" placeholder="https://…/model.gguf"></label>
      <label>계산 장치<select id="s-device"><option value="auto">자동 (GPU 우선)</option><option value="gpu">GPU</option><option value="cpu">CPU만</option></select></label>
      <label>대화 기억 길이<select id="s-ctx"><option value="2048">2,048 토큰</option><option value="4096">4,096 토큰</option><option value="8192">8,192 토큰</option><option value="16384">16,384 토큰</option></select></label>
    </div><div class="row"><button class="btn" id="loadUrl">주소에서 불러오기</button><span class="small">장치와 기억 길이는 모델을 다시 불러오면 적용됩니다.</span></div></div></div>`;
}
function knowTab(){
  return `<h3 class="h">내 지식</h3><p class="sub">문서를 올려 두면 "내 문서에서 … 찾아줘"처럼 물었을 때 누리가 관련 부분을 찾아 답합니다. 문서는 이 컴퓨터에만 저장됩니다.</p>
    <div class="card"><div class="body"><div class="form" style="grid-template-columns:1fr">
      <label>파일 올리기 (.txt .md .csv .json .html 코드 등)<input type="file" id="docFiles" multiple></label>
      <label>또는 붙여넣기 · 제목<input type="text" id="docTitle" placeholder="예: 우리 회사 휴가 규정"></label>
      <label>내용<textarea id="docText" placeholder="문서 내용"></textarea></label></div>
      <div class="row"><button class="btn primary" id="docAdd">저장</button></div></div></div>
    <div class="card"><h3>저장된 문서 <small>${docs.length}개</small></h3><div class="body"><div class="list">${docs.length ? docs.slice().sort((a, b) => b.added - a.added).map(d => `<div><span class="t">${esc(d.name)}</span><span class="small">${fmtN(d.size)}자</span><button class="btn danger" data-rmdoc="${d.id}">삭제</button></div>`).join("") : `<p class="empty">아직 문서가 없습니다.</p>`}</div></div></div>`;
}
function aboutTab(){
  const msgs = chats.flatMap(c => c.messages), q = msgs.filter(m => m.role === "user").length;
  const tools = msgs.flatMap(m => m.parts || []).filter(p => p.type === "tool");
  const by = tools.reduce((o, p) => (o[p.label || p.name] = (o[p.label || p.name] || 0) + 1, o), {});
  const acct = ls.get("tr:acct:upbit", null);
  let tot = null; if (acct){ tot = acct.cash; for (const p of Object.values(acct.pos)) tot += p.qty * p.avg; }
  return `<h3 class="h">사용 현황</h3>
    <div class="kpis"><div class="kpi"><label>대화</label><span class="v">${fmtN(chats.length)}</span><span class="s">채팅 ${chats.filter(c => c.mode !== "code").length} · 코드 ${chats.filter(c => c.mode === "code").length}</span></div>
    <div class="kpi"><label>보낸 질문</label><span class="v">${fmtN(q)}</span></div><div class="kpi"><label>도구 사용</label><span class="v">${fmtN(tools.length)}</span></div>
    <div class="kpi"><label>내 지식</label><span class="v">${fmtN(docs.length)}</span><span class="s">문서</span></div>
    ${tot != null ? `<div class="kpi"><label>모의투자 (업비트)</label><span class="v" style="color:${tot >= acct.start ? "var(--up)" : "var(--down)"}">${((tot / acct.start - 1) * 100).toFixed(2)}%</span><span class="s">매수가 기준</span></div>` : ""}</div>
    <div class="card"><h3>자주 쓴 도구</h3><div class="body"><div class="list">${Object.entries(by).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<div><span class="t">${esc(k)}</span><span class="small">${v}회</span></div>`).join("") || `<p class="empty">아직 없습니다.</p>`}</div></div></div>
    <p class="small">누리 AI · 오픈소스 모델과 llama.cpp(wllama)로 동작합니다. ${LAUNCHER.on ? "실행기(NuriAI.exe) 연결됨." : "웹 버전으로 실행 중입니다."}</p>`;
}
$("#sheetBody").addEventListener("change", async e => {
  const t = e.target;
  if (t.dataset.pin){ if (t.value) settings.pinModel[t.dataset.pin] = t.value; else delete settings.pinModel[t.dataset.pin]; saveSettings(); }
  if (t.id === "img-model"){ settings.imageModel = t.value; saveSettings(); }
  if (t.id === "ol-model"){ settings.olModel = t.value; saveSettings(); }
  if (t.id === "s-device"){ settings.device = t.value; saveSettings(); }
  if (t.id === "s-ctx"){ settings.ctx = +t.value; saveSettings(); }
  if (t.id === "ggufFile" && t.files.length){ const files = [...t.files].sort((a, b) => a.name.localeCompare(b.name)); settings.brain = "local"; await loadModel({kind: "file", name: files[0].name.replace(/(-\d{5}-of-\d{5})?\.gguf$/i, ""), files}); }
  if (t.id === "docFiles"){ let n = 0; for (const f of t.files){ try { if (await addDoc(f.name, await readTextFile(f))) n++; } catch(err){ toast(err.message); } } if (n) toast(`문서 ${n}개를 추가했습니다`); renderSheet(); }
});
$("#sheetBody").addEventListener("keydown", e => { if (e.key !== "Enter" || e.isComposing) return; if (e.target.id === "apiKey") $("#apiAdd").click(); if (e.target.id === "memIn") $("#memAdd").click(); });
$("#sheetBody").addEventListener("click", async e => {
  const t = e.target;
  if (t.dataset.usebrain){ settings.brain = t.dataset.usebrain; saveSettings(); toast(brainName(t.dataset.usebrain) + (brainReady() ? "" : " · 설정이 더 필요합니다")); }
  if (t.id === "apiAdd"){
    const v = $("#apiKey").value.trim(); if (!v){ toast("키를 붙여넣으세요"); return; }
    t.disabled = true; $("#apiMsg").textContent = "어느 회사 키인지 확인하고 모델 목록을 받는 중…";
    try { const r = await addApiKey(v); toast(r.kind === "search" ? `${r.name} 연결됨` : `${r.name} 연결됨${r.models ? ` · 모델 ${r.models}개` : ""}${r.warn ? " (목록 확인 실패: " + r.warn + ")" : ""}`); renderSheet(); renderModelBtn(); }
    catch(err){ $("#apiMsg").textContent = err.message; t.disabled = false; }
  }
  if (t.dataset.rmkey){ if (t.dataset.c !== "1"){ t.dataset.c = "1"; t.textContent = "정말 삭제"; return; } removeApiKey(t.dataset.rmkey); renderSheet(); }
  const tc = t.closest("[data-tplcat]"); if (tc){ tplCat = +tc.dataset.tplcat; renderSheet(); }
  const tp = t.closest("[data-tpl]"); if (tp){ useTemplate(tp.dataset.tpl); return; }
  if (t.dataset.skoff){ const o = new Set(settings.skillsOff || []); o.has(t.dataset.skoff) ? o.delete(t.dataset.skoff) : o.add(t.dataset.skoff); settings.skillsOff = [...o]; saveSettings(); renderSheet(); }
  if (t.id === "skAdd"){
    const name = $("#skName").value.trim(), prompt = $("#skPrompt").value.trim(), keys = $("#skKeys").value.trim(), always = $("#skAlways").checked;
    if (!name || prompt.length < 10){ toast("이름과 10자 이상의 지침을 넣으세요"); return; }
    if (!keys && !always){ toast("켜지는 단어를 넣거나 '항상 켜기'를 고르세요"); return; }
    (settings.skills ||= []).push({id: uid(), name, keys, prompt, always}); saveSettings(); toast("스킬을 추가했습니다"); renderSheet();
  }
  if (t.dataset.sktoggle){ const sk = settings.skills.find(x => x.id === t.dataset.sktoggle); if (sk){ sk.off = !sk.off; saveSettings(); renderSheet(); } }
  if (t.dataset.skrm){ settings.skills = settings.skills.filter(x => x.id !== t.dataset.skrm); saveSettings(); renderSheet(); }
  if (t.id === "memAdd"){ const v = $("#memIn").value.trim(); if (v){ (settings.memory ||= []).push({text: v.slice(0, 300), t: Date.now()}); saveSettings(); renderSheet(); } }
  if (t.dataset.memrm){ settings.memory.splice(+t.dataset.memrm, 1); saveSettings(); renderSheet(); }
  const ld = t.closest("[data-load]"); if (ld){ const c = CATALOG.find(x => x.id === ld.dataset.load); settings.brain = "local"; saveSettings(); loadModel({kind: "hf", id: c.id, name: c.name, repo: c.repo, quant: c.quant}); }
  if (t.id === "unload") unloadModel();
  if (t.id === "loadUrl"){ const url = $("#ggufUrl").value.trim(); if (!/^https?:\/\/.+\.gguf(\?.*)?$/i.test(url)){ toast(".gguf로 끝나는 주소를 넣으세요"); return; } settings.brain = "local"; loadModel({kind: "url", name: decodeURIComponent(url.split("/").pop().split("?")[0]).replace(/\.gguf$/i, ""), url}); }
  if (t.id === "instrSave"){ settings.instructions = $("#instr").value.trim(); saveSettings(); toast("지침을 저장했습니다"); }
  if (t.id === "docAdd"){ const title = $("#docTitle").value.trim(), text = $("#docText").value.trim(); if (!title || text.length < 20){ toast("제목과 20자 이상의 내용을 넣으세요"); return; } await addDoc(title, text); toast("저장했습니다"); renderSheet(); }
  if (t.dataset.rmdoc){ if (t.dataset.c !== "1"){ t.dataset.c = "1"; t.textContent = "정말 삭제"; return; } await removeDoc(t.dataset.rmdoc); renderSheet(); }
  if (t.dataset.btest){
    const prev = settings.brain, was = settings.olOk; settings.brain = t.dataset.btest; if (t.dataset.btest === "ollama") settings.olOk = true;
    t.disabled = true; t.textContent = "확인 중…";
    try { let out = ""; const c = await brainStream({messages: [{role: "user", content: "한 단어로만 답해: 안녕?"}], maxTokens: 32, temperature: 0, only: t.dataset.btest, onContent: d => out += d}); toast(`연결 성공${c?.model ? " · " + shortModel(c.model) : ""}: ` + (splitThink(out).body.trim().slice(0, 30) || "응답 받음")); if (t.dataset.btest === "ollama") settings.olOk = true; }
    catch(err){ toast(err.message); settings.olOk = t.dataset.btest === "ollama" ? false : was; }
    finally { settings.brain = prev; saveSettings(); t.disabled = false; t.textContent = "테스트"; }
  }
  if (t.id === "ol-list"){
    t.disabled = true;
    try {
      let names = [];
      { const r = await fetch(apiBase("ollama") + "/api/tags"); if (!r.ok) throw new Error("Ollama 응답 오류 " + r.status); names = (await r.json()).models.map(m => m.name); settings.olOk = names.length > 0; }
      const sel = $("#ol-model"), cur = sel.value;
      if (!names.length) toast("받은 모델이 없습니다. Ollama 앱에서 모델을 먼저 받으세요.");
      else { sel.innerHTML = names.map(n => `<option${n === cur ? " selected" : ""}>${esc(n)}</option>`).join(""); if (!names.includes(cur)){ sel.value = names[0]; sel.dispatchEvent(new Event("change", {bubbles: true})); } toast(`모델 ${names.length}개`); }
      saveSettings();
    } catch(err){ toast(err instanceof TypeError ? (LAUNCHER.on ? "연결 실패" : "NuriAI.exe로 실행해야 연결됩니다") : err.message); }
    finally { t.disabled = false; }
  }
});

/* ============ 시작 ============ */
(async () => {
  await detectLauncher();
  chats = (await idb.all("chat:")).map(c => ({...c, mode: c.mode || "chat"}));
  await loadDocs();
  setMode(mode, true); newChat(); renderList(); renderModelBtn(); syncSideBtn(); updateSend();
  refreshCache();
  if (settings.autoload && settings.last && settings.brain === "local" && !window.__nuriNoAutoload) loadModel(settings.last);
})();

// 서비스 워커: 오프라인 실행 + 멀티스레드용 격리 헤더 + 업데이트 시 새로고침
if ("serviceWorker" in navigator && /^https?:$/.test(location.protocol) && !window.__nuriNoSW){
  const hadController = !!navigator.serviceWorker.controller;
  navigator.serviceWorker.register("./sw.js", {updateViaCache: "none"}).then(reg => {
    const flag = "nuri:coi-reload";
    const maybeReload = () => { if (!self.crossOriginIsolated && !sessionStorage.getItem(flag) && !eng.loading && !busy){ sessionStorage.setItem(flag, "1"); location.reload(); } };
    if (navigator.serviceWorker.controller) maybeReload();
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (hadController && !sessionStorage.getItem("nuri:sw-updated") && !eng.loading && !busy){ sessionStorage.setItem("nuri:sw-updated", "1"); location.reload(); }
      else maybeReload();
    });
    reg.update().catch(() => {});
  }).catch(() => {});
}
window.__nuri = {get chats(){ return chats; }, get current(){ return current; }, settings, eng, LAUNCHER, openArtifact, get trade(){ return trade; }};
