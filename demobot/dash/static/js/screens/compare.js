// #/compare?ids=a,b,c&L=20 비교: 2-4 accounts side by side at one leverage. Their equity curves on one chart (each
// its own colour AND its own dash, named in the legend), and a table: P&L, trades, win rate, mean R, max drawdown,
// the stop-rule twin's P&L and the latest confirmation. accounts.json + judge.json + acct/<id>.json, every 60 s.
// Round 5 stage 2: the rule bot's v4 매매법 비교 look (compare.js / compare.css): each pick a chip with its colour, its
// line style and the account's pixel character; leverage and the stop-rule switch in one bar; the legend with the last
// value of each line; the side-by-side table with the picks' swatches and figures in its head.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {lineChart, PICK_TOKENS} from "../chart.js";
import {LEVS, KIND_KO, kindOfId} from "../labels.js";

const ID_RE = /^[A-Za-z0-9-]{3,40}$/;
const MAX = 4;
const DASH_CLS = ["dl-dash0", "dl-dash", "dl-dot", "dl-dash3"];

export async function mount(el, ctx) {
  ctx.setTitle("비교");
  const q = ctx.params.query || {};
  const saved = local.get("compare", {}) || {};
  let L = LEVS.map(String).includes(String(q.L)) ? String(q.L) : LEVS.map(String).includes(String(saved.L)) ? String(saved.L) : "20";
  let ids = String(q.ids || (saved.ids || []).join(",") || "").split(",").map((x) => x.trim()).filter((x) => ID_RE.test(x));
  let stopsMode = false;
  const pickBox = h("div", {class: "dl-picks"});
  const levSeg = ui.seg(LEVS.map((x) => ({id: String(x), label: `${x}배`})), L, (v) => { L = v; save(); paint(); }, {label: "배수"});
  const stopTog = K4.chipToggle("정지 규칙 적용 시로 보기", false, (v) => { stopsMode = v; paint(); }, "정지 규칙을 썼다면의 잔고 흐름으로 바꿔 봅니다");
  const chartBox = h("div", {class: "dl-chart", role: "img", "aria-label": "고른 계좌들의 잔고 흐름"});
  const legendBox = h("div"), tableBox = h("div");
  el.append(ui.screenHead("비교", "계좌 2~4개를 같은 배수로 나란히"),
    h("section", {class: "k4-sec", "aria-label": "고르기"}, K4.secRow("고르기", "2~4개 · 고른 순서대로 색과 선 모양"), pickBox),
    h("div", {class: "s2a-bar"}, h("span", {class: "s2a-barg"}, h("span", {class: "k4-k"}, "배수"), levSeg), stopTog),
    ui.card({plate: "잔고 흐름", sub: "지갑 + 열린 포지션 · 점선 가로줄 = 시작 $1,000", cls: "s2a-cmpchart"}, chartBox, legendBox),
    ui.card({plate: "나란히", sub: "같은 배수의 줄끼리"}, tableBox),
    h("p", {class: "assume"}, "색과 함께 선 모양(실선·긴 점선·점선·짧은 점선)으로도 구분합니다. 주소를 저장하면 같은 비교를 다시 열 수 있습니다."));

  let accounts = null, judge = null, details = {}, chart = null;
  function save() {
    local.set("compare", {ids, L});
    ctx.setQuery({ids: ids.join(","), L});
  }

  let seen;
  async function load() {
    let acc, jd;
    try {
      [acc, jd] = await Promise.all([ctx.api("/api/accounts"), ctx.api("/api/judge").catch(() => null)]);
    } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!accounts) put(pickBox, ui.errorBox(e, load));
      return;
    }
    const key = `${acc && acc.generated_ms}|${jd && jd.generated_ms}`;
    if (key === seen) return;
    const first = seen === undefined;
    seen = key;
    accounts = acc; judge = jd; details = {};
    if (isMissing(accounts)) {
      put(pickBox, ui.missing("계좌 목록"));
      put(chartBox, ui.none("준비 중")); put(tableBox); put(legendBox);
      return;
    }
    const known = new Set((accounts.accounts || []).map((a) => a.id));
    ids = [...new Set(ids.filter((x) => known.has(x)))].slice(0, MAX);
    if (ids.length < 2) {                     // a first visit: the default S2 account against its coin flip
      for (const want of ["fx-def-S2-15m", "cf-15m", ...known]) if (ids.length < 2 && known.has(want) && !ids.includes(want)) ids.push(want);
    }
    save();
    if (first) paintPicks();
    await fetchDetails();
    paint();
  }

  async function fetchDetails() {
    const want = ids.filter((x) => !details[x]);
    const got = await Promise.all(want.map((x) => ctx.api(`/api/account/${encodeURIComponent(x)}`).catch(() => null)));
    want.forEach((x, i) => { details[x] = got[i]; });
  }

  function paintPicks() {
    const opts = [...(accounts.accounts || [])].map((a) => ({id: a.id, label: `${a.name || a.id} (${KIND_KO[a.kind || kindOfId(a.id)] || "기타"})`}));
    const sel = (i) => {
      const cur = ids[i] || "";
      const s = ui.select([{id: "", label: i < 2 ? "고르세요" : "(없음)"}, ...opts], cur, async (v) => {
        const next = ids.slice();
        if (v) next[i] = v; else next.splice(i, 1);
        ids = [...new Set(next.filter(Boolean))].slice(0, MAX);
        save();
        paintPicks();
        await fetchDetails();
        paint();
      }, `계좌 ${i + 1}`);
      const a = (accounts.accounts || []).find((y) => y.id === cur);
      return h("div", {class: ["dl-pick", "s2a-pick", cur ? "" : "empty"], style: {"--pc": `var(${PICK_TOKENS[i]})`}},
        h("span", {class: "dl-pick-k"}, h("b", null, `${i + 1}`), h("i", {class: DASH_CLS[i]})), a ? K4.acctFig(a, 22) : null, s);
    };
    const n = Math.min(MAX, Math.max(2, ids.length + 1));
    put(pickBox, Array.from({length: n}, (_, i) => sel(i)));
  }

  async function paint() {
    const rows = ids.map((x, i) => ({i, id: x, d: details[x], a: (accounts.accounts || []).find((y) => y.id === x)}));
    const key = stopsMode ? "curves_stops" : "curves";
    put(legendBox, h("div", {class: "dl-legend s2a-cmplg"}, rows.map((r) => {
      const x = r.a && r.a.lines ? r.a.lines[L] : null;
      const v = x ? (stopsMode ? (x.stops ? x.stops.pnl_pct : null) : x.pnl_pct) : null;
      const t = fmt.pct(v, true);
      return h("span", {class: "dl-lg s2a-lgacct"}, h("i", {class: DASH_CLS[r.i], style: {"--pc": `var(${PICK_TOKENS[r.i]})`}}),
        r.a ? [K4.acctFig(r.a, 18), K4.acctName(r.a)] : r.id, h("b", {class: ["num", fmt.tone(v, t)]}, t));
    })));
    const list = rows.filter((r) => r.d && !isMissing(r.d) && r.d[key] && (r.d[key][L] || []).length)
      .map((r) => ({key: `${r.id}`, title: `${r.i + 1}`, token: PICK_TOKENS[r.i], points: r.d[key][L]}));
    if (!list.length) {
      if (chart) { chart.dispose(); chart = null; }
      put(chartBox, ui.none(stopsMode ? "정지 규칙 잔고 흐름: 기록 없음" : "기록 없음"));
    } else {
      try {
        if (!chart) { put(chartBox); chart = await lineChart(chartBox, {format: (p) => "$" + fmt.num(p, Math.abs(p) >= 100 ? 0 : 2), base: 1000, baseTitle: "시작"}); ctx.signal.addEventListener("abort", () => chart && chart.dispose()); }
        if (!ctx.alive()) return;
        chart.set(list);
      } catch (e) { put(chartBox, ui.empty("차트를 그리지 못했습니다.")); }
    }
    const conf = {};
    for (const r of (judge && !isMissing(judge) ? judge.rows : []) || []) conf[`${r.id}|${r.L}`] = r;
    const line = (r) => (r.a && r.a.lines ? r.a.lines[L] : null);
    const metrics = [
      ["손익", (r, x) => { const v = fmt.pct(x.pnl_pct, true); return ui.signed(v, fmt.tone(x.pnl_pct, v), "b"); }],
      ["잔고", (r, x) => fmt.money(x.equity)],
      ["닫힌 거래", (r, x) => fmt.int(x.trades)],
      ["승률", (r, x) => fmt.ratio(x.win_rate)],
      ["평균 R", (r, x) => { const v = fmt.r(x.mean_R); return ui.signed(v, fmt.tone(x.mean_R, v)); }],
      ["최대 낙폭", (r, x) => fmt.ratio(x.max_dd)],
      ["정지 규칙 적용 시", (r, x) => { const s = x.stops; if (!s) return h("span", {class: "muted"}, "준비 중"); const v = fmt.pct(s.pnl_pct, true); return h("span", null, ui.signed(v, fmt.tone(s.pnl_pct, v)), s.halted_ms ? h("small", {class: "muted"}, " · 멈춤") : null); }],
      ["확인 기간", (r) => { const j = conf[`${r.id}|${L}`]; return j ? (ui.confirmBadge(j.confirm) || h("span", {class: "muted"}, j.ours && j.ours.pass ? "통과" : "아직")) : h("span", {class: "muted"}, "—"); }],
      ["파산", (r, x) => (x.ruins ? `${fmt.int(x.ruins)}번` : x.ruined ? "있음" : "없음")],
    ];
    put(tableBox, rows.length ? h("div", {class: "tbl-wrap"}, h("table", {class: "tbl dl-cmp s2a-tbl s2a-cmptbl"},
      h("thead", null, h("tr", null, h("th", {class: "l dl-c2", scope: "col"}, h("span", {class: "dl-levtag", dataset: {lev: L}}, `${L}배`)), rows.map((r) => h("th", {scope: "col"},
        h("span", {class: "dl-cmph"}, h("i", {class: DASH_CLS[r.i], style: {"--pc": `var(${PICK_TOKENS[r.i]})`}}),
          h("a", {class: "s2a-nm", href: ctx.href("account", r.id), title: r.id}, r.a ? [K4.acctFig(r.a, 18), K4.acctName(r.a)] : r.id)))))),
      h("tbody", null, metrics.map(([k, fn]) => h("tr", null, h("th", {class: "l dl-c2", scope: "row"}, k),
        rows.map((r) => { const x = line(r); return h("td", null, x ? fn(r, x) : h("span", {class: "muted"}, "기록 없음")); })))))) : ui.none("계좌를 두 개 이상 고르세요"));
  }

  await load();
  ctx.every(60000, load);
}
