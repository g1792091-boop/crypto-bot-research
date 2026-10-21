// 실거래 › 못 탄 신호 (#/livebots/missed; owners 10/19 "못 탄 신호들은 어땠나", "진입을 안 했는데 좋은 놓친 신호 분석 같은 거"):
// every signal the paper bot (A+C 합본, COMBO@mix, the one both executors follow) did not take and what it would have done,
// by why it was not taken, and the paper trades the executors did not follow (their paper result): /api/v4/livebots/missed
// (dash/more/livemissed.py; the 1-minute watcher's pass paperbot/livemissed.py simulates each signal on the paper bot's own
// engine with the rule bot's 1m bars, paperbot/livesim.py). View only: no rule of the bots changes here.
//   머리   못 탄 신호는 어땠을까? · 최근 7일 | 기록 전체 · the cards: 실제로 탄 거래, then each group (한 번에 하나 · 연구 조건 밖 ·
//          돌파 없음 · 쉬는 시간 · 늦음·재시작 · 실행기가 안 따라감): count, 이김 / 짐 at the same size, win rate, net ROE sum and
//          mean, the other states, the one-line read ("… → 이번엔 막은 게 손해를 줄였어요"), 표본 적음 under 20
//   목록   group chips (전체 / 그룹별, with counts) and a result filter (전체 / 이겼을 신호 / 졌을 신호); the chosen group's totals
//          for BOTH sides stay above the list whatever the filter; newest first, 10 a page: time, coin, 롱/숏, strategy · tf,
//          the group, why, the virtual result and how it was computed ("돌파를 안 기다리고 바로 탔다면"), hold, the trade taken
//   발    always on screen: 가상 결과 · 필터는 5년 시험에서 나쁜 자리를 거른 것 · 13장 순서, and the funding note
// HONESTY: never a "good ones only" view without the totals of both sides next to it; the watcher's file or table not there
// yet = 수집 전, unreadable = 못 읽음 + why (never an empty list); a refresh that fails keeps the last answer, dimmed, with its
// age; no virtual price is ever made up (1분봉 없음 / 다시 못 만듦 with the reason).
import {h, put, ui, fmt, local, motion} from "../core/pb.js";
import {sourceState} from "./livebots-kit.js";

export const API = "/api/v4/livebots/missed";
const REFRESH_MS = 30 * 1000;                // the watcher computes every minute; the server caches 5 s
const SPAN_KEY = "lb-missed-span", GROUP_KEY = "lb-missed-group", RESULT_KEY = "lb-missed-result";
const PAGE = 10;
export const SPANS = [{id: "7d", label: "최근 7일"}, {id: "all", label: "기록 전체"}];
export const GROUPS = [{id: "one", label: "한 번에 하나"}, {id: "research", label: "연구 조건 밖"}, {id: "nobreak", label: "돌파 없음"},
  {id: "pause", label: "쉬는 시간"}, {id: "late", label: "늦음·재시작"}, {id: "exec", label: "실행기가 안 따라감"}];
export const RESULTS = [{id: "all", label: "전체"}, {id: "win", label: "이겼을 신호"}, {id: "loss", label: "졌을 신호"}];
export const SMALL_N = 20;
// the server's words (dash/more/livemissed.py note_ko / filter_note_ko / funding_ko), here too so the foot is there before the
// first answer
export const NOTE = "가상 결과예요: 페이퍼 봇과 같은 엔진·같은 1분봉으로 계산했지만 실제 체결이 아니에요. 1포지션 규칙은 그대로이고, 이건 "
  + "바꾸자는 뜻이 아니라 보기만 하는 거예요. 거래가 적을 때는 대부분 운이에요.";
export const FILTER_NOTE = "필터는 5년 시험에서 평균적으로 나쁜 자리를 걸렀기 때문에 넣은 거예요. 이긴 것만 보면 아쉬움만 커져요: 진 것과 같이 "
  + "봐야 해요. 규칙을 바꿀지는 두 분이 정하고, 바꾸려면 13장 순서(백테스트 → 그림자 → 채택)를 따라요.";
export const FUNDING = "펀딩비는 빠져 있어요: 페이퍼 봇은 바이낸스 펀딩비(8시간마다)를 내지만 그 비율은 어디에도 기록되지 않아서 "
  + "가상 결과에는 넣지 못했어요 (보통 8시간에 순ROE 0.3%p 안팎)";
const EXIT_KO = {SL: "손절", LOCK: "계단 익절", LIQ: "강제청산", HALT: "멈춤 청산", MANUAL: "수동 청산", REV: "빠른 청산", JUDGE: "감독 청산(추세 뒤집힘)",
  TIME: "감독 청산(시간 정리)", TP: "익절", END: "끝"};
const GROUP_LABEL = Object.fromEntries(GROUPS.map((g) => [g.id, g.label]));
const RESULT_LABEL = Object.fromEntries(RESULTS.map((r) => [r.id, r.label]));

// ---------------------------------------------------------------- pure functions (node tests: tests/test_dash_livebots_missed.py)
const numOr = (x) => (x == null || x === "" || typeof x === "boolean" || !Number.isFinite(Number(x)) ? null : Number(x));
export const spanOf = (v) => (SPANS.some((s) => s.id === v) ? v : "7d");
export const groupOf = (v) => (v === "all" || GROUPS.some((g) => g.id === v) ? v : "all");
export const resOf = (v) => (RESULTS.some((r) => r.id === v) ? v : "all");

/** The virtual result of a row: {icon, text, tone, why}. tone: up / down / open / thin / bad. */
export function resultOf(r) {
  const st = r && r.state, roe = numOr(r && r.roe);
  if (st === "closed") {
    const win = !!r.win;
    return {icon: win ? "✅" : "❌", text: `${fmt.pct(roe, 1)} ${r.reason_ko || EXIT_KO[r.reason] || r.reason || ""}`.trim(), tone: win ? "up" : "down"};
  }
  if (st === "open") return {icon: "", text: `진행 중 ${fmt.pct(roe, 1)}`, tone: "open"};
  if (st === "no_data") return {icon: "", text: "1분봉 없음", tone: "thin"};
  if (st === "refused") return {icon: "", text: "진입 안 됨", tone: "thin", why: r.note || "엔진이 거절했어요"};
  if (st === "rebuild_failed") return {icon: "", text: "다시 못 만듦", tone: "thin", why: r.note || "이유 기록 없음"};
  return {icon: "", text: "못 읽음", tone: "bad", why: (r && r.error) || "이유 기록 없음"};
}
/** "✅ +11.2% 계단 익절" / "진행 중 +4.0%" / "1분봉 없음". */
export const resultText = (r) => { const x = resultOf(r); return [x.icon, x.text].filter(Boolean).join(" "); };

/** "그때 탄 거래: BTC 롱 +19.8%" / "… 진행 중 +3.1%" / "그때 탄 거래: 기록 못 찾음". */
export function takenText(t) {
  if (!t) return "그때 탄 거래: 기록 못 찾음";
  const head = `그때 탄 거래: ${fmt.coin(t.symbol)} ${fmt.sideKo(t.side)}`;
  const roe = numOr(t.roe);
  if (t.state === "open") return roe == null ? `${head} 진행 중` : `${head} 진행 중 ${fmt.pct(roe, 1)}`;
  return roe == null ? head : `${head} ${fmt.pct(roe, 1)}`;
}
/** Hold time: closed = exit − entry, open = so far; "—" when unknown. */
export const holdText = (r) => (r && numOr(r.hold_ms) != null ? fmt.dur(Number(r.hold_ms) / 1000) : "—");

/** One block's numbers in words: {count, closed, wins, losses, rate, sum, mean, small}. unit: "번" (trades) / "개" (signals). */
export function blockWords(b, unit) {
  if (!b) return null;
  return {count: `${fmt.int(b.n || 0)}${unit}`, closed: b.closed || 0, wins: fmt.int(b.wins || 0), losses: fmt.int(b.losses || 0),
    rate: b.win_rate == null ? "—" : fmt.pct(b.win_rate, 0, false), sum: b.closed ? fmt.pct(b.roe_sum, 1) : "—",
    mean: b.roe_mean == null ? "—" : fmt.pct(b.roe_mean, 1), small: !!b.small};
}

/** A block's other states in words: "진행 중 2 · 1분봉 없음 1 · 진입 안 됨 1 · 다시 못 만듦 1 · 못 읽음 1" ('' when none). */
export function otherLine(m) {
  if (!m) return "";
  return [["open", "진행 중"], ["no_data", "1분봉 없음"], ["refused", "진입 안 됨"], ["rebuild_failed", "다시 못 만듦"], ["error", "못 읽음"]]
    .filter(([k]) => m[k]).map(([k, ko]) => `${ko} ${fmt.int(m[k])}`).join(" · ");
}

/** The chosen group's totals for both sides, whatever the result filter: "연구 조건 밖: 이김 12 · 짐 9 · 진행 중 3 (전체 24개) ·
 *  보이는 것: 이겼을 신호 12개". */
export function listLine(list, result) {
  if (!list) return "";
  const head = `${list.group_ko || "전체"}: 이김 ${fmt.int(list.wins || 0)} · 짐 ${fmt.int(list.losses || 0)}`;
  const other = otherLine(list);
  const shown = resOf(result) === "all" ? "" : ` · 보이는 것: ${RESULT_LABEL[resOf(result)]} ${fmt.int(list.shown || 0)}개`;
  return `${head}${other ? ` · ${other}` : ""} (전체 ${fmt.int(list.n || 0)}개)${shown}`;
}

/** The group chips with their counts: [{id, label}] for ui.seg. */
export const groupChips = (counts) => [{id: "all", label: `전체 ${fmt.int((counts && counts.all) || 0)}`},
  ...GROUPS.map((g) => ({id: g.id, label: `${g.label} ${fmt.int((counts && counts[g.id]) || 0)}`}))];

/** The answer without what moves on its own (the clock, the pass time, a row's last computation): the same records draw nothing. */
export function sameKey(d) {
  if (!d) return "";
  const p = d.pass ? {...d.pass, last_ms: 0, stale: false} : null;
  return JSON.stringify({...d, now_ms: 0, pass: p, rows: (d.rows || []).map(({updated_ts: _u, sims: _s, ...r}) => r)});
}

/** The watcher's last pass in words. */
export function passLine(p, now = Date.now()) {
  if (!p) return "";
  if (!p.last_ms) return "1분 감시가 아직 계산 전이에요";
  const at = `마지막 계산 ${fmt.hm(p.last_ms)} (${fmt.ago(p.last_ms, now)})`;
  return p.stale ? `${at} · 1분 감시가 10분 넘게 계산하지 않았어요` : `${at} · 1분 감시가 매분 다시 계산`;
}

// ---------------------------------------------------------------- the view
/** missedView(ctx) -> {el}: its own endpoint every 30 s; the span, group and result chosen are remembered on this device. */
export function missedView(ctx) {
  const st = {span: spanOf(local.get(SPAN_KEY, "7d")), group: groupOf(local.get(GROUP_KEY, "all")), result: resOf(local.get(RESULT_KEY, "all")),
    d: null, key: "", okAt: 0};
  const choose = (k, store, v) => { st[k] = v; local.set(store, v); st.key = ""; load(true).catch(() => {}); };
  const spanSeg = ui.seg(SPANS, st.span, (id) => choose("span", SPAN_KEY, spanOf(id)), {label: "기간"});
  const groupSlot = h("div", {class: "lbm-gseg"});
  const resSeg = ui.seg(RESULTS, st.result, (id) => choose("result", RESULT_KEY, resOf(id)), {label: "결과"});
  const stateSlot = h("div", {class: "lb-slot"});
  const srcSlot = h("div", {class: "lb-slot"});
  const cards = h("div", {class: "lbm-cards", role: "list", "aria-label": "왜 못 탔나, 그룹마다"}, motion.shimmer(3));
  const small = h("p", {class: "lbm-small"});
  const passEl = h("p", {class: "lbm-pass"});
  const tot = h("p", {class: "lbm-tot", role: "status"});
  const pg = ui.pager({size: PAGE, row: (r) => rowEl(r), empty: () => (st.d ? ui.empty(st.result === "all" ? "이 기간·이 그룹에 못 탄 신호가 없어요"
    : `이 그룹에 ${RESULT_LABEL[st.result]}이 없어요 (위 숫자가 전체예요)`) : motion.shimmer(3))});
  const listCard = ui.card({title: "신호 하나씩", sub: "최신 먼저 · 10개씩 · 한국 시간", cls: "lbm-list"},
    groupSlot, h("div", {class: "lbm-rbar"}, resSeg), tot, pg.el);
  const foot = h("div", {class: "lbm-foot", role: "note"});
  const body = h("div", {class: "lbm-body"},
    h("section", {class: "lbm-head", "aria-label": "못 탄 신호는 어땠을까"},
      h("div", {class: "lbm-htop"}, h("h2", null, "못 탄 신호는 어땠을까?"), spanSeg),
      h("p", {class: "lbm-sub"}, "봇이 안 들어간 신호를, 왜 못 탔는지 그룹마다, 페이퍼 봇과 같은 엔진으로 따라가 봤어요"),
      srcSlot, cards, small, passEl),
    listCard);
  const el = h("div", {class: "lbm"}, stateSlot, body, foot);

  function card(cls, title, b, unit, extra, read) {
    const w = blockWords(b, unit);
    if (!b.n && cls !== "taken") {
      return h("div", {class: ["lbm-blk", cls, "none"], role: "listitem", "aria-label": title}, h("h3", null, title),
        h("p", {class: "lbm-read"}, read || "이 기간에 없어요"));
    }
    return h("div", {class: ["lbm-blk", cls], role: "listitem", "aria-label": title},
      h("h3", null, title),
      h("b", {class: "lbm-n num"}, w.count),
      h("p", {class: "lbm-closed"}, unit === "개" ? `끝난 것 ${fmt.int(w.closed)}개` : `닫힌 거래 ${fmt.int(w.closed)}번`),
      h("div", {class: "lbm-wl"},
        h("span", {class: "lbm-w"}, h("span", {class: "k"}, "이김"), h("b", {class: "num"}, w.wins)),
        h("span", {class: "lbm-l"}, h("span", {class: "k"}, "짐"), h("b", {class: "num"}, w.losses))),
      h("dl", {class: "lbm-kv"},
        h("div", null, h("dt", null, "승률"), h("dd", {class: "num"}, w.rate)),
        h("div", null, h("dt", null, "순ROE 합"), h("dd", {class: ["num", fmt.tone(b.roe_sum, w.sum)]}, w.sum)),
        h("div", null, h("dt", null, "한 번 평균"), h("dd", {class: ["num", fmt.tone(b.roe_mean, w.mean)]}, w.mean))),
      extra ? h("p", {class: "lbm-extra"}, extra) : null,
      read ? h("p", {class: "lbm-read"}, read) : null,
      w.small ? ui.pill("표본 적음", "thin", `닫힌 것 ${SMALL_N}번 미만: 대부분 운이에요`) : null);
  }
  function drawCards(d) {
    const s = d.summary || {};
    const left = s.taken ? card("taken", "실제로 탄 거래", s.taken, "번", s.taken.open ? `진행 중 ${fmt.int(s.taken.open)}번 (닫히면 셈)` : "",
      "페이퍼 봇이 같은 기간에 실제로 들어간 거래")
      : h("div", {class: "lbm-blk taken", role: "listitem"}, h("h3", null, "실제로 탄 거래"), sourceState(d.paper || {state: "missing"}, "페이퍼 DB"));
    put(cards, left, (s.groups || []).map((g) => card(`g-${g.id}`, g.ko, g, g.id === "exec" ? "번" : "개", otherLine({...g, open: g.open}), g.read_ko)));
    const anySmall = (s.taken && s.taken.small) || (s.groups || []).some((g) => g.n && g.small);
    put(small, anySmall ? [h("b", null, "표본 적음"), ` · 닫힌 것 ${SMALL_N}번 미만은 대부분 운이에요. 이긴 것만 보지 말고 진 것과 같이 보세요`] : null);
  }
  function rowEl(r) {
    const x = resultOf(r);
    return h("div", {class: ["lbm-row", r.state, x.tone], role: "listitem"},
      h("span", {class: "lbm-t num"}, fmt.kst(r.t)),
      h("span", {class: "lbm-c"}, h("b", null, fmt.coin(r.symbol)), ui.sideTag(r.side)),
      h("span", {class: "lbm-s", title: r.member || ""}, `${fmt.stratKo(r.strategy)} · ${fmt.tfKo(r.tf)}`),
      h("span", {class: "lbm-why"}, h("span", {class: ["lbm-g", `g-${r.grp}`]}, r.grp_ko || GROUP_LABEL[r.grp] || r.grp), " ",
        h("span", {title: r.why_kind_ko || ""}, r.why || r.why_kind_ko || "—")),
      h("span", {class: ["lbm-res", x.tone], title: x.why || (r.stop_rule ? `손절: ${r.stop_rule}` : "")},
        x.icon ? h("i", {"aria-hidden": "true"}, x.icon) : null, h("b", {class: "num"}, x.text), x.why ? h("small", null, x.why) : null,
        r.how_ko ? h("small", {class: "lbm-how"}, r.how_ko) : null),
      h("span", {class: "lbm-hold num", title: "들고 있던 시간 (진행 중이면 지금까지)"}, holdText(r)),
      h("span", {class: ["lbm-tk", r.taken && r.taken.state === "open" ? "open" : ""]}, r.grp === "one" ? takenText(r.taken) : ""));
  }
  function drawFoot(d) {
    put(foot, h("p", null, (d && d.note_ko) || NOTE), h("p", null, (d && d.filter_note_ko) || FILTER_NOTE),
      !(d && d.funding_included) ? h("p", null, (d && d.funding_ko) || FUNDING) : null);
  }
  function drawGroups(d) {
    const seg = ui.seg(groupChips(d && d.counts), st.group, (id) => choose("group", GROUP_KEY, groupOf(id)), {label: "왜 못 탔나", scroll: true});
    put(groupSlot, seg);
  }
  function draw(user) {
    const d = st.d;
    spanSeg.set(st.span); resSeg.set(st.result);
    drawFoot(d);
    listCard.hidden = !!d && d.state !== "ok";        // 수집 전 / 못 읽음: no list (an empty list would read as "nothing missed")
    if (!d) { put(cards, motion.shimmer(3)); put(small); put(passEl); put(tot); drawGroups(null); pg.set(undefined); return; }
    if (d.state !== "ok") {
      put(srcSlot, sourceState(d, "못 탄 신호 기록 (livecheck.db)"));
      put(cards); put(small); put(passEl); put(tot); pg.set([]);
      return;
    }
    put(srcSlot, d.pass && d.pass.rig_error ? h("p", {class: "lbm-warn"}, `계산을 못 했어요: ${d.pass.rig_error}`) : null);
    drawCards(d);
    drawPass(d);
    drawGroups(d);
    put(tot, d.list ? [h("b", null, listLine(d.list, st.result)), d.list.read_ko ? h("span", {class: "lbm-totr"}, d.list.read_ko) : null] : null);
    pg.set(d.rows || [], !user);
    if (user) motion.swap(cards);
  }
  function drawPass(d) {
    const p = d.pass || null;
    const left = p && p.left ? ` · 아직 계산 안 한 신호 ${fmt.int(p.left)}개 (오래된 것부터 한 번에 60개씩)` : "";
    put(passEl, p ? [h("span", {class: p.stale ? "lbm-stale" : ""}, passLine(p)), left,
      d.n_rows > (d.rows || []).length ? ` · 최신 ${fmt.int((d.rows || []).length)}개만 보여요` : ""] : null);
  }
  async function load(user) {
    let d;
    const want = `${API}?span=${encodeURIComponent(st.span)}&group=${encodeURIComponent(st.group)}&result=${encodeURIComponent(st.result)}`;
    try { d = await ctx.api(want); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      ui.dim(body, !!st.d);
      if (!st.d) body.hidden = true;
      throw e;
    }
    const now = `${API}?span=${encodeURIComponent(st.span)}&group=${encodeURIComponent(st.group)}&result=${encodeURIComponent(st.result)}`;
    if (!ctx.alive() || now !== want) return;          // the choice changed while it loaded: the newer load draws
    put(stateSlot);
    ui.dim(body, false);
    body.hidden = false;
    const key = sameKey(d);
    st.okAt = Date.now();
    if (key === st.key) { st.d = d; drawPass(d); return; }          // the same records: only the pass line moves
    st.key = key; st.d = d;
    draw(!!user);
  }
  draw(false);
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  return {el};
}
