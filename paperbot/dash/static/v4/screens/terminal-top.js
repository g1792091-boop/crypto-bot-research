// 터미널 top strip (term v2, owners 10/06: "HelloQuant 터미널처럼 한 줄로 읽히게"): the coin and its big price (a teal /
// pink glow only when the price really moved), the 24 h change, the 24 h quote volume, funding and the time to the next
// funding, then 급등 · 급락 · 음펀비 over EVERY Binance USD-M perpetual (/api/v4/movers: the server asks Binance twice a
// minute at most for everybody; a "시장" chip says 시장 전체 (우리 봇 아님) in its tooltip, owners 10/06 ~14:00), the
// session and the KST clock. Under it one slow line of the latest real AI meeting conclusions (/api/office: finished
// meetings' decision lines; '회의 중' only from office.running). The office is read through the shared store like 홈
// (every 30 s and when a room changes).
import {h, put, fmt, store, motion, bars, serverNow, sound} from "../core/pb.js";
import {countdown, fundPct} from "./positions-book.js";
import {hit} from "./terminal-live.js";
import {MARKET_LABEL, marketChip} from "./terminal-kit.js";
import {topStats} from "./terminal-stats.js";      // term-plus: 미결제약정 · 롱/숏 · 24시간 범위 (terminal-stats.js)
import {usdKo} from "./market-live.js";

const FUND_HOT = 0.0005;          // funding of 0.05 % or more (5 times the usual 0.01 %) gets the caution colour, nothing below it
const RELAY_FRESH_MS = 6000;      // the selected coin's relay price this fresh keeps the big price (the ticker is older)

const two = (x) => String(x).padStart(2, "0");
const clockKst = (ms) => { const d = new Date(ms + 9 * 3.6e6); return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}:${two(d.getUTCSeconds())}`; };
const clean = (t) => String(t || "").replace(/^\s*🧾\s*/u, "").trim();
const pct2 = (v) => fmt.pctOf(v, 2, true);

/** topBar(ctx, st) -> {el, setSym, onTicker(map), onRelay, onTick, tick()} */
export function topBar(ctx, st) {
  const symEl = h("b", {class: "term-sym"}), perp = h("span", {class: "term-perp"}, "무기한 · 모의");
  const px = h("b", {class: "term-px num"}, "—"), chg = h("span", {class: "term-chg num"}, "");
  const stat = (k, cls) => { const v = h("b", {class: "num"}, "—"); return {v, el: h("div", {class: ["term-st", cls || ""]}, h("span", null, k), v)}; };
  const vol = stat("24시간 거래대금"), fund = stat("펀딩 / 다음까지", "fund");
  const fundK = fund.el.firstChild;
  const extra = topStats(ctx, st);
  const sess = h("span", {class: "term-sess"}), clock = h("b", {class: "term-clock num"}, "—");
  // the live dot: lit while the market-trade relay is really connected, one pulse per real relay message
  const liveDot = h("i", {class: "term-live", "aria-hidden": "true"});
  const clockBox = h("div", {class: "term-clockbox", title: "한국 시각 (서버 시계 기준)"}, liveDot, clock, h("small", null, "KST"));
  let relayAt = 0;
  // the live sound starts only from a tap (a browser rule): while it is off or waiting for that tap, a small button
  // here says so and opens the header speaker's menu (the same switch, core/sound.js); gone once the sound plays
  const sndHint = h("button", {type: "button", class: "term-snd", hidden: true, onclick: () => { const b = document.getElementById("sndbtn"); if (b) b.click(); }});
  const paintSnd = () => {
    const off = !sound.cfg.on, wait = sound.waiting();
    sndHint.hidden = !(off || wait);
    sndHint.textContent = off ? "소리 켜기" : "한 번 누르면 소리 시작";
    sndHint.title = "실시간 체결 소리 (실제 바이낸스 체결 · 우리 봇 진입·익절·손절)";
  };
  paintSnd();
  ctx.on("sound:cfg", paintSnd);

  // 급등 · 급락 · 음펀비 (the whole market): one item each, the top 3 in the title
  const mover = (k, tone) => {
    const s = h("b", {class: "term-mvs"}, "—"), v = h("span", {class: ["term-mvv", "num", tone]}, "");
    return {s, v, el: h("div", {class: "term-mv"}, h("span", {class: "term-mvk"}, k), h("span", {class: "term-mvl"}, s, v))};
  };
  const mUp = mover("급등", "up"), mDn = mover("급락", "down"), mNeg = mover("음펀비", "down");
  // the whole market's: a "시장" chip (its tooltip has the words; owners 10/06 ~14:00: the terminal's footer says it once)
  const mWhen = h("span", {class: "term-mvwhen num"}, "");
  const mCap = h("span", {class: "term-mvcap"}, marketChip(`급등 · 급락 · 음펀비: 바이낸스 USD-M 무기한 전체에서 1분마다 (${MARKET_LABEL})`), mWhen);
  const movers = h("div", {class: "term-movers", role: "group", "aria-label": `급등 · 급락 · 음펀비: 바이낸스 USD-M 무기한 ${MARKET_LABEL}`},
    mCap, mUp.el, mDn.el, mNeg.el);

  // the meetings line: a label, a running count (real), the conclusions (duplicated once for a seamless loop; the copy is
  // hidden from screen readers)
  const meetN = h("span", {class: "term-mrun", hidden: true});
  const track = h("div", {class: "term-marq-in"});
  const marq = h("div", {class: "term-marq", role: "marquee", "aria-label": "최근 AI 회의 결론"}, track);
  const line = h("div", {class: "term-mline"}, h("a", {class: "term-mlab", href: ctx.href("digest", "day"), title: "회의 요약 열기"}, "AI 회의 결론"), meetN, marq);
  const rowEl = h("div", {class: "term-row"},
      h("div", {class: "term-id"}, symEl, perp),
      h("div", {class: "term-pxbox"}, px, chg),
      h("div", {class: "term-stats"}, vol.el, fund.el, extra.el),
      h("i", {class: "term-vsep", "aria-hidden": "true"}),
      movers,
      h("span", {class: "grow"}), sndHint, sess, clockBox);
  const el = h("header", {class: "term-top", "aria-label": "시세 요약"}, rowEl, line);
  // the new market cells give way before anything is clipped (terminal-stats.js fit: the row or the movers box would cut)
  if (typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(() => extra.fit(rowEl, movers));
    ro.observe(rowEl); ro.observe(movers);
    ctx.track(() => ro.disconnect());
  }

  let fundT = null, sig = "";
  function paint(tk) {
    const t = tk && tk[st.sym];
    symEl.textContent = `${fmt.coin(st.sym)}USDT`;
    extra.onTicker(tk);                                      // (the 24시간 범위 cell reads the same ticker)
    if (!t) { px.textContent = "—"; return; }
    const p = Number(t.c ?? t.mark);
    if (Date.now() - relayAt > RELAY_FRESH_MS || px.dataset.pk !== st.sym) motion.tickPrice(px, p, fmt.price(p), st.sym);   // glows only on a real move
    px.classList.toggle("up", Number(t.p) > 0); px.classList.toggle("down", Number(t.p) < 0);
    chg.textContent = t.p == null ? "" : fmt.pct(Number(t.p) / 100, 2);
    chg.className = "term-chg num " + fmt.tone(t.p);
    // the same amount reads the same on every screen (차트 · 시장 print it with usdKo too): 12.0억 USDT, not 1.2B
    vol.v.textContent = t.q != null ? `${usdKo(t.q)} USDT` : "—";
    vol.el.title = `24시간 거래대금 ${t.q != null ? `${usdKo(t.q)} USDT` : "— (불러오지 못함)"} · 고가 ${fmt.price(t.h)} · 저가 ${fmt.price(t.l)} · 마크 ${fmt.price(t.mark)}`;
    fundT = t.T || null;
    // funding is not a gain or a loss: a plus rate is not pink (review 10/06). Neutral ink with WHO pays in words; the
    // caution colour only when it is 5 times the usual 0.01 % or more
    const r = Number(t.r), hot = Number.isFinite(r) && Math.abs(r) >= FUND_HOT;
    fundK.textContent = !Number.isFinite(r) || r === 0 ? "펀딩 / 다음까지" : r > 0 ? "펀딩 (롱이 냄) / 다음까지" : "펀딩 (숏이 냄) / 다음까지";
    fund.el.title = Number.isFinite(r) ? `펀딩 ${fundPct(r)}: ${r > 0 ? "롱이 숏에게" : r < 0 ? "숏이 롱에게" : "아무도 안"} 냅니다 (8시간마다) · 보통은 +0.0100% · ${fmt.num(FUND_HOT * 100, 2)}% 이상 쏠리면 주의 색`
      : "펀딩: 이 코인의 펀딩을 받지 못했습니다 (불러오지 못함)";
    put(fund.v, h("span", {class: hot ? "warn-t" : ""}, fundPct(t.r)), " ", h("span", {class: "term-fcd"}, fundT ? countdown(fundT) : ""));
  }

  // ---- movers: /api/v4/movers every minute (the server's own 60 s cache: one Binance fetch a minute for everybody)
  function paintMovers(d, failed) {
    const ok = d && d.ready;
    movers.classList.toggle("none", !ok);
    movers.classList.toggle("stale", !!(ok && d.stale));
    const one = (m, row, val, list, what) => {
      m.s.textContent = row ? fmt.coin(row.s) : ok ? "없음" : failed ? "—" : "수집 전";
      m.v.textContent = row ? val(row) : "";
      m.el.title = ok && list && list.length
        ? `${what} (${MARKET_LABEL}, 바이낸스 USD-M 무기한 ${fmt.int(d.n)}개 중)\n${list.map((r, i) => `${i + 1}. ${fmt.coin(r.s)} ${val(r)}`).join("\n")}`
        : `${what}: ${failed ? "불러오지 못함 (잠시 뒤 다시 받습니다)" : "아직 받은 값이 없습니다"}`;
    };
    one(mUp, ok && d.up[0], (r) => pct2(r.pct), ok && d.up, "24시간 가장 많이 오른 코인");
    one(mDn, ok && d.down[0], (r) => pct2(r.pct), ok && d.down, "24시간 가장 많이 내린 코인");
    one(mNeg, ok && d.neg[0], (r) => fmt.num(r.rate * 100, 4, true) + "%", ok && d.neg, "펀딩비가 가장 낮은 코인 (숏이 롱에게 냄)");
    mWhen.textContent = ok && d.stale ? `${fmt.hm(d.ts)} 값` : "";
  }
  paintMovers(null);
  let moversGot = false;
  const loadMovers = async () => {
    try { const d = await ctx.api("/api/v4/movers"); if (ctx.alive()) { paintMovers(d); moversGot = true; } }
    catch (e) { if (!moversGot && !(e && e.name === "AbortError") && ctx.alive()) paintMovers(null, true); /* the last answer stays */ }
  };
  ctx.every(60000, loadMovers, {now: true});

  function meetings(o) {
    if (!o || o.ready === false) { put(track, h("span", {class: "term-mi muted"}, "회의 기록이 아직 없습니다")); return; }
    const run = (o.running || []).length;
    meetN.hidden = !run;
    meetN.textContent = run ? `회의 중 ${fmt.int(run)}` : "";
    const done = (o.recent || []).filter((m) => clean(m.decision)).slice(0, 6);
    const key = done.map((m) => `${m.room_id}:${m.round_id}:${m.ended_ts}`).join("|");
    if (key === sig) return;
    sig = key;
    if (!done.length) { put(track, h("span", {class: "term-mi muted"}, "오늘 끝난 회의가 아직 없습니다")); track.classList.remove("run"); return; }
    const item = (m) => h("a", {class: "term-mi", href: ctx.href("rooms", m.room_id)}, h("span", {class: "num"}, fmt.hm(m.ended_ts || m.started_ts)),
      h("b", null, m.title || m.room_id), h("span", null, clean(m.decision)));
    const one = h("span", {class: "term-mset"}, done.map(item));
    const copy = h("span", {class: "term-mset", "aria-hidden": "true"}, done.map(item));
    copy.querySelectorAll("a").forEach((a) => { a.tabIndex = -1; });
    put(track, one, copy);
    // about 40 px a second whatever the length (the line is read, not chased)
    requestAnimationFrame(() => { track.style.setProperty("--dur", Math.max(30, Math.round(one.scrollWidth / 40)) + "s"); track.classList.add("run"); });
  }
  const office = async (age) => {
    try { const o = await store.need("office", age); if (ctx.alive()) meetings(o); }
    catch (e) { if (!sig && ctx.alive()) put(track, h("span", {class: "term-mi muted"}, "회의 기록을 불러오지 못함 · 30초마다 다시 시도 중")); }
  };
  office(25000);
  ctx.every(30000, () => office(25000), {now: false});
  let roomT = null;
  ctx.on("rooms", () => { clearTimeout(roomT); roomT = setTimeout(() => ctx.alive() && office(0), 900); });
  ctx.track(() => clearTimeout(roomT));

  return {
    el,
    setSym() { relayAt = 0; paint(store.get("ticker")); extra.setSym(st.sym); },
    onTicker: paint,
    /** Every relay message: the dot says the relay's real state and pulses once per message that carried trades. */
    onRelay(m) {
      liveDot.dataset.s = m.state;
      liveDot.title = m.state === "live" ? "바이낸스 실시간 체결 연결됨" : "실시간 체결 연결 안 됨 (가격은 5초마다)";
      if (m.state === "live" && Array.isArray(m.ev) && m.ev.length) motion.pulseLive(liveDot);
    },
    /** A real relay event of the selected coin {s, side, p}: the big price shows that trade's price and lights once
     *  (the direction of the move, or the side that led when the price did not move). */
    onTick(ev) {
      const p = Number(ev.p);
      if (ev.s !== st.sym || !Number.isFinite(p) || p <= 0) return;
      relayAt = Date.now();
      const tone = motion.tickPrice(px, p, fmt.price(p), st.sym) || (ev.side === "buy" ? "up" : "down");
      hit(px, tone);
    },
    tick() {
      const now = serverNow();
      clock.textContent = clockKst(now);
      const ss = bars.session(now);
      sess.textContent = `${ss.weekend ? "주말 · " : ""}${ss.ko}`;
      sess.title = `미국 증시 ${bars.usMarket(now).text}`;
      clockBox.title = `한국 시각 (서버 시계 기준) · ${sess.textContent}`;
      if (fundT) { const c = fund.v.lastChild; if (c) c.textContent = countdown(fundT); }
    },
  };
}
