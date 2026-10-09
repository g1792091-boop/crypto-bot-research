// #/vs5y 5년 대비 (CONTRACT 9.6): each fixed account (the same setting and exit live and in the 5-year study; all coins
// together): its live mean R next to each 5-year period's mean R, the gap to 2024-26 and the engine's note ("5년 시험과
// 비슷" ...). A sortable table and a dot chart (one row per account: a dot per period, the live one larger, a line from
// 2024-26 to live = the gap). vs5y.json every 5 min. SVG through s() (no markup).
import {h, s, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {tfKo, shortOf} from "../labels.js";
import {fewNote, FEW, ticks} from "../g4.js";

const PER = [["2020", "2020"], ["2021-23", "21–23"], ["2024-26", "24–26"], ["2020-03", "코로나"], ["2022-05", "루나"], ["2022-11", "FTX"]];
const DOTS = [["2020", "p1", "circle"], ["2021-23", "p2", "square"], ["2024-26", "p3", "tri"]];
const SORTS = [{id: "gap", label: "차이"}, {id: "live", label: "실시간 R"}, {id: "n", label: "거래 수"}, {id: "name", label: "이름"}];

export async function mount(el, ctx) {
  ctx.setTitle("5년 대비");
  let sort = local.get("vs5y-sort", "gap");
  if (!SORTS.some((x) => x.id === sort)) sort = "gap";
  let desc = local.get("vs5y-desc", false) === true;
  const sum = h("div");
  const chart = h("div", {class: "g4-dots"});
  const legend = h("div");
  const tbl = h("div");
  const sortSeg = ui.seg(SORTS, sort, (v) => { sort = v; local.set("vs5y-sort", v); paint(); }, {label: "줄 세우기"});
  const dirBtn = ui.toggle("큰 것부터", desc, (v) => { desc = v; local.set("vs5y-desc", v); paint(); }, "순서 뒤집기");
  el.append(ui.screenHead("5년 대비", "고정 계좌: 실시간 성적이 5년 시험과 비슷한가"),
    ui.card({plate: "읽는 법"}, h("ul", {class: "dl-ul"},
      h("li", null, "고정 계좌는 설정과 청산을 바꾸지 않으니, 5년 연구에서 같은 설정·같은 청산이 낸 평균 R과 바로 비교할 수 있습니다."),
      h("li", null, "차이 = 실시간 평균 R − 2024~26년 평균 R. 차이가 ±0.1R 안이면 '비슷'입니다."),
      h("li", null, "실시간이 훨씬 나쁘면 시장이 바뀌었거나 5년 시험이 운이 좋았을 수 있습니다. 훨씬 좋아도 운일 수 있습니다 (특히 거래가 30건보다 적을 때)."),
      h("li", null, "코로나 · 루나 · FTX는 폭락이 있던 한 달씩입니다: 급한 장에서 어땠는지 참고로 봅니다."))),
    sum,
    ui.card({plate: "점 그림", sub: "줄마다 5년 기간의 평균 R과 실시간 평균 R"}, legend, chart),
    ui.card({plate: "표", acts: h("div", {class: "row wrap"}, sortSeg, dirBtn)}, tbl),
    ui.note("평균 R은 수수료 후, 코인 7개를 합친 값입니다. 실시간은 20배 줄의 닫힌 거래로 셉니다."));

  let data = null, seen = null, ro = null, lastW = 0;
  async function load() {
    let d;
    try { d = await ctx.api("/api/vs5y"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!data) put(tbl, ui.errorBox(e, load));
      return;
    }
    if (d && d.generated_ms === seen && data) return;
    seen = d && d.generated_ms;
    data = d;
    paint();
  }

  function sorted() {
    const rows = [...(data.rows || [])];
    const key = {gap: (r) => r.gap_R, live: (r) => r.live && r.live.mean_R, n: (r) => r.live && r.live.n, name: (r) => r.name || r.id}[sort];
    rows.sort((a, b) => {
      const x = key(a), y = key(b);
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      const c = typeof x === "string" ? x.localeCompare(y, "ko") : x - y;
      return desc ? -c : c;
    });
    return rows;
  }

  function paint() {
    if (!data || isMissing(data)) { put(sum); put(chart, ui.missing("5년 대비 자료")); put(legend); put(tbl); return; }
    const rows = sorted();
    const word = (r) => String(r.note_ko || "");
    put(sum, h("div", {class: "stats dl-s4"},
      ui.stat("고정 계좌", fmt.int(rows.length), `거래 30건 미만 ${fmt.int(rows.filter((r) => !r.live || Number(r.live.n) < FEW).length)}개`),
      ui.stat("비슷", fmt.int(rows.filter((r) => word(r).includes("비슷")).length), "차이 ±0.1R 안"),
      ui.stat("5년보다 나쁨", fmt.int(rows.filter((r) => word(r).includes("나쁨")).length), null, "dl-bad"),
      ui.stat("5년보다 좋음", fmt.int(rows.filter((r) => word(r).includes("좋음")).length), null, "dl-good")));
    put(tbl, ui.table([
      {label: "계좌", l: true, cls: "dl-c2", get: (r) => h("span", {class: "dl-kn"}, h("a", {href: ctx.href("account", r.id)}, r.name || r.id),
        h("small", {class: "mono muted"}, `${r.setting_ko || ""} · ${r.exit_ko || ""}`))},
      {label: "실시간", get: (r) => h("span", {class: "dl-5y"}, ui.signed(fmt.r(r.live && r.live.mean_R), fmt.tone(r.live && r.live.mean_R, fmt.r(r.live && r.live.mean_R)), "b"),
        h("small", {class: "muted"}, `${fmt.int(r.live && r.live.n)}건 · 승률 ${fmt.ratio(r.live && r.live.win_rate, 0)}`))},
      ...PER.map(([p, ko], i) => ({label: ko, cls: i === 0 ? "dl-5y0" : "", get: (r) => {
        const x = (r.past || {})[p];
        if (!x || x.mean_R == null) return h("span", {class: "muted"}, "—");
        return h("span", {class: "dl-5y"}, ui.signed(fmt.r(x.mean_R), fmt.tone(x.mean_R, fmt.r(x.mean_R))), h("small", {class: "muted"}, `${fmt.int(x.n)}건`));
      }})),
      {label: "차이 (실시간 − 24–26)", get: (r) => ui.signed(fmt.r(r.gap_R), fmt.tone(r.gap_R, fmt.r(r.gap_R)), "b")},
      {label: "한마디", l: true, cls: "dl-wrap2", get: (r) => h("span", {class: "dl-kn"}, word(r) || "—", /건/.test(word(r)) ? null : fewNote(r.live && r.live.n))},
    ], rows, {cls: "g4-vs"}));
    put(legend, h("div", {class: "hm-legend"},
      DOTS.map(([p, cls, shape]) => h("span", {class: "dl-lg"}, s("svg", {width: 14, height: 14, viewBox: "0 0 14 14", class: ["g4-dot", cls], "aria-hidden": "true"},
        dot(shape, 7, 7, 4.5)), PER.find((x) => x[0] === p)[1])),
      h("span", {class: "dl-lg"}, s("svg", {width: 14, height: 14, viewBox: "0 0 14 14", class: "g4-dot live", "aria-hidden": "true"}, dot("diamond", 7, 7, 5.5)), "실시간"),
      h("span", {class: "dl-lg"}, h("i", {class: "g4-sw gap"}), "차이 (24–26 → 실시간)")));
    drawDots(rows);
  }

  function drawDots(rows) {
    const W = Math.max(300, Math.floor(chart.clientWidth || 600));
    lastW = W;
    const nameW = W < 560 ? 104 : 190;
    const rowH = 26, pad = {t: 8, b: 30, r: 14};
    const H = pad.t + rows.length * rowH + pad.b;
    const vals = rows.flatMap((r) => [r.live && r.live.mean_R, ...DOTS.map(([p]) => ((r.past || {})[p] || {}).mean_R)]).filter((v) => v != null && Number.isFinite(Number(v))).map(Number);
    if (!vals.length) { put(chart, ui.none("기록 없음")); return; }
    let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
    const span = hi - lo || 0.2;
    lo -= span * 0.06; hi += span * 0.06;
    const X = (v) => nameW + (v - lo) / (hi - lo) * (W - nameW - pad.r);
    const kids = [];
    for (const t of ticks(lo, hi, W < 560 ? 4 : 6)) {
      kids.push(s("line", {x1: X(t), x2: X(t), y1: pad.t, y2: H - pad.b, class: t === 0 ? "g4-zero" : "g4-gridl"}),
        s("text", {x: X(t), y: H - pad.b + 16, class: "g4-tick", "text-anchor": "middle"}, fmt.num(t, 2, true)));
    }
    kids.push(s("text", {x: W - pad.r, y: H - 4, class: "g4-axl", "text-anchor": "end"}, "평균 R →"));
    rows.forEach((r, i) => {
      const y = pad.t + i * rowH + rowH / 2;
      const name = r.name || r.id;
      const sub = {def: "기본", fr: "친구", pk: "1등"}[String(r.id).split("-")[1]];
      const short = W < 560 && sub ? `${shortOf(r.strategy)} ${sub} ${tfKo(r.tf)}` : name;
      kids.push(s("line", {x1: nameW, x2: W - pad.r, y1: y, y2: y, class: "g4-rowl"}),
        s("text", {x: nameW - 8, y: y + 4, class: "g4-rown", "text-anchor": "end"}, short));
      const ref = ((r.past || {})["2024-26"] || {}).mean_R, live = r.live ? r.live.mean_R : null;
      if (ref != null && live != null) kids.push(s("line", {x1: X(ref), x2: X(live), y1: y, y2: y, class: ["g4-gapl", Number(live) >= Number(ref) ? "up" : "down"]}));
      for (const [p, cls, shape] of DOTS) {
        const v = ((r.past || {})[p] || {}).mean_R;
        if (v == null) continue;
        kids.push(s("g", {class: ["g4-dot", cls]}, s("title", null, `${name} · ${PER.find((x) => x[0] === p)[1]}: ${fmt.r(v)}`), dot(shape, X(v), y, 4.2)));
      }
      if (live != null) {
        kids.push(s("g", {class: ["g4-dot", "live", r.live.n < FEW ? "few" : ""]}, s("title", null, `${name} · 실시간: ${fmt.r(live)} (${r.live.n}건)${r.live.n < FEW ? " · 표본 적음" : ""}`),
          dot("diamond", X(live), y, 6)));
      }
    });
    put(chart, s("svg", {class: "g4-svg", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img",
      "aria-label": "고정 계좌마다 5년 기간과 실시간의 평균 R"}, kids));
    if (!ro && typeof ResizeObserver === "function") {
      ro = new ResizeObserver(() => { const w = Math.floor(chart.clientWidth); if (w && Math.abs(w - lastW) > 8 && data) drawDots(sorted()); });
      ro.observe(chart);
    }
  }

  await load();
  ctx.every(5 * 60000, load);
  return () => { if (ro) ro.disconnect(); };
}

function dot(shape, cx, cy, r) {
  if (shape === "square") return s("rect", {x: cx - r * 0.85, y: cy - r * 0.85, width: r * 1.7, height: r * 1.7});
  if (shape === "tri") return s("path", {d: `M${cx} ${cy - r} L${cx + r * 0.95} ${cy + r * 0.75} L${cx - r * 0.95} ${cy + r * 0.75} Z`});
  if (shape === "diamond") return s("path", {d: `M${cx} ${cy - r * 1.15} L${cx + r * 1.15} ${cy} L${cx} ${cy + r * 1.15} L${cx - r * 1.15} ${cy} Z`});
  return s("circle", {cx, cy, r});
}
