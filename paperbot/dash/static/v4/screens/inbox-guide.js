// 홈 · 결재함 안내 카드 (review addition 8: "10/26부터 첫 결정 때까지 홈에 안내 카드 한 장"). From 00:00 KST of the day
// before the observation period ends (no copy proposals before it) until the owners' first approve / reject click, or until they
// close it on this device: what will come, the three things to judge, what happens when they do nothing, and a button
// to the 결재함. Dates come from /api/v4/approvals `period` (the run's start + 21 days, the runner's own floor when later;
// the owners' OK period of at least 60 days); nothing is typed in. A failed load shows nothing (no claim either way).
import {h, ui, fmt, local} from "../core/pb.js";

const DAY = 86400000;
export const GUIDE_KEY = "inbox-guide-done";

/** Show the card now? (pure) p: /api/v4/approvals period. */
export function guideShows(p, now, dismissed) {
  if (dismissed || !p || p.start == null || p.observe_until == null) return false;
  if (p.first_owner_decision_ts) return false;                          // the owners decided once: they know the way
  if (p.owner_ok_until && now >= p.owner_ok_until) return false;        // past the owners' OK period
  // from 00:00 KST of the day before the first day proposals can come (10/27 11:46 -> from 10/26 00:00, not 10/26 11:46)
  return now >= fmt.kstMidnight(p.observe_until) - DAY;
}

export function inboxGuide(ctx) {
  const el = h("section", {class: "card ibx-guide", hidden: true, "aria-label": "결재함 안내"});
  if (local.get(GUIDE_KEY, 0)) return el;
  // weeks before the card can show (the shared summary already says when the observation period ends; its date is
  // never later than the 결재함's), the home page does not ask the 결재함 at all
  const s = ctx.store.get("summary");
  if (s && s.observe_until && Math.max(s.now || 0, Date.now()) < fmt.kstMidnight(s.observe_until) - DAY) return el;
  ctx.api("/api/v4/approvals").then((d) => {
    const p = d && d.period;
    if (!ctx.alive() || !guideShows(p, (d && d.now) || Date.now(), local.get(GUIDE_KEY, 0))) return;
    const started = (d.now || Date.now()) >= p.observe_until;
    const n = (d.waiting || []).length;
    el.replaceChildren(
      h("div", {class: "card-h"}, ui.plate("결재함 안내"), n ? ui.pill(`기다리는 제안 ${fmt.int(n)}건`, "accent") : null),
      h("h2", null, started ? "복제 계좌 제안이 오기 시작했습니다" : `${fmt.kst(p.observe_until)}부터 복제 계좌 제안이 옵니다`),
      h("p", null, "직원들이 5년 시험을 통과한 규칙 하나를 바꾼 ", h("b", null, "복제 계좌"), "(원본은 그대로, 새 모의 계좌 1개)를 제안하면 위쪽 종에 숫자가 뜨고 텔레그램으로 한 번 알립니다. ",
        p.owner_ok_until ? [h("b", null, `${fmt.kst(p.owner_ok_until)}까지`), "는 두 분이 승인해야만 계좌가 시작됩니다."] : null),
      h("p", null, h("b", null, "판단할 것 세 가지")),
      h("ol", null,
        h("li", null, "5년 시험 세 기간 모두에서 바꾼 것이 원본보다 나았나 (한 기간만 좋으면 우연일 수 있음)"),
        h("li", null, "반론 검토관이 무엇을 걱정했나 (찬성·반대 한 줄씩 결재함에 있음)"),
        h("li", null, "거래 수가 넉넉했나, 원본은 그대로 두고 작은 새 계좌로 확인해 볼 만한가")),
      h("p", null, "안 누르면 대기로 남고 아무 계좌도 시작되지 않습니다. 승인한 계좌는 시작하고 30일이 지난 뒤의 판정 날에 따로 판정합니다."),
      h("div", {class: "row wrap"}, h("a", {class: "btn-y", href: ctx.href("inbox")}, "결재함 열기 →"),
        h("button", {class: "btn-line", type: "button", onclick: () => { local.set(GUIDE_KEY, 1); el.hidden = true; }}, "알겠습니다 (닫기)")));
    el.hidden = false;
  }).catch(() => { /* not shown: the 결재함 itself says what failed */ });
  return el;
}
