// 실거래 › 못 탄 신호 (#/livebots/missed; owners 10/19 "못 탄 신호들은 어땠나"): the signals the paper bot (A+C 합본,
// COMBO@mix, the one both executors follow) could not take, because a position was already open (one at a time) or another
// signal of the same minute went in, and what each would have done: /api/v4/livebots/missed (dash/more/livemissed.py; the
// 1-minute watcher's pass paperbot/livemissed.py simulates each on the paper bot's own engine with the rule bot's 1m bars,
// paperbot/livesim.py). View only: the one-position rule stays as it is.
//   머리   못 탄 신호는 어땠을까? · 최근 7일 | 기록 전체 · two blocks side by side: 실제로 탄 거래 vs 못 탄 신호(가상) (count,
//          이김 / 짐 at the same size, win rate, net ROE sum and mean), 표본 적음 under 20, the watcher's last pass
//   목록   newest first, 10 a page: time, coin, 롱/숏, strategy · tf, why it was missed ("이미 BTC 롱 보유 중"), the virtual
//          result (✅ +11.2% 계단 익절 / ❌ −38.0% 손절 / 진행 중 +4.0% / 1분봉 없음), hold time, the trade taken instead
//   발    always on screen: 가상 결과 · 1포지션 규칙은 그대로 · 거래가 적으면 운, and the funding note while funding is left out
// HONESTY: the watcher's file or table not there yet = 수집 전, unreadable = 못 읽음 + why (never an empty list); a refresh
// that fails keeps the last answer, dimmed, with its age; no virtual price is ever made up (1분봉 없음).
import {h, put, ui, fmt, local, motion} from "../core/pb.js";
import {sourceState} from "./livebots-kit.js";

export const API = "/api/v4/livebots/missed";
const REFRESH_MS = 30 * 1000;                // the watcher computes every minute; the server caches 5 s
const SPAN_KEY = "lb-missed-span";
const PAGE = 10;
export const SPANS = [{id: "7d", label: "최근 7일"}, {id: "all", label: "기록 전체"}];
export const SMALL_N = 20;
// the server's words (dash/more/livemissed.py note_ko / funding_ko), here too so the foot is there before the first answer
export const NOTE = "가상 결과예요: 페이퍼 봇과 같은 엔진·같은 1분봉으로 계산했지만 실제 체결이 아니에요. 1포지션 규칙은 그대로이고, 이건 "
  + "바꾸자는 뜻이 아니라 보기만 하는 거예요. 거래가 적을 때는 대부분 운이에요.";
export const FUNDING = "펀딩비는 빠져 있어요: 페이퍼 봇은 바이낸스 펀딩비(8시간마다)를 내지만 그 비율은 어디에도 기록되지 않아서 "
  + "가상 결과에는 넣지 못했어요 (보통 8시간에 순ROE 0.3%p 안팎)";
const EXIT_KO = {SL: "손절", LOCK: "계단 익절", LIQ: "강제청산", HALT: "멈춤 청산", MANUAL: "수동 청산", REV: "빠른 청산", TP: "익절", END: "끝"};

// ---------------------------------------------------------------- pure functions (node tests: tests/test_dash_livebots_missed.py)
const numOr = (x) => (x == null || x === "" || typeof x === "boolean" || !Number.isFinite(Number(x)) ? null : Number(x));
export const spanOf = (v) => (SPANS.some((s) => s.id === v) ? v : "7d");

/** The virtual result of a row: {icon, text, tone}. tone: up / down / open / thin / bad. */
export function resultOf(r) {
  const st = r && r.state, roe = numOr(r && r.roe);
  if (st === "closed") {
    const win = !!r.win;
    return {icon: win ? "✅" : "❌", text: `${fmt.pct(roe, 1)} ${r.reason_ko || EXIT_KO[r.reason] || r.reason || ""}`.trim(), tone: win ? "up" : "down"};
  }
  if (st === "open") return {icon: "", text: `진행 중 ${fmt.pct(roe, 1)}`, tone: "open"};
  if (st === "no_data") return {icon: "", text: "1분봉 없음", tone: "thin"};
  if (st === "refused") return {icon: "", text: "진입 안 됨", tone: "thin", why: r.note || "엔진이 거절했어요"};
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

/** One block's numbers in words: {count, wins, losses, rate, sum, mean}. unit: "번" (trades) / "개" (signals). */
export function blockWords(b, unit) {
  if (!b) return null;
  return {count: `${fmt.int(b.n || 0)}${unit}`, closed: b.closed || 0, wins: fmt.int(b.wins || 0), losses: fmt.int(b.losses || 0),
    rate: b.win_rate == null ? "—" : fmt.pct(b.win_rate, 0, false), sum: b.closed ? fmt.pct(b.roe_sum, 1) : "—",
    mean: b.roe_mean == null ? "—" : fmt.pct(b.roe_mean, 1), small: !!b.small};
}

/** The missed block's other states in words: "진행 중 2 · 1분봉 없음 1 · 진입 안 됨 1 · 못 읽음 1" ('' when none). */
export function otherLine(m) {
  if (!m) return "";
  return [["open", "진행 중"], ["no_data", "1분봉 없음"], ["refused", "진입 안 됨"], ["error", "못 읽음"]]
    .filter(([k]) => m[k]).map(([k, ko]) => `${ko} ${fmt.int(m[k])}`).join(" · ");
}

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
/** missedView(ctx) -> {el}: its own endpoint every 30 s; the span chosen is remembered on this device. */
export function missedView(ctx) {
  const st = {span: spanOf(local.get(SPAN_KEY, "7d")), d: null, key: "", okAt: 0};
  const seg = ui.seg(SPANS, st.span, (id) => { st.span = spanOf(id); local.set(SPAN_KEY, st.span); st.key = ""; load(true).catch(() => {}); },
    {label: "기간"});
  const stateSlot = h("div", {class: "lb-slot"});
  const srcSlot = h("div", {class: "lb-slot"});
  const vs = h("div", {class: "lbm-vs"}, motion.shimmer(3));
  const small = h("p", {class: "lbm-small"});
  const passEl = h("p", {class: "lbm-pass"});
  const pg = ui.pager({size: PAGE, row: (r) => rowEl(r), empty: () => (st.d ? ui.empty("이 기간에 못 탄 신호가 없어요 (탄 것만 있었거나 신호가 없었어요)") : motion.shimmer(3))});
  const listCard = ui.card({title: "신호 하나씩", sub: "최신 먼저 · 10개씩 · 한국 시간", cls: "lbm-list"}, pg.el);
  const foot = h("div", {class: "lbm-foot", role: "note"});
  const body = h("div", {class: "lbm-body"},
    h("section", {class: "lbm-head", "aria-label": "못 탄 신호는 어땠을까"},
      h("div", {class: "lbm-htop"}, h("h2", null, "못 탄 신호는 어땠을까?"), seg),
      h("p", {class: "lbm-sub"}, "한 번에 하나 규칙 때문에 못 탄 신호를 페이퍼 봇과 같은 엔진으로 따라가 봤어요"),
      srcSlot, vs, small, passEl),
    listCard);
  const el = h("div", {class: "lbm"}, stateSlot, body, foot);

  function block(cls, title, b, unit, extra) {
    const w = blockWords(b, unit);
    return h("div", {class: ["lbm-blk", cls], role: "group", "aria-label": title},
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
      w.small ? ui.pill("표본 적음", "thin", `닫힌 것 ${SMALL_N}번 미만: 대부분 운이에요`) : null);
  }
  function drawVs(d) {
    const s = d.summary || {};
    const left = s.taken ? block("taken", "실제로 탄 거래", s.taken, "번", s.taken.open ? `진행 중 ${fmt.int(s.taken.open)}번 (닫히면 셈)` : "")
      : h("div", {class: "lbm-blk taken"}, h("h3", null, "실제로 탄 거래"), sourceState(d.paper || {state: "missing"}, "페이퍼 DB"));
    const m = s.missed || {};
    const extra = [otherLine(m), m.n ? `서로 다른 순간 ${fmt.int(m.moments || 0)}번` : ""].filter(Boolean).join(" · ");
    put(vs, left, h("span", {class: "lbm-vsx", "aria-hidden": "true"}, "vs"), block("missed", "못 탄 신호(가상)", m, "개", extra));
    const anySmall = (s.taken && s.taken.small) || m.small;
    put(small, anySmall ? [h("b", null, "표본 적음"), ` · 닫힌 것 ${SMALL_N}번 미만은 대부분 운이에요. 두 숫자의 차이로 규칙을 판단하지 마세요`] : null);
  }
  function rowEl(r) {
    const x = resultOf(r);
    return h("div", {class: ["lbm-row", r.state, x.tone], role: "listitem"},
      h("span", {class: "lbm-t num"}, fmt.kst(r.t)),
      h("span", {class: "lbm-c"}, h("b", null, fmt.coin(r.symbol)), ui.sideTag(r.side)),
      h("span", {class: "lbm-s", title: r.member || ""}, `${fmt.stratKo(r.strategy)} · ${fmt.tfKo(r.tf)}`),
      h("span", {class: "lbm-why", title: r.why_kind_ko || ""}, r.why || r.why_kind_ko || "—"),
      h("span", {class: ["lbm-res", x.tone], title: x.why || (r.stop_rule ? `손절: ${r.stop_rule}` : "")},
        x.icon ? h("i", {"aria-hidden": "true"}, x.icon) : null, h("b", {class: "num"}, x.text), x.why ? h("small", null, x.why) : null),
      h("span", {class: "lbm-hold num", title: "들고 있던 시간 (진행 중이면 지금까지)"}, holdText(r)),
      h("span", {class: ["lbm-tk", r.taken && r.taken.state === "open" ? "open" : ""]}, takenText(r.taken)));
  }
  function drawFoot(d) {
    put(foot, h("p", null, (d && d.note_ko) || NOTE), !(d && d.funding_included) ? h("p", null, (d && d.funding_ko) || FUNDING) : null);
  }
  function draw(user) {
    const d = st.d;
    seg.set(st.span);
    drawFoot(d);
    listCard.hidden = !!d && d.state !== "ok";        // 수집 전 / 못 읽음: no list (an empty list would read as "nothing missed")
    if (!d) { put(vs, motion.shimmer(3)); put(small); put(passEl); pg.set(undefined); return; }
    if (d.state !== "ok") {
      put(srcSlot, sourceState(d, "못 탄 신호 기록 (livecheck.db)"));
      put(vs); put(small); put(passEl); pg.set([]);
      return;
    }
    put(srcSlot, d.pass && d.pass.rig_error ? h("p", {class: "lbm-warn"}, `계산을 못 했어요: ${d.pass.rig_error}`) : null);
    drawVs(d);
    drawPass(d);
    pg.set(d.rows || [], !user);
    if (user) motion.swap(vs);
  }
  function drawPass(d) {
    const p = d.pass || null;
    const left = p && p.left ? ` · 아직 계산 안 한 신호 ${fmt.int(p.left)}개 (한 번에 30개씩)` : "";
    put(passEl, p ? [h("span", {class: p.stale ? "lbm-stale" : ""}, passLine(p)), left,
      d.n_rows > (d.rows || []).length ? ` · 최신 ${fmt.int((d.rows || []).length)}개만 보여요` : ""] : null);
  }
  async function load(user) {
    let d;
    const span = st.span;
    try { d = await ctx.api(`${API}?span=${encodeURIComponent(span)}`); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      ui.dim(body, !!st.d);
      if (!st.d) body.hidden = true;
      throw e;
    }
    if (!ctx.alive() || span !== st.span) return;
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
