// 조합 성과 (combo.js): the pieces its three tabs share. Member colours (one hue per member on the avatar
// saturation / lightness tokens, so both skins hold), the correlation colour (the neutral 참고 pair --cmp-hi / --cmp-lo:
// a correlation is neither good nor bad), the picker list (/api/v4/combo/units, kept a minute per page), names, the
// verdict time for refNote, and the sample-size words. Every server string goes in as text (h()).
import {h, s, ui, fmt, store, tok} from "../core/pb.js";
import {progressBar} from "./analysis-kit.js";

/** One hue per member, far apart around the wheel (order = the order the members were picked). */
export const HUES = [205, 330, 145, 35, 265, 95, 0, 175];
export const hueOf = (i) => HUES[i % HUES.length];
/** A swatch / chip colour: CSS reads hsl(var(--h) var(--av-s) var(--av-ring-l)) (combo.css .cb-sw). */
export const swatch = (i, cls) => h("i", {class: ["cb-sw", cls], style: {"--h": hueOf(i)}, "aria-hidden": "true"});

function hslRgb(hh, ss, ll) {
  const a = ss * Math.min(ll, 1 - ll);
  const f = (n) => { const k = (n + hh / 30) % 12; return ll - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)); };
  return [f(0), f(8), f(4)].map((x) => Math.round(x * 255));
}
/** The same member colour as a plain rgb() string for the chart library (computed from the tokens, never typed in). */
export function lineColor(i) {
  const sat = parseFloat(tok("--av-s")) / 100 || 0.45, lig = parseFloat(tok("--av-ring-l")) / 100 || 0.58;
  const [r, g, b] = hslRgb(hueOf(i), sat, lig);
  return `rgb(${r}, ${g}, ${b})`;
}

/** The first verdict time (refNote), from /api/summary in the shared store. */
export function verdictTs() {
  const sm = store.get("summary") || {};
  return (sm.restart && sm.restart.ready && sm.restart.verdict_ts) || (sm.next_checkpoint && sm.next_checkpoint.ts) || null;
}

let unitsHit = null;
/** /api/v4/combo/units, reused for a minute (the picker of every tab). */
export async function loadUnits(ctx, force) {
  if (!force && unitsHit && Date.now() - unitsHit.at < 60000) return unitsHit.d;
  const d = await ctx.api("/api/v4/combo/units");
  unitsHit = {d, at: Date.now()};
  return d;
}

/** {key: {key, name, sub, kind, trades, ret, tf, strategy}} for every pickable unit: a strategy (4 accounts summed),
 *  each of its accounts, the reel. */
export function unitIndex(d) {
  const out = {};
  for (const st of (d && d.strategies) || []) {
    out[st.id] = {key: st.id, strategy: st.id, kind: "strategy", tf: null, name: st.name_ko || fmt.stratKo(st.id),
      sub: "봉 4개 합", trades: st.trades || 0, ret: st.ret, accounts: st.accounts.map((a) => a.id)};
    for (const a of st.accounts || []) {
      out[a.id] = {key: a.id, strategy: st.id, kind: "account", tf: a.tf, name: st.name_ko || fmt.stratKo(st.id),
        sub: `${fmt.tfKo(a.tf)}봉 하나`, trades: a.trades || 0, ret: a.ret, accounts: [a.id]};
    }
  }
  const r = d && d.reel;
  if (r && (r.accounts || []).length) {
    out[r.id] = {key: r.id, strategy: r.id, kind: "reel", tf: "5m", name: r.name_ko || fmt.stratKo(r.id), sub: "5분봉 · 자기 청산",
      trades: r.accounts.reduce((x, a) => x + (a.trades || 0), 0), ret: r.accounts[0].ret, accounts: r.accounts.map((a) => a.id), reel: true};
  }
  return out;
}
/** "슈퍼트렌드·EMA" / "슈퍼트렌드·EMA · 1시간" for a unit key (best effort without the index). */
export function unitName(key, idx) {
  const u = idx && idx[key];
  if (u) return u.kind === "account" ? `${u.name} · ${fmt.tfKo(u.tf)}` : u.name;
  const i = String(key).lastIndexOf("@");
  return i < 0 ? fmt.stratKo(key) : fmt.idName(key);
}

/** A correlation cell's colour: --cmp-hi for together (+), --cmp-lo for opposite (−), the strength as opacity. */
export function corrStyle(r) {
  if (r == null) return {fill: "var(--surface-3)"};
  return {fill: r >= 0 ? "var(--cmp-hi)" : "var(--cmp-lo)", "fill-opacity": String(0.12 + 0.88 * Math.min(1, Math.abs(r)))};
}
export const corrWords = (r) => (r == null ? "—" : r >= 0.7 ? "거의 같이 움직임" : r >= 0.4 ? "꽤 같이 움직임" : r >= 0.15 ? "조금 같이"
  : r > -0.15 ? "따로 움직임" : r > -0.4 ? "조금 반대로" : "반대로 움직임 (헤지)");

/** A small k x k correlation table (SVG-free: a CSS grid of cells, numbers inside). names: short labels. */
export function corrGrid(m, names, o = {}) {
  const k = names.length;
  const cell = (r, i, j) => h("span", {class: ["cb-cc", i === j ? "diag" : "", r == null ? "none" : r >= 0 ? "pos" : "neg"],
    style: r == null || i === j ? null : {"--a": String(0.12 + 0.88 * Math.min(1, Math.abs(r)))},
    title: `${names[i]} · ${names[j]}: ${r == null ? "아직 계산 전" : fmt.num(r, 2)}`}, i === j ? "·" : r == null ? "—" : fmt.num(r, 2));
  return h("div", {class: "cb-cgrid", style: {"--k": k}, role: "table", "aria-label": o.label || "상관 표"},
    h("span", {class: "cb-ch corner", "aria-hidden": "true"}),
    names.map((n, j) => h("span", {class: "cb-ch top", title: n}, o.swatches ? swatch(j) : null, String(j + 1))),
    m.map((row, i) => [h("span", {class: "cb-ch left", title: n0(names[i])}, o.swatches ? swatch(i) : null, String(i + 1)),
      row.map((r, j) => cell(r, i, j))]));
}
const n0 = (x) => String(x || "");

/** The early-days words: "거래 N건 · 아직 판단하기 이릅니다" with the filling bars (trades and days to the floor). */
export function earlyCard(sm, title) {
  if (!sm || !sm.early) return null;
  const bars = [
    {label: `거래 ${fmt.int(sm.need)}건까지`, words: `지금 ${fmt.int(sm.trades)}건 (구성원 거래를 모두 더한 수)`, share: sm.need ? Math.min(1, sm.trades / sm.need) : 1},
    {label: `기록 ${fmt.int(sm.need_days)}일까지`, words: `지금 ${fmt.num(sm.days, 1)}일째`, share: sm.need_days ? Math.min(1, sm.days / sm.need_days) : 1}];
  return ui.card({plate: "채워지는 중", sub: title || "", cls: "an-wait cb-early"},
    h("p", {class: "cb-early-w"}, h("b", null, sm.words)),
    ...bars.map((b) => progressBar(b.label, b.words, b.share)),
    h("p", {class: "an-note"}, "곡선과 숫자는 지금까지의 실제 기록 그대로입니다. 두 기준을 넘기 전에는 어느 조합이 낫다고 말하지 않습니다."));
}

/** "−12.3%" with its tone, or "—". */
export const pctB = (x, dec = 1) => h("b", {class: ["num", fmt.tone(x, fmt.pct(x, dec))]}, fmt.pct(x, dec));
/** Money with its sign and tone. */
export const moneyB = (x) => h("b", {class: ["num", fmt.tone(x, fmt.money(x))]}, fmt.money(x, true));
/** A ratio number (Sharpe-like etc.) or the reason it is not shown yet. */
export const ratioOr = (x, why) => (x == null ? h("b", {class: "num muted"}, "—") : h("b", {class: "num"}, fmt.num(x, 2)));

/** A tiny inline sparkline of a member's return path (the picker chips): drawn only from real numbers. */
export function chipSpark(values, i) {
  const vs = (values || []).filter((v) => v != null && Number.isFinite(v));
  if (vs.length < 2) return null;
  const w = 44, hh = 14, lo = Math.min(...vs, 0), hi = Math.max(...vs, 0), span = hi - lo || 1;
  const d = "M" + vs.map((v, k) => `${(1 + (w - 2) * k / (vs.length - 1)).toFixed(1)},${(hh - 1 - (hh - 2) * (v - lo) / span).toFixed(1)}`).join(" L");
  return s("svg", {class: "cb-cspark", viewBox: `0 0 ${w} ${hh}`, style: {"--h": hueOf(i)}, "aria-hidden": "true"}, s("path", {d}));
}
