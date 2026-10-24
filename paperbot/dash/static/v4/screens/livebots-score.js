// 실거래 › 성적: 매매법 성적표 and 개선 후보 장부 (/api/v4/livebots/perf `scorecard`, `ledger`; paperbot/liveimprove.py).
//   매매법 성적표  per strategy of the paper account (the trades both executors follow): live trades, wins, win rate, the
//                 backtest's fit win rate and its honest one (unseen 2025-26), the status word exactly as liveimprove gives it
//                 (표본 작음 / 기대 안 / 주의 / 확실히 나쁨), the paper money, and per executor what costs and slippage took on
//                 the trades it followed (실제 − 페이퍼, %p of the margin). Sorting; the note that with 27 strategies one or
//                 two 주의 come by luck alone. Computed now by liveimprove's own functions (the `score` command's numbers).
//   개선 후보 장부 liveimprove.db's ledger: open items first, each with its research question, its evidence when found and now,
//                 the next step and the exact command that moves it (the page moves nothing: a status changes only by that
//                 command, by hand, with a note); then the adoption rule set in advance (three conditions) as liveimprove
//                 prints it.
// HONESTY: liveimprove's numbers and words only; a file not there yet says 수집 전, one that cannot be read 못 읽음 + why;
// small samples are 표본 작음 (no verdict); paper money keeps its caption.
import {h, put, ui, fmt, local} from "../core/pb.js";
import {sourceState, mainFollowKo, acctKo, allFollowKo} from "./livebots-kit.js";

const SORTS = [{id: "n", label: "거래 많은 순"}, {id: "status", label: "상태"}, {id: "excess", label: "기대 대비"}, {id: "win", label: "승률"},
  {id: "pnl", label: "손익"}];
/** The status words' tones (liveimprove: SMALL, OK, WATCH, BAD in that order). */
const TONE = ["thin", "good", "warn", "bad"];
export const toneOf = (words, w) => TONE[(words || []).indexOf(w)] || "thin";

/** The rows in an order: n (liveimprove's: most trades first), status (worst first), excess (wins below what the honest
 *  rate expects first), win, pnl (lowest first for the last two would hide the good ones: highest first). */
export function sortRows(rows, by, words) {
  const rank = (r) => (words || []).indexOf(r.status);
  const ex = (r) => (r.n ? r.wins - r.n * (r.honest ?? 0) : 0);
  const key = {n: (r) => [-r.n, r.key], status: (r) => [-rank(r), -r.n, r.key], excess: (r) => [ex(r), -r.n, r.key],
    win: (r) => [-(r.win ?? -1), -r.n, r.key], pnl: (r) => [-(r.pnl ?? 0), -r.n, r.key]}[by] || ((r) => [-r.n, r.key]);
  return [...(rows || [])].sort((a, b) => {
    const x = key(a), y = key(b);
    for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1;
    return 0;
  });
}

const pc = (x, d = 0) => (x == null ? "—" : fmt.pct(x, d, false));

function execCell(name, e, ok) {
  const ko = acctKo(name);                               // 바이비트 · WOO X Pro · 딥코인 (the site's names)
  if (!ok) return h("span", {class: "muted"}, `${ko} 기록 못 읽음`);
  if (!e || !e.n) return h("span", {class: "muted"}, `${ko} 따라간 거래 없음`);
  return h("span", null, `${ko} ${fmt.int(e.n)}번`, e.leak != null ? h("b", {class: ["num", fmt.tone(e.leak)]}, ` ${fmt.num(e.leak * 100, 1, true)}%p`) : "");
}

/** One strategy row: name and status, the counts against the backtest, the executors' cost gap. */
export function scoreRow(r, d) {
  const okEx = Object.fromEntries((d.execs || []).map((x) => [x.id, x.followed]));
  const ko = r.key ? fmt.stratKo(r.key) : null;
  return h("div", {class: "lb-sc", role: "listitem"},
    h("div", {class: "lb-sch"}, h("b", {class: "lb-scl"}, ko && ko !== r.key ? ko : r.label),
      ko && ko !== r.key ? h("span", {class: "muted lb-scc"}, r.label) : null,
      ui.pill(r.n ? r.status : "거래 없음", r.n ? toneOf(d.words, r.status) : "thin")),
    h("div", {class: "lb-scn num"}, h("span", null, `${fmt.int(r.n)}번 ${fmt.int(r.wins)}승`), h("b", null, r.win == null ? "—" : pc(r.win, 0)),
      h("span", {class: "muted"}, `맞춘 ${pc(r.fit)} · 처음 보는 ${pc(r.honest)}${r.honest_src === "전체" ? "*" : ""}`),
      h("span", {class: ["num", fmt.tone(r.pnl)]}, `손익 ${fmt.money(r.pnl, true)}`)),
    (d.execs || []).every((x) => okEx[x.id] && !((r.exec || {})[x.id] || {}).n) ? h("div", {class: "lb-scx muted"}, "실거래가 따라간 거래 없음")
      : h("div", {class: "lb-scx"}, h("span", {class: "muted"}, "실거래 비용 "),
        ...(d.execs || []).map((x, i) => [i ? h("span", {class: "muted"}, " · ") : null, execCell(x.id, (r.exec || {})[x.id], okEx[x.id])])));
}

/** scoreView(ctx) -> {el, set(scorecard)}: the 매매법 성적표 card. */
export function scoreView(ctx) {
  const st = {sort: local.get("lb-ssort", "n"), empty: false, d: null};
  if (!SORTS.some((s) => s.id === st.sort)) st.sort = "n";
  const sseg = ui.seg(SORTS, st.sort, (id) => { st.sort = id; local.set("lb-ssort", id); draw(true); }, {label: "줄 순서", scroll: true});
  const emptyBtn = h("button", {type: "button", "aria-pressed": "false", onclick: () => { st.empty = !st.empty; draw(true); }}, "거래 없는 매매법도");
  const head = h("div", {class: "lb-schead"});
  const notes = h("div", {class: "lb-scnotes"});
  const pg = ui.pager({size: 10, row: (r) => scoreRow(r, st.d), empty: () => (!st.d ? h("p", {class: "note"}, "불러오는 중")
    : st.d.state === "ok" ? ui.empty("페이퍼 닫힌 거래가 아직 없어요") : null)});
  const el = ui.card({title: "매매법 성적표", sub: "페이퍼(두 실행기가 따라가는 계좌) 닫힌 거래 · 백테스트 기준과 비교 · 지금 계산", cls: "lb-sccard"},
    head, h("div", {class: "lb-scbar"}, sseg, h("div", {class: "seg"}, emptyBtn)), pg.el, notes);
  const sub = el.firstChild ? Array.from(el.firstChild.childNodes).find((n) => String(n.className || "") === "sub") || null : null;
  function draw(user) {
    const d = st.d;
    // two paper bots (owners 10/23): who follows the paper scored here, by name; one: the usual words
    const sw = `페이퍼(${mainFollowKo() || allFollowKo()} 계좌) 닫힌 거래 · 백테스트 기준과 비교 · 지금 계산`;
    if (sub && sub.textContent !== sw) sub.textContent = sw;
    emptyBtn.setAttribute("aria-pressed", String(st.empty));
    if (!d) { put(head); put(notes); pg.set(undefined); return; }
    if (d.state !== "ok") { put(head, sourceState(d, "매매법 성적표")); put(notes); pg.set([]); return; }
    const o = d.overall || {};
    put(head,
      h("p", {class: "lb-sco"}, h("b", null, `전체 ${fmt.int(o.n)}번 ${fmt.int(o.wins)}승 · ${o.win == null ? "—" : pc(o.win, 1)}`),
        ui.pill(o.status || "—", toneOf(d.words, o.status)), h("span", {class: ["num", fmt.tone(o.pnl)]}, ` 손익 ${fmt.money(o.pnl, true)} USDT`)),
      h("p", {class: "lb-scref muted"}, `기준: 맞춘 ${pc(o.fit)} · 처음 보는 기간 ${pc(o.honest)} · 본전 ${pc(o.break_even, 1)}`),
      ...(d.problems || []).map((t) => h("p", {class: "lb-warn"}, t)));
    const rows = (d.rows || []).filter((r) => st.empty || r.n);
    pg.set(sortRows(rows, st.sort, d.words), !user);
    const hidden = (d.rows || []).length - (d.rows || []).filter((r) => r.n).length;
    emptyBtn.textContent = hidden ? `거래 없는 매매법 ${fmt.int(hidden)}개도` : "거래 없는 매매법도";
    emptyBtn.disabled = !hidden;
    put(notes,
      h("p", {class: "lb-luck"}, `※ ${d.luck_ko}`),
      ui.note("실거래 비용: 실행기가 따라간 같은 거래에서 실제 순ROE − 페이퍼 순ROE (%p, 증거금 대비). −면 비용·미끄러짐으로 샌 거예요"),
      (d.rows || []).some((r) => r.n && r.honest_src === "전체") ? ui.note("* 처음 보는 기간 거래가 30번 미만인 매매법은 전체 승률(처음 보는 기간)과 비교해요") : null,
      o.n < (d.check_n || 40) ? ui.note(`첫 진짜 점검은 거래 ${fmt.int(d.check_n || 40)}번이에요 (지금 ${fmt.int(o.n)}번). 그 전 차이는 대부분 운이에요`) : null,
      ui.disclosure("상태 말 읽는 법", h("ul", {class: "lb-schow"}, (d.how_ko || []).map((t) => h("li", null, t.replace(/^- /, ""))))),
      h("p", {class: "note"}, "같은 숫자를 서버에서: ", h("code", {class: "lb-cmd"}, d.cmd || "")));
  }
  return {el, set(d) {
    const sig = d ? JSON.stringify(d) : "";                  // the same answer again: nothing redrawn (an open row stays open)
    if (d && sig === st.sig) return;
    st.sig = sig; st.d = d || null; draw(false);
  }};
}

const STATUS_TONE = {"발견": "accent", "백테스트 시험": "warn", "그림자 시험": "warn", "채택": "good", "기각": "thin"};
const FLOW = ["발견", "백테스트 시험", "그림자 시험", "채택"];
const wr = (w, n) => (n ? `${fmt.int(w)}/${fmt.int(n)}승 (${pc(w / n)})` : "0번");

/** One ledger item: open ones in full (evidence, question, next step, the exact command, its history), closed ones short. */
export function ledgerItem(it) {
  const head = h("div", {class: "lb-lgh"}, h("b", {class: "num"}, `#${fmt.int(it.id)}`), ui.pill(it.status, STATUS_TONE[it.status] || "thin"),
    h("b", {class: "lb-lgl"}, it.label), h("span", {class: "muted"}, `${it.kind_ko || ""} · 찾은 날 ${it.found || "—"}`));
  const log = (it.log || []).length ? ui.disclosure(`기록 ${fmt.int(it.log.length)}개`, h("ul", {class: "lb-lglog"}, it.log.map((x) =>
    h("li", null, h("span", {class: "num muted"}, x.day || ""), " ", h("b", null, x.old ? `${x.old} → ${x.new}` : x.new), x.note ? ` · ${x.note}` : "",
      x.who ? h("span", {class: "muted"}, ` (${x.who})`) : null)))) : null;
  if (!it.open) {
    return h("div", {class: "lb-lg closed", role: "listitem"}, head, it.note ? h("p", {class: "lb-lgq muted"}, `메모: ${it.note}`) : null, log);
  }
  const ev = it.latest || {};
  const at = FLOW.indexOf(it.status);
  return h("div", {class: "lb-lg", role: "listitem"}, head,
    ui.stepStrip(FLOW.map((s) => ({id: s, label: s})), {done: FLOW.slice(0, Math.max(0, at)), now: it.status, label: "장부 단계"}),
    h("p", {class: "lb-lgev"}, h("span", {class: "muted"}, "찾을 때 "), h("b", {class: "num"}, wr(it.wins, it.n)),
      h("span", {class: "muted"}, ` · 기대 ${pc(it.expected)} (${it.expected_src || ""}) · 그 주 본 칸 ${fmt.int(it.family)}개`)),
    ev.n != null ? h("p", {class: "lb-lgev"}, h("span", {class: "muted"}, "지금 "), h("b", {class: "num"}, wr(ev.wins || 0, ev.n || 0)),
      it.rule_a ? ui.pill("규칙 (a) 맞음", "good") : null) : null,
    h("p", {class: "lb-lgq"}, h("span", {class: "muted"}, "질문 "), it.question),
    h("p", {class: "lb-lgq"}, h("span", {class: "muted"}, "다음 "), h("b", null, it.next_ko)),
    (it.cmds || []).length ? h("div", {class: "lb-lgcmds"}, it.cmds.map((c) => h("code", {class: "lb-cmd"}, c))) : null,
    it.note ? h("p", {class: "lb-lgq muted"}, `마지막 메모: ${it.note}`) : null, log);
}

/** ledgerView() -> {el, set(ledger)}: 개선 후보 장부 and the adoption rule. */
export function ledgerView() {
  const head = h("div", {class: "lb-lghead"});
  let mode = "loading";
  const pg = ui.pager({size: 10, row: ledgerItem, empty: () => (mode === "ok" ? ui.empty("장부가 아직 비어 있어요: 주간 점검이 찾은 후보가 없어요")
    : mode === "loading" ? h("p", {class: "note"}, "불러오는 중") : null)});
  const rule = h("div", {class: "lb-adopt"});
  const el = ui.card({title: "개선 후보 장부", sub: "손실이 기대보다 몰린 칸 · 보기만 (상태는 서버 명령으로만 바뀌어요)", cls: "lb-lgcard"}, head, pg.el, rule);
  let sig0 = "";
  return {el, set(d) {
    const sig = d ? JSON.stringify(d) : "";                  // the same answer again: nothing redrawn (an open log stays open)
    if (d && sig === sig0) return;
    sig0 = sig;
    mode = !d ? "loading" : d.state === "ok" ? "ok" : "off";
    if (!d) { put(head); put(rule); pg.set(undefined); return; }
    if (d.state !== "ok") { put(head, sourceState(d, "개선 후보 장부")); put(rule); pg.set([]); return; }
    const w = d.week;
    put(head, h("p", {class: "lb-lgsum"}, h("b", null, `열린 것 ${fmt.int(d.open_n)}개`), h("span", {class: "muted"}, ` / 전체 ${fmt.int(d.n)}개`)),
      w ? ui.note(`마지막 주간 점검 ${w.week} · 본 칸 ${fmt.int(w.tested)}개 중 후보 ${fmt.int(w.flagged)}개 (운만으로도 약 ${fmt.num((w.tested || 0) * 0.05, 1)}개)`
        + (w.sent === false ? " · 텔레그램 못 보냄" : "")) : ui.note("주간 점검 기록이 아직 없어요 (월요일 09:30)"),
      h("p", {class: "note"}, `명령은 서버에서 ${d.cd} 한 뒤에 써요. 전체 보기: `, h("code", {class: "lb-cmd"}, d.list_cmd)));
    pg.set(d.items || [], true);
    const r = d.adopt_rule || [];
    put(rule, r.length ? [h("h3", {class: "lb-h3"}, r[0]), h("ul", {class: "lb-adoptl"}, r.slice(1, -1).map((t) => h("li", null, t))),
      h("p", {class: "note"}, r[r.length - 1])] : null);
  }};
}
