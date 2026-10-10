// 후보 리그 dashboard: the engine's snapshots (/api/league, /api/trades/<id>, /api/fills; every 30 s) and a 터미널 on
// live Binance data that the dashboard server fetches and caches (/api/live every 5 s, /api/klines every 10 s; only
// while that screen is on). Charts: lightweight-charts v4 (/static/vendor), Korea time on every axis.
"use strict";

const VERDICT = { early: "아직 판단 이름", ok: "기준 통과", not_yet: "기준 미달" };
const ROLE = { cand: "후보", base: "기본값", flip: "동전 던지기" };
const REASON = { SL: "손절", TP: "익절", LOCK: "사다리 익절", LIQ: "강제청산" };
const COINS = ["BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD"];
const TFS = ["15m", "30m", "1h", "4h"];
const TF_MS = { "15m": 900e3, "30m": 1800e3, "1h": 3600e3, "4h": 14400e3 };
const TABS = ["rank", "term", "open", "fills", "status"];
const COL = { up: "#34d39a", down: "#f4646b", long: "#5aa9ff", short: "#ffb347", exit: "#e8ecf1",
  surface: "#1a1e23", grid: "#262c33", line: "#2c333b", ink2: "#bcc3cc" };

const S = { doc: null, fills: [], live: null, tab: "rank", detail: null, rankTf: "all", rankKind: "all",
  coin: "BTCUSD", tf: "15m", acct: null, fAcct: "all", trades: {}, focus: null };
const T = { chart: null, candles: null, vol: null, key: null, bars: [], lines: [], timer: null, liveTimer: null };

// ------------------------------------------------------------------------------------------------ small helpers
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") e.className = v; else if (k === "text") e.textContent = v; else e.setAttribute(k, v);
  }
  for (const k of kids) if (k != null) e.append(k);
  return e;
};
const $ = (id) => document.getElementById(id);
const pct = (x, d = 2) => (x == null ? "-" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(d)}%`);
const usd = (x) => (x == null ? "-" : `${x < 0 ? "-" : ""}$${Math.abs(Math.round(x)).toLocaleString("en-US")}`);
const two = (x) => String(x).padStart(2, "0");
const kstDate = (ms) => new Date(ms + 9 * 3600e3);
const kst = (ms) => {
  if (!ms) return "-";
  const d = kstDate(ms);
  return `${two(d.getUTCMonth() + 1)}-${two(d.getUTCDate())} ${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`;
};
const kstDay = (ms) => { const d = kstDate(ms); return `${d.getUTCFullYear()}-${two(d.getUTCMonth() + 1)}-${two(d.getUTCDate())}`; };
const sign = (x) => (x == null ? "" : x > 0 ? "pos" : x < 0 ? "neg" : "");
const priceDec = (p) => { const a = Math.abs(Number(p) || 0); return a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1; };
const price = (p) => (p == null ? "-" : Number(p).toLocaleString("en-US",
  { minimumFractionDigits: priceDec(p), maximumFractionDigits: priceDec(p) }));
const big = (x) => (x == null ? "-" : x >= 1e9 ? `$${(x / 1e9).toFixed(2)}B` : x >= 1e6 ? `$${(x / 1e6).toFixed(1)}M` : usd(x));
const short = (coin) => coin.replace(/USDT?$/, "");
const coinOf = (sym) => (sym || "").replace(/T$/, "");
const side = (s) => (s > 0 ? "롱" : "숏");
const reason = (r) => REASON[r] || r || "-";
const winRate = (a) => (a.trades ? `${Math.round((100 * a.wins) / a.trades)}%` : "-");
const label = (a) => (a.role === "cand"
  ? `${a.name} · ${a.tf}${a.source && a.source.rank > 1 ? ` #${a.source.rank}` : ""}`
  : `${ROLE[a.role]} · ${a.name} · ${a.tf}`);
const acctById = (id) => (S.doc ? S.doc.accounts.find((a) => a.id === id) : null);
const store = {
  get() { try { return JSON.parse(localStorage.getItem("candleague-ui") || "{}"); } catch (e) { return {}; } },
  save() {
    try {
      localStorage.setItem("candleague-ui", JSON.stringify({ tab: S.tab, coin: S.coin, tf: S.tf, acct: S.acct,
        rankTf: S.rankTf, rankKind: S.rankKind, fAcct: S.fAcct }));
    } catch (e) { /* private window: not remembered */ }
  },
};

async function getJSON(url) {
  const r = await fetch(url, { credentials: "same-origin" });
  if (r.status === 401) { location.href = "/login"; throw new Error("login"); }
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}
function td(text, cls = "") { return el("td", { class: cls, text }); }
function sideBadge(s) { return el("span", { class: `badge ${s > 0 ? "b-long" : "b-short"}`, text: side(s) }); }
function seg(box, items, current, onPick) {
  box.replaceChildren(...items.map(([v, text]) => {
    const b = el("button", { type: "button", "aria-pressed": String(v === current), text });
    b.addEventListener("click", () => onPick(v));
    return b;
  }));
}
function emptyRow(t, n, text) { t.append(el("tr", {}, el("td", { colspan: String(n), class: "empty", text }))); }

// ------------------------------------------------------------------------------------------------ summary cards
function renderCards() {
  const doc = S.doc, box = $("cards");
  const cands = doc.accounts.filter((a) => a.role === "cand");
  const v = { ok: 0, not_yet: 0, early: 0 };
  for (const c of cands) v[(doc.judge[c.id] || {}).verdict || "early"] += 1;
  const open = doc.accounts.filter((a) => a.open);
  const openCand = open.filter((a) => a.role === "cand");
  const today = kstDay(Date.now());
  const fillsToday = S.fills.filter((f) => f.exit_time && kstDay(f.exit_time) === today);
  const candToday = fillsToday.filter((f) => (acctById(f.account) || {}).role === "cand");
  const days = Math.max(1, Math.floor((doc.done_ms - doc.start_ms) / 86400e3) + 1);
  const lagMin = Math.round(doc.lag_s / 60);
  const card = (k, val, sub, cls = "") => el("div", { class: `card ${cls}` },
    el("div", { class: "k", text: k }), el("div", { class: "v", text: val }), el("div", { class: "s", text: sub }));
  box.replaceChildren(
    card("후보", String(cands.length), `계좌 ${doc.accounts.length}개 (기본값 · 동전 포함)`),
    card("기준 통과", String(v.ok), `미달 ${v.not_yet} · 아직 판단 이름 ${v.early}`, v.ok ? "good" : ""),
    card("열린 포지션", String(open.length), `후보 ${openCand.length} · 롱 ${open.filter((a) => a.open.side > 0).length}`
      + ` / 숏 ${open.filter((a) => a.open.side < 0).length}`),
    card("오늘 끝난 거래", String(fillsToday.length), `후보 계좌 ${candToday.length}건 (KST 기준)`),
    card("리그", `${days}일째`, "10월 1일부터 종이 매매"),
    card("자료", kst(doc.done_ms).slice(6), lagMin > 30 ? `${lagMin}분 늦음 · 확인 필요` : `지연 ${lagMin}분 · 5분마다`,
      lagMin > 30 ? "warn" : ""));
  const f = $("fresh");
  f.textContent = `${kst(doc.done_ms)} KST까지`;
  f.classList.toggle("late", lagMin > 30);
}

// ------------------------------------------------------------------------------------------------ 순위표
function renderRankFilters() {
  const doc = S.doc, box = $("rank-filters");
  const tfs = TFS.filter((t) => doc.accounts.some((a) => a.role === "cand" && a.tf === t));
  const kinds = [...new Set(doc.accounts.filter((a) => a.role === "cand").map((a) => a.kind))];
  const tfBox = el("div", { class: "seg", role: "group", "aria-label": "봉" });
  const kindBox = el("div", { class: "seg", role: "group", "aria-label": "종류" });
  seg(tfBox, [["all", "봉 전체"], ...tfs.map((t) => [t, t])], S.rankTf, (v) => { S.rankTf = v; store.save(); renderRankFilters(); renderRank(); });
  seg(kindBox, [["all", "종류 전체"], ...kinds.map((k) => [k, k === "ds" ? "딥시크" : "기존 36"])], S.rankKind,
    (v) => { S.rankKind = v; store.save(); renderRankFilters(); renderRank(); });
  box.replaceChildren(tfBox, kindBox);
}

function renderRank() {
  const doc = S.doc, t = $("rank");
  t.replaceChildren();
  const acc = Object.fromEntries(doc.accounts.map((a) => [a.id, a]));
  const cands = doc.accounts.filter((a) => a.role === "cand" && (S.rankTf === "all" || a.tf === S.rankTf)
      && (S.rankKind === "all" || a.kind === S.rankKind))
    .sort((a, b) => (b.mean_ret ?? -1e9) - (a.mean_ret ?? -1e9) || b.trades - a.trades);
  t.append(el("thead", {}, el("tr", {},
    ...["매매법 · 봉", "익절 · 손절", "거래", "승률", "한 번 평균", "잔고", "최대 낙폭", "판정"].map((h, i) =>
      el("th", { class: i < 2 ? "l" : "", text: h })))));
  const body = el("tbody");
  if (!cands.length) emptyRow(body, 8, doc.accounts.length ? "이 조건의 후보가 없습니다" : "후보가 아직 없습니다");
  for (const c of cands) {
    const j = doc.judge[c.id] || {};
    const row = el("tr", { class: "cand", tabindex: "0" },
      el("td", { class: "l" }, el("span", { class: "sw sw-cand" }), label(c), c.open ? el("span", { class: "dot", title: "포지션 열림" }) : null),
      td(c.exit_ko, "l"), td(String(c.trades)), td(winRate(c)),
      td(pct(c.mean_ret), sign(c.mean_ret)), td(c.kind === "ds" && c.wallet == null ? "숨김" : usd(c.wallet)),
      td(c.max_dd == null ? "-" : `${(c.max_dd * 100).toFixed(1)}%`),
      el("td", { class: `v-${j.verdict || "early"}` }, VERDICT[j.verdict] || "-",
        j.band && j.band.below ? el("span", { class: "warn small", text: " · 예상보다 아래" }) : null));
    row.addEventListener("click", () => openDetail(c.id));
    row.addEventListener("keydown", (e) => { if (e.key === "Enter") openDetail(c.id); });
    body.append(row);
    for (const [role, id] of [["base", `base-${c.kind}-${c.name}-${c.tf}`], ["flip", `${c.id}-flip`]]) {
      const r = acc[id];
      if (!r) continue;
      body.append(el("tr", { class: "ref" },
        el("td", { class: "l" }, el("span", { class: `sw sw-${role}` }), ROLE[role]),
        td(r.exit_ko, "l"), td(String(r.trades)), td(winRate(r)),
        td(pct(r.mean_ret), sign(r.mean_ret)), td(r.wallet == null ? "-" : usd(r.wallet)),
        td(r.max_dd == null ? "-" : `${(r.max_dd * 100).toFixed(1)}%`), td(r.bust ? "파산" : "")));
    }
  }
  t.append(body);
}

// ------------------------------------------------------------------------------------------------ 지금 포지션
function liveRow(coin) { return S.live && S.live.coins ? S.live.coins.find((c) => c.coin === coin) : null; }
function moved(o) {
  const lr = liveRow(coinOf(o.symbol));
  return o.entry == null || !lr || lr.price == null ? null : o.side * (lr.price / o.entry - 1);
}

function renderOpen() {
  const t = $("open");
  t.replaceChildren(el("thead", {}, el("tr", {}, ...["계좌", "코인", "방향", "진입가", "지금 가격 변화", "손절", "익절", "진입 (KST)"]
    .map((h, i) => el("th", { class: i < 3 ? "l" : "", text: h })))));
  const body = el("tbody");
  const open = S.doc.accounts.filter((a) => a.open);
  if (!open.length) emptyRow(body, 8, "열린 포지션이 없습니다");
  for (const a of open) {
    const o = a.open, m = moved(o);
    const row = el("tr", { class: "cand", tabindex: "0", title: "터미널에서 보기" },
      el("td", { class: "l" }, el("span", { class: `sw sw-${a.role}` }), label(a)), td(short(o.symbol), "l"),
      el("td", { class: "l" }, sideBadge(o.side)), td(o.entry == null ? "숨김" : price(o.entry)), td(pct(m), sign(m)),
      td(o.stop == null ? "-" : price(o.stop)), td(o.tp == null ? "-" : price(o.tp)), td(kst(o.since)));
    const go = () => toTerminal(a.id, coinOf(o.symbol));
    row.addEventListener("click", go);
    row.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    body.append(row);
  }
  t.append(body);
}

// ------------------------------------------------------------------------------------------------ 거래 기록
function fillRow(f, withAcct = true) {
  const a = acctById(f.account);
  const tr = el("tr", { class: "cand", tabindex: "0", title: "터미널에서 이 거래 보기" },
    td(kst(f.exit_time), "l"),
    withAcct ? el("td", { class: "l" }, el("span", { class: `sw sw-${a ? a.role : "cand"}` }), a ? label(a) : f.account) : null,
    td(short(f.symbol || ""), "l"), el("td", { class: "l" }, sideBadge(f.side)),
    td(f.entry_price == null ? "숨김" : price(f.entry_price)), td(f.exit_price == null ? "숨김" : price(f.exit_price)),
    td(reason(f.exit_reason)), td(f.leverage ? `${f.leverage}x` : "-"), td(pct(f.roe, 1), sign(f.roe)),
    td(f.pnl == null ? "숨김" : usd(f.pnl), sign(f.pnl)));
  const go = () => toTerminal(f.account || S.acct, coinOf(f.symbol), f);
  tr.addEventListener("click", go);
  tr.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  return tr;
}
const FILL_HEAD = ["청산 (KST)", "계좌", "코인", "방향", "진입가", "청산가", "이유", "배수", "수익률", "손익"];

function renderFills() {
  const sel = $("f-acct");
  fillAcctSelect(sel, S.fAcct, true);
  const t = $("fills");
  t.replaceChildren(el("thead", {}, el("tr", {}, ...FILL_HEAD.map((h, i) => el("th", { class: i < 4 ? "l" : "", text: h })))));
  const body = el("tbody");
  const rows = S.fills.filter((f) => S.fAcct === "all" || (S.fAcct === "cand" ? (acctById(f.account) || {}).role === "cand"
    : f.account === S.fAcct));
  if (!rows.length) emptyRow(body, 10, "아직 끝난 거래가 없습니다");
  for (const f of rows.slice(0, 300)) body.append(fillRow(f));
  t.append(body);
}

function fillAcctSelect(sel, current, withAll) {
  const doc = S.doc;
  const groups = [["cand", "후보"], ["base", "기본값"], ["flip", "동전 던지기"]];
  const opts = [];
  if (withAll) opts.push(el("option", { value: "all", text: "전체 계좌" }), el("option", { value: "cand", text: "후보 계좌만" }));
  for (const [role, name] of groups) {
    const g = el("optgroup", { label: name });
    for (const a of doc.accounts.filter((x) => x.role === role)) g.append(el("option", { value: a.id, text: label(a) }));
    if (g.childElementCount) opts.push(g);
  }
  sel.replaceChildren(...opts);
  sel.value = current;
  if (sel.value !== current && sel.options.length) sel.selectedIndex = 0;
}

// ------------------------------------------------------------------------------------------------ 상태
function renderStatus() {
  const doc = S.doc, s = $("status");
  const rows = [["처리한 시각", `${kst(doc.done_ms)} KST`], ["지연", `${Math.round(doc.lag_s / 60)}분`],
    ["시작", `${kst(doc.start_ms)} KST (10월 1일부터 다시 돌림)`], ["계좌 수", String(doc.accounts.length)],
    ["딥시크 금액", doc.ds_money ? "보임" : "숨김 (두 분 규칙)"],
    ["시세 (터미널)", !S.live ? "-" : S.live.off ? "꺼짐" : S.live.unavailable ? "바이낸스 연결 안 됨"
      : `${S.live.source === "fake" ? "연습용 가짜 시세" : "바이낸스"}${S.live.stale ? " (지난 값)" : ""}`]];
  s.replaceChildren(...rows.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })]));
  for (const n of doc.notes || []) s.append(el("dt", { text: "참고" }), el("dd", { text: n }));
}

// ------------------------------------------------------------------------------------------------ 터미널
function termAccounts() { return S.doc ? S.doc.accounts : []; }

function setupTerm() {
  seg($("t-tfs"), TFS.map((t) => [t, t]), S.tf, (v) => { S.tf = v; S.focus = null; store.save(); setupTerm(); loadBars(true); });
  renderWatch();
}

function renderWatch() {
  const box = $("t-coins");
  const openBy = {};
  for (const a of termAccounts()) if (a.open) openBy[coinOf(a.open.symbol)] = (openBy[coinOf(a.open.symbol)] || 0) + 1;
  box.replaceChildren(...COINS.map((c) => {
    const lr = liveRow(c);
    const b = el("button", { type: "button", class: "wl", "aria-pressed": String(c === S.coin) },
      el("span", { class: "wl-c", text: short(c) }),
      el("span", { class: "wl-p", text: lr && lr.price != null ? price(lr.price) : "-" }),
      el("span", { class: `wl-ch ${sign(lr && lr.change_pct)}`, text: lr && lr.change_pct != null
        ? `${lr.change_pct >= 0 ? "+" : ""}${lr.change_pct.toFixed(2)}%` : "" }),
      openBy[c] ? el("span", { class: "wl-n", title: "열린 포지션", text: String(openBy[c]) }) : null);
    b.addEventListener("click", () => { S.coin = c; S.focus = null; store.save(); renderWatch(); loadBars(true); renderTermSide(); renderTicker(); });
    return b;
  }));
}

function renderTicker() {
  const box = $("t-ticker"), lr = liveRow(S.coin);
  const item = (k, v, cls = "") => el("div", { class: "tk" }, el("span", { class: "k", text: k }), el("span", { class: `v ${cls}`, text: v }));
  const now = Date.now();
  const tfms = TF_MS[S.tf];
  const left = tfms - (now % tfms);
  const mmss = (ms) => { const s = Math.max(0, Math.floor(ms / 1000)); return `${s >= 3600 ? `${Math.floor(s / 3600)}:` : ""}${two(Math.floor((s % 3600) / 60))}:${two(s % 60)}`; };
  const d = kstDate(now);
  const head = el("div", { class: "tk-head" }, el("strong", { text: `${short(S.coin)} 무기한` }),
    el("span", { class: `tk-price ${sign(lr && lr.change_pct)}`, text: lr ? price(lr.price) : "-" }));
  const kids = [head];
  if (!S.live || S.live.off) kids.push(item("시세", S.live && S.live.off ? "꺼짐" : "불러오는 중"));
  else if (S.live.unavailable) kids.push(item("시세", "바이낸스 연결 안 됨 (잠시 뒤 다시)", "warn"));
  if (lr) {
    kids.push(item("24시간", lr.change_pct == null ? "-" : `${lr.change_pct >= 0 ? "+" : ""}${lr.change_pct.toFixed(2)}%`, sign(lr.change_pct)),
      item("고가 / 저가", `${price(lr.high)} / ${price(lr.low)}`), item("거래대금", big(lr.quote_volume)),
      item("마크", price(lr.mark)),
      item("펀딩", lr.funding_rate == null ? "-" : `${(lr.funding_rate * 100).toFixed(4)}%`
        + (lr.next_funding_ms ? ` · ${mmss(lr.next_funding_ms - now)}` : ""), sign(lr.funding_rate)));
  }
  kids.push(item(`${S.tf} 봉 마감`, mmss(left)), item("KST", `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}:${two(d.getUTCSeconds())}`));
  if (S.live && S.live.source === "fake") kids.push(item("", "연습용 가짜 시세", "warn"));
  else if (S.live && S.live.stale && !S.live.unavailable) kids.push(item("", "지난 값", "warn"));
  box.replaceChildren(...kids.filter(Boolean));
}

function ensureChart() {
  if (T.chart) return true;
  const L = window.LightweightCharts;
  if (!L) { chartMsg("차트 파일을 불러오지 못했습니다"); return false; }
  const kstTick = (t, type) => {
    const d = kstDate(t * 1000);
    if (type === 0) return String(d.getUTCFullYear());
    if (type === 1) return `${d.getUTCMonth() + 1}월`;
    if (type === 2) return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
    return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`;
  };
  T.chart = L.createChart($("tv"), {
    autoSize: true,
    layout: { background: { type: "solid", color: COL.surface }, textColor: COL.ink2, fontSize: 12 },
    grid: { vertLines: { color: COL.grid }, horzLines: { color: COL.grid } },
    rightPriceScale: { borderColor: COL.line, scaleMargins: { top: 0.08, bottom: 0.22 } },
    timeScale: { borderColor: COL.line, timeVisible: true, secondsVisible: false, rightOffset: 6, tickMarkFormatter: kstTick },
    crosshair: { mode: 0 },
    localization: { locale: "ko-KR", timeFormatter: (t) => {
      const d = kstDate(t * 1000);
      return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${two(d.getUTCHours())}:${two(d.getUTCMinutes())} KST`;
    } },
  });
  T.candles = T.chart.addCandlestickSeries({ upColor: COL.up, downColor: COL.down, borderVisible: false,
    wickUpColor: COL.up, wickDownColor: COL.down });
  T.vol = T.chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "", lastValueVisible: false,
    priceLineVisible: false });
  T.chart.priceScale("").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  return true;
}

function chartMsg(text) { const m = $("tv-msg"); m.textContent = text || ""; m.hidden = !text; }

const toBar = (b, i) => ({ time: b.t[i] / 1000, open: b.o[i], high: b.h[i], low: b.l[i], close: b.c[i] });
const toVol = (b, i) => ({ time: b.t[i] / 1000, value: b.v[i], color: b.c[i] >= b.o[i] ? "rgba(52,211,154,.35)" : "rgba(244,100,107,.35)" });

async function loadBars(reset) {
  if (S.tab !== "term" || !ensureChart()) return;
  const key = `${S.coin}|${S.tf}`;
  if (key !== T.key) reset = true;
  let k;
  try {
    k = await getJSON(`/api/klines?coin=${S.coin}&tf=${S.tf}&limit=${reset ? 1000 : 50}`);
  } catch (e) { chartMsg("차트 자료를 불러오지 못했습니다 (잠시 뒤 다시)"); return; }
  if (`${S.coin}|${S.tf}` !== key) return;                     // the viewer switched meanwhile
  if (k.off) { chartMsg("시세가 꺼져 있습니다 (CANDLEAGUE_DASH_LIVE=off)"); return; }
  const b = k.bars;
  if (!b || !b.t || !b.t.length) { chartMsg(k.unavailable ? "바이낸스 연결 안 됨 (잠시 뒤 다시)" : "봉이 없습니다"); return; }
  chartMsg("");
  const n = b.t.length;
  if (reset) {
    const dec = priceDec(b.c[n - 1]);
    T.candles.applyOptions({ priceFormat: { type: "price", precision: dec, minMove: 10 ** -dec } });
    T.candles.setData(b.t.map((_, i) => toBar(b, i)));
    T.vol.setData(b.t.map((_, i) => toVol(b, i)));
    T.key = key;
    T.first = b.t[0];
    T.last = b.t[n - 1];
    T.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 160), to: n + 6 });
  } else {
    for (let i = 0; i < n; i++) {
      if (b.t[i] < T.last) continue;
      T.candles.update(toBar(b, i));
      T.vol.update(toVol(b, i));
      T.last = b.t[i];
    }
  }
  await applyMarks(reset);
}

async function accountTrades(id, fresh) {
  if (!id) return { trades: [] };
  if (!S.trades[id] || fresh) {
    try { S.trades[id] = await getJSON(`/api/trades/${encodeURIComponent(id)}`); } catch (e) { return S.trades[id] || { trades: [] }; }
  }
  return S.trades[id];
}

async function applyMarks(reset) {
  if (!T.candles) return;
  const a = acctById(S.acct);
  const book = await accountTrades(S.acct, false);
  const tfms = TF_MS[S.tf], bar = (ms) => (Math.floor(ms / tfms) * tfms) / 1000;
  const inRange = (ms) => ms && ms >= T.first;
  const marks = [];
  for (const t of book.trades || []) {
    if (coinOf(t.symbol) !== S.coin) continue;
    if (inRange(t.entry_time)) {
      marks.push({ time: bar(t.entry_time), position: t.side > 0 ? "belowBar" : "aboveBar",
        shape: t.side > 0 ? "arrowUp" : "arrowDown", color: t.side > 0 ? COL.long : COL.short, text: side(t.side) });
    }
    if (inRange(t.exit_time)) {
      marks.push({ time: bar(t.exit_time), position: t.side > 0 ? "aboveBar" : "belowBar", shape: "circle", color: COL.exit,
        text: `${reason(t.exit_reason)}${t.roe == null ? "" : ` ${pct(t.roe, 0)}`}` });
    }
  }
  const o = a && a.open && coinOf(a.open.symbol) === S.coin ? a.open : null;
  if (o && inRange(o.since)) {
    marks.push({ time: bar(o.since), position: o.side > 0 ? "belowBar" : "aboveBar", shape: o.side > 0 ? "arrowUp" : "arrowDown",
      color: o.side > 0 ? COL.long : COL.short, text: `${side(o.side)} (열림)` });
  }
  marks.sort((x, y) => x.time - y.time);
  T.candles.setMarkers(marks);
  for (const l of T.lines) T.candles.removePriceLine(l);
  T.lines = [];
  if (o) {
    const line = (p, color, title, style) => (p == null ? null
      : T.lines.push(T.candles.createPriceLine({ price: p, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title })));
    line(o.entry, COL.ink2, `진입 ${side(o.side)}`, 2);
    line(o.stop, COL.down, "손절", 0);
    line(o.tp, COL.up, "익절", 0);
  }
  if (reset && S.focus && coinOf(S.focus.symbol) === S.coin) {
    const f = S.focus;
    if (f.entry_time && f.entry_time >= T.first) {
      const from = bar(f.entry_time) - 40 * tfms / 1000, to = bar(f.exit_time || f.entry_time) + 40 * tfms / 1000;
      T.chart.timeScale().setVisibleRange({ from, to });
    } else chartMsg("이 거래는 차트 범위 밖입니다 (봉을 1h · 4h로 바꿔 보세요)");
  }
}

function renderAcctCard() {
  const box = $("t-acct-card"), a = acctById(S.acct);
  if (!a) { box.replaceChildren(el("div", { class: "empty", text: "계좌를 고르세요" })); return; }
  const j = (S.doc.judge[a.id] || {});
  const base = acctById(`base-${a.kind}-${a.name}-${a.tf}`), flip = acctById(a.role === "cand" ? `${a.id}-flip` : "");
  const kv = (k, v, cls = "") => el("div", { class: "kv" }, el("span", { text: k }), el("b", { class: cls, text: v }));
  const kids = [
    el("div", { class: "ac-name" }, el("span", { class: `sw sw-${a.role}` }), label(a)),
    el("div", { class: "ac-sub", text: `${ROLE[a.role]} · ${a.exit_ko}${a.bust ? " · 파산" : ""}` }),
    kv("판정", a.role === "cand" ? VERDICT[j.verdict] || "-" : "-", `v-${j.verdict || "early"}`),
    a.role === "cand" && j.band ? kv(`예상 범위 (${j.band.n}건 기준)`, j.band.below
      ? `아래 (하위 5% ${pct(j.band.p5)})` : `안 (하위 5% ${pct(j.band.p5)})`, j.band.below ? "warn" : "") : null,
    kv("거래 · 승률", `${a.trades}건 · ${winRate(a)}`),
    kv("한 번 평균", pct(a.mean_ret), sign(a.mean_ret)),
    kv("잔고", a.wallet == null ? "숨김" : usd(a.wallet), sign(a.wallet == null ? null : a.wallet - 5000)),
    kv("최대 낙폭", a.max_dd == null ? "-" : `${(a.max_dd * 100).toFixed(1)}%`),
  ];
  if (a.role === "cand") {
    kids.push(kv("같은 기간 기본값", base ? pct(base.mean_ret) : "-", sign(base && base.mean_ret)),
      kv("같은 기간 동전", flip ? pct(flip.mean_ret) : "-", sign(flip && flip.mean_ret)));
  }
  if (a.combo) {
    kids.push(el("div", { class: "combo" }, ...Object.entries(a.combo).map(([k, v]) =>
      el("span", { text: `${k} = ${Array.isArray(v) ? v.join("/") : v}` }))));
  }
  const more = el("button", { type: "button", class: "btn", text: "잔고 그래프 · 자세히" });
  more.addEventListener("click", () => openDetail(a.role === "cand" ? a.id : a.id));
  kids.push(more);
  box.replaceChildren(...kids.filter(Boolean));
}

function renderTermSide() {
  if (!S.doc) return;
  const sel = $("t-acct");
  fillAcctSelect(sel, S.acct, false);
  S.acct = sel.value || null;
  renderAcctCard();
  $("t-open-coin").textContent = short(S.coin);
  const open = S.doc.accounts.filter((a) => a.open && coinOf(a.open.symbol) === S.coin);
  const box = $("t-open");
  if (!open.length) box.replaceChildren(el("div", { class: "empty", text: `${short(S.coin)}에 열린 포지션 없음` }));
  else {
    box.replaceChildren(...open.map((a) => {
      const o = a.open, m = moved(o);
      const it = el("button", { type: "button", class: `si${a.id === S.acct ? " on" : ""}` },
        el("div", { class: "si-top" }, sideBadge(o.side), el("span", { class: "si-name", text: label(a) })),
        el("div", { class: "si-bot" },
          el("span", { text: o.entry == null ? "진입가 숨김" : `진입 ${price(o.entry)}` }),
          el("span", { class: sign(m), text: m == null ? "" : `가격 ${pct(m)}` }),
          el("span", { class: "muted", text: kst(o.since).slice(6) })));
      it.addEventListener("click", () => selectAcct(a.id));
      return it;
    }));
  }
  const others = S.doc.accounts.filter((a) => a.open && coinOf(a.open.symbol) !== S.coin).length;
  if (others) box.append(el("div", { class: "muted small", text: `다른 코인에 ${others}개 더 (왼쪽 코인 숫자)` }));
  const fl = $("t-fills");
  const rows = S.fills.slice(0, 40);
  if (!rows.length) fl.replaceChildren(el("div", { class: "empty", text: "아직 끝난 거래가 없습니다" }));
  else {
    fl.replaceChildren(...rows.map((f) => {
      const a = acctById(f.account);
      const it = el("button", { type: "button", class: "si" },
        el("div", { class: "si-top" }, sideBadge(f.side), el("span", { class: "si-coin", text: short(f.symbol || "") }),
          el("span", { class: "si-name", text: a ? label(a) : f.account })),
        el("div", { class: "si-bot" }, el("span", { class: "muted", text: kst(f.exit_time).slice(6) }),
          el("span", { text: reason(f.exit_reason) }), el("span", { class: sign(f.roe), text: pct(f.roe, 1) })));
      it.addEventListener("click", () => toTerminal(f.account, coinOf(f.symbol), f));
      return it;
    }));
  }
  renderTermTrades();
}

async function renderTermTrades() {
  const t = $("t-trades"), a = acctById(S.acct);
  $("t-trades-sub").textContent = a ? `${label(a)} · 최근 50건 · 줄을 누르면 차트에서 보기` : "";
  const book = await accountTrades(S.acct, false);
  t.replaceChildren(el("thead", {}, el("tr", {}, ...FILL_HEAD.filter((h) => h !== "계좌")
    .map((h, i) => el("th", { class: i < 3 ? "l" : "", text: h })))));
  const body = el("tbody");
  const rows = (book.trades || []).slice(0, 50);
  if (!rows.length) emptyRow(body, 9, "이 계좌는 아직 끝난 거래가 없습니다");
  for (const f of rows) body.append(fillRow({ ...f, account: S.acct }, false));
  t.append(body);
}

function selectAcct(id) {
  const a = acctById(id);
  if (!a) return;
  S.acct = id;
  if (TFS.includes(a.tf) && a.tf !== S.tf) S.tf = a.tf;
  if (a.open) S.coin = coinOf(a.open.symbol);
  S.focus = null;
  store.save();
  setupTerm(); renderTermSide(); renderTicker();
  loadBars(true);
}

function toTerminal(id, coin, focus) {
  const a = acctById(id);
  if (a) { S.acct = id; if (TFS.includes(a.tf)) S.tf = a.tf; }
  if (coin && COINS.includes(coin)) S.coin = coin;
  S.focus = focus || null;
  store.save();
  showTab("term");
  setupTerm(); renderTermSide(); renderTicker();
  loadBars(true);
  window.scrollTo({ top: 0 });
}

// ------------------------------------------------------------------------------------------------ 자세히 (equity)
function chart(series) {
  // One axis (balance, $), x = time; crosshair + tooltip; a legend and an end label per line.
  const box = el("div", { class: "chart" });
  const legend = el("div", { class: "legend" });
  for (const s of series) legend.append(el("span", {}, el("span", { class: `sw sw-${s.role}` }), s.label));
  box.append(legend);
  const all = series.flatMap((s) => s.points);
  if (all.length < 2) { box.append(el("div", { class: "empty", text: "아직 거래가 없습니다" })); return box; }
  const avail = (document.querySelector("main").clientWidth || 800) - 34;
  const W = Math.max(300, Math.min(1100, avail)), narrow = W < 560;
  const H = 260, L = narrow ? 52 : 64, R = narrow ? 44 : 70, T0 = 10, B = 26;
  const t0 = Math.min(...all.map((p) => p[0])), t1 = Math.max(...all.map((p) => p[0]), t0 + 1);
  let y0 = Math.min(...all.map((p) => p[1])), y1 = Math.max(...all.map((p) => p[1]));
  if (y1 - y0 < 1) { y0 -= 50; y1 += 50; }
  const pad = (y1 - y0) * 0.08; y0 -= pad; y1 += pad;
  const X = (t) => L + ((t - t0) / (t1 - t0)) * (W - L - R), Y = (v) => T0 + (1 - (v - y0) / (y1 - y0)) * (H - T0 - B);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "잔고 그래프");
  const mk = (tag, a) => { const e = document.createElementNS(ns, tag); for (const k in a) e.setAttribute(k, a[k]); return e; };
  for (let i = 0; i <= 4; i++) {
    const v = y0 + ((y1 - y0) * i) / 4;
    svg.append(mk("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), class: "gl" }));
    const tx = mk("text", { x: L - 6, y: Y(v) + 4, "text-anchor": "end", class: "ax" });
    tx.textContent = `$${Math.round(v).toLocaleString("en-US")}`;
    svg.append(tx);
  }
  for (const [t, anchor] of [[t0, "start"], [t1, "end"]]) {
    const tx = mk("text", { x: X(t), y: H - 6, "text-anchor": anchor, class: "ax" });
    tx.textContent = kst(t).slice(0, 11);
    svg.append(tx);
  }
  const ends = [];
  for (const s of series) {
    if (s.points.length < 2) continue;
    const d = s.points.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    svg.append(mk("path", { d, class: `ln ln-${s.role}` }));
    const last = s.points[s.points.length - 1];
    ends.push({ x: X(last[0]) + 6, y: Y(last[1]) + 4, text: s.label });
  }
  ends.sort((a, b) => a.y - b.y);                       // end labels at least 13 px apart
  for (let i = 1; i < ends.length; i++) ends[i].y = Math.max(ends[i].y, ends[i - 1].y + 13);
  for (const e of ends) {
    const lab = mk("text", { x: e.x, y: e.y, class: "lab" });
    lab.textContent = e.text;
    svg.append(lab);
  }
  const cross = mk("line", { y1: T0, y2: H - B, class: "xh", visibility: "hidden" });
  svg.append(cross);
  const tip = el("div", { class: "tip", hidden: "" });
  svg.addEventListener("pointermove", (ev) => {
    const r = svg.getBoundingClientRect();
    const x = ((ev.clientX - r.left) / r.width) * W;
    const t = t0 + ((x - L) / (W - L - R)) * (t1 - t0);
    if (x < L || x > W - R) { cross.setAttribute("visibility", "hidden"); tip.hidden = true; return; }
    cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("visibility", "visible");
    const lines = series.map((s) => {
      let v = null;
      for (const p of s.points) { if (p[0] <= t) v = p[1]; else break; }
      return `${s.label}: ${v == null ? "-" : usd(v)}`;
    });
    tip.textContent = `${kst(t)} KST · ` + lines.join(" · ");
    tip.hidden = false;
    tip.style.left = `${Math.min(ev.clientX - r.left + 10, r.width - tip.offsetWidth - 4)}px`;
    tip.style.top = "28px";
  });
  svg.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); tip.hidden = true; });
  box.append(svg, tip);
  return box;
}

async function openDetail(id) {
  S.detail = id;
  const c = acctById(id);
  if (!c) return;
  const cand = c.role === "cand" ? c : acctById((c.id.endsWith("-flip") ? c.id.slice(0, -5) : "")) || c;
  const baseId = `base-${cand.kind}-${cand.name}-${cand.tf}`, flipId = `${cand.id}-flip`;
  const ids = cand.role === "cand" ? [cand.id, baseId, flipId] : [cand.id];
  const books = await Promise.all(ids.map((a) => accountTrades(a, true)));
  const d = $("detail");
  const close = el("button", { class: "close", text: "닫기" });
  close.addEventListener("click", () => { d.hidden = true; S.detail = null; });
  const toTerm = el("button", { class: "close", text: "터미널에서 보기" });
  toTerm.addEventListener("click", () => toTerminal(cand.id, cand.open ? coinOf(cand.open.symbol) : null));
  const src = cand.source || {};
  const combo = el("div", { class: "combo" }, ...Object.entries(cand.combo || {}).map(([k, v]) =>
    el("span", { text: `${k} = ${Array.isArray(v) ? v.join("/") : v}` })));
  const roles = cand.role === "cand" ? [["cand", "후보"], ["base", "기본값"], ["flip", "동전"]] : [[cand.role, ROLE[cand.role]]];
  const series = roles.map(([role, lab], i) => [role, lab, books[i]])
    .filter(([, , b]) => b && b.equity).map(([role, lab, b]) => ({ role, label: lab, points: b.equity }));
  const trades = el("table");
  trades.append(el("thead", {}, el("tr", {}, ...FILL_HEAD.filter((h) => h !== "계좌")
    .map((h, i) => el("th", { class: i < 3 ? "l" : "", text: h })))));
  const body = el("tbody");
  for (const t of (books[0].trades || []).slice(0, 100)) body.append(fillRow({ ...t, account: cand.id }, false));
  if (!(books[0].trades || []).length) emptyRow(body, 9, "아직 거래가 없습니다");
  trades.append(body);
  d.replaceChildren(close, toTerm, el("h2", { text: label(cand) }),
    el("div", { class: "meta", text: `${cand.exit_ko} · 백테스트 순위 #${src.rank ?? "-"} · 시험 기간 거래 ${src.test_n ?? "-"}건`
      + (src.test_mean != null ? ` · 시험 기간 한 번 평균 ${pct(src.test_mean)}` : "") }),
    combo, series.length ? chart(series) : el("div", { class: "empty", text: "잔고 그래프 없음 (딥시크: 금액 숨김)" }),
    el("div", { class: "tablewrap" }, trades));
  d.hidden = false;
  d.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ------------------------------------------------------------------------------------------------ refresh loops
function showTab(tab) {
  if (!TABS.includes(tab)) tab = "rank";
  S.tab = tab;
  store.save();
  for (const x of document.querySelectorAll(".tabs button")) x.setAttribute("aria-selected", String(x.dataset.tab === tab));
  for (const s of document.querySelectorAll(".tab")) s.hidden = s.id !== `tab-${tab}`;
  document.querySelector("main").classList.toggle("wide", tab === "term");
  $("cards").hidden = tab !== "rank";
  if (tab === "term") { setupTerm(); renderTermSide(); renderTicker(); loadBars(true); }
  refreshLive();
}

async function refreshLive() {
  if (document.hidden || !["term", "open", "status"].includes(S.tab)) return;
  try { S.live = await getJSON("/api/live"); } catch (e) { return; }
  if (S.tab === "term") { renderWatch(); renderTicker(); renderTermSide(); }
  if (S.tab === "open" && S.doc) renderOpen();
  if (S.tab === "status" && S.doc) renderStatus();
}

async function refresh() {
  try {
    const [doc, fills] = await Promise.all([getJSON("/api/league"), getJSON("/api/fills")]);
    if (!doc.accounts) {
      $("cards").replaceChildren(el("div", { class: "card" }, el("div", { class: "k", text: "후보 리그" }),
        el("div", { class: "v", text: "준비 중" }), el("div", { class: "s", text: "엔진이 첫 처리를 끝내면 여기에 나옵니다" })));
      return;
    }
    const changed = !S.doc || S.doc.done_ms !== doc.done_ms;
    S.doc = doc;
    S.fills = fills.fills || [];
    if (changed) S.trades = {};
    if (!S.acct || !acctById(S.acct)) {
      const first = doc.accounts.filter((a) => a.role === "cand").sort((a, b) => (b.mean_ret ?? -1e9) - (a.mean_ret ?? -1e9))[0];
      S.acct = first ? first.id : (doc.accounts[0] || {}).id || null;
    }
    renderCards(); renderRankFilters(); renderRank(); renderOpen(); renderFills(); renderStatus();
    if (S.tab === "term") { renderWatch(); renderTermSide(); if (changed) applyMarks(false); }
    if (S.detail && changed) openDetail(S.detail);
  } catch (e) { /* the next refresh tries again */ }
}

for (const b of document.querySelectorAll(".tabs button")) b.addEventListener("click", () => showTab(b.dataset.tab));
$("t-acct").addEventListener("change", (e) => selectAcct(e.target.value));
$("f-acct").addEventListener("change", (e) => { S.fAcct = e.target.value; store.save(); renderFills(); });
document.addEventListener("visibilitychange", () => { if (!document.hidden) { refresh(); refreshLive(); if (S.tab === "term") loadBars(false); } });

(async () => {
  const saved = store.get();
  for (const k of ["coin", "tf", "acct", "rankTf", "rankKind", "fAcct"]) if (saved[k] != null) S[k] = saved[k];
  if (!COINS.includes(S.coin)) S.coin = "BTCUSD";
  if (!TFS.includes(S.tf)) S.tf = "15m";
  const hash = location.hash.replace("#", "");
  await refresh();
  showTab(TABS.includes(hash) ? hash : saved.tab || "rank");
  setInterval(refresh, 30_000);
  setInterval(refreshLive, 5_000);
  setInterval(() => { if (S.tab === "term" && !document.hidden) loadBars(false); }, 10_000);
  setInterval(() => { if (S.tab === "term" && !document.hidden) renderTicker(); }, 1_000);
})();
