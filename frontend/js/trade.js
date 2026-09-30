// 트레이드 화면
import { addPriceAlert, getPriceAlerts, removePriceAlert } from "./alerts.js";
import { TermChart } from "./chart.js";
import { copilotSymbolChanged, initCopilot, showCopilot } from "./copilot.js";
import {
  $, $$, INTERVALS, IV_LABEL, TV_INTERVAL, api, big, busy, cls, css, emit, esc, fmt, hhmm, mdhm, on, pct,
  px, savePrefs, state, toast, tradeRows,
} from "./core.js";
import { DEFAULT_INDICATORS, GROUPS, INDICATORS } from "./ind.js";

const MACRO = [
  ["NASDAQ:NDX", "나스닥100"], ["CAPITALCOM:US100", "나스닥 CFD"], ["SP:SPX", "S&P500"], ["TVC:DXY", "달러인덱스"],
  ["TVC:US10Y", "미 10년물"], ["TVC:GOLD", "금"], ["CRYPTOCAP:BTC.D", "BTC.D"], ["CRYPTOCAP:USDT.D", "USDT.D"],
];
state.indicators ||= DEFAULT_INDICATORS;
state.overlays ||= { heat: false, whales: false, bots: true, scenario: true, sr: true };
state.overlays.sr ??= true;
state.overlays.countdown ??= true;
state.overlays.forecast ??= true;
state.overlays.footprint ??= false;
delete state.overlays.rotation;
state.overlays.ladder ??= true;
state.overlays.ai ??= true;           // AI 진입 시그널
// 차트 분할: 칸 수 · 열/행 비율 · (큰 칸이 있으면) 영역 배치
const LAYOUT_LIST = [
  ["1", { n: 1, cols: "1fr", rows: "1fr", name: "차트 1개" }],
  ["2", { n: 2, cols: "1fr 1fr", rows: "1fr", name: "2개 · 좌우" }],
  ["2v", { n: 2, cols: "1fr", rows: "1fr 1fr", name: "2개 · 위아래" }],
  ["3", { n: 3, cols: "2fr 1fr", rows: "1fr 1fr", areas: ["a b", "a c"], name: "3개 · 큰 차트 + 오른쪽 2개" }],
  ["3b", { n: 3, cols: "1fr 1fr", rows: "3fr 2fr", areas: ["a a", "b c"], name: "3개 · 큰 차트 + 아래 2개" }],
  ["3c", { n: 3, cols: "1fr 1fr 1fr", rows: "1fr", name: "3개 · 가로" }],
  ["4", { n: 4, cols: "1fr 1fr", rows: "1fr 1fr", name: "4개 · 2×2" }],
  ["4b", { n: 4, cols: "3fr 1fr", rows: "1fr 1fr 1fr", areas: ["a b", "a c", "a d"], name: "4개 · 큰 차트 + 오른쪽 3개" }],
  ["5", { n: 5, cols: "2fr 1fr 1fr", rows: "1fr 1fr", areas: ["a b c", "a d e"], name: "5개 · 큰 차트 + 4개" }],
  ["6", { n: 6, cols: "1fr 1fr 1fr", rows: "1fr 1fr", name: "6개 · 3×2" }],
  ["8", { n: 8, cols: "1fr 1fr 1fr 1fr", rows: "1fr 1fr", name: "8개 · 4×2" }],
  ["9", { n: 9, cols: "1fr 1fr 1fr", rows: "1fr 1fr 1fr", name: "9개 · 3×3" }],
];
const LAYOUTS = Object.fromEntries(LAYOUT_LIST);   // (숫자 이름은 객체에서 순서가 바뀌므로 메뉴는 LAYOUT_LIST 순서로)
const layIcon = (L) => `<span class="lico" style="grid-template-columns:${L.cols};grid-template-rows:${L.rows};${L.areas ? `grid-template-areas:${L.areas.map((r) => `'${r}'`).join(" ")}` : ""}">${Array.from({ length: L.n }, (_, i) => `<i${L.areas ? ` style="grid-area:${"abcde"[i]}"` : ""}></i>`).join("")}</span>`;
state.layout = LAYOUTS[String(state.layout)] ? String(state.layout) : "1";
const MULTI_DEFAULT = [["ETHUSDT", "1h"], ["SOLUSDT", "1h"], ["BTCUSDT", "4h"], ["XRPUSDT", "1h"], ["BNBUSDT", "1h"], ["DOGEUSDT", "1h"], ["BTCUSDT", "15m"], ["ETHUSDT", "4h"]];
state.multi ||= [];
while (state.multi.length < 8) { const [symbol, interval] = MULTI_DEFAULT[state.multi.length]; state.multi.push({ symbol, interval }); }

// ================================================================ 시세 · 관심종목
async function pollTickers() {
  const syms = [...new Set([...state.watch, state.symbol])];
  try {
    const d = await api(`/api/tickers?symbols=${syms.join(",")}`);
    d.items.forEach((t) => (state.tickers[t.symbol] = t));
    state.tickerSource = d.source;
    emit("tickers", state.tickers);
    renderWatchlist(); renderTickerBar();
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
  const last = $("#t-last"), prev = +last.dataset.v || t.price;
  last.dataset.v = t.price;
  last.textContent = px(t.price);
  last.className = `lastpx ${t.price > prev ? "up" : t.price < prev ? "down" : cls(t.change_pct)}`;
  $("#t-chg").innerHTML = `<span class="${cls(t.change_pct)}">${pct(t.change_pct)}</span>`;
  $("#t-high").textContent = px(t.high); $("#t-low").textContent = px(t.low); $("#t-vol").textContent = big(t.quote_volume);
  document.title = `${px(t.price)} ${state.symbol.replace("USDT", "")} · GH Quant`;
}

let premium = null;
async function pollDerivatives() {
  const sym = state.symbol;
  try {
    const d = await api(`/api/derivatives?symbol=${sym}&interval=1h&limit=48`);
    if (sym !== state.symbol) return;
    premium = d.premium;
    const oi = d.open_interest.at(-1)?.value, oi24 = d.open_interest.at(-25)?.value;
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

async function pollSentiment() {
  api("/api/fear-greed?days=30").then((f) => {
    state.fng = f;
    const c = f.value < 45 ? "down" : f.value > 55 ? "up" : "accent";
    $("#t-fng").innerHTML = `<span class="${c}">${f.value}</span> <span class="muted">${f.label}</span>`;
    emit("fng", f);
  }).catch(() => ($("#t-fng").textContent = "–"));
  const sym = state.symbol;
  api(`/api/exchanges?symbol=${sym}`).then((e) => {
    if (sym !== state.symbol) return;
    state.exchanges = e;
    $("#t-kimp").innerHTML = e.kimchi_pct == null ? "–" : `<span class="${cls(e.kimchi_pct)}">${pct(e.kimchi_pct)}</span>`;
    if (bottomTab === "ex") renderBottom();
  }).catch(() => ($("#t-kimp").textContent = "–"));
}

// "페페", "도지", "pepe" 같은 입력 → 바이낸스 선물 심볼 (1000PEPEUSDT 등)
async function lookup(q) {
  q = q.trim();
  if (/^[A-Z0-9]+USDT$/.test(q)) return q;
  try { return (await api(`/api/resolve?q=${encodeURIComponent(q)}`)).symbol; }
  catch { q = q.toUpperCase(); return q.endsWith("USDT") ? q : q + "USDT"; }
}

function setSymbol(sym) {
  sym = sym.toUpperCase();
  if (!sym.endsWith("USDT")) sym += "USDT";
  state.symbol = sym;
  if (!state.watch.includes(sym)) state.watch.push(sym);
  savePrefs();
  $("#t-last").dataset.v = "";
  ["#t-oi", "#t-ls", "#t-fund", "#t-kimp"].forEach((id) => ($(id).textContent = "–"));
  premium = null; state.exchanges = null; bookStep = null;
  renderWatchlist();
  pollTickers(); pollDerivatives(); pollSentiment(); loadBook();
  renderChart(); loadAnalysis(); copilotSymbolChanged();
  emit("symbol", sym);
}
export { setSymbol };

// ================================================================ 차트
let charts = [];   // TermChart 들 (0번 = 메인)

function renderTimeframes() {
  $("#tfs").innerHTML = INTERVALS.map(([k, l]) => `<button data-iv="${k}" class="${k === state.interval ? "on" : ""}">${l}</button>`).join("");
}

function renderToolbar() {
  const mode = state.chartMode, term = mode === "term";
  $$("#chart-mode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
  $("#macro-syms").hidden = mode !== "macro";
  $$(".term-only").forEach((e) => (e.hidden = !term));
  $("#ind-btn").hidden = mode === "macro";
  $$("#overlays button").forEach((b) => b.classList.toggle("on", b.dataset.ov === "patterns" ? state.indicators.some((x) => x.key === "chartpat") : !!state.overlays[b.dataset.ov]));
  $$("#layouts button").forEach((b) => b.classList.toggle("on", b.dataset.layout === state.layout));
  $("#lay-btn").innerHTML = `${layIcon(LAYOUTS[state.layout])}<span>분할</span>`;
}

function renderChart() {
  renderToolbar();
  const mode = state.chartMode;
  $("#tv-main").hidden = mode === "term";
  $("#term-grid").hidden = mode !== "term";
  if (mode !== "term") {
    charts.forEach((c) => c.destroy()); charts = [];
    return renderTv(mode === "macro" ? state.macro : `BINANCE:${state.symbol}.P`, mode === "tv" ? state.studies : []);
  }
  $("#tv-main").innerHTML = "";
  const grid = $("#term-grid");
  const L = LAYOUTS[state.layout], n = L.n;
  if (charts.length !== n || grid.dataset.layout !== state.layout) {
    charts.forEach((c) => c.destroy()); charts = [];
    grid.dataset.layout = state.layout;
    grid.className = `term-grid${n >= 6 ? " dense" : ""}`;
    Object.assign(grid.style, { gridTemplateColumns: L.cols, gridTemplateRows: L.rows, gridTemplateAreas: L.areas ? L.areas.map((r) => `"${r}"`).join(" ") : "none" });
    grid.innerHTML = Array.from({ length: n }, (_, i) => `<div class="cell"${L.areas ? ` style="grid-area:${"abcde"[i]}"` : ""}>${i ? `<div class="cell-h">
        <input data-cell="${i}" data-k="symbol" value="${state.multi[i - 1].symbol.replace("USDT", "")}">
        <select data-cell="${i}" data-k="interval">${INTERVALS.map(([k, l]) => `<option value="${k}" ${k === state.multi[i - 1].interval ? "selected" : ""}>${l}</option>`).join("")}</select></div>` : ""}
        <div class="cell-b"></div></div>`).join("");
    $$(".cell-b", grid).forEach((el, i) => {
      const subInd = state.indicators.filter((x) => INDICATORS[x.key]?.pane === "sub");
      charts.push(new TermChart(el, {
        symbol: i ? state.multi[i - 1].symbol : state.symbol, interval: i ? state.multi[i - 1].interval : state.interval,
        // 작은 칸에는 보조지표 창을 줄인다 (6칸 이상이면 가격 위 지표만)
        indicators: i ? state.indicators.filter((x) => INDICATORS[x.key]?.pane !== "sub").concat(n >= 6 ? [] : subInd.slice(0, 1)) : state.indicators,
        overlays: i ? { heat: false, whales: false, bots: true, scenario: false, sr: state.overlays.sr, countdown: state.overlays.countdown, ai: state.overlays.ai } : { ...state.overlays },
        onDrawDone: () => $$("#draw-tools button").forEach((b) => b.classList.remove("on")),
        onEditPosition: editPosition,
      }));
    });
  }
  charts[0]?.setLadder(!!state.overlays.ladder);
  charts.forEach((c, i) => c.load(i ? state.multi[i - 1].symbol : state.symbol, i ? state.multi[i - 1].interval : state.interval)
    .then(() => { if (!i && state.overlays.forecast && state.forecast) c.setForecast(state.forecast); })
    .catch((e) => toast("차트 오류", e.message, "err")));
  if (state.analysis?.symbol === state.symbol) charts[0]?.setScenario(state.overlays.scenario ? state.analysis.scenarios[0] : null, state.analysis.symbol);
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

// 지표 선택 패널
function indicatorPanel(e) {
  const m = $("#ind-menu");
  if (!m.hidden && !e.refresh) { m.hidden = true; return; }
  if (state.chartMode === "tv") return tvStudiesMenu(e);
  const groups = Object.fromEntries(GROUPS.map((g) => [g, []]));
  Object.entries(INDICATORS).forEach(([k, d]) => (groups[d.group] ||= []).push([k, d]));
  const used = new Set(state.indicators.map((x) => x.key));
  m.innerHTML = `<div class="ind-panel">
    <div class="ind-list"><input id="ind-q" placeholder="지표 검색 (${Object.keys(INDICATORS).length}개 · 한글/영문)">${Object.entries(groups).filter(([, xs]) => xs.length).map(([g, xs]) => `<div class="sub" data-g="${esc(g)}">${g}</div>` +
      xs.map(([k, d]) => `<div class="ind-item" data-add="${k}" data-g="${esc(g)}" data-q="${esc(`${d.name} ${k} ${d.desc || ""}`.toLowerCase())}" title="${esc(d.desc || d.name)}">${esc(d.name)}${used.has(k) ? ' <span class="accent">✓</span>' : ""}</div>`).join("")).join("")}</div>
    <div class="ind-active"><div class="sub">적용된 지표 ${state.indicators.length}개 · 제한 없음</div>${state.indicators.map((s, i) => {
      const d = INDICATORS[s.key]; if (!d) return "";
      return `<div class="ind-row"><span class="grow">${esc(d.name)}</span>${Object.entries({ ...d.params, ...s.params }).map(([k, v]) =>
        `<input data-i="${i}" data-p="${k}" value="${v}" title="${k}" style="width:46px">`).join("")}<button class="x" data-del="${i}">✕</button></div>`;
    }).join("")}<div class="row" style="margin-top:8px"><button class="sm" id="ind-reset">기본값으로</button></div></div></div>`;
  const r = $("#ind-btn").getBoundingClientRect();
  m.style.left = `${Math.max(8, Math.min(r.left, innerWidth - 640))}px`; m.style.top = `${r.bottom + 4}px`;
  m.hidden = false;
  e.stopPropagation?.();
  $("#ind-q").oninput = (ev) => {
    const q = ev.target.value.trim().toLowerCase().replace(/\s+/g, "");
    $$(".ind-item", m).forEach((it) => (it.hidden = !!q && !it.dataset.q.replace(/\s+/g, "").includes(q)));
    $$(".ind-list .sub", m).forEach((h) => (h.hidden = !$$(`.ind-item[data-g="${h.dataset.g}"]`, m).some((it) => !it.hidden)));
  };
  if (!e.refresh) $("#ind-q").focus();
}
function applyIndicators() {
  savePrefs();
  charts[0]?.setIndicators(state.indicators);
  indicatorPanel({ refresh: true });
}
function tvStudiesMenu(e) {
  const m = $("#ind-menu");
  const reg = state.status?.indicators || {};
  const list = Object.values(reg).filter((v) => v.tv).map((v) => [v.tv, v.desc]);
  list.push(["Volume@tv-basicstudies", "거래량"]);
  m.innerHTML = `<div style="padding:6px 8px;max-width:320px" class="muted">트레이딩뷰 무료 위젯은 지표 수가 제한됩니다. 제한 없이 쓰려면 '터미널 차트'를 쓰세요.</div>` +
    list.map(([id, l]) => `<label class="ind-item"><input type="checkbox" data-study="${id}" ${state.studies.includes(id) ? "checked" : ""} style="height:auto"> ${esc(l)}</label>`).join("");
  const r = $("#ind-btn").getBoundingClientRect();
  m.style.left = `${r.left}px`; m.style.top = `${r.bottom + 4}px`;
  m.hidden = false;
  e.stopPropagation?.();
}

function toggleFullscreen() {
  const el = $("#chartp");
  if (document.fullscreenElement) document.exitFullscreen();
  else el.requestFullscreen?.().catch(() => toast("전체 화면을 지원하지 않는 브라우저입니다"));
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
    renderRegime(a); renderScenarios(a);
    charts[0]?.setScenario(state.overlays.scenario ? a.scenarios[0] : null, a.symbol);
    emit("analysis", a);
    loadForecast(); loadFpPanel();
  } catch (e) {
    $("#regime").innerHTML = `<span class="muted">분석 실패: ${esc(e.message)}</span>`;
  }
  analysisTimer = setTimeout(() => loadAnalysis(), 60_000);
}

// ================================================================ 패턴 예측 · 다음 봉
let fcBusy = false;
async function loadForecast() {
  if (fcBusy) return;
  const sym = state.symbol, iv = state.interval;
  if (iv === "1y") { $("#side-fc").innerHTML = `<div class="empty">연봉은 데이터가 적어 예측하지 않습니다.</div>`; return; }
  fcBusy = true;
  try {
    const f = await api(`/api/forecast?symbol=${sym}&interval=${iv}`);
    if (sym !== state.symbol || iv !== state.interval) return;
    const changed = state.forecast?.bar_time !== f.bar_time || state.forecast?.symbol !== f.symbol || state.forecast?.interval !== f.interval;
    state.forecast = f;
    renderForecast(f);
    loadEntry();
    if (changed) charts[0]?.setForecast(state.overlays.forecast ? f : null);
    emit("forecast", f);
  } catch (e) {
    $("#side-fc").innerHTML = `<div class="empty">예측 실패: ${esc(e.message)}</div>`;
  } finally { fcBusy = false; }
}

function spark(shape, split, ret) {
  const w = 132, h = 34, lo = Math.min(...shape), hi = Math.max(...shape), sx = w / (shape.length - 1), y = (v) => h - 2 - (v - lo) / ((hi - lo) || 1) * (h - 4);
  const pts = (a, b) => shape.slice(a, b + 1).map((v, i) => `${((a + i) * sx).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="과거 비슷한 구간과 그 뒤 흐름">
    <line x1="${split * sx}" x2="${split * sx}" y1="0" y2="${h}" stroke="var(--line-2)" stroke-dasharray="2 2"/>
    <polyline points="${pts(0, split)}" fill="none" stroke="var(--text-2)" stroke-width="1.5"/>
    <polyline points="${pts(split, shape.length - 1)}" fill="none" stroke="${ret >= 0 ? "var(--up)" : "var(--down)"}" stroke-width="2"/></svg>`;
}

async function loadEntry() {
  const sym = state.symbol, iv = state.interval;
  try {
    const e = await api(`/api/entry?symbol=${sym}&interval=${iv}`);
    if (sym !== state.symbol || iv !== state.interval) return;
    state.entry = e;
    const el = $("#side-entry");
    if (!el) return;
    const cls2 = { long: "up", short: "down", wait: "accent" }[e.verdict];
    el.innerHTML = `<div class="sub" style="padding-left:0">종합 진입 판단 <span class="muted">(${e.agree}/${e.total}개 근거가 같은 방향)</span></div>
      <div class="row"><b class="${cls2}" style="font-size:20px">${e.label}</b><span class="muted">점수 ${e.score > 0 ? "+" : ""}${e.score}</span></div>
      <div class="gauge" style="margin:6px 0"><i style="left:calc(${(e.score + 100) / 2}% - 1px)"></i></div>
      ${e.parts.map((p) => `<div class="hbar"><span class="dim">${esc(p.name)}</span><div class="track"><b></b>
        <i style="${p.contrib >= 0 ? `left:50%;width:${Math.min(50, Math.abs(p.contrib) * 2)}%` : `right:50%;width:${Math.min(50, Math.abs(p.contrib) * 2)}%`};background:${p.contrib >= 0 ? "var(--up)" : "var(--down)"}"></i></div>
        <span class="${cls(p.contrib)}" style="text-align:right">${p.contrib > 0 ? "+" : ""}${p.contrib}</span></div><div class="muted" style="font-size:11px;margin:-1px 0 4px">${esc(p.text)}</div>`).join("")}
      ${e.plan ? `<div class="plan ${e.verdict}" style="margin-top:6px"><div class="row"><b>${e.verdict === "long" ? "롱" : "숏"} 계획</b><span class="muted">${esc(e.plan.source)} · RR ${e.plan.rr ?? "–"}</span><div class="grow"></div>
        <button class="flat sm" data-plan='${JSON.stringify({ k: e.verdict, ...e.plan }).replace(/'/g, "&#39;")}'>차트에</button></div>
        <div class="kv2"><span class="k">진입</span><span>${px(e.plan.entry)}</span><span class="k">손절</span><span class="down">${px(e.plan.stop)}</span><span class="k">익절</span><span class="up">${px(e.plan.take)}</span></div>
        <div class="help">${esc(e.plan.why)}</div></div>` : ""}
      ${e.evidence.length || e.footprint_notes.length ? `<div class="sub" style="padding-left:0;margin-top:6px">근거</div><ul class="reasons">${[...e.evidence, ...e.footprint_notes].map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
      <div class="help">${esc(e.note)}</div>`;
  } catch (err) {
    const el = $("#side-entry");
    if (el) el.innerHTML = `<div class="muted">종합 판단 실패: ${esc(err.message)}</div>`;
  }
}

function renderForecast(f) {
  const a = f.analog, nb = f.next_bar;
  const bar = (p) => `<div class="bar"><i style="width:${p}%;background:${p >= 50 ? "var(--up)" : "var(--down)"}"></i></div>`;
  const pctS = (v) => `<span class="${cls(v)}">${v > 0 ? "+" : ""}${fmt(v, 2)}%</span>`;
  $("#side-fc").innerHTML = `
    <div class="fc-sec" id="side-entry">${$("#side-entry")?.innerHTML || '<div class="muted">종합 판단 계산 중…</div>'}</div>
    <div class="fc-sec"><div class="sub" style="padding-left:0">다음 봉 예측 <span class="muted">(${IV_LABEL[f.interval]} 1개)</span></div>
      ${nb ? `<div class="row"><b class="${nb.p_up > 50 ? "up" : nb.p_up < 50 ? "down" : "accent"}" style="font-size:18px">${nb.p_up === 50 ? "방향 불분명 50%" : `${nb.p_up > 50 ? "상승" : "하락"} ${Math.max(nb.p_up, 100 - nb.p_up)}%`}</b>
          <span class="muted">예상 ${pctS(nb.median_ret_pct)} · 범위 ${px(nb.range.low)} ~ ${px(nb.range.high)}</span></div>${bar(nb.p_up)}
        <div class="kv" style="margin-top:6px"><span class="k">최근 ${nb.backtest.evaluated}봉 적중률</span><span><b>${nb.backtest.accuracy_pct ?? "–"}%</b> <span class="muted">(찍기 기준 ${nb.backtest.baseline_pct}%)</span></span>
          <span class="k">확신 높은 때만</span><span>${nb.backtest.confident_accuracy_pct ?? "–"}% <span class="muted">(${nb.backtest.confident_n}번)</span></span></div>
        <div class="help" style="margin-top:4px">${esc(nb.verdict)}. 12가지 특징이 비슷했던 과거 ${nb.neighbors}개 봉의 다음 봉 결과로 계산합니다. 차트 오른쪽 흐린 캔들이 예상 모양입니다.</div>`
        : `<div class="muted">${esc(f.next_bar_error || "계산할 수 없습니다")}</div>`}</div>
    <div class="fc-sec"><div class="sub" style="padding-left:0">과거 유사 패턴 시나리오 <span class="muted">(${a ? a.horizon + "봉 뒤까지" : ""})</span></div>
      ${a ? `<div class="row"><b class="${a.prob_up >= 50 ? "up" : "down"}" style="font-size:18px">상승 ${a.prob_up}%</b>
          <span class="muted">중간값 ${pctS(a.median_ret_pct)} · 유사도 ${a.avg_corr} · 신뢰도 ${a.reliability}</span></div>${bar(a.prob_up)}
        <div class="mtf" style="margin-top:6px">${Object.entries(a.prob_up_by_h).map(([h, p]) => `<div><span class="k">${h}봉 뒤</span><span class="${p >= 50 ? "up" : "down"}">상승 ${p}%</span></div>`).join("")}</div>
        <div class="kv" style="margin-top:6px"><span class="k">예상 범위 (10~90%)</span><span>${pctS(a.p10_ret_pct)} ~ ${pctS(a.p90_ret_pct)}</span>
          <span class="k">가격 범위</span><span>${px(a.bands.p10.at(-1))} ~ ${px(a.bands.p90.at(-1))}</span></div>
        <div class="help" style="margin-top:4px">${esc(a.summary)} 차트의 주황 부채꼴이 이 범위(진한 곳 25~75%, 옅은 곳 10~90%), 주황선이 중간값입니다.</div>
        <div class="sub" style="padding-left:0;margin-top:8px">가장 비슷했던 과거 구간</div>
        ${a.matches.slice(0, 6).map((m) => `<div class="fc-match"><div>${spark(m.shape, a.window - 1, m.ret_pct)}</div>
          <div><div class="muted">${mdhm(m.end)} · 유사도 ${m.corr}</div><div>${a.horizon}봉 뒤 ${pctS(m.ret_pct)} <span class="muted">최고 ${fmt(m.max_up_pct, 1)}% · 최저 ${fmt(m.max_down_pct, 1)}%</span></div></div></div>`).join("")}`
        : `<div class="muted">${esc(f.analog_error || "계산할 수 없습니다")}</div>`}</div>
    <div class="help" style="padding:10px 0">통계적 참고 자료입니다. 과거에 비슷했다고 똑같이 움직이지는 않습니다. 적중률이 '찍기 기준'보다 높지 않으면 믿지 마세요.</div>`;
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

// ================================================================ 호가창
let bookStep = null, bookTimer;
async function loadBook() {
  clearTimeout(bookTimer);
  if ($("#side-book").hidden) return;
  const sym = state.symbol;
  try {
    const ob = await api(`/api/orderbook?symbol=${sym}&rows=18${bookStep ? "&step=" + bookStep : ""}`);
    if (sym !== state.symbol) { bookTimer = setTimeout(loadBook, 0); return; }
    const max = Math.max(...ob.asks.map((x) => x.cum), ...ob.bids.map((x) => x.cum));
    const row = (x, sd) => `<div class="ob-row ${sd}"><i style="width:${(x.cum / max * 100).toFixed(1)}%"></i>
      <span class="${sd === "ask" ? "down" : "up"}">${px(x.price)}</span><span>${fmt(x.qty, x.qty >= 100 ? 0 : 3)}</span><span class="dim">${big(x.usd)}</span></div>`;
    const imb = ob.imbalance * 100;
    $("#side-book").innerHTML = `
      <div class="ph" style="gap:4px"><span class="t">호가</span><span class="muted">${ob.source === "synthetic" ? "가상" : "바이낸스 선물"}</span><div class="grow"></div>
        <span class="muted">묶음</span><select id="ob-step" style="height:22px">${ob.steps.map((s) => `<option ${s === ob.step ? "selected" : ""}>${s}</option>`).join("")}</select></div>
      <div class="ob-head"><span>가격</span><span>수량</span><span>금액($)</span></div>
      ${ob.asks.slice().reverse().map((x) => row(x, "ask")).join("")}
      <div class="ob-mid"><b>${px(ob.mid)}</b> <span class="muted">스프레드 ${px(ob.spread)}</span></div>
      ${ob.bids.map((x) => row(x, "bid")).join("")}
      <div style="padding:8px 12px">
        <div class="row muted" style="justify-content:space-between"><span>±1% 매수 $${big(ob.bid_usd_1pct)}</span><span>매도 $${big(ob.ask_usd_1pct)}</span></div>
        <div class="imb"><i style="width:${(50 + imb / 2).toFixed(1)}%"></i></div>
        <div class="${imb >= 0 ? "up" : "down"}" style="text-align:center">${imb >= 0 ? "매수 우위" : "매도 우위"} ${Math.abs(imb).toFixed(1)}%</div></div>
      ${bookTools(ob)}`;
    $("#ob-step").onchange = (e) => { bookStep = +e.target.value; loadBook(); };
  } catch (e) {
    $("#side-book").innerHTML = `<div class="empty">호가창을 불러오지 못했습니다: ${esc(e.message)}</div>`;
  }
  bookTimer = setTimeout(loadBook, 2000);
}

// 호가 기반 진입 도구: 깊이별 불균형 · 추이 · 벽 유지 시간 · 사라진 벽 · 슬리피지 · 진입 계획
function bookTools(ob) {
  const age = (s) => s >= 3600 ? `${Math.floor(s / 3600)}시간` : s >= 60 ? `${Math.floor(s / 60)}분` : `${s}초`;
  const h = ob.imbalance_history || [];
  let spark = "";
  if (h.length > 2) {
    const W = 236, H = 34, x = (i) => i / (h.length - 1) * W, y = (v) => H / 2 - v * (H / 2 - 2);
    spark = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="±1% 호가 불균형 추이"><line x1="0" x2="${W}" y1="${H / 2}" y2="${H / 2}" stroke="var(--line-2)"/>
      <polyline points="${h.map((p, i) => `${x(i).toFixed(1)},${y(p.imbalance).toFixed(1)}`).join(" ")}" fill="none" stroke="var(--accent)" stroke-width="1.5"/></svg>`;
  }
  const plan = (k, p) => p ? `<div class="plan ${k}"><div class="row"><b class="${k === "long" ? "up" : "down"}">${k === "long" ? "롱 계획" : "숏 계획"}</b><span class="muted">RR ${p.rr ?? "–"}</span><div class="grow"></div>
      <button class="flat sm" data-plan='${JSON.stringify({ k, ...p }).replace(/'/g, "&#39;")}'>차트에</button></div>
      <div class="kv2"><span class="k">지정가</span><span>${px(p.entry)}</span><span class="k">손절</span><span class="down">${px(p.stop)}</span><span class="k">익절</span><span class="up">${px(p.take)}</span></div>
      <div class="help">${esc(p.why)}</div></div>` : "";
  return `
    <div class="sub">깊이별 매수·매도 불균형</div>
    ${ob.depth.map((d) => `<div class="hbar" style="padding:2px 12px"><span class="dim">±${d.pct}%</span><div class="track"><b></b>
      <i style="${d.imbalance >= 0 ? `left:50%;width:${d.imbalance * 50}%` : `right:50%;width:${-d.imbalance * 50}%`};background:${d.imbalance >= 0 ? "var(--up)" : "var(--down)"}"></i></div>
      <span class="${d.imbalance >= 0 ? "up" : "down"}" style="text-align:right">${(d.imbalance * 100).toFixed(0)}%</span></div>`).join("")}
    ${spark ? `<div style="padding:4px 12px"><div class="muted" style="font-size:11px">±1% 불균형 추이 (보고 있는 동안, 위 = 매수 우위)</div>${spark}</div>` : ""}
    <div class="sub">진입 계획 (호가 벽 기준)</div>
    <div style="padding:0 12px"><div class="help" style="margin-bottom:4px">${esc(ob.plan.note)}</div>
      ${plan("long", ob.plan.plans.long)}${plan("short", ob.plan.plans.short)}
      ${!ob.plan.plans.long && !ob.plan.plans.short ? '<div class="muted">±2% 안에 뚜렷한 벽이 없습니다</div>' : ""}</div>
    <div class="sub">호가 벽 (±5%) <span class="muted">· 유지 시간</span></div>
    ${ob.walls.map((w) => `<div class="lv"><span class="${w.side === "bid" ? "up" : "down"}">${w.side === "bid" ? "매수벽" : "매도벽"} ${px(w.price)}</span><span class="px">$${big(w.usd)} <span class="muted">${age(w.age_sec)}</span></span></div>`).join("") || '<div class="empty">눈에 띄는 벽 없음</div>'}
    ${ob.pulled?.length ? `<div class="sub">가격이 닿기 전에 사라진 벽 <span class="muted">(허수 주문 의심)</span></div>
      ${ob.pulled.slice().reverse().map((w) => `<div class="lv"><span class="dim">${hhmm(w.time)} ${w.side === "bid" ? "매수벽" : "매도벽"} ${px(w.price)}</span><span class="px">$${big(w.usd)} <span class="muted">${age(w.lived_sec)} 유지</span></span></div>`).join("")}` : ""}
    <div class="sub">시장가 주문 시 예상 슬리피지</div>
    <table style="margin:0 0 8px"><tr><th>규모</th><th>매수</th><th>매도</th></tr>
      ${ob.slippage.map((r) => `<tr><td>$${big(r.usd)}</td>${["buy", "sell"].map((k) => `<td>${r[k] ? `${r[k].slip_pct.toFixed(3)}%` : '<span class="muted">호가 부족</span>'}</td>`).join("")}</tr>`).join("")}</table>
    <div class="help" style="padding:0 12px 10px">스프레드 ${ob.spread_bps?.toFixed(2)}bp. 큰 주문은 여러 번 나눠 넣거나 지정가를 쓰면 슬리피지를 줄일 수 있습니다. 벽은 언제든 취소될 수 있으니 벽만 믿고 진입하지 마세요.</div>`;
}

// ================================================================ 풋프린트 분석 패널 (다음 봉 · 진입 신호 · 지지저항 판정)
let fpTimer;
async function loadFpPanel() {
  clearTimeout(fpTimer);
  if ($("#side-fpx").hidden) return;
  const sym = state.symbol, iv = state.interval, el = $("#side-fpx");
  if (iv === "1m" || iv === "1y") { el.innerHTML = `<div class="empty">풋프린트는 3분봉 ~ 월봉에서 쓸 수 있습니다.</div>`; return; }
  if (!el.innerHTML) el.innerHTML = `<div class="empty">분석 중…</div>`;
  try {
    const f = await api(`/api/footprint?symbol=${sym}&interval=${iv}&bars=80&analysis=true`);
    if (sym !== state.symbol || iv !== state.interval) return;
    renderFpPanel(f);
  } catch (e) { el.innerHTML = `<div class="empty">풋프린트 분석 실패: ${esc(e.message)}</div>`; }
  fpTimer = setTimeout(loadFpPanel, 30_000);
}

function renderFpPanel(f) {
  const a = f.analysis, nx = a.next, st = a.signal_stats;
  const odds = (o) => o.p_up == null ? `<span class="muted">표본 없음</span>`
    : `<b class="${o.p_up > 50 ? "up" : o.p_up < 50 ? "down" : "accent"}">${o.p_up === 50 ? "반반 50%" : o.p_up > 50 ? `상승 ${o.p_up}%` : `하락 ${100 - o.p_up}%`}</b> <span class="muted">(같은 모양 ${o.n}번 · 평소 상승 ${nx.baseline_up}%)</span>${o.n < 30 ? ' <span class="accent">표본 적음</span>' : ""}`;
  const ST = { holding: ["유지", "up"], weakening: ["흔들림", "accent"], broken: ["이탈", "down"], untested: ["미테스트", "muted"] };
  const sig = (s) => `<div class="plan ${s.dir}"><div class="row"><b class="${s.dir === "long" ? "up" : "down"}">${s.dir === "long" ? "▲ 롱" : "▼ 숏"}</b>
      <span class="muted">${mdhm(s.time)}</span><span class="${s.outcome === "take" ? "up" : s.outcome === "stop" ? "down" : "accent"}">${s.outcome === "take" ? "익절 도달" : s.outcome === "stop" ? "손절 도달" : "진행 중"}</span>
      <div class="grow"></div><button class="flat sm" data-plan='${JSON.stringify({ k: s.dir, entry: s.entry, stop: s.stop, take: s.take }).replace(/'/g, "&#39;")}'>차트에</button></div>
    <ul class="reasons" style="margin:3px 0">${s.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
    <div class="kv2"><span class="k">진입</span><span>${px(s.entry)}</span><span class="k">손절</span><span class="down">${px(s.stop)}</span><span class="k">익절</span><span class="up">${px(s.take)}</span></div></div>`;
  $("#side-fpx").innerHTML = `
    <div class="fc-sec"><div class="sub" style="padding-left:0">다음 봉 (체결 모양 기준)</div>
      <div class="kv" style="display:grid;grid-template-columns:auto 1fr;gap:4px 10px">
        <span class="k">지금 봉이 이대로 끝나면</span><span>${odds(nx.forming)}<div class="muted" style="font-size:11px">${esc(nx.forming.bucket)}</div></span>
        <span class="k">직전 확정 봉 기준</span><span>${odds(nx.last_closed)}<div class="muted" style="font-size:11px">${esc(nx.last_closed.bucket)}</div></span></div>
      <div class="help" style="margin-top:4px">${esc(nx.note)} 과거 ${nx.history}봉 기준.</div>
      ${f.summary?.notes?.length ? `<ul class="reasons">${f.summary.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}</div>
    <div class="fc-sec"><div class="sub" style="padding-left:0">지지 · 저항 하는지 <span class="muted">(최근 40봉 체결)</span></div>
      ${a.levels.length ? a.levels.map((lv) => `<div class="lvt"><div class="row"><span class="${lv.role === "support" ? "up" : "down"}">${lv.role === "support" ? "지지" : "저항"}</span>
          <b>${px(lv.price)}</b><span class="badge ${ST[lv.status][1]}">${ST[lv.status][0]}</span><div class="grow"></div><span class="muted">${lv.distance_atr > 0 ? "+" : ""}${lv.distance_atr} ATR</span></div>
          <div class="muted" style="font-size:11px">${esc(lv.source)}</div><div style="font-size:11.5px">${esc(lv.text)}</div>
          ${lv.touches ? `<div class="muted" style="font-size:11px">그 가격에서 매수 ${fmt(lv.buy_at, 2)} · 매도 ${fmt(lv.sell_at, 2)} · 닿은 봉 델타 합 ${fmt(lv.delta_on_touch, 2)}</div>` : ""}</div>`).join("")
        : '<div class="muted">가까운 지지·저항이 없습니다</div>'}
      <div class="help">차트의 선: 실선 = 유지, 긴 점선 = 흔들림, 짧은 점선 = 이탈·미테스트.</div></div>
    <div class="fc-sec"><div class="sub" style="padding-left:0">풋프린트 진입 신호 ${st.n ? `<span class="muted">· 지난 신호 ${st.n}개 중 익절 먼저 ${st.win_rate}%</span>` : ""}</div>
      ${a.signals.slice().reverse().slice(0, 5).map(sig).join("") || '<div class="muted">최근 80봉에 신호가 없습니다</div>'}
      <div class="help">${esc(st.note)}. 익절은 손절 거리의 2배라 승률 34% 이상이면 본전 이상입니다.</div></div>`;
}

// ================================================================ 주문 · 계좌
let side = "long";
function renderOrderPreview() {
  const m = +$("#o-margin").value || 0, lev = +$("#o-lev").value;
  $("#o-lev-v").textContent = `${lev}x`;
  const p = state.tickers[state.symbol]?.price;
  const liq = p ? p * (1 - (side === "long" ? 1 : -1) * (1 / lev - 0.005)) : null;
  const sgn = side === "long" ? 1 : -1, sl = +$("#o-sl").value, tp = +$("#o-tp").value;
  $("#o-preview").innerHTML = `포지션 규모 <b>${fmt(m * lev, 0)} USDT</b> · 예상 강제청산가 <b class="down">${px(liq)}</b>` +
    (p && (sl || tp) ? `<br>${sl ? `손절가 <b class="down">${px(p * (1 - sgn * sl / 100))}</b> (손실 ${fmt(m * lev * sl / 100, 0)} USDT) ` : ""}` +
      `${tp ? `익절가 <b class="up">${px(p * (1 + sgn * tp / 100))}</b> (수익 ${fmt(m * lev * tp / 100, 0)} USDT)` : ""}` : "") +
    `<br><span class="muted">진입 후 차트의 손절·익절 선을 끌거나 아래 포지션 표에서 바꿀 수 있습니다</span>`;
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
  const typing = document.activeElement?.closest?.(".edit-sltp");
  if ((bottomTab === "pos" && !typing) || bottomTab === "fills") renderBottom();
}

async function editPosition(symbol, edit) {
  try {
    await api(`/api/paper/position/${symbol}`, { method: "POST", body: edit });
    toast("손절·익절을 바꿨습니다", `${symbol} 손절 ${edit.stop ? px(edit.stop) : "없음"} · 익절 ${edit.take ? px(edit.take) : "없음"}`);
  } catch (e) {
    toast("손절·익절 변경 실패", e.message, "err");
    throw e;
  } finally {
    loadAccount(); charts[0]?.refreshOverlays();
  }
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
        <td class="edit-sltp"><input data-sl="${p.symbol}" type="number" step="any" value="${p.stop ? px(p.stop).replace(/,/g, "") : ""}" placeholder="손절가">
          <input data-tp="${p.symbol}" type="number" step="any" value="${p.take ? px(p.take).replace(/,/g, "") : ""}" placeholder="익절가">
          <button class="sm" data-save="${p.symbol}">적용</button></td>
        <td class="${cls(p.unrealized_pnl)}">${fmt(p.unrealized_pnl)} (${pct(p.roe_pct)})</td>
        <td><button class="sm" data-aipos="${p.symbol}" title="이 포지션을 실시간 AI 로 분석">AI 분석</button> <button class="sm" data-close="${p.symbol}">시장가 청산</button></td></tr>`).join("")}</table>
      <div class="help" style="padding:6px 10px">손절·익절은 칸에 가격을 넣고 '적용'을 누르거나, 차트의 손절·익절 선을 마우스로 끌어서 바꿀 수 있습니다. 칸을 비우고 적용하면 해제됩니다.</div>`
      : `<div class="empty">열린 포지션이 없습니다. 오른쪽 '주문' 탭에서 모의 주문을 넣을 수 있습니다.</div>`;
  } else if (bottomTab === "fills") {
    el.innerHTML = `<table>${tradeRows((account?.trades || []).slice().reverse())}</table>`;
  } else if (bottomTab === "bots") {
    el.innerHTML = bots.length ? `<table><tr><th>봇</th><th>종목</th><th>상태</th><th>평가 자산</th><th>수익률</th><th>포지션</th><th>거래</th><th>자동 개선</th><th></th></tr>
      ${bots.map((b) => { const a = b.account, p = a.position, r = (a.equity / b.initial_equity - 1) * 100;
        return `<tr><td>${esc(b.name)}</td><td>${b.symbol} ${IV_LABEL[b.interval] || b.interval}</td><td class="${b.running ? "up" : "muted"}">${b.running ? "실행" : "정지"}</td>
        <td>${fmt(a.equity)}</td><td class="${cls(r)}">${pct(r)}</td>
        <td>${p ? `<span class="${p.side === "long" ? "up" : "down"}">${p.side === "long" ? "롱" : "숏"}</span> ${px(p.entry_price)}` : "–"}</td><td>${a.trades.length}</td>
        <td class="${b.auto_improve ? "accent" : "muted"}">${b.auto_improve ? `켜짐 (${b.improve_every}건마다)` : "꺼짐"}</td>
        <td><button class="sm" data-botchart="${b.symbol}|${b.interval}">차트에서 보기</button></td></tr>`; }).join("")}</table>`
      : `<div class="empty">실행 중인 페이퍼 봇이 없습니다. '전략 · 백테스트'에서 만들 수 있습니다.</div>`;
  } else if (bottomTab === "ex") {
    const e = state.exchanges;
    if (!e) { el.innerHTML = `<div class="empty">불러오는 중…</div>`; return; }
    el.innerHTML = `<table><tr><th>거래소</th><th>시장</th><th>가격 ($)</th><th>원화 가격</th><th>바이낸스 선물 대비</th><th>김치 프리미엄</th><th>24h</th><th>펀딩비</th><th>24h 거래대금</th></tr>
      ${e.rows.map((r) => r.error ? `<tr><td>${r.exchange}</td><td>${r.market}</td><td colspan="7" class="muted" style="text-align:left">연결 실패</td></tr>` :
        `<tr><td>${r.exchange}</td><td class="dim">${r.market}</td><td>${px(r.price)}</td><td>${r.price_krw ? fmt(r.price_krw, 0) + "원" : "–"}</td>
        <td class="${cls(r.diff_pct)}">${r.diff_pct == null ? "–" : pct(r.diff_pct, 3)}</td><td class="${cls(r.kimchi_pct)}">${r.kimchi_pct == null ? "–" : pct(r.kimchi_pct)}</td>
        <td class="${cls(r.change_pct)}">${pct(r.change_pct)}</td><td class="${cls(r.funding_pct)}">${r.funding_pct == null ? "–" : r.funding_pct.toFixed(4) + "%"}</td>
        <td>$${big(r.volume_usd)}</td></tr>`).join("")}</table>
      <div class="help" style="padding:6px 10px">환율 ${e.fx_usdkrw ? fmt(e.fx_usdkrw, 1) + "원" : "–"} · 업비트 USDT ${e.usdt_krw ? fmt(e.usdt_krw, 0) + "원" : "–"} (테더 프리미엄 ${e.tether_premium_pct == null ? "–" : pct(e.tether_premium_pct)})${e.source === "synthetic" ? ' · <span class="accent">가상 데이터</span>' : ""}</div>`;
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
// 새 AI 분석 · 새 AI 진입 시그널이 나오면 차트의 'AI 시그널'을 다시 그린다
on("copilot", () => charts.forEach((c) => c.refreshAi?.()));
on("apsignals", (items) => {
  const syms = new Set((items || []).filter((x) => x.type === "ai_entry").map((x) => x.symbol));
  charts.forEach((c) => syms.has(c.symbol) && c.refreshAi?.());
});

async function loadBots() {
  try { bots = await api("/api/paper/bots"); } catch { return; }
  emit("bots", bots);
  if (bottomTab === "bots") renderBottom();
  if (charts[0]?.opts.overlays.bots) charts[0].refreshOverlays();
}

export function showOnChart(symbol, interval) {
  state.chartMode = "term"; state.interval = interval; state.overlays.bots = true;
  savePrefs(); renderTimeframes();
  emit("goto", "trade");
  setSymbol(symbol);
}

// ================================================================ 초기화
export function initTrade() {
  if (!["term", "tv", "macro"].includes(state.chartMode)) state.chartMode = "term";
  renderTimeframes();
  $("#macro-syms").innerHTML = MACRO.map(([s, l]) => `<button data-macro="${s}" class="${s === state.macro ? "on" : ""}">${l}</button>`).join("");
  renderWatchlist(); renderChart(); renderOrderPreview(); renderPriceAlerts();

  $("#chart-mode").onclick = (e) => { const m = e.target.dataset.mode; if (m) { state.chartMode = m; savePrefs(); renderChart(); } };
  $("#tfs").onclick = (e) => {
    const iv = e.target.dataset.iv;
    if (!iv) return;
    state.interval = iv; savePrefs(); renderTimeframes(); renderChart(); loadAnalysis(); copilotSymbolChanged();
  };
  $("#macro-syms").onclick = (e) => {
    const s = e.target.dataset.macro;
    if (!s) return;
    state.macro = s; savePrefs();
    $$("#macro-syms button").forEach((b) => b.classList.toggle("on", b.dataset.macro === s));
    renderChart();
  };
  $("#overlays").onclick = (e) => {
    const k = e.target.dataset.ov;
    if (!k) return;
    if (k === "patterns") {   // 차트 패턴 = 지표 하나를 켜고 끄는 단축 버튼
      const has = state.indicators.some((x) => x.key === "chartpat");
      state.indicators = has ? state.indicators.filter((x) => x.key !== "chartpat") : [...state.indicators, { key: "chartpat", params: {} }];
      savePrefs(); renderToolbar(); charts[0]?.setIndicators(state.indicators);
      if (!$("#ind-menu").hidden) indicatorPanel({ refresh: true });
      return;
    }
    state.overlays[k] = !state.overlays[k];
    savePrefs(); renderToolbar();
    if (k === "forecast") charts[0]?.setForecast(state.overlays.forecast ? state.forecast : null);
    else if (k === "ladder") charts[0]?.setLadder(state.overlays.ladder);
    else if (k === "countdown") charts.forEach((c) => { c.opts.overlays.countdown = state.overlays.countdown; c.countdown.update(); });
    else charts[0]?.setOverlay(k, state.overlays[k]);
    if (k === "scenario") charts[0]?.setScenario(state.overlays.scenario ? state.analysis?.scenarios?.[0] : null, state.analysis?.symbol);
  };
  $("#layouts").innerHTML = LAYOUT_LIST.map(([k, L]) => `<button data-layout="${k}" title="${L.name}">${layIcon(L)}<span>${L.name}</span></button>`).join("");
  renderToolbar();
  $("#lay-btn").onclick = (e) => {
    e.stopPropagation();
    const m = $("#layouts"), r = e.currentTarget.getBoundingClientRect();   // 툴바가 가로 스크롤이라 fixed 로 띄운다
    m.hidden = !m.hidden;
    Object.assign(m.style, { top: `${r.bottom + 4}px`, left: `${Math.max(8, r.right - 440)}px` });
  };
  document.addEventListener("click", (e) => { if (!e.target.closest(".lay-pick")) $("#layouts").hidden = true; });
  $("#layouts").onclick = (e) => { const k = e.target.closest("[data-layout]")?.dataset.layout; if (k) { state.layout = k; $("#layouts").hidden = true; savePrefs(); renderChart(); } };
  $("#term-grid").onchange = async (e) => {
    const i = +e.target.dataset.cell;
    if (!i) return;
    const k = e.target.dataset.k;
    if (k === "symbol") {
      const v = await lookup(e.target.value);
      e.target.value = v.replace(/USDT$/, "");
      state.multi[i - 1].symbol = v;
    } else state.multi[i - 1][k] = e.target.value;
    savePrefs();
    charts[i]?.load(state.multi[i - 1].symbol, state.multi[i - 1].interval).catch((err) => toast("차트 오류", err.message, "err"));
  };
  $("#draw-tools").onclick = (e) => {
    const t = e.target.dataset.draw;
    if (!t || !charts[0]) return;
    if (t === "clear") { charts[0].clearDrawings(); return; }
    const on_ = !e.target.classList.contains("on");
    $$("#draw-tools button").forEach((b) => b.classList.remove("on"));
    e.target.classList.toggle("on", on_);
    charts[0].setDrawMode(on_ ? t : null);
  };
  $("#ind-btn").onclick = indicatorPanel;
  $("#ind-menu").onclick = (e) => {
    e.stopPropagation();
    const add = e.target.closest("[data-add]")?.dataset.add, del = e.target.dataset.del;
    if (add) { state.indicators = [...state.indicators, { key: add, params: {} }]; applyIndicators(); }
    if (del != null) { state.indicators = state.indicators.filter((_, i) => i !== +del); applyIndicators(); }
    if (e.target.id === "ind-reset") { state.indicators = DEFAULT_INDICATORS; applyIndicators(); }
  };
  $("#ind-menu").onchange = (e) => {
    if (e.target.dataset.study) {
      const id = e.target.dataset.study;
      state.studies = e.target.checked ? [...state.studies, id] : state.studies.filter((s) => s !== id);
      savePrefs(); renderChart(); return;
    }
    const i = e.target.dataset.i, k = e.target.dataset.p;
    if (i == null) return;
    const v = Number(e.target.value);
    state.indicators = state.indicators.map((s, j) => j === +i ? { ...s, params: { ...s.params, [k]: Number.isNaN(v) ? e.target.value : v } } : s);
    savePrefs(); charts[0]?.setIndicators(state.indicators);
  };
  document.addEventListener("click", (e) => { if (!e.target.closest("#ind-menu")) $("#ind-menu").hidden = true; });
  $("#fs-btn").onclick = toggleFullscreen;
  document.addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() === "f" && !e.target.closest("input, textarea, select") && $("#v-trade").classList.contains("on")) toggleFullscreen();
    if (e.key === "Escape") { charts[0]?.setDrawMode(null); $$("#draw-tools button").forEach((b) => b.classList.remove("on")); }
  });

  $("#watchlist").onclick = (e) => { const r = e.target.closest("[data-sym]"); if (r) setSymbol(r.dataset.sym); };
  $("#watchlist").ondblclick = (e) => {
    const r = e.target.closest("[data-sym]");
    if (!r || r.dataset.sym === state.symbol) return;
    state.watch = state.watch.filter((s) => s !== r.dataset.sym); savePrefs(); renderWatchlist();
  };
  $("#wl-search").onkeydown = async (e) => {
    if (e.key !== "Enter" || !e.target.value.trim()) return;
    const q = e.target.value; e.target.value = "";
    setSymbol(await lookup(q));
  };
  $("#symbtn").onclick = () => $("#wl-search").focus();

  $("#side-tabs").onclick = (e) => {
    const t = e.target.closest("[data-t]")?.dataset.t;
    if (!t) return;
    $$("#side-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === t));
    $("#side-sc").hidden = t !== "sc"; $("#side-order").hidden = t !== "order"; $("#side-book").hidden = t !== "book"; $("#side-fc").hidden = t !== "fc"; $("#side-fpx").hidden = t !== "fpx";
    $("#side-ai").hidden = t !== "ai";
    if (t === "ai") showCopilot();
    if (t === "fpx") loadFpPanel();
    if (t === "book") loadBook();
  };
  $("#side").addEventListener("click", (e) => {
    const b = e.target.closest("[data-plan]");
    if (!b) return;
    const p = JSON.parse(b.dataset.plan);
    state.overlays.scenario = true; savePrefs(); renderToolbar();
    if (state.chartMode !== "term") { state.chartMode = "term"; renderChart(); }
    charts[0]?.setScenario({ title: p.k === "long" ? "롱 계획" : "숏 계획", entry: p.entry, stop: p.stop, targets: [p.take] }, state.symbol);
    toast("차트에 진입 계획을 표시했습니다", `${p.k === "long" ? "롱" : "숏"} ${px(p.entry)} · 손절 ${px(p.stop)} · 익절 ${px(p.take)}`);
  });
  $("#side-sc").onclick = (e) => {
    const b = e.target.closest("[data-sc]");
    if (b) {
      state.overlays.scenario = true; savePrefs();
      if (state.chartMode !== "term") { state.chartMode = "term"; renderChart(); }
      renderToolbar();
      charts[0]?.setScenario(state.analysis.scenarios[+b.dataset.sc], state.analysis.symbol);
    }
    if (e.target.id === "ai-comment") busy(e.target, () => loadAnalysis(true));
  };
  $$(".sidebtn button").forEach((b) => (b.onclick = () => {
    side = b.dataset.side;
    $$(".sidebtn button").forEach((x) => x.classList.toggle("on", x === b));
    renderOrderPreview();
  }));
  ["#o-margin", "#o-lev", "#o-sl", "#o-tp"].forEach((s) => ($(s).oninput = renderOrderPreview));
  on("tickers", renderOrderPreview);
  $("#o-submit").onclick = (e) => busy(e.target, async () => {
    const num = (id) => { const v = $(id).value; return v === "" ? null : Number(v); };
    await api("/api/paper/order", { method: "POST", body: { symbol: state.symbol, side, margin: num("#o-margin"),
      leverage: num("#o-lev"), stop_loss_pct: num("#o-sl"), take_profit_pct: num("#o-tp") } });
    toast(`${state.symbol} ${side === "long" ? "롱" : "숏"} 체결 (모의)`, "", side === "long" ? "up" : "err");
    loadAccount(); charts[0]?.refreshOverlays();
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
    const sv = e.target.dataset.save;
    if (sv) {
      const num = (sel) => { const v = $(sel).value; return v === "" ? null : Number(v); };
      busy(e.target, () => editPosition(sv, { stop: num(`[data-sl="${sv}"]`), take: num(`[data-tp="${sv}"]`) }));
      return;
    }
    const sym = e.target.dataset.close;
    if (sym) busy(e.target, async () => { await api(`/api/paper/close/${sym}`, { method: "POST" }); loadAccount(); charts[0]?.refreshOverlays(); });
    const bc = e.target.dataset.botchart;
    if (bc) { const [s, iv] = bc.split("|"); showOnChart(s, iv); }
    const ap = e.target.dataset.aipos;
    if (ap) { if (ap !== state.symbol) setSymbol(ap); $('#side-tabs [data-t="ai"]').click(); }
  };
  on("rechart", renderChart);

  pollTickers(); setInterval(pollTickers, 5000);
  pollDerivatives(); setInterval(pollDerivatives, 30_000); setInterval(tickFunding, 1000);
  pollSentiment(); setInterval(pollSentiment, 60_000);
  loadAnalysis();
  initCopilot({ afterTrade: () => { loadAccount(); charts[0]?.refreshOverlays(); } });
  loadAccount(); setInterval(loadAccount, 5000);
  loadBots(); setInterval(loadBots, 15_000);
  renderBottom();
}
