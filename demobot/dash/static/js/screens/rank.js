// #/rank 설정 순위 (round 5: was 순위표; the accounts screen is 순위표 now): the live ranking of every setting of one
// strategy and timeframe, for one exit, scope and window (/api/rank reads rank_<STRAT>_<tf>.npz), with the luck line,
// the 5-year study's columns and paging. The choices live in the hash (#/rank?strat=S2&tf=15m&...), so a view can be
// bookmarked; the last one is remembered on this device.
// Round 5 stage 2B (the rule bot's v4 board look): the choices as one filter bar (segments, selects, the three filters as
// chips), the four numbers of the view as stat cards that count to new values (luck line, settings shown, minimum
// trades, the median whip), and the v4 dense table whose column heads sort (the server sorts and pages: the same sorts
// as the 정렬 menu). "이 표 읽는 법" behind 더 보기 under the table.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {STRAT_KO, WINDOW_KO, WINDOW_SUB, SORT_KO, SCOPE_KO, tfKo} from "../labels.js";

const DEFAULTS = {strat: "S2", tf: "15m", exit: "0", scope: "ALL", window: "26w", sort: "plateau", dir: "", win60: "", low_whip: "", min_ok: "", q: "", size: "25", page: "0"};
const SIZES = ["25", "50", "100"];
const ASC_FIRST = new Set(["mdd_R", "whip"]);           // smaller is better: these sort low to high unless turned
let GRID = null;           // /api/grid, once per page load

const COLS_KO = [
  ["순위", "지금 고른 정렬 기준으로 몇 번째인지"],
  ["설정", "매매법의 숫자 (ST 기간/배수 …). 기본값 · 친구 값 · 5년 1등 값에는 표시가 붙습니다"],
  ["거래 수", "이 기간에 닫힌 거래 수 (열린 것 빼고)"],
  ["승률", "수수료 뺀 뒤 이익이 난 거래의 비율"],
  ["본전 승률", "평균 이익과 평균 손실로 계산한, 본전이 되는 승률. 승률이 이보다 높아야 남습니다"],
  ["평균 R (수수료 후)", "거래 한 번에 손절 폭의 몇 배를 벌었나 (수수료·슬리피지·펀딩 뺀 뒤)"],
  ["수수료 전 R", "같은 값을 비용 빼기 전에 잰 것"],
  ["비용 R", "거래 한 번에 비용으로 나간 몫 (수수료 전 R − 평균 R)"],
  ["낙폭(R)", "누적 R이 가장 크게 떨어진 폭. 작을수록 덜 아픕니다"],
  ["흔들림", "신호 뒤 3봉 안에 반대 신호가 나온 비율. 높을수록 시끄러운 설정"],
  ["주변 평균(점수)", "이 설정과 바로 옆 설정들 평균 R의 평균. 순위의 기본 기준. 거래 수가 모자라면 비어 있습니다"],
  ["운 기준선", "평균 R이 운 기준선보다 높으면 ✓ (운으로 보기 어려움)"],
  ["5년 성적", "5년 연구에서 같은 설정·같은 청산·같은 범위의 결과: 위는 평균 R, 아래는 승률 (코로나·루나·FTX = 그 폭락 달)"],
];

function readState(query) {
  const saved = local.get("rank", {}) || {};
  const st = {...DEFAULTS, ...saved, ...query};
  for (const k of Object.keys(st)) if (!(k in DEFAULTS)) delete st[k];
  return st;
}
/** A label and its control in the filter bar (v4 board toolbar: the small terminal-font label first). */
const grp = (label, ...kids) => h("span", {class: "k4-barg s2-g"}, h("span", {class: "k4-k"}, label), ...kids);

export async function mount(el, ctx) {
  ctx.setTitle("설정 순위");
  if (!GRID) {
    try { GRID = await ctx.api("/api/grid"); } catch (e) {
      if (e && e.name === "AbortError") return;
      el.append(ui.screenHead("설정 순위"), ui.errorBox(e, () => location.reload()));
      return;
    }
  }
  const st = readState(ctx.params.query);
  // an exit by name (from the home leaders) -> its index
  const exIdx = GRID.exits.findIndex((x) => x.name === st.exit || String(x.i) === String(st.exit));
  st.exit = String(exIdx >= 0 ? exIdx : 0);
  if (!GRID.strategies.some((x) => x.short === st.strat)) st.strat = "S2";
  let user = false;                                       // the next paint follows the viewer's own choice (no count-up)

  const set = (k, v, keepPage) => { st[k] = String(v); if (!keepPage) st.page = "0"; user = true; save(); load(); };
  const save = () => {
    const keep = {};
    for (const k of Object.keys(DEFAULTS)) if (st[k] !== DEFAULTS[k] && k !== "page") keep[k] = st[k];
    local.set("rank", keep);
    ctx.setQuery(keep);
  };
  const effDir = () => st.dir || (ASC_FIRST.has(st.sort) ? "asc" : "desc");

  // ---------------------------------------------------------------- the filter bar
  const stratSeg = ui.seg(GRID.strategies.map((x) => ({id: x.short, label: x.short, title: `${STRAT_KO[x.short] || x.id} · 설정 ${x.settings}개`})),
    st.strat, (v) => set("strat", v), {label: "매매법"});
  const tfSeg = ui.seg(GRID.tfs.map((x) => ({id: x, label: tfKo(x)})), st.tf, (v) => set("tf", v), {label: "봉"});
  const winSeg = ui.seg(GRID.windows.map((x) => ({id: x, label: WINDOW_KO[x] || x, title: WINDOW_SUB[x]})), st.window, (v) => set("window", v), {label: "기간"});
  const exitSel = ui.select(GRID.exits.map((x) => ({id: x.i, label: x.ko})), st.exit, (v) => set("exit", v), "청산");
  const scopeSel = ui.select(GRID.scopes.map((x) => ({id: x, label: SCOPE_KO(x)})), st.scope, (v) => set("scope", v), "범위");
  const sortSel = ui.select(GRID.sorts.map((x) => ({id: x, label: SORT_KO[x] || x})), st.sort, (v) => { st.dir = ""; set("sort", v); }, "정렬");
  const dirBtn = h("button", {type: "button", class: "btn-line dl-dir", title: "정렬 방향 바꾸기"});
  dirBtn.addEventListener("click", () => set("dir", effDir() === "desc" ? "asc" : "desc"));
  const paintDir = () => { dirBtn.textContent = effDir() === "desc" ? "높은 순 ↓" : "낮은 순 ↑"; sortSel.value = st.sort; };
  const t60 = K4.chipToggle("승률 60% 이상만", st.win60 === "1", (v) => set("win60", v ? "1" : ""), "승률이 60% 이상인 설정만");
  const tWhip = K4.chipToggle("흔들림 적은 것만", st.low_whip === "1", (v) => set("low_whip", v ? "1" : ""), "흔들림이 지금 보이는 설정들의 가운데 값 이하인 것만");
  const tMin = K4.chipToggle("최소 거래 수 충족만", st.min_ok === "1", (v) => set("min_ok", v ? "1" : ""), "이 기간의 최소 거래 수를 채운 설정만 (점수가 있는 것)");
  const search = h("input", {class: "search k4-tsearch dl-q", type: "search", placeholder: "설정 찾기 (예: ST 10/6)", "aria-label": "설정 찾기",
    maxlength: "40", value: st.q, autocomplete: "off"});
  let qTimer = null;
  search.addEventListener("input", () => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => {
      const v = search.value.replace(/[^A-Za-z0-9 ./:_x-]/g, "").slice(0, 40);
      set("q", v);
    }, 300);
  });
  const sizeSel = ui.select(SIZES.map((x) => ({id: x, label: `${x}줄씩`})), st.size, (v) => set("size", v), "한 쪽 줄 수");

  const bar = h("div", {class: "s2-ctl", role: "group", "aria-label": "고르기"},
    h("div", {class: "k4-bar"}, grp("매매법", stratSeg), grp("봉", tfSeg), grp("기간", winSeg)),
    h("div", {class: "k4-bar"}, grp("청산", exitSel), grp("범위", scopeSel), grp("정렬", sortSel, dirBtn)),
    h("div", {class: "k4-bar"}, grp("거르기", h("span", {class: "row wrap s2-chips"}, t60, tWhip, tMin))));

  // ---------------------------------------------------------------- the view's numbers (v4 board stat cards)
  const nLuck = K4.liveNum(null, {format: (v) => fmt.r(v), tone: true, flash: "accent"});
  const nShown = K4.liveNum(null, {format: (v) => fmt.int(v), flash: "accent"});
  const nMin = K4.liveNum(null, {format: (v) => `${fmt.int(v)}건`, flash: "accent"});
  const nWhip = K4.liveNum(null, {format: (v) => fmt.ratio(v), flash: "accent"});
  const nAbove = K4.liveNum(null, {format: (v) => fmt.int(v), flash: "accent"});
  const shownSub = h("span", {class: "s"}, "—");
  const aboveSub = h("span", {class: "s"}, "—");
  // the fourth card: the median whip when the 흔들림 filter is on (the server sends it then), else this page's rows over the luck line
  const whipK = h("span", {class: "k"}, "흔들림 가운데 값"), aboveK = h("span", {class: "k"}, "이 쪽 운 기준선 위");
  const whipCard = h("div", {class: "stat"}, whipK, nWhip, h("span", {class: "s"}, "지금 보이는 설정들의 가운데"));
  const aboveCard = h("div", {class: "stat"}, aboveK, nAbove, aboveSub);
  const stats = h("div", {class: "stats s4 s2-stats"},
    K4.stat("운 기준선", nLuck, "무작위 선수 1등이 낼 법한 평균 R (95%)"),
    K4.stat("보이는 설정", nShown, shownSub),
    K4.stat("최소 거래 수", nMin, "이 기간에 점수를 받으려면"),
    whipCard, aboveCard);
  const meta = h("p", {class: "s2-meta"});
  const count = h("span", {class: "muted s2-count"});

  const tableBox = h("div", {class: "dl-rtable"});
  const prev = h("button", {class: "btn-line", type: "button"}, "이전");
  const next = h("button", {class: "btn-line", type: "button"}, "다음");
  const pinfo = h("span", {class: "pinfo"});
  prev.addEventListener("click", () => { set("page", Math.max(0, Number(st.page) - 1), true); });
  next.addEventListener("click", () => { set("page", Number(st.page) + 1, true); });
  const pbar = h("div", {class: "pager"}, prev, pinfo, next);
  const howto = ui.disclosure("이 표 읽는 법 (더 보기)", h("dl", {class: "dl-howcols"},
    COLS_KO.map(([k, v]) => h("div", null, h("dt", null, k), h("dd", null, v)))));
  const info = h("div", {class: "s2-info"}, stats, meta);

  el.append(ui.screenHead("설정 순위", "모든 설정을 같은 조건에서 줄 세운 표 (계좌 순위는 순위표)"), bar, info,
    ui.card({plate: "순위", cls: "dl-rcard s2-rcard", acts: count},
      h("div", {class: "row dl-qrow"}, search, sizeSel), tableBox, pbar, howto));

  let seenKey = null, lastData = null;
  async function load() {
    paintDir();
    const size = Number(st.size) || 25;
    const q = {strat: st.strat, tf: st.tf, exit: st.exit, scope: st.scope, window: st.window, sort: st.sort,
      limit: String(size), offset: String((Number(st.page) || 0) * size)};
    if (st.dir) q.dir = st.dir;
    if (st.win60) q.win60 = "1";
    if (st.low_whip) q.low_whip = "1";
    if (st.min_ok) q.min_ok = "1";
    if (st.q) q.q = st.q;
    const path = "/api/rank?" + new URLSearchParams(q);
    let d;
    try { d = await ctx.api(path); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!lastData) put(tableBox, ui.errorBox(e, load));
      return;
    }
    const key = `${path}|${d.generated_ms}`;
    if (key === seenKey) return;
    seenKey = key;
    lastData = d;
    if (d.offset > 0 && d.total > 0 && d.offset >= d.total) { set("page", Math.max(0, Math.ceil(d.total / size) - 1), true); return; }
    paint(d, size);
  }

  /** A column head click: that sort (again: the other way), like the v4 board table. */
  function sortBy(id) {
    if (st.sort === id) { set("dir", effDir() === "desc" ? "asc" : "desc"); return; }
    st.dir = "";
    set("sort", id);
  }

  function paint(d, size) {
    if (user) for (const n of [nLuck, nShown, nMin, nWhip, nAbove]) delete n.dataset.v;     // the viewer's own change: no count-up
    user = false;
    if (isMissing(d)) {
      put(meta, ui.missing(`${d.short || st.strat} · ${tfKo(st.tf)} 순위 파일`));
      for (const n of [nLuck, nShown, nMin, nWhip, nAbove]) n.update(null);
      shownSub.textContent = "준비 중";
      whipCard.hidden = true; aboveCard.hidden = false; aboveSub.textContent = "준비 중";
      count.textContent = "";
      put(tableBox);
      pbar.hidden = true;
      return;
    }
    const exitKo = (GRID.exits[d.exit] || {}).ko || d.exit_ko;
    nLuck.update(d.luck95);
    nShown.update(d.total);
    nMin.update(d.min_n);
    nWhip.update(d.whip_median);
    whipCard.hidden = d.whip_median == null;
    aboveCard.hidden = d.whip_median != null;
    const judged = d.rows.filter((r) => r.beats_luck != null);
    nAbove.update(judged.filter((r) => r.beats_luck).length);
    aboveSub.textContent = judged.length ? `지금 보이는 ${fmt.int(d.rows.length)}줄 가운데 (판단된 ${fmt.int(judged.length)}줄)` : "이 쪽에 판단할 줄이 없습니다";
    shownSub.textContent = `설정 ${fmt.int(d.settings)}개 중 거르기에 맞는 것`;
    put(meta,
      h("b", null, `${d.short} · ${tfKo(d.tf)}`), ` · ${exitKo} · ${SCOPE_KO(d.scope)} · ${WINDOW_KO[d.window]}`,
      d.bounds_ms ? ` (${fmt.mmdd(d.bounds_ms[0])} ~ ${fmt.mmdd(d.bounds_ms[1])})` : "", " · ",
      h("span", {class: "nowrap"}, `설정 ${fmt.int(d.settings)}개 중 ${fmt.int(d.total)}개`), " · ",
      h("span", {class: "nowrap"}, `최소 거래 수 ${fmt.int(d.min_n)}건`),
      d.whip_median != null ? h("span", {class: "nowrap"}, ` · 흔들림 가운데 값 ${fmt.ratio(d.whip_median)}`) : null,
      d.generated_ms ? h("span", {class: "nowrap muted"}, ` · 자료 ${fmt.kst(d.generated_ms)}`) : null,
      d.past5y ? null : h("span", {class: "s2-warnline"}, " · 5년 성적 파일이 없어 5년 칸은 비워 둡니다."));
    const from = d.total ? d.offset + 1 : 0, to = d.offset + d.rows.length;
    count.textContent = `${SORT_KO[st.sort] || st.sort} ${effDir() === "desc" ? "높은 순" : "낮은 순"} · ${fmt.int(d.total)}개`;
    put(tableBox, d.rows.length ? rankTable(d, st, effDir(), sortBy) : ui.empty("조건에 맞는 설정이 없습니다. 거르기를 줄여 보세요."));
    pinfo.textContent = `${fmt.int(from)}–${fmt.int(to)} / ${fmt.int(d.total)}`;
    prev.disabled = d.offset <= 0;
    next.disabled = to >= d.total;
    pbar.hidden = d.total <= size;
  }

  await load();
  ctx.every(60000, load);
}

function rTone(v) { return fmt.tone(v, fmt.r(v)); }

function pastCell(p) {
  if (!p || p.mean_R == null) return h("span", {class: "muted"}, "—");
  return h("span", {class: "dl-5y", title: `${fmt.int(p.n)}건`},
    h("span", {class: ["num", rTone(p.mean_R)]}, fmt.num(p.mean_R, 3, true)),
    h("small", {class: "muted"}, fmt.ratio(p.win_rate)));
}

/** The v4 dense table (board-table look) with server-side sorting: a head with a sort id is a button. */
function rankTable(d, st, dir, sortBy) {
  const tags = (r) => [r.is_default ? ui.pill("기본값", "accent") : null, r.is_friend ? ui.pill("친구 값", "warn") : null,
    r.is_pick ? ui.pill("5년 1등", "good") : null];
  const cols = [
    {label: "순위", hcls: "dl-c1", cls: "dl-c1", get: (r) => h("span", {class: "rk"}, fmt.int(r.rank))},
    {label: "설정", l: true, hcls: "dl-c2", cls: "dl-c2", get: (r) => h("span", {class: "dl-set"}, h("span", {class: "mono"}, r.label), tags(r))},
    {label: "거래 수", sort: "n", get: (r) => h("span", {class: r.min_ok ? "num" : "num muted", title: r.min_ok ? "" : "최소 거래 수 미달"}, fmt.int(r.n))},
    {label: "승률", sort: "win_rate", get: (r) => h("span", {class: ["num", r.win_rate != null && r.breakeven_win != null && r.win_rate >= r.breakeven_win ? "up" : ""]}, fmt.ratio(r.win_rate))},
    {label: "본전 승률", get: (r) => fmt.ratio(r.breakeven_win)},
    {label: "평균 R (수수료 후)", sort: "mean_R", get: (r) => h("b", {class: ["num", rTone(r.mean_R)]}, fmt.r(r.mean_R))},
    {label: "수수료 전 R", sort: "mean_G", get: (r) => h("span", {class: ["num", rTone(r.mean_G)]}, fmt.r(r.mean_G))},
    {label: "비용 R", get: (r) => fmt.num(r.cost_R, 3)},
    {label: "낙폭(R)", sort: "mdd_R", get: (r) => fmt.num(r.mdd_R, 1)},
    {label: "흔들림", sort: "whip", get: (r) => fmt.ratio(r.whip)},
    {label: "주변 평균(점수)", sort: "plateau", get: (r) => h("span", {class: ["num", rTone(r.plateau)]}, fmt.num(r.plateau, 3, true))},
    {label: "운 기준선", get: (r) => ui.mark(r.beats_luck, r.beats_luck == null ? "" : r.beats_luck ? "위" : "아래")},
  ];
  const periods = d.periods || [];
  if (d.past5y) {
    periods.forEach((p, i) => cols.push({label: (d.periods_ko || [])[i] || p, hcls: i === 0 ? "dl-5yh dl-5y0" : "dl-5yh",
      cls: i === 0 ? "dl-5y0" : "", get: (r) => pastCell(r.past && r.past[p])}));
  }
  const headTop = d.past5y ? h("tr", {class: "dl-htop"}, h("th", {colspan: "12", class: "l dl-c12"}, ""),
    h("th", {colspan: String(periods.length), class: "dl-5yg"}, "5년 성적 (평균 R · 승률)")) : null;
  const head = h("tr", null, cols.map((c) => {
    const on = c.sort && st.sort === c.sort;
    return h("th", {class: [c.l ? "l" : "", c.hcls, on ? "on" : ""], scope: "col", "aria-sort": on ? (dir === "asc" ? "ascending" : "descending") : null},
      c.sort ? h("button", {type: "button", class: "k4-th", title: `${SORT_KO[c.sort] || c.label} 순으로 (한 번 더 누르면 거꾸로)`, onclick: () => sortBy(c.sort)},
        c.label, on ? h("span", {"aria-hidden": "true"}, dir === "asc" ? " ▴" : " ▾") : null) : c.label);
  }));
  return h("div", {class: "tbl-wrap k4-tscroll"}, h("table", {class: "tbl k4-table dl-rank s2-rank"},
    h("caption", {class: "sr"}, "설정 순위"),
    h("thead", null, headTop, head),
    h("tbody", null, d.rows.map((r) => h("tr", {class: r.is_default || r.is_friend || r.is_pick ? "dl-marked" : ""},
      cols.map((c) => { const v = c.get(r); return h("td", {class: [c.l ? "l" : "", c.cls]}, v instanceof Node ? v : v ?? "—"); }))))));
}
