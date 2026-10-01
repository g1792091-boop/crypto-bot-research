// 마켓: 도미넌스 · 매크로(나스닥 등) · 뉴스 · 경제지표 · 히트맵
import { $, api, big, busy, css, esc, fmt, makeChart, on, pct, state } from "./core.js";
import { newsRows, showOnChart } from "./trade.js";

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
    $("#heatmap").innerHTML = d.items.map((x) => `<div class="tile" data-sym="${x.symbol}" style="background:${heatColor(x.change_pct)}" title="거래대금 $${big(x.quote_volume)}">
      <div class="s">${x.symbol.replace("USDT", "")}</div><div class="c">${pct(x.change_pct)}</div></div>`).join("");
  }).catch((e) => ($("#heatmap").innerHTML = `<div class="empty" style="grid-column:1/-1">${esc(e.message)}</div>`));
  renderNews();
  if (!loaded) { loaded = true; loadMacro(); }
  api("/api/market/heatmap?limit=120").then((d) => treemap($("#treemap"), d.items))
    .catch((e) => ($("#treemap").innerHTML = `<div class="empty">${esc(e.message)}</div>`));
}

// 매크로: 자체 라인차트 (외부 위젯 없음)
const macroCharts = [];
async function loadMacro() {
  const grid = $("#macro-grid");
  grid.innerHTML = `<div class="panel"><div class="pb muted">매크로 지표 불러오는 중…</div></div>`;
  let d;
  try { d = await api("/api/macro"); } catch (e) { grid.innerHTML = `<div class="panel"><div class="pb muted">매크로 지표를 불러오지 못했습니다: ${esc(e.message)}</div></div>`; return; }
  macroCharts.splice(0).forEach((c) => c.remove());
  grid.innerHTML = d.items.map((x, i) => `<div class="panel"><div class="ph"><span class="t">${esc(x.name)}</span><div class="grow"></div>
      ${x.error ? `<span class="muted">불러오기 실패</span>` : `<b class="num">${fmt(x.last)}</b>
      <span class="${x.change_pct >= 0 ? "up" : "down"}" style="margin-left:6px">${pct(x.change_pct)}</span>
      <span class="muted" style="margin-left:6px">1M ${pct(x.change_1m_pct)}</span>`}</div>
      <div class="chart" id="macro-${i}" style="height:130px"></div></div>`).join("");
  d.items.forEach((x, i) => {
    if (!x.history.length) return;
    const ch = makeChart($(`#macro-${i}`), { timeScale: { timeVisible: false }, rightPriceScale: { borderVisible: false } });
    const up = x.history.at(-1).value >= x.history[0].value;
    const s = ch.addSeries(LightweightCharts.AreaSeries, { lineColor: css(up ? "--up" : "--down"), lineWidth: 2,
      topColor: up ? "rgba(8,153,129,.25)" : "rgba(242,54,69,.25)", bottomColor: "rgba(0,0,0,0)", priceLineVisible: false });
    s.setData(x.history);
    ch.timeScale().fitContent();
    macroCharts.push(ch);
  });
}

// 히트맵: 거래대금 크기의 사각형 트리맵 (squarify)
function treemap(el, items) {
  const W = el.clientWidth || 600, H = el.clientHeight || 360;
  const data = items.filter((x) => x.quote_volume > 0).slice(0, 100);
  const wt = (x) => Math.sqrt(x.quote_volume);          // 제곱근 — BTC 하나가 화면을 다 덮지 않게
  const total = data.reduce((a, x) => a + wt(x), 0) || 1;
  const nodes = data.map((x) => ({ x, a: (wt(x) / total) * W * H }));
  const out = [];
  const worst = (row, w) => { const s = row.reduce((a, n) => a + n.a, 0); const mx = Math.max(...row.map((n) => n.a)), mn = Math.min(...row.map((n) => n.a));
    return Math.max((w * w * mx) / (s * s), (s * s) / (w * w * mn)); };
  let rect = { x: 0, y: 0, w: W, h: H }, row = [], rest = nodes.slice();
  const layout = (row) => {
    const s = row.reduce((a, n) => a + n.a, 0);
    if (rect.w >= rect.h) { const cw = s / rect.h; let y = rect.y; row.forEach((n) => { const h = n.a / cw; out.push({ ...n, l: rect.x, t: y, w: cw, h }); y += h; }); rect = { x: rect.x + cw, y: rect.y, w: rect.w - cw, h: rect.h }; }
    else { const rh = s / rect.w; let x = rect.x; row.forEach((n) => { const w = n.a / rh; out.push({ ...n, l: x, t: rect.y, w, h: rh }); x += w; }); rect = { x: rect.x, y: rect.y + rh, w: rect.w, h: rect.h - rh }; }
  };
  while (rest.length) {
    const n = rest[0], side = Math.min(rect.w, rect.h);
    if (!row.length || worst([...row, n], side) <= worst(row, side)) { row.push(n); rest.shift(); }
    else { layout(row); row = []; }
  }
  if (row.length) layout(row);
  el.innerHTML = out.map(({ x, l, t, w, h }) => `<div class="tm" data-sym="${x.symbol}" title="${x.symbol} · 거래대금 $${big(x.quote_volume)}"
    style="left:${l}px;top:${t}px;width:${w}px;height:${h}px;background:${heatColor(x.change_pct)};font-size:${Math.max(9, Math.min(22, Math.sqrt(w * h) / 6))}px">
    ${w > 34 && h > 22 ? `<b>${x.symbol.replace("USDT", "")}</b>${h > 38 ? `<span>${pct(x.change_pct)}</span>` : ""}` : ""}</div>`).join("");
}

let fngChart, cgChart;
function renderFng(f) {
  const c = f.value < 45 ? "down" : f.value > 55 ? "up" : "accent";
  const prev = f.previous || {};
  $("#fng-now").innerHTML = `<div class="fng"><div class="big ${c}">${f.value}</div><div>
      <div class="${c}" style="font-weight:600;font-size:14px">${f.label}</div>
      <div class="fng-bar" style="margin:8px 0 4px"><i style="left:calc(${f.value}% - 1px)"></i></div>
      <div class="row muted" style="justify-content:space-between;font-size:10.5px"><span>극단적 공포</span><span>중립</span><span>극단적 탐욕</span></div>
      <div class="dim" style="margin-top:6px">어제 ${prev.yesterday ?? "–"} · 1주 전 ${prev.week ?? "–"} · 1달 전 ${prev.month ?? "–"}</div></div></div>`;
  fngChart?.remove();
  fngChart = makeChart($("#fng-chart"), { timeScale: { timeVisible: false } });
  const s = fngChart.addSeries(LightweightCharts.LineSeries, { color: css("--accent"), lineWidth: 2, priceFormat: { type: "price", precision: 0, minMove: 1 } });
  s.setData(f.history);
  [25, 50, 75].forEach((p) => s.createPriceLine({ price: p, color: "rgba(164,172,182,.3)", lineStyle: 2, lineWidth: 1, axisLabelVisible: false }));
  fngChart.timeScale().fitContent();
}

// CoinGlass 응답은 지표마다 형식이 달라서, 시간 + 숫자 필드를 찾아 선으로 그린다
function toSeries(data) {
  const rows = Array.isArray(data) ? data : Array.isArray(data?.data_list) ? data.data_list.map((v, i) => ({ time: data.time_list?.[i], value: v })) : [];
  const tkey = rows[0] && ["time", "timestamp", "date", "t"].find((k) => k in rows[0]);
  if (!tkey) return {};
  const keys = Object.keys(rows[0]).filter((k) => k !== tkey && typeof rows[0][k] !== "object" && !Number.isNaN(parseFloat(rows[0][k]))).slice(0, 3);
  const out = {};
  keys.forEach((k) => (out[k] = rows.map((r) => ({ time: Math.floor(+r[tkey] > 1e11 ? +r[tkey] / 1000 : +r[tkey]), value: parseFloat(r[k]) }))
    .filter((p) => p.time && Number.isFinite(p.value)).sort((a, b) => a.time - b.time)
    .filter((p, i, arr) => i === 0 || p.time > arr[i - 1].time)));
  return out;
}
async function loadCg(list) {
  const name = $("#cg-sel").value;
  cgChart?.remove(); cgChart = null;
  if (!list.enabled) {
    $("#cg-note").innerHTML = "코인글라스 지표(AHR999, 강세장 고점 지표, 퓨엘 멀티플, ETF 순유입 등)는 CoinGlass API 키가 필요합니다. settings.txt 의 COINGLASS_API_KEY 에 넣으세요.<br>키 없이도 차트의 '지표 +' 에서 OI · 펀딩 · 롱숏 · 테이커 · 코인베이스 프리미엄은 바로 쓸 수 있습니다.";
    return;
  }
  $("#cg-note").textContent = "불러오는 중…";
  try {
    const d = await api(`/api/cg-index/${name}`);
    const ser = toSeries(d.data);
    const keys = Object.keys(ser);
    if (!keys.length) { $("#cg-note").textContent = "그릴 수 있는 데이터 형식이 아닙니다."; return; }
    $("#cg-note").textContent = keys.join(" · ");
    cgChart = makeChart($("#cg-chart"), { timeScale: { timeVisible: false } });
    const colors = [css("--accent"), css("--s1"), css("--s3")];
    keys.forEach((k, i) => cgChart.addSeries(LightweightCharts.LineSeries, { color: colors[i], lineWidth: 2, priceScaleId: i ? "s" + i : "right" }).setData(ser[k]));
    cgChart.timeScale().fitContent();
  } catch (e) { $("#cg-note").textContent = "CoinGlass 요청 실패: " + e.message; }
}

export function initMarket() {
  // 숨겨진 탭에서는 차트 크기가 0이라, 마켓 탭을 열 때 그린다
  on("fng", (f) => $("#v-market").classList.contains("on") && renderFng(f));
  on("view", (v) => v === "market" && state.fng && renderFng(state.fng));
  api("/api/cg-index").then((list) => {
    $("#cg-sel").innerHTML = list.items.map((x) => `<option value="${x.name}">${esc(x.title)}</option>`).join("");
    $("#cg-sel").onchange = () => loadCg(list);
    on("view", (v) => v === "market" && !cgChart && loadCg(list));
  });
  $("#news-imp").onchange = renderNews;
  ["#heatmap", "#treemap"].forEach((q) => $(q).addEventListener("click", (e) => {
    const t = e.target.closest("[data-sym]");
    if (t) showOnChart(t.dataset.sym);
  }));
  on("news", () => { if ($("#v-market").classList.contains("on")) renderNews(); });
  on("calendar", renderCalendar);
  on("view", (v) => v === "market" && load());
  if (state.status?.llm) {
    const b = $("#news-ai");
    b.hidden = false;
    b.onclick = () => busy(b, async () => { brief = (await api("/api/news/brief?limit=30")).items; renderNews(); });
  }
}
