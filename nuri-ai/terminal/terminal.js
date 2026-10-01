// 누리 차트 터미널 — 트레이딩뷰 방식 분석 화면 (분석 전용: 주문 버튼 없음)
// 사용: import { openTerminal, closeTerminal } from "./terminal/terminal.js";
//       openTerminal({market: "BTCUSDT", exchange: "binancef", interval: "1h"}, {toast, esc});
// 전체 화면 오버레이 · 종목 검색 · 거래소 · 봉 간격 · 차트 종류 · 로그 · 지표(편집) · 그리기 도구 · 흐름 오버레이(호가 벽 · 고래 · 청산 추정) ·
// 흐름 패널 · 전략 신호/백테스트 · 1×1 / 1×2 / 2×2 · 스크린샷 · 전체 과거
import * as D from "./data.js";
import { DEFS, PALETTE, Q_GROUPS, X_GROUPS, loadCustom, labelOf } from "./registry.js";

const LC_URL = new URL("../vendor/lightweight-charts/lightweight-charts.standalone.production.js", import.meta.url).href;
const CSS_URL = new URL("./terminal.css", import.meta.url).href;
const KEY = "nuri:term:state", STRAT_KEY = "nuri:term:strategy";
const esc0 = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const uid = () => Math.random().toString(36).slice(2, 9);
const lsGet = (k, d) => { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* 저장소 막힘 */ } };
const LAYOUTS = { 1: "1×1", 2: "1×2", 4: "2×2" };
const CELL_IV = ["1h", "4h", "1d", "15m"];
const CTYPES = [["candles", "캔들"], ["hollow", "속빈 캔들"], ["ha", "헤이킨아시"], ["bars", "바"], ["line", "라인"], ["area", "영역"]];
const DEFAULT_INDS = () => [
  { id: uid(), key: "x:volume", params: { ma: 20 }, color: "#ff9800" },
  { id: uid(), key: "q:ema", params: { length: 20, source: "close" }, color: "#ff9800" },
  { id: uid(), key: "q:ema", params: { length: 50, source: "close" }, color: "#2962ff" },
];
const EXAMPLE = {
  name: "EMA 교차 + RSI 필터", interval: "1h",
  indicators: [{ id: "fast", type: "ema", length: 20 }, { id: "slow", type: "ema", length: 50 }, { id: "rsi", type: "rsi", length: 14 }],
  long_entry: { logic: "all", conditions: [{ left: "fast", op: "crosses_above", right: "slow" }, { left: "rsi", op: "<", right: "70" }] },
  short_entry: { logic: "all", conditions: [{ left: "fast", op: "crosses_below", right: "slow" }, { left: "rsi", op: ">", right: "30" }] },
  risk: { leverage: 3, stop_loss_pct: 2, take_profit_pct: 4 },
};

// 그리기 도구 아이콘 (원본 index.html 의 왼쪽 도구 막대)
const TOOLS_HTML = `<button data-draw="cursor" title="커서 (Esc)"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M8 5l12 9-5.5 1.2L18 21l-2.4 1.1-2.6-5.6L8.5 20z"/></svg></button><span class="nt-lsep"></span><button data-draw="trend" title="추세선"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M5 22L23 6"/><circle cx="5" cy="22" r="2"/><circle cx="23" cy="6" r="2"/></svg></button><button data-draw="ray" title="레이"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M5 20L25 8"/><circle cx="5" cy="20" r="2"/><circle cx="13" cy="15" r="2"/></svg></button><button data-draw="extended" title="연장선"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M2 21L26 7"/><circle cx="9" cy="17" r="2"/><circle cx="19" cy="11" r="2"/></svg></button><button data-draw="hline" title="수평선"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M3 14h22"/><circle cx="14" cy="14" r="2"/></svg></button><button data-draw="hray" title="수평 레이"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M10 14h16"/><circle cx="10" cy="14" r="2"/></svg></button><button data-draw="vline" title="수직선"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M14 3v22"/><circle cx="14" cy="14" r="2"/></svg></button><button data-draw="channel" title="평행 채널 (3점)"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M4 18L20 6M8 24L24 12"/><circle cx="4" cy="18" r="1.6"/><circle cx="20" cy="6" r="1.6"/></svg></button><span class="nt-lsep"></span><button data-draw="fib" title="피보나치 되돌림"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M4 6h20M4 11h20M4 15h20M4 19h20M4 23h20" stroke-width="1.2"/><circle cx="4" cy="23" r="1.6"/><circle cx="24" cy="6" r="1.6"/></svg></button><button data-draw="fibext" title="피보나치 확장 (3점)"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M4 8h20M4 14h20M4 20h20" stroke-width="1.2"/><path d="M5 22l6-12 6 6"/><circle cx="5" cy="22" r="1.5"/></svg></button><span class="nt-lsep"></span><button data-draw="long" title="롱 포지션 (진입·손절·목표 · RR)"><svg class="nt-ti" viewBox="0 0 28 28"><rect x="5" y="5" width="18" height="8" fill="rgba(8,153,129,.35)" stroke="#089981"/><rect x="5" y="13" width="18" height="7" fill="rgba(242,54,69,.3)" stroke="#f23645"/></svg></button><button data-draw="short" title="숏 포지션"><svg class="nt-ti" viewBox="0 0 28 28"><rect x="5" y="5" width="18" height="7" fill="rgba(242,54,69,.3)" stroke="#f23645"/><rect x="5" y="12" width="18" height="8" fill="rgba(8,153,129,.35)" stroke="#089981"/></svg></button><button data-draw="range" title="가격 범위 (변동폭 · %)"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M14 4v20M9 9l5-5 5 5M9 19l5 5 5-5"/></svg></button><button data-draw="daterange" title="날짜·가격 범위"><svg class="nt-ti" viewBox="0 0 28 28"><rect x="5" y="6" width="18" height="16"/><path d="M14 6v16M5 14h18" stroke-dasharray="2 2"/></svg></button><span class="nt-lsep"></span><button data-draw="rect" title="사각형"><svg class="nt-ti" viewBox="0 0 28 28"><rect x="5" y="7" width="18" height="14"/></svg></button><button data-draw="arrow" title="화살표"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M5 22L22 6M22 6h-7M22 6v7"/></svg></button><button data-draw="text" title="텍스트 (더블클릭으로 수정)"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M7 7h14M14 7v15"/></svg></button><button data-draw="brush" title="브러시"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M5 20c3-6 6 2 9-4s5-6 9-8"/></svg></button><span class="nt-lsep"></span><button data-dt="magnet" title="자석 (봉의 시가·고가·저가·종가에 붙기 · Ctrl 누른 채로도)"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M8 5v9a6 6 0 0 0 12 0V5M8 9h4M16 9h4"/></svg></button><button data-dt="stay" title="계속 그리기 (도구 유지)"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M6 20l10-10 3 3-10 10H6z"/><path d="M18 6l4 4"/></svg></button><button data-dt="lock" title="모든 그림 잠그기"><svg class="nt-ti" viewBox="0 0 28 28"><rect x="7" y="13" width="14" height="10" rx="2"/><path d="M10 13V9a4 4 0 0 1 8 0v4"/></svg></button><button data-dt="hide" title="모든 그림 숨기기"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M3 14s4-7 11-7 11 7 11 7-4 7-11 7S3 14 3 14z"/><circle cx="14" cy="14" r="3"/></svg></button><button data-dt="clear" title="모든 그림 지우기 (이 코인)"><svg class="nt-ti" viewBox="0 0 28 28"><path d="M6 8h16M11 8V5h6v3M8 8l1 15h10l1-15"/></svg></button>`;
const IC = {
  ind: `<svg class="nt-i" viewBox="0 0 24 24"><path d="M4 18c3-9 5-12 8-6s5 3 8-6"/><path d="M4 21h16"/></svg>`,
  shot: `<svg class="nt-i" viewBox="0 0 24 24"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>`,
  side: `<svg class="nt-i" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/></svg>`,
  hist: `<svg class="nt-i" viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v4h4M12 7v5l3 2"/></svg>`,
  flow: `<svg class="nt-i" viewBox="0 0 24 24"><path d="M3 7h12M3 12h18M3 17h8"/><circle cx="18" cy="7" r="2"/><circle cx="14" cy="17" r="2"/></svg>`,
  search: `<svg class="nt-i" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>`,
};

let T = null;   // 열린 터미널 하나

function loadScript(src) {
  return new Promise((res, rej) => {
    const old = [...document.scripts].find((s) => s.src === src);
    if (old && window.LightweightCharts) return res();
    const s = old || document.createElement("script");
    s.addEventListener("load", () => res(), { once: true });
    s.addEventListener("error", () => rej(new Error("차트 라이브러리를 불러오지 못했습니다")), { once: true });
    if (!old) { s.src = src; document.head.append(s); }
  });
}
function loadCss(href) {
  if ([...document.querySelectorAll("link[rel=stylesheet]")].some((l) => l.href === href)) return Promise.resolve();
  return new Promise((res) => {
    const l = document.createElement("link");
    l.rel = "stylesheet"; l.href = href; l.dataset.nuriTerminal = "1";
    l.onload = () => res(); l.onerror = () => res();
    document.head.append(l);
  });
}

export function terminalOpen() { return !!T; }

export async function openTerminal({ market = "BTCUSDT", exchange = "binancef", interval = "1h" } = {}, ctx = {}) {
  exchange = exchange || D.guessExchange(market);
  if (!D.EX_SHORT[exchange]) exchange = D.guessExchange(market);
  const want = { exchange, symbol: D.normSymbol(exchange, market), interval: D.normIv(interval) };
  if (T) { T.setCell(T.S.active, want); T.root.focus(); return T; }
  await loadCss(CSS_URL);
  if (!window.LightweightCharts) await loadScript(LC_URL);
  // chart.js · draw.js 는 라이브러리를 쓴 뒤에 불러온다
  const [{ TermChart, esc, big, smart }, { Drawings, TOOLS }] = await Promise.all([import("./chart.js"), import("./draw.js")]);
  if (T) { T.setCell(T.S.active, want); return T; }
  T = new Terminal(ctx, { TermChart, Drawings, TOOLS, esc: ctx.esc || esc, big, smart }, want);
  return T;
}

export function closeTerminal() { if (T) { const t = T; T = null; t.destroy(); } }

class Terminal {
  constructor(ctx, lib, want) {
    this.ctx = ctx; this.lib = lib; this.esc = lib.esc || esc0;
    const saved = lsGet(KEY, {});
    this.S = {
      inds: Array.isArray(saved.inds) ? saved.inds.filter((s) => s && DEFS[s.key]).map((s) => ({ ...s, id: s.id || uid() })) : DEFAULT_INDS(),
      ctype: saved.ctype || "candles", log: !!saved.log, overlays: { walls: false, whales: false, liq: false, ...(saved.overlays || {}) },
      layout: LAYOUTS[saved.layout] ? +saved.layout : 1, cells: Array.isArray(saved.cells) ? saved.cells.filter((c) => c && D.EX_SHORT[c.exchange] && c.symbol) : [],
      active: 0, side: innerWidth < 760 ? false : saved.side ?? (innerWidth > 1100),   // 휴대폰은 차트부터 tab: saved.tab || "flow", magnet: !!saved.magnet, stay: !!saved.stay, stratMode: saved.stratMode || "signals",
    };
    this.S.cells[0] = want;
    this.cells = [];
    this.strat = null;   // {spec, result}
    this._build();
    this._applyLayout();
    this._save();
    this.root.focus();
  }

  toast(msg, kind) { if (this.ctx.toast) this.ctx.toast(msg, kind); else { this.statusEl.querySelector(".nt-st-msg").textContent = msg; } }
  _save() {
    const S = this.S;
    lsSet(KEY, { inds: S.inds, ctype: S.ctype, log: S.log, overlays: S.overlays, layout: S.layout, cells: S.cells, side: S.side, tab: S.tab, magnet: S.magnet, stay: S.stay, stratMode: S.stratMode });
  }
  get cur() { return this.cells[this.S.active]; }

  // ------------------------------------------------------------ 화면 만들기
  _build() {
    const S = this.S, r = document.createElement("div");
    r.className = "nt-root"; r.tabIndex = -1; r.setAttribute("role", "dialog"); r.setAttribute("aria-label", "차트 터미널");
    r.innerHTML = `
      <div class="nt-top">
        <button class="nt-sym" data-nt="search" title="종목 검색">${IC.search}<b class="nt-sym-name"></b><span class="nt-sym-ex"></span></button>
        <select class="nt-ex" title="거래소">${D.EXCHANGES.map(([k, n]) => `<option value="${k}">${n}</option>`).join("")}</select>
        <div class="nt-ivs" role="group" aria-label="봉 간격">${D.IVS.map(([k]) => `<button data-iv="${k}">${k === "1d" ? "1D" : k === "1w" ? "1W" : k}</button>`).join("")}</div>
        <span class="nt-sep"></span>
        <select class="nt-ctype" title="차트 종류">${CTYPES.map(([k, n]) => `<option value="${k}">${n}</option>`).join("")}</select>
        <button data-nt="ind" title="보조지표">${IC.ind}<span>지표</span></button>
        <button data-nt="log" class="nt-tog" title="로그 가격축">로그</button>
        <button data-nt="full" title="이 종목·간격의 전체 과거 캔들 받기 (캐시)">${IC.hist}<span>전체 과거</span></button>
        <div class="nt-mwrap"><button data-nt="flowmenu" title="흐름 오버레이">${IC.flow}<span>흐름</span> ▾</button>
          <div class="nt-menu" hidden>
            <label><input type="checkbox" data-ov="walls"> 호가 벽 (가격대 띠)</label>
            <label><input type="checkbox" data-ov="whales"> 고래 체결 (버블)</label>
            <label><input type="checkbox" data-ov="liq"> 청산 구간 <b class="heat">추정</b> (열선)</label>
            <div class="nt-menu-note">코인(바이낸스·업비트)만 · 15초마다 갱신 · 청산은 실제 데이터가 아닌 추정</div>
          </div></div>
        <select class="nt-layout" title="화면 분할">${Object.entries(LAYOUTS).map(([k, n]) => `<option value="${k}">${n}</option>`).join("")}</select>
        <button data-nt="shot" title="스크린샷 저장">${IC.shot}</button>
        <button data-nt="side" class="nt-tog" title="흐름 · 전략 패널">${IC.side}<span>패널</span></button>
        <span class="nt-grow"></span>
        <span class="nt-badge" title="분석 전용 — 주문은 트레이딩 모듈에서">분석 전용</span>
        <button class="nt-close" data-nt="close" title="닫기 (Esc)" aria-label="닫기">✕</button>
      </div>
      <div class="nt-body">
        <nav class="nt-tools" aria-label="그리기 도구">${TOOLS_HTML}</nav>
        <div class="nt-grid"></div>
        <aside class="nt-side" hidden>
          <div class="nt-tabs"><button data-tab="flow">흐름</button><button data-tab="strat">전략</button><button class="nt-side-x" data-nt="side" aria-label="패널 닫기">✕</button></div>
          <div class="nt-pane" data-pane="flow"></div>
          <div class="nt-pane" data-pane="strat">
            <div class="nt-st-help">전략 JSON(quant.js 형식)을 붙여 넣으면 지금 차트 캔들로 신호와 백테스트를 계산해 표시합니다. <a href="#" data-nt="example">예시 넣기</a></div>
            <textarea class="nt-strat" spellcheck="false" placeholder='{"indicators":[...], "long_entry":{...}, "short_entry":{...}, "risk":{...}}'></textarea>
            <div class="nt-row"><button class="nt-primary" data-nt="strat-run">실행</button><select class="nt-strat-mode"><option value="signals">신호 표시</option><option value="trades">백테스트 거래 표시</option></select><button data-nt="strat-clear">지우기</button></div>
            <div class="nt-strat-out"></div>
          </div>
        </aside>
      </div>
      <div class="nt-status"><span class="nt-st-src"></span><span class="nt-st-live"></span><span class="nt-st-cd"></span><span class="nt-st-msg"></span></div>
      <div class="nt-modal" hidden><div class="nt-dlg" role="dialog"></div></div>`;
    document.body.append(r);
    this.root = r;
    this.grid = r.querySelector(".nt-grid"); this.sideEl = r.querySelector(".nt-side"); this.statusEl = r.querySelector(".nt-status");
    this.modal = r.querySelector(".nt-modal"); this.dlg = r.querySelector(".nt-dlg");
    this._prevOverflow = document.body.style.overflow; document.body.style.overflow = "hidden";
    r.querySelector(".nt-strat").value = lsGet(STRAT_KEY, "");
    r.querySelector(".nt-strat-mode").value = S.stratMode;

    // 앱의 문서 전체 클릭 처리기(data-act 등)가 터미널 안의 클릭을 가로채지 않게 여기서 멈춘다
    r.addEventListener("click", (e) => { this._onClick(e); e.stopPropagation(); });
    ["keydown", "input", "submit"].forEach((t) => r.addEventListener(t, (e) => { if (t !== "keydown" || e.key !== "Escape") e.stopPropagation(); }));
    r.querySelector(".nt-ex").addEventListener("change", (e) => {
      const ex = e.target.value, cfg = this.S.cells[this.S.active];
      let sym = cfg.symbol;
      if (ex === "yahoo") sym = D.isCrypto(cfg.exchange) ? "NVDA" : sym;
      else if (!D.isCrypto(cfg.exchange)) sym = ex === "upbit" ? "KRW-BTC" : "BTCUSDT";
      this.setCell(this.S.active, { exchange: ex, symbol: D.normSymbol(ex, sym), interval: cfg.interval });
    });
    r.querySelector(".nt-ctype").addEventListener("change", (e) => { S.ctype = e.target.value; this.cells.forEach((c) => c.tc.setChartType(S.ctype)); this._save(); });
    r.querySelector(".nt-layout").addEventListener("change", (e) => { S.layout = +e.target.value; this._applyLayout(); this._save(); });
    r.querySelector(".nt-strat-mode").addEventListener("change", (e) => { S.stratMode = e.target.value; this._save(); this._applyStrat(); });
    r.querySelectorAll("[data-ov]").forEach((cb) => cb.addEventListener("change", () => this.setOverlay(cb.dataset.ov, cb.checked)));
    this._onKey = (e) => {
      if (e.key !== "Escape" || !T) return;
      if (!this.modal.hidden) { this._closeModal(); e.preventDefault(); return; }
      const m = r.querySelector(".nt-menu:not([hidden])");
      if (m) { m.hidden = true; e.preventDefault(); return; }
      if (e.target.closest?.("input, textarea, select")) { e.target.blur(); return; }
      e.preventDefault(); closeTerminal();
    };
    document.addEventListener("keydown", this._onKey);
    this._onDocDown = (e) => { const m = r.querySelector(".nt-menu:not([hidden])"); if (m && !e.target.closest(".nt-mwrap")) m.hidden = true; };
    document.addEventListener("pointerdown", this._onDocDown, true);
    this.modal.addEventListener("pointerdown", (e) => { if (e.target === this.modal) this._closeModal(); });
    this._cd = setInterval(() => this._statusTick(), 1000);
    this._syncToolbar();
  }

  destroy() {
    clearInterval(this._cd);
    document.removeEventListener("keydown", this._onKey);
    document.removeEventListener("pointerdown", this._onDocDown, true);
    this.cells.forEach((c) => { c.dr.destroy(); c.tc.destroy(); });
    this.cells = [];
    document.body.style.overflow = this._prevOverflow || "";
    this.root.remove();
  }

  // ------------------------------------------------------------ 칸 (1×1 / 1×2 / 2×2)
  _applyLayout() {
    const S = this.S, n = S.layout;
    this.grid.className = `nt-grid g${n}`;
    while (this.cells.length > n) { const c = this.cells.pop(); c.dr.destroy(); c.tc.destroy(); c.wrap.remove(); }
    for (let i = this.cells.length; i < n; i++) {
      if (!S.cells[i]) { const a = S.cells[0]; S.cells[i] = { exchange: a.exchange, symbol: a.symbol, interval: CELL_IV.find((iv) => !S.cells.slice(0, i).some((c) => c?.interval === iv && c.symbol === a.symbol)) || a.interval }; }
      this.cells.push(this._makeCell(i));
    }
    S.cells.length = Math.max(S.cells.length, n);
    if (S.active >= n) S.active = 0;
    this.cells.forEach((c, i) => { c.wrap.classList.toggle("on", i === S.active); if (!c.loaded) { c.loaded = true; this._load(i); } });
    this._syncToolbar();
  }
  _makeCell(i) {
    const S = this.S, wrap = document.createElement("div");
    wrap.className = "nt-cell"; wrap.innerHTML = `<div class="nt-cellbox"></div>`;
    this.grid.append(wrap);
    const cell = { wrap };
    cell.tc = new this.lib.TermChart(wrap.firstChild, {
      getInds: () => S.inds, overlays: S.overlays, ws: this.ctx.ws,
      isActive: (tc) => this.cur?.tc === tc && this.modal.hidden,
      wantFlow: (tc) => S.side && S.tab === "flow" && this.cur?.tc === tc,
      onLegend: (act, id) => this._legendAct(act, id),
      onLoad: (tc) => { cell.dr.load(); if (this.cur === cell) { this._syncToolbar(); if (this.strat) this._runStrat(true); } },
      onFlow: (tc) => { if (this.cur?.tc === tc) this._renderFlow(); },
      onStatus: (tc) => { if (this.cur?.tc === tc) this._statusTick(); },
      onTick: (tc) => { if (this.strat && this.cur?.tc === tc && tc.candles.at(-1)?.time !== this._stratBar) this._runStrat(true); },
    });
    cell.tc.setChartType(S.ctype); cell.tc.setLog(S.log);
    cell.dr = new this.lib.Drawings(cell.tc, { onChange: () => { if (this.cur === cell) this._syncTools(); } });
    cell.dr.magnet = S.magnet; cell.dr.stay = S.stay;
    wrap.addEventListener("pointerdown", () => { const k = this.cells.indexOf(cell); if (k >= 0 && k !== S.active) this.activate(k); }, true);
    return cell;
  }
  activate(i) {
    const S = this.S, prev = this.cur;
    if (prev && prev.dr.tool !== "cursor") prev.dr.setTool("cursor");
    S.active = i;
    this.cells.forEach((c, k) => c.wrap.classList.toggle("on", k === i));
    this._syncToolbar(); this._save();
    if (S.side && S.tab === "flow") this.cur.tc.refreshFlow();
    if (prev?.tc && prev !== this.cur) prev.tc.refreshFlow();   // 흐름 패널 폴링은 활성 칸만
    if (this.strat) this._runStrat(true);
  }
  async _load(i) {
    const cfg = this.S.cells[i], cell = this.cells[i];
    try { await cell.tc.load(cfg.exchange, cfg.symbol, cfg.interval); }
    catch (e) { if (i === this.S.active) this.toast(`${cfg.symbol} 불러오기 실패: ${e.message || e}`, "err"); }
    if (i === this.S.active) this._syncToolbar();
  }
  setCell(i, cfg) {
    const S = this.S;
    S.cells[i] = { ...S.cells[i], ...cfg };
    S.cells[i].symbol = D.normSymbol(S.cells[i].exchange, S.cells[i].symbol);
    this._save(); this._syncToolbar();
    if (this.cells[i]) this._load(i);
  }

  // ------------------------------------------------------------ 툴바 동작
  _onClick(e) {
    const b = e.target.closest("button, a[data-nt]");
    if (!b || !this.root.contains(b)) return;
    if (b.closest(".nt-dlg")) return;   // 대화상자는 따로
    const S = this.S, act = b.dataset.nt;
    if (b.dataset.iv) { const c = S.cells[S.active]; this.setCell(S.active, { ...c, interval: b.dataset.iv }); return; }
    if (b.dataset.draw) { this.cur?.dr.setTool(b.dataset.draw); this._syncTools(); return; }
    if (b.dataset.dt) { this._drawToggle(b.dataset.dt); return; }
    if (b.dataset.tab) { S.tab = b.dataset.tab; this._save(); this._syncSide(); return; }
    if (act) e.preventDefault();
    switch (act) {
      case "close": closeTerminal(); break;
      case "search": this._openSearch(); break;
      case "ind": this._openPicker(); break;
      case "log": S.log = !S.log; this.cells.forEach((c) => c.tc.setLog(S.log)); this._save(); this._syncToolbar(); break;
      case "full": this._full(b); break;
      case "flowmenu": {
        const m = b.parentElement.querySelector(".nt-menu"), rc = b.getBoundingClientRect();
        m.hidden = !m.hidden;
        if (!m.hidden) { m.style.top = `${rc.bottom}px`; m.style.left = `${Math.max(4, Math.min(innerWidth - m.offsetWidth - 4, rc.left))}px`; }
        break;
      }
      case "shot": this._shot(); break;
      case "side": S.side = !S.side; this._save(); this._syncSide(); this.cur?.tc.refreshFlow(); break;
      case "example": this.root.querySelector(".nt-strat").value = JSON.stringify({ ...EXAMPLE, interval: this.S.cells[this.S.active].interval }, null, 2); break;
      case "strat-run": this._runStrat(); break;
      case "strat-clear": this.strat = null; this.cells.forEach((c) => c.tc.setStrategyMarkers([])); this.root.querySelector(".nt-strat-out").innerHTML = ""; break;
      case "flow-refresh": this.cur?.tc.refreshFlow(); break;
      default: break;
    }
  }
  setOverlay(name, on) {
    this.S.overlays[name] = on; this._save();
    this.cells.forEach((c) => c.tc.refreshFlow());
    this._syncToolbar();
  }
  _drawToggle(k) {
    const S = this.S, dr = this.cur?.dr;
    if (!dr) return;
    if (k === "magnet") { S.magnet = !S.magnet; this.cells.forEach((c) => (c.dr.magnet = S.magnet)); }
    else if (k === "stay") { S.stay = !S.stay; this.cells.forEach((c) => (c.dr.stay = S.stay)); }
    else if (k === "lock") { dr.locked = !dr.locked; }
    else if (k === "hide") { dr.hidden = !dr.hidden; dr.layer.update(); }
    else if (k === "clear") { if (dr.items.length && confirm(`${this.cur.tc.symbol}의 그림 ${dr.items.length}개를 모두 지울까요?`)) dr.clear(); }
    this._save(); this._syncTools();
  }
  _syncTools() {
    const dr = this.cur?.dr, r = this.root;
    if (!dr) return;
    r.querySelectorAll(".nt-tools [data-draw]").forEach((b) => b.classList.toggle("on", b.dataset.draw === dr.tool));
    const st = { magnet: this.S.magnet, stay: this.S.stay, lock: dr.locked, hide: dr.hidden };
    r.querySelectorAll(".nt-tools [data-dt]").forEach((b) => b.classList.toggle("on", !!st[b.dataset.dt]));
    this.cells.forEach((c) => c.wrap.classList.toggle("drawing", c.dr.tool !== "cursor"));
  }
  _syncToolbar() {
    const S = this.S, r = this.root, cfg = S.cells[S.active];
    if (!cfg || !r) return;
    const tc = this.cur?.tc, name = tc?.meta?.name || D.nameOf(cfg.exchange, cfg.symbol);
    r.querySelector(".nt-sym-name").textContent = cfg.symbol;
    r.querySelector(".nt-sym-ex").textContent = name || D.EX_SHORT[cfg.exchange];
    r.querySelector(".nt-ex").value = cfg.exchange;
    r.querySelectorAll(".nt-ivs [data-iv]").forEach((b) => b.classList.toggle("on", b.dataset.iv === cfg.interval));
    r.querySelector(".nt-ctype").value = S.ctype;
    r.querySelector(".nt-layout").value = String(S.layout);
    r.querySelector('[data-nt="log"]').classList.toggle("on", S.log);
    r.querySelectorAll("[data-ov]").forEach((cb) => { cb.checked = !!S.overlays[cb.dataset.ov]; });
    r.querySelector('[data-nt="flowmenu"]').classList.toggle("on", Object.values(S.overlays).some(Boolean));
    this._syncSide(); this._syncTools(); this._statusTick();
  }
  _syncSide() {
    const S = this.S, r = this.root;
    this.sideEl.hidden = !S.side;
    this.root.classList.toggle("with-side", S.side);
    r.querySelectorAll('.nt-top [data-nt="side"]').forEach((b) => b.classList.toggle("on", S.side));
    r.querySelectorAll(".nt-tabs [data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === S.tab));
    r.querySelectorAll(".nt-pane").forEach((p) => (p.hidden = p.dataset.pane !== S.tab));
    if (S.side && S.tab === "flow") this._renderFlow();
  }
  _statusTick() {
    const tc = this.cur?.tc, st = this.statusEl;
    if (!tc || !st) return;
    const b = tc.candles.at(-1), sec = D.IV_SEC[tc.interval] || 3600;
    st.querySelector(".nt-st-src").textContent = `${tc.meta.source || D.EX_SHORT[tc.exchange]}${tc.full ? " · 전체 과거" : ""} · ${tc.candles.length.toLocaleString()}봉`;
    const live = st.querySelector(".nt-st-live");
    live.textContent = tc.live || ""; live.className = "nt-st-live " + (tc.live === "실시간" ? "ok" : "");
    st.querySelector(".nt-st-cd").textContent = b && tc.exchange !== "yahoo" ? `봉 마감까지 ${fmtLeft(b.time + sec - Date.now() / 1000)}` : "";
  }

  // ------------------------------------------------------------ 종목 검색
  _openSearch() {
    const S = this.S, cfg = S.cells[S.active];
    this._openModal(`<div class="nt-dlg-h"><b>종목 검색</b><button data-x aria-label="닫기">✕</button></div>
      <div class="nt-srch"><input type="search" placeholder="BTCUSDT · KRW-ETH · NVDA · 005930 · ^KS11 · CL=F" autocomplete="off" spellcheck="false">
      <select>${D.EXCHANGES.map(([k, n]) => `<option value="auto">자동</option>`).slice(0, 1).join("")}${D.EXCHANGES.map(([k, n]) => `<option value="${k}">${n}</option>`).join("")}</select></div>
      <div class="nt-srch-list"></div><div class="nt-dlg-note">목록에 없어도 코드를 입력하고 Enter. 코인 이름만 쓰면 지금 거래소의 USDT 마켓으로 찾습니다.</div>`, "search");
    const inp = this.dlg.querySelector("input"), sel = this.dlg.querySelector("select"), list = this.dlg.querySelector(".nt-srch-list");
    let remote = [];
    const all = () => {
      const base = D.PRESETS.map(([s, ex, n]) => ({ s, ex, n, tag: "추천" }));
      const y = D.YAHOO_ALL.filter(([s]) => !base.some((b) => b.s === s)).map(([s, n]) => ({ s, ex: "yahoo", n, tag: "" }));
      return [...base, ...remote, ...y];
    };
    const render = () => {
      const q = inp.value.trim().toUpperCase(), ex = sel.value;
      let rows = all().filter((x) => (ex === "auto" || x.ex === ex) && (!q || x.s.toUpperCase().includes(q) || (x.n || "").toUpperCase().includes(q)));
      const seen = new Set(); rows = rows.filter((x) => { const k = x.ex + x.s; if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 80);
      list.innerHTML = rows.map((x, i) => `<button data-i="${i}" class="${x.s === cfg.symbol && x.ex === cfg.exchange ? "on" : ""}"><b>${this.esc(x.s)}</b><span>${this.esc(x.n || "")}</span><em>${D.EX_SHORT[x.ex]}${x.tag ? " · " + x.tag : ""}</em></button>`).join("")
        || `<div class="nt-empty">일치하는 프리셋이 없습니다 — Enter 로 "${this.esc(q)}" 열기</div>`;
      list._rows = rows;
    };
    const pick = (x) => { this._closeModal(); this.setCell(S.active, { exchange: x.ex, symbol: D.normSymbol(x.ex, x.s), interval: cfg.interval }); };
    list.addEventListener("click", (e) => { const b = e.target.closest("[data-i]"); if (b) pick(list._rows[+b.dataset.i]); });
    inp.addEventListener("input", render); sel.addEventListener("change", () => { render(); loadRemote(); });
    inp.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      const q = inp.value.trim();
      if (!q) return;
      const first = list._rows?.[0];
      if (first && first.s.toUpperCase() === q.toUpperCase()) return pick(first);
      const ex = sel.value === "auto" ? D.guessExchange(q, cfg.exchange) : sel.value;
      pick({ s: q, ex });
    });
    // 거래소 전체 목록 (거래대금 상위)
    const loadRemote = async () => {
      const ex = sel.value === "auto" ? (D.isCrypto(cfg.exchange) ? cfg.exchange : "binancef") : sel.value;
      if (!D.isCrypto(ex) || remote.some((x) => x.ex === ex)) return;
      try {
        await D.ensureLauncher();
        const { exchanges } = await import("../trade.js"), { apiBase, webGet } = await import("../engine.js");
        const rows = await exchanges(apiBase, webGet)[ex].list();
        remote = [...remote, ...rows.map((t) => ({ s: t.id, ex, n: `${t.name} · ${t.chg >= 0 ? "+" : ""}${(t.chg * 100).toFixed(2)}%`, tag: "" }))];
        if (!this.modal.hidden) render();
      } catch (e) { /* 목록 실패는 무시 (직접 입력 가능) */ }
    };
    sel.value = "auto"; render(); loadRemote();
    setTimeout(() => inp.focus(), 30);
  }

  // ------------------------------------------------------------ 지표 선택 · 설정
  _openPicker() {
    const groups = [
      ...Q_GROUPS.map((g) => ({ title: g, sec: "기본 지표 · 전략 엔진(quant.js)과 같은 공식", keys: Object.keys(DEFS).filter((k) => DEFS[k].src === "q" && DEFS[k].group === g) })),
      ...X_GROUPS.map((g) => ({ title: g, sec: "확장 지표 · 차트 전용", keys: Object.keys(DEFS).filter((k) => DEFS[k].src === "x" && DEFS[k].group === g) })),
    ];
    const cur = () => this.S.inds.map((s) => `<div class="nt-cur-row"><span class="dot" style="background:${s.color || "#888"}"></span><span>${this.esc(labelOf(s))}</span><span class="muted">${this.esc(paramText(s))}</span><button data-set="${s.id}">설정</button><button data-del="${s.id}" aria-label="지우기">✕</button></div>`).join("") || `<div class="nt-empty">추가한 지표가 없습니다</div>`;
    this._openModal(`<div class="nt-dlg-h"><b>보조지표</b><button data-x aria-label="닫기">✕</button></div>
      <input type="search" class="nt-pick-q" placeholder="지표 검색 (RSI, 볼린저, 일목, SMC …)" autocomplete="off">
      <div class="nt-pick">
        <div class="nt-pick-list"></div>
        <div class="nt-pick-side"><div class="nt-sub-h">차트에 있는 지표</div><div class="nt-cur"></div>
          <div class="nt-sub-h">커스텀 지표</div><div class="nt-cust"><div class="nt-empty">확인 중…</div></div>
          <button class="nt-reset" data-reset>기본 지표로 되돌리기</button></div>
      </div>`, "picker");
    const q = this.dlg.querySelector(".nt-pick-q"), list = this.dlg.querySelector(".nt-pick-list"), curEl = this.dlg.querySelector(".nt-cur");
    const render = () => {
      const s = q.value.trim().toLowerCase();
      let html = "", lastSec = "";
      for (const g of groups) {
        const keys = g.keys.filter((k) => !s || DEFS[k].name.toLowerCase().includes(s) || k.includes(s) || (DEFS[k].desc || "").toLowerCase().includes(s));
        if (!keys.length) continue;
        if (g.sec !== lastSec) { html += `<div class="nt-sec">${g.sec}</div>`; lastSec = g.sec; }
        html += `<div class="nt-grp">${g.title}</div>` + keys.map((k) => `<button data-add="${k}" title="${this.esc(DEFS[k].desc || "")}"><span>${this.esc(DEFS[k].name)}</span><em>${DEFS[k].pane === "sub" ? "아래 창" : DEFS[k].pane === "volume" ? "거래량" : "가격 위"}</em></button>`).join("");
      }
      list.innerHTML = html || `<div class="nt-empty">없음</div>`;
      curEl.innerHTML = cur();
    };
    q.addEventListener("input", render);
    this.dlg.addEventListener("click", (e) => {
      const a = e.target.closest("[data-add]"), st = e.target.closest("[data-set]"), dl = e.target.closest("[data-del]");
      if (a) { this.addInd(a.dataset.add); render(); this.toast(`${DEFS[a.dataset.add].name} 추가`); }
      else if (st) this._openSettings(st.dataset.set);
      else if (dl) { this.removeInd(dl.dataset.del); render(); }
      else if (e.target.closest("[data-reset]")) { this.S.inds = DEFAULT_INDS(); this._indsChanged(); render(); }
      else if (e.target.closest("[data-cust-add]")) {
        const ta = this.dlg.querySelector(".nt-cust textarea"), expr = ta?.value.trim();
        if (!expr) return;
        const ov = this.dlg.querySelector(".nt-cust input[type=checkbox]")?.checked ? 1 : 0;
        this.addInd("c:expr", { expr, overlay: ov });
        ta.value = ""; render();
      }
    });
    render(); setTimeout(() => q.focus(), 30);
    // 커스텀 지표 (customind.js 가 있을 때만)
    loadCustom().then((m) => {
      const box = this.dlg.querySelector(".nt-cust");
      if (!box) return;
      box.innerHTML = m
        ? `<textarea rows="3" spellcheck="false" placeholder="예: zscore(close, 50) · (close - close[20]) / (ind(&quot;atr&quot;, {length:14}) * sqrt(20))"></textarea><label class="nt-chk"><input type="checkbox"> 가격 위에 그리기</label><button class="nt-primary" data-cust-add>수식 추가</button>${m.CUSTOM_DOC ? `<details class="nt-doc"><summary>수식 문법 · 예시</summary><pre>${this.esc(String(m.CUSTOM_DOC))}</pre></details>` : ""}`
        : `<div class="nt-disabled">커스텀 지표 모듈(customind.js)이 아직 없어 수식 입력을 쓸 수 없습니다.</div>`;
    });
  }
  addInd(key, params = {}) {
    const def = DEFS[key];
    if (!def) return null;
    const used = new Set(this.S.inds.map((s) => s.color));
    const color = PALETTE.find((c) => !used.has(c)) || PALETTE[this.S.inds.length % PALETTE.length];
    const spec = { id: uid(), key, params: { ...def.params, ...params }, color };
    this.S.inds.push(spec);
    this._indsChanged();
    return spec;
  }
  removeInd(id) { this.S.inds = this.S.inds.filter((s) => s.id !== id); this._indsChanged(); }
  _indsChanged() { this._save(); this.cells.forEach((c) => c.tc.renderIndicators()); }
  _legendAct(act, id) {
    const s = this.S.inds.find((x) => x.id === id);
    if (!s) return;
    if (act === "hide") { s.hidden = !s.hidden; this._indsChanged(); }
    else if (act === "del") this.removeInd(id);
    else if (act === "set") this._openSettings(id);
  }
  _openSettings(id) {
    const s = this.S.inds.find((x) => x.id === id), def = s && DEFS[s.key];
    if (!def) return;
    const back = this.modal.hidden ? null : this._modalKind;
    const p = { ...def.params, ...s.params };
    const field = (k, v) => {
      if (k === "expr") return `<label class="wide">수식<textarea name="expr" rows="3" spellcheck="false">${this.esc(v)}</textarea></label>`;
      if (k === "overlay") return `<label class="nt-chk"><input type="checkbox" name="overlay" ${+v ? "checked" : ""}> 가격 위에 그리기</label>`;
      if (k === "source") return `<label>${k}<select name="source">${["close", "open", "high", "low", "hl2", "hlc3", "ohlc4", "volume"].map((x) => `<option ${x === v ? "selected" : ""}>${x}</option>`).join("")}</select></label>`;
      if (typeof v === "number") return `<label>${k}<input type="number" name="${k}" value="${v}" step="any"></label>`;
      return `<label>${k}<input name="${k}" value="${this.esc(v)}"></label>`;
    };
    this._openModal(`<div class="nt-dlg-h"><b>${this.esc(labelOf(s))} 설정</b><button data-x aria-label="닫기">✕</button></div>
      ${def.desc ? `<div class="nt-dlg-note">${this.esc(def.desc)}</div>` : ""}
      <form class="nt-form">${Object.entries(p).map(([k, v]) => field(k, v)).join("")}
        <label>색<input type="color" name="__color" value="${/^#[0-9a-f]{6}$/i.test(s.color || "") ? s.color : "#2962ff"}"></label></form>
      <div class="nt-row end"><button data-cancel>취소</button><button class="nt-primary" data-ok>적용</button></div>`, "settings");
    const done = () => { if (back === "picker") this._openPicker(); else this._closeModal(); };
    this.dlg.querySelector("[data-cancel]").onclick = done;
    this.dlg.querySelector("[data-ok]").onclick = () => {
      const f = this.dlg.querySelector("form"), np = {};
      for (const [k, v0] of Object.entries(p)) {
        const el = f.elements[k];
        if (!el) continue;
        if (k === "overlay") np[k] = el.checked ? 1 : 0;
        else if (typeof v0 === "number") { const x = parseFloat(el.value); np[k] = Number.isFinite(x) ? x : v0; }
        else np[k] = el.value;
      }
      s.params = np; s.color = f.elements.__color.value;
      this._indsChanged(); done();
    };
  }

  // ------------------------------------------------------------ 대화상자
  _openModal(html, kind) {
    this._modalKind = kind;
    this.dlg.className = `nt-dlg nt-dlg-${kind}`;
    this.dlg.innerHTML = html;
    this.modal.hidden = false;
    this.dlg.querySelector("[data-x]")?.addEventListener("click", () => this._closeModal());
  }
  _closeModal() { this.modal.hidden = true; this.dlg.innerHTML = ""; this._modalKind = null; this.root.focus(); }

  // ------------------------------------------------------------ 전체 과거 · 스크린샷
  async _full(btn) {
    const tc = this.cur?.tc;
    if (!tc || btn.disabled) return;
    btn.disabled = true; btn.classList.add("busy");
    const label = btn.querySelector("span"), old = label.textContent;
    try {
      const r = await tc.loadFull((p) => { label.textContent = p.bars ? `${p.bars.toLocaleString()}봉…` : p.phase === "incremental" ? "갱신…" : "받는 중…"; });
      if (r) this.toast(r.note || "전체 과거를 불러왔습니다");
    } catch (e) { this.toast("전체 과거 실패: " + (e.message || e), "err"); }
    finally { btn.disabled = false; btn.classList.remove("busy"); label.textContent = old; this._statusTick(); }
  }
  _shot() {
    const tc = this.cur?.tc;
    if (!tc?.candles.length) return;
    const cv = tc.screenshot();
    cv.toBlob((b) => {
      if (!b) return;
      const a = document.createElement("a"), d = new Date(), z = (n) => String(n).padStart(2, "0");
      a.href = URL.createObjectURL(b);
      a.download = `${tc.symbol.replace(/[^\w.-]/g, "_")}_${tc.interval}_${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}_${z(d.getHours())}${z(d.getMinutes())}.png`;
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      this.toast("스크린샷을 저장했습니다");
    }, "image/png");
  }

  // ------------------------------------------------------------ 흐름 패널
  _renderFlow() {
    const el = this.root.querySelector('[data-pane="flow"]'), tc = this.cur?.tc;
    if (!el || !tc || !this.S.side || this.S.tab !== "flow") return;
    const big = this.lib.big, px = (v) => tc.px(v), pc = (v, d = 2) => v == null || !Number.isFinite(v) ? "–" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}%`;
    const ov = this.S.overlays, tg = (k, t) => `<button class="nt-chipb ${ov[k] ? "on" : ""}" data-ovb="${k}">${t}</button>`;
    let html = `<div class="nt-row wrap">${tg("walls", "호가 벽")}${tg("whales", "고래")}${tg("liq", "청산 추정")}<button class="nt-chipb" data-nt="flow-refresh">새로고침</button></div>`;
    if (!tc.crypto) { el.innerHTML = html + `<div class="nt-empty">호가·고래·선물 흐름은 코인(바이낸스·업비트)만 제공됩니다.<br>지금 종목: ${this.esc(tc.symbol)} (야후)</div>`; this._bindFlowBtns(el); return; }
    const f = tc.flow, s = f.snap;
    if (!s) { el.innerHTML = html + `<div class="nt-empty">${f.err ? `<span class="down">${this.esc(f.err)}</span>` : "흐름 데이터를 불러오는 중…"}</div>`; this._bindFlowBtns(el); return; }
    const cur = s.orderBook?.quote === "KRW" || s.whaleTrades?.quote === "KRW" ? "₩" : "$";
    // 흐름 점수
    const sc = s.score, scCls = sc >= 20 ? "up" : sc <= -20 ? "down" : "";
    html += `<section class="nt-card"><div class="nt-card-h">흐름 점수 <span class="muted">(−100 매도 ~ +100 매수 압력)</span></div>
      <div class="nt-score ${scCls}"><b>${sc > 0 ? "+" : ""}${sc}</b><span>${this.esc(s.label)}</span></div>
      <div class="nt-gauge"><i style="left:${50 + sc / 2}%"></i></div>
      ${s.factors.map((x) => `<div class="nt-fac"><span>${this.esc(x.label)}</span><span class="muted">${this.esc(x.note)}</span><span class="${x.pts > 0 ? "up" : x.pts < 0 ? "down" : ""}">${x.pts > 0 ? "+" : ""}${x.pts}/${x.max}</span></div>`).join("")}</section>`;
    // 호가
    const ob = s.orderBook;
    if (ob) {
      html += `<section class="nt-card"><div class="nt-card-h">호가 깊이 <span class="muted">중간가 ${px(ob.mid)} · 스프레드 ${ob.spreadBps.toFixed(2)}bp</span></div>
        ${ob.bands.map((b) => { const t = b.bid + b.ask || 1; return `<div class="nt-depth"><span>±${b.band}%</span><div class="nt-bar"><i class="bid" style="width:${(b.bid / t * 100).toFixed(1)}%"></i><i class="ask" style="width:${(b.ask / t * 100).toFixed(1)}%"></i></div><span class="${b.imbalance > 0 ? "up" : "down"}">${pc(b.imbalance * 100, 0)}</span></div><div class="nt-depth-n"><span class="up">매수 ${cur}${big(b.bid)}</span><span class="down">매도 ${cur}${big(b.ask)}</span>${b.complete ? "" : `<span class="muted">부분 집계</span>`}</div>`; }).join("")}
        <div class="nt-walls"><div><div class="nt-sub-h down">매도벽</div>${ob.askWalls.map((w) => `<div class="nt-wl"><span>${px(w.price)}</span><span class="muted">${pc(w.distPct)}</span><b>${cur}${big(w.notional)}</b></div>`).join("")}</div>
        <div><div class="nt-sub-h up">매수벽</div>${ob.bidWalls.map((w) => `<div class="nt-wl"><span>${px(w.price)}</span><span class="muted">${pc(w.distPct)}</span><b>${cur}${big(w.notional)}</b></div>`).join("")}</div></div>
        <div class="nt-interp">${this.esc(ob.interpretation)}</div></section>`;
    }
    // 고래
    const wt = s.whaleTrades;
    if (wt) {
      const w = wt.whale, kst = (t) => new Date(t + 9 * 3600e3).toISOString().slice(11, 19);
      html += `<section class="nt-card"><div class="nt-card-h">고래 체결 <span class="muted">≥ ${cur}${big(wt.threshold)} · 최근 ${wt.windowMin.toFixed(0)}분</span></div>
        <div class="nt-kv"><span>건수</span><b>${w.count} <span class="muted">(매수 ${w.buyCount} · 매도 ${w.sellCount})</span></b></div>
        <div class="nt-kv"><span>순매수</span><b class="${w.net >= 0 ? "up" : "down"}">${w.net >= 0 ? "+" : "−"}${cur}${big(Math.abs(w.net))}</b></div>
        <div class="nt-kv"><span>시장가 매수/매도</span><b>${wt.takerBuySellRatio == null ? "–" : wt.takerBuySellRatio.toFixed(2)}</b></div>
        ${(wt.top || []).slice(0, 6).map((x) => `<div class="nt-wl"><span class="muted">${kst(x.t)}</span><span class="${x.side === "buy" ? "up" : "down"}">${x.side === "buy" ? "매수" : "매도"} ${px(x.price)}</span><b>${cur}${big(x.notional)}</b></div>`).join("")}
        <div class="nt-interp">${this.esc(wt.interpretation)}</div></section>`;
    }
    // 선물 흐름
    const ff = s.futuresFlow;
    if (ff) {
      const fa = ff.funding, oi = ff.oi;
      html += `<section class="nt-card"><div class="nt-card-h">선물 포지션 흐름 <span class="muted">바이낸스 ${this.esc(ff.symbol)} · ${ff.period}×${ff.limit}</span></div>
        ${fa ? `<div class="nt-kv"><span>펀딩비</span><b class="${fa.latestPct >= 0 ? "up" : "down"}">${fa.latestPct.toFixed(4)}% <span class="muted">/${fa.intervalH}h · 연 ${fa.latestAnnPct.toFixed(1)}%</span></b></div>` : ""}
        ${ff.premium?.nextFundingPct != null ? `<div class="nt-kv"><span>다음 펀딩 예상</span><b>${ff.premium.nextFundingPct.toFixed(4)}%</b></div>` : ""}
        ${oi ? `<div class="nt-kv"><span>미결제약정</span><b>$${big(oi.latestValue)} <span class="${oi.changePct >= 0 ? "up" : "down"}">${pc(oi.changePct)}</span></b></div><div class="nt-kv"><span>같은 기간 가격</span><b class="${oi.priceChangePct >= 0 ? "up" : "down"}">${pc(oi.priceChangePct)}</b></div>` : ""}
        ${ff.global ? `<div class="nt-kv"><span>전체 계정 롱</span><b>${ff.global.longPct.toFixed(1)}% <span class="muted">(롱/숏 ${ff.global.latest.toFixed(2)})</span></b></div><div class="nt-ls"><i style="width:${ff.global.longPct.toFixed(1)}%"></i></div>` : ""}
        ${ff.topPosition ? `<div class="nt-kv"><span>상위 트레이더 롱</span><b>${ff.topPosition.longPct.toFixed(1)}%</b></div>` : ""}
        ${ff.taker ? `<div class="nt-kv"><span>시장가 매수/매도 (6봉)</span><b>${ff.taker.recentAvg.toFixed(2)}</b></div>` : ""}
        <div class="nt-kv"><span>스퀴즈 위험</span><b>${this.esc(ff.squeezeRisk)}</b></div>
        <div class="nt-interp">${this.esc(ff.interpretation)}</div></section>`;
    }
    // 청산 추정
    const lq = f.liq;
    if (this.S.overlays.liq) {
      html += `<section class="nt-card"><div class="nt-card-h">청산 구간 <b class="heat">추정</b> <span class="muted">실제 청산 데이터 아님</span></div>`;
      if (lq) {
        const row = (x, side) => `<div class="nt-wl"><span class="${side === "long" ? "down" : "up"}">${side === "long" ? "롱" : "숏"} ${px(x.price)}</span><span class="muted">${pc(x.distPct)} · ${x.mainLev}배${x.wall ? " · 벽" : ""}</span><b>~$${big(x.estUsd)}</b></div>`;
        html += `${lq.shortClusters.slice().reverse().map((x) => row(x, "short")).join("")}<div class="nt-mid">현재 ${px(lq.price)}</div>${lq.longClusters.map((x) => row(x, "long")).join("")}
          <div class="nt-interp">${this.esc(lq.interpretation || "")} · 진입가 근거: ${this.esc(lq.entryBasis)} · 레버리지 비중은 가정값</div>`;
      } else html += `<div class="nt-empty">${tc.exchange === "upbit" ? "업비트(원화)는 청산 추정 없음 — 바이낸스 선물로 보세요" : this.esc(f.liqErr || "불러오는 중…")}</div>`;
      html += `</section>`;
    }
    if (Object.keys(s.errors || {}).length) html += `<div class="nt-dlg-note">일부 실패: ${this.esc(Object.entries(s.errors).map(([k, v]) => `${k} ${v}`).join(" · "))}</div>`;
    el.innerHTML = html;
    this._bindFlowBtns(el);
  }
  _bindFlowBtns(el) { el.querySelectorAll("[data-ovb]").forEach((b) => (b.onclick = () => this.setOverlay(b.dataset.ovb, !this.S.overlays[b.dataset.ovb]))); }

  // ------------------------------------------------------------ 전략 신호 · 백테스트 (quant.js)
  async _runStrat(silent = false) {
    const ta = this.root.querySelector(".nt-strat"), out = this.root.querySelector(".nt-strat-out"), tc = this.cur?.tc;
    const txt = ta.value.trim();
    if (!txt) { if (!silent) out.innerHTML = `<div class="nt-empty">전략 JSON 을 붙여 넣으세요 (예시 넣기)</div>`; return; }
    lsSet(STRAT_KEY, txt);
    if (!tc?.candles.length) return;
    let spec;
    try { spec = JSON.parse(txt); } catch (e) { out.innerHTML = `<div class="down">JSON 오류: ${this.esc(e.message)}</div>`; return; }
    const Q = await import("../quant.js");
    spec = { ...spec, interval: tc.interval, symbol: tc.symbol };
    const c = D.toQuant(tc.candles);
    try {
      const sig = Q.signals(spec, c), bt = Q.backtest(spec, c, { barSeconds: D.IV_SEC[tc.interval] });
      this.strat = { spec, sig, bt, tc };
      this._stratBar = tc.candles.at(-1)?.time;
      this._applyStrat();
      const st = bt.stats, n = (v, d = 2, suf = "") => v == null ? "–" : `${(+v).toFixed(d)}${suf}`, cls = (v) => v > 0 ? "up" : v < 0 ? "down" : "";
      const edges = (a) => a.reduce((k, v, i) => k + (v && !a[i - 1] ? 1 : 0), 0);
      out.innerHTML = `<div class="nt-card"><div class="nt-card-h">${this.esc(bt.spec.name)} <span class="muted">${this.esc(tc.symbol)} · ${D.IV_LABEL[tc.interval]} · ${c.length.toLocaleString()}봉</span></div>
        <div class="nt-stats">
          <div><span>수익률</span><b class="${cls(st.total_return_pct)}">${n(st.total_return_pct, 2, "%")}</b></div>
          <div><span>보유 대비</span><b class="${cls(st.buy_and_hold_pct)}">${n(st.buy_and_hold_pct, 2, "%")}</b></div>
          <div><span>최대 낙폭</span><b class="down">${n(st.max_drawdown_pct, 2, "%")}</b></div>
          <div><span>거래</span><b>${st.trades ?? 0} <span class="muted">롱 ${st.long_trades ?? 0}·숏 ${st.short_trades ?? 0}</span></b></div>
          <div><span>승률</span><b>${n(st.win_rate_pct, 1, "%")}</b></div>
          <div><span>손익비(PF)</span><b>${n(st.profit_factor)}</b></div>
          <div><span>샤프</span><b>${n(st.sharpe)}</b></div>
          <div><span>청산</span><b class="${st.liquidations ? "down" : ""}">${st.liquidations ?? 0}</b></div>
        </div>
        <div class="nt-dlg-note">신호(상승 엣지): 롱 진입 ${edges(sig.longEntry)} · 숏 진입 ${edges(sig.shortEntry)} · 롱 청산 ${edges(sig.longExit)} · 숏 청산 ${edges(sig.shortExit)}<br>레버리지 ${bt.spec.risk.leverage}배 · 수수료 ${bt.spec.risk.fee_pct}% · 다음 봉 시가 체결 · 분석용 시뮬레이션</div>
        ${bt.trades.slice(-8).reverse().map((t) => `<div class="nt-wl"><span class="${t.side === "long" ? "up" : "down"}">${t.side === "long" ? "롱" : "숏"} ${tc.px(t.entryP)}→${tc.px(t.exitP)}</span><span class="muted">${new Date(t.exitT).toLocaleDateString("ko-KR")} · ${this.esc(t.reason)}</span><b class="${cls(t.pnlPct)}">${n(t.pnlPct, 1, "%")}</b></div>`).join("")}</div>`;
    } catch (e) {
      this.strat = null; this.cells.forEach((x) => x.tc.setStrategyMarkers([]));
      out.innerHTML = `<div class="down">${this.esc(e.message || e)}</div>${e.problems ? `<ul>${e.problems.map((p) => `<li>${this.esc(p)}</li>`).join("")}</ul>` : ""}`;
    }
  }
  _applyStrat() {
    const st = this.strat;
    this.cells.forEach((x) => { if (!st || x.tc !== st.tc) x.tc.setStrategyMarkers([]); });
    if (!st) return;
    const tc = st.tc, c = tc.candles, mk = [], up = "#26a69a", dn = "#ef5350";
    if (this.S.stratMode === "trades") {
      const bt = (t) => tc._barTime(Math.floor(t / 1000));
      for (const t of st.bt.trades) {
        const long = t.side === "long", et = bt(t.entryT), xt = bt(t.exitT);
        if (et) mk.push({ time: et, position: long ? "belowBar" : "aboveBar", shape: long ? "arrowUp" : "arrowDown", color: long ? up : dn, text: long ? "롱" : "숏" });
        if (xt) mk.push({ time: xt, position: long ? "aboveBar" : "belowBar", shape: "circle", color: t.pnl > 0 ? up : dn, size: 0.7, text: `${t.pnlPct >= 0 ? "+" : ""}${t.pnlPct.toFixed(1)}%` });
      }
    } else {
      const s = st.sig, edge = (a, i) => a[i] && !a[i - 1];
      for (let i = 0; i < c.length; i++) {
        if (edge(s.longEntry, i)) mk.push({ time: c[i].time, position: "belowBar", shape: "arrowUp", color: up, text: "롱 신호" });
        if (edge(s.shortEntry, i)) mk.push({ time: c[i].time, position: "aboveBar", shape: "arrowDown", color: dn, text: "숏 신호" });
        if (edge(s.longExit, i)) mk.push({ time: c[i].time, position: "aboveBar", shape: "circle", color: "#b2b5be", size: 0.6, text: "롱 청산" });
        if (edge(s.shortExit, i)) mk.push({ time: c[i].time, position: "belowBar", shape: "circle", color: "#b2b5be", size: 0.6, text: "숏 청산" });
      }
    }
    // 마커 글자가 화면을 덮지 않게 최근 60개만 글자 표시
    mk.forEach((m, i) => { if (i < mk.length - 60) m.text = ""; });
    tc.setStrategyMarkers(mk);
  }
}

function paramText(s) {
  const v = Object.entries(s.params || {}).filter(([k]) => !["expr", "overlay", "name", "source"].includes(k)).map(([, x]) => x);
  return v.join(", ");
}
function fmtLeft(sec) {
  sec = Math.max(0, Math.floor(sec));
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60), x = sec % 60, z = (n) => String(n).padStart(2, "0");
  return d ? `${d}일 ${z(h)}:${z(m)}:${z(x)}` : h ? `${z(h)}:${z(m)}:${z(x)}` : `${z(m)}:${z(x)}`;
}
