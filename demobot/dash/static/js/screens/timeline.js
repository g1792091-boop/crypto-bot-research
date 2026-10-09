// #/timeline 타임라인 (CONTRACT 9.9, timeline.json): what happened to the demo lab, newest first: install and restarts,
// updates, the private plug-ins loaded, the warm-up, the live start, lines passing "우리 기준", confirmations passed or
// failed. Grouped by KST day, a filter by kind of event. Every 60 s. Text from the engine is text.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import * as K from "../live-kit.js";

const WHAT = {start: {ko: "시작", cls: "thin"}, update: {ko: "업데이트", cls: "accent"}, plugins: {ko: "비공개 매매법", cls: "thin"},
  warm: {ko: "과거 채우기", cls: "thin"}, live: {ko: "실시간 시작", cls: "accent"}, pass: {ko: "기준 통과", cls: "warn"},
  confirmed: {ko: "실전 후보", cls: "good"}, failed: {ko: "확인 실패", cls: "bad"}};
const GROUPS = [{id: "all", label: "전체"}, {id: "sys", label: "설치 · 업데이트", whats: ["start", "update", "plugins", "warm", "live"]},
  {id: "judge", label: "판정", whats: ["pass", "confirmed", "failed"]}];

export async function mount(el, ctx) {
  await K.needCss();
  ctx.setTitle("타임라인");
  let grp = GROUPS.some((g) => g.id === local.get("timeline-g")) ? local.get("timeline-g") : "all";
  const seg = ui.seg(GROUPS.map((g) => ({id: g.id, label: g.label})), grp, (v) => { grp = v; local.set("timeline-g", v); paint(); }, {label: "무엇"});
  const box = h("div"), count = h("p", {class: "note"});
  el.append(ui.screenHead("타임라인", "데모 랩에 있었던 일 (새것부터)"),
    ui.card({cls: "dl-controls"}, ui.field("보기", seg), count),
    ui.card({}, box),
    ui.note("기준 통과 = 한 줄(계좌 × 배수)이 '우리 기준'을 처음 넘은 때. 그 뒤 4주(거래 20건 이상) 확인 기간을 거쳐 실전 후보 또는 확인 실패가 됩니다. 실제 돈은 두 분이 정합니다."));

  let data = null, seen = null;
  function paint() {
    if (!data) return;
    if (isMissing(data)) { put(box, ui.missing("타임라인 자료")); count.textContent = ""; return; }
    const g = GROUPS.find((x) => x.id === grp);
    const evs = (data.events || []).filter((e) => !g.whats || g.whats.includes(e.what));
    count.textContent = `${fmt.int(evs.length)}개`;
    if (!evs.length) { put(box, ui.none("기록 없음")); return; }
    const days = [];
    for (const e of evs) {
      const d = fmt.date(e.t_ms);
      if (!days.length || days[days.length - 1].d !== d) days.push({d, items: []});
      days[days.length - 1].items.push(e);
    }
    put(box, h("div", {class: "lv-tl"}, days.map((day) => h("section", {class: "lv-tlday", "aria-label": day.d},
      h("h3", {class: "lv-tld"}, day.d),
      h("ol", {class: "lv-tlist"}, day.items.map((e) => {
        const w = WHAT[e.what] || {ko: String(e.what || "—"), cls: "thin"};
        return h("li", {class: ["lv-tli", `w-${w.cls}`]}, h("span", {class: "lv-tlt num"}, fmt.hm(e.t_ms)), ui.pill(w.ko, w.cls),
          h("span", {class: "lv-tlx"}, String(e.detail_ko ?? "")));
      }))))));
  }
  async function load() {
    let d;
    try { d = await ctx.api("/api/timeline"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!data) put(box, ui.errorBox(e, load));
      return;
    }
    const key = d && !isMissing(d) ? `${d.generated_ms}|${(d.events || []).length}` : "missing";
    if (key === seen) return;
    seen = key;
    data = d;
    paint();
  }
  await load();
  ctx.every(60000, load);
}
