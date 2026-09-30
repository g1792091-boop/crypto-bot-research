// 에이전트 팀 (23명) — 회의(아침 계획 · 저녁 점검 · 주간 검토 · 긴급 복기)를 채팅방처럼 실시간으로 보여준다.
// 서버가 에이전트를 차례로 부르고 메시지를 쌓으면, 화면은 1초마다 새 메시지만 읽는다.
import { $, $$, api, busy, esc, hhmm, on, toast } from "./core.js";

let R = null;              // /api/team/roster 결과
let cur = null;            // 보고 있는 대화방 id
let msgs = [], total = 0, runInfo = null, timer = null, visible = false;
const DIR = { long: ["롱", "up"], short: ["숏", "down"], both: ["양방향", "accent"], none: ["쉬기", "muted"], neutral: ["중립", "muted"] };
const LVL = { normal: ["정상", "up"], caution: ["주의", "accent"], danger: ["위험", "down"] };
const ACT = { keep: "유지", reduce: "축소", pause_strategy: "봇 중지", pause_all: "전체 중지" };
const SRC = (s) => !s ? "" : s === "rules" ? "규칙" : /opus/i.test(s) ? "Opus" : /sonnet/i.test(s) ? "Sonnet" : /gemini/i.test(s) ? "Gemini" : s.includes("/") ? s.split("/").pop() : s;

const who = (id) => R?.roster.find((r) => r.id === id);

export function initAgents() {
  on("view", (v) => { visible = v === "agents"; if (visible) open(); });
  $("#v-agents").addEventListener("click", onClick);
  $("#tm-runs").onchange = (e) => select(e.target.value);
  $("#tm-send").onclick = (e) => busy(e.target, send);
  $("#tm-text").onkeydown = (e) => { if (e.key === "Enter" && !e.isComposing) $("#tm-send").click(); };
  $("#tm-newchat").onclick = (e) => busy(e.target, async () => { const r = await api("/api/team/chat", { method: "POST" }); await loadRuns(r.id); });
}

async function open() {
  R = await api("/api/team/roster");
  $("#tm-engine").textContent = R.engine === "rules" ? "AI 키 없음 → 규칙 분석" : R.engine === "claude" ? "Claude (Opus·Sonnet)" : R.engine === "nvidia" ? "NVIDIA" : "Gemini";
  renderRoster();
  renderSide();
  await loadRuns(cur);
  schedule();
}

async function loadRuns(pick) {
  const d = await api("/api/team/runs");
  $("#tm-runs").innerHTML = d.items.length ? d.items.map((r) => `<option value="${r.id}">${r.status === "running" ? "● " : ""}${esc(r.title)} · ${hhmm(r.started)} · ${r.messages}개${r.trigger !== "사람" ? ` (${esc(r.trigger)})` : ""}</option>`).join("")
    : `<option value="">아직 회의 없음</option>`;
  const id = pick || cur || d.items[0]?.id;
  if (id) { $("#tm-runs").value = id; await select(id); }
}

async function select(id) {
  if (!id) return;
  if (id !== cur) { cur = id; msgs = []; total = 0; $("#tm-msgs").innerHTML = ""; }
  await poll();
}

function schedule() {
  clearInterval(timer);
  timer = setInterval(() => { if (visible && !document.hidden && cur) poll(); }, 1000);
}

let polling = false, slowTick = 0, lastTyping = "";
async function poll() {
  if (polling) return;
  // 진행 중이 아니면 5초에 한 번만 (사람 질문의 답을 기다릴 때)
  if (runInfo && runInfo.id === cur && runInfo.status !== "running" && !runInfo.typing.length && (slowTick++ % 5)) return;
  polling = true;
  try {
    const v = await api(`/api/team/runs/${cur}?since=${total}`);
    if (v.id !== cur) return;
    const wasRunning = runInfo?.status === "running";
    runInfo = v;
    if (v.messages.length) { msgs.push(...v.messages); total = v.total; appendMsgs(v.messages); }
    $("#tm-title").textContent = v.title;
    $("#tm-status").innerHTML = v.status === "running" ? '<span class="accent">● 회의 중</span>' : v.status === "error" ? '<span class="down">오류로 중단</span>' : `끝 · ${v.engine === "rules" ? "규칙 분석" : v.engine}`;
    renderTyping(v.typing);
    if (v.typing.join() !== lastTyping) { lastTyping = v.typing.join(); renderRoster(v.typing); }
    if (v.messages.length || wasRunning) renderSide(v);
    if (wasRunning && v.status !== "running") { R = await api("/api/team/roster"); renderSide(v); loadRuns(cur); }
  } catch { /* 다음 주기 */ } finally { polling = false; }
}

// ---------------------------------------------------------------- 명단
function renderRoster(typing = runInfo?.typing || []) {
  if (!R) return;
  const teams = {};
  R.roster.forEach((r) => (teams[r.team] ||= []).push(r));
  $("#tm-roster").innerHTML = Object.entries(teams).map(([t, rs]) => `<div class="tm-team"><div class="tm-team-h" style="color:${R.teams[t].color}">${esc(R.teams[t].name)} <span class="muted">${rs.length}</span></div>
    ${rs.map((r) => `<div class="tm-member ${typing.includes(r.id) ? "typing" : ""}" data-mention="${esc(r.name)}" title="${esc(r.duty)}\n참여: ${r.pipelines.map((p) => R.pipelines[p].name).join(", ") || "-"}\n클릭하면 채팅에서 부를 수 있습니다">
      <span class="tm-av" style="background:${r.color}22;border-color:${r.color}">${r.emoji}</span>
      <span class="tm-mn"><b>${esc(r.name)}</b><span class="muted">${esc(r.duty)}</span>
        ${r.scorecard?.n ? `<span class="muted">적중 ${r.scorecard.hit_rate_pct}% (${r.scorecard.n}건${r.scorecard.status === "ok" ? "" : ", 표본 부족"})</span>` : ""}</span>
      <span class="tm-tier ${r.tier}">${r.tier === "opus" ? "Opus" : "Sonnet"}</span></div>`).join("")}</div>`).join("");
}

// ---------------------------------------------------------------- 메시지
function mention(t) {
  return esc(t).replace(/@([가-힣A-Za-z·()]+(?: [가-힣A-Za-z·()]+)?)/g, (m, n) => {
    const r = R?.roster.find((x) => n.startsWith(x.name) || n.replace(/ /g, "").startsWith(x.name.replace(/ /g, "")));
    return r ? `<b class="tm-at" style="color:${r.color}">@${esc(r.name)}</b>${esc(n.slice(r.name.length))}` : m;
  });
}

function detail(d) {
  if (!d) return "";
  const ev = (e) => (e || []).map((p) => `<code>${esc(p)}</code>`).join(" ");
  const parts = [];
  if (d.findings?.length) parts.push(`<div class="tm-sec">근거 있는 주장</div>${d.findings.map((f) => `<div class="tm-f ${f.severity}"><span class="tm-k">${f.kind === "fact" ? "사실" : "가설"}</span>${esc(f.claim)}<div class="tm-ev">${ev(f.evidence)}</div></div>`).join("")}`);
  if (d.calls?.length) parts.push(`<div class="tm-sec">코인별 판단</div><div class="tm-chips">${d.calls.map((c) => `<span class="ai-chip ${DIR[c.bias][1]}">${c.symbol.replace("USDT", "")} ${DIR[c.bias][0]}</span>`).join("")}</div>`);
  if (d.allowed?.length) parts.push(`<div class="tm-sec">허용범위 초안</div>${d.allowed.map((a) => `<div class="tm-f"><span class="ai-chip ${DIR[a.direction][1]}">${a.symbol.replace("USDT", "")} ${DIR[a.direction][0]}</span> ${esc(a.reason || "")}<div class="tm-ev">${ev(a.evidence)}</div></div>`).join("")}`);
  if (d.focus?.length) parts.push(`<div class="tm-sec">집중할 것</div><ul class="reasons">${d.focus.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`);
  if (d.risk_level) parts.push(`<div class="tm-sec">위험 수준 <span class="ai-chip ${LVL[d.risk_level][1]}">${LVL[d.risk_level][0]}</span></div>
    ${(d.decisions || []).map((a) => `<div class="tm-f"><span class="ai-chip ${DIR[a.direction][1]}">${a.symbol.replace("USDT", "")} ${DIR[a.direction][0]}</span> ${esc(a.reason || "")}</div>`).join("")}
    ${(d.actions || []).map((a) => `<div class="tm-f ${a.action === "keep" ? "" : "warn"}"><b>${ACT[a.action]}</b> ${esc(a.target || "")} — ${esc(a.reason || "")}<div class="tm-ev">${ev(a.evidence)}</div></div>`).join("")}`);
  if (d.proposals?.length) parts.push(`<div class="tm-sec">제안 (가설)</div>${d.proposals.map((p) => `<div class="tm-f"><b>${esc(p.change)}</b> — ${esc(p.reason || "")}${p.how_to_confirm ? `<div class="muted">확인 방법: ${esc(p.how_to_confirm)}</div>` : ""}<div class="tm-ev">${ev(p.evidence)}</div></div>`).join("")}`);
  if (d.hypotheses?.length) parts.push(`<div class="tm-sec">새 매매법 가설</div>${d.hypotheses.map((h) => `<div class="tm-f"><b>${esc(h.name)}</b> (${esc(h.symbol || "")} ${esc(h.interval || "")})<div>${esc(h.rule)}</div><div class="muted">${esc(h.why || "")}</div></div>`).join("")}`);
  if (d.verdicts?.length) parts.push(`<div class="tm-sec">판정</div>${d.verdicts.map((v) => `<div class="tm-f"><span class="ai-chip ${v.verdict === "pass" ? "up" : v.verdict === "fail" ? "down" : "accent"}">${{ pass: "통과", fail: "탈락", need_more_data: "데이터 더" }[v.verdict]}</span> ${esc(v.candidate)} — ${esc(v.reason || "")}</div>`).join("")}`);
  if (d.approvals?.length) parts.push(`<div class="tm-sec">승인</div>${d.approvals.map((a) => `<div class="tm-f"><span class="ai-chip ${a.decision === "approve" ? "up" : "down"}">${a.decision === "approve" ? "승인" : "거부"}</span> ${esc(a.candidate)} — ${esc(a.reason || "")}</div>`).join("")}`);
  if (d.weights?.length) parts.push(`<div class="tm-sec">자본 배분안</div>${d.weights.map((w) => `<div class="tm-f"><b>${esc(w.bot)}</b> ${w.weight_pct}% — ${esc(w.reason || "")}</div>`).join("")}`);
  if (d.memos?.length) parts.push(`<div class="tm-sec">관찰 메모</div>${d.memos.map((m) => `<div class="tm-f">${esc(m.text)} <span class="muted">(${m.n}건)</span></div>`).join("")}`);
  if (d.summary?.length) parts.push(`<div class="tm-sec">3줄 요약</div><ol class="tm-ol">${d.summary.map((x) => `<li>${esc(x)}</li>`).join("")}</ol>
    ${d.human_actions?.length ? `<div class="tm-sec">사람이 할 일</div><ul class="reasons">${d.human_actions.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    ${d.glossary?.length ? `<div class="tm-sec">용어</div>${d.glossary.map((g) => `<div class="muted">${esc(g.term)}: ${esc(g.meaning)}</div>`).join("")}` : ""}`);
  if (d.data_gaps?.length) parts.push(`<div class="tm-sec">모자란 데이터</div><ul class="reasons">${d.data_gaps.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`);
  return parts.length ? `<details class="tm-det" ${d.summary ? "open" : ""}><summary>${d.headline ? esc(d.headline) + " · " : ""}자세히</summary>${parts.join("")}</details>` : "";
}

function msgHtml(m) {
  const t = hhmm(m.ts);
  if (m.from === "human") return `<div class="tm-m me"><div class="tm-bub">${mention(m.text)}</div><span class="tm-t">${t} · 나</span></div>`;
  if (m.from === "code") {
    if (m.kind === "result" && m.data?.plan) {
      const p = m.data.plan;
      return `<div class="tm-code result"><b>📋 ${esc(m.text.split(":")[0])}</b>
        <div class="tm-plan">${Object.entries(p.allowed).map(([s, v]) => `<span class="ai-chip ${DIR[v.direction][1]}" title="${esc(v.reason)} (전략가: ${DIR[v.strategist][0]})">${s.replace("USDT", "")} ${DIR[v.direction][0]}</span>`).join("")}</div>
        <span class="muted">${esc(m.text.split(" — ")[1] || "")}</span></div>`;
    }
    return `<div class="tm-code ${m.kind}"><span>${m.kind === "check" ? "🧾 " : m.kind === "result" ? "📋 " : "⚙ "}${esc(m.text)}</span><span class="tm-t">${t}</span></div>`;
  }
  const r = who(m.from) || { name: m.from, emoji: "🤖", color: "#888", team_name: "" };
  const src = SRC(m.meta?.source);
  return `<div class="tm-m"><span class="tm-av" style="background:${r.color}22;border-color:${r.color}">${r.emoji}</span>
    <div class="tm-body"><div class="tm-name"><b style="color:${r.color}">${esc(r.name)}</b><span class="muted">${esc(r.team_name)}</span>${src ? `<span class="tm-src">${esc(src)}</span>` : ""}<span class="tm-t">${t}</span></div>
      <div class="tm-bub">${mention(m.text)}</div>${detail(m.data)}
      ${m.meta?.bad_evidence?.length ? `<div class="muted" style="font-size:11px">⚠ 입력에 없는 근거 인용: ${m.meta.bad_evidence.map(esc).join(", ")}</div>` : ""}</div></div>`;
}

function appendMsgs(list) {
  const box = $("#tm-msgs");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80 || box.children.length <= 1;
  if (box.querySelector(".empty")) box.innerHTML = "";
  box.insertAdjacentHTML("beforeend", list.map(msgHtml).join(""));
  if (atBottom) box.scrollTop = box.scrollHeight;
}

function renderTyping(ids) {
  $("#tm-typing").innerHTML = ids.length ? `<span class="dots"><i></i><i></i><i></i></span> ${ids.map((id) => { const r = who(id); return r ? `${r.emoji} ${esc(r.name)}` : id; }).join(", ")} 입력 중…` : "";
}

// ---------------------------------------------------------------- 오른쪽: 결과 · 설정
function renderSide(v = runInfo) {
  if (!R) return;
  const plan = v?.results?.plan || R.plan, risk = v?.results?.risk, lead = v?.results?.lead, S = R.settings;
  const today = plan && (Date.now() / 1000 - plan.made) < 36 * 3600;
  const cands = v?.results?.candidates || [], appr = v?.results?.approvals || [];
  const acts = (risk?.actions || []).filter((a) => a.action !== "keep");
  $("#tm-side").innerHTML = `
    <div class="panel"><div class="ph"><span class="t">오늘의 허용범위</span><div class="grow"></div>${plan ? `<span class="ai-chip ${LVL[plan.risk_level]?.[1] || ""}">위험 ${LVL[plan.risk_level]?.[0] || "-"}</span>` : ""}</div>
      <div class="pb">${plan ? `<div class="muted" style="font-size:11px;margin-bottom:4px">${esc(plan.date)} 아침 계획${today ? "" : " (오래됨 — 봇 관문에 쓰지 않음)"}</div>
        <table class="tm-tbl">${Object.entries(plan.allowed).map(([s, a]) => `<tr><td>${s.replace("USDT", "")}</td><td><span class="ai-chip ${DIR[a.direction][1]}">${DIR[a.direction][0]}</span></td><td class="muted">${a.strategist !== a.direction ? `전략가 ${DIR[a.strategist][0]} → 좁힘` : ""}</td></tr>`).join("")}</table>
        <div class="help">전략가 초안을 리스크 책임자가 승인하거나 좁힌 결과입니다 (넓히기는 코드가 거부). 봇 관문이 켜져 있으면 페이퍼 봇이 이 방향으로만 진입합니다.</div>`
        : `<div class="muted">아직 없음 — '아침 계획'을 실행하세요.</div>`}</div></div>
    ${lead ? `<div class="panel"><div class="ph"><span class="t">팀장 요약</span></div><div class="pb"><ol class="tm-ol">${lead.summary.map((x) => `<li>${esc(x)}</li>`).join("")}</ol>
      ${lead.human_actions.length ? `<div class="tm-sec">사람이 할 일</div><ul class="reasons">${lead.human_actions.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div></div>` : ""}
    ${acts.length ? `<div class="panel"><div class="ph"><span class="t">리스크 조치 권고</span><span class="muted">적용은 사람이</span></div><div class="pb">
      ${acts.map((a) => `<div class="tm-f warn"><b>${ACT[a.action]}</b> ${esc(a.target || "")}<div class="muted">${esc(a.reason || "")}</div>
        ${a.action === "pause_all" ? `<button class="sm" data-apply="pause_all">모든 봇 멈추기</button>` : a.action === "pause_strategy" ? `<button class="sm" data-apply="pause_bot" data-target="${esc(a.target)}">이 봇 멈추기</button>` : `<span class="muted" style="font-size:11px">포지션 축소는 트레이드 화면 'AI' 탭이나 포지션 표에서</span>`}</div>`).join("")}</div></div>` : ""}
    ${cands.length ? `<div class="panel"><div class="ph"><span class="t">후보 (주간)</span></div><div class="pb">
      ${cands.map((c) => { const a = appr.find((x) => x.candidate === c.id), ok = a?.decision === "approve" && c.gate?.passed;
        return `<div class="tm-f ${c.gate?.passed ? "" : "muted"}"><b>${esc(c.target)}</b> <span class="muted">${c.kind === "improve" ? "봇 수정안" : "새 가설"}</span>
          <div>관문 ${c.gate?.passed ? '<span class="up">통과</span>' : `<span class="down">탈락</span> — ${esc(c.gate?.reason || "")}`}${a ? ` · 승인관 ${a.decision === "approve" ? '<span class="up">승인</span>' : '<span class="down">거부</span>'}` : ""}</div>
          ${c.rule ? `<div class="muted" style="font-size:11px">${esc(c.rule)}</div>` : ""}
          ${ok ? `<button class="pri sm" data-apply="candidate" data-cand="${esc(c.id)}">${c.kind === "improve" ? "봇에 적용" : "페이퍼 봇으로 시작"}</button>` : ""}</div>`; }).join("")}</div></div>` : ""}
    <div class="panel"><div class="ph"><span class="t">설정</span></div><div class="pb tm-set">
      <div class="tm-sec">자동 회의 (프로그램이 켜져 있을 때, 한국 시간)</div>
      ${[["morning", "아침 계획"], ["evening", "저녁 점검"], ["weekly", "주간 검토"]].map(([k, l]) => `<label><input type="checkbox" data-auto="${k}" ${S.auto[k] ? "checked" : ""}> ${l} <input class="tm-time" data-time="${k}" value="${esc(S.times[k])}"></label>`).join("")}
      <label title="AI 포지션 감시의 위험 경고나 큰 손실(ROE -30% 이하·강제청산)이 나면 긴급 복기 (1시간에 한 번)"><input type="checkbox" data-auto="emergency" ${S.auto.emergency ? "checked" : ""}> 긴급 복기 자동</label>
      <label title="켜면 페이퍼 봇이 오늘의 허용범위 밖 방향으로는 진입하지 않습니다 (코드 관문)"><input type="checkbox" id="tm-gate" ${S.bot_gate ? "checked" : ""}> 봇 관문 (허용범위를 봇에 적용)</label>
      <label>분석 코인 <input id="tm-coins" value="${esc(S.coins.map((c) => c.replace("USDT", "")).join(", "))}"></label>
      <label>하루 AI 호출 상한 <input id="tm-limit" type="number" value="${S.daily_call_limit}" style="width:70px"></label>
      <button class="sm" id="tm-save">설정 저장</button></div></div>
    ${R.knowledge?.lessons?.length || R.knowledge?.memos?.length ? `<div class="panel"><div class="ph"><span class="t">학습 (교훈 · 메모)</span></div><div class="pb">
      ${(R.knowledge.lessons || []).map((l) => `<div class="tm-f"><b>교훈</b> ${esc(l.text)} <span class="muted">(${l.n}건)</span></div>`).join("")}
      ${(R.knowledge.memos || []).slice(-6).map((m) => `<div class="tm-f muted">메모 ${esc(m.text)} <span>(${m.n}건 · ${m.seen}회)</span></div>`).join("")}
      <div class="help">메모는 검증 전까지 판단에 쓰지 않습니다. 표본 30건 이상 · 두 번 이상 관찰된 것만 교훈이 됩니다.</div></div></div>` : ""}`;
}

async function onClick(e) {
  const p = e.target.closest("[data-pipe]");
  if (p) {
    await busy(p, async () => { const r = await api("/api/team/run", { method: "POST", body: { pipeline: p.dataset.pipe } }); runInfo = null; await loadRuns(r.id); });
    return;
  }
  const m = e.target.closest("[data-mention]");
  if (m) { const i = $("#tm-text"); i.value = `@${m.dataset.mention} ${i.value.replace(/^@\S+(?: \S+)? /, "")}`; i.focus(); return; }
  const a = e.target.closest("[data-apply]");
  if (a) {
    const k = a.dataset.apply;
    if (!confirm({ pause_all: "모든 페이퍼 봇을 멈출까요?", pause_bot: `봇 '${a.dataset.target}' 을 멈출까요?`, candidate: "승인된 후보를 적용할까요? (페이퍼 봇)" }[k])) return;
    await busy(a, async () => { const r = await api("/api/team/apply", { method: "POST", body: { kind: k, target: a.dataset.target, run_id: cur, candidate: a.dataset.cand } }); toast("적용했습니다", r.msg); });
    return;
  }
  if (e.target.id === "tm-save") {
    const auto = {}, times = {};
    $$("[data-auto]").forEach((x) => (auto[x.dataset.auto] = x.checked));
    $$("[data-time]").forEach((x) => (times[x.dataset.time] = x.value.trim()));
    await busy(e.target, async () => {
      const s = await api("/api/team/settings", { method: "POST", body: { auto, times, bot_gate: $("#tm-gate").checked, coins: $("#tm-coins").value.split(/[,\s]+/).filter(Boolean),
        daily_call_limit: +$("#tm-limit").value || 80 } });
      R.settings = s; renderSide(); toast("에이전트 팀 설정을 저장했습니다");
    });
  }
}

async function send() {
  const t = $("#tm-text").value.trim();
  if (!t) return;
  if (!cur) { const r = await api("/api/team/chat", { method: "POST" }); await loadRuns(r.id); }
  await api(`/api/team/runs/${cur}/say`, { method: "POST", body: { text: t } });
  $("#tm-text").value = "";
  slowTick = 0;
  if (runInfo) runInfo.status = "running";   // 답이 올 때까지 1초마다 읽기
  await poll();
}

