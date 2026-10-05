// 터미널 top bar: the coin and its price (a teal / pink glow only when the server's price really moved), the 24 h
// numbers, mark, funding and the time to the next funding, the trading session, the KST clock, and one slow line of
// the latest real AI meeting conclusions (/api/office: finished meetings' decision lines; '회의 중' only from
// office.running). The office is read through the shared store like 홈 (every 30 s and when a room changes).
import {h, put, fmt, store, motion, bars, serverNow, sound} from "../core/pb.js";
import {countdown, fundPct} from "./positions-book.js";
import {hit} from "./terminal-live.js";

const RELAY_FRESH_MS = 6000;      // the selected coin's relay price this fresh keeps the big price (the ticker is older)

const two = (x) => String(x).padStart(2, "0");
const clockKst = (ms) => { const d = new Date(ms + 9 * 3.6e6); return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}:${two(d.getUTCSeconds())}`; };
const clean = (t) => String(t || "").replace(/^\s*🧾\s*/u, "").trim();

/** topBar(ctx, st) -> {el, setSym, onTicker(map), tick()} */
export function topBar(ctx, st) {
  const symEl = h("b", {class: "term-sym"}), perp = h("span", {class: "term-perp"}, "무기한 · 모의");
  const px = h("b", {class: "term-px num"}, "—"), chg = h("span", {class: "term-chg num"}, "");
  const stat = (k) => { const v = h("b", {class: "num"}, "—"); return {v, el: h("div", {class: "term-st"}, h("span", null, k), v)}; };
  const hi = stat("24시간 고가"), lo = stat("24시간 저가"), vol = stat("24시간 거래대금"), mark = stat("마크 가격"), fund = stat("펀딩비 / 다음까지");
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
  // the meetings line: a label, a running count (real), the conclusions (duplicated once for a seamless loop; the copy is
  // hidden from screen readers)
  const meetN = h("span", {class: "term-mrun", hidden: true});
  const track = h("div", {class: "term-marq-in"});
  const marq = h("div", {class: "term-marq", role: "marquee", "aria-label": "최근 AI 회의 결론"}, track);
  const line = h("div", {class: "term-mline"}, h("a", {class: "term-mlab", href: ctx.href("digest", "day"), title: "회의 요약 열기"}, "AI 회의 결론"), meetN, marq);
  const el = h("header", {class: "term-top", "aria-label": "시세 요약"},
    h("div", {class: "term-row"},
      h("div", {class: "term-id"}, symEl, perp),
      h("div", {class: "term-pxbox"}, px, chg),
      h("div", {class: "term-stats"}, hi.el, lo.el, vol.el, mark.el, fund.el),
      h("span", {class: "grow"}), sndHint, sess, clockBox),
    line);

  let fundT = null, sig = "";
  function paint(tk) {
    const t = tk && tk[st.sym];
    symEl.textContent = `${fmt.coin(st.sym)}USDT`;
    if (!t) { px.textContent = "—"; return; }
    const p = Number(t.c ?? t.mark);
    if (Date.now() - relayAt > RELAY_FRESH_MS || px.dataset.pk !== st.sym) motion.tickPrice(px, p, fmt.price(p), st.sym);   // glows only on a real move
    px.classList.toggle("up", Number(t.p) > 0); px.classList.toggle("down", Number(t.p) < 0);
    chg.textContent = t.p == null ? "" : fmt.pct(Number(t.p) / 100, 2);
    chg.className = "term-chg num " + fmt.tone(t.p);
    hi.v.textContent = fmt.price(t.h); lo.v.textContent = fmt.price(t.l);
    vol.v.textContent = t.q != null ? fmt.compact(t.q) : "—";
    mark.v.textContent = fmt.price(t.mark);
    fundT = t.T || null;
    put(fund.v, h("span", {class: fmt.tone(-Number(t.r || 0))}, fundPct(t.r)), " ", h("span", {class: "muted"}, fundT ? countdown(fundT) : ""));
  }

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
  const office = async (age) => { try { const o = await store.need("office", age); if (ctx.alive()) meetings(o); } catch (e) { if (!sig) meetings(null); } };
  office(25000);
  ctx.every(30000, () => office(25000), {now: false});
  let roomT = null;
  ctx.on("rooms", () => { clearTimeout(roomT); roomT = setTimeout(() => ctx.alive() && office(0), 900); });
  ctx.track(() => clearTimeout(roomT));

  return {
    el,
    setSym() { relayAt = 0; paint(store.get("ticker")); },
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
      if (fundT) { const c = fund.v.lastChild; if (c) c.textContent = countdown(fundT); }
    },
  };
}
