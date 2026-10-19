// 실거래 터미널's own panels (screens/livebots-term.js lays them out in the rule bot's terminal frame, terminal-kit.js panel):
//   bandLine     the status strip under the price row: 바이비트 잔고 · MEXC 잔고 · 오늘 실거래 손익 · 신호등 · 멈춤 · 40번까지
//   fillsPanel   실거래 체결: the entries and exits of 페이퍼 / 바이비트 / MEXC as they happen (진입 · 잠금 · 손절 …)
//   coinMarks    the coin strip's second line: which account holds which side on that coin, a dot for the sign of its P&L
//   minePanel    이 코인 포지션: the three accounts' positions on the coin on screen, ROE at the mark rolling to a new mark
//   tablePanel   the bottom table: 포지션 / 체결 / 손절 주문 of the three accounts (계좌 filter, 롱·숏 bar, 실거래 미실현 합계)
// HONESTY: every number is the server's (dash/more/livebots.py) or the mark of the dashboard's own ticker; an account that
// could not be read says 못 읽음 (never 0 or '포지션 없음'); a row lights only when it really arrived after the first look;
// paper money (모의) and real money (실거래) are never added together; no order buttons.
import {h, put, ui, fmt, store, motion, local} from "../core/pb.js";
import {panel, ratioBar, ping, ageCell} from "./terminal-kit.js";
import {hit} from "./terminal-live.js";
import {failNote} from "./terminal-state.js";
import {unrealized, roeAt, lightWords, coinCounts, liveToday, distTo} from "./livebots-calc.js";
import {ACCT, acctKo, acctTag, posTip, EXIT_SHORT} from "./livebots-kit.js";

const live = () => motion.visible() && !motion.reduced();
const IDS = ["paper", "bybit", "mexc"];

// ---------------------------------------------------------------- the status strip
/** bandLine(ctx) -> {el, set(d, state)}: one slim line of chips, each a link to the tab that explains it. */
export function bandLine(ctx) {
  const chip = (key, tab, label) => h("a", {class: ["term-bc2", "lb-bc", "c-" + key], href: ctx.href("livebots", tab), "data-k": key, title: label});
  const c = {bybit: chip("bybit", "safety", "바이비트 잔고"), mexc: chip("mexc", "safety", "MEXC 잔고"), today: chip("today", "trades", "오늘 실거래 손익"),
    light: chip("light", "safety", "신호등"), halt: chip("halt", "safety", "멈춤"), goal: chip("goal", "perf", "40번 판단까지")};
  const el = h("div", {class: "term-band lb-band", role: "group", "aria-label": "실거래 한 줄 요약"},
    h("span", {class: "term-bl"}, "실거래"), c.bybit, c.mexc, c.today, c.light, c.halt, c.goal);
  const dash = () => h("b", {class: "num"}, "—");
  function set(d, state) {
    const accts = (d && d.accts) || [];
    const by = Object.fromEntries(accts.map((a) => [a.id, a]));
    for (const id of ["bybit", "mexc"]) {
      const a = by[id], el2 = c[id];
      if (!a) { put(el2, h("span", null, `${acctKo(id)} `), dash()); el2.title = `${acctKo(id)} 잔고: ${state === "failed" ? "불러오지 못함" : "불러오는 중"}`; continue; }
      if (a.state !== "ok") {
        put(el2, h("span", null, `${acctKo(id)} `), a.state === "error" ? h("b", {class: "down"}, "못 읽음") : h("b", {class: "muted"}, "수집 전"));
        el2.title = `${acctKo(id)}: ${a.reason_ko || ""}`;
        continue;
      }
      const v = h("b", {class: "num"}, a.balance == null ? "—" : `$${fmt.money(a.balance)}`);
      put(el2, h("i", {class: ["term-bdot", a.stale ? "" : "live"], "aria-hidden": "true"}), h("span", null, ` ${acctKo(id)} `), v,
        a.stale ? h("span", {class: "muted"}, " · 기록 멈춤") : null);
      el2.title = `${acctKo(id)} 잔고 (거래소, 열린 포지션 평가 포함) · 마지막 기록 ${fmt.kst(a.as_of_ms)}${a.stale ? " · 기록이 멈췄어요" : " · 실시간"}`;
    }
    const t = liveToday(accts);
    if (!t) { put(c.today, h("span", null, "오늘 실거래 "), dash()); c.today.title = "오늘 실거래 손익: 실행기 기록을 아직 못 읽음"; }
    else {
      put(c.today, h("span", null, "오늘 실거래 "), h("b", {class: ["num", fmt.tone(t.pnl, fmt.money(t.pnl, true))]}, `${fmt.money(t.pnl, true)}`),
        h("span", {class: "muted num"}, ` · ${fmt.int(t.trades)}번 ${fmt.int(t.wins)}승 ${fmt.int(t.losses)}패`));
      c.today.title = `오늘(한국 시간 0시부터) 닫힌 실거래 손익 · ${t.parts.map((p) => `${acctKo(p.id)} ${fmt.money(p.pnl, true)} USDT`).join(" · ")} · 페이퍼(모의)는 빼고`;
    }
    const execs = (d && d.execs) || [];
    if (!execs.length) { put(c.light, h("span", null, "신호등 "), dash()); put(c.halt, h("span", null, "멈춤 "), dash()); }
    else {
      put(c.light, h("span", null, "신호등 "), execs.map((x, i) => {
        const w = lightWords(x.light);
        return h("span", {class: ["lb-bl", w.tone]}, i ? " · " : "", h("i", {class: ["lb-dot", "sm", w.tone], "aria-hidden": "true"}), ` ${ACCT[x.id].s} `, h("b", null, w.short));
      }));
      c.light.title = execs.map((x) => `${x.name_ko}: ${lightWords(x.light).line}`).join(" / ");
      const halted = execs.filter((x) => x.record && x.record.state === "ok" && x.record.halted);
      const unknown = execs.filter((x) => !x.record || x.record.state !== "ok");
      c.halt.classList.toggle("bad", halted.length > 0);
      put(c.halt, h("span", null, "멈춤 "), halted.length ? h("b", {class: "down"}, halted.map((x) => x.name_ko).join(" · ")) : unknown.length === execs.length ? dash()
        : h("b", {class: "up"}, "없음"), unknown.length && unknown.length < execs.length ? h("span", {class: "muted"}, ` · ${unknown.map((x) => x.name_ko).join(" · ")} 모름`) : null);
      c.halt.title = execs.map((x) => `${x.name_ko}: ${!x.record || x.record.state !== "ok" ? "기록을 못 읽어 모름" : x.record.halted ? `멈춤 (${x.record.halt_reason || "이유 기록 없음"})` : "멈춤 아님"}`).join(" / ");
    }
    const cp = d && d.checkpoint;
    if (!cp) { put(c.goal, h("span", null, "40번 판단까지 "), dash()); c.goal.title = "페이퍼 거래 기록을 아직 못 읽음"; }
    else {
      put(c.goal, h("span", null, `${fmt.int(cp.trades)}번 판단까지 `), cp.ready ? h("b", null, "도착") : h("b", {class: "num"}, `${fmt.int(cp.left)}번 남음`),
        h("span", {class: "muted num"}, ` · 페이퍼(연습) ${fmt.int(cp.n)}/${fmt.int(cp.trades)}`));
      c.goal.title = `페이퍼 닫힌 거래 ${fmt.int(cp.n)}번 · ${fmt.int(cp.trades)}번이 되면 두 분이 정해요: ${cp.rule_ko || `${cp.up_ko} / ${cp.mid_ko} / ${cp.low_ko}`} · 그 전의 승률은 판단이 아니에요 (참고)`;
    }
  }
  set(null, "loading");
  /** A light that really turned red or an executor that really halted since the last answer: its chip lights once. */
  const alarm = (list) => { for (const a of list || []) motion.flash(a.what === "red" ? c.light : c.halt, "down"); };
  return {el, set, alarm};
}

// ---------------------------------------------------------------- 실거래 체결
const MAX_FILLS = 24;
/** fillsPanel(ctx) -> {el, set(d, state)}: the server's fills (newest first); rows that arrived after the first look slide in once. */
export function fillsPanel(ctx) {
  const list = h("div", {class: "term-feed term-fl", role: "list", "aria-live": "off"});
  const ratio = ratioBar([{key: "W", label: "이김", tone: "up"}, {key: "L", label: "짐", tone: "down"}], {label: "최근 닫힌 실거래 이김·짐"});
  const ratioK = h("span", {class: "term-rbk"}, "최근 청산");
  const el = panel("실거래 체결", {cls: "term-fills lb-fills", sub: "페이퍼(연습) · 바이비트 · MEXC", scroll: true,
    info: `세 계좌의 진입과 청산 (잠금 = 잠금선에서 이익으로 닫힘, 손절 = 손절선에서 닫힘) · 실거래 손익: ${ui.ASSUME_LIVE_KO} · 페이퍼 손익: ${ui.ASSUME_KO}`}, list);
  el.append(h("div", {class: "term-pf"}, h("div", {class: "term-rbrow"}, ratioK, ratio)));
  const nodes = new Map();
  let seen = null;
  const tagOf = (f) => (f.kind === "entry" ? h("span", {class: "term-tag in"}, "진입")
    : h("span", {class: ["term-tag", f.reason === "LIQ" ? "liq" : f.pnl > 0 ? "up" : f.pnl < 0 ? "down" : ""], title: f.reason_ko || ""}, EXIT_SHORT[f.reason] || "청산"));
  function rowOf(f) {
    const right = f.kind === "exit" ? h("b", {class: ["num", "term-fv", fmt.tone(f.pnl)], title: f.est ? "체결 기록을 아직 못 읽어 지갑 변화로 잡은 어림" : null},
      f.pnl == null ? "—" : `${fmt.money(f.pnl, true)}${f.est ? "≈" : ""}`) : h("span", {class: "num term-fv muted"}, fmt.price(f.price));
    const what = `${acctKo(f.acct)} · ${fmt.coin(f.symbol)} ${fmt.sideKo(f.side)} ${fmt.lev(f.lev)}${f.kind === "exit" ? ` · ${f.reason_ko || ""}${f.roe != null ? ` · ROE ${fmt.pct(f.roe, 1)}` : ""}` : f.open ? " · 지금 열림" : ""}`;
    return h("a", {class: ["term-fr", "fl", "lb-fr", "lb-a-" + f.acct], role: "listitem", href: ctx.href("livebots", "trades", {acct: f.acct}), title: `${what} · ${fmt.kst(f.t)}`},
      ageCell(f.t), tagOf(f), h("span", {class: "term-fn"}, acctTag(f.acct)),
      h("span", {class: "term-fc"}, fmt.coin(f.symbol), " ", h("span", {class: f.side > 0 ? "up" : "down"}, fmt.sideKo(f.side))), right);
  }
  function set(d, state) {
    const fills = d ? d.fills || [] : null;
    if (!fills) { put(list, state === "failed" ? failNote("실거래 체결 기록", {retrying: true}) : motion.shimmer(3)); return; }
    const show = fills.slice(0, MAX_FILLS);
    const fresh = seen ? show.filter((f) => !seen.has(f.key)) : [];
    seen = new Set(fills.map((f) => f.key));
    if (!show.length) {
      const unread = (d.accts || []).filter((a) => a.state !== "ok").map((a) => acctKo(a.id));
      put(list, ui.empty(unread.length ? `아직 체결이 없어요 (${unread.join(" · ")} 기록은 못 읽음)` : "아직 체결이 없어요"));
    } else {
      list.replaceChildren(...show.map((f) => {
        let n = nodes.get(f.key);
        if (!n) { n = rowOf(f); nodes.set(f.key, n); }
        return n;
      }));
      for (const k of [...nodes.keys()]) if (!show.some((f) => f.key === k)) nodes.delete(k);
      if (fresh.length && live()) {
        for (const f of fresh) motion.fillIn(nodes.get(f.key), f.kind === "exit" ? (f.pnl > 0 ? "up" : "down") : null);
        ping(el);
      }
    }
    let W = 0, L = 0, n = 0;
    for (const f of fills) { if (f.kind !== "exit" || f.acct === "paper" || f.pnl == null) continue; if (f.pnl > 0) W++; else L++; if (++n >= 20) break; }
    ratioK.textContent = `실거래 최근 ${fmt.int(n)}번`;
    ratio.set({W, L});
  }
  set(null, "loading");
  return {el, set};
}

// ---------------------------------------------------------------- the coin strip's second line
/** coinMarks() -> the painter watchList takes (o.marks): paint(rows, d, failed) with d = the livebots answer. */
export function coinMarks() {
  let prev = null;
  return {
    paint(rows, d, failed) {
      const accts = d ? d.accts || [] : null;
      const readable = accts ? accts.some((a) => a.state === "ok") : false;
      const cnt = accts && readable ? coinCounts(accts, (s) => store.mark(s)) : null;
      for (const [sym, r] of rows) {
        if (!r.pos) continue;
        if (!cnt) {
          put(r.pos, "—"); r.pos.className = "term-wpos muted";
          r.pos.title = `${fmt.coin(sym)}: 실거래 포지션 ${accts && !readable ? "수집 전 (세 계좌 기록을 아직 못 읽음)" : failed ? "불러오지 못함" : "불러오는 중"}`;
          continue;
        }
        const xs = cnt[sym] || [];
        if (!xs.length) {
          put(r.pos, sym === "XRPUSDT" ? "안 함" : "포지션 없음"); r.pos.className = "term-wpos muted";
          r.pos.title = sym === "XRPUSDT" ? "XRP: 실거래 봇이 거래하지 않는 코인" : `${fmt.coin(sym)}: 세 계좌 모두 포지션 없음`;
        } else {
          put(r.pos, xs.map((x, i) => h("span", {class: x.side > 0 ? "up" : "down"}, i ? " " : "", `${ACCT[x.id].s}${fmt.sideKo(x.side)}`)),
            xs.some((x) => x.id !== "paper") ? h("i", {class: ["term-wdot", (() => { const u = xs.filter((x) => x.id !== "paper"); const k = u.every((x) => x.u != null);
              const s = u.reduce((a, x) => a + (x.u || 0), 0); return !k ? "flat" : Math.abs(s) < 0.005 ? "flat" : s > 0 ? "up" : "down"; })()], "aria-hidden": "true"}) : null);
          r.pos.className = "term-wpos num";
          r.pos.title = xs.map((x) => `${acctKo(x.id)} ${fmt.sideKo(x.side)}${x.u != null ? ` (미실현 ${fmt.money(x.u, true)} USDT)` : ""}`).join(" · ")
            + " · 점 = 실거래 미실현 합계의 부호 (마크 가격, 수수료 전)";
        }
        const keys = new Set(xs.map((x) => x.id));
        if (prev && [...keys].some((k) => !(prev[sym] || new Set()).has(k))) hit(r.b, "own");      // a position really opened on this coin
      }
      if (cnt) prev = Object.fromEntries(Object.entries(cnt).map(([s, xs]) => [s, new Set(xs.map((x) => x.id))]));
    },
  };
}

// ---------------------------------------------------------------- 이 코인 포지션
/** minePanel(ctx, st) -> {el, set(d, state), setSym(), onTicker()} */
export function minePanel(ctx, st) {
  const list = h("div", {class: "term-cp", role: "list"});
  const other = h("p", {class: "term-cpo muted", hidden: true});
  const el = panel("이 코인 포지션", {cls: "term-mine lb-mine", scroll: true,
    info: `페이퍼(연습) · 바이비트 · MEXC의 이 코인 포지션 · ROE = 마크 가격 기준 미실현 ÷ 증거금 (나갈 때 수수료 전) · 줄에 마우스를 올리면 진입가 · 손절·잠금 · 다음 잠금 · 청산가 · 주문 버튼 없음`},
    list, other);
  const rows = new Map();
  let data = null, state = "loading";
  function render() {
    const accts = data ? data.accts || [] : null;
    if (!accts) { put(list, state === "failed" ? failNote("세 계좌의 포지션", {retrying: true}) : ui.empty("불러오는 중")); other.hidden = true; return; }
    const mk = store.mark(st.sym);
    const xs = accts.filter((a) => a.state === "ok" && a.position && a.position.symbol === st.sym);
    const unread = accts.filter((a) => a.state !== "ok");
    el.sub.textContent = `${fmt.coin(st.sym)} · ${fmt.int(xs.length)}개`;
    const elsewhere = accts.filter((a) => a.state === "ok" && a.position && a.position.symbol !== st.sym);
    other.hidden = !(elsewhere.length || unread.length);
    other.textContent = [elsewhere.length ? `다른 코인: ${elsewhere.map((a) => `${acctKo(a.id)} ${fmt.coin(a.position.symbol)} ${fmt.sideKo(a.position.side)}`).join(" · ")}` : null,
      unread.length ? `${unread.map((a) => acctKo(a.id)).join(" · ")}: 기록을 못 읽어 모름` : null].filter(Boolean).join(" / ");
    const nodes = xs.map((a) => {
      const p = a.position, key = `${a.id}|${p.key}`;
      let r = rows.get(a.id);
      if (!r || r.key !== key) {
        const roe = h("b", {class: "num term-roe"}, "—");
        const node = h("div", {class: ["term-cr", "lb-cr"], role: "listitem"},
          ui.sideTag(p.side), h("span", {class: "term-fn term-cfn"}, acctTag(a.id), p.status === "entering" ? ui.pill("확인 중", "warn") : null),
          h("span", {class: "muted num"}, fmt.lev(p.leverage)), roe);
        if (r && live()) motion.fillIn(node, null);                     // a position that replaced another one: lit once
        r = {key, node, roe};
        rows.set(a.id, r);
      }
      r.node.title = posTip(a, mk);
      motion.countTo(r.roe, roeAt(p, mk), {format: "pct", dec: 1, tone: true, glow: true});
      return r.node;
    });
    for (const k of [...rows.keys()]) if (!xs.some((a) => a.id === k)) rows.delete(k);
    if (!nodes.length) put(list, accts.some((a) => a.state === "ok") ? ui.empty(`${fmt.coin(st.sym)}에 열린 포지션이 없어요`)
      : h("p", {class: "empty"}, ui.notYet("수집 전"), " 세 계좌의 기록을 아직 못 읽었어요"));
    else list.replaceChildren(h("div", {class: "term-cr hd", "aria-hidden": "true"}, h("span", null, "방향"), h("span", null, "계좌"), h("span", null, "배수"),
      h("span", null, "ROE")), ...nodes);
  }
  return {el, set(d, s) { data = d || data; state = s; render(); }, setSym() { rows.clear(); render(); }, onTicker: render};
}

// ---------------------------------------------------------------- the bottom table
const TAB_NOTE = {
  pos: `세 계좌의 열린 포지션 · 미실현 = 마크 가격 기준 (나갈 때 수수료 전) · 실거래 미실현 합계는 바이비트 + MEXC만 (페이퍼는 모의라 더하지 않음)`,
  fills: "세 계좌의 닫힌 거래 · 실거래 손익은 거래소 체결 기록 기준 (≈ = 체결을 아직 못 읽어 지갑 변화로 어림) · 페이퍼는 모의",
  stops: "손절·잠금 가격 · 실행기는 거래소에 실제로 걸어 둔 손절 주문 (실행기가 확인한 가격), 페이퍼는 모의라 주문 없음 · 지금 가격에서 가까운 순",
};
/** tablePanel(ctx, st, onPick) -> {el, set(d, state), setSym(), onTicker()} */
export function tablePanel(ctx, st, onPick) {
  const t = {tab: local.get("lb-tab", "pos"), acct: local.get("lb-tacct", ""), d: null, state: "loading"};
  if (!["pos", "fills", "stops"].includes(t.tab)) t.tab = "pos";
  if (t.acct && !IDS.includes(t.acct)) t.acct = "";
  const tabs = ui.seg([{id: "pos", label: "포지션"}, {id: "fills", label: "체결"}, {id: "stops", label: "손절 주문"}], t.tab,
    (id) => { t.tab = id; local.set("lb-tab", id); render(true); }, {label: "아래 표"});
  const posBtn = tabs.querySelector('[data-id="pos"]');
  const sel = h("select", {class: "select term-sel", "aria-label": "계좌 고르기", title: "ALL = 페이퍼(연습) · 바이비트 · MEXC"},
    h("option", {value: ""}, "ALL"), IDS.map((id) => h("option", {value: id}, acctKo(id))));
  sel.value = t.acct;
  sel.addEventListener("change", () => { t.acct = sel.value; local.set("lb-tacct", t.acct); render(true); });
  const total = h("b", {class: "num term-utot"}, "—");
  const ratio = ratioBar([{key: "L", label: "롱", tone: "up"}, {key: "S", label: "숏", tone: "down"}], {label: "열린 포지션 롱·숏 비율", cls: "wide inline"});
  const tbl = h("div", {class: "term-tw lb-tw"});
  const foot = h("div", {class: "term-pf row"});
  const el = panel("세 계좌", {cls: "term-table lb-table", lead: [tabs], info: TAB_NOTE.pos,
    acts: [sel, ratio, h("span", {class: "term-ut"}, "실거래 미실현 ", total, " USDT")]}, tbl, foot);
  tabs.after(el.tip);
  const cells = new Map();
  const accts = () => (t.d ? (t.d.accts || []).filter((a) => !t.acct || a.id === t.acct) : []);
  const coinCell = (sym) => h("td", null, h("button", {type: "button", class: ["term-coin", sym === st.sym ? "on" : ""], onclick: () => onPick(sym), title: "이 코인 보기"}, fmt.coin(sym)));
  const nameCell = (id) => h("td", {class: "nm"}, h("a", {href: ctx.href("livebots", "trades", {acct: id}), title: ACCT[id] ? ACCT[id].tip : id}, acctTag(id)));
  const table = (cols, rows) => h("table", {class: "term-t lb-t"}, h("thead", null, h("tr", null, cols.map((c) => h("th", {class: c[1] || ""}, c[0])))), h("tbody", null, rows));
  const unreadNote = () => {
    const bad = (t.d ? t.d.accts || [] : []).filter((a) => a.state !== "ok" && (!t.acct || a.id === t.acct));
    return bad.length ? h("span", {class: "down"}, `${bad.map((a) => `${acctKo(a.id)} ${a.state === "error" ? "못 읽음" : "수집 전"}`).join(" · ")} · `) : null;
  };
  /** "none" only when an account in the filter was really read; otherwise 수집 전 / 못 읽음 (never '없음') */
  const noneOr = (words) => (accts().some((a) => a.state === "ok") ? ui.empty(words)
    : h("p", {class: "empty"}, ui.notYet("수집 전"), " 이 계좌들의 기록을 아직 못 읽었어요"));
  function posTable() {
    const xs = accts().filter((a) => a.state === "ok" && a.position);
    const rows = xs.map((a) => {
      const p = a.position, m = store.mark(p.symbol), u = unrealized(p, m);
      let c = cells.get(a.id);
      if (!c) { c = {pnl: h("b", {class: "num"}), roe: h("span", {class: "num"})}; cells.set(a.id, c); }
      motion.countTo(c.pnl, u, {dec: 2, sign: true, tone: true, glow: true});
      motion.countTo(c.roe, roeAt(p, m), {format: "pct", dec: 1, tone: true});
      return h("tr", {class: p.symbol === st.sym ? "on" : "", title: posTip(a, m)}, nameCell(a.id), coinCell(p.symbol), h("td", null, ui.sideTag(p.side)),
        h("td", {class: "r num xn"}, fmt.lev(p.leverage)), h("td", {class: "r num xe"}, fmt.price(p.entry)), h("td", {class: "r num muted xm"}, fmt.price(m)),
        h("td", {class: "r"}, c.pnl), h("td", {class: "r"}, c.roe),
        h("td", {class: "r num warn-t"}, p.liq ? fmt.price(p.liq) : h("span", {class: "muted", title: "실행기 기록에 청산가가 없어요 (거래소 앱에서 확인)"}, "—")),
        h("td", {class: ["r", "num", p.locked ? "up" : ""]}, p.locked ? `잠금 ${fmt.price(p.stop)}` : fmt.price(p.stop)),
        h("td", {class: "r num muted xs"}, p.entry_time ? fmt.kst(p.entry_time) : "—"));
    });
    put(foot, h("span", {class: "muted"}, unreadNote(), "ROE = 마크 가격 기준 미실현 ÷ 증거금 · 페이퍼의 순ROE(잠금 계산)는 줄에 마우스를 올리면"));
    return rows.length ? table([["계좌"], ["코인"], ["방향"], ["배수", "r xn"], ["진입가", "r xe"], ["마크", "r xm"], ["미실현 (USDT)", "r"], ["ROE", "r"], ["청산가", "r"],
      ["손절·잠금", "r"], ["진입 시각", "r xs"]], rows) : noneOr("열린 포지션이 없어요");
  }
  function fillsTable() {
    const fills = ((t.d && t.d.fills) || []).filter((f) => f.kind === "exit" && (!t.acct || f.acct === t.acct)).slice(0, 20);
    const rows = fills.map((f) => h("tr", null, h("td", {class: "num muted"}, fmt.kst(f.t)), nameCell(f.acct), coinCell(f.symbol), h("td", null, ui.sideTag(f.side)),
      h("td", {class: "r num"}, fmt.lev(f.lev)), h("td", {class: [f.reason === "SL" || f.reason === "LIQ" ? "down" : f.reason === "LOCK" ? "up" : ""]}, f.reason_ko || "—"),
      h("td", {class: ["r", "num", fmt.tone(f.roe)]}, f.roe == null ? "—" : fmt.pct(f.roe, 1)),
      h("td", {class: ["r", "num", fmt.tone(f.pnl)], title: f.est ? "체결을 아직 못 읽어 지갑 변화로 잡은 어림" : null}, f.pnl == null ? "—" : `${fmt.money(f.pnl, true)}${f.est ? "≈" : ""}`)));
    put(foot, h("span", {class: "muted"}, unreadNote(), `최근 ${fmt.int(rows.length)}건 · `, h("a", {href: ctx.href("livebots", "trades")}, "거래 전체 →")));
    return rows.length ? table([["청산"], ["계좌"], ["코인"], ["방향"], ["배수", "r"], ["이유"], ["ROE", "r"], ["손익 (USDT)", "r"]], rows) : noneOr("닫힌 거래가 아직 없어요");
  }
  function stopsTable() {
    const xs = accts().filter((a) => a.state === "ok" && a.position && a.position.stop).map((a) => {
      const m = store.mark(a.position.symbol);
      return {a, p: a.position, m, d: distTo(m, a.position.stop)};
    }).sort((x, y) => (x.d ?? 9) - (y.d ?? 9));
    const rows = xs.map((x) => h("tr", null, nameCell(x.a.id), coinCell(x.p.symbol), h("td", null, ui.sideTag(x.p.side)),
      h("td", null, x.p.locked ? h("span", {class: "up"}, x.p.lock_roe != null ? `잠금 +${fmt.num(x.p.lock_roe * 100, 0)}%` : "잠금") : "손절"),
      h("td", {class: "r num"}, fmt.price(x.p.stop)), h("td", {class: "r num muted"}, fmt.price(x.m)),
      h("td", {class: ["r", "num", x.d != null && x.d < 0.005 ? "down" : ""]}, x.d == null ? "—" : fmt.pct(x.d, 2, false)),
      h("td", {class: "muted"}, x.a.kind === "live" ? (x.p.stop_order ? `거래소에 걸림 · #${String(x.p.stop_order).slice(-8)}` : "거래소 손절 (번호 기록 없음)") : "모의 (주문 없음)")));
    put(foot, h("span", {class: "muted"}, unreadNote(), "실행기는 거래소에 손절을 걸고 확인한 가격을 기록해요 · 페이퍼는 모의라 주문 없음"));
    return rows.length ? table([["계좌"], ["코인"], ["방향"], ["종류"], ["가격", "r"], ["지금", "r"], ["거리", "r"], ["주문"]], rows) : noneOr("걸린 손절이 없어요");
  }
  function render(user) {
    el.tip.set(TAB_NOTE[t.tab] || TAB_NOTE.pos);
    if (!t.d) {
      tbl.replaceChildren(t.state === "failed" ? failNote("세 계좌 기록", {retrying: true}) : motion.shimmer(3));
      return;
    }
    let L = 0, S = 0, tot = 0, known = 0, nLive = 0;
    const liveRead = accts().some((a) => a.kind === "live" && a.state === "ok");
    for (const a of accts()) {
      if (a.state !== "ok" || !a.position) continue;
      if (Number(a.position.side) > 0) L++; else S++;
      if (a.kind !== "live") continue;
      nLive++;
      const u = unrealized(a.position, store.mark(a.position.symbol));
      if (u != null) { tot += u; known++; }
    }
    ratio.set({L, S}, (n, sh) => `${fmt.int(n)}`);
    if (posBtn) posBtn.textContent = `포지션 ${fmt.int(L + S)}`;
    motion.countTo(total, !liveRead ? null : nLive && known === nLive ? tot : nLive ? null : 0, {dec: 2, sign: true, tone: true, glow: true});
    const body = t.tab === "fills" ? fillsTable() : t.tab === "stops" ? stopsTable() : posTable();
    tbl.replaceChildren(body);
    if (user) motion.swap(tbl);
  }
  return {el, set(d, s) { if (d) t.d = d; t.state = s; render(false); }, setSym() { render(false); }, onTicker() { if (t.tab !== "fills") render(false); }};
}

