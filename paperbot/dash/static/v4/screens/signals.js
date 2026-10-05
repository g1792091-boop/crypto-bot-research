// #/signals — 신호 (builder E). The last 24 hours per timeframe (count, late, average delay vs the limit) from
// /api/status, and the signal log (/api/signals) with a timeframe filter, search and 10 rows a page. A signal is an
// entry REQUEST: whether an account really entered is on its account screen. New signals (a real new id) slide in.
// Old homes: 신호 tab, 서버 상태 › 최근 24시간 신호 (INVENTORY.md 12).
import {h, ui, fmt, motion, local, put, bars, serverNow} from "../core/pb.js";
import {SIG_KO, SIG_CLS, sigByTf, limitsOf, limitFor, sec, dayTime, note, TF_ORDER} from "./server-kit.js";
import {waitRoom} from "./strategies-radar.js";

const TFS = [{id: "", label: "전부"}, {id: "5m", label: "5분"}, {id: "15m", label: "15분"}, {id: "30m", label: "30분"}, {id: "1h", label: "1시간"},
  {id: "4h", label: "4시간"}, {id: "1d", label: "일봉(기록)"}];

/** A strategy code in Korean (fmt.stratKo knows the 36, DeepSeek and the reel); DeepSeek says so. */
const nameKo = (code) => (fmt.familyKo(String(code || "")) ? `딥시크 · ${fmt.stratKo(code)}` : fmt.stratKo(code));

export async function mount(el, ctx) {
  ctx.setTitle("신호");
  el.append(ui.screenHead("신호", "봉이 닫힐 때 매매법이 낸 진입 요청"));
  // fill-radar: 곧 신호 대기실 (the 36's conditions on 6 coins, strategies-radar.js) and the 24-hour coin x timeframe map
  el.append(h("div", {class: "signals-top"}, waitRoom(ctx).el, heatCard(ctx).el));

  // ---------------------------------------------------------------- the last 24 hours per timeframe
  const sumBody = h("div", {class: "stack tight"});
  const sumCard = ui.card({plate: "최근 24시간", sub: "봉별 신호 수와 계산 지연"}, sumBody,
    note("지연 = 봉이 닫힌 뒤 신호를 계산해 기준가를 잡기까지 걸린 시간. 한도를 넘긴 신호는 '늦음'으로 들어가지 않습니다."));
  const paintSum = (s) => {
    const lim = limitsOf(s);
    const rows = sigByTf(s && s.signals_24h);
    if (!rows.length) { put(sumBody, ui.empty(s ? "지난 24시간 동안 신호가 없었습니다" : "읽는 중")); return; }
    put(sumBody, ui.table([
      {label: "봉", l: true, get: (r) => fmt.tfKo(r.tf)},
      {label: "신호", get: (r) => fmt.int(r.n)},
      {label: "늦음", get: (r) => r.late ? h("span", {class: "warn-t"}, fmt.int(r.late)) : "0"},
      {label: "평균 지연", get: (r) => sec(r.avg)},
      {label: "한도", get: (r) => sec(limitFor(r.tf, lim))},
    ], rows), h("div", {class: "server-counts"}, Object.entries(SIG_KO).map(([k, v]) => {
      const n = rows.reduce((a, r) => a + (r.statuses[k] || 0), 0);
      return n ? h("span", null, `${v} `, h("b", null, fmt.int(n))) : null;
    })));
  };
  ctx.watch("status", paintSum);

  // ---------------------------------------------------------------- groups x timeframes (v4_missing A8)
  // status.signals_by_group (the server's G15 rows): a stopped DeepSeek timeframe shows as a 0 next to the 36's counts.
  // "Expected" timeframes come from the board's own accounts (a group with no account on a timeframe shows ·).
  const grpBody = h("div", {class: "stack tight"});
  const grpCard = ui.card({plate: "묶음별 신호", sub: "최근 24시간 · 묶음 × 봉"}, grpBody,
    note("숫자 = 신호 수, 주황 '늦음' = 한도를 넘겨 진입하지 않은 신호. · = 그 묶음은 그 봉에 계좌가 없음. "
      + "다른 봉은 신호가 있는데 한 봉만 0이면 주황으로 표시합니다 (멈췄는지 확인; 신호가 드문 4시간봉은 빼고). "
      + "추가 계좌(복제)는 원본과 같은 신호를 써서 기존 36에 함께 셉니다."));
  const gst = {status: null, board: null};
  const paintGroups = () => {
    const rows = gst.status && Array.isArray(gst.status.signals_by_group) ? gst.status.signals_by_group : null;
    if (!rows) { put(grpBody, gst.status ? ui.notYet("묶음별 신호 수집 전") : ui.empty("읽는 중")); return; }
    put(grpBody, groupGrid(rows, gst.board));
  };
  ctx.watch("status", (s) => { if (s) { gst.status = s; paintGroups(); } });
  ctx.watch("board", (b) => { if (b) { gst.board = b; paintGroups(); } });

  // ---------------------------------------------------------------- the log
  let tf = TFS.some((t) => t.id === local.get("signals-tf")) ? local.get("signals-tf") : "";
  let seen = null;                                   // ids already shown (null: first load, nothing slides)
  const fresh = new Set();
  const list = ui.searchList({size: 10, placeholder: "매매법·코인 찾기", empty: "신호가 없습니다",
    match: (r, q) => r.nm.toLowerCase().includes(q) || String(r.strategy).toLowerCase().includes(q) || fmt.coin(r.symbol).toLowerCase().includes(q),
    row: (r) => {
      const late = r.status === "LATE";
      const el2 = h("div", {class: "lrow signals-row", role: "listitem"},
        h("span", {class: "rk"}, fmt.hm(r.bar_close)),
        h("span", {class: "lname", title: r.strategy}, r.nm, h("span", {class: "muted"}, ` · ${fmt.tfKo(r.timeframe)}`)),
        h("span", {class: ["ret", late ? "warn-t" : "ink2"]}, r.delay_ms == null ? "—" : sec(r.delay_ms)),
        h("span", {class: "meta"}, h("b", {class: "signals-coin"}, fmt.coin(r.symbol)), ui.sideTag(r.side),
          h("span", null, `기준가 ${fmt.price(r.ref_price)}`),
          // the usual case (진입 요청) needs no pill: only the unusual statuses get one
          r.status !== "SUBMITTED" ? ui.pill(SIG_KO[r.status] || String(r.status || "—"), SIG_CLS[r.status] || "") : null,
          dayTime(r.bar_close).startsWith("오늘") ? null : h("span", null, fmt.mmdd(r.bar_close))));
      if (fresh.delete(r.id)) motion.slideIn(el2);
      return el2;
    }});
  const tfSeg = ui.seg(TFS, tf, (id) => { tf = id; local.set("signals-tf", id); seen = null; load(true); }, {label: "봉", scroll: true});
  const listNote = note();
  el.append(h("div", {class: "signals-cols"}, h("div", {class: "stack signals-left"}, sumCard, grpCard),
    ui.card({plate: "신호 기록", sub: "최근 300개까지"}, tfSeg, list.el, listNote,
      note("표시가 없는 줄은 '진입 요청'입니다. 일봉은 기록만 합니다 (거래하지 않음). 실제로 들어갔는지는 계좌 화면에서 봅니다."))));

  async function load(reset) {
    try {
      const rows = await ctx.api(`/api/signals?limit=300${tf ? `&tf=${encodeURIComponent(tf)}` : ""}`);
      if (!ctx.alive()) return;
      const items = (Array.isArray(rows) ? rows : []).map((r) => ({...r, nm: nameKo(r.strategy)}));
      if (seen) for (const r of items) if (!seen.has(r.id)) fresh.add(r.id);
      seen = new Set(items.map((r) => r.id));
      list.set(items, !reset);
      if (reset) motion.swap(list.el);
      listNote.textContent = items.length ? `${fmt.int(items.length)}개 · 가장 최근 ${dayTime(items[0].bar_close)} 마감` : "";
    } catch (e) {
      if (e && e.name === "AbortError") return;
      listNote.textContent = "신호를 불러오지 못했습니다. 1분 뒤 다시 읽습니다.";
    }
  }
  await load(true);
  ctx.every(60000, () => load(false), {now: false});
}

export function unmount() {}

// ---------------------------------------------------------------- 24 hours: coin x timeframe (fill-radar)
const HEAT_TFS = ["5m", "15m", "30m", "1h", "4h"];
/** /api/signals rows (newest first) -> {coins, tfs, cells: {"SYM|tf": {n, long, short, late}}, n, capped} for the last 24 h.
 *  capped: 1,000 rows came back and the oldest is still inside the 24 h (older ones are missing from the count). */
export function heatMap(rows, now) {
  const since = now - 864e5, cells = {}, coins = new Set(bars.TRADE_SYMS), tfs = new Set(["15m", "30m", "1h", "4h"]);
  let n = 0, oldest = Infinity;
  for (const r of rows || []) {
    if (!r || !(Number(r.bar_close) >= since)) continue;
    oldest = Math.min(oldest, Number(r.bar_close));
    if (!HEAT_TFS.includes(r.timeframe)) continue;
    const c = (cells[`${r.symbol}|${r.timeframe}`] ||= {n: 0, long: 0, short: 0, late: 0});
    c.n++; n++;
    if (Number(r.side) > 0) c.long++; else c.short++;
    if (r.status === "LATE") c.late++;
    coins.add(r.symbol); tfs.add(r.timeframe);
  }
  return {coins: bars.SYMS.filter((s) => coins.has(s)), tfs: HEAT_TFS.filter((t) => tfs.has(t)), cells, n,
    capped: (rows || []).length >= 1000 && oldest > since};
}

function heatCard(ctx) {
  const body = h("div", {class: "sig-heat-wrap"}, motion.shimmer(4));
  const foot = note();
  const card = ui.card({plate: "24시간 신호 지도", sub: "코인 × 봉 · 모든 묶음의 신호 수", cls: "sig-heatcard"}, body, foot,
    note("칸 = 지난 24시간 그 코인·봉에서 나온 신호 수 (초록 롱 · 빨강 숏). 색이 진할수록 많습니다. 새 신호가 들어오면 그 칸이 한 번 반짝입니다. "
      + "딥시크·동전 봇도 수만 셉니다 (손익 아님). 봉 이름 아래 숫자는 그 봉이 다음에 닫히기까지 남은 시간입니다."));
  let prev = null, shown = false;
  function paint(rows) {
    const m = heatMap(rows, serverNow());
    const cells = new Map();
    const max = Math.max(1, ...Object.values(m.cells).map((c) => c.n));
    put(body, h("div", {class: "sig-heat", style: {"--cols": String(m.tfs.length)}},
      h("span", {class: "sig-heat-h"}, "코인"),
      m.tfs.map((tf) => h("span", {class: "sig-heat-h"}, fmt.tfKo(tf), h("small", {class: "sig-heat-cd num", dataset: {tf}}, bars.closeIn(tf, serverNow())))),
      m.coins.map((sym) => [h("b", {class: "sig-heat-coin"}, fmt.coin(sym)), m.tfs.map((tf) => {
        const c = m.cells[`${sym}|${tf}`];
        if (!c) return h("span", {class: "sig-heat-cell zero"}, "0");
        const x = h("span", {class: "sig-heat-cell", style: {"--a": `${Math.round(10 + 36 * c.n / max)}%`},
          title: `${fmt.coin(sym)} ${fmt.tfKo(tf)} · 롱 ${c.long} · 숏 ${c.short}${c.late ? ` · 늦음 ${c.late}` : ""}`},
          h("b", {class: "num"}, fmt.int(c.n)), h("small", null, h("span", {class: "up"}, fmt.int(c.long)), " · ", h("span", {class: "down"}, fmt.int(c.short))),
          c.late ? h("small", {class: "warn-t"}, `늦음 ${fmt.int(c.late)}`) : null);
        cells.set(`${sym}|${tf}`, [x, c.n]);
        return x;
      })])));
    if (prev) for (const [k, [x, n]] of cells) if (n > (prev.get(k) || 0)) motion.flash(x, "accent");   // a real new signal
    prev = new Map([...cells].map(([k, [, n]]) => [k, n]));
    foot.textContent = m.n ? `지난 24시간 신호 ${fmt.int(m.n)}개` + (m.capped ? " · 최근 1,000개까지만 셉니다 (그보다 오래된 것은 빠짐)" : "")
      : "지난 24시간 동안 신호가 아직 없습니다";
  }
  async function load() {
    try {
      const rows = await ctx.api("/api/signals?limit=1000");
      if (!ctx.alive()) return;
      paint(Array.isArray(rows) ? rows : []);
      shown = true;
    } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!shown) put(body, ui.notYet("준비 전", "신호 기록을 읽지 못했습니다"));
    }
  }
  ctx.every(1000, () => { const now = serverNow(); for (const x of body.querySelectorAll(".sig-heat-cd")) x.textContent = bars.closeIn(x.dataset.tf, now); }, {now: false});
  ctx.every(60000, load, {now: false});
  load();
  return {el: card};
}

// the server's group keys (paperbot/groups.py, dash/app.py signal_group) in the owners' order and words. No 추가 계좌
// row: the server never counts one (a copy trades on its original's signals, counted with the 36; the new-strategy
// lab's NL rows are left out of /api/status), so a row there would be all zeros.
const SIG_GROUPS = [["core", "기존 36"], ["ds200", "딥시크"], ["reel", "5분봉"], ["flip", "동전 봇"]];
const KIND_GROUP = {strategy: "core", ds200: "ds200", reel: "reel", random: "flip"};
const RARE_TF = new Set(["4h", "1d"]);

/** status.signals_by_group [{group, timeframe, status, n}] + the board's accounts -> a small group x timeframe table. */
export function groupGrid(rows, board) {
  const by = {}, seenTf = new Set();
  for (const r of rows || []) {
    if (!r || typeof r !== "object") continue;
    const c = ((by[r.group] ||= {})[r.timeframe] ||= {n: 0, late: 0});
    const n = Number(r.n) || 0;
    c.n += n;
    if (r.status === "LATE") c.late += n;
    seenTf.add(r.timeframe);
  }
  const has = {};                                      // group -> Set of timeframes it has accounts on
  for (const a of (board && board.accounts) || []) {
    const g = a.group || KIND_GROUP[a.kind];
    if (g) (has[g] ||= new Set()).add(a.timeframe);
  }
  const tfs = TF_ORDER.filter((tf) => seenTf.has(tf) || Object.values(has).some((s) => s.has(tf)));
  const groups = SIG_GROUPS.filter(([g]) => by[g] || has[g]);
  if (!groups.length || !tfs.length) return ui.empty("지난 24시간 동안 신호가 없었습니다");
  const cell = (g, tf) => {
    const c = by[g] && by[g][tf];
    const mine = has[g];
    if (!c && board && mine && !mine.has(tf)) return h("span", {class: "muted", title: "이 봉에는 계좌가 없음"}, "·");
    const n = c ? c.n : 0;
    if (!n) {
      // 0 on a timeframe the group trades while another of its timeframes has signals: worth a look (not on 4h / 1d,
      // where a quiet day is normal: about 0.07 trades a month per account on 4h, research/power)
      const others = board && mine && mine.size > 1 && !RARE_TF.has(tf)
        && [...mine].some((t) => t !== tf && by[g] && by[g][t] && by[g][t].n >= 5);
      return others ? h("b", {class: "warn-t", title: "다른 봉은 신호가 있는데 이 봉은 24시간 동안 0개입니다: 멈췄는지 확인"}, "0") : "0";
    }
    return h("span", {class: "signals-cell"}, fmt.int(n), c.late ? h("small", {class: "warn-t"}, ` 늦음 ${fmt.int(c.late)}`) : null);
  };
  return ui.table([{label: "묶음", l: true, get: (r) => r[1]},
    ...tfs.map((tf) => ({label: fmt.tfKo(tf), get: (r) => cell(r[0], tf)}))], groups);
}
