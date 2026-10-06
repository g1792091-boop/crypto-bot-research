// 회의실 · 오늘 회의 일정 (agents-ui): while no meeting runs, a clean day line of today's fixed meetings (Korea time):
// a 24-hour track with a mark per fixed meeting hour, the 지금 marker, each meeting's state (끝 / 진행 중 / 지남 · 기록 없음 /
// 예정, home-live.js timeline: from /api/office schedule + today's finished meetings) and a ticking countdown to the next
// one. Every hour is the server's own schedule (office.schedule.slots); meetings that open on their own (losses,
// incidents, owner posts, research) have no hour and are said so. Nothing here moves except the real clock.
import {h, ui, fmt} from "../core/pb.js";
import {timeline} from "./home-live.js";
import {countdown} from "./office-wall.js";

const STATE = {run: ["진행 중", "run"], done: ["끝", "done"], past: ["지남 · 기록 없음", "past"], next: ["예정", "next"]};

export function makeSched(ctx) {
  const cd = h("b", {class: "osc-cd num"}, "—");
  const cdWhat = h("span", {class: "osc-cdw"});
  const track = h("div", {class: "osc-track", role: "img", "aria-label": "오늘 회의 시각 (한국 시간)"});
  const list = h("ol", {class: "osc-list"});
  const el = h("section", {class: "osc", "aria-label": "오늘 회의 일정", hidden: true},
    h("div", {class: "osc-h"}, h("span", {class: "plate"}, "오늘 회의 일정"),
      h("span", {class: "osc-now"}, "지금 열린 회의 없음"), h("span", {class: "grow"}),
      h("span", {class: "osc-next"}, h("span", {class: "muted"}, "다음 정기 회의까지 "), cd, cdWhat)),
    track, list,
    h("p", {class: "osc-foot"}, "시각은 서버가 보낸 오늘 일정 (한국 시간) · 손실·사고·두 분 글·연구 회의는 정해진 시각 없이 조건이 되면 열립니다"));
  let office = null;
  const nowMark = h("i", {class: "osc-nowmark", "aria-hidden": "true"}, h("span", null, "지금"));

  function tick() {
    const nx = office && office.schedule && office.schedule.next;
    const t = countdown(nx && nx.at_ms);
    cd.textContent = t || "—";
    const day0 = fmt.kstMidnight(Date.now());
    nowMark.style.left = `${Math.min(100, Math.max(0, ((Date.now() - day0) / 86400000) * 100)).toFixed(2)}%`;
  }
  ctx.every(1000, tick);

  function paint() {
    const nx = office && office.schedule && office.schedule.next;
    cdWhat.textContent = nx ? ` · ${nx.tomorrow ? "내일 " : ""}${nx.hhmm} ${nx.trigger_ko || ""}` : "";
    const rows = timeline(office);
    const nextKey = nx && !nx.tomorrow ? nx.trigger : null;
    const hours = [0, 6, 12, 18, 24].map((x) => h("span", {class: "osc-hr", style: {left: `${(x / 24) * 100}%`}}, String(x).padStart(2, "0")));
    const marks = rows.map((s) => h("span", {class: ["osc-mark", STATE[s.state][1], s.trigger === nextKey ? "is-next" : ""],
      style: {left: `${(s.hour / 24) * 100}%`}, title: `${s.hhmm} ${s.trigger_ko} · ${STATE[s.state][0]}`}, h("i"), h("b", null, s.hhmm)));
    track.replaceChildren(h("i", {class: "osc-line", "aria-hidden": "true"}), ...hours, ...marks, nowMark);
    list.replaceChildren(...(rows.length ? rows.map((s) => h("li", {class: ["osc-li", STATE[s.state][1], s.trigger === nextKey ? "is-next" : ""]},
      h("b", {class: "num"}, s.hhmm),
      h("span", {class: "osc-lb"}, h("span", {class: "osc-ln"}, s.trigger_ko || s.trigger, h("small", null, ` · ${s.where || ""}`)), h("small", {class: "osc-lw"}, s.what)),
      s.state === "run" ? ui.livePill("진행 중") : h("span", {class: ["osc-st", STATE[s.state][1]]}, s.trigger === nextKey ? "다음" : STATE[s.state][0])))
      : [h("li", {class: "osc-li"}, ui.notYet("일정 수집 전"))]));
    tick();
  }
  return {
    el,
    /** o: /api/office. Shown only while no meeting runs. */
    update(o) {
      office = o || null;
      el.hidden = !office || !!(office.running || []).length || !office.schedule;
      if (!el.hidden) paint();
    },
  };
}
