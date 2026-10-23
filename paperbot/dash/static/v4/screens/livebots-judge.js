// 실거래 › 규칙 점검 (#/livebots/judge, owners 10/19 night "규칙봇 15"): did the new rules help, since the new config started?
// /api/v4/livebots/judge (dash/more/liveinsight.py judge()), three cards:
//   빠른 손절 판정  every REV exit (the strategy's own reverse signal before the first lock) replayed as if it had been held
//                  under the -50 % net stop and the ladder (the bot's own math on the rule bot's 1m bars): would it have
//                  reached the first lock (+10 % or more), hit -50 %, or is it still undecided; what the early exit saved or
//                  cost in net ROE points and money at each account's own size
//   추격 막기 판정  every B-group signal the chase block stopped, and what it would have done if entered (the watcher's own
//                  virtual trade when it has one, else replayed the same way)
//   동전 쌍둥이     the paper account against its coin-flip twin (same signals, random side) since the start, and the gap
//                  in plain words; 성적 keeps the all-time twin block, this is the since-start head-to-head
//   두 페이퍼 비교  only while there are two paper bots (owners 10/19, docs/live15-mexc-ko.md): each one's trades, wins, win
//                  rate, net ROE sum, equity and deepest drop since the second one started, and "같은 진입 n번 중 결과가
//                  갈린 거래 m번" (the server's compare)
// HONESTY: a replay is arithmetic on the recorded bars, never a trade (said on every card); funding is left out (said);
// what could not be worked out says why; under 20 decided trades the card says it is mostly luck; the start of the
// config is the server's (sure or not, and how it knows); a failed refresh keeps the last answer dimmed with its age.
// 추세판단 봇 (the server's trend_bot, owners 10/21): every line says its own start ("추세판단 봇 시작 뒤"); a new card first,
//   감독 청산 판정  every supervisor exit (추세 뒤집힘 · 시간 정리, before the first lock) held instead under the stop and the
//                  ladder, the same replay as 빠른 손절 (which stays: the fast stop is still a rule; its note says the
//                  supervisor is not in that replay);
// 추격 막기 covers the members the server says (all of them in its config: no B group), each row with the member's role;
// 동전 쌍둥이 has no 75 % line (that was the old rules' analysis: none for a new rule set).
import {h, put, ui, fmt, motion, serverNow} from "../core/pb.js";
import {acctKo, sourceState, EXEC_SLOTS, execsKo} from "./livebots-kit.js";

export const JUDGE_API = "/api/v4/livebots/judge";
const REFRESH_MS = 60 * 1000;
const LIVE = EXEC_SLOTS;                  // the executors with live rows (the third, 플립스터, only while the server has it)


// ================================================================ pure functions (node tests: tests/test_dash_liveinsight.py)
const has = (x) => x != null && Number.isFinite(Number(x));
/** A ratio as percentage points: 0.308 -> "+30.8%p". */
export const pp = (x, dec = 1) => (has(x) ? `${fmt.num(Number(x) * 100, dec, true)}%p` : "—");

/** Since when, in one line: "규칙봇 15 시작 10/19 09:30부터 · 봇이 이 설정으로 켜진 때" (or why it is not sure). */
export function startWords(s) {
  if (!s) return "시작 시각 모름";
  const name = s.name || "지금 설정";
  if (s.ms == null) return `${name}: ${s.how_ko || "시작 시각을 몰라요"}`;
  return `${name} 시작 ${fmt.kst(s.ms)}부터 · ${s.how_ko || ""}${s.sure ? "" : " (확실하지 않음)"}`;
}

/** A replay's result in words: {ko, tone, kind} (kind won / lost / open / none). */
export function cfWords(cf) {
  if (!cf) return {ko: "—", tone: "", kind: "none"};
  if (cf.state === "won") {
    return {kind: "won", tone: "up", ko: cf.floor ? `첫 잠금 넘음 · 순ROE ${fmt.pct(cf.roe, 1)} 이상 (아직 진행 중)`
      : `이겼을 것 · ${fmt.pct(cf.roe, 1)}${cf.exit && cf.exit.reason_ko ? ` ${cf.exit.reason_ko}` : ""}`};
  }
  if (cf.state === "lost") return {kind: "lost", tone: "down", ko: `−50% 손절에 닿았을 것 · ${fmt.pct(cf.roe, 1)}`};
  if (cf.state === "open") {
    return {kind: "open", tone: "", ko: `아직 결정 안 남${has(cf.roe) ? ` · 지금 순ROE ${fmt.pct(cf.roe, 1)}` : ""}${cf.why_ko ? ` · ${cf.why_ko}` : ""}`};
  }
  const what = {no_data: "1분봉 없음", missing: "1분봉 수집 전", error: "못 읽음", unknown: "계산 못 함"}[cf.state] || "계산 못 함";
  return {kind: "none", tone: "", ko: `${what}${cf.why_ko ? ` · ${cf.why_ko}` : ""}`};
}

/** The bot's name for "… 시작 뒤" lines (the server's start name; the old one's "규칙봇 15"). */
export const botName = (s) => (s && s.name) || "규칙봇 15";

/** The early-exit verdict in one line (positive = the early exit saved: the real exit was better than holding). */
export function revVerdict(t, name = "규칙봇 15") {
  if (!t || !t.n) return {ko: `${name} 시작 뒤 빠른 손절로 닫힌 거래가 아직 없어요`, tone: ""};
  if (!t.decided) return {ko: `빠른 손절 ${fmt.int(t.n)}번 · 붙잡았다면 어땠을지 아직 결정 난 게 없어요`, tone: ""};
  const v = t.delta_roe;
  if (t.verdict === "saved") return {ko: `빠른 손절이 지금까지 순ROE 합 ${pp(v)} 아꼈어요`, tone: "up"};
  if (t.verdict === "cost") return {ko: `빠른 손절 때문에 지금까지 순ROE 합 ${pp(v)} 손해였어요`, tone: "down"};
  return {ko: "빠른 손절이 지금까지 아낀 것도 손해 본 것도 없어요 (본전)", tone: ""};
}

/** The supervisor's verdict (the trend bot): positive = closing early saved (the real exit beat holding). */
export function supVerdict(t, name = "추세판단 봇") {
  if (!t || !t.n) return {ko: `${name} 시작 뒤 감독 청산으로 닫힌 거래가 아직 없어요`, tone: ""};
  if (!t.decided) return {ko: `감독 청산 ${fmt.int(t.n)}번 · 붙잡았다면 어땠을지 아직 결정 난 게 없어요`, tone: ""};
  const v = t.delta_roe;
  if (t.verdict === "saved") return {ko: `감독 청산이 지금까지 순ROE 합 ${pp(v)} 아꼈어요`, tone: "up"};
  if (t.verdict === "cost") return {ko: `감독 청산 때문에 지금까지 순ROE 합 ${pp(v)} 손해였어요`, tone: "down"};
  return {ko: "감독 청산이 지금까지 아낀 것도 손해 본 것도 없어요 (본전)", tone: ""};
}

/** The chase-block verdict (a blocked loss saved, a blocked win cost). */
export function chaseVerdict(t, name = "규칙봇 15") {
  if (!t || !t.n) return {ko: `${name} 시작 뒤 추격 막기에 걸린 신호가 아직 없어요`, tone: ""};
  if (!t.decided) return {ko: `막힌 신호 ${fmt.int(t.n)}개 · 들어갔다면 어땠을지 아직 결정 난 게 없어요`, tone: ""};
  const v = t.roe_sum;
  if (t.verdict === "saved") return {ko: `추격 막기가 손해를 순ROE 합 ${pp(-v)} 줄였어요`, tone: "up"};
  if (t.verdict === "cost") return {ko: `추격 막기 때문에 이익 순ROE 합 ${pp(v)}를 놓쳤어요`, tone: "down"};
  return {ko: "추격 막기가 막은 신호들은 합쳐서 본전이었어요", tone: ""};
}

/** The coin-flip gap in plain words: "진짜 신호가 동전보다 승률 12.5%p 높음". */
export function twinWords(tw) {
  if (!tw || tw.state !== "ok") return null;
  if (!tw.real.n || !tw.flip.n) return "둘 중 하나가 아직 닫힌 거래가 없어서 견줄 수 없어요";
  const g = tw.gap;
  if (!has(g) || Math.abs(g) < 0.0005) return "진짜 신호와 동전의 승률이 같아요";
  return `진짜 신호가 동전보다 승률 ${fmt.num(Math.abs(g) * 100, 1)}%p ${g > 0 ? "높음" : "낮음"}`;
}

// ================================================================ the view
/** judgeView(ctx) -> {el, set()}: its own endpoint, read now and every 60 s. */
export function judgeView(ctx) {
  const st = {d: null, okAt: 0, sig: ""};
  const stateSlot = h("div", {class: "lb-slot"});
  const head = h("div", {class: "lbj-intro"});
  const revSlot = h("div", {class: "lbj-slot"});
  const chaseSlot = h("div", {class: "lbj-slot"});
  const twinSlot = h("div", {class: "lbj-slot"});
  const twoSlot = h("div", {class: "lbj-slot"});
  const twoCard = ui.card({title: "두 페이퍼 비교", sub: "같은 신호 · 손절만 다름 · 두 번째 봇 시작부터", cls: "lbj-card lbj-two"}, twoSlot);
  twoCard.hidden = true;
  const revPg = ui.pager({size: 10, row: (r) => revRow(r), empty: () => (st.d ? ui.empty("빠른 손절로 닫힌 거래가 아직 없어요") : motion.shimmer(2))});
  const chasePg = ui.pager({size: 10, row: (r) => chaseRow(r), empty: () => (st.d ? ui.empty("추격 막기에 걸린 신호가 아직 없어요") : motion.shimmer(2))});
  const supSlotIn = h("div", {class: "lbj-slot"});
  const supPg = ui.pager({size: 10, row: (r) => revRow(r, true), empty: () => (st.d ? ui.empty("감독 청산으로 닫힌 거래가 아직 없어요") : motion.shimmer(2))});
  const supCard = ui.card({title: "감독 청산 판정", sub: "추세가 뒤집혀서 · 시간이 다 돼서 일찍 닫은 거래를 붙잡고 있었다면", cls: "lbj-card lbj-sup"}, supSlotIn, supPg.el);
  const supSlot = h("div", {class: "lb-slot stack"});      // the trend bot only (draw)
  const chaseCard = ui.card({title: "추격 막기 판정", sub: "B 그룹이 막은 신호에 들어갔다면", cls: "lbj-card lbj-chase"}, chaseSlot, chasePg.el);
  const twinCard = ui.card({title: "동전 쌍둥이 비교", sub: "같은 신호 · 방향만 동전 · 규칙봇 15 시작부터", cls: "lbj-card lbj-twin"}, twinSlot);
  const body = h("div", {class: "lbj-body stack"}, head, supSlot,
    ui.card({title: "빠른 손절 판정", sub: "반대 신호로 일찍 닫은 거래를 붙잡고 있었다면", cls: "lbj-card lbj-rev"}, revSlot, revPg.el),
    chaseCard, twinCard,
    twoCard,
    h("div", {class: "lb-foot"}, ui.assumeLine(["closed"], "페이퍼(연습) 손익 · 다시 계산한 결과는 가상이에요"),
      ui.assumeLive(`${execsKo()}: 따라간 거래의 크기로 셈`)));
  const el = h("div", {class: "lbj stack"}, stateSlot, body);

  const money = (x) => (has(x) ? `${fmt.money(x, true)} USDT` : "—");
  const cardPart = (card) => (card && card.firstChild ? Array.from(card.firstChild.childNodes).find((n) => String(n.className || "") === "sub") || null : null);
  const say = (node, text) => { if (node && node.textContent !== text) node.textContent = text; };
  const num = (x, cls) => h("b", {class: ["num", fmt.tone(x, pp(x)), cls]}, pp(x));
  const chip = (n, unit, ko, cls) => h("span", {class: ["lbj-chip", cls]}, h("b", {class: "num"}, `${fmt.int(n)}${unit}`), ` ${ko}`);

  function revRow(r, sup = false) {
    const w = cfWords(r.cf);
    const how = sup ? (r.exit_reason === "TIME" ? "시간 정리" : r.exit_reason === "JUDGE" ? "추세 뒤집힘" : (r.exit_ko || "감독 청산")) : "빠른 손절";
    return h("div", {class: ["lbj-row", "k-" + w.kind], role: "listitem", title: sup && r.why ? r.why : null},
      h("span", {class: "lbj-rt num muted"}, fmt.kst(r.exit_time)),
      h("span", {class: "lbj-rc"}, h("b", null, fmt.coin(r.symbol)), ui.sideTag(r.side),
        h("span", {class: "muted"}, ` ${fmt.stratKo(r.strategy_id)} · ${fmt.tfKo(r.timeframe)}`),
        r.group && r.group !== "old" ? h("span", {class: "lbj-g"}, r.group) : null),
      h("span", {class: "lbj-rv"}, h("small", null, `실제 (${how})`), h("b", {class: ["num", fmt.tone(r.roe, fmt.pct(r.roe, 1))]}, fmt.pct(r.roe, 1))),
      h("span", {class: ["lbj-rcf", w.tone]}, h("small", null, "붙잡았다면"), h("span", null, w.ko)),
      h("span", {class: "lbj-rv"}, h("small", null, has(r.delta_roe) ? (r.delta_roe >= 0 ? "아낌" : "손해") : "차이"),
        has(r.delta_roe) ? num(r.delta_roe) : h("b", {class: "num muted"}, "—")));
  }
  function chaseRow(r) {
    const w = cfWords(r.cf);
    return h("div", {class: ["lbj-row", "k-" + w.kind], role: "listitem"},
      h("span", {class: "lbj-rt num muted"}, fmt.kst(r.t)),
      h("span", {class: "lbj-rc"}, h("b", null, fmt.coin(r.symbol)), ui.sideTag(r.side),
        h("span", {class: "muted"}, ` ${fmt.stratKo(r.strategy)} · ${fmt.tfKo(r.tf)}`), r.group ? h("span", {class: "lbj-g"}, r.group) : null),
      h("span", {class: "lbj-rwhy muted"}, r.why || "추격 진입 막기"),
      h("span", {class: ["lbj-rcf", w.tone]}, h("small", null, "들어갔다면"), h("span", null, w.ko)),
      h("span", {class: "lbj-src", title: r.cf && r.cf.source === "missed" ? "1분 감시가 페이퍼 봇 엔진으로 계산한 가상 거래" : "이 화면이 1분봉으로 다시 계산"},
        r.cf && r.cf.source === "missed" ? "감시 계산" : "다시 계산"));
  }

  function drawRev(d) {
    const a = d.rev || {};
    if (a.state !== "ok") { put(revSlot, h("p", {class: "lbj-rule"}, a.ko || ""), sourceState(a, "페이퍼 DB")); revPg.set([]); return; }
    const t = a.totals || {};
    const v = revVerdict(t, botName(d.start));
    const live = LIVE.filter((id) => t.live && t.live[id] && t.live[id].n);
    put(revSlot, h("p", {class: "lbj-rule"}, a.ko),
      h("div", {class: ["lbj-hero", v.tone]}, h("b", {class: "lbj-big"}, v.ko),
        t.decided ? h("span", {class: "lbj-money"}, `돈으로 (각 계좌 크기): 페이퍼 ${money(t.delta_pnl)}`,
          ...live.map((id) => ` · ${acctKo(id)} ${money(t.live[id].delta_pnl)} (${fmt.int(t.live[id].n)}번)`)) : null),
      // the chips' colour = good or bad for the rule (as on 추격 막기): a hold that would have lost is what the rule saved
      t.n ? h("div", {class: "lbj-chips"}, chip(t.lost, "번", "−50%에 닿았을 것 (빨리 닫아 아낌)", "up"), chip(t.won, "번", "이겼을 것 (빨리 닫아 놓침)", "down"),
        chip(t.open, "번", "아직 모름", ""), t.unknown ? chip(t.unknown, "번", "계산 못 함", "thin") : null) : null,
      t.decided && t.decided < (d.small_n || 20) ? ui.note(`결정 난 거래 ${fmt.int(t.decided)}번이라 아직 우연이 커요 (${fmt.int(d.small_n || 20)}번 미만)`) : null,
      ui.note("붙잡았다면 = 같은 진입·같은 손절(−50%)·같은 계단 익절로 규칙봇 1분봉을 다시 계산한 가상 결과 · ", a.funding_ko || "",
        " · 그동안 다른 진입을 못 했을 수 있는 건 셈에 넣지 않았어요"),
      a.hold_ko ? ui.note(a.hold_ko) : null);
    revPg.set(a.rows || [], true);
  }
  function drawSup(d) {
    const a = d.sup;
    if (!a) { put(supSlot); supPg.set([]); return; }
    if (supCard.parentNode !== supSlot) put(supSlot, supCard);
    if (a.state !== "ok") { put(supSlotIn, h("p", {class: "lbj-rule"}, a.ko || ""), sourceState(a, "페이퍼 DB")); supPg.set([]); return; }
    const t = a.totals || {};
    const v = supVerdict(t, botName(d.start));
    const live = LIVE.filter((id) => t.live && t.live[id] && t.live[id].n);
    const by = a.by_reason || {};
    put(supSlotIn, h("p", {class: "lbj-rule"}, a.ko),
      h("div", {class: ["lbj-hero", v.tone]}, h("b", {class: "lbj-big"}, v.ko),
        t.decided ? h("span", {class: "lbj-money"}, `돈으로 (각 계좌 크기): 페이퍼 ${money(t.delta_pnl)}`,
          ...live.map((id) => ` · ${acctKo(id)} ${money(t.live[id].delta_pnl)} (${fmt.int(t.live[id].n)}번)`)) : null),
      t.n ? h("div", {class: "lbj-chips"}, chip(by.JUDGE || 0, "번", "추세 뒤집힘", "thin"), chip(by.TIME || 0, "번", "시간 정리", "thin"),
        chip(t.lost, "번", "−50%에 닿았을 것 (일찍 닫아 아낌)", "up"), chip(t.won, "번", "이겼을 것 (일찍 닫아 놓침)", "down"),
        chip(t.open, "번", "아직 모름", ""), t.unknown ? chip(t.unknown, "번", "계산 못 함", "thin") : null) : null,
      t.decided && t.decided < (d.small_n || 20) ? ui.note(`결정 난 거래 ${fmt.int(t.decided)}번이라 아직 우연이 커요 (${fmt.int(d.small_n || 20)}번 미만)`) : null,
      ui.note("붙잡았다면 = 감독 없이 같은 진입·같은 손절(−50%)·같은 계단 익절로 규칙봇 1분봉을 다시 계산한 가상 결과 · ", a.funding_ko || "",
        " · 그동안 다른 진입을 못 했을 수 있는 건 셈에 넣지 않았어요"));
    supPg.set(a.rows || [], true);
  }
  function drawChase(d) {
    const a = d.chase || {};
    if (a.state !== "ok") { put(chaseSlot, h("p", {class: "lbj-rule"}, a.ko || ""), sourceState(a, "페이퍼 DB 신호 기록")); chasePg.set([]); return; }
    const t = a.totals || {};
    const v = chaseVerdict(t, botName(d.start));
    put(chaseSlot, h("p", {class: "lbj-rule"}, a.ko),
      h("div", {class: ["lbj-hero", v.tone]}, h("b", {class: "lbj-big"}, v.ko),
        t.pnl_n ? h("span", {class: "lbj-money"}, `막힌 신호에 들어갔다면 페이퍼 크기로 ${money(t.pnl)} (${fmt.int(t.pnl_n)}개)`) : null),
      t.n ? h("div", {class: "lbj-chips"}, chip(t.lost, "개", "−50%에 닿았을 것 (막아서 아낌)", "up"), chip(t.won, "개", "이겼을 것 (막아서 놓침)", "down"),
        chip(t.open, "개", "아직 모름", ""), t.unknown ? chip(t.unknown, "개", "계산 못 함", "thin") : null) : null,
      a.missed && a.missed.state !== "ok" && t.n ? ui.note(`1분 감시 기록이 없어 (${a.missed.reason_ko || "수집 전"}) 이 화면이 1분봉으로 다시 계산했어요`) : null,
      t.decided && t.decided < (d.small_n || 20) ? ui.note(`결정 난 신호 ${fmt.int(t.decided)}개라 아직 우연이 커요 (${fmt.int(d.small_n || 20)}개 미만)`) : null,
      ui.note("들어갔다면 = 신호 때 참고 가격으로 들어가 같은 손절·계단 익절로 계산한 가상 결과 (한 번에 하나 규칙은 빼고) · ", a.funding_ko || ""));
    chasePg.set(a.rows || [], true);
  }
  function drawTwin(d) {
    const tw = d.twin || {};
    if (tw.state !== "ok") { put(twinSlot, sourceState(tw, "동전 쌍둥이 기록")); return; }
    const col = (title, x, cls) => h("div", {class: ["lbj-tcol", cls]}, h("b", {class: "lbj-tt"}, title),
      ui.kv([["거래", `${fmt.int(x.n)}번`], ["이김", `${fmt.int(x.wins)}번`], ["승률", has(x.win_rate) ? fmt.pct(x.win_rate, 1, false) : "—"],
        ["순ROE 합", h("b", {class: ["num", fmt.tone(x.roe_sum, fmt.pct(x.roe_sum, 1))]}, fmt.pct(x.roe_sum, 1))],
        ["잔고", has(x.wallet) ? `${fmt.money(x.wallet)} USDT${has(x.change) ? ` (${fmt.pct(x.change, 1)})` : ""}` : "—"]]));
    const words = twinWords(tw);
    const g = tw.gap;
    put(twinSlot, h("div", {class: "lbj-twin2"}, col("진짜 신호 (페이퍼)", tw.real, "real"), col("동전 쌍둥이", tw.flip, "flip")),
      words ? h("p", {class: ["lbj-gap", has(g) && Math.abs(g) >= 0.0005 ? (g > 0 ? "up" : "down") : ""]}, words) : null,
      tw.small ? h("p", {class: "lbj-luck"}, `거래 ${fmt.int(Math.min(tw.real.n, tw.flip.n))}개라 아직 우연이 커요 (${fmt.int(tw.small_n)}개 넘어야 조금 믿을 만)`) : null,
      has(tw.ref_flip_win)
        ? h("p", {class: "note"}, ui.pill("", "ref"), ` 참고 · 예전 분석에서 새 규칙의 동전 승률은 약 ${fmt.pct(tw.ref_flip_win, 0, false)}였어요 · 비교일 뿐 실력의 증거가 아니에요`)
        : h("p", {class: "note"}, ui.pill("", "ref"), " 견줄 동전 승률 기준이 없어요 (새 규칙이라 지난 분석이 없어요) · 비교일 뿐 실력의 증거가 아니에요"));
  }
  function drawTwo(d) {
    const c = d.compare;
    twoCard.hidden = !c;                                  // one paper bot: no card (the page as before)
    if (!c) { put(twoSlot); return; }
    // two different bots (the server's twin false, owners 10/23): side by side by name, no "손절만 다름"
    say(cardPart(twoCard), c.twin === false ? "두 봇 나란히 · 매매법이 서로 달라요 · 둘 다 돌던 때부터" : "같은 신호 · 손절만 다름 · 두 번째 봇 시작부터");
    if (c.state !== "ok") { put(twoSlot, sourceState(c, "두 번째 페이퍼 기록")); return; }
    const col = (x) => h("div", {class: ["lbj-tcol", x.id]}, h("b", {class: "lbj-tt"}, x.label_ko || x.id),
      ui.kv([["거래", `${fmt.int(x.n)}번`], ["이김", `${fmt.int(x.wins)}번`], ["승률", has(x.win_rate) ? fmt.pct(x.win_rate, 1, false) : "—"],
        ["순ROE 합", h("b", {class: ["num", fmt.tone(x.roe_sum, fmt.pct(x.roe_sum, 1))]}, fmt.pct(x.roe_sum, 1))],
        ["잔고", has(x.equity) ? `${fmt.money(x.equity)} USDT${has(x.change) ? ` (${fmt.pct(x.change, 1)})` : ""}` : "—"],
        ["최대 낙폭", has(x.max_dd) ? fmt.pct(-x.max_dd, 1) : "—"]]));
    const rows = c.rows || [];
    put(twoSlot, h("div", {class: "lbj-twin2"}, ...rows.map(col)),
      h("p", {class: "lbj-gap"}, c.words_ko),
      c.since_ms ? h("p", {class: "note"}, `${fmt.kst(c.since_ms)}부터 · ${c.note_ko || ""}`) : null,
      (c.parted_rows || []).length ? h("ul", {class: "lbj-parted"}, (c.parted_rows || []).slice(0, 10).map((r) => h("li", null,
        `${fmt.kst(r.entry_time)} ${fmt.coin(r.symbol)} ${fmt.sideKo(r.side)} ${r.strategy_id ? fmt.stratKo(r.strategy_id) : ""} · `,
        ...rows.map((x, i) => { const v = r[x.id] || {}; return [i ? " / " : "", `${(x.label_ko || "").split(" (")[0]} `, h("b", {class: ["num", fmt.tone(v.roe, fmt.pct(v.roe, 1))]}, fmt.pct(v.roe, 1))]; })))) : null,
      ui.smallSample(Math.min(...rows.map((x) => x.n || 0)), 20));
  }
  function draw() {
    const d = st.d;
    if (!d) { put(head, motion.shimmer(1)); put(revSlot, motion.shimmer(2, true)); put(chaseSlot); put(twinSlot); revPg.set(undefined); chasePg.set(undefined); return; }
    const s = d.start || {};
    put(head, h("b", null, "새 규칙이 실제로 도왔나?"), h("span", {class: "muted"}, ` · ${startWords(s)}`),
      d.paper && d.paper.state !== "ok" ? sourceState(d.paper, "페이퍼 DB") : null,
      s.combo && s.combo.state && s.combo.state !== "ok" ? sourceState(s.combo, "합친 봇 설정") : null);
    const trend = !!d.trend_bot;
    say(cardPart(chaseCard), trend ? "추격 막기가 막은 신호에 들어갔다면" : "B 그룹이 막은 신호에 들어갔다면");
    say(cardPart(twinCard), `같은 신호 · 방향만 동전 · ${botName(s)} 시작부터`);
    drawSup(d); drawRev(d); drawChase(d); drawTwin(d); drawTwo(d);
  }
  async function load() {
    let d;
    try { d = await ctx.api(JUDGE_API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      ui.dim(body, !!st.d);
      throw e;
    }
    if (!ctx.alive()) return;
    st.okAt = serverNow();
    put(stateSlot);
    ui.dim(body, false);
    const sig = JSON.stringify({...d, now_ms: 0});
    if (st.d && sig === st.sig) return;                   // the same records again: nothing redrawn, the page stays put
    st.d = d; st.sig = sig;
    draw();
  }
  draw();
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  return {el, set() {}};
}
