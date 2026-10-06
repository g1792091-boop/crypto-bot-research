// 그림자 리그: the member card. Status, 기록 시작일, 신호 수, 열린·닫힌 거래, and while the record is small a waiting bar toward
// 30 closed trades (the floor the 30-day verdict uses; under it a mean is more luck than rule).
// HONESTY: a block the file could not give (a missing table) is notYet('표 없음'), never 0; the status words are the bot's own
// (꺼짐 / 시작 전 / 워밍업 중 / 기록 중 / 오류 / 멈춤); 5-year verdict next to the live numbers.
import {h, ui, fmt} from "../core/pb.js";
import {progressBar} from "./analysis-kit.js";
import {LABEL, pctB, statusPill, studyPill, offBox} from "./league-kit.js";

const tfk = (tf) => fmt.tfKo(tf);
const gone = () => ui.notYet("표 없음", "기록 파일에 이 표가 없어서 읽지 못했어요");

function statusBanner(c, d) {
  if (c.status === "off") return offBox(c, d.switch);
  if (c.status === "halted") {
    return h("div", {class: "lg-banner halt", role: "status"}, h("p", {class: "lg-bt"}, ui.pill(c.status_ko, "warn"), " ", c.halted_ko || "이 멤버는 멈췄어요."),
      h("p", {class: "lg-sub"}, "멤버의 규칙은 한 번 기록한 뒤에는 바꿀 수 없어요. 규칙을 바꾸고 싶으면 그것은 새 멤버(새 사전 등록)가 맞아요. 쌓인 기록은 그대로 남아 있어요."));
  }
  if (c.status === "waiting") {
    return h("div", {class: "lg-banner", role: "status"}, h("p", {class: "lg-bt"}, ui.pill("시작 전", "thin"),
      ` 시작일(${fmt.date(c.started_at_ms)}) 전이라 아직 기록할 봉이 없어요.`, c.starts_in_days > 0 ? ` ${fmt.num(c.starts_in_days, 1)}일 뒤에 시작해요.` : ""));
  }
  if (c.status === "warming") {
    return h("div", {class: "lg-banner", role: "status"}, h("p", {class: "lg-bt"}, ui.pill("워밍업 중", "accent"),
      " 신호를 내려면 봉이 300개 필요해서 아직 모으는 중이에요. 다 모이면 기록을 시작해요."));
  }
  if (c.status === "error") {
    return h("div", {class: "lg-banner bad", role: "alert"}, h("p", {class: "lg-bt"}, ui.pill("오류", "bad"),
      " 칸마다의 상태를 읽을 수 없거나, 모든 칸이 시세를 못 받고 있어요. 아래 오류 칸의 이유를 봐 주세요."));
  }
  return null;
}

function cellList(items, what) {
  if (!items.length) return null;
  const show = items.slice(0, 6);
  const line = (x) => h("li", null, h("b", null, `${x.coin} ${tfk(x.tf)}`), " ", what(x));
  const more = items.length - show.length;
  return h("ul", {class: "lg-list"}, show.map(line), more > 0 ? h("li", {class: "muted"}, `외 ${fmt.int(more)}칸`) : null);
}

/** The card. d: the endpoint's answer, m: the chosen member's detail (state ok). */
export function memberCard(d, m) {
  const c = m.card, t = c.trades, s = c.signals, sr = c.series;
  const need = d.min_trades || 30;
  const study = m.study;
  const started = c.started_at_ms <= d.now_ms;
  const sig = s ? h("span", null, `진입 ${fmt.int(s.taken)} · 건너뜀 ${fmt.int(s.skipped)}${s.pending ? ` · 대기 ${fmt.int(s.pending)}` : ""}`,
    s.late ? h("span", {class: "muted", title: "신호가 난 봉이 켜기 전이라 나중에 계산했어요"}, ` · 뒤늦게 ${fmt.int(s.late)}`) : null) : null;
  const stats = h("div", {class: "stats lg-stats"},
    ui.stat("기록 시작일", fmt.date(c.started_at_ms), started ? `${fmt.num(c.days, 1)}일째` : `${fmt.num(c.starts_in_days, 1)}일 뒤 시작`),
    ui.stat("신호", s ? fmt.int(s.total) : gone(), sig || "신호 표 없음"),
    ui.stat("열린 거래", t ? fmt.int(t.open) : gone(), "지금 가상으로 들고 있는 것"),
    ui.stat("닫힌 거래", t ? fmt.int(t.closed) : gone(), t ? ui.smallSample(t.closed, need) || `손절·목표·48봉으로 끝난 것` : "거래 표 없음"),
    ui.stat("거래당 평균 (비용 뒤)", t ? (t.avg_net_pct == null ? "—" : pctB(t.avg_net_pct, 2)) : gone(),
      t && t.avg_gross_pct != null ? `비용 전 ${fmt.pctOf(t.avg_gross_pct, 2, true)} · 1배 기준` : "1배 기준"),
    ui.stat("이긴 거래", t ? (t.closed ? `${fmt.int(t.wins)} / ${fmt.int(t.closed)}` : "—") : gone(), t && t.win_pct != null ? `승률 ${fmt.pctOf(t.win_pct, 0)}` : "닫힌 거래 전"),
    ui.stat("기록하는 칸", sr ? `${fmt.int(sr.recording)} / ${fmt.int(sr.total)}` : gone(),
      sr ? `워밍업 ${fmt.int(sr.warming)} · 시작 전 ${fmt.int(sr.waiting)} · 오류 ${fmt.int(sr.error)}` : "칸 상태 표 없음"));
  const wait = t && t.closed < need
    ? progressBar(`닫힌 거래 ${fmt.int(need)}건까지`,
      `닫힌 거래 ${fmt.int(t.closed)}건 · ${fmt.int(need - t.closed)}건 더 쌓여야 해요. ${fmt.int(need)}건 전의 평균은 운일 수 있어서 읽지 않는 게 좋아요.`, t.closed / need) : null;
  const toStudy = h("button", {type: "button", class: "linkish", onclick: () => { const el = document.getElementById("lg-study"); if (el) el.scrollIntoView({block: "start"}); }},
    "5년 시험과 나란히 보기 ↓");
  return ui.card({plate: "멤버", title: c.name_ko, sub: c.source_ko, cls: "lg-member", label: c.name_ko, acts: [statusPill(c)]},
    h("div", {class: "lg-pills"}, ui.pill(LABEL, "thin"), studyPill(study), study ? toStudy : null),
    c.blurb_ko ? h("p", {class: "lg-sub"}, c.blurb_ko) : null,
    statusBanner(c, d),
    stats, wait,
    cellList(c.errors, (x) => h("span", {class: "lg-bad"}, x.note || "오류")),
    c.warming.length ? ui.disclosure(`워밍업 중인 칸 ${fmt.int(c.warming.length)}개`, cellList(c.warming, (x) =>
      `${fmt.int(x.have)} / ${fmt.int(x.need)}봉${x.note ? ` · ${x.note}` : ""}`)) : null);
}
