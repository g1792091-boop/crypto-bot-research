// 누리 차트 터미널 — 트레이딩뷰 방식 분석 화면 (분석 전용: 주문 버튼 없음)
// 사용: import { openTerminal, closeTerminal } from "./terminal/terminal.js";
//       openTerminal({market: "BTCUSDT", exchange: "binancef", interval: "1h"}, {esc, onClose, ws});
//       (ctx.toast 는 쓰지 않는다 — 앱 알림이 전체 화면 아래에 가려지므로 터미널 안에 따로 띄움 · ws:false 면 웹소켓 끔)
//       새 탭으로 열 때는 terminal/index.html?market=NVDA&exchange=yahoo&interval=1d
// 전체 화면 오버레이 · 종목 검색 · 거래소 · 봉 간격 · 차트 종류 · 로그 · 지표(편집) · 그리기 도구 · 흐름 오버레이(호가 벽 · 고래 · 청산 추정) ·
// 흐름 패널 · 전략 신호/백테스트 · 1×1 / 1×2 / 2×2 · 스크린샷 · 전체 과거
import * as D from "./data.js";
import { DEFS, PALETTE, Q_GROUPS, X_GROUPS, loadCustom, labelOf } from "./registry.js";
import * as CR from "./chartread.js";

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
export const _term = () => T;   // 시험용: 열린 터미널

export async function openTerminal({ market = "BTCUSDT", exchange, interval = "1h" } = {}, ctx = {}) {
  // 거래소를 안 주면 종목으로 짐작 (BTCUSDT → 바이낸스 선물 · KRW-BTC → 업비트 · NVDA/005930/^KS11/ES=F → 야후)
  if (!D.EX_SHORT[exchange]) exchange = D.guessExchange(market, "binancef");
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

export function closeTerminal() { if (T) { const t = T; T = null; t.destroy(); try { t.ctx.onClose?.(); } catch (e) { /* 무시 */ } } }

class Terminal {
  constructor(ctx, lib, want) {
    this.ctx = ctx; this.lib = lib; this.esc = lib.esc || esc0;
    const saved = lsGet(KEY, {});
    this.S = {
      inds: Array.isArray(saved.inds) ? saved.inds.filter((s) => s && DEFS[s.key]).map((s) => ({ ...s, id: s.id || uid() })) : DEFAULT_INDS(),
      ctype: saved.ctype || "candles", log: !!saved.log, overlays: { walls: false, whales: false, liq: false, ...(saved.overlays || {}) },
      layout: LAYOUTS[saved.layout] ? +saved.layout : 1, cells: Array.isArray(saved.cells) ? saved.cells.filter((c) => c && D.EX_SHORT[c.exchange] && c.symbol) : [],
      // 휴대폰은 차트부터 (패널 닫힘)
      active: 0, side: innerWidth < 760 ? false : saved.side ?? (innerWidth > 1100), tab: saved.tab || "flow", magnet: !!saved.magnet, stay: !!saved.stay, stratMode: saved.stratMode || "signals",
      aiShow: {combo: true, pattern: true, ic: true, calls: true, local: true, ...(saved.aiShow || {})},
    };
    this.S.cells[0] = want;
    this.cells = [];
    this.strat = null;   // {spec, result}
    this._build();
    this._applyLayout();
    // AI 팀 분석이 새로 오면 차트 위 표시와 'AI 팀' 탭을 다시 그림
    import("../analysisbus.js").then((B) => { this.bus = B; this._unbus = B.onChange(() => { this._applyAi(); if (this.S.side && this.S.tab === "ai") this._renderAi(); }); this._applyAi(); }).catch(() => {});
    this._save();
    this.root.focus();
  }

  // 앱의 알림(ctx.toast)은 이 전체 화면 아래에 가려지므로 터미널 안에 직접 띄운다
  toast(msg, kind) {
    const el = this.root.querySelector(".nt-toast");
    el.textContent = msg; el.className = "nt-toast" + (kind === "err" ? " err" : ""); el.hidden = false;
    this.statusEl.querySelector(".nt-st-msg").textContent = msg;
    clearTimeout(this._toastT); this._toastT = setTimeout(() => (el.hidden = true), kind === "err" ? 5000 : 2600);
  }
  _save() {
    const S = this.S;
    lsSet(KEY, { inds: S.inds, ctype: S.ctype, log: S.log, overlays: S.overlays, layout: S.layout, cells: S.cells, side: S.side, tab: S.tab, magnet: S.magnet, stay: S.stay, stratMode: S.stratMode, aiShow: S.aiShow });
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
        <button data-nt="lab" class="nt-lab-btn" title="내 차트에 띄운 보조지표로: 노이즈 적은 값 찾기 → 매매법 만들기 → 검증(처음 보는 구간·다른 코인) → 데모 투입 → 지금 포지션 실시간">🔬 내 지표</button>
        <button data-nt="read" class="nt-read-btn" title="내 차트 읽기(가격·지표 실시간 값·그린 선 레벨·가격 흐름) · 구조화 JSON 리포트 · 멀티 심볼 비교 · 시니어 트레이더 결정(JSON) · 전략 분석 5항목 — 숫자는 봉 데이터에서 계산, AI 는 해설만">📖 차트 AI</button>
        <button data-nt="mkt" class="nt-mkt-btn" title="지금 이 코인에 시장가로 들어간다면? — 지지·저항·매수벽/매도벽·15분/1시간/4시간 추세·내 보조지표를 분석하고 GH Coin 에이전트 팀과 뉴트론이 토론해 롱/숏·손절·익절·승률을 알려줍니다 (주문은 안 함)">⚡ 시장가</button>
        <span class="nt-grow"></span>
        <span class="nt-badge" title="분석 전용 — 주문은 트레이딩 모듈에서">분석 전용</span>
        <button class="nt-close" data-nt="close" title="닫기 (Esc)" aria-label="닫기">✕</button>
      </div>
      <div class="nt-body">
        <nav class="nt-tools" aria-label="그리기 도구">${TOOLS_HTML}</nav>
        <div class="nt-grid"></div>
        <aside class="nt-side" hidden>
          <div class="nt-tabs"><button data-tab="flow">흐름</button><button data-tab="ai">🤖 AI 팀</button><button data-tab="lab">🧪 실험</button><button data-tab="strat">전략</button><button class="nt-side-x" data-nt="side" aria-label="패널 닫기">✕</button></div>
          <div class="nt-pane" data-pane="flow"></div>
          <div class="nt-pane" data-pane="ai"><div class="nt-ai"></div></div>
          <div class="nt-pane" data-pane="lab"><div class="nt-lab"></div></div>
          <div class="nt-pane" data-pane="strat">
            <div class="nt-st-help">전략 JSON(quant.js 형식)을 붙여 넣으면 지금 차트 캔들로 신호와 백테스트를 계산해 표시합니다. <a href="#" data-nt="example">예시 넣기</a></div>
            <textarea class="nt-strat" spellcheck="false" placeholder='{"indicators":[...], "long_entry":{...}, "short_entry":{...}, "risk":{...}}'></textarea>
            <div class="nt-row"><button class="nt-primary" data-nt="strat-run">실행</button><select class="nt-strat-mode"><option value="signals">신호 표시</option><option value="trades">백테스트 거래 표시</option></select><button data-nt="strat-clear">지우기</button></div>
            <div class="nt-strat-out"></div>
          </div>
        </aside>
      </div>
      <div class="nt-status"><span class="nt-st-src"></span><span class="nt-st-live"></span><span class="nt-st-cd"></span><span class="nt-st-msg"></span></div>
      <div class="nt-modal" hidden><div class="nt-dlg" role="dialog"></div></div>
      <div class="nt-toast" role="status" hidden></div>`;
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
    clearInterval(this._cd); this._unbus?.();
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
      onLoad: (tc) => { cell.dr.load(); this._applyAi(); if (this.cur === cell) { this._syncToolbar(); if (this.strat) this._runStrat(true); if (S.side && S.tab === "ai") this._renderAi(); } },
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
    if (b.dataset.tab) { S.tab = b.dataset.tab; this._save(); this._syncSide(); if (S.tab === "flow") this.cur?.tc.refreshFlow(); return; }
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
      case "mkt": this._marketEntry(); break;
      case "lab": this._chartLab(); break;
      case "read": this._chartRead(); break;
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
    if (S.side && S.tab === "ai") this._renderAi();
    if (S.side && S.tab === "lab") this._renderLab();
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
      const rows = list._rows || [], exact = rows.find((x) => x.s.toUpperCase() === q.toUpperCase());
      if (exact || rows[0]) return pick(exact || rows[0]);   // 목록 첫 줄 (트레이딩뷰처럼)
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
    if (!matchMedia("(pointer: coarse)").matches) setTimeout(() => inp.focus(), 30);
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
    this.dlg.onclick = (e) => {
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
    };
    render(); if (!matchMedia("(pointer: coarse)").matches) setTimeout(() => q.focus(), 30);   // 휴대폰은 키보드가 화면을 가리지 않게
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
        const el = f.querySelector(`[name="${k}"]`);   // f.elements.length 처럼 이름이 겹치는 속성을 피한다
        if (!el) continue;
        if (k === "overlay") np[k] = el.checked ? 1 : 0;
        else if (typeof v0 === "number") { const x = parseFloat(el.value); np[k] = Number.isFinite(x) ? x : v0; }
        else np[k] = el.value;
      }
      s.params = np; s.color = f.querySelector('[name="__color"]').value;
      this._indsChanged(); done();
    };
  }

  // ------------------------------------------------------------ 대화상자
  _openModal(html, kind) {
    this._modalKind = kind;
    this.dlg.onclick = null;
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
  // ------------------------------------------------------------ ⚡ 시장가 (손매매용): GH Coin 분석 + 에이전트 팀 ↔ 뉴트론 토론
  async _marketEntry() {
    const cfg = this.S.cells[this.S.active] || {}, e = (x) => this.esc(String(x ?? ""));
    if (typeof window.ghCoinMarketEntry !== "function") { this.toast("⚡ 시장가는 GH Coin 앱에서 쓸 수 있습니다 (GHCoin.exe)", "err"); return; }
    let sym = String(cfg.symbol || "BTCUSDT").toUpperCase(); const m = sym.match(/^KRW-(\w+)$/); if (m) sym = m[1] + "USDT"; if (!/USDT$/.test(sym)) sym += "USDT";
    let pn = this.root.querySelector(".nt-mkt:not(.nt-mylab)"); if (!pn) { pn = document.createElement("div"); pn.className = "nt-mkt"; this.root.appendChild(pn); }
    const steps = [];
    if (this._mktBusy) return; this._mktBusy = true;
    const live = !!this._mktLive, head = `<div class="nt-mkt-h"><b>⚡ 시장가 · ${e(sym.replace("USDT", ""))}</b><span class="muted">${live ? "🔴 실시간 · " + new Date().toLocaleTimeString("ko-KR") : "코인 선물 기준 · 주문은 직접"}</span><label class="nt-mkt-live" title="60초마다 다시 분석 (토론은 5분에 한 번)"><input type="checkbox" data-live ${live ? "checked" : ""}> 실시간</label><button data-x>✕</button></div>`;
    const stop = () => { clearInterval(this._mktTimer); this._mktTimer = 0; this._mktLive = false; };
    const paint = (body) => { pn.innerHTML = head + body; pn.querySelector("[data-x]").onclick = () => { stop(); pn.remove(); };
      pn.querySelector("[data-live]").onchange = (ev) => { if (ev.target.checked) { this._mktLive = true; this._mktSym = sym; clearInterval(this._mktTimer); this._mktTimer = setInterval(() => { if (!this.root.isConnected || !this.root.querySelector(".nt-mkt:not(.nt-mylab)")) return stop(); this._marketEntry(); }, 60e3); } else stop(); }; };
    const debate = !live || !this._mktDebAt || Date.now() - this._mktDebAt > 5 * 60e3; if (debate) this._mktDebAt = Date.now();
    if (!live || !pn.innerHTML) paint(`<div class="nt-mkt-st">분석 시작…</div>`);
    const btn = this.root.querySelector('[data-nt="mkt"]'); if (btn) btn.disabled = true;
    try {
      const r = await window.ghCoinMarketEntry(sym, (t) => { steps.push(t); if (!live) paint(`<div class="nt-mkt-st">${steps.map((x, i) => `<div>${i === steps.length - 1 ? "⏳" : "✓"} ${e(x)}</div>`).join("")}</div>`); }, { debate });
      if (!debate && this._mktLast?.best?.debate && !r.best.debate?.team) r.best.debate = { ...this._mktLast.best.debate, verdict: (this._mktLast.best.debate.verdict || "") + " (최근 토론)" };
      this._mktLast = r;
      const b = r.best, o = r.other, d = r.decision, L = b.side > 0, f = (v) => v == null ? "—" : (+v >= 1000 ? Math.round(+v).toLocaleString() : (+v).toPrecision(6).replace(/\.?0+$/, ""));
      const db = b.debate || {}, side = (x) => `<div class="nt-mkt-cmp ${x === b ? "on" : ""}"><b class="${x.side > 0 ? "up" : "down"}">${x.side > 0 ? "롱" : "숏"}</b> 익절1 도달 ${x.wr}% · 기대값 ${x.exp >= 0 ? "+" : ""}${x.exp}R${x.my ? ` · 내 지표 같은 상태 ${x.my.wr}%` : ""} · <span class="muted">${e(x.grade)}</span></div>`;
      const sw = r.swing, dz = r.daily, ck = r.checklist || [], ckOk = ck.filter((x) => x[1] === true).length, ckN = ck.filter((x) => x[1] != null).length;
      const swHtml = sw ? `<div class="nt-mkt-sec">🏆 일봉 검증 셋업 — ${e(sw.name)}</div>
        <div class="nt-mkt-chips"><span>승률 ${sw.wr}%</span><span>손익비 ${sw.pf}</span><span>${sw.n}건 · 4년 · ${sw.pos}/${sw.coins}코인 이익</span><span>전반 ${sw.pf1} / 후반 ${sw.pf2}</span></div>
        <div class="nt-mkt-px"><div><small>시장가 ${sw.side > 0 ? "롱" : "숏"}</small><b>${f(sw.entry)}</b></div><div><small>손절 −${sw.slPct}% (일봉 ATR×3)</small><b class="down">${f(sw.sl)}</b></div><div><small>${sw.target ? "1차 목표(5일선)" : "익절"}</small><b class="up">${sw.target ? f(sw.target) : "규칙 청산"}</b></div><div><small>레버리지</small><b>≤${sw.lev}x</b></div></div>
        <div class="muted">청산 규칙: ${e(sw.exitKo)} · 포지션 크기: 계좌 $1,000당 $${sw.per1000.toLocaleString()} (손절 시 계좌의 1% 손실) · 청산가 ${f(sw.liq)} · 며칠 보유하는 스윙이라 단타 손절·익절과 다릅니다</div>`
        : dz ? `<div class="nt-mkt-sec">📅 일봉 검증 셋업 — 지금은 신호 없음 (기다리는 자리)</div><div class="nt-mkt-chips">${(dz.watch || []).map((x) => `<span class="n">${e(x)}</span>`).join("") || `<span class="n">대기 조건 없음</span>`}${(dz.chased || []).map((x) => `<span class="w">${e(x)} 신호는 났지만 이미 1 ATR 넘게 진행 — 추격 금지</span>`).join("")}</div>` : "";
      paint(`<div class="nt-mkt-dec ${d.go ? "go" : "no"}">${e(d.label)}</div>
        ${swHtml}
        ${ck.length ? `<div class="nt-mkt-sec">✅ 진입 전 체크리스트 ${ckOk}/${ckN}</div><div class="nt-mkt-chips">${ck.map((x) => `<span class="${x[1] === true ? "" : x[1] === false ? "w" : "n"}">${x[1] === true ? "✓" : x[1] === false ? "✗" : "?"} ${e(x[0])}</span>`).join("")}</div>` : ""}
        <div class="nt-mkt-sec">${sw ? "단타 계획(참고 — 검증된 우위 없음)" : "단타 계획"}</div>
        <div class="nt-mkt-px"><div><small>시장가</small><b>${f(b.entry)}</b></div><div><small>손절 −${b.slPct}%</small><b class="down">${f(b.sl)}</b></div><div><small>익절1 ${b.rr1}R</small><b class="up">${f(b.tp1)}</b></div><div><small>익절2 ${b.rr}R</small><b class="up">${f(b.tp2)}</b></div></div>
        <div class="muted">권장 레버 ≤${b.lev}x · 청산 ${f(b.liq)} · 익절1에서 절반 익절 후 손절을 본전으로 · 포지션 크기: 계좌 $1,000당 $${Math.round(10 / (b.slPct / 100)).toLocaleString()} (손절 시 1% 손실)</div>
        <details class="muted"><summary>단타 셋업 실제 검증표 (1년·6코인·수수료 포함) — 왜 '비권장'이 자주 나오나</summary>눌림목 회복 48% / −0.06R · 돌파 후 리테스트 48% / −0.09R · 유동성 스윕 48% / −0.14R · 고가 돌파 추격 46% / −0.05R (1시간봉, 익절1 도달률 / 기대값). 15분봉은 더 나쁨(−0.12~−0.18R). 일봉 추세 방향으로만 걸러도 47~51%. 같은 검증을 통과한 것은 일봉 추세추종과 일봉 눌림 매수(승률 74%·손익비 1.49)뿐입니다.</details>
        <div class="nt-mkt-sec">롱 vs 숏</div>${side(b)}${side(o)}
        <div class="nt-mkt-sec">근거</div><div class="nt-mkt-chips">📌 ${e(b.evidence)}</div>${b.daily ? `<div class="nt-mkt-chips"><span class="${b.daily.dir === -b.side ? "w" : ""}">📅 일봉 추세 ${e(b.daily.label)} (50일선 ${b.daily.distPct >= 0 ? "+" : ""}${b.daily.distPct}%)${b.daily.dir === -b.side ? " — 역행" : b.daily.dir === b.side ? " — 같은 방향" : ""}</span></div>` : ""}<div class="nt-mkt-chips">${b.why.map((x) => `<span>${e(x)}</span>`).join("")}${b.warn.map((x) => `<span class="w">${e(x)}</span>`).join("")}</div>
        ${r.myInd?.length ? `<div class="nt-mkt-sec">내 차트 지표 (5분 / 15분 / 1시간)</div><div class="nt-mkt-chips">${r.myInd.map((x) => { const a = (v) => v > 0 ? "↑" : v < 0 ? "↓" : "·", sc = (x.d5 || 0) + x.d15 + x.d1h; return `<span class="${sc > 0 ? "" : sc < 0 ? "w" : "n"}">${e(x.name)} ${a(x.d5)}/${a(x.d15)}/${a(x.d1h)}</span>`; }).join("")}</div>` : `<div class="muted">차트에 띄운 보조지표가 없어 지표 비교는 생략</div>`}
        <div class="nt-mkt-sec">지지·저항·벽 (가까운 순) <span class="muted" style="font-weight:400" title="2026-10-05 실측(6코인·1시간봉 5,800건): 레벨에 닿은 뒤 1 ATR 반등이 1 ATR 이탈보다 먼저 온 비율 51.1% · 아무 가격이나 골랐을 때 50.7%. 밀도 군집(DBSCAN)으로 바꿔도 51.1%로 같음">· 반등 예측력은 확인 안 됨(51% vs 무작위 51%) — 손절·익절 위치 참고용</span></div><div class="nt-mkt-chips">${(r.levels || []).slice().sort((a, c) => Math.abs(a.price - r.price) - Math.abs(c.price - r.price)).slice(0, 8).map((l) => `<span class="${l.price > r.price ? "w" : ""}">${f(l.price)} ${e(l.src.join("+"))}</span>`).join("")}</div>
        <div class="nt-mkt-sec">⚖ 토론 · ${e(db.verdict || "")}</div>
        <div class="nt-mkt-db"><b>에이전트 팀(${e(db.team?.who || "")})</b> ${e(db.team?.pick || db.team?.stance || "")} — ${e(db.team?.reason || "")}${db.team?.applied ? ` <span class="muted">(${e(db.team.applied)})</span>` : ""}</div>
        <div class="nt-mkt-db"><b>뉴트론(${e(db.neural?.model || "—")})</b> ${e(db.neural?.stance || "—")} — ${e(db.neural?.reason || "")}</div>
        ${db.final ? `<div class="nt-mkt-db"><b>팀 최종</b> ${db.final.keep ? "유지" : "철회"} — ${e(db.final.reason)}</div>` : ""}
        <div class="muted nt-mkt-foot">승률·기대값은 과거 비슷한 상황을 같은 손절·익절로 시뮬레이션한 값(수수료 포함, 보정)입니다. 2개월 표본외 검증에서 지표·지지저항·호가 조합만으로는 우위가 없었고, '진입 가능'은 검증된 매매법 신호가 있을 때만 표시합니다. 차트에 진입·손절·익절·레벨 선이 그려집니다.</div>`);
      this._applyAi?.(); this._renderAi?.();
    } catch (err) { paint(`<div class="down" style="padding:8px">분석 실패: ${e(err.message || err)}</div>`); }
    if (btn) btn.disabled = false; this._mktBusy = false;
  }
  // ------------------------------------------------------------ 🔬 내 지표 연구소: 노이즈 튜닝 → 매매법 → 검증 → 데모 투입 → 지금 포지션(30초 갱신)
  // 📖 차트 AI — 차트 읽기(3-1) · JSON 리포트(3-2) · 멀티 심볼 비교(3-3) · 트레이더 결정(3-4) · 전략 분석(3-5). 숫자는 화면에 떠 있는 봉·지표·그린 선에서 코드가 계산한다.
  async _chartRead(tab) {
    const cfg = this.S.cells[this.S.active] || {}, e = (x) => this.esc(String(x ?? "")), tc = this.cur?.tc;
    if (!tc?.candles?.length) { this.toast("차트가 아직 안 열렸습니다", "err"); return; }
    this._readTab = tab || this._readTab || "read";
    let pn = this.root.querySelector(".nt-read"); if (!pn) { pn = document.createElement("div"); pn.className = "nt-mkt nt-read"; this.root.appendChild(pn); }
    const TABS = [["read", "차트 읽기"], ["json", "JSON 리포트"], ["cmp", "멀티 비교"], ["trader", "트레이더 결정"], ["strat", "전략 분석"]];
    const head = `<div class="nt-mkt-h"><b>📖 차트 AI · ${e(String(cfg.symbol).replace("USDT", ""))} ${e(D.IV_LABEL[cfg.interval] || cfg.interval)}</b><button data-x>✕</button></div><div class="nt-read-tabs">${TABS.map(([k, n]) => `<button data-rt="${k}" class="${k === this._readTab ? "on" : ""}">${n}</button>`).join("")}</div>`;
    const copy = (txt) => { try { navigator.clipboard.writeText(txt); this.toast("복사했습니다"); } catch (err) { this.toast("복사 실패", "err"); } };
    const paint = (body) => { pn.innerHTML = head + body; pn.querySelector("[data-x]").onclick = () => pn.remove(); pn.querySelectorAll("[data-rt]").forEach((b) => (b.onclick = () => this._chartRead(b.dataset.rt))); };
    const f = (v) => v == null ? "—" : (Math.abs(+v) >= 1000 ? (+v).toLocaleString("en-US", { maximumFractionDigits: 2 }) : String(v));
    const app = (name) => typeof window[name] === "function";
    let sym = String(cfg.symbol || "BTCUSDT").toUpperCase(); const mm = sym.match(/^KRW-(\w+)$/); if (mm) sym = mm[1] + "USDT";
    paint(`<div class="nt-mkt-st">읽는 중…</div>`);
    try {
      const R = await CR.readChart({ exchange: cfg.exchange, symbol: cfg.symbol, interval: cfg.interval, candles: tc.candles, inds: this.S.inds, ctype: this.S.ctype });
      this._readLast = R;
      if (this._readTab === "read") {
        const inds = R.active_indicators.map((i) => `<tr><td>${e(i.name)}</td><td>${i.error ? "계산 오류" : e(i.note || Object.entries(i.values || {}).map(([k, v]) => `${k} ${f(v)}`).join(" · ") || "—")}${i.signal ? ` <span class="${i.signal.dir === "up" ? "up" : i.signal.dir === "down" ? "down" : "muted"}">${e(i.signal.text || "")}${i.signal.dir === "up" ? "▲" : i.signal.dir === "down" ? "▼" : ""} ${i.signal.bars_ago}봉 전</span>${i.signal.stat ? ` <span class="muted">(과거 적중 ${i.signal.stat.hit}% vs 기준 ${i.signal.stat.base}% · ${e(i.signal.stat.grade)})</span>` : ""}` : ""}</td></tr>`).join("");
        const lv = R.key_levels.map((l) => `<tr><td class="${l.price > R.last_price ? "down" : "up"}">${f(l.price)}</td><td>${l.dist_pct >= 0 ? "+" : ""}${l.dist_pct}%</td><td>${e(l.label)} <span class="muted">· ${e(l.src)}</span></td></tr>`).join("");
        paint(`<div class="nt-mkt-px"><div><small>현재가</small><b>${f(R.last_price)}</b></div><div><small>직전 봉 대비</small><b class="${R.change_pct_bar >= 0 ? "up" : "down"}">${R.change_pct_bar >= 0 ? "+" : ""}${R.change_pct_bar}%</b></div><div><small>100봉 대비</small><b class="${R.change_pct_100_bars >= 0 ? "up" : "down"}">${R.change_pct_100_bars >= 0 ? "+" : ""}${R.change_pct_100_bars}%</b></div><div><small>레짐</small><b>${e(R.regime.ko)}</b></div></div>
          <div class="muted">RSI(14) ${R.rsi14 ?? "—"} · ADX ${R.regime.adx ?? "—"} · ATR ${R.regime.atrPct ?? "—"}% (최근 200봉 중 상위 ${100 - (R.regime.atrRank ?? 0)}%)</div>
          <div class="nt-mkt-sec">표시된 지표와 실시간 값 (${R.active_indicators.length})</div>${inds ? `<table class="nt-read-t">${inds}</table>` : `<div class="muted">차트에 띄운 지표가 없습니다 — [지표]에서 추가하면 여기에 값이 나옵니다</div>`}
          <div class="nt-mkt-sec">차트의 선·라벨 레벨 — 높은 순 (${R.key_levels.length})</div>${lv ? `<table class="nt-read-t">${lv}</table>` : `<div class="muted">그린 선·AI 팀 선이 없습니다 — 수평선·추세선·피보나치·롱/숏 포지션 도구를 그리면 읽습니다</div>`}
          <div class="nt-mkt-sec">최근 가격 흐름</div><div>${e(R.price_action)}</div>
          <div class="nt-mkt-sec">🤖 AI 해설</div><div class="nt-read-ai muted">${app("ghCoinChartAI") ? "아래 버튼을 누르면 위 숫자만 근거로 해설합니다" : "AI 해설은 GH Coin 앱에서 쓸 수 있습니다"}</div>
          <div class="nt-row"><button data-do="ai" ${app("ghCoinChartAI") ? "" : "disabled"}>🤖 AI 해설</button> <button data-do="copy">📋 글로 복사</button></div>`);
        pn.querySelector('[data-do="copy"]').onclick = () => copy(CR.readText(R));
        const ab = pn.querySelector('[data-do="ai"]'); if (ab) ab.onclick = async () => { ab.disabled = true; const box = pn.querySelector(".nt-read-ai"); box.textContent = "해설 작성 중… (로컬 모델은 10~40초)"; try { const r = await window.ghCoinChartAI({ report: R }); box.classList.remove("muted"); box.textContent = r.text || "AI 가 답하지 못했습니다(모델 연결 확인)"; } catch (err) { box.textContent = "실패: " + (err.message || err); } ab.disabled = false; };
      } else if (this._readTab === "json") {
        const J = CR.reportJSON(R, this._shotPath || null), txt = JSON.stringify(J, null, 2);
        paint(`<div class="muted">저널·티켓·파이프라인에 그대로 붙일 수 있는 고정 형식입니다. screenshot_path 는 [스크린샷 저장]을 누르면 채워집니다.</div><pre class="nt-read-pre">${e(txt)}</pre><div class="nt-row"><button data-do="copy">📋 JSON 복사</button> <button data-do="shot">📷 스크린샷 저장</button></div>`);
        pn.querySelector('[data-do="copy"]').onclick = () => copy(txt);
        pn.querySelector('[data-do="shot"]').onclick = () => { const d = new Date(), z = (n) => String(n).padStart(2, "0"); this._shotPath = `${tc.symbol.replace(/[^\w.-]/g, "_")}_${tc.interval}_${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}_${z(d.getHours())}${z(d.getMinutes())}.png`; this._shot(); setTimeout(() => this._chartRead("json"), 300); };
      } else if (this._readTab === "cmp") {
        paint(`<div class="nt-mkt-st">6개 코인 ${e(D.IV_LABEL[cfg.interval] || cfg.interval)}봉 불러오는 중…</div>`);
        const C = await CR.compare(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT"], D.IV_SEC[cfg.interval] ? cfg.interval : "1h", "binancef");
        const rows = C.rows.map((x) => x.error ? `<tr><td>${e(x.symbol)}</td><td colspan="5">오류: ${e(x.error)}</td></tr>` : `<tr><td><b>${e(x.symbol.replace("USDT", ""))}</b>${x.symbol === C.strongest ? " 🥇" : ""}</td><td>${f(x.last_price)}</td><td class="${x.change_pct_100_bars >= 0 ? "up" : "down"}">${x.change_pct_100_bars >= 0 ? "+" : ""}${x.change_pct_100_bars}%</td><td class="${x.rsi14 >= 70 ? "down" : x.rsi14 <= 30 ? "up" : ""}">${x.rsi14}</td><td>${x.volume_confirmed ? "✅" : "—"} ${x.volume_ratio}배</td><td>${e(x.regime_ko)}</td></tr>`).join("");
        paint(`<table class="nt-read-t"><tr><th>심볼</th><th>마지막 가격</th><th>100봉 변화율</th><th>RSI(14)</th><th>거래량 확인</th><th>레짐</th></tr>${rows}</table><div class="muted">${e(C.note)} · 🥇 = 100봉 변화율 1위 · 바이낸스 선물 기준</div><div class="nt-row"><button data-do="copy">📋 JSON 복사</button></div>`);
        pn.querySelector('[data-do="copy"]').onclick = () => copy(JSON.stringify(C, null, 2));
      } else if (this._readTab === "trader") {
        if (!app("ghCoinTrader")) { paint(`<div class="muted">트레이더 결정은 GH Coin 앱에서 쓸 수 있습니다 (GHCoin.exe)</div>`); return; }
        const last = this._traderLast && this._traderLast.symbol === sym ? this._traderLast : null;
        const show = (T) => { const cls = T.action === "ENTER" ? "go" : "no", J = { ...T }; delete J.meta;
          paint(`<div class="nt-mkt-dec ${cls}">${e(T.action)}${T.side ? " " + e(T.side) : ""} · 확신도 ${T.confidence}</div><div>${e(T.rationale)}</div>
            <div class="nt-mkt-px"><div><small>기준가</small><b>${f(T.entry_ref)}</b></div><div><small>손절</small><b class="down">${f(T.stop_loss)}</b></div><div><small>목표</small><b class="up">${f(T.take_profit)}</b></div><div><small>손익비 · 크기</small><b>${T.risk_reward ?? "—"} · ${T.size_pct}%</b></div></div>
            <div class="nt-mkt-sec">운영 규칙 점검 (코드가 집행)</div><table class="nt-read-t">${(T.meta?.rules || []).map((r) => `<tr><td>${e(r[0])}</td><td>${e(r[1])}</td></tr>`).join("")}</table>
            <div class="nt-mkt-sec">결정 JSON (감사 기록에 저장됨)</div><pre class="nt-read-pre">${e(JSON.stringify(J, null, 2))}</pre>
            <div class="muted">size_pct = 계좌 대비 포지션(명목) 크기 — 손절 시 계좌의 약 1% 손실 기준 · 차트에 롱/숏 포지션 도구를 그려 두면 그 포지션의 관리(HOLD·REDUCE·EXIT)를 판단합니다 · 주문은 하지 않습니다</div>
            <div class="nt-row"><button data-do="run">🎯 다시 판단</button> <button data-do="copy">📋 JSON 복사</button></div>`);
          pn.querySelector('[data-do="copy"]').onclick = () => copy(JSON.stringify(J, null, 2)); pn.querySelector('[data-do="run"]').onclick = run; };
        const run = async () => { const steps = []; paint(`<div class="nt-mkt-st">시작…</div>`);
          try { const T = await window.ghCoinTrader({ sym, interval: ["15m", "1h", "4h", "1d"].includes(cfg.interval) ? cfg.interval : "1h", onStep: (t) => { steps.push(t); paint(`<div class="nt-mkt-st">${steps.map((x, i) => `<div>${i === steps.length - 1 ? "⏳" : "✓"} ${e(x)}</div>`).join("")}</div>`); } }); this._traderLast = T; show(T); }
          catch (err) { paint(`<div class="nt-mkt-st">실패: ${e(err.message || err)}</div><div class="nt-row"><button data-do="run">다시</button></div>`); pn.querySelector('[data-do="run"]').onclick = run; } };
        if (last) show(last); else { paint(`<div>시니어 트레이더 운영 규칙으로 지금 이 코인을 판단합니다: ① 레짐 → 편향 → 포지션 크기 ② ATR 손절·손익비 1:2 ③ 추적 손절·부분 익절·펀딩비 ④ 목표·추적 손절·레짐 전환 시 청산 ⑤ 감사 기록.</div><div class="muted">진입(ENTER)은 검증된 근거(일봉 검증 셋업 또는 워크포워드 통과 신호)가 있을 때만 나옵니다. AI 는 더 보수적으로만 바꿀 수 있습니다.</div><div class="nt-row"><button data-do="run">🎯 지금 판단</button></div>`); pn.querySelector('[data-do="run"]').onclick = run; }
      } else if (this._readTab === "strat") {
        if (!app("ghCoinStratReview")) { paint(`<div class="muted">전략 분석은 GH Coin 앱에서 쓸 수 있습니다 (GHCoin.exe)</div>`); return; }
        let spec = null; try { const raw = this.root.querySelector(".nt-strat")?.value || ""; if (raw.trim()) spec = JSON.parse(raw); } catch (err) { spec = null; }
        const tfMap = { "15m": "15", "1h": "60", "4h": "240", "1d": "D" };
        const run = async (useSpec) => { const steps = []; paint(`<div class="nt-mkt-st">시작…</div>`);
          try { const r = await window.ghCoinStratReview({ ...(useSpec && spec ? { spec, market: sym, tf: tfMap[cfg.interval] || "60" } : {}), onStep: (t) => { steps.push(t); paint(`<div class="nt-mkt-st">${steps.map((x, i) => `<div>${i === steps.length - 1 ? "⏳" : "✓"} ${e(x)}</div>`).join("")}</div>`); } });
            if (!r) { paint(`<div class="muted">분석할 전략이 없습니다 — 패널의 [전략] 탭에 전략 JSON 을 넣거나 데모 전략이 생긴 뒤 다시 누르세요</div>`); return; }
            paint(`<div class="nt-mkt-sec">${e(r.name)} · ${e(String(r.market).replace("USDT", ""))} · ${r.trades}건 · 손익비 ${r.pf} · 건전성 ${r.score}/4</div><table class="nt-read-t">${r.rows.map((x) => `<tr><td><b>${e(x[0])}</b></td><td>${e(x[1])}<div class="${/손실|부족|의심|취약|민감|가까움|낙폭|연속/.test(x[2]) ? "down" : "muted"}">${e(x[2])}</div></td></tr>`).join("")}</table>${r.text ? `<div class="nt-mkt-sec">🤖 AI 해설</div><div>${e(r.text)}</div>` : ""}<div class="nt-row"><button data-do="mine" ${spec ? "" : "disabled"}>내 전략 JSON 분석</button> <button data-do="demo">데모 전략 다음 것</button></div>`);
            pn.querySelector('[data-do="mine"]').onclick = () => run(true); pn.querySelector('[data-do="demo"]').onclick = () => run(false);
          } catch (err) { paint(`<div class="nt-mkt-st">실패: ${e(err.message || err)}</div>`); } };
        paint(`<div>전략을 5항목으로 측정합니다: ① 레짐 적합성 ② 리스크 노출 ③ 과최적화 가능성 ④ 실행 현실성 ⑤ 개선 방향(사후 시험 숫자 포함).</div><div class="muted">${spec ? "패널 [전략] 탭에 있는 JSON 을 이 코인·봉으로 분석할 수 있습니다." : "패널 [전략] 탭에 전략 JSON 이 없어 데모 전략을 차례로 분석합니다."}</div><div class="nt-row"><button data-do="mine" ${spec ? "" : "disabled"}>내 전략 JSON 분석</button> <button data-do="demo">데모 전략 분석</button></div>`);
        pn.querySelector('[data-do="mine"]').onclick = () => run(true); pn.querySelector('[data-do="demo"]').onclick = () => run(false);
      }
    } catch (err) { paint(`<div class="nt-mkt-st">차트 읽기 실패: ${e(err.message || err)}</div>`); }
  }
  async _chartLab() {
    const cfg = this.S.cells[this.S.active] || {}, e = (x) => this.esc(String(x ?? ""));
    if (typeof window.ghCoinChartLab !== "function") { this.toast("🔬 내 지표 연구소는 GH Coin 앱에서 쓸 수 있습니다 (GHCoin.exe)", "err"); return; }
    let sym = String(cfg.symbol || "BTCUSDT").toUpperCase(); const m = sym.match(/^KRW-(\w+)$/); if (m) sym = m[1] + "USDT"; if (!/USDT$/.test(sym)) sym += "USDT";
    let pn = this.root.querySelector(".nt-mylab"); if (!pn) { pn = document.createElement("div"); pn.className = "nt-mkt nt-mylab"; this.root.appendChild(pn); }
    const close = () => { clearInterval(this._labTimer); this._labTimer = 0; pn.remove(); };
    const head = `<div class="nt-mkt-h"><b>🔬 내 지표 연구소 · ${e(sym.replace("USDT", ""))} ${e(cfg.interval || "")}</b><span class="muted">차트에 띄운 보조지표 ${this.S.inds.length}개</span><button data-x>✕</button></div>`;
    const paint = (body) => { pn.innerHTML = head + body; pn.querySelector("[data-x]").onclick = close; };
    const steps = []; paint(`<div class="nt-mkt-st">시작…</div>`);
    const btn = this.root.querySelector('[data-nt="lab"]'); if (btn) btn.disabled = true;
    try {
      const r = await window.ghCoinChartLab({ sym, interval: cfg.interval, specs: this.S.inds.map((x) => ({ id: x.id, key: x.key, params: { ...(x.params || {}) }, color: x.color })), onStep: (t) => { steps.push(t); paint(`<div class="nt-mkt-st">${steps.map((x, i) => `<div>${i === steps.length - 1 ? "⏳" : "✓"} ${e(x)}</div>`).join("")}</div>`); } });
      const T = r.tune, B = r.build, g = B.gene;
      const tuneRows = T.rows.map((x) => `<tr><td>${e(x.name)}</td><td>${x.changed ? `<b class="up">${e(x.changed)}</b>` : `<span class="muted">유지</span>`}</td><td>${x.before.whip}→<b>${x.after.whip}</b>%</td><td>${x.before.hit}→<b>${x.after.hit}</b>%</td></tr><tr><td colspan="4" class="muted" style="font-size:10.5px;padding-bottom:5px">${e(x.reason)}</td></tr>`).join("");
      const sr = (lab, x) => `<tr><td>${lab}</td><td>${x.n}</td><td class="${x.mean > 0 ? "up" : "down"}">${x.mean >= 0 ? "+" : ""}${x.mean}R</td><td>${x.wr}%</td></tr>`;
      const posBox = (p) => !p ? "" : `<div class="nt-mkt-dec ${p.side && B.pass ? "go" : "no"}">${e(p.state)}${p.side && !B.pass ? " — ⚠ 검증 미통과 매매법의 신호(참고만)" : ""}</div>${p.side && p.sl ? `<div class="nt-mkt-px"><div><small>시장가</small><b>${p.price}</b></div><div><small>손절 −${p.slPct}%</small><b class="down">${(+p.sl).toPrecision(6)}</b></div><div><small>익절 +${p.tpPct}%</small><b class="up">${(+p.tp).toPrecision(6)}</b></div><div><small>레버</small><b>≤${p.lev}x</b></div></div>` : ""}<div class="muted">지표 합의 ${p.vote}/${p.m} · ${new Date(p.t).toLocaleTimeString("ko-KR")} 갱신 (30초마다)</div>`;
      const render = (pos) => paint(`<div class="nt-mkt-sec">① 노이즈 튜닝 — 처음 보는 뒤 30% 기준 (가짜 신호 = 3봉 안에 되돌림)</div>
        <table class="nt-mylab-tb"><tr><th>지표</th><th>값</th><th>가짜 신호</th><th>방향 적중</th></tr>${tuneRows}</table>
        ${T.rows.some((x) => x.changed) ? `<div class="nt-row"><button data-apply>튜닝 값을 내 차트에 적용</button></div>` : `<div class="muted">바꿀 만한 값이 없었습니다(원래 값 유지)</div>`}
        <div class="nt-mkt-sec">② 내 지표 합의 매매법</div>
        ${B.ok ? `<div>진입: 지표 ${g.specs.length}개 중 <b>${g.k}개</b>가 막 같은 방향이 되는 순간 · 손절 ${g.atrK}ATR/스윙 · 손익비 ${g.rr} · ${g.exitFlip ? "합의가 깨지면 청산" : "손절·익절까지 보유"}</div>
          <table class="nt-mylab-tb"><tr><th>구간</th><th>거래</th><th>평균</th><th>승률</th></tr>${sr("학습(앞 70%)", B.train)}${sr("처음 보는(뒤 30%)", B.test)}${B.cross.map((x) => sr(e(x.sym.replace("USDT", "")) + " (같은 값)", x)).join("")}</table>
          <div class="nt-mkt-dec ${B.pass ? "go" : "no"}">${e(B.verdict)}</div>
          <div class="nt-row"><button data-demo>${B.pass ? "데모에 투입" : "그래도 데모에 투입(검증 미통과)"}</button></div>
          <div class="muted">데모 투입 후에도 뉴럴 데스크가 6개 코인 자체 백테스트 + 최근 성적(기대값 +0.1R↑)을 통과해야 실제 데모 진입을 합니다.</div>` : `<div class="down">${e(B.reason)}</div>`}
        <div class="nt-mkt-sec">③ 지금 포지션 (이 매매법 기준 · 실시간)</div>${posBox(pos)}
        <div class="muted nt-mkt-foot">모든 숫자는 수수료 포함 백테스트 · 과거 성적은 미래를 보장하지 않습니다 · 주문은 직접</div>`);
      const wire = () => {
        pn.querySelector("[data-apply]")?.addEventListener("click", () => { for (const t of T.tuned) { const s0 = this.S.inds.find((x) => x.id === t.id); if (s0) s0.params = { ...t.params }; } this._indsChanged(); this.toast("튜닝 값을 차트에 적용했습니다"); });
        pn.querySelector("[data-demo]")?.addEventListener("click", async (ev) => { ev.target.disabled = true; try { await window.ghCoinChartDemo(g, { test: B.test, crossPos: B.crossPos, pass: B.pass }); this.toast("뉴럴 데스크 데모에 투입했습니다 — 다음 자체 백테스트(최대 2시간 안)부터 검증"); ev.target.textContent = "✓ 데모 투입됨"; } catch (er) { this.toast("투입 실패: " + (er.message || er), "err"); ev.target.disabled = false; } });
      };
      render(r.pos); wire();
      clearInterval(this._labTimer);
      if (g) this._labTimer = setInterval(async () => { if (!pn.isConnected) return clearInterval(this._labTimer); try { const p = await window.ghCoinChartPos(g, sym); render(p); wire(); } catch (er) { /* 다음에 */ } }, 30e3);
    } catch (err) { paint(`<div class="down" style="padding:8px">실패: ${e(err.message || err)}</div>`); }
    if (btn) btn.disabled = false;
  }
  // ------------------------------------------------------------ 🤖 AI 팀 분석 (GH Coin 직원들 → analysisbus.js)
  _aiData(tc) { return this.bus && tc?.symbol ? this.bus.read(tc.symbol) : {}; }
  _applyAi() {
    if (!this.bus) return;
    for (const cell of this.cells) {
      const tc = cell.tc; if (!tc?.candles?.length) continue;
      const d = this._aiData(tc), lines = [], markers = [], segs = [];
      for (const [k, v] of Object.entries(d)) { if (!this.S.aiShow[k.replace(/4h$/, "")] || !v) continue; lines.push(...(v.lines || [])); markers.push(...(v.markers || [])); segs.push(...(v.segs || [])); }
      tc.setAiOverlay({ lines: lines.slice(0, 24), markers: markers.slice(-80), segs: segs.slice(0, 30) });
    }
  }
  _renderAi() {
    const el = this.root.querySelector(".nt-ai"), tc = this.cur?.tc; if (!el) return;
    const d = this._aiData(tc), e = this.esc, NAMES = { ...(this.bus?.SECTIONS || {}), local: "🔎 이 차트로 계산", pattern4h: "🕯 차트 패턴 (4시간봉)" };
    const ago = (t) => { const m = Math.round((Date.now() - t) / 60000); return m < 1 ? "방금" : m < 60 ? `${m}분 전` : m < 1440 ? `${Math.round(m / 60)}시간 전` : `${Math.round(m / 1440)}일 전`; };
    const keys = Object.keys(d).sort((a, b) => (d[b].t || 0) - (d[a].t || 0));
    el.innerHTML = `<div class="nt-ai-h"><b>🤖 AI 팀 분석</b><span class="muted">${e(tc?.symbol || "")} · 직원들이 낸 분석을 차트에 겹쳐 그립니다</span></div>
      <div class="nt-row"><button class="nt-primary" data-ai="local">이 차트로 지금 계산</button>${typeof window.ghCoinAsk === "function" ? `<button data-ai="deep">본부에 깊게 분석 맡기기</button>` : ""}<button data-ai="off">표시 모두 끄기</button></div>
      ${keys.length ? keys.map((k) => { const v = d[k], key = k.replace(/4h$/, ""); return `<div class="nt-card nt-ai-card"><div class="nt-card-h"><label><input type="checkbox" data-aishow="${e(key)}" ${this.S.aiShow[key] ? "checked" : ""}> ${e(NAMES[k] || k)}</label><span class="muted">${ago(v.t)}</span></div>
        <div class="nt-ai-t">${e(v.title || "")}</div><div class="muted nt-ai-x">${e(v.text || "")}</div>
        ${v.rows?.length ? `<table class="nt-ai-tb">${v.rows.slice(0, 8).map((r) => `<tr>${r.map((x) => `<td>${e(x)}</td>`).join("")}</tr>`).join("")}</table>` : ""}
        ${(v.lines || []).length ? `<div class="muted nt-ai-x">차트 선 ${v.lines.length}개${(v.markers || []).length ? ` · 표시 ${v.markers.length}개` : ""}${(v.segs || []).length ? ` · 패턴 선 ${v.segs.length}개` : ""}</div>` : ""}
        ${v.spec ? `<div class="nt-row"><button data-ai="lab" data-k="${e(k)}">🧪 이 전략 실험하기</button></div>` : ""}</div>`; }).join("")
      : `<div class="nt-empty">아직 이 코인의 AI 분석이 없습니다.<br>GH Coin 본부가 일하면(실시간 타점·패턴·위원회·리스크·거래소 비교) 여기에 쌓이고 차트에 그려집니다. 위의 <b>이 차트로 지금 계산</b>으로 바로 볼 수도 있습니다.</div>`}`;
    el.onchange = (ev) => { const cb = ev.target.closest("[data-aishow]"); if (!cb) return; this.S.aiShow[cb.dataset.aishow] = cb.checked; this._save(); this._applyAi(); };
    el.onclick = (ev) => { const b = ev.target.closest("[data-ai]"); if (!b) return; ev.stopPropagation();
      if (b.dataset.ai === "local") this._aiLocal(b);
      if (b.dataset.ai === "off") { Object.keys(this.S.aiShow).forEach((k) => (this.S.aiShow[k] = false)); this._save(); this._applyAi(); this._renderAi(); }
      if (b.dataset.ai === "deep") { window.ghCoinAsk?.(`${tc.symbol.replace(/USDT$|^KRW-/, "")} 모든 보조지표 종합해서 추세랑 타점 분석해줘`); this.toast("본부 실시간 종합 지표 타점팀에 맡겼습니다 · 끝나면 여기에 그려집니다"); }
      if (b.dataset.ai === "lab") { this._labPreset = d[b.dataset.k]?.spec; this.S.tab = "lab"; this._save(); this._syncSide(); }
    };
  }
  // 본부가 안 돌아도: 이 차트의 캔들로 패턴·기술 요약·종합 지표·겹친 지지/저항을 바로 계산
  async _aiLocal(btn) {
    const tc = this.cur?.tc; if (!tc?.candles.length) return;
    btn.disabled = true; btn.textContent = "계산 중…";
    try {
      const [PT, TR, CB] = await Promise.all([import("../../gh-coin/lib/patterns.js"), import("../../gh-coin/lib/ta_rating.js"), import("../../gh-coin/combo.js")]);
      const cs = D.toQuant(tc.candles).slice(0, -1), last = cs.at(-1);
      const pats = PT.scan(cs), tv = TR.rating(cs), cdl = TR.candles(cs), an = await CB.analyzeTF(cs.slice(-500));
      const cl = CB.clusterLevels(an.levels, last.c, an.atr).filter((x) => x.n >= 2).sort((a, b) => Math.abs(a.price - last.c) - Math.abs(b.price - last.c)).slice(0, 6);
      this.bus.publish(tc.symbol, "local", { team: "local", title: `${D.IV_LABEL[tc.interval]}봉 · 종합 ${Math.round(an.score * 100)} (${CB.verdict(an.score)}) · TV ${tv ? tv.label : "—"}`,
        text: `지표 ${an.total}종 · 상승 ${an.up} · 하락 ${an.dn} · ${an.regime.label} · 패턴 ${pats.map((p) => p.name + " " + (PT.STATE_KO[p.state] || "")).join(", ") || "없음"} · 캔들 ${cdl.map((x) => x.name).join(", ") || "특이 없음"}`,
        lines: [...cl.map((x) => ({ price: x.price, label: `${x.price > last.c ? "저항" : "지지"} ×${x.n}`, color: x.price > last.c ? "#ff9800" : "#2962ff", style: 3 })), ...pats.filter((p) => p.trigger).map((p) => ({ price: p.trigger, label: `${p.name} 기준`, color: "#ffb300", style: 2 }))],
        segs: pats.flatMap((p) => (p.lines || []).map((l) => ({ a: { t: l.from.t, p: l.from.p }, b: { t: l.to.t, p: l.to.p }, color: p.dir > 0 ? "#26a69a" : p.dir < 0 ? "#ef5350" : "#b2b5be", label: `${p.name} ${l.name}` }))),
        markers: [...pats.flatMap((p) => Object.entries(p.points || {}).map(([nm, q]) => ({ t: q.t, text: `${p.name.slice(0, 6)} ${nm}`, dir: 0, color: "#ffb300" }))), ...cdl.filter((x) => x.dir).map((x) => ({ t: last.t, dir: x.dir, text: x.name, color: "#ffd54f" }))],
        rows: [["이평 15", tv ? tv.maLabel : "—"], ["오실레이터 11", tv ? tv.oscLabel : "—"], ["새 신호", an.fresh.map((f) => f.name).slice(0, 4).join(", ") || "—"]] });
      this.S.aiShow.local = true; this._save();
    } catch (e) { this.toast("계산 실패: " + (e.message || e), "err"); }
    btn.disabled = false; btn.textContent = "이 차트로 지금 계산";
  }

  // ------------------------------------------------------------ 🧪 실험: AI 팀 전략으로 백테스트 · 검증 · 견고성 · 하이퍼옵트 · 버전 저장
  async _labSources() {
    const out = [{ id: "strat", name: "✍ 전략 탭의 JSON", get: () => { try { return JSON.parse(this.root.querySelector(".nt-strat").value); } catch (e) { return null; } } }, { id: "example", name: "예시: EMA 교차 + RSI", get: () => EXAMPLE }];
    if (this._labPreset) out.unshift({ id: "preset", name: "🤖 AI 팀이 보낸 전략", get: () => this._labPreset });
    try { const S = JSON.parse(localStorage.getItem("coinSDLC") || "{}"); for (const p of Object.values(S)) { const v = p.versions?.at(-1); if (v?.spec) out.push({ id: "sdlc:" + p.name, name: `📦 ${p.name} v${v.semver || v.v}`, get: () => v.spec }); } } catch (e) { /* 없음 */ }
    try { const d = this._aiData(this.cur?.tc); if (d.opt?.spec) { out.push({ id: "opt-best", name: "🎛 최적화팀 최신 결과(최적)", get: () => d.opt.spec }); out.push({ id: "opt-base", name: "🎛 최적화팀 최신 결과(원본)", get: () => d.opt.baseSpec }); } } catch (e) { /* 없음 */ }
    try { const E = await import("../engine.js"), v = await E.idb.all("coin:log"), log = Array.isArray(v[0]) ? v[0] : [], seen = new Set();
      for (const x of log.filter((x) => x.kind === "bt" && x.spec).reverse()) { if (seen.has(x.name) || seen.size >= 15) continue; seen.add(x.name); out.push({ id: "bt:" + x.id, name: `${x.pass ? "✅" : "❌"} ${x.name} (${x.mname || x.market})`, get: () => x.spec }); } } catch (e) { /* 없음 */ }
    return out;
  }
  async _renderLab() {
    const el = this.root.querySelector(".nt-lab"); if (!el) return;
    const H = await import("../../gh-coin/lib/hyperopt.js").catch(() => null), src = await this._labSources(); this._labSrc = src;
    const e = this.esc, tc = this.cur?.tc;
    el.innerHTML = `<div class="nt-ai-h"><b>🧪 실험실</b><span class="muted">${e(tc?.symbol || "")} · ${D.IV_LABEL[tc?.interval] || ""}봉 ${tc?.candles?.length?.toLocaleString() || 0}개로 (더 길게: 위쪽 '전체 과거')</span></div>
      <label class="nt-lab-l">전략<select class="nt-lab-src">${src.map((x) => `<option value="${e(x.id)}">${e(x.name)}</option>`).join("")}</select></label>
      <div class="nt-row"><button class="nt-primary" data-lab="all">⚡ 전체 분석</button><button data-lab="bt">백테스트</button><button data-lab="wf">검증(70/30)</button><button data-lab="rb">견고성</button><button data-lab="trust">🏆 신뢰점수</button><button data-lab="edit">전략 탭으로</button></div>
      <div class="nt-row"><select class="nt-lab-loss">${H ? Object.entries(H.LOSSES).map(([k, v]) => `<option value="${k}"${k === "SharpeDaily" ? " selected" : ""}>${e(v.ko)}</option>`).join("") : ""}</select><input class="nt-lab-ep" type="number" min="10" max="300" value="40" title="탐색 횟수"><button data-lab="ho">하이퍼옵트</button></div>
      <div class="nt-row"><button data-lab="save">버전으로 저장 (검토 요청)</button></div>
      <div class="nt-lab-out"></div>`;
    el.onclick = (ev) => { const b = ev.target.closest("[data-lab]"); if (!b) return; ev.stopPropagation(); this._labRun(b.dataset.lab, b); };
  }
  _labSpec() {
    const id = this.root.querySelector(".nt-lab-src")?.value, s = (this._labSrc || []).find((x) => x.id === id)?.get();
    const tc = this.cur?.tc; return s && tc ? { ...s, interval: tc.interval, symbol: tc.symbol } : null;
  }
  _equitySvg(eq) {
    if (!eq?.length) return "";
    const v = eq.map((p) => p.v), lo = Math.min(...v), hi = Math.max(...v), W = 300, Hh = 64, step = Math.max(1, Math.floor(v.length / 300));
    const pts = v.filter((_, i) => i % step === 0).map((x, i, a) => `${(i / Math.max(1, a.length - 1) * W).toFixed(1)},${(Hh - (x - lo) / (hi - lo || 1) * (Hh - 4) - 2).toFixed(1)}`).join(" ");
    return `<svg class="nt-eq" viewBox="0 0 ${W} ${Hh}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="${v.at(-1) >= v[0] ? "#26a69a" : "#ef5350"}" stroke-width="1.5"/></svg>`;
  }
  async _labRun(kind, btn) {
    const out = this.root.querySelector(".nt-lab-out"), tc = this.cur?.tc, e = this.esc;
    if (!tc?.candles.length) return;
    let spec = this._labSpec();
    if (!spec) { out.innerHTML = `<div class="down">전략을 읽을 수 없습니다 (전략 탭 JSON 확인)</div>`; return; }
    if (kind === "edit") { this.root.querySelector(".nt-strat").value = JSON.stringify(spec, null, 2); this.S.tab = "strat"; this._save(); this._syncSide(); return; }
    const Q = await import("../quant.js"), c = D.toQuant(tc.candles), bs = D.IV_SEC[tc.interval] || 3600, f = (x, d = 2) => x == null || !Number.isFinite(+x) ? "–" : (+x).toFixed(d), cls = (x) => x > 0 ? "up" : x < 0 ? "down" : "";
    const old = btn.textContent; btn.disabled = true; btn.textContent = "계산 중…";
    try {
      spec = Q.normalizeSpec(spec);
      const show = (bt, label) => { this.strat = { spec: bt.spec, sig: Q.signals(bt.spec, c), bt, tc }; this._stratBar = tc.candles.at(-1)?.time; this.S.stratMode = "trades"; this._applyStrat(); };
      if (kind === "bt") {
        const H = await import("../../gh-coin/lib/hyperopt.js"), bt = Q.backtest(spec, c, { barSeconds: bs }), st = bt.stats, an = H.analyzers(bt.equity, bt.trades, { perYear: 365 * 86400 / bs });
        show(bt);
        out.innerHTML = `<div class="nt-card"><div class="nt-card-h">${e(spec.name || "전략")} <span class="muted">${c.length.toLocaleString()}봉 · 레버리지 ${spec.risk.leverage}배</span></div>${this._equitySvg(bt.equity)}
          <div class="nt-stats"><div><span>수익률</span><b class="${cls(st.total_return_pct)}">${f(st.total_return_pct)}%</b></div><div><span>보유 대비</span><b>${f(st.buy_and_hold_pct)}%</b></div><div><span>최대 낙폭</span><b class="down">${f(st.max_drawdown_pct)}%</b></div><div><span>거래</span><b>${st.trades}</b></div>
          <div><span>승률</span><b>${f(st.win_rate_pct, 1)}%</b></div><div><span>손익비</span><b>${f(st.profit_factor)}</b></div><div><span>SQN</span><b>${f(an.sqn)} <span class="muted">${e(an.sqnGrade)}</span></b></div><div><span>VWR</span><b>${f(an.vwr, 1)}</b></div>
          <div><span>최장 물림</span><b>${an.maxddLen}봉</b></div><div><span>연승/연패</span><b>${an.streakWon}/${an.streakLost}</b></div><div><span>ROI 익절</span><b>${st.roi_exits ?? 0}</b></div><div><span>보호장치 잠금</span><b>${st.protection_locks ?? 0}</b></div></div>
          <div class="nt-dlg-note">차트에 진입·청산 표시 · 다음 봉 시가 체결 · 수수료 ${spec.risk.fee_pct}% · 분석용 시뮬레이션</div></div>`;
      } else if (kind === "wf") {
        const wf = Q.walkForward(spec, c, { barSeconds: bs }), row = (n, x) => `<tr><td>${n}</td><td class="${cls(x.net_pnl)}">${f(x.net_pnl)}</td><td>${x.trades}</td><td>${f(x.profit_factor)}</td><td>${f(x.win_rate, 1)}%</td><td>${f(x.max_dd_pct, 1)}%</td></tr>`;
        out.innerHTML = `<div class="nt-card"><div class="nt-card-h">검증 (앞 70% 학습 · 뒤 30% 처음 보는 구간) — ${wf.pass ? `<b class="up">통과</b>` : `<b class="down">불통과</b>`}</div>
          <table class="nt-ai-tb"><tr><td>구간</td><td>순손익</td><td>거래</td><td>손익비</td><td>승률</td><td>낙폭</td></tr>${row("학습", wf.is)}${row("검증", wf.oos)}</table>
          <ul class="nt-lab-ul">${wf.reasons.map((r) => `<li>${e(r)}</li>`).join("")}</ul><div class="muted">3구간 관문(60/20/20): ${e({ pass: "통과", train_fail: "학습 구간 미달", valid_fail: "검증 구간 미달", hold_fail: "최종 구간 미달" }[wf.gate3.stage] || wf.gate3.stage)}</div></div>`;
      } else if (kind === "rb") {
        const RB = await import("../../gh-coin/lib/robust.js"), bt = Q.backtest(spec, c, { barSeconds: bs }), pnl = bt.trades.map((t) => t.pnl);
        const pt = RB.permutationTest(pnl), b = RB.bootstrapSharpe(pnl), mw = RB.multiWindow(Q, spec, c, 5), hy = RB.hygiene(bt);
        out.innerHTML = `<div class="nt-card"><div class="nt-card-h">견고성 — 이 성과가 운인가?</div><table class="nt-ai-tb">
          <tr><td>운일 확률 p (1000번 뒤섞기)</td><td class="${pt.p != null && pt.p <= 0.05 ? "up" : "down"}">${f(pt.p, 3)}</td><td class="muted">${pt.p == null ? "거래 부족" : pt.p <= 0.05 ? "운으로 보기 어려움" : "운일 수 있음"}</td></tr>
          <tr><td>부트스트랩 샤프 90%</td><td>${b ? `${f(b.lo)} ~ ${f(b.hi)}` : "–"}</td><td class="muted">0 아래가 넓으면 불안정</td></tr>
          ${mw.windows.map((w) => `<tr><td>구간 ${w.j}</td><td class="${cls(w.ret)}">${w.err ? e(w.err) : f(w.ret) + "%"}</td><td class="muted">거래 ${w.n ?? "–"} · 손익비 ${f(w.pf)}</td></tr>`).join("")}
          <tr><td>위생</td><td colspan="2">${hy.ok ? (hy.warns.map(e).join(", ") || "이상 없음") : `<span class="down">${hy.fails.map(e).join(", ")}</span>`}</td></tr></table></div>`;
      } else if (kind === "all") {
        // 전체 분석: 백테스트 + 검증(70/30) + 견고성 + 신뢰점수를 백테스트 1회 재사용으로 한 번에
        const RB = await import("../../gh-coin/lib/robust.js"), H = await import("../../gh-coin/lib/hyperopt.js");
        const bt = Q.backtest(spec, c, { barSeconds: bs }), wf = Q.walkForward(spec, c, { barSeconds: bs }), st = bt.stats;
        const an = H.analyzers(bt.equity, bt.trades, { perYear: 365 * 86400 / bs }), pnl = bt.trades.map((t) => t.pnl);
        const pt = RB.permutationTest(pnl), bst = RB.bootstrapSharpe(pnl), mw = RB.multiWindow(Q, spec, c, 5), hy = RB.hygiene(bt);
        const nTr = st.trades || 0, pOK = pt.p == null || pt.p <= 0.1, mwOK = mw.total < 3 || mw.positive >= Math.ceil(mw.total * 0.6), hyOK = hy.ok !== false, nOK = nTr >= 8;
        const robust = { ok: pOK && mwOK && hyOK && nOK, p: pt.p ?? null, mwPos: mw.positive ?? null, mwTotal: mw.total ?? null, sqn: Number.isFinite(an.sqn) ? +an.sqn.toFixed(2) : null };
        const clc = (lo, hi, v) => Math.max(lo, Math.min(hi, v));
        const retN = clc(0, 1, ((st.total_return_pct || 0) + 10) / 30), wrN = clc(0, 1, ((st.win_rate_pct || 0) - 40) / 30), pf = st.profit_factor, pfN = pf == null ? 0.4 : clc(0, 1, (pf - 0.8) / 1.7);
        const A = 35 * (0.5 * retN + 0.25 * wrN + 0.25 * pfN);
        const pN = robust.p == null ? 0.5 : clc(0, 1, (0.2 - robust.p) / 0.2), mwN = robust.mwTotal ? clc(0, 1, robust.mwPos / robust.mwTotal) : 0.5, sqnN = robust.sqn == null ? 0.4 : clc(0, 1, robust.sqn / 3);
        const Bb = 30 * (robust.ok ? 1 : 0.5) * (0.4 * pN + 0.35 * mwN + 0.25 * sqnN), Cc = 8, Dd = 15 * clc(0, 1, nTr / 25);
        const trust = Math.round(A + Bb + Cc + Dd), grade = trust >= 75 ? "A 매우 신뢰" : trust >= 60 ? "B 신뢰" : trust >= 45 ? "C 보통" : trust >= 30 ? "D 주의" : "E 위험", gcol = trust >= 60 ? "up" : trust >= 45 ? "" : "down";
        show(bt);
        const verdict = !wf.pass ? "❌ 검증(70/30) 불통과 — 처음 보는 구간에서 무너짐" : !robust.ok ? "⚠️ 검증은 통과했지만 과최적화 의심(운·불안정)" : trust >= 60 ? "✅ 견고하고 신뢰할 만함" : "△ 통과했지만 신뢰점수가 낮음 — 신중히";
        out.innerHTML = `<div class="nt-card"><div class="nt-card-h">⚡ 전체 분석 — ${e(spec.name || "전략")} <span class="muted">${c.length.toLocaleString()}봉 · 레버리지 ${spec.risk.leverage}배</span></div>
          <div style="display:flex;align-items:baseline;gap:10px;margin:4px 0 8px"><span class="muted">신뢰점수</span><b class="${gcol}" style="font-size:32px;line-height:1">${trust}</b><span class="${gcol}">${e(grade)}</span><span class="muted">/ 100</span></div>
          ${this._equitySvg(bt.equity)}
          <div class="nt-stats"><div><span>수익률</span><b class="${cls(st.total_return_pct)}">${f(st.total_return_pct)}%</b></div><div><span>보유 대비</span><b>${f(st.buy_and_hold_pct)}%</b></div><div><span>최대 낙폭</span><b class="down">${f(st.max_drawdown_pct)}%</b></div><div><span>거래</span><b>${nTr}</b></div>
          <div><span>승률</span><b>${f(st.win_rate_pct, 1)}%</b></div><div><span>손익비</span><b>${f(pf)}</b></div><div><span>SQN</span><b>${f(an.sqn)} <span class="muted">${e(an.sqnGrade)}</span></b></div><div><span>VWR</span><b>${f(an.vwr, 1)}</b></div></div>
          <table class="nt-ai-tb" style="margin-top:8px">
            <tr><td>검증 70/30</td><td class="${wf.pass ? "up" : "down"}">${wf.pass ? "통과" : "불통과"}</td><td class="muted">검증구간 순손익 ${f(wf.oos?.net_pnl)} · 손익비 ${f(wf.oos?.profit_factor)}</td></tr>
            <tr><td>운일 확률 p</td><td class="${pt.p != null && pt.p <= 0.05 ? "up" : "down"}">${f(pt.p, 3)}</td><td class="muted">${pt.p == null ? "거래 부족" : pt.p <= 0.05 ? "운으로 보기 어려움" : "운일 수 있음"}</td></tr>
            <tr><td>부트스트랩 샤프 90%</td><td>${bst ? `${f(bst.lo)} ~ ${f(bst.hi)}` : "–"}</td><td class="muted">0 아래가 넓으면 불안정</td></tr>
            <tr><td>구간 일관성</td><td class="${mwOK ? "up" : "down"}">${mw.positive}/${mw.total}</td><td class="muted">기간별로 고르게 버는지</td></tr>
            <tr><td>위생</td><td colspan="2">${hy.ok ? (hy.warns.map(e).join(", ") || "이상 없음") : `<span class="down">${hy.fails.map(e).join(", ")}</span>`}</td></tr></table>
          <div class="nt-dlg-note"><b class="${gcol}">${e(verdict)}</b> · 시장 일반화(같은 자산군 다른 시장)는 본부가 자동 검증 · 계산값일 뿐 미래 보장 아님</div></div>`;
      } else if (kind === "trust") {
        // 신뢰점수: 백테스트 성과 + 견고성(순열검정·구간일관성·SQN) + 표본을 0~100 하나로 (GH Coin/Nano 와 동일 기준)
        const RB = await import("../../gh-coin/lib/robust.js"), H = await import("../../gh-coin/lib/hyperopt.js");
        const bt = Q.backtest(spec, c, { barSeconds: bs }), st = bt.stats;
        const an = H.analyzers(bt.equity, bt.trades, { perYear: 365 * 86400 / bs }), pt = RB.permutationTest(bt.trades.map((t) => t.pnl)), mw = RB.multiWindow(Q, spec, c, 5), hy = RB.hygiene(bt);
        const nTr = st.trades || 0, pOK = pt.p == null || pt.p <= 0.1, mwOK = mw.total < 3 || mw.positive >= Math.ceil(mw.total * 0.6), hyOK = hy.ok !== false, nOK = nTr >= 8;
        const robust = { ok: pOK && mwOK && hyOK && nOK, p: pt.p ?? null, mwPos: mw.positive ?? null, mwTotal: mw.total ?? null, sqn: Number.isFinite(an.sqn) ? +an.sqn.toFixed(2) : null };
        const clc = (lo, hi, v) => Math.max(lo, Math.min(hi, v));
        const retN = clc(0, 1, ((st.total_return_pct || 0) + 10) / 30), wrN = clc(0, 1, ((st.win_rate_pct || 0) - 40) / 30), pf = st.profit_factor, pfN = pf == null ? 0.4 : clc(0, 1, (pf - 0.8) / 1.7);
        const A = 35 * (0.5 * retN + 0.25 * wrN + 0.25 * pfN);
        const pN = robust.p == null ? 0.5 : clc(0, 1, (0.2 - robust.p) / 0.2), mwN = robust.mwTotal ? clc(0, 1, robust.mwPos / robust.mwTotal) : 0.5, sqnN = robust.sqn == null ? 0.4 : clc(0, 1, robust.sqn / 3);
        const B = 30 * (robust.ok ? 1 : 0.5) * (0.4 * pN + 0.35 * mwN + 0.25 * sqnN), C = 8, D = 15 * clc(0, 1, nTr / 25);
        const trust = Math.round(A + B + C + D), grade = trust >= 75 ? "A 매우 신뢰" : trust >= 60 ? "B 신뢰" : trust >= 45 ? "C 보통" : trust >= 30 ? "D 주의" : "E 위험", gcol = trust >= 60 ? "up" : trust >= 45 ? "" : "down";
        show(bt);
        const bar = (v, max, label, sub) => `<div style="margin:5px 0"><div style="display:flex;align-items:center;gap:8px"><span class="muted" style="width:84px;font-size:12px">${e(label)}</span><span style="flex:1;height:8px;background:#2a2e39;border-radius:4px;overflow:hidden"><i style="display:block;height:100%;width:${Math.round(clc(0, 1, v / max) * 100)}%;background:#2962ff"></i></span><b style="width:44px;text-align:right;font-size:12px">${Math.round(v)}/${max}</b></div><div class="muted" style="font-size:11px;margin-left:92px">${e(sub)}</div></div>`;
        out.innerHTML = `<div class="nt-card"><div class="nt-card-h">🏆 신뢰 점수 <span class="muted">성과+견고성+일반화+표본 종합</span></div>
          <div style="display:flex;align-items:baseline;gap:10px;margin:6px 0 10px"><b class="${gcol}" style="font-size:34px;line-height:1">${trust}</b><span class="${gcol}">${e(grade)}</span><span class="muted">/ 100</span></div>
          ${bar(A, 35, "데모 성과", `수익 ${f(st.total_return_pct, 1)}% · 승률 ${f(st.win_rate_pct, 0)}% · 손익비 ${f(pf)}`)}
          ${bar(B, 30, "견고성", `운일확률 p${f(robust.p, 2)} · 구간 ${robust.mwPos ?? "–"}/${robust.mwTotal ?? "–"} · SQN ${f(robust.sqn)}`)}
          ${bar(C, 20, "시장 일반화", "차트 실험에선 미포함 — 본부가 같은 자산군 다른 시장으로 자동 검증")}
          ${bar(D, 15, "표본 신뢰도", `거래 ${nTr}회`)}
          <div class="nt-dlg-note">수익만 높고 과최적화(운일확률↑·구간 들쭉날쭉·표본 적음)면 점수가 깎입니다 · 계산값일 뿐 미래 보장 아님</div></div>`;
      } else if (kind === "ho") {
        const H = await import("../../gh-coin/lib/hyperopt.js"), loss = this.root.querySelector(".nt-lab-loss").value, ep = Math.max(10, Math.min(300, +this.root.querySelector(".nt-lab-ep").value || 40));
        H.setSeed(Date.now() % 100000);
        const res = await H.hyperopt(Q, spec, c, { epochs: ep, loss, space: ["buy", "roi", "stoploss", "trailing", "protection"], tfMin: bs / 60, onProgress: (k, n) => { btn.textContent = `${k}/${n}…`; } });
        this._labBest = res.best.spec;
        out.innerHTML = `<div class="nt-card"><div class="nt-card-h">하이퍼옵트 (${e(res.lossKo)} · ${res.epochs}회 · 앞 70%에서만 탐색)</div><table class="nt-ai-tb">
          <tr><td></td><td>지금</td><td>최적</td></tr><tr><td>손실값(작을수록 좋음)</td><td>${f(res.base.loss, 3)}</td><td>${f(res.best.loss, 3)}</td></tr>
          <tr><td>검증 구간 순손익</td><td class="${cls(res.base.wf.oos.net_pnl)}">${f(res.base.wf.oos.net_pnl)}</td><td class="${cls(res.best.wf.oos.net_pnl)}">${f(res.best.wf.oos.net_pnl)}</td></tr>
          <tr><td>관문</td><td>${res.base.wf.pass ? "통과" : "불통과"}</td><td>${res.best.wf.pass ? "통과" : "불통과"}</td></tr></table>
          <div class="nt-dlg-note">${res.improved ? `<b class="up">처음 보는 구간에서도 좋아졌습니다</b>` : res.overfit ? `<b class="down">학습 구간만 좋아짐 = 과최적화</b>` : "뚜렷한 개선 없음"} · 바뀐 위험 설정: ${e(JSON.stringify(res.best.risk).slice(0, 220))}</div>
          <div class="nt-row"><button data-lab="apply">최적 결과를 차트에 백테스트</button></div></div>`;
      } else if (kind === "apply") {
        if (!this._labBest) return;
        this._labPreset = this._labBest; await this._renderLab(); this.root.querySelector(".nt-lab-src").value = "preset"; return this._labRun("bt", this.root.querySelector('[data-lab="bt"]'));
      } else if (kind === "save") {
        const S = await import("../../gh-coin/lib/sdlc.js"), wf = Q.walkForward(spec, c, { barSeconds: bs }), rv = S.propose(spec, { author: "차트 터미널", why: "실험실에서 저장" });
        if (rv.status === "review") S.decide(spec.name || "전략", rv.id, wf.pass, { who: "코드 관문", why: wf.pass ? "70/30 검증 통과" : "검증 불통과 — 반려" });
        const v = S.latest(spec.name || "전략");
        out.innerHTML = `<div class="nt-card">${rv.status === "rejected" ? `<b class="down">제약 위반으로 반려:</b> ${e(rv.fails.map((x) => x.text).join(", "))}` : wf.pass ? `<b class="up">버전 ${e(v?.semver || "")} 로 저장</b> — GH Coin 본부의 전략 버전 관리·실험실 목록에 보입니다` : `<b class="down">검증 불통과라 버전으로 올리지 않았습니다</b> (검토 기록은 남음)`}<div class="muted">바뀐 곳 ${rv.diff.length}군데</div></div>`;
      }
    } catch (err) { out.innerHTML = `<div class="down">${e(err.message || err)}</div>${err.problems ? `<ul>${err.problems.map((p) => `<li>${e(p)}</li>`).join("")}</ul>` : ""}`; }
    btn.disabled = false; btn.textContent = old;
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
