// 터미널 right column (term v2, owners 10/06: HelloQuant's right column without the order form):
//   - 이 코인 포지션: this coin's open positions of OUR named accounts (기존 36, 5분봉, 추가: live ROE at the mark price,
//     the liquidation price; the numbers roll to a real new mark). DeepSeek and the coin flips are counted only (their
//     money is on their own group screens). Paper: 주문 버튼 없음.
//   - 수익 (기존 36): the 36's realized P&L, the sum of the day's closed trades of those accounts (/api/v4/flow/calendar,
//     g.core.pnl: the same answer as 흐름 · 수익 달력), drawn as the cumulative line from the run start with the daily
//     bars under it; 오늘 수익 (today's realized sum and trades); the 수익 캘린더 with each day's realized P&L in its
//     cell, green / red by sign. Read every 5 minutes like 흐름.
// HONESTY: realized money of closed trades only (the open positions' P&L is in the table below), the 36 only, 참고 (a
// running record, not a verdict); a day without a record is 기록 없음, never a zero; nothing is drawn before the first
// real day.
import {h, s, put, ui, fmt, store, motion} from "../core/pb.js";
import {normPos} from "./positions-kit.js";
import {CAL_API} from "./flow-cal.js";
import {panel} from "./terminal-kit.js";
import {MONEY_G} from "./terminal-table.js";       // the groups whose money is shown per account (DeepSeek / coin flips: counts only)

// ---------------------------------------------------------------- this coin's positions
/** coinPositions(ctx, st) -> {el, setSym, onBoard, onTicker} */
export function coinPositions(ctx, st) {
  const list = h("div", {class: "term-cp", role: "list"});
  const other = h("p", {class: "term-cpo muted", hidden: true});
  const el = panel("이 코인 포지션", {cls: "term-mine", scroll: true}, list, other);
  el.append(h("div", {class: "term-pf"}, ui.assume("open")));
  let board = null;
  const rows = new Map();          // account id -> {key, node, roe}
  function render() {
    const mk = store.mark(st.sym);
    const all = board ? board.accounts.filter((a) => a.position && a.position.symbol === st.sym) : [];
    const xs = all.filter((a) => MONEY_G.has(fmt.groupOf(a))).map((a) => ({a, p: normPos(a.position)}));
    xs.sort((x, y) => (y.p.entry_time || 0) - (x.p.entry_time || 0));
    const L = xs.filter((x) => x.p.side > 0).length;
    el.sub.textContent = board ? `${fmt.coin(st.sym)} · ${fmt.int(xs.length)}개 · 롱 ${fmt.int(L)} · 숏 ${fmt.int(xs.length - L)}` : "";
    const nDs = all.filter((a) => fmt.groupOf(a) === "ds").length, nCoin = all.filter((a) => fmt.groupOf(a) === "coin").length;
    other.hidden = !(nDs || nCoin);
    other.textContent = `딥시크 ${fmt.int(nDs)}개 · 동전 봇 ${fmt.int(nCoin)}개도 이 코인에 열려 있음 (건수만)`;
    const nodes = xs.slice(0, 20).map((x) => {
      const id = x.a.account_id, key = `${st.sym}|${x.p.entry_time}|${x.p.liq}`;
      let r = rows.get(id);
      if (!r || r.key !== key) {
        const roe = h("b", {class: "num term-roe"}, "—");
        const node = h("a", {class: "term-cr", role: "listitem", href: ctx.href("account", id), title: `${id} · 진입 ${fmt.price(x.p.entry)} · ${fmt.lev(x.p.leverage)}`},
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
    if (!nodes.length) put(list, ui.empty(board ? `${fmt.coin(st.sym)}에 열린 포지션이 없습니다` : "불러오는 중"));
    else list.replaceChildren(h("div", {class: "term-cr hd", "aria-hidden": "true"}, h("span", null, "방향"), h("span", null, "계좌"), h("span", null, "배수"),
      h("span", null, "ROE"), h("span", null, "청산가")), ...nodes);
  }
  return {el, setSym() { rows.clear(); render(); }, onBoard(b) { board = b; render(); }, onTicker: render};
}

// ---------------------------------------------------------------- 수익 (기존 36): chart, today, calendar
const WD = ["월", "화", "수", "목", "금", "토", "일"];
const K = "core";                                     // the calendar answer's key of 기존 36
let UID = 0;
/** 1,234.5 -> "1.2K", 356 -> "356", -7,512 -> "−7.5K" (calendar cells, axis labels). */
const short = (v) => {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  const a = Math.abs(v);
  return a >= 1e6 ? `${fmt.num(v / 1e6, 1)}M` : a >= 1e4 ? `${fmt.num(v / 1e3, 0)}K` : a >= 1e3 ? `${fmt.num(v / 1e3, 1)}K` : fmt.num(v, 0);
};

/** pnlPanel(ctx) -> {el, onBoard} */
export function pnlPanel(ctx) {
  const st = {cal: null};
  const big = h("b", {class: "num term-pbig"}, "—"), unit = h("span", {class: "term-punit"}, "USDT");
  const meta = h("span", {class: "term-pmeta"}, "");
  const chartBox = h("div", {class: "term-pchart"});
  const todayV = h("b", {class: "num term-tdv"}, "—"), todayK = h("span", {class: "term-tdk"}, "");
  const calMonth = h("span", {class: "term-calm num"}, "");
  const calBox = h("div", {class: "term-cal"});
  const legend = h("div", {class: "term-plg"}, h("span", null, h("i", {class: "k-line", "aria-hidden": "true"}), "누적 수익"),
    h("span", null, h("i", {class: "k-bar", "aria-hidden": "true"}), "일별 수익"));
  const el = panel("수익 차트", {cls: "term-pnl", sub: "기존 36 · 실현 손익", acts: [ui.pill("", "ref")]},
    h("div", {class: "term-phero"}, legend, h("span", {class: "grow"}), big, unit),
    meta, chartBox,
    h("div", {class: "term-today"}, h("span", {class: "term-tdt"}, "오늘 수익"), todayK, h("span", {class: "grow"}), todayV, h("span", {class: "term-punit"}, "USDT")),
    h("div", {class: "term-calh"}, h("span", {class: "term-calt"}, "수익 캘린더"), calMonth, h("span", {class: "grow"}),
      h("a", {class: "term-more", href: ctx.href("flow")}, "흐름 →")),
    calBox);
  el.append(h("div", {class: "term-pf"}, ui.assume(),
    ui.note("기존 36 계좌가 닫은 거래의 실현 손익 합 (열린 포지션 빼고, 아래 표에 따로) · 칸 = 한국 시간 하루 · 중간 기록일 뿐 판정이 아닙니다")));

  const daysOf = (cal) => (cal && cal.ready ? cal.days || [] : []);
  const hasDay = (d) => (d.state === "done" || d.state === "today") && d.g && d.g[K];

  function chart(cal) {
    const W = Math.max(200, chartBox.clientWidth || 280), H = Math.max(96, chartBox.clientHeight || 130);
    const days = daysOf(cal).filter(hasDay);
    if (!days.length) return h("div", {class: "term-pnone"}, h("b", null, "곡선 수집 전"), h("span", null, "첫 하루의 기록이 쌓이면 그려집니다"));
    // cumulative realized P&L: 0 at the run start, then the end of every recorded day (today: now)
    let cum = 0;
    const pts = [[Number(cal.start) || days[0].ts, 0]];
    for (const d of days) { cum += Number(d.g[K].pnl) || 0; pts.push([d.state === "today" ? Number(cal.now) || d.ts + 86400000 : d.ts + 86400000, cum]); }
    const ta = pts[0][0], tb = pts[pts.length - 1][0];
    const bh = Math.round(H * 0.3), lh = H - bh - 18;                       // line area, bars area, date labels
    let lo = Math.min(0, ...pts.map((p) => p[1])), hi = Math.max(0, ...pts.map((p) => p[1]));
    const pad = (hi - lo) * 0.1 || 1; lo -= pad; hi += pad;
    const X = (t) => 4 + ((t - ta) / Math.max(1, tb - ta)) * (W - 50), Y = (v) => 4 + (1 - (v - lo) / (hi - lo)) * (lh - 8);
    const d = pts.map(([t, v], i) => `${i ? "L" : "M"}${X(t).toFixed(1)},${Y(v).toFixed(1)}`).join("");
    const end = pts[pts.length - 1], up = end[1] >= 0, id = "tg" + ++UID;
    const kids = [
      s("defs", null, s("linearGradient", {id, x1: 0, y1: 0, x2: 0, y2: 1}, s("stop", {offset: "0%", class: up ? "g-up" : "g-dn"}), s("stop", {offset: "100%", class: "g-0"}))),
      s("line", {class: "zero", x1: 0, x2: W - 46, y1: Y(0).toFixed(1), y2: Y(0).toFixed(1)}),
      s("path", {class: "area", d: `${d}L${X(tb).toFixed(1)},${Y(0).toFixed(1)}L${X(ta).toFixed(1)},${Y(0).toFixed(1)}Z`, fill: `url(#${id})`}),
      s("path", {class: ["ln", up ? "up" : "dn"], d}),
      s("circle", {class: ["glow", up ? "up" : "dn"], cx: X(end[0]).toFixed(1), cy: Y(end[1]).toFixed(1), r: 6}),
      s("circle", {class: ["end", up ? "up" : "dn"], cx: X(end[0]).toFixed(1), cy: Y(end[1]).toFixed(1), r: 2.6}),
      s("text", {class: "ax", x: W - 42, y: Y(hi - pad) + 9}, short(hi - pad)),
      short(lo + pad) !== short(hi - pad) ? s("text", {class: "ax", x: W - 42, y: Y(lo + pad)}, short(lo + pad)) : null,
      s("text", {class: "ax", x: W - 42, y: Y(0) + 4}, "0"),
    ].filter(Boolean);
    // daily bars: that day's realized P&L, centred on the day
    const mx = Math.max(1, ...days.map((x) => Math.abs(Number(x.g[K].pnl) || 0)));
    const bw = Math.max(3, Math.min(16, (W - 50) / Math.max(days.length, 6) - 3)), base = lh + bh / 2;
    kids.push(s("line", {class: "zero", x1: 0, x2: W - 46, y1: base, y2: base}));
    for (const x of days) {
      const v = Number(x.g[K].pnl) || 0, hgt = Math.max(1, (Math.abs(v) / mx) * (bh / 2 - 2));
      const cx = Math.min(W - 50, Math.max(4 + bw / 2, X(Math.min(tb, x.ts + 43200000))));
      kids.push(s("rect", {class: ["bar", v > 0 ? "up" : v < 0 ? "dn" : ""], x: (cx - bw / 2).toFixed(1), y: (v > 0 ? base - hgt : base).toFixed(1), width: bw.toFixed(1), height: hgt.toFixed(1)},
        s("title", null, `${fmt.date(x.ts)} 실현 ${fmt.money(v, true)} USDT · 거래 ${fmt.int(x.g[K].trades)}`)));
    }
    kids.push(s("text", {class: "ax", x: 4, y: H - 3}, fmt.mmdd(ta)), s("text", {class: "ax end", x: W - 50, y: H - 3}, fmt.mmdd(tb)));
    return s("svg", {class: "term-psvg", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img",
      "aria-label": `기존 36 실현 손익 누적 ${fmt.money(end[1], true)} USDT`}, kids);
  }

  function calendar(cal) {
    const days = daysOf(cal);
    if (!days.length) return [h("div", {class: "term-pnone sm"}, h("b", null, "달력 수집 전"))];
    const vs = days.filter(hasDay).map((d) => Math.abs(Number(d.g[K].pnl) || 0)).sort((a, b) => a - b);
    const sc = vs.length ? Math.max(1, vs[Math.min(vs.length - 1, Math.floor(vs.length * 0.9))]) : 1;
    const cells = WD.map((w, i) => h("span", {class: ["term-cw", i >= 5 ? "we" : ""]}, w));
    for (let i = 0; i < days[0].dow; i++) cells.push(h("span", {class: "term-cc pad", "aria-hidden": "true"}));
    for (const d of days) {
      const has = hasDay(d), v = has ? Number(d.g[K].pnl) || 0 : null, zero = !has || Math.abs(v) < 0.5;
      const a = zero ? 0 : 0.2 + 0.55 * Math.min(1, Math.abs(v) / sc);
      const lab = `${fmt.date(d.ts)} · ${d.state === "future" ? "아직 오지 않은 날" : !has ? "기록 없음"
        : `기존 36 실현 ${fmt.money(v, true)} USDT · 거래 ${fmt.int(d.g[K].trades)} · 이김 ${fmt.int(d.g[K].wins)}`}`;
      cells.push(h("span", {class: ["term-cc", "s-" + d.state, has ? (zero ? "flat" : v > 0 ? "up" : "down") : ""], style: {"--a": a.toFixed(3)}, title: lab, "aria-label": lab},
        h("span", {class: "dn num"}, String(Number(d.d.slice(8, 10)))), has ? h("span", {class: "dv num"}, zero ? "0" : short(v)) : null));
    }
    return cells;
  }

  function draw() {
    const cal = st.cal, days = daysOf(cal).filter(hasDay);
    const tot = days.length ? days.reduce((acc, d) => acc + (Number(d.g[K].pnl) || 0), 0) : null;
    const n = days.reduce((acc, d) => acc + (Number(d.g[K].trades) || 0), 0), w = days.reduce((acc, d) => acc + (Number(d.g[K].wins) || 0), 0);
    motion.countTo(big, tot, {dec: 2, sign: true, tone: true, glow: true});
    meta.textContent = days.length ? `${fmt.int(days.length)}일 · 거래 ${fmt.int(n)} · 이긴 거래 ${fmt.int(w)}${cal.seasons > 1 ? " · 이번 판정 구간" : ""}` : "";
    const td = days.find((d) => d.state === "today");
    const tv = td ? Number(td.g[K].pnl) || 0 : null;
    motion.countTo(todayV, tv, {dec: 2, sign: true, tone: true});
    todayK.textContent = td ? `거래 ${fmt.int(td.g[K].trades)} · 이김 ${fmt.int(td.g[K].wins)}` : cal && cal.ready ? "오늘 기록 없음" : "수집 전";
    const all = daysOf(cal);
    calMonth.textContent = all.length ? `${all[0].d.slice(0, 7).replace("-", ".")}${all[all.length - 1].d.slice(0, 7) !== all[0].d.slice(0, 7) ? ` – ${Number(all[all.length - 1].d.slice(5, 7))}월` : ""}` : "";
    put(chartBox, chart(cal));
    put(calBox, calendar(cal));
  }

  let sig = "";
  async function load() {
    let c = null;
    try { c = await ctx.api(CAL_API); } catch (e) { /* drawn as 수집 전 */ }
    if (!ctx.alive()) return;
    const k = JSON.stringify([c && c.now, c && c.days && c.days.length]);
    if (k === sig && st.cal) return;
    sig = k;
    st.cal = c;
    draw();
  }
  ctx.every(300000, load, {now: true});
  if (typeof ResizeObserver === "function") {
    let w = 0, hh = 0;
    const ro = new ResizeObserver(() => {
      const nw = chartBox.clientWidth, nh = chartBox.clientHeight;
      if ((Math.abs(nw - w) > 4 || Math.abs(nh - hh) > 4) && st.cal) { w = nw; hh = nh; put(chartBox, chart(st.cal)); }
    });
    ro.observe(chartBox); ctx.track(() => ro.disconnect());
  }
  return {el, onBoard() {}};
}
