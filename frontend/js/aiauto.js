// AI 자동 모드 — 백그라운드에서 스스로 도는 AI 작업(마켓 브리핑 · 포트폴리오 리스크 · 봇 코치 · 스캐너 코멘트 · 차트 실시간 AI)의
// 결과 카드를 각 화면에 띄우고, 오토파일럿 화면에서 켜고 끄기 · 간격을 정한다.
import { $, api, busy, emit, esc, hhmm, on, toast } from "./core.js";

let S = null, view = "trade";
const LV = { ok: ["평소", "up"], caution: ["주의", "accent"], danger: ["위험", "down"] };
const BIAS = { long: ["롱 우위", "up"], short: ["숏 우위", "down"], neutral: ["중립", "muted"] };
const PNAME = { nvidia: "NVIDIA", gemini: "Gemini", claude: "Claude" };
// 화면별로 보여 줄 작업
const SLOTS = { "aa-market": "market", "aa-risk": "risk", "aa-bots": "bots", "aa-scanner": "scanner", "aa-team": "team", "aa-signals": "signals" };

export function initAiAuto() {
  $("#v-market .page").insertAdjacentHTML("afterbegin", `<div id="aa-market"></div>`);
  $("#q-tabs").closest(".panel").insertAdjacentHTML("afterend", `<div id="aa-risk"></div>`);
  $("#q-scan").insertAdjacentHTML("afterbegin", `<div id="aa-scanner"></div>`);
  $("#bot-list").closest(".panel").insertAdjacentHTML("beforebegin", `<div id="aa-bots"></div>`);
  $("#v-autopilot .cols-2 > div").insertAdjacentHTML("afterbegin", `<div class="panel" id="aa-panel"><div class="ph"><span class="t">🤖 AI 자동 모드</span>
    <span class="muted" id="aa-sub"></span><div class="grow"></div><label class="row" style="gap:4px"><input type="checkbox" id="aa-on" style="height:auto"> 켜기</label></div>
    <div class="pb" id="aa-set"><div class="muted">불러오는 중…</div></div></div>`);
  $("#aa-panel").insertAdjacentHTML("afterend", `<div id="aa-signals"></div>`);
  document.addEventListener("click", onClick);
  $("#aa-on").onchange = (e) => save({ enabled: e.target.checked });
  on("view", (v) => { view = v; load(); });
  load();
  setInterval(() => !document.hidden && load(), 15_000);
}

export const aiAuto = () => S;

async function load() {
  try { S = await api("/api/ai/auto"); } catch { return; }
  emit("aiauto", S);
  for (const [id, job] of Object.entries(SLOTS)) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = S.settings.enabled && S.settings.every_min[job] ? card(job) : "";
  }
  renderSet();
}

function ago(t) {
  if (!t) return "아직 안 돎";
  const s = Math.max(0, Math.round(Date.now() / 1000 - t));
  return s < 60 ? "방금" : s < 3600 ? `${Math.floor(s / 60)}분 전` : `${Math.floor(s / 3600)}시간 전`;
}

export function engineLabel(e) {
  if (!e || e === "rules") return "규칙 분석";
  const [p, ...m] = String(e).split(":");
  const name = m.join(":").split("/").pop();
  return `${PNAME[p] || p}${name ? ` · ${name}` : ""}`;
}

export function card(job) {
  const J = S?.jobs?.[job];
  if (!J) return "";
  const x = J.insight;
  const head = `<div class="ph"><span class="t">🤖 ${esc(J.title)}</span>${x ? ` <span class="ai-chip ${LV[x.level]?.[1] || ""}">${LV[x.level]?.[0] || ""}</span>` : ""}
    <span class="muted" style="font-size:11px">${x ? `${esc(engineLabel(x.engine))} · ${ago(x.at)}` : J.running ? "분석 중…" : "곧 첫 분석"}${J.running && x ? " · 다시 분석 중…" : ""}</span><div class="grow"></div>
    <button class="flat sm" data-aarun="${job}" title="지금 바로 다시 분석">지금 다시</button><button class="flat sm" data-aaset title="AI 자동 모드 설정 (오토파일럿 화면)">⚙</button></div>`;
  if (!x) return `<div class="panel aa-card">${head}<div class="pb muted">${J.running ? "AI 가 분석 중입니다…" : `앱이 켜져 있으면 ${J.every_min}분마다 스스로 분석합니다.`}</div></div>`;
  const bias = job === "market" && x.bias ? `<span class="ai-chip ${BIAS[x.bias][1]}">${BIAS[x.bias][0]}</span> ` : "";
  return `<div class="panel aa-card lvl-${x.level}">${head}<div class="pb">
    <div class="aa-head">${bias}<b>${esc(x.headline)}</b></div>
    ${x.points?.length ? `<ul class="reasons">${x.points.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>` : ""}
    ${x.actions?.length ? `<div class="aa-acts">${x.actions.map((p) => `<div>▶ ${esc(p)}</div>`).join("")}</div>` : ""}
    ${x.watch?.length ? `<div class="muted" style="font-size:11.5px;margin-top:4px">지켜볼 것: ${x.watch.map(esc).join(" · ")}</div>` : ""}
    ${x.error || J.error ? `<div class="help" style="margin-top:4px">${esc(x.error || J.error)}</div>` : ""}
    <div class="muted" style="font-size:10.5px;margin-top:6px">AI 자동 모드 · ${J.every_min}분마다 스스로 분석${J.next ? ` · 다음 ${hhmm(J.next)}` : ""} · 투자 조언 아님</div></div></div>`;
}

function renderSet() {
  if (!S || !$("#aa-set")) return;
  const s = S.settings;
  $("#aa-on").checked = s.enabled;
  $("#aa-sub").textContent = s.enabled ? ` · 켜짐 · 오늘 AI 호출 ${S.calls_today}/${s.daily_limit}${S.llm ? "" : " · AI 키 없음(규칙 분석)"}` : " · 꺼짐";
  if ($("#aa-set").contains(document.activeElement)) return;              // 입력 중이면 다시 그리지 않음
  $("#aa-set").innerHTML = `<div class="help" style="margin-bottom:6px">사람이 누르지 않아도 AI 가 아래 작업을 정해진 간격으로 스스로 돌리고, 결과를 각 화면(마켓 · 퀀트 · 전략)에 카드로 띄웁니다.
      판단이 바뀌거나 위험 수준이 오르면 알림(종)으로 알려줍니다. AI 키가 없거나 하루 상한을 넘으면 규칙 분석으로 대신합니다.</div>
    <table class="ap-tbl aa-jobs"><tr><th style="text-align:left">작업</th><th>간격(분)</th><th>최근</th><th></th></tr>
    ${Object.entries(S.jobs).map(([j, J]) => `<tr><td style="text-align:left"><b>${esc(J.title)}</b><div class="muted" style="font-size:11px">${esc(J.desc)}</div></td>
      <td><input type="number" min="0" max="1440" data-aaevery="${j}" value="${J.every_min}" style="width:58px" title="0 = 끔"></td>
      <td class="muted" style="font-size:11px">${J.running ? '<span class="accent">도는 중</span>' : ago(J.last)}${J.error ? `<div class="down" title="${esc(J.error)}">오류</div>` : ""}</td>
      <td><button class="flat sm" data-aarun="${j}">지금</button></td></tr>`).join("")}</table>
    <div class="ap-set" style="margin-top:6px">
      <label><input type="checkbox" data-aaflag="positions" ${s.positions ? "checked" : ""}> 내 포지션에 위험 경고가 뜨면 AI 가 바로 분석해 알림에 붙이기</label>
      <label><input type="checkbox" data-aaflag="bots_auto_improve" ${s.bots_auto_improve ? "checked" : ""}> 성과 나쁜 전략 시그널(10건 이상) 스스로 개선 — 검증 구간에서 나아질 때만 적용 (하루 한 번)</label>
      <label><input type="checkbox" data-aaflag="bots_auto_pause" ${s.bots_auto_pause ? "checked" : ""}> 가상 낙폭 35% 넘는 전략 시그널 자동 멈춤</label>
      <label><input type="checkbox" data-aaflag="notify" ${s.notify ? "checked" : ""}> 판단 변경 · 위험 상승 알림</label>
      <label>하루 AI 호출 상한 <input type="number" data-aalimit value="${s.daily_limit}" min="0" max="5000" style="width:70px">회</label>
      <button class="sm" id="aa-save">자동 모드 설정 저장</button>
      <button class="flat sm" data-open-ai>🧠 이 작업들에 쓸 AI 모델 고르기</button></div>
    ${S.feed?.length ? `<div class="tm-sec" style="margin-top:8px">최근 자동 알림</div>${S.feed.slice(0, 8).map((f) => `<div style="font-size:11.5px"><span class="muted">${hhmm(f.created)}</span> <span class="ai-chip ${LV[f.level]?.[1] || ""}">${esc(f.title)}</span> ${esc(f.text)}</div>`).join("")}` : ""}`;
}

async function save(body) {
  try { await api("/api/ai/auto/settings", { method: "POST", body }); toast("AI 자동 모드 설정 저장"); } catch (e) { toast("저장 실패", e.message, "err"); }
  load();
}

async function onClick(e) {
  const r = e.target.closest("[data-aarun]");
  if (r) {
    const job = r.dataset.aarun;
    await busy(r, async () => {
      toast(`${S?.jobs?.[job]?.title || job} 분석 중…`, "AI 는 10~40초 걸릴 수 있습니다");
      await api(`/api/ai/auto/run/${job}`, { method: "POST" });
      await load();
    });
    return;
  }
  if (e.target.closest("[data-aaset]")) { emit("goto", "autopilot"); setTimeout(() => $("#aa-panel")?.scrollIntoView({ behavior: "smooth" }), 50); return; }
  if (e.target.id === "aa-save") {
    const every = {}, body = { every_min: every, daily_limit: +$("[data-aalimit]").value };
    document.querySelectorAll("[data-aaevery]").forEach((i) => (every[i.dataset.aaevery] = +i.value));
    document.querySelectorAll("[data-aaflag]").forEach((i) => (body[i.dataset.aaflag] = i.checked));
    await busy(e.target, () => save(body));
  }
}
