// 터미널 칸 크기를 끌어서 조절 (term-plus, owners' review 10/06: "아래 표는 열린 포지션 24개 중 4줄만 보이고 차트는 1156×456. 칸 크기가 고정이라
// '오늘은 포지션 표를 크게' 같은 조절을 할 수 없다. 바이낸스, Bybit, TradingView는 경계를 끌어서 바꾼다"):
//   - 왼쪽 칸 | 가운데 사이, 가운데 | 오른쪽 칸 사이 (너비) and 차트 | 아래 표 사이 (높이): a thin handle in each gap.
//   - drag it with the mouse or a finger; or focus it (Tab) and press the arrow keys (Shift = bigger steps, Home = smallest,
//     End = biggest); double-click or Enter = back to the original size of THAT handle.
//   - T = 차트 위주 ↔ 표 위주 (the table's height flips between small and big), when no box is being typed in.
//   - remembered per device (local "term-rs"), and checked again whenever the window changes: a saved size is clamped to what
//     the window can hold (the chart keeps at least 480 px of width and 230 px of height, the side columns and the table keep
//     a usable minimum), every minimum grows with the 글자 크기 (--ts), and a window that cannot hold both minimums simply
//     uses the original layout. Below 1200 px wide (the stacked tablet layout) or 640 px tall nothing is changed and the
//     handles are hidden.
// The original sizes come from terminal.css (they depend on the window and the 글자 크기): this file measures them and only
// writes CSS variables (--rs-l, --rs-r, --rs-t) behind data-rsc / data-rsh on .term; clearing them restores the layout exactly.
import {h, local, motion} from "../core/pb.js";

const GAP = 8;                        // the grid's gap (terminal.css)
const MIN_L = 220, MIN_R = 240, MIN_MID = 480, MIN_T = 132, MIN_CHART = 230;
const STEP = 24, STEP_BIG = 96;
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const typing = (el) => !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
const px = (n) => `${Math.round(n)}px`;

/**
 * paneResize(ctx, {root, grid, left, right, mid, strip, table}) -> {apply(), reset(), preset(kind), state()}
 *   root: .term; grid: .term-grid (left, mid, right inside); strip: the coin strip (first row of mid); table: the table panel.
 */
export function paneResize(ctx, {root, grid, left, right, mid, strip, table}) {
  const saved = local.get("term-rs", {}) || {};
  const rs = {l: Number.isFinite(saved.l) ? saved.l : null, r: Number.isFinite(saved.r) ? saved.r : null, t: Number.isFinite(saved.t) ? saved.t : null};
  const save = () => local.set("term-rs", {l: rs.l, r: rs.r, t: rs.t});
  const wideQ = typeof matchMedia === "function" ? matchMedia("(min-width: 1200px) and (min-height: 640px)") : null;
  const wide = () => (wideQ ? wideQ.matches : true);
  const tsOf = () => { const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ts")); return Number.isFinite(v) && v > 0 ? v : 1; };

  // ---- the three handles
  const mkHandle = (id, vertical, label) => h("div", {class: ["term-rs", vertical ? "v" : "hz"], "data-rs": id, role: "separator", tabindex: "0",
    "aria-orientation": vertical ? "vertical" : "horizontal", "aria-label": label, title: `${label.split(" (")[0]}: 끌어서 크기를 바꿉니다 · 두 번 누르면 원래대로 · T 키 = 차트 크게 ↔ 표 크게`},
  h("i", {class: "term-rs-grip", "aria-hidden": "true"}));
  const hL = mkHandle("l", true, "왼쪽 칸 너비 (끌거나 좌우 화살표 · Enter = 원래대로)");
  const hR = mkHandle("r", true, "오른쪽 칸 너비 (끌거나 좌우 화살표 · Enter = 원래대로)");
  const hT = mkHandle("t", false, "아래 표 높이 (끌거나 위아래 화살표 · Enter = 원래대로)");
  grid.append(hL, hR);
  mid.append(hT);

  /** the limits for this window: {l: [min, max], r: [min, max], t: [min, max] | null} given the original sizes */
  function limits(dl, dr) {
    const ts = tsOf(), gw = grid.clientWidth, cap = gw * 0.45;
    const minL = MIN_L * ts, minR = MIN_R * ts, minMid = MIN_MID;
    const maxL = (r) => Math.min(cap, gw - 2 * GAP - r - minMid), maxR = (l) => Math.min(cap, gw - 2 * GAP - l - minMid);
    const midH = mid.clientHeight, stripH = strip ? strip.offsetHeight : 0;
    const minT = MIN_T * ts, maxT = midH - stripH - 2 * GAP - MIN_CHART * ts;
    return {minL, minR, maxL, maxR, minT, maxT, ok: maxL(dr) >= minL && maxR(dl) >= minR, okT: maxT >= minT};
  }

  let cur = {l: 0, r: 0, t: 0, lim: null};          // what is on screen now (for aria and the keys)
  function apply() {
    root.removeAttribute("data-rsc"); root.removeAttribute("data-rsh");
    const on = wide();
    for (const x of [hL, hR, hT]) x.hidden = !on;
    if (!on) return;
    const dl = left.offsetWidth, dr = right.offsetWidth, dt = table.offsetHeight;       // the original sizes (no override now)
    const lim = limits(dl, dr);
    let l = dl, r = dr, t = dt;
    if ((rs.l != null || rs.r != null) && lim.ok) {
      l = clamp(rs.l ?? dl, lim.minL, lim.maxL(rs.r ?? dr));
      r = clamp(rs.r ?? dr, lim.minR, lim.maxR(l));
      grid.style.setProperty("--rs-l", px(l)); grid.style.setProperty("--rs-r", px(r));
      root.dataset.rsc = "1";
    }
    if (rs.t != null && lim.okT) {
      t = clamp(rs.t, lim.minT, lim.maxT);
      mid.style.setProperty("--rs-t", px(t));
      root.dataset.rsh = "1";
    }
    cur = {l, r, t, lim, dl, dr, dt};
    place();
  }
  /** the handles sit in the gaps: measured from the boxes themselves */
  function place() {
    if (hL.hidden) return;
    hL.style.left = px(left.offsetLeft + left.offsetWidth + GAP / 2);
    hR.style.left = px(right.offsetLeft - GAP / 2);
    hT.style.top = px(table.offsetTop - GAP / 2);
    const lim = cur.lim;
    if (!lim) return;
    const info = (el, now, min, max, lab) => {
      el.setAttribute("aria-valuemin", String(Math.round(min))); el.setAttribute("aria-valuemax", String(Math.round(max)));
      el.setAttribute("aria-valuenow", String(Math.round(now))); el.setAttribute("aria-valuetext", `${lab} ${Math.round(now)}픽셀`);
    };
    info(hL, cur.l, lim.minL, lim.maxL(cur.r), "왼쪽 칸 너비");
    info(hR, cur.r, lim.minR, lim.maxR(cur.l), "오른쪽 칸 너비");
    info(hT, cur.t, lim.minT, Math.max(lim.minT, lim.maxT), "아래 표 높이");
    root.classList.toggle("rs-custom", rs.l != null || rs.r != null || rs.t != null);
  }

  function set(which, v, persist = true) {
    rs[which] = v;
    if (persist) save();
    apply();
  }
  /** a new size from a drag or a key: only the handle's own number, clamped by apply() */
  function setWidth(which, v) {
    if (!cur.lim) return;
    if (which === "l") rs.l = clamp(v, cur.lim.minL, cur.lim.maxL(cur.r));
    else rs.r = clamp(v, cur.lim.minR, cur.lim.maxR(cur.l));
    apply();
  }
  const setHeight = (v) => { if (!cur.lim || !cur.lim.okT) return; rs.t = clamp(v, cur.lim.minT, cur.lim.maxT); apply(); };

  // ---- the mouse / finger
  function drag(handle) {
    const which = handle.dataset.rs;
    handle.addEventListener("pointerdown", (e) => {
      if (e.button != null && e.button !== 0) return;
      e.preventDefault();
      handle.setPointerCapture(e.pointerId);
      handle.classList.add("on");
      document.documentElement.classList.add("term-rsing");
      const g = grid.getBoundingClientRect(), m = mid.getBoundingClientRect();
      const move = (ev) => {
        if (which === "l") setWidth("l", ev.clientX - g.left - GAP / 2);
        else if (which === "r") setWidth("r", g.right - ev.clientX - GAP / 2);
        else setHeight(m.bottom - ev.clientY - GAP / 2);
      };
      const end = () => {
        handle.releasePointerCapture && handle.hasPointerCapture && handle.hasPointerCapture(e.pointerId) && handle.releasePointerCapture(e.pointerId);
        handle.removeEventListener("pointermove", move); handle.removeEventListener("pointerup", end); handle.removeEventListener("pointercancel", end);
        handle.classList.remove("on");
        document.documentElement.classList.remove("term-rsing");
        save();
      };
      handle.addEventListener("pointermove", move); handle.addEventListener("pointerup", end); handle.addEventListener("pointercancel", end);
    });
    handle.addEventListener("dblclick", () => reset(which));
    handle.addEventListener("keydown", (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const st = e.shiftKey ? STEP_BIG : STEP;
      let used = true;
      if (e.key === "Enter") reset(which);
      else if (which === "t") {
        if (e.key === "ArrowUp") setHeight(cur.t + st);
        else if (e.key === "ArrowDown") setHeight(cur.t - st);
        else if (e.key === "Home") setHeight(cur.lim.minT);
        else if (e.key === "End") setHeight(cur.lim.maxT);
        else used = false;
      } else {
        const sign = which === "l" ? 1 : -1;                       // the right column grows when its handle moves left
        const curW = which === "l" ? cur.l : cur.r;
        if (e.key === "ArrowRight") setWidth(which, curW + sign * st);
        else if (e.key === "ArrowLeft") setWidth(which, curW - sign * st);
        else if (e.key === "Home") setWidth(which, which === "l" ? cur.lim.minL : cur.lim.minR);
        else if (e.key === "End") setWidth(which, which === "l" ? cur.lim.maxL(cur.r) : cur.lim.maxR(cur.l));
        else used = false;
      }
      if (used) { e.preventDefault(); save(); }
    });
  }
  for (const x of [hL, hR, hT]) drag(x);

  function reset(which) {
    if (!which) { rs.l = rs.r = rs.t = null; }
    else if (which === "l") rs.l = null;
    else if (which === "r") rs.r = null;
    else rs.t = null;
    save(); apply();
  }
  /** T: 차트 위주 ↔ 표 위주 (the table's height small / big); kind forces one of them */
  function preset(kind) {
    if (!cur.lim || !cur.lim.okT) return;
    const room = cur.lim.maxT + cur.lim.minT;                      // the chart + the table share this much
    const big = (cur.t || cur.dt) > 0.45 * room;                   // the table is already large: go chart-first
    const want = kind || (big ? "chart" : "table");
    setHeight(want === "chart" ? cur.lim.minT : cur.lim.maxT * 0.9);
    save();
    if (!motion.reduced()) { hT.classList.add("on"); setTimeout(() => hT.classList.remove("on"), 500); }
  }
  ctx.listen(document, "keydown", (e) => {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.isComposing || typing(e.target) || document.querySelector(".tour-card")) return;
    if ((e.key === "t" || e.key === "T") && !e.repeat && wide()) { e.preventDefault(); preset(); }
  });

  // ---- keep it right whenever the window or the boxes change
  if (typeof ResizeObserver === "function") {
    let busy = false;
    const ro = new ResizeObserver(() => { if (busy) return; busy = true; requestAnimationFrame(() => { busy = false; if (ctx.alive()) apply(); }); });
    ro.observe(grid); ro.observe(mid);
    ctx.track(() => ro.disconnect());
  }
  if (wideQ && wideQ.addEventListener) { wideQ.addEventListener("change", apply); ctx.track(() => wideQ.removeEventListener("change", apply)); }
  requestAnimationFrame(apply);
  return {apply, reset, preset, state: () => ({...rs})};
}
