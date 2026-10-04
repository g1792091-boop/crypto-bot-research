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
  const ta = (c) => {   // GH Coin's TA rating (4h, else 1h): buy / sell / neutral words from its own ta_rating.js
    const r = (c.rating || {})["240"] || (c.rating || {})["60"];
    return r && r.label ? `<span class="${r.all > 0 ? "up" : r.all < 0 ? "down" : "muted"}">${esc(r.label)}</span>` : "—";
  };
  return `<table class="p2t"><thead><tr><th class="l">코인</th><th class="l">GH Coin 판단</th><th>확신</th><th title="GH Coin 보조지표 종합 평가 (4시간봉)">지표</th></tr></thead><tbody>` +
    TRADE_SYMS.map((s) => {
      const c = g.coins[s];
      if (!c) return `<tr><td class="l"><b>${coin(s)}</b></td><td class="l muted" colspan="3">${esc((g.errors || {})[s] ? "가격 못 받음" : "—")}</td></tr>`;
      return `<tr class="click ${s === state.sym ? "sel" : ""}" data-gs="${s}" title="${esc([c.regime, c.why].filter(Boolean).join(" · "))}"><td class="l"><b>${coin(s)}</b></td>
        <td class="l"><span class="${GH_CLS[c.state] || "muted"}">${esc(GH_STATE_KO[c.state] || c.state)}</span></td>
        <td class="mono">${c.conf == null ? "—" : Math.round(c.conf)}</td><td>${ta(c)}</td></tr>`;
    }).join("") + "</tbody></table>" +
    `<div class="p2n">${g.alive ? "5분마다 갱신" : "기록기가 15분 넘게 조용함"} · 누르면 그 코인 차트에 GH Coin 선 · 기록만 하는 참고용 (${RUN.accounts}개 계좌와 무관)</div>`;
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
  // D-day by the Korea calendar day: an event later today is "오늘", tomorrow's is D-1
  const kday = (ms) => Math.floor((ms + 9 * 3.6e6) / 864e5);
  if (ev && ev.length) ev.slice(0, 3).forEach((e) => {
    const d = kday(e.ts_ms) - kday(now);
    out += kv(esc(e.name_ko), `${tsKo(e.ts_ms)} (${d <= 0 ? "오늘" : "D-" + d})`);
  });
  else if (s) out += kv("미국 경제발표", '<span class="muted">등록된 일정 없음</span>');
  if (s && s.next_checkpoint) {
    const d = kday(s.next_checkpoint.ts) - kday(now);
    out += kv(`${s.next_checkpoint.day}일째 판정`, `${tsKo(s.next_checkpoint.ts)} (${d <= 0 ? "오늘" : "D-" + d})`);
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
  // the recorder writes every few seconds on a normal market: 10 quiet minutes means it has stopped
  const quiet = d.last_any ? Math.floor((Date.now() - d.last_any) / 6e4) : null;
  const warn = quiet != null && quiet >= 10 ? `<div class="alwarn">강제청산 기록기가 ${quiet}분째 조용합니다. 아래 숫자는 그 전까지의 기록입니다 (서버: systemctl status paperbot-liq)</div>` : "";
  const tot = d.long_usd + d.short_usd, share = tot > 0 ? d.long_usd / tot : 0.5;
  const usdK = (x) => x >= 1e6 ? `$${(x / 1e6).toFixed(2)}M` : x >= 1e3 ? `$${(x / 1e3).toFixed(1)}K` : `$${fmt(x, 0)}`;
  const rows = d.rows.map((r) => `<tr><td class="l mono">${hms(r.ts)}</td>
    <td class="l ${r.liquidated === "long" ? "down" : "up"}">${r.liquidated === "long" ? "롱 청산" : "숏 청산"}</td>
    <td class="mono">${px(r.price)}</td><td class="mono">${r.usd >= 1e5 ? `<b>${usdK(r.usd)}</b>` : usdK(r.usd)}</td></tr>`).join("");
  return `${warn}<div class="p2h">최근 1시간 ${coin(d.symbol)} 강제청산 (바이낸스 전체, ${d.n || 0}건)</div>
    <div class="bkbar"><span class="down">롱 ${usdK(d.long_usd)}</span><div class="liqbar"><i style="width:${(share * 100).toFixed(1)}%"></i></div><span class="up">숏 ${usdK(d.short_usd)}</span></div>
    ${rows ? `<table class="p2t"><thead><tr><th class="l">시각</th><th class="l">종류</th><th>가격</th><th>규모</th></tr></thead><tbody>${rows}</tbody></table>` : '<p class="empty">최근 기록 없음</p>'}
    <div class="p2n">롱 청산 = 롱 포지션이 강제로 팔림(가격 하락 쪽), 숏 청산 = 반대. 바이낸스가 코인별로 1초에 1건만 알려줘서 실제보다 적게 잡힙니다.</div>`;
}
// ------------------------------------------------------------ price alerts (inbox.db; paperbot-tgtrades sends them)
p2.alerts = null;
let alines = [];
async function loadAlerts() {
  try { p2.alerts = await api("/api/price-alerts"); } catch (e) { p2.alerts = null; }
  drawAlertLines();
  if (state.view === "trade" && state.side2 === "alerts") renderAlerts(false);
}
function drawAlertLines() {   // armed alerts of the chart's coin as dotted lines
  if (!tseries) return;
  alines.forEach((l) => { try { tseries.removePriceLine(l); } catch (e) { /* gone */ } }); alines = [];
  for (const a of (p2.alerts && p2.alerts.alerts) || []) {
    if (a.symbol !== state.sym || !a.armed) continue;
    alines.push(tseries.createPriceLine({price: a.price, color: css("--accent"), lineWidth: 1, lineStyle: 1,
      title: `🔔 알림 ${a.direction === "above" ? "↑" : "↓"}`}));
  }
}
function renderAlerts(force) {
  const el = $("side2-body"); if (!el) return;
  if (!force && el.contains(document.activeElement)) return;      // never wipe what the owner is typing
  const d = p2.alerts, last = (state.tick[state.sym] || {}).c || state.mark[state.sym];
  const rows = ((d && d.alerts) || []).slice().sort((x, y) => (x.symbol === state.sym ? 0 : 1) - (y.symbol === state.sym ? 0 : 1) || y.id - x.id);
  el.innerHTML = `<div class="p2h">${coin(state.sym)} 가격이 닿으면 텔레그램으로 알림 (소리 있음, 한 번 울리면 꺼짐)</div>
    <div class="alform"><input id="al-px" inputmode="decimal" placeholder="${last ? px(last) : "가격"}" aria-label="알림 가격">
      <input id="al-note" maxlength="100" placeholder="메모 (선택)" aria-label="메모"><button id="al-add">알림 걸기</button></div>
    <div class="p2n" id="al-msg">${last ? `지금 ${px(last)} · 지금보다 높게 적으면 오를 때, 낮게 적으면 내릴 때 울립니다` : ""}</div>
    ${d && !d.sender_alive ? `<div class="alwarn">텔레그램 보내는 프로그램(paperbot-tgtrades)이 꺼져 있어 알림이 가지 않습니다. 서버에서 <code>sudo systemctl enable --now paperbot-tgtrades</code></div>` : ""}
    ${rows.length ? `<table class="p2t"><thead><tr><th class="l">코인</th><th>가격</th><th class="l">상태</th><th></th></tr></thead><tbody>${rows.map((a) => `<tr>
      <td class="l"><b>${coin(a.symbol)}</b> ${a.direction === "above" ? "↑" : "↓"}${a.note ? ` <small class="muted">${esc(a.note)}</small>` : ""}</td>
      <td class="mono">${px(a.price)}</td>
      <td class="l">${a.armed ? '<span class="accent">대기 중</span>' : `<span class="muted">울림 ${hms(a.fired_ts)}</span>`}</td>
      <td>${a.armed ? "" : `<button class="mini" data-al-rearm="${a.id}">다시 켜기</button> `}<button class="mini" data-al-del="${a.id}">지우기</button></td></tr>`).join("")}</tbody></table>`
      : '<p class="empty">걸어 둔 알림이 없습니다</p>'}`;
  const msg = (t) => { $("al-msg").textContent = t; };
  $("al-add").onclick = async () => {
    const v = parseFloat(String($("al-px").value).replace(/,/g, ""));
    if (!(v > 0)) { msg("가격을 숫자로 적어 주세요"); return; }
    try {
      const r = await apiPost("/api/price-alerts", {symbol: state.sym, price: v, note: $("al-note").value});
      await loadAlerts(); renderAlerts(true);
      $("al-msg").textContent = `${coin(state.sym)} ${px(v)} ${r.direction === "above" ? "위로 오르면" : "아래로 내리면"} 알립니다`;
    } catch (e) { msg(e.message); }
  };
  el.querySelectorAll("[data-al-del]").forEach((b) => b.onclick = async () => {
    try { await apiPost(`/api/price-alerts/${b.dataset.alDel}/delete`, {}); await loadAlerts(); renderAlerts(true); } catch (e) { toast(e.message); }
  });
  el.querySelectorAll("[data-al-rearm]").forEach((b) => b.onclick = async () => {
    try { await apiPost(`/api/price-alerts/${b.dataset.alRearm}/rearm`, {}); await loadAlerts(); renderAlerts(true); } catch (e) { toast(e.message); }
  });
}
function renderSide2() {
  const el = $("side2-body"); if (!el) return;
  if (state.side2 === "alerts") return;             // drawn on load and on every change (never every second)
  el.innerHTML = state.side2 === "book" ? bookHtml(state.sym, 8) : liqRows();
}
seg("watch2-tabs", "t", (t) => { state.watch2 = t; if (t === "day") loadSum(); renderWatch2(); });
seg("side2-tabs", "t", (t) => { state.side2 = t; if (t === "liq") { p2.liq = null; loadLiq(); } if (t === "alerts") { loadAlerts(); renderAlerts(true); return; } renderSide2(); });
loadGh(); loadSum();
setInterval(() => { if (state.view === "trade") { renderSide2(); if (state.watch2 === "day") renderWatch2(); } }, 1000);
setInterval(() => { if (state.view === "trade") { loadGh(); loadSum(); } }, 60000);
setInterval(() => { if (state.view === "trade" && state.side2 === "liq") loadLiq(); }, 10000);
let p2sym = state.sym;
setInterval(() => { if (p2sym !== state.sym) { p2sym = state.sym; p2.liq = null; if (state.side2 === "liq") loadLiq(); renderWatch2(); drawAlertLines(); if (state.side2 === "alerts") renderAlerts(true); } }, 500);
setInterval(() => { if (state.view === "trade") loadAlerts(); }, 15000);
loadAlerts();
