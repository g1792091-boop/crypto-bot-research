// 마켓: 도미넌스 · 매크로(나스닥 등) · 뉴스 · 경제지표 · 히트맵
import { $, api, big, busy, css, embedTvWidget, esc, fmt, on, pct, state, tvTheme } from "./core.js";
import { newsRows } from "./trade.js";

const MACRO_MINI = [
  ["NASDAQ:NDX", "나스닥100"], ["SP:SPX", "S&P500"], ["TVC:DXY", "달러인덱스"],
  ["TVC:US10Y", "미 10년물 금리"], ["TVC:GOLD", "금"], ["CRYPTOCAP:BTC.D", "BTC 도미넌스"],
];
let loaded = false, brief = null;

function heatColor(p) {
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const t = Math.min(1, Math.abs(p) / 8);
  const [a, b] = [hex(css("--panel-2")), hex(p >= 0 ? css("--up") : css("--down"))];
  return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * t)).join(",")})`;
}

function renderNews() {
  const imp = $("#news-imp").checked;
  const items = (state.news || []).filter((n) => !imp || n.important);
  $("#news-full").innerHTML = newsRows(items, 80, brief);
}

function renderCalendar(items) {
  $("#cal-table").innerHTML = items.length
    ? `<tr><th>일시 (한국)</th><th>지표</th><th>예상</th><th>이전</th></tr>` + items.map((e) => {
      const t = Date.parse(e.date), past = t < Date.now();
      return `<tr class="${past ? "" : ""}"><td class="${past ? "muted" : ""}">${t ? new Date(t).toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false }) : "–"}</td>
        <td style="text-align:left;${past ? "color:var(--muted)" : ""}">${esc(e.title)}</td><td>${esc(e.forecast || "–")}</td><td>${esc(e.previous || "–")}</td></tr>`;
    }).join("")
    : `<tr><td class="muted">일정을 불러오지 못했습니다.</td></tr>`;
}

async function load() {
  api("/api/market/dominance").then((d) => {
    const st = (k, v, c = "") => `<div class="stat"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`;
    $("#dom-stats").innerHTML = st("전체 시가총액", "$" + big(d.total_market_cap_usd)) + st("24h 변동", pct(d.market_cap_change_24h_pct), d.market_cap_change_24h_pct > 0 ? "up" : "down") +
      st("BTC", `${fmt(d.btc_dominance)}%`) + st("ETH", `${fmt(d.eth_dominance)}%`) + st("스테이블코인", `${fmt(d.stablecoin_dominance)}%`) + st("알트 (기타)", `${fmt(d.others_dominance)}%`);
  }).catch((e) => ($("#dom-stats").innerHTML = `<div class="stat" style="grid-column:1/-1"><div class="k">도미넌스를 불러오지 못했습니다</div><div class="muted">${esc(e.message)}</div></div>`));
  api("/api/market/heatmap?limit=60").then((d) => {
    $("#heatmap").innerHTML = d.items.map((x) => `<div class="tile" style="background:${heatColor(x.change_pct)}" title="거래대금 $${big(x.quote_volume)}">
      <div class="s">${x.symbol.replace("USDT", "")}</div><div class="c">${pct(x.change_pct)}</div></div>`).join("");
  }).catch((e) => ($("#heatmap").innerHTML = `<div class="empty" style="grid-column:1/-1">${esc(e.message)}</div>`));
  renderNews();
  if (!loaded) {
    loaded = true;
    const th = tvTheme();
    $("#macro-grid").innerHTML = MACRO_MINI.map(([s, l], i) => `<div class="panel"><div class="ph"><span class="t">${l}</span></div><div class="tv-embed sm" id="mini-${i}"></div></div>`).join("");
    MACRO_MINI.forEach(([s], i) => embedTvWidget($(`#mini-${i}`), "embed-widget-mini-symbol-overview.js",
      { ...th, symbol: s, dateRange: "3M", chartOnly: false, trendLineColor: css("--s1"), underLineColor: "rgba(57,135,229,.15)" }));
    embedTvWidget($("#tv-heatmap"), "embed-widget-crypto-coins-heatmap.js", { ...th, dataSource: "Crypto", blockSize: "market_cap_calc",
      blockColor: "24h_close_change|5", hasTopBar: false, isDataSetEnabled: false, isZoomEnabled: true, hasSymbolTooltip: true });
    embedTvWidget($("#tv-calendar"), "embed-widget-events.js", { ...th, importanceFilter: "0,1", countryFilter: "us,eu,cn,jp,kr" });
  }
}

export function initMarket() {
  $("#news-imp").onchange = renderNews;
  on("news", () => { if ($("#v-market").classList.contains("on")) renderNews(); });
  on("calendar", renderCalendar);
  on("view", (v) => v === "market" && load());
  if (state.status?.llm) {
    const b = $("#news-ai");
    b.hidden = false;
    b.onclick = () => busy(b, async () => { brief = (await api("/api/news/brief?limit=30")).items; renderNews(); });
  }
}
