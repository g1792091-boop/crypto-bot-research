"use strict";
// Trade view extras: the '거래소 차트' (TradingView Advanced Chart embed, Binance perpetual), Coinglass links per coin and
// the bar-close countdown strip for every timeframe. Browser side only: the dashboard server never fetches TradingView
// or Coinglass (the page loads https://s3.tradingview.com/tv.js itself, only when that chart is opened; Coinglass
// opens in a new tab). The countdown uses the server's clock (/api/time) so a phone with a wrong clock still counts
// right. Uses app.js helpers ($, api, esc, coin, state, TF_KO, TRADE_TFS, closeIn, barEnd, nowMs, loadTradeChart).
(function () {
  const ALL_TFS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"];
  const TV_SRC = "https://s3.tradingview.com/tv.js";
  const TV_IV = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "2h": "120", "4h": "240",
    "6h": "360", "8h": "480", "12h": "720", "1d": "D", "3d": "3D", "1w": "W", "1M": "M"};
  const SHORT = {"1m": "1분", "3m": "3분", "5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "2h": "2시간", "4h": "4시간",
    "6h": "6시간", "8h": "8시간", "12h": "12시간", "1d": "일", "3d": "3일", "1w": "주", "1M": "월"};
  const SOON_MS = 60000;              // a bar closing within this long is highlighted
  const ch = {mode: "bot", tvKey: "", tvLoading: null, cgSym: ""};
  try { if (localStorage.getItem("pb-chart-mode") === "tv") ch.mode = "tv"; } catch (e) { /* storage blocked */ }

  // ------------------------------------------------------------ server clock
  async function syncClock() {
    const t0 = Date.now();
    try {
      const d = await api("/api/time");
      const t1 = Date.now();
      if (d && typeof d.now === "number" && t1 - t0 < 5000) state.clockSkew = d.now - (t0 + t1) / 2;
    } catch (e) { /* the phone's own clock until the next try */ }
  }

  // ------------------------------------------------------------ countdown strip (every timeframe)
  function buildStrip() {
    const el = $("cd-strip");
    if (!el) return;
    el.innerHTML = `<span class="cdk" title="●: 봇 계좌가 매매하는 봉. 1분 안에 닫히는 봉은 강조">봉 마감</span>` + ALL_TFS.map((tf) =>
      `<button class="cd${TRADE_TFS.includes(tf) ? " bot" : ""}" data-tf="${tf}" title="${esc(TF_KO[tf] || tf)} 봉이 닫힐 때까지${TRADE_TFS.includes(tf) ? " · 봇이 매매하는 봉" : ""}">` +
      `<span>${TRADE_TFS.includes(tf) ? "●" : ""}${SHORT[tf]}</span><b>—</b></button>`).join("");
    el.querySelectorAll("button.cd").forEach((b) => b.onclick = () => {
      const t = document.querySelector(`#tf-seg button[data-tf="${b.dataset.tf}"]`);
      if (t) t.click();
    });
  }
  function tickStrip() {
    const el = $("cd-strip");
    if (!el || state.view !== "trade") return;
    const now = nowMs();
    el.querySelectorAll("button.cd").forEach((b) => {
      const tf = b.dataset.tf, end = barEnd(tf, now);
      b.lastChild.textContent = closeIn(tf);
      b.classList.toggle("soon", end != null && end - now <= SOON_MS);
      b.classList.toggle("cur", tf === state.tf);
    });
  }

  // ------------------------------------------------------------ Coinglass links (links only)
  function renderLinks() {
    const el = $("cg-links");
    if (!el || ch.cgSym === state.sym) return;
    ch.cgSym = state.sym;
    const c = encodeURIComponent(coin(state.sym));
    const links = [["코인글래스 차트", `https://www.coinglass.com/tv/Binance_${c}USDT`],
      ["청산 지도", "https://www.coinglass.com/pro/futures/LiquidationMap"],
      ["청산 히트맵", "https://www.coinglass.com/pro/futures/LiquidationHeatMap"],
      [`${coin(state.sym)} 파생 정보`, `https://www.coinglass.com/currencies/${c}`]];
    el.innerHTML = `<span class="cdk">코인글래스 (새 탭)</span>` + links.map(([t, u]) =>
      `<a class="cgl" href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(t)}</a>`).join("");
  }

  // ------------------------------------------------------------ 봇 차트 / 거래소 차트
  const tvTheme = () => document.documentElement.dataset.theme === "light" ? "light" : "dark";
  function loadTv() {
    if (window.TradingView) return Promise.resolve();
    if (ch.tvLoading) return ch.tvLoading;
    ch.tvLoading = new Promise((ok, bad) => {
      const s = document.createElement("script");
      s.src = TV_SRC; s.async = true;
      s.onload = () => ok();
      s.onerror = () => { ch.tvLoading = null; s.remove(); bad(new Error("tv.js")); };
      document.head.appendChild(s);
    });
    return ch.tvLoading;
  }
  async function renderTv(force) {
    if (ch.mode !== "tv") return;
    const key = `${state.sym}|${state.tf}|${tvTheme()}`;
    if (!force && key === ch.tvKey) return;
    ch.tvKey = key;
    const el = $("tvchart");
    if (!window.TradingView) el.innerHTML = '<p class="empty">트레이딩뷰 차트를 불러오는 중…</p>';
    try { await loadTv(); } catch (e) {
      ch.tvKey = "";
      el.innerHTML = '<p class="empty">트레이딩뷰 차트를 불러오지 못했습니다 (이 네트워크가 tradingview.com을 막았을 수 있음). 봇 차트는 그대로 볼 수 있습니다.</p>';
      return;
    }
    if (key !== ch.tvKey || ch.mode !== "tv" || !window.TradingView) return;
    el.innerHTML = '<div id="tvchart-in" class="tvin"></div>';
    try {
      // the official Advanced Chart embed: Binance USDT perpetual (.P), Korean, the dashboard's theme, Korea time
      new window.TradingView.widget({
        container_id: "tvchart-in", autosize: true, symbol: `BINANCE:${coin(state.sym)}USDT.P`,
        interval: TV_IV[state.tf] || "15", timezone: "Asia/Seoul", theme: tvTheme(), style: "1", locale: "kr",
        enable_publishing: false, allow_symbol_change: true, hide_side_toolbar: false, withdateranges: true,
        save_image: false, details: false, hotlist: false, calendar: false,
      });
    } catch (e) {
      el.innerHTML = '<p class="empty">트레이딩뷰 차트를 그리지 못했습니다.</p>';
    }
  }
  function setMode(m) {
    ch.mode = m === "tv" ? "tv" : "bot";
    try { localStorage.setItem("pb-chart-mode", ch.mode); } catch (e) { /* private window */ }
    document.querySelectorAll("#chart-mode button").forEach((b) => b.classList.toggle("on", b.dataset.m === ch.mode));
    const p = document.querySelector(".chartp");
    if (p) p.classList.toggle("tvmode", ch.mode === "tv");
    $("bot-chartwrap").hidden = ch.mode !== "bot";
    $("tv-chartwrap").hidden = ch.mode !== "tv";
    if (ch.mode === "tv") renderTv();
  }
  document.querySelectorAll("#chart-mode button").forEach((b) => b.onclick = () => setMode(b.dataset.m));

  // ------------------------------------------------------------ start
  buildStrip();
  setMode(ch.mode);
  syncClock();
  setInterval(syncClock, 600000);
  setInterval(() => {
    if (state.view !== "trade") return;
    tickStrip();
    renderLinks();
    if (ch.mode === "tv") renderTv();        // follows the coin, the timeframe and the theme
  }, 1000);
  tickStrip();
  renderLinks();
})();
