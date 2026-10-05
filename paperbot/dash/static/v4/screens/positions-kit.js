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
 * collapsible, open, href (ctx.href), onChart, caption}.
 */
export function posCard(a, pos, o = {}) {
  const reel = reelExits(a);
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
    [`크기 (${fmt.coin(pos.symbol)})`, qty(pos.qty)], ["증거금 (USDT)", fmt.money(pos.margin)],
    !reel && pos.stop_initial && pos.stop_initial !== pos.stop ? ["첫 손절", fmt.price(pos.stop_initial)] : null,
  ];
  const held = pos.entry_time ? fmt.dur((serverNow() - pos.entry_time) / 1000) : null;
  const acts = h("div", {class: "pos-acts"},
    h("span", {class: "muted pos-when"}, pos.entry_time ? `${fmt.kst(pos.entry_time)} 진입` : "", held ? ` · ${held} 보유` : "",
      ` · ${fmt.tfKo(a.timeframe)}봉`, o.collapsible ? ` · ${groupKo(a)}` : ""),
    o.href ? h("a", {class: "btn-line", href: o.href("chart", pos.symbol, {acct: a.account_id, tf: a.timeframe})}, "차트") : null,
    o.href && (a.kind === "strategy" || a.kind === "copy") ? h("a", {class: "btn-line", href: o.href("strategies", a.strategy)}, "매매법") : null,
    o.href && !o.noAccountLink ? h("a", {class: "btn-line", href: o.href("account", a.account_id)}, "계좌") : null);
  const body = [
    h("div", {class: "pnl pos-led"}, h("div", null, h("span", {class: "k"}, "미실현 손익 (USDT)"), pnlEl),
      h("div", {class: "r"}, h("span", {class: "k"}, "ROI"), roiEl)),
    whyBox(a, pos, o.why, o.wallet), ui.kv(pairs), meter, stopLine(a, pos), ruleLine(a, pos), acts,
    o.caption === false ? null : ui.assume("open"),
  ];
  const head = h("div", {class: "pos-top"}, h("span", {class: "pos-sym"}, `${fmt.coin(pos.symbol)}USDT`), h("span", {class: "muted pos-perp"}, "무기한"),
    ui.sideTag(pos.side), h("span", {class: "muted"}, `격리 ${fmt.lev(pos.leverage)}`), h("span", {class: "grow"}),
    ui.pill(groupKo(a), fmt.groupOf(a) === "core" ? "accent" : ""));
  let el, rowPnl = null, rowRoi = null;
  if (o.collapsible) {
    rowPnl = h("b", {class: "num"}, "—"); rowRoi = h("small", {class: "num"}, "—");
    const region = h("div", {class: "pos-body", hidden: !o.open}, body);
    const btn = h("button", {class: "pos-row", type: "button", "aria-expanded": String(!!o.open), title: a.account_id},
      ui.sideTag(pos.side),
      h("span", {class: "pos-row-t"}, h("b", null, `${fmt.coin(pos.symbol)}USDT · 격리 ${fmt.lev(pos.leverage)}`), h("small", null, nameNode(a, o.data))),
      h("span", {class: "pos-row-v"}, rowPnl, rowRoi), h("span", {class: "pos-chev", "aria-hidden": "true"}, "▾"));
    btn.addEventListener("click", () => {
      const open = btn.getAttribute("aria-expanded") !== "true";
      btn.setAttribute("aria-expanded", String(open));
      el.classList.toggle("open", open);
      motion.expand(region, open);
      if (o.onToggle) o.onToggle(a.account_id, open);
    });
    el = h("article", {class: ["pos-card", "card", "pos-fold", o.open ? "open" : ""], "aria-label": `${fmt.coin(pos.symbol)} ${fmt.sideKo(pos.side)} · ${name}`}, btn, region);
  } else {
    el = h("article", {class: "pos-card card open", "aria-label": `${fmt.coin(pos.symbol)} ${fmt.sideKo(pos.side)} · ${name}`},
      head, o.noName ? null : h("div", {class: "pos-acct"}, name), body);
  }
  el.pos = pos;
  el.update = (mark) => {
    const u = derive.livePnl(pos, mark);
    motion.countTo(pnlEl, u && u.pnl, {dec: 2, sign: true, tone: true});
    motion.countTo(roiEl, u && u.roe, {format: "pct", dec: 2, tone: true});
    if (rowPnl) {
      motion.countTo(rowPnl, u && u.pnl, {dec: 2, sign: true, tone: true});
      motion.countTo(rowRoi, u && u.roe, {format: "pct", dec: 2, tone: true});
    }
    markEl.textContent = mark ? fmt.price(mark) : "—";
    const dLiq = derive.distTo(mark, pos.liq), dStop = derive.distTo(mark, pos.stop);
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
/** A closed trade as one list row (tap -> account). t: /api/trades or /api/account trade row; a: its board row. */
export function tradeRow(t, a, o = {}) {
  const today = t.exit_time >= fmt.kstMidnight(serverNow());
  const reason = fmt.reasonKo(t.exit_reason) + (t.exit_reason === "LOCK" && t.lock_roe ? ` +${fmt.num(t.lock_roe * 100, 0)}%` : "");
  const nm = o.noName ? null : a ? ui.acctLabel(a) : fmt.idName(t.account_id);
  const meta = h("span", {class: "meta"},
    o.noName ? null : h("span", null, fmt.coin(t.symbol)), ui.sideTag(t.side), h("span", null, fmt.lev(t.leverage)),
    h("span", {class: t.exit_reason === "LIQ" ? "down" : ""}, reason), h("span", {class: fmt.tone(t.roe)}, `ROE ${fmt.pct(t.roe)}`),
    t.tier === "best" ? ui.pill("좋은 자리", "good") : null, a && !o.noName ? h("span", null, groupKo(a)) : null,
    o.prices ? h("span", null, `${fmt.price(t.entry_price)} → ${fmt.price(t.exit_price)}`) : null,
    o.equity && t.equity_after != null ? h("span", null, `잔고 ${fmt.money(t.equity_after)}`) : null);
  const kids = [h("span", {class: "rk"}, today ? fmt.hm(t.exit_time) : fmt.kst(t.exit_time)),
    h("span", {class: "lname", title: t.account_id}, o.noName ? `${fmt.coin(t.symbol)}USDT` : nm),
    h("span", {class: ["ret", fmt.tone(t.pnl)]}, fmt.money(t.pnl, true)), meta];
  if (o.why && t.why) kids.push(h("span", {class: "pos-twhy"}, `왜 ${fmt.lev(t.leverage)}: `, whyShort(t.why, a)));
  const attrs = {class: ["lrow", "pos-trow", o.onClick ? "click" : ""], role: "listitem"};
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

/** "N건 · 합계 +12.30 USDT · 이긴 거래 a" for a list of trades. */
export function tradeSum(rows) {
  const tot = rows.reduce((s, t) => s + (Number(t.pnl) || 0), 0), wins = rows.filter((t) => t.pnl > 0).length;
  const liq = rows.filter((t) => t.exit_reason === "LIQ").length;
  return h("p", {class: "pos-sum"}, `${fmt.int(rows.length)}건 · 합계 `, h("b", {class: fmt.tone(tot)}, fmt.usdt(tot, true)),
    ` · 이긴 거래 ${fmt.int(wins)}`, liq ? h("span", {class: "down"}, ` · 강제청산 ${fmt.int(liq)}`) : null);
}

/** Coin strip: [전체 n] [BTC n] ... as a segmented control. counts: {sym: n}. */
export function coinSeg(syms, counts, value, onChange, o = {}) {
  const total = Object.values(counts || {}).reduce((s, n) => s + n, 0);
  const opts = [{id: "", label: [o.allLabel || "전체", h("small", {class: "pos-cnt"}, fmt.int(total))]}].concat(syms.map((s) =>
    ({id: s, label: [fmt.coin(s), h("small", {class: "pos-cnt"}, fmt.int((counts || {})[s] || 0))]})));
  return ui.seg(opts, value, onChange, {label: o.label || "코인", scroll: true});
}
