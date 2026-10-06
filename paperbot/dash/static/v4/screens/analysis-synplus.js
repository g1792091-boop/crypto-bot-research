// 분석 › 조합 시너지, the added cards (ana-syn): GET /api/v4/synplus (dash/more/synplus.py), one request for four cards.
//   같이 망하는 날      pairs of the 36 that lose on the same days, and pairs where one wins when the other loses
//   같이 들어간 진입    how trades did when other strategies entered the same coin and side at about the same time
//   다음 기간에도 통할까 the first half's best combination, scored on the second half against every combination
//   한 계좌로 합치면    the top combinations in one account: time holding one coin both ways, peak margin in use
// A part the server marks `waiting` (too few days or trades) is one filling bar in a single 채워지는 중 card with its real
// threshold, never a ranking of zeros. {pending: true}: a shimmer, asked again after 3 s (the server computes it in the
// background). HONESTY: descriptive only (설명용, 판정 아님); coin flips are the 참고 line with refNote; money has assume().
import {h, put, ui, fmt, motion} from "../core/pb.js";
import {dimSeg, progressBar} from "./analysis-kit.js";

const API = "/api/v4/synplus";
const RETRY_MS = 3000;
const pc = (x, d = 0) => (x == null ? "—" : fmt.pct(x, d, false));
const sc = (x) => (x == null ? "—" : fmt.num(x, 2));
const span = (f) => (f ? `${f.from.slice(5).replace("-", "/")}~${f.to.slice(5).replace("-", "/")} (${fmt.int(f.days)}일)` : "—");

/** The section: a wrapper that fills itself (shimmer → cards). env: the analysis view's env (ctx, verdictTs, track). */
export function synPlus(env) {
  const box = h("div", {class: "stack ax-syn", "aria-live": "polite"},
    ui.card({plate: "조합 더 보기", sub: "같이 망하는 날 · 같이 들어간 진입 · 다음 기간 · 한 계좌로"}, motion.shimmer(4, true)));
  let dead = false;
  env.track(() => { dead = true; });
  const ask = () => {
    env.ctx.api(API).then((d) => {
      if (dead || !env.ctx.alive()) return;
      if (d && d.pending) {
        put(box, ui.card({plate: "조합 더 보기"}, h("p", {class: "muted"}, d.note || "서버가 계산하는 중입니다. 잠시 뒤 다시 봅니다."), motion.shimmer(3)));
        env.ctx.timeout(() => { if (!dead) ask(); }, RETRY_MS);
        return;
      }
      put(box, ...render(d || {}, env));
      motion.swap(box);
    }).catch(() => {
      if (dead || !env.ctx.alive()) return;
      put(box, ui.card({plate: "조합 더 보기"}, ui.errorBox(null, () => { put(box, motion.shimmer(3, true)); ask(); })));
    });
  };
  ask();
  return box;
}

/** The cards for one answer (exported for the tests). */
export function render(d, env) {
  if (d.error) return [ui.card({plate: "조합 더 보기"}, h("p", {class: "muted"}, String(d.error)))];
  const co = d.coloss || {}, ag = d.agree || {}, wf = d.walk || {}, oa = d.one_account || {};
  const bars = [];
  if (co.waiting) bars.push({label: `같이 망하는 날 · 하루 손익 ${fmt.int(co.need_days || 14)}일 필요`, share: (co.days || 0) / (co.need_days || 14),
    words: `지금 ${fmt.int(co.days || 0)}일째 (한국 시간 하루 단위)`});
  if (ag.waiting) bars.push({label: `같이 들어간 진입 · 기존 36 끝난 거래 ${fmt.int(ag.need_trades || 30)}건 필요`, share: (ag.trades || 0) / (ag.need_trades || 30),
    words: `지금 ${fmt.int(ag.trades || 0)}건`});
  if (wf.waiting) bars.push({label: `다음 기간에도 통할까 · 하루 손익 ${fmt.int(wf.need_days || 20)}일 필요 (앞 절반으로 고르고 뒤 절반으로 확인)`,
    share: (wf.days || 0) / (wf.need_days || 20), words: `지금 ${fmt.int(wf.days || 0)}일째`});
  if (oa.waiting) bars.push({label: `한 계좌로 합치면 · 36 계좌 평균 거래 ${fmt.int(oa.need_avg_trades || 5)}건 필요 (조합 순위가 생긴 뒤)`,
    share: (oa.avg_trades || 0) / (oa.need_avg_trades || 5), words: `지금 계좌당 평균 ${fmt.num(oa.avg_trades || 0, 1)}건`});
  const out = [];
  if (bars.length) {
    out.push(ui.card({plate: "채워지는 중", sub: "조합 더 보기", cls: "an-wait"},
      ...bars.map((b) => progressBar(b.label, b.words, Math.min(1, b.share))),
      h("p", {class: "an-note"}, "막대는 지금까지 쌓인 실제 날 수와 거래 수입니다. 기준을 넘으면 그 카드가 숫자로 채워집니다.")));
  }
  if (!co.waiting && co.pairs != null) out.push(colossCard(co, env));
  if (!ag.waiting && ag.buckets) out.push(agreeCard(ag, env));
  if (!wf.waiting && (wf.strategies || wf.coin_flips)) out.push(walkCard(wf, env));
  if (!oa.waiting && (oa.combos || []).length) out.push(oneCard(oa, env));
  out.push(h("p", {class: "an-note an-foot"}, `조합 더 보기: 기존 36 매매법만 · 실험 시작부터 · ${d.label || "설명용, 판정 아님"} · 계좌를 묶거나 바꾸지 않습니다.`));
  return out;
}

// ---------------------------------------------------------------- 같이 망하는 날
function pairRow(r, i, main) {
  const [a, b] = r.names || r.units || ["", ""];
  return h("div", {class: "lrow an-row", role: "listitem"},
    h("span", {class: "rk"}, String(i + 1)), h("span", {class: "lname an-wrap"}, `${a} + ${b}`),
    h("span", {class: "ret num"}, main === "cover" ? pc(r.cover) : pc(r.co_loss)),
    h("span", {class: "meta"},
      h("span", null, `둘 중 하나라도 잃은 ${fmt.int(r.either_days)}일 중 둘 다 잃음 ${fmt.int(r.both_days)}일 · 하나가 잃을 때 다른 하나는 범 ${fmt.int(r.cover_days)}일`),
      // the worst days that were losses (a unit with fewer losing days has fewer): each side's own count
      h("span", null, `${a}의 나쁜 날 ${fmt.int(r.bad_a_days)}일 중 ${b}도 잃음 ${pc(r.bad_ab)} · ${b}의 나쁜 날 ${fmt.int(r.bad_b_days)}일 중 ${a}도 잃음 ${pc(r.bad_ba)}`)));
}
function colossCard(co, env) {
  const m = co.median || {}, f = co.coin_flips;
  const body = h("div");
  const seg = dimSeg("syn-coloss", [{id: "together", label: "같이 망한 쌍"}, {id: "cover", label: "서로 받쳐 준 쌍"}], "together", () => paint(true));
  function paint(anim) {
    const main = seg.get(), rows = main === "cover" ? co.cover_best || [] : co.together || [];
    put(body, h("p", {class: "an-note"}, main === "cover" ? "오른쪽 = 둘 중 하나가 잃은 날 가운데 다른 하나는 번 날의 비율 (높은 순)"
      : "오른쪽 = 둘 중 하나라도 잃은 날 가운데 둘 다 잃은 날의 비율 (높은 순)"),
    rows.length ? h("div", {class: "plist", role: "list"}, rows.map((r, i) => pairRow(r, i, main))) : ui.empty("비교할 쌍이 아직 없습니다."));
    if (anim) motion.swap(body);
  }
  paint(false);
  return ui.card({plate: "같이 망하는 날", sub: `기존 36 매매법 쌍 · 하루 손익 ${fmt.int(co.days)}일`},
    h("p", {class: "an-read"}, h("b", null, "읽는 법 "), `매매법마다 하루(한국 시간) 손익을 봅니다. '같이 잃은 날' = 둘 중 하나라도 잃은 날 가운데 둘 다 잃은 날. '나쁜 날 겹침' = 한 매매법이 가장 많이 잃은 날(전체 날의 ${fmt.int((co.worst_share || 0.2) * 100)}%인 ${fmt.int(co.worst_days)}일 가운데 실제로 잃은 날)에 다른 매매법도 잃은 비율.`),
    h("div", {class: "stats s4"},
      ui.stat("같이 잃은 날 (중앙값)", pc(m.co_loss), `매매법 쌍 ${fmt.int(co.pairs)}개`),
      ui.stat("나쁜 날 겹침 (중앙값)", pc(m.bad), "가장 나쁜 날에 상대도 잃음"),
      ui.stat("받쳐 준 날 (중앙값)", pc(m.cover), "하나가 잃을 때 다른 하나는 범"),
      f ? ui.stat("동전 봇끼리 (참고)", pc(f.median && f.median.co_loss), `같이 잃은 날 · 나쁜 날 겹침 ${pc(f.median && f.median.bad)}`) : null),
    seg.el, body,
    h("p", {class: "an-note"}, `둘 중 하나라도 잃은 날이 ${fmt.int(co.min_pair_days)}일 이상인 쌍만 봅니다.`,
      f ? ` 동전 봇은 계좌 ${fmt.int(f.units)}개(봉 하나씩)끼리 ${fmt.int(f.pairs)}쌍: 매매법은 봉 계좌 4개를 합친 것이라 조건이 같지 않은 참고 기준입니다.` : ""),
    ui.refNote(env.verdictTs));
}

// ---------------------------------------------------------------- 같이 들어간 진입
const AG_ROWS = [["alone", "혼자", "같이 들어간 다른 매매법 없음"], ["two", "2개 같이", "다른 매매법 1개"], ["three_plus", "3개 이상", "다른 매매법 2개 이상"]];
const OPP_ROWS = [["opposite", "반대 방향 있음", "같은 코인 반대 방향 포지션이 열려 있었음"], ["no_opposite", "반대 방향 없음", "반대 방향 포지션 없음"]];
const TF_ROWS = [["tf_none", "다른 봉 없음", "같은 매매법의 다른 봉 계좌가 같은 쪽에 없었음"], ["tf_one", "다른 봉 1개", "같은 매매법 다른 봉 1개가 이미 같은 쪽"],
  ["tf_two_plus", "다른 봉 2개 이상", "같은 매매법 다른 봉 2개 이상이 이미 같은 쪽"]];
function agCell(c, share, small) {
  if (!c || !c.trades) return h("span", {class: "muted"}, "—");
  return h("span", {class: "an-cell"}, h("b", {class: "num"}, `${fmt.int(c.trades)}건`), share != null ? h("span", {class: "muted"}, `(${pc(share)})`) : null,
    " · ", h("span", {class: "num"}, `이김 ${pc(c.win_rate)}`),
    " · ", h("span", {class: ["num", fmt.tone(c.mean_roe)]}, `ROE ${fmt.pct(c.mean_roe, 1)}`),
    " · ", h("span", {class: ["num", fmt.tone(c.mean_eq)]}, `자금 대비 ${fmt.pct(c.mean_eq, 2)}`),
    c.trades < small ? [" ", ui.pill("표본 적음", "thin")] : null);
}
function agList(rows, B, small) {
  return h("div", {class: "an-cmp", role: "list"},
    h("div", {class: "an-cmprow an-cmphead", "aria-hidden": "true"}, h("span", null, ""), h("span", null, "기존 36"), h("span", null, "동전 봇 (참고)")),
    rows.map(([k, ko, why]) => {
      const b = B[k] || {};
      return h("div", {class: "an-cmprow", role: "listitem"},
        h("span", {class: "ax-k2"}, h("b", null, ko), h("small", {class: "muted"}, why)),
        h("span", null, h("i", {class: "an-tag"}, "기존 36"), agCell(b.strategies, b.share, small)),
        h("span", null, h("i", {class: "an-tag"}, "동전 봇"), agCell(b.coin_flips, b.flip_share, small)));
    }));
}
function agreeCard(ag, env) {
  const B = ag.buckets || {}, small = ag.small_n || 20, all = ag.all || {};
  const s = (k) => (B[k] || {}).strategies || {};
  const alone = s("alone"), three = s("three_plus"), opp = B.opposite || {}, tfAny = (B.tf_one || {}).share || 0;
  return ui.card({plate: "같이 들어간 진입", sub: `기존 36 끝난 거래 ${fmt.int(ag.trades)}건 · 동전 봇 ${fmt.int(ag.flip_trades)}건`},
    h("p", {class: "an-read"}, h("b", null, "읽는 법 "), "거래마다 들어간 순간 앞뒤로 그 거래의 봉 하나 길이 안에 같은 코인·같은 방향으로 들어간 다른 매매법(이름 기준, 봉 무관)을 셉니다. 세 묶음은 따로 나눈 것이라 묶음마다 합이 100%입니다. ROE = 증거금 대비, 자금 대비 = 거래 전 잔고 대비 (수수료·펀딩 뺀 순)."),
    agList(AG_ROWS, B, small),
    alone.trades && three.trades ? h("p", {class: "ax-say"}, `혼자 들어간 거래의 이긴 비율은 ${pc(alone.win_rate)}, 3개 이상 같이 들어간 거래는 ${pc(three.win_rate)}였어요. (전체 ${pc((all.strategies || {}).win_rate)})`) : null,
    h("h3", {class: "an-sub"}, "들어갈 때 같은 코인에 반대 방향 포지션이 있었나 (기존 36 어느 계좌든)"),
    agList(OPP_ROWS, B, small),
    opp.share != null ? h("p", {class: "ax-say"}, `기존 36 거래의 ${pc(opp.share)}는 들어갈 때 다른 계좌가 같은 코인을 반대 방향으로 들고 있었어요. (동전 봇 ${pc(opp.flip_share)})`) : null,
    h("h3", {class: "an-sub"}, "봉 합의: 같은 매매법의 다른 봉 계좌가 이미 같은 쪽에 있었나"),
    agList(TF_ROWS, B, small),
    h("p", {class: "ax-say"}, `기존 36 거래의 ${pc(tfAny + ((B.tf_two_plus || {}).share || 0))}는 같은 매매법의 다른 봉 계좌가 이미 같은 코인·같은 방향에 들어가 있었어요.`),
    h("p", {class: "an-note"}, "동전 봇 칸 = 동전 봇이 들어간 순간 같은 코인·방향으로 들어간 기존 36 매매법 수로 나눔 (0개 = 혼자, 1개 = 2개 같이, 2개 이상 = 3개 이상), 반대 방향도 기존 36 포지션 기준. 봉 합의의 동전 봇은 같은 번호 동전 봇의 다른 봉 계좌. 지금 열린 포지션도 '들어감'으로 셉니다",
      ag.open_now ? ` (${fmt.int(ag.open_now)}개).` : "."),
    ui.refNote(env.verdictTs), ui.assume());
}

// ---------------------------------------------------------------- 다음 기간에도 통할까
function walkCard(wf, env) {
  const s = wf.strategies, f = wf.coin_flips;
  const say = s ? (s.second_score != null && s.second_median != null
    ? `앞 절반 최고 조합은 뒤 절반에서 점수 ${sc(s.second_score)}: 조합 ${fmt.int(s.combos)}개 중 ${pc(s.beat_share)}보다 높았어요 (중앙값 ${sc(s.second_median)}).` : null) : null;
  return ui.card({plate: "다음 기간에도 통할까", sub: `앞 절반 ${span(wf.first)} → 뒤 절반 ${span(wf.second)}`},
    h("p", {class: "an-read"}, h("b", null, "읽는 법 "), "앞 절반의 하루 손익만 보고 점수(총손익 ÷ 최대 낙폭)가 가장 높은 조합(매매법 2~5개)을 고른 뒤, 고를 때 보지 않은 뒤 절반에서 다시 점수를 매깁니다. 뒤 절반에서 모든 조합의 중앙값·상위 25% 선과 나란히 봅니다."),
    s ? [h("p", {class: "ax-combo"}, h("b", null, (s.names || []).join(" + ")), h("span", {class: "muted"}, ` · 앞 절반 점수 ${sc(s.first_score)}`)),
      h("div", {class: "stats s4"},
        ui.stat("고른 조합 · 뒤 절반", h("b", {class: "num"}, sc(s.second_score)), "고를 때 보지 않은 기간"),
        ui.stat("모든 조합 중앙값", sc(s.second_median), `뒤 절반 · 조합 ${fmt.int(s.combos)}개`),
        ui.stat("상위 25% 선", sc(s.second_p75), "뒤 절반 · 모든 조합"),
        ui.stat("이 조합보다 낮은 조합", pc(s.beat_share), "뒤 절반 점수 기준")),
      say ? h("p", {class: "ax-say"}, say) : null] : h("p", {class: "muted"}, "조합할 매매법이 2개 미만입니다."),
    f ? h("p", {class: "an-note"}, `동전 봇 계좌 ${fmt.int(f.units_n)}개로 같은 방법 (참고): 앞 절반 최고 조합의 뒤 절반 점수 ${sc(f.second_score)} · 모든 조합 중앙값 ${sc(f.second_median)} · 상위 25% 선 ${sc(f.second_p75)} (조합 ${fmt.int(f.combos)}개).`) : null,
    h("p", {class: "an-note"}, "점수 = 총손익 ÷ 최대 낙폭. 낙폭이 자금의 0.5%보다 작으면 0.5%로 셈니다 (거의 내려가지 않은 기간은 점수가 크게 나옴). 기간이 짧으면 앞뒤 모두 우연이 큽니다. 한 번 나눈 결과라 '다음에도 그렇다'는 뜻이 아닙니다."),
    ui.refNote(env.verdictTs));
}

// ---------------------------------------------------------------- 한 계좌로 합치면
function oneRow(c, i, init) {
  return h("div", {class: "lrow an-row", role: "listitem"},
    h("span", {class: "rk"}, String(i + 1)), h("span", {class: "lname an-wrap"}, (c.names || []).join(" + ")),
    h("span", {class: "ret num", title: "포지션이 있던 시간 중 서로 상쇄된 시간 비율"}, `상쇄 ${pc(c.cancel_share)}`),
    h("span", {class: "meta"},
      h("span", null, `포지션 있던 ${fmt.num(c.busy_hours, 0)}시간 중 같은 코인을 롱·숏 동시에 ${fmt.num(c.cancel_hours, 0)}시간`),
      h("span", null, `최대 동시 증거금 ${fmt.money(c.peak_margin)} USDT = 한 계좌 시작 자금의 ${fmt.num(c.peak_x_one, 1)}배`,
        c.peak_ts ? ` (${fmt.kst(c.peak_ts)})` : ""),
      h("span", null, `계좌 ${fmt.int(c.accounts)}개 · 합친 시작 자금 ${fmt.money(c.capital)} USDT`)));
}
function oneCard(oa, env) {
  const f = oa.coin_flips;
  const top = (oa.combos || [])[0];
  return ui.card({plate: "한 계좌로 합치면", sub: `점수 높은 조합 ${fmt.int((oa.combos || []).length)}개`},
    h("p", {class: "an-read"}, h("b", null, "읽는 법 "), "조합의 계좌들을 거래소 계좌 하나에서 돌렸다면: 같은 코인을 한쪽은 롱, 한쪽은 숏으로 들고 있던 시간은 서로 지워져 수수료·펀딩만 나갑니다(상쇄). 최대 동시 증거금 = 같은 순간 열려 있던 포지션의 증거금 합의 최고값."),
    h("div", {class: "plist", role: "list"}, (oa.combos || []).map((c, i) => oneRow(c, i, oa.initial))),
    top ? h("p", {class: "ax-say"}, `1위 조합은 포지션이 있던 시간의 ${pc(top.cancel_share)} 동안 같은 코인을 양쪽으로 들고 있었고, 한때 한 계좌 시작 자금(${fmt.money(oa.initial)} USDT)의 ${fmt.num(top.peak_x_one, 1)}배를 증거금으로 썼어요.`) : null,
    f ? h("p", {class: "an-note"}, `동전 봇 계좌 ${fmt.int(f.accounts)}개를 한 계좌로 (참고): 상쇄 ${pc(f.cancel_share)} · 최대 동시 증거금 한 계좌 시작 자금의 ${fmt.num(f.peak_x_one, 1)}배.`) : null,
    h("p", {class: "an-note"}, "같은 매매법의 다른 봉 계좌끼리도 셉니다 (한 계좌에서는 모두 서로 지워지므로). 끝난 거래와 지금 열린 포지션 기준."),
    ui.refNote(env.verdictTs), ui.assume());
}
