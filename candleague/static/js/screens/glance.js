// #/glance 한눈 지도: the way in for a beginner. One card per analysis screen with that screen's own one-line answer from the snapshot
// (decision.summary_ko, risk.headline_ko, ...), a button to it, and the order to look in. It computes nothing: every sentence is the
// server's, a block that is not there yet reads "아직 기록이 없습니다".
import {h, put} from "../dom.js";
import * as ui from "../ui.js";

export const css = ["scr/kinds.css"];

const ORDER = [["home", "요약", "계좌 종류와 일정, 판정 한 줄"], ["decision", "판정", "미리 정한 규칙의 답 (28일째 한 번)"],
  ["risk", "위험 점검", "포지션이 한쪽으로 몰렸는지, 가장 나빴던 일"], ["monthsim", "한 달 시뮬", "지금 성적이 한 달 이어지면, 동전과 비교"],
  ["versus", "메인 vs 대조", "새 청산 구조가 원래 방식보다 나은지"]];

/** [screen id, title, the snapshot's sentence or null] for every analysis screen. */
export function cards(d) {
  const x = d && typeof d === "object" ? d : {};
  const s = (b, k) => (b && typeof b === "object" && typeof b[k] === "string" && b[k] ? b[k] : null);
  const dq = x.dataq && typeof x.dataq === "object" ? [s(x.dataq, "status_ko"), s(x.dataq, "headline_ko")].filter(Boolean).join(" · ") || null : null;
  return [["decision", "판정", s(x.decision, "summary_ko")], ["monthsim", "한 달 시뮬", s(x.monthsim, "headline_ko")],
    ["risk", "위험 점검", s(x.risk, "headline_ko")], ["losses", "손실 해부", s(x.losses, "headline_ko")], ["conditions", "조건별", s(x.conditions, "headline_ko")],
    ["coins", "코인별", s(x.coins, "headline_ko")], ["costs", "실제 비용", s(x.costs, "headline_ko")],
    ["dataq", "데이터 점검", dq], ["timeline", "타임라인", s(x.timeline, "headline_ko")]];
}

export async function mount(el, ctx) {
  el.classList.add("kd");
  const root = h("div", {class: "kd-root"});
  el.append(ui.screenHead("한눈 지도", "어느 화면에서 무엇을 보는지 · 처음이면 이 순서로"), root);
  const order = h("ol", {class: "kd-rules"}, ORDER.map(([id, ko, what]) => h("li", null, h("a", {href: ctx.href(id)}, ko), `: ${what}`)));
  function paint(d) {
    const list = cards(d);
    put(root,
      ui.card({plate: "처음이면 이 순서로", sub: "위에서 아래로 한 번씩 보시면 됩니다"}, order),
      h("div", {class: "kd-glance"}, list.filter(([id, , sent]) => id !== "costs" || sent).map(([id, ko, sent]) =>
        ui.card({plate: ko, sub: "이 화면의 한 줄 답", acts: h("a", {class: "btn-line", href: ctx.href(id)}, `${ko} 보기 →`)},
          h("p", {class: sent ? "dl-vline" : "muted"}, sent || "아직 기록이 없습니다 (거래가 쌓이면 나타납니다)")))),
      h("p", {class: "note"}, "여기 문장은 각 화면이 계산한 그대로이고, 이 화면은 아무것도 새로 계산하지 않습니다. 판정에 쓰는 것은 판정 화면뿐입니다."));
  }
  paint(null);
  ctx.onLeague((d) => paint(d));
}
