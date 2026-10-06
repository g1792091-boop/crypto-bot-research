// 터미널 coin strip and two of the left column's lists (term v2, owners 10/06: "HelloQuant처럼 촘촘하고 읽기 쉽게").
//   - the coin strip over the chart: the 7 coins, live price and 24 h change (GH Coin's call while that recorder runs);
//     a tap picks the coin for the whole terminal;
//   - 시장 강제청산: the chosen coin's forced liquidations across Binance (/api/liq every 10 s, while the recorder runs:
//     features.liq), dense single-line rows LONG / SHORT · price · $ · age, the 1-hour long / short $ bar beneath;
//     the whole market's, labelled 시장 전체 (우리 봇 아님);
//   - 우리 봇 체결: OUR bots' fills as they happen. Closed trades from /api/trades (then the stream's `trades` events) and
//     entries from the board's positions (a position with a new entry time in a real board update is a new entry).
//     기존 36, the 5분봉 reel and the extra accounts are named one by one; DeepSeek and the coin flips are folded into
//     count rows per minute (no money of theirs here). The recent entries' long / short bar beneath.
// A row that really arrived while the page is open slides in from the top with one brief glow; ages ('6s', '4m') are
// repainted by the terminal's 1 s clock tick (text only).
import {h, put, ui, fmt, motion, bars, features} from "../core/pb.js";
import {panel, ratioBar, ping, ageCell, MARKET_LABEL} from "./terminal-kit.js";
import {hit} from "./terminal-live.js";

const GH_KO = {long: "롱 타점", short: "숏 타점", longWait: "롱 대기", shortWait: "숏 대기", wait: "관망"};
const GH_TONE = {long: "up", longWait: "up", short: "down", shortWait: "down"};
const FOLD = new Set(["ds", "coin"]);             // groups shown as count rows
const GSHORT = {core: "기존 36", ds: "딥시크", m5: "5분봉", coin: "동전 봇", extra: "추가"};
const REASON_SHORT = {SL: "손절", LOCK: "잠금", LIQ: "청산", TP: "익절", HALT: "정지", MANUAL: "수동", END: "종료", TIME: "시간", BAND: "익절"};
const MAX_ROWS = 24;
const live = () => motion.visible() && !motion.reduced();
export const TICK_FRESH_MS = 6000;                 // a coin whose relay price is this fresh keeps it (the ticker is older)
const ROW_GAP_MS = 500;                            // a watchlist row lights at most twice a second

// ---------------------------------------------------------------- coin strip (the watchlist)
/** watchList(ctx, st, onPick) -> {el, setSym, onTicker, onFeatures, onTick} */
export function watchList(ctx, st, onPick) {
  const rows = new Map();
  const list = h("div", {class: "term-wl", role: "listbox", "aria-label": "코인 고르기 (서버 경유 5초 · 실시간 체결이 오면 바로)"}, bars.SYMS.map((s) => {
    const px = h("span", {class: "num term-wpx"}, "—"), chg = h("span", {class: "num term-wch"}, ""), gh = h("span", {class: "term-wgh", hidden: !features.ghcoin});
    const b = h("button", {type: "button", class: "term-wr", role: "option", "aria-selected": String(s === st.sym), onclick: () => onPick(s),
      title: s === "XRPUSDT" ? "XRP: 기록만 (매매하지 않는 코인)" : `${fmt.coin(s)} 보기`},
    h("b", null, fmt.coin(s)), px, chg, gh);
    rows.set(s, {b, px, chg, gh, last: null, at: 0, lit: 0});
    return b;
  }));
  const el = h("nav", {class: "term-coins", "aria-label": "관심 종목"}, list);
  el.head = null;
  let gh = null;
  async function loadGh() {
    const on = features.ghcoin;
    for (const r of rows.values()) r.gh.hidden = !on;
    el.classList.toggle("gh", on);
    if (!on) return;
    try { gh = await ctx.api("/api/ghcoin/board"); } catch (e) { gh = null; }
    if (!ctx.alive()) return;
    for (const [s, r] of rows) {
      const c = gh && gh.coins && gh.coins[s];
      r.gh.textContent = c ? GH_KO[c.state] || c.state || "—" : "—";
      r.gh.className = "term-wgh " + (c ? GH_TONE[c.state] || "muted" : "muted");
      r.gh.title = c && c.why ? `GH 판단: ${c.why}` : "GH 판단";
    }
  }
  ctx.every(300000, loadGh, {now: true});
  return {
    el,
    setSym(s) { for (const [k, r] of rows) r.b.setAttribute("aria-selected", String(k === s)); },
    onTicker(tk) {
      for (const [s, r] of rows) {
        const t = tk[s];
        if (!t) continue;
        const p = Number(t.c ?? t.mark);
        if (Date.now() - r.at > TICK_FRESH_MS) motion.tickPrice(r.px, p, fmt.price(p), s);   // else the relay's is newer
        r.chg.textContent = t.p == null ? "" : fmt.pct(Number(t.p) / 100, 2);
        r.chg.className = "num term-wch " + fmt.tone(t.p);
      }
    },
    onFeatures: loadGh,
    /** One real relay event {s, side, p}: that coin's row shows the traded price and lights once (teal when the
     *  price went up or buyers led, pink when it went down or sellers led), at most twice a second per row. */
    onTick(ev) {
      const r = rows.get(ev.s), p = Number(ev.p);
      if (!r || !Number.isFinite(p) || p <= 0) return;
      const now = Date.now();
      r.at = now;
      if (now - r.lit < ROW_GAP_MS) { r.px.textContent = fmt.price(p); r.px.dataset.pv = String(p); r.px.dataset.pk = ev.s; return; }
      r.lit = now;
      const tone = motion.tickPrice(r.px, p, fmt.price(p), ev.s) || (ev.side === "buy" ? "up" : "down");
      hit(r.b, tone);
    },
  };
}

// ---------------------------------------------------------------- our fills
const groupOfTrade = (t, a) => (a ? fmt.groupOf(a) : fmt.SERVER_GROUP[t.group] || fmt.groupOf({kind: t.kind, timeframe: t.timeframe}));

/** fillsFeed(ctx) -> {el, ready, onBoard(b), onTrades(rows)} */
export function fillsFeed(ctx) {
  const st = {ev: [], seen: new Set(), board: null, byId: new Map(), nodes: new Map(), seeded: false};
  const list = h("div", {class: "term-feed term-fl", role: "list", "aria-live": "off"});
  const ratio = ratioBar([{key: "L", label: "롱", tone: "up"}, {key: "S", label: "숏", tone: "down"}], {label: "최근 진입 롱·숏"});
  const ratioK = h("span", {class: "term-rbk"}, "최근 진입");
  const el = panel("우리 봇 체결", {cls: "term-fills", sub: "딥시크·동전 봇은 건수만", scroll: true}, list);
  el.append(h("div", {class: "term-pf"}, h("div", {class: "term-rbrow"}, ratioK, ratio), ui.assume()));

  const add = (e, isLive) => {
    if (st.seen.has(e.key)) return false;
    st.seen.add(e.key);
    e.live = isLive;
    st.ev.push(e);
    return true;
  };
  const entryOf = (a, p, isLive) => ({key: `e:${a.account_id}:${p.entry_time}`, t: Number(p.entry_time) || 0, kind: "entry", g: fmt.groupOf(a),
    id: a.account_id, sym: p.symbol, side: Number(p.side) > 0 ? 1 : -1, lev: p.leverage, price: p.entry ?? p.entry_price, live: isLive});
  const fromTrade = (t, isLive) => {
    const a = st.byId.get(t.account_id), g = groupOfTrade(t, a);
    const out = [{key: `x:${t.id}`, t: Number(t.exit_time) || 0, kind: "exit", g, id: t.account_id, sym: t.symbol, side: Number(t.side) > 0 ? 1 : -1,
      lev: t.leverage, pnl: t.pnl, roe: t.roe, reason: t.exit_reason, price: t.exit_price}];
    if (t.entry_time) out.push({key: `e:${t.account_id}:${t.entry_time}`, t: Number(t.entry_time), kind: "entry", g, id: t.account_id, sym: t.symbol,
      side: Number(t.side) > 0 ? 1 : -1, lev: t.leverage, price: t.entry_price});
    return out;
  };

  // rows: one per named fill; DeepSeek / coin flips folded per group, kind and minute
  function models() {
    const ev = st.ev.sort((x, y) => y.t - x.t || (x.kind === "exit" ? -1 : 1)).slice(0, 400);
    st.ev = ev;
    const out = [], fold = new Map();
    for (const e of ev) {
      if (out.length >= MAX_ROWS) break;
      if (!FOLD.has(e.g)) { out.push({id: e.key, one: e, live: e.live, t: e.t}); continue; }
      const k = `${e.g}:${e.kind}:${Math.floor(e.t / 60000)}`;
      let m = fold.get(k);
      if (!m) { m = {id: "f:" + k, g: e.g, kind: e.kind, t: e.t, n: 0, L: 0, S: 0, win: 0, liq: 0, syms: new Set(), live: false}; fold.set(k, m); out.push(m); }
      m.n++; if (e.side > 0) m.L++; else m.S++;
      if (e.kind === "exit") { if (e.pnl > 0) m.win++; if (e.reason === "LIQ") m.liq++; }
      m.syms.add(fmt.coin(e.sym));
      if (e.live) m.live = true;
    }
    return out;
  }
  const sigOf = (m) => (m.one ? m.id : `${m.id}:${m.n}:${m.win}:${m.liq}`);
  const tagOf = (e) => (e.kind === "entry" ? h("span", {class: "term-tag in"}, "진입")
    : h("span", {class: ["term-tag", e.reason === "LIQ" ? "liq" : e.pnl > 0 ? "up" : "down"], title: fmt.reasonKo(e.reason)}, REASON_SHORT[e.reason] || fmt.reasonKo(e.reason)));
  function rowOf(m) {
    if (m.one) {
      const e = m.one, a = st.byId.get(e.id);
      const right = e.kind === "exit" ? h("b", {class: ["num", "term-fv", fmt.tone(e.pnl)]}, fmt.money(e.pnl, true)) : h("span", {class: "num term-fv muted"}, fmt.price(e.price));
      const what = `${fmt.coin(e.sym)} ${fmt.sideKo(e.side)} ${fmt.lev(e.lev)}${e.kind === "exit" && e.roe != null ? ` · ROE ${fmt.pct(e.roe, 0)}` : ""}`;
      return h("a", {class: ["term-fr", "fl", e.g], role: "listitem", href: ctx.href("account", e.id), title: `${e.id} · ${what} · ${fmt.kst(e.t)}`},
        ageCell(e.t), tagOf(e),
        h("span", {class: "term-fn"}, h("i", {class: ["term-gsw", e.g], "aria-hidden": "true"}), a ? ui.acctLabel(a) : fmt.idName(e.id)),
        h("span", {class: "term-fc"}, fmt.coin(e.sym), " ", h("span", {class: e.side > 0 ? "up" : "down"}, fmt.sideKo(e.side))),
        right);
    }
    const detail = m.kind === "entry" ? `롱 ${fmt.int(m.L)} · 숏 ${fmt.int(m.S)}` : `이김 ${fmt.int(m.win)}${m.liq ? ` · 강제청산 ${fmt.int(m.liq)}` : ""}`;
    const what = `${fmt.int(m.n)}건`;
    return h("div", {class: ["term-fr", "fl", "fold", m.g], role: "listitem", title: `${GSHORT[m.g]} ${what} · ${detail} · ${[...m.syms].join("·")} (건수만)`},
      ageCell(m.t), h("span", {class: ["term-tag", m.kind === "entry" ? "in" : "n"]}, m.kind === "entry" ? "진입" : "청산"),
      h("span", {class: "term-fn"}, h("i", {class: ["term-gsw", m.g], "aria-hidden": "true"}), h("span", null, `${GSHORT[m.g]} · ${what}`)),
      h("span", {class: "term-fc muted"}, [...m.syms].slice(0, 2).join("·")),
      m.g === "ds" ? ui.pill("", "ref") : h("span", {class: "muted term-fv term-fbase"}, "기준"));
  }
  function render() {
    const ms = models();
    const nodes = [];
    for (const m of ms) {
      const sig = sigOf(m), was = st.nodes.get(m.id);
      if (was && was.sig === sig) { nodes.push(was.node); continue; }
      const node = rowOf(m);
      st.nodes.set(m.id, {sig, node});
      nodes.push(node);
      if (m.live && live()) {
        const tone = m.one && m.one.kind === "exit" ? (m.one.reason === "LIQ" || m.one.pnl < 0 ? "down" : "up") : null;
        if (was) motion.flash(node, null); else motion.fillIn(node, tone);
      }
    }
    const keep = new Set(ms.map((m) => m.id));
    for (const k of st.nodes.keys()) if (!keep.has(k)) st.nodes.delete(k);
    for (const e of st.ev) e.live = false;
    if (!nodes.length) put(list, ui.empty("아직 체결이 없습니다"));
    else list.replaceChildren(...nodes);
    if (ms.some((m) => m.live) && live()) ping(el);
    // long / short share of the last 100 entries (every group: the market side our bots took; counts, not money)
    let L = 0, S = 0, n = 0;
    for (const e of st.ev) { if (e.kind !== "entry") continue; if (e.side > 0) L++; else S++; if (++n >= 100) break; }
    ratioK.textContent = `최근 진입 ${fmt.int(n)}건`;
    ratio.set({L, S});
  }

  async function seed() {
    let rows = [];
    try { rows = await ctx.api("/api/trades?limit=120"); } catch (e) { if (e && e.name === "AbortError") return; }
    if (!ctx.alive()) return;
    for (const t of rows || []) for (const e of fromTrade(t, false)) add(e, false);
    st.seeded = true;
    render();
  }
  const ready = seed();
  return {
    el, ready,
    onBoard(b) {
      st.board = b;
      st.byId = new Map(b.accounts.map((a) => [a.account_id, a]));
      const first = !st.boardSeen;
      st.boardSeen = true;
      let any = false;
      for (const a of b.accounts) {
        const p = a.position;
        if (!p || !p.entry_time) continue;
        if (add(entryOf(a, p, !first), !first)) any = true;
      }
      if (any || first) render();
    },
    onTrades(rows) {
      let any = false;
      for (const t of rows || []) for (const e of fromTrade(t, true)) if (add(e, e.kind === "exit")) any = true;
      if (any) render();
    },
  };
}

// ---------------------------------------------------------------- market liquidations (feature: the recorder runs)
const usdK = (x) => (x >= 1e6 ? `${fmt.num(x / 1e6, 2)}M` : x >= 1e3 ? `${fmt.num(x / 1e3, 1)}K` : fmt.num(x, 0));

/** liqFeed(ctx, st) -> {el, setSym, onFeatures}: /api/liq of the chosen coin every 10 s (as 차트's tab) while the recorder runs. */
export function liqFeed(ctx, st, onNew) {
  const list = h("div", {class: "term-feed term-liq", role: "list"});
  const ratio = ratioBar([{key: "long", label: "롱", tone: "up"}, {key: "short", label: "숏", tone: "down"}], {label: "최근 1시간 강제청산된 롱·숏 금액"});
  const ratioK = h("span", {class: "term-rbk"}, "1시간");
  const el = panel("시장 강제청산", {cls: "term-liqp", sub: "", scroll: true}, list);
  el.append(h("div", {class: "term-pf"}, h("div", {class: "term-rbrow"}, ratioK, ratio),
    h("p", {class: "note term-blab", title: "바이낸스는 코인마다 1초에 1건만 알려 줘서 실제보다 적게 잡힙니다"}, h("b", null, `바이낸스 ${MARKET_LABEL}`), " · 코인마다 1초에 1건만 기록")));
  const seen = new Set();
  let sym = null, busy = false, last = {sym: null, rows: []};
  async function load() {
    el.hidden = !features.liq;
    if (!features.liq || busy || (sym === st.sym && !el.getClientRects().length)) return;      // on screen only (the first answer always)
    busy = true;
    const want = st.sym, fresh = sym !== want;
    try {
      const d = await ctx.api(`/api/liq?symbol=${encodeURIComponent(want)}&minutes=60`);
      if (want !== st.sym || !ctx.alive()) return;
      if (fresh) { seen.clear(); sym = want; }
      el.sub.textContent = `${fmt.coin(want)} · 1시간 ${fmt.int(d.n || 0)}건 · 시장 전체`;
      if (!d.recorder) { put(list, ui.empty("강제청산 기록기 자료가 없습니다")); ratio.set({}); return; }
      const rows = (d.rows || []).slice(0, 20);
      const had = last.sym === want ? last.rows.length : -1;
      last = {sym: want, rows};
      let nNew = 0;                                // rows that really arrived since the last answer
      const arrived = [];                          // ... and the rows themselves (the chart flashes once for them)
      put(list, rows.length ? rows.map((r) => {
        const k = `${r.ts}:${r.usd}:${r.price}`, isNew = !fresh && !seen.has(k);
        seen.add(k);
        const lg = r.liquidated === "long";
        const node = h("div", {class: ["term-fr", "liq", lg ? "lg" : "sh", r.usd >= 100000 ? "bigl" : ""], role: "listitem",
          title: `${fmt.coin(want)} ${lg ? "롱" : "숏"} 포지션 강제청산 · ${fmt.price(r.price)} · $${usdK(r.usd)} · ${fmt.kst(r.ts)} (${MARKET_LABEL})`},
        h("span", {class: ["term-lb", lg ? "up" : "down"]}, lg ? "LONG" : "SHORT"),
        h("span", {class: "num term-lp"}, fmt.price(r.price)), h("b", {class: "num term-lu"}, "$" + usdK(r.usd)), ageCell(r.ts));
        if (isNew) nNew++;
        if (isNew) arrived.push(r);
        if (isNew && live()) motion.fillIn(node, lg ? "up" : "down");
        return node;
      }) : ui.empty("최근 1시간 기록 없음"));
      ratio.set({long: d.long_usd || 0, short: d.short_usd || 0}, (n, sh) => `${fmt.pct(sh, 0, false)} · $${fmt.compact(n)}`);
      if (nNew && live()) ping(el);
      // the chart flashes once for the really new ones
      if ((nNew || had !== rows.length) && onNew) onNew(arrived);
    } catch (e) { if (!(e && e.name === "AbortError") && fresh) put(list, ui.errorBox(e, load)); }
    finally { busy = false; }
  }
  ctx.every(10000, load, {now: true});
  return {el, load, setSym() { put(list, motion.shimmer(3)); load(); }, onFeatures: load,
    /** The last loaded liquidations of ``s`` (none for another coin, or before the first answer). */
    recent: (s) => (features.liq && last.sym === s ? last.rows : [])};
}
