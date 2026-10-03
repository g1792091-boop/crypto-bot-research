// ------------------------------------------------------------ market tab (/api/market)
// Outside context only: fear & greed, dominance, total market cap, US indexes and the registered US macro releases.
// Nothing here feeds the paper accounts.
const mk = {data: null, t: 0};
const FNG_CLS = (v) => v == null ? "" : v < 25 ? "down" : v < 45 ? "down" : v <= 55 ? "" : "up";

function spark(points, w = 220, h = 46) {
  if (!points || points.length < 2) return '<div class="muted" style="height:46px">—</div>';
  const xs = points.map((p) => p[0]), ys = points.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const sx = (x) => ((x - x0) / Math.max(1, x1 - x0) * (w - 2) + 1).toFixed(1);
  const sy = (y) => (h - 1 - (y - y0) / Math.max(1e-12, y1 - y0) * (h - 2)).toFixed(1);
  const up = ys[ys.length - 1] >= ys[0];
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="5일 흐름">
    <polyline fill="none" stroke="${up ? "var(--up)" : "var(--down)"}" stroke-width="1.5" points="${points.map((p) => sx(p[0]) + "," + sy(p[1])).join(" ")}"/></svg>`;
}
function bigNum(x) { return x == null ? "—" : x >= 1e12 ? `$${(x / 1e12).toFixed(2)}조` : x >= 1e9 ? `$${(x / 1e9).toFixed(1)}B` : `$${fmt(x, 0)}`; }

function renderMarket() {
  const d = mk.data, el = $("mk-body");
  if (!d) { el.innerHTML = '<p class="empty">불러오는 중</p>'; return; }
  const miss = (x, what) => !x || x.error ? `<div class="muted">${what}를 받지 못했습니다${x && x.error ? ` (${esc(x.error)})` : ""}</div>` : "";
  const stale = (x) => x && x.stale ? ' <small class="muted">(예전 값)</small>' : "";
  // fear & greed
  const f = d.fng || {}, fn = f.now;
  const fng = fn ? `<div class="mk-big ${FNG_CLS(fn.value)}">${fn.value}<small>/100</small></div>
      <div class="mk-lbl">${esc(fn.label_ko)}${stale(f)}</div>
      <div class="mk-row"><span>어제</span><b>${f.yesterday ? `${f.yesterday.value} · ${esc(f.yesterday.label_ko)}` : "—"}</b></div>
      <div class="mk-row"><span>1주 전</span><b>${f.week ? `${f.week.value} · ${esc(f.week.label_ko)}` : "—"}</b></div>
      <div class="mk-bar"><i style="left:${fn.value}%"></i></div>` : miss(f, "공포·탐욕 지수");
  // dominance
  const g = d.global || {};
  const dom = g.btc_dom != null ? `<div class="mk-big">${g.btc_dom.toFixed(1)}<small>%</small></div><div class="mk-lbl">비트코인 도미넌스${stale(g)}</div>
      <div class="mk-row"><span>이더리움</span><b>${g.eth_dom != null ? g.eth_dom.toFixed(1) + "%" : "—"}</b></div>
      <div class="mk-row"><span>코인 전체 시가총액</span><b>${bigNum(g.total_mcap)}</b></div>
      <div class="mk-row"><span>24시간</span><b class="${cls(g.mcap_chg_24h)}">${g.mcap_chg_24h != null ? pct(g.mcap_chg_24h / 100, 2) : "—"}</b></div>` : miss(g, "도미넌스");
  const ix = (d.indexes || []).map((x) => `<div class="mk-card">
      <div class="mk-name">${esc(x.name)} <small class="muted">${esc(x.symbol)}</small></div>
      ${x.price != null ? `<div class="mk-px">${x.symbol === "^TNX" ? x.price.toFixed(3) + "%" : fmt(x.price, 2)}
        <span class="${cls(x.chg)}">${x.chg != null ? pct(x.chg, 2) : ""}</span>${stale(x)}</div>${spark(x.points)}
        <div class="muted" style="font-size:10.5px">${x.ts ? "마지막 " + tsKo(x.ts) : ""} · 5일</div>` : miss(x, esc(x.name))}
    </div>`).join("");
  // macro calendar
  const now = Date.now();
  const evs = (d.events || []).map((e) => {
    const days = Math.ceil((e.ts_ms - now) / 864e5), past = e.ts_ms < now;
    return `<tr class="${past ? "muted" : ""}"><td class="l">${tsKo(e.ts_ms)}</td><td class="l">${esc(e.name_ko)}</td>
      <td>${past ? "지남" : days <= 0 ? '<b class="accent">오늘</b>' : "D-" + days}</td></tr>`;
  }).join("");
  $("mk-body").innerHTML = `
    <div class="mk-grid">
      <div class="mk-card"><div class="mk-name">공포·탐욕 지수 <small class="muted">alternative.me</small></div>${fng}</div>
      <div class="mk-card"><div class="mk-name">도미넌스 <small class="muted">CoinGecko</small></div>${dom}</div>
      ${ix}
    </div>
    <div class="mk-card mk-cal"><div class="mk-name">미국 경제발표 일정 <small class="muted">한국 시각 · 발표 앞뒤로 변동성이 커지는 때</small></div>
      ${evs ? `<table class="p2t"><thead><tr><th class="l">시각</th><th class="l">발표</th><th>남은 날</th></tr></thead><tbody>${evs}</tbody></table>`
        : `<p class="empty">등록된 일정이 없습니다 (data/macro_events.csv)</p>`}
      ${(d.events_problems || []).length ? `<div class="down" style="font-size:11px">일정 파일에서 읽지 못한 줄: ${d.events_problems.map(esc).join(" · ")}</div>` : ""}
    </div>
    <p class="muted" style="font-size:11px">참고용 바깥 자료입니다. 무료 공개 자료라 늦거나 비어 있을 수 있고(미국 지수는 장이 열린 시간에만 움직임), 195개 계좌의 매매에는 쓰이지 않습니다.</p>`;
}
async function loadMarket() {
  try { mk.data = await api("/api/market"); mk.t = Date.now(); } catch (e) { /* keep the last */ }
  if (state.view === "market") renderMarket();
}
setInterval(() => { if (state.view === "market") loadMarket(); }, 120000);
