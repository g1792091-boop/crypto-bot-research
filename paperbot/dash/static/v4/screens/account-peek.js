// The side panel's content (core/drawer.js; owners 10/06: details without leaving the page). Three kinds:
//   account  — #/account/<id>: the profile card (return, curve, drawdown, win rate; grid-kit.js) or the counts, a
//              small candle chart of one coin with this account's entries and exits, the open position card
//              (positions-kit.js), the last closed trades (each opens its trade here), the strategy's own link.
//   strategy — #/strategies/<name>: its timeframe accounts (each opens here), the profile card, the chart of one of
//              them, the open positions, the last trades of all of them, the rule in short.
//   trade    — #/replay/<trade id>: what happened (side, leverage, how it ended, prices, times), the bars around it with
//              the entry and the exit (GET /api/v4/replay/<id>), the account.
// '전체 화면으로' (the panel's head) opens the full page. Built from the account / strategy / replay pages' own pieces.
// HONESTY (CONTRACT §1): a DeepSeek or coin-flip account outside its own group's view is COUNTED ONLY (derive.countOnlyIn
// with spec.view): no wallet, return, P&L, ROE, margin, no green / red exit dots; the 참고 pill. Money carries ui.assume().
import {h, ui, fmt, derive, store, makeChart, candleOptions, tok, priceDec} from "../core/pb.js";
import {normPos, posCard, tradeRow, nameOf, groupKo, COUNT_ONLY_KO, COUNT_ONLY_WHY} from "./positions-kit.js";
import {chartWindow, markLabels} from "./account-pick.js";
import {profileCard} from "./grid-kit.js";
import {accountsOf, nameKo, groupOfStrategy} from "./strategies-calc.js";
import {ruleBody} from "./strategies-panels.js";
import {DS_DEFS, FAMILY, REEL} from "./strategies-defs.js";

const TF_S = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400};
const LAST_N = 6;
const GROUP_PLATE = {core: "기존 36", ds: "딥시크 44", m5: "5분봉"};
const parseData = (raw) => { if (raw && typeof raw === "object") return raw; try { const d = JSON.parse(raw || "{}"); return d && typeof d === "object" ? d : {}; } catch (e) { return {}; } };
const newestFirst = (rows) => [...(rows || [])].sort((x, y) => (y.exit_time || 0) - (x.exit_time || 0));
const sec = (ms) => Math.floor(Number(ms) / 1000);

export async function renderPeek(spec, ctx, panel) {
  if (spec.kind === "strategy") return strategyPeek(spec, ctx, panel);
  if (spec.kind === "trade") return tradePeek(spec, ctx, panel);
  return accountPeek(spec, ctx, panel);
}

// ---------------------------------------------------------------- shared pieces
/** The account row as the pages see it: /api/account's record merged with its board row. */
function merged(d, board) {
  const acc = d.account || {};
  const row = board && (board.accounts || []).find((x) => x.account_id === acc.account_id);
  return {...acc, ...(row || {}), ...(d.extra ? {label_ko: d.extra.label_ko} : {})};
}

/** A small candle chart of one coin with an account's entries (arrows) and exits (dots), the open position's lines.
 *  co: counted only (neutral exit dots, no ROE on them). Returns {el, draw(sym)}. */
function coinChart(ctx, a, d, co) {
  const trades = d.trades || [];
  const pos = normPos(d.state && d.state.position);
  const syms = [...new Set((pos ? [pos.symbol] : []).concat(newestFirst(trades).map((t) => t.symbol)))];
  const box = h("div", {class: "pk-chart", role: "img", "aria-label": "코인 차트: 이 계좌의 진입과 청산"});
  const sel = syms.length > 1 ? h("select", {class: "select", "aria-label": "코인"}, syms.map((s) => h("option", {value: s}, fmt.coin(s)))) : null;
  const tf = a.timeframe, step = TF_S[tf] || 900;
  let chart = null, gen = 0;
  ctx.track(() => { if (chart) chart.dispose(); });
  async function draw(sym) {
    const g = ++gen;
    if (chart) { chart.dispose(); chart = null; }
    box.replaceChildren();
    let data;
    try { data = await ctx.api(`/api/candles?symbol=${encodeURIComponent(sym)}&interval=${encodeURIComponent(tf)}&limit=300`); }
    catch (e) { if (!(e && e.name === "AbortError") && g === gen) box.replaceChildren(ui.errorBox(e, () => draw(sym))); return; }
    if (g !== gen || !ctx.alive() || !Array.isArray(data) || !data.length) { if (g === gen && ctx.alive()) box.replaceChildren(ui.empty("봉 자료가 없습니다")); return; }
    try {
      const c = await makeChart(box);
      if (g !== gen || !ctx.alive()) { c.dispose(); return; }
      chart = c;
      c.chart.applyOptions({handleScale: false});
      const s = c.chart.addCandlestickSeries(candleOptions());
      const dec = priceDec(data[data.length - 1].close);
      s.applyOptions({priceFormat: {type: "price", precision: dec, minMove: Math.pow(10, -dec)}});
      s.setData(data);
      const t0 = data[0].time;
      const mine = trades.filter((t) => t.symbol === sym && sec(t.entry_time) >= t0);
      const opHere = pos && pos.symbol === sym && pos.entry_time ? pos : null;
      const win = chartWindow(data, opHere ? mine.concat([{entry_time: opHere.entry_time}]) : mine, step);
      const lab = markLabels(mine.length, win);
      const marks = [];
      for (const t of mine) {
        const e = sec(t.entry_time), x = sec(t.exit_time);
        marks.push({time: e - (e % step), position: t.side > 0 ? "belowBar" : "aboveBar", color: tok("--accent"), shape: t.side > 0 ? "arrowUp" : "arrowDown", text: lab.entry(t)});
        marks.push({time: x - (x % step), position: t.side > 0 ? "aboveBar" : "belowBar", shape: "circle",
          color: co ? tok("--muted") : t.pnl > 0 ? tok("--up") : tok("--down"), text: co ? (lab.level === "full" ? fmt.reasonKo(t.exit_reason) : "") : lab.exit(t)});
      }
      if (opHere) {
        const e = sec(opHere.entry_time);
        marks.push({time: e - (e % step), position: opHere.side > 0 ? "belowBar" : "aboveBar", color: tok("--accent"),
          shape: opHere.side > 0 ? "arrowUp" : "arrowDown", text: lab.level === "bare" ? "보유" : `${lab.entry(opHere)} 보유 중`});
        s.createPriceLine({price: opHere.entry, color: tok("--accent"), lineWidth: 1, title: "진입"});
        if (opHere.stop) s.createPriceLine({price: opHere.stop, color: tok("--down"), lineWidth: 1, lineStyle: 2, title: opHere.lock_roe != null ? "잠금" : "손절"});
        if (opHere.liq) s.createPriceLine({price: opHere.liq, color: tok("--warn"), lineWidth: 1, lineStyle: 3, title: "청산가"});
      }
      marks.sort((x, y) => x.time - y.time);
      s.setMarkers(marks);
      if (win) c.chart.timeScale().setVisibleLogicalRange(win); else c.chart.timeScale().fitContent();
    } catch (e) { if (g === gen) box.replaceChildren(ui.errorBox(e)); }
  }
  const first = syms[0] || "BTCUSDT";
  if (sel) { sel.value = first; sel.addEventListener("change", () => draw(sel.value)); }
  const el = ui.card({plate: "진입·청산", sub: `${fmt.tfKo(tf)}봉`, acts: sel ? [sel] : null, cls: "pk-card"}, box,
    h("p", {class: "pos-note"}, co ? "화살표 = 진입, 회색 동그라미 = 청산 (개수만: 손익 색 없음)" : "화살표 = 진입, 동그라미 = 청산 (초록 수익, 빨강 손실)"));
  return {el, draw: () => draw(sel ? sel.value : first)};
}

/** The open position card (live mark), or one line saying there is none. */
function positionBlock(ctx, a, pos, o) {
  if (!pos) return ui.card({plate: "열린 포지션", cls: "pk-card"}, ui.empty("지금 열린 포지션이 없습니다"));
  const card = posCard(a, pos, {why: o.why, wallet: o.wallet, data: o.data, href: ctx.href, noAccountLink: !!o.noAccountLink, noName: !!o.noName,
    countOnly: o.co});
  card.update(store.mark(pos.symbol));
  ctx.watch("ticker", () => { if (card.isConnected) card.update(store.mark(pos.symbol)); });
  return card;
}

/** The last closed trades as rows; each row's 다시보기 opens that trade in this panel. */
function lastTrades(ctx, rows, acctOf, o = {}) {
  const list = newestFirst(rows).slice(0, LAST_N);
  const kids = list.length ? h("div", {role: "list", class: "pk-trades"}, list.map((t) => {
    const a = acctOf(t);
    return tradeRow(t, a, {noName: !!o.noName, countOnly: o.co || (o.isCo && o.isCo(a)), prices: true, replay: t.id != null ? ctx.href("replay", String(t.id)) : null});
  })) : ui.empty("아직 닫힌 거래가 없습니다");
  return ui.card({plate: "최근 거래", sub: `${fmt.int((rows || []).length)}건 중 최근 ${fmt.int(list.length)}건`, cls: "pk-card"}, kids,
    list.length && !o.co ? ui.assume("closed", "거래마다 나갈 때 수수료·펀딩 뒤") : null);
}

// ---------------------------------------------------------------- account
async function accountPeek(spec, ctx, {setHead, body}) {
  const [d, board] = await Promise.all([ctx.api(`/api/account/${encodeURIComponent(spec.id)}`), store.need("board", 120000).catch(() => null)]);
  if (!ctx.alive()) return;
  const acc = d.account || {}, stt = d.state || {}, data = parseData(acc.data);
  const a = merged(d, board);
  const co = derive.countOnlyIn(a, spec.view);
  const g = fmt.groupOf(a);
  const isExtra = g === "extra" || g === "other";
  const trades = d.trades || [];
  const n = trades.length;
  const init = (board && board.initial) || 5000;
  setHead({title: nameOf(a, data), sub: [acc.account_id, `${fmt.tfKo(acc.timeframe)}봉`, fmt.familyKo(a) ? `계열 ${fmt.familyKo(a)}` : null].filter(Boolean).join(" · "),
    pills: [ui.pill(groupKo(a), g === "core" ? "accent" : ""), stt.bust || a.bust ? ui.pill("파산", "bad") : null,
      co ? ui.pill("참고", "ref", COUNT_ONLY_WHY) : null, ui.smallSample(n)]});

  // the summary: the profile card (money accounts on the map; DeepSeek gets its counts there), else plain numbers
  let summary;
  if (co) {
    const pos0 = normPos(stt.position);
    summary = ui.card({plate: "요약", sub: COUNT_ONLY_KO, cls: "pk-card"},
      h("div", {class: "stats"}, ui.stat("닫힌 거래", `${fmt.int(n)}건`), ui.stat("지금", pos0 ? `${fmt.coin(pos0.symbol)} ${fmt.sideKo(pos0.side)}` : "대기")),
      h("p", {class: "pos-note"}, a.kind === "ds200" ? "딥시크 계좌는 계좌별 수익을 보지 않습니다: 묶음 중앙값으로만 봅니다 (딥시크 묶음 화면)."
        : a.kind === "random" ? "동전 봇은 비교 기준이라 섞인 목록에서는 개수만 봅니다 (동전 봇 묶음 화면에서 손익)." : COUNT_ONLY_WHY));
  } else if (isExtra) {
    const w = a.wallet == null ? stt.wallet ?? init : a.wallet;
    const wins = trades.filter((t) => t.pnl > 0).length;
    const mdd = stt.max_drawdown ?? a.max_drawdown;
    summary = ui.card({plate: "요약", cls: "pk-card"},
      h("div", {class: "stats"}, ui.stat("잔고 (USDT)", fmt.money(w)), ui.stat("수익률", h("b", {class: fmt.tone(w / init - 1)}, fmt.pct(w / init - 1, 2))),
        ui.stat("거래", `${fmt.int(n)}건`, n ? `승률 ${fmt.pct(wins / n, 0, false)}` : ""), ui.stat("최대 낙폭", mdd ? fmt.pct(-mdd, 1) : "—")),
      h("p", {class: "pos-note"}, "나중에 시작한 추가 계좌: 원래 계좌들과 따로 셉니다."), ui.assume());
  } else {
    const prof = profileCard(ctx, acc.account_id, {head: false, cls: "pk-prof"});
    prof.load();
    summary = prof.el;
  }
  const chart = coinChart(ctx, a, d, co);
  const pos = normPos(stt.position);
  const links = h("div", {class: "row wrap pk-links"},
    a.strategy && ["strategy", "ds200", "reel"].includes(a.kind) ? h("a", {class: "btn-line", href: ctx.href("strategies", a.strategy)}, "이 매매법 보기") : null,
    h("a", {class: "btn-line", href: ctx.href("account", acc.account_id), dataset: {full: "1"}}, `거래 ${fmt.int(n)}건 모두 · 전체 화면`));
  body.replaceChildren(summary, chart.el,
    positionBlock(ctx, a, pos, {why: d.position_why, wallet: stt.wallet ?? a.wallet, data, co, noAccountLink: true, noName: true}),
    lastTrades(ctx, trades, () => a, {co, noName: true}), links);
  chart.draw();
}

// ---------------------------------------------------------------- strategy
async function strategyPeek(spec, ctx, {setHead, body}) {
  const name = spec.id;
  const [board, list36] = await Promise.all([store.need("board", 120000).catch(() => null), ctx.api("/api/strategies").catch(() => [])]);
  if (!ctx.alive()) return;
  const rows = accountsOf(board, name);
  const kind = rows.length ? rows[0].kind : DS_DEFS[name] ? "ds200" : name === REEL.id ? "reel" : "strategy";
  const group = groupOfStrategy(name, kind);
  const isCo = (a) => derive.countOnlyIn(a, spec.view);
  const co = rows.length ? rows.some(isCo) : kind === "ds200" && spec.view !== "ds";
  const init = (board && board.initial) || 5000;
  const fam = kind === "ds200" && DS_DEFS[name] ? `${DS_DEFS[name].fam} ${FAMILY[DS_DEFS[name].fam].ko}` : null;
  setHead({title: nameKo(name, list36), sub: [name, rows.length ? `봉 ${fmt.int(rows.length)}개` : null].filter(Boolean).join(" · "),
    pills: [ui.pill(GROUP_PLATE[group] || "매매법", group === "core" ? "accent" : ""), fam ? ui.pill(fam, "thin") : null, co ? ui.pill("참고", "ref", COUNT_ONLY_WHY) : null]});

  // the timeframe accounts: each opens its account here
  const tfRow = (a) => {
    const w = a.wallet == null ? init : a.wallet, r = w / init - 1;
    const p = normPos(a.position);
    const val = isCo(a) ? `${fmt.int(a.trades || 0)}건` : fmt.pct(r, 1);
    return h("a", {class: "pk-tf", href: ctx.href("account", a.account_id), title: a.account_id},
      h("span", {class: "pk-tf-k"}, `${fmt.tfKo(a.timeframe)}봉`), h("b", {class: ["num", isCo(a) ? "" : fmt.tone(r, val)]}, val),
      a.bust ? h("span", {class: "down"}, "파산") : p ? h("span", null, `${fmt.coin(p.symbol)} `, ui.sideTag(p.side)) : h("span", {class: "muted"}, "대기"));
  };
  const tfs = ui.card({plate: "봉별 계좌", sub: co ? "닫힌 거래 수 (개수만)" : "지금 수익률", cls: "pk-card"},
    rows.length ? h("div", {class: "pk-tfs"}, rows.map(tfRow)) : ui.empty("아직 이 매매법의 계좌가 없습니다"),
    !co && rows.length ? ui.assume("closed", "수익률 = 지금 잔고 ÷ 시작 잔고") : null);
  // the profile card: DeepSeek strategies get their counts there (grid-kit's own rule)
  const prof = profileCard(ctx, name, {cls: "pk-prof"});
  prof.load();
  // the rule in short
  const meta = (Array.isArray(list36) ? list36 : []).find((s) => s.strategy === name) || null;
  const rule = kind === "strategy"
    ? (meta && (meta.style || meta.hold) ? h("p", {class: "ink2"}, [meta.style, meta.hold].filter(Boolean).join(" · ")) : h("p", {class: "muted"}, "조건 문장과 지표 차트는 전체 화면에 있습니다."))
    : h("div", {class: "stack tight"}, ruleBody(name, kind, meta, null));
  const ruleCard = ui.card({plate: "규칙", sub: "짧게", cls: "pk-card"}, rule);
  const chartSlot = h("div", {class: "stack tight"});
  const posSlot = h("div", {class: "stack tight"});
  const tradeSlot = h("div", {class: "stack tight"}, ui.card({plate: "최근 거래", cls: "pk-card"}, ui.empty("불러오는 중")));
  body.replaceChildren(tfs, prof.el, chartSlot, posSlot, tradeSlot, ruleCard,
    h("div", {class: "row wrap pk-links"}, h("a", {class: "btn-line", href: spec.full, dataset: {full: "1"}}, "지표 차트·신호 기록 · 전체 화면")));

  // open positions (live)
  const open = rows.filter((a) => normPos(a.position));
  if (open.length) posSlot.append(...open.slice(0, 4).map((a) => positionBlock(ctx, a, normPos(a.position), {wallet: a.wallet, co: isCo(a)})));
  // the accounts' own records: the chart of one of them (the one in a position, else 1h, else the first) and the trades
  if (!rows.length) return;
  const pick = rows.find((a) => a.position) || rows.find((a) => a.timeframe === "1h") || rows[0];
  const details = await Promise.all(rows.map((a) => ctx.api(`/api/account/${encodeURIComponent(a.account_id)}`).catch(() => null)));
  if (!ctx.alive()) return;
  const byId = new Map(rows.map((a) => [a.account_id, a]));
  const all = [];
  details.forEach((d) => { if (d) for (const t of d.trades || []) all.push(t); });
  tradeSlot.replaceChildren(lastTrades(ctx, all, (t) => byId.get(t.account_id), {isCo, co}));
  const dPick = details[rows.indexOf(pick)];
  if (dPick) {
    const chart = coinChart(ctx, {...pick, ...(dPick.account || {})}, dPick, isCo(pick));
    chart.el.querySelector(".card-h .sub").textContent = `${fmt.tfKo(pick.timeframe)}봉 계좌 · ${pick.position ? "포지션 보유 중" : "최근 거래"}`;
    chartSlot.append(chart.el);
    chart.draw();
  }
}

// ---------------------------------------------------------------- one closed trade
async function tradePeek(spec, ctx, {setHead, body}) {
  const [d, board] = await Promise.all([ctx.api(`/api/v4/replay/${encodeURIComponent(spec.id)}`), store.need("board", 120000).catch(() => null)]);
  if (!ctx.alive()) return;
  const t = d.trade || {};
  const row = board && (board.accounts || []).find((x) => x.account_id === t.account_id);
  const a = {...(d.account || {}), ...(row || {}), account_id: t.account_id};
  const co = derive.countOnlyIn(a, spec.view);
  const reason = fmt.reasonKo(t.exit_reason) + (t.exit_reason === "LOCK" && t.lock_roe ? ` +${fmt.num(t.lock_roe * 100, 0)}%` : "");
  setHead({kind: "거래", title: `${fmt.coin(t.symbol)}USDT ${fmt.sideKo(t.side)} · ${fmt.lev(t.leverage)}`,
    sub: `${fmt.acctName(a)} · ${fmt.kst(t.exit_time)} 청산`,
    pills: [ui.pill(reason, t.exit_reason === "LIQ" ? "bad" : ""), ui.pill(groupKo(a), fmt.groupOf(a) === "core" ? "accent" : ""), co ? ui.pill("참고", "ref", COUNT_ONLY_WHY) : null]});
  const hero = co
    ? ui.card({plate: "결과", sub: COUNT_ONLY_KO, cls: "pk-card"}, h("p", {class: "pos-note"}, `${reason}로 닫힘. `, COUNT_ONLY_WHY))
    : ui.card({plate: "결과", cls: "pk-card"},
      h("div", {class: "pnl pk-led"}, h("div", null, h("span", {class: "k"}, "손익 (USDT)"), h("b", {class: ["led-num", "num", fmt.tone(t.pnl)]}, fmt.money(t.pnl, true))),
        h("div", {class: "r"}, h("span", {class: "k"}, "ROE (증거금 대비)"), h("b", {class: ["led-sm", "num", fmt.tone(t.roe)]}, fmt.pct(t.roe, 1)))),
      ui.assume(null, "손익은 나갈 때 수수료·펀딩 뒤"));
  const box = h("div", {class: "pk-chart", role: "img", "aria-label": `${fmt.coin(t.symbol)} ${fmt.tfKo(d.tf)}봉: 이 거래의 진입과 청산`});
  const chartCard = ui.card({plate: "진입·청산", sub: `${fmt.tfKo(d.tf)}봉`, cls: "pk-card"}, box,
    h("p", {class: "pos-note"}, "화살표 = 진입, 동그라미 = 청산 · 봉 하나씩 다시 보려면 전체 화면"));
  const lv = d.levels || {};
  const facts = ui.card({plate: "거래 기록", cls: "pk-card"}, ui.kv([["진입", fmt.kst(t.entry_time)], ["청산", fmt.kst(t.exit_time)],
    ["보유", fmt.dur(t.hold_s)], ["진입가 → 청산가", `${fmt.price(t.entry_price)} → ${fmt.price(t.exit_price)}`],
    ["첫 손절", fmt.price(lv.stop_initial)], ["강제청산가", h("span", {class: "down"}, fmt.price(lv.liq))],
    co ? null : ["증거금", fmt.money(t.margin)], co ? null : ["수수료 · 펀딩", `${fmt.money(t.fees)} · ${fmt.money(t.funding)}`]]));
  body.replaceChildren(hero, chartCard, facts, h("div", {class: "row wrap pk-links"},
    h("a", {class: "btn-line", href: ctx.href("account", t.account_id)}, "이 계좌 보기"),
    h("a", {class: "btn-line", href: spec.full, dataset: {full: "1"}}, "▶ 봉 하나씩 다시보기 · 전체 화면")));
  const bars = d.bars || [];
  if (bars.length < 2) { box.replaceChildren(ui.empty("봉 자료가 없습니다")); return; }
  try {
    const c = await makeChart(box);
    if (!ctx.alive()) { c.dispose(); return; }
    ctx.track(c.dispose);
    c.chart.applyOptions({handleScale: false});
    const s = c.chart.addCandlestickSeries(candleOptions());
    const dec = priceDec(t.entry_price || bars[bars.length - 1][4]);
    s.applyOptions({priceFormat: {type: "price", precision: dec, minMove: Math.pow(10, -dec)}});
    s.setData(bars.map((b) => ({time: b[0], open: b[1], high: b[2], low: b[3], close: b[4]})));
    const ix = d.idx || {}, marks = [];
    if (ix.entry != null && bars[ix.entry]) marks.push({time: bars[ix.entry][0], position: t.side > 0 ? "belowBar" : "aboveBar", color: tok("--accent"),
      shape: t.side > 0 ? "arrowUp" : "arrowDown", text: `${fmt.sideKo(t.side)} ${fmt.lev(t.leverage)}`});
    if (ix.exit != null && bars[ix.exit]) marks.push({time: bars[ix.exit][0], position: t.side > 0 ? "aboveBar" : "belowBar", shape: "circle",
      color: co ? tok("--muted") : t.pnl > 0 ? tok("--up") : tok("--down"), text: co ? fmt.reasonKo(t.exit_reason) : `${fmt.reasonKo(t.exit_reason)} ${fmt.pct(t.roe, 0)}`});
    marks.sort((x, y) => x.time - y.time);
    s.setMarkers(marks);
    if (t.entry_price) s.createPriceLine({price: t.entry_price, color: tok("--accent"), lineWidth: 1, lineStyle: 2, title: "진입"});
    if (lv.stop_initial) s.createPriceLine({price: lv.stop_initial, color: tok("--down"), lineWidth: 1, lineStyle: 2, title: "첫 손절"});
    c.chart.timeScale().fitContent();
  } catch (e) { box.replaceChildren(ui.errorBox(e)); }
}
