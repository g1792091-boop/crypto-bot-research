// 분석 › 들고 있었다면 (ana7a): GET /api/v4/holdcmp?group= (dash/more/holdcmp.py). Per group since the run start:
//   한눈에          the group's realized return, the same trades the other way round (반대로, a rough mirror), the
//                   group's coin flips, and an equal-weight basket of the six coins simply held (1x, no fees)
//   곡선            the four as thin lines over time (hourly points)
//   코인별          each coin's price change since the run start (market data) and how often the group traded it
// HONESTY: the mirror is rough (other stops and lock steps would have changed the exits) and says so; the accounts
// trade at 20-50x while holding is 1x; DeepSeek shows no return, mirror or curve (counts and win shares only), the
// coins' price changes stay (market data). Money numbers carry assume(); coin flips are 참고 with refNote.
import {h, ui, fmt} from "../core/pb.js";
import {viewHead, groupWords, waitCard} from "./analysis-kit.js";
import {pc, sp, divBar, when, noMoneyLine} from "./analysis-a7kit.js";

const SERIES = {core: "core", ds200: "ds", reel: "m5"};

function tile(label, value, sub, tone, cls) {
  return h("div", {class: ["a7-tile", cls]}, h("span", {class: "a7-tk"}, label),
    h("b", {class: ["a7-tv", "num", tone || ""]}, value), sub ? h("small", null, sub) : null);
}

export function holdcmp(d, env) {
  const grp = d.group || env.group || "core", W = groupWords(grp), money = !d.no_money && W.money;
  const m = d.mine || {}, f = d.coin_flips || {}, hold = d.hold || {};
  const out = [viewHead({plate: "들고 있었다면", q: "매매하지 않고 코인을 들고만 있었다면, 거꾸로 했다면",
    meta: [d.since ? `실험 시작 ${when(d.since)}부터` : null, d.accounts != null ? `${W.who} 계좌 ${fmt.int(d.accounts)}개` : null,
      `끝난 거래 ${fmt.int(m.trades || 0)}건`].filter(Boolean).join(" · "), at: d.computed_at, stale: d.stale,
    read: money
      ? `묶음 수익률 = 끝난 거래 손익 합 ÷ 시작 돈 합 (계좌 ${fmt.int(d.accounts || 0)}개 × ${fmt.int(d.initial || 5000)}). 들고 있기 = 실험 시작 때 코인 6개를 같은 돈으로 1배로 사서 지금까지 (수수료·펀딩 없음). 반대로 = 계좌마다 거꾸로 계좌를 하나씩 따로 굴린 것: 끝난 거래마다 같은 때 들어가고 나와서 방향만 거꾸로, 크기는 그때 거꾸로 계좌가 가진 돈에 맞춰서 (진짜 계좌와 같은 비율), 돈이 파산선 아래로 떨어지면 거기서 멈춤.`
      : "들고 있기 = 실험 시작 때 코인 6개를 같은 돈으로 1배로 사서 지금까지 (수수료·펀딩 없음). 반대로 = 끝난 거래마다 같은 때 들어가고 나와서 방향만 거꾸로 했을 때 이긴 비율.",
    warn: [!money ? noMoneyLine() : null,
      h("p", {class: "an-warn"}, ui.pill("대충 계산", "ref"), " 반대로는 대충입니다: 반대로 들어갔다면 손절·익절 자리가 달라서 실제로는 다른 때 나갔을 겁니다. 수수료는 거꾸로 한 거래도 똑같이 내고(양쪽 다 뺌), 펀딩은 반대로 셉니다. 한 거래에서 증거금보다 더 잃지는 않게 했습니다."),
      money ? h("p", {class: "an-read"}, "계좌는 20~50배로 매매하고 들고 있기는 1배라서, 크기를 바로 견줄 수는 없습니다. 방향과 흐름을 보는 용도입니다.") : null]})];
  if (d.error) { out.push(ui.card({plate: "들고 있었다면"}, h("p", {class: "muted"}, String(d.error)))); return out; }

  // ---- 한눈에
  const basket = hold.basket_chg;
  const tiles = [];
  if (money) {
    const none = (x) => (x.trades ? null : "아직 끝난 거래 없음");
    tiles.push(tile(`${W.short} (끝난 거래)`, sp(m.ret, 2), none(m) || `이긴 비율 ${pc(m.wr)}`, fmt.tone(m.ret), "me"));
    const mb = (m.mirror || {}).busts || 0;
    tiles.push(tile("반대로 했다면", sp((m.mirror || {}).mirror_ret, 2),
      none(m) || `이긴 비율 ${pc((m.mirror || {}).wr)} · 대충${mb ? ` · 파산했을 계좌 ${fmt.int(mb)}개` : ""}`, fmt.tone((m.mirror || {}).mirror_ret), "mir"));
    tiles.push(tile(`${W.flips} (참고)`, sp(f.ret, 2), none(f) || `이긴 비율 ${pc(f.wr)}`, fmt.tone(f.ret), "flip"));
  } else {
    tiles.push(tile(`${W.short} 이긴 비율`, pc(m.wr), `끝난 거래 ${fmt.int(m.trades || 0)}건 · 수익률은 딥시크 화면에서`, "", "me"));
    tiles.push(tile("반대로 했다면 이긴 비율", pc((m.mirror || {}).wr), "대충 계산", "", "mir"));
    tiles.push(tile(`${W.flips} 이긴 비율 (참고)`, pc(f.wr), `끝난 거래 ${fmt.int(f.trades || 0)}건`, "", "flip"));
  }
  tiles.push(tile("코인 6개 그냥 들고 있기", sp(basket, 2), `같은 돈씩 · 1배 · ${fmt.int(hold.known || 0)}개 시세`, fmt.tone(basket), "bas"));
  const waitNote = d.waiting
    ? waitCard("들고 있었다면", [{label: `${W.short} 끝난 거래 ${fmt.int(d.min_trades || 20)}건부터 비교가 의미 있어요`,
      share: Math.min(1, (m.trades || 0) / (d.min_trades || 20)), words: `지금 ${fmt.int(m.trades || 0)}건 · 들고 있기 숫자는 시세라서 지금도 볼 수 있습니다`}], null)
    : null;
  out.push(ui.card({plate: "한눈에", sub: `실험 시작부터 지금까지 · ${when(d.now)} 기준`},
    h("div", {class: "a7-tiles"}, tiles),
    money ? h("p", {class: "an-note"}, "묶음·반대로·동전 봇은 끝난 거래만 (열린 포지션 빼고). 들고 있기는 지금 시세까지.") : null,
    ui.refNote(env.verdictTs), money ? ui.assume() : null));
  if (waitNote) out.push(waitNote);

  // ---- 곡선
  const hc = d.hold_curve || {}, cv = d.curve || {};
  const n = (hc.t || []).length;
  const series = [];
  if (money && cv.group && m.trades) {         // no closed trade yet: no line (never a flat zero)
    series.push({values: cv.group, cls: `a7-l-${SERIES[grp] || "core"}`, label: W.short});
    series.push({values: cv.mirror, cls: "a7-l-mir", label: "반대로"});
  }
  if (money && cv.flips && f.trades) series.push({values: cv.flips, cls: "lc", label: W.flips});
  series.push({values: hc.basket || [], cls: "a7-l-bas", label: "들고 있기"});
  const xl = n ? [fmt.mmdd(hc.t[0]), "", fmt.kst(hc.t[n - 1])] : [];
  const legend = h("div", {class: "a7-legend2"}, series.map((s) => h("span", null, h("i", {class: ["a7-sw", s.cls]}), s.label)));
  out.push(ui.card({plate: "곡선", sub: money ? "끝난 거래 누적 수익률 · 바구니는 시세" : "코인 바구니 시세 (딥시크 곡선은 딥시크 화면에서)"},
    legend,
    n >= 3 ? ui.curves({series, base: 0, height: 170, xlabels: xl, yfmt: (v) => fmt.pct(v, 1, true), label: "수익률 곡선"})
      : h("p", {class: "muted"}, "곡선은 점이 3개 이상 쌓이면 그립니다 (한 시간에 한 점)."),
    money ? ui.assume() : null));

  // ---- 코인별
  const coins = hold.coins || [];
  const top = Math.max(0.02, ...coins.map((c) => Math.abs(c.chg || 0)));
  out.push(ui.card({plate: "코인별 그냥 들고 있기", sub: "실험 시작 가격 → 지금 가격 (1배)"},
    h("div", {class: "a7-rows", role: "list"}, coins.map((c) => h("div", {class: "a7-row coin", role: "listitem"},
      h("span", {class: "a7-k"}, h("b", null, fmt.coin(c.symbol)), h("small", null, `${W.short} 거래 ${fmt.int(c.traded || 0)}건`)),
      h("span", {class: "a7-bar"}, divBar(c.chg, top, c.chg == null ? "flat" : c.chg >= 0 ? "up" : "down", `${fmt.coin(c.symbol)} ${sp(c.chg, 2)}`)),
      h("span", {class: "a7-v"}, h("b", {class: ["num", fmt.tone(c.chg)]}, c.chg == null ? "시세 없음" : sp(c.chg, 2)),
        h("small", {class: "num"}, c.p0 != null && c.p1 != null ? `${fmt.price(c.p0)} → ${fmt.price(c.p1)}` : "—"))))),
    h("p", {class: "an-note"}, (hold.price_source || []).includes("frames")
      ? "가격: 시장 기록기의 5분봉, 없는 코인은 1시간봉 (첫 가격 = 시작 직전 정시 종가)." : "가격: 시장 기록기의 5분봉 (첫 가격 = 실험 시작 뒤 첫 5분봉 시가).")));
  out.push(h("p", {class: "an-note an-foot"}, `들고 있었다면: ${W.who} · 실험 시작부터 · ${d.label || "설명용, 판정 아님"}`));
  return out;
}
