// 실거래 › 거래 (#/livebots/trades?acct=): the closed trades of 페이퍼 / 바이비트 / MEXC (/api/v4/livebots/trades), 10 a page,
// with filters 코인 / 매매법 / 이김·짐, and one trade opened in place: the strategy, its timeframe, the setting it came from
// (its number in the combined bot's config and that setting's custom numbers, entry mode 즉시 / 돌파 확인, 반대 방향, the stop
// rule and the distance it really had), entry / exit in Korea time, why it closed (손절 / 잠금 익절 …), the highest lock, the
// net ROE, the money and the fees; for a live trade its paper partner (same coin and side, entry within 5 minutes): the
// entry slippage against the paper and the difference in money against the paper × the size ratio; for a paper trade
// what each executor did with it (따라감 / 안 따라감 with the executor's own reason). A losing trade with a loss card
// (livecheck.db; a live trade shows its paper partner's) opens with the card under it (livebots-cards.js); the filter
// 손실 카드만 and, over the trades shown, the count by the card's cause label.
// HONESTY: every number is a record's; a field the record does not have is '—' or left out; real money and paper money each
// carry their own caption; no buttons that change anything; cards not collected yet say 수집 전, never '없음'.
import {h, put, ui, fmt, local, motion} from "../core/pb.js";
import {acctKo, acctTag, sourceState} from "./livebots-kit.js";
import {cardBlock, cardSummary} from "./livebots-cards.js";

const IDS = ["paper", "bybit", "mexc"];
const REFRESH_MS = 30 * 1000;
const STATE_KO = {matched: "따라감", missed: "안 따라감", before: "시작 전", open: "닫는 중", unknown: "모름"};
const F0 = () => ({coin: "", strat: "", res: "all", card: false});

/** The trades in a filter: {coin, strat, res: "all" | "win" | "loss", card: only the ones with a loss card}. */
export function filterRows(rows, f) {
  return (rows || []).filter((r) => (!f.coin || r.symbol === f.coin) && (!f.strat || r.strategy_id === f.strat)
    && (f.res === "win" ? r.win : f.res === "loss" ? !r.win : true) && (!f.card || !!r.card));
}

/** tradesView(ctx) -> {el, set()}: its own endpoint, read now and every 30 s. */
export function tradesView(ctx) {
  const q = ctx.params.query || {};
  const st = {acct: IDS.includes(q.acct) ? q.acct : local.get("lb-tacct2", "bybit"), f: F0(), d: null, open: null, okAt: 0};
  if (!IDS.includes(st.acct)) st.acct = "bybit";
  const seg = ui.seg(IDS.map((id) => ({id, label: acctKo(id)})), st.acct, (id) => { st.acct = id; local.set("lb-tacct2", id); st.f = F0(); st.open = null; resSeg.set("all"); draw(true); },
    {label: "계좌 고르기"});
  const coinSel = h("select", {class: "select", "aria-label": "코인"});
  const stratSel = h("select", {class: "select", "aria-label": "매매법"});
  const resSeg = ui.seg([{id: "all", label: "전부"}, {id: "win", label: "이김"}, {id: "loss", label: "짐"}], "all", (id) => { st.f.res = id; draw(false); }, {label: "이김·짐"});
  const cardBtn = h("button", {type: "button", "aria-pressed": "false", title: "손실 카드가 있는 거래만 (감시가 손실마다 만든 카드)",
    onclick: () => { st.f.card = !st.f.card; draw(false); }}, "손실 카드만");
  coinSel.addEventListener("change", () => { st.f.coin = coinSel.value; draw(false); });
  stratSel.addEventListener("change", () => { st.f.strat = stratSel.value; draw(false); });
  const sum = h("div", {class: "lb-tsum"});
  const csum = h("div", {class: "lb-slot lb-csumw"});
  const stateSlot = h("div", {class: "lb-slot"});
  const pg = ui.pager({size: 10, row: (r) => rowOf(r), empty: () => (st.d ? ui.empty("맞는 거래가 없어요") : motion.shimmer(3))});
  const cap = h("div", {class: "lb-foot"});
  const el = h("div", {class: "lb-trades stack"},
    ui.card({title: "닫힌 거래", sub: "줄을 누르면 그 거래를 자세히 · 손실이면 손실 카드도 · 10개씩", cls: "lb-tcard"},
      h("div", {class: "lb-tbar"}, seg, h("div", {class: "lb-tfil"}, coinSel, stratSel, resSeg, h("div", {class: "seg lb-cardseg"}, cardBtn))),
      stateSlot, sum, csum, pg.el),
    cap);

  const money = (x, est) => (x == null ? "—" : `${fmt.money(x, true)}${est ? "≈" : ""}`);
  const kv = (k, v) => [k, v == null || v === "" ? "—" : v];
  function detail(r) {
    const live = st.acct !== "paper";
    const s = r.setting;
    const dist = r.stop_initial && r.entry_price ? Math.abs(r.entry_price - r.stop_initial) / r.entry_price : null;
    const rows = [
      kv("매매법", r.strategy_id ? `${fmt.stratKo(r.strategy_id)} (${r.strategy_id})` : "—"), kv("봉", r.timeframe ? fmt.tfKo(r.timeframe) : null),
      kv("설정", r.order ? `${r.order}번 설정${s && s.cell ? ` · ${s.cell}` : ""}` : r.member || "기록 없음"),
      kv("진입 방식", s ? s.entry_ko + (s.invert ? " · 반대 방향" : "") : null),
      kv("손절 방식", s ? s.stop.ko : r.stop_rule || null), kv("처음 손절 거리", dist != null ? `${fmt.pct(dist, 2, false)} (${fmt.price(r.stop_initial)})` : null),
      kv("진입", `${fmt.kst(r.entry_time)} · ${fmt.price(r.entry_price)}`), kv("청산", `${fmt.kst(r.exit_time)}${r.exit_price ? ` · ${fmt.price(r.exit_price)}` : ""}`),
      kv("청산 이유", r.reason_ko), kv("가장 높은 잠금", live ? (r.locked ? `잠금선 ${fmt.price(r.stop_final)}` : r.paper && r.paper.lock_roe != null ? `페이퍼 기준 순ROE ${fmt.pct(r.paper.lock_roe, 0, false)}` : "잠금 없음")
        : r.lock_roe != null ? `순ROE ${fmt.pct(r.lock_roe, 0, false)}` : "잠금 없음"),
      kv(live ? "ROE" : "순ROE", r.roe != null ? fmt.pct(r.roe, 1) : null), kv("손익 (USDT)", money(r.pnl, r.est)),
      kv("수수료", live ? (r.commission != null ? fmt.money(r.commission) : "체결 기록 전") : r.fees != null ? fmt.money(r.fees) : null),
      kv("펀딩", (live ? r.funding : r.funding) != null ? fmt.money(r.funding, true) : null),
    ];
    if (live) {
      rows.push(kv("짝 페이퍼 거래", r.paper ? `${fmt.kst(r.paper.entry_time)} 진입 · ${fmt.price(r.paper.entry_price)} · 손익 ${fmt.money(r.paper.pnl, true)}` : "없음 (페이퍼에 같은 거래가 없어요)"),
        kv("진입 미끄러짐", r.slip_vs_paper != null ? `${fmt.pct(r.slip_vs_paper, 3)} (${r.slip_vs_paper >= 0 ? "페이퍼보다 유리" : "페이퍼보다 불리"})` : null),
        kv("페이퍼 × 크기 비율", r.paper_scaled != null ? fmt.money(r.paper_scaled, true) : null), kv("차이 (실거래 − 페이퍼)", r.diff != null ? fmt.money(r.diff, true) : null));
    }
    const nums = s && s.numbers ? h("div", {class: "lb-nums"}, Object.entries(s.numbers).map(([k, v]) => h("span", {class: "pp thin num"}, `${k} ${Array.isArray(v) ? v.join("/") : v}`))) : null;
    const extra = s ? [s.filter.length ? ui.note(`조건: ${s.filter.map((x) => x.ko).join(" · ")}`) : null, s.disp ? ui.note(`신호봉: ${s.disp}`) : null,
      s.off.length ? ui.disclosure(`끄는 구간 ${fmt.int(s.off.length)}개 보기`, h("p", {class: "note"}, s.off.map((o) => o.ko).join(" · "))) : null] : [];
    const cells = !live && r.live ? h("div", {class: "lb-tlive"}, Object.entries(r.live).map(([id, c]) => h("div", {class: "lb-tcell"}, acctTag(id),
      ui.pill(STATE_KO[c.state] || c.state, c.state === "matched" ? "good" : c.state === "missed" ? "warn" : "thin"),
      c.state === "matched" ? h("span", {class: "num"}, ` 손익 ${money(c.pnl, c.est)} · 미끄러짐 ${c.slip == null ? "—" : fmt.pct(c.slip, 3)} · 차이 ${c.diff == null ? "—" : fmt.money(c.diff, true)}`)
        : h("span", {class: "muted"}, ` ${c.why_ko || ""}`), c.why_text ? h("span", {class: "lb-cmeta muted", title: c.why_text}, ` · ${c.why_text}`) : null))) : null;
    return h("div", {class: "lb-tdet"}, r.card || !r.win ? cardPart(r, live) : null, ui.kv(rows), nums, ...extra, cells);
  }
  /** The loss card first (what the owners open a loss for); a loss without one says why not. */
  function cardPart(r, live) {
    const src = st.d && st.d.cards;
    if (r.card) return cardBlock(r.card, {kinds: src && src.kinds, of: live ? "paper" : null});
    if (src && src.state && src.state !== "ok") return h("div", {class: "lb-cnone"}, sourceState(src, "손실 카드"));
    if (live) return r.paper ? (r.paper.pnl != null && r.paper.pnl < 0 ? h("p", {class: "note"}, "짝 페이퍼 거래의 손실 카드가 아직 없어요") : null)
      : h("p", {class: "note"}, "손실 카드는 페이퍼 거래마다 만들어요: 이 실거래는 짝 페이퍼 거래가 없어 카드가 없어요");
    return h("p", {class: "note"}, "이 손실의 카드는 아직 없어요 (감시가 청산 몇 분 뒤에 만들어요 · 7일보다 오래된 손실은 만들지 않아요)");
  }
  function rowOf(r) {
    const open = st.open === r.key;
    const head = h("button", {type: "button", class: ["lb-trow", r.win ? "win" : "loss"], "aria-expanded": String(open),
      onclick: () => { st.open = open ? null : r.key; pg.rerender(); }},
    h("span", {class: "num muted lb-tt"}, fmt.kst(r.exit_time)), h("b", {class: "lb-tc"}, fmt.coin(r.symbol)), ui.sideTag(r.side),
    h("span", {class: "lb-ts"}, r.strategy_id ? `${fmt.stratKo(r.strategy_id)} · ${fmt.tfKo(r.timeframe)}` : "매매법 모름"),
    h("span", {class: "lb-tpills"}, ui.pill(r.reason_ko || "—", r.exit_reason === "LOCK" || r.exit_reason === "TP" ? "good" : r.exit_reason === "SL" || r.exit_reason === "LIQ" ? "bad" : "thin"),
      r.card ? ui.pill("카드", "thin", `손실 카드: ${r.card.label || ""}`) : null),
    h("span", {class: ["num", "lb-tr", fmt.tone(r.roe)]}, r.roe == null ? "—" : fmt.pct(r.roe, 1)),
    h("b", {class: ["num", "lb-tp", fmt.tone(r.pnl)]}, money(r.pnl, r.est)));
    return h("div", {class: ["lb-titem", open ? "open" : ""], role: "listitem"}, head, open ? detail(r) : null);
  }
  function options(sel, vals, label, cur, lab) {
    sel.replaceChildren(h("option", {value: ""}, label), ...vals.map((v) => h("option", {value: v}, lab(v))));
    sel.value = vals.includes(cur) ? cur : "";
  }
  function draw(user) {
    seg.set(st.acct);
    cardBtn.setAttribute("aria-pressed", String(st.f.card));
    const a = st.d ? st.d.accts[st.acct] : null;
    if (!st.d) { put(stateSlot); pg.set(undefined); return; }
    if (!a || a.state !== "ok") { put(stateSlot, sourceState(a, acctKo(st.acct))); put(sum); put(csum); pg.set([]); return; }
    put(stateSlot);
    const rows = a.rows || [];
    options(coinSel, [...new Set(rows.map((r) => r.symbol))].sort(), "코인 전부", st.f.coin, (v) => fmt.coin(v));
    options(stratSel, [...new Set(rows.map((r) => r.strategy_id).filter(Boolean))].sort(), "매매법 전부", st.f.strat, (v) => fmt.stratKo(v));
    st.f.coin = coinSel.value; st.f.strat = stratSel.value;
    const xs = filterRows(rows, st.f);
    const w = xs.filter((r) => r.win).length, pnl = xs.reduce((s, r) => s + (Number(r.pnl) || 0), 0);
    put(sum, h("span", null, `${fmt.int(xs.length)}번`), h("span", {class: "muted"}, ` / 전체 ${fmt.int(a.n)}번 · `), h("b", {class: "up"}, `${fmt.int(w)}승`), " ",
      h("b", {class: "down"}, `${fmt.int(xs.length - w)}패`), " · 손익 ", h("b", {class: ["num", fmt.tone(pnl)]}, `${fmt.money(pnl, true)} USDT`),
      ui.smallSample(xs.length, 20), a.n > a.rows.length ? h("span", {class: "muted"}, ` · 최근 ${fmt.int(a.rows.length)}번만`) : null);
    const cs = st.d.cards || {};
    put(csum, cs.state && cs.state !== "ok" ? sourceState(cs, "손실 카드") : cardSummary(xs, cs.kinds, cs));
    pg.set(xs, !user);
    put(cap, st.acct === "paper" ? ui.assumeLine(["closed"], "페이퍼 A+C 합본") : ui.assumeLive(`${acctKo(st.acct)} · ≈ = 체결 기록 전 지갑 변화로 어림`));
  }
  async function load() {
    let d;
    try { d = await ctx.api("/api/v4/livebots/trades"); st.okAt = Date.now(); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      if (!st.d) put(stateSlot, ui.errorBox(e, () => load()));
      else put(stateSlot, ui.staleNote(e, st.okAt, () => load()));
      throw e;
    }
    // the same records again (asked every 30 s) redraw nothing: an opened trade and its card stay as they are
    const sig = JSON.stringify({...d, now_ms: 0});
    if (st.d && sig === st.sig) { put(stateSlot); return; }
    st.d = d; st.sig = sig;
    if (ctx.alive()) draw(false);
  }
  draw(true);
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  return {el, set() {}};
}
