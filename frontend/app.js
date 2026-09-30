/* 코인 선물 터미널 프론트엔드 (빌드 도구 없는 바닐라 JS) */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = {
  status: null,
  symbol: "BTCUSDT",
  interval: "1h",
  studies: new Set(["RSI@tv-basicstudies", "MAExp@tv-basicstudies"]),
  spec: null,
  lastBacktest: null,
  loadedMarketWidgets: false,
};

// ------------------------------------------------------------------ 공통
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
  return data;
}

let toastTimer;
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (err ? " err" : "");
  t.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.style.display = "none"), err ? 8000 : 4000);
}

async function busy(btn, fn) {
  const prev = btn.textContent;
  btn.disabled = true;
  btn.textContent = "처리 중…";
  try { return await fn(); }
  catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = prev; }
}

const fmt = (v, d = 2) => (v == null || Number.isNaN(v) ? "–" : Number(v).toLocaleString("ko-KR", { maximumFractionDigits: d, minimumFractionDigits: 0 }));
const fmtUsd = (v) => {
  if (v == null) return "–";
  const a = Math.abs(v);
  if (a >= 1e12) return (v / 1e12).toFixed(2) + "T";
  if (a >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (a >= 1e6) return (v / 1e6).toFixed(2) + "M";
  return fmt(v);
};
const signCls = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "");
const time = (t) => (t ? new Date(t * 1000).toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "–");
const stat = (k, v, cls = "") => `<div class="stat"><div class="k">${esc(k)}</div><div class="v ${cls}">${v}</div></div>`;

// ------------------------------------------------------------------ 차트 (lightweight-charts)
function makeChart(el, extra = {}) {
  el.innerHTML = "";
  return LightweightCharts.createChart(el, {
    autoSize: true,
    layout: { background: { color: css("--surface-1") }, textColor: css("--text-secondary"), fontSize: 11 },
    grid: { vertLines: { color: css("--grid") }, horzLines: { color: css("--grid") } },
    rightPriceScale: { borderColor: css("--border") },
    timeScale: { borderColor: css("--border"), timeVisible: true },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    ...extra,
  });
}

const charts = {};
function resetChart(key, el, extra) {
  if (charts[key]) charts[key].remove();
  charts[key] = makeChart(el, extra);
  return charts[key];
}

// ------------------------------------------------------------------ TradingView 위젯
const TV_INTERVAL = { "1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D" };

function renderTvChart(studies = [...state.studies]) {
  const el = $("#tv-chart");
  if (typeof TradingView === "undefined") {
    el.innerHTML = `<p class="hint">TradingView 스크립트를 불러오지 못했습니다 (네트워크 차단 여부 확인).</p>`;
    return;
  }
  el.innerHTML = "";
  new TradingView.widget({
    container_id: "tv-chart",
    autosize: true,
    symbol: `BINANCE:${state.symbol}.P`,
    interval: TV_INTERVAL[state.interval] || "60",
    timezone: "Asia/Seoul",
    theme: "dark",
    style: "1",
    locale: "kr",
    allow_symbol_change: true,
    hide_side_toolbar: false,
    withdateranges: true,
    studies,
  });
}

function renderStudyChips() {
  const reg = state.status?.indicators || {};
  const list = Object.entries(reg).filter(([, v]) => v.tv).map(([k, v]) => ({ id: v.tv, label: v.desc || k }));
  list.push({ id: "Volume@tv-basicstudies", label: "거래량" });
  $("#study-chips").innerHTML = list
    .map((s) => `<button class="chip ${state.studies.has(s.id) ? "on" : ""}" data-study="${s.id}">${esc(s.label)}</button>`)
    .join("");
}

function embedTvWidget(elId, script, config) {
  const el = document.getElementById(elId);
  el.innerHTML = `<div class="tradingview-widget-container" style="height:100%"><div class="tradingview-widget-container__widget" style="height:100%"></div></div>`;
  const s = document.createElement("script");
  s.src = `https://s3.tradingview.com/external-embedding/${script}`;
  s.async = true;
  s.text = JSON.stringify(config);
  el.firstChild.appendChild(s);
}

// ------------------------------------------------------------------ 트레이딩 탭
async function loadDerivatives() {
  try {
    const d = await api(`/api/derivatives?symbol=${state.symbol}&interval=${state.interval}&limit=200`);
    $("#deriv-src").textContent = d.source ? `출처: ${d.source}` : "데이터 없음";
    const oi = resetChart("oi", $("#oi-chart"));
    oi.addAreaSeries({ lineColor: css("--series-1"), topColor: "rgba(57,135,229,.25)", bottomColor: "rgba(57,135,229,0)", lineWidth: 2 })
      .setData(d.open_interest);
    const fr = resetChart("funding", $("#funding-chart"));
    fr.addHistogramSeries({ color: css("--series-2"), priceFormat: { type: "price", precision: 4, minMove: 0.0001 } })
      .setData(d.funding);
    const ls = resetChart("ls", $("#ls-chart"));
    const lsSeries = ls.addLineSeries({ color: css("--series-3"), lineWidth: 2 });
    lsSeries.setData(d.long_short);
    if (d.long_short.length) lsSeries.createPriceLine({ price: 1, color: css("--text-muted"), lineStyle: 2, lineWidth: 1, title: "1.0" });
    for (const [k, el] of [["open_interest", "#oi-chart"], ["funding", "#funding-chart"], ["long_short", "#ls-chart"]]) {
      if (!d[k].length) $(el).innerHTML = `<p class="hint">${esc(d.errors?.[k] || "데이터 없음")}</p>`;
    }
    const p = d.premium;
    const c = await api(`/api/candles?symbol=${state.symbol}&interval=1d&limit=2`);
    const [prev, cur] = c.candles.slice(-2);
    const chg = prev ? (cur.close / prev.close - 1) * 100 : null;
    $("#ticker-stats").innerHTML =
      stat("현재가", fmt(cur.close, 4)) +
      stat("일간 변동", `${chg == null ? "–" : (chg > 0 ? "+" : "") + chg.toFixed(2) + "%"}`, signCls(chg)) +
      stat("마크 가격", fmt(p?.mark_price, 4)) +
      stat("펀딩비 (현재)", p ? p.funding_rate_pct.toFixed(4) + "%" : "–", signCls(p?.funding_rate_pct)) +
      stat("다음 펀딩", p ? time(p.next_funding_time) : "–") +
      stat("데이터", esc(c.source));
  } catch (e) {
    toast("파생 데이터: " + e.message, true);
  }
}

async function loadAccount() {
  const a = await api("/api/paper/account");
  $("#acct-stats").innerHTML =
    stat("평가 자산", fmt(a.equity)) + stat("가용 증거금", fmt(a.free_margin)) +
    stat("지갑 잔고", fmt(a.cash)) + stat("포지션", a.positions.length);
  $("#positions").innerHTML = a.positions.length
    ? a.positions.map((p) => `<div style="padding:6px 0;border-bottom:1px solid var(--grid)">
        <div class="row"><b>${p.symbol}</b><span class="${p.side === "long" ? "pos" : "neg"}">${p.side} ${p.leverage}x</span>
          <span class="${signCls(p.roe_pct)}">ROE ${fmt(p.roe_pct)}% (${fmt(p.unrealized_pnl)})</span><span class="spacer"></span>
          <button class="x" data-close="${p.symbol}" title="시장가 청산">청산</button></div>
        <div class="small muted">진입 ${fmt(p.entry_price, 4)} · 현재 ${fmt(p.mark_price, 4)} · 강제청산 ${fmt(p.liq_price, 4)}${p.stop ? " · 손절 " + fmt(p.stop, 4) : ""}${p.take ? " · 익절 " + fmt(p.take, 4) : ""}</div></div>`).join("")
    : `<p class="hint">열린 포지션 없음</p>`;
  $("#acct-trades").innerHTML = tradeRows(a.trades.slice().reverse().slice(0, 30));
}

function tradeRows(trades) {
  if (!trades.length) return `<tr><td class="muted">거래 없음</td></tr>`;
  return `<tr><th>청산 시각</th><th>방향</th><th>진입</th><th>청산</th><th>사유</th><th>손익</th><th>증거금 대비</th></tr>` +
    trades.map((t) => `<tr><td>${time(t.exit_time)}</td><td class="${t.side === "long" ? "pos" : "neg"}">${t.side} ${fmt(t.leverage, 1)}x</td>
      <td>${fmt(t.entry_price, 4)}</td><td>${fmt(t.exit_price, 4)}</td><td>${esc(t.exit_reason)}</td>
      <td class="${signCls(t.pnl)}">${fmt(t.pnl)}</td><td class="${signCls(t.pnl_pct_on_margin)}">${fmt(t.pnl_pct_on_margin)}%</td></tr>`).join("");
}

async function placeOrder(side) {
  const num = (id) => { const v = $(id).value; return v === "" ? null : Number(v); };
  await api("/api/paper/order", {
    method: "POST",
    body: { symbol: state.symbol, side, margin: num("#o-margin"), leverage: num("#o-lev"), stop_loss_pct: num("#o-sl"), take_profit_pct: num("#o-tp") },
  });
  toast(`${state.symbol} ${side === "long" ? "롱" : "숏"} 페이퍼 주문 체결`);
  loadAccount();
}

// ------------------------------------------------------------------ 전략 빌더
const PRICE_REFS = ["close", "open", "high", "low", "volume", "hl2", "hlc3"];
const DERIV_REFS = ["funding", "oi", "oi_change_pct", "long_short"];
const OPS = [">", "<", ">=", "<=", "crosses_above", "crosses_below", "rising", "falling"];
const OP_LABEL = { crosses_above: "상향 돌파", crosses_below: "하향 돌파", rising: "N봉 상승", falling: "N봉 하락" };
const GROUPS = [["long_entry", "롱 진입"], ["short_entry", "숏 진입"], ["long_exit", "롱 청산 (선택)"], ["short_exit", "숏 청산 (선택)"]];
const RISK_FIELDS = [
  ["leverage", "레버리지"], ["position_pct", "증거금 비중 %"], ["stop_loss_pct", "손절 %"], ["take_profit_pct", "익절 %"],
  ["atr_stop_mult", "ATR 손절 x"], ["atr_tp_mult", "ATR 익절 x"], ["trailing_stop_pct", "추적손절 %"],
  ["fee_pct", "수수료 %"], ["slippage_pct", "슬리피지 %"], ["funding_rate_8h_pct", "펀딩 8h %"],
];
const PARAM_KEYS = ["length", "fast", "slow", "signal", "mult", "k_smooth", "d_smooth"];

function defaultSpec() {
  return {
    name: "새 전략", description: "", symbol: state.symbol, interval: state.interval,
    indicators: [{ id: "ema_fast", type: "ema", length: 20 }, { id: "ema_slow", type: "ema", length: 50 }, { id: "rsi", type: "rsi", length: 14 }],
    long_entry: { logic: "all", conditions: [{ left: "ema_fast", op: "crosses_above", right: "ema_slow" }, { left: "rsi", op: "<", right: "70" }] },
    short_entry: { logic: "all", conditions: [{ left: "ema_fast", op: "crosses_below", right: "ema_slow" }, { left: "rsi", op: ">", right: "30" }] },
    long_exit: null, short_exit: null,
    risk: { leverage: 5, position_pct: 20, stop_loss_pct: 2, take_profit_pct: 4, atr_stop_mult: null, atr_tp_mult: null,
      trailing_stop_pct: null, fee_pct: 0.04, slippage_pct: 0.01, funding_rate_8h_pct: 0.01, allow_reverse: true },
  };
}

function refOptions() {
  const reg = state.status?.indicators || {};
  const refs = [...PRICE_REFS];
  for (const i of state.spec.indicators) {
    refs.push(i.id);
    const outs = reg[i.type]?.outputs || [];
    if (outs.length > 1) outs.forEach((o) => refs.push(`${i.id}.${o}`));
  }
  return [...refs, ...DERIV_REFS];
}

function renderBuilder() {
  const s = state.spec;
  const reg = state.status?.indicators || {};
  const typeOpts = (sel) => Object.keys(reg).map((k) => `<option value="${k}" ${k === sel ? "selected" : ""}>${k}</option>`).join("");
  const refs = refOptions();
  let html = `<datalist id="refs">${refs.map((r) => `<option value="${r}">`).join("")}</datalist>
    <div class="row"><label>이름<input data-f="name" value="${esc(s.name)}"></label>
    <label>심볼<input data-f="symbol" value="${esc(s.symbol)}"></label>
    <label>봉<select data-f="interval">${["5m", "15m", "30m", "1h", "4h", "1d"].map((v) => `<option ${v === s.interval ? "selected" : ""}>${v}</option>`).join("")}</select></label></div>`;
  if (s.description) html += `<p class="hint">${esc(s.description)}</p>`;

  html += `<div class="builder-section"><h3>보조지표 <button class="ghost small" data-act="add-ind">+ 추가</button></h3>`;
  s.indicators.forEach((ind, i) => {
    const keys = Object.keys(reg[ind.type]?.defaults || {}).filter((k) => PARAM_KEYS.includes(k));
    html += `<div class="ind"><input data-ind="${i}" data-k="id" value="${esc(ind.id)}" title="조건식에서 쓰는 이름">
      <select data-ind="${i}" data-k="type">${typeOpts(ind.type)}</select>
      <div class="params">${keys.map((k) => `<input data-ind="${i}" data-k="${k}" type="number" step="any" placeholder="${k} ${reg[ind.type].defaults[k]}" value="${ind[k] ?? ""}" title="${k}">`).join("") || '<span class="muted small">파라미터 없음</span>'}</div>
      <button class="x" data-act="del-ind" data-i="${i}">✕</button></div>`;
  });
  html += `</div>`;

  for (const [g, label] of GROUPS) {
    const grp = s[g];
    html += `<div class="builder-section"><h3>${label}
      <select data-grp="${g}" data-k="logic" ${grp ? "" : "disabled"}><option value="all" ${grp?.logic !== "any" ? "selected" : ""}>모두 충족 (AND)</option><option value="any" ${grp?.logic === "any" ? "selected" : ""}>하나라도 (OR)</option></select>
      <button class="ghost small" data-act="add-cond" data-g="${g}">+ 조건</button></h3>`;
    (grp?.conditions || []).forEach((c, i) => {
      html += `<div class="cond"><input list="refs" data-g="${g}" data-ci="${i}" data-k="left" value="${esc(c.left)}">
        <select data-g="${g}" data-ci="${i}" data-k="op">${OPS.map((o) => `<option value="${o}" ${o === c.op ? "selected" : ""}>${OP_LABEL[o] || o}</option>`).join("")}</select>
        <input list="refs" data-g="${g}" data-ci="${i}" data-k="right" value="${esc(c.right)}">
        <button class="x" data-act="del-cond" data-g="${g}" data-i="${i}">✕</button></div>`;
    });
    html += `</div>`;
  }

  html += `<div class="builder-section"><h3>리스크 · 비용</h3><div class="risk-grid">${RISK_FIELDS.map(([k, l]) =>
    `<label>${l}<input data-risk="${k}" type="number" step="any" value="${s.risk[k] ?? ""}" placeholder="없음"></label>`).join("")}
    <label>반대 신호 스위칭<select data-risk="allow_reverse"><option value="true" ${s.risk.allow_reverse ? "selected" : ""}>예</option><option value="false" ${s.risk.allow_reverse ? "" : "selected"}>아니오</option></select></label></div>
    <p class="hint">피연산자: 가격(close…), 지표 id, <code>id.출력</code>(macd.hist, bb.lower), 파생(funding, oi_change_pct, long_short), 과거값 <code>close[1]</code>, 배수 <code>vol_ma*2</code>, 숫자.</p></div>`;
  $("#builder").innerHTML = html;
  $("#spec-json").value = JSON.stringify(s, null, 2);
}

function onBuilderInput(e) {
  const t = e.target, s = state.spec;
  const numOrNull = (v) => (v === "" ? null : Number(v));
  if (t.dataset.f) s[t.dataset.f] = t.value;
  else if (t.dataset.ind != null) {
    const ind = s.indicators[+t.dataset.ind];
    if (t.dataset.k === "type") {
      state.spec.indicators[+t.dataset.ind] = { id: ind.id, type: t.value };
      return renderBuilder();
    }
    ind[t.dataset.k] = t.dataset.k === "id" ? t.value : numOrNull(t.value);
    if (t.dataset.k === "id" && e.type === "change") return renderBuilder();
  } else if (t.dataset.grp) s[t.dataset.grp].logic = t.value;
  else if (t.dataset.g) s[t.dataset.g].conditions[+t.dataset.ci][t.dataset.k] = t.value;
  else if (t.dataset.risk) s.risk[t.dataset.risk] = t.dataset.risk === "allow_reverse" ? t.value === "true" : numOrNull(t.value);
  $("#spec-json").value = JSON.stringify(s, null, 2);
}

function onBuilderClick(e) {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  const s = state.spec;
  const act = b.dataset.act;
  if (act === "add-ind") {
    let n = s.indicators.length + 1;
    while (s.indicators.some((i) => i.id === `ind${n}`)) n++;
    s.indicators.push({ id: `ind${n}`, type: "sma", length: 20 });
  } else if (act === "del-ind") s.indicators.splice(+b.dataset.i, 1);
  else if (act === "add-cond") {
    s[b.dataset.g] = s[b.dataset.g] || { logic: "all", conditions: [] };
    s[b.dataset.g].conditions.push({ left: "close", op: ">", right: s.indicators[0]?.id || "0" });
  } else if (act === "del-cond") {
    const g = s[b.dataset.g];
    g.conditions.splice(+b.dataset.i, 1);
    if (!g.conditions.length) s[b.dataset.g] = null;
  }
  renderBuilder();
}

function setSpec(spec, engineNote) {
  state.spec = spec;
  renderBuilder();
  if (engineNote) $("#nl-engine").innerHTML = engineNote;
}

function specToTv() {
  const reg = state.status?.indicators || {};
  const studies = state.spec.indicators.filter((i) => reg[i.type]?.tv).map((i) => {
    const inputs = {};
    if (i.length) inputs.length = i.length;
    return Object.keys(inputs).length ? { id: reg[i.type].tv, inputs } : reg[i.type].tv;
  });
  state.studies = new Set(studies.map((s) => (typeof s === "string" ? s : s.id)));
  renderStudyChips();
  switchTab("trade");
  renderTvChart(studies);
  toast("전략의 지표를 TradingView 차트에 표시했습니다 (TV에 없는 지표는 제외).");
}

// ------------------------------------------------------------------ 백테스트 결과
function renderBacktest(r) {
  state.lastBacktest = r;
  const m = r.metrics;
  if (r.warnings?.length) toast("⚠ " + r.warnings.join(" / "), true);
  $("#bt-src").textContent = `캔들: ${r.data_source}${r.data_source === "synthetic" ? " (합성 데이터 — 실데이터 아님)" : ""}${r.derivatives_source ? " · 파생: " + r.derivatives_source : ""}`;
  $("#bt-stats").innerHTML =
    stat("총 수익률", `${fmt(m.total_return_pct)}%`, signCls(m.total_return_pct)) +
    stat("단순 보유", `${fmt(r.metrics.buy_and_hold_pct)}%`, signCls(r.metrics.buy_and_hold_pct)) +
    stat("최대 낙폭", `${fmt(m.max_drawdown_pct)}%`, "neg") +
    stat("샤프", fmt(m.sharpe)) +
    stat("승률", m.win_rate_pct == null ? "–" : `${m.win_rate_pct}%`) +
    stat("손익비 (PF)", fmt(m.profit_factor)) +
    stat("거래 수", `${m.trades} <span class="small muted">L${m.long_trades}/S${m.short_trades}</span>`) +
    stat("강제청산", m.liquidations, m.liquidations ? "neg" : "") +
    stat("수수료", fmt(m.fees_paid)) + stat("펀딩 비용", fmt(m.funding_paid)) +
    stat("노출 시간", `${m.exposure_pct}%`) + stat("최종 자본", fmt(m.final_equity));

  const pc = resetChart("btPrice", $("#bt-price"));
  const cs = pc.addCandlestickSeries({
    upColor: css("--up"), downColor: css("--down"), borderVisible: false,
    wickUpColor: css("--up"), wickDownColor: css("--down"),
  });
  cs.setData(r.candles);
  // 진입만 L/S 라벨, 청산은 점으로만 (상세는 거래 내역 표)
  cs.setMarkers(r.markers.map((mk) => mk.shape === "circle"
    ? { ...mk, text: "", color: css("--text-muted") }
    : { ...mk, text: mk.text.split(" ")[0], color: mk.position === "belowBar" ? css("--up") : css("--down") }));
  pc.timeScale().fitContent();

  const ec = resetChart("btEquity", $("#bt-equity-chart"));
  const eqSeries = ec.addAreaSeries({ lineColor: css("--series-1"), topColor: "rgba(57,135,229,.25)", bottomColor: "rgba(57,135,229,0)", lineWidth: 2 });
  eqSeries.setData(r.equity_curve);
  eqSeries.createPriceLine({ price: m.initial_equity, color: css("--text-muted"), lineStyle: 2, lineWidth: 1, title: "초기" });
  ec.timeScale().fitContent();
  $("#bt-trades").innerHTML = tradeRows(r.trades.slice().reverse());
}

async function runBacktest() {
  const r = await api("/api/backtest", { method: "POST", body: { spec: state.spec, bars: +$("#bt-bars").value, initial_equity: +$("#bt-equity").value } });
  renderBacktest(r);
}

async function nlAuto(startPaper) {
  const r = await api("/api/strategy/auto", {
    method: "POST",
    body: { text: $("#nl-text").value, symbol: state.symbol, interval: state.interval, bars: +$("#bt-bars").value, initial_equity: +$("#bt-equity").value, start_paper: startPaper },
  });
  setSpec(r.spec, engineNote(r.engine));
  renderBacktest(r);
  if (startPaper) toast(`페이퍼 봇 가동: ${r.paper_bot.id}`);
}

const engineNote = (engine) => engine === "claude"
  ? `Claude가 변환했습니다. 아래 빌더에서 조건을 확인·수정하세요.`
  : `규칙 파서로 변환했습니다 (ANTHROPIC_API_KEY 없음). 복잡한 문장은 키를 설정하면 Claude가 변환합니다.`;

// ------------------------------------------------------------------ 페이퍼 봇
async function loadBots() {
  const bots = await api("/api/paper/bots");
  const el = $("#bot-list");
  if (!bots.length) {
    el.innerHTML = `<div class="card"><p class="hint">실행 중인 봇이 없습니다. 전략 랩에서 “페이퍼 봇 시작”을 누르세요.</p></div>`;
    return;
  }
  el.innerHTML = bots.map((b) => {
    const a = b.account, p = a.position;
    const ret = (a.equity / b.initial_equity - 1) * 100;
    return `<div class="card"><h2>${esc(b.name)} <span class="badge">${b.symbol} · ${b.interval}</span>
        <span class="badge ${b.running ? "on" : "warn"}">${b.running ? "실행 중" : "일시정지"}</span>
        <span class="badge">${esc(b.data_source || "")}</span><span class="spacer"></span>
        <button class="ghost small" data-bot="${b.id}" data-a="${b.running ? "pause" : "resume"}">${b.running ? "일시정지" : "재개"}</button>
        <button class="ghost small" data-bot="${b.id}" data-a="close">포지션 청산</button>
        <button class="ghost small" data-bot="${b.id}" data-a="delete">삭제</button></h2>
      <div class="bot"><div>
        <div class="stats">${stat("평가 자산", fmt(a.equity))}${stat("수익률 (봇 시작 후)", `${fmt(ret)}%`, signCls(ret))}${stat("현재가", fmt(b.last_price, 4))}${stat("거래 수", a.trades.length)}</div>
        <p>${p ? `<b class="${p.side === "long" ? "pos" : "neg"}">${p.side} ${p.leverage}x</b> 진입 ${fmt(p.entry_price, 4)} · 손절 ${fmt(p.stop, 4)} · 익절 ${fmt(p.take, 4)} · 청산가 ${fmt(p.liq_price, 4)} · ROE <span class="${signCls(p.roe_pct)}">${fmt(p.roe_pct)}%</span>` : '<span class="muted">포지션 없음 — 다음 봉 마감 신호 대기</span>'}</p>
        <div class="log">${b.log.slice().reverse().map((l) => `${time(l.time)}  ${esc(l.msg)}`).join("\n")}</div>
      </div><div class="chart" id="bot-eq-${b.id}"></div></div>
      <div class="scroll" style="max-height:180px;margin-top:8px"><table>${tradeRows(a.trades.slice().reverse())}</table></div></div>`;
  }).join("");
  for (const b of bots) {
    const el2 = document.getElementById(`bot-eq-${b.id}`);
    if (b.equity_curve.length < 2) { el2.innerHTML = `<p class="hint">봉이 마감되면 자본 곡선이 그려집니다.</p>`; continue; }
    const c = resetChart(`bot-${b.id}`, el2);
    c.addLineSeries({ color: css("--series-1"), lineWidth: 2 }).setData(b.equity_curve);
    c.timeScale().fitContent();
  }
}

// ------------------------------------------------------------------ 에이전트
const STANCE = { bullish: ["강세", "pos"], bearish: ["약세", "neg"], neutral: ["중립", ""] };
const ACTION = { long: ["롱", "pos"], short: ["숏", "neg"], stay_flat: ["관망", ""] };

async function runAgents(btn) {
  const r = await api("/api/agents/run", { method: "POST", body: { symbol: state.symbol } });
  $("#agents-meta").textContent = `${r.engine === "claude" ? "Claude (" + r.model + ")" : "규칙 기반 (API 키 없음)"} · ${r.elapsed_sec}s · 데이터 ${r.snapshot.data_source}`;
  const cards = Object.values(r.reports).map((a) => {
    const [label, cls] = STANCE[a.stance];
    return `<div class="card agent-card"><h2>${esc(a.name)}</h2>
      <div><span class="stance ${cls}">${label}</span> <span class="muted">확신도 ${a.confidence}</span></div>
      <p>${esc(a.summary)}</p><ul>${a.key_points.map((k) => `<li>${esc(k)}</li>`).join("")}</ul></div>`;
  }).join("");
  const rk = r.risk, d = r.decision;
  const [al, acls] = ACTION[d.action];
  $("#agents-out").innerHTML = `<div class="grid three">${cards}</div>
    <div class="grid two" style="margin-top:12px">
      <div class="card"><h2>리스크 매니저</h2><div class="stats">${stat("최대 레버리지", rk.max_leverage + "x")}${stat("권장 비중", rk.position_pct + "%")}${stat("이벤트 리스크", rk.event_risk ? "있음" : "없음", rk.event_risk ? "neg" : "")}</div>
        <p>${esc(rk.summary)}</p><ul>${rk.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>
      <div class="card decision"><h2>헤드 트레이더 최종 결정</h2>
        <div class="big ${acls}">${al} <span class="muted small">확신도 ${d.confidence}</span></div>
        ${d.action !== "stay_flat" ? `<div class="stats" style="margin-top:8px">${stat("진입", fmt(d.entry, 4))}${stat("손절", fmt(d.stop_loss, 4))}${stat("익절", d.take_profits.map((x) => fmt(x, 4)).join(" / "))}${stat("레버리지 · 비중", `${d.leverage}x · ${d.position_pct}%`)}</div>` : ""}
        <p>${esc(d.rationale)}</p>${d.invalidation ? `<p class="hint">무효화 조건: ${esc(d.invalidation)}</p>` : ""}
        ${d.action !== "stay_flat" ? `<button class="primary" id="exec-decision">페이퍼 계좌에 주문</button>` : ""}
        <p class="hint">투자 조언이 아니며, 실거래 연결은 없습니다.</p></div></div>`;
  const ex = $("#exec-decision");
  if (ex) ex.onclick = () => busy(ex, async () => {
    await api("/api/agents/execute", { method: "POST", body: { symbol: state.symbol, decision: d } });
    toast("에이전트 결정을 페이퍼 계좌에 주문했습니다.");
    loadAccount();
  });
}

// ------------------------------------------------------------------ 마켓
function heatColor(pct) {
  // 발산형: 빨강(하락) ← 회색(0) → 초록(상승), ±8% 에서 포화
  const lerp = (a, b, t) => Math.round(a + (b - a) * t);
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const t = Math.min(1, Math.abs(pct) / 8);
  const [n, e] = [hex(css("--neutral")), hex(pct >= 0 ? css("--up") : css("--down"))];
  return `rgb(${lerp(n[0], e[0], t)},${lerp(n[1], e[1], t)},${lerp(n[2], e[2], t)})`;
}

async function loadMarket() {
  api("/api/market/dominance").then((d) => {
    $("#dom-stats").innerHTML =
      stat("전체 시총", "$" + fmtUsd(d.total_market_cap_usd)) +
      stat("시총 24h", `${fmt(d.market_cap_change_24h_pct)}%`, signCls(d.market_cap_change_24h_pct)) +
      stat("BTC 도미넌스", `${fmt(d.btc_dominance)}%`) + stat("ETH 도미넌스", `${fmt(d.eth_dominance)}%`) +
      stat("스테이블 도미넌스", `${fmt(d.stablecoin_dominance)}%`) + stat("기타 알트", `${fmt(d.others_dominance)}%`);
  }).catch((e) => ($("#dom-stats").innerHTML = `<p class="hint">${esc(e.message)}</p>`));

  api("/api/market/heatmap?limit=60").then((d) => {
    $("#heatmap").innerHTML = d.items.map((x) =>
      `<div class="tile" style="background:${heatColor(x.change_pct)}" title="${x.symbol} 거래대금 $${fmtUsd(x.quote_volume)}">
        <div class="s">${x.symbol.replace("USDT", "")}</div><div class="c">${x.change_pct > 0 ? "+" : ""}${x.change_pct.toFixed(2)}%</div></div>`).join("");
  }).catch((e) => ($("#heatmap").innerHTML = `<p class="hint" style="grid-column:1/-1">${esc(e.message)}</p>`));

  api("/api/news?limit=40").then((d) => {
    $("#news").innerHTML = d.items.length
      ? d.items.map((n) => `<li><span class="src">${esc(n.source)} · ${time(n.time)}</span><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a></li>`).join("")
      : `<li class="hint">뉴스를 불러오지 못했습니다: ${esc(Object.keys(d.errors).join(", "))}</li>`;
  });

  if (!state.loadedMarketWidgets) {
    state.loadedMarketWidgets = true;
    const common = { colorTheme: "dark", isTransparent: true, locale: "kr", width: "100%", height: "100%" };
    embedTvWidget("tv-heatmap", "embed-widget-crypto-coins-heatmap.js", { ...common, dataSource: "Crypto", blockSize: "market_cap_calc", blockColor: "24h_close_change|5", hasTopBar: false, isDataSetEnabled: false, isZoomEnabled: true, hasSymbolTooltip: true });
    embedTvWidget("tv-news", "embed-widget-timeline.js", { ...common, feedMode: "market", market: "crypto", displayMode: "regular" });
    embedTvWidget("tv-calendar", "embed-widget-events.js", { ...common, importanceFilter: "0,1", countryFilter: "us,eu,cn,jp,kr" });
    embedTvWidget("tv-btcd", "embed-widget-symbol-overview.js", { ...common, symbols: [["BTC.D", "CRYPTOCAP:BTC.D|1M"], ["USDT.D", "CRYPTOCAP:USDT.D|1M"]], chartType: "area", chartOnly: false });
  }
}

// ------------------------------------------------------------------ 탭 / 초기화
let accountTimer, botTimer;
function switchTab(name) {
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${name}`));
  clearInterval(accountTimer); clearInterval(botTimer);
  if (name === "trade") { loadAccount(); accountTimer = setInterval(loadAccount, 5000); }
  if (name === "bots") { loadBots(); botTimer = setInterval(loadBots, 15000); }
  if (name === "market") loadMarket();
}

function renderBadges() {
  const s = state.status;
  $("#badges").innerHTML =
    `<span class="badge ${s.llm ? "on" : "warn"}" title="${s.llm ? s.model : "ANTHROPIC_API_KEY 미설정 — 규칙 기반 대체"}">AI ${s.llm ? "연결" : "규칙모드"}</span>` +
    `<span class="badge ${s.coinglass ? "on" : ""}" title="${s.coinglass ? "" : "COINGLASS_API_KEY 미설정 — 바이낸스 공개 데이터 사용"}">CoinGlass ${s.coinglass ? "연결" : "미설정"}</span>` +
    `<span class="badge">데이터 ${s.data_source_mode}</span>`;
}

async function init() {
  state.status = await api("/api/status");
  renderBadges();
  renderStudyChips();
  renderTvChart();
  loadDerivatives();
  setSpec(defaultSpec());
  switchTab("trade");

  $("#tabs").onclick = (e) => e.target.dataset.tab && switchTab(e.target.dataset.tab);
  $("#symbol").onchange = (e) => { state.symbol = e.target.value; renderTvChart(); loadDerivatives(); };
  $("#interval").onchange = (e) => { state.interval = e.target.value; renderTvChart(); loadDerivatives(); };
  $("#study-chips").onclick = (e) => {
    const id = e.target.dataset.study;
    if (!id) return;
    state.studies.has(id) ? state.studies.delete(id) : state.studies.add(id);
    renderStudyChips(); renderTvChart();
  };
  $$("[data-order]").forEach((b) => (b.onclick = () => busy(b, () => placeOrder(b.dataset.order))));
  $("#positions").onclick = (e) => {
    const sym = e.target.dataset.close;
    if (sym) busy(e.target, async () => { await api(`/api/paper/close/${sym}`, { method: "POST" }); loadAccount(); });
  };
  $("#reset-acct").onclick = () => confirm("페이퍼 계좌를 10,000 USDT 로 초기화할까요?") &&
    api("/api/paper/reset", { method: "POST", body: {} }).then(loadAccount);

  $("#builder").addEventListener("input", onBuilderInput);
  $("#builder").addEventListener("change", onBuilderInput);
  $("#builder").addEventListener("click", onBuilderClick);
  $("#json-apply").onclick = () => { try { setSpec(JSON.parse($("#spec-json").value)); toast("JSON 적용됨"); } catch (e) { toast("JSON 오류: " + e.message, true); } };
  $("#spec-to-tv").onclick = specToTv;
  $("#nl-parse").onclick = (e) => busy(e.target, async () => {
    const r = await api("/api/strategy/parse", { method: "POST", body: { text: $("#nl-text").value, symbol: state.symbol, interval: state.interval } });
    setSpec(r.spec, engineNote(r.engine) + (r.problems.length ? `<br><span class="neg">${esc(r.problems.join(" / "))}</span>` : ""));
  });
  $("#nl-auto").onclick = (e) => busy(e.target, () => nlAuto(false));
  $("#nl-auto-paper").onclick = (e) => busy(e.target, () => nlAuto(true));
  $("#bt-run").onclick = (e) => busy(e.target, runBacktest);
  $("#bt-paper").onclick = (e) => busy(e.target, async () => {
    const b = await api("/api/paper/bots", { method: "POST", body: { spec: state.spec, initial_equity: +$("#bt-equity").value } });
    toast(`페이퍼 봇 ${b.id} 가동 — '페이퍼 봇' 탭에서 확인`);
  });
  $("#bot-list").onclick = (e) => {
    const b = e.target.closest("[data-bot]");
    if (!b) return;
    if (b.dataset.a === "delete" && !confirm("봇을 삭제할까요?")) return;
    busy(b, async () => { await api(`/api/paper/bots/${b.dataset.bot}/${b.dataset.a}`, { method: "POST" }); loadBots(); });
  };
  $("#agents-run").onclick = (e) => busy(e.target, () => runAgents(e.target));
}

init().catch((e) => toast("초기화 실패: " + e.message, true));
