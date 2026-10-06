// 분석 › 장세 스위치 (regime5y, the 36 only): does a locked strategy lose mainly because it runs in the wrong kind of
// market? Pre-registered in docs/regime5y.md; descriptive (설명용, 판정 아님); the locked rules do not change.
//   GET /api/v4/regime5y        the 5-year study as committed (paperbot/dash/data/regime5y.json, dash/more/regime5y.py)
//   GET /api/v4/regime5y/live   the paper run's own closed trades by regime (a filling bar until the 36 have enough)
// Cards: the head, the caveat, the honest headline (from the file's counts, never typed in), the four regimes, one row
// per strategy x timeframe (survivors highlighted, everything else 차이 없음 / 표본 적음 / 규칙 없음; tap for the regime
// table and the walk-forward check), the paper-forward table. Coin flips are 참고 (refNote); money has its caption.
import {h, ui, fmt, put, motion} from "../core/pb.js";
import {viewHead, dimSeg, progressBar} from "./analysis-kit.js";

const RK = ["trend", "range", "shock", "normal"];
const RKO = {trend: "추세장", range: "횡보장", shock: "급변장", normal: "보통", unknown: "모름"};
const pc = (x, d = 1) => (x == null ? "—" : fmt.pct(x, d));
const pp = (x) => (x == null ? "—" : `${fmt.num(x * 100, 1, true)}%p`);
const ASSUME_5Y = "5년 과거 시험 · 평균 = 거래당 순 ROE · 손익(USDT) = 30일마다 새 $5,000 계좌들의 합";

/** The median over cells of each regime's 5-year mean net ROE (cells with at least ``min`` trades in that regime). */
export function regimeMedians(cells, min = 30) {
  const out = {};
  for (const k of RK) {
    const v = (cells || []).map((c) => ((c.regimes || {}).all || {})[k]).filter((r) => r && r[0] >= min && r[2] != null).map((r) => r[2]).sort((a, b) => a - b);
    out[k] = v.length ? {n: v.length, med: v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2} : null;
  }
  return out;
}

/** The word a cell gets: survivor / nodiff / small / norule / notrade. */
export function cellWord(c) {
  const t = c.test || {};
  if (t.survivor) return "survivor";
  if (t.status === "tested") return "nodiff";
  if (t.status === "small") return "small";
  return ((c.total || {}).all || [0])[0] ? "norule" : "notrade";
}
const WORD = {survivor: ["남음", "acc"], nodiff: ["차이 없음", ""], small: ["표본 적음", "thin"], norule: ["규칙 없음", ""], notrade: ["거래 없음", ""]};
const WORD_TITLE = {
  survivor: "동전 봇보다 장세 차이가 뚜렷했고, 여러 번 시험한 것을 보정한 뒤에도 남았고, 확인 A와 B 각각에서도 같은 쪽이었습니다",
  nodiff: "확인 기간에 장세 차이가 동전 봇보다 뚜렷하다고 볼 수 없었습니다",
  small: "확인 기간에 고른 장세 안팎 거래가 각각 20건이 안 됐습니다",
  norule: "고르는 기간에 거래가 30건 이상인 장세 중 평균보다 나은 장세가 없었거나, 네 장세가 다 골라졌습니다 (그러면 스위치가 아님)",
  notrade: "5년 동안 이 봉에서 거래가 없었습니다",
};

/** The honest one-line headline from the file's own counts and the regime medians. */
export function headline(head, med) {
  const hd = head || {};
  const vals = RK.map((k) => med[k] && med[k].med).filter((v) => v != null);
  const allNeg = vals.length === RK.length && vals.every((v) => v < 0);
  const spread = vals.length ? Math.max(...vals) - Math.min(...vals) : null;
  const lines = [];
  if (!hd.survivors && !hd.stops_losing) {
    lines.push("5년 자료에서는 '맞지 않는 장에서 돌아서 잃는다'는 설명이 뒷받침되지 않았습니다. 맞는 장에서만 켜는 스위치로도 손실이 멈추지 않았습니다.");
  } else if (hd.survivors) {
    lines.push(`${fmt.int(hd.survivors)}칸에서 장세 차이가 동전 봇보다 뚜렷하게 남았습니다. 그래도 설명용이고, 잠긴 규칙은 그대로입니다.`);
  } else {
    lines.push(`스위치를 켜고 확인 두 기간 모두 손실이 아니었던 칸이 ${fmt.int(hd.stops_losing)}개 있지만, 동전 봇보다 뚜렷한 장세 차이는 아니었습니다.`);
  }
  if (allNeg && spread != null && spread < 0.01) {
    lines.push(`네 장세 모두 거래당 평균 ${pc(Math.max(...vals))} ~ ${pc(Math.min(...vals))}로 비슷하게 잃었습니다. 어느 장에서 돌려도 비슷했다는 뜻입니다.`);
  }
  return lines;
}

function rChips(rule) {
  if (!rule || !rule.length) return h("span", {class: "muted rg-norule"}, "—");
  return h("span", {class: "rg-chips"}, rule.map((k) => h("span", {class: ["rg-chip", k]}, RKO[k] || k)));
}

/** One cell's detail: the 5-year regime table, the pick, the walk-forward check. */
function detail(c, doc) {
  const all = (c.regimes || {}).all || {};
  const rule = c.rule || [];
  const keys = [...RK, ...(all.unknown ? ["unknown"] : [])].filter((k) => all[k]);
  const rows = keys.map((k) => ({k, r: all[k]}));
  const tbl = rows.length ? ui.table([
    {label: "장세", l: true, get: (x) => h("span", {class: "rg-two l"}, RKO[x.k], rule.includes(x.k) ? h("b", {class: "rg-in"}, "스위치 켬") : null)},
    {label: "거래", get: (x) => h("span", {class: "rg-two"}, `${fmt.int(x.r[0])}건`, h("small", {class: "num muted"}, `승률 ${fmt.pct(x.r[1], 0, false)}`))},
    {label: "평균 · 손익", get: (x) => h("span", {class: "rg-two"}, h("span", {class: fmt.tone(x.r[2])}, pc(x.r[2])),
      h("small", {class: ["num", fmt.tone(x.r[3])]}, fmt.money(x.r[3], true)))},
  ], rows) : h("p", {class: "muted"}, "5년 동안 거래가 없었습니다.");
  const pick = ((c.regimes || {}).pick) || {};
  const pickLine = rule.length
    ? `고르는 기간(2021-07 ~ 2022-12) 거래당 평균 ${pc(c.pick_mean)}보다 나았던 장세 (각 30건 이상): ${rule.map((k) => `${RKO[k]} ${pc((pick[k] || [])[2])}`).join(", ")}. 이 장세에서만 들어가는 것이 이 칸의 스위치입니다.`
    : WORD_TITLE[cellWord(c)];
  const kids = [h("h3", {class: "an-sub"}, "5년 장세별 (진입한 봉의 장세)"), tbl, ui.assume("closed", ASSUME_5Y),
    h("h3", {class: "an-sub"}, "스위치 고르기 · 2021-07 ~ 2022-12만 봄"), h("p", {class: "rg-say"}, pickLine)];
  const sw = c.switch;
  if (sw) {
    const t = c.test || {}, per = t.per || {};
    const pr = (k) => (doc.periods || []).find((p) => p.key === k) || {ko: k};
    kids.push(h("h3", {class: "an-sub"}, "손대지 않은 두 기간에서 확인"),
      h("div", {class: "rg-wf", role: "list"}, ["a", "b"].map((k) => h("div", {class: "rg-wfp", role: "listitem"},
        h("b", {class: "rg-wfk"}, pr(k).ko),
        h("div", {class: "rg-wfc"},
          wfCell("그대로", sw[k].base),
          wfCell("스위치 켬", sw[k].switch, true),
          wfCell("동전 봇 + 같은 스위치 (참고)", sw[k].flip_switch, false, "씨앗 3개 평균"))))),
      h("p", {class: "rg-say"}, "고른 장세 안 − 밖, 거래당 평균 차이: ",
        ["a", "b"].map((k, i) => [i ? " · " : "", `${pr(k).ko.split(" ")[1]} 매매법 ${pp((per[k] || {}).s)}, 동전 봇 ${pp((per[k] || {}).f)}`])),
      h("p", {class: ["rg-verdict", t.survivor ? "on" : ""]}, t.survivor
        ? `남음: 동전 봇보다 뚜렷했고, ${fmt.int((doc.head || {}).tested || 0)}칸을 같이 시험한 것을 보정한 뒤에도 남았고, 두 기간 각각에서 같은 쪽이었습니다.`
        : t.status === "tested" ? "차이 없음: 이 정도 차이는 동전 봇에도 생기거나, 여러 번 시험하면 우연으로도 나오는 크기입니다."
          : WORD_TITLE[cellWord(c)]),
      ui.assume("closed", ASSUME_5Y));
  }
  return h("div", {class: "rg-detail"}, kids);
}
/** One account of the walk-forward check: "평균 −3.1%" with "1,234건 · −12,345.67" under it. */
function wfCell(label, r, hi, note) {
  const body = !r || !r[0] ? h("span", {class: "muted"}, "거래 없음")
    : [h("b", {class: ["num", fmt.tone(r[2])]}, `평균 ${pc(r[2])}`),
      h("small", {class: "num muted"}, `${fmt.int(r[0])}건${note ? ` (${note})` : ""} · `, h("span", {class: fmt.tone(r[3])}, `${fmt.money(r[3], true)} USDT`))];
  return h("div", {class: ["rg-wfa", hi ? "hi" : ""]}, h("span", {class: "rg-wfl"}, label), body);
}

function cellRow(c, open, toggle, doc) {
  const w = cellWord(c), [word, cls] = WORD[w];
  const tot = (c.total || {}).all || [0];
  const btn = h("button", {class: ["rg-row", w === "survivor" ? "win" : ""], type: "button", "aria-expanded": String(open), onclick: toggle},
    ui.acctLabel({kind: "strategy", strategy: c.s, timeframe: c.tf}),
    h("span", {class: "rg-mid"}, rChips(c.rule)),
    h("span", {class: "rg-end"}, ui.pill(word, cls, WORD_TITLE[w]),
      h("small", {class: ["num", fmt.tone(tot[2])]}, tot[0] ? `5년 평균 ${pc(tot[2])} · ${fmt.int(tot[0])}건` : "")));
  return h("div", {class: "rg-item", role: "listitem"}, btn, open ? detail(c, doc) : null);
}

function listCard(doc) {
  const cells = (doc.cells || []).slice().sort((a, b) => {
    const o = {survivor: 0, nodiff: 1, small: 2, norule: 3, notrade: 4};
    return o[cellWord(a)] - o[cellWord(b)] || ((a.test || {}).p ?? 1) - ((b.test || {}).p ?? 1);
  });
  const opened = new Set();
  const pg = ui.pager({size: 10, empty: "맞는 칸이 없습니다",
    row: (c) => cellRow(c, opened.has(c.s + "@" + c.tf), () => { const k = c.s + "@" + c.tf; opened.has(k) ? opened.delete(k) : opened.add(k); pg.rerender(); }, doc)});
  const tf = dimSeg("rg-tf", [{id: "all", label: "전체"}, {id: "15m", label: "15분"}, {id: "30m", label: "30분"}, {id: "1h", label: "1시간"}, {id: "4h", label: "4시간"}], "all", () => apply(), true);
  const show = dimSeg("rg-show", [{id: "all", label: "모두"}, {id: "rule", label: "스위치 있는 칸"}, {id: "win", label: "남은 칸"}], "all", () => apply(), true);
  function apply() {
    const t = tf.get(), s = show.get();
    pg.set(cells.filter((c) => (t === "all" || c.tf === t) && (s === "all" || (s === "rule" ? !!c.rule : cellWord(c) === "survivor"))));
  }
  apply();
  const n = (w) => cells.filter((c) => cellWord(c) === w).length;
  return ui.card({plate: "매매법마다", sub: "칸을 누르면 장세별 표와 확인 결과"},
    h("div", {class: "rg-filters"}, tf.el, show.el),
    h("p", {class: "an-note"}, `남음 ${fmt.int(n("survivor"))} · 차이 없음 ${fmt.int(n("nodiff"))} · 표본 적음 ${fmt.int(n("small"))} · 규칙 없음 ${fmt.int(n("norule"))} · 거래 없음 ${fmt.int(n("notrade"))} (모두 ${fmt.int(cells.length)}칸)`),
    pg.el);
}

/** " · 달러 손익(30일 계좌 합)으로는 n칸": a per-trade mean above 0 can still lose dollars when the bigger trades lose. */
function usdNote(n) {
  return n == null ? "" : ` · 달러 손익(30일 계좌들의 합)으로 둘 다 플러스는 ${fmt.int(n)}칸`;
}

function headCard(doc) {
  const hd = doc.head || {}, med = regimeMedians(doc.cells);
  const lines = headline(hd, med);
  return ui.card({plate: "한 줄 결론", sub: "5년 · 확인 두 기간", cls: "rg-headline"},
    lines.map((l, i) => h(i ? "p" : "h2", {class: i ? "rg-say" : "rg-big"}, l)),
    h("div", {class: "rg-stats"},
      ui.stat("남은 칸", `${fmt.int(hd.survivors || 0)} / ${fmt.int(hd.tested || 0)}`, "동전 봇보다 뚜렷 · 보정 후 · 두 기간 모두"),
      ui.stat("스위치 켜고 손실 멈춤", `${fmt.int(hd.stops_losing || 0)} / ${fmt.int(hd.with_rule || 0)}`, `확인 A·B 둘 다 거래당 평균 플러스${usdNote(hd.stops_losing_usd)}`),
      ui.stat("동전 봇 + 같은 스위치", `${fmt.int(hd.flip_stops_losing || 0)} / ${fmt.int(hd.with_rule || 0)}`, `참고: 아무 데나 들어가도 같은 스위치로${usdNote(hd.flip_stops_losing_usd)}`),
      ui.stat("스위치 없이도 플러스", `${fmt.int(hd.base_positive_both || 0)} / ${fmt.int(hd.cells || 0)}`, `확인 A·B 둘 다 거래당 평균 플러스${usdNote(hd.base_positive_both_usd)}`)),
    hd.p05 != null ? h("p", {class: "an-note"}, `시험한 ${fmt.int(hd.tested || 0)}칸 중 한쪽 p < 0.05는 ${fmt.int(hd.p05)}칸입니다. 아무 차이가 없어도 우연만으로 약 ${fmt.num((hd.tested || 0) * 0.05, 1)}칸은 나오는 수라서, 여러 번 시험한 것을 보정(BH)하면 ${fmt.int(hd.bh_pass || 0)}칸이 남습니다.`) : null,
    h("h3", {class: "an-sub"}, "장세별 거래당 평균 순 ROE (칸들의 가운데 값)"),
    h("div", {class: "rg-meds"}, RK.map((k) => h("span", {class: ["rg-med", k]}, h("b", null, RKO[k]),
      h("span", {class: ["num", fmt.tone(med[k] && med[k].med)]}, med[k] ? pc(med[k].med) : "—"),
      h("small", {class: "muted"}, med[k] ? `${fmt.int(med[k].n)}칸` : "")))),
    h("p", {class: "an-note"}, "ROE = 증거금 대비 손익 (수수료·펀딩·슬리피지 뺀 순). 가운데 값 = 그 장세에서 30건 이상 거래한 칸들의 평균을 줄 세운 가운데."));
}

function defsCard(doc) {
  const d = doc.defs || {}, sh = doc.share || {};
  const avg = (k) => { const v = Object.values(sh).map((x) => x[k]).filter((x) => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  const rows = [
    ["shock", `ATR%(평균 진폭 ÷ 가격)가 그 코인·그 봉의 지난 1년 중 위 ${fmt.int((1 - (d.vol_q || 0.8)) * 100)}%`],
    ["trend", `ADX(${d.adx_n || 14}) ${d.adx_trend || 25} 이상, 그리고 EMA${d.ema_n || 50}이 ${d.slope_bars || 10}봉 동안 ATR의 ${fmt.num(d.slope_min || 0.5, 1)}배 넘게 움직임`],
    ["range", `ADX(${d.adx_n || 14}) ${d.adx_range || 20} 미만 (방향이 약함)`],
    ["normal", "나머지"],
  ];
  return ui.card({plate: "장세 4가지", sub: "그 봉 종가까지의 자료만으로 · 위에서 먼저 맞는 것"},
    h("div", {class: "rg-defs", role: "list"}, rows.map(([k, t]) => h("div", {class: "rg-def", role: "listitem"},
      h("span", {class: ["rg-chip", k]}, RKO[k]), h("span", {class: "rg-def-t"}, t),
      h("small", {class: "num muted"}, avg(k) != null ? `봉의 ${fmt.pct(avg(k), 0, false)}` : "")))),
    h("p", {class: "an-note"}, "거래의 장세 = 신호가 난 봉의 장세 (들어가는 건 다음 봉 시가라 미래 자료를 쓰지 않습니다). 봉 비율 = 2021-07부터 네 봉 평균."));
}

function caveatCard() {
  return ui.card({plate: "먼저 읽어 주세요", cls: "rg-caveat"},
    h("p", {class: "an-warn"}, ui.pill("설명용, 판정 아님", "ref"), " 잠긴 매매법 36개의 규칙은 이 결과로 바뀌지 않습니다. 지금 도는 모의 계좌도 그대로입니다."),
    h("ul", {class: "rg-list"},
      h("li", null, "지나고 나서 가장 좋았던 장세를 고르면 과최적화입니다 (어떤 숫자든 좋아 보이게 만들 수 있음). 그래서 스위치는 2021-07 ~ 2022-12에서만 고르고, 2023-24와 2025-26은 손대지 않고 확인만 했습니다."),
      h("li", null, "같은 스위치를 아무 데나 들어가는 동전 봇에도 달아 봤습니다. 동전 봇도 똑같이 좋아지면 매매법 덕이 아니라 그 장세 자체의 효과입니다."),
      h("li", null, "36개는 같은 5년 자료로 골라진 매매법이라 5년 숫자는 원래 좋게 보이는 쪽으로 치우칩니다. 배수(50·40·30·20배)는 v4 비율대로 무작위로 정했습니다."),
      h("li", null, "규칙과 숫자는 결과를 보기 전에 docs/regime5y.md에 적어 두었습니다.")));
}

/** The paper run's own trades by regime (a filling bar until the 36 have enough). */
function liveCard(env) {
  const body = h("div", {class: "stack tight"}, motion.shimmer(3));
  const card = ui.card({plate: "모의 v4 거래 · 장세별", sub: "기존 36 vs 동전 봇 (참고)"}, body);
  const ctx = env.ctx;
  let tries = 0;
  const load = async () => {
    let d;
    try { d = await ctx.api("/api/v4/regime5y/live"); } catch (e) {
      if (ctx.alive() && card.isConnected) put(body, ui.errorBox(e, load));
      return;
    }
    if (!ctx.alive() || !card.isConnected) return;
    if (d && d.pending) {
      put(body, h("p", {class: "muted"}, d.note || "서버가 계산하는 중입니다."), motion.shimmer(2));
      if (++tries < 20) ctx.timeout(load, 3000);
      return;
    }
    put(body, ...liveBody(d || {}, env));
  };
  load();
  return card;
}
function liveBody(d, env) {
  if (d.error) return [h("p", {class: "muted"}, String(d.error))];
  const need = d.need || 100, n = d.trades || 0, fn = d.flip_trades || 0;
  if (d.waiting || !d.rows) {
    return [progressBar(`기존 36 끝난 거래 ${fmt.int(need)}건 필요`, `지금 ${fmt.int(n)}건 · 동전 봇 ${fmt.int(fn)}건`, Math.min(1, n / need)),
      h("p", {class: "an-note"}, "막대는 실험 시작부터 끝난 실제 거래 수입니다. 다 차면 같은 공식으로 장세를 나눠 5년 숫자 옆에 놓습니다. 그 전에는 위 5년 결과만 봐 주세요.")];
  }
  const min = d.cell_min || 20;
  const rows = (d.rows || []).filter((r) => r.key !== "unknown" || (r.group || [0])[0] || (r.coin_flips || [0])[0]);
  const unk = (d.rows || []).find((r) => r.key === "unknown");
  return [
    ui.table([
      {label: "장세", l: true, get: (r) => r.ko},
      {label: "기존 36", get: (r) => liveCell(r.group, min)},
      {label: "동전 봇", get: (r) => liveCell(r.coin_flips, min)},
    ], rows),
    ui.assume("closed"),
    h("p", {class: "an-note"}, `기존 36 끝난 거래 ${fmt.int(n)}건 · 동전 봇 ${fmt.int(fn)}건. 장세는 바이낸스 공개 봉 최근 ${fmt.int(d.candles_n || 1500)}개로 같은 공식을 계산했고, 급변장 기준선은 ${d.vol_q_asof || "저장본 마지막 날"}까지 1년입니다.`,
      unk && (unk.group || [0])[0] ? ` 봉 자료 밖이라 장세를 모르는 거래 ${fmt.int(unk.group[0])}건은 '모름'에 있습니다.` : "",
      (d.fetch_failed || []).length ? ` 봉을 받지 못한 곳: ${d.fetch_failed.join(", ")}.` : ""),
    ui.refNote(env.verdictTs),
  ];
}
function liveCell(r, min) {
  if (!r || !r[0]) return h("span", {class: "muted"}, "—");
  return h("span", {class: "rg-two"}, h("span", null, `${fmt.int(r[0])}건 · 승률 ${fmt.pct(r[1], 0, false)}`, " ", ui.smallSample(r[0], min)),
    h("small", {class: "num"}, h("span", {class: fmt.tone(r[2])}, `평균 ${pc(r[2])}`), " · ", h("span", {class: fmt.tone(r[3])}, fmt.money(r[3], true))));
}

// ---------------------------------------------------------------- 장세 스위치 (/api/v4/regime5y)
export function regime(d, env) {
  const hd = d.head || {};
  const per = (d.periods || []).map((p) => p.ko).join(" · ");
  const out = [viewHead({plate: "장세 스위치", q: "잃는 게 '맞지 않는 장'에서 돌아서일까?",
    meta: `5년 과거 시험 · 기존 36 × 15분·30분·1시간·4시간 = ${fmt.int(hd.cells || 0)}칸 · 30일마다 새 $5,000 계좌`, at: d.generated_at,
    read: "장을 추세장·횡보장·급변장·보통 넷으로 나누고, 매매법마다 '이 장세에서만 들어가는' 스위치를 앞 기간에서 골라 뒤 두 기간에서 확인했습니다. 같은 스위치를 단 동전 봇보다 나아야 매매법 덕입니다.",
    warn: [per ? h("p", {class: "an-meta"}, per) : null]})];
  if (d.unavailable) { out.push(ui.card({plate: "장세 스위치"}, h("p", {class: "muted"}, d.note || "준비 중입니다."))); return out; }
  out.push(caveatCard(), headCard(d), defsCard(d), listCard(d), liveCard(env),
    h("p", {class: "an-note an-foot"}, `장세 스위치: 기존 36 · 5년 과거 시험 + 모의 v4 · ${d.label || "설명용, 판정 아님"} · 사전 등록 ${d.prereg || "docs/regime5y.md"}`));
  return out;
}
