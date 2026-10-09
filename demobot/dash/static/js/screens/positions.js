// #/positions 포지션 (CONTRACT 9.2, 9.8; round 5: the rule bot's v4 포지션 look for the demo lab). Every open demo
// position as a calm one-line row (side, coin, leverage, unrealized P&L, the account with its pixel character and its
// timeframe chip) that opens into the full card: the LED P&L, entry / now / stop (and the target when the exit has one),
// a meter from the price now to the stop (and on to the target), time held, the setting and the exit rule, and the
// account's leverage lines that share the entry (every account trades its 20 · 30 · 40 · 50배 lines together).
//   top     미실현 손익 합계 · 롱 · 숏 (one-sided warning like v4 when a coin leans 80 % one way over 5 entries or more)
//   filters the coin segment (each coin "3↑ 1↓"), the account-kind chips
//   tabs    포지션 n · 손절·목표 (closest to its stop first) · 체결 기록 (closed trades of trades.json: the newest 300
//           lines, one row per account entry, filters for side, result and kind)
//   side    손절 사다리: the entries closest to their stop, as bars that move with the live price
// Data: positions.json every 15 s, /api/live every 10 s (the P&L = the engine's number at the last closed 15m bar plus
// the move since; without a live price: the engine's own number and `last`), trades.json when its tab is opened.
// Paper only: no order button anywhere; the demo has no liquidation price per position, so none is drawn.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {COINS, KINDS, KIND_KO, kindOfId, sideKo, reasonKo, targetR} from "../labels.js";
import * as K from "../live-kit.js";

const SKEW_MIN = 5, SKEW_SHARE = 0.8;
const STOP_CAP = 0.05;            // the ladder's bar is full at the stop, empty 5 % or more away
const NEAR = 0.005;               // within 0.5 % of the stop: the ladder row is marked (a real price move only)
const SORTS = [["pnl", "수익 큰 순"], ["loss", "손실 큰 순"], ["new", "최근 진입"], ["stop", "손절 가까운 순"]];
const shortOf = (id) => (/-(S2|N02|N04)-/.exec(String(id)) || [])[1] || null;
const acctOf = (g) => ({id: g.id, kind: g.kind || kindOfId(g.id), tf: g.tf, name: g.name, short: shortOf(g.id)});
const finite = (v) => v != null && Number.isFinite(Number(v));
const pctS = (r, dec = 2) => (finite(r) ? `${fmt.num(Number(r) * 100, dec, true)}%` : "—");

export async function mount(el, ctx) {
  await K.needCss();
  ctx.setTitle("포지션");
  const qCoin = COINS.includes(ctx.params.query.coin) ? ctx.params.query.coin : null;
  const st = {
    coin: qCoin || (COINS.includes(local.get("pos-coin")) ? local.get("pos-coin") : ""), kind: String(local.get("pos-kind", "")),
    tab: ["pos", "stop", "trd"].includes(local.get("pos-tab")) ? local.get("pos-tab") : "pos", sort: local.get("pos-sort", "pnl"),
    tPer: local.get("pos-tper", "all"), tSide: "all", tRes: "all", open: new Set(), first: true,
    pos: null, live: null, trades: null, tradesErr: null,
  };
  if (qCoin) local.set("pos-coin", qCoin);
  const priceOf = (c) => { const r = st.live && (st.live.coins || []).find((x) => x.coin === c); return r && r.ok ? Number(r.price) : null; };
  const nowOf = (g) => priceOf(g.coin) ?? (finite(g.last) ? Number(g.last) : null);
  /** The line a row speaks for: the lowest leverage the entry holds (20배 when it is there). */
  const lead = (g) => g.rows.slice().sort((a, b) => Number(a.L) - Number(b.L))[0];
  const uOf = (p) => K.liveUnreal(p, priceOf(p.coin));
  const roeOf = (p) => { const u = uOf(p); return u != null && Number(p.margin) ? u / Number(p.margin) : null; };

  // ---------------------------------------------------------------- the summary
  const sumNum = K4.liveNum(null, {format: (v) => fmt.money(v, true), tone: true});
  const sumSub = h("span", {class: "s"});
  const lsEl = h("b", null, "—"), lsSub = h("span", {class: "s"});
  const line = h("p", {class: "positions-line"});
  const bestLine = h("div", {class: "positions-bw"});
  const skewLine = h("p", {class: "pos-note positions-skew-note"});
  const sumCard = h("section", {class: "card positions-sum", "aria-label": "열린 포지션 요약"},
    h("div", {class: "stats"}, K4.stat("미실현 손익 합계 (모든 줄)", sumNum, sumSub), K4.stat("롱 · 숏 (계좌 진입)", lsEl, lsSub)),
    line, skewLine, ui.disclosure("가장 많이 버는·잃는 포지션", bestLine));

  // ---------------------------------------------------------------- filters: coin segment, kind chips
  const coinBar = h("div", {class: "positions-coins-bar"});
  const kindBar = h("div", {class: "row wrap pos-kinds", role: "group", "aria-label": "계좌 종류"});

  // ---------------------------------------------------------------- tabs
  const tabBar = h("div", {class: "positions-tabs"});
  const tabBody = h("div", {class: "stack"});
  const sortSel = h("select", {class: "select", "aria-label": "정렬"}, SORTS.map(([v, t]) => h("option", {value: v}, t)));
  sortSel.value = SORTS.some((x) => x[0] === st.sort) ? st.sort : "pnl";
  sortSel.addEventListener("change", () => { st.sort = sortSel.value; local.set("pos-sort", st.sort); paint(false); });
  const posPager = ui.pager({size: 10, render: (part) => part.map(cardOf), empty: "조건에 맞는 열린 포지션이 없습니다"});
  const posPane = h("div", {class: "stack"}, h("div", {class: "row wrap positions-filters"}, sortSel,
    h("span", {class: "muted pos-hint"}, "한 줄을 누르면 펼쳐집니다 · 숫자는 가장 낮은 배수 줄 (보통 20배)")), posPager.el);
  const stopPager = ui.pager({size: 12, render: (part) => h("div", {class: "dl-list", role: "list"}, part.map(stopRow)), empty: "걸려 있는 손절이 없습니다"});
  const stopPane = h("div", {class: "stack"}, stopPager.el,
    h("p", {class: "pos-note"}, "지금 가격과 가까운 손절이 위. 발동 시 손익은 그 진입의 가장 낮은 배수 줄, 나갈 때 수수료 전입니다. 모의 주문이라 거래소에는 아무것도 걸려 있지 않습니다."));
  const perSeg = ui.seg([{id: "today", label: "오늘"}, {id: "all", label: "최근 300줄"}], st.tPer, (v) => { st.tPer = v; local.set("pos-tper", v); paintTrades(); }, {label: "기간"});
  const sideSeg = ui.seg([{id: "all", label: "전체"}, {id: "long", label: "롱"}, {id: "short", label: "숏"}], st.tSide, (v) => { st.tSide = v; paintTrades(); }, {label: "방향"});
  const resSeg = ui.seg([{id: "all", label: "전부"}, {id: "win", label: "수익"}, {id: "loss", label: "손실"}, {id: "liq", label: "강제청산"}], st.tRes,
    (v) => { st.tRes = v; paintTrades(); }, {label: "결과"});
  const tSum = h("div"), tNote = h("p", {class: "pos-note"});
  const tPager = ui.pager({size: 12, render: (part) => h("div", {class: "dl-list", role: "list"}, part.map(tradeRow)), empty: "조건에 맞는 체결이 없습니다"});
  const trPane = h("div", {class: "stack"}, h("div", {class: "row wrap positions-filters"}, perSeg, sideSeg, resSeg), tSum, tPager.el, tNote);

  // ---------------------------------------------------------------- the side: 손절 사다리
  const ladList = h("div", {class: "risk-list", role: "list", "aria-label": "손절까지 가까운 순"});
  const ladMore = h("p", {class: "pos-note"});
  const ladder = ui.card({plate: "손절 사다리", sub: "손절선까지 남은 거리 · 가까운 순"},
    h("div", {class: "risk-key"}, h("span", null, h("i", {class: "stop"}), "손절까지"), h("span", null, h("i", {class: "lock"}), "수익 쪽 손절까지 (닿으면 수익으로 끝남)"),
      h("span", {class: "muted"}, "막대가 찰수록 가까움 · 0.5% 안이면 붉게")), ladList, ladMore);
  const liveLine = h("p", {class: "pos-note"});

  el.append(ui.screenHead("포지션", "지금 열려 있는 데모 포지션 (계좌 진입마다 한 줄)"), sumCard, coinBar, kindBar,
    h("div", {class: "positions-cols"}, h("div", {class: "stack"}, tabBar, tabBody), h("div", {class: "stack positions-side"}, ladder)),
    liveLine,
    h("p", {class: "assume once"}, "모의 · 실제 시세 · 평가 손익 = 마지막 15분봉 종가로 잰 엔진의 값(들어갈 때 수수료 포함)에 그 뒤 실시간 가격 움직임을 더한 것 · 나갈 때 수수료와 펀딩 전 · 주문 버튼 없음"));

  // ================================================================ data
  const entries = () => (st.pos && !isMissing(st.pos) ? K.groupEntries(st.pos.positions || []) : []);
  const kindOf = (g) => g.kind || kindOfId(g.id);
  const inScope = (g) => (!st.coin || g.coin === st.coin) && (!st.kind || kindOf(g) === st.kind);
  const stopGap = (g) => {           // signed distance from now to the stop as a share of now (positive = still away)
    const m = nowOf(g), s = Number(g.stop);
    if (!finite(m) || !finite(g.stop) || !m) return null;
    return g.side > 0 ? (m - s) / m : (s - m) / m;
  };
  const isLock = (g) => finite(g.stop) && finite(g.entry) && g.side * (Number(g.stop) - Number(g.entry)) > 0;
  const sorted = (list) => {
    const u = (g) => uOf(lead(g)) ?? 0;
    const by = {pnl: (a, b) => u(b) - u(a), loss: (a, b) => u(a) - u(b), new: (a, b) => b.entry_ms - a.entry_ms,
      stop: (a, b) => (stopGap(a) ?? 9) - (stopGap(b) ?? 9)};
    return list.slice().sort(by[st.sort] || by.pnl);
  };

  // ================================================================ one entry: the row and its card
  const cards = new Map();           // entry key -> {key, el, update}
  const keyOf = (g) => `${g.id}|${g.coin}|${g.entry_ms}|${g.side}`;
  function cardOf(g) {
    const k = keyOf(g), sig = `${k}|${g.Ls.join(",")}|${g.stop}|${g.target}`;
    let c = cards.get(k);
    if (!c || c.sig !== sig) { c = buildCard(g, st.open.has(k)); c.sig = sig; cards.set(k, c); }
    c.update(g);
    return c.el;
  }
  function buildCard(g, open) {
    const a = acctOf(g);
    const k = keyOf(g);
    const rowPnl = h("b", {class: "num"}, "—"), rowRoe = h("small", {class: "num"}, "—");
    const pnlEl = h("b", {class: "led-num num"}, "—"), roeEl = h("b", {class: "led-sm num"}, "—");
    const nowEl = h("span", {class: "num"}, "—");
    const dStop = h("b", {class: "num"}, "—"), dTgt = h("b", {class: "num"}, "—"), rNow = h("b", {class: "num"}, "—");
    const tgt = finite(g.target) ? Number(g.target) : targetR(g.exit_ko) != null && finite(g.stop)
      ? Number(g.entry) + g.side * targetR(g.exit_ko) * Math.abs(Number(g.entry) - Number(g.stop)) : null;
    const far = tgt != null ? tgt : Number(g.entry) + g.side * 2 * Math.abs(Number(g.entry) - Number(g.stop));   // no target: 2R for scale
    const meter = h("div", {class: "pos-meter"},
      h("div", {class: "pos-m-k"}, h("span", null, h("i", {class: "pos-m-key stop", "aria-hidden": "true"}), "손절까지 ", dStop),
        h("span", null, "지금 ", rNow),
        h("span", null, tgt != null ? "목표까지 " : "2R 자리까지 ", dTgt, h("i", {class: "pos-m-key tgt", "aria-hidden": "true"}))),
      h("div", {class: "pos-m-track", "aria-hidden": "true"}, h("i", {class: "pos-m-danger"}), h("i", {class: "pos-m-tick stop"}),
        h("i", {class: "pos-m-tick entry"}), h("i", {class: "pos-m-tick now"}), h("i", {class: ["pos-m-tick", "tgt", tgt == null ? "ghost" : ""]})),
      h("div", {class: "pos-m-k pos-m-ends"}, h("span", null, `손절 ${K.px(g.stop)}`), h("span", null, `진입 ${K.px(g.entry)}`),
        h("span", null, `${tgt != null ? "목표" : "2R"} ${K.px(far)}`)));
    const levRows = h("tbody");
    const levTbl = h("div", {class: "tbl-wrap"}, h("table", {class: "tbl pos-levs"},
      h("thead", null, h("tr", null, ["배수", "증거금", "평가 손익", "증거금 대비", "R"].map((x, i) => h("th", {class: i ? "" : "l", scope: "col"}, x)))), levRows));
    const held = h("span");
    const body = h("div", {class: "pos-body", hidden: !open},
      h("div", {class: "pnl pos-led"}, h("div", null, h("span", {class: "k"}, `미실현 손익 · ${fmt.lev(lead(g).L)} 줄`), pnlEl),
        h("div", {class: "r"}, h("span", {class: "k"}, "증거금 대비"), roeEl)),
      ui.kv([["진입가", K.px(g.entry)], ["지금 가격", nowEl], ["손절가", h("span", {class: "warn-t num"}, K.px(g.stop))],
        ["목표가", tgt != null ? h("span", {class: "num accent"}, K.px(tgt)) : h("span", {class: "muted"}, "없음 (사다리 · 고정 익절 없음)")],
        ["진입", fmt.kst(g.entry_ms)], ["보유", held]]),
      meter,
      h("p", {class: "pos-plain"}, h("b", null, "설정 "), h("span", {class: "mono"}, g.setting_ko || "—"), " · ", h("b", null, "청산 "), g.exit_ko || "—"),
      g.rows.length > 1 ? [h("p", {class: "pos-sub"}, `같은 진입을 나눠 가진 배수 ${fmt.int(g.rows.length)}줄 (줄마다 지갑 $1,000 따로)`), levTbl] : null,
      h("div", {class: "pos-acts"},
        h("a", {class: "btn-line", href: K.tradeHref(ctx, lead(g), "positions")}, "거래 차트"),
        h("a", {class: "btn-line", href: ctx.href("terminal", g.coin)}, "터미널에서"),
        h("a", {class: "btn-line", href: ctx.href("account", g.id)}, "계좌")));
    const btn = h("button", {class: "pos-row", type: "button", "aria-expanded": String(!!open), title: `${g.name || g.id} · ${g.id}`},
      K.sideTag(g.side),
      h("span", {class: "pos-row-t"}, h("b", null, `${fmt.coin(g.coin)} · ${K.levText(g.Ls)}`),
        h("small", {class: "pos-row-a"}, K4.acctFig(a, 16), K4.acctName(a))),
      h("span", {class: "pos-row-n"}, rowPnl, rowRoe), h("span", {class: "pos-chev", "aria-hidden": "true"}, "▾"));
    const elc = h("article", {class: ["card", "pos-card", "pos-fold", open ? "open" : ""], dataset: {kind: a.kind},
      "aria-label": `${fmt.coin(g.coin)} ${sideKo(g.side)} · ${g.name || g.id}`}, btn, body);
    btn.addEventListener("click", () => {
      const o = btn.getAttribute("aria-expanded") !== "true";
      btn.setAttribute("aria-expanded", String(o));
      elc.classList.toggle("open", o);
      body.hidden = !o;
      if (o) { st.open.add(k); K4.swap(body); } else st.open.delete(k);
    });
    const update = (gg) => {
      const p = lead(gg), u = uOf(p), r = roeOf(p);
      K4.countTo(rowPnl, u, {format: (v) => fmt.money(v, true), tone: true});
      K4.countTo(rowRoe, r, {format: (v) => pctS(v), tone: true});
      K4.countTo(pnlEl, u, {format: (v) => fmt.money(v, true), tone: true});
      K4.countTo(roeEl, r, {format: (v) => pctS(v), tone: true});
      const m = nowOf(gg);
      K4.tickPrice(nowEl, m, K.px(m), gg.coin);
      held.textContent = fmt.dur((Date.now() - Number(gg.entry_ms)) / 1000);
      const ds = stopGap(gg);
      dStop.textContent = ds == null ? "—" : ds <= 0 ? "닿음" : fmt.ratio(ds, 2);
      dStop.className = "num " + (isLock(gg) ? "up" : ds != null && ds < NEAR ? "down" : "");
      const dt = m && far ? gg.side * (far - m) / m : null;
      dTgt.textContent = dt == null ? "—" : dt <= 0 ? "넘음" : fmt.ratio(dt, 2);
      const risk = Math.abs(Number(gg.entry) - Number(gg.stop));
      const rn = m && risk ? gg.side * (m - Number(gg.entry)) / risk : null;
      rNow.textContent = rn == null ? "—" : fmt.r(rn);
      rNow.className = "num " + fmt.tone(rn, fmt.r(rn));
      // the meter spans stop (0 %) .. target or 2R (100 %): the entry and the price now sit on it
      const span = far - Number(gg.stop);
      const at = (x) => (span ? Math.max(0, Math.min(1, (x - Number(gg.stop)) / span)) : 0.5);
      meter.style.setProperty("--entry", `${(at(Number(gg.entry)) * 100).toFixed(1)}%`);
      meter.style.setProperty("--now", `${(at(m ?? Number(gg.entry)) * 100).toFixed(1)}%`);
      put(levRows, gg.rows.slice().sort((x, y) => Number(x.L) - Number(y.L)).map((q) => {
        const uq = uOf(q), rq = roeOf(q), ut = fmt.money(uq, true);
        return h("tr", null, h("td", {class: "l"}, h("span", {class: "dl-levtag", dataset: {lev: q.L}}, fmt.lev(q.L))), h("td", null, fmt.money(q.margin)),
          h("td", null, h("b", {class: ["num", fmt.tone(uq, ut)]}, ut)), h("td", null, h("span", {class: ["num", fmt.tone(rq, pctS(rq))]}, pctS(rq))),
          h("td", null, fmt.r(q.R)));
      }));
    };
    return {el: elc, update};
  }

  // ================================================================ 손절·목표 rows, the ladder, closed trades
  function stopRow(g) {
    const p = lead(g), ds = stopGap(g);
    const atStop = finite(g.stop) && finite(g.entry) ? g.side * (Number(g.stop) - Number(g.entry)) / Number(g.entry) * Number(p.notional || 0) : null;
    const tgt = finite(g.target) ? Number(g.target) : null;
    return h("a", {class: "lrow click pos-srow", role: "listitem", href: K.tradeHref(ctx, p, "positions"), title: g.id},
      K.sideTag(g.side), h("span", {class: "lname"}, K4.acctName(acctOf(g))),
      h("span", {class: "ret num"}, K.px(g.stop)),
      h("span", {class: "meta"}, h("span", null, `${fmt.coin(g.coin)} · ${K.levText(g.Ls)}`), h("span", null, isLock(g) ? "수익 쪽 손절" : "손절"),
        h("span", {class: ds != null && ds < NEAR ? "down" : ""}, `지금과 ${ds == null ? "—" : ds <= 0 ? "닿음" : fmt.ratio(ds, 2)}`),
        atStop != null ? h("span", {class: fmt.tone(atStop, fmt.money(atStop, true))}, `발동 시 ${fmt.money(atStop, true)} (${fmt.lev(p.L)})`) : null,
        tgt != null ? h("span", null, `목표 ${K.px(tgt)}`) : null));
  }
  const ladRows = new Map();
  function paintLadder(list) {
    const ranked = list.map((g) => ({g, d: stopGap(g)})).sort((a, b) => (a.d ?? 9) - (b.d ?? 9));
    const shown = ranked.slice(0, 12);
    put(ladList, shown.length ? shown.map(({g, d}) => {
      const k = keyOf(g), lock = isLock(g);
      const fill = h("i", {class: lock ? "lock" : "stop", style: {width: `${((d == null ? 0 : Math.max(0, Math.min(1, 1 - d / STOP_CAP))) * 100).toFixed(1)}%`}});
      const near = d != null && d < NEAR && !lock;
      const was = ladRows.get(k);
      ladRows.set(k, near);
      const row = h("a", {class: ["risk-row", near ? "near" : "", near && was === false ? "turned" : ""], role: "listitem", href: K.tradeHref(ctx, lead(g), "positions"), title: g.id},
        h("span", {class: "risk-h"}, K.sideTag(g.side), h("b", null, fmt.coin(g.coin)), h("span", {class: "muted"}, K.levText(g.Ls)),
          h("span", {class: "risk-n"}, K4.acctName(acctOf(g)))),
        h("span", {class: ["risk-b", lock ? "lock" : ""]}, h("span", {class: "risk-bar"}, fill),
          h("span", {class: "risk-t"}, lock ? "수익 쪽 손절까지 " : "손절까지 ", h("b", {class: "num"}, d == null ? "—" : d <= 0 ? "닿음" : fmt.ratio(d, 2)))));
      return row;
    }) : ui.empty(st.pos ? "열린 포지션이 없습니다" : "불러오는 중"));
    ladMore.textContent = (ranked.length > 12 ? `가까운 12개만 · 전체 ${fmt.int(ranked.length)}개 · ` : "") + "거리 = 지금 가격에서 손절 가격까지 (%). 누르면 거래 차트.";
  }
  /** Closed trade rows (one per leverage line) -> one per account entry, newest first. */
  function tradeEntries() {
    const rows = st.trades && !isMissing(st.trades) ? (st.trades.trades || []).filter((t) => t.status === "closed") : [];
    const by = new Map();
    for (const t of rows) {
      const k = `${t.account}|${String(t.key || "").split("|").slice(0, -1).join("|")}`;
      let e = by.get(k);
      if (!e) { e = {k, rows: [], account: t.account, name: t.name, coin: t.coin, side: Number(t.side), entry_ms: t.entry_ms, exit_ms: t.exit_ms}; by.set(k, e); }
      e.rows.push(t);
      e.exit_ms = Math.max(Number(e.exit_ms) || 0, Number(t.exit_ms) || 0);
    }
    for (const e of by.values()) {
      e.rows.sort((a, b) => Number(a.L) - Number(b.L));
      e.lead = e.rows[0];
      e.sum = e.rows.reduce((s, t) => s + (Number(t.pnl) || 0), 0);
      e.liq = e.rows.some((t) => t.reason === "liq");
    }
    return [...by.values()].sort((a, b) => b.exit_ms - a.exit_ms);
  }
  function tradeRow(e) {
    const t = e.lead, a = {id: e.account, kind: kindOfId(e.account), tf: String(t.key || "").split("|")[1], name: e.name, short: shortOf(e.account)};
    const today = Number(e.exit_ms) >= kstMidnight();
    const pv = fmt.money(t.pnl, true);
    return h("a", {class: "lrow click pos-trow", role: "listitem", href: ctx.href("trade", e.account, {from: "positions"}, t.key), title: e.account},
      h("span", {class: "rk"}, today ? fmt.hm(e.exit_ms) : fmt.kst(e.exit_ms)),
      h("span", {class: "lname"}, K4.acctFig(a, 16), K4.acctName(a)),
      h("span", {class: ["ret", "num", fmt.tone(t.pnl, pv)]}, pv),
      h("span", {class: "meta"}, h("span", null, fmt.coin(e.coin)), K.sideTag(e.side), h("span", null, fmt.lev(t.L)),
        h("span", {class: t.reason === "liq" ? "down" : ""}, reasonKo(t.reason)), h("span", {class: fmt.tone(t.roe, pctS(t.roe))}, `증거금 대비 ${pctS(t.roe)}`),
        h("span", null, `R ${fmt.r(t.R)}`),
        e.rows.length > 1 ? h("span", {class: "muted"}, `${fmt.int(e.rows.length)}줄 합 ${fmt.money(e.sum, true)}`) : null,
        e.liq && t.reason !== "liq" ? ui.pill("높은 배수 줄 강제청산", "bad") : null));
  }
  function paintTrades() {
    if (st.tradesErr && !st.trades) { put(tSum, ui.errorBox(st.tradesErr, loadTrades)); tPager.set([]); return; }
    if (!st.trades) { put(tSum, ui.empty("불러오는 중")); return; }
    if (isMissing(st.trades)) { put(tSum, ui.missing("거래 기록")); tPager.set([]); return; }
    let rows = tradeEntries();
    if (st.tPer === "today") rows = rows.filter((e) => Number(e.exit_ms) >= kstMidnight());
    if (st.coin) rows = rows.filter((e) => e.coin === st.coin);
    if (st.kind) rows = rows.filter((e) => kindOfId(e.account) === st.kind);
    if (st.tSide !== "all") rows = rows.filter((e) => (st.tSide === "long") === (e.side > 0));
    if (st.tRes === "win") rows = rows.filter((e) => Number(e.lead.pnl) > 0);
    else if (st.tRes === "loss") rows = rows.filter((e) => Number(e.lead.pnl) < 0);
    else if (st.tRes === "liq") rows = rows.filter((e) => e.liq);
    const tot = rows.reduce((s, e) => s + (Number(e.lead.pnl) || 0), 0), wins = rows.filter((e) => Number(e.lead.pnl) > 0).length;
    const tv = fmt.money(tot, true);
    put(tSum, h("p", {class: "pos-sum"}, `${fmt.int(rows.length)}건 · 가장 낮은 배수 줄 합계 `, h("b", {class: fmt.tone(tot, tv)}, tv), ` · 이긴 거래 ${fmt.int(wins)}`,
      rows.some((e) => e.liq) ? h("span", {class: "down"}, ` · 강제청산이 있었던 진입 ${fmt.int(rows.filter((e) => e.liq).length)}`) : null));
    tNote.textContent = "trades.json은 모든 계좌의 최근 300줄만 담습니다 (배수 줄마다 한 줄). 더 오래된 것은 거래 기록 화면과 계좌별 CSV에 있습니다. 한 줄을 누르면 그 거래의 차트. "
      + "숫자는 가장 낮은 배수 줄 · 수수료·펀딩 뒤.";
    tPager.set(rows, false);
  }
  async function loadTrades() {
    try { st.trades = await ctx.api("/api/trades"); st.tradesErr = null; } catch (e) { if (e && e.name === "AbortError") return; st.tradesErr = e; }
    if (ctx.alive() && st.tab === "trd") paintTrades();
  }

  // ================================================================ painting
  let tabSeg = null, tabKey = "";
  function paintTabs(n) {
    const opts = [{id: "pos", label: st.pos ? `포지션 ${fmt.int(n)}` : "포지션"}, {id: "stop", label: "손절·목표"}, {id: "trd", label: "체결 기록"}];
    const key = opts.map((o) => o.label).join("|");
    if (key === tabKey) return;
    tabKey = key;
    tabSeg = ui.seg(opts, st.tab, (v) => { st.tab = v; local.set("pos-tab", v); showTab(true); }, {label: "포지션 보기"});
    put(tabBar, tabSeg);
  }
  function showTab(animate) {
    const pane = st.tab === "stop" ? stopPane : st.tab === "trd" ? trPane : posPane;
    if (tabBody.firstChild !== pane) put(tabBody, pane);
    if (animate) K4.swap(tabBody);
    if (st.tab === "trd") { if (!st.trades) loadTrades(); paintTrades(); }
  }
  function paintCoins(all) {
    const mine = all.filter((g) => !st.kind || kindOf(g) === st.kind);
    const sides = {};
    for (const g of mine) { const c = sides[g.coin] || (sides[g.coin] = {long: 0, short: 0}); if (g.side > 0) c.long++; else c.short++; }
    const skewOf = (c) => { const n = c ? c.long + c.short : 0; return n < SKEW_MIN ? null : c.long / n >= SKEW_SHARE ? "long" : c.short / n >= SKEW_SHARE ? "short" : null; };
    const lab = (c) => {
      const s = sides[c] || {long: 0, short: 0}, sk = skewOf(s);
      return [fmt.coin(c), h("small", {class: "pos-cnt pos-ls", title: `롱 ${fmt.int(s.long)} · 숏 ${fmt.int(s.short)}`},
        h("span", {class: s.long ? "up" : ""}, `${fmt.int(s.long)}↑`), " ", h("span", {class: s.short ? "down" : ""}, `${fmt.int(s.short)}↓`)),
      sk ? h("i", {class: "pos-skew", role: "img", "aria-label": `한 방향 몰림: ${sk === "long" ? "롱" : "숏"} 80% 이상`}) : null];
    };
    put(coinBar, ui.seg([{id: "", label: ["전체", h("small", {class: "pos-cnt"}, fmt.int(mine.length))]}, ...COINS.map((c) => ({id: c, label: lab(c)}))], st.coin,
      (v) => { st.coin = v; local.set("pos-coin", v); paint(false); }, {label: "코인 고르기", cls: "scroll"}),
    h("p", {class: "pos-note positions-skew-note"}, "↑ 롱 · ↓ 숏 = 계좌 진입 수 (배수 줄을 하나로 셈)",
      COINS.some((c) => skewOf(sides[c])) ? [" · ", h("i", {class: "pos-skew", "aria-hidden": "true"}), ` 한 방향 몰림 (${SKEW_MIN}개 이상 중 한쪽 ${SKEW_SHARE * 100}% 이상)`] : null));
    const kinds = KINDS.filter((k) => all.some((g) => kindOf(g) === k.id));
    put(kindBar, h("span", {class: "k4-k"}, "계좌 종류"), [{id: "", ko: "모두"}, ...kinds].map((k) => h("button", {type: "button", class: "k4-chip",
      "aria-pressed": String(st.kind === k.id), dataset: k.id ? {kind: k.id} : null, onclick: () => { st.kind = st.kind === k.id ? "" : k.id; local.set("pos-kind", st.kind); paint(false); }},
    k.ko, h("small", {class: "pos-cnt"}, fmt.int(k.id ? all.filter((g) => kindOf(g) === k.id && (!st.coin || g.coin === st.coin)).length : all.filter((g) => !st.coin || g.coin === st.coin).length)))));
  }
  function paintSum(list) {
    const lines = list.flatMap((g) => g.rows);
    let tot = 0, known = 0, up = 0, dn = 0, best = null, worst = null;
    const margin = lines.reduce((s, p) => s + (Number(p.margin) || 0), 0);
    for (const p of lines) { const u = uOf(p); if (u == null) continue; known++; tot += u; }
    for (const g of list) {
      const u = uOf(lead(g));
      if (u == null) continue;
      if (u > 0) up++; else if (u < 0) dn++;
      if (!best || u > best.u) best = {g, u};
      if (!worst || u < worst.u) worst = {g, u};
    }
    sumNum.update(known ? tot : null);
    sumSub.textContent = known && margin ? `묶인 증거금 대비 ${pctS(tot / margin)}` : "";
    sumSub.className = "s " + fmt.tone(tot, pctS(tot / (margin || 1)));
    const longs = list.filter((g) => g.side > 0).length;
    lsEl.textContent = `${fmt.int(longs)} · ${fmt.int(list.length - longs)}`;
    const scope = [st.coin ? fmt.coin(st.coin) : "", st.kind ? KIND_KO[st.kind] : ""].filter(Boolean).join(" · ");
    lsSub.textContent = `열린 진입 ${fmt.int(list.length)}개 · 줄 ${fmt.int(lines.length)}개${scope ? " · " + scope : ""}`;
    const share = list.length ? Math.max(longs, list.length - longs) / list.length : 0;
    put(skewLine, list.length >= SKEW_MIN && share >= SKEW_SHARE
      ? [h("i", {class: "pos-skew", "aria-hidden": "true"}), ` 한 방향 몰림: ${longs > list.length - longs ? "롱" : "숏"}이 ${fmt.int(Math.round(share * 100))}% (계좌 진입 ${fmt.int(list.length)}개 중). 시장이 반대로 가면 한꺼번에 잃습니다.`]
      : null);
    skewLine.hidden = !skewLine.firstChild;
    put(line, "수익 중 ", h("b", {class: "up"}, fmt.int(up)), " · 손실 중 ", h("b", {class: "down"}, fmt.int(dn)), " · 묶인 증거금 ",
      h("b", {class: "num"}, fmt.money(margin)), h("span", {class: "muted"}, " (진입마다 가장 낮은 배수 줄로 셈)"));
    const bw = (lab, b) => (b ? h("a", {class: "positions-bwl", href: K.tradeHref(ctx, lead(b.g), "positions")}, h("span", {class: "muted"}, lab),
      h("b", {class: "positions-bwn"}, K4.acctName(acctOf(b.g))), h("span", {class: "muted"}, `${fmt.coin(b.g.coin)} ${sideKo(b.g.side)} ${fmt.lev(lead(b.g).L)}`),
      h("b", {class: ["num", fmt.tone(b.u)]}, fmt.money(b.u, true))) : null);
    put(bestLine, bw("가장 많이 버는 중", best && best.u > 0 ? best : null), bw("가장 많이 잃는 중", worst && worst.u < 0 ? worst : null));
  }
  function paint(keepPage) {
    if (!st.pos) return;
    if (isMissing(st.pos)) {
      put(coinBar, ui.missing("포지션 자료")); put(kindBar); sumNum.update(null); posPager.set([]); stopPager.set([]); paintLadder([]);
      paintTabs(0);
      return;
    }
    const all = entries();
    const list = all.filter(inScope);
    paintCoins(all);
    paintSum(list);
    paintTabs(list.length);
    const ordered = sorted(list);
    if (st.first && ordered.length) { st.first = false; st.open.add(keyOf(ordered[0])); }   // the top card starts open, once
    posPager.set(ordered, keepPage);
    stopPager.set(list.slice().sort((a, b) => (stopGap(a) ?? 9) - (stopGap(b) ?? 9)), keepPage);
    paintLadder(list);
    for (const k of [...cards.keys()]) if (!all.some((g) => keyOf(g) === k)) cards.delete(k);
    if (st.tab === "trd") paintTrades();
  }
  /** a new live price: the open cards and rows count to it; the lists are not rebuilt */
  function tick() {
    if (!st.pos || isMissing(st.pos)) return;
    const all = entries().filter(inScope);
    for (const g of all) { const c = cards.get(keyOf(g)); if (c && c.el.isConnected) c.update(g); }
    paintSum(all);
    paintLadder(all);
  }

  async function loadPos() {
    let d;
    try { d = await ctx.api("/api/positions"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!st.pos) put(coinBar, ui.errorBox(e, loadPos));
      return;
    }
    const same = st.pos && d && st.pos.generated_ms === d.generated_ms;
    st.pos = d;
    if (!same) paint(true);
  }
  async function loadLive() {
    try { st.live = await ctx.api("/api/live"); } catch (e) { if (e && e.name === "AbortError") return; }
    liveLine.textContent = `가격: ${K.liveNote(st.live)} · 10초마다`;
    tick();
  }
  paintTabs(0);
  showTab(false);
  await Promise.all([loadPos(), loadLive()]);
  paint(true);
  ctx.every(15000, loadPos);
  ctx.every(10000, loadLive);
}

/** Today's 00:00 in Korea time (ms). */
function kstMidnight(ms = Date.now()) {
  return Math.floor((ms + 9 * 3.6e6) / 86400000) * 86400000 - 9 * 3.6e6;
}
