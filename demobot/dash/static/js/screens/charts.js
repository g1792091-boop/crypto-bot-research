// #/charts 여러 차트 (CONTRACT 9.8; round 5: the rule bot's v4 여러 차트 for the demo lab): 2×2 or 3×3 candle charts on
// one screen. Each cell picks its coin (the 7 the demo trades), its timeframe (1분 ~ 일) and which of our open demo
// positions it lays over the candles ("포지션 선 끔 · n개 열림", all of them, or one account's entry); its head shows the
// price now and the 24 h change, and "⛶ 크게" opens the cell over the whole window (Esc closes). Three switches for every
// cell: 포지션 선, 손절·목표, 거래량. The layout, the cells and the switches are remembered on this device.
// Data: /api/klines (300 bars when a cell changes; then every 6 s the newest 2 bars of each distinct coin + timeframe
// that is on screen: the server keeps them 10 s), /api/live every 6 s for the price (the forming bar follows it), and
// positions.json every 30 s. Only while the page is visible (and a cell only while it is in view). We have no market
// trade stream, so the status says "시세 6초마다", never "실시간 체결". No order button anywhere.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {COINS, sideKo} from "../labels.js";
import * as K from "../live-kit.js";

const KEY = "charts-grid";
export const LAYOUTS = {"2x2": 4, "3x3": 9};
const TFS = K.TFS;                                              // 1분 5분 15분 30분 1시간 4시간 일
const DEFAULT_CELLS = [["BTCUSD", "15m"], ["ETHUSD", "15m"], ["SOLUSD", "15m"], ["DOGEUSD", "15m"], ["LTCUSD", "15m"], ["BCHUSD", "15m"],
  ["XRPUSD", "15m"], ["BTCUSD", "1h"], ["ETHUSD", "1h"]].map(([coin, tf]) => ({coin, tf, pos: ""}));
const POLL_MS = 6000;
const BARS = "300";

/** A stored grid -> a clean one (a known layout, nine cells of known coins / timeframes, the three switches). */
export function cleanGrid(v) {
  const x = v && typeof v === "object" ? v : {};
  const cells = DEFAULT_CELLS.map((d, i) => {
    const c = Array.isArray(x.cells) && x.cells[i] && typeof x.cells[i] === "object" ? x.cells[i] : {};
    return {coin: COINS.includes(c.coin) ? c.coin : d.coin, tf: TFS.includes(c.tf) ? c.tf : d.tf,
      pos: typeof c.pos === "string" && c.pos.length < 120 ? c.pos : ""};
  });
  const sw = x.sw && typeof x.sw === "object" ? x.sw : {};
  return {layout: Object.prototype.hasOwnProperty.call(LAYOUTS, x.layout) ? x.layout : "2x2", cells,
    sw: {pos: sw.pos !== false, risk: sw.risk === true, vol: sw.vol !== false}};
}

export async function mount(el, ctx) {
  await K.needCss();
  ctx.setTitle("여러 차트");
  let cfg = cleanGrid(local.get(KEY, null));
  const save = () => local.set(KEY, cfg);
  const D = {pos: null, live: null, cells: [], full: null};
  const groupsOf = (coin) => (D.pos && !isMissing(D.pos) ? K.groupEntries((D.pos.positions || []).filter((p) => p.coin === coin)) : []);
  const gkey = (g) => `${g.id}|${g.entry_ms}|${g.side}`;
  const liveRow = (c) => (D.live && (D.live.coins || []).find((x) => x.coin === c)) || null;

  // ---------------------------------------------------------------- the bar above the grid
  const laySeg = ui.seg([{id: "2x2", label: "2×2"}, {id: "3x3", label: "3×3"}], cfg.layout, (id) => { cfg.layout = id; save(); loadCells(layout()); }, {label: "칸 수"});
  const swPos = K4.chipToggle("포지션 선", cfg.sw.pos, (v) => { cfg.sw.pos = v; save(); D.cells.forEach((c) => c.drawLines()); }, "칸마다 고른 우리 포지션의 진입 선");
  const swRisk = K4.chipToggle("손절·목표", cfg.sw.risk, (v) => { cfg.sw.risk = v; save(); D.cells.forEach((c) => c.drawLines()); }, "그 포지션들의 손절 선(점선)과 고정 익절 목표 선");
  const swVol = K4.chipToggle("거래량", cfg.sw.vol, (v) => { cfg.sw.vol = v; save(); D.cells.forEach((c) => c.chart && c.chart.volume(v)); }, "봉 아래 거래량 막대");
  const status = K4.liveDot("시세 확인 중", "off");
  const grid = h("div", {class: "cg-grid", dataset: {layout: cfg.layout}});
  el.append(ui.screenHead("여러 차트", "코인·봉을 칸마다 골라 한 화면에", [h("a", {class: "btn-line", href: ctx.href("terminal")}, "차트 하나 크게 →")]),
    h("div", {class: "k4-bar cg-bar"},
      h("div", {class: "k4-barg"}, h("span", {class: "k4-k"}, "칸"), laySeg),
      h("div", {class: "k4-barg"}, h("span", {class: "k4-k"}, "선"), swPos, swRisk, swVol),
      h("span", {class: "grow"}), status),
    grid,
    h("div", {class: "cg-foot"},
      ui.note("칸마다 코인 · 봉 · 겹쳐 볼 포지션을 고르면 이 기기에 기억합니다. '⛶ 크게'는 그 칸을 화면 가득 (Esc로 돌아옴). 봉은 바이낸스 공개 시세를 대시보드 서버가 받아 10초 동안 보관한 것이고, "
        + "새 가격은 6초마다 다시 묻습니다 (실시간 체결 흐름은 없음). 선 = 우리 데모 포지션의 진입 가격 (초록 롱 · 빨강 숏), 손절·목표는 점선."),
      h("p", {class: "assume once"}, "모의 · 실제 시세 · 포지션 선은 엔진의 마지막 15분봉 기준 · 주문 버튼 없음")));

  // ---------------------------------------------------------------- one cell
  function cellOf(i) {
    const cfgC = () => cfg.cells[i];
    const coinSel = h("select", {class: "select cg-sel", "aria-label": `칸 ${i + 1} 코인`}, COINS.map((c) => h("option", {value: c}, fmt.coin(c))));
    const tfSel = h("select", {class: "select cg-sel", "aria-label": `칸 ${i + 1} 봉`}, TFS.map((tf) => h("option", {value: tf}, K.TF_SHORT[tf])));
    const posSel = h("select", {class: "select cg-sel cg-ov", "aria-label": `칸 ${i + 1} 겹쳐 볼 포지션`});
    coinSel.value = cfgC().coin; tfSel.value = cfgC().tf;
    const px = h("b", {class: "cg-px num"}, "—"), chg = h("small", {class: "cg-chg num"});
    const bigBtn = h("button", {type: "button", class: "btn-line cg-big", "aria-pressed": "false", title: "이 칸을 화면 가득 (Esc로 돌아옴)"}, "⛶ 크게");
    const box = h("div", {class: "cg-box", role: "img", "aria-label": `칸 ${i + 1} 차트`});
    const msg = h("div", {class: "cg-msg", hidden: true});
    const tag = h("div", {class: "cg-tag num", "aria-hidden": "true"});
    const note = h("p", {class: "cg-note", hidden: true});
    const head = h("div", {class: "cg-h"}, coinSel, tfSel, posSel, h("span", {class: "grow"}), h("span", {class: "cg-pxw"}, px, chg), bigBtn);
    const root = h("section", {class: "cg-cell", "aria-label": `칸 ${i + 1}`, dataset: {i: String(i)}}, head, h("div", {class: "cg-wrap"}, box, tag, msg), note);
    const cell = {i, root, chart: null, key: "", seen: true, dead: false, loading: 0};

    function paintHead() {
      const r = liveRow(cfgC().coin);
      const p = r && r.ok ? Number(r.price) : null;
      K4.tickPrice(px, p, p != null ? K.px(p) : "—", `cg${i}:${cfgC().coin}`);
      const cp = r && r.ok ? Number(r.change_pct) : null;
      chg.textContent = cp == null ? "" : fmt.pct(cp, true, 2);
      chg.className = "cg-chg num " + fmt.tone(cp, chg.textContent);
      tag.textContent = `${fmt.coin(cfgC().coin)} · ${K.TF_SHORT[cfgC().tf]}`;
    }
    function fillPos() {
      const gs = groupsOf(cfgC().coin);
      const want = cfgC().pos;
      const has = want === "all" || gs.some((g) => gkey(g) === want);
      const first = h("option", {value: ""}, !D.pos ? "포지션 불러오는 중" : isMissing(D.pos) ? "포지션 준비 중" : gs.length ? `포지션 선 끔 · ${fmt.int(gs.length)}개 열림` : "열린 데모 포지션 없음");
      const opts = gs.length ? [h("option", {value: "all"}, `우리 포지션 전부 (${fmt.int(gs.length)}개)`),
        h("optgroup", {label: "계좌 하나만"}, gs.map((g) => h("option", {value: gkey(g)}, `${g.name || g.id} · ${sideKo(g.side)} ${K.levText(g.Ls)}`)))] : [];
      // a chosen entry that has closed stays listed (the choice is not lost silently) and says so
      const gone = want && want !== "all" && !has ? [h("option", {value: want}, `${want.split("|")[0]} · 포지션 닫힘`)] : [];
      posSel.replaceChildren(first, ...opts, ...gone);
      posSel.value = want === "all" && !gs.length ? "" : want;
      posSel.disabled = !gs.length && !gone.length;
    }
    function drawLines() {
      if (!cell.chart) return;
      const gs = groupsOf(cfgC().coin), want = cfgC().pos;
      const chosen = !cfg.sw.pos ? [] : want === "all" ? gs : gs.filter((g) => gkey(g) === want);
      const r = liveRow(cfgC().coin);
      cell.chart.lines(chosen, {price: r && r.ok ? r.price : null, stops: cfg.sw.risk, targets: cfg.sw.risk, labels: want === "all" ? 2 : 1});
      const one = want && want !== "all" ? gs.find((g) => gkey(g) === want) : null;
      note.textContent = !want ? "" : want === "all" ? (gs.length ? `우리 포지션 ${fmt.int(gs.length)}개${cfg.sw.pos ? "" : " · '포지션 선'이 꺼져 있음"}` : "이 코인에 열린 데모 포지션이 지금 없습니다")
        : one ? `${one.name || one.id} · ${sideKo(one.side)} ${K.levText(one.Ls)} · 진입 ${K.px(one.entry)} · 손절 ${K.px(one.stop)}${one.target != null ? ` · 목표 ${K.px(one.target)}` : ""}`
          : "고른 포지션이 닫혔습니다";
      note.hidden = !note.textContent;
    }
    async function load() {
      const tk = ++cell.loading, c = cfgC();
      let d;
      try { d = await ctx.api(`/api/klines?${new URLSearchParams({coin: c.coin, tf: c.tf, limit: BARS})}`); } catch (e) {
        if (e && e.name === "AbortError") return;
        msg.hidden = false; put(msg, ui.errorBox(e, load));
        return;
      }
      if (tk !== cell.loading || cell.dead || !ctx.alive()) return;
      if (d.off || d.unavailable || !d.bars || !(d.bars.t || []).length) {
        msg.hidden = false;
        put(msg, h("div", {class: "dl-missing"}, h("b", null, d.off ? "꺼짐" : "준비 중"), h("span", null, d.off ? " · 실시간 시세가 꺼져 있습니다" : " · 봉을 아직 받지 못했습니다")));
        return;
      }
      msg.hidden = true;
      if (!cell.chart) {
        try { cell.chart = await K.liveChart(box, {compact: true, volume: true}); } catch (e) { put(box, ui.empty("차트를 그리지 못했습니다.")); return; }
        if (cell.dead || !ctx.alive()) { cell.chart.dispose(); cell.chart = null; return; }
        cell.chart.volume(cfg.sw.vol);
      }
      const key = `${c.coin}|${c.tf}`;
      cell.chart.set(d.bars, c.tf, cell.key === key);
      cell.key = key;
      drawLines();
    }
    coinSel.addEventListener("change", () => { cfg.cells[i] = {...cfgC(), coin: coinSel.value, pos: ""}; save(); fillPos(); paintHead(); cell.key = ""; load(); });
    tfSel.addEventListener("change", () => { cfg.cells[i] = {...cfgC(), tf: tfSel.value}; save(); paintHead(); cell.key = ""; load(); });
    posSel.addEventListener("change", () => { cfg.cells[i] = {...cfgC(), pos: posSel.value}; save(); drawLines(); });
    bigBtn.addEventListener("click", () => setFull(D.full === cell ? null : cell));
    Object.assign(cell, {paintHead, fillPos, drawLines, load, bigBtn,
      get coin() { return cfgC().coin; }, get tf() { return cfgC().tf; },
      dispose() { cell.dead = true; if (cell.chart) cell.chart.dispose(); cell.chart = null; root.remove(); }});
    if (io) io.observe(root);
    fillPos(); paintHead();
    return cell;
  }

  // ---------------------------------------------------------------- ⛶ 크게: one cell over the whole window
  function setFull(cell) {
    if (D.full) { D.full.root.classList.remove("cg-full"); D.full.bigBtn.textContent = "⛶ 크게"; D.full.bigBtn.setAttribute("aria-pressed", "false"); }
    D.full = cell;
    document.documentElement.classList.toggle("cg-lock", !!cell);
    if (cell) {
      cell.root.classList.add("cg-full");
      cell.bigBtn.textContent = "닫기 (Esc)";
      cell.bigBtn.setAttribute("aria-pressed", "true");
      cell.bigBtn.focus({preventScroll: true});
    }
  }
  const onKey = (e) => { if (e.key === "Escape" && D.full) { const b = D.full.bigBtn; setFull(null); b.focus({preventScroll: true}); } };
  document.addEventListener("keydown", onKey);

  // ---------------------------------------------------------------- the grid; cells in view (only those poll)
  const io = typeof IntersectionObserver === "function" ? new IntersectionObserver((ents) => {
    for (const en of ents) { const c = D.cells.find((x) => x.root === en.target); if (c) c.seen = en.isIntersecting; }
  }, {rootMargin: "120px"}) : null;
  function layout() {
    const n = LAYOUTS[cfg.layout];
    grid.dataset.layout = cfg.layout;
    laySeg.set(cfg.layout);
    if (D.full && D.full.i >= n) setFull(null);
    while (D.cells.length > n) D.cells.pop().dispose();
    const added = [];
    while (D.cells.length < n) { const c = cellOf(D.cells.length); D.cells.push(c); grid.append(c.root); added.push(c); }
    return added;
  }
  async function loadCells(list) { for (const c of list) { if (!ctx.alive()) return; await c.load(); } }   // one after another: kind to the rate limit

  // ---------------------------------------------------------------- live data
  function paintStatus() {
    const d = D.live;
    const s = !d ? "off" : d.off ? "off" : d.unavailable ? "bad" : d.stale ? "warn" : "ok";
    status.set(!d ? "시세 확인 중" : d.off ? "시세 꺼짐" : d.unavailable ? "시세 받지 못함" : d.stale ? "시세 늦음 · 6초마다 다시" : "시세 6초마다", s);
    status.title = `${K.liveNote(d)} · 실시간 체결 흐름은 없고 6초마다 새 가격을 묻습니다`;
  }
  async function loadLive() {
    try { D.live = await ctx.api("/api/live"); } catch (e) { if (e && e.name === "AbortError") return; }
    paintStatus();
    for (const c of D.cells) {
      c.paintHead();
      const r = liveRow(c.coin);
      if (c.chart && r && r.ok) c.chart.tick(r.price);           // the forming bar follows the price (only while it is forming)
    }
  }
  async function poll() {
    const pairs = new Map();
    for (const c of D.cells) if (c.chart && c.key && (c.seen || D.full === c)) pairs.set(c.key, [c.coin, c.tf]);
    await Promise.all([loadLive(), ...[...pairs].map(async ([key, [coin, tf]]) => {
      let d;
      try { d = await ctx.api(`/api/klines?${new URLSearchParams({coin, tf, limit: "2"})}`); } catch (e) { return; }
      if (!d || !d.bars) return;
      for (const c of D.cells) if (c.chart && c.key === key) c.chart.merge(d.bars);
    })]);
  }
  async function loadPos() {
    try { D.pos = await ctx.api("/api/positions"); } catch (e) { if (e && e.name === "AbortError") return; }
    for (const c of D.cells) { c.fillPos(); c.drawLines(); }
  }

  const first = layout();
  await Promise.all([loadPos(), loadLive()]);
  await loadCells(first);
  ctx.every(POLL_MS, poll);
  ctx.every(30000, loadPos);
  return () => {
    document.removeEventListener("keydown", onKey);
    document.documentElement.classList.remove("cg-lock");
    if (io) io.disconnect();
    for (const c of D.cells) c.dispose();
  };
}
