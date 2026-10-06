// 분석 › GH Coin 방향 (ana7a): GET /api/v4/ghagree?group= (dash/more/ghagree.py). Shown only while the GH Coin
// recorder runs (features.ghcoin, like the GH Coin tab). Per group: our entries whose coin had a GH Coin call in the 24
// hours before that pointed the SAME way, the OPPOSITE way, or NO call, next to the group's coin flips split the same
// way. Before enough entries with a call: one filling bar. HONESTY: DeepSeek counts and shares only; coin flips 참고;
// GH Coin is a separate recorder that never trades or tells the accounts anything.
import {h, ui, fmt} from "../core/pb.js";
import {viewHead, groupWords, waitCard} from "./analysis-kit.js";
import {cellLine, cmpRows, pc, when, noMoneyLine} from "./analysis-a7kit.js";

const ROWS = [
  {k: "same", ko: "GH Coin과 같은 방향", sub: "예: GH Coin 롱 타점 뒤 우리도 롱"},
  {k: "opposite", ko: "GH Coin과 반대 방향", sub: "예: GH Coin 롱 타점 뒤 우리는 숏"},
  {k: "none", ko: "GH Coin 타점 없음", sub: "진입 전 24시간 안에 그 코인 타점이 없음"},
];

export function ghagree(d, env) {
  const grp = d.group || env.group || "core", W = groupWords(grp), money = !d.no_money && W.money;
  const out = [viewHead({plate: "GH Coin 방향", q: "GH Coin 타점과 같은 방향으로 들어간 거래는 어땠나",
    meta: [d.calls != null ? `GH Coin 타점 ${fmt.int(d.calls)}개 (기록 시작 ${when(d.first_ts)})` : null,
      d.trades != null ? `${W.who} 끝난 거래 ${fmt.int(d.trades)}건 · ${W.flips} ${fmt.int(d.flip_trades || 0)}건` : null].filter(Boolean).join(" · "),
    at: d.computed_at, stale: d.stale,
    read: `진입 전 ${fmt.int(d.lookback_h || 24)}시간 안에 GH Coin이 그 코인에 낸 마지막 타점을 봅니다 (타점은 24시간이 지나면 끝남). 같은 방향 / 반대 방향 / 타점 없음으로 나누고, ${W.flips}도 같은 기준으로 나눠 나란히 둡니다.`,
    warn: [!money ? noMoneyLine() : null,
      h("p", {class: "an-read"}, "GH Coin은 따로 도는 타점 기록기입니다. 계좌는 GH Coin을 읽지 않고, 이 화면도 매매를 바꾸지 않습니다.")]})];
  if (d.error) { out.push(ui.card({plate: "GH Coin 방향"}, h("p", {class: "muted"}, String(d.error)))); return out; }
  if (d.ready === false) {
    out.push(ui.card({plate: "GH Coin 방향"}, h("p", {class: "muted"}, d.why || "GH Coin 타점 기록이 아직 없습니다.")));
    return out;
  }
  const g = d.mine || {}, f = d.coin_flips || {};
  const need = d.min_with_call || 20;
  if (d.waiting) {
    out.push(waitCard("GH Coin 방향", [{label: `GH Coin 타점이 있던 ${W.short} 진입 ${fmt.int(need)}건 필요`, share: Math.min(1, (d.with_call || 0) / need),
      words: `지금 ${fmt.int(d.with_call || 0)}건 (같은 방향 ${fmt.int((g.same || {}).n || 0)} · 반대 ${fmt.int((g.opposite || {}).n || 0)}) · 타점 없던 진입 ${fmt.int((g.none || {}).n || 0)}건`}], null));
  } else {
    out.push(ui.card({plate: "같은 방향 vs 반대", sub: `${W.short} vs ${W.flips}`},
      cmpRows(ROWS.map((r) => ({label: r.ko, sub: r.sub, a: cellLine(g[r.k], !money), b: cellLine(f[r.k], !money)})),
        {k: "GH Coin 타점", a: W.short, b: `${W.flips} (참고)`}),
      h("p", {class: "a7-say"}, `GH Coin 타점이 있던 진입 ${fmt.int(d.with_call || 0)}건 중 같은 방향 ${fmt.int((g.same || {}).n || 0)}건 (이긴 비율 ${pc((g.same || {}).wr)}), 반대 방향 ${fmt.int((g.opposite || {}).n || 0)}건 (${pc((g.opposite || {}).wr)}). ${W.flips}은 같은 방향 ${pc((f.same || {}).wr)} · 반대 ${pc((f.opposite || {}).wr)}.`),
      h("p", {class: "an-note"}, `진입 때 아직 진행 중이던 GH Coin 타점 ${fmt.int(g.open_at_entry || 0)}건.`,
        g.before ? ` GH Coin 기록 시작 전 진입 ${fmt.int(g.before)}건은 뺐습니다.` : "",
        money ? " ROE = 증거금 대비 손익 (수수료·펀딩 뺀 순)." : ""),
      ui.refNote(env.verdictTs), money ? ui.assume() : null));
  }
  out.push(ui.card({plate: "GH Coin 타점 수", sub: "코인별 (기록 시작부터)"},
    h("div", {class: "a7-chips"}, Object.entries(d.per_coin || {}).map(([s, c]) => h("span", {class: "a7-chip"}, h("b", null, fmt.coin(s)), h("span", {class: "num"}, `${fmt.int(c.calls || 0)}개`)))),
    h("p", {class: "an-note"}, "GH Coin 자체 성적(타점마다 R, 동전과 비교)은 ", h("a", {href: env.ctx.href("analysis", "ghcoin")}, "분석 › GH Coin"), "에 있습니다.")));
  out.push(h("p", {class: "an-note an-foot"}, `GH Coin 방향: ${W.who} · 실험 시작부터 끝난 거래 · ${d.label || "설명용, 판정 아님"}`));
  return out;
}
