// 누리 AI 화면: 채팅·코드 두 모드, 결과물 패널, 설정
import { esc, uid, fmtN, ls, idb, bus, settings, saveSettings, CATALOG, eng, loadModel, unloadModel, gpuSupported, refreshCache, cacheList,
  LAUNCHER, detectLauncher, apiBase, codeCall, OL_MODELS, BRAINS, brainReady, brainLabel, brainStream, splitThink,
  PROVIDERS, SEARCH_KEYS, addApiKey, removeApiKey, routeCandidates, shortModel, webGet, ollamaPull, ollamaImportGGUF,
  modelKind, KIND_KO, VISION_RE, rankModel, opfsSave, opfsList, opfsRemove,
  docs, loadDocs, addDoc, removeDoc, readTextFile, md, highlight } from "./engine.js";
import { runAgent, BUILTIN_SKILLS, TOOLS, installSkill, marketNews } from "./agent.js";
import { nvIndex, nvSkill, nvSearch, GROUP_KO } from "./nvskills.js";
import { TEMPLATES } from "./templates.js";
import { BASES, TOPICS, samplesFromChats, loadSynth, removeSynth, clearSynth, toJSONL, generateSynth, notebookJSON, localScript, teachers, NANO_MERGE, nanoNotebookJSON, mergeYAML, skillCoverage, generateAllSkills, fusionSources, fusionStats, toDPOJSONL } from "./train.js";
import { initTrade } from "./trade.js";

const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const AI = () => settings.aiName || "GH Nano";
function applyTheme(){ document.documentElement.dataset.theme = settings.theme || "dark"; const m = document.querySelector('meta[name="theme-color"]'); if (m) m.content = getComputedStyle(document.documentElement).getPropertyValue("--bg").trim() || "#0A0B0F"; }
function applyBrand(){ const n = AI(); document.title = n; $$(".brand-name").forEach(e => e.textContent = n); $$(".logo").forEach(e => e.textContent = [...n][0].toUpperCase()); }
const ico = (id, st = "") => `<svg class="i" style="${st}"><use href="#i-${id}"/></svg>`;
const toast = m => { const t = $("#toast"); t.textContent = m; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, 2800); };

/* ============ 상태 ============ */
let chats = [], current = null, mode = ls.get("mode", "chat"), attach = [];
// 대화마다 따로 돈다: 한 대화가 답하는 동안 다른 대화를 열거나 새 작업을 시작할 수 있다
const runs = new Map();                       // 대화 id → {ctl, msg}
const isBusy = (c = current) => !!(c && runs.has(c.id));
const byUpdated = () => chats.slice().sort((a, b) => b.updated - a.updated);
function saveChat(c){ c.updated = Date.now(); if (!chats.includes(c)) chats.push(c); idb.put("chat:" + c.id, c); }
const pendingPerm = new Map();

/* ============ 모드 ============ */
function setMode(m, keepChat){
  mode = m; ls.set("mode", m);
  $$(".modes [data-mode]").forEach(b => b.setAttribute("aria-selected", b.dataset.mode === m));
  $$(".code-only").forEach(e => e.hidden = m !== "code");
  $("#input").placeholder = m === "code" ? "무엇을 만들거나 고칠까요?" : `${AI()}에게 무엇이든 물어보세요`;
  $("#dockNote").textContent = m === "code" ? `${AI()} 코드는 작업 폴더의 파일을 읽고 고치며 명령을 실행합니다. 바꾸기 전에 허락을 구합니다.` : `${AI()}는 실수할 수 있습니다. 중요한 정보는 확인하세요.`;
  $("#permSel").value = settings.permission;
  if (!keepChat && current && (current.mode || "chat") !== m) newChat();
  renderWs();
}
$$(".modes [data-mode]").forEach(b => b.onclick = () => { if (b.dataset.mode !== mode) setMode(b.dataset.mode); });

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
    html += `<div class="grp">${label}</div>` + g.map(c => `<div class="ci" role="button" tabindex="0" data-id="${c.id}" aria-current="${current && current.id === c.id}">${runs.has(c.id) ? `<span class="spin" title="답하는 중"></span>` : ""}<span class="t">${esc(c.title)}</span>${c.mode === "code" ? `<span class="tag">코드</span>` : ""}<button class="del" data-del="${c.id}" aria-label="대화 삭제">삭제</button></div>`).join("");
  }
  $("#recents").innerHTML = html || `<div class="grp" style="font-weight:400">${q ? "검색 결과가 없습니다" : "대화가 여기에 쌓입니다"}</div>`;
}
$("#recents").addEventListener("click", e => {
  const d = e.target.closest("[data-del]"); if (d){ e.stopPropagation(); deleteChat(d.dataset.del); return; }
  const it = e.target.closest(".ci"); if (it) openChat(it.dataset.id);
});
$("#recents").addEventListener("keydown", e => { if (e.key === "Enter" && e.target.classList.contains("ci")) e.target.click(); });
$("#search").addEventListener("input", renderList);
let pendingDel = null;
function deleteChat(id){
  if (pendingDel !== id){ pendingDel = id; toast("한 번 더 누르면 삭제합니다"); setTimeout(() => { if (pendingDel === id) pendingDel = null; }, 3000); return; }
  pendingDel = null; runs.get(id)?.ctl.abort(); chats = chats.filter(c => c.id !== id); idb.del("chat:" + id);
  if (current && current.id === id) newChat();
  renderList(); toast("대화를 삭제했습니다");
}
function newChat(){
  current = {id: uid(), title: "새 대화", mode, created: Date.now(), updated: Date.now(), messages: [], workspace: mode === "code" ? ls.get("lastWs", "") : ""};
  closePanel(); render(); renderList(); renderWs(); closeSide(); $("#input").focus();
}
function openChat(id){
  const c = chats.find(x => x.id === id); if (!c) return newChat();
  current = c; setMode(c.mode || "chat", true); closePanel(); render(); renderList(); renderWs(); closeSide(); updateSend();
  if (isBusy(c)){ scrollDown(true); if (!isMobile() && innerWidth >= 1100) openActivity(); }
}
$("#newChat").onclick = () => { newChat(); updateSend(); };

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
// 좁은 화면에서는 패널이 화면 위쪽을 덮으므로, 입력창은 항상 아래(독)에 두고 패널은 그 위까지만 덮는다
const isNarrow = () => matchMedia("(max-width:980px)").matches;
function syncDock(){ const d = $("#dock"); document.documentElement.style.setProperty("--dock-h", (d.hidden ? 0 : d.offsetHeight) + "px"); }
if (window.ResizeObserver) new ResizeObserver(syncDock).observe($("#dock"));
addEventListener("resize", () => { syncDock(); if (current && !current.messages.length && !$("#panel").hidden) render(); });
function render(){
  const th = $("#thread"), empty = !current.messages.length;
  if ($("#composer").parentElement.id !== "dock") $("#dock").prepend($("#composer")); // 다시 그리기 전에 입력창을 안전한 곳으로
  $("#title").textContent = empty ? "" : current.title;
  if (empty && isNarrow() && !$("#panel").hidden){ th.innerHTML = ""; $("#dock").hidden = false; syncDock(); $("#panelToggle").hidden = !lastArtifact(); return; }
  if (empty){
    const note = !brainReady() ? `<div class="hero-note"><b>먼저 AI 두뇌를 준비하세요.</b> 입력창의 모델 버튼에서 고르거나 <a href="#" data-open="brain" style="color:var(--accent)">설정</a>을 여세요.</div>`
      : mode === "code" && !LAUNCHER.on ? `<div class="hero-note"><b>코드 모드는 GHNano.exe로 실행해야 쓸 수 있습니다.</b></div>`
      : mode === "code" && !current.workspace ? `<div class="hero-note">입력창의 <b>폴더 열기</b>로 작업할 폴더를 고르세요.</div>`
      : mode === "code" ? `<div class="hero-note">작업 폴더: <b>${esc(current.workspace)}</b></div>` : "";
    th.innerHTML = `<div class="hero"><h1><span class="logo">${esc([...AI()][0].toUpperCase())}</span><span class="g">${mode === "code" ? "무엇을 만들어 볼까요?" : GREET}</span></h1><p class="hero-sub">${mode === "code" ? "작업 폴더를 열고 무엇이든 맡기세요" : "코인·주식·선물 분석, 건축 설계, 리서치, 코딩까지 — 하나의 AI로"}</p><div class="hero-slot" id="heroSlot"></div>
      <div class="chips">${CHIPS[mode].map(([i, t]) => `<button class="chip" data-chip>${ico(i)}${esc(t)}</button>`).join("")}<button class="chip more" data-open="tpl">${ico("grid")}템플릿 더 보기</button></div>${note}</div>`;
    $("#heroSlot").appendChild($("#composer"));
    $("#dock").hidden = true; syncDock();
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
    const files = (m.images || []).map(u => `<img class="uimg" alt="첨부 이미지" src="${u}">`).join("") + (m.attach || []).map(a => `<span class="fchip">${ico("doc", "width:14px;height:14px")}${esc(a.name)}</span>`).join("");
    return `<div class="msg user" data-i="${i}">${files ? `<div class="files" style="justify-content:flex-end">${files}</div>` : ""}<div class="bubble">${esc(m.content)}</div>${isBusy() ? "" : `<div class="acts"><button data-act="copy">${ico("copy","width:14px;height:14px")}복사</button><button data-act="edit">${ico("pen","width:14px;height:14px")}수정</button></div>`}</div>`;
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
    ${m.streaming ? "" : `<div class="acts"><button data-act="copy">${ico("copy","width:14px;height:14px")}복사</button><button data-act="regen">${ico("redo","width:14px;height:14px")}다시 생성</button><button data-act="good" aria-pressed="${m.rating > 0}" title="좋은 답 (학습 데이터에 넣기)">👍</button><button data-act="bad" aria-pressed="${m.rating < 0}" title="나쁜 답 (학습에서 빼기)">👎</button><button data-openact>${ico("pulse","width:14px;height:14px")}과정</button><span class="meta">${esc(who)}${m.ms ? " · " + (m.ms/1000).toFixed(1) + "초" : ""}</span></div>`}</div>`;
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
  const pm = t.closest("[data-perm]"); if (pm){ const r = pendingPerm.get(pm.dataset.perm); if (r){ pendingPerm.delete(pm.dataset.perm); if (pm.dataset.v === "always") current.allowAll = true; r.res(pm.dataset.v !== "no"); } return; }
  const a = t.closest("[data-act]"); if (a && !isBusy()){
    const i = +a.closest(".msg").dataset.i, m = current.messages[i];
    if (a.dataset.act === "copy") copy(m.role === "user" ? m.content : aiParts(m).filter(p => p.type === "text").map(p => splitThink(p.text).body).join("\n\n"));
    if (a.dataset.act === "good" || a.dataset.act === "bad"){ const v = a.dataset.act === "good" ? 1 : -1; m.rating = m.rating === v ? 0 : v; saveChat(current); const el = $(`#thread .msg[data-i="${i}"]`); if (el) el.outerHTML = msgHTML(m, i); if (m.rating) toast(v > 0 ? "좋은 답으로 표시했습니다 · 학습 데이터에 들어갑니다" : "학습 데이터에서 뺍니다"); }
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
  if (isBusy()){ s.disabled = false; s.classList.add("stop"); s.innerHTML = ico("stop"); s.setAttribute("aria-label", "멈추기"); }
  else { s.classList.remove("stop"); s.innerHTML = ico("up"); s.setAttribute("aria-label", "보내기"); s.disabled = !input.value.trim() && !attach.length; }
}
input.addEventListener("input", () => { autoGrow(); updateSend(); });
input.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229){ e.preventDefault(); if (!isBusy()) send(); } });
$("#send").onclick = () => isBusy() ? stop() : send();
$("#thinkBtn").onclick = e => { settings.think = !settings.think; saveSettings(); e.currentTarget.setAttribute("aria-pressed", settings.think); };
$("#thinkBtn").setAttribute("aria-pressed", settings.think);
$("#permSel").onchange = e => { settings.permission = e.target.value; saveSettings(); };
// 이미지는 AI에 보낼 수 있게 줄여서(최대 약 170KB JPEG) 넣는다
async function shrinkImage(f){
  const img = await createImageBitmap(f);
  let w = img.width, h = img.height, max = 1280, q = 0.82, url = "";
  for (let k = 0; k < 6; k++){
    const sc = Math.min(1, max / Math.max(w, h)), c = document.createElement("canvas"); c.width = Math.round(w * sc); c.height = Math.round(h * sc);
    const g = c.getContext("2d"); g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height); g.drawImage(img, 0, 0, c.width, c.height);
    url = c.toDataURL("image/jpeg", q); if (url.length * 0.75 < 170e3) break; max = Math.round(max * 0.8); q = Math.max(0.5, q - 0.08);
  }
  return url;
}
let attachBusy = Promise.resolve();
function addFiles(list){ return attachBusy = attachBusy.then(() => addFilesNow(list)); }
async function addFilesNow(list){
  for (const f of list){
    try {
      if (/^image\//.test(f.type)) attach.push({name: f.name || "이미지.png", size: f.size, image: await shrinkImage(f)});
      else attach.push({name: f.name, size: f.size, text: await readTextFile(f)});
    } catch(err){ toast(err.message || "파일을 읽지 못했습니다"); }
  }
  renderPending(); updateSend();
}
$("#fileIn").addEventListener("change", async e => { await addFiles([...e.target.files]); e.target.value = ""; });
input.addEventListener("paste", e => { const imgs = [...(e.clipboardData?.files || [])].filter(f => /^image\//.test(f.type)); if (imgs.length){ e.preventDefault(); addFiles(imgs); } });
function renderPending(){ $("#pending").innerHTML = attach.map((a, i) => `<span class="fchip">${a.image ? `<img class="thumb" alt="" src="${a.image}">` : ""}${esc(a.name)} <button data-rm="${i}" aria-label="첨부 삭제">✕</button></span>`).join(""); }
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
async function send(){
  await attachBusy;
  const text = input.value.trim(); if (!text && !attach.length) return;
  if (!brainReady()){ toast("먼저 AI 두뇌를 준비하세요"); openSheet(settings.brain === "local" ? "local" : "brain"); return; }
  if (mode === "code"){
    if (!LAUNCHER.on){ toast("코드 모드는 GHNano.exe로 실행해야 쓸 수 있습니다"); return; }
    if ([...runs.values()].some(r => r.code)){ toast("다른 코드 작업이 진행 중입니다. 작업 폴더가 하나라 끝난 뒤에 실행하세요 (채팅은 동시에 됩니다)"); return; }
    if (!current.workspace){ toast("먼저 작업 폴더를 여세요"); $("#wsBtn").click(); return; }
  }
  current.mode = mode;
  const imgs = attach.filter(a => a.image), docsA = attach.filter(a => !a.image);
  current.messages.push({role: "user", content: text || (imgs.length ? "이 이미지를 보고 설명해줘" : "첨부한 파일을 살펴봐줘"), attach: docsA.length ? docsA : undefined, images: imgs.length ? imgs.map(a => a.image) : undefined, ts: Date.now()});
  if (current.title === "새 대화") current.title = (text || attach[0].name).replace(/\s+/g, " ").slice(0, 34);
  input.value = ""; attach = []; renderPending(); autoGrow();
  saveChat(current); renderList();
  run();
}
function stop(){
  const r = current && runs.get(current.id); if (!r) return;
  r.ctl.abort();
  for (const [id, p] of pendingPerm) if (p.chat === current.id){ p.res(false); pendingPerm.delete(id); }
}
async function run(){
  const chat = current, rmode = chat.mode || mode;
  const msg = {role: "assistant", parts: [], mode: rmode, model: brainLabel(), ts: Date.now(), streaming: true};
  const history = chat.messages.slice();
  chat.messages.push(msg);
  const ctl = new AbortController();
  runs.set(chat.id, {ctl, msg, code: rmode === "code"});
  updateSend(); render(); scrollDown(true); renderList();
  const t0 = performance.now(); let raf = 0;
  const idx = chat.messages.length - 1;
  const here = () => current === chat;
  const paint = () => { raf = 0; if (!here()) return; const el = $(`#thread .msg[data-i="${idx}"]`); if (el){ el.outerHTML = msgHTML(msg, idx); scrollDown(); } $("#panelToggle").hidden = !lastArtifact(); };
  const update = () => { if (!raf) raf = requestAnimationFrame(() => { paint(); if (here()) renderActivity(); }); };
  const onAct = e => { const d = e.detail || {}; (msg.log ||= []).push({t: Date.now(), kind: d.kind, text: d.text}); update(); };
  bus.addEventListener("activity", onAct);
  const tick = setInterval(update, 1000);
  if (!isMobile() && innerWidth >= 1100 && $("#panel").hidden && settings.autoActivity !== false) openActivity(true);
  else if (!$("#panel").hidden && panelTab === "act") renderActivity();
  try {
    if (rmode === "code") await codeCall("open", {path: chat.workspace});
    await runAgent({mode: rmode, history, msg, signal: ctl.signal, onUpdate: update, think: settings.think, workspace: chat.workspace,
      // 다른 대화를 보고 있으면 패널은 열지 않고(설계 수치 계산만) 결과를 카드로 남긴다
      openArtifact: (spec, wait) => here() ? openArtifact(spec, wait) : spec.type === "building" ? loadBuilding(spec, wait) : null,
      askPermission: tp => chat.allowAll ? Promise.resolve(true) : new Promise(res => { pendingPerm.set(tp.id, {res, chat: chat.id}); if (!here()) toast(`‘${chat.title}’ 대화가 허락을 기다립니다`); update(); })});
    if (!msg.parts.some(p => (p.type === "text" && p.text.trim()) || p.type === "tool")) msg.error = "빈 답변이 나왔습니다. 다시 생성해 보세요.";
  } catch (e){
    if (ctl.signal.aborted || e.name === "AbortError" || e.name === "WllamaAbortError"){ if (!msg.parts.length) msg.error = "답변을 멈췄습니다."; }
    else msg.error = String(e.message || e).slice(0, 300);
  } finally {
    cancelAnimationFrame(raf); clearInterval(tick); bus.removeEventListener("activity", onAct);
    msg.streaming = false; msg.ms = Math.round(performance.now() - t0);
    runs.delete(chat.id);
    if (chats.includes(chat) || chat.messages.length) saveChat(chat);
    renderList();
    if (here()){
      updateSend(); render(); renderActivity();
      // 이번 답변에서 새로 만든 글 결과물이 있으면 패널로 연다
      const arts = aiParts(msg).flatMap((p, j) => p.type === "text" ? artifactsIn(splitThink(p.text).body).map((a, n) => `${idx}:${j}:${n}`) : []);
      if (arts.length) openArtKey(arts[arts.length - 1]);
    } else toast(`‘${chat.title}’ 답변이 끝났습니다`);
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
  panelArt = a; $("#panel").hidden = false; setTabs("art"); panelOpened();
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
    if (!trade) trade = initTrade({root: $("#tradeHost"), brain: window.NuriBrain, apiBase, webGet, toast, md, esc, ls, launcher: () => LAUNCHER.on, news: marketNews});
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
function closePanel(){ $("#panel").hidden = true; trade?.hide(); panelArt = null; if (isNarrow() && current && !current.messages.length) render(); }
// 패널이 열릴 때 좁은 화면이면 입력창을 아래로 옮겨 항상 쓸 수 있게
function panelOpened(){ if (isNarrow() && current && !current.messages.length && $("#composer").parentElement.id !== "dock") render(); syncDock(); }
document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("#panel").hidden && !$("#sheet").open && isNarrow()) closePanel(); });

/* ============ 진행 상황 (지금 무엇을 하는지 실시간으로) ============ */
function openActivity(){
  $("#panel").hidden = false; setTabs("act"); trade?.hide(); panelOpened();
  $("#pTitle").textContent = "진행 상황"; $("#pType").textContent = `${AI()}가 지금 하는 일 · 쓴 AI · 스킬 · 도구 · 출처`;
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
  if (sheetTab === "instr") B.innerHTML = `<h3 class="h">화면 테마</h3><div class="seg wrap" id="themeSeg">${[["dark", "어둡게"], ["light", "밝게"], ["system", "시스템 따라"]].map(([v, l]) => `<button data-theme="${v}" aria-pressed="${(settings.theme || "dark") === v}">${l}</button>`).join("")}</div><h3 class="h">내 AI 이름</h3><div class="card"><div class="body"><div class="keyrow"><input id="aiName" value="${esc(AI())}" maxlength="24" aria-label="AI 이름"><button class="btn primary" id="aiNameSave">저장</button></div><span class="small">모든 모델·스킬을 하나로 묶은 내 AI의 이름입니다. 화면과 대화에서 이 이름을 씁니다.</span></div></div><h3 class="h">맞춤 지침</h3><p class="sub">${AI()}가 모든 대화에서 기억할 내용입니다. 하는 일, 관심사, 원하는 답변 스타일을 적어 두세요.</p>
    <div class="form" style="grid-template-columns:1fr"><label>지침<textarea id="instr" style="min-height:220px" placeholder="예: 나는 건축사무소를 운영하고 코인 단타를 한다. 답은 짧게 핵심만, 숫자는 표로 정리해줘.">${esc(settings.instructions)}</textarea></label></div><div class="row"><button class="btn primary" id="instrSave">저장</button></div>`;
  if (sheetTab === "about") B.innerHTML = aboutTab();
  if (sheetTab === "tpl") B.innerHTML = tplTab();
  if (sheetTab === "skills"){ B.innerHTML = skillsTab(); nvCard().then(h => { const el = $("#nvCard"); if (el) el.innerHTML = h; }).catch(err => { const el = $("#nvCard"); if (el) el.innerHTML = `<div class="body"><p class="err">${esc(err.message)}</p></div>`; }); }
  if (sheetTab === "mem") B.innerHTML = memTab();
  if (sheetTab === "train"){ B.innerHTML = await trainTab(); }
  if (sheetTab === "models"){ B.innerHTML = await modelsTab(); }
}
/* ---- 모델 탐색기: 연결된 모든 회사의 모든 모델 + Hugging Face GGUF + 내가 만든 모델 ---- */
let mdlQ = "", mdlKind = "all", hfQ = "", hfRes = null, hfFiles = null, hfBusy = false;
function allCloudModels(){
  const out = [];
  for (const id of connectedAI()) for (const m of (settings.provModels[id]?.length ? settings.provModels[id] : PROVIDERS[id].defaults)) out.push({prov: id, id: m, kind: modelKind(m)});
  return out;
}
async function modelsTab(){
  const all = allCloudModels(), mine = await opfsList();
  const counts = all.reduce((o, m) => (o[m.kind] = (o[m.kind] || 0) + 1, o), {});
  const q = mdlQ.toLowerCase(), list = all.filter(m => (mdlKind === "all" || m.kind === mdlKind) && (!q || m.id.toLowerCase().includes(q))).slice(0, 300);
  const usable = k => ["chat", "code", "reason", "vision"].includes(k);
  const fmtSize = b => b >= 1e9 ? (b / 1e9).toFixed(2) + "GB" : Math.round(b / 1e6) + "MB";
  return `<h3 class="h">모델</h3><p class="sub">${esc(AI())}는 아래의 모든 모델을 하나의 AI처럼 씁니다. 질문마다 알맞은 모델을 고르고(자동), 원하면 특정 모델을 고정할 수 있습니다. 클라우드 모델은 API 키를 넣은 회사의 전체 목록이 자동으로 들어오고, Hugging Face의 GGUF 모델은 Ollama 없이 이 앱 안에서 바로 내려받아 실행합니다.</p>
  <div class="card"><h3>클라우드 모델 <small>${all.length}개 · ${connectedAI().map(id => PROVIDERS[id].name).join(", ") || "API 키 없음"}</small></h3><div class="body">
    ${all.length ? `<div class="seg wrap" id="mdlKinds">${[["all", "전체 " + all.length], ...Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, n]) => [k, (KIND_KO[k] || k) + " " + n])].map(([k, l]) => `<button data-mkind="${k}" aria-pressed="${mdlKind === k}">${esc(l)}</button>`).join("")}</div>
    <input class="search" id="mdlQ" type="search" placeholder="모델 이름 검색 (예: nemotron, qwen, vision)" value="${esc(mdlQ)}">
    <div class="list mlist">${list.map(m => { const pinned = settings.pinModel[m.prov] === m.id; return `<div><span class="t"><b>${esc(m.id)}</b><span class="small">${esc(PROVIDERS[m.prov].name)} · ${esc(KIND_KO[m.kind] || m.kind)}${m.kind === "image" ? " · 렌더링에 사용" : ""}</span></span>
      ${usable(m.kind) ? `<button class="btn${pinned ? " primary" : ""}" data-usemodel="${esc(m.prov)}|${esc(m.id)}">${pinned ? "고정됨" : "이 모델 쓰기"}</button>` : m.kind === "image" && m.prov === "nvidia" ? `<button class="btn" data-imgmodel="${esc(m.id)}">${settings.imageModel === m.id ? "렌더링 모델 ✓" : "렌더링에 쓰기"}</button>` : ""}</div>`; }).join("") || `<p class="empty">찾는 모델이 없습니다.</p>`}</div>
    ${Object.values(settings.pinModel).length ? `<div class="row"><button class="btn" id="unpinAll">고정 모두 풀고 자동 선택으로</button></div>` : ""}` : `<p class="empty">설정 → AI 두뇌에서 NVIDIA(build.nvidia.com)·Hugging Face 등의 무료 API 키를 넣으면 그 회사의 모델 전체가 여기에 들어옵니다.</p><button class="btn primary" data-open="brain">API 키 넣기</button>`}</div></div>
  <div class="card"><h3>Hugging Face 모델을 이 앱에서 실행 <small>GGUF · Ollama 없이</small></h3><div class="body">
    <div class="keyrow"><input id="hfQ" placeholder="모델 검색 (예: qwen3.5, gemma-4, exaone, kanana, llama)" value="${esc(hfQ)}"><button class="btn primary" id="hfGo" ${hfBusy ? "disabled" : ""}>검색</button></div>
    ${hfFiles ? `<div class="row"><button class="btn" id="hfBack">← 검색 결과</button><b>${esc(hfFiles.repo)}</b></div><div class="list mlist">${hfFiles.files.map(f => `<div><span class="t">${esc(f.label)}<span class="small">${fmtSize(f.size)}${f.parts > 1 ? ` · ${f.parts}개로 나뉨` : ""}</span></span>${f.size > 3.6e9 ? `<span class="small">너무 큼</span>` : f.parts === 1 && f.size > 2.1e9 ? `<span class="small">2GB 초과(분할본 필요)</span>` : `<button class="btn primary" data-hfrun="${esc(f.path)}">내려받고 실행</button>`}</div>`).join("") || `<p class="empty">GGUF 파일이 없습니다.</p>`}</div>`
      : hfRes ? `<div class="list mlist">${hfRes.map(r => `<div><span class="t"><b>${esc(r.id)}</b><span class="small">내려받기 ${fmtN(r.downloads || 0)} · ♥ ${fmtN(r.likes || 0)}</span></span><button class="btn" data-hfrepo="${esc(r.id)}">파일 보기</button></div>`).join("") || `<p class="empty">결과가 없습니다.</p>`}</div>` : ""}
    <span class="small">Hugging Face의 무료 모델 중 GGUF 형식이면 무엇이든 검색해서 이 컴퓨터에서 바로 돌립니다(인터넷 없이 재실행 가능). 4GB 그래픽카드에는 1~4B 모델의 Q4 파일을 권합니다. API로 쓰는 Hugging Face 모델(수천 개)은 hf_ 키를 넣으면 위 클라우드 목록에 들어옵니다.</span></div></div>
  <div class="card"><h3>내가 만든 모델 <small>${mine.length}개 · 앱 안에 저장됨</small></h3><div class="body"><div class="list">${mine.map(m => `<div><span class="t"><b>${esc(m.name)}</b><span class="small">${fmtSize(m.size)}</span></span><button class="btn primary" data-opfsrun="${esc(m.name)}">실행</button><button class="btn danger" data-opfsrm="${esc(m.name)}">삭제</button></div>`).join("") || `<p class="empty">학습 탭에서 만든 모델을 등록하면 여기에 저장됩니다.</p>`}</div></div></div>`;
}
async function hfApi(path){ return webGet("https://huggingface.co/api/" + path, "json"); }
/* ---- 학습 (내 모델 만들기) ---- */
let synthCtl = null, synthLog = [], allProg = null, trainOpt = Object.assign({good: true, tools: true, synth: true, topics: ["crypto_spot", "crypto_futures", "us_stocks", "arch", "news"], count: 30, judge: true, ensemble: true, agent: true, base: BASES[0].id, epochs: 3}, ls.get("trainOpt", {}));
trainOpt.topics = trainOpt.topics.filter(t => TOPICS.some(x => x.id === t)); if (!trainOpt.topics.length) trainOpt.topics = ["crypto_spot", "us_stocks", "arch", "news"];
const saveTrainOpt = () => ls.set("trainOpt", trainOpt);
async function trainData(){
  const chatS = samplesFromChats(chats, {onlyGood: trainOpt.good, tools: trainOpt.tools}), syn = await loadSynth();
  return {chatS, syn, all: [...chatS, ...(trainOpt.synth ? syn : [])]};
}
function download(name, text, type = "application/json"){
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text], {type: type + ";charset=utf-8"})); a.download = name;
  document.body.append(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
async function trainTab(){
  const {chatS, syn, all} = await trainData();
  const rated = chats.flatMap(c => c.messages).filter(m => m.rating > 0).length;
  const base = BASES.find(b => b.id === trainOpt.base) || BASES[0];
  const teacher = routeCandidates("general")[0];
  const ck = (k, label) => `<label class="chk"><input type="checkbox" data-topt="${k}"${trainOpt[k] ? " checked" : ""}> ${label}</label>`;
  const ts = teachers(), nanoRunning = synthCtl && synthCtl.nano;
  const cov = await skillCoverage().catch(() => null), allRun = synthCtl && synthCtl.all, running = allRun || nanoRunning;
  const pct = (a, b) => b ? Math.min(100, Math.round(a / b * 100)) : 0;
  const srcAll = fusionSources(), fst = fusionStats(syn), usedN = srcAll.filter(t => fst.used.has(t.model)).length;
  const provs = [...new Set(srcAll.map(t => PROVIDERS[t.id]?.name || t.id))];
  const skillN = cov ? cov.nvTotal + cov.builtin.length : 0, skillDone = cov ? cov.nvDone + cov.builtinDone : 0, allDone = cov && skillDone >= skillN;
  const bar = (label, a, b, id = "") => `<div class="cov-row"><span>${label}</span><div class="bar"><i style="width:${pct(a, b)}%"></i></div><em${id ? ` id="${id}"` : ""}>${a}/${b}</em></div>`;
  const chips = srcAll.slice(0, 18).map(t => `<span class="${fst.used.has(t.model) ? "on" : ""}" title="${esc(t.model)}">${esc(shortModel(t.model))}</span>`).join("") + (srcAll.length > 18 ? `<span class="more">외 ${srcAll.length - 18}개</span>` : "");
  return `<div class="nano-hero"><div class="nano-badge"><span class="logo">${esc([...AI()][0].toUpperCase())}</span><div><b>${esc(AI())} — 하나의 AI 모델</b><span>연결된 모든 AI 모델과 모든 스킬을 융합해 ${esc(AI())} 모델 파일 하나로 만듭니다</span></div></div>
    <div class="fuse"><div class="fuse-in">
      <div class="fuse-box"><b>AI 모델 ${srcAll.length}개</b><span>${srcAll.length ? esc(provs.join(" · ")) : "API 키를 넣으면 그 회사의 모든 모델이 여기에 들어옵니다"}</span>${srcAll.length ? `<div class="fchips">${chips}</div>` : ""}</div>
      <div class="fuse-box"><b>스킬 ${skillN}개</b><span>기본 ${cov?.builtin.length || 0} + NVIDIA ${cov?.nvTotal || 0} · 실제 도구 사용법 포함</span></div></div>
      <div class="fuse-arrow" aria-hidden="true">→</div>
      <div class="fuse-out"><span class="logo">${esc([...AI()][0].toUpperCase())}</span><b>${esc(AI())}</b><span>모델 파일 1개 · ${esc(NANO_MERGE.size)} · 이 앱에서 오프라인 실행</span></div></div>
    <div class="nano-cov">${bar("융합된 모델", usedN, srcAll.length, "covSrc")}${cov ? bar("기본 스킬", cov.builtinDone, cov.builtin.length) + bar("NVIDIA 스킬", cov.nvDone, cov.nvTotal, "covNv") : ""}<span class="small">학습 예시 ${syn.length}개 · 모델 간 비교 쌍(DPO) ${fst.pairs}개</span></div>
    <div class="row wrap">${running ? `<button class="btn" id="nanoStop">멈추기</button><span class="small" id="allProg">${allRun ? (allProg ? `${allProg.done}/${allProg.total} · ${esc(allProg.label || "")}` : "시작하는 중…") : "데이터를 더 만드는 중"} · 다른 대화를 해도 계속되고, 멈춰도 이어서 할 수 있습니다</span>`
      : `${allDone ? `<button class="btn" id="nanoGo" ${ts.length && !synthCtl ? "" : "disabled"}>융합 데이터 100개 더</button>` : `<button class="btn primary" id="nanoAll" ${ts.length && !synthCtl ? "" : "disabled"}>${syn.length ? "이어서 만들기" : esc(AI()) + " 만들기 시작"} (남은 스킬 ${skillN - skillDone}개)</button>`}<button class="btn${allDone ? " primary" : ""}" id="nanoNb">Colab에서 완성하기 (노트북 받기)</button>`}</div>
    <div class="trlog" id="trLog2">${running ? synthLog.slice(-4).map(l => `<div>${esc(l)}</div>`).join("") : ""}</div>
    <ol class="nano-steps"><li class="${allDone ? "done" : running ? "run" : ""}"><b>1. 융합 데이터</b><span>모든 모델이 답하고 순위를 매김 · 모든 스킬</span></li><li><b>2. 융합 학습</b><span>무료 Colab · SFT + DPO</span></li><li class="${settings.myModel ? "done" : ""}"><b>3. 등록</b><span>${settings.myModel ? "등록됨: " + esc(settings.myModel) : "모델 파일을 앱에 넣으면 끝"}</span></li></ol>
    <details class="nano-more"><summary>어떻게 하나로 합치나요?</summary>
      <p>Llama·DeepSeek·Mistral·Qwen·Nemotron처럼 구조가 다른 모델은 가중치를 그대로 더할 수 없습니다. 그래서 FuseChat-3.0과 같은 <b>모델 융합</b>을 씁니다: 같은 질문에 여러 모델이 답하면 심사 모델이 순위를 매기고, ${esc(AI())}는 <b>가장 좋은 답을 따라 배우고(SFT)</b>, <b>좋은 답과 나쁜 답의 차이를 배웁니다(DPO)</b>. 모든 모델이 돌아가며 참여하므로 각 모델의 강점이 한 모델에 모입니다.</p>
      <p>스킬은 스킬마다 핵심 문답과 '원문을 찾아 읽고 답하는 과정'으로 학습하고, 스킬 원문은 앱 안에 모두 들어 있어 ${esc(AI())}가 필요할 때 꺼내 읽습니다.</p>
      <p>몸체: 같은 Qwen2 구조인 ${NANO_MERGE.models.map(m => esc(m.id.split("/")[1]) + `(${esc(m.role)})`).join(" + ")}를 TIES로 먼저 합친 ${esc(NANO_MERGE.name)}입니다.</p>
      <pre class="nano-yml">${esc(mergeYAML())}</pre></details></div>
  <h3 class="h">학습 · 내 모델 만들기</h3><p class="sub">${AI()}와 나눈 대화와 큰 AI가 만든 문제·모범답안으로 작은 오픈모델을 직접 미세조정(LoRA)해, 내 노트북에서 인터넷 없이 도는 나만의 AI를 만듭니다. NVIDIA 스킬(data-designer, tao-finetune-huggingface-model)과 같은 방식입니다.</p>
  <ol class="steps"><li><b>데이터 모으기</b><span>👍 받은 답변</span></li><li><b>합성 데이터</b><span>큰 AI가 문제·답 생성</span></li><li><b>학습</b><span>Colab 무료 GPU</span></li><li><b>내 모델 등록</b><span>Ollama · 내 기기</span></li></ol>
  <div class="card"><h3>① 학습 데이터 <small>총 ${all.length}개</small></h3><div class="body">
    <div class="kpis"><div class="kpi"><label>👍 받은 답</label><span class="v">${rated}</span></div><div class="kpi"><label>대화에서 뽑은 예시</label><span class="v">${chatS.length}</span></div><div class="kpi"><label>합성 예시</label><span class="v">${syn.length}</span></div></div>
    <div class="row wrap">${ck("good", "👍 받은 답만")}${ck("tools", "도구 쓰는 과정까지 가르치기")}${ck("synth", "합성 데이터 포함")}</div>
    <div class="row"><button class="btn primary" id="trDl" ${all.length ? "" : "disabled"}>학습 데이터 내려받기 (nuri-train.jsonl)</button><span class="small">답변 아래 👍로 좋은 답을 표시하세요. 최소 50개, 200개 이상이면 효과가 좋습니다.</span></div></div></div>
  <div class="card"><h3>② 합성 데이터 만들기 <small>선생 AI: ${teacher ? esc((PROVIDERS[teacher.id]?.name || teacher.id) + " · " + shortModel(teacher.model)) : "API 키 필요"}</small></h3><div class="body">
    <div class="topics">${TOPICS.map(t => `<label class="chk"><input type="checkbox" data-topic="${t.id}"${trainOpt.topics.includes(t.id) ? " checked" : ""}> ${esc(t.name)}</label>`).join("")}</div>
    <div class="row wrap"><label class="small">개수 <select class="sel" id="trCount">${[10, 30, 60, 100, 200].map(n => `<option${n === trainOpt.count ? " selected" : ""}>${n}</option>`).join("")}</select></label>${ck("judge", "AI 채점으로 4점 이상만 남기기")}${ck("ensemble", "모든 AI 모델 융합 (가장 좋은 답 + 비교 쌍)")}${ck("agent", "실제 도구 쓰는 과정까지 기록")}</div>
    <div class="row">${synthCtl ? `<button class="btn" id="trStop">멈추기</button>` : `<button class="btn primary" id="trGen" ${teacher ? "" : "disabled"}>만들기</button>`}${syn.length ? `<button class="btn danger" id="trClear">합성 데이터 모두 지우기</button>` : ""}</div>
    <div class="trlog" id="trLog">${synthLog.slice(-6).map(l => `<div>${esc(l)}</div>`).join("")}</div>
    ${syn.length ? `<div class="list">${syn.slice(-8).reverse().map(x => `<div><span class="t">${esc(x.messages[1].content)}</span><span class="small">${esc(TOPICS.find(t => t.id === x.topic)?.name || "")}${x.score ? " · " + x.score + "점" : ""}</span><button class="btn danger" data-synrm="${x.id}">삭제</button></div>`).join("")}</div>` : ""}
    <span class="small">조건(주제·질문자·난이도·말투)을 무작위로 섞어 질문을 만들고, 선생 AI가 모범답안을 쓰고, 다시 채점해 좋은 것만 남깁니다. Qwen·DeepSeek처럼 학습 사용이 허용된 오픈모델이 선생일 때 쓰세요.</span></div></div>
  <div class="card"><h3>③ 학습하기</h3><div class="body">
    <div class="form"><label>바탕 모델<select id="trBase">${BASES.map(b => `<option value="${esc(b.id)}"${b.id === base.id ? " selected" : ""}>${esc(b.name)} — ${esc(b.fit)}</option>`).join("")}</select></label>
      <label>반복 횟수<select id="trEpochs">${[1, 2, 3].map(n => `<option${n === trainOpt.epochs ? " selected" : ""}>${n}</option>`).join("")}</select></label></div>
    <p class="small" style="margin:0">라이선스: ${esc(base.lic)} · 결과 모델 크기 ${esc(base.gguf)}</p>
    <div class="tiles">
      <div class="tile"><div class="hd"><b>Google Colab (추천)</b><span class="tag good">무료 T4 GPU 16GB</span></div><p>노트북 그래픽카드(RTX 3050 4GB)로는 학습이 느리고 메모리가 빠듯해서, 무료 Colab GPU에서 학습하고 결과만 받아 오는 방법을 추천합니다.</p>
        <ol class="small"><li>아래 버튼으로 노트북 파일과 학습 데이터를 받습니다.</li><li><a href="https://colab.research.google.com" target="_blank" rel="noopener">colab.research.google.com</a> → 업로드 → 노트북 파일 선택</li><li>런타임 → 런타임 유형 변경 → <b>T4 GPU</b> → 모두 실행</li><li>데이터 파일을 올리면 10~30분 뒤 .gguf가 내려받아집니다.</li></ol>
        <div class="row"><button class="btn primary" id="trNb">Colab 노트북 받기</button></div></div>
      <div class="tile${base.local ? "" : " dim"}"><div class="hd"><b>내 노트북에서 (RTX 3050)</b><span class="tag">고급</span></div><p>${base.local ? "4GB 그래픽카드용 설정(짧은 길이·작은 배치)으로 만든 스크립트입니다. WSL2 또는 Python 3.11 + NVIDIA 드라이버가 필요합니다." : "이 바탕 모델은 4GB 그래픽카드로 학습하기 어렵습니다. Qwen3.5 0.8B·2B 또는 EXAONE 1.2B를 고르세요."}</p>
        <div class="row"><button class="btn" id="trPy" ${base.local ? "" : "disabled"}>로컬 학습 스크립트 받기</button></div></div></div></div></div>
  <div class="card"><h3>④ 내 모델 등록</h3><div class="body">
    <div class="form"><label>모델 이름<input id="trName" value="${esc(ls.get("myModelName", "gh-nano"))}"></label><label>학습 결과 GGUF 파일 (분할본이면 모두 선택)<input type="file" id="trGguf" accept=".gguf" multiple></label></div>
    <div class="row"><button class="btn primary" id="trLocal">${esc(AI())}에 등록 (앱 안에 저장·실행)</button><button class="btn" id="trOl">Ollama에 등록 (선택)</button></div>
    <span class="small" id="trMsg">다른 프로그램 없이 이 앱 안(브라우저 저장소)에 저장해 그래픽카드(WebGPU)로 돌리고, 다음 실행 때도 자동으로 켭니다. 파일 하나가 2GB를 넘으면 노트북이 만든 분할 파일을 함께 고르세요. Ollama 등록은 원할 때만 쓰세요.</span>
    ${settings.myModel ? `<p class="small">등록된 내 모델: <b>${esc(settings.myModel)}</b></p>` : ""}</div></div>`;
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
  if ((c.mode || "chat") !== mode) setMode(c.mode || "chat");
  input.value = t.text; autoGrow(); updateSend(); input.focus();
  const a = t.text.indexOf("["), b = t.text.indexOf("]", a); if (a >= 0 && b > a) input.setSelectionRange(a, b + 1);
}
/* ---- 스킬 ---- */
function skillsTab(){
  const off = settings.skillsOff || [], mine = settings.skills || [];
  return `<h3 class="h">스킬</h3><p class="sub">스킬은 분야별 전문가의 일하는 방식(지침)과 도구 묶음입니다. 질문 내용에 맞는 스킬이 자동으로 켜지고, '진행 상황'에서 어떤 스킬을 썼는지 보입니다. 나만의 스킬을 만들어 ${AI()}에게 일하는 방식을 가르칠 수 있습니다.</p>
    <div class="card" id="nvCard"><div class="body"><p class="empty">NVIDIA 스킬 목록을 읽는 중…</p></div></div>
    <div class="tiles">${BUILTIN_SKILLS.map(sk => { const on = !off.includes(sk.id); return `<div class="tile${on ? "" : " dim"}"><div class="hd"><b>${esc(sk.icon)} ${esc(sk.name)}</b><button class="btn" data-skoff="${sk.id}">${on ? "켜짐" : "꺼짐"}</button></div>
      <div class="meta">${(sk.tools || []).map(t => `<span class="tag">${esc(TOOLS[t]?.label || t)}</span>`).join("")}</div><details><summary class="small">지침 보기</summary><pre class="skp">${esc(sk.prompt)}</pre></details></div>`; }).join("")}</div>
    <div class="card"><h3>엔비디아·외부 스킬 가져오기 <small>SKILL.md 형식</small></h3><div class="body">
      <div class="keyrow"><input id="skUrl" placeholder="GitHub 주소 또는 NVIDIA 스킬 이름 (예: portfolio-optimization, data-designer)"><button class="btn primary" id="skUrlAdd">가져오기</button></div>
      <label class="small">또는 SKILL.md 파일 <input type="file" id="skFile" accept=".md" multiple></label>
      <span class="small"><a href="https://github.com/NVIDIA/skills/tree/main/skills" target="_blank" rel="noopener">NVIDIA 스킬 목록</a>의 지침을 ${AI()}가 그대로 참고합니다. 단, 대부분은 GPU 서버·전용 프로그램을 다루는 지침이라 ${AI()} 채팅 안에서는 '방법 안내'로만 쓰입니다.</span></div></div>
    <div class="card"><h3>새 스킬 만들기</h3><div class="body"><div class="form" style="grid-template-columns:1fr">
      <label>이름<input id="skName" placeholder="예: 우리 회사 주간보고 양식"></label>
      <label>켜지는 단어 (쉼표로 구분)<input id="skKeys" placeholder="예: 주간보고, 보고서"></label>
      <label>지침 (${AI()}가 이 일을 할 때 따를 방법)<textarea id="skPrompt" placeholder="예: 보고서는 ①요약 3줄 ②진행 현황 표 ③이슈 ④다음 주 계획 순서로 쓴다. 금액은 만원 단위."></textarea></label>
      <label class="chk"><input type="checkbox" id="skAlways"> 모든 대화에서 항상 켜기</label></div>
      <div class="row"><button class="btn primary" id="skAdd">스킬 추가</button></div></div></div>
    <div class="card"><h3>내 스킬 <small>${mine.length}개</small></h3><div class="body"><div class="list">${mine.length ? mine.map(sk => `<div><span class="t"><b>${esc(sk.name)}</b> <span class="small">${sk.always ? "항상" : esc(sk.keys || "")}</span></span><button class="btn" data-sktoggle="${sk.id}">${sk.off ? "꺼짐" : "켜짐"}</button><button class="btn danger" data-skrm="${sk.id}">삭제</button></div>`).join("") : `<p class="empty">아직 없습니다.</p>`}</div></div></div>`;
}
// SKILL.md(NVIDIA·Claude 스킬 형식) → 내 스킬
function importSkill(text, src){
  const fm = text.match(/^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)$/);
  if (!fm) throw new Error("SKILL.md 형식이 아닙니다 (맨 위 --- 머리말 필요)");
  const head = fm[1], body = fm[2].replace(/<!--[\s\S]*?-->/g, "").trim();
  const lines = head.split("\n");
  const field = k => { const i = lines.findIndex(l => l.startsWith(k + ":")); if (i < 0) return ""; let v = lines[i].slice(k.length + 1).trim(); if (/^[>|]-?$/.test(v)){ v = ""; for (let j = i + 1; j < lines.length && /^\s+\S/.test(lines[j]); j++) v += " " + lines[j].trim(); } return v.replace(/\s+/g, " ").replace(/^["']|["']$/g, "").trim(); };
  const name = field("name"); if (!name) throw new Error("스킬 이름(name)이 없습니다");
  const desc = field("description");
  const tags = [...head.matchAll(/^\s+-\s+([\w.-]+)\s*$/gm)].map(x => x[1]).filter(x => x.length > 2).slice(0, 6);
  const STOP = new Set(["data", "model", "models", "skill", "skills", "nvidia", "gpu", "tools", "catalog", "router", "setup", "guide"]);
  const KO = {portfolio: "포트폴리오", optimization: "최적화", finetune: "파인튜닝", finetuning: "파인튜닝", training: "학습", designer: "합성 데이터", dataset: "데이터셋", rag: "문서 검색", forecasting: "예측", cuopt: "최적화", robotics: "로봇", inference: "추론 서버"};
  const words = [...name.split(/[-_]/), ...tags].map(w => w.toLowerCase()).filter(w => w.length > 2 && !STOP.has(w));
  const keys = [...new Set([name, ...words, ...words.map(w => KO[w]).filter(Boolean)])].join(", ");
  const prompt = `(가져온 스킬: ${name}${desc ? " — " + desc : ""})\n${body}`.slice(0, 8000);
  settings.skills = (settings.skills || []).filter(x => x.name !== name);
  settings.skills.push({id: uid(), name, keys, prompt, src, imported: true});
  saveSettings(); toast(`스킬 '${name}'을 가져왔습니다`);
}
/* ---- NVIDIA 공식 스킬 라이브러리 ---- */
let nvQ = "", nvGroup = "all";
async function nvListHTML(){
  const idx = await nvIndex();
  let list;
  if (nvQ.trim()) list = (await nvSearch(nvQ, 40)).map(x => idx.skills.find(s => s.n === x.name)).filter(Boolean);
  else list = idx.skills;
  if (nvGroup !== "all") list = list.filter(s => s.g === nvGroup);
  return list.slice(0, 60).map(s => `<div><span class="t"><b>${esc(s.n)}</b><span class="small">${esc(GROUP_KO[s.g] || s.g)} · ${esc(s.d.slice(0, 140))}</span></span><button class="btn" data-nvview="${esc(s.n)}">지침 보기</button></div>`).join("") + (list.length > 60 ? `<p class="small">… ${list.length - 60}개 더 (검색으로 좁히세요)</p>` : "") || `<p class="empty">맞는 스킬이 없습니다.</p>`;
}
async function nvCard(){
  const idx = await nvIndex();
  const groups = idx.skills.reduce((o, s) => (o[s.g] = (o[s.g] || 0) + 1, o), {});
  const ws = current?.workspace || ls.get("lastWs", "");
  return `<h3>NVIDIA 공식 스킬 <small>${idx.count}개 · 저장소 파일 ${fmtN(idx.files || 0)}개 전부 내장 · NVIDIA/skills ${esc(idx.commit)}</small></h3><div class="body">
    <div class="row wrap"><label class="chk"><input type="checkbox" data-nvopt="nvSkills"${settings.nvSkills !== false ? " checked" : ""}> 사용 (필요할 때 ${esc(AI())}가 찾아 읽음)</label><label class="chk"><input type="checkbox" data-nvopt="nvAuto"${settings.nvAuto !== false ? " checked" : ""}> 질문과 딱 맞으면 자동 적용</label></div>
    <div class="seg wrap" id="nvGroups">${[["all", "전체 " + idx.count], ...Object.entries(groups).sort((a, b) => b[1] - a[1]).map(([g, n]) => [g, (GROUP_KO[g] || g) + " " + n])].map(([g, l]) => `<button data-nvgroup="${esc(g)}" aria-pressed="${nvGroup === g}">${esc(l)}</button>`).join("")}</div>
    <input class="search" id="nvQ" type="search" placeholder="스킬 검색 (예: 젯슨, 파인튜닝, cuopt, 의료영상, 음성인식, RAG)" value="${esc(nvQ)}">
    <div class="list mlist" id="nvList">${await nvListHTML()}</div>
    <pre class="skp" id="nvView" hidden></pre>
    <div class="row wrap"><button class="btn primary" id="nvInstall" ${LAUNCHER.on && ws ? "" : "disabled"}>작업 폴더에 전체 설치 (.claude/skills + 저장소 전체)</button><span class="small">${LAUNCHER.on ? (ws ? `작업 폴더: ${esc(ws)} · <code>npx skills add NVIDIA/skills</code>와 같은 결과라 Claude Code·Codex에서도 바로 쓰고, 코드 모드에서 스크립트를 실행할 수 있습니다.` : "코드 모드에서 작업 폴더를 먼저 여세요.") : "GHNano.exe로 실행해야 설치할 수 있습니다."}</span></div>
    <span class="small">라이선스: Apache-2.0 / CC-BY-4.0 (NVIDIA). 대부분 NVIDIA GPU·서버용 작업 지침이라, 채팅에서는 절차 안내로, 코드 모드에서는 실제 실행에 쓰입니다.</span></div>`;
}
/* ---- 기억 ---- */
function memTab(){
  const mem = settings.memory || [];
  return `<h3 class="h">기억</h3><p class="sub">대화 중에 "기억해줘"라고 하거나 ${AI()}가 앞으로 도움이 될 정보라고 판단하면 여기에 저장되고, 이후 모든 대화에서 참고합니다. 이 컴퓨터에만 저장됩니다.</p>
    <div class="card"><div class="body"><div class="keyrow"><input id="memIn" placeholder="직접 추가: 예) 나는 경기도에서 건축사무소를 운영한다"><button class="btn primary" id="memAdd">추가</button></div></div></div>
    <div class="card"><h3>기억한 것 <small>${mem.length}개</small></h3><div class="body"><div class="list">${mem.length ? mem.map((m, k) => `<div><span class="t">${esc(m.text)}</span><span class="small">${new Date(m.t).toLocaleDateString("ko-KR")}</span><button class="btn danger" data-memrm="${k}">삭제</button></div>`).reverse().join("") : `<p class="empty">아직 없습니다.</p>`}</div></div></div>`;
}
bus.addEventListener("engine", () => { renderModelBtn(); if ($("#sheet").open && (sheetTab === "brain" || sheetTab === "local")) renderSheet(); if (current && !current.messages.length) render(); });
function brainTab(){
  const conn = connectedAI(), exeNote = LAUNCHER.on ? "" : `<p class="err small">웹 버전에서는 외부 AI 연결이 막힐 수 있습니다. GHNano.exe로 실행하세요.</p>`;
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
      <label class="small">모델<select class="sel" id="ol-model">${opts(OL_MODELS, settings.olModel)}</select></label><div class="row"><button class="btn primary" data-olpull="1">이 모델 받기</button><button class="btn" id="ol-list">받은 모델 보기</button><button class="btn" data-btest="ollama">연결 테스트</button></div></div>
    <div class="tile${settings.brain === "local" ? " active" : ""}"><div class="hd"><b>내 기기 AI</b><span class="pill"><i class="dot ${eng.w ? "ok" : "bad"}"></i>${eng.w ? "실행 중" : "모델 없음"}</span></div><p>인터넷 없이 이 컴퓨터에서 도는 소형 모델. 현재: ${esc(eng.loaded ? eng.loaded.name : "없음")}</p><div class="row"><button class="btn" data-open="local">내 기기 모델 고르기</button></div></div>
  </div>
  <div class="card"><h3>${AI()}는 어떻게 배우나요?</h3><div class="body"><p class="small" style="margin:0">무료 API(NVIDIA 등)는 이미 학습된 모델을 '빌려 쓰는' 방식이라 모델 자체를 다시 학습시킬 수는 없습니다. 대신 ${AI()}는 <b>스킬</b>(분야별 일하는 방식), <b>기억</b>(나에 대한 정보), <b>내 지식</b>(올린 문서), <b>맞춤 지침</b>으로 매번 그것을 참고해 답하므로, 쓰면 쓸수록 나에게 맞춰집니다. 모델 자체를 미세조정하려면 GPU와 별도 학습 환경(NVIDIA NeMo, Unsloth 등)이 필요합니다.</p></div></div>`;
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
  return `<h3 class="h">내 지식</h3><p class="sub">문서를 올려 두면 "내 문서에서 … 찾아줘"처럼 물었을 때 ${AI()}가 관련 부분을 찾아 답합니다. 문서는 이 컴퓨터에만 저장됩니다.</p>
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
    <p class="small">${AI()} · 오픈소스 모델과 llama.cpp(wllama)로 동작합니다. ${LAUNCHER.on ? "실행기(GHNano.exe) 연결됨." : "웹 버전으로 실행 중입니다."}</p>`;
}
$("#sheetBody").addEventListener("change", async e => {
  const t = e.target;
  if (t.dataset.nvopt){ settings[t.dataset.nvopt] = t.checked; saveSettings(); }
  if (t.dataset.topt){ trainOpt[t.dataset.topt] = t.checked; saveTrainOpt(); if (t.dataset.topt !== "judge") renderSheet(); }
  if (t.dataset.topic){ const o = new Set(trainOpt.topics); t.checked ? o.add(t.dataset.topic) : o.delete(t.dataset.topic); trainOpt.topics = [...o]; saveTrainOpt(); }
  if (t.id === "trCount"){ trainOpt.count = +t.value; saveTrainOpt(); }
  if (t.id === "trBase"){ trainOpt.base = t.value; saveTrainOpt(); renderSheet(); }
  if (t.id === "trEpochs"){ trainOpt.epochs = +t.value; saveTrainOpt(); }
  if (t.id === "trName") ls.set("myModelName", t.value.trim() || "gh-nano");
  if (t.id === "skFile" && t.files.length){ for (const f of t.files){ try { importSkill(await f.text(), f.name); } catch(err){ toast(err.message); } } renderSheet(); }
  if (t.dataset.pin){ if (t.value) settings.pinModel[t.dataset.pin] = t.value; else delete settings.pinModel[t.dataset.pin]; saveSettings(); }
  if (t.id === "img-model"){ settings.imageModel = t.value; saveSettings(); }
  if (t.id === "ol-model"){ settings.olModel = t.value; saveSettings(); }
  if (t.id === "s-device"){ settings.device = t.value; saveSettings(); }
  if (t.id === "s-ctx"){ settings.ctx = +t.value; saveSettings(); }
  if (t.id === "ggufFile" && t.files.length){ const files = [...t.files].sort((a, b) => a.name.localeCompare(b.name)); settings.brain = "local"; await loadModel({kind: "file", name: files[0].name.replace(/(-\d{5}-of-\d{5})?\.gguf$/i, ""), files}); }
  if (t.id === "docFiles"){ let n = 0; for (const f of t.files){ try { if (await addDoc(f.name, await readTextFile(f))) n++; } catch(err){ toast(err.message); } } if (n) toast(`문서 ${n}개를 추가했습니다`); renderSheet(); }
});
let nvT = 0;
$("#sheetBody").addEventListener("input", e => {
  if (e.target.id === "nvQ"){ nvQ = e.target.value; clearTimeout(nvT); nvT = setTimeout(async () => { const L = $("#nvList"); if (L) L.innerHTML = await nvListHTML(); }, 200); }
  if (e.target.id === "mdlQ"){ mdlQ = e.target.value; clearTimeout(nvT); nvT = setTimeout(async () => { const pos = e.target.selectionStart; await renderSheet(); const q = $("#mdlQ"); if (q){ q.focus(); q.setSelectionRange(pos, pos); } }, 250); }
});
$("#sheetBody").addEventListener("keydown", e => { if (e.key !== "Enter" || e.isComposing) return; if (e.target.id === "apiKey") $("#apiAdd").click(); if (e.target.id === "memIn") $("#memAdd").click(); if (e.target.id === "hfQ") $("#hfGo").click(); if (e.target.id === "aiName") $("#aiNameSave").click(); });
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
  const th = t.closest("#themeSeg [data-theme]"); if (th){ settings.theme = th.dataset.theme; saveSettings(); applyTheme(); $$("#themeSeg [data-theme]").forEach(b => b.setAttribute("aria-pressed", b === th)); return; }
  const ng = t.closest("[data-nvgroup]"); if (ng){ nvGroup = ng.dataset.nvgroup; $$("#nvGroups [data-nvgroup]").forEach(b => b.setAttribute("aria-pressed", b.dataset.nvgroup === nvGroup)); $("#nvList").innerHTML = await nvListHTML(); return; }
  if (t.dataset.nvview){ const v = $("#nvView"); try { const sk = await nvSkill(t.dataset.nvview); v.textContent = `${sk.name} · 파일 ${Object.keys(sk.files).length + Object.keys(sk.bin || {}).length}개\n\n` + sk.files["SKILL.md"]; v.hidden = false; v.scrollIntoView({block: "nearest"}); } catch(err){ toast(err.message); } return; }
  if (t.id === "nvInstall"){
    const ws = current?.workspace || ls.get("lastWs", ""); if (!ws) return;
    t.disabled = true;
    try {
      await codeCall("open", {path: ws});
      const idx = await nvIndex(); let nf = 0, i = 0;
      for (const s of idx.skills){ i++; t.textContent = `설치 중 ${i}/${idx.count}`; nf += await installSkill(await nvSkill(s.n), `.claude/skills/${s.n}`); }
      t.textContent = "저장소 나머지 파일 설치 중…"; nf += await installSkill(await nvSkill("_repo"), ".claude/nvidia-skills-repo");
      toast(`NVIDIA 스킬 ${idx.count}개 + 저장소 파일, 모두 ${nf}개 파일을 설치했습니다`); t.textContent = "설치 완료 ✓";
    } catch(err){ toast("설치 실패: " + err.message); t.textContent = "다시 설치"; t.disabled = false; }
  }
  const mk = t.closest("[data-mkind]"); if (mk){ mdlKind = mk.dataset.mkind; renderSheet(); return; }
  if (t.dataset.usemodel){ const [prov, id] = t.dataset.usemodel.split("|"); if (settings.pinModel[prov] === id){ delete settings.pinModel[prov]; settings.brain = "auto"; } else { settings.pinModel[prov] = id; settings.brain = prov; } saveSettings(); renderModelBtn(); toast(settings.brain === "auto" ? AI() + " 자동 선택으로 돌아갑니다" : shortModel(id) + " 모델로 답합니다"); renderSheet(); }
  if (t.dataset.imgmodel){ settings.imageModel = t.dataset.imgmodel; saveSettings(); toast("렌더링 모델: " + shortModel(t.dataset.imgmodel)); renderSheet(); }
  if (t.id === "unpinAll"){ settings.pinModel = {}; settings.brain = "auto"; saveSettings(); renderModelBtn(); renderSheet(); }
  if (t.id === "hfGo"){ hfQ = $("#hfQ").value.trim(); if (!hfQ) return; hfBusy = true; hfFiles = null; t.disabled = true;
    try { hfRes = await hfApi(`models?search=${encodeURIComponent(hfQ)}&filter=gguf&sort=downloads&direction=-1&limit=25`); } catch(err){ toast("Hugging Face 검색 실패: " + err.message); hfRes = []; } finally { hfBusy = false; renderSheet(); } }
  if (t.dataset.hfrepo || t.id === "hfBack"){
    if (t.id === "hfBack"){ hfFiles = null; renderSheet(); return; }
    const repo = t.dataset.hfrepo; t.disabled = true;
    try {
      const tree = await hfApi(`models/${repo}/tree/main?recursive=true`);
      const ggufs = tree.filter(f => f.type === "file" && /\.gguf$/i.test(f.path) && !/mmproj/i.test(f.path)).map(f => ({path: f.path, size: f.lfs?.size || f.size || 0}));
      const groups = new Map();
      for (const f of ggufs){ const m = f.path.match(/^(.*)-(\d{5})-of-(\d{5})\.gguf$/i); const key = m ? m[1] : f.path; const g = groups.get(key) || {path: m ? `${m[1]}-00001-of-${m[3]}.gguf` : f.path, label: (m ? m[1] : f.path.replace(/\.gguf$/i, "")).split("/").pop(), size: 0, parts: 0}; g.size += f.size; g.parts++; groups.set(key, g); }
      hfFiles = {repo, files: [...groups.values()].sort((a, b) => a.size - b.size)};
    } catch(err){ toast("파일 목록을 받지 못했습니다: " + err.message); }
    renderSheet();
  }
  if (t.dataset.hfrun){ const file = t.dataset.hfrun, repo = hfFiles.repo; $("#sheet").close(); settings.brain = "local"; saveSettings(); toast("내려받는 중… 입력창 모델 버튼에 진행률이 보입니다"); await loadModel({kind: "hf", id: repo + "/" + file, name: repo.split("/").pop() + " · " + file.split("/").pop().replace(/(-\d{5}-of-\d{5})?\.gguf$/i, ""), repo, file}); if (eng.error) toast(eng.error); }
  if (t.dataset.opfsrun){ $("#sheet").close(); settings.brain = "local"; saveSettings(); await loadModel({kind: "opfs", dir: t.dataset.opfsrun, name: t.dataset.opfsrun}); toast(eng.w ? t.dataset.opfsrun + " 모델로 대화합니다" : eng.error); }
  if (t.dataset.opfsrm){ if (t.dataset.c !== "1"){ t.dataset.c = "1"; t.textContent = "정말 삭제"; return; } await opfsRemove(t.dataset.opfsrm); renderSheet(); }
  if (t.id === "trDl"){ const {all} = await trainData(); download("nuri-train.jsonl", toJSONL(all), "application/jsonl"); toast(`학습 예시 ${all.length}개를 내보냈습니다`); }
  if (t.id === "nanoNb"){
    const name = ls.get("myModelName", "gh-nano"), {all, syn} = await trainData();
    const sources = [...fusionStats(syn).used].sort((a, b) => b[1] - a[1]), dpo = toDPOJSONL(syn), pairs = dpo.trim() ? dpo.trim().split("\n").length : 0;
    download("gh_nano_fusion_colab.ipynb", nanoNotebookJSON({name, epochs: trainOpt.epochs, sources}));
    if (all.length) setTimeout(() => download("nuri-train.jsonl", toJSONL(all), "application/jsonl"), 400);
    if (pairs) setTimeout(() => download("nuri-dpo.jsonl", dpo, "application/jsonl"), 800);
    toast(all.length ? `노트북 + 학습 예시 ${all.length}개 + 비교 쌍 ${pairs}개를 받았습니다. Colab에서 모두 실행하세요` : "노트북을 받았습니다. 먼저 'GH Nano 만들기 시작'으로 데이터를 만드세요");
  }
  if (t.id === "trNb" || t.id === "trPy"){
    const b = BASES.find(x => x.id === trainOpt.base) || BASES[0], name = ls.get("myModelName", "gh-nano"), local = t.id === "trPy";
    const o = {base: b.id, baseName: b.name, lic: b.lic, epochs: trainOpt.epochs, name, maxLen: local ? 1024 : 2048, batch: local ? 1 : 2, accum: local ? 8 : 4};
    if (local) download("nuri_train_local.py", localScript(o), "text/x-python"); else download("nuri_train_colab.ipynb", notebookJSON(o));
    const {all} = await trainData(); if (all.length) setTimeout(() => download("nuri-train.jsonl", toJSONL(all), "application/jsonl"), 400);
    toast(all.length ? "학습 파일과 데이터를 내려받았습니다" : "학습 파일을 받았습니다. 학습 데이터가 아직 없습니다");
  }
  if (t.id === "trGen"){
    synthLog = ["시작합니다…"]; synthCtl = new AbortController(); renderSheet();
    const log = x => { synthLog.push(x); const L = $("#trLog"); if (L) L.innerHTML = synthLog.slice(-6).map(l => `<div>${esc(l)}</div>`).join(""); };
    generateSynth({topics: trainOpt.topics, count: trainOpt.count, judge: trainOpt.judge, ensemble: trainOpt.ensemble, agent: trainOpt.agent, signal: synthCtl.signal,
      onEvent: ev => { if (ev.kind === "log") log(ev.text); if (ev.kind === "sample") log(`✓ ${ev.made}/${ev.count} 저장`); }})
      .then(n => { toast(`합성 예시 ${n}개를 만들었습니다`); }).catch(err => { if (!synthCtl?.signal.aborted) toast(err.message); log("멈춤: " + (err.message || "")); })
      .finally(() => { synthCtl = null; if ($("#sheet").open && sheetTab === "train") renderSheet(); });
  }
  if (t.id === "trStop" || t.id === "nanoStop"){ synthCtl?.abort(); }
  if (t.id === "nanoAll"){
    synthLog = ["모든 스킬을 학습 데이터에 넣기 시작합니다…"]; allProg = null; synthCtl = new AbortController(); synthCtl.all = true; renderSheet();
    const log = x => { synthLog.push(x); if (synthLog.length > 200) synthLog.splice(0, 100); const L = $("#trLog2"); if (L) L.innerHTML = synthLog.slice(-4).map(l => `<div>${esc(l)}</div>`).join(""); };
    generateAllSkills({signal: synthCtl.signal, judge: true, ensemble: true, agent: true,
      onEvent: ev => { if (ev.kind === "log") log(ev.text); if (ev.kind === "progress"){ allProg = ev; const P = $("#allProg"); if (P) P.textContent = `${ev.done}/${ev.total} · ${ev.label} · 멈춰도 이어서 할 수 있습니다`; } }})
      .then(n => { if (!synthCtl?.signal.aborted) toast(`스킬 학습 데이터 ${n}개를 만들었습니다. 이제 'Colab에서 완성하기'를 누르세요`); })
      .catch(err => { if (!synthCtl?.signal.aborted) toast(err.message); log("멈춤: " + (err.message || "")); })
      .finally(() => { synthCtl = null; allProg = null; if ($("#sheet").open && sheetTab === "train") renderSheet(); });
  }
  if (t.id === "nanoGo"){
    synthLog = ["GH Nano 데이터 증류를 시작합니다…"]; synthCtl = new AbortController(); synthCtl.nano = true; renderSheet();
    const log = x => { synthLog.push(x); for (const id of ["#trLog", "#trLog2"]){ const L = $(id); if (L) L.innerHTML = synthLog.slice(id === "#trLog2" ? -4 : -6).map(l => `<div>${esc(l)}</div>`).join(""); } };
    generateSynth({topics: TOPICS.map(x => x.id), count: 100, judge: true, ensemble: true, agent: true, signal: synthCtl.signal,
      onEvent: ev => { if (ev.kind === "log") log(ev.text); if (ev.kind === "sample") log(`✓ ${ev.made}/${ev.count} 저장 (${ev.sample.kind})`); }})
      .then(n => { toast(`${AI()} 학습 데이터 ${n}개를 만들었습니다. 이제 'Colab에서 완성하기'를 누르세요`); })
      .catch(err => { if (!synthCtl?.signal.aborted) toast(err.message); log("멈춤: " + (err.message || "")); })
      .finally(() => { synthCtl = null; if ($("#sheet").open && sheetTab === "train") renderSheet(); });
  }
  if (t.id === "trClear"){ if (t.dataset.c !== "1"){ t.dataset.c = "1"; t.textContent = "정말 모두 지우기"; return; } await clearSynth(); renderSheet(); }
  if (t.dataset.synrm){ await removeSynth(t.dataset.synrm); renderSheet(); }
  if (t.id === "trOl" || t.id === "trLocal"){
    const fs = [...$("#trGguf").files].sort((a, b) => a.name.localeCompare(b.name)), f = fs[0]; if (!f){ toast("학습 결과 .gguf 파일을 먼저 고르세요"); return; }
    const name = ($("#trName").value.trim() || "gh-nano").toLowerCase().replace(/[^a-z0-9._:-]+/g, "-");
    if (t.id === "trLocal"){
      if (fs.some(x => x.size > 2.1e9)){ toast("한 파일이 2GB를 넘습니다. 노트북의 '나눠 저장' 단계로 만든 분할 파일들을 함께 고르세요"); return; }
      t.disabled = true;
      try { await opfsSave(name, fs, ph => $("#trMsg").textContent = ph); }
      catch(err){ $("#trMsg").textContent = "앱 저장소에 저장하지 못했습니다: " + err.message; t.disabled = false; return; }
      $("#sheet").close(); settings.brain = "local"; saveSettings(); await loadModel({kind: "opfs", dir: name, name});
      if (eng.w){ settings.myModel = name; settings.autoload = true; saveSettings(); toast(`등록 완료! 이제 내가 학습한 ${name} 모델이 답합니다 (다음 실행 때도 자동으로 켜짐)`); } else toast(eng.error || "불러오기 실패");
      return;
    }
    t.disabled = true;
    try { await ollamaImportGGUF(f, name, ph => $("#trMsg").textContent = ph); settings.olModel = name; settings.olOk = true; settings.brain = "ollama"; settings.myModel = name; saveSettings(); toast("등록 완료! 이제 내 모델(" + name + ")이 답합니다"); renderSheet(); }
    catch(err){ $("#trMsg").textContent = (err instanceof TypeError ? "Ollama에 연결하지 못했습니다. Ollama 앱을 켜고 GHNano.exe로 실행하세요." : err.message) + " · 직접 하려면 명령창에서: ollama create " + name + " -f Modelfile"; }
    finally { t.disabled = false; }
  }
  if (t.dataset.olpull){
    const sel = $("#ol-model"), model = sel.value; t.disabled = true; const lab = t.textContent;
    try { await ollamaPull(model, p => { t.textContent = p.total ? `받는 중 ${Math.round((p.completed || 0) / p.total * 100)}%` : (p.status || "받는 중").slice(0, 18); }); settings.olModel = model; settings.olOk = true; saveSettings(); toast("받기 완료: " + model); renderSheet(); }
    catch(err){ toast(err instanceof TypeError ? (LAUNCHER.on ? "Ollama에 연결하지 못했습니다. Ollama 앱을 켜세요" : "GHNano.exe로 실행해야 연결됩니다") : err.message); }
    finally { t.disabled = false; t.textContent = lab; }
  }
  if (t.id === "skUrlAdd"){
    let u = $("#skUrl").value.trim(); if (!u) return;
    const m = u.match(/^https:\/\/github\.com\/([^/]+)\/([^/]+)\/(?:tree|blob)\/([^/]+)\/(.+?)(?:\/SKILL\.md)?\/?$/);
    if (m) u = `https://raw.githubusercontent.com/${m[1]}/${m[2]}/${m[3]}/${m[4]}/SKILL.md`;
    else if (/^[\w.-]+$/.test(u)) u = `https://raw.githubusercontent.com/NVIDIA/skills/main/skills/${u}/SKILL.md`;
    t.disabled = true;
    try { importSkill(await webGet(u), u); renderSheet(); } catch(err){ toast("가져오지 못했습니다: " + err.message); } finally { t.disabled = false; }
  }
  if (t.id === "memAdd"){ const v = $("#memIn").value.trim(); if (v){ (settings.memory ||= []).push({text: v.slice(0, 300), t: Date.now()}); saveSettings(); renderSheet(); } }
  if (t.dataset.memrm){ settings.memory.splice(+t.dataset.memrm, 1); saveSettings(); renderSheet(); }
  const ld = t.closest("[data-load]"); if (ld){ const c = CATALOG.find(x => x.id === ld.dataset.load); settings.brain = "local"; saveSettings(); loadModel({kind: "hf", id: c.id, name: c.name, repo: c.repo, quant: c.quant}); }
  if (t.id === "unload") unloadModel();
  if (t.id === "loadUrl"){ const url = $("#ggufUrl").value.trim(); if (!/^https?:\/\/.+\.gguf(\?.*)?$/i.test(url)){ toast(".gguf로 끝나는 주소를 넣으세요"); return; } settings.brain = "local"; loadModel({kind: "url", name: decodeURIComponent(url.split("/").pop().split("?")[0]).replace(/\.gguf$/i, ""), url}); }
  if (t.id === "aiNameSave"){ settings.aiName = $("#aiName").value.trim() || "GH Nano"; saveSettings(); applyBrand(); setMode(mode, true); renderModelBtn(); toast("이제 " + AI() + "입니다"); }
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
    } catch(err){ toast(err instanceof TypeError ? (LAUNCHER.on ? "연결 실패" : "GHNano.exe로 실행해야 연결됩니다") : err.message); }
    finally { t.disabled = false; }
  }
});

/* ============ 시작 ============ */
(async () => {
  await detectLauncher();
  chats = (await idb.all("chat:")).map(c => ({...c, mode: c.mode || "chat"}));
  await loadDocs();
  applyTheme(); applyBrand(); setMode(mode, true); newChat(); renderList(); renderModelBtn(); syncSideBtn(); updateSend();
  refreshCache();
  if (settings.autoload && settings.last && settings.brain === "local" && !window.__nuriNoAutoload) loadModel(settings.last);
})();

// 서비스 워커: 오프라인 실행 + 멀티스레드용 격리 헤더 + 업데이트 시 새로고침
if ("serviceWorker" in navigator && /^https?:$/.test(location.protocol) && !window.__nuriNoSW){
  const hadController = !!navigator.serviceWorker.controller;
  navigator.serviceWorker.register("./sw.js", {updateViaCache: "none"}).then(reg => {
    const flag = "nuri:coi-reload";
    const maybeReload = () => { if (!self.crossOriginIsolated && !sessionStorage.getItem(flag) && !eng.loading && !runs.size){ sessionStorage.setItem(flag, "1"); location.reload(); } };
    if (navigator.serviceWorker.controller) maybeReload();
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (hadController && !sessionStorage.getItem("nuri:sw-updated") && !eng.loading && !runs.size){ sessionStorage.setItem("nuri:sw-updated", "1"); location.reload(); }
      else maybeReload();
    });
    reg.update().catch(() => {});
  }).catch(() => {});
}
// 실행 중 오류를 숨기지 않고 알려 준다 (원인을 알려 주시면 고칠 수 있게)
addEventListener("error", e => { if (e.message && !/ResizeObserver/.test(e.message)) toast("오류: " + e.message.slice(0, 120)); });
addEventListener("unhandledrejection", e => { const m = String(e.reason?.message || e.reason || ""); if (m && !/abort/i.test(m)) toast("오류: " + m.slice(0, 120)); });
window.__nuri = {get chats(){ return chats; }, get current(){ return current; }, settings, eng, LAUNCHER, openArtifact, get trade(){ return trade; }};
