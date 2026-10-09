// #/timeline 타임라인 (CONTRACT 9.9, timeline.json): what happened to the demo lab, newest first: install and restarts,
// updates, the private plug-ins loaded, the warm-up, the live start, lines passing "우리 기준", confirmations passed or
// failed. Grouped by KST day, a filter by kind of event. Every 60 s. Text from the engine is text.
// Round 5 stage 2B (the rule bot's v4 alert / timeline list look): four stat cards (all events, passes, candidates,
// failed confirmations) that count to new values, the filter in one bar, each day under its ◆ date plate with one v4
// time-stamped row per event on a line with a coloured dot (the kind's colour, the kind's name always written).
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
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
  const seg = ui.seg(GROUPS.map((g) => ({id: g.id, label: g.label})), grp, (v) => { grp = v; local.set("timeline-g", v); paint(true); }, {label: "무엇"});
  const box = h("div"), count = h("span", {class: "muted s2-count"});
  const nAll = K4.liveNum(null, {format: (v) => fmt.int(v), flash: "accent"});
  const nPass = K4.liveNum(null, {format: (v) => fmt.int(v), flash: "accent"});
  const nConf = K4.liveNum(null, {format: (v) => fmt.int(v), flash: "accent"});
  const nFail = K4.liveNum(null, {format: (v) => fmt.int(v), flash: "accent"});
  const allSub = h("span", {class: "s"}, "—");
  const stats = h("div", {class: "stats s4 s2-stats"},
    K4.stat("있었던 일", nAll, allSub), K4.stat("기준 통과", nPass, "한 줄이 '우리 기준'을 처음 넘은 때", "warn"),
    K4.stat("실전 후보", nConf, "확인 기간을 넘은 줄", "good"), K4.stat("확인 실패", nFail, "확인 기간을 못 넘은 줄", "bad"));
  el.append(ui.screenHead("타임라인", "데모 랩에 있었던 일 (새것부터)"), stats,
    ui.card({plate: "있었던 일", cls: "s2-tlcard", acts: count},
      h("div", {class: "k4-bar s2-rgbar"}, h("span", {class: "k4-barg s2-g"}, h("span", {class: "k4-k"}, "보기"), seg)), box),
    ui.note("기준 통과 = 한 줄(계좌 × 배수)이 '우리 기준'을 처음 넘은 때. 그 뒤 4주(거래 20건 이상) 확인 기간을 거쳐 실전 후보 또는 확인 실패가 됩니다. 실제 돈은 두 분이 정합니다."));

  let data = null, seen = null;
  function paint(user) {
    if (!data) return;
    if (isMissing(data)) {
      put(box, ui.missing("타임라인 자료")); count.textContent = "";
      for (const n of [nAll, nPass, nConf, nFail]) n.update(null);
      allSub.textContent = "준비 중";
      return;
    }
    const all = data.events || [];
    nAll.update(all.length);
    nPass.update(all.filter((e) => e.what === "pass").length);
    nConf.update(all.filter((e) => e.what === "confirmed").length);
    nFail.update(all.filter((e) => e.what === "failed").length);
    const newest = all.reduce((m, e) => Math.max(m, Number(e.t_ms) || 0), 0);
    allSub.textContent = newest ? `가장 새것 ${fmt.kst(newest)}` : "기록 없음";
    const g = GROUPS.find((x) => x.id === grp);
    const evs = all.filter((e) => !g.whats || g.whats.includes(e.what));
    count.textContent = `${fmt.int(evs.length)}개`;
    if (!evs.length) { put(box, ui.none("기록 없음")); return; }
    const days = [];
    for (const e of evs) {
      const d = fmt.date(e.t_ms);
      if (!days.length || days[days.length - 1].d !== d) days.push({d, items: []});
      days[days.length - 1].items.push(e);
    }
    put(box, h("div", {class: "lv-tl s2-tl"}, days.map((day) => h("section", {class: "lv-tlday", "aria-label": day.d},
      h("h3", {class: "lv-tld s2-tld"}, ui.plate(day.d), h("span", {class: "muted"}, `${fmt.int(day.items.length)}개`)),
      h("ol", {class: "lv-tlist"}, day.items.map((e) => {
        const w = WHAT[e.what] || {ko: String(e.what || "—"), cls: "thin"};
        return h("li", {class: ["lv-tli", "s2-tli", `w-${w.cls}`]}, h("span", {class: "lv-tlt num"}, fmt.hm(e.t_ms)), ui.pill(w.ko, w.cls),
          h("span", {class: "lv-tlx"}, String(e.detail_ko ?? "")));
      }))))));
    if (user) K4.swap(box);
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
    paint(false);
  }
  await load();
  ctx.every(60000, load);
}
