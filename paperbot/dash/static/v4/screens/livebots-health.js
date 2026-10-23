// 실거래 › 봇 상태 (#/livebots/health, owners 10/19 night): is every bot alive, in one look. From /api/v4/livebots/health
// (dash/more/liveinsight.py health()):
//   한 줄        one traffic light: "다 정상", or what is late and by how much (the bots' own records, never a guess)
//   하나씩       the rule bot's newest 1m bar per coin and its last signal, the paper bot's heartbeat and last stepped
//                minute, each executor's last loop, the 1-minute watcher (Telegram alarms); each against its threshold,
//                said on the page (1m data: more than 3 minutes = 늦음)
//   진입 쉬는 시간 the pause now (KST weekend, ±30 minutes around a US macro release, 30 minutes after the Nasdaq open) and
//                when entries may come again; the next pause
//   비상 정지     the kill file there or not
// HONESTY: a file not there = 수집 전, unreadable = 못 읽음 + why (never "정상"); the ages tick with the server clock between
// answers; a failed refresh keeps the last answer dimmed with its age.
import {h, put, ui, fmt, motion, serverNow} from "../core/pb.js";
import {sourceState, execsNow} from "./livebots-kit.js";

export const HEALTH_API = "/api/v4/livebots/health";
const REFRESH_MS = 15 * 1000;


// ================================================================ pure functions (node tests)
const has = (x) => x != null && Number.isFinite(Number(x));
const mins = (ms) => fmt.dur(Number(ms) / 1000);

/** One item's state in words: {ko, tone} (tone ok / warn / bad). */
export function itemWords(it) {
  if (!it) return {ko: "—", tone: ""};
  if (it.state === "ok") return {ko: "정상", tone: "ok"};
  if (it.state === "missing") return {ko: "수집 전", tone: it.severity === "bad" ? "bad" : "warn"};
  if (it.state === "error") return {ko: "못 읽음", tone: it.severity === "bad" ? "bad" : "warn"};
  if (it.state === "quiet") return {ko: `조용함 · ${has(it.late_ms) ? mins(it.late_ms) : "—"}`, tone: "warn"};
  if (it.state === "late") return {ko: it.why_ko ? `늦음 · ${it.why_ko}` : "늦음", tone: it.severity === "bad" ? "bad" : "warn"};
  return {ko: String(it.state), tone: "warn"};
}

/** The thresholds in one line (the server's numbers). */
export function limitsWords(l) {
  if (!l) return "";
  const m = (x) => mins(x);
  return `늦음 기준: 1분봉·페이퍼 마지막 1분 ${m(l.bars_ms)}, 페이퍼 심장 박동 ${m(l.paper_hb_ms)}, 실행기 ${m(l.exec_ms)}, 감시 ${m(l.watch_ms)} 넘게 새 기록 없음`
    + ` · 규칙봇 신호는 ${m(l.signal_ms)} 넘게 없으면 '조용함' (장이 조용할 수도 있어요)`;
}

/** The pause now and the next resume, in words. */
export function pauseWords(pz, now) {
  if (!pz) return {ko: "쉬는 시간을 몰라요", tone: ""};
  const at = (ms) => (ms - now < 86400000 ? fmt.hm(ms) : fmt.kst(ms));
  if (pz.paused) {
    const why = (pz.why || []).map((w) => w.ko).join(" · ");
    return {ko: `지금 진입 쉬는 중 (${why})${has(pz.resume_ms) ? ` · 다시 진입 ${at(pz.resume_ms)}부터` : ""}`, tone: "warn"};
  }
  const n = pz.next;
  return {ko: `지금 진입할 수 있어요${n ? ` · 다음 쉬는 시간: ${n.ko} ${at(n.from)}~${at(n.to)}` : ""}`, tone: "ok"};
}

// ================================================================ the view
/** healthView(ctx) -> {el, set()}: its own endpoint, read now and every 15 s; the ages tick every 5 s in between. */
export function healthView(ctx) {
  const st = {d: null, okAt: 0, at: 0};
  const stateSlot = h("div", {class: "lb-slot"});
  const light = h("div", {class: "lbd-light", role: "status"});
  const list = h("div", {class: "lbd-list", role: "list"});
  const limits = h("p", {class: "lbd-limits"});
  const pause = h("div", {class: "lbd-slot"});
  const kill = h("div", {class: "lbd-slot"});
  const body = h("div", {class: "lbd-body stack"}, light,
    ui.card({title: "하나씩", sub: "마지막으로 기록을 남긴 때 · 한국 시간", cls: "lbd-card"}, list, limits),
    ui.card({title: "진입 쉬는 시간", sub: "주말 · 미국 경제 발표 앞뒤 · 나스닥 개장 앞뒤 (열린 포지션은 그대로)", cls: "lbd-card"}, pause),
    ui.card({title: "비상 정지", cls: "lbd-card"}, kill));
  const el = h("div", {class: "lbd stack"}, stateSlot, body);

  const now = () => serverNow();
  function ageOf(it) {
    if (!has(it.at) || !st.d) return "—";
    // between two answers the age grows with the clock (the record itself is the server's)
    const age = Number(st.d.now_ms) - Number(it.at) + Math.max(0, now() - st.at);
    return `${fmt.hm(it.at)} · ${has(age) ? `${mins(Math.max(0, age))} 전` : "—"}`;
  }
  function row(it) {
    const w = itemWords(it);
    const det = it.detail || {};
    const extra = it.id === "exec" && det.halted ? `멈춤: ${det.halt_reason || "이유 기록 없음"}`
      : it.id === "signal" && det.strategy ? `${fmt.stratKo(String(det.strategy).split("@")[0])} ${fmt.tfKo(det.tf)} ${fmt.coin(det.symbol)}` : "";
    return h("div", {class: ["lbd-row", "t-" + (w.tone || "none")], role: "listitem"},
      h("i", {class: ["lbd-dot", w.tone], "aria-hidden": "true"}),
      h("b", {class: "lbd-name"}, it.ko),
      h("span", {class: "lbd-age num", dataset: {age: "1"}}, ageOf(it)),
      h("span", {class: ["lbd-st", w.tone]}, w.ko),
      (it.state === "missing" || it.state === "error") && it.reason_ko ? h("span", {class: "lbd-why"}, it.reason_ko) : null,
      extra ? h("span", {class: "lbd-why"}, extra) : null);
  }
  function draw() {
    const d = st.d;
    if (!d) { put(light, motion.shimmer(1)); put(list, motion.shimmer(4)); put(pause); put(kill); return; }
    const s = d.summary || {};
    put(light, h("i", {class: ["lbd-big", s.tone], "aria-hidden": "true"}),
      h("b", {class: ["lbd-head", s.tone]}, s.tone === "ok" ? "다 정상" : s.ko || "확인 필요"),
      h("span", {class: "muted"}, ` · ${fmt.hm(d.now_ms)} 기준`));
    put(list, (d.items || []).map(row));
    put(limits, limitsWords(d.limits));
    const pw = pauseWords(d.pause, d.now_ms || now());
    const ev = (d.pause || {}).events || {};
    put(pause, h("p", {class: ["lbd-pause", pw.tone]}, pw.ko),
      ev.state && ev.state !== "ok" ? sourceState(ev, "경제 발표 일정 파일") : null,
      (d.pause || {}).us_error ? ui.note(`나스닥 개장 시간을 계산하지 못했어요 (${d.pause.us_error})`) : null,
      d.combo && d.combo.state !== "ok" ? sourceState(d.combo, "합친 봇 설정 (쉬는 시간 규칙)") : null);
    const k = d.kill || {};
    put(kill, (k.files || []).map((f) => h("p", {class: ["lbd-kill", f.present ? "on" : ""]}, h("i", {class: ["lbd-dot", f.present ? "bad" : "ok"], "aria-hidden": "true"}),
      h("b", null, f.present ? `비상 정지 파일 있음 (${execsNow().length > 2 ? "세" : "두"} 실행기 멈춤)` : "비상 정지 파일 없음"), ` ${f.path}`)),
    h("p", {class: "lbd-cmd"}, h("span", {class: "muted"}, "멈추는 명령 "), h("code", null, k.cmd || "sudo touch /var/lib/paperbot/STOP")));
  }
  function tick() {
    if (!st.d) return;
    const ages = [];
    const walk = (n) => { if (!n || !n.childNodes) return; if (n.dataset && n.dataset.age) ages.push(n); n.childNodes.forEach(walk); };
    walk(list);
    (st.d.items || []).forEach((it, i) => { if (ages[i]) ages[i].textContent = ageOf(it); });
  }
  async function load() {
    let d;
    try { d = await ctx.api(HEALTH_API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      ui.dim(body, !!st.d);
      throw e;
    }
    if (!ctx.alive()) return;
    st.okAt = serverNow(); st.at = serverNow();
    put(stateSlot);
    ui.dim(body, false);
    st.d = d;
    draw();
  }
  draw();
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  ctx.every(5000, tick, {now: false});
  return {el, set() {}};
}
