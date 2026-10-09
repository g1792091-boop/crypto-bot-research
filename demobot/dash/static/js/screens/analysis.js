// #/analysis 분석 (CONTRACT 9.5): one account (its 20배 line: the entries are the same on every line up to skipped
// ones) or one kind of account (all its accounts' 20배 lines together): closed trades split by coin, long / short,
// timeframe and exit reason (n, mean R, P&L, win rate, with a bar), and a KST weekday × hour grid of mean R (hw_n / hw_R;
// without them the hour and weekday bars). A bucket under 30 trades says so: it may be luck. analysis.json every 5 min.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {COINS, KIND_KO, tfKo} from "../labels.js";
import {byKind, divBar, barN, fewNote, FEW, FEW_KO, mixOf} from "../g4.js";

const WD_KO = ["월", "화", "수", "목", "금", "토", "일"];

export async function mount(el, ctx) {
  ctx.setTitle("분석");
  const q = ctx.params.query;
  let pick = q.id ? `a:${q.id}` : q.kind ? `k:${q.kind}` : local.get("analysis-pick", "k:fixed");
  const ctrl = h("div");
  const head = h("div");
  const body = h("div", {class: "stack"});
  el.append(ui.screenHead("분석", "어떤 코인·방향·시간에 벌고 잃었나"),
    ui.card({plate: "고르기", cls: "dl-controls"}, ctrl), head, body,
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
    paint();
  }

  function paintControls() {
    if (!data || isMissing(data)) { put(ctrl, ui.none("준비 중")); return; }
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
      paint();
    });
    put(ctrl, ui.field("보기", sel));
  }

  function current() {
    if (!data || isMissing(data)) return null;
    if (pick.startsWith("a:")) return (data.accounts || []).find((a) => a.id === pick.slice(2)) || null;
    return (data.kinds || []).find((k) => k.kind === pick.slice(2)) || null;
  }

  function paint() {
    if (!data || isMissing(data)) { put(head); put(body, ui.missing("분석 자료")); return; }
    let x = current();
    if (!x) { pick = "k:fixed"; x = current() || (data.kinds || [])[0] || null; }
    if (!x) { put(head); put(body, ui.none("기록 없음")); return; }
    const side = x.by_side || {};
    const all = [side.long, side.short].filter(Boolean);
    const n = Number(x.n) || all.reduce((a, b) => a + (Number(b.n) || 0), 0);
    const sumR = all.reduce((a, b) => a + (b.mean_R != null ? Number(b.mean_R) * Number(b.n) : 0), 0);
    const pnl = all.reduce((a, b) => a + (Number(b.pnl) || 0), 0);
    const wins = all.reduce((a, b) => a + (b.win_rate != null ? Number(b.win_rate) * Number(b.n) : 0), 0);
    const meanR = n ? sumR / n : null;
    put(head, h("div", {class: "stats dl-s4"},
      ui.stat("닫힌 거래", fmt.int(n), x.id ? (x.name || x.id) : `${x.kind_ko || KIND_KO[x.kind] || x.kind} 계좌 모두`),
      ui.stat("평균 R", ui.signed(fmt.r(meanR), fmt.tone(meanR, fmt.r(meanR)), "b"), "수수료 후"),
      ui.stat("승률", n ? fmt.ratio(wins / n) : "—"),
      ui.stat("손익 (20배 줄)", ui.signed(fmt.money(pnl, true), fmt.tone(pnl, fmt.money(pnl)), "b"), x.id ? null : "계좌들 합계")),
    n < FEW ? h("p", {class: "g4-warn"}, `거래가 ${fmt.int(n)}건뿐입니다: 표본이 적으면 우연일 수 있습니다.`) : null,
    x.id ? h("p", {class: "row wrap"}, h("a", {class: "btn-line", href: ctx.href("account", x.id)}, "이 계좌 자세히")) : null);
    const coins = COINS.map((c) => ({k: fmt.coin(c), ...((x.by_coin || {})[c] || {n: 0})}));
    const sides = [{k: "롱 (오를 쪽)", ...(side.long || {n: 0})}, {k: "숏 (내릴 쪽)", ...(side.short || {n: 0})}];
    const tfs = Object.entries(x.by_tf || {}).map(([k, v]) => ({k: tfKo(k), ...v}));
    const exits = Object.entries(x.by_exit || {}).map(([k, v]) => ({k, ...v})).filter((r) => Number(r.n) > 0);
    put(body,
      h("div", {class: "grid2"},
        ui.card({plate: "코인별"}, bucketTable(coins)),
        h("div", {class: "stack"}, ui.card({plate: "롱 / 숏"}, bucketTable(sides)),
          tfs.length > 1 ? ui.card({plate: "봉별"}, bucketTable(tfs)) : null,
          ui.card({plate: "나간 이유별", sub: "익절 · 손절 · 잠금 익절(사다리) · 본전 · 강제청산 · 시간"}, bucketTable(exits)))),
      ui.card({plate: "요일 × 시간 (한국 시간)", sub: "들어간 시각 기준 · 칸 색 = 그 시간 평균 R"}, heat(x)));
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
  ], rows, {cls: "g4-bt", rowCls: (r) => (Number(r.n) < FEW ? "g4-dim" : "")});
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
      cells.push(h("span", {class: ["g4-hcell", has ? (v >= 0 ? "pos" : "neg") : "none", n && n < 5 ? "thin" : ""], title, "aria-label": title,
        style: has ? {"--mix": `${mixOf(v, vmax)}%`} : null}));
    }
  }
  const byDay = (x.by_weekday || []).map((b, i) => ({k: WD_KO[i] || String(i), ...b}));
  return h("div", {class: "stack tight"},
    h("div", {class: "g4-heatwrap"}, h("div", {class: "g4-heat", role: "img", "aria-label": "요일과 시간별 평균 R"}, cells)),
    h("div", {class: "hm-legend"}, h("span", {class: "hm-scale"}, h("span", {class: "num"}, fmt.r(-vmax)), h("i", {class: "hm-grad"}), h("span", {class: "num"}, fmt.r(vmax))),
      h("span", {class: "dl-lg"}, h("i", {class: "g4-sw none"}), "거래 없음"), h("span", {class: "dl-lg"}, h("i", {class: "g4-sw thin"}), "5건 미만 (흐림)")),
    h("p", {class: "note"}, "칸 하나는 한 요일의 한 시간에 들어간 거래들입니다. 칸마다 거래가 몇 건 안 되어서, 색 하나하나보다 넓게 몰린 무늬를 보세요. 칸에 손가락이나 마우스를 올리면 숫자가 나옵니다."),
    byDay.length === 7 ? ui.disclosure("요일별 숫자", bucketTable(byDay)) : null,
    (x.by_hour || []).length === 24 ? ui.disclosure("시간별 숫자", bucketTable((x.by_hour || []).map((b, i) => ({k: `${i}시`, ...b})))) : null);
}

function hourBars(list, label) {
  if (!list.length) return ui.none("기록 없음");
  return bucketTable(list.map((b, i) => ({k: label(i), ...b})));
}
