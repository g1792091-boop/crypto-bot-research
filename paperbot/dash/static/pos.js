// ------------------------------------------------------------ positions (exchange-style, live)
// Every open paper position like an exchange's position list: unrealized P&L and ROI on the live mark price
// (same as the Binance app: before the exit fee), size, margin, entry / mark / liquidation price, the stop and the
// profit lock, plus the coin's order book. Nothing here trades: there are no order buttons.
const pv = {sym: "", sort: "pnl", tab: "pos", why: {}, whyAt: 0};
const LOCK = {first: 0.10, step: 0.05, gap: 0.02};   // config.py ladder (ladder.py): arms at lock + gap net ROE

function usdt(x, d = 2) { return x == null || isNaN(x) ? "—" : (x > 0 ? "+" : x < 0 ? "-" : "") + fmt(Math.abs(x), d); }
function holdKo(ms) {
  if (!ms) return "—";
  const m = Math.max(0, Math.floor((Date.now() - ms) / 60000));
  return m < 60 ? `${m}분` : m < 1440 ? `${Math.floor(m / 60)}시간 ${m % 60}분` : `${Math.floor(m / 1440)}일 ${Math.floor(m % 1440 / 60)}시간`;
}
function pvList() {
  const list = positions().filter((a) => !pv.sym || a.position.symbol === pv.sym).map((a) => ({a, p: a.position, u: livePnl(a.position)}));
  const by = {
    pnl: (x, y) => ((y.u || {}).pnl ?? -1e18) - ((x.u || {}).pnl ?? -1e18),
    loss: (x, y) => ((x.u || {}).pnl ?? 1e18) - ((y.u || {}).pnl ?? 1e18),
    new: (x, y) => (y.p.entry_time || 0) - (x.p.entry_time || 0),
    liq: (x, y) => liqGap(x) - liqGap(y),
  };
  return list.sort(by[pv.sort] || by.pnl);
}
function liqGap(x) { const m = x.u ? x.u.m : null; return m && x.p.liq ? Math.abs(m - x.p.liq) / m : 9; }

function renderPvCoins() {
  const all = positions();
  const chip = (s, label) => {
    const n = s ? all.filter((a) => a.position.symbol === s).length : all.length;
    return `<button data-s="${s}" class="${pv.sym === s ? "on" : ""}">${label}<small>${n}</small></button>`;
  };
  $("pv-coins").innerHTML = chip("", "전체") + TRADE_SYMS.map((s) => chip(s, coin(s))).join("");
  $("pv-coins").querySelectorAll("button").forEach((b) => b.onclick = () => { pv.sym = b.dataset.s; bookUse(pv.sym); renderPos(); });
}
function renderPvSum(list) {
  const live = list.filter((x) => x.u);
  const tot = live.reduce((s, x) => s + x.u.pnl, 0), mg = list.reduce((s, x) => s + (x.p.margin || 0), 0);
  const up = live.filter((x) => x.u.pnl > 0).length, dn = live.filter((x) => x.u.pnl < 0).length;
  const longs = list.filter((x) => x.p.side > 0).length;
  const best = live.length ? live.reduce((b, x) => x.u.pnl > b.u.pnl ? x : b) : null;
  const worst = live.length ? live.reduce((b, x) => x.u.pnl < b.u.pnl ? x : b) : null;
  const cell = (k, v, sub) => `<div class="pv-c"><div class="k">${k}</div><div class="v">${v}</div>${sub ? `<div class="s">${sub}</div>` : ""}</div>`;
  $("pv-sum").innerHTML =
    cell("미실현 손익 합계 (USDT)", `<span class="${cls(tot)}">${usdt(tot)}</span>`, mg ? `묶인 증거금 대비 <span class="${cls(tot)}">${pct(tot / mg, 2)}</span>` : "") +
    cell("열린 포지션", `${list.length}개`, `롱 ${longs} · 숏 ${list.length - longs}`) +
    cell("수익 중 / 손실 중", `<span class="up">${up}</span> / <span class="down">${dn}</span>`, `묶인 증거금 $${fmt(mg, 0)}`) +
    cell("가장 많이 먹는 중", best ? `<span class="${cls(best.u.pnl)}">${usdt(best.u.pnl)}</span>` : "—", best ? esc(name(best.a)) + " · " + coin(best.p.symbol) : "") +
    cell("가장 많이 잃는 중", worst ? `<span class="${cls(worst.u.pnl)}">${usdt(worst.u.pnl)}</span>` : "—", worst ? esc(name(worst.a)) + " · " + coin(worst.p.symbol) : "");
}
function renderPvHead() {
  const el = $("pv-mkt");
  el.hidden = !pv.sym;
  if (!pv.sym) return;
  const s = pv.sym, t = state.tick[s], f = state.fund[s], m = state.mark[s];
  let fund = "—";
  if (f) {
    const left = Math.max(0, f.T - Date.now()), h = Math.floor(left / 3.6e6), mi = Math.floor(left % 3.6e6 / 6e4), se = Math.floor(left % 6e4 / 1000);
    fund = `<span class="${cls(-f.r)}">${(f.r * 100).toFixed(4)}%</span> / ${String(h).padStart(2, "0")}:${String(mi).padStart(2, "0")}:${String(se).padStart(2, "0")}`;
  }
  $("pv-head").innerHTML = `<div class="pv-sym">${coin(s)}USDT <small>무기한</small></div>
    <div class="pv-px ${t ? cls(t.p) : ""}">${t ? px(t.c) : m ? px(m) : "—"}</div>
    <div class="pv-kv"><span>24시간</span><b class="${t ? cls(t.p) : ""}">${t ? pct(t.p / 100, 2) : "—"}</b></div>
    <div class="pv-kv"><span>마크 가격</span><b>${m ? px(m) : "—"}</b></div>
    <div class="pv-kv"><span>펀딩비 / 남은 시간</span><b>${fund}</b></div>
    <div class="pv-kv"><span>24시간 고가 / 저가</span><b>${t ? px(t.h) + " / " + px(t.l) : "—"}</b></div>
    <button class="mini" id="pv-chart">이 코인 차트 보기</button>`;
  $("pv-chart").onclick = () => { show("trade"); if (state.sym !== s) setSym(s); };
  renderBook();
}
function renderBook() { if (pv.sym) $("pv-book").innerHTML = bookHtml(pv.sym, 7); }

// order book of one coin, shared by the positions tab and the trade screen (one subscription at a time):
// Binance's WebSocket in the browser, or /api/depth from the server every 2 s where that is blocked
const book = {sym: null, data: null, ws: null, ok: false, poll: null};
function bookUse(sym) {
  sym = sym || null;
  if (sym === book.sym) return;
  if (book.ws) { book.ws.onclose = null; book.ws.close(); book.ws = null; }
  clearInterval(book.poll); book.poll = null; book.ok = false; book.data = null; book.sym = sym;
  if (!sym) return;
  const poll = async () => {
    if (book.ok || sym !== book.sym) return;
    try { const d = await api(`/api/depth?symbol=${sym}`); if (sym === book.sym && !book.ok) book.data = d; } catch (e) { /* none */ }
  };
  try {
    book.ws = new WebSocket(`wss://fstream.binance.com/ws/${sym.toLowerCase()}@depth20@500ms`);
    book.ws.onopen = () => { book.ok = true; };
    book.ws.onmessage = (ev) => {
      const d = JSON.parse(ev.data); if (sym !== book.sym) return;
      book.data = {bids: (d.b || []).map((x) => [+x[0], +x[1]]), asks: (d.a || []).map((x) => [+x[0], +x[1]])};
    };
    book.ws.onclose = () => { book.ok = false; };
  } catch (e) { /* blocked: the poll below */ }
  poll(); book.poll = setInterval(poll, 2000);
}
function bookHtml(sym, n) {
  const b = book.data;
  if (!b || book.sym !== sym) return '<p class="empty">호가 불러오는 중</p>';
  const asks = b.asks.slice(0, n).reverse(), bids = b.bids.slice(0, n);
  const mx = Math.max(...asks.map((x) => x[1]), ...bids.map((x) => x[1]), 1e-12);
  const row = (x, c) => `<div class="bk ${c}"><i style="width:${Math.min(100, x[1] / mx * 100).toFixed(1)}%"></i><span>${px(x[0])}</span><span>${fmt(x[1], x[1] < 10 ? 3 : 1)}</span></div>`;
  const bq = b.bids.reduce((s, x) => s + x[1], 0), aq = b.asks.reduce((s, x) => s + x[1], 0);
  const share = bq + aq > 0 ? bq / (bq + aq) : 0.5;
  const t = state.tick[sym], last = t ? t.c : null;
  return `<div class="bk h"><span>가격 (USDT)</span><span>수량 (${coin(sym)})</span></div>` +
    asks.map((x) => row(x, "a")).join("") +
    `<div class="bk mid ${t ? cls(t.p) : ""}">${last ? px(last) : "—"}<small>${state.mark[sym] ? px(state.mark[sym]) : ""}</small></div>` +
    bids.map((x) => row(x, "b")).join("") +
    `<div class="bkbar"><span class="up">${(share * 100).toFixed(1)}%</span><div><i style="width:${(share * 100).toFixed(1)}%"></i></div><span class="down">${((1 - share) * 100).toFixed(1)}%</span></div>` +
    `<div class="muted" style="font-size:10.5px">${book.ok ? "바이낸스 실시간 호가" : "호가 (서버 경유, 2초마다)"} · 위 20개 호가 기준 매수/매도 비율</div>`;
}

function lockText(p, u) {
  if (p.lock_roe) {
    const nx = p.lock_roe + LOCK.step;
    return `<span class="up">순 ROE +${Math.round(p.lock_roe * 100)}% 잠금 중</span> (손절선이 수익 쪽) · 다음: +${Math.round((nx + LOCK.gap) * 100)}% 되면 +${Math.round(nx * 100)}% 잠금`;
  }
  return `순 ROE +${Math.round((LOCK.first + LOCK.gap) * 100)}% 되면 +${Math.round(LOCK.first * 100)}% 잠금 시작 (고정 익절 없음)`;
}
function posCard(x) {
  const {a, p, u} = x, lev = p.leverage, m = u ? u.m : null;
  const stopPnl = p.side * p.qty * (p.stop - p.entry);
  const gap = m && p.liq ? Math.abs(m - p.liq) / m : null;
  const strat = a.kind === "strategy" || a.kind === "copy";
  return `<div class="pcard ${u ? (u.pnl >= 0 ? "win" : "lose") : ""}">
    <div class="pc-top">${sideTag(p.side)} <b>${coin(p.symbol)}USDT</b> <span class="muted">무기한 · 격리 ${lev}배</span>
      <span class="grow"></span><span class="pc-acct" data-acct="${esc(a.account_id)}">${esc(name(a))}</span></div>
    <div class="pc-pnl"><div><div class="k">미실현 손익 (USDT)</div><div class="big ${u ? cls(u.pnl) : ""}">${u ? usdt(u.pnl) : "—"}</div></div>
      <div class="r"><div class="k">ROI</div><div class="big ${u ? cls(u.roe) : ""}">${u ? pct(u.roe, 2) : "—"}</div></div></div>
    <div class="pc-grid">
      <div><span>크기 (${coin(p.symbol)})</span><b>${fmt(p.qty, p.qty < 10 ? 4 : 1)}</b></div>
      <div><span>증거금 (USDT)</span><b>${fmt(p.margin, 2)}</b></div>
      <div><span>청산까지</span><b class="${gap != null && gap < 0.02 ? "down" : ""}">${gap == null ? "—" : (gap * 100).toFixed(2) + "%"}</b></div>
      <div><span>진입가</span><b>${px(p.entry)}</b></div>
      <div><span>마크 가격</span><b>${m ? px(m) : "—"}</b></div>
      <div><span>청산가</span><b class="accent">${px(p.liq)}</b></div>
    </div>
    <div class="pc-tpsl"><span>손절 ${px(p.stop)}</span> <span class="muted">닿으면</span> <b class="${cls(stopPnl)}">${usdt(stopPnl)}</b>
      <span class="muted">(${pct(stopPnl / p.margin, 1)})</span></div>
    <div class="pc-tpsl muted">${lockText(p, u)}</div>
    ${whyLine(a.account_id, p)}
    <div class="pc-foot"><span class="muted">${tsKo(p.entry_time)} 진입 · ${holdKo(p.entry_time)} 보유 · ${TF_KO[a.timeframe] || a.timeframe}봉</span>
      <span class="grow"></span><button class="mini" data-chart="${esc(a.account_id)}" data-sym="${esc(p.symbol)}">차트</button>
      ${strat ? `<button class="mini" data-strat="${esc(a.strategy)}" data-tf="${esc(a.timeframe)}" data-sym="${esc(p.symbol)}">매매법</button>` : ""}
      <button class="mini" data-acct="${esc(a.account_id)}">계좌</button></div>
  </div>`;
}
// why this leverage (GET /api/levwhy: group 좋은 자리/보통, entry-quality score, rejected higher candidates)
function whyHtml(w) {
  if (!w) return "";
  const tag = w.group === "best" ? '<span class="tag good">좋은 자리</span>' : w.group === "normal" ? '<span class="tag">보통</span>' : "";
  const sc = w.score != null ? `품질 점수 ${Number(w.score).toFixed(2)}` : w.source === "coin_flip" ? `동전 봇 (좋은 자리 확률 ${Math.round((w.p_best || 0) * 100)}%)` : "품질 점수 없음";
  return `${tag} ${sc} · ${esc(w.short_ko || (w.leverage ? w.leverage + "배" : ""))}`;
}
function whyLine(aid, p) {
  const w = pv.why[aid];
  if (!w || (w.entry_time != null && p.entry_time != null && w.entry_time !== p.entry_time)) return "";
  return `<div class="pc-tpsl muted">왜 ${p.leverage}배: ${whyHtml(w)}</div>`;
}
async function loadWhy(force) {
  if (!force && Date.now() - pv.whyAt < 20000) return;
  pv.whyAt = Date.now();
  try { pv.why = (await api("/api/levwhy")).positions || {}; } catch (e) { /* keeps the last */ }
  if (state.view === "pos") renderPos();
}
function orderRows(list) {
  if (!list.length) return '<p class="empty">걸려 있는 손절·잠금 주문이 없습니다</p>';
  return `<div class="scroll"><table><thead><tr><th class="l">계좌</th><th class="l">코인</th><th class="l">종류</th><th>발동 가격</th><th>지금과 거리</th><th>발동 시 손익</th></tr></thead><tbody>` +
    list.map(({a, p, u}) => {
      const pnl = p.side * p.qty * (p.stop - p.entry), m = u ? u.m : null;
      return `<tr class="click" data-id="${esc(a.account_id)}"><td class="l">${esc(name(a))}</td><td class="l">${coin(p.symbol)} ${sideTag(p.side)}</td>
        <td class="l">${p.lock_roe ? `익절 잠금 +${Math.round(p.lock_roe * 100)}% (스탑 마켓)` : "손절 (스탑 마켓)"}</td><td class="mono">${px(p.stop)}</td>
        <td class="mono">${m ? pct(Math.abs(m - p.stop) / m, 2).replace("+", "") : "—"}</td><td class="mono ${cls(pnl)}">${usdt(pnl)}</td></tr>`;
    }).join("") + "</tbody></table></div>";
}
async function renderPvHist() {
  const el = $("pv-list");
  const kst = 9 * 3.6e6, day0 = Math.floor((Date.now() + kst) / 864e5) * 864e5 - kst;   // 00:00 KST, as the summary card
  const rows = (await api("/api/trades?limit=500").catch(() => [])).filter((t) => t.exit_time >= day0 && (!pv.sym || t.symbol === pv.sym));
  if (pv.tab !== "hist") return;
  const tot = rows.reduce((s, t) => s + (t.pnl || 0), 0);
  el.innerHTML = `<div class="muted" style="margin:6px 2px">오늘(한국 0시 이후) 청산 ${rows.length}건 · 합계 <b class="${cls(tot)}">${usdt(tot)} USDT</b> (수수료 뒤)</div>` + tradeRows(rows, true);
  bindAccountClicks(el);
}
function renderPos() {
  if (state.view !== "pos") return;
  const list = pvList();
  renderPvCoins(); renderPvSum(list); renderPvHead();
  const n = positions().filter((a) => !pv.sym || a.position.symbol === pv.sym).length;
  $("pv-tabs").querySelector('[data-t="pos"]').textContent = `포지션 (${n})`;
  $("pv-tabs").querySelector('[data-t="orders"]').textContent = `손절·잠금 주문 (${n})`;
  if (pv.tab === "hist") return;
  const el = $("pv-list");
  if (pv.tab === "orders") el.innerHTML = orderRows(list);
  else el.innerHTML = list.length ? `<div class="pcards">${list.map(posCard).join("")}</div>` : '<p class="empty">열린 포지션이 없습니다</p>';
  bindAccountClicks(el);
  el.querySelectorAll(".pc-acct[data-acct]").forEach((s) => s.onclick = () => openAccount(s.dataset.acct));
}
function loadPos() { bookUse(pv.sym); renderPos(); loadWhy(true); if (pv.tab === "hist") renderPvHist(); }
document.querySelectorAll("#pv-tabs button").forEach((b) => b.onclick = () => {
  pv.tab = b.dataset.t;
  document.querySelectorAll("#pv-tabs button").forEach((x) => x.classList.toggle("on", x === b));
  renderPos(); if (pv.tab === "hist") renderPvHist();
});
$("pv-sort").onchange = (e) => { pv.sort = e.target.value; renderPos(); };
setInterval(() => {
  bookUse(state.view === "pos" ? pv.sym : state.view === "trade" && state.side2 === "book" ? state.sym : null);
  if (state.view === "pos") { renderPos(); loadWhy(); }
}, 1000);
