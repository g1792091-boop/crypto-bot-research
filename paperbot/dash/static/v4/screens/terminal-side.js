// 터미널 right column: this coin's open positions (live ROE at the mark price, liquidation price; the numbers roll to
// a real new mark), and the chosen group's median balance over the run (/api/v4/flow/race, flow-kit prep) as a line
// with its gradient and glowing end, the daily change bars and the profit calendar of the season
// (/api/v4/flow/calendar, the same answer and colour rule as 흐름 · 수익 달력). Both are read every 5 minutes like 흐름.
// HONESTY: a group median is not a verdict (참고); a day without a record is 기록 없음, never a zero; nothing is drawn
// before two real points.
import {h, s, put, ui, fmt, store, motion, local} from "../core/pb.js";
import {normPos} from "./positions-kit.js";
import {RACE_API, LANES, SHORT, prep} from "./flow-kit.js";
import {CAL_API} from "./flow-cal.js";
import {panel} from "./terminal-kit.js";

// ---------------------------------------------------------------- this coin's positions
/** coinPositions(ctx, st) -> {el, setSym, onBoard, onTicker} */
export function coinPositions(ctx, st) {
  const list = h("div", {class: "term-cp", role: "list"});
  const el = panel("이 코인 포지션", {cls: "term-mine", scroll: true}, list);
  el.append(h("div", {class: "term-pf"}, ui.assume("open")));
  let board = null;
  const rows = new Map();          // account id -> {key, node, roe}
  function render() {
    const mk = store.mark(st.sym);
    const xs = board ? board.accounts.filter((a) => a.position && a.position.symbol === st.sym).map((a) => ({a, p: normPos(a.position)})) : [];
    const main = (x) => (["core", "m5", "extra"].includes(fmt.groupOf(x.a)) ? 0 : 1);
    xs.sort((x, y) => main(x) - main(y) || (y.p.entry_time || 0) - (x.p.entry_time || 0));
    const L = xs.filter((x) => x.p.side > 0).length;
    el.sub.textContent = board ? `${fmt.coin(st.sym)} ${fmt.int(xs.length)}개 · 롱 ${fmt.int(L)} · 숏 ${fmt.int(xs.length - L)}` : "";
    const nodes = xs.slice(0, 20).map((x) => {
      const id = x.a.account_id, key = `${st.sym}|${x.p.entry_time}|${x.p.liq}`;
      let r = rows.get(id);
      if (!r || r.key !== key) {
        const roe = h("b", {class: "num term-roe"}, "—");
        const node = h("a", {class: "term-cr", role: "listitem", href: ctx.href("account", id), title: id},
          ui.sideTag(x.p.side), h("span", {class: "term-fn"}, h("i", {class: ["term-gsw", fmt.groupOf(x.a)], "aria-hidden": "true"}), ui.acctLabel(x.a)),
          h("span", {class: "muted num"}, fmt.lev(x.p.leverage)), roe,
          h("span", {class: "term-lq num", title: "청산가"}, fmt.price(x.p.liq)));
        r = {key, node, roe};
        rows.set(id, r);
      }
      const u = mk && x.p.margin ? (x.p.side * x.p.qty * (mk - x.p.entry)) / x.p.margin : null;
      motion.countTo(r.roe, u, {format: "pct", dec: 1, tone: true, glow: true});
      return r.node;
    });
    if (!nodes.length) put(list, ui.empty(board ? "이 코인에 열린 포지션이 없습니다" : "불러오는 중"));
    else list.replaceChildren(h("div", {class: "term-cr hd", "aria-hidden": "true"}, h("span", null, "방향"), h("span", null, "계좌"), h("span", null, "배수"),
      h("span", null, "ROE"), h("span", null, "청산가")), ...nodes);
  }
  return {el, setSym() { rows.clear(); render(); }, onBoard(b) { board = b; render(); }, onTicker: render};
}

// ---------------------------------------------------------------- group P&L: line + daily bars + calendar
const WD = ["월", "화", "수", "목", "금", "토", "일"];
const pctS = (v) => (v == null ? "—" : fmt.pct(v, Math.abs(v) < 0.01 ? 2 : 1));
let UID = 0;

/** pnlPanel(ctx) -> {el, onBoard} */
export function pnlPanel(ctx) {
  const st = {g: local.get("term-g", "core"), race: null, cal: null};
  if (!SHORT[st.g]) st.g = "core";
  const seg = ui.seg(LANES.map((l) => ({id: l.id, label: SHORT[l.id]})), st.g, (id) => { st.g = id; local.set("term-g", id); draw(true); }, {label: "묶음 고르기"});
  const big = h("b", {class: "num term-pbig"}, "—"), today = h("span", {class: "num term-ptoday"}, "");
  const chartBox = h("div", {class: "term-pchart"});
  const calBox = h("div", {class: "term-cal"});
  const calHead = h("div", {class: "term-calh"}, h("span", {class: "term-calt"}, "수익 달력"), h("span", {class: "grow"}),
    h("a", {class: "term-more", href: ctx.href("flow")}, "흐름 →"));
  const el = panel("누적 손익", {cls: "term-pnl", acts: [ui.pill("", "ref")]},
    seg, h("div", {class: "term-phero"}, h("i", {class: ["fk-sw", "term-psw"], "aria-hidden": "true"}), h("span", {class: "term-pk"}, ""), big, today),
    chartBox, calHead, calBox,
    ui.note("선 = 묶음 안 계좌 잔고(열린 포지션 포함) 중앙값의 수익률 · 막대 = 그날 변화 · 칸 = 한국 시간 하루 · 중간 기록일 뿐 판정이 아닙니다"));
  const sw = el.querySelector(".term-psw"), pk = el.querySelector(".term-pk");

  function line(model, cal) {
    const W = Math.max(200, chartBox.clientWidth || 280), H = Math.max(90, chartBox.clientHeight || 120), barsH = Math.round(H * 0.28), lineH = H - barsH - 6;
    const lane = model && model.lanes.find((l) => l.id === st.g);
    const pts = lane ? lane.v.map((v, i) => [model.t[i], v]).filter(([, v]) => v != null) : [];
    if (pts.length < 2) return h("div", {class: "term-pnone"}, h("b", null, "곡선 수집 전"), h("span", null, "잔고 기록이 두 번 넘게 쌓이면 선이 그려집니다"));
    const ta = pts[0][0], tb = pts[pts.length - 1][0];
    let lo = Math.min(0, ...pts.map((p) => p[1])), hi = Math.max(0, ...pts.map((p) => p[1]));
    const pad = (hi - lo) * 0.12 || 0.002; lo -= pad; hi += pad;
    const X = (t) => 4 + ((t - ta) / Math.max(1, tb - ta)) * (W - 52), Y = (v) => 4 + (1 - (v - lo) / (hi - lo)) * (lineH - 8);
    const d = pts.map(([t, v], i) => `${i ? "L" : "M"}${X(t).toFixed(1)},${Y(v).toFixed(1)}`).join("");
    const end = pts[pts.length - 1], up = end[1] >= 0, id = "tg" + ++UID;
    const kids = [
      s("defs", null, s("linearGradient", {id, x1: 0, y1: 0, x2: 0, y2: 1}, s("stop", {offset: "0%", class: up ? "g-up" : "g-dn"}), s("stop", {offset: "100%", class: "g-0"}))),
      s("line", {class: "zero", x1: 0, x2: W - 48, y1: Y(0).toFixed(1), y2: Y(0).toFixed(1)}),
      s("path", {class: "area", d: `${d}L${X(tb).toFixed(1)},${Y(lo).toFixed(1)}L${X(ta).toFixed(1)},${Y(lo).toFixed(1)}Z`, fill: `url(#${id})`}),
      s("path", {class: ["ln", up ? "up" : "dn"], d}),
      s("circle", {class: ["glow", up ? "up" : "dn"], cx: X(end[0]).toFixed(1), cy: Y(end[1]).toFixed(1), r: 6}),
      s("circle", {class: ["end", up ? "up" : "dn"], cx: X(end[0]).toFixed(1), cy: Y(end[1]).toFixed(1), r: 2.6}),
      s("text", {class: "ax", x: W - 44, y: Y(hi - pad) + 8}, pctS(hi - pad)),
      // the bottom label only when it reads differently from the top one (a flat line would print '0.00%' twice)
      pctS(lo + pad) !== pctS(hi - pad) ? s("text", {class: "ax", x: W - 44, y: Y(lo + pad)}, pctS(lo + pad)) : null,
    ].filter(Boolean);
    // daily bars: that day's change of the group's median (the calendar answer), on the same time axis
    const gk = (LANES.find((l) => l.id === st.g) || {}).key;
    const days = cal && cal.ready ? (cal.days || []).filter((x) => (x.state === "done" || x.state === "today") && x.g && x.g[gk] && x.g[gk].chg != null) : [];
    if (days.length) {
      const mx = Math.max(0.001, ...days.map((x) => Math.abs(x.g[gk].chg)));
      const bw = Math.max(2, Math.min(14, (W - 52) / Math.max(days.length, 8) - 2)), base = H - barsH / 2;
      kids.push(s("line", {class: "zero", x1: 0, x2: W - 48, y1: base, y2: base}));
      for (const x of days) {
        const v = x.g[gk].chg, hgt = Math.max(1, (Math.abs(v) / mx) * (barsH / 2 - 2));
        const cx = Math.min(W - 52, Math.max(4, X(Math.min(tb, Math.max(ta, x.ts + 43200000)))));
        kids.push(s("rect", {class: ["bar", v > 0 ? "up" : v < 0 ? "dn" : ""], x: (cx - bw / 2).toFixed(1), y: (v > 0 ? base - hgt : base).toFixed(1), width: bw.toFixed(1), height: hgt.toFixed(1)},
          s("title", null, `${fmt.date(x.ts)} ${pctS(v)}`)));
      }
    }
    return s("svg", {class: "term-psvg", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img",
      "aria-label": `${SHORT[st.g]} 중앙값 수익률 ${pctS(end[1])}`}, kids);
  }

  function calendar(cal) {
    if (!cal || !cal.ready) return [h("div", {class: "term-pnone sm"}, h("b", null, "달력 수집 전"))];
    const gk = (LANES.find((l) => l.id === st.g) || {}).key, days = cal.days || [];
    const xs = days.filter((d) => d.g && d.g[gk] && d.g[gk].chg != null).map((d) => Math.abs(d.g[gk].chg)).sort((a, b) => a - b);
    const sc = xs.length ? Math.max(0.002, xs[Math.min(xs.length - 1, Math.floor(xs.length * 0.9))]) : 0.005;
    const cells = WD.map((w, i) => h("span", {class: ["term-cw", i >= 5 ? "we" : ""]}, w));
    for (let i = 0; i < (days.length ? days[0].dow : 0); i++) cells.push(h("span", {class: "term-cc pad", "aria-hidden": "true"}));
    for (const d of days) {
      const x = d.g && d.g[gk], v = x ? x.chg : null, shown = pctS(v), zero = v == null || !/[1-9]/.test(shown);
      const has = d.state === "done" || d.state === "today";
      const a = !has || zero ? 0 : 0.18 + 0.62 * Math.min(1, Math.abs(v) / sc);
      const lab = `${fmt.date(d.ts)} · ${d.state === "future" ? "아직 오지 않은 날" : d.state === "empty" ? "기록 없음" : `${SHORT[st.g]} 중앙값 ${shown}`}`;
      cells.push(h("span", {class: ["term-cc", "s-" + d.state, has ? (zero ? "flat" : v > 0 ? "up" : "down") : ""], style: {"--a": a.toFixed(3)}, title: lab, "aria-label": lab},
        h("span", {class: "dn num"}, String(Number(d.d.slice(8, 10)))), has && !zero ? h("span", {class: "dv num"}, fmt.num(v * 100, Math.abs(v) >= 0.001 ? 1 : 2, true)) : null));
    }
    return cells;
  }

  function draw(user) {
    const model = st.race, lane = model && model.lanes.find((l) => l.id === st.g);
    sw.className = `fk-sw term-psw ${st.g === "coin" ? "band" : st.g}`;
    pk.textContent = `${SHORT[st.g]} 중앙값`;
    const v = lane ? [...lane.v].reverse().find((x) => x != null) : null;
    if (user) delete big.dataset.v;          // a group switch repaints without a roll
    motion.countTo(big, v ?? null, {format: "pct", dec: 2, tone: true, glow: !user});
    const gk = (LANES.find((l) => l.id === st.g) || {}).key;
    const td = st.cal && st.cal.ready ? (st.cal.days || []).find((d) => d.state === "today") : null;
    const tv = td && td.g && td.g[gk] ? td.g[gk].chg : null;
    today.textContent = tv == null ? "" : `오늘 ${pctS(tv)}`;
    today.className = "num term-ptoday " + fmt.tone(tv, pctS(tv));
    put(chartBox, line(model, st.cal));
    put(calBox, calendar(st.cal));
    if (user) motion.swap(chartBox);
  }

  let sig = "";
  async function load() {
    let r = null, c = null;
    try { [r, c] = await Promise.all([ctx.api(RACE_API + "?step=auto").catch(() => null), ctx.api(CAL_API).catch(() => null)]); } catch (e) { /* drawn as 수집 전 */ }
    if (!ctx.alive()) return;
    const k = JSON.stringify([r && r.now, r && r.t && r.t.length, c && c.now]);
    if (k === sig && st.race) return;
    sig = k;
    st.race = prep(r); st.cal = c;
    draw(false);
  }
  ctx.every(300000, load, {now: true});
  if (typeof ResizeObserver === "function") {
    let w = 0;
    const ro = new ResizeObserver(() => { const nw = chartBox.clientWidth; if (Math.abs(nw - w) > 4 && st.race) { w = nw; put(chartBox, line(st.race, st.cal)); } });
    ro.observe(chartBox); ctx.track(() => ro.disconnect());
  }
  return {el, onBoard() {}};
}
