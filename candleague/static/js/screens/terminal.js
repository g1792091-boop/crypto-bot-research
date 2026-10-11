// #/terminal 터미널 (the rule bot's v4 terminal look, as the demo lab's: thin charcoal panels with an accent tick):
//   top     the six coins (price, 24 h change, the league's open positions on it) and the chosen coin's line (price,
//           24 h high / low, volume, mark, funding and the time to the next one, the bar close countdown, KST clock)
//   left    the chosen account (grouped by role) with its numbers against its own 기본값 and 동전, its custom values
//   centre  the candles (15분 · 30분 · 1시간 · 4시간, Korea time) with that account's entries ▲▼ and exits ● on this coin,
//           and its open position's entry, stop and take-profit lines
//   right   this coin's open league positions and the league's newest fills (a row picks that account / coin / trade)
//   bottom  the chosen account's closed trades (a row moves the chart to that trade)
// Data: /api/live every 5 s, /api/klines every 10 s (the dashboard server reads Binance's public data and caches it; the
// browser never talks to Binance), the shared snapshot, /api/fills and /api/trades/<id>. ?acct=&coin=&tf=&at= pick one.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {loadLwc, color, tok} from "../chart.js";
import {COINS, TFS, TF_MS, tfKo, ROLES, ROLE_KO, sideKo, reasonKo, coinOf, coinShort} from "../labels.js";
import {paramTable} from "./custom.js";

const two = (x) => String(x).padStart(2, "0");
const priceDec = (p) => { const a = Math.abs(Number(p) || 0); return a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1; };
const px = (p) => (fmt.bad(p) ? "—" : fmt.num(p, priceDec(p)));
function mmss(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${s >= 3600 ? `${Math.floor(s / 3600)}:` : ""}${two(Math.floor((s % 3600) / 60))}:${two(s % 60)}`;
}
function bigUsd(x) {
  if (fmt.bad(x)) return "—";
  const v = Number(x);
  return v >= 1e8 ? `${fmt.num(v / 1e8, 1)}억 USDT` : v >= 1e4 ? `${fmt.num(v / 1e4, 0)}만 USDT` : `${fmt.num(v, 0)} USDT`;
}
const panel = (title, sub, ...kids) => h("section", {class: "lv-p"}, h("div", {class: "lv-ph"}, h("h2", null, title), sub ? h("span", {class: "lv-phs"}, sub) : null), ...kids);

export async function mount(el, ctx) {
  let meta = null;
  try { meta = await ctx.meta(); } catch (e) { /* codes */ }
  const q = ctx.params.query || {};
  const st = {coin: COINS.includes(q.coin) ? q.coin : "BTCUSD", tf: TFS.includes(q.tf) ? q.tf : null, acct: q.acct || null,
    at: q.at ? Number(q.at) : null, live: null, fills: [], book: null};
  const strip = h("div", {class: "lv-strip", role: "tablist", "aria-label": "코인"});
  const headBox = h("div", {class: "lv-head"});
  const acctSel = h("span");
  const acctCard = h("div", {class: "lv-pb"});
  const tfBar = h("div", {class: "lv-tfs", role: "tablist", "aria-label": "봉"});
  const cbox = h("div", {class: "lv-cbox", "aria-label": "캔들 차트 (한국 시각)"});
  const legend = h("div", {class: "lv-legend"});
  const cmsg = h("div", {class: "lv-cmsg", hidden: true});
  const openBox = h("div", {class: "lv-pb scroll cl-tside"});
  const fillBox = h("div", {class: "lv-pb scroll cl-tside"});
  const tradeBox = h("div", {class: "lv-tabbody"});
  const tradeSub = h("span", {class: "lv-phs"});
  el.append(h("div", {class: "lv-term"},
    h("div", {class: "lv-top"}, h("div", {class: "lv-stripwrap"}, strip), headBox),
    h("div", {class: "lv-grid"},
      h("div", {class: "lv-left"}, h("section", {class: "lv-p"}, h("div", {class: "lv-ph"}, h("h2", null, "고른 계좌"), acctSel), acctCard)),
      h("section", {class: "lv-p lv-chartp"}, h("div", {class: "lv-ph"}, h("h2", null, "차트"), h("span", {class: "lv-phs"}, "한국 시각 · 고른 계좌의 거래만"), h("span", {class: "grow"}), tfBar),
        h("div", {class: "lv-pb"}, h("div", {class: "lv-cwrap"}, cbox, legend, cmsg)),
        h("div", {class: "lv-cfoot"}, h("div", {class: "lv-ckey"},
          h("span", null, h("i", {class: "k-ar"}), "진입 (롱 ▲ · 숏 ▼)"), h("span", null, h("i", {class: "k-dot"}), "청산 (이유 · 증거금 대비)"),
          h("span", null, h("i", {class: "k-up"}), "익절선"), h("span", null, h("i", {class: "k-dn"}), "손절선")))),
      h("div", {class: "lv-right"},
        panel("이 코인 열린 포지션", "후보 리그 190계좌", openBox),
        panel("최근 체결", "후보 리그 전체 · 누르면 그 계좌", fillBox)),
      h("section", {class: "lv-p lv-tablep"}, h("div", {class: "lv-ph"}, h("h2", null, "이 계좌 거래"), tradeSub), h("div", {class: "lv-pb"}, tradeBox)))));

  // ------------------------------------------------------------ the chart
  let chart = null, candles = null, vol = null, plines = [], key = null, first = null, last = null, ro = null;
  const L = await loadLwc().catch(() => null);
  if (!ctx.alive()) return;
  if (L) {
    const kstTick = (t, type) => {
      const d = new Date(t * 1000 + 9 * 3.6e6);
      if (type === 0) return String(d.getUTCFullYear());
      if (type === 1) return `${d.getUTCMonth() + 1}월`;
      if (type === 2) return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
      return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`;
    };
    chart = L.createChart(cbox, {width: cbox.clientWidth || 600, height: cbox.clientHeight || 400,
      layout: {background: {color: tok("--surface")}, textColor: tok("--ink-2"), fontSize: 12, fontFamily: tok("--f-body")},
      grid: {vertLines: {color: tok("--line")}, horzLines: {color: tok("--line")}},
      rightPriceScale: {borderColor: tok("--line-2"), scaleMargins: {top: 0.08, bottom: 0.22}},
      timeScale: {borderColor: tok("--line-2"), timeVisible: true, secondsVisible: false, rightOffset: 6, tickMarkFormatter: kstTick},
      crosshair: {mode: 0},
      localization: {locale: "ko-KR", timeFormatter: (t) => { const d = new Date(t * 1000 + 9 * 3.6e6); return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${two(d.getUTCHours())}:${two(d.getUTCMinutes())} KST`; }},
      handleScroll: {vertTouchDrag: false}});
    const up = color("--up"), down = color("--down");
    candles = chart.addCandlestickSeries({upColor: up, downColor: down, borderVisible: false, wickUpColor: up, wickDownColor: down});
    vol = chart.addHistogramSeries({priceFormat: {type: "volume"}, priceScaleId: "", lastValueVisible: false, priceLineVisible: false});
    chart.priceScale("").applyOptions({scaleMargins: {top: 0.82, bottom: 0}});
    ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => chart.resize(cbox.clientWidth, cbox.clientHeight)) : null;
    if (ro) ro.observe(cbox);
  } else {
    msg("차트 파일을 불러오지 못했습니다");
  }
  function msg(text) { cmsg.hidden = !text; put(cmsg, text ? h("div", {class: "errbox"}, text) : null); }
  const tfNow = () => st.tf || "15m";

  async function loadBars(reset) {
    if (!candles) return;
    const k = `${st.coin}|${tfNow()}`;
    if (k !== key) reset = true;
    let d;
    try { d = await ctx.api(`/api/klines?coin=${st.coin}&tf=${tfNow()}&limit=${reset ? 1000 : 50}`); } catch (e) {
      if (!(e && e.name === "AbortError")) msg("차트 자료를 불러오지 못했습니다 (잠시 뒤 다시)");
      return;
    }
    if (`${st.coin}|${tfNow()}` !== k || !ctx.alive()) return;
    if (d.off) { msg("시세가 꺼져 있습니다 (CANDLEAGUE_DASH_LIVE=off)"); return; }
    const b = d.bars;
    if (!b || !b.t || !b.t.length) { msg(d.unavailable ? "바이낸스 연결 안 됨 (잠시 뒤 다시)" : "봉이 없습니다"); return; }
    msg("");
    const upV = color("--vol-up", "--up"), dnV = color("--vol-down", "--down");
    const bar = (i) => ({time: b.t[i] / 1000, open: b.o[i], high: b.h[i], low: b.l[i], close: b.c[i]});
    const vbar = (i) => ({time: b.t[i] / 1000, value: b.v[i], color: b.c[i] >= b.o[i] ? upV : dnV});
    const n = b.t.length;
    if (reset) {
      const dec = priceDec(b.c[n - 1]);
      candles.applyOptions({priceFormat: {type: "price", precision: dec, minMove: 10 ** -dec}});
      candles.setData(b.t.map((_, i) => bar(i)));
      vol.setData(b.t.map((_, i) => vbar(i)));
      key = k; first = b.t[0]; last = b.t[n - 1];
      chart.timeScale().setVisibleLogicalRange({from: Math.max(0, n - 160), to: n + 6});
    } else {
      for (let i = 0; i < n; i++) {
        if (b.t[i] < last) continue;
        candles.update(bar(i)); vol.update(vbar(i)); last = b.t[i];
      }
    }
    const lb = n ? b : null;
    put(legend, h("b", null, `${coinShort(st.coin)} · ${tfKo(tfNow())}`),
      lb ? `시 ${px(lb.o[n - 1])} 고 ${px(lb.h[n - 1])} 저 ${px(lb.l[n - 1])} 종 ${px(lb.c[n - 1])}` : null);
    marks(reset);
  }

  function marks(reset) {
    if (!candles) return;
    const a = acct();
    const tfms = TF_MS[tfNow()], barT = (ms) => (Math.floor(ms / tfms) * tfms) / 1000;
    const inRange = (ms) => ms && first != null && ms >= first;
    const ms = [];
    const cLong = color("--accent"), cShort = color("--warn", "--down"), cExitW = color("--up"), cExitL = color("--down");
    for (const t of (st.book && st.book.trades) || []) {
      if (coinOf(t.symbol) !== st.coin) continue;
      if (inRange(t.entry_time)) ms.push({time: barT(t.entry_time), position: t.side > 0 ? "belowBar" : "aboveBar", shape: t.side > 0 ? "arrowUp" : "arrowDown", color: t.side > 0 ? cLong : cShort, text: sideKo(t.side)});
      if (inRange(t.exit_time)) {
        const win = t.pnl != null ? t.pnl > 0 : t.roe != null ? t.roe > 0 : t.win != null ? !!t.win : null;
        ms.push({time: barT(t.exit_time - 1), position: t.side > 0 ? "aboveBar" : "belowBar", shape: "circle", color: win === false ? cExitL : cExitW,
          text: `${reasonKo(t.exit_reason)}${t.roe == null ? "" : ` ${fmt.pct(t.roe * 100, true, 0)}`}`});
      }
    }
    const o = a && a.open && coinOf(a.open.symbol) === st.coin ? a.open : null;
    if (o && inRange(o.since)) ms.push({time: barT(o.since), position: o.side > 0 ? "belowBar" : "aboveBar", shape: o.side > 0 ? "arrowUp" : "arrowDown", color: o.side > 0 ? cLong : cShort, text: `${sideKo(o.side)} (열림)`});
    ms.sort((x, y) => x.time - y.time);
    candles.setMarkers(ms);
    for (const p of plines) candles.removePriceLine(p);
    plines = [];
    if (o) {
      const line = (p, c, title, style) => { if (p != null) plines.push(candles.createPriceLine({price: p, color: c, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title})); };
      line(o.entry, color("--ink-2"), `진입 ${sideKo(o.side)}`, 2);
      line(o.stop, color("--down"), "손절", 0);
      line(o.tp, color("--up"), "익절", 0);
    }
    if (reset && st.at && first != null) {
      if (st.at >= first) {
        const t = st.book && st.book.trades ? st.book.trades.find((x) => x.entry_time === st.at) : null;
        const from = barT(st.at) - 40 * tfms / 1000, to = barT(t ? t.exit_time : st.at) + 40 * tfms / 1000;
        try { chart.timeScale().setVisibleRange({from, to}); } catch (e) { /* out of range */ }
      } else msg("이 거래는 차트 범위 밖입니다 (봉을 1시간 · 4시간으로 바꿔 보세요)");
    }
  }

  // ------------------------------------------------------------ the pieces
  const acct = () => (st.acct ? LK.index().byId[st.acct] : null);
  function paintTfs() {
    put(tfBar, TFS.map((t) => h("button", {type: "button", role: "tab", "aria-selected": String(t === tfNow()), onclick: () => { st.tf = t; st.at = null; save(); paintTfs(); loadBars(true); }}, tfKo(t))));
  }
  function save() { ctx.setQuery(Object.fromEntries(Object.entries({acct: st.acct, coin: st.coin, tf: st.tf}).filter(([, v]) => v))); }
  const liveRow = (c) => (st.live && st.live.coins ? st.live.coins.find((x) => x.coin === c) : null);
  function paintStrip() {
    const d = LK.league();
    const openBy = {};
    for (const a of (d && d.accounts) || []) if (a.open) { const c = coinOf(a.open.symbol); openBy[c] = (openBy[c] || 0) + 1; }
    put(strip, COINS.map((c) => {
      const r = liveRow(c);
      const ch = r && r.change_pct != null ? fmt.pct(r.change_pct, true, 2) : "";
      return h("button", {type: "button", class: "lv-sc", role: "tab", "aria-selected": String(c === st.coin), onclick: () => { st.coin = c; st.at = null; save(); paintAll(); loadBars(true); }},
        h("span", {class: "lv-scn"}, coinShort(c)), h("span", {class: "lv-scp num"}, r ? px(r.price) : "—"),
        h("span", {class: ["lv-scc", "num", fmt.tone(r && r.change_pct, ch)]}, ch), h("span", {class: "lv-scl muted"}, openBy[c] ? `포지션 ${openBy[c]}` : ""));
    }));
  }
  function paintHead() {
    const r = liveRow(st.coin), now = Date.now(), tfms = TF_MS[tfNow()];
    const lv = st.live;
    const stat = (k, v, cls) => h("div", {class: "lv-hs"}, h("span", null, k), h("b", {class: ["num", cls]}, v));
    const d = new Date(now + 9 * 3.6e6);
    put(headBox, h("div", {class: "lv-hid"}, h("span", {class: "lv-hn"}, `${coinShort(st.coin)}USDT`), h("span", {class: "lv-hsub"}, "무기한 · 종이 매매")),
      h("div", {class: "lv-hpxbox"}, h("span", {class: ["lv-hpx", fmt.tone(r && r.change_pct)]}, r ? px(r.price) : "—"),
        h("span", {class: ["lv-hchg", "num", fmt.tone(r && r.change_pct)]}, r && r.change_pct != null ? fmt.pct(r.change_pct, true, 2) : "")),
      h("div", {class: "lv-hstats"},
        r ? stat("24시간 고가 / 저가", `${px(r.high)} ~ ${px(r.low)}`) : null,
        r ? stat("24시간 거래대금", bigUsd(r.quote_volume)) : null,
        r ? stat("마크", px(r.mark)) : null,
        r ? stat("펀딩 / 다음까지", `${r.funding_rate == null ? "—" : fmt.num(r.funding_rate * 100, 4, true) + "%"}${r.next_funding_ms ? ` · ${mmss(r.next_funding_ms - now)}` : ""}`, fmt.tone(r.funding_rate)) : null,
        stat(`${tfKo(tfNow())} 봉 마감까지`, mmss(tfms - (now % tfms))),
        stat("KST", `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}:${two(d.getUTCSeconds())}`),
        !lv ? stat("시세", "불러오는 중") : lv.off ? stat("시세", "꺼짐") : lv.unavailable ? stat("시세", "바이낸스 연결 안 됨", "warn-t")
          : lv.source === "fake" ? stat("시세", "연습용 가짜", "warn-t") : lv.stale ? stat("시세", "지난 값", "warn-t") : null));
  }
  function paintAcct() {
    const d = LK.league();
    if (!d || !d.accounts) { put(acctCard, ui.none("준비 중")); return; }
    const ix = LK.index(d);
    pickDefault();
    // one option per account, grouped by role (a 기본값 account shared by two picks of one cell shows once)
    const seen = new Set();
    const groups = ROLES.map((role) => h("optgroup", {label: ROLE_KO[role]}, ix.cands.map((c) => {
      const a = ix.sets[c.id][role];
      if (!a || seen.has(a.id)) return null;
      seen.add(a.id);
      return h("option", {value: a.id, selected: a.id === st.acct}, LK.pickKo(c, meta));
    })));
    const sel = h("select", {class: "select", "aria-label": "계좌"}, groups);
    sel.value = st.acct;
    sel.addEventListener("change", () => { selectAcct(sel.value); });
    put(acctSel, sel);
    const a = ix.byId[st.acct];
    if (!a) { put(acctCard, ui.none("계좌를 고르세요")); return; }
    const c = LK.pickOf(a, ix) || a;
    const set = ix.sets[c.id] || {};
    const kv = (k, v) => h("div", {class: "cl-tkv"}, h("span", null, k), v);
    put(acctCard, h("div", {class: "stack tight"},
      h("div", null, LK.pickName(c), " ", LK.roleChip(a.role)),
      h("div", {class: "muted cl-exit"}, a.exit_ko),
      kv("거래 · 승률", h("b", {class: "num"}, `${fmt.int(a.trades)}번 · ${LK.winTxt(a)}`)),
      kv("한 번 평균", LK.ret(a.mean_ret, {hiddenIf: LK.dsHidden(a)})),
      kv("잔고", LK.wallet(a)),
      kv("최대 낙폭", h("span", {class: "num"}, LK.ddTxt(a))),
      a.role === "cand" ? kv("기준", LK.verdictPill(ix.judge[c.id])) : null,
      h("div", {class: "cl-tfive"}, h("span", {class: "muted"}, "같은 후보 5계좌"), LK.fiveRows(set, {short: true})),
      c.role === "cand" ? ui.disclosure("커스텀값 보기", paramTable(c, set.base, meta)) : null,
      h("a", {class: "btn-line", href: `#/account/${encodeURIComponent(a.id)}`}, "계좌 자세히 · 잔고 그래프")));
  }
  function paintOpen() {
    const d = LK.league();
    if (!d || !d.accounts) { put(openBox, ui.none("준비 중")); return; }
    const ix = LK.index(d);
    const rows = d.accounts.filter((a) => a.open && coinOf(a.open.symbol) === st.coin);
    const r = liveRow(st.coin);
    const others = d.accounts.filter((a) => a.open && coinOf(a.open.symbol) !== st.coin).length;
    put(openBox, rows.length ? h("div", {class: "cl-tlist"}, rows.map((a) => {
      const o = a.open, c = LK.pickOf(a, ix) || a;
      const m = o.entry != null && r && r.price != null ? o.side * (r.price / o.entry - 1) * 100 : null;
      return h("button", {type: "button", class: ["cl-ti", a.id === st.acct ? "on" : ""], onclick: () => selectAcct(a.id)},
        h("span", {class: ["side", o.side > 0 ? "long" : "short"]}, sideKo(o.side)), h("span", {class: "cl-tin"}, LK.pickKo(c, meta)),
        LK.roleChip(a.role),
        h("span", {class: ["num", fmt.tone(m)]}, m == null ? "" : `가격 ${fmt.pct(m, true, 2)}`),
        h("span", {class: "num muted"}, fmt.kst(o.since)));
    })) : h("p", {class: "lv-none"}, `${coinShort(st.coin)}에 열린 포지션 없음`), others ? h("p", {class: "lv-none"}, `다른 코인에 ${others}개 더 (위 코인 줄)`) : null);
  }
  function paintFills() {
    const ix = LK.index();
    const rows = st.fills.slice(0, 40);
    put(fillBox, rows.length ? h("div", {class: "cl-tlist"}, rows.map((f) => {
      const a = ix.byId[f.account], c = a ? LK.pickOf(a, ix) || a : null;
      return h("button", {type: "button", class: "cl-ti", onclick: () => { st.coin = coinOf(f.symbol) || st.coin; st.at = f.entry_time; selectAcct(f.account); }},
        h("span", {class: ["side", f.side > 0 ? "long" : "short"]}, sideKo(f.side)), h("b", null, coinShort(coinOf(f.symbol))),
        h("span", {class: "cl-tin"}, c ? LK.pickKo(c, meta) : f.account), a ? LK.roleChip(a.role) : null,
        h("span", {class: "muted"}, reasonKo(f.exit_reason)),
        h("span", {class: ["num", fmt.tone(f.roe)]}, f.roe == null ? "" : fmt.pct(f.roe * 100, true, 1)),
        h("span", {class: "num muted"}, fmt.kst(f.exit_time)));
    })) : h("p", {class: "lv-none"}, "아직 끝난 거래가 없습니다"));
  }
  function paintTrades() {
    const a = acct();
    tradeSub.textContent = a ? `${LK.pickKo(LK.pickOf(a) || a, meta)} · ${ROLE_KO[a.role]} · 줄을 누르면 차트가 그 거래로` : "";
    const rows = ((st.book && st.book.trades) || []).slice(0, 100);
    if (!rows.length) { put(tradeBox, h("p", {class: "lv-none"}, "이 계좌는 아직 끝난 거래가 없습니다")); return; }
    put(tradeBox, ui.table([
      {label: "청산 (KST)", l: true, get: (t) => h("span", {class: "num"}, fmt.kst(t.exit_time))},
      {label: "코인", l: true, get: (t) => coinShort(coinOf(t.symbol))},
      {label: "방향", l: true, get: (t) => h("span", {class: ["side", t.side > 0 ? "long" : "short"]}, sideKo(t.side))},
      {label: "진입가", get: (t) => (t.entry_price == null ? "숨김" : px(t.entry_price))},
      {label: "청산가", get: (t) => (t.exit_price == null ? "숨김" : px(t.exit_price))},
      {label: "이유", get: (t) => reasonKo(t.exit_reason)},
      {label: "배수", get: (t) => (t.leverage ? `${fmt.int(t.leverage)}배` : "—")},
      {label: "증거금 대비", get: (t) => (t.roe == null ? "숨김" : h("span", {class: ["num", fmt.tone(t.roe)]}, fmt.pct(t.roe * 100, true, 1)))},
      {label: "손익", get: (t) => (t.pnl == null ? "숨김" : h("span", {class: ["num", fmt.tone(t.pnl)]}, fmt.money(t.pnl, true)))},
    ], rows, {cls: "lv-dense", rowCls: (t) => (t.entry_time === st.at ? "lv-on" : ""),
      onRow: (t) => { st.coin = coinOf(t.symbol) || st.coin; st.at = t.entry_time; save(); paintAll(); loadBars(true); }}));
  }
  async function loadBook(fresh) {
    if (!st.acct) { st.book = null; return; }
    if (!fresh && st.book && st.book.id === st.acct) return;
    const id = st.acct;
    try { const b = await ctx.api(`/api/trades/${encodeURIComponent(id)}`); if (id === st.acct) st.book = {...b, id}; } catch (e) { /* keep */ }
  }
  async function selectAcct(id) {
    const a = LK.index().byId[id];
    if (!a) return;
    st.acct = id;
    if (!st.tf || st.tf !== a.tf) st.tf = a.tf;
    if (a.open && !st.at) st.coin = coinOf(a.open.symbol);
    save();
    await loadBook(true);
    paintAll(); paintTfs();
    loadBars(true);
  }
  function paintAll() { paintStrip(); paintHead(); paintAcct(); paintOpen(); paintFills(); paintTrades(); }

  async function pollLive() { try { st.live = await ctx.api("/api/live"); } catch (e) { return; } paintStrip(); paintHead(); paintOpen(); }
  async function pollFills() { try { st.fills = (await ctx.api("/api/fills")).fills || []; } catch (e) { return; } paintFills(); }

  /** The account to show when none was asked for: the pick with the best mean so far (or the first); its timeframe. */
  function pickDefault() {
    const d = LK.league();
    if (!d || !d.accounts) return false;
    const ix = LK.index(d);
    if (!st.acct || !ix.byId[st.acct]) {
      const best = ix.cands.filter((c) => c.mean_ret != null && c.trades).sort((a, b) => b.mean_ret - a.mean_ret)[0] || ix.cands[0];
      st.acct = best ? best.id : null;
    }
    const a = ix.byId[st.acct];
    const before = st.tf;
    if (!st.tf) st.tf = a ? a.tf : "15m";
    return before !== st.tf;
  }
  let started = false;
  ctx.onLeague(async () => {
    const tfChanged = pickDefault();
    await loadBook(true);
    if (!ctx.alive()) return;
    paintAll(); paintTfs();
    if (started && tfChanged) loadBars(true); else marks(false);
  });
  pickDefault();
  paintTfs();
  await Promise.all([pollLive(), pollFills(), loadBook(true)]);
  if (!ctx.alive()) return;
  if (!q.coin) {                       // no coin asked for: the chosen account's open position, else its newest trade
    const a = acct();
    const t = st.book && st.book.trades && st.book.trades[0];
    if (a && a.open) st.coin = coinOf(a.open.symbol);
    else if (t && COINS.includes(coinOf(t.symbol))) st.coin = coinOf(t.symbol);
  }
  paintAll();
  started = true;
  await loadBars(true);
  ctx.every(5000, pollLive);
  ctx.every(10000, () => loadBars(false));
  ctx.every(30000, pollFills);
  ctx.every(1000, paintHead);
  return () => { if (ro) ro.disconnect(); try { if (chart) chart.remove(); } catch (e) { /* gone */ } };
}
