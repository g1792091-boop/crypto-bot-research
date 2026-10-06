// 그림자 리그: '5년 시험은 이랬어요'. The pre-registered 5-year test of the member's rule (numbers from the committed result
// document, paperbot/dash/data/league_studies.json, checked against docs/zoneflip-reel by tests/test_dash_league.py) next to
// the live record, timeframe by timeframe, so the owners see at a glance whether the live record has the shape of the study's.
// HONESTY: the verdict is written plainly (실패), the hashes and the run date are shown, the live side says 표본 적음 under 30 closed
// trades and a missing table is not 0; nothing here is a verdict on the live record (참고용, 판정 아님).
import {h, ui, fmt} from "../core/pb.js";
import {LABEL, pctB} from "./league-kit.js";

const TFS = ["15m", "30m", "1h", "4h"];
const PER = [["is", "1기"], ["oos", "2기"], ["pre", "3기"]];
const tfk = (tf) => fmt.tfKo(tf);

/** How many of the study's period x timeframe cells lost money per trade after costs: {neg, all}. */
export function lossCells(s) {
  let neg = 0, all = 0;
  for (const tf of TFS) for (const [k] of PER) {
    const r = ((s.main || {})[tf] || {})[k];
    if (r && r.net_pct != null) { all++; if (r.net_pct < 0) neg++; }
  }
  return {neg, all};
}

/** why: why there is no live row: "none" = nothing was ever recorded, "error" = the file could not be read, else a table is missing. */
function liveCell(r, need, why) {
  if (!r) {
    return why === "none" ? h("span", {class: "muted"}, "아직 기록이 없어요") : why === "error" ? ui.notYet("읽지 못함", "기록 파일을 읽지 못했어요") : ui.notYet("표 없음");
  }
  const l = r.live;
  if (!l.trades) return h("span", {class: "muted"}, "아직 닫힌 거래가 없어요");
  return h("span", {class: "lg-cellcol"}, h("span", null, pctB(l.net_pct, 2), " ", h("small", {class: "muted"}, "거래당")),
    h("small", {class: "muted"}, `${fmt.int(l.trades)}건 · 승률 ${fmt.pctOf(l.win_pct, 0)}`), ui.smallSample(l.trades, need));
}
function perCell(p) {
  if (!p) return h("span", {class: "muted"}, "—");
  return h("span", {class: "lg-cellcol"}, h("span", null, pctB(p.net_pct, 2), " ", h("small", {class: "muted"}, "거래당")),
    h("small", {class: "muted"}, `${fmt.int(p.trades)}건 · 승률 ${fmt.pctOf(p.win_pct, 0)}`));
}
function flipCell(f) {
  if (!f) return h("span", {class: "muted"}, "—");
  return h("span", {class: "lg-cellcol"}, h("span", null, "이 규칙 ", pctB(f.main_pct, 2)), h("small", {class: "muted"}, `동전 던지기 ${fmt.pctOf(f.flip_pct, 2, true)}`));
}

function sideBySide(s, rows, need, why) {
  const byTf = Object.fromEntries((rows || []).map((r) => [r.tf, r]));
  const dist = (tf) => { const d = (s.distance_pct || {})[tf]; return d ? `손절 ${fmt.num(d.stop[0], 1)}~${fmt.num(d.stop[1], 1)}% · 목표 ${fmt.num(d.target[0], 1)}~${fmt.num(d.target[1], 1)}%` : ""; };
  const wide = h("div", {class: "tbl-wrap lg-wide"}, h("table", {class: "tbl lg-cmp"},
    h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "봉"), h("th", {class: "live", scope: "col"}, "지금 (라이브)"),
      PER.map(([k, ko]) => h("th", {scope: "col", title: (s.periods || {})[k]}, `5년 시험 ${ko}`)), h("th", {scope: "col"}, "동전 던지기와 (5년 1·2기)"))),
    h("tbody", null, TFS.map((tf) => h("tr", null, h("th", {class: "l", scope: "row"}, h("b", null, tfk(tf)), h("small", {class: "muted"}, dist(tf))),
      h("td", {class: "live"}, liveCell(byTf[tf], need, why)),
      PER.map(([k]) => h("td", null, perCell(((s.main || {})[tf] || {})[k]))), h("td", null, flipCell((s.vs_flip || {})[tf])))))));
  const stack = h("div", {class: "lg-stack"}, TFS.map((tf) => h("section", {class: "lg-sblock", "aria-label": tfk(tf)},
    h("h3", null, tfk(tf), h("small", {class: "muted"}, ` ${dist(tf)}`)),
    h("dl", null, h("dt", null, "지금 (라이브)"), h("dd", null, liveCell(byTf[tf], need, why)),
      PER.map(([k, ko]) => [h("dt", null, `5년 시험 ${ko}`), h("dd", null, perCell(((s.main || {})[tf] || {})[k]))]),
      h("dt", null, "동전 던지기와"), h("dd", null, flipCell((s.vs_flip || {})[tf]))))));
  return [wide, stack];
}

function allNumbers(s) {
  const rows = [];
  for (const tf of TFS) for (const [k, ko] of PER) {
    const r = ((s.main || {})[tf] || {})[k];
    if (r) rows.push(h("tr", null, h("th", {class: "l", scope: "row"}, `${tfk(tf)} ${ko}`), h("td", null, fmt.int(r.trades)), h("td", null, fmt.pctOf(r.win_pct, 1)),
      h("td", null, fmt.pctOf(r.avg_win_pct, 2, true)), h("td", null, fmt.pctOf(r.avg_loss_pct, 2, true)), h("td", null, fmt.num(r.pf, 2)), h("td", null, pctB(r.net_pct, 2)),
      h("td", null, fmt.pctOf(r.gross_pct, 2, true)), h("td", null, r.coins_of ? `${fmt.int(r.coins_positive)} / ${fmt.int(r.coins_of)}` : "—"),
      h("td", null, fmt.pctOf(r.flip_net_pct, 2, true)), h("td", null, `${fmt.num(r.account_x, 2)}배`)));
  }
  const cols = ["거래", "승률", "평균 이익", "평균 손실", "손익비(PF)", "거래당 (비용 뒤)", "비용 전", "플러스 코인", "동전 평균", "가상 계좌 끝"];
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl"}, h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "봉·기간"), cols.map((c) => h("th", {scope: "col"}, c)))),
    h("tbody", null, rows)));
}

function readingBlock(s) {
  const flipRows = TFS.map((tf) => ({tf, v: (s.vs_flip || {})[tf], p12: (s.p12 || {})[tf]})).filter((x) => x.v);
  return h("div", {class: "lg-read-box"},
    s.rules_ko ? h("p", null, h("b", null, "규칙 "), s.rules_ko) : null,
    h("ul", {class: "lg-list"}, (s.reading_ko || []).map((x) => h("li", null, x)), s.ctrl_ko ? h("li", null, s.ctrl_ko) : null),
    s.cost_note_ko ? h("p", {class: "lg-sub"}, s.cost_note_ko) : null,
    flipRows.length ? h("div", {class: "tbl-wrap"}, h("table", {class: "tbl"}, h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "봉"), h("th", {scope: "col"}, "이 규칙"),
      h("th", {scope: "col"}, "동전 던지기"), h("th", {scope: "col", title: "1에 가까울수록 '우연보다 나을 게 없다'는 쪽이에요"}, "p (동전과)"), h("th", {scope: "col", title: "1에 가까울수록 '0보다 나을 게 없다'는 쪽이에요"}, "p (0과)"))),
      h("tbody", null, flipRows.map((x) => h("tr", null, h("th", {class: "l", scope: "row"}, tfk(x.tf)), h("td", null, pctB(x.v.main_pct, 2)), h("td", null, fmt.pctOf(x.v.flip_pct, 2, true)),
        h("td", null, fmt.num(x.v.p, 2)), h("td", null, x.p12 == null ? "—" : fmt.num(x.p12, 2))))))) : null,
    h("p", {class: "lg-sub"}, "p는 '우연으로도 이만큼 나올 수 있는 정도'를 나타내는 숫자예요. 1에 가까우면 이 규칙이 우연(또는 0)보다 나을 게 없다는 쪽이에요. 5년 시험 안에서의 값이고, 라이브 기록의 판정이 아니에요."));
}

function proof(s) {
  return ui.kv([["시험한 날", s.run_date], ["사전 등록 해시", h("code", {class: "lg-hash"}, s.prereg_sha256)], ["결과 문서 해시", h("code", {class: "lg-hash"}, s.results_sha256)],
    ["규칙 코드 해시", h("code", {class: "lg-hash"}, s.code_sha256)], ["문서 위치", s.where], ["자료 기간", `${s.window_ko || ""}`]]);
}

/** d: the endpoint's answer, m: the member's detail. Always drawn: it does not depend on the live record. */
export function studyCard(d, m) {
  const need = d.min_trades || 30;
  if (d.studies_state !== "ok") {
    return ui.card({plate: "5년 시험은 이랬어요", sub: LABEL, cls: "lg-study", id: "lg-study"},
      h("p", {class: "lg-warn"}, ui.pill("못 읽음", "warn"), ` ${d.studies_reason_ko || "5년 시험 숫자를 읽지 못했어요"}. 그래서 이 칸을 비워 두었어요(5년 시험이 없었다는 뜻이 아니에요).`));
  }
  const s = m ? m.study : null;
  if (!s) {
    return ui.card({plate: "5년 시험은 이랬어요", sub: LABEL, cls: "lg-study", id: "lg-study"},
      h("p", {class: "lg-warn"}, ui.pill("자료 없음", "warn"), " 이 멤버의 5년 시험 숫자를 이 화면이 아직 몰라요. 5년 시험 결과 문서가 있어야 라이브 기록 옆에 나란히 놓을 수 있어요."));
  }
  const loss = lossCells(s);
  const rows = m.comparison && m.comparison.state === "ok" ? m.comparison.rows : null;
  return ui.card({plate: "5년 시험은 이랬어요", title: s.title_ko, sub: `${s.run_date} 시험 · 사전 등록 ${s.prereg_sha256.slice(0, 8)}…`, cls: "lg-study", id: "lg-study", label: "5년 시험은 이랬어요",
    acts: [ui.pill(s.verdict_ko, s.verdict === "FAIL" ? "bad" : "thin"), ui.pill(LABEL, "thin")]},
  h("p", {class: "lg-verdict"}, h("b", null, `${s.verdict_ko}. `), s.one_line_ko),
  h("div", {class: "stats lg-stats"},
    ui.stat("미리 정한 관문을 넘은 칸", `${fmt.int(s.cells_passed)} / ${fmt.int(s.cells)}`, "봉 4개 × 본 규칙·대조"),
    ui.stat("비용 뒤 거래당 손실인 칸", `${fmt.int(loss.neg)} / ${fmt.int(loss.all)}`, "봉 4개 × 세 기간"),
    ui.stat("본 규칙 거래 수", `${fmt.int(s.trades_main)}건`, `대조 설정 ${fmt.int(s.trades_ctrl)}건은 따로 셈`)),
  h("p", {class: "lg-sub"}, s.honest_ko),
  h("h3", {class: "lg-h3"}, "5년 시험과 지금, 봉마다 나란히"),
  ...sideBySide(s, rows, need, d.state === "error" || (d.member && d.member.state === "error") ? "error" : !m.comparison ? "none" : "table"),
  ui.note("지금 기록은 거래가 적어서 숫자 차이를 해석하지 않는 게 맞아요. 5년 시험은 비용 뒤 거래당 평균(1배)이고, 라이브도 같은 비용을 뺀 1배 기준이에요."),
  ui.disclosure("5년 시험 숫자 전부 (봉 × 기간)", allNumbers(s)),
  ui.disclosure("규칙 · 읽는 법 · 동전 던지기와 비교", readingBlock(s)),
  ui.disclosure("사전 등록과 해시 (미리 정한 규칙이 그대로인지 확인하는 값)", proof(s)));
}
