// 24시간 토론방 (builder D, CONTRACT.md section 4; feature `debate`: the tab is shown greyed '꺼짐' until the room has
// run). A separate paid-API service (docs/debate-room.md) that debates around the clock and never changes an order, a
// rule or an account. GET /api/debate (store key `debate`, polled every 5 minutes).
// agents-ui: when it is on, the latest round as a two-column 강세 (낙관론자) vs 약세 (비관론자) view with the other voices
// (회의론자 · 리스크 책임자 · 퀀트) under it and the round's own summary (the 정리 line the model wrote), the 판정 미터 (the
// room's graded claims against a coin flip: the room never gives a direction, code grades its hypotheses), this
// month's real spend against the cap and the next round's countdown (last attempt + its interval: a round with nothing
// new is skipped at no cost, said so). Then the earlier rounds, skipped rounds and errors, the graded hypotheses, the
// ideas and the caution line. When it is off: what the room is, that it costs nothing now, and the three steps to
// turn it on (docs/debate-room.md), plus the free 12:00 낙관·비관 판정 the agents already hold.
// HONESTY: every text is the stored text (text nodes); nothing is typed out; the countdown is the configured interval,
// labelled 예정.
import {h, put, ui, fmt, motion, store} from "../core/pb.js";
import {countdown} from "./office-wall.js";

const STATE = {running: ["돌고 있음", "good"], paused: ["멈춤", "bad"], no_key: ["키 없음", "bad"], off: ["꺼짐", "thin"]};
const usd = fmt.usd;
const BULL = "낙관론자", BEAR = "비관론자", NOTE = "정리";

export async function mount(el, ctx) {
  ctx.setTitle("24시간 토론방");
  el.append(ui.screenHead("24시간 토론방", "유료 API로 따로 도는 AI 토론 · 주문·규칙·계좌를 바꾸지 않습니다"));
  const head = h("div", {class: "stack"});
  const live = h("div", {class: "stack"});
  const rounds = ui.pager({size: 3, empty: "아직 토론 글이 없습니다", row: (r) => roundNode(r)});
  const hyps = ui.pager({size: 6, empty: "아직 없음", row: (x) => hypRow(x)});
  const ideas = ui.pager({size: 5, empty: "아직 없음", row: (x) => h("div", {class: "lrow", role: "listitem"}, h("span", {class: "rk"}, fmt.mmdd(x.ts)),
    h("span", {class: "lname db-wrap"}, x.text), x.tag ? ui.pill(x.tag, "thin") : h("span"))});
  const roundsMeta = h("div", {class: "stack tight"});
  const score = h("div", {class: "stack tight"});
  const body = h("div", {class: "stack"},
    head, live,
    ui.card({plate: "지난 토론", sub: "새것부터 · AI가 쓴 글 그대로 (의견이지 사실이 아님)"}, rounds.el, roundsMeta),
    ui.card({plate: "가설", sub: "메뉴에 있는 것만 코드가 채점 · 결론 아님"}, score, hyps.el),
    ui.card({plate: "새 매매법 연구실에 줄 아이디어", sub: "시험 전의 생각"}, ideas.el));
  const wrap = h("div", {class: "db-body"}, motion.shimmer(5));
  el.append(wrap);
  let cur = null;

  // ---------------------------------------------------------------- pieces
  function roundNode(r) {
    return h("div", {class: "db-round", role: "listitem"},
      h("div", {class: "db-rh"}, h("time", null, fmt.kst(r.ts)), h("b", null, r.topic || "주제 없음"), h("span", {class: "grow"}), h("span", {class: "muted"}, usd(r.cost_usd))),
      h("div", {class: "db-msgs"}, (r.messages || []).map((m) => h("div", {class: "db-msg"},
        h("span", {class: "db-who"}, `> ${m.speaker || "?"}${m.stance ? ` · ${m.stance}` : ""}`), ui.moreText(String(m.text || ""), 3)))));
  }
  function hypRow(x) {
    const cls = x.status === "graded" ? (String(x.outcome).startsWith("hit") ? "good" : "bad") : "thin";
    return h("div", {class: "lrow", role: "listitem"}, ui.pill(x.status_ko || x.status, cls), h("span", {class: "lname db-wrap"}, x.claim || x.kind || ""),
      h("span", {class: "ret muted"}, x.speaker || ""),
      h("span", {class: "meta"}, x.horizon ? h("span", null, `기한 ${x.horizon}`) : null, h("span", null, fmt.kst(x.ts)),
        x.status === "dropped" && x.outcome ? h("span", null, String(x.outcome)) : null));
  }
  const say = (m, side) => h("div", {class: ["db-say", side]}, side === "mid" ? h("span", {class: "db-say-who"}, m.speaker) : null, ui.moreText(String(m.text || ""), 5));
  /** The newest round with turns: 강세 vs 약세 side by side, the other voices under them, the 정리 line on top. */
  function liveRound(r) {
    const ms = (r && r.messages) || [];
    const bull = ms.filter((m) => m.speaker === BULL), bear = ms.filter((m) => m.speaker === BEAR);
    const note = ms.filter((m) => m.speaker === NOTE || m.stance === NOTE).pop();
    const others = ms.filter((m) => ![BULL, BEAR, NOTE].includes(m.speaker) && m.stance !== NOTE);
    const col = (side, ko, list) => h("div", {class: ["db-col", side]}, h("div", {class: "db-col-h"}, h("b", null, ko), h("small", null, side === "bull" ? BULL : BEAR)),
      list.length ? list.map((m) => say(m, side)) : h("p", {class: "muted"}, "이번 회차에 발언 없음"));
    return ui.card({plate: "지금 토론", sub: `${fmt.kst(r.ts)} · 회차 비용 ${usd(r.cost_usd)} · 저장된 글 그대로`, cls: "db-live"},
      h("p", {class: "db-topic"}, h("span", {class: "muted"}, "주제 "), r.topic || "주제 없음"),
      note ? h("div", {class: "db-note"}, h("b", null, "이번 회차 정리"), h("span", null, String(note.text || "").replace(/^정리:\s*/, ""))) : null,
      h("div", {class: "db-vs"}, col("bull", "강세", bull), h("span", {class: "db-vs-mid", "aria-hidden": "true"}, "VS"), col("bear", "약세", bear)),
      others.length ? h("div", {class: "db-others"}, others.map((m) => say(m, "mid"))) : null,
      h("p", {class: "rk-note"}, "AI 하나가 다섯 역할을 모두 말하는 방입니다. 강세·약세 어느 쪽이 이겼는지는 이 방이 정하지 않고, 가설만 코드가 나중에 채점합니다."));
  }
  /** 판정 미터: the room's graded claims (hit share) against a coin flip, a small sample said so. */
  function meter(sb) {
    const g = sb.graded || 0, hit = sb.hit || 0, rate = g ? hit / g : null;
    return h("div", {class: "db-meter"},
      h("div", {class: "db-mh"}, h("b", null, "판정 미터"), h("span", {class: "muted"}, "방 전체 가설 채점 · 동전 던지기 50%와 비교")),
      h("div", {class: "db-mbar", role: "img", "aria-label": g ? `맞음 ${hit}, 틀림 ${g - hit}` : "채점 전"},
        g ? [h("i", {class: "hit", style: {"--w": `${(hit / g) * 100}%`}}), h("i", {class: "miss", style: {"--w": `${((g - hit) / g) * 100}%`}})] : null,
        h("span", {class: "db-m50", title: "동전 던지기 50%"})),
      h("div", {class: "db-mf"}, h("span", null, g ? `맞음 ${fmt.int(hit)} · 틀림 ${fmt.int(g - hit)} (${fmt.pct(rate, 0, false)})` : "채점된 가설 없음"),
        sb.small !== false ? ui.pill("표본 적음", "thin") : null, h("span", {class: "grow"}), h("span", {class: "muted"}, `채점 대기 ${fmt.int(((sb.by_status || {}).open) || 0)}`)));
  }
  /** 이번 달 사용 $x / 한도 $y and the day's spend. */
  function costMeter(sp) {
    const cap = sp.cap || 0, used = sp.month || 0, p = cap ? Math.min(1, used / cap) : 0;
    return h("div", {class: "db-cost"},
      h("div", {class: "db-mh"}, h("b", null, "이번 달 사용"), h("span", {class: "muted"}, "실제 비용 (유료 API) · 모의 계좌 돈 아님")),
      h("div", {class: "db-costv"}, h("b", {class: "num"}, usd(used)), h("span", {class: "muted"}, ` / 한도 ${cap ? usd(cap) : "—"}`), h("span", {class: "grow"}), h("span", {class: "muted"}, `오늘 ${usd(sp.day)}`)),
      h("div", {class: ["db-cbar", p >= 0.95 ? "bad" : p >= 0.8 ? "warn" : ""], role: "img", "aria-label": `한도의 ${Math.round(p * 100)}%`},
        h("i", {style: {"--w": `${(p * 100).toFixed(1)}%`}}), h("span", {class: "db-c80", title: "80%: 텔레그램 경고"}), h("span", {class: "db-c95", title: "95%: 그달은 멈춤"})),
      h("p", {class: "muted db-small"}, "80%에서 경고, 95%부터 그달은 멈추고 다음 달 1일(한국 시간)에 이어집니다. 진짜 한도는 Anthropic 콘솔의 지출 한도입니다."));
  }
  const nextEl = h("b", {class: "num db-next"}, "—");
  const nextWhat = h("span", {class: "muted"});
  function nextAt(d) {
    const last = (d.last_attempt && d.last_attempt.ts) || d.last_round_ts;
    return d.state === "running" && last && d.every_min ? last + d.every_min * 60000 : null;
  }
  function tick() {
    if (!cur) return;
    const at = nextAt(cur);
    const t = countdown(at);
    nextEl.textContent = at ? (t || "곧") : "—";
    nextWhat.textContent = cur.state !== "running" ? "돌고 있지 않음" : at ? (t ? " 남음 · 예정 (새 소식이 없으면 비용 없이 건너뜀)" : " · 차례가 됐습니다 (기록되면 나옵니다)") : "";
  }
  ctx.every(1000, tick);

  function offCard(d) {
    const step = (n, t, code) => h("li", null, h("b", {class: "db-stepn"}, String(n)), h("span", null, t, code ? h("code", null, code) : null));
    return ui.card({plate: "꺼짐", sub: "아직 시작 전", cls: "db-off"},
      h("div", {class: "row wrap"}, ui.pill("꺼짐", "thin"), h("b", null, "아직 시작 전 · 켜면 하루 종일 토론")),
      h("p", {class: "ink2"}, (d && d.note) || "24시간 토론방은 아직 한 번도 돌지 않았습니다."),
      h("p", {class: "rk-note"}, "에이전트 회의와 별도로, 두 분이 API 키를 넣고 켜면 하루 종일 장을 두고 강세·약세로 토론하는 방입니다 (유료 API, 월 한도). 주문·규칙·계좌는 바꾸지 않습니다. 지금은 비용이 들지 않습니다."),
      h("ol", {class: "db-steps"},
        step(1, "키 없이 비용 재 보기 · ", "python -m paperbot.agents.debate once --dry-run"),
        step(2, "키와 한도 넣기 (편집기 안에만) · ", "sudoedit /etc/paperbot/debate.env"),
        step(3, "켜기 · ", "sudo systemctl enable --now paperbot-debate")),
      h("p", {class: "rk-note"}, "자세한 순서와 끄는 법: 서버 안내서 docs/debate-room.md. 켜면 이 화면에 강세·약세 토론, 이번 달 비용과 다음 회차까지 남은 시간이 나옵니다."),
      h("div", {class: "db-free"}, h("b", null, "지금 무료로 도는 것"),
        h("span", null, "매일 12:00 시장분석팀이 회의에서 낙관·비관 판정을 내고, 24시간 뒤 코드가 채점합니다 (구독 안에서, 추가 비용 없음)."),
        h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: ctx.href("digest", "staff")}, "판정 채점 보기"), h("a", {class: "btn-line", href: ctx.href("office")}, "회의실로"))));
  }

  function render(d) {
    cur = d || null;
    if (!d || !d.ready) { wrap.replaceChildren(offCard(d)); return; }
    const [stKo, stCls] = STATE[d.state] || [d.state_ko || d.state, "thin"];
    const sp = d.spend || {};
    const sb = d.scoreboard || {}, easy = sb.easy || {};
    head.replaceChildren(ui.card({hero: true, plate: "상태"},
      h("div", {class: "row wrap"}, d.state === "running" ? ui.livePill("토론 중") : ui.pill(stKo, stCls), d.reason ? h("span", {class: "ink2"}, d.reason) : null,
        h("span", {class: "grow"}), h("span", {class: "db-nextw"}, h("span", {class: "muted"}, "다음 회차까지 "), nextEl, nextWhat)),
      h("div", {class: "db-meters"}, costMeter(sp), meter(sb)),
      ui.kv([["모델", d.model || "—"], ["주기", d.every_min ? `${fmt.int(d.every_min)}분마다` : "—"], ["마지막 토론", d.last_round_ts ? fmt.kst(d.last_round_ts) : "—"],
        ["회차당 평균", d.avg_round ? usd(d.avg_round.cost_usd) : "—"], ["최근 7일 회차", d.avg_round ? fmt.int(d.avg_round.rounds_7d) : "—"],
        ["하루 안에 건너뜀", `${fmt.int(d.skipped_24h || 0)}번`]]),
      d.caution ? h("p", {class: "rk-banner"}, h("b", null, "읽을 때 주의"), h("span", null, d.caution)) : null));
    tick();
    const all = d.rounds || [];
    const withTurns = all.filter((r) => (r.messages || []).length).sort((a, b) => (b.ts || 0) - (a.ts || 0));
    live.replaceChildren(...(withTurns.length ? [liveRound(withTurns[0])] : []));
    rounds.set(withTurns.slice(1), true);
    const skipped = all.filter((r) => r.status === "skipped").length;
    const bad = all.filter((r) => r.status === "error" || r.status === "aborted").slice(0, 3);
    put(roundsMeta,
      skipped ? h("p", {class: "rk-note"}, `건너뛴 회차 ${fmt.int(skipped)}번: 새 청산·알림·밤 점검이 없어 같은 이야기를 되풀이하지 않았습니다.`) : null,
      bad.length ? h("p", {class: "rk-note"}, "최근 오류 · ", bad.map((r) => `${fmt.kst(r.ts)} ${String(r.error || r.status).slice(0, 80)}`).join(" / ")) : null);
    // #88: the whole room's record only (one model speaks every role: per-speaker rates are not separate opinions),
    // next to a coin flip and to the hits expected by chance; a small sample is marked red
    put(score,
      sb.small !== false ? h("p", {class: "rk-banner bad"}, h("b", null, "표본 적음"),
        h("span", null, `채점된 가설이 ${fmt.int(sb.graded || 0)}개입니다. ${fmt.int(sb.small_below || 10)}개 미만이면 우연과 구별할 수 없어 아무것도 말해 주지 못합니다.`)) : null,
      h("div", {class: "db-total"}, h("span", null, "방 전체 맞음"), h("b", null, sb.graded ? `${fmt.int(sb.hit)}/${fmt.int(sb.graded)} (${fmt.pct(sb.rate, 0, false)})` : "—"),
        h("span", {class: "muted"}, "동전 던지기 (기준)"), h("span", null, "50%"),
        h("span", {class: "muted"}, "우연히 맞을 기대치"), sb.expected_rate != null
          ? h("span", null, `${fmt.pct(sb.expected_rate, 0, false)} (${fmt.int(Math.round(sb.expected_hits))}개쯤)`)
          : ui.notYet("채점된 가설 없음", "채점된 가설이 생기면 주장마다 원래 맞을 확률(모르면 50%)을 더해 보여 줍니다")),
      easy.graded ? h("p", {class: "rk-note"}, `원래 ${fmt.pct(easy.rate_from, 0, false)} 넘게 맞는 쉬운 예측 ${fmt.int(easy.graded)}개는 따로 셌습니다 (맞음 ${fmt.int(easy.hit)}개, 성적에 넣지 않음).`) : null,
      h("p", {class: "rk-note"}, "AI 한 번이 모든 역할을 말하는 방이라 직원별 성적은 보여 주지 않습니다."));
    hyps.set(d.hypotheses || [], true);
    ideas.set(d.ideas || [], true);
    if (!body.isConnected) wrap.replaceChildren(body);
  }

  ctx.watch("debate", (d, k, err) => {
    if (d) render(d);
    else if (err && !wrap.querySelector(".db-round, .card")) wrap.replaceChildren(ui.errorBox(err, () => store.refresh("debate").catch(() => {})));
  });
  await store.need("debate", 60000).catch(() => null);
}

export function unmount() {}
