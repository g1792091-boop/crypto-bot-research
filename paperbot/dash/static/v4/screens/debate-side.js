// 24시간 토론방 · the status column (debate-side): is the room working? 토론 중 / 쉬는 중 (the service's own state), the
// next round's countdown from the server's real schedule (/api/debate `next`: last attempt + interval, or the end of a
// backoff), this month's cost against the cap with today's cost, the last 12 rounds as a timeline (토론함 with its cost /
// 건너뜀 with the stored reason / 오류 with its cause) and the hypotheses ledger (채점 대기 / 맞음 / 틀림, the room as a
// whole against a coin flip, a small sample said so). On a phone or a narrow window the column folds into one summary
// line at the top of the screen (tap: 펼치기).
// HONESTY: "토론 중" only while the service says running (its heartbeat is fresh: debate.summary turns a stale one into
// 꺼짐); "지금 회차 진행 중" only while the newest stored round is 'running'; costs are the API's own usage numbers
// (real money, not paper money); nothing is animated to look busy. Every string is a text node.
// The idea factory (design step 6): the state block says what today's factory did (ideas handed to the lab's 5-year
// queue against the daily share, candidates, the next pick); the cost block gives the daily deep debate's own month
// line (its spend against its share, inside the month's cap). Only when /api/debate sends `factory`.
import {h, put, ui, fmt, local, serverNow} from "../core/pb.js";
import {countdown} from "./office-wall.js";

const usd = fmt.usd;
export const usd4 = (x) => x == null || !Number.isFinite(Number(x)) ? "—" : `$${fmt.num(x, 4)}`;
/** the service's state -> [Korean, pill class] (running is the live pill) */
const STATE = {running: ["토론 중", "live"], paused: ["쉬는 중", "warn"], no_key: ["쉬는 중 · 키 없음", "bad"], off: ["꺼짐", "thin"]};
/** the stored error's cause tag (debate.py ApiError kinds and the packet failure) -> plain Korean */
const CAUSE = {auth: "API 키가 거부됨", credit: "API 잔액 부족", rate: "요청이 너무 잦다는 답(429)", server: "Anthropic 서버 오류",
  network: "인터넷 연결 오류", bad_request: "요청이 거절됨(설정 확인)", output: "AI 답을 읽지 못함", packet: "봇 자료를 읽지 못함"};
const OPEN_KEY = "debate-side-open";

/** One timeline row's [label, tone, detail, small line] from a stored round. */
export function roundKo(r, newest, running) {
  const why = String(r.why || "");
  if (r.status === "ok") return ["토론함", "is-ok", `${usd4(r.cost_usd)} · 발언 ${fmt.int(r.turns || 0)}개${why ? " · 일부 잘림" : ""}`, r.topic || ""];
  // the service's own reason ("새 청산 4건(기준 10건), 새 알림 없음, 새 밤 점검 없음"): its first part says enough
  if (r.status === "skipped") return ["건너뜀", "is-skip", "새 소식 없음 · 비용 0", why.split(/,\s*/)[0]];
  if (r.status === "running") return newest && running ? ["토론 중", "is-live", "AI 답을 기다리는 중", ""] : ["기록 중", "is-skip", "끝난 기록이 아직 없음", ""];
  if (r.status === "aborted") return ["중단", "is-bad", why || "서비스가 도중에 멈춤", ""];
  const tag = (why.match(/^([a-z_]+):/) || [])[1];
  return ["오류", "is-bad", `${CAUSE[tag] || "실패"}${r.cost_usd ? ` · ${usd4(r.cost_usd)}` : ""}`, ""];
}

/** The idea factory's line in the state block: "아이디어 공장 · 오늘 5년 시험 줄 0/2 · 후보 4 · 다음 고르기 21:00". */
export function factoryLine(f) {
  if (!f) return null;
  if (f.mode !== "factory") return h("p", {class: "db-small"}, `토론 방식: ${f.mode_ko || "예전 토론"} · 아이디어 공장 기록은 왼쪽(아래)에 남아 있습니다`);
  const t = f.today || {};
  return h("p", {class: "db-small db-fline"}, h("b", null, "아이디어 공장"),
    ` · 오늘 5년 시험 줄 ${fmt.int(t.queued || 0)}/${fmt.int(t.cap || 0)} · 후보 ${fmt.int(t.candidates || 0)}`
    + (t.next_pick_ts ? ` · 다음 고르기 ${fmt.hm(t.next_pick_ts)}` : ""));
}
/** The daily deep debate's own month line (inside the month's cap), when it is on or has run. */
export function deepCost(f) {
  const d = f && f.deep;
  if (!d || (!d.on && !d.round)) return null;
  return h("p", {class: "db-small"}, `깊은 토론 몫 이번 달 ${usd4(d.month)}${d.cap != null ? ` / ${usd(d.cap)}` : ""}`
    + ` · ${d.model || "따로 정한 모델"} · 하루 한 번 세 번 호출 · 월 한도 안에서 씀`);
}

export function makeSide(ctx) {
  const st = {d: null, open: !!local.get(OPEN_KEY, false)};
  // ---------------------------------------------------------------- the summary line (phone / narrow window only)
  const sumState = h("span", {class: "db-sum-st"});
  const sumNext = h("span", {class: "db-sum-n num"});
  const sumCost = h("span", {class: "db-sum-c"});
  const chev = h("span", {class: "db-chev"});
  const toggle = h("button", {class: "db-stoggle", type: "button", "aria-controls": "db-sbody"}, sumState, sumNext, sumCost, chev);
  toggle.addEventListener("click", () => { st.open = !st.open; local.set(OPEN_KEY, st.open); setOpen(); });
  // ---------------------------------------------------------------- the blocks
  const stateBox = h("section", {class: "db-sec db-state", "aria-label": "지금 상태"});
  const nextNum = h("b", {class: "db-next num"}, "—");
  const nextWhat = h("span", {class: "db-next-w"});
  const nextBox = h("div", {class: "db-nextbox"}, h("span", {class: "db-next-k"}), nextNum, nextWhat);
  const costBox = h("section", {class: "db-sec db-costs", "aria-label": "비용"});
  const tlBox = h("section", {class: "db-sec db-tl", "aria-label": "최근 회차"});
  const ledger = h("section", {class: "db-sec db-ledger", "aria-label": "가설 장부"});
  const hyps = ui.pager({size: 4, empty: "아직 가설이 없습니다", row: (x) => hypRow(x)});
  const body = h("div", {class: "db-sbody", id: "db-sbody"}, stateBox, costBox, tlBox, ledger);
  const el = h("aside", {class: "db-side", "aria-label": "토론방 상태"}, toggle, body);
  setOpen();

  function setOpen() {
    el.classList.toggle("open", st.open);
    toggle.setAttribute("aria-expanded", String(st.open));
    chev.textContent = st.open ? "접기" : "펼치기";
  }

  /** when the next round is due (the server's schedule; an older server: last attempt + interval) */
  function nextOf(d) {
    if (!d || !["running", "paused"].includes(d.state)) return null;
    if (d.next && d.next.ts) return d.state === "running" || d.next.kind === "retry" ? d.next : null;
    const last = (d.last_attempt && d.last_attempt.ts) || d.last_round_ts;
    return d.state === "running" && last && d.every_min ? {ts: last + d.every_min * 60000, kind: "round"} : null;
  }
  function stateKo(d) { return STATE[d.state] || [d.state_ko || d.state || "—", "thin"]; }
  function pillOf(d) { const [ko, cls] = stateKo(d); return cls === "live" ? ui.livePill(ko) : ui.pill(ko, cls); }
  const newestRunning = (d) => d.state === "running" && ((d.timeline || [])[0] || {}).status === "running";

  function render(d) {
    st.d = d;
    const sp = d.spend || {};
    const nx = nextOf(d);
    // state
    nextBox.firstChild.textContent = nx && nx.kind === "retry" ? "다시 시도까지" : "다음 회차까지";
    nextBox.hidden = !nx;
    const every = d.every_min || (d.next && d.next.every_min);
    put(stateBox,
      h("h3", null, "지금 상태"),
      h("div", {class: "db-strow"}, pillOf(d), newestRunning(d) ? ui.pill("지금 회차 진행 중", "accent") : null),
      d.reason ? h("p", {class: "db-reason"}, d.reason) : null,
      nextBox,
      h("p", {class: "db-small"}, every ? `${fmt.int(every)}분마다 한 회차 · 새 소식이 없으면 비용 없이 건너뜁니다` : "주기를 아직 모릅니다"),
      factoryLine(d.factory),
      ui.kv([["마지막 토론", d.last_round_ts ? `${fmt.kst(d.last_round_ts)} (${fmt.ago(d.last_round_ts)})` : "아직 없음"],
        ["모델", d.model || "—"]]));
    // cost
    const cap = sp.cap || 0, used = sp.month || 0, p = cap ? Math.min(1, used / cap) : 0;
    const td = d.today || null, avg = d.avg_round || null;
    put(costBox,
      h("h3", null, "이번 달 비용", h("small", null, "실제 비용 (유료 API) · 모의 계좌 돈 아님")),
      h("div", {class: "db-costv"}, h("b", {class: "num"}, usd(used)), h("span", {class: "muted"}, ` / 한도 ${cap ? usd(cap) : "—"}`),
        h("span", {class: "grow"}), h("span", {class: "db-today"}, "오늘 ", h("b", {class: "num"}, usd(sp.day)))),
      h("div", {class: ["db-cbar", p >= 0.95 ? "bad" : p >= 0.8 ? "warn" : ""], role: "img", "aria-label": `한도의 ${Math.round(p * 100)}%`},
        h("i", {style: {"--w": `${(p * 100).toFixed(1)}%`}}), h("span", {class: "db-c80", title: "80%: 텔레그램 경고"}), h("span", {class: "db-c95", title: "95%: 그달은 멈춤"})),
      h("p", {class: "db-small"}, `한도의 ${fmt.int(Math.round(p * 100))}% · 80%에서 경고, 95%부터 그달은 멈추고 다음 달 1일(한국 시간)에 이어집니다`),
      td ? h("p", {class: "db-small"}, `오늘 토론 ${fmt.int(td.ok)}번 · 건너뜀 ${fmt.int(td.skipped)}번 · 오류 ${fmt.int(td.error)}번`) : null,
      avg && avg.rounds_7d ? h("p", {class: "db-small"}, `회차당 평균 ${usd4(avg.cost_usd)} (최근 7일 ${fmt.int(avg.rounds_7d)}회)`) : null,
      deepCost(d.factory));
    // timeline: the newest rounds of every kind
    const tl = (d.timeline || (d.rounds || []).map((r) => ({...r, why: String(r.error || "").replace(/^unchanged:\s*/, "")}))).slice(0, 12);
    const run = d.state === "running";
    put(tlBox,
      h("h3", null, "최근 회차", h("small", null, tl.length ? `${fmt.int(tl.length)}번 · 새것이 위` : "")),
      tl.length ? h("div", {class: "db-dots", role: "img", "aria-label": `최근 ${tl.length}회차: 토론 ${tl.filter((r) => r.status === "ok").length}번, 건너뜀 ${tl.filter((r) => r.status === "skipped").length}번`},
        [...tl].reverse().map((r, i, a) => { const [ko, tone] = roundKo(r, i === a.length - 1, run); return h("i", {class: tone, title: `${fmt.kst(r.ts)} ${ko}`}); })) : null,
      tl.length ? h("ol", {class: "db-tlist"}, tl.map((r, i) => {
        const [ko, tone, detail, sub] = roundKo(r, i === 0, run);
        return h("li", {class: tone}, h("time", {title: fmt.kst(r.ts)}, fmt.dayKey(r.ts) === fmt.dayKey(Date.now()) ? fmt.hm(r.ts) : `${fmt.mmdd(r.ts)} ${fmt.hm(r.ts)}`),
          h("b", null, ko), h("span", {class: "db-tl-d"}, detail, sub ? h("small", {title: r.status === "skipped" ? String(r.why || "") : null}, sub) : null));
      })) : h("p", {class: "db-small"}, "아직 기록된 회차가 없습니다"));
    // the hypotheses ledger (the whole room's record: one model speaks every role)
    const sb = d.scoreboard || {}, by = sb.by_status || {}, easy = sb.easy || {};
    const g = sb.graded || 0, hit = sb.hit || 0;
    put(ledger,
      h("h3", null, "가설 장부", h("small", null, "코드가 기한 뒤 채점 · 결론 아님")),
      h("div", {class: "db-tiles"},
        h("div", {class: "db-tile wait"}, h("span", null, "채점 대기"), h("b", {class: "num"}, fmt.int(by.open || 0))),
        h("div", {class: "db-tile hit"}, h("span", null, "맞음"), h("b", {class: "num"}, fmt.int(hit))),
        h("div", {class: "db-tile miss"}, h("span", null, "틀림"), h("b", {class: "num"}, fmt.int(g - hit)))),
      h("p", {class: "db-small"}, g ? `방 전체 ${fmt.int(hit)}/${fmt.int(g)} 맞음 (${fmt.pct(sb.rate, 0, false)}) · 동전 던지기 50%` +
        (sb.expected_rate != null ? ` · 우연히 맞을 기대 ${fmt.pct(sb.expected_rate, 0, false)}` : "") : "아직 채점된 가설이 없습니다"),
      sb.small !== false ? h("p", {class: "db-warn"}, h("b", null, "표본 적음 "), `채점 ${fmt.int(g)}개 · ${fmt.int(sb.small_below || 10)}개 미만은 우연과 구별할 수 없습니다`) : null,
      easy.graded ? h("p", {class: "db-small"}, `원래 ${fmt.pct(easy.rate_from, 0, false)} 넘게 맞는 쉬운 예측 ${fmt.int(easy.graded)}개는 따로 셌습니다 (맞음 ${fmt.int(easy.hit)}개, 성적에 넣지 않음)`) : null,
      (by.dropped || by.void || by.expired) ? h("p", {class: "db-small"}, [by.dropped ? `메뉴에 안 맞아 버림 ${fmt.int(by.dropped)}` : "", by.void ? `무효 ${fmt.int(by.void)}` : "",
        by.expired ? `기한 지남 ${fmt.int(by.expired)}` : ""].filter(Boolean).join(" · ")) : null,
      hyps.el);
    hyps.set(d.hypotheses || [], true);
    // the summary line
    sumState.replaceChildren(pillOf(d));
    sumCost.textContent = `이번 달 ${usd(used)} / ${cap ? usd(cap) : "—"}`;
    tick();
  }

  function hypRow(x) {
    const cls = x.status === "graded" ? (String(x.outcome).startsWith("hit") ? "good" : "bad") : x.status === "open" ? "accent" : "thin";
    return h("div", {class: "db-hyp", role: "listitem"}, ui.pill(x.status_ko || x.status, cls),
      h("span", {class: "db-hyp-t"}, x.claim || x.kind || "", h("small", null, [x.horizon ? `기한 ${x.horizon}` : "", fmt.kst(x.ts)].filter(Boolean).join(" · "))));
  }

  /** every second: the countdown (the server's schedule; nothing else moves) */
  function tick() {
    const d = st.d;
    if (!d) return;
    const nx = nextOf(d);
    const t = nx ? countdown(nx.ts, serverNow()) : null;           // the server's clock (the page's may be off)
    nextNum.textContent = nx ? (t || "곧") : "—";
    nextWhat.textContent = !nx ? "" : t ? " 남음" : " · 차례가 됐습니다 (30초 안에 시작하거나 건너뜁니다)";
    sumNext.textContent = nx ? `${nx.kind === "retry" ? "다시 시도" : "다음 회차"} ${t || "곧"}` : "";
    return nx;
  }

  return {el, render, tick, nextOf};
}
