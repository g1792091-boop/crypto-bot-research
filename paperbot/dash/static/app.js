"use strict";
// Paper v4 dashboard, the old screen (/v3, "예전 화면"). Server data: /api/* (read-only store). Live prices: Binance public streams in the browser.
const SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT", "XRPUSDT"];
const TRADE_SYMS = SYMS.slice(0, 6);
const TF_KO = {"1m": "1분", "3m": "3분", "5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "2h": "2시간", "4h": "4시간", "6h": "6시간", "8h": "8시간", "12h": "12시간", "1d": "일봉", "3d": "3일봉", "1w": "주봉", "1M": "월봉"};
// seconds per bar (a month counted as 30 days: only used to place markers, never for the countdown)
const TF_SEC = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600,
  "8h": 28800, "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800, "1M": 2592000};
// the run's timeframes and size. /api/board 'run_shape' (counted from the accounts table, paper v4) refills these in
// place (applyRunShape): the other files share them. The defaults are the v4 rule's (config.V4_GROUPS) until it comes.
// TRADE_TFS: every timeframe some account trades (5m: the reel and its three coin flips only); CORE_TFS: the 36's
// (never 5m; the strategy and digest tabs); JUDGED_TFS: the 36's judged timeframes (4h observed).
const TRADE_TFS = ["5m", "15m", "30m", "1h", "4h"];
const CORE_TFS = ["15m", "30m", "1h", "4h"];
const JUDGED_TFS = ["15m", "30m", "1h"];
const RUN = {accounts: 331, strategy_accounts: 144, q1_family: 108, judged: 241};
// per group: {core|ds200|reel: [judged timeframes]} and {group: {accounts, tfs: {tf: n}, judged}}
const JUDGED_BY_GROUP = {core: ["15m", "30m", "1h"], ds200: ["15m", "30m", "1h"], reel: ["5m"]};
const RUN_GROUPS = {};
// the chart's account features (entries, exits, position lines, S/R) exist on the accounts' own timeframes only
const botTf = (tf) => TRADE_TFS.includes(tf);
const REASON_KO = {SL: "손절", LOCK: "익절 잠금", LIQ: "강제청산", TP: "익절", HALT: "정지", MANUAL: "수동", END: "종료", TIME: "시간 청산"};
const STATUS_KO = {SUBMITTED: "진입 요청", RECORD: "기록만", LATE: "늦음(미진입)", NO_PRICE: "가격 없음", NO_ATR: "ATR 없음"};
// engine outcomes of a signal (outcomes.status); FILTERED: a copy account's own rule skipped the entry
const OUTCOME_KO = {ENTERED: "진입", SKIPPED: "건너뜀", REJECTED: "거절", FILTERED: "규칙으로 건너뜀"};
// extra paper accounts (copies of a strategy with one rule changed, new strategies from the lab)
const EXTRA_KINDS = ["copy", "newlab"];
const EXTRA_ST_KO = {active: "도는 중", suspended: "멈춤(보류)", held: "정지(동결)"};
let INITIAL = 5000;   // replaced by the bot's own value from /api/board
function applyRunShape(r) {
  if (!r) return;
  if (Array.isArray(r.trade_tfs) && r.trade_tfs.length) TRADE_TFS.splice(0, TRADE_TFS.length, ...r.trade_tfs);
  if (Array.isArray(r.core_tfs) && r.core_tfs.length) CORE_TFS.splice(0, CORE_TFS.length, ...r.core_tfs);
  if (Array.isArray(r.judged_tfs) && r.judged_tfs.length) JUDGED_TFS.splice(0, JUDGED_TFS.length, ...r.judged_tfs);
  if (r.judged_by_group && typeof r.judged_by_group === "object")
    for (const [g, tfs] of Object.entries(r.judged_by_group)) if (Array.isArray(tfs)) JUDGED_BY_GROUP[g] = tfs.slice();
  if (r.groups && typeof r.groups === "object") {
    for (const k of Object.keys(RUN_GROUPS)) delete RUN_GROUPS[k];
    Object.assign(RUN_GROUPS, r.groups);
  }
  for (const k of Object.keys(RUN)) if (typeof r[k] === "number") RUN[k] = r[k];
  // counts written in the page itself (<span data-run="strategy_accounts">)
  if (typeof document !== "undefined" && document.querySelectorAll)
    document.querySelectorAll("[data-run]").forEach((el) => { if (RUN[el.dataset.run] != null) el.textContent = RUN[el.dataset.run]; });
}
const $ = (id) => document.getElementById(id);
// Paper v4 groups (/api/board rows carry group, family, exits: paperbot/groups.py). The group switch on the 순위표
// (default: the 36 + the 5m reel + the extra accounts, owners' plan) applies to every account list, position list,
// chart line and P&L on the page: the DeepSeek P&L is shown only while its own group is chosen (owners' D11).
const GROUP_VIEWS = [["main", "기존 36 + 5분봉"], ["core", "기존 36"], ["ds200", "딥시크 44"], ["reel", "5분봉"],
  ["flip", "동전 봇"], ["extra", "추가 계좌"]];
const KIND_GROUP = {strategy: "core", random: "flip", ds200: "ds200", reel: "reel", copy: "extra", newlab: "extra"};
const groupOf = (a) => (a && a.group) || KIND_GROUP[a && a.kind] || "other";
// is an account in a group view: "main" = the 36, the reel and the extras; "reel" = the reel and its 5m coin flips
function inView(a, v) {
  const g = groupOf(a);
  v = v || state.group;
  if (v === "main") return g === "core" || g === "reel" || g === "extra";
  if (v === "reel") return g === "reel" || (g === "flip" && a.timeframe === "5m");
  return g === v;
}
let savedGroup = null;
try { savedGroup = localStorage.getItem("pb-group"); } catch (e) { /* storage blocked */ }
const state = {
  board: null, mark: {}, fund: {}, tick: {}, sym: "BTCUSDT", tf: "15m", acct: "", markers: true, view: "trade",
  sideTab: "pos", botTab: "allpos", account: null, sigTf: "", bf: {tf: "", kind: "", sort: "wallet"},
  lastCandle: null, group: GROUP_VIEWS.some(([k]) => k === savedGroup) ? savedGroup : "main",
};

// ------------------------------------------------------------ helpers
const fmt = (x, d = 2) => x == null || isNaN(x) ? "—" : Number(x).toLocaleString("ko-KR", {minimumFractionDigits: d, maximumFractionDigits: d});
const pxd = (x) => x == null ? 2 : x < 1 ? 5 : x < 10 ? 4 : x < 1000 ? 2 : 1;
const px = (x) => fmt(x, pxd(x));
const pct = (x, d = 1) => x == null || isNaN(x) ? "—" : (x > 0 ? "+" : "") + (x * 100).toFixed(d) + "%";
const cls = (x) => x > 0 ? "up" : x < 0 ? "down" : "";
const tsKo = (ms) => ms ? new Date(ms).toLocaleString("ko-KR", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"}) : "—";
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const coin = (s) => String(s).replace("USDT", "");
// an extra account's own label (the runner's label_ko); a trade row of one is named from the board
const extraLabel = (aid) => {
  const a = state.board && state.board.accounts.find((x) => x.account_id === aid);
  return a ? a.label_ko : null;
};
// a strategy's Korean name, as every Telegram message writes it (agents/roster3 STRATEGY_KO via /api/board)
const stratKo = (s) => String(s).startsWith("RANDOM_") ? String(s).replace("RANDOM_", "동전 봇 ")
  : (state.board && ((state.board.strategy_ko && state.board.strategy_ko[s]) || (state.board.names_ko && state.board.names_ko[s]))) || s;
const name = (a) => a.label_ko || (EXTRA_KINDS.includes(a.kind) && a.account_id && extraLabel(a.account_id))
  || `${stratKo(a.strategy)} · ${TF_KO[a.timeframe] || a.timeframe}`;
// pills of an extra account: what it is (copy / new) and the runner's status when it is not running normally
function extraPills(a) {
  if (!EXTRA_KINDS.includes(a.kind)) return "";
  let h = a.kind === "copy" ? ' <span class="tag xcopy" title="원본과 같고 한 가지만 바꾼 새 paper 계좌">복제</span>'
    : ' <span class="tag xnew" title="새 매매법 연구실에서 통과한 새 매매법의 paper 계좌">새</span>';
  if (a.extra_status === "suspended") h += ' <span class="tag xsus" title="새 진입 없음, 열린 포지션은 규칙대로 관리">멈춤(보류)</span>';
  if (a.extra_status === "held") h += ' <span class="tag bust" title="저장된 상태 그대로 동결">정지(동결)</span>';
  if (a.orphan) h += ' <span class="tag bust" title="에이전트 쪽 제안이 없거나 승인 상태가 아님">제안 상태와 달리 실행 중</span>';
  return h;
}
// the reel and its 5m coin flips run their own exits (reel_engine.py): no ladder, a moving target, a time exit
const REEL_EXITS_KO = "스윙 저점 손절 · 직전 5분봉 볼린저 윗선 익절(5분마다 바뀜) · 96봉(8시간) 시간 청산 · 사다리 없음";
function groupPills(a) {
  return a && a.exits === "reel" ? ` <span class="tag" title="${REEL_EXITS_KO}">자체 청산</span>` : "";
}
const sideTag = (s) => s > 0 ? '<span class="tag long">롱</span>' : '<span class="tag short">숏</span>';
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
async function api(path) {
  const r = await fetch(path, {credentials: "same-origin"});
  if (r.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname + location.hash); throw new Error("login"); }
  if (!r.ok) throw new Error(path + " " + r.status);
  return r.json();
}
function toast(text) {
  const t = $("toast"); t.textContent = text; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 5000);
}
// Engine and runner messages are in English; show them in Korean (Telegram: notify.ko).
function alertKo(text) {
  const t = String(text); let m;
  if ((m = t.match(/^\[([^\]]+)\] drawdown ([\d.]+)% \(level (\d+)%\), equity ([\d.]+)/)))
    return `${idName(m[1])} 낙폭 ${m[2]}% (${m[3]}% 경고선), 잔고 $${m[4]}`;
  if ((m = t.match(/^\[([^\]]+)\] BUST/))) return `${idName(m[1])} 파산 (잔고 $10 미만, 계좌 정지)`;
  if ((m = t.match(/^\[([^\]]+)\] LIQUIDATED (\S+) (\d+)x lost margin ([\d.]+)/)))
    return `${idName(m[1])} 강제청산: ${coin(m[2])} ${m[3]}배, 증거금 $${m[4]} 손실`;
  if ((m = t.match(/^signal workers did not answer within (\d+)s; signals skipped at (\d+) for (.+)/)))
    return `신호 계산 ${m[1]}초 초과로 ${tsKo(+m[2])} 봉 신호 건너뜀: ${m[3].split(", ").map((x) => TF_KO[x] || x).join(", ")}`;
  // paper v4 group texts (sigservice.py): "[ds200] " / "[reel] " name a group, never an account
  if ((m = t.match(/^\[ds200\] DeepSeek signal workers timed out after (\d+)s; DeepSeek signals skipped at (\d+) for (.+)/)))
    return `딥시크 그룹: 신호 계산 ${m[1]}초 초과로 ${tsKo(+m[2])} 봉 딥시크 신호 건너뜀: ${m[3].split(", ").map((x) => TF_KO[x] || x).join(", ")}`;
  if ((m = t.match(/^\[(ds200|reel)\] (.*)/))) return `${m[1] === "ds200" ? "딥시크" : "5분봉"} 그룹: ${m[2]}`;
  if ((m = t.match(/^data gap at (\d+): no bar for (.+)/))) return `데이터 누락 ${tsKo(+m[1])}: ${m[2]}`;
  if (/^no new closed bars/.test(t)) return "새 1분봉이 들어오지 않음: " + t;
  if (/^5m history incomplete/.test(t)) return "5분봉 기록 불완전으로 신호 계산 건너뜀";
  if (/^Binance blocked/.test(t)) return "바이낸스가 서버 접속을 막음: " + t;
  return t;
}
const toastWorthy = (a) => a.level === "CRITICAL" || /BUST|LIQUIDATED|blocked|gap|no new closed/.test(a.text);
function pnlShort(u) {   // "+0.4% +$3"
  if (!u) return "";
  const d = Math.abs(u.pnl) < 10 ? 2 : 0;
  return `${pct(u.roe)} ${u.pnl >= 0 ? "+$" : "-$"}${fmt(Math.abs(u.pnl), d)}`;
}
function entryTitle(p) {   // "진입 롱 20배 +12.3% +$154": the selected account's position, live
  const u = livePnl(p);
  return `진입 ${p.side > 0 ? "롱" : "숏"} ${p.leverage}배${u ? " " + pnlShort(u) : ""}`;
}
// Open positions of the chart's coin as thin lines at their entry price, labelled live on the line
// ("롱 20배 +0.4% +$3", green in profit, red in loss), like an exchange chart. Entries closer than 0.05% share
// one line ("3개 롱2·숏1 합계 +$12"), so labels never pile up. The account picked in the menu has its own line.
let plines = {};   // key -> {line, price}
state.posLines = true;
function renderPosLines() {
  if (!tseries) return;
  const list = state.posLines && TF_SEC[state.tf] < 86400 ? positions().filter((a) => a.position.symbol === state.sym && a.account_id !== state.acct) : [];
  list.sort((x, y) => x.position.entry - y.position.entry);
  const groups = [];
  for (const a of list) {
    const g = groups[groups.length - 1];
    if (g && Math.abs(a.position.entry - g.price) / g.price < 0.0005) g.items.push(a); else groups.push({price: a.position.entry, items: [a]});
  }
  const want = {};
  for (const g of groups) {
    const us = g.items.map((a) => livePnl(a.position));
    const known = us.filter(Boolean), pnl = known.reduce((s, u) => s + u.pnl, 0);
    let title;
    if (g.items.length === 1) { const p = g.items[0].position; title = `${p.side > 0 ? "롱" : "숏"} ${p.leverage}배 ${pnlShort(us[0])}`; }
    else {
      const L = g.items.filter((a) => a.position.side > 0).length;
      title = `${g.items.length}개 ${L ? "롱" + L : ""}${L && L < g.items.length ? "·" : ""}${L < g.items.length ? "숏" + (g.items.length - L) : ""} 합계 ${pnl >= 0 ? "+$" : "-$"}${fmt(Math.abs(pnl), Math.abs(pnl) < 10 ? 2 : 0)}`;
    }
    const key = g.items.map((a) => a.account_id).join(",") + "@" + g.price;
    want[key] = {price: g.price, color: !known.length ? css("--muted") : pnl >= 0 ? css("--up") : css("--down"), title};
  }
  for (const k of Object.keys(plines)) if (!want[k]) { try { tseries.removePriceLine(plines[k].line); } catch (e) { /* gone */ } delete plines[k]; }
  for (const [k, w] of Object.entries(want)) {
    const o = {price: w.price, color: w.color, lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: w.title};
    if (plines[k]) plines[k].line.applyOptions(o); else plines[k] = {line: tseries.createPriceLine(o)};
  }
}
function pickChartAccount(id, symChanged) {   // the chart moves to that account's timeframe, so its entries and exits line up
  const a = state.board && state.board.accounts.find((x) => x.account_id === id);
  const tf = a && a.timeframe, tfChanged = tf && tf !== state.tf && document.querySelector(`#tf-seg button[data-tf="${tf}"]`);
  if (tfChanged) {
    state.tf = tf;
    document.querySelectorAll("#tf-seg button").forEach((b) => b.classList.toggle("on", b.dataset.tf === tf));
  }
  state.acct = id; state.markers = true;
  fillAcctFilter(); $("mk-toggle").classList.add("on");
  loadTradeChart(); if (tfChanged || symChanged) klineStream();
  if (tfChanged) renderTicker();      // the bar-close countdown follows the new timeframe at once
}
function bindPosButtons(root) {
  root.querySelectorAll("button[data-strat]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation();
    if (typeof openStrategy === "function") openStrategy(b.dataset.strat, b.dataset.tf, b.dataset.sym);
  });
  root.querySelectorAll("button[data-acct]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); openAccount(b.dataset.acct); });
  root.querySelectorAll("button[data-chart]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation(); show("trade");
    const moved = b.dataset.sym && b.dataset.sym !== state.sym;
    if (moved) { state.sym = b.dataset.sym; renderWatch(); renderTicker(); renderSide(); }   // one chart load, below
    pickChartAccount(b.dataset.chart, moved);
  });
}
function livePnl(p) {   // p: board position {symbol, side, qty, entry, margin}
  const m = state.mark[p.symbol];
  if (!m) return null;
  const pnl = p.side * p.qty * (m - p.entry);
  return {m, pnl, roe: pnl / p.margin};
}
// the open positions of the accounts in the chosen group view (the switch on the 순위표)
const positions = () => (state.board ? state.board.accounts.filter((a) => a.position && inView(a)) : []);
// a trade row (/api/trades) of an account in the chosen view (an account the board does not know yet is shown)
const tradeInView = (t) => { const a = state.byId && state.byId[t.account_id]; return !a || inView(a); };

// ------------------------------------------------------------ theme and nav
function themeInit() {
  let t = null;
  try { t = localStorage.getItem("pb-theme"); } catch (e) { /* storage blocked */ }
  if (t === "light") document.documentElement.dataset.theme = "light";
  $("theme").onclick = () => {
    const light = document.documentElement.dataset.theme === "light";
    if (light) delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = "light";
    try { localStorage.setItem("pb-theme", light ? "dark" : "light"); } catch (e) { /* ignore */ }
    applyChartTheme();
    if (state.view === "account" && state.account) renderAccount(state.account);
  };
}
$("logout").onclick = async () => { await fetch("/api/logout", {method: "POST"}); location.href = "/login"; };
function show(v) {
  state.view = v;
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("on", b.dataset.v === v));
  document.querySelectorAll("section.view").forEach((s) => s.classList.toggle("on", s.id === "v-" + v));
  if (v === "board") { renderBoard(); loadOverlap(); }
  if (v === "signals") loadSignals();
  if (v === "status") loadStatus();
  if (v === "rooms" && typeof loadRooms === "function") loadRooms();
  if (v === "digest" && typeof loadDigest === "function") loadDigest();
  if (v === "office" && typeof loadOffice === "function") loadOffice();
  if (v === "strat" && typeof loadStrat === "function") loadStrat();
  if (v === "pos" && typeof loadPos === "function") loadPos();
  if (v === "market" && typeof loadMarket === "function") { if (typeof renderMarket === "function") renderMarket(); loadMarket(); }
  if (v === "trade" && tchart) tchart.timeScale().scrollToRealTime();
}
document.querySelectorAll("#nav button").forEach((b) => b.onclick = () => show(b.dataset.v));
$("back").onclick = () => show("board");
function seg(id, attr, cb) {
  document.querySelectorAll(`#${id} button`).forEach((b) => b.onclick = () => {
    document.querySelectorAll(`#${id} button`).forEach((x) => x.classList.toggle("on", x === b));
    cb(b.dataset[attr]);
  });
}

// ------------------------------------------------------------ charts
function chartOpts(el) {
  return {
    width: el.clientWidth, height: el.clientHeight,
    layout: {background: {color: css("--panel")}, textColor: css("--text-2"), fontSize: 11},
    grid: {vertLines: {color: css("--line")}, horzLines: {color: css("--line")}},
    rightPriceScale: {borderColor: css("--line-2")},
    timeScale: {borderColor: css("--line-2"), timeVisible: true, secondsVisible: false},
    crosshair: {mode: 0}, localization: {locale: "ko-KR"},
  };
}
let tchart = null, tseries = null, tlines = [];
function applyChartTheme() {
  if (!tchart) return;
  const el = $("tchart");
  const o = chartOpts(el); delete o.width; delete o.height;
  tchart.applyOptions(o);
  tseries.applyOptions({upColor: css("--up"), downColor: css("--down"), wickUpColor: css("--up"), wickDownColor: css("--down")});
}
function ensureTradeChart() {
  if (tchart || !window.LightweightCharts) return;
  const el = $("tchart");
  tchart = LightweightCharts.createChart(el, chartOpts(el));
  tseries = tchart.addCandlestickSeries({upColor: css("--up"), downColor: css("--down"), borderVisible: false,
    wickUpColor: css("--up"), wickDownColor: css("--down")});
  new ResizeObserver(() => tchart.resize(el.clientWidth, el.clientHeight)).observe(el);
  tchart.subscribeCrosshairMove((p) => {
    const d = p && p.seriesData && p.seriesData.get(tseries);
    legend(d || state.lastCandle);
  });
}
function legend(d) {
  if (!d) { $("legend").innerHTML = ""; return; }
  const ch = (d.close - d.open) / d.open;
  $("legend").innerHTML = `<b>${coin(state.sym)}</b> ${TF_KO[state.tf]} · 시 <b>${px(d.open)}</b> 고 <b>${px(d.high)}</b> ` +
    `저 <b>${px(d.low)}</b> 종 <b>${px(d.close)}</b> <span class="${cls(ch)}">${pct(ch, 2)}</span>`;
}
async function loadTradeChart() {
  ensureTradeChart();
  if (!tchart) { $("tchart").innerHTML = '<p class="empty">차트 부품을 불러오지 못했습니다</p>'; return; }
  let data = [];
  try { data = await api(`/api/candles?symbol=${state.sym}&interval=${state.tf}&limit=500`); }
  catch (e) { toast("가격 데이터를 불러오지 못했습니다"); }
  tseries.setData(data);
  state.lastCandle = data[data.length - 1] || null;
  legend(state.lastCandle);
  await drawTradeMarkers(data.length ? data[0].time : 0);
  tchart.timeScale().fitContent();
  renderPosLines();
  loadLevels();
}

// ------------------------------------------------------------ support / resistance and GH Coin plan lines
// S/R: /api/levels (entry_marks.chart_levels, the same level definitions recorded with every signal): the nearest
// 3 above and below the last closed bar, within 8 ATR. Descriptive only: the entry study found no effect on outcomes.
// GH Coin: its current plan for this coin (board.json of the recorder) when it has a side: entry, stop, TP1, TP2.
const GH_STATE_KO = {long: "롱 타점", short: "숏 타점", longWait: "롱 대기", shortWait: "숏 대기", wait: "관망"};
let slines = [];
function pref(k, d) { try { const v = localStorage.getItem("pb-" + k); return v == null ? d : v === "1"; } catch (e) { return d; } }
function setPref(k, v) { try { localStorage.setItem("pb-" + k, v ? "1" : "0"); } catch (e) { /* private window */ } }
state.srOn = pref("sr", true); state.ghOn = pref("gh", false); state.evOn = pref("ev", true);
let macroEvs = null;           // US releases from /api/events (code only, data/macro_events.csv)
async function macroMarks(t0) {   // a square on the bar of each release in view (CPI · FOMC · NFP · PCE)
  if (!state.evOn || !(TF_SEC[state.tf] < 86400)) return [];
  if (!macroEvs || Date.now() - macroEvs.t > 600000) {
    try { macroEvs = {t: Date.now(), list: (await api("/api/events?days_back=60&days_ahead=1")).events}; } catch (e) { macroEvs = {t: Date.now(), list: []}; }
  }
  const step = TF_SEC[state.tf], now = Date.now() / 1000;
  return macroEvs.list.filter((e) => e.ts_ms / 1000 >= t0 && e.ts_ms / 1000 <= now).map((e) => {
    const s = Math.floor(e.ts_ms / 1000);
    return {time: s - (s % step), position: "aboveBar", color: css("--accent"), shape: "square", text: e.kind};
  });
}
async function loadLevels() {
  const sym = state.sym, tf = state.tf;
  let lv = null, gb = null;
  if (state.srOn && botTf(tf)) { try { lv = await api(`/api/levels?symbol=${sym}&tf=${tf}`); } catch (e) { /* none */ } }
  if (state.ghOn) { try { gb = await api("/api/ghcoin/board"); } catch (e) { /* none */ } }
  if (sym !== state.sym || tf !== state.tf) return;
  state.levels = lv; state.ghBoard = gb;
  drawLevels();
}
function drawLevels() {
  if (!tseries) return;
  slines.forEach((l) => { try { tseries.removePriceLine(l); } catch (e) { /* gone */ } }); slines = [];
  const add = (price, color, style, title) => { if (price) slines.push(tseries.createPriceLine({price, color, lineWidth: 1, lineStyle: style, title})); };
  if (state.srOn && state.levels) {
    for (const side of ["resistance", "support"]) {
      (state.levels.levels || []).filter((x) => x.side === side && (x.atr == null || Math.abs(x.atr) <= 8)).slice(0, 3)
        .forEach((x) => add(x.price, side === "resistance" ? css("--down") : css("--up"), 4, `${side === "resistance" ? "저항" : "지지"} · ${x.ko}`));
    }
  }
  const g = state.ghOn && state.ghBoard && state.ghBoard.coins && state.ghBoard.coins[state.sym];
  if (g && g.side && g.entry) {
    const k = `GH ${GH_STATE_KO[g.state] || g.state}`;
    add(g.entry, css("--accent"), 0, `${k} 진입`); add(g.sl, css("--accent"), 2, `${k} 손절`);
    add(g.tp1, css("--accent"), 2, `${k} 익절1`); add(g.tp2, css("--accent"), 3, `${k} 익절2`);
  }
  const note = [];
  if (state.srOn && state.levels && state.levels.levels) note.push("지지·저항: 설명용 (진입 연구에서 수익과 관계없음)");
  if (state.ghOn) note.push(!state.ghBoard || !state.ghBoard.alive ? "GH Coin 기록기 응답 없음"
    : g ? `GH Coin: ${GH_STATE_KO[g.state] || g.state}${g.why ? " · " + g.why : ""}` : "GH Coin: 이 코인 계획 없음");
  $("lv-note").textContent = note.join(" · ");
}
$("sr-toggle").classList.toggle("on", state.srOn);
$("gh-toggle").classList.toggle("on", state.ghOn);
$("sr-toggle").onclick = (e) => { state.srOn = !state.srOn; setPref("sr", state.srOn); e.target.classList.toggle("on", state.srOn); loadLevels(); };
$("gh-toggle").onclick = (e) => { state.ghOn = !state.ghOn; setPref("gh", state.ghOn); e.target.classList.toggle("on", state.ghOn); loadLevels(); };
$("ev-toggle").classList.toggle("on", state.evOn);
$("ev-toggle").onclick = (e) => { state.evOn = !state.evOn; setPref("ev", state.evOn); e.target.classList.toggle("on", state.evOn); loadTradeChart(); };
setInterval(() => { if (state.view === "trade") loadLevels(); }, 120000);
async function drawTradeMarkers(t0) {
  tlines.forEach((l) => tseries.removePriceLine(l)); tlines = [];
  // All accounts at once would bury the candles in markers: draw them for one chosen account only.
  const ev = await macroMarks(t0);
  if (!state.markers || !botTf(state.tf) || !state.acct) { tseries.setMarkers(ev.sort((a, b) => a.time - b.time)); return; }
  let trades = [];
  try { trades = await api(`/api/trades?symbol=${state.sym}&tf=${state.tf}&limit=600`); } catch (e) { /* none */ }
  if (state.acct) trades = trades.filter((t) => t.account_id === state.acct);
  const step = TF_SEC[state.tf];
  const marks = [];
  trades.filter((t) => t.entry_time / 1000 >= t0).forEach((t) => {
    const e = Math.floor(t.entry_time / 1000), x = Math.floor(t.exit_time / 1000);
    marks.push({time: e - (e % step), position: t.side > 0 ? "belowBar" : "aboveBar", color: css("--series"),
      shape: t.side > 0 ? "arrowUp" : "arrowDown", text: state.acct ? `${t.side > 0 ? "롱" : "숏"} ${t.leverage}배` : ""});
    marks.push({time: x - (x % step), position: t.side > 0 ? "aboveBar" : "belowBar", color: t.pnl > 0 ? css("--up") : css("--down"),
      shape: "circle", text: state.acct ? `${REASON_KO[t.exit_reason] || t.exit_reason} ${pct(t.roe, 0)}` : ""});
  });
  marks.push(...ev);
  marks.sort((a, b) => a.time - b.time);
  tseries.setMarkers(marks);
  state.entryLine = null;
  if (state.acct && state.board) {
    const a = state.board.accounts.find((x) => x.account_id === state.acct);
    const p = a && a.position;
    if (p && p.symbol === state.sym) {
      state.entryLine = tseries.createPriceLine({price: p.entry, color: css("--series"), lineWidth: 1, title: entryTitle(p)});
      tlines.push(state.entryLine);
      if (p.exits === "reel") {   // the reel's own exits: swing-low stop and the band target, no ladder lock
        tlines.push(tseries.createPriceLine({price: p.stop, color: css("--down"), lineWidth: 1, lineStyle: 2, title: "손절(스윙 저점)"}));
        if (p.tp) tlines.push(tseries.createPriceLine({price: p.tp, color: css("--up"), lineWidth: 1, lineStyle: 2, title: "익절 목표(볼린저 윗선)"}));
      } else tlines.push(tseries.createPriceLine({price: p.stop, color: p.lock_roe ? css("--up") : css("--down"), lineWidth: 1, lineStyle: 2,
        title: p.lock_roe ? `잠금 +${Math.round(p.lock_roe * 100)}%` : "손절"}));
      tlines.push(tseries.createPriceLine({price: p.liq, color: css("--accent"), lineWidth: 1, lineStyle: 3, title: "청산가"}));
    }
  }
}

// ------------------------------------------------------------ trade view
function setSym(s) {
  state.sym = s;
  renderWatch(); renderTicker();
  loadTradeChart(); renderSide(); klineStream();
}
function fillAcctFilter() {
  const sel = $("acct-filter"); const cur = state.acct;
  const list = state.board ? state.board.accounts.filter((a) => a.timeframe === state.tf && inView(a)) : [];
  sel.innerHTML = `<option value="">${state.tf === "1d" ? "일봉은 기록 전용 (계좌 없음)" : !botTf(state.tf) ? (list.length ? `${TF_KO[state.tf] || state.tf}: 지금 매매하지 않는 봉 (진입·청산 표시 없음)` : `${TF_KO[state.tf] || state.tf}에는 계좌가 없음 (진입·청산 표시 없음)`) : "계좌를 고르면 진입·청산이 표시됩니다"}</option>` +
    list.map((a) => `<option value="${esc(a.account_id)}">${esc(name(a))}</option>`).join("");
  sel.value = list.some((a) => a.account_id === cur) ? cur : "";
  state.acct = sel.value;
}
seg("tf-seg", "tf", (tf) => { state.tf = tf; fillAcctFilter(); loadTradeChart(); klineStream(); renderTicker(); });
$("acct-filter").onchange = (e) => { state.acct = e.target.value; loadTradeChart(); };
$("mk-toggle").onclick = (e) => { state.markers = !state.markers; e.target.classList.toggle("on", state.markers); loadTradeChart(); };
function renderWatch() {
  $("wl").innerHTML = SYMS.map((s) => {
    const t = state.tick[s], m = state.mark[s];
    const last = t ? t.c : m;
    return `<tr class="click ${s === state.sym ? "sel" : ""}" data-s="${s}"><td>${coin(s)}${s === "XRPUSDT" ? ' <span class="muted">기록</span>' : ""}</td>
      <td>${last ? px(last) : "—"}</td><td class="${t ? cls(t.p) : ""}">${t ? pct(t.p / 100, 2) : "—"}</td></tr>`;
  }).join("");
  document.querySelectorAll("#wl tr").forEach((tr) => tr.onclick = () => setSym(tr.dataset.s));
}
function renderTicker() {
  const s = state.sym, t = state.tick[s], f = state.fund[s];
  $("t-sym").innerHTML = `${coin(s)}USDT<small>무기한</small>`;
  $("t-px").textContent = t ? px(t.c) : state.mark[s] ? px(state.mark[s]) : "—";
  $("t-px").className = "lastpx " + (t ? cls(t.p) : "");
  $("t-chg").innerHTML = t ? `<span class="${cls(t.p)}">${pct(t.p / 100, 2)}</span>` : "—";
  $("t-hi").textContent = t ? px(t.h) : "—";
  $("t-lo").textContent = t ? px(t.l) : "—";
  $("t-vol").textContent = t ? (t.q >= 1e9 ? (t.q / 1e9).toFixed(2) + "B" : (t.q / 1e6).toFixed(1) + "M") : "—";
  $("t-mark").textContent = state.mark[s] ? px(state.mark[s]) : "—";
  if (f) {
    const left = Math.max(0, f.T - Date.now()), h = Math.floor(left / 3.6e6), m = Math.floor(left % 3.6e6 / 6e4);
    $("t-fund").innerHTML = `<span class="${cls(-f.r)}">${(f.r * 100).toFixed(4)}%</span> / ${h}시간 ${m}분`;
  } else $("t-fund").textContent = "—";
  const tfk = TF_KO[state.tf] || state.tf;
  $("t-cd-k").textContent = `${tfk}${tfk.endsWith("봉") ? "" : "봉"} 마감까지`;
  $("t-cd").textContent = closeIn(state.tf);
  const n = positions().filter((a) => a.position.symbol === s).length;
  $("t-pos").textContent = state.board ? `${n}개 계좌` : "—";
  $("t-sess").textContent = sessionText(Date.now());
}
// sessions.py, in Korea time: asia 09-16, europe 16-22, us 22-05, dawn 05-09; weekend Sat/Sun; US stock open 09:30 New York
const SESS_KO = {asia: "아시아장", europe: "유럽장", us: "미국장", dawn: "새벽"};
function sessionText(now) {
  const k = new Date(now + 9 * 3.6e6), h = k.getUTCHours(), wd = k.getUTCDay();
  const ss = h >= 9 && h < 16 ? "asia" : h >= 16 && h < 22 ? "europe" : h >= 5 && h < 9 ? "dawn" : "us";
  let out = (wd === 0 || wd === 6 ? "주말 · " : "") + SESS_KO[ss];
  const ny = new Intl.DateTimeFormat("en-US", {timeZone: "America/New_York", hour12: false, weekday: "short", hour: "2-digit", minute: "2-digit"})
    .formatToParts(new Date(now)).reduce((o, p) => (o[p.type] = p.value, o), {});
  const mins = (+ny.hour % 24) * 60 + +ny.minute, open = 9 * 60 + 30;
  if (!["Sat", "Sun"].includes(ny.weekday)) {
    if (mins < open && open - mins <= 360) out += ` · 미국 증시 개장까지 ${Math.floor((open - mins) / 60)}시간 ${(open - mins) % 60}분`;
    else if (mins >= open && mins < open + 60) out += " · 미국 증시 개장 직후";
  }
  return out;
}
seg("side-tabs", "t", (t) => { state.sideTab = t; renderSide(); });
seg("bot-tabs", "t", (t) => { state.botTab = t; renderBottom(); });
function posRows(list, withCoin) {
  if (!list.length) return '<p class="empty">열린 포지션이 없습니다</p>';
  return `<table><thead><tr><th class="l">계좌</th>${withCoin ? '<th class="l">코인</th>' : ""}<th class="l">방향</th><th>배수</th>
    ${withCoin ? "<th>진입가</th>" : ""}<th>평가 ROE</th><th>손절/잠금·목표</th><th class="l">보기</th></tr></thead><tbody>` + list.map((a) => {
    const p = a.position, u = livePnl(p);
    const stop = p.exits === "reel" ? `${px(p.stop)} <small class="muted" title="${REEL_EXITS_KO}">목표 ${p.tp ? px(p.tp) : "—"}</small>`
      : p.lock_roe ? `<span class="up">+${Math.round(p.lock_roe * 100)}% 잠금</span>` : px(p.stop);
    const strat = a.kind === "strategy" || a.kind === "copy";
    return `<tr class="click" data-id="${esc(a.account_id)}"><td class="l" title="${esc(a.account_id)}">${esc(name(a))}</td>${withCoin ? `<td class="l">${coin(p.symbol)}</td>` : ""}
      <td class="l">${sideTag(p.side)}</td><td>${p.leverage}배</td>${withCoin ? `<td class="mono">${px(p.entry)}</td>` : ""}
      <td class="mono ${u ? cls(u.roe) : ""}">${u ? pct(u.roe) : "—"}</td><td class="mono">${stop}</td>
      <td class="l"><button class="mini" data-chart="${esc(a.account_id)}" data-sym="${esc(p.symbol)}">차트</button>${strat ? ` <button class="mini" data-strat="${esc(a.strategy)}" data-tf="${esc(a.timeframe)}" data-sym="${esc(p.symbol)}">매매법</button>` : ""}</td></tr>`;
  }).join("") + "</tbody></table>";
}
function tradeRows(rows, withCoin) {
  if (!rows.length) return '<p class="empty">체결 내역이 없습니다</p>';
  return `<table><thead><tr><th class="l">청산 시각</th><th class="l">계좌</th>${withCoin ? '<th class="l">코인</th>' : ""}<th class="l">방향</th>
    <th>배수</th><th class="l">이유</th><th>ROE</th><th>손익</th></tr></thead><tbody>` + rows.map((t) => `<tr class="click" data-id="${esc(t.account_id)}">
    <td class="l">${tsKo(t.exit_time)}</td><td class="l" title="${esc(t.account_id)}">${esc(name(t))}</td>${withCoin ? `<td class="l">${coin(t.symbol)}</td>` : ""}
    <td class="l">${sideTag(t.side)}</td><td>${t.leverage}배${t.tier === "best" ? ' <span class="tag good" title="진입 품질 best: 50배·50%부터 시도">좋은 자리</span>' : ""}</td>
    <td class="l">${REASON_KO[t.exit_reason] || t.exit_reason}${t.lock_roe ? ` +${Math.round(t.lock_roe * 100)}%` : ""}</td>
    <td class="mono ${cls(t.roe)}">${pct(t.roe)}</td><td class="mono ${cls(t.pnl)}">${t.pnl > 0 ? "+" : ""}${fmt(t.pnl)}</td></tr>`).join("") + "</tbody></table>";
}
function bindAccountClicks(root) {
  root.querySelectorAll("tr.click[data-id]").forEach((tr) => tr.onclick = () => openAccount(tr.dataset.id));
  bindPosButtons(root);
}
async function renderSide() {
  const el = $("side-body");
  if (state.sideTab === "pos") el.innerHTML = posRows(positions().filter((a) => a.position.symbol === state.sym), false);
  else if (state.sideTab === "trades") el.innerHTML = tradeRows((await api(`/api/trades?symbol=${state.sym}&limit=100&group=${state.group}`).catch(() => [])).filter(tradeInView), false);
  else {
    const rows = await api(`/api/signals?symbol=${state.sym}&limit=150`).catch(() => []);
    el.innerHTML = rows.length ? `<table><thead><tr><th class="l">봉 마감</th><th class="l">봉</th><th class="l">매매법</th><th class="l">방향</th>
      <th>지연</th><th class="l">상태</th></tr></thead><tbody>` + rows.map((r) => `<tr><td class="l">${tsKo(r.bar_close)}</td>
      <td class="l">${TF_KO[r.timeframe] || r.timeframe}</td><td class="l">${esc(r.strategy.replace("RANDOM_", "동전 봇 "))}</td>
      <td class="l">${sideTag(r.side)}</td><td>${r.delay_ms == null ? "—" : (r.delay_ms / 1000).toFixed(1) + "초"}</td>
      <td class="l">${STATUS_KO[r.status] || r.status}</td></tr>`).join("") + "</tbody></table>" : '<p class="empty">이 코인 신호가 없습니다</p>';
  }
  bindAccountClicks(el);
}
async function renderBottom() {
  const el = $("bot-body");
  if (state.botTab === "allpos") el.innerHTML = posRows(positions(), true);
  else if (state.botTab === "alltrades") el.innerHTML = tradeRows((await api(`/api/trades?limit=150&group=${state.group}`).catch(() => [])).filter(tradeInView), true);
  else el.innerHTML = tfSummary();
  bindAccountClicks(el);
}
// rows per (group, timeframe) of the groups in the chosen view; the coin flips are the yardstick column (their own rows
// only in the 동전 봇 view) and the extras one line of their own, never inside the original accounts' numbers
const GROUP_ROW_KO = {core: "기존 36", ds200: "딥시크", reel: "5분봉 단타", flip: "동전 봇", extra: "추가 계좌"};
const REF_NOTE = "참고: 딥시크는 늘 '보통' 배수인데 동전 봇은 21%를 '좋은 자리' 배수로 거래해 공정한 기준이 아님";
function median(xs) { if (!xs.length) return null; const s = [...xs].sort((a, b) => a - b); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; }
function tfSummary() {
  if (!state.board) return "";
  const accts = state.board.accounts;
  const extras = accts.filter((a) => EXTRA_KINDS.includes(a.kind) && inView(a));
  let gs = ["core", "ds200", "reel"].filter((g) => accts.some((a) => groupOf(a) === g && inView(a)));
  if (!gs.length && accts.some((a) => groupOf(a) === "flip" && inView(a))) gs = ["flip"];
  const top = (xs) => xs.reduce((b, a) => (!b || (a.wallet ?? INITIAL) > (b.wallet ?? INITIAL)) ? a : b, null);
  const rows = gs.map((g) => TRADE_TFS.map((tf) => {
    const st = accts.filter((a) => a.timeframe === tf && groupOf(a) === g && inView(a));
    if (!st.length) return "";
    const rnd = accts.filter((a) => a.timeframe === tf && a.kind === "random");
    const w = st.map((a) => a.wallet ?? INITIAL), best = top(st);
    const ref = g === "ds200" ? ` <small class="muted" title="${REF_NOTE}">참고</small>` : "";
    return `<tr><td class="l">${GROUP_ROW_KO[g]} · ${TF_KO[tf] || tf}</td><td>${st.length}</td><td>${st.filter((a) => a.position).length}</td>
      <td>${st.filter((a) => a.bust).length}</td><td class="mono">$${fmt(median(w))}</td>
      <td class="l">${best ? esc(stratKo(best.strategy)) + ` <span class="mono ${cls((best.wallet ?? INITIAL) - INITIAL)}">$${fmt(best.wallet ?? INITIAL)}</span>` : "—"}</td>
      <td class="mono">${rnd.length ? "$" + fmt(Math.max(...rnd.map((a) => a.wallet ?? INITIAL))) : "—"}</td>
      <td>${g === "flip" ? "—" : st.filter((a) => a.beats_random).length + ref}</td></tr>`;
  }).join("")).join("");
  // the extra accounts in one line of their own (never inside the original accounts' numbers)
  const xbest = top(extras);
  const xrow = extras.length ? `<tr><td class="l">추가 계좌</td><td>${extras.length}</td><td>${extras.filter((a) => a.position).length}</td>
      <td>${extras.filter((a) => a.bust).length}</td><td class="mono">$${fmt(median(extras.map((a) => a.wallet ?? INITIAL)))}</td>
      <td class="l">${xbest ? esc(name(xbest)) + ` <span class="mono ${cls((xbest.wallet ?? INITIAL) - INITIAL)}">$${fmt(xbest.wallet ?? INITIAL)}</span>` : "—"}</td>
      <td class="mono">—</td><td title="늦게 시작해 처음부터 돈 동전 봇과 잔고를 비교하지 않음">—</td></tr>` : "";
  return `<table><thead><tr><th class="l">그룹 · 봉</th><th>계좌</th><th>포지션</th><th>파산</th><th>잔고 중앙값</th>
    <th class="l">최고 계좌</th><th>동전 봇 최고</th><th>동전 봇보다 나음</th></tr></thead><tbody>${rows}${xrow}</tbody></table>`;
}

// ------------------------------------------------------------ board
async function loadBoard() {
  state.board = await api("/api/board");
  state.byId = Object.fromEntries(state.board.accounts.map((a) => [a.account_id, a]));
  if (state.board.initial) INITIAL = state.board.initial;
  applyRunShape(state.board.run_shape);
  if (!$("acct-filter").options.length || $("acct-filter").options.length === 1) fillAcctFilter();
  renderTicker();
  if (state.view === "board") renderBoard();
  if (state.view === "trade") { if (state.sideTab === "pos") renderSide(); if (state.botTab !== "alltrades") renderBottom(); }
  // the strategy tab's live record (wins, losses, P&L) follows a closed trade too
  if (state.view === "strat" && typeof renderSList === "function") { renderSList(); renderLive(); renderAccts(); }
}
// the group switch (GROUP_VIEWS): built once; a choice is remembered in this browser and redraws every view
function setGroup(v) {
  if (!GROUP_VIEWS.some(([k]) => k === v)) return;
  state.group = v;
  try { localStorage.setItem("pb-group", v); } catch (e) { /* private window */ }
  document.querySelectorAll("#f-group button").forEach((x) => x.classList.toggle("on", x.dataset.g === v));
  renderBoard(); fillAcctFilter(); renderPosLines(); renderSide(); renderBottom();
  if (typeof document.dispatchEvent === "function" && typeof Event === "function") document.dispatchEvent(new Event("pb-group"));
}
function buildGroupSwitch() {
  const el = $("f-group");
  if (!el) return;
  el.innerHTML = GROUP_VIEWS.map(([k, label]) => `<button data-g="${k}" class="${k === state.group ? "on" : ""}">${label}</button>`).join("");
  el.querySelectorAll("button").forEach((b) => b.onclick = () => setGroup(b.dataset.g));
}
buildGroupSwitch();
// the timeframe buttons of the chosen view (5m only where the view has 5m accounts: the reel and its coin flips)
let tfSegKey = "";
function buildTfSeg(tfs) {
  const key = tfs.join(",");
  if (!state.bf.tf || !tfs.includes(state.bf.tf)) state.bf.tf = "";
  if (key + "|" + state.bf.tf === tfSegKey) return;
  tfSegKey = key + "|" + state.bf.tf;
  $("f-tf").innerHTML = `<button data-tf="" class="${state.bf.tf ? "" : "on"}">전체</button>` +
    tfs.map((tf) => `<button data-tf="${tf}" class="${state.bf.tf === tf ? "on" : ""}">${TF_KO[tf] || tf}</button>`).join("");
  seg("f-tf", "tf", (v) => { state.bf.tf = v; renderBoard(); });
}
$("f-sort").onchange = (e) => { state.bf.sort = e.target.value; renderBoard(); };
// copies / new strategies inside a view that has extra accounts (the group switch chooses the groups)
seg("f-kind", "k", (v) => { state.bf.kind = v; renderBoard(); });
// group summary cards (기존 36 / 딥시크 44 / 5분봉 / 동전 봇, + 추가 계좌 when there is one); a tap chooses that view.
// The DeepSeek card shows counts only until its own view is chosen (owners' D11: its P&L stays in its own group).
const CARD_GROUPS = [["core", "기존 36"], ["ds200", "딥시크 44"], ["reel", "5분봉"], ["flip", "동전 봇"], ["extra", "추가 계좌"]];
function groupStats(list) {
  const w = list.map((a) => a.wallet ?? INITIAL);
  return {n: list.length, pos: list.filter((a) => a.position).length, bust: list.filter((a) => a.bust).length,
    above: w.filter((x) => x > INITIAL).length, beats: list.filter((a) => a.beats_random).length, med: median(w)};
}
function groupCards(all) {
  return CARD_GROUPS.map(([g, label]) => {
    const list = all.filter((a) => groupOf(a) === g);
    if (!list.length && g === "extra") return "";
    const s = groupStats(list), on = state.group === g || (state.group === "main" && ["core", "reel", "extra"].includes(g));
    let v, sub;
    if (!list.length) { v = "—"; sub = "아직 계좌 없음"; }
    else if (g === "ds200" && state.group !== "ds200") {
      v = `${s.n}개`; sub = `포지션 ${s.pos} · 파산 ${s.bust}<br><span class="muted">손익은 눌러서 딥시크 보기에서만</span>`;
    } else if (g === "reel") {
      const r = list[0], w = r.wallet ?? INITIAL;
      const f5 = all.filter((a) => a.kind === "random" && a.timeframe === r.timeframe);
      const fb = f5.length ? Math.max(...f5.map((a) => a.wallet ?? INITIAL)) : null;
      v = `$${fmt(w)} <small class="${cls(w - INITIAL)}">${pct(w / INITIAL - 1)}</small>`;
      sub = `거래 ${r.trades} · ${r.position ? "포지션 중" : "대기"}${r.bust ? " · 파산" : ""}<br>5분 동전 봇 ${f5.length}개 최고 ${fb == null ? "—" : "$" + fmt(fb)}`;
    } else {
      v = `$${fmt(s.med)} <small class="muted">중앙값</small>`;
      sub = `계좌 ${s.n} · 포지션 ${s.pos} · 파산 ${s.bust}` + (g === "flip" || g === "extra" ? ""
        : `<br>$${fmt(INITIAL, 0)} 넘음 ${s.above} · 동전 봇보다 나음 ${s.beats}${g === "ds200" ? ` <span class="muted" title="${REF_NOTE}">(참고)</span>` : ""}`);
    }
    return `<button class="tile gcard${on ? " on" : ""}" data-g="${g}"><div class="k">${label}</div><div class="v">${v}</div><div class="s">${sub}</div></button>`;
  }).join("");
}
function renderBoard() {
  const b = state.board; if (!b) return;
  const all = b.accounts, view = all.filter((a) => inView(a));
  const gc = $("gcards");
  if (gc) {
    gc.innerHTML = groupCards(all);
    gc.querySelectorAll("button.gcard[data-g]").forEach((x) => x.onclick = () => setGroup(x.dataset.g));
  }
  const judged = view.filter((a) => !["flip", "extra"].includes(groupOf(a)));   // the accounts compared with the coin flips
  const per = {};
  view.forEach((a) => { const g = groupOf(a); per[g] = (per[g] || 0) + 1; });
  const ds = state.group === "ds200";
  const nx = per.extra || 0;
  $("tiles").innerHTML = [
    ["계좌", nx && nx < view.length ? `${view.length - nx} + 추가 ${nx}` : view.length,
      Object.entries(per).map(([g, n]) => `${GROUP_ROW_KO[g] || g} ${n}`).join(" · ") || "—"],
    ["포지션 중", view.filter((a) => a.position).length, "지금 열린 포지션"],
    ["$" + fmt(INITIAL, 0) + " 넘은 계좌", judged.filter((a) => (a.wallet ?? INITIAL) > INITIAL).length, `${judged.length}개 중 (동전 봇·추가 계좌 빼고)`],
    ["동전 봇보다 나은 계좌", judged.filter((a) => a.beats_random).length + (ds ? ' <small class="muted">참고</small>' : ""),
      "같은 봉 동전 봇 3개 최고보다 잔고가 큼" + (ds ? " · 딥시크는 참고만" : "")],
    ["파산", view.filter((a) => a.bust).length, "잔고 $10 미만으로 정지"],
  ].map(([k, v, s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
  buildTfSeg(TRADE_TFS.filter((tf) => view.some((a) => a.timeframe === tf)));
  const f = state.bf, fk = $("f-kind");
  if (fk) fk.hidden = !nx;
  if (!nx) f.kind = "";
  const rows = view.filter((a) => (!f.tf || a.timeframe === f.tf) && (!f.kind || a.kind === f.kind));
  const key = {wallet: (a) => -(a.wallet ?? INITIAL), trades: (a) => -a.trades, win: (a) => -(a.win_rate ?? -1),
    dd: (a) => a.max_drawdown ?? 0, name: (a) => name(a)}[f.sort];
  rows.sort((x, y) => { const p = key(x), q = key(y); return p < q ? -1 : p > q ? 1 : 0; });
  $("board").innerHTML = rows.map((a, i) => {
    const w = a.wallet ?? INITIAL, ret = w / INITIAL - 1;
    let st = '<span class="tag">대기</span>';
    if (a.bust) st = '<span class="tag bust">✕ 파산</span>';
    else if (a.position) {
      const p = a.position, u = livePnl(p);
      st = `<span class="tag acc">● ${coin(p.symbol)} ${p.side > 0 ? "롱" : "숏"} ${p.leverage}배${u ? ` <span class="${cls(u.roe)}">${pct(u.roe)}</span>` : ""}</span>`;
    }
    const vs = a.kind === "random" ? '<span class="muted">기준</span>'
      : a.beats_random == null ? "—"
      : a.vs_random_ref ? `<span class="muted" title="${REF_NOTE}">${a.beats_random ? "✓ 나음" : "✕ 못함"} · 참고</span>`
      : a.beats_random ? '<span class="up">✓ 나음</span>' : '<span class="down">✕ 못함</span>';
    return `<tr class="click" data-id="${esc(a.account_id)}"><td class="l muted" data-k="순위">${i + 1}</td><td class="l name" title="${esc(a.account_id)}">${esc(name(a))}${extraPills(a)}${groupPills(a)}</td>
      <td class="mono" data-k="잔고">$${fmt(w)}</td><td class="mono ${cls(ret)}" data-k="수익률">${pct(ret)}</td><td data-k="거래">${a.trades}</td>
      <td data-k="승률">${a.win_rate == null ? "—" : Math.round(a.win_rate * 100) + "%"}${a.trades ? ` <small class="muted">${a.wins}승 ${a.losses}패</small>` : ""}</td>
      <td class="mono" data-k="최대 낙폭">${a.max_drawdown ? "-" + (a.max_drawdown * 100).toFixed(1) + "%" : "—"}</td>
      <td class="l">${st}</td><td class="l" data-k="동전 봇 대비">${vs}</td></tr>`;
  }).join("") || '<tr><td colspan="9" class="empty">계좌가 없습니다</td></tr>';
  bindAccountClicks($("board"));
}

// ------------------------------------------------------------ overlap (순위표 아래, /api/overlap)
// Descriptive only: which accounts moved together and when many piled into one coin+side.
let ovAt = 0;
const idName = (id) => {
  const x = extraLabel(id);
  if (x) return x;
  const i = String(id).lastIndexOf("@");
  return i < 0 ? String(id) : name({strategy: id.slice(0, i), timeframe: id.slice(i + 1)});
};
const usd = (x) => x == null ? "—" : (x < 0 ? "-$" : "+$") + fmt(Math.abs(x), 0);
const mins = (m) => m >= 60 ? `${Math.floor(m / 60)}시간${m % 60 ? ` ${m % 60}분` : ""}` : `${m}분`;
async function loadOverlap(force) {
  if (!force && Date.now() - ovAt < 600000) return;     // the server caches ~10 min too
  ovAt = Date.now();
  try { renderOverlap(await api("/api/overlap?days=7")); }
  catch (e) { ovAt = 0; $("ov-body").innerHTML = '<p class="muted">겹침 분석을 불러오지 못했습니다.</p>'; }
}
function renderOverlap(d) {
  const el = $("ov-body");
  $("ov-at").textContent = d.computed_at ? tsKo(d.computed_at) + " 계산" : "";
  if (!d.window) { el.innerHTML = '<p class="muted">아직 자본 기록이 없습니다.</p>'; return; }
  const r = d.rules, ac = d.accounts, ex = d.exposure, pr = d.pairs;
  const chip = (a) => `<button class="ovchip" data-id="${esc(a.account_id)}">${esc(name(a))}</button>`;
  let h = `<p class="ovnote">지난 ${d.window.days}일 기록을 그대로 정리한 것입니다(설명용, 앞으로도 그렇다는 예측이 아님).
    계좌끼리 비교는 기록이 충분할 때만 합니다: 같이 쌓인 기록 ${r.min_days}일 이상, 계좌마다 거래 ${r.min_trades}번 이상.
    지금 비교 가능한 매매법 계좌 <b>${ac.strategy_enough_data}/${ac.strategy}</b>개. 동전 봇은 묶지 않고 기준으로만 봅니다.</p>`;
  // groups
  h += `<h3 class="ovh">같이 움직이는 계좌</h3><p class="ovsub">1시간 수익률이 서로 ${r.group_corr} 이상 같이 움직인 계좌 묶음(묶음 안 모든 쌍이 그 이상). 한 묶음은 사실상 같은 베팅입니다.</p>`;
  if (!d.groups.length) {
    h += `<p class="muted">${ac.strategy_enough_data < 2 ? "아직 데이터가 충분한 계좌가 적어 묶음을 만들 수 없습니다." : `상관 ${r.group_corr} 이상으로 묶인 계좌가 없습니다.`}</p>`;
  } else {
    h += d.groups.slice(0, 8).map((g) => {
      const c = g.combined;
      const comb = c ? `<div class="ovc">모두 같이 돌렸다면: 최대 낙폭 <b class="down">-${(c.max_dd * 100).toFixed(1)}%</b>
        (계좌 평균 -${(c.avg_member_max_dd * 100).toFixed(1)}%) · 최악의 날 <span class="mono ${cls(c.worst_day)}">${usd(c.worst_day)}</span>
        (각자 최악의 날 합 <span class="mono">${usd(c.members_worst_days_sum)}</span>)${c.dd_ratio != null && c.dd_ratio > 0.8 ? " · 합쳐도 낙폭이 거의 줄지 않음" : ""}</div>` : "";
      return `<div class="ovg"><div class="ovgh"><b>${g.size}개 계좌</b> <span class="muted">매매법 ${g.strategies}개 · 상관 최소 ${g.min_corr.toFixed(2)} / 평균 ${g.mean_corr.toFixed(2)}${g.same_of_busy_mean != null ? ` · 포지션 있을 때 같은 코인·방향 ${Math.round(g.same_of_busy_mean * 100)}%` : ""}</span></div>
        <div class="ovchips">${g.accounts.map(chip).join("")}</div>${comb}</div>`;
    }).join("") + (d.groups.length > 8 ? `<p class="muted">외 ${d.groups.length - 8}개 묶음</p>` : "");
  }
  const rs = pr && pr.random_reference && pr.random_reference.random_pairs;
  if (pr && pr.corr && pr.corr.pairs) h += `<p class="ovsub">비교한 매매법 계좌 쌍 ${pr.corr.pairs}개: 상관 중앙값 ${pr.corr.median.toFixed(2)}, ${r.group_corr} 이상 ${Math.round(pr.corr.share_ge_group * 100)}%${rs && rs.pairs ? ` · 동전 봇끼리(우연의 기준) 중앙값 ${rs.median.toFixed(2)}` : ""}. 데이터 부족으로 뺀 쌍 ${pr.insufficient}개.</p>`;
  // crowded moments
  h += `<h3 class="ovh">한 코인에 몰린 순간</h3>`;
  if (!ex || !ex.top.length) h += '<p class="muted">겹친 포지션 기록이 없습니다.</p>';
  else {
    const ge5 = ex.share_ge5 != null ? Math.round(ex.share_ge5 * 100) : null;
    h += `<p class="ovsub">5분마다 같은 코인·같은 방향에 들어가 있던 매매법 계좌 수(지속 = 그 절반 이상이 함께 들고 있던 시간). 가장 많이 몰린 때 <b>${ex.max.count}개</b>
      (${coin(ex.max.symbol)} ${ex.max.side > 0 ? "롱" : "숏"}, ${tsKo(ex.max.ts)}), 보통은 ${ex.percentiles.p50}개${ge5 ? `, 시간의 ${ge5}%는 5개 이상` : ""}. 이 계좌들이 한 계정에 있었다면 같이 벌고 같이 잃습니다.</p>`;
    h += `<table class="cards ovt"><thead><tr><th class="l">시각</th><th class="l">코인·방향</th><th>계좌 수</th><th>매매법 수</th><th>지속</th><th class="l">계좌</th></tr></thead><tbody>` +
      ex.top.map((m) => `<tr><td class="l" data-k="시각">${tsKo(m.ts)}</td><td class="l" data-k="코인">${coin(m.symbol)} ${sideTag(m.side)}</td>
        <td class="mono" data-k="계좌 수">${m.count}</td><td class="mono" data-k="매매법 수">${m.strategies}</td>
        <td data-k="절반 이상 유지">${m.minutes != null ? mins(m.minutes) : "—"}</td>
        <td class="l ovlist">${m.accounts.slice(0, 6).map((a) => esc(idName(a))).join(", ")}${m.accounts.length > 6 ? ` 외 ${m.accounts.length - 6}` : ""}</td></tr>`).join("") +
      "</tbody></table>";
  }
  el.innerHTML = h;
  el.querySelectorAll(".ovchip[data-id]").forEach((b) => b.onclick = () => openAccount(b.dataset.id));
}

// ------------------------------------------------------------ account
let acharts = [];
async function openAccount(id) {
  show("account");
  state.account = await api("/api/account/" + encodeURIComponent(id));
  renderAccount(state.account);
}
function renderAccount(d) {
  $("acct-empty").hidden = true; $("acct").hidden = false;
  const a = d.account, st = d.state || {}, trades = d.trades;
  const w = st.wallet ?? INITIAL, n = trades.length, wins = trades.filter((t) => t.pnl > 0).length;
  const reel = a.exits === "reel";      // the reel's own exits: target (TP) and time exits instead of the ladder lock
  const locks = trades.filter((t) => t.exit_reason === (reel ? "TP" : "LOCK")).length;
  $("a-csv").href = "/api/export/trades.csv?account=" + encodeURIComponent(a.account_id);
  $("a-title").innerHTML = esc(name({...a, label_ko: d.extra ? d.extra.label_ko : null})) + (d.extra ? extraPills({...a, ...d.extra}) : "") + groupPills(a);
  $("a-tiles").innerHTML = [
    ["잔고", "$" + fmt(w), pct(w / INITIAL - 1)],
    ["거래", n, `승률 ${n ? Math.round(wins / n * 100) + "%" : "—"}`],
    [reel ? "익절 목표 청산" : "익절 잠금 청산", locks, (n ? Math.round(locks / n * 100) + "%" : "") + (reel ? ` · 시간 청산 ${trades.filter((t) => t.exit_reason === "TIME").length}` : "")],
    ["최대 낙폭", st.max_drawdown ? "-" + (st.max_drawdown * 100).toFixed(1) + "%" : "—", st.bust ? "파산" : ""],
    ["신호", Object.values(d.signals).reduce((s, x) => s + x, 0),
      `${OUTCOME_KO.ENTERED} ${d.signals.ENTERED || 0} · ${OUTCOME_KO.SKIPPED} ${d.signals.SKIPPED || 0} · ${OUTCOME_KO.REJECTED} ${d.signals.REJECTED || 0}`
        + (d.signals.FILTERED ? ` · ${OUTCOME_KO.FILTERED} ${d.signals.FILTERED}` : "")],
  ].map(([k, v, s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
  renderExtraInfo(d.extra);
  renderAcctPos(st.position, d.position_why, a.exits);
  acharts.forEach((c) => c.remove()); acharts = [];
  if (window.LightweightCharts) {
    const el = $("a-eq"); const c = LightweightCharts.createChart(el, chartOpts(el)); acharts.push(c);
    const s = c.addLineSeries({color: css("--series"), lineWidth: 2, priceFormat: {type: "price", precision: 2, minMove: 0.01}});
    const pts = d.equity.map((p) => ({time: Math.floor(p.t / 1000), value: p.v}));
    s.setData(pts.length ? pts : [{time: Math.floor(Date.now() / 1000), value: w}]);
    s.createPriceLine({price: INITIAL, color: css("--muted"), lineStyle: 2, lineWidth: 1, title: "시작"});
    c.timeScale().fitContent();
  }
  const syms = [...new Set(trades.map((t) => t.symbol).concat(st.position ? [st.position.symbol] : []))];
  const sel = $("a-sym"); const cur = sel.value;
  sel.innerHTML = (syms.length ? syms : TRADE_SYMS).map((s) => `<option value="${s}">${coin(s)}</option>`).join("");
  if (syms.includes(cur)) sel.value = cur;
  sel.onchange = () => drawAcctCandles(d);
  drawAcctCandles(d);
  $("a-trades").innerHTML = trades.map((t) => `<tr><td class="l">${tsKo(t.exit_time)}</td><td class="l">${coin(t.symbol)}</td>
    <td class="l">${sideTag(t.side)}</td><td>${t.leverage}배</td><td class="mono">${px(t.entry_price)}</td><td class="mono">${px(t.exit_price)}</td>
    <td class="l">${REASON_KO[t.exit_reason] || t.exit_reason}${t.lock_roe ? ` (+${Math.round(t.lock_roe * 100)}%)` : ""}</td>
    <td class="mono ${cls(t.roe)}">${pct(t.roe)}</td><td class="mono ${cls(t.pnl)}">${t.pnl > 0 ? "+" : ""}${fmt(t.pnl)}</td>
    <td class="mono">$${fmt(t.equity_after)}</td></tr>${t.why && typeof whyHtml === "function" ? `<tr class="why-row"><td colspan="10" class="l"><span class="why">왜 ${t.leverage}배: ${whyHtml(t.why)}</span></td></tr>` : ""}`).join("") || '<tr><td colspan="10" class="empty">아직 거래가 없습니다</td></tr>';
}
// an extra account: what it is (rule or new strategy), where it came from, when it started, the runner's events
const EVENT_KO = {created: "시작", suspended: "멈춤(보류)", resumed: "다시 돎", held: "정지(동결)", code_accepted: "새 코드 받아들임"};
function renderExtraInfo(x) {
  const el = $("a-extra");
  if (!el) return;
  if (!x) { el.hidden = true; el.innerHTML = ""; return; }
  el.hidden = false;
  const what = x.kind === "copy" ? `복제 계좌 · 원본 ${esc(x.parent || "")} · 바꾼 규칙: <b>${esc(x.rule_ko || "")}</b>`
    : `새 매매법 계좌 · ${esc(x.description_ko || "")}`;
  const ev = (x.events || []).slice(-8).reverse().map((e) => `<li>${tsKo(e.ts)} ${esc(EVENT_KO[e.event] || e.event)}${e.code ? ` (${esc(e.code)})` : ""}</li>`).join("");
  el.innerHTML = `<div class="ph"><span class="t">추가 계좌</span></div><div class="body"><div>${what}</div>
    <div class="muted">제안 #${esc(x.proposal_id ?? "—")}${x.trial_id != null ? ` · 시험·장부 #${esc(x.trial_id)}` : ""} · 시작 ${tsKo(x.created_ts)} ·
    상태 ${esc(EXTRA_ST_KO[x.extra_status] || x.extra_status || "—")}</div>
    ${x.kind === "newlab" && x.spec ? `<div class="muted mono">${esc(JSON.stringify(x.spec))}</div>` : ""}
    ${ev ? `<ul class="reasons">${ev}</ul>` : ""}
    <div class="muted">원본 ${RUN.accounts}개 계좌와 따로 셉니다. 시작된 계좌는 규칙대로 돌고, 거절로 멈출 수 없습니다.</div></div>`;
}
// the reel's time exit of a saved position (reel_engine.py: signal.meta.reel_exit.end), null for any other
const reelEnd = (p) => { const m = p && p.signal && p.signal.meta, st = m && m.reel_exit; return st && typeof st.end === "number" ? st.end : null; };
function renderAcctPos(p, why, exits) {
  const el = $("a-pos");
  if (!p) { el.innerHTML = '<span class="muted">없음</span>'; return; }
  const u = livePnl({symbol: p.symbol, side: p.side, qty: p.qty, entry: p.entry_price, margin: p.margin});
  if (exits === "reel") {     // no ladder lock: the swing-low stop, the moving band target and the time exit
    el.innerHTML = `<div style="margin-bottom:8px">${coin(p.symbol)} ${sideTag(p.side)} <b>${p.leverage}배</b> <span class="tag" title="${REEL_EXITS_KO}">자체 청산</span></div><div class="kv">
    <div><span>현재가(마크)</span>${u ? px(u.m) : "—"}</div>
    <div><span>평가 손익 (ROE)</span><b class="${u ? cls(u.pnl) : ""}">${u ? (u.pnl > 0 ? "+" : "") + fmt(u.pnl) + " (" + pct(u.roe) + ")" : "—"}</b></div>
    <div><span>진입가</span>${px(p.entry_price)}</div>
    <div><span>손절(스윙 저점)</span>${px(p.stop_price)}</div>
    <div><span>익절 목표(직전 5분봉 볼린저 윗선)</span>${p.tp_price == null ? "—" : px(p.tp_price)}</div>
    <div><span>시간 청산</span>${tsKo(reelEnd(p))}</div><div><span>청산가</span>${px(p.liq_price)}</div>
    <div><span>증거금</span>$${fmt(p.margin)}</div><div><span>진입 시각</span>${tsKo(p.entry_time)}</div></div>
    <div class="muted">${REEL_EXITS_KO}</div>
    ${why && typeof whyHtml === "function" ? `<div class="why">왜 ${p.leverage}배: ${whyHtml(why)}</div>` : ""}`;
    return;
  }
  el.innerHTML = `<div style="margin-bottom:8px">${coin(p.symbol)} ${sideTag(p.side)} <b>${p.leverage}배</b></div><div class="kv">
    <div><span>현재가(마크)</span>${u ? px(u.m) : "—"}</div>
    <div><span>평가 손익 (ROE)</span><b class="${u ? cls(u.pnl) : ""}">${u ? (u.pnl > 0 ? "+" : "") + fmt(u.pnl) + " (" + pct(u.roe) + ")" : "—"}</b></div>
    <div><span>진입가</span>${px(p.entry_price)}</div>
    <div><span>손절선</span>${px(p.stop_price)}${p.lock_roe ? ` <span class="up">+${Math.round(p.lock_roe * 100)}% 잠금</span>` : ""}</div>
    <div><span>첫 손절</span>${px(p.stop_initial)}</div><div><span>청산가</span>${px(p.liq_price)}</div>
    <div><span>증거금</span>$${fmt(p.margin)}</div><div><span>진입 시각</span>${tsKo(p.entry_time)}</div></div>
    ${why && typeof whyHtml === "function" ? `<div class="why">왜 ${p.leverage}배: ${whyHtml(why)}</div>` : ""}`;
}
async function drawAcctCandles(d) {
  const el = $("a-candles");
  if (!window.LightweightCharts) { el.innerHTML = '<p class="empty">차트 부품을 불러오지 못했습니다</p>'; return; }
  const sym = $("a-sym").value, tf = d.account.timeframe;
  let data;
  try { data = await api(`/api/candles?symbol=${sym}&interval=${tf}&limit=400`); }
  catch (e) { el.innerHTML = '<p class="empty">가격 데이터를 불러오지 못했습니다</p>'; return; }
  el.innerHTML = "";
  const c = LightweightCharts.createChart(el, chartOpts(el)); acharts.push(c);
  const s = c.addCandlestickSeries({upColor: css("--up"), downColor: css("--down"), borderVisible: false,
    wickUpColor: css("--up"), wickDownColor: css("--down")});
  s.setData(data);
  const t0 = data.length ? data[0].time : 0, step = TF_SEC[tf] || 60, marks = [];
  d.trades.filter((t) => t.symbol === sym && t.entry_time / 1000 >= t0).forEach((t) => {
    const e = Math.floor(t.entry_time / 1000), x = Math.floor(t.exit_time / 1000);
    marks.push({time: e - e % step, position: t.side > 0 ? "belowBar" : "aboveBar", color: css("--series"),
      shape: t.side > 0 ? "arrowUp" : "arrowDown", text: `${t.side > 0 ? "롱" : "숏"} ${t.leverage}배`});
    marks.push({time: x - x % step, position: t.side > 0 ? "aboveBar" : "belowBar", color: t.pnl > 0 ? css("--up") : css("--down"),
      shape: "circle", text: `${REASON_KO[t.exit_reason] || t.exit_reason} ${pct(t.roe, 0)}`});
  });
  marks.sort((a, b) => a.time - b.time);
  s.setMarkers(marks);
  const p = d.state && d.state.position;
  if (p && p.symbol === sym) {
    s.createPriceLine({price: p.entry_price, color: css("--series"), lineWidth: 1, title: "진입"});
    if (d.account.exits === "reel") {
      s.createPriceLine({price: p.stop_price, color: css("--down"), lineWidth: 1, lineStyle: 2, title: "손절(스윙 저점)"});
      if (p.tp_price != null) s.createPriceLine({price: p.tp_price, color: css("--up"), lineWidth: 1, lineStyle: 2, title: "익절 목표(볼린저 윗선)"});
    } else s.createPriceLine({price: p.stop_price, color: p.lock_roe ? css("--up") : css("--down"), lineWidth: 1, lineStyle: 2, title: p.lock_roe ? "잠금" : "손절"});
    s.createPriceLine({price: p.liq_price, color: css("--accent"), lineWidth: 1, lineStyle: 3, title: "청산가"});
  }
  c.timeScale().fitContent();
}

// ------------------------------------------------------------ signals & status
seg("sig-tf", "tf", (v) => { state.sigTf = v; loadSignals(); });
async function loadSignals() {
  const rows = await api("/api/signals?limit=300" + (state.sigTf ? "&tf=" + state.sigTf : "")).catch(() => []);
  $("signals").innerHTML = rows.map((r) => `<tr><td class="l">${tsKo(r.bar_close)}</td><td class="l">${TF_KO[r.timeframe] || r.timeframe}</td>
    <td class="l" title="${esc(r.strategy)}">${esc(stratKo(r.strategy))}</td><td class="l">${coin(r.symbol)}</td><td class="l">${sideTag(r.side)}</td>
    <td class="mono">${px(r.ref_price)}</td><td>${r.delay_ms == null ? "—" : (r.delay_ms / 1000).toFixed(1) + "초"}</td>
    <td class="l">${STATUS_KO[r.status] || r.status}</td></tr>`).join("") || '<tr><td colspan="8" class="empty">신호가 없습니다</td></tr>';
}
async function loadStatus() {
  const s = await api("/api/status");
  const hb = s.heartbeat, age = hb ? (s.now - hb[0]) / 1000 : null, run = s.run ? s.run[1] : {};
  $("st-tiles").innerHTML = [
    ["봇 생존 신호", age == null ? "없음" : age < 90 ? "정상" : Math.round(age) + "초 전", hb ? tsKo(hb[0]) : ""],
    ["계좌", run.accounts ?? "—", run.restored ? "재시작 후 복구됨" : "새로 시작"],
    ["수수료(편도)", run.taker_fee != null ? (run.taker_fee * 100).toFixed(3) + "%" : "—", "계정 실제 수수료율"],
    ["레버리지 구간", run.brackets ? (run.brackets.includes("EXAMPLE") ? "예시 표" : "거래소 실제 값") : "—", ""],
  ].map(([k, v, x]) => `<div class="tile"><div class="k">${k}</div><div class="v">${esc(v)}</div><div class="s">${esc(x)}</div></div>`).join("");
  $("st-sig").innerHTML = s.signals_24h.map((r) => `<tr><td class="l">${TF_KO[r.timeframe] || r.timeframe}</td><td class="l">${STATUS_KO[r.status] || r.status}</td>
    <td>${r.n}</td><td>${r.avg_delay == null ? "—" : (r.avg_delay / 1000).toFixed(1) + "초"}</td></tr>`).join("")
    || '<tr><td colspan="4" class="empty">최근 신호 없음</td></tr>';
  $("st-alerts").innerHTML = s.alerts.map((a) => `<tr><td class="l">${tsKo(a.ts)}</td><td class="l ${a.level === "CRITICAL" ? "down" : "accent"}">
    ${a.level === "CRITICAL" ? "긴급" : "주의"}</td><td class="l" style="white-space:normal">${esc(alertKo(a.text))}</td></tr>`).join("")
    || '<tr><td colspan="3" class="empty">경고 없음</td></tr>';
}

// ------------------------------------------------------------ live: server events
function chip(id, ok, text) { const el = $(id); el.className = (id === "chip-bot" ? "" : "opt ") + (ok === true ? "ok" : ok === false ? "bad" : "warn"); el.innerHTML = `<i></i>${text}`; }
function heartbeat(hb) {
  const age = hb ? (Date.now() - hb[0]) / 1000 : null;
  chip("chip-bot", age != null && age < 90, age == null ? "봇 신호 없음" : age < 90 ? "봇 실시간" : `봇 응답 없음 ${Math.round(age)}초`);
}
function stream() {
  const es = new EventSource("/api/stream");
  es.onopen = () => { if (typeof onRoomsStream === "function") onRoomsStream(null); };   // (re)connected: catch up
  es.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    heartbeat(d.heartbeat);
    if (d.rooms && Object.keys(d.rooms).length && typeof onRoomsStream === "function") onRoomsStream(d.rooms);
    if (d.rooms && Object.keys(d.rooms).length && typeof onOfficeStream === "function") onOfficeStream();
    if (Object.keys(d.changed).length) loadBoard();
    // a toast per closed trade of the 36, the reel and the extras only (owners' D10: DeepSeek and the coin flips are
    // counted, not announced; a liquidation of any group still comes as a CRITICAL alert below)
    d.trades.filter((t) => { const a = state.byId && state.byId[t.account_id]; return !a || ["core", "reel", "extra"].includes(groupOf(a)); })
      .forEach((t) => toast(`${idName(t.account_id)} ${coin(t.symbol)} ${REASON_KO[t.exit_reason] || t.exit_reason} ${pct(t.roe)} → $${fmt(t.equity_after)}`));
    d.alerts.filter(toastWorthy).forEach((a) => toast(`⚠ ${alertKo(a.text)}`));
    if (d.trades.length && state.view === "trade") { if (state.sideTab === "trades") renderSide(); if (state.botTab === "alltrades") renderBottom(); loadTradeChart(); }
    if (state.view === "account" && state.account && d.trades.some((t) => t.account_id === state.account.account.account_id)) openAccount(state.account.account.account_id);
  };
  es.onerror = () => chip("chip-bot", false, "재연결 중");
}

// time left in a bar. Binance bars are aligned to UTC: up to 3 days the epoch modulo works, a week starts on Monday
// 00:00 UTC (the epoch was a Thursday: 4 days before a Monday), a month on the 1st 00:00 UTC. The clock is the
// server's (state.clockSkew from /api/time, charts.js), so a phone whose clock is off still counts right.
const TF_MS = {"1m": 6e4, "3m": 18e4, "5m": 3e5, "15m": 9e5, "30m": 18e5, "1h": 36e5, "2h": 72e5, "4h": 144e5, "6h": 216e5,
  "8h": 288e5, "12h": 432e5, "1d": 864e5, "3d": 2592e5};
const nowMs = () => Date.now() + (state.clockSkew || 0);
function barEnd(tf, now) {
  if (TF_MS[tf]) return now - (now % TF_MS[tf]) + TF_MS[tf];
  if (tf === "1w") { const w = 6048e5, mon = 3456e5; return now - ((now - mon) % w) + w; }
  if (tf === "1M") { const d = new Date(now); return Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1); }
  return null;
}
function closeIn(tf) {
  const now = nowMs(), end = barEnd(tf, now); if (end == null) return "—";
  const left = Math.ceil((end - now) / 1000), dd = Math.floor(left / 86400), h = Math.floor(left % 86400 / 3600), m = Math.floor(left % 3600 / 60), s = left % 60;
  const two = (x) => String(x).padStart(2, "0");
  return dd ? `${dd}일 ${h}:${two(m)}:${two(s)}` : h ? `${h}:${two(m)}:${two(s)}` : `${two(m)}:${two(s)}`;
}

// ------------------------------------------------------------ live: Binance public streams (browser side)
// Where the browser cannot reach Binance's WebSocket (some networks and phones), the same numbers come from
// the dashboard server instead (/api/ticker, /api/candles), polled every 5 s while the stream is down.
let mws = null, kws = null, mwsOk = false, kwsOk = false;
async function pollTicker() {
  if (mwsOk) return;
  try {
    const d = await api("/api/ticker");
    for (const [s, v] of Object.entries(d)) {
      if (v.c != null) state.tick[s] = {c: v.c, p: v.p, h: v.h, l: v.l, q: v.q};
      if (v.mark != null) { state.mark[s] = v.mark; state.fund[s] = {r: v.r, T: v.T}; }
    }
    if (!mwsOk && Object.keys(d).length) chip("chip-feed", true, "시세 (서버 경유)");
  } catch (e) { /* login redirect or server down: the bot chip shows it */ }
}
async function pollKline() {
  if (kwsOk || !tseries) return;
  const sym = state.sym, tf = state.tf;
  try {
    const rows = await api(`/api/candles?symbol=${sym}&interval=${tf}&limit=2`);
    if (sym !== state.sym || tf !== state.tf) return;
    for (const c of rows) { try { tseries.update(c); state.lastCandle = c; } catch (e) { /* older than the last bar */ } }
  } catch (e) { /* next poll */ }
}
setInterval(pollTicker, 5000);
setInterval(pollKline, 5000);
function marketStream() {
  const streams = SYMS.flatMap((s) => [s.toLowerCase() + "@markPrice@1s", s.toLowerCase() + "@ticker"]).join("/");
  try { mws = new WebSocket("wss://fstream.binance.com/stream?streams=" + streams); } catch (e) { chip("chip-feed", false, "시세 끊김"); return; }
  mws.onopen = () => { mwsOk = true; chip("chip-feed", true, "바이낸스 시세"); };
  mws.onmessage = (ev) => {
    const m = JSON.parse(ev.data).data; if (!m) return;
    if (m.e === "markPriceUpdate") { state.mark[m.s] = +m.p; state.fund[m.s] = {r: +m.r, T: +m.T}; }
    else if (m.e === "24hrTicker") state.tick[m.s] = {c: +m.c, p: +m.P, h: +m.h, l: +m.l, q: +m.q};
  };
  mws.onclose = () => { mwsOk = false; chip("chip-feed", false, "시세 재연결 중"); pollTicker(); setTimeout(marketStream, 5000); };
}
function klineStream() {
  if (kws) { kws.onclose = null; kws.close(); }
  kwsOk = false;
  const tf = state.tf, sym = state.sym;
  try { kws = new WebSocket(`wss://fstream.binance.com/ws/${sym.toLowerCase()}@kline_${tf}`); } catch (e) { return; }
  kws.onmessage = (ev) => {
    const k = JSON.parse(ev.data).k; if (!k || !tseries || sym !== state.sym || tf !== state.tf) return;
    const c = {time: Math.floor(k.t / 1000), open: +k.o, high: +k.h, low: +k.l, close: +k.c};
    try { tseries.update(c); state.lastCandle = c; } catch (e) { /* older than the last bar */ }
  };
  kws.onopen = () => { kwsOk = true; };
  kws.onclose = () => { kwsOk = false; setTimeout(() => { if (sym === state.sym && tf === state.tf) klineStream(); }, 5000); };
}
setInterval(() => {
  renderWatch(); renderTicker();
  if (state.view === "trade") {
    renderPosLines();
    if (state.entryLine && state.acct && state.board) {
      const a = state.board.accounts.find((x) => x.account_id === state.acct);
      if (a && a.position && a.position.symbol === state.sym) { try { state.entryLine.applyOptions({title: entryTitle(a.position)}); } catch (e) { /* line removed */ } }
    }
    if (state.sideTab === "pos") renderSide();
    if (state.botTab === "allpos") renderBottom();
  }
  if (state.view === "board") renderBoard();
  // (with its 'why this leverage' line: the 1 s refresh used to drop it)
  if (state.view === "account" && state.account) renderAcctPos(state.account.state && state.account.state.position, state.account.position_why, state.account.account.exits);
}, 1000);

// ------------------------------------------------------------ start
// the top bar wraps on phones: full-height panes (rooms) subtract its real height
function topHeight() {   // the top bar and the experiment strip under it
  const ex = document.getElementById("expbar");
  document.documentElement.style.setProperty("--toph", document.querySelector(".topbar").offsetHeight + (ex ? ex.offsetHeight : 0) + "px");
}
window.addEventListener("resize", topHeight);
topHeight();
themeInit();
chip("chip-ai", null, "에이전트 연결 전");
renderWatch();
pollTicker();
loadBoard().then(() => { fillAcctFilter(); loadTradeChart(); renderSide(); renderBottom(); stream(); marketStream(); klineStream(); })
  .catch((e) => console.error(e));
$("pl-toggle").onclick = (e) => { state.posLines = !state.posLines; e.target.classList.toggle("on", state.posLines); renderPosLines(); };
