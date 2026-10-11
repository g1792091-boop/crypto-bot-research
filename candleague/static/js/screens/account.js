// #/account/<id> 계좌 자세히: one account and its pick's other four side by side: the numbers (trades, win rate, mean per
// trade, wallet, drawdown, the basis verdict and the warning light), the five wallets as lines over the same days, the
// pick's custom values against the defaults with its exit, where the pick came from, and this account's closed trades
// (the newest 200 the snapshot keeps). Data: the shared snapshot + /api/trades/<id> for the five.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {ROLES, ROLE_KO, ROLE_DESC, tfKo, sideKo, reasonKo, coinOf, coinShort} from "../labels.js";
import {paramTable, originBox} from "./custom.js";

export async function mount(el, ctx) {
  let meta = null;
  try { meta = await ctx.meta(); } catch (e) { /* codes */ }
  const id = ctx.params.arg;
  const head = h("div"), stats = h("div"), chart = h("div"), five = h("div"), params = h("div"), trades = h("div"), split = h("div");
  const body = h("div", {class: "stack"}, stats,
    ui.card({plate: "잔고 흐름", sub: "같은 후보의 계좌 5개 · 닫힌 거래마다 · $5,000에서 시작"}, chart),
    ui.card({plate: "롱 · 숏 · 코인별 · 커스텀값이 바꾼 거래", sub: "이 후보(후보 계좌)의 닫힌 거래를 나눠 보기 · 한쪽 방향이나 한 코인에서만 벌었으면 운일 수 있음"}, split),
    ui.card({plate: "계좌 5개", sub: "누르면 그 계좌"}, five),
    params,
    ui.card({plate: "거래 기록", sub: "이 계좌 · 최신 200번까지 · 코인을 누르면 터미널"}, trades));
  el.append(head, body);
  let seen = null;
  ctx.onLeague(async (d) => {
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
    put(head, ui.screenHead(`${LK.pickKo(c, meta)}`, `${ROLE_KO[a.role]} 계좌 · ${a.id}`,
      [h("a", {class: "btn-line", href: `#/terminal?acct=${encodeURIComponent(a.id)}`}, "터미널에서 보기"),
        h("a", {class: "btn-line", href: `#/custom?s=${encodeURIComponent(c.name)}`}, "커스텀값"),
        h("a", {class: "btn-line", href: "#/rank"}, "순위표")]),
    h("div", {class: "row wrap cl-acthead"}, LK.roleChip(a.role), LK.kindChip(a.kind), LK.styleChip((LK.pickMeta(c.id, meta) || {}).style),
      h("span", {class: "pp thin"}, a.exit_ko), a.bust ? ui.pill("파산", "bad") : null, h("span", {class: "muted"}, ROLE_DESC[a.role])));
    const j = ix.judge[c.id];
    put(stats, h("div", {class: "stats cl-stats6"},
      ui.stat("거래", `${fmt.int(a.trades)}번`, a.trades < 30 ? "30번 전: 아직 판단 안 함" : `승 ${fmt.int(a.wins)} · 패 ${fmt.int(a.trades - a.wins)}`),
      ui.stat("승률", LK.winTxt(a)),
      ui.stat("한 번 평균", LK.ret(a.mean_ret, {hiddenIf: LK.dsHidden(a)}), "닫힌 거래마다 직전 지갑 대비"),
      ui.stat("잔고", LK.wallet(a), a.wallet != null ? fmt.pct(LK.walletChange(a), true, 1) + " (시작 $5,000)" : null),
      ui.stat("최대 낙폭", LK.ddTxt(a), "닫힌 거래 기준"),
      ui.stat(a.role === "cand" ? "기준" : "지금 포지션", a.role === "cand" ? h("span", null, LK.verdictPill(j), " ", LK.bandMark(j) || "")
        : a.open ? h("span", {class: ["side", a.open.side > 0 ? "long" : "short"]}, `${coinShort(coinOf(a.open.symbol))} ${sideKo(a.open.side)}`) : "없음")));
    put(five, LK.fiveRows(set));
    put(split, LK.sideSplit(((d.watch || {}).picks || {})[c.id], {hidden: LK.dsHidden(c)}),
      LK.pairedBox((((d.watch || {}).picks || {})[c.id] || {}).paired, {hidden: LK.dsHidden(c)}));
    put(params, c.role === "cand" ? ui.card({plate: "커스텀값", sub: `${c.name} · ${tfKo(c.tf)} · 색 글씨 = 기본값에서 바뀐 값 · 범위 끝 = 탐색한 가장 끝 값`},
      h("div", {class: "cl-pickgrid"}, h("div", {class: "stack tight"}, paramTable(c, set.base, meta),
        h("div", {class: "cl-exits"}, h("div", null, LK.roleChip("cand"), h("b", null, c.exit_ko)),
          h("div", null, LK.roleChip("base"), h("span", null, set.base ? set.base.exit_ko : "—")))),
      originBox(c, meta))) : null);
    if (seen === d.done_ms) return;
    seen = d.done_ms;
    const ids = ROLES.map((r) => set[r]).filter(Boolean);
    const books = await Promise.all(ids.map((x) => ctx.api(`/api/trades/${encodeURIComponent(x.id)}`).catch(() => null)));
    if (!ctx.alive()) return;
    const series = ids.map((x, i) => ({role: x.role, label: ROLE_KO[x.role], points: books[i] && books[i].equity})).filter((x) => x.points);
    put(chart, series.length ? LK.equityLines(series, {label: `${LK.pickKo(c, meta)} 계좌 5개 잔고`, until: d.done_ms})
      : ui.empty(a.kind === "ds" ? "딥시크 금액 숨김 설정이라 잔고 그래프가 없습니다" : "아직 끝난 거래가 없습니다"));
    const mine = books[ids.findIndex((x) => x.id === a.id)];
    put(trades, tradeTable((mine && mine.trades) || [], a));
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
  ], rows, {cls: "lv-dense"});
}
