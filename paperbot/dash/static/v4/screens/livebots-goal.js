// 실거래 › 목표 (#/livebots/goal, owners 10/19 night): this Korea-time month against the owners' monthly goal (+500 %, x6:
// their target, never a forecast), from /api/v4/livebots/goal (dash/more/liveinsight.py goal()).
//   이번 달      per account (페이퍼 · 바이비트 · MEXC): the month's return in % and USDT (the live accounts with deposits and
//               withdrawals taken out), how far x6 still is and the pace it needs (per day, per weekday, as +3 % wins with
//               no loss), the pace so far
//   지금까지 기록 the paper account since the 규칙봇 15 start: the win rate with its 90 % range (Wilson) against break-even
//               (about 86 % compounded, 82-83 % as a plain sum: the owners' earlier analysis), entries per weekday
//               against the 6.2 of the in-sample replay, the average win and loss in net ROE
//   계산해 보면  the record so far carried on to the month's end at its own pace: arithmetic, labelled so, never a forecast
//   per account (owners 10/19, docs/live15-plan-ko.md): 목표에 필요한 승률 (the win rate the rest of the month needs at the
//               account's own average win / loss and entries per weekday, next to its win rate and 90 % range, and the
//               whole month's from its start: arithmetic, never a forecast); per live account 돈 늘리기 기준 (40 trades,
//               the followed paper's win rate 88 %+, the entry gap 1 net-ROE point or less: ✓ / ✗, information only); in
//               the head 규칙 고정 (until 11/3)
//   손절 비교    only while there are two paper bots (owners 10/19 final, "Mexc -35%로 가자"): Bybit on -50 % against MEXC on
//               the -35 % twin, the two-week test for the 11/3 review, side by side in one plain table (each paper bot since
//               the second one started, each live account since MEXC switched; numbers only, no verdict)
// HONESTY: a number nobody has is '—' or its reason (수집 전 / 못 읽음), never 0; small samples say so; paper money (연습)
// and real money (진짜 돈) carry their own captions; a failed refresh keeps the last answer dimmed with its age.
import {h, put, ui, fmt, motion, serverNow} from "../core/pb.js";
import {acctKo, acctTag, sourceState} from "./livebots-kit.js";

export const GOAL_API = "/api/v4/livebots/goal";
const REFRESH_MS = 60 * 1000;


// ================================================================ pure functions (node tests)
const has = (x) => x != null && Number.isFinite(Number(x));

/** How far along to the month's goal, on a log scale (x1 = 0, the goal = 1; a loss is 0): 0..1, or null. */
export function progressOf(ret, target) {
  if (!has(ret) || !has(target) || target <= 0) return null;
  const m = 1 + Number(ret);
  if (m <= 1) return 0;
  return Math.min(1, Math.log(m) / Math.log(1 + Number(target)));
}

/** A ratio range as a position on a 0..100 % scale: {lo, hi, at} in percent (one decimal), for the win-rate bar. */
export function barOf(rate, range) {
  const p = (x) => (has(x) ? Math.round(Math.max(0, Math.min(1, Number(x))) * 1000) / 10 : null);
  return {at: p(rate), lo: range ? p(range[0]) : null, hi: range ? p(range[1]) : null};
}

/** Where the 90 % range sits against break-even, in plain words (a fact about the range, not a verdict). */
export function rangeWords(range, be) {
  if (!range || !has(be)) return null;
  if (range[1] < be) return "90% 범위 전체가 본전선 아래예요";
  if (range[0] >= be) return "90% 범위 전체가 본전선 위예요";
  return "90% 범위가 본전선에 걸쳐 있어요";
}

/** A multiple in words: "×1.84"; under ×0.01 "×0.01 미만" (the arithmetic of a losing record goes to almost nothing). */
export const multKo = (m) => (!has(m) ? "—" : m < 0.01 ? "×0.01 미만" : `×${fmt.num(m, 2)}`);

/** 돈 늘리기 기준 as rows: [{mark: "✓" | "✗", ko, what}] from the server's scale checks (null without them). */
export function scaleRows(scale) {
  if (!scale || !Array.isArray(scale.checks)) return null;
  return scale.checks.map((c) => ({mark: c.ok ? "✓" : "✗", ok: !!c.ok, ko: c.ko || "", what: c.what_ko || ""}));
}

/** The pace the rest of the month needs, in words (pace: the server's {need, reached, per_day, per_weekday, wins}). */
export function paceWords(p) {
  if (!p || !has(p.need)) return "계산할 잔고가 없어요";
  if (p.reached) return "이번 달 목표에 닿았어요";
  const parts = [`목표까지 ×${fmt.num(p.need, 2)} 더`];
  if (has(p.per_day)) parts.push(`남은 날 하루 ${fmt.pct(p.per_day, 1)}씩`);
  if (has(p.per_weekday)) parts.push(`평일만 치면 하루 ${fmt.pct(p.per_weekday, 1)}씩`);
  if (has(p.wins)) parts.push(`+3% 승리로 ${fmt.int(p.wins)}번 (지는 거래 없이)`);
  return parts.join(" · ");
}

/** 손절 비교 (the server's h2h) as a plain table: {head: [two column titles], rows: [{k, cells: [two texts], tones: [two
 *  "up" | "down" | ""]}]}, null without two paper bots. Each column is one stop: its paper bot and the live account that
 *  follows it (the first one; "—" when none). */
export function h2hTable(x) {
  if (!x || x.state !== "ok" || !Array.isArray(x.sides) || x.sides.length < 2) return null;
  const S = x.sides.slice(0, 2);
  const head = S.map((s) => `손절 ${s.stop_short || "?"} · ${(s.followers || []).join("·") || "따라가는 실행기 없음"}`);
  const wl = (r) => (has(r.n) ? `${fmt.int(r.n)}번 (${fmt.int(r.wins)}승 ${fmt.int(r.losses)}패)` : "—");
  const pct = (v, sign = true) => (has(v) ? fmt.pct(v, 1, sign) : "—");
  const of = {paper: (s) => s.paper || {}, live: (s) => (s.live || [])[0]};
  const row = (k, side, text, val) => {
    const xs = S.map(of[side]);
    const cells = xs.map((r) => (!r ? "—" : r.state && r.state !== "ok" ? (r.reason_ko || "못 읽음") : text(r)));
    const tones = xs.map((r, i) => (val && r && (!r.state || r.state === "ok") ? fmt.tone(val(r), cells[i]) : ""));
    return {k, cells, tones};
  };
  const rows = [
    row("페이퍼 거래", "paper", wl),
    row("페이퍼 승률", "paper", (r) => pct(r.win_rate, false)),
    row("페이퍼 순ROE 합", "paper", (r) => pct(r.roe_sum), (r) => r.roe_sum),
    row("페이퍼 잔고 변화", "paper", (r) => pct(r.change), (r) => r.change),
    row("페이퍼 최대 낙폭", "paper", (r) => (has(r.max_dd) ? fmt.pct(-r.max_dd, 1) : "—"), (r) => (has(r.max_dd) ? -r.max_dd : null)),
  ];
  if (x.live_since_ms != null) {
    rows.push(row("실거래 거래", "live", wl), row("실거래 승률", "live", (r) => pct(r.win_rate, false)),
      row("실거래 손익", "live", (r) => (has(r.pnl) ? `${fmt.money(r.pnl, true)} USDT` : "—"), (r) => r.pnl),
      row("실거래 잔고 변화", "live", (r) => pct(r.change), (r) => r.change));
  }
  return {head, rows};
}

// ================================================================ the view
/** goalView(ctx) -> {el, set()}: its own endpoint, read now and every 60 s. */
export function goalView(ctx) {
  const st = {d: null, okAt: 0, sig: ""};
  const stateSlot = h("div", {class: "lb-slot"});
  const head = h("div", {class: "lbg-intro"});
  const cards = h("div", {class: "lbg-cards"});
  const rec = h("div", {class: "lbg-slot"});
  const imply = h("div", {class: "lbg-slot"});
  const h2h = h("div", {class: "lbg-slot"});
  const h2hCard = ui.card({title: "손절 비교 (11/3 검토용)", sub: "바이비트 −50% · MEXC −35% · 같은 신호, 손절만 다름", cls: "lbg-card lbg-h2h"}, h2h);
  h2hCard.hidden = true;                                  // one paper bot: no card (the page as before)
  const body = h("div", {class: "lbg-body stack"}, head, cards,
    ui.card({title: "지금까지 기록", sub: "페이퍼(연습) · 규칙봇 15 시작부터 닫힌 거래", cls: "lbg-card lbg-rec"}, rec),
    ui.card({title: "지금 기록 그대로라면", sub: "계산일 뿐이에요 · 예측이 아니에요", cls: "lbg-card lbg-imply"}, imply),
    h2hCard,
    h("div", {class: "lb-foot"}, ui.assumeLine(["closed"], "페이퍼(연습): 잔고는 닫힌 거래 기준"),
      ui.assumeLive("바이비트 · MEXC: 잔고 기록 기준 · 입출금 뺌")));
  const el = h("div", {class: "lbg stack"}, stateSlot, body);

  function acctCard(a, d) {
    const name = [acctTag(a.id), h("span", {class: ["lbg-kind", a.kind]}, a.kind === "live" ? "실거래 · 진짜 돈" : "모의 · 연습 돈"),
      a.follows_ko ? h("small", {class: "muted"}, ` 따라감 · ${a.follows_ko}`) : null];
    const sc = scaleRows(a.scale);
    const scaleEl = sc ? h("div", {class: "lbg-scale"}, h("b", null, "돈 늘리기 기준"), h("small", {class: "muted"}, " · 보여 주기만 해요"),
      h("ul", null, sc.map((r) => h("li", {class: r.ok ? "up" : "down", title: r.what}, `${r.mark} ${r.ko}`))),
      h("p", {class: ["lbg-scale-ko", a.scale.ok ? "up" : ""]}, a.scale.ko), ui.note(a.scale.note_ko || "")) : null;
    const nd = a.need;
    const needEl = nd ? h("div", {class: "lbg-need"}, h("p", {class: ["lbg-need-ko", nd.state === "impossible" ? "down" : nd.state === "reached" ? "up" : ""]}, nd.ko),
      nd.month_ko ? h("p", {class: "muted"}, nd.month_ko) : null,
      h("small", {class: "muted"}, `${nd.src_ko || ""} · ${nd.note_ko || ""}`)) : null;
    if (a.state !== "ok") {
      return h("section", {class: ["card", "lbg-acct", "off", "lbg-a-" + a.id]}, h("div", {class: "lbg-ah"}, ...name),
        sourceState(a, a.kind === "paper" ? "페이퍼 DB" : `${acctKo(a.id)} 잔고 기록`),
        has(a.closed_n) && a.closed_n ? ui.note(`이번 달 닫힌 거래 ${fmt.int(a.closed_n)}번 · ${fmt.money(a.closed_pnl, true)} USDT`) : null, scaleEl);
    }
    const prog = progressOf(a.ret, d.target);
    const retTxt = has(a.ret) ? fmt.pct(a.ret, 1) : "—";
    return h("section", {class: ["card", "lbg-acct", "lbg-a-" + a.id]}, h("div", {class: "lbg-ah"}, ...name),
      h("div", {class: ["lbg-ret", fmt.tone(a.ret, retTxt)]}, h("span", {class: "k"}, `${(d.month || {}).label || "이번 달"} 수익률`),
        h("b", {class: "num"}, retTxt),
        h("span", {class: "s"}, has(a.change) ? `${fmt.money(a.change, true)} USDT · ${fmt.money(a.start_equity)} → ${fmt.money(a.now_equity)}` : "—")),
      h("div", {class: "lbg-prog", role: "img", "aria-label": `목표 ×${fmt.num(d.target_mult, 0)}까지 ${prog == null ? "—" : fmt.pct(prog, 0, false)}`},
        h("i", {style: {width: `${Math.round((prog || 0) * 1000) / 10}%`}}), h("span", {class: "lbg-pgoal"}, `목표 ×${fmt.num(d.target_mult, 0)}`)),
      h("p", {class: "lbg-pace"}, paceWords(a.pace)),
      has(a.so_far_per_day) ? h("p", {class: "lbg-sofar"}, `지금까지 하루 평균 ${fmt.pct(a.so_far_per_day, 1)} (복리)`) : null,
      a.late_start ? ui.note(`이 계좌는 ${fmt.kst(a.start_ms)} 첫 잔고 기록부터 셌어요`) : null,
      ui.note(`이번 달 닫힌 거래 ${fmt.int(a.closed_n || 0)}번 · ${fmt.money(a.closed_pnl, true)} USDT`), needEl, scaleEl);
  }
  function drawRec(d) {
    const r = d.record || {};
    if (r.state !== "ok") { put(rec, sourceState(r, "페이퍼 DB")); put(imply); return; }
    const b = barOf(r.win_rate, r.wilson90), be = barOf(d.break_even).at;
    const plain = d.break_even_plain || [];
    const words = rangeWords(r.wilson90, d.break_even);
    put(rec,
      h("div", {class: "lbg-win"}, h("span", {class: "k"}, "승률"), h("b", {class: "num"}, has(r.win_rate) ? fmt.pct(r.win_rate, 1, false) : "—"),
        h("span", {class: "s"}, `${fmt.int(r.wins)}승 ${fmt.int(r.losses)}패 · ${fmt.int(r.n)}번`), ui.smallSample(r.n, d.small_n || 20)),
      r.n ? h("div", {class: "lbg-wbar", role: "img", "aria-label": `승률 ${fmt.pct(r.win_rate, 1, false)}, 90% 범위 ${fmt.pct((r.wilson90 || [])[0], 0, false)}~${fmt.pct((r.wilson90 || [])[1], 0, false)}, 본전 약 ${fmt.pct(d.break_even, 0, false)}`},
        b.lo != null ? h("span", {class: "lbg-band", style: {left: `${b.lo}%`, width: `${Math.max(0.5, b.hi - b.lo)}%`}}) : null,
        plain.length === 2 ? h("span", {class: "lbg-plain", style: {left: `${barOf(plain[0]).at}%`, width: `${Math.max(0.5, barOf(plain[1]).at - barOf(plain[0]).at)}%`}}) : null,
        be != null ? h("em", {class: "lbg-be", style: {left: `${be}%`}}) : null,
        b.at != null ? h("i", {class: "lbg-pt", style: {left: `${b.at}%`}}) : null) : null,
      h("p", {class: "lbg-wl"}, r.wilson90 ? `90% 범위 ${fmt.pct(r.wilson90[0], 0, false)}~${fmt.pct(r.wilson90[1], 0, false)} (윌슨)` : "닫힌 거래가 아직 없어요",
        ` · 본전 약 ${fmt.pct(d.break_even, 0, false)} (복리; 단순 합으로는 ${plain.map((x) => fmt.pct(x, 0, false)).join("~")})`,
        words ? ` · ${words}` : ""),
      ui.kv([["평일 하루 진입", has(r.per_weekday) ? `${fmt.num(r.per_weekday, 1)}번 (평일 ${fmt.num(r.weekdays, 1)}일에 ${fmt.int(r.weekday_entries)}번)`
        : `평일이 하루 지나면 계산해요 (지금 평일 ${fmt.num(r.weekdays, 1)}일에 ${fmt.int(r.weekday_entries)}번)`],
        ["참고", `${fmt.num(r.weekday_ref, 1)}번 (15개를 고를 때 쓴 2주를 다시 돌린 숫자라 실제는 적을 수 있어요)`],
        ["이긴 거래 평균", has(r.avg_win) ? h("b", {class: "num up"}, fmt.pct(r.avg_win, 1)) : "—"],
        ["진 거래 평균", has(r.avg_loss) ? h("b", {class: "num down"}, fmt.pct(r.avg_loss, 1)) : "—"],
        ["이 평균의 본전 승률", has(r.break_even_record) ? `약 ${fmt.pct(r.break_even_record, 1, false)} (단순 합)` : "—"]]),
      ui.note("순ROE = 증거금 대비 손익 (수수료·슬리피지 포함) · 본전 숫자는 예전 분석 (이길 때 +10%, 질 때 −50%, 증거금 30%)"));
    const m = r.implied;
    if (!m) { put(imply, ui.empty("닫힌 거래와 평일이 조금 더 쌓이면 계산해요")); return; }
    put(imply, ui.kv([["거래 한 번에 계좌", h("b", {class: ["num", fmt.tone(m.per_trade, fmt.pct(m.per_trade, 2))]}, `${fmt.pct(m.per_trade, 2)} (복리 평균)`)],
      ["이번 달 남은 거래", `약 ${fmt.num(m.trades_left, 0)}번 (평일 하루 ${fmt.num(r.per_weekday, 1)}번 × 남은 평일 ${fmt.num((d.month || {}).weekdays_left, 1)}일)`],
      ["그러면 남은 기간", multKo(m.rest_mult)], ["한 달(평일 21.7일)이면", multKo(m.month_mult)]]),
    h("p", {class: "lbg-warn"}, "지금까지 숫자를 그대로 곱한 계산일 뿐이에요. 예측이 아니고, 거래가 적을수록 크게 틀려요.",
      m.small ? ` 닫힌 거래 ${fmt.int(r.n)}번이라 대부분 운이에요.` : ""));
  }
  function drawH2h(d) {
    const x = d.h2h;
    h2hCard.hidden = !x;
    if (!x) { put(h2h); return; }
    if (x.state !== "ok") { put(h2h, sourceState(x, "두 번째 페이퍼 기록"), ui.note(x.review_ko || "")); return; }
    const t = h2hTable(x);
    put(h2h, h("p", {class: "lbg-h2h-why"}, x.review_ko),
      h("div", {class: "tbl-wrap"}, h("table", {class: "tbl lbg-h2h-t"},
        h("thead", null, h("tr", null, h("th", {class: "l"}, ""), ...t.head.map((c) => h("th", null, c)))),
        h("tbody", null, t.rows.map((r) => h("tr", null, h("td", {class: "l"}, r.k),
          ...r.cells.map((c, i) => h("td", {class: ["num", r.tones[i]]}, c))))))),
      h("p", {class: "lbg-h2h-gap"}, x.words_ko || ""),
      ui.note(`페이퍼: ${fmt.kst(x.since_ms)}부터` + (x.live_since_ms != null ? ` · 실거래: ${fmt.kst(x.live_since_ms)}부터 (MEXC가 옮긴 때)` : ` · ${x.live_ko || ""}`)),
      ui.smallSample(Math.min(...x.sides.map((s) => (s.paper || {}).n || 0)), x.small_n || 20),
      ui.note(x.note_ko || ""));
  }
  function draw() {
    const d = st.d;
    if (!d) { put(head, motion.shimmer(1)); put(cards, motion.shimmer(3, true)); put(rec); put(imply); return; }
    const mo = d.month || {};
    put(head, h("b", null, `목표: 한 달 +${fmt.num(d.target * 100, 0)}% (×${fmt.num(d.target_mult, 0)})`),
      h("span", {class: "muted"}, " · 두 분이 정한 목표예요 (예측 아님)"),
      h("span", {class: "lbg-month"}, ` · ${mo.label || ""} 남은 날 ${fmt.num(mo.days_left, 1)}일 (평일 ${fmt.num(mo.weekdays_left, 1)}일)`),
      d.start && d.start.ms != null ? h("span", {class: "muted"}, ` · 규칙봇 15 시작 ${fmt.kst(d.start.ms)}`) : null,
      d.frozen ? h("span", {class: ["lbg-frozen", d.frozen.on ? "on" : ""], title: d.frozen.why_ko || ""}, ` · ${d.frozen.ko}`) : null);
    put(cards, (d.accts || []).map((a) => acctCard(a, d)));
    drawRec(d);
    drawH2h(d);
  }
  async function load() {
    let d;
    try { d = await ctx.api(GOAL_API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      ui.dim(body, !!st.d);
      throw e;
    }
    if (!ctx.alive()) return;
    st.okAt = serverNow();
    put(stateSlot);
    ui.dim(body, false);
    const sig = JSON.stringify({...d, now_ms: 0});
    if (st.d && sig === st.sig) return;
    st.d = d; st.sig = sig;
    draw();
  }
  draw();
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  return {el, set() {}};
}
