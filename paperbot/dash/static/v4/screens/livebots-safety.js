// 실거래 › 안전 (#/livebots/safety): per executor (/api/v4/livebots/safety) whether it is halted and why (and since when),
// the risk limits its config REALLY has (owners 10/19 took the $40 daily limit and the wallet check out: a limit the
// config does not set is simply not listed), the kill file (/var/lib/paperbot/STOP: there or not), the signal light now and
// every time it turned red (or could not read the paper), the halt log, and its WARN / CRITICAL log, 10 a page. Between
// them the live checks (livebots-checks.js, livecheck.db): 아침 점검 of the last 14 days and the watcher's 감시 알람.
// HONESTY: the executors' own records only; an executor that could not be read says 못 읽음 and why; the page changes
// nothing (no 'clear halt' button: that stays a command on the server, with a name and a note).
import {h, put, ui, fmt, local, motion} from "../core/pb.js";
import {lightRow, sourceState, notesEl} from "./livebots-kit.js";
import {checksView} from "./livebots-checks.js";

const REFRESH_MS = 30 * 1000;

/** safetyView(ctx) -> {el, set()} */
export function safetyView(ctx) {
  const st = {d: null, okAt: 0, ex: local.get("lb-sex", "all")};
  const stateSlot = h("div", {class: "lb-slot"});
  const cards = h("div", {class: "lb-safe"});
  const exSeg = ui.seg([{id: "all", label: "전부"}, {id: "bybit", label: "바이비트"}, {id: "mexc", label: "WOO X Pro"}], st.ex, (id) => { st.ex = id; local.set("lb-sex", id); drawLog(true); },
    {label: "실행기 고르기"});
  const pg = ui.pager({size: 10, row: (e) => evRow(e), empty: () => (st.d ? ui.empty("주의 · 긴급 기록이 아직 없어요") : motion.shimmer(3))});
  const checks = checksView();
  const el = h("div", {class: "lb-safety stack"}, stateSlot, cards, checks.el,
    ui.card({title: "주의 · 긴급 기록", sub: "실행기 두 개 · 거래소 요청 재시도는 뺌 · 10개씩", cls: "lb-logcard", acts: [exSeg]}, pg.el),
    ui.note("멈춤 풀기는 이 화면에 없어요: 서버에서 이름과 메모를 남기는 명령으로만 풀어요 (clear-halt)"),
    h("div", {class: "lb-foot"}, ui.assumeLive("바이비트 · WOO X Pro 실행기 기록"), ui.assumeLine(["closed"], "아침 점검의 페이퍼 손익")));

  function evRow(e) {
    return h("div", {class: "lb-ev", role: "listitem"},
      h("div", {class: "lb-evtop"}, h("span", {class: "num muted"}, fmt.kst(e.ts)), h("b", null, e.ex_ko),
        ui.pill(e.level_ko || e.level, e.level === "CRITICAL" ? "bad" : "warn"), h("span", {class: "lb-kind"}, e.kind_ko || e.kind)),
      ui.moreText(e.text || "", 2));
  }
  function card(x) {
    const r = x.record || {}, c = x.config || {};
    const kill = c.kill_file;
    const head = r.state !== "ok" ? sourceState(r, `${x.name_ko} 실행기 DB`)
      : r.halted ? h("p", {class: "lb-halt"}, h("b", null, "멈춤"), ` · ${r.halt_reason || "이유 기록 없음"}`, r.halted_ts ? ` · ${fmt.kst(r.halted_ts)}부터` : "",
        " · 사람이 풀 때까지 새 진입 없음") : h("p", {class: "lb-ok"}, ui.pill("멈춤 아님", "good"), r.stale ? ui.pill(`기록 멈춤 · ${fmt.ago(r.as_of_ms)}`, "warn") : null,
        r.consecutive_losses != null ? h("span", {class: "lb-meta"}, ` 연속 손실 ${fmt.int(r.consecutive_losses)}번`) : null);
    const limits = c.state === "ok" ? (c.limits && c.limits.length ? h("ul", {class: "lb-limits"}, c.limits.map((l) => h("li", {title: l.what_ko}, h("b", null, l.ko))))
      : ui.empty("설정에 적힌 위험 한도가 없어요")) : sourceState(c, "실행기 설정");
    const halts = (r.halts || []).slice(-6).reverse();
    const lights = (x.lights || []).slice(0, 6);
    return ui.card({title: x.name_ko, sub: c.state === "ok" ? `${c.exchange || ""} · ${c.mode || ""} · 따라가는 계좌 ${c.account || "—"}` : "", cls: "lb-scard2"},
      head,
      h("div", {class: "lb-kill"}, h("span", {class: "muted"}, "비상 정지 파일 "), kill ? [h("b", {class: kill.present ? "down" : "up"}, kill.present ? "있음 (모든 진입 멈춤)" : "없음"),
        h("span", {class: "muted lb-path"}, ` · ${kill.path}`)] : h("span", {class: "muted"}, "설정에 없음")),
      h("h3", {class: "lb-h3"}, "설정에 적힌 위험 한도"), limits,
      h("h3", {class: "lb-h3"}, "신호등"), lightRow(x),
      lights.length ? ui.disclosure(`신호등 기록 ${fmt.int((x.lights || []).length)}번 보기`, h("ul", {class: "lb-lhist"}, lights.map((l) => h("li", null,
        h("span", {class: "num muted"}, fmt.kst(l.ts)), " ", h("b", {class: l.kind === "light_red" ? "down" : "warn-t"}, l.kind_ko), " ", h("span", null, l.text))))) : h("p", {class: "note"}, "신호등이 빨강이었던 적이 아직 없어요"),
      halts.length ? ui.disclosure(`멈춤 기록 ${fmt.int((r.halts || []).length)}번 보기`, h("ul", {class: "lb-lhist"}, halts.map((t) => h("li", null,
        h("span", {class: "num muted"}, fmt.kst(t.ts)), " ", h("b", {class: t.action === "halt" ? "down" : "up"}, t.action === "halt" ? "멈춤" : "풀림"), ` ${t.reason || ""}`)))) : null,
      notesEl(x.notes));
  }
  function drawLog(user) {
    const d = st.d;
    if (!d) { pg.set(undefined); return; }
    const all = [];
    for (const x of d.execs || []) for (const e of x.log || []) all.push({...e, ex: x.id, ex_ko: x.name_ko});
    all.sort((a, b) => (b.ts || 0) - (a.ts || 0));
    pg.set(all.filter((e) => st.ex === "all" || e.ex === st.ex), !user);
  }
  function draw() {
    const d = st.d;
    if (!d) { put(cards, motion.shimmer(4)); drawLog(false); checks.set(null); return; }
    put(cards, (d.execs || []).map(card));
    checks.set(d.checks || {state: "missing", reason_ko: "서버가 점검 기록을 보내지 않았어요"});
    drawLog(false);
  }
  async function load() {
    try { st.d = await ctx.api("/api/v4/livebots/safety"); st.okAt = Date.now(); put(stateSlot); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      throw e;
    }
    if (ctx.alive()) draw();
  }
  draw();
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  return {el, set() {}};
}
