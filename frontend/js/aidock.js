// 차트 옆 'AI 상시' 패널 — AI 알림(진입 시그널 · AI 봇 진입/청산 · 포지션 경고 · 브리핑 · 판단 변경)이 계속 흘러오고,
// 아래 입력칸으로 AI(지금 차트·포지션을 보고 답함) 또는 @에이전트(에이전트 팀)에게 바로 말할 수 있다.
import { $, IV_LABEL, api, esc, hhmm, on, pct, px, state } from "./core.js";
import { showOnChart } from "./trade.js";

const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
const store = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 무시 */ } };
const TAG = {
  signal: ["시그널", "accent"], bot: ["봇", "up"], alert: ["경고", "down"], brief: ["브리핑", "muted"], analysis: ["AI 분석", "muted"],
  me: ["나", ""], ai: ["AI", "accent"], team: ["팀", "accent"],
};
const FILTERS = [["all", "전체"], ["trade", "시그널·봇"], ["watch", "경고·브리핑"], ["chat", "채팅"]];
const QUICK = ["지금 들어가도 돼?", "AI 봇 성적 어때?", "@팀장 지금 상황 브리핑해줘", "@리스크 책임자 내 포지션 위험해?"];

let items = [], seen = new Set(), filter = load("ft.dock.filter", "all"), onlyHere = load("ft.dock.here", false);
let chat = load("ft.dock.chat", []), unread = 0, names = null, lastBias = {};
const open = () => !document.querySelector(".trade")?.classList.contains("dock-off");

export function initAiDock() {
  const trade = document.querySelector(".trade");
  $("#chartp").insertAdjacentHTML("afterend", `<aside class="aidock" id="aidock">
    <button class="dk-strip" id="dk-open" title="AI 상시 알림 · 채팅 펼치기"><span>🤖</span><b>AI</b><i id="dk-unread" hidden></i></button>
    <div class="dk-main">
      <div class="ph"><span class="t">🤖 AI 상시 알림 · 채팅</span><div class="grow"></div><button class="flat sm" id="dk-fold" title="접기 (차트를 넓게)">⟩</button></div>
      <div class="dk-bot" id="dk-bot"></div>
      <div class="dk-chips">${FILTERS.map(([k, l]) => `<button class="flat sm ${filter === k ? "on" : ""}" data-dkf="${k}">${l}</button>`).join("")}
        <label title="지금 차트 코인만"><input type="checkbox" id="dk-here" ${onlyHere ? "checked" : ""}> 이 코인만</label></div>
      <div class="dk-stream" id="dk-stream"><div class="muted" style="padding:8px">불러오는 중…</div></div>
      <div class="dk-quick">${QUICK.map((q) => `<button class="flat sm" data-dkq="${esc(q)}">${esc(q)}</button>`).join("")}</div>
      <div class="dk-input"><textarea id="dk-text" rows="2" placeholder="AI 에게 질문 (지금 차트·포지션·AI 봇을 보고 답함) · @팀장 @리스크 책임자 처럼 부르면 에이전트 팀이 답함"></textarea>
        <button class="pri sm" id="dk-send">보내기</button></div>
    </div></aside>`);
  if (load("ft.dock.off", innerWidth < 1450)) trade.classList.add("dock-off");     // 처음엔 넓은 화면에서만 펼침 (접어도 알림 수가 보임)
  $("#dk-fold").onclick = () => { trade.classList.add("dock-off"); store("ft.dock.off", true); window.dispatchEvent(new Event("resize")); };
  $("#dk-open").onclick = () => { trade.classList.remove("dock-off"); store("ft.dock.off", false); unread = 0; badge(); render(true); window.dispatchEvent(new Event("resize")); };
  $("#aidock").addEventListener("click", onClick);
  $("#dk-here").onchange = (e) => { onlyHere = e.target.checked; store("ft.dock.here", onlyHere); render(true); };
  $("#dk-send").onclick = () => send($("#dk-text").value);
  $("#dk-text").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send($("#dk-text").value); } };
  on("apsignals", (xs) => { (xs || []).forEach(fromSignal); render(); });
  on("aiwatch", (xs) => { (xs || []).forEach(fromAlert); render(); });
  on("copilot", fromAnalysis);
  on("aibot", botLine);
  on("symbol", () => render(true));
  chat.forEach((m) => add(m, false));
  history();
}

// ---------------------------------------------------------------- 들어오는 것들 → 한 줄
function add(it, count = true) {
  if (it.key && seen.has(it.key)) return;
  if (it.key) seen.add(it.key);
  items.push(it);
  if (items.length > 400) items = items.slice(-300);
  if (count && !open() && ["signal", "bot", "alert", "ai", "team"].includes(it.kind)) { unread++; badge(); }
}

function fromSignal(x) {
  const kind = { ai_entry: "signal", aibot: "bot", entry: "bot", exit: "bot", deploy: "bot", ai_note: "bot", ai: "analysis", ai_auto: "brief" }[x.type] || "brief";
  const plan = x.entry && x.stop && x.take ? `진입 ${px(x.entry)} · 손절 ${px(x.stop)} · 익절 ${px(x.take)}` : "";
  add({ key: `s:${x.id}`, ts: x.created, kind, symbol: x.symbol, interval: x.interval, side: x.side, text: x.text,
    sub: [x.type === "aibot" ? "" : plan && !x.text.includes("진입 ") ? plan : "", x.strategy].filter(Boolean).join(" · "),
    tone: x.type === "aibot" && x.event === "exit" ? (x.pnl > 0 ? "up" : "down") : x.side === "long" ? "up" : x.side === "short" ? "down" : "" });
}

function fromAlert(a) {
  add({ key: `a:${a.id}`, ts: a.created, kind: "alert", symbol: a.symbol, text: a.text, sub: a.ai || "", tone: a.level === "high" ? "down" : "" });
}

function fromAnalysis(r) {
  const a = r?.analysis;
  if (!a) return;
  const k = `${r.symbol}:${r.interval}`, prev = lastBias[k];
  lastBias[k] = a.bias;
  const B = { long: "롱 우위", short: "숏 우위", neutral: "중립" };
  add({ key: `c:${k}:${r.analyzed_at}`, ts: r.analyzed_at, kind: "analysis", symbol: r.symbol, interval: r.interval,
    text: `${prev && prev !== a.bias ? `판단 변경 ${B[prev]} → ` : ""}${B[a.bias]} ${a.confidence}% — ${a.headline}`,
    sub: a.entry_idea && a.entry_idea.action !== "wait" ? `진입 아이디어: ${a.entry_idea.action === "long" ? "롱" : "숏"} ${px(a.entry_idea.entry)} · 손절 ${px(a.entry_idea.stop)} · 익절 ${px(a.entry_idea.take)}` : (a.watch || [])[0] || "",
    tone: a.bias === "long" ? "up" : a.bias === "short" ? "down" : "" });
  render();
}

function botLine(d) {
  const el = $("#dk-bot");
  if (!el || !d) return;
  const s = d.stats, o = d.open.find((t) => t.symbol === state.symbol) || d.open[0];
  el.innerHTML = `<span title="AI 진입 시그널을 따라 한 모의 매매 (아래 '체결 내역' → AI 봇)">🤖 AI 봇 <b class="${s.return_pct > 0 ? "up" : s.return_pct < 0 ? "down" : ""}">${pct(s.return_pct)}</b></span>
    <span class="muted">${s.trades}건${s.win_rate != null ? ` · 승률 ${s.win_rate}%` : ""}${s.avg_r != null ? ` · 평균 ${s.avg_r > 0 ? "+" : ""}${s.avg_r}R` : ""}</span>
    ${o ? `<span class="${o.side === "long" ? "up" : "down"}" data-dkchart="${o.symbol}|${o.interval}" style="cursor:pointer">보유 ${o.symbol.replace("USDT", "")} ${o.side === "long" ? "롱" : "숏"} ${pct(o.roe_pct, 1)}</span>` : ""}`;
}

async function history() {
  const since = Math.floor(Date.now() / 1000) - 24 * 3600;
  await Promise.all([
    api(`/api/autopilot/signals?since=${since}`).then((d) => d.items.slice().reverse().forEach((x) => fromSignal(x))).catch(() => {}),
    api(`/api/copilot/alerts?since=${since}`).then((d) => d.items.slice().reverse().forEach((x) => fromAlert(x))).catch(() => {}),
  ]);
  unread = 0; badge();
  render(true);
}

function badge() {
  const b = $("#dk-unread");
  if (!b) return;
  b.hidden = !unread; b.textContent = unread > 99 ? "99+" : unread;
}

// ---------------------------------------------------------------- 그리기
function pass(it) {
  if (onlyHere && it.symbol && it.symbol !== state.symbol) return false;
  if (filter === "trade") return ["signal", "bot"].includes(it.kind);
  if (filter === "watch") return ["alert", "brief", "analysis"].includes(it.kind);
  if (filter === "chat") return ["me", "ai", "team"].includes(it.kind);
  return true;
}

function render(jump = false) {
  const el = $("#dk-stream");
  if (!el) return;
  const atBottom = jump || el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  const list = items.slice().sort((a, b) => a.ts - b.ts).filter(pass).slice(-150);
  el.innerHTML = list.map(row).join("") || `<div class="muted" style="padding:10px">아직 없습니다. AI 가 시그널·경고·브리핑을 내면 여기로 계속 들어옵니다.</div>`;
  if (atBottom) el.scrollTop = el.scrollHeight;
}

function row(it) {
  const [tl, tc] = TAG[it.kind] || ["", ""];
  const coin = it.symbol ? `<b class="dk-coin" data-dkchart="${it.symbol}|${it.interval || ""}" title="이 코인 차트로">${it.symbol.replace("USDT", "")}${it.interval ? ` ${IV_LABEL[it.interval] || it.interval}` : ""}</b>` : "";
  if (["me", "ai", "team"].includes(it.kind)) {
    return `<div class="dk-msg ${it.kind}"><div class="dk-meta">${it.kind === "me" ? "나" : esc(it.who || "AI")} · ${hhmm(it.ts)}${it.pending ? " · 생각 중…" : ""}</div>
      <div class="dk-bubble">${esc(it.text).replace(/\n/g, "<br>")}</div></div>`;
  }
  return `<div class="dk-it ${it.tone || ""}"><span class="dk-t">${hhmm(it.ts)}</span><span class="ai-chip ${tc}">${tl}</span> ${coin} <span class="dk-x">${esc(it.text)}</span>
    ${it.sub ? `<div class="dk-sub">${esc(it.sub)}</div>` : ""}</div>`;
}

// ---------------------------------------------------------------- 채팅
function remember(m) {
  chat.push({ ...m, pending: false, key: undefined });
  chat = chat.slice(-80);
  store("ft.dock.chat", chat);
}

async function send(text) {
  text = (text || "").trim();
  if (!text) return;
  $("#dk-text").value = "";
  if (filter !== "all" && filter !== "chat") { filter = "all"; document.querySelectorAll("[data-dkf]").forEach((b) => b.classList.toggle("on", b.dataset.dkf === "all")); }
  const me = { ts: Math.floor(Date.now() / 1000), kind: "me", text };
  add(me, false); remember(me);
  if (text.startsWith("@")) return askTeam(text);
  const wait = { ts: me.ts + 0.1, kind: "ai", who: "AI", text: "…", pending: true };
  add(wait, false); render(true);
  try {
    const hist = chat.filter((m) => m.kind === "me" || m.kind === "ai").slice(-8, -1).map((m) => ({ role: m.kind === "me" ? "user" : "ai", text: m.text }));
    const r = await api("/api/copilot/ask", { method: "POST", body: { symbol: state.symbol, interval: state.interval, question: text, history: hist } });
    Object.assign(wait, { text: r.answer, pending: false, who: `AI${r.model ? ` · ${String(r.model).split("/").pop()}` : ""} (${state.symbol.replace("USDT", "")})`, ts: Math.floor(Date.now() / 1000) });
  } catch (e) { Object.assign(wait, { text: "실패: " + e.message, pending: false }); }
  remember(wait);
  render(true);
}

async function roomId() {
  let id = load("ft.dock.room", null);
  if (id) {
    try { await api(`/api/team/runs/${id}?since=999999`); return id; } catch { id = null; }
  }
  const r = await api("/api/team/chat", { method: "POST" });
  store("ft.dock.room", r.id);
  return r.id;
}

async function askTeam(text) {
  const wait = { ts: Math.floor(Date.now() / 1000) + 0.1, kind: "team", who: "에이전트 팀", text: "…", pending: true };
  add(wait, false); render(true);
  try {
    if (!names) names = Object.fromEntries((await api("/api/team/roster")).roster.map((r) => [r.id, `${r.emoji} ${r.name}`]));
    const id = await roomId();
    const start = (await api(`/api/team/runs/${id}?since=0`)).total;
    const r = await api(`/api/team/runs/${id}/say`, { method: "POST", body: { text } });
    wait.who = names[r.to] || r.to;
    render();
    for (let i = 0; i < 60; i++) {
      await new Promise((ok) => setTimeout(ok, 2000));
      const v = await api(`/api/team/runs/${id}?since=${start}`);
      const ans = v.messages.find((m) => m.from === r.to && m.kind === "message") || v.messages.find((m) => m.from === "code" && /답변 실패/.test(m.text));
      if (ans) { Object.assign(wait, { text: ans.text || ans.data?.headline || "(빈 답)", pending: false, ts: Math.floor(ans.ts) }); break; }
    }
    if (wait.pending) Object.assign(wait, { text: "답이 늦습니다. '에이전트 팀' 화면의 채팅방에서 이어서 볼 수 있습니다.", pending: false });
  } catch (e) { Object.assign(wait, { text: "실패: " + e.message, pending: false }); }
  remember(wait);
  render(true);
}

function onClick(e) {
  const f = e.target.closest("[data-dkf]");
  if (f) { filter = f.dataset.dkf; store("ft.dock.filter", filter); document.querySelectorAll("[data-dkf]").forEach((b) => b.classList.toggle("on", b === f)); render(true); return; }
  const q = e.target.closest("[data-dkq]");
  if (q) { send(q.dataset.dkq); return; }
  const c = e.target.closest("[data-dkchart]");
  if (c) { const [s, iv] = c.dataset.dkchart.split("|"); showOnChart(s, iv || state.interval); }
}
