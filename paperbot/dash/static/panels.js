// ------------------------------------------------------------ trade screen: lower-left and lower-right panels
// Lower left: GH Coin's current call for each coin (recorder board.json) / today and the schedule.
// Lower right: the chart coin's order book (pos.js bookUse) / forced liquidations across Binance (liq.db).
state.watch2 = "gh"; state.side2 = "book";
const p2 = {gh: null, sum: null, liq: null};
const GH_CLS = {long: "up", longWait: "up", short: "down", shortWait: "down"};

async function loadGh() {
  try { p2.gh = await api("/api/ghcoin/board"); } catch (e) { p2.gh = null; }
  if (state.view === "trade" && state.watch2 === "gh") renderWatch2();
}
async function loadSum() {
  try { p2.sum = await api("/api/summary"); } catch (e) { /* keep the last */ }
}
async function loadLiq() {
  const sym = state.sym;
  try { const d = await api(`/api/liq?symbol=${sym}&minutes=60`); if (sym === state.sym) p2.liq = d; } catch (e) { p2.liq = null; }
  if (state.view === "trade" && state.side2 === "liq") renderSide2();
}

function ghRows() {
  const g = p2.gh;
  if (!g || !g.coins || !Object.keys(g.coins).length) return '<p class="empty">GH Coin 기록기 응답 없음</p>';
  return `<table class="p2t"><thead><tr><th class="l">코인</th><th class="l">GH Coin 판단</th><th>확신</th></tr></thead><tbody>` +
    TRADE_SYMS.map((s) => {
      const c = g.coins[s];
      if (!c) return `<tr><td class="l"><b>${coin(s)}</b></td><td class="l muted" colspan="2">${esc((g.errors || {})[s] ? "가격 못 받음" : "—")}</td></tr>`;
      return `<tr class="click ${s === state.sym ? "sel" : ""}" data-gs="${s}" title="${esc([c.regime, c.why].filter(Boolean).join(" · "))}"><td class="l"><b>${coin(s)}</b></td>
        <td class="l"><span class="${GH_CLS[c.state] || "muted"}">${esc(GH_STATE_KO[c.state] || c.state)}</span></td>
        <td class="mono">${c.conf == null ? "—" : Math.round(c.conf)}</td></tr>`;
    }).join("") + "</tbody></table>" +
    `<div class="p2n">${g.alive ? "5분마다 갱신" : "기록기가 15분 넘게 조용함"} · 누르면 그 코인 차트에 GH Coin 선 · 기록만 하는 참고용 (195개 계좌와 무관)</div>`;
}
function usOpen(now) {   // US stocks 09:30-16:00 New York, weekdays
  const ny = new Intl.DateTimeFormat("en-US", {timeZone: "America/New_York", hour12: false, weekday: "short", hour: "2-digit", minute: "2-digit"})
    .formatToParts(new Date(now)).reduce((o, p) => (o[p.type] = p.value, o), {});
  const mins = (+ny.hour % 24) * 60 + +ny.minute, wk = !["Sat", "Sun"].includes(ny.weekday);
  const off = ((+ny.hour % 24) - new Date(now).getUTCHours() + 24) % 24 - 24;   // -4 (summer) or -5
  const kstOpen = `${(9 - off + 9) % 24}:30`;   // 09:30 New York in Korea time: 22:30 or 23:30
  const hm = (m) => `${Math.floor(m / 60)}시간 ${m % 60}분`;
  if (wk && mins < 570) return `${hm(570 - mins)} 후 개장 (한국 ${kstOpen})`;
  if (wk && mins < 960) return `<span class="up">열려 있음</span> · 마감까지 ${hm(960 - mins)}`;
  return `닫힘 · 다음 개장 한국 ${kstOpen}${ny.weekday === "Fri" || !wk ? " (월요일 밤)" : ""}`;
}
function dayRows() {
  const s = p2.sum, now = Date.now(), f = state.fund[state.sym];
  const kv = (k, v) => `<div class="p2kv"><span>${k}</span><b>${v}</b></div>`;
  let out = '<div class="p2h">오늘 (한국 0시부터)</div>';
  if (s && s.today) {
    const t = s.today;
    out += kv("청산된 거래", `${t.trades}건`) + kv("매매법 계좌 손익 합계", `<span class="${cls(t.pnl)}">${t.pnl < 0 ? "-" : "+"}$${fmt(Math.abs(t.pnl), 0)}</span>`) +
      kv("이긴 거래", `${t.wins} / ${t.strategy_trades}`) + kv("강제청산", t.liquidations ? `<span class="down">${t.liquidations}건</span>` : "0건");
  } else out += '<p class="empty">불러오는 중</p>';
  out += '<div class="p2h">일정</div>';
  if (f) {
    const left = Math.max(0, f.T - now);
    out += kv(`다음 펀딩 (${coin(state.sym)})`, `${Math.floor(left / 3.6e6)}시간 ${Math.floor(left % 3.6e6 / 6e4)}분 · <span class="${cls(-f.r)}">${(f.r * 100).toFixed(4)}%</span>`);
  }
  out += kv("미국 증시", usOpen(now));
  const ev = s && s.events;
  if (ev && ev.length) ev.slice(0, 2).forEach((e) => {
    const d = Math.ceil((e.ts_ms - now) / 864e5);
    out += kv(esc(e.name_ko), `${tsKo(e.ts_ms)} (${d <= 0 ? "오늘" : "D-" + d})`);
  });
  else if (s) out += kv("미국 경제발표", '<span class="muted">등록된 일정 없음</span>');
  if (s && s.next_checkpoint) {
    const d = Math.ceil((s.next_checkpoint.ts - now) / 864e5);
    out += kv(`${s.next_checkpoint.day}일째 판정`, `${tsKo(s.next_checkpoint.ts)} (D-${d})`);
  }
  if (s && s.observing) out += kv("관찰 기간 끝", tsKo(s.observe_until));
  return out;
}
function renderWatch2() {
  const el = $("watch2-body"); if (!el) return;
  el.innerHTML = state.watch2 === "gh" ? ghRows() : dayRows();
  el.querySelectorAll("[data-gs]").forEach((tr) => tr.onclick = () => {
    if (!state.ghOn) { state.ghOn = true; setPref("gh", true); $("gh-toggle").classList.add("on"); }
    if (tr.dataset.gs !== state.sym) setSym(tr.dataset.gs); else loadLevels();
  });
}
const hms = (ms) => { const d = new Date(ms); return [d.getHours(), d.getMinutes(), d.getSeconds()].map((x) => String(x).padStart(2, "0")).join(":"); };
function liqRows() {
  const d = p2.liq;
  if (!d) return '<p class="empty">불러오는 중</p>';
  if (!d.recorder) return '<p class="empty">강제청산 기록기 자료가 없습니다 (paperbot-liq)</p>';
  const tot = d.long_usd + d.short_usd, share = tot > 0 ? d.long_usd / tot : 0.5;
  const usdK = (x) => x >= 1e6 ? `$${(x / 1e6).toFixed(2)}M` : x >= 1e3 ? `$${(x / 1e3).toFixed(1)}K` : `$${fmt(x, 0)}`;
  const rows = d.rows.map((r) => `<tr><td class="l mono">${hms(r.ts)}</td>
    <td class="l ${r.liquidated === "long" ? "down" : "up"}">${r.liquidated === "long" ? "롱 청산" : "숏 청산"}</td>
    <td class="mono">${px(r.price)}</td><td class="mono">${r.usd >= 1e5 ? `<b>${usdK(r.usd)}</b>` : usdK(r.usd)}</td></tr>`).join("");
  return `<div class="p2h">최근 1시간 ${coin(d.symbol)} 강제청산 (바이낸스 전체)</div>
    <div class="bkbar"><span class="down">롱 ${usdK(d.long_usd)}</span><div class="liqbar"><i style="width:${(share * 100).toFixed(1)}%"></i></div><span class="up">숏 ${usdK(d.short_usd)}</span></div>
    ${rows ? `<table class="p2t"><thead><tr><th class="l">시각</th><th class="l">종류</th><th>가격</th><th>규모</th></tr></thead><tbody>${rows}</tbody></table>` : '<p class="empty">최근 기록 없음</p>'}
    <div class="p2n">롱 청산 = 롱 포지션이 강제로 팔림(가격 하락 쪽), 숏 청산 = 반대. 바이낸스가 코인별로 1초에 1건만 알려줘서 실제보다 적게 잡힙니다.</div>`;
}
function renderSide2() {
  const el = $("side2-body"); if (!el) return;
  el.innerHTML = state.side2 === "book" ? bookHtml(state.sym, 8) : liqRows();
}
seg("watch2-tabs", "t", (t) => { state.watch2 = t; if (t === "day") loadSum(); renderWatch2(); });
seg("side2-tabs", "t", (t) => { state.side2 = t; if (t === "liq") { p2.liq = null; loadLiq(); } renderSide2(); });
loadGh(); loadSum();
setInterval(() => { if (state.view === "trade") { renderSide2(); if (state.watch2 === "day") renderWatch2(); } }, 1000);
setInterval(() => { if (state.view === "trade") { loadGh(); loadSum(); } }, 60000);
setInterval(() => { if (state.view === "trade" && state.side2 === "liq") loadLiq(); }, 10000);
let p2sym = state.sym;
setInterval(() => { if (p2sym !== state.sym) { p2sym = state.sym; p2.liq = null; if (state.side2 === "liq") loadLiq(); renderWatch2(); } }, 500);
