// 회의 요약 · 결정 보드 (agents-ui): the meetings' conclusions as cards (오늘 / 이번 주 = the last 7 KST days), each with
// who concluded it (the lead's summary, else the code's summary), why the meeting opened, the conclusion's first line
// and what comes next (the action the meeting ended with, the disagreement left open), then the staff's hypotheses
// with their scorecard status (맞음 / 틀림 / 진행 중 / 기간 만료 / 채점 불가). And staffBoard(): the staff ranked by their
// graded predictions with a sparkline of the running hit rate (used by the 직원 성적표 tab).
// Sources: GET /api/digest/day?day=… (one per day, code-written, read-only) and GET /api/trials (the hypothesis ledger
// with each latest result and the per-role scorecard). Every line is a stored line; nothing is summarised by the page.
// HONESTY: a prediction is graded once by code on the trades that came AFTER it was written; small samples say so;
// the order uses the 95 % lower bound of the hit rate, so 2 of 2 does not outrank 30 of 40.
import {h, put, ui, fmt, motion, serverNow, store} from "../core/pb.js";
import {statusPill, stripLead, triggerKo, whyOf, ACTION_KO, roomAvatar, roleName} from "./rooms-kit.js";
import {pixAvatar, gradesByRole, hypStatus, wilsonLow, dayLabel} from "./agents-ui.js";
import {meetSchedule} from "./home-live.js";
import {roundTradesSlot, LOSS_TRIGGERS} from "./meet-links.js";

const METRIC_KO = {mean_roe: "거래당 평균 ROE", win_rate: "승률", lock_share: "익절 잠금 비율", loss_tag_share: "손실 중 그 특징 비율"};
const pctish = (m, v) => (m === "mean_roe" ? fmt.pct(v, 1) : fmt.pct(v, 0, false));
/** "다음 30건 15분 승률 40% 넘음" from a stored prediction. */
export function predictionKo(p) {
  if (!p || typeof p !== "object") return "";
  return [`다음 ${fmt.int(p.after_trades)}건`, p.timeframe ? fmt.tfKo(p.timeframe) : "모든 봉", `${METRIC_KO[p.metric] || p.metric}${p.tag ? ` (${p.tag})` : ""}`,
    `${pctish(p.metric, p.value)} ${p.direction === "below" ? "아래" : "넘음"}`].join(" ");
}

const dayKey = (ms) => fmt.dayKey(ms);
const dayMs = (day) => Date.parse(`${day}T12:00:00+09:00`);

let trialsCache = null;            // /api/trials: shared by the board and the staff tab while the page is open
export function loadTrials(ctx, fresh) {
  if (!fresh && trialsCache && Date.now() - trialsCache.at < 60000) return trialsCache.p;
  const p = ctx.api("/api/trials?limit=500");
  trialsCache = {at: Date.now(), p};
  p.catch(() => { trialsCache = null; });
  return p;
}

export function makeBoard(ctx) {
  const st = {span: "today", days: new Map(), roles: {}, hypFilter: "all", trials: null, req: 0};
  const spanSeg = ui.seg([{id: "today", label: "오늘"}, {id: "week", label: "이번 주 (7일)"}], st.span, (id) => { st.span = id; load(); }, {label: "기간"});
  const counts = h("div", {class: "db2-counts"});
  const decPager = ui.pager({size: 6, empty: "아직 끝난 회의가 없습니다", row: (m) => decisionCard(m)});
  const decBody = h("div", {class: "db2-dec"}, motion.shimmer(3));
  const hypCounts = h("div", {class: "db2-hcounts", role: "group", "aria-label": "가설 상태"});
  const hypPager = ui.pager({size: 8, empty: "아직 적어 둔 가설이 없습니다", row: (t) => hypRow(t)});
  const hypBody = h("div", {class: "stack tight"}, motion.shimmer(3));
  const el = h("div", {class: "db2 stack"},
    ui.card({plate: "결정 보드", sub: "회의가 낸 결론 · 누가 · 왜 · 다음", acts: [spanSeg]}, counts, decBody),
    ui.card({plate: "가설 장부", sub: "직원이 적은 가설과 코드 채점 · 실험 전체"}, hypCounts, hypBody,
      ui.note("예측이 붙은 가설만 채점합니다: 가설을 쓴 뒤 들어간 거래가 정해 둔 건수(30~300건)만큼 쌓이면 코드가 한 번 판정 · 30일 판정과는 별개")));

  // ---------------------------------------------------------------- decisions
  function decisionCard(m) {
    const lead = (m.lead || [])[0];
    const sumLines = stripLead(m.summary_ko).split("\n").map((x) => x.trim()).filter(Boolean);
    const main = lead || sumLines[0] || triggerKo(m);
    const leadSpeaker = (m.speakers || []).filter((s) => s.kind === "summary").pop();
    const who = leadSpeaker ? leadSpeaker : null;
    const why = whyOf(m);
    const act = m.action && ACTION_KO[m.action] ? ACTION_KO[m.action] : null;
    const people = [...new Map((m.speakers || []).map((s) => [s.role, s])).values()];
    return h("article", {class: ["db2-card", m.status === "done" ? "done" : ""], role: "listitem"},
      h("div", {class: "db2-h"}, h("span", {class: "db2-rav"}, roomAvatar({room_id: m.room_id, kind: String(m.room_id).startsWith("strat:") ? "strategy" : "team", title: m.title})),
        h("span", {class: "db2-ht"}, h("b", null, m.title || m.room_id), h("small", null, `${triggerKo(m)} · ${st.span === "week" ? `${fmt.mmdd(m.ended_ts || m.started_ts)} ` : ""}${fmt.hm(m.ended_ts || m.started_ts)}`)),
        statusPill(m.status)),
      h("p", {class: "db2-main"}, main),
      h("dl", {class: "db2-kv"},
        h("dt", null, "누가"), h("dd", null, who ? h("span", {class: "db2-who"}, pixAvatar(st.roles, who.role, {size: 16}), who.name) : h("span", {class: "muted"}, "코드 요약"),
          people.length > 1 ? h("small", {class: "muted"}, ` · 함께 ${people.map((p) => p.name).filter((n) => !who || n !== who.name).slice(0, 3).join(", ")}${people.length > 4 ? " 외" : ""}`) : null),
        h("dt", null, "왜"), h("dd", null, why || triggerKo(m)),
        h("dt", null, "다음"), h("dd", null, act ? h("b", {class: "db2-act"}, act) : h("span", {class: "muted"}, "기록 없음"),
          m.open_disagreement ? h("span", {class: "db2-dis"}, ` · 갈린 의견: ${m.open_disagreement}`) : null)),
      // a loss meeting: the trades it was about, each to its replay (meet-links.js)
      LOSS_TRIGGERS.includes(m.trigger) ? roundTradesSlot(ctx, m.round_id) : null,
      h("div", {class: "db2-f"}, h("span", {class: "muted"}, `AI ${fmt.int(m.calls)}회 · 발언 ${fmt.int((m.speakers || []).length)}번`), h("span", {class: "grow"}),
        h("a", {class: "btn-line", href: ctx.href("digest", "day", {d: dayKey(m.started_ts), r: m.round_id})}, "회의 기록"),
        h("a", {class: "btn-y", href: ctx.href("rooms", m.room_id)}, "방 열기")));
  }
  async function day(d) {
    if (st.days.has(d) && d !== dayKey(serverNow())) return st.days.get(d);
    const x = await ctx.api(`/api/digest/day?day=${d}`);
    st.days.set(d, x);
    return x;
  }
  async function load() {
    const req = ++st.req;
    const today = dayKey(serverNow());
    const want = st.span === "today" ? [today] : Array.from({length: 7}, (_, i) => dayKey(dayMs(today) - i * 86400000));
    let ds;
    try { ds = await Promise.all(want.map(day)); } catch (e) {
      if (req === st.req && ctx.alive() && !(e && e.name === "AbortError")) decBody.replaceChildren(ui.errorBox(e, load));
      return;
    }
    if (req !== st.req || !ctx.alive()) return;
    const err = ds.find((x) => x && x.error);
    const ms = ds.flatMap((x) => (x && x.meetings) || []).filter((m) => m.status !== "running")
      .sort((a, b) => (b.ended_ts || b.started_ts) - (a.ended_ts || a.started_ts));
    const n = (s) => ms.filter((m) => m.status === s).length;
    put(counts, tile("끝난 회의", ms.length), tile("결정", n("done"), "accent"), tile("행동 없음", n("no_action")),
      tile("갈린 채 끝남", ms.filter((m) => m.open_disagreement).length, "amber"), tile("멈춤", n("failed") + n("stopped_budget")));
    if (err && !ms.length) { decBody.replaceChildren(ui.empty(String(err.error))); return; }
    if (!ms.length && st.span === "today") {
      // before today's first meeting: the fixed hours and a countdown (home-live.js meetSchedule), not a bare empty box
      const sc = meetSchedule(ctx, {cls: "db2-sched"});
      decBody.replaceChildren(ui.empty("오늘(한국 0시 이후) 끝난 회의가 아직 없습니다"), sc);
      ctx.store.need("office", 25000).then((o) => sc.set(o)).catch(() => sc.set(null));
      return;
    }
    if (!decPager.el.isConnected) decBody.replaceChildren(decPager.el);
    decPager.set(ms, false);
  }
  const tile = (k, v, cls) => h("div", {class: ["db2-tile", cls]}, h("b", {class: "num"}, fmt.int(v)), h("span", null, k));

  // ---------------------------------------------------------------- hypotheses
  function hypRow(t) {
    const [ko, cls] = hypStatus(t);
    const spec = t.spec || {};
    const res = t.result && t.result.result;
    return h("div", {class: "db2-hyp", role: "listitem"},
      ui.pill(ko, cls),
      h("div", {class: "db2-hb"}, h("span", {class: "db2-hyp-t"}, spec.text || "(내용 없음)"),
        h("span", {class: "db2-hyp-m"},
          spec.by ? h("span", {class: "db2-who"}, pixAvatar(st.roles, spec.by, {size: 14}), roleName(st.roles, spec.by)) : null,
          t.strategy ? h("a", {href: ctx.href("strategies", t.strategy)}, fmt.stratKo(t.strategy)) : null,
          spec.prediction ? h("span", null, `예측 · ${predictionKo(spec.prediction)}`) : h("span", {class: "muted"}, "예측 없이 적은 가설"),
          res && res.value != null ? h("span", null, `실제 ${pctish((spec.prediction || {}).metric, res.value)} · ${fmt.int(res.n)}건`) : null,
          h("time", null, dayLabel(t.ts)))));
  }
  function paintHyps() {
    const all = ((st.trials && st.trials.trials) || []).filter((t) => t.kind === "hypothesis");
    const by = (k) => all.filter((t) => hypStatus(t)[2] === k);
    const chips = [["all", "전부", all.length], ["hit", "맞음", by("hit").length], ["miss", "틀림", by("miss").length],
      ["wait", "진행 중", by("wait").length], ["exp", "기간 만료", by("exp").length], ["none", "채점 불가", by("none").length]];
    hypCounts.replaceChildren(...chips.filter(([id, , n]) => id === "all" || n).map(([id, ko, n]) => h("button", {class: ["db2-chip", id], type: "button",
      "aria-pressed": String(st.hypFilter === id), onclick: () => { st.hypFilter = id; paintHyps(); }}, ko, h("small", {class: "num"}, fmt.int(n)))));
    if (!hypPager.el.isConnected) hypBody.replaceChildren(hypPager.el);
    hypPager.set(st.hypFilter === "all" ? all : by(st.hypFilter), false);
  }
  async function loadHyps(fresh) {
    try { st.trials = await loadTrials(ctx, fresh); } catch (e) {
      if (ctx.alive() && !(e && e.name === "AbortError") && !st.trials) hypBody.replaceChildren(ui.errorBox(e, () => loadHyps(true)));
      return;
    }
    if (!ctx.alive()) return;
    for (const r of (st.trials.scorecard && st.trials.scorecard.roles) || []) if (r.role && !st.roles[r.role]) st.roles[r.role] = {name: r.name};
    paintHyps();
  }

  return {el, show: () => Promise.all([load(), st.trials ? null : loadHyps()]), refresh: () => { load(); loadHyps(true); },
    setRoles(r) { st.roles = {...(r || {}), ...st.roles}; }};
}

/** The staff leaderboard (직원 성적표 tab): ranked by the 95 % lower bound of graded predictions, a sparkline of the
 *  running hit rate (one point per grade, the 50 % line under it), waiting / expired counts. */
export function staffBoard(ctx) {
  const body = h("div", {class: "db2-lb", role: "list"}, motion.shimmer(3));
  const card = ui.card({plate: "직원 순위 · 예측 채점", sub: "실험 전체 · 표본을 감안한 순서"}, body,
    ui.note("순위 = 맞음 비율의 95% 하한 (채점이 적으면 낮게 잡힘) · 선 = 채점이 쌓일 때마다 누적 맞음 비율, 가는 선 50% · 20건 미만은 표본 적음 · 30일 판정과 별개"));
  loadTrials(ctx).then((d) => {
    if (!ctx.alive()) return;
    const names = {};
    for (const r of (d.scorecard && d.scorecard.roles) || []) names[r.role] = r.name;
    const roles = (store.get("office") || {}).roles || {};
    const by = Object.values(gradesByRole(d.trials || []));
    const graded = by.filter((k) => k.graded).sort((a, b) => wilsonLow(b.correct, b.graded) - wilsonLow(a.correct, a.graded) || b.graded - a.graded);
    const rest = by.filter((k) => !k.graded).sort((a, b) => b.waiting - a.waiting);
    const nm = (role) => names[role] || roleName(roles || {}, role);
    if (!graded.length && !rest.length) { put(body, ui.empty("아직 예측이 붙은 가설이 없습니다")); return; }
    put(body, ...graded.map((k, i) => {
      const rate = k.correct / k.graded;
      return h("div", {class: ["db2-lrow", i < 3 ? `top${i + 1}` : ""], role: "listitem"},
        h("span", {class: "db2-rank num"}, fmt.int(i + 1)),
        pixAvatar(roles || {}, k.role),
        h("span", {class: "db2-ln"}, h("b", null, nm(k.role)),
          h("small", null, `맞음 ${fmt.int(k.correct)}/${fmt.int(k.graded)}`, k.waiting ? ` · 채점 대기 ${fmt.int(k.waiting)}` : "", k.expired ? ` · 만료 ${fmt.int(k.expired)}` : "", " ", ui.smallSample(k.graded, 20))),
        h("span", {class: "db2-spark"}, ui.sparkline(k.series, {w: 110, h: 30, base: 0.5, label: `${nm(k.role)} 누적 맞음 비율`})),
        h("b", {class: "db2-rate num"}, fmt.pct(rate, 0, false)));
    }), ...(rest.length ? [h("p", {class: "db2-rest"}, "아직 채점 전 · ", rest.map((k) => `${nm(k.role)} ${k.waiting ? `대기 ${fmt.int(k.waiting)}` : k.notGradable ? "예측 없음" : ""}`).join(" · "))] : []));
  }).catch((e) => { if (ctx.alive() && !(e && e.name === "AbortError")) put(body, ui.errorBox(e, () => {})); });
  return card;
}
