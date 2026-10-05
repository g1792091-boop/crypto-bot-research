// 매매법 상세 › 이 매매법 그림자 (ana8B): /api/analysis/shadows?strategy=<name> (dash/more/shadowplus.py
// strategy_view). This strategy's nightly shadows (규칙 하나만 바꿔 다시 계산: 잠금 / 시간 / 손절 폭 / 익절 / 레버리지)
// against its own base, and its 5-year leverage x stop-width cells (research/levstop) for the live timeframes, 30x / 50x.
// Only the 36 core strategies have both; DeepSeek and the reel say so. HONESTY: descriptive, no verdict; small samples
// say so; the 5-year cells are labelled 5년 (every signal at that fixed multiple, not today's rule B).
import {h, put, ui, fmt, motion} from "../core/pb.js";

const STOPS = ["1.5", "2.0", "2.5", "3.0"];
const TFS = ["15m", "30m", "1h", "4h"];

function shadowTable(D) {
  const groups = D.groups || [];
  const base = D.base || {};
  if (!base.trades) return h("p", {class: "muted"}, "아직 없음 · 이 매매법 계좌의 거래가 끝나고 밤 점검이 돌면 나옵니다 (10건부터 볼 만함).");
  const rows = [];
  for (const g of groups) for (const r of g.rows || []) if (r.trades) rows.push({...r, title: g.title});
  if (!rows.length) return h("p", {class: "muted"}, "그림자 기록이 아직 없습니다.");
  const pg = ui.pager({size: 10, row: (r) => h("div", {class: "lrow an-row", role: "listitem"},
    h("span", {class: "rk"}, r.title), h("span", {class: "lname"}, r.ko || r.variant),
    h("span", {class: ["ret num", fmt.tone(r.vs_base_eq)], title: "그림자 평균 − 같은 거래 base 평균 (자금 대비)"}, fmt.pct(r.vs_base_eq, 2)),
    h("span", {class: "meta"}, h("span", null, `${fmt.int(r.trades)}건`), h("span", null, `자금 대비 ${fmt.pct(r.mean_eq, 2)}`),
      h("span", null, `나음 ${r.better_share == null ? "—" : fmt.pct(r.better_share, 0, false)} · 나쁨 ${r.worse_share == null ? "—" : fmt.pct(r.worse_share, 0, false)}`),
      ui.smallSample(r.trades, D.small_n || 10)))});
  pg.set(rows);
  return h("div", {class: "stack tight"}, h("p", null, `base 그림자 ${fmt.int(base.trades)}건 · 거래당 자금 대비 ${fmt.pct(base.mean_eq, 2)}`), pg.el);
}

function fiveYear(D) {
  const L = D.levstop || {};
  if (L.error) return h("p", {class: "muted"}, String(L.error));
  const by = L.by_tf || {};
  const tfs = TFS.filter((tf) => by[tf]);
  if (!tfs.length) return h("p", {class: "muted"}, "5년 레버리지·손절 칸이 없는 매매법입니다 (기존 36만 있음).");
  // one timeframe at a time (a phone holds four narrow columns, not four timeframes)
  let cur = tfs.includes("1h") ? "1h" : tfs[0];
  const slot = h("div", {class: "stack tight"});      // .stack: min-width 0, so the table scrolls inside its box
  const rows = [];
  for (const lev of ["30", "50"]) for (const st of STOPS) rows.push({arm: `${lev}|${st}`, lev, st});
  const c = (r) => (by[cur] || {})[r.arm] || {};
  const draw = (anim) => {
    put(slot, ui.table([
      {label: "배수·손절", l: true, get: (r) => [`${r.lev}배·${r.st}`, r.st === "2.0" ? h("span", {class: "muted"}, " 지금") : null]},
      {label: "자금 대비", get: (r) => (c(r).mean_eq == null ? "—" : h("span", {class: fmt.tone(c(r).mean_eq)}, fmt.pct(c(r).mean_eq, 2)))},
      {label: "승률", get: (r) => (c(r).win_rate == null ? "—" : fmt.pct(c(r).win_rate, 0, false))},
      {label: "청산", get: (r) => (c(r).liq_share == null ? "—" : fmt.pct(c(r).liq_share, 1, false))},
      {label: "파산", get: (r) => (c(r).periods ? `${fmt.int(c(r).busts)}/${fmt.int(c(r).periods)}` : "—")},
    ], rows));
    if (anim) motion.swap(slot);
  };
  const seg = ui.seg(tfs.map((tf) => ({id: tf, label: fmt.tfKo(tf)})), cur, (id) => { cur = id; draw(true); }, {label: "봉"});
  draw(false);
  return h("div", {class: "stack tight"}, seg, slot,
    h("p", {class: "an-note"}, "배수·손절 = 레버리지 배수와 손절 폭(ATR 배수, 지금 = 2 ATR). 자금 대비 = 거래당 자금 대비 평균, 청산 = 강제청산 비율, 파산 = 기간 2개 중 파산한 기간 (5년, 모든 신호를 그 배수로 고정). 지금 규칙 B(좋은 자리 50배, 보통 30배)와 같지 않습니다. ", L.note || ""));
}

/** The card for #/strategies/<name>: loads its own data; null for a page that is not one of the 36. */
export function stratShadows(ctx, name, kind) {
  if (kind && kind !== "strategy") return null;
  const body = h("div", {class: "stack tight"}, motion.shimmer(3));
  const link = h("a", {class: "btn-line", href: ctx.href("analysis", "shadows")}, "전체 그림자 비교 →");
  const card = ui.card({plate: "이 매매법 그림자", sub: "규칙 하나만 바꿨다면 · 설명용"}, body, link);
  card.style.order = "9";             // after the loss cards on a phone (strategies.css strat-o1..o8)
  let tries = 0;
  const load = () => ctx.api(`/api/analysis/shadows?strategy=${encodeURIComponent(name)}`).then((D) => {
    if (!ctx.alive()) return;
    if (D && D.pending && tries++ < 10) { ctx.timeout(load, 3000); return; }
    if (!D || D.pending) { put(body, h("p", {class: "muted"}, "서버가 아직 계산하는 중입니다. 잠시 뒤 다시 열어 주세요.")); return; }
    put(body, D.error ? h("p", {class: "an-warn"}, String(D.error)) : null,
      h("h3", {class: "an-sub"}, "이번 실험 (밤 점검 그림자)"), shadowTable(D),
      h("h3", {class: "an-sub"}, "5년 시험: 레버리지 × 손절 폭"), fiveYear(D),
      h("p", {class: "an-note"}, D.note || ""));
  }).catch(() => { if (ctx.alive()) put(body, h("p", {class: "muted"}, "불러오지 못했습니다.")); });
  load();
  return card;
}
