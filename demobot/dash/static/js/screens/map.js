// #/map 설정 지도 (CONTRACT 8.12): a heatmap of one strategy's settings for one timeframe, window, exit and scope.
// Two chosen parameters on the axes; the other parameters are averaged (only the settings that meet the window's
// minimum trade count) or fixed at chosen values. Colour = mean R (after costs) or the neighbourhood score; a cell
// whose settings are all under the window minimum is grey. The numbers come from the ranking (/api/rank, every
// setting in pages of 200) and the parameter values from /api/grid. Nothing new is computed on the server.
// Round 5 stage 2B (the rule bot's v4 heat maps, grid-kit.css): the choices as one filter bar, the map's numbers as stat
// cards (luck line, cells with a value, the best cell, cells over the luck line), cells in nine colour steps with a
// small second line (settings over the minimum / trades), the nine-step scale as the legend.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {STRAT_KO, WINDOW_KO, SCOPE_KO, tfKo} from "../labels.js";

const DEF = {strat: "S2", tf: "15m", window: "26w", exit: "0", scope: "ALL", x: "0", y: "1", metric: "mean_R", mode: "avg", fix: ""};
const METRIC_KO = {mean_R: "평균 R (수수료 후)", plateau: "주변 평균 (점수)"};
const PAGE = 200;
let GRID = null;

const valKo = (v) => (Number.isInteger(v) ? String(v) : fmt.num(v, v < 1 ? 2 : 1).replace(/0$/, "").replace(/\.$/, ""));
const grp = (label, ...kids) => h("span", {class: "k4-barg s2-g"}, h("span", {class: "k4-k"}, label), ...kids);
/** The colour step of a value against the scale (grid-kit data-b: −4..4; 0 = about zero). */
const stepOf = (v, max) => {
  const a = Math.abs(Number(v)) / (max || 1);
  if (!(a > 0.02)) return 0;
  return Math.sign(Number(v)) * Math.max(1, Math.min(4, Math.ceil(a * 4)));
};

export async function mount(el, ctx) {
  ctx.setTitle("설정 지도");
  if (!GRID) {
    try { GRID = await ctx.api("/api/grid"); } catch (e) {
      if (e && e.name === "AbortError") return;
      el.append(ui.screenHead("설정 지도"), ui.errorBox(e, () => location.reload()));
      return;
    }
  }
  const st = {...DEF, ...(local.get("map", {}) || {}), ...ctx.params.query};
  for (const k of Object.keys(st)) if (!(k in DEF)) delete st[k];
  const strat = () => GRID.strategies.find((s) => s.short === st.strat) || GRID.strategies[0];
  const save = () => {
    const keep = {};
    for (const k of Object.keys(DEF)) if (st[k] !== DEF[k]) keep[k] = st[k];
    local.set("map", keep);
    ctx.setQuery(keep);
  };
  const ctrl = h("div", {class: "s2-ctl", role: "group", "aria-label": "고르기"});
  const meta = h("p", {class: "s2-meta"});
  const how = h("p", {class: "note"});
  const mapBox = h("div", {class: "hm-wrap"});
  const legendBox = h("div", {class: "stack tight"});
  // the map's numbers (count to new values when the ranking is written again)
  const nLuck = K4.liveNum(null, {format: (v) => fmt.r(v), tone: true, flash: "accent"});
  const nFill = h("b", {class: "num"}, "—");
  const nBest = h("b", {class: "num"}, "—");
  const nAbove = h("b", {class: "num"}, "—");
  const fillSub = h("span", {class: "s"}, "—"), bestSub = h("span", {class: "s"}, "—"), aboveSub = h("span", {class: "s"}, "—");
  const aboveK = h("span", {class: "k"}, "운 기준선 위 칸");
  const stats = h("div", {class: "stats s4 s2-stats"},
    K4.stat("운 기준선", nLuck, "무작위 선수 1등이 낼 법한 평균 R (95%)"),
    K4.stat("값이 있는 칸", nFill, fillSub),
    K4.stat("가장 좋은 칸", nBest, bestSub),
    h("div", {class: "stat"}, aboveK, nAbove, aboveSub));
  el.append(ui.screenHead("설정 지도", "설정 두 개를 축으로 놓고 어디가 좋은지 색으로"), ctrl,
    h("div", {class: "s2-info"}, stats, meta),
    ui.card({plate: "지도", cls: "dl-rcard s2-mapcard"}, how, mapBox, legendBox),
    ui.note("한 칸만 진하게 튀는 곳보다 넓게 같은 색인 곳이 운이 아닐 가능성이 큽니다 (주변 평균이 이것을 숫자로 봅니다). "
      + "회색 칸은 거래가 그 기간의 최소 거래 수보다 적어서 믿기 어려운 칸입니다."));

  function fixArr(s) {
    const dims = s.dims || [];
    const parts = String(st.fix || "").split(",").map((x) => Number(x));
    return dims.map((d, i) => (Number.isInteger(parts[i]) && parts[i] >= 0 && parts[i] < d.values.length ? parts[i]
      : (s.default_idx || [])[i] ?? 0));
  }

  function paintControls() {
    const s = strat();
    const dims = s.dims || [];
    if (!dims.length) { put(ctrl, ui.none("설정 격자 정보가 없습니다 (서버를 새로 띄워야 합니다)")); return; }
    let x = Math.min(Number(st.x) || 0, dims.length - 1), y = Math.min(Number(st.y) || 0, dims.length - 1);
    if (x === y) y = (x + 1) % dims.length;
    st.x = String(x); st.y = String(y);
    const set = (k, v) => { st[k] = String(v); if (k === "strat") { st.fix = ""; st.x = "0"; st.y = "1"; } save(); paintControls(); load(); };
    const dimOpts = dims.map((d, i) => ({id: String(i), label: d.ko}));
    const fx = fixArr(s);
    const fixed = dims.map((d, i) => (i === x || i === y ? null : grp(d.ko, ui.select(d.values.map((v, j) => ({id: String(j), label: valKo(v)})), fx[i],
      (v) => { const a = fixArr(s); a[i] = Number(v); st.fix = a.join(","); save(); paint(); }, `${d.ko} 고정 값`)))).filter(Boolean);
    put(ctrl,
      h("div", {class: "k4-bar"},
        grp("매매법", ui.seg(GRID.strategies.map((x2) => ({id: x2.short, label: x2.short, title: STRAT_KO[x2.short]})), st.strat, (v) => set("strat", v), {label: "매매법"})),
        grp("봉", ui.seg(GRID.tfs.map((t) => ({id: t, label: tfKo(t)})), st.tf, (v) => set("tf", v), {label: "봉"})),
        grp("기간", ui.seg(GRID.windows.map((w) => ({id: w, label: WINDOW_KO[w] || w})), st.window, (v) => set("window", v), {label: "기간"}))),
      h("div", {class: "k4-bar"},
        grp("청산", ui.select(GRID.exits.map((e) => ({id: String(e.i), label: e.ko})), st.exit, (v) => set("exit", v), "청산")),
        grp("범위", ui.select(GRID.scopes.map((c) => ({id: c, label: SCOPE_KO(c)})), st.scope, (v) => set("scope", v), "범위")),
        grp("색", ui.seg(Object.entries(METRIC_KO).map(([id, label]) => ({id, label})), st.metric, (v) => { st.metric = v; save(); paint(); }, {label: "색"}))),
      h("div", {class: "k4-bar"},
        grp("가로", ui.select(dimOpts, st.x, (v) => { if (v === st.y) st.y = st.x; st.x = v; save(); paintControls(); paint(); }, "가로 축")),
        grp("세로", ui.select(dimOpts, st.y, (v) => { if (v === st.x) st.x = st.y; st.y = v; save(); paintControls(); paint(); }, "세로 축")),
        grp("나머지", ui.seg([{id: "avg", label: "평균"}, {id: "fix", label: "값 고정"}], st.mode,
          (v) => { st.mode = v; save(); paintControls(); paint(); }, {label: "나머지 설정"}))),
      st.mode === "fix" && fixed.length ? h("div", {class: "k4-bar s2-fixbar"}, fixed) : null);
  }

  // ---------------------------------------------------------------- data: every setting of the cell (pages of 200)
  let cache = {key: null}, req = 0;
  async function load() {
    const my = ++req;                                   // a newer choice wins; an older answer is dropped
    const key = [st.strat, st.tf, st.window, st.exit, st.scope].join("|");
    const rows = [];
    let d, off = 0, total = Infinity;
    try {
      while (off < total) {
        d = await ctx.api("/api/rank?" + new URLSearchParams({strat: st.strat, tf: st.tf, window: st.window, exit: st.exit,
          scope: st.scope, sort: "n", limit: String(PAGE), offset: String(off)}));
        if (my !== req) return;
        if (isMissing(d)) break;
        total = Number(d.total) || 0;
        rows.push(...(d.rows || []));
        off += PAGE;
        if (!(d.rows || []).length) break;
      }
    } catch (e) {
      if (e && e.name === "AbortError") return;
      if (my === req) put(mapBox, ui.errorBox(e, load));
      return;
    }
    if (cache.key !== key) delete nLuck.dataset.v;     // another map: no count-up
    cache = {key, d, rows, missing: isMissing(d)};
    paint();
  }

  function paint() {
    const s = strat();
    const dims = s.dims || [];
    if (!cache.d || !dims.length) return;
    if (cache.missing) {
      put(meta, ui.missing(`${st.strat} · ${tfKo(st.tf)} 순위 파일`));
      nLuck.update(null);
      for (const b of [nFill, nBest, nAbove]) b.textContent = "—";
      for (const b of [fillSub, bestSub, aboveSub]) b.textContent = "준비 중";
      put(how); put(mapBox, ui.none("준비 중")); put(legendBox);
      return;
    }
    const d = cache.d;
    const shape = dims.map((x) => x.values.length);
    const stride = shape.map((_, i) => shape.slice(i + 1).reduce((a, b) => a * b, 1));
    const idxOf = (c) => shape.map((n, i) => Math.floor(c / stride[i]) % n);
    const xi = Number(st.x), yi = Number(st.y);
    const fx = fixArr(s);
    const nx = shape[xi], ny = shape[yi];
    const cells = Array.from({length: ny}, () => Array.from({length: nx}, () => ({rows: []})));
    for (const r of cache.rows) {
      const ix = idxOf(Number(r.c));
      if (st.mode === "fix" && ix.some((v, i) => i !== xi && i !== yi && v !== fx[i])) continue;
      cells[ix[yi]][ix[xi]].rows.push(r);
    }
    const metric = st.metric === "plateau" ? "plateau" : "mean_R";
    let vmax = 0;
    for (const row of cells) for (const c of row) {
      const ok = c.rows.filter((r) => r.min_ok && r[metric] != null && Number.isFinite(Number(r[metric])));
      c.ok = ok.length;
      c.n = c.rows.reduce((a, r) => a + (Number(r.n) || 0), 0);
      if (!ok.length) { c.v = null; continue; }
      if (metric === "mean_R") {
        const w = ok.reduce((a, r) => a + Number(r.n), 0);
        c.v = w > 0 ? ok.reduce((a, r) => a + Number(r.mean_R) * Number(r.n), 0) / w : null;
      } else {
        c.v = ok.reduce((a, r) => a + Number(r.plateau), 0) / ok.length;
      }
      if (c.v != null) vmax = Math.max(vmax, Math.abs(c.v));
    }
    vmax = Math.max(vmax, 0.02);
    const luck = d.luck95;
    const exitKo = (GRID.exits[d.exit] || {}).ko || d.exit_ko;
    put(meta, h("b", null, `${d.short || st.strat} · ${tfKo(d.tf)}`), ` · ${exitKo} · ${SCOPE_KO(d.scope)} · ${WINDOW_KO[d.window] || d.window}`,
      d.bounds_ms ? ` (${fmt.mmdd(d.bounds_ms[0])} ~ ${fmt.mmdd(d.bounds_ms[1])})` : "", " · ",
      h("span", {class: "nowrap"}, `설정 ${fmt.int(d.settings)}개`), " · ", h("span", {class: "nowrap"}, `최소 거래 수 ${fmt.int(d.min_n)}건`),
      luck != null ? [" · ", h("span", {class: "nowrap"}, `운 기준선 ${fmt.r(luck)}`)] : null,
      d.generated_ms ? [" · ", h("span", {class: "nowrap muted"}, `자료 ${fmt.kst(d.generated_ms)}`)] : null);
    put(how, st.mode === "fix"
      ? `칸 하나 = 설정 하나 (나머지: ${dims.map((x, i) => (i === xi || i === yi ? null : `${x.ko} ${valKo(x.values[fx[i]])}`)).filter(Boolean).join(", ")}) · 작은 숫자 = 거래 수`
      : `칸 하나 = 나머지 설정들의 평균 (최소 거래 수를 넘은 설정만${metric === "mean_R" ? ", 거래 수로 가중" : ""}) · 작은 숫자 = 최소 거래 수를 넘은 설정 / 칸의 설정`);
    // the stat cards
    const flat = cells.flatMap((row, y) => row.map((c, x) => ({c, x, y})));
    const filled = flat.filter((q) => q.c.v != null);
    nLuck.update(luck);
    nFill.textContent = `${fmt.int(filled.length)} / ${fmt.int(flat.length)}`;
    fillSub.textContent = `회색 ${fmt.int(flat.length - filled.length)}칸 = 최소 거래 수 미만`;
    const best = filled.reduce((m, q) => (!m || q.c.v > m.c.v ? q : m), null);
    nBest.textContent = best ? fmt.num(best.c.v, 3, true) : "—";
    nBest.className = ["num", best ? fmt.tone(best.c.v, nBest.textContent) : ""].join(" ");
    bestSub.textContent = best ? `${dims[xi].ko} ${valKo(dims[xi].values[best.x])} · ${dims[yi].ko} ${valKo(dims[yi].values[best.y])} (${METRIC_KO[metric]})` : "값이 있는 칸이 없습니다";
    if (metric === "mean_R") {
      aboveK.textContent = "운 기준선 위 칸";
      nAbove.textContent = luck == null ? "—" : fmt.int(filled.filter((q) => q.c.v > luck).length);
      aboveSub.textContent = luck == null ? "운 기준선이 없습니다" : `평균 R이 ${fmt.r(luck)}보다 큰 칸 (노란 점)`;
    } else {
      aboveK.textContent = "0보다 큰 칸";
      nAbove.textContent = fmt.int(filled.filter((q) => q.c.v > 0).length);
      aboveSub.textContent = "주변 평균이 더하기인 칸";
    }
    // the map
    const dx = (s.default_idx || [])[xi], dy = (s.default_idx || [])[yi];
    const head = [h("span", {class: "hm-corner"}), ...dims[xi].values.map((v) => h("span", {class: "hm-ax hm-axx"}, valKo(v)))];
    const body = [];
    cells.forEach((row, y) => {
      body.push(h("span", {class: "hm-ax hm-axy"}, valKo(dims[yi].values[y])));
      row.forEach((c, x) => {
        const grey = c.v == null;
        const beats = metric === "mean_R" && !grey && luck != null && c.v > luck;
        const isDef = x === dx && y === dy && (st.mode !== "fix" || dims.every((_, i) => i === xi || i === yi || fx[i] === (s.default_idx || [])[i]));
        const label = st.mode === "fix" && c.rows[0] ? c.rows[0].label : null;
        const title = `${dims[xi].ko} ${valKo(dims[xi].values[x])} · ${dims[yi].ko} ${valKo(dims[yi].values[y])}\n`
          + (grey ? "최소 거래 수 미만" : `${METRIC_KO[metric]} ${fmt.num(c.v, 3, true)}`)
          + ` · 설정 ${c.rows.length}개 중 ${c.ok}개가 최소 거래 수 이상 · 거래 ${fmt.int(c.n)}건` + (label ? `\n${label}` : "");
        body.push(h(label ? "a" : "span", {class: ["s2-hc", grey ? "grey" : "", isDef ? "def" : "", beats ? "luck" : ""],
          dataset: grey ? null : {b: String(stepOf(c.v, vmax))}, title, "aria-label": title.replace(/\n/g, " · "),
          href: label ? ctx.href("rank", null, {strat: st.strat, tf: st.tf, window: st.window, exit: st.exit, scope: st.scope, q: label}) : null},
        h("b", null, grey ? "—" : fmt.num(c.v, 2, true)),
        h("small", null, st.mode === "fix" ? `${fmt.int(c.n)}건` : `${fmt.int(c.ok)}/${fmt.int(c.rows.length)}`)));
      });
    });
    put(mapBox, h("p", {class: "hm-axes"}, h("span", null, "가로 → ", h("b", null, dims[xi].ko)), h("span", null, "세로 ↓ ", h("b", null, dims[yi].ko))),
      h("div", {class: "hm s2-hm", style: {"--nx": String(nx)}, role: "table", "aria-label": `${dims[yi].ko} × ${dims[xi].ko} 설정 지도`}, head, body));
    put(legendBox,
      h("div", {class: "s2-scale", "aria-hidden": "true"},
        h("div", {class: "s2-scale-row"}, [-4, -3, -2, -1, 0, 1, 2, 3, 4].map((b) => h("span", {class: "s2-hc", dataset: {b: String(b)}}))),
        h("div", {class: "s2-scale-words"}, h("span", {class: "num"}, fmt.num(-vmax, 2, true)), h("span", null, "0"), h("span", {class: "num"}, fmt.num(vmax, 2, true)))),
      h("div", {class: "s2-keys"},
        h("span", null, h("i", {class: "s2-hc grey"}), "최소 거래 수 미만"),
        h("span", null, h("i", {class: "s2-hc def", dataset: {b: "0"}}), "기본값이 있는 칸"),
        metric === "mean_R" ? h("span", null, h("i", {class: "s2-hc luck", dataset: {b: "0"}}), "운 기준선 위 (노란 점)") : null),
      ui.note(`색: 초록 쪽 = 더하기, 빨강 쪽 = 빼기, 진할수록 큼 (가장 진한 색 = ±${fmt.num(vmax, 2)}). `
        + (st.mode === "fix" ? "칸을 누르면 설정 순위에서 그 설정을 찾습니다." : "칸에 손가락이나 마우스를 올리면 설정 수와 거래 수가 나옵니다.")));
  }

  paintControls();
  await load();
  ctx.every(5 * 60000, load);
}
