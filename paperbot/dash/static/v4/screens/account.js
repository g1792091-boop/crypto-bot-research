// #/account/<account id> — 계좌 (builder B, CONTRACT.md §4, INVENTORY §8; a hidden tab reached from every list).
// One paper account: wallet (LED, counts to new values), trades / win rate, lock exits (house) or band / time exits
// (the reel), drawdown, signals entered / skipped / rejected; a coin-flip comparison only as 참고 (DeepSeek: the 참고
// pill only); its exit rules in plain words; an extra account's rule, proposal and events; the open position card;
// the equity curve with the start line; a candle chart per coin with its entries and exits; its trades with the why
// line, ten per page; the CSV. update(params) swaps the account in place.
// Top (builder grid): the profile card (grid-kit.js; name, group chip, curve with the same-timeframe coin flips' median,
// 수익률 / 최대 낙폭 / 승률 / 거래 수, the coin-flip difference as 참고, 7일 / 30일). An account the map does not cover (a
// copy / new-lab extra) keeps the plain head and the 참고 box. Every closed trade row links to its replay
// (#/replay/<trade id>).
import {h, ui, fmt, derive, store, motion, makeChart, candleOptions, candleGlow, tok, priceDec, local, fullChart} from "../core/pb.js";
import {accountPicker, chartWindow, markLabels} from "./account-pick.js";
import {normPos, posCard, tradeRow, reelExits, nameOf, groupKo, REEL_BARS, LADDER} from "./positions-kit.js";
import {profileCard} from "./grid-kit.js";
import {termChip, termify} from "./faq-terms.js";

const OUTCOME_KO = {ENTERED: "진입", SKIPPED: "건너뜀", REJECTED: "거절", FILTERED: "규칙으로 건너뜀"};
const EXTRA_ST_KO = {active: "도는 중", suspended: "멈춤 (보류)", held: "정지 (동결)"};
const EVENT_KO = {created: "시작", suspended: "멈춤 (보류)", resumed: "다시 돎", held: "정지 (동결)", code_accepted: "새 코드 받아들임"};
const TF_S = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400};
const decOf = priceDec;
/** 같은 매매법: the kinds whose timeframe accounts share one rule (a copy / new-lab extra follows its own). */
const SAME_KINDS = new Set(["strategy", "ds200", "reel", "random"]);
const tfRank = (tf) => { const i = fmt.TF_ORDER.indexOf(tf); return i < 0 ? 99 : i; };
/** The board rows of a's strategy and kind, 5m → 4h (a itself included). */
export function sameOf(board, a) {
  return ((board && board.accounts) || []).filter((x) => x.strategy === a.strategy && x.kind === a.kind)
    .sort((x, y) => tfRank(x.timeframe) - tfRank(y.timeframe));
}
const parseData = (raw) => { if (raw && typeof raw === "object") return raw; try { const d = JSON.parse(raw || "{}"); return d && typeof d === "object" ? d : {}; } catch (e) { return {}; } };

let cur = null;           // {el, ctx, show(id)} of the mounted screen

export async function mount(el, ctx) {
  const view = {id: null, gen: 0, disposers: [], card: null, led: null, d: null, prof: null};
  const clean = () => { for (const f of view.disposers.splice(0)) { try { f(); } catch (e) { /* gone */ } } };
  ctx.track(clean);

  // quiet: a refresh of the same account (new trade, position opened / closed): no shimmer, numbers count from where
  // they were, the page stays where it is.
  async function show(id, quiet) {
    const gen = ++view.gen;
    if (!quiet || id !== view.id) { view.prev = null; }
    view.id = id;
    ctx.setTitle("계좌");
    if (!id) {
      // no account in the link: a picker with search (the last viewed account or the top of the saved group first)
      clean();
      const b = await store.need("board", 120000).catch(() => null);
      if (gen !== view.gen || !ctx.alive()) return;
      el.replaceChildren(ui.screenHead("계좌", "계좌를 고르세요 · 이름이나 코드로 찾을 수 있습니다"),
        b ? accountPicker(ctx, b, {last: local.get("account-last", null)}) : ui.empty("순위 자료를 불러오지 못했습니다"));
      return;
    }
    local.set("account-last", id);
    if (!quiet) { clean(); view.card = null; view.d = null; el.replaceChildren(motion.shimmer(5, true)); window.scrollTo(0, 0); }
    let d;
    try { d = await ctx.api(`/api/account/${encodeURIComponent(id)}`); }
    catch (e) {
      if (e && e.name === "AbortError") return;
      if (gen === view.gen) el.replaceChildren(backLink(), ui.screenHead("계좌", id), ui.errorBox(e, () => show(id)));
      return;
    }
    if (gen !== view.gen || !ctx.alive()) return;
    if (quiet) clean();
    view.d = d;
    await render(d, gen);
  }

  const backLink = () => h("a", {class: "account-back", href: ctx.href("board")}, "← 순위표");

  async function render(d, gen) {
    const board = await store.need("board", 120000).catch(() => null);
    if (gen !== view.gen) return;
    const acc = d.account || {}, data = parseData(acc.data), stt = d.state || {};
    const row = board && board.accounts.find((x) => x.account_id === acc.account_id);
    const a = {...acc, ...(row || {}), ...(d.extra ? {label_ko: d.extra.label_ko} : {})};
    const init = (board && board.initial) || 5000;
    const name = nameOf(a, data);
    ctx.setTitle(name);
    const trades = d.trades || [];
    const n = trades.length, wins = trades.filter((t) => t.pnl > 0).length;
    const reel = reelExits(a);

    // ---------------------------------------------------------------- head
    const pills = [ui.pill(groupKo(a), fmt.groupOf(a) === "core" ? "accent" : ""), stt.bust || a.bust ? ui.pill("파산", "bad") : null,
      a.kind === "copy" ? ui.pill("복제", "", "원본과 같고 한 가지만 바꾼 새 모의 계좌") : null,
      a.kind === "newlab" ? ui.pill("새 매매법", "", "새 매매법 연구실에서 통과한 매매법의 모의 계좌") : null,
      a.extra_status === "suspended" ? ui.pill("멈춤 (보류)", "warn", "새 진입 없음, 열린 포지션은 규칙대로 관리") : null,
      a.extra_status === "held" ? ui.pill("정지 (동결)", "bad", "저장된 상태 그대로 동결") : null,
      a.orphan ? ui.pill("제안 상태와 달리 실행 중", "bad") : null, ui.smallSample(n)];
    const sub = [acc.account_id, `${fmt.tfKo(acc.timeframe)}봉`, fmt.familyKo(a) ? `계열 ${fmt.familyKo(a)}` : null, data.group ? `담당 ${data.group}` : null,
      acc.created_ts ? `시작 ${fmt.kst(acc.created_ts)}` : null].filter(Boolean).join(" · ");

    // ---------------------------------------------------------------- wallet (LED) + stats
    const walletEl = h("b", {class: "led-num num"}), retEl = h("b", {class: "led-sm num"});
    const pnlSum = trades.reduce((s, t) => s + (Number(t.pnl) || 0), 0);
    const led = h("div", {class: "pnl account-led"}, h("div", null, h("span", {class: "k"}, "잔고 (USDT)"), walletEl),
      h("div", {class: "r"}, h("span", {class: "k"}, `시작 ${fmt.money(init)} 대비`), retEl));
    if (view.prev != null) { walletEl.dataset.v = String(view.prev); retEl.dataset.v = String(view.prev / init - 1); }
    view.led = (w) => { if (w != null) view.prev = w; motion.countTo(walletEl, w, {dec: 2}); motion.countTo(retEl, w == null ? null : w / init - 1, {format: "pct", dec: 2, tone: true}); };
    view.led(row && row.wallet != null ? row.wallet : stt.wallet ?? init);
    const locks = trades.filter((t) => t.exit_reason === "LOCK").length;
    const bandTp = trades.filter((t) => t.exit_reason === "TP" || t.exit_reason === "BAND").length;
    const timeX = trades.filter((t) => t.exit_reason === "TIME" || t.exit_reason === "END").length;
    const sig = d.signals || {}, sigN = Object.values(sig).reduce((s, x) => s + x, 0);
    const mdd = stt.max_drawdown ?? a.max_drawdown;
    // the profile card (top) carries trades, win rate and drawdown for its window; an extra account (no card) keeps
    // them here
    const isExtra = fmt.groupOf(a) === "extra" || fmt.groupOf(a) === "other";
    const stats = h("div", {class: ["stats", isExtra ? "s4" : "account-s2"]},
      isExtra ? ui.stat("거래", `${fmt.int(n)}건`, h("span", {class: "s"}, `승률 ${n ? fmt.pct(wins / n, 0, false) : "—"} `, ui.smallSample(n))) : null,
      reel ? ui.stat("윗밴드 익절 · 시간 청산", `${fmt.int(bandTp)} · ${fmt.int(timeX)}`, "사다리 잠금 없음")
        : ui.stat("익절 잠금 청산", `${fmt.int(locks)}건`, n ? `거래의 ${fmt.pct(locks / n, 0, false)}` : ""),
      isExtra ? ui.stat("최대 낙폭", mdd ? fmt.pct(-mdd, 1) : "—", stt.bust || a.bust ? h("span", {class: "s down"}, "파산") : "") : null,
      // the signal tile only where signals are recorded: a DeepSeek / 5m / coin-flip account with none shows nothing
      // ("신호 0개 · 기록 없음" next to 25 trades read like a fault)
      !sigN && (a.kind === "ds200" || a.kind === "random" || reel) ? null
        : ui.stat("신호", `${fmt.int(sigN)}개`, Object.keys(OUTCOME_KO).filter((k) => sig[k]).map((k) => `${OUTCOME_KO[k]} ${fmt.int(sig[k])}`).join(" · ") || "기록 없음"));
    const walletCard = h("section", {class: "card account-wallet", "aria-label": "잔고"}, led,
      h("p", {class: "pos-plain"}, "청산된 거래 손익 합계 ", h("b", {class: fmt.tone(pnlSum)}, fmt.usdt(pnlSum, true)),
        d.trades && d.trades.length >= 500 ? " (최근 500건)" : "", n ? ` · 이긴 거래 ${fmt.int(wins)} / ${fmt.int(n)}` : ""),
      stats, ui.assume());

    // ---------------------------------------------------------------- 참고: the coin flips of the same interval
    const ref = refBox(a, board, init);

    // ---------------------------------------------------------------- rules, extra, position
    const rules = ui.card({plate: "청산 규칙"}, reel
      ? h("p", {class: "pos-plain"}, h("b", null, "자기 청산 규칙"), ` (사다리 잠금 없음): 손절은 스윙 저점 아래 고정 (스탑 마켓), 목표는 직전 5분봉의 볼린저(20, 2) 윗밴드에 걸어 둔 리밋 (5분마다 옮겨짐), 진입 후 ${REEL_BARS}봉 (8시간)이 지나면 시간 청산. 손절과 목표가 같은 봉에 닿으면 손절이 먼저입니다.`)
      : h("p", {class: "pos-plain"}, h("b", null, "기본 청산 규칙"), ` (공통): 진입 때 정한 손절선, 고정 익절 없음. 순 ROE +${fmt.num((LADDER.first + LADDER.gap) * 100, 0)}%가 되면 손절선을 +${fmt.num(LADDER.first * 100, 0)}% 잠금 자리로 올리고, 그 뒤 ${fmt.num(LADDER.step * 100, 0)}%씩 계단으로 올립니다. 잠금은 내려가지 않습니다.`),
      a.kind === "random" ? h("p", {class: "pos-note"}, reel
        ? `5분봉 동전 봇: 롱만 무작위로 들어가고, 릴스 5분 단타와 같은 청산 규칙(스윙 저점 손절 · 윗밴드 목표 · ${REEL_BARS}봉 시간 청산)으로 나옵니다. 릴스 5분 단타의 비교 기준 계좌입니다.`
        : "동전 봇: 방향을 동전 던지기로 정하는 비교 기준 계좌입니다. 매매법 계좌와 같은 규칙(사다리 잠금)으로 청산합니다.") : null);
    const extra = d.extra ? extraCard(d.extra) : null;
    const pos = normPos(stt.position);
    let posEl;
    if (pos) {
      view.card = posCard(a, pos, {why: d.position_why, wallet: stt.wallet ?? a.wallet, data, href: ctx.href, noAccountLink: true, noName: true});
      view.card.update(store.mark(pos.symbol));
      posEl = h("div", {class: "stack tight"}, ui.plate("열린 포지션"), view.card);
    } else posEl = ui.card({plate: "열린 포지션"}, ui.empty("지금 열린 포지션이 없습니다"));

    // ---------------------------------------------------------------- charts and trades
    const eqBox = h("div", {class: "account-eq", "data-fc-grow": ""});
    // 차트 크게 보기 for the curve too (core/fullchart.js), once there is a curve to see (2 points or more)
    const eqFs = (d.equity || []).length >= 2 ? fullChart({ctx, label: "자본 곡선"}) : null;
    const eqCard = ui.card({plate: "자본 곡선", sub: `기록 ${fmt.int(d.equity_points || 0)}점${(d.equity || []).length < (d.equity_points || 0) ? ` · 화면에는 ${fmt.int(d.equity.length)}점으로 줄임` : ""}`,
      acts: eqFs ? [eqFs] : null}, eqBox, ui.assume("closed", "점선은 시작 잔고"));
    if (eqFs) eqFs.bind(eqCard);
    const syms = [...new Set(trades.map((t) => t.symbol).concat(pos ? [pos.symbol] : []))];
    const symSel = h("select", {class: "select", "aria-label": "코인"}, (syms.length ? syms : ["BTCUSDT"]).map((s) => h("option", {value: s}, fmt.coin(s))));
    if (pos) symSel.value = pos.symbol;
    else if (trades.length) symSel.value = [...trades].sort((x, y) => (y.exit_time || 0) - (x.exit_time || 0))[0].symbol;
    const cBox = h("div", {class: "account-candles", "data-fc-grow": ""});
    const fs = fullChart({ctx, label: "계좌 차트"});                  // 차트 크게 보기 (core/fullchart.js, key "f")
    const candleCard = ui.card({plate: "코인별 진입·청산", sub: `${fmt.tfKo(acc.timeframe)}봉 · 첫 거래부터 지금까지`, acts: [symSel, fs], cls: "account-cc"}, cBox,
      h("p", {class: "pos-note"}, "화살표 = 진입, 동그라미 = 청산 (초록 수익, 빨강 손실). 열린 포지션이 있으면 진입·손절·청산가 선이 나옵니다."));
    fs.bind(candleCard);
    const pg = ui.pager({size: 10, row: (t) => withReplay(tradeRow(t, a, {noName: true, why: true, prices: true, equity: true}), t), empty: "아직 거래가 없습니다"});
    pg.set(trades);
    const tradesCard = ui.card({plate: "거래 내역", sub: `${fmt.int(n)}건 · 최근 것부터`,
      acts: [h("a", {class: "btn-line", href: `/api/export/trades.csv?account=${encodeURIComponent(acc.account_id)}`, download: ""}, "엑셀(CSV)")]},
      pg.el, ui.assume("closed", "거래마다 나갈 때 수수료·펀딩 뒤"));

    // the head: the profile card for every account on the map; the plain head + 참고 box otherwise (or when the card's
    // route answers 404)
    const plainHead = () => [h("div", {class: "scr-head account-head"}, h("h1", null, name), h("span", {class: "sub"}, sub)),
      h("div", {class: "row wrap account-pills"}, pills)];
    const headSlot = h("div", {class: "stack account-top"});
    view.plain = () => { headSlot.replaceChildren(...plainHead()); if (ref) headSlot.append(ref); };
    let refSlot = null;
    if (isExtra || (view.prof && view.prof.id === acc.account_id && view.prof.missing)) { headSlot.append(...plainHead()); refSlot = ref; }
    else {
      if (!view.prof || view.prof.id !== acc.account_id) {
        const prof = {id: acc.account_id, missing: false};
        prof.card = profileCard(ctx, acc.account_id, {head: true, cls: "account-prof",
          sub: [acc.account_id, acc.created_ts ? `시작 ${fmt.kst(acc.created_ts)}` : null].filter(Boolean).join(" · "),
          onMissing: () => { prof.missing = true; if (view.prof === prof && view.plain) view.plain(); }});
        if (view.prof && view.prof.mo) view.prof.mo.disconnect();
        view.prof = prof;
        prof.mo = watchTerms(prof.card.el);
        prof.card.load();
      } else view.prof.card.load();
      headSlot.append(view.prof.card.el);
    }
    const same = sameStrip(a, board, init);
    view.same = same;
    // the coin chart sits full width right under the profile card (v3's centrepiece); the separate 자본 곡선 panel only
    // where no profile card draws the curve already (an extra account, or a card the server does not have)
    const profDraws = !isExtra && !(view.prof && view.prof.missing);
    // (the DOM's own replaceChildren writes a null as the word "null": an extra account has no same-strategy strip)
    el.replaceChildren(...[backLink(), headSlot, same ? same.el : null, candleCard,
      h("div", {class: "account-cols"},
        h("div", {class: "stack"}, walletCard, refSlot, posEl, profDraws ? null : eqCard),
        h("div", {class: "stack"}, rules, extra, tradesCard))].filter(Boolean));

    // "?" chips next to the number names this page draws (용어 사전 in the FAQ)
    termify(walletCard);
    if (posEl) termify(posEl);
    // the charts draw once their boxes are on the page
    if (!profDraws) drawEquity(eqBox, d, init, gen);
    const drawC = () => drawCandles(cBox, d, a, symSel.value, gen);
    symSel.addEventListener("change", drawC);
    drawC();
  }

  // ---------------------------------------------------------------- 다시보기 on a closed trade row
  // an inline link at the end of the meta line (keeps the phone rows short; positions-kit's o.replay button squeezes
  // this page's longer meta line into one column); nothing is added when the row already has a replay link
  function withReplay(row, t) {
    if (!t || t.id == null || row.querySelector('a[href^="#/replay/"]')) return row;
    const link = h("a", {class: "account-replay", href: ctx.href("replay", String(t.id)), title: "이 거래를 봉 차트에서 다시 보기",
      "aria-label": `${fmt.coin(t.symbol)} 거래 다시보기`}, h("span", {class: "pl", "aria-hidden": "true"}, "▶"), "다시보기");
    const meta = row.querySelector(".meta");
    if (meta) meta.append(link); else row.append(link);
    return row;
  }

  /** Keep the "?" chips on a card that redraws itself (the profile card): termify now and after each redraw. */
  function watchTerms(node) {
    termify(node);
    if (typeof MutationObserver !== "function") return null;
    const mo = new MutationObserver(() => termify(node));      // termify skips chipped labels: no loop
    mo.observe(node, {childList: true, subtree: true});
    ctx.track(() => mo.disconnect());
    return mo;
  }

  // ---------------------------------------------------------------- 같은 매매법 (under the profile card)
  // The same strategy's own timeframe accounts (same kind; a copy / new-lab extra follows another rule: no strip), each
  // with its return now from the board row, or for DeepSeek and the coin flips only its trade count (counted, never
  // money: CONTRACT §1.3, nothing per account beyond 참고), and whether it holds a position. Two buttons: the strategy page at this timeframe (rules and the
  // indicator chart) and the strategy's own AI room when the server has one (the 36 only today).
  function sameStrip(a, board, init) {
    if (!board || !a.strategy || !SAME_KINDS.has(a.kind)) return null;
    const ds = a.kind === "ds200", counts = ds || a.kind === "random";
    const box = h("div", {class: "account-same-row", role: "list"});
    const roomId = `strat:${a.strategy}`;
    const rooms = store.get("rooms");
    const hasRoom = rooms && Array.isArray(rooms.rooms) ? rooms.rooms.some((r) => r.room_id === roomId) : a.kind === "strategy";
    const acts = h("div", {class: "row wrap account-same-acts"},
      a.kind !== "random" ? h("a", {class: "btn-line", href: ctx.href("strategies", a.strategy, a.position && a.position.symbol ? {tf: a.timeframe, sym: a.position.symbol} : {tf: a.timeframe})},
        a.position && a.position.symbol ? "진입 중인 차트 보기 (규칙·지표)" : "규칙·지표 차트 보기") : null,
      hasRoom ? h("a", {class: "btn-line", href: ctx.href("rooms", roomId)}, "담당 AI 방") : null);
    const paint = (b) => {
      const sib = sameOf(b, a);
      box.replaceChildren(...sib.map((x) => {
        const me = x.account_id === a.account_id;
        const pos = normPos(x.position);
        const w = x.wallet == null ? init : x.wallet;
        const r = w / init - 1;
        const val = counts ? `${fmt.int(x.trades || 0)}건` : fmt.pct(r, 1);
        const state = x.bust ? h("span", {class: "ps down"}, "파산") : pos ? h("span", {class: "ps"}, `${fmt.coin(pos.symbol)} `, ui.sideTag(pos.side))
          : h("span", {class: "ps muted"}, "대기");
        const kids = [h("span", {class: "tf"}, h("span", null, fmt.tfKo(x.timeframe)), me ? h("small", null, "지금") : null),
          h("b", {class: ["num", counts ? "" : fmt.tone(r, val)]}, val), state];
        return me ? h("div", {class: "account-same-t me", role: "listitem", "aria-current": "page"}, kids)
          : h("a", {class: "account-same-t", role: "listitem", href: ctx.href("account", x.account_id), title: x.account_id}, kids);
      }));
      box.style.setProperty("--n", String(Math.max(1, Math.min(4, sib.length))));
    };
    paint(board);
    const el = h("section", {class: "card account-same", "aria-label": "같은 매매법"},
      h("div", {class: "card-h"}, ui.plate("같은 매매법"), h("span", {class: "sub"}, ds ? "봉마다 닫힌 거래 수 (딥시크는 계좌별 수익을 보지 않음)"
        : counts ? "봉마다 닫힌 거래 수 (동전 봇은 비교 기준이라 개수만)" : "봉마다 지금 수익률"),
        counts ? ui.pill("", "ref") : null),
      box, acts, counts ? null : ui.assume("closed", "수익률 = 지금 잔고 ÷ 시작 잔고"));
    return {el, update: (b) => { if (b && el.isConnected) paint(b); }};
  }

  // ---------------------------------------------------------------- 참고 box
  function refBox(a, board, init) {
    const g = fmt.groupOf(a);
    if (a.kind === "random") return h("p", {class: "refnote"}, h("b", null, "비교 기준"), " · 이 계좌가 동전 봇입니다. 다른 계좌를 이 계좌들과 견줍니다.");
    if (g === "extra") return h("p", {class: "refnote"}, h("b", null, "따로 셈"), " · 나중에 시작한 추가 계좌라 동전 봇과 견주지 않습니다.");
    const s = store.get("summary");
    const vts = s && s.next_checkpoint && s.next_checkpoint.ts;
    if (a.kind === "ds200") return h("div", {class: "stack tight"}, h("div", {class: "row wrap"}, ui.pill("딥시크는 묶음 중앙값으로만 봅니다", "ref")), ui.refNote(vts));
    if (!board) return null;
    const gs = derive.groupStats(board);
    const med = gs.flipMedByTf[a.timeframe];
    const w = a.wallet == null ? init : a.wallet;
    if (med == null) return null;
    const where = w > med ? "위" : w < med ? "아래" : "같음";
    return h("div", {class: "stack tight"}, h("p", {class: "pos-plain"}, h("b", null, "참고"), ` · 같은 ${fmt.tfKo(a.timeframe)}봉 동전 봇 중앙값`, termChip("중앙값"),
      ` ${fmt.money(med)}보다 `, h("b", null, where), " (이 계좌 ", fmt.money(w), ")"), ui.refNote(vts));
  }

  function extraCard(x) {
    const ev = (x.events || []).slice(-8).reverse();
    return ui.card({plate: "추가 계좌"},
      h("p", {class: "pos-plain"}, x.kind === "copy" ? ["복제 계좌 · 원본 ", h("b", null, x.parent || "—"), " · 바꾼 규칙: ", h("b", null, x.rule_ko || x.rule || "—")]
        : ["새 매매법 계좌 · ", x.description_ko || "—"]),
      h("p", {class: "pos-note"}, `제안 #${x.proposal_id ?? "—"}`, x.trial_id != null ? ` · 시험 장부 #${x.trial_id}` : "",
        ` · 시작 ${fmt.kst(x.created_ts)} · 상태 ${EXTRA_ST_KO[x.extra_status] || x.extra_status || "—"}`),
      x.kind === "newlab" && x.spec ? ui.disclosure("규칙 원문 보기", h("pre", {class: "account-spec"}, JSON.stringify(x.spec, null, 1))) : null,
      ev.length ? h("ul", {class: "account-ev"}, ev.map((e) => h("li", null, `${fmt.kst(e.ts)} ${EVENT_KO[e.event] || e.event}`, e.code ? ` (${e.code})` : ""))) : null,
      h("p", {class: "pos-note"}, "원래 계좌들과 따로 셉니다. 시작된 계좌는 규칙대로 돌고, 거절로 멈출 수 없습니다."));
  }

  // ---------------------------------------------------------------- equity curve (lightweight-charts line)
  async function drawEquity(box, d, init, gen) {
    const pts = [];
    for (const p of d.equity || []) { const t = Math.floor(p.t / 1000); if (!pts.length || t > pts[pts.length - 1].time) pts.push({time: t, value: p.v}); }
    if (pts.length < 2) { box.replaceChildren(ui.notYet("곡선 기록 전", "자본 기록이 아직 2점보다 적습니다")); box.classList.add("none"); return; }
    try {
      const c = await makeChart(box);
      if (gen !== view.gen) { c.dispose(); return; }
      view.disposers.push(c.dispose);
      c.chart.applyOptions({handleScroll: false, handleScale: false});
      const s = c.chart.addLineSeries({color: tok("--accent"), lineWidth: 2, priceFormat: {type: "price", precision: 2, minMove: 0.01}, lastValueVisible: true});
      s.setData(pts);
      s.createPriceLine({price: init, color: tok("--muted"), lineStyle: 2, lineWidth: 1, title: "시작"});
      c.chart.timeScale().fitContent();
      // the curve cannot be scrolled or zoomed: at a new size (차트 크게 보기, a turned phone) it fills the width again
      c.chart.timeScale().subscribeSizeChange(() => c.chart.timeScale().fitContent());
    } catch (e) { box.replaceChildren(ui.errorBox(e)); }
  }

  // ---------------------------------------------------------------- candles of one coin with this account's marks
  let cChart = null;
  async function drawCandles(box, d, a, sym, gen) {
    if (cChart) { cChart.dispose(); cChart = null; }
    const tf = a.timeframe, step = TF_S[tf] || 900;
    box.replaceChildren();
    let data;
    try { data = await ctx.api(`/api/candles?symbol=${encodeURIComponent(sym)}&interval=${encodeURIComponent(tf)}&limit=400`); }
    catch (e) { if (!(e && e.name === "AbortError") && gen === view.gen) box.replaceChildren(ui.errorBox(e)); return; }
    if (gen !== view.gen || !ctx.alive()) return;
    try {
      const c = await makeChart(box);
      if (gen !== view.gen) { c.dispose(); return; }
      cChart = c;
      view.disposers.push(() => { if (cChart === c) { c.dispose(); cChart = null; } });
      const s = c.chart.addCandlestickSeries(candleOptions());
      candleGlow(c.chart, s);                              // the AI skin's soft neon glow (core/chartfx.js), nothing in 클래식
      const dec = decOf(data.length ? data[data.length - 1].close : 1);
      s.applyOptions({priceFormat: {type: "price", precision: dec, minMove: Math.pow(10, -dec)}});
      s.setData(data);
      const t0 = data.length ? data[0].time : 0, marks = [];
      const mine = (d.trades || []).filter((t) => t.symbol === sym && t.entry_time / 1000 >= t0);
      const op = normPos(d.state && d.state.position);
      const opHere = op && op.symbol === sym && op.entry_time ? op : null;
      const win = chartWindow(data, opHere ? mine.concat([{entry_time: opHere.entry_time}]) : mine, step);
      const lab = markLabels(mine.length, win);
      for (const t of d.trades || []) {
        if (t.symbol !== sym || t.entry_time / 1000 < t0) continue;
        const e = Math.floor(t.entry_time / 1000), x = Math.floor(t.exit_time / 1000);
        marks.push({time: e - (e % step), position: t.side > 0 ? "belowBar" : "aboveBar", color: tok("--accent"), shape: t.side > 0 ? "arrowUp" : "arrowDown",
          text: lab.entry(t)});
        marks.push({time: x - (x % step), position: t.side > 0 ? "aboveBar" : "belowBar", color: t.pnl > 0 ? tok("--up") : tok("--down"), shape: "circle",
          text: lab.exit(t)});
      }
      if (opHere) {        // the open position's entry arrow (its exit is still to come)
        const e = Math.floor(opHere.entry_time / 1000);
        marks.push({time: e - (e % step), position: opHere.side > 0 ? "belowBar" : "aboveBar", color: tok("--accent"),
          shape: opHere.side > 0 ? "arrowUp" : "arrowDown", text: lab.level === "bare" ? "보유" : `${lab.entry(opHere)} 보유 중`});
      }
      marks.sort((x, y) => x.time - y.time);
      s.setMarkers(marks);
      const p = normPos(d.state && d.state.position);
      if (p && p.symbol === sym) {
        const reel = reelExits(a);
        s.createPriceLine({price: p.entry, color: tok("--accent"), lineWidth: 1, title: "진입"});
        s.createPriceLine({price: p.stop, color: !reel && p.lock_roe != null ? tok("--up") : tok("--down"), lineWidth: 1, lineStyle: 2,
          title: reel ? "손절 (스윙 저점)" : p.lock_roe != null ? "잠금" : "손절"});
        s.createPriceLine({price: p.liq, color: tok("--warn"), lineWidth: 1, lineStyle: 3, title: "청산가"});
        if (reel && p.target) s.createPriceLine({price: p.target, color: tok("--up"), lineWidth: 1, lineStyle: 2, title: "목표 (윗밴드)"});
      }
      // zoom: the first trade on this coin minus ~40 bars through now, so the arrows and dots are readable
      if (win) c.chart.timeScale().setVisibleLogicalRange(win); else c.chart.timeScale().fitContent();
    } catch (e) { box.replaceChildren(ui.errorBox(e)); }
  }

  // ---------------------------------------------------------------- live
  ctx.watch("ticker", () => { if (view.card && view.card.isConnected) view.card.update(store.mark(view.card.pos.symbol)); });
  ctx.watch("board", (b) => {
    if (!b || !view.id || !view.led) return;
    const r = b.accounts.find((x) => x.account_id === view.id);
    if (r && r.wallet != null) view.led(r.wallet);
    if (view.same) view.same.update(b);
    const had = view.d && view.d.state && view.d.state.position, has = r && r.position;
    if (r && (!!had !== !!has || (had && has && had.entry_time !== has.entry_time))) reload();   // opened / closed
  });
  let rT = null;
  const reload = () => { clearTimeout(rT); rT = setTimeout(() => { if (ctx.alive() && view.id) show(view.id, true); }, 1200); };
  ctx.track(() => clearTimeout(rT));
  ctx.on("trades", (rows) => { if ((rows || []).some((t) => t.account_id === view.id)) reload(); });

  cur = {show};
  ctx.track(() => { cur = null; });
  await show(ctx.params.arg);
}

export function update(params) { if (cur) cur.show(params.arg); }

export function unmount() { cur = null; }
