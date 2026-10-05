// 거래 screens (builder B): pieces shared by positions, chart and account. Position facts in plain words (why this
// leverage, with the entry-time liquidation distance; the ladder lock, or the reel's own exits), the position card
// with its LED P&L and the stop / liquidation meter, closed-trade rows and the per-account names.
// Everything is built with h() (text nodes only); money goes through fmt; unrealized money carries ui.assume("open").
import {h, ui, fmt, derive, motion, serverNow} from "../core/pb.js";

// ---------------------------------------------------------------- rule numbers (copied from the server's config)
export const LADDER = {first: 0.10, step: 0.05, gap: 0.02};   // config.py ladder_first_lock / ladder_step / ladder_trigger_gap
export const ROUND_TRIP = 2 * (0.0005 + 0.0002);              // config.py round_trip_cost: taker fee + slippage, both sides
export const REEL_BARS = 96;                                  // reel_engine.MAX_HOLD_5M (5m bars at risk, entry bar = 1)
const M5 = 300000;

/** The reel and the three 5m coin flips use the reel's own exits (config.v4_exits): no ladder, no profit lock. */
/** The reel and the 5m coin flips (own exits, no ladder): the board row's `exits` when the server sends it. */
export const reelExits = (a) => fmt.ownExits(a);

const fin = (x) => (x == null || x === "" || typeof x === "boolean" || !Number.isFinite(Number(x)) ? null : Number(x));

/** One shape for a position from /api/board (entry, stop, liq, tp, time_exit: app.board_position) or from
 *  /api/account state (entry_price, stop_price, liq_price, tp_price, signal.meta.reel_exit.end). */
export function normPos(p) {
  if (!p || typeof p !== "object") return null;
  const meta = (p.signal && p.signal.meta) || {};
  const rx = meta.reel_exit || {};
  return {symbol: p.symbol, side: Number(p.side) > 0 ? 1 : -1, qty: fin(p.qty), entry: fin(p.entry ?? p.entry_price),
    entry_time: fin(p.entry_time), leverage: fin(p.leverage), margin: fin(p.margin), stop: fin(p.stop ?? p.stop_price),
    stop_initial: fin(p.stop_initial), lock_roe: fin(p.lock_roe), liq: fin(p.liq ?? p.liq_price),
    target: fin(p.tp ?? p.tp_price) || null, timeExit: fin(p.time_exit ?? rx.end), tier: p.tier || null};
}

/** The reel's time exit: the stored one, else entry 5m bar open + 96 x 5m (reel_engine, clock-based). */
export function reelTimeExit(pos) {
  if (pos.timeExit) return pos.timeExit;
  return pos.entry_time ? Math.floor(pos.entry_time / M5) * M5 + REEL_BARS * M5 : null;
}

/** The price at which the net ROE reaches `roe` (ladder.roe_price, without funding). */
export const roePrice = (pos, roe) => pos.entry * (1 + pos.side * (roe / pos.leverage + ROUND_TRIP));

/** Account name: the server's own name (row name_ko, the one Telegram uses) wins, then accounts.data name_ko, then
 *  fmt.acctName's tables, so 계좌, 순위표 and 포지션 all show the same name. */
export function nameOf(a, data) {
  if (!a) return "—";
  const d = data || {};
  if (!a.label_ko && !a.name_ko && d.name_ko) return `${d.name_ko} · ${fmt.tfKo(a.timeframe)}`;
  return fmt.acctName(a);
}
/** nameOf as a list label: the timeframe box first, then the name (ui.acctLabel: a phone cuts the name, never the
 *  timeframe). */
export function nameNode(a, data) {
  const d = data || {};
  if (a && !a.label_ko && !a.name_ko && d.name_ko) return ui.acctLabel({...a, kind: "copy", name_ko: d.name_ko});
  return ui.acctLabel(a);
}
export const groupKo = (a) => fmt.GROUP_KO[fmt.groupOf(a)] || "기타";
/** D10/D11 (CONTRACT §1): a DeepSeek or coin-flip account is COUNTED ONLY outside its own group's view: no P&L, no ROE,
 *  no margin or size in a mixed list. view: the group the screen is filtered to ("" / "all" = mixed). */
export const countOnly = (a, view) => derive.countOnlyIn(a, view);
export const COUNT_ONLY_KO = "개수만";
export const COUNT_ONLY_WHY = "딥시크·동전 봇은 섞인 목록에서 손익을 보이지 않습니다 (그 묶음만 고르면 보임)";
export const qty = (x) => (x == null ? "—" : fmt.num(x, Math.abs(x) < 10 ? 3 : Math.abs(x) < 1000 ? 2 : 0));
export const dist = (r) => (r == null ? "—" : fmt.pct(r, 2, false));

/** DeepSeek and the 5m accounts (the reel and its coin flips) always trade at the 보통 multiple (config.py, rules
 *  change 1): the server's "위 단계가 안 된 이유 기록 못 찾음" would read like an error there, so it is replaced. */
export const FIXED_NORMAL_KO = "딥시크·5분봉은 규칙상 늘 보통 배수";
const fixedNormal = (a) => !!a && (a.kind === "ds200" || reelExits(a));
/** "보통 자리 · 30배 · 증거금 30% · 진입 때 청산까지 2.9%" + a short reason line. why: /api/levwhy entry (stale ones,
 *  from an earlier position of the same account, are left out by entry time). */
export function whyBox(a, pos, why, wallet) {
  const w = why && (why.entry_time == null || pos.entry_time == null || why.entry_time === pos.entry_time) ? why : null;
  const gk = w && w.group_ko ? w.group_ko : pos.tier === "best" ? "좋은 자리" : pos.tier === "normal" ? "보통" : null;
  const parts = [];
  if (gk) parts.push(gk.endsWith("자리") ? gk : `${gk} 자리`);
  parts.push(fmt.lev(pos.leverage));
  if (wallet && pos.margin) parts.push(`증거금 ${fmt.pct(pos.margin / wallet, 0, false)}`);
  const ld = derive.liqDistance(pos);
  if (ld != null) parts.push(`진입 때 청산까지 ${fmt.pct(ld, 1, false)}`);
  const sub = [];
  if (fixedNormal(a)) sub.push(FIXED_NORMAL_KO);
  else if (w && w.short_ko) sub.push(w.short_ko);
  if (w && w.score != null) sub.push(`품질 점수 ${fmt.num(w.score, 2)}`);
  if (w && w.source === "coin_flip" && !fixedNormal(a)) sub.push(`동전 봇: 좋은 자리 확률 ${fmt.pct(w.p_best || 0, 0, false)}`);
  return h("div", {class: "pos-why"}, h("span", null, ui.plate(`왜 ${fmt.lev(pos.leverage)}`)),
    h("p", null, parts.join(" · ")), sub.length ? h("small", null, sub.join(" · ")) : null);
}

/** The exit rule in plain words. House: the ladder lock (no fixed take-profit). Reel: its own three exits. */
export function ruleLine(a, pos) {
  if (reelExits(a)) {
    const te = reelTimeExit(pos);
    return h("p", {class: "pos-plain"}, h("b", null, "자기 청산 규칙"), " · 사다리 잠금 없음. 손절은 스윙 저점 아래 고정, 목표는 직전 5분봉의 볼린저 윗밴드 (5분마다 옮겨짐), ",
      te ? `${fmt.kst(te)}에 시간 청산 (진입 후 ${REEL_BARS}봉).` : `진입 후 ${REEL_BARS}봉이 지나면 시간 청산.`);
  }
  if (pos.lock_roe != null) {
    const nx = pos.lock_roe + LADDER.step;
    return h("p", {class: "pos-plain"}, h("b", {class: "up"}, `순 ROE +${fmt.num(pos.lock_roe * 100, 0)}% 잠금 중`),
      pos.side * (pos.stop - pos.entry) > 0 ? " · 손절선이 수익 쪽에 있습니다." : "", " 다음: 순 ROE +", fmt.num((nx + LADDER.gap) * 100, 0), "%가 되면 (가격 약 ",
      fmt.price(roePrice(pos, nx + LADDER.gap)), ") +", fmt.num(nx * 100, 0), "% 잠금. 고정 익절은 없습니다.");
  }
  return h("p", {class: "pos-plain"}, h("b", null, "사다리 잠금"), " · 순 ROE +", fmt.num((LADDER.first + LADDER.gap) * 100, 0),
    "%가 되면 (가격 약 ", fmt.price(roePrice(pos, LADDER.first + LADDER.gap)), ") 손절선을 +", fmt.num(LADDER.first * 100, 0),
    "% 잠금 자리로 올립니다. 고정 익절은 없습니다.");
}

/** What happens at the stop (before the exit fee), and whether it comes before the liquidation. */
function stopLine(a, pos) {
  if (pos.stop == null || pos.entry == null || pos.qty == null) return null;
  const pnl = pos.side * pos.qty * (pos.stop - pos.entry);
  const roe = pos.margin ? pnl / pos.margin : null;
  const first = pos.liq != null && (pos.side > 0 ? pos.stop > pos.liq : pos.stop < pos.liq);
  const lock = pnl >= 0;
  return h("p", {class: "pos-plain"}, lock ? "잠금선에 닿으면 " : "손절에 닿으면 ",
    h("b", {class: fmt.tone(pnl)}, fmt.usdt(pnl, true)), ` (ROI ${fmt.pct(roe, 1)})`, lock ? "가 남습니다." : ".",
    first ? (lock ? "" : " 청산보다 손절이 먼저 옵니다.") : h("b", {class: "down"}, " 손절선이 청산가보다 멀리 있습니다."));
}

// ---------------------------------------------------------------- the position card
/**
 * posCard(a, pos, o) -> element with .update(mark) (call it with real mark prices only: the P&L counts to them).
 * a: board account row (kind, timeframe, strategy, wallet); pos: normPos(); o: {why, wallet, data (account.data),
 * collapsible, open, href (ctx.href), onChart, caption, countOnly}. countOnly (D10/D11): side, leverage, prices and
 * distances only: no P&L, ROI, margin, size or "what the stop pays" line, and a neutral price line.
 */
export function posCard(a, pos, o = {}) {
  const reel = reelExits(a);
  const co = !!o.countOnly;
  const name = nameOf(a, o.data);
  const pnlEl = h("b", {class: "led-num num"}, "—"), roiEl = h("b", {class: "led-sm num"}, "—");
  const markEl = h("span", {class: "num"}, "—");
  const dLiqEl = h("b", {class: "down num"}, "—"), dStopEl = h("b", {class: "num"}, "—"), dTgtEl = h("b", {class: "num"}, "—");
  // the meter: the left end is the mark price now (yellow), the white tick the stop, the right end the liquidation
  const meter = h("div", {class: "pos-meter"},
    h("div", {class: "pos-m-k"}, h("span", null, h("i", {class: "pos-m-key now", "aria-hidden": "true"}), "지금 → ",
      h("i", {class: "pos-m-key stop", "aria-hidden": "true"}), pos.lock_roe != null && !reel ? "잠금선 " : "손절 ", dStopEl),
      h("span", null, h("i", {class: "pos-m-key liq", "aria-hidden": "true"}), "청산 ", dLiqEl)),
    h("div", {class: "pos-m-track", "aria-hidden": "true"}, h("i", {class: "pos-m-danger"}), h("i", {class: "pos-m-tick now"}),
      h("i", {class: "pos-m-tick stop"}), h("i", {class: "pos-m-tick liq"})),
    reel ? h("div", {class: "pos-m-k"}, h("span", null, "목표(윗밴드)까지"), dTgtEl) : null);
  const te = reel ? reelTimeExit(pos) : null;
  const pairs = [
    ["진입가", fmt.price(pos.entry)], ["마크 가격", markEl], ["청산가", h("span", {class: "down num"}, fmt.price(pos.liq))],
    [reel ? "손절가 (스윙 저점)" : pos.lock_roe != null ? "잠금선" : "손절가", fmt.price(pos.stop)],
    reel ? ["목표가 (윗밴드)", pos.target ? fmt.price(pos.target) : ui.notYet("기록 없음", "서버가 이 포지션의 목표가를 보내지 않았습니다")] : null,
    reel ? ["시간 청산", te ? fmt.hm(te) : "—"] : null,
    co ? null : [`크기 (${fmt.coin(pos.symbol)})`, qty(pos.qty)], co ? null : ["증거금 (USDT)", fmt.money(pos.margin)],
    !reel && pos.stop_initial && pos.stop_initial !== pos.stop ? ["첫 손절", fmt.price(pos.stop_initial)] : null,
  ];
  const held = pos.entry_time ? fmt.dur((serverNow() - pos.entry_time) / 1000) : null;
  const acts = h("div", {class: "pos-acts"},
    h("span", {class: "muted pos-when"}, pos.entry_time ? `${fmt.kst(pos.entry_time)} 진입` : "", held ? ` · ${held} 보유` : "",
      ` · ${fmt.tfKo(a.timeframe)}봉`, o.collapsible ? ` · ${groupKo(a)}` : ""),
    o.href ? h("a", {class: "btn-line", href: o.href("chart", pos.symbol, {acct: a.account_id, tf: a.timeframe})}, "차트") : null,
    o.href && (a.kind === "strategy" || a.kind === "copy" || a.kind === "reel") ? h("a", {class: "btn-line", href: o.href("strategies", a.strategy, {tf: a.timeframe, sym: pos.symbol}), title: "이 매매법 차트에서 이 포지션 보기"}, "매매법 차트") : null,
    o.href && !o.noAccountLink ? h("a", {class: "btn-line", href: o.href("account", a.account_id)}, "계좌") : null);
  // the price since the entry (5m closes + the mark now): filled by setSpark when the page has the bars
  const sparkBox = h("div", {class: "pos-spark", hidden: true},
    h("div", {class: "pos-spark-k"}, h("span", null, "진입 뒤 가격"), h("span", {class: "muted"}, "5분봉 종가 · 점선 진입가 · 붉은 점선 손절")),
    h("div", {class: "pos-spark-g"}));
  const body = [
    co ? h("p", {class: "pos-plain pos-count-only"}, h("b", null, COUNT_ONLY_KO), " · ", COUNT_ONLY_WHY) :
      h("div", {class: "pnl pos-led"}, h("div", null, h("span", {class: "k"}, "미실현 손익 (USDT)"), pnlEl),
        h("div", {class: "r"}, h("span", {class: "k"}, "ROI"), roiEl)),
    sparkBox,
    whyBox(a, pos, o.why, co ? null : o.wallet), ui.kv(pairs), meter, co ? null : stopLine(a, pos), ruleLine(a, pos), acts,
    o.caption === false || co ? null : ui.assume("open"),
  ];
  const head = h("div", {class: "pos-top"}, h("span", {class: "pos-sym"}, `${fmt.coin(pos.symbol)}USDT`), h("span", {class: "muted pos-perp"}, "무기한"),
    ui.sideTag(pos.side), h("span", {class: "muted"}, `격리 ${fmt.lev(pos.leverage)}`), h("span", {class: "grow"}),
    ui.pill(groupKo(a), fmt.groupOf(a) === "core" ? "accent" : ""));
  let el, rowPnl = null, rowRoi = null;
  const rowSpark = h("span", {class: "pos-row-spark", "aria-hidden": "true"});
  if (o.collapsible) {
    rowPnl = h("b", {class: ["num", co ? "muted" : ""]}, co ? COUNT_ONLY_KO : "—"); rowRoi = h("small", {class: "num"}, co ? groupKo(a) : "—");
    const region = h("div", {class: "pos-body", hidden: !o.open}, body);
    const btn = h("button", {class: "pos-row", type: "button", "aria-expanded": String(!!o.open), title: a.account_id},
      ui.sideTag(pos.side),
      h("span", {class: "pos-row-t"}, h("b", null, `${fmt.coin(pos.symbol)}USDT · 격리 ${fmt.lev(pos.leverage)}`), h("small", null, nameNode(a, o.data))),
      h("span", {class: "pos-row-v"}, rowSpark, h("span", {class: "pos-row-n"}, rowPnl, rowRoi)), h("span", {class: "pos-chev", "aria-hidden": "true"}, "▾"));
    btn.addEventListener("click", () => {
      const open = btn.getAttribute("aria-expanded") !== "true";
      btn.setAttribute("aria-expanded", String(open));
      el.classList.toggle("open", open);
      motion.expand(region, open);
      if (o.onToggle) o.onToggle(a.account_id, open);
    });
    el = h("article", {class: ["pos-card", "card", "pos-fold", o.open ? "open" : "", co ? "count-only" : ""], "aria-label": `${fmt.coin(pos.symbol)} ${fmt.sideKo(pos.side)} · ${name}`}, btn, region);
  } else {
    el = h("article", {class: ["pos-card", "card", "open", co ? "count-only" : ""], "aria-label": `${fmt.coin(pos.symbol)} ${fmt.sideKo(pos.side)} · ${name}`},
      head, o.noName ? null : h("div", {class: "pos-acct"}, name), body);
  }
  el.pos = pos;
  let sparkDrawn = false, lastSgn = null, nearDone = false;
  /** The price path since the entry (real closes, then the mark now). The line is green while the position is in
   *  profit (a short: the price below the entry), red otherwise; it draws itself in once. */
  el.setSpark = (vals) => {
    if (!vals || vals.length < 2) return;
    const last = vals[vals.length - 1];
    const tone = co ? "" : pos.side * (last - pos.entry) >= 0 ? "up" : "down";
    const refs = pos.stop != null ? [{v: pos.stop, cls: "stopl"}] : [];
    sparkBox.hidden = false;
    sparkBox.lastChild.replaceChildren(ui.miniSpark(vals, {w: 300, h: 46, fluid: true, base: pos.entry, refs, tone,
      draw: !sparkDrawn, label: "진입 뒤 가격 흐름"}));
    rowSpark.replaceChildren(ui.miniSpark(vals, {w: 52, h: 20, base: pos.entry, tone, label: "진입 뒤 가격 흐름"}));
    sparkDrawn = true;
  };
  el.update = (mark) => {
    const u = co ? null : derive.livePnl(pos, mark);
    // one soft ring when the unrealized P&L crosses zero, and once when the mark comes within 0.5% of the stop
    const sgn = u && u.pnl != null ? Math.sign(Math.round(u.pnl * 100)) : null;
    if (sgn && lastSgn && sgn !== lastSgn) motion.ring(el, sgn > 0 ? "up" : "down");
    if (sgn) lastSgn = sgn;
    if (!co) {
      motion.countTo(pnlEl, u && u.pnl, {dec: 2, sign: true, tone: true, glow: true});
      motion.countTo(roiEl, u && u.roe, {format: "pct", dec: 2, tone: true});
    }
    if (rowPnl && !co) {
      motion.countTo(rowPnl, u && u.pnl, {dec: 2, sign: true, tone: true, glow: true});
      motion.countTo(rowRoi, u && u.roe, {format: "pct", dec: 2, tone: true});
    }
    motion.tickPrice(markEl, mark || null, mark ? fmt.price(mark) : "—", pos.symbol);
    const dLiq = derive.distTo(mark, pos.liq), dStop = derive.distTo(mark, pos.stop);
    if (dStop != null && dStop < 0.005 && !nearDone) { nearDone = true; motion.ring(el, "down"); }
    dLiqEl.textContent = dist(dLiq);
    dStopEl.textContent = dist(dStop);
    dLiqEl.classList.toggle("pos-near", dLiq != null && dLiq < 0.02);
    if (reel) {
      const dt = pos.target && mark ? (pos.target - mark) / mark : null;
      dTgtEl.textContent = dt == null ? "—" : fmt.pct(dt, 2);
    }
    const r = dLiq && dStop != null ? Math.max(0, Math.min(1, dStop / dLiq)) : null;
    meter.style.setProperty("--stop", r == null ? "50%" : (r * 100).toFixed(1) + "%");
    meter.classList.toggle("none", r == null);
    return u;
  };
  return el;
}

// ---------------------------------------------------------------- closed trades
/** A closed trade as one list row (tap -> account). t: /api/trades or /api/account trade row; a: its board row.
 *  o.replay: the 거래 다시보기 link of this trade (ctx.href("replay", String(t.id))) -> a "다시보기" button in the row. */
export function tradeRow(t, a, o = {}) {
  const today = t.exit_time >= fmt.kstMidnight(serverNow());
  const reason = fmt.reasonKo(t.exit_reason) + (t.exit_reason === "LOCK" && t.lock_roe ? ` +${fmt.num(t.lock_roe * 100, 0)}%` : "");
  const nm = o.noName ? null : a ? ui.acctLabel(a) : fmt.idName(t.account_id);
  const meta = h("span", {class: "meta"},
    o.noName ? null : h("span", null, fmt.coin(t.symbol)), ui.sideTag(t.side), h("span", null, fmt.lev(t.leverage)),
    h("span", {class: t.exit_reason === "LIQ" ? "down" : ""}, reason), o.countOnly ? null : h("span", {class: fmt.tone(t.roe)}, `ROE ${fmt.pct(t.roe)}`),
    t.tier === "best" ? ui.pill("좋은 자리", "good") : null, a && !o.noName ? h("span", null, groupKo(a)) : null,
    o.prices ? h("span", null, `${fmt.price(t.entry_price)} → ${fmt.price(t.exit_price)}`) : null,
    o.equity && !o.countOnly && t.equity_after != null ? h("span", null, `잔고 ${fmt.money(t.equity_after)}`) : null);
  const kids = [h("span", {class: "rk"}, today ? fmt.hm(t.exit_time) : fmt.kst(t.exit_time)),
    h("span", {class: "lname", title: t.account_id}, o.noName ? `${fmt.coin(t.symbol)}USDT` : nm),
    o.countOnly ? h("span", {class: "ret muted", title: COUNT_ONLY_WHY}, COUNT_ONLY_KO) : h("span", {class: ["ret", fmt.tone(t.pnl)]}, fmt.money(t.pnl, true)), meta];
  const rp = o.replay && t.id != null;
  if (rp) kids.push(h("a", {class: "pos-replay", href: o.replay, title: "이 거래를 봉 하나씩 다시 보기", "aria-label": "이 거래 다시보기",
    onclick: (e) => e.stopPropagation(), onkeydown: (e) => e.stopPropagation()}, "▶ 다시보기"));
  if (o.why && t.why) kids.push(h("span", {class: "pos-twhy"}, `왜 ${fmt.lev(t.leverage)}: `, whyShort(t.why, a)));
  const attrs = {class: ["lrow", "pos-trow", o.onClick ? "click" : "", rp ? "has-replay" : ""], role: "listitem"};
  if (o.onClick) { attrs.onclick = () => o.onClick(t); attrs.tabindex = "0"; attrs.onkeydown = (e) => { if (e.key === "Enter") o.onClick(t); }; }
  return h("div", attrs, kids);
}
/** levwhy compact -> "보통 · 첫 후보 30배 그대로". a: the account (DeepSeek / 5m: the fixed 보통 line). */
export function whyShort(w, a) {
  if (!w) return "—";
  const parts = [];
  if (w.group_ko) parts.push(w.group_ko);
  if (fixedNormal(a)) { parts.push(FIXED_NORMAL_KO); return parts.join(" · "); }
  if (w.score != null) parts.push(`품질 점수 ${fmt.num(w.score, 2)}`);
  else if (w.source === "coin_flip") parts.push(`동전 봇 (좋은 자리 확률 ${fmt.pct(w.p_best || 0, 0, false)})`);
  if (w.short_ko) parts.push(w.short_ko);
  return parts.join(" · ");
}

/** "N건 · 합계 +12.30 USDT · 이긴 거래 a" for a list of trades. isCountOnly(t) (D10/D11): those trades are only
 *  counted ("딥시크·동전 봇 n건 (개수만)") and left out of the sum and the wins. */
export function tradeSum(rows, isCountOnly) {
  const co = isCountOnly ? rows.filter(isCountOnly) : [];
  const money = co.length ? rows.filter((t) => !isCountOnly(t)) : rows;
  const tot = money.reduce((s, t) => s + (Number(t.pnl) || 0), 0), wins = money.filter((t) => t.pnl > 0).length;
  const liq = money.filter((t) => t.exit_reason === "LIQ").length;
  return h("p", {class: "pos-sum"}, `${fmt.int(money.length)}건 · 합계 `, h("b", {class: fmt.tone(tot)}, fmt.usdt(tot, true)),
    ` · 이긴 거래 ${fmt.int(wins)}`, liq ? h("span", {class: "down"}, ` · 강제청산 ${fmt.int(liq)}`) : null,
    co.length ? h("span", {class: "muted", title: COUNT_ONLY_WHY}, ` · 딥시크·동전 봇 ${fmt.int(co.length)}건 (개수만)`) : null);
}

/** 한 방향 몰림: at least SKEW_MIN positions on a coin and one side holding SKEW_SHARE of them or more. Counts only. */
export const SKEW_MIN = 5;
export const SKEW_SHARE = 0.8;
/** {long, short} -> "long" | "short" | null (not enough positions, or no side at 80 %). */
export function oneSided(c) {
  const l = Math.max(0, Number(c && c.long) || 0), sh = Math.max(0, Number(c && c.short) || 0), n = l + sh;
  if (n < SKEW_MIN) return null;
  return l / n >= SKEW_SHARE ? "long" : sh / n >= SKEW_SHARE ? "short" : null;
}
/** Open positions per coin by side: [{pos: {symbol, side}}] -> {sym: {long, short}}. */
export function sideCounts(list) {
  const out = {};
  for (const x of list || []) {
    const p = x && (x.pos || x);
    if (!p || !p.symbol) continue;
    const c = out[p.symbol] || (out[p.symbol] = {long: 0, short: 0});
    if (Number(p.side) > 0) c.long++; else c.short++;
  }
  return out;
}

/** Coin strip: [전체 n] [BTC n] ... as a segmented control. counts: {sym: n}. o.sides ({sym: {long, short}}): each coin
 *  shows "9↑ 3↓" (롱 ↑ · 숏 ↓) instead of its total, and a dot when it leans one way (oneSided). */
export function coinSeg(syms, counts, value, onChange, o = {}) {
  const total = Object.values(counts || {}).reduce((s, n) => s + n, 0);
  const lab = (s) => {
    if (!o.sides) return [fmt.coin(s), h("small", {class: "pos-cnt"}, fmt.int((counts || {})[s] || 0))];
    const c = o.sides[s] || {long: 0, short: 0}, sk = oneSided(c);
    return [fmt.coin(s), h("small", {class: "pos-cnt pos-ls", title: `롱 ${fmt.int(c.long)} · 숏 ${fmt.int(c.short)}`},
      h("span", {class: c.long ? "up" : ""}, `${fmt.int(c.long)}↑`), " ", h("span", {class: c.short ? "down" : ""}, `${fmt.int(c.short)}↓`)),
      sk ? h("i", {class: ["pos-skew", sk], role: "img", "aria-label": `한 방향 몰림: ${sk === "long" ? "롱" : "숏"}이 80% 이상`,
        title: `한 방향 몰림 · ${sk === "long" ? "롱" : "숏"} ${fmt.int(sk === "long" ? c.long : c.short)} / ${fmt.int(c.long + c.short)}`}) : null];
  };
  const opts = [{id: "", label: [o.allLabel || "전체", h("small", {class: "pos-cnt"}, fmt.int(total))]}].concat(syms.map((s) =>
    ({id: s, label: lab(s)})));
  return ui.seg(opts, value, onChange, {label: o.label || "코인", scroll: true});
}
