// 순위표 rows (RANK builder), copied from the rule bot's v4 board (home-shared.js rankRow / topBottom / rankList,
// board-motion.js) and fitted to the 후보 리그. One row:
//   rank (+ ▲▼ since this viewer's last visit) · pixel character · 15분 chip · Korean name (2순위, role chip)
//   ................................................ small balance line · 잔고 수익률 %
//   거래 n · a승 b패 · 잔고 x · 낙폭 y% · ● BTC 롱 30배 +0.1% (live) · 표본 적음 · 파산 · 동전 ▲/▼ (참고)
// A hidden DeepSeek account (snapshot ds_money false) is a count-only row: no rank, no %, no balance, no line; its
// position pill names the coin and the side only; its 동전 mark is the judge's label (30 trades or more), never a number.
// DOM only through h() / put().
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as K4 from "../v4kit.js";
import * as LK from "../lk.js";
import {TFS, tfKo, ROLE_SHORT, STYLE_KO} from "../labels.js";
import {SMALL, hidden, walletRet, retPct, nameBits, kindKo, rowVsFlip} from "./rank-cards.js";
import {openAfter, openBefore, afterOn} from "../after.js";

// ---------------------------------------------------------------- ▲▼ since the last visit (a per-viewer convenience)
/**
 * rankMemo(key, {gapMs, now}) -> {base, save(values)} (rule bot core/ui.js rankMemo): a visit is a run of saves less
 * than gapMs apart (30 min); base is the last values of the visit before this one ({ts, v} or null), so hopping
 * between screens keeps the same arrows. localStorage only (a private window shows no arrows).
 */
export function rankMemo(key = "rank-memo", o = {}) {
  const gap = o.gapMs || 30 * 60000;
  const now = o.now || Date.now();
  let st = local.get(key, null);
  if (!st || typeof st !== "object") st = {};
  if (st.cur && st.cur.seen && now - st.cur.seen > gap) { st.prev = {ts: st.cur.seen, v: st.cur.v}; st.cur = null; }
  const base = st.prev && st.prev.v && typeof st.prev.v === "object" ? st.prev : null;
  return {
    base,
    save(values) {
      const v = {};
      for (const [k, x] of Object.entries(values || {})) if (Number.isFinite(x)) v[k] = Math.round(x * 1e5) / 1e5;
      st.cur = {seen: Date.now(), v};
      local.set(key, st);
    },
  };
}
/** {id: earlier rank - rank now} among the ranked accounts that existed both times (positive = moved up). */
export function rankDeltas(base, shown, d) {
  if (!base || !base.v) return {};
  const ids = shown.map((a) => a.id).filter((id) => Number.isFinite(base.v[id]));
  const now = Object.fromEntries(shown.filter((a) => ids.includes(a.id)).map((a) => [a.id, walletRet(a, d)]));
  const was = Object.fromEntries(ids.map((id) => [id, base.v[id]]));
  const r0 = K4.ranksOf(was), r1 = K4.ranksOf(now);
  return Object.fromEntries(ids.map((id) => [id, r0[id] - r1[id]]));
}

// ---------------------------------------------------------------- one row
/** The neutral 동전 ▲ / ▼ mark (참고: never green / red); "비교 기준" on a coin-flip row. */
export function vsGlyph(a, d, ix) {
  if (a.role === "flip") return h("span", {class: "k4-vs", title: "동전 계좌는 판정 대상이 아니라 비교 기준입니다"}, "비교 기준");
  const v = rowVsFlip(d, ix, a);
  if (v == null) return null;
  const t = v ? "위" : "아래";
  return h("span", {class: "k4-vs", title: `참고 · 같은 후보의 동전 계좌보다 거래 한 번 평균이 ${t}${hidden(a, d) ? " (점검 라벨, 금액 숨김)" : ""} · 판정 아님`,
    "aria-label": `참고: 동전 계좌보다 ${t}`}, "동전 ", h("b", {"aria-hidden": "true"}, v ? "▲" : "▼"));
}

/**
 * rankRow(a, o) -> a.k4-row.rk-row link to the account. o: {d, ix, rk (null: no rank), delta, spark(a) -> svg|null,
 * pill(a) -> element, role (show the role chip), kind (say 기존 36 / 딥시크), moved: Map(id -> "up"|"down"), flash: []}.
 */
export function rankRow(a, o) {
  const d = o.d;
  const co = hidden(a, d);
  const r = walletRet(a, d);
  const t = retPct(r);
  const words = [];
  if (o.kind) words.push(kindKo(a.kind));
  words.push(`거래 ${fmt.int(a.trades)}`);
  if (a.trades) words.push(`${fmt.int(a.wins)}승 ${fmt.int(a.trades - a.wins)}패`);
  if (!co && a.wallet != null) words.push(`잔고 ${fmt.num(a.wallet, 2)}`);
  if (!co && a.max_dd) words.push(`낙폭 ${fmt.pct(a.max_dd * 100, false, 1)}`);
  const meta = [h("span", null, words.join(" · "))];
  if (a.open && o.pill) meta.push(o.pill(a));
  if (co) meta.push(h("span", {class: "pp thin", title: "딥시크 금액 숨김 설정: 잔고·수익률·순위 없이 개수와 라벨만"}, "금액 숨김"));
  meta.push(K4.smallSample(a.trades, SMALL));
  if (a.bust) meta.push(K4.pill("파산", "bad", "잔고 10 USDT 미만으로 정지"));
  meta.push(vsGlyph(a, d, o.ix));
  const rkd = o.delta ? K4.rankDelta(o.delta, {title: `지난번 방문 때보다 ${fmt.int(Math.abs(o.delta))}칸 ${o.delta > 0 ? "오름" : "내림"} (묶음 안 잔고 수익률 순위)`}) : null;
  let ret;
  if (co) {
    ret = h("span", {class: "ret rk-co", title: "딥시크 금액 숨김 설정: 수익률·순위 없이 개수만"}, "개수만");
  } else {
    const sv = o.spark ? o.spark(a) : null;
    ret = h("span", {class: ["ret", "num", fmt.tone(r, t)]}, sv ? h("span", {class: "k4-spark rk-spark"}, sv) : null, t);
    const mv = o.moved && o.moved.get(a.id);
    if (mv && o.flash) o.flash.push([ret, mv]);
  }
  const label = `${o.rk == null ? "" : `${o.rk}위 `}${LK.stratKo(a.name)} ${tfKo(a.tf)}${a.role !== "cand" ? ` ${ROLE_SHORT[a.role] || ""}` : ""} · ` +
    `${co ? "금액 숨김" : `잔고 수익률 ${t}`} · 거래 ${fmt.int(a.trades)}번${a.trades < SMALL ? " · 표본 적음" : ""}${a.bust ? " · 파산" : ""}`;
  return h("a", {class: ["k4-row", "rk-row", co ? "co" : "", a.role === "flip" ? "flip" : "", a.trades < SMALL ? "thin" : ""],
    href: `#/account/${encodeURIComponent(a.id)}`, role: "listitem", title: a.id, "aria-label": label, dataset: {id: a.id}},
  h("span", {class: "rk"}, o.rk == null ? "—" : fmt.int(o.rk), rkd),
  h("span", {class: "lname"}, nameBits(a, {role: o.role})), ret, h("span", {class: "meta"}, meta));
}

// ---------------------------------------------------------------- 상위 5 / 하위 5
/**
 * topBottom() -> {el, set(o)}: the best and the worst five of the 묶음 by 잔고 수익률 (one list when it has 10 or
 * fewer). o: {label, rk: ranking(), row(a, rank) -> el, hidRow(a) -> el}. Below: how many wait for their first trade and
 * how many are hidden (count only). A 묶음 whose accounts are all hidden lists them count-only, by name.
 */
export function topBottom() {
  const body = h("div", {class: "k4-tb rk-tb"});
  const foot = h("div", {class: "rk-tbfoot"});
  const el = h("div", {class: "stack tight"}, body, foot);
  function col(title, sub, rows) {
    return h("div", {class: "k4-tbcol"}, h("div", {class: "k4-tbh"}, h("b", null, title), h("span", null, sub)), h("div", {role: "list"}, rows));
  }
  return {
    el,
    set(o) {
      const {shown, waiting, hid} = o.rk;
      const n = shown.length;
      if (!n && hid.length) {
        // every account of the 묶음 is hidden: no ranking; the ones in a position now (count only), the rest in 전체 목록
        // (설치 뒤 진입만: the ones whose position was entered before the install are not "없음", they are hidden)
        const open = hid.filter((a) => openAfter(a)), pre = hid.filter((a) => openBefore(a));
        put(body, open.length ? col(o.label, `지금 포지션 있는 ${fmt.int(open.length)}개${afterOn() ? " (설치 뒤만)" : ""} · 개수만 (금액 숨김)`, open.map((a) => o.hidRow(a)))
          : h("p", {class: "k4-wait"}, pre.length
            ? `${o.label} ${fmt.int(hid.length)}개 · 지금 열린 포지션 ${fmt.int(pre.length)}개는 모두 설치 전 진입 ('설치 뒤 진입만'에서 숨김)`
            : `${o.label} ${fmt.int(hid.length)}개 · 지금 열린 포지션 없음`));
      }
      else if (!n) put(body, h("p", {class: "k4-wait"}, waiting.length ? "아직 순위를 매길 계좌가 없습니다 (첫 거래 뒤부터)" : "계좌가 없습니다"));
      else if (n <= 10) put(body, col(o.label, `전체 ${fmt.int(n)}개`, shown.map((a, i) => o.row(a, i + 1))));
      else {
        put(body, col(o.label, "상위 5", shown.slice(0, 5).map((a, i) => o.row(a, i + 1))),
          col(o.label, "하위 5", shown.slice(-5).map((a, i) => o.row(a, n - 4 + i))));
      }
      const lines = [];
      if (waiting.length) lines.push(`아직 거래 없는 계좌 ${fmt.int(waiting.length)}개 · 첫 거래 뒤부터 순위`);
      if (hid.length) lines.push(n ? `딥시크 ${fmt.int(hid.length)}개는 금액 숨김 설정이라 순위 없이 개수만 (전체 목록 맨 뒤)`
        : `딥시크 금액 숨김 설정: 잔고·수익률이 없어 순위를 매기지 않습니다 · ${fmt.int(hid.length)}개 모두 아래 전체 목록에 (이름 순)`);
      put(foot, lines.map((x) => h("p", {class: "k4-wait"}, x)));
    },
  };
}

// ---------------------------------------------------------------- the full list: filters, sort, 10 per page
export const SORTS = [
  {id: "ret", label: "잔고 수익률", key: (a, d) => -(walletRet(a, d) ?? -1e9)},
  {id: "mean", label: "한 번 평균", key: (a) => -(a.mean_ret ?? -1e9)},
  {id: "trades", label: "거래 수", key: (a) => -(a.trades || 0)},
  {id: "win", label: "승률", key: (a) => -(a.trades ? a.wins / a.trades : -1)},
  {id: "dd", label: "낙폭 작은 순", key: (a) => (a.max_dd == null ? 1e9 : a.max_dd)},
  {id: "name", label: "이름", key: (a) => `${LK.stratKo(a.name)} ${a.tf}`},
];
/** The search text of an account: Korean name, code, timeframe, role, kind, id. */
export const searchText = (a) => `${LK.stratKo(a.name)} ${a.name} ${tfKo(a.tf)} ${a.tf} ${ROLE_SHORT[a.role] || ""} ${kindKo(a.kind)} ${a.id}`.toLowerCase();
/** f: {q, tf, kind, style} -> the rows that match. */
export function filterRows(rows, f = {}) {
  const q = String(f.q || "").trim().toLowerCase();
  return rows.filter((a) => (!f.tf || f.tf === "all" || a.tf === f.tf) && (!f.kind || f.kind === "all" || a.kind === f.kind)
    && (!f.style || f.style === "all" || (LK.pickMeta((LK.pickOf(a) || a).id) || {}).style === f.style)
    && (!q || searchText(a).includes(q)));
}
/** Sort by one of SORTS: the ranked rows first, then the ones waiting for their first trade (no rank yet), then the
 *  hidden (count-only) rows by name; ties keep the 잔고 수익률 rank. rank: Map(id -> rank) of the ranked rows. */
export function sortRows(rows, sortId, d, rank) {
  const s = SORTS.find((x) => x.id === sortId) || SORTS[0];
  const has = (a) => !!(rank && rank.has(a.id));
  const rk = (a) => (has(a) ? rank.get(a.id) : 1e6);
  const by = (x, y) => {
    const p = s.key(x, d), q = s.key(y, d);
    const c = typeof p === "string" ? p.localeCompare(q, "ko") : p - q;
    return c || rk(x) - rk(y) || (x.id < y.id ? -1 : 1);
  };
  const named = (x, y) => `${LK.stratKo(x.name)} ${x.tf} ${x.id}`.localeCompare(`${LK.stratKo(y.name)} ${y.tf} ${y.id}`, "ko");
  const ranked = rows.filter((a) => !hidden(a, d) && (has(a) || !rank)).sort(by);
  const waiting = rank ? rows.filter((a) => !hidden(a, d) && !has(a)).sort(s.id === "ret" ? named : by) : [];
  return ranked.concat(waiting, rows.filter((a) => hidden(a, d)).sort(named));
}

/**
 * listFilters({kinds, memo, onChange}) -> {el, value(), setKinds(on)}: the search box, the 봉 switch, the 종류 switch
 * (only for the mixed 묶음), 성격 and 정렬 (the sort applies to the card list; the table sorts by its heads).
 */
export function listFilters(o = {}) {
  const st = {q: "", tf: "all", kind: "all", style: "all", sort: local.get("rank-sort", "ret")};
  if (!SORTS.some((s) => s.id === st.sort)) st.sort = "ret";
  const fire = () => o.onChange && o.onChange();
  const search = h("input", {class: "search rk-search", type: "search", placeholder: "이름·코드 찾기 (예: 도지, F10, 동전)", "aria-label": "순위표에서 계좌 찾기",
    autocomplete: "off", enterkeyhint: "search"});
  search.addEventListener("input", () => { st.q = search.value; fire(); });
  const seg = (opts, key, label) => {
    const el = h("div", {class: ["seg", "rk-seg"], role: "tablist", "aria-label": label});
    const btns = opts.map((x) => h("button", {type: "button", role: "tab", "aria-selected": String(x.id === st[key]), dataset: {id: x.id},
      onclick: () => { st[key] = x.id; for (const b of btns) b.setAttribute("aria-selected", String(b.dataset.id === x.id)); fire(); }}, x.label));
    el.append(...btns);
    return el;
  };
  const tfSeg = seg([{id: "all", label: "모든 봉"}, ...TFS.map((t) => ({id: t, label: tfKo(t)}))], "tf", "봉 고르기");
  const kindSeg = seg([{id: "all", label: "모든 종류"}, {id: "core", label: "기존 36"}, {id: "ds", label: "딥시크"}], "kind", "종류 고르기");
  const styleSel = h("select", {class: "select", "aria-label": "성격"}, [{id: "all", label: "모든 성격"}, ...Object.entries(STYLE_KO).map(([k, v]) => ({id: k, label: v}))]
    .map((x) => h("option", {value: x.id}, x.label)));
  styleSel.addEventListener("change", () => { st.style = styleSel.value; fire(); });
  const sortSel = h("select", {class: "select", "aria-label": "정렬"}, SORTS.map((s) => h("option", {value: s.id, selected: s.id === st.sort || null}, s.label)));
  sortSel.addEventListener("change", () => { st.sort = sortSel.value; local.set("rank-sort", st.sort); fire(); });
  const sortBox = h("label", {class: "rk-sort"}, h("span", null, "정렬"), sortSel);
  const kindBox = h("span", {class: "rk-kindbox"}, kindSeg);
  const el = h("div", {class: "stack tight rk-filters"}, search,
    h("div", {class: "rk-frow"}, tfSeg, kindBox, h("label", {class: "rk-sort"}, h("span", null, "성격"), styleSel), sortBox));
  return {
    el,
    value: () => ({...st}),
    /** Show the 종류 switch (a 묶음 that mixes 기존 36 and 딥시크) and the sort (card view only). */
    show({kinds, sort}) {
      kindBox.hidden = !kinds;
      if (!kinds && st.kind !== "all") { st.kind = "all"; for (const b of kindSeg.querySelectorAll("button")) b.setAttribute("aria-selected", String(b.dataset.id === "all")); }
      sortBox.hidden = !sort;
    },
  };
}

/** The caption under 상위·하위: what the arrows and the small lines mean (and how many of the top 10 stayed). */
export function motionNote(base, shown, opts = {}) {
  const parts = [];
  if (base && shown.length) {
    parts.push(`▲▼ = ${fmt.ago(base.ts)} 이 화면을 봤을 때보다 묶음 안 잔고 수익률 순위가 오르고 내린 칸 수`);
    if (shown.length >= 20) {
      const ids = shown.map((a) => a.id).filter((id) => Number.isFinite(base.v[id]));
      const was = Object.entries(K4.ranksOf(Object.fromEntries(ids.map((id) => [id, base.v[id]])))).filter(([, r]) => r <= 10).map(([id]) => id);
      const now = new Set(shown.slice(0, 10).map((a) => a.id));
      parts.push(`그때 상위 10 중 지금도 상위 10: ${fmt.int(was.filter((id) => now.has(id)).length)}개`);
    }
  } else if (shown.length) parts.push("▲▼ 순위 변화는 다음 방문부터 보입니다 (이 기기에 지금 순위를 기억해 둡니다)");
  const spark = opts.sparks && shown.length ? h("span", {class: "rk-sparknote"}, `${parts.length ? " · " : ""}작은 선 = 시작부터 지금까지 잔고 흐름 (닫힌 거래마다)`) : null;
  if (!parts.length && !spark) return null;
  return h("p", {class: "note rk-monote"}, parts.join(" · "), spark, base ? " · 짧은 기간 순위는 운으로도 크게 움직입니다 (판정 아님)." : "");
}
