// 실거래 › 신호 (#/livebots/signals): "왜 안 들어갔지?". Every signal of the combined bot (the paper bot both executors
// follow) of the last 7 Korea-time days and what became of it (/api/v4/livebots/signals: its signal_log rows and the
// account's outcomes): 걸러짐 with the bot's own Korean why (연구 조건 밖 · 끈 구간 · 주말 · 경제 발표 앞뒤 · 돌파 없음 …),
// 돌파 기다림 / 돌파 확인, and for a submitted signal its outcome (진입 · 포지션 있음 · 같은 때 다른 신호에 밀림 · 늦음 · 손절
// 자리가 안 맞음 …). A funnel for today and the 7 days, the reasons counted, the newest 200 in a list of 10 a page.
// HONESTY: counts of real rows only; a signal whose outcome is not written yet says so; the executors follow only the
// paper's entries (their own skips are on 안전 and 거래).
import {h, put, ui, fmt, local, motion} from "../core/pb.js";
import {sourceState} from "./livebots-kit.js";

const REFRESH_MS = 30 * 1000;
const STAGE = [["signals", "신호"], ["filtered", "걸러짐"], ["waiting", "돌파 기다림"], ["skipped", "밀림·건너뜀"], ["rejected", "거절"], ["entered", "진입"]];
const TONE = {entered: "good", filtered: "thin", waiting: "accent", broke: "accent", skipped: "warn", rejected: "bad", submitted: "thin", other: "thin"};
const LIST = [{id: "all", label: "전부"}, {id: "out", label: "안 들어감"}, {id: "entered", label: "진입"}];

/** Rows for a list filter: "all", "entered", or "out" (every signal that did not become an entry). */
export const rowsFor = (rows, f) => (rows || []).filter((r) => f === "all" || (f === "entered" ? r.stage === "entered" : r.stage !== "entered" && r.status !== "BROKE"));

/** signalsView(ctx) -> {el, set()} */
export function signalsView(ctx) {
  const st = {span: local.get("lb-sspan", "today"), list: "out", d: null, okAt: 0};
  if (!["today", "week"].includes(st.span)) st.span = "today";
  const spanSeg = ui.seg([{id: "today", label: "오늘"}, {id: "week", label: "최근 7일"}], st.span, (id) => { st.span = id; local.set("lb-sspan", id); draw(); }, {label: "기간"});
  const funnel = h("div", {class: "lb-funnel"});
  const reasons = h("div", {class: "lb-reasons"});
  const stateSlot = h("div", {class: "lb-slot"});
  const listSeg = ui.seg(LIST, st.list, (id) => { st.list = id; drawList(true); }, {label: "목록 고르기"});
  const pg = ui.pager({size: 10, row: (r) => rowOf(r), empty: () => (st.d ? ui.empty("맞는 신호가 없어요") : motion.shimmer(3))});
  const el = h("div", {class: "lb-signals stack"},
    ui.card({title: "신호가 어디까지 갔나", sub: "합친 봇(페이퍼)의 신호 · 한국 시간", cls: "lb-fcard", acts: [spanSeg]}, stateSlot, funnel,
      h("p", {class: "lb-rhead"}, "이유별"), reasons,
      ui.note("실거래 실행기는 페이퍼가 진입한 것만 따라가요 (신호등이 빨강이거나 멈춤이면 그것도 건너뜀: 거래 · 안전 탭)")),
    ui.card({title: "왜 안 들어갔지?", sub: "최근 신호 200개까지 · 10개씩", cls: "lb-scard", acts: [listSeg]}, pg.el));

  function rowOf(r) {
    return h("div", {class: ["lb-srow", r.stage], role: "listitem"},
      h("span", {class: "num muted lb-st"}, fmt.kst(r.t)), h("b", {class: "lb-tc"}, fmt.coin(r.symbol)), ui.sideTag(r.side),
      h("span", {class: "lb-ss", title: r.member}, `${fmt.stratKo(r.strategy)} · ${fmt.tfKo(r.tf)}`),
      ui.pill(r.ko, TONE[r.stage] || "thin"),
      r.why && r.why !== r.ko ? h("span", {class: "lb-sw2 muted", title: r.why}, ui.moreText(r.why_ko || r.why, 2)) : null);
  }
  function drawList(user) { pg.set(st.d && st.d.state === "ok" ? rowsFor(st.d.rows, st.list) : st.d ? [] : undefined, !user); }
  function draw() {
    spanSeg.set(st.span);
    const d = st.d;
    if (!d) { put(funnel, motion.shimmer(2)); put(reasons); drawList(false); return; }
    if (d.state !== "ok") { put(stateSlot, sourceState(d, "페이퍼 DB (신호 기록)")); put(funnel); put(reasons); drawList(false); return; }
    put(stateSlot);
    const sg = d.stages[st.span] || {};
    const top = Math.max(1, sg.signals || 0);
    put(funnel, STAGE.map(([k, ko]) => h("div", {class: ["lb-fstep", k]}, h("span", {class: "lb-fk"}, ko),
      h("span", {class: "lb-fbar"}, h("i", {style: {width: `${((sg[k] || 0) / top * 100).toFixed(1)}%`}})), h("b", {class: "num"}, fmt.int(sg[k] || 0)))));
    const cs = (d.counts[st.span] || []);
    const mx = Math.max(1, ...cs.map((c) => c.n));
    put(reasons, cs.length ? cs.map((c) => h("div", {class: ["lb-rsn", c.stage]}, h("span", {class: "lb-rk"}, c.ko),
      h("span", {class: "lb-rbar"}, h("i", {style: {width: `${(c.n / mx * 100).toFixed(1)}%`}})), h("b", {class: "num"}, fmt.int(c.n))))
      : ui.empty(st.span === "today" ? "오늘은 아직 신호가 없어요" : "최근 7일 신호가 없어요"));
    drawList(false);
  }
  async function load() {
    try { st.d = await ctx.api("/api/v4/livebots/signals"); st.okAt = Date.now(); }
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
