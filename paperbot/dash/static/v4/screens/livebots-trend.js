// 실거래 › 관제 (#/trend, the live site's first screen; owners 10/21 "대시보드 다시 만들어야겠네 야무지게 필요한부분들 전부다
// 포함해서 멋있게"): the 추세판단 봇 both executors follow, everything on one screen, read-only:
//   지금        the hero: what the bot is doing now (보유 중 · 되돌림 기다림 (only while a signal waits: a config with
//              trend.pullback_wait; the owners' since 10/22 enters at once) · 진입 가능 · 쉬는 시간 · 기록 멈춤), the rule freeze
//              countdown (2 weeks, then the review), the money (바이비트 · WOO X Pro · 페이퍼, today), the bot's record since it
//              started
//   포지션 · 감독 the open paper position and what can close it: 시간 정리 countdown (4 entry bars), the higher bar's judgment
//              now (반대 3/4 = 감독 청산), the fast stop, the first lock; each executor's own position next to it
//   추세 지도    every coin's last closed 1h (30m entries), 4h (1h entries) and daily (4h entries, 10/22) judgment, the ones
//              the config's members read: 상승 / 하락 / 보류, the four judges, ADX on a 0-60 meter, 끝물 / 힘 약함, and which
//              entries it allows now (보류 허용, trend.hold_entry: a 보류 takes both sides, only the other direction stops)
//   되돌림 대기  the signals waiting for their pullback (a config that waits): the level, the price now and how far, the
//              time left; else (바로 진입) what the bot looks at next; the pauses
//   오늘 신호 흐름 signals → checks passed → pullback touched (a config that waits) → entered, and what stopped the rest
//   진입 매매법  each entry member: role, timeframes, today's signals, its record since the start, its pause
//   새 봇 성적 · 최근 거래 · 감독 청산 · 규칙 · 최근 24시간 신호
// A fresh start (owners 10/21 "뭔가 허전해 보여서") says what the bot does meanwhile instead of empty boxes: a position
// the bot before it opened (전환 전 포지션: closed by this bot, never its trade) and what each executor did with it, the
// next bar closes and the directions the trend takes now, the next entry pause, the 7/1~10/20 replay's expectation (가상,
// with the 시간 정리 exit it ran with), the judgment changes of the last 24 h (the 일지 tab's own rows); today's funnel and
// the signals count from the bot's start.
// Sources: /api/v4/livebots/trend (dash/more/livetrend.py, every 15 s) and the site's summary /api/v4/livebots (the money
// and the executors' positions, every 5 s, handed in by screens/livebots.js); the price is the site's ticker (core/store.js
// mark) when it has one, else the rule bot's last 1m close from the answer; the strategies' Korean names come with the
// board. Countdowns tick every second on the server's clock. HONESTY: unread = 못 읽음 + why, never a zero; paper money is
// never shown as real money.
import {h, put, ui, fmt, store, serverNow, href} from "../core/pb.js";
import {sourceState, waitKo, expectLines, expectHead, mainFollowKo, papersNow, josaObj} from "./livebots-kit.js";

export const API = "/api/v4/livebots/trend";
// the judgment changes of the last 24 h: the 일지 tab's answer (dash/more/livejournal.py, its "trend" rows), every 60 s
export const JOURNAL_API = "/api/v4/livebots/journal";
const JOURNAL_MS = 60 * 1000;
const CHANGES_KEEP = 6;
const REFRESH_MS = 15 * 1000;
const TICK_MS = 1000;
const MIN = 60 * 1000, HOUR = 60 * MIN, DAY = 24 * 60 * MIN;
const COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"];
const JUDGES = [["V39", "V3.9"], ["S6", "EMA·DMI·ADX"], ["OBV", "OBV"], ["N12", "일목·AO"]];
export const DIR_KO = {1: "상승", "-1": "하락", 0: "보류"};
const TF_ENTRY = {"1h": "30m", "4h": "1h", "1d": "4h"};         // the judged bar -> the entries that read it (1d: 10/22)
const JUDGED = ["1h", "4h", "1d"];
const ENTRY_KO = {"30m": "30분", "1h": "1시간", "4h": "4시간"};
const MAP_HEAD_KO = {"1h": "1시간 → 30분 진입", "4h": "4시간 → 1시간 진입", "1d": "일봉 → 4시간 진입"};
const TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440};
const CAT_ORDER = ["entered", "submitted", "pulled", "pullback_wait", "nopull", "trend", "spot", "member_pause", "coin_pause", "daily",
  "chase", "chase_unread", "weekend", "macro", "usopen", "trend_unread", "late", "when", "config", "other"];
export const HELD_KO = "보류 진입";             // an entry on a 보류 judgment (10/22 보류 허용: the answer's entry_held)
/** A timeframe as a bar's name: "1시간봉" / "일봉" (never "일봉봉"). */
const barKo = (tf) => { const k = fmt.tfKo(tf); return k.endsWith("봉") ? k : `${k}봉`; };
const EXIT_CLS = {LOCK: "good", SL: "bad", LIQ: "bad", REV: "warn", JUDGE: "accent", TIME: "accent"};
export const EXIT_SHORT_KO = {SL: "손절", LOCK: "계단 익절", LIQ: "강제청산", REV: "빠른 청산", JUDGE: "감독(추세)", TIME: "감독(시간)",
  HALT: "멈춤", MANUAL: "수동"};
const exitKo = (r) => EXIT_SHORT_KO[r] || r || "—";
const SIDE = (s) => (Number(s) > 0 ? "롱" : "숏");
const ok = (x) => x != null && x !== "" && Number.isFinite(Number(x));
const signed = (x) => `${Number(x) >= 0 ? "+" : "−"}${fmt.usd(Math.abs(Number(x)))}`;
/** A coin's price now: the ticker's mark, else the answer's last 1m close (null when neither). */
const priceOf = (t, sym) => {
  const m = store.mark(sym);
  if (ok(m)) return Number(m);
  const p = ((t && t.prices) || {})[sym];
  return p && ok(p.price) ? Number(p.price) : null;
};

// ---------------------------------------------------------------- pure (node tests: tests/test_livetrend.py)
/** {cls, word, sub} of one judgment ({error} when unread). */
export function judgeCell(j) {
  if (!j || j.error) return {cls: "na", word: "못 읽음", sub: (j && j.error) || "아직 판단 없음"};
  const d = Number(j.dir);
  const raw = Number(j.raw);
  let word = DIR_KO[d] ?? "보류";
  if (d === 0 && raw) word = `보류 (${DIR_KO[raw]} 유지 확인 중)`;
  const adx = Number(j.adx), prev = Number(j.adx_prev);
  const votes = Object.values(j.votes || {});
  const bits = [`상승 ${votes.filter((v) => v > 0).length}·하락 ${votes.filter((v) => v < 0).length}`];
  if (Number.isFinite(adx)) bits.push(`ADX ${Math.round(adx)} ${adx > prev ? "오름" : "내림"}`);
  if (j.tired) bits.push("끝물");
  else if (j.strong === false) bits.push("힘 약함");
  const cls = d > 0 ? "up" : d < 0 ? "down" : "hold";
  return {cls: (j.tired || j.strong === false) && d ? `${cls} weak` : cls, word, sub: bits.join(" · ")};
}
/** "▲" / "▼" / "–" of one judge's vote. */
export const voteMark = (v) => (Number(v) > 0 ? "▲" : Number(v) < 0 ? "▼" : "–");
/** The signal counts in the bot's order (the ones with rows only). */
export function countsInOrder(counts) {
  const c = counts || {};
  const keys = [...CAT_ORDER.filter((k) => c[k]), ...Object.keys(c).filter((k) => !CAT_ORDER.includes(k) && c[k])];
  return keys.map((k) => ({id: k, n: c[k]}));
}
/** What a higher-bar judgment allows now: {side: 1 | -1 | 0, both, ko} ("30분 롱만" / "30분 쉼 · 보류"); ``hold`` (the
 *  config's trend.hold_entry, 10/22 보류 허용): a 보류 with strength and not 끝물 takes both sides ("30분 롱·숏 (보류 허용)"). */
export function allows(j, tf, hold) {
  const e = ENTRY_KO[TF_ENTRY[tf]] || "진입";
  if (!j || j.error) return {side: 0, ko: `${e} 쉼 · 판단 못 읽음`};
  const d = Number(j.dir);
  if (!d && !hold) return {side: 0, ko: `${e} 쉼 · 보류`};
  if (j.strong === false) return {side: 0, ko: `${e} 쉼 · 힘 약함`};
  if (j.tired) return {side: 0, ko: `${e} 쉼 · 끝물`};
  if (!d) return {side: 0, both: true, ko: `${e} 롱·숏 (보류 허용)`};
  return {side: d, ko: `${e} ${SIDE(d)}만`};
}
/** The ADX meter's fill (0..1 over 0-60) and its zone ("weak" < 20, "ok", "hot" > 40). */
export function adxMeter(adx) {
  const v = Number(adx);
  if (adx == null || !Number.isFinite(v)) return {fill: 0, zone: "na"};
  return {fill: Math.max(0, Math.min(1, v / 60)), zone: v < 20 ? "weak" : v > 40 ? "hot" : "ok"};
}
/** How far the price still is from a wait's level, as a share of the price (0 once there): a long waits for lower. */
export function waitGap(w, price) {
  if (!w || !ok(w.level) || !ok(price) || Number(price) <= 0) return null;
  const g = Number(w.side) > 0 ? (Number(price) - Number(w.level)) / Number(price) : (Number(w.level) - Number(price)) / Number(price);
  return Math.max(0, g);
}
/** The rule freeze: {days, ko} ("규칙 고정 D-12 · 11/04 검토" / "… 검토할 때예요"). */
export function freezeKo(bot, now) {
  if (!bot || !ok(bot.freeze_until)) return {days: null, ko: "규칙 고정 기간 모름"};
  const left = Number(bot.freeze_until) - Number(now);
  if (left <= 0) return {days: 0, ko: `규칙 고정 2주 끝 · ${fmt.mmdd(bot.freeze_until)}부터 검토할 때예요`};
  return {days: Math.ceil(left / DAY), ko: `규칙 고정 D-${Math.ceil(left / DAY)} · ${fmt.mmdd(bot.freeze_until)} 검토`};
}
/** "1:02:03" / "12:05" / "0:59" (a countdown, whole seconds rounded up). */
export function clock(ms) {
  if (!ok(ms)) return "—";
  const t = Math.max(0, Math.ceil(Number(ms) / 1000));
  const hh = Math.floor(t / 3600), mm = Math.floor((t % 3600) / 60), ss = t % 60;
  const two = (n) => String(n).padStart(2, "0");
  return hh ? `${hh}:${two(mm)}:${two(ss)}` : `${mm}:${two(ss)}`;
}
/** The judged bars the running config's members read (their entry bar's higher bar), in order; without members the ones
 *  the coins carry (1h · 4h · 1d). */
export function judgedTfs(t) {
  const ms = (t && t.members) || [];
  const want = new Set(ms.map((m) => m.htf || {"30m": "1h", "1h": "4h", "4h": "1d"}[m.tf]).filter(Boolean));
  if (want.size) return JUDGED.filter((tf) => want.has(tf));
  const have = new Set(Object.values((t && t.coins) || {}).flatMap((r) => Object.keys(r || {})));
  const out = JUDGED.filter((tf) => have.has(tf));
  return out.length ? out : ["1h", "4h"];
}
/** The entry bars in words, from the judged ones: "30분·1시간·4시간". */
export const entryTfsKo = (t) => judgedTfs(t).map((tf) => ENTRY_KO[TF_ENTRY[tf]]).join("·");
/** The directions the trend takes now, in the map's words: ["BTC 30분 롱만", "ETH 1시간 숏만", "SOL 4시간 롱·숏 (보류 허용)", ...]. */
export function takingNow(t) {
  const out = [];
  for (const c of COINS) {
    for (const tf of judgedTfs(t)) {
      const a = allows((((t && t.coins) || {})[c] || {})[tf], tf, t && t.hold_entry);
      if (a.side || a.both) out.push(`${fmt.coin(c)} ${a.ko}`);
    }
  }
  return out;
}
/** The next closes after now: {m30, h1, h4} (ms; the entry signals come at a 30-minute, an hour or a 4-hour close). */
export function nextCloses(now) {
  const n = Number(now);
  return {m30: n - (n % (30 * MIN)) + 30 * MIN, h1: n - (n % HOUR) + HOUR, h4: n - (n % (4 * HOUR)) + 4 * HOUR};
}
// waitKo, expectLines and expectHead (the replay's expectation in words) live in livebots-kit.js (성적 · 지도 say it too)
export {waitKo, expectLines, expectHead};
/** The higher bar's judgment against the position, in words: closed by the supervisor only on a bar closed after the
 *  entry, so a position opened against it (전환 전) waits for the next close (trendbot.py _before_step). */
export function againstKo(p, j) {
  const htfMs = (TF_MIN[p && p.htf] || 60) * MIN;
  if (j && ok(j.bar_close) && p && ok(p.entry_time) && Number(j.bar_close) <= Number(p.entry_time)) {
    return `진입 때부터 반대 · ${fmt.hm(Number(j.bar_close) + htfMs)}에 끝나는 ${barKo(p.htf)}도 반대면 감독 청산`;
  }
  return "반대로 바뀜 · 감독 청산";
}
const KICK = "추세판단 봇 · 바이비트 · WOO X Pro가 따라가는 페이퍼(−50%)";
/** The hero's kicker: who follows this bot (two paper bots, owners 10/23: only its own followers; one: the usual line). */
export const kickKo = () => { const f = mainFollowKo(); return f ? `추세판단 봇 · ${f} 페이퍼(−50%)` : KICK; };
/** The other paper bot an executor follows now (the summary's follows_ko against the main bot's name), null when it follows
 *  this one (or with one paper bot). */
export function otherBotOf(a) {
  const ps = papersNow();
  if (!ps || !a || !a.follows_ko) return null;
  const main = ps.find((b) => b.id === "paper") || {};
  return a.follows_ko !== main.short_ko ? a.follows_ko : null;
}
/** An executor without a position, in words: following and waiting, halted, or what it did with the paper's open one
 *  (``f``: that executor's row of the answer's position.follow, from its own records). */
export function idleKo(a, p, f) {
  if (a && a.halted) return "포지션 없음 · 멈춤 (사람이 풀기 전엔 새 진입 안 함)";
  if (!p) return `포지션 없음 · 따라가는 중 · 다음 페이퍼 진입을 기다려요${a && a.stale ? " (기록 오래됨)" : ""}`;
  if (f && f.state === "skip") return `이 포지션 안 따라감 · ${f.ko}`;
  if (f && f.state === "none") return "이 포지션을 따라간 기록 없음";
  if (f && f.state === "other") return f.ko;
  return "포지션 없음 (안 따라갔거나 이미 닫음)";
}
/** The hero's state from the trend answer: {cls, head, sub}. */
export function heroOf(t, now) {
  if (!t || t.state !== "ok") return {cls: "na", head: "추세판단 봇 기록을 기다리는 중", sub: ""};
  const bot = t.bot || {};
  if (bot.stale) return {cls: "stop", head: "페이퍼 봇 기록이 멈췄어요", sub: "5분 넘게 새 기록이 없어요 · 봇 상태 탭을 보세요 (그동안 실행기는 새 진입을 안 해요)"};
  const p = t.position;
  if (p) {
    const lockKo = p.locked ? `첫 잠금 +${Math.round(Number(p.lock_roe) * 100)}% · 계단 익절만`
      : ok(p.deadline) ? `시간 정리까지 ${clock(Number(p.deadline) - now)}` : "첫 잠금 전 · 손절·추세 뒤집힘이 지켜봐요";
    return {cls: "hold", head: `${fmt.coin(p.symbol)} ${SIDE(p.side)} 보유 중`, sub: `${fmt.stratKo(p.strategy)} ${fmt.tfKo(p.tf)} · ${lockKo}`};
  }
  const pz = t.pause || {};
  if (pz.paused) {
    return {cls: "pause", head: pz.ko,
      sub: ok(pz.until) ? `${fmt.kst(pz.until)}까지 (${clock(Number(pz.until) - now)} 남음) · 열린 포지션은 그대로` : ""};
  }
  const waits = (t.waits || []).filter((w) => Number(w.until) > now);
  if (waits.length) {
    const w = waits[0];
    return {cls: "wait", head: `되돌림 기다리는 신호 ${waits.length}개`,
      sub: `${fmt.coin(w.symbol)} ${SIDE(w.side)} ${fmt.stratKo(String(w.member || "").split("@")[0])} · ${fmt.price(w.level)} 닿으면 진입`};
  }
  const trending = takingNow(t);
  return {cls: "go", head: "진입 가능 · 추세와 같은 방향 신호를 기다리는 중",
    sub: trending.length ? `지금 받는 방향: ${trending.slice(0, 6).join(" · ")}${trending.length > 6 ? " …" : ""}`
      : t.hold_entry ? "지금 받는 곳이 없어요 (모두 힘 약함·끝물이거나 못 읽음)" : "지금은 모든 코인이 보류예요 (추세가 생기면 받아요)"};
}

// ---------------------------------------------------------------- the view
/** trendView(ctx, hub) -> {el, set(summary)}: its own endpoint every 15 s, the countdowns every second (ctx.every: the
 *  router stops them); ``set`` gets the site's summary (money, the executors' positions) from screens/livebots.js. */
export function trendView(ctx, hub) {
  const st = {t: null, s: null, okAt: 0, busy: false, ticks: [], j: null, jAt: 0};
  const stateSlot = h("div", {class: "lb-slot"});
  // the hero
  const head = h("h2", {class: "ltr-head"}, "불러오는 중");
  const sub = h("p", {class: "ltr-hsub"});
  const chips = h("div", {class: "ltr-hchips"});
  const money = h("div", {class: "ltr-money", role: "list", "aria-label": "지갑"});
  const kick = h("p", {class: "ltr-kick"}, kickKo());
  const hero = h("section", {class: "ltr-hero na", "aria-label": "지금"},
    h("div", {class: "ltr-orb", "aria-hidden": "true"}, h("i")),
    h("div", {class: "ltr-hmain"}, kick, head, sub, chips),
    money);
  // the cards
  const posBox = h("div", {class: "ltr-pos"});
  const grid = h("div", {class: "ltr-grid"});
  const changes = h("div", {class: "ltr-chg"});
  const waits = h("div", {class: "ltr-waits"});
  const pauses = h("div", {class: "ltr-pauses"});
  const pauseHead = h("h3", {class: "ltr-h3"}, "쉬는 매매법 · 코인");
  const funnelBox = h("div", {class: "ltr-funnel"});
  const membersBox = h("div", {class: "ltr-members", role: "list"});
  const recordBox = h("div", {class: "ltr-record"});
  const tradesBox = h("div", {class: "ltr-trades"});
  const sigHead = h("div", {class: "ltr-chips"});
  const sigList = h("div", {class: "ltr-sigs"});
  const sup = h("div", {class: "ltr-sup"});
  const rules = h("div", {class: "ltr-rules"});
  const stamp = h("span", {class: "ltr-stamp"});
  // the waits card and the map's line follow the running config (trend.pullback_wait, trend.hold_entry: drawWaits, drawGrid)
  const wTitle = h("span", null, "되돌림 기다리는 신호");
  const wSub = h("span", null, "추세와 같은 방향 신호 · 진입 봉 하나 동안 기다리고 안 오면 버려요");
  const mapSub = h("span", null, "끝난 봉만 봐요 · 4개 중 3개 이상 같은 쪽이면 추세 · ADX 20 이상, 40 넘고 꺾이면 끝물");
  const memTitle = h("span", null, "진입 매매법");
  const cards = h("div", {class: "ltr-cards"},
    h("div", {class: "ltr-two ltr-top"},
      ui.card({title: "포지션 · 감독", sub: "첫 잠금 전에는 손절 · 추세 뒤집힘 · 빠른 청산이 지켜봐요 (시간 정리는 10/21 밤에 뺌)", cls: "ltr-poscard"}, posBox),
      ui.card({title: wTitle, label: "다음 진입", sub: wSub, cls: "ltr-wcard"}, waits,
        pauseHead, pauses)),
    ui.card({title: "추세 지도", sub: mapSub, cls: "ltr-judge", acts: [stamp]}, grid, changes),
    h("div", {class: "ltr-two"},
      ui.card({title: "오늘 신호 흐름", sub: "한국 시간 오늘 · 진입 매매법 신호가 어디서 걸렸나", cls: "ltr-fcard"}, funnelBox),
      ui.card({title: "새 봇 성적", sub: "페이퍼(연습) · 새 규칙 시작 뒤 거래만 · 실거래 계좌는 위 지갑", cls: "ltr-rcard"}, recordBox)),
    ui.card({title: memTitle, label: "진입 매매법", sub: "진입만 하는 매매법 · 추세 판단 4개(V3.9 · EMA·DMI·ADX · OBV · 일목·AO)는 진입 안 함", cls: "ltr-mcard"}, membersBox),
    ui.card({title: "최근 거래", sub: "페이퍼 · 새 규칙 시작 뒤 · 청산 이유와 진입 때 추세 판단", cls: "ltr-tcard"}, tradesBox),
    h("div", {class: "ltr-two"},
      ui.card({title: "감독 청산", sub: "최근 7일 · 추세 뒤집힘 (시간 정리는 10/21 밤에 뺌)", cls: "ltr-supcard"}, sup),
      ui.card({title: "규칙", sub: "봇이 지금 쓰는 숫자 (설정 파일 그대로)", cls: "ltr-rulecard"}, rules)),
    ui.card({title: "최근 24시간 신호", sub: "봇이 남긴 이유 그대로 · 한국 시간", cls: "ltr-scard"}, sigHead, sigList));
  const main = h("div", {class: "ltr-body"}, hero, cards);
  const el = h("div", {class: "ltr stack"}, stateSlot, main,
    ui.note("보기만 하는 화면 · 판단은 봇이 1분마다 다시 읽고 이 화면은 15초마다 새로 읽어요 · 남은 시간은 1초마다 줄어요 · 판단 4개는 각 매매법 차트 화면과 같은 계산"));

  // ---------------------------------------------------------------- parts
  const tick = (node, until, fmtFn) => {
    st.ticks.push({node, until: Number(until), fmtFn});
    node.textContent = fmtFn(Number(until) - serverNow());
    return node;
  };
  function drawHero() {
    const t = st.t, now = serverNow();
    const x = heroOf(t, now);
    // a position the bot before it opened (전환 전): the bot only closes it (its record starts after it)
    const inh = t && t.state === "ok" && t.position && t.position.inherited && x.cls === "hold" ? t.position : null;
    hero.className = `ltr-hero ${x.cls}`;
    head.textContent = inh ? `전환 전 포지션 정리 중 · ${fmt.coin(inh.symbol)} ${SIDE(inh.side)}` : x.head;
    sub.textContent = x.sub;
    if (!t || t.state !== "ok") { put(chips); return; }
    const fz = freezeKo(t.bot, now);
    const age = ok(t.ts) ? now - Number(t.ts) : null;
    const pz = t.pause || {};
    put(chips,
      inh ? ui.pill(inh.inherited_ko || "전환 전 포지션", "warn", "새 봇이 켜지기 전에 열린 포지션이에요 · 새 봇이 손절 · 계단 익절 · 추세 뒤집힘 감독으로 닫아요 · 새 봇 성적에는 안 세요") : null,
      ui.pill(fz.ko, fz.days === 0 ? "warn" : "accent", "새 규칙은 2주 동안 바꾸지 않고 기록을 모은 뒤 검토해요"),
      t.bot && ok(t.bot.since) ? ui.pill(`새 규칙 시작 ${fmt.kst(t.bot.since)}`, "thin") : null,
      ui.pill(age != null ? `판단 ${fmt.dur(age / 1000)} 전` : "판단 시각 모름", age != null && age > 5 * MIN ? "warn" : "thin"),
      ui.pill(pz.paused ? "진입 쉬는 시간 (주말·발표·나스닥)" : pz.paused === false ? "진입 가능 시간" : "진입 시간 모름",
        pz.paused ? "warn" : pz.paused === false ? "good" : "thin", "주말(한국 시간 토·일) · 미국 경제 발표 앞뒤 30분 · 나스닥 개장 앞뒤 30분(한국 시간 22:00~23:00, 겨울 23:00~24:00)은 진입 안 해요 · 추세 판단은 계속"));
  }
  function drawMoney() {
    const s = st.s, t = st.t;
    const accts = (s && s.accts) || [];
    const tile = (k, v, sub2, cls, title) => h("div", {class: ["ltr-tile", cls || ""], role: "listitem", title},
      h("span", {class: "ltr-tk"}, k), h("b", {class: "ltr-tv num"}, v), sub2 ? h("span", {class: "ltr-ts num"}, sub2) : null);
    const items = [];
    for (const a of accts.filter((x) => x.kind === "live")) {
      if (a.state !== "ok") { items.push(tile(a.name_ko, "못 읽음", a.reason_ko || "", "na")); continue; }
      const td = a.today || {};
      const tone = ok(td.pnl) && td.pnl < 0 ? "down" : ok(td.pnl) && td.pnl > 0 ? "up" : "";
      const other = otherBotOf(a);                       // its wallet follows the other paper bot now (owners 10/23)
      items.push(tile(`${a.name_ko} 실거래`, ok(a.balance) ? fmt.usd(a.balance) : "—",
        `오늘 ${ok(td.pnl) ? signed(td.pnl) : "—"} · ${fmt.int(td.trades || 0)}번` + (a.halted ? " · 멈춤" : "") + (a.stale ? " · 기록 오래됨" : "")
          + (other ? ` · ${other} 따라감` : ""),
        a.halted ? "bad" : tone, other ? `거래소 실제 잔고 (실행기 기록) · 지금은 ${other}${josaObj(other)} 따라가요` : "거래소 실제 잔고 (실행기 기록)"));
    }
    const pa = accts.find((x) => x.id === "paper");
    if (pa && pa.state === "ok") items.push(tile("페이퍼(연습) 지갑", fmt.usd(pa.balance), "진짜 돈 아님", "paper"));
    const r = t && t.state === "ok" ? t.record : null;
    if (r) {
      const ex = ((t.next || {}).expect) || {};
      items.push(tile("새 봇 성적", r.n ? `${fmt.int(r.wins)}승 ${fmt.int(r.losses)}패` : "아직 거래 없음",
        r.n ? `승률 ${fmt.pct(r.win_rate, 0, false)} · ${signed(r.pnl)}`
          : ex.state === "ok" && ok(ex.per_weekday) ? `새 규칙 시작 뒤 · 재현(가상)은 평일 하루 약 ${Number(ex.per_weekday).toFixed(1)}번` : "새 규칙 시작 뒤", "rec"));
    }
    put(money, items.length ? items : h("p", {class: "ltr-sub"}, "지갑 기록을 불러오는 중"));
  }
  function liveRows(p) {
    const accts = ((st.s && st.s.accts) || []).filter((a) => a.kind === "live");
    if (!accts.length) return h("p", {class: "ltr-sub"}, "실행기 기록을 불러오는 중");
    const fol = p && Array.isArray(p.follow) ? p.follow : null;
    const none = fol && fol.length && fol.every((f) => f.state === "skip" || f.state === "none");
    return h("div", null, h("ul", {class: "ltr-list ltr-follow"}, accts.map((a) => {
      if (a.state !== "ok") return h("li", null, h("b", null, `${a.name_ko} `), "기록 못 읽음");
      const q = a.position;
      const f = fol ? fol.find((x) => x.id === a.id) : null;
      const other = otherBotOf(a);
      if (other) {                                      // it follows the other paper bot (owners 10/23): its position is that bot's
        return h("li", null, h("b", null, `${a.name_ko} `), `${other}${josaObj(other)} 따라가는 중`,
          q ? h("small", {class: "ltr-sub"}, `그 봇 포지션 ${fmt.coin(q.symbol)} ${SIDE(q.side)} (이 화면 숫자에 안 셈)`) : null);
      }
      if (!q) {
        return h("li", null, h("b", null, `${a.name_ko} `), idleKo(a, p, f),
          f && f.text ? h("small", {class: "ltr-sub"}, `실행기 기록 ${ok(f.ts) ? fmt.hm(f.ts) + " " : ""}· ${f.text}`) : null);
      }
      const price = priceOf(st.t, q.symbol);
      const roe = ok(price) && ok(q.entry) && ok(q.leverage) ? Number(q.leverage) * Number(q.side) * (Number(price) / Number(q.entry) - 1) : null;
      return h("li", null, h("b", null, `${a.name_ko} `), `${fmt.coin(q.symbol)} ${SIDE(q.side)} ${fmt.lev(q.leverage)} · 진입 ${fmt.price(q.entry)}`,
        roe != null ? h("span", {class: ["num", fmt.tone(roe)]}, ` · ROE ${fmt.pct(roe, 1)}`) : null,
        q.lock_roe != null ? ` · 자기 잠금 +${fmt.pct(q.lock_roe, 0, false)}` : " · 자기 잠금 전");
    })), none ? h("p", {class: "ltr-sub ltr-real"}, "실거래 두 계좌는 이 포지션을 들고 있지 않아요 · 이 포지션의 손익은 페이퍼(연습)에만 남아요") : null);
  }
  // 전환 전 포지션: opened by the bot before this one on the same paper account (answer: position.inherited, prev)
  function inheritedNote(t, p) {
    const prev = (t.prev || {}).bot_ko || "봇";
    return h("div", {class: "ltr-inh", role: "note"},
      h("b", null, "전환 전 포지션"),
      h("span", null, `예전 ${prev}가 ${fmt.kst(p.entry_time)}에 연 포지션이에요 · 새 봇(${fmt.kst((t.bot || {}).since)} 시작)이 `
        + (p.locked ? "첫 잠금에 가 있어 계단 익절로 이어서 정리해요"
          : "다음 1분 안에 \"전환 전 포지션 정리\"로 닫아요 (첫 잠금 전이라서)")),
      h("span", null, "닫힐 때까지 새 봇은 새로 들어가지 않아요 (한 번에 하나) · 이 거래는 새 봇 성적에 세지 않아요"));
  }
  function prevClosed(t) {
    const xs = (t.prev || {}).closed || [];
    if (!xs.length) return null;
    return h("div", {class: "ltr-inh done", role: "note"}, h("b", null, "전환 전 포지션 정리됨"),
      xs.map((x) => h("span", null, `${fmt.kst(x.exit_time)} · ${fmt.coin(x.symbol)} ${SIDE(x.side)} ${fmt.stratKo(x.strategy)} ${fmt.tfKo(x.tf)} · `
        + `${x.reason_ko || exitKo(x.reason)} · `, h("b", {class: ["num", fmt.tone(x.roe)]}, `순ROE ${fmt.pct(x.roe, 1)}`),
        " (새 봇 성적엔 안 셈)")));
  }
  function drawPos() {
    const t = st.t, p = t && t.position, now = serverNow();
    if (!t || t.state !== "ok") { put(posBox); return; }
    if (!p) {
      put(posBox, h("div", {class: "ltr-empty"}, h("b", null, "포지션 없음"),
        h("p", null, t.pullback_wait === false
          ? `추세와 같은 방향 신호가 오고 진입 전 검사를 통과하면 그 분에 바로 들어가요 (한 번에 하나${t.hold_entry ? " · 보류여도 반대 방향만 아니면 받아요" : ""}).`
          : "추세와 같은 방향 신호가 오고, 진입 전 검사를 통과하고, 되돌림 가격에 닿으면 들어가요 (한 번에 하나).")),
        prevClosed(t), h("h3", {class: "ltr-h3"}, "실거래 두 계좌"), liveRows(null));
      return;
    }
    const price = priceOf(t, p.symbol);
    const roe = ok(price) && ok(p.entry_price) && ok(p.leverage) ? Number(p.leverage) * Number(p.side) * (Number(price) / Number(p.entry_price) - 1) : null;
    const timed = ok(p.time_bars) && ok(p.deadline);          // no time_bars: no TIME exit (owners 10/21 night)
    const total = timed ? Number(p.time_bars) * (TF_MIN[p.tf] || 60) * MIN : 0;
    const left = timed ? Number(p.deadline) - now : null;
    const frac = total > 0 ? Math.max(0, Math.min(1, 1 - left / total)) : 0;
    const j = p.judge;
    const jc = judgeCell(j);
    const judgeKo = !p.judge_exit ? "꺼짐(설정)" : p.locked ? "첫 잠금 뒤라 꺼짐" : !j || j.error ? "판단을 못 읽음 · 청산 미룸(손절은 거래소에 걸려 있음)"
      : p.judge_against ? againstKo(p, j) : Number(j.raw) === Number(p.side) ? "같은 방향 유지 중" : "보류 · 반대 3/4가 되면 청산";
    const timeNode = h("b", {class: "num"});
    put(posBox,
      h("div", {class: "ltr-phead"},
        h("span", {class: ["side", Number(p.side) > 0 ? "long" : "short"]}, SIDE(p.side)),
        h("b", {class: "ltr-pcoin"}, fmt.coin(p.symbol)),
        h("span", {class: "ltr-sub"}, ` ${fmt.lev(p.leverage)} · ${fmt.stratKo(p.strategy)} ${fmt.tfKo(p.tf)}`),
        p.role ? ui.pill(p.role, "thin") : null),
      p.inherited ? inheritedNote(t, p) : null,
      h("dl", {class: "ltr-kv"},
        h("dt", null, "진입"), h("dd", {class: "num"}, `${fmt.price(p.entry_price)} · ${fmt.kst(p.entry_time)}`),
        h("dt", null, "지금"), h("dd", {class: "num"}, ok(price) ? fmt.price(price) : "—",
          roe != null ? h("span", {class: fmt.tone(roe)}, ` · ROE ${fmt.pct(roe, 1)} (수수료 전)`) : null),
        h("dt", null, p.locked ? "잠금선" : "손절선"), h("dd", {class: "num"}, fmt.price(p.stop), p.locked ? ` · +${fmt.pct(p.lock_roe, 0, false)} 잠금` : " · 순ROE −50%"),
        p.entry_judge ? h("dt", null, "진입 근거") : null,
        p.entry_judge ? h("dd", null, p.entry_held ? [ui.pill(HELD_KO, "warn", "상위 봉 판단이 보류일 때 들어간 거래예요 (보류 허용: 반대 방향만 막음)"), " "] : null,
          p.entry_judge, ok(p.entry_score) ? h("small", {class: "ltr-sub"}, ` · 점수 ${Number(p.entry_score).toFixed(2)}`) : null) : null),
      h("div", {class: "ltr-guards"},
        h("div", {class: ["ltr-guard", p.locked || !timed ? "off" : left <= 0 ? "fire" : ""]},
          h("span", {class: "ltr-gk"}, "⏱ 시간 정리"),
          !timed ? h("b", null, "없음 (10/21 밤에 뺌)") : p.locked ? h("b", null, "꺼짐 (첫 잠금 뒤)")
            : h("span", null, `진입 봉 ${p.time_bars}개 안에 첫 잠금 · 남은 시간 `, tick(timeNode, p.deadline, clock)),
          p.locked || !timed ? null : h("span", {class: "ltr-bar"}, h("i", {style: {"--v": frac.toFixed(4)}}))),
        h("div", {class: ["ltr-guard", p.locked || !p.judge_exit ? "off" : p.judge_against ? "fire" : ""]},
          h("span", {class: "ltr-gk"}, `🧭 ${fmt.tfKo(p.htf)} 추세`),
          h("span", null, h("b", {class: ["ltr-word", jc.cls]}, jc.word), ` · ${judgeKo}`)),
        h("div", {class: ["ltr-guard", p.locked ? "off" : ""]},
          h("span", {class: "ltr-gk"}, "↩ 빠른 청산"),
          h("span", null, p.locked ? "꺼짐 (첫 잠금 뒤)" : "같은 매매법이 반대 신호를 내면 바로 청산 (갈아타지 않음)"))),
      h("h3", {class: "ltr-h3"}, "실거래 두 계좌"), liveRows(p));
  }
  function drawGrid() {
    const t = st.t;
    stamp.textContent = ok(t.ts) ? `${fmt.kst(t.ts)} 기준` : "";
    const tfs = judgedTfs(t);
    mapSub.textContent = `끝난 봉만 봐요 · ${tfs.map((tf) => `${ENTRY_KO[TF_ENTRY[tf]]} 진입은 ${fmt.tfKo(tf)}`).join(", ")} · `
      + `4개 중 3개 이상 같은 쪽이면 추세${t.hold_entry ? " · 보류여도 반대 방향만 아니면 진입" : ""} · ADX 20 이상, 40 넘고 꺾이면 끝물`;
    const headRow = h("div", {class: "ltr-row ltr-hrow", role: "row"}, h("span", {role: "columnheader"}, "코인"),
      tfs.map((tf) => h("span", {role: "columnheader"}, MAP_HEAD_KO[tf])));
    const rows = COINS.filter((c) => t.coins && t.coins[c]).map((c) => {
      const price = priceOf(t, c);
      const cell = (tf) => {
        const j = t.coins[c][tf];
        const x = judgeCell(j);
        const a = allows(j, tf, t.hold_entry);
        const m = adxMeter(j && !j.error ? j.adx : null);
        return h("div", {class: ["ltr-cell", x.cls], role: "cell"},
          h("div", {class: "ltr-ctop"}, h("b", {class: "ltr-word"}, x.word),
            h("span", {class: ["ltr-allow", a.side > 0 ? "up" : a.side < 0 ? "down" : ""]}, a.ko)),
          h("small", {class: "ltr-sub"}, x.sub),
          j && !j.error ? h("span", {class: ["ltr-adx", m.zone], title: `ADX ${Math.round(Number(j.adx))} (20 미만 힘 약함 · 40 넘고 꺾이면 끝물)`},
            h("i", {style: {"--v": m.fill.toFixed(4)}})) : null,
          j && j.votes ? h("span", {class: "ltr-votes"}, JUDGES.map(([k, ko]) => h("span", {class: ["ltr-vote", Number(j.votes[k]) > 0 ? "up" : Number(j.votes[k]) < 0 ? "down" : ""], title: ko},
            voteMark(j.votes[k]), h("i", null, ko)))) : null);
      };
      return h("div", {class: "ltr-row", role: "row"},
        h("div", {class: "ltr-coin", role: "rowheader"}, h("b", null, fmt.coin(c)), price != null ? h("small", {class: "num"}, fmt.price(price)) : null),
        tfs.map(cell));
    });
    put(grid, h("div", {class: "ltr-table", role: "table", "aria-label": "코인별 추세 판단", style: {"--cols": String(tfs.length)}}, headRow, rows));
  }
  // nothing waits: what the bot looks at next (the closes, the directions it takes now, an open position, the next pause)
  function idleBox(t, now) {
    const nc = nextCloses(now);
    const take = takingNow(t);
    const p = t.position, np = (t.next || {}).pause, pz = t.pause || {};
    const left = h("span", {class: "num"});
    const same = np && ok(np.until) && fmt.mmdd(np.from) === fmt.mmdd(np.until);
    const ents = new Set(judgedTfs(t).map((tf) => TF_ENTRY[tf]));
    const closes = [["30m", "30분봉", nc.m30], ["1h", "1시간봉", nc.h1], ["4h", "4시간봉", nc.h4]].filter(([tf]) => ents.has(tf));
    return h("div", {class: "ltr-idle"},
      h("p", {class: "ltr-ihead"}, t.pullback_wait === false ? "지금 들어갈 신호 없음 · 검사를 통과한 신호는 그 분에 바로 들어가요" : "지금 기다리는 신호 없음"),
      h("ul", {class: "ltr-list ltr-ilist"},
        h("li", null, h("span", {class: "ltr-ik"}, "다음 신호 볼 때"),
          `${closes.map(([, ko, at]) => `${ko} ${fmt.hm(at)}`).join(" · ")} (봉이 끝날 때 매매법 신호가 나와요)`),
        h("li", null, h("span", {class: "ltr-ik"}, "지금 받는 방향"),
          take.length ? take.join(" · ") : t.hold_entry ? "없음 · 모든 코인이 힘 약함·끝물이라 신호가 와도 안 들어가요"
            : "없음 · 모든 코인이 보류·힘 약함·끝물이라 신호가 와도 안 들어가요"),
        p ? h("li", {class: "warn"}, h("span", {class: "ltr-ik"}, "새 진입"),
          p.inherited ? "안 해요 · 전환 전 포지션이 열려 있어요 (한 번에 하나) · 닫히면 받기 시작해요" : "안 해요 · 포지션이 열려 있어요 (한 번에 하나)") : null,
        !pz.paused && np && ok(np.from) ? h("li", null, h("span", {class: "ltr-ik"}, "다음 쉬는 시간"),
          h("span", null, `${np.ko} · ${fmt.kst(np.from)}~${ok(np.until) ? (same ? fmt.hm(np.until) : fmt.kst(np.until)) : ""} · `,
            tick(left, np.from, (ms) => (ms > 0 ? `${clock(ms)} 뒤` : "지금")))) : null));
  }
  function drawWaits() {
    const t = st.t, now = serverNow();
    const ws = (t.waits || []).filter((w) => Number(w.until) > now - MIN);
    // 바로 진입 (trend.pullback_wait false, the owners' config since 10/22): no pullback card unless a wait is still left
    const pull = t.pullback_wait !== false || ws.length > 0;
    wTitle.textContent = pull ? "되돌림 기다리는 신호" : "다음 진입";
    wSub.textContent = pull ? "추세와 같은 방향 신호 · 진입 봉 하나 동안 기다리고 안 오면 버려요"
      : "추세와 같은 방향 신호가 검사를 통과하면 그 분에 바로 들어가요 (되돌림 안 기다림)";
    put(waits, ws.length ? h("ul", {class: "ltr-list ltr-wlist"}, ws.map((w) => {
      const price = priceOf(t, w.symbol);
      const gap = waitGap(w, price);
      const span = Number(w.until) - Number(w.t0);
      const frac = span > 0 ? Math.max(0, Math.min(1, (now - Number(w.t0)) / span)) : 1;
      const leftNode = h("span", {class: "num"});
      return h("li", {class: "ltr-witem"},
        h("div", null, h("b", null, `${fmt.coin(w.symbol)} ${SIDE(w.side)}`), ` ${fmt.stratKo(String(w.member || "").split("@")[0])} ${fmt.tfKo(w.tf)}`),
        h("div", {class: "ltr-sub"}, h("span", {class: "num"}, fmt.price(w.level)), " 닿으면 진입",
          gap != null ? h("span", {class: "num"}, ` · 지금 ${fmt.price(price)} (${(gap * 100).toFixed(2)}% 남음)`) : null,
          " · ", tick(leftNode, w.until, (ms) => (ms > 0 ? `${clock(ms)} 뒤 끝` : "끝남"))),
        h("span", {class: "ltr-bar"}, h("i", {style: {"--v": frac.toFixed(4)}})),
        w.judge ? h("small", {class: "ltr-sub"}, w.judge) : null);
    })) : idleBox(t, now));
    // the bot's own 쉬기 (a member after losses, a coin after a loss, the daily limit): off in the owners' config (10-21
    // night "쉬기는 빼주고"); shown only when a config turns one on
    const nb = t.numbers || {};
    const pausing = nb.member_losses != null || nb.coin_pause_h != null || nb.daily_loss != null;
    pauseHead.hidden = pauses.hidden = !pausing;
    const pz = t.pauses || {};
    const items = [];
    if (pz.day) items.push(h("li", {class: "bad"}, h("b", null, "하루 손실 한도 "), pz.day[0], ` · ${fmt.kst(pz.day[1])}부터 다시`));
    for (const [label, v] of Object.entries(pz.members || {})) {
      items.push(h("li", null, h("b", null, `${fmt.stratKo(label.split("@")[0])} ${fmt.tfKo(label.split("@")[1])} `), v[0]));
    }
    for (const c of pz.coins || []) items.push(h("li", null, c[2]));
    put(pauses, items.length ? h("ul", {class: "ltr-list"}, items) : h("p", {class: "ltr-sub"}, "쉬는 매매법·코인이 없어요"));
  }
  function drawFunnel() {
    const f = st.t.funnel;
    if (!f) { put(funnelBox, ui.empty("신호 기록을 못 읽었어요")); return; }
    const pull = st.t.pullback_wait !== false || Number(f.touched) > 0;      // 바로 진입: no pullback step
    const steps = [["신호", f.signals, "진입 매매법 신호"], ["검사 통과", f.passed, "추세 판단 · 진입 자리 · 쉬기를 통과"],
      pull ? ["되돌림 닿음", f.touched, "기다린 가격에 닿음"] : null, ["진입", f.entered, "페이퍼가 들어감"]].filter(Boolean);
    const top = Math.max(1, Number(f.signals) || 0);
    const bmax = Math.max(1, ...(f.blocked || []).map((b) => b.n));
    put(funnelBox,
      h("div", {class: "ltr-steps", style: {"--n": String(steps.length)}}, steps.map(([k, n, title], i) => h("div", {class: ["ltr-step", i === steps.length - 1 ? "last" : ""], title},
        h("b", {class: "num"}, fmt.int(n || 0)), h("span", null, k),
        h("span", {class: "ltr-bar"}, h("i", {style: {"--v": ((Number(n) || 0) / top).toFixed(4)}}))))),
      (f.blocked || []).length ? h("ul", {class: "ltr-list ltr-blocks"}, f.blocked.map((b) => h("li", null,
        h("span", {class: "ltr-bk"}, b.ko), h("span", {class: "ltr-bar"}, h("i", {style: {"--v": (b.n / bmax).toFixed(4)}})), h("b", {class: "num"}, fmt.int(b.n)))))
        : h("p", {class: "ltr-sub"}, f.signals ? "걸린 신호가 없어요" : f.cut ? "새 봇이 켜진 뒤 아직 신호가 없어요" : "오늘은 아직 신호가 없어요"),
      f.cut && ok(f.from) ? h("p", {class: "ltr-sub"}, `새 봇 시작 ${fmt.hm(f.from)}부터 세요 · 그 전 신호와 진입은 예전 봇 것이라 빼요`) : null);
  }
  function drawRecord() {
    const r = st.t.record;
    if (!r || !r.n) {
      const ex = (st.t.next || {}).expect || {};
      const lines = expectLines(ex);
      put(recordBox, ui.empty("새 규칙으로 닫힌 거래가 아직 없어요"),
        lines.length ? h("div", {class: "ltr-exp"},
          h("p", {class: "ltr-ehead"}, ui.pill("가상 · 재현", "thin"), ` ${expectHead(ex)}`),
          h("ul", {class: "ltr-list ltr-rlist"}, lines.map((x) => h("li", null, x))),
          ex.note_ko ? h("p", {class: "ltr-sub"}, ex.note_ko) : null,
          h("a", {class: "ltr-more", href: (ctx.href || href)("livebots", "expect")}, "재현 비교 →")) : null);
      return;
    }
    put(recordBox,
      h("div", {class: "ltr-stats"},
        ui.stat("거래", `${fmt.int(r.n)}번`, `${fmt.int(r.wins)}승 ${fmt.int(r.losses)}패`),
        ui.stat("승률", fmt.pct(r.win_rate, 0, false), r.n < 20 ? "표본 적음" : ""),
        ui.stat("순손익", signed(r.pnl), `순ROE 합 ${fmt.pct(r.roe_sum, 0)}`),
        ui.stat("최고 / 최저", `${fmt.pct(r.best, 0)} / ${fmt.pct(r.worst, 0)}`, "순ROE")),
      h("div", {class: "ltr-stack", role: "img", "aria-label": "청산 이유 나눔"}, (r.by_exit || []).map((b) =>
        h("i", {class: "ltr-x-" + b.id, style: {"--v": (b.n / Math.max(1, r.n)).toFixed(4)}, title: `${b.ko} ${b.n}번`}))),
      h("ul", {class: "ltr-list ltr-legend"}, (r.by_exit || []).map((b) => h("li", null,
        h("i", {class: "ltr-sw ltr-x-" + b.id, "aria-hidden": "true"}), `${b.ko} ${fmt.int(b.n)}번 · ${fmt.int(b.wins)}승 · `,
        h("span", {class: ["num", fmt.tone(b.pnl)]}, signed(b.pnl))))));
  }
  function drawMembers() {
    const ms = st.t.members || [];
    memTitle.textContent = ms.length ? `진입 매매법 ${ms.length}개` : "진입 매매법";
    put(membersBox, ms.length ? ms.map((m) => h("div", {class: ["ltr-mem", m.paused ? "paused" : ""], role: "listitem"},
      h("div", {class: "ltr-mtop"}, h("b", null, fmt.stratKo(m.strategy)), m.role ? ui.pill(m.role, "thin") : null,
        m.side_only ? ui.pill(m.side_only === "short" ? "숏만" : "롱만", "warn") : null),
      h("span", {class: "ltr-sub"}, `${fmt.tfKo(m.tf)} 진입 · ${fmt.tfKo(m.htf)} 추세`),
      h("div", {class: "ltr-mrow"},
        h("span", null, "오늘 신호 ", h("b", {class: "num"}, fmt.int(m.today))),
        h("span", null, m.trades ? `${fmt.int(m.wins)}승 ${fmt.int(m.losses)}패` : "거래 없음"),
        m.trades ? h("span", {class: ["num", fmt.tone(m.roe_sum)]}, `순ROE 합 ${fmt.pct(m.roe_sum, 0)}`) : null),
      m.paused ? h("span", {class: "ltr-mpause"}, `쉬는 중 · ${fmt.kst(m.paused.until)}까지`)
        : m.last ? h("span", {class: "ltr-sub"}, "마지막 ", ui.pill(exitKo(m.last.exit_reason), EXIT_CLS[m.last.exit_reason] || "thin"),
          h("span", {class: ["num", fmt.tone(m.last.roe)]}, ` ${fmt.pct(m.last.roe, 1)}`)) : null))
      : ui.empty("매매법 목록을 못 읽었어요"));
  }
  function drawTrades() {
    const ts = st.t.trades || [];
    put(tradesBox, ts.length ? h("ul", {class: "ltr-list ltr-tlist"}, ts.slice(0, 12).map((x) => h("li", {class: "ltr-trow"},
      h("span", {class: "num ltr-t"}, fmt.kst(x.exit_time)),
      h("span", {class: "ltr-tw"}, h("b", null, `${fmt.coin(x.symbol)} ${SIDE(x.side)}`), ` ${fmt.stratKo(x.strategy)} ${fmt.tfKo(x.tf)}`),
      ui.pill(exitKo(x.reason), EXIT_CLS[x.reason] || "thin"),
      h("b", {class: ["num", fmt.tone(x.roe)]}, fmt.pct(x.roe, 1)),
      x.why || x.entry_judge ? h("small", {class: "ltr-sub ltr-tsub"}, [x.why, x.entry_judge ? `진입 때 ${x.entry_judge}${x.entry_held ? ` (${HELD_KO})` : ""}` : null].filter(Boolean).join(" · ")) : null)))
      : ui.empty("새 규칙으로 닫힌 거래가 아직 없어요"));
  }
  function drawRest() {
    const t = st.t;
    const sig = t.signals || {};
    const kos = {};
    for (const r of sig.rows || []) kos[r.cat] = r.cat_ko;
    put(sigHead, countsInOrder(sig.counts).map((c) => ui.pill(`${kos[c.id] || c.id} ${fmt.int(c.n)}`, ["entered", "submitted", "pulled"].includes(c.id) ? "good" : "thin")),
      sig.cut && ok(sig.from) ? h("span", {class: "ltr-sub"}, `새 봇 시작 ${fmt.kst(sig.from)} 뒤 신호만 (그 전은 예전 봇)`) : null);
    put(sigList, (sig.rows || []).length ? ui.disclosure(`신호 ${fmt.int(sig.rows.length)}개 펼치기`, h("ul", {class: "ltr-list ltr-siglist"},
      sig.rows.slice(0, 60).map((r) => h("li", {class: "ltr-s-" + r.cat},
        h("span", {class: "num ltr-t"}, fmt.kst(r.bar_close)), " ",
        h("b", null, `${fmt.coin(r.symbol)} ${SIDE(r.side)}`), ` ${fmt.stratKo(r.strategy)} ${fmt.tfKo(r.tf)} · `,
        h("span", {class: "ltr-cat"}, r.cat_ko),
        r.why ? h("small", {class: "ltr-sub"}, r.why) : null))))
      : ui.empty(sig.cut ? `새 봇이 켜진 뒤 아직 신호가 없어요 · 매매법 신호는 ${entryTfsKo(t)} 봉이 끝날 때 나와요` : "최근 24시간 신호가 없어요"));
    put(sup, (t.sup || []).length ? h("ul", {class: "ltr-list"}, t.sup.map((x) => h("li", null,
      h("span", {class: "num ltr-t"}, fmt.kst(x.exit_time)), " ", h("b", null, `${fmt.coin(x.symbol)} ${SIDE(x.side)}`),
      x.inherited ? [" ", ui.pill("전환 전 포지션", "warn", "새 봇이 켜지기 전에 열린 포지션 · 새 봇 성적에 안 셈")] : null,
      ` ${fmt.stratKo(x.strategy)} ${fmt.tfKo(x.tf)} · ${x.reason_ko} · `,
      h("span", {class: ["num", fmt.tone(x.roe)]}, `순ROE ${fmt.pct(x.roe, 1)}`),
      x.why ? h("small", {class: "ltr-sub"}, x.why) : null)))
      : ui.empty("최근 7일 감독 청산이 없어요"));
    put(rules, (t.rules || []).length ? h("ul", {class: "ltr-list ltr-rlist"}, t.rules.map((x) => h("li", null, x)),
      h("li", {class: "ltr-sub"}, "2단계(준비 중): 급변 · 경제 발표 직전 손절 당기기 · 실행기가 거래소 손절을 같이 옮기는 시험 뒤에 넣어요"))
      : ui.empty("규칙 기록이 없어요"));
  }
  // the judgment changes of the last 24 h (the 일지 tab's "trend" rows: the 추세 차트 tab's recomputation)
  function drawChanges() {
    const j = st.j;
    if (!j || !Array.isArray(j.events)) { put(changes); return; }
    const rows = j.events.filter((e) => e && e.kind === "trend").sort((a, b) => b.t - a.t).slice(0, CHANGES_KEEP);
    const jd = j.judge || {};
    put(changes, h("h3", {class: "ltr-h3"}, "최근 24시간 바뀐 판단"),
      rows.length ? h("ul", {class: "ltr-list ltr-clist"}, rows.map((e) => h("li", null,
        h("span", {class: "num ltr-t"}, fmt.kst(e.t)), " ", h("b", {class: ["ltr-word", e.tone || "hold"]}, e.text),
        e.detail ? h("small", {class: "ltr-sub"}, e.detail) : null)))
        : h("p", {class: "ltr-sub"}, jd.pending ? "판단 기록을 불러오는 중이에요 (몇 초 뒤 보여요)"
          : jd.state === "ok" || jd.state === "partial" ? "최근 24시간 동안 바뀐 판단이 없어요" : jd.reason_ko || "판단 기록을 못 읽었어요"),
      h("a", {class: "ltr-more", href: (ctx.href || href)("livebots", "journal")}, "일지에서 더 보기 →"));
  }
  async function loadJournal() {
    st.jAt = Date.now();
    let d;
    try { d = await ctx.api(`${JOURNAL_API}?hours=24`); }
    catch (e) { return; }                         // the map stands without it; tried again next minute
    if (!ctx.alive()) return;
    st.j = d;
    if (d && d.judge && d.judge.pending) st.jAt -= JOURNAL_MS - REFRESH_MS;     // still fetching bars: ask sooner
    drawChanges();
  }
  function draw() {
    const t = st.t;
    st.ticks = [];
    drawHero();
    drawMoney();
    if (!t || t.state !== "ok") {
      cards.hidden = true;
      put(stateSlot, t && t.state === "off"
        ? h("div", {class: "lb-state"}, ui.pill("꺼짐", "thin"), h("span", null, ` ${t.reason_ko}`))
        : sourceState(t, "추세판단 봇"));
      return;
    }
    cards.hidden = false;
    put(stateSlot);
    drawPos(); drawGrid(); drawWaits(); drawFunnel(); drawRecord(); drawMembers(); drawTrades(); drawRest(); drawChanges();
  }
  function onTick() {
    for (const k of st.ticks) k.node.textContent = k.fmtFn(k.until - serverNow());
    if (st.t && st.t.state === "ok" && (st.t.position || (st.t.pause || {}).paused)) sub.textContent = heroOf(st.t, serverNow()).sub;
  }

  async function load() {
    if (st.busy) return;
    st.busy = true;
    let d;
    try { d = await ctx.api(API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      if (st.t) { put(stateSlot, ui.staleNote(e, st.okAt, () => load().catch(() => {}))); ui.dim(main, true); }
      else put(stateSlot, ui.errorBox(e, () => load()));
      throw e;
    } finally { st.busy = false; }
    if (!ctx.alive()) return;
    ui.dim(main, false);
    st.t = d; st.okAt = Date.now();
    draw();
    if (d && d.state === "ok" && Date.now() - st.jAt >= JOURNAL_MS) loadJournal();
  }
  if (hub && hub.get && hub.get()) st.s = hub.get();
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  ctx.every(TICK_MS, onTick, {now: false});
  // the Korean names come with the board, the live price with the ticker: draw again when they arrive
  if (ctx.watch) {
    ctx.watch("board", () => { if (st.t && st.t.state === "ok") draw(); });
    ctx.watch("ticker", () => {
      if (!st.t || st.t.state !== "ok") return;
      st.ticks = st.ticks.filter((k) => !posBox.contains(k.node) && !waits.contains(k.node));
      drawPos(); drawWaits();
    });
  }
  return {el, set(s) {
    if (!s) return;
    st.s = s;
    const kk = kickKo();
    if (kick.textContent !== kk) kick.textContent = kk;
    drawMoney();
    if (st.t && st.t.state === "ok") { st.ticks = st.ticks.filter((k) => !posBox.contains(k.node)); drawPos(); }
  }};
}
