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
//                     the list) next to the design's 5-year backtest per coin (labelled: not live), and the rules; the
//                     손실 분석 (owners 10-25 night, paperbot/mixcheck.py): 운이냐 고장이냐 (the live record in the 5-year
//                     replay of the bot's own code, with the replay next to the design's numbers), the loss cards of the
//                     live trades, the last morning check (the signal replay, live against paper)
// Sources: /api/v4/livebots/mix (every 15 s; countdowns tick every second), /mixperf (every 60 s), dash/more/livemix.py.
// The 바이비트 봇 (owners 10-29, docs/mixbybit-ko.md: the friend's trend with the OBV / Stoch RSI entries on the Bybit
// account, the same code) has the same two tabs from its own answers (/mixbybit, /mixbybitperf): mixView(ctx, BYBIT_UI);
// its 성적 has no 5-year reference (said so), and 실거래 vs 모의 side by side.
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
/** Each mix bot's screens: its answers, its account and the words that differ (the friend bot's: the tabs as they were). */
export const MIX_UI = {id: "mix", api: API, perf: PERF_API, account: "WOO X Pro 2", exchange: "WOO X Pro", key: "",
  kick: "진짜 돈 · WOO X Pro 두 번째 계정",
  wait: "30분봉이 끝날 때 ① 친구 추세(4표 중 같은 쪽 2표 이상) 쪽으로 " +
    "OBV 히스토그램이 연한색→진한색이 되고 OBV MACD의 AC 막대가 그 쪽(롱: 플러스 양봉, 숏: 마이너스 음봉)이면, " +
    "② 추세 3개(EMA RSI · 하늘·보라 선 · 슈퍼트렌드)가 모두 같은 쪽일 때 EMA RSI 막대가 연한색→진한색이 되면 시장가로 들어가요 (한 번에 1포지션).",
  plan: "계획(손절 1번 = 잔고의 0.25% + 수수료)과 비교", morning: "09:05", h1: true};
export const BYBIT_UI = {id: "bybit", api: "/api/v4/livebots/mixbybit", perf: "/api/v4/livebots/mixbybitperf", account: "바이비트",
  exchange: "바이비트", key: "-b", kick: "진짜 돈 · 바이비트 계정",
  wait: "30분봉이 끝날 때 친구 추세(하늘·보라 선 · EMA RSI · 찹존 · 슈퍼트렌드 4표 중 같은 쪽 2표 이상, 횡보 2표 이상이면 금지) 쪽으로 " +
    "OBV 히스토그램이 연한색→진한색이 되고 OBV MACD의 AC 막대가 그 쪽(롱: 플러스 양봉, 숏: 마이너스 음봉)이면 시장가로 들어가요 (한 번에 1포지션, 50선 조건 없음).",
  plan: "손절 = 진입 때 30분봉 ATR × 3 · 증거금 = 잔고의 40%", morning: "09:07", h1: false};
const botKo = (id, o = MIX_UI) => (id === "live" ? `실거래 · ${o.account}` : "모의 · 주문 없음");
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
  const w = n.basis === "net" ? "순ROE" : "ROE";
  const s = `${w} ${pctKo(n.trigger_roe, 0)} (${fmt.price(n.trigger)})에 닿으면 손절을 ${fmt.price(n.stop_to)} (${w} ${pctKo(n.stop_to_roe, 0)})로`;
  return n.reached ? `${s} · 이미 닿음: ${p.every_s ? "1분 안에" : "다음 30분봉 마감 때"} 옮겨요` : s;
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
    // owners 10-26: the second rule's rows say whose they are (the friend's rows read as before)
    const what = `${x.coin} ${x.rule === "st" || x.rule === "srsi" ? `${x.rule_ko} ` : ""}${x.colour_ko}`;
    if (x.stage === "entered") {
      return {head: `${what}${want}`, pill: o.adopted ? "진입 (늦게 확인)" : "진입", tone: "good",
        text: [`체결 ${fmt.price(o.entry)} · ${fmt.num(o.qty, 4)}개 · 손절 ${fmt.price(o.stop)}`, vals].filter(Boolean).join(" · ")};
    }
    if (x.stage === "skipped") return {head: `${what}${want}`, pill: `건너뜀 · ${o.group_ko}`, tone: o.tone || "thin", text: [o.why, vals].filter(Boolean).join(" · ")};
    if (x.stage === "refused") return {head: what, pill: "진입 안 함", tone: "thin", text: [x.why, vals].filter(Boolean).join(" · ")};
    return {head: `${what}${want}`, pill: "결과 기록 없음", tone: "thin", text: vals};
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
/** The signal's numbers: "30분 평균 RSI 61.2 · 1시간 평균 RSI 55.0 · 종가 0.0812 · 손절 폭 1.23%" (the second rule:
 *  "스톡RSI K 30.1 / D 25.2 · 30분 RSI26 56.0 · 1시간 RSI26 54.0 · MOM 0.0042 · 종가 … · 손절 폭 …"; MOM since 10-27). */
export function valsKo(v) {
  if (!v) return "";
  return [trendKo(v), ok(v.ersi) ? `EMA RSI ${fmt.num(v.ersi, 1)}` : null, ok(v.roc) ? `ROC ${fmt.num(v.roc, 1)}` : null, ok(v.obv50) ? `OBV 50선 ${fmt.num(v.obv50, 1)}` : null, acVal(v), ok(v.avg_rsi_30m) ? `30분 평균 RSI ${fmt.num(v.avg_rsi_30m, 1)}` : null, ok(v.avg_rsi_1h) ? `1시간 평균 RSI ${fmt.num(v.avg_rsi_1h, 1)}` : null,
    ok(v.k) && ok(v.d) ? `스톡RSI K ${fmt.num(v.k, 1)} / D ${fmt.num(v.d, 1)}` : null,
    ok(v.rsi26_30m) ? `30분 RSI26 ${fmt.num(v.rsi26_30m, 1)}` : null, ok(v.rsi26_1h) ? `1시간 RSI26 ${fmt.num(v.rsi26_1h, 1)}` : null,
    ok(v.mom) ? `MOM ${fmt.price(v.mom)}` : null,
    ok(v.close) ? `종가 ${fmt.price(v.close)}` : null, ok(v.stop_pct) ? `손절 폭 ${fmt.num(v.stop_pct, 2)}%` : null].filter(Boolean).join(" · ");
}
const RULE_KO = {mix: "친구 매매법", st: "슈퍼트렌드·스톡RSI", obv: "OBV 진한색", srsi: "스톡RSI 50선", obv50: "OBV 50선", roc50: "ROC 50선",
  ema3: "추세 3개 일치", obvac: "OBV 진한색 + AC"};
/** OBV MACD's AC bar (owners 10-31 evening): "AC 플러스 양봉 0.42". */
const acVal = (v) => (ok(v.ac) ? `AC ${Number(v.ac) > 0 ? "플러스" : Number(v.ac) < 0 ? "마이너스" : "0"} ${Number(v.ac_col) > 0 ? "양봉" : Number(v.ac_col) < 0 ? "음봉" : "보합"} ${fmt.num(v.ac, 2)}` : null);
const E3_KO = {ema: ["EMA RSI", {1: "초록", "-1": "빨강", 0: "50"}], line: ["하늘·보라 선", {1: "하늘", "-1": "보라"}],
  st: ["슈퍼트렌드", {1: "상승", "-1": "하락", 0: "횡보"}]};
const TREND_KO = {1: "상승", "-1": "하락", 0: "진입 금지"}, VOTE_KO = {1: "상승", "-1": "하락", 0: "횡보"};
const VOTES = [["line", "하늘·보라 선"], ["ema", "EMA RSI"], ["chop", "찹존"], ["st", "슈퍼트렌드"]];
/** The 바이비트 봇's trend of the bar in words (owners 10-29): "친구 추세 상승 (하늘·보라 선 상승 · EMA RSI 상승 · 찹존 횡보 ·
 *  슈퍼트렌드 상승)"; null without one (the friend bot's rows). */
export function trendKo(v) {
  if (v && v.e3_votes && typeof v.e3_votes === "object") {   // owners 10-31: 추세 3개 일치's own three trends
    const vs = Object.entries(E3_KO).filter(([k]) => v.e3_votes[k] != null).map(([k, [ko, m]]) => `${ko} ${m[Number(v.e3_votes[k])] || "?"}`);
    return `추세 ${{1: "3개 상승", "-1": "3개 하락"}[Number(v.e3_trend)] || "진입 금지"}${vs.length ? ` (${vs.join(" · ")})` : ""}`;
  }
  if (!v || v.trend == null || !Number.isFinite(Number(v.trend))) return null;
  const swing = v.trend_mode === "swing";             // owners 10-30: the friend bot's (line + chop / supertrend sideways)
  const vs = v.votes && typeof v.votes === "object" ? VOTES.filter(([k]) => v.votes[k] != null && !(swing && k === "ema"))
    .map(([k, ko]) => `${ko} ${VOTE_KO[Number(v.votes[k])] || "?"}`) : [];
  const head = swing ? `추세 ${{1: "롱 가능", "-1": "숏 가능", 0: "진입 금지"}[Number(v.trend)] || "?"}` : `친구 추세 ${TREND_KO[Number(v.trend)] || "?"}`;
  return `${head}${vs.length ? ` (${vs.join(" · ")})` : ""}`;
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
function botHead(b, now, o = MIX_UI) {
  const s = statusOf(b, now);
  return h("div", {class: ["lmx-bhead", s.cls]},
    h("div", {class: "lmx-orb", "aria-hidden": "true"}, h("i")),
    h("div", {class: "lmx-bmain"},
      h("p", {class: "lmx-kick"}, b.real ? o.kick : "연습 · 같은 신호, 주문 없음 · 진짜 돈 아님"),
      h("h2", {class: "lmx-bname"}, botKo(b.id, o) || b.ko, " ", ui.pill(s.pill, s.tone, `서버 서비스 ${b.unit}`)),
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
/** mixView(ctx, o) -> {el, set()}: the two bots now (module comment); ``o``: which mix bot (MIX_UI, BYBIT_UI). */
export function mixView(ctx, o = MIX_UI) {
  const st = {d: null, okAt: 0, busy: false, ticks: [], feed: local.get("lmx-feed" + o.key, "live"), feedN: FEED_PAGE};
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
        b.real ? `봇이 ${o.exchange}에서 읽어 기록한 마지막 잔고 (지금 거래소 값은 앱에서)` : "모의 잔고 (주문 없음)"));
    } else items.push(tile(b.real ? "실거래 잔고" : "모의 잔고", "수집 전", e.none_ko || "", "na"));
    // owners 10-27 ("친구봇 돈 움직이는것도 안뜨고"): with a position open, the balance read at its entry plus the position at the
    // page's mark (before the exit fee), redrawn with the ticker
    const p = b.position && b.position.state === "ok" ? b.position : null;
    const mk = p ? store.mark(p.symbol) : null;
    const u = p && ok(mk) && ok(p.entry) && ok(p.qty) ? Number(p.side) * Number(p.qty) * (Number(mk) - Number(p.entry)) : null;
    if (u != null && n && ok(n.value) && (n.from === "entry" || n.from === "adopted")) {
      items.push(tile("지금 어림 잔고", usdKo(Number(n.value) + u), `진입 때 잔고 + 평가 ${pnlKo(u)} · 마크 ${fmt.price(mk)}`, b.real ? "real" : "paper",
        "진입 때 읽은 잔고에 열린 포지션의 평가 손익(바이낸스 마크 가격, 나갈 때 수수료 전)을 더한 어림값 · 정확한 값은 앱에서"));
    }
    items.push(tile("시작 잔고", usdKo(e.start), ok(e.change) ? `지금까지 ${pctKo(e.change)}${b.real ? "" : " (모의)"}` : "", b.real ? "" : "paper"));
    const floorOn = Number(e.floor_frac) > 0;            // the 바이비트 봇 (owners 10-29): no floor
    items.push(floorOn ? tile(`바닥선 (시작의 ${rateKo(e.floor_frac, 0)})`, usdKo(e.floor),
      e.below ? "아래로 내려감 → 새 진입 멈춤" : ok(e.room) ? `남은 여유 ${usdKo(e.room)}` : "아래로 가면 새 진입을 멈춰요", e.below ? "bad" : "")
      : tile("바닥선", "없음", "잔고가 줄어도 새 진입을 멈추지 않아요 (두 분 결정)"));
    const frac = ok(n && n.value) && ok(e.start) && Number(e.start) > 0 ? Math.max(0, Math.min(1, Number(n.value) / Number(e.start) / 1.5)) : null;
    return [h("div", {class: "lmx-money", role: "list", "aria-label": b.real ? "실거래 잔고" : "모의 잔고"}, items),
      frac == null ? null : h("div", {class: ["lmx-meter", e.below ? "bad" : ""], role: "img", "aria-label": "잔고와 바닥선"},
        h("i", {style: {"--v": frac.toFixed(4)}}), floorOn ? h("b", {style: {"--m": (Number(e.floor_frac) / 1.5).toFixed(4)}}) : null,
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
        h("p", null, o.wait));
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
          h("small", {class: "lmx-sub"}, p.every_s ? ` (바이낸스 1분봉 고가·저가, ${fmt.int(p.every_s)}초마다 반영)` : " (30분봉 고가·저가, 마감 때 반영)")),
        h("dt", null, "다음 계단"), h("dd", {class: ["num", p.next && p.next.reached ? "warn" : ""]}, ladderKo(p)),
        roe != null ? h("dt", null, "지금 가격") : null,
        roe != null ? h("dd", {class: "num"}, `${fmt.price(mark)} · ROE `, h("span", {class: fmt.tone(roe)}, pctKo(roe, 0)),
          h("small", {class: "lmx-sub"}, " (바이낸스 가격, 수수료 전 · 참고)")) : null,
        h("dt", null, "신호 봉"), h("dd", {class: "num"}, `${fmt.kst(p.signal_close_ms)} 마감 · 종가 ${fmt.price(p.signal_close)}`)),
      p.stop_id_missing ? h("p", {class: "lmx-warn"}, `상태 파일에 손절 주문 번호가 없어요 · 봇이 5분마다 손절을 확인해요 · ${o.exchange} 앱에서도 확인하세요`) : null,
      h("p", {class: "lmx-sub"}, p.ladder_basis === "net"
        ? `계단(순ROE, 수수료 뺀 값): 가장 유리했던 가격이 순ROE ${pctKo(p.roe_act, 0)} (${fmt.price(p.first_act_price)})에 닿으면 손절을 순ROE ${pctKo(p.lock_roe, 0)} (${fmt.price(p.first_lock_price)})로, 그 뒤 ${pctKo(p.ladder_step, 0)}마다 한 칸 · ${p.every_s ? `${fmt.int(p.every_s)}초마다 1분봉으로` : "30분봉 마감 때"} 옮겨요`
        : `계단: 가장 유리했던 가격이 ROE ${pctKo(p.roe_act, 0)} (${fmt.price(p.first_act_price)})에 닿으면 손절을 ROE ${pctKo(p.lock_roe, 0)} (${fmt.price(p.first_lock_price)})로, 그 뒤 같은 폭씩 · 30분봉 마감 때만 옮겨요`));
  }
  function botCol(b) {
    const now = serverNow();
    const s = (b.status || {}).state;
    const kids = [botHead(b, now, o)];
    if (s === "off") kids.push(offBox(b));
    else {
      if (s === "error") kids.push(sourceState({state: "error", reason_ko: b.status.reason_ko, reason: b.status.reason}, "상태 파일"));
      kids.push(...moneyBox(b), haltBox(b), h("h3", {class: "lmx-h3"}, "포지션"), posBox(b));
      if ((b.setup_bad || []).length) kids.push(h("p", {class: "lmx-warn"}, `마지막 시작 때 설정 실패: ${b.setup_bad.join(" · ")} (그 코인은 거래 안 함)`));
      kids.push(...fileNotes(b));
    }
    return h("section", {class: ["lmx-bot", b.id, (STATUS[s] || [])[2] || "err"], "aria-label": botKo(b.id, o) || b.ko}, kids);
  }
  function drawBots() {
    st.ticks = [];
    put(botsBox, (st.d.bots || []).map(botCol));
  }
  function drawFeed() {
    const bots = st.d.bots || [];
    const b = bots.find((x) => x.id === st.feed) || bots[0];
    put(feedHead, ui.seg(bots.map((x) => ({id: x.id, label: x.id === "live" ? "실거래" : "모의"})), b ? b.id : "",
      (id) => { st.feed = id; st.feedN = FEED_PAGE; local.set("lmx-feed" + o.key, id); drawFeed(); }, {label: "어느 봇"}),
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
  poller(ctx, o.api, REFRESH_MS, st, slot, main, draw);
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
/** A luck-band row (paperbot/mixcheck.py band) in words: {head, pill, tone, text}. */
export function bandRowKo(x) {
  const pTxt = ok(x.p) ? `이만큼 나쁘거나 더 나빴던 때 ${rateKo(x.p, 0)}` : "";
  return {head: `${x.ko} ${x.live}`, pill: x.verdict_ko || "참고", tone: x.tone || "thin",
    text: [x.range, pTxt, x.why].filter(Boolean).join(" · ")};
}
const CARD_PILL = {normal: "설계대로", abnormal: "설계보다 큰 손실", very_abnormal: "설계보다 아주 큰 손실", unknown: "손익 모름", win: "익절"};
/** A loss card (or a win's line) in words: {head, pill, tone, lines, causes, win}. */
export function cardKo(c) {
  const head = `${c.coin || ""} ${c.side_ko || ""}`.trim();
  if (c.verdict === "win") {
    const tw = c.twin && c.twin.state === "closed" && ok(c.twin.r) ? ` · 모의 ${fmt.num(c.twin.r, 2, true)}R` : "";
    return {head, pill: c.ko || "익절", tone: "good", win: true, causes: [],
      lines: [`${fmt.kst(c.opened_ms)} → ${fmt.kst(c.exit_ms)} (${holdKo(c.hold_ms)}) · ${pnlKo(c.pnl)}${ok(c.r) ? ` (${fmt.num(c.r, 2, true)}R)` : ""}${tw}`]};
  }
  const bad = c.verdict === "abnormal" || c.verdict === "very_abnormal";
  return {head, pill: CARD_PILL[c.verdict] || c.ko || "손실", tone: bad ? "bad" : c.verdict === "unknown" ? "warn" : "thin", win: false,
    lines: (c.lines || []).filter(Boolean), causes: (c.causes || []).map((x) => x.ko).concat(c.notes || []).filter(Boolean),
    causesHead: bad ? "이유 후보" : "참고"};
}
/** The last morning check in lines (paperbot/mixcheck.py last-morning.json). */
export function morningKo(m) {
  if (!m || m.state !== "ok") return {pill: m && m.state === "error" ? "못 읽음" : "아직 없음", tone: m && m.state === "error" ? "bad" : "thin", lines: [(m && m.ko) || "아침 점검 기록이 아직 없어요"]};
  const d = m.d || {};
  const rp = d.replay || null;
  const lines = [];
  if ((d.warn || []).length) lines.push(...d.warn.map((x) => `확인할 것: ${x}`));
  const s = d.signals || {};
  lines.push(`색 변화 ${fmt.int(s.changes || 0)}번${s.crosses != null ? ` · 스톡RSI 크로스 ${fmt.int(s.crosses)}번` : ""} · 조건 맞은 신호 ${fmt.int(s.signals || 0)}번 · 진입 ${fmt.int(s.entries || 0)}번`);
  if (!rp) lines.push("신호 다시 계산: 건너뜀");
  else if (rp.state !== "ok") lines.push(`신호 다시 계산: ${rp.ko || "못 함"}`);
  else {
    lines.push(`놓친 신호 ${fmt.int((rp.missed || []).length)}개 (바이낸스 봉으로 봇 공식을 다시 계산 · 색 변화 ${fmt.int(rp.changes || 0)}번`
      + `${rp.crosses != null ? ` · 스톡RSI 크로스 ${fmt.int(rp.crosses)}번` : ""})`);
    for (const x of (rp.missed || []).slice(0, 6)) lines.push(`· ${fmt.kst(x.close_ms)} ${x.coin} ${SIDE(x.side)}${x.rule === "st" ? `(${RULE_KO.st})` : ""}: ${x.ko}`);
    if ((rp.different || []).length) lines.push(`판정이 다른 봉 ${fmt.int(rp.different.length)}개`);
    if ((rp.unexplained || []).length) lines.push(`이유 없이 안 들어간 신호 ${fmt.int(rp.unexplained.length)}개`);
  }
  const vs = d.vs_paper || {};
  if (vs.state === "ok") lines.push(`모의와 같은 진입 ${fmt.int(vs.same || 0)}번${(vs.diffs || []).length ? ` · 다른 것 ${fmt.int(vs.diffs.length)}개` : " · 다른 것 없음"}`);
  for (const x of (vs.diffs || []).slice(0, 4)) lines.push(`· ${x.ko}`);
  return {pill: d.level === "WARN" ? `확인할 것 ${fmt.int((d.warn || []).length)}개` : "이상 없음", tone: d.level === "WARN" ? "warn" : "good",
    day: d.day || "", lines};
}
/** The design's numbers next to the replay of the bot's own code, per coin: [coin, design, replay at 0.042 %, at 0.02 %]. */
export function designRows(ds) {
  return ((ds && ds.rows) || []).map((r) => ({coin: r.coin, design: `${pctKo(r.design_month, 2)} · 승률 ${rateKo(r.design_win, 0)}`,
    replay: `${pctKo(r.month, 2)} · 승률 ${rateKo(r.win, 0)}`, replay02: ok(r.month_fee02) ? pctKo(r.month_fee02, 2) : "—",
    neg: ok(r.neg_months) ? `${fmt.int(r.neg_months)}/60` : "—"}));
}

/** The backtest table's rows with each bot's own numbers per coin beside them. */
export function compareCoins(bt, bots) {
  const of = (id, sym) => ((bots.find((b) => b.id === id) || {}).coins || []).find((c) => c.symbol === sym) || null;
  const cell = (c) => (c && c.n ? `${fmt.int(c.n)}번 · 승률 ${rateKo(c.win_rate, 0)} · ${pnlKo(c.pnl)}` : "아직 없음");
  return ((bt && bt.rows) || []).map((r) => ({symbol: r.symbol, coin: fmt.coin(r.symbol), month: pctKo(r.month, 2), win: rateKo(r.win, 0),
    live: cell(of("live", r.symbol)), paper: cell(of("paper", r.symbol)), small: [of("live", r.symbol), of("paper", r.symbol)].some((c) => c && c.n && c.small)}));
}

/** mixperfView(ctx, o) -> {el, set()}: 성적 (module comment); ``o``: which mix bot (MIX_UI, BYBIT_UI). */
export function mixperfView(ctx, o = MIX_UI) {
  const st = {d: null, okAt: 0, busy: false, acct: local.get("lmx-trades" + o.key, "live"), tn: TRADES_PAGE, cn: TRADES_PAGE};
  const slot = h("div", {class: "lb-slot"});
  const recBox = h("div", {class: "lmx-bots"});
  const btBox = h("div", {class: "lmx-bt"});
  const tradeHead = h("div", {class: "lmx-feedhead"});
  const tradeBox = h("div", {class: "lmx-trades"});
  const rulesBox = h("div", {class: "lmx-bots"});
  const bandBox = h("div", {class: "lmx-band"});
  const morningBox = h("div", {class: "lmx-morning"});
  const lossBox = h("div", {class: "lmx-loss"});
  const twinBox = h("div", {class: "lmx-twin"});
  const btCard = ui.card({title: "설계서 5년 백테스트와 나란히", sub: "왼쪽 두 칸은 설계서 숫자 (실거래 아님) · 오른쪽은 이 봇들의 실제 기록", cls: "lmx-btcard"}, btBox);
  const cards = h("div", {class: "lmx-cards"}, recBox,
    ui.card({title: "실거래 vs 모의", sub: "같은 신호를 받는 두 봇 · 차이는 체결 · 수수료 · 놓친 진입 · 모의 칸의 돈은 진짜 돈 아님", cls: "lmx-twincard"}, twinBox),
    ui.card({title: "운이냐 고장이냐", sub: "실거래 기록을 봇 코드 그대로 돌린 5년 재생과 비교 · 이만큼 나쁘거나 더 나빴던 때가 10% 넘으면 정상 범위", cls: "lmx-bandcard"}, bandBox),
    ui.card({title: "손실 카드", sub: `실거래 거래마다 · ${o.plan} · 새것부터 · 텔레그램에도 청산 몇 분 뒤 와요`, cls: "lmx-losscard"}, lossBox),
    ui.card({title: "어제 아침 점검", sub: `매일 ${o.morning} · 신호 다시 계산(바이낸스 봉, 봇 공식)과 모의 비교`, cls: "lmx-morncard"}, morningBox),
    btCard,
    ui.card({title: "거래", sub: "새것부터 · 청산 기록을 진입 기록과 맞춤 · 한국 시간", cls: "lmx-tradecard"}, tradeHead, tradeBox),
    ui.card({title: "규칙", sub: "봇이 읽는 설정 그대로 (서버 설정 파일)", cls: "lmx-rulecard"}, rulesBox));
  const main = h("div", {class: "lmx-body"}, cards);
  const el = h("div", {class: "lmx stack"}, slot, main,
    ui.note("보기만 하는 화면 · 1분마다 새로 읽어요 · 승패는 손익 > 0 기준 · 손익은 진입 때부터 청산 뒤까지 잔고 변화 (수수료 포함) · 모의 칸의 돈은 진짜 돈이 아니에요"));

  function recCard(b) {
    const now = serverNow();
    const s = (b.status || {}).state;
    const kids = [botHead(b, now, o)];
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
      t.signal && (ok(t.signal.avg_rsi_30m) || ok(t.signal.k)) ? h("div", {class: "lmx-sub"},
        `진입 근거${t.signal.rule && RULE_KO[t.signal.rule] ? `(${RULE_KO[t.signal.rule]})` : ""}: ${valsKo(t.signal)}`) : null,
      t.pnl == null ? h("small", {class: "lmx-sub"}, "손익 모름: 청산 뒤 잔고를 읽지 못했어요") : null,
      t.no_entry_row ? h("small", {class: "lmx-sub"}, "진입 기록이 읽은 범위 밖이라 진입 때 값 일부가 비어요") : null);
  }
  function drawTrades() {
    const bots = st.d.bots || [];
    const b = bots.find((x) => x.id === st.acct) || bots[0];
    put(tradeHead, ui.seg(bots.map((x) => ({id: x.id, label: x.id === "live" ? "실거래" : "모의"})), b ? b.id : "",
      (id) => { st.acct = id; st.tn = TRADES_PAGE; local.set("lmx-trades" + o.key, id); drawTrades(); }, {label: "어느 봇"}));
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
    if (!r) return h("section", {class: ["lmx-bot", b.id]}, h("h3", {class: "lmx-h3"}, botKo(b.id, o)), sourceState((b.files || {}).config || {}, "설정 파일"));
    return h("section", {class: ["lmx-bot", b.id]},
      h("h3", {class: "lmx-h3"}, `${botKo(b.id, o)} · ${r.mode === "mainnet" ? "실거래 (mainnet)" : "모의 (paper)"}`),
      r.source === "repo" ? h("p", {class: "lmx-warn"}, r.reason_ko || "서버 설정 파일 대신 저장소 기본 설정이에요") : null,
      h("ul", {class: "lmx-list lmx-rlist"},
        h("li", null, `${r.margin_frac > 0 ? `진입마다 증거금 = 잔고의 ${rateKo(r.margin_frac, 0)}` : `손절 1번 = 잔고의 ${fmt.num(r.risk_pct, 2)}%`} · 한 번에 1포지션 (같은 봉에 겹치면 아래 코인 순서)`),
        h("li", null, `${Number(r.equity_floor_frac) > 0 ? `잔고가 시작의 ${rateKo(r.equity_floor_frac, 0)} 아래면 새 진입 멈춤` : "바닥선 없음 (잔고가 줄어도 새 진입)"} · 한 포지션 최대 ${usdKo(r.max_notional_usd)}`),
        h("li", null, r.ladder
          ? `계단(순ROE, 모든 코인): ${rateKo(r.ladder.trigger, 0)}에 닿으면 손절을 ${rateKo(r.ladder.lock, 0)}로, 그 뒤 ${rateKo(r.ladder.step, 0)}마다 한 칸${r.ladder_every_s ? ` · ${fmt.int(r.ladder_every_s)}초마다 1분봉으로 옮김` : ""} · 반대 신호나 시간으로는 청산 안 함`
          : `계단: 시작 ROE에 닿으면 손절을 ROE ${pctKo(r.lock_roe, 0)}로, 그 뒤 같은 폭씩 · 반대 신호나 시간으로는 청산 안 함`),
        h("li", null, `진입 금지: ${(r.blocks || []).map((x) => `${x.ko} ${x.on ? "켬" : "끔"}`).join(" · ")}`),
        ok(r.start_equity) ? h("li", null, `시작 금액 ${usdKo(r.start_equity)}${r.mode === "paper" ? " (모의)" : ""}`) : null),
      h("div", {class: ["lmx-ctab", o.h1 ? "" : "no-h1"], role: "table", "aria-label": "코인별 설정"},
        h("div", {class: "lmx-ctr lmx-cth", role: "row"}, ["코인", ...(o.h1 ? ["1시간 여유"] : []), "손절 ATR ×", "계단 시작 ROE", "레버리지"].map((x) => h("span", {role: "columnheader"}, x))),
        (r.coins || []).map((c) => h("div", {class: ["lmx-ctr", c.enabled && !c.off_at_start ? "" : "off"], role: "row"},
          h("b", {role: "rowheader"}, c.coin, !c.enabled ? " (꺼짐)" : c.off_at_start ? " (시작 때 꺼짐)" : ""),
          o.h1 ? h("span", {class: "num", role: "cell"}, fmt.num(c.h1_buf, 1)) : null, h("span", {class: "num", role: "cell"}, fmt.num(c.sl_atr, 1)),
          h("span", {class: "num", role: "cell"}, r.ladder ? `${rateKo(r.ladder.trigger, 0)} → ${rateKo(r.ladder.lock, 0)} (순ROE)` : `${rateKo(c.roe_act, 0)} → ${rateKo(r.lock_roe, 0)}`), h("span", {class: "num", role: "cell"}, fmt.lev(c.leverage))))));
  }
  function drawBand(an) {
    const b = an.band || {};
    const kids = [];
    if (b.state === "empty" || b.state === "changed") kids.push(ui.empty(b.ko || "아직 닫힌 실거래가 없어요"));
    else if (b.state === "none") kids.push(ui.empty(b.ko || "이 봇은 5년 재생이 없어 운이냐 고장이냐를 재지 않아요 · 손실 카드와 아침 점검은 그대로예요"));
    else if (b.state === "ok") {
      kids.push(h("div", {class: ["lmx-verdict", b.worst === "very_rare" ? "halt" : b.worst === "rare" ? "block" : "go"]},
        h("b", null, b.ko || ""), h("span", {class: "lmx-sub"}, ` 실거래 ${fmt.int(b.n)}번`)));
      kids.push(h("ul", {class: "lmx-list lmx-blist"}, (b.rows || []).map((x) => {
        const k = bandRowKo(x);
        return h("li", {class: ["lmx-brow", k.tone]}, h("b", {class: "lmx-fhead"}, k.head), ui.pill(k.pill, k.tone), k.text ? h("small", {class: "lmx-sub lmx-why"}, k.text) : null);
      })));
      if (b.model_ko) kids.push(h("p", {class: "lmx-honest"}, b.model_ko));
    } else kids.push(h("p", {class: "lmx-warn"}, "운이냐 고장이냐를 계산하지 못했어요"));
    const ds = an.design;
    if (ds) {
      const lr = ds.live_rules || {}, op = ds.one_position || {};
      kids.push(h("h3", {class: "lmx-h3"}, "설계서 숫자와 5년 재생 (봇 코드 그대로, 코인마다 따로 · 진입 금지 없음)"),
        h("div", {class: "lmx-btab lmx-dtab", role: "table", "aria-label": "설계서와 5년 재생"},
          h("div", {class: "lmx-btr lmx-bth", role: "row"}, ["코인", "설계서 한 달·승률", "재생 (수수료 0.042%)", "재생 (0.02%)", "마이너스 달"].map((x) => h("span", {role: "columnheader"}, x))),
          designRows(ds).map((r) => h("div", {class: "lmx-btr", role: "row"}, h("b", {role: "rowheader"}, r.coin), h("span", {class: "num ref", role: "cell"}, r.design),
            h("span", {class: "num", role: "cell"}, r.replay), h("span", {class: "num", role: "cell"}, r.replay02), h("span", {class: "num", role: "cell"}, r.neg)))),
        h("ul", {class: "lmx-list lmx-rlist"},
          ok(op.trades) ? h("li", null, `여섯 코인 한 번에 1포지션: 1년 약 ${fmt.int(op.per_year)}번 · 승률 ${rateKo(op.win_rate, 0)} · 한 달 평균 ${pctKo(op.month_mean, 2)} · 마이너스 달 ${fmt.int(op.neg_months)}/60`) : null,
          ok(lr.trades) ? h("li", null, `실거래 규칙 그대로 (1포지션 · 진입 금지 시간 · 최소 주문 · $50): 1년 약 ${fmt.int(lr.per_year)}번 · 승률 ${rateKo(lr.win_rate, 0)} · ` +
            `평균 익절 ${fmt.num(lr.avg_win_r, 1, true)}R · 평균 손절 ${fmt.num(lr.avg_loss_r, 1, true)}R · 한 달 평균 ${pctKo(lr.month_mean, 2)} · 가장 긴 연속 손절 ${fmt.int(lr.max_losing_streak)}번 · ` +
            `가장 깊은 낙폭 ${fmt.num(-Number(lr.max_dd_r), 1, true)}R (잔고 ${pctKo(-Number(lr.max_dd_equity), 1)})`) : null),
        h("p", {class: "lmx-sub"}, `재생에 없는 것: ${(ds.not_modelled || []).join(" · ")} · 출처 ${ds.src || ""}`));
    }
    put(bandBox, kids);
  }
  function drawLoss(an) {
    const cs = an.cards || [];
    if (!cs.length) { put(lossBox, ui.empty("닫힌 실거래가 아직 없어요 · 청산되면 몇 분 안에 카드가 생겨요")); return; }
    const n = cs.filter((c) => c.verdict === "abnormal" || c.verdict === "very_abnormal").length;
    const list = h("ul", {class: "lmx-list lmx-clist"}, cs.slice(0, st.cn).map((c) => {
      const k = cardKo(c);
      return h("li", {class: ["lmx-card", k.win ? "win" : k.tone]},
        h("div", {class: "lmx-ttop"}, h("b", null, k.head), ui.pill(k.pill, k.tone), h("b", {class: ["num", "lmx-tpnl", fmt.tone(c.pnl)]}, pnlKo(c.pnl))),
        k.lines.map((ln) => h("div", {class: "lmx-tmeta num"}, ln)),
        k.causes.length ? h("div", {class: "lmx-causes"}, h("span", {class: "lmx-ik"}, k.causesHead), h("ul", {class: "lmx-list"}, k.causes.map((x) => h("li", null, x)))) : null);
    }));
    const more = cs.length > st.cn ? h("button", {class: "btn-line lmx-more", type: "button", onclick: () => { st.cn += TRADES_PAGE; drawLoss(an); }},
      `더 보기 (${fmt.int(cs.length - st.cn)}개 남음)`) : null;
    put(lossBox, h("p", {class: "lmx-sub"}, `거래 ${fmt.int(cs.length)}번 · 설계보다 큰 손실 ${fmt.int(n)}번 · 청산 가격은 봇 기록에 없어 잔고 변화로 거꾸로 계산해요`), list, more);
  }
  function drawMorning(an) {
    const k = morningKo(an.morning);
    put(morningBox, h("div", {class: "lmx-ttop"}, h("b", null, k.day ? `${k.day} (한국 시간 하루)` : "아침 점검"), ui.pill(k.pill, k.tone)),
      h("ul", {class: "lmx-list lmx-rlist"}, k.lines.map((x) => h("li", null, x))),
      h("p", {class: "lmx-sub"}, "트레이딩뷰는 자동으로 읽을 수 없어요 · 이 점검은 봇 공식을 바이낸스 봉으로 다시 계산한 것이고, 차트와 직접 맞춰 보려면 python -m paperbot.mixchop signals"));
  }
  function drawAnalysis() {
    const an = st.d.analysis;
    if (!an || an.state !== "ok") {
      const box = sourceState({state: "error", reason_ko: (an && an.ko) || "손실 분석을 만들지 못했어요", reason: an && an.reason}, "손실 분석");
      put(bandBox, box); put(lossBox); put(morningBox);
      return;
    }
    drawBand(an); drawLoss(an); drawMorning(an);
  }
  /** 실거래 vs 모의: the two records side by side, row by row (recordRows). */
  function drawTwin() {
    const bots = st.d.bots || [];
    const lv = bots.find((b) => b.id === "live"), pp = bots.find((b) => b.id === "paper");
    if (!lv || !pp || !lv.record || !pp.record) { put(twinBox, ui.empty("두 봇 모두 기록이 있어야 나란히 봐요 · 꺼져 있거나 기록을 못 읽은 봇이 있어요")); return; }
    const a = recordRows(lv.record, true), b = recordRows(pp.record, false);
    put(twinBox, h("div", {class: "lmx-btab", role: "table", "aria-label": "실거래와 모의 기록"},
      h("div", {class: "lmx-btr lmx-bth", role: "row"}, ["", "실거래", "모의"].map((x) => h("span", {role: "columnheader"}, x))),
      a.map(([k, v, tone], i) => h("div", {class: "lmx-btr", role: "row"}, h("b", {role: "rowheader"}, k.replace(" (모의)", "")),
        h("span", {class: ["num", tone || ""], role: "cell"}, v), h("span", {class: ["num", (b[i] || [])[2] || ""], role: "cell"}, (b[i] || [])[1] || "—")))),
    h("p", {class: "lmx-sub"}, "모의는 주문을 내지 않고 같은 신호에 같은 규칙으로 들어간 것으로 쳐요 · 승률 차이가 크면 체결 · 놓친 진입을 아침 점검에서 봐요"));
  }
  function draw() {
    const d = st.d;
    if (!d) return;
    put(recBox, (d.bots || []).map(recCard));
    btCard.hidden = !d.backtest;                         // the 바이비트 봇 has no 5-year reference
    drawAnalysis(); drawTwin(); if (d.backtest) drawBt(); drawTrades();
    put(rulesBox, (d.bots || []).map(rulesCard));
  }
  poller(ctx, o.perf, SLOW_MS, st, slot, main, draw);
  return {el, set() {}};
}
