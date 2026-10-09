// #/review?w=<start_ms> 주간 회의록 (CONTRACT 8.10): one KST week (Monday 00:00 to Sunday 24:00) made by code from the
// numbers: what the owners have to decide (first, big), what happened in plain sentences, the numbers, the judgment
// (closer / further from "우리 기준"), what the stop rules saved or cost, how much the real costs ate, the market
// and the view log. The current week is marked "진행 중". review.json every 60 s.
// Round 5 stage 2B (the rule bot's v4 회의 요약 · 주간 성적표 look, digest-week / digest-board; no AI parts: this record
// is made by code): the week navigation (◀ 이전 주 · the week · 다음 주 ▶, every week in a menu), what to decide first,
// the summary, four stat cards that count to new values, the best / worst lines as v4 ranked rows (the pixel
// character, the leverage, the P&L), the kinds as share bars, the judgment, the stop rules and the costs, the market.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {COINS, TRENDS, TREND_KO, kindOfId} from "../labels.js";

const figOf = (id) => K4.acctFig({id, kind: kindOfId(id), short: String(id).split("-").find((p) => /^(S2|N02|N04)$/.test(p))}, 18);

export async function mount(el, ctx) {
  ctx.setTitle("주간 회의록");
  let pick = ctx.params.query.w || null;
  const pickBox = h("div", {class: "s2-wknav"});
  const body = h("div", {class: "stack"});
  const nTr = K4.liveNum(null, {format: (v) => fmt.int(v), flash: "accent"});
  const nUp = K4.liveNum(null, {format: (v) => fmt.int(v), flash: "accent"});
  const nDn = K4.liveNum(null, {format: (v) => fmt.int(v), flash: "accent"});
  const vSub = h("span", {class: "s"}, "—"), vNum = h("b", {class: "num"}, "—");
  const stats = h("div", {class: "stats s4 s2-stats"},
    K4.stat("닫힌 거래", nTr, "모든 줄 합계"), K4.stat("오른 계좌", nUp, "이 주 손익 +", "good"),
    K4.stat("내린 계좌", nDn, "이 주 손익 −", "bad"), K4.stat("관점", vNum, vSub));
  el.append(ui.screenHead("주간 회의록", "한 주를 숫자로 정리한 회의록 (사람이 아니라 코드가 씁니다)"), pickBox, body,
    ui.note("매주 월요일 09:00에 지난주 회의록이 텔레그램으로도 갑니다. 진행 중인 주는 지금까지의 숫자입니다."));

  let data = null, seen = null;
  async function load() {
    let d;
    try { d = await ctx.api("/api/review"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!data) put(body, ui.errorBox(e, load));
      return;
    }
    if (d && d.generated_ms != null && d.generated_ms === seen) return;
    seen = d ? d.generated_ms : null;
    data = d;
    if (isMissing(d) || !(d.weeks || []).length) {
      put(pickBox);
      put(body, isMissing(d) ? ui.missing("주간 회의록(review.json)") : ui.none("아직 회의록이 없습니다"));
      return;
    }
    paint(false);
  }

  function go(v) { pick = String(v); ctx.setQuery({w: pick}); paint(true); }
  function paint(user) {
    const weeks = data.weeks;
    let w = weeks.find((x) => String(x.start_ms) === String(pick)) || weeks[0];
    pick = String(w.start_ms);
    const i = weeks.indexOf(w);                       // weeks come newest first
    const label = (x) => `${x.week_ko || fmt.mmdd(x.start_ms)}${x.final ? "" : " · 진행 중"}`;
    const older = weeks[i + 1], newer = weeks[i - 1];
    put(pickBox,
      h("button", {type: "button", class: "btn-line", disabled: !older || null, title: "지난주", onclick: () => older && go(older.start_ms)}, "◀ 이전 주"),
      h("b", {class: "s2-wklabel"}, w.week_ko || fmt.mmdd(w.start_ms)),
      w.final ? ui.pill("끝난 주", "thin") : ui.pill("진행 중", "accent"),
      h("button", {type: "button", class: "btn-line", disabled: !newer || null, title: "다음 주", onclick: () => newer && go(newer.start_ms)}, "다음 주 ▶"),
      h("span", {class: "grow"}),
      h("span", {class: "k4-barg s2-g"}, h("span", {class: "k4-k"}, "주"),
        ui.select(weeks.map((x) => ({id: String(x.start_ms), label: label(x)})), pick, (v) => go(v), "주 고르기")));
    if (user) for (const n of [nTr, nUp, nDn]) delete n.dataset.v;
    const n = w.numbers || {}, v = w.views || {};
    nTr.update(n.trades); nUp.update(n.accounts_up); nDn.update(n.accounts_down);
    vNum.textContent = `${fmt.int(v.n)}개`;
    vSub.textContent = v.dir24_rate != null ? `끝난 것 ${fmt.int(v.done)}개 · 24시간 방향 ${fmt.ratio(v.dir24_rate)}` : `끝난 것 ${fmt.int(v.done)}개`;
    put(body, week(w, ctx, stats));
    if (user) K4.swap(body);
  }

  await load();
  ctx.every(60000, load);
}

const lineRef = (x, ctx) => h("a", {class: "s2-aname", href: ctx.href("account", x.id), title: `${x.name || x.id} ${fmt.lev(x.L)}`}, figOf(x.id), x.name || x.id);

function week(w, ctx, stats) {
  const n = w.numbers || {}, j = w.judge || {}, s = w.stops || {}, c = w.costs || {};
  const decide = w.decide_ko || [];
  const pctCell = (x) => { const t = fmt.pct(x, true); return ui.signed(t, fmt.tone(x, t), "b"); };
  // v4 ranked rows (digest-week rankRows): the leverage where the rank goes, the account, the number on the right
  const list = (rows, val, empty) => (rows && rows.length ? h("div", {class: "dl-list s2-wklist", role: "list"}, rows.map((x) => h("div", {class: "lrow", role: "listitem"},
    h("span", {class: "rk"}, fmt.lev(x.L)), h("span", {class: "lname"}, lineRef(x, ctx)), h("span", {class: "ret"}, val(x))))) : ui.none(empty || "없음"));
  const kinds = n.by_kind || [];
  const kmax = Math.max(1, ...kinds.map((x) => Math.abs(Number(x.mean_pnl_pct) || 0)));
  return [
    ui.card({hero: true, plate: w.final ? "두 분이 정할 것" : "두 분이 정할 것 (지금까지)", cls: "dl-decide",
      sub: `${w.week_ko || ""}${w.final ? "" : " · 진행 중"}`},
    decide.length ? h("ol", {class: "dl-decl"}, decide.map((x) => h("li", null, x)))
      : h("p", {class: "dl-vline"}, w.final ? "이 주는 정할 것이 없었습니다." : "지금까지는 정할 것이 없습니다.")),
    ui.card({plate: "한 주 요약"}, (w.summary_ko || []).length ? h("div", {class: "stack tight dl-sum s2-wksum"}, w.summary_ko.map((x) => h("p", null, x))) : ui.none()),
    stats,
    h("div", {class: "grid2"},
      ui.card({plate: "잘 된 줄", sub: "이 주 손익 (시작 $1,000 대비)"}, list(n.best, (x) => pctCell(x.pnl_pct))),
      ui.card({plate: "안 된 줄", sub: "이 주 손익 (시작 $1,000 대비)"}, list(n.worst, (x) => pctCell(x.pnl_pct)))),
    ui.card({plate: "종류별 평균", sub: "계좌 종류마다 줄 평균"}, kinds.length ? h("div", {class: "s2-kbars"}, kinds.map((x) => {
      const v = Number(x.mean_pnl_pct);
      const w2 = Number.isFinite(v) ? Math.min(50, Math.abs(v) / kmax * 50) : 0;
      return h("div", {class: "s2-kbrow", dataset: {kind: x.kind}}, h("span", {class: "s2-kbk"}, h("i", {class: "k4-sw", "aria-hidden": "true"}), x.kind_ko || x.kind || "—"),
        h("span", {class: "s2-kbt", "aria-hidden": "true"}, h("i", {class: v >= 0 ? "pos" : "neg", style: {"--w": `${w2.toFixed(1)}%`}})), pctCell(x.mean_pnl_pct));
    })) : ui.none()),
    ui.card({plate: "판정", sub: w.final ? "주가 끝났을 때" : "지금"},
      h("div", {class: "stats s2-stats s2-s3"}, ui.stat("우리 기준 통과", `${fmt.int(j.passed)}줄`),
        ui.stat("확인 기간", `${fmt.int(j.confirming)}줄`), ui.stat("실전 후보", `${fmt.int(j.candidates)}줄`, null, Number(j.candidates) ? "good" : null)),
      h("div", {class: "grid2"},
        h("div", {class: "stack tight"}, h("p", {class: "s2-sub"}, "기준에 가까워진 줄"),
          list(j.closer, (x) => h("span", {class: "num up"}, `${fmt.int(x.ok_from)} → ${fmt.int(x.ok_to)} / 5`), "없음")),
        h("div", {class: "stack tight"}, h("p", {class: "s2-sub"}, "기준에서 멀어진 줄"),
          list(j.further, (x) => h("span", {class: "num down"}, `${fmt.int(x.ok_from)} → ${fmt.int(x.ok_to)} / 5`), "없음")))),
    h("div", {class: "grid2"},
      ui.card({plate: "정지 규칙", sub: "정지 규칙을 썼다면 손익이 얼마나 달랐나 (%p)"},
        h("p", {class: "dl-vline"}, s.net_pct == null ? "기록 없음" : Number(s.net_pct) >= 0
          ? `줄마다 평균 ${fmt.num(s.net_pct, 1)}%p 덜 잃었습니다.` : `줄마다 평균 ${fmt.num(-Number(s.net_pct), 1)}%p 더 나빴습니다.`),
        h("p", {class: "s2-sub"}, "덕 본 줄"), list(s.saved, (x) => pctCell(x.diff_pct)),
        h("p", {class: "s2-sub"}, "손해 본 줄"), list(s.cost, (x) => pctCell(x.diff_pct))),
      ui.card({plate: "실제 비용", sub: "호가창에서 잰 진입 비용"},
        h("p", {class: "dl-vline"}, c.median_entry_bps == null ? "잰 값 없음"
          : `진입 비용 중간값 ${fmt.num(c.median_entry_bps, 2)}bp (가정 ${fmt.num(c.assumed_bps ?? 2, 0)}bp)`),
        h("p", {class: "s2-sub"}, "번 돈을 비용이 많이 먹은 줄"),
        list(c.eaten, (x) => h("span", {class: "num warn-t"}, `번 돈의 ${fmt.ratio(x.share, 0)}`)))),
    ui.card({plate: "시장", sub: "코인마다 이 주에 각 추세였던 시간 비율 · 오른쪽 = 주 끝 국면"}, regimeTable(w.regime || [])),
  ];
}

function regimeTable(rows) {
  if (!rows.length) return ui.none();
  const by = Object.fromEntries(rows.map((r) => [r.coin, r]));
  return h("div", {class: "dl-wkrg"}, COINS.filter((c) => by[c]).map((c) => {
    const r = by[c], sh = r.share || {};
    return h("div", {class: "dl-wkrow"}, h("b", {class: "dl-rgcoin"}, fmt.coin(c)),
      h("div", {class: "dl-share", role: "img", "aria-label": TRENDS.map((t) => `${TREND_KO[t]} ${fmt.ratio(sh[t], 0)}`).join(", ")},
        TRENDS.map((t) => h("i", {class: "t-" + t, style: {width: `${Math.max(0, Number(sh[t]) || 0) * 100}%`}, title: `${TREND_KO[t]} ${fmt.ratio(sh[t], 0)}`}))),
      h("span", {class: "dl-wkpct muted"}, TRENDS.map((t) => `${TREND_KO[t].replace(" 추세", "")} ${fmt.ratio(sh[t], 0)}`).join(" · ")),
      ui.regimeChips(r.trend, r.vol));
  }), h("div", {class: "dl-legend"}, TRENDS.map((t) => h("span", {class: "dl-lg"}, h("i", {class: ["dl-sw", "t-" + t]}), TREND_KO[t]))));
}
