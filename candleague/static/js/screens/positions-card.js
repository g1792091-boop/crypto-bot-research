// 포지션 › the position card (copied and adapted from the rule bot's paperbot/dash/static/v4/screens/positions-kit.js:
// posCard, whyBox, stopLine, ruleLine; nothing imported from it). One open position of /api/positions as a calm card: a
// one-line row (side, coin, leverage, the account, a small price line, the live unrealized P&L and ROI) that opens into
// the full card (the LED P&L, "진입 뒤 가격", "왜 N배", entry / mark / liquidation / stop, a meter from now to the stop
// and the liquidation, what the stop pays, the exit rule in plain words, links). Every string reaches the page as a
// text node (dom.js h() / s()).
// Numbers: P&L = side x qty x (mark - entry), ROI = P&L / margin, at the coin's mark price (poskit.livePnl); size,
// margin and liquidation price are the server's rebuild "진입 때 기준" (dash.py rebuild_open). A hidden DeepSeek position
// (p.hidden: the server sent no money, D11) becomes a count-only card: side, coin, time, name and rule only.
import {h, s} from "../dom.js";
import * as fmt from "../fmt.js";
import * as K4 from "../v4kit.js";
import * as LK from "../lk.js";
import {livePnl, gap, extremes} from "../poskit.js";
import {serverNow} from "../live.js";
import {tfKo, sideKo, coinShort, ROLE_SHORT, KIND_KO} from "../labels.js";

// ---------------------------------------------------------------- rule numbers (paperbot config, as the engine uses them)
export const LADDER_FIRST = {ladder: 0.10, ladder5: 0.05, ladder20: 0.20, ladder_tp2R: 0.10, swing3: 0.10, swing10: 0.10};
export const LADDER = {step: 0.05, gap: 0.02};               // config ladder_step / ladder_trigger_gap
export const ROUND_TRIP = 2 * (0.0005 + 0.0002);             // config round_trip_cost: taker fee + slippage, both sides
export const HIDDEN_KO = "개수만";
export const HIDDEN_WHY = "딥시크 금액 숨김 (서버 설정): 방향·코인·시각만 보내고 손익·가격·배수는 보내지 않습니다. 합계에서 뺍니다.";
export const CATCHUP_KO = "따라잡는 중";

const fin = (x) => (x == null || x === "" || typeof x === "boolean" || !Number.isFinite(Number(x)) ? null : Number(x));
/** "1,184.83 USDT" / "+212.20 USDT" (sign); "—" without a number. */
export const usdt = (x, sign = false) => (fmt.bad(x) ? "—" : `${fmt.num(x, 2, sign)} USDT`);
/** A share as a percent with 2 decimals: 0.0312 -> "3.12%". */
export const dist = (r) => (r == null ? "—" : fmt.pct(Number(r) * 100, false, 2));
/** A position size: 0.738 BTC, 372.14 LTC, 307,192 DOGE. */
export const qtyTxt = (x) => (fmt.bad(x) ? "—" : fmt.num(x, Math.abs(x) < 10 ? 3 : Math.abs(x) < 1000 ? 2 : 0));
export const sym = (p) => `${coinShort(p.coin || p.symbol)}USDT`;
export const sideTag = (side) => h("span", {class: ["side", Number(side) > 0 ? "long" : "short"]}, sideKo(side));
/** The price at which the net ROE reaches ``roe`` (the ladder's trigger, without funding): "가격 약". */
export const roePrice = (p, roe) => Number(p.entry) * (1 + Number(p.side) * (roe / Number(p.lev) + ROUND_TRIP));

/** The account's name for a list: the timeframe chip, the strategy's Korean name (the pick's "2순위" when it is not its
 *  cell's first), and outside a 후보 the role chip (1/4 · 청산만 · 기본값 · 동전). */
export function nameNode(p, o = {}) {
  const ix = LK.index();
  const pk = (p.pick && ix.byId[p.pick]) || null;
  // the pick's "2순위" belongs to the pick and its own accounts, not to the 기본값 account its cell shares
  const rank = p.role !== "base" && pk && pk.source && pk.source.rank > 1 ? pk.source.rank : null;
  return h("span", {class: "ps-nm"},
    h("span", {class: "an", title: `${p.name} · ${p.id}`}, h("span", {class: "an-tf"}, tfKo(p.tf)),
      h("span", {class: "an-n"}, LK.stratKo(p.name)), rank ? h("small", {class: "ps-code"}, `${rank}순위`) : null),
    p.role && p.role !== "cand" && !o.noRole ? LK.roleChip(p.role, ROLE_SHORT[p.role]) : null);
}
export const kindKo = (p) => KIND_KO[p && p.kind] || "";

/** The exit rule in plain words from the account's rule code ("tp3R|4", "ladder|2", "roe50|4", ...), with the take-profit
 *  price when the server sent it. */
export function exitPlain(p) {
  const [rule = "", k = ""] = String(p.exit || "").split("|");
  const stopK = k ? `손절 ${k} ATR` : "손절";
  const lead = h("b", null, p.exit_ko || "청산 규칙");
  const hid = p.hidden || fin(p.entry) == null || fin(p.lev) == null;
  const ladder = LADDER_FIRST[rule];
  const parts = [];
  if (/^tp[\d.]+R$/.test(rule)) {
    const m = rule.slice(2, -1);
    parts.push(` · 진입 기준가에서 손절 거리(R)의 ${m}배 가면 익절 리밋`, hid || p.tp == null ? "" : ` (${fmt.price(p.tp)})`, `, 반대로 ${stopK} 자리에 닿으면 손절.`);
  } else if (/^roe\d+$/.test(rule)) {
    parts.push(` · 순 ROE +${rule.slice(3)}%에 닿으면 익절`, hid || p.tp == null ? "" : ` (가격 ${fmt.price(p.tp)})`, `, ${stopK} 자리에 닿으면 손절.`);
  }
  if (ladder != null) {
    if (p.stop_is_lock) parts.push(" · 손절선이 이미 수익 쪽에 올라와 있습니다 (잠금 중: 닿으면 수익으로 끝남).");
    const trig = ladder + LADDER.gap;
    parts.push(` · 계단 잠금: 순 ROE +${fmt.num(trig * 100, 0)}%`, hid ? "" : `(가격 약 ${fmt.price(roePrice(p, trig))})`,
      `가 되면 손절선을 +${fmt.num(ladder * 100, 0)}% 자리로 올리고, 그 뒤 ${fmt.num(LADDER.step * 100, 0)}%씩 따라 올립니다.`);
    if (rule === "ladder_tp2R") parts.push(hid || p.tp == null ? " 익절 리밋 2R도 함께 겁니다." : ` 익절 리밋 2R (${fmt.price(p.tp)})도 함께 겁니다.`);
    else if (rule.startsWith("swing")) parts.push(" 직전 스윙 자리에 익절 리밋도 겁니다.");
    else parts.push(" 고정 익절은 없습니다.");
  }
  return h("p", {class: "ps-plain"}, lead, parts.filter(Boolean));
}

/** "왜 N배": the server's words (dash.py why_lev) from the leverage the engine chose, the account's margin share and the
 *  entry-time liquidation distance; the rule in one short line (a phone has no tooltip; the full sentence is the
 *  tooltip) with a link to the 익절·손절·배수 screen. */
export function whyBox(p) {
  const w = p.why || null;
  const lev = fin(p.lev), mp = fin(p.margin_pct), ld = fin(p.liq_dist_entry);
  const head = [w && w.group_ko ? w.group_ko : "보통 또는 좋은 자리", lev ? fmt.lev(lev) : null,
    mp != null ? `증거금 ${fmt.num(mp * 100, mp < 0.1 ? 1 : 0)}%` : null, ld != null ? `진입 때 청산까지 ${fmt.num(ld * 100, 1)}%` : null];
  return h("div", {class: "ps-why", title: w && w.rule_ko ? w.rule_ko : null},
    h("span", null, K4.plate(lev ? `왜 ${fmt.lev(lev)}` : "왜 이 배수")),
    h("p", null, head.filter(Boolean).join(" · ")),
    w ? h("small", null, [w.lev_ko, w.sub_ko].filter(Boolean).join(" · ")) : null,
    w && w.rule_ko ? h("small", {class: "ps-rule"}, w.rule_short_ko || `좋은 자리 ${LK.levLadder().bestTight} · 보통 ${LK.levLadder().normalTight}`, " · ",
      h("a", {href: p.pick ? `#/rules?pick=${encodeURIComponent(p.pick)}` : "#/rules"}, "배수 규칙 자세히")) : null);
}

/** What touching the stop (or the lock line) pays, before the exit fee, and whether it comes before the liquidation. */
export function stopLine(p) {
  const pnl = fin(p.stop_pnl);
  if (pnl == null) return null;
  const roe = fin(p.stop_roe);
  const lock = !!p.stop_is_lock || pnl >= 0;
  const first = fin(p.liq) == null || fin(p.stop) == null ? null : (Number(p.side) > 0 ? p.stop > p.liq : p.stop < p.liq);
  return h("p", {class: "ps-plain"}, lock ? "잠금선에 닿으면 " : "손절에 닿으면 ",
    h("b", {class: fmt.tone(pnl)}, usdt(pnl, true)), roe == null ? "" : ` (ROI ${fmt.pct(roe * 100, true, 1)})`, lock ? "가 남습니다." : ".",
    first == null ? "" : first ? (lock ? "" : " 청산보다 손절이 먼저 옵니다.") : h("b", {class: "down"}, " 손절선이 청산가보다 멀리 있습니다."),
    fin(p.tp_pnl) != null ? [" 익절에 닿으면 ", h("b", {class: "up"}, usdt(p.tp_pnl, true)), "."] : null);
}

/**
 * priceLine(values, {w, h, base, refs: [{v, cls}], tone, draw, label}) -> the price since the entry as a small svg
 * (the rule bot's ui.miniSpark with reference lines; fluid: fills its box). base: the entry (dashed); refs: the stop
 * (red dashed). Fewer than 2 values: an empty box of the same size.
 */
export function priceLine(values, o = {}) {
  const w = o.w || 300, hh = o.h || 46;
  const box = o.fluid ? {width: "100%", height: hh + "px", display: "block"}
    : {width: w + "px", height: hh + "px", display: "inline-block", verticalAlign: "middle", flex: "none"};
  const vs = (values || []).map((v) => fin(v));
  const real = vs.filter((v) => v != null);
  if (real.length < 2) return s("svg", {class: ["chart", "mspark", "none"], viewBox: `0 0 ${w} ${hh}`, style: box, "aria-hidden": "true"});
  let lo = Math.min(...real), hi = Math.max(...real);
  if (fin(o.base) != null) { lo = Math.min(lo, Number(o.base)); hi = Math.max(hi, Number(o.base)); }
  // clip: a reference line much farther than the price path itself (a 4 ATR stop on a quiet day) is left out of the
  // scale, so the path stays readable; the caller says so (svg.dropped)
  const room = (hi - lo || Math.abs(hi) * 0.002) * 1.5;
  const dropped = [];
  const refs = (o.refs || []).filter((r) => {
    if (!r || fin(r.v) == null) return false;
    if (o.clip && (Number(r.v) < lo - room || Number(r.v) > hi + room)) { dropped.push(r); return false; }
    return true;
  });
  for (const r of refs) { lo = Math.min(lo, Number(r.v)); hi = Math.max(hi, Number(r.v)); }
  const span = hi - lo || Math.abs(hi) * 0.001 || 1;
  const pad = 2.5;
  const X = (i) => pad + (w - 2 * pad) * i / Math.max(1, vs.length - 1);
  const Y = (v) => hh - pad - (hh - 2 * pad) * (v - lo) / span;
  let d = "", pen = false, lastI = 0;
  vs.forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`; pen = true; lastI = i; });
  const end = real[real.length - 1], ref = fin(o.base) != null ? Number(o.base) : real[0];
  const up = o.tone ? o.tone === "up" : end >= ref;
  const line = (v, cls) => s("line", {class: cls, x1: 0, x2: w, y1: Y(Number(v)).toFixed(1), y2: Y(Number(v)).toFixed(1)});
  const svg = s("svg", {class: ["chart", "mspark"], viewBox: `0 0 ${w} ${hh}`, style: box, role: "img",
    "aria-label": o.label || "진입 뒤 가격 흐름", preserveAspectRatio: o.fluid ? "none" : null},
  fin(o.base) != null ? line(o.base, "base") : null,
  refs.map((r) => line(r.v, r.cls || "base")),
  s("path", {class: up ? "lu" : "ld", d}),
  o.fluid ? null : s("circle", {cx: X(lastI).toFixed(1), cy: Y(end).toFixed(1), r: 1.9, style: {fill: up ? "var(--up)" : "var(--down)"}}));
  svg.dropped = dropped;
  if (o.draw) K4.drawIn(svg);
  return svg;
}

// ---------------------------------------------------------------- the card
/**
 * posCard(p, o) -> <article> with .update(mark, allowed) (call it with real mark prices only: the numbers count to them;
 * allowed false = the engine is catching up or its record is old: no live P&L, no distances, waitKo says why) and
 * .setSpark(vals,
 * {note, live}). p: an /api/positions entry. o: {open, onToggle(id, open), href (ctx.href)}.
 */
export function posCard(p, o = {}) {
  if (p.hidden) return hiddenCard(p, o);
  const side = Number(p.side);
  const lev = fin(p.lev);
  const pnlEl = h("b", {class: "led-num num"}, "—"), roiEl = h("b", {class: "led-sm num"}, "—");
  const ledNote = h("small", {class: "ps-lednote"});
  const markEl = h("span", {class: "num"}, "—");
  const dLiqEl = h("b", {class: "down num"}, "—"), dStopEl = h("b", {class: "num"}, "—");
  const lockLine = !!p.stop_is_lock;
  // the meter: the left end is the mark price now (accent), the white tick the stop (or the lock line), the right end
  // the liquidation price; the red part is what lies past the stop
  const meter = h("div", {class: "ps-meter"},
    h("div", {class: "ps-m-k"}, h("span", null, h("i", {class: "ps-m-key now", "aria-hidden": "true"}), "지금 → ",
      h("i", {class: "ps-m-key stop", "aria-hidden": "true"}), lockLine ? "잠금선 " : "손절 ", dStopEl),
    h("span", null, h("i", {class: "ps-m-key liq", "aria-hidden": "true"}), "청산 ", dLiqEl)),
    h("div", {class: "ps-m-track", "aria-hidden": "true"}, h("i", {class: "ps-m-danger"}), h("i", {class: "ps-m-tick now"}),
      h("i", {class: "ps-m-tick stop"}), h("i", {class: "ps-m-tick liq"})));
  const extEl = h("span", {class: "num", title: "진입한 뒤 가장 높았던 / 가장 낮았던 수익률 (증거금 대비, 수수료 전). 1분봉 기록 + 지금 가격"}, "—");
  const pairs = [
    ["진입가", fmt.price(p.entry)], ["마크 가격", markEl], ["청산가", h("span", {class: "down num", title: "진입 때 기준 (펀딩 전)"}, fmt.price(p.liq))],
    [lockLine ? "잠금선 (손절 주문)" : "손절가", fmt.price(p.stop)],
    fin(p.tp) != null ? ["익절가", h("span", {class: "up num"}, fmt.price(p.tp))] : null,
    ["진입 뒤 최고 · 최저", extEl],
    [`크기 (${coinShort(p.coin)})`, qtyTxt(p.qty)], ["증거금 (USDT)", fmt.num(p.margin, 2)],
  ];
  const when = h("span", {class: "muted ps-when"});
  const paintWhen = (allowed, now) => {
    const held = p.since ? fmt.dur(Math.max(0, (now - p.since) / 1000)) : null;
    when.textContent = [p.since ? `${fmt.kst(p.since)} 진입` : "", held ? `${held} 보유${allowed ? "" : " (엔진 기준)"}` : "",
      `${tfKo(p.tf)}봉`, kindKo(p)].filter(Boolean).join(" · ");
  };
  const href = o.href || ((n, a, q) => `#/${n}${a ? "/" + encodeURIComponent(a) : ""}${q ? "?" + new URLSearchParams(q) : ""}`);
  const acts = h("div", {class: "ps-acts"}, when,
    h("a", {class: "btn-line", href: href("terminal", null, {acct: p.id, coin: p.coin}), title: "터미널 차트에서 이 포지션의 진입·손절선 보기"}, "터미널"),
    h("a", {class: "btn-line", href: href("account", p.id)}, "계좌"),
    h("a", {class: "btn-line", href: href("custom", null, {kind: p.kind, s: p.name, tf: p.tf}), title: "이 매매법의 커스텀값"}, "커스텀값"));
  // the price since the entry (5m closes + the mark now): filled by setSpark when the page has the bars
  const sparkNote = h("span", {class: "muted"}, "5분봉 종가 · 점선 진입가 · 붉은 점선 손절");
  const sparkBox = h("div", {class: "ps-spark", hidden: true}, h("div", {class: "ps-spark-k"}, h("span", null, "진입 뒤 가격"), sparkNote),
    h("div", {class: "ps-spark-g"}));
  const body = h("div", {class: "ps-body", hidden: !o.open},
    h("div", {class: "pnl ps-led"}, h("div", null, h("span", {class: "k"}, "미실현 손익 (USDT)"), pnlEl),
      h("div", {class: "r"}, h("span", {class: "k"}, "ROI"), roiEl), ledNote),
    sparkBox, whyBox(p), h("dl",{class: "kv"}, pairs.filter(Boolean).map(([k, v]) => h("div", null, h("dt", null, k), h("dd", null, v ?? "—")))),
    meter, stopLine(p), exitPlain(p), acts);
  const rowPnl = h("b", {class: "num"}, "—"), rowRoi = h("small", {class: "num"}, "—");
  const rowSpark = h("span", {class: "ps-row-spark", "aria-hidden": "true"});
  const btn = h("button", {class: "ps-row", type: "button", "aria-expanded": String(!!o.open), title: p.id},
    sideTag(side),
    h("span", {class: "ps-row-t"}, h("b", null, `${sym(p)} · 격리 ${fmt.lev(lev)}`), h("small", null, nameNode(p))),
    h("span", {class: "ps-row-v"}, rowSpark, h("span", {class: "ps-row-n"}, rowPnl, rowRoi)), h("span", {class: "ps-chev", "aria-hidden": "true"}, "▾"));
  const el = h("article", {class: ["ps-card", "card", o.open ? "open" : ""], "aria-label": `${coinShort(p.coin)} ${sideKo(side)} · ${LK.stratKo(p.name)} ${tfKo(p.tf)}`}, btn, body);
  btn.addEventListener("click", () => {
    const open = btn.getAttribute("aria-expanded") !== "true";
    btn.setAttribute("aria-expanded", String(open));
    el.classList.toggle("open", open);
    body.hidden = !open;
    if (open) K4.fadeIn(body, 220);
    if (o.onToggle) o.onToggle(p.id, open);
  });
  el.pos = p;
  let sparkDrawn = false;
  /** The price path since the entry (real 5m closes, then the mark now when allowed). Green while the position is in
   *  profit at the last point (a short: the price below the entry), red otherwise; it draws itself in once. */
  el.setSpark = (vals, so = {}) => {
    if (!vals || vals.length < 2) return;
    const last = vals[vals.length - 1];
    const tone = side * (last - Number(p.entry)) >= 0 ? "up" : "down";
    const refs = fin(p.stop) != null ? [{v: p.stop, cls: lockLine ? "lockl" : "stopl"}] : [];
    sparkBox.hidden = false;
    const big = priceLine(vals, {w: 300, h: 46, fluid: true, base: p.entry, refs, tone, clip: true, draw: !sparkDrawn});
    const far = big.dropped && big.dropped.length;
    sparkNote.textContent = ["5분봉 종가", so.note, "점선 진입가", far ? (lockLine ? "잠금선은 멀어서 뺌" : "손절선은 멀어서 뺌")
      : lockLine ? "초록 점선 잠금선" : "붉은 점선 손절"].filter(Boolean).join(" · ");
    sparkBox.lastChild.replaceChildren(big);
    rowSpark.replaceChildren(priceLine(vals, {w: 56, h: 20, base: p.entry, tone}));
    sparkDrawn = true;
  };
  el.update = (mark, allowed = true, waitKo = CATCHUP_KO) => {
    const u = allowed ? livePnl(p, mark) : null;
    K4.countTo(pnlEl, u && u.pnl, {format: (v) => fmt.num(v, 2, true), tone: true, flash: true});
    K4.countTo(roiEl, u && u.roe, {format: (v) => fmt.pct(v * 100, true, 2), tone: true});
    K4.countTo(rowPnl, u && u.pnl, {format: (v) => fmt.num(v, 2, true), tone: true});
    K4.countTo(rowRoi, u && u.roe, {format: (v) => fmt.pct(v * 100, true, 2), tone: true});
    ledNote.textContent = allowed ? (u ? "" : "시세 없음") : waitKo;
    const ex = extremes(p, allowed ? mark : null);
    extEl.replaceChildren(...(ex && ex.best != null && ex.worst != null
      ? [h("span", {class: "up"}, fmt.pct(ex.best * 100, true, 1)), " · ", h("span", {class: "down"}, fmt.pct(ex.worst * 100, true, 1))] : ["—"]));
    el.classList.toggle("ps-wait", !allowed);
    if (allowed) { markEl.title = ""; K4.tickPrice(markEl, mark ?? null, mark != null ? fmt.price(mark) : "—", p.coin); }
    else { markEl.textContent = /따라잡/.test(waitKo) ? "따라잡은 뒤" : "감춤"; markEl.title = waitKo; delete markEl.dataset.pv; }
    const dLiq = allowed ? gap(side, mark, p.liq) : null, dStop = allowed ? gap(side, mark, p.stop) : null;
    dLiqEl.textContent = dist(dLiq);
    dStopEl.textContent = dStop != null && dStop <= 0 ? "닿음" : dist(dStop);
    dLiqEl.classList.toggle("ps-near", dLiq != null && dLiq < 0.02);
    const r = dLiq && dStop != null ? Math.max(0, Math.min(1, dStop / dLiq)) : null;
    meter.style.setProperty("--stop", r == null ? "50%" : (r * 100).toFixed(1) + "%");
    meter.classList.toggle("none", r == null);
    paintWhen(allowed, serverNow());
    return u;
  };
  return el;
}

/** A hidden DeepSeek position (D11): what may be shown (side, coin, entry time, the account's name and rule, counts). */
function hiddenCard(p, o) {
  const side = Number(p.side);
  const now = serverNow();
  const href = o.href || ((n, a) => `#/${n}${a ? "/" + encodeURIComponent(a) : ""}`);
  const body = h("div", {class: "ps-body", hidden: !o.open},
    h("p", {class: "ps-plain ps-co"}, h("b", null, HIDDEN_KO), " · ", HIDDEN_WHY),
    h("dl", {class: "kv"},
      h("div", null, h("dt", null, "방향 · 코인"), h("dd", null, `${sideKo(side)} · ${sym(p)}`)),
      h("div", null, h("dt", null, "진입 시각"), h("dd", null, fmt.kst(p.since))),
      h("div", null, h("dt", null, "보유"), h("dd", null, p.since ? fmt.dur(Math.max(0, (now - p.since) / 1000)) : "—")),
      h("div", null, h("dt", null, "닫힌 거래"), h("dd", null, p.trades != null ? `${fmt.int(p.trades)}번 · ${fmt.int(p.wins || 0)}승` : "—"))),
    h("p", {class: "ps-plain"}, h("b", null, p.exit_ko || "청산 규칙")),
    h("div", {class: "ps-acts"}, h("span", {class: "muted ps-when"}, `${tfKo(p.tf)}봉 · ${kindKo(p)}`),
      h("a", {class: "btn-line", href: href("account", p.id)}, "계좌")));
  const btn = h("button", {class: "ps-row", type: "button", "aria-expanded": String(!!o.open), title: p.id},
    sideTag(side), h("span", {class: "ps-row-t"}, h("b", null, `${sym(p)} · 배수 숨김`), h("small", null, nameNode(p))),
    h("span", {class: "ps-row-v"}, h("span", {class: "ps-row-n"}, h("b", {class: "muted", title: HIDDEN_WHY}, HIDDEN_KO), h("small", null, kindKo(p)))),
    h("span", {class: "ps-chev", "aria-hidden": "true"}, "▾"));
  const el = h("article", {class: ["ps-card", "card", "ps-hidden", o.open ? "open" : ""], "aria-label": `${coinShort(p.coin)} ${sideKo(side)} · ${HIDDEN_KO}`}, btn, body);
  btn.addEventListener("click", () => {
    const open = btn.getAttribute("aria-expanded") !== "true";
    btn.setAttribute("aria-expanded", String(open));
    el.classList.toggle("open", open);
    body.hidden = !open;
    if (o.onToggle) o.onToggle(p.id, open);
  });
  el.pos = p;
  el.setSpark = () => {};
  el.update = () => null;
  return el;
}
