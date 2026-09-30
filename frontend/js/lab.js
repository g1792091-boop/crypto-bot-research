// 전략 · 백테스트 · 페이퍼 봇
import { $, IV_LABEL, api, busy, cls, css, emit, esc, fmt, makeChart, pct, px, savePrefs, state, toast, tradeRows } from "./core.js";

const PRICE_REFS = ["close", "open", "high", "low", "volume", "hl2", "hlc3"];
const DERIV_REFS = ["funding", "oi", "oi_change_pct", "long_short"];
const OPS = [">", "<", ">=", "<=", "crosses_above", "crosses_below", "rising", "falling"];
const OP_LABEL = { crosses_above: "상향 돌파", crosses_below: "하향 돌파", rising: "N봉 상승", falling: "N봉 하락" };
const GROUPS = [["long_entry", "롱 진입"], ["short_entry", "숏 진입"], ["long_exit", "롱 청산"], ["short_exit", "숏 청산"]];
const RISK_FIELDS = [
  ["leverage", "레버리지"], ["position_pct", "증거금 비중 %"], ["stop_loss_pct", "손절 %"], ["take_profit_pct", "익절 %"],
  ["atr_stop_mult", "ATR 손절 ×"], ["atr_tp_mult", "ATR 익절 ×"], ["trailing_stop_pct", "추적손절 %"],
  ["fee_pct", "수수료 %"], ["slippage_pct", "슬리피지 %"], ["funding_rate_8h_pct", "펀딩 8h %"],
];
const PARAM_KEYS = ["length", "fast", "slow", "signal", "mult", "k_smooth", "d_smooth"];
const charts = {};

function defaultSpec() {
  return {
    name: "EMA 20/50 크로스", description: "", symbol: state.symbol, interval: "1h",
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
  const typeOpts = (sel) => Object.entries(reg).map(([k, v]) => `<option value="${k}" ${k === sel ? "selected" : ""}>${k}</option>`).join("");
  let html = `<datalist id="refs">${refOptions().map((r) => `<option value="${r}">`).join("")}</datalist>
    <div class="row"><label class="f grow">이름<input data-f="name" value="${esc(s.name)}"></label>
    <label class="f" style="width:110px">심볼<input data-f="symbol" value="${esc(s.symbol)}"></label>
    <label class="f" style="width:80px">봉<select data-f="interval">${Object.entries(IV_LABEL).filter(([k]) => k !== "1y")
      .map(([k, l]) => `<option value="${k}" ${k === s.interval ? "selected" : ""}>${l}</option>`).join("")}</select></label></div>`;
  if (s.description) html += `<div class="help" style="margin-top:6px">${esc(s.description)}</div>`;

  html += `<div class="bsec" style="margin-top:8px"><h4>지표 <button class="flat sm" data-act="add-ind">+ 추가</button></h4>`;
  s.indicators.forEach((ind, i) => {
    const keys = Object.keys(reg[ind.type]?.defaults || {}).filter((k) => PARAM_KEYS.includes(k));
    html += `<div class="ind"><input data-ind="${i}" data-k="id" value="${esc(ind.id)}" title="조건식에서 쓰는 이름">
      <select data-ind="${i}" data-k="type">${typeOpts(ind.type)}</select>
      <div class="params">${keys.map((k) => `<input data-ind="${i}" data-k="${k}" type="number" step="any" placeholder="${k} ${reg[ind.type].defaults[k]}" value="${ind[k] ?? ""}" title="${k}">`).join("") || '<span class="muted">파라미터 없음</span>'}</div>
      <button class="x" data-act="del-ind" data-i="${i}">✕</button></div>`;
  });
  html += `</div>`;

  for (const [g, label] of GROUPS) {
    const grp = s[g];
    html += `<div class="bsec"><h4>${label}
      <select data-grp="${g}" ${grp ? "" : "disabled"} style="height:22px"><option value="all" ${grp?.logic !== "any" ? "selected" : ""}>모두 (AND)</option><option value="any" ${grp?.logic === "any" ? "selected" : ""}>하나라도 (OR)</option></select>
      <button class="flat sm" data-act="add-cond" data-g="${g}">+ 조건</button></h4>`;
    (grp?.conditions || []).forEach((c, i) => {
      html += `<div class="cond"><input list="refs" data-g="${g}" data-ci="${i}" data-k="left" value="${esc(c.left)}">
        <select data-g="${g}" data-ci="${i}" data-k="op">${OPS.map((o) => `<option value="${o}" ${o === c.op ? "selected" : ""}>${OP_LABEL[o] || o}</option>`).join("")}</select>
        <input list="refs" data-g="${g}" data-ci="${i}" data-k="right" value="${esc(c.right)}">
        <button class="x" data-act="del-cond" data-g="${g}" data-i="${i}">✕</button></div>`;
    });
    html += `</div>`;
  }
  html += `<div class="bsec"><h4>리스크 · 비용</h4><div class="risk">${RISK_FIELDS.map(([k, l]) =>
    `<label class="f">${l}<input data-risk="${k}" type="number" step="any" value="${s.risk[k] ?? ""}" placeholder="—"></label>`).join("")}
    <label class="f">반대 신호 전환<select data-risk="allow_reverse"><option value="true" ${s.risk.allow_reverse ? "selected" : ""}>예</option><option value="false" ${s.risk.allow_reverse ? "" : "selected"}>아니오</option></select></label></div>
    <div class="help" style="margin-top:6px">조건에 쓸 수 있는 값: close 등 가격, 지표 이름, <code>macd.hist</code>·<code>bb.lower</code> 같은 세부값,
      <code>funding</code>·<code>oi_change_pct</code>·<code>long_short</code>, 이전 봉 <code>close[1]</code>, 배수 <code>vol_ma*2</code>, 숫자</div></div>`;
  $("#builder").innerHTML = html;
  $("#spec-json").value = JSON.stringify(s, null, 2);
}

function onInput(e) {
  const t = e.target, s = state.spec;
  const num = (v) => (v === "" ? null : Number(v));
  if (t.dataset.f) s[t.dataset.f] = t.value;
  else if (t.dataset.ind != null) {
    const ind = s.indicators[+t.dataset.ind];
    if (t.dataset.k === "type") { s.indicators[+t.dataset.ind] = { id: ind.id, type: t.value }; return renderBuilder(); }
    ind[t.dataset.k] = t.dataset.k === "id" ? t.value : num(t.value);
    if (t.dataset.k === "id" && e.type === "change") return renderBuilder();
  } else if (t.dataset.grp) s[t.dataset.grp].logic = t.value;
  else if (t.dataset.g) s[t.dataset.g].conditions[+t.dataset.ci][t.dataset.k] = t.value;
  else if (t.dataset.risk) s.risk[t.dataset.risk] = t.dataset.risk === "allow_reverse" ? t.value === "true" : num(t.value);
  $("#spec-json").value = JSON.stringify(s, null, 2);
}

function onClick(e) {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  const s = state.spec, act = b.dataset.act;
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

function setSpec(spec, note) {
  state.spec = spec;
  renderBuilder();
  if (note != null) $("#nl-engine").innerHTML = note;
}
const engineNote = (engine) => engine === "claude" ? "Claude가 변환했습니다. 아래에서 조건을 확인하세요."
  : "기본 변환기로 변환했습니다. 복잡한 문장은 settings.txt 에 ANTHROPIC_API_KEY 를 넣으면 Claude가 처리합니다.";

function specToTv() {
  const reg = state.status?.indicators || {};
  state.studies = [...new Set(state.spec.indicators.filter((i) => reg[i.type]?.tv).map((i) => reg[i.type].tv))];
  state.chartMode = "tv";
  savePrefs();
  emit("goto", "trade");
  emit("rechart");
  toast("트레이딩뷰 차트에 전략 지표를 표시했습니다", "트레이딩뷰에 없는 지표(슈퍼트렌드 등)는 제외됩니다.");
}

function renderBacktest(r) {
  if (r.warnings?.length) toast("데이터 경고", r.warnings.join(" / "), "err");
  const m = r.metrics;
  $("#bt-src").textContent = `${r.data_source === "synthetic" ? "가상 데이터 (거래소 연결 안 됨)" : "바이낸스 선물"}${r.derivatives_source ? " · 파생: " + r.derivatives_source : ""}`;
  const st = (k, v, c = "") => `<div class="stat"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`;
  $("#bt-stats").innerHTML = st("수익률", pct(m.total_return_pct), cls(m.total_return_pct)) + st("단순 보유", pct(m.buy_and_hold_pct), cls(m.buy_and_hold_pct)) +
    st("최대 낙폭", `-${fmt(m.max_drawdown_pct)}%`, "down") + st("샤프", fmt(m.sharpe)) + st("승률", m.win_rate_pct == null ? "–" : `${m.win_rate_pct}%`) +
    st("손익비", fmt(m.profit_factor)) + st("거래", `${m.trades} <span class="muted" style="font-size:11px">L${m.long_trades} S${m.short_trades}</span>`) +
    st("강제청산", m.liquidations, m.liquidations ? "down" : "") + st("수수료", fmt(m.fees_paid)) + st("펀딩 비용", fmt(m.funding_paid)) +
    st("보유 시간", `${m.exposure_pct}%`) + st("최종 자본", fmt(m.final_equity));

  charts.p?.remove();
  const pc = (charts.p = makeChart($("#bt-price")));
  const cs = pc.addCandlestickSeries({ upColor: css("--up"), downColor: css("--down"), borderVisible: false, wickUpColor: css("--up"), wickDownColor: css("--down") });
  cs.setData(r.candles);
  cs.setMarkers(r.markers.map((mk) => mk.shape === "circle"
    ? { ...mk, text: "", color: css("--muted") }
    : { ...mk, text: mk.text.split(" ")[0], color: mk.position === "belowBar" ? css("--up") : css("--down") }));
  pc.timeScale().fitContent();
  charts.e?.remove();
  const ec = (charts.e = makeChart($("#bt-equity-chart")));
  const es = ec.addAreaSeries({ lineColor: css("--s1"), topColor: "rgba(57,135,229,.22)", bottomColor: "rgba(57,135,229,0)", lineWidth: 2 });
  es.setData(r.equity_curve);
  es.createPriceLine({ price: m.initial_equity, color: css("--muted"), lineStyle: 2, lineWidth: 1, title: "시작" });
  ec.timeScale().fitContent();
  $("#bt-trades").innerHTML = tradeRows(r.trades.slice().reverse());
}

async function nlAuto(startPaper) {
  const r = await api("/api/strategy/auto", { method: "POST", body: { text: $("#nl-text").value, symbol: state.symbol,
    bars: +$("#bt-bars").value, initial_equity: +$("#bt-equity").value, start_paper: startPaper } });
  setSpec(r.spec, engineNote(r.engine));
  renderBacktest(r);
  if (startPaper) { toast("페이퍼 봇 시작", r.paper_bot.name); loadBots(); }
}

async function loadBots() {
  let bots;
  try { bots = await api("/api/paper/bots"); } catch { return; }
  const el = $("#bot-list");
  if (!bots.length) { el.innerHTML = `<div class="empty">실행 중인 봇이 없습니다.</div>`; return; }
  el.innerHTML = bots.map((b) => {
    const a = b.account, p = a.position, ret = (a.equity / b.initial_equity - 1) * 100;
    return `<div style="padding:10px 12px;border-bottom:1px solid var(--line)">
      <div class="row"><b class="grow">${esc(b.name)}</b><span class="muted">${b.symbol} · ${IV_LABEL[b.interval] || b.interval}</span>
        <span class="${b.running ? "up" : "muted"}">${b.running ? "실행 중" : "정지"}</span>
        <button class="sm" data-bot="${b.id}" data-a="${b.running ? "pause" : "resume"}">${b.running ? "정지" : "재개"}</button>
        <button class="sm" data-bot="${b.id}" data-a="close">청산</button><button class="sm" data-bot="${b.id}" data-a="delete">삭제</button></div>
      <div class="row dim" style="margin-top:4px;gap:14px"><span>자산 <b>${fmt(a.equity)}</b></span><span class="${cls(ret)}">${pct(ret)}</span>
        <span>거래 ${a.trades.length}</span><span>${p ? `<span class="${p.side === "long" ? "up" : "down"}">${p.side === "long" ? "롱" : "숏"} ${p.leverage}x</span> ${px(p.entry_price)} · ROE ${pct(p.roe_pct)}` : "포지션 없음"}</span></div>
      ${b.log.length ? `<div class="log" style="margin-top:6px">${b.log.slice(-5).reverse().map((l) => esc(l.msg)).join("\n")}</div>` : ""}</div>`;
  }).join("");
}

export function initLab() {
  setSpec(defaultSpec());
  $("#builder").addEventListener("input", onInput);
  $("#builder").addEventListener("change", onInput);
  $("#builder").addEventListener("click", onClick);
  $("#json-apply").onclick = () => { try { setSpec(JSON.parse($("#spec-json").value)); toast("적용했습니다"); } catch (e) { toast("JSON 오류", e.message, "err"); } };
  $("#spec-to-tv").onclick = specToTv;
  $("#nl-parse").onclick = (e) => busy(e.target, async () => {
    const r = await api("/api/strategy/parse", { method: "POST", body: { text: $("#nl-text").value, symbol: state.symbol } });
    setSpec(r.spec, engineNote(r.engine) + (r.problems.length ? `<br><span class="down">${esc(r.problems.join(" / "))}</span>` : ""));
  });
  $("#nl-auto").onclick = (e) => busy(e.target, () => nlAuto(false));
  $("#nl-auto-paper").onclick = (e) => busy(e.target, () => nlAuto(true));
  $("#bt-run").onclick = (e) => busy(e.target, async () => renderBacktest(await api("/api/backtest", { method: "POST",
    body: { spec: state.spec, bars: +$("#bt-bars").value, initial_equity: +$("#bt-equity").value } })));
  $("#bt-paper").onclick = (e) => busy(e.target, async () => {
    const b = await api("/api/paper/bots", { method: "POST", body: { spec: state.spec, initial_equity: +$("#bt-equity").value } });
    toast("페이퍼 봇 시작", b.name); loadBots();
  });
  $("#bot-list").onclick = (e) => {
    const b = e.target.closest("[data-bot]");
    if (!b || (b.dataset.a === "delete" && !confirm("봇을 삭제할까요?"))) return;
    busy(b, async () => { await api(`/api/paper/bots/${b.dataset.bot}/${b.dataset.a}`, { method: "POST" }); loadBots(); });
  };
  loadBots(); setInterval(loadBots, 15_000);
}
