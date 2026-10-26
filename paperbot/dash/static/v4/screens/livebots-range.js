// 실거래 › 봇별 › 레인지 봇 (#/rangebot; owners 10/26 "레인지봇을 추세 봇 woo x pro 거래소로 … 원래 있던 추세봇 woo x pro 는
// 없애고", docs/range-bot-ko.md): the 레인지 봇 paper bot (COMBO@mix in range.db and its coin-flip twin COMBOFLIP@mix) and only
// the executors that follow it (now WOO X Pro), on one screen and nothing of the other bots. Read-only:
//   지금        켜짐 / 기록 멈춤 / 멈춤 / 못 읽음 / 첫 기록 전, or 아직 꺼져 있어요 with the guide's steps (until its database is
//               there); the paper wallet against its start (모의 · 진짜 돈 아님), today's trades, each follower's real balance
//               and its change since it moved to this bot
//   계획        the plan in words from the config's own numbers (F7_RF_TRIPLE 1시간 커스텀값, 0.2 ATR 되돌림 최대 60분, 코인 ·
//               BTC 1시간 슈퍼트렌드(10, 3), 강제청산 여유, 고정 익절 순ROE +10%, 손절 순ROE −50%, 증거금 40%, 코인별 배수)
//   포지션      the paper's open position with its stop and take-profit prices, the pullback it entered on; each follower's
//               own position (its exchange stop, its own take-profit net ROE)
//   되돌림 · 추세 the pullback the bot waits for now (level, until when) and every coin's 1h supertrend side
//   거래        the recent closed paper trades with each follower's part side by side; the paper entries against each
//               follower (followed, or the executor's own reason); real vs the coin-flip twin; the balance lines; the
//               signals of the last 24 hours by what became of each; the warnings
// Source: /api/v4/livebots/range (every 15 s), dash/more/liverange.py.
// HONESTY: a file that is not there = 꺼짐 / 수집 전, an unreadable one = 못 읽음 + why, never a zero; the paper money is never
// shown as real money; small samples say so.
import {h, put, ui, fmt, serverNow} from "../core/pb.js";
import {sourceState} from "./livebots-kit.js";

export const API = "/api/v4/livebots/range";
const REFRESH_MS = 15 * 1000;
const PAGE = 10;
const SIDE = (x) => (Number(x) > 0 ? "롱" : "숏");
const ok = (x) => x != null && x !== "" && Number.isFinite(Number(x));
// status -> [pill, tone, hero class]
const STATUS = {running: ["켜짐", "good", "run"], halted: ["멈춤", "bad", "stop"], stopped: ["기록 멈춤", "bad", "stop"],
  off: ["꺼짐", "thin", "off"], error: ["못 읽음", "bad", "err"], missing: ["수집 전", "thin", "off"], other: ["레인지 봇 아님", "warn", "err"]};
// a follower's part of a paper trade -> [pill, tone]
const CELL = {followed: ["따라 들어감", "good"], open: ["같이 들고 있음", "accent"], missed: ["안 들어감", "warn"],
  before: ["옮기기 전", "thin"], other: ["다른 봇을 따라감", "thin"], waiting: ["기록 기다리는 중", "thin"], unknown: ["못 읽음", "bad"]};

// ---------------------------------------------------------------- pure (node tests: tests/test_dash_live_range.py)
/** Money with its sign ("+$3.40" / "−$16.40"); "모름" for unknown. */
export function pnlKo(x, d = 2) {
  if (!ok(x)) return "모름";
  const v = Number(x);
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}$${fmt.num(Math.abs(v), d)}`;
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
    : x.state === "error" ? (x.reason_ko || x.ko || "레인지 봇 기록을 못 읽었어요")
      : x.state === "missing" || x.state === "other" ? (x.why_ko || x.ko || "")
        : [x.why_ko, seen, ok(x.since_ms) ? `처음 켬 ${fmt.kst(x.since_ms)}` : ""].filter(Boolean).join(" · ");
  const hint = x.state === "off" || x.state === "missing" ? `켜는 순서: ${x.guide_ko || "docs/range-bot-ko.md"}`
    : x.state === "stopped" || x.state === "error" ? `서버에서 systemctl status ${x.unit || "paperbot-combo-range"}` : "";
  return {pill, tone, cls, line, hint};
}
/** A follower's part of a paper trade: {pill, tone, text}. */
export function cellKo(c) {
  const x = c || {};
  const [pill, tone] = CELL[x.state] || ["모름", "thin"];
  if (x.state === "followed") {
    return {pill, tone, text: `${x.name_ko || "실거래"} ${x.exit_ko || "청산"} ${pnlKo(x.pnl)}${ok(x.roe) ? ` (ROE ${pctKo(x.roe)})` : ""}${x.est ? " · 지갑 변화로 어림" : ""}`};
  }
  if (x.state === "missed") return {pill, tone, text: [x.why_ko, x.why_text && x.why_text !== x.why_ko ? x.why_text : null].filter(Boolean).join(" · ")};
  return {pill, tone, text: x.why_ko || x.reason_ko || ""};
}
/** A paper trade's own result: "페이퍼 익절 순ROE +12%" / "페이퍼 아직 열림". */
export function paperKo(r) {
  if (r.open) return "페이퍼 아직 열림";
  return `페이퍼 ${r.paper_ko || r.reason_ko || "청산"}${ok(r.paper_roe != null ? r.paper_roe : r.roe) ? ` 순ROE ${pctKo(r.paper_roe != null ? r.paper_roe : r.roe, 0)}` : ""}`;
}
/** The pullback wait in words: "SOL 롱 · 149.6에 닿으면 다음 5분봉 시가에 진입 · 21:00까지 (40분 남음)"; null without one. */
export function waitKo(w, now) {
  if (!w) return null;
  const left = ok(w.until) ? Math.max(0, Number(w.until) - Number(now)) : null;
  const how = w.hit ? `${fmt.kst(w.hit)}에 닿음 · 그 5분봉이 끝나면 다음 5분봉 시가에 진입` : `${ok(w.level) ? fmt.price(w.level) : "—"}에 닿으면 다음 5분봉 시가에 진입`;
  return `${w.coin || ""} ${SIDE(w.side)} · ${how}${ok(w.until) ? ` · ${fmt.kst(w.until)}까지${left != null && !w.hit ? ` (${fmt.dur(left / 1000)} 남음)` : ""}` : ""}`;
}
/** A coin's 1h supertrend side: {text, tone}. */
export function stKo(c) {
  if (!c || c.side == null) return {text: `${(c && c.coin) || ""} 못 읽음`, tone: "bad"};
  return {text: `${c.coin} ${c.ko || (Number(c.side) > 0 ? "상승" : "하락")}`, tone: Number(c.side) > 0 ? "good" : Number(c.side) < 0 ? "bad" : "thin"};
}

// ---------------------------------------------------------------- the view
function tile(k, v, sub, cls, title) {
  return h("div", {class: ["lrb-tile", cls || ""], role: "listitem", title}, h("span", {class: "lrb-tk"}, k), h("b", {class: "lrb-tv num"}, v),
    sub ? h("span", {class: "lrb-ts"}, sub) : null);
}

/** rangeView(ctx) -> {el, set()}: the screen (module comment), its own endpoint every 15 s. */
export function rangeView(ctx) {
  const st = {d: null, okAt: 0, busy: false, tradesN: PAGE, followN: PAGE * 2, sigN: PAGE * 2};
  const slot = h("div", {class: "lb-slot"});
  const orb = h("div", {class: "lrb-orb", "aria-hidden": "true"}, h("i"));
  const name = h("h2", {class: "lrb-name"}, "레인지 봇");
  const line = h("p", {class: "lrb-sub"});
  const hint = h("p", {class: "lrb-hint"});
  const chips = h("div", {class: "lrb-chips"});
  const money = h("div", {class: "lrb-money", role: "list", "aria-label": "지갑과 잔고"});
  const offBox = h("div", {class: "lrb-offbox"});
  const kick = h("p", {class: "lrb-kick"}, "레인지 봇 페이퍼(연습)와 그 봇을 따라가는 실행기(진짜 돈)");
  const hero = h("section", {class: "lrb-hero off", "aria-label": "지금"}, orb, h("div", {class: "lrb-hmain"}, kick, name, line, hint, chips), money, offBox);
  const planBox = h("div", {class: "lrb-plan"});
  const posBox = h("div", {class: "lrb-pos"});
  const waitBox = h("div", {class: "lrb-wait"});
  const tradesBox = h("div", {class: "lrb-trades"});
  const followBox = h("div", {class: "lrb-follow"});
  const flipBox = h("div", {class: "lrb-flip"});
  const eqBox = h("div", {class: "lrb-eq"});
  const sigBox = h("div", {class: "lrb-sigs"});
  const warnBox = h("div", {class: "lrb-warns"});
  const cards = h("div", {class: "lrb-cards"},
    h("div", {class: "lrb-two"},
      ui.card({title: "계획", sub: "두 분이 정한 대로 · 설정의 숫자 그대로 (docs/range-bot-ko.md)", cls: "lrb-plancard"}, planBox),
      ui.card({title: "지금 포지션", sub: "페이퍼(연습)의 손절 · 익절 가격 · 따라가는 실행기는 자기 체결가로 손절 · 익절", cls: "lrb-poscard"}, posBox)),
    ui.card({title: "되돌림 기다림 · 1시간 슈퍼트렌드", sub: "봇이 지금 기다리는 되돌림과 코인마다 마지막 1시간봉 슈퍼트렌드 (봇 기록 그대로)", cls: "lrb-waitcard"}, waitBox),
    ui.card({title: "최근 거래 · 페이퍼 vs 실거래", sub: "닫힌 페이퍼 거래와 따라가는 실행기의 같은 거래를 나란히 · 한국 시간", cls: "lrb-tcard"}, tradesBox),
    ui.card({title: "페이퍼 진입 vs 실거래", sub: "실행기가 이 봇으로 옮긴 뒤 페이퍼 진입마다 따라 들어갔나 · 안 들어갔으면 실행기가 남긴 이유 그대로", cls: "lrb-fcard"}, followBox),
    h("div", {class: "lrb-two"},
      ui.card({title: "진짜 방향 vs 동전 쌍둥이", sub: "같은 때 들어가고 방향만 동전으로 던진 쌍둥이 계좌와 견줘요 (둘 다 모의)", cls: "lrb-flipcard"}, flipBox),
      ui.card({title: "잔고", sub: "페이퍼 지갑(모의)과 실행기 잔고(진짜 돈) · 입출금은 빼고 셈", cls: "lrb-eqcard"}, eqBox)),
    ui.card({title: "최근 24시간 신호", sub: "신호마다 어떻게 됐는지 · 봇이 남긴 이유 그대로", cls: "lrb-sigcard"}, sigBox),
    ui.card({title: "주의 · 긴급 기록", sub: "페이퍼 봇과 따라가는 실행기의 기록 그대로", cls: "lrb-warncard"}, warnBox));
  const main = h("div", {class: "lrb-body"}, hero, cards);
  const el = h("div", {class: "lrb stack"}, slot, main,
    ui.note("보기만 하는 화면 · 15초마다 새로 읽어요 · 페이퍼(COMBO@mix · COMBOFLIP@mix)의 돈은 진짜 돈이 아니에요 · 실거래 손익은 거래소 체결 기록 (못 읽은 거래는 지갑 변화로 어림)"));

  const followers = () => (st.d && st.d.followers) || [];
  function drawHero() {
    const d = st.d, s = d.status || {}, now = serverNow();
    const x = statusOf(s, now);
    hero.className = `lrb-hero ${x.cls}`;
    put(name, "레인지 봇 ", ui.pill(x.pill, x.tone, `서버 서비스 ${s.unit || "paperbot-combo-range"}`));
    const fs = followers().map((f) => f.name_ko);
    kick.textContent = `레인지 봇 페이퍼(연습) · ${fs.length ? `따라가는 실행기: ${fs.join(" · ")} (진짜 돈)` : "따라가는 실행기 없음 (페이퍼만)"}`;
    line.textContent = x.line;
    hint.textContent = x.hint;
    hint.hidden = !x.hint;
    put(chips, ...followers().flatMap((f) => (f.notes || []).map((n) => ui.pill(n, "warn"))),
      d.plan && d.plan.source && d.plan.source !== "db" ? ui.pill(d.plan.source === "server" ? "계획: 서버 설정 파일" : "계획: 저장소 설정 원본", "thin", d.plan.reason_ko || "") : null);
    if (s.state === "off") {
      put(money);
      put(offBox, h("div", {class: "lrb-off", role: "status"},
        h("div", {class: "lrb-offhead"}, ui.pill("꺼짐", "thin"), h("b", null, "아직 꺼져 있어요")),
        h("p", null, `${s.why_ko || ""} · 켜는 순서는 ${s.guide_ko || "docs/range-bot-ko.md"}에 있어요.`),
        (s.steps || []).length ? h("ol", {class: "lrb-steps"}, s.steps.map((c) => h("li", null, h("code", null, c)))) : null,
        h("p", null, "켜면 이 화면에 상태 · 지갑 · 포지션 · 되돌림 · 오늘 거래 · 실행기가 따라갔는지가 보여요. 그 전에는 숫자를 만들지 않아요."),
        h("p", {class: "lrb-sub"}, `읽는 파일: ${((d.files || {}).db || {}).path || "—"}`)));
      return;
    }
    put(offBox, s.state === "error" ? sourceState({state: "error", reason_ko: s.reason_ko, reason: s.reason}, "레인지 봇 기록") : null);
    const items = [];
    const w = d.wallet;
    if (w && w.state === "ok") {
      items.push(tile("페이퍼 지갑 (모의)", fmt.usd(w.wallet), `${ok(w.initial) ? `시작 ${fmt.usd(w.initial)} · ` : ""}${ok(w.change_pct) ? pctKo(w.change_pct) : ""} · 진짜 돈 아님`,
        "paper", "레인지 봇 페이퍼 계좌 COMBO@mix"));
      const r = w.record || {};
      items.push(tile("페이퍼 성적", r.trades ? `${fmt.int(r.wins)}승 ${fmt.int(r.losses)}패` : "아직 거래 없음",
        r.trades ? `승률 ${rateKo(r.win_rate)} · 순ROE 합 ${pctKo(w.roe_sum, 0)}${r.trades < 20 ? " · 표본 적음" : ""}` : "첫 거래가 닫히면 채워져요", "paper"));
    } else items.push(tile("페이퍼 지갑 (모의)", s.state === "error" ? "못 읽음" : "수집 전", (w && w.reason_ko) || "", "na"));
    const td = d.today;
    items.push(tile("오늘 페이퍼 (한국 시간)", td ? `${fmt.int(td.trades)}번` : "—",
      td && td.trades ? `${fmt.int(td.wins)}승 ${fmt.int(td.losses)}패 · ${fmt.money(td.pnl, true)} USDT (모의)` : "오늘 닫힌 거래 없음", "paper"));
    for (const f of followers()) {
      if (f.state !== "ok") { items.push(tile(`${f.name_ko} 잔고 (실거래)`, f.state === "error" ? "못 읽음" : "수집 전", f.reason_ko || "", "na")); continue; }
      items.push(tile(`${f.name_ko} 잔고 (실거래)`, ok(f.balance) ? fmt.usd(f.balance) : "—",
        `${ok(f.change) ? `${pnlKo(f.change)} (${pctKo(f.change_pct)})` : "변화 모름"}${ok(f.since_ms) ? ` · ${fmt.kst(f.since_ms)} 옮긴 뒤` : ""} · ${f.run_ko || ""}`,
        `real ${ok(f.change) ? (Number(f.change) < 0 ? "down" : "up") : ""}`, "실행기가 거래소에서 읽어 기록한 마지막 잔고 (지금 값은 앱에서)"));
      const ft = f.today;
      items.push(tile(`오늘 ${f.name_ko} (실거래)`, ft ? `${fmt.int(ft.trades)}번` : "—",
        ft && ft.trades ? `${fmt.int(ft.wins)}승 ${fmt.int(ft.losses)}패 · ${pnlKo(ft.pnl)}` : "오늘 닫힌 실거래 없음", "real"));
    }
    put(money, items);
  }
  function drawPlan() {
    const pl = st.d.plan || {};
    if (!(pl.lines || []).length) { put(planBox, h("p", {class: "lrb-warn"}, pl.reason_ko || "계획을 읽지 못했어요")); return; }
    put(planBox,
      pl.source !== "db" ? h("p", {class: "lrb-warn"}, pl.reason_ko || "봇 기록 대신 설정 파일로 보여 줘요") : null,
      h("dl", {class: "lrb-kv"}, pl.lines.flatMap((x) => [h("dt", null, x.k), h("dd", null, x.ko)])),
      h("p", {class: "lrb-sub"}, pl.source === "db" ? `봇이 지금 쓰는 설정 (봇 DB의 시작 기록${ok(pl.since_ms) ? `, ${fmt.kst(pl.since_ms)}` : ""})` : `설정 파일: ${pl.path || "—"}`));
  }
  function drawPos() {
    const d = st.d, s = d.status || {}, p = d.position;
    if (s.state === "off" || s.state === "missing") { put(posBox, h("div", {class: "lrb-empty"}, h("b", null, "기록 없음"), h("p", null, "봇이 켜지면 포지션이 여기 보여요."))); return; }
    if (s.state === "error") { put(posBox, sourceState({state: "error", reason_ko: s.reason_ko, reason: s.reason}, "레인지 봇 기록")); return; }
    const lives = followers().map((f) => {
      const q = f.position;
      if (f.state !== "ok") return h("p", {class: "lrb-sub lrb-pline"}, h("b", null, `${f.name_ko}: `), f.reason_ko || "기록 못 읽음");
      if (!q) return h("p", {class: "lrb-sub lrb-pline"}, h("b", null, `${f.name_ko}: `), "포지션 없음 (실거래)");
      return h("p", {class: "lrb-sub lrb-pline"}, h("b", null, `${f.name_ko}: `),
        `${q.coin} ${SIDE(q.side)} ${fmt.lev(q.leverage)} · 진입 ${fmt.price(q.entry)}${ok(q.paper_entry) ? ` (페이퍼 ${fmt.price(q.paper_entry)})` : ""} · 손절 ${fmt.price(q.stop)}`
        + `${ok(q.tp_roe) ? ` · 익절 순ROE +${rateKo(q.tp_roe)} (자기 체결가 기준)` : ""}${q.stop_order ? "" : " · 손절 주문 번호 기록 없음 (앱에서 확인)"} (진짜 돈)`);
    });
    if (!p) {
      put(posBox, h("div", {class: "lrb-empty"}, h("b", null, "페이퍼 포지션 없음"),
        h("p", null, d.wait ? "되돌림을 기다리는 중이에요 (아래 칸)." : "다음 1시간봉 신호와 되돌림을 기다려요. 한 번에 한 신호 · 포지션 하나예요.")), ...lives);
      return;
    }
    const rg = p.range || {};
    put(posBox,
      h("div", {class: "lrb-phead"}, h("span", {class: ["side", Number(p.side) > 0 ? "long" : "short"]}, SIDE(p.side)),
        h("b", {class: "lrb-pcoin"}, p.coin), h("span", {class: "lrb-sub"}, ` ${fmt.lev(p.leverage)} · 페이퍼(모의)`),
        ok(p.roe) ? ui.pill(`순ROE ${pctKo(p.roe)}`, Number(p.roe) >= 0 ? "good" : "bad", "마지막 마크 가격으로 계산 (수수료 포함)") : null),
      h("dl", {class: "lrb-kv"},
        h("dt", null, "진입"), h("dd", {class: "num"}, `${fmt.price(p.entry)} · ${fmt.kst(p.entry_time)}`),
        h("dt", null, "익절"), h("dd", {class: "num up"}, ok(p.tp) ? `${fmt.price(p.tp)} (진입가에서 ${pctKo(p.tp_move, 2)})` : "—"),
        h("dt", null, "손절"), h("dd", {class: "num down"}, ok(p.stop) ? `${fmt.price(p.stop)} (진입가에서 ${pctKo(p.stop_move, 2)})` : "—"),
        h("dt", null, "강제청산"), h("dd", {class: "num"}, ok(p.liq) ? fmt.price(p.liq) : "기록 없음"),
        h("dt", null, "지금 가격"), h("dd", {class: "num"}, ok(p.mark) ? `${fmt.price(p.mark)} (마지막 마크)` : "—"),
        h("dt", null, "되돌림"), h("dd", null, ok(rg.level) ? `종가 ${fmt.price(rg.close)} → ${fmt.num(rg.k, 1)} ATR ${Number(p.side) > 0 ? "아래" : "위"} ${fmt.price(rg.level)}${ok(rg.touch) ? ` · ${fmt.kst(rg.touch)} 닿음` : ""}` : "기록 없음")),
      ...lives);
  }
  function drawWait() {
    const d = st.d, s = d.status || {}, now = serverNow();
    if (s.state === "off" || s.state === "missing" || s.state === "error") { put(waitBox, ui.empty(s.state === "error" ? "레인지 봇 기록을 못 읽었어요" : "봇이 켜지면 보여요")); return; }
    const w = d.wait, t = d.supertrend;
    put(waitBox,
      w ? h("div", {class: "lrb-wline", role: "status"}, ui.pill("되돌림 기다림", "accent"), h("b", null, waitKo(w, now)),
        h("small", {class: "lrb-sub"}, `신호 ${fmt.kst(w.t0)} 종가 ${fmt.price(w.close)} · ATR ${ok(w.atr) ? fmt.price(w.atr) : "—"} · 안 오면 그 신호는 버려요`))
        : h("p", {class: "lrb-sub"}, d.position ? "포지션을 들고 있어 새 신호를 받지 않아요 (한 신호씩)" : "지금 기다리는 되돌림이 없어요"),
      t ? h("div", {class: "lrb-chiprow", role: "list", "aria-label": "1시간 슈퍼트렌드"}, h("span", {class: "lrb-sub"}, "1시간 슈퍼트렌드"),
        ...(t.coins || []).map((c) => { const k = stKo(c); return ui.pill(k.text, k.tone, c.error_ko || ""); }))
        : h("p", {class: "lrb-sub"}, "슈퍼트렌드 기록이 아직 없어요 (봇이 1분마다 남겨요)"),
      t && t.busy_ko ? h("p", {class: "lrb-sub"}, `봇: ${t.busy_ko}`) : null,
      t && ok(t.at) ? h("p", {class: "lrb-sub"}, `${fmt.kst(t.at)} 기록${ok(t.st_at) ? ` · ${fmt.kst(t.st_at)}에 닫힌 1시간봉` : ""}`) : null);
  }
  function drawTrades() {
    const d = st.d, rows = d.trades || [];
    if (!rows.length) { put(tradesBox, ui.empty((d.status || {}).state === "running" || (d.status || {}).state === "stopped" ? "아직 닫힌 페이퍼 거래가 없어요" : "봇이 켜지면 거래가 여기 쌓여요")); return; }
    const t0 = d.today && d.today.from_ms;
    const list = h("ul", {class: "lrb-list"}, rows.slice(0, st.tradesN).map((t) => h("li", {class: ["lrb-trow", ok(t0) && t.exit_time >= t0 ? "today" : ""]},
      h("span", {class: "num lrb-t"}, fmt.kst(t.exit_time)),
      h("b", null, `${t.coin} ${SIDE(t.side)} ${fmt.lev(t.leverage)}`), ui.pill(`페이퍼 ${t.reason_ko || "청산"}`, t.exit_reason === "SL" ? "bad" : t.win ? "good" : "thin"),
      h("b", {class: ["num", "lrb-tpnl", Number(t.roe) >= 0 ? "up" : "down"]}, `순ROE ${pctKo(t.roe, 0)}`),
      h("div", {class: "lrb-cells"}, (t.live || []).length ? t.live.map((c) => { const k = cellKo(c); return h("span", {class: "lrb-cell"}, ui.pill(`${c.name_ko} ${k.pill}`, k.tone), h("small", {class: "lrb-sub"}, k.text)); })
        : h("small", {class: "lrb-sub"}, "따라가는 실행기 없음")))));
    const more = rows.length > st.tradesN ? h("button", {class: "btn-line lrb-more", type: "button", onclick: () => { st.tradesN += PAGE; drawTrades(); }},
      `더 보기 (${fmt.int(rows.length - st.tradesN)}개 남음)`) : null;
    put(tradesBox, list, more);
  }
  function drawFollow() {
    const fs = st.d.follow || [];
    if (!fs.length) { put(followBox, ui.empty("이 봇을 따라가는 실행기가 아직 없어요 (페이퍼만)")); return; }
    put(followBox, fs.map((f) => {
      if (f.state !== "ok") return sourceState(f, `${f.name_ko} 실행기 기록`);
      const c = f.counts || {};
      const head = h("div", {class: "lrb-chiprow"}, h("b", null, f.name_ko), ok(f.since_ms) ? h("span", {class: "lrb-sub"}, `${fmt.kst(f.since_ms)}부터`) : null,
        ...[["followed", "따라 들어감"], ["open", "같이 들고 있음"], ["missed", "안 들어감"], ["waiting", "기록 기다리는 중"]]
          .filter(([k]) => c[k]).map(([k, ko]) => ui.pill(`${ko} ${fmt.int(c[k])}`, (CELL[k] || [])[1] || "thin")),
        ...(f.why || []).map((w) => ui.pill(`${w.ko || "이유 기록 없음"} ${fmt.int(w.n)}`, "warn")));
      const rows = f.rows || [];
      return h("div", {class: "lrb-fgroup"}, head, rows.length ? h("ul", {class: "lrb-list"}, rows.slice(0, st.followN).map((r) => {
        const k = cellKo(r);
        return h("li", {class: ["lrb-frow", r.state]}, h("span", {class: "num lrb-t"}, fmt.kst(r.entry_ms)), h("b", null, `${r.coin} ${SIDE(r.side)}`),
          ui.pill(k.pill, k.tone), h("small", {class: "lrb-sub"}, [paperKo(r), k.text].filter(Boolean).join(" · ")));
      })) : ui.empty("옮긴 뒤 페이퍼 진입이 아직 없어요"), f.more ? h("p", {class: "lrb-sub"}, `그 전 ${fmt.int(f.more)}개는 이 화면에 안 보여요`) : null);
    }));
  }
  function drawFlip() {
    const f = st.d.flip;
    if (!f) { put(flipBox, ui.empty("봇이 켜지면 보여요")); return; }
    put(flipBox,
      h("p", {class: "lrb-lead"}, f.lead_ko || ""),
      h("ul", {class: "lrb-list"}, (f.rows || []).map((r) => h("li", {class: "lrb-xrow"}, h("b", null, r.ko),
        r.state === "ok" ? h("span", {class: "num"}, `${fmt.int(r.n)}번 · ${fmt.int(r.wins)}승 ${fmt.int(r.losses)}패 · 승률 ${rateKo(r.win_rate)} · 순ROE 합 ${pctKo(r.roe_sum, 0)} · 지갑 ${fmt.usd(r.wallet)} (모의)`)
          : h("span", {class: "lrb-sub"}, r.reason_ko || "수집 전")))),
      f.few ? h("p", {class: "lrb-sub"}, "거래 40번 전에는 우연이 커요 · 어느 쪽이 낫다고 정하지 않아요") : null);
  }
  function drawEquity() {
    const d = st.d, w = d.wallet;
    const parts = [];
    if (w && w.state === "ok" && (w.curve || []).length >= 2) {
      parts.push(h("p", {class: "lrb-sub"}, h("b", null, "페이퍼 지갑 (모의)")),
        h("div", {class: "lrb-spark"}, ui.miniSpark(w.curve.map((x) => Number(x[1])), {fluid: true, h: 56, base: ok(w.initial) ? Number(w.initial) : null, label: "페이퍼 지갑 흐름"})));
    } else parts.push(h("p", {class: "lrb-sub"}, "페이퍼 지갑: 닫힌 거래가 쌓이면 줄이 그려져요"));
    for (const f of followers()) {
      if (f.state !== "ok") { parts.push(h("p", {class: "lrb-sub"}, `${f.name_ko}: ${f.reason_ko || "기록 못 읽음"}`)); continue; }
      const vals = (f.curve || []).map((x) => Number(x[1]));
      parts.push(h("p", {class: "lrb-sub"}, h("b", null, `${f.name_ko} 잔고 (실거래)`), ok(f.start_balance) ? ` · 옮길 때 ${fmt.usd(f.start_balance)} → 지금 ${fmt.usd(f.balance)}` : ""),
        vals.length >= 2 ? h("div", {class: "lrb-spark"}, ui.miniSpark(vals, {fluid: true, h: 56, base: ok(f.start_balance) ? Number(f.start_balance) : null, label: `${f.name_ko} 잔고 흐름`}))
          : h("p", {class: "lrb-sub"}, "잔고 기록이 둘 이상 쌓이면 줄이 그려져요"));
    }
    put(eqBox, parts);
  }
  function drawSignals() {
    const sg = st.d.signals || {}, rows = sg.rows || [];
    if (!rows.length) { put(sigBox, ui.empty("최근 24시간 신호가 없어요")); return; }
    put(sigBox,
      h("div", {class: "lrb-chiprow"}, (sg.counts || []).map((c) => ui.pill(`${c.ko} ${fmt.int(c.n)}`, c.stage === "entered" ? "good" : c.stage === "filtered" ? "warn" : "thin"))),
      h("ul", {class: "lrb-list"}, rows.slice(0, st.sigN).map((r) => h("li", {class: ["lrb-srow", r.stage]}, h("span", {class: "num lrb-t"}, fmt.kst(r.t)),
        h("b", null, `${r.coin} ${SIDE(r.side)}`), ui.pill(r.ko, r.stage === "entered" ? "good" : r.stage === "filtered" ? "warn" : "thin"),
        r.why ? h("small", {class: "lrb-sub"}, r.why) : null))),
      rows.length > st.sigN ? h("button", {class: "btn-line lrb-more", type: "button", onclick: () => { st.sigN += PAGE * 2; drawSignals(); }},
        `더 보기 (${fmt.int(rows.length - st.sigN)}개 남음)`) : null);
  }
  function drawWarns() {
    const d = st.d;
    const xs = [...(d.alerts || []).map((a) => ({...a, who: "레인지 봇"})),
      ...followers().flatMap((f) => (f.events || []).map((e) => ({...e, who: f.name_ko})))].sort((a, b) => Number(b.ts) - Number(a.ts));
    put(warnBox, xs.length ? h("ul", {class: "lrb-list"}, xs.slice(0, 20).map((x) => h("li", {class: ["lrb-erow", x.level === "CRITICAL" ? "crit" : ""]},
      h("span", {class: "num lrb-t"}, fmt.kst(x.ts)), ui.pill(x.level_ko || x.level, x.level === "CRITICAL" ? "bad" : "warn"),
      h("b", null, `${x.who}${x.kind_ko ? ` · ${x.kind_ko}` : ""}`), h("small", {class: "lrb-sub"}, x.text || ""))))
      : ui.empty("주의 · 긴급 기록이 없어요"));
  }
  function draw() {
    if (!st.d) return;
    drawHero(); drawPlan(); drawPos(); drawWait(); drawTrades(); drawFollow(); drawFlip(); drawEquity(); drawSignals(); drawWarns();
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
