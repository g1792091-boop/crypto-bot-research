// 신호 레이더 (fill-radar): how many of each of the 36's entry conditions are on, on the last closed bar.
// Data: /api/v4/radar?tf&symbol (dash/more/radar.py: the same conditions /api/strategy/<name> shows under '지금 조건',
// computed once per bar on the server) and /api/v4/radar/strategy/<name> (6 coins x 4 timeframes for one strategy).
// HONESTY: this is the code's own check of its rules on the bar that just closed, not a forecast ("2/3 on" does not mean
// the third comes next). '신호!' only when the bot really logged a signal on that bar (signal_log); all lamps on without a
// logged signal says '조건 모두 켜짐'. The 36 only (no DeepSeek, no coin flips). Countdowns are the real bar clock.
// Three pieces: radarCard (매매법 목록 top card), radarMatrix (매매법 상세: 코인 × 봉 조건 지도), waitRoom (신호 화면).
import {h, put, ui, fmt, motion, local, bars, serverNow} from "../core/pb.js";

export const RADAR_TFS = ["15m", "30m", "1h", "4h"];
export const RADAR_COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"];
const PHONE_TOP = 12;          // phone: the 12 closest, then 모두 보기
const WIDE_TOP = 18;           // PC: the 18 closest (two columns of 9), then 모두 보기
const HONEST = "레이더는 매매법 코드가 방금 닫힌 봉에서 자기 진입 조건을 하나씩 검사한 결과입니다. 예측이 아닙니다: "
  + "2/3이 켜져 있어도 다음 봉에 나머지가 켜진다는 뜻은 아닙니다. '신호!'는 봇이 그 봉에서 실제로 신호를 기록했을 때만 뜹니다.";

/** Load this piece's stylesheet once (the router loads only the screen's own CSS). */
export function radarCss() {
  if (typeof document === "undefined" || document.querySelector("link[data-radar-css]")) return;
  document.head.append(h("link", {rel: "stylesheet", href: "/static/v4/screens/strategies-radar.css", dataset: {radarCss: "1"}}));
}

// ---------------------------------------------------------------- pure logic (tests/test_dash_fill_radar.py runs these in node)
/** Conditions still off on the closer side; null when neither side has conditions. */
export function leftOf(r) {
  let best = null;
  for (const k of ["long", "short"]) {
    const s = r && r[k];
    if (s && s.of) { const left = s.of - (s.on || 0); best = best == null ? left : Math.min(best, left); }
  }
  return best;
}
/** The closer side: "long" | "short" | null (ties: the larger share on, then long). */
export function sideOf(r) {
  const sh = (k) => (r && r[k] && r[k].of ? (r[k].on || 0) / r[k].of : -1);
  const left = (k) => (r && r[k] && r[k].of ? r[k].of - (r[k].on || 0) : 99);
  if (sh("long") < 0 && sh("short") < 0) return null;
  if (left("long") !== left("short")) return left("long") < left("short") ? "long" : "short";
  return sh("short") > sh("long") ? "short" : "long";
}
/** What a row says: fired (a logged signal) > all on > one left > n left. */
export function stateOf(r) {
  const f = r && r.fired;
  if (f && (f.long || f.short)) return {key: "fired", ko: "신호!", side: f.long ? "long" : "short"};
  const left = leftOf(r);
  if (left == null) return {key: "none", ko: "조건 없음", side: null};
  if (left === 0) return {key: "all", ko: "조건 모두 켜짐", side: sideOf(r)};
  if (left === 1) return {key: "one", ko: "한 칸 남음", side: sideOf(r)};
  return {key: "far", ko: `${left}칸 남음`, side: sideOf(r)};
}
/** Sort key: a logged signal first, then fewest left, then the larger share on. */
export function rankKey(r) {
  const st = stateOf(r), left = leftOf(r);
  const share = Math.max(...["long", "short"].map((k) => (r && r[k] && r[k].of ? (r[k].on || 0) / r[k].of : 0)));
  return [st.key === "fired" ? 0 : 1, left == null ? 99 : left, -share];
}
export function byClose(a, b) {
  const x = rankKey(a), y = rankKey(b);
  for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] - y[i];
  return 0;
}
/** radars: [{symbol, rows}] -> the n closest (strategy, coin) cells across coins. */
export function topCells(radars, n = 15) {
  const all = [];
  for (const d of radars || []) for (const r of (d && d.rows) || []) all.push({...r, symbol: d.symbol, tf: d.tf});
  return all.filter((r) => leftOf(r) != null).sort(byClose).slice(0, n);
}
/** "롱 2/3 · 숏 0/3" */
export const onOf = (r) => `롱 ${(r.long && r.long.on) || 0}/${(r.long && r.long.of) || 0} · 숏 ${(r.short && r.short.on) || 0}/${(r.short && r.short.of) || 0}`;

// ---------------------------------------------------------------- small pieces
/** One side's lamps: lit = on (the condition's name in the tooltip). */
function lamps(side, s, big) {
  if (!s || !s.of) return h("span", {class: "rd-side muted"}, side === "long" ? "롱 —" : "숏 —");
  const names = Array.isArray(s.names) ? s.names : Array.from({length: s.of}, (_, i) => ({name: "", on: i < s.on}));
  return h("span", {class: ["rd-side", side, s.on === s.of ? "full" : s.of - s.on === 1 ? "near" : ""]},
    h("span", {class: "rd-sk"}, side === "long" ? "롱" : "숏"),
    h("span", {class: ["rd-lamps", big ? "big" : ""], "aria-hidden": "true"},
      names.map((c) => h("i", {class: ["rd-lamp", c.on ? "on" : ""], title: `${c.name || "조건"} · ${c.on ? "켜짐" : "꺼짐"}`}))),
    h("b", {class: "rd-n num"}, `${s.on}/${s.of}`));
}
function badge(st) {
  return h("span", {class: ["rd-badge", st.key, st.side || ""]}, st.ko);
}
/** "04:00 봉 기준 · 다음 마감까지 12:34" (live) */
function clockLine(tf, d) {
  const el = h("span", {class: "rd-clock"});
  el.tick = (now) => {
    put(el, d && d.bar_close ? h("span", null, `${fmt.hm(d.bar_close)} 마감 봉 기준`) : h("span", null, "봉 기다리는 중"),
      h("span", {class: "rd-sep"}, " · "), h("span", null, "다음 마감까지 "), h("b", {class: "num"}, bars.closeIn(tf, now)));
  };
  el.tick(serverNow());
  return el;
}
/** Re-read on each bar close: after the close (+ grace for the bars and the signal log), and again while the server
 *  still has the old bar. Returns the time of the next load. */
function nextLoadAt(d, now) {
  if (d && d.next_close && d.next_close > now) return d.next_close + 12000;
  return now + 20000;
}

// ---------------------------------------------------------------- 매매법 목록: 신호 레이더 · 다음 신호까지
export function radarCard(ctx) {
  radarCss();
  const st = {tf: RADAR_TFS.includes(local.get("radar-tf")) ? local.get("radar-tf") : "1h",
    sym: RADAR_COINS.includes(local.get("radar-sym")) ? local.get("radar-sym") : "BTCUSDT", d: null, at: 0, all: false, busy: false, prev: new Map()};
  const coinSel = h("select", {class: "select", "aria-label": "코인"}, RADAR_COINS.map((s) => h("option", {value: s}, fmt.coin(s))));
  coinSel.value = st.sym;
  coinSel.addEventListener("change", () => { st.sym = coinSel.value; local.set("radar-sym", st.sym); st.prev.clear(); load(true); });
  const tfSeg = ui.seg(RADAR_TFS.map((t) => ({id: t, label: fmt.tfKo(t)})), st.tf, (t) => { st.tf = t; local.set("radar-tf", t); st.prev.clear(); load(true); }, {label: "봉"});
  const clock = h("div", {class: "rd-clockrow"});
  const sum = h("div", {class: "rd-sum"});
  const list = h("div", {class: "rd-list", role: "list"}, motion.shimmer(4));
  const more = h("button", {type: "button", class: "btn-line rd-more"}, "모두 보기");
  more.addEventListener("click", () => { st.all = !st.all; el.classList.toggle("all", st.all); more.textContent = st.all ? "접기" : "모두 보기"; });
  const el = ui.card({plate: "신호 레이더", title: "다음 신호까지", h: "h3", cls: "rd-card", acts: [coinSel]},
    h("div", {class: "row wrap rd-ctl"}, tfSeg, clock), sum, list, more, ui.note(HONEST));
  let clk = null;

  function paint(animate) {
    const d = st.d;
    clk = clockLine(st.tf, d);
    put(clock, clk);
    if (!d) { put(list, motion.shimmer(4)); return; }
    if (!d.ready || !Array.isArray(d.rows) || !d.rows.length) {
      put(sum); put(list, ui.notYet(d.why || "준비 전", "서버가 아직 이 코인의 봉을 받지 못했습니다")); more.hidden = true; return;
    }
    const rows = d.rows.slice().sort(byClose);
    const n = {fired: 0, all: 0, one: 0};
    for (const r of rows) { const k = stateOf(r).key; if (n[k] != null) n[k]++; }
    put(sum, h("span", null, `${fmt.coin(d.symbol)} ${fmt.tfKo(d.tf)} · 매매법 ${fmt.int(rows.length)}개`),
      n.fired ? h("span", {class: "rd-badge fired"}, `신호 ${fmt.int(n.fired)}`) : null,
      n.all ? h("span", {class: "rd-badge all"}, `조건 모두 켜짐 ${fmt.int(n.all)}`) : null,
      h("span", {class: ["rd-badge", n.one ? "one" : "far"]}, `한 칸 남음 ${fmt.int(n.one)}`));
    put(list, ...rows.map((r, i) => {
      const s = stateOf(r);
      const a = h("a", {class: ["rd-row", s.key, i >= PHONE_TOP ? "rd-extra" : "", i >= WIDE_TOP ? "rd-extra2" : ""], role: "listitem",
        href: ctx.href("strategies", r.strategy, {tf: d.tf, sym: d.symbol}), title: `${r.strategy} · 차트와 조건 보기`},
        h("span", {class: "rd-rk num"}, String(i + 1)),
        h("span", {class: "rd-name"}, h("b", null, r.ko || fmt.stratKo(r.strategy)), h("small", {class: "muted"}, r.strategy)),
        h("span", {class: "rd-sides"}, lamps("long", r.long), lamps("short", r.short)),
        badge(s));
      const was = st.prev.get(r.strategy);
      if (!animate && was && was !== s.key && (s.key === "one" || s.key === "all" || s.key === "fired")) motion.flash(a, "accent");
      st.prev.set(r.strategy, s.key);
      return a;
    }));
    more.hidden = rows.length <= PHONE_TOP;
    if (animate) motion.swap(list);
  }

  async function load(animate) {
    if (st.busy && !animate) return;               // a coin / timeframe change always loads (a stale answer is dropped)
    st.busy = true;
    const want = `${st.tf}|${st.sym}`;
    try {
      const d = await ctx.api(`/api/v4/radar?tf=${encodeURIComponent(st.tf)}&symbol=${encodeURIComponent(st.sym)}`);
      if (!ctx.alive() || want !== `${st.tf}|${st.sym}`) return;
      st.d = d;
      paint(animate);
    } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!st.d) put(list, ui.errorBox(e, () => load(true)));
    } finally {
      st.busy = false;
      st.at = nextLoadAt(st.d, serverNow());
    }
  }
  ctx.every(1000, () => {
    if (!el.isConnected) return;                 // another group is showing: no fetch, no repaint
    const now = serverNow();
    if (clk) clk.tick(now);
    if (now >= st.at) load(false);
  }, {now: false});
  load(false);
  return {el};
}

// ---------------------------------------------------------------- 매매법 상세: 코인 × 봉 조건 지도
/** opts: {pick(tf, sym): switch the chart, sel(): {tf, sym} now shown}. */
export function radarMatrix(ctx, name, opts = {}) {
  radarCss();
  const body = h("div", {class: "rd-mx-wrap"}, motion.shimmer(4));
  const foot = h("p", {class: "note rd-mx-foot"});
  const el = ui.card({plate: "코인 × 봉 조건 지도", sub: "마지막으로 닫힌 봉 · 누르면 그 차트로", cls: "strat-o3 rd-mxcard"}, body, foot,
    ui.note("칸마다 롱·숏 조건이 몇 개 켜졌는지. 밝게 빛나는 칸이 지금 가장 가까운 곳입니다. 예측이 아니라 코드의 조건 검사 결과입니다."));
  const st = {d: null, at: 0, busy: false, cells: new Map(), selKey: ""};

  function paint() {
    const d = st.d;
    if (!d || !Array.isArray(d.cells)) return;
    const ready = d.cells.filter((c) => c.ready);
    const best = ready.length ? Math.min(...ready.map((c) => (c.left == null ? 99 : c.left))) : null;
    const at = (tf, sym) => d.cells.find((c) => c.tf === tf && c.symbol === sym);
    st.cells.clear();
    const grid = h("div", {class: "rd-mx", role: "grid", style: {"--rd-cols": String(RADAR_TFS.length)}},
      h("span", {class: "rd-mx-h"}, "코인"), RADAR_TFS.map((tf) => h("span", {class: "rd-mx-h", title: `${fmt.tfKo(tf)} 다음 마감`}, fmt.tfKo(tf),
        h("small", {class: "rd-mx-cd num", dataset: {tf}}, bars.closeIn(tf, serverNow())))),
      RADAR_COINS.map((sym) => [h("span", {class: "rd-mx-coin"}, fmt.coin(sym)), RADAR_TFS.map((tf) => {
        const c = at(tf, sym);
        if (!c || !c.ready) return h("span", {class: "rd-mx-cell wait", title: "아직 계산 전"}, "…");
        const s = stateOf(c);
        const glow = c.left != null && best != null && c.left === best && best <= 1;
        const b = h("button", {type: "button", class: ["rd-mx-cell", s.key, glow ? "glow" : ""], title: `${fmt.coin(sym)} ${fmt.tfKo(tf)} · ${onOf(c)} · ${s.ko}`,
          onclick: () => { if (opts.pick) opts.pick(tf, sym); markSel(); }},
          h("span", {class: ["rd-mx-l", c.long.of && c.long.on === c.long.of ? "full" : ""]}, `롱 ${c.long.on}/${c.long.of}`),
          h("span", {class: ["rd-mx-s", c.short.of && c.short.on === c.short.of ? "full" : ""]}, `숏 ${c.short.on}/${c.short.of}`),
          s.key === "fired" ? h("b", {class: "rd-mx-f"}, "신호!") : null);
        st.cells.set(`${tf}|${sym}`, b);
        return b;
      })]));
    put(body, grid);
    st.selKey = "";
    markSel();
    const n1 = ready.filter((c) => c.left === 1).length, n0 = ready.filter((c) => c.left === 0).length;
    foot.textContent = `${fmt.int(ready.length)}/${fmt.int(d.cells.length)}칸 계산됨`
      + (d.pending ? ` · 나머지 ${fmt.int(d.pending)}칸 계산 중` : "")
      + ` · 한 칸 남음 ${fmt.int(n1)}칸` + (n0 ? ` · 조건 모두 켜짐 ${fmt.int(n0)}칸` : "");
  }
  function markSel() {
    const v = opts.sel ? opts.sel() : null;
    const key = v ? `${v.tf}|${v.sym}` : "";
    if (key === st.selKey) return;
    st.selKey = key;
    for (const [k, b] of st.cells) { b.classList.toggle("sel", k === key); b.setAttribute("aria-pressed", String(k === key)); }
  }
  async function load() {
    if (st.busy) return;
    st.busy = true;
    try {
      const d = await ctx.api(`/api/v4/radar/strategy/${encodeURIComponent(name)}`);
      if (!ctx.alive()) return;
      st.d = d;
      paint();
      const now = serverNow();
      // cells still being computed: ask again shortly; else after the next 15-minute close (the soonest timeframe)
      st.at = d.pending ? now + 2500 : bars.barEnd("15m", now) + 12000;
    } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!st.d) put(body, ui.notYet("준비 전", "레이더를 아직 읽지 못했습니다"));
      st.at = serverNow() + 30000;
    } finally { st.busy = false; }
  }
  ctx.every(1000, () => {
    if (!el.isConnected) return;
    const now = serverNow();
    for (const x of body.querySelectorAll(".rd-mx-cd")) x.textContent = bars.closeIn(x.dataset.tf, now);
    markSel();
    if (now >= st.at) load();
  }, {now: false});
  load();
  return {el};
}

// ---------------------------------------------------------------- 신호 화면: 곧 신호 대기실
export function waitRoom(ctx) {
  radarCss();
  const st = {tf: RADAR_TFS.includes(local.get("wait-tf")) ? local.get("wait-tf") : "15m", ds: [], at: 0, busy: false, gen: 0};
  const tfSeg = ui.seg(RADAR_TFS.map((t) => ({id: t, label: fmt.tfKo(t)})), st.tf, (t) => { st.tf = t; local.set("wait-tf", t); st.ds = []; load(true); }, {label: "봉"});
  const clock = h("span", {class: "rd-clock"});
  const sum = h("div", {class: "rd-sum"});
  const list = h("div", {class: "rd-wait", role: "list"}, motion.shimmer(5));
  const el = ui.card({plate: "곧 신호 대기실", sub: "기존 36 · 6코인 · 가장 가까운 15칸", cls: "rd-waitcard"},
    h("div", {class: "row wrap rd-ctl"}, tfSeg, clock), sum, list, ui.note(HONEST, " 딥시크와 동전 봇은 레이더에 넣지 않습니다."));

  function paint(animate) {
    const ok = st.ds.filter((d) => d && d.ready);
    const last = ok.length ? Math.max(...ok.map((d) => d.bar_close || 0)) : null;
    clock.tick = (now) => put(clock, last ? `${fmt.hm(last)} 마감 봉 기준 · ` : "", "다음 마감까지 ", h("b", {class: "num"}, bars.closeIn(st.tf, now)));
    clock.tick(serverNow());
    if (!st.ds.length) { put(list, motion.shimmer(5)); return; }
    if (!ok.length) { put(sum); put(list, ui.notYet("준비 전", "서버가 아직 봉을 받지 못했습니다")); return; }
    const cells = topCells(ok, 15);
    const all = topCells(ok, 1e9);
    const one = all.filter((r) => leftOf(r) === 1).length, fired = all.filter((r) => stateOf(r).key === "fired").length;
    put(sum, h("span", null, `${fmt.int(ok.length)}코인 × 매매법 ${fmt.int(ok[0].rows.length)}개 = ${fmt.int(all.length)}칸 중`),
      fired ? h("span", {class: "rd-badge fired"}, `이 봉 신호 ${fmt.int(fired)}`) : null,
      h("span", {class: ["rd-badge", one ? "one" : "far"]}, `한 칸 남음 ${fmt.int(one)}`),
      ok.length < RADAR_COINS.length ? h("span", {class: "muted"}, `${fmt.int(RADAR_COINS.length - ok.length)}코인 읽는 중`) : null);
    put(list, ...cells.map((r, i) => {
      const s = stateOf(r), side = s.side || sideOf(r);
      return h("a", {class: ["rd-wrow", s.key], role: "listitem", href: ctx.href("strategies", r.strategy, {tf: st.tf, sym: r.symbol})},
        h("span", {class: "rd-rk num"}, String(i + 1)),
        h("b", {class: "rd-coin"}, fmt.coin(r.symbol)),
        h("span", {class: "rd-name"}, h("b", null, r.ko || fmt.stratKo(r.strategy))),
        side ? lamps(side, r[side], true) : null,
        badge(s));
    }));
    if (animate) motion.swap(list);
  }
  async function load(animate) {
    if (st.busy && !animate) return;
    const gen = ++st.gen;
    st.busy = true;
    const tf = st.tf, out = [];
    try {
      for (const sym of RADAR_COINS) {              // one coin at a time (the server computes each once per bar)
        try { out.push(await ctx.api(`/api/v4/radar?tf=${encodeURIComponent(tf)}&symbol=${encodeURIComponent(sym)}`)); }
        catch (e) { if (e && e.name === "AbortError") return; out.push(null); }
        if (!ctx.alive() || gen !== st.gen) return;
        st.ds = out.slice();
        paint(animate && out.length === 1);
      }
    } finally {
      if (gen === st.gen) {
        st.busy = false;
        const ok = out.filter((d) => d && d.ready);
        const nx = ok.length ? Math.min(...ok.map((d) => d.next_close || 0)) : null;
        st.at = nextLoadAt(nx ? {next_close: nx} : null, serverNow());
      }
    }
  }
  ctx.every(1000, () => {
    if (!el.isConnected) return;
    const now = serverNow();
    if (clock.tick) clock.tick(now);
    if (now >= st.at && !st.busy) load(false);
  }, {now: false});
  load(false);
  return {el};
}
