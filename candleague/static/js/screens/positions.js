// #/positions 포지션 · 모의 계좌의 열린 포지션, in the rule bot's v4 look (copied and adapted from
// paperbot/dash/static/v4/screens/positions.js; nothing imported from it). From the top:
//   the freshness line (엔진 기준 HH:MM · 시세 n초 전) and, while the engine replays from 10/01 or its record is old, a
//   banner (no live P&L then: the positions are "그때 기준")
//   the summary over the chosen 묶음 and coin: 미실현 손익 합계 (USDT) at the mark, 묶인 증거금 대비 %, 롱 · 숏, 수익 중 /
//   손실 중, 묶인 증거금, hidden DeepSeek positions counted only; 가장 많이 버는·잃는 포지션
//   the coin chips (전체 n, BTC n↑ m↓ with the 한 방향 몰림 dot)
//   tabs 포지션 n / 손절·잠금 주문 / 체결 기록; 묶음 and sort selects; the position cards (all open in a 2-3 column grid at
//   1280 px and wider, one-line rows that open below), 12 per page
//   the side card 위험 사다리 (청산까지 / 손절선까지)
//   the switch 설치 뒤 진입만 (js/after.js) under the freshness line: on, the cards, the ladder, the orders, the 체결 기록
//   tab, the coin chips, the 포지션 n tab and the summary keep only what was entered after the install (labelled 설치
//   뒤만); a list it emptied says how many it hid (and offers to turn it off)
// Data: /api/positions (poskit: every 30 s and on each new engine snapshot), /api/live (5 s: the mark), /api/klines 5m
// (진입 뒤 가격, per coin, again after 5 minutes), /api/fills (체결 기록). Nothing here can place an order.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import * as LK from "../lk.js";
import {markOf, liveState} from "../live.js";
import {livePnl, sums, crowd, POS_GROUPS, inGroup, liveAllowed, liveOk, waitKo as whyKo, freshLine, staleBanner, snapAge} from "../poskit.js";
import {COINS, coinShort, KIND_KO} from "../labels.js";
import {posCard, nameNode, usdt, HIDDEN_KO, HIDDEN_WHY} from "./positions-card.js";
import {riskLadder} from "./positions-risk.js";
import {ordersPane, tradesPane} from "./positions-orders.js";
import {afterBar, afterPositions, afterTag, afterSuffix, afterEmpty} from "../after.js";

export const css = "scr/positions.css";

const SORTS = [{id: "pnl", label: "수익 큰 순"}, {id: "loss", label: "손실 큰 순"}, {id: "new", label: "최근 진입"}, {id: "liq", label: "청산 가까운 순"}];
const GROUP_KO = Object.fromEntries(POS_GROUPS.map((g) => [g.id, g.ko]));
const PAGE = 12;
const PX_TTL = 5 * 60000;
const M5 = 300000;
export const ASSUME_KO = "모의 · 실제 시세 · 마크 가격 기준 미실현 (나갈 때 수수료 전) · 주문 버튼 없음 · 크기·증거금·청산가는 진입 때 기준 (펀딩 전)";

const coinKey = (c) => {
  const x = String(c || "").toUpperCase().replace(/USDT$/, "USD");
  const k = x && !x.endsWith("USD") ? `${x}USD` : x;
  return COINS.includes(k) ? k : "";
};

/** The order of a list: the shown positions by the chosen sort, the hidden (count-only) ones last by entry time, so their
 *  place never says how much they made. pnlOf(p) -> live P&L or null; gapOf(p) -> distance to liquidation or null. */
export function sortPositions(list, sort, pnlOf, gapOf) {
  const shown = list.filter((p) => !p.hidden), hid = list.filter((p) => p.hidden);
  const since = (a, b) => (b.since || 0) - (a.since || 0) || String(a.id).localeCompare(String(b.id));
  const nullLast = (va, vb, dir) => (va == null && vb == null ? 0 : va == null ? 1 : vb == null ? -1 : dir * (va - vb));
  const by = {
    pnl: (a, b) => nullLast(pnlOf(a), pnlOf(b), -1) || since(a, b),
    loss: (a, b) => nullLast(pnlOf(a), pnlOf(b), 1) || since(a, b),
    new: since,
    liq: (a, b) => nullLast(gapOf(a), gapOf(b), 1) || since(a, b),
  };
  return [...shown.sort(by[sort] || by.pnl), ...hid.sort(since)];
}

export async function mount(el, ctx) {
  el.classList.add("ps-scr", "ps-pos");
  try { await ctx.meta(); } catch (e) { /* names fall back to codes */ }
  if (!ctx.alive()) return undefined;                          // left while the names loaded: subscribe to nothing
  const q = ctx.params.query || {};
  const st = {
    coin: coinKey(q.coin) || coinKey(local.get("ps-coin", "")), tab: local.get("ps-tab", "pos"), sort: local.get("ps-sort", "pnl"),
    grp: local.get("ps-grp", "cand"), doc: null, open: new Set(), firstOpen: true, focus: q.acct || null, pin: null, countsKey: "", lastGen: null,
    sortedWith: 0, sortedLive: false, // how many shown positions had a sort value, and were live numbers allowed, when
                                      // the cards were last ordered
  };
  if (coinKey(q.coin)) local.set("ps-coin", st.coin);          // #/positions?coin=BTCUSD (a link from another screen)
  if (!POS_GROUPS.some((g) => g.id === st.grp)) st.grp = "cand";
  if (!SORTS.some((x) => x.id === st.sort)) st.sort = "pnl";
  if (!["pos", "ord", "trd"].includes(st.tab)) st.tab = "pos";
  const cards = new Map();            // account id -> {key, el}: reused, so a number counts from its last value
  const wideMq = typeof matchMedia === "function" ? matchMedia("(min-width: 1280px)") : null;
  let wide = !!(wideMq && wideMq.matches);
  /** Live P&L, ROE and distances may show: the snapshot is "now" and the prices are live (poskit liveOk). */
  const allowed = () => liveOk(st.doc);
  /** The snapshot alone is "now" (the 진입 뒤 가격 bars then run to the present, not to the engine's time). */
  const snapNow = () => liveAllowed(st.doc);
  /** Why live numbers are hidden (the words on the cards, the ladder and the orders). */
  const waitKo = () => whyKo(st.doc) || "엔진이 따라잡는 중";

  // ---------------------------------------------------------------- 진입 뒤 가격: one /api/klines 5m per coin, again after 5 min
  const px = new Map();               // coin|end -> {at, bars, busy}
  const pxKey = (coin) => `${coin}|${snapNow() ? "" : (st.doc && st.doc.done_ms) || ""}`;
  const needPx = (coin) => {
    const key = pxKey(coin), c = px.get(key);
    if (c && (c.busy || Date.now() - c.at < PX_TTL)) return;
    px.set(key, {...(c || {}), busy: true, at: c ? c.at : 0});
    const end = snapNow() || !st.doc ? "" : `&end=${st.doc.done_ms}`;
    ctx.api(`/api/klines?coin=${encodeURIComponent(coin)}&tf=5m&limit=288${end}`).then((d) => {
      px.set(key, {at: Date.now(), bars: d && d.bars ? d.bars : null, busy: false});
      if (ctx.alive()) for (const x of cards.values()) if (x.el.pos.coin === coin) sparkOf(x.el);
    }).catch(() => { px.set(key, {at: Date.now(), bars: (c && c.bars) || null, busy: false}); });
  };
  const sparkOf = (cardEl) => {
    const p = cardEl.pos;
    if (p.hidden || p.entry == null) return;
    const c = px.get(pxKey(p.coin));
    if (!c || !c.bars || !Array.isArray(c.bars.t) || !p.since) return;
    const ok = allowed(), now = snapNow();
    const t0 = Math.floor(p.since / M5) * M5;
    const lim = now ? Infinity : Number(st.doc.done_ms);
    // older than the 24 hours of bars: the last 24 hours only (the dashed line still marks the entry price)
    const older = c.bars.t.length > 0 && c.bars.t[0] > t0;
    const vals = older ? [] : [Number(p.entry)];
    for (let i = 0; i < c.bars.t.length; i++) {
      const t = c.bars.t[i];
      if (t >= t0 && t <= lim) vals.push(c.bars.c[i]);
    }
    const m = ok ? markOf(p.coin) : null;
    if (m != null) vals.push(m);
    cardEl.setSpark(vals, {note: [older ? "최근 24시간만" : "", now ? "" : "엔진 기준 시각까지"].filter(Boolean).join(" · ")});
  };

  // ---------------------------------------------------------------- skeleton
  const fresh = freshLine(null, {cls: "ps-fresh"});
  const afterEl = afterBar({cls: "ps-after"});
  const sumTag = h("span", {class: "ps-aftertag"});
  const bannerSlot = h("div", {class: "ps-banner"});
  const sumNum = h("b", {class: "num ps-big ps-pnl"}, "—");
  const sumSub = h("span", {class: "s"}, "");
  const lsEl = h("b", {class: "num ps-big"}, "—"), nOpenSub = h("span", {class: "s"}, "");
  const liveChip = K4.liveDot("시세 기다리는 중", "off");
  const line = h("p", {class: "ps-line"});
  const bestLine = h("div", {class: "ps-bw"});
  const sumCard = h("section", {class: "card ps-sum", "aria-label": "열린 포지션 요약"},
    h("div", {class: "stats"},
      K4.stat(h("span", null, "미실현 손익 합계 (USDT) ", sumTag, h("span", {class: "ps-tip", tabindex: "0", role: "note", title: ASSUME_KO, "aria-label": `설명: ${ASSUME_KO}`}, "ⓘ")), sumNum, sumSub),
      K4.stat("롱 · 숏", lsEl, nOpenSub)),
    h("div", {class: "ps-sumfoot"}, line, liveChip),
    ui.disclosure("가장 많이 버는·잃는 포지션", bestLine));
  const coinBar = h("div", {class: "ps-coins"});
  const tabBar = h("div", {class: "ps-tabs"});
  const tabBody = h("div", {class: "stack"});
  const ladder = riskLadder(ctx);
  const side = h("div", {class: "stack ps-side"}, ladder.el);
  el.append(ui.screenHead("포지션", "모의 계좌의 열린 포지션"), fresh, afterEl, bannerSlot, sumCard, coinBar,
    h("div", {class: "ps-cols"}, h("div", {class: "stack ps-main"}, tabBar, tabBody), side),
    h("p", {class: "assume once ps-assume"}, ASSUME_KO));

  // ---------------------------------------------------------------- data helpers
  const all = () => (st.doc && Array.isArray(st.doc.positions) ? st.doc.positions : []);
  const inScope = (p) => (!st.coin || p.coin === st.coin) && inGroup(p, st.grp);
  /** 설치 뒤 진입만: the open positions in scope that the switch left out (entered before the install) */
  const beforeIn = () => (st.doc && st.doc.after ? st.doc.after.before.filter(inScope).length : 0);
  const pnlOf = (p) => { if (!allowed()) return null; const u = livePnl(p); return u ? u.pnl : null; };
  const gapOf = (p) => { if (allowed()) { const u = livePnl(p); return u ? u.liqGap : null; } return p.liq_dist_entry ?? null; };

  // ---------------------------------------------------------------- the coin chips (counts of open positions)
  const renderCoins = () => {
    if (!st.doc || st.doc.status) { st.countsKey = ""; put(coinBar); return; }
    const mine = all().filter((p) => inGroup(p, st.grp));
    const sides = {};
    for (const c of COINS) sides[c] = {long: 0, short: 0};
    for (const p of mine) if (sides[p.coin]) sides[p.coin][Number(p.side) > 0 ? "long" : "short"] += 1;
    const key = JSON.stringify([sides, st.coin, st.grp]);
    if (key === st.countsKey) return;
    st.countsKey = key;
    const skewed = COINS.some((c) => crowd(sides[c]).on);
    const lab = (c) => {
      const x = sides[c], k = crowd(x);
      return [coinShort(c), h("small", {class: "ps-cnt ps-ls", title: `롱 ${fmt.int(x.long)} · 숏 ${fmt.int(x.short)}`},
        h("span", {class: x.long ? "up" : ""}, `${fmt.int(x.long)}↑`), " ", h("span", {class: x.short ? "down" : ""}, `${fmt.int(x.short)}↓`)),
      k.on ? h("i", {class: "ps-skew", role: "img", "aria-label": `한 방향 몰림: ${k.side > 0 ? "롱" : "숏"}이 80% 이상`,
        title: `한 방향 몰림 · ${k.side > 0 ? "롱" : "숏"} ${fmt.int(k.side > 0 ? x.long : x.short)} / ${fmt.int(k.n)}`}) : null];
    };
    const opts = [{id: "", label: ["전체", h("small", {class: "ps-cnt"}, fmt.int(mine.length))]}, ...COINS.map((c) => ({id: c, label: lab(c)}))];
    put(coinBar, ui.seg(opts, st.coin, (v) => { st.coin = v; st.pin = null; local.set("ps-coin", v); st.countsKey = ""; renderAll(false); }, {label: "코인 고르기", cls: "scroll"}),
      h("p", {class: "pos-note ps-skew-note"}, "↑ 롱 · ↓ 숏 개수", afterSuffix(st.doc),
        skewed ? [" · ", h("i", {class: "ps-skew", "aria-hidden": "true"}), " 한 방향 몰림 (5개 이상 중 한쪽 80% 이상)"] : null,
        st.grp !== "all" ? ` · ${GROUP_KO[st.grp]} 묶음` : ""));
  };

  // ---------------------------------------------------------------- the summary (follows the coin and 묶음)
  const renderSum = () => {
    const d = st.doc;
    if (!d) { sumNum.textContent = "—"; sumSub.textContent = ""; lsEl.textContent = "—"; nOpenSub.textContent = "불러오는 중"; put(line, "불러오는 중"); put(bestLine); return; }
    if (d.status) { sumNum.textContent = "—"; sumSub.textContent = ""; lsEl.textContent = "—"; nOpenSub.textContent = "준비 중"; put(line, "엔진이 첫 기록을 쓰면 저절로 나타납니다."); put(bestLine); return; }
    const ok = allowed();
    const list = all().filter(inScope);
    const t = sums(list, ok ? markOf : () => null);
    const allHidden = t.n > 0 && t.hidden === t.n;
    K4.countTo(sumNum, t.priced ? t.pnl : null, {format: (v) => fmt.num(v, 2, true), tone: true});
    // 묶인 증거금 대비: the P&L over the margin of the same (priced) positions; a coin without a price is out of both
    sumSub.textContent = allHidden ? `딥시크 금액 숨김 (${HIDDEN_KO})` : !ok ? `${waitKo()}: 실시간 손익 감춤`
      : t.priced && t.pricedMargin ? `묶인 증거금 대비 ${fmt.pct((t.pnl / t.pricedMargin) * 100, true, 2)}${t.unpriced ? ` (시세 있는 ${fmt.int(t.priced)}개)` : ""}`
        : t.n ? "시세를 기다리는 중" : "열린 포지션 없음";
    sumSub.className = "s " + (ok && t.priced ? fmt.tone(t.pnl) : "");
    lsEl.textContent = `${fmt.int(t.long)} · ${fmt.int(t.short)}`;
    const scope = [st.coin ? coinShort(st.coin) : "", GROUP_KO[st.grp] || ""].filter(Boolean).join(" · ");
    nOpenSub.textContent = `열린 ${fmt.int(t.n)}개${scope ? " · " + scope : ""}${afterSuffix(d)}`;
    put(sumTag, afterTag(d));
    if (allHidden) put(line, h("span", {class: "muted", title: HIDDEN_WHY}, `딥시크 ${fmt.int(t.hidden)}개 (${HIDDEN_KO}: 서버가 금액·가격을 보내지 않아 합계가 없습니다)`));
    else put(line, ok ? ["수익 중 ", h("b", {class: "up"}, fmt.int(t.winning)), " · 손실 중 ", h("b", {class: "down"}, fmt.int(t.losing)), " · "] : null,
      ok && t.unpriced ? [h("b", {class: "warn-t", title: "이 코인들은 지금 시세가 없어 손익 합계와 수익 중·손실 중에서 뺐습니다 (0으로 세지 않음)"},
        `시세 없음 ${fmt.int(t.unpriced)}`), " · "] : null,
      "묶인 증거금 ", h("b", {class: "num"}, usdt(t.margin)),
      t.hidden ? h("span", {class: "muted", title: HIDDEN_WHY}, ` · 딥시크 ${fmt.int(t.hidden)}개 (${HIDDEN_KO}, 합계에서 뺌)`) : null);
    let best = null, worst = null;
    if (ok) for (const p of list) { const v = pnlOf(p); if (v == null) continue; if (!best || v > best.v) best = {p, v}; if (!worst || v < worst.v) worst = {p, v}; }
    const bw = (lab, b) => (b ? h("a", {class: "ps-bwl", href: ctx.href("positions", null, {acct: b.p.id, coin: b.p.coin})},
      h("span", {class: "muted"}, lab), h("b", {class: "ps-bwn"}, nameNode(b.p)), h("span", {class: "muted"}, `${coinShort(b.p.coin)} ${Number(b.p.side) > 0 ? "롱" : "숏"}`),
      h("b", {class: ["num", fmt.tone(b.v)]}, usdt(b.v, true))) : null);
    const byG = {};
    for (const p of list) { const g = `${KIND_KO[p.kind] || p.kind} ${GROUP_KO[p.role] || p.role}`; byG[g] = (byG[g] || 0) + 1; }
    put(bestLine, bw("가장 많이 버는 중", best && best.v > 0 ? best : null), bw("가장 많이 잃는 중", worst && worst.v < 0 ? worst : null),
      !ok ? h("p", {class: "pos-note"}, `${waitKo()}이라 지금 손익 순위는 감춥니다.`) : null,
      list.length ? h("p", {class: "ps-groups muted"}, "묶음별 ", Object.entries(byG).map(([g, n]) => `${g} ${fmt.int(n)}`).join(" · ")) : null);
  };
  const paintLive = () => {
    const ls = liveState();
    const d = st.doc;
    if (d && !d.status && d.catching_up) liveChip.set("엔진 따라잡는 중 · 실시간 손익 감춤", "warn");
    else if (d && !d.status && d.old) liveChip.set(`엔진 기록 ${fmt.dur(snapAge(d) || 0)} 전에 멈춤`, "bad");
    else if (ls.state === "ok") liveChip.set("실시간 · 5초마다", "ok");
    else if (ls.state === "fake") liveChip.set("시험용 시세 · 5초마다", "warn");
    else if (ls.state === "stale") liveChip.set(`시세 지난 값${ls.generated_ms ? ` (${fmt.hms(ls.generated_ms)})` : ""}${allowed() ? "" : " · 실시간 손익 감춤"}`, "warn");
    else liveChip.set(ls.ko, ls.state === "wait" ? "off" : "bad");
    el.classList.toggle("ps-stalepx", ls.state === "stale" || ls.state === "unavailable");
    fresh.update(d || undefined);
  };

  // ---------------------------------------------------------------- tab: 포지션 (cards, paged)
  const sortSel = ui.select(SORTS, st.sort, (v) => { st.sort = v; st.pin = null; local.set("ps-sort", v); renderAll(false); }, "정렬");
  const grpSel = ui.select(POS_GROUPS.map((g) => ({id: g.id, label: g.id === "all" ? "모든 묶음" : g.ko})), st.grp,
    (v) => { st.grp = v; st.pin = null; local.set("ps-grp", v); st.countsKey = ""; renderAll(false); }, "묶음");
  const keyOf = (p, open) => [open ? "o" : "c", p.hidden ? "h" : "m", p.since, p.stop, p.tp, p.liq, p.lev, p.margin, p.stop_is_lock].join("|");
  const onToggle = (id, o) => {
    if (o) st.open.add(id); else st.open.delete(id);
    const x = cards.get(id);
    if (x) x.key = keyOf(x.el.pos, o);
  };
  const cardOf = (p) => {
    const open = wide || st.open.has(p.id);
    const key = keyOf(p, open);
    let c = cards.get(p.id);
    if (!c || c.key !== key) {
      const elc = posCard(p, {open, href: ctx.href, onToggle});
      c = {key, el: elc};
      cards.set(p.id, c);
      elc.update(markOf(p.coin), allowed(), waitKo());
      sparkOf(elc);
    }
    if (!p.hidden) needPx(p.coin);
    return c.el;
  };
  const emptyPos = () => {
    if (!st.doc) return h("p", {class: "empty"}, "불러오는 중");
    if (st.doc.status) return ui.missing("포지션 자료");
    const n = all().length;
    const before = st.doc.after ? st.doc.after.before.length : 0;
    if (!n && before) return afterEmpty("설치 뒤에 들어간 열린 포지션이 아직 없습니다",
      `열린 포지션 ${fmt.int(before)}개는 모두 설치 전(10/01부터 다시 돌린 기록)에 들어간 것이라 '설치 뒤 진입만'에서 숨겼습니다.`, {cls: "ps-empty"});
    if (!n) return h("div", {class: "ps-empty"}, h("b", null, "지금 열린 포지션이 없습니다"),
      h("span", null, "엔진은 5분마다 신호를 확인합니다. 새 포지션은 들어간 뒤 5~10분 안에 여기에 나타납니다."),
      h("a", {class: "btn-line", href: "#/entries"}, "진입 차트 보기"));
    return h("div", {class: "ps-empty"}, h("b", null, "조건에 맞는 열린 포지션이 없습니다"),
      h("span", null, `${st.coin ? coinShort(st.coin) + " · " : ""}${GROUP_KO[st.grp] || ""} 묶음에는 없고, 전체로는 ${fmt.int(n)}개가 열려 있습니다${st.doc.after ? " (설치 뒤만)" : ""}.` +
        (beforeIn() ? ` 이 조건의 열린 포지션 ${fmt.int(beforeIn())}개는 설치 전에 들어간 것이라 숨겼습니다.` : "")),
      h("button", {class: "btn-line", type: "button", onclick: () => { st.coin = ""; st.grp = "all"; local.set("ps-coin", ""); local.set("ps-grp", "all"); grpSel.value = "all"; st.countsKey = ""; renderAll(false); }}, "전체 보기"));
  };
  const posPager = ui.pager({size: PAGE, render: (part) => h("div", {class: "ps-grid", role: "list"}, part.map(cardOf))});
  const posNote = h("p", {class: "pos-note"});
  const notePos = () => {
    posNote.textContent = (wide ? "넓은 화면이라 모든 카드를 펼쳐 둡니다. " : "한 줄을 누르면 펼쳐집니다. ") +
      "미실현 손익은 마크 가격 기준이고 5초마다 서버 시세로 바뀝니다. 새 진입·청산은 엔진이 5분마다 계산해 몇 분 늦게 보입니다.";
  };
  notePos();
  const posBody = h("div");
  const posPane = h("div", {class: "stack"}, h("div", {class: "row wrap ps-filters"}, grpSel, sortSel), posBody, posNote);

  // ---------------------------------------------------------------- tabs 손절·잠금 주문 / 체결 기록
  const ordPane = ordersPane(ctx);
  const trPane = tradesPane(ctx, {coin: () => st.coin, grp: st.grp});
  let tabKey = "";
  const renderTabBar = () => {
    const n = all().filter(inScope).length;
    const known = !!(st.doc && !st.doc.status);
    const aft = known && !!st.doc.after;                     // 설치 뒤 진입만: the count is over the kept positions
    const posLabel = known ? `포지션 ${fmt.int(n)}` : "포지션";
    const opts = [{id: "pos", label: aft ? [posLabel, afterTag(st.doc)] : posLabel}, {id: "ord", label: "손절·잠금 주문"}, {id: "trd", label: "체결 기록"}];
    const key = [posLabel, aft, "손절·잠금 주문", "체결 기록"].join("|") + st.tab;
    if (key === tabKey) return;
    tabKey = key;
    put(tabBar, ui.seg(opts, st.tab, (v) => { st.tab = v; local.set("ps-tab", v); tabKey = ""; renderTabBar(); showTab(true); }, {label: "포지션 보기"}));
  };
  const showTab = (animate) => {
    const pane = st.tab === "ord" ? ordPane.el : st.tab === "trd" ? trPane.el : posPane;
    if (tabBody.firstChild !== pane) put(tabBody, pane);
    if (animate) K4.swap(tabBody);
    if (st.tab === "trd") { if (!trPane.loaded) trPane.load(); else trPane.render(true); }
    if (st.tab === "ord") ordPane.set(all().filter(inScope), markOf, allowed(), false, waitKo(), beforeIn());
  };

  // ---------------------------------------------------------------- render everything
  function renderAll(keepPage) {
    renderCoins();
    renderTabBar();
    put(bannerSlot, staleBanner(st.doc));
    const ok = allowed();
    const list = sortPositions(all().filter(inScope), st.sort, pnlOf, gapOf);
    st.sortedWith = sortKnown();
    st.sortedLive = ok;
    const pin = st.pin ? list.findIndex((p) => p.id === st.pin) : -1;
    if (pin > 0) list.unshift(...list.splice(pin, 1));
    if (!list.length) { put(posBody, emptyPos()); } else {
      if (posBody.firstChild !== posPager.el) put(posBody, posPager.el);
      if (st.firstOpen && !wide && (ok ? liveState().state !== "wait" : true)) {     // the top row starts open (once)
        st.firstOpen = false;
        st.open.add(list[0].id);
      }
      posPager.set(list, keepPage);
    }
    for (const id of [...cards.keys()]) if (!all().some((p) => p.id === id)) cards.delete(id);
    renderSum();
    if (!st.doc || st.doc.status) ladder.loading(st.doc ? "준비 중" : "불러오는 중");
    else ladder.set(all().filter(inScope), markOf, ok, waitKo(), beforeIn());
    if (st.tab === "ord") ordPane.set(all().filter(inScope), markOf, ok, keepPage, waitKo(), beforeIn());
    if (st.tab === "trd" && trPane.loaded) trPane.render(keepPage);
    paintLive();
  }
  /** How many shown positions in scope have a value for the chosen sort now (0 before the first price for a live sort). */
  const sortKnown = () => {
    if (st.sort === "new") return -1;
    const f = st.sort === "liq" ? gapOf : pnlOf;
    let n = 0;
    for (const p of all()) if (!p.hidden && inScope(p) && f(p) != null) n += 1;
    return n;
  };
  const onLiveTick = () => {
    const ok = allowed();
    for (const c of cards.values()) if (c.el.isConnected) { c.el.update(markOf(c.el.pos.coin), ok, waitKo()); sparkOf(c.el); }
    // the order was made before these prices (the first tick after a load, a coin whose price came later): order once
    // more so 수익 큰 순 is true from the first prices, then keep it still until the next snapshot (no jumping cards)
    if (st.doc && !st.doc.status && st.sort !== "new" && (sortKnown() > st.sortedWith || ok !== st.sortedLive)) renderAll(true);
    else if (st.firstOpen && st.doc && !wide) renderAll(true);
    renderSum();
    if (st.doc && !st.doc.status) ladder.set(all().filter(inScope), markOf, ok, waitKo(), beforeIn());
    if (st.tab === "ord" && st.doc) ordPane.set(all().filter(inScope), markOf, ok, true, waitKo(), beforeIn());
    paintLive();
  };
  const focusAcct = () => {
    if (!st.focus || !st.doc || st.doc.status) return;
    const p = all().find((x) => x.id === st.focus);
    st.focus = null;
    if (!p) return;
    if (!inGroup(p, st.grp)) { st.grp = "all"; grpSel.value = "all"; }
    st.coin = p.coin;
    st.tab = "pos";
    st.open.add(p.id);
    st.countsKey = ""; tabKey = "";
    st.pin = p.id;
    showTab(false);
    renderAll(false);
    ctx.setQuery({});                                          // the address loses ?acct= (a reload does not jump again)
    const c = cards.get(p.id);
    if (c && c.el.isConnected && typeof c.el.scrollIntoView === "function") {
      c.el.scrollIntoView({block: "center", behavior: K4.reduced() ? "auto" : "smooth"});
      K4.flash(c.el, null);
    }
  };

  // ---------------------------------------------------------------- wiring
  const onWide = () => {
    const w = !!(wideMq && wideMq.matches);
    if (w === wide) return;
    wide = w;
    el.classList.toggle("ps-wide", wide);
    notePos();
    renderAll(true);
  };
  el.classList.toggle("ps-wide", wide);
  if (wideMq) wideMq.addEventListener("change", onWide);
  renderTabBar();
  showTab(false);
  renderAll(true);
  ctx.onPositions((d0) => {
    const d = afterPositions(d0);                              // 설치 뒤 진입만: the positions entered after the install
    const gen = d ? `${d.generated_ms}|${d.done_ms}|${d.catching_up}|${d.old}` : "";
    st.doc = d;
    afterEl.repaint(d0 || undefined);
    renderAll(true);
    if (gen !== st.lastGen) {
      st.lastGen = gen;
      if (st.tab === "trd" && trPane.loaded) trPane.load();
    }
    focusAcct();
  });
  ctx.onLive(onLiveTick);
  ctx.onLeague(() => { for (const c of cards.values()) c.key = ""; if (st.doc) renderAll(true); });
  ctx.every(30000, () => { if (st.doc) paintLive(); });
  return () => { if (wideMq) wideMq.removeEventListener("change", onWide); };
}
