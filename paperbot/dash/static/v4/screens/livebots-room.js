// 실거래 › 회의실 (#/room; owners 2026-11-01, with a picture and a video of someone's 'AI office' trading dashboard: "이렇게
// 가능할까?"): one round table, each seat one real program on the server, from one read-only answer (dash/more/liveroom.py,
// /api/v4/livebots/room, every 15 s):
//   the table   a glowing round table drawn on a canvas, the camera slowly circling it; each seat a program (the three
//               live bots, their paper twins, their checks, the AI 분석팀's four members, the backup, this site) with its
//               name tag: its role, its state (일하는 중 · 기다리는 중 · 쉬는 중 · 꺼짐 · 확인 필요) and when it last did
//               something; a beam from the centre to each program that is running; a tag picked shows what it did last
//   left        팀 상태 (the three live bots' balance, today, closed trades, open positions), 다음 봉 마감 (15m · 30m · 1h · 4h ·
//               1d, counting down), 포지션 (the live bots' open positions)
//   right       팀 맥박 (the last 24 h: signals, entries, exits, checks, meetings), 활동 (the newest rows of every program)
//   below       자리 (every seat as a list: the same words without the picture, and the phone's main view)
// HONESTY: a seat is a program the repo installs and what it says is read from its own files or systemd; the AI members
// read and explain, they never trade; the figures and the room are a picture (said on the screen), never a number.
// Under reduced motion the camera stands still.
import {h, put, ui, fmt, motion, serverNow} from "../core/pb.js";
// the table in real 3D (owners 11-01 "3d로"): the browser's WebGL; where it cannot start, the 2D picture below
import {create3d, hexRgb, seatPose, screenOf, YAW0} from "./livebots-room3d.js";

export const ROOM_API = "/api/v4/livebots/room";
const REFRESH_MS = 15 * 1000;
const MIN = 60 * 1000;
const FRAME_MS = 33;
const ok = (x) => x != null && x !== "" && Number.isFinite(Number(x));
const TINT = {bot: "--dk-green", paper: "--dk-cyan", check: "--dk-amber", ai: "--dk-core-violet", ops: "--dk-steel"};
const STATE_TINT = {live: "--dk-green", wait: "--dk-cyan", idle: "--dk-steel", off: "--dk-muted", error: "--dk-red"};
const STATE_ORDER = ["live", "wait", "idle", "error", "off"];
const px = (x) => (ok(x) ? String(Number(Number(x).toPrecision(6))) : "—");

// ---------------------------------------------------------------- pure (node tests: tests/test_dash_liveroom.py)
/** "방금" / "12분 전" / "3시간 전" / "2일 전" / "기록 없음". */
export function agoKo(now, ts) {
  if (!ok(ts)) return "기록 없음";
  const m = Math.max(0, Math.floor((Number(now) - Number(ts)) / MIN));
  return m < 1 ? "방금" : m < 60 ? `${m}분 전` : m < 1440 ? `${Math.floor(m / 60)}시간 전` : `${Math.floor(m / 1440)}일 전`;
}
/** Binance's bar closes after ``now`` (UTC-aligned: the 4h and the day close at 09:00 KST and every 4 h from it). */
export const CLOSES = [["15분", 15 * MIN], ["30분", 30 * MIN], ["1시간", 60 * MIN], ["4시간", 240 * MIN], ["1일", 1440 * MIN]];
export function nextCloses(now) {
  return CLOSES.map(([ko, ms]) => { const at = Math.floor(now / ms) * ms + ms; return {ko, at, left: at - now}; });
}
/** "6:13" / "36:13" / "2:36:13" (h:mm:ss past an hour). */
export function clockKo(ms) {
  const t = Math.max(0, Math.floor(Number(ms) / 1000)), hh = Math.floor(t / 3600), mm = Math.floor((t % 3600) / 60), ss = t % 60;
  const two = (x) => String(x).padStart(2, "0");
  return hh ? `${hh}:${two(mm)}:${two(ss)}` : `${mm}:${two(ss)}`;
}
/** A seat's place round the table: its angle (the first seat nearest the camera at the start) and its point. */
export function seatAt(i, n, r = 1.38) {
  const a = Math.PI / 2 + (i / Math.max(1, n)) * Math.PI * 2;
  return {a, x: Math.cos(a) * r, z: Math.sin(a) * r};
}
/** A point of the room (x, z on the floor, y up) on the screen: [X, Y, depth, scale] for a camera {cx, cy, S, th
 * (its turn), el (its height angle), D (its distance)}; a larger depth is further away. */
export function project(c, x, y, z) {
  const ct = Math.cos(c.th), st = Math.sin(c.th), ce = Math.cos(c.el), se = Math.sin(c.el);
  const x1 = x * ct - z * st, z1 = x * st + z * ct;
  const up = y * ce + z1 * se, d = z1 * ce - y * se;
  const k = c.D / (c.D + d);
  return [c.cx + x1 * k * c.S, c.cy - up * k * c.S, d, k];
}
/** A seat's tag: {cls, name, role, line} (its state in a word or two and when it last did something, as the video's tags;
 * a live bot's holding in full: "보유 중 · SOL 숏"). */
export const STATE_WORD = {live: "일하는 중", wait: "기다리는 중", idle: "쉬는 중", off: "꺼짐", error: "확인 필요"};
export function tagOf(s, now) {
  const word = s.state === "live" && s.group === "bot" ? s.state_ko : STATE_WORD[s.state] || s.state_ko;
  return {cls: ["rm-tag", s.state || "off", `g-${s.group || "ops"}`], name: s.name_ko || "?", role: s.role_ko || "",
    line: `${word || "—"} · ${agoKo(now, s.last_ms)}`};
}
/** 팀 맥박: [[words, count, share of the largest], …]. */
export function pulseRows(p) {
  const rows = [["신호", "signals"], ["진입", "entries"], ["청산", "exits"], ["점검", "checks"], ["회의", "meetings"]]
    .map(([ko, k]) => [ko, ok((p || {})[k]) ? Number(p[k]) : 0]);
  const m = Math.max(1, ...rows.map((r) => r[1]));
  return rows.map(([ko, n]) => [ko, n, n / m]);
}
/** The floating screens of the 3D room, each with its place behind the table (pose: livebots-room3d.js layoutPose): the
 * coins (Binance's closed bars and the bots' formulas, as the 관제실: price, 24 hours, the 30m 추세 바 종합, the last 15m
 * histogram and its 0 cross), the coin cards, the team's pulse, its status and its newest rows; all from the answer. */
const TREND_WORD = {1: ["상승", "up"], "-1": ["하락", "down"], 0: ["진입 금지", "flat"]};
export function panelSpecs(d, now) {
  const t = (d && d.team) || {}, money = (x) => (ok(x) ? `${x >= 0 ? "" : "−"}$${fmt.num(Math.abs(x), 2)}` : "—");
  const sign = (x) => (ok(x) ? `${x >= 0 ? "+" : "−"}$${fmt.num(Math.abs(x), 2)}` : "—");
  const pct = (r) => (ok(r) ? `${r >= 0 ? "+" : "−"}${fmt.num(Math.abs(r) * 100, 2)}%` : "—");
  const coins = (d && d.coins) || [];
  const cRows = coins.map((c) => {
    if (c.state !== "ok") return [{t: c.coin || c.symbol}, {t: c.ko || "못 읽음", tone: "muted"}];
    const tw = TREND_WORD[String(c.trend)] || ["—", "muted"], x = Number(c.cross) || 0;
    return [{t: c.coin}, {t: px(c.last)}, {t: pct(c.chg24), tone: ok(c.chg24) ? (c.chg24 >= 0 ? "up" : "down") : "muted"}, {t: tw[0], tone: tw[1]},
      {t: ok(c.hist) ? `${fmt.num(c.hist, 2)}${x ? (x > 0 ? " ▲0선" : " ▼0선") : ""}` : "—", tone: ok(c.hist) ? (c.hist >= 0 ? "up" : "down") : "muted"}];
  });
  return [
    {title: "COINS · 코인", sub: "바이낸스 봉 · 30분 추세 바 종합 · 15분 히스토그램 (봇의 계산 그대로)", px: [1024, 420],
      pose: {off: 0, y: 1.62, w: 3.1, h: 1.27, r: 3.45},
      table: {cols: ["코인", "가격", "24시간", "30분 추세", "히스토그램"], x: [22, 150, 390, 590, 790], rows: cRows.length ? cRows : [[{t: "코인 값을 기다리는 중", tone: "muted"}]]}},
    {title: "TOP 6 · 코인 카드", sub: "24시간 줄", px: [720, 460], pose: {off: -0.98, y: 1.42, w: 1.85, h: 1.18, r: 3.35},
      cards: coins.filter((c) => c.state === "ok").map((c) => ({coin: c.coin, price: px(c.last), chg: pct(c.chg24),
        tone: ok(c.chg24) ? (c.chg24 >= 0 ? "up" : "down") : "muted", spark: c.spark || []}))},
    {title: "TEAM PULSE · 팀 맥박", sub: "지난 24시간", pose: {off: 0.98, y: 1.42, w: 1.7, h: 1.06, r: 3.35},
      bars: pulseRows(d && d.pulse).map(([ko, n, f]) => [ko, f, String(n)])},
    {title: "TEAM STATUS · 팀 상태", sub: "세 실거래 봇", pose: {off: -1.75, y: 1.25, w: 1.6, h: 1.0, r: 3.2}, rows: [
      {k: "잔고", t: money(t.equity), big: true},
      {k: "오늘 손익", t: sign(t.today_pnl), tone: ok(t.today_pnl) ? (t.today_pnl >= 0 ? "up" : "down") : ""},
      {k: "닫힌 거래", t: ok(t.n) ? `${fmt.int(t.n)}번 · 승 ${fmt.int(t.wins || 0)} / 패 ${fmt.int(Math.max(0, t.n - (t.wins || 0)))}` : "—"},
      {k: "열린 포지션", t: ok(t.open) ? `${fmt.int(t.open)}개` : "—"}]},
    {title: "ACTIVITY · 활동", sub: "모든 자리의 최근 기록", pose: {off: 1.75, y: 1.25, w: 1.6, h: 1.0, r: 3.2},
      rows: ((d && d.feed) || []).slice(0, 7).map((r) => ({t: `${fmt.hm(r.ts)} ${r.who_ko} ${r.kind_ko} · ${r.text}`}))},
  ];
}
/** How many seats in each state: {live, wait, idle, error, off}. */
export function stateCounts(seats) {
  const out = {live: 0, wait: 0, idle: 0, error: 0, off: 0};
  for (const s of seats || []) if (s && s.state in out) out[s.state] += 1;
  return out;
}

// ---------------------------------------------------------------- the table (canvas) and its name tags (HTML)
function tableView(ctx, onPick) {
  const pin = {position: "absolute", left: "0", top: "0", width: "100%", height: "100%", display: "block"};
  const cv = h("canvas", {class: "rm-cv", "aria-hidden": "true", style: pin});
  const tags = h("div", {class: "rm-tags"});
  const note = h("small", {class: "rm-note dk-mono"}, "그림은 장식 · 자리마다 실제 프로그램 · 글자는 그 기록 · 3D는 끌어서 돌려요");
  const box = h("div", {class: "rm-scene", style: {position: "relative", overflow: "hidden"}}, cv, tags, note);
  const r3 = create3d(cv);                             // WebGL: the real 3D room; else the 2D picture
  const g = r3 ? null : cv.getContext ? cv.getContext("2d") : null;
  if (r3) box.classList.add("is-3d");
  const o = {W: 0, H: 0, dpr: 1, th: 0.35, seats: [], tagEls: [], tw: [], col: null, raf: 0, last: 0, alive: true, sel: null, motes: [], small: false,
    yaw: YAW0, pitch: 0.36, drag: null, idleUntil: 0, c3: null, fit: 1};
  for (let i = 0; i < 160; i++) o.motes.push({a: (i * 2.39996) % (Math.PI * 2), r: 0.04 + ((i * 37) % 100) / 100 * 0.2, y: ((i * 53) % 100) / 100, v: 0.15 + ((i * 17) % 10) / 40});
  const tok = () => {
    const cs = getComputedStyle(document.documentElement), v = (k) => String(cs.getPropertyValue(k) || "").trim();
    o.col = {cyan: v("--dk-core-cyan"), blue: v("--dk-core-blue"), sand: v("--dk-core-sand"), ink: v("--dk-ink"), panel: v("--dk-panel-2"),
      line: v("--dk-line-2"), bg: v("--dk-bg"), haze: v("--dk-core-haze")};
    for (const [k, t] of Object.entries(TINT)) o.col["g-" + k] = v(t);
    for (const [k, t] of Object.entries(STATE_TINT)) o.col["s-" + k] = v(t);
    const num3 = (k, d) => hexRgb(v(k)) || d;           // the 3D room's colours: the same tokens, as numbers
    const c3 = {bg: num3("--dk-bg", [0.01, 0.03, 0.04]), floor: num3("--dk-panel", [0.02, 0.07, 0.1]), table: num3("--dk-core-haze", [0.04, 0.13, 0.2]),
      desk: num3("--dk-panel-2", [0.03, 0.1, 0.15]), chair: num3("--dk-line-2", [0.13, 0.25, 0.31]), cyan: num3("--dk-core-cyan", [0.25, 0.81, 0.88]),
      blue: num3("--dk-core-blue", [0.48, 0.71, 0.94]), sand: num3("--dk-core-sand", [0.88, 0.8, 0.57]), ink: num3("--dk-ink", [0.87, 0.9, 0.93]),
      muted: num3("--dk-muted", [0.45, 0.54, 0.59]), green: num3("--dk-green", [0.32, 0.78, 0.6])};
    for (const [k, t] of Object.entries(TINT)) c3["g-" + k] = num3(t, c3.ink);
    for (const [k, t] of Object.entries(STATE_TINT)) c3["s-" + k] = num3(t, c3.muted);
    o.c3 = c3;
    o.css = {panel: v("--dk-panel"), cyan: v("--dk-core-cyan"), ink: v("--dk-ink"), muted: v("--dk-muted"), line: v("--dk-line-2"),
      up: v("--dk-green"), down: v("--dk-red"), flat: v("--dk-amber"), upTile: v("--dk-green-tile"), downTile: v("--dk-red-tile"),
      mutedTile: v("--dk-line")};
    o.font = v("--f-term") || "monospace";
  };
  function layout() {
    const r = box.getBoundingClientRect ? box.getBoundingClientRect() : {width: 0, height: 0};
    const dpr = Math.min(2, (typeof window !== "undefined" && window.devicePixelRatio) || 1);
    const W = Math.round(Math.min(r.width, 2000) * dpr), H = Math.round(Math.min(r.height, 1200) * dpr);
    o.small = r.width < 560;
    o.fit = r.width >= 1100 ? 0.6 : 1;                 // (wide: the side panels lie over the room, the table in the free middle)
    if (W === o.W && H === o.H) return false;
    o.W = W; o.H = H; o.dpr = dpr;
    cv.width = Math.max(1, W); cv.height = Math.max(1, H);
    return true;
  }
  const cam = () => ({cx: o.W / 2, cy: o.H * 0.6, S: Math.min(o.W * (o.small ? 0.33 : 0.27), o.H * 0.48), th: o.th, el: 0.6, D: 4.2});
  const P = (c, x, y, z) => project(c, x, y, z);
  function ring(c, r, y, stroke, alpha, width) {
    g.beginPath();
    for (let i = 0; i <= 96; i++) {
      const a = (i / 96) * Math.PI * 2, [X, Y] = P(c, Math.cos(a) * r, y, Math.sin(a) * r);
      if (i) g.lineTo(X, Y); else g.moveTo(X, Y);
    }
    g.globalAlpha = alpha; g.strokeStyle = stroke; g.lineWidth = width * o.dpr; g.stroke();
  }
  function disc(c, r, y, fill, alpha) {
    g.beginPath();
    for (let i = 0; i <= 96; i++) {
      const a = (i / 96) * Math.PI * 2, [X, Y] = P(c, Math.cos(a) * r, y, Math.sin(a) * r);
      if (i) g.lineTo(X, Y); else g.moveTo(X, Y);
    }
    g.globalAlpha = alpha; g.fillStyle = fill; g.fill();
  }
  function figure(c, s, at, t) {                       // a seat: its chair, its figure, its light on the floor
    const C = o.col, tint = C["g-" + s.group] || C.ink, st = C["s-" + s.state] || C.line, dim = s.state === "off" ? 0.35 : 1;
    const [fx, fy, , k] = P(c, at.x, 0, at.z);
    const u = k * c.S;                                 // one room unit on the screen here
    const pulse = s.state === "live" ? 0.6 + 0.4 * Math.sin(t / 300 + at.a * 3) : 1;
    g.globalAlpha = 0.85 * pulse; g.strokeStyle = st; g.lineWidth = 2 * o.dpr;           // the light on the floor
    g.beginPath(); g.ellipse(fx, fy, 0.17 * u, 0.07 * u, 0, 0, Math.PI * 2); g.stroke();
    g.globalAlpha = 0.18 * pulse; g.fillStyle = st; g.fill();
    g.globalAlpha = 0.9 * dim; g.fillStyle = C.panel;                                      // the chair
    g.fillRect(fx - 0.09 * u, fy - 0.34 * u, 0.18 * u, 0.26 * u);
    g.fillStyle = tint; g.globalAlpha = 0.85 * dim;                                        // the figure: a body, a head
    const bw = 0.13 * u, bh = 0.2 * u, by = fy - 0.3 * u;
    g.beginPath();
    if (g.roundRect) g.roundRect(fx - bw / 2, by, bw, bh, bw / 2.4); else g.rect(fx - bw / 2, by, bw, bh);
    g.fill();
    g.beginPath(); g.arc(fx, by - 0.075 * u, 0.06 * u, 0, Math.PI * 2); g.fill();
    if (o.sel === s.id) { g.globalAlpha = 1; g.strokeStyle = C.ink; g.lineWidth = 1.5 * o.dpr; g.beginPath(); g.arc(fx, by - 0.075 * u, 0.09 * u, 0, Math.PI * 2); g.stroke(); }
  }
  function draw3d(t) {
    if (!o.c3 || !o.W) return;
    const vp = r3.draw({W: o.W, H: o.H, dpr: o.dpr, t, yaw: o.yaw, pitch: o.pitch, col: o.c3, drift: !o.drag && !motion.reduced() && Date.now() >= o.idleUntil,
      fit: o.fit,
      seats: o.seats.map((s) => ({group: s.group, state: s.state, sel: s.id === o.sel}))});
    if (!vp) return;
    const css = o.dpr || 1, wCss = o.W / css, n = o.seats.length;
    o.seats.forEach((s, i) => {                        // each name tag over its figure's head
      const el = o.tagEls[i];
      if (!el) return;
      const p = seatPose(i, n), at = screenOf(vp, p.x + Math.cos(p.a) * 0.12, 1.02, p.z + Math.sin(p.a) * 0.12, o.W, o.H);
      if (!at) { el.style.visibility = "hidden"; return; }
      const sc = Math.max(0.7, Math.min(1.08, 6.8 / at[2] * (o.small ? 0.85 : 1)));
      const half = ((o.tw[i] || 150) / 2) * sc + 4;
      el.style.visibility = "visible";
      el.style.left = `${Math.max(half, Math.min(wCss - half, at[0] / css)).toFixed(1)}px`;
      el.style.top = `${Math.max(4, at[1] / css).toFixed(1)}px`;
      el.style.zIndex = String(Math.round(200 - at[2] * 20));
      el.style.opacity = String(Math.max(0.6, Math.min(1, 1.6 - at[2] * 0.12)));
      el.style.transform = `translate(-50%, -100%) scale(${sc.toFixed(3)})`;
      el.style.transformOrigin = "50% 100%";
    });
  }
  function draw(t) {
    if (r3) { draw3d(t); return; }
    if (!g || !o.col || !o.W) return;
    const c = cam(), C = o.col, tt = (t || 0) / 1000;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.globalCompositeOperation = "source-over";
    g.clearRect(0, 0, o.W, o.H);
    for (const [r, a] of [[2.1, 0.1], [2.5, 0.07], [2.95, 0.05]]) ring(c, r, 0, C.cyan, a, 1);          // the floor's rings
    disc(c, 1.0, 0, C.haze, 0.95);                                                                   // the table
    ring(c, 1.0, 0, C.cyan, 0.9, 2.2);
    ring(c, 1.04, 0, C.cyan, 0.25, 5);
    for (const [r, a] of [[0.32, 0.5], [0.55, 0.35], [0.78, 0.28]]) ring(c, r, 0.001, C.cyan, a, 1);
    g.globalAlpha = 0.22; g.strokeStyle = C.blue; g.lineWidth = o.dpr;                              // the circuits, turning
    for (let i = 0; i < 24; i++) {
      const a = (i / 24) * Math.PI * 2 + tt * 0.08, r0 = i % 2 ? 0.32 : 0.55;
      const [x0, y0] = P(c, Math.cos(a) * r0, 0, Math.sin(a) * r0), [x1, y1] = P(c, Math.cos(a) * 0.97, 0, Math.sin(a) * 0.97);
      g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke();
    }
    const n = o.seats.length;
    const seats = o.seats.map((s, i) => ({s, at: seatAt(i, n)})).map((x) => ({...x, d: P(c, x.at.x, 0, x.at.z)[2]}));
    seats.sort((a, b) => b.d - a.d);                                                                  // far first
    const core = () => {                                                                             // the centre: a column of light
      const [bx, byy, , k] = P(c, 0, 0, 0), u = k * c.S;
      g.globalCompositeOperation = "lighter";
      for (const m of o.motes) {
        const yy = (m.y + tt * m.v * 0.1) % 1, a = m.a + tt * 0.4;
        const [X, Y] = P(c, Math.cos(a) * m.r, yy * 0.9, Math.sin(a) * m.r);
        g.globalAlpha = 0.5 * (1 - yy); g.fillStyle = yy > 0.6 ? C.sand : C.cyan;
        g.fillRect(X - o.dpr, Y - o.dpr, 2 * o.dpr, 2 * o.dpr);
      }
      for (const [yy, r] of [[0.45, 0.2], [0.62, 0.15], [0.76, 0.1]]) ring(c, r, yy, C.cyan, 0.5, 1.2);
      g.globalAlpha = 0.25; g.fillStyle = C.cyan; g.beginPath(); g.ellipse(bx, byy, 0.26 * u, 0.1 * u, 0, 0, Math.PI * 2); g.fill();
      g.globalCompositeOperation = "source-over";
    };
    let drewCore = false;
    for (const x of seats) {
      if (!drewCore && x.d < 0) { core(); drewCore = true; }
      if (x.s.state === "live" || x.s.state === "wait") {                                            // a beam to each running program
        const [x0, y0] = P(c, 0, 0.32, 0), [x1, y1] = P(c, x.at.x * 0.86, 0.12, x.at.z * 0.86);
        g.globalAlpha = x.s.state === "live" ? 0.55 : 0.25; g.strokeStyle = C["s-" + x.s.state]; g.lineWidth = o.dpr;
        g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke();
        const f = (tt * 0.5 + x.at.a) % 1;
        g.globalAlpha = 0.9; g.fillStyle = C["s-" + x.s.state];
        g.beginPath(); g.arc(x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, 1.8 * o.dpr, 0, Math.PI * 2); g.fill();
      }
      figure(c, x.s, x.at, t || 0);
    }
    if (!drewCore) core();
    g.globalAlpha = 1;
    placeTags(c, seats);
  }
  function placeTags(c, seats) {
    const css = o.dpr || 1, wCss = o.W / css;
    for (const x of seats) {
      const i = o.seats.indexOf(x.s), el = o.tagEls[i];
      if (!el) continue;
      const [X, Y, d, k] = P(c, x.at.x, 0.62, x.at.z);
      const sc = Math.max(0.72, Math.min(1.05, k * (o.small ? 0.85 : 1)));
      const half = ((o.tw[i] || 150) / 2) * sc + 4;                  // a tag stays inside the frame
      el.style.left = `${Math.max(half, Math.min(wCss - half, X / css)).toFixed(1)}px`;
      el.style.top = `${Math.max(4, Y / css).toFixed(1)}px`;
      el.style.zIndex = String(100 - Math.round(d * 20));
      el.style.opacity = String(Math.max(0.55, Math.min(1, 0.75 + (1 - d) * 0.2)));
      el.style.transform = `translate(-50%, -100%) scale(${sc.toFixed(3)})`;
      el.style.transformOrigin = "50% 100%";
    }
  }
  const measure = () => { o.tw = o.tagEls.map((e) => (e.offsetWidth || 0)); };
  const running = () => o.alive && cv.isConnected && !document.hidden && !motion.reduced() && (!!g || !!r3);
  function frame(t) {
    o.raf = 0;
    if (!running()) return;
    if (t - o.last >= FRAME_MS) {
      const dt = o.last ? Math.min(120, t - o.last) : 0;
      o.last = t;
      o.th += dt * 0.00006;
      // (the camera sways round its start by itself, livebots-room3d.js; a drag turns it by hand)
      draw(t);
    }
    o.raf = requestAnimationFrame(frame);
  }
  const kick = () => { if (!o.raf && running()) { o.last = 0; o.raf = requestAnimationFrame(frame); } };
  const still = () => { layout(); draw(0); };
  if (r3) {                                            // drag to turn the camera (a finger or the mouse); it circles again 4 s after
    ctx.listen(cv, "pointerdown", (e) => { o.drag = {x: e.clientX, y: e.clientY, yaw: o.yaw, pitch: o.pitch}; if (cv.setPointerCapture) cv.setPointerCapture(e.pointerId); });
    ctx.listen(cv, "pointermove", (e) => {
      if (!o.drag) return;
      o.yaw = o.drag.yaw - (e.clientX - o.drag.x) * 0.006;
      o.pitch = Math.max(0.22, Math.min(1.0, o.drag.pitch + (e.clientY - o.drag.y) * 0.004));
      if (!o.raf) draw(0);
    });
    const up = () => { o.drag = null; o.idleUntil = Date.now() + 4000; };
    ctx.listen(cv, "pointerup", up);
    ctx.listen(cv, "pointercancel", up);
  }
  if (typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(() => { if (layout()) { measure(); if (running()) kick(); else still(); } });
    ro.observe(box);
    ctx.track(() => ro.disconnect());
  }
  ctx.listen(document, "visibilitychange", () => { if (!document.hidden) { tok(); if (running()) kick(); else still(); } });
  ctx.track(() => { o.alive = false; if (o.raf) cancelAnimationFrame(o.raf); o.raf = 0; });
  requestAnimationFrame(() => { tok(); layout(); if (running()) kick(); else still(); });
  return {
    el: box,
    set(seats, now) {
      o.seats = seats || [];
      o.tagEls = o.seats.map((s) => {
        const tg = tagOf(s, now);
        return h("button", {type: "button", class: [...tg.cls, o.sel === s.id ? "on" : ""], title: `${tg.name} · ${tg.role}`,
          onclick: () => { o.sel = s.id; onPick(s); for (const e of o.tagEls) e.classList.toggle("on", e === o.tagEls[o.seats.indexOf(s)]); if (!o.raf) still(); }},
        h("b", null, tg.name), h("small", {class: "rm-role"}, tg.role), h("small", {class: "rm-line"}, tg.line));
      });
      put(tags, o.tagEls);
      requestAnimationFrame(() => { measure(); if (!o.raf) still(); });
      if (!o.raf) { if (running()) kick(); else still(); }
    },
    pick(id) { o.sel = id; },
    panels(specs) { if (r3 && o.css) { r3.panels(specs, o.css, o.font, "PAPERBOT · LIVE 3D · 회의실"); if (!o.raf) still(); } },
  };
}

// ---------------------------------------------------------------- the screen
const panel = (cls, title, sub, ...body) => h("section", {class: ["dk-p", cls]},
  h("header", {class: "dk-ph"}, h("b", {class: "dk-pt"}, "◆ ", title), sub ? h("span", {class: "dk-ps"}, sub) : null), ...body);

export function roomView(ctx) {
  const st = {d: null, okAt: 0, busy: false, sel: null};
  const slot = h("div", {class: "lb-slot"});
  const clockK = h("b", {class: "dk-clk num"}, "--:--:--"), clockU = h("small", {class: "dk-clku num"}, "");
  const counts = h("div", {class: "rm-counts"});
  const team = h("div", {class: "rm-team"});
  const closes = h("div", {class: "rm-closes"});
  const pos = h("div", {class: "rm-pos"});
  const pulse = h("div", {class: "rm-pulse"});
  const feed = h("div", {class: "rm-feed"});
  const roster = h("div", {class: "rm-roster"});
  const detail = h("div", {class: "rm-detail", "aria-live": "polite"});
  const pick = (s) => { st.sel = s.id; drawDetail(); };
  const table = tableView(ctx, pick);
  const el = h("div", {class: ["dk", "rm"]},
    slot,
    h("header", {class: "dk-top"},
      h("div", {class: "dk-brand"}, h("span", {class: "dk-logo", "aria-hidden": "true"}, "PB"),
        h("div", null, h("small", {class: "dk-mono"}, "THE TEAM · REAL PROGRAMS · READ ONLY"),
          h("b", {class: "dk-name"}, "PAPERBOT ", h("em", null, "//"), " 회의실"),
          h("small", {class: "dk-mono"}, "자리마다 서버의 실제 프로그램 · 상태는 그 기록과 systemd"))),
      counts,
      h("div", {class: "dk-clock"}, h("div", null, clockK, h("span", {class: "dk-live"}, "LIVE")), h("small", {class: "dk-mono"}, "KST · 한국 시간"), clockU)),
    h("div", {class: "rm-g"},
      h("div", {class: ["rm-col", "rm-left"]},
        panel("rm-a-team", "팀 상태 · TEAM STATUS", "세 실거래 봇", team),
        panel("rm-a-close", "다음 봉 마감 · NEXT CANDLE CLOSES", "바이낸스 봉 (UTC 기준)", closes),
        panel("rm-a-pos", "포지션 · POSITIONS", "실거래 봇의 열린 포지션", pos)),
      h("section", {class: ["dk-p", "rm-a-room"]},
        h("header", {class: "dk-ph"}, h("b", {class: "dk-pt"}, "◆ 회의실 · THE TABLE"),
          h("span", {class: "dk-ps"}, "이름표를 누르면 그 프로그램이 마지막에 한 일 · 빛 = 초록 일하는 중 · 하늘 기다리는 중 · 회색 쉬는 중 · 빨강 확인 필요")),
        table.el, detail),
      h("div", {class: ["rm-col", "rm-right"]},
        panel("rm-a-pulse", "팀 맥박 · TEAM PULSE", "지난 24시간", pulse),
        panel("rm-a-feed", "활동 · ACTIVITY", "모든 자리의 최근 기록", feed))),
    panel("rm-a-roster", "자리 · ROSTER", "그림 없이 같은 내용 · 묶음마다", roster),
    h("p", {class: "dk-ps rm-foot"}, "보기만 하는 화면 · 15초마다 새로 읽어요 · AI 분석팀은 기록을 읽고 설명만 해요 (거래하지 않아요) · 사람 모양 그림은 장식이에요"));

  function tickClock() {
    const now = serverNow(), two = (x) => String(x).padStart(2, "0");
    const k = new Date(now + 9 * 3600 * 1000), u = new Date(now);
    clockK.textContent = `${two(k.getUTCHours())}:${two(k.getUTCMinutes())}:${two(k.getUTCSeconds())}`;
    clockU.textContent = `${two(u.getUTCHours())}:${two(u.getUTCMinutes())} UTC`;
    put(closes, nextCloses(now).map((c) => h("div", {class: "rm-cl"}, h("small", {class: "dk-mono"}, `${c.ko} 마감`),
      h("b", {class: "num"}, clockKo(c.left)), h("small", {class: "dk-ps"}, fmt.hm(c.at)))));
    if (st.d) table.panels(panelSpecs(st.d, now));     // the 3D room's floating screens (their clock counts down too)
  }
  function drawTop(d) {
    const c = stateCounts(d.seats);
    put(counts, STATE_ORDER.map((k) => h("span", {class: ["rm-cnt", k]}, h("i"), `${(d.states_ko || {})[k] || k} ${c[k]}`)));
  }
  function drawTeam(d) {
    const t = d.team || {};
    const row = (k, v, cls) => h("div", {class: "rm-kv"}, h("small", {class: "dk-mono"}, k), h("b", {class: ["num", cls || ""]}, v));
    put(team, h("div", {class: "rm-kvs"},
      row("잔고", ok(t.equity) ? fmt.usd(t.equity) : "—"),
      row("시작 대비", ok(t.pnl) ? `${t.pnl >= 0 ? "+" : ""}${fmt.usd(t.pnl)}` : "—", ok(t.pnl) ? (t.pnl >= 0 ? "up" : "down") : ""),
      row("오늘 손익", ok(t.today_pnl) ? `${t.today_pnl >= 0 ? "+" : ""}${fmt.usd(t.today_pnl)}` : "—", ok(t.today_pnl) ? (t.today_pnl >= 0 ? "up" : "down") : ""),
      row("닫힌 거래", ok(t.n) ? `${fmt.int(t.n)}번` : "—"),
      row("승 / 패", ok(t.n) ? `${fmt.int(t.wins || 0)} / ${fmt.int(Math.max(0, (t.n || 0) - (t.wins || 0)))}` : "—"),
      row("열린 포지션", ok(t.open) ? `${fmt.int(t.open)}개` : "—")));
  }
  function drawPos(d) {
    const ps = d.positions || [];
    put(pos, ps.length ? ps.map((p) => h("div", {class: ["rm-p", Number(p.side) > 0 ? "up" : "down"]},
      h("b", null, `${p.coin || p.symbol} ${Number(p.side) > 0 ? "롱" : "숏"}`), h("small", null, p.bot_ko || ""),
      h("small", {class: "dk-mono"}, `진입 ${px(p.entry)} · 손절 ${px(p.stop)}${p.step ? ` · ${p.step}단계` : ""}${p.leverage ? ` · ${p.leverage}배` : ""}`)))
      : ui.empty("열린 포지션이 없어요"));
  }
  function drawPulse(d) {
    put(pulse, pulseRows(d.pulse).map(([ko, n, f]) => h("div", {class: "rm-pr"}, h("small", {class: "dk-mono"}, ko),
      h("span", {class: "rm-bar"}, h("i", {style: {width: `${Math.round(f * 100)}%`}})), h("b", {class: "num"}, fmt.int(n)))));
  }
  function drawFeed(d) {
    const now = serverNow(), rows = (d.feed || []).slice(0, 30);
    put(feed, rows.length ? rows.map((r) => h("div", {class: "rm-f"}, h("small", {class: "dk-mono num"}, fmt.hm(r.ts)),
      h("span", {class: ["rm-chip", (r.seat || "").split("-")[1] === "paper" ? "paper" : (r.seat || "").startsWith("team") ? "ai" : (r.seat || "").endsWith("check") ? "check" : "bot"]}, r.who_ko),
      h("span", {class: "rm-ft"}, `${r.kind_ko} · ${r.text}`), h("small", {class: "dk-ps"}, agoKo(now, r.ts))))
      : ui.empty("아직 기록이 없어요"));
  }
  function drawRoster(d) {
    const now = serverNow(), groups = d.groups_ko || {};
    put(roster, Object.keys(groups).map((gk) => {
      const ss = (d.seats || []).filter((s) => s.group === gk);
      if (!ss.length) return null;
      return h("div", {class: "rm-rg"}, h("small", {class: "dk-mono"}, groups[gk]),
        ss.map((s) => h("button", {type: "button", class: ["rm-rs", s.state, st.sel === s.id ? "on" : ""], onclick: () => { table.pick(s.id); pick(s); drawRoster(d); }},
          h("i"), h("b", null, s.name_ko), h("small", null, s.role_ko), h("small", {class: "rm-line"}, `${s.state_ko} · ${agoKo(now, s.last_ms)}`))));
    }));
  }
  function drawDetail() {
    const s = st.d && (st.d.seats || []).find((x) => x.id === st.sel);
    if (!s) { put(detail, h("small", {class: "dk-ps"}, "이름표나 아래 자리를 누르면 그 프로그램이 마지막에 한 일이 나와요")); return; }
    put(detail, h("div", {class: ["rm-dc", s.state]}, h("b", null, `${s.name_ko} · ${(st.d.groups_ko || {})[s.group] || ""}`),
      h("small", null, s.role_ko), h("small", {class: "rm-line"}, `${s.state_ko} · ${agoKo(serverNow(), s.last_ms)}`),
      h("span", null, `마지막 기록: ${s.last_ko || "—"}`), s.unit ? h("small", {class: "dk-mono"}, `systemd · ${s.unit}`) : null));
  }
  function draw() {
    const d = st.d;
    if (!d) return;
    drawTop(d); drawTeam(d); drawPos(d); drawPulse(d); drawFeed(d); drawRoster(d); drawDetail();
    table.set(d.seats, serverNow());
    tickClock();
  }
  async function load() {
    if (st.busy) return;
    st.busy = true;
    let d;
    try { d = await ctx.api(ROOM_API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      if (st.d) put(slot, ui.staleNote(e, st.okAt, () => load().catch(() => {})));
      else put(slot, ui.errorBox(e, () => load()));
      throw e;
    } finally { st.busy = false; }
    if (!ctx.alive()) return;
    put(slot);
    st.d = d; st.okAt = Date.now();
    draw();
  }
  put(roster, ui.empty("불러오는 중"));
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  ctx.every(1000, tickClock);
  return {el, set() {}};
}
