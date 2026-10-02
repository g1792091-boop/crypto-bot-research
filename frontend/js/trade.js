// 트레이드 화면 — 트레이딩뷰 방식 UI (자체 제작: 위 툴바 · 왼쪽 그리기 도구 · 오른쪽 위젯 패널 · 아래 패널 · 기간 바)
// 분석 전용: 모의 주문 · 포지션 · 계좌는 없다. AI 시그널 · 전략 시그널은 '가상 체결'로 성과만 잰다.
import { addPriceAlert, getPriceAlerts, removePriceAlert } from "./alerts.js";
import { TermChart, sbotLine } from "./chart.js";
import { copilotSymbolChanged, initCopilot, showCopilot } from "./copilot.js";
import {
  $, $$, INTERVALS, IV_LABEL, api, big, busy, cls, css, emit, esc, fmt, hhmm, mdhm, on, pct,
  px, savePrefs, state, toast,
} from "./core.js";
import { COLORS, Drawings, TOOLS } from "./draw.js";
import { renderKb } from "./kb.js";
import { DEFAULT_INDICATORS, GROUPS, INDICATORS } from "./ind.js";

state.indicators ||= DEFAULT_INDICATORS;
state.overlays ||= { heat: false, whales: false, bots: true, scenario: true, sr: true };
state.overlays.sr ??= true;
state.overlays.countdown ??= true;
state.overlays.forecast ??= true;
state.overlays.footprint ??= false;
delete state.overlays.rotation;
state.overlays.ladder ??= true;
state.overlays.ai ??= true;           // AI 진입 시그널
state.overlays.sbot ??= true;         // 시나리오 봇 진입·포지션
state.ctype ||= "candles";            // 차트 종류
state.scale ||= { mode: "normal", auto: true };
state.rightTab ||= "dock";            // 오른쪽 위젯 (기본: AI 상시 알림 · 채팅)
state.favIv ||= ["1m", "5m", "15m", "1h", "4h", "1d", "1w"];
const CTYPES = [["candles", "캔들", "▮"], ["hollow", "속 빈 캔들", "▯"], ["ha", "하이킨 아시", "◧"], ["bars", "바", "┤"],
  ["line", "라인", "∿"], ["area", "영역", "◭"], ["baseline", "베이스라인", "≋"]];
// 기간 버튼 (트레이딩뷰처럼 기간에 맞는 봉으로 바꾼 뒤 그 기간만 보여 줌)
const RANGES = [["1D", "1일", "5m", 86400], ["5D", "5일", "15m", 5 * 86400], ["1M", "1개월", "1h", 30 * 86400], ["3M", "3개월", "4h", 91 * 86400],
  ["6M", "6개월", "4h", 182 * 86400], ["YTD", "올해", "1d", null], ["1Y", "1년", "1d", 365 * 86400], ["5Y", "5년", "1w", 5 * 365 * 86400], ["ALL", "전체", "1M", 0]];
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
  } catch { state.tickerSource = null; emit("tickers", state.tickers); }   // 거래소 연결 안 됨 → 상태 표시에 반영
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
  $("#sym-name").textContent = state.symbol; $("#si-name").textContent = state.symbol;
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

// 위 툴바: 자주 쓰는 봉 + 나머지는 펼침 메뉴 (★ 로 자주 쓰는 봉 고르기)
function renderTimeframes() {
  const fav = state.favIv.filter((k) => IV_LABEL[k]);
  const cur = fav.includes(state.interval) ? "" : `<button data-iv="${state.interval}" class="on">${IV_LABEL[state.interval] || state.interval}</button>`;
  $("#tfs").innerHTML = fav.map((k) => `<button data-iv="${k}" class="${k === state.interval ? "on" : ""}">${shortIv(k)}</button>`).join("") + cur +
    `<div class="dd"><button class="tv-more" id="iv-more" title="다른 봉">▾</button><div class="dd-menu iv-menu" id="iv-menu" hidden>
      ${INTERVALS.map(([k, l]) => `<div class="dd-item ${k === state.interval ? "on" : ""}" data-iv="${k}"><span>${l}</span><button class="star ${fav.includes(k) ? "on" : ""}" data-fav="${k}" title="자주 쓰는 봉">★</button></div>`).join("")}</div></div>`;
}
const shortIv = (k) => ({ "1m": "1분", "3m": "3분", "5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시", "2h": "2시", "4h": "4시", "6h": "6시", "12h": "12시", "1d": "일", "3d": "3일", "1w": "주", "1M": "월", "1y": "년" }[k] || k);

function renderToolbar() {
  $$("#overlays button").forEach((b) => b.classList.toggle("on", b.dataset.ov === "patterns" ? state.indicators.some((x) => x.key === "chartpat") : !!state.overlays[b.dataset.ov]));
  $$("#layouts button").forEach((b) => b.classList.toggle("on", b.dataset.layout === state.layout));
  $("#lay-btn").innerHTML = `${layIcon(LAYOUTS[state.layout])}`;
  const ct = CTYPES.find((c) => c[0] === state.ctype) || CTYPES[0];
  $("#ctype-btn").innerHTML = `<span class="ct-ico">${ct[2]}</span><span>${ct[1]}</span>`;
  $("#ctype-menu").innerHTML = CTYPES.map(([k, l, ic]) => `<div class="dd-item ${k === state.ctype ? "on" : ""}" data-ctype="${k}"><span class="ct-ico">${ic}</span>${l}</div>`).join("");
  $$("#tv-foot [data-scale]").forEach((b) => b.classList.toggle("on", b.dataset.scale === "auto" ? state.scale.auto : state.scale.mode === b.dataset.scale));
  $$("#draw-tools [data-dt]").forEach((b) => b.classList.toggle("on", !!draw?.[{ magnet: "magnet", stay: "stay", lock: "locked", hide: "hidden" }[b.dataset.dt]]));
  $$("#draw-tools [data-draw]").forEach((b) => b.classList.toggle("on", (draw?.tool || "cursor") === b.dataset.draw));
}

let draw = null;   // 메인 차트의 그리기 도구
function renderChart() {
  renderToolbar();
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
        overlays: i ? { heat: false, whales: false, bots: true, scenario: false, sr: state.overlays.sr, countdown: state.overlays.countdown, ai: state.overlays.ai, sbot: state.overlays.sbot } : { ...state.overlays },
        onLoad: i ? null : () => { draw?.load(); renderTree(); },
        onLegend: i ? null : legendAction,
      }));
    });
    draw = new Drawings(charts[0], { onChange: () => { renderStyler(); renderTree(); renderToolbar(); } });
  }
  charts.forEach((c) => { c.ctype = state.ctype; c.setScale(state.scale); });
  charts[0]?.setLadder(!!state.overlays.ladder);
  charts.forEach((c, i) => c.load(i ? state.multi[i - 1].symbol : state.symbol, i ? state.multi[i - 1].interval : state.interval)
    .then(() => { if (!i && state.overlays.forecast && state.forecast) c.setForecast(state.forecast); if (!i && pendingRange != null) { c.showSeconds(pendingRange); pendingRange = null; } })
    .catch((e) => toast("차트 오류", e.message, "err")));
  if (state.analysis?.symbol === state.symbol) charts[0]?.setScenario(state.overlays.scenario ? state.analysis.scenarios[0] : null, state.analysis.symbol);
}
let pendingRange = null;

// 범례의 지표 버튼 (숨기기 · 설정 · 지우기)
function legendAction(act, i, btn) {
  if (!(i >= 0)) return;
  if (act === "hide") state.indicators = state.indicators.map((s, j) => j === i ? { ...s, hidden: !s.hidden } : s);
  else if (act === "del") state.indicators = state.indicators.filter((_, j) => j !== i);
  else if (act === "set") { indicatorPanel({ stopPropagation() {}, anchor: btn, focus: i }); return; }
  savePrefs(); charts[0]?.setIndicators(state.indicators); renderTree();
}

// 선택한 그림의 모양 바 (색 · 굵기 · 점선 · 잠금 · 삭제)
function renderStyler() {
  const d = draw?.selected(), el = $("#draw-style");
  if (!d) { el.hidden = true; return; }
  el.hidden = false;
  el.innerHTML = `<span class="muted">${esc(TOOLS[d.type]?.name || d.type)}</span>
    ${COLORS.map((c) => `<button class="sw ${d.color === c ? "on" : ""}" data-col="${c}" style="background:${c}" title="${c}"></button>`).join("")}
    <span class="tv-sep"></span>${[1, 2, 3, 4].map((w) => `<button class="${(d.width || 2) === w ? "on" : ""}" data-w="${w}" title="굵기 ${w}"><i style="height:${w}px"></i></button>`).join("")}
    <button class="${d.dash ? "on" : ""}" data-dash title="점선">┄</button>
    ${d.type === "text" ? `<button data-edit title="글자 바꾸기">✎</button>` : ""}
    <button class="${d.locked ? "on" : ""}" data-lk title="잠금">🔒</button><button data-rm title="삭제 (Delete)">🗑</button>`;
}

// 객체 트리: 그림 목록 + 지표 목록
function renderTree() {
  const el = $("#side-tree");
  if (!el || el.hidden) return;
  const ds = draw?.list() || [];
  el.innerHTML = `<div class="sub">그림 ${ds.length}개 <span class="muted">· ${esc(state.symbol)} (모든 봉에서 같이 보임)</span></div>
    ${ds.map((d) => `<div class="tree-row ${d.id === draw.sel ? "sel" : ""}" data-did="${d.id}"><span class="grow">${esc(d.name)}${d.text ? ` <span class="muted">${esc(d.text)}</span>` : ""}</span>
      <button class="flat sm" data-dhide="${d.id}" title="숨기기">${d.hidden ? "◌" : "◉"}</button><button class="flat sm" data-dlock="${d.id}" title="잠금">${d.locked ? "🔒" : "🔓"}</button><button class="flat sm" data-ddel="${d.id}" title="삭제">✕</button></div>`).join("") || '<div class="empty">왼쪽 도구로 그린 선 · 도형이 여기에 나옵니다.</div>'}
    <div class="sub">지표 ${state.indicators.length}개</div>
    ${state.indicators.map((s, i) => `<div class="tree-row"><span class="grow">${esc(INDICATORS[s.key]?.name || s.key)}</span>
      <button class="flat sm" data-ihide="${i}" title="숨기기">${s.hidden ? "◌" : "◉"}</button><button class="flat sm" data-idel="${i}" title="삭제">✕</button></div>`).join("")}
    <div class="help" style="padding:8px 10px">그림을 고르면 끌어서 옮기고 점을 끌어 모양을 바꿀 수 있습니다. Delete 삭제 · Ctrl+Z 되돌리기 · Esc 커서.</div>`;
}

// 지표 선택 패널
function indicatorPanel(e) {
  const m = $("#ind-menu");
  if (!m.hidden && !e.refresh && e.focus == null) { m.hidden = true; return; }
  const groups = Object.fromEntries(GROUPS.map((g) => [g, []]));
  Object.entries(INDICATORS).forEach(([k, d]) => (groups[d.group] ||= []).push([k, d]));
  const used = new Set(state.indicators.map((x) => x.key));
  m.innerHTML = `<div class="ind-panel">
    <div class="ind-list"><input id="ind-q" placeholder="지표 검색 (${Object.keys(INDICATORS).length}개 · 한글/영문)">${Object.entries(groups).filter(([, xs]) => xs.length).map(([g, xs]) => `<div class="sub" data-g="${esc(g)}">${g}</div>` +
      xs.map(([k, d]) => `<div class="ind-item" data-add="${k}" data-g="${esc(g)}" data-q="${esc(`${d.name} ${k} ${d.desc || ""}`.toLowerCase())}" title="${esc(d.desc || d.name)}">${esc(d.name)}${used.has(k) ? ' <span class="accent">✓</span>' : ""}</div>`).join("")).join("")}</div>
    <div class="ind-active"><div class="sub">적용된 지표 ${state.indicators.length}개 · 제한 없음</div>${state.indicators.map((s, i) => {
      const d = INDICATORS[s.key]; if (!d) return "";
      return `<div class="ind-row ${e.focus === i ? "focus" : ""}"><span class="grow">${esc(d.name)}</span>${Object.entries({ ...d.params, ...s.params }).map(([k, v]) =>
        `<input data-i="${i}" data-p="${k}" value="${v}" title="${k}" style="width:46px">`).join("")}<button class="x" data-del="${i}">✕</button></div>`;
    }).join("")}<div class="row" style="margin-top:8px"><button class="sm" id="ind-reset">기본값으로</button></div></div></div>`;
  const r = (e.anchor || $("#ind-btn")).getBoundingClientRect();
  m.style.left = `${Math.max(8, Math.min(r.left, innerWidth - 640))}px`; m.style.top = `${Math.min(r.bottom + 4, innerHeight - 420)}px`;
  m.hidden = false;
  e.stopPropagation?.();
  $("#ind-q").oninput = (ev) => {
    const q = ev.target.value.trim().toLowerCase().replace(/\s+/g, "");
    $$(".ind-item", m).forEach((it) => (it.hidden = !!q && !it.dataset.q.replace(/\s+/g, "").includes(q)));
    $$(".ind-list .sub", m).forEach((h) => (h.hidden = !$$(`.ind-item[data-g="${h.dataset.g}"]`, m).some((it) => !it.hidden)));
  };
  if (!e.refresh && e.focus == null) $("#ind-q").focus();
  if (e.focus != null) m.querySelector(".ind-row.focus input")?.focus();
}
function applyIndicators() {
  savePrefs();
  charts[0]?.setIndicators(state.indicators);
  indicatorPanel({ refresh: true });
  renderTree();
}

function toggleFullscreen() {
  const el = $("#tv");
  if (document.fullscreenElement) document.exitFullscreen();
  else el.requestFullscreen?.().catch(() => toast("전체 화면을 지원하지 않는 브라우저입니다"));
}

// 오른쪽 위젯 패널 (트레이딩뷰의 오른쪽 아이콘 줄)
const PANELS = ["watch", "dock", "ai", "sc", "fc", "fpx", "book", "alerts", "kb", "tree"];
function showPanel(t, toggle = false) {
  const tv = $("#tv");
  if (toggle && state.rightTab === t && !tv.classList.contains("right-off")) { tv.classList.add("right-off"); state.rightOff = true; savePrefs(); setTimeout(() => window.dispatchEvent(new Event("resize")), 0); return; }
  tv.classList.remove("right-off"); state.rightOff = false;
  state.rightTab = t; savePrefs();
  $$("#side-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === t));
  PANELS.forEach((k) => { const el = $(`#side-${k}`); if (el) el.hidden = k !== t; });
  if (t === "ai") showCopilot();
  if (t === "fpx") loadFpPanel();
  if (t === "book") loadBook();
  if (t === "tree") renderTree();
  if (t === "kb") renderKb($("#side-kb"), state.symbol, state.interval);
  if (t === "dock") emit("dockshown");
  setTimeout(() => window.dispatchEvent(new Event("resize")), 0);
}

// 심볼 검색 창
let symList = null;
async function openSymbols(q = "") {
  $("#sym-modal").hidden = false;
  const inp = $("#sym-q");
  inp.value = q; inp.focus();
  if (!symList) {
    try { symList = (await api("/api/market/heatmap?limit=400")).items; } catch { symList = []; }
  }
  renderSymbols();
}
function renderSymbols() {
  const q = $("#sym-q").value.trim().toUpperCase();
  const rows = (symList || []).filter((x) => !q || x.symbol.includes(q)).slice(0, 80);
  $("#sym-list").innerHTML = rows.map((x) => `<div class="sym-row" data-pick="${x.symbol}"><b>${x.symbol.replace(/USDT$/, "")}</b><span class="muted">${x.symbol} · 무기한</span><div class="grow"></div>
    <span>${px(x.price)}</span><span class="${cls(x.change_pct)}" style="width:64px;text-align:right">${pct(x.change_pct)}</span><span class="muted" style="width:70px;text-align:right">$${big(x.quote_volume)}</span></div>`).join("")
    || `<div class="empty">목록에 없으면 Enter — '이더', '페페' 같은 한글 이름도 찾아 줍니다.</div>`;
}
function closeSymbols() { $("#sym-modal").hidden = true; }

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
      ${s.learned ? `<div class="learn" title="시나리오 진입 봇이 과거·실시간 결과로 배운 값 (체결된 것 기준)">배운 실제 적중률 <b>${s.learned.win}%</b> · 평균 <b class="${s.learned.avg_r > 0 ? "up" : "down"}">${s.learned.avg_r > 0 ? "+" : ""}${s.learned.avg_r}R</b> <span class="muted">(${s.learned.n}건${s.learned.n < 20 ? " · 적어서 전체 평균 반영" : ""})</span></div>`
        : a.bot ? `<div class="learn muted">배운 실제 적중률: ${a.bot.learning ? "학습 중… " + esc(a.bot.progress || "") : "아직 이 시나리오 표본 없음 (학습이 끝나면 표시)"}</div>` : ""}
      ${(a.bot?.orders || []).filter((o) => o.title === s.title || (s.key === "range" && o.title === "박스권 양방향")).map((o) => `<div class="botst">🤖 진입 봇 ${o.interval} ${o.side > 0 ? "롱" : "숏"} ${o.lev ? o.lev + "배 " : ""}${o.status === "open" ? `보유 중${o.roe_pct != null ? ` <b class="${o.roe_pct >= 0 ? "up" : "down"}">${o.roe_pct > 0 ? "+" : ""}${o.roe_pct}%</b>` : ""}` : "주문 대기"} @ ${px(o.entry)}</div>`).join("")}
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
  $("#side-sc-body").innerHTML = `
    ${a.ai_comment ? `<div class="ai">${esc(a.ai_comment)}</div>` : ""}
    ${state.status?.llm ? `<div style="padding:8px 12px;border-bottom:1px solid var(--line)"><button class="sm" id="ai-comment">${a.ai_comment ? "AI 코멘트 새로고침" : "AI 코멘트 받기"}</button></div>` : ""}
    ${a.bot ? `<div class="sbot-st">${sbotLine(a.bot, a.interval)}</div>` : ""}
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

function renderPriceAlerts() {
  $("#pa-list").innerHTML = getPriceAlerts().map((a, i) => `<div class="lv" style="padding:3px 0"><span>${a.symbol.replace("USDT", "")} ${a.dir === "up" ? "≥" : "≤"} <span class="px">${px(a.price)}</span></span>
    <button class="x" data-pa="${i}">✕</button></div>`).join("") || `<div class="muted">등록된 알림 없음</div>`;
}

// ================================================================ 아래 패널
let bottomTab = state.bottomTab && ["aisig", "bots", "scan", "ex", "news", "alerts"].includes(state.bottomTab) ? state.bottomTab : "aisig";
let bots = [], aibot = null, scanItems = null;

// AI 시그널 성과 (AI 진입 시그널을 그대로 따랐다면 — 가상 체결로 계산) — 아래 패널 · 차트 옆 AI 패널에서 씀
export async function loadAiBot() {
  try { aibot = await api("/api/aibot"); } catch { return; }
  emit("aibot", aibot);
  if (bottomTab === "aisig") renderBottom();
}
const sg = (v) => (v > 0 ? "+" : "");
const AIOUT = { take: "익절", stop: "손절", expired: "미체결", open: "진행 중", waiting: "진입 대기", unknown: "-" };
const hold = (m) => m == null ? "–" : m < 120 ? `${m}분` : `${Math.round(m / 60 * 10) / 10}시간`;

function aibotHtml() {
  if (!aibot) return `<div class="muted" style="padding:8px">불러오는 중…</div>`;
  const s = aibot.stats, set = aibot.settings;
  const st = (k, v, c = "") => `<div class="stat"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`;
  const who = (e) => (e && e !== "rules" ? "AI" : "규칙");
  const openRows = aibot.open.map((t) => `<tr><td>${mdhm(t.entry_time)} 진입</td><td>${t.symbol.replace("USDT", "")} <span class="muted">${IV_LABEL[t.interval] || t.interval}</span></td>
    <td class="${t.side === "long" ? "up" : "down"}">${t.side === "long" ? "롱" : "숏"}</td><td>${px(t.entry)} → <span class="muted">지금</span> ${px(t.mark)}</td>
    <td class="accent">진행 중</td><td class="${cls(t.roe_pct)}">${pct(t.roe_pct)}</td><td class="${cls(t.r)}">${sg(t.r)}${t.r}R</td>
    <td>${hold(t.held_min)}</td><td>${t.confidence ?? "–"}% · ${who(t.engine)}</td>
    <td class="muted" style="font-size:11px">손절 ${px(t.stop)} · 익절 ${px(t.take)}</td><td><button class="sm" data-botchart="${t.symbol}|${t.interval}">차트</button></td></tr>`).join("");
  const rows = aibot.trades.slice().reverse().map((t) => `<tr><td>${mdhm(t.exit_time)}</td><td>${t.symbol.replace("USDT", "")} <span class="muted">${IV_LABEL[t.interval] || t.interval}</span></td>
    <td class="${t.side === "long" ? "up" : "down"}">${t.side === "long" ? "롱" : "숏"}</td><td>${px(t.entry)} → ${px(t.exit)}</td>
    <td class="${t.pnl > 0 ? "up" : "down"}">${t.label}</td><td class="${cls(t.roe_pct)}">${pct(t.roe_pct)}</td><td class="${cls(t.r)}">${sg(t.r)}${t.r}R</td>
    <td>${hold(t.held_min)}</td><td>${t.confidence ?? "–"}% · ${who(t.engine)}</td>
    <td class="muted" style="font-size:11px">${esc((t.reason || "").slice(0, 60))}</td><td><button class="sm" data-botchart="${t.symbol}|${t.interval}">차트</button></td></tr>`).join("");
  const sigs = aibot.signals.slice(-40).reverse().map((x) => `<tr><td>${mdhm(x.created)}</td><td>${x.symbol.replace("USDT", "")} <span class="muted">${IV_LABEL[x.interval] || x.interval}</span></td>
    <td class="${x.side === "long" ? "up" : "down"}">${x.side === "long" ? "롱" : "숏"}</td><td>진입 ${px(x.entry)} · 손절 ${px(x.stop)} · 익절 ${px(x.take)}</td>
    <td>${x.skip ? `<span class="muted" title="${esc(x.skip)}">건너뜀</span> ` : ""}${AIOUT[x.outcome?.status] || ""}</td>
    <td>${x.confidence ?? "–"}% · ${who(x.engine)}</td><td class="muted" style="font-size:11px">${esc((x.trigger || x.headline || "").slice(0, 70))}</td>
    <td><button class="sm" data-botchart="${x.symbol}|${x.interval}">차트</button></td></tr>`).join("");
  return `<div class="stats aib-stats">
      ${st("가상 누적 수익률", pct(s.return_pct), cls(s.return_pct))}${st("적중률", s.win_rate != null ? `${s.win_rate}% <small class="muted">${s.wins}익절 ${s.losses}손절</small>` : "–")}
      ${st("평균 R", s.avg_r != null ? `${sg(s.avg_r)}${s.avg_r}R` : "–", cls(s.avg_r))}${st("손익비", s.profit_factor ?? "–")}
      ${st("거래당 평균", s.avg_roe_pct != null ? pct(s.avg_roe_pct) : "–", cls(s.avg_roe_pct))}${st("최대 낙폭", s.max_drawdown_pct ? `-${s.max_drawdown_pct}%` : "0%", s.max_drawdown_pct ? "down" : "")}
      ${st("최고 / 최저", s.best != null ? `${pct(s.best, 1)} / ${pct(s.worst, 1)}` : "–")}${st("평균 보유", hold(s.avg_hold_min))}
      ${st("진행 중", `${s.open}개`)}${st("채점된 시그널", `${s.trades}개`)}</div>
    <div class="help" style="padding:4px 10px">AI 진입 시그널(차트의 보라 표시)을 그대로 따랐다면 어땠는지 <b>가상으로</b> 채점합니다 — 진입가에 닿으면 체결, 손절·익절 중 먼저 닿는 쪽(한 봉에 둘 다면 손절), 12봉 안에 안 닿으면 미체결.
      수익률은 거래당 증거금 ${set.position_pct}% · ${set.leverage}배 · 수수료 ${set.fee_pct}%×2 를 가정한 값입니다. 실제 주문은 하지 않습니다.</div>
    <table><tr><th>시각</th><th>코인</th><th>방향</th><th>진입 → 청산</th><th>결과</th><th>수익률</th><th>R</th><th>보유</th><th>확신·엔진</th><th>근거</th><th></th></tr>
      ${openRows}${rows || (openRows ? "" : `<tr><td colspan="11" class="muted">아직 채점된 시그널이 없습니다. AI 진입 시그널이 나오고 진입가에 닿으면 여기에 쌓입니다.</td></tr>`)}</table>
    ${sigs ? `<div class="sub" style="padding:8px 10px 2px">AI 진입 시그널 기록 <span class="muted">(최근 40개)</span></div>
      <table><tr><th>시각</th><th>코인</th><th>방향</th><th>진입 · 손절 · 익절</th><th>결과</th><th>확신·엔진</th><th>조건</th><th></th></tr>${sigs}</table>` : ""}`;
}

function strategyHtml() {
  return bots.length ? `<table><tr><th>전략</th><th>종목</th><th>상태</th><th>가상 누적</th><th>지금 신호</th><th>신호 수</th><th>자동 개선</th><th></th></tr>
      ${bots.map((b) => { const a = b.account, p = a.position, r = (a.equity / b.initial_equity - 1) * 100;
        return `<tr><td style="text-align:left">${esc(b.name)}</td><td>${b.symbol.replace("USDT", "")} ${IV_LABEL[b.interval] || b.interval}</td><td class="${b.running ? "up" : "muted"}">${b.running ? "추적 중" : "멈춤"}</td>
        <td class="${cls(r)}">${pct(r)}</td>
        <td>${p ? `<span class="${p.side === "long" ? "up" : "down"}">${p.side === "long" ? "롱" : "숏"} 신호</span> ${px(p.entry_price)}` : '<span class="muted">대기</span>'}</td><td>${a.trades.length}</td>
        <td class="${b.auto_improve ? "accent" : "muted"}">${b.auto_improve ? `켜짐 (${b.improve_every}건마다)` : "꺼짐"}</td>
        <td><button class="sm" data-botchart="${b.symbol}|${b.interval}">차트에서 보기</button></td></tr>`; }).join("")}</table>
      <div class="help" style="padding:6px 10px">오토파일럿이 과거 3구간 검증을 통과한 매매법과 직접 추가한 매매법을 실시간 봉으로 계속 추적합니다(포워드 테스트 · 가상). 실제 주문은 하지 않습니다.</div>`
    : `<div class="empty">추적 중인 전략 시그널이 없습니다. 오토파일럿이 검증된 매매법을 찾으면 여기에 추가됩니다.</div>`;
}

async function loadScan() {
  try { scanItems = (await api("/api/scanner/signals?limit=150")).items; } catch { scanItems = []; }
  if (bottomTab === "scan") renderBottom();
}
function scanHtml() {
  if (!scanItems) { loadScan(); return `<div class="muted" style="padding:8px">불러오는 중…</div>`; }
  return scanItems.length ? `<table><tr><th>시각</th><th>코인</th><th>봉</th><th>신호</th><th>방향</th><th>강도</th><th style="text-align:left">내용</th><th></th></tr>
    ${scanItems.map((x) => `<tr><td>${hhmm(x.created)}</td><td><b>${x.symbol.replace("USDT", "")}</b></td><td>${IV_LABEL[x.interval] || x.interval}</td><td>${esc(x.label)}</td>
      <td class="${x.dir === "long" ? "up" : x.dir === "short" ? "down" : ""}">${x.dir === "long" ? "롱" : x.dir === "short" ? "숏" : "–"}</td><td>${"●".repeat(x.strength || 1)}</td>
      <td style="text-align:left">${esc(x.text)}${x.ai ? `<div class="aa-sc">🤖 ${esc(x.ai)}</div>` : ""}</td><td><button class="sm" data-botchart="${x.symbol}|${x.interval}">차트</button></td></tr>`).join("")}</table>`
    : `<div class="empty">최근 신호가 없습니다. 퀀트 → 시그널 스캐너에서 코인 · 봉 · 신호 종류를 고를 수 있습니다.</div>`;
}

function renderBottom() {
  const el = $("#bottom-body");
  $$("#bot-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === bottomTab));
  if (bottomTab === "aisig") el.innerHTML = aibotHtml();
  else if (bottomTab === "bots") el.innerHTML = strategyHtml();
  else if (bottomTab === "scan") el.innerHTML = scanHtml();
  else if (bottomTab === "ex") {
    const e = state.exchanges;
    if (!e) { el.innerHTML = `<div class="empty">불러오는 중…</div>`; return; }
    el.innerHTML = `<table><tr><th>거래소</th><th>시장</th><th>가격 ($)</th><th>원화 가격</th><th>바이낸스 선물 대비</th><th>김치 프리미엄</th><th>24h</th><th>펀딩비</th><th>24h 거래대금</th></tr>
      ${e.rows.map((r) => r.error ? `<tr><td>${r.exchange}</td><td>${r.market}</td><td colspan="7" class="muted" style="text-align:left">연결 실패</td></tr>` :
        `<tr><td>${r.exchange}</td><td class="dim">${r.market}</td><td>${px(r.price)}</td><td>${r.price_krw ? fmt(r.price_krw, 0) + "원" : "–"}</td>
        <td class="${cls(r.diff_pct)}">${r.diff_pct == null ? "–" : pct(r.diff_pct, 3)}</td><td class="${cls(r.kimchi_pct)}">${r.kimchi_pct == null ? "–" : pct(r.kimchi_pct)}</td>
        <td class="${cls(r.change_pct)}">${pct(r.change_pct)}</td><td class="${cls(r.funding_pct)}">${r.funding_pct == null ? "–" : r.funding_pct.toFixed(4) + "%"}</td>
        <td>$${big(r.volume_usd)}</td></tr>`).join("")}</table>
      <div class="help" style="padding:6px 10px">환율 ${e.fx_usdkrw ? fmt(e.fx_usdkrw, 1) + "원" : "–"} · 업비트 USDT ${e.usdt_krw ? fmt(e.usdt_krw, 0) + "원" : "–"} (테더 프리미엄 ${e.tether_premium_pct == null ? "–" : pct(e.tether_premium_pct)})</div>`;
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
// 시나리오 봇 주문·포지션 실시간 손익 (5초마다 · 화면이 보일 때만)
setInterval(() => {
  if (document.hidden || !document.querySelector("#v-trade.on")) return;
  charts.forEach((c, i) => c.refreshSbot?.().then(() => {        // 시나리오 패널의 봇 상태도 같이 갱신
    const el = document.querySelector(".sbot-st");
    if (!i && el && c.sbot?.symbol === c.symbol) el.innerHTML = sbotLine(c.sbot, c.interval);
  }));
}, 5000);
on("apsignals", (items) => {
  const syms = new Set((items || []).filter((x) => x.type === "ai_entry" || x.type === "aibot").map((x) => x.symbol));
  if (syms.size) loadAiBot();
  charts.forEach((c) => syms.has(c.symbol) && c.refreshAi?.());
});

async function loadBots() {
  try { bots = await api("/api/paper/bots"); } catch { return; }
  emit("bots", bots);
  if (bottomTab === "bots") renderBottom();
  if (charts[0]?.opts.overlays.bots) charts[0].refreshOverlays();
}

export function showOnChart(symbol, interval) {
  if (interval) state.interval = interval;
  state.overlays.bots = true; state.overlays.ai = true;
  savePrefs(); renderTimeframes();
  emit("goto", "trade");
  setSymbol(symbol);
}

// ================================================================ 초기화
function tickClock() {
  const d = new Date(), z = (n) => String(n).padStart(2, "0"), off = -d.getTimezoneOffset() / 60;
  $("#tv-clock").textContent = `${z(d.getHours())}:${z(d.getMinutes())}:${z(d.getSeconds())} (UTC${off >= 0 ? "+" : ""}${off})`;
}

export function initTrade() {
  renderTimeframes();
  $("#tv-ranges").innerHTML = RANGES.map(([k, l]) => `<button data-rng="${k}" title="${l}">${k}</button>`).join("");
  renderWatchlist(); renderChart(); renderPriceAlerts();
  if (state.rightOff) $("#tv").classList.add("right-off");
  if (state.botOff) $("#tv").classList.add("bot-off");
  showPanel(PANELS.includes(state.rightTab) ? state.rightTab : "dock");
  if (state.rightOff) $("#tv").classList.add("right-off");

  // 봉 (자주 쓰는 봉 + 펼침 메뉴 + ★)
  $("#tfs").onclick = (e) => {
    const fav = e.target.closest("[data-fav]");
    if (fav) {
      e.stopPropagation();
      const k = fav.dataset.fav;
      state.favIv = state.favIv.includes(k) ? state.favIv.filter((x) => x !== k) : INTERVALS.map(([x]) => x).filter((x) => x === k || state.favIv.includes(x));
      savePrefs(); renderTimeframes(); $("#iv-menu").hidden = false; return;
    }
    if (e.target.id === "iv-more") { e.stopPropagation(); $("#iv-menu").hidden = !$("#iv-menu").hidden; return; }
    const iv = e.target.closest("[data-iv]")?.dataset.iv;
    if (!iv) return;
    state.interval = iv; savePrefs(); renderTimeframes(); renderChart(); loadAnalysis(); copilotSymbolChanged();
  };
  // 차트 종류
  $("#ctype-btn").onclick = (e) => { e.stopPropagation(); $("#ctype-menu").hidden = !$("#ctype-menu").hidden; };
  $("#ctype-menu").onclick = (e) => {
    const k = e.target.closest("[data-ctype]")?.dataset.ctype;
    if (!k) return;
    state.ctype = k; savePrefs(); $("#ctype-menu").hidden = true;
    charts.forEach((c) => c.setChartType(k)); renderToolbar();
  };
  // 오버레이 메뉴
  $("#ov-btn").onclick = (e) => { e.stopPropagation(); $("#overlays").hidden = !$("#overlays").hidden; };
  $("#overlays").onclick = (e) => {
    e.stopPropagation();
    const k = e.target.dataset.ov;
    if (!k) return;
    if (k === "patterns") {   // 차트 패턴 = 지표 하나를 켜고 끄는 단축 버튼
      const has = state.indicators.some((x) => x.key === "chartpat");
      state.indicators = has ? state.indicators.filter((x) => x.key !== "chartpat") : [...state.indicators, { key: "chartpat", params: {} }];
      savePrefs(); renderToolbar(); charts[0]?.setIndicators(state.indicators);
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
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".dd")) $$(".dd-menu").forEach((m) => (m.hidden = true));
    if (!e.target.closest(".lay-pick")) $("#layouts").hidden = true;
    if (!e.target.closest("#ind-menu")) $("#ind-menu").hidden = true;
  });
  // 분할
  $("#layouts").innerHTML = LAYOUT_LIST.map(([k, L]) => `<button data-layout="${k}" title="${L.name}">${layIcon(L)}<span>${L.name}</span></button>`).join("");
  renderToolbar();
  $("#lay-btn").onclick = (e) => {
    e.stopPropagation();
    const m = $("#layouts"), r = e.currentTarget.getBoundingClientRect();
    m.hidden = !m.hidden;
    Object.assign(m.style, { top: `${r.bottom + 4}px`, left: `${Math.max(8, Math.min(r.left, innerWidth - 450))}px` });
  };
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
  // 왼쪽 그리기 도구
  $("#draw-tools").onclick = (e) => {
    const b = e.target.closest("button");
    if (!b || !draw) return;
    if (b.dataset.draw) { draw.setTool(draw.tool === b.dataset.draw && b.dataset.draw !== "cursor" ? "cursor" : b.dataset.draw); renderToolbar(); return; }
    const t = b.dataset.dt;
    if (t === "magnet") draw.magnet = !draw.magnet;
    else if (t === "stay") draw.stay = !draw.stay;
    else if (t === "lock") draw.locked = !draw.locked;
    else if (t === "hide") { draw.hidden = !draw.hidden; draw.layer.update(); }
    else if (t === "clear" && confirm(`${state.symbol} 에 그린 그림을 모두 지울까요? (Ctrl+Z 로 되돌릴 수 있음)`)) draw.clear();
    renderToolbar();
  };
  $("#undo-btn").onclick = () => draw?.doUndo();
  $("#redo-btn").onclick = () => draw?.doRedo();
  $("#draw-style").onclick = (e) => {
    const b = e.target.closest("button");
    if (!b || !draw) return;
    if (b.dataset.col) draw.style({ color: b.dataset.col });
    else if (b.dataset.w) draw.style({ width: +b.dataset.w });
    else if ("dash" in b.dataset) draw.style({ dash: !draw.selected()?.dash });
    else if ("lk" in b.dataset) draw.style({ locked: !draw.selected()?.locked });
    else if ("rm" in b.dataset) draw.remove(draw.sel);
    else if ("edit" in b.dataset) { const s = prompt("텍스트", draw.selected()?.text || ""); if (s != null) draw.style({ text: s }); }
    renderStyler();
  };
  $("#side-tree").onclick = (e) => {
    const b = e.target.closest("button"), row = e.target.closest("[data-did]");
    if (b?.dataset.dhide) draw.toggle(b.dataset.dhide, "hidden");
    else if (b?.dataset.dlock) draw.toggle(b.dataset.dlock, "locked");
    else if (b?.dataset.ddel) draw.remove(b.dataset.ddel);
    else if (b?.dataset.ihide != null) legendAction("hide", +b.dataset.ihide);
    else if (b?.dataset.idel != null) legendAction("del", +b.dataset.idel);
    else if (row) draw.select(row.dataset.did);
    renderTree();
  };
  // 아래 기간 바 · 가격축
  $("#tv-foot").onclick = (e) => {
    const r = e.target.closest("[data-rng]")?.dataset.rng, sc = e.target.closest("[data-scale]")?.dataset.scale;
    if (r) {
      const [, , iv, sec] = RANGES.find((x) => x[0] === r);
      const secs = r === "YTD" ? Math.floor(Date.now() / 1000 - new Date(new Date().getFullYear(), 0, 1).getTime() / 1000) : sec;
      if (iv !== state.interval) { state.interval = iv; savePrefs(); renderTimeframes(); pendingRange = secs; renderChart(); loadAnalysis(); copilotSymbolChanged(); }
      else charts[0]?.showSeconds(secs);
      return;
    }
    if (sc === "auto") state.scale.auto = !state.scale.auto;
    else if (sc) state.scale.mode = state.scale.mode === sc ? "normal" : sc;
    if (sc) { savePrefs(); charts.forEach((c) => c.setScale(state.scale)); renderToolbar(); }
  };
  tickClock(); setInterval(tickClock, 1000);
  // 지표
  $("#ind-btn").onclick = indicatorPanel;
  $("#ind-menu").onclick = (e) => {
    e.stopPropagation();
    const add = e.target.closest("[data-add]")?.dataset.add, del = e.target.dataset.del;
    if (add) { state.indicators = [...state.indicators, { key: add, params: {} }]; applyIndicators(); }
    if (del != null) { state.indicators = state.indicators.filter((_, i) => i !== +del); applyIndicators(); }
    if (e.target.id === "ind-reset") { state.indicators = DEFAULT_INDICATORS; applyIndicators(); }
  };
  $("#ind-menu").onchange = (e) => {
    const i = e.target.dataset.i, k = e.target.dataset.p;
    if (i == null) return;
    const v = Number(e.target.value);
    state.indicators = state.indicators.map((s, j) => j === +i ? { ...s, params: { ...s.params, [k]: Number.isNaN(v) ? e.target.value : v } } : s);
    savePrefs(); charts[0]?.setIndicators(state.indicators);
  };
  $("#fs-btn").onclick = toggleFullscreen;
  $("#shot-btn").onclick = () => {
    const cv = charts[0]?.screenshot();
    if (!cv) return;
    const a = document.createElement("a");
    a.href = cv.toDataURL("image/png");
    a.download = `${state.symbol}_${state.interval}_${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "")}.png`;
    a.click();
    toast("스크린샷을 저장했습니다", a.download);
  };
  $("#alert-btn").onclick = () => {
    const p = state.tickers[state.symbol]?.price;
    if (!p) return toast("가격을 아직 받지 못했습니다");
    showPanel("alerts");
    $("#pa-price").value = p; $("#pa-price").focus(); $("#pa-price").select();
  };
  // 심볼 검색
  $("#symbtn").onclick = () => openSymbols();
  $("#sym-close").onclick = closeSymbols;
  $("#sym-modal").onclick = (e) => { if (e.target.id === "sym-modal") closeSymbols(); };
  $("#sym-q").oninput = renderSymbols;
  $("#sym-q").onkeydown = async (e) => {
    if (e.key === "Escape") closeSymbols();
    if (e.key !== "Enter" || e.isComposing) return;
    const first = $("#sym-list [data-pick]");
    const q = e.target.value.trim();
    closeSymbols();
    setSymbol(first && q && first.dataset.pick.startsWith(q.toUpperCase()) ? first.dataset.pick : await lookup(q || state.symbol));
  };
  $("#sym-list").onclick = (e) => { const r = e.target.closest("[data-pick]"); if (r) { closeSymbols(); setSymbol(r.dataset.pick); } };
  // 단축키 (트레이딩뷰처럼)
  document.addEventListener("keydown", (e) => {
    if (!$("#v-trade").classList.contains("on") || e.target.closest("input, textarea, select") || !$("#sym-modal").hidden) return;
    const k = e.key;
    if (k.toLowerCase() === "f" && !e.ctrlKey && !e.metaKey && !e.altKey) { toggleFullscreen(); return; }
    if (k === "/") { e.preventDefault(); indicatorPanel({ stopPropagation() {} }); return; }
    if (e.altKey) {
      const t = { t: "trend", h: "hline", v: "vline", f: "fib", r: "rect", l: "long", s: "short" }[k.toLowerCase()];
      if (t && draw) { e.preventDefault(); draw.setTool(t); renderToolbar(); }
      return;
    }
    if (!e.ctrlKey && !e.metaKey && /^[a-zA-Z0-9가-힣]$/.test(k)) { e.preventDefault(); openSymbols(k); }   // 아무 글자나 → 심볼 검색
  });

  // 관심 종목
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

  // 오른쪽 위젯
  $("#side-tabs").onclick = (e) => { const t = e.target.closest("[data-t]")?.dataset.t; if (t) showPanel(t, true); };
  $("#side").addEventListener("click", (e) => {
    const b = e.target.closest("[data-plan]");
    if (!b) return;
    const p = JSON.parse(b.dataset.plan);
    state.overlays.scenario = true; savePrefs(); renderToolbar();
    charts[0]?.setScenario({ title: p.k === "long" ? "롱 계획" : "숏 계획", entry: p.entry, stop: p.stop, targets: [p.take] }, state.symbol);
    toast("차트에 진입 계획을 표시했습니다", `${p.k === "long" ? "롱" : "숏"} ${px(p.entry)} · 손절 ${px(p.stop)} · 익절 ${px(p.take)}`);
  });
  $("#side-sc").onclick = (e) => {
    const b = e.target.closest("[data-sc]");
    if (b) {
      state.overlays.scenario = true; savePrefs(); renderToolbar();
      charts[0]?.setScenario(state.analysis.scenarios[+b.dataset.sc], state.analysis.symbol);
    }
    if (e.target.id === "ai-comment") busy(e.target, () => loadAnalysis(true));
  };
  $("#pa-add").onclick = () => { addPriceAlert(state.symbol, +$("#pa-price").value); $("#pa-price").value = ""; };
  $("#pa-list").onclick = (e) => { const i = e.target.dataset.pa; if (i != null) removePriceAlert(+i); };

  // 아래 패널
  $("#bot-tabs").onclick = (e) => {
    const t = e.target.dataset.t;
    if (!t) return;
    bottomTab = t; state.bottomTab = t; savePrefs();
    if ($("#tv").classList.contains("bot-off")) { $("#tv").classList.remove("bot-off"); state.botOff = false; savePrefs(); }
    if (t === "scan") loadScan();
    renderBottom();
  };
  $("#bot-fold").onclick = () => {
    const off = $("#tv").classList.toggle("bot-off");
    state.botOff = off; savePrefs();
    $("#bot-fold").textContent = off ? "▴" : "▾";
    setTimeout(() => window.dispatchEvent(new Event("resize")), 0);
  };
  $("#bot-fold").textContent = state.botOff ? "▴" : "▾";
  $("#bottom-body").onclick = (e) => {
    const bc = e.target.dataset.botchart;
    if (bc) { const [s, iv] = bc.split("|"); showOnChart(s, iv); }
  };
  on("rechart", renderChart);

  pollTickers(); setInterval(pollTickers, 5000);
  pollDerivatives(); setInterval(pollDerivatives, 30_000); setInterval(tickFunding, 1000);
  pollSentiment(); setInterval(pollSentiment, 60_000);
  loadAnalysis();
  initCopilot({});
  loadBots(); setInterval(loadBots, 15_000);
  loadAiBot(); setInterval(() => !document.hidden && loadAiBot(), 20_000);
  setInterval(() => bottomTab === "scan" && !document.hidden && loadScan(), 30_000);
  renderBottom();
}
