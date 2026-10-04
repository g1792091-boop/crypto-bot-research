"use strict";
// 매매법 tab: one strategy at a time. Its five timeframe accounts, its entries on the chart,
// its 5-year character (same rules), and the loss cards built by code at every losing close.
// Uses helpers and state from app.js ($, api, esc, fmt, pct, px, cls, coin, css, tsKo, state, openAccount).
const ss = {list: null, name: null, tf: "1h", sym: "BTCUSDT", filter: "", tab: "cards", markers: true,
  chart: null, series: null, lines: [], extra: [], profile: null, pageReq: 0, chartReq: 0};
const STYLE_TAG = {"추세 따라가기": "long", "되돌림 노리기": "short"};

async function loadStrat() {
  if (!ss.list) {
    try { ss.list = await api("/api/strategies"); } catch (e) { ss.list = []; }
    if (!ss.name && ss.list.length) ss.name = ss.list[0].strategy;
    $("s-sym").innerHTML = TRADE_SYMS.map((s) => `<option value="${s}">${coin(s)}</option>`).join("");
    $("s-pick").innerHTML = ss.list.map((x) => `<option value="${esc(x.strategy)}">${esc(x.name_ko)}</option>`).join("");
  }
  $("s-sym").value = ss.sym;
  document.querySelectorAll("#v-strat #s-tf button").forEach((b) => b.classList.toggle("on", b.dataset.tf === ss.tf));
  renderSList();
  await renderStrat();
}

// ------------------------------------------------------------ list
function bestWallet(name) {
  if (!state.board) return null;
  // the strategy's own 5 accounts only: its copy accounts (kind "copy") are listed on their own
  const ws = state.board.accounts.filter((a) => a.strategy === name && (a.kind ?? "strategy") === "strategy")
    .map((a) => a.wallet ?? INITIAL);
  return ws.length ? Math.max(...ws) : null;
}
function renderSList() {
  const rows = (ss.list || []).filter((x) => !ss.filter || x.style === ss.filter);
  $("slist").innerHTML = rows.map((x) => {
    const w = bestWallet(x.strategy);
    return `<div class="srow ${x.strategy === ss.name ? "sel" : ""}" data-n="${esc(x.strategy)}">
      <div style="min-width:0"><div class="nm">${esc(x.name_ko)}</div>
      <div class="st">${esc(x.style || "신호 부족")}${x.rare ? " · 신호 드묾" : ""}</div>
      <div class="st">${wlText(liveRec(stratAccts(x.strategy)))}</div></div>
      <span class="w ${w == null ? "" : cls(w - INITIAL)}">${w == null ? "" : "$" + fmt(w, 0)}</span></div>`;
  }).join("") || '<p class="empty">없음</p>';
  document.querySelectorAll("#slist .srow").forEach((r) => r.onclick = () => pickStrat(r.dataset.n));
  $("s-pick").value = ss.name || "";
}
// live record of a strategy's accounts (the 5 timeframes; copies and new-lab accounts are not its own)
function liveRec(list) {
  const r = {trades: 0, wins: 0, losses: 0, pnl: 0, gw: 0, gl: 0};
  for (const a of list) { r.trades += a.trades || 0; r.wins += a.wins || 0; r.losses += a.losses || 0; r.pnl += a.pnl || 0; r.gw += a.gross_win || 0; r.gl += a.gross_loss || 0; }
  r.rate = r.trades ? r.wins / r.trades : null;
  r.avgW = r.wins ? r.gw / r.wins : null; r.avgL = r.losses ? r.gl / r.losses : null;
  r.ratio = r.avgW != null && r.avgL ? r.avgW / Math.abs(r.avgL) : null;
  // 본전 승률: the win rate at which these average win and loss come out even, |avg loss| / (avg win + |avg loss|)
  r.be = r.avgW != null && r.avgL ? Math.abs(r.avgL) / (r.avgW + Math.abs(r.avgL)) : null;
  return r;
}
// 최대 낙폭 and 파산 확률 of the strategy's five accounts (server-side, /api/profile live_risk: agents/survival.py)
function riskSpans(lr) {
  if (!lr || lr.error) return "";
  const pc = (x) => (x * 100 < 1 && x > 0 ? (x * 100).toFixed(1) : Math.round(x * 100)) + "%";
  let s = "";
  if (lr.max_dd_pct != null) {
    s += `<span title="5개 봉 계좌를 합친 자금이 지금까지 가장 높았던 때에서 가장 많이 내려간 폭(5분마다 기록된 평가 자금, 열린 포지션 포함)${lr.max_dd_usd != null ? `. 금액으로 $${Math.round(lr.max_dd_usd).toLocaleString("en-US")}` : ""}${lr.max_dd_at ? `, 바닥 ${lr.max_dd_at}` : ""}">최대 낙폭 <b class="${lr.max_dd_pct >= 0.3 ? "down" : ""}">${lr.max_dd_pct > 0 ? "-" : ""}${pc(lr.max_dd_pct)}</b></span>`;
  }
  if (lr.p_bust != null) {
    s += `<span title="이 매매법 봉 계좌의 지금까지 끝난 거래(20건 이상인 계좌만)를 무작위로 다시 뽑아 앞으로 30일을 ${(lr.paths || 10000).toLocaleString("en-US")}번 흉내 냈을 때, 잔고가 파산선(엔진 기준 $10) 아래로 떨어진 비율. 봉 계좌 중 가장 높은 값(${TF_KO[lr.p_bust_tf] || lr.p_bust_tf || ""}). 지난 거래가 앞으로도 같은 모양이라는 가정이라 예측이 아니라 설명용입니다">파산 확률 <b class="${lr.p_bust >= 0.05 ? "down" : ""}">${pc(lr.p_bust)}</b></span>`;
  }
  return s;
}
const stratAccts = (n) => (state.board ? state.board.accounts.filter((a) => a.kind === "strategy" && a.strategy === n) : []);
const wlText = (r) => r.trades ? `${r.wins}승 ${r.losses}패 · ${Math.round(r.rate * 100)}%` : "거래 없음";
function renderLive() {
  const el = $("s-live"); if (!el || !ss.name) return;
  const r = liveRec(stratAccts(ss.name));
  const lr = ss.profile && ss.profile.strategy === ss.name ? ss.profile.live_risk : null;
  const usd0 = (x) => x == null ? "—" : `${x < 0 ? "-" : "+"}$${fmt(Math.abs(x), 0)}`;
  el.innerHTML = r.trades ? `<div class="lv"><b>실전 기록 (5개 봉 합계)</b> <span>${r.wins}승 ${r.losses}패</span>
    <span>승률 <b>${Math.round(r.rate * 100)}%</b></span><span>손익 <b class="${cls(r.pnl)}">${usd0(r.pnl)}</b></span>
    <span>평균 이익 <b class="up">${usd0(r.avgW)}</b></span><span>평균 손실 <b class="down">${usd0(r.avgL)}</b></span>
    <span title="평균 이익 ÷ 평균 손실. 승률이 낮아도 이게 크면 남을 수 있음">손익비 <b>${r.ratio == null ? "—" : r.ratio.toFixed(2)}</b></span>
    <span title="이 평균 이익·평균 손실이라면 몇 % 이겨야 본전인지(평균 손실 ÷ (평균 이익 + 평균 손실)). 실제 승률이 이보다 높아야 남습니다. 손절이 멀고 첫 익절 잠금이 가까운 지금 규칙에서는 높게 나오는 게 자연스럽습니다">본전 승률 <b class="${r.be == null ? "" : r.rate >= r.be ? "up" : "down"}">${r.be == null ? "—" : Math.round(r.be * 100) + "%"}</b></span>${riskSpans(lr)}</div>`
    : '<div class="lv muted">실전 기록: 아직 끝난 거래가 없습니다</div>';
}
function pickStrat(n) { ss.name = n; renderSList(); renderStrat(); }
// from a position anywhere (trade chart box, position tables): this strategy, at that account's timeframe and coin
function openStrategy(name, tf, sym) {
  ss.name = name;
  if (tf && tf !== "1d") ss.tf = tf;
  if (sym && TRADE_SYMS.includes(sym)) ss.sym = sym;
  show("strat");
}
$("s-pick").onchange = (e) => pickStrat(e.target.value);
$("s-sym").onchange = (e) => { ss.sym = e.target.value; drawStratChart(); };
$("s-mk").onclick = (e) => { ss.markers = !ss.markers; e.target.classList.toggle("on", ss.markers); drawStratChart(); };
seg("sl-filter", "f", (f) => { ss.filter = f; renderSList(); });
function setStratTf(tf) { ss.tf = tf; renderAccts(); renderProfile(); drawStratChart(); }
seg("s-tf", "tf", setStratTf);
seg("s-tabs", "t", (t) => { ss.tab = t; renderSSide(); });

// ------------------------------------------------------------ page
async function renderStrat() {
  if (!ss.name) return;
  const id = ++ss.pageReq;
  renderAccts();
  drawStratChart();
  ss.profile = await api(`/api/profile/${encodeURIComponent(ss.name)}`).catch(() => null);
  if (id !== ss.pageReq) return;
  renderProfile();
  renderLive();
  renderSSide();
}

function renderAccts() {
  document.querySelectorAll("#s-tf button").forEach((b) => b.classList.toggle("on", b.dataset.tf === ss.tf));
  $("s-accts").innerHTML = TRADE_TFS.map((tf) => {
    const a = state.board && state.board.accounts.find((x) => x.account_id === `${ss.name}@${tf}`);
    const w = a ? (a.wallet ?? INITIAL) : null;
    let s = !a ? "—" : a.trades ? `${a.wins}승 ${a.losses}패 · ${Math.round(a.trades ? a.wins / a.trades * 100 : 0)}%` : "거래 없음";
    if (a && a.bust) s += ' · <span class="down">파산</span>';
    else if (a && a.position) s += `<br><span class="accent">● ${coin(a.position.symbol)} ${a.position.side > 0 ? "롱" : "숏"}</span>`;
    const vs = !a || a.beats_random == null ? "" : a.beats_random ? '<span class="up">동전 봇보다 ✓</span>' : '<span class="muted">동전 봇보다 ✕</span>';
    return `<div class="acard ${tf === ss.tf ? "sel" : ""}" data-tf="${tf}" title="누르면 이 봉으로 차트를 봅니다. 두 번 누르면 계좌 화면">
      <div class="k">${TF_KO[tf]}</div><div class="v ${w == null ? "" : cls(w - INITIAL)}">${w == null ? "—" : "$" + fmt(w, 0)}</div>
      <div class="s">${s}</div><div class="s">${vs}</div></div>`;
  }).join("");
  renderLive();
  document.querySelectorAll("#s-accts .acard").forEach((c) => {
    c.onclick = () => setStratTf(c.dataset.tf);
    c.ondblclick = () => openAccount(`${ss.name}@${c.dataset.tf}`);
  });
}

// ------------------------------------------------------------ chart
function ensureStratChart() {
  if (ss.chart || !window.LightweightCharts) return;
  const el = $("schart");
  ss.chart = LightweightCharts.createChart(el, chartOpts(el));
  ss.series = ss.chart.addCandlestickSeries({upColor: css("--up"), downColor: css("--down"), borderVisible: false,
    wickUpColor: css("--up"), wickDownColor: css("--down")});
  new ResizeObserver(() => ss.chart.resize(el.clientWidth, el.clientHeight)).observe(el);
}
async function drawStratChart() {
  ensureStratChart();
  if (!ss.chart) { $("schart").innerHTML = '<p class="empty">차트 부품을 불러오지 못했습니다</p>'; return; }
  const id = ++ss.chartReq;
  const aid = `${ss.name}@${ss.tf}`;
  const [bars, trades, view, sigs] = await Promise.all([
    api(`/api/candles?symbol=${ss.sym}&interval=${ss.tf}&limit=500`).catch(() => []),
    ss.markers ? api(`/api/trades?symbol=${ss.sym}&tf=${ss.tf}&limit=600`).catch(() => []) : Promise.resolve([]),
    api(`/api/strategy/${encodeURIComponent(ss.name)}?tf=${ss.tf}&symbol=${ss.sym}`).catch(() => null),
    api(`/api/signals?symbol=${ss.sym}&tf=${ss.tf}&limit=500`).catch(() => []),
  ]);
  ss.sigs = sigs.filter((r) => r.strategy === ss.name);
  if (id !== ss.chartReq) return;
  ss.series.setData(bars);
  // indicator lines exactly as the strategy's locked code uses them (when the view is available)
  ss.extra.forEach((x) => ss.chart.removeSeries(x)); ss.extra = [];
  const palette = [css("--series"), css("--text-2"), css("--accent"), "#b38cf0"];
  if (view && view.overlays) view.overlays.forEach((o, i) => {
    const s = ss.chart.addLineSeries({color: palette[i % palette.length], lineWidth: 1.5, priceLineVisible: false,
      lastValueVisible: false, crosshairMarkerVisible: false, title: o.name});
    s.setData(o.data); ss.extra.push(s);
  });
  if (view && view.panes) view.panes.forEach((p, k) => {
    const scale = `pane${k}`;
    p.series.forEach((ln, i) => {
      const hist = /히스토그램/.test(ln.name);
      const s = hist
        ? ss.chart.addHistogramSeries({priceScaleId: scale, priceLineVisible: false, lastValueVisible: false})
        : ss.chart.addLineSeries({color: palette[(i + 1) % palette.length], lineWidth: 1.5, priceScaleId: scale,
          priceLineVisible: false, lastValueVisible: i === 0, crosshairMarkerVisible: false, title: i === 0 ? p.name : ""});
      s.setData(hist ? ln.data.map((d) => ({...d, color: d.value >= 0 ? css("--up-bg") : css("--down-bg")})) : ln.data);
      if (i === 0) (p.levels || []).forEach((lv) => s.createPriceLine({price: lv, color: css("--line-2"), lineWidth: 1,
        lineStyle: 2, axisLabelVisible: false}));
      ss.extra.push(s);
    });
    ss.chart.priceScale(scale).applyOptions({scaleMargins: {top: 0.78 - 0.2 * k, bottom: 0.02 + 0.2 * k}});
  });
  ss.chart.priceScale("right").applyOptions({scaleMargins: {top: 0.05, bottom: view && view.panes && view.panes.length ? 0.28 : 0.05}});
  // this account's entries and exits
  const step = TF_SEC[ss.tf], t0 = bars.length ? bars[0].time : 0, marks = [];
  trades.filter((t) => t.account_id === aid && t.entry_time / 1000 >= t0).forEach((t) => {
    const e = Math.floor(t.entry_time / 1000), x = Math.floor(t.exit_time / 1000);
    // arrows for entries, dots with the ROE for exits: details are in the loss cards, not on the candles
    marks.push({time: e - (e % step), position: t.side > 0 ? "belowBar" : "aboveBar", color: css("--series"),
      shape: t.side > 0 ? "arrowUp" : "arrowDown", text: ""});
    marks.push({time: x - (x % step), position: t.side > 0 ? "aboveBar" : "belowBar", color: t.pnl > 0 ? css("--up") : css("--down"),
      shape: "circle", text: pct(t.roe, 0)});
  });
  marks.sort((a, b) => a.time - b.time);
  ss.series.setMarkers(marks);
  ss.lines.forEach((l) => ss.series.removePriceLine(l)); ss.lines = [];
  const a = state.board && state.board.accounts.find((x) => x.account_id === aid);
  const p = a && a.position;
  if (p && p.symbol === ss.sym) {
    ss.lines.push(ss.series.createPriceLine({price: p.entry, color: css("--series"), lineWidth: 1, title: "진입"}));
    ss.lines.push(ss.series.createPriceLine({price: p.stop, color: p.lock_roe ? css("--up") : css("--down"), lineWidth: 1, lineStyle: 2,
      title: p.lock_roe ? `잠금 +${Math.round(p.lock_roe * 100)}%` : "손절"}));
  }
  ss.chart.timeScale().fitContent();
  const last = bars[bars.length - 1];
  $("slegend").innerHTML = `<b>${esc(nameKo(ss.name))}</b> · ${coin(ss.sym)} ${TF_KO[ss.tf]}` +
    (last ? ` · 종 <b>${px(last.close)}</b>` : "") + (view ? "" : ' <span class="muted">· 지표선은 준비 중</span>');
  renderConds(view);
}
function nameKo(n) { const x = (ss.list || []).find((y) => y.strategy === n); return x ? x.name_ko : n; }
function renderConds(view) {
  const el = $("s-conds");
  if (!view || !view.conditions) { el.innerHTML = ""; return; }
  const part = (side, list) => {
    if (!list || !list.length) return "";
    const on = list.filter((c) => c.on).length;
    return `<div><div style="margin-bottom:4px"><b>${side} 조건</b> <span class="muted">${on}/${list.length} 켜짐</span></div>` +
      list.map((c) => `<div class="cond"><span>${esc(c.name)}</span><span class="${c.on ? "ok" : "no"}">${c.on ? "✓" : "✕"}</span></div>`).join("") + "</div>";
  };
  const c = view.conditions;
  const left = (l) => l && l.length ? l.length - l.filter((x) => x.on).length : null;
  const nl = left(c.long), ns = left(c.short);
  const near = [nl, ns].filter((x) => x != null).length ? Math.min(...[nl, ns].filter((x) => x != null)) : null;
  // what the bot itself signalled on that bar (signal log = the exact source; the checklist explains it)
  const bot = (ss.sigs || []).find((r) => r.bar_close === view.bar_close);
  const botTxt = bot ? `봇 신호: <b class="${bot.side > 0 ? "up" : "down"}">${bot.side > 0 ? "롱" : "숏"}</b> (${STATUS_KO[bot.status] || bot.status})`
    : '봇 신호: <span class="muted">없음</span>';
  el.innerHTML = `<div class="muted" style="margin-bottom:6px">방금 마감한 ${TF_KO[ss.tf]}봉 기준 · ${tsKo(view.bar_close)} · ${botTxt}</div>` +
    `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:4px 18px">${part("롱", c.long)}${part("숏", c.short)}</div>` +
    (near === 0 ? '<div class="near">이 봉에서 신호 조건이 모두 켜졌습니다</div>'
      : near != null ? `<div class="near">신호까지 조건 ${near}개 남음</div>` : "") + lastMarks(view.last_signal);
}

// ------------------------------------------------------------ entry marks (paperbot/entry_marks.py)
// Support / resistance and the strategy's own entry-strength numbers, recorded with every signal.
// Descriptive only: the pre-registered entry study (research/entry_study) found no effect on outcomes.
const MARKS_NOTE = "가격선·강도 숫자는 진입 연구에서 수익과 관계없다고 나온 설명용 표시입니다.";
function srLine(sr) {
  if (!sr) return "";
  const d = (v, ko) => v == null ? "—" : `${v >= 10 ? "10+" : fmt(v, 1)} ATR${ko ? ` (${esc(ko)})` : ""}`;
  return `가는 쪽 가장 가까운 선 ${d(sr.room, sr.room_ko)} · 뒤쪽 가장 가까운 선 ${d(sr.floor, sr.floor_ko)}`;
}
function strengthLine(fs) {
  if (!fs || !fs.length) return "";
  return fs.map((f) => `${esc(f.label_ko)} <b>${fmt(f.value, f.value != null && Math.abs(f.value) >= 100 ? 0 : 2)}</b> ` +
    `${esc(f.unit_ko || f.unit)}${f.higher_is_stronger ? "" : " (작을수록 강함)"}`).join(" · ");
}
function lastMarks(ls) {
  if (!ls) return `<div class="muted" style="margin-top:8px">최근 30일 이 코인·봉에서 이 매매법의 신호가 없습니다.</div>`;
  const st = ls.strength && ls.strength.features ? strengthLine(ls.strength.features)
    : ls.strength && ls.strength.error ? '<span class="muted">강도 계산 실패</span>' : "";
  const sr = ls.sr && !ls.sr.error ? srLine(ls.sr) : ls.sr && ls.sr.error ? '<span class="muted">가격선 계산 실패</span>' : "";
  const body = [st && `<div>진입 강도: ${st}</div>`, sr && `<div>${sr}</div>`].filter(Boolean).join("")
    || `<div class="muted">${ls.error ? "표시 계산 실패" : "이 신호에는 기록이 없습니다 (기능 추가 전 신호)"}</div>`;
  return `<div style="margin-top:8px;line-height:1.6;overflow-wrap:anywhere"><div class="muted">최근 신호 ${tsKo(ls.bar_close)} · ` +
    `<b class="${ls.side > 0 ? "up" : "down"}">${ls.side > 0 ? "롱" : "숏"}</b> (${STATUS_KO[ls.status] || esc(ls.status)})</div>${body}` +
    `<div class="muted" style="font-size:11px">${MARKS_NOTE}</div></div>`;
}

// ------------------------------------------------------------ 5-year character
function renderProfile() {
  const p = ss.profile, el = $("s-profile");
  if (!p) { el.innerHTML = '<p class="empty">과거 성격 자료가 없습니다</p>'; return; }
  const rows = p.rows.map((r) => {
    if (r.mean_roe == null) return `<tr><td class="l">${TF_KO[r.tf]}</td><td>${fmt(r.signals_per_day, 2)}</td><td colspan="6" class="l muted">신호가 너무 적음</td></tr>`;
    const more = r.hold_more_16 == null ? "—" : `<span class="${r.hold_verdict === "더 들고 갔으면 나았음" ? "up" : r.hold_verdict === "빨리 나오는 게 맞음" ? "down" : "muted"}">${(r.hold_more_16 * 100 > 0 ? "+" : "") + (r.hold_more_16 * 100).toFixed(1)}%p</span>`;
    const acct = (w, b) => w == null ? "—" : `<span class="${b ? "down" : cls(w - INITIAL)}">$${fmt(w, 0)}</span>`;
    return `<tr class="${r.tf === ss.tf ? "sel" : ""}"><td class="l">${TF_KO[r.tf]}</td><td>${fmt(r.signals_per_day, 1)}</td>
      <td class="mono ${cls(r.mean_roe)}">${pct(r.mean_roe)}</td><td>${r.win_rate == null ? "—" : Math.round(r.win_rate * 100) + "%"}</td>
      <td>${fmt(r.median_hold_hours, 1)}시간</td><td>${r.lock_share == null ? "—" : Math.round(r.lock_share * 100) + "%"}</td>
      <td class="mono">${more}</td><td class="mono">${acct(r.account_is, r.bust_is)} → ${acct(r.account_cf, r.bust_cf)}</td></tr>`;
  }).join("");
  const src = p.data_source === "binance_futures" ? "바이낸스 선물 데이터" : "여러 거래소 합산 현물 데이터";
  el.innerHTML = `<div class="sum">과거 5년(${src}), 같은 규칙: <b>${esc(p.style || "신호 부족")}</b> · ${esc(p.hold)}` +
    `${p.least_bad_tf ? ` · 가장 덜 나쁜 봉 <b>${TF_KO[p.least_bad_tf]}</b>` : ""}${p.rare ? ' · <span class="accent">신호가 너무 드묾</span>' : ""}<br>` +
    `<span class="muted">성격 설명일 뿐 실력 증거가 아닙니다. 평균 ROE가 비용(40배 왕복 약 −5.6%) 근처면 방향을 맞히는 힘이 0에 가깝다는 뜻입니다.</span></div>` +
    `<table><thead><tr><th class="l">봉</th><th>하루 신호</th><th>거래당 ROE</th><th>승률</th><th>보유</th><th>잠금 청산</th>` +
    `<th title="익절 잠금으로 나간 거래를 16봉 더 들고 있었다면">16봉 더</th><th>5년 계좌</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// ------------------------------------------------------------ loss cards and patterns
async function renderSSide() {
  const el = $("s-side"), id = ss.pageReq, n = encodeURIComponent(ss.name);
  if (ss.tab === "cards") {
    const cards = await api(`/api/cards?strategy=${n}&days=30&limit=40`).catch(() => []);
    if (id !== ss.pageReq) return;
    el.innerHTML = cards.length ? cards.map(lossCard).join("") : '<p class="empty">최근 30일 손실 거래가 없습니다</p>';
  } else {
    const st = await api(`/api/cards/stats?strategy=${n}&days=30`).catch(() => null);
    if (id !== ss.pageReq) return;
    if (!st || !st.trades) { el.innerHTML = '<p class="empty">최근 30일 거래가 없습니다</p>'; return; }
    el.innerHTML = `<div class="sum" style="padding:8px 12px;color:var(--text-2)">최근 30일 거래 ${st.trades}건 (손실 ${st.losses} · 이익 ${st.wins}).
      손실에서 이익보다 훨씬 자주 보이는 상황이 전담 직원이 먼저 볼 곳입니다. 건수가 적으면 우연일 수 있습니다.
      ${MARKS_NOTE}</div>` +
      st.tags.map((t) => `<div class="tagrow"><div>${esc(t.tag)}</div>${t.note ? `<div class="muted" style="font-size:11px">${esc(t.note)}</div>` : ""}<div class="bars">
        <span>손실</span><div class="bar"><i style="width:${Math.round((t.loss_share || 0) * 100)}%;background:var(--down)"></i></div><span>${t.loss_share == null ? "—" : Math.round(t.loss_share * 100) + "%"}</span>
        <span>이익</span><div class="bar"><i style="width:${Math.round((t.win_share || 0) * 100)}%;background:var(--up)"></i></div><span>${t.win_share == null ? "—" : Math.round(t.win_share * 100) + "%"}</span>
      </div></div>`).join("");
  }
}
function lossCard(c) {
  const ctx = [c.regime_ko && `이 봉 ${c.regime_ko}`, c.htf_regime_ko && `상위 봉 ${c.htf_regime_ko}`,
    c.ctx && c.ctx.adx != null && `ADX ${c.ctx.adx.toFixed(0)}`].filter(Boolean).join(" · ");
  const ifs = Object.keys(c.if_stop || {}).length
    ? Object.entries(c.if_stop).map(([k, v]) => `${k} ATR: <span class="${cls(v.roe)}">${v.roe == null ? "진입 안 됨" : pct(v.roe, 0)}</span>`).join(" · ")
    : '<span class="muted">밤 점검 후 표시</span>';
  return `<div class="lcard"><div class="hd"><span>${coin(c.symbol)} ${TF_KO[c.timeframe] || c.timeframe} ${c.side_ko} ${c.leverage}배</span>
    <span class="down">${esc(c.reason_ko)} ${pct(c.roe, 0)}</span></div>
    <div class="ln">${tsKo(c.entry_time)} 진입 · ${c.hold_min < 120 ? Math.round(c.hold_min) + "분" : (c.hold_min / 60).toFixed(1) + "시간"} 보유 ·
      진입 후 최고 <span class="${cls(c.best_roe)}">${pct(c.best_roe, 0)}</span>${c.touched_first_lock ? " (잠금선 닿음)" : ""}</div>
    ${ctx ? `<div class="ln">${esc(ctx)}</div>` : ""}
    ${c.strength && c.strength.length ? `<div class="ln">진입 강도: ${strengthLine(c.strength)}</div>` : ""}
    ${c.sr ? `<div class="ln">${srLine(c.sr)}</div>` : ""}
    <div class="ln">손절 거리를 바꿨다면: ${ifs}</div>
    ${c.tags.length ? `<div class="chips2">${c.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>` : ""}</div>`;
}
