// 한눈 지도 kit (builder grid): the pieces the map (grid.js), the strategies list (strategies-list.js) and the account
// page (account.js) share. Server: /api/v4/grid (every account's cell), /api/v4/grid/profile/<id or strategy>.
//   bin(v)            a difference / return -> -4..4 (the colour step; thresholds in BINS)
//   heatCell(c, o)    one coloured cell (a link to the account)
//   identicon(id)     a 5 x 5 pixel badge from the strategy's code (the same picture on every screen)
//   spark(v, ghost)   the card's small curve: this account (line + soft area) and the same-timeframe coin flips'
//                     median (dashed ghost), both as returns from the window start, with the 0 line
//   profileCard(...)  the copy-trading style card: name, group chip, curve, 수익률 / 최대 낙폭 / 승률 / 거래 수, the
//                     coin-flip difference (참고), 7일 / 30일
// HONESTY (CONTRACT section 1): a coin-flip comparison never uses the up / down (green / red) colours: it is '참고'
// in the neutral pair (accent above, cyan below; also colour-blind safe) with refNote; a DeepSeek account gets no
// per-account comparison (the 참고 pill and group-level medians only); a coin flip is the yardstick itself; money has
// assume(); fewer than 10 trades = no colour, fewer than 30 = 표본 적음.
import {h, s, ui, fmt, motion, store, local, stratFigure, stratHue, derive} from "../core/pb.js";

/** |difference| thresholds (ratios) of the colour steps 1..4; under the first one = 0 (비슷). */
export const BINS = [0.005, 0.02, 0.05, 0.10];
export const STEP_KO = ["비슷", "조금", "꽤", "많이", "아주 많이"];
export const MIN_COLOR = 10;
export const SMALL = 30;
const KIND_OF = {core: "strategy", ds200: "ds200", reel: "reel", flip: "random"};
const GROUP_PAGE = {core: "core", ds200: "ds", reel: "m5", flip: "coin"};

/** -4..4 for a ratio (sign = above / below), null for none. */
export function bin(v) {
  if (v == null || !Number.isFinite(v)) return null;
  const a = Math.abs(v);
  let k = 0;
  for (const t of BINS) if (a >= t) k++;
  return v < 0 ? -k : k;
}

/** The short Korean name of a cell / profile row ("돈치안·MFI", "FVG 되돌림", "릴스 5분 단타", "동전 봇 2"). */
export function nameOf(x) {
  const strategy = x.s ?? x.strategy, tf = x.tf ?? x.timeframe, g = x.g ?? x.group;
  return fmt.acctParts({kind: KIND_OF[g] || "strategy", strategy, timeframe: tf}).name;
}
export const groupKo = (g) => fmt.GROUP_KO[GROUP_PAGE[g]] || "기타";

/** The first verdict time for refNote (summary: the restart's verdict, else the next checkpoint). */
export function verdictTs() {
  const sm = store.get("summary") || {};
  return (sm.restart && sm.restart.ready && sm.restart.verdict_ts) || (sm.next_checkpoint && sm.next_checkpoint.ts) || null;
}

/** "최근 30일" / "시작 후 9일" (the window covers the whole run so far). */
export function periodKo(d) {
  if (!d) return "";
  if (d.covers_run && d.start) return `시작 후 ${fmt.int(Math.max(1, Math.round((d.now - d.start) / 86400000)))}일`;
  return `최근 ${fmt.int(d.days)}일`;
}

/** A percent that fits a cell: "+3.2%", "−14%". */
export const cellPct = (r) => (r == null ? "—" : fmt.pct(r, Math.abs(r) >= 0.0995 ? 0 : 1));
/** A difference in percentage points, neutral words: "▲ 4.3%p 위" / "▼ 1.2%p 아래" / "= 비슷". */
export function vsWords(v) {
  if (v == null) return "—";
  const k = bin(v);
  if (k === 0) return "= 비슷";
  return `${v > 0 ? "▲" : "▼"} ${fmt.num(Math.abs(v) * 100, 1)}%p ${v > 0 ? "위" : "아래"}`;
}

// ---------------------------------------------------------------- pixel badge
/** The strategy's own pixel character (core/figure.js stratFigure, wave 2 ⑦: body colour by family, hair / cap from the
 *  code, DeepSeek's numbered cap, the reel's phone, a coin head for a coin flip) in the badge frame; the same person on
 *  every screen. Decoration only: aria-hidden. */
export function identicon(id, cls = "") {
  const hue = stratHue(String(id ?? "").split("@")[0]);
  return h("span", {class: ["gk-av", "gk-fig", cls], style: {"--h": hue == null ? 210 : hue}, "aria-hidden": "true"},
    stratFigure({strategy: String(id ?? "").split("@")[0], size: 22}));
}

// ---------------------------------------------------------------- the card's curve
/** spark([ret...], [ret...] | null, {w, h}) -> svg: this account (accent line + soft area), the coin flips' median
 *  (dashed), the 0 line. Values are REAL server points; fewer than 2 -> '곡선 기록 전'. */
export function spark(values, ghost, o = {}) {
  const W = o.w || 300, H = o.h || 72, pad = 3;
  const vs = (values || []).map((v) => (v == null || !Number.isFinite(v) ? null : v));
  const gs = (ghost || []).map((v) => (v == null || !Number.isFinite(v) ? null : v));
  const all = [0, ...vs.filter((v) => v != null), ...gs.filter((v) => v != null)];
  if (vs.filter((v) => v != null).length < 2) return h("div", {class: "gk-spark none"}, ui.notYet("곡선 기록 전", "이 기간 안의 기록이 아직 2점보다 적습니다"));
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi - lo < 0.002) { lo -= 0.001; hi += 0.001; }
  const n = Math.max(vs.length, gs.length);
  const X = (i) => (n < 2 ? 0 : (W * i) / (n - 1)), Y = (v) => pad + (H - 2 * pad) * (1 - (v - lo) / (hi - lo));
  const line = (arr) => arr.map((v, i) => (v == null ? null : `${X(i).toFixed(1)},${Y(v).toFixed(1)}`)).filter(Boolean);
  const pts = line(vs);
  const kids = [s("line", {class: "gk-zero", x1: 0, x2: W, y1: Y(0).toFixed(1), y2: Y(0).toFixed(1)})];
  const last = vs.filter((v) => v != null).slice(-1)[0];
  kids.push(s("path", {class: ["gk-area", last >= 0 ? "pos" : "neg"], d: `M${pts[0].split(",")[0]},${Y(0).toFixed(1)} L${pts.join(" L")} L${pts[pts.length - 1].split(",")[0]},${Y(0).toFixed(1)} Z`}));
  const gp = line(gs);
  if (gp.length > 1) kids.push(s("path", {class: "gk-ghost", d: "M" + gp.join(" L")}));
  kids.push(s("path", {class: "gk-line", d: "M" + pts.join(" L")}));
  return s("svg", {class: "gk-spark", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
    "aria-label": o.label || "잔고 흐름 (시작 대비)"}, kids);
}

/** A tiny list curve (summed balance), no axes: up / down by its end versus its start. */
export function miniSpark(v, o = {}) {
  const xs = (v || []).filter((x) => x != null && Number.isFinite(x));
  if (xs.length < 2) return h("span", {class: "gk-mini none", "aria-hidden": "true"});
  const W = o.w || 64, H = o.h || 22, lo = Math.min(...xs), hi = Math.max(...xs), span = hi - lo || 1;
  const d = "M" + xs.map((x, i) => `${(W * i / (xs.length - 1)).toFixed(1)},${(1 + (H - 2) * (1 - (x - lo) / span)).toFixed(1)}`).join(" L");
  const up = xs[xs.length - 1] >= xs[0];
  const y0 = (1 + (H - 2) * (1 - (xs[0] - lo) / span)).toFixed(1);
  return s("svg", {class: ["gk-mini", up ? "up" : "down"], viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
    "aria-label": o.label || "최근 잔고 흐름"}, s("line", {class: "gk-zero", x1: 0, x2: W, y1: y0, y2: y0}), s("path", {d}));
}

// ---------------------------------------------------------------- one heat cell
/**
 * heatCell(c, {mode: "vs"|"own", href, i, label}) -> a.gk-cell. c: a /api/v4/grid cell. mode "vs": the colour is the
 * difference from the same-timeframe coin-flip median (참고, neutral pair); "own": the account's own return (up / down:
 * money made or lost, a fact). Under MIN_COLOR trades: hatched, no colour; under SMALL: dashed inner line.
 */
export function heatCell(c, o = {}) {
  if (!c) return h("span", {class: "gk-cell none", title: o.noneTitle || "이 봉 계좌가 없습니다"}, h("b", null, "없음"));
  const grey = c.n < MIN_COLOR;
  const v = o.mode === "own" ? c.ret : c.vs;
  const b = grey || c.bust ? null : bin(v);
  const tf = fmt.tfKo(c.tf);
  const words = [`${o.label || nameOf(c)} · ${tf}`, `수익률 ${fmt.pct(c.ret)}`, `거래 ${fmt.int(c.n)}건`];
  if ((o.mode !== "own" || o.vsMark) && c.vs != null) words.push(`같은 봉 동전 봇 중앙값과 ${vsWords(c.vs)} (참고)`);
  if (grey) words.push("거래가 적어 색 없음");
  else if (c.n < SMALL) words.push("표본 적음");
  if (c.open) words.push("지금 포지션 있음");
  if (c.bust) words.push("파산");
  const el = h(o.href ? "a" : "span", {class: ["gk-cell", o.mode === "own" ? "own" : "", grey ? "grey" : "", c.bust ? "bust" : "", !grey && c.n < SMALL ? "small" : ""],
    href: o.href || null, dataset: {b: b == null ? "" : String(b)}, style: o.i != null ? {"--i": o.i} : null,
    title: words.join(" · "), "aria-label": words.join(", ")},
  h("b", {class: "num"}, c.bust ? "파산" : cellPct(c.ret)),
  // vsMark (own colours): the coin-flip comparison only as a small neutral ▲ / ▼ beside the trade count (참고), never the
  // colour (beside the count, not in the corner: a phone cell's corner sits on the return's "%")
  h("small", {class: "num"}, c.open ? h("i", {class: "gk-dot", "aria-hidden": "true"}) : null, `${fmt.int(c.n)}건`,
    o.vsMark && !grey && !c.bust && c.vs != null && c.vs !== 0 ? h("i", {class: "gk-vsm", "aria-hidden": "true"}, c.vs > 0 ? "▲" : "▼") : null));
  return el;
}

// ---------------------------------------------------------------- fill-strat: 5년 시험 and 지금 포지션 cells
/** |per-trade| thresholds of the 5-year colour steps: the 36's ROE on margin ("roe") use BINS; DeepSeek's and the
 *  reel's net price % per trade with no leverage ("1x") are about 30x smaller, so their steps are too. */
export const Y5_BINS_1X = [0.0002, 0.0007, 0.0017, 0.0035];
export function y5Bin(v, unit) {
  if (v == null || !Number.isFinite(v)) return null;
  const t = unit === "1x" ? Y5_BINS_1X : BINS, a = Math.abs(v);
  let k = 0;
  for (const x of t) if (a >= x) k++;
  return v < 0 ? -k : k;
}

/** One 5-year cell: the past test's mean result per trade (big) and win rate (small), coloured up / down (a past
 *  fact, labelled 5년 과거 시험 · 참고; never this account's own record). y = {roe, win, per_day} or null (준비 전). */
export function y5Cell(c, y, unit, o = {}) {
  if (!c) return h("span", {class: "gk-cell none", title: o.noneTitle || "이 봉 계좌가 없습니다"}, h("b", null, "없음"));
  const tf = fmt.tfKo(c.tf), what = unit === "1x" ? "가격 % (레버리지 없이)" : "ROE (증거금 대비)";
  if (!y || y.roe == null) {
    return h(o.href ? "a" : "span", {class: "gk-cell y5 none", href: o.href || null, title: `${o.label || nameOf(c)} · ${tf} · 5년 시험 자료 없음 (준비 전)`},
      h("b", null, "—"), h("small", null, "자료 없음"));
  }
  const words = [`${o.label || nameOf(c)} · ${tf}`, `5년 과거 시험 거래 한 건 평균 ${what} ${fmt.pct(y.roe, 2)}`,
    y.win != null ? `승률 ${fmt.pct(y.win, 0, false)}` : null, y.per_day != null ? `하루 ${fmt.num(y.per_day, 2)}건` : null, "참고 · 지금 계좌의 성적 아님"].filter(Boolean);
  return h(o.href ? "a" : "span", {class: "gk-cell y5", href: o.href || null, dataset: {b: String(y5Bin(y.roe, unit) ?? "")},
    title: words.join(" · "), "aria-label": words.join(", ")},
  h("b", {class: "num"}, fmt.pct(y.roe, unit === "1x" ? 2 : 1)),
  h("small", {class: "num"}, y.win != null ? `승률 ${fmt.pct(y.win, 0, false)}` : "5년"));
}

/** The live ROE of a board account's open position at the mark price (null without a position or a mark). */
export function posRoe(a, mark) {
  if (!a || !a.position) return null;
  const u = derive.livePnl(a.position, mark ? mark(a.position.symbol) : null);
  return u ? u.roe : null;
}

/** One 지금 포지션 cell: lit when its account holds a position (coin, side, leverage, live ROE), dim otherwise. */
export function posCell(c, a, mark, o = {}) {
  if (!c) return h("span", {class: "gk-cell none", title: o.noneTitle || "이 봉 계좌가 없습니다"}, h("b", null, "없음"));
  const p = a && a.position;
  const tf = fmt.tfKo(c.tf);
  if (!p) {
    return h(o.href ? "a" : "span", {class: "gk-cell pos off", href: o.href || null, title: `${o.label || nameOf(c)} · ${tf} · 지금 포지션 없음`},
      h("b", null, "—"), h("small", null, c.bust ? "파산" : "대기"));
  }
  const r = posRoe(a, mark);
  const words = `${o.label || nameOf(c)} · ${tf} · ${fmt.coin(p.symbol)} ${fmt.sideKo(p.side)} ${fmt.lev(p.leverage)} · 지금 평가 ROE (마크 가격, 나갈 때 수수료 전)`;
  return h(o.href ? "a" : "span", {class: "gk-cell pos on", href: o.href || null, title: words, "aria-label": words},
    h("b", {class: ["num", fmt.tone(r)], dataset: {posAcct: a.account_id}}, r == null ? "—" : fmt.pct(r, 1)),
    h("small", null, `${fmt.coin(p.symbol)} ${fmt.sideKo(p.side)} ${fmt.lev(p.leverage)}`));
}

/** The colour scale as a legend strip: lo4 .. lo1, 0, hi1 .. hi4 with words. */
export function scaleStrip(mode) {
  const steps = [-4, -3, -2, -1, 0, 1, 2, 3, 4];
  const cap = (k) => (k === 0 ? `±${fmt.num(BINS[0] * 100, 1)}%p 안` : `${fmt.num(BINS[Math.abs(k) - 1] * 100, 1)}%p+`);
  return h("div", {class: ["gk-scale", mode === "own" ? "own" : ""]},
    h("div", {class: "gk-scale-row"}, steps.map((k) => h("span", {class: "gk-cell sw", dataset: {b: String(k)}, title: cap(k)}))),
    h("div", {class: "gk-scale-words"}, h("span", null, mode === "own" ? "잃음" : "동전 봇보다 아래"), h("span", null, mode === "own" ? "0 근처" : "비슷"),
      h("span", null, mode === "own" ? "벌었음" : "동전 봇보다 위")));
}

// ---------------------------------------------------------------- the profile card
const PERIODS = [{id: "7", label: "7일"}, {id: "30", label: "30일"}];

/**
 * profileCard(ctx, key, {head, onMissing, cls, days, once}) -> {el, load(), set(days)}. once: no money caption of its own
 * (the page says it once; the card keeps its own note).
 * key: an account id (S5_DONCHIAN_MFI@15m) or a strategy name. head: show the name / chips / identicon block (the
 * account page uses it as its title; the strategies list already shows the name). onMissing(): a 404 (an extra
 * account is not on the map: the caller shows its own head).
 */
export function profileCard(ctx, key, o = {}) {
  const st = {days: String(o.days || local.get("gk-days", "30")), d: null, gen: 0};
  if (!PERIODS.some((p) => p.id === st.days)) st.days = "30";
  const body = h("div", {class: "gk-pbody"}, motion.shimmer(3, true));
  const seg = ui.seg(PERIODS, st.days, (id) => { st.days = id; local.set("gk-days", id); load(true); }, {label: "기간"});
  seg.classList.add("gk-period");
  const headSlot = h("div", {class: "gk-phead"});
  const el = h("section", {class: ["card", "gk-profile", o.cls], "aria-label": "매매법 프로필"}, headSlot, body);
  if (!o.head) headSlot.append(h("div", {class: "gk-phead-r"}, o.title ? h("span", {class: "gk-ptitle"}, o.title) : null, seg));

  async function load(animate) {
    const g = ++st.gen;
    let d;
    try { d = await ctx.api(`/api/v4/grid/profile/${encodeURIComponent(key)}?days=${st.days}`); }
    catch (e) {
      if (e && e.name === "AbortError") return;
      if (g !== st.gen) return;
      if (e && e.status === 404 && o.onMissing) { o.onMissing(); return; }
      body.replaceChildren(ui.errorBox(e, () => load(false)));
      return;
    }
    if (g !== st.gen || !ctx.alive()) return;
    st.d = d;
    if (o.head) headSlot.replaceChildren(headBlock(d));
    // (a null part would print as the text "null")
    body.replaceChildren(...(d.group === "ds200" ? dsCounts(ctx, d) : d.kind === "strategy" ? strategyBody(ctx, d) : accountBody(d)).filter((x) => x != null));
    if (animate) motion.swap(body);
  }

  function headBlock(d) {
    const g = d.group;
    const chips = [ui.pill(groupKo(g), g === "core" ? "accent" : ""),
      d.family ? ui.pill(`${d.family} ${d.family_ko || ""}`.trim(), "") : null, d.role_ko ? ui.pill(d.role_ko, "") : null,
      d.bust ? ui.pill("파산", "bad") : null, d.open ? ui.pill("포지션 보유 중", "accent") : null,
      ui.smallSample(d.trades, d.small_n || SMALL)];
    return h("div", {class: "gk-phead-in"}, identicon(d.strategy, "lg"),
      h("div", {class: "gk-pname"}, h("h1", null, nameOf(d), h("span", {class: "gk-ptf"}, ` · ${fmt.tfKo(d.tf)}`)),
        h("div", {class: "gk-chips"}, chips), o.sub ? h("p", {class: "gk-psub"}, o.sub) : null),
      h("div", {class: "gk-phead-r"}, seg));
  }

  function retBlock(ret, label, w0, w) {
    return h("div", {class: "gk-ret"}, h("span", {class: "k"}, label),
      h("b", {class: ["num", fmt.tone(ret, fmt.pct(ret, 2))]}, fmt.pct(ret, 2)),
      w0 != null && w != null ? h("span", {class: "s num"}, `잔고 ${fmt.money(w0)} → ${fmt.money(w)}`) : null);
  }

  function accountBody(d) {
    const ghost = d.spark && d.spark.flip;
    const vsTxt = d.group === "reel" ? `5분봉 동전 ${fmt.int((d.vs_basis || {}).n || 0)}개 중앙값` : `같은 ${fmt.tfKo(d.tf)}봉 동전 봇 중앙값`;
    const curve = h("div", {class: "gk-curve"}, spark(d.spark && d.spark.v, ghost, {label: `${nameOf(d)} 잔고 흐름`}),
      h("div", {class: "gk-legend"}, h("span", {class: "me"}, "이 계좌"), ghost ? h("span", {class: "gh"}, `${vsTxt} (참고)`) : null,
        h("span", {class: "mut"}, `${fmt.mmdd(d.from)} → 지금`)));
    const mddSub = d.covers_run ? "열린 포지션 포함" : "5분 기록 · 열린 포지션 포함";
    const stats = [
      ui.stat("최대 낙폭", d.mdd == null ? "—" : fmt.pct(-d.mdd, 1), mddSub),
      ui.stat("승률", d.win_rate == null ? "—" : fmt.pct(d.win_rate, 0, false), d.trades ? `${fmt.int(d.wins)}승 ${fmt.int(d.trades - d.wins)}패` : "거래 없음"),
      ui.stat("거래 수", `${fmt.int(d.trades)}건`, ui.smallSample(d.trades, d.small_n || SMALL) || "닫힌 거래"),
      vsStat(d, vsTxt)];
    const notes = [];
    if (d.group === "core" || d.group === "reel" || d.group === "ds200") notes.push(ui.refNote(verdictTs(), d.group === "ds200" ? "딥시크는 계좌마다 동전 봇과 비교하지 않습니다." : null));
    // o.once: the page prints the money caption once at its bottom (account.js, owners 10/06 ~14:00): only the card's own words
    notes.push(o.once ? ui.note(`수익률·곡선은 닫힌 거래 기준 · ${periodKo(d)}`) : ui.assume("closed", `수익률·곡선은 닫힌 거래 기준 · ${periodKo(d)}`));
    return [h("div", {class: "gk-top"}, retBlock(d.ret, `수익률 · ${periodKo(d)}`, d.w0, d.w), curve), h("div", {class: "stats s4 gk-stats"}, stats), ...notes];
  }

  function vsStat(d, vsTxt) {
    if (d.group === "flip" || d.baseline) return ui.stat("동전 봇 대비", "비교 기준", "이 계좌가 동전 봇입니다");
    if (d.group === "ds200") {
      const x = d.ds_group || {};
      return ui.stat("동전 봇 대비", h("span", {class: "gk-vs"}, ui.pill("묶음으로만", "ref")),
        `같은 봉 딥시크 ${fmt.int(x.n || 0)}개 중앙값 ${fmt.pct(x.median_ret)} · 동전 봇 ${fmt.pct(x.flip_median_ret)}`);
    }
    const b = d.vs_basis || {};
    return ui.stat("동전 봇 대비", h("b", {class: "gk-vs num"}, vsWords(d.vs)),
      h("span", {class: "s"}, `${vsTxt} ${fmt.pct(b.median_ret)} · `, h("span", {class: "gk-ref"}, "참고")));
  }

  return {el, load: () => load(false), set(days) { st.days = String(days); seg.set(st.days); load(true); }};
}

/** DeepSeek (an account or one definition's accounts): counts only, never money or returns. Owners' D11: DeepSeek
 *  P&L is shown only on the DeepSeek group screen (순위표 · 딥시크). */
export function dsCounts(ctx, d) {
  const strat = d.kind === "strategy";
  const c = strat ? (d.combined || {}) : d;
  const accts = strat ? (d.accounts || []) : [];
  const trades = c.trades || 0, wins = c.wins || 0;
  const busts = strat ? accts.filter((a) => a.bust).length : (d.bust ? 1 : 0);
  const stats = [
    ui.stat("거래 수", `${fmt.int(trades)}건`, strat ? `봉 계좌 ${fmt.int(accts.length)}개 합` : "닫힌 거래"),
    ui.stat("이긴 거래", `${fmt.int(wins)}건`, trades ? `진 거래 ${fmt.int(trades - wins)}건` : "거래 없음"),
    ui.stat("파산", `${fmt.int(busts)}${strat ? "개" : ""}`, strat ? "파산한 봉 계좌" : d.bust ? "이 계좌는 파산" : "아직 없음")];
  const tiles = strat ? h("div", {class: "gk-tfrow own"}, accts.map((a) => h("a", {class: "gk-tf", href: ctx.href("account", a.id)},
    h("span", {class: "k"}, fmt.tfKo(a.tf)), h("span", {class: "num"}, `거래 ${fmt.int(a.trades || 0)}`), a.bust ? ui.pill("파산", "bad") : null))) : null;
  return [h("div", {class: "stats gk-stats s3"}, stats), tiles,
    h("p", {class: "gk-vsline"}, ui.pill("딥시크는 여기서 개수만", "ref"), " 손익은 ",
      h("a", {href: ctx.href("board", null, {g: "ds"})}, "딥시크 화면"), "에서만 봅니다.")];
}

/** The strategy-level card body: combined return + curve, the four numbers, and one cell per timeframe (the map's
 *  own colours; each a link to that account). */
function strategyBody(ctx, d) {
  const c = d.combined || {};
  const ds = d.group === "ds200";
  // review 10/06 (as the map): the colour is each account's own return (a −58 % account is never gold); the coin-flip
  // comparison is the small neutral ▲ / ▼ beside the trade count (참고), DeepSeek without it
  const tiles = h("div", {class: "gk-tfrow own"}, (d.accounts || []).map((a, i) => h("div", {class: "gk-tf"},
    h("span", {class: "k"}, fmt.tfKo(a.tf)),
    heatCell({id: a.id, s: a.strategy, tf: a.tf, g: a.group, ret: a.ret, vs: a.vs, n: a.trades, bust: a.bust, open: a.open},
      {mode: "own", vsMark: !ds, href: ctx.href("account", a.id), i}))));
  const vsLine = ds
    ? h("p", {class: "gk-vsline"}, ui.pill("딥시크는 묶음 중앙값으로만 봅니다", "ref"), " 칸 색 = 자기 수익률")
    : h("p", {class: "gk-vsline"}, h("b", null, "참고"), ` · 칸 색 = 자기 수익률 · 봉 ${fmt.int(c.vs_n || 0)}개 중 같은 봉 동전 봇 중앙값보다 위 ${fmt.int(c.above || 0)} · 아래 ${fmt.int(c.below || 0)} (거래 수 옆 ▲ / ▼)`);
  const stats = [
    // the deepest SINGLE timeframe account (the strategy page's '최대 낙폭 · 합친 곡선' is the summed curve): said so
    ui.stat("최대 낙폭 · 계좌 하나", c.mdd_max == null ? "—" : fmt.pct(-c.mdd_max, 1), "봉 계좌 중 가장 깊었던 하나 (합친 곡선 아님)"),
    ui.stat("승률", c.win_rate == null ? "—" : fmt.pct(c.win_rate, 0, false), c.trades ? `${fmt.int(c.wins)}승 ${fmt.int(c.trades - c.wins)}패` : "거래 없음"),
    ui.stat("거래 수", `${fmt.int(c.trades || 0)}건`, ui.smallSample(c.trades || 0, SMALL) || `봉 계좌 ${fmt.int((d.accounts || []).length)}개 합`)];
  return [
    h("div", {class: "gk-top"},
      h("div", {class: "gk-ret"}, h("span", {class: "k"}, `수익률 · 봉 계좌 ${fmt.int((d.accounts || []).length)}개 합 · ${periodKo(d)}`),
        h("b", {class: ["num", fmt.tone(c.ret, fmt.pct(c.ret, 2))]}, fmt.pct(c.ret, 2)),
        h("span", {class: "s num"}, `잔고 합 ${fmt.money(c.w0)} → ${fmt.money(c.w)}`)),
      h("div", {class: "gk-curve"}, spark(d.spark && d.spark.v, null, {label: "봉 계좌 합산 잔고 흐름"}))),
    h("div", {class: "stats gk-stats s3"}, stats),
    tiles, vsLine,
    ds ? ui.refNote(verdictTs(), "딥시크는 계좌마다 동전 봇과 비교하지 않습니다.") : ui.refNote(verdictTs()),
    ui.assume("closed", `닫힌 거래 기준 · ${periodKo(d)}`)];
}
