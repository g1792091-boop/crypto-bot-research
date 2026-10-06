// 누가 맞았나 (design 102 C, paperbot/agents/disputes.py): the staff board's card, the chip on a staff row, a
// strategy room's sides and disputes, and the lab room's shared test queue. Every word is the server's code text except
// a dispute's claim (the attacker's own words, shown as a quote). A score always sits next to its side's base rate and
// the coin flip's 50 %, and says 표본 적음 under 10 settled disputes. Nothing here is a pass / fail of an account.
// CORE CANDIDATE: sideTag() is the same idea as rooms-kit's sideChip (the shared-queue branch); keep one after merge.
import {h, ui, fmt} from "../core/pb.js";
import {avatarFor} from "./rooms-kit.js";

const SMALL = 10;
const share = (x) => (x == null ? "—" : fmt.pct(x, 0, false));
const SOURCE_KO = {debate: "토론방", meeting: "회의", owner: "두 분", researcher: "연구원", lab: "연구원"};
const NOTE_KO = "앞으로 N건 확인(20~60건)은 동전 던지기 50%와 함께 봅니다. 5년 시험 다툼은 편드는 쪽이 거의 늘 이깁니다(바꾼 규칙이 "
  + "나아진 예가 드묾). 한 모델이 모든 역할을 맡으므로 사람의 실력 점수가 아닙니다.";

/** 'advocate' -> 편드는 직원 (green), 'attacker' -> 공격하는 직원 (red). */
export function sideTag(side) {
  return side === "attacker" ? ui.pill("공격하는 직원", "bad") : ui.pill("편드는 직원", "good");
}

/** '누가 맞았나 7/10' on a staff row (the whole run), or null when the member has no dispute yet. */
export function rightChip(r) {
  if (!r || !(r.settled || r.pending)) return null;
  const tip = `결론 난 다툼 ${r.settled}개 중 ${r.won}개 맞음 · 그 편의 기준 비율로만 맞혔다면 ${fmt.num(r.expected || 0, 1)}개 · 대기 ${r.pending}개`;
  return h("span", {class: "dg-wrchip"}, ui.pill(r.settled ? `누가 맞았나 ${fmt.int(r.won)}/${fmt.int(r.settled)}` : `다툼 대기 ${fmt.int(r.pending)}`, "thin", tip),
    r.settled ? ui.smallSample(r.settled, SMALL) : null);
}

function bar(label, v, cls) {
  return h("div", {class: "dg-rate"}, h("span", null, label),
    h("div", {class: "prog"}, h("i", {style: {"--p": v == null ? "0%" : `${Math.round(v * 100)}%`}, class: cls || ""})),
    h("b", null, share(v)));
}

function roleRow(r) {
  const at = r.as_attacker || {}, ad = r.as_advocate || {};
  return h("div", {class: "lrow", role: "listitem"},
    avatarFor({[r.role]: {name: r.name}}, r.role, r.name),
    h("span", {class: "lname"}, r.name || r.role),
    h("span", {class: "ret"}, r.settled ? `맞음 ${fmt.int(r.won)}/${fmt.int(r.settled)}` : "결론 전"),
    h("span", {class: "meta"},
      r.settled ? h("span", null, `기준 비율로만 맞혔다면 ${fmt.num(r.expected || 0, 1)}개`) : null,
      at.won + at.lost ? h("span", null, `공격할 때 ${fmt.int(at.won)}/${fmt.int(at.won + at.lost)}`) : null,
      ad.won + ad.lost ? h("span", null, `편들 때 ${fmt.int(ad.won)}/${fmt.int(ad.won + ad.lost)}`) : null,
      r.pending ? h("span", null, `대기 ${fmt.int(r.pending)}`) : null,
      r.conceded ? h("span", null, `인정 ${fmt.int(r.conceded)}`) : null,
      r.talk_only ? h("span", null, `말로만 ${fmt.int(r.talk_only)}`) : null,
      r.gave_up ? h("span", null, `포기 ${fmt.int(r.gave_up)}`) : null,
      r.settled ? ui.smallSample(r.settled, SMALL) : null));
}

function resultPill(d) {
  if (d.status === "settled") return ui.pill(d.winner_ko || "결론", "accent");
  return ui.pill(d.status_ko || d.status, "thin");
}

function resultRow(d) {
  return h("div", {class: "lrow dg-wrres", role: "listitem"}, resultPill(d),
    h("span", {class: "lname"}, `#${d.id} · ${d.strategy_ko || d.strategy}`),
    h("span", {class: "ret muted"}, d.settled_ts ? fmt.kst(d.settled_ts) : fmt.kst(d.ts)),
    h("span", {class: "meta"}, h("span", null, `공격 ${d.side_a_name} vs 편 ${d.side_b_name}`),
      h("span", null, `주장: “${d.claim_ko}”`), h("span", null, d.settle_ko),
      d.trial_id ? h("span", null, `5년 시험 #${d.trial_id}`) : null,
      d.outcome ? h("span", null, d.outcome) : null));
}

/** The staff board's '누가 맞았나 (실험 전체)' card from /api/digest/staff's who_was_right. */
export function whoWasRightCard(w) {
  if (!w) return null;
  const t = w.tiles || {}, br = w.base_rates || {};
  const roles = (w.roles || []).filter((r) => r.settled || r.pending || r.conceded || r.talk_only || r.gave_up);
  const sub = "실험 전체 · 코드가 시험 결과로 채점";
  if (!t.settled && !t.pending && !roles.length) {
    return ui.card({plate: "누가 맞았나", sub}, h("p", {class: "ink2"},
      "아직 다툼이 없습니다. 매매법 방의 공격하는 직원이 반대하며 가릴 시험을 정하면, 시험 결과로 코드가 누가 맞았는지 채점합니다."),
    h("p", {class: "rk-note"}, NOTE_KO));
  }
  const lab = br.lab || {}, fwd = br.forward || {};
  const people = ui.pager({size: 10, empty: "아직 다툼에 낀 직원이 없습니다", row: roleRow});
  const recent = ui.pager({size: 5, empty: "아직 끝난 다툼이 없습니다", row: resultRow});
  people.set(roles);
  recent.set(w.recent || []);
  return ui.card({plate: "누가 맞았나", sub, cls: "dg-wr"},
    h("div", {class: "stats s4"},
      ui.stat("결론 난 다툼", fmt.int(t.settled || 0), h("span", {class: "s"}, `공격 쪽 ${fmt.int(t.attacker_won || 0)} · 편 쪽 ${fmt.int((t.settled || 0) - (t.attacker_won || 0))} `,
        ui.smallSample(t.settled || 0, SMALL))),
      ui.stat("공격 쪽이 이긴 비율", share(t.attacker_share), "기준: 아래 막대와 동전 50%"),
      ui.stat("대기", fmt.int(t.pending || 0), "5년 시험 대기 또는 앞으로 N건 확인 중"),
      ui.stat("인정 · 말로만 · 포기", `${fmt.int(t.conceded || 0)} · ${fmt.int(t.talk_only || 0)} · ${fmt.int(t.gave_up || 0)}`, "점수 없음")),
    h("div", {class: "dg-rates"},
      bar(`공격 쪽 승 · 5년 시험 (${fmt.int(lab.attacker_won || 0)}/${fmt.int(lab.settled || 0)})`, lab.attacker_share, ""),
      bar(`공격 쪽 승 · 앞으로 N건 (${fmt.int(fwd.attacker_won || 0)}/${fmt.int(fwd.settled || 0)})`, fwd.attacker_share, ""),
      bar("동전 던지기 (기준)", 0.5, "dim")),
    h("p", {class: "rk-note"}, NOTE_KO),
    h("h3", {class: "dg-wrh"}, "직원별"), people.el,
    h("h3", {class: "dg-wrh"}, "최근 결론"), recent.el);
}

/** A strategy room's '편: … · 공격: …' and its disputes ({sides, disputes, base_rates}: /api/disputes?room=, or /api/trials'
 *  sides and disputes). Null when sides were never on and the room has no dispute. */
export function roomSides(d) {
  const seats = d && d.sides, rows = (d && d.disputes) || [];
  if (!seats && !rows.length) return null;
  const seat = (s, side) => s ? h("p", {class: "row wrap"}, sideTag(side), h("b", null, s.name),
    h("span", {class: "muted"}, (s.record_side && (s.record_side.won + s.record_side.lost))
      ? `이 편에서 맞음 ${fmt.int(s.record_side.won)}/${fmt.int(s.record_side.won + s.record_side.lost)}` : "아직 결론 난 다툼 없음"),
    s.record && s.record.settled ? ui.smallSample(s.record.settled, SMALL) : null) : null;
  const br = d.base_rates || (seats && seats.base_rates) || {};
  const row = (d) => h("div", {class: "rm-trow"},
    h("span", null, `다툼 #${d.id} · ${d.settle_ko}`, d.progress_ko ? ` · ${d.progress_ko}` : ""), resultPill(d));
  return h("section", {class: "rm-sec"}, h("h3", null, "편 가르기 · 누가 맞았나"),
    seats ? [seat(seats.advocate, "advocate"), seat(seats.attacker, "attacker")] : null,
    rows.length ? rows.slice(0, 5).map(row) : h("p", {class: "muted"}, "아직 이 방의 다툼이 없습니다"),
    rows.length > 5 ? ui.disclosure(`나머지 ${fmt.int(rows.length - 5)}개`, rows.slice(5, 20).map(row)) : null,
    h("p", {class: "rk-note"}, `공격 쪽이 이긴 비율: 5년 시험 ${share((br.lab || {}).attacker_share)}, 앞으로 N건 ${share((br.forward || {}).attacker_share)}, `
      + "동전 던지기 50%. 5년 시험 다툼은 편드는 쪽이 거의 늘 이기니 이 기준과 함께 봅니다. 시험은 이 방 장부로 돌고, 채점은 코드가 합니다."));
}

/** The lab room's shared test queue (/api/lab/intake, the shared-queue branch): source, what is tested (code text), its
 *  state, today's quota and the bar. Until the server has the queue (a 404): '수집 전', never a made-up list. */
export function labIntake(d) {
  if (!d || d.error) return h("section", {class: "rm-sec"}, h("h3", null, "5년 시험 대기열"),
    h("p", null, ui.notYet("수집 전", "시험 대기열이 아직 이 서버에 없습니다")));
  const items = d.items || d.view || d.cards || [];
  const today = d.today && typeof d.today === "object" ? d.today : null;
  const quota = today ? Object.entries(today.by_source || today).filter(([, v]) => v && typeof v === "object" && v.limit != null)
    .map(([k, v]) => `${SOURCE_KO[k] || k} ${fmt.int(v.used || 0)}/${fmt.int(v.limit)}`) : [];
  const row = (it) => {
    const det = it.detail || it.result || {};
    const n = det.test_number ?? it.test_number;
    return h("div", {class: "rm-trow"},
      h("span", null, ui.pill(SOURCE_KO[it.source] || it.source || "—", "thin"), " ", it.description_ko || ""),
      h("span", {class: "row wrap"}, ui.pill(it.status_ko || it.status || "—", it.status === "tested" ? "accent" : "thin"),
        n != null ? h("small", {class: "muted"}, `${fmt.int(n)}번째 시험 · 기준 p<0.05/${fmt.int(n)}`) : null));
  };
  return h("section", {class: "rm-sec"}, h("h3", null, "5년 시험 대기열"),
    quota.length ? h("p", {class: "muted"}, `오늘 몫: ${quota.join(" · ")}`) : null,
    items.length ? items.slice(0, 5).map(row) : h("p", {class: "muted"}, "대기 중인 시험이 없습니다"),
    items.length > 5 ? ui.disclosure(`나머지 ${fmt.int(items.length - 5)}개`, items.slice(5, 20).map(row)) : null,
    h("p", {class: "rk-note"}, "연구원·토론방·회의 다툼·두 분이 낸 시험이 한 줄로 섭니다. 무엇을 시험할지는 코드가 정하고, 시험마다 그 장부의 시험 수에 들어가 통과 기준이 엄격해집니다."));
}
