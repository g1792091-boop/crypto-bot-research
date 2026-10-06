// 24시간 토론방 · the chat (debate-chat): one debate round as a messenger conversation, the look of the agents' rooms
// (rooms-chat.js): each role is a pixel character (core/figure.js stratFigure heads, one hair shape and one colour per
// role) with its name; the turns are bubbles in speaking order; a turn that answers an earlier one says whom it answers
// ("↳ 비관론자에게", tap: jump to that bubble) and its stance chip (동의 / 반대 / 보완 / 질문) ONLY when the stored turn
// has them (/api/debate chat[].messages[].reply_to / reply_stance; older rounds have neither and read as plain
// bubbles); the round's 정리 line is pinned at the end as the 사회자's note.
// HONESTY: every bubble is a stored turn (no typing effect, nothing invented); every string is a text node (h()).
import {h, ui, fmt, motion, stratFigure} from "../core/pb.js";

/** The cast: the five debate roles (paperbot/agents/debate.py ROLES) and the 사회자 who writes the round's 정리 note. */
export const CAST = [
  {id: "낙관론자", name: "낙관론자", tag: "낙관", hue: 150, fig: "DEBATE_BULL2", job: "좋게 볼 숫자를 찾음"},
  {id: "비관론자", name: "비관론자", tag: "비관", hue: 350, fig: "DEBATE_BEAR", job: "위험하게 볼 숫자를 찾음"},
  {id: "회의론자", name: "회의론자", tag: "검증", hue: 268, fig: "DEBATE_SKEPTIC3", job: "앞 사람 말의 약한 고리를 찾음"},
  {id: "리스크 책임자", name: "리스크 책임자", tag: "리스크", hue: 28, fig: "DEBATE_RISK13", job: "파산·낙폭·사고 쪽을 봄"},
  {id: "퀀트", name: "퀀트", tag: "퀀트", hue: 205, fig: "DEBATE_QUANT11", job: "숫자의 뜻과 한계를 짚음"},
  {id: "정리", name: "사회자", tag: "정리", hue: 45, fig: "DEBATE_CHAIR7", job: "회차 끝에 알게 된 것을 정리"},
];
const BY_ID = new Map(CAST.map((c) => [c.id, c]));
export const castOf = (speaker) => BY_ID.get(speaker) || {id: speaker, name: String(speaker || "?"), tag: "", hue: 210, fig: `DEBATE_${speaker}`, job: ""};
export const isNote = (m) => !!m && (m.speaker === "정리" || m.stance === "정리");
/** 동의 / 반대 / 보완 / 질문 -> the chip's tone */
export const STANCE_CLS = {"동의": "agree", "반대": "disagree", "보완": "add", "질문": "ask"};

/** A role's pixel character in a round frame of its colour. */
export function avatar(speaker, size = 34) {
  const c = castOf(speaker);
  const f = stratFigure({strategy: c.fig, size});
  f.style.setProperty("--h", String(c.hue));
  return h("span", {class: "db-av", style: {"--h": c.hue}, title: c.name, "aria-hidden": "true"}, f);
}

/** The cast strip: who sits in this room and how often each spoke in the shown round (stored turns only); before the
 *  first finished round (round null) each one's job. */
export function castStrip(round) {
  const n = {};
  for (const m of (round && round.messages) || []) n[isNote(m) ? "정리" : m.speaker] = (n[isNote(m) ? "정리" : m.speaker] || 0) + 1;
  const said = (c) => !round ? c.job : c.id === "정리" ? (n[c.id] ? "정리함" : "정리 없음") : n[c.id] ? `${fmt.int(n[c.id])}번 말함` : "이번엔 차례 없음";
  return h("ul", {class: "db-cast", "aria-label": "토론 참가자"}, CAST.map((c) => h("li", {class: ["db-castm", !round || n[c.id] ? "" : "quiet"],
    style: {"--h": c.hue}, title: `${c.name}: ${c.job}`}, avatar(c.id, 30), h("b", null, c.name), h("small", null, said(c)))));
}

/**
 * roundChat(round, {flashTo}) -> the conversation of one stored round: bubbles in order, the 정리 note pinned last.
 * round: /api/debate chat[] item {round_id, ts, topic, cost_usd, turns, cut, messages}.
 */
export function roundChat(round, o = {}) {
  const ms = (round && round.messages) || [];
  const turns = ms.filter((m) => !isNote(m));
  const note = ms.filter(isNote).pop();
  const nodes = [];
  const list = h("div", {class: "db-list", role: "log", "aria-label": "토론 대화"});
  turns.forEach((m, i) => {
    // the bubble a turn answers: the latest earlier turn of that speaker
    let target = null;
    if (m.reply_to) for (let j = i - 1; j >= 0; j--) if (turns[j].speaker === m.reply_to) { target = j; break; }
    const n = bubble(m, i, round, target == null ? null : () => jump(nodes[target]));
    nodes.push(n);
    list.append(n);
  });
  if (round && round.cut) list.append(h("p", {class: "db-sys"}, "AI 답이 길이 한도에서 잘려 끝난 발언까지만 저장됐습니다"));
  if (note) list.append(noteNode(note, round));
  else list.append(h("p", {class: "db-sys"}, "이번 회차에는 정리 글이 없습니다"));
  function jump(n) {
    if (!n) return;
    n.scrollIntoView({block: "nearest", behavior: motion.reduced() ? "auto" : "smooth"});
    n.classList.remove("db-flash"); void n.offsetWidth; n.classList.add("db-flash");
    if (o.flashTo) o.flashTo(n);
  }
  return list;
}

function bubble(m, i, round, onReply) {
  const c = castOf(m.speaker);
  const sc = STANCE_CLS[m.reply_stance];
  const re = m.reply_to ? h(onReply ? "button" : "span", {class: "db-re", type: onReply ? "button" : null, onclick: onReply || null,
    title: onReply ? `${castOf(m.reply_to).name}의 말로 가기` : null}, `↳ ${castOf(m.reply_to).name}에게`) : null;
  return h("div", {class: "db-msg", style: {"--h": c.hue}, dataset: {i: String(i)}},
    avatar(m.speaker),
    h("div", {class: "db-mb"},
      h("div", {class: "db-mh"}, h("b", {class: "db-who"}, c.name), c.tag ? h("span", {class: "db-tag"}, c.tag) : null,
        h("span", {class: "db-no"}, `${fmt.int(i + 1)}번째`), round && round.ts ? h("time", {title: fmt.kst(round.ts)}, fmt.hm(round.ts)) : null),
      h("div", {class: "db-bub"},
        re || sc ? h("div", {class: "db-reline"}, re, sc ? h("span", {class: ["db-st", sc]}, m.reply_stance) : null) : null,
        ui.moreText(String(m.text || ""), 5))));
}

function noteNode(m, round) {
  return h("div", {class: "db-pin", style: {"--h": castOf("정리").hue}},
    avatar("정리"),
    h("div", {class: "db-mb"},
      h("div", {class: "db-mh"}, h("b", {class: "db-who"}, "사회자"), h("span", {class: "db-tag"}, "이번 회차 정리"),
        round && round.ts ? h("time", null, fmt.hm(round.ts)) : null),
      h("p", {class: "db-pin-t"}, String(m.text || "").replace(/^\s*정리\s*[:：]\s*/, ""))));
}

/** One line of a round's note (the history row), '' when it has none. */
export function noteLine(round) {
  const n = ((round && round.messages) || []).filter(isNote).pop();
  return n ? String(n.text || "").replace(/^\s*정리\s*[:：]\s*/, "").replace(/\s+/g, " ").trim() : "";
}
/** Did this round store who answers whom (a round of the back-and-forth format)? */
export const hasReplies = (round) => ((round && round.messages) || []).some((m) => m.reply_to || m.reply_stance);
