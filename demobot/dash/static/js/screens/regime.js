// #/regime 시장 국면 (CONTRACT 8.5): the market's state per coin now (trend from 4h bars, volatility against the
// coin's own last 90 days, since when), a timeline strip per coin from `history`, and every account line's results
// split by the trend and by the volatility at entry (filter by account and leverage). regime.json every 60 s.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {LEVS, COINS, TRENDS, VOLS, TREND_KO, VOL_KO} from "../labels.js";

export async function mount(el, ctx) {
  ctx.setTitle("시장 국면");
  const saved = local.get("regime", {}) || {};
  const f = {acct: saved.acct || "all", lev: saved.lev || "all", by: saved.by === "vol" ? "vol" : "trend"};
  const keep = () => local.set("regime", f);
  const nowBox = h("div"), stripBox = h("div", {class: "stack tight"}), sumBox = h("div");
  const acctSel = h("span");
  const levSeg = ui.seg([{id: "all", label: "전체"}, ...LEVS.map((L) => ({id: String(L), label: `${L}배`}))], f.lev,
    (v) => { f.lev = v; keep(); paintLines(true); }, {label: "배수"});
  const bySeg = ui.seg([{id: "trend", label: "추세로 나눠 보기"}, {id: "vol", label: "변동으로 나눠 보기"}], f.by,
    (v) => { f.by = v; keep(); paintLines(true); }, {label: "나누기"});
  let build = null;
  const pg = ui.pager({size: 25, empty: "맞는 줄이 없습니다", render: (part) => (build ? build(part) : ui.empty("—"))});
  el.append(ui.screenHead("시장 국면", "지금 시장이 오르나, 내리나, 옆으로 가나"),
    ui.card({hero: true, plate: "지금 시장", sub: "코인마다 · 닫힌 봉으로만 판단"}, nowBox),
    ui.card({plate: "흐름", sub: "코인마다 국면이 바뀐 때 · 위 굵은 띠 = 추세, 아래 가는 띠 = 변동"}, stripBox, stripLegend()),
    ui.card({plate: "국면별 성적", sub: "계좌 × 배수마다, 들어갈 때의 국면으로 나눔 (닫힌 거래)", cls: "dl-controls"},
      h("div", {class: "dl-fields"}, ui.field("계좌", acctSel), ui.field("배수", levSeg)),
      h("div", {class: "row wrap"}, bySeg), sumBox, pg.el),
    ui.note("추세: 4시간봉 EMA50의 최근 6봉 기울기를 4시간 ATR로 나눈 값이 +0.5보다 크면 상승 추세, −0.5보다 작으면 하락 추세, "
      + "그 사이는 횡보. 변동: 15분 ATR ÷ 가격을 그 코인의 지난 90일과 비교해 위 30%면 변동 큼, 아래 30%면 변동 작음."));

  let data = null, seen = null;
  async function load() {
    let d;
    try { d = await ctx.api("/api/regime"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!data) put(nowBox, ui.errorBox(e, load));
      return;
    }
    if (d && d.generated_ms != null && d.generated_ms === seen) return;
    seen = d ? d.generated_ms : null;
    data = d;
    if (isMissing(d)) {
      put(nowBox, ui.missing("시장 국면 자료(regime.json)"));
      put(stripBox, ui.none("준비 중"));
      put(acctSel); put(sumBox); pg.set([]);
      return;
    }
    paintNow(d.now || []);
    paintStrips(d.history || [], d.generated_ms);
    const ids = [];
    for (const r of d.lines || []) if (!ids.some((x) => x.id === r.id)) ids.push({id: r.id, name: r.name || r.id});
    if (f.acct !== "all" && !ids.some((x) => x.id === f.acct)) f.acct = "all";
    put(acctSel, ui.select([{id: "all", label: "모든 계좌"}, ...ids.map((x) => ({id: x.id, label: x.name}))], f.acct,
      (v) => { f.acct = v; keep(); paintLines(false); }, "계좌"));
    paintLines(true);
  }

  function paintNow(rows) {
    if (!rows.length) { put(nowBox, ui.none("준비 중")); return; }
    put(nowBox, h("div", {class: "dl-rgnow"}, rows.map((r) => h("div", {class: "dl-rgrow"},
      h("b", {class: "dl-rgcoin"}, fmt.coin(r.coin)),
      ui.regimeChips(r.trend, r.vol),
      h("span", {class: "muted dl-rgsince"}, r.since_ms ? `${fmt.kst(r.since_ms)}부터 (${fmt.ago(r.since_ms)})` : "시작 때 모름"),
      h("span", {class: "muted dl-rgnum", title: "기울기 = EMA50 기울기 ÷ 4시간 ATR · 변동 = 15분 ATR ÷ 가격"},
        `기울기 ${fmt.num(r.slope, 2, true)} · 변동 ${fmt.pct(r.atr_pct, false, 2)}`)))));
  }

  function paintStrips(hist, gen) {
    const byCoin = Object.fromEntries(hist.map((x) => [x.coin, x.points || []]));
    const all = hist.flatMap((x) => (x.points || []).map((p) => Number(p[0]))).filter(Number.isFinite);
    if (!all.length) { put(stripBox, ui.none("기록 없음")); return; }
    const t0 = Math.min(...all), t1 = Math.max(Number(gen) || 0, ...all) || t0 + 1;
    const span = Math.max(1, t1 - t0);
    const rows = COINS.filter((c) => byCoin[c]).map((c) => {
      const pts = byCoin[c].filter((p) => Array.isArray(p) && Number.isFinite(Number(p[0])));
      const segs = (key) => pts.map((p, i) => {
        const a = Number(p[0]), b = i + 1 < pts.length ? Number(pts[i + 1][0]) : t1;
        const w = Math.max(0, (b - a) / span * 100);
        const lab = key === 1 ? p[1] : p[2];
        const ko = key === 1 ? (TREND_KO[lab] || "기록 없음") : (VOL_KO[lab] || "기록 없음");
        return h("i", {class: (key === 1 ? "t-" : "v-") + (lab || "none"),
          style: {width: `${w.toFixed(3)}%`}, title: `${fmt.coin(c)} ${ko} · ${fmt.kst(a)} ~ ${fmt.kst(b)}`});
      });
      return h("div", {class: "dl-strip"}, h("b", {class: "dl-stc"}, fmt.coin(c)),
        h("div", {class: "dl-stbars"}, h("div", {class: "dl-stt"}, segs(1)), h("div", {class: "dl-stv"}, segs(2))));
    });
    const ticks = [];
    for (let k = 0; k <= 4; k++) ticks.push(h("span", {style: {left: `${k * 25}%`}}, fmt.mmdd(t0 + span * k / 4)));
    put(stripBox, rows, h("div", {class: "dl-strip dl-stax"}, h("b", {class: "dl-stc"}), h("div", {class: "dl-stticks"}, ticks)));
  }

  function paintLines(keepPage) {
    if (!data || isMissing(data)) return;
    let rows = data.lines || [];
    if (f.acct !== "all") rows = rows.filter((r) => r.id === f.acct);
    if (f.lev !== "all") rows = rows.filter((r) => String(r.L) === f.lev);
    const keys = f.by === "vol" ? VOLS : TRENDS;
    const kko = f.by === "vol" ? VOL_KO : TREND_KO;
    // all the shown lines together, per regime
    const tot = keys.map((k) => {
      let n = 0, sR = 0, nR = 0, pnl = 0;
      for (const r of rows) {
        const x = (r[f.by] || {})[k] || {};
        n += Number(x.n) || 0;
        pnl += Number(x.pnl) || 0;
        if (x.mean_R != null && Number(x.n) > 0) { sR += Number(x.mean_R) * Number(x.n); nR += Number(x.n); }
      }
      return {k, n, mean_R: nR ? sR / nR : null, pnl};
    });
    put(sumBox, rows.length ? h("div", {class: "stats dl-s3"}, tot.map((x) => {
      const rT = fmt.r(x.mean_R);
      return ui.stat(kko[x.k], ui.signed(rT, fmt.tone(x.mean_R, rT), "b"),
        `${fmt.int(x.n)}건 · ${fmt.money(x.pnl, true)} (보이는 줄 합계)`);
    })) : null);
    const cell = (r, k) => {
      const x = (r[f.by] || {})[k];
      if (!x || !Number(x.n)) return h("span", {class: "muted"}, "거래 없음");
      const rT = fmt.r(x.mean_R), pT = fmt.money(x.pnl, true);
      return h("span", {class: "dl-rgcell"}, ui.signed(rT, fmt.tone(x.mean_R, rT), "b"),
        h("small", {class: "muted"}, `${fmt.int(x.n)}건 · `, ui.signed(pT, fmt.tone(x.pnl, pT))));
    };
    build = (part) => ui.table([
      {label: "계좌", l: true, hcls: "dl-c2", cls: "dl-c2 dl-wrap2", get: (r) => h("a", {href: ctx.href("account", r.id)}, r.name || r.id)},
      {label: "배수", get: (r) => fmt.lev(r.L)},
      ...keys.map((k) => ({label: kko[k], get: (r) => cell(r, k)})),
    ], part, {cls: "dl-rgtbl"});
    pg.set(rows, keepPage);
  }

  await load();
  ctx.every(60000, load);
}

function stripLegend() {
  const it = (cls, text) => h("span", {class: "dl-lg"}, h("i", {class: ["dl-sw", cls]}), text);
  return h("div", {class: "dl-legend"}, it("t-up", "상승 추세"), it("t-down", "하락 추세"), it("t-range", "횡보"),
    it("v-high", "변동 큼"), it("v-normal", "보통"), it("v-low", "변동 작음"), it("t-none", "기록 없음"));
}
