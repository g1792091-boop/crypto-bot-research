// 회의 요약 · 직원 성적표 (builder D): per staff member over 1 / 7 / 30 days (turns, meetings, 동의·반대·보완, objections
// received, questions, facts vs hypotheses, unreadable answers, proposals, verdicts) and graded predictions over the
// whole run (small samples say so), the latest graded predictions, and the 12:00 bull/bear calls against their base
// rates (a coin flip 50 %, "always up" on the same days) as the server computes them. GET /api/digest/staff?days=N.
import {h, put, ui, fmt, motion} from "../core/pb.js";
import {avatarFor, ACTION_KO, VERDICT_KO} from "./rooms-kit.js";

const TEAM_KO = {market: "시장분석", plan: "매매 계획", risk: "리스크", ops: "운영·검증", dev: "개발", lead: "총괄", review: "손익 복기",
  evolve: "자기진화", compare: "비교분석", timing: "타점분석", safety: "안전·실거래", specialist: "매매법 전담"};

/** 동의 / 반대 / 보완 shares of one staff member's replies (r.agree / r.disagree / r.add): [{k, n, w}] with w the
 *  share in % (one decimal), or null when there is no reply yet. Counts only. */
export function reactShares(r) {
  const parts = [["agree", "동의"], ["disagree", "반대"], ["add", "보완"]].map(([k, ko]) => ({k, ko, n: Math.max(0, Number((r || {})[k]) || 0)}));
  const tot = parts.reduce((a, x) => a + x.n, 0);
  if (!tot) return null;
  return parts.map((x) => ({...x, w: Math.round((x.n / tot) * 1000) / 10}));
}
/** The one-line colour bar of the replies (teal agree, pink disagree, yellow add; the same tokens in both skins). */
function reactBar(r) {
  const sh = reactShares(r);
  if (!sh) return h("span", {class: "dg-rbar none"}, h("span", {class: "dg-rbar-t muted"}, "반응 아직 없음"));
  return h("span", {class: "dg-rbar", role: "img", "aria-label": `반응 ${sh.map((x) => `${x.ko} ${x.n}`).join(" · ")}`},
    h("span", {class: "dg-rbar-l", "aria-hidden": "true"}, sh.filter((x) => x.n).map((x) => h("i", {class: x.k, style: {"--w": `${x.w}%`}, title: `${x.ko} ${x.n}`}))));
}

export function makeStaff(ctx) {
  const st = {days: 7, d: null, req: 0};
  const seg = ui.seg([{id: "1", label: "하루"}, {id: "7", label: "7일"}, {id: "30", label: "30일"}], "7", (v) => { st.days = +v; load(); }, {label: "기간"});
  const tiles = h("div", {class: "stats s4"});
  const debateBox = h("div");
  const list = ui.pager({size: 10, empty: "아직 발언이 없습니다", row: (s) => staffRow(s)});
  const grades = ui.pager({size: 5, empty: "아직 채점된 예측이 없습니다. 예측은 정해 둔 거래 수 (30~300건)가 쌓여야 채점됩니다.", row: (g) => gradeRow(g)});
  const note = h("p", {class: "rk-note"});
  const body = h("div", {class: "stack"}, motion.shimmer(4));
  const el = h("div", {class: "dg-staff stack"}, h("div", {class: "row wrap"}, seg, h("span", {class: "muted dg-hint"}, "발언·반응은 고른 기간, 예측 채점은 실험 전체")), body);

  function staffRow(s) {
    const p = s.predictions || {}, r = s.replies || {}, rb = s.replied_by || {};
    const props = Object.entries(s.proposals || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${ACTION_KO[k] || k} ${fmt.int(v)}`).join(", ");
    const verd = Object.entries(s.verdicts || {}).map(([k, v]) => `${VERDICT_KO[k] || k} ${fmt.int(v)}`).join(", ");
    return h("div", {class: "lrow dg-srow2", role: "listitem"},
      avatarFor({[s.role]: {name: s.name, team: s.team}}, s.role, s.name),
      h("span", {class: "lname"}, s.name, h("small", {class: "muted"}, ` ${TEAM_KO[s.team] || ""}`)),
      h("span", {class: "ret"}, `발언 ${fmt.int(s.turns)}`),
      h("span", {class: "meta"},
        reactBar(r),
        h("span", null, `회의 ${fmt.int(s.meetings)}`),
        h("span", null, `반응 동의 ${fmt.int(r.agree || 0)} · `, h("span", {class: r.disagree ? "down" : ""}, `반대 ${fmt.int(r.disagree || 0)}`), ` · 보완 ${fmt.int(r.add || 0)}`),
        h("span", null, `받은 반대 ${fmt.int(rb.disagree || 0)}`),
        h("span", null, `질문 ${fmt.int(s.asks)}`),
        h("span", null, `사실·가설 ${fmt.int(s.facts)}·${fmt.int(s.hypotheses_said)}`),
        s.unreadable ? ui.pill(`못 읽은 답 ${fmt.int(s.unreadable)}`, "warn") : null,
        p.graded ? h("span", null, `예측 ${fmt.int(p.correct)}/${fmt.int(p.graded)} 맞음`, " ", ui.smallSample(p.graded, 20)) : null,
        p.waiting ? h("span", null, `채점 대기 ${fmt.int(p.waiting)}`) : null,
        props || verd ? h("span", null, [props, verd].filter(Boolean).join(" · ")) : null,
        s.last_ts ? h("span", null, `마지막 ${fmt.kst(s.last_ts)}`) : null));
  }
  function gradeRow(g) {
    const pill = g.status === "expired" ? ui.pill("기간 만료", "thin") : g.correct ? ui.pill("맞음", "good") : ui.pill("틀림", "bad");
    return h("div", {class: "lrow", role: "listitem"}, pill, h("span", {class: "lname"}, `${g.name || "—"}${g.strategy ? ` · ${g.strategy}` : ""}`),
      h("span", {class: "ret muted"}, fmt.kst(g.ts)),
      h("span", {class: "meta"}, h("span", null, g.prediction_ko || ""), g.value != null ? h("span", null, `실제 ${fmt.num(g.value, 3)} · ${fmt.int(g.n)}건`) : null,
        g.text ? h("span", null, g.text) : null));
  }
  /** The 12:00 bull/bear calls (team:market): the room's total against the base rates the server computed. */
  function debateCard(b) {
    if (!b) return null;
    if (!b.calls && !b.graded) return ui.card({plate: "낙관·비관 판정", sub: "매일 12:00 시장분석팀"},
      h("p", {class: "ink2"}, "아직 채점된 판정이 없습니다. 판정은 24시간 뒤 종가로 코드가 채점합니다."), b.rule ? h("p", {class: "rk-note"}, b.rule) : null);
    const bar = (lab, v, cls) => h("div", {class: "dg-rate"}, h("span", null, lab), h("div", {class: "prog"}, h("i", {style: {"--p": v == null ? "0%" : `${Math.round(v * 100)}%`}, class: cls})),
      h("b", null, v == null ? "—" : fmt.pct(v, 0, false)));
    return ui.card({plate: "낙관·비관 판정", sub: "매일 12:00 시장분석팀 · 실험 전체"},
      b.graded < 20 ? h("p", {class: "rk-banner"}, h("b", null, "표본 적음"), h("span", null, `채점된 판정이 ${fmt.int(b.graded)}개뿐이라 운과 구별할 수 없습니다. 20개가 넘어도 30일 판정과는 관계없는 참고입니다.`)) : null,
      h("div", {class: "dg-rates"}, bar(`방 전체 맞음 ${fmt.int(b.correct)}/${fmt.int(b.graded)}`, b.hit_rate, ""),
        bar("동전 던지기 (기준)", b.coin_flip_rate, "dim"), b.always_up_rate != null ? bar(`'늘 상승'이라고 했다면 (${fmt.int(b.always_up_correct || 0)}/${fmt.int(b.graded)})`, b.always_up_rate, "dim") : null),
      b.open ? h("p", {class: "muted"}, `채점 대기 ${fmt.int(b.open)}개`) : null,
      b.rule ? h("p", {class: "rk-note"}, b.rule) : null);
  }

  async function load() {
    const req = ++st.req;
    let d;
    try { d = await ctx.api(`/api/digest/staff?days=${st.days}`); } catch (e) {
      if (req === st.req && ctx.alive() && !(e && e.name === "AbortError") && !st.d) body.replaceChildren(ui.errorBox(e, load));
      return;
    }
    if (req !== st.req || !ctx.alive()) return;
    st.d = d;
    if (d.error) { body.replaceChildren(ui.empty(String(d.error))); return; }
    const t = d.total || {}, staff = d.staff || [];
    put(tiles,
      ui.stat("예측 채점 (실험 전체)", t.graded ? `${fmt.int(t.correct)}/${fmt.int(t.graded)}` : "—",
        h("span", {class: "s"}, t.graded ? `맞음 ${fmt.pct(t.hit_rate, 0, false)} ` : "아직 채점 없음", t.graded ? ui.smallSample(t.graded, 20) : null)),
      ui.stat("채점 대기", fmt.int(t.waiting || 0), "정해 둔 거래 수가 차면 코드가 한 번 판정"),
      ui.stat(`말한 직원 (${st.days === 1 ? "하루" : `${st.days}일`})`, fmt.int(staff.filter((s) => s.turns).length), `발언 ${fmt.int(staff.reduce((a, s) => a + s.turns, 0))}번`),
      ui.stat("못 읽은 답", fmt.int(staff.reduce((a, s) => a + (s.unreadable || 0), 0)), "형식이 틀려 코드가 버린 답"));
    debateBox.replaceChildren(...[debateCard(d.debate)].filter(Boolean));
    list.set(staff.filter((s) => s.turns || (s.predictions || {}).graded), true);
    grades.set(d.recent_grades || [], true);
    note.textContent = d.note || "";
    if (!tiles.isConnected) put(body, tiles,
      ui.card({plate: "직원별", sub: "발언이 있는 직원만 · 10명씩"},
        h("p", {class: "dg-rkey"}, h("span", null, "색 막대 = 이 직원이 남의 말에 한 반응"),
          h("span", null, h("i", {class: "agree"}), "동의"), h("span", null, h("i", {class: "disagree"}), "반대"), h("span", null, h("i", {class: "add"}), "보완")),
        list.el),
      debateBox,
      ui.card({plate: "최근 채점된 예측", sub: "가설을 쓴 뒤 들어간 거래로 코드가 판정"}, grades.el), note);
  }
  return {el, show: () => (st.d ? null : load()), refresh: load};
}
