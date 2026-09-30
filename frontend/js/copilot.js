// 실시간 AI 상황 분석 (트레이드 오른쪽 '실시간 AI' 탭)
// 몇 초마다 /api/copilot 을 읽는다. 경고 · 포지션은 매번 새로, AI 분석은 서버가 필요할 때만(새 봉 · 가격 급변 · 포지션 변경 ·
// 새 위험 경고 · 최대 간격 경과) 다시 만든다. 탭을 열지 않아도 1분마다 스스로 분석하고 차트 위 'AI 배지'에 결과를 띄운다.
import { addPriceAlert } from "./alerts.js";
import { $, IV_LABEL, api, busy, cls, esc, hhmm, pct, px, state, toast } from "./core.js";

const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
const store = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 무시 */ } };
const prefs = { every: 30, maxAge: 300, ...load("ft.copilot", {}) };
const ACTION = { hold: "유지", add: "추가 진입", reduce: "일부 청산", close: "전량 청산", move_stop: "손절 이동", take_profit: "익절" };
const URG = { high: ["긴급", "down"], medium: ["주의", "accent"], low: ["참고", "muted"] };
const BIAS = { long: ["롱 우위", "up"], short: ["숏 우위", "down"], neutral: ["중립", "accent"] };
const ENGINE = { claude: "Claude", gemini: "Gemini", nvidia: "NVIDIA", rules: "규칙 분석" };
const QUICK = ["지금 포지션 버텨도 될까?", "손절은 어디가 좋아?", "지금 진입해도 돼?", "다음 봉 어떻게 봐?"];

let hooks = {}, last = null, timer = null, loading = false, chats = {}, lastLoad = 0;
const BG_SEC = 60;                  // 탭이 닫혀 있을 때 스스로 다시 보는 간격

const visible = () => !$("#side-ai").hidden && !document.hidden;

export function initCopilot(h) {
  hooks = h;
  const el = $("#side-ai");
  el.innerHTML = `<div class="row" style="gap:6px;flex-wrap:wrap">
      <b style="font-size:13px">실시간 AI 상황 분석</b><span class="ai-eng" id="ai-eng"></span><div class="grow"></div>
      <button class="pri sm" id="ai-now" title="지금 바로 다시 분석">지금 분석</button></div>
    <div class="help" style="margin:2px 0 4px">🤖 자동 분석 켜짐 — 이 탭을 열지 않아도 AI 가 차트·포지션을 계속 보고 판단이 바뀌면 알림으로 알려줍니다.</div>
    <div class="row ai-ctl">
      <label>화면 갱신<select id="ai-every">${[[0, "끄기"], [15, "15초"], [30, "30초"], [60, "1분"], [180, "3분"]].map(([v, l]) => `<option value="${v}" ${+prefs.every === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label title="변화가 없어도 이 시간이 지나면 AI 가 다시 분석">AI 재분석 최대<select id="ai-maxage">${[[180, "3분"], [300, "5분"], [600, "10분"], [900, "15분"], [1800, "30분"]].map(([v, l]) => `<option value="${v}" ${+prefs.maxAge === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label title="내 포지션에 위험 경고가 뜨면 이 탭을 열어두지 않아도 서버가 AI 분석을 돌려 알림에 붙임"><input type="checkbox" id="ai-auto"> 위험 시 자동 AI</label></div>
    <div id="ai-status" class="muted" style="font-size:11px;margin:4px 0 6px"></div>
    <div id="ai-body"><div class="muted">분석 중…</div></div>
    <div class="fc-sec" style="margin-top:8px"><div class="sub" style="padding-left:0">AI 에게 질문 <span class="muted">(지금 차트 · 포지션을 보고 답함)</span></div>
      <div class="chips" id="ai-quick">${QUICK.map((q) => `<button class="flat sm" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>
      <div id="ai-chat" class="ai-chat"></div>
      <div class="row" style="gap:4px;margin-top:4px"><input id="ai-q" placeholder="예: 지금 숏 들어가면 손절은?" style="flex:1"><button class="sm" id="ai-send">보내기</button></div></div>`;
  $("#ai-every").onchange = (e) => { prefs.every = +e.target.value; store("ft.copilot", prefs); schedule(); };
  $("#ai-maxage").onchange = (e) => { prefs.maxAge = +e.target.value; store("ft.copilot", prefs); };
  $("#ai-now").onclick = (e) => busy(e.target, () => refresh(true));
  $("#ai-auto").onchange = (e) => api("/api/copilot/config", { method: "POST", body: { auto_ai: e.target.checked } }).catch(() => {});
  api("/api/copilot/alerts?since=" + Math.floor(Date.now() / 1000)).then((d) => ($("#ai-auto").checked = !!d.settings?.auto_ai)).catch(() => {});
  $("#ai-send").onclick = (e) => busy(e.target, () => ask($("#ai-q").value));
  $("#ai-q").onkeydown = (e) => { if (e.key === "Enter" && !e.isComposing) $("#ai-send").click(); };
  $("#ai-quick").onclick = (e) => { const q = e.target.dataset.q; if (q) busy(e.target, () => ask(q)); };
  el.addEventListener("click", onAction);
  document.addEventListener("visibilitychange", () => !document.hidden && refresh());
  setInterval(tickStatus, 1000);
  $("#ai-badge").onclick = () => document.querySelector('#side-tabs [data-t="ai"]')?.click();
  schedule();
  setTimeout(() => refresh(), 1500);          // 앱을 켜면 바로 한 번
}

// 탭을 열거나 코인·봉이 바뀌면 부른다
export function showCopilot() { renderChat(); refresh(); schedule(); }
export function copilotSymbolChanged() { last = null; renderChat(); $("#ai-body").innerHTML = `<div class="muted">분석 중…</div>`; badge(); refresh(); }

// 탭이 보이면 '화면 갱신' 간격, 안 보여도 1분마다 (서버는 바뀐 게 있을 때만 AI 를 부름)
function schedule() {
  clearInterval(timer);
  timer = setInterval(() => {
    if (document.hidden) return;
    const gap = (Date.now() - lastLoad) / 1000;
    if (visible() ? (prefs.every && gap >= prefs.every) : gap >= BG_SEC) refresh();
  }, 5000);
}

async function refresh(force = false) {
  if (loading && !force) return;
  const sym = state.symbol, iv = state.interval;
  loading = true;
  if (force) $("#ai-status").textContent = "AI 가 분석 중… (AI 는 10~30초 걸릴 수 있음)";
  try {
    lastLoad = Date.now();
    const r = await api(`/api/copilot?symbol=${sym}&interval=${iv}&max_age=${prefs.maxAge}${force ? "&force=true" : ""}`);
    if (sym !== state.symbol || iv !== state.interval) return;
    const fresh = !last || last.analyzed_at !== r.analyzed_at;
    last = { ...r, got: Date.now() };
    render(fresh);
  } catch (e) {
    $("#ai-status").textContent = "실패: " + e.message;
  } finally { loading = false; }
}

// 차트 위 AI 배지 (시세 줄 끝) — 누르면 AI 탭
function badge() {
  const el = $("#ai-badge");
  if (!el) return;
  if (!last) { el.innerHTML = `<span class="muted">🤖 AI 분석 중…</span>`; el.className = "ai-badge"; return; }
  const a = last.analysis, [bl, bc] = BIAS[a.bias], urgent = a.position_advice.some((x) => x.urgency === "high") || last.alerts.some((x) => x.level === "high");
  el.className = `ai-badge ${urgent ? "hot" : ""}`;
  el.title = `${a.headline}\n${a.situation}\n(${ENGINE[last.engine] || last.engine}${last.model ? ` · ${last.model}` : ""} · 누르면 실시간 AI 탭)`;
  el.innerHTML = `<span class="k">🤖 AI${last.updating ? " …" : ""}</span><span class="ai-chip ${bc}">${bl} ${a.confidence}%</span>${urgent ? '<span class="ai-chip down">⚠ 포지션</span>' : ""}<span class="ai-bh">${esc(a.headline)}</span>`;
}

function tickStatus() {
  if (!last || !visible()) return;
  const age = last.age_sec + Math.round((Date.now() - last.got) / 1000), left = Math.max(0, last.bar_left_sec - Math.round((Date.now() - last.got) / 1000));
  $("#ai-status").innerHTML = `${age < 60 ? `${age}초` : `${Math.floor(age / 60)}분`} 전 분석 (${esc(last.refresh_reason)}) · 분석 때 가격 ${px(last.price_at_analysis)} → 지금 ${px(last.price)}
    <span class="${cls(last.price - last.price_at_analysis)}">${pct((last.price / last.price_at_analysis - 1) * 100)}</span> · ${IV_LABEL[last.interval] || last.interval} 봉 마감까지 ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}
    ${last.updating ? ' · <span class="accent">새 분석 중…</span>' : ""}`;
}

function posLine(p) {
  const L = p.side === "long";
  return `<div class="ai-pos"><b class="${L ? "up" : "down"}">${esc(p.kind === "manual" ? "내" : p.target)} ${p.symbol.replace("USDT", "")} ${L ? "롱" : "숏"} ${p.leverage}x</b>
    <span class="${cls(p.upnl)}">${p.upnl >= 0 ? "+" : ""}${p.upnl.toFixed(2)} (${pct(p.roe_pct, 1)})</span>
    <span class="muted">진입 ${px(p.entry)} · 손절 ${p.stop ? `${px(p.stop)} (${pct(p.to_stop_pct)})` : '<span class="down">없음</span>'} · 청산 ${px(p.liq)} (${pct(p.to_liq_pct)})</span></div>`;
}

function render(fresh) {
  badge();
  const r = last, a = r.analysis, [bl, bc] = BIAS[a.bias];
  $("#ai-eng").innerHTML = `<span class="${r.engine === "rules" ? "muted" : "accent"}">${ENGINE[r.engine] || r.engine}${r.model ? ` · ${esc(r.model)}` : ""}</span>`;
  const myPos = r.positions.filter((p) => p.symbol === r.symbol || p.kind === "manual");
  $("#ai-body").innerHTML = `
    ${r.error ? `<div class="ai-alert medium">${esc(r.error)}</div>` : ""}
    ${!r.llm_available ? `<div class="help" style="margin-bottom:6px">AI 키가 없어 <b>규칙 분석</b>으로 보여줍니다. settings.txt 에 NVIDIA·Gemini(무료) 또는 Claude 키를 넣으면 AI 가 직접 판단합니다.</div>` : ""}
    ${r.alerts.length ? `<div class="ai-alerts">${r.alerts.map((x) => `<div class="ai-alert ${x.level}">${x.level === "high" ? "⚠ " : ""}${esc(x.text)}</div>`).join("")}</div>` : ""}
    <div class="ai-head ${fresh ? "flash" : ""}"><span class="ai-chip ${bc}">${bl}</span><b>${esc(a.headline)}</b></div>
    <div class="row" style="gap:6px;margin:4px 0"><span class="muted" style="font-size:11px">확신</span><div class="ai-bar" style="flex:1"><i style="width:${a.confidence}%;background:var(--${bc === "accent" ? "accent" : bc})"></i></div><span style="font-size:11px">${a.confidence}%</span></div>
    <div class="ai-text">${esc(a.situation)}</div>
    ${a.changes ? `<div class="ai-text muted" style="margin-top:4px">변화: ${esc(a.changes)}</div>` : ""}
    ${myPos.length || a.position_advice.length ? `<div class="sub" style="padding-left:0;margin-top:8px">포지션 관리</div>${myPos.map(posLine).join("")}
      ${a.position_advice.map(advCard).join("")}` : ""}
    ${a.entry_idea ? ideaCard(a.entry_idea) : ""}
    ${a.key_levels.length ? `<div class="sub" style="padding-left:0;margin-top:8px">핵심 가격 <span class="muted">(🔔 = 가격 알림 등록)</span></div>
      ${a.key_levels.map((k) => `<div class="kv"><span class="k">${esc(k.label)}</span><span>${px(k.price)} <span class="muted">${pct((k.price / r.price - 1) * 100)}</span>
        <button class="flat sm" data-alert="${k.price}" title="이 가격에 알림">🔔</button></span></div>`).join("")}` : ""}
    ${a.risks.length ? `<div class="sub" style="padding-left:0;margin-top:8px">위험</div><ul class="reasons">${a.risks.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    ${a.watch.length ? `<div class="sub" style="padding-left:0;margin-top:8px">다음 봉 마감 전까지 볼 것</div><ul class="reasons">${a.watch.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    ${r.history.length > 1 ? `<div class="sub" style="padding-left:0;margin-top:8px">분석 기록</div>
      ${r.history.slice().reverse().map((h) => `<div class="ai-hist"><span class="muted">${hhmm(h.time)}</span><span class="${BIAS[h.bias][1]}">${BIAS[h.bias][0]} ${h.confidence}%</span>
        <span class="muted">${px(h.price)} · ${esc(h.why)}</span></div>`).join("")}` : ""}
    <div class="help" style="margin-top:8px">투자 조언이 아닙니다. AI 는 틀릴 수 있으니 손절 위치를 먼저 정하고, 버튼은 모의(페이퍼) 계좌에만 적용됩니다.</div>`;
  tickStatus();
}

function advCard(v) {
  const [ul, uc] = URG[v.urgency], manual = v.target.startsWith("내 포지션");
  let btn = "";
  if (manual) {
    if (v.action === "move_stop" && v.new_stop) btn = `<button class="sm" data-act="stop" data-sym="${v.symbol}" data-v="${v.new_stop}">손절 ${px(v.new_stop)} 적용</button>`;
    if (v.new_take) btn += `<button class="sm" data-act="take" data-sym="${v.symbol}" data-v="${v.new_take}">익절 ${px(v.new_take)} 적용</button>`;
    if (["reduce", "take_profit"].includes(v.action)) btn += `<button class="sm" data-act="reduce" data-sym="${v.symbol}" data-v="${v.fraction || 0.5}">${Math.round((v.fraction || 0.5) * 100)}% 청산</button>`;
    if (v.action === "close") btn += `<button class="sm" data-act="close" data-sym="${v.symbol}">전량 청산</button>`;
  }
  return `<div class="ai-adv ${v.urgency}"><div class="row"><b>${esc(v.target)}</b><div class="grow"></div><span class="ai-chip ${uc}">${ul}</span><span class="ai-chip">${ACTION[v.action] || v.action}</span></div>
    <div class="ai-text">${esc(v.reason)}</div>
    ${btn ? `<div class="row" style="gap:4px;margin-top:4px;flex-wrap:wrap">${btn}</div>` : !manual ? `<div class="muted" style="font-size:11px">봇이 자동으로 관리하는 포지션 — 참고 의견</div>` : ""}</div>`;
}

function ideaCard(e) {
  const k = e.action, title = { long: "롱 진입 아이디어", short: "숏 진입 아이디어", wait: "지금은 관망" }[k];
  const plan = k !== "wait" && e.entry && e.stop && e.take ? JSON.stringify({ k, entry: e.entry, stop: e.stop, take: e.take }).replace(/'/g, "&#39;") : null;
  return `<div class="plan ${k === "wait" ? "" : k}" style="margin-top:8px"><div class="row"><b>${title}</b><div class="grow"></div>${plan ? `<button class="flat sm" data-plan='${plan}'>차트에</button>` : ""}</div>
    ${k !== "wait" ? `<div class="kv2"><span class="k">진입</span><span>${px(e.entry)}</span><span class="k">손절</span><span class="down">${px(e.stop)}</span><span class="k">익절</span><span class="up">${px(e.take)}</span></div>` : ""}
    <div class="ai-text"><b>조건</b> ${esc(e.trigger)}</div><div class="help">${esc(e.reason)}</div></div>`;
}

async function onAction(e) {
  const al = e.target.closest("[data-alert]");
  if (al) { addPriceAlert(state.symbol, +al.dataset.alert); toast("가격 알림 등록", `${state.symbol} ${px(+al.dataset.alert)}`); return; }
  const b = e.target.closest("[data-act]");
  if (!b) return;
  const { act, sym } = b.dataset, v = +b.dataset.v, pos = last?.positions.find((p) => p.symbol === sym && p.kind === "manual");
  const what = { stop: `손절을 ${px(v)}로 옮길까요?`, take: `익절을 ${px(v)}로 바꿀까요?`, reduce: `${sym} 포지션의 ${Math.round(v * 100)}%를 시장가로 청산할까요?`, close: `${sym} 포지션을 전부 시장가로 청산할까요?` }[act];
  if (!confirm(`${what}\n(모의 계좌)`)) return;
  await busy(b, async () => {
    if (act === "stop" || act === "take") await api(`/api/paper/position/${sym}`, { method: "POST", body: { stop: act === "stop" ? v : pos?.stop ?? null, take: act === "take" ? v : pos?.take ?? null } });
    else if (act === "reduce") await api(`/api/paper/reduce/${sym}`, { method: "POST", body: { fraction: v } });
    else await api(`/api/paper/close/${sym}`, { method: "POST" });
    toast("적용했습니다", what.replace(/할까요\?|길까요\?|꿀까요\?/, "").trim());
    hooks.afterTrade?.();
    await refresh();
  });
}

function renderChat() {
  const log = chats[state.symbol] || [];
  const el = $("#ai-chat");
  if (!el) return;
  el.innerHTML = log.map((m) => `<div class="msg ${m.role === "user" ? "me" : "bot"}">${esc(m.text).replace(/\n/g, "<br>")}</div>`).join("");
  el.scrollTop = el.scrollHeight;
}

async function ask(q) {
  q = (q || "").trim();
  if (!q) return;
  const sym = state.symbol, log = (chats[sym] ||= []);
  log.push({ role: "user", text: q });
  $("#ai-q").value = "";
  renderChat();
  try {
    const r = await api("/api/copilot/ask", { method: "POST", body: { symbol: sym, interval: state.interval, question: q, history: log.slice(-7, -1) } });
    log.push({ role: "ai", text: r.answer });
  } catch (e) { log.push({ role: "ai", text: "실패: " + e.message }); }
  if (sym === state.symbol) renderChat();
}
