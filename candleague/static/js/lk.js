// The 후보 리그's own pieces for every screen: the shared snapshot (app.js polls it), /api/meta (Korean names, entry
// rules, parameter meanings, each pick's character), the five accounts of a pick, number formats in this league's unit
// (P&L per closed trade as a share of the wallet before it, WATCH_PREREG 2) and the small marks every table uses.
// Money a snapshot does not carry (CANDLEAGUE_DS_MONEY=0) shows as "숨김", never as zero.
import {h, s} from "./dom.js";
import * as fmt from "./fmt.js";
import {getJSON} from "./api.js";
import {pill} from "./ui.js";
import {acctFig} from "./v4kit.js";
import {serverNow} from "./live.js";
import {ROLES, ROLE_KO, ROLE_SHORT, roleId, tfKo, KIND_KO, VERDICT_KO, VERDICT_CLS, STYLE_KO} from "./labels.js";

export const EQUITY = 5000;
const DAY = 86400000;

// ---------------------------------------------------------------- the snapshot and the meta file
let LEAGUE = null, IDX = null, META = null, metaP = null;
export function setLeague(d) { LEAGUE = d; IDX = null; }
export const league = () => LEAGUE;
export async function getMeta() {
  if (META) return META;
  metaP = metaP || getJSON("/api/meta").then((m) => (META = m || {})).catch((e) => { metaP = null; throw e; });
  return metaP;
}
export const metaNow = () => META;

/** Closed trades at a later date if the pace so far (the league's start to the processed time) holds; null before a
 *  full day. */
export function paceAt(d, n, ms) {
  const days = d && d.start_ms ? (d.done_ms - d.start_ms) / DAY : 0;
  if (!(days >= 1) || !(ms > d.done_ms)) return null;
  return Math.round(n + (n / days) * ((ms - d.done_ms) / DAY));
}

/** "이 속도면 12/11에 약 N번 · 01/11에 약 M번" toward the 300-trade condition (2차 and 3차 dates); warn colour when the
 *  last date falls short. Nothing once the count is reached. */
export function paceLine(d, n, min = 300) {
  const cps = (((d && d.watch) || {}).checkpoints || []).filter((c) => c.id !== "C1" && c.ms > d.done_ms);
  const parts = cps.map((c) => ({c, v: paceAt(d, n, c.ms)})).filter((x) => x.v != null);
  if (n >= min || !parts.length) return null;
  const last = parts[parts.length - 1].v;
  return h("small", {class: ["cl-pace", last < min ? "short" : ""]},
    `이 속도면 ${parts.map((x) => `${fmt.mmdd(x.c.ms)}에 약 ${fmt.int(x.v)}번`).join(" · ")}${last < min ? ` (${fmt.int(min)}번 못 미침)` : ""}`);
}

// THE START (owners 10/12, "커스텀값 봇 돌린 시점부터 ... 규칙봇 형식처럼"): the league starts at its install time, every
// account at $5,000 then; the snapshot's start_ms (league meta, the install time floored to 5 minutes) is the one
// source of every "시작부터", "D+n" and "n일째" (no date is written into the page). started_ms is the install time.
/** The league's day in Korea at the engine's processed time (the start's KST date = 1일째; calDay at done_ms), so the
 *  processed day and the calendar day read alike (a start at 12:00 KST is not "1일째" until noon the next day). */
export const leagueDay = (d) => (d && d.start_ms ? calDay(d, d.done_ms) : 0);
/** The calendar day of the league in Korea (the start's KST date = 1일째), whatever the engine has processed: the top
 *  pill's "n일째" (a catch-up does not turn it back). ``now`` defaults to the device's clock. */
const KST_MS = 9 * 3600000;
export const calDay = (d, now = Date.now()) => (d && d.start_ms
  ? Math.max(1, Math.floor((now + KST_MS) / DAY) - Math.floor((d.start_ms + KST_MS) / DAY) + 1) : 0);
/** The "D+n" of the day pill, counted like the rule bot's (paperbot v4 core/shell.js: days gone since the start, the
 *  start day is D+0): started 10/11 -> 10/11 = D+0, 10/12 = D+1. calDay() stays the "n일째" (10/12 = 2일째). */
export const dPlus = (d, now = Date.now()) => (d && d.start_ms ? Math.max(0, calDay(d, now) - 1) : 0);
/** "10/11 12:00": the league's start in Korea time ("—" before the first snapshot). */
export const startKo = (d = LEAGUE) => (d && d.start_ms ? fmt.kst(d.start_ms) : "—");
/** "10/11 12:00 시작부터" (or "시작부터" before the first snapshot). */
export const fromKo = (d = LEAGUE) => (d && d.start_ms ? `${fmt.kst(d.start_ms)} 시작부터` : "시작부터");
/** "D+1 · 10/11 12:00 시작부터 2일째" (the day pill's panel, 요약's 일정). */
export const dayLine = (d, now = Date.now()) => (d && d.start_ms ? `D+${dPlus(d, now)} · ${fromKo(d)} ${calDay(d, now)}일째` : "—");
/** The start lies at the install: a league of the new kind (owners 10/12), nothing before it. False only for an older
 *  snapshot that replayed from 10/01 and was installed later (the start is the install time floored to 5 minutes, so
 *  up to 5 minutes before it). */
export const REPLAY_GAP_MS = 5 * 60000;
export const replayedBefore = (d) => !!(d && Number(d.start_ms) > 0 && Number(d.started_ms) > 0 && d.started_ms - d.start_ms >= REPLAY_GAP_MS);

/** The engine is catching up: the snapshot's own ``catching`` (the engine writes it true only right after a start-over
 *  or a computed chunk while its processed time is more than 30 minutes behind, so a crash loop or a stuck engine never
 *  reads as catching up: it shows by its age and its lag, red); a snapshot without the field (written before 10/12) by
 *  the lag alone. dash.py catching_up is the same rule. */
export const CATCHING_MS = 30 * 60000;
export const catchingUp = (d) => (!d ? false : typeof d.catching === "boolean" ? d.catching
  : !!(d.generated_ms != null && d.done_ms != null && d.generated_ms - d.done_ms > CATCHING_MS));

/** Seconds since the engine wrote its record after which the record counts as late (warn) and stopped (bad): the same
 *  numbers as js/poskit.js SNAP_WARN_S / SNAP_OLD_S and the server's ``old`` flag (dash.py /api/positions), so the
 *  header dot, the 터미널 band and 요약 never say "정상" under a banner that says the engine stopped. */
export const WRITE_WARN_S = 12 * 60;
export const WRITE_OLD_S = 15 * 60;
/** The engine's state for the top dot: ok (up to date), warn (catching up / a little late / not there yet), bad.
 *  Ages are by the dashboard server's clock (live.js serverNow), never the device's alone. */
export function health(d, now = serverNow()) {
  if (!d || !d.accounts) return {lv: "warn", ko: "엔진이 첫 기록을 아직 쓰지 않았습니다"};
  const sinceWrite = Math.max(0, now - (d.generated_ms || 0)), lag = Math.max(0, now - (d.done_ms || 0));
  if (sinceWrite > WRITE_OLD_S * 1000) return {lv: "bad", ko: `엔진 기록이 ${fmt.dur(sinceWrite / 1000)} 전에 멈춤`};
  if (catchingUp(d)) return {lv: "warn", ko: `따라잡는 중 (${fmt.kst(d.done_ms)}까지 계산)`};
  if (sinceWrite > WRITE_WARN_S * 1000) return {lv: "warn", ko: `엔진 기록이 ${fmt.dur(sinceWrite / 1000)} 전 (조금 늦음)`};
  if (lag > 60 * 60000) return {lv: "bad", ko: `처리가 ${fmt.dur(lag / 1000)} 늦음 (시세 연결 확인)`};
  if (lag > 30 * 60000) return {lv: "warn", ko: `처리가 ${fmt.dur(lag / 1000)} 늦음`};
  return {lv: "ok", ko: "정상 (5분마다 처리)"};
}

/** Index of a snapshot: byId, the picks (cand rows), each pick's five accounts. Cached per snapshot. */
export function index(d = LEAGUE) {
  if (IDX && IDX.doc === d) return IDX;
  const byId = {};
  for (const a of (d && d.accounts) || []) byId[a.id] = a;
  const cands = ((d && d.accounts) || []).filter((a) => a.role === "cand");
  const sets = {};
  for (const c of cands) sets[c.id] = Object.fromEntries(ROLES.map((r) => [r, byId[roleId(c, r)] || null]));
  IDX = {doc: d, byId, cands, sets, judge: (d && d.judge) || {}};
  return IDX;
}
/** The pick an account belongs to (itself for a pick; the pick of a 1/4, 청산만 or 동전 account; the first pick of its
 *  cell for a 기본값 account). */
export function pickOf(a, ix = index()) {
  if (!a) return null;
  if (a.role === "cand") return a;
  if (a.of && ix.byId[a.of]) return ix.byId[a.of];
  for (const c of ix.cands) if (Object.values(ix.sets[c.id]).some((x) => x && x.id === a.id)) return c;
  return null;
}

// ---------------------------------------------------------------- names
export const stratKo = (name, meta = META) => (meta && meta.strategies && meta.strategies[name] ? meta.strategies[name].ko : name);
export const stratMeta = (name, meta = META) => (meta && meta.strategies ? meta.strategies[name] : null) || null;
export const pickMeta = (id, meta = META) => (meta && meta.picks ? meta.picks[id] : null) || null;
/** "도지 봇 · 15분" */
export const pickKo = (a, meta = META) => (a ? `${stratKo(a.name, meta)} · ${tfKo(a.tf)}` : "—");
/** The pick's name for a list: the 15분 chip, the Korean name, the code in small print. */
export function pickName(a, o = {}) {
  if (!a) return h("span", null, "—");
  return h("span", {class: ["an", "cl-an"], title: `${a.name} · ${a.id}`}, h("span", {class: "an-tf"}, tfKo(a.tf)),
    h("span", {class: "an-n"}, stratKo(a.name)), o.code === false ? null : h("small", {class: "cl-code"}, a.name),
    a.source && a.source.rank > 1 ? h("small", {class: "cl-code"}, `${a.source.rank}순위`) : null);
}
export const kindChip = (kind) => h("span", {class: ["cl-kind", `k-${kind}`]}, KIND_KO[kind] || kind);
/** The role's coloured square and name (colour never alone: the name is always there). */
export const roleChip = (role, short) => h("span", {class: ["cl-role", `r-${role}`]}, h("i", {"aria-hidden": "true"}), short ? short : ROLE_KO[role]);
export const styleChip = (style) => (style ? h("span", {class: ["cl-style", `s-${style}`]}, STYLE_KO[style]) : null);

/** The account's pixel character (v4kit acctFig): the hue by strategy (all five accounts of a pick look alike), the
 *  role by its head: 동전 a coin, 1/4 a cap, 청산만 a visor, 기본값 grey, 후보 its own hair. aria-hidden. */
const strHue = (s) => { let x = 2166136261; for (const c of String(s)) { x ^= c.codePointAt(0); x = Math.imul(x, 16777619); } return ((x >>> 0) % 12) * 30; };
export function fig(a, size = 20) {
  const role = a && a.role;
  const kind = role === "flip" ? "flip" : role === "quarter" ? "adaptive" : role === "exitonly" ? "friend" : role === "base" ? "base" : "fixed";
  return acctFig({id: (a && a.id) || "", kind}, size, {hue: strHue((a && a.name) || "")});
}
/** 잔고 수익률: the wallet against the $5,000 start (closed trades; a fraction), null when hidden or unknown. */
export const walletRet = (a) => (a && a.wallet != null && Number.isFinite(Number(a.wallet)) ? Number(a.wallet) / EQUITY - 1 : null);
/** The account against its pick's 동전 account on 한 번 평균 (better()): true / false / null (no flip, no trades, hidden). */
export function vsFlip(a, ix = index()) {
  const pk = pickOf(a, ix);
  const flip = pk ? ix.byId[roleId(pk, "flip")] : null;
  if (!a || !flip || flip.id === a.id) return null;
  return better(a, flip);
}

/** True when this account's money is hidden by the server (DeepSeek with CANDLEAGUE_DS_MONEY=0), never for a row that
 *  simply has no trade yet. */
export const dsHidden = (a) => !!a && a.kind === "ds" && !(LEAGUE && LEAGUE.ds_money);

// ---------------------------------------------------------------- numbers (this league's unit)
const hidden = () => h("span", {class: "muted", title: "딥시크 금액 숨김 (CANDLEAGUE_DS_MONEY=0)"}, "숨김");
/** Mean P&L per trade (a fraction): "+0.12%". */
export const retTxt = (x, dec = 2) => (fmt.bad(x) ? "—" : fmt.pct(Number(x) * 100, true, dec));
export function ret(x, o = {}) {
  if (x == null && o.hiddenIf) return hidden();
  if (x == null) return h("span", {class: "muted"}, "—");
  const t = retTxt(x, o.dec ?? 2);
  return h("span", {class: ["num", fmt.tone(x, t)]}, t);
}
export function wallet(a) {
  if (!a) return h("span", {class: "muted"}, "—");
  if (a.wallet == null) return dsHidden(a) ? hidden() : h("span", {class: "muted"}, "—");
  const t = fmt.money(a.wallet);
  return h("span", {class: ["num", fmt.tone(a.wallet - EQUITY, t)]}, t);
}
export function walletChange(a) {
  if (!a || a.wallet == null) return null;
  return (a.wallet / EQUITY - 1) * 100;
}
export const winRate = (a) => (a && a.trades ? (100 * a.wins) / a.trades : null);
export const winTxt = (a) => (a && a.trades ? fmt.pct(winRate(a), false, 0) : "—");
export const ddTxt = (a) => (a && a.max_dd != null ? fmt.pct(a.max_dd * 100, false, 1) : dsHidden(a) ? "숨김" : "—");

/** "↑ 기본값보다" / "↓" mark of a comparison (true / false / null). */
export function vsMark(ok, what, o = {}) {
  if (o.hidden) return h("span", {class: "muted", title: "딥시크 금액 숨김 설정 (CANDLEAGUE_DS_MONEY=0)"}, "숨김");
  if (ok == null) return h("span", {class: "muted", title: o.title || "아직 비교할 거래가 없습니다"}, "—");
  return h("span", {class: ["cl-vs", ok ? "up" : "down"], title: o.title || null}, ok ? "▲" : "▼", what ? ` ${what}` : null);
}
/** a better than b (means per trade) or null. */
export const better = (a, b) => (a && b && a.mean_ret != null && b.mean_ret != null && a.trades && b.trades ? a.mean_ret > b.mean_ret : null);

export function verdictPill(j) {
  const v = (j && j.verdict) || "early";
  return pill(v === "early" ? "아직" : VERDICT_KO[v] || v, VERDICT_CLS[v] || "thin",
    v === "early" ? "닫힌 거래 30번 전: 판단하지 않습니다" : "평균 > 0 · 기본값보다 · 동전보다 (세 가지 다면 통과)");
}
/** The warning light of a core pick (its own backtest band, WATCH_PREREG 3.1): null when there is no band yet. */
export function bandMark(j) {
  if (!j || !j.band) return null;
  return j.band.below
    ? pill(`경고등 · ${fmt.int(j.band.n)}번 기준 아래`, "warn", `백테스트로 본 ${j.band.n}번 평균의 하위 5% (${retTxt(j.band.p5)})보다 낮음: 알림일 뿐 판정 아님`)
    : pill("예상 범위 안", "thin", `백테스트 ${j.band.n}번 평균의 하위 5% ${retTxt(j.band.p5)} 위`);
}
/** What the custom numbers changed, against the same exit on the default numbers (청산만 바꾼 기본값): the trades both
 *  took, the ones only the custom numbers took, the ones the custom numbers left out. pr: {both, cand_only,
 *  default_only} ({n, wins, mean}) from the snapshot's watch. */
export function pairedBox(pr, o = {}) {
  if (!pr) return null;
  const row = (label, x, cls) => h("div", {class: "cl-srow wide"}, h("b", {class: cls || ""}, label),
    h("span", {class: "num"}, `${fmt.int(x.n)}번`), h("span", {class: "num muted"}, x.n ? fmt.pct((100 * x.wins) / x.n, false, 0) : "—"),
    x.mean == null && x.n && o.hidden ? h("span", {class: "muted"}, "숨김") : ret(x.mean));
  return h("div", {class: "cl-sidebox"},
    h("span", {class: "muted"}, "커스텀값이 바꾼 거래 (같은 익절·손절에 기본값 숫자를 쓴 계좌와 비교 · 같은 코인 · 방향을 한 봉 안에 들어가면 같은 거래)"),
    row("둘 다 들어감", pr.both), row("커스텀값만 들어감", pr.cand_only, "accent"), row("커스텀값이 걸러냄", pr.default_only),
    h("p", {class: "note"}, "커스텀값이 도움이 되려면, 새로 들어간 거래의 평균이 좋고 걸러낸 거래의 평균은 나빠야 합니다. 거래가 적으면 운입니다."));
}

/** Where a 후보's mean per trade sits against its own 5-year test (the band at the largest n reached: its 하위 5% and its
 *  중앙값). {key: 0 below 하위 5% / 1 under 중앙값 / 2 at or over it / null not yet, el}. DeepSeek picks have no band. */
export function bandPos(a) {
  const band = a && a.source && a.source.band;
  if (!band) return {key: null, el: h("span", {class: "muted"}, a && a.kind === "ds" ? "범위 없음" : "—")};
  const all = Object.keys(band).map(Number).sort((x, y) => x - y);
  const ns = all.filter((n) => n <= a.trades);
  if (!ns.length || a.mean_ret == null) return {key: null, el: h("span", {class: "muted"}, `${all[0]}번부터`)};
  const n = ns[ns.length - 1], b = band[String(n)];
  const key = a.mean_ret < b.p5 ? 0 : a.mean_ret < b.median ? 1 : 2;
  return {key, el: h("span", {class: ["pp", "thin", key === 0 ? "warn" : ""],
    title: `시험 기간 ${n}번 평균의 범위: 하위 5% ${retTxt(b.p5)} · 중앙값 ${retTxt(b.median)} (지금 ${retTxt(a.mean_ret)})`},
  ["하위 5% 아래", "중앙값 아래", "중앙값 이상"][key])};
}
export const smallN = (n, min = 30) => (n != null && n < min ? h("span", {class: "pp thin", title: `닫힌 거래 ${min}번 미만: 우연일 수 있습니다`}, "표본 적음") : null);

// ---------------------------------------------------------------- the equity line of a pick's accounts (svg, one axis)
/**
 * equityLines([{role, label, points: [[ms, $]...]}], {h}) -> an svg chart: one axis ($), the $5,000 start dashed, each
 * line named at its end and in the legend (never colour alone), a crosshair with every line's value at that time.
 */
export function equityLines(series, o = {}) {
  if (o.until) {
    series = series.map((x) => {
      const p = x.points || [];
      return p.length && p[p.length - 1][0] < o.until ? {...x, points: [...p, [o.until, p[p.length - 1][1]]]} : x;
    });
  }
  const box = h("div", {class: "cl-eq"});
  const legend = h("div", {class: "cl-legend"}, series.map((x) => h("span", null, roleChip(x.role, ROLE_KO[x.role] || x.label))));
  const all = series.flatMap((x) => x.points || []);
  if (all.length < 3) { box.append(legend, h("p", {class: "empty"}, o.empty || "아직 끝난 거래가 없습니다")); return box; }
  // drawn at the box's real width (text stays its size on a phone); redrawn when the width changes
  const H = o.h || 260, T = 12, B = 26;
  const t0 = Math.min(...all.map((p) => p[0])), t1 = Math.max(...all.map((p) => p[0]), t0 + 1);
  let y0 = Math.min(EQUITY, ...all.map((p) => p[1])), y1 = Math.max(EQUITY, ...all.map((p) => p[1]));
  if (y1 - y0 < 1) { y0 -= 50; y1 += 50; }
  const pad = (y1 - y0) * 0.08; y0 -= pad; y1 += pad;
  const wrap = h("div", {class: "cl-eqwrap"});
  const tip = h("div", {class: "cl-tip", hidden: true});
  let drawn = 0;
  function render(W) {
    drawn = W;
    const narrow = W < 560, L = narrow ? 52 : 64, R = narrow ? 58 : 92;
    const X = (t) => L + ((t - t0) / (t1 - t0)) * (W - L - R), Y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
    const kids = [];
    for (let i = 0; i <= 4; i++) {
      const v = y0 + ((y1 - y0) * i) / 4;
      kids.push(s("line", {x1: L, x2: W - R, y1: Y(v), y2: Y(v), class: "gl"}), s("text", {x: L - 6, y: Y(v) + 4, "text-anchor": "end", class: "ax"}, fmt.money(v).replace(/\.\d+$/, "")));
    }
    kids.push(s("line", {x1: L, x2: W - R, y1: Y(EQUITY), y2: Y(EQUITY), class: "base"}));
    kids.push(s("text", {x: L, y: H - 6, class: "ax"}, fmt.mmdd(t0)), s("text", {x: W - R, y: H - 6, "text-anchor": "end", class: "ax"}, fmt.mmdd(t1)));
    const ends = [];
    for (const x of series) {
      const p = x.points || [];
      if (p.length < 2) continue;
      kids.push(s("path", {class: ["ln", `r-${x.role}`], d: p.map((q, i) => `${i ? "L" : "M"}${X(q[0]).toFixed(1)},${Y(q[1]).toFixed(1)}`).join("")}));
      const last = p[p.length - 1];
      ends.push({y: Y(last[1]) + 4, text: ROLE_SHORT[x.role] || x.label, role: x.role});
    }
    ends.sort((a, b) => a.y - b.y);
    for (let i = 1; i < ends.length; i++) ends[i].y = Math.max(ends[i].y, ends[i - 1].y + 15);
    for (const e of ends) kids.push(s("text", {x: W - R + 6, y: e.y, class: ["lab", `r-${e.role}`]}, e.text));
    const cross = s("line", {y1: T, y2: H - B, class: "xh", visibility: "hidden"});
    kids.push(cross);
    const svg = s("svg", {viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "cl-eqsvg", role: "img", "aria-label": o.label || "잔고 그래프"}, kids);
    svg.addEventListener("pointermove", (ev) => {
      const r = svg.getBoundingClientRect();
      const x = ((ev.clientX - r.left) / r.width) * W;
      if (x < L || x > W - R) { cross.setAttribute("visibility", "hidden"); tip.hidden = true; return; }
      const t = t0 + ((x - L) / (W - L - R)) * (t1 - t0);
      cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("visibility", "visible");
      const rows = series.map((q) => {
        let v = null;
        for (const p of q.points || []) { if (p[0] <= t) v = p[1]; else break; }
        return h("div", null, roleChip(q.role, q.label), " ", h("b", {class: "num"}, v == null ? "—" : fmt.money(v)));
      });
      tip.replaceChildren(h("div", {class: "muted"}, `${fmt.kst(t)} KST`), ...rows);
      tip.hidden = false;
      const left = Math.min(ev.clientX - r.left + 12, r.width - 220);
      tip.style.left = `${Math.max(0, left)}px`;
    });
    svg.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); tip.hidden = true; });
    wrap.replaceChildren(svg, tip);
  }
  render(1000);
  if (typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(() => {
      if (!wrap.isConnected) { ro.disconnect(); return; }
      const W = Math.round(wrap.clientWidth);
      if (W > 0 && Math.abs(W - drawn) > 4) render(Math.max(300, W));
    });
    ro.observe(wrap);
  }
  box.append(legend, wrap);
  return box;
}

/** A pick's five accounts as small rows: role, trades, win rate, mean per trade, wallet (the 커스텀값 / 5계좌 cards). */
export function fiveRows(set, o = {}) {
  const head = h("div", {class: ["cl-fiverow", "cl-fivehd"], "aria-hidden": "true"}, h("span", null, "계좌"), h("span", null, "거래"),
    h("span", null, "승률"), h("span", null, o.short ? "평균" : "한 번 평균"), h("span", null, "잔고"), h("span", null, ""));
  return h("div", {class: "cl-five"}, head, ROLES.map((r) => {
    const a = set[r];
    if (!a) return null;
    return h("a", {class: ["cl-fiverow", `r-${r}`], href: `#/account/${encodeURIComponent(a.id)}`, title: `${ROLE_KO[r]} 계좌 자세히`},
      roleChip(r, o.short ? ROLE_SHORT[r] : undefined), h("span", {class: "num"}, `${fmt.int(a.trades)}번`),
      h("span", {class: "num muted"}, winTxt(a)), ret(a.mean_ret, {hiddenIf: dsHidden(a)}), wallet(a),
      a.bust ? pill("파산", "bad") : null);
  }));
}

/** "고정 익절 3R · 손절 2 ATR" -> "익절 3R · 손절 2"; "계단 잠금 10%부터 · 손절 2 ATR" -> "계단 10% · 손절 2" (tables). */
export const exitShort = (ko) => String(ko || "—").replace("고정 익절 수익 ", "익절 수익 ").replace("고정 익절 ", "익절 ")
  .replace("계단 잠금 ", "계단 ").replace("%부터", "%").replace(" ATR", "");

/** The long / short (and per coin) split of a pick or a pool: a row per side with trades, win rate and mean per trade; a
 *  result that rests on one side (or one coin) shows at once. sp: {long, short, coins?} from the snapshot's watch. */
export function sideSplit(sp, o = {}) {
  if (!sp) return h("p", {class: "empty"}, "준비 중");
  const row = (label, cls, x) => h("div", {class: "cl-srow"}, h("span", {class: ["side", cls]}, label),
    h("span", {class: "num"}, `${fmt.int(x.n)}번`), h("span", {class: "num muted"}, x.n ? fmt.pct((100 * x.wins) / x.n, false, 0) : "—"),
    x.mean == null && x.n && o.hidden ? h("span", {class: "muted"}, "숨김") : ret(x.mean));
  const kids = [row("롱", "long", sp.long), row("숏", "short", sp.short)];
  if (sp.coins && Object.keys(sp.coins).length) {
    kids.push(h("div", {class: "cl-scoins"}, Object.entries(sp.coins).sort((a, b) => b[1].n - a[1].n).map(([c, x]) =>
      h("span", {class: "pp thin", title: `${c} ${x.n}번 · 승률 ${x.n ? Math.round((100 * x.wins) / x.n) : 0}%`},
        `${c} ${fmt.int(x.n)}번 `, x.mean == null ? (x.n && o.hidden ? "숨김" : "") : h("b", {class: fmt.tone(x.mean)}, retTxt(x.mean, 1))))));
  }
  return h("div", {class: "cl-split"}, kids);
}
