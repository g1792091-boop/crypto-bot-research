// #/charts 여러 차트 (CONTRACT 9.8): the 7 coins side by side, one timeframe for all (5분 ~ 4시간, 15분 first), each
// with our open demo positions as entry lines (one per account entry, the colour = long / short) and its price, 24 h
// change and long / short count. A coin's title opens it in the terminal. Candles every 30 s (the server keeps them
// 10 s), the price every 10 s, positions.json every 30 s. Phone: one chart per row; tablet two; PC three or four.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {COINS} from "../labels.js";
import * as K from "../live-kit.js";

const TFS = ["5m", "15m", "30m", "1h", "4h"];

export async function mount(el, ctx) {
  await K.needCss();
  ctx.setTitle("여러 차트");
  let tf = TFS.includes(local.get("charts-tf")) ? local.get("charts-tf") : "15m";
  const tfSeg = ui.seg(TFS.map((x) => ({id: x, label: K.TF_SHORT[x]})), tf, (v) => { tf = v; local.set("charts-tf", v); loadAll(false); }, {label: "봉 길이"});
  const liveLine = h("p", {class: "note"});
  const cells = new Map();
  const grid = h("div", {class: "lv-cgrid"}, COINS.map((c) => {
    const price = h("b", {class: "num lv-ccp"}, "—"), chg = h("span", {class: "num lv-ccc"}), cnt = h("span", {class: "lv-ccn"});
    const box = h("div", {class: "lv-ccbox", role: "img", "aria-label": `${fmt.coin(c)} 차트`});
    const msg = h("div", {class: "lv-cmsg", hidden: true});
    const foot = h("div", {class: "lv-ccf"});
    const card = h("section", {class: "lv-p lv-cc1", "aria-label": `${fmt.coin(c)} 차트`},
      h("div", {class: "lv-ph"}, h("a", {class: "lv-cct", href: ctx.href("terminal", c), title: "터미널에서 크게 보기"}, h("h2", null, fmt.coin(c))),
        price, chg, h("span", {class: "grow"}), cnt),
      h("div", {class: "lv-ccwrap"}, box, msg), foot);
    cells.set(c, {card, box, msg, price, chg, cnt, foot, chart: null, key: ""});
    return card;
  }));
  el.append(ui.screenHead("여러 차트", "코인 7개를 한 번에 · 선 = 우리 데모 포지션의 진입 가격"),
    ui.card({cls: "dl-controls"}, ui.field("봉", tfSeg),
      h("div", {class: "lv-ckey"}, h("span", null, h("i", {class: "k-up"}), "롱 진입선"), h("span", null, h("i", {class: "k-dn"}), "숏 진입선"))),
    grid, liveLine,
    ui.note("봉은 바이낸스 공개 시세입니다 (대시보드 서버가 받아 10초 동안 보관). 코인 이름을 누르면 터미널에서 크게 봅니다. 주문은 넣지 않습니다."));

  let pos = null, live = null;
  const posOf = (c) => (pos && !isMissing(pos) ? (pos.positions || []).filter((p) => p.coin === c) : []);
  function paintCell(c) {
    const x = cells.get(c);
    const r = live && (live.coins || []).find((y) => y.coin === c);
    x.price.textContent = r && r.ok ? K.px(r.price) : "—";
    x.chg.textContent = r && r.ok ? fmt.pct(r.change_pct, true, 2) : "";
    x.chg.className = `num lv-ccc ${r && r.ok ? fmt.tone(r.change_pct) : ""}`;
    const bc = pos && !isMissing(pos) ? (pos.by_coin || []).find((y) => y.coin === c) : null;
    put(x.cnt, bc ? [h("span", {class: "up"}, `롱 ${bc.long}`), " ", h("span", {class: "down"}, `숏 ${bc.short}`)] : "");
    const groups = K.groupEntries(posOf(c));
    const u = posOf(c).reduce((a, p) => a + (K.liveUnreal(p, r && r.ok ? r.price : null) || 0), 0), uv = fmt.money(u, true);
    put(x.foot, groups.length ? [`열린 진입 ${fmt.int(groups.length)}개 · 평가 손익 `, ui.signed(uv, fmt.tone(u, uv), "b")]
      : pos && isMissing(pos) ? "포지션 준비 중" : "열린 데모 포지션 없음");
    if (x.chart) {
      x.chart.lines(groups, {price: r && r.ok ? r.price : null, labels: 0});
      if (r && r.ok) x.chart.tick(r.price);
    }
  }
  async function loadCoin(c, keep) {
    const x = cells.get(c);
    let d;
    try { d = await ctx.api(`/api/klines?${new URLSearchParams({coin: c, tf, limit: "240"})}`); } catch (e) {
      if (e && e.name === "AbortError") return;
      x.msg.hidden = false; put(x.msg, ui.errorBox(e, () => loadCoin(c, false)));
      return;
    }
    if (!ctx.alive()) return;
    if (d.off || d.unavailable || !d.bars || !(d.bars.t || []).length) {
      x.msg.hidden = false;
      put(x.msg, h("div", {class: "dl-missing"}, h("b", null, d.off ? "꺼짐" : "준비 중"), h("span", null, d.off ? " · 실시간 시세 꺼짐" : " · 봉을 아직 받지 못했습니다")));
      return;
    }
    x.msg.hidden = true;
    if (!x.chart) {
      try { x.chart = await K.liveChart(x.box, {compact: true}); } catch (e) { put(x.box, ui.empty("차트를 그리지 못했습니다.")); return; }
      if (!ctx.alive()) { x.chart.dispose(); return; }
    }
    const key = `${c}|${tf}`;
    x.chart.set(d.bars, tf, keep && x.key === key);
    x.key = key;
    paintCell(c);
  }
  async function loadAll(keep) {
    for (const c of COINS) { if (!ctx.alive()) return; await loadCoin(c, keep); }       // one after another: kind to the rate limit
  }
  async function loadPos() {
    try { pos = await ctx.api("/api/positions"); } catch (e) { if (e && e.name === "AbortError") return; }
    COINS.forEach(paintCell);
  }
  async function loadLive() {
    try { live = await ctx.api("/api/live"); } catch (e) { if (e && e.name === "AbortError") return; }
    liveLine.textContent = `가격: ${K.liveNote(live)}`;
    COINS.forEach(paintCell);
  }
  await Promise.all([loadPos(), loadLive()]);
  await loadAll(false);
  ctx.every(30000, () => loadAll(true));
  ctx.every(10000, loadLive);
  ctx.every(30000, loadPos);
  return () => { for (const x of cells.values()) if (x.chart) x.chart.dispose(); };
}
