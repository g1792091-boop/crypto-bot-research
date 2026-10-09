// #/accounts 순위표 (round 5, the rule bot's v4 순위표 for the demo lab; the settings ranking is #/rank 설정 순위):
//   head     "묶음을 고르면 아래가 모두 그 묶음으로 바뀝니다" · 순위표 CSV (made here from accounts.json) · 전체 거래 CSV
//            (the newest 300 trades of trades.json made here, or one account's whole CSV from /api/export/<id>.csv)
//   배수     20 / 30 / 40 / 50 (every account has the four lines; default 20)
//   ◆ 묶음 ◆ a card per kind: 고정 · 자동 교체 · 친구 규칙 · 비공개 매매법 (when there) · 동전 던지기 (비교 기준, 판정 안 함):
//            the median P&L % of its lines at that leverage, "동전 던지기 중앙값보다 위 a/n" (each line against the median
//            of the coin-flip lines of the same timeframe and leverage; 참고), 파산 · 포지션; "전체 N개 보기" = all kinds
//   ◆ 상위 · 하위 ◆ four stat cards, then the best and the worst five: rank (▲▼ = rank change against the P&L % one
//            day ago, accounts.json pnl_pct_24h), the account's pixel character, the timeframe chip, the name, its small
//            equity line (spark), the P&L %, "거래 · 승패 · 잔고 · 낙폭", the best open position at that leverage
//            (positions.json), 표본 적음 (under 30 trades), 동전 ▲ / ▼ (참고)
//   전체 목록 the same lines in the v4 dense table, sortable, with the confirmation badge and the stop-rule column
// accounts.json + positions.json + judge.json every 60 s (drawn again only when one of them changed). Read-only; a
// missing file shows "준비 중". HONESTY: a coin-flip comparison is 참고 in neutral colours, never a pass or a fail.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {starBtn, isFav} from "../favs.js";
import {LEVS, KINDS, KIND_KO, SUB_KO, kindOfId, tfKo, sideKo, reasonKo, CONFIRM_KO} from "../labels.js";

const ORDER = ["fixed", "adaptive", "friend", "private", "flip"];       // the reference card last
const SMALL = 30;
const SEED = 1000;
const kindOf = (a) => {
  const k = a.kind || kindOfId(a.id);
  return KINDS.some((x) => x.id === k) ? k : "__other";
};
const kindKo = (k) => (k === "__other" ? "기타" : KIND_KO[k] || k);
const finite = (v) => v != null && Number.isFinite(Number(v));
/** A position's return on its margin, signed: 0.0123 -> "+1.2%" (positions.json roe is a ratio). */
const roeText = (v) => (finite(v) ? `${Number(v) > 0 && /[1-9]/.test(fmt.ratio(v)) ? "+" : ""}${fmt.ratio(v)}` : "—");

export async function mount(el, ctx) {
  ctx.setTitle("순위표");
  const st = {
    L: LEVS.includes(Number(local.get("board-lev", 20))) ? Number(local.get("board-lev", 20)) : 20,
    sel: String(local.get("board-group", "fixed")),
    accts: null, pos: null, judge: null, trades: null, exports: null, seen: null,
  };
  const D = {prevPnl: new Map(), prevDelta: new Map(), painted: false};

  // ---------------------------------------------------------------- head: CSV buttons
  const csvBtn = h("button", {type: "button", class: "btn-line", title: "모든 계좌 × 배수 4줄의 지금 순위 (엑셀로 열림, 이 화면이 가진 자료로 만듦)",
    onclick: () => boardCsv()}, "순위표 CSV");
  const tradesBox = h("div", {class: "k4-menupop", role: "group", "aria-label": "전체 거래 CSV"});
  const tradesMenu = h("details", {class: "k4-menu"}, h("summary", {class: "btn-line"}, "전체 거래 CSV ", h("span", {"aria-hidden": "true"}, "▾")), tradesBox);
  tradesMenu.addEventListener("toggle", () => { if (tradesMenu.open) paintTradesMenu(); });
  const closeMenu = (e) => { if (tradesMenu.open && !tradesMenu.contains(e.target)) tradesMenu.open = false; };
  document.addEventListener("mousedown", closeMenu);
  el.append(ui.screenHead("순위표", "묶음을 고르면 아래가 모두 그 묶음으로 바뀝니다", [csvBtn, tradesMenu]));

  // ---------------------------------------------------------------- 배수 + 묶음
  const levSeg = ui.seg(LEVS.map((L) => ({id: String(L), label: `${L}배`})), String(st.L), (v) => {
    st.L = Number(v); local.set("board-lev", st.L); paint(true);
  }, {label: "배수"});
  const allBtn = h("button", {type: "button", class: "btn-line k4-allbtn", "aria-pressed": "false", onclick: () => pick("all")}, "전체 보기");
  const cards = K4.groupCards({onPick: (id) => pick(id)});
  const groupsSec = h("section", {class: "k4-sec", "aria-label": "묶음"},
    K4.secRow("묶음", "동전 던지기와 견준 숫자는 모두 참고입니다 (판정 아님)", allBtn), cards);

  // ---------------------------------------------------------------- 상위 · 하위
  const cnt = ["n", "open", "above", "ruined"].map(() => K4.liveNum(null, {format: (v) => fmt.int(v), flash: "accent"}));
  const cntSub = h("span", {class: "s"});
  const stats = h("div", {class: "stats s4 bd-stats"},
    K4.stat("계좌", cnt[0], cntSub), K4.stat("포지션 중", cnt[1], "지금 열린 포지션이 있는 줄"),
    K4.stat("시작보다 많은 계좌", cnt[2], "잔고 $1,000 넘음"), K4.stat("파산", cnt[3], "잔고가 $100 아래로 간 적 있는 줄"));
  const tb = h("div", {class: "k4-tb"});
  const tbFoot = h("div");
  const tbCard = ui.card({plate: "상위 · 하위", cls: "bd-tbcard"}, stats, tb, tbFoot);

  // ---------------------------------------------------------------- 전체 목록 (the dense table)
  const table = K4.boardTable({
    cols: tableCols(ctx, () => st), page: 25, sort: {id: "pnl", dir: -1},
    search: {placeholder: "이름·코드 찾기", match: (r, q) => String(r.a.name || "").toLowerCase().includes(q) || r.id.toLowerCase().includes(q)},
    onRow: (r) => { location.hash = ctx.href("account", r.id); },
    rowCls: (r) => [r.kind === "flip" ? "k4-flip" : "", r.x && r.x.ruined ? "k4-ruined" : ""].filter(Boolean).join(" "),
    empty: "계좌가 없습니다",
  });
  const listCount = h("span", {class: "muted bd-count"});
  const listCard = ui.card({plate: "전체 목록", cls: "bd-list", acts: [listCount]}, table.el,
    ui.note("손익 % = 시작 $1,000 대비 (지갑 + 열린 포지션 평가금, 수수료·슬리피지·펀딩 포함). 확인 기간 = 기준을 넘은 뒤 4주 다시 보는 중 · 넘음(실전 후보) · 못 넘음. "
      + "정지 규칙 적용 시 = 같은 진입에 계좌 −20% · 하루 −5% · 5연패 멈춤을 걸었다면의 손익. 주문은 넣지 않습니다."));

  const body = h("div", {class: "stack bd-body"}, tbCard, listCard);
  el.append(h("div", {class: "row wrap bd-levbar"}, h("span", {class: "k4-k"}, "배수"), levSeg,
    h("span", {class: "muted bd-levnote"}, "계좌마다 4줄 (각 $1,000에서 시작) 가운데 고른 배수의 줄")), groupsSec, body);

  // ================================================================ data
  async function load() {
    const get = (p) => ctx.api(p).catch((e) => (e && e.name === "AbortError" ? Promise.reject(e) : e));
    let a, p, j;
    try { [a, p, j] = await Promise.all([get("/api/accounts"), get("/api/positions"), get("/api/judge")]); } catch (e) { return; }
    if (!ctx.alive()) return;
    if (a instanceof Error) {
      if (!st.accts) put(body, ui.errorBox(a, () => { put(body, tbCard, listCard); load(); }));
      return;
    }
    const key = [a, p, j].map((x) => (x && !(x instanceof Error) ? x.generated_ms : "e")).join("|");
    if (key === st.seen) return;
    st.seen = key;
    st.accts = a;
    st.pos = p instanceof Error ? null : p;
    st.judge = j instanceof Error ? null : j;
    paint(false);
  }

  // ================================================================ derived rows
  const linesAt = (L) => {
    const accts = st.accts && !isMissing(st.accts) ? st.accts.accounts || [] : [];
    const posBy = new Map();
    for (const p of (st.pos && !isMissing(st.pos) ? st.pos.positions || [] : [])) {
      if (Number(p.L) !== L) continue;
      const k = String(p.id);
      if (!posBy.has(k)) posBy.set(k, []);
      posBy.get(k).push(p);
    }
    const conf = new Map();
    for (const r of (st.judge && !isMissing(st.judge) ? st.judge.rows || [] : [])) if (Number(r.L) === L) conf.set(String(r.id), r.confirm || null);
    // the coin flips' median per timeframe at this leverage (the reference of every other line)
    const flipMed = {};
    for (const tf of new Set(accts.map((a) => a.tf))) {
      flipMed[tf] = K4.median(accts.filter((a) => kindOf(a) === "flip" && a.tf === tf).map((a) => ((a.lines || {})[String(L)] || {}).pnl_pct));
    }
    return accts.map((a) => {
      const x = (a.lines || {})[String(L)] || null;
      const kind = kindOf(a);
      const ps = (posBy.get(String(a.id)) || []).slice().sort((p, q) => (Number(q.roe) || 0) - (Number(p.roe) || 0));
      const med = flipMed[a.tf];
      const pnl = x && finite(x.pnl_pct) ? Number(x.pnl_pct) : null;
      return {a, x, id: String(a.id), kind, tf: a.tf, pnl, pnl24: x && finite(x.pnl_pct_24h) ? Number(x.pnl_pct_24h) : null,
        vs: kind === "flip" || med == null || pnl == null ? null : pnl - med, pos: ps, conf: conf.get(String(a.id)) || null};
    });
  };
  /** Ranks (now and one day ago) within a set of rows: rank by P&L %, and the change against the 24 h ranking of the
   *  rows that have both numbers (a new line does not push the others). Coin flips are the baseline: no rank in 전체. */
  function ranked(rows) {
    const ranks = K4.ranksOf(Object.fromEntries(rows.map((r) => [r.id, r.pnl])));
    const both = rows.filter((r) => r.pnl != null && r.pnl24 != null);
    const now = K4.ranksOf(Object.fromEntries(both.map((r) => [r.id, r.pnl])));
    const ago = K4.ranksOf(Object.fromEntries(both.map((r) => [r.id, r.pnl24])));
    for (const r of rows) { r.rk = ranks[r.id] ?? null; r.delta = now[r.id] != null && ago[r.id] != null ? ago[r.id] - now[r.id] : null; }
    return rows.slice().sort((p, q) => (p.rk ?? 1e9) - (q.rk ?? 1e9));
  }
  const inSel = (rows) => (st.sel === "all" ? rows.filter((r) => r.kind !== "flip") : rows.filter((r) => r.kind === st.sel));

  // ================================================================ painting
  function pick(id) {
    if (id === st.sel) return;
    st.sel = id;
    local.set("board-group", id);
    paint(true);
  }
  function paint(user) {
    const A = st.accts;
    if (!A) return;
    if (isMissing(A)) {
      put(cards, ui.missing("계좌 목록"));
      put(tb, ui.empty("준비 중")); put(tbFoot); table.set([]); listCount.textContent = "";
      return;
    }
    const rows = linesAt(st.L);
    const kinds = ORDER.filter((k) => rows.some((r) => r.kind === k));
    if (rows.some((r) => r.kind === "__other")) kinds.splice(kinds.length - 1, 0, "__other");
    if (st.sel !== "all" && !kinds.includes(st.sel)) st.sel = kinds[0] || "all";
    // the cards
    const flips = rows.filter((r) => r.kind === "flip");
    cards.update(kinds.map((k) => {
      const rs = rows.filter((r) => r.kind === k);
      const lines = rs.filter((r) => r.x);
      const vsN = rs.filter((r) => r.vs != null).length, above = rs.filter((r) => r.vs != null && r.vs > 0).length;
      const shorts = new Set(rs.map((r) => r.a.short).filter(Boolean)), subs = new Set(rs.map((r) => r.a.sub).filter(Boolean));
      const count = k === "fixed" || k === "friend" ? `${fmt.int(rs.length)}계좌 · 매매법 ${fmt.int(shorts.size)}개`
        : k === "adaptive" ? `${fmt.int(rs.length)}계좌 · 고르는 방식 ${fmt.int(subs.size)}가지`
          : k === "flip" ? `${fmt.int(rs.length)}계좌 · 봉마다 ${fmt.int(Math.round(rs.length / Math.max(1, new Set(rs.map((r) => r.tf)).size)))}개`
            : `${fmt.int(rs.length)}계좌`;
      return {id: k, name: kindKo(k), count, med: K4.median(lines.map((r) => r.pnl)),
        vs: k === "flip" ? "비교 기준 (판정 안 함)" : vsN ? `동전 던지기 중앙값보다 위 ${fmt.int(above)}/${fmt.int(vsN)}` : "동전 던지기 자료 준비 중",
        ref: k !== "flip" && vsN > 0,
        foot: `파산 ${fmt.int(lines.filter((r) => r.x.ruined).length)} · 포지션 ${fmt.int(lines.reduce((s, r) => s + (Number(r.x.open) || 0), 0))}`,
        title: (KINDS.find((x) => x.id === k) || {}).desc || ""};
    }), st.sel);
    const nAll = rows.filter((r) => r.kind !== "flip").length;
    allBtn.textContent = `전체 ${fmt.int(nAll)}개 보기`;
    allBtn.setAttribute("aria-pressed", String(st.sel === "all"));
    allBtn.title = "동전 던지기를 뺀 모든 계좌를 한 목록으로 (동전 던지기는 비교 기준)";

    const sel = ranked(inSel(rows));
    const lines = sel.filter((r) => r.x);
    if (user) for (const c of cnt) delete c.dataset.v;                     // another group or leverage: no tint
    cnt[0].update(sel.length);
    cnt[1].update(lines.filter((r) => Number(r.x.open) > 0).length);
    cnt[2].update(lines.filter((r) => Number(r.x.equity) > SEED).length);
    cnt[3].update(lines.filter((r) => r.x.ruined).length);
    cntSub.textContent = `${st.sel === "all" ? "전체 (동전 던지기 빼고)" : kindKo(st.sel)} · ${st.L}배`;
    paintTopBottom(sel, user);
    // the table: the chosen kind, or every account (the coin flips last, without a rank) for 전체
    const tableRows = st.sel === "all" ? ranked(rows.filter((r) => r.kind !== "flip")).concat(flips.map((r) => ({...r, rk: null, delta: null}))) : sel;
    table.set(tableRows, !user);
    listCount.textContent = `${st.sel === "all" ? "전체" : kindKo(st.sel)} · ${st.L}배 · ${fmt.int(tableRows.length)}줄`;
    for (const r of rows) D.prevPnl.set(`${r.id}|${st.L}`, r.pnl);
    D.painted = true;
    if (user) K4.swap(tb);
  }

  function rowEl(r, user) {
    const x = r.x || {};
    const key = `${r.id}|${st.L}`;
    const prev = D.prevPnl.get(key);
    const ret = h("b", {class: ["num", fmt.tone(r.pnl, fmt.pct(r.pnl, true))]}, fmt.pct(r.pnl, true));
    if (!user && D.painted && prev != null && r.pnl != null && Math.abs(prev - r.pnl) > 1e-9) K4.flashPrice(ret, r.pnl > prev ? "up" : "down");
    const wasDelta = D.prevDelta.get(key);
    D.prevDelta.set(key, r.delta);
    const rkd = r.kind === "flip" && st.sel !== "flip" ? null : K4.rankDelta(r.delta, {title: "하루 전 손익 %로 매긴 순위와 비교 (같은 목록, 같은 배수)",
      fade: !user && D.painted && wasDelta !== r.delta});
    const trades = Number(x.trades) || 0, wins = Number(x.wins) || 0;
    const words = [`거래 ${fmt.int(trades)}`];
    if (trades) words.push(`${fmt.int(wins)}승 ${fmt.int(trades - wins)}패`);
    words.push(`잔고 ${fmt.money(x.equity)}`);
    if (finite(x.max_dd)) words.push(`낙폭 ${fmt.ratio(x.max_dd)}`);
    return h("a", {class: ["k4-row", trades < SMALL ? "dim" : ""], href: ctx.href("account", r.id), role: "listitem",
      title: `${r.a.name || r.id} · ${r.id}`},
    h("span", {class: "rk"}, r.rk == null ? "—" : fmt.int(r.rk), rkd),
    h("span", {class: "lname"}, K4.acctFig(r.a, 22), K4.acctName(r.a), isFav("account", r.id) ? h("span", {class: "bd-star", title: "즐겨찾기"}, "★") : null),
    h("span", {class: "ret"}, h("span", {class: "k4-spark"}, K4.miniSpark(x.spark, {w: 56, h: 18, base: SEED, label: "시작부터 지금까지 잔고 흐름 (30점)"})), ret),
    h("span", {class: "meta"}, h("span", null, words.join(" · ")), posChip(r), K4.smallSample(trades, SMALL), vsTag(r),
      x.ruined ? ui.pill(`파산 ${fmt.int(x.ruins || 1)}번`, "bad", "잔고가 $100 아래로 떨어져 $1,000에서 다시 시작한 적이 있습니다") : null));
  }

  function paintTopBottom(sel, user) {
    const name = st.sel === "all" ? "전체" : kindKo(st.sel);
    const n = sel.length;
    const col = (label, rows) => h("div", {class: "k4-tbcol"}, h("div", {class: "k4-tbh"}, h("b", null, name), h("span", null, label)),
      h("div", {role: "list"}, rows.map((r) => rowEl(r, user))));
    if (!n) put(tb, ui.empty("이 묶음에 계좌가 없습니다"));
    else if (n <= 10) put(tb, col(`전체 ${fmt.int(n)}개`, sel));
    else put(tb, col("상위 5", sel.slice(0, 5)), col("하위 5", sel.slice(-5)));
    put(tbFoot, h("p", {class: "assume"}, h("b", null, "참고"),
      " · 순위 = 고른 배수 줄의 손익 % · ▲▼ = 하루 전 손익 %로 매긴 순위보다 오르고 내린 칸 수 · 작은 선 = 시작부터 지금까지 잔고 (30점) · 흐린 줄 = 거래 30건 미만 (표본 적음)",
      st.sel === "flip" ? "" : " · 동전 ▲▼ = 같은 봉 · 같은 배수 동전 던지기 중앙값보다 위 · 아래 (운과 견줄 뿐, 판정 아님)"));
  }

  function posChip(r) {
    if (!r.pos.length) return null;
    const p = r.pos[0];
    const roe = finite(p.roe) ? Number(p.roe) : null;
    const t = roeText(roe);
    const more = r.pos.length > 1 ? ` 외 ${r.pos.length - 1}` : "";
    return h("span", {class: ["k4-pos", fmt.tone(roe, t)], title: `열린 포지션 ${r.pos.length}개 (이 배수) · 가장 좋은 것을 보입니다 · `
      + "증거금 대비 손익 (마지막 15분봉 기준, 나갈 때 수수료 전)\n" + r.pos.map((q) => `${fmt.coin(q.coin)} ${sideKo(q.side)} ${roeText(q.roe)}`).join("\n")},
    `${fmt.coin(p.coin)} ${sideKo(p.side)} ${st.L}배`, h("b", {class: ["num", fmt.tone(roe, t)]}, t), more || null);
  }
  function vsTag(r) {
    if (r.kind === "flip") return h("span", {class: "k4-vs", title: "동전 던지기는 판정 대상이 아니라 비교 기준입니다"}, "비교 기준");
    if (r.vs == null) return null;
    const [g, w, c] = r.vs > 0 ? ["▲", "위", "hi"] : r.vs < 0 ? ["▼", "아래", "lo"] : ["=", "같음", ""];
    return h("span", {class: ["k4-vs", c], title: `참고 · 같은 봉 · 같은 배수 동전 던지기 중앙값보다 ${w} (${fmt.num(r.vs, 1, true)}%p) · 판정 아님`,
      "aria-label": `참고: 동전 던지기 중앙값보다 ${w}`}, "동전 ", h("b", {"aria-hidden": "true"}, g));
  }

  // ================================================================ CSV
  function boardCsv() {
    const A = st.accts && !isMissing(st.accts) ? st.accts.accounts || [] : [];
    if (!A.length) return;                                       // nothing to write yet (the button stays harmless)
    const out = [];
    for (const L of LEVS) {
      const rows = ranked(linesAt(L).filter((r) => r.kind !== "flip")).concat(linesAt(L).filter((r) => r.kind === "flip").map((r) => ({...r, rk: null})));
      for (const r of rows) {
        const x = r.x || {}, s = x.stops || {};
        out.push([L, r.rk ?? "", r.id, r.a.name || "", kindKo(r.kind), SUB_KO[r.a.sub] || r.a.sub || "", r.a.short || "", tfKo(r.tf),
          x.pnl_pct ?? "", x.pnl_pct_24h ?? "", x.equity ?? "", x.pnl ?? "", x.trades ?? "", x.wins ?? "",
          finite(x.win_rate) ? fmt.num(Number(x.win_rate) * 100, 1) : "", x.mean_R ?? "", finite(x.max_dd) ? fmt.num(Number(x.max_dd) * 100, 1) : "",
          x.open ?? "", x.liqs ?? "", x.ruins ?? "", s.pnl_pct ?? "", r.conf && r.conf.status ? CONFIRM_KO[r.conf.status] || r.conf.status : "",
          r.vs != null ? fmt.num(r.vs, 2) : r.kind === "flip" ? "비교 기준" : "", r.a.setting_ko || ""]);
      }
    }
    K4.downloadCsv(`demolab-ranking-${stampName()}.csv`,
      ["배수", "순위(같은 배수, 동전 던지기 빼고)", "계좌", "이름", "종류", "세부", "매매법", "봉", "손익 %", "하루 전 손익 %", "잔고 $", "손익 $", "거래",
        "이김", "승률 %", "평균 R", "최대 낙폭 %", "열린 포지션", "강제청산", "파산 횟수", "정지 규칙 적용 시 손익 %", "확인 기간",
        "동전 던지기 중앙값 대비 %p (참고)", "지금 설정"], out);
  }
  async function paintTradesMenu() {
    put(tradesBox, h("p", {class: "muted"}, "불러오는 중…"));
    const [tr, ex] = await Promise.all([ctx.api("/api/trades").catch(() => null), ctx.api("/api/export").catch(() => null)]);
    if (!ctx.alive()) return;
    st.trades = tr; st.exports = ex;
    const rows = tr && !isMissing(tr) ? tr.trades || [] : [];
    const names = new Map((st.accts && !isMissing(st.accts) ? st.accts.accounts || [] : []).map((a) => [String(a.id), a.name || a.id]));
    const ids = ex && !isMissing(ex) ? ex.ids || [] : [];
    let cur = ids.includes(local.get("trades-csv")) ? local.get("trades-csv") : ids[0];
    const link = h("a", {class: "btn-line", download: ""}, "이 계좌 전부 CSV");
    const setLink = () => { if (cur) { link.setAttribute("href", `/api/export/${encodeURIComponent(cur)}.csv`); link.setAttribute("download", `demolab-${cur}.csv`); } };
    setLink();
    put(tradesBox,
      h("div", {class: "k4-mrow"}, h("b", null, "최근 거래 (모든 계좌)"),
        h("span", {class: "muted"}, rows.length ? `trades.json의 최근 ${fmt.int(rows.length)}건 · 배수 줄마다 한 줄` : "거래 자료 준비 중"),
        h("button", {type: "button", class: "btn-line", disabled: !rows.length || null, onclick: () => tradesCsv(rows)}, `최근 ${fmt.int(rows.length)}건 CSV`)),
      h("div", {class: "k4-mrow"}, h("b", null, "계좌 하나의 모든 거래"),
        ids.length ? [ui.select(ids.map((i) => ({id: i, label: names.get(i) || i})), cur, (v) => { cur = v; local.set("trades-csv", v); setLink(); }, "계좌"), link]
          : h("span", {class: "muted"}, "준비 중 · 엔진이 계좌별 CSV를 한 시간마다 씁니다")),
      h("p", {class: "note"}, "모든 줄 · 모든 기간은 계좌별 CSV에 있습니다 (엔진이 만든 파일). 최근 거래 CSV는 이 화면이 받은 자료로 만듭니다."));
  }
  function tradesCsv(rows) {
    K4.downloadCsv(`demolab-trades-recent-${stampName()}.csv`,
      ["청산 시각 (KST)", "진입 시각 (KST)", "계좌", "이름", "배수", "코인", "방향", "진입가", "손절가", "청산가", "이유", "상태", "손익 $", "ROE %", "R",
        "증거금 $", "펀딩 $", "수수료 $", "진입 비용 bp", "설정", "청산 방식", "키"],
      rows.map((t) => [t.exit_ms ? fmt.kst(t.exit_ms) : "", fmt.kst(t.entry_ms), t.account, t.name || "", t.L, fmt.coin(t.coin), sideKo(t.side), t.entry ?? "",
        t.stop ?? "", t.exit ?? "", t.reason ? reasonKo(t.reason) : "", t.status === "open" ? "열림" : t.status === "closed" ? "닫힘" : t.status || "", t.pnl ?? "", finite(t.roe) ? fmt.num(Number(t.roe) * 100, 2) : "", t.R ?? "", t.margin ?? "",
        t.funding ?? "", t.fee ?? "", t.cost_bps ?? "", t.setting_ko || "", t.exit_ko || "", t.key || ""]));
  }

  await load();
  ctx.every(60000, load);
  return () => document.removeEventListener("mousedown", closeMenu);
}

/** "20261009-2041" (KST) for file names. */
function stampName() {
  const d = new Date(Date.now() + 9 * 3.6e6), two = (x) => String(x).padStart(2, "0");
  return `${d.getUTCFullYear()}${two(d.getUTCMonth() + 1)}${two(d.getUTCDate())}-${two(d.getUTCHours())}${two(d.getUTCMinutes())}`;
}

/** The dense table's columns (v4 board-table, plus the demo's 확인 기간 and 정지 규칙 적용 시). */
function tableCols(ctx, state) {
  const x = (r) => r.x || {};
  const confRank = {confirmed: 3, confirming: 2, failed: 1};
  return [
    {id: "rk", label: "순위", sort: (r) => r.rk ?? null, dir: 1, get: (r) => h("span", {class: "bd-rkc"}, r.rk == null ? "—" : fmt.int(r.rk),
      K4.rankDelta(r.delta, {title: "하루 전 손익 %로 매긴 순위와 비교"}))},
    {id: "name", label: "계좌", l: true, sort: (r) => String(r.a.name || r.id), dir: 1, get: (r) => h("span", {class: "dl-anrow"},
      h("a", {class: "k4-name", href: ctx.href("account", r.id), title: r.id}, K4.acctFig(r.a, 18), K4.acctName(r.a)),
      starBtn("account", r.id, {label: r.a.name || r.id}))},
    {id: "kind", label: "종류 · 세부", l: true, sort: (r) => `${r.kind}|${r.a.sub || ""}`, dir: 1, get: (r) => (state().sel === "all"
      ? h("span", {class: "dl-kn"}, h("span", null, KIND_KO[r.kind] || "기타"), SUB_KO[r.a.sub] ? h("small", {class: "muted"}, SUB_KO[r.a.sub]) : null)
      : h("span", {class: "muted"}, SUB_KO[r.a.sub] || KIND_KO[r.kind] || "—"))},
    {id: "pnl", label: "손익 %", sort: (r) => r.pnl, get: (r) => { const t = fmt.pct(r.pnl, true); return h("b", {class: ["num", fmt.tone(r.pnl, t)]}, t); }},
    {id: "eq", label: "잔고", sort: (r) => (finite(x(r).equity) ? Number(x(r).equity) : null), get: (r) => h("span", {class: "num"}, fmt.money(x(r).equity))},
    {id: "trades", label: "거래", sort: (r) => Number(x(r).trades) || 0, get: (r) => h("span", {class: "num"}, fmt.int(x(r).trades), K4.smallSample(x(r).trades) ? h("small", {class: "muted"}, " 적음") : null)},
    {id: "win", label: "승률", sort: (r) => (finite(x(r).win_rate) ? Number(x(r).win_rate) : null), get: (r) => (Number(x(r).trades)
      ? h("span", {class: "num"}, fmt.ratio(x(r).win_rate, 0), h("small", {class: "k4-wl"}, ` ${fmt.int(x(r).wins)}승 ${fmt.int((x(r).trades || 0) - (x(r).wins || 0))}패`)) : "—")},
    {id: "dd", label: "최대 낙폭", sort: (r) => (finite(x(r).max_dd) ? Number(x(r).max_dd) : null), dir: 1, get: (r) => fmt.ratio(x(r).max_dd)},
    {id: "pos", label: "상태", l: true, sort: (r) => (x(r).ruined ? -1 : r.pos.length), get: (r) => (r.pos.length ? h("span", {class: "k4-pos"},
      `${fmt.coin(r.pos[0].coin)} ${sideKo(r.pos[0].side)} ${state().L}배`, h("b", {class: ["num", fmt.tone(r.pos[0].roe, roeText(r.pos[0].roe))]}, roeText(r.pos[0].roe)),
      r.pos.length > 1 ? ` 외 ${r.pos.length - 1}` : null)
      : x(r).ruined ? h("span", {class: "pp bad"}, "파산 기록") : h("span", {class: "muted"}, "대기"))},
    {id: "vs", label: "동전 대비", title: "참고: 같은 봉 · 같은 배수 동전 던지기 중앙값과의 차이 (%p, 판정 아님)", sort: (r) => r.vs, get: (r) => (r.kind === "flip"
      ? h("span", {class: "muted"}, "비교 기준") : r.vs == null ? "—" : h("span", {class: ["k4-vs", r.vs > 0 ? "hi" : r.vs < 0 ? "lo" : ""]},
        h("b", null, r.vs > 0 ? "▲ " : r.vs < 0 ? "▼ " : "= "), `${fmt.num(r.vs, 1, true)}%p`))},
    {id: "conf", label: "확인 기간", sort: (r) => (r.conf && r.conf.status ? confRank[r.conf.status] || 0 : 0), get: (r) => ui.confirmBadge(r.conf, true)},
    {id: "stops", label: "정지 규칙 적용 시", title: "같은 진입에 정지 규칙(계좌 −20% · 하루 −5% · 5연패)을 걸었다면의 손익",
      sort: (r) => (x(r).stops && finite(x(r).stops.pnl_pct) ? Number(x(r).stops.pnl_pct) : null), get: (r) => {
        const sp = x(r).stops;
        if (!sp) return h("span", {class: "muted"}, "준비 중");
        const t = fmt.pct(sp.pnl_pct, true);
        return h("span", {class: "dl-kn"}, h("b", {class: ["num", fmt.tone(sp.pnl_pct, t)]}, t),
          sp.halted_ms ? h("small", {class: "muted"}, `${fmt.mmdd(sp.halted_ms)} 멈춤`) : h("small", {class: "muted"}, `막힘 ${fmt.int(sp.blocked)}`));
      }},
  ];
}
