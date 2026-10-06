// #/compare[?ids=a,b,c,d] — 매매법 비교 (conv-b, owners 10/06: "두세 개를 나란히 놓고 보고 싶다"). 2-4 strategies or
// accounts side by side:
//   고르기       the picks (each with its colour and line style, ✕ to take it out), a search box over the 36, DeepSeek,
//                the reel and every account, the starred ones one tap away; '＋ 비교에 추가' on a strategy page, an
//                account page and the side panel adds here too (core/cmp.js, per device; ?ids= in the address wins)
//   채워지는 중  while any pick has under 30 closed trades: one filling bar per pick (analysis-kit waitCard)
//   합친 곡선    each pick's summed realized balance after every closed trade, as a return from its start, on one chart
//   주요 숫자    수익률, 합친 곡선 최대 낙폭, 계좌 하나의 가장 깊은 낙폭, 거래 수, 승률, 손익비, 수익 팩터, 동전 봇 순위 (참고),
//                지금 포지션, 파산 — one column per pick
//   봉별로       the same picks per timeframe (return, trades, win rate, the gap to that timeframe's coin-flip median)
//   5년 시험     the research numbers the strategy page already shows (more/vs5y.five_year), per timeframe
// Data: /api/v4/compare (dash/more/compare.py; background + cached, {pending} answered with a retry in 3 s) and the
// shared board for names. HONESTY: DeepSeek picks are compared by counts only on this mixed screen (trades, open
// positions; no money, rates, curve or 5-year return; the server sends nothing else); coin flips are the yardstick,
// never a pick (their place is the 동전 봇 순위 row, 참고 with refNote); late-started extras get no coin-flip or
// 5-year side; every number is labelled 설명용, 판정 아님; small samples say 표본 적음.
import {h, put, ui, fmt, fav, cmp, makeChart, tok, motion} from "../core/pb.js";
import {progressBar} from "./analysis-kit.js";

const SMALL = 30;
const DASH = [0, 2, 3, 1];          // lightweight-charts line styles: solid, dashed, large dashed, dotted (never colour alone)
const OWN = new Set(["strategy", "ds200", "reel"]);
const colour = (i) => `var(--pick-${i + 1})`;

let current = null;

/** The pickable things from the board: strategies (their own timeframe accounts) and accounts (no coin flips). */
export function pickables(board) {
  const rows = (board && board.accounts) || [];
  const strat = new Map();
  for (const a of rows) {
    if (OWN.has(a.kind) && !strat.has(a.strategy)) {
      strat.set(a.strategy, {id: a.strategy, kind: "strategy", label: fmt.stratKo(a.strategy), sub: `매매법 · ${fmt.GROUP_KO[fmt.groupOf(a)] || ""}`});
    }
  }
  const accts = rows.filter((a) => a.kind !== "random").map((a) => ({id: a.account_id, kind: "account", label: fmt.acctName(a),
    sub: `계좌 · ${fmt.GROUP_KO[fmt.groupOf(a)] || ""}`}));
  return [...strat.values(), ...accts];
}
/** Up to n pickables matching a query (name or code, lower case), strategies first. */
export function findPicks(items, q, taken, n = 8) {
  const k = String(q || "").trim().toLowerCase();
  if (!k) return [];
  return items.filter((x) => !taken.includes(x.id) && (x.label.toLowerCase().includes(k) || x.id.toLowerCase().includes(k))).slice(0, n);
}
/** A pick's display name from the board (a strategy's Korean name, an account's name), else its id. */
export function pickName(id, board) {
  if (String(id).includes("@")) {
    const a = ((board && board.accounts) || []).find((x) => x.account_id === id);
    return a ? fmt.acctName(a) : fmt.idName(id);
  }
  return fmt.stratKo(id);
}
/** [{time (s), value}] strictly increasing from ms times and returns (the server sends them in time order; a point in
 *  the same second as the one before, or out of order, replaces that one's value); a missing time or value is skipped. */
export function lineData(t, v) {
  const out = [];
  for (let i = 0; i < (t || []).length; i++) {
    if (t[i] == null) continue;
    const s = Math.floor(Number(t[i]) / 1000), y = v[i];
    if (!Number.isFinite(s) || y == null || !Number.isFinite(y)) continue;
    if (out.length && s <= out[out.length - 1].time) { out[out.length - 1].value = y; continue; }
    out.push({time: s, value: y});
  }
  return out;
}

export async function mount(el, ctx) {
  ctx.setTitle("매매법 비교");
  const st = {ids: [], d: null, gen: 0};
  const q0 = ctx.params.query || {};
  st.ids = q0.ids != null ? cmp.setPicks(cmp.readPicks(q0.ids)) : cmp.picks();

  const picksBox = h("div", {class: "cmp-picks", role: "list", "aria-label": "고른 것"});
  const input = h("input", {class: "search cmp-in", type: "search", autocomplete: "off", "aria-label": "비교할 매매법·계좌 찾기"});
  const results = h("div", {class: "cmp-res", role: "list"});
  const favBox = h("div", {class: "cmp-favs"});
  const clearBtn = h("button", {type: "button", class: "btn-line", onclick: () => setIds([])}, "모두 빼기");
  const pickCard = ui.card({plate: "고르기", sub: `최대 ${cmp.CMP_MAX}개 · 이 기기에 기억`, acts: [clearBtn]}, picksBox, input, results, favBox,
    ui.note("매매법 화면·계좌 화면·옆 창의 '＋ 비교에 추가'로도 넣을 수 있습니다. 동전 봇은 비교 기준이라 고르지 않고, 각 칸의 '동전 봇 순위'로 봅니다."));
  const body = h("div", {class: "stack cmp-body"});
  el.append(ui.screenHead("매매법 비교", "2~4개를 나란히 · 설명용, 판정 아님"), pickCard, body);

  const board = () => ctx.store.get("board");
  function setIds(ids) {
    st.ids = cmp.setPicks(ids);
    try { window.history.replaceState(null, "", ctx.href("compare", null, st.ids.length ? {ids: st.ids.join(",")} : null)); } catch { /* keep the hash */ }
    renderPicker(); load();
  }
  function renderPicker() {
    const full = st.ids.length >= cmp.CMP_MAX;
    put(picksBox, st.ids.length ? st.ids.map((id, i) => h("span", {class: "cmp-pick", role: "listitem", style: {"--c": colour(i)}},
      h("i", {class: ["cmp-sw", `d${i}`], "aria-hidden": "true"}), h("b", null, pickName(id, board())), h("small", {class: "muted"}, id),
      h("button", {type: "button", class: "cmp-x", "aria-label": `${pickName(id, board())} 빼기`, onclick: () => setIds(st.ids.filter((x) => x !== id))}, "✕")))
      : h("p", {class: "muted cmp-none"}, "아직 고른 것이 없습니다. 아래에서 찾거나 즐겨찾기에서 눌러 넣으세요."));
    input.disabled = full;
    input.placeholder = full ? `${cmp.CMP_MAX}개가 다 찼습니다 · 하나 빼고 넣기` : "매매법·계좌 찾기 (예: 돈치안, S5, F9)";
    clearBtn.hidden = !st.ids.length;
    paintResults();
    const f = fav.favs();
    const quick = [...f.strategy, ...f.account].filter((id) => !st.ids.includes(id) && !cmp.isFlipId(id)).slice(0, 8);
    put(favBox, quick.length && !full ? [h("span", {class: "muted cmp-favk"}, "★ 즐겨찾기에서"),
      quick.map((id) => h("button", {type: "button", class: "cmp-add", onclick: () => setIds([...st.ids, id])}, "＋ ", pickName(id, board())))] : null);
  }
  function paintResults() {
    const found = findPicks(pickables(board()), input.value, st.ids);
    put(results, input.value.trim() && !found.length ? h("p", {class: "muted cmp-none"}, "맞는 매매법·계좌가 없습니다") : found.map((x) =>
      h("button", {type: "button", class: "cmp-add", role: "listitem", onclick: () => { input.value = ""; setIds([...st.ids, x.id]); }},
        "＋ ", h("b", null, x.label), h("small", {class: "muted"}, ` ${x.sub}`))));
  }
  input.addEventListener("input", paintResults);

  // ---------------------------------------------------------------- the chart (made once, its lines replaced)
  let C = null, lines = [];
  const chartBox = h("div", {class: "cmp-chart"});
  const legend = h("div", {class: "cmp-legend"});
  const chartCard = ui.card({plate: "합친 곡선", sub: "닫힌 거래마다 · 시작 잔고 합 대비 수익률"}, chartBox, legend,
    ui.note("선 끝 = 지금 잔고 (닫힌 거래 기준, 열린 포지션 손익 제외). 매매법은 봉 계좌를 더한 값, 계좌는 그 계좌 하나입니다."));
  // a flat start (no closed trade yet) keeps at least 2%p of height, so the axis reads −1.0% … +1.0%, never 0.0% six times
  const minSpan = (orig) => {
    const r = orig();
    if (!r || !r.priceRange) return r;
    const {minValue: lo, maxValue: hi} = r.priceRange, pad = Math.max(0, 0.02 - (hi - lo)) / 2;
    return pad ? {...r, priceRange: {minValue: lo - pad, maxValue: hi + pad}} : r;
  };
  async function drawChart(items) {
    if (!C) {
      try {
        C = await makeChart(chartBox, {rightPriceScale: {borderColor: tok("--line-2"), scaleMargins: {top: 0.1, bottom: 0.1}}, timeScale: {rightOffset: 4}});
        ctx.track(C.dispose);
      } catch (e) { put(chartBox, ui.errorBox(e, () => location.reload())); return; }
    }
    if (!ctx.alive()) return;
    for (const s of lines) { try { C.chart.removeSeries(s); } catch (e) { /* gone */ } }
    lines = [];
    items.forEach((x) => {
      const i = st.ids.indexOf(x.id);
      const s = C.chart.addLineSeries({color: tok(`--pick-${i + 1}`), lineWidth: 2, lineStyle: DASH[i] || 0, lastValueVisible: false, priceLineVisible: false,
        priceFormat: {type: "custom", minMove: 0.0001, formatter: (v) => fmt.pct(v, 1)}, autoscaleInfoProvider: minSpan});
      s.setData(lineData(x.t, x.curve));
      if (!lines.length) s.createPriceLine({price: 0, color: tok("--line-2"), lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: ""});
      lines.push(s);
    });
    C.chart.timeScale().fitContent();
  }

  // ---------------------------------------------------------------- the tables
  const head = (x) => {
    const i = st.ids.indexOf(x.id);
    return h("th", {scope: "col", class: "cmp-th", style: {"--c": colour(i)}}, h("i", {class: ["cmp-sw", `d${i}`], "aria-hidden": "true"}),
      h("b", null, x.name || pickName(x.id, board())),
      h("small", null, x.kind === "account" ? `계좌 · ${fmt.tfKo(x.tfs[0])}` : `매매법 · 봉 ${fmt.int(x.accounts)}개 합`));
  };
  const coMark = () => h("span", {class: "muted cmp-co", title: "딥시크는 섞인 화면에서 돈 숫자를 보이지 않습니다 (거래 수만)"}, "거래 수만");
  /** Side by side: a table (one column per pick) from 600 px, one block per pick on a phone (compare.css). */
  function table(items, rowsIn) {
    // DeepSeek picks alone: only the count rows (a table of '거래 수만' cells says nothing)
    const rows = items.every((x) => x.counts_only) ? rowsIn.filter((r) => r.money === false) : rowsIn;
    const val = (x, r) => (x.counts_only && r.money !== false ? coMark() : r.get(x));
    const wide = h("div", {class: "tbl-wrap cmp-scroll"}, h("table", {class: "tbl cmp-tbl"},
      h("thead", null, h("tr", null, h("th", {class: "l cmp-rowh", scope: "col"}, ""), items.map(head))),
      h("tbody", null, rows.map((r) => h("tr", null, h("th", {class: "l cmp-rowh", scope: "row"}, h("b", null, r.k), r.s ? h("small", null, r.s) : null),
        items.map((x) => h("td", {class: "num"}, val(x, r))))))));
    const phone = h("div", {class: "cmp-stack"}, items.map((x) => {
      const i = st.ids.indexOf(x.id);
      return h("section", {class: "cmp-sitem", style: {"--c": colour(i)}, "aria-label": x.name},
        h("div", {class: "cmp-shead"}, h("i", {class: ["cmp-sw", `d${i}`], "aria-hidden": "true"}), h("b", null, x.name),
          h("small", {class: "muted"}, x.kind === "account" ? `계좌 · ${fmt.tfKo(x.tfs[0])}` : `봉 ${fmt.int(x.accounts)}개 합`)),
        h("dl", {class: "cmp-kv"}, rows.map((r) => [h("dt", null, r.k), h("dd", null, val(x, r))])));
    }));
    return [wide, phone];
  }
  const pctCell = (v, dec = 1) => h("b", {class: ["num", fmt.tone(v, fmt.pct(v, dec))]}, v == null ? "—" : fmt.pct(v, dec));
  const MAIN = [
    {k: "수익률", s: "시작 잔고 합 대비 · 닫힌 거래", get: (x) => pctCell(x.ret)},
    {k: "합친 곡선 최대 낙폭", s: "고점에서 가장 많이 내려간 폭", get: (x) => (x.mdd == null ? "—" : fmt.pct(x.mdd, 1, false))},
    {k: "계좌 하나의 가장 깊은 낙폭", s: "열린 포지션 손익까지 · 봇이 기록한 값", get: (x) => (x.mdd_worst == null ? "—" : fmt.pct(x.mdd_worst, 1, false))},
    {k: "거래 수", s: "닫힌 거래", money: false, get: (x) => h("span", null, `${fmt.int(x.trades)}건`, " ", ui.smallSample(x.trades, SMALL))},
    {k: "승률", s: "이긴 거래 ÷ 전체", get: (x) => (x.win_rate == null ? "—" : h("span", null, fmt.pct(x.win_rate, 0, false), h("small", {class: "muted"}, ` ${fmt.int(x.wins)}승 ${fmt.int(x.losses)}패`)))},
    {k: "손익비", s: "평균 이익 ÷ 평균 손실", get: (x) => (x.payoff != null ? fmt.num(x.payoff, 2) : x.no_loss ? "손실 없음" : "—")},
    {k: "수익 팩터", s: "총이익 ÷ 총손실", get: (x) => (x.pf != null ? fmt.num(x.pf, 2) : x.no_loss ? "손실 없음" : "—")},
    // a rank on a handful of trades is luck more than skill: it says 표본 적음 next to it (like the 순위표's 동전 ▲▼)
    {k: "동전 봇 순위 (참고)", s: "같은 봉 동전 봇 몇 개보다 수익률이 높은지", get: (x) => (x.extra ? h("span", {class: "muted"}, "비교 안 함 (늦게 시작)")
      : !x.trades ? h("span", {class: "muted"}, "거래 전 (아직 견줄 것 없음)")
      : x.flip ? h("span", null, `동전 봇 ${fmt.int(x.flip.n)}개 중 ${fmt.int(x.flip.above)}개보다 높음`, x.trades < SMALL ? h("small", {class: "muted"}, " · 표본 적음") : null) : "—")},
    {k: "지금 포지션", s: "열린 것", money: false, get: (x) => `${fmt.int(x.open)}개`},
    {k: "파산 계좌", s: "잔고 10 USDT 미만", get: (x) => fmt.int(x.bust)},
  ];
  const tfsOf = (items) => fmt.TF_ORDER.filter((tf) => items.some((x) => x.tfs.includes(tf)));
  function tfTable(items) {
    const rows = tfsOf(items).map((tf) => ({k: fmt.tfKo(tf), money: false, get: (x) => {
      const r = (x.by_tf || []).find((y) => y.tf === tf);
      if (!r) return h("span", {class: "muted"}, "—");
      if (x.counts_only) return h("span", null, `${fmt.int(r.trades)}건`, r.open ? h("small", {class: "accent"}, " · 포지션") : null);
      return h("span", {class: "cmp-cell"}, pctCell(r.ret), h("small", null, `${fmt.int(r.trades)}건${r.win_rate != null ? ` · 승률 ${fmt.pct(r.win_rate, 0, false)}` : ""}`),
        r.vs != null ? h("small", {class: "muted", title: "같은 봉 동전 봇 수익률 중앙값과의 차이 (참고, 판정 아님)"}, `동전 대비 ${fmt.pct(r.vs, 1)}`) : null);
    }}));
    return table(items, rows);
  }
  function y5Table(items) {
    const rows = tfsOf(items).map((tf) => ({k: fmt.tfKo(tf), money: false, get: (x) => {
      if (x.counts_only) return h("span", {class: "muted"}, "이 화면에서는 안 보임");
      if (x.extra) return h("span", {class: "muted"}, "규칙이 달라 없음");
      const r = x.y5 && x.y5.rows.find((y) => y.tf === tf);
      if (!x.tfs.includes(tf)) return h("span", {class: "muted"}, "—");
      if (!r) return h("span", {class: "muted"}, "5년 자료 없음");
      return h("span", {class: "cmp-cell"}, h("b", {class: "num"}, `건당 ${r.roe == null ? "—" : fmt.pct(r.roe, x.y5.unit === "1x" ? 2 : 1)}`),
        h("small", null, `승률 ${r.win == null ? "—" : fmt.pct(r.win, 0, false)} · 하루 ${r.per_day == null ? "—" : fmt.num(r.per_day, 2)}건`),
        r.hold_h != null ? h("small", {class: "muted"}, `보유 ${fmt.num(r.hold_h, 1)}시간`) : null);
    }}));
    return table(items, rows);
  }

  // ---------------------------------------------------------------- render
  const verdictTs = () => { const s = ctx.store.get("summary") || {}; return (s.restart && s.restart.ready && s.restart.verdict_ts) || (s.next_checkpoint && s.next_checkpoint.ts) || null; };
  function render(d) {
    const items = (d.items || []).map((x) => ({...x, name: pickName(x.id, board()) || x.name_ko}))
      .sort((a, b) => st.ids.indexOf(a.id) - st.ids.indexOf(b.id));
    const money = items.filter((x) => !x.counts_only);
    const kids = [];
    const notes = [];
    if ((d.dropped || []).length) notes.push(ui.note(`동전 봇은 비교 기준이라 뺐습니다: ${d.dropped.join(", ")}. 각 칸의 '동전 봇 순위'로 봅니다.`));
    if ((d.unknown || []).length) notes.push(ui.note(`찾지 못했습니다 (지금 순위표에 없음): ${d.unknown.join(", ")}`));
    if (items.some((x) => x.counts_only)) {
      notes.push(h("p", {class: "refnote"}, h("b", null, "딥시크"), " · 이 화면은 여러 묶음이 섞여 있어 딥시크는 거래 수만 보입니다. 수익·낙폭은 ",
        h("a", {href: ctx.href("board", null, {g: "ds"})}, "순위표 › 딥시크"), "에서 봅니다."));
    }
    if (items.length === 1) notes.push(h("p", {class: "cmp-hint"}, "하나 더 고르면 나란히 봅니다."));
    if (notes.length) kids.push(h("div", {class: "stack tight"}, notes));
    if (!items.length) {           // every pick unknown or a coin flip: no empty tables, the how-to card instead
      kids.push(emptyCard());
      put(body, kids);
      return;
    }
    // the analysis kit's filling bars (one per pick under 30 closed trades); the numbers below stay on screen, so the
    // note says what they are worth now (analysis-kit waitCard's own note promises a view that fills in later)
    const thin = items.filter((x) => x.trades < SMALL);
    if (thin.length) {
      kids.push(ui.card({plate: "채워지는 중", sub: "비교할 만큼 거래가 쌓이는 중", cls: "an-wait"},
        thin.map((x) => progressBar(x.name, `닫힌 거래 ${fmt.int(x.trades)} / ${SMALL}건 · ${SMALL}건이 안 되면 숫자가 우연일 수 있어 결론을 내리지 않습니다${x.counts_only ? " (딥시크는 거래 수만)" : ""}`,
          x.trades / SMALL)),
        h("p", {class: "an-note"}, `막대는 고른 것마다 실제 닫힌 거래 수입니다. ${SMALL}건이 될 때까지 아래 숫자는 지금까지의 기록일 뿐, 어느 쪽이 낫다는 뜻이 아닙니다.`)));
    }
    if (money.length) kids.push(chartCard);
    kids.push(ui.card({plate: "주요 숫자", sub: d.label || "설명용, 판정 아님"}, table(items, MAIN),
      money.length ? ui.refNote(verdictTs(), "동전 봇 순위는 같은 봉 동전 봇 묶음(RANDOM_1~3)을 같은 봉끼리 더해 견준 참고 숫자입니다.")
        : ui.note("딥시크끼리는 거래 수와 지금 포지션만 나란히 봅니다."),
      money.length ? ui.assume(null, "수익률·낙폭·손익비는 닫힌 거래 기준") : null));
    kids.push(ui.card({plate: "봉별로 나눠 보기", sub: money.length ? "참고" : "거래 수"}, tfTable(items),
      money.length ? ui.note("동전 대비 = 같은 봉 동전 봇 수익률 중앙값과의 차이 (참고, 판정 아님). 늦게 시작한 추가 계좌는 견주지 않습니다.") : null));
    // the research is NOT the live rules (vs5y-kit says the same on the strategy page): the 36's 5-year cards used the v3
    // leverage rule, every signal was taken (a live account holds one position at a time), and some research exits differ
    const exitDiff = items.filter((x) => x.y5 && x.y5.exit && x.y5.same_exits_as_live === false)
      .map((x) => `${x.name}: 5년 연구 청산(${x.y5.exit})은 지금 계좌 청산과 다름`);
    if (items.every((x) => x.counts_only)) {
      kids.push(ui.card({plate: "5년 시험", sub: "딥시크는 이 화면에서 안 보임"},
        h("p", {class: "ink2"}, "딥시크 정의의 5년 연구 숫자는 섞인 화면에서 보이지 않습니다. 각 정의의 매매법 화면(딥시크)에서 봅니다.")));
    } else kids.push(ui.card({plate: "5년 시험", sub: "연구 결과 · 지난 5년 · 지금 규칙과 일부 다름"}, y5Table(items),
      ui.note(["기존 36의 '건당'은 증거금 대비 거래 한 번의 평균 ROE (5년 시험은 예전 v3 배수 규칙), 5분봉은 배수 없이 가격 % (1배)입니다. ",
        "5년 시험은 신호를 모두 따로 잡아서 지금 계좌(한 번에 한 포지션)보다 거래가 많은 게 보통입니다. ",
        ...exitDiff.map((t) => `${t}. `), "5년 숫자는 성격을 보는 참고이지 실력의 증거가 아닙니다."].join(""))));
    kids.push(h("p", {class: "cmp-foot"}, `${d.label || "설명용, 판정 아님"}${d.computed_at ? ` · ${fmt.kst(d.computed_at)} 계산${d.stale ? " (예전 값, 다시 계산 중)" : ""}` : ""} · 같이 돌렸다면 어땠을지는 `,
      h("a", {href: ctx.href("analysis", "synergy")}, "분석 › 조합 시너지"), "에서 봅니다."));
    put(body, kids);
    put(legend, money.map((x) => {
      const i = st.ids.indexOf(x.id);
      return h("span", {class: "cmp-lg", style: {"--c": colour(i)}}, h("i", {class: ["cmp-sw", `d${i}`], "aria-hidden": "true"}), h("b", null, x.name),
        " ", h("span", {class: ["num", fmt.tone(x.ret, fmt.pct(x.ret))]}, fmt.pct(x.ret)), x.trades < SMALL ? h("small", {class: "muted"}, " 표본 적음") : null);
    }), items.filter((x) => x.counts_only).map((x) => h("span", {class: "cmp-lg muted"}, `${x.name}: 거래 수만 (곡선 없음)`)));
    if (money.length) drawChart(money);
  }
  const emptyCard = () => ui.card({plate: "나란히 보기", cls: "cmp-empty"},
      h("p", {class: "ink2"}, "매매법이나 계좌를 2개 이상 고르면 여기에 합친 곡선, 주요 숫자, 봉별 숫자, 5년 시험 숫자가 나란히 나옵니다."),
      h("ol", {class: "cmp-steps"}, h("li", null, "위 찾기 칸에 이름이나 코드를 적어 고르거나"),
        h("li", null, "매매법 화면·계좌 화면의 '＋ 비교에 추가'를 누르거나"), h("li", null, "★ 즐겨찾기한 것을 한 번에 넣습니다.")),
      h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: ctx.href("strategies")}, "매매법 목록"), h("a", {class: "btn-line", href: ctx.href("board")}, "순위표")));
  const renderEmpty = () => put(body, emptyCard());
  /** quiet: a periodic refresh keeps the shown answer until the new one is there (a shimmer only on a new pick list). */
  async function load(quiet) {
    const gen = ++st.gen;
    if (!st.ids.length) { st.d = null; renderEmpty(); return; }
    if (!quiet || !st.d) put(body, motion.shimmer(4, true));
    let d;
    try { d = await ctx.api(`/api/v4/compare?ids=${encodeURIComponent(st.ids.join(","))}`); }
    catch (e) { if (gen === st.gen && !(e && e.name === "AbortError") && (!quiet || !st.d)) put(body, ui.errorBox(e, () => load())); return; }
    if (gen !== st.gen || !ctx.alive()) return;
    if (d && d.pending) { ctx.timeout(() => { if (gen === st.gen) load(quiet); }, 3000); return; }
    if (d && d.error) { if (!quiet || !st.d) put(body, ui.errorBox(new Error(d.error), () => load())); return; }
    st.d = d;
    render(d);
  }

  current = (params) => {
    const q = (params && params.query) || {};
    if (q.ids == null) return;
    const ids = cmp.readPicks(q.ids);
    if (ids.join(",") === st.ids.join(",")) return;
    st.ids = cmp.setPicks(ids);
    renderPicker(); load();
  };
  ctx.track(() => { current = null; });
  ctx.track(fav.onFavs(() => renderPicker()));
  await ctx.store.need("board", 60000).catch(() => null);
  if (!ctx.alive()) return;
  renderPicker();
  let nAcc = -1;                     // names only change with the account list (a new extra): the picker follows that
  ctx.watch("board", (b) => { const n = ((b && b.accounts) || []).length; if (n !== nAcc) { nAcc = n; renderPicker(); } });
  ctx.every(60000, () => { if (st.ids.length && !document.hidden) load(true); }, {now: false});
  await load();
}

export function update(params) { if (current) current(params); }

export function unmount() { current = null; }
