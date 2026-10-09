// #/trades 거래 기록: the newest trades of all accounts (trades.json, newest 300 rows; each leverage line is its own
// row), filtered by account kind, coin, open / closed and leverage, with the measured entry cost and the market at entry
// (CONTRACT 8.3 / 8.5). A row opens its trade chart (#/trade/<account>/<key>); the account's name opens the account.
// Round 5 stage 2: the rule bot's v4 positions › 체결 기록 rows (positions.js / positions-kit.css): the time, the
// account's pixel character and timeframe chip, the P&L on the right, the coin / side / leverage / prices / reason /
// cost / market / setting as one quiet line under it; the filters in one bar; CSV 내려받기 (CONTRACT 9.9: one account's
// every trade, all four lines) as a small menu in the screen head. Every 60 s. Read-only; a missing file shows "준비 중".
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {COINS, KINDS, LEVS, kindOfId, reasonKo, sideKo} from "../labels.js";

/** An account-like object for the pixel figure and the name chip, from a trade row (account id, name, key "COIN|tf|..."). */
function acctOf(t) {
  const x = String(t.account || "");
  const tf = /-(15m|30m)$/.exec(x), sh = /(?:^|-)(S2|N02|N04)(?:-|$)/.exec(x);
  return {id: x, name: t.name || x, kind: kindOfId(x), tf: tf ? tf[1] : String(t.key || "").split("|")[1] || null, short: sh ? sh[1] : null};
}

export async function mount(el, ctx) {
  ctx.setTitle("거래 기록");
  const saved = local.get("trades", {}) || {};
  const f = {kind: saved.kind || "all", coin: saved.coin || "all", st: saved.st || "all", lev: saved.lev || "all"};
  const keep = () => local.set("trades", f);
  const kindSeg = ui.seg([{id: "all", label: "전체"}, ...KINDS.map((k) => ({id: k.id, label: k.ko}))], f.kind,
    (v) => { f.kind = v; keep(); apply(false); }, {label: "계좌 종류", cls: "scroll"});
  const stSeg = ui.seg([{id: "all", label: "전체"}, {id: "open", label: "열림"}, {id: "closed", label: "닫힘"}], f.st,
    (v) => { f.st = v; keep(); apply(false); }, {label: "상태"});
  const coinSel = ui.select([{id: "all", label: "모든 코인"}, ...COINS.map((c) => ({id: c, label: fmt.coin(c)}))], f.coin,
    (v) => { f.coin = v; keep(); apply(false); }, "코인");
  const levSel = ui.select([{id: "all", label: "모든 배수"}, ...LEVS.map((L) => ({id: String(L), label: `${L}배`}))], f.lev,
    (v) => { f.lev = v; keep(); apply(false); }, "배수");
  const count = h("span", {class: "s2a-count"});
  const pg = ui.pager({size: 25, empty: "조건에 맞는 거래가 없습니다", render: (part) => h("div", {class: "s2a-trows", role: "list"}, part.map((t) => tradeRow(t, ctx)))});
  const box = h("div");
  // CSV 내려받기 (CONTRACT 9.9): one account's every trade (all four lines), picked from the accounts that have a file
  const csvBox = h("div", {class: "k4-menupop", role: "group", "aria-label": "CSV 내려받기"}, h("span", {class: "muted"}, "불러오는 중"));
  const csvMenu = h("details", {class: "k4-menu"}, h("summary", {class: "btn-line", title: "한 계좌의 모든 거래 (배수 4줄) · 엑셀에서 열림"}, "CSV 내려받기 ",
    h("span", {"aria-hidden": "true"}, "▾")), csvBox);
  const closeMenu = (e) => { if (csvMenu.open && !csvMenu.contains(e.target)) csvMenu.open = false; };
  document.addEventListener("mousedown", closeMenu);
  (async () => {
    let x, names = {};
    try {
      x = await ctx.api("/api/export");
      if (x && Array.isArray(x.ids) && x.ids.length) {
        const a = await ctx.api("/api/accounts");
        for (const r of (a && a.accounts) || []) names[r.id] = r.name;
      }
    } catch (e) { if (e && e.name === "AbortError") return; }
    if (!ctx.alive()) return;
    const ids = x && Array.isArray(x.ids) ? x.ids : [];
    if (!ids.length) { put(csvBox, h("p", {class: "note"}, "준비 중 · 엔진이 계좌별 CSV를 아직 쓰지 않았습니다 (한 시간마다 씀)")); return; }
    const pick = local.get("trades-csv");
    let cur = ids.includes(pick) ? pick : ids[0];
    const link = h("a", {class: "btn-line", download: true}, "CSV 내려받기");
    const setLink = () => { link.setAttribute("href", `/api/export/${encodeURIComponent(cur)}.csv`); };
    setLink();
    const sel = ui.select(ids.map((i) => ({id: i, label: names[i] ? `${names[i]} (${i})` : i})), cur, (v) => { cur = v; local.set("trades-csv", v); setLink(); }, "계좌");
    put(csvBox, h("div", {class: "k4-mrow"}, h("b", null, "한 계좌의 모든 거래 (배수 4줄)"), sel, link),
      h("p", {class: "note"}, `${fmt.int(ids.length)}개 계좌${x.generated_ms ? ` · ${fmt.kst(x.generated_ms)}에 씀` : ""} · 엑셀에서 열림 (UTF-8)`));
  })();
  el.append(ui.screenHead("거래 기록", "모든 계좌의 최근 거래 (배수마다 한 줄)", [csvMenu]),
    h("div", {class: "s2a-bar s2a-tfilt"},
      h("span", {class: "s2a-barg"}, h("span", {class: "k4-k"}, "계좌 종류"), kindSeg),
      h("span", {class: "s2a-barg"}, h("span", {class: "k4-k"}, "상태"), stSeg),
      h("span", {class: "s2a-barg"}, h("span", {class: "k4-k"}, "코인"), coinSel),
      h("span", {class: "s2a-barg"}, h("span", {class: "k4-k"}, "배수"), levSel)),
    ui.card({plate: "거래", sub: "줄을 누르면 거래 차트 · 이름을 누르면 계좌", acts: [count]}, box, pg.el),
    h("p", {class: "assume"}, "손익은 수수료·슬리피지·펀딩을 뺀 값입니다. 열린 거래는 마크 가격 기준 미실현(나갈 때 수수료 전). 주문 없음."));

  let rows = null, seen = null;
  function apply(keepPage) {
    if (!rows) return;
    const out = rows.filter((t) => (f.kind === "all" || kindOfId(t.account) === f.kind)
      && (f.coin === "all" || t.coin === f.coin) && (f.st === "all" || t.status === f.st)
      && (f.lev === "all" || String(t.L) === f.lev));
    count.textContent = `최근 ${fmt.int(rows.length)}줄 중 ${fmt.int(out.length)}줄`;
    pg.set(out, keepPage);
    if (!keepPage) K4.swap(pg.el);
  }
  async function load() {
    let d;
    try { d = await ctx.api("/api/trades"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!rows) put(box, ui.errorBox(e, load));
      return;
    }
    if (d && d.generated_ms != null && d.generated_ms === seen) return;
    seen = d ? d.generated_ms : null;
    if (isMissing(d)) { rows = null; put(box, ui.missing("거래 기록")); pg.set([]); count.textContent = ""; return; }
    put(box);
    const first = rows == null;
    rows = d.trades || [];
    apply(!first);
  }
  await load();
  ctx.every(60000, load);
  return () => document.removeEventListener("mousedown", closeMenu);
}

const priceDec = (p) => { const a = Math.abs(Number(p) || 0); return a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1; };

/** One trade as a v4 체결 row: time · figure + name · P&L (and R), the rest as one quiet line; the row opens the chart. */
function tradeRow(t, ctx) {
  const open = t.status === "open";
  const a = acctOf(t);
  const pT = fmt.money(t.pnl, true), rT = fmt.r(t.R);
  const go = t.account && t.key ? ctx.href("trade", t.account, {from: "trades"}, t.key) : null;
  const row = h("div", {class: ["s2a-trow", go ? "click" : "", open ? "open" : ""], role: "listitem", tabindex: go ? "0" : null,
    title: go ? "누르면 거래 차트" : null},
  h("span", {class: "s2a-trk num"}, fmt.kst(open ? t.entry_ms : t.exit_ms)),
  h("span", {class: "s2a-trn"}, t.account ? h("a", {class: "s2a-nm dl-tacct", href: ctx.href("account", t.account), title: t.account}, K4.acctFig(a, 18), K4.acctName(a))
    : h("span", {class: "muted"}, "—")),
  h("span", {class: "s2a-trr"}, h("b", {class: ["num", fmt.tone(t.pnl, pT)]}, pT), h("small", {class: ["num", fmt.tone(t.R, rT)]}, rT)),
  h("span", {class: "s2a-trm"},
    h("b", null, fmt.coin(t.coin)), h("span", {class: ["side", Number(t.side) > 0 ? "long" : "short"]}, sideKo(t.side)),
    h("span", {class: "dl-levtag", dataset: {lev: t.L}}, fmt.lev(t.L)),
    h("span", {class: "num"}, fmt.num(t.entry, priceDec(t.entry)), " → ", t.exit != null ? fmt.num(t.exit, priceDec(t.exit)) : "—"),
    open ? ui.pill("열림", "accent") : h("span", {class: t.reason === "liq" ? "down" : ""}, reasonKo(t.reason)),
    h("span", {class: "s2a-trc"}, h("span", {class: "muted"}, "비용 "), ui.costCell(t)),
    t.trend || t.vol ? ui.regimeChips(t.trend, t.vol) : null,
    h("span", {class: "muted mono dl-tset", title: `${t.setting_ko || ""} · ${t.exit_ko || ""}`}, t.setting_ko || "—")));
  if (go) {
    row.addEventListener("click", (e) => { if (!(e.target && e.target.closest && e.target.closest("a, button"))) location.hash = go; });
    row.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target === row) location.hash = go; });
  }
  return row;
}
