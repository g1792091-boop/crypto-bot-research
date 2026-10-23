// 실거래 › VWAP 봇 (owners 10/23: the second paper bot 'VWAP 개선판', docs/vwap-bot-ko.md, and the executor that will follow
// it; "천천히 작업해도 되니까 완벽하게 … 성공 매매법을 위한 연구 부분이나 분석 부분 필요한 것 다 추가해도 돼"), three tabs of the
// menu group "VWAP 봇" (core/routes.js LIVE_GROUPS), read-only:
//   관제 (#/vwap)       the bot now: running or not, who follows it (since when, its own signal light 20 / 75 %), the open
//                       position with its hold limit counting down (96 bars of its own bar), lock and next lock, net ROE,
//                       the gates it passed and the follower's own position; every coin now (the 4h vote, each signal bar's
//                       ATR% against its 30-day 80 % point, which side a signal could take); the entry pauses; its rules;
//                       its last 48 hours of signals with the bot's reasons and what the gates read
//   성적 (#/vwperf)     the paper and its coin-flip twin side by side (break-even win rate from their own averages, profit
//                       factor, deepest drop, the curves), 실력 vs 운, the scale-up / stop checklist of each follower (its
//                       live trades while it followed this bot only), the research's numbers next to the live ones,
//                       나눠 보기 (strategy, coin, side, the 4h vote and ATR% at the entry, session, exit, hold) and the trades
//   막은 신호 (#/vwblock) its filtered signals by reason (today · 7 days · since its start) and "막지 않았다면": the 1-minute
//                       watcher's virtual results per reason, with the gates' numbers
// Sources: /api/v4/livebots/vwap (every 15 s; countdowns tick every second on the server's clock), /vwperf and /vwblock
// (every 60 s), dash/more/livevwap.py; the real money from the site's summary (/api/v4/livebots, handed in by
// screens/livebots.js). Before the bot runs every tab says so (꺼짐, how to turn it on) and nothing else. HONESTY: unread =
// 못 읽음 + why, never a zero; paper money is never shown as real money; small samples say so; the research's numbers are
// labelled as what they are (the 17 days were picked from that very period; 5 years lost money per trade).
import {h, put, ui, fmt, store, serverNow, local} from "../core/pb.js";
import {sourceState, lightRow} from "./livebots-kit.js";

export const API = "/api/v4/livebots/vwap";
export const PERF_API = "/api/v4/livebots/vwperf";
export const BLOCK_API = "/api/v4/livebots/vwblock";
const REFRESH_MS = 15 * 1000;
const SLOW_MS = 60 * 1000;
const TICK_MS = 1000;
const MIN = 60 * 1000, HOUR = 60 * MIN;
const TRADES_PAGE = 12;
const SIG_PAGE = 20;
const SIDE = (x) => (Number(x) > 0 ? "롱" : "숏");
const ok = (x) => x != null && x !== "" && Number.isFinite(Number(x));
const signedUsd = (x) => (ok(x) ? `${Number(x) >= 0 ? "+" : "−"}${fmt.usd(Math.abs(Number(x)))}` : "—");
const STAGE_TONE = {entered: "good", skipped: "thin", late: "warn", rejected: "warn", filtered: "bad", submitted: "thin", other: "thin"};
const GROUP_TONE = {vote: "bad", vol: "warn", pause: "", unread: "thin", other: "thin"};
const CHECK_KO = {ok: "충족", no: "아직 아님", wait: "기다림", info: "참고", bad: "본전 아래"};
const CHECK_TONE = {ok: "good", no: "bad", wait: "thin", info: "accent", bad: "bad"};
const UNIT = "paperbot-combo-vwap";

// ---------------------------------------------------------------- pure (node tests: tests/test_dash_livevwap.py)
/** "31시간 20분" / "45분" / "0분" (ms). */
export function holdKo(ms) {
  if (!ok(ms)) return "—";
  const m = Math.max(0, Math.floor(Number(ms) / MIN));
  if (m < 60) return `${m}분`;
  return `${Math.floor(m / 60)}시간${m % 60 ? ` ${m % 60}분` : ""}`;
}
/** "+12.1%" / "−4.3%" of a ratio (fmt.pct; "—" for unknown). */
export const pctKo = (x, d = 1) => fmt.pct(x, d, true);
/** "71.4%" (no sign). */
export const rateKo = (x, d = 1) => (ok(x) ? fmt.pct(x, d, false) : "—");
/** The hero of 관제: {cls, head, sub} (stop / hold / pause / go / na). */
export function heroOf(d, now) {
  if (!d || d.state !== "ok") return {cls: "na", head: "VWAP 개선판", sub: ""};
  const b = d.bot || {};
  if (b.running === false || b.stale) {
    return {cls: "stop", head: "VWAP 개선판 기록이 멈췄어요",
      sub: `${b.heartbeat_ms ? `마지막 기록 ${fmt.kst(b.heartbeat_ms)} · ` : ""}5분 넘게 새 기록이 없어요 · 서버에서 systemctl status ${UNIT}`};
  }
  const p = d.position;
  if (p) return {cls: "hold", head: `${fmt.coin(p.symbol)} ${SIDE(p.side)} 보유 중`, sub: `${p.strategy_ko} · ${leftKo(p, now)}`};
  const pz = (d.pause || {}).now || {};
  if (pz.paused) {
    return {cls: "pause", head: pz.ko || "진입 쉬는 시간",
      sub: ok(pz.until) ? `${fmt.kst(pz.until)}까지 (${holdKo(Number(pz.until) - now)} 남음)` : ""};
  }
  const open = openSides(d.picture);
  return {cls: "go", head: "진입 가능 · 신호를 기다리는 중",
    sub: open === null ? "코인별 그림이 아직 없어요" : open.length ? `지금 들어갈 수 있는 쪽: ${open.join(" · ")}` : "지금은 모든 코인이 막혀 있어요 (아래 지금 코인별)"};
}
/** The hold limit's countdown in words (the answer's deadline against ``now``). */
export function leftKo(p, now) {
  if (!p || !ok(p.deadline_ms)) return "보유 한도 없음";
  const left = Number(p.deadline_ms) - Number(now);
  return left > 0 ? `보유 한도까지 ${holdKo(left)}` : "보유 한도 지남 · 다음 1분에 정리";
}
/** The coins and sides a signal could take now from the picture: ["BTC 30분 롱", "SOL 1시간 롱·숏", ...]; null without one. */
export function openSides(pic) {
  if (!pic || pic.state !== "ok") return null;
  const out = [];
  for (const r of pic.rows || []) {
    for (const x of r.sides || []) {
      const sides = [x.long && x.long.ok ? "롱" : null, x.short && x.short.ok ? "숏" : null].filter(Boolean);
      if (sides.length) out.push(`${fmt.coin(r.symbol)} ${fmt.tfKo(x.tf)} ${sides.join("·")}`);
    }
  }
  return out;
}
/** A side cell's tone: "both" (롱·숏) / "long" / "short" / "none" (막힘) / "unread". */
export function sideTone(x) {
  if (!x) return "none";
  if (x.unread) return "unread";
  const l = x.long && x.long.ok, sh = x.short && x.short.ok;
  return l && sh ? "both" : l ? "long" : sh ? "short" : "none";
}
/** The ATR meter: {fill 0..1 over 0..1.5 of the 80 % point, mark (the point at 1.0), high}. */
export function atrMeter(v) {
  if (!v || v.error || !ok(v.ratio)) return {fill: 0, mark: 1 / 1.5, high: false, na: true};
  return {fill: Math.max(0, Math.min(1, Number(v.ratio) / 1.5)), mark: 1 / 1.5, high: !!v.high, na: false};
}
/** A virtual (or paper) result in words: "✅ +12.1% 계단 익절" / "❌ −43.0% 손절" / "진행 중 −5.0%" / "1분봉 없음". */
export function resultKo(r) {
  if (!r) return "—";
  if (r.state === "closed") return `${r.win ? "✅" : "❌"} ${pctKo(r.roe)} ${r.reason_ko || ""}`.trim();
  if (r.state === "open") return `진행 중 ${pctKo(r.roe)}`;
  return r.state_ko || r.state || "—";
}
/** One live cell of the trades table: {tone, ko}. */
export function liveCellKo(c) {
  if (!c) return {tone: "", ko: "—"};
  if (c.state === "matched") return {tone: fmt.tone(c.roe), ko: `${pctKo(c.roe)}${c.est ? " (어림)" : ""}`};
  if (c.state === "other") return {tone: "", ko: "다른 페이퍼"};
  if (c.state === "before") return {tone: "", ko: "시작 전"};
  if (c.state === "open") return {tone: "", ko: "닫는 중"};
  if (c.state === "unknown") return {tone: "", ko: "못 읽음"};
  return {tone: "warn", ko: "안 따라감"};
}

// ---------------------------------------------------------------- shared parts
function offBox(d) {
  return h("div", {class: "lvw-off", role: "status"},
    h("div", {class: "lvw-offhead"}, ui.pill("꺼짐", "thin"), h("b", null, (d && d.reason_ko) || "VWAP 개선판 페이퍼 봇이 아직 꺼져 있어요")),
    d && d.other_ko ? h("p", null, d.other_ko) : null,
    h("p", null, "켜면 이 탭에 봇의 지금 상태 · 포지션 · 코인별 진입 조건 · 신호 · 성적 · 막은 신호가 보여요. 켜는 순서: docs/vwap-bot-ko.md 5장 B (돈·주문 없음)."),
    h("p", {class: "lvw-sub"}, "실행기 하나를 옮기는 건 그다음 (5장 C) · 남은 실행기는 그대로 추세판단 봇을 따라가요"));
}
/** The state slot of a tab: 꺼짐 / 수집 전 / 못 읽음, or nothing when the answer is ok. */
function stateOf(d) {
  if (!d || d.state === "ok") return null;
  if (d.state === "off") return offBox(d);
  return sourceState(d, "VWAP 개선판");
}
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
    ui.dim(main, false);
    st.d = d; st.okAt = Date.now();
    draw();
  }
  load().catch(() => {});
  ctx.every(every, () => load().catch(() => {}), {now: false});
  return load;
}
function gatesLine(g, o = {}) {
  if (!g) return o.none === false ? null : h("span", {class: "lvw-sub"}, "조건 기록 없음");
  const v = g.vote, x = g.vol;
  return h("span", {class: "lvw-gates"},
    v ? h("span", {class: ["lvw-gv", v.with_side === 1 ? "up" : v.with_side === -1 ? "down" : "hold"], title: v.text || ""},
      `4시간 ${v.word || "?"}`, ok(v.up) ? ` (상승 ${v.up}·하락 ${v.down}·중립 ${v.neutral})` : "") : null,
    x ? h("span", {class: ["lvw-gx", ok(x.ratio) && x.ratio > 1 ? "high" : ""], title: x.text || ""},
      `${fmt.tfKo(x.tf)} ATR ${fmt.pctOf(x.atr_pct, 2)} / 80% 위치 ${x.q_pct == null ? "모름" : fmt.pctOf(x.q_pct, 2)}`,
      ok(x.ratio) ? ` (${Number(x.ratio).toFixed(2)}배)` : "") : null);
}
function moneyTile(k, v, sub, cls, title) {
  return h("div", {class: ["lvw-tile", cls || ""], role: "listitem", title},
    h("span", {class: "lvw-tk"}, k), h("b", {class: "lvw-tv num"}, v), sub ? h("span", {class: "lvw-ts"}, sub) : null);
}
function follower(d) {
  return (d && d.followers || []).filter((f) => f.state === "following");
}

// ================================================================ 관제 (#/vwap)
/** vwapView(ctx, hub) -> {el, set(summary)}: the VWAP bot now (module comment). */
export function vwapView(ctx, hub) {
  const st = {d: null, s: null, okAt: 0, busy: false, ticks: [], sigN: SIG_PAGE};
  const slot = h("div", {class: "lb-slot"});
  const head = h("h2", {class: "lvw-head"}, "불러오는 중");
  const sub = h("p", {class: "lvw-hsub"});
  const chips = h("div", {class: "lvw-chips"});
  const money = h("div", {class: "lvw-money", role: "list", "aria-label": "지갑"});
  const hero = h("section", {class: "lvw-hero na", "aria-label": "지금"},
    h("div", {class: "lvw-orb", "aria-hidden": "true"}, h("i")),
    h("div", {class: "lvw-hmain"}, h("p", {class: "lvw-kick"}, "VWAP 개선판 · 페이퍼(연습) · VWAP 복귀 실패 30분 + CMO·샌드위치 캔들 1시간"), head, sub, chips),
    money);
  const posBox = h("div", {class: "lvw-pos"});
  const folBox = h("div", {class: "lvw-fol"});
  const coinBox = h("div", {class: "lvw-coins"});
  const stamp = h("span", {class: "lvw-stamp"});
  const pauseBox = h("div", {class: "lvw-pause"});
  const rulesBox = h("div", {class: "lvw-rules"});
  const sigHead = h("div", {class: "lvw-chiprow"});
  const sigBox = h("div", {class: "lvw-sigs"});
  const cards = h("div", {class: "lvw-cards"},
    h("div", {class: "lvw-two lvw-top"},
      ui.card({title: "포지션", sub: "페이퍼(연습) · 손절 2 ATR · 계단 익절 · 자기 봉 96개 보유 한도", cls: "lvw-poscard"}, posBox),
      ui.card({title: "따라가는 실행기", sub: "실행기 시작 기록으로 봐요 · 신호등은 그 실행기 설정의 기준", cls: "lvw-folcard"}, folBox)),
    ui.card({title: "지금 코인별", sub: "4시간 판단 3개 이상 반대면 그쪽 진입 안 함 · 신호 봉 ATR%가 지난 30일 80% 위치보다 크면 진입 안 함",
      cls: "lvw-coincard", acts: [stamp]}, coinBox),
    h("div", {class: "lvw-two"},
      ui.card({title: "진입 쉬는 시간", sub: "봇 설정 그대로 · 열린 포지션은 그대로 가요", cls: "lvw-pausecard"}, pauseBox),
      ui.card({title: "규칙", sub: "봇이 지금 쓰는 설정 (시작 기록 그대로)", cls: "lvw-rulecard"}, rulesBox)),
    ui.card({title: "최근 신호 (48시간)", sub: "봇이 남긴 이유와 조건 숫자 그대로 · 한국 시간", cls: "lvw-sigcard"}, sigHead, sigBox));
  const main = h("div", {class: "lvw-body"}, hero, cards);
  const el = h("div", {class: "lvw stack"}, slot, main,
    ui.note("보기만 하는 화면 · 이 화면은 15초마다 새로 읽어요 · 남은 시간은 1초마다 줄어요 · 코인별 그림은 봇이 30분봉이 끝날 때마다 2분 뒤에 그려요"));

  const tick = (node, until, f) => { st.ticks.push({node, until: Number(until), f}); node.textContent = f(Number(until) - serverNow()); return node; };

  function drawHero() {
    const d = st.d, now = serverNow();
    const x = heroOf(d, now);
    hero.className = `lvw-hero ${x.cls}`;
    head.textContent = x.head;
    sub.textContent = x.sub;
    if (!d || d.state !== "ok") { put(chips); return; }
    const b = d.bot || {}, fol = follower(d);
    const pic = d.picture || {};
    put(chips,
      ui.pill(b.running ? `돌고 있음 · 기록 ${fmt.dur((b.age_ms || 0) / 1000)} 전` : "기록 멈춤", b.running ? "good" : "bad", `서버 서비스 ${UNIT}`),
      ok(b.since_ms) ? ui.pill(`처음 켬 ${fmt.kst(b.since_ms)}`, "thin") : null,
      ok(b.started_ms) && b.started_ms !== b.since_ms ? ui.pill(`마지막 시작 ${fmt.kst(b.started_ms)}`, "thin") : null,
      fol.length ? ui.pill(`따라감: ${fol.map((f) => `${f.name_ko} (${fmt.kst(f.since_ms)}부터)`).join(", ")}`, "accent")
        : ui.pill(d.no_follower_ko || "아직 따라가는 실행기 없음 (페이퍼만)", "warn"),
      pic.state === "ok" ? ui.pill(`코인별 그림 ${fmt.hm(pic.at)}${pic.stale ? " · 오래됨" : ""}`, pic.stale ? "warn" : "thin") : null);
  }
  function drawMoney() {
    const d = st.d;
    const items = [];
    const accts = (st.s && st.s.accts) || [];
    for (const f of follower(d)) {
      const a = accts.find((x) => x.id === f.id);
      if (!a) continue;
      if (a.state !== "ok") { items.push(moneyTile(`${f.name_ko} 실거래`, "못 읽음", a.reason_ko || "", "na")); continue; }
      const td = a.today || {};
      items.push(moneyTile(`${f.name_ko} 실거래 (VWAP)`, ok(a.balance) ? fmt.usd(a.balance) : "—",
        `오늘 ${ok(td.pnl) ? signedUsd(td.pnl) : "—"} · ${fmt.int(td.trades || 0)}번${a.halted ? " · 멈춤" : ""}${a.stale ? " · 기록 오래됨" : ""}`,
        a.halted ? "bad" : "", "거래소 실제 잔고 (실행기 기록)"));
    }
    const ac = d && d.state === "ok" ? d.account || {} : null;
    if (ac && ac.state === "ok") {
      items.push(moneyTile("페이퍼(연습) 지갑", fmt.usd(ac.wallet), `시작 ${fmt.usd(ac.initial)} 대비 ${pctKo(ac.change)} · 진짜 돈 아님`, "paper"));
      items.push(moneyTile("VWAP 개선판 성적", ac.n ? `${fmt.int(ac.wins)}승 ${fmt.int(ac.losses)}패` : "아직 거래 없음",
        ac.n ? `승률 ${rateKo(ac.win_rate)} · 순ROE 합 ${pctKo(ac.roe_sum)}${ac.n < 20 ? " · 표본 적음" : ""}` : "첫 거래가 닫히면 채워져요", "rec"));
    } else if (ac) items.push(moneyTile("페이퍼(연습) 지갑", "수집 전", ac.reason_ko || "", "na"));
    put(money, items);
  }
  function followerPos(p) {
    const fol = follower(st.d);
    if (!fol.length) return h("p", {class: "lvw-sub lvw-real"}, "따라가는 실행기가 없어 이 포지션의 손익은 페이퍼(연습)에만 남아요");
    return h("ul", {class: "lvw-list"}, fol.map((f) => {
      const q = f.position;
      if (f.record && f.record.state !== "ok") return h("li", null, h("b", null, `${f.name_ko} `), "실행기 기록 못 읽음");
      if (!q) return h("li", null, h("b", null, `${f.name_ko} `), f.record && f.record.halted ? "포지션 없음 · 멈춤" : "포지션 없음 (이 진입을 안 따라갔거나 이미 닫음)");
      const same = p && q.key === p.key;
      const mark = store.mark(q.symbol);
      const m = ok(mark) ? Number(mark) : p && same && ok(p.mark) ? Number(p.mark) : null;
      const roe = m != null && ok(q.entry) && ok(q.leverage) ? Number(q.leverage) * Number(q.side) * (m / Number(q.entry) - 1) : null;
      return h("li", null, h("b", null, `${f.name_ko} `), same ? "같은 포지션 · " : "다른 포지션 · ",
        `${fmt.coin(q.symbol)} ${SIDE(q.side)} ${fmt.lev(q.leverage)} · 진입 ${fmt.price(q.entry)}`,
        roe != null ? h("span", {class: ["num", fmt.tone(roe)]}, ` · ROE ${pctKo(roe)} (수수료 전)`) : null,
        q.lock_roe != null ? ` · 자기 잠금 +${rateKo(q.lock_roe, 0)}` : " · 자기 잠금 전");
    }));
  }
  function drawPos() {
    const d = st.d, p = d.position, now = serverNow();
    if (!p) {
      put(posBox, h("div", {class: "lvw-empty"}, h("b", null, "포지션 없음"),
        h("p", null, "VWAP 복귀 실패(30분봉) 또는 CMO·샌드위치 캔들(1시간봉) 신호가 나오고, 쉬는 시간이 아니고, 4시간 판단과 변동성 조건을 통과하면 그 분에 들어가요 (한 번에 하나).")),
        h("h3", {class: "lvw-h3"}, "따라가는 실행기"), followerPos(null));
      return;
    }
    const total = ok(p.limit_ms) ? Number(p.limit_ms) : null;
    const frac = total ? Math.max(0, Math.min(1, (now - Number(p.entry_time)) / total)) : 0;
    const leftNode = h("b", {class: "num"});
    const nx = p.next_lock;
    put(posBox,
      h("div", {class: "lvw-phead"}, h("span", {class: ["side", Number(p.side) > 0 ? "long" : "short"]}, SIDE(p.side)),
        h("b", {class: "lvw-pcoin"}, fmt.coin(p.symbol)), h("span", {class: "lvw-sub"}, ` ${fmt.lev(p.leverage)} · ${p.strategy_ko}`)),
      h("dl", {class: "lvw-kv"},
        h("dt", null, "진입"), h("dd", {class: "num"}, `${fmt.price(p.entry)} · ${fmt.kst(p.entry_time)}`),
        h("dt", null, "지금"), h("dd", {class: "num"}, ok(p.mark) ? fmt.price(p.mark) : "—",
          ok(p.roe_now) ? h("span", {class: fmt.tone(p.roe_now)}, ` · 순ROE ${pctKo(p.roe_now)}`) : null, h("small", {class: "lvw-sub"}, " (봇의 마지막 1분 가격)")),
        h("dt", null, "증거금"), h("dd", {class: "num"}, `${fmt.usd(p.margin)} (연습)`),
        h("dt", null, p.locked ? "잠금선" : "손절"), h("dd", {class: "num"}, fmt.price(p.stop), p.locked ? ` · +${rateKo(p.lock_roe, 0)} 잠금` : " · 2 ATR"),
        h("dt", null, "다음 잠금"), h("dd", {class: "num"}, nx ? `순ROE ${rateKo(nx.at, 0)}(${fmt.price(nx.price)})에 닿으면 ${rateKo(nx.lock, 0)} 잠금` : "—"),
        h("dt", null, "보유"), h("dd", null, `${holdKo(now - Number(p.entry_time))} 째`)),
      h("div", {class: ["lvw-limit", ok(p.left_ms) && Number(p.deadline_ms) - now <= 0 ? "fire" : ""]},
        h("span", {class: "lvw-gk"}, `⏱ 보유 한도 ${p.limit_bars || "—"}봉 (${fmt.tfKo(p.timeframe)}봉 · ${holdKo(p.limit_ms)})`),
        ok(p.deadline_ms) ? h("span", null, tick(leftNode, p.deadline_ms, (ms) => (ms > 0 ? `보유 한도까지 ${holdKo(ms)}` : "보유 한도 지남 · 다음 1분에 정리")),
          h("small", {class: "lvw-sub"}, ` · ${fmt.kst(p.deadline_ms)}에 시장가 정리 (보유 한도 청산)`)) : h("span", null, "보유 한도 없음"),
        ok(p.deadline_ms) ? h("span", {class: "lvw-bar"}, h("i", {style: {"--v": frac.toFixed(4)}})) : null,
        // docs/vwap-bot-ko.md 6장: an executor past its own first lock keeps its own ladder instead of this close
        follower(d).length ? h("small", {class: "lvw-sub"}, "따라가는 실행기는 자기 첫 잠금 뒤에는 이 정리를 따르지 않고 자기 계단으로 가요") : null),
      h("div", {class: "lvw-passed"}, h("span", {class: "lvw-gk"}, "진입 때 통과한 조건"), gatesLine(p.gates)),
      h("h3", {class: "lvw-h3"}, "따라가는 실행기"), followerPos(p));
  }
  function drawFol() {
    const d = st.d, fs = d.followers || [];
    if (!fs.length) {
      put(folBox, h("div", {class: "lvw-empty"}, h("b", null, d.no_follower_ko || "아직 따라가는 실행기 없음 (페이퍼만)"),
        h("p", null, "두 분이 실행기 하나(바이비트 또는 WOO X Pro)를 옮기면 그 실행기의 시작 기록부터 여기 보여요 (docs/vwap-bot-ko.md 5장 C). 옮기면 신호등은 페이퍼 최근 20번 중 75% 이상일 때만 새 진입을 따라가요.")));
      return;
    }
    put(folBox, fs.map((f) => h("div", {class: ["lvw-fitem", f.state]},
      h("div", {class: "lvw-fhead"}, h("b", null, f.name_ko), ui.pill(f.state_ko, f.state === "following" ? "good" : "warn"),
        ok(f.since_ms) ? h("span", {class: "lvw-sub"}, ` ${fmt.kst(f.since_ms)}부터${ok(f.until_ms) ? ` ${fmt.kst(f.until_ms)}까지` : ""}`) : null),
      f.state === "following" || f.state === "pending" ? lightRow({name_ko: `${f.name_ko} 신호등 (VWAP 페이퍼 기준)`, light: f.light}) : null,
      (f.notes || []).map((n) => h("p", {class: "lvw-warn"}, n)))));
  }
  function drawCoins() {
    const pic = st.d.picture || {};
    stamp.textContent = pic.state === "ok" || pic.state === "error" ? `${fmt.kst(pic.at)} 그림 · ${fmt.dur((pic.age_ms || 0) / 1000)} 전` : "";
    if (pic.state !== "ok") {
      put(coinBox, pic.state === "error" ? h("div", {class: "lb-state bad"}, ui.pill("못 읽음", "bad"), h("span", null, ` ${pic.ko}`),
        pic.reason ? h("span", {class: "lb-raw", title: pic.reason}, ` (${pic.reason})`) : null)
        : h("div", {class: "lb-state"}, ui.notYet("아직 그림 없음"), h("span", null, ` ${pic.ko || ""}`)));
      return;
    }
    const tfs = pic.tfs || [];
    const headRow = h("div", {class: "lvw-crow lvw-chead", role: "row"}, h("span", {role: "columnheader"}, "코인"),
      h("span", {role: "columnheader"}, `${fmt.tfKo(pic.vote_tf)} 판단`), tfs.map((tf) => h("span", {role: "columnheader"}, `${fmt.tfKo(tf)} 변동성`)),
      h("span", {role: "columnheader"}, "신호가 오면"));
    const rows = (pic.rows || []).map((r) => {
      const v = r.vote;
      const vcell = !v ? h("div", {class: "lvw-cell na", role: "cell"}, h("b", null, "조건 없음"))
        : v.error ? h("div", {class: "lvw-cell na", role: "cell", title: v.error}, h("b", {class: "lvw-word"}, "못 읽음"), h("small", {class: "lvw-sub"}, "→ 진입 안 함"))
          : h("div", {class: ["lvw-cell", v.raw > 0 ? "up" : v.raw < 0 ? "down" : "hold"], role: "cell", title: v.text || ""},
            h("b", {class: "lvw-word"}, v.word), h("small", {class: "lvw-sub"}, `상승 ${v.up}·하락 ${v.down}·중립 ${v.neutral}`));
      const vols = tfs.map((tf) => {
        const x = (r.vol || {})[tf];
        if (!x) return h("div", {class: "lvw-cell na", role: "cell"}, h("b", null, "—"));
        if (x.error) return h("div", {class: "lvw-cell na", role: "cell", title: x.error}, h("b", {class: "lvw-word"}, "못 읽음"), h("small", {class: "lvw-sub"}, "→ 진입 안 함"));
        const m = atrMeter(x);
        return h("div", {class: ["lvw-cell", x.high ? "high" : "calm"], role: "cell", title: x.text || ""},
          h("b", {class: "lvw-word num"}, `${fmt.pctOf(x.atr_pct, 2)}`, h("small", null, ` / ${x.q_pct == null ? "모름" : fmt.pctOf(x.q_pct, 2)}`)),
          h("span", {class: ["lvw-atr", x.high ? "high" : ""], title: `80% 위치의 ${ok(x.ratio) ? Number(x.ratio).toFixed(2) : "?"}배`},
            h("i", {style: {"--v": m.fill.toFixed(4)}}), h("b", {style: {"--m": m.mark.toFixed(4)}})),
          h("small", {class: "lvw-sub"}, x.high ? "높음 → 진입 안 함" : ok(x.ratio) ? `80% 위치의 ${Number(x.ratio).toFixed(2)}배` : "30일 위치 모름 (통과)"));
      });
      const sides = h("div", {class: "lvw-cell lvw-sides", role: "cell"}, (r.sides || []).map((x) => h("div", {class: ["lvw-side", sideTone(x)]},
        h("span", {class: "lvw-sk"}, x.member_ko), h("b", null, x.ko))));
      return h("div", {class: "lvw-crow", role: "row"}, h("div", {class: "lvw-coin", role: "rowheader"}, h("b", null, fmt.coin(r.symbol))), vcell, vols, sides);
    });
    put(coinBox, pic.stale ? h("p", {class: "lvw-warn"}, `그림이 ${fmt.dur((pic.age_ms || 0) / 1000)} 전 것이에요 (40분 넘게 안 바뀜) · 봇이 그림을 못 그리고 있을 수 있어요 · 진입 판단은 신호마다 따로 해요`) : null,
      h("div", {class: "lvw-ctable", role: "table", "aria-label": "코인별 진입 조건", style: {"--cols": String(tfs.length), "--cells": String(tfs.length + 1)}}, headRow, rows),
      h("p", {class: "lvw-sub"}, `${fmt.tfKo(pic.vote_tf)} 판단 4개(V3.9 · EMA·DMI·ADX · OBV · 일목·AO)는 추세판단 봇과 같은 계산 · ATR%는 14봉 · 막대의 세로선이 지난 30일 80% 위치 · 못 읽은 칸은 그 신호를 들어가지 않아요`));
  }
  function drawPause() {
    const pz = st.d.pause || {};
    const n = pz.now || {}, nx = pz.next;
    const left = h("span", {class: "num"});
    put(pauseBox, h("ul", {class: "lvw-list lvw-ilist"},
      h("li", {class: n.paused ? "warn" : ""}, h("span", {class: "lvw-ik"}, "지금"),
        n.paused ? `${n.ko}${ok(n.until) ? ` · ${fmt.kst(n.until)}까지` : ""}` : n.paused === false ? "쉬는 시간 아님 · 신호가 오면 조건을 보고 들어가요" : (n.ko || "모름")),
      nx ? h("li", null, h("span", {class: "lvw-ik"}, "다음"), h("span", null, `${nx.ko} · ${fmt.kst(nx.from)}~${ok(nx.until) ? fmt.kst(nx.until) : ""} · `,
        tick(left, nx.from, (ms) => (ms > 0 ? `${holdKo(ms)} 뒤` : "지금")))) : h("li", null, h("span", {class: "lvw-ik"}, "다음"), "앞으로 8일 안에 없음")),
    pz.error ? h("p", {class: "lvw-warn"}, `쉬는 시간 계산 실패: ${pz.error}`) : null,
    h("p", {class: "lvw-sub"}, "주말(한국 시간 토·일) · 미국 경제 발표 앞뒤 30분 (일정: data/macro_events.csv) · 나스닥 개장 앞뒤 30분"));
  }
  function drawRules() {
    const r = st.d.rules || {};
    put(rulesBox, (r.lines || []).length ? h("ul", {class: "lvw-list lvw-rlist"}, r.lines.map((x) => h("li", null, x))) : ui.empty("규칙 기록이 없어요"),
      r.error ? h("p", {class: "lvw-warn"}, `설정을 다 읽지 못했어요: ${r.error}`) : null);
  }
  function drawSigs() {
    const sg = st.d.signals || {};
    const c = sg.counts || {};
    const order = [["entered", "진입"], ["filtered", "막힘"], ["skipped", "건너뜀 (한 번에 하나)"], ["late", "늦음"], ["rejected", "거절"], ["submitted", "결과 기록 전"]];
    put(sigHead, order.filter(([k]) => c[k]).map(([k, ko]) => ui.pill(`${ko} ${fmt.int(c[k])}`, STAGE_TONE[k])),
      sg.cut && ok(sg.from) ? h("span", {class: "lvw-sub"}, ` 봇 시작 ${fmt.kst(sg.from)} 뒤 신호만`) : null);
    const rows = sg.rows || [];
    const list = h("ul", {class: "lvw-list lvw-siglist"}, rows.slice(0, st.sigN).map((r) => h("li", {class: ["lvw-sig", r.stage]},
      h("span", {class: "num lvw-t"}, fmt.kst(r.t)),
      h("span", {class: "lvw-sname"}, h("b", null, `${fmt.coin(r.symbol)} ${SIDE(r.side)}`), ` ${r.member_ko}`),
      ui.pill(r.group_ko ? `막힘 · ${r.group_ko}` : r.stage_ko, r.group ? GROUP_TONE[r.group] : STAGE_TONE[r.stage]),
      r.why ? h("small", {class: "lvw-sub lvw-why"}, r.why) : null,
      r.gates ? h("small", {class: "lvw-why"}, gatesLine(r.gates, {none: false})) : null)));
    const more = rows.length > st.sigN ? h("button", {class: "btn-line lvw-more", type: "button", onclick: () => { st.sigN += SIG_PAGE; drawSigs(); }},
      `더 보기 (${fmt.int(rows.length - st.sigN)}개 남음)`) : null;
    put(sigBox, rows.length ? [list, more] : ui.empty("최근 48시간 신호가 없어요 · VWAP 복귀 실패는 30분봉, CMO·샌드위치 캔들은 1시간봉이 끝날 때 나와요"));
  }
  function draw() {
    const d = st.d;
    st.ticks = [];
    put(slot, stateOf(d));
    drawHero();
    if (!d || d.state !== "ok") { cards.hidden = true; money.hidden = true; hero.hidden = !d || d.state === "off"; return; }
    cards.hidden = false; money.hidden = false; hero.hidden = false;
    drawMoney(); drawPos(); drawFol(); drawCoins(); drawPause(); drawRules(); drawSigs();
  }
  function onTick() {
    for (const k of st.ticks) k.node.textContent = k.f(k.until - serverNow());
    if (st.d && st.d.state === "ok" && (st.d.position || ((st.d.pause || {}).now || {}).paused)) sub.textContent = heroOf(st.d, serverNow()).sub;
  }
  if (hub && hub.get && hub.get()) st.s = hub.get();
  poller(ctx, API, REFRESH_MS, st, slot, main, draw);
  ctx.every(TICK_MS, onTick, {now: false});
  if (ctx.watch) ctx.watch("ticker", () => { if (st.d && st.d.state === "ok") { st.ticks = st.ticks.filter((k) => !posBox.contains(k.node)); drawPos(); } });
  return {el, set(sm) {
    if (!sm) return;
    st.s = sm;
    if (st.d && st.d.state === "ok") { drawMoney(); st.ticks = st.ticks.filter((k) => !posBox.contains(k.node)); drawPos(); }
  }};
}

// ================================================================ 성적 (#/vwperf)
/** The rows of the paper / twin comparison: [label, paper text, twin text, tone of the paper's]. */
export function compareRows(p, f) {
  const v = (a, fn) => (a && a.state === "ok" ? fn(a) : "—");
  return [
    ["지갑 (연습)", v(p, (a) => fmt.usd(a.wallet)), v(f, (a) => fmt.usd(a.wallet))],
    ["시작", v(p, (a) => fmt.usd(a.initial)), v(f, (a) => fmt.usd(a.initial))],
    ["변화", v(p, (a) => pctKo(a.change)), v(f, (a) => pctKo(a.change)), p && fmt.tone(p.change)],
    ["닫힌 거래", v(p, (a) => `${fmt.int(a.n)}번`), v(f, (a) => `${fmt.int(a.n)}번`)],
    ["이김 / 짐", v(p, (a) => `${fmt.int(a.wins)}승 ${fmt.int(a.losses)}패`), v(f, (a) => `${fmt.int(a.wins)}승 ${fmt.int(a.losses)}패`)],
    ["승률", v(p, (a) => rateKo(a.win_rate)), v(f, (a) => rateKo(a.win_rate))],
    ["평균 익절 (순ROE)", v(p, (a) => pctKo(a.avg_win)), v(f, (a) => pctKo(a.avg_win))],
    ["평균 손절 (순ROE)", v(p, (a) => pctKo(a.avg_loss)), v(f, (a) => pctKo(a.avg_loss))],
    ["본전 승률 (이 평균으로)", v(p, (a) => (a.breakeven == null ? "아직 모름" : rateKo(a.breakeven))), v(f, (a) => (a.breakeven == null ? "아직 모름" : rateKo(a.breakeven)))],
    ["손익비 (PF)", v(p, (a) => (a.pf == null ? (a.n ? "손실 없음" : "—") : Number(a.pf).toFixed(2))), v(f, (a) => (a.pf == null ? (a.n ? "손실 없음" : "—") : Number(a.pf).toFixed(2)))],
    ["순ROE 합", v(p, (a) => pctKo(a.roe_sum)), v(f, (a) => pctKo(a.roe_sum)), p && fmt.tone(p.roe_sum)],
    ["손익 (연습)", v(p, (a) => signedUsd(a.pnl)), v(f, (a) => signedUsd(a.pnl)), p && fmt.tone(p.pnl)],
    ["가장 깊은 낙폭", v(p, (a) => (a.max_dd == null ? "—" : pctKo(-a.max_dd))), v(f, (a) => (a.max_dd == null ? "—" : pctKo(-a.max_dd)))],
  ];
}
/** The two equity lines on the same moments for the site's thin curves (ui.curves draws values in order): every close of
 *  either account, each line holding its last closed-trade equity (null before its own first point). {t: [ms], series:
 *  [[equity | null]]}; null with fewer than two moments. */
export function alignCurves(curves) {
  const lines = curves.map((c) => (c || []).filter((p) => ok(p[0]) && ok(p[1])).map((p) => [Number(p[0]), Number(p[1])]));
  const t = [...new Set(lines.flat().map((p) => p[0]))].sort((x, y) => x - y);
  if (t.length < 2) return null;
  const series = lines.map((pts) => {
    let i = -1;
    return t.map((tt) => { while (i + 1 < pts.length && pts[i + 1][0] <= tt) i += 1; return i >= 0 ? pts[i][1] : null; });
  });
  return {t, series};
}
/** A split's rows for the bars: the largest |ROE sum| sets the scale. */
export function splitScale(rows) {
  return Math.max(0.0001, ...(rows || []).map((r) => Math.abs(Number(r.roe_sum) || 0)));
}

/** vwperfView(ctx) -> {el, set()}: 성적 (module comment). */
export function vwperfView(ctx) {
  const st = {d: null, okAt: 0, busy: false, acct: local.get("lvw-split-acct", "paper"), split: local.get("lvw-split", "strategy"), tn: TRADES_PAGE};
  const slot = h("div", {class: "lb-slot"});
  const cmpBox = h("div", {class: "lvw-cmp"});
  const chartBox = h("div", {class: "lvw-eqbox"});
  const skillBox = h("div", {class: "lvw-skill"});
  const checkBox = h("div", {class: "lvw-checks"});
  const refBox = h("div", {class: "lvw-ref"});
  const noteBox = h("div", {class: "lvw-notes"});
  const splitHead = h("div", {class: "lvw-splithead"});
  const splitBox = h("div", {class: "lvw-split"});
  const tradeBox = h("div", {class: "lvw-trades"});
  const since = h("span", {class: "lvw-stamp"});
  const cards = h("div", {class: "lvw-cards"},
    ui.card({title: "페이퍼 vs 동전 쌍둥이", sub: "같은 진입 · 동전 쌍둥이는 방향만 무작위 · 닫힌 거래 기준 · 연습 돈", cls: "lvw-cmpcard", acts: [since]},
      h("div", {class: "lvw-cmpgrid"}, cmpBox, chartBox), skillBox),
    ui.card({title: "키우기 · 멈추기", sub: "실행기가 이 봇을 따라간 뒤의 실거래만 · docs/vwap-bot-ko.md 6장", cls: "lvw-checkcard"}, checkBox),
    ui.card({title: "연구 숫자와 나란히", sub: "연구 계산은 참고예요 · 실제가 이 숫자를 따라간다는 약속이 아니에요", cls: "lvw-refcard"}, refBox),
    ui.card({title: "연구 노트", sub: "페이퍼 기록으로 지금 계산 · 물림(이기기 전에 얼마나 밀렸나)과 신호등이 진 거래를 골라내는지", cls: "lvw-notecard"}, noteBox),
    ui.card({title: "나눠 보기", sub: "어디서 이기고 어디서 지나 · 칸마다 10번 미만은 표본 적음", cls: "lvw-splitcard"}, splitHead, splitBox),
    ui.card({title: "거래", sub: "새것부터 · 진입 때 조건 숫자와 실행기의 결과", cls: "lvw-tradecard"}, tradeBox));
  const main = h("div", {class: "lvw-body"}, cards);
  const el = h("div", {class: "lvw stack"}, slot, main,
    ui.note("보기만 하는 화면 · 1분마다 새로 읽어요 · 승패는 손익 > 0 기준 · 순ROE는 수수료·슬리피지 뒤, 그 거래의 배율 기준"));

  function drawCmp() {
    const d = st.d, p = d.paper || {}, f = d.flip || {};
    since.textContent = ok(d.since_ms) ? `${fmt.kst(d.since_ms)} 시작부터` : "";
    const rows = compareRows(p, f);
    put(cmpBox, h("div", {class: "lvw-ctab", role: "table", "aria-label": "페이퍼와 동전 쌍둥이"},
      h("div", {class: "lvw-ctr lvw-cth", role: "row"}, h("span", {role: "columnheader"}, ""),
        h("span", {role: "columnheader"}, h("i", {class: "lvw-sw paper", "aria-hidden": "true"}), "페이퍼 (진짜 방향)"),
        h("span", {role: "columnheader"}, h("i", {class: "lvw-sw flip", "aria-hidden": "true"}), "동전 쌍둥이")),
      rows.map(([k, a, b, tone]) => h("div", {class: "lvw-ctr", role: "row"}, h("span", {class: "lvw-ck", role: "rowheader"}, k),
        h("b", {class: ["num", tone || ""], role: "cell"}, a), h("span", {class: "num", role: "cell"}, b)))),
      p.state !== "ok" ? sourceState(p, "페이퍼 계좌") : null, f.state !== "ok" ? sourceState(f, "동전 쌍둥이") : null,
      p.state === "ok" && p.n ? h("p", {class: "lvw-sub"}, `본전 승률 = |평균 손절| ÷ (평균 익절 + |평균 손절|) · 승률이 이보다 낮으면 거래당 손해예요`,
        p.small ? ` · 거래 ${p.n}번은 표본 적음` : "") : null);
    // the site's thin curves (the strategy solid, the coin flip dashed), on every close of either account
    const al = alignCurves([p.state === "ok" ? p.curve : [], f.state === "ok" ? f.curve : []]);
    const mid = al ? al.t[Math.floor((al.t.length - 1) / 2)] : null;
    put(chartBox, al ? [ui.curves({series: [{values: al.series[0], cls: "ls", label: "페이퍼"}, {values: al.series[1], cls: "lc", label: "동전 쌍둥이"}],
      base: ok(p.initial) ? Number(p.initial) : null, yfmt: (v) => `$${fmt.num(v, 0)}`, height: 210,
      xlabels: [fmt.kst(al.t[0]), fmt.kst(mid), fmt.kst(al.t[al.t.length - 1])], label: "닫힌 거래 기준 지갑 흐름 (페이퍼 · 동전 쌍둥이)"}),
    h("div", {class: "lvw-legend"}, h("span", null, h("i", {class: "lvw-sw paper"}), "페이퍼"), h("span", null, h("i", {class: "lvw-sw flip"}), "동전 쌍둥이"),
      h("span", null, h("i", {class: "lvw-sw base"}), "시작 지갑"), h("span", {class: "lvw-sub"}, "가로축은 거래가 닫힌 순서 (시간 간격 아님)"))]
      : h("p", {class: "lvw-sub"}, "닫힌 거래가 생기면 지갑 흐름이 그려져요"));
    const k = d.skill;
    put(skillBox, k ? h("p", {class: ["lvw-skillline", k.small ? "small" : ""]}, h("b", null, k.ko)) : null);
  }
  function checkCard(c) {
    const rec = c.record || {}, be = c.breakeven || {}, stp = c.stop || {};
    const pct = Math.min(1, (c.n || 0) / (c.goal || 50));
    return h("div", {class: "lvw-check"},
      h("div", {class: "lvw-fhead"}, h("b", null, c.name_ko), h("span", {class: "lvw-sub"}, ok(c.since_ms) ? ` ${fmt.kst(c.since_ms)}부터 VWAP 개선판을 따라감` : ""),
        c.record_state !== "ok" ? ui.pill("기록 못 읽음", "bad", c.reason_ko || "") : null),
      h("div", {class: "lvw-prog", role: "img", "aria-label": `${c.n} / ${c.goal}번`}, h("i", {style: {"--v": pct.toFixed(4)}})),
      h("p", {class: "lvw-pn"}, h("b", {class: "num"}, `${fmt.int(c.n)} / ${fmt.int(c.goal)}번`),
        rec.n ? h("span", null, ` · ${fmt.int(rec.wins)}승 ${fmt.int(rec.losses)}패 · 승률 ${rateKo(rec.win_rate)} · 순ROE 합 `,
          h("b", {class: ["num", fmt.tone(rec.roe_sum)]}, pctKo(rec.roe_sum))) : h("span", {class: "lvw-sub"}, " · 아직 닫힌 실거래 없음")),
      h("div", {class: ["lvw-be", stp.state]},
        h("div", null, h("span", {class: "lvw-gk"}, "본전 승률 (멈추기 선)"), h("b", {class: "num"}, ` ${rateKo(be.value)}`),
          h("small", {class: "lvw-sub"}, ` · ${be.ko}`)),
        h("div", {class: "lvw-sub"}, `페이퍼 평균으로 ${be.paper == null ? "아직 모름" : rateKo(be.paper)} · 5년 기록 ${rateKo(be.ref)} (참고)`),
        h("div", null, ui.pill(stp.state === "bad" ? "본전 아래" : stp.state === "ok" ? "본전 위" : "아직 모름", stp.state === "bad" ? "bad" : stp.state === "ok" ? "good" : "thin"),
          ` ${stp.value_ko || ""}`, stp.small ? h("small", {class: "lvw-sub"}, " · 20번 미만은 운이 커요 (아직 멈출 근거 아님)") : null),
        h("small", {class: "lvw-sub"}, stp.ko)),
      h("ul", {class: "lvw-list lvw-crows"}, (c.rows || []).map((r) => h("li", {class: ["lvw-crit", r.state]},
        ui.pill(CHECK_KO[r.state] || r.state, CHECK_TONE[r.state] || "thin"), h("b", null, r.ko), h("span", {class: "num"}, r.value_ko),
        r.note ? h("small", {class: "lvw-sub"}, r.note) : null))),
      h("p", {class: "lvw-rule"}, h("b", null, "키우기: "), c.scale_ko),
      h("p", {class: "lvw-honest"}, c.honest_ko));
  }
  function drawChecks() {
    const d = st.d, cs = d.checklist || [];
    put(checkBox, cs.length ? cs.map(checkCard) : h("div", {class: "lvw-empty"}, h("b", null, d.no_follower_ko || "아직 따라가는 실행기 없음 (페이퍼만)"),
      h("p", null, "실행기 하나를 옮기면 그 실행기의 실거래가 여기서 50번까지 세져요. 키우기는 50번 승률 80% 이상 · 페이퍼와 비슷함, 멈추기는 승률이 본전 승률 아래로 이어질 때예요."),
      h("p", {class: "lvw-honest"}, d.honest_ko || "")));
  }
  function drawRef() {
    const r = st.d.research || {}, p17 = r.pick17 || {}, y5 = r.five_year || {};
    const rows = [
      ["17일 연구 (고른 기간)", `${fmt.int(p17.n)}번`, `${fmt.int(p17.wins)}승 ${fmt.int(p17.losses)}패 · ${rateKo(p17.win_rate)}`, "—", p17.ko, "ref"],
      ["5년 페이퍼 (같은 규칙)", `${fmt.int(y5.trades)}번`, rateKo(y5.win_rate), `${pctKo(y5.avg_win_roe)} / ${pctKo(y5.avg_loss_roe)} · 본전 ${rateKo(y5.breakeven_win)}`,
        y5.ko, "ref"],
    ];
    const pp = r.paper;
    if (pp) rows.push(["지금 페이퍼 (시작부터)", `${fmt.int(pp.n)}번`, rateKo(pp.win_rate), pp.n ? `${pctKo(pp.avg_win)} / ${pctKo(pp.avg_loss)} · 본전 ${pp.breakeven == null ? "모름" : rateKo(pp.breakeven)}` : "—",
      pp.n < 20 ? "표본 적음" : "", "now"]);
    for (const x of r.live || []) rows.push([`${x.name_ko} 실거래 (VWAP 뒤)`, `${fmt.int(x.n)}번`, rateKo(x.win_rate), x.n ? `${pctKo(x.avg_win)} / ${pctKo(x.avg_loss)} · 본전 ${x.breakeven == null ? "모름" : rateKo(x.breakeven)}` : "—",
      x.n < 20 ? "표본 적음" : "", "now"]);
    const pt = y5.per_trade || {}, mo = y5.months || {};
    put(refBox, h("div", {class: "lvw-rtab", role: "table", "aria-label": "연구 숫자와 지금"},
      h("div", {class: "lvw-rtr lvw-rth", role: "row"}, ["", "거래", "승률", "평균 익절 / 손절 (순ROE)", "메모"].map((x) => h("span", {role: "columnheader"}, x))),
      rows.map(([k, n, w, a, note, kind]) => h("div", {class: ["lvw-rtr", kind], role: "row"}, h("b", {role: "rowheader"}, k), h("span", {class: "num", role: "cell"}, n),
        h("span", {class: "num", role: "cell"}, w), h("span", {class: "num", role: "cell"}, a), h("small", {class: "lvw-sub", role: "cell"}, note || "")))),
      h("ul", {class: "lvw-list lvw-rlist"},
        h("li", null, `5년 거래당 순손익(가격 기준, 수수료 뒤): ${pt.a_ko} ${pctKo(pt.a, 3)} · ${pt.b_ko} ${pctKo(pt.b, 3)} — 매번 조금씩 잃는 구조였어요 (${pt.src || ""})`),
        h("li", null, `달마다 새로 시작하면 ${fmt.int(mo.months)}개월 중 플러스 ${fmt.int(mo.plus)}달, 가운데 달 ×${ok(mo.median) ? Number(mo.median).toFixed(2) : "—"} (증거금 40% · ${mo.src || ""})`),
        h("li", null, `50번 연속 구간에서 승률 80% 이상은 ${rateKo(y5.share_80)}였고, 그 뒤 50번은 평균 승률 ${rateKo(y5.next_win_80)} · 거래당 순ROE ${pctKo(y5.next_roe_80)} · 가운데 ×${ok(y5.next_mult_80) ? Number(y5.next_mult_80).toFixed(2) : "—"}였어요`),
        h("li", {class: "lvw-sub"}, `출처: ${y5.src || ""} · ${p17.src || ""}`)));
  }
  function drawNotes() {
    const n = st.d.notes || {}, dp = n.dips || {}, lt = n.light || {};
    const dip = (x) => (x ? `${fmt.int(x.n)}번${ok(x.share) ? ` (${rateKo(x.share, 0)})` : ""}` : "—");
    const [d20, d40] = dp.dips || [];
    const rec = (r) => (r && r.n ? `${fmt.int(r.n)}번 · ${fmt.int(r.wins)}승 ${fmt.int(r.losses)}패 · 승률 ${rateKo(r.win_rate)} · 순ROE 합 ${pctKo(r.roe_sum)}` : "없음");
    const rule = lt.rule || {};
    put(noteBox,
      h("div", {class: "lvw-note"}, h("b", null, "물림 (진입 뒤 가장 깊이 밀린 순ROE)"),
        h("ul", {class: "lvw-list lvw-rlist"},
          h("li", null, `이긴 거래 ${fmt.int(dp.wins)}번 중 먼저 −20% 넘게 물린 거래 ${dip(d20)} · −40% 넘게 ${dip(d40)}`),
          h("li", null, `이긴 거래의 평균 최저 ${pctKo(dp.mae_win)} · 진 거래의 평균 최저 ${pctKo(dp.mae_loss)}`),
          h("li", null, `진 거래 중 먼저 +10%까지 갔던 거래 ${fmt.int(dp.loss_up10)}번`),
          dp.ref ? h("li", {class: "lvw-sub"}, `${dp.ref.ko} (${dp.ref.src})`) : null),
        dp.small ? h("p", {class: "lvw-sub"}, "거래 20번 미만 · 표본 적음") : null),
      h("div", {class: "lvw-note"}, h("b", null, `신호등 시험 (최근 ${fmt.int(rule.n)}번 중 ${rateKo(rule.min_win, 0)} 이상일 때만 따라감)`),
        h("ul", {class: "lvw-list lvw-rlist"},
          h("li", null, `따라갔을 거래 ${rec(lt.follow)}`),
          h("li", null, `걸렀을 거래 ${rec(lt.hold)}`),
          lt.ref ? h("li", {class: "lvw-sub"}, `${lt.ref.ko} (${lt.ref.src})`) : null),
        lt.small ? h("p", {class: "lvw-sub"}, `페이퍼 거래가 ${fmt.int((rule.n || 20) * 2)}번이 안 돼 아직 대부분 '근거 쌓는 중'(모두 따라감)이에요 · 표본 적음`) : null));
  }
  function drawSplit() {
    const d = st.d, sp = (d.splits || {})[st.acct] || [];
    const accts = [{id: "paper", label: "페이퍼"}, {id: "flip", label: "동전 쌍둥이"}];
    const cur = sp.find((x) => x.id === st.split) || sp[0];
    put(splitHead, ui.seg(accts, st.acct, (id) => { st.acct = id; local.set("lvw-split-acct", id); drawSplit(); }, {label: "계좌"}),
      ui.seg(sp.map((x) => ({id: x.id, label: x.ko})), cur ? cur.id : "", (id) => { st.split = id; local.set("lvw-split", id); drawSplit(); }, {label: "나눠 보기", scroll: true}));
    if (!cur) { put(splitBox, ui.empty("닫힌 거래가 생기면 나눠 볼 수 있어요")); return; }
    const top = splitScale(cur.rows);
    put(splitBox, cur.sub_ko ? h("p", {class: "lvw-sub"}, cur.sub_ko) : null,
      cur.rows.length ? h("ul", {class: "lvw-list lvw-srows"}, cur.rows.map((r) => h("li", {class: ["lvw-srow", r.small ? "small" : ""]},
        h("b", {class: "lvw-sk"}, r.ko),
        h("span", {class: "num lvw-sn"}, `${fmt.int(r.n)}번 · ${fmt.int(r.wins)}승 ${fmt.int(r.losses)}패 · 승률 ${rateKo(r.win_rate, 0)}`),
        h("span", {class: ["lvw-sbar", Number(r.roe_sum) >= 0 ? "up" : "down"]}, h("i", {style: {"--v": (Math.abs(Number(r.roe_sum) || 0) / top).toFixed(4)}})),
        h("b", {class: ["num", "lvw-sroe", fmt.tone(r.roe_sum)]}, pctKo(r.roe_sum)),
        r.small ? h("small", {class: "lvw-sub"}, "표본 적음") : null)))
        : ui.empty(st.acct === "flip" ? "동전 쌍둥이의 닫힌 거래가 아직 없어요" : "닫힌 거래가 아직 없어요"),
      h("p", {class: "lvw-sub"}, "순ROE 합 막대 · 표본이 적은 칸의 차이는 대부분 운이에요 · 규칙을 바꿀지는 두 분이 정해요"));
  }
  function drawTrades() {
    const d = st.d, ts = d.trades || [], fol = (d.followers || []);
    if (!ts.length) { put(tradeBox, ui.empty("닫힌 거래가 아직 없어요")); return; }
    const cols = fol.map((f) => ({id: f.id, ko: f.name_ko}));
    const rows = ts.slice(0, st.tn).map((t) => h("li", {class: ["lvw-trow", t.win ? "win" : "loss"]},
      h("div", {class: "lvw-ttop"},
        h("b", null, `${fmt.coin(t.symbol)} ${SIDE(t.side)}`), h("span", {class: "lvw-sub"}, ` ${t.member_ko}`),
        ui.pill(t.reason_ko, t.reason === "LOCK" ? "good" : t.reason === "SL" ? "bad" : "accent", t.why || ""),
        h("b", {class: ["num", "lvw-troe", fmt.tone(t.roe)]}, pctKo(t.roe))),
      h("div", {class: "lvw-tmeta num"}, `${fmt.kst(t.entry_time)} → ${fmt.kst(t.exit_time)} (${holdKo(t.hold_ms)}) · ${fmt.price(t.entry_price)} → ${fmt.price(t.exit_price)}`,
        t.why ? ` · ${t.why}` : "", ok(t.mae) ? ` · 물림 ${pctKo(t.mae)} · 최고 ${pctKo(t.mfe)}` : ""),
      h("div", {class: "lvw-tg"}, gatesLine(t.gates)),
      cols.length ? h("div", {class: "lvw-tlive"}, cols.map((c) => {
        const cell = (t.live || {})[c.id];
        const x = liveCellKo(cell);
        return h("span", {class: ["lvw-lc", x.tone], title: (cell && (cell.why_ko || cell.why_text)) || ""}, `${c.ko}: `, h("b", {class: "num"}, x.ko),
          cell && cell.state === "missed" && cell.why_ko ? h("small", {class: "lvw-sub"}, ` (${cell.why_ko})`) : null);
      })) : null));
    const more = ts.length > st.tn ? h("button", {class: "btn-line lvw-more", type: "button", onclick: () => { st.tn += TRADES_PAGE; drawTrades(); }},
      `더 보기 (${fmt.int(ts.length - st.tn)}개 남음)`) : null;
    put(tradeBox, h("ul", {class: "lvw-list lvw-tlist"}, rows), more);
  }
  function draw() {
    const d = st.d;
    put(slot, stateOf(d));
    if (!d || d.state !== "ok") { cards.hidden = true; return; }
    cards.hidden = false;
    drawCmp(); drawChecks(); drawRef(); drawNotes(); drawSplit(); drawTrades();
  }
  poller(ctx, PERF_API, SLOW_MS, st, slot, main, draw);
  return {el, set() {}};
}

// ================================================================ 막은 신호 (#/vwblock)
/** vwblockView(ctx) -> {el, set()}: 막은 신호 (module comment). */
export function vwblockView(ctx) {
  const st = {d: null, okAt: 0, busy: false};
  const slot = h("div", {class: "lb-slot"});
  const countBox = h("div", {class: "lvw-counts"});
  const virtBox = h("div", {class: "lvw-virt"});
  const recentBox = h("div", {class: "lvw-recent"});
  const since = h("span", {class: "lvw-stamp"});
  const cards = h("div", {class: "lvw-cards"},
    ui.card({title: "막은 신호 수", sub: "VWAP 개선판 기록 그대로 · 오늘(한국 시간) · 최근 7일 · 시작부터", cls: "lvw-countcard", acts: [since]}, countBox),
    ui.card({title: "막지 않았다면", sub: "1분 감시가 같은 엔진·같은 1분봉으로 계산한 가상 결과 · 계좌가 비어 있었다고 치고", cls: "lvw-virtcard"}, virtBox),
    ui.card({title: "최근 막은 신호", sub: "새것부터 · 봇이 남긴 이유와 조건 숫자", cls: "lvw-recentcard"}, recentBox));
  const main = h("div", {class: "lvw-body"}, cards);
  const el = h("div", {class: "lvw stack"}, slot, main,
    ui.note("보기만 하는 화면 · 1분마다 새로 읽어요 · 조건을 바꿀지는 두 분이 정해요 (이 화면은 숫자만 보여 드려요)"));

  function drawCounts() {
    const c = st.d.counts || {}, gs = c.groups || [], tot = c.total || {};
    since.textContent = ok(st.d.since_ms) ? `${fmt.kst(st.d.since_ms)} 시작부터` : "";
    const top = Math.max(1, ...gs.map((g) => g.all || 0));
    put(countBox, h("div", {class: "lvw-btab", role: "table", "aria-label": "막은 신호 수"},
      h("div", {class: "lvw-btr lvw-bth", role: "row"}, ["이유", "오늘", "7일", "시작부터", ""].map((x) => h("span", {role: "columnheader"}, x))),
      gs.map((g) => h("div", {class: ["lvw-btr", g.all ? "" : "zero"], role: "row"},
        h("div", {class: "lvw-bk", role: "rowheader"}, h("b", null, g.ko), h("small", {class: "lvw-sub"}, g.sub_ko),
          (g.kinds || []).length ? h("small", {class: "lvw-sub"}, g.kinds.map((k) => `${k.ko} ${k.n}`).join(" · ")) : null),
        h("span", {class: "num", role: "cell"}, fmt.int(g.today)), h("span", {class: "num", role: "cell"}, fmt.int(g.week)),
        h("b", {class: "num", role: "cell"}, fmt.int(g.all)),
        h("span", {class: ["lvw-bbar", g.id], role: "cell"}, h("i", {style: {"--v": ((g.all || 0) / top).toFixed(4)}})))),
      h("div", {class: "lvw-btr lvw-btot", role: "row"}, h("b", {role: "rowheader"}, "합계"), h("b", {class: "num"}, fmt.int(tot.today)),
        h("b", {class: "num"}, fmt.int(tot.week)), h("b", {class: "num"}, fmt.int(tot.all)), h("span"))));
  }
  function vrow(r) {
    return h("li", {class: ["lvw-vrow", r.state === "closed" ? (r.win ? "win" : "loss") : r.state]},
      h("span", {class: "num lvw-t"}, fmt.kst(r.t)),
      h("span", {class: "lvw-sname"}, h("b", null, `${fmt.coin(r.symbol)} ${SIDE(r.side)}`), r.member_ko ? ` ${r.member_ko}` : "",
        r.executor_ko ? ` · ${r.executor_ko}` : ""),
      h("b", {class: ["num", r.state === "closed" ? fmt.tone(r.roe) : ""]}, resultKo(r)),
      r.gates ? h("small", {class: "lvw-why"}, gatesLine(r.gates, {none: false})) : r.why ? h("small", {class: "lvw-sub lvw-why"}, r.why) : null);
  }
  function drawVirt() {
    const v = st.d.virtual || {};
    if (v.state !== "ok") {
      put(virtBox, v.state === "pending" ? h("div", {class: "lb-state"}, ui.notYet("계산 전"), h("span", null, ` ${v.reason_ko}`))
        : sourceState(v, "못 탄 신호 (livecheck.db)"),
      h("p", {class: "lvw-sub"}, "막은 신호 수(위)는 VWAP 개선판 기록에서 바로 세요 · 가상 결과만 1분 감시를 기다려요"));
      return;
    }
    const g = v.gate || {};
    put(virtBox,
      h("p", {class: "lvw-vhead"}, h("b", null, "진입 조건(4시간·변동성)이 막은 신호: "),
        g.n ? `가상 ${fmt.int(g.wins)}승 ${fmt.int(g.losses)}패 · 진행 중 ${fmt.int(g.open)} · 순ROE 합 ` : "아직 없어요",
        g.n ? h("b", {class: ["num", fmt.tone(g.roe_sum)]}, pctKo(g.roe_sum)) : null,
        g.n && g.small ? h("small", {class: "lvw-sub"}, ` · 끝난 것 ${fmt.int(g.closed)}번 · 표본 적음`) : null),
      (v.kinds || []).length ? h("div", {class: "lvw-kinds"}, v.kinds.map((k) => h("section", {class: ["lvw-kind", k.grp]},
        h("div", {class: "lvw-khead"}, h("b", null, k.ko), k.grp_ko && k.grp_ko !== k.ko ? ui.pill(k.grp_ko, k.grp === "gate" ? "bad" : "thin") : null,
          h("span", {class: "num lvw-sub"}, ` ${fmt.int(k.n)}개 · 끝남 ${fmt.int(k.closed)} · ${fmt.int(k.wins)}승 ${fmt.int(k.losses)}패 · 순ROE 합 `),
          h("b", {class: ["num", fmt.tone(k.roe_sum)]}, pctKo(k.roe_sum)), k.paper_result ? ui.pill("페이퍼 결과 (가상 아님)", "accent") : null),
        h("p", {class: "lvw-kread"}, k.read_ko),
        h("ul", {class: "lvw-list lvw-vlist"}, (k.rows || []).map(vrow)))))
        : ui.empty("아직 막은 신호의 가상 결과가 없어요"),
      h("p", {class: "lvw-honest"}, v.note_ko),
      v.pass && v.pass.stale ? h("p", {class: "lvw-warn"}, `1분 감시의 마지막 계산 ${v.pass.last_ms ? fmt.kst(v.pass.last_ms) : "기록 없음"} · 10분 넘게 멈췄어요`) : null);
  }
  function drawRecent() {
    const rs = (st.d.counts || {}).recent || [];
    put(recentBox, rs.length ? h("ul", {class: "lvw-list lvw-siglist"}, rs.map((r) => h("li", {class: "lvw-sig filtered"},
      h("span", {class: "num lvw-t"}, fmt.kst(r.t)),
      h("span", {class: "lvw-sname"}, h("b", null, `${fmt.coin(r.symbol)} ${SIDE(r.side)}`), ` ${r.member_ko}`),
      ui.pill(r.group_ko, GROUP_TONE[r.group] || "thin"),
      r.why ? h("small", {class: "lvw-sub lvw-why"}, r.why) : null,
      r.gates ? h("small", {class: "lvw-why"}, gatesLine(r.gates, {none: false})) : null)))
      : ui.empty("막은 신호가 아직 없어요"));
  }
  function draw() {
    const d = st.d;
    put(slot, stateOf(d));
    if (!d || d.state !== "ok") { cards.hidden = true; return; }
    cards.hidden = false;
    drawCounts(); drawVirt(); drawRecent();
  }
  poller(ctx, BLOCK_API, SLOW_MS, st, slot, main, draw);
  return {el, set() {}};
}

