// 회의 요약 (builder D, CONTRACT.md section 4 / INVENTORY section 11): code-only views of the agents' meetings, read-only.
// Tabs #/digest/<tab>: day (회의 결론, ?d=YYYY-MM-DD, ?r=<round> opens one row), staff (직원 성적표), week (주간 성적표),
// tf (봉 비교). update() switches tabs and days in place; each tab keeps what it loaded while the screen is open.
import {h, ui, motion, local, store} from "../core/pb.js";
import {makeDay} from "./digest-day.js";
import {makeStaff} from "./digest-staff.js";
import {makeWeek, makeTf} from "./digest-week.js";
import {makeBoard} from "./digest-board.js";

const TABS = [{id: "board", label: "결정 보드"}, {id: "day", label: "회의 결론"}, {id: "staff", label: "직원 성적표"}, {id: "week", label: "주간 성적표"}, {id: "tf", label: "봉 비교"}];
const MAKE = {board: makeBoard, day: makeDay, staff: makeStaff, week: makeWeek, tf: makeTf};
let cur = null;

export async function mount(el, ctx) {
  ctx.setTitle("회의 요약");
  const views = {};
  let tab = null;
  const seg = ui.seg(TABS, "board", (id) => ctx.go("digest", id), {label: "회의 요약 보기", scroll: true});
  const body = h("div", {class: "dg-body"});
  el.append(ui.screenHead("회의 요약", "코드가 정리한 회의 결론과 성적표 · 읽기 전용"), seg, body);

  async function show(params) {
    const want = TABS.some((t) => t.id === params.arg) ? params.arg : local.get("digest-tab", "board");
    local.set("digest-tab", want);
    seg.set(want);
    if (!views[want]) views[want] = MAKE[want](ctx);
    const v = views[want];
    if (want === "day" || want === "board") store.need("office", 30000).then((o) => v.setRoles && v.setRoles(o && o.roles)).catch(() => {});
    if (tab !== want) { tab = want; body.replaceChildren(v.el); motion.swap(body); }
    await v.show(params.query || {});
  }
  cur = show;
  ctx.track(() => { if (cur === show) cur = null; });
  ctx.every(120000, () => { const v = views[tab]; if (v && v.refresh) v.refresh(); }, {now: false});
  await show(ctx.params);
}

/** Same screen, new tab or day: switch in place. */
export function update(params) { if (cur) return cur(params); }

export function unmount() {}
