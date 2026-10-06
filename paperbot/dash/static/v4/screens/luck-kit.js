// 운 vs 실력 (luck-calc, the owners' idea 1 '운으로 통과할 개수'): when many things are tested at once, some pass by luck.
// /api/v4/luck (paperbot/dash/more/luck.py, background + cached) answers one row per place that tests many things:
// how many were tested, the pass rule, how many would pass by luck alone, how many really passed, a plain verdict line.
//   luckView(d, env)        the 분석 › 운 vs 실력 tab (analysis.js VIEWS): why it matters (the coin example), every row
//   luckMini(ctx, {cls})    the compact card on 홈 (요약): the 30-day verdict's row + the places with numbers, one link
//   luckCheck(ctx, {cls})   the compact card on 판정: the verdict's own luck numbers before / after the verdict
// HONESTY: every number is the server's; a place without its file or database says 준비 중, a small sample waits with
// its real threshold (analysis-kit.js progressBar); before the 30-day verdict nothing hints at a pass (판정 전); the
// pills are neutral (no green / red); DeepSeek rows carry counts only (the server sends no money). 설명용, 판정 아님.
// Its look: luck-kit.css, @imported by analysis.css, home.css and checkpoint.css.
import {h, ui, fmt, put, motion} from "../core/pb.js";
import {viewHead, progressBar} from "./analysis-kit.js";

export const LUCK_API = "/api/v4/luck";
const RETRY_MS = 3000;
const REFRESH_MS = 10 * 60 * 1000;
const PILL = {more: "accent", some: "warn", like_luck: "thin", none: "thin", waiting: "thin", before: "ref", preparing: "thin"};
const PILL_KO = {more: "운보다 확실히 많음", some: "운보다 조금 많음", like_luck: "운과 비슷", none: "통과 0", waiting: "기다리는 중",
  before: "판정 전", preparing: "준비 중"};

const num = (x, dec = 2) => (x == null ? "—" : fmt.num(x, Number(x) >= 10 ? 0 : dec));
const linkOf = (ctx, w) => (w && w.screen && ctx && ctx.href ? ctx.href(w.screen, w.arg || null, w.query || undefined) : null);
export const verdictPill = (r) => ui.pill(PILL_KO[r.verdict] || "—", PILL[r.verdict] || "thin", r.verdict_ko || "");

/** Two small bars on one scale: 운으로 (luck) and 실제 (passed); null when either side is missing. */
export function luckBars(luck, passed) {
  if (luck == null || passed == null) return null;
  const top = Math.max(1, Number(luck) || 0, Number(passed) || 0);
  return h("div", {class: "lk-bars", role: "img", "aria-label": `운으로 나올 수 ${num(luck)}개, 실제 통과 ${fmt.int(passed)}개`},
    bar("운으로", luck, "lk-luck", top, num(luck)), bar("실제", passed, "lk-real", top, fmt.int(passed)));
}

function bar(k, v, cls, top, label) {
  return h("div", {class: "lk-bar"}, h("span", {class: "lk-bk"}, k),
    h("span", {class: ["lk-bt", cls]}, h("i", {style: {"--w": Math.max(0, Math.min(1, (Number(v) || 0) / top)) * 100 + "%"}})),
    h("b", {class: "num"}, `${label}개`));
}

/** One place: title, verdict pill, the four numbers, the rule, the verdict line, the note, a link to where it lives. */
export function luckRow(r, ctx) {
  const href = linkOf(ctx, r.where);
  const head = h("div", {class: "lk-rt"}, h("b", {class: "lk-title"}, r.title), verdictPill(r),
    href ? h("a", {class: "lk-go", href}, "보러 가기 →") : null);
  if (r.verdict === "preparing") {
    return h("div", {class: "lk-row lk-prep", role: "listitem"}, head,
      h("p", {class: "muted lk-note"}, "준비 중", r.note ? ` · ${r.note}` : ""),
      h("p", {class: "lk-rule"}, h("span", {class: "muted"}, "통과 기준 "), r.rule_ko || "—"));
  }
  const before = r.verdict === "before";
  const wait = r.verdict === "waiting" && r.need && r.tested != null
    ? progressBar(`채점 ${fmt.int(r.need)}개 필요`, `지금 채점 ${fmt.int(r.tested)}개 · 그 전에는 맞힌 비율로 결론을 내지 않습니다`, r.tested / r.need) : null;
  // the two bars only where they say something (a pass, or luck of one or more); 0 against 0.05 is just the words
  const bars = !before && r.passed != null && r.luck != null && (r.passed > 0 || r.luck >= 1) ? luckBars(r.luck, r.passed) : null;
  const more = [
    h("p", {class: "lk-rule"}, h("span", {class: "muted"}, "통과 기준 "), r.rule_ko || "—"),
    r.luck_ko ? h("p", {class: "lk-rule"}, h("span", {class: "muted"}, "운으로 "), r.luck_ko) : null,
    r.passed_ko ? h("p", {class: "lk-rule"}, h("span", {class: "muted"}, "실제 "),
      before && r.first_verdict_ts ? `${fmt.date(r.first_verdict_ts)} 판정 전` : r.passed_ko) : null,
    r.counts_only ? h("p", {class: "muted lk-note"}, "딥시크는 시험 수와 통과 수만 (돈 숫자 없음)") : null,
    r.note ? h("p", {class: "muted lk-note"}, r.note) : null,
  ].filter(Boolean);
  return h("div", {class: ["lk-row", `lk-s-${r.verdict}`], role: "listitem"}, head,
    h("div", {class: "lk-nums"},
      numCell("시험한 수", r.tested == null ? "—" : fmt.int(r.tested)),
      numCell("운으로 나올 수", r.luck == null ? "—" : num(r.luck)),
      numCell("실제 통과", before ? "판정 전" : r.passed == null ? "—" : fmt.int(r.passed))),
    bars,
    h("p", {class: ["lk-v", `lk-s-${r.verdict}`]}, r.verdict_ko || ""),
    wait,
    ui.disclosure("기준과 숫자 자세히", h("div", {class: "stack tight"}, more)));
}

const numCell = (k, v) => h("div", {class: "lk-num"}, h("span", {class: "k"}, k), h("b", {class: "num"}, v));

/** Why it matters: 100 people flip a coin 20 times (the server's exact numbers), then the same for the accounts. */
export function whyCard(d) {
  const ex = d.example || {};
  const people = Number(ex.people) || 0, lucky = Math.round(Number(ex.expected) || 0);
  const dots = people ? h("div", {class: "lk-dots", role: "img", "aria-label": `${people}명 중 약 ${lucky}명이 ${ex.hit}번 이상 앞면`},
    Array.from({length: people}, (_, i) => h("i", {class: i < lucky ? "hit" : ""}))) : null;
  const ck = (d.rows || []).find((r) => r.id === "checkpoint") || {};
  return ui.card({plate: "왜 중요한가", cls: "lk-why"},
    h("p", {class: "lk-lede"}, `동전을 ${fmt.int(ex.flips)}번 던지는 사람 ${fmt.int(people)}명이 있으면, 실력이 아니라 운만으로 앞면이 ${fmt.int(ex.hit)}번 이상 나오는 사람이 평균 ${num(ex.expected)}명 나옵니다.`),
    dots,
    h("p", {class: "muted lk-note"}, `점 하나 = 한 사람. 색칠한 점 = 앞면이 ${fmt.int(ex.hit)}번 이상 나온 사람 (그 확률 ${fmt.pct(ex.share, 1, false)}). 이 사람들이 동전 던지기를 잘하는 걸까요? 아닙니다. 다시 던지면 대부분 평범해집니다.`),
    h("p", null, "매매법도 같습니다. 여러 개를 한꺼번에 시험하면 아무 실력이 없어도 몇 개는 좋아 보입니다. ",
      ck.tested ? `지금 30일 판정에 들어갈 계좌는 ${fmt.int(ck.tested)}개라, '동전 봇 95%보다 잘하면 합격'으로만 보면 실력이 없어도 약 ${num(ck.plain, 1)}개가 합격처럼 보입니다. ` : "",
      "그래서 이 프로젝트는 시험할 때마다 기준을 엄격하게 보정하고, 아래처럼 '통과한 수'를 '운으로 나올 수'와 나란히 봅니다."),
    h("p", {class: "lk-rule"}, h("b", null, "읽는 법 "), "통과한 수가 운으로 나올 수와 비슷하면 아직 진짜를 찾았다고 할 수 없습니다. 운으로 나올 수보다 확실히 많을 때만 '진짜가 섞여 있을 수 있다'고 봅니다. 그래도 어느 것이 진짜인지는 새 자료로 다시 확인해야 합니다."));
}

/** The 분석 › 운 vs 실력 tab: head, why, the run's own places, the 5-year studies. */
export function luckView(d, env) {
  const rows = Array.isArray(d.rows) ? d.rows : [];
  const ctx = env && env.ctx;
  const sm = d.summary || {};
  const now = rows.filter((r) => r.part === "now"), past = rows.filter((r) => r.part !== "now");
  const list = (rs) => h("div", {class: "lk-list", role: "list"}, rs.map((r) => luckRow(r, ctx)));
  return [
    viewHead({plate: "운 vs 실력", q: "많이 시험하면 몇 개는 운으로 통과합니다. 통과한 수가 운으로 나올 수보다 많은가?",
      meta: `시험하는 곳 ${fmt.int(sm.places || rows.length)}곳 · 숫자가 있는 곳 ${fmt.int(sm.with_data || 0)}곳 · ${d.label || "설명용, 판정 아님"}`,
      at: d.computed_at, stale: d.stale,
      read: "곳마다 시험한 수, 통과 기준, 실력이 하나도 없어도 운으로 통과할 수, 실제로 통과한 수를 나란히 둡니다. 판정이 아니라 '얼마나 조심해서 봐야 하나'를 보여 줍니다."}),
    whyCard(d),
    ui.card({plate: "지금 실험", sub: "이번 모의 실험의 기록"}, list(now)),
    ui.card({plate: "지난 5년 연구", sub: "이미 끝난 시험의 결과 파일"}, list(past),
      h("p", {class: "muted lk-note"}, "5년 연구 파일이 아직 없는 곳은 '준비 중'입니다. 파일이 생기면 여기에 바로 나옵니다.")),
  ];
}

/** Ask /api/v4/luck; a pending answer asks again after 3 s, the answer is refreshed every 10 minutes. */
function follow(ctx, paint) {
  let dead = false, last = null;
  const ask = async () => {
    let d;
    try { d = await ctx.api(LUCK_API); } catch (e) { if (!dead && ctx.alive()) paint(null, e); return; }
    if (dead || !ctx.alive()) return;
    if (d && d.pending) { if (!last) paint(null, null); ctx.timeout(() => { if (!dead) ask(); }, RETRY_MS); return; }
    last = d;
    paint(d, null);
  };
  ask();
  ctx.every(REFRESH_MS, () => { if (!dead) ask(); }, {now: false});
  ctx.track(() => { dead = true; });
}

/** 홈 (요약): one compact card. The 30-day verdict's row first, then up to three places that have numbers. */
export function luckMini(ctx, o = {}) {
  const body = h("div", {class: "stack tight"}, motion.shimmer(2));
  const foot = h("p", {class: "muted lk-note"});
  const more = h("a", {class: "btn-line", href: ctx.href("analysis", "luck")}, "전체 보기 →");
  const el = ui.card({plate: "운 vs 실력", sub: "설명용, 판정 아님", cls: ["lk-mini", o.cls || ""].join(" "), acts: [more]},
    h("p", {class: "lk-lede"}, "많이 시험하면 몇 개는 운으로 통과합니다. 통과한 수가 운으로 나올 수보다 많아야 진짜일 수 있어요."), body, foot);
  follow(ctx, (d, err) => {
    if (err) { put(body, h("p", {class: "muted"}, "운 계산을 불러오지 못했습니다.")); return; }
    if (!d) { put(body, h("p", {class: "muted"}, "계산 중입니다. 잠시 뒤 자동으로 나옵니다.")); return; }
    const rows = d.rows || [];
    const ck = rows.find((r) => r.id === "checkpoint");
    const rest = rows.filter((r) => r.id !== "checkpoint" && r.tested != null && r.verdict !== "preparing")
      .sort((a, b) => (a.part === "now" ? 0 : 1) - (b.part === "now" ? 0 : 1)).slice(0, 3);
    put(body, h("div", {class: "lk-mlist", role: "list"}, [ck, ...rest].filter(Boolean).map((r) => miniRow(r, ctx))));
    const sm = d.summary || {};
    const named = (ids) => (ids || []).map((id) => { const r = rows.find((x) => x.id === id); return r ? r.short || r.title : id; });
    const moreIds = named(sm.more);
    put(foot, `시험하는 곳 ${fmt.int(sm.places || rows.length)}곳 · 숫자가 있는 곳 ${fmt.int(sm.with_data || 0)}곳 · 운보다 확실히 많은 곳 ${fmt.int(moreIds.length)}곳`,
      moreIds.length ? ` (${moreIds.join(", ")})` : "");
  });
  return el;
}

function miniRow(r, ctx) {
  const href = linkOf(ctx, r.where);
  const nums = r.verdict === "preparing" ? "준비 중"
    : r.verdict === "before" ? `대상 ${fmt.int(r.tested)}개 · 운만으로 평균 ${num(r.luck)}개 · 판정 전`
    : `시험 ${fmt.int(r.tested)} · 통과 ${r.passed == null ? "—" : fmt.int(r.passed)} · 운으로 ${num(r.luck)}`;
  return h(href ? "a" : "div", {class: "lk-mrow", role: "listitem", href: href || undefined},
    h("b", {class: "lk-mt"}, r.short || r.title), h("span", {class: "lk-mn num"}, nums), verdictPill(r));
}

/** 판정: the verdict's own luck numbers (before: how strict the rule is; after: passed vs luck). */
export function luckCheck(ctx, o = {}) {
  const body = h("div", {class: "stack tight"}, motion.shimmer(3));
  const more = h("a", {class: "btn-line", href: ctx.href("analysis", "luck")}, "다른 곳도 보기 →");
  const el = ui.card({plate: "운 vs 실력", sub: "설명용, 판정 아님", cls: ["lk-check", o.cls || ""].join(" "), acts: [more]}, body);
  follow(ctx, (d, err) => {
    if (err) { put(body, h("p", {class: "muted"}, "운 계산을 불러오지 못했습니다.")); return; }
    if (!d) { put(body, h("p", {class: "muted"}, "계산 중입니다. 잠시 뒤 자동으로 나옵니다.")); return; }
    const r = (d.rows || []).find((x) => x.id === "checkpoint");
    if (!r || r.tested == null) { put(body, h("p", {class: "muted"}, "준비 중", r && r.note ? ` · ${r.note}` : "")); return; }
    if (r.verdict === "before") {
      put(body,
        h("p", {class: "lk-lede"}, `판정에 들어갈 계좌 ${fmt.int(r.tested)}개 가운데 실력이 하나도 없는데도 운으로 합격처럼 보일 수 있는 수`),
        luckPair(r.plain, r.luck),
        h("p", {class: "ink2"}, `보정 없이 '동전 봇 95%보다 잘하면 합격'이었다면 운만으로 약 ${num(r.plain, 1)}개. 이 판정 규칙(묶음마다 보정)으로는 평균 ${num(r.luck)}개, 1개라도 나올 확률 약 ${fmt.pct(r.any_luck, 0, false)}입니다.`),
        h("p", {class: "muted lk-note"}, r.note || ""));
      return;
    }
    put(body, h("div", {class: "lk-list", role: "list"}, luckRow(r, ctx)));
  });
  return el;
}

/** Before the verdict: 보정 없이 vs 이 규칙 as two bars on one scale. */
function luckPair(plain, rule) {
  if (plain == null || rule == null) return null;
  const top = Math.max(1, Number(plain) || 0, Number(rule) || 0);
  return h("div", {class: "lk-bars", role: "img", "aria-label": `보정 없이 ${num(plain, 1)}개, 이 규칙으로 ${num(rule)}개`},
    bar("보정 없이", plain, "lk-luck", top, num(plain, 1)), bar("이 규칙", rule, "lk-real", top, num(rule)));
}
