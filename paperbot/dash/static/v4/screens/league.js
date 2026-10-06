// #/league[/<member id>] — 그림자 리그 (owners 10/06: "그래도 어차피 모의 거래인데 넣어볼만하지 않아?"). A failed 5-year idea (the reel's
// 매물대 지지→저항 전환) followed live as VIRTUAL trades in a database of its own: not one of the 331 accounts, not judged on the
// verdict day, no orders. /api/v4/shadowleague (dash/more/shadowleague.py, read-only) answers the members' cards and the chosen member's
// record; this screen draws:
//   head card      what a shadow account is and is not
//   멤버           status, 기록 시작일, 신호 수, 열린·닫힌 거래, a waiting bar toward 30 closed trades while the record is small
//   누적 수익 곡선   the member against the coin-flip clones' median and 10-90 % band (core/lwc.js)
//   가상 계좌       the owners' account (5,000 USDT, 20 % x 20x) with its max drawdown, per timeframe
//   코인 × 봉       one cell per series, totals per coin and per timeframe
//   최근 거래 · 신호 기록
//   5년 시험은 이랬어요  the pre-registered 5-year result (실패) next to the live numbers
// HONESTY: the file missing = '아직 켜지 않았어요' with how it is turned on (the server's settings file, never a button here); the file
// unreadable = an error box with its reason, never an empty record; a missing table switches off only its own block; every number
// block says 참고용, 판정 아님.
import {h, put, ui, fmt, motion, serverNow} from "../core/pb.js";
import {headCard, notStartedCard, errorCard, fileNotes} from "./league-kit.js";
import {memberCard} from "./league-member.js";
import {curveCard} from "./league-chart.js";
import {accountCard} from "./league-account.js";
import {tableCard, tradesCard, signalsBlock} from "./league-table.js";
import {studyCard} from "./league-study.js";

const API = "/api/v4/shadowleague";
const REFRESH_MS = 60 * 1000;          // the agents write every 15 minutes; the server answers from a 5 s cache
let current = null;

/** The answer without the clock fields: a poll that changed nothing does not redraw the charts. */
const signature = (d) => JSON.stringify(d, (k, v) => (k === "now_ms" || k === "as_of_ms" ? undefined : v));

export async function mount(el, ctx) {
  ctx.setTitle("그림자 리그");
  el.append(ui.screenHead("그림자 리그", "5년 시험에서 떨어진 아이디어를 실제 봉에서 가상 거래로만 지켜봐요 · 참고용, 판정 아님"));
  const st = {member: ctx.params.arg || null, d: null, sig: null, board: null, verdictTs: null, headSig: null};
  const headSlot = h("div", {class: "lg-slot"});
  const staleSlot = h("div", {class: "lg-slot"});
  const body = h("div", {class: "lg-body"}, motion.shimmer(3));
  el.append(headSlot, staleSlot, body);

  function paintHead() {
    const sig = `${st.board}|${st.verdictTs}`;
    if (sig === st.headSig) return;
    st.headSig = sig;
    put(headSlot, headCard({accounts: st.board, verdictTs: st.verdictTs}));
  }
  ctx.watch("board", (b) => { st.board = b && b.accounts ? b.accounts.length : null; paintHead(); });
  ctx.watch("summary", (s) => {
    const rs = (s && s.restart) || {};
    st.verdictTs = (rs.ready ? rs.verdict_ts : null) || (s && s.next_checkpoint && s.next_checkpoint.ts) || null;
    paintHead();
  });
  paintHead();

  function picker(d) {
    if (!d.members || d.members.length < 2) return null;
    return ui.seg(d.members.map((m) => ({id: m.member_id, label: m.short_ko || m.name_ko || m.member_id})), d.selected,
      (id) => ctx.go("league", id), {label: "멤버 고르기", scroll: true});
  }

  function render(d) {
    const parts = [];
    if (d.state === "not_started") {
      parts.push(notStartedCard(d), studyCard(d, studyOf(d, null)));
    } else if (d.state === "error") {
      parts.push(errorCard(d, load), studyCard(d, studyOf(d, null)));
    } else {
      const m = d.member || {state: "error", reason_ko: "멤버 기록이 비어 있어요"};
      parts.push(picker(d), fileNotes(d));
      if (m.state !== "ok") {
        parts.push(errorCard({reason: m.reason, reason_ko: m.reason_ko || "이 멤버의 기록을 읽지 못했어요", path: d.path}, load), studyCard(d, studyOf(d, null)));
      } else {
        parts.push(memberCard(d, m), curveCard(ctx, m, d), accountCard(ctx, m), h("div", {class: "lg-col"}, tableCard(m), signalsBlock(m)), tradesCard(m), studyCard(d, m));
      }
    }
    const kids = parts.filter(Boolean);
    put(body, kids);
    for (const k of kids) if (typeof k.draw === "function") k.draw();
  }

  async function load() {
    let d;
    const q = st.member ? `?member=${encodeURIComponent(st.member)}` : "";
    try { d = await ctx.api(API + q); } catch (e) {
      if (!ctx.alive()) return;
      // a refresh that fails after a good read keeps the page but says the numbers are old (never silently stale)
      if (st.d) {
        put(staleSlot, h("p", {class: "lg-warn"}, ui.pill("새로 못 읽음", "warn"),
          ` 방금 새로 고치지 못했어요. 아래 숫자는 ${fmt.ago(st.d.now_ms, serverNow())}에 읽은 거예요.`));
      } else put(body, ui.errorBox(e, load));
      return;
    }
    if (!ctx.alive()) return;
    put(staleSlot);
    const sig = signature(d);
    st.d = d;
    if (sig === st.sig) return;
    st.sig = sig;
    render(d);
  }
  current = {set(arg) { st.member = arg || null; st.sig = null; load(); }};
  await load();
  ctx.every(REFRESH_MS, load, {now: false});
}

/** The study of a member for the not-started / error states (the member's detail is not there): the first known one. */
function studyOf(d, m) {
  if (m) return m;
  const k = (d.known || [])[0];
  return {study: k && d.studies ? d.studies[k.study] : null, comparison: null};
}

export function update(params) { if (current) current.set(params.arg); }
export function unmount() { current = null; }
