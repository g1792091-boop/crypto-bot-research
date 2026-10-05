// 분석 › 그림자 비교 › 진입 가격 차이 (ana8B): /api/v4/drift (dash/more/drift.py). How far the price the paper fill
// used (ask for a long, bid for a short, read when the signal was ready) was from the signal bar's close, in bp (0.01%),
// per group and timeframe, by the delay after the bar closed; a strategy group minus the same timeframe's coin flips.
// The 5-year tests assumed next open + 0.02% (2 bp); a median over 3 bp (1.5x) gets a neutral '가정보다 큼' mark.
// HONESTY: descriptive (no pass/fail words), counts and bp only, small samples say so; nothing sent → 아직 없음;
// the '동전 봇 빼면' column is a coin-flip comparison, so the card carries ui.refNote (참고).
import {h, put, ui, fmt, motion} from "../core/pb.js";

const bp = (x, sign = true) => (x == null ? "—" : `${fmt.num(x, 1, sign)}bp`);

function table(D, g) {
  const tfs = (D.groups[g] || {}).timeframes || {};
  const order = (D.tf_order || []).filter((tf) => tfs[tf]);
  if (!order.length) return null;
  return ui.table([
    {label: "봉", l: true, get: (tf) => fmt.tfKo(tf)},
    {label: "신호", get: (tf) => [fmt.int(tfs[tf].n), " ", ui.smallSample(tfs[tf].n, D.small_n || 20)]},
    {label: "중앙값", get: (tf) => [h("b", {class: "num"}, bp(tfs[tf].median)), tfs[tf].over ? [" ", ui.pill("가정보다 큼", "warn", `중앙값이 ${bp(D.flag_bps, false)}(가정의 1.5배)를 넘음`)] : null]},
    {label: "90%", get: (tf) => bp(tfs[tf].p90)},
    {label: "동전 봇 빼면", get: (tf) => (g === "flip" ? "기준" : bp(tfs[tf].minus_flip))},
  ], order);
}

function delays(D, g) {
  const tfs = (D.groups[g] || {}).timeframes || {};
  const rows = [];
  for (const tf of D.tf_order || []) {
    const t = tfs[tf];
    if (!t) continue;
    for (const b of D.buckets || []) {
      const c = (t.by_delay || {})[b.key];
      if (c && c.n) rows.push({tf, b: b.ko, c});
    }
  }
  if (!rows.length) return null;
  return ui.disclosure("늦게 들어간 정도별 보기", ui.table([
    {label: "봉", l: true, get: (r) => fmt.tfKo(r.tf)}, {label: "봉 닫힌 뒤", l: true, get: (r) => r.b},
    {label: "신호", get: (r) => fmt.int(r.c.n)}, {label: "중앙값", get: (r) => bp(r.c.median)}, {label: "90%", get: (r) => bp(r.c.p90)},
  ], rows.slice(0, 20)));
}

/** The card: fetches /api/v4/drift itself (env.ctx.api), shimmer while in flight, 아직 없음 when nothing yet. */
export function driftCard(env) {
  const body = h("div", {class: "stack tight"}, motion.shimmer(3));
  const card = ui.card({plate: "진입 가격 차이", sub: "신호 봉 종가 vs 체결 기준 가격"}, body);
  let pick = null;
  const paint = (D) => {
    if (D.error) { put(body, h("p", {class: "muted"}, String(D.error))); return; }
    D.groups = D.groups || {};
    const order = (D.order || []).filter((g) => ((D.groups[g] || {}).all || {}).n);
    if (!order.length) {
      put(body, h("p", {class: "muted"}, "아직 없음 · 신호가 쌓이면 바로 나옵니다 (15분봉·동전 봇은 첫날부터, 4시간봉은 한 주쯤)."),
        h("p", {class: "an-note"}, D.note || ""));
      return;
    }
    const cur = pick && order.includes(pick) ? pick : order[0];
    const slot = h("div", {class: "stack tight"});
    const seg = ui.seg(order.map((g) => ({id: g, label: (D.group_ko || {})[g] || g})), cur, (id) => { pick = id; draw(id, true); }, {label: "묶음", scroll: true});
    function draw(g, anim) {
      const a = (D.groups[g] || {}).all || {};
      put(slot, h("p", null, `${(D.group_ko || {})[g] || g} 신호 ${fmt.int(a.n || 0)}개: 중앙값 `, h("b", {class: "num"}, bp(a.median)), ` · 90% ${bp(a.p90)} · 가정 ${bp(D.assumed_bps, false)}`),
        table(D, g), delays(D, g));
      if (anim) motion.swap(slot);
    }
    draw(cur, false);
    put(body, h("p", {class: "an-read"}, h("b", null, "읽는 법 "), "플러스 = 신호 봉 종가보다 불리하게 들어감 (롱은 비싸게, 숏은 싸게). 동전 봇은 같은 봉에서 뽑으니 '동전 봇 빼면' = 매매법만의 차이."),
      seg, slot, h("p", {class: "an-note"}, D.note || "", ` · ${D.label || "설명용, 판정 아님"}`),
      ui.refNote(env.verdictTs));         // a comparison with the coin flips: 참고 until the verdict (CONTRACT §1.3)
  };
  env.ctx.api("/api/v4/drift").then((D) => { if (env.ctx.alive()) paint(D || {}); })
    .catch(() => { if (env.ctx.alive()) put(body, h("p", {class: "muted"}, "불러오지 못했습니다. 화면을 다시 열면 다시 시도합니다.")); });
  return card;
}
