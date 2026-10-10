// 후보 리그 dashboard: reads /api/league and /api/trades/<id> (the engine's snapshots), refreshes every 60 s.
"use strict";

const VERDICT = { early: "아직 판단 이름", ok: "기준 통과", not_yet: "기준 미달" };
const ROLE = { cand: "후보", base: "기본값", flip: "동전 던지기" };
let LAST = null;
let OPEN_DETAIL = null;

const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else if (k === "text") e.textContent = v; else e.setAttribute(k, v);
  }
  for (const k of kids) if (k != null) e.append(k);
  return e;
};
const pct = (x, d = 2) => (x == null ? "-" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(d)}%`);
const usd = (x) => (x == null ? "-" : `${x < 0 ? "-" : ""}$${Math.abs(Math.round(x)).toLocaleString("en-US")}`);
const kst = (ms) => {
  if (!ms) return "-";
  const d = new Date(ms + 9 * 3600e3);
  return `${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")} `
    + `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
};
const sign = (x) => (x == null ? "" : x > 0 ? "pos" : x < 0 ? "neg" : "");

async function getJSON(url) {
  const r = await fetch(url, { credentials: "same-origin" });
  if (r.status === 401) { location.href = "/login"; throw new Error("login"); }
  return r.json();
}

function td(text, cls = "") { return el("td", { class: cls, text }); }

function renderRank(doc) {
  const t = document.getElementById("rank");
  t.replaceChildren();
  const acc = Object.fromEntries(doc.accounts.map((a) => [a.id, a]));
  const cands = doc.accounts.filter((a) => a.role === "cand")
    .sort((a, b) => (b.mean_ret ?? -1e9) - (a.mean_ret ?? -1e9) || b.trades - a.trades);
  t.append(el("thead", {}, el("tr", {},
    ...["매매법 · 봉", "익절 · 손절", "거래", "승률", "한 번 평균", "잔고", "최대 낙폭", "판정"].map((h, i) =>
      el("th", { class: i < 2 ? "l" : "", text: h })))));
  const body = el("tbody");
  if (!cands.length) body.append(el("tr", {}, el("td", { colspan: "8", class: "empty", text: "후보가 아직 없습니다" })));
  for (const c of cands) {
    const j = doc.judge[c.id] || {};
    const row = el("tr", { class: "cand", tabindex: "0" },
      el("td", { class: "l" }, el("span", { class: "sw sw-cand" }), `${c.name} · ${c.tf}`),
      td(c.exit_ko, "l"), td(String(c.trades)), td(c.trades ? `${Math.round((100 * c.wins) / c.trades)}%` : "-"),
      td(pct(c.mean_ret), sign(c.mean_ret)), td(c.kind === "ds" && c.wallet == null ? "숨김" : usd(c.wallet)),
      td(c.max_dd == null ? "-" : `${(c.max_dd * 100).toFixed(1)}%`),
      td(VERDICT[j.verdict] || "-", `v-${j.verdict || "early"}`));
    row.addEventListener("click", () => openDetail(c.id));
    row.addEventListener("keydown", (e) => { if (e.key === "Enter") openDetail(c.id); });
    body.append(row);
    for (const [role, id] of [["base", `base-${c.kind}-${c.name}-${c.tf}`], ["flip", `${c.id}-flip`]]) {
      const r = acc[id];
      if (!r) continue;
      body.append(el("tr", { class: "ref" },
        el("td", { class: "l" }, el("span", { class: `sw sw-${role}` }), ROLE[role]),
        td(r.exit_ko, "l"), td(String(r.trades)), td(r.trades ? `${Math.round((100 * r.wins) / r.trades)}%` : "-"),
        td(pct(r.mean_ret), sign(r.mean_ret)), td(r.wallet == null ? "-" : usd(r.wallet)),
        td(r.max_dd == null ? "-" : `${(r.max_dd * 100).toFixed(1)}%`), td(r.bust ? "파산" : "")));
    }
  }
  t.append(body);
}

function renderOpen(doc) {
  const t = document.getElementById("open");
  t.replaceChildren(el("thead", {}, el("tr", {}, ...["계좌", "코인", "방향", "진입가", "손절", "익절", "진입 (KST)"]
    .map((h, i) => el("th", { class: i < 3 ? "l" : "", text: h })))));
  const body = el("tbody");
  const open = doc.accounts.filter((a) => a.open);
  if (!open.length) body.append(el("tr", {}, el("td", { colspan: "7", class: "empty", text: "열린 포지션이 없습니다" })));
  for (const a of open) {
    const o = a.open;
    body.append(el("tr", {}, td(`${a.name} · ${a.tf} (${ROLE[a.role]})`, "l"), td(o.symbol, "l"),
      td(o.side > 0 ? "롱" : "숏", "l"), td(o.entry == null ? "숨김" : String(o.entry)), td(o.stop == null ? "-" : String(o.stop)),
      td(o.tp == null ? "-" : String(o.tp)), td(kst(o.since))));
  }
  t.append(body);
}

function renderStatus(doc) {
  const s = document.getElementById("status");
  const rows = [["처리한 시각", `${kst(doc.done_ms)} KST`], ["지연", `${Math.round(doc.lag_s / 60)}분`],
    ["시작", `${kst(doc.start_ms)} KST (10월 1일부터 다시 돌림)`], ["계좌 수", String(doc.accounts.length)],
    ["딥시크 금액", doc.ds_money ? "보임" : "숨김 (두 분 규칙)"]];
  s.replaceChildren(...rows.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })]));
  for (const n of doc.notes || []) s.append(el("dt", { text: "참고" }), el("dd", { text: n }));
  const f = document.getElementById("fresh");
  f.textContent = `${kst(doc.done_ms)} KST까지`;
  f.classList.toggle("late", doc.lag_s > 1800);
}

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
  const H = 260, L = narrow ? 52 : 64, R = narrow ? 44 : 70, T = 10, B = 26;
  const t0 = Math.min(...all.map((p) => p[0])), t1 = Math.max(...all.map((p) => p[0]), t0 + 1);
  let y0 = Math.min(...all.map((p) => p[1])), y1 = Math.max(...all.map((p) => p[1]));
  if (y1 - y0 < 1) { y0 -= 50; y1 += 50; }
  const pad = (y1 - y0) * 0.08; y0 -= pad; y1 += pad;
  const X = (t) => L + ((t - t0) / (t1 - t0)) * (W - L - R), Y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
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
  const cross = mk("line", { y1: T, y2: H - B, class: "xh", visibility: "hidden" });
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
  OPEN_DETAIL = id;
  const doc = LAST;
  const c = doc.accounts.find((a) => a.id === id);
  if (!c) return;
  const baseId = `base-${c.kind}-${c.name}-${c.tf}`, flipId = `${c.id}-flip`;
  const [tc, tb, tf] = await Promise.all([id, baseId, flipId].map((a) => getJSON(`/api/trades/${encodeURIComponent(a)}`)));
  const d = document.getElementById("detail");
  const close = el("button", { class: "close", text: "닫기" });
  close.addEventListener("click", () => { d.hidden = true; OPEN_DETAIL = null; });
  const src = c.source || {};
  const combo = el("div", { class: "combo" }, ...Object.entries(c.combo).map(([k, v]) =>
    el("span", { text: `${k} = ${Array.isArray(v) ? v.join("/") : v}` })));
  const series = [["cand", "후보", tc], ["base", "기본값", tb], ["flip", "동전", tf]]
    .filter(([, , b]) => b && b.equity).map(([role, label, b]) => ({ role, label, points: b.equity }));
  const trades = el("table");
  trades.append(el("thead", {}, el("tr", {}, ...["코인", "방향", "진입 (KST)", "청산 (KST)", "이유", "레버리지", "손익"]
    .map((h, i) => el("th", { class: i < 2 ? "l" : "", text: h })))));
  const body = el("tbody");
  for (const t of (tc.trades || []).slice(0, 100)) {
    body.append(el("tr", {}, td(t.symbol, "l"), td(t.side > 0 ? "롱" : "숏", "l"), td(kst(t.entry_time)), td(kst(t.exit_time)),
      td(t.exit_reason), td(`${t.leverage}x`), td(t.pnl == null ? "숨김" : usd(t.pnl), sign(t.pnl))));
  }
  if (!(tc.trades || []).length) body.append(el("tr", {}, el("td", { colspan: "7", class: "empty", text: "아직 거래가 없습니다" })));
  trades.append(body);
  d.replaceChildren(close, el("h2", { text: `${c.name} · ${c.tf}` }),
    el("div", { class: "meta", text: `${c.exit_ko} · 백테스트 순위 #${src.rank ?? "-"} · 시험 기간 거래 ${src.test_n ?? "-"}건`
      + (src.test_mean != null ? ` · 시험 기간 한 번 평균 ${pct(src.test_mean)}` : "") }),
    combo, series.length ? chart(series) : el("div", { class: "empty", text: "잔고 그래프 없음 (딥시크: 금액 숨김)" }),
    el("div", { class: "tablewrap" }, trades));
  d.hidden = false;
  d.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function refresh() {
  try {
    const doc = await getJSON("/api/league");
    if (!doc.accounts) { document.getElementById("rank").replaceChildren(el("tr", {}, el("td", { class: "empty", text: "준비 중" }))); return; }
    LAST = doc;
    renderRank(doc); renderOpen(doc); renderStatus(doc);
    if (OPEN_DETAIL) openDetail(OPEN_DETAIL);
  } catch (e) { /* the next refresh tries again */ }
}

for (const b of document.querySelectorAll(".tabs button")) {
  b.addEventListener("click", () => {
    for (const x of document.querySelectorAll(".tabs button")) x.setAttribute("aria-selected", String(x === b));
    for (const s of document.querySelectorAll(".tab")) s.hidden = s.id !== `tab-${b.dataset.tab}`;
  });
}
refresh();
setInterval(refresh, 60_000);
