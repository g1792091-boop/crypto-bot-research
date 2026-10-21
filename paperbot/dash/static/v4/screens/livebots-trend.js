// 실거래 › 추세 (#/livebots/trend; owners 10/21 추세판단 봇: "추세형 매매법은 진입 안 하고 추세만 보는 거"). What the paper bot
// both executors follow judged, read-only (dash/more/livetrend.py, /api/v4/livebots/trend, every 30 s):
//   추세 판단   every coin's last closed 1h (for the 30m entries) and 4h (for the 1h entries) judgment: 상승 / 하락 / 보류,
//              the four judges (V3.9 · EMA·DMI·ADX · OBV 추세형 · 일목·AO) as ▲ ▼ –, ADX and rising or falling, 끝물, 힘 약함
//   기다리는 신호  the signals waiting for their pullback: the level, until when
//   쉬는 중     the daily loss stop, the members and the coin-sides taking a break
//   최근 24시간  the entry members' signals by what became of them, with the bot's own reason
//   감독 청산    the supervisor's exits of the last 7 days (추세 판단 뒤집힘 · 시간 정리) and why
// HONESTY: unread = 못 읽음 + why (never a guess); the judgment of a coin the bot could not read says so; nothing here
// changes the bot.
import {h, put, ui, fmt, serverNow} from "../core/pb.js";
import {sourceState} from "./livebots-kit.js";

export const API = "/api/v4/livebots/trend";
const REFRESH_MS = 30 * 1000;
const COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"];
const JUDGES = [["V39", "V3.9"], ["S6", "EMA·DMI·ADX"], ["OBV", "OBV"], ["N12", "일목·AO"]];
export const DIR_KO = {1: "상승", "-1": "하락", 0: "보류"};
const CAT_ORDER = ["entered", "pulled", "pullback_wait", "nopull", "trend", "spot", "member_pause", "coin_pause", "daily",
  "chase", "chase_unread", "weekend", "macro", "usopen", "trend_unread", "late", "when", "submitted", "config", "other"];
const SIDE = (s) => (Number(s) > 0 ? "롱" : "숏");

// ---------------------------------------------------------------- pure (node tests: tests/test_livetrend.py)
/** {cls, word, sub} of one judgment ({error} when unread). */
export function judgeCell(j) {
  if (!j || j.error) return {cls: "na", word: "못 읽음", sub: (j && j.error) || "아직 판단 없음"};
  const d = Number(j.dir);
  const raw = Number(j.raw);
  let word = DIR_KO[d] ?? "보류";
  if (d === 0 && raw) word = `보류 (${DIR_KO[raw]} 유지 확인 중)`;
  const adx = Number(j.adx), prev = Number(j.adx_prev);
  const bits = [`상승 ${(Object.values(j.votes || {})).filter((v) => v > 0).length}·하락 ${(Object.values(j.votes || {})).filter((v) => v < 0).length}`];
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

// ---------------------------------------------------------------- the view
export function trendView(ctx) {
  const st = {d: null, okAt: 0, busy: false};
  const stateSlot = h("div", {class: "lb-slot"});
  const grid = h("div", {class: "lbt-grid"});
  const waits = h("div", {class: "lbt-waits"});
  const pauses = h("div", {class: "lbt-pauses"});
  const sigHead = h("div", {class: "lbt-chips"});
  const sigList = h("div", {class: "lbt-sigs"});
  const sup = h("div", {class: "lbt-sup"});
  const rules = h("div", {class: "lbt-rules"});
  const stamp = h("span", {class: "lbt-stamp"});
  const main = h("div", {class: "lbt-body"},
    ui.card({title: "코인별 추세 판단", sub: "끝난 봉만 봐요 · 30분 진입은 1시간, 1시간 진입은 4시간 · 4개 중 3개 이상 같은 쪽이면 추세", cls: "lbt-judge", acts: [stamp]}, grid),
    h("div", {class: "lbt-two"},
      ui.card({title: "되돌림 기다리는 신호", sub: "추세와 같은 방향 신호 · 진입 봉 하나 동안 기다리고 안 오면 버려요", cls: "lbt-wcard"}, waits),
      ui.card({title: "쉬는 중", sub: "하루 손실 한도 · 손실 2번 연속 매매법 · 손실 뒤 코인·방향", cls: "lbt-pcard"}, pauses)),
    ui.card({title: "최근 24시간 신호", sub: "진입 매매법의 신호가 어떻게 됐나 · 봇이 남긴 이유 그대로 · 한국 시간", cls: "lbt-scard"}, sigHead, sigList),
    ui.card({title: "감독 청산", sub: "첫 잠금 전에만 · 상위 봉 판단 뒤집힘 · 진입 봉 4개 안에 첫 잠금 못 감 · 최근 7일", cls: "lbt-supcard"}, sup),
    ui.card({title: "규칙", sub: "봇이 지금 쓰는 숫자 (설정 파일 그대로)", cls: "lbt-rcard"}, rules));
  const el = h("div", {class: "lbt stack"}, stateSlot, main,
    ui.note("보기만 하는 화면 · 판단은 봇이 1분마다 다시 읽고 이 화면은 30초마다 새로 읽어요 · 판단 4개의 선은 각 매매법 차트 화면과 같은 계산이에요"));

  function draw(d) {
    if (!d || d.state !== "ok") {
      main.hidden = true;
      put(stateSlot, d && d.state === "off"
        ? h("div", {class: "lb-state"}, ui.pill("꺼짐", "thin"), h("span", null, ` ${d.reason_ko}`))
        : sourceState(d, "추세 판단"));
      return;
    }
    main.hidden = false;
    put(stateSlot, d.age_ms > 5 * 60 * 1000
      ? h("div", {class: "lb-state bad"}, ui.pill("오래됨", "warn"), h("span", null, ` 판단이 ${fmt.ago(d.ts, serverNow())} 기록이에요 (봇이 멈췄는지 봇 상태를 보세요)`))
      : null);
    stamp.textContent = `${fmt.kst(d.ts)} 기준`;
    // 추세 판단: one row a coin, 1h and 4h
    const head = h("div", {class: "lbt-row lbt-hrow", role: "row"}, h("span", {role: "columnheader"}, "코인"),
      h("span", {role: "columnheader"}, "1시간 (30분 진입용)"), h("span", {role: "columnheader"}, "4시간 (1시간 진입용)"));
    const rows = COINS.filter((c) => d.coins && d.coins[c]).map((c) => {
      const cell = (tf) => {
        const j = d.coins[c][tf];
        const x = judgeCell(j);
        return h("div", {class: ["lbt-cell", x.cls], role: "cell"},
          h("b", {class: "lbt-word"}, x.word),
          h("small", {class: "lbt-sub"}, x.sub),
          j && j.votes ? h("span", {class: "lbt-votes"}, JUDGES.map(([k, ko]) => h("span", {class: ["lbt-vote", Number(j.votes[k]) > 0 ? "up" : Number(j.votes[k]) < 0 ? "down" : ""], title: ko},
            voteMark(j.votes[k]), h("i", null, ko)))) : null);
      };
      return h("div", {class: "lbt-row", role: "row"}, h("b", {class: "lbt-coin", role: "rowheader"}, fmt.coin(c)), cell("1h"), cell("4h"));
    });
    put(grid, h("div", {class: "lbt-table", role: "table", "aria-label": "코인별 추세 판단"}, head, rows));
    // 기다리는 신호
    const now = serverNow();
    put(waits, (d.waits || []).length ? h("ul", {class: "lbt-list"}, d.waits.map((w) => h("li", null,
      h("b", null, `${fmt.coin(w.symbol)} ${SIDE(w.side)}`), ` ${fmt.stratKo(String(w.member || "").split("@")[0])} ${fmt.tfKo(w.tf)} · `,
      h("span", {class: "num"}, fmt.price(w.level)), " 닿으면 진입 · ",
      h("span", {class: "num"}, Number(w.until) > now ? `${fmt.hm(w.until)}까지 (${fmt.dur((Number(w.until) - now) / 1000)} 남음)` : "끝남"),
      w.judge ? h("small", {class: "lbt-sub"}, w.judge) : null)))
      : ui.empty("지금 기다리는 신호가 없어요"));
    // 쉬는 중
    const pz = d.pauses || {};
    const items = [];
    if (pz.day) items.push(h("li", {class: "bad"}, h("b", null, "하루 손실 한도 "), pz.day[0], ` · ${fmt.kst(pz.day[1])}부터 다시`));
    for (const [label, v] of Object.entries(pz.members || {})) items.push(h("li", null, h("b", null, `${fmt.stratKo(label.split("@")[0])} ${fmt.tfKo(label.split("@")[1])} `), v[0]));
    for (const c of pz.coins || []) items.push(h("li", null, c[2]));      // the bot's words already name the coin and side
    put(pauses, items.length ? h("ul", {class: "lbt-list"}, items) : ui.empty("쉬는 매매법·코인이 없어요"));
    // 최근 24시간
    const sig = d.signals || {};
    const kos = {};
    for (const r of sig.rows || []) kos[r.cat] = r.cat_ko;
    put(sigHead, countsInOrder(sig.counts).map((c) => ui.pill(`${kos[c.id] || c.id} ${fmt.int(c.n)}`, ["entered", "pulled"].includes(c.id) ? "good" : "thin")));
    put(sigList, (sig.rows || []).length ? h("ul", {class: "lbt-list lbt-siglist"}, sig.rows.slice(0, 40).map((r) => h("li", {class: "lbt-s-" + r.cat},
      h("span", {class: "num lbt-t"}, fmt.kst(r.bar_close)), " ",
      h("b", null, `${fmt.coin(r.symbol)} ${SIDE(r.side)}`), ` ${fmt.stratKo(r.strategy)} ${fmt.tfKo(r.tf)} · `,
      h("span", {class: "lbt-cat"}, r.cat_ko),
      r.why ? h("small", {class: "lbt-sub"}, r.why) : null)))
      : ui.empty("최근 24시간 신호가 없어요"));
    // 감독 청산
    put(sup, (d.sup || []).length ? h("ul", {class: "lbt-list"}, d.sup.map((t) => h("li", null,
      h("span", {class: "num lbt-t"}, fmt.kst(t.exit_time)), " ", h("b", null, `${fmt.coin(t.symbol)} ${SIDE(t.side)}`),
      ` ${fmt.stratKo(t.strategy)} ${fmt.tfKo(t.tf)} · ${t.reason_ko} · `,
      h("span", {class: ["num", fmt.tone(t.roe)]}, `순ROE ${fmt.pct(t.roe, 1)}`),
      t.why ? h("small", {class: "lbt-sub"}, t.why) : null)))
      : ui.empty("최근 7일 감독 청산이 없어요"));
    put(rules, (d.rules || []).length ? h("ul", {class: "lbt-list"}, d.rules.map((x) => h("li", null, x))) : ui.empty("규칙 기록이 없어요"));
  }

  async function load() {
    if (st.busy) return;
    st.busy = true;
    let d;
    try { d = await ctx.api(API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      if (st.d) { put(stateSlot, ui.staleNote(e, st.okAt, () => load().catch(() => {}))); ui.dim(main, true); }
      else { put(stateSlot, ui.errorBox(e, () => load())); main.hidden = true; }
      throw e;
    } finally { st.busy = false; }
    if (!ctx.alive()) return;
    ui.dim(main, false);
    st.d = d; st.okAt = Date.now();
    draw(d);
  }
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  return {el, set() {}};
}
