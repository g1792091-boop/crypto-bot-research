// #/analysis 분석 (CONTRACT 9.5): one account (its 20배 line: the entries are the same on every line up to skipped
// ones) or one kind of account (all its accounts' 20배 lines together): closed trades split by coin, long / short,
// timeframe and exit reason (n, mean R, P&L, win rate, with a bar), and a KST weekday × hour grid of mean R (hw_n / hw_R;
// without them the hour and weekday bars). A bucket under 30 trades says so: it may be luck. analysis.json every 5 min.
// Round 5 stage 2B (the rule bot's v4 분석 look, analysis-kit.js): the choice in the filter bar; the v4 question card
// (plate, the question in plain words, what it stands on, how to read it, the small-sample warning); four stat cards
// that count to new values; the buckets in the dense table look; the weekday × hour grid in the v4 heat-cell steps.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {COINS, KIND_KO, tfKo} from "../labels.js";
import {byKind, divBar, barN, fewNote, FEW, FEW_KO} from "../g4.js";

const WD_KO = ["월", "화", "수", "목", "금", "토", "일"];
/** The colour step of a value against the scale (grid-kit data-b: −4..4). */
const stepOf = (v, max) => {
  const a = Math.abs(Number(v)) / (max || 1);
  if (!(a > 0.02)) return 0;
  return Math.sign(Number(v)) * Math.max(1, Math.min(4, Math.ceil(a * 4)));
};

export async function mount(el, ctx) {
  ctx.setTitle("분석");
  const q = ctx.params.query;
  let pick = q.id ? `a:${q.id}` : q.kind ? `k:${q.kind}` : local.get("analysis-pick", "k:fixed");
  const ctrl = h("span", {class: "k4-barg s2-g"});
  const headQ = h("h2", {class: "s2-q"}, "어떤 코인 · 방향 · 시간에 벌고 잃었나?");
  const headMeta = h("p", {class: "s2-meta"});
  const headWarn = h("div");
  const headActs = h("div", {class: "row wrap s2-acts"});
  const nN = K4.liveNum(null, {format: (v) => fmt.int(v), flash: "accent"});
  const nR = K4.liveNum(null, {format: (v) => fmt.r(v), tone: true, flash: "accent"});
  const nW = K4.liveNum(null, {format: (v) => fmt.ratio(v), flash: "accent"});
  const nP = K4.liveNum(null, {format: (v) => fmt.money(v, true), tone: true, flash: "accent"});
  const nSub = h("span", {class: "s"}, "—"), pSub = h("span", {class: "s"}, "—");
  const stats = h("div", {class: "stats s4 s2-stats"},
    K4.stat("닫힌 거래", nN, nSub), K4.stat("평균 R", nR, "수수료 후"), K4.stat("승률", nW, "닫힌 거래 기준"), K4.stat("손익 (20배 줄)", nP, pSub));
  const body = h("div", {class: "stack"});
  el.append(ui.screenHead("분석", "어떤 코인·방향·시간에 벌고 잃었나"),
    h("div", {class: "s2-ctl", role: "group", "aria-label": "고르기"}, h("div", {class: "k4-bar"}, ctrl)),
    ui.card({plate: "분석", cls: "s2-head", acts: headActs}, headQ, headMeta,
      h("p", {class: "s2-read"}, h("b", null, "읽는 법 "), "20배 줄의 닫힌 거래를 코인 · 방향 · 봉 · 나간 이유 · 들어간 시각으로 나눕니다. 막대는 평균 R의 크기와 방향입니다."),
      headWarn),
    stats, body,
    ui.note(`20배 줄의 닫힌 거래로 셉니다 (배수 줄들은 같은 진입이고, 진입 검사로 건너뛴 것만 다릅니다). R = 손절 폭을 1로 본 손익, 손익은 20배 줄의 달러. ${FEW_KO}`));

  let data = null, seen = null;
  async function load() {
    let d;
    try { d = await ctx.api("/api/analysis"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!data) put(body, ui.errorBox(e, load));
      return;
    }
    if (d && d.generated_ms === seen && data) return;
    seen = d && d.generated_ms;
    data = d;
    paintControls();
    paint(false);
  }

  function paintControls() {
    if (!data || isMissing(data)) { put(ctrl, h("span", {class: "k4-k"}, "보기"), ui.none("준비 중")); return; }
    const kinds = data.kinds || [];
    const groups = byKind(data.accounts || []);
    const sel = h("select", {class: "select", "aria-label": "계좌 또는 종류"},
      h("optgroup", {label: "종류 (계좌 모두 합침)"}, kinds.map((k) => h("option", {value: `k:${k.kind}`, selected: pick === `k:${k.kind}`},
        `${k.kind_ko || KIND_KO[k.kind] || k.kind} 전체 (${fmt.int(k.n)}건)`))),
      groups.map((g) => h("optgroup", {label: g.ko}, g.rows.map((a) => h("option", {value: `a:${a.id}`, selected: pick === `a:${a.id}`},
        `${a.name || a.id} (${fmt.int(a.n)}건)`)))));
    sel.addEventListener("change", () => {
      pick = sel.value;
      local.set("analysis-pick", pick);
      ctx.setQuery(pick.startsWith("a:") ? {id: pick.slice(2)} : {kind: pick.slice(2)});
      paint(true);
    });
    put(ctrl, h("span", {class: "k4-k"}, "보기"), sel);
  }

  function current() {
    if (!data || isMissing(data)) return null;
    if (pick.startsWith("a:")) return (data.accounts || []).find((a) => a.id === pick.slice(2)) || null;
    return (data.kinds || []).find((k) => k.kind === pick.slice(2)) || null;
  }

  function paint(user) {
    if (user) for (const n of [nN, nR, nW, nP]) delete n.dataset.v;
    if (!data || isMissing(data)) {
      for (const n of [nN, nR, nW, nP]) n.update(null);
      nSub.textContent = "준비 중"; pSub.textContent = ""; headMeta.textContent = "";
      put(headWarn); put(headActs); put(body, ui.missing("분석 자료"));
      return;
    }
    let x = current();
    if (!x) { pick = "k:fixed"; x = current() || (data.kinds || [])[0] || null; }
    if (!x) { put(headWarn); put(body, ui.none("기록 없음")); return; }
    const side = x.by_side || {};
    const all = [side.long, side.short].filter(Boolean);
    const n = Number(x.n) || all.reduce((a, b) => a + (Number(b.n) || 0), 0);
    const sumR = all.reduce((a, b) => a + (b.mean_R != null ? Number(b.mean_R) * Number(b.n) : 0), 0);
    const pnl = all.reduce((a, b) => a + (Number(b.pnl) || 0), 0);
    const wins = all.reduce((a, b) => a + (b.win_rate != null ? Number(b.win_rate) * Number(b.n) : 0), 0);
    const meanR = n ? sumR / n : null;
    const who = x.id ? (x.name || x.id) : `${x.kind_ko || KIND_KO[x.kind] || x.kind} 계좌 모두`;
    nN.update(n); nR.update(meanR); nW.update(n ? wins / n : null); nP.update(pnl);
    nSub.textContent = who;
    pSub.textContent = x.id ? "이 계좌의 20배 줄" : "계좌들 합계";
    headMeta.textContent = `${who} · 닫힌 거래 ${fmt.int(n)}건 · 20배 줄${data.generated_ms ? ` · ${fmt.kst(data.generated_ms)} 계산` : ""}`;
    put(headWarn, n < FEW ? h("p", {class: "s2-warn"}, ui.pill("표본 적음", "thin"), ` 거래가 ${fmt.int(n)}건뿐입니다: 표본이 적으면 우연일 수 있습니다.`) : null);
    put(headActs, x.id ? h("a", {class: "btn-line", href: ctx.href("account", x.id)}, "이 계좌 자세히") : null);
    const coins = COINS.map((c) => ({k: fmt.coin(c), ...((x.by_coin || {})[c] || {n: 0})}));
    const sides = [{k: "롱 (오를 쪽)", ...(side.long || {n: 0})}, {k: "숏 (내릴 쪽)", ...(side.short || {n: 0})}];
    const tfs = Object.entries(x.by_tf || {}).map(([k, v]) => ({k: tfKo(k), ...v}));
    const exits = Object.entries(x.by_exit || {}).map(([k, v]) => ({k, ...v})).filter((r) => Number(r.n) > 0);
    put(body,
      h("div", {class: "grid2 s2-angrid"},
        ui.card({plate: "코인별"}, bucketTable(coins)),
        h("div", {class: "stack"}, ui.card({plate: "롱 / 숏"}, bucketTable(sides)),
          tfs.length > 1 ? ui.card({plate: "봉별"}, bucketTable(tfs)) : null,
          ui.card({plate: "나간 이유별", sub: "익절 · 손절 · 잠금 익절(사다리) · 본전 · 강제청산 · 시간"}, bucketTable(exits)))),
      ui.card({plate: "요일 × 시간 (한국 시간)", sub: "들어간 시각 기준 · 칸 색 = 그 시간 평균 R"}, heat(x)));
    if (user) K4.swap(body);
  }

  await load();
  ctx.every(5 * 60000, load);
}

function bucketTable(rows) {
  if (!rows.length || rows.every((r) => !Number(r.n))) return ui.none("기록 없음");
  const maxR = Math.max(0.05, ...rows.map((r) => (r.mean_R != null && Number(r.n) >= 5 ? Math.abs(Number(r.mean_R)) : 0)));
  const maxN = Math.max(1, ...rows.map((r) => Number(r.n) || 0));
  return ui.table([
    {label: "", l: true, get: (r) => h("b", null, r.k)},
    {label: "거래", l: true, get: (r) => barN(r.n, maxN)},
    {label: "평균 R", l: true, get: (r) => divBar(r.mean_R, maxR, fmt.r(r.mean_R))},
    {label: "승률", get: (r) => fmt.ratio(r.win_rate)},
    {label: "손익", get: (r) => ui.signed(fmt.money(r.pnl, true), fmt.tone(r.pnl, fmt.money(r.pnl)))},
    {label: "", l: true, get: (r) => fewNote(r.n) || ""},
  ], rows, {cls: "g4-bt s2-dense", rowCls: (r) => (Number(r.n) < FEW ? "g4-dim" : "")});
}

function heat(x) {
  const hn = x.hw_n, hr = x.hw_R;
  const ok = Array.isArray(hn) && hn.length === 7 && Array.isArray(hr) && hr.length === 7;
  if (!ok) return h("div", {class: "stack"}, h("p", {class: "note"}, "요일 × 시간 칸 자료가 없어 시간별, 요일별로 따로 봅니다."),
    hourBars(x.by_hour || [], (i) => `${i}시`), hourBars(x.by_weekday || [], (i) => WD_KO[i] || String(i)));
  let vmax = 0.05;
  for (let d = 0; d < 7; d++) for (let k = 0; k < 24; k++) if ((hn[d] || [])[k] >= 5 && hr[d][k] != null) vmax = Math.max(vmax, Math.abs(hr[d][k]));
  vmax = Math.min(vmax, 1);
  const cells = [h("span", {class: "g4-hc0"})];
  for (let k = 0; k < 24; k++) cells.push(h("span", {class: "g4-hx"}, k % 3 === 0 ? String(k) : ""));
  for (let d = 0; d < 7; d++) {
    cells.push(h("span", {class: "g4-hy"}, WD_KO[d]));
    for (let k = 0; k < 24; k++) {
      const n = Number((hn[d] || [])[k]) || 0, v = (hr[d] || [])[k];
      const has = n > 0 && v != null;
      const title = `${WD_KO[d]}요일 ${k}시: 거래 ${n}건${has ? ` · 평균 ${fmt.r(v)}` : ""}${n && n < 5 ? " (너무 적음)" : ""}`;
      cells.push(h("span", {class: ["s2-hc", "s2-hcs", has ? "" : "grey", n && n < 5 ? "thin" : ""], title, "aria-label": title,
        dataset: has ? {b: String(stepOf(v, vmax))} : null}));
    }
  }
  const byDay = (x.by_weekday || []).map((b, i) => ({k: WD_KO[i] || String(i), ...b}));
  return h("div", {class: "stack tight"},
    h("div", {class: "g4-heatwrap"}, h("div", {class: "g4-heat s2-heat", role: "img", "aria-label": "요일과 시간별 평균 R"}, cells)),
    h("div", {class: "s2-keys"},
      h("span", {class: "s2-scale", "aria-hidden": "true"},
        h("span", {class: "s2-scale-row"}, [-4, -3, -2, -1, 0, 1, 2, 3, 4].map((b) => h("span", {class: "s2-hc", dataset: {b: String(b)}}))),
        h("span", {class: "s2-scale-words"}, h("span", {class: "num"}, fmt.r(-vmax)), h("span", null, "0"), h("span", {class: "num"}, fmt.r(vmax)))),
      h("span", null, h("i", {class: "s2-hc grey"}), "거래 없음"), h("span", null, h("i", {class: "s2-hc thin", dataset: {b: "2"}}), "5건 미만 (흐림)")),
    h("p", {class: "note"}, "칸 하나는 한 요일의 한 시간에 들어간 거래들입니다. 칸마다 거래가 몇 건 안 되어서, 색 하나하나보다 넓게 몰린 무늬를 보세요. 칸에 손가락이나 마우스를 올리면 숫자가 나옵니다."),
    byDay.length === 7 ? ui.disclosure("요일별 숫자 (더 보기)", bucketTable(byDay)) : null,
    (x.by_hour || []).length === 24 ? ui.disclosure("시간별 숫자 (더 보기)", bucketTable((x.by_hour || []).map((b, i) => ({k: `${i}시`, ...b})))) : null);
}

function hourBars(list, label) {
  if (!list.length) return ui.none("기록 없음");
  return bucketTable(list.map((b, i) => ({k: label(i), ...b})));
}
