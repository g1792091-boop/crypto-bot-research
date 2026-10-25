// 실거래 › 믹스 봇 (owners 10/25 night: the '믹스 30분 봇', paperbot/mixchop.py, docs/mixchop-ko.md, trades the second WOO X
// Pro account with real money; its paper twin runs the same signal with no orders), two tabs of the menu group "믹스 봇"
// (core/routes.js LIVE_GROUPS), read-only:
//   관제 (#/mix)      the live bot and the paper bot side by side: running / stopped / not installed (the last record, the
//                     systemd unit when stopped), the equity now with the start equity and the 70 % floor line, what stops
//                     new entries now (the stop files, the floor; the last halt the log shows), the entry block now and the
//                     next window (counting down on the server's clock), the open position with its stop, ladder step,
//                     best price and the next ladder trigger; the last 48 hours of signals with what became of each, the
//                     warnings highlighted
//   성적 (#/mixperf)  the closed trades of each bot (count, wins, win rate, P&L, average win / loss, largest loss, by coin,
//                     the list) next to the design's 5-year backtest per coin (labelled: not live), and the rules
// Sources: /api/v4/livebots/mix (every 15 s; countdowns tick every second), /mixperf (every 60 s), dash/more/livemix.py.
// HONESTY: unread = 못 읽음 + why, never a zero; a bot with no files says 꺼짐 and how to start it; the paper bot's money is
// never shown as real money (모의 · 진짜 돈 아님); small samples say so; the backtest is labelled as the design's, not live.
import {h, put, ui, fmt, store, serverNow, local} from "../core/pb.js";
import {sourceState} from "./livebots-kit.js";

export const API = "/api/v4/livebots/mix";
export const PERF_API = "/api/v4/livebots/mixperf";
const REFRESH_MS = 15 * 1000;
const SLOW_MS = 60 * 1000;
const TICK_MS = 1000;
const MIN = 60 * 1000;
const FEED_PAGE = 25;
const TRADES_PAGE = 15;
const SIDE = (x) => (Number(x) > 0 ? "롱" : "숏");
const ok = (x) => x != null && x !== "" && Number.isFinite(Number(x));
const BOT_KO = {live: "실거래 · WOO X Pro 2", paper: "모의 · 주문 없음"};
const STATUS = {running: ["돌고 있음", "good", "run"], stopped: ["멈춤", "bad", "stop"], off: ["꺼짐", "thin", "off"], error: ["못 읽음", "bad", "err"]};

// ---------------------------------------------------------------- pure (node tests: tests/test_dash_livemix.py)
/** "31시간 20분" / "45분" (ms); "—" for unknown. */
export function holdKo(ms) {
  if (!ok(ms)) return "—";
  const m = Math.max(0, Math.floor(Number(ms) / MIN));
  if (m < 60) return `${m}분`;
  if (m < 48 * 60) return `${Math.floor(m / 60)}시간${m % 60 ? ` ${m % 60}분` : ""}`;
  return `${Math.floor(m / 1440)}일 ${Math.floor((m % 1440) / 60)}시간`;
}
/** "+12.1%" / "−4.3%" of a ratio. */
export const pctKo = (x, d = 1) => fmt.pct(x, d, true);
/** "32.0%" (no sign). */
export const rateKo = (x, d = 1) => (ok(x) ? fmt.pct(x, d, false) : "—");
/** "$49.95" (2 decimals); "—" for unknown. */
export const usdKo = (x) => (ok(x) ? fmt.usd(x) : "—");
/** A small P&L with its sign, 3 decimals ($50 accounts: a stop-out is about $0.13): "+$0.026" / "−$0.130"; "모름". */
export function pnlKo(x) {
  if (!ok(x)) return "모름";
  const v = Number(x);
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}$${fmt.num(Math.abs(v), 3)}`;
}
/** The status line of a bot: {cls, pill, tone, line, hint}. */
export function statusOf(b, now) {
  const s = (b && b.status) || {};
  const [pill, tone, cls] = STATUS[s.state] || ["모름", "thin", "err"];
  const seen = ok(s.seen_ms) ? `마지막 기록 ${fmt.kst(s.seen_ms)} (${holdKo(Number(now) - Number(s.seen_ms))} 전)` : "";
  const line = s.state === "off" ? (s.ko || "기록 파일이 없어요")
    : s.state === "error" ? (s.reason_ko || s.ko || "상태 파일을 읽지 못했어요")
      : [seen, ok(s.last_close_ms) ? `마지막으로 본 30분봉 ${fmt.hm(Number(s.last_close_ms))} 마감` : "",
        ok(s.started_ms) ? `마지막 시작 ${fmt.kst(s.started_ms)}` : ""].filter(Boolean).join(" · ");
  const hint = s.state === "stopped" || s.state === "error" ? `서버에서 systemctl status ${s.unit || (b && b.unit) || ""}`.trim() : "";
  return {cls, pill, tone, line, hint};
}
/** The new-entry verdict of a running bot: {cls: halt / block / hold / go / na, ko, sub}. */
export function verdictOf(b) {
  if (!b || !b.status || b.status.state === "off" || b.status.state === "error") return {cls: "na", ko: "", sub: ""};
  const hs = (b.halts || {}).items || [];
  const sure = hs.filter((x) => x.sure);
  if (sure.length) return {cls: "halt", ko: "새 진입 멈춤", sub: sure.map((x) => x.ko).join(" · ")};
  if (hs.length) return {cls: "halt", ko: "새 진입 멈춤인지 몰라요", sub: hs.map((x) => x.ko).join(" · ")};
  const bl = b.blocks || {};
  if (bl.state === "ok" && bl.now && bl.now.blocked) return {cls: "block", ko: "지금은 진입 금지 시간", sub: bl.now.ko};
  if (bl.state === "error") return {cls: "na", ko: "진입 금지 시간을 몰라요", sub: bl.reason || bl.ko || ""};
  const p = b.position;
  if (p && p.state === "ok") return {cls: "hold", ko: `${p.coin} ${SIDE(p.side)} 보유 중`, sub: "새 신호는 건너뛰어요 (한 번에 1포지션)"};
  if (p && p.state !== "ok") return {cls: "na", ko: "포지션을 몰라요", sub: p.ko || ""};
  return {cls: "go", ko: "지금 진입 가능", sub: "30분봉이 끝날 때 신호가 나오면 들어가요"};
}
/** The next ladder step in words: "ROE +290% (107.25)에 닿으면 손절을 103.75 (ROE +150%)로" (+ 이미 닿음). */
export function ladderKo(p) {
  const n = p && p.next;
  if (!n) return "계산할 수 없어요";
  const s = `ROE ${pctKo(n.trigger_roe, 0)} (${fmt.price(n.trigger)})에 닿으면 손절을 ${fmt.price(n.stop_to)} (ROE ${pctKo(n.stop_to_roe, 0)})로`;
  return n.reached ? `${s} · 이미 닿음: 다음 30분봉 마감 때 옮겨요` : s;
}
/** The stop in words: "100.25 · ROE +10% · 계단 1단계" / "99.00 · ROE −40% · 처음 손절". */
export function stopKo(p) {
  if (!p || !ok(p.stop)) return "—";
  return `${fmt.price(p.stop)} · ROE ${pctKo(p.stop_roe, 0)} · ${p.step > 0 ? `계단 ${p.step}단계` : "처음 손절"}`;
}
/** One row of 최근 48시간 in words: {head, pill, tone, text}. */
export function feedKo(x) {
  const who = `${x.coin || ""}${x.side ? ` ${SIDE(x.side)}` : ""}`.trim();
  if (x.cat === "signal") {
    const want = x.want ? ` (${SIDE(x.want)} 쪽)` : "";
    const o = x.outcome || {};
    const vals = valsKo(x.vals);
    if (x.stage === "entered") {
      return {head: `${x.coin} ${x.colour_ko}${want}`, pill: o.adopted ? "진입 (늦게 확인)" : "진입", tone: "good",
        text: [`체결 ${fmt.price(o.entry)} · ${fmt.num(o.qty, 4)}개 · 손절 ${fmt.price(o.stop)}`, vals].filter(Boolean).join(" · ")};
    }
    if (x.stage === "skipped") return {head: `${x.coin} ${x.colour_ko}${want}`, pill: `건너뜀 · ${o.group_ko}`, tone: o.tone || "thin", text: [o.why, vals].filter(Boolean).join(" · ")};
    if (x.stage === "refused") return {head: `${x.coin} ${x.colour_ko}`, pill: "진입 안 함", tone: "thin", text: [x.why, vals].filter(Boolean).join(" · ")};
    return {head: `${x.coin} ${x.colour_ko}${want}`, pill: "결과 기록 없음", tone: "thin", text: vals};
  }
  if (x.cat === "skip") return {head: who, pill: `건너뜀 · ${x.group_ko}`, tone: x.tone, text: x.why || ""};
  if (x.cat === "entry") return {head: `${who} 진입${x.adopted ? " (늦게 확인)" : ""}`, pill: "진입", tone: "good",
    text: `체결 ${fmt.price(x.entry)} · ${fmt.num(x.qty, 4)}개 · 손절 ${fmt.price(x.stop)}`};
  if (x.cat === "exit") {
    return {head: `${who} 청산 · ${x.why_ko}`, pill: pnlKo(x.pnl), tone: x.tone,
      text: [ok(x.price) ? `가격 ${fmt.price(x.price)}` : "체결가는 기록에 없음", x.pnl == null ? "손익 모름 (잔고를 못 읽음)" : null,
        ok(x.equity) ? `잔고 ${usdKo(x.equity)}` : null, x.step > 0 ? `계단 ${x.step}단계까지` : null].filter(Boolean).join(" · ")};
  }
  if (x.cat === "ladder") return {head: `${x.coin} 계단 ${x.step}단계`, pill: "손절 올림", tone: "accent",
    text: `손절 ${fmt.price(x.old)} → ${fmt.price(x.new)} · 가장 유리했던 가격 ${fmt.price(x.best)}`};
  if (x.cat === "start") {
    return {head: "봇 시작", pill: (x.setup_bad || []).length ? "설정 실패 있음" : "시작", tone: x.tone,
      text: [`잔고 ${usdKo(x.equity)} · 시작 잔고 ${usdKo(x.start_equity)}`, x.held ? `보유 중 ${x.held} 이어감` : null,
        ...(x.setup_bad || []).map((t) => `⚠ ${t}`)].filter(Boolean).join(" · ")};
  }
  if (x.cat === "warn") {
    return {head: [x.ko, x.coin].filter(Boolean).join(" · "), pill: x.tone === "bad" ? "긴급" : "주의", tone: x.tone,
      text: [x.n > 1 ? `${fmt.int(x.n)}번 (${fmt.kst(x.first_ms)}부터)` : null, x.where ? `${x.where}` : null, x.error].filter(Boolean).join(" · ")};
  }
  return {head: who || String(x.kind || ""), pill: String(x.kind || ""), tone: "thin", text: ""};
}
/** The signal's numbers: "30분 평균 RSI 61.2 · 1시간 평균 RSI 55.0 · 종가 0.0812 · 손절 폭 1.23%". */
export function valsKo(v) {
  if (!v) return "";
  return [ok(v.avg_rsi_30m) ? `30분 평균 RSI ${fmt.num(v.avg_rsi_30m, 1)}` : null, ok(v.avg_rsi_1h) ? `1시간 평균 RSI ${fmt.num(v.avg_rsi_1h, 1)}` : null,
    ok(v.close) ? `종가 ${fmt.price(v.close)}` : null, ok(v.stop_pct) ? `손절 폭 ${fmt.num(v.stop_pct, 2)}%` : null].filter(Boolean).join(" · ");
}

// ---------------------------------------------------------------- shared parts
/** A tab's own poll: its endpoint every ``every`` ms, the failures said (stale: dimmed with its age). */
function poller(ctx, api, every, st, slot, main, draw) {
  async function load() {
    if (st.busy) return;
    st.busy = true;
    let d;
    try { d = await ctx.api(api); }
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
  ctx.every(every, () => load().catch(() => {}), {now: false});
  return load;
}
function tile(k, v, sub, cls, title) {
  return h("div", {class: ["lmx-tile", cls || ""], role: "listitem", title}, h("span", {class: "lmx-tk"}, k), h("b", {class: "lmx-tv num"}, v),
    sub ? h("span", {class: "lmx-ts"}, sub) : null);
}
/** The head of a bot's column: the orb, its name, the status pill and line (both tabs). */
function botHead(b, now) {
  const s = statusOf(b, now);
  return h("div", {class: ["lmx-bhead", s.cls]},
    h("div", {class: "lmx-orb", "aria-hidden": "true"}, h("i")),
    h("div", {class: "lmx-bmain"},
      h("p", {class: "lmx-kick"}, b.real ? "진짜 돈 · WOO X Pro 두 번째 계정" : "연습 · 같은 신호, 주문 없음 · 진짜 돈 아님"),
      h("h2", {class: "lmx-bname"}, BOT_KO[b.id] || b.ko, " ", ui.pill(s.pill, s.tone, `서버 서비스 ${b.unit}`)),
      s.line ? h("p", {class: "lmx-sub"}, s.line) : null,
      s.hint ? h("p", {class: "lmx-hint"}, s.hint) : null,
      (b.status || {}).mode_ko ? h("p", {class: "lmx-warn"}, b.status.mode_ko) : null));
}
function offBox(b) {
  return h("div", {class: "lmx-off", role: "status"},
    h("div", {class: "lmx-offhead"}, ui.pill("꺼짐", "thin"), h("b", null, (b.status || {}).ko || "아직 꺼져 있어요")),
    h("p", null, `켜면 이 칸에 봇의 상태 · 잔고 · 포지션 · 신호 · 성적이 보여요. ${b.start_ko || ""}`),
    h("p", {class: "lmx-sub"}, `읽는 파일: ${((b.files || {}).state || {}).path || "—"} · ${((b.files || {}).log || {}).path || "—"}`));
}
/** The small print of the files: the config's source, a cut log, unreadable parts. */
function fileNotes(b) {
  const f = b.files || {}, c = f.config || {}, lg = f.log || {};
  return [
    c.source === "repo" ? h("p", {class: "lmx-warn"}, c.reason_ko || "서버 설정 파일 대신 저장소 기본 설정으로 보여 줘요") : null,
    c.state === "error" ? sourceState(c, "설정 파일") : null,
    lg.state && lg.state !== "ok" ? sourceState(lg, "기록(log) 파일") : null,
    lg.cut ? h("p", {class: "lmx-sub"}, `기록이 길어 끝부분 ${fmt.int((lg.tail_bytes || 0) / 1048576)}MB만 읽었어요 (${fmt.kst(lg.from_ms)}부터) · 그 전 거래는 성적에 빠져요`) : null,
    lg.bad ? h("p", {class: "lmx-sub"}, `기록 줄 ${fmt.int(lg.bad)}개는 읽을 수 없어 뺐어요`) : null];
}

// ================================================================ 관제 (#/mix)
/** mixView(ctx) -> {el, set()}: the two bots now (module comment). */
export function mixView(ctx) {
  const st = {d: null, okAt: 0, busy: false, ticks: [], feed: local.get("lmx-feed", "live"), feedN: FEED_PAGE};
  const slot = h("div", {class: "lb-slot"});
  const botsBox = h("div", {class: "lmx-bots"});
  const feedHead = h("div", {class: "lmx-feedhead"});
  const feedBox = h("div", {class: "lmx-feed"});
  const cards = h("div", {class: "lmx-cards"}, botsBox,
    ui.card({title: "최근 48시간", sub: "봇 기록 그대로 · 30분봉 색 변화마다 무엇이 됐는지 · 경고는 색 줄 · 한국 시간", cls: "lmx-feedcard"}, feedHead, feedBox));
  const main = h("div", {class: "lmx-body"}, cards);
  const el = h("div", {class: "lmx stack"}, slot, main,
    ui.note("보기만 하는 화면 · 15초마다 새로 읽어요 · 남은 시간은 1초마다 줄어요 · 봇은 30분봉이 끝날 때마다 기록해요 · 모의 칸의 돈은 진짜 돈이 아니에요"));

  // a text that follows the server's clock every second (a countdown, a hold time)
  const tick = (node, f) => { st.ticks.push({node, f}); node.textContent = f(serverNow()); return node; };

  function moneyBox(b) {
    const e = b.equity || {}, n = e.now;
    const items = [];
    if (n && ok(n.value)) {
      items.push(tile(b.real ? "실거래 잔고" : "모의 잔고", usdKo(n.value),
        `${n.from_ko}${ok(n.ms) ? ` · ${fmt.kst(n.ms)}` : ""}${b.real ? "" : " · 진짜 돈 아님"}`, b.real ? "real" : "paper",
        b.real ? "봇이 WOO X Pro에서 읽어 기록한 마지막 잔고 (지금 거래소 값은 앱에서)" : "모의 잔고 (주문 없음)"));
    } else items.push(tile(b.real ? "실거래 잔고" : "모의 잔고", "수집 전", e.none_ko || "", "na"));
    items.push(tile("시작 잔고", usdKo(e.start), ok(e.change) ? `지금까지 ${pctKo(e.change)}${b.real ? "" : " (모의)"}` : "", b.real ? "" : "paper"));
    items.push(tile(`바닥선 (시작의 ${rateKo(e.floor_frac, 0)})`, usdKo(e.floor),
      e.below ? "아래로 내려감 → 새 진입 멈춤" : ok(e.room) ? `남은 여유 ${usdKo(e.room)}` : "아래로 가면 새 진입을 멈춰요", e.below ? "bad" : ""));
    const frac = ok(n && n.value) && ok(e.start) && Number(e.start) > 0 ? Math.max(0, Math.min(1, Number(n.value) / Number(e.start) / 1.5)) : null;
    return [h("div", {class: "lmx-money", role: "list", "aria-label": b.real ? "실거래 잔고" : "모의 잔고"}, items),
      frac == null ? null : h("div", {class: ["lmx-meter", e.below ? "bad" : ""], role: "img", "aria-label": "잔고와 바닥선"},
        h("i", {style: {"--v": frac.toFixed(4)}}), h("b", {style: {"--m": (Number(e.floor_frac || 0.7) / 1.5).toFixed(4)}}),
        h("u", {style: {"--m": (1 / 1.5).toFixed(4)}}))];
  }
  function haltBox(b) {
    const hs = b.halts || {}, bl = b.blocks || {};
    const v = verdictOf(b);
    const last = hs.last;
    const left = h("span", {class: "num"});
    return h("div", {class: "lmx-gate"},
      h("div", {class: ["lmx-verdict", v.cls]}, h("b", null, v.ko), v.sub ? h("span", {class: "lmx-sub"}, ` ${v.sub}`) : null),
      h("ul", {class: "lmx-list lmx-ilist"},
        (hs.items || []).map((x) => h("li", {class: "bad"}, h("span", {class: "lmx-ik"}, "멈춤"), h("span", null, x.ko, x.path ? h("small", {class: "lmx-sub"}, ` (${x.path})`) : null))),
        hs.cfg_unread ? h("li", {class: "warn"}, h("span", {class: "lmx-ik"}, "멈춤"), "설정을 못 읽어 정지 파일 위치를 몰라요") : null,
        bl.state === "ok" ? h("li", {class: bl.now && bl.now.blocked ? "warn" : ""}, h("span", {class: "lmx-ik"}, "지금"),
          h("span", null, bl.now.ko, bl.now.blocked && ok(bl.now.until) ? ` · ${fmt.kst(bl.now.until)}까지` : "")) :
          h("li", {class: "warn"}, h("span", {class: "lmx-ik"}, "지금"), bl.ko || "진입 금지 시간을 몰라요", bl.reason ? h("small", {class: "lmx-sub"}, ` (${bl.reason})`) : null),
        bl.state === "ok" && bl.any ? (bl.next ? h("li", null, h("span", {class: "lmx-ik"}, "다음 금지"),
          h("span", null, `${bl.next.ko} · ${fmt.kst(bl.next.from)} ~ ${ok(bl.next.until) ? fmt.kst(bl.next.until) : "?"} · `,
            tick(left, (now) => (Number(bl.next.from) > now ? `${holdKo(Number(bl.next.from) - now)} 뒤` : "지금")))) : h("li", null, h("span", {class: "lmx-ik"}, "다음 금지"), `앞으로 ${bl.days || 8}일 안에 없음`)) : null,
        last ? h("li", {class: last.recent && !last.entry_after ? "warn" : ""}, h("span", {class: "lmx-ik"}, "기록"),
          h("span", null, `마지막 멈춤 기록 ${fmt.kst(last.ms)}: ${last.why}`, last.entry_after ? h("small", {class: "lmx-sub"}, " · 그 뒤 진입이 있었어요") : null)) : null),
      bl.state === "ok" ? h("p", {class: "lmx-sub"}, `진입 금지: ${(bl.rules || []).map((r) => `${r.ko} ${r.on ? "켬" : "끔"}`).join(" · ")} · 서버 시계로 판단 · 막힌 신호는 나중에 따라 들어가지 않아요`) : null,
      hs.note_ko ? h("p", {class: "lmx-sub"}, hs.note_ko) : null);
  }
  function posBox(b) {
    const p = b.position;
    if (p && p.state !== "ok") {
      return h("div", {class: "lmx-pos"}, h("div", {class: "lb-state bad"}, ui.pill("못 읽음", "bad"), h("span", null, ` ${p.ko}`),
        p.reason ? h("span", {class: "lb-raw", title: p.reason}, ` (${p.reason})`) : null));
    }
    if (!p) {
      return h("div", {class: "lmx-pos lmx-empty"}, h("b", null, "포지션 없음"),
        h("p", null, "30분봉이 끝날 때 하늘색(롱)·보라색(숏)으로 바뀌고 30분·1시간 평균 RSI 조건이 맞으면 시장가로 들어가요 (한 번에 1포지션)."));
    }
    const heldNode = h("b", {class: "num"});
    const mark = store.mark(p.symbol);
    const roe = ok(mark) && ok(p.entry) && ok(p.leverage) ? Number(p.side) * (Number(mark) / Number(p.entry) - 1) * Number(p.leverage) : null;
    return h("div", {class: "lmx-pos"},
      h("div", {class: "lmx-phead"}, h("span", {class: ["side", Number(p.side) > 0 ? "long" : "short"]}, SIDE(p.side)),
        h("b", {class: "lmx-pcoin"}, p.coin), h("span", {class: "lmx-sub"}, ` ${fmt.lev(p.leverage)} 격리 · `),
        ok(p.opened_ms) ? tick(heldNode, (now) => `${holdKo(now - Number(p.opened_ms))} 째`) : null),
      h("dl", {class: "lmx-kv"},
        h("dt", null, "진입"), h("dd", {class: "num"}, `${fmt.price(p.entry)} · ${fmt.kst(p.opened_ms)}`),
        h("dt", null, "수량"), h("dd", {class: "num"}, `${fmt.num(p.qty, 4)}개 · ≈ ${usdKo(p.notional)} (증거금 ${usdKo(p.margin)})${b.real ? "" : " · 모의"}`),
        h("dt", null, "손절"), h("dd", {class: ["num", p.locked ? "up" : ""]}, stopKo(p),
          ok(p.stop_pnl) ? h("small", {class: "lmx-sub"}, ` · 맞으면 약 ${pnlKo(p.stop_pnl)} (수수료 전)`) : null),
        h("dt", null, "가장 유리했던 가격"), h("dd", {class: "num"}, `${fmt.price(p.best)} · ROE ${pctKo(p.best_roe, 0)}`,
          h("small", {class: "lmx-sub"}, " (30분봉 고가·저가, 마감 때 반영)")),
        h("dt", null, "다음 계단"), h("dd", {class: ["num", p.next && p.next.reached ? "warn" : ""]}, ladderKo(p)),
        roe != null ? h("dt", null, "지금 가격") : null,
        roe != null ? h("dd", {class: "num"}, `${fmt.price(mark)} · ROE `, h("span", {class: fmt.tone(roe)}, pctKo(roe, 0)),
          h("small", {class: "lmx-sub"}, " (바이낸스 가격, 수수료 전 · 참고)")) : null,
        h("dt", null, "신호 봉"), h("dd", {class: "num"}, `${fmt.kst(p.signal_close_ms)} 마감 · 종가 ${fmt.price(p.signal_close)}`)),
      p.stop_id_missing ? h("p", {class: "lmx-warn"}, "상태 파일에 손절 주문 번호가 없어요 · 봇이 5분마다 손절을 확인해요 · WOO X Pro 앱에서도 확인하세요") : null,
      h("p", {class: "lmx-sub"}, `계단: 가장 유리했던 가격이 ROE ${pctKo(p.roe_act, 0)} (${fmt.price(p.first_act_price)})에 닿으면 손절을 ROE ${pctKo(p.lock_roe, 0)} (${fmt.price(p.first_lock_price)})로, 그 뒤 같은 폭씩 · 30분봉 마감 때만 옮겨요`));
  }
  function botCol(b) {
    const now = serverNow();
    const s = (b.status || {}).state;
    const kids = [botHead(b, now)];
    if (s === "off") kids.push(offBox(b));
    else {
      if (s === "error") kids.push(sourceState({state: "error", reason_ko: b.status.reason_ko, reason: b.status.reason}, "상태 파일"));
      kids.push(...moneyBox(b), haltBox(b), h("h3", {class: "lmx-h3"}, "포지션"), posBox(b));
      if ((b.setup_bad || []).length) kids.push(h("p", {class: "lmx-warn"}, `마지막 시작 때 설정 실패: ${b.setup_bad.join(" · ")} (그 코인은 거래 안 함)`));
      kids.push(...fileNotes(b));
    }
    return h("section", {class: ["lmx-bot", b.id, (STATUS[s] || [])[2] || "err"], "aria-label": BOT_KO[b.id] || b.ko}, kids);
  }
  function drawBots() {
    st.ticks = [];
    put(botsBox, (st.d.bots || []).map(botCol));
  }
  function drawFeed() {
    const bots = st.d.bots || [];
    const b = bots.find((x) => x.id === st.feed) || bots[0];
    put(feedHead, ui.seg(bots.map((x) => ({id: x.id, label: x.id === "live" ? "실거래" : "모의"})), b ? b.id : "",
      (id) => { st.feed = id; st.feedN = FEED_PAGE; local.set("lmx-feed", id); drawFeed(); }, {label: "어느 봇"}),
    b && b.feed ? h("div", {class: "lmx-chiprow"}, ...[["signal", "색 변화"], ["entered", "진입"], ["skipped", "건너뜀"], ["refused", "조건 안 맞음"], ["exit", "청산"], ["ladder", "계단"]]
      .filter(([k]) => b.feed.counts[k]).map(([k, ko]) => ui.pill(`${ko} ${fmt.int(b.feed.counts[k])}`, k === "entered" ? "good" : "thin")),
    b.feed.counts.warn ? ui.pill(`경고 ${fmt.int(b.feed.counts.warn)}`, b.feed.bad ? "bad" : "warn") : null) : null);
    if (!b) { put(feedBox, ui.empty("봇이 없어요")); return; }
    if ((b.status || {}).state === "off") { put(feedBox, ui.empty(`${b.ko} 봇이 아직 꺼져 있어요 · 켜면 신호가 여기 쌓여요`)); return; }
    if (!b.feed) { put(feedBox, sourceState((b.files || {}).log || {}, "기록(log) 파일")); return; }
    const rows = b.feed.rows || [];
    const list = h("ul", {class: "lmx-list lmx-flist"}, rows.slice(0, st.feedN).map((x) => {
      const k = feedKo(x);
      return h("li", {class: ["lmx-frow", x.cat, x.cat === "warn" && x.tone === "bad" ? "crit" : ""]},
        h("span", {class: "num lmx-t"}, fmt.kst(x.t)), h("b", {class: "lmx-fhead"}, k.head), ui.pill(k.pill, k.tone),
        k.text ? h("small", {class: "lmx-sub lmx-why"}, k.text) : null);
    }));
    const more = rows.length > st.feedN ? h("button", {class: "btn-line lmx-more", type: "button", onclick: () => { st.feedN += FEED_PAGE; drawFeed(); }},
      `더 보기 (${fmt.int(rows.length - st.feedN)}개 남음)`) : null;
    put(feedBox, rows.length ? [list, more] : ui.empty("최근 48시간 기록이 없어요 · 신호는 30분봉 색이 바뀔 때만 남아요"));
  }
  function draw() {
    if (!st.d) return;
    drawBots(); drawFeed();
  }
  function onTick() {
    for (const k of st.ticks) k.node.textContent = k.f(serverNow());
  }
  poller(ctx, API, REFRESH_MS, st, slot, main, draw);
  ctx.every(TICK_MS, onTick, {now: false});
  if (ctx.watch) ctx.watch("ticker", () => { if (st.d) drawBots(); });
  return {el, set() {}};
}

// ================================================================ 성적 (#/mixperf)
/** The record's numbers in rows: [label, text, tone]. */
export function recordRows(r, real) {
  if (!r) return [];
  const unit = real ? "" : " (모의)";
  return [
    ["닫힌 거래", `${fmt.int(r.n)}번${r.unknown ? ` (손익 모름 ${fmt.int(r.unknown)})` : ""}`],
    ["이김 / 짐", `${fmt.int(r.wins)}승 ${fmt.int(r.losses)}패`],
    ["승률", rateKo(r.win_rate)],
    [`손익 합${unit}`, pnlKo(r.pnl), fmt.tone(r.pnl)],
    ["평균 익절", r.avg_win == null ? "—" : pnlKo(r.avg_win)],
    ["평균 손절", r.avg_loss == null ? "—" : pnlKo(r.avg_loss)],
    ["가장 큰 손실", r.worst == null ? "—" : pnlKo(r.worst), r.worst == null ? "" : "down"],
    ["계단까지 간 거래", `${fmt.int(r.ladder_n)}번`],
  ];
}
/** The backtest table's rows with each bot's own numbers per coin beside them. */
export function compareCoins(bt, bots) {
  const of = (id, sym) => ((bots.find((b) => b.id === id) || {}).coins || []).find((c) => c.symbol === sym) || null;
  const cell = (c) => (c && c.n ? `${fmt.int(c.n)}번 · 승률 ${rateKo(c.win_rate, 0)} · ${pnlKo(c.pnl)}` : "아직 없음");
  return ((bt && bt.rows) || []).map((r) => ({symbol: r.symbol, coin: fmt.coin(r.symbol), month: pctKo(r.month, 2), win: rateKo(r.win, 0),
    live: cell(of("live", r.symbol)), paper: cell(of("paper", r.symbol)), small: [of("live", r.symbol), of("paper", r.symbol)].some((c) => c && c.n && c.small)}));
}

/** mixperfView(ctx) -> {el, set()}: 성적 (module comment). */
export function mixperfView(ctx) {
  const st = {d: null, okAt: 0, busy: false, acct: local.get("lmx-trades", "live"), tn: TRADES_PAGE};
  const slot = h("div", {class: "lb-slot"});
  const recBox = h("div", {class: "lmx-bots"});
  const btBox = h("div", {class: "lmx-bt"});
  const tradeHead = h("div", {class: "lmx-feedhead"});
  const tradeBox = h("div", {class: "lmx-trades"});
  const rulesBox = h("div", {class: "lmx-bots"});
  const cards = h("div", {class: "lmx-cards"}, recBox,
    ui.card({title: "설계서 5년 백테스트와 나란히", sub: "왼쪽 두 칸은 설계서 숫자 (실거래 아님) · 오른쪽은 이 봇들의 실제 기록", cls: "lmx-btcard"}, btBox),
    ui.card({title: "거래", sub: "새것부터 · 청산 기록을 진입 기록과 맞춤 · 한국 시간", cls: "lmx-tradecard"}, tradeHead, tradeBox),
    ui.card({title: "규칙", sub: "봇이 읽는 설정 그대로 (서버 설정 파일)", cls: "lmx-rulecard"}, rulesBox));
  const main = h("div", {class: "lmx-body"}, cards);
  const el = h("div", {class: "lmx stack"}, slot, main,
    ui.note("보기만 하는 화면 · 1분마다 새로 읽어요 · 승패는 손익 > 0 기준 · 손익은 진입 때부터 청산 뒤까지 잔고 변화 (수수료 포함) · 모의 칸의 돈은 진짜 돈이 아니에요"));

  function recCard(b) {
    const now = serverNow();
    const s = (b.status || {}).state;
    const kids = [botHead(b, now)];
    if (s === "off") { kids.push(offBox(b)); return h("section", {class: ["lmx-bot", b.id, "off"]}, kids); }
    const r = b.record;
    if (!r) kids.push(sourceState((b.files || {}).log || {}, "기록(log) 파일"));
    else {
      kids.push(h("dl", {class: "lmx-kv lmx-rec"}, recordRows(r, b.real).map(([k, v, tone]) => [h("dt", null, k), h("dd", {class: ["num", tone || ""]}, v)])));
      if (r.small) kids.push(h("p", {class: "lmx-sub"}, `거래 ${fmt.int(r.n)}번은 표본 적음 (${fmt.int(r.small_n)}번 미만) · 이 구조는 승률 20~40%라 연속 손절이 길 수 있어요`));
      kids.push(h("h3", {class: "lmx-h3"}, "코인별"), h("ul", {class: "lmx-list lmx-coins"}, (b.coins || []).map((c) => h("li", {class: ["lmx-crow", c.n ? "" : "zero", c.small && c.n ? "small" : ""]},
        h("b", null, c.coin), h("span", {class: "num"}, c.n ? `${fmt.int(c.n)}번 · ${fmt.int(c.wins)}승 ${fmt.int(c.losses)}패 · 승률 ${rateKo(c.win_rate, 0)}` : "아직 없음"),
        h("b", {class: ["num", fmt.tone(c.pnl)]}, c.n ? pnlKo(c.pnl) : ""), c.n && c.small ? h("small", {class: "lmx-sub"}, "표본 적음") : null))));
    }
    kids.push(...fileNotes(b));
    return h("section", {class: ["lmx-bot", b.id, (STATUS[s] || [])[2] || "err"]}, kids);
  }
  function drawBt() {
    const bt = st.d.backtest || {};
    const rows = compareCoins(bt, st.d.bots || []);
    put(btBox, h("div", {class: "lmx-btab", role: "table", "aria-label": "설계서 백테스트와 실제 기록"},
      h("div", {class: "lmx-btr lmx-bth", role: "row"}, ["코인", "백테스트 한 달 평균", "백테스트 승률", "실거래 (지금까지)", "모의 (지금까지)"].map((x) => h("span", {role: "columnheader"}, x))),
      rows.map((r) => h("div", {class: ["lmx-btr", r.small ? "small" : ""], role: "row"}, h("b", {role: "rowheader"}, r.coin),
        h("span", {class: "num ref", role: "cell"}, r.month), h("span", {class: "num ref", role: "cell"}, r.win),
        h("span", {class: "num", role: "cell"}, r.live), h("span", {class: "num", role: "cell"}, r.paper)))),
    h("p", {class: "lmx-honest"}, `${bt.ko || ""} · ${(bt.notes_ko || []).join(" · ")}`),
    h("p", {class: "lmx-sub"}, `출처: ${bt.src || ""} · 실제 칸의 거래가 ${fmt.int(st.d.split_min_n || 10)}번 미만이면 표본 적음 (대부분 운)`));
  }
  function tradeRow(t, real) {
    return h("li", {class: ["lmx-trow", t.win === true ? "win" : t.win === false ? "loss" : "unknown"]},
      h("div", {class: "lmx-ttop"}, h("b", null, `${t.coin} ${SIDE(t.side)}`), ui.pill(t.why_ko || "청산", t.why === "ladder" ? "good" : t.why === "stop" ? "bad" : "warn"),
        t.step > 0 ? ui.pill(`계단 ${t.step}단계`, "accent") : null,
        h("b", {class: ["num", "lmx-tpnl", fmt.tone(t.pnl)]}, pnlKo(t.pnl), real ? "" : h("small", {class: "lmx-sub"}, " 모의"))),
      h("div", {class: "lmx-tmeta num"}, `${fmt.kst(t.opened_ms)} → ${fmt.kst(t.exit_ms)} (${holdKo(t.hold_ms)}) · ${fmt.price(t.entry)} → ${ok(t.exit) ? fmt.price(t.exit) : "체결가 기록 없음"}`,
        ok(t.roe) ? ` · ROE ${pctKo(t.roe, 0)}` : "", ok(t.r) ? ` · 손절 1번의 ${fmt.num(t.r, 1, true)}배` : "", ok(t.qty) ? ` · ${fmt.num(t.qty, 4)}개 ${fmt.lev(t.leverage)}` : ""),
      t.signal && ok(t.signal.avg_rsi_30m) ? h("div", {class: "lmx-sub"}, `진입 근거: ${valsKo(t.signal)}`) : null,
      t.pnl == null ? h("small", {class: "lmx-sub"}, "손익 모름: 청산 뒤 잔고를 읽지 못했어요") : null,
      t.no_entry_row ? h("small", {class: "lmx-sub"}, "진입 기록이 읽은 범위 밖이라 진입 때 값 일부가 비어요") : null);
  }
  function drawTrades() {
    const bots = st.d.bots || [];
    const b = bots.find((x) => x.id === st.acct) || bots[0];
    put(tradeHead, ui.seg(bots.map((x) => ({id: x.id, label: x.id === "live" ? "실거래" : "모의"})), b ? b.id : "",
      (id) => { st.acct = id; st.tn = TRADES_PAGE; local.set("lmx-trades", id); drawTrades(); }, {label: "어느 봇"}));
    if (!b) { put(tradeBox, ui.empty("봇이 없어요")); return; }
    if ((b.status || {}).state === "off") { put(tradeBox, ui.empty(`${b.ko} 봇이 아직 꺼져 있어요`)); return; }
    const ts = b.trades;
    if (!ts) { put(tradeBox, sourceState((b.files || {}).log || {}, "기록(log) 파일")); return; }
    if (!ts.length) { put(tradeBox, ui.empty("닫힌 거래가 아직 없어요 · 손절이나 계단 손절에 맞아야 닫혀요")); return; }
    const more = ts.length > st.tn ? h("button", {class: "btn-line lmx-more", type: "button", onclick: () => { st.tn += TRADES_PAGE; drawTrades(); }},
      `더 보기 (${fmt.int(ts.length - st.tn)}개 남음)`) : null;
    put(tradeBox, h("ul", {class: "lmx-list lmx-tlist"}, ts.slice(0, st.tn).map((t) => tradeRow(t, b.real))), more);
  }
  function rulesCard(b) {
    const r = b.rules;
    if (!r) return h("section", {class: ["lmx-bot", b.id]}, h("h3", {class: "lmx-h3"}, BOT_KO[b.id]), sourceState((b.files || {}).config || {}, "설정 파일"));
    return h("section", {class: ["lmx-bot", b.id]},
      h("h3", {class: "lmx-h3"}, `${BOT_KO[b.id]} · ${r.mode === "mainnet" ? "실거래 (mainnet)" : "모의 (paper)"}`),
      r.source === "repo" ? h("p", {class: "lmx-warn"}, r.reason_ko || "서버 설정 파일 대신 저장소 기본 설정이에요") : null,
      h("ul", {class: "lmx-list lmx-rlist"},
        h("li", null, `손절 1번 = 잔고의 ${fmt.num(r.risk_pct, 2)}% · 한 번에 1포지션 (같은 봉에 겹치면 아래 코인 순서)`),
        h("li", null, `잔고가 시작의 ${rateKo(r.equity_floor_frac, 0)} 아래면 새 진입 멈춤 · 한 포지션 최대 ${usdKo(r.max_notional_usd)}`),
        h("li", null, `계단: 시작 ROE에 닿으면 손절을 ROE ${pctKo(r.lock_roe, 0)}로, 그 뒤 같은 폭씩 · 반대 신호나 시간으로는 청산 안 함`),
        h("li", null, `진입 금지: ${(r.blocks || []).map((x) => `${x.ko} ${x.on ? "켬" : "끔"}`).join(" · ")}`),
        ok(r.start_equity) ? h("li", null, `시작 금액 ${usdKo(r.start_equity)}${r.mode === "paper" ? " (모의)" : ""}`) : null),
      h("div", {class: "lmx-ctab", role: "table", "aria-label": "코인별 설정"},
        h("div", {class: "lmx-ctr lmx-cth", role: "row"}, ["코인", "1시간 여유", "손절 ATR ×", "계단 시작 ROE", "레버리지"].map((x) => h("span", {role: "columnheader"}, x))),
        (r.coins || []).map((c) => h("div", {class: ["lmx-ctr", c.enabled && !c.off_at_start ? "" : "off"], role: "row"},
          h("b", {role: "rowheader"}, c.coin, !c.enabled ? " (꺼짐)" : c.off_at_start ? " (시작 때 꺼짐)" : ""),
          h("span", {class: "num", role: "cell"}, fmt.num(c.h1_buf, 1)), h("span", {class: "num", role: "cell"}, fmt.num(c.sl_atr, 1)),
          h("span", {class: "num", role: "cell"}, `${rateKo(c.roe_act, 0)} → ${rateKo(r.lock_roe, 0)}`), h("span", {class: "num", role: "cell"}, fmt.lev(c.leverage))))));
  }
  function draw() {
    const d = st.d;
    if (!d) return;
    put(recBox, (d.bots || []).map(recCard));
    drawBt(); drawTrades();
    put(rulesBox, (d.bots || []).map(rulesCard));
  }
  poller(ctx, PERF_API, SLOW_MS, st, slot, main, draw);
  return {el, set() {}};
}
