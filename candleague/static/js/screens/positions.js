// #/positions 포지션: every open league position (190 accounts), with its account, role, coin, side, entry, the price
// move since (live), stop and take-profit and the entry time; filters 계좌 종류 and 코인; summary of long / short counts per
// coin. A row opens the terminal on that account. Data: the shared snapshot + /api/live every 10 s.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {COINS, ROLES, ROLE_KO, sideKo, coinOf, coinShort} from "../labels.js";

const priceDec = (p) => { const a = Math.abs(Number(p) || 0); return a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1; };
const px = (p) => (fmt.bad(p) ? "—" : fmt.num(p, priceDec(p)));

export async function mount(el, ctx) {
  try { await ctx.meta(); } catch (e) { /* codes */ }
  const st = {role: "all", coin: "all", live: null};
  const sum = h("div"), table = h("div");
  el.append(
    ui.screenHead("포지션", "지금 열려 있는 후보 리그 포지션 (190계좌) · 줄을 누르면 터미널"),
    h("div", {class: "dl-fields"},
      ui.field("계좌", ui.seg([{id: "all", label: "전체"}, ...ROLES.map((r) => ({id: r, label: ROLE_KO[r]}))], st.role, (v) => { st.role = v; paint(); }, {label: "계좌"})),
      ui.field("코인", ui.seg([{id: "all", label: "전체"}, ...COINS.map((c) => ({id: c, label: coinShort(c)}))], st.coin, (v) => { st.coin = v; paint(); }, {label: "코인"}))),
    ui.card({plate: "코인별", sub: "롱 · 숏 수 (모든 계좌)"}, sum),
    ui.card({plate: "열린 포지션", sub: "가격 변화 = 진입가에서 지금 가격까지 (방향 반영, 레버리지 전)"}, table));
  const live = (c) => (st.live && st.live.coins ? st.live.coins.find((x) => x.coin === c) : null);
  function paint() {
    const d = LK.league();
    if (!d || !d.accounts) { put(table, ui.none("준비 중")); return; }
    const ix = LK.index(d);
    const open = d.accounts.filter((a) => a.open);
    // the 후보 accounts on the same coin and side at once move together: the pool's result rests on fewer bets
    const cands = open.filter((a) => a.role === "cand");
    const crowd = {};
    for (const a of cands) { const k = `${coinShort(coinOf(a.open.symbol))} ${sideKo(a.open.side)}`; crowd[k] = (crowd[k] || 0) + 1; }
    const top = Object.entries(crowd).sort((x, y) => y[1] - x[1]).slice(0, 3);
    put(sum, h("div", {class: "cl-coinsum"}, COINS.map((c) => {
      const rows = open.filter((a) => coinOf(a.open.symbol) === c);
      return h("div", {class: "cl-coinbox"}, h("b", null, coinShort(c)), h("span", {class: "num"}, `${rows.length}개`),
        h("span", {class: "side long"}, `롱 ${rows.filter((a) => a.open.side > 0).length}`), h("span", {class: "side short"}, `숏 ${rows.filter((a) => a.open.side < 0).length}`));
    })), h("p", {class: "note"}, top.length
      ? `후보 계좌 ${fmt.int(ix.cands.length)}개 중 ${fmt.int(cands.length)}개가 포지션 보유 · 가장 많이 겹친 곳: ${top.map(([k, n]) => `${k} ${n}개`).join(" · ")}. ` +
        "같은 코인 · 같은 방향의 후보는 함께 벌고 함께 잃어서, 묶음 결과가 생각보다 적은 수의 시장 움직임에 기대게 됩니다."
      : "지금 포지션을 가진 후보 계좌가 없습니다."));
    const rows = open.filter((a) => (st.role === "all" || a.role === st.role) && (st.coin === "all" || coinOf(a.open.symbol) === st.coin))
      .sort((a, b) => b.open.since - a.open.since);
    if (!rows.length) { put(table, ui.empty("조건에 맞는 열린 포지션이 없습니다")); return; }
    put(table, ui.table([
      {label: "계좌", l: true, get: (a) => h("span", null, LK.pickName(LK.pickOf(a, ix) || a, {code: false}), " ", LK.roleChip(a.role))},
      {label: "코인", l: true, get: (a) => h("b", null, coinShort(coinOf(a.open.symbol)))},
      {label: "방향", l: true, get: (a) => h("span", {class: ["side", a.open.side > 0 ? "long" : "short"]}, sideKo(a.open.side))},
      {label: "진입가", get: (a) => (a.open.entry == null ? h("span", {class: "muted"}, "숨김") : px(a.open.entry))},
      {label: "지금 가격", get: (a) => { const r = live(coinOf(a.open.symbol)); return r ? px(r.price) : "—"; }},
      {label: "가격 변화", get: (a) => {
        const r = live(coinOf(a.open.symbol));
        const m = a.open.entry != null && r && r.price != null ? a.open.side * (r.price / a.open.entry - 1) * 100 : null;
        return m == null ? "—" : h("span", {class: ["num", fmt.tone(m)]}, fmt.pct(m, true, 2));
      }},
      {label: "손절", get: (a) => (LK.dsHidden(a) ? h("span", {class: "muted"}, "숨김") : a.open.stop == null ? "—" : px(a.open.stop))},
      {label: "익절", get: (a) => (LK.dsHidden(a) ? h("span", {class: "muted"}, "숨김") : a.open.tp == null ? h("span", {class: "muted"}, "계단 잠금") : px(a.open.tp))},
      {label: "진입 (KST)", get: (a) => h("span", {class: "num muted"}, fmt.kst(a.open.since))},
      {label: "보유", get: (a) => h("span", {class: "num muted"}, fmt.dur((Date.now() - a.open.since) / 1000))},
    ], rows, {cls: "lv-dense", onRow: (a) => { location.hash = `#/terminal?acct=${encodeURIComponent(a.id)}&coin=${coinOf(a.open.symbol)}`; }}));
  }
  async function pollLive() { try { st.live = await ctx.api("/api/live"); } catch (e) { return; } paint(); }
  ctx.onLeague(paint);
  await pollLive();
  ctx.every(10000, pollLive);
}
