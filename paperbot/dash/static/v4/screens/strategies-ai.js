// 매매법 상세 › 이 매매법에 대한 AI 의견 (agents-ui): the latest stored lines of this strategy's own agent room
// (GET /api/rooms/strat:<name>/messages): its latest conclusion (the lead's summary or the code's decision line), the
// last three staff turns with their type badges, and a link into the room. Read-only; every line is a stored line
// (text nodes, clamped). A strategy without a room (DeepSeek, the reel: 404) gets no card at all. No money here.
import {h, ui, fmt, store} from "../core/pb.js";
import {SPEAKING, KIND_KO, roleName, hueFor, stripLead} from "./rooms-kit.js";
import {pixAvatar, typeBadges, dayLabel} from "./agents-ui.js";

const firstLine = (t) => stripLead(t).split("\n").map((x) => x.replace(/^\s*(\d+\.|-|↳)\s*/, "").trim()).find(Boolean) || "";

/** The card (a section that stays hidden until the room answers with something to show, or with nothing yet). */
export function aiOpinionCard(ctx, name) {
  const room = `strat:${name}`;
  const body = h("div", {class: "ag-op"}, h("p", {class: "muted"}, "불러오는 중"));
  const card = ui.card({plate: "이 매매법에 대한 AI 의견", sub: "전담 방의 저장된 발언 · AI는 주문하지 않습니다",
    acts: [h("a", {class: "btn-line", href: ctx.href("rooms", room)}, "방 열기 →")], cls: "ag-opcard"}, body);
  card.hidden = true;
  ctx.api(`/api/rooms/${encodeURIComponent(room)}/messages?limit=80`).then((d) => {
    if (!ctx.alive()) return;
    const roles = (store.get("office") || {}).roles || {};
    const ms = (d && d.messages) || [];
    card.hidden = false;
    if (!ms.length) {
      body.replaceChildren(h("p", {class: "ink2"}, "아직 이 매매법 방에서 열린 회의가 없습니다. 손실이 쌓이거나 주간 검토 때 전담 직원이 스스로 회의를 엽니다."));
      return;
    }
    const concl = [...ms].reverse().find((m) => m.kind === "summary" || m.kind === "decision");
    const staff = ms.filter((m) => SPEAKING.has(m.kind) && !["code", "system", "owner"].includes(m.role)).slice(-3).reverse();
    const rounds = new Set(ms.map((m) => m.round_id).filter((x) => x != null)).size;
    body.replaceChildren(
      concl ? h("div", {class: "ag-op-pin"}, h("small", null, `최근 결론 · ${dayLabel(concl.ts)} ${fmt.hm(concl.ts)}`), h("b", null, firstLine(concl.text))) : null,
      staff.length ? h("div", {class: "ag-op-list", role: "list"}, staff.map((m) => h("div", {class: "ag-op-row", role: "listitem", style: {"--h": hueFor(roles, m.role)}},
        pixAvatar(roles, m.role),
        h("div", null, h("div", {class: "ag-op-h"}, h("b", null, m.speaker_name || roleName(roles, m.role)), h("span", null, KIND_KO[m.kind] || m.kind), h("time", null, fmt.hm(m.ts)), typeBadges(m, 2)),
          ui.moreText(firstLine(m.text) + (String(m.text || "").includes("\n") ? " …" : ""), 2, "ag-op-t"))))) : null,
      h("div", {class: "ag-op-foot"}, h("span", null, `최근 기록 ${fmt.int(ms.length)}줄 · 회의 ${fmt.int(rounds)}번`), h("span", {class: "grow"}),
        h("span", null, `마지막 ${dayLabel(ms[ms.length - 1].ts)} ${fmt.hm(ms[ms.length - 1].ts)}`)));
  }).catch(() => { card.hidden = true; });        // no room for this strategy (404) or the agents are not set up: no card
  return card;
}
