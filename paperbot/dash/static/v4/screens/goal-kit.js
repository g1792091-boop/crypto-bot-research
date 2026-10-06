// 목표 진척도 한 줄 (owners' round 2, 10/06): one slim line for the top of 홈 (and wherever the remodel places it):
// 오늘 5년 시험 (통과) · 동전보다 나은 새 매매법 후보 (운만으로 나올 수와 함께) · 판정 D-day. Every word is the server's
// code text (/api/v4/goal = paperbot/agents/goalline.py, the same line the evening Telegram can carry); the line links to
// 다음 버전 (#/nextver). Nothing here says pass or fail about a paper account (the verdict decides that).
//   goalLine(ctx, {cls})  -> a <div> that loads itself, refreshes every 5 minutes and stays one line (wraps on a phone)
// Its look: goal-kit.css (@imported by home.css).
import {h, ui} from "../core/pb.js";

export const GOAL_API = "/api/v4/goal";
const REFRESH_MS = 5 * 60 * 1000;

export function goalLine(ctx, o = {}) {
  const parts = h("span", {class: "gl-parts"}, ui.notYet("불러오는 중", "서버에 묻는 중"));
  const go = h("a", {class: "gl-go", href: ctx.href("nextver")}, "다음 버전 후보 →");
  const el = h("div", {class: ["gl", o.cls], role: "status", "aria-label": "목표 진척도"},
    h("span", {class: "gl-k"}, "🎯 목표 진척도"), parts, go);
  async function load() {
    let d = null;
    try { d = await ctx.api(GOAL_API); } catch { d = null; }
    if (!ctx.alive()) return;
    if (!d || !Array.isArray(d.parts)) {
      parts.replaceChildren(ui.notYet("수집 전", "서버가 아직 이 값을 보내지 않습니다"));
      return;
    }
    parts.replaceChildren(...d.parts.map((t, i) => h("span", {class: "gl-p", dataset: {i: String(i)}}, t)));
    el.title = d.caveat_ko || "";
  }
  load();
  if (ctx.every) ctx.every(REFRESH_MS, load);
  return el;
}
