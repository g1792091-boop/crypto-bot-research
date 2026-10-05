// 매매법 상세: 이미 해 본 시험 (batch ana8A), under the 5-year card. What the pre-registered studies already tested for
// THIS strategy on the same five years (/api/profile `research_prior` = agents/packets3.research_prior):
// - the 36: the entry study (research_prior.json): support / resistance, its own entry numbers (per timeframe, the ones
//   whose direction was the same in all three periods), trendlines; parameters are left to their own panel.
// - DeepSeek / the reel: not in the entry study; the DeepSeek-200 / reel study rows instead (ds_prior.json).
// The study's own conclusion_ko is shown as written (설명용). No p-values, no pass / fail marks: counts and plain words.
import {h, ui, fmt} from "../core/pb.js";

const LIVE_TFS = ["15m", "30m", "1h", "4h"];
const SR_KO = {level_before_lock: "앞쪽 가격선이 첫 잠금가보다 가까움", support_before_stop: "뒤쪽 가격선이 손절선보다 가까움"};
const TL_KO = {tl_break_now: "신호 봉에서 추세선 돌파", tl_against: "안 깨진 추세선을 거슬러 진입", tl_support: "뒤쪽 추세선이 받쳐 줌",
  tl_aligned: "추세선 기울기와 같은 방향"};
const EXIT_KO = {X5_TRAIL2: "2 ATR 손절 + 추적", X2_SL15_TP3: "1.5 ATR 손절 · 3 ATR 익절", SWING_BAND: "릴스 자체 청산"};

const li = (...kids) => h("li", null, ...kids);
const n0 = (x) => fmt.int(x || 0);

/** Same-sign entry numbers per live timeframe: [{tf, items: [{ko, dir, max}]}] (dir +1: stronger came out a little better). */
export function sameSign(es) {
  const by = new Map();
  for (const f of (es && es.features) || []) {
    if (!f.same_sign_all3 || !LIVE_TFS.includes(f.tf)) continue;
    const r = (f.spearman_p1_p2_p3 || []).filter((x) => x != null).map(Number).filter(Number.isFinite);
    if (!r.length) continue;
    if (!by.has(f.tf)) by.set(f.tf, []);
    by.get(f.tf).push({ko: f.label_ko || f.feature, dir: r[0] > 0 ? 1 : -1, max: Math.max(...r.map(Math.abs))});
  }
  return LIVE_TFS.filter((tf) => by.has(tf)).map((tf) => ({tf, items: by.get(tf)}));
}

function corePanel(rp) {
  const sr = rp.support_resistance || {}, es = rp.entry_strength || {}, tl = rp.trendline || {};
  const total = (sr.tests || 0) + (es.tests || 0) + (tl.tests || 0);
  if (!total) {
    return [h("p", null, "이 매매법은 5년 신호가 적어(1기 300개 미만) 진입 연구에서 시험한 칸이 없습니다.")];
  }
  const srHit = sr.passed_all3 || [], tlHit = tl.passed_all3 || [];
  // what is left after the three periods, from the study (an S/R hit that random entries show too is the market's)
  const left = srHit.filter((x) => !x.note).length + (Number(es.passed_all3) || 0) + tlHit.length;
  const ss = sameSign(es);
  const ssN = ss.reduce((a, x) => a + x.items.length, 0);
  const esN5 = ((es.features || []).filter((f) => f.tf === "5m")).length;
  return [
    h("p", null, `같은 5년 자료로 이 매매법의 진입을 ${fmt.int(total)}건 시험했고, 세 기간 확인을 거쳐 남은 후보는 ${fmt.int(left)}건입니다.`),
    h("ul", {class: "strat-lines small"},
      li(h("b", null, "지지·저항 "), `${n0(sr.tests)}건 · `, (sr.features || []).map((f) => SR_KO[f] || f).join(" / "),
        srHit.length ? h("span", {class: "muted"}, ` · 세 기간 같은 효과 ${fmt.int(srHit.length)}건 (${srHit.map((x) => `${fmt.tfKo(x.tf)}: ${x.note || "설명용"}`).join(", ")})`) : h("span", {class: "muted"}, " · 남은 것 없음")),
      li(h("b", null, "진입 수치 "), `${n0(es.tests)}건 · 조건이 강하게 맞을수록 결과가 좋은가 · 남은 것 ${n0(es.passed_all3)}건`),
      li(h("b", null, "추세선 "), `${n0(tl.tests)}건 · `, (tl.features || []).map((f) => TL_KO[f] || f).join(" / "),
        h("span", {class: "muted"}, tlHit.length ? ` · 세 기간 같은 효과 ${fmt.int(tlHit.length)}건` : " · 남은 것 없음"))),
    ssN ? ui.disclosure(`진입 수치: 세 기간 방향만 같았던 ${fmt.int(ssN)}개 보기`, h("div", {class: "stack tight"},
      h("p", {class: "muted small"}, "아무 관계가 없어도 4개 중 1개꼴로 세 기간 방향이 같게 나옵니다. 크기는 −1~+1 (0이면 관계 없음)이고 세 기간 중 가장 큰 값을 적었습니다. 거래가 적은 칸(특히 4시간봉 3기)은 크기가 크게 흔들립니다.", Number(es.passed_all3) ? "" : " 이 가운데 미리 정한 기준을 넘은 것은 없습니다."),
      h("ul", {class: "strat-lines small"}, ss.map((x) => li(h("b", null, `${fmt.tfKo(x.tf)} `),
        x.items.map((it) => `${it.ko} (${it.dir > 0 ? "강할수록 조금 나은 쪽" : "강할수록 조금 나쁜 쪽"}, 최대 ${fmt.num(it.max, 3)})`).join(" · ")))),
      esN5 ? h("p", {class: "muted small"}, `5분봉 칸 ${fmt.int(esN5)}개는 과거 기록이라 뺐습니다 (36개는 지금 5분봉을 거래하지 않음).`) : null))
      : h("p", {class: "muted small"}, "진입 수치 가운데 세 기간 방향이라도 같았던 것은 지금 봉에서 없습니다."),
  ];
}

function dsPanel(rp, kind) {
  const out = [h("p", null, "이 매매법은 진입 연구(지지·저항 · 진입 수치 · 추세선) 대상이 아닙니다.")];
  if (kind === "reel") {
    const x = rp.h1;
    out.push(x ? h("p", null, "대신 사전 등록한 시험 H1(지금 계좌와 같은 5분봉 진입·청산)을 같은 5년 자료로 했습니다: ",
      `1·2기 합친 거래당 ${fmt.num(x.mean12_pct, 3)}% (${fmt.int(x.n12)}건), 3기 ${fmt.num(x.pre_mean_pct, 3)}%. 1배 가격 %, 비용 뒤.`) : null,
      h("p", {class: "muted small"}, `봉·진입 방식을 바꾼 격자 ${fmt.int(rp.configs)}개 설정 가운데 세 기간 모두 플러스 ${fmt.int(rp.all3_positive)}개, 남은 후보 ${fmt.int(rp.candidates)}개.`));
  } else {
    const fg = rp.family_gauntlet || {};
    out.push(h("p", null, `대신 딥시크 200 연구가 같은 5년 자료로 이 정의를 ${fmt.int(rp.configs)}개 설정(봉 × 연구 청산 2종)으로 시험했습니다: `,
      `세 기간 모두 플러스 ${fmt.int(rp.all3_positive)}개, 남은 후보 ${fmt.int(rp.candidates)}개.`),
      rp.family_ko ? h("p", {class: "muted small"}, `같은 계열(${rp.family_ko}) 전체 ${fmt.int(fg.configs)}개 설정: 세 기간 모두 플러스 ${fmt.int(fg.all3_positive)}개, 남은 후보 ${fmt.int(fg.candidate)}개.`) : null);
    const per = (k) => (r) => (r[k + "_mean_pct"] == null ? "—" : h("span", {class: fmt.tone(r[k + "_mean_pct"])}, `${fmt.num(r[k + "_mean_pct"], 3)}%`));
    const rows = (rp.tests || []).slice(0, 12);
    if (rows.length) {
      out.push(ui.disclosure(`설정별 거래당 순손익 ${fmt.int(rows.length)}줄 보기`, h("div", {class: "stack tight"},
        ui.table([{label: "봉", l: true, get: (r) => fmt.tfKo(r.tf)}, {label: "연구 청산", l: true, get: (r) => EXIT_KO[r.exit] || r.exit},
          {label: "1기", get: per("is")}, {label: "2기", get: per("cf")}, {label: "3기", get: per("pre")}], rows),
        h("p", {class: "muted small"}, "거래당 순손익 = 진입가 대비 가격 %, 레버리지 없음, 비용 뒤."),
        rp.exit_note_ko ? h("p", {class: "muted small"}, rp.exit_note_ko) : null)));
    }
  }
  return out;
}

/** The panel for one strategy page: p = the /api/profile answer, kind = strategy | ds200 | reel. */
export function priorPanel(p, kind) {
  const rp = p && p.research_prior;
  const head = h("div", {class: "strat-priorh"}, h("b", null, "이미 해 본 시험"), h("span", {class: "muted small"}, " · 사전 등록 · 같은 5년 자료"));
  if (!rp) {
    return h("div", {class: "strat-prior stack tight"}, head,
      h("p", {class: "muted"}, p ? "이 매매법은 진입 연구 대상이 아닙니다." : "연구 기록을 불러오지 못했습니다."));
  }
  const body = kind === "strategy" && rp.support_resistance ? corePanel(rp) : dsPanel(rp, kind);
  return h("div", {class: "strat-prior stack tight"}, head, ...body,
    rp.conclusion_ko ? h("div", {class: "strat-priorc"}, h("span", {class: "pp thin"}, "설명용"), " ", ui.moreText(rp.conclusion_ko, 2, "small")) : null,
    h("p", {class: "muted small"}, "같은 시험을 다시 해도 새 정보가 아닙니다. 지금 계좌의 성적은 30일째 판정이 따로 봅니다."));
}
