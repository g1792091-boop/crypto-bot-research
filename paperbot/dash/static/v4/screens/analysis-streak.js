// 분석 › 손익비·위험 › 연패 맥락 (ana8B): /api/analysis/risk .streaks (dash/more/streaks.py). Per group: the longest
// losing run so far and the one going on now, with the chance that this many trades at this win rate hold a run that
// long somewhere (Schilling 1990, exact), the chance some account of the group does, and the coin flips' longest runs
// as the band. HONESTY: counts and rates only for every group (DeepSeek never priced); descriptive, no verdict.
import {h, ui, fmt} from "../core/pb.js";
import {acctLabel} from "./analysis-kit.js";

const chance = (p) => (p == null ? "—" : p < 0.001 ? "0.1% 미만" : fmt.pct(p, p < 0.1 ? 1 : 0, false));

function groupRow(g, c, ko, min, ctx) {
  const top = (c.top || [])[0];
  const b = c.flip_band;
  if (!top || !top.longest) {
    return h("div", {class: "lrow an-row", role: "listitem"}, h("span", {class: "rk"}, ko),
      h("span", {class: "lname muted"}, c.with_trades ? "아직 연패 없음" : `아직 없음 · 계좌마다 끝난 거래 ${fmt.int(min)}건 쌓이면 볼 만함`),
      b ? h("span", {class: "meta"}, h("span", null, `${c.flip_band_ko || "동전 봇"} 가장 긴 연패 ${fmt.int(b.min)}~${fmt.int(b.max)}번 (중앙 ${fmt.num(b.median, 1)})`)) : null);
  }
  const now = c.now;
  return h("div", {class: "lrow an-row", role: "listitem"},
    h("span", {class: "rk"}, ko),
    top.account_id ? h("a", {class: "lname", href: ctx.href("account", top.account_id), title: top.account_id}, acctLabel(top.account_id))
      : h("span", {class: "lname"}, `${ko} 한 계좌 `, ui.pill("묶음만", "ref")),        // DeepSeek: group level only
    h("span", {class: "ret num"}, `${fmt.int(top.longest)}연패`),
    h("span", {class: "meta"},
      h("span", null, `${fmt.int(top.trades)}건 · 승률 ${fmt.pct(top.win_rate, 0, false)} → 이만한 연패가 나올 확률 ${chance(top.p_longest)}`),
      c.any_account ? h("span", null, `${ko} 계좌 ${fmt.int(c.with_trades)}개 중 어딘가에서 ${fmt.int(c.any_account.k)}연패 이상: ${chance(c.any_account.p)}`) : null,
      now && now.now ? h("span", null, `지금 이어지는 가장 긴 연패 ${fmt.int(now.now)}번 (`, now.account_id ? acctLabel(now.account_id) : "한 계좌", `, 확률 ${chance(now.p_now)})`) : h("span", null, "지금 이어지는 연패 없음"),
      b ? h("span", null, `${c.flip_band_ko || "동전 봇"} 가장 긴 연패 ${fmt.int(b.min)}~${fmt.int(b.max)}번 (중앙 ${fmt.num(b.median, 1)}, ${fmt.int(b.accounts)}개)`) : null,
      ui.smallSample(top.trades, min)));
}

/** The card (null when the server sent no block: an older server). */
export function streakCard(d, env) {
  const S = d && d.streaks;
  if (!S) return null;
  const gs = S.groups || {}, ko = S.group_ko || {}, min = S.min_trades || 20;
  const order = (S.order || Object.keys(gs)).filter((g) => gs[g] && (gs[g].accounts || gs[g].with_trades));
  return ui.card({plate: "연패 맥락", sub: "이 승률이면 흔한가"},
    h("p", {class: "an-read"}, h("b", null, "읽는 법 "), "승률 40%로 100번 거래하면 9연패가 나올 확률은 셋 중 하나 꼴입니다. 확률이 높으면 그 승률에서 흔한 연패, 낮으면 드문 연패입니다. 동전 봇의 가장 긴 연패가 비교 기준입니다."),
    S.error ? h("p", {class: "an-warn"}, String(S.error)) : null,
    order.length ? h("div", {class: "plist", role: "list"}, order.map((g) => groupRow(g, gs[g], ko[g] || g, min, env.ctx)))
      : h("p", {class: "muted"}, `아직 없음 · 끝난 거래가 계좌마다 ${fmt.int(min)}건 쌓이면 볼 만합니다.`),
    h("p", {class: "an-note"}, S.note || "", " 계산: ", S.cite || "", ". ", S.label || "설명용, 판정 아님"),
    ui.refNote(env.verdictTs));
}
