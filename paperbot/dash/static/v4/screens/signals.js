// #/signals — 신호 (builder E). The last 24 hours per timeframe (count, late, average delay vs the limit) from
// /api/status, and the signal log (/api/signals) with a timeframe filter, search and 10 rows a page. A signal is an
// entry REQUEST: whether an account really entered is on its account screen. New signals (a real new id) slide in.
// Old homes: 신호 tab, 서버 상태 › 최근 24시간 신호 (INVENTORY.md 12).
import {h, ui, fmt, motion, local, put} from "../core/pb.js";
import {SIG_KO, SIG_CLS, sigByTf, limitsOf, limitFor, sec, dayTime, note} from "./server-kit.js";

const TFS = [{id: "", label: "전부"}, {id: "5m", label: "5분"}, {id: "15m", label: "15분"}, {id: "30m", label: "30분"}, {id: "1h", label: "1시간"},
  {id: "4h", label: "4시간"}, {id: "1d", label: "일봉(기록)"}];

/** A strategy code in Korean (fmt.stratKo knows the 36, DeepSeek and the reel); DeepSeek says so. */
const nameKo = (code) => (fmt.familyKo(String(code || "")) ? `딥시크 · ${fmt.stratKo(code)}` : fmt.stratKo(code));

export async function mount(el, ctx) {
  ctx.setTitle("신호");
  el.append(ui.screenHead("신호", "봉이 닫힐 때 매매법이 낸 진입 요청"));

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
  el.append(h("div", {class: "signals-cols"}, sumCard,
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
