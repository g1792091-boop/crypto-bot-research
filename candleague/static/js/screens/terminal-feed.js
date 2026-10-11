// 터미널 coin strip and 우리 봇 체결 (the rule bot's v4 terminal-feed.js + terminal-coinpos.js, copied and adapted).
//   coinStrip   the six coins over the chart: live price (a glow only on a real move), 24 h change, and under it the
//               league's open positions on that coin in the chosen 묶음 — "롱 n · 숏 n" with the crowding dot (5 or more
//               positions, 80 % or more one way) and a dot for the sign of their unrealized total (B11). A tap picks the coin.
//   fillsFeed   OUR accounts' fills as they come: the closed trades of /api/fills (exits, and their entries) and the
//               entries found in /api/positions (a position that was not there at the last answer is a new entry).
//               Dense single-line rows: age · tag (진입 / 손절 / 익절 / 잠금 / 청산) · account · coin side · result. A
//               hidden DeepSeek account (D11) is folded into count rows per minute ("딥시크 · 3건 · 개수만"); no price,
//               leverage or money of theirs. The recent entries' long / short bar beneath. A row picks that account.
// A row that really arrived while the page is open fades in once; ages ('6s', '4m') are repainted by the 1 s tick.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as LK from "../lk.js";
import {liveRow, markOf} from "../live.js";
import {crowd, inGroup, livePnl, liveAllowed} from "../poskit.js";
import {tickPrice, fadeIn, reduced, visible} from "../v4kit.js";
import {COINS, coinShort, coinOf, sideKo, reasonKo} from "../labels.js";
import {panel, ratioBar, ping, ageCell, acctLabel, hiddenFill, hiddenPos, usdt} from "./terminal-kit.js";

// ---------------------------------------------------------------- the coin strip
/** coinStrip(ctx, st, onPick) -> {el, setCoin(), onLive(), onPositions(doc), repaint()} */
export function coinStrip(ctx, st, onPick) {
  const rows = new Map();
  const list = h("div", {class: "tm-wl", role: "listbox", "aria-label": "코인 고르기"}, COINS.map((c) => {
    const px = h("span", {class: "num tm-wpx"}, "—"), chg = h("span", {class: "num tm-wch"}, "");
    const pos = h("span", {class: "tm-wpos muted"}, "—");
    const b = h("button", {type: "button", class: "tm-wr", role: "option", "aria-selected": String(c === st.coin), onclick: () => onPick(c),
      title: `${coinShort(c)} 보기`}, h("span", {class: "tm-wtop"}, h("b", null, coinShort(c)), px), h("span", {class: "tm-wbot"}, chg, pos));
    rows.set(c, {b, px, chg, pos});
    return b;
  }));
  const el = h("nav", {class: "tm-coins", "aria-label": "코인 (후보 리그의 여섯 코인)"}, list);
  let doc = null;
  function paintPrices() {
    for (const [c, r] of rows) {
      const lr = liveRow(c);
      if (!lr || lr.ok === false || lr.price == null) { r.px.textContent = "—"; r.chg.textContent = ""; r.b.title = `${coinShort(c)}: 시세 없음`; continue; }
      tickPrice(r.px, Number(lr.price), fmt.price(lr.price), c);
      r.chg.textContent = lr.change_pct == null ? "" : fmt.pct(lr.change_pct, true, 2);
      r.chg.className = "num tm-wch " + fmt.tone(lr.change_pct);
    }
  }
  function paintPos() {
    const allowed = liveAllowed(doc);
    for (const [c, r] of rows) {
      if (!doc || doc.status) { put(r.pos, "—"); r.pos.className = "tm-wpos muted"; r.pos.title = doc ? "엔진 기록 준비 중" : "불러오는 중"; continue; }
      const ps = (doc.positions || []).filter((p) => p.coin === c && inGroup(p, st.grp));
      const L = ps.filter((p) => Number(p.side) > 0).length, S = ps.length - L, hid = ps.filter(hiddenPos).length;
      if (!ps.length) { put(r.pos, "포지션 없음"); r.pos.className = "tm-wpos muted"; r.pos.title = `${coinShort(c)}에 열린 포지션이 없습니다 (고른 묶음)`; continue; }
      const k = crowd({long: L, short: S});
      let pnl = 0, known = 0;
      if (allowed) for (const p of ps) { const u = livePnl(p, markOf(c)); if (u) { pnl += u.pnl; known += 1; } }
      const tone = known ? (Math.abs(pnl) < 0.005 ? "flat" : pnl > 0 ? "up" : "down") : "flat";
      put(r.pos, h("span", {class: "up"}, `${fmt.int(L)}↑`), " ", h("span", {class: "down"}, `${fmt.int(S)}↓`),
        k.on ? h("i", {class: "tm-crowd", "aria-label": "한 방향 몰림"}) : null, known ? h("i", {class: ["tm-wdot", tone], "aria-hidden": "true"}) : null);
      r.pos.className = "tm-wpos num";
      r.pos.title = `${coinShort(c)}에 열린 포지션 ${fmt.int(ps.length)}개 (롱 ${fmt.int(L)} · 숏 ${fmt.int(S)})`
        + (k.on ? ` · 한 방향 몰림 (${Math.round(k.share * 100)}%가 ${k.side > 0 ? "롱" : "숏"})` : "")
        + (known ? ` · 점 = 미실현 합계 ${usdt(pnl)} USDT (마크 가격, ${known}개)` : allowed ? "" : " · 엔진이 따라잡는 중이라 손익 점 없음")
        + (hid ? ` · 딥시크 ${hid}개는 개수만` : "");
    }
  }
  return {
    el,
    setCoin(c) { for (const [k, r] of rows) r.b.setAttribute("aria-selected", String(k === c)); },
    onLive() { paintPrices(); paintPos(); },
    onPositions(d) { doc = d; paintPos(); },
    repaint() { paintPos(); },
  };
}

// ---------------------------------------------------------------- 우리 봇 체결
const REASON_SHORT = {SL: "손절", TP: "익절", LOCK: "잠금", LIQ: "청산"};
const MAX_ROWS = 40;

/** fillsFeed(ctx, st, onPick) -> {el, onFills(rows, first), onPositions(doc), ratio} ; onPick({account, coin, at}) */
export function fillsFeed(ctx, st, onPick) {
  const S = {ev: [], seen: new Set(), nodes: new Map(), posSeen: null, failed: false, loaded: false};
  const list = h("div", {class: "tm-feed", role: "list", "aria-live": "off"});
  const ratio = ratioBar([{key: "L", label: "롱", tone: "up"}, {key: "S", label: "숏", tone: "down"}], {label: "최근 진입 롱·숏"});
  const ratioK = h("span", {class: "tm-rbk"}, "최근 진입");
  const el = panel("우리 봇 체결", {cls: "tm-fills", sub: "190계좌 · 누르면 그 계좌", scroll: true,
    tip: "후보 리그 계좌들의 진입·청산 (엔진은 5분마다 기록하므로 몇 분 늦게 보입니다) · 청산 손익은 수수료·펀딩 포함 · 딥시크 금액 숨김이면 딥시크는 건수만"}, list);
  el.append(h("div", {class: "tm-pf"}, h("div", {class: "tm-rbrow"}, ratioK, ratio)));

  const dsMoney = () => (st.pos && !st.pos.status ? !!st.pos.ds_money : !!(LK.league() && LK.league().ds_money));
  const add = (e, isLive) => {
    if (S.seen.has(e.key)) return false;
    S.seen.add(e.key);
    e.live = isLive;
    S.ev.push(e);
    return true;
  };
  const fromFill = (f, isLive) => {
    const a = LK.index().byId[f.account] || null;
    const hid = hiddenFill(f, a, dsMoney());
    const out = [{key: `x:${f.account}:${f.exit_time}`, t: Number(f.exit_time) || 0, kind: "exit", id: f.account, a, hid, coin: coinOf(f.symbol),
      side: Number(f.side) > 0 ? 1 : -1, lev: f.leverage, pnl: hid ? null : f.pnl, roe: hid ? null : f.roe, reason: f.exit_reason,
      win: f.pnl != null ? f.pnl > 0 : !!f.win, at: f.entry_time, live: isLive}];
    if (f.entry_time) out.push({key: `e:${f.account}:${f.entry_time}`, t: Number(f.entry_time), kind: "entry", id: f.account, a, hid, coin: coinOf(f.symbol),
      side: Number(f.side) > 0 ? 1 : -1, lev: f.leverage, price: hid ? null : f.entry_price, at: f.entry_time, live: false});
    return out;
  };
  const fromPos = (p, isLive) => ({key: `e:${p.id}:${p.since}`, t: Number(p.since) || 0, kind: "entry", id: p.id,
    a: LK.index().byId[p.id] || {id: p.id, role: p.role, kind: p.kind, name: p.name, tf: p.tf}, hid: hiddenPos(p), coin: p.coin,
    side: Number(p.side) > 0 ? 1 : -1, lev: p.lev, price: hiddenPos(p) ? null : p.entry, at: p.since, open: true, live: isLive});

  function models() {
    S.ev.sort((x, y) => y.t - x.t || (x.kind === "exit" ? -1 : 1));
    S.ev = S.ev.slice(0, 500);
    const out = [], fold = new Map();
    for (const e of S.ev) {
      if (out.length >= MAX_ROWS) break;
      const a = e.a || {};
      if (!inGroup({role: a.role, kind: a.kind}, st.grp)) continue;
      if (!e.hid) { out.push({id: e.key, one: e, live: e.live, t: e.t}); continue; }
      const k = `ds:${e.kind}:${Math.floor(e.t / 60000)}`;
      let m = fold.get(k);
      if (!m) { m = {id: "f:" + k, kind: e.kind, t: e.t, n: 0, L: 0, S: 0, win: 0, coins: new Set(), live: false}; fold.set(k, m); out.push(m); }
      m.n += 1; if (e.side > 0) m.L += 1; else m.S += 1;
      if (e.kind === "exit" && e.win) m.win += 1;
      m.coins.add(coinShort(e.coin));
      if (e.live) m.live = true;
    }
    return out;
  }
  const tagOf = (e) => (e.kind === "entry" ? h("span", {class: "tm-tag in"}, "진입")
    : h("span", {class: ["tm-tag", e.reason === "LIQ" ? "liq" : e.win ? "up" : "down"], title: reasonKo(e.reason)}, REASON_SHORT[e.reason] || reasonKo(e.reason)));
  function rowOf(m) {
    if (m.one) {
      const e = m.one;
      const right = e.kind === "exit" ? h("b", {class: ["num", "tm-fv", fmt.tone(e.pnl, usdt(e.pnl))]}, usdt(e.pnl))
        : h("span", {class: "num tm-fv muted"}, e.price == null ? "" : fmt.price(e.price));
      const what = `${coinShort(e.coin)} ${sideKo(e.side)}${e.lev ? ` ${fmt.lev(e.lev)}` : ""}${e.kind === "exit" && e.roe != null ? ` · ROE ${fmt.pct(e.roe * 100, true, 0)}` : ""}`;
      return h("button", {type: "button", class: ["tm-fr", "fl", e.open ? "open" : ""], role: "listitem",
        title: `${e.id} · ${what} · ${e.kind === "exit" ? `${reasonKo(e.reason)} ` : "진입 "}${fmt.kst(e.t)} KST${e.open ? " · 지금 열려 있음" : ""} · 누르면 차트에서 보기`,
        onclick: () => onPick({account: e.id, coin: e.coin, at: e.at})},
      ageCell(e.t), tagOf(e), h("span", {class: "tm-fn"}, acctLabel(e.a, {role: true})),
      h("span", {class: "tm-fc"}, coinShort(e.coin), " ", h("span", {class: e.side > 0 ? "up" : "down"}, sideKo(e.side))), right);
    }
    const detail = m.kind === "entry" ? `롱 ${fmt.int(m.L)} · 숏 ${fmt.int(m.S)}` : `이김 ${fmt.int(m.win)} · 짐 ${fmt.int(m.n - m.win)}`;
    return h("div", {class: ["tm-fr", "fl", "fold"], role: "listitem", title: `딥시크 ${fmt.int(m.n)}건 · ${detail} · ${[...m.coins].join("·")} (금액 숨김: 건수만)`},
      ageCell(m.t), h("span", {class: ["tm-tag", m.kind === "entry" ? "in" : "n"]}, m.kind === "entry" ? "진입" : "청산"),
      h("span", {class: "tm-fn"}, h("span", null, `딥시크 · ${fmt.int(m.n)}건`)),
      h("span", {class: "tm-fc muted"}, [...m.coins].slice(0, 2).join("·")), h("span", {class: "pp thin tm-fv"}, "개수만"));
  }
  function render() {
    const ms = models();
    const nodes = [];
    const motionOk = !reduced() && visible();
    for (const m of ms) {
      const sig = m.one ? `${m.id}:${m.one.open ? 1 : 0}` : `${m.id}:${m.n}:${m.win}`;
      const was = S.nodes.get(m.id);
      if (was && was.sig === sig) { nodes.push(was.node); continue; }
      const node = rowOf(m);
      S.nodes.set(m.id, {sig, node});
      nodes.push(node);
      if (m.live && motionOk) fadeIn(node);
    }
    const keep = new Set(ms.map((m) => m.id));
    for (const k of [...S.nodes.keys()]) if (!keep.has(k)) S.nodes.delete(k);
    const anyLive = ms.some((m) => m.live);
    for (const e of S.ev) e.live = false;
    if (!nodes.length) put(list, S.failed && !S.loaded ? h("p", {class: "tm-empty"}, "체결 기록을 불러오지 못함 · 30초마다 다시 받습니다")
      : h("p", {class: "tm-empty"}, S.loaded ? "고른 묶음에 아직 체결이 없습니다" : "불러오는 중"));
    else list.replaceChildren(...nodes);
    if (anyLive) ping(el);
    let L = 0, Sh = 0, n = 0;
    for (const e of S.ev) {
      if (e.kind !== "entry" || !inGroup({role: e.a && e.a.role, kind: e.a && e.a.kind}, st.grp)) continue;
      if (e.side > 0) L += 1; else Sh += 1;
      if (++n >= 100) break;
    }
    ratioK.textContent = `최근 진입 ${fmt.int(n)}건`;
    ratio.set({L, S: Sh});
  }
  return {
    el,
    /** the newest /api/fills rows (null when the load failed: the old list stays) */
    onFills(rows) {
      if (rows == null) { S.failed = true; if (!S.loaded) render(); return; }
      const first = !S.loaded;
      S.loaded = true; S.failed = false;
      let any = false;
      for (const f of rows) for (const e of fromFill(f, !first)) if (add(e, !first && e.kind === "exit")) any = true;
      // a closed trade means its position is no longer open: the entry row from the positions stops saying "열림"
      for (const e of S.ev) if (e.open && rows.some((f) => f.account === e.id && f.entry_time === e.at)) e.open = false;
      if (any || first) render();
    },
    /** a new /api/positions answer: positions not seen before are new entries (the first answer is the past) */
    onPositions(d) {
      if (!d || d.status) return;
      const first = S.posSeen == null;
      const now = new Set();
      let any = false;
      for (const p of d.positions || []) {
        const k = `${p.id}:${p.since}`;
        now.add(k);
        if (add(fromPos(p, !first && !S.posSeen.has(k)), !first && !S.posSeen.has(k))) any = true;
      }
      for (const e of S.ev) if (e.open && !now.has(`${e.id}:${e.at}`)) e.open = false;
      S.posSeen = now;
      if (any || first) render();
    },
    repaint: render,
  };
}
