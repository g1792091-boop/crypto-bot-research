// #/replay/<trades.id> — 거래 다시보기 (v4 additions). One closed trade, bar by bar: the bars around it (5m for the reel
// and the 5m coin flips, the account's own timeframe otherwise), the entry, the first stop, the lock steps (house
// exits) or the moving upper-band target with the Bollinger band and the 200 line (the reel), the exit; ▶ 재생 / ❚❚ /
// one bar ◀ ▶ / 1x 2x 4x, and a caption that says what each moment means in plain Korean.
// Data: GET /api/v4/replay/<id> (dash/more/replay.py, cached per trade). Without an id: the latest closed trades.
// HONESTY: one trade's story, never a verdict (the page says so); money carries ui.assume(); what the server rebuilt
// from bars (lock times, the reel's breach bar) is labelled; bars that do not match the trade's prices are flagged.
// Motion: on a trade's own page the player is started by the viewer only; the landing (#/replay, fill-strat) plays the
// most recently closed trade (the 36 or the 5분봉 group) once on its own, above the list (a replay of a real stored trade,
// labelled 다시보기; not with reduced motion). It pauses when the page is hidden or left; no other animation runs.
import {h, ui, fmt, motion, local, makeChart, candleOptions, tok, priceDec, fullChart} from "../core/pb.js";
import {exitKo, entryWho, stopPath, eventLines, caption, startBar, notes, summary} from "./replay-story.js";
import {tradeRow} from "./positions-kit.js";
import {tradeMeetSlot} from "./meet-links.js";

const BASE_MS = 650;          // one bar at 1x
const DWELL_MS = 1500;        // a moment with an event stays this much longer (time to read its caption)
const SPEEDS = [{id: "1", label: "1x"}, {id: "2", label: "2x"}, {id: "4", label: "4x"}];

let current = null;

export async function mount(el, ctx) {
  ctx.setTitle("거래 다시보기");
  const head = ui.screenHead("거래 다시보기", "닫힌 거래 하나를 봉 하나씩 다시 봅니다");
  const body = h("div", {class: "rp-body"});
  el.append(head, body);
  const view = {gen: 0, dispose: []};
  const cleanup = () => { for (const fn of view.dispose.splice(0)) { try { fn(); } catch (e) { /* gone */ } } };
  ctx.track(cleanup);

  async function show(arg) {
    cleanup();
    const gen = ++view.gen;
    const id = /^\d+$/.test(String(arg || "")) ? String(arg) : null;
    if (!id) { await picker(gen); return; }
    body.replaceChildren(motion.shimmer(4, true));
    let d;
    try { d = await ctx.api(`/api/v4/replay/${id}`); }
    catch (e) {
      if (e && e.name === "AbortError") return;
      if (gen !== view.gen) return;
      if (e && e.status === 404) {          // not in the record: say so, and offer the latest trades right here
        await picker(gen, h("div", {class: "rp-missing", role: "status"}, h("b", null, `거래 #${id}는 기록에 없습니다`),
          h("span", {class: "muted"}, "아래 최근 거래에서 고르거나, 포지션 › 체결 기록에서 '다시보기'를 누르세요.")));
        return;
      }
      body.replaceChildren(ui.card({plate: "다시보기"}, ui.errorBox(e, () => show(id))));
      return;
    }
    if (gen !== view.gen || !ctx.alive()) return;
    ctx.setTitle(`다시보기 · ${fmt.coin(d.trade.symbol)} ${fmt.sideKo(d.trade.side)}`);
    render(d, gen);
  }

  // ---------------------------------------------------------------- no id: the latest closed trades to pick from
  async function picker(gen, lead) {
    body.replaceChildren(motion.shimmer(4, true));
    let reelRows, coreRows;
    try {
      [reelRows, coreRows] = await Promise.all([ctx.api("/api/trades?limit=5&group=reel"), ctx.api("/api/trades?limit=10&group=core")]);
    } catch (e) {
      if (e && e.name === "AbortError") return;
      if (gen === view.gen) body.replaceChildren(ui.errorBox(e, () => show(null)));
      return;
    }
    if (gen !== view.gen) return;
    const board = ctx.store.get("board");
    const byId = new Map(((board && board.accounts) || []).map((a) => [a.account_id, a]));
    const pick = (t) => ctx.go("replay", String(t.id));
    const reel = (reelRows || []).slice(0, 5);
    const core = (coreRows || []).slice(0, 10);
    const list = (xs, empty) => (xs.length ? h("div", {role: "list"}, xs.map((t) => tradeRow(t, byId.get(t.account_id), {onClick: pick}))) : ui.empty(empty));
    // the most recently closed trade of the two lists plays on its own above them
    const newest = latestOf([...reel, ...core]);
    const auto = h("div", {class: "stack rp-auto"});
    body.replaceChildren(lead || "", auto,
      ui.card({plate: "최근 닫힌 거래", sub: "한 줄을 누르면 다시보기"},
        h("h3", {class: "rp-pick-h"}, "5분봉 (매매법과 5분봉 동전 봇)"), list(reel, "아직 닫힌 5분봉 거래가 없습니다"),
        h("h3", {class: "rp-pick-h"}, "기존 36"), list(core, "아직 닫힌 기존 36 거래가 없습니다"),
        h("p", {class: "note"}, "다른 거래는 포지션 › 체결 기록이나 계좌 화면의 거래 줄에서 '다시보기'를 누르세요."),
        ui.assume()));
    if (!newest) { auto.replaceChildren(ui.card({plate: "방금 닫힌 거래"}, ui.empty("아직 닫힌 거래가 없습니다 · 첫 거래가 닫히면 여기서 저절로 다시 봅니다"))); return; }
    auto.replaceChildren(ui.card({plate: "방금 닫힌 거래", sub: "불러오는 중"}, motion.shimmer(3, true)));
    let d;
    try { d = await ctx.api(`/api/v4/replay/${newest.id}`); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (gen === view.gen) auto.replaceChildren(ui.card({plate: "방금 닫힌 거래"}, h("p", {class: "muted"}, "이 거래의 다시보기를 불러오지 못했습니다. 아래 목록에서 골라 보세요.")));
      return;
    }
    if (gen !== view.gen || !ctx.alive()) return;
    auto.replaceChildren(h("div", {class: "row wrap rp-autohead"}, ui.plate("방금 닫힌 거래 · 저절로 다시보기"),
      h("span", {class: "muted small"}, `${fmt.kst(newest.exit_time)}에 닫힘 · 가장 최근 거래`),
      h("a", {class: "btn-line", href: ctx.href("replay", String(newest.id))}, "이 거래만 크게 보기")));
    const slot = h("div");
    auto.append(slot);
    render(d, gen, {into: slot, autoplay: !motion.reduced()});
  }

  // ---------------------------------------------------------------- one trade
  function render(d, gen, opts = {}) {
    const t = d.trade, a = d.account || {};
    const n = d.bars.length;
    const evs = eventLines(d);
    const stops = stopPath(d);
    const byBar = new Map();
    for (const e of evs) byBar.set(e.bar, (byBar.get(e.bar) || []).concat(e));

    // ---- header: who, what, how it ended
    const tone = fmt.tone(t.pnl);
    const holdBars = d.idx.entry != null && d.idx.exit != null ? d.idx.exit - d.idx.entry + 1 : null;
    const hero = ui.card({hero: true, cls: "rp-hero", label: "거래 요약"},
      h("div", {class: "rp-who"}, ui.plate("다시보기"),
        h("a", {class: "rp-acct", href: ctx.href("account", t.account_id), title: t.account_id}, ui.acctLabel(a)),
        a.kind === "ds200" ? ui.pill("참고", "ref") : null, tradeMeetSlot(ctx, t)),
      h("div", {class: "rp-line"}, h("b", {class: "rp-sym"}, `${fmt.coin(t.symbol)}USDT`), ui.sideTag(t.side),
        h("span", {class: "muted"}, `격리 ${fmt.lev(t.leverage)} · ${fmt.dur(t.hold_s)} 보유`),
        h("span", {class: "rp-reason " + (t.exit_reason === "LIQ" ? "down" : t.pnl > 0 ? "up" : "")}, exitKo(d))),
      h("div", {class: "rp-pnl"},
        h("div", null, h("span", {class: "k"}, "손익 (USDT)"), h("b", {class: ["rp-led", "num", tone]}, fmt.money(t.pnl, true))),
        h("div", {class: "r"}, h("span", {class: "k"}, "ROE (증거금 대비)"), h("b", {class: ["rp-led-sm", "num", fmt.tone(t.roe)]}, fmt.pct(t.roe, 1)))),
      ui.assume(null, "손익은 나갈 때 수수료·펀딩 뒤"));
    const facts = ui.card({plate: "거래 기록", sub: "가격 · 금액은 USDT", cls: "rp-facts"},
      ui.kv([["진입", fmt.kst(t.entry_time)], ["청산", fmt.kst(t.exit_time)],
        ["보유", `${fmt.dur(t.hold_s)}${holdBars ? ` · ${fmt.tfKo(d.tf)}봉 ${fmt.int(holdBars)}개` : ""}`],
        ["진입가 → 청산가", `${fmt.price(t.entry_price)} → ${fmt.price(t.exit_price)}`],
        ["첫 손절", fmt.price(d.levels.stop_initial)],
        d.exits === "reel" ? ["마지막 목표 (윗밴드)", fmt.price(d.levels.target_final)] : ["마지막 손절·잠금", fmt.price(d.levels.stop_final)],
        ["강제청산가", h("span", {class: "down"}, fmt.price(d.levels.liq))], ["증거금", fmt.money(t.margin)],
        ["수수료", fmt.money(t.fees)], ["펀딩", fmt.money(t.funding)]]),
      h("ul", {class: "rp-notes"}, notes(d).map((x) => h("li", null, x))));

    // ---- the caption (the moment) and the chart
    const capStep = h("span", {class: "rp-cap-step"});
    const capText = h("p", {class: "rp-cap-text", "aria-live": "polite"});
    const cap = h("div", {class: "rp-cap"}, h("div", {class: "rp-cap-top"}, h("span", {class: "rp-cap-plate"}, "◆ 지금 이 순간"), capStep), capText);
    const box = h("div", {class: "rp-chart", role: "img", "aria-label": `${fmt.coin(t.symbol)} ${fmt.tfKo(d.tf)}봉 차트, 이 거래의 진입과 청산`, "data-fc-grow": ""});
    const legend = h("div", {class: "rp-legend"}, legendItems(d).map(([cls, txt]) => h("span", null, h("i", {class: cls, "aria-hidden": "true"}), txt)));

    // ---- controls
    const bPlay = h("button", {type: "button", class: "rp-btn rp-play", "aria-label": "재생"}, "▶ 재생");
    const bPrev = h("button", {type: "button", class: "rp-btn", "aria-label": "한 봉 뒤로"}, "◀");
    const bNext = h("button", {type: "button", class: "rp-btn", "aria-label": "한 봉 앞으로"}, "▶");
    const bFirst = h("button", {type: "button", class: "rp-btn", "aria-label": "처음으로"}, "⏮");
    const bLast = h("button", {type: "button", class: "rp-btn", "aria-label": "끝으로"}, "⏭");
    const P = {k: n - 1, playing: false, speed: Number(local.get("replay-speed", "1")) || 1, t: null};
    const speed = ui.seg(SPEEDS, String(P.speed), (v) => { P.speed = Number(v) || 1; local.set("replay-speed", v); if (P.playing) schedule(); }, {label: "속도"});
    const range = h("input", {type: "range", class: "rp-range", min: "0", max: String(Math.max(0, n - 1)), value: String(n - 1), step: "1",
      "aria-label": "봉 고르기"});
    const ctl = h("div", {class: "rp-ctl", role: "group", "aria-label": "다시보기 조작"},
      h("div", {class: "rp-ctl-row"}, bFirst, bPrev, bPlay, bNext, bLast), h("div", {class: "rp-ctl-row"}, range, speed));

    // ---- the story list (tap a line: go to that moment)
    const story = h("ol", {class: "rp-story"}, evs.map((e) => h("li", {class: ["rp-ev", e.kind, e.tone], dataset: {bar: e.bar}},
      h("button", {type: "button", class: "rp-ev-b", onclick: () => { pause(); goTo(e.bar, false); }},
        h("span", {class: "rp-ev-t"}, e.t ? fmt.hm(e.t) : "—"), h("span", {class: "rp-ev-dot", "aria-hidden": "true"}),
        h("span", {class: "rp-ev-x"}, e.text, e.rebuilt ? h("small", null, " · 봉으로 다시 찾음") : null)))));

    const warn = [];
    if (d.fit === false) warn.push(h("p", {class: "rp-warn", role: "note"}, "이 봉 자료는 거래 가격과 맞지 않습니다 (진입·청산 가격이 그 봉 밖). 이야기의 숫자는 거래 기록만 믿으세요."));
    // 차트 크게 보기 (core/fullchart.js, key "f"): the card fills the window with its caption and play buttons
    const fs = n ? fullChart({ctx, label: "다시보기 차트"}) : null;
    const chartCard = ui.card({plate: `${fmt.coin(t.symbol)} · ${fmt.tfKo(d.tf)}봉`, sub: entryWho(d), cls: "rp-chartcard", acts: fs ? [fs] : null},
      ...warn, n ? box : emptyBars(d), cap, n ? ctl : null, n ? legend : null);
    if (fs) fs.bind(chartCard);
    const storyCard = ui.card({plate: "이 거래의 순간들", sub: "누르면 그 봉으로", cls: "rp-storycard"}, evs.length ? story : ui.empty("표시할 순간이 없습니다 (봉 자료 없음)"),
      h("p", {class: "refnote"}, h("b", null, "참고"), " · 거래 한 건의 이야기입니다. 한 건으로 매매법이 좋다·나쁘다를 말할 수 없습니다 (판정은 30일째, 동전 봇과 비교)."));
    const links = h("div", {class: "row wrap rp-links"},
      h("a", {class: "btn-line", href: ctx.href("account", t.account_id)}, "← 계좌로"),
      h("a", {class: "btn-line", href: ctx.href("chart", t.symbol, {tf: d.tf_own})}, "차트에서 보기"),
      h("a", {class: "btn-line", href: ctx.href("replay")}, "다른 거래"));
    const target = opts.into || body;
    target.replaceChildren(h("div", {class: "rp-grid"}, h("div", {class: "rp-main"}, chartCard, opts.into ? null : facts, opts.into ? null : links), h("div", {class: "rp-side"}, hero, storyCard)));
    motion.swap(target);

    // ---- player
    let chartApi = null;
    function paintCaption(k, animate) {
      const c = n ? caption(d, k, evs, stops) : {text: "봉 자료가 없어 거래 기록의 숫자만 보여 드립니다.", tone: ""};
      capText.textContent = c.text;
      cap.className = `rp-cap ${c.tone || ""}`;
      const b = d.bars[k];
      capStep.textContent = n ? `봉 ${fmt.int(k + 1)} / ${fmt.int(n)} · ${b ? fmt.kst(b[0] * 1000) : ""}` : "";
      if (animate && byBar.has(k)) motion.fadeIn(capText);
      for (const li of story.children) {
        const bar = Number(li.dataset.bar);
        li.classList.toggle("past", bar <= k);
        li.classList.toggle("now", bar === k);
      }
    }
    function goTo(k, animate) {
      P.k = Math.max(0, Math.min(n - 1, k));
      range.value = String(P.k);
      paintCaption(P.k, animate);
      if (chartApi) chartApi.reveal(P.k);
      bPrev.disabled = P.k <= 0; bFirst.disabled = P.k <= 0;
      bNext.disabled = P.k >= n - 1; bLast.disabled = P.k >= n - 1;
    }
    function schedule() {
      clearTimeout(P.t);
      const dwell = byBar.has(P.k) ? DWELL_MS : 0;
      P.t = setTimeout(tick, (BASE_MS + dwell) / P.speed);
    }
    function tick() {
      if (!P.playing || gen !== view.gen) return;
      if (P.k >= n - 1) { pause(); return; }
      goTo(P.k + 1, true);
      if (P.k >= n - 1) { pause(); capText.textContent = summary(d, evs).replace(/ ▶ 재생을.*$/, " 끝까지 봤습니다."); cap.className = "rp-cap accent"; }
      else schedule();
    }
    function play() {
      if (!n) return;
      if (P.k >= n - 1) goTo(startBar(d, evs), false);
      P.playing = true;
      bPlay.textContent = "❚❚ 멈춤"; bPlay.setAttribute("aria-label", "멈춤"); bPlay.classList.add("on");
      schedule();
    }
    function pause() {
      P.playing = false;
      clearTimeout(P.t);
      bPlay.textContent = P.k >= n - 1 ? "▶ 처음부터" : "▶ 재생"; bPlay.setAttribute("aria-label", "재생"); bPlay.classList.remove("on");
    }
    bPlay.addEventListener("click", () => (P.playing ? pause() : play()));
    bPrev.addEventListener("click", () => { pause(); goTo(P.k - 1, true); });
    bNext.addEventListener("click", () => { pause(); goTo(P.k + 1, true); });
    bFirst.addEventListener("click", () => { pause(); goTo(startBar(d, evs), false); });
    bLast.addEventListener("click", () => { pause(); goTo(n - 1, false); });
    range.addEventListener("input", () => { pause(); goTo(Number(range.value), false); });
    ctl.addEventListener("keydown", (e) => {
      if (e.target === range) return;
      if (e.key === " " || e.key === "k") { e.preventDefault(); if (P.playing) pause(); else play(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); pause(); goTo(P.k - 1, true); }
      else if (e.key === "ArrowRight") { e.preventDefault(); pause(); goTo(P.k + 1, true); }
    });
    const onVis = () => { if (document.hidden && P.playing) pause(); };
    document.addEventListener("visibilitychange", onVis);
    view.dispose.push(() => { clearTimeout(P.t); P.playing = false; document.removeEventListener("visibilitychange", onVis); });
    goTo(n - 1, false);
    pause();
    if (n) { capText.textContent = summary(d, evs); cap.className = "rp-cap accent"; }
    // the landing's newest trade starts by itself once the chart is up (the viewer can stop it any time)
    if (n && opts.autoplay) setTimeout(() => { if (gen === view.gen && !document.hidden && !P.playing) { goTo(startBar(d, evs), false); play(); } }, 900);

    if (n) {
      drawChart(box, d, stops, gen).then((api) => {
        if (!api) return;
        if (gen !== view.gen) { api.dispose(); return; }
        chartApi = api;
        view.dispose.push(api.dispose);
        api.reveal(P.k);
      });
    }
  }

  // ---------------------------------------------------------------- the chart (vendored lightweight-charts)
  async function drawChart(box, d, stops, gen) {
    let c;
    try { c = await makeChart(box, {handleScroll: false, handleScale: false}); }
    catch (e) { if (gen === view.gen) box.replaceChildren(ui.errorBox(e)); return null; }
    const {chart} = c;
    const t = d.trade, n = d.bars.length, side = t.side;
    const dec = priceDec(t.entry_price || d.bars[n - 1][4]);
    const pf = {type: "price", precision: dec, minMove: Math.pow(10, -dec)};
    chart.applyOptions({timeScale: {shiftVisibleRangeOnNewBar: false, rightOffset: 1, lockVisibleTimeRangeOnResize: true},
      rightPriceScale: {scaleMargins: {top: 0.12, bottom: 0.1}}});
    const T = (i) => d.bars[i][0];
    const C = {up: tok("--up"), down: tok("--down"), accent: tok("--accent"), accentLine: tok("--accent-line"), ink: tok("--ink"),
      ink2: tok("--ink-2"), line2: tok("--line-2"), warn: tok("--warn"), upLine: tok("--up-line"), soft: tok("--accent-soft")};
    const quiet = {lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false, priceFormat: pf};
    // the playhead: a soft full-height band behind the bar being shown (its own hidden scale)
    const head = chart.addHistogramSeries({priceScaleId: "head", color: C.soft, base: 0, lastValueVisible: false, priceLineVisible: false});
    chart.priceScale("head").applyOptions({scaleMargins: {top: 0, bottom: 0}, visible: false});
    const lines = [];
    const addLine = (vals, o) => { lines.push({s: chart.addLineSeries({...quiet, lineWidth: 1, ...o}), vals}); };
    if (d.exits === "reel" && d.lines.bb_up) {
      addLine(d.lines.bb_up, {color: C.accentLine});
      addLine(d.lines.bb_dn, {color: C.line2});
      addLine(d.lines.ma200, {color: C.ink2, lineStyle: 2});
    }
    const candles = chart.addCandlestickSeries({...candleOptions(), priceFormat: pf, lastValueVisible: false, priceLineVisible: false});
    const ie = d.idx.entry, ix = d.idx.exit == null ? n - 1 : d.idx.exit;
    if (ie != null) {
      addLine(d.bars.map((_, i) => (i >= ie && i <= ix ? t.entry_price : null)), {color: C.ink, lineStyle: 2});
      if (d.exits !== "reel" && d.levels.lock_start) {
        const firstLock = (d.steps || []).length ? d.steps[0].bar : ix;
        addLine(d.bars.map((_, i) => (i >= ie && i <= firstLock ? d.levels.lock_start : null)), {color: C.upLine, lineStyle: 1});
      }
      if (d.exits === "reel" && d.lines.target) addLine(d.lines.target, {color: C.accent, lineWidth: 2, lineType: 1});
      lines.push({s: chart.addLineSeries({...quiet, lineWidth: 2, lineType: 1, color: C.down}),
        vals: stops.map((x) => (x ? x.v : null)), cols: stops.map((x) => (x && x.lock != null ? C.up : C.down))});
    }
    const hide = "transparent";
    const full = d.bars.map((b) => ({time: b[0], open: b[1], high: b[2], low: b[3], close: b[4]}));
    // every bar is always in the data (the price scale and the time axis never jump): bars not reached yet are drawn
    // transparent and the overlays stop at the bar being shown
    const marks = [];
    const mk = (i, o) => { if (i != null && d.bars[i]) marks.push({bar: i, time: T(i), ...o}); };
    for (const e of d.events) {
      if (e.kind === "breach" || e.kind === "breach_again") mk(e.bar, {position: "belowBar", shape: "circle", color: C.warn, text: ""});
      else if (e.kind === "signal") mk(e.bar, {position: side > 0 ? "aboveBar" : "belowBar", shape: "circle", color: C.accent, text: "신호"});
      else if (e.kind === "entry") mk(e.bar, {position: side > 0 ? "belowBar" : "aboveBar", shape: side > 0 ? "arrowUp" : "arrowDown", color: C.ink, text: "진입"});
      else if (e.kind === "lock") {
        const first = !marks.some((m) => m.lock);
        mk(e.bar, {position: side > 0 ? "aboveBar" : "belowBar", shape: "square", color: C.up, lock: true,
          text: first && e.bar !== d.idx.exit ? `잠금 +${fmt.num(e.level * 100, 0)}%` : ""});
      }
      else if (e.kind === "exit") mk(e.bar, {position: side > 0 ? "aboveBar" : "belowBar", shape: "circle", color: t.pnl > 0 ? C.up : C.down, text: "청산"});
    }
    let shown = -1;
    const reveal = (k) => {
      if (k === shown) return;
      shown = k;
      candles.setData(full.map((b, i) => (i <= k ? b : {...b, color: hide, wickColor: hide, borderColor: hide})));
      for (const ln of lines) {
        ln.s.setData(d.bars.map((b, i) => {
          const v = ln.vals[i];
          if (i > k || v == null) return {time: b[0]};
          return ln.cols ? {time: b[0], value: v, color: ln.cols[i]} : {time: b[0], value: v};
        }));
      }
      head.setData(d.bars.map((b, i) => (i === k && k < n - 1 ? {time: b[0], value: 1} : {time: b[0]})));
      candles.setMarkers(marks.filter((m) => m.bar <= k).map(({bar, lock, ...m}) => m));
    };
    reveal(n - 1);
    chart.timeScale().fitContent();
    return {reveal, dispose: c.dispose};
  }

  current = (params) => show(params.arg);
  ctx.track(() => { current = null; });
  await show(ctx.params.arg);
}

/** Legend keys under the chart: what each line is (only the lines this trade has). */
/** The most recently closed of some /api/trades rows (by exit time, then id), or null. */
export function latestOf(rows) {
  let best = null;
  for (const t of rows || []) {
    if (!t || t.id == null) continue;
    if (!best || (Number(t.exit_time) || 0) > (Number(best.exit_time) || 0) || ((Number(t.exit_time) || 0) === (Number(best.exit_time) || 0) && t.id > best.id)) best = t;
  }
  return best;
}

function legendItems(d) {
  const out = [["k-entry", "진입가"], ["k-stop", "손절선"]];
  if (d.exits === "reel") out.push(["k-target", "목표 (직전 봉 윗밴드)"], ["k-band", "볼린저 띠"], ["k-ma", "200선"]);
  else {
    if ((d.steps || []).length) out.push(["k-lock", "잠금선 (손절선이 수익 쪽으로)"]);
    if (d.levels.lock_start) out.push(["k-lstart", "잠금 시작선"]);
  }
  if (d.events.some((e) => e.kind === "breach")) out.push(["k-breach", "아래 띠 밖 마감 (준비)"]);
  if (d.events.some((e) => e.kind === "signal")) out.push(["k-signal", "신호"]);
  return out;
}

/** No bars for this trade: the levels as a small price ladder, so the story still reads. */
function emptyBars(d) {
  const t = d.trade, lv = d.levels;
  const rows = [["청산가", t.exit_price, t.pnl > 0 ? "up" : "down"], ["진입가", t.entry_price, ""], ["첫 손절", lv.stop_initial, "down"]];
  if (lv.stop_final != null && lv.stop_final !== lv.stop_initial) rows.push(["마지막 손절·잠금", lv.stop_final, t.lock_roe != null ? "up" : "down"]);
  if (lv.target_final != null) rows.push(["마지막 목표", lv.target_final, "up"]);
  rows.sort((x, y) => (y[1] ?? 0) - (x[1] ?? 0));
  return h("div", {class: "rp-empty"},
    h("p", {class: "rp-empty-h"}, "봉 자료를 받지 못했습니다"),
    h("p", {class: "note"}, "이 거래 시간의 봉이 서버에 없습니다 (기록 전이거나 너무 오래된 거래). 거래 기록의 가격만 순서대로 보여 드립니다."),
    h("ol", {class: "rp-ladder"}, rows.map(([k, v, cls]) => h("li", {class: cls}, h("span", null, k), h("b", {class: "num"}, fmt.price(v))))));
}

export function update(params) { if (current) current(params); }
export function unmount() { current = null; }
