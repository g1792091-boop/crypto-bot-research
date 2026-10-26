// 실거래 › 봇별 › V3.9 투비트 (#/v39; owners 10/26 "추세판단봇 화면 따로, vwap 개선판 봇 화면 따로, 친구 30분 봇 화면 따로,
// v3.9 화면 따로"): the fifth executor, 투비트 ($50 of real money, docs/toobit-ko.md), and the paper account it follows, the
// rule bot's V3.9 1-hour account V39_ALL@1h, on one screen and nothing of the other bots. Read-only:
//   지금        running / 기록 멈춤 / 멈춤 / 못 읽음, or 아직 꺼져 있어요 with the guide's step to start it (until its database
//               is there); the real balance, its change since the first one, today's trades, the paper account's wallet
//               (모의 · 진짜 돈 아님)
//   계획        the owners' plan in words from the config's own numbers (증거금 40%, BTC 40배 · 나머지 30배, 손절 2.5 ATR, 계단
//               순ROE 20→17 · 25→22 · 30→27 …, 청산가보다 먼 손절이면 진입 안 함, 미국 지표 앞뒤 30분 진입 금지); the repo's
//               template while the server has no config, said so
//   포지션      the open live position with its ladder step, the lock, the best net ROE and the next step; the stop and its
//               ROE, the liquidation by the guard's estimate (어림); the paper account's own position next to it
//   거래        today's and the recent closed live trades, each with the paper trade it followed
//   페이퍼 vs 실거래  the paper account's entries since the executor's start: followed (with the live result) or missed and
//               why, in the executor's own words
//   잔고        the equity line since the first balance (deposits and withdrawals left out)
// Source: /api/v4/livebots/v39 (every 15 s), dash/more/livev39.py.
// HONESTY: a file that is not there = 꺼짐 / 수집 전, an unreadable one = 못 읽음 + why, never a zero; the paper money is never
// shown as real money; small samples say so.
import {h, put, ui, fmt, serverNow} from "../core/pb.js";
import {sourceState} from "./livebots-kit.js";

export const API = "/api/v4/livebots/v39";
const REFRESH_MS = 15 * 1000;
const FOLLOW_PAGE = 15;
const TRADES_PAGE = 10;
const SIDE = (x) => (Number(x) > 0 ? "롱" : "숏");
const ok = (x) => x != null && x !== "" && Number.isFinite(Number(x));
// status -> [pill, tone, orb class]
const STATUS = {running: ["켜짐", "good", "run"], halted: ["멈춤", "bad", "stop"], stopped: ["기록 멈춤", "bad", "stop"],
  off: ["꺼짐", "thin", "off"], error: ["못 읽음", "bad", "err"]};
// a paper entry's state -> [pill, tone]
const FOLLOW = {followed: ["따라 들어감", "good"], open: ["같이 들고 있음", "accent"], missed: ["안 들어감", "warn"],
  before: ["실행기 시작 전", "thin"], off: ["실행기 꺼짐", "thin"], waiting: ["기록 기다리는 중", "thin"]};

// ---------------------------------------------------------------- pure (node tests: tests/test_dash_livev39.py)
/** A small P&L with its sign, 3 decimals ($50 account: "+$0.026" / "−$0.130"); "모름" for unknown. */
export function pnlKo(x) {
  if (!ok(x)) return "모름";
  const v = Number(x);
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}$${fmt.num(Math.abs(v), 3)}`;
}
/** "+12.1%" / "−4.3%" of a ratio; "—" for unknown. */
export const pctKo = (x, d = 1) => (ok(x) ? fmt.pct(Number(x), d, true) : "—");
/** "17%" (no sign) of a ratio; "—" for unknown. */
export const rateKo = (x, d = 0) => (ok(x) ? fmt.pct(Number(x), d, false) : "—");
/** The status line: {pill, tone, cls, line, hint}. */
export function statusOf(s, now) {
  const x = s || {};
  const [pill, tone, cls] = STATUS[x.state] || ["모름", "thin", "err"];
  const seen = ok(x.seen_ms) ? `마지막 기록 ${fmt.kst(x.seen_ms)} (${fmt.dur(Math.max(0, Number(now) - Number(x.seen_ms)) / 1000)} 전)` : "";
  const line = x.state === "off" ? `${x.ko || "아직 꺼져 있어요"} · ${x.why_ko || ""}`.replace(/ · $/, "")
    : x.state === "error" ? (x.reason_ko || x.ko || "실행기 기록을 못 읽었어요")
      : [x.why_ko, seen, ok(x.since_ms) ? `처음 켬 ${fmt.kst(x.since_ms)}` : ""].filter(Boolean).join(" · ");
  const hint = x.state === "off" ? `켜는 순서: ${x.guide_ko || "docs/toobit-ko.md"}`
    : x.state === "stopped" || x.state === "error" ? `서버에서 systemctl status ${x.unit || "paperbot-executor-toobit"}` : "";
  return {pill, tone, cls, line, hint};
}
/** The ladder step of the open position in words: "계단 2단계 · 순ROE 22% 잠금" / "처음 손절 (계단 전)". */
export function stepKo(p) {
  if (!p) return "—";
  return Number(p.step) > 0 && ok(p.lock_roe) ? `계단 ${p.step}단계 · 순ROE ${rateKo(p.lock_roe)} 잠금` : "처음 손절 (계단 전)";
}
/** The next ladder step: "순ROE 25% (0.2150)에 닿으면 손절을 순ROE 22% (0.2140)로"; "다음 계단 계산 전" without one. */
export function nextKo(p) {
  const n = p && p.next;
  if (!n || !ok(n.at) || !ok(n.lock)) return "다음 계단은 실행기가 첫 1분봉을 읽은 뒤 보여요";
  return `순ROE ${rateKo(n.at)}${ok(n.price) ? ` (${fmt.price(n.price)})` : ""}에 닿으면 손절을 순ROE ${rateKo(n.lock)}${ok(n.lock_price) ? ` (${fmt.price(n.lock_price)})` : ""}로`;
}
/** A paper entry against the live one: {pill, tone, text}. */
export function followKo(r) {
  const [pill, tone] = FOLLOW[r.state] || ["모름", "thin"];
  if (r.state === "followed") {
    const l = r.live || {};
    return {pill, tone, text: `실거래 ${l.exit_ko || "청산"} ${pnlKo(l.pnl)}${ok(l.roe) ? ` (ROE ${pctKo(l.roe)})` : ""}${l.est ? " · 지갑 변화로 어림" : ""}`};
  }
  if (r.state === "missed") return {pill, tone, text: [r.why_ko, r.why_text && r.why_text !== r.why_ko ? r.why_text : null].filter(Boolean).join(" · ")};
  return {pill, tone, text: r.why_ko || ""};
}
/** A paper entry's own result: "페이퍼 잠금 익절 순ROE +21%" / "페이퍼 아직 열림". */
export function paperKo(r) {
  if (r.open) return "페이퍼 아직 열림";
  return `페이퍼 ${r.exit_ko || r.exit_reason || "청산"}${ok(r.roe) ? ` 순ROE ${pctKo(r.roe, 0)}` : ""}`;
}

// ---------------------------------------------------------------- the view
function tile(k, v, sub, cls, title) {
  return h("div", {class: ["l39-tile", cls || ""], role: "listitem", title}, h("span", {class: "l39-tk"}, k), h("b", {class: "l39-tv num"}, v),
    sub ? h("span", {class: "l39-ts"}, sub) : null);
}

/** v39View(ctx) -> {el, set()}: the screen (module comment), its own endpoint every 15 s. */
export function v39View(ctx) {
  const st = {d: null, okAt: 0, busy: false, followN: FOLLOW_PAGE, tradesN: TRADES_PAGE};
  const slot = h("div", {class: "lb-slot"});
  const orb = h("div", {class: "l39-orb", "aria-hidden": "true"}, h("i"));
  const name = h("h2", {class: "l39-name"}, "V3.9 투비트");
  const line = h("p", {class: "l39-sub"});
  const hint = h("p", {class: "l39-hint"});
  const chips = h("div", {class: "l39-chips"});
  const money = h("div", {class: "l39-money", role: "list", "aria-label": "잔고"});
  const offBox = h("div", {class: "l39-offbox"});
  const hero = h("section", {class: "l39-hero off", "aria-label": "지금"}, orb,
    h("div", {class: "l39-hmain"}, h("p", {class: "l39-kick"}, "진짜 돈 · 투비트 실행기 · 규칙봇 V3.9 1시간 페이퍼(V39_ALL@1h)를 따라가요"),
      name, line, hint, chips), money, offBox);
  const planBox = h("div", {class: "l39-plan"});
  const posBox = h("div", {class: "l39-pos"});
  const tradesBox = h("div", {class: "l39-trades"});
  const followHead = h("div", {class: "l39-chiprow"});
  const followBox = h("div", {class: "l39-follow"});
  const eqBox = h("div", {class: "l39-eq"});
  const eventsBox = h("div", {class: "l39-events"});
  const cards = h("div", {class: "l39-cards"},
    h("div", {class: "l39-two"},
      ui.card({title: "계획", sub: "두 분이 정한 대로 · 설정 파일의 숫자 그대로 (docs/toobit-ko.md)", cls: "l39-plancard"}, planBox),
      ui.card({title: "지금 포지션", sub: "실거래(투비트) · 계단은 자기 체결가 · 투비트 1분봉 · 투비트 비용으로 재요", cls: "l39-poscard"}, posBox)),
    ui.card({title: "페이퍼 V39 진입 vs 실거래", sub: "실행기가 켜진 뒤 페이퍼 진입마다 따라 들어갔나 · 안 들어갔으면 실행기가 남긴 이유 그대로", cls: "l39-fcard"},
      followHead, followBox),
    h("div", {class: "l39-two"},
      ui.card({title: "오늘 · 최근 실거래", sub: "닫힌 거래 · 한국 시간 · 손익은 투비트 체결 기록 (수수료 포함)", cls: "l39-tcard"}, tradesBox),
      ui.card({title: "잔고", sub: "실행기가 읽은 투비트 잔고 · 입출금은 빼고 셈", cls: "l39-eqcard"}, eqBox)),
    ui.card({title: "주의 · 긴급 기록", sub: "실행기 기록 그대로 · 최근 20개", cls: "l39-ecard"}, eventsBox));
  const main = h("div", {class: "l39-body"}, hero, cards);
  const el = h("div", {class: "l39 stack"}, slot, main,
    ui.note("보기만 하는 화면 · 15초마다 새로 읽어요 · 페이퍼(V39_ALL@1h)의 돈은 진짜 돈이 아니에요 · 실거래 손익은 투비트 체결 기록 (못 읽은 거래는 지갑 변화로 어림)"));

  function drawHero() {
    const d = st.d, s = d.status || {}, now = serverNow();
    const x = statusOf(s, now);
    hero.className = `l39-hero ${x.cls}`;
    put(name, "V3.9 투비트 ", ui.pill(x.pill, x.tone, `서버 서비스 ${s.unit || "paperbot-executor-toobit"}`));
    line.textContent = x.line;
    hint.textContent = x.hint;
    hint.hidden = !x.hint;
    const kill = d.kill_file;
    put(chips,
      s.mode_ko ? ui.pill(s.mode_ko, "warn") : null,
      kill && kill.present ? ui.pill("비상 정지 파일 있음 · 모든 실행기 새 진입 멈춤", "bad", kill.path) : null,
      s.state === "halted" && ok(s.halted_ms) ? ui.pill(`멈춘 시각 ${fmt.kst(s.halted_ms)}`, "bad") : null,
      ...(d.notes || []).map((n) => ui.pill(n, "warn")));
    const items = [];
    const e = d.equity || {}, td = d.today, rec = d.record;
    if (s.state === "off") {
      put(money);
      put(offBox, h("div", {class: "l39-off", role: "status"},
        h("div", {class: "l39-offhead"}, ui.pill("꺼짐", "thin"), h("b", null, "아직 꺼져 있어요")),
        h("p", null, `${s.why_ko || ""} · 켜는 순서는 ${s.guide_ko || "docs/toobit-ko.md"}에 있어요.`),
        h("p", null, "켜면 이 화면에 상태 · 잔고 · 포지션 · 계단 · 오늘 거래 · 페이퍼를 따라갔는지가 보여요. 그 전에는 숫자를 만들지 않아요."),
        h("p", {class: "l39-sub"}, `읽는 파일: ${((d.files || {}).config || {}).path || "—"} · ${((d.files || {}).db || {}).path || "—"}`)));
    } else {
      put(offBox, s.state === "error" ? sourceState({state: "error", reason_ko: s.reason_ko, reason: s.reason}, "실행기 기록") : null);
      if (e.state === "ok" && ok(e.now)) {
        items.push(tile("투비트 잔고 (실거래)", fmt.usd(e.now), `${ok(e.now_ms) ? `${fmt.kst(e.now_ms)} 기록` : "실행기 기록"}`, "real",
          "실행기가 투비트에서 읽어 기록한 마지막 잔고 (지금 값은 앱에서)"));
        items.push(tile("처음 잔고 대비", ok(e.change) ? pnlKo(e.change) : "—",
          `${ok(e.change_pct) ? pctKo(e.change_pct) : ""}${ok(e.base) ? ` · 기준 ${fmt.usd(e.base)}` : ""}`, ok(e.change) ? (Number(e.change) < 0 ? "down" : "up") : ""));
      } else items.push(tile("투비트 잔고 (실거래)", "수집 전", "아직 잔고 기록이 없어요", "na"));
      items.push(tile("오늘 (한국 시간)", td ? `${fmt.int(td.trades)}번` : "—",
        td && td.trades ? `${fmt.int(td.wins)}승 ${fmt.int(td.losses)}패 · ${pnlKo(td.pnl)}` : "오늘 닫힌 거래 없음"));
      items.push(tile("실거래 성적", rec && rec.trades ? `${fmt.int(rec.wins)}승 ${fmt.int(rec.losses)}패` : "아직 거래 없음",
        rec && rec.trades ? `승률 ${rateKo(rec.win_rate)} · ${pnlKo(rec.pnl)}${rec.trades < 20 ? " · 표본 적음" : ""}` : "첫 거래가 닫히면 채워져요", "rec"));
    }
    const pa = d.paper || {};
    if (pa.state === "ok") {
      items.push(tile("페이퍼 V39 지갑", fmt.usd(pa.wallet), `${ok(pa.initial) ? `시작 ${fmt.usd(pa.initial)} · ` : ""}모의 · 진짜 돈 아님`, "paper",
        `규칙봇 페이퍼 계좌 ${pa.account}`));
    } else items.push(tile("페이퍼 V39 지갑", pa.state === "error" ? "못 읽음" : "수집 전", pa.reason_ko || "", "na", pa.path));
    put(money, items);
  }
  function drawPlan() {
    const pl = st.d.plan || {};
    if (!(pl.lines || []).length) { put(planBox, h("p", {class: "l39-warn"}, pl.reason_ko || "계획을 읽지 못했어요")); return; }
    put(planBox,
      pl.source === "repo" ? h("p", {class: "l39-warn"}, pl.reason_ko || "저장소의 설정 원본으로 보여 줘요") : null,
      (pl.ladder || []).length ? h("div", {class: "l39-ladder", role: "list", "aria-label": "계단 익절"},
        pl.ladder.map((x, i) => h("span", {class: "l39-step", role: "listitem"}, h("small", null, `${i + 1}단계`),
          h("b", {class: "num"}, `${rateKo(x.at)} → ${rateKo(x.lock)}`))), h("span", {class: "l39-step more", "aria-hidden": "true"}, "…")) : null,
      h("dl", {class: "l39-kv"}, pl.lines.flatMap((x) => [h("dt", null, x.k), h("dd", null, x.ko)])),
      pl.source === "server" ? h("p", {class: "l39-sub"}, `설정 파일: ${pl.path}`) : null);
  }
  function drawPos() {
    const d = st.d, s = d.status || {}, p = d.position, pa = d.paper || {};
    const paperLine = pa.state === "ok" ? (pa.position
      ? h("p", {class: "l39-sub l39-pline"}, h("b", null, "페이퍼 V39: "),
        `${pa.position.coin} ${SIDE(pa.position.side)} ${fmt.lev(pa.position.leverage)} · 진입 ${fmt.price(pa.position.entry)} · ${fmt.kst(pa.position.entry_time)}`
        + ` · ${pa.position.locked ? `잠금 순ROE ${rateKo(pa.position.lock_roe)}` : `손절 ${fmt.price(pa.position.stop)}`} (모의)`)
      : h("p", {class: "l39-sub l39-pline"}, h("b", null, "페이퍼 V39: "), "포지션 없음 (모의)"))
      : h("p", {class: "l39-sub l39-pline"}, h("b", null, "페이퍼 V39: "), pa.reason_ko || "기록 수집 전");
    if (s.state === "off") { put(posBox, h("div", {class: "l39-empty"}, h("b", null, "실행기 꺼짐"), h("p", null, "켜지면 투비트 포지션과 계단이 여기 보여요.")), paperLine); return; }
    if (s.state === "error") { put(posBox, sourceState({state: "error", reason_ko: s.reason_ko, reason: s.reason}, "실행기 기록"), paperLine); return; }
    if (!p) {
      put(posBox, h("div", {class: "l39-empty"}, h("b", null, "포지션 없음"),
        h("p", null, "페이퍼 V39가 진입하면 따라 들어가요 (한 번에 1포지션 · 시장가 · 격리). 손절이 강제청산보다 멀거나 미국 경제 발표 앞뒤 30분이면 들어가지 않아요.")), paperLine);
      return;
    }
    put(posBox,
      h("div", {class: "l39-phead"}, h("span", {class: ["side", Number(p.side) > 0 ? "long" : "short"]}, SIDE(p.side)),
        h("b", {class: "l39-pcoin"}, p.coin), h("span", {class: "l39-sub"}, ` ${fmt.lev(p.leverage)} 격리`),
        p.status === "entering" ? ui.pill("진입 확인 중", "warn") : null, ui.pill(stepKo(p), Number(p.step) > 0 ? "good" : "thin")),
      h("dl", {class: "l39-kv"},
        h("dt", null, "진입"), h("dd", {class: "num"}, `${fmt.price(p.entry)} · ${fmt.kst(p.entry_ms)}`,
          ok(p.paper_entry) ? h("small", {class: "l39-sub"}, ` · 페이퍼 ${fmt.price(p.paper_entry)}`) : null),
        h("dt", null, "크기"), h("dd", {class: "num"}, `${fmt.num(p.qty, 4)}개 · ≈ ${fmt.usd(p.notional)} (증거금 ${fmt.usd(p.margin)})`),
        h("dt", null, p.locked ? "잠금선" : "손절선"), h("dd", {class: ["num", p.locked ? "up" : ""]}, fmt.price(p.stop),
          ok(p.stop_roe) ? ` · ROE ${pctKo(p.stop_roe, 0)}` : "", ok(p.stop_move) ? h("small", {class: "l39-sub"}, ` (진입가에서 ${pctKo(p.stop_move, 2)}, 수수료 전)`) : null,
          p.stop_order ? null : h("small", {class: "l39-warn-t"}, " · 손절 주문 번호 기록 없음 (앱에서 확인)")),
        h("dt", null, "계단"), h("dd", null, stepKo(p), ok(p.best_roe) ? h("small", {class: "l39-sub"}, ` · 가장 좋았던 순ROE ${pctKo(p.best_roe, 0)}`) : null),
        h("dt", null, "다음 계단"), h("dd", {class: "num"}, nextKo(p)),
        h("dt", null, "강제청산 (어림)"), h("dd", {class: "num"}, ok(p.liq_price) ? `${fmt.price(p.liq_price)} · 진입가에서 약 ${rateKo(p.liq_frac, 2)}` : "—",
          h("small", {class: "l39-sub"}, ` (1/${p.leverage} − 유지증거금률 ${rateKo(p.liq_mmr, 1)}, 실제는 앱에서)`))),
      p.staying ? h("p", {class: "l39-sub"}, "페이퍼는 가격으로 닫았고 실거래는 자기 손절 · 계단으로 계속 가요") : null,
      paperLine);
  }
  function drawTrades() {
    const d = st.d, s = d.status || {}, rows = d.trades || [];
    if (s.state === "off") { put(tradesBox, ui.empty("실행기가 아직 꺼져 있어요 · 켜면 닫힌 거래가 여기 쌓여요")); return; }
    if (!rows.length) { put(tradesBox, ui.empty(s.state === "error" ? "실행기 기록을 못 읽었어요" : "아직 닫힌 실거래가 없어요")); return; }
    const t0 = d.today && d.today.from_ms;
    const list = h("ul", {class: "l39-list l39-tlist"}, rows.slice(0, st.tradesN).map((t) => h("li", {class: ["l39-trow", ok(t0) && t.exit_ms >= t0 ? "today" : ""]},
      h("span", {class: "num l39-t"}, fmt.kst(t.exit_ms)),
      h("b", null, `${t.coin} ${SIDE(t.side)} ${fmt.lev(t.leverage)}`), ui.pill(t.exit_ko || "청산", t.exit_reason === "SL" ? "bad" : t.exit_reason === "LOCK" ? "good" : "thin"),
      h("b", {class: ["num", "l39-tpnl", fmt.tone(t.pnl)]}, pnlKo(t.pnl)),
      h("small", {class: "l39-sub"}, [ok(t.roe) ? `ROE ${pctKo(t.roe)}` : null, t.est ? "지갑 변화로 어림" : null,
        t.paper ? `페이퍼 ${t.paper.exit_ko || ""}${ok(t.paper.roe) ? ` 순ROE ${pctKo(t.paper.roe, 0)}` : ""}` : "페이퍼 짝 없음"].filter(Boolean).join(" · ")))));
    const more = rows.length > st.tradesN ? h("button", {class: "btn-line l39-more", type: "button", onclick: () => { st.tradesN += TRADES_PAGE; drawTrades(); }},
      `더 보기 (${fmt.int(rows.length - st.tradesN)}개 남음)`) : null;
    put(tradesBox, list, more);
  }
  function drawFollow() {
    const d = st.d, f = d.follow || {}, rows = f.rows || [], c = f.counts || {}, pa = d.paper || {};
    put(followHead,
      ...[["followed", "따라 들어감"], ["open", "같이 들고 있음"], ["missed", "안 들어감"], ["before", "실행기 시작 전"], ["off", "실행기 꺼짐"]]
        .filter(([k]) => c[k]).map(([k, ko]) => ui.pill(`${ko} ${fmt.int(c[k])}`, (FOLLOW[k] || [])[1] || "thin")),
      ...(f.why || []).map((w) => ui.pill(`${w.ko || "이유 기록 없음"} ${fmt.int(w.n)}`, "warn")));
    if (pa.state !== "ok") { put(followBox, sourceState(pa, `페이퍼 ${pa.account || "V39_ALL@1h"}`)); return; }
    if (!rows.length) { put(followBox, ui.empty("페이퍼 V39의 거래가 아직 없어요")); return; }
    const list = h("ul", {class: "l39-list l39-flist"}, rows.slice(0, st.followN).map((r) => {
      const k = followKo(r);
      return h("li", {class: ["l39-frow", r.state]},
        h("span", {class: "num l39-t"}, fmt.kst(r.entry_ms)), h("b", null, `${r.coin} ${SIDE(r.side)}`), ui.pill(k.pill, k.tone),
        h("small", {class: "l39-sub"}, [paperKo(r), k.text].filter(Boolean).join(" · ")));
    }));
    const left = rows.length - st.followN + (f.more || 0);
    const more = rows.length > st.followN ? h("button", {class: "btn-line l39-more", type: "button", onclick: () => { st.followN += FOLLOW_PAGE; drawFollow(); }},
      `더 보기 (${fmt.int(left)}개 남음)`) : null;
    put(followBox, list, more, f.more ? h("p", {class: "l39-sub"}, `그 전 ${fmt.int(f.more)}개는 이 화면에 안 보여요`) : null);
  }
  function drawEquity() {
    const d = st.d, e = d.equity || {}, s = d.status || {};
    if (s.state === "off") { put(eqBox, ui.empty("실행기가 아직 꺼져 있어요 · 켜면 잔고 줄이 그려져요")); return; }
    if (e.state !== "ok") { put(eqBox, ui.empty("잔고 기록을 못 읽었어요")); return; }
    const vals = (e.curve || []).map((x) => Number(x[1]));
    put(eqBox,
      vals.length >= 2 ? h("div", {class: "l39-spark"}, ui.miniSpark(vals, {fluid: true, h: 64, base: ok(e.base) ? Number(e.base) : null, label: "투비트 잔고 흐름"}))
        : h("p", {class: "l39-sub"}, "잔고 기록이 둘 이상 쌓이면 줄이 그려져요"),
      h("dl", {class: "l39-kv"},
        h("dt", null, "처음"), h("dd", {class: "num"}, ok(e.first) ? `${fmt.usd(e.first)} · ${fmt.kst(e.first_ms)}` : "—"),
        h("dt", null, "지금"), h("dd", {class: "num"}, ok(e.now) ? `${fmt.usd(e.now)}${ok(e.now_ms) ? ` · ${fmt.kst(e.now_ms)}` : ""}` : "—"),
        h("dt", null, "변화"), h("dd", {class: ["num", fmt.tone(e.change)]}, ok(e.change) ? `${pnlKo(e.change)} (${pctKo(e.change_pct)})` : "—"),
        ok(e.budget) ? h("dt", null, "정한 금액") : null, ok(e.budget) ? h("dd", {class: "num"}, fmt.usd(e.budget)) : null));
  }
  function drawEvents() {
    const d = st.d, xs = d.events || [];
    if ((d.status || {}).state === "off") { put(eventsBox, ui.empty("실행기가 아직 꺼져 있어요")); return; }
    put(eventsBox, xs.length ? h("ul", {class: "l39-list l39-elist"}, xs.map((x) => h("li", {class: ["l39-erow", x.level === "CRITICAL" ? "crit" : ""]},
      h("span", {class: "num l39-t"}, fmt.kst(x.ts)), ui.pill(x.level_ko || x.level, x.level === "CRITICAL" ? "bad" : "warn"),
      h("b", null, x.kind_ko || x.kind), h("small", {class: "l39-sub"}, x.text || ""))))
      : ui.empty("주의 · 긴급 기록이 없어요"));
  }
  function draw() {
    if (!st.d) return;
    drawHero(); drawPlan(); drawPos(); drawFollow(); drawTrades(); drawEquity(); drawEvents();
  }

  async function load() {
    if (st.busy) return;
    st.busy = true;
    let d;
    try { d = await ctx.api(API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      if (st.d) { put(slot, ui.staleNote(e, st.okAt, () => load().catch(() => {}))); ui.dim(main, true); }
      else put(slot, ui.errorBox(e, () => load()));
      throw e;
    } finally { st.busy = false; }
    if (!ctx.alive()) return;
    put(slot);
    ui.dim(main, false);
    st.d = d; st.okAt = Date.now();
    draw();
  }
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  return {el, set() {}};
}
