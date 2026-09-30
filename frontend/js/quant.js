// 퀀트: 순환매(RRG) · 시그널 스캐너 · 리스크(상관·VaR·몬테카를로·민감도·포지션 크기)
import { $, $$, IV_LABEL, api, busy, cls, css, esc, fmt, makeChart, mdhm, on, pct, px, state, toast } from "./core.js";
import { showOnChart } from "./trade.js";

const LC = LightweightCharts;
const base = (s) => s.replace(/USDT$/, "");
const TIER_COLOR = { btc: "#3987e5", eth: "#d95926", large: "#199e70", mid: "#c98500", meme: "#d55181" };   // 검증된 범주 팔레트 순서
const TIER_NAME = { btc: "비트코인", eth: "이더리움", large: "대형 알트", mid: "중소형 알트", meme: "밈코인" };
const QUAD_CLS = { leading: "up", weakening: "accent", lagging: "down", improving: "info" };

// ---------------------------------------------------------------- 툴팁
const tip = {
  show(e, html) { const t = $("#q-tip"); t.innerHTML = html; t.hidden = false; this.move(e); },
  move(e) { const t = $("#q-tip"); t.style.left = `${Math.min(innerWidth - t.offsetWidth - 8, e.clientX + 14)}px`; t.style.top = `${Math.min(innerHeight - t.offsetHeight - 8, e.clientY + 14)}px`; },
  hide() { $("#q-tip").hidden = true; },
};
function bindTips(root) {
  root.onmousemove = (e) => { const el = e.target.closest("[data-tip]"); if (el) tip.show(e, el.dataset.tip); else tip.hide(); };
  root.onmouseleave = () => tip.hide();
}

// 두 색 사이 선형 보간 (중간 = 회색) — 발산형 색
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
function diverge(v, neg = "#3987e5", pos = "#e66767", mid = "#383835") {
  const t = Math.max(-1, Math.min(1, v)), a = hex(mid), b = hex(t >= 0 ? pos : neg), k = Math.abs(t);
  return `rgb(${a.map((x, i) => Math.round(x + (b[i] - x) * k)).join(",")})`;
}

// ================================================================ 순환매
let rot = null;
function universe() { return $("#rot-univ").value === "watch" ? state.watch.join(",") : ""; }

async function runRotation() {
  const q = new URLSearchParams({ interval: $("#rot-iv").value, bench: $("#rot-bench").value, lookback: $("#rot-lb").value });
  if (universe()) q.set("symbols_csv", universe());
  rot = await api(`/api/rotation/rrg?${q}`);
  renderRRG(rot); renderPhase(rot); renderRank(rot);
  $("#q-meta").textContent = `${IV_LABEL[rot.interval]} · ${rot.rows.length}개 코인${rot.data_source === "synthetic" ? " · 가상 데이터" : ""}`;
}

function renderRRG(r) {
  const W = 620, H = 460, P = { l: 44, r: 16, t: 14, b: 34 };
  const all = r.rows.flatMap((x) => x.tail);
  const span = (k) => { const v = all.map((p) => p[k]); const d = Math.max(...v.map((x) => Math.abs(x - 100)), 1) * 1.12; return [100 - d, 100 + d]; };
  const [x0, x1] = span("ratio"), [y0, y1] = span("mom");
  const X = (v) => P.l + (v - x0) / (x1 - x0) * (W - P.l - P.r), Y = (v) => H - P.b - (v - y0) / (y1 - y0) * (H - P.t - P.b);
  const cx = X(100), cy = Y(100);
  const quad = (x, y, w, h, fill) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill}"/>`;
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="상대강도 회전 그래프">
    ${quad(cx, P.t, W - P.r - cx, cy - P.t, "rgba(34,176,125,.07)")}${quad(cx, cy, W - P.r - cx, H - P.b - cy, "rgba(245,165,36,.06)")}
    ${quad(P.l, cy, cx - P.l, H - P.b - cy, "rgba(229,72,77,.07)")}${quad(P.l, P.t, cx - P.l, cy - P.t, "rgba(57,135,229,.07)")}
    <line x1="${cx}" x2="${cx}" y1="${P.t}" y2="${H - P.b}" stroke="var(--line-2)"/><line x1="${P.l}" x2="${W - P.r}" y1="${cy}" y2="${cy}" stroke="var(--line-2)"/>
    <text class="ql" x="${W - P.r - 6}" y="${P.t + 14}" text-anchor="end">주도</text><text class="ql" x="${W - P.r - 6}" y="${H - P.b - 6}" text-anchor="end">약화</text>
    <text class="ql" x="${P.l + 6}" y="${H - P.b - 6}">소외</text><text class="ql" x="${P.l + 6}" y="${P.t + 14}">개선</text>
    <text x="${(W + P.l) / 2}" y="${H - 6}" text-anchor="middle">상대강도 수준 (RS-Ratio) →</text>
    <text x="12" y="${(H - P.b + P.t) / 2}" text-anchor="middle" transform="rotate(-90 12 ${(H - P.b + P.t) / 2})">상대강도 변화 (RS-Momentum) →</text>`;
  const placed = [];
  const labelY = (x, y) => {   // 이미 놓인 이름표와 겹치면 위아래로 비켜 놓는다
    for (const dy of [0, -12, 12, -24, 24, -36, 36]) {
      const ty = y - 6 + dy;
      if (!placed.some((p) => Math.abs(p.x - x) < 46 && Math.abs(p.y - ty) < 11)) { placed.push({ x, y: ty }); return ty; }
    }
    return y - 6;
  };
  for (const row of r.rows) {
    const col = TIER_COLOR[row.tier], pts = row.tail.map((p) => `${X(p.ratio).toFixed(1)},${Y(p.mom).toFixed(1)}`).join(" "), h = row.tail.at(-1);
    const t = `<b>${base(row.symbol)}</b> · ${esc(row.tier_name)}<br>구역 <b>${row.quadrant_name}</b><br>RS-Ratio ${fmt(row.ratio, 2)} · RS-Mom ${fmt(row.mom, 2)}<br>${r.lookback}봉 수익률 ${row.ret_pct ?? "–"}% · 기준 대비 ${row.rel_pct ?? "–"}%p`;
    svg += `<polyline points="${pts}" fill="none" stroke="${col}" stroke-opacity=".45" stroke-width="2"/>
      <circle cx="${X(h.ratio)}" cy="${Y(h.mom)}" r="5" fill="${col}" stroke="var(--panel)" stroke-width="2" data-tip="${esc(t)}" style="cursor:pointer" data-sym="${row.symbol}"/>
      <circle cx="${X(h.ratio)}" cy="${Y(h.mom)}" r="12" fill="transparent" data-tip="${esc(t)}" data-sym="${row.symbol}" style="cursor:pointer"/>
      <text class="lbl" x="${X(h.ratio) + 7}" y="${labelY(X(h.ratio) + 7, Y(h.mom))}">${base(row.symbol)}</text>`;
  }
  $("#rrg").innerHTML = svg + "</svg>";
  bindTips($("#rrg"));
  $("#rrg").onclick = (e) => { const s = e.target.closest("[data-sym]")?.dataset.sym; if (s) showOnChart(s, r.interval); };
  const tiers = [...new Set(r.rows.map((x) => x.tier))];
  $("#rrg-legend").innerHTML = ["btc", "eth", "large", "mid", "meme"].filter((t) => tiers.includes(t)).map((t) => `<span><i style="background:${TIER_COLOR[t]}"></i>${TIER_NAME[t]}</span>`).join("");
}

function renderPhase(r) {
  const p = r.phase, tr = Object.entries(p.tier_ret_pct), mx = Math.max(...tr.map(([, v]) => Math.abs(v)), 1);
  $("#rot-phase").innerHTML = `<div style="font-size:14px;font-weight:600;margin-bottom:8px" class="${p.key === "off" ? "down" : "accent"}">${esc(p.text)}</div>
    <div class="sub" style="padding-left:0">그룹별 ${r.lookback}봉 수익률</div>
    ${tr.map(([k, v]) => `<div class="hbar"><span class="dim">${esc(k)}</span><div class="track"><b></b>
      <i style="${v >= 0 ? `left:50%;width:${v / mx * 50}%` : `right:50%;width:${-v / mx * 50}%`};background:${v >= 0 ? "var(--up)" : "var(--down)"}"></i></div>
      <span class="${cls(v)}" style="text-align:right">${v > 0 ? "+" : ""}${fmt(v, 2)}%</span></div>`).join("")}
    <div class="kv" style="display:grid;grid-template-columns:auto 1fr;gap:3px 10px;margin-top:8px">
      <span class="muted">BTC 보다 강한 코인</span><span>${p.breadth_beat_btc_pct ?? "–"}%</span>
      <span class="muted">EMA20 위에 있는 코인</span><span>${p.breadth_above_ema20_pct ?? "–"}%</span>
      <span class="muted">ETH/BTC 변화</span><span class="${cls(p.ethbtc_change_pct)}">${p.ethbtc_change_pct == null ? "–" : (p.ethbtc_change_pct > 0 ? "+" : "") + p.ethbtc_change_pct + "%"}</span></div>`;
}

function renderRank(r) {
  $("#rot-rank").innerHTML = `<tr><th>코인</th><th>그룹</th><th>구역</th><th>${r.lookback}봉</th><th>기준 대비</th><th></th></tr>` +
    r.rows.map((x) => `<tr><td><b>${base(x.symbol)}</b></td><td class="dim">${esc(x.tier_name)}</td><td class="${QUAD_CLS[x.quadrant]}">${x.quadrant_name}</td>
      <td class="${cls(x.ret_pct)}">${x.ret_pct == null ? "–" : pct(x.ret_pct)}</td><td class="${cls(x.rel_pct)}">${x.rel_pct == null ? "–" : (x.rel_pct > 0 ? "+" : "") + fmt(x.rel_pct, 2) + "%p"}</td>
      <td><button class="sm" data-chart="${x.symbol}">차트</button></td></tr>`).join("");
}

let rbChart = null;
async function runRotBacktest() {
  const body = { interval: $("#rot-iv").value, lookback: +$("#rb-lb").value, top: +$("#rb-top").value, rebalance: +$("#rb-reb").value,
    mode: $("#rb-mode").value, score: $("#rb-score").value, abs_filter: $("#rb-abs").checked, bars: +$("#rb-bars").value };
  if (universe()) body.symbols = state.watch;
  const r = await api("/api/rotation/backtest", { method: "POST", body });
  const row = (l, s) => `<tr><td>${l}</td><td class="${cls(s.return_pct)}">${pct(s.return_pct)}</td><td class="down">-${fmt(s.max_drawdown_pct, 1)}%</td><td>${s.sharpe ?? "–"}</td></tr>`;
  $("#rb-out").innerHTML = `<div class="cols-2" style="align-items:start"><div>
      <table><tr><th></th><th>수익률</th><th>최대 낙폭</th><th>샤프</th></tr>${row("<b>순환매 전략</b>", r.strategy)}${row("BTC 보유", r.btc)}${row("동일 비중 보유", r.equal_weight)}</table>
      <div class="help" style="margin-top:4px">${r.rebalances}번 교체 · 수수료 ${r.params.fee_pct}% 반영${r.data_source === "synthetic" ? " · <span class='accent'>가상 데이터</span>" : ""}</div></div>
    <div><div class="sub" style="padding-left:0">지금 기준 ${r.params.mode === "long_short" ? "매수 · 숏" : "매수"} 후보</div>
      <div>${r.now.long.map((s) => `<span class="chk on up" data-chart="${s}">${base(s)} 롱</span>`).join(" ") || '<span class="muted">모멘텀이 모두 음수 → 현금</span>'}
        ${r.now.short.map((s) => `<span class="chk on down" data-chart="${s}">${base(s)} 숏</span>`).join(" ")}</div>
      <div class="sub" style="padding-left:0;margin-top:8px">최근 교체 기록</div>
      <div style="max-height:120px;overflow:auto">${r.history.slice().reverse().slice(0, 12).map((h) => `<div class="dim" style="font-size:11px">${mdhm(h.time)} · ${h.long.map(base).join(", ") || "현금"}${h.short.length ? " / 숏 " + h.short.map(base).join(", ") : ""}</div>`).join("")}</div></div></div>
    <div class="legend-row" style="margin-top:8px"><span><i style="background:var(--s1)"></i>순환매 전략</span><span><i style="background:var(--s2)"></i>BTC 보유</span><span><i style="background:var(--s3)"></i>동일 비중 보유</span></div>`;
  $("#rb-chart").hidden = false;
  rbChart?.remove();
  rbChart = makeChart($("#rb-chart"));
  [["curve", "--s1", "전략"], ["btc_curve", "--s2", "BTC"], ["ew_curve", "--s3", "동일비중"]].forEach(([k, c, t]) => {
    const s = rbChart.addSeries(LC.LineSeries, { color: css(c), lineWidth: 2, title: t, priceLineVisible: false });
    s.setData(r[k]);
  });
  rbChart.timeScale().fitContent();
}

// ================================================================ 시그널 스캐너
let scan = null, sigs = [];
const STRENGTH = (n) => "●".repeat(n) + "○".repeat(3 - n);
async function loadScanner() {
  scan = await api("/api/scanner");
  renderScanCfg(); renderBoard();
  const d = await api("/api/scanner/signals?limit=150");
  sigs = d.items; renderSignals();
}
function renderScanCfg() {
  const c = scan.config;
  $("#sc-on").checked = c.enabled;
  $("#sc-syms").innerHTML = c.symbols.map((s) => `<span class="chk on" data-rm="${s}" title="눌러서 빼기">${base(s)} ✕</span>`).join("") || '<span class="muted">코인을 추가하세요</span>';
  $("#sc-ivs").innerHTML = ["5m", "15m", "30m", "1h", "4h", "1d", "1w"].map((k) => `<span class="chk ${c.intervals.includes(k) ? "on" : ""}" data-iv="${k}">${IV_LABEL[k]}</span>`).join("");
  $("#sc-types").innerHTML = Object.entries(scan.labels).map(([k, l]) => `<span class="chk ${c.signals[k] ? "on" : ""}" data-type="${k}">${esc(l)}</span>`).join("");
  $("#sc-last").textContent = scan.last_run ? `마지막 스캔 ${mdhm(scan.last_run)}${Object.keys(scan.errors).length ? ` · 오류 ${Object.keys(scan.errors).length}` : ""}` : "아직 스캔 전";
}
async function saveScan(patch) {
  scan.config = await api("/api/scanner/config", { method: "POST", body: patch });
  renderScanCfg();
}
function renderSignals() {
  const min = +$("#sc-filter").value;
  const xs = sigs.filter((s) => s.strength >= min);
  $("#sc-list").innerHTML = xs.length ? xs.map((s) => `<div class="sig">
      <div><div class="d ${s.dir === "long" ? "up" : s.dir === "short" ? "down" : "accent"}">${s.dir === "long" ? "▲ 롱" : s.dir === "short" ? "▼ 숏" : "● 중립"}</div><div class="st" title="강도">${STRENGTH(s.strength)}</div></div>
      <div><div><b>${base(s.symbol)}</b> <span class="muted">${IV_LABEL[s.interval]}</span> · ${esc(s.label)}${s.confluence ? ` <span class="accent">(${s.confluence}개 겹침)</span>` : ""}</div>
        <div class="dim">${esc(s.text)}</div><div class="muted" style="font-size:11px">${mdhm(s.bar_time)} 봉 · ${px(s.price)}</div></div>
      <button class="sm" data-chart="${s.symbol}|${s.interval}">차트</button></div>`).join("")
    : `<div class="empty">아직 신호가 없습니다. 조건이 맞는 봉이 끝나면 여기에 쌓입니다.</div>`;
}
function renderBoard() {
  const c = scan.config, rows = scan.board, by = Object.fromEntries(rows.map((r) => [`${r.symbol}:${r.interval}`, r]));
  const ST = { long: "up", short: "down", range: "accent" };
  $("#sc-board").innerHTML = `<table class="board"><tr><th>코인</th><th>가격</th>${c.intervals.map((i) => `<th>${IV_LABEL[i]}</th>`).join("")}</tr>
    ${c.symbols.map((s) => { const any = c.intervals.map((i) => by[`${s}:${i}`]).find(Boolean);
      return `<tr><td><b>${base(s)}</b></td><td>${any ? px(any.price) : "–"}</td>${c.intervals.map((i) => { const r = by[`${s}:${i}`];
        return r ? `<td class="bcell" data-chart="${s}|${i}" data-tip="${esc(`<b>${base(s)} ${IV_LABEL[i]}</b><br>${r.label} · 점수 ${r.score}<br>RSI ${r.rsi} · ADX ${r.adx}<br>이번 봉 ${r.change_pct}%`)}">
          <span class="${ST[r.state]}">${r.label}</span><div class="muted" style="font-size:10.5px">RSI ${Math.round(r.rsi)}</div></td>` : "<td class='muted'>–</td>"; }).join("")}</tr>`; }).join("")}</table>`;
  bindTips($("#sc-board"));
}

// ================================================================ 리스크
async function runMatrix() {
  const r = await api("/api/risk/matrix", { method: "POST", body: { symbols: state.watch, interval: $("#rk-iv").value, bars: 180 } });
  const n = r.symbols.length;
  $("#rk-matrix").innerHTML = `<div style="overflow:auto"><table class="heat"><tr><th></th>${r.symbols.map((s) => `<th>${base(s)}</th>`).join("")}</tr>
    ${r.symbols.map((a, i) => `<tr><th style="text-align:right">${base(a)}</th>${r.corr[i].map((v, j) => `<td style="background:${v == null ? "var(--panel-2)" : i === j ? "var(--panel-2)" : diverge(v)}"
      data-tip="${esc(`${base(a)} ↔ ${base(r.symbols[j])}<br>상관 ${v ?? "–"}`)}">${v == null ? "–" : i === j ? "" : fmt(v, 2)}</td>`).join("")}</tr>`).join("")}</table></div>
    <div class="legend-row"><span><i style="background:#3987e5"></i>반대로 움직임 (−1)</span><span><i style="background:#383835"></i>무관 (0)</span><span><i style="background:#e66767"></i>같이 움직임 (+1)</span>
      <span class="muted">평균 |상관| ${r.avg_abs_corr ?? "–"}</span></div>
    <div class="help">${esc(r.note)}</div>
    <table style="margin-top:8px"><tr><th>코인</th><th>연 변동성</th><th>BTC 베타</th><th>VaR 95%</th><th>CVaR 95%</th><th>최대 낙폭</th><th>샤프</th></tr>
      ${r.stats.map((s) => `<tr><td><b>${base(s.symbol)}</b></td><td>${s.vol_ann_pct}%</td><td>${s.beta_btc ?? "–"}</td><td class="down">-${s.var95_pct}%</td>
        <td class="down">${s.cvar95_pct == null ? "–" : "-" + s.cvar95_pct + "%"}</td><td class="down">-${s.max_dd_pct}%</td><td>${s.sharpe ?? "–"}</td></tr>`).join("")}</table>
    <div class="help">VaR 95% = ${IV_LABEL[r.interval]} 한 봉에 20번 중 1번은 이보다 더 떨어질 수 있다는 뜻. CVaR = 그런 나쁜 날의 평균 손실.</div>`;
  bindTips($("#rk-matrix"));
  state.riskStats = Object.fromEntries(r.stats.map((s) => [s.symbol, s]));
  renderSizer();
}

async function runPortfolio() {
  const r = await api(`/api/risk/portfolio?shock_pct=${+$("#pf-shock").value || -10}`);
  if (!r.positions) { $("#pf-out").innerHTML = `<div class="empty">열린 포지션이 없습니다.</div>`; return; }
  $("#pf-out").innerHTML = `<table><tr><th>누구</th><th>코인</th><th>방향</th><th>명목 금액</th></tr>${r.items.map((p) => `<tr><td class="dim">${esc(p.who)}</td><td>${base(p.symbol)}</td>
      <td class="${p.side === "long" ? "up" : "down"}">${p.side === "long" ? "롱" : "숏"}</td><td>${fmt(p.notional, 0)}</td></tr>`).join("")}</table>
    <div class="kv" style="display:grid;grid-template-columns:auto 1fr;gap:3px 10px;margin-top:8px">
      <span class="muted">총 노출 / 순 노출</span><span>${fmt(r.gross, 0)} / ${fmt(r.net, 0)} USDT</span>
      <span class="muted">하루 VaR 95%</span><span class="down">-${fmt(r.var95, 0)} USDT</span>
      <span class="muted">하루 VaR 99%</span><span class="down">-${fmt(r.var99, 0)} USDT</span>
      <span class="muted">CVaR 95%</span><span class="down">${r.cvar95 == null ? "–" : "-" + fmt(r.cvar95, 0) + " USDT"}</span>
      <span class="muted">BTC ${r.stress_shock_pct}% 일 때</span><span class="${cls(r.stress_pnl)}">${r.stress_pnl > 0 ? "+" : ""}${fmt(r.stress_pnl, 0)} USDT</span></div>
    <div class="help">최근 ${r.samples}일의 실제 가격 변화를 지금 포지션에 그대로 적용해 본 결과입니다 (역사적 시뮬레이션). 스트레스는 코인별 BTC 베타로 계산합니다.</div>`;
}

async function runMonteCarlo() {
  const b = state.lastBacktest;
  if (!b) return toast("먼저 '전략 · 백테스트'에서 백테스트를 실행하세요");
  const r = await api("/api/risk/montecarlo", { method: "POST", body: { pnls: b.trades.map((t) => t.pnl), initial_equity: b.initial } });
  const h = r.histogram, mx = Math.max(...h.counts), W = 520, H = 150, bw = W / h.counts.length;
  const x = (v) => (v - h.from) / (h.step * h.counts.length) * W;
  const bars = h.counts.map((n, i) => { const lo = h.from + i * h.step; return `<rect x="${i * bw + 1}" y="${H - n / mx * (H - 10)}" width="${bw - 2}" height="${n / mx * (H - 10)}" rx="2"
    fill="${lo + h.step <= 0 ? "var(--down)" : "var(--s1)"}" data-tip="${esc(`${fmt(lo, 1)}% ~ ${fmt(lo + h.step, 1)}%<br>${n}번 / ${r.sims}번`)}"/>`; }).join("");
  const mark = (v, l) => `<line x1="${x(v)}" x2="${x(v)}" y1="0" y2="${H}" stroke="var(--text-2)" stroke-dasharray="3 3"/><text x="${x(v) + 3}" y="10" style="font-size:10px;fill:var(--text-2)">${l}</text>`;
  const q = r.return_pct, d = r.max_dd_pct;
  $("#mc-out").innerHTML = `<div class="dim" style="margin-bottom:6px">${esc(b.name)} · ${base(b.symbol)} ${IV_LABEL[b.interval] || b.interval} · 거래 ${r.trades}건을 ${r.sims}번 재조합</div>
    <svg viewBox="0 0 ${W} ${H + 16}" style="width:100%;height:auto" role="img" aria-label="최종 수익률 분포">${bars}${mark(q.p5, "5%")}${mark(q.p50, "중간")}${mark(q.p95, "95%")}
      <text x="0" y="${H + 13}" style="font-size:10px;fill:var(--muted)">${fmt(h.from, 0)}%</text><text x="${W}" y="${H + 13}" text-anchor="end" style="font-size:10px;fill:var(--muted)">${fmt(h.from + h.step * h.counts.length, 0)}%</text></svg>
    <table style="margin-top:6px"><tr><th></th><th>나쁜 경우 5%</th><th>25%</th><th>중간</th><th>75%</th><th>좋은 경우 95%</th></tr>
      <tr><td>최종 수익률</td>${["p5", "p25", "p50", "p75", "p95"].map((k) => `<td class="${cls(q[k])}">${pct(q[k])}</td>`).join("")}</tr>
      <tr><td>최대 낙폭</td>${["p5", "p25", "p50", "p75", "p95"].map((k) => `<td class="down">-${fmt(d[k], 1)}%</td>`).join("")}</tr></table>
    <div class="kv" style="display:grid;grid-template-columns:auto 1fr;gap:3px 10px;margin-top:8px">
      <span class="muted">손실로 끝날 확률</span><span>${r.prob_loss_pct}%</span><span class="muted">낙폭 30% 이상 확률</span><span>${r.prob_dd30_pct}%</span>
      <span class="muted">낙폭 50% 이상 확률</span><span class="${r.prob_dd50_pct > 5 ? "down" : ""}">${r.prob_dd50_pct}%</span></div>
    <div class="help">백테스트 결과 하나는 '운 좋은 한 번'일 수 있습니다. 나쁜 경우 5% 칸도 감당할 수 있는지 보세요.</div>`;
  bindTips($("#mc-out"));
}

// 파라미터 민감도
let swParams = [];
async function loadSweepForm() {
  if (!state.spec) return;
  swParams = await api("/api/risk/params", { method: "POST", body: state.spec });
  const opt = (sel) => swParams.map((p, i) => `<option value="${i}" ${i === sel ? "selected" : ""}>${esc(p.label)} (지금 ${p.value})</option>`).join("");
  const rng = (v) => [Math.max(1, +(v * 0.5).toFixed(2)), +(v * 1.5).toFixed(2)];
  const r1 = rng(swParams[0]?.value || 10), r2 = rng(swParams[swParams.findIndex((p) => p.path.startsWith("risk")) >= 0 ? swParams.findIndex((p) => p.path.startsWith("risk")) : 1]?.value || 2);
  const i2 = Math.max(0, swParams.findIndex((p) => p.path.startsWith("risk")));
  $("#sw-form").innerHTML = swParams.length ? `<span class="dim">${esc(state.spec.name)} · ${base(state.spec.symbol)} ${IV_LABEL[state.spec.interval] || ""}</span>
    <label class="f">가로<select id="sw-p1">${opt(0)}</select></label><label class="f">최소<input id="sw-a1" type="number" step="any" value="${r1[0]}" style="width:60px"></label><label class="f">최대<input id="sw-b1" type="number" step="any" value="${r1[1]}" style="width:60px"></label>
    <label class="f">세로<select id="sw-p2">${opt(i2)}</select></label><label class="f">최소<input id="sw-a2" type="number" step="any" value="${r2[0]}" style="width:60px"></label><label class="f">최대<input id="sw-b2" type="number" step="any" value="${r2[1]}" style="width:60px"></label>
    <label class="f">칸 수<input id="sw-n" type="number" value="6" min="2" max="9" style="width:50px"></label>`
    : `<span class="muted">바꿀 수 있는 숫자 파라미터가 없습니다.</span>`;
}
async function runSweep() {
  if (!swParams.length) await loadSweepForm();
  if (!swParams.length) return;
  const n = Math.max(2, Math.min(9, +$("#sw-n").value || 6)), steps = (a, b) => Array.from({ length: n }, (_, k) => +(a + (b - a) * k / (n - 1)).toFixed(4));
  const p1 = swParams[+$("#sw-p1").value], p2 = swParams[+$("#sw-p2").value];
  const intish = (p) => Number.isInteger(p.value);
  const v1 = [...new Set(steps(+$("#sw-a1").value, +$("#sw-b1").value).map((v) => intish(p1) ? Math.round(v) : v))];
  const v2 = p2.path === p1.path ? null : [...new Set(steps(+$("#sw-a2").value, +$("#sw-b2").value).map((v) => intish(p2) ? Math.round(v) : v))];
  const r = await api("/api/risk/sweep", { method: "POST", body: { spec: state.spec, p1: p1.path, v1, p2: v2 ? p2.path : null, v2, bars: 1500 } });
  const cells = Object.fromEntries(r.cells.map((c) => [`${c.a}|${c.b}`, c]));
  const mx = Math.max(...r.cells.filter((c) => c.test).map((c) => Math.abs(c.test.net_pnl)), 1);
  const cols = r.v2.length ? r.v2 : [null];
  $("#sw-out").innerHTML = `<div style="overflow:auto"><table class="heat sw-grid"><tr><th>${esc(p1.label)} ↓ / ${r.v2.length ? esc(p2.label) + " →" : ""}</th>${cols.map((b) => `<th>${b ?? ""}</th>`).join("")}</tr>
    ${r.v1.map((a) => `<tr><th style="text-align:right">${a}</th>${cols.map((b) => { const c = cells[`${a}|${b}`]; if (!c || c.error) return `<td class="muted" data-tip="${esc(c?.error || "")}">×</td>`;
      const cur = a === p1.value && (b == null || b === p2.value);
      return `<td style="background:${diverge(c.test.net_pnl / mx, "#e5484d", "#22b07d")};${cur ? "outline:2px solid var(--accent);outline-offset:-2px" : ""}"
        data-tip="${esc(`${p1.label} ${a}${b != null ? ` · ${p2.label} ${b}` : ""}<br>검증 구간 손익 ${fmt(c.test.net_pnl, 0)} (${c.test.trades}건)<br>학습 구간 손익 ${fmt(c.train.net_pnl, 0)} (${c.train.trades}건)<br>전체 수익률 ${c.return_pct}% · 낙폭 ${c.max_dd_pct}%`)}">${fmt(c.test.net_pnl, 0)}</td>`; }).join("")}</tr>`).join("")}</table></div>
    <div class="legend-row"><span><i style="background:#e5484d"></i>검증 구간 손실</span><span><i style="background:#383835"></i>0</span><span><i style="background:#22b07d"></i>검증 구간 이익</span><span><i style="background:transparent;outline:2px solid var(--accent)"></i>지금 값</span></div>
    <div class="help">칸 숫자 = 학습에 안 쓴 최근 30% 구간의 손익. 이익 칸 비율 <b>${r.robust_share_pct ?? "–"}%</b>. ${esc(r.note)}</div>`;
  bindTips($("#sw-out"));
}

// 포지션 크기 계산기
function renderSizer() {
  const b = state.lastBacktest?.metrics, st = state.riskStats?.[state.symbol];
  const win = b?.win_rate_pct, pf = b?.profit_factor;
  let kelly = null;
  if (win != null && pf && b.trades > 0) { const p = win / 100, R = pf * (1 - p) / p; kelly = R > 0 ? (p - (1 - p) / R) * 100 : null; }
  const el = $("#sz");
  const v = (id, d) => el.querySelector(`#${id}`)?.value ?? d;
  el.innerHTML = `<div class="row" style="flex-wrap:wrap;gap:6px">
      <label class="f">자본<input id="sz-eq" type="number" value="${v("sz-eq", 10000)}" style="width:80px"></label>
      <label class="f">진입가<input id="sz-en" type="number" step="any" value="${v("sz-en", state.tickers[state.symbol]?.price ? +(+state.tickers[state.symbol].price).toPrecision(7) : "")}" style="width:90px"></label>
      <label class="f">손절가<input id="sz-sl" type="number" step="any" value="${v("sz-sl", "")}" style="width:90px"></label>
      <label class="f">한 번에 잃을 돈 %<input id="sz-r" type="number" step="0.1" value="${v("sz-r", 1)}" style="width:60px"></label>
      <label class="f">목표 연 변동성 %<input id="sz-tv" type="number" value="${v("sz-tv", 40)}" style="width:60px"></label></div>
    <div id="sz-out" style="margin-top:8px"></div>`;
  const calc = () => {
    const eq = +v("sz-eq"), en = +v("sz-en"), sl = +v("sz-sl"), r = +v("sz-r") / 100, tv = +v("sz-tv");
    const riskAmt = eq * r, dist = en && sl ? Math.abs(en - sl) / en : null, notional = dist ? riskAmt / dist : null;
    $("#sz-out").innerHTML = `<div class="kv" style="display:grid;grid-template-columns:auto 1fr;gap:3px 10px">
      <span class="muted">손절 시 손실</span><span>${fmt(riskAmt, 2)} USDT</span>
      <span class="muted">손절 거리</span><span>${dist ? fmt(dist * 100, 2) + "%" : "–"}</span>
      <span class="muted">포지션 크기 (명목)</span><span><b>${notional ? fmt(notional, 0) + " USDT" : "진입가·손절가를 넣으세요"}</b>${notional && en ? ` · ${fmt(notional / en, 4)} ${base(state.symbol)}` : ""}</span>
      <span class="muted">필요 레버리지</span><span>${notional ? fmt(Math.max(1, notional / eq), 1) + "배 (자본 전부를 증거금으로 쓸 때)" : "–"}</span>
      <span class="muted">켈리 비중</span><span>${kelly == null ? "백테스트 후 표시" : `${fmt(kelly, 1)}% → 반 켈리 ${fmt(kelly / 2, 1)}% 권장`}</span>
      <span class="muted">변동성 목표 레버리지</span><span>${st ? `${base(state.symbol)} 연 변동성 ${st.vol_ann_pct}% → ${fmt(tv / st.vol_ann_pct, 2)}배` : "'상관관계' 계산 후 표시"}</span></div>
      <div class="help">정해진 금액만 잃도록 크기를 거꾸로 계산합니다. 켈리는 최근 백테스트의 승률·손익비 기준이며, 실제로는 절반 이하를 권장합니다.</div>`;
  };
  el.oninput = calc; calc();
}

// ================================================================ 기관식 포트폴리오
const M_COLOR = { equal: "#3987e5", inv_vol: "#d95926", risk_parity: "#199e70", min_var: "#c98500", max_sharpe: "#d55181" };   // 검증된 범주 순서
let opt = null;
async function runOptimize() {
  const typed = $("#po-syms").value.split(/[,\s]+/).filter(Boolean);
  opt = await api("/api/portfolio/optimize", { method: "POST", body: { symbols: typed.length ? typed : state.watch, interval: $("#po-iv").value,
    bars: +$("#po-bars").value, max_weight: (+$("#po-cap").value || 40) / 100 } });
  const R = opt.results, st = (x, k, unit = "") => x?.[k] == null ? "–" : `${x[k]}${unit}`;
  // 효율적 투자선 산점도
  const W = 720, H = 440, P = { l: 52, r: 90, t: 14, b: 40 }, pts = [...opt.cloud, ...R.map((r) => r.point)];
  const [vx0, vx1] = [Math.min(...pts.map((p) => p.vol)) * 0.95, Math.max(...pts.map((p) => p.vol)) * 1.03];
  const [ry0, ry1] = [Math.min(...pts.map((p) => p.ret)), Math.max(...pts.map((p) => p.ret))].map((v, i) => v + (i ? 1 : -1) * Math.abs(v) * 0.08 + (i ? 0.5 : -0.5));
  const X = (v) => P.l + (v - vx0) / (vx1 - vx0) * (W - P.l - P.r), Y = (v) => H - P.b - (v - ry0) / (ry1 - ry0) * (H - P.t - P.b);
  const placed = [];
  const ly = (x, y) => { for (const dy of [0, -13, 13, -26, 26, -39, 39]) { const t = y + 4 + dy; if (!placed.some((q) => Math.abs(q.x - x) < 90 && Math.abs(q.y - t) < 12)) { placed.push({ x, y: t }); return t; } } return y + 4; };
  const tk = (v) => fmt(v, 0);
  const svg = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:640px;height:auto" role="img" aria-label="효율적 투자선">
    <line x1="${P.l}" x2="${W - P.r}" y1="${H - P.b}" y2="${H - P.b}" stroke="var(--line-2)"/><line x1="${P.l}" x2="${P.l}" y1="${P.t}" y2="${H - P.b}" stroke="var(--line-2)"/>
    <text x="${P.l}" y="${H - P.b + 14}" style="font-size:11px;fill:var(--muted)">${tk(vx0)}%</text><text x="${W - P.r}" y="${H - P.b + 14}" text-anchor="end" style="font-size:11px;fill:var(--muted)">${tk(vx1)}%</text>
    <text x="${P.l - 4}" y="${H - P.b}" text-anchor="end" style="font-size:11px;fill:var(--muted)">${tk(ry0)}%</text><text x="${P.l - 4}" y="${P.t + 10}" text-anchor="end" style="font-size:11px;fill:var(--muted)">${tk(ry1)}%</text>
    ${opt.cloud.map((p) => `<circle cx="${X(p.vol).toFixed(1)}" cy="${Y(p.ret).toFixed(1)}" r="1.6" fill="var(--muted)" fill-opacity=".35"/>`).join("")}
    ${R.map((r) => `<circle cx="${X(r.point.vol)}" cy="${Y(r.point.ret)}" r="6" fill="${M_COLOR[r.method]}" stroke="var(--panel)" stroke-width="2"
      data-tip="${esc(`<b>${r.name}</b><br>연 변동성 ${r.point.vol}% · 연 기대수익 ${r.point.ret}% (학습 구간)`)}"/>
      <text x="${X(r.point.vol) + 9}" y="${ly(X(r.point.vol) + 9, Y(r.point.ret))}" style="font-size:12px;fill:var(--text)">${r.name}</text>`).join("")}
    <text x="${(W + P.l - P.r) / 2}" y="${H - 8}" text-anchor="middle" style="font-size:12px;fill:var(--text-2)">연 변동성 % (위험) →</text>
    <text x="14" y="${(H - P.b) / 2}" text-anchor="middle" transform="rotate(-90 14 ${(H - P.b) / 2})" style="font-size:12px;fill:var(--text-2)">연 기대수익 % →</text></svg>`;
  $("#po-out").innerHTML = `<div class="cols-2" style="align-items:start"><div>
      <table><tr><th>방법</th><th>학습 샤프</th><th>검증 수익</th><th>검증 샤프</th><th>검증 낙폭</th><th></th></tr>
        ${R.map((r) => `<tr><td><i style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${M_COLOR[r.method]};margin-right:5px"></i>${r.name}</td>
          <td>${st(r.train, "sharpe")}</td><td class="${cls(r.test.return_pct)}">${pct(r.test.return_pct)}</td><td><b>${st(r.test, "sharpe")}</b></td>
          <td class="down">-${st(r.test, "max_dd_pct", "%")}</td><td><button class="sm" data-stress="${r.method}">스트레스</button></td></tr>`).join("")}</table>
      <div class="sub" style="padding-left:0;margin-top:8px">코인별 비중 <span class="muted">(마우스를 올리면 위험 기여도)</span></div>
      <div style="overflow:auto"><table><tr><th>코인</th>${R.map((r) => `<th>${r.name}</th>`).join("")}</tr>
        ${opt.symbols.map((sym) => `<tr><td><b>${base(sym)}</b></td>${R.map((r) => `<td class="wcell" data-tip="${esc(`${base(sym)} · ${r.name}<br>비중 ${(r.weights[sym] * 100).toFixed(1)}% · 위험 기여 ${(r.risk_contrib[sym] * 100).toFixed(1)}%`)}"><i style="width:${(r.weights[sym] * 100).toFixed(1)}%"></i><span>${(r.weights[sym] * 100).toFixed(1)}%</span></td>`).join("")}</tr>`).join("")}</table></div>
    </div><div>${svg}<div class="legend-row"><span><i style="background:var(--muted)"></i>무작위 배분 ${opt.cloud.length}개</span>${R.map((r) => `<span><i style="background:${M_COLOR[r.method]}"></i>${r.name}</span>`).join("")}</div>
      <div class="help">${esc(opt.note)} 학습 ${opt.train_bars}봉 · 검증 ${opt.test_bars}봉 (${mdhm(opt.test_from)}부터)${opt.data_source === "synthetic" ? " · <span class='accent'>가상 데이터</span>" : ""}</div></div></div>`;
  bindTips($("#po-out"));
}

async function runStress(weights) {
  const r = await api("/api/portfolio/stress", { method: "POST", body: weights ? { weights, equity: 10_000 } : {} });
  $("#st-out").innerHTML = `<div class="muted" style="margin-bottom:6px">${weights ? "배분 결과 (자본 10,000 USDT 가정)" : "지금 모의 포지션"} · 총 노출 ${fmt(r.gross, 0)} USDT</div>
    <table><tr><th>시나리오</th><th>BTC</th><th>예상 손익</th><th>노출 대비</th><th></th></tr>
      ${r.scenarios.map((s) => `<tr data-tip="${esc(`<b>${s.name}</b> (${s.period})<br>` + s.detail.map((d) => `${base(d.symbol)} ${d.ret_pct > 0 ? "+" : ""}${d.ret_pct}%${d.low_pct != null ? ` (구간 최저 ${d.low_pct}%)` : ""}${d.estimated ? " · 추정" : ""}`).join("<br>"))}">
        <td>${esc(s.name)}<div class="muted" style="font-size:10.5px">${esc(s.period)}</div></td><td class="${cls(s.btc_ret_pct)}">${s.btc_ret_pct == null ? "–" : pct(s.btc_ret_pct)}</td>
        <td class="${cls(s.pnl)}"><b>${s.pnl > 0 ? "+" : ""}${fmt(s.pnl, 0)}</b></td><td class="${cls(s.pnl_pct_gross)}">${pct(s.pnl_pct_gross)}</td>
        <td>${s.liquidation.length ? `<span class="down">청산 위험: ${s.liquidation.map(base).join(", ")}</span>` : ""}</td></tr>`).join("")}</table>
    <div class="help">${esc(r.note)} 줄에 마우스를 올리면 코인별 등락을 볼 수 있습니다.</div>`;
  bindTips($("#st-out"));
}

async function runExposure() {
  const r = await api("/api/portfolio/exposure");
  const tile = (k, v, c = "") => `<div class="tile"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`;
  $("#ex-out").innerHTML = `<div class="tiles">${tile("총 노출", fmt(r.gross, 0))}${tile("순 노출", fmt(r.net, 0), cls(r.net))}
      ${tile("BTC 1% 움직일 때", `${r.beta_dollars >= 0 ? "+" : ""}${fmt(r.beta_dollars / 100, 1)}`, cls(r.beta_dollars))}
      ${tile("모멘텀 기울기", r.mom_tilt, cls(r.mom_tilt))}${tile("변동성 기울기", r.vol_tilt)}</div>
    <div class="muted" style="margin:6px 0">그룹별 순노출: ${Object.entries(r.tiers).map(([k, v]) => `${esc(k)} <span class="${cls(v)}">${fmt(v, 0)}</span>`).join(" · ")}</div>
    <div style="overflow:auto"><table><tr><th>코인</th><th>방향</th><th>금액</th><th>BTC 베타</th><th>모멘텀 z</th><th>연 변동성</th><th>거래대금 대비</th><th>정리 일수*</th><th>한 번에 정리 시 슬리피지</th></tr>
      ${r.rows.map((x) => `<tr><td><b>${base(x.symbol)}</b> <span class="muted">${esc(x.who || "")}</span></td><td class="${x.side === "long" ? "up" : "down"}">${x.side === "long" ? "롱" : "숏"}</td>
        <td>${fmt(x.notional, 0)}</td><td>${x.beta}</td><td class="${cls(x.mom_z)}">${x.mom_z}</td><td>${x.vol_ann_pct}%</td>
        <td>${x.pct_adv == null ? "–" : x.pct_adv + "%"}</td><td>${x.days_to_exit_10pct ?? "–"}</td><td>${x.exit_slip_pct == null ? "–" : x.exit_slip_pct + "%"}</td></tr>`).join("")}</table></div>
    <div class="help">${esc(r.note)} *하루 거래대금의 10%씩만 팔 때 걸리는 날 수.</div>`;
}

let tsChart = null;
async function runTearsheet() {
  const src = $("#ts-src").value, b = state.lastBacktest;
  if (src === "bt" && !b) return toast("먼저 '전략 · 백테스트'에서 백테스트를 실행하세요");
  let r;
  try {
    r = await api("/api/portfolio/tearsheet", { method: "POST", body: src === "paper" ? { source: "paper" }
      : { source: "custom", trades: b.trades, equity_curve: b.equity_curve, initial: b.initial } });
  } catch (err) {
    $("#ts-out").innerHTML = `<div class="empty">${esc(err.message)} ${src === "paper" ? "모의 거래를 청산하거나 봇이 거래를 마치면 분석할 수 있습니다. 백테스트 결과로 보려면 위에서 '최근 백테스트'를 고르세요." : ""}</div>`;
    return;
  }
  const s = r.stats, tile = (k, v, c = "") => `<div class="tile"><div class="k">${k}</div><div class="v ${c}">${v ?? "–"}</div></div>`;
  const months = Object.entries(r.monthly), mx = Math.max(1, ...months.flatMap(([, m]) => Object.values(m).map(Math.abs)));
  const bar = (rows, label) => { const m = Math.max(1, ...rows.map((x) => Math.abs(x.pnl)));
    return rows.map((x) => `<div class="hbar" style="grid-template-columns:60px 1fr 70px"><span class="dim">${label(x.key)}</span><div class="track"><b></b>
      <i style="${x.pnl >= 0 ? `left:50%;width:${x.pnl / m * 50}%` : `right:50%;width:${-x.pnl / m * 50}%`};background:${x.pnl >= 0 ? "var(--up)" : "var(--down)"}"
        data-tip="${esc(`${label(x.key)} · ${x.trades}건 · 승률 ${x.win_rate}%<br>손익 ${fmt(x.pnl, 2)}`)}"></i></div>
      <span class="${cls(x.pnl)}" style="text-align:right">${fmt(x.pnl, 0)}</span></div>`).join(""); };
  $("#ts-out").innerHTML = `<div class="tiles">
      ${tile("총 수익률", pct(s.total_return_pct), cls(s.total_return_pct))}${tile("연 환산 (CAGR)", s.cagr_pct == null ? "30일 이상 필요" : pct(s.cagr_pct), cls(s.cagr_pct))}
      ${tile("샤프", s.sharpe)}${tile("소르티노", s.sortino)}${tile("칼마", s.calmar)}${tile("최대 낙폭", `-${s.max_dd_pct}%`, "down")}
      ${tile("낙폭 최장 기간", `${s.max_dd_days}일`)}${tile("연 변동성", `${s.ann_vol_pct}%`)}${tile("거래", s.trades)}${tile("승률", `${s.win_rate_pct}%`)}
      ${tile("손익비", s.payoff)}${tile("거래당 기대값", fmt(s.expectancy, 2), cls(s.expectancy))}${tile("수익 팩터", s.profit_factor)}
      ${tile("평균 보유", `${s.avg_hold_h}시간`)}${tile("최고 / 최악", `<span class="up">${fmt(s.best_trade, 0)}</span> / <span class="down">${fmt(s.worst_trade, 0)}</span>`)}
      ${tile("연승 / 연패", `${s.win_streak} / ${s.loss_streak}`)}</div>
    <div class="cols-2" style="margin-top:10px;align-items:start"><div>
      <div class="sub" style="padding-left:0">월별 수익률</div>
      <table class="heat"><tr><th></th>${Array.from({ length: 12 }, (_, i) => `<th>${i + 1}월</th>`).join("")}</tr>
        ${months.map(([y, m]) => `<tr><th>${y}</th>${Array.from({ length: 12 }, (_, i) => { const v = m[i + 1];
          return v == null ? "<td style='background:var(--panel-2)'></td>" : `<td style="background:${diverge(v / mx, "#e5484d", "#22b07d")}">${v > 0 ? "+" : ""}${fmt(v, 1)}</td>`; }).join("")}</tr>`).join("")}</table>
      <div class="sub" style="padding-left:0;margin-top:8px">낙폭 (고점 대비 %)</div><div class="chart" id="ts-dd" style="height:150px"></div></div>
    <div>
      <div class="sub" style="padding-left:0">코인별 손익</div>${bar(r.by_symbol, base)}
      <div class="sub" style="padding-left:0;margin-top:6px">방향별</div>${bar(r.by_side, (k) => k)}
      <div class="sub" style="padding-left:0;margin-top:6px">진입 시간대별 (한국 시간)</div>${bar(r.by_hour, (k) => `${k}시`)}
      <div class="sub" style="padding-left:0;margin-top:6px">요일별</div>${bar(r.by_weekday, (k) => r.weekday_names[k] + "요일")}</div></div>`;
  bindTips($("#ts-out"));
  tsChart?.remove();
  tsChart = makeChart($("#ts-dd"));
  const a = tsChart.addSeries(LC.AreaSeries, { lineColor: css("--down"), topColor: "rgba(229,72,77,0)", bottomColor: "rgba(229,72,77,.35)", lineWidth: 1, priceLineVisible: false });
  a.setData(r.underwater);
  tsChart.timeScale().fitContent();
}

// ================================================================ 초기화
export function initQuant() {
  $("#q-tabs").onclick = (e) => {
    const q = e.target.dataset.q;
    if (!q) return;
    $$("#q-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.q === q));
    $$(".qpane").forEach((p) => (p.hidden = p.id !== `q-${q}`));
    if (q === "scan") loadScanner().catch((err) => toast("스캐너 오류", err.message, "err"));
    if (q === "risk") { renderSizer(); loadSweepForm().catch(() => {}); }
  };
  $("#rot-run").onclick = (e) => busy(e.target, runRotation);
  $("#rb-run").onclick = (e) => busy(e.target, runRotBacktest);
  $("#v-quant").addEventListener("click", (e) => {
    const c = e.target.closest("[data-chart]")?.dataset.chart;
    if (!c) return;
    const [s, iv] = c.split("|");
    showOnChart(s, iv || (rot?.interval ?? state.interval));
  });
  // 스캐너
  $("#sc-on").onchange = (e) => saveScan({ enabled: e.target.checked });
  $("#sc-now").onclick = (e) => busy(e.target, async () => { scan = await api("/api/scanner/run", { method: "POST" }); renderScanCfg(); renderBoard(); sigs = (await api("/api/scanner/signals?limit=150")).items; renderSignals(); });
  $("#sc-syms").onclick = (e) => { const s = e.target.closest("[data-rm]")?.dataset.rm; if (s) saveScan({ symbols: scan.config.symbols.filter((x) => x !== s) }); };
  $("#sc-ivs").onclick = (e) => { const k = e.target.closest("[data-iv]")?.dataset.iv; if (!k) return; const cur = scan.config.intervals; saveScan({ intervals: cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k] }); };
  $("#sc-types").onclick = (e) => { const k = e.target.closest("[data-type]")?.dataset.type; if (k) saveScan({ signals: { ...scan.config.signals, [k]: !scan.config.signals[k] } }); };
  $("#sc-add").onkeydown = (e) => { if (e.key === "Enter" && e.target.value.trim()) { saveScan({ symbols: [...scan.config.symbols, e.target.value.trim()] }); e.target.value = ""; } };
  $("#sc-watch").onclick = () => saveScan({ symbols: [...new Set([...scan.config.symbols, ...state.watch])] });
  $("#sc-filter").onchange = renderSignals;
  on("signals", (items) => { sigs = [...items, ...sigs].slice(0, 200); if (!$("#q-scan").hidden) renderSignals(); });
  setInterval(() => { if (!$("#q-scan").hidden && !document.hidden) api("/api/scanner").then((s) => { scan = s; renderBoard(); renderScanCfg(); }).catch(() => {}); }, 30_000);
  // 리스크
  $("#rk-run").onclick = (e) => busy(e.target, runMatrix);
  $("#pf-run").onclick = (e) => busy(e.target, runPortfolio);
  $("#mc-run").onclick = (e) => busy(e.target, runMonteCarlo);
  $("#sw-run").onclick = (e) => busy(e.target, runSweep);
  on("backtest", () => { if (!$("#q-risk").hidden) { renderSizer(); loadSweepForm().catch(() => {}); } });
  on("view", (v) => { if (v === "quant" && !rot) busy($("#rot-run"), runRotation); });
  // 기관식 포트폴리오
  $("#po-run").onclick = (e) => busy(e.target, runOptimize);
  $("#st-run").onclick = (e) => busy(e.target, () => runStress(null));
  $("#ex-run").onclick = (e) => busy(e.target, runExposure);
  $("#ts-run").onclick = (e) => busy(e.target, runTearsheet);
  $("#po-out").addEventListener("click", (e) => {
    const m = e.target.closest("[data-stress]")?.dataset.stress;
    if (!m || !opt) return;
    busy(e.target, () => runStress(opt.results.find((r) => r.method === m).weights));
    $("#st-out").scrollIntoView({ behavior: "smooth", block: "center" });
  });
}
