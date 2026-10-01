"use strict";
// Paper v3 dashboard. Server data: /api/* (read-only store). Live prices: Binance public streams in the browser.
const SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT", "XRPUSDT"];
const TRADE_SYMS = SYMS.slice(0, 6);
const TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일봉"};
const TF_SEC = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400};
const TRADE_TFS = ["5m", "15m", "30m", "1h", "4h"];
const REASON_KO = {SL: "손절", LOCK: "익절 잠금", LIQ: "강제청산", TP: "익절", HALT: "정지", MANUAL: "수동", END: "종료"};
const STATUS_KO = {SUBMITTED: "진입 요청", RECORD: "기록만", LATE: "늦음(미진입)", NO_PRICE: "가격 없음", NO_ATR: "ATR 없음"};
let INITIAL = 5000;   // replaced by the bot's own value from /api/board
const $ = (id) => document.getElementById(id);
const state = {
  board: null, mark: {}, fund: {}, tick: {}, sym: "BTCUSDT", tf: "15m", acct: "", markers: true, view: "trade",
  sideTab: "pos", botTab: "allpos", account: null, sigTf: "", bf: {tf: "", kind: "", sort: "wallet"},
  lastCandle: null,
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
const name = (a) => `${a.strategy.replace("RANDOM_", "동전 봇 ")} · ${TF_KO[a.timeframe] || a.timeframe}`;
const sideTag = (s) => s > 0 ? '<span class="tag long">롱</span>' : '<span class="tag short">숏</span>';
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
async function api(path) {
  const r = await fetch(path, {credentials: "same-origin"});
  if (r.status === 401) { location.href = "/login"; throw new Error("login"); }
  if (!r.ok) throw new Error(path + " " + r.status);
  return r.json();
}
function toast(text) {
  const t = $("toast"); t.textContent = text; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 5000);
}
// Engine and runner messages are in English; show them in Korean.
function alertKo(text) {
  const t = String(text); let m;
  if ((m = t.match(/^\[([^\]]+)\] drawdown ([\d.]+)% \(level (\d+)%\), equity ([\d.]+)/)))
    return `${m[1]} 낙폭 ${m[2]}% (${m[3]}% 경고선), 잔고 $${m[4]}`;
  if ((m = t.match(/^\[([^\]]+)\] BUST/))) return `${m[1]} 파산 (잔고 $10 미만, 계좌 정지)`;
  if ((m = t.match(/^\[([^\]]+)\] LIQUIDATED (\S+) (\d+)x lost margin ([\d.]+)/)))
    return `${m[1]} 강제청산: ${coin(m[2])} ${m[3]}배, 증거금 $${m[4]} 손실`;
  if ((m = t.match(/^data gap at (\d+): no bar for (.+)/))) return `데이터 누락 ${tsKo(+m[1])}: ${m[2]}`;
  if (/^no new closed bars/.test(t)) return "새 1분봉이 들어오지 않음: " + t;
  if (/^5m history incomplete/.test(t)) return "5분봉 기록 불완전으로 신호 계산 건너뜀";
  if (/^Binance blocked/.test(t)) return "바이낸스가 서버 접속을 막음: " + t;
  return t;
}
const toastWorthy = (a) => a.level === "CRITICAL" || /BUST|LIQUIDATED|blocked|gap|no new closed/.test(a.text);
function livePnl(p) {   // p: board position {symbol, side, qty, entry, margin}
  const m = state.mark[p.symbol];
  if (!m) return null;
  const pnl = p.side * p.qty * (m - p.entry);
  return {m, pnl, roe: pnl / p.margin};
}
const positions = () => (state.board ? state.board.accounts.filter((a) => a.position) : []);

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
  if (v === "strat" && typeof loadStrat === "function") loadStrat();
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
}
async function drawTradeMarkers(t0) {
  tlines.forEach((l) => tseries.removePriceLine(l)); tlines = [];
  // All accounts at once would bury the candles in markers: draw them for one chosen account only.
  if (!state.markers || state.tf === "1d" || !state.acct) { tseries.setMarkers([]); return; }
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
  marks.sort((a, b) => a.time - b.time);
  tseries.setMarkers(marks);
  if (state.acct && state.board) {
    const a = state.board.accounts.find((x) => x.account_id === state.acct);
    const p = a && a.position;
    if (p && p.symbol === state.sym) {
      tlines.push(tseries.createPriceLine({price: p.entry, color: css("--series"), lineWidth: 1, title: "진입"}));
      tlines.push(tseries.createPriceLine({price: p.stop, color: p.lock_roe ? css("--up") : css("--down"), lineWidth: 1, lineStyle: 2,
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
  const list = state.board ? state.board.accounts.filter((a) => a.timeframe === state.tf) : [];
  sel.innerHTML = `<option value="">${state.tf === "1d" ? "일봉은 기록 전용 (계좌 없음)" : "계좌를 고르면 진입·청산이 표시됩니다"}</option>` +
    list.map((a) => `<option value="${esc(a.account_id)}">${esc(name(a))}</option>`).join("");
  sel.value = list.some((a) => a.account_id === cur) ? cur : "";
  state.acct = sel.value;
}
seg("tf-seg", "tf", (tf) => { state.tf = tf; fillAcctFilter(); loadTradeChart(); klineStream(); });
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
  const n = positions().filter((a) => a.position.symbol === s).length;
  $("t-pos").textContent = state.board ? `${n}개 계좌` : "—";
}
seg("side-tabs", "t", (t) => { state.sideTab = t; renderSide(); });
seg("bot-tabs", "t", (t) => { state.botTab = t; renderBottom(); });
function posRows(list, withCoin) {
  if (!list.length) return '<p class="empty">열린 포지션이 없습니다</p>';
  return `<table><thead><tr><th class="l">계좌</th>${withCoin ? '<th class="l">코인</th>' : ""}<th class="l">방향</th><th>배수</th>
    ${withCoin ? "<th>진입가</th>" : ""}<th>평가 ROE</th><th>손절/잠금</th></tr></thead><tbody>` + list.map((a) => {
    const p = a.position, u = livePnl(p);
    const stop = p.lock_roe ? `<span class="up">+${Math.round(p.lock_roe * 100)}% 잠금</span>` : px(p.stop);
    return `<tr class="click" data-id="${esc(a.account_id)}"><td class="l">${esc(name(a))}</td>${withCoin ? `<td class="l">${coin(p.symbol)}</td>` : ""}
      <td class="l">${sideTag(p.side)}</td><td>${p.leverage}배</td>${withCoin ? `<td class="mono">${px(p.entry)}</td>` : ""}
      <td class="mono ${u ? cls(u.roe) : ""}">${u ? pct(u.roe) : "—"}</td><td class="mono">${stop}</td></tr>`;
  }).join("") + "</tbody></table>";
}
function tradeRows(rows, withCoin) {
  if (!rows.length) return '<p class="empty">체결 내역이 없습니다</p>';
  return `<table><thead><tr><th class="l">청산 시각</th><th class="l">계좌</th>${withCoin ? '<th class="l">코인</th>' : ""}<th class="l">방향</th>
    <th>배수</th><th class="l">이유</th><th>ROE</th><th>손익</th></tr></thead><tbody>` + rows.map((t) => `<tr class="click" data-id="${esc(t.account_id)}">
    <td class="l">${tsKo(t.exit_time)}</td><td class="l">${esc(name(t))}</td>${withCoin ? `<td class="l">${coin(t.symbol)}</td>` : ""}
    <td class="l">${sideTag(t.side)}</td><td>${t.leverage}배</td>
    <td class="l">${REASON_KO[t.exit_reason] || t.exit_reason}${t.lock_roe ? ` +${Math.round(t.lock_roe * 100)}%` : ""}</td>
    <td class="mono ${cls(t.roe)}">${pct(t.roe)}</td><td class="mono ${cls(t.pnl)}">${t.pnl > 0 ? "+" : ""}${fmt(t.pnl)}</td></tr>`).join("") + "</tbody></table>";
}
function bindAccountClicks(root) {
  root.querySelectorAll("tr.click[data-id]").forEach((tr) => tr.onclick = () => openAccount(tr.dataset.id));
}
async function renderSide() {
  const el = $("side-body");
  if (state.sideTab === "pos") el.innerHTML = posRows(positions().filter((a) => a.position.symbol === state.sym), false);
  else if (state.sideTab === "trades") el.innerHTML = tradeRows(await api(`/api/trades?symbol=${state.sym}&limit=100`).catch(() => []), false);
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
  else if (state.botTab === "alltrades") el.innerHTML = tradeRows(await api("/api/trades?limit=150").catch(() => []), true);
  else el.innerHTML = tfSummary();
  bindAccountClicks(el);
}
function median(xs) { if (!xs.length) return null; const s = [...xs].sort((a, b) => a - b); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; }
function tfSummary() {
  if (!state.board) return "";
  const rows = TRADE_TFS.map((tf) => {
    const all = state.board.accounts.filter((a) => a.timeframe === tf);
    const st = all.filter((a) => a.kind === "strategy"), rnd = all.filter((a) => a.kind === "random");
    const w = st.map((a) => a.wallet ?? INITIAL);
    const best = st.reduce((b, a) => (!b || (a.wallet ?? INITIAL) > (b.wallet ?? INITIAL)) ? a : b, null);
    return `<tr><td class="l">${TF_KO[tf]}</td><td>${st.length}</td><td>${all.filter((a) => a.position).length}</td>
      <td>${st.filter((a) => a.bust).length}</td><td class="mono">$${fmt(median(w))}</td>
      <td class="l">${best ? esc(best.strategy) + ` <span class="mono ${cls((best.wallet ?? INITIAL) - INITIAL)}">$${fmt(best.wallet ?? INITIAL)}</span>` : "—"}</td>
      <td class="mono">$${fmt(Math.max(...rnd.map((a) => a.wallet ?? INITIAL), 0))}</td>
      <td>${st.filter((a) => a.beats_random).length}</td></tr>`;
  }).join("");
  return `<table><thead><tr><th class="l">봉</th><th>매매법 계좌</th><th>포지션</th><th>파산</th><th>잔고 중앙값</th>
    <th class="l">최고 계좌</th><th>동전 봇 최고</th><th>동전 봇보다 나음</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// ------------------------------------------------------------ board
async function loadBoard() {
  state.board = await api("/api/board");
  if (state.board.initial) INITIAL = state.board.initial;
  if (!$("acct-filter").options.length || $("acct-filter").options.length === 1) fillAcctFilter();
  renderTicker();
  if (state.view === "board") renderBoard();
  if (state.view === "trade") { if (state.sideTab === "pos") renderSide(); if (state.botTab !== "alltrades") renderBottom(); }
}
seg("f-tf", "tf", (v) => { state.bf.tf = v; renderBoard(); });
seg("f-kind", "k", (v) => { state.bf.kind = v; renderBoard(); });
$("f-sort").onchange = (e) => { state.bf.sort = e.target.value; renderBoard(); };
function renderBoard() {
  const b = state.board; if (!b) return;
  const all = b.accounts, strat = all.filter((a) => a.kind === "strategy");
  $("tiles").innerHTML = [
    ["계좌", all.length, `매매법 ${strat.length} · 동전 봇 ${all.length - strat.length}`],
    ["포지션 중", all.filter((a) => a.position).length, "지금 열린 포지션"],
    ["$" + fmt(INITIAL, 0) + " 넘은 매매법", strat.filter((a) => (a.wallet ?? INITIAL) > INITIAL).length, `${strat.length}개 중`],
    ["동전 봇보다 나은 매매법", strat.filter((a) => a.beats_random).length, "같은 봉 동전 봇 3개 최고보다 잔고가 큼"],
    ["파산", all.filter((a) => a.bust).length, "잔고 $10 미만으로 정지"],
  ].map(([k, v, s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
  const f = state.bf;
  const rows = all.filter((a) => (!f.tf || a.timeframe === f.tf) && (!f.kind || a.kind === f.kind));
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
      : a.beats_random == null ? "—" : a.beats_random ? '<span class="up">✓ 나음</span>' : '<span class="down">✕ 못함</span>';
    return `<tr class="click" data-id="${esc(a.account_id)}"><td class="l muted" data-k="순위">${i + 1}</td><td class="l name">${esc(name(a))}</td>
      <td class="mono" data-k="잔고">$${fmt(w)}</td><td class="mono ${cls(ret)}" data-k="수익률">${pct(ret)}</td><td data-k="거래">${a.trades}</td>
      <td data-k="승률">${a.win_rate == null ? "—" : Math.round(a.win_rate * 100) + "%"}</td>
      <td class="mono" data-k="최대 낙폭">${a.max_drawdown ? "-" + (a.max_drawdown * 100).toFixed(1) + "%" : "—"}</td>
      <td class="l">${st}</td><td class="l" data-k="동전 봇 대비">${vs}</td></tr>`;
  }).join("") || '<tr><td colspan="9" class="empty">계좌가 없습니다</td></tr>';
  bindAccountClicks($("board"));
}

// ------------------------------------------------------------ overlap (순위표 아래, /api/overlap)
// Descriptive only: which accounts moved together and when many piled into one coin+side.
let ovAt = 0;
const idName = (id) => { const i = String(id).lastIndexOf("@"); return i < 0 ? String(id) : name({strategy: id.slice(0, i), timeframe: id.slice(i + 1)}); };
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
  const locks = trades.filter((t) => t.exit_reason === "LOCK").length;
  $("a-title").textContent = name(a);
  $("a-tiles").innerHTML = [
    ["잔고", "$" + fmt(w), pct(w / INITIAL - 1)],
    ["거래", n, `승률 ${n ? Math.round(wins / n * 100) + "%" : "—"}`],
    ["익절 잠금 청산", locks, n ? Math.round(locks / n * 100) + "%" : ""],
    ["최대 낙폭", st.max_drawdown ? "-" + (st.max_drawdown * 100).toFixed(1) + "%" : "—", st.bust ? "파산" : ""],
    ["신호", Object.values(d.signals).reduce((s, x) => s + x, 0),
      `진입 ${d.signals.ENTERED || 0} · 건너뜀 ${d.signals.SKIPPED || 0} · 거절 ${d.signals.REJECTED || 0}`],
  ].map(([k, v, s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
  renderAcctPos(st.position);
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
    <td class="mono">$${fmt(t.equity_after)}</td></tr>`).join("") || '<tr><td colspan="10" class="empty">아직 거래가 없습니다</td></tr>';
}
function renderAcctPos(p) {
  const el = $("a-pos");
  if (!p) { el.innerHTML = '<span class="muted">없음</span>'; return; }
  const u = livePnl({symbol: p.symbol, side: p.side, qty: p.qty, entry: p.entry_price, margin: p.margin});
  el.innerHTML = `<div style="margin-bottom:8px">${coin(p.symbol)} ${sideTag(p.side)} <b>${p.leverage}배</b></div><div class="kv">
    <div><span>현재가(마크)</span>${u ? px(u.m) : "—"}</div>
    <div><span>평가 손익 (ROE)</span><b class="${u ? cls(u.pnl) : ""}">${u ? (u.pnl > 0 ? "+" : "") + fmt(u.pnl) + " (" + pct(u.roe) + ")" : "—"}</b></div>
    <div><span>진입가</span>${px(p.entry_price)}</div>
    <div><span>손절선</span>${px(p.stop_price)}${p.lock_roe ? ` <span class="up">+${Math.round(p.lock_roe * 100)}% 잠금</span>` : ""}</div>
    <div><span>첫 손절</span>${px(p.stop_initial)}</div><div><span>청산가</span>${px(p.liq_price)}</div>
    <div><span>증거금</span>$${fmt(p.margin)}</div><div><span>진입 시각</span>${tsKo(p.entry_time)}</div></div>`;
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
    s.createPriceLine({price: p.stop_price, color: p.lock_roe ? css("--up") : css("--down"), lineWidth: 1, lineStyle: 2, title: p.lock_roe ? "잠금" : "손절"});
    s.createPriceLine({price: p.liq_price, color: css("--accent"), lineWidth: 1, lineStyle: 3, title: "청산가"});
  }
  c.timeScale().fitContent();
}

// ------------------------------------------------------------ signals & status
seg("s-tf", "tf", (v) => { state.sigTf = v; loadSignals(); });
async function loadSignals() {
  const rows = await api("/api/signals?limit=300" + (state.sigTf ? "&tf=" + state.sigTf : "")).catch(() => []);
  $("signals").innerHTML = rows.map((r) => `<tr><td class="l">${tsKo(r.bar_close)}</td><td class="l">${TF_KO[r.timeframe] || r.timeframe}</td>
    <td class="l">${esc(r.strategy.replace("RANDOM_", "동전 봇 "))}</td><td class="l">${coin(r.symbol)}</td><td class="l">${sideTag(r.side)}</td>
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
    if (Object.keys(d.changed).length) loadBoard();
    d.trades.forEach((t) => toast(`${t.account_id} ${coin(t.symbol)} ${REASON_KO[t.exit_reason] || t.exit_reason} ${pct(t.roe)} → $${fmt(t.equity_after)}`));
    d.alerts.filter(toastWorthy).forEach((a) => toast(`⚠ ${alertKo(a.text)}`));
    if (d.trades.length && state.view === "trade") { if (state.sideTab === "trades") renderSide(); if (state.botTab === "alltrades") renderBottom(); loadTradeChart(); }
    if (state.view === "account" && state.account && d.trades.some((t) => t.account_id === state.account.account.account_id)) openAccount(state.account.account.account_id);
  };
  es.onerror = () => chip("chip-bot", false, "재연결 중");
}

// ------------------------------------------------------------ live: Binance public streams (browser side)
let mws = null, kws = null;
function marketStream() {
  const streams = SYMS.flatMap((s) => [s.toLowerCase() + "@markPrice@1s", s.toLowerCase() + "@ticker"]).join("/");
  try { mws = new WebSocket("wss://fstream.binance.com/stream?streams=" + streams); } catch (e) { chip("chip-feed", false, "시세 끊김"); return; }
  mws.onopen = () => chip("chip-feed", true, "바이낸스 시세");
  mws.onmessage = (ev) => {
    const m = JSON.parse(ev.data).data; if (!m) return;
    if (m.e === "markPriceUpdate") { state.mark[m.s] = +m.p; state.fund[m.s] = {r: +m.r, T: +m.T}; }
    else if (m.e === "24hrTicker") state.tick[m.s] = {c: +m.c, p: +m.P, h: +m.h, l: +m.l, q: +m.q};
  };
  mws.onclose = () => { chip("chip-feed", false, "시세 재연결 중"); setTimeout(marketStream, 5000); };
}
function klineStream() {
  if (kws) { kws.onclose = null; kws.close(); }
  const tf = state.tf, sym = state.sym;
  try { kws = new WebSocket(`wss://fstream.binance.com/ws/${sym.toLowerCase()}@kline_${tf}`); } catch (e) { return; }
  kws.onmessage = (ev) => {
    const k = JSON.parse(ev.data).k; if (!k || !tseries || sym !== state.sym || tf !== state.tf) return;
    const c = {time: Math.floor(k.t / 1000), open: +k.o, high: +k.h, low: +k.l, close: +k.c};
    try { tseries.update(c); state.lastCandle = c; } catch (e) { /* older than the last bar */ }
  };
  kws.onclose = () => setTimeout(() => { if (sym === state.sym && tf === state.tf) klineStream(); }, 5000);
}
setInterval(() => {
  renderWatch(); renderTicker();
  if (state.view === "trade") {
    if (state.sideTab === "pos") renderSide();
    if (state.botTab === "allpos") renderBottom();
  }
  if (state.view === "board") renderBoard();
  if (state.view === "account" && state.account) renderAcctPos(state.account.state && state.account.state.position);
}, 1000);

// ------------------------------------------------------------ start
// the top bar wraps on phones: full-height panes (rooms) subtract its real height
function topHeight() { document.documentElement.style.setProperty("--toph", document.querySelector(".topbar").offsetHeight + "px"); }
window.addEventListener("resize", topHeight);
topHeight();
themeInit();
chip("chip-ai", null, "에이전트 연결 전");
renderWatch();
loadBoard().then(() => { fillAcctFilter(); loadTradeChart(); renderSide(); renderBottom(); stream(); marketStream(); klineStream(); })
  .catch((e) => console.error(e));
