// 분석 › 좋은 수치 찾기 (ana7a): GET /api/v4/indranges (dash/more/indranges.py; the committed 5-year result written
// offline by dash/tools/indranges.py), /api/v4/indranges/strategy?name= (one strategy's cells, on demand) and
// /api/v4/indranges/paper (the paper run's own entries of the 36, background).
//   기존 36 합쳐서 (5년)   one number at a time (a remembered switch): its five ranges (or funding's three, the four
//                          sessions), each with the mean result in R, the difference against the other entries as a bar
//                          from the middle, and 더 좋음 / 더 나쁨 ONLY for cells that pass every check; the rest read
//                          차이 없음 in plain ink
//   매매법별 (5년)          the same for one strategy (a select of the 36, with each one's number of marked cells)
//   표시된 칸 모두          every marked cell, strongest first, 10 a page, 전체 / 더 좋음 / 더 나쁨
//   지금 실험               the paper run's entries in the same ranges (the 5-year edges of each trade's timeframe) next
//                          to the 5-year numbers; a filling bar until enough trades
//   어떻게 계산했나         the methods, the counts, and the rule added after the first run (behind a disclosure)
// HONESTY: descriptive (설명용, 판정 아님); finding ranges after the fact overfits; nothing changes the locked rules.
import {h, put, ui, fmt, motion, local} from "../core/pb.js";
import {viewHead, dimSeg, progressBar} from "./analysis-kit.js";
import {pc, rr, divBar, fetchInto} from "./analysis-a7kit.js";

/** A trade count in Korean units: 378,013 -> "37.8만", 4,079 -> "4,079". */
const cnt = (n) => (n == null ? "—" : n >= 100000 ? `${fmt.num(n / 10000, 1)}만` : fmt.int(n));

const IND = {
  rsi: {ko: "RSI", long: "RSI(14) · 진입 방향 기준", help: "숏은 100−RSI로 읽습니다. 높을수록 들어가는 방향으로 이미 많이 오른(숏이면 내린) 상태.", dec: 0},
  atr_pct: {ko: "변동성 ATR%", long: "ATR% (봉 하나 평균 움직임 ÷ 가격)", help: "높을수록 한 봉에 크게 움직이는 때. 변동이 큰 코인(도지·솔라나)이 높은 칸에 많이 들어갑니다.", pct: true},
  adx: {ko: "추세 세기 ADX", long: "ADX(14) (방향 없는 추세 세기)", help: "높을수록 한쪽으로 뚜렷하게 가는 때 (25 넘으면 추세가 뚜렷한 편).", dec: 0},
  ema200: {ko: "EMA200 거리", long: "EMA200에서 거리 (ATR 몇 개, 진입 방향 기준)", help: "+ = 이미 들어가는 방향 쪽에 있음 (롱이면 EMA200 위, 숏이면 아래). − = 반대쪽.", dec: 1, sign: true},
  vol: {ko: "거래량", long: "거래량 ÷ 앞 20봉 평균", help: "1 = 평소만큼, 2 = 평소의 두 배.", dec: 2, unit: "배"},
  bbw: {ko: "볼린저 폭", long: "볼린저 밴드(20, 2) 폭 (%)", help: "좁을수록 조용히 뭉친 때, 넓을수록 크게 벌어진 때.", dec: 1, unit: "%"},
  funding: {ko: "펀딩비", long: "진입 때 펀딩비 (8시간마다 정산)", help: "+ = 롱이 숏에게 냄 (롱이 붐빔). 기본은 0.01%."},
  session: {ko: "시간대", long: "진입 시각 (한국 시간)", help: "아시아·유럽·미국장과 새벽."},
};
const ORDER = ["rsi", "atr_pct", "adx", "ema200", "vol", "bbw", "funding", "session"];
const QK = ["아주 낮음", "낮음", "중간", "높음", "아주 높음"];
const FIX = {funding: ["음수 (숏이 냄)", "0~0.01% (보통)", "0.01% 넘음 (롱이 더 냄)"],
  session: ["아시아장 09~16시", "유럽장 16~22시", "미국장 22~05시", "새벽 05~09시"]};
const EX_TF = "1h";                       // the timeframe whose edges the row labels show (all four behind 구간 경계)

const labelOf = (k, j) => (FIX[k] ? FIX[k][j] : QK[j]);
function val(k, x) {
  const o = IND[k];
  if (x == null) return "—";
  if (o.pct) return fmt.pct(x, 2, false);
  return `${fmt.num(x, o.dec ?? 1, !!o.sign)}${o.unit || ""}`;
}
/** "~44" / "44~52" / "62~" from the four edges of one timeframe. */
function rangeText(k, j, edges) {
  if (FIX[k] || !edges) return "";
  if (j === 0) return `~${val(k, edges[0])}`;
  if (j === 4) return `${val(k, edges[3])}~`;
  return `${val(k, edges[j - 1])}~${val(k, edges[j])}`;
}

/** The status words of one cell: 더 좋음 / 더 나쁨 only for marked cells; else 차이 없음 (or 표본 적음). */
function status(c, rules) {
  if (c.ok === 1) return ui.pill("더 좋음", "good", "여러 번 본 것을 감안한 검사와 세 기간 모두 같은 방향, 차이 0.05R 이상");
  if (c.ok === -1) return ui.pill("더 나쁨", "bad", "여러 번 본 것을 감안한 검사와 세 기간 모두 같은 방향, 차이 0.05R 이상");
  if (c.p == null) return h("span", {class: "a7-plain"}, `표본 적음 (${fmt.int(rules.min_cell || 30)}건 미만)`);
  return h("span", {class: "a7-plain"}, "차이 없음");
}

/** Five (or three / four) rows of one number for one scope. cells: [cell], edges: {tf: [4]}. */
function rangeRows(k, cells, edges, rules, five) {
  const top = Math.max(0.08, ...cells.map((c) => Math.abs(c.d || 0)));
  return h("div", {class: "a7-rows", role: "list", "aria-label": IND[k].long},
    cells.map((c, j) => {
      const tone = c.ok === 1 ? "up" : c.ok === -1 ? "down" : "flat";
      const rt = rangeText(k, j, (edges || {})[EX_TF]);
      return h("div", {class: ["a7-row", c.ok ? "marked" : ""], role: "listitem"},
        h("span", {class: "a7-k"}, h("b", null, labelOf(k, j)), rt ? h("small", {class: "num"}, `${fmt.tfKo(EX_TF)}봉 ${rt}`) : null),
        h("span", {class: "a7-bar"}, divBar(c.d, top, tone, `나머지보다 ${rr(c.d)}`),
          h("small", {class: ["num", c.ok ? fmt.tone(c.d) : "muted"]}, c.d == null ? "—" : `나머지보다 ${rr(c.d)}`)),
        h("span", {class: "a7-v"}, h("b", {class: "num"}, `평균 ${rr(c.r)}`),
          h("small", {class: "num"}, `${cnt(c.n)}건 · 이긴 비율 ${pc(c.wr)}`)),
        h("span", {class: "a7-st"}, status(c, rules)));
    }),
    five ? h("p", {class: "a7-legend"}, "가운데 선 = 같은 매매법의 나머지 진입과 같음. 오른쪽 = 그보다 좋음, 왼쪽 = 나쁨 (R 단위).") : null);
}

/** The edges of one number on every timeframe (구간 경계 table). */
function edgeTable(k, edges, tfs) {
  if (FIX[k]) return h("p", {class: "an-note"}, k === "funding" ? "펀딩비는 정해진 세 칸입니다: 0보다 작음 / 0~0.01% / 0.01% 넘음." : "시간대는 한국 시간으로 정해진 네 칸입니다.");
  const cols = [{label: "봉", l: true, get: (tf) => fmt.tfKo(tf)}, ...[0, 1, 2, 3].map((i) => ({label: `${QK[i]} | ${QK[i + 1]}`, get: (tf) => val(k, ((edges || {})[tf] || [])[i])}))];
  return h("div", {class: "a7-edges"}, ui.table(cols, tfs),
    h("p", {class: "an-note"}, "칸 경계는 봉 길이마다 그 봉의 5년 진입을 다섯으로 똑같이 나눈 값입니다 (36개 매매법 모두 같은 경계)."));
}

export function indranges(d, env) {
  const out = [viewHead({plate: "좋은 수치 찾기", q: "들어갈 때 어떤 숫자 구간에서 결과가 좋았나",
    meta: d.ready ? `5년 시험 ${String((d.span || {}).from || "").replace(/-/g, ".")}~${String((d.span || {}).to || "").replace(/-/g, ".")} · 기존 36 진입 ${fmt.int(d.trades)}건 · 15분·30분·1시간·4시간봉` : "5년 결과 파일 없음",
    read: "진입한 봉의 숫자(RSI, 변동성, 추세 세기, EMA200 거리, 거래량, 볼린저 폭, 펀딩비, 시간대)를 칸으로 나눠, 칸마다 결과를 봅니다. R = 처음 손절 거리 한 번만큼 (−1R = 손절 한 번, 수수료·펀딩 뺀 순).",
    warn: [h("p", {class: "an-warn"}, ui.pill("설명용, 판정 아님", "ref"),
      " 결과를 보고 나서 좋은 구간을 고르면 과거에만 맞는 구간을 고르게 됩니다(과적합). 36개 매매법도 이 5년 자료로 골랐습니다. 잠긴 규칙은 이 화면 때문에 바뀌지 않습니다.")]})];
  if (!d.ready) {
    out.push(ui.card({plate: "좋은 수치 찾기"}, h("p", {class: "muted"}, d.why || "5년 결과가 아직 없습니다.")));
    return out;
  }
  const rules = d.rules || {}, tfs = d.tfs || ["15m", "30m", "1h", "4h"];
  const ind = dimSeg("indr", ORDER.map((k) => ({id: k, label: IND[k].ko, title: IND[k].long})), "rsi", () => paintAll(true), true);
  const pooledBody = h("div"), stratBody = h("div"), edgeBody = h("div");
  const paints = [];
  const paintAll = (anim) => { for (const f of paints) f(anim); };

  // ---- 기존 36 합쳐서 (5년)
  paints.push((anim) => {
    const k = ind.get(), cells = ((d.pooled || {}).cells || {})[k] || [];
    put(pooledBody, h("p", {class: "a7-help"}, h("b", null, IND[k].long), " · ", IND[k].help),
      rangeRows(k, cells, (d.edges || {})[k], rules, true));
    put(edgeBody, edgeTable(k, (d.edges || {})[k], tfs));
    if (anim) motion.swap(pooledBody);
  });
  const p = d.pooled || {};
  out.push(ui.card({plate: "기존 36 합쳐서", sub: `5년 · 평균 ${rr(p.r)} · 이긴 비율 ${pc(p.wr)}`},
    h("div", {class: "a7-segrow"}, ind.el), pooledBody,
    ui.disclosure("구간 경계 보기 (봉 길이마다)", edgeBody),
    h("p", {class: "an-note"}, "더 좋음·더 나쁨은 아래 '어떻게 계산했나'의 검사를 모두 넘은 칸에만 붙습니다. 나머지는 차이 없음으로 둡니다.")));

  // ---- 매매법별 (5년)
  const names = Object.keys(d.strategies || {});
  const pick = h("select", {class: "select a7-pick", "aria-label": "매매법 고르기"},
    names.map((s) => h("option", {value: s}, `${fmt.stratKo(s)} · 표시 ${fmt.int((d.strategies[s] || {}).passed || 0)}칸`)));
  // first visit: the strategy with the most marked cells (a thinly traded one would open on empty ranges)
  const most = names.reduce((a, s) => (((d.strategies[s] || {}).passed || 0) > ((d.strategies[a] || {}).passed || 0) ? s : a), names[0]);
  const saved = local.get("an-indr-s", null);
  pick.value = saved && names.includes(saved) ? saved : most;
  const cache = {};
  const indName = h("b", {class: "a7-ind-name"});
  const showStrat = (anim) => {
    const s = pick.value, k = ind.get(), got = cache[s];
    indName.textContent = IND[k].ko;
    if (!got) { put(stratBody, motion.shimmer(3, true)); return; }
    if (got.error) { put(stratBody, h("p", {class: "muted"}, got.error)); return; }
    put(stratBody, h("p", {class: "a7-help"}, `${fmt.stratKo(s)} · 5년 진입 ${fmt.int(got.n)}건 · 평균 ${rr(got.r)} · 이긴 비율 ${pc(got.wr)} · 표시된 칸 ${fmt.int(got.passed || 0)}개`),
      rangeRows(k, (got.cells || {})[k] || [], (d.edges || {})[k], rules, false));
    if (anim) motion.swap(stratBody);
  };
  const loadStrat = () => {
    const s = pick.value;
    local.set("an-indr-s", s);
    if (cache[s]) { showStrat(true); return; }
    put(stratBody, motion.shimmer(3, true));
    env.ctx.api(`/api/v4/indranges/strategy?name=${encodeURIComponent(s)}`).then((x) => {
      if (!env.ctx.alive()) return;
      cache[s] = x || {error: "자료 없음"};
      if (pick.value === s) showStrat(true);
    }).catch(() => { cache[s] = {error: "불러오지 못했습니다. 다시 골라 주세요."}; if (pick.value === s) showStrat(false); delete cache[s]; });
  };
  pick.addEventListener("change", loadStrat);
  paints.push((anim) => showStrat(anim));
  out.push(ui.card({plate: "매매법별", sub: "5년 · 한 매매법씩"},
    h("div", {class: "a7-segrow"}, pick, h("span", {class: "a7-note"}, "숫자: ", indName, " (위에서 고른 것)")),
    stratBody,
    h("p", {class: "an-note"}, "가운데 선 = 그 매매법의 나머지 진입. 표시 0칸이면 이 매매법은 어느 숫자 구간에서도 뚜렷한 차이가 없었다는 뜻입니다.")));

  // ---- 표시된 칸 모두
  const all = d.marked || [];
  const pg = ui.pager({size: 10, row: (c, i) => markedRow(c, d, i), empty: "표시된 칸이 없습니다."});
  const filt = dimSeg("indr-mk", [{id: "all", label: `전체 ${fmt.int(all.length)}`}, {id: "up", label: `더 좋음 ${fmt.int(all.filter((c) => c.ok === 1).length)}`},
    {id: "down", label: `더 나쁨 ${fmt.int(all.filter((c) => c.ok === -1).length)}`}], "all", () => setMarked(), false);
  const setMarked = () => { const f = filt.get(); pg.set(all.filter((c) => f === "all" || (f === "up" ? c.ok === 1 : c.ok === -1))); };
  setMarked();
  out.push(ui.card({plate: "표시된 칸 모두", sub: `5년 · 검사 ${fmt.int(rules.tests)}칸 중 ${fmt.int(rules.passed)}칸 · 차이 큰 순`},
    filt.el, pg.el,
    h("p", {class: "an-note"}, "세 기간 = 2021.8~2022 · 2023~2024 · 2025~2026.9 (그 칸이 나머지보다 얼마나 나았나). 칸 경계는 봉 길이마다 다릅니다 (위 '구간 경계 보기').")));

  // ---- 지금 실험 (paper)
  out.push(fetchInto(env, "/api/v4/indranges/paper", "지금 실험", (pd) => paperCards(pd, d, ind, paints)));

  // ---- 어떻게 계산했나
  out.push(ui.card({plate: "어떻게 계산했나"}, ui.disclosure("검사 방법과 숫자 보기", methods(d))));
  out.push(h("p", {class: "an-note an-foot"}, `좋은 수치 찾기: 기존 36 · 5년 과거 시험 + 지금 실험 · ${d.label || "설명용, 판정 아님"} · 매매 규칙은 바뀌지 않습니다.`));
  paintAll(false);
  loadStrat();
  return out;
}

function markedRow(c, d, i) {
  const k = c.k, who = c.s ? fmt.stratKo(c.s) : "기존 36 전체";
  const w = (c.w || []).map((x, j) => `${["21~22", "23~24", "25~26"][j]} ${x && x[1] != null ? rr(x[1]) : "—"}`).join(" · ");
  const rt = rangeText(k, c.j, ((d.edges || {})[k] || {})[EX_TF]);
  return h("div", {class: "lrow an-row a7-mrow", role: "listitem"},
    h("span", {class: "rk"}, String(i + 1)),
    h("span", {class: "lname an-wrap"}, h("b", null, who), ` · ${IND[k].ko} ${labelOf(k, c.j)}`, rt ? h("small", {class: "num muted"}, ` (${fmt.tfKo(EX_TF)}봉 ${rt})`) : null),
    h("span", {class: ["ret", "num", fmt.tone(c.d)]}, rr(c.d)),
    h("span", {class: "meta"},
      h("span", null, `평균 ${rr(c.r)} · ${cnt(c.n)}건 · 이긴 비율 ${pc(c.wr)}`),
      h("span", null, `세 기간: ${w}`)));
}

function paperCards(pd, d, ind, paints) {
  if (pd.error) return [ui.card({plate: "지금 실험"}, h("p", {class: "muted"}, String(pd.error)))];
  const cov = pd.coverage || {}, need = pd.min_trades || 100, have = cov.with_numbers || 0;
  if (pd.waiting) {
    return [ui.card({plate: "채워지는 중", sub: "지금 실험의 진입", cls: "an-wait"},
      progressBar(`기존 36 끝난 거래 ${fmt.int(need)}건 필요 (진입 때 숫자를 잴 수 있는 거래)`, `지금 ${fmt.int(have)}건 · 끝난 거래 전체 ${fmt.int(cov.trades || 0)}건`, Math.min(1, have / need)),
      h("p", {class: "an-note"}, "막대는 지금까지 실제로 끝난 거래 수입니다. 넘으면 위와 같은 칸으로 나눈 지금 실험의 성적이 여기에 나옵니다. 그때까지는 위의 5년 숫자를 보시면 됩니다."))];
  }
  const body = h("div");
  const paint = (anim) => {
    const k = ind.get(), cells = (pd.cells || {})[k] || [], five = (((d.pooled || {}).cells || {})[k]) || [];
    put(body, h("p", {class: "a7-help"}, h("b", null, IND[k].long), " · 위에서 고른 숫자"),
      h("div", {class: "a7-rows", role: "list"}, cells.map((c, j) => h("div", {class: "a7-row paper", role: "listitem"},
        h("span", {class: "a7-k"}, h("b", null, labelOf(k, j))),
        h("span", {class: "a7-v"}, h("b", {class: "num"}, c.n ? `평균 ${rr(c.mean_r)}` : "—"),     // plain ink: nothing tested yet
          h("small", {class: "num"}, c.n ? `${fmt.int(c.n)}건 · 이긴 비율 ${pc(c.wr)}` : "0건"), c.small && c.n ? ui.pill("표본 적음", "thin") : null),
        h("span", {class: "a7-v five"}, h("small", null, "5년"), h("span", {class: "num"}, `평균 ${rr((five[j] || {}).r)}`))))));
    if (anim) motion.swap(body);
  };
  paints.push(paint);
  paint(false);
  return [ui.card({plate: "지금 실험", sub: `기존 36 끝난 거래 ${fmt.int(have)}건 · 실험 시작부터`},
    body,
    h("p", {class: "an-note"}, `칸 경계는 5년 시험과 같습니다 (그 거래의 봉 길이). ${fmt.int(pd.min_bucket || 20)}건 미만 칸은 표본 적음. 아직 검사는 하지 않습니다 (설명용).`,
      cov.no_bars ? ` 진입 봉 시세를 찾지 못한 거래 ${fmt.int(cov.no_bars)}건은 뺐습니다.` : ""))];
}

function methods(d) {
  const r = d.rules || {}, src = d.source || {};
  const li = (...t) => h("li", null, ...t);
  return h("div", {class: "a7-methods"},
    h("ul", null,
      li(`거래: 기존 36개 매매법이 15분·30분·1시간·4시간봉, 코인 6개에서 낸 모든 신호를 한 번씩 거래 (실험과 같은 청산: 다음 봉 시가 진입, 2 ATR 손절, 계단 잠금, 수수료·펀딩·강제청산 포함). 계좌·동시 포지션 제한 없음. 모두 ${fmt.int(d.trades)}건.`),
      li("숫자: 신호 봉이 닫힐 때의 값 (그 봉과 앞 봉들만 씀). RSI와 EMA200 거리는 진입 방향 기준 (숏은 뒤집음)."),
      li("칸: 봉 길이마다 36개 모두의 5년 진입을 다섯으로 똑같이 나눈 경계 (펀딩비 세 칸, 시간대 네 칸)."),
      li(`비교: 한 칸의 평균 R과 같은 매매법의 나머지 진입 평균 R의 차이. 양쪽 다 ${fmt.int(r.min_cell)}건 이상일 때만 검사 (같은 주의 진입은 같이 움직이므로 주 단위로 묶어 계산).`),
      li(`여러 번 본 것 감안: 검사한 ${fmt.int(r.tests)}칸 모두를 한꺼번에 (Benjamini-Hochberg ${fmt.pct(r.fdr, 0, false)}). 그러고도 세 기간(2021.8~2022, 2023~2024, 2025~2026.9) 모두에서 같은 방향이고 각 기간 양쪽 ${fmt.int(r.min_window)}건 이상인 칸만 표시.`),
      li(h("b", null, "첫 실행 뒤에 더한 규칙: "), `거래가 189만 건이나 되어 0.02R 같은 아주 작은 차이도 검사를 넘었습니다. 그래서 표시는 차이가 ${fmt.num(r.min_effect_r, 2)}R(손절 거리의 5%) 이상인 칸만 합니다. 검사는 넘었지만 차이가 작은 ${fmt.int(r.tiny)}칸은 차이 없음으로 둡니다.`),
      li(`결과: 표시 ${fmt.int(r.passed)}칸 (더 좋음 ${fmt.int(r.better)} · 더 나쁨 ${fmt.int(r.worse)}). 이 방식은 표시된 칸의 약 5%가 우연일 수 있다고 보는 방식입니다.`),
      li(`자료: 연구실 5년 신호 저장본${src.main_identical === true ? ` (파일 ${fmt.int(src.main_files)}개 모두 연구 자료와 같음을 확인)` : ""}, 펀딩비 기록${src.funding ? "" : " 없음"} · 만든 때 ${d.built_utc || "—"} UTC${d.code_commit ? ` · 코드 ${d.code_commit}` : ""}.`)));
}
