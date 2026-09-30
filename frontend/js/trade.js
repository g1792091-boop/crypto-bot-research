// 트레이드 화면
import { addPriceAlert, getPriceAlerts, removePriceAlert } from "./alerts.js";
import {
  $, $$, INTERVALS, IV_LABEL, TV_INTERVAL, api, big, busy, cls, css, emit, esc, fmt, hhmm, makeChart, mdhm, on, pct,
  px, savePrefs, state, toast, tradeRows,
} from "./core.js";

const MACRO = [
  ["NASDAQ:NDX", "나스닥100"], ["CAPITALCOM:US100", "나스닥 CFD"], ["SP:SPX", "S&P500"], ["TVC:DXY", "달러인덱스"],
  ["TVC:US10Y", "미 10년물"], ["TVC:GOLD", "금"], ["CRYPTOCAP:BTC.D", "BTC.D"], ["CRYPTOCAP:USDT.D", "USDT.D"],
];

// ================================================================ 시세 · 관심종목
async function pollTickers() {
  const syms = [...new Set([...state.watch, state.symbol])];
  try {
    const d = await api(`/api/tickers?symbols=${syms.join(",")}`);
    d.items.forEach((t) => (state.tickers[t.symbol] = t));
    state.tickerSource = d.source;
    emit("tickers", state.tickers);
    renderWatchlist();
    renderTickerBar();
  } catch { /* 다음 주기 */ }
}

function renderWatchlist() {
  $("#watchlist").innerHTML = `<tr><th>종목</th><th>가격</th><th>24h</th></tr>` + state.watch.map((s) => {
    const t = state.tickers[s];
    return `<tr class="click ${s === state.symbol ? "sel" : ""}" data-sym="${s}" title="더블클릭하면 목록에서 제거">
      <td>${s.replace(/USDT$/, "")}</td><td>${t ? px(t.price) : "–"}</td><td class="${cls(t?.change_pct)}">${t ? pct(t.change_pct) : "–"}</td></tr>`;
  }).join("");
}

function renderTickerBar() {
  const t = state.tickers[state.symbol];
  $("#symbtn").innerHTML = `${state.symbol}<small>무기한</small>`;
  if (!t) return;
  const last = $("#t-last");
  const prev = +last.dataset.v || t.price;
  last.dataset.v = t.price;
  last.textContent = px(t.price);
  last.className = `lastpx ${t.price > prev ? "up" : t.price < prev ? "down" : cls(t.change_pct)}`;
  $("#t-chg").innerHTML = `<span class="${cls(t.change_pct)}">${pct(t.change_pct)}</span>`;
  $("#t-high").textContent = px(t.high);
  $("#t-low").textContent = px(t.low);
  $("#t-vol").textContent = big(t.quote_volume);
  document.title = `${px(t.price)} ${state.symbol.replace("USDT", "")} · 선물 터미널`;
}

let premium = null;
async function pollDerivatives() {
  try {
    const d = await api(`/api/derivatives?symbol=${state.symbol}&interval=1h&limit=48`);
    premium = d.premium;
    const oi = d.open_interest.at(-1)?.value;
    const oi24 = d.open_interest.at(-25)?.value;
    $("#t-oi").innerHTML = oi ? `${big(oi)} <span class="${cls(oi - oi24)}">${oi24 ? pct((oi / oi24 - 1) * 100, 1) : ""}</span>` : "–";
    const ls = d.long_short.at(-1)?.value;
    $("#t-ls").innerHTML = ls ? `<span class="${ls >= 1 ? "up" : "down"}">${ls.toFixed(2)}</span>` : "–";
  } catch { premium = null; }
  tickFunding();
}
function tickFunding() {
  if (!premium) { $("#t-fund").textContent = "–"; return; }
  const s = Math.max(0, premium.next_funding_time - Math.floor(Date.now() / 1000));
  const hms = [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60].map((x) => String(x).padStart(2, "0")).join(":");
  $("#t-fund").innerHTML = `<span class="${cls(premium.funding_rate_pct)}">${premium.funding_rate_pct.toFixed(4)}%</span> <span class="muted">${hms}</span>`;
}

function setSymbol(sym) {
  sym = sym.toUpperCase();
  if (!sym.endsWith("USDT")) sym += "USDT";
  state.symbol = sym;
  if (!state.watch.includes(sym)) state.watch.push(sym);
  savePrefs();
  $("#t-last").dataset.v = "";
  renderWatchlist();
  pollTickers(); pollDerivatives();
  renderChart(); loadAnalysis();
  emit("symbol", sym);
}

// ================================================================ 차트
let lw = null, lwCandles = null, lwVolume = null, heat = null, heatNorm = 1, scLines = [];

function renderTimeframes() {
  $("#tfs").innerHTML = INTERVALS.map(([k, l]) => `<button data-iv="${k}" class="${k === state.interval ? "on" : ""}">${l}</button>`).join("");
}

function renderChart() {
  const mode = state.chartMode;
  $$("#chart-mode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
  $("#macro-syms").hidden = mode !== "macro";
  $("#studies-btn").hidden = mode !== "tv";
  $("#toggle-sc").hidden = mode !== "liq";
  $("#tv-main").hidden = mode === "liq";
  $("#lw-main").hidden = $("#heat").hidden = $("#legend").hidden = mode !== "liq";
  if (mode === "liq") return renderLiqChart();
  if (lw) { lw.remove(); lw = lwCandles = lwVolume = null; scLines = []; heat = null; drawHeat(); }
  renderTv(mode === "macro" ? state.macro : `BINANCE:${state.symbol}.P`, mode === "tv" ? state.studies : []);
}

function renderTv(symbol, studies) {
  const el = $("#tv-main");
  if (typeof TradingView === "undefined") {
    el.innerHTML = `<div class="empty">트레이딩뷰 스크립트를 불러오지 못했습니다. 인터넷 연결이나 광고 차단 확장 프로그램을 확인하세요.</div>`;
    return;
  }
  el.innerHTML = "";
  new TradingView.widget({
    container_id: "tv-main", autosize: true, symbol, interval: TV_INTERVAL[state.interval] || "60",
    timezone: "Asia/Seoul", theme: "dark", style: "1", locale: "kr",
    backgroundColor: css("--panel"), gridColor: "rgba(255,255,255,0.04)",
    allow_symbol_change: true, hide_side_toolbar: false, withdateranges: true, details: false, studies,
  });
}

async function renderLiqChart() {
  const wrap = $("#chartwrap");
  if (!lw) {
    lw = makeChart($("#lw-main"), { layout: { background: { type: "solid", color: "transparent" }, textColor: css("--text-2"), fontSize: 11 } });
    lwCandles = lw.addCandlestickSeries({ upColor: css("--up"), downColor: css("--down"), borderVisible: false,
      wickUpColor: css("--up"), wickDownColor: css("--down") });
    lwVolume = lw.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    lw.priceScale("vol").applyOptions({ scaleMargins: { top: 0.86, bottom: 0 } });
    lw.timeScale().subscribeVisibleLogicalRangeChange(drawHeat);
    lw.subscribeCrosshairMove(onCross);
    if (!wrap.dataset.heatHooks) {
      wrap.dataset.heatHooks = "1";
      new ResizeObserver(() => requestAnimationFrame(drawHeat)).observe(wrap);
      wrap.addEventListener("wheel", () => requestAnimationFrame(drawHeat), { passive: true });
      wrap.addEventListener("pointermove", (e) => e.buttons && requestAnimationFrame(drawHeat));
    }
  }
  $("#legend").innerHTML = `<b>${state.symbol}</b> · ${IV_LABEL[state.interval]} · 청산맵 불러오는 중…`;
  try {
    heat = await api(`/api/liq-heatmap?symbol=${state.symbol}&interval=${state.interval}&limit=500`);
  } catch (e) {
    $("#legend").textContent = "청산맵 오류: " + e.message;
    return;
  }
  const vals = heat.columns.flatMap(([, col]) => col.map(([, v]) => v)).sort((a, b) => a - b);
  heatNorm = vals[Math.floor(vals.length * 0.995)] || 1;
  lwCandles.setData(heat.candles);
  lwVolume.setData(heat.candles.map((b) => ({ time: b.time, value: b.volume || 0,
    color: b.close >= b.open ? "rgba(34,176,125,.35)" : "rgba(229,72,77,.35)" })));
  lw.timeScale().fitContent();
  legendBase();
  drawScenarioLines();
  requestAnimationFrame(drawHeat);
}

const MODEL = { coinglass: "CoinGlass 청산맵", estimate_oi: "추정 청산맵 (미결제약정 기반)", estimate_volume: "추정 청산맵 (거래대금 기반 · 상대 강도)" };
function legendBase(extra = "") {
  if (!heat) return;
  $("#legend").innerHTML = `<b>${state.symbol}</b> · ${IV_LABEL[state.interval]} · ${MODEL[heat.model] || heat.model}
    <span class="scale"></span><span class="muted">적음 → 많음</span>${heat.data_source === "synthetic" ? ' · <span class="accent">가상 데이터</span>' : ""}
    ${extra ? `<br>${extra}` : ""}`;
}

function onCross(p) {
  if (!heat || !p.point || p.time == null) return legendBase();
  const col = heat.columns.find(([t]) => t === p.time);
  const price = lwCandles.coordinateToPrice(p.point.y);
  if (!col || price == null) return legendBase();
  const bi = Math.floor((price - heat.price_min) / heat.price_step);
  const cell = col[1].find(([i]) => i === bi);
  const v = cell ? cell[1] : 0;
  legendBase(`${px(price)} 부근 예상 청산 물량 <b>${heat.unit === "usd" ? "$" + big(v) : fmt(v / heatNorm * 100, 0) + " (상대)"}</b>`);
}

function drawHeat() {
  const cv = $("#heat"), wrap = $("#chartwrap");
  const w = wrap.clientWidth, h = wrap.clientHeight, dpr = window.devicePixelRatio || 1;
  if (cv.width !== w * dpr || cv.height !== h * dpr) { cv.width = w * dpr; cv.height = h * dpr; }
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (!lw || !heat || state.chartMode !== "liq") return;
  const ts = lw.timeScale();
  const plotW = w - lw.priceScale("right").width();
  const range = ts.getVisibleLogicalRange();
  if (!range) return;
  const n = heat.columns.length;
  const x0 = ts.logicalToCoordinate(0), x1 = ts.logicalToCoordinate(1);
  const bw = Math.max(1, (x1 ?? 0) - (x0 ?? 0));
  const rgb = css("--heat");
  ctx.save();
  ctx.beginPath(); ctx.rect(0, 0, plotW, h); ctx.clip();
  for (let i = Math.max(0, Math.floor(range.from) - 1); i <= Math.min(n - 1, Math.ceil(range.to) + 1); i++) {
    const x = ts.logicalToCoordinate(i);
    if (x == null) continue;
    for (const [bi, v] of heat.columns[i][1]) {
      const a = Math.min(1, (v / heatNorm) ** 1.6);   // 큰 물량만 밝게 → 배경은 어둡게 유지
      if (a < 0.1) continue;
      const lo = heat.price_min + bi * heat.price_step;
      const yTop = lwCandles.priceToCoordinate(lo + heat.price_step), yBot = lwCandles.priceToCoordinate(lo);
      if (yTop == null || yBot == null) continue;
      ctx.fillStyle = `rgba(${rgb}, ${(0.9 * a).toFixed(3)})`;
      ctx.fillRect(x - bw / 2, yTop, bw + 0.5, Math.max(1, yBot - yTop));
    }
  }
  ctx.restore();
}

function drawScenarioLines(sc) {
  if (!lwCandles) return;
  scLines.forEach((l) => lwCandles.removePriceLine(l));
  scLines = [];
  sc = sc || state.analysis?.scenarios?.[0];
  if (!state.showScenario || !sc || state.analysis?.symbol !== state.symbol) return;
  const add = (price, title, color, style = 2) => price && scLines.push(lwCandles.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title }));
  add(sc.entry, `${sc.title} 진입`, css("--accent"), 0);
  add(sc.stop, "손절", css("--down"));
  sc.targets.forEach((t, i) => add(t, `목표${i + 1}`, css("--up")));
  if (sc.alt) {
    add(sc.alt.entry, "박스 상단 숏", css("--accent"), 0);
    add(sc.alt.stop, "숏 손절", css("--down"));
  }
}

function toggleFullscreen() {
  const el = $("#chartp");
  if (document.fullscreenElement) document.exitFullscreen();
  else el.requestFullscreen?.().catch(() => toast("전체 화면을 지원하지 않는 브라우저입니다"));
}

function studiesMenu(e) {
  const m = $("#studies-menu");
  if (!m.hidden) { m.hidden = true; return; }
  const reg = state.status?.indicators || {};
  const list = Object.values(reg).filter((v) => v.tv).map((v) => [v.tv, v.desc]);
  list.push(["Volume@tv-basicstudies", "거래량"]);
  m.innerHTML = list.map(([id, l]) => `<label><input type="checkbox" data-study="${id}" ${state.studies.includes(id) ? "checked" : ""} style="height:auto"> ${esc(l)}</label>`).join("");
  const r = e.currentTarget.getBoundingClientRect();
  m.style.left = `${r.left}px`; m.style.top = `${r.bottom + 4}px`;
  m.hidden = false;
  e.stopPropagation();
}

// ================================================================ 시장 판단 · 시나리오
let analysisTimer;
export async function loadAnalysis(withAi = false) {
  clearTimeout(analysisTimer);
  const sym = state.symbol, iv = state.interval;
  try {
    const a = await api(`/api/analysis?symbol=${sym}&interval=${iv}${withAi ? "&ai=true" : ""}`);
    if (sym !== state.symbol || iv !== state.interval) return;
    if (!withAi && state.analysis?.ai_comment && state.analysis.bar_time === a.bar_time && state.analysis.symbol === sym) a.ai_comment = state.analysis.ai_comment;
    state.analysis = a;
    renderRegime(a); renderScenarios(a); drawScenarioLines();
    emit("analysis", a);
  } catch (e) {
    $("#regime").innerHTML = `<span class="muted">분석 실패: ${esc(e.message)}</span>`;
  }
  analysisTimer = setTimeout(() => loadAnalysis(), 60_000);
}

const ST_CLS = { long: "up", short: "down", range: "accent" };
function renderRegime(a) {
  const r = a.regime;
  $("#regime").innerHTML = `
    <div class="head"><span class="state ${r.state}">${r.label}</span>
      <span class="dim">점수 <b class="${cls(r.score)}">${r.score > 0 ? "+" : ""}${r.score}</b> · 신뢰도 ${r.confidence}</span>
      <span class="grow"></span><span class="muted">${IV_LABEL[a.interval]} · ${hhmm(a.time)}</span></div>
    <div class="gauge"><i style="left:calc(${(r.score + 100) / 2}% - 1px)"></i></div>
    <div class="row muted" style="justify-content:space-between;font-size:10.5px"><span>숏 우위</span><span>횡보</span><span>롱 우위</span></div>
    <div class="mtf">${a.mtf.map((m) => `<div><span class="k">${IV_LABEL[m.interval]}</span><span class="${ST_CLS[m.state]}">${m.label}</span></div>`).join("")}</div>
    <ul class="reasons">${r.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    ${a.data_source === "synthetic" ? '<div class="accent" style="margin-top:6px">가상 데이터로 분석 중 (거래소 연결 안 됨)</div>' : ""}`;
}

function renderScenarios(a) {
  const color = { long: css("--up"), short: css("--down"), range: css("--accent") };
  const scs = a.scenarios.map((s, i) => `
    <div class="sc">
      <div class="h"><span class="p">${s.probability}%</span><span class="n">${esc(s.title)}</span>
        <span class="muted">RR ${s.rr ?? "–"}</span><button class="flat sm" data-sc="${i}">차트에</button></div>
      <div class="bar"><i style="width:${s.probability}%;background:${color[s.bias]}"></i></div>
      <div class="trig">${esc(s.trigger)}</div>
      <div class="kv"><span class="k">진입</span><span>${px(s.entry)}</span>
        <span class="k">손절</span><span class="down">${px(s.stop)}</span>
        <span class="k">목표</span><span class="up">${s.targets.map(px).join(" → ")}</span>
        ${s.alt ? `<span class="k">상단 숏</span><span>${px(s.alt.entry)} / 손절 ${px(s.alt.stop)}</span>` : ""}
        <span class="k">무효</span><span class="dim">${esc(s.invalidation)}</span></div>
    </div>`).join("");
  const lv = (xs, c) => xs.map((x) => `<div class="lv"><span class="dim">${esc(x.kind)}</span><span class="px ${c}">${px(x.price)}</span></div>`).join("");
  const liq = a.liquidation;
  const zone = (z) => `<div class="lv"><span class="dim">${px(z.low)} ~ ${px(z.high)}</span><span class="px">${liq.unit === "usd" ? "$" + big(z.value) : "상대 " + big(z.value)}</span></div>`;
  $("#side-sc").innerHTML = `
    ${a.ai_comment ? `<div class="ai">${esc(a.ai_comment)}</div>` : ""}
    ${state.status?.llm ? `<div style="padding:8px 12px;border-bottom:1px solid var(--line)"><button class="sm" id="ai-comment">${a.ai_comment ? "AI 코멘트 새로고침" : "AI 코멘트 받기"}</button></div>` : ""}
    ${scs}
    <div class="sub">저항</div>${lv(a.resistance, "down")}
    <div class="sub">지지</div>${lv(a.support, "up")}
    ${liq ? `<div class="sub">위쪽 청산 구간 (숏 청산)</div>${liq.clusters_above.slice(0, 3).map(zone).join("")}
      <div class="sub">아래쪽 청산 구간 (롱 청산)</div>${liq.clusters_below.slice(0, 3).map(zone).join("")}` : ""}
    <div class="help" style="padding:10px 12px">자동 계산된 참고용 시나리오입니다. 투자 판단의 책임은 본인에게 있습니다.</div>`;
}

// ================================================================ 주문 · 계좌
let side = "long";
function renderOrderPreview() {
  const m = +$("#o-margin").value || 0, lev = +$("#o-lev").value;
  $("#o-lev-v").textContent = `${lev}x`;
  const p = state.tickers[state.symbol]?.price;
  const liq = p ? p * (1 - (side === "long" ? 1 : -1) * (1 / lev - 0.005)) : null;
  $("#o-preview").innerHTML = `포지션 규모 <b>${fmt(m * lev, 0)} USDT</b> · 예상 강제청산가 <b class="down">${px(liq)}</b>`;
  const b = $("#o-submit");
  b.className = side === "long" ? "buy" : "sell";
  b.textContent = `${side === "long" ? "롱" : "숏"} 진입 (모의)`;
}

let account = null;
async function loadAccount() {
  try { account = await api("/api/paper/account"); } catch { return; }
  $("#acct").innerHTML = [["평가 자산", fmt(account.equity)], ["가용 증거금", fmt(account.free_margin)],
    ["지갑 잔고", fmt(account.cash)], ["미실현 손익", `<span class="${cls(account.equity - account.cash)}">${fmt(account.equity - account.cash)}</span>`]]
    .map(([k, v]) => `<div><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
  if (bottomTab === "pos" || bottomTab === "fills") renderBottom();
}

function renderPriceAlerts() {
  $("#pa-list").innerHTML = getPriceAlerts().map((a, i) => `<div class="lv" style="padding:3px 0"><span>${a.symbol.replace("USDT", "")} ${a.dir === "up" ? "≥" : "≤"} <span class="px">${px(a.price)}</span></span>
    <button class="x" data-pa="${i}">✕</button></div>`).join("") || `<div class="muted">등록된 알림 없음</div>`;
}

// ================================================================ 하단 탭
let bottomTab = "pos", bots = [];
function renderBottom() {
  const el = $("#bottom-body");
  if (bottomTab === "pos") {
    const ps = account?.positions || [];
    el.innerHTML = ps.length ? `<table><tr><th>종목</th><th>방향</th><th>규모(USDT)</th><th>진입가</th><th>현재가</th><th>강제청산가</th><th>손절/익절</th><th>미실현 손익</th><th></th></tr>
      ${ps.map((p) => `<tr><td>${p.symbol}</td><td class="${p.side === "long" ? "up" : "down"}">${p.side === "long" ? "롱" : "숏"} ${p.leverage}x</td>
        <td>${fmt(p.qty * p.entry_price, 0)}</td><td>${px(p.entry_price)}</td><td>${px(p.mark_price)}</td><td class="down">${px(p.liq_price)}</td>
        <td class="dim">${p.stop ? px(p.stop) : "–"} / ${p.take ? px(p.take) : "–"}</td>
        <td class="${cls(p.unrealized_pnl)}">${fmt(p.unrealized_pnl)} (${pct(p.roe_pct)})</td>
        <td><button class="sm" data-close="${p.symbol}">시장가 청산</button></td></tr>`).join("")}</table>`
      : `<div class="empty">열린 포지션이 없습니다. 오른쪽 '주문' 탭에서 모의 주문을 넣을 수 있습니다.</div>`;
  } else if (bottomTab === "fills") {
    el.innerHTML = `<table>${tradeRows((account?.trades || []).slice().reverse())}</table>`;
  } else if (bottomTab === "bots") {
    el.innerHTML = bots.length ? `<table><tr><th>봇</th><th>종목</th><th>상태</th><th>평가 자산</th><th>수익률</th><th>포지션</th><th>거래</th></tr>
      ${bots.map((b) => { const a = b.account, p = a.position, r = (a.equity / b.initial_equity - 1) * 100;
        return `<tr><td>${esc(b.name)}</td><td>${b.symbol} ${IV_LABEL[b.interval] || b.interval}</td><td class="${b.running ? "up" : "muted"}">${b.running ? "실행" : "정지"}</td>
        <td>${fmt(a.equity)}</td><td class="${cls(r)}">${pct(r)}</td>
        <td>${p ? `<span class="${p.side === "long" ? "up" : "down"}">${p.side === "long" ? "롱" : "숏"}</span> ${px(p.entry_price)}` : "–"}</td><td>${a.trades.length}</td></tr>`; }).join("")}</table>`
      : `<div class="empty">실행 중인 페이퍼 봇이 없습니다. '전략 · 백테스트'에서 만들 수 있습니다.</div>`;
  } else if (bottomTab === "news") {
    el.innerHTML = newsRows(state.news || [], 40);
  } else if (bottomTab === "alerts") {
    el.innerHTML = (alertLog.length ? alertLog.map((a) => `<div class="news-row"><span class="tm">${hhmm(a.t)}</span><span class="src">${esc(a.cat)}</span>
      <span class="ttl">${esc(a.title)}${a.msg ? ` <span class="muted">${esc(a.msg)}</span>` : ""}</span></div>`).join("") : `<div class="empty">알림 기록이 없습니다.</div>`);
  }
}

export function newsRows(items, limit = 60, brief = null) {
  if (!items.length) return `<div class="empty">뉴스를 불러오지 못했습니다. 인터넷 연결을 확인하세요.</div>`;
  const S = { bullish: ["호재", "bull"], bearish: ["악재", "bear"], neutral: ["중립", ""] };
  return items.slice(0, limit).map((n) => {
    const b = brief?.[n.id];
    return `<a class="news-row ${n.important ? "imp" : ""}" href="${esc(n.url)}" target="_blank" rel="noopener">
      <span class="tm">${n.time ? hhmm(n.time) : "–"}</span><span class="src">${esc(n.source)}</span>
      <span class="ttl">${b ? `<span class="tag ${S[b.sentiment][1]}">${S[b.sentiment][0]}${"!".repeat(Math.max(0, b.impact - 1))}</span>` : ""}${(n.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}${esc(b?.ko_title || n.title)}</span></a>`;
  }).join("");
}

let alertLog = [];
on("alertlog", (l) => { alertLog = l; if (bottomTab === "alerts") renderBottom(); });
on("news", () => { if (bottomTab === "news") renderBottom(); });
on("pricealerts", renderPriceAlerts);

async function loadBots() {
  try { bots = await api("/api/paper/bots"); } catch { return; }
  emit("bots", bots);
  if (bottomTab === "bots") renderBottom();
}

// ================================================================ 초기화
export function initTrade() {
  renderTimeframes();
  $("#macro-syms").innerHTML = MACRO.map(([s, l]) => `<button data-macro="${s}" class="${s === state.macro ? "on" : ""}">${l}</button>`).join("");
  $("#toggle-sc").classList.toggle("on", state.showScenario);
  renderWatchlist(); renderChart(); renderOrderPreview(); renderPriceAlerts();

  $("#chart-mode").onclick = (e) => { const m = e.target.dataset.mode; if (m) { state.chartMode = m; savePrefs(); renderChart(); } };
  $("#tfs").onclick = (e) => {
    const iv = e.target.dataset.iv;
    if (!iv) return;
    state.interval = iv; savePrefs(); renderTimeframes(); renderChart(); loadAnalysis();
  };
  $("#macro-syms").onclick = (e) => {
    const s = e.target.dataset.macro;
    if (!s) return;
    state.macro = s; savePrefs();
    $$("#macro-syms button").forEach((b) => b.classList.toggle("on", b.dataset.macro === s));
    renderChart();
  };
  $("#studies-btn").onclick = studiesMenu;
  $("#studies-menu").onchange = (e) => {
    const id = e.target.dataset.study;
    state.studies = e.target.checked ? [...state.studies, id] : state.studies.filter((s) => s !== id);
    savePrefs(); renderChart();
  };
  document.addEventListener("click", (e) => { if (!e.target.closest("#studies-menu")) $("#studies-menu").hidden = true; });
  $("#toggle-sc").onclick = (e) => { state.showScenario = !state.showScenario; e.currentTarget.classList.toggle("on", state.showScenario); savePrefs(); drawScenarioLines(); };
  $("#fs-btn").onclick = toggleFullscreen;
  document.addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() === "f" && !e.target.closest("input, textarea, select") && $("#v-trade").classList.contains("on")) toggleFullscreen();
  });
  document.addEventListener("fullscreenchange", () => setTimeout(() => { lw?.timeScale().fitContent(); drawHeat(); }, 150));
  on("tickers", renderOrderPreview);

  $("#watchlist").onclick = (e) => { const r = e.target.closest("[data-sym]"); if (r) setSymbol(r.dataset.sym); };
  $("#watchlist").ondblclick = (e) => {
    const r = e.target.closest("[data-sym]");
    if (!r || r.dataset.sym === state.symbol) return;
    state.watch = state.watch.filter((s) => s !== r.dataset.sym); savePrefs(); renderWatchlist();
  };
  $("#wl-search").onkeydown = (e) => { if (e.key === "Enter" && e.target.value.trim()) { setSymbol(e.target.value.trim()); e.target.value = ""; } };
  $("#symbtn").onclick = () => $("#wl-search").focus();

  $("#side-tabs").onclick = (e) => {
    const t = e.target.dataset.t;
    if (!t) return;
    $$("#side-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === t));
    $("#side-sc").hidden = t !== "sc"; $("#side-order").hidden = t !== "order";
  };
  $("#side-sc").onclick = (e) => {
    const b = e.target.closest("[data-sc]");
    if (b) {
      state.showScenario = true; $("#toggle-sc").classList.add("on");
      if (state.chartMode !== "liq") { state.chartMode = "liq"; renderChart(); }
      drawScenarioLines(state.analysis.scenarios[+b.dataset.sc]);
    }
    if (e.target.id === "ai-comment") busy(e.target, () => loadAnalysis(true));
  };
  $$(".sidebtn button").forEach((b) => (b.onclick = () => {
    side = b.dataset.side;
    $$(".sidebtn button").forEach((x) => x.classList.toggle("on", x === b));
    renderOrderPreview();
  }));
  ["#o-margin", "#o-lev"].forEach((s) => ($(s).oninput = renderOrderPreview));
  $("#o-submit").onclick = (e) => busy(e.target, async () => {
    const num = (id) => { const v = $(id).value; return v === "" ? null : Number(v); };
    await api("/api/paper/order", { method: "POST", body: { symbol: state.symbol, side, margin: num("#o-margin"),
      leverage: num("#o-lev"), stop_loss_pct: num("#o-sl"), take_profit_pct: num("#o-tp") } });
    toast(`${state.symbol} ${side === "long" ? "롱" : "숏"} 체결 (모의)`, "", side === "long" ? "up" : "err");
    loadAccount();
  });
  $("#pa-add").onclick = () => { addPriceAlert(state.symbol, +$("#pa-price").value); $("#pa-price").value = ""; };
  $("#pa-list").onclick = (e) => { const i = e.target.dataset.pa; if (i != null) removePriceAlert(+i); };

  $("#bot-tabs").onclick = (e) => {
    const t = e.target.dataset.t;
    if (!t) return;
    bottomTab = t;
    $$("#bot-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === t));
    renderBottom();
  };
  $("#bottom-body").onclick = (e) => {
    const sym = e.target.dataset.close;
    if (sym) busy(e.target, async () => { await api(`/api/paper/close/${sym}`, { method: "POST" }); loadAccount(); });
  };

  on("rechart", renderChart);
  pollTickers(); setInterval(pollTickers, 5000);
  pollDerivatives(); setInterval(pollDerivatives, 30_000); setInterval(tickFunding, 1000);
  loadAnalysis();
  loadAccount(); setInterval(loadAccount, 5000);
  loadBots(); setInterval(loadBots, 15_000);
  renderBottom();
}
