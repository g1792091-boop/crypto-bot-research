"use strict";
const SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"];
const TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일봉"};
const REASON_KO = {SL: "손절", LOCK: "익절 잠금", LIQ: "강제청산", TP: "익절", HALT: "정지", MANUAL: "수동", END: "종료"};
const STATUS_KO = {SUBMITTED: "진입 요청", RECORD: "기록만", LATE: "늦음(미진입)", NO_PRICE: "가격 없음", NO_ATR: "ATR 없음"};
const INITIAL = 1000;
const $ = (id) => document.getElementById(id);
const state = {board: null, tf: "", kind: "", sort: "wallet", prices: {}, account: null, sigTf: "", view: "board"};

// ------------------------------------------------------------ helpers
const fmt = (x, d = 2) => x == null || isNaN(x) ? "—" : Number(x).toLocaleString("ko-KR", {minimumFractionDigits: d, maximumFractionDigits: d});
const pct = (x, d = 1) => x == null || isNaN(x) ? "—" : (x > 0 ? "+" : "") + (x * 100).toFixed(d) + "%";
const signCls = (x) => x > 0 ? "gain" : x < 0 ? "loss" : "";
const tsKo = (ms) => ms ? new Date(ms).toLocaleString("ko-KR", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"}) : "—";
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const name = (a) => `${a.strategy.replace("RANDOM_", "동전 봇 ")} · ${TF_KO[a.timeframe] || a.timeframe}`;
const sideKo = (s) => s > 0 ? "롱" : "숏";
async function api(path) {
  const r = await fetch(path, {credentials: "same-origin"});
  if (r.status === 401) { location.href = "/login"; throw new Error("login"); }
  if (!r.ok) throw new Error(path + " " + r.status);
  return r.json();
}
// Engine and runner messages are in English; show them in Korean.
function alertKo(text) {
  const t = String(text);
  let m;
  if ((m = t.match(/^\[([^\]]+)\] drawdown ([\d.]+)% \(level (\d+)%\), equity ([\d.]+)/)))
    return `${m[1]} 낙폭 ${m[2]}% (${m[3]}% 경고선), 잔고 $${m[4]}`;
  if ((m = t.match(/^\[([^\]]+)\] BUST/))) return `${m[1]} 파산 (잔고 $10 미만, 계좌 정지)`;
  if ((m = t.match(/^\[([^\]]+)\] LIQUIDATED (\S+) (\d+)x lost margin ([\d.]+)/)))
    return `${m[1]} 강제청산: ${m[2]} ${m[3]}배, 증거금 $${m[4]} 손실`;
  if ((m = t.match(/^data gap at (\d+): no bar for (.+)/))) return `데이터 누락 ${tsKo(+m[1])}: ${m[2]}`;
  if (/^no new closed bars/.test(t)) return "새 1분봉이 들어오지 않음: " + t;
  if (/^5m history incomplete/.test(t)) return "5분봉 기록 불완전으로 신호 계산 건너뜀";
  if (/^Binance blocked/.test(t)) return "바이낸스가 서버 접속을 막음: " + t;
  return t;
}
// Per-account drawdown notes stay on the status page; toasts are for events that need attention.
const toastWorthy = (a) => a.level === "CRITICAL" || /BUST|LIQUIDATED|blocked|gap|no new closed/.test(a.text);
function toast(text) {
  const t = $("toast"); t.textContent = text; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 5000);
}
function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
function unrealized(pos) {
  const px = state.prices[pos.symbol];
  if (!px) return null;
  const pnl = pos.side * pos.qty * (px - pos.entry);
  return {px, pnl, roe: pnl / pos.margin};
}

// ------------------------------------------------------------ theme
(function initTheme() {
  let t = null;
  try { t = localStorage.getItem("theme"); } catch (e) { /* storage blocked */ }
  if (t) document.documentElement.dataset.theme = t;
  $("theme").onclick = () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) { /* ignore */ }
    if (state.view === "account" && state.account) renderAccount(state.account);
  };
})();
$("logout").onclick = async () => { await fetch("/api/logout", {method: "POST"}); location.href = "/login"; };

// ------------------------------------------------------------ tabs
function show(v) {
  state.view = v;
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.v === v));
  document.querySelectorAll("section.view").forEach((s) => s.classList.toggle("on", s.id === "v-" + v));
  if (v === "signals") loadSignals();
  if (v === "status") loadStatus();
}
document.querySelectorAll("#tabs button").forEach((b) => b.onclick = () => show(b.dataset.v));
$("back").onclick = () => show("board");
function seg(id, key, attr, cb) {
  document.querySelectorAll(`#${id} button`).forEach((b) => b.onclick = () => {
    document.querySelectorAll(`#${id} button`).forEach((x) => x.classList.toggle("on", x === b));
    state[key] = b.dataset[attr]; cb();
  });
}
seg("f-tf", "tf", "tf", renderBoard);
seg("f-kind", "kind", "k", renderBoard);
seg("s-tf", "sigTf", "tf", loadSignals);
$("f-sort").onchange = (e) => { state.sort = e.target.value; renderBoard(); };

// ------------------------------------------------------------ board
async function loadBoard() { state.board = await api("/api/board"); renderBoard(); }
function renderBoard() {
  const b = state.board; if (!b) return;
  const all = b.accounts;
  const strat = all.filter((a) => a.kind === "strategy");
  const open = all.filter((a) => a.position).length;
  const bust = all.filter((a) => a.bust).length;
  const beat = strat.filter((a) => a.beats_random).length;
  const above = strat.filter((a) => (a.wallet ?? INITIAL) > INITIAL).length;
  $("tiles").innerHTML = [
    ["계좌", all.length, `매매법 ${strat.length} · 동전 봇 ${all.length - strat.length}`],
    ["포지션 중", open, "지금 열려 있는 포지션"],
    ["$1,000 넘은 매매법", above, `${strat.length}개 중`],
    ["동전 봇보다 나은 매매법", beat, "같은 봉 동전 봇 3개 최고보다 잔고가 큼"],
    ["파산", bust, "잔고 $10 미만으로 정지"],
  ].map(([k, v, s]) => `<div class="tile"><div class="k">${k}</div><div class="v num">${v}</div><div class="s">${s}</div></div>`).join("");
  let rows = all.filter((a) => (!state.tf || a.timeframe === state.tf) && (!state.kind || a.kind === state.kind));
  const key = {
    wallet: (a) => -(a.wallet ?? INITIAL), trades: (a) => -a.trades, win: (a) => -(a.win_rate ?? -1),
    dd: (a) => a.max_drawdown ?? 0, name: (a) => name(a),
  }[state.sort];
  rows.sort((x, y) => { const p = key(x), q = key(y); return p < q ? -1 : p > q ? 1 : 0; });
  $("board").innerHTML = rows.map((a, i) => {
    const w = a.wallet ?? INITIAL, ret = w / INITIAL - 1;
    let st = '<span class="chip">대기</span>';
    if (a.bust) st = '<span class="chip bust">✕ 파산</span>';
    else if (a.position) {
      const p = a.position, u = unrealized(p);
      st = `<span class="chip pos">● ${p.symbol.replace("USDT", "")} ${sideKo(p.side)} ${p.leverage}배` +
        (u ? ` <span class="${signCls(u.roe)}">${pct(u.roe)}</span>` : "") + "</span>";
    }
    const vs = a.kind === "random" ? '<span class="muted">기준</span>'
      : a.beats_random == null ? "—" : a.beats_random ? '<span class="gain">✓ 나음</span>' : '<span class="loss">✕ 못함</span>';
    return `<tr class="click" data-id="${esc(a.account_id)}">
      <td class="muted" data-k="순위">${i + 1}</td><td class="name">${esc(name(a))}</td>
      <td class="r" data-k="잔고">$${fmt(w)}</td><td class="r ${signCls(ret)}" data-k="수익률">${pct(ret)}</td>
      <td class="r" data-k="거래">${a.trades}</td><td class="r" data-k="승률">${a.win_rate == null ? "—" : pct(a.win_rate, 0).replace("+", "")}</td>
      <td class="r" data-k="최대 낙폭">${a.max_drawdown ? "-" + (a.max_drawdown * 100).toFixed(1) + "%" : "—"}</td>
      <td>${st}</td><td data-k="동전 봇 대비">${vs}</td></tr>`;
  }).join("") || '<tr><td colspan="9" class="empty">계좌가 없습니다</td></tr>';
  document.querySelectorAll("#board tr.click").forEach((tr) => tr.onclick = () => openAccount(tr.dataset.id));
}

// ------------------------------------------------------------ account
let charts = [];
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
  ].map(([k, v, s]) => `<div class="tile"><div class="k">${k}</div><div class="v num">${v}</div><div class="s num">${s}</div></div>`).join("");
  renderPosition(st.position);
  charts.forEach((c) => c.remove()); charts = [];
  const lc = window.LightweightCharts;
  const opts = (el) => ({
    width: el.clientWidth, height: el.clientHeight,
    layout: {background: {color: css("--surface-1")}, textColor: css("--text-secondary")},
    grid: {vertLines: {color: css("--line")}, horzLines: {color: css("--line")}},
    rightPriceScale: {borderColor: css("--line")}, timeScale: {borderColor: css("--line"), timeVisible: true},
    localization: {locale: "ko-KR"},
  });
  if (lc) {
    const el = $("a-eq"); const c = lc.createChart(el, opts(el)); charts.push(c);
    const s = c.addLineSeries({color: css("--series-1"), lineWidth: 2, priceFormat: {type: "price", precision: 2, minMove: 0.01}});
    const pts = d.equity.map((p) => ({time: Math.floor(p.t / 1000), value: p.v}));
    s.setData(pts.length ? pts : [{time: Math.floor(Date.now() / 1000), value: w}]);
    s.createPriceLine({price: INITIAL, color: css("--text-muted"), lineStyle: 2, lineWidth: 1, title: "시작"});
    c.timeScale().fitContent();
  }
  const syms = [...new Set(trades.map((t) => t.symbol).concat(st.position ? [st.position.symbol] : []))];
  const sel = $("a-sym"); const cur = sel.value;
  sel.innerHTML = (syms.length ? syms : SYMS).map((s) => `<option>${s}</option>`).join("");
  if (syms.includes(cur)) sel.value = cur;
  sel.onchange = () => drawCandles(d);
  drawCandles(d);
  $("a-trades").innerHTML = trades.map((t) => `<tr>
    <td>${tsKo(t.exit_time)}</td><td>${t.symbol.replace("USDT", "")}</td><td>${sideKo(t.side)}</td>
    <td class="r">${t.leverage}배</td><td class="r">${fmt(t.entry_price, 4)}</td><td class="r">${fmt(t.exit_price, 4)}</td>
    <td>${REASON_KO[t.exit_reason] || t.exit_reason}${t.lock_roe ? ` (+${Math.round(t.lock_roe * 100)}%)` : ""}</td>
    <td class="r ${signCls(t.roe)}">${pct(t.roe)}</td><td class="r ${signCls(t.pnl)}">${t.pnl > 0 ? "+" : ""}${fmt(t.pnl)}</td>
    <td class="r">$${fmt(t.equity_after)}</td></tr>`).join("") || '<tr><td colspan="10" class="empty">아직 거래가 없습니다</td></tr>';
}
function renderPosition(p) {
  const el = $("a-pos");
  if (!p) { el.innerHTML = '<h3>열린 포지션</h3><p class="muted">없음</p>'; return; }
  const u = unrealized({symbol: p.symbol, side: p.side, qty: p.qty, entry: p.entry_price, margin: p.margin});
  el.innerHTML = `<h3>열린 포지션 · ${p.symbol.replace("USDT", "")} ${sideKo(p.side)} ${p.leverage}배</h3>
    <div class="kv num">
      <div><span>현재가</span>${u ? fmt(u.px, 4) : "—"}</div>
      <div><span>평가 손익 (ROE)</span><b class="${u ? signCls(u.pnl) : ""}">${u ? (u.pnl > 0 ? "+" : "") + fmt(u.pnl) + " (" + pct(u.roe) + ")" : "—"}</b></div>
      <div><span>진입가</span>${fmt(p.entry_price, 4)}</div>
      <div><span>손절선</span>${fmt(p.stop_price, 4)}${p.lock_roe ? ` <span class="gain">+${Math.round(p.lock_roe * 100)}% 잠금</span>` : ""}</div>
      <div><span>첫 손절</span>${fmt(p.stop_initial, 4)}</div>
      <div><span>청산가</span>${fmt(p.liq_price, 4)}</div>
      <div><span>증거금</span>$${fmt(p.margin)}</div>
      <div><span>진입 시각</span>${tsKo(p.entry_time)}</div>
    </div>`;
}
async function drawCandles(d) {
  const lc = window.LightweightCharts; const el = $("a-candles");
  if (!lc) { el.innerHTML = '<p class="empty">차트 부품을 불러오지 못했습니다</p>'; return; }
  const sym = $("a-sym").value, tf = d.account.timeframe;
  let data;
  try { data = await api(`/api/candles?symbol=${sym}&interval=${tf}&limit=400`); }
  catch (e) { el.innerHTML = '<p class="empty">가격 데이터를 불러오지 못했습니다</p>'; return; }
  el.innerHTML = "";
  const c = lc.createChart(el, {
    width: el.clientWidth, height: el.clientHeight,
    layout: {background: {color: css("--surface-1")}, textColor: css("--text-secondary")},
    grid: {vertLines: {color: css("--line")}, horzLines: {color: css("--line")}},
    timeScale: {timeVisible: true, borderColor: css("--line")}, rightPriceScale: {borderColor: css("--line")},
    localization: {locale: "ko-KR"},
  });
  charts.push(c);
  const s = c.addCandlestickSeries({upColor: css("--gain"), downColor: css("--loss"), borderVisible: false,
    wickUpColor: css("--gain"), wickDownColor: css("--loss")});
  s.setData(data);
  const t0 = data.length ? data[0].time : 0;
  const marks = [];
  d.trades.filter((t) => t.symbol === sym && t.entry_time / 1000 >= t0).forEach((t) => {
    marks.push({time: Math.floor(t.entry_time / 1000), position: t.side > 0 ? "belowBar" : "aboveBar",
      color: css("--series-1"), shape: t.side > 0 ? "arrowUp" : "arrowDown", text: `${sideKo(t.side)} ${t.leverage}배`});
    marks.push({time: Math.floor(t.exit_time / 1000), position: t.side > 0 ? "aboveBar" : "belowBar",
      color: t.pnl > 0 ? css("--gain") : css("--loss"), shape: "circle", text: `${REASON_KO[t.exit_reason] || t.exit_reason} ${pct(t.roe, 0)}`});
  });
  marks.sort((a, b) => a.time - b.time);
  const tfSec = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}[tf] || 60;
  marks.forEach((m) => m.time = m.time - (m.time % tfSec));
  s.setMarkers(marks);
  const p = d.state && d.state.position;
  if (p && p.symbol === sym) {
    s.createPriceLine({price: p.entry_price, color: css("--series-1"), lineWidth: 1, title: "진입"});
    s.createPriceLine({price: p.stop_price, color: p.lock_roe ? css("--gain") : css("--loss"), lineWidth: 1, lineStyle: 2, title: p.lock_roe ? "잠금" : "손절"});
    s.createPriceLine({price: p.liq_price, color: css("--warn"), lineWidth: 1, lineStyle: 3, title: "청산가"});
  }
  c.timeScale().fitContent();
}

// ------------------------------------------------------------ signals & status
async function loadSignals() {
  const rows = await api("/api/signals?limit=300" + (state.sigTf ? "&tf=" + state.sigTf : ""));
  $("signals").innerHTML = rows.map((r) => `<tr><td>${tsKo(r.bar_close)}</td><td>${TF_KO[r.timeframe] || r.timeframe}</td>
    <td>${esc(r.strategy.replace("RANDOM_", "동전 봇 "))}</td><td>${r.symbol.replace("USDT", "")}</td><td>${sideKo(r.side)}</td>
    <td class="r">${fmt(r.ref_price, 4)}</td><td class="r">${r.delay_ms == null ? "—" : (r.delay_ms / 1000).toFixed(1) + "초"}</td>
    <td>${STATUS_KO[r.status] || r.status}</td></tr>`).join("") || '<tr><td colspan="8" class="empty">신호가 없습니다</td></tr>';
}
async function loadStatus() {
  const s = await api("/api/status");
  const hb = s.heartbeat, age = hb ? (s.now - hb[0]) / 1000 : null;
  const run = s.run ? s.run[1] : {};
  $("st-tiles").innerHTML = [
    ["봇 생존 신호", age == null ? "없음" : age < 60 ? "정상" : Math.round(age) + "초 전", hb ? tsKo(hb[0]) : ""],
    ["계좌", run.accounts ?? "—", run.restored ? "재시작 후 복구됨" : "새로 시작"],
    ["수수료(편도)", run.taker_fee != null ? (run.taker_fee * 100).toFixed(3) + "%" : "—", "계정 실제 수수료율"],
    ["레버리지 구간", run.brackets ? (run.brackets.includes("EXAMPLE") ? "예시 표" : "거래소 실제 값") : "—", ""],
  ].map(([k, v, x]) => `<div class="tile"><div class="k">${k}</div><div class="v">${esc(v)}</div><div class="s">${esc(x)}</div></div>`).join("");
  $("st-sig").innerHTML = s.signals_24h.map((r) => `<tr><td>${TF_KO[r.timeframe] || r.timeframe}</td><td>${STATUS_KO[r.status] || r.status}</td>
    <td class="r">${r.n}</td><td class="r">${r.avg_delay == null ? "—" : (r.avg_delay / 1000).toFixed(1) + "초"}</td></tr>`).join("")
    || '<tr><td colspan="4" class="empty">최근 신호 없음</td></tr>';
  $("st-alerts").innerHTML = s.alerts.map((a) => `<tr><td>${tsKo(a.ts)}</td><td class="${a.level === "CRITICAL" ? "loss" : "warn"}">${a.level === "CRITICAL" ? "긴급" : "주의"}</td>
    <td style="white-space:normal">${esc(alertKo(a.text))}</td></tr>`).join("") || '<tr><td colspan="3" class="empty">경고 없음</td></tr>';
}

// ------------------------------------------------------------ live: server events + Binance prices
function heartbeat(hb) {
  const age = hb ? (Date.now() - hb[0]) / 1000 : null;
  $("hbdot").className = "dot " + (age != null && age < 90 ? "ok" : "bad");
  $("hbtext").textContent = age == null ? "봇 신호 없음" : age < 90 ? "실시간" : `봇 응답 없음 ${Math.round(age)}초`;
}
function stream() {
  const es = new EventSource("/api/stream");
  es.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    heartbeat(d.heartbeat);
    if (state.board && Object.keys(d.changed).length) {
      const by = Object.fromEntries(state.board.accounts.map((a) => [a.account_id, a]));
      for (const [id, [wallet, trades, bust, position]] of Object.entries(d.changed)) {
        const a = by[id]; if (!a) continue;
        Object.assign(a, {wallet, trades, bust, position});
      }
      loadBoard();  // refresh derived columns (win rate, vs coin-flip)
    }
    d.trades.forEach((t) => toast(`${t.account_id} ${t.symbol.replace("USDT", "")} ${REASON_KO[t.exit_reason] || t.exit_reason} ${pct(t.roe)} → $${fmt(t.equity_after)}`));
    d.alerts.filter(toastWorthy).forEach((a) => toast(`⚠ ${alertKo(a.text)}`));
    if (state.view === "account" && state.account && d.trades.some((t) => t.account_id === state.account.account.account_id)) {
      openAccount(state.account.account.account_id);
    }
  };
  es.onerror = () => { $("hbdot").className = "dot bad"; $("hbtext").textContent = "재연결 중"; };
}
function prices() {
  const url = "wss://fstream.binance.com/stream?streams=" + SYMS.map((s) => s.toLowerCase() + "@markPrice@1s").join("/");
  let ws;
  try { ws = new WebSocket(url); } catch (e) { return; }
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data).data; if (!m) return;
    state.prices[m.s] = parseFloat(m.p);
    $("ticker").innerHTML = SYMS.map((s) => `<span><b>${s.replace("USDT", "")}</b>${state.prices[s] ? fmt(state.prices[s], state.prices[s] < 10 ? 4 : 2) : "—"}</span>`).join("");
  };
  ws.onclose = () => setTimeout(prices, 5000);
  setInterval(() => {
    if (state.view === "board") renderBoard();
    if (state.view === "account" && state.account) renderPosition(state.account.state && state.account.state.position);
  }, 1000);
}

loadBoard().then(() => { stream(); prices(); }).catch((e) => console.error(e));
