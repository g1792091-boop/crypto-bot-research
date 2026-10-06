// 30일 판정 › 판정 뒤 할 일 (review 10/06 addition 2): what the owners ask on the verdict morning, once /api/checkpoint
// says ready. ① three lines: trading does not change, the 1차 합격 accounts' 2nd check and the held accounts' next try
// on the next checkpoint's date; ② the 매매법 × 봉 result map (the 36 by strategy on 15분 · 30분 · 1시간; DeepSeek, the 5m
// reel and the extras as group counts only, owners' D10 / D11); ③ the real-trading checklist of every account that passed
// (/api/v4/verdictday/after: agents/readiness, 충족 / 아직 / 모름 per condition); ④ the lead's checkpoint meeting
// (/api/v4/verdictday meeting), rule B's evaluation (/api/analysis/levrule) and the way into 졸업 길 (#/path).
// HONESTY: only the stored verdict's own statuses; a load that failed says so (never '없음'); nothing per DeepSeek account.
import {h, put, ui, fmt} from "../core/pb.js";
import {judgedTfs, verdictDate} from "./home-shared.js";

const PASS2 = "2차 통과", PASS1 = "1차 합격", FAIL = "불합격", HOLD = "보류", OBS = "관찰용";
const RANK = {[PASS2]: 0, [PASS1]: 1, [FAIL]: 2, [HOLD]: 3, [OBS]: 4};
const SHORT = {[PASS2]: "2차", [PASS1]: "1차", [FAIL]: "불합격", [HOLD]: "보류", [OBS]: "관찰"};
const CLS = {[PASS2]: "good", [PASS1]: "good", [FAIL]: "bad", [HOLD]: "thin", [OBS]: "thin"};
const V_KO = {met: "충족", not_yet: "아직", unknown: "모름"};
const V_CLS = {met: "good", not_yet: "warn", unknown: "thin"};
const GROUP_LINES = [["ds200", "딥시크"], ["reel", "5분봉 단타"], ["extra", "추가 계좌 (복제·새 매매법)"]];

const count = (rows, s) => rows.filter((r) => r.status === s).length;

/** A verdict row of a DeepSeek account (owners' D10 / D11: DeepSeek money only on its own group screen). */
export const isDs = (r) => !!r && (r.group === "ds200" || r.family === "ds200");
/** The stored verdict's reason without its dollar amounts (checkpoint.decide words: '평가금 $X ≤ 시작 $Y', ', 평가금 $X',
 *  '손익 $X'), for a DeepSeek row on 판정: the rule in words, the money only on the DeepSeek screen. */
const USD = "\\$-?\\d+(?:,\\d{3})*(?:\\.\\d+)?";        // "$60,000", "$-1,234" (never the comma after it)
const RX = (src) => new RegExp(src.replace(/USD/g, () => USD), "g");
export function moneyFree(text) {
  return String(text || "")
    .replace(RX("평가금 USD ≤ 시작 USD"), "평가금이 시작 잔고 이하")
    .replace(RX(", 평가금 USD"), "")
    .replace(RX("2차 기간 손익 USD"), "2차 기간 손익 플러스 아님")
    .replace(RX(", 손익 USD"), "")
    .replace(RX("USD"), "(금액은 딥시크 화면에서)");
}
const strat = (r) => String(r.account_id || "").split("@")[0];

/** The 36 by strategy x judged timeframe: [{strategy, best, cells: {tf: row}}], the passes first. */
export function mapRows(ck, board) {
  const tfs = judgedTfs(board, "strategy");
  const by = new Map();
  for (const r of (ck && ck.rows) || []) {
    if (r.group !== "core" || !tfs.includes(r.timeframe)) continue;
    const s = strat(r);
    if (!by.has(s)) by.set(s, {strategy: s, cells: {}});
    by.get(s).cells[r.timeframe] = r;
  }
  const out = [...by.values()].map((x) => ({...x, best: Math.min(...Object.values(x.cells).map((r) => RANK[r.status] ?? 9))}));
  out.sort((a, b) => a.best - b.best || fmt.stratKo(a.strategy).localeCompare(fmt.stratKo(b.strategy)));
  return {tfs, rows: out};
}

// the next checkpoint's date from the clock, only once the clock has seen this verdict (between two summary polls it
// still names the verdict's own day)
function nextDate(summary, ck) {
  const c = summary && summary.verdict_clock;
  return c && c.ts && c.last && c.last.date === ck.date ? fmt.mmdd(c.ts) : "다음 판정 날";
}

function lines(ck, summary) {
  const rows = (ck.rows || []).filter((r) => r.group !== "flip");
  const n1 = count(rows, PASS1), n2 = count(rows, PASS2), nh = count(rows, HOLD), nf = count(rows, FAIL);
  const nd = nextDate(summary, ck);
  // past day 180 (checkpoint.NO_VERDICT_DAYS) there is no next verdict: no '2차 확인' date is promised
  const last = !!(summary && summary.verdict_clock && summary.verdict_clock.state === "ended");
  return h("ul", {class: "cka-lines"},
    h("li", null, h("b", null, "거래는 아무것도 바뀌지 않습니다"),
      " · 모든 모의 계좌가 같은 규칙으로 계속 돕니다. 판정은 이름표일 뿐이고, 실거래는 두 분이 정하기 전에는 없습니다."),
    last ? h("li", null, h("b", null, "180일 실험의 마지막 판정입니다"), " · 더 이상 판정(2차 확인 · 보류 다시)은 없습니다")
      : h("li", null, n1 ? [h("b", null, `1차 합격 ${fmt.int(n1)}개는 ${nd}에 2차 확인`),
        " · 그 30일 동안의 새 거래 30건 이상 · 그 기간 손익 플러스 · 운 시험 다시"]
        : [h("b", null, "1차 합격 0개"), ` · ${nd}에 2차 확인할 계좌가 없습니다`]),
    last ? h("li", null, h("b", null, `1차 합격 ${fmt.int(n1)}개 · 보류 ${fmt.int(nh)}개`))
      : h("li", null, h("b", null, `보류 ${fmt.int(nh)}개도 ${nd}에 다시`), " · 그때 거래가 30건을 넘은 계좌는 1차 판정을 받습니다"),
    nf ? h("li", null, h("b", null, `불합격 ${fmt.int(nf)}개`), " · 이 판정으로 끝 (계좌는 그대로 계속 돎)") : null,
    n2 ? h("li", null, h("b", null, `2차 통과 ${fmt.int(n2)}개`), " · 실거래 조건 점검으로 (아래 표)") : null);
}

function resultMap(ck, board, phoneAll, ctx) {
  const {tfs, rows} = mapRows(ck, board);
  if (!rows.length) return ui.empty("이 판정에 기존 36 계좌 줄이 없습니다");
  // three blocks side by side on a PC, each with its own column heads; a phone shows the first block until 모두 보기
  const per = Math.max(1, Math.ceil(rows.length / 3));
  const blocks = [];
  for (let i = 0; i < rows.length; i += per) blocks.push(rows.slice(i, i + per));
  const headOf = () => h("div", {class: "cka-mh", "aria-hidden": "true"}, h("span", null, "매매법"), tfs.map((tf) => h("span", null, fmt.tfKo(tf))));
  const list = h("div", {class: ["cka-map", phoneAll.on ? "all" : ""], "aria-label": "매매법 × 봉 판정 결과"}, blocks.map((blk) => h("div", {class: "cka-blk", role: "list"}, headOf(),
    blk.map((x) => h("div", {class: "cka-mrow", role: "listitem"},
      h("span", {class: "cka-mn", title: x.strategy}, fmt.stratKo(x.strategy)),
      tfs.map((tf) => {
        const r = x.cells[tf];
        if (!r) return h("span", {class: "cka-c none", title: `${fmt.tfKo(tf)}: 판정 줄 없음`}, "—");
        return h("a", {class: ["cka-c", CLS[r.status] || ""], href: ctx.href("account", r.account_id),
          title: `${fmt.stratKo(x.strategy)} · ${fmt.tfKo(tf)}: ${r.status}${r.reason ? ` · ${r.reason}` : ""}`,
          "aria-label": `${fmt.stratKo(x.strategy)} ${fmt.tfKo(tf)} ${r.status}`}, SHORT[r.status] || r.status);
      }))))));
  const more = blocks.length > 1 ? h("button", {class: "btn-line cka-more", type: "button", "aria-expanded": String(phoneAll.on),
    onclick: (e) => { phoneAll.on = !phoneAll.on; list.classList.toggle("all", phoneAll.on); e.currentTarget.setAttribute("aria-expanded", String(phoneAll.on));
      e.currentTarget.textContent = phoneAll.on ? "접기" : `${fmt.int(rows.length)}개 모두 보기`; }},
  phoneAll.on ? "접기" : `${fmt.int(rows.length)}개 모두 보기`) : null;
  const groups = GROUP_LINES.map(([g, ko]) => {
    const gr = (ck.rows || []).filter((r) => r.group === g && r.status !== OBS);
    if (!gr.length) return null;
    const parts = [PASS2, PASS1, FAIL, HOLD].map((s) => [s, count(gr, s)]).filter(([, n]) => n);
    return h("li", null, h("b", null, `${ko} ${fmt.int(gr.length)}개`), " · ",
      parts.length ? parts.map(([s, n]) => `${s} ${fmt.int(n)}`).join(" · ") : "—",
      g === "ds200" ? h("span", {class: "muted"}, " (계좌별로는 보이지 않음)") : null);
  }).filter(Boolean);
  return h("div", {class: "stack tight"}, list, more,
    h("p", {class: "muted home-small"}, "칸 = 그 봉 계좌의 판정 · 1차 = 1차 합격 · 2차 = 2차 통과 · 4시간봉은 관찰용이라 빠짐 · 칸을 누르면 그 계좌"),
    groups.length ? h("ul", {class: "cka-groups"}, groups) : null);
}

function checklist(d, ctx) {
  if (!d) return h("p", {class: "muted home-small"}, "실거래 조건을 읽는 중…");
  if (d.pending) return h("p", {class: "muted home-small"}, "실거래 조건을 계산하는 중입니다. 잠시 뒤 자동으로 나옵니다.");
  if (d.error || d.failed) return h("p", {class: "ck-bad", role: "status"}, `실거래 조건을 불러오지 못했습니다${d.error ? ` (${d.error})` : ""}. 없다는 뜻이 아닙니다 · 1분 뒤 다시 시도합니다.`);
  if (!d.ready) return h("p", {class: "muted home-small"}, "판정 기록을 아직 읽지 못했습니다.");
  const order = d.order || [];
  const accts = d.accounts || [];
  const dsLine = d.ds_passed ? h("p", {class: "muted home-small"}, `딥시크에서 합격한 계좌 ${fmt.int(d.ds_passed)}개 (계좌별로는 보이지 않음)`) : null;
  if (!accts.length) {
    return h("div", {class: "stack tight"}, h("p", {class: "ink2"}, "합격한 계좌가 없어 실거래 조건을 볼 계좌가 없습니다. 규칙: 아무것도 합격하지 못하면 실거래는 없습니다."), dsLine);
  }
  return h("div", {class: "stack tight"},
    h("div", {class: "cka-ck", role: "list"}, accts.map((a) => h("div", {class: "cka-ckrow", role: "listitem"},
      h("div", {class: "cka-ckh"}, ui.pill(a.status, "good"), h("a", {class: "lname", href: ctx.href("account", a.account_id), title: a.account_id}, fmt.idName(a.account_id)),
        a.status === PASS1 ? h("span", {class: "muted"}, "실거래 검토는 2차 통과 뒤") : null),
      h("div", {class: "cka-ckc"}, order.map((id) => {
        const c = (a.conditions || {})[id] || {v: "unknown"};
        return h("span", {class: ["pp", V_CLS[c.v] || "thin"], title: c.why || ""}, `${(d.labels || {})[id] || id} · ${V_KO[c.v] || "모름"}`);
      })),
      a.in_readiness ? null : h("p", {class: "muted home-small"}, "이 계좌는 실전 준비도 표(기존 36 · 5분봉)에 없어 모두 '모름'입니다")))),
    dsLine,
    h("p", {class: "muted home-small"}, "충족 / 아직 / 모름 · 실제 비용과 테스트넷 연습은 실거래 직전에 두 분이 확인하는 항목이라 지금은 '모름' · 표시만 합니다 (아무것도 켜지 않음)"));
}

function meetingLine(m, ctx) {
  const go = h("a", {class: "btn-line", href: ctx.href("rooms", "team:lead")}, "회의 보기 →");
  if (m === undefined) return h("span", {class: "muted"}, "읽는 중…");
  if (m === null) return h("span", null, "아직 시작 전 · 총괄이 판정 결과를 받으면 회의를 엽니다 ", go);
  if (m.error || m.failed) return h("span", {class: "ck-bad"}, "회의 기록을 읽지 못했습니다 (없다는 뜻이 아님) · 1분 뒤 다시 확인");
  if (m.status === "running") return h("span", null, h("b", null, "진행 중"), ` · ${fmt.hm(m.started_ts)} 시작 `, go);
  return h("span", null, h("b", null, `끝남 ${fmt.hm(m.ended_ts)}`), m.line ? ` · '${m.line}'` : "", " ", go);
}

function levruleLine(lv, ctx) {
  const go = h("a", {class: "btn-line", href: ctx.href("analysis", "levrule")}, "평가 보기 →");
  if (lv === undefined) return h("span", {class: "muted"}, "읽는 중…");
  if (!lv || lv.failed) return h("span", {class: "ck-bad"}, "규칙 B 평가를 불러오지 못했습니다 (없다는 뜻이 아님) ", go);
  if (lv.pending) return h("span", {class: "muted"}, "계산 중 · 잠시 뒤 자동으로 ", go);
  if (lv.error) return h("span", {class: "ck-bad"}, `${lv.error} `, go);
  return h("span", null, h("b", null, lv.status_ko || "—"), " ", go);
}

/** afterCard(ctx) -> card with .update({ck, board, summary, vd}); it asks its own two routes (checklist, rule B). */
export function afterCard(ctx) {
  const st = {ck: null, board: null, summary: null, vd: null, list: null, lv: undefined, phoneAll: {on: false}, busy: false,
    failedAt: 0};
  const head = h("p", {class: "cka-head"});
  const linesBox = h("div");
  const mapBox = h("div");
  const ckBox = h("div");
  const meetBox = h("div");
  const lvBox = h("div");
  const card = ui.card({hero: true, plate: "판정 뒤 할 일", sub: "그래서 이제 뭐가 바뀌나", cls: "cka"}, head, linesBox,
    h("h3", {class: "cka-h3"}, "매매법 × 봉 결과 지도"), mapBox,
    h("h3", {class: "cka-h3"}, "합격한 계좌의 실거래 조건"), ckBox,
    h("h3", {class: "cka-h3"}, "다음에 볼 것"),
    h("div", {class: "cka-links"},
      h("div", {class: "cka-link"}, h("span", {class: "k"}, "총괄 판정 회의"), meetBox),
      h("div", {class: "cka-link"}, h("span", {class: "k"}, "레버리지 규칙 B 평가 (같은 날)"), lvBox),
      h("div", {class: "cka-link"}, h("span", {class: "k"}, "졸업 길"), h("span", null, "아이디어 → 5년 시험 → 모의 계좌 → 판정 → 실전 후보 ",
        h("a", {class: "btn-line", href: ctx.href("path")}, "졸업 길 보기 →")))));

  async function loadList() {
    if (st.busy) return;
    st.busy = true;
    try { st.list = await ctx.api("/api/v4/verdictday/after"); } catch (e) {
      if (e && e.name === "AbortError") { st.busy = false; return; }
      st.list = {failed: true};
      st.failedAt = Date.now();
    }
    st.busy = false;
    if (!ctx.alive()) return;
    put(ckBox, checklist(st.list, ctx));
    if (st.list && st.list.pending) ctx.timeout(loadList, 3000);
  }
  async function loadLev() {
    try { st.lv = await ctx.api("/api/analysis/levrule"); } catch (e) {
      if (e && e.name === "AbortError") return;
      st.lv = {failed: true};
    }
    if (!ctx.alive()) return;
    put(lvBox, levruleLine(st.lv, ctx));
    if (st.lv && st.lv.pending) ctx.timeout(loadLev, 3000);
  }
  let loadedFor = null;
  card.update = (o) => {
    Object.assign(st, o);
    const ck = st.ck;
    if (!ck || !ck.ready) return;
    put(head, `${ck.day ?? "—"}일째 판정 · ${verdictDate(ck.date)} 09:00 (한국 시각) 결과로 정리했습니다`);
    put(linesBox, lines(ck, st.summary));
    put(mapBox, resultMap(ck, st.board, st.phoneAll, ctx));
    // /api/v4/verdictday (asked every minute by 판정): its failed load says so, never 'still reading' for ever
    put(meetBox, meetingLine(!st.vd ? undefined : st.vd.failed ? {failed: true} : st.vd.meeting, ctx));
    if (loadedFor !== ck.date) {
      loadedFor = ck.date;
      put(ckBox, checklist(null, ctx)); put(lvBox, levruleLine(undefined, ctx));
      loadList(); loadLev();
    } else if (st.list && st.list.failed && Date.now() - st.failedAt >= 60000) loadList();     // once a minute, not per render
  };
  return card;
}
