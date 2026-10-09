// #/flow 흐름 (round 5; the rule bot's v4 흐름 for the demo lab): how the account kinds moved since the live start.
//   reading  one line in plain Korean: which kinds were above / below the coin flips over the last 7 days (참고)
//   누적      each kind's cumulative closed-trade P&L % (calendar.json days[].by_kind[].mean_pnl_pct, summed day by day:
//            the mean over the kind's lines of their P&L against the $1,000 start) and the all-lines line from
//            home.json pnl_total (every plain line together, as a % of lines x $1,000); labels at the right edge in the
//            current order, a tap / hover reads any day
//   막대      daily or weekly bars of one kind (or all lines), the coin flips of the same day as a dashed mark
//   달력      the P&L calendar (the terminal's, live-kit.js calendar()): all lines in $, or one kind in %
// calendar.json + home.json + accounts.json every 60 s (drawn again only when one of them changed). Read-only; a missing
// file shows "준비 중". HONESTY: every comparison with the coin flips is 참고 (never a pass or a fail); the lines draw
// themselves in once when they first arrive (never on a timer; off under reduced motion).
import {h, s, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {KIND_KO} from "../labels.js";
import {ticks} from "../g4.js";
import * as K from "../live-kit.js";

const DAY = 86400000, KST = 9 * 3600000;
const ORDER = ["fixed", "adaptive", "friend", "private", "flip"];
const SEED = 1000;
const dayStart = (key) => Date.parse(`${key}T00:00:00Z`) - KST;              // a KST day key -> its 00:00 in ms
const pp = (v, dec = 1) => (v == null || !Number.isFinite(v) ? "—" : fmt.pct(v, true, dec));
/** 이 / 가 after a Korean word (a final consonant takes 이). */
const josa = (w, a = "이", b = "가") => { const c = String(w).charCodeAt(String(w).length - 1); return c >= 0xac00 && c <= 0xd7a3 && (c - 0xac00) % 28 ? a : b; };

export async function mount(el, ctx) {
  await K.needCss();
  ctx.setTitle("흐름");
  const st = {cal: null, home: null, accts: null, seen: null, range: local.get("flow-range", "all"), bars: local.get("flow-bars", "day"),
    barKind: String(local.get("flow-bar-kind", "all")), calKind: String(local.get("flow-cal-kind", "all")), focus: null, drawn: false};

  // ---------------------------------------------------------------- skeleton
  const reading = h("p", {class: "k4-reading", role: "status"}, "준비 중");
  const rangeSeg = ui.seg([{id: "all", label: "처음부터"}, {id: "30", label: "최근 30일"}, {id: "7", label: "최근 7일"}], st.range,
    (v) => { st.range = v; local.set("flow-range", v); drawRace(); }, {label: "기간"});
  const raceBox = h("div", {class: "fl-race", role: "img", "aria-label": "종류별 누적 손익"});
  const raceRead = h("p", {class: "fl-read", "aria-live": "polite"});
  const legend = h("div", {class: "fl-legend"});
  const raceCard = ui.card({plate: "누적 손익", cls: "fl-racecard", acts: [rangeSeg]},
    h("h2", {class: "fl-title"}, "종류마다 ", h("em", null, "실시간 시작부터"), " 어떻게 움직였나"),
    raceBox, raceRead, legend,
    ui.note("선 = 종류 안 모든 줄(계좌 × 배수)의 닫힌 거래 손익을 날마다 더한 것 (시작 $1,000 대비 %, 종류 평균). 점선 회색 = 동전 던지기 (운과 견줄 기준). "
      + "점점이 흰 선 = 모든 줄 합계 (요약 파일 home.json의 한 시간 간격 잔고, 열린 포지션은 빼고 파산한 줄은 $1,000에서 다시 셈). 그래프를 누르거나 마우스를 올리면 그날 숫자."));
  const barSeg = ui.seg([{id: "day", label: "하루"}, {id: "week", label: "주"}], st.bars, (v) => { st.bars = v; local.set("flow-bars", v); drawBars(); }, {label: "막대 단위"});
  const barKindBox = h("div", {class: "fl-kinds"});
  const barBox = h("div", {class: "fl-bars", role: "img", "aria-label": "날마다 손익 막대"});
  const barRead = h("p", {class: "fl-read"});
  const barCard = ui.card({plate: "날마다 · 주마다", cls: "fl-barcard", acts: [barSeg]}, barKindBox, barBox, barRead,
    ui.note("막대 = 고른 종류의 그날(그 주) 닫힌 거래 손익 (줄 평균, 시작 $1,000 대비 %). 점선 눈금 = 같은 날 동전 던지기. 하루 성적은 운이 큽니다."));
  const calKindBox = h("div", {class: "fl-kinds"});
  const cal = K.calendar({href: ctx.href, cls: "fl-cal"});
  const calCard = ui.card({plate: "수익 달력", cls: "fl-calcard", acts: [cal.prev, cal.title, cal.next]}, calKindBox,
    h("div", {class: "fl-calbody"}, cal.grid, cal.day),
    ui.note("칸 색 = 그날 닫힌 거래 손익 (한국 시간 0시 기준) · 기록 없는 날은 점선 · 오늘은 진행 중"));
  el.append(ui.screenHead("흐름", "종류끼리 실시간 시작부터 어떻게 움직였나"), reading,
    raceCard, h("div", {class: "fl-two"}, barCard, calCard), K4.refNote(),
    h("p", {class: "assume once"}, "모의 · 실제 시세 · 닫힌 거래 손익은 수수료·슬리피지·펀딩 포함 · 주문 버튼 없음"));

  // ================================================================ data shaping
  const days = () => (st.cal && !isMissing(st.cal) ? st.cal.days || [] : []);
  const kindsHere = () => {
    const seen = new Set(days().flatMap((d) => (d.by_kind || []).map((k) => k.kind)));
    return ORDER.filter((k) => seen.has(k)).concat([...seen].filter((k) => !ORDER.includes(k)));
  };
  const kindVal = (d, k) => { const x = (d.by_kind || []).find((y) => y.kind === k); return x && Number.isFinite(Number(x.mean_pnl_pct)) ? Number(x.mean_pnl_pct) : null; };
  const nLines = () => {
    const a = st.accts && !isMissing(st.accts) ? (st.accts.accounts || []).length : null;
    const n = a || (st.home && !isMissing(st.home) && st.home.totals ? Number(st.home.totals.accounts) : 0);
    return n ? n * 4 : null;
  };
  /** the all-lines value of one day: P&L $ of every plain line / (lines x $1,000), in % */
  const allVal = (d) => { const n = nLines(); return n && Number.isFinite(Number(d.pnl_sum)) ? Number(d.pnl_sum) / (n * SEED) * 100 : null; };
  const valOf = (d, k) => (k === "all" ? allVal(d) : kindVal(d, k));

  // ================================================================ the reading line
  function paintReading() {
    const ds = days();
    if (!ds.length) { put(reading, h("b", null, "준비 중"), h("small", null, " · 날마다 기록이 아직 없습니다")); return; }
    const last = ds.slice(-7);
    const sum = (k) => last.reduce((a, d) => a + (kindVal(d, k) || 0), 0);
    if (!kindsHere().includes("flip")) { put(reading, "동전 던지기 기록이 아직 없어 비교할 수 없습니다"); return; }
    const flip = sum("flip");
    const rows = kindsHere().filter((k) => k !== "flip").map((k) => ({k, d: sum(k) - flip}));
    const above = rows.filter((r) => r.d > 0.05).sort((a, b) => b.d - a.d), below = rows.filter((r) => r.d < -0.05).sort((a, b) => a.d - b.d);
    const same = rows.filter((r) => Math.abs(r.d) <= 0.05);
    const names = (xs) => xs.map((r) => KIND_KO[r.k] || r.k).join(" · ");
    const n = last.length;
    const parts = [];
    if (above.length) parts.push(h("span", null, h("em", null, names(above)), josa(KIND_KO[above[above.length - 1].k] || "x"), ` 지난 ${n}일 동안 동전 던지기보다 위`));
    if (below.length) parts.push(h("span", null, parts.length ? ", " : "", names(below), josa(KIND_KO[below[below.length - 1].k] || "x", "은", "는"),
      above.length ? " 아래" : ` 지난 ${n}일 동안 동전 던지기보다 아래`));
    if (same.length) parts.push(h("span", null, parts.length ? ", " : "", names(same), josa(KIND_KO[same[same.length - 1].k] || "x", "은", "는"), " 비슷"));
    put(reading, ...parts, " ", K4.pill("", "ref", "참고: 운과 견줄 뿐, 판정이 아닙니다"),
      h("small", null, `${n}일 손익 합 (줄 평균 %): ${rows.sort((a, b) => b.d - a.d).map((r) => `${KIND_KO[r.k] || r.k} ${fmt.num(r.d, 1, true)}%p`).join(" · ")} (동전 던지기 대비)`));
  }

  // ================================================================ the cumulative chart
  function raceSeries() {
    const ds = days();
    const out = kindsHere().map((k) => {
      let c = 0;
      const pts = [];
      ds.forEach((d, i) => {
        const v = kindVal(d, k);
        if (i === 0) pts.push([dayStart(d.day), 0]);
        c += v || 0;
        pts.push([Math.min(dayStart(d.day) + DAY, Date.now()), c]);
      });
      return {id: k, label: KIND_KO[k] || k, pts};
    });
    const n = nLines(), tot = st.home && !isMissing(st.home) ? st.home.pnl_total || [] : [];
    if (n && tot.length > 1) out.push({id: "all", label: "모든 줄", pts: tot.filter((p) => Array.isArray(p) && Number.isFinite(Number(p[1])))
      .map((p) => [Number(p[0]), Number(p[1]) / (n * SEED) * 100])});
    return out.filter((x) => x.pts.length > 1);
  }
  const valueAt = (pts, t) => { let v = null; for (const p of pts) { if (p[0] > t) break; v = p[1]; } return v; };
  let raceGeo = null;
  function drawRace() {
    const all = raceSeries();
    if (!all.length) { put(raceBox, h("div", {class: "lv-pnone"}, h("b", null, "준비 중"), " · 날마다 기록이 아직 없습니다")); put(legend); raceRead.textContent = ""; return; }
    const tEnd = Math.max(...all.map((x) => x.pts[x.pts.length - 1][0]));
    const tStart = st.range === "all" ? Math.min(...all.map((x) => x.pts[0][0])) : tEnd - Number(st.range) * DAY;
    // a shorter range starts every line at 0 on its first day (what moved inside the range)
    const series = all.map((x) => {
      const base = st.range === "all" ? 0 : valueAt(x.pts, tStart) ?? 0;
      const pts = x.pts.filter((p) => p[0] >= tStart).map((p) => [p[0], p[1] - base]);
      if (st.range !== "all" && (!pts.length || pts[0][0] > tStart)) pts.unshift([tStart, 0]);
      return {...x, pts};
    });
    const W = Math.max(280, Math.round(raceBox.clientWidth || 600)), H = Math.round(raceBox.clientHeight || 320);
    const ts = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ts")) || 1;
    const gut = Math.round((W < 520 ? 100 : 128) * ts), x0 = Math.round(46 * ts), x1 = W - gut, y0 = 12, y1 = H - 24;
    const vals = series.flatMap((x) => x.pts.map((p) => p[1])).concat([0]);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    const pad = (hi - lo) * 0.08 || 1;
    lo -= pad; hi += pad;
    const X = (t) => x0 + (x1 - x0) * (t - tStart) / ((tEnd - tStart) || 1), Y = (v) => y1 - (y1 - y0) * (v - lo) / ((hi - lo) || 1);
    const kids = [];
    for (const v of ticks(lo, hi, 4)) {
      kids.push(s("line", {class: ["grid", Math.abs(v) < 1e-9 ? "zero" : ""], x1: x0, x2: x1, y1: Y(v).toFixed(1), y2: Y(v).toFixed(1)}),
        s("text", {class: "ax", x: x0 - 6, y: (Y(v) + 4).toFixed(1), "text-anchor": "end"}, `${fmt.num(v, Math.abs(hi - lo) < 10 ? 1 : 0, true)}%`));
    }
    const nd = Math.round((tEnd - tStart) / DAY), step = nd > 40 ? 14 : nd > 14 ? 7 : nd > 6 ? 2 : 1;
    for (let t = Math.ceil((tStart + KST) / DAY) * DAY - KST, i = 0; t <= tEnd; t += DAY, i++) {
      if (i % step) continue;
      kids.push(s("text", {class: "ax", x: X(t).toFixed(1), y: H - 6, "text-anchor": "middle"}, fmt.mmdd(t)));
    }
    for (const x of series) {
      const d = "M" + x.pts.map((p) => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" L");
      kids.push(s("path", {class: ["fl-ln", st.focus && st.focus !== x.id ? "dim" : "", st.focus === x.id ? "on" : ""], dataset: {kind: x.id}, d}));
      const last = x.pts[x.pts.length - 1];
      kids.push(s("circle", {class: "fl-head", dataset: {kind: x.id}, cx: X(last[0]).toFixed(1), cy: Y(last[1]).toFixed(1), r: 3.2}));
    }
    const cross = s("line", {class: "fl-cross", x1: 0, x2: 0, y1: y0, y2: y1, visibility: "hidden"});
    const hit = s("rect", {class: "fl-hit", x: x0, y: y0, width: Math.max(1, x1 - x0), height: y1 - y0});
    kids.push(cross, hit);
    const svg = s("svg", {class: "chart fl-svg", viewBox: `0 0 ${W} ${H}`, width: W, height: H}, kids);
    // labels at the right edge, in the current order (pushed apart so they never overlap)
    const labs = series.map((x) => ({x, v: x.pts[x.pts.length - 1][1]})).sort((a, b) => b.v - a.v);
    const LH = Math.round(36 * ts);
    let yy = -1e9;
    const placed = labs.map((l) => { const want = Y(l.v) - LH / 2; yy = Math.max(want, yy + LH + 2); return {...l, y: yy}; });
    const over = placed.length ? placed[placed.length - 1].y + LH - H : 0;
    if (over > 0) for (const p of placed) p.y -= over;
    const labEls = placed.map((p) => h("button", {type: "button", class: ["fl-lab", st.focus === p.x.id ? "on" : ""], dataset: {kind: p.x.id},
      style: {top: `${Math.max(0, p.y).toFixed(0)}px`, left: `${x1 + 8}px`, width: `${gut - 10}px`}, "aria-pressed": String(st.focus === p.x.id),
      title: `${p.x.label}: 누르면 이 선만 또렷하게`, onclick: () => { st.focus = st.focus === p.x.id ? null : p.x.id; drawRace(); }},
    h("span", {class: "fl-l1"}, h("i", {class: "k4-sw"}), p.x.label), h("b", {class: ["num", fmt.tone(p.v, pp(p.v))]}, pp(p.v))));
    put(raceBox, svg, h("div", {class: "fl-labs"}, labEls));
    if (!st.drawn) { st.drawn = true; K4.drawIn(svg, 900); }
    raceGeo = {X, x0, x1, tStart, tEnd, series, cross};
    const read = (px) => {
      const t = tStart + (px - x0) / ((x1 - x0) || 1) * (tEnd - tStart);
      cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("visibility", "visible");
      put(raceRead, h("b", null, `${fmt.mmdd(t)} ${fmt.hm(t)}`), " · ", series.map((x, i) => [i ? " · " : "", h("span", {class: "fl-rk", dataset: {kind: x.id}}, h("i", {class: "k4-sw"}), x.label, " "),
        h("b", {class: fmt.tone(valueAt(x.pts, t), pp(valueAt(x.pts, t)))}, pp(valueAt(x.pts, t)))]));
    };
    const pxOf = (e) => { const r = svg.getBoundingClientRect(); return Math.max(x0, Math.min(x1, (e.clientX - r.left) * (W / r.width))); };
    hit.addEventListener("pointermove", (e) => read(pxOf(e)));
    hit.addEventListener("pointerdown", (e) => read(pxOf(e)));
    hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); paintRaceRead(); });
    paintRaceRead();
    put(legend, ORDER.concat(["all"]).filter((k) => series.some((x) => x.id === k)).map((k) => h("span", {class: "fl-lg", dataset: {kind: k}}, h("i", {class: "k4-sw"}),
      k === "all" ? "모든 줄 (합계)" : k === "flip" ? "동전 던지기 (비교 기준)" : KIND_KO[k] || k)));
  }
  function paintRaceRead() {
    if (!raceGeo) return;
    const {series, tStart, tEnd} = raceGeo;
    const lead = series.filter((x) => x.id !== "all" && x.id !== "flip").map((x) => ({x, v: x.pts[x.pts.length - 1][1]})).sort((a, b) => b.v - a.v)[0];
    put(raceRead, h("b", null, `${fmt.mmdd(tStart)} → ${fmt.mmdd(tEnd)}`), lead ? [" · 지금 가장 위 ", h("b", null, lead.x.label), ` ${pp(lead.v)}`] : null,
      h("span", {class: "muted"}, " · 순서는 중간 기록일 뿐 판정이 아닙니다"));
  }

  // ================================================================ the bars
  function barData(k) {
    const ds = days();
    const flip = kindsHere().includes("flip") && k !== "flip";
    if (st.bars === "day") return ds.map((d) => ({t: dayStart(d.day), label: fmt.mmdd(dayStart(d.day)), v: valOf(d, k), f: flip ? kindVal(d, "flip") : null, n: 1}));
    const by = new Map();
    for (const d of ds) {
      const t = dayStart(d.day), wd = (new Date(t + KST).getUTCDay() + 6) % 7, wk = t - wd * DAY;
      const w = by.get(wk) || {t: wk, label: `${fmt.mmdd(wk)} 주`, v: 0, f: flip ? 0 : null, n: 0};
      w.v += valOf(d, k) || 0;
      if (flip) w.f += kindVal(d, "flip") || 0;
      w.n++;
      by.set(wk, w);
    }
    return [...by.values()].sort((a, b) => a.t - b.t);
  }
  function kindPicker(box, cur, onPick, withAll) {
    const opts = (withAll ? [{id: "all", label: withAll}] : []).concat(kindsHere().map((k) => ({id: k, label: KIND_KO[k] || k})));
    put(box, ui.seg(opts, opts.some((o) => o.id === cur) ? cur : opts[0] && opts[0].id, onPick, {label: "종류 고르기", cls: "scroll"}));
  }
  function drawBars() {
    kindPicker(barKindBox, st.barKind, (v) => { st.barKind = v; local.set("flow-bar-kind", v); drawBars(); }, "모든 줄");
    if (st.barKind !== "all" && !kindsHere().includes(st.barKind)) st.barKind = "all";
    const rows = barData(st.barKind);
    if (!rows.length) { put(barBox, h("div", {class: "lv-pnone"}, h("b", null, "준비 중"), " · 날마다 기록이 아직 없습니다")); barRead.textContent = ""; return; }
    const W = Math.max(280, Math.round(barBox.clientWidth || 560)), H = Math.round(barBox.clientHeight || 220);
    const x0 = 44, x1 = W - 6, y0 = 10, y1 = H - 22;
    const vals = rows.flatMap((r) => [r.v, r.f]).filter((v) => v != null).concat([0]);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    const pad = (hi - lo) * 0.08 || 1;
    lo -= pad; hi += pad;
    const Y = (v) => y1 - (y1 - y0) * (v - lo) / ((hi - lo) || 1);
    const bw = (x1 - x0) / rows.length;
    const kids = [];
    for (const v of ticks(lo, hi, 4)) kids.push(s("line", {class: ["grid", Math.abs(v) < 1e-9 ? "zero" : ""], x1: x0, x2: x1, y1: Y(v).toFixed(1), y2: Y(v).toFixed(1)}),
      s("text", {class: "ax", x: x0 - 6, y: (Y(v) + 4).toFixed(1), "text-anchor": "end"}, `${fmt.num(v, Math.abs(hi - lo) < 10 ? 1 : 0, true)}%`));
    const every = Math.max(1, Math.ceil(rows.length / Math.max(2, Math.floor((x1 - x0) / 56))));
    rows.forEach((r, i) => {
      const x = x0 + i * bw, w = Math.max(1, bw * 0.72), cx = x + bw / 2;
      if (r.v != null) {
        const ya = Y(Math.max(0, r.v)), yb = Y(Math.min(0, r.v));
        kids.push(s("rect", {class: ["fl-bar", r.v >= 0 ? "up" : "down"], x: (cx - w / 2).toFixed(1), y: ya.toFixed(1), width: w.toFixed(1), height: Math.max(1, yb - ya).toFixed(1)},
          s("title", null, `${r.label}: ${pp(r.v, 2)}${r.f != null ? ` · 동전 던지기 ${pp(r.f, 2)}` : ""}`)));
      }
      if (r.f != null) kids.push(s("line", {class: "fl-flip", x1: (cx - w / 2 - 1).toFixed(1), x2: (cx + w / 2 + 1).toFixed(1), y1: Y(r.f).toFixed(1), y2: Y(r.f).toFixed(1)}));
      if (i % every === 0) kids.push(s("text", {class: "ax", x: cx.toFixed(1), y: H - 6, "text-anchor": "middle"}, st.bars === "day" ? r.label : r.label.replace(" 주", "")));
    });
    put(barBox, s("svg", {class: "chart fl-svg", viewBox: `0 0 ${W} ${H}`, width: W, height: H}, kids));
    const up = rows.filter((r) => r.v > 0).length, dn = rows.filter((r) => r.v < 0).length;
    const beat = rows.filter((r) => r.f != null && r.v != null && r.v > r.f).length, cmp = rows.filter((r) => r.f != null && r.v != null).length;
    const last = rows[rows.length - 1];
    put(barRead, h("b", null, st.barKind === "all" ? "모든 줄" : KIND_KO[st.barKind] || st.barKind), ` · ${st.bars === "day" ? "날" : "주"} ${fmt.int(rows.length)}개 중 오른 ${fmt.int(up)} · 내린 ${fmt.int(dn)}`,
      cmp ? [" · 동전 던지기보다 위 ", h("b", null, `${fmt.int(beat)}/${fmt.int(cmp)}`), " ", K4.pill("", "ref")] : null,
      ` · 마지막 ${st.bars === "day" ? "날" : "주"} ${last.label} `, h("b", {class: fmt.tone(last.v, pp(last.v, 2))}, pp(last.v, 2)),
      st.bars === "week" && last.n < 7 ? h("span", {class: "muted"}, ` (진행 중, ${fmt.int(last.n)}일)`) : null);
  }

  // ================================================================ the calendar's value
  function paintCal() {
    kindPicker(calKindBox, st.calKind, (v) => { st.calKind = v; local.set("flow-cal-kind", v); paintCal(); }, "모든 줄 ($)");
    if (st.calKind !== "all" && !kindsHere().includes(st.calKind)) st.calKind = "all";
    if (st.calKind === "all") cal.mode({value: (d) => Number(d.pnl_sum) || 0, text: K.shortNum, label: "모든 줄 손익 합 $"});
    else {
      const k = st.calKind;
      cal.mode({value: (d) => kindVal(d, k) || 0, text: (v) => `${fmt.num(v, Math.abs(v) < 10 ? 1 : 0, true)}%`, label: `${KIND_KO[k] || k} 줄 평균`});
    }
    cal.set(st.cal);
  }

  // ================================================================ load
  async function load() {
    const get = (p) => ctx.api(p).catch((e) => (e && e.name === "AbortError" ? Promise.reject(e) : e));
    let c, hm, ac;
    try { [c, hm, ac] = await Promise.all([get("/api/calendar"), get("/api/home"), get("/api/accounts")]); } catch (e) { return; }
    if (!ctx.alive()) return;
    if (c instanceof Error) { if (!st.cal) put(reading, ui.errorBox(c, load)); return; }
    const key = [c, hm, ac].map((x) => (x && !(x instanceof Error) ? x.generated_ms : "e")).join("|");
    if (key === st.seen) return;
    st.seen = key;
    st.cal = c; st.home = hm instanceof Error ? null : hm; st.accts = ac instanceof Error ? null : ac;
    paintReading(); drawRace(); drawBars(); paintCal();
  }
  // the charts are drawn at their box's real width: again when it changes (a window resize, the 글자 크기 switch)
  let lastW = 0, rt = 0;
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => {
    const w = Math.round(raceBox.clientWidth);
    if (Math.abs(w - lastW) < 2) return;
    lastW = w;
    clearTimeout(rt);
    rt = setTimeout(() => { if (st.cal) { drawRace(); drawBars(); } }, 120);
  }) : null;
  if (ro) ro.observe(raceBox);
  await load();
  ctx.every(60000, load);
  return () => { if (ro) ro.disconnect(); clearTimeout(rt); };
}

