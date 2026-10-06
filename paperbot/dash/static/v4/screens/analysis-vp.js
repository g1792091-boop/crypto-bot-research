// 분석 › 매물대 (owners' request 2026-10-06; /api/analysis/vp?group=, agents/entrymoment.vp_dash_view). A group's closed
// trades by the price level ahead at entry (its kind: 매물대 / 스윙 / 전일·전주 / 라운드 / 상위 봉, and its distance in ATR)
// and by where the entry sat against the volume profile (매물대 위 / 70% 구간 안 / 아래 / 최다 가격 근처), each next to the
// group's own coin flips in the same cells; the trades entered with a 매물대 right ahead, per strategy; and the 5-year entry
// study A's 매물대 rows (research/entry_study, read only: no edge found, the server builds the plain lines from the
// files' own counts). Counts, win rates and ROE only (no money for any group, DeepSeek included). Descriptive: many
// cells are looked at, so one odd cell is a hypothesis, never a rule. Every card set next to the coin flips carries
// ui.refNote (참고 until the verdict, CONTRACT section 1.3).
import {h, put, ui, fmt, motion} from "../core/pb.js";
import {viewHead, thin, dimSeg, groupWords, pp} from "./analysis-kit.js";

const DIM_KO = {sr_ahead: "앞 가격대 종류", sr_room: "앞 가격대까지", va_pos: "매물대 안·밖"};
const BK_KO = {"바로 앞": "바로 앞 (ATR 0.5 미만)", "가까움": "가까움 (ATR 0.5~1)", "보통": "보통 (ATR 1~2)", "멂": "멂 (ATR 2 이상)",
  "최다 가격 근처": "최다 가격 근처 (ATR 0.25 안)", "70% 구간 안": "거래량 70% 구간 안", "상위 봉": "상위 봉 스윙", "스윙": "스윙 고저",
  "전일·전주": "전일·전주 고저", "라운드": "라운드 넘버", unknown: "모름 (기록 없음)"};
const bk = (b) => BK_KO[b] || b;

/** One table: the group's cell and the coin flips' cell for each bucket (n, win rate, ROE; never money). */
function sideBySide(t, f, order, min, W) {
  t = t || {}; f = f || {};
  const keys = [...order.filter((b) => t[b] || f[b]), ...Object.keys(t).filter((b) => !order.includes(b))];
  if (!keys.length) return ui.empty("아직 이 칸에 든 거래가 없습니다.");
  const c = (x, k) => (x ? k(x) : "—");
  return ui.table([
    {label: "칸", l: true, get: (b) => h("span", {class: t[b] && t[b].n >= min ? "" : "muted"}, bk(b))},
    {label: `${W.short} 거래`, get: (b) => c(t[b], (x) => fmt.int(x.n))},
    {label: "승률", get: (b) => c(t[b], (x) => fmt.pct(x.wr, 0, false))},
    {label: "평균 ROE", get: (b) => c(t[b], (x) => h("span", {class: fmt.tone(x.roe)}, fmt.pct(x.roe)))},
    {label: `${W.flips} 거래`, get: (b) => c(f[b], (x) => fmt.int(x.n))},
    {label: "승률", get: (b) => c(f[b], (x) => fmt.pct(x.wr, 0, false))},
    {label: "평균 ROE", get: (b) => c(f[b], (x) => h("span", {class: fmt.tone(x.roe)}, fmt.pct(x.roe)))},
    {label: "", get: (b) => (t[b] && t[b].n < min ? ui.smallSample(t[b].n, min) : "")},
  ], keys);
}

const STUDY_SMALL = 200;        // the study's own '*' line (RESULTS_ENTRY_A.md section 4: under 200 trades)
const share = (n, of) => (of ? fmt.pct(n / of, 0, false) : "—");

export function vp(d, env) {
  const grp = d.group || "core", W = groupWords(grp), min = d.min_n || 10;
  const cov = d.coverage || {}, mc = d.multiple_comparisons || {}, order = d.bucket_order || {};
  const out = [viewHead({plate: "매물대", q: "매물대(거래가 몰린 가격대) 바로 앞이나 안·밖에서 들어간 거래는 어땠나",
    meta: `${d.group_label || W.who}의 끝난 거래 ${fmt.int(d.trades || 0)}건 · ${W.flips} ${fmt.int(d.flip_trades || 0)}건 · 칸 최소 ${fmt.int(min)}건 · 거래 수·승률·ROE만 (돈 숫자 없음)`,
    at: d.computed_at || d.generated_ms, stale: d.stale,
    read: d.how_to_read || "거래 방향 앞 가격대의 종류와 거리, 매물대 안·밖으로 끝난 거래를 나눴습니다.",
    warn: [thin(d.trades || 0, 100, `${W.short} 끝난 거래`), mc.note || null,
      d.no_money ? h("p", {class: "an-read"}, ui.pill("돈 숫자 없음", "ref"), " 딥시크는 거래 수와 비율만 봅니다.") : null]})];
  const s5 = study(d.study_5y, grp);
  if (!d.trades && !d.flip_trades) {
    out.push(ui.card({}, ui.empty(d.note || "아직 끝난 거래가 없습니다.")));
    if (s5) out.push(s5);
    return out;
  }
  const mine = d.mine || {}, flips = d.coin_flips || {};
  const dims = (d.dims || Object.keys(DIM_KO)).filter((k) => DIM_KO[k]);
  const body = h("div");
  const seg = dimSeg("vp", dims.map((k) => ({id: k, label: DIM_KO[k]})), dims[0], () => paint(true), true);
  function paint(anim) {
    const k = seg.get();
    put(body, sideBySide((mine.buckets || {})[k], (flips.buckets || {})[k], order[k] || [], min, W));
    if (anim) motion.swap(body);
  }
  paint(false);
  const T = d.trades || 0, F = d.flip_trades || 0;
  out.push(ui.card({plate: "모습별 성적", sub: `${W.short}와 ${W.flips} 나란히`}, seg.el, body,
    h("p", {class: "an-note"}, `자료가 붙은 비율: 앞 가격대 ${share(cov.sr || 0, T)} · 매물대 안·밖 ${share(cov.va || 0, T)}`,
      ` (${W.flips} ${share(cov.flip_sr || 0, F)} · ${share(cov.flip_va || 0, F)}). 매물대 안·밖은 같은 봉 200개가 빠짐없이 쌓인 뒤부터 계산합니다 (그 전과 거래량 기록이 없으면 모름).`,
      cov.bars_note ? ` ${cov.bars_note}.` : ""),
    h("p", {class: "an-note"}, W.flipNote), ui.refNote(env.verdictTs)));

  // a 매물대 right ahead: by distance, then per strategy
  const ru = d.right_under || {};
  const rows = ru.rows || [];
  // the 36 open their strategy page; DeepSeek definitions and the reel are named only (no per-definition page link here)
  const unit = grp === "ds200" ? "정의" : "매매법";
  const pg = ui.pager({size: 10, empty: "아직 매물대 바로 앞에서 들어간 거래가 없습니다.",
    row: (x) => h(grp === "core" ? "a" : "div",
      {class: ["lrow an-row", grp === "core" ? "click" : ""], role: "listitem", href: grp === "core" ? env.ctx.href("strategies", x.strategy) : null},
      h("span", {class: "rk"}, String(x.strategy).split("_")[0]), h("span", {class: "lname"}, x.name_ko || x.strategy),
      h("span", {class: ["ret num", fmt.tone(x.roe)]}, fmt.pct(x.roe)),
      h("span", {class: "meta"}, h("span", null, `${fmt.int(x.n)}건 · 승률 ${fmt.pct(x.wr, 0, false)}`),
        h("span", null, `이 ${unit} 거래의 ${fmt.pct(x.share, 0, false)}`),
        h("span", null, `${unit} 평균 ${fmt.pct(x.strategy_roe)} (${fmt.int(x.strategy_n)}건)`), ui.smallSample(x.n, min)))});
  pg.set(rows);
  const list = pg.el;
  const a = ru.all || {}, fa = ru.coin_flips || {};
  out.push(ui.card({plate: "매물대가 거래 방향 바로 앞", sub: "롱이면 위쪽, 숏이면 아래쪽 매물대가 0.5 ATR 안"},
    // a plain paragraph (not .an-read: its <b> is the accent label colour, which would hide the ROE's up/down tone)
    h("p", null, a.n ? [`${W.short} ${fmt.int(a.n)}건 · 승률 ${fmt.pct(a.wr, 0, false)} · 평균 ROE `, h("b", {class: fmt.tone(a.roe)}, fmt.pct(a.roe)), " ", ui.smallSample(a.n, min)] : `${W.short} 0건`,
      " / ", fa.n ? [`${W.flips} ${fmt.int(fa.n)}건 · 승률 ${fmt.pct(fa.wr, 0, false)} · 평균 ROE `, h("b", {class: fmt.tone(fa.roe)}, fmt.pct(fa.roe))] : `${W.flips} 0건`),
    h("p", {class: "an-sub"}, "앞 가격대가 매물대인 거래 · 거리별"),
    sideBySide(mine.under_vp, flips.under_vp, order.sr_room || [], min, W),
    h("p", {class: "an-sub"}, `매물대 바로 앞에서 들어간 거래가 많은 순 (${fmt.int(ru.total || 0)}개 중 최대 10개)`), list,
    h("p", {class: "an-note"}, "같은 칸의 동전 봇도 비슷하면 그 매매법 탓이 아니라 그 자리 자체의 성질일 수 있습니다. 칸이 많아 차이는 가설로만 봅니다."),
    ui.refNote(env.verdictTs)));

  // va_pos is a price position: a long and a short read it differently
  out.push(ui.card({plate: "매물대 안·밖 · 롱과 숏", sub: "가격 위치라 롱·숏을 나눠 봅니다"},
    h("p", {class: "an-sub"}, "롱"), sideBySide(mine.va_long, flips.va_long, order.va_pos || [], min, W),
    h("p", {class: "an-sub"}, "숏"), sideBySide(mine.va_short, flips.va_short, order.va_pos || [], min, W),
    h("p", {class: "an-note"}, "롱이 매물대 위에서 들어가면 매물대를 벗어나 오른 뒤의 추격, 숏이 매물대 위에서 들어가면 위로 벗어난 곳에서 되돌림을 노리는 자리입니다."),
    ui.refNote(env.verdictTs)));
  if (s5) out.push(s5);
  if (d.note) out.push(h("p", {class: "an-note an-foot"}, d.note));
  return out;
}

/** The 5-year entry study A's 매물대 rows (참고). The verdict and headline lines come from the server (built from the
 *  committed files' own counts); this only lays them out. */
function study(s, grp) {
  if (!s) return null;
  if (!s.available) return ui.card({plate: "5년 진입 연구 · 매물대", sub: "참고"}, h("p", {class: "muted"}, s.note || "5년 연구 결과를 읽지 못했습니다."));
  const rows = [];
  for (const r of s.rows || []) for (const p of r.periods || []) rows.push({tf: r.tf, p, same: r.same_sign_3, rsame: r.random_same_sign_3});
  const st = (x, k) => (x.p.strategies ? k(x.p.strategies) : "—");
  const rn = (x, k) => (x.p.random ? k(x.p.random) : "—");
  const src = s.source || {};
  return ui.card({plate: "5년 진입 연구 · 매물대", sub: "참고 · 설명용 표"},
    s.verdict_ko ? h("p", {class: "an-read"}, h("b", null, "결론 "), s.verdict_ko) : null,
    s.headline_ko ? h("p", {class: "an-read"}, s.headline_ko) : null,
    ui.table([
      {label: "봉", l: true, get: (x) => fmt.tfKo(x.tf)},
      {label: "기간", l: true, get: (x) => x.p.label},
      {label: "매물대가 앞인 비중", get: (x) => st(x, (v) => fmt.pct(v.share, 0, false))},
      {label: "그 거래 평균 ROE", get: (x) => st(x, (v) => h("span", {class: fmt.tone(v.roe)}, fmt.pct(v.roe)))},
      {label: "봉 전체 평균 ROE", get: (x) => st(x, (v) => h("span", {class: fmt.tone(v.all_roe)}, fmt.pct(v.all_roe)))},
      {label: "차이", get: (x) => st(x, (v) => [h("span", {class: fmt.tone(v.diff)}, pp(v.diff * 100, 2)), " ", ui.smallSample(v.n, STUDY_SMALL)])},
      {label: "무작위 진입 차이", get: (x) => rn(x, (v) => h("span", {class: fmt.tone(v.diff)}, pp(v.diff * 100, 2)))},
    ], rows),
    h("p", {class: "an-note"}, `매매법 = 기존 36개 매매법의 5년 신호 합산(코인·매매법 합침), 무작위 진입 = 같은 봉·코인에서 무작위로 들어간 거래.${grp === "ds200" ? " 딥시크 정의는 이 연구에 없어 기존 36의 숫자를 참고로만 둡니다." : ""}${grp === "reel" ? " 5분봉 줄은 기존 36의 과거 5분봉 신호이며 릴스 자체는 이 연구에 없습니다." : ""}`),
    h("p", {class: "an-note"}, `${fmt.int(STUDY_SMALL)}건 미만 칸은 표본 적음(연구 문서의 * 표시와 같은 선). 표의 숫자는 5년 연구를 바이낸스 선물 자료로 다시 돌린 결과이고, 연구 문서의 숫자는 사전 등록한 원래 자료의 결과입니다${s.same_conclusion ? " (결론은 같음: 후보는 모두 무작위 진입에도 같은 효과)" : ""}.`),
    h("p", {class: "an-note an-wrap", title: [src.numbers, src.recheck_doc].filter(Boolean).join(" · ")}, `문서: ${src.doc || "research/entry_study/RESULTS_ENTRY_A.md"}`));
}
