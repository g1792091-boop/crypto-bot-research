// 터미널 윗줄의 시장 숫자 세 칸 (term-plus, owners' review 10/06 "터미널 위 줄에 미결제약정, 롱/숏, 하루 가격 범위"): 고른 코인의
//   미결제약정  (USDT, 1시간 변화)         /api/v4/topstats  (바이낸스 공개 선물 자료, 서버가 코인마다 60초 캐시)
//   롱/숏       (계좌 수 기준 비율 + 롱 몇 %)  /api/v4/topstats
//   24시간 범위 (저가 ─●─ 고가, 지금 가격의 자리)  the ticker the page already has (/api/ticker: /fapi/v1/ticker/24hr)
// HONESTY: a number that could not be read is "—" with the tooltip "불러오지 못함", never 0 and never a flat bar; the
// last good value of the SAME coin stays (dimmed, its age in the tooltip) for 10 minutes after a failed refresh, then
// "—"; the tooltip names the record time ("5분 단위 기록 14:05 기준"). The cells are market-wide numbers of that coin
// (not our bots'): a "시장" chip sits in the terminal's top strip already. When the window is too narrow they are hidden
// before anything else is cut (fit(): range first, then 미결제약정, then 롱/숏; no text is ever clipped).
import {h, fmt, serverNow} from "../core/pb.js";
import {rangePos, usdKo} from "./market-live.js";

const KEEP_MS = 10 * 60_000;
const REFRESH_MS = 60_000;
const FAIL_WORDS = "불러오지 못함 · 바이낸스 공개 자료를 받지 못했습니다 (잠시 뒤 다시 시도합니다)";
const LOAD_WORDS = "불러오는 중";

/** the cell's short label above its value */
const cell = (k, cls) => {
  const v = h("b", {class: "num term-sv"}, "—");
  const sub = h("span", {class: "num term-ss"});
  return {v, sub, el: h("div", {class: ["term-st", "term-sx", cls]}, h("span", null, k), h("span", {class: "term-sl"}, v, sub))};
};

/** topStats(ctx, st) -> {el, setSym, onTicker(tk), fit(row, movers), state()} */
export function topStats(ctx, st) {
  const oi = cell("미결제약정", "oi"), ls = cell("롱/숏 계좌", "ls"), rng = cell("24시간 범위", "rng");
  // the long / short bar: the share of accounts long (up colour) and short (down colour), the terminal's 롱 / 숏 colours
  const lsBar = h("i", {class: "term-lsb", "aria-hidden": "true"}, h("i", {class: "up"}), h("i", {class: "down"}));
  ls.el.querySelector(".term-sl").append(lsBar);
  // the range: low price, a bar with the price's place on it, high price
  const lo = h("span", {class: "num term-rl"}, "—"), hi = h("span", {class: "num term-rl"}, "—");
  const dot = h("i", {class: "term-rd"}), bar = h("span", {class: "term-rb2", "aria-hidden": "true"}, dot);
  rng.el.querySelector(".term-sl").replaceChildren(lo, bar, hi);
  const el = h("div", {class: "term-sxs", role: "group", "aria-label": "고른 코인의 시장 숫자: 미결제약정, 롱/숏, 24시간 범위"}, oi.el, ls.el, rng.el);

  let data = null, sym = st.sym, tok = 0, failedAt = 0, loadedFor = null, tk = null;
  const goodAt = {oi: 0, ls: 0};

  function paintOi() {
    const part = data && data.oi;
    const fresh = part && data.symbol === sym;
    oi.el.classList.toggle("old", !!(fresh && (part.stale || failedAt)));
    if (!fresh) {
      oi.v.textContent = "—"; oi.sub.textContent = "";
      oi.el.title = loadedFor === sym && failedAt ? `미결제약정: ${FAIL_WORDS}` : `미결제약정: ${LOAD_WORDS}`;
      return;
    }
    oi.v.textContent = usdKo(part.usd);                           // (the unit, USDT, is in its label tooltip: the row has no room for it)
    oi.sub.textContent = part.chg_1h == null ? "" : fmt.pct(part.chg_1h, 1);
    oi.sub.className = "num term-ss " + fmt.tone(part.chg_1h, oi.sub.textContent);
    oi.el.title = `${fmt.coin(sym)} 미결제약정 ${usdKo(part.usd)} USDT (아직 닫지 않은 계약의 총 금액)` + (part.chg_1h == null ? "" : ` · 1시간 전보다 ${fmt.pct(part.chg_1h, 2)}`)
      + ` · 5분 단위 기록 ${fmt.hm(part.ts)} 기준 · 바이낸스 시장 전체 숫자 (우리 봇 아님)`
      + (part.stale || failedAt ? ` · 새로 받지 못해 ${fmt.ago(part.ts, serverNow())} 값 (흐리게)` : "");
  }
  function paintLs() {
    const part = data && data.ls;
    const fresh = part && data.symbol === sym;
    ls.el.classList.toggle("old", !!(fresh && (part.stale || failedAt)));
    if (!fresh) {
      ls.v.textContent = "—"; ls.sub.textContent = ""; lsBar.hidden = true;
      ls.el.title = loadedFor === sym && failedAt ? `롱/숏 계좌 비율: ${FAIL_WORDS}` : `롱/숏 계좌 비율: ${LOAD_WORDS}`;
      return;
    }
    ls.v.textContent = fmt.num(part.ratio, 2);
    ls.sub.textContent = `롱 ${fmt.pct(part.long, 0, false)}`;
    ls.sub.className = "num term-ss";
    lsBar.hidden = false;
    lsBar.firstChild.style.width = (part.long * 100).toFixed(1) + "%";
    lsBar.lastChild.style.width = (part.short * 100).toFixed(1) + "%";
    ls.el.title = `${fmt.coin(sym)} 롱/숏 비율 ${fmt.num(part.ratio, 2)} = 계좌의 ${fmt.pct(part.long, 1, false)}가 롱, ${fmt.pct(part.short, 1, false)}가 숏 `
      + `(돈의 크기가 아니라 계좌 수 기준 · 1보다 크면 롱 계좌가 더 많음) · 5분 단위 기록 ${fmt.hm(part.ts)} 기준 · 바이낸스 시장 전체 숫자 (우리 봇 아님)`
      + (part.stale || failedAt ? ` · 새로 받지 못해 ${fmt.ago(part.ts, serverNow())} 값 (흐리게)` : "");
  }
  function paintRange() {
    const t = tk && tk[sym];
    const c = t ? Number(t.c ?? t.mark) : NaN, l = t ? Number(t.l) : NaN, hh = t ? Number(t.h) : NaN;
    const p = t ? rangePos(c, l, hh) : null;
    if (p == null) {
      lo.textContent = hi.textContent = "—"; dot.hidden = true;
      rng.el.title = t ? "24시간 가격 범위: 이 코인의 고가·저가를 받지 못했습니다 (불러오지 못함)" : `24시간 가격 범위: ${LOAD_WORDS}`;
      return;
    }
    lo.textContent = fmt.price(l); hi.textContent = fmt.price(hh);
    dot.hidden = false; dot.style.left = `${(p * 100).toFixed(1)}%`;
    rng.el.title = `${fmt.coin(sym)} 최근 24시간 저가 ${fmt.price(l)} · 고가 ${fmt.price(hh)} · 지금 ${fmt.price(c)}은 하루 범위의 ${fmt.pct(p, 0, false)} 자리 `
      + `(0% = 저가, 100% = 고가) · 서버가 5초마다 바이낸스에서 받음`;
  }
  const paint = () => { paintOi(); paintLs(); paintRange(); };

  async function load() {
    const my = ++tok, want = sym;
    let d = null, bad = false;
    try { d = await ctx.api(`/api/v4/topstats?symbol=${encodeURIComponent(want)}`); }
    catch (e) { if (e && e.name === "AbortError") return; bad = true; }
    if (my !== tok || want !== sym || !ctx.alive()) return;
    loadedFor = want;
    const now = Date.now();
    if (d && typeof d === "object") {
      // each part on its own: a good new one replaces the old; a missing one keeps the last good of this coin for 10 minutes
      const keep = (k) => (data && data.symbol === want && data[k] && now - goodAt[k] <= KEEP_MS ? data[k] : null);
      const next = {symbol: want, errors: d.errors || {}};
      for (const k of ["oi", "ls"]) {
        if (d[k]) { next[k] = d[k]; if (!d[k].stale) goodAt[k] = now; }
        else { next[k] = keep(k); }
      }
      failedAt = (d.errors && (d.errors.oi || d.errors.ls)) || bad ? now : 0;
      data = next;
    } else {
      failedAt = now;
      const keep = (k) => (data && data.symbol === want && data[k] && now - goodAt[k] <= KEEP_MS ? data[k] : null);
      data = {symbol: want, oi: keep("oi"), ls: keep("ls"), errors: {}};
    }
    paint();
  }
  ctx.every(REFRESH_MS, load, {now: true});

  return {
    el,
    setSym(s) { sym = s; data = data && data.symbol === s ? data : null; failedAt = 0; loadedFor = null; paint(); load(); },
    onTicker(t) { tk = t; paintRange(); },
    /** Show every cell, then hide them one by one (range first, then 미결제약정, then 롱/숏) while the top row would
     *  clip something (the row itself overflows, or the movers box is cut). row / movers: the strip's elements. */
    fit(row, movers) {
      const order = [rng.el, oi.el, ls.el];
      for (const c of order) c.hidden = false;
      row.classList.remove("term-tight");
      const tight = () => row.scrollWidth > row.clientWidth + 1 || (movers && movers.scrollWidth > movers.clientWidth + 1);
      // first the short words give way ("(롱이 냄)", "USDT": their tooltips keep them), only then the cells themselves
      if (tight()) row.classList.add("term-tight");
      for (const c of order) { if (!tight()) break; c.hidden = true; }
    },
  };
}
