// 실거래 › 안전: the live checks' own records (/api/v4/livebots/safety `checks`, livecheck.db read-only; paperbot/livecheck.py).
//   아침 점검  the morning check of the last 14 KST check days (09:00 to 09:00, run at 09:10): its level (확인할 것 N개 /
//             이상 없음 / 대조는 못 함), the loud reasons as its message lists them, a one-line summary (the paper's day,
//             each executor's day, halted or not, the replay comparison), and the whole message behind 펼치기; a day with no
//             record says so (점검 전 before 09:45, else 기록 없음), never a quiet day.
//   감시 알람  every alarm the 2-minute watcher sent: time, 긴급 / 조용한 알림, what it watches, the first line, the message
//             (더 보기), and whether it is still on, cleared at a time (then re-armed: it rings again if it comes back) or a
//             once-only note; the watcher's last pass (a watcher silent for 10 minutes says so).
// HONESTY: the records only; a file or table that is not there yet = 수집 전; unreadable = 못 읽음 + why.
import {h, put, ui, fmt, local, serverNow} from "../core/pb.js";
import {sourceState, acctTag} from "./livebots-kit.js";

const ago = (ms) => fmt.ago(ms, serverNow());

/** The level of one check day as a pill: 확인할 것 N개 (loud) / the quiet head's words (이상 없음, 대조는 못 함). */
export function dayPill(it) {
  if (it.state === "pending") return ui.pill("점검 전", "thin");
  if (it.state !== "ok") return ui.pill("기록 없음", "thin");
  if (it.level === "CRITICAL" || it.loud_n) return ui.pill(`확인할 것 ${fmt.int(it.loud_n)}개`, "bad");
  const tail = String(it.head || "").split(" · ").slice(1).join(" · ") || "이상 없음";
  return ui.pill(tail, tail === "이상 없음" ? "good" : "warn");
}

/** The day in one line: the paper's day, each executor's, the replay comparison. */
export function daySummary(sm) {
  if (!sm) return null;
  const parts = [];
  const p = sm.paper;
  if (p) parts.push(h("span", null, `페이퍼(연습) ${fmt.int(p.n)}번 ${fmt.int(p.wins)}승`, p.n ? h("b", {class: ["num", fmt.tone(p.pnl)]}, ` ${fmt.money(p.pnl, true)}`) : ""));
  else parts.push(h("span", {class: "muted"}, "페이퍼 못 읽음"));
  for (const x of sm.execs || []) {
    if (x.missing) { parts.push(h("span", {class: "muted"}, `${x.label} ${x.exists ? "못 읽음" : "시작 전"}`)); continue; }
    parts.push(h("span", null, `${x.label} ${fmt.int(x.n)}번`, x.n ? h("b", {class: ["num", fmt.tone(x.pnl)]}, ` ${fmt.money(x.pnl, true)}`) : "",
      x.halted ? h("b", {class: "down"}, " 멈춤") : ""));
  }
  parts.push(h("span", {class: sm.parity_flags ? "down" : "muted"}, sm.parity_error ? "대조 못 함" : sm.parity_flags ? `대조 차이 ${fmt.int(sm.parity_flags)}개` : "대조 같음"));
  return h("p", {class: "lb-msum"}, ...parts.flatMap((x, i) => (i ? [h("span", {class: "muted"}, " · "), x] : [x])));
}

/** One check day. */
export function dayRow(it) {
  const top = h("div", {class: "lb-mtop"}, h("b", {class: "lb-mday"}, it.day_ko || it.day), dayPill(it),
    it.sent === false ? ui.pill("텔레그램 못 보냄", "warn") : null);
  if (it.state !== "ok") return h("div", {class: "lb-mrow none", role: "listitem"}, top, h("p", {class: "note"}, it.why_ko || ""));
  return h("div", {class: "lb-mrow", role: "listitem"}, top,
    (it.reasons || []).length ? h("ul", {class: "lb-mwhy"}, it.reasons.map((r) => h("li", null, r))) : null,
    daySummary(it.summary),
    ui.disclosure("점검 글 보기", h("pre", {class: "lb-ctext"}, it.text || "")));
}

const W_STATE = {
  active: (f) => [`켜져 있음 · 마지막 확인 ${fmt.hm(f.last_ts)}`, "warn"],
  cleared: (f) => [`풀림 ${fmt.kst(f.cleared_ts)} · 다시 울릴 준비`, "good"],
  once: () => ["한 번만 알림", "thin"],
  unsent: () => ["못 보냄 · 다음 감시에서 다시", "warn"],
  unknown: () => ["지금 상태 기록 없음", "thin"],
};

/** One alarm the watcher sent. */
export function alarmRow(f) {
  const [txt, tone] = (W_STATE[f.state] || W_STATE.unknown)(f);
  const rest = String(f.text || "").split("\n").slice(1).join("\n");
  return h("div", {class: ["lb-al", f.state], role: "listitem"},
    h("div", {class: "lb-evtop"}, h("span", {class: "num muted"}, fmt.kst(f.ts)), ui.pill(f.level_ko || f.level, f.level === "CRITICAL" ? "bad" : "thin"),
      f.ex ? acctTag(f.ex) : null, h("span", {class: "lb-kind"}, f.kind_ko || f.kind), ui.pill(txt, tone)),
    h("p", {class: "lb-altitle"}, f.title || ""),
    rest ? ui.moreText(rest, 2) : null,
    f.state === "cleared" && f.recover ? h("p", {class: "note"}, `풀릴 때: ${f.recover}`) : null);
}

/** checksView(ctx) -> {el, set(checks)}: 아침 점검 and 감시 알람. */
export function checksView() {
  const st = {d: null, f: local.get("lb-wf", "all")};
  if (!["all", "active", "cleared"].includes(st.f)) st.f = "all";
  const mHead = h("div", {class: "lb-slot"});
  const mList = h("div", {class: "lb-mlist", role: "list"});
  const wHead = h("div", {class: "lb-whead"});
  const wSeg = ui.seg([{id: "all", label: "전부"}, {id: "active", label: "켜져 있음"}, {id: "cleared", label: "풀림"}], st.f,
    (id) => { st.f = id; local.set("lb-wf", id); drawWatch(true); }, {label: "알람 고르기"});
  const pg = ui.pager({size: 10, row: alarmRow, empty: () => (!st.d ? h("p", {class: "note"}, "불러오는 중")
    : (st.d.watch || {}).state === "ok" ? ui.empty(st.f === "all" ? "감시가 보낸 알람이 아직 없어요" : "이 조건의 알람이 없어요") : null)});
  const el = h("div", {class: "lb-checks"},
    ui.card({title: "아침 점검", sub: "매일 09:10 · 지난 14일 · 하루는 09:00~09:00 (한국)", cls: "lb-mcard"}, mHead, mList),
    ui.card({title: "감시 알람", sub: "2분마다 보는 감시가 보낸 알람 · 풀리면 다시 울릴 준비", cls: "lb-wcard", acts: [wSeg]}, wHead, pg.el));

  function drawMorning() {
    const m = st.d ? st.d.morning : null;
    if (!st.d) { put(mHead); put(mList, h("p", {class: "note"}, "불러오는 중")); return; }
    if (!m || m.state !== "ok") { put(mHead, sourceState(m || st.d, "아침 점검")); put(mList); return; }
    const items = m.items || [];
    put(mHead, h("p", {class: "lb-msum"}, h("b", null, `${fmt.int(items.filter((x) => x.state === "ok").length)}일 기록`),
      h("span", {class: "muted"}, ` · 확인할 것이 있던 날 ${fmt.int(m.loud_days)}일 · ${items.length ? `${items[items.length - 1].day_ko}부터` : ""}`)));
    put(mList, items.map(dayRow));
  }
  function drawWatch(user) {
    const w = st.d ? st.d.watch : null;
    if (!st.d) { put(wHead); pg.set(undefined); return; }
    if (!w || w.state !== "ok") { put(wHead, sourceState(w || st.d, "감시 알람")); pg.set([]); return; }
    put(wHead, h("p", {class: "lb-msum"}, h("b", null, `지금 켜진 알람 ${fmt.int(w.active_n)}개`),
      h("span", {class: "muted"}, ` · 보낸 알람 ${fmt.int(w.n)}번 · 마지막 감시 ${w.last_seen_ms ? `${fmt.hm(w.last_seen_ms)} (${ago(w.last_seen_ms)})` : "기록 없음"}`),
      w.stale ? ui.pill("감시가 10분 넘게 안 돌았어요", "warn") : null));
    pg.set((w.items || []).filter((f) => st.f === "all" || f.state === st.f), !user);
  }
  // the same answer again (the page asks every 30 s) changes nothing: an opened message stays open
  return {el, set(d) {
    const sig = d ? JSON.stringify(d) : "";
    if (d && sig === st.sig) return;
    st.sig = sig; st.d = d || null; drawMorning(); drawWatch(false);
  }};
}
