// 'AI 모델' 창 — 키 넣기 · 여러 모델 등록 · 기능별/에이전트별 배정 · 대체 순서 · 모델 테스트
import { $, api, busy, esc, toast } from "./core.js";

let D = null, st = null;
const PNAME = { claude: "Claude", nvidia: "NVIDIA", gemini: "Gemini" };
const short = (r) => {
  const [p, m] = r.split(/:(.*)/s);
  if (p === "nvidia" && (m === "auto" || m === "auto-fast")) {
    const pick = D?.auto?.[m === "auto" ? "nvidia" : "nvidia_fast"];
    return `NVIDIA · 자동${m === "auto-fast" ? " (가벼운)" : ""}${pick ? ` → ${pick}` : ""}`;
  }
  return `${PNAME[p] || p} · ${m === "auto" ? "자동" : m}`;
};
const isDead = (r) => !!D?.dead?.[r];

export function initAiModels() {
  document.body.insertAdjacentHTML("beforeend", `<div class="modal-bg" id="ai-modal" hidden><div class="modal ai-modal">
    <div class="ph"><span class="t">AI 모델 설정</span><span class="muted" id="aim-primary"></span><div class="grow"></div><button class="flat sm" id="aim-close">닫기 ✕</button></div>
    <div class="pb" id="aim-body"><div class="muted">불러오는 중…</div></div></div></div>`);
  $("#aim-close").onclick = close;
  $("#ai-modal").onclick = (e) => { if (e.target.id === "ai-modal") close(); };
  $("#ai-modal").addEventListener("click", onClick);
  document.addEventListener("click", (e) => { if (e.target.closest("[data-open-ai]")) { e.preventDefault(); openAiModels(); } });
}

function close() { $("#ai-modal").hidden = true; }

export async function openAiModels() {
  $("#ai-modal").hidden = false;
  D = await api("/api/ai");
  st = { models: [...D.models], default: D.default, fallback: [...D.fallback], features: { ...D.features }, roles: { ...D.roles } };
  render();
  if (D.keys.nvidia && !D.auto?.nvidia) loadCatalog("nvidia").catch(() => {});   // 이 키로 쓸 수 있는 모델로 추천·자동 선택 표시
}

async function loadCatalog(prov, refresh = false) {
  const r = await api(`/api/ai/catalog?provider=${prov}${refresh ? "&refresh=true" : ""}`);
  if ($("#ai-modal").hidden) return r;
  if (prov === "nvidia") {
    D.suggest.nvidia = r.suggest || D.suggest.nvidia;
    D.auto = r.auto || D.auto;
    D.dead = Object.fromEntries((r.dead || []).map((m) => [`nvidia:${m}`, D.dead?.[`nvidia:${m}`] || {}]));
  }
  collect(); render();
  $("#aim-dl").innerHTML = r.models.map((m) => `<option value="${esc(m)}">`).join("");
  return r;
}

function dropDead() {
  collect();
  st.models = st.models.filter((r) => !isDead(r));
  st.fallback = st.fallback.filter((r) => !isDead(r));
  if (isDead(st.default)) st.default = "";
  for (const k of ["features", "roles"]) for (const [a, b] of Object.entries(st[k])) if (isDead(b)) delete st[k][a];
  render();
  toast("종료된 모델을 뺐습니다", "'모델 배정 저장'을 눌러야 저장됩니다");
}

function opts(sel, blank = "기본 모델 따름") {
  return `<option value="">${blank}</option>` + st.models.map((r) => `<option value="${esc(r)}" ${r === sel ? "selected" : ""} ${D.keys[r.split(":")[0]] ? "" : "disabled"}>${esc(short(r))}${D.keys[r.split(":")[0]] ? "" : " (키 없음)"}${isDead(r) ? " (종료됨 → 자동 대체)" : ""}</option>`).join("");
}

function render() {
  $("#aim-primary").textContent = D.primary ? ` · 지금 기본: ${short(D.primary)}${isDead(D.primary) ? " (종료됨 → 자동 대체)" : ""}` : " · AI 키 없음 (규칙 분석)";
  const keyRow = (p, name, hint) => `<div class="aim-key"><b>${PNAME[p]}</b><span class="ai-chip ${D.keys[p] ? "up" : "muted"}">${D.keys[p] ? "연결됨" : "키 없음"}</span>
    <input type="password" data-key="${name}" placeholder="${hint}" autocomplete="off"><span class="muted" style="font-size:11px">${p === "nvidia" ? "build.nvidia.com → Get API Key (nvapi-…)" : p === "gemini" ? "aistudio.google.com/apikey" : "console.anthropic.com (유료)"}</span></div>`;
  const sugg = Object.values(D.suggest).flat().filter((r) => !st.models.includes(r) && !isDead(r));
  const used = [...new Set([...st.models, st.default, ...st.fallback, ...Object.values(st.features), ...Object.values(st.roles)])].filter(isDead);
  $("#aim-body").innerHTML = `${used.length ? `<div class="aim-warn">⚠ NVIDIA 에서 종료된 모델 ${used.length}개가 등록돼 있습니다 (${used.map((r) => esc(r.split(":").slice(1).join(":"))).join(", ")}).
      지금은 자동으로 다른 모델이 대신 답합니다. <button class="sm" id="aim-dropdead">종료된 모델 모두 빼기</button></div>` : ""}
    <div class="aim-sec"><div class="tm-sec">1. API 키 <span class="muted">(여기서 넣으면 바로 적용되고 settings.txt 에도 저장됩니다. 지우려면 - 입력)</span></div>
      ${keyRow("nvidia", "nvidia", "nvapi-...")}${keyRow("gemini", "gemini", "AIza...")}${keyRow("claude", "anthropic", "sk-ant-...")}
      <button class="sm" id="aim-savekeys">키 저장</button></div>
    <div class="aim-sec"><div class="tm-sec">2. 내 모델 목록 <span class="muted">(공급자:모델 이름 · 여러 개 등록해서 아래에서 골라 씀)</span></div>
      <div class="chips" id="aim-models">${st.models.map((r, i) => `<span class="aim-chip ${D.keys[r.split(":")[0]] ? "" : "off"} ${isDead(r) ? "dead" : ""}" title="${isDead(r) ? "NVIDIA 에서 종료된 모델 — 다른 모델이 자동으로 대신 답함" : ""}">${esc(short(r))}${isDead(r) ? ' <b class="down">종료됨</b>' : ""}
        <button class="flat sm" data-test="${esc(r)}" title="이 모델만 짧게 불러보기">테스트</button><button class="flat sm" data-rm="${i}" title="목록에서 빼기">✕</button></span>`).join("") || '<span class="muted">아직 없음 — 아래에서 추가하세요</span>'}</div>
      <div class="row" style="gap:6px;margin-top:6px;flex-wrap:wrap"><select id="aim-prov">${["nvidia", "gemini", "claude"].map((p) => `<option value="${p}">${PNAME[p]}</option>`).join("")}</select>
        <input id="aim-name" list="aim-dl" placeholder="모델 이름 (예: deepseek-ai/deepseek-v3.1)" style="flex:1;min-width:240px"><datalist id="aim-dl"></datalist>
        <button class="sm" id="aim-add">추가</button><button class="flat sm" id="aim-cat" title="이 키로 쓸 수 있는 모델 이름을 불러와 입력칸 추천에 넣음">모델 목록 불러오기</button></div>
      ${sugg.length ? `<div class="chips" style="margin-top:6px"><span class="muted" style="font-size:11px">추천:</span>${sugg.map((r) => `<button class="flat sm" data-addsug="${esc(r)}">+ ${esc(short(r))}</button>`).join("")}</div>` : ""}
      <div id="aim-test" class="muted" style="font-size:11.5px;margin-top:4px"></div></div>
    <div class="aim-sec"><div class="tm-sec">3. 기본 모델 · 대체 순서</div>
      <label class="aim-row">기본 모델 <select data-default>${opts(st.default, "키가 있는 공급자의 기본 모델")}</select></label>
      <div class="muted" style="font-size:11.5px">대체 순서 — 배정된 모델이 한도·오류로 실패하면 이 순서로 다음 모델을 시도합니다</div>
      <ol class="aim-fb">${st.fallback.map((r, i) => `<li>${esc(short(r))}${isDead(r) ? ' <b class="down">종료됨</b>' : ""} <button class="flat sm" data-up="${i}">↑</button><button class="flat sm" data-fbrm="${i}">✕</button></li>`).join("")}</ol>
      <label class="aim-row">추가 <select id="aim-fbadd">${opts("", "골라서 추가…")}</select></label></div>
    <div class="aim-sec"><div class="tm-sec">4. 기능별 모델</div>
      ${Object.entries(D.features_desc).map(([k, d]) => `<label class="aim-row"><span>${esc(d)}</span><select data-feature="${k}">${opts(st.features[k] || "")}</select></label>`).join("")}</div>
    <div class="aim-sec"><div class="tm-sec">5. 에이전트별 모델 <span class="muted">(23명 · 비우면 위 '에이전트 팀 판단형/반복형' 설정을 따름)</span></div>
      <div class="aim-roles">${D.roles_list.map((r) => `<label class="aim-row"><span>${r.emoji} ${esc(r.name)} <span class="muted">${r.tier === "opus" ? "판단형" : "반복형"}</span></span>
        <select data-role="${r.id}">${opts(st.roles[r.id] || "")}</select></label>`).join("")}</div></div>
    <div class="row" style="gap:8px;position:sticky;bottom:0;background:var(--panel);padding:8px 0"><button class="pri" id="aim-save">모델 배정 저장</button>
      <span class="muted" style="font-size:11.5px">무료 모델은 한도가 있어서, 많이 쓰는 반복형 에이전트엔 가벼운 모델, 판단형엔 큰 모델을 추천합니다.</span></div>`;
}

function collect() {
  st.default = $("[data-default]").value;
  document.querySelectorAll("[data-feature]").forEach((s) => { if (s.value) st.features[s.dataset.feature] = s.value; else delete st.features[s.dataset.feature]; });
  document.querySelectorAll("[data-role]").forEach((s) => { if (s.value) st.roles[s.dataset.role] = s.value; else delete st.roles[s.dataset.role]; });
}

async function onClick(e) {
  const t = e.target;
  if (t.id === "aim-savekeys") {
    const body = {};
    document.querySelectorAll("[data-key]").forEach((i) => { if (i.value.trim()) body[i.dataset.key] = i.value.trim(); });
    if (!Object.keys(body).length) return toast("넣은 키가 없습니다");
    await busy(t, async () => { const r = await api("/api/ai/keys", { method: "POST", body }); toast("키를 적용했습니다", r.saved_to_file ? "settings.txt 에도 저장" : "이번 실행에만 적용 (settings.txt 를 찾지 못함)"); await openAiModels(); });
    return;
  }
  if (t.id === "aim-dropdead") { dropDead(); return; }
  if (t.id === "aim-add") {
    const name = $("#aim-name").value.trim();
    if (!name) return;
    collect(); st.models.push(`${$("#aim-prov").value}:${name}`); st.models = [...new Set(st.models)]; render(); return;
  }
  if (t.dataset.addsug) { collect(); st.models = [...new Set([...st.models, t.dataset.addsug])]; render(); return; }
  if (t.dataset.rm != null) { collect(); const r = st.models.splice(+t.dataset.rm, 1)[0]; st.fallback = st.fallback.filter((x) => x !== r); render(); return; }
  if (t.dataset.fbrm != null) { collect(); st.fallback.splice(+t.dataset.fbrm, 1); render(); return; }
  if (t.dataset.up != null) { collect(); const i = +t.dataset.up; if (i > 0) [st.fallback[i - 1], st.fallback[i]] = [st.fallback[i], st.fallback[i - 1]]; render(); return; }
  if (t.id === "aim-cat") {
    await busy(t, async () => {
      const prov = $("#aim-prov").value;
      const r = await loadCatalog(prov, true);
      $("#aim-prov").value = prov;
      toast(`${PNAME[r.provider]} 모델 ${r.models.length}개`, "입력칸을 누르면 추천 목록이 나옵니다");
    });
    return;
  }
  if (t.dataset.test) {
    $("#aim-test").textContent = `${short(t.dataset.test)} 테스트 중…`;
    await busy(t, async () => {
      const r = await api("/api/ai/test", { method: "POST", body: { route: t.dataset.test } });
      $("#aim-test").innerHTML = r.ok ? `<span class="up">✓ ${esc(short(r.route))}${r.used && r.used !== r.route ? ` (실제로 답한 모델: ${esc(r.used.split(":").slice(1).join(":"))})` : ""} (${r.seconds}초)</span> ${esc(r.answer)}` : `<span class="down">✕ ${esc(short(r.route))}: ${esc(r.error)}</span>`;
      if (r.dead) { D.dead = { ...D.dead, [r.route]: {} }; collect(); const msg = $("#aim-test").innerHTML; render(); $("#aim-test").innerHTML = msg; }
    });
    return;
  }
  if (t.id === "aim-save") {
    collect();
    await busy(t, async () => { await api("/api/ai/routes", { method: "POST", body: st }); toast("AI 모델 배정을 저장했습니다", "다음 AI 호출부터 적용됩니다"); await openAiModels(); });
  }
}

document.addEventListener("change", (e) => {
  if (e.target.id === "aim-fbadd" && e.target.value) { collect(); st.fallback = [...new Set([...st.fallback, e.target.value])]; render(); }
});
