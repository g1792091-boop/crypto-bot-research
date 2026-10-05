// 오늘의 회의 결론 보고판 (v4 additions wave 2 ⑥, ranked #11): the home card that replaced "최근 회의", and the report
// on the 대표실 desk (office floor). GET /api/v4/brief/meetings (dash/more/brief.py): today's finished meetings in
// three lines (the lead's first summary line, else the code summary's), the counts 회의 · 결정 · 갈린 의견, and a link
// to 회의 요약 › 회의 결론 (a row opens its own meeting there: ?r=<round>).
// HONESTY: every line is a stored line (never typed out, no typing effect); 회의 중 only from /api/office `running`;
// a row slides in (motion.fillIn) only when a NEW meeting really finished since the last answer; the counts count to a
// new value only when the server's number changed. No money here, so no caption.
import {h, s, put, ui, fmt, motion} from "../core/pb.js";

const STATUS = {done: ["결정", "accent"], no_action: ["행동 없음", "thin"], failed: ["멈춤", "warn"], stopped_budget: ["한도로 멈춤", "warn"]};
const POLL_MS = 60000;

const px = (x, y, w, hh, c) => s("rect", {x, y, width: w, height: hh, class: c});
/** A small pixel report (a sheet with a clip and three text lines). */
export const paperIcon = (cls = "") => s("svg", {class: ["mb-paper", cls], viewBox: "0 0 8 10", "shape-rendering": "crispEdges", "aria-hidden": "true"},
  px(0, 1, 8, 9, "pa"), px(2, 0, 4, 2, "pc"), px(1, 4, 6, 1, "pl"), px(1, 6, 5, 1, "pl"), px(1, 8, 4, 1, "pl"));

/** The server's answer, shared by the card and the desk report: polled while the screen is open, refreshed (after a
 *  short pause) when a room gets a new message; a 404 (an older server) stops asking. */
function feed(ctx, onData) {
  let on = true, t = null;
  const load = async () => {
    if (!on) return;
    let d;
    try { d = await ctx.api("/api/v4/brief/meetings"); } catch (e) {
      if (e && e.status === 404) { on = false; onData(null, true); } else if (!(e && e.name === "AbortError")) onData(null, false, e);
      return;
    }
    if (ctx.alive()) onData(d);
  };
  ctx.every(POLL_MS, load);
  ctx.on("rooms", () => { clearTimeout(t); t = setTimeout(() => ctx.alive() && load(), 2500); });
  ctx.track(() => clearTimeout(t));
  return load;
}

/**
 * meetBoard(ctx, {cls}) -> the home card (section.card) with .office(o): /api/office for 회의 중 and the next meeting.
 */
export function meetBoard(ctx, o = {}) {
  const st = {d: null, seen: null, office: null, gone: false};
  const nMeet = ui.liveNum(null, {format: "int", flash: "accent"}), nDec = ui.liveNum(null, {format: "int", flash: "accent"});
  const nDis = ui.liveNum(null, {format: "int", flash: "accent"});
  const tile = (k, v, cls, title) => h("div", {class: ["mb-tile", cls], title}, v, h("span", null, k));
  const counts = h("div", {class: "mb-counts", role: "group", "aria-label": "오늘 회의 수"},
    tile("회의", nMeet, "", "오늘 시작한 회의"), tile("결정", nDec, "", "오늘 끝난 회의 중 결정으로 끝난 것"),
    tile("갈린 의견", nDis, "amber", "회의를 이끈 직원이 의견이 갈린 채로 남긴 회의"));
  const now = h("div", {class: "mb-now"});
  const list = h("div", {class: "mb-list", role: "list"}, motion.shimmer(3));
  const foot = h("div", {class: "mb-foot"});
  const all = h("a", {class: "btn-line", href: ctx.href("digest", "day")}, "회의 결론 전체 →");
  const card = ui.card({plate: "오늘의 회의 결론", cls: ["mb-card", o.cls].filter(Boolean).join(" "), acts: [all]},
    counts, now, list, foot, ui.note("결론 = 회의를 이끈 직원이 남긴 요약 첫 줄 (없으면 코드 요약) · 저장된 글 그대로 · 누르면 그 회의"));

  function row(m, fresh) {
    const [ko, cls] = STATUS[m.status] || [m.status || "—", "thin"];
    const r = h("a", {class: ["mb-row", m.status === "done" ? "done" : ""], role: "listitem", href: ctx.href("digest", "day", {r: m.round_id}),
      title: `${m.title} · ${m.trigger_ko} 회의 열기`},
      h("span", {class: "mb-pin"}, paperIcon(m.status === "done" ? "done" : "")),
      h("span", {class: "mb-body"},
        h("span", {class: "mb-meta"}, h("b", {class: "num"}, fmt.hm(m.ts)), h("span", {class: "mb-room"}, m.title),
          h("span", {class: "muted"}, `· ${m.trigger_ko}`)),
        h("span", {class: "mb-line"}, m.line),
        m.dis ? h("span", {class: "mb-dis"}, `◆ 갈린 의견 · ${m.dis}`) : null),
      ui.pill(ko, cls));
    if (fresh) motion.fillIn(r, null);
    return r;
  }

  function renderNow() {
    const of = st.office, run = (of && of.running) || [];
    if (run.length) {
      const m = run[run.length - 1];
      put(now, h("a", {class: "mb-nowa", href: ctx.href("office")}, ui.livePill("회의 중"),
        h("span", {class: "mb-nowt"}, `${m.title || m.room_id} · ${m.trigger_ko || ""}${run.length > 1 ? ` 외 ${fmt.int(run.length - 1)}곳` : ""}`),
        h("span", {class: "muted", "aria-hidden": "true"}, "›")));
    } else put(now);
  }

  function render() {
    const d = st.d;
    if (st.gone) { put(list, ui.empty("회의 결론 보고판은 서버를 고친 뒤 보입니다")); put(foot); return; }
    if (!d) return;
    nMeet.update(d.n || 0); nDec.update(d.decided || 0); nDis.update(d.split || 0);
    const first = st.seen === null;
    const seen = st.seen || new Set();
    const lines = d.lines || [];
    if (!lines.length) {
      const nx = st.office && st.office.schedule && st.office.schedule.next;
      put(list, h("div", {class: "mb-empty"}, paperIcon("idle"),
        h("div", null, h("b", null, d.error ? "회의 기록을 읽지 못했습니다" : "오늘 끝난 회의가 아직 없습니다"),
          nx ? h("span", {class: "muted"}, `다음 정기 회의 ${nx.tomorrow ? "내일 " : ""}${nx.hhmm} · ${nx.trigger_ko}`) : null)));
    } else {
      put(list, lines.map((m) => row(m, !first && !seen.has(m.round_id))));
    }
    st.seen = new Set([...seen, ...lines.map((m) => m.round_id)]);
    put(foot, d.more ? h("a", {class: "mb-more", href: ctx.href("digest", "day")}, `오늘 끝난 회의 ${fmt.int(d.finished)}개 중 ${fmt.int(d.more)}개 더 보기 →`) : null);
  }

  feed(ctx, (d, gone) => { if (gone) st.gone = true; else if (d) st.d = d; render(); });
  card.office = (of) => { st.office = of || null; renderNow(); if (st.d && !(st.d.lines || []).length) render(); };
  return card;
}

/**
 * deskReport(ctx) -> the report on the 대표실 desk: a small pixel paper stack (one sheet per finished meeting today, at
 * most 4 drawn) and "보고서 N" that opens 회의 결론. Nothing while the server does not answer.
 */
export function deskReport(ctx) {
  const stack = h("span", {class: "mb-stack", "aria-hidden": "true"});
  const label = h("span", {class: "mb-dlabel"});
  const el = h("a", {class: "mb-desk", href: ctx.href("digest", "day"), hidden: true}, stack, label);
  let last = null;
  feed(ctx, (d) => {
    if (!d || d.ready === false) { el.hidden = true; return; }
    const n = d.finished || 0;
    el.hidden = false;
    el.title = n ? `오늘 끝난 회의 ${n}개의 결론 · 누르면 회의 결론` : "오늘 끝난 회의가 아직 없습니다";
    el.setAttribute("aria-label", `보고서 ${n}건. 누르면 회의 결론`);
    const sheets = Math.min(4, n);
    if (last !== n) {
      stack.replaceChildren(...Array.from({length: Math.max(1, sheets)}, (_, i) => paperIcon(n ? `s${i}` : "idle")));
      label.replaceChildren("보고서 ", h("b", {class: "num"}, fmt.int(n)));
      if (last != null && n > last) motion.flash(el, "accent");
      last = n;
    }
  });
  return el;
}
