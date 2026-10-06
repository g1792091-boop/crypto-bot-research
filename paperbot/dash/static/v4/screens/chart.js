// #/chart[/<SYMBOL>][?tf=15m&acct=<account id>] — 차트 (builder B, CONTRACT.md §4, INVENTORY §2). The bot's chart:
// the vendored lightweight-charts (same origin), 15 intervals with a bar-close countdown on each (server clock),
// one chosen account's entries and exits, this coin's open positions as lines with live P&L, the chosen account's
// entry / stop / liquidation (and the reel's target), support / resistance, GH Coin plan lines (only while its recorder
// runs), US macro release marks, armed price alerts. Prices come from the server: /api/ticker (store, 5 s) and
// /api/candles?limit=2 every 5 s for the forming bar. TradingView and Coinglass are new-tab links; the opt-in second
// tab 거래소 차트 shows TradingView's own page in a sandboxed cross-origin iframe (chart-tv.js), built only while open.
// The chart deck (core/chartfx.js, the same as the terminal's): the AI skin's glow, Premium / Discount light and event
// flashes (a real big trade from the server relay, a market liquidation, our own fill of this coin), 1 px lines with a
// compact pill at the left (click to hide; never in the autoscale; an edge marker when off the price range), the '선'
// menu (포지션 선 · 손절·잠금 · 지지·저항 · 프리미엄 지표 · 경제지표 · 거래량), 프리미엄 지표 and the volume bars.
import {h, ui, fmt, store, local, motion, bars, serverNow, makeChart, candleOptions, tok, priceDec, features, chartDeck, chartAi,
  bigEvent, liqEvent, ownEvent, onPref, fullChart} from "../core/pb.js";
import {normPos, reelExits, nameOf, countOnly} from "./positions-kit.js";
import {posLines} from "./chart-lines.js";
import {tickStream} from "./terminal-live.js";
import {countdown, fundPct} from "./positions-book.js";
import {sidePanels} from "./chart-panels.js";
import {coinFlowCard, usdKo} from "./market-live.js";
import {TV_IV, tvFrame} from "./chart-tv.js";

const SHORT = {"1m": "1분", "3m": "3분", "5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "2h": "2시간", "4h": "4시간",
  "6h": "6시간", "8h": "8시간", "12h": "12시간", "1d": "일", "3d": "3일", "1w": "주", "1M": "월"};
const TF_S = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800,
  "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800, "1M": 2592000};
const LEVEL_TFS = ["15m", "30m", "1h", "4h"];                  // /api/levels answers for the traded house timeframes
const GH_KO = {long: "롱 타점", short: "숏 타점", longWait: "롱 대기", shortWait: "숏 대기", wait: "관망"};
// [key, label, default on a PC, default on a phone]. The position / support-resistance / macro / volume groups are in
// the chart deck's '선' menu (on a phone the position and level lines start off there; remembered per device).
const TOGGLES = [["mk", "진입·청산", true, true], ["al", "가격 알림 선", true, true], ["gh", "GH Coin 타점", false, false]];
const narrow = () => typeof matchMedia === "function" && matchMedia("(max-width: 599px)").matches;

const decOf = priceDec;

let alive = null;                       // the mounted screen's update(params) target

export async function mount(el, ctx) {
  ctx.setTitle("차트");
  const p0 = ctx.params;
  const savedShow = local.get("chart-show", {});
  const st = {
    sym: bars.SYMS.includes(p0.arg) ? p0.arg : local.get("chart-sym", "BTCUSDT"),
    tf: TF_S[p0.query.tf] ? p0.query.tf : local.get("chart-tf", "15m"),
    acct: p0.query.acct || "", board: null, show: Object.fromEntries(TOGGLES.map(([k, , d, dp]) => [k, savedShow[k] ?? (narrow() ? dp : d)])),
    last: null, levels: null, gh: null, events: null, alerts: null, acctData: null, loadTok: 0, fitted: false, view: "bot",
  };
  if (!bars.SYMS.includes(st.sym)) st.sym = "BTCUSDT";
  if (!TF_S[st.tf]) st.tf = "15m";

  // ---------------------------------------------------------------- top: coins, price line, intervals
  const coinBtns = new Map();
  const coinBar = h("div", {class: "seg scroll chart-coins", role: "tablist", "aria-label": "코인"}, bars.SYMS.map((s) => {
    const px = h("span", {class: "num"}, "—"), chg = h("small", {class: "num"}, "");
    const b = h("button", {type: "button", role: "tab", "aria-selected": String(s === st.sym), onclick: () => setSym(s)},
      h("b", null, fmt.coin(s)), s === "XRPUSDT" ? h("small", {class: "muted"}, "기록") : null, px, chg);
    coinBtns.set(s, {b, px, chg});
    return b;
  }));
  const pxBig = h("b", {class: "chart-px num"}, "—"), pxChg = h("span", {class: "num"}, ""), barLeft = h("b", {class: "num"}, "—");
  const barLab = h("span", {class: "muted"});
  const priceLine = h("div", {class: "chart-pline"}, h("span", {class: "chart-sym"}, ""), pxBig, pxChg, h("span", {class: "grow"}),
    h("span", {class: "chart-cd"}, barLab, " ", barLeft));
  const tfBtns = new Map();
  const tfBar = h("div", {class: "chart-tfs", role: "tablist", "aria-label": "봉 (남은 시간)"}, bars.ALL_TFS.map((tf) => {
    const left = h("small", {class: "num"}, "—");
    const b = h("button", {type: "button", role: "tab", "aria-selected": String(tf === st.tf), onclick: () => setTf(tf), title: `${fmt.tfKo(tf)} 봉이 닫힐 때까지`},
      h("span", null, h("i", {class: "chart-dot", "aria-hidden": "true"}), SHORT[tf]), left);
    tfBtns.set(tf, {b, left});
    return b;
  }));

  // ---------------------------------------------------------------- chart box + controls
  const legend = h("div", {class: "chart-legend num"});
  const box = h("div", {class: "chart-box", "data-fc-box": ""});
  const wrap = h("div", {class: "chart-wrap", "data-fc-grow": ""}, box, legend);
  const acctSel = h("select", {class: "select chart-acct", "aria-label": "진입·청산을 볼 계좌"});
  acctSel.addEventListener("change", () => { st.acct = acctSel.value; st.acctData = null; reflectUrl(); drawAccount(); });
  const toggleBtns = TOGGLES.map(([k, label]) => {
    const b = h("button", {type: "button", "aria-pressed": String(!!st.show[k]), dataset: {k}}, label);
    b.addEventListener("click", () => {
      st.show[k] = !st.show[k]; b.setAttribute("aria-pressed", String(st.show[k])); local.set("chart-show", st.show);
      if (k === "mk") drawMarkers(); if (k === "gh") loadLevels();
      if (k === "al") drawAlertLines();
    });
    return b;
  });
  const toggles = h("div", {class: "seg scroll chart-toggles", role: "group", "aria-label": "차트에 표시"}, toggleBtns);
  const tgl = (k) => toggleBtns[TOGGLES.findIndex((x) => x[0] === k)];
  // 설정 한 곳 (core/settings.js) writes the same "chart-show" choice: the toggles and the chart follow at once
  ctx.track(onPref("chart-show", (v) => {
    for (const [k] of TOGGLES) {
      const want = !!(v && v[k]);
      if (st.show[k] === want) continue;
      st.show[k] = want; tgl(k).setAttribute("aria-pressed", String(want));
      if (k === "mk") drawMarkers(); if (k === "gh") loadLevels(); if (k === "al") drawAlertLines();
    }
  }));
  const fxBar = h("div", {class: "chart-fx"});          // the deck's controls (filled once the chart exists)
  const lvNote = h("p", {class: "pos-note"});
  const tvA = h("a", {class: "btn-line", target: "_blank", rel: "noopener noreferrer"}, "트레이딩뷰에서 열기 ↗");
  const cgLinks = h("span", {class: "chart-links"});
  const links = h("div", {class: "chart-linkrow"}, tvA, cgLinks);

  // ---------------------------------------------------------------- the ticker details
  const tk = {mark: h("b", {class: "num"}, "—"), fund: h("b", {class: "num"}, "—"), fundLeft: h("span", {class: "muted num"}), hi: h("b", {class: "num"}, "—"),
    lo: h("b", {class: "num"}, "—"), vol: h("b", {class: "num"}, "—"), pos: h("b", null, "—"), sess: h("p", {class: "pos-note"})};
  const tickCard = ui.card({plate: "시세", sub: "서버 경유 · 5초마다"},
    ui.kv([["마크 가격", tk.mark], ["펀딩비 / 다음까지", h("span", null, tk.fund, " ", tk.fundLeft)], ["이 코인 포지션", tk.pos],
      ["24시간 고가", tk.hi], ["24시간 저가", tk.lo], ["24시간 거래대금", tk.vol]]), tk.sess);

  const panels = sidePanels(ctx, {sym: st.sym, onPick: (id) => pickAccount(id), onAlerts: (d) => { st.alerts = d; drawAlertLines(); }});
  // 우리 차트 (default, every visit) | 거래소 차트 (opt-in: TradingView's page in an iframe that exists only while open)
  const tv = tvFrame();
  ctx.track(() => tv.hide());
  const viewSeg = ui.seg([{id: "bot", label: "우리 차트"}, {id: "tv", label: "거래소 차트", title: "트레이딩뷰 화면 (바깥 사이트)"}], "bot",
    (v) => setView(v), {label: "차트 종류"});
  viewSeg.classList.add("chart-views");
  const chartCard = h("section", {class: "card chart-card", "aria-label": "봇 차트", dataset: {view: "bot"}}, viewSeg, tfBar, fxBar, wrap, tv.el,
    h("div", {class: "chart-ctrl"}, acctSel), toggles, lvNote,
    ui.assume("open", "포지션 선의 손익은 그 계좌들의 미실현 손익"));
  // 차트 크게 보기 (core/fullchart.js): the chart card fills the window (key "f"); the chart takes the height
  const fs = fullChart({ctx, label: "차트"});
  fs.bind(chartCard);
  const flowCard = coinFlowCard(ctx, st.sym);           // 이 코인 시장 지표 (flow.db + liq.db, /api/v4/flowlive)
  ctx.every(30000, () => flowCard.load(), {now: true});
  el.append(ui.screenHead("차트", "봇이 보는 시세와 모의 계좌의 진입·청산"), coinBar, priceLine,
    h("div", {class: "chart-cols"}, h("div", {class: "stack"}, chartCard, links, tickCard, flowCard), panels));

  // ---------------------------------------------------------------- the chart
  let C = null, series = null, deck = null;
  try {
    C = await makeChart(box, {timeScale: {rightOffset: 26}});
    ctx.track(C.dispose);
    series = C.chart.addCandlestickSeries({...candleOptions(), lastValueVisible: false, priceLineStyle: 2, priceLineWidth: 1});
    deck = chartDeck({chart: C.chart, series, wrap, box, ctx, key: "chart", tag: true, groups: ["pos", "risk", "sr", "smc", "ev", "vol"],
      defaults: narrow() ? {pos: false, risk: false, sr: false, smc: false} : null, sym: () => st.sym, legend});
    deck.onToggle((g) => { if (g === "ev" || g == null) drawMarkers(); if (g === "sr" || g == null) loadLevels(); });
    fxBar.append(deck.lightChip, deck.flashSel, deck.smcBtn, deck.menuBtn, fs);
    C.chart.subscribeCrosshairMove((p) => { const d = p && p.seriesData && p.seriesData.get(series); paintLegend(d || st.last); });
  } catch (e) {
    box.replaceChildren(h("div", {class: "chart-fail"}, ui.errorBox(e, () => location.reload())));
  }

  function paintLegend(d) {
    if (!d) { legend.textContent = ""; return; }
    const ch = d.open ? (d.close - d.open) / d.open : null;
    legend.replaceChildren(h("b", null, `${fmt.coin(st.sym)} ${fmt.tfKo(st.tf)}`), ` 시 ${fmt.price(d.open)} 고 ${fmt.price(d.high)} 저 ${fmt.price(d.low)} 종 ${fmt.price(d.close)} `,
      h("span", {class: fmt.tone(ch)}, fmt.pct(ch, 2)));
  }

  async function loadCandles() {
    if (!series) return;
    const tokn = ++st.loadTok, sym = st.sym, tf = st.tf;
    let data = [];
    try { data = await ctx.api(`/api/candles?symbol=${sym}&interval=${tf}&limit=500`); }
    catch (e) { if (e && e.name === "AbortError") return; ctx.toast("가격 자료를 불러오지 못했습니다"); }
    if (tokn !== st.loadTok || !ctx.alive()) return;
    const dec = decOf(data.length ? data[data.length - 1].close : store.mark(sym));
    series.applyOptions({priceFormat: {type: "price", precision: dec, minMove: Math.pow(10, -dec)}});
    deck.setData(data);
    st.t0 = data.length ? data[0].time : 0;
    st.last = data[data.length - 1] || null;
    paintLegend(st.last);
    deck.showRecent(narrow() ? 90 : 200, narrow() ? 10 : 26);
    drawMarkers(); drawPosLines(); drawAccount(); drawAlertLines(); loadLevels();
  }
  async function liveBar() {
    if (!series || !st.last) return;
    const sym = st.sym, tf = st.tf;
    try {
      const rows = await ctx.api(`/api/candles?symbol=${sym}&interval=${tf}&limit=2`);
      if (sym !== st.sym || tf !== st.tf) return;
      for (const c of rows) if (c.time >= st.last.time && deck.update(c, true)) st.last = c;
      paintLegend(st.last);
    } catch (e) { /* next poll */ }
  }

  // ---------------------------------------------------------------- markers: the chosen account's trades + macro releases
  async function eventsList() {
    if (st.events && Date.now() - st.events.at < 600000) return st.events.list;
    try { const d = await ctx.api("/api/events?days_back=60&days_ahead=1"); st.events = {at: Date.now(), list: d.events || []}; }
    catch (e) { st.events = {at: Date.now(), list: []}; }
    return st.events.list;
  }
  async function drawMarkers() {
    if (!series) return;
    const sym = st.sym, tf = st.tf, step = TF_S[tf], t0 = st.t0 || 0;
    const marks = [];
    if (deck.shown("ev") && step < 86400) {
      const now = serverNow() / 1000;
      for (const e of await eventsList()) {
        const s = Math.floor(e.ts_ms / 1000);
        if (s >= t0 && s <= now) marks.push({time: s - (s % step), position: "aboveBar", color: tok("--accent"), shape: "square", text: e.kind, glow: false});
      }
    }
    if (st.show.mk && st.acct && st.acctData && st.acctData.account && st.acctData.account.account_id === st.acct) {
      for (const t of st.acctData.trades || []) {
        if (t.symbol !== sym || t.entry_time / 1000 < t0) continue;
        const e = Math.floor(t.entry_time / 1000), x = Math.floor(t.exit_time / 1000);
        marks.push({time: e - (e % step), position: t.side > 0 ? "belowBar" : "aboveBar", color: tok("--accent"),
          shape: t.side > 0 ? "arrowUp" : "arrowDown", text: `${fmt.sideKo(t.side)} ${fmt.lev(t.leverage)}`});
        marks.push({time: x - (x % step), position: t.side > 0 ? "aboveBar" : "belowBar", color: t.pnl > 0 ? tok("--up") : tok("--down"),
          shape: "circle", text: `${fmt.reasonKo(t.exit_reason)} ${fmt.pct(t.roe, 0)}`});
      }
    }
    if (sym !== st.sym || tf !== st.tf) return;
    marks.sort((a, b) => a.time - b.time);
    deck.setMarkers(marks);
  }

  // ---------------------------------------------------------------- lines (the deck: 1 px, a pill at the left, click to hide)
  function drawPosLines() {
    if (!deck) return;
    // D10/D11: DeepSeek / coin-flip positions are counted on the line but add no money to its pill (chart-lines.js)
    const accts = TF_S[st.tf] < 86400 && st.board ? st.board.accounts.filter((a) => a.position && a.position.symbol === st.sym && a.account_id !== st.acct) : [];
    deck.setLines("pos", posLines(accts, store.mark(st.sym), {stops: 4}));
    const now = new Set(accts.map((a) => a.account_id + "@" + (a.position.entry_time || a.position.entry_price || a.position.entry)));
    if (st.seenPos && [...now].some((k) => !st.seenPos.has(k))) deck.flash(ownEvent());     // a real new entry fill
    if (st.board) st.seenPos = now;
  }
  function drawAcctLines() {
    if (!deck) return;
    const d = st.acctData, out = [];
    const a = d && d.account && d.account.account_id === st.acct ? (st.board && st.board.accounts.find((x) => x.account_id === st.acct)) || d.account : null;
    const p = a ? normPos(d.state && d.state.position) : null;
    if (p && p.symbol === st.sym) {
      const m = store.mark(p.symbol), co = countOnly(a, ""), pnl = m && !co ? p.side * p.qty * (m - p.entry) : null;
      const reel = reelExits(a), id = "a:" + st.acct;
      const kids = [];
      const add = (k, price, tone, dash, label) => { if (price) { out.push({id: `${id}:${k}`, parent: id, group: "risk", price, tone, dash, alpha: 0.6, axis: true, label}); kids.push(`${id}:${k}`); } };
      add("stop", p.stop, !reel && p.lock_roe != null ? "up" : "down", 1, reel ? "손절 (스윙 저점)" : p.lock_roe != null ? (co ? "잠금선" : `잠금 +${fmt.num(p.lock_roe * 100, 0)}%`) : "손절");
      add("liq", p.liq, "warn", 2, "청산가");
      if (reel && p.target) add("tp", p.target, "up", 1, "목표 (윗밴드)");
      out.unshift({id, group: "pos", price: p.entry, tone: "accent", dash: 0, alpha: 0.8, axis: true,
        pill: {text: [`진입 ${fmt.sideKo(p.side)} ${fmt.lev(p.leverage)}`, pnl != null && p.margin ? fmt.pct(pnl / p.margin, 1) : null].filter(Boolean).join(" · "),
          short: `고른 계좌 ${fmt.sideKo(p.side)}`, title: `${nameOf(a)} · 진입 ${fmt.price(p.entry)}${pnl != null ? " · 미실현 ROE (마크 가격, 나갈 때 수수료 전)" : ""}`,
          chips: kids.length ? [{text: "손절·청산", ids: kids, title: "이 계좌의 손절·청산가 선 보이기·숨기기"}] : []}});
    }
    deck.setLines("acct", out);
  }
  async function drawAccount() {
    acctSel.value = st.acct;
    if (st.acct && (!st.acctData || st.acctData.account.account_id !== st.acct)) {
      const want = st.acct;
      try {
        const d = await ctx.api(`/api/account/${encodeURIComponent(want)}`);
        if (want !== st.acct || !ctx.alive()) return;
        st.acctData = d;
      } catch (e) { if (!(e && e.name === "AbortError")) ctx.toast("계좌 자료를 불러오지 못했습니다"); return; }
    }
    drawMarkers(); drawAcctLines(); drawPosLines();
  }
  function drawAlertLines() {
    if (!deck) return;
    const out = [];
    if (st.show.al) {
      for (const a of (st.alerts && st.alerts.alerts) || []) {
        if (a.symbol !== st.sym || !a.armed) continue;
        out.push({id: `al:${a.id ?? a.price}`, group: "al", price: a.price, tone: "accent", dash: 2, alpha: 0.6, axis: true, glow: false,
          label: `알림 ${a.direction === "above" ? "↑" : "↓"}`});
      }
    }
    deck.setLines("al", out);
  }
  async function loadLevels() {
    const sym = st.sym, tf = st.tf;
    let lv = null, gb = null;
    if (deck && deck.shown("sr") && LEVEL_TFS.includes(tf)) { try { lv = await ctx.api(`/api/levels?symbol=${sym}&tf=${tf}`); } catch (e) { lv = null; } }
    if (st.show.gh && features.ghcoin) { try { gb = await ctx.api("/api/ghcoin/board"); } catch (e) { gb = null; } }
    if (sym !== st.sym || tf !== st.tf || !ctx.alive()) return;
    st.levels = lv; st.gh = gb;
    drawLevels();
  }
  function drawLevels() {
    if (!deck) return;
    const out = [];
    const add = (id, group, price, tone, dash, label) => { if (price) out.push({id, group, price, tone, dash, alpha: 0.5, axis: false, glow: false, label}); };
    const note = [], sr = deck.shown("sr");
    if (sr && st.levels && st.levels.levels) {
      for (const side of ["resistance", "support"]) {
        st.levels.levels.filter((x) => x.side === side && (x.atr == null || Math.abs(x.atr) <= 8)).slice(0, 3)
          .forEach((x, i) => add(`lv:${side}:${i}`, "sr", x.price, side === "resistance" ? "down" : "up", 2, side === "resistance" ? "저항" : "지지"));
      }
      const named = st.levels.levels.filter((x) => x.atr == null || Math.abs(x.atr) <= 8).slice(0, 6)
        .map((x) => `${x.side === "resistance" ? "저항" : "지지"} ${fmt.price(x.price)}${x.ko ? " " + x.ko : ""}`);
      if (named.length && !narrow()) note.push(named.join(" · ") + ".");
      note.push("지지·저항은 설명용입니다 (진입 연구에서 수익과 관계가 없었음).");
    } else if (sr && !LEVEL_TFS.includes(st.tf)) note.push("지지·저항은 15분·30분·1시간·4시간 봉에만 있습니다.");
    const g = st.show.gh && features.ghcoin && st.gh && st.gh.coins && st.gh.coins[st.sym];
    if (g && g.side && g.entry) {
      const k = `GH ${GH_KO[g.state] || g.state}`;
      add("gh:e", "gh", g.entry, "accent", 0, `${k} 진입`); add("gh:sl", "gh", g.sl, "accent", 1, `${k} 손절`);
      add("gh:tp1", "gh", g.tp1, "accent", 1, `${k} 익절1`); add("gh:tp2", "gh", g.tp2, "accent", 2, `${k} 익절2`);
    }
    if (st.show.gh && features.ghcoin) note.push(!st.gh || !st.gh.alive ? "GH Coin 기록기 응답 없음." : g ? `GH Coin: ${GH_KO[g.state] || g.state}${g.why ? " · " + g.why : ""}` : "GH Coin: 이 코인 계획 없음.");
    deck.setLines("lv", out);
    lvNote.textContent = note.join(" ");
    lvNote.hidden = !note.length;
  }

  // ---------------------------------------------------------------- account picker (accounts of this interval)
  function fillAccounts() {
    const list = st.board ? st.board.accounts.filter((a) => a.timeframe === st.tf) : [];
    const first = h("option", {value: ""}, !st.board ? "계좌 목록을 불러오는 중" : list.length ? `계좌를 고르면 진입·청산이 보입니다 (${fmt.int(list.length)}개)` :
      st.tf === "1d" ? "일봉은 기록만 합니다 (계좌 없음)" : `${fmt.tfKo(st.tf)} 봉에는 계좌가 없습니다`);
    const groups = fmt.GROUPS.map((g) => {
      const mine = list.filter((a) => fmt.groupOf(a) === g.id);
      return mine.length ? h("optgroup", {label: g.ko}, mine.map((a) => h("option", {value: a.account_id},
        `${a.position && a.position.symbol === st.sym ? "● " : ""}${nameOf(a)}`))) : null;
    });
    acctSel.replaceChildren(first, ...groups.filter(Boolean));
    if (!list.some((a) => a.account_id === st.acct)) { if (st.acct && st.board) { st.acct = ""; st.acctData = null; } }
    acctSel.value = st.acct;
    acctSel.disabled = !list.length;
  }
  const traded = () => new Set(((st.board && st.board.accounts) || []).map((a) => a.timeframe));
  function paintTfs() {
    const tr = traded();
    for (const [tf, x] of tfBtns) { x.b.setAttribute("aria-selected", String(tf === st.tf)); x.b.classList.toggle("bot", tr.has(tf)); }
  }

  // ---------------------------------------------------------------- the ticker (store) and the clocks
  function paintTicker() {
    const all = store.get("ticker") || {};
    for (const [s, x] of coinBtns) {
      const t = all[s];
      motion.tickPrice(x.px, t ? (t.c ?? t.mark) : null, t ? fmt.price(t.c ?? t.mark) : "—", s);     // glows on a real move
      x.chg.textContent = t && t.p != null ? fmt.pct(Number(t.p) / 100, 2) : "";
      x.chg.className = "num " + (t ? fmt.tone(t.p) : "");
    }
    const t = all[st.sym];
    priceLine.firstChild.textContent = `${fmt.coin(st.sym)}USDT`;
    motion.tickPrice(pxBig, t ? (t.c ?? t.mark) : null, t ? fmt.price(t.c ?? t.mark) : "—", st.sym);
    pxBig.className = "chart-px num " + (t ? fmt.tone(t.p) : "");
    pxChg.textContent = t && t.p != null ? `24시간 ${fmt.pct(Number(t.p) / 100, 2)}` : "";
    pxChg.className = "num " + (t ? fmt.tone(t.p) : "");
    motion.tickPrice(tk.mark, t ? t.mark : null, t ? fmt.price(t.mark) : "—", st.sym);
    tk.fund.textContent = t ? fundPct(t.r) : "—";
    tk.fund.className = "num " + (t ? fmt.tone(-Number(t.r || 0)) : "");
    tk.hi.textContent = t ? fmt.price(t.h) : "—";
    tk.lo.textContent = t ? fmt.price(t.l) : "—";
    tk.vol.textContent = t && t.q != null ? `${usdKo(t.q)} USDT` : "—";      // 만 / 억 like 시장 (fix: no 'B' / 'K' on one screen)
    st.fundT = t && t.T;
    const n = st.board ? st.board.accounts.filter((a) => a.position && a.position.symbol === st.sym).length : null;
    tk.pos.textContent = n == null ? "—" : `${fmt.int(n)}개 계좌`;
  }
  function tick() {
    const now = serverNow();
    for (const [tf, x] of tfBtns) {
      x.left.textContent = bars.closeIn(tf, now);
      const end = bars.barEnd(tf, now);
      x.b.classList.toggle("soon", end != null && end - now <= 60000);
    }
    barLab.textContent = `${fmt.tfKo(st.tf)}${fmt.tfKo(st.tf).endsWith("봉") ? "" : "봉"} 마감까지`;
    barLeft.textContent = bars.closeIn(st.tf, now);
    tk.fundLeft.textContent = st.fundT ? countdown(st.fundT) : "";
    const ss = bars.session(now), us = bars.usMarket(now);
    tk.sess.textContent = `지금 ${ss.weekend ? "주말 · " : ""}${ss.ko} (한국 시각) · 미국 증시 ${us.text}`;
  }

  // ---------------------------------------------------------------- 우리 차트 / 거래소 차트
  function setView(v) {
    st.view = v === "tv" ? "tv" : "bot";
    chartCard.dataset.view = st.view;
    viewSeg.set(st.view);
    if (st.view === "tv") tv.show(fmt.coin(st.sym), st.tf); else tv.hide();
  }

  // ---------------------------------------------------------------- links (new tab; the 거래소 차트 frame follows the coin and interval)
  function paintLinks() {
    if (st.view === "tv") tv.show(fmt.coin(st.sym), st.tf);
    const c = encodeURIComponent(fmt.coin(st.sym));
    tvA.href = `https://www.tradingview.com/chart/?symbol=BINANCE:${c}USDT.P&interval=${TV_IV[st.tf] || "15"}`;
    cgLinks.replaceChildren(...[["코인글래스 차트", `https://www.coinglass.com/tv/Binance_${c}USDT`],
      ["청산 지도", "https://www.coinglass.com/pro/futures/LiquidationMap"],
      ["청산 히트맵", "https://www.coinglass.com/pro/futures/LiquidationHeatMap"],
      [`${fmt.coin(st.sym)} 파생 정보`, `https://www.coinglass.com/currencies/${c}`]].map(([t, u]) =>
      h("a", {class: "btn-line", href: u, target: "_blank", rel: "noopener noreferrer"}, t, " ↗")));
  }

  // ---------------------------------------------------------------- changes
  function reflectUrl() {
    const want = ctx.href("chart", st.sym, {tf: st.tf, acct: st.acct || null});
    if (location.hash !== want) window.history.replaceState(null, "", want);
  }
  function setSym(s) {
    if (!bars.SYMS.includes(s) || s === st.sym) return;
    st.sym = s; local.set("chart-sym", s);
    for (const [k, x] of coinBtns) x.b.setAttribute("aria-selected", String(k === s));
    st.seenPos = null; st.liqSeen = null;
    paintTicker(); paintLinks(); fillAccounts(); panels.setSym(s); flowCard.setSym(s); reflectUrl();
    loadCandles();
  }
  function setTf(tf) {
    if (!TF_S[tf] || tf === st.tf) return;
    st.tf = tf; local.set("chart-tf", tf);
    paintTfs(); fillAccounts(); paintLinks(); tick(); reflectUrl();
    loadCandles();
  }
  function pickAccount(id) {
    const a = st.board && st.board.accounts.find((x) => x.account_id === id);
    if (!a) return;
    st.acct = id; st.acctData = null;
    if (st.view === "tv") setView("bot");                 // entries and exits are drawn on 우리 차트 only
    if (!st.show.mk) { st.show.mk = true; tgl("mk").setAttribute("aria-pressed", "true"); local.set("chart-show", st.show); }
    if (a.timeframe !== st.tf && TF_S[a.timeframe]) { st.tf = a.timeframe; local.set("chart-tf", st.tf); paintTfs(); paintLinks(); tick(); fillAccounts(); reflectUrl(); loadCandles(); }
    else { fillAccounts(); reflectUrl(); drawAccount(); }
    box.scrollIntoView({behavior: motion.reduced() ? "auto" : "smooth", block: "center"});
  }
  alive = (params) => {
    const s = bars.SYMS.includes(params.arg) ? params.arg : st.sym;
    const tf = TF_S[params.query.tf] ? params.query.tf : st.tf;
    const acct = params.query.acct || "";
    const symCh = s !== st.sym, tfCh = tf !== st.tf, acCh = acct !== st.acct;
    if (!symCh && !tfCh && !acCh) return;
    st.sym = s; st.tf = tf; st.acct = acct; st.acctData = null;
    for (const [k, x] of coinBtns) x.b.setAttribute("aria-selected", String(k === s));
    st.seenPos = null; st.liqSeen = null;
    paintTicker(); paintTfs(); paintLinks(); fillAccounts(); tick(); panels.setSym(s); flowCard.setSym(s);
    if (symCh || tfCh) loadCandles(); else drawAccount();
  };
  ctx.track(() => { alive = null; });

  // ---------------------------------------------------------------- wiring
  paintTicker(); paintTfs(); paintLinks(); tick();
  ctx.watch("board", (b) => {
    if (!b) return;
    const first = !st.board;
    st.board = b;
    fillAccounts(); paintTfs(); paintTicker(); panels.onBoard(b);
    if (first && st.acct) {
      const a = b.accounts.find((x) => x.account_id === st.acct);
      if (a && a.timeframe !== st.tf && TF_S[a.timeframe]) { st.tf = a.timeframe; paintTfs(); fillAccounts(); paintLinks(); tick(); loadCandles(); return; }
    }
    drawPosLines(); drawAccount();
  });
  ctx.watch("ticker", () => { paintTicker(); drawPosLines(); drawAcctLines(); panels.onTicker(); });
  ctx.on("trades", (rows) => {
    panels.onTrades(rows);
    if (deck && (rows || []).some((t) => t.symbol === st.sym)) deck.flash(ownEvent());          // our bot's real exit fill
    if (st.acct && rows.some((t) => t.account_id === st.acct)) { st.acctData = null; drawAccount(); }
  });
  ctx.on("features", () => { panels.onFeatures(); tgl("gh").hidden = !features.ghcoin; });
  tgl("gh").hidden = !features.ghcoin;

  // ---------------------------------------------------------------- the light's real events (AI skin only)
  // a new big taker trade of this coin (the server's relay, the same feed as the terminal's 실시간 큰 체결) and a new
  // market liquidation (the recorder, while it runs) flash the chart once; the first answer of each is the past
  if (chartAi()) {
    const ticks = tickStream(ctx);
    ticks.on((m) => {
      if (!m.first && m.big && Array.isArray(m.big.rows)) for (const r of m.big.rows) if (r && r.s === st.sym && deck) deck.flash(bigEvent(r));
    });
    ticks.start();
    ctx.every(10000, async () => {
      if (!features.liq || !deck || document.hidden) return;
      const sym = st.sym;
      try {
        const d = await ctx.api(`/api/liq?symbol=${encodeURIComponent(sym)}&minutes=60`);
        if (sym !== st.sym || !ctx.alive()) return;
        const keys = (d.rows || []).map((r) => `${r.ts}:${r.usd}:${r.price}`);
        if (st.liqSeen) (d.rows || []).forEach((r, i) => { if (!st.liqSeen.has(keys[i])) deck.flash(liqEvent(r)); });
        st.liqSeen = new Set(keys);
      } catch (e) { /* next poll */ }
    }, {now: true});
  }
  ctx.every(1000, tick, {now: false});
  ctx.every(5000, liveBar, {now: false});
  ctx.every(120000, loadLevels, {now: false});
  ctx.every(15000, () => panels.alerts().load(), {now: true});
  await Promise.all([store.need("board", 60000).catch(() => null), loadCandles()]);
}

export function update(params) { if (alive) alive(params); }

export function unmount() { alive = null; }
