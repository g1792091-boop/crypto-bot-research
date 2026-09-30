// 전략 대화 · 백테스트 · 복기/자동 개선 · 페이퍼 봇
import { $, $$, INTERVALS, IV_LABEL, api, busy, cls, css, emit, esc, fmt, makeChart, mdhm, pct, px, savePrefs, state, toast, tradeRows } from "./core.js";
import { showOnChart } from "./trade.js";

const AI = { claude: "Claude", gemini: "Gemini" };

const LC = LightweightCharts;
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

// 대화 · 버전은 브라우저에 저장 (새로고침해도 유지)
const lab = (() => { try { return JSON.parse(localStorage.getItem("ft.lab") || "null"); } catch { return null; } })() || { chat: [], versions: [], cur: -1 };
const saveLab = () => { try { localStorage.setItem("ft.lab", JSON.stringify({ ...lab, chat: lab.chat.slice(-80), versions: lab.versions.slice(-40) })); } catch { /* 무시 */ } };
let lastResult = null;

// ================================================================ 대화
function renderChat() {
  const el = $("#chat");
  el.innerHTML = lab.chat.length ? lab.chat.map((m) => `<div class="msg ${m.role === "user" ? "me" : "bot"}">${esc(m.text)}${
    m.changes?.length ? `<ul>${m.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}${m.delta ? `<div class="delta">${m.delta}</div>` : ""}</div>`).join("")
    : `<div class="msg bot">원하는 진입 기준을 말로 설명해 주세요. 전략으로 만들어 바로 백테스트합니다.
그다음엔 고칠 점이나 부족한 점을 계속 말하면 그때마다 수정하고 다시 백테스트해서 전·후를 비교해 드립니다.
"알아서 개선해줘"라고 하면 손실 거래를 분석해 검증을 통과한 개선만 적용합니다.</div>`;
  el.scrollTop = el.scrollHeight;
}

const M = (m) => m && { ret: m.total_return_pct, mdd: m.max_drawdown_pct, win: m.win_rate_pct, pf: m.profit_factor, n: m.trades };
function delta(a, b) {
  if (!b) return "";
  const f = (v, s = "%") => v == null ? "–" : `${fmt(v, 1)}${s}`;
  const arrow = (x, y, good) => `${x} → <span class="${good ? "up" : "down"}">${y}</span>`;
  if (!a) return `수익률 ${f(b.ret)} · 최대낙폭 ${f(b.mdd)} · 승률 ${f(b.win)} · 손익비 ${fmt(b.pf)} · 거래 ${b.n}`;
  return [`수익률 ${arrow(f(a.ret), f(b.ret), (b.ret ?? 0) >= (a.ret ?? 0))}`, `최대낙폭 ${arrow(f(a.mdd), f(b.mdd), (b.mdd ?? 0) <= (a.mdd ?? 0))}`,
    `승률 ${arrow(f(a.win), f(b.win), (b.win ?? 0) >= (a.win ?? 0))}`, `손익비 ${arrow(fmt(a.pf), fmt(b.pf), (b.pf ?? 0) >= (a.pf ?? 0))}`, `거래 ${a.n} → ${b.n}`].join(" · ");
}

function addVersion(spec, metrics, label) {
  lab.versions = lab.versions.slice(0, lab.cur + 1);
  lab.versions.push({ spec, metrics: M(metrics), label, time: Math.floor(Date.now() / 1000) });
  lab.cur = lab.versions.length - 1;
  saveLab(); renderVersions();
}

function renderVersions() {
  $("#versions").innerHTML = lab.versions.length ? lab.versions.map((v, i) => `<div class="ver ${i === lab.cur ? "cur" : ""}" data-ver="${i}">
      <span class="v">v${i + 1}</span><span>${esc(v.label)}</span><span class="${cls(v.metrics?.ret)}">${v.metrics ? pct(v.metrics.ret, 1) : ""}</span></div>`).reverse().join("")
    : `<div class="empty">아직 없습니다.</div>`;
}

async function send(text) {
  text = text.trim();
  if (!text) return;
  lab.chat.push({ role: "user", text });
  renderChat();
  $("#chat-text").value = "";
  const bars = +$("#bt-bars").value, eq = +$("#bt-equity").value;
  try {
    if (!lab.versions.length || lab.fresh) {   // 첫 문장은 새 전략 작성, 이후는 수정
      // 문장에 코인·봉이 없으면 위 '대상'의 코인·봉으로 만든다
      const r = await api("/api/strategy/auto", { method: "POST", body: { text, symbol: state.spec?.symbol || state.symbol, interval: state.spec?.interval || "1h", bars, initial_equity: eq } });
      lab.fresh = false;
      setSpec(r.spec);
      renderBacktest(r);
      addVersion(r.spec, r.metrics, "처음 작성");
      lab.chat.push({ role: "bot", text: `'${r.spec.name}' 전략을 만들어 ${r.spec.symbol} ${IV_LABEL[r.spec.interval] || r.spec.interval} ${r.candles.length}봉으로 백테스트했습니다.${AI[r.engine] ? ` (${AI[r.engine]})` : " (기본 변환기 사용)"}${r.ai_error ? `\n※ AI를 쓰지 못해 기본 변환기로 처리했습니다: ${r.ai_error}` : ""}\n고칠 점을 말해 주세요.`,
        delta: delta(null, M(r.metrics)) });
    } else {
      const before = lab.versions[lab.cur]?.metrics, prev = state.spec;
      const history = lab.chat.slice(-10).map((m) => ({ role: m.role, text: m.text }));
      const r = await api("/api/strategy/refine", { method: "POST", body: { spec: state.spec, message: text, history, metrics: lastResult?.metrics, bars } });
      if (r.backtest) {
        setSpec(r.spec);
        renderBacktest(r.backtest);
        addVersion(r.spec, r.backtest.metrics, (r.changes || []).join(", ").slice(0, 60) || text.slice(0, 40));
      }
      if (r.improve) renderImprove(r.improve, false);
      let reply = r.reply + (r.ai_error ? `\n※ AI를 쓰지 못해 기본 편집기로 처리했습니다: ${r.ai_error}` : "");
      if (r.spec && (r.spec.symbol !== prev?.symbol || r.spec.interval !== prev?.interval) && r.backtest) reply += `\n(대상: ${r.spec.symbol} ${IV_LABEL[r.spec.interval] || r.spec.interval})`;
      const after = r.backtest && M(r.backtest.metrics);
      if (before && after && r.engine !== "improve") {
        const warn = [];
        if (after.n < before.n * 0.4) warn.push(`거래 수가 ${before.n} → ${after.n}건으로 크게 줄었습니다. 조건이 같은 봉에 동시에 맞기 어려운 조합일 수 있습니다 (예: 크로스 조건 두 개). 둘 중 하나를 '>' / '<' 같은 상태 조건으로 바꾸는 것을 고려하세요.`);
        if ((after.ret ?? 0) < (before.ret ?? 0) - 5) warn.push(`수익률이 나빠졌습니다. 버전 기록에서 v${lab.cur} 을 누르면 이전 버전으로 되돌릴 수 있습니다.`);
        if (after.n < 10) warn.push("거래가 10건 미만이라 결과를 믿기 어렵습니다. 봉 개수를 늘리거나 조건을 완화해 보세요.");
        if (warn.length) reply += "\n\n주의: " + warn.join("\n");
      }
      lab.chat.push({ role: "bot", text: reply, changes: r.changes, delta: r.backtest ? delta(before, after) : "" });
      $("#chat-engine").textContent = AI[r.engine] || (r.engine === "improve" ? "자동 개선" : "기본 편집기");
    }
  } catch (e) {
    lab.chat.push({ role: "bot", text: "처리하지 못했습니다: " + e.message });
  }
  saveLab(); renderChat();
}

// ================================================================ 편집기
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
  const typeOpts = (sel) => Object.keys(reg).map((k) => `<option value="${k}" ${k === sel ? "selected" : ""}>${k}</option>`).join("");
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
    <label class="f">반대 신호 전환<select data-risk="allow_reverse"><option value="true" ${s.risk.allow_reverse ? "selected" : ""}>예</option><option value="false" ${s.risk.allow_reverse ? "" : "selected"}>아니오</option></select></label></div></div>`;
  $("#builder").innerHTML = html;
  $("#spec-json").value = JSON.stringify(s, null, 2);
  syncTarget();
}

// ================================================================ 대상 코인 · 봉
const LAB_IVS = INTERVALS.filter(([k]) => k !== "1y");
function syncTarget() {
  if (!$("#lab-sym")) return;
  $("#lab-sym").value = (state.spec.symbol || "").replace(/USDT$/, "");
  $("#lab-iv").value = state.spec.interval;
}
async function resolveSym(q) {
  q = (q || "").trim();
  if (!q) return null;
  try { return (await api(`/api/resolve?q=${encodeURIComponent(q)}`)).symbol; } catch { return null; }
}
const btBody = (spec) => ({ spec, bars: +$("#bt-bars").value, initial_equity: +$("#bt-equity").value });
async function runBacktest(spec = state.spec) {
  const r = await api("/api/backtest", { method: "POST", body: btBody(spec) });
  renderBacktest(r);
  return r;
}
// 전략은 그대로 두고 코인·봉만 바꿔서 다시 백테스트 (실패하면 원래대로)
async function setTarget(symbol, interval, why = "대상 변경") {
  const prev = { symbol: state.spec.symbol, interval: state.spec.interval };
  if (symbol === prev.symbol && interval === prev.interval && lastResult) return lastResult;
  state.spec.symbol = symbol; state.spec.interval = interval; renderBuilder();
  try {
    const r = await runBacktest();
    addVersion(state.spec, r.metrics, `${why}: ${symbol.replace(/USDT$/, "")} ${IV_LABEL[interval] || interval}`);
    return r;
  } catch (e) {
    Object.assign(state.spec, prev); renderBuilder();
    toast("백테스트 실패", e.message, "err");
    return null;
  }
}
async function runImprove() {
  renderImprove(await api("/api/strategy/improve", { method: "POST", body: { spec: state.spec, bars: +$("#bt-bars").value, ai: !!state.status?.llm } }));
  $("#improve-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}
async function startBot(spec = state.spec) {
  const b = await api("/api/paper/bots", { method: "POST", body: { spec, initial_equity: +$("#bt-equity").value } });
  toast(`페이퍼 봇 시작 · ${b.symbol.replace(/USDT$/, "")} ${IV_LABEL[b.interval] || b.interval}`, `${b.name} — 진입·청산이 '트레이드' 차트에 표시됩니다`);
  loadBots();
  return b;
}

// ================================================================ 여러 코인 · 봉 한꺼번에
const scan = lab.scan ||= { syms: null, ivs: ["15m", "1h", "4h", "1d"] };
let scanRows = [];
function renderScanPicker() {
  scan.syms ||= state.watch.slice(0, 6);
  $("#scan-syms").innerHTML = scan.syms.map((s) => `<span class="chk on" data-rm="${s}" title="눌러서 빼기">${s.replace(/USDT$/, "")} ✕</span>`).join("")
    || '<span class="muted">코인을 추가하세요</span>';
  $("#scan-ivs").innerHTML = LAB_IVS.map(([k, l]) => `<span class="chk ${scan.ivs.includes(k) ? "on" : ""}" data-iv="${k}">${l}</span>`).join("");
  const n = scan.syms.length * scan.ivs.length;
  $("#scan-count").textContent = `${scan.syms.length}개 코인 × ${scan.ivs.length}개 봉 = ${n}개 조합${n > 80 ? " (80개까지 가능)" : ""}`;
}
function renderScan() {
  const ok = scanRows.filter((r) => !r.error);
  $("#scan-top").hidden = !ok.length;
  const st = (v, d = 1) => v == null ? "–" : fmt(v, d);
  $("#scan-out").innerHTML = scanRows.length ? `<table><tr><th>#</th><th>코인</th><th>봉</th><th>수익률</th><th>단순 보유</th><th>최대낙폭</th><th>승률</th><th>손익비</th><th>거래</th><th></th></tr>
    ${scanRows.map((r, i) => r.error
      ? `<tr><td></td><td>${r.symbol.replace(/USDT$/, "")}</td><td>${IV_LABEL[r.interval] || r.interval}</td><td colspan="7" class="muted">${esc(r.error)}</td></tr>`
      : `<tr><td class="muted">${i + 1}</td><td><b>${r.symbol.replace(/USDT$/, "")}</b>${r.data_source === "synthetic" ? ' <span class="accent" title="거래소 연결 안 됨">가상</span>' : ""}</td>
        <td>${IV_LABEL[r.interval] || r.interval}</td><td class="${cls(r.metrics.total_return_pct)}">${pct(r.metrics.total_return_pct)}</td>
        <td class="${cls(r.metrics.buy_and_hold_pct)}">${pct(r.metrics.buy_and_hold_pct)}</td><td class="down">-${st(r.metrics.max_drawdown_pct)}%</td>
        <td>${r.metrics.win_rate_pct == null ? "–" : r.metrics.win_rate_pct + "%"}</td><td>${st(r.metrics.profit_factor, 2)}</td><td>${r.metrics.trades}</td>
        <td style="white-space:nowrap"><button class="sm" data-scan="view" data-i="${i}">보기</button><button class="sm" data-scan="improve" data-i="${i}">개선</button><button class="sm" data-scan="bot" data-i="${i}">봇 시작</button></td></tr>`).join("")}</table>
    <div class="help" style="margin-top:6px">같은 기간 수가 아니라 같은 봉 개수(${$("#bt-bars").value}개)로 비교합니다. 과거 성적이 좋다고 앞으로도 좋다는 보장은 없습니다 — '개선'은 학습/검증 구간을 나눠 검증을 통과한 것만 적용합니다.</div>`
    : "";
}

function onInput(e) {
  const t = e.target, s = state.spec, num = (v) => (v === "" ? null : Number(v));
  if (t.dataset.f === "symbol" && e.type === "change") { resolveSym(t.value).then((v) => { if (v) { s.symbol = v; renderBuilder(); } }); return; }
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
  if (act === "add-ind") { let n = s.indicators.length + 1; while (s.indicators.some((i) => i.id === `ind${n}`)) n++; s.indicators.push({ id: `ind${n}`, type: "sma", length: 20 }); }
  else if (act === "del-ind") s.indicators.splice(+b.dataset.i, 1);
  else if (act === "add-cond") { s[b.dataset.g] = s[b.dataset.g] || { logic: "all", conditions: [] }; s[b.dataset.g].conditions.push({ left: "close", op: ">", right: s.indicators[0]?.id || "0" }); }
  else if (act === "del-cond") { const g = s[b.dataset.g]; g.conditions.splice(+b.dataset.i, 1); if (!g.conditions.length) s[b.dataset.g] = null; }
  renderBuilder();
}

function setSpec(spec) { state.spec = structuredClone(spec); renderBuilder(); }

function specToTv() {
  const reg = state.status?.indicators || {};
  state.studies = [...new Set(state.spec.indicators.filter((i) => reg[i.type]?.tv).map((i) => reg[i.type].tv))];
  state.chartMode = "tv";
  savePrefs(); emit("goto", "trade"); emit("rechart");
  toast("트레이딩뷰 차트에 전략 지표를 표시했습니다", "트레이딩뷰에 없는 지표(슈퍼트렌드 등)는 제외됩니다.");
}

// ================================================================ 결과
function renderBacktest(r) {
  lastResult = r;
  // 퀀트 화면(몬테카를로 · 포지션 크기 계산기)이 쓰도록
  state.lastBacktest = { name: state.spec?.name, symbol: state.spec?.symbol, interval: state.spec?.interval, trades: r.trades, initial: r.metrics.initial_equity, metrics: r.metrics };
  emit("backtest", state.lastBacktest);
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
  const cs = pc.addSeries(LC.CandlestickSeries, { upColor: css("--up"), downColor: css("--down"), borderVisible: false, wickUpColor: css("--up"), wickDownColor: css("--down") });
  cs.setData(r.candles);
  LC.createSeriesMarkers(cs, r.markers.map((mk) => mk.shape === "circle"
    ? { ...mk, text: mk.text.includes("-") ? "손절" : "익절", color: mk.text.includes("-") ? css("--down") : css("--up") }
    : { ...mk, text: mk.text.startsWith("L") ? "롱" : "숏", color: mk.position === "belowBar" ? css("--up") : css("--down") }));
  pc.timeScale().fitContent();
  charts.e?.remove();
  const ec = (charts.e = makeChart($("#bt-equity-chart")));
  const es = ec.addSeries(LC.AreaSeries, { lineColor: css("--s1"), topColor: "rgba(57,135,229,.22)", bottomColor: "rgba(57,135,229,0)", lineWidth: 2 });
  es.setData(r.equity_curve);
  es.createPriceLine({ price: m.initial_equity, color: css("--muted"), lineStyle: 2, lineWidth: 1, title: "시작" });
  ec.timeScale().fitContent();
  $("#bt-trades").innerHTML = tradeRows(r.trades.slice().reverse());
}

// ================================================================ 복기 · 자동 개선
let lastImprove = null;
function renderImprove(rep, offerApply = true) {
  lastImprove = rep;
  $("#improve-panel").hidden = false;
  const sc = (x) => `${x.net_pnl >= 0 ? "+" : ""}${fmt(x.net_pnl, 0)} · 승률 ${x.win_rate ?? "–"}% · PF ${x.profit_factor ?? "–"} · ${x.trades}건`;
  const row = (label, a) => `<tr><td>${label}</td><td class="${cls(a.train.net_pnl)}">${sc(a.train)}</td><td class="${cls(a.test.net_pnl)}">${sc(a.test)}</td></tr>`;
  $("#improve-out").innerHTML = `
    <div style="margin-bottom:8px">${rep.applied ? `<b class="up">검증을 통과한 개선</b>: ${rep.changes.map(esc).join(" / ")}`
      : `<b class="accent">적용할 개선 없음</b> — 여러 개선안이 검증 구간(최근 30%)에서 성과를 떨어뜨려 전략을 그대로 두는 것이 낫습니다.`}</div>
    <table><tr><th>구분</th><th>학습 구간 (앞 70%)</th><th>검증 구간 (뒤 30%, 개선에 안 쓴 데이터)</th></tr>
      ${row("현재 전략", rep.baseline)}${rep.applied ? row("개선 후", rep.after) : ""}</table>
    ${rep.applied && offerApply ? `<div class="row" style="margin:8px 0"><button class="pri sm" id="imp-apply">개선안 적용</button><span class="muted">적용하면 새 버전으로 저장되고 다시 백테스트합니다</span></div>` : ""}
    ${rep.ai_summary ? `<div class="ai" style="padding:8px 0">${esc(rep.ai_summary)}</div>` : ""}
    <div class="cols-2" style="margin-top:10px">
      <div><div class="sub" style="padding-left:0">손실 원인 (많이 나온 순)</div>${rep.loss_causes.map((c) => `<div class="lv" style="padding:3px 0"><span>${esc(c.cause)} <span class="muted">${c.count}건</span></span><span class="px down">${fmt(c.pnl, 0)}</span></div>`).join("") || '<div class="muted">없음</div>'}</div>
      <div><div class="sub" style="padding-left:0">익절 거래의 공통점</div>${rep.win_traits.map((c) => `<div class="lv" style="padding:3px 0"><span>${esc(c.cause)} <span class="muted">${c.count}건</span></span><span class="px up">+${fmt(c.pnl, 0)}</span></div>`).join("") || '<div class="muted">없음</div>'}</div>
    </div>
    <div class="sub" style="padding-left:0;margin-top:8px">시험한 개선안</div>
    <table><tr><th>변경</th><th>학습 손익</th><th>검증 손익</th><th>결과</th></tr>${rep.candidates.map((c) => `<tr><td>${esc(c.change)}</td>
      <td class="${cls(c.train.net_pnl)}">${fmt(c.train.net_pnl, 0)}</td><td class="${cls(c.test.net_pnl)}">${fmt(c.test.net_pnl, 0)}</td>
      <td class="${c.passed ? "up" : "muted"}">${c.passed ? "통과" : "탈락"}</td></tr>`).join("") || '<tr><td class="muted">개선 후보가 없습니다</td></tr>'}</table>
    <div class="sub" style="padding-left:0;margin-top:8px">거래 복기 (최근)</div>
    ${rep.journal.slice(-15).reverse().map((n) => `<div class="note ${n.win ? "win" : "loss"}"><span class="muted">${mdhm(n.entry_time)}</span> ${esc(n.note)}</div>`).join("")}`;
  const ap = $("#imp-apply");
  if (ap) ap.onclick = () => busy(ap, async () => {
    const r = await api("/api/backtest", { method: "POST", body: { spec: rep.spec, bars: +$("#bt-bars").value, initial_equity: +$("#bt-equity").value } });
    const before = lab.versions[lab.cur]?.metrics;
    setSpec(rep.spec); renderBacktest(r); addVersion(rep.spec, r.metrics, "자동 개선: " + rep.changes.join(", ").slice(0, 50));
    lab.chat.push({ role: "bot", text: "자동 개선안을 적용했습니다.", changes: rep.changes, delta: delta(before, M(r.metrics)) });
    saveLab(); renderChat(); ap.remove();
  });
}

// ================================================================ 페이퍼 봇
async function loadBots() {
  let bots;
  try { bots = await api("/api/paper/bots"); } catch { return; }
  const el = $("#bot-list");
  if (!bots.length) { el.innerHTML = `<div class="empty">실행 중인 봇이 없습니다. 위에서 '페이퍼 봇 시작'을 누르세요.</div>`; return; }
  const open = new Set($$("#bot-list details[open]").map((d) => d.dataset.id));
  el.innerHTML = bots.map((b) => {
    const a = b.account, p = a.position, ret = (a.equity / b.initial_equity - 1) * 100;
    return `<div style="padding:10px 12px;border-bottom:1px solid var(--line)">
      <div class="row"><b class="grow">${esc(b.name)}</b><span class="muted">${b.symbol} · ${IV_LABEL[b.interval] || b.interval}</span>
        <span class="${b.running ? "up" : "muted"}">${b.running ? "실행 중" : "정지"}</span>
        <button class="sm" data-chart="${b.symbol}|${b.interval}">차트에서 보기</button>
        <button class="sm" data-bot="${b.id}" data-a="${b.running ? "pause" : "resume"}">${b.running ? "정지" : "재개"}</button>
        <button class="sm" data-bot="${b.id}" data-a="close">청산</button><button class="sm" data-bot="${b.id}" data-a="delete">삭제</button></div>
      <div class="row dim" style="margin-top:4px;gap:14px"><span>자산 <b>${fmt(a.equity)}</b></span><span class="${cls(ret)}">${pct(ret)}</span>
        <span>거래 ${a.trades.length}</span><span>${p ? `<span class="${p.side === "long" ? "up" : "down"}">${p.side === "long" ? "롱" : "숏"} ${p.leverage}x</span> ${px(p.entry_price)} · ROE ${pct(p.roe_pct)}` : "포지션 없음"}</span></div>
      <div class="row" style="margin-top:6px;gap:8px">
        <label class="row" style="gap:4px"><input type="checkbox" data-auto="${b.id}" ${b.auto_improve ? "checked" : ""} style="height:auto"> 자동 개선</label>
        <span class="muted">새 거래</span><input type="number" data-every="${b.id}" value="${b.improve_every}" min="3" style="width:52px;height:22px"><span class="muted">건마다</span>
        <button class="sm" data-improve="${b.id}">지금 복기·개선</button><span class="muted">전략 버전 ${b.versions.length}</span></div>
      <details data-id="${b.id}" ${open.has(b.id) ? "open" : ""}><summary class="muted" style="margin-top:6px;cursor:pointer">복기 노트 · 변경 기록 · 로그</summary>
        ${b.versions.slice(1).reverse().map((v) => `<div class="note"><span class="accent">${mdhm(v.time)} 전략 변경</span> ${esc(v.reason)}</div>`).join("")}
        ${b.journal.slice().reverse().slice(0, 10).map((n) => `<div class="note ${n.win ? "win" : "loss"}"><span class="muted">${mdhm(n.exit_time)}</span> ${esc(n.note)}</div>`).join("") || '<div class="muted" style="padding:4px 0">아직 끝난 거래가 없습니다.</div>'}
        <div class="log" style="margin-top:6px">${b.log.slice(-8).reverse().map((l) => `${mdhm(l.time)}  ${esc(l.msg)}`).join("\n")}</div></details></div>`;
  }).join("");
}

export function initLab() {
  const cur = lab.versions[lab.cur];
  setSpec(cur ? cur.spec : defaultSpec());
  renderChat(); renderVersions();
  $("#builder").addEventListener("input", onInput);
  $("#builder").addEventListener("change", onInput);
  $("#builder").addEventListener("click", onClick);
  $("#chat-send").onclick = (e) => busy(e.target, () => send($("#chat-text").value));
  $("#chat-text").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#chat-send").click(); } };
  $("#chat-chips").onclick = (e) => { const q = e.target.dataset.q; if (q) busy(e.target, () => send(q)); };
  $("#chat-new").onclick = () => { lab.chat = []; lab.fresh = true; saveLab(); renderChat(); $("#chat-text").focus(); };
  $("#versions").onclick = (e) => {
    const v = e.target.closest("[data-ver]");
    if (!v) return;
    lab.cur = +v.dataset.ver; saveLab(); renderVersions();
    setSpec(lab.versions[lab.cur].spec);
    busy(v, async () => renderBacktest(await api("/api/backtest", { method: "POST", body: { spec: state.spec, bars: +$("#bt-bars").value, initial_equity: +$("#bt-equity").value } })));
  };
  $("#json-apply").onclick = () => { try { setSpec(JSON.parse($("#spec-json").value)); toast("적용했습니다"); } catch (e) { toast("JSON 오류", e.message, "err"); } };
  $("#spec-to-tv").onclick = (e) => { e.preventDefault(); specToTv(); };
  $("#bt-run").onclick = (e) => busy(e.target, async () => { const r = await runBacktest(); addVersion(state.spec, r.metrics, "직접 편집"); });
  $("#bt-improve").onclick = (e) => busy(e.target, runImprove);
  $("#bt-paper").onclick = (e) => busy(e.target, () => startBot());

  // 대상 코인 · 봉
  $("#lab-iv").innerHTML = LAB_IVS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("");
  syncTarget();
  $("#lab-sym").onchange = async (e) => {
    const sym = await resolveSym(e.target.value);
    if (!sym) { syncTarget(); return; }
    setTarget(sym, state.spec.interval);
  };
  $("#lab-sym").onkeydown = (e) => { if (e.key === "Enter") e.target.blur(); };
  $("#lab-iv").onchange = (e) => setTarget(state.spec.symbol, e.target.value);
  $("#lab-sync").onclick = (e) => busy(e.target, () => setTarget(state.symbol, state.interval === "1y" ? "1M" : state.interval, "차트 코인으로"));

  // 여러 코인 · 봉 한꺼번에
  renderScanPicker();
  $("#scan-syms").onclick = (e) => { const s = e.target.closest("[data-rm]")?.dataset.rm; if (s) { scan.syms = scan.syms.filter((x) => x !== s); saveLab(); renderScanPicker(); } };
  $("#scan-ivs").onclick = (e) => {
    const k = e.target.closest("[data-iv]")?.dataset.iv;
    if (!k) return;
    scan.ivs = scan.ivs.includes(k) ? scan.ivs.filter((x) => x !== k) : LAB_IVS.map(([x]) => x).filter((x) => x === k || scan.ivs.includes(x));
    saveLab(); renderScanPicker();
  };
  $("#scan-add").onkeydown = async (e) => {
    if (e.key !== "Enter" || !e.target.value.trim()) return;
    const sym = await resolveSym(e.target.value); e.target.value = "";
    if (sym && !scan.syms.includes(sym)) { scan.syms.push(sym); saveLab(); renderScanPicker(); }
  };
  $("#scan-all-watch").onclick = () => { scan.syms = [...new Set([...scan.syms, ...state.watch])]; saveLab(); renderScanPicker(); };
  $("#scan-clear").onclick = () => { scan.syms = []; saveLab(); renderScanPicker(); };
  $("#scan-run").onclick = (e) => busy(e.target, async () => {
    if (!scan.syms.length || !scan.ivs.length) return toast("코인과 봉을 하나 이상 고르세요");
    $("#scan-out").innerHTML = `<div class="muted">${scan.syms.length * scan.ivs.length}개 조합 백테스트 중…</div>`;
    try {
      scanRows = (await api("/api/strategy/scan", { method: "POST", body: { ...btBody(state.spec), symbols: scan.syms, intervals: scan.ivs } })).rows;
    } catch (err) { $("#scan-out").innerHTML = ""; throw err; }
    renderScan();
  });
  $("#scan-out").onclick = (e) => {
    const b = e.target.closest("[data-scan]");
    if (!b) return;
    const r = scanRows[+b.dataset.i];
    busy(b, async () => {
      if (b.dataset.scan === "bot") return startBot({ ...state.spec, symbol: r.symbol, interval: r.interval });
      if (!(await setTarget(r.symbol, r.interval, "스캔에서 선택"))) return;
      if (b.dataset.scan === "improve") await runImprove();
      else $("#bt-stats").scrollIntoView({ behavior: "smooth", block: "center" });
    });
  };
  $("#scan-top").onclick = (e) => busy(e.target, async () => {
    const top = scanRows.filter((r) => !r.error && r.metrics.trades > 0 && r.metrics.total_return_pct > 0).slice(0, 3);
    if (!top.length) return toast("수익이 난 조합이 없습니다");
    for (const r of top) await startBot({ ...state.spec, symbol: r.symbol, interval: r.interval });
  });
  $("#bot-list").onclick = (e) => {
    const c = e.target.dataset.chart;
    if (c) { const [s, iv] = c.split("|"); showOnChart(s, iv); return; }
    const imp = e.target.dataset.improve;
    if (imp) return busy(e.target, async () => {
      const rep = await api(`/api/paper/bots/${imp}/improve`, { method: "POST" });
      toast(rep?.applied ? "봇 전략을 개선했습니다" : "검증을 통과한 개선이 없어 그대로 둡니다", rep?.changes?.join(" / ") || "");
      if (rep) renderImprove(rep, false);
      loadBots();
    });
    const b = e.target.closest("[data-bot]");
    if (!b || (b.dataset.a === "delete" && !confirm("봇을 삭제할까요?"))) return;
    busy(b, async () => { await api(`/api/paper/bots/${b.dataset.bot}/${b.dataset.a}`, { method: "POST" }); loadBots(); });
  };
  $("#bot-list").onchange = (e) => {
    const id = e.target.dataset.auto || e.target.dataset.every;
    if (!id) return;
    const body = e.target.dataset.auto ? { auto_improve: e.target.checked } : { improve_every: +e.target.value };
    api(`/api/paper/bots/${id}/config`, { method: "POST", body }).then(() => toast(e.target.dataset.auto ? (e.target.checked ? "자동 개선 켬" : "자동 개선 끔") : "개선 주기 변경")).catch((err) => toast("오류", err.message, "err"));
  };
  loadBots(); setInterval(loadBots, 15_000);
}
