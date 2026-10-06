// 24시간 토론방 (builder D, CONTRACT.md section 4; feature `debate`: the tab is shown greyed '꺼짐' until the room has
// run). A separate paid-API service (docs/debate-room.md) that debates around the clock and never changes an order, a
// rule or an account. GET /api/debate (store key `debate`, polled every 5 minutes; once more about a minute after the
// next round was due, so a new round shows soon).
// debate-chat (owners 10/06: "에이전트 팀들끼리 서로 대화하는게 토론 아니야? … 회의실 화면처럼"): a chat room like the
// agents' rooms. Left: the newest debate as a conversation (debate-chat.js: each role a pixel character with its name,
// bubbles in speaking order, "↳ 비관론자에게" and a 동의 / 반대 / 보완 / 질문 chip when the stored turn has them, the
// round's topic as the room's subject line, the 사회자's 정리 pinned at the end), then the earlier debates newest first,
// folded to their topic and note (tap: the whole conversation), then the ideas for the new-strategy lab. Right: the
// status column (debate-side.js: 토론 중 / 쉬는 중, the next round's countdown from the server's schedule, the month's
// cost against the cap with today's, the last 12 rounds, the hypotheses ledger); on a phone it folds into one line on
// top. When the room is off: what it is, that it costs nothing now, and the three steps to turn it on.
// HONESTY: every bubble is a stored turn (text nodes, no typing effect); it is ONE AI speaking every role (said under
// the chat); nothing here changes an order, a rule or an account.
import {h, ui, fmt, motion, store} from "../core/pb.js";
import {roundChat, castStrip, avatar, noteLine, hasReplies, CAST} from "./debate-chat.js";
import {makeSide, usd4} from "./debate-side.js";

export async function mount(el, ctx) {
  ctx.setTitle("24시간 토론방");
  el.append(ui.screenHead("24시간 토론방", "AI 하나가 다섯 역할로 나눠 하는 토론 · 유료 API로 따로 돌고 주문·규칙·계좌를 바꾸지 않습니다"));
  const wrap = h("div", {class: "db-body"}, motion.shimmer(5));
  el.append(wrap);
  const st = {d: null, shown: null, poked: 0};

  // ---------------------------------------------------------------- the room (chat | status)
  const side = makeSide(ctx);
  const subject = h("b", {class: "db-topic"});
  const meta = h("span", {class: "db-meta"});
  const castBox = h("div", {class: "db-castbox"});
  const startLine = h("div", {class: "db-start"});
  const chatBox = h("div", {class: "db-chat"});
  const scroller = h("div", {class: "db-scroll"}, startLine, chatBox);
  const head = h("div", {class: "db-head"},
    h("span", {class: "db-avs", "aria-hidden": "true"}, CAST.slice(0, 5).map((c) => avatar(c.id, 22))),
    h("div", {class: "db-ht"}, h("small", null, "이번 회차 주제"), subject), meta);
  const honest = h("p", {class: "db-honest"}, "AI 하나가 다섯 역할과 사회자를 모두 맡아 말하는 방입니다. 말풍선은 저장된 글 그대로(실시간 타이핑 아님)이고, ",
    "의견이지 사실이 아닙니다. 이 방은 주문·규칙·계좌를 바꾸지 않습니다.");
  const live = h("section", {class: "db-room", "aria-label": "지금 토론"}, head, castBox, scroller, honest);
  const history = ui.pager({size: 5, empty: "지난 토론이 아직 없습니다", row: (r) => histRow(r)});
  const histCard = h("section", {class: "db-sec db-hist", "aria-label": "지난 토론"},
    h("h3", null, "지난 토론", h("small", null, "새것부터 · 누르면 대화 전체")), history.el);
  const ideas = ui.pager({size: 4, empty: "아직 없음", row: (x) => h("div", {class: "db-idea", role: "listitem"},
    h("time", null, fmt.mmdd(x.ts)), h("span", null, x.text), x.tag ? ui.pill(x.tag, "thin") : null)});
  const ideaCard = h("section", {class: "db-sec", "aria-label": "새 매매법 연구실에 줄 아이디어"},
    h("h3", null, "새 매매법 연구실에 줄 아이디어", h("small", null, "시험 전의 생각 · 결론 아님")), ideas.el);
  const caution = h("p", {class: "rk-banner db-caution"});
  const main = h("div", {class: "db-main"}, live, histCard, ideaCard, caution);
  const frame = h("section", {class: "console db-frame", "aria-label": "24시간 토론방"},
    h("div", {class: "con-head"}, h("span", {class: "con-title"}, "24시간 토론방"), h("span", {class: "grow"}),
      h("span", {class: "db-conhint"}, "유료 API · 의견일 뿐")),
    h("div", {class: "db-panes"}, main, side.el));

  // ---------------------------------------------------------------- pieces
  function histRow(r) {
    const region = h("div", {class: "db-hbody", hidden: true});
    const note = noteLine(r);
    const btn = h("button", {class: "db-hrow", type: "button", "aria-expanded": "false"},
      h("time", {title: fmt.kst(r.ts)}, fmt.kst(r.ts)),
      h("span", {class: "db-hmain"}, h("b", null, r.topic || "주제 없음"), note ? h("span", {class: "db-hnote"}, note) : null),
      h("span", {class: "db-hmeta"}, `발언 ${fmt.int((r.messages || []).filter((m) => m.speaker !== "정리" && m.stance !== "정리").length)}개 · ${usd4(r.cost_usd)}`,
        hasReplies(r) ? null : h("small", null, "예전 형식")),
      h("i", {class: "db-hchev", "aria-hidden": "true"}, "›"));
    btn.addEventListener("click", () => {
      const open = btn.getAttribute("aria-expanded") !== "true";
      if (open && !region.firstChild) region.append(roundChat(r));
      btn.setAttribute("aria-expanded", String(open));
      motion.expand(region, open);
    });
    return h("div", {class: "db-hitem", role: "listitem"}, btn, region);
  }

  function offCard(d) {
    const step = (n, t, code) => h("li", null, h("b", {class: "db-stepn"}, String(n)), h("span", null, t, code ? h("code", null, code) : null));
    return ui.card({plate: "꺼짐", sub: "아직 시작 전", cls: "db-off"},
      h("div", {class: "row wrap"}, ui.pill("꺼짐", "thin"), h("b", null, "아직 시작 전 · 켜면 하루 종일 토론")),
      h("p", {class: "ink2"}, (d && d.note) || "24시간 토론방은 아직 한 번도 돌지 않았습니다."),
      h("p", {class: "rk-note"}, "에이전트 회의와 별도로, 두 분이 API 키를 넣고 켜면 하루 종일 다섯 역할(낙관·비관·회의·리스크·퀀트)이 장을 두고 서로 대화하는 방입니다 (유료 API, 월 한도). 주문·규칙·계좌는 바꾸지 않습니다. 지금은 비용이 들지 않습니다."),
      h("ol", {class: "db-steps"},
        step(1, "키 없이 비용 재 보기 · ", "python -m paperbot.agents.debate once --dry-run"),
        step(2, "키와 한도 넣기 (편집기 안에만) · ", "sudoedit /etc/paperbot/debate.env"),
        step(3, "켜기 · ", "sudo systemctl enable --now paperbot-debate")),
      h("p", {class: "rk-note"}, "자세한 순서와 끄는 법: 서버 안내서 docs/debate-room.md. 켜면 이 화면에 대화방, 이번 달 비용과 다음 회차까지 남은 시간이 나옵니다."),
      h("div", {class: "db-free"}, h("b", null, "지금 무료로 도는 것"),
        h("span", null, "매일 12:00 시장분석팀이 회의에서 낙관·비관 판정을 내고, 24시간 뒤 코드가 채점합니다 (구독 안에서, 추가 비용 없음)."),
        h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: ctx.href("digest", "staff")}, "판정 채점 보기"), h("a", {class: "btn-line", href: ctx.href("office")}, "회의실로"))));
  }

  /** The finished debates newest first (the server's `chat`; an older server: its `rounds` that have turns). */
  const chatOf = (d) => (Array.isArray(d.chat) ? d.chat : (d.rounds || []).filter((r) => r.status === "ok" && (r.messages || []).length))
    .slice().sort((a, b) => (b.ts || 0) - (a.ts || 0));

  function renderLive(r) {
    if (!r) {
      subject.textContent = "아직 끝난 토론이 없습니다";
      meta.textContent = "";
      castBox.replaceChildren(castStrip(null));
      startLine.replaceChildren();
      chatBox.replaceChildren(h("div", {class: "db-none"}, h("b", null, "첫 토론이 끝나면 여기에 대화가 나옵니다"),
        h("span", null, "새 청산·알림·밤 점검이 없으면 회차를 건너뛰어 비용이 들지 않습니다. 오른쪽(휴대폰은 위)의 최근 회차에서 무엇을 했는지 보입니다.")));
      st.shown = null;
      return;
    }
    if (st.shown === r.round_id) return;              // the same stored round: leave it as the reader left it
    const fresh = st.shown != null;
    st.shown = r.round_id;
    const turns = (r.messages || []).filter((m) => m.speaker !== "정리" && m.stance !== "정리").length;
    subject.textContent = r.topic || "주제 없음";
    meta.replaceChildren(h("time", {title: fmt.kst(r.ts)}, fmt.kst(r.ts)), ` · 발언 ${fmt.int(turns)}개 · ${usd4(r.cost_usd)}`);
    castBox.replaceChildren(castStrip(r));
    startLine.replaceChildren(h("span", {class: "db-start-k"}, "토론 시작"), h("span", {class: "db-start-t"}, r.topic || "주제 없음"),
      h("time", null, fmt.hm(r.ts)));
    chatBox.replaceChildren(roundChat(r));
    if (fresh) motion.slideIn(chatBox);             // a new stored round arrived since the last paint
  }

  function render(d) {
    st.d = d || null;
    if (!d || !d.ready) { st.shown = null; wrap.replaceChildren(offCard(d)); return; }
    const chat = chatOf(d);
    side.render(d);
    renderLive(chat[0] || null);
    history.set(chat.slice(1), true);
    ideas.set(d.ideas || [], true);
    caution.replaceChildren(h("b", null, "읽을 때 주의"), h("span", null, d.caution || "AI가 쓴 토론이라 사실이 아니라 의견입니다."));
    if (!frame.isConnected) wrap.replaceChildren(frame);
  }

  // the countdown each second; about a minute after a round was due, ask the server once for what happened
  ctx.every(1000, () => {
    const nx = side.tick();
    if (nx && nx.ts && Date.now() > nx.ts + 60000 && st.poked !== nx.ts) {
      st.poked = nx.ts;
      store.refresh("debate").catch(() => {});
    }
  });

  ctx.watch("debate", (d, k, err) => {
    if (d) render(d);
    else if (err && !wrap.querySelector(".db-frame, .card")) wrap.replaceChildren(ui.errorBox(err, () => store.refresh("debate").catch(() => {})));
  });
  await store.need("debate", 60000).catch(() => null);
}

export function unmount() {}
