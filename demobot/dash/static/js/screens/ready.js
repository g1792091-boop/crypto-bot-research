// #/ready 실전 준비 (CONTRACT 9.9, 9.10): for each 실전 후보 (judge.json candidates), else the line closest to "우리 기준"
// (home.json goal.closest): its confirmation window, its P&L after the measured costs (costs.json lines), the stop rules'
// effect (accounts.json lines.stops, judge rows' stops), "버티는 수익인가" (judge rows' robust: the 5 best trades' share,
// first / second half, coins, losing streak, worst day, the flags), a small-start example (margin 10% of $300 at the
// line's leverage, with the line's own stop distance from acct/<id>.json) and the checklist of what is not built yet.
// Plain warnings only: there is no order code here and never a buy button.
// Round 5 stage 2: the rule bot's v4 look (checkpoint-after.js / checkpoint.css): the 실전 금지 card with its stamp, one
// card per line with its pixel figure and timeframe chip, the P&L as LED numbers, the checklist as rows of lights, the
// numbers in key-value blocks, the small-start example as ◆ lines, "버티는 수익인가" in full behind 펼치기.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {CONFIRM_KO, kindOfId} from "../labels.js";
import {FEW} from "../g4.js";

/** An account-like object for the pixel figure and the name chip (the accounts.json row when there, else from the id). */
function acctOf(id, name, row) {
  if (row) return row;
  const x = String(id || "");
  const tf = /-(15m|30m)$/.exec(x), sh = /(?:^|-)(S2|N02|N04)(?:-|$)/.exec(x);
  return {id: x, name: name || x, kind: kindOfId(x), tf: tf ? tf[1] : null, short: sh ? sh[1] : null};
}
/** A check as a small light: the dot AND ✓ / ✗ / — (never colour alone). */
const light = (ok) => h("span", {class: ["s2a-lt", ok == null ? "na" : ok ? "ok" : "no"]}, h("i", {"aria-hidden": "true"}), ok == null ? "—" : ok ? "✓" : "✗");

const START_USD = 300, MARGIN_SHARE = 0.10;
const TAKER = 0.0005, SLIP = 0.0002;

export async function mount(el, ctx) {
  ctx.setTitle("실전 준비");
  const top = h("div");
  const list = h("div", {class: "stack"});
  el.append(ui.screenHead("실전 준비", "후보가 실제 돈에 쓸 만한지, 무엇이 아직 없는지"),
    h("section", {class: "card hero dl-verdict s2a-hero s2a-vhead", "aria-label": "먼저"},
      h("div", {class: "s2a-hrow"}, ui.plate("먼저")),
      h("div", {class: "s2a-stamp", "aria-hidden": "true"}, h("b", null, "실전 금지"), h("small", null, "주문 없음")),
      h("p", {class: "dl-vbig no"}, "실전 금지"),
      h("p", {class: "dl-vline"}, "이 봇에는 주문 코드도 거래소 키도 없습니다. 아래는 두 분이 정할 때 볼 숫자와 남은 일입니다."),
      h("ul", {class: "s2a-dlines"}, h("li", null, "실전 후보가 나와도 실제 돈을 쓸지는 ", h("b", null, "두 분이 정합니다"), "."),
        h("li", null, "이 화면에는 ", h("b", null, "사는 버튼이 없습니다"), ". 숫자와 남은 일만 보여 줍니다.")),
      h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: "#/judge"}, "판정"), h("a", {class: "btn-line", href: "#/path"}, "졸업 길"))),
    top, list);

  let seen = null;
  async function load() {
    let judge, home, costs, accts;
    try {
      [judge, home, costs, accts] = await Promise.all([ctx.api("/api/judge"), ctx.api("/api/home").catch(() => null),
        ctx.api("/api/costs").catch(() => null), ctx.api("/api/accounts").catch(() => null)]);
    } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!seen) put(list, ui.errorBox(e, load));
      return;
    }
    const key = [judge, home, costs, accts].map((x) => x && x.generated_ms).join("|");
    if (key === seen) return;
    seen = key;
    if (!judge || isMissing(judge)) { put(top); put(list, ui.missing("판정 자료")); return; }
    const cands = judge.candidates || [];
    const closest = home && !isMissing(home) && home.goal ? home.goal.closest : null;
    const targets = cands.length ? cands.map((c) => ({id: c.id, L: c.L, cand: c})) : closest ? [{id: closest.id, L: closest.L, closest}] : [];
    put(top, cands.length
      ? K4.secRow(`실전 후보 ${cands.length}줄`, "우리 기준을 넘고 4주 확인 기간까지 넘은 줄입니다. 아래에서 줄마다 숫자와 남은 일을 보세요.")
      : h("div", {class: "stack tight"}, K4.secRow("아직 실전 후보 없음"), h("p", {class: "k4-reading"}, closest
        ? `실전 후보가 아직 없어서, 우리 기준에 가장 가까운 줄(${closest.name || closest.id} ${fmt.lev(closest.L)}, ${closest.of}개 중 ${closest.ok}개 통과)을 대신 봅니다.`
        : "실전 후보도, 가까운 줄 자료도 아직 없습니다.")));
    if (!targets.length) { put(list, ui.none("기록 없음")); return; }
    const details = await Promise.all(targets.map((t) => ctx.api(`/api/account/${encodeURIComponent(t.id)}`).catch(() => null)));
    if (!ctx.alive()) return;
    put(list, targets.map((t, i) => lineCard(t, details[i], judge, costs, accts, ctx)));
  }

  await load();
  ctx.every(60000, load);
}

function lineCard(t, acct, judge, costs, accts, ctx) {
  const row = (judge.rows || []).find((r) => r.id === t.id && r.L === t.L) || null;
  const conf = (judge.confirm || []).find((c) => c.id === t.id && c.L === t.L) || null;
  const a = accts && !isMissing(accts) ? (accts.accounts || []).find((x) => x.id === t.id) : null;
  const line = a ? (a.lines || {})[String(t.L)] : null;
  const cost = costs && !isMissing(costs) ? (costs.lines || []).find((x) => x.id === t.id && x.L === t.L) : null;
  const name = (t.cand && t.cand.name) || (row && row.name) || (a && a.name) || t.id;
  const rb = row && row.robust;
  const flags = rb && Array.isArray(rb.flags_ko) ? rb.flags_ko : null;
  // the line's typical stop distance (median |entry − stop| / entry of its trades at this leverage)
  const tr = acct && !isMissing(acct) ? (acct.trades || []).filter((x) => Number(x.L) === Number(t.L) && x.entry && x.stop) : [];
  const ds = tr.map((x) => Math.abs(Number(x.entry) - Number(x.stop)) / Number(x.entry)).filter((v) => v > 0 && Number.isFinite(v)).sort((x, y) => x - y);
  const d = ds.length ? ds[Math.floor(ds.length / 2)] : null;
  const margin = START_USD * MARGIN_SHARE, notional = margin * t.L;
  const oneR = d != null ? notional * d : null;
  const fee = notional * (TAKER + SLIP) * 2;
  const win = t.cand ? t.cand.window : conf ? {n: conf.n, mean_R: conf.mean_R, pnl_pct: conf.pnl_pct, max_dd: conf.max_dd} : null;
  const checks = [
    {ok: !!t.cand, ko: "확인 기간 통과 (실전 후보)", why: t.cand ? `${fmt.mmdd(t.cand.decided_ms)}에 통과` : conf ? `지금 ${CONFIRM_KO[conf.status] || conf.status}` : "아직 확인 기간 전"},
    {ok: cost ? Number(cost.pnl_adj) > 0 : null, ko: "실제 호가 비용을 넣어도 이익", why: cost ? `${fmt.money(cost.pnl_adj, true)} (비용 전 ${fmt.money(cost.pnl, true)})` : "잰 비용 기록 없음"},
    {ok: row && row.stops ? !!row.stops.ours_pass : null, ko: "정지 규칙을 걸어도 우리 기준 통과", why: row && row.stops ? `정지 규칙 손익 ${fmt.pct(row.stops.pnl_pct, true)}` : "준비 중"},
    {ok: flags ? flags.length === 0 : null, ko: "버티는 수익 경고 없음", why: flags ? (flags.length ? `경고 ${flags.length}개` : "없음") : "준비 중"},
    {ok: false, ko: "실제 주문 연결", why: "없음: 이 봇은 주문을 넣지 않습니다 (만들지 않았음)"},
    {ok: false, ko: "거래소 키 · 실제 계좌", why: "없음"},
    {ok: false, ko: "두 분의 결정", why: "실제 돈을 쓸지, 얼마로 시작할지 두 분이 정해야 합니다"},
  ];
  const fig = acctOf(t.id, name, a);
  const pT = line ? fmt.pct(line.pnl_pct, true) : "—", aT = cost ? fmt.pct(cost.pnl_adj_pct, true) : null;
  const kv = (pairs) => h("dl", {class: "kv s2a-kv"}, pairs.map(([k, v]) => h("div", null, h("dt", null, k), h("dd", null, v ?? "—"))));
  const sig = (v, t) => ui.signed(t, fmt.tone(v, t));
  return ui.card({plate: t.cand ? "실전 후보" : "가장 가까운 줄", cls: t.cand ? "g4-ready cand s2a-ready" : "g4-ready s2a-ready",
    acts: h("a", {class: "btn-line", href: ctx.href("account", t.id)}, "계좌 자세히")},
  h("div", {class: "s2a-candn"}, h("a", {class: "s2a-nm", href: ctx.href("account", t.id), title: t.id}, K4.acctFig(fig, 26), K4.acctName(fig)),
    h("span", {class: "dl-levtag", dataset: {lev: t.L}}, fmt.lev(t.L)), conf ? ui.confirmBadge(conf) : null),
  h("div", {class: "pnl s2a-ledbox"},
    h("div", null, h("span", {class: "k"}, `지금 손익 · ${fmt.lev(t.L)} 줄`), h("b", {class: ["led-num", "num", line ? fmt.tone(line.pnl_pct, pT) : ""]}, pT)),
    h("div", {class: "r"}, h("span", {class: "k"}, "실제 비용 넣으면"), aT ? h("b", {class: ["led-sm", "num", fmt.tone(cost.pnl_adj_pct, aT)]}, aT)
      : h("b", {class: "led-sm"}, "기록 없음"))),
  h("p", {class: "k4-k"}, "남은 일 확인표"),
  h("div", {class: "s2a-cklist", role: "list"}, checks.map((c) => h("div", {class: ["s2a-ckrow", c.ok == null ? "na" : c.ok ? "ok" : "no"], role: "listitem"},
    light(c.ok), h("b", null, c.ko), h("span", {class: "muted"}, c.why)))),
  h("div", {class: "s2a-wrap even"},
    h("div", {class: "stack tight"}, h("p", {class: "k4-k"}, "확인 기간"),
      win ? kv([
        ["기간", conf ? `${fmt.mmdd(conf.start_ms)} ~ ${fmt.mmdd(conf.decided_ms || conf.end_ms)}` : "—"],
        ["거래", `${fmt.int(win.n)}건`],
        ["평균 R", sig(win.mean_R, fmt.r(win.mean_R))],
        ["손익", sig(win.pnl_pct, fmt.pct(win.pnl_pct, true))],
        ["최대 낙폭", fmt.ratio(win.max_dd)]]) : ui.none("아직 확인 기간에 들어가지 않았습니다")),
    h("div", {class: "stack tight"}, h("p", {class: "k4-k"}, "실제 비용과 정지 규칙"),
      kv([
        ["지금 손익", line ? sig(line.pnl_pct, fmt.pct(line.pnl_pct, true)) : "—"],
        ["실제 비용 넣으면", cost ? sig(cost.pnl_adj_pct, fmt.pct(cost.pnl_adj_pct, true)) : "기록 없음"],
        ["더 든 비용", cost && cost.mean_extra_bps != null ? `거래마다 ${fmt.num(cost.mean_extra_bps, 2, true)}bp` : "—"],
        ["정지 규칙 걸면", line && line.stops ? sig(line.stops.pnl_pct, fmt.pct(line.stops.pnl_pct, true)) : "—"]]))),
  h("div", {class: "s2a-small-start"}, h("p", {class: "k4-k"}, `작게 시작한다면 (예: $${START_USD}의 ${MARGIN_SHARE * 100}%)`),
    h("ul", {class: "s2a-dlines"},
      h("li", null, `증거금 $${fmt.num(margin, 0)} × ${t.L}배 = 포지션 $${fmt.num(notional, 0)}`),
      oneR != null ? h("li", null, `이 줄의 손절 거리 가운데 값 ${fmt.num(d * 100, 2)}% → 손절 한 번(1R) ≈ `, h("b", null, `$${fmt.num(oneR, 2)}`), ` 손실 + 수수료·슬리피지 약 $${fmt.num(fee, 2)}`)
        : h("li", null, "손절 거리: 거래 기록이 없어 셀 수 없습니다"),
      oneR != null ? h("li", null, "5번 연속 손절이면 약 ", h("b", null, `$${fmt.num(5 * (oneR + fee), 0)}`), ` (시작 돈의 ${fmt.num(5 * (oneR + fee) / START_USD * 100, 0)}%)`) : null,
      oneR != null && win && win.mean_R != null ? h("li", null, `확인 기간처럼 거래 ${fmt.int(win.n)}건에 평균 ${fmt.r(win.mean_R)}이면 약 ${fmt.money(win.n * win.mean_R * oneR, true)} (수수료 후 R 기준, 어림)`) : null),
    h("p", {class: "note"}, "어림 계산입니다: 실제로는 배수·체결·펀딩·연속 손실 순서에 따라 달라집니다. 정지 규칙(계좌 −20% · 하루 −5% · 5연패)을 함께 쓰는 것을 전제로 합니다.")),
  robustBlock(rb));
}

/** CONTRACT 9.10 "버티는 수익인가" in full, each number with a plain sentence. */
function robustBlock(rb) {
  if (!rb || typeof rb !== "object") return h("div", {class: "g4-robfull"}, h("p", {class: "k4-k"}, "버티는 수익인가"), ui.none("준비 중"));
  const hf = rb.half || {};
  const flags = Array.isArray(rb.flags_ko) ? rb.flags_ko : [];
  const wd = rb.worst_day;
  return h("div", {class: "g4-robfull"}, h("p", {class: "k4-k"}, "버티는 수익인가"),
    flags.length ? h("div", {class: "row wrap dl-pills"}, flags.map((f) => h("span", {class: "pp warn g4-flag"}, `⚠ ${f}`)))
      : h("p", {class: "g4-ok"}, "✓ 경고 없음: 몇 건의 큰 거래나 한 코인, 운 좋은 앞 시기에만 기대는 모습은 보이지 않습니다."),
    ui.disclosure("여섯 가지 숫자 펼치기", h("dl", {class: "g4-robkv"},
      h("div", null, h("dt", null, "큰 거래 5건의 몫"), h("dd", null, h("b", null, rb.top5_share == null ? "—" : rb.top5_share > 1 ? "100% 넘음" : fmt.ratio(rb.top5_share, 0)),
        h("small", null, "수익 가운데 가장 큰 거래 5건이 낸 몫. 100%가 넘으면 그 5건을 빼면 손실입니다. 작을수록 고르게 번 것입니다."))),
      h("div", null, h("dt", null, "앞 절반 → 뒤 절반"), h("dd", null, h("b", null, `${fmt.r(hf.first_R)} → ${fmt.r(hf.second_R)}`),
        h("small", null, `닫힌 거래를 시간 순서로 반씩(${fmt.int(hf.first_n)}건 / ${fmt.int(hf.second_n)}건) 나눈 평균 R. 뒤가 크게 나빠졌으면 처음의 운이 다했을 수 있습니다.`))),
      h("div", null, h("dt", null, "번 코인"), h("dd", null, h("b", null, `${fmt.int(rb.coins_up)} / ${fmt.int(rb.coins_traded)}개`),
        h("small", null, "거래한 코인 가운데 이익이 난 코인 수. 한두 코인에서만 벌었다면 그 코인의 우연일 수 있습니다."))),
      h("div", null, h("dt", null, "가장 긴 연속 손실"), h("dd", null, h("b", null, `${fmt.int(rb.max_lose_streak)}번`),
        h("small", null, "실제 돈이면 이만큼 연속으로 잃는 것을 견뎌야 합니다 (정지 규칙은 5연패에서 하루 쉼)."))),
      h("div", null, h("dt", null, "가장 나쁜 하루"), h("dd", null, h("b", null, wd ? `${String(wd.day).slice(5).replace("-", "/")} ${fmt.money(wd.pnl, true)}` : "—"),
        h("small", null, "한국 시간 하루 동안 닫힌 거래의 손익 합계 가운데 가장 나쁜 날."))),
      h("div", null, h("dt", null, "닫힌 거래"), h("dd", null, h("b", null, `${fmt.int(rb.n)}건 · ${fmt.money(rb.pnl, true)}`),
        h("small", null, Number(rb.n) < FEW ? "거래가 30건보다 적어 위 숫자들이 우연일 수 있습니다." : "이 줄의 모든 닫힌 거래."))))));
}
