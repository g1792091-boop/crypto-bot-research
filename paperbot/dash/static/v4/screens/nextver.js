// 다음 버전 (#/nextver, owners' round 2 10/06; reached from 졸업 길 and 홈's 목표 진척도 line): three read-only views for
// deciding, after the 30-day verdict, what a next version could carry. /api/v4/nextver (paperbot/dash/more/nextver.py):
//   후보 장부 (#/nextver)          every result that could become a change, each with the code's evidence grade (강함 /
//                                  보통 / 약함 / 아주 약함 / 등급 없음 for a descriptive study) and, per testing place, what luck
//                                  alone gives there (the luck-calc's numbers)
//   주장별 성적표 (#/nextver/claims) the same claim tried on many strategies: how often the pre-registered claim rule held,
//                                  next to the base rate over every claim (and the coin flip's 50 % for forward checks)
//   못 하는 아이디어 (#/nextver/cantdo) ideas no test could express (the owners' requests translated as 'none', the
//                                  debate's ideas outside the grammar), with the code's reason and a count per reason
// HONESTY: every word but a quoted idea / claim is the server's code text; grades are neutral pills (no pass / fail
// colours); small samples say 표본 적음; nothing here proposes, approves or changes anything (보기만).
import {h, put, ui, fmt, motion} from "../core/pb.js";

const API = "/api/v4/nextver";
const REFRESH_MS = 5 * 60 * 1000;
const TABS = [{id: "candidates", label: "후보 장부"}, {id: "claims", label: "주장별 성적표"}, {id: "cantdo", label: "못 하는 아이디어"}];
const GRADE_CLS = {A: "accent", B: "thin", C: "thin", D: "thin", "-": "ref"};
const SMALL = 10;
let cur = null;

const share = (x) => (x == null ? "—" : fmt.pct(x, 0, false));
const gradePill = (r) => ui.pill(`${r.grade === "-" ? "" : r.grade + " "}${r.grade_ko}`, GRADE_CLS[r.grade] || "thin", r.grade_why || "");
const linkOf = (ctx, g) => (g && g.name ? ctx.href(g.name, g.arg || null) : null);

// ---------------------------------------------------------------- 1. 후보 장부
function candRow(ctx, r) {
  const href = linkOf(ctx, r.go);
  const kids = [h("div", {class: "nv-rh"}, gradePill(r), h("span", {class: "muted"}, r.kind_ko), r.ts ? h("time", {class: "muted"}, fmt.mmdd(r.ts)) : null),
    h("b", {class: "nv-title"}, r.title || ""),
    r.sub ? h("p", {class: "nv-sub"}, r.sub) : null,
    r.quote ? h("p", {class: "nv-quote"}, h("span", {class: "muted"}, "주장 "), `“${r.quote}”`) : null];
  return href ? h("a", {class: "nv-row click", role: "listitem", href}, kids) : h("div", {class: "nv-row", role: "listitem"}, kids);
}

function candidates(ctx, c) {
  const by = c.by_grade || {};
  const pg = ui.pager({size: 10, row: (r) => candRow(ctx, r), empty: "아직 후보가 없습니다: 관문을 넘은 시험도, 공격 쪽이 이긴 다툼도 없습니다"});
  pg.set(c.rows || []);
  const luck = c.luck || {};
  const luckLine = (id, name) => {
    const l = luck[id];
    if (!l || l.tested == null) return null;
    return h("p", {class: "nv-luck"}, h("b", null, name), ` 시험 ${fmt.int(l.tested)}개 · 운으로 ${l.luck_ko || "—"} · 실제 ${l.passed_ko || "—"}`,
      l.verdict_ko ? h("span", {class: "muted"}, ` · ${l.verdict_ko}`) : null);
  };
  const d = c.disputes || {};
  const studies = (c.studies || []).map((s) => h("div", {class: "nv-study", role: "listitem"},
    h("div", {class: "nv-rh"}, gradePill(s), h("span", {class: "muted"}, s.kind_ko)), h("b", {class: "nv-title"}, s.title), s.sub ? h("p", {class: "nv-sub"}, s.sub) : null,
    linkOf(ctx, s.go) ? h("a", {class: "nv-go", href: linkOf(ctx, s.go)}, "자세히 →") : null));
  return [
    ui.card({plate: "다음 버전 후보 장부", sub: `후보 ${fmt.int(c.total || 0)}개 · ` + ["A", "B", "C", "D"].map((g) => `${(c.grades || {})[g] ? c.grades[g].ko : g} ${fmt.int(by[g] || 0)}`).join(" · ")},
      h("div", {class: "nv-list"}, pg.el),
      h("div", {class: "nv-luckbox"}, luckLine("newlab", "새 매매법 시험실"), luckLine("roomtests", "방별 규칙 시험")),
      d.settled ? h("p", {class: "nv-sub"}, `끝난 다툼 ${fmt.int(d.settled)}개 중 공격 쪽 맞음 ${fmt.int(d.attacker)} (위 목록) · 편드는 쪽 맞음 ${fmt.int(d.advocate)} (그대로 두기)`) : null,
      h("p", {class: "rk-note"}, c.note_ko || "")),
    ui.card({plate: "증거 등급", sub: "코드가 정한 기준"}, h("ul", {class: "nv-grades"}, Object.entries(c.grades || {}).map(([g, v]) =>
      h("li", null, ui.pill(`${g === "-" ? "" : g + " "}${v.ko}`, GRADE_CLS[g] || "thin"), " ", v.why)))),
    ui.card({plate: "5년 연구", sub: "이미 끝난 사전 등록 연구"}, h("div", {class: "plist", role: "list"}, studies)),
  ];
}

// ---------------------------------------------------------------- 2. 주장별 성적표
function claimRow(r, base) {
  const held = r.held_share, b = base.held_share;
  const bars = r.tests ? h("div", {class: "nv-bars", role: "img", "aria-label": `맞음 ${share(held)}, 기준 ${share(b)}`},
    bar("이 주장", held, "nv-me"), bar("기준(모든 주장)", b, "nv-base")) : null;
  return h("div", {class: "nv-row", role: "listitem"},
    h("b", {class: "nv-title"}, r.claim_ko),
    h("p", {class: "nv-sub"}, `매매법 ${fmt.int(r.strategies)}개 · 5년 시험 ${fmt.int(r.tests)}개 · 맞음 ${fmt.int(r.held)} (${share(held)}) · 복제 관문 통과 ${fmt.int(r.gate)} `,
      ui.smallSample(r.tests, SMALL)),
    bars,
    r.lab_disputes ? h("p", {class: "nv-sub"}, `5년 시험 다툼 ${fmt.int(r.lab_disputes)}개 중 공격 쪽 맞음 ${fmt.int(r.lab_attacker)}`) : null,
    r.fwd_disputes ? h("p", {class: "nv-sub"}, `앞으로 N건 확인 ${fmt.int(r.fwd_disputes)}개 중 공격 쪽 맞음 ${fmt.int(r.fwd_attacker)} (동전 50%와 비교) `, ui.smallSample(r.fwd_disputes, SMALL)) : null);
}

function bar(label, v, cls) {
  return h("div", {class: "nv-bar"}, h("span", null, label),
    h("div", {class: "prog"}, h("i", {class: cls, style: {"--p": v == null ? "0%" : `${Math.round(v * 100)}%`}})), h("b", null, share(v)));
}

function claims(c) {
  const base = c.base || {};
  const pg = ui.pager({size: 10, row: (r) => claimRow(r, base), empty: "아직 주장별로 볼 시험이 없습니다 (매매법 방의 5년 고쳐 보기 시험이 쌓이면 나옵니다)"});
  pg.set(c.rows || []);
  return [ui.card({plate: "주장별 성적표", sub: "같은 주장을 여러 매매법에서 시험한 결과"},
    h("div", {class: "stats s3"},
      ui.stat("5년 시험 (모든 주장)", fmt.int(base.tests || 0), ui.smallSample(base.tests || 0, SMALL)),
      ui.stat("맞음 기준 비율", share(base.held_share), "미리 정한 다툼 채점 규칙"),
      ui.stat("앞으로 N건 확인", `${fmt.int(base.fwd_attacker || 0)}/${fmt.int(base.fwd_settled || 0)}`, "공격 쪽 맞음 · 동전 50%")),
    h("div", {class: "nv-list"}, pg.el),
    h("p", {class: "rk-note"}, c.note_ko || ""))];
}

// ---------------------------------------------------------------- 3. 못 하는 아이디어
function cantRow(it) {
  return h("div", {class: "nv-row", role: "listitem"},
    h("div", {class: "nv-rh"}, ui.pill(it.source_ko, "thin"), h("span", {class: "muted"}, it.label || ""), it.ts ? h("time", {class: "muted"}, fmt.mmdd(it.ts)) : null),
    it.quote ? h("p", {class: "nv-quote"}, `“${it.quote}”`) : null,
    it.question_ko ? h("p", {class: "nv-sub"}, h("span", {class: "muted"}, "토론 질문 "), it.question_ko) : null,
    (it.reasons_ko || []).length ? h("ul", {class: "nv-why"}, it.reasons_ko.map((x) => h("li", null, x)))
      : it.why_ko ? h("p", {class: "nv-sub"}, h("span", {class: "muted"}, "코드 "), it.why_ko) : null);
}

function cantdo(c) {
  const pg = ui.pager({size: 10, row: cantRow, empty: "아직 문법으로 옮기지 못한 아이디어가 없습니다"});
  pg.set(c.items || []);
  const tally = c.by_reason || [];
  return [
    ui.card({plate: "연구실이 못 하는 아이디어", sub: `${fmt.int(c.total || 0)}개 · 두 분 요청 ${fmt.int(c.owner || 0)} · 토론방 ${fmt.int(c.debate || 0)}`},
      h("div", {class: "nv-list"}, pg.el), h("p", {class: "rk-note"}, c.note_ko || "")),
    ui.card({plate: "이유별", sub: "두 분 요청을 옮길 때 붙은 이유 (근사 포함)"},
      tally.length ? h("ul", {class: "nv-tally"}, tally.map((r) => h("li", null, h("b", null, r.ko),
        h("span", {class: "muted"}, ` · 옮길 수 없음 ${fmt.int(r.none)} · 근사 ${fmt.int(r.approx)}`))))
        : h("p", {class: "muted"}, "아직 이유가 붙은 요청이 없습니다")),
  ];
}

export async function mount(el, ctx) {
  ctx.setTitle("다음 버전");
  el.append(ui.screenHead("다음 버전", "판정 뒤 무엇을 바꿀지 정할 때 보는 장부 · 보기만, 아무것도 제안하지 않음"));
  const st = {tab: TABS.some((t) => t.id === ctx.params.arg) ? ctx.params.arg : "candidates", d: null};
  const seg = ui.seg(TABS, st.tab, (id) => ctx.go("nextver", id === "candidates" ? null : id), {label: "다음 버전 보기", scroll: true});
  const body = h("div", {class: "nv-body"}, motion.shimmer(3));
  const foot = h("p", {class: "nv-foot muted"});
  el.append(seg, body, foot);

  function render(animate) {
    if (!st.d) return;
    const d = st.d;
    const parts = st.tab === "claims" ? claims(d.claims || {}) : st.tab === "cantdo" ? cantdo(d.cantdo || {}) : candidates(ctx, d.candidates || {});
    put(body, ...parts);
    foot.textContent = `${d.label || "보기만"}${d.now ? ` · ${fmt.kst(d.now)} 기준` : ""}`;
    if (animate) motion.swap(body);
  }
  async function load() {
    let d;
    try { d = await ctx.api(API); } catch (e) {
      if (ctx.alive()) put(body, ui.errorBox(e, load));
      return;
    }
    if (!ctx.alive()) return;
    st.d = d;
    render(false);
  }
  cur = {set(tab) { st.tab = TABS.some((t) => t.id === tab) ? tab : "candidates"; seg.set(st.tab); render(true); }};
  await load();
  ctx.every(REFRESH_MS, load);
}

export function update(params) { if (cur) cur.set(params.arg); }
export function unmount() { cur = null; }
