// 24시간 토론방 (builder D, CONTRACT.md section 4; feature `debate`: the router and the nav hide it until the room has
// run). A separate paid-API service (docs/debate-room.md) that debates around the clock and never changes an order, a
// rule or an account. Shows its state and reason, this month's real spend against its cap, the latest rounds (text
// as written), skipped rounds and errors, the hypotheses code graded with the scoreboard (small samples say so), the
// ideas for the new-strategy lab and the caution line. GET /api/debate (store key `debate`, polled every 5 minutes).
import {h, put, ui, fmt, motion, store} from "../core/pb.js";

const STATE = {running: ["돌고 있음", "good"], paused: ["멈춤", "bad"], no_key: ["키 없음", "bad"], off: ["꺼짐", "thin"]};
const usd = fmt.usd;

export async function mount(el, ctx) {
  ctx.setTitle("24시간 토론방");
  el.append(ui.screenHead("24시간 토론방", "유료 API로 따로 도는 AI 토론 · 주문·규칙·계좌를 바꾸지 않습니다"));
  const head = h("div", {class: "stack"});
  const rounds = ui.pager({size: 3, empty: "아직 토론 글이 없습니다", row: (r) => roundNode(r)});
  const hyps = ui.pager({size: 6, empty: "아직 없음", row: (x) => hypRow(x)});
  const ideas = ui.pager({size: 5, empty: "아직 없음", row: (x) => h("div", {class: "lrow", role: "listitem"}, h("span", {class: "rk"}, fmt.mmdd(x.ts)),
    h("span", {class: "lname db-wrap"}, x.text), x.tag ? ui.pill(x.tag, "thin") : h("span"))});
  const roundsMeta = h("div", {class: "stack tight"});
  const score = h("div", {class: "stack tight"});
  const body = h("div", {class: "stack"},
    head,
    ui.card({plate: "최근 토론", sub: "새것부터 · AI가 쓴 글 그대로 (의견이지 사실이 아님)"}, rounds.el, roundsMeta),
    ui.card({plate: "가설", sub: "메뉴에 있는 것만 코드가 채점 · 결론 아님"}, score, hyps.el),
    ui.card({plate: "새 매매법 연구실에 줄 아이디어", sub: "시험 전의 생각"}, ideas.el));
  const wrap = h("div", {class: "db-body"}, motion.shimmer(5));
  el.append(wrap);

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

  function render(d) {
    if (!d || !d.ready) {
      wrap.replaceChildren(ui.card({plate: "꺼짐"}, h("p", {class: "ink2"}, (d && d.note) || "24시간 토론방 — 꺼짐"),
        h("p", {class: "rk-note"}, "에이전트와 별도로, 두 분이 API 키를 넣고 켜면 하루 종일 장을 두고 토론하는 방입니다 (유료 API, 월 한도). 지금은 비용이 들지 않습니다.")));
      return;
    }
    const [stKo, stCls] = STATE[d.state] || [d.state_ko || d.state, "thin"];
    const sp = d.spend || {};
    head.replaceChildren(ui.card({hero: true, plate: "상태"},
      h("div", {class: "row wrap"}, ui.pill(stKo, stCls), d.reason ? h("span", {class: "ink2"}, d.reason) : null),
      h("div", {class: "grid2"},
        ui.gauge({name: "이번 달 실제 비용 (유료 API)", value: sp.month, display: usd(sp.month), cap: sp.cap || null, capDisplay: sp.cap ? usd(sp.cap) : null,
          mean: `오늘 ${usd(sp.day)} · 한도에 닿으면 그달은 멈춥니다. 모의 계좌의 돈이 아니라 이 방의 API 키로 나가는 실제 비용입니다.`}),
        ui.kv([["모델", d.model || "—"], ["주기", d.every_min ? `${fmt.int(d.every_min)}분마다` : "—"], ["마지막 토론", d.last_round_ts ? fmt.kst(d.last_round_ts) : "—"],
          ["회차당 평균", d.avg_round ? usd(d.avg_round.cost_usd) : "—"], ["최근 7일 회차", d.avg_round ? fmt.int(d.avg_round.rounds_7d) : "—"],
          ["하루 안에 건너뜀", `${fmt.int(d.skipped_24h || 0)}번`]])),
      d.caution ? h("p", {class: "rk-banner"}, h("b", null, "읽을 때 주의"), h("span", null, d.caution)) : null));
    const all = d.rounds || [];
    rounds.set(all.filter((r) => (r.messages || []).length), true);
    const skipped = all.filter((r) => r.status === "skipped").length;
    const bad = all.filter((r) => r.status === "error" || r.status === "aborted").slice(0, 3);
    put(roundsMeta,
      skipped ? h("p", {class: "rk-note"}, `건너뛴 회차 ${fmt.int(skipped)}번: 새 청산·알림·밤 점검이 없어 같은 이야기를 되풀이하지 않았습니다.`) : null,
      bad.length ? h("p", {class: "rk-note"}, "최근 오류 · ", bad.map((r) => `${fmt.kst(r.ts)} ${String(r.error || r.status).slice(0, 80)}`).join(" / ")) : null);
    // #88: the whole room's record only (one model speaks every role: per-speaker rates are not separate opinions),
    // next to a coin flip and to the hits expected by chance; a small sample is marked red
    const sb = d.scoreboard || {}, easy = sb.easy || {};
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
