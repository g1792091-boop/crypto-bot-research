// 그림자 리그 (#/league) kit: the words and small pieces every part of the screen shares: the head card (what a shadow
// account is and is not), the three states that are not a record (아직 켜지 않았어요 / 못 읽었어요 / 이 부분은 자료 표가 없어요),
// the switch's how-to (who turns it on: the server's settings file, never a button here) and the last-run line.
// HONESTY: a failed read is an error box with its reason, never 0 or an empty list; every number block says 참고용, 판정 아님.
import {h, ui, fmt, serverNow} from "../core/pb.js";

export const LABEL = "참고용, 판정 아님";
const STATUS_TONE = {recording: "good", waiting: "thin", warming: "accent", error: "bad", off: "thin", halted: "warn"};

/** A percent that is already in percent units, with its sign colour ("+0.30%", "−0.10%"). */
export const pctB = (v, dec = 2) => h("b", {class: ["num", fmt.tone(v, fmt.pctOf(v, dec, true))]}, v == null ? "—" : fmt.pctOf(v, dec, true));
export const statusPill = (c) => ui.pill(c.status_ko, STATUS_TONE[c.status] || "thin");
export const labelPill = () => ui.pill(LABEL, "thin");
/** The pill of a member's 5-year study ("5년 시험 실패"), null when the page has none for it. */
export const studyPill = (s) => (s ? ui.pill(`5년 시험 ${s.verdict_ko}`, s.verdict === "FAIL" ? "bad" : "thin", s.one_line_ko) : null);

/** The card for a block the database file cannot give (an older or newer file has no such table): says why, never a zero. */
export function unavailableCard(title, blk) {
  return ui.card({plate: title, sub: LABEL, cls: "lg-off"},
    h("p", {class: "lg-warn"}, ui.pill("자료 표 없음", "warn"), " ", blk.reason_ko || "이 부분은 아직 보여 줄 수 없어요"),
    ui.note("읽지 못한 것을 0이나 '없음'으로 보이지 않으려고 이 칸을 비워 두었어요. 에이전트가 새 모양으로 기록 파일을 올리면 채워져요."));
}

// ---------------------------------------------------------------- the head card
/** o: {accounts: the board's account count | null, verdictTs: the first verdict (ms) | null}. */
export function headCard(o = {}) {
  const verdict = o.verdictTs ? `${fmt.mmdd(o.verdictTs)} 판정` : "30일 판정";
  const accts = o.accounts ? `${fmt.int(o.accounts)}개 모의 계좌` : "모의 계좌들";
  return ui.card({plate: "그림자 리그", title: "떨어진 아이디어를 돈 없이 구경만 해요", sub: LABEL, hero: true, cls: "lg-head", label: "그림자 계좌란"},
    h("p", {class: "lg-lead"}, "5년 자료로 시험했더니 실패했지만 '그래도 한번 지켜보고 싶다'고 하신 아이디어를, 지금 실제로 닫히는 봉 위에서 "
      + "같은 규칙 그대로 돌려 봐요. 신호가 나오면 '여기서 들어갔다면' 하는 가상 거래를 적고, 손절·목표·48봉 시간 청산까지 따라가서 결과를 적어요."),
    h("div", {class: "lg-two"},
      h("section", {class: "lg-box"}, h("h3", null, "그림자 계좌는 이런 거예요"),
        h("ul", null,
          h("li", null, "5년 시험과 같은 규칙을 실제 봉에서 가상 거래로만 기록해요."),
          h("li", null, "결과 옆에는 늘 5년 시험 숫자(실패)를 같이 놓아요."),
          h("li", null, "다른 아이디어가 생기면 같은 방식으로 한 명씩 더해요."))),
      h("section", {class: "lg-box lg-not"}, h("h3", null, "이런 건 아니에요"),
        h("ul", null,
          h("li", null, `${accts} 중 하나가 아니에요. 진짜 계좌도, 돈도, 주문도 없어요. 아래 '가상 계좌'는 그렇게 했다면 어땠을지 계산한 숫자예요.`),
          h("li", null, `${verdict}을 받지 않아요. 여러 번 시험한 만큼의 보정에도 세지 않아요.`),
          h("li", null, "실제 주문이 아니에요. 거래소에 올리는 것이 하나도 없어요."),
          h("li", null, "잘해도 못해도 다른 계좌의 결과·순위·판정에는 영향이 없어요.")))),
    ui.note(h("b", null, "솔직한 기대 "), "5년 동안 안 된 규칙이 몇 주 사이에 갑자기 되는 이유는 없어요. 지금도 비용에 지는 것이 예상이고, 거래가 적을 때의 "
      + "플러스는 운일 수 있어요. 그래서 이 화면의 모든 숫자에 '참고용, 판정 아님'을 붙여요."));
}

// ---------------------------------------------------------------- how it is turned on (never a button here)
export function switchBox(sw) {
  const s = sw || {};
  return h("div", {class: "lg-switch"},
    h("h3", null, "켜는 법"),
    ui.kv([["켜고 끄는 곳", "서버의 설정 파일 (이 화면에는 버튼이 없어요)"], ["파일", h("code", null, s.file || "/etc/paperbot/agents.env")],
      ["적을 한 줄", h("code", null, `${s.name || "AGENTS_SHADOW_LEAGUE"}=${s.value || "1"}`)]]),
    h("p", {class: "lg-sub"}, s.how_ko || "서버의 설정 파일에서 켜고 끕니다. 서버 설정을 바꾸는 쪽에 부탁해 주세요."));
}

/** The member is not running (never started, or no new record for 3 hours). */
export function offBox(c, sw) {
  return h("div", {class: "lg-banner off", role: "status"},
    h("p", {class: "lg-bt"}, ui.pill(c.status_ko, "thin"), " ", c.off_ko || "꺼져 있어요."),
    c.last_tick_ms ? h("p", {class: "lg-sub"}, `마지막으로 기록한 때: ${fmt.kst(c.last_tick_ms)} (${fmt.ago(c.last_tick_ms, serverNow())})`) : null,
    h("p", {class: "lg-sub"}, "꺼져 있는 동안 지나간 봉은 켠 뒤에 순서대로 따라잡아 기록해요(빠진 것도, 두 번 센 것도 없게). 따라잡아 계산한 신호에는 '뒤늦게' 표시가 붙어요."),
    switchBox(sw));
}

/** Nothing has ever been recorded (no file, or no member in it): the member is off, said plainly. */
export function notStartedCard(d) {
  const names = (d.known || []).map((k) => k.name_ko).filter(Boolean);
  return ui.card({plate: "그림자 리그", title: "아직 켜지 않았어요", sub: LABEL, cls: "lg-off", acts: [ui.pill("꺼짐", "thin")]},
    h("p", {class: "lg-bt"}, d.reason_ko || "기록 파일이 아직 없어요."),
    names.length ? h("p", {class: "lg-sub"}, `켜면 이 멤버부터 기록해요: ${names.join(" · ")}`) : null,
    h("p", {class: "lg-sub"}, "꺼져 있는 동안은 가상 거래도 신호도 없어요. 아래 5년 시험 숫자는 켜지 않아도 볼 수 있어요."),
    switchBox(d.switch),
    d.path ? ui.disclosure("찾아본 파일 위치 (자세히)", h("p", {class: "lg-sub"}, h("code", null, d.path), " 에는 아직 기록이 없어요. 화면이 엉뚱한 곳을 보고 있다면 서버 설정에서 위치를 확인해야 해요.")) : null);
}

/** The file is there but could not be read: the reason in words and raw, never an empty record. */
export function errorCard(d, retry) {
  return ui.card({plate: "그림자 리그", title: "기록 파일을 읽지 못했어요", sub: LABEL, cls: "lg-err", acts: [ui.pill("오류", "bad")]},
    h("p", {class: "lg-bt"}, d.reason_ko || "읽는 중 문제가 생겼어요."),
    h("p", {class: "lg-sub"}, "읽지 못한 것을 '거래 0건'처럼 보이지 않으려고 이 화면은 기록을 비워 두었어요. 기록이 없어진 것이 아니라 이번에 못 읽은 거예요."),
    ui.disclosure("이유 (자세히)", h("div", {class: "lg-raw"}, h("p", null, h("code", null, d.reason || "")), d.path ? h("p", null, h("code", null, d.path)) : null)),
    h("div", {class: "lg-actions"}, h("button", {type: "button", class: "btn-line", onclick: retry}, "다시 읽기")));
}

/** The line under the member card: the notes of the file's shape, tables missing, the last run and its problems. */
export function fileNotes(d) {
  const kids = [];
  for (const n of d.notes_ko || []) kids.push(h("p", {class: "lg-warn"}, ui.pill("파일 모양", "warn"), " ", n));
  if ((d.tables_missing || []).length) {
    kids.push(h("p", {class: "lg-warn"}, ui.pill("표 없음", "warn"), ` 기록 파일에 없는 표: ${d.tables_missing.join(", ")}. 그 표가 필요한 부분만 비워 두었어요.`));
  }
  if (d.requested_missing) kids.push(h("p", {class: "lg-warn"}, ui.pill("멤버 없음", "warn"), " 주소의 멤버가 기록에 없어서 첫 멤버를 보여 드려요."));
  const t = d.last_tick;
  if (t) {
    const bits = [`새 봉 ${fmt.int(t.bars_added)}개`, `신호 ${fmt.int(t.signals)}`, `진입 ${fmt.int(t.opened)}`, `청산 ${fmt.int(t.closed)}`];
    kids.push(h("p", {class: "lg-sub"}, `마지막 실행 ${t.ms ? fmt.kst(t.ms) : "—"} (${fmt.ago(t.ms, serverNow())}): ${bits.join(" · ")}`,
      t.timed_out ? " · 시간이 모자라 일부는 다음 차례로 넘겼어요" : "", t.behind ? ` · 따라잡는 중인 칸 ${fmt.int(t.behind)}개` : ""));
    if ((t.errors_ko || []).length) {
      kids.push(ui.disclosure(`마지막 실행에서 있었던 문제 ${fmt.int(t.errors_ko.length)}건`, h("ul", {class: "lg-list"}, t.errors_ko.map((e) =>
        h("li", null, e.ko, h("small", {class: "muted"}, ` (${e.raw})`))))));
    }
  } else if (d.state === "ok") {
    // 'no run recorded' and 'the record could not be read' are different things (a failed read is never 'none')
    if (d.last_tick_state === "unreadable") kids.push(h("p", {class: "lg-warn"}, ui.pill("읽지 못함", "warn"), " 마지막 실행 기록의 글이 깨져 있어서 읽지 못했어요. 실행이 없었다는 뜻이 아니에요."));
    else if (d.last_tick_state === "missing_table") kids.push(h("p", {class: "lg-warn"}, ui.pill("표 없음", "warn"), " 기록 파일에 마지막 실행을 적는 표가 없어서 언제 실행했는지 알 수 없어요."));
    else kids.push(h("p", {class: "lg-sub"}, "아직 실행 기록이 없어요(켠 뒤 첫 15분 차례가 오기 전)."));
  }
  return kids.length ? h("div", {class: "lg-notes"}, kids) : null;
}
