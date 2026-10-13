// #/account/<id> 계좌 자세히: one account and its pick's other four side by side: the numbers (trades, win rate, mean per
// trade, wallet, drawdown, the basis verdict and the warning light), the five wallets as lines over the same days, the
// pick's custom values against the defaults with its exit, where the pick came from, and this account's closed trades
// (the newest 200 the snapshot keeps). Data: the shared snapshot + /api/trades/<id> for the five.
// 설치 뒤 진입만 (js/after.js, the switch under the head): the open-position pill, 지금 포지션 and the 거래 기록 keep only
// what was entered after the install (a position entered before reads "설치 전 진입 · 숨김" where its pill would be; the
// record's count says 설치 뒤만); the numbers, the five wallets' lines and the comparisons stay the full record from the start.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {ROLES, ROLE_KO, ROLE_DESC, tfKo, sideKo, reasonKo, coinOf, coinShort, lineupOn} from "../labels.js";
import {paramTable, originBox} from "./custom.js";
import {posPill, pricesLive} from "../poskit.js";
import {serverNow} from "../live.js";
import {afterBar, afterOn, afterBook, openAfter, openBefore, beforeChip, afterEmpty} from "../after.js";
import * as RK from "../rulekit.js";
import * as WK from "../whykit.js";
import {whyCard as retCard} from "./account-why.js";
import {replayHref} from "../why.js";

export const css = ["scr/replay.css"];

/** Live ROE may be shown: the engine is not catching up, wrote its record in the last 15 minutes, and the prices
 *  are live (poskit pricesLive). */
const liveOk = (d) => !!d && !LK.catchingUp(d) && !(d.generated_ms && serverNow() - d.generated_ms > 15 * 60000) && pricesLive();

export async function mount(el, ctx) {
  let meta = null;
  try { meta = await ctx.meta(); } catch (e) { /* codes */ }
  const id = ctx.params.arg;
  const head = h("div"), stats = h("div"), chart = h("div"), five = h("div"), params = h("div"), trades = h("div"), split = h("div");
  const why = h("div"), rule = h("div"), ret = h("div");
  const chartCard = ui.card({plate: "잔고 흐름", sub: `같은 후보의 계좌 5개 · 닫힌 거래마다 · ${LK.startUsd()}에서 시작`}, chart);
  const splitCard = ui.card({plate: "롱 · 숏 · 코인별 · 커스텀값이 바꾼 거래", sub: "이 후보(후보 계좌)의 닫힌 거래를 나눠 보기 · 한쪽 방향이나 한 코인에서만 벌었으면 운일 수 있음"}, split);
  const fiveCard = ui.card({plate: "계좌 5개", sub: "누르면 그 계좌"}, five);
  /** The card words that count the pick's accounts: five in the candidate league, the lineup's kinds (those this pick has) in the owner-exit league. */
  const cardWords = (set) => {
    const owner = lineupOn(), n = ROLES.filter((r) => set && set[r]).length;
    const f = (card, k, t) => { const e = card.querySelector(k); if (e) e.textContent = t; };
    f(chartCard, ".sub", `같은 후보의 계좌 ${owner ? fmt.int(n) : 5}개 · 닫힌 거래마다 · ${LK.startUsd()}에서 시작`);
    f(splitCard, ".sub", `이 후보(${owner ? `‘${ROLE_KO.cand}’ 계좌` : "후보 계좌"})의 닫힌 거래를 나눠 보기 · 한쪽 방향이나 한 코인에서만 벌었으면 운일 수 있음`);
    f(fiveCard, ".plate", `계좌 ${owner ? fmt.int(n) : 5}개`);
  };
  const body = h("div", {class: "stack"}, stats, ret, why,
    chartCard,
    rule,
    splitCard,
    fiveCard,
    params,
    ui.card({plate: "거래 기록", sub: "이 계좌 · 최신 200번까지 · 코인을 누르면 터미널"}, trades));
  const afterEl = afterBar({cls: "cl-actafter"});
  el.append(head, afterEl, body);
  let seen = null, pill = null, doc = null, R = RK.rulesNow(), INS = null;
  ctx.onLive(() => { if (pill) pill.update({allowed: liveOk(doc)}); });
  /** 왜 이 성적인가 (whykit) and the pick's 익절·손절·배수 card (rulekit), painted again when their data arrives. */
  function paintWhy(d) {
    const ix = LK.index(d);
    const a = ix.byId[id];
    if (!a) { put(why, null); put(rule, null); return; }
    const c = LK.pickOf(a, ix) || a;
    const set = ix.sets[c.id] || {};
    const p = R && R.picks ? R.picks[c.id] : null;
    // the 동전 account shares the 후보's signal times and exit (a fair yardstick for the 후보 only); the rule's own
    // break-even only for an account with the pick's exit (not the 기본값's lock)
    put(why, INS ? WK.whyCard(a, (INS.accounts || {})[a.id], {flip: a.role === "cand" ? set.flip : null, rule: p && a.exit === p.exit ? p : null, pick: c,
      href: (t) => `#/terminal?acct=${encodeURIComponent(a.id)}&coin=${coinOf(t.symbol)}&at=${t.entry_time}`}) : null);
    // an account whose exit is not the pick's (the 기본값's lock) reads its own exit first (rulekit ownExitBox)
    put(rule, c.role === "cand" ? ui.card({plate: "익절 · 손절 · 배수", sub: `${LK.pickKo(c, meta)} · 이 후보의 익절·손절과 ${lineupOn() ? "모든 계좌 공통" : "계좌 5개 공통"} 배수 규칙 · 지금 코인별로 몇 배가 되나`, cls: "rl-pickcard"},
      p ? RK.pickRuleBody(p, R, {account: a}) : RK.ruleBox(c, R)) : null);
  }
  RK.loadRules(ctx, (x) => { R = x; if (ctx.alive() && LK.league()) paintWhy(LK.league()); }).catch(() => { /* the exit's name stays */ });
  ctx.onLeague(async (d) => {
    doc = d;
    paintWhy(d);
    WK.loadInsight(ctx).then((x) => { if (x !== INS && ctx.alive()) { INS = x; paintWhy(LK.league()); } }).catch(() => { /* the card stays away */ });
    const ix = LK.index(d);
    const a = ix.byId[id];
    body.hidden = !a;
    if (!a) {
      put(head, ui.screenHead("계좌 자세히"), d.accounts ? h("div", {class: "stack tight"}, ui.empty("그런 계좌가 없습니다"),
        h("p", null, h("a", {class: "btn-line", href: "#/rank"}, "순위표에서 고르기"))) : ui.none("준비 중"));
      return;
    }
    const c = LK.pickOf(a, ix) || a;
    const set = ix.sets[c.id] || {[a.role]: a};
    ctx.setTitle(`${LK.pickKo(c, meta)} ${ROLE_KO[a.role]}`);
    // the open position with its live ROE (rule bot 순위표 pill); a hidden DeepSeek position: coin and side only
    const hid = LK.dsHidden(a) || (a.kind === "ds" && a.wallet == null);
    pill = openAfter(a) ? posPill(a, {allowed: liveOk(d), hidden: hid}) : null;
    put(head, ui.screenHead(`${LK.pickKo(c, meta)}`, `${ROLE_KO[a.role]} 계좌 · ${a.id}`,
      [h("a", {class: "btn-line", href: `#/terminal?acct=${encodeURIComponent(a.id)}`}, "터미널에서 보기"),
        h("a", {class: "btn-line", href: `#/custom?s=${encodeURIComponent(c.name)}`}, "커스텀값"),
        h("a", {class: "btn-line", href: "#/rank"}, "순위표")]),
    h("div", {class: "row wrap cl-acthead"}, LK.fig(a, 28), LK.roleChip(a.role), LK.kindChip(a.kind), LK.styleChip((LK.pickMeta(c.id, meta) || {}).style),
      h("span", {class: "pp thin"}, a.exit_ko), pill || beforeChip(a), a.bust ? ui.pill("파산", "bad") : null, h("span", {class: "muted"}, ROLE_DESC[a.role])));
    const j = ix.judge[c.id];
    put(stats, h("div", {class: "stats cl-stats6"},
      ui.stat("거래", `${fmt.int(a.trades)}번`, a.trades < 30 ? "30번 전: 아직 판단 안 함" : `승 ${fmt.int(a.wins)} · 패 ${fmt.int(a.trades - a.wins)}`),
      ui.stat("승률", LK.winTxt(a)),
      ui.stat("한 번 평균", LK.ret(a.mean_ret, {hiddenIf: LK.dsHidden(a)}), "닫힌 거래마다 직전 지갑 대비"),
      ui.stat("잔고", LK.wallet(a), a.wallet != null ? fmt.pct(LK.walletChange(a), true, 1) + ` (시작 ${LK.startUsd()})` : null),
      ui.stat("최대 낙폭", LK.ddTxt(a), "닫힌 거래 기준"),
      ui.stat(a.role === "cand" ? (lineupOn() ? "경고등" : "기준") : "지금 포지션", a.role === "cand" ? (lineupOn() ? (LK.bandMark(j) || h("span", {class: "muted"}, "—")) : h("span", null, LK.verdictPill(j), " ", LK.bandMark(j) || ""))
        : openAfter(a) ? h("span", {class: ["side", a.open.side > 0 ? "long" : "short"]}, `${coinShort(coinOf(a.open.symbol))} ${sideKo(a.open.side)}`)
          : openBefore(a) ? h("span", {class: "muted", title: "설치 전에 들어간 포지션이라 '설치 뒤 진입만' 보기에서 숨김"}, "설치 전 진입 · 숨김") : "없음",
      a.role !== "cand" && openBefore(a) ? "설치 뒤만 보는 중" : null)));
    cardWords(set);
    put(five, LK.fiveRows(set));
    put(split, LK.sideSplit(((d.watch || {}).picks || {})[c.id], {hidden: LK.dsHidden(c)}),
      LK.pairedBox((((d.watch || {}).picks || {})[c.id] || {}).paired, {hidden: LK.dsHidden(c)}));
    put(params, c.role === "cand" ? ui.card({plate: "커스텀값", sub: `${c.name} · ${tfKo(c.tf)} · 색 글씨 = 기본값에서 바뀐 값 · 범위 끝 = 탐색한 가장 끝 값`},
      h("div", {class: "cl-pickgrid"}, h("div", {class: "stack tight"}, paramTable(c, set.base, meta)),
      originBox(c, meta))) : null);
    if (seen === d.done_ms) return;
    seen = d.done_ms;
    const ids = ROLES.map((r) => set[r]).filter(Boolean);
    const books = await Promise.all(ids.map((x) => ctx.api(`/api/trades/${encodeURIComponent(x.id)}`).catch(() => null)));
    if (!ctx.alive()) return;
    const series = ids.map((x, i) => ({role: x.role, label: ROLE_KO[x.role], points: books[i] && books[i].equity})).filter((x) => x.points);
    put(chart, series.length ? LK.equityLines(series, {label: `${LK.pickKo(c, meta)} 계좌 ${lineupOn() ? fmt.int(ids.length) : 5}개 잔고`, until: d.done_ms})
      : ui.empty(a.kind === "ds" ? "딥시크 금액 숨김 설정이라 잔고 그래프가 없습니다" : "아직 끝난 거래가 없습니다"));
    const mine = books[ids.findIndex((x) => x.id === a.id)];
    put(ret, retCard(a, mine, {start: LK.EQUITY, hidden: hid}));          // 왜 이 수익률인가: the full record, not the 설치 뒤 view
    const kept = afterBook(mine);                            // 설치 뒤 진입만: the trades entered after the install
    const nKept = (kept && kept.trades || []).length, nAll = (mine && mine.trades || []).length;
    put(trades, afterOn() && kept ? h("p", {class: "note"}, `설치 뒤만 · ${fmt.int(nKept)}번 (이 목록의 전체 ${fmt.int(kept.all_trades || 0)}번 중)`) : null,
      afterOn() && !nKept && nAll ? afterEmpty("설치 뒤에 들어간 끝난 거래가 아직 없습니다", `이 계좌의 최근 거래 ${fmt.int(nAll)}번은 모두 설치 전에 들어간 것이라 '설치 뒤 진입만'에서 숨겼습니다`)
        : tradeTable((kept && kept.trades) || [], a));
  });
}

export function tradeTable(rows, a) {
  if (!rows.length) return ui.empty("아직 끝난 거래가 없습니다");
  return ui.table([
    {label: "청산 (KST)", l: true, get: (t) => h("span", {class: "num"}, fmt.kst(t.exit_time))},
    {label: "코인", l: true, get: (t) => h("a", {href: `#/terminal?acct=${encodeURIComponent(a.id)}&coin=${coinOf(t.symbol)}&at=${t.entry_time}`, class: "dl-tlink"}, coinShort(coinOf(t.symbol)))},
    {label: "방향", l: true, get: (t) => h("span", {class: ["side", t.side > 0 ? "long" : "short"]}, sideKo(t.side))},
    {label: "진입 (KST)", get: (t) => h("span", {class: "num muted"}, fmt.kst(t.entry_time))},
    {label: "진입가", get: (t) => (t.entry_price == null ? "숨김" : fmt.price(t.entry_price))},
    {label: "청산가", get: (t) => (t.exit_price == null ? "숨김" : fmt.price(t.exit_price))},
    {label: "이유", get: (t) => reasonKo(t.exit_reason)},
    {label: "배수", get: (t) => (t.leverage ? `${fmt.int(t.leverage)}배` : "—")},
    {label: "증거금 대비", get: (t) => (t.roe == null ? h("span", {class: "muted"}, "숨김") : h("span", {class: ["num", fmt.tone(t.roe)]}, fmt.pct(t.roe * 100, true, 1)))},
    {label: "손익", get: (t) => (t.pnl == null ? h("span", {class: "muted"}, "숨김") : h("span", {class: ["num", fmt.tone(t.pnl)]}, fmt.money(t.pnl, true)))},
    {label: "다시보기", get: (t) => h("a", {href: replayHref(a.id, t.entry_time), class: "dl-tlink", title: "이 거래를 봉 하나씩 다시 보기"}, "다시보기")},
  ], rows, {cls: "lv-dense"});
}
