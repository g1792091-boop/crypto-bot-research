// 공통: API, 상태, 포맷, 토스트, 차트 팩토리
export const $ = (s, el = document) => el.querySelector(s);
export const $$ = (s, el = document) => [...el.querySelectorAll(s)];
export const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const saved = (() => { try { return JSON.parse(localStorage.getItem("ft.prefs") || "{}"); } catch { return {}; } })();

export const state = {
  status: null,
  symbol: saved.symbol || "BTCUSDT",
  interval: saved.interval || "1h",
  watch: saved.watch || ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT"],
  studies: saved.studies || ["MAExp@tv-basicstudies", "RSI@tv-basicstudies"],
  chartMode: saved.chartMode || "tv",
  macro: saved.macro || "NASDAQ:NDX",
  showScenario: saved.showScenario ?? true,
  spec: null,
  analysis: null,
  tickers: {},
};

export function savePrefs() {
  const { symbol, interval, watch, studies, chartMode, macro, showScenario } = state;
  try { localStorage.setItem("ft.prefs", JSON.stringify({ symbol, interval, watch, studies, chartMode, macro, showScenario })); } catch { /* 저장 불가 환경 */ }
}

// 간단한 이벤트 버스
const handlers = {};
export const on = (ev, fn) => (handlers[ev] = handlers[ev] || []).push(fn);
export const emit = (ev, data) => (handlers[ev] || []).forEach((fn) => fn(data));

export async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
  return data;
}

export function toast(title, msg = "", kind = "") {
  const box = $("#toasts");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `<div class="tt">${esc(title)}</div>${msg ? `<div class="m">${esc(msg)}</div>` : ""}`;
  box.prepend(el);
  while (box.children.length > 4) box.lastChild.remove();
  setTimeout(() => el.remove(), kind === "err" ? 9000 : 6000);
}

export async function busy(btn, fn) {
  btn.disabled = true;
  try { return await fn(); }
  catch (e) { toast("오류", e.message, "err"); }
  finally { btn.disabled = false; }
}

// 가격 자릿수: 가격 크기에 맞춰 자동
export function px(v) {
  if (v == null || Number.isNaN(+v)) return "–";
  const a = Math.abs(v);
  const d = a >= 1000 ? 1 : a >= 100 ? 2 : a >= 1 ? 3 : a >= 0.01 ? 5 : 7;
  return Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}
export const fmt = (v, d = 2) => (v == null || Number.isNaN(+v) ? "–" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }));
export const pct = (v, d = 2) => (v == null ? "–" : `${v > 0 ? "+" : ""}${Number(v).toFixed(d)}%`);
export const big = (v) => {
  if (v == null) return "–";
  const a = Math.abs(v);
  if (a >= 1e12) return (v / 1e12).toFixed(2) + "T";
  if (a >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (a >= 1e6) return (v / 1e6).toFixed(2) + "M";
  if (a >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return fmt(v, 0);
};
export const cls = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");
export const hhmm = (t) => (t ? new Date(t * 1000).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false }) : "–");
export const mdhm = (t) => (t ? new Date(t * 1000).toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }) : "–");

export const INTERVALS = [
  ["1m", "1분"], ["3m", "3분"], ["5m", "5분"], ["15m", "15분"], ["30m", "30분"], ["1h", "1시간"], ["2h", "2시간"],
  ["4h", "4시간"], ["6h", "6시간"], ["12h", "12시간"], ["1d", "일"], ["3d", "3일"], ["1w", "주"], ["1M", "월"], ["1y", "년"],
];
export const IV_LABEL = Object.fromEntries(INTERVALS);
export const TV_INTERVAL = { "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "2h": "120", "4h": "240",
  "6h": "360", "12h": "720", "1d": "D", "3d": "3D", "1w": "W", "1M": "M", "1y": "12M" };

export function makeChart(el, extra = {}) {
  el.innerHTML = "";
  return LightweightCharts.createChart(el, {
    autoSize: true,
    layout: { background: { type: "solid", color: css("--panel") }, textColor: css("--text-2"), fontSize: 11,
      fontFamily: getComputedStyle(document.body).fontFamily },
    grid: { vertLines: { color: "rgba(255,255,255,.035)" }, horzLines: { color: "rgba(255,255,255,.035)" } },
    rightPriceScale: { borderColor: css("--line") },
    timeScale: { borderColor: css("--line"), timeVisible: true, secondsVisible: false },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    localization: { locale: "ko-KR", priceFormatter: px },
    ...extra,
  });
}

export function tvTheme() {
  return { colorTheme: "dark", isTransparent: false, backgroundColor: css("--panel"), locale: "kr", width: "100%", height: "100%" };
}

export function embedTvWidget(el, script, config) {
  el.innerHTML = `<div class="tradingview-widget-container" style="height:100%"><div class="tradingview-widget-container__widget" style="height:100%"></div></div>`;
  const s = document.createElement("script");
  s.src = `https://s3.tradingview.com/external-embedding/${script}`;
  s.async = true;
  s.text = JSON.stringify(config);
  el.firstChild.appendChild(s);
}

export function tradeRows(trades) {
  if (!trades.length) return `<tr><td class="muted">체결 없음</td></tr>`;
  return `<tr><th>청산 시각</th><th>방향</th><th>진입가</th><th>청산가</th><th>사유</th><th>손익</th><th>수익률</th></tr>` +
    trades.map((t) => `<tr><td>${mdhm(t.exit_time)}</td><td class="${t.side === "long" ? "up" : "down"}">${t.side === "long" ? "롱" : "숏"} ${fmt(t.leverage, 0)}x</td>
      <td>${px(t.entry_price)}</td><td>${px(t.exit_price)}</td><td class="dim">${REASON[t.exit_reason] || esc(t.exit_reason)}</td>
      <td class="${cls(t.pnl)}">${fmt(t.pnl)}</td><td class="${cls(t.pnl_pct_on_margin)}">${pct(t.pnl_pct_on_margin)}</td></tr>`).join("");
}
export const REASON = { stop_loss: "손절", take_profit: "익절", trailing_stop: "추적손절", liquidation: "강제청산",
  reverse_signal: "반대 신호", exit_signal: "청산 신호", end_of_test: "테스트 종료", manual: "수동", manual_close: "수동" };
