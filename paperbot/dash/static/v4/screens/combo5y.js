// #/combo5y: 5년 조합 시험 on its own page (the same cards the #/combo screen shows, from ./combo-5y.js). Read-only, the
// committed 5-year results (GET /api/v4/combo5y); a link to 분석 › 조합 시너지 for the live-run combinations.
import {h, ui} from "../core/pb.js";
import {render5y} from "./combo-5y.js";

export async function mount(el, ctx) {
  ctx.setTitle("5년 조합 시험");
  const body = h("div", {class: "c5-page"});
  el.append(ui.screenHead("5년 조합 시험", "36개 매매법을 묶었다면 · 지난 5년 과거 계산 · 설명용, 판정 아님"),
    h("p", {class: "note c5-links"}, "지금 실험(모의 계좌)으로 본 조합은 ",
      h("a", {href: ctx.href("analysis", "synergy")}, "분석 › 조합 시너지 →"), " · 매매법마다 한 달 수익률 분포는 ",
      h("a", {href: ctx.href("analysis", "monthly5y")}, "분석 › 5년 월별 →")),
    body);
  await render5y(ctx, body);
}

export function unmount() {}
