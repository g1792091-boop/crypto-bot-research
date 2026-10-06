// 30칸 픽셀 길 (wave 3, ranked #6): the 30-day run as a road of day cells, for the home headline card (in place of the
// progress bar) and the top of 판정. One cell per Korea-time day of the current season (the start day through the
// verdict day, /api/v4/flow/calendar): a past day is tinted by how much the 기존 36's median balance moved that day
// (up / down colour, light; 참고: never a pass or a fail), a day without a single record is hatched (기록 없음, never a
// zero), the days ahead are dashed. Today carries the two owners' pixel figures; marks: the verdict flag, US macro
// releases (/api/events), the day the observation ends (proposals may start), busts that day (all groups, counted).
// Tapping a past day opens that day's 하이라이트 (#/story/<day>). When the day really changes while the page is open,
// the figures take one step (reduced motion: none). Asked every 5 minutes (paused while hidden); its look: road-kit.css.
import {h, s, put, ui, fmt, figure, motion} from "../core/pb.js";

const CAL_API = "/api/v4/flow/calendar";
const EV_API = "/api/events?days_back=40&days_ahead=40";
const REFRESH_MS = 5 * 60 * 1000;
const FULL_CHG = 0.03;             // a day's median move of 3 % or more gets the full tint

function ensureCss() {
  if (document.querySelector("link[data-road-kit]")) return;
  document.head.append(h("link", {rel: "stylesheet", href: new URL("road-kit.css", import.meta.url).href, dataset: {roadKit: "1"}}));
}

// a 7 x 9 pixel flag (fill = currentColor)
const flag = () => s("svg", {class: "proad-flag", viewBox: "0 0 7 9", width: "10", height: "13", fill: "currentColor", "shape-rendering": "crispEdges", "aria-hidden": "true"},
  s("rect", {x: 0, y: 0, width: 1, height: 9, class: "pole"}), s("rect", {x: 1, y: 0, width: 6, height: 2}), s("rect", {x: 1, y: 2, width: 4, height: 2}));

const kstDay = (ms) => { const k = new Date(ms + 9 * 3600000); return k.toISOString().slice(0, 10); };

/** The day's marks: [{k: "ev"|"obs"|"bust", t: text}] */
function marksOf(e, ctxd) {
  const out = [];
  const evs = (ctxd.events || []).filter((x) => kstDay(x.ts_ms) === e.d);
  if (evs.length) out.push({k: "ev", t: evs.map((x) => `${x.name_ko || x.kind} ${fmt.hm(x.ts_ms)}`).join(", ")});
  if (ctxd.obsDay && ctxd.obsDay === e.d) out.push({k: "obs", t: "관찰 기간 끝 · 이때부터 에이전트가 새 계좌를 제안할 수 있음"});
  const busts = e.g ? Object.values(e.g).reduce((a, x) => a + (x && x.busts ? x.busts : 0), 0) : 0;
  if (busts) out.push({k: "bust", t: `파산 ${busts}개 (모든 묶음)`});
  return out;
}

/** pixelRoad(ctx, {card}) -> element. card: wrap in its own card with a plate and the legend (판정 screen). */
export function pixelRoad(ctx, opts = {}) {
  ensureCss();
  const st = {cal: null, events: null, summary: null, today: null, err: null};
  const road = h("div", {class: "proad-road", role: "list", "aria-label": "30일 길: 하루 한 칸"});
  const head = h("div", {class: "proad-head"});
  const legend = h("p", {class: "proad-legend"},
    h("span", null, h("i", {class: "proad-sw up"}), h("i", {class: "proad-sw down"}), " 그날 기존 36 중앙값이 오른·내린 정도 (참고)"),
    h("span", null, h("i", {class: "proad-mk ev"}), " 미국 지표"),
    h("span", null, h("i", {class: "proad-mk obs"}), " 제안 시작"),
    h("span", null, h("i", {class: "proad-mk bust"}), " 파산"),
    h("span", null, h("i", {class: "proad-sw none"}), " 기록 없음"));
  const mini = h("p", {class: "proad-legend proad-mini"}, "한 칸 = 하루 · 색 = 그날 기존 36 중앙값이 오른·내린 정도 (참고) · 누르면 그날 하이라이트");
  const box = h("div", {class: "proad" + (opts.card ? " proad-in-card" : " proad-compact")}, opts.card ? head : null, road, opts.card ? legend : mini);
  const root = opts.card ? ui.card({plate: "30일 길", cls: "proad-card", acts: [h("a", {class: "btn-line", href: ctx.href("flow")}, "날짜별 →")]}, box, ui.note("지난 칸을 누르면 그날의 하이라이트가 열립니다."))
    : box;
  road.append(motion.shimmer(1));

  function render() {
    const c = st.cal;
    if (!c) return;
    if (!c.ready || !(c.days || []).length) {
      put(head, h("span", {class: "muted"}, "봇이 첫 계좌를 만들면 길이 생깁니다."));
      put(road, ...Array.from({length: 31}, () => h("span", {class: "proad-c proad-future", role: "listitem"}, h("span", {class: "proad-fig"}), h("span", {class: "proad-sq"}))));
      return;
    }
    const s0 = st.summary || {};
    const obs = s0.observe_until ? kstDay(s0.observe_until - 1) : null;
    const ctxd = {events: st.events, obsDay: obs};
    const days = c.days;
    // today = the server's KST day (a today without a single record is still today, never "after the verdict")
    let ti = days.findIndex((e) => e.d === c.today);
    if (ti < 0) ti = days.findIndex((e) => e.state === "today");
    const moved = st.today != null && ti > st.today;
    st.today = ti;
    const last = days[days.length - 1];
    // D+n is the checkpoint clock's day (summary.restart, the same number as the top chip and the home card); the
    // cells are Korea-time dates, so they carry dates, never a second day count that could disagree with D+n
    const rs = s0.restart && s0.restart.ready ? s0.restart : null;
    const now = ti >= 0 ? (rs ? `D+${rs.day}` : "오늘") : "판정 뒤";
    put(head, h("b", null, now), h("span", {class: "muted"}, ` · ${days.length}칸 중 지난 ${Math.max(0, ti)}칸`),
      h("span", {class: "grow"}), h("span", {class: "proad-target"}, flag(), ` 판정 ${fmt.date(c.verdict_ts || last.ts)}`));
    road.style.setProperty("--n", String(days.length));
    put(road, days.map((e, i) => {
      const chg = e.g && e.g.core ? e.g.core.chg : null;
      const cls = ["proad-c", "proad-" + e.state];
      let a = 0;
      if (e.state === "done" || e.state === "today") {
        if (chg != null && Math.abs(chg) > 1e-6) { cls.push(chg > 0 ? "proad-up" : "proad-down"); a = Math.min(1, Math.abs(chg) / FULL_CHG); }
        else cls.push("proad-flat");
      }
      if (e.verdict) cls.push("proad-goal");
      const mk = e.state === "future" && !e.verdict ? marksOf(e, ctxd).filter((m) => m.k !== "bust") : marksOf(e, ctxd);
      const word = e.state === "future" ? "앞으로" : e.state === "empty" ? "기록 없음" : chg != null ? `기존 36 중앙값 ${fmt.pct(chg, 2)} (참고)` : "변화 없음";
      const label = `${fmt.date(e.ts)}${i === ti ? " (오늘)" : ""} · ${word}${e.verdict ? " · 판정 날" : ""}${mk.length ? " · " + mk.map((m) => m.t).join(" · ") : ""}`;
      const kids = [
        h("span", {class: "proad-fig"}, i === ti ? [figure({kind: "owner", size: 10, cls: moved ? "proad-step" : ""}), figure({kind: "owner", size: 10, i: 1, cls: moved ? "proad-step" : ""})]
          : e.verdict ? flag() : null),
        h("span", {class: "proad-sq", style: {"--a": a.toFixed(3)}}),
        h("span", {class: "proad-mks"}, mk.map((m) => h("i", {class: "proad-mk " + m.k}))),
      ];
      const go = e.state !== "future";
      return go ? h("a", {class: cls.join(" "), role: "listitem", href: ctx.href("story", e.d), title: label, "aria-label": label + ". 누르면 그날 하이라이트"}, kids)
        : h("span", {class: cls.join(" "), role: "listitem", title: label, "aria-label": label}, kids);
    }));
  }

  async function load() {
    try {
      const [cal, ev] = await Promise.all([ctx.api(CAL_API), st.events ? Promise.resolve({events: st.events}) : ctx.api(EV_API).catch(() => ({events: []}))]);
      if (!ctx.alive()) return;
      st.cal = cal; st.events = (ev && ev.events) || [];
      render();
    } catch (e) {
      if (!ctx.alive()) return;
      if (!st.cal) put(road, h("span", {class: "muted proad-err"}, e && e.status === 404 ? "길 그림 준비 전" : "길을 불러오지 못했습니다 (잠시 뒤 다시)."));
    }
  }
  ctx.watch("summary", (v) => { if (v) { const first = !st.summary; st.summary = v; if (!first || st.cal) render(); } });
  ctx.every(REFRESH_MS, load, {now: true});
  root.dataset.days = "road";
  return root;
}

