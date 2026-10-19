// 실거래 › 순위 › 진입 가능성 (owners 10/19 "각 매매법마다 진입 가능성 몇%, 순위별로 뭐가 제일 진입 가능성이 높은지"):
// /api/v4/livebots/likely (dash/more/livebots.py likely, likely_rows; deploy/combo.live-ac.likely.json). For an hour like this one
// (KST day group 월~목 · 금 · 토 · 일 and hour), how often in the 5-year backtest of the settings the bot runs each strategy's
// entry signal came within 1 / 4 / 24 hours ("최근" 2025-26 the main number, 5년 small), its share of the bot's next
// entries, when in the next 24 hours it tends to come, its break signal waiting now (a countdown), its live signals of the
// week. The server ranks (waits first, then 4 hours, 24 hours, next); the window chips re-rank here by that window.
//   머리    다음 진입은 어느 매매법일까? · the whole bot's line for this hour and its next 24 hours, the window chips
//   시상대  the top three as podium cards; the rest a list of 10 a page
// HONESTY: past frequency, never a forecast, and not a win rate (the 성적 순위 says how they did); a strategy missing from
// the 5-year file says 5년 기준 없음 (never a 0); zeros on the weekend are real (the bot does not enter on weekends); what
// stops an entry now is said on top; the file not there = 수집 전, not read = 못 읽음 + why.
import {h, s, put, ui, fmt, local, motion, stratFigure, stratHue} from "../core/pb.js";
import {sourceState} from "./livebots-kit.js";

export const API = "/api/v4/livebots/likely";
const REFRESH_MS = 30 * 1000;
const WIN_KEY = "lb-likely-win";
export const PODIUM = 3;
const PAGE = 10;
/** The windows: id, the chip, the words after the number. */
export const WINDOWS = [{id: "w1", label: "1시간", ko: "1시간 안에 신호"}, {id: "w4", label: "4시간", ko: "4시간 안에 신호"},
  {id: "w24", label: "24시간", ko: "24시간 안에 신호"}];
const WIN_BY = Object.fromEntries(WINDOWS.map((w) => [w.id, w]));
export const GROUP_KO = {mt: "월~목", fri: "금", sat: "토", sun: "일"};
const TYPE_ID = {"추세": "trend", "되돌림": "pull", "돌파": "brk", "반전": "rev", "박스권": "box"};
const KST = 9 * 3600000, DAY = 86400000;

// ---------------------------------------------------------------- pure functions (node tests: tests/test_dash_livebots_likely_view.py)
const numOr = (x) => (x == null || x === "" || typeof x === "boolean" || !Number.isFinite(Number(x)) ? null : Number(x));
const cmpStr = (a, b) => (String(a) < String(b) ? -1 : String(a) > String(b) ? 1 : 0);
export const winOf = (v) => (WIN_BY[v] ? v : "w4");

/** A share already in percent: under 10 with one decimal ("7.4%"), else whole ("38%"); null: "—". */
export function pk(v) {
  const x = numOr(v);
  return x == null ? "—" : fmt.pctOf(x, x < 10 && x !== 0 ? 1 : 0);
}
/** A row's recent share for a window (null when the 5-year file has none). */
export const shareOf = (r, win, per = "recent") => numOr(r && r.p && r.p[win] && r.p[win][per]);

/** The wait that leads a row (the server's order: touched first, then the closest), or null. */
export const leadWait = (r) => ((r && r.waits) || [])[0] || null;

/**
 * The rows in the order of a window: a strategy with a break signal waiting now first (touched first, then the closest
 * to its level), then by that window's recent share (no share last), then 24 hours, then the share of next entries, then
 * the code. rank is renumbered 1, 2, ... in this order.
 */
export function sortRows(rows, win) {
  const w = winOf(win);
  const key = (r) => {
    const x = leadWait(r);
    const neg = (v) => (v == null ? Infinity : -v);
    return [x ? 0 : 1, x ? (x.touched ? 0 : 1) : 1, x && numOr(x.to_go) != null ? Number(x.to_go) : 9,
      neg(shareOf(r, w)), neg(shareOf(r, "w24")), neg(shareOf(r, "next"))];
  };
  return [...(rows || [])].map((r) => ({r, k: key(r)})).sort((a, b) => {
    for (let i = 0; i < a.k.length; i++) if (a.k[i] !== b.k[i]) return a.k[i] < b.k[i] ? -1 : 1;
    return cmpStr(a.r.strategy, b.r.strategy);
  }).map((x, i) => ({...x.r, rank: i + 1}));
}

/** The largest recent share of a window among the rows (the bars' scale), or null. */
export function barMax(rows, win) {
  const vs = (rows || []).map((r) => shareOf(r, winOf(win))).filter((v) => v != null);
  return vs.length ? Math.max(...vs) : null;
}

/** The bot's line: "지금 같은 시간(월~목 19시)에는 4시간 안에 진입 신호가 나온 적이 38% (5년 42%) · 보통 4.5시간 뒤 다음 신호". */
export function botLine(d, win) {
  const w = winOf(win), c = (d && d.cell) || {}, b = (d && d.bot) || {};
  const v = numOr(b[w] && b[w].recent), a = numOr(b[w] && b[w].all), med = numOr(b.next_h_median && b.next_h_median.recent);
  const when = `${GROUP_KO[c.group] || "—"} ${c.hour == null ? "—" : c.hour}시`;
  const head = v == null ? `지금 같은 시간(${when}) 기록이 없어요`
    : `지금 같은 시간(${when})에는 ${WIN_BY[w].label} 안에 진입 신호가 나온 적이 ${pk(v)}${a != null ? ` (5년 ${pk(a)})` : ""}`;
  return med != null ? `${head} · 보통 ${fmt.num(med, 1)}시간 뒤 다음 신호` : head;
}

/** "월~목 19시 표본: 최근 363시간 · 5년 1,408시간". */
export function samplesLine(c) {
  const sm = (c && c.samples) || {};
  return `${GROUP_KO[c && c.group] || "—"} ${c && c.hour != null ? c.hour : "—"}시 표본: 최근 ${sm.recent == null ? "—" : fmt.int(sm.recent)}시간 · 5년 ${sm.all == null ? "—" : fmt.int(sm.all)}시간`;
}

/** The week's live signals: "이번 주 신호 9개 · 진입 3 · 마지막 10/19 18:50 (돌파 기다림)" or "이번 주 신호 없음". */
export function liveLine(sig, ok = true) {
  if (!ok) return "신호 기록 못 읽음";
  const x = sig || {};
  if (!x.week) return "이번 주 신호 없음";
  return `이번 주 신호 ${fmt.int(x.week)}개 · 진입 ${fmt.int(x.entered_week || 0)}`
    + (x.last_ms ? ` · 마지막 ${fmt.kst(x.last_ms)}${x.last_ko ? ` (${x.last_ko})` : ""}` : "");
}

/** A compact countdown: "4분 53초" / "1시간 02분" / "시간 지남"; unknown "—". */
export function clockKo(ms) {
  if (ms == null || !Number.isFinite(Number(ms))) return "—";
  const sec = Math.floor(Number(ms) / 1000);
  if (sec <= 0) return "시간 지남";
  const hh = Math.floor(sec / 3600), mm = Math.floor((sec % 3600) / 60), ss = sec % 60, two = (n) => String(n).padStart(2, "0");
  return hh ? `${hh}시간 ${two(mm)}분` : `${mm}분 ${two(ss)}초`;
}

/** The ⏳ chip of a waiting row without its countdown: "대기 중 · BCH 롱 · 1.00% 남음" / "돌파함 · 진입 확인 중 · BCH 롱". */
export function waitHead(w) {
  if (!w) return null;
  const who = `${fmt.coin(w.symbol)} ${fmt.sideKo(w.side)}`;
  if (w.touched === true) return `돌파함 · 진입 확인 중 · ${who}`;
  const tg = numOr(w.to_go);
  return `대기 중 · ${who} · ${tg == null ? "기준가 못 읽음" : tg > 0 ? `${fmt.pct(tg, 2, false)} 남음` : "기준가 넘음"}`;
}

/** A 24-hour strip's cells: {t, p, f (0..1 of the strip's own largest), now (the current hour), weekend (KST Sat / Sun)}. */
export function stripCells(hours) {
  const xs = (hours || []).map((x) => ({t: Number(x.t), p: numOr(x.p)}));
  const mx = Math.max(0, ...xs.map((x) => x.p || 0));
  return xs.map((x, i) => ({...x, f: x.p == null ? null : mx > 0 ? x.p / mx : 0, now: i === 0,
    weekend: ((Math.floor((x.t + KST) / DAY) + 3) % 7) >= 5, hour: Math.floor((x.t + KST) / 3600000) % 24}));
}

/** The answer without what changes on its own (the clock, the waits' time left): the same records draw nothing. */
export function sameKey(d) {
  if (!d) return "";
  return JSON.stringify({...d, now_ms: 0, rows: (d.rows || []).map((r) => ({...r, waits: (r.waits || []).map(({left_ms: _l, ...w}) => w)}))});
}

// ---------------------------------------------------------------- pieces
function strip(hours, o = {}) {
  const cells = stripCells(hours);
  if (!cells.length) return null;
  const bars = cells.map((c, i) => s("rect", {class: ["lbl-sc", c.now ? "now" : "", c.weekend ? "wk" : "", c.p == null ? "none" : ""].join(" "),
    x: i * 6 + 0.5, width: 5, y: c.f == null ? 22 : 24 - Math.max(1, Math.round(c.f * 22)), height: c.f == null ? 2 : Math.max(1, Math.round(c.f * 22)), rx: 1},
  s("title", null, `${String(c.hour).padStart(2, "0")}시 ${c.p == null ? "—" : pk(c.p)}${c.weekend ? " (주말: 봇이 진입 안 함)" : ""}`)));
  const svg = s("svg", {class: ["lbl-strip", o.cls || ""].join(" "), viewBox: "0 0 144 24", preserveAspectRatio: "none", role: "img",
    "aria-label": o.label || "앞으로 24시간 신호가 잘 나오는 시간"}, bars);
  if (!o.ticks) return svg;
  const ticks = cells.map((c, i) => (c.now ? h("span", {class: "lbl-tk now", style: {left: `${(i * 6 + 3) / 144 * 100}%`}}, "지금")
    : c.hour % 6 === 0 && i > 1 && i < 23 ? h("span", {class: "lbl-tk", style: {left: `${(i * 6 + 3) / 144 * 100}%`}}, `${c.hour}시`) : null));
  return h("div", {class: "lbl-stripw"}, svg, h("div", {class: "lbl-ticks", "aria-hidden": "true"}, ticks));
}
const typeChip = (t) => (t ? h("span", {class: "lbl-type", dataset: {t: TYPE_ID[t] || "other"}}, t) : null);

/** likelyView(ctx) -> {el}: 진입 가능성 순위 (its own endpoint every 30 s; the wait countdowns every second). */
export function likelyView(ctx) {
  const st = {win: winOf(local.get(WIN_KEY, "w4")), d: null, key: "", okAt: 0, clocks: [], rows: []};
  const seg = ui.seg(WINDOWS.map((w) => ({id: w.id, label: w.label})), st.win, (id) => { st.win = winOf(id); local.set(WIN_KEY, st.win); draw(true); },
    {label: "몇 시간 안에"});
  const stateSlot = h("div", {class: "lb-slot"});
  const srcSlot = h("div", {class: "lb-slot"});
  const botBox = h("div", {class: "lbl-bot"}, motion.shimmer(2));
  const banner = h("div", {class: "lbl-banner"});
  const podium = h("div", {class: "lbl-podium", role: "list", "aria-label": "가장 먼저 진입할 것 같은 셋"});
  const pg = ui.pager({size: PAGE, row: (r) => rowEl(r), empty: () => (!st.d ? motion.shimmer(3) : null)});
  const restHead = h("div", {class: "lbl-resth"});
  const foot = h("div", {class: "lbl-foot"});
  const body = h("div", {class: "lbl-body stack"},
    h("section", {class: "lbl-head", "aria-label": "다음 진입은 어느 매매법일까"},
      h("div", {class: "lbl-htop"}, h("h2", null, "다음 진입은 어느 매매법일까?"), seg), botBox, banner),
    srcSlot, podium, h("div", {class: "lbl-rest"}, restHead, pg.el), foot);
  const el = h("div", {class: "lbl stack"}, stateSlot, body);

  function waitChip(r) {
    const w = leadWait(r);
    if (!w) return null;
    const cd = h("b", {class: "lbl-cd num"}, w.touched ? "" : clockKo(st.okAt + Number(w.left_ms) - Date.now()));
    const chip = h("div", {class: ["lbl-wait", w.touched ? "touched" : "", Number(w.side) > 0 ? "long" : "short"], title: `${fmt.tfKo(w.tf)} 신호 ${fmt.kst(w.t0)} · ${fmt.hm(w.until)}까지 못 넘으면 진입 없음`},
      h("span", {class: "lbl-wi", "aria-hidden": "true"}, w.touched ? "●" : "⏳"), h("span", null, waitHead(w)), w.touched ? null : h("span", {class: "lbl-wsep"}, "·"), w.touched ? null : cd);
    if (!w.touched) st.clocks.push({w, deadline: st.okAt + Number(w.left_ms), cd, chip});
    return chip;
  }
  function bigBlock(r, mx) {
    const v = shareOf(r, st.win), a = shareOf(r, st.win, "all"), nx = shareOf(r, "next");
    if (!r.known) {
      return h("div", {class: "lbl-big none"}, h("b", {class: "lbl-bigv"}, "5년 기준 없음"),
        h("span", {class: "lbl-bigs"}, "이 매매법은 진입 가능성 기준표에 없어요"));
    }
    return h("div", {class: "lbl-big"},
      h("div", {class: "lbl-bigl"}, h("b", {class: "lbl-bigv num"}, pk(v)), h("span", {class: "lbl-bigk"}, WIN_BY[st.win].ko)),
      h("span", {class: "lbl-bar", role: "img", "aria-label": `${WIN_BY[st.win].ko} ${pk(v)}`},
        v != null && mx ? h("i", {style: {width: `${Math.max(2, v / mx * 100).toFixed(1)}%`}}) : null),
      h("span", {class: "lbl-bigs"}, `5년 ${pk(a)} · 다음 진입일 확률 ${pk(nx)}`));
  }
  function meta(r) {
    return h("span", {class: "lbl-meta"}, (r.tfs || []).map((tf) => h("span", {class: "lbl-tf"}, fmt.tfKo(tf))),
      r.n_settings ? h("span", {class: "lbl-nset"}, `세팅 ${fmt.int(r.n_settings)}`) : null);
  }
  function podCard(r, mx, sigOk) {
    const ko = fmt.stratKo(r.strategy);
    return h("div", {class: ["lbl-pod", `r${r.rank}`, leadWait(r) ? "waiting" : ""], role: "listitem", dataset: {t: TYPE_ID[r.type] || "other"},
      style: {"--h": stratHue(r.strategy) ?? 210}},
    waitChip(r),
    h("div", {class: "lbl-ptop"}, h("span", {class: "lbl-prk num"}, fmt.int(r.rank), h("small", null, "위")), typeChip(r.type)),
    h("div", {class: "lbl-pfig", "aria-hidden": "true"}, h("span", {class: "lbl-ring"}), stratFigure({strategy: r.strategy, size: 48, cls: "lbl-fig"})),
    h("div", {class: "lbl-pname"}, h("b", {title: ko}, ko), ko !== r.strategy ? h("code", null, r.strategy) : null),
    meta(r), bigBlock(r, mx),
    r.known ? strip(r.hours, {label: `${ko}: 앞으로 24시간 신호가 잘 나오는 시간`}) : null,
    h("p", {class: "lbl-live"}, liveLine(r.sig, sigOk)));
  }
  function rowEl(r) {
    const d = st.d, ko = fmt.stratKo(r.strategy), sigOk = !d || !d.signals || d.signals.state === "ok";
    return h("div", {class: ["lbl-row", leadWait(r) ? "waiting" : "", r.known ? "" : "unknown"], role: "listitem", dataset: {t: TYPE_ID[r.type] || "other"}},
      h("span", {class: "lbl-rk num"}, fmt.int(r.rank)),
      stratFigure({strategy: r.strategy, size: 28, cls: "lbl-rfig"}),
      h("div", {class: "lbl-rname"}, waitChip(r),
        h("div", {class: "lbl-rn"}, h("b", null, ko), ko !== r.strategy ? h("code", null, r.strategy) : null, typeChip(r.type)),
        meta(r), h("p", {class: "lbl-live"}, liveLine(r.sig, sigOk))),
      r.known ? strip(r.hours, {cls: "row", label: `${ko}: 앞으로 24시간`}) : h("span", {class: "lbl-nostrip"}),
      bigBlock(r, st.mx));
  }
  function tick() {
    const now = Date.now();
    for (const c of st.clocks) {
      const left = c.deadline - now;
      c.cd.textContent = clockKo(left);
      c.chip.classList.toggle("lapsed", left <= 0);
    }
  }
  function drawBanner(d) {
    const parts = [];
    if (d.blocked_ko) {
      parts.push(h("p", {class: "lbl-block", role: "status"}, h("b", null, "지금은 진입 안 해요: "), d.blocked_ko,
        d.pause_until ? ` (${fmt.kst(d.pause_until)}에 풀려요)` : "", h("span", {class: "lbl-blk2"}, " · 풀리면 이 순서예요")));
    }
    const np = d.next_pause;
    if (np && np.from) parts.push(h("p", {class: "lbl-pause"}, `다음 쉬는 시간: ${np.ko || "쉼"} ${fmt.kst(np.from)}부터${np.to ? ` ${fmt.kst(np.to)}까지` : ""}`));
    put(banner, parts);
  }
  function drawFoot(d) {
    put(foot, ui.card({title: "읽는 법", cls: "lbl-how"},
      h("ul", {class: "lbl-howl"},
        h("li", null, h("b", null, "이건 신호가 얼마나 자주 나오는지예요. 이길 확률이 아니에요"), " (이길 확률은 성적 순위)."),
        d && d.note_ko ? h("li", null, d.note_ko) : null,
        h("li", null, "큰 숫자는 '최근'(2025~26년), 작은 '5년'은 2020~26년 전체예요. '다음 진입일 확률'은 봇의 다음 진입이 이 매매법이었던 비율이에요."),
        h("li", null, "막대: 앞으로 24시간, 시간마다 1시간 안에 신호가 나온 비율 (밝은 칸이 지금). 주말 칸이 0인 건 봇이 주말에 진입하지 않아서예요."),
        h("li", null, "⏳ 대기 중 = 신호는 나왔고 돌파를 기다리는 중 (진입 확정 아님). 그래서 맨 앞에 와요."),
        d && d.cell ? h("li", null, samplesLine(d.cell)) : null)));
  }
  function draw(user) {
    const d = st.d;
    st.clocks = [];
    seg.set(st.win);
    if (!d) { put(podium); put(foot); return; }
    if (d.state !== "ok") {
      put(srcSlot, sourceState(d, "진입 가능성 기준표"));
      put(botBox); put(banner); put(podium); put(restHead); pg.set([]); drawFoot(null);
      return;
    }
    put(srcSlot, d.combo && d.combo.state && d.combo.state !== "ok" ? sourceState(d.combo, "합친 봇 설정 (매매법 목록은 기준표에서)") : null);
    const rows = sortRows(d.rows, st.win), mx = barMax(rows, st.win), sigOk = !d.signals || d.signals.state === "ok";
    st.rows = rows; st.mx = mx;
    const b = d.bot || {}, bv = numOr(b[st.win] && b[st.win].recent);
    put(botBox,
      h("div", {class: "lbl-botn"}, h("b", {class: "lbl-botv num"}, pk(bv)), h("span", null, `봇 전체 · ${WIN_BY[st.win].ko}`)),
      h("div", {class: "lbl-botr"}, h("p", {class: "lbl-botl"}, botLine(d, st.win)),
        strip(b.hours, {ticks: true, cls: "bot", label: "봇 전체: 앞으로 24시간 신호가 잘 나오는 시간"})));
    drawBanner(d);
    put(podium, rows.slice(0, PODIUM).map((r) => podCard(r, mx, sigOk)));
    const rest = rows.slice(PODIUM);
    put(restHead, rest.length ? [h("b", null, `${fmt.int(PODIUM + 1)}위부터`), h("span", null, `${fmt.int(rest.length)}개 · ${WIN_BY[st.win].ko} 순`)] : null);
    pg.set(rest, !user);
    if (user) motion.swap(podium);
    drawFoot(d);
    tick();
  }
  async function load() {
    let d;
    try { d = await ctx.api(API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      ui.dim(body, !!st.d);
      if (!st.d) body.hidden = true;
      throw e;
    }
    if (!ctx.alive()) return;
    put(stateSlot);
    ui.dim(body, false);
    body.hidden = false;
    const key = sameKey(d), at = Date.now();
    if (key === st.key) {                               // the same records: keep everything, move the countdowns to the new answer
      const by = new Map((d.rows || []).map((r) => [r.strategy, leadWait(r)]));
      for (const c of st.clocks) {
        const w = [...by.values()].find((x) => x && x.symbol === c.w.symbol && x.t0 === c.w.t0 && x.tf === c.w.tf);
        if (w) c.deadline = at + Number(w.left_ms);
      }
      st.okAt = at;
      return;
    }
    st.key = key; st.d = d; st.okAt = at;
    draw(false);
  }
  draw(false);
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  ctx.every(1000, tick, {now: false});
  return {el};
}
