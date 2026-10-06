// 시장 › 코인 온도판 · 시장 파생 지표판 · 시장 강제청산 보드 (거래 채우기). Real numbers only:
//   온도판   the store ticker (/api/ticker through the store, 5 s): price (glows when it really moved), 24 h %, where the
//            price sits inside the 24 h low-high range, 24 h volume, funding rate with its countdown.
//   지표판   /api/v4/flowlive (flow.db, the hourly recorder; read-only, cached 60 s on the server): open interest with
//            1 h / 24 h change, long/short ratios now vs 24 h ago, taker buy/sell of the newest hour, premium, sparklines.
//   강제청산 /api/v4/flowlive/liq (liq.db, the public forced-order stream): long vs short liquidated USDT over 1 h and
//            24 h, the biggest single one, the latest 5 sliding in when they are new.
// Missing files say 수집 전 / 기록기 멈춤, never a zero. Nothing here touches a paper account.
import {h, ui, fmt, store, motion, bars, serverNow, liqkit} from "../core/pb.js";

const {usdShort, liqTone, liqKo, LIQ_TIP} = liqkit;       // one colour rule (롱 청산 = up, 숏 청산 = down: the terminal's) and one money format ($K/M)
import {countdown, fundPct} from "./positions-book.js";

/** Where the price sits in the 24 h range: 0 = at the low, 1 = at the high (null without a range). */
export function rangePos(c, lo, hi) {
  const x = Number(c), l = Number(lo), hh = Number(hi);
  if (!Number.isFinite(x) || !Number.isFinite(l) || !Number.isFinite(hh) || hh <= l) return null;
  return Math.max(0, Math.min(1, (x - l) / (hh - l)));
}
/** A time of the last 24 h: "06:52", or "어제 20:33" when it was before 00:00 KST today (never reads like a future time). */
export function whenKo(ts) {
  if (ts == null) return "—";
  return Number(ts) < fmt.kstMidnight(serverNow()) ? `어제 ${fmt.hm(ts)}` : fmt.hm(ts);
}
/** "12.3억" style USDT amounts for big numbers (Korean units: 만 / 억 / 조). */
export function usdKo(x) {
  const v = Number(x);
  if (x == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v), sg = v < 0 ? "−" : "";
  if (a >= 1e12) return `${sg}${fmt.num(a / 1e12, 2)}조`;
  if (a >= 1e8) return `${sg}${fmt.num(a / 1e8, a >= 1e10 ? 0 : 1)}억`;
  if (a >= 1e4) return `${sg}${fmt.num(a / 1e4, a >= 1e6 ? 0 : 1)}만`;
  return `${sg}${fmt.num(a, 0)}`;
}
/** Split of a long / short pair as shares (0..1), null when both are zero. */
export function split(l, s) {
  const a = Number(l) || 0, b = Number(s) || 0;
  return a + b > 0 ? {long: a / (a + b), short: b / (a + b)} : null;
}
const chgEl = (x, dec = 1) => h("span", {class: ["num", fmt.tone(x)]}, x == null ? "—" : fmt.pct(x, dec));
const ratio = (x) => (x == null ? "—" : fmt.num(x, 2));

// ---------------------------------------------------------------- 코인 온도판
export function tempBoard(ctx) {
  const el = h("div", {class: "mk-temp", role: "list", "aria-label": "코인 온도판"});
  const tiles = new Map();
  for (const sym of bars.SYMS) {
    const px = h("b", {class: "mk-t-px num"}, "—"), chg = h("span", {class: "num"}, "—");
    const dot = h("i", {class: "mk-t-dot"}), lo = h("span", {class: "num"}, "—"), hi = h("span", {class: "num"}, "—");
    const vol = h("b", {class: "num"}, "—"), fund = h("b", {class: "num"}, "—"), left = h("span", {class: "num muted"}, "");
    const tile = h("a", {class: "mk-t", role: "listitem", href: ctx.href("chart", sym), "aria-label": `${fmt.coin(sym)} 차트 보기`},
      h("div", {class: "mk-t-h"}, h("span", {class: "mk-t-c"}, fmt.coin(sym)), sym === "XRPUSDT" ? ui.pill("기록만", "thin", "XRP는 기록만 하고 매매하지 않습니다") : null, h("span", {class: "grow"}), chg),
      px,
      h("div", {class: "mk-t-rng", title: "24시간 최저 ~ 최고 사이에서 지금 가격의 자리"}, h("div", {class: "mk-t-bar"}, dot), h("div", {class: "mk-t-lh"}, lo, hi)),
      h("div", {class: "mk-t-kv"}, h("span", null, "24시간 거래대금"), vol),
      h("div", {class: "mk-t-kv"}, h("span", null, "펀딩"), h("span", null, fund, " ", left)));
    tiles.set(sym, {tile, px, chg, dot, lo, hi, vol, fund, left, T: null});
    el.append(tile);
  }
  const update = () => {
    const tk = store.get("ticker") || {};
    for (const [sym, t] of tiles) {
      const x = tk[sym];
      if (!x) continue;
      const c = Number(x.c);
      const tone = motion.tickPrice(t.px, c, fmt.price(c), sym);
      if (tone) t.tile.dataset.tone = tone;
      t.chg.textContent = x.p == null ? "—" : fmt.pctOf(Number(x.p), 2, true);
      t.chg.className = "num " + fmt.tone(Number(x.p));
      const rp = rangePos(c, x.l, x.h);
      t.dot.style.left = rp == null ? "50%" : `${(rp * 100).toFixed(1)}%`;
      t.dot.hidden = rp == null;
      t.lo.textContent = x.l == null ? "—" : fmt.price(Number(x.l));
      t.hi.textContent = x.h == null ? "—" : fmt.price(Number(x.h));
      t.vol.textContent = x.q == null ? "—" : `${usdKo(x.q)} USDT`;
      t.fund.textContent = fundPct(x.r);
      t.fund.className = "num " + fmt.tone(-Number(x.r || 0));
      t.T = x.T || null;
    }
    tick();
  };
  const tick = () => { for (const t of tiles.values()) t.left.textContent = t.T ? `${countdown(t.T)} 뒤` : ""; };
  return {el, update, tick};
}

// ---------------------------------------------------------------- 시장 파생 지표판
export function flowBoard(ctx) {
  const body = h("div", {class: "mk-flow"}, motion.shimmer(4));
  const foot = h("p", {class: "pos-note"});
  const card = ui.card({plate: "시장 파생 지표판", sub: "미결제약정 · 롱숏 비율 · 테이커 · 프리미엄"}, body, foot);
  let d = null;
  const prev = new Map();
  const paint = () => {
    if (!d) return;
    if (!d.ready) {
      body.replaceChildren(h("div", {class: "mk-wait"}, ui.notYet("수집 전"), h("span", null, d.why || "시장 지표 기록이 아직 없습니다")));
      foot.textContent = "기록기가 1시간마다 바이낸스 공개 통계를 받아 저장합니다. 기록이 생기면 여기 표가 채워집니다.";
      return;
    }
    const rules = d.hint_rules || {};
    const head = h("div", {class: "mk-fr mk-fh", "aria-hidden": "true"}, h("span", null, "코인"), h("span", null, "미결제약정 (USDT)"), h("span", null, "24시간 흐름"),
      h("span", null, "롱/숏 (전체 계좌)"), h("span", null, "고수 포지션 롱/숏"), h("span", null, "테이커 매수/매도 1시간"), h("span", null, "프리미엄"));
    const rows = (d.coins || []).map((x) => {
      if (!x.ts) return h("div", {class: "mk-fr", role: "row"}, h("b", null, fmt.coin(x.symbol)), h("span", {class: "muted mk-span"}, "이 코인 기록 아직 없음"));
      const was = prev.get(x.symbol);
      const r = h("div", {class: "mk-fr", role: "row"},
        h("span", {class: "mk-fc"}, h("b", null, fmt.coin(x.symbol)), (x.hints || []).map((k) => ui.pill((rules[k] || {}).ko || k, k.includes("crowd") || k === "oi_jump" ? "warn" : "thin", (rules[k] || {}).rule))),
        h("span", {class: "mk-fv", "data-k": "미결제약정"}, h("b", {class: "num"}, usdKo(x.oi_usd)), h("small", null, "1시간 ", chgEl(x.oi_chg_1h), " · 24시간 ", chgEl(x.oi_chg_24h))),
        h("span", {class: "mk-fs", "data-k": "24시간 흐름"}, ui.sparkline((x.oi_series || []).map((p) => p[1]), {w: 120, h: 28, label: `${fmt.coin(x.symbol)} 미결제약정 24시간`, cls: "lc"}),
          ui.sparkline((x.ls_series || []).map((p) => p[1]), {w: 120, h: 20, label: `${fmt.coin(x.symbol)} 롱/숏 비율 24시간`, cls: "ls", base: 1})),
        h("span", {class: "mk-fv", "data-k": "롱/숏 (전체)"}, h("b", {class: ["num", x.ls_global > 1 ? "up" : x.ls_global < 1 ? "down" : ""]}, ratio(x.ls_global)),
          h("small", null, x.long_share != null ? `롱 ${fmt.pct(x.long_share, 0, false)} · ` : "", `24시간 전 ${ratio(x.ls_global_24h)}`)),
        h("span", {class: "mk-fv", "data-k": "고수 포지션"}, h("b", {class: "num"}, ratio(x.ls_top)), h("small", null, `24시간 전 ${ratio(x.ls_top_24h)}`)),
        h("span", {class: "mk-fv", "data-k": "테이커 1시간"}, h("b", {class: ["num", x.taker_1h > 1 ? "up" : x.taker_1h < 1 ? "down" : ""]}, ratio(x.taker_1h)),
          h("small", null, x.taker_1h == null ? "" : x.taker_1h >= 1 ? "시장가 매수가 많음" : "시장가 매도가 많음")),
        h("span", {class: "mk-fv", "data-k": "프리미엄"}, h("b", {class: "num"}, x.premium == null ? "—" : fmt.pctOf(x.premium * 100, 3, true)),
          h("small", null, x.premium_24h_avg == null ? "" : `24시간 평균 ${fmt.pctOf(x.premium_24h_avg * 100, 3, true)}`)));
      if (was != null && was !== x.ts) motion.flash(r, "accent");
      prev.set(x.symbol, x.ts);
      return r;
    });
    body.replaceChildren(h("div", {class: "mk-ftab", role: "table", "aria-label": "시장 파생 지표"}, head, ...rows),
      h("div", {class: "mk-hints"}, Object.values(rules).map((r) => h("span", null, h("b", null, r.ko), ` = ${r.rule}`))));
    foot.textContent = `${d.every_ko || "1시간마다 갱신"} · 마지막 기록 ${d.as_of ? fmt.kst(d.as_of) : "—"} · 바이낸스 선물 전체 시장 숫자 (우리 계좌와 무관) · 롱/숏 1보다 크면 롱이 많음`;
  };
  const load = async () => {
    try { d = await ctx.api("/api/v4/flowlive"); if (ctx.alive()) paint(); }
    catch (e) { if (!(e && e.name === "AbortError") && !d) body.replaceChildren(ui.errorBox(e, load)); }
  };
  return {el: card, load};
}

// ---------------------------------------------------------------- 시장 강제청산 보드
export function liqBoard(ctx) {
  const body = h("div", {class: "mk-liq"}, motion.shimmer(4));
  const feed = h("div", {class: "mk-lfeed", role: "list", "aria-label": "최근 강제청산 5건"});
  const foot = h("p", {class: "pos-note"});
  const card = ui.card({plate: "시장 강제청산", sub: "바이낸스 선물 전체 · 1시간 / 24시간"}, body, h("div", {class: "mk-lf-h"}, "최근 5건"), feed, foot);
  let d = null;
  const seen = new Set();
  const bar = (o, label) => {
    const sp = split(o.long_usd, o.short_usd);
    return h("div", {class: "mk-lb"}, h("span", {class: "mk-lb-k"}, label),
      h("div", {class: "mk-lb-bar", role: "img", "aria-label": `${label} 롱 청산 ${usdShort(o.long_usd)} · 숏 청산 ${usdShort(o.short_usd)}`},
        sp ? [h("i", {class: "l", style: {width: `${(sp.long * 100).toFixed(1)}%`}}), h("i", {class: "s", style: {width: `${(sp.short * 100).toFixed(1)}%`}})] : h("i", {class: "z"})),
      h("span", {class: "mk-lb-v"}, h("b", {class: [liqTone("long"), "num"]}, usdShort(o.long_usd)), " · ", h("b", {class: [liqTone("short"), "num"]}, usdShort(o.short_usd))));
  };
  const paint = () => {
    if (!d) return;
    if (!d.ready) {
      body.replaceChildren(h("div", {class: "mk-wait"}, ui.notYet("수집 전"), h("span", null, d.why || "강제청산 기록이 아직 없습니다")));
      feed.replaceChildren(); foot.textContent = d.note_ko || ""; return;
    }
    body.replaceChildren(
      ...(d.stale ? [h("p", {class: "down"}, `마지막 기록이 ${fmt.ago(d.last_record_ts, serverNow())}: 기록기가 멈췄을 수 있어 아래 0은 '모름'일 수 있습니다`)] : []),
      h("div", {class: "mk-lk", title: LIQ_TIP}, h("span", null, h("i", {class: "l"}), "롱 청산 (가격이 내려 롱이 털림)"), h("span", null, h("i", {class: "s"}), "숏 청산 (가격이 올라 숏이 털림)"), h("span", {class: "muted"}, "색 = 정리된 쪽 · 달러")),
      ...(d.coins || []).map((x) => h("div", {class: "mk-lr"},
        h("b", {class: "mk-lr-c"}, fmt.coin(x.symbol)),
        h("div", {class: "mk-lr-bars"}, bar(x.h1, "1시간"), bar(x.h24, d.partial_24h ? "24시간*" : "24시간")),
        h("span", {class: "mk-lr-big"}, x.biggest ? [h("small", null, "가장 큰 한 건"), h("b", {class: ["num", liqTone(x.biggest.liquidated)]}, usdShort(x.biggest.usd)),
          h("small", null, `${x.biggest.liquidated === "long" ? "롱" : "숏"} · ${whenKo(x.biggest.ts)}`)] : h("small", {class: "muted"}, "24시간 0건")))));
    const rows = (d.latest || []).map((r) => {
      const k = `${r.symbol}|${r.ts}|${r.usd}`;
      const row = h("div", {class: "mk-lfr", role: "listitem"}, h("span", {class: "num muted"}, whenKo(r.ts)), h("b", null, fmt.coin(r.symbol)),
        h("span", {class: liqTone(r.liquidated)}, liqKo(r.liquidated)),
        h("span", {class: "num"}, fmt.price(r.price)), h("b", {class: "num"}, usdShort(r.usd)));
      if (seen.size && !seen.has(k)) motion.fillIn(row, liqTone(r.liquidated));
      return [k, row];
    });
    for (const [k] of rows) seen.add(k);
    feed.replaceChildren(...(rows.length ? rows.map((x) => x[1]) : [ui.empty("아직 없음")]));
    foot.textContent = `${d.note_ko}. ${d.partial_24h ? `* 기록 시작(${fmt.kst(d.since_ts)}) 뒤만 셉니다. ` : ""}20초마다 새로 읽음 · 마지막 기록 ${d.last_record_ts ? fmt.kst(d.last_record_ts) : "—"}`;
  };
  const load = async () => {
    try { d = await ctx.api("/api/v4/flowlive/liq"); if (ctx.alive()) paint(); }
    catch (e) { if (!(e && e.name === "AbortError") && !d) body.replaceChildren(ui.errorBox(e, load)); }
  };
  return {el: card, load};
}

// ---------------------------------------------------------------- 차트 › 이 코인 시장 지표 (the same two answers, one coin)
export function coinFlowCard(ctx, sym0) {
  let sym = sym0, f = null, l = null;
  const body = h("div", {class: "mk-cf"}, motion.shimmer(2));
  const foot = h("p", {class: "pos-note"});
  const el = ui.card({plate: "이 코인 시장 지표", sub: "바이낸스 선물 전체 · 우리 계좌와 무관"}, body, foot);
  const cell = (k, v, sub) => h("div", {class: "mk-cf-c"}, h("span", null, k), v, sub ? h("small", null, sub) : null);
  const paint = () => {
    if (!f && !l) return;
    const x = f && f.ready ? (f.coins || []).find((c) => c.symbol === sym && c.ts) : null;
    const q = l && l.ready ? (l.coins || []).find((c) => c.symbol === sym) : null;
    if (!x && !q) {
      body.replaceChildren(h("div", {class: "mk-wait"}, ui.notYet(sym === "XRPUSDT" ? "기록 안 함" : "수집 전"),
        h("span", null, sym === "XRPUSDT" ? "XRP는 시장 지표를 기록하지 않습니다" : "이 코인의 시장 지표 기록이 아직 없습니다")));
      foot.textContent = "";
      return;
    }
    const rules = (f && f.hint_rules) || {};
    const parts = [
      x ? cell("미결제약정", h("b", {class: "num"}, `${usdKo(x.oi_usd)} USDT`), h("span", null, "1시간 ", chgEl(x.oi_chg_1h), " · 24시간 ", chgEl(x.oi_chg_24h))) : cell("미결제약정", ui.notYet()),
      x ? cell("롱/숏 (전체 계좌)", h("b", {class: "num"}, ratio(x.ls_global)), `24시간 전 ${ratio(x.ls_global_24h)}`) : null,
      x ? cell("고수 포지션 롱/숏", h("b", {class: "num"}, ratio(x.ls_top)), `24시간 전 ${ratio(x.ls_top_24h)}`) : null,
      x ? cell("테이커 매수/매도 1시간", h("b", {class: ["num", x.taker_1h > 1 ? "up" : x.taker_1h < 1 ? "down" : ""]}, ratio(x.taker_1h)), null) : null,
      q ? cell("강제청산 1시간 (롱 · 숏)", h("b", {class: "num"}, h("span", {class: liqTone("long")}, usdShort(q.h1.long_usd)), " · ", h("span", {class: liqTone("short")}, usdShort(q.h1.short_usd))), "롱 · 숏 (달러)") : cell("강제청산", ui.notYet()),
      q ? cell("강제청산 24시간 (롱 · 숏)", h("b", {class: "num"}, h("span", {class: liqTone("long")}, usdShort(q.h24.long_usd)), " · ", h("span", {class: liqTone("short")}, usdShort(q.h24.short_usd))),
        q.biggest ? `가장 큰 한 건 ${usdShort(q.biggest.usd)} (${q.biggest.liquidated === "long" ? "롱" : "숏"} ${whenKo(q.biggest.ts)})` : "24시간 0건") : null,
      x ? h("div", {class: "mk-cf-s"}, h("span", null, "미결제약정 24시간"), ui.sparkline((x.oi_series || []).map((p) => p[1]), {w: 240, h: 30, cls: "lc", label: "미결제약정 24시간"})) : null,
      x && x.hints && x.hints.length ? h("div", {class: "mk-cf-hint"}, x.hints.map((k) => ui.pill((rules[k] || {}).ko || k, "warn", (rules[k] || {}).rule))) : null,
    ];
    body.replaceChildren(...parts.filter(Boolean));
    foot.replaceChildren(x ? `시장 지표 마지막 기록 ${fmt.kst(x.ts)} (1시간마다) · ` : "", "강제청산은 20초마다 · ", h("a", {href: ctx.href("market")}, "여섯 코인 전부 보기 (시장)"));
  };
  const load = async () => {
    const [a, b] = await Promise.all([ctx.api("/api/v4/flowlive").catch(() => null), ctx.api("/api/v4/flowlive/liq").catch(() => null)]);
    if (a) f = a;
    if (b) l = b;
    if (ctx.alive()) paint();
  };
  el.setSym = (s) => { sym = s; paint(); };
  el.load = load;
  return el;
}
