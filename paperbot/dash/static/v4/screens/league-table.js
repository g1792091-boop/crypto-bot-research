// 그림자 리그: the coin x timeframe table (one cell per series, every one of the member's coins and timeframes, with the totals per
// coin and per timeframe), the last 50 trades and the signal record (skipped ones included, with the reason).
// HONESTY: a cell that is not recording says so in words (시작 전 / 워밍업 150/300 / 오류), it never shows a 0 that looks recorded;
// totals are pooled over the trades (not an average of cell averages); a trade computed late carries '뒤늦게'.
import {h, ui, fmt} from "../core/pb.js";
import {LABEL, pctB, unavailableCard} from "./league-kit.js";

const tfk = (tf) => fmt.tfKo(tf);
const uniq = (xs) => [...new Set(xs)];

function avgLine(x) {
  return x.closed ? pctB(x.avg_net_pct, 2) : h("span", {class: "muted"}, "—");
}

/** One cell: what the series is doing, else its closed trades and their mean. */
function cell(x) {
  const tip = `${x.status_ko}${x.note ? ` · ${x.note}` : ""} · 신호 ${fmt.int(x.signals)} · 진입 ${fmt.int(x.taken)}`;
  let top, sub;
  if (x.status === "recording" || x.closed || x.open) {
    top = h("span", {class: "lg-n"}, `${fmt.int(x.closed)}건`, x.open ? h("em", null, ` +열림 ${fmt.int(x.open)}`) : null);
    sub = x.status === "recording" ? avgLine(x) : h("span", {class: ["lg-st", x.status]}, x.status_ko);
  } else if (x.status === "warming") {
    top = h("span", {class: "lg-st warming"}, "워밍업");
    sub = h("span", {class: "muted"}, `${fmt.int(x.warm_have)}/${fmt.int(x.warm_need)}`);
  } else {
    top = h("span", {class: ["lg-st", x.status]}, x.status_ko);
    sub = h("span", {class: "muted"}, x.stored ? "" : "기록 없음");
  }
  return h("td", {class: "lg-c", title: tip}, top, sub);
}

export function tableCard(m) {
  const t = m.table;
  if (t.state !== "ok") return unavailableCard("코인 × 봉", t);
  const coins = uniq(t.cells.map((x) => x.coin)), tfs = uniq(t.cells.map((x) => x.tf));
  const at = (coin, tf) => t.cells.find((x) => x.coin === coin && x.tf === tf);
  const total = (x, cls = "lg-c tot") => h("td", {class: cls}, h("span", {class: "lg-n"}, `${fmt.int(x.closed)}건`, x.open ? h("em", null, ` +열림 ${fmt.int(x.open)}`) : null), avgLine(x));
  const grand = m.card.trades;
  const head = h("tr", null, h("th", {class: "l", scope: "col"}, "코인"), tfs.map((tf) => h("th", {scope: "col"}, tfk(tf))), h("th", {scope: "col", class: "tot"}, "합계"));
  const rows = coins.map((coin) => {
    const tot = t.by_coin.find((x) => x.coin === coin);
    return h("tr", null, h("th", {class: "l lg-coin", scope: "row"}, h("b", null, coin), tot ? h("small", {class: "lg-rowtot"}, `${fmt.int(tot.closed)}건`) : null),
      tfs.map((tf) => { const x = at(coin, tf); return x ? cell(x) : h("td", {class: "lg-c"}, ui.notYet("—")); }), tot ? total(tot) : h("td"));
  });
  const foot = h("tr", {class: "lg-foot"}, h("th", {class: "l", scope: "row"}, "합계"), tfs.map((tf) => {
    const x = t.by_tf.find((y) => y.tf === tf);
    return x ? total(x, "lg-c ft") : h("td");
  }), h("td", {class: "lg-c tot"}, grand ? [h("span", {class: "lg-n"}, `${fmt.int(grand.closed)}건`), avgLine({closed: grand.closed, avg_net_pct: grand.avg_net_pct})] : null));
  return ui.card({plate: "코인 × 봉", sub: "칸마다 닫힌 거래 수와 거래당 평균 (1배, 비용 뒤)", cls: "lg-table", label: "코인 × 봉", acts: [ui.pill(LABEL, "thin")]},
    h("table", {class: "lg-mx"}, h("thead", null, head), h("tbody", null, rows), h("tfoot", null, foot)),
    ui.note("칸 위에 올리면(폰은 길게 누르면) 신호·진입 수와 상태가 나와요. 거래가 적은 칸(특히 4시간봉)은 숫자가 크게 흔들려요: 한두 건이 평균을 정해요. 합계는 거래를 모두 모아 다시 낸 평균이에요."));
}

// ---------------------------------------------------------------- the last trades
const RESULT_TONE = {TP: "good", SL: "bad", TIME: "thin", EOD: "thin"};

function tradeRow(t) {
  const open = t.status === "open";
  const res = open ? ui.pill("열려 있음", "accent") : ui.pill(t.reason_ko || "끝남", RESULT_TONE[t.reason] || "thin");
  return h("div", {class: "lg-trade", role: "listitem"},
    h("div", {class: "lg-t1"}, ui.sideTag(t.side), h("b", {class: "lg-tn"}, `${t.coin} ${tfk(t.tf)}`), res,
      t.late ? ui.pill("뒤늦게", "thin", "신호가 난 봉이 켜기 전이라 나중에 계산한 거래예요") : null, h("span", {class: "lg-tnet"}, open ? h("span", {class: "muted"}, "진행 중") : pctB(t.net_pct, 2))),
    h("div", {class: "lg-t2"}, `들어간 때 ${fmt.kst(t.entry_ms)} · 가격 ${fmt.price(t.entry_px)} · 손절 ${fmt.price(t.stop_px)} · 목표 ${fmt.price(t.target_px)}`,
      open ? " · 아직 손절·목표·48봉 어느 쪽에도 닿지 않았어요" : ` · 나간 봉 ${fmt.kst(t.exit_ms)} (${fmt.int(t.hold_bars)}봉 보유) · 비용 전 ${fmt.pctOf(t.gross_pct, 2, true)} → 비용 뒤 ${fmt.pctOf(t.net_pct, 2, true)}`));
}

export function tradesCard(m) {
  const tr = m.trades;
  if (tr.state !== "ok") return unavailableCard("최근 거래", tr);
  const pg = ui.pager({size: 8, row: tradeRow, empty: "아직 가상 거래가 없어요. 신호가 나서 다음 봉 시가에 들어가면 여기에 쌓여요."});
  pg.set(tr.rows);
  return ui.card({plate: "최근 거래", sub: `전체 ${fmt.int(tr.total)}건 중 최근 ${fmt.int(tr.rows.length)}건 · 들어간 때 순`, cls: "lg-trades", label: "최근 거래", acts: [ui.pill(LABEL, "thin")]},
    h("div", {class: "lg-list-wrap", role: "list"}, pg.el),
    ui.note("들어가는 가격은 신호 다음 봉의 시가(5년 시험과 같은 가정)예요. 실제 주문이 그 가격에 체결된다는 뜻이 아니에요. 나간 봉은 손절·목표·48봉에 닿은 봉의 시작 시각이에요. 비용 = 수수료 왕복 + 슬리피지 + 펀딩(5년 시험과 같음)."));
}

// ---------------------------------------------------------------- the signal record
function sigRow(s) {
  return h("div", {class: "lg-trade", role: "listitem"},
    h("div", {class: "lg-t1"}, ui.sideTag(s.side), h("b", {class: "lg-tn"}, `${s.coin} ${tfk(s.tf)}`), ui.pill(s.status_ko, s.status === "taken" ? "good" : "thin"),
      h("span", {class: "lg-tnet muted"}, fmt.kst(s.bar_ms))),
    h("div", {class: "lg-t2"}, `기준가 ${fmt.price(s.plan_entry)} · 손절 ${fmt.price(s.stop)} · 목표 ${s.target == null ? "없음" : fmt.price(s.target)}`,
      s.rr != null ? ` · 손익비 ${fmt.num(s.rr, 1)}` : "", s.touches != null ? ` · 막아 준 횟수 ${fmt.int(s.touches)}` : ""));
}

export function signalsBlock(m) {
  const sg = m.signals;
  if (sg.state !== "ok") return unavailableCard("신호 기록", sg);
  const pg = ui.pager({size: 10, row: sigRow, empty: "아직 신호가 없어요."});
  pg.set(sg.rows);
  return ui.card({plate: "신호 기록", sub: `최근 ${fmt.int(sg.rows.length)}개 · 건너뛴 것도 이유와 함께`, cls: "lg-signals", label: "신호 기록"},
    ui.disclosure("신호 기록 펼치기", h("div", {class: "lg-list-wrap", role: "list"}, pg.el)));
}
