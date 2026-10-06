// 분석 › 청산 이유 (ana-syn): GET /api/v4/exits?group= (dash/more/exits.py). Per group (기존 36 / 딥시크 / 5분봉, the
// analysis.js 묶음 switch) against its own coin flips:
//   어떻게 끝났나   each exit reason that really occurs (손절, each profit-lock step, 목표가, 시간 청산, 강제청산, ...): share of
//                  trades as bars (group vs coin flips), then trades, win share and mean net ROE per reason
//   역행·순행       winners and losers: how far price went against the entry before the exit, as a share of the first stop
//                  distance; losers: the best move they had seen, in R (R = the first stop distance)
// One plain line under each chart says what it shows (no advice, no verdict). A part with too few trades is a filling
// bar with its real threshold. HONESTY: DeepSeek (d.no_money) shows counts and shares only (no ROE, no R size); coin flips
// are 참고 with refNote.
import {h, ui, fmt} from "../core/pb.js";
import {viewHead, groupWords, waitCard, progressBar} from "./analysis-kit.js";

const pc = (x, d = 0) => (x == null ? "—" : fmt.pct(x, d, false));
/** A share for a bar's label: one decimal under 10% (0 stays "0%"). */
const pv = (x) => (x == null ? "—" : fmt.pct(x, x > 0 && x < 0.1 ? 1 : 0, false));
const SERIES = {core: "core", ds200: "ds", reel: "m5"};

/** A legend: the group's colour and the coin flips' colour, with their trade counts. */
function legend(grp, W, n, fn) {
  return h("div", {class: "ax-legend"},
    h("span", null, h("i", {class: ["ax-sw", SERIES[grp] || "core"]}), `${W.short} (${fmt.int(n)}건)`),
    h("span", null, h("i", {class: "ax-sw flip"}), `${W.flips} (${fmt.int(fn)}건, 참고)`));
}

/** Rows of two thin bars (group, coin flips) on one 0..max scale, the values on the right. rows: [{label, a, b, an, bn}];
 *  short: bucket labels that stay beside the bars on a phone too. */
function dualBars(rows, grp, W, aria, short = false) {
  const top = Math.max(0.0001, ...rows.map((r) => Math.max(r.a || 0, r.b || 0)));
  const w = (x) => `${((x || 0) / top * 100).toFixed(1)}%`;
  return h("div", {class: ["ax-dual", short ? "short" : ""], role: "list", "aria-label": aria},
    rows.map((r) => {
      const say = `${r.label}: ${W.short} ${pc(r.a, 1)}${r.an != null ? ` (${fmt.int(r.an)}건)` : ""} · ${W.flips} ${pc(r.b, 1)}${r.bn != null ? ` (${fmt.int(r.bn)}건)` : ""}`;
      return h("div", {class: "ax-row", role: "listitem", title: say, "aria-label": say},
        h("span", {class: "ax-k"}, r.label),
        h("span", {class: "ax-bars", "aria-hidden": "true"},          // a zero share draws no bar (not a stub)
          h("i", {class: ["ax-b", SERIES[grp] || "core", r.a ? "" : "z"], style: {"--w": w(r.a)}}),
          h("i", {class: ["ax-b", "flip", r.b ? "" : "z"], style: {"--w": w(r.b)}})),
        h("span", {class: "ax-v"}, h("b", {class: "num"}, pv(r.a)), h("small", {class: "num"}, pv(r.b))));
    }));
}

/** A table cell: the group's value, the coin flips' under it (small). */
const sub = (x, y) => h("span", {class: "ax-two"}, h("span", {class: "num"}, x), h("small", {class: "num muted"}, y));

// ---------------------------------------------------------------- 청산 이유 (/api/v4/exits)
export function exits(d, env) {
  const grp = d.group || env.group || "core", W = groupWords(grp), money = !d.no_money && W.money;
  const n = d.trades || 0, fn = d.flip_trades || 0, min = d.min_trades || 20;
  const out = [viewHead({plate: "청산 이유", q: "거래는 어떻게 끝났고, 끝나기 전에 얼마나 밀렸나",
    meta: `${W.who} 끝난 거래 ${fmt.int(n)}건 · ${W.flips} ${fmt.int(fn)}건 · 실험 시작부터`, at: d.computed_at, stale: d.stale,
    read: d.house_exits === false
      ? "릴스는 자기 규칙으로 나갑니다: 손절(스윙 저점 아래), 목표가(볼린저 윗밴드), 96봉(8시간) 시간 청산. 이유마다 몇 건이었고 그 거래들이 어땠는지 봅니다."
      : "기존 규칙은 2 ATR 손절, 그리고 이익이 나면 손절선을 계단처럼 올려 이익을 잠급니다(+12%에 닿으면 +10% 잠금, 그 뒤 5%씩). 잠금 단계마다, 손절·강제청산마다 몇 건이었고 그 거래들이 어땠는지 봅니다.",
    warn: [!money ? h("p", {class: "an-read"}, ui.pill("돈 숫자 없음", "ref"), " 딥시크는 거래 수와 비율만 봅니다 (평균 ROE와 R 크기도 빼고).") : null]})];
  if (d.error) { out.push(ui.card({plate: "청산 이유"}, h("p", {class: "muted"}, String(d.error)))); return out; }
  if (d.waiting) {
    out.push(waitCard("청산 이유", [{label: `${W.short} 끝난 거래 ${fmt.int(min)}건 필요`, share: Math.min(1, n / min),
      words: `지금 ${fmt.int(n)}건 · ${W.flips} ${fmt.int(fn)}건`}], null));
    return out;
  }
  const rs = d.reasons || [];
  const rows = rs.map((r) => ({label: r.ko, a: (r.group || {}).share, b: (r.coin_flips || {}).share, an: (r.group || {}).trades, bn: (r.coin_flips || {}).trades}));
  const sl = rs.find((r) => r.key === "SL"), locks = rs.filter((r) => String(r.key).startsWith("LOCK"));
  const lockShare = locks.reduce((a, r) => a + ((r.group || {}).share || 0), 0);
  const tp = rs.find((r) => r.key === "TP");
  const say = d.house_exits === false
    ? `끝난 거래 ${fmt.int(n)}건 중 손절 ${pc(sl && sl.group.share)}, 목표가 익절 ${pc(tp && tp.group.share)}였어요.`
    : `끝난 거래 ${fmt.int(n)}건 중 손절이 ${pc(sl && sl.group.share)}, 익절 잠금이 모두 ${pc(lockShare)}였어요.`;
  const cols = [
    {label: "청산 이유", l: true, get: (r) => r.ko, cls: () => "ax-wrap"},
    {label: "거래", get: (r) => sub(`${fmt.int((r.group || {}).trades || 0)}건`, `동전 ${fmt.int((r.coin_flips || {}).trades || 0)}`)},
    {label: "이긴 비율", get: (r) => sub(pc((r.group || {}).win_rate), `동전 ${pc((r.coin_flips || {}).win_rate)}`)},
    money ? {label: "평균 ROE", get: (r) => sub(h("span", {class: fmt.tone((r.group || {}).mean_roe)}, fmt.pct((r.group || {}).mean_roe, 1)), `동전 ${fmt.pct((r.coin_flips || {}).mean_roe, 1)}`)} : null,
  ].filter(Boolean);
  out.push(ui.card({plate: "어떻게 끝났나", sub: `${W.short} vs ${W.flips}`},
    legend(grp, W, n, fn),
    dualBars(rows, grp, W, "청산 이유별 비율"),
    h("p", {class: "ax-say"}, say, ` (${W.flips}: 손절 ${pc(((rs.find((r) => r.key === "SL") || {}).coin_flips || {}).share)})`),
    h("h3", {class: "an-sub"}, "이유별 성적"),
    h("div", {class: "ax-tbl"}, ui.table(cols, rs)),
    h("p", {class: "an-note"}, money ? "ROE = 증거금 대비 손익 (수수료·펀딩 뺀 순). 아래 작은 숫자 = 동전 봇." : "아래 작은 숫자 = 동전 봇.",
      d.busts || d.flip_busts ? ` 이 청산 뒤 계좌가 파산선 아래로 내려간 거래 ${fmt.int(d.busts || 0)}건 (${W.flips} ${fmt.int(d.flip_busts || 0)}건).` : ""),
    ui.refNote(env.verdictTs)));
  out.push(excursionCard(d, grp, W, money, env));
  out.push(h("p", {class: "an-note an-foot"}, `청산 이유: ${W.who} · 실험 시작부터 끝난 거래 · ${d.label || "설명용, 판정 아님"}`));
  return out;
}

// ---------------------------------------------------------------- 역행·순행
function chart(title, part, fpart, key, grp, W, line, wait) {
  const p = part || {}, fp = fpart || {};
  if (wait) {         // too few winners / losers with a recorded stop: the real threshold as a filling bar
    return h("div", {class: "ax-chart an-wait"}, h("h3", {class: "an-sub"}, title),
      progressBar(`${wait.who} ${fmt.int(wait.need)}건부터 그립니다`, `지금 ${fmt.int(p.n || 0)}건 (처음 손절이 기록된 거래)`, Math.min(1, (p.n || 0) / wait.need)));
  }
  const fb = (fp[key] || []);
  const rows = (p[key] || []).map((b, i) => ({label: b.label, a: b.share, b: (fb[i] || {}).share, an: b.n, bn: (fb[i] || {}).n}));
  return h("div", {class: "ax-chart"}, h("h3", {class: "an-sub"}, title), dualBars(rows, grp, W, title, true), h("p", {class: "ax-say"}, line));
}
function excursionCard(d, grp, W, money, env) {
  const ex = d.excursion || {}, g = ex.group || {}, f = ex.coin_flips || {};
  const gw = g.winners || {}, gl = g.losers || {}, fw = f.winners || {}, fl = f.losers || {};
  const min = d.min_side || 10, near = d.near_stop || 0.8;
  const lessW = (gw.n || 0) < min ? {who: "이긴 거래", need: min} : null;
  const lessL = (gl.n || 0) < min ? {who: "진 거래", need: min} : null;
  return ui.card({plate: "역행·순행", sub: "끝나기 전에 얼마나 밀렸고, 얼마나 갔었나"},
    h("p", {class: "an-read"}, h("b", null, "읽는 법 "), "역행 = 들어간 뒤 반대쪽으로 가장 멀리 간 거리를 처음 손절까지 거리로 나눈 비율 (100%면 처음 손절선까지 감). 순행 R = 가장 유리하게 간 거리 ÷ 처음 손절까지 거리 (1R = 손절 거리만큼 이익 쪽으로)."),
    legend(grp, W, (gw.n || 0) + (gl.n || 0), (fw.n || 0) + (fl.n || 0)),
    h("div", {class: "ax-charts"},
      chart("이긴 거래: 손절선 쪽으로 밀린 정도", gw, fw, "mae", grp, W,
        `이긴 거래 ${fmt.int(gw.n || 0)}건 중 ${pc(gw.near_stop)}는 손절선 ${fmt.int(near * 100)}% 가까이 갔다 왔어요. (${W.flips} ${pc(fw.near_stop)})`, lessW),
      chart("진 거래: 손절선 쪽으로 밀린 정도", gl, fl, "mae", grp, W,
        `진 거래 ${fmt.int(gl.n || 0)}건 중 ${pc(gl.deep)}는 처음 손절 거리의 75% 넘게 밀린 뒤 끝났어요. (${W.flips} ${pc(fl.deep)})`, lessL),
      chart("진 거래: 끝나기 전 가장 유리했던 곳 (R)", gl, fl, "mfe", grp, W,
        `진 거래 중 ${pc(gl.one_r)}는 한때 1R(손절 거리만큼) 넘게 이기고 있었어요.` + (money && gl.median_mfe_r != null ? ` 가운데 값은 ${fmt.num(gl.median_mfe_r, 2)}R.` : "") + ` (${W.flips} ${pc(fl.one_r)})`, lessL)),
    g.no_stop ? h("p", {class: "an-note"}, `처음 손절 기록이 없는 거래 ${fmt.int(g.no_stop)}건은 뺐습니다.`) : null,
    h("p", {class: "an-note"}, "가격은 봉의 고가·저가로 잽니다 (봉 안의 순서는 모름). 이긴 = 수수료·펀딩 뺀 손익이 플러스."),
    ui.refNote(env.verdictTs));
}
