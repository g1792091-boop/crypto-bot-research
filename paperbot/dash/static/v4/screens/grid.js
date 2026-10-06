// #/grid[?g=core|ds|m5] — 한눈 지도 (매매법 › 한눈 지도, builder grid). Rows = strategies, columns = 15분 / 30분 / 1시간 /
// 4시간, one cell per account (a link to it). 기존 36: the colour is the account's return minus the median coin flip
// of the SAME timeframe (참고: the neutral accent / cyan pair, never green / red before the verdict). 딥시크 44: grouped by
// the four DeepSeek specialists (paperbot/groups.py V4_ROLES), the colour is the account's own return (up / down: money
// made or lost) because DeepSeek gets no per-account coin-flip comparison (CONTRACT honesty rule 3); the five session
// definitions have no 4시간 account ('없음'). 5분봉: the reel and its three 5m coin flips as one strip, with the reel's
// profile card. Sort 이름 / 높은 순, window 30일 / 7일. Data: /api/v4/grid (one small answer, 60 s cache on the
// server), polled every 60 s while the screen is open (paused when the page is hidden).
// Not a copy of 분석 › 코인·장세 지도 (where money was made by coin / regime / session over all trades): this is per
// account; the legend links there and to 회의 요약 › 봉 비교.
import {h, put, ui, fmt, motion, local, derive} from "../core/pb.js";
import {heatCell, bin, nameOf, scaleStrip, verdictTs, periodKo, cellPct, profileCard, identicon, BINS, MIN_COLOR, SMALL,
  y5Cell, y5Bin, posCell, posRoe} from "./grid-kit.js";

const TABS = [{id: "core", label: "기존 36"}, {id: "ds", label: "딥시크 44"}, {id: "m5", label: "5분봉"}];
// "높은 순": the mean of the coloured cells (a sort, never a ranking claim; the legend says so)
const SORTS = [{id: "name", label: "이름"}, {id: "good", label: "높은 순"}];
const PERIODS = [{id: "30", label: "30일"}, {id: "7", label: "7일"}];
// fill-strat: '5년 시험' (the 5-year past test per trade, so the map has colour on day 1, 참고) and '지금 포지션' (the
// cells holding a position now, lit, with the live ROE at the mark price)
// review 10/06: the default is the account's own return (mint / pink: money made or lost). As the default, 동전 봇 대비
// painted a −58 % account gold (good-looking) because the coin flips lost more; it is the second choice now, and in
// 자기 수익률 the comparison stays visible only as a small neutral ▲ / ▼ in each cell's corner (참고)
const COLORS = [{id: "own", label: "자기 수익률"}, {id: "vs", label: "동전 봇 대비"}, {id: "y5", label: "5년 시험"}, {id: "pos", label: "지금 포지션"}];
const DS_COLORS = [{id: "own", label: "자기 수익률"}, {id: "y5", label: "5년 시험"}, {id: "pos", label: "지금 포지션"}];
const LIVE = new Set(["y5", "pos"]);
const COLS = ["15m", "30m", "1h", "4h"];
const okTab = (g) => (TABS.some((t) => t.id === g) ? g : null);
const median = (xs) => {
  const v = xs.filter((x) => x != null && Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = v.length >> 1;
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
};

let current = null;

export async function mount(el, ctx) {
  ctx.setTitle("한눈 지도");
  const q = ctx.params.query || {};
  const st = {tab: okTab(q.g) || okTab(local.get("grid-tab", "core")) || "core", sort: local.get("grid-sort", "name"),
    days: String(local.get("grid-days", "30")), color: local.get("grid-color", "own"), dsColor: local.get("grid-dscolor", "own"), y5: null, d: null, gen: 0, painted: false, prev: new Map(), reel: null};
  if (!COLORS.some((x) => x.id === st.color)) st.color = "own";
  // once per device (review 10/06): a "vs" kept from before the change (the old default, often re-picked only to go
  // back to it) is reset to the new default 자기 수익률; a "vs" chosen after this is honoured
  if (local.get("grid-color-v", 0) !== 2) {
    if (st.color === "vs") { st.color = "own"; local.set("grid-color", "own"); }
    local.set("grid-color-v", 2);
  }
  if (!DS_COLORS.some((x) => x.id === st.dsColor)) st.dsColor = "own";
  if (!SORTS.some((x) => x.id === st.sort)) st.sort = "name";
  if (!PERIODS.some((x) => x.id === st.days)) st.days = "30";

  const tabs = ui.seg(TABS, st.tab, (id) => setTab(id, true), {label: "묶음"});
  const sortSeg = ui.seg(SORTS, st.sort, (id) => { st.sort = id; local.set("grid-sort", id); paint(true); }, {label: "순서"});
  const daySeg = ui.seg(PERIODS, st.days, (id) => { st.days = id; local.set("grid-days", id); load(true); }, {label: "기간"});
  const sortBox = h("span", {class: "grid-opt"}, h("span", {class: "k"}, "순서"), sortSeg);
  // 기존 36 only: the colour can also be the account's own return (money made or lost; DeepSeek always is)
  const colorSeg = ui.seg(COLORS, st.color, (id) => { st.color = id; local.set("grid-color", id); st.prev.clear(); st.painted = false; paint(true); }, {label: "색"});
  const colorBox = h("span", {class: "grid-opt"}, h("span", {class: "k"}, "색"), colorSeg);
  const dsColorSeg = ui.seg(DS_COLORS, st.dsColor, (id) => { st.dsColor = id; local.set("grid-dscolor", id); st.prev.clear(); st.painted = false; paint(true); }, {label: "색"});
  const dsColorBox = h("span", {class: "grid-opt"}, h("span", {class: "k"}, "색"), dsColorSeg);
  const modeNow = () => (st.tab === "ds" ? st.dsColor : st.tab === "core" ? st.color : "own");     // 5분봉: own + ▲ / ▼
  // the 5-year rows: research files only (one small answer, cached an hour on the server); fetched once
  async function loadY5() {
    if (st.y5) return st.y5;
    try { st.y5 = await ctx.api("/api/v4/grid/y5"); } catch (e) { st.y5 = {strategies: {}, failed: true}; }
    return st.y5;
  }
  const accts = () => new Map((((ctx.store.get("board") || {}).accounts) || []).map((a) => [a.account_id, a]));
  const markOf = (sym) => ctx.store.mark(sym);
  const summary = h("div", {class: "grid-sum"});
  const mapCard = h("section", {class: "card grid-mapcard", "aria-label": "매매법 × 봉 지도"}, motion.shimmer(8, true));
  const legend = h("div", {class: "stack grid-side"});
  const ctrl = ui.card({plate: "매매법 × 봉", cls: "hero grid-ctrl"}, tabs,
    h("div", {class: "grid-opts"}, sortBox, h("span", {class: "grid-opt"}, h("span", {class: "k"}, "기간"), daySeg)), summary);
  el.append(ui.screenHead("한눈 지도", "매매법마다 봉 4개 · 한 칸이 계좌 하나 · 누르면 그 계좌"),
    h("div", {class: "grid-cols"}, h("div", {class: "stack grid-main"}, ctrl, mapCard), legend));

  function setTab(id, user) {
    if (!okTab(id)) return;
    st.tab = id; local.set("grid-tab", id); tabs.set(id);
    if (user) { try { window.history.replaceState(null, "", ctx.href("grid", null, {g: id})); } catch { /* keep the hash */ } }
    st.painted = false; st.prev.clear();
    paint(true);
  }
  current = (params) => { const g = okTab((params.query || {}).g); if (g && g !== st.tab) setTab(g, false); };
  ctx.track(() => { current = null; });

  async function load(animate) {
    const g = ++st.gen;
    let d;
    try { d = await ctx.api(`/api/v4/grid?days=${st.days}`); }
    catch (e) {
      if (e && e.name === "AbortError") return;
      if (g === st.gen && !st.d) put(mapCard, ui.errorBox(e, () => load(false)));
      return;
    }
    if (g !== st.gen || !ctx.alive()) return;
    if (st.d && st.d.days !== d.days) { st.painted = false; st.prev.clear(); }
    const changedDays = st.reel && st.d && st.d.days !== d.days;
    st.d = d;
    paint(animate);
    if (changedDays) st.reel.set(st.days);
  }

  // ---------------------------------------------------------------- rows
  function rowsOf(d, group, mode) {
    const by = new Map();
    for (const c of d.cells) {
      if (c.g !== group) continue;
      if (!by.has(c.s)) by.set(c.s, {s: c.s, name: nameOf(c), fam: c.fam, role: c.role, cells: {}});
      by.get(c.s).cells[c.tf] = c;
    }
    const y5 = (st.y5 && st.y5.strategies) || {};
    for (const r of by.values()) {
      const xs = mode === "y5" ? Object.values((y5[r.s] || {}).tfs || {}).map((y) => y.roe).filter((v) => v != null)
        : mode === "pos" ? Object.values(r.cells).map((c) => (c.open ? 1 : 0))
        : Object.values(r.cells).filter((c) => c.n >= MIN_COLOR && !c.bust).map((c) => (mode === "own" ? c.ret : c.vs)).filter((v) => v != null);
      r.score = xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
    }
    const rows = [...by.values()];
    if (st.sort === "good") rows.sort((a, b) => (b.score ?? -9) - (a.score ?? -9) || a.name.localeCompare(b.name, "ko"));
    else rows.sort((a, b) => a.name.localeCompare(b.name, "ko"));
    return rows;
  }

  function counts(cells, mode) {
    const n = {up: 0, mid: 0, down: 0, grey: 0, bust: 0, total: cells.length, bins: {}};
    for (const c of cells) {
      if (c.bust) { n.bust++; continue; }
      const k = c.n < MIN_COLOR ? null : bin(mode === "own" ? c.ret : c.vs);
      if (k == null) { n.grey++; continue; }
      n.bins[k] = (n.bins[k] || 0) + 1;
      if (k > 0) n.up++; else if (k < 0) n.down++; else n.mid++;
    }
    return n;
  }

  function paintSummary(cells, mode) {
    if (LIVE.has(mode)) { paintLiveSummary(cells, mode); return; }
    const n = counts(cells, mode);
    const segs = [];
    for (const k of [-4, -3, -2, -1, 0, 1, 2, 3, 4]) if (n.bins[k]) segs.push(h("i", {class: "gk-cell sw", dataset: {b: String(k)}, style: {flex: String(n.bins[k])}, title: `${fmt.int(n.bins[k])}칸`}));
    if (n.grey) segs.push(h("i", {class: "gk-cell sw grey", style: {flex: String(n.grey)}, title: `거래 적음 ${fmt.int(n.grey)}칸`}));
    if (n.bust) segs.push(h("i", {class: "gk-cell sw bust", style: {flex: String(n.bust)}, title: `파산 ${fmt.int(n.bust)}칸`}));
    const words = mode === "own"
      ? [`${fmt.int(n.total)}칸`, `번 칸 ${fmt.int(n.up)}`, `0 근처 ${fmt.int(n.mid)}`, `잃은 칸 ${fmt.int(n.down)}`]
      : [`${fmt.int(n.total)}칸`, `동전 봇보다 위 ${fmt.int(n.up)}`, `비슷 ${fmt.int(n.mid)}`, `아래 ${fmt.int(n.down)}`];
    if (n.grey) words.push(`거래 적음 ${fmt.int(n.grey)}`);
    if (n.bust) words.push(`파산 ${fmt.int(n.bust)}`);
    // 자기 수익률 on the 36 / the reel: the coin-flip comparison as counts (the ▲ / ▼ marks), 참고
    let vsLine = null;
    if (mode === "own" && st.tab !== "ds") {
      const xs = cells.filter((c) => !c.bust && c.n >= MIN_COLOR && c.vs != null);
      if (xs.length) vsLine = h("p", {class: "note"}, `▲ 같은 봉 동전 봇 중앙값보다 위 ${fmt.int(xs.filter((c) => c.vs > 0).length)} · ▼ 아래 ${fmt.int(xs.filter((c) => c.vs < 0).length)} (참고, 판정 아님)`);
    }
    put(summary, segs.length && cells.length > 3 ? h("div", {class: ["grid-bar", mode === "own" ? "own" : ""], role: "img", "aria-label": words.join(", ")}, segs) : null,
      h("p", {class: "grid-sumtxt"}, ui.pill("", "ref"), words.join(" · ")), vsLine,
      h("p", {class: "note"}, `${periodKo(st.d)} · ${fmt.mmdd(st.d.from)}부터 지금까지 · 닫힌 거래 기준`));
  }

  /** 5년 시험: how many cells had a positive / negative 5-year result per trade; 지금 포지션: open cells and their live
   *  ROE (unrealized, at the mark price, before the exit fee). */
  function paintLiveSummary(cells, mode) {
    if (mode === "y5") {
      const y5 = (st.y5 && st.y5.strategies) || {};
      let up = 0, down = 0, none = 0;
      for (const c of cells) {
        const y = ((y5[c.s] || {}).tfs || {})[c.tf];
        if (!y || y.roe == null) none++; else if (y.roe > 0) up++; else if (y.roe < 0) down++;
      }
      put(summary, h("p", {class: "grid-sumtxt"}, ui.pill("5년 과거 시험 · 참고", "ref"), ` ${fmt.int(cells.length)}칸 · 거래당 평균이 + 인 칸 ${fmt.int(up)} · − 인 칸 ${fmt.int(down)}`,
        none ? ` · 자료 없음 ${fmt.int(none)}` : ""),
      h("p", {class: "note"}, st.y5 && st.y5.failed ? "5년 시험 자료를 불러오지 못했습니다 (준비 전)." : "과거 5년 시험의 거래 한 건 평균입니다. 지금 계좌의 성적이 아니며 앞으로도 그렇다는 뜻이 아닙니다."));
      return;
    }
    const by = accts();
    const open = cells.filter((c) => c.open);
    let gain = 0, loss = 0;
    for (const c of open) { const r = posRoe(by.get(c.id), markOf); if (r != null) { if (r > 0) gain++; else if (r < 0) loss++; } }
    put(summary, h("p", {class: "grid-sumtxt"}, `${fmt.int(cells.length)}칸 중 지금 포지션 ${fmt.int(open.length)}칸`,
      open.length ? ` · 평가 이익 ${fmt.int(gain)} · 평가 손실 ${fmt.int(loss)}` : " · 지금 열린 포지션 없음"),
    h("p", {class: "note"}, "빛나는 칸 = 지금 포지션이 열린 계좌 · % = 지금 평가 ROE (마크 가격, 나갈 때 수수료 전) · 5초마다 실제 시세"));
  }

  // ---------------------------------------------------------------- the map
  function headRow(d, group) {
    const judged = (d.judged || {})[group] || [];
    return h("div", {class: "grid-row grid-head", role: "row"}, h("span", {class: "grid-nm", role: "columnheader"}, group === "ds200" ? "정의" : "매매법"),
      COLS.map((tf) => h("span", {class: "grid-th", role: "columnheader"}, fmt.tfKo(tf),
        judged.length && !judged.includes(tf) ? h("small", {title: "4시간봉은 30일 판정에 들지 않는 관찰용 계좌입니다"}, "관찰용") : null)));
  }

  function refRow(label, vals, title, cls) {
    return h("div", {class: ["grid-row", "grid-ref", cls], role: "row", title},
      h("span", {class: "grid-nm"}, label),
      COLS.map((tf) => { const v = vals[tf]; return h("span", {class: "gk-cell ref"}, h("b", {class: "num"}, v == null ? "—" : cellPct(v.ret)), v && v.n != null ? h("small", null, `${fmt.int(v.n)}개`) : null); }));
  }

  function nameCell(r, group) {
    return h("a", {class: "grid-nm", href: ctx.href("strategies", r.s), title: `${r.name} · 매매법 보기`},
      group === "ds200" ? null : identicon(r.s, "sm"),
      h("span", {class: "grid-nmt"}, group === "ds200" && r.fam ? h("span", {class: "grid-fam"}, r.fam) : null, r.name));
  }

  function bodyRow(r, group, idx, mode) {
    const noneTitle = group === "ds200" ? "세션 정의는 4시간봉 계좌가 없습니다" : "이 봉 계좌가 없습니다";
    const by = mode === "pos" ? accts() : null, y5 = (st.y5 && st.y5.strategies) || {};
    return h("div", {class: "grid-row", role: "row", style: {"--i": idx}}, nameCell(r, group),
      COLS.map((tf) => {
        const c = r.cells[tf], href = c ? ctx.href("account", c.id) : null;
        if (mode === "y5") return y5Cell(c, (y5[r.s] || {}).tfs ? y5[r.s].tfs[tf] : null, (y5[r.s] || {}).unit, {href, label: r.name, noneTitle});
        if (mode === "pos") return posCell(c, c ? by.get(c.id) : null, markOf, {href, label: r.name, noneTitle});
        return heatCell(c, {mode, href, label: r.name, noneTitle, vsMark: mode === "own" && group !== "ds200"});
      }));
  }

  function footRow(cells, mode) {
    if (LIVE.has(mode)) {
      const y5 = (st.y5 && st.y5.strategies) || {};
      return h("div", {class: "grid-row grid-foot", role: "row"}, h("span", {class: "grid-nm"}, mode === "y5" ? "5년 + · −" : "열린 칸"),
        COLS.map((tf) => {
          const xs = cells.filter((c) => c.tf === tf);
          if (mode === "pos") return h("span", {class: "grid-ft num"}, h("b", {class: "hi"}, fmt.int(xs.filter((c) => c.open).length)), h("i", null, "/"), h("b", null, fmt.int(xs.length)));
          const ys = xs.map((c) => ((y5[c.s] || {}).tfs || {})[tf]).filter((y) => y && y.roe != null);
          return h("span", {class: "grid-ft num"}, h("b", {class: "hi"}, fmt.int(ys.filter((y) => y.roe > 0).length)), h("i", null, "·"), h("b", {class: "lo"}, fmt.int(ys.filter((y) => y.roe < 0).length)));
        }));
    }
    return h("div", {class: "grid-row grid-foot", role: "row"}, h("span", {class: "grid-nm"}, mode === "own" ? "번 칸 · 잃은 칸" : "위 · 아래"),
      COLS.map((tf) => {
        const n = counts(cells.filter((c) => c.tf === tf), mode);
        return h("span", {class: "grid-ft num"}, h("b", {class: "hi"}, fmt.int(n.up)), h("i", null, "·"), h("b", {class: "lo"}, fmt.int(n.down)));
      }));
  }

  function flipVals(d) {
    const out = {};
    for (const tf of COLS) { const f = (d.flips || {})[tf]; out[tf] = f ? {ret: f.median, n: f.n} : null; }
    return out;
  }

  function coreMap(d) {
    const cells = d.cells.filter((c) => c.g === "core");
    if (!cells.length) return [emptyMap()];
    const mode = st.color;
    paintSummary(cells, mode);
    return [h("div", {class: ["grid-map", mode !== "vs" ? "own" : "", mode === "pos" ? "pos" : ""], role: "table", "aria-label": "기존 36 매매법 × 봉"}, headRow(d, "core"),
      LIVE.has(mode) ? null : refRow("동전 봇 중앙값", flipVals(d), mode === "own" ? "같은 봉 동전 봇 3개의 중앙값 (참고)" : "같은 봉 동전 봇 3개의 중앙값: 칸 색의 기준 (참고)", "flip"),
      rowsOf(d, "core", mode).map((r, i) => bodyRow(r, "core", i, mode)), footRow(cells, mode))];
  }

  function dsMap(d) {
    const cells = d.cells.filter((c) => c.g === "ds200");
    if (!cells.length) return [emptyMap()];
    const mode = st.dsColor;
    paintSummary(cells, mode);
    const dsMed = {};
    for (const tf of COLS) { const xs = cells.filter((c) => c.tf === tf); dsMed[tf] = xs.length ? {ret: median(xs.map((c) => c.ret)), n: xs.length} : null; }
    const rows = rowsOf(d, "ds200", mode);
    const roles = (d.roles || []).filter((r) => r.key !== "reel_5m");
    const kids = [headRow(d, "ds200"),
      LIVE.has(mode) ? null : refRow("동전 봇 중앙값", flipVals(d), "같은 봉 동전 봇 3개의 중앙값 (묶음끼리 볼 때의 기준, 참고)", "flip"),
      LIVE.has(mode) ? null : refRow("딥시크 중앙값", dsMed, "같은 봉 딥시크 계좌 전체의 중앙값 (묶음 숫자, 참고)", "dsmed")];
    let i = 0;
    for (const role of roles) {
      const mine = rows.filter((r) => r.role === role.key);
      if (!mine.length) continue;
      const m = median(cells.filter((c) => c.role === role.key).map((c) => c.ret));
      kids.push(h("div", {class: "grid-row grid-sec", role: "row"},
        h("span", {class: "grid-secname"}, h("b", null, role.ko.replace(/ 담당$/, "")), h("span", {class: "sub"}, ` 정의 ${fmt.int(mine.length)}개 · ${role.families.join("·")}`)),
        h("span", {class: ["grid-secmed", "num", fmt.tone(m, cellPct(m))]}, `중앙값 ${cellPct(m)}`)));
      for (const r of mine) kids.push(bodyRow(r, "ds200", i++, mode));
    }
    const left = rows.filter((r) => !roles.some((x) => x.key === r.role));
    if (left.length) {
      kids.push(h("div", {class: "grid-row grid-sec", role: "row"}, h("span", {class: "grid-secname"}, h("b", null, "그 밖"))));
      for (const r of left) kids.push(bodyRow(r, "ds200", i++, mode));
    }
    kids.push(footRow(cells, mode));
    return [h("div", {class: ["grid-map own", mode === "pos" ? "pos" : ""], role: "table", "aria-label": "딥시크 44 정의 × 봉"}, kids.filter(Boolean))];
  }

  function m5Map(d) {
    const reel = d.cells.find((c) => c.g === "reel");
    const fl = d.cells.filter((c) => c.g === "flip" && c.tf === "5m");
    paintSummary(reel ? [reel] : [], "own");
    const f5 = (d.flips || {})["5m"] || {};
    const strip = h("div", {class: "grid-strip", role: "list"},
      h("div", {class: "grid-sc reel", role: "listitem"}, h("span", {class: "k"}, "릴스 5분 단타"),
        heatCell(reel, {mode: "own", vsMark: true, href: reel ? ctx.href("account", reel.id) : null, label: "릴스 5분 단타", noneTitle: "릴스 계좌가 없습니다"})),
      fl.map((c) => h("div", {class: "grid-sc flip", role: "listitem"}, h("span", {class: "k"}, nameOf(c).replace("동전 봇", "동전")),
        h("a", {class: "gk-cell ref", href: ctx.href("account", c.id), title: `${nameOf(c)} · 5분 · 수익률 ${fmt.pct(c.ret)} · 거래 ${fmt.int(c.n)}건 (비교 기준)`},
          h("b", {class: "num"}, cellPct(c.ret)), h("small", {class: "num"}, `${fmt.int(c.n)}건`)))));
    if (!st.reel && reel) {
      st.reel = profileCard(ctx, reel.id, {days: st.days, cls: "grid-reelcard", sync: false});
      st.reel.load();
    }
    return [h("p", {class: "ink2 grid-m5intro"}, "릴스 5분 단타는 자기 청산 규칙(스윙 저점 손절 · 윗밴드 목표 · 96봉 시간 청산)으로 돕니다. 같은 청산으로 롱만 하는 5분봉 동전 봇 3개가 비교 기준입니다 (동전 봇에서 셈)."),
      strip,
      h("p", {class: "grid-sumtxt"}, ui.pill("", "ref"), `5분봉 동전 ${fmt.int(f5.n || 0)}개 중앙값 ${cellPct(f5.median)} · 릴스 칸 색 = 자기 수익률, ▲ / ▼ = 그 중앙값보다 위 / 아래`),
      st.reel ? h("div", {class: "grid-reelwrap"}, ui.plate("릴스 5분 단타 프로필"), st.reel.el) : null];
  }

  function emptyMap() {
    const ghost = [];
    for (let i = 0; i < 4; i++) ghost.push(h("div", {class: "grid-row"}, h("span", {class: "grid-nm"}, h("span", {class: "grid-ghostname"})),
      COLS.map(() => h("span", {class: "gk-cell grey"}))));
    put(summary, h("p", {class: "grid-sumtxt"}, "계좌 기록 전"));
    return h("div", {class: "grid-empty"}, h("div", {class: "grid-map ghost", "aria-hidden": "true"}, ghost),
      h("p", {class: "grid-emptytxt"}, "계좌 기록 전 · 봇이 계좌를 열고 거래를 닫으면 칸이 채워집니다"));
  }

  function paint(animate) {
    const d = st.d;
    if (!d) return;
    const mode = modeNow();
    if (mode === "y5" && !st.y5) { put(mapCard, motion.shimmer(8, true)); loadY5().then(() => { if (ctx.alive()) paint(false); }); return; }
    sortBox.hidden = st.tab === "m5";
    const kids = st.tab === "core" ? coreMap(d) : st.tab === "ds" ? dsMap(d) : m5Map(d);
    const title = st.tab === "core" ? "기존 36 × 봉" : st.tab === "ds" ? "딥시크 44 × 봉" : "5분봉 · 릴스와 동전 3개";
    const sub = mode === "y5" ? (st.tab === "ds" ? "색 = 5년 과거 시험의 거래 한 건 평균 (레버리지 없이 가격 %) · 참고" : "색 = 5년 과거 시험의 거래 한 건 평균 ROE (증거금 대비) · 참고")
      : mode === "pos" ? "빛나는 칸 = 지금 포지션이 열린 계좌 · % = 지금 평가 ROE (마크 가격)"
      : st.tab === "core" ? (mode === "own" ? "색 = 자기 수익률 (시작 대비) · 칸 구석 ▲ / ▼ = 같은 봉 동전 봇 중앙값보다 위 / 아래 (참고)"
        : "색 = 같은 봉 동전 봇 중앙값과의 차이 (참고) · 크게 잃은 칸도 동전 봇이 더 잃었으면 진한 색입니다") : st.tab === "ds" ? "색 = 자기 수익률 · 계좌마다 동전 봇과 비교하지 않음"
        : "색 = 자기 수익률 · ▲ / ▼ = 5분봉 동전 3개 중앙값보다 위 / 아래 (참고)";
    put(mapCard, h("div", {class: "card-h grid-maph"}, ui.plate(title), st.tab === "core" ? colorBox : st.tab === "ds" ? dsColorBox : null), h("p", {class: "grid-mapsub"}, sub), ...kids);
    // a cell whose colour step changed since the last answer flashes once (real data only, never on the first paint)
    const first = !st.painted;
    for (const a of mapCard.querySelectorAll("a.gk-cell[href]")) {
      const id = decodeURIComponent((a.getAttribute("href") || "").split("/").pop() || "");
      const b = a.dataset.b || "";
      if (!first && st.prev.has(id) && st.prev.get(id) !== b) motion.play(a, "gk-flash");
      st.prev.set(id, b);
    }
    if (first) {
      mapCard.classList.remove("intro"); void mapCard.offsetWidth; mapCard.classList.add("intro");
      ctx.timeout(() => mapCard.classList.remove("intro"), 1400);
    } else if (animate) motion.swap(mapCard);
    st.painted = true;
    paintLegend(mode);
  }

  function paintLegend(mode) {
    const step = (k) => `${fmt.num(BINS[k] * 100, 1)}%p`;
    if (LIVE.has(mode)) { put(legend, liveLegend(mode), linksCard()); return; }
    put(legend,
      ui.card({plate: "읽는 법"},
        scaleStrip(mode),
        h("ul", {class: "grid-keys"},
          mode === "own"
            ? h("li", null, st.tab === "ds" ? "칸 색 = 그 계좌의 자기 수익률 (시작 대비). 딥시크는 계좌마다 동전 봇과 견주지 않고, 위 '중앙값' 줄처럼 묶음으로만 봅니다."
              : st.tab === "m5" ? "릴스 칸 색 = 릴스의 자기 수익률 (시작 대비: 초록 벌었음, 빨강 잃었음). 옆 칸이 비교 기준인 5분봉 동전 3개입니다."
              : "칸 색 = 그 계좌의 자기 수익률 (시작 대비: 초록 벌었음, 빨강 잃었음). 맨 위 줄이 같은 봉 동전 봇 중앙값입니다.")
            : null,
          mode === "own" && st.tab !== "ds"
            ? h("li", null, h("span", {class: "gk-legvs", "aria-hidden": "true"}, "▲▼"), h("span", null, "칸 구석 ▲ / ▼ = 같은 봉 동전 봇 중앙값보다 위 / 아래 (참고, 판정 아님). 차이 크기는 색 '동전 봇 대비'에서 봅니다."))
            : mode === "own" ? null
            : h("li", null, `칸 색 = 그 계좌 수익률에서 같은 봉 동전 봇 3개 중앙값을 뺀 차이. 진할수록 차이가 큽니다 (${step(0)} · ${step(1)} · ${step(2)} · ${step(3)} 기준).`),
          h("li", null, "칸 안 큰 숫자 = 그 계좌 수익률, 작은 숫자 = 닫힌 거래 수."),
          h("li", null, h("span", {class: "gk-cell sw grey", "aria-hidden": "true"}), h("span", null, `빗금 = 거래 ${fmt.int(MIN_COLOR)}건 미만이라 색 없음`)),
          h("li", null, h("span", {class: "gk-cell sw small", dataset: {b: "2"}, "aria-hidden": "true"}), h("span", null, `안쪽 점선 = ${fmt.int(SMALL)}건 미만, 표본 적음 (우연일 수 있음)`)),
          h("li", null, h("span", {class: "gk-cell sw none", "aria-hidden": "true"}), h("span", null, "없음 = 그 봉 계좌가 없음 (딥시크 세션 정의 5개의 4시간)")),
          h("li", null, h("span", {class: "gk-legdot", "aria-hidden": "true"}), h("span", null, "노란 점 = 지금 포지션이 열려 있음 · 파산 = 잔고 10 USDT 미만으로 멈춤"))),
        ui.refNote(verdictTs(), "칸 색은 순위도 판정도 아닙니다."),
        ui.assume("closed", "수익률은 닫힌 거래 기준")),
      linksCard());
  }

  function liveLegend(mode) {
    if (mode === "y5") {
      return ui.card({plate: "읽는 법 · 5년 시험"}, scaleStrip("own"),
        h("ul", {class: "grid-keys"},
          h("li", null, st.tab === "ds" ? "칸 = 그 정의·봉의 5년 과거 시험에서 거래 한 건의 평균 결과 (레버리지 없이 가격 %, 수수료 뒤). 큰 숫자 = 그 평균, 작은 숫자 = 승률."
            : "칸 = 그 매매법·봉의 5년 과거 시험에서 거래 한 건의 평균 ROE (증거금 대비, v3 크기 규칙). 큰 숫자 = 그 평균, 작은 숫자 = 승률."),
          h("li", null, "초록 = 5년 동안 거래당 평균이 + · 빨강 = − . 진할수록 큽니다."),
          h("li", null, "점선 칸 = 5년 자료가 없는 칸 (준비 전)."),
          h("li", null, "칸을 누르면 지금 그 계좌로 갑니다. 지금 성적은 색 '자기 수익률'에서 봅니다.")),
        h("p", {class: "refnote"}, h("b", null, "참고"), " · 5년 과거 시험 · 지금 계좌의 성적도, 판정도, 앞으로의 약속도 아닙니다."));
    }
    return ui.card({plate: "읽는 법 · 지금 포지션"},
      h("ul", {class: "grid-keys"},
        h("li", null, "빛나는 칸 = 지금 포지션이 열린 계좌. 칸 안에 코인·방향·배수와 지금 평가 ROE."),
        h("li", null, "% 는 마크 가격으로 본 미실현 ROE (나갈 때 수수료 전). 5초마다 실제 시세로 바뀝니다."),
        h("li", null, "흐린 칸 = 지금 포지션 없음 · 칸을 누르면 그 계좌.")),
      ui.assume("open"));
  }

  function linksCard() {
    return ui.card({plate: "함께 보기", cls: "grid-links"},
        st.tab === "ds" ? h("a", {class: "lrow click", href: ctx.href("strategies", null, {g: "ds", fam: "all"})}, h("span", {class: "rk"}, "매매법"),
          h("span", {class: "lname"}, "딥시크 17계열 요약"), h("span", {class: "ret"}, "→"),
          h("span", {class: "meta"}, "계열마다 정의·계좌·거래·승률·파산 (셈만, 돈 숫자 없음)")) : null,
        h("a", {class: "lrow click", href: ctx.href("analysis", "map")}, h("span", {class: "rk"}, "분석"), h("span", {class: "lname"}, "코인·장세 지도"), h("span", {class: "ret"}, "→"),
          h("span", {class: "meta"}, "모든 거래를 코인·장세·시간대로 나눠 어디서 벌고 잃었나")),
        h("a", {class: "lrow click", href: ctx.href("digest", "tf")}, h("span", {class: "rk"}, "회의"), h("span", {class: "lname"}, "봉 비교"), h("span", {class: "ret"}, "→"),
          h("span", {class: "meta"}, "매매법마다 봉별 수수료·보유 시간·방향")),
        h("a", {class: "lrow click", href: ctx.href("board", null, {g: st.tab})}, h("span", {class: "rk"}, "홈"), h("span", {class: "lname"}, "순위표"), h("span", {class: "ret"}, "→"),
          h("span", {class: "meta"}, "같은 계좌를 한 줄씩 순서대로")));
  }

  await Promise.all([ctx.store.need("board", 120000).catch(() => null), ctx.store.need("summary", 120000).catch(() => null)]);
  if (!ctx.alive()) return;
  await load(false);
  ctx.every(60000, () => load(false));
  ctx.watch("summary", () => { if (st.d) paintLegend(modeNow()); });
  if (modeNow() === "y5") loadY5();
  // 지금 포지션: the lit cells' ROE follows the shared ticker (5 s); a new board (a position opened / closed) repaints
  ctx.watch("ticker", () => {
    if (modeNow() !== "pos" || !st.d) return;
    const by = accts();
    for (const b of mapCard.querySelectorAll("[data-pos-acct]")) {
      const r = posRoe(by.get(b.dataset.posAcct), markOf);
      if (r == null) continue;
      const txt = fmt.pct(r, 1);
      if (b.textContent !== txt) { b.textContent = txt; b.className = ["num", fmt.tone(r)].filter(Boolean).join(" "); }
    }
  });
  let lastOpen = null;
  ctx.watch("board", (b) => {
    if (!b || modeNow() !== "pos" || !st.d) return;
    const key = (b.accounts || []).filter((a) => a.position).map((a) => a.account_id).join();
    if (lastOpen != null && key !== lastOpen) load(false);
    lastOpen = key;
  });
}

export function update(params) { if (current) current(params); }

export function unmount() { current = null; }
