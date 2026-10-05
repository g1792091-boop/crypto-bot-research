// 흐름 kit: the group race chart, used by the 흐름 screen (#/flow) and by the small race card on home (raceMini).
// Data: /api/v4/flow/race (dash/more/flow.py): each group's MEDIAN balance over the run (equity rows, 5-minute
// samples, the last one of each step carried forward) and the coin flips' middle 50 % as the baseline band.
// HONESTY: the lines are real server series (nothing drawn before two real points: a designed '곡선 수집 전'
// instead); the order at the right edge is an interim order, never a verdict (참고 + refNote where it is shown);
// the replay walks the stored history only when the viewer presses play, never on its own, never under
// prefers-reduced-motion, and it pauses when the page is hidden.
import {h, s, put, ui, fmt, motion} from "../core/pb.js";

export const RACE_API = "/api/v4/flow/race";
// server group key -> this page's group id (fmt.SERVER_GROUP); one fixed colour per group (flow-kit.css)
export const LANES = [{key: "core", id: "core"}, {key: "ds200", id: "ds"}, {key: "reel", id: "m5"}, {key: "flip", id: "coin"}];
export const laneKo = (id) => fmt.GROUP_KO[id] || id;
/** Short names where room is tight (tables, the calendar picker). */
export const SHORT = {core: "기존 36", ds: "딥시크", m5: "5분봉", coin: "동전 봇"};
const DAY = 86400000;
let UID = 0;

/** D+n of a time in the run on the checkpoint clock (server restart_banner: whole days since 00:00 UTC of the start
 *  day), so the replay counter agrees with the D+n chip in the top bar. */
export const dayN = (t, start) => Math.max(0, Math.floor((t - (start - (start % DAY))) / DAY));

/** The kit's css for screens that are not 흐름 (home): flow.css @imports the same file. */
export function ensureKitCss() {
  if (typeof document === "undefined" || document.querySelector("link[data-flow-kit]")) return;
  document.head.append(h("link", {rel: "stylesheet", href: "/static/v4/screens/flow-kit.css", dataset: {flowKit: "1"}}));
}

/** /api/v4/flow/race -> the chart's model (returns as ratios to the starting balance), or null before 2 real points. */
export function prep(d) {
  if (!d || !d.ready || !Array.isArray(d.t) || d.t.length < 2) return null;
  const init = Number(d.initial) || 5000;
  const md = d.median || {}, band = d.band || {}, n = d.n || {};
  const r = (xs) => (Array.isArray(xs) ? xs : []).map((v) => (v == null || !Number.isFinite(v) ? null : v / init - 1));
  const lanes = LANES.filter((l) => n[l.key] > 0).map((l) => ({...l, n: n[l.key], v: r(md[l.key])}));
  const real = lanes.some((l) => l.v.filter((v) => v != null).length >= 2);
  if (!real) return null;
  return {t: d.t, start: d.start, now: d.now, verdict: d.next_verdict || null, k: d.verdict_k || 1, step: d.step,
    lanes, lo: r(band.lo), hi: r(band.hi), f5: r(md.flip5m), n5: n.flip5m || 0, busts: d.busts || [], initial: init};
}

/** The value of series xs (at times T) at time t: linear between the two neighbouring points; null outside. */
export function valueAt(xs, T, t) {
  if (!T.length || t < T[0]) return null;
  if (t >= T[T.length - 1]) return xs[T.length - 1];
  let lo = 0, hi = T.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (T[m] <= t) lo = m; else hi = m; }
  const a = xs[lo], b = xs[hi];
  if (a == null || b == null) return a ?? b;
  return a + (b - a) * (t - T[lo]) / (T[hi] - T[lo] || 1);
}

/** The order of the lanes at time t (highest median first). */
export function orderAt(m, t) {
  return m.lanes.map((l) => ({...l, at: valueAt(l.v, m.t, t)})).sort((a, b) => (b.at ?? -9) - (a.at ?? -9));
}

function niceStep(span, want) {
  const c = [0.001, 0.002, 0.0025, 0.005, 0.01, 0.02, 0.025, 0.05, 0.1, 0.2, 0.25, 0.5, 1];
  return c.find((x) => span / x <= want) || 1;
}
const pts = (xs, X, Y, T) => {
  let d = "", pen = false;
  for (let i = 0; i < xs.length; i++) {
    if (xs[i] == null) { pen = false; continue; }
    d += `${pen ? "L" : "M"}${X(T[i]).toFixed(1)},${Y(xs[i]).toFixed(1)}`;
    pen = true;
  }
  return d;
};
const tlabel = (t) => `${fmt.mmdd(t)} ${fmt.hm(t)}`;

/**
 * raceChart({mini, height, onTime(t, order), onState("idle"|"playing"|"paused")}) -> div with
 *   .set(model)      draw (keeps the viewer's focus); model from prep()
 *   .focus(id|null)  one group in front, the others dimmed (5분봉 also shows its three 5m coin flips)
 *   .play() / .pause() / .playing()   the replay (no-op under prefers-reduced-motion)
 * Lines are drawn at the box's real pixel width (crisp on phone and PC, redrawn on resize).
 */
export function raceChart(o = {}) {
  const mini = !!o.mini;
  const id = ++UID;
  const svgHost = h("div", {class: "fk-svg"});
  const labels = h("div", {class: "fk-labels", "aria-hidden": "true"});
  const chip = h("div", {class: "fk-chip", hidden: true});
  const box = h("div", {class: ["fk-race", mini ? "mini" : ""], style: {height: o.height ? o.height + "px" : null}}, svgHost, labels, chip);
  const st = {m: null, W: 0, focus: null, mode: o.mode || "auto", events: [], t: null, reveal: null, g: null, labs: new Map(), order: "", raf: 0, p: 0, playing: false, hover: false};

  // "auto": the 30-day road once a third of the way is behind (before that the lines would be a few pixels wide)
  function resolved() {
    const m = st.m;
    if (st.mode !== "auto") return st.mode;
    return m && m.verdict && (m.now - m.start) < (m.verdict - m.start) / 3 ? "now" : "road";
  }

  function textScale() {
    const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ts"));
    return v > 0 ? v : 1;
  }

  function geometry(W, H) {
    const m = st.m;
    // the label gutter grows with the 글자 크기 setting (--ts on <html>); the screen is drawn again when it changes
    const gut = mini ? 6 : Math.round((W < 520 ? 112 : 140) * textScale());
    // two views of the road still to go (now -> the verdict): "road" (the owners' 30일 길) draws the axis to scale up to
    // the verdict day with the finish flag; "now" gives the lines the whole width and shows the rest as a short hatched
    // stub that is NOT to scale ('남은 n일')
    const ahead = !mini && m.verdict && m.verdict > m.now;
    const road = ahead && resolved() === "road";
    const stub = ahead && !road ? (W < 520 ? 40 : 58) : 0;
    const x0 = mini ? 2 : 42, x1 = W - gut - stub, y0 = mini ? 4 : 14, y1 = H - (mini ? 4 : 24);
    const end = road ? m.verdict : m.now;
    const X = (t) => x0 + (x1 - x0) * (t - m.start) / ((end - m.start) || 1);
    // the scale: every group median and the coin band. A one- or few-account group (the reel: one account) swings far
    // more than a median of 144; when it would squash the others flat it runs off the edge (its label keeps the true
    // value with an arrow, and the viewer can ask for the full range or pick that group: then it is in the scale)
    const ext = (xs) => { let a = Infinity, b = -Infinity; for (const v of xs) if (v != null) { if (v < a) a = v; if (v > b) b = v; } return [a, b]; };
    const [blo, bhi] = ext([0, ...m.lo, ...m.hi, ...m.lanes.filter((l) => l.n >= 5).flatMap((l) => l.v)]);
    let lo = blo, hi = bhi;
    const clipped = [], far = [];
    const span0 = Math.max(bhi - blo, 0.004);
    for (const l of m.lanes.filter((x) => x.n < 5)) {
      const [a, b] = ext(l.v);
      if (!Number.isFinite(a)) continue;
      const isFar = a < blo - 1.5 * span0 || b > bhi + 1.5 * span0;
      if (isFar) far.push(l.id);
      if (isFar && !st.full && st.focus !== l.id) { clipped.push(l.id); lo = Math.min(lo, Math.max(a, blo - 0.6 * span0)); hi = Math.max(hi, Math.min(b, bhi + 0.6 * span0)); }
      else { lo = Math.min(lo, a); hi = Math.max(hi, b); }
    }
    const pad = (hi - lo) * 0.1 || 0.002;
    lo -= pad; hi += pad;
    const Y = (v) => y1 - (y1 - y0) * (v - lo) / (hi - lo);
    const Yc = (v) => Math.max(y0, Math.min(y1, Y(v)));
    return {x0, x1, y0, y1, end, X, Y, Yc, lo, hi, gut, stub, road, W, H, clipped, far, ix: (px) => m.start + (px - x0) / ((x1 - x0) || 1) * ((end - m.start) || 1)};
  }

  function draw() {
    const m = st.m, W = st.W, H = box.clientHeight || o.height || 260;
    if (!m || W < 60) return;
    const g = (st.g = geometry(W, H));
    const {x0, x1, y0, y1, X, Y} = g;
    const kids = [];
    const clipId = `fkc${id}`, hatchId = `fkh${id}`;
    kids.push(s("defs", null,
      s("clipPath", {id: clipId}, (st.clip = s("rect", {x: 0, y: y0 - 1, width: W, height: y1 - y0 + 2}))),
      s("pattern", {id: hatchId, width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)"},
        s("rect", {class: "fk-hatch", x: 0, y: 0, width: 2, height: 6}))));
    if (!mini) {
      const step = niceStep(g.hi - g.lo, 4);
      for (let v = Math.ceil(g.lo / step) * step; v <= g.hi + 1e-12; v += step) {
        const y = Y(v).toFixed(1);
        if (Math.abs(v) < 1e-9) continue;
        kids.push(s("line", {class: "grid", x1: x0, x2: x1, y1: y, y2: y}),
          s("text", {class: "ax", x: x0 - 6, y: (Y(v) + 4).toFixed(1), "text-anchor": "end"}, fmt.pct(v, step < 0.01 ? 1 : 0)));
      }
      kids.push(s("text", {class: "ax", x: x0 - 6, y: (Y(0) + 4).toFixed(1), "text-anchor": "end"}, "0%"));
      // the road still to go, hatched, with the days left, the outside events on it (to scale only) and the flag
      if (g.road || g.stub) {
        const sx = g.road ? X(m.now) : x1 + 5, xv = g.road ? X(m.verdict) : x1 + g.stub - 1, cx = ((sx + xv) / 2).toFixed(1);
        const left = Math.max(0, Math.ceil((m.verdict - m.now) / DAY));
        kids.push(s("rect", {class: "fk-future", x: sx.toFixed(1), y: y0, width: Math.max(0, xv - sx).toFixed(1), height: y1 - y0, fill: `url(#${hatchId})`}));
        if (xv - sx > 64) kids.push(s("text", {class: "fk-left big", x: cx, y: (y0 + 16).toFixed(1), "text-anchor": "middle"}, `남은 ${fmt.int(left)}일`));
        else if (xv - sx > 26) kids.push(s("text", {class: "fk-left", x: cx, y: (y0 + 30).toFixed(1), "text-anchor": "middle"}, "남은"),
          s("text", {class: "fk-left big", x: cx, y: (y0 + 46).toFixed(1), "text-anchor": "middle"}, `${fmt.int(left)}일`));
        if (g.road) for (const ev of st.events || []) {
          const t = Number(ev.ts_ms);
          if (!(t > m.now && t <= m.verdict)) continue;
          const x = X(t);
          kids.push(s("g", {class: "fk-ev", transform: `translate(${x.toFixed(1)},${(y1 - 6).toFixed(1)})`},
            s("rect", {x: -3, y: -3, width: 6, height: 6, transform: "rotate(45)"}),
            s("text", {x: 0, y: -8, "text-anchor": x > xv - 22 ? "end" : x < sx + 16 ? "start" : "middle"}, String(ev.kind || "").slice(0, 5)),
            s("title", null, `${ev.name_ko || ev.kind} · ${tlabel(t)}`)));
        }
        kids.push(s("line", {class: "fk-vline", x1: xv, x2: xv, y1: y0, y2: y1}),
          s("g", {class: "fk-flag", transform: `translate(${(xv).toFixed(1)},${y0 - 2})`, "shape-rendering": "crispEdges"},
            s("rect", {x: 0, y: 0, width: 2, height: 16}), s("rect", {class: "f1", x: 2, y: 0, width: 4, height: 3}),
            s("rect", {class: "f2", x: 6, y: 0, width: 4, height: 3}), s("rect", {class: "f2", x: 2, y: 3, width: 4, height: 3}),
            s("rect", {class: "f1", x: 6, y: 3, width: 4, height: 3})));
      }
    }
    kids.push(s("line", {class: "base", x1: x0, x2: x1, y1: Y(0).toFixed(1), y2: Y(0).toFixed(1)}));
    // the coin flips: their middle 50 % as a band, their median dashed (the baseline, drawn first)
    const lanes = [];
    const band = [];
    for (let i = 0; i < m.t.length; i++) if (m.hi[i] != null) band.push(`${X(m.t[i]).toFixed(1)},${Y(m.hi[i]).toFixed(1)}`);
    for (let i = m.t.length - 1; i >= 0; i--) if (m.lo[i] != null) band.push(`${X(m.t[i]).toFixed(1)},${Y(m.lo[i]).toFixed(1)}`);
    if (band.length > 2) lanes.push(s("path", {class: "fk-band", d: "M" + band.join("L") + "Z"}));
    if (m.n5 && m.f5.some((v) => v != null)) lanes.push(s("path", {class: "ln f5", d: pts(m.f5, X, Y, m.t)}));
    const order = ["coin", "ds", "core", "m5"];
    for (const l of [...m.lanes].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id))) {
      lanes.push(s("path", {class: ["ln", l.id], d: pts(l.v, X, Y, m.t), dataset: {lane: l.id}}));
    }
    if (!mini) for (const [t, gk] of m.busts) {
      const lane = LANES.find((x) => x.key === gk);
      const x = X(t).toFixed(1);
      lanes.push(s("rect", {class: ["fk-bust", lane ? lane.id : ""], x: (X(t) - 1.5).toFixed(1), y: y1 - 7, width: 3, height: 7},
        s("title", null, `파산 · ${lane ? laneKo(lane.id) : ""} · ${tlabel(t)}`)), s("line", {class: "fk-bustl", x1: x, x2: x, y1: y1 - 7, y2: y1}));
    }
    kids.push(s("g", {"clip-path": `url(#${clipId})`, class: "fk-lanes"}, lanes));
    if (!mini) {
      kids.push(s("text", {class: "ax", x: x0, y: H - 6}, fmt.mmdd(m.start)));
      const xn = X(m.now), xv = g.road ? X(m.verdict) : x1 + g.stub - 1;
      if (xn - x0 > 34 && (!g.road || xv - xn > 16)) kids.push(s("text", {class: "ax now", x: xn.toFixed(1), y: H - 6, "text-anchor": g.road ? "middle" : "end"}, "지금"));
      if (g.road || g.stub) kids.push(s("text", {class: "ax fk-vlab", x: (xv + 4).toFixed(1), y: H - 6}, `판정 ${fmt.mmdd(m.verdict)}`));
      st.cross = s("line", {class: "fk-cross", x1: 0, x2: 0, y1: y0, y2: y1, visibility: "hidden"});
      kids.push(st.cross);
    }
    st.heads = new Map();
    st.links = new Map();
    for (const l of m.lanes) {
      if (!mini) { const ln = s("line", {class: ["fk-link", l.id]}); st.links.set(l.id, ln); kids.push(ln); }
      const c = s("circle", {class: ["fk-head", l.id], r: mini ? 2.4 : 3.6});
      st.heads.set(l.id, c);
      kids.push(c);
    }
    const hit = mini ? null : s("rect", {class: "fk-hit", x: x0, y: 0, width: Math.max(0, x1 - x0), height: H});
    if (hit) kids.push(hit);
    const svg = s("svg", {class: ["chart", "fk-chart"], viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img",
      "aria-label": "묶음별 잔고 중앙값의 흐름: " + orderAt(m, m.now).map((l) => `${laneKo(l.id)} ${fmt.pct(l.at)}`).join(", ")}, kids);
    svgHost.replaceChildren(svg);
    if (hit) wire(hit);
    applyFocus();
    view(st.t ?? m.now, st.reveal ?? m.now);
    if (o.onClip) o.onClip(g.far, g.clipped);
  }

  function label(l) {
    let el = st.labs.get(l.id);
    if (!el) {
      el = {root: h("div", {class: ["fk-lab", l.id]}), rk: h("b", {class: "fk-rk num"}, "0"), nm: h("span", {class: "fk-nm"}, laneKo(l.id)), vv: h("span", {class: "fk-vv num"}, "—")};
      el.root.append(h("span", {class: "fk-l1"}, h("i", {class: ["fk-sw", l.id === "coin" ? "band" : l.id]}), el.nm), h("span", {class: "fk-l2"}, el.rk, el.vv));
      st.labs.set(l.id, el);
      labels.append(el.root);
    }
    return el;
  }

  /** Heads, links and labels at time t; lines revealed up to `reveal`. */
  function view(t, reveal) {
    const m = st.m, g = st.g;
    if (!m || !g) return;
    st.t = t; st.reveal = reveal;
    if (st.clip) st.clip.setAttribute("width", Math.max(0, g.X(reveal) - 0 + 4).toFixed(1));
    const ord = orderAt(m, t);
    const xh = g.X(t);
    for (const l of ord) {
      const c = st.heads.get(l.id);
      if (!c) continue;
      if (l.at == null || t > reveal + 1) { c.setAttribute("visibility", "hidden"); continue; }
      c.setAttribute("visibility", "visible");
      c.setAttribute("cx", xh.toFixed(1)); c.setAttribute("cy", g.Yc(l.at).toFixed(1));
      c.classList.toggle("out", g.Y(l.at) < g.y0 || g.Y(l.at) > g.y1);
    }
    if (!mini) {
      // labels in the right gutter, in order, at their line's height (pushed apart so they never overlap)
      // label pitch = the real label height (it grows with the bigger type and 글자 크기), measured once per draw
      // of the chart; 34 px is the floor the old fixed pitch used
      if (!st.lh) { const h0 = ord.length ? label(ord[0]).root.offsetHeight : 0; if (h0) st.lh = Math.max(34, Math.ceil(h0) + 3); }
      const LH = st.lh || Math.round(40 * textScale()), top = g.y0 - 4, bot = g.y1 - LH + 4;
      const ys = ord.map((l) => (l.at == null ? bot : g.Yc(l.at) - LH / 2));
      for (let i = 1; i < ys.length; i++) ys[i] = Math.max(ys[i], ys[i - 1] + LH);
      const over = ys.length ? ys[ys.length - 1] - bot : 0;
      if (over > 0) for (let i = 0; i < ys.length; i++) ys[i] -= over;
      for (let i = 0; i < ys.length; i++) ys[i] = Math.max(top + i * LH, ys[i]);
      const gx = g.x1 + g.stub + 12;
      const sig = ord.map((l) => l.id).join();
      ord.forEach((l, i) => {
        const el = label(l);
        el.root.style.transform = `translate(${gx.toFixed(1)}px, ${ys[i].toFixed(1)}px)`;
        el.root.style.width = (g.W - gx - 2).toFixed(0) + "px";
        el.rk.textContent = String(i + 1);
        const out = l.at != null && (g.Y(l.at) < g.y0 ? "↑ " : g.Y(l.at) > g.y1 ? "↓ " : "");
        el.vv.textContent = l.at == null ? "—" : (out || "") + fmt.pct(l.at, Math.abs(l.at) < 0.1 ? 2 : 0);
        el.root.title = out ? "1계좌라 흔들림이 커서 그래프 밖으로 나갔습니다 (숫자는 실제 값)" : "";
        el.vv.className = "fk-vv num " + fmt.tone(l.at, el.vv.textContent);
        if (st.order && st.order !== sig && st.order.split(",").indexOf(l.id) !== i) motion.play(el.root, "fk-bump");
        const ln = st.links.get(l.id);
        if (ln) {
          const vis = l.at != null && t <= reveal + 1;
          ln.setAttribute("visibility", vis ? "visible" : "hidden");
          if (vis) { ln.setAttribute("x1", (xh + 5).toFixed(1)); ln.setAttribute("y1", g.Yc(l.at).toFixed(1)); ln.setAttribute("x2", (gx - 3).toFixed(1)); ln.setAttribute("y2", (ys[i] + LH / 2).toFixed(1)); }
        }
      });
      st.order = sig;
    }
    if (o.onTime) o.onTime(t, ord);
  }

  function wire(hit) {
    const at = (e) => {
      const r = hit.ownerSVGElement.getBoundingClientRect();
      const t = st.g.ix(e.clientX - r.left);
      const m = st.m;
      const tt = Math.max(m.start, Math.min(st.playing ? st.reveal : m.now, t));
      let i = 0;   // snap to the nearest stored point
      for (let k = 0; k < m.t.length; k++) if (Math.abs(m.t[k] - tt) < Math.abs(m.t[i] - tt)) i = k;
      return m.t[i];
    };
    const show = (e) => {
      if (st.playing) return;
      const t = at(e);
      st.hover = true;
      const x = st.g.X(t);
      st.cross.setAttribute("visibility", "visible"); st.cross.setAttribute("x1", x.toFixed(1)); st.cross.setAttribute("x2", x.toFixed(1));
      chip.hidden = false;
      chip.textContent = `${tlabel(t)} · D+${dayN(t, st.m.start)}`;
      chip.style.transform = `translateX(${Math.max(0, Math.min(st.W - 140, x - 70)).toFixed(0)}px)`;
      view(t, st.m.now);
    };
    const hide = () => {
      if (!st.hover) return;
      st.hover = false;
      chip.hidden = true;
      st.cross.setAttribute("visibility", "hidden");
      if (!st.playing) view(st.m.now, st.m.now);
    };
    // a finger lifts at once: keep what it pointed at for a moment (a mouse leaving clears it now)
    let later = 0;
    const leave = (e) => { clearTimeout(later); if (e.pointerType === "touch" || e.pointerType === "pen") later = setTimeout(hide, 2500); else hide(); };
    hit.addEventListener("pointermove", (e) => { clearTimeout(later); show(e); });
    hit.addEventListener("pointerdown", (e) => { clearTimeout(later); show(e); });
    hit.addEventListener("pointerleave", leave);
    hit.addEventListener("pointercancel", leave);
  }

  function applyFocus() {
    box.classList.toggle("focused", !!st.focus);
    for (const p of svgHost.querySelectorAll(".ln[data-lane]")) p.classList.toggle("on", p.dataset.lane === st.focus);
    for (const [k, c] of st.heads || []) c.classList.toggle("dim", !!st.focus && k !== st.focus);
    for (const [k, el] of st.labs) el.root.classList.toggle("dim", !!st.focus && k !== st.focus);
    box.classList.toggle("show-f5", st.focus === "m5");
  }

  // ---------------------------------------------------------------- replay (only when the viewer presses play)
  const dur = () => Math.max(4500, Math.min(9000, (st.m ? st.m.t.length : 0) * 11));
  function frame(now) {
    const m = st.m;
    if (!m || !st.playing) return;
    st.p = Math.min(1, st.p + (now - (st.last || now)) / dur());
    st.last = now;
    const t = m.start + (m.now - m.start) * st.p;
    view(t, t);
    if (st.p >= 1) { st.playing = false; st.p = 0; st.raf = 0; view(m.now, m.now); if (o.onState) o.onState("idle"); return; }
    st.raf = requestAnimationFrame(frame);
  }
  box.play = () => {
    if (!st.m || motion.reduced() || st.playing) return;
    if (st.p <= 0 || st.p >= 1) st.p = 0;
    st.playing = true; st.last = 0;
    chip.hidden = true; st.hover = false;
    if (st.cross) st.cross.setAttribute("visibility", "hidden");
    if (o.onState) o.onState("playing");
    st.raf = requestAnimationFrame((t) => { st.last = t; frame(t); });
  };
  box.pause = () => {
    if (!st.playing) return;
    st.playing = false; cancelAnimationFrame(st.raf); st.raf = 0;
    if (o.onState) o.onState(st.p > 0 && st.p < 1 ? "paused" : "idle");
  };
  box.stop = () => {
    st.playing = false; cancelAnimationFrame(st.raf); st.raf = 0; st.p = 0;
    if (st.m) view(st.m.now, st.m.now);
    if (o.onState) o.onState("idle");
  };
  box.playing = () => st.playing;
  box.focus = (fid) => { const was = st.focus; st.focus = fid || null; if (st.g && st.g.far.length && was !== st.focus) draw(); else applyFocus(); };
  box.full = (on) => { st.full = !!on; draw(); };
  box.mode = (md) => { st.mode = md; if (st.m) draw(); };
  box.resolvedMode = () => resolved();
  /** Outside events (summary.events: CPI, FOMC, ...) drawn as small marks on the road ahead. */
  box.events = (evs) => { const sig = JSON.stringify(evs || []); if (sig === st.evsig) return; st.evsig = sig; st.events = evs || []; if (st.m) draw(); };
  box.set = (m) => {
    const was = st.m;
    st.m = m;
    if (!m) { put(svgHost, emptyArt(mini)); labels.replaceChildren(); st.labs.clear(); st.g = null; return; }
    if (!st.playing) { st.t = m.now; st.reveal = m.now; }
    if (was && st.playing) { /* new data mid-replay: keep the replay's position */ }
    draw();
  };
  const fit = () => {
    const w = Math.round(box.clientWidth);
    if (w > 60 && w !== st.W) { st.W = w; draw(); }
  };
  if (typeof ResizeObserver === "function") new ResizeObserver(fit).observe(box);
  requestAnimationFrame(() => { fit(); if (!st.W) { st.W = 320; draw(); } });
  return box;
}

/** The designed empty state: the road with its finish flag, no line (nothing is made up). */
function emptyArt(mini) {
  return h("div", {class: ["fk-empty", mini ? "mini" : ""]},
    s("svg", {class: "fk-road", viewBox: "0 0 120 24", "aria-hidden": "true", "shape-rendering": "crispEdges"},
      s("rect", {class: "r", x: 0, y: 18, width: 120, height: 2}),
      [0, 16, 32, 48, 64, 80, 96].map((x) => s("rect", {class: "d", x: x + 4, y: 18, width: 8, height: 2})),
      s("rect", {class: "p", x: 108, y: 2, width: 2, height: 16}), s("rect", {class: "f1", x: 110, y: 2, width: 4, height: 3}),
      s("rect", {class: "f2", x: 114, y: 2, width: 4, height: 3}), s("rect", {class: "f2", x: 110, y: 5, width: 4, height: 3}),
      s("rect", {class: "f1", x: 114, y: 5, width: 4, height: 3})),
    h("b", null, "곡선 수집 전"),
    mini ? null : h("span", null, "봇이 1시간 넘게 잔고를 기록하면 묶음마다 선이 그려집니다. 지어낸 선은 그리지 않습니다."));
}

/** A legend row of swatches (tap = focus that group); returns {el, set(order)}. */
export function laneLegend(o = {}) {
  const el = h("div", {class: "fk-legend", role: "group", "aria-label": "묶음 고르기"});
  const btns = new Map();
  let sel = null;
  el.set = (m) => {
    if (!m) { el.replaceChildren(); btns.clear(); return; }
    for (const l of m.lanes) {
      if (btns.has(l.id)) continue;
      const b = h("button", {type: "button", class: ["fk-lg", l.id], "aria-pressed": "false",
        onclick: () => { sel = sel === l.id ? null : l.id; for (const [k, x] of btns) x.setAttribute("aria-pressed", String(k === sel)); o.onPick && o.onPick(sel); }},
        h("i", {class: ["fk-sw", l.id === "coin" ? "band" : l.id]}), h("span", null, laneKo(l.id)), h("small", null, `${fmt.int(l.n)}개`));
      btns.set(l.id, b);
      el.append(b);
    }
  };
  return el;
}

/**
 * raceParts(ctx, {height, onModel, css, short}) -> {chart, list, sub, note} (short: the short group names): the small race without its frame, for home's head card
 * (the four groups' median lines with the coin flips' band, and the order now as the legend: the numbers ARE the
 * lines' right ends, so the legend always matches the curve). It loads /api/v4/flow/race itself every 5 minutes while
 * the screen is open; onModel(model | null) gets each new model (home draws its group-card lines from it).
 */
export function raceParts(ctx, o = {}) {
  if (o.css !== false) ensureKitCss();          // home.css @imports the kit itself (css: false)
  let clipped = [], model = null;
  const chart = raceChart({mini: true, height: o.height || 74, onClip: (_f, c) => { const was = clipped.join(); clipped = c; if (was !== c.join() && model) list.render(); }});
  const list = h("ol", {class: "fk-mlist", "aria-label": "지금 순서 (참고)"});
  const sub = h("span", {class: "sub"});
  const note = ui.note("선 = 묶음 안 계좌 평가금(열린 포지션 포함)의 중앙값 · 회색 띠 = 동전 봇 가운데 50% · 순서는 중간 기록일 뿐 판정이 아닙니다");
  let off = false;
  async function load() {
    if (off) return;
    let d;
    try { d = await ctx.api(RACE_API + "?step=auto"); } catch (e) { if (e && e.status === 404) off = true; if (!model) chart.set(null); return; }
    if (!ctx.alive()) return;
    const m = (model = prep(d));
    chart.set(m);
    if (o.onModel) o.onModel(m);
    if (!m) { list.replaceChildren(); sub.textContent = ""; return; }
    sub.textContent = `D+${dayN(m.now, m.start)} · ${m.step >= DAY ? "하루" : m.step >= 4 * 3600000 ? "4시간" : "1시간"}마다`;
    list.render();
  }
  // the order now; a group whose line runs off the small chart (one account: the reel) carries an arrow. A value that
  // really changed since the last answer gets one soft tint (motion.flash: real data only, never on a timer).
  list.render = () => {
    const was = new Map([...list.querySelectorAll("li[data-id]")].map((li) => [li.dataset.id, li.dataset]));
    put(list, orderAt(model, model.now).map((l) => {
      const shown = fmt.pct(l.at);
      const b = h("b", {class: ["num", fmt.tone(l.at, shown)], title: clipped.includes(l.id) ? "1계좌라 흔들림이 커서 작은 그래프 밖으로 나갑니다" : null},
        clipped.includes(l.id) ? (l.at > 0 ? "↑ " : "↓ ") : "", shown);
      const w = was.get(l.id);
      if (w && w.v !== shown) motion.flash(b, l.at > Number(w.r) ? "up" : "down");
      return h("li", {class: l.id, dataset: {id: l.id, v: shown, r: String(l.at)}}, h("i", {class: ["fk-sw", l.id === "coin" ? "band" : l.id]}),
        h("span", {class: "fk-nm"}, o.short ? SHORT[l.id] || laneKo(l.id) : laneKo(l.id)), b);
    }));
  };
  ctx.every(300000, load, {now: true});
  return {chart, list, sub, note, model: () => model};
}

/**
 * raceMini(ctx) -> a small card: the race parts above in a card with the plate 묶음 레이스 and a "자세히 →" link to
 * #/flow (home puts the same parts inside its head card instead).
 */
export function raceMini(ctx) {
  const p = raceParts(ctx);
  return ui.card({plate: "묶음 레이스", cls: "fk-minicard", label: "묶음 레이스",
    acts: [h("a", {class: "btn-line", href: ctx.href("flow")}, "자세히 →")]},
  h("div", {class: "fk-mtop"}, p.sub, ui.pill("", "ref")), p.chart, p.list, p.note);
}
