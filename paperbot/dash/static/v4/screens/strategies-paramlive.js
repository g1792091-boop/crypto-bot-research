// 커스텀값 실시간 비교 (매매법 상세 #/strategies/<id>, the 36 only; owners' "2번" 2026-10-10). GET
// /api/v4/paramlive/<id> (dash/more/paramlive.py) reads what the nightly custom-value shadow (paperbot/paramshadow.py,
// 10:00 KST) wrote: per timeframe the default recomputed the same way (기본값(재계산)) next to the real account, the share
// of entries both have (재계산 일치), and every one-number variant (×0.5 · ×0.75 · ×1.25 · ×1.5 of one parameter) with
// its trades, win rate, money and its difference from the recomputed default, grouped by parameter.
// HONESTY: a shadow and a reference, never a verdict (no pass / fail words). ★ is the job's own luck-corrected mark
// (enough trades, above the luck line for the number of variants tested, better in both halves) in the neutral accent;
// "표본 적음" where the job could not test, "기본값과 신호 같음" where the changed number never changed a signal; the
// money difference keeps the up / down colours (money made or lost against the default, a fact). The job's own texts
// (luck, parity, caution) come through the server. Rows: variant | trades over win rate | difference over money on a
// phone, the five numbers in one line where the card is wide (a container query), so nothing scrolls sideways at 390 px.
import {h, put, ui, fmt, motion} from "../core/pb.js";

export const TFS = ["15m", "30m", "1h", "4h"];

/** A parameter value as the study wrote it: 10 → "10", 6.0 → "6", 0.75 → "0.75", [5, 8, 10, 15] → "5·8·10·15". */
export function valueKo(v) {
  if (Array.isArray(v)) return v.map(valueKo).join("·");
  if (typeof v !== "number" || !Number.isFinite(v)) return v == null ? "—" : String(v);
  let d = 0;
  while (d < 4 && Math.abs(v * 10 ** d - Math.round(v * 10 ** d)) > 1e-9) d++;
  return fmt.num(v, d);
}
export const multKo = (m) => `×${valueKo(m)}`;
/** "2026-10-08" → "10/08" (the job's last finished UTC day). */
export const dayKo = (day) => (day ? fmt.mmdd(Date.parse(`${day}T00:00:00Z`)) : "—");
const wr = (x) => (x == null ? "—" : fmt.pct(x, 0, false));

/** The state lines every paramlive answer can carry: the last night that failed, a run that is still filling. */
export function stateLines(d) {
  const out = [];
  if (d.error_ko) {
    out.push(h("p", {class: "pl-state", role: "status"}, ui.pill("지난 계산 실패", "warn"), d.error_ko,
      h("span", {class: "muted"}, [d.error_at ? ` · ${fmt.kst(d.error_at)}` : "", d.available ? " · 아래는 그 전 계산" : ""].join(""))));
  }
  if (d.available && d.status === "filling") {
    out.push(h("p", {class: "pl-state"}, ui.pill(`${fmt.int(d.days_remaining || 0)}일 채우는 중`, "thin"),
      `v4 시작부터 아직 다 채우지 못했습니다 (지금 ${dayKo(d.through_day)}까지 ${fmt.int(d.days || 0)}일). 남은 날은 다음 밤들에 채웁니다.`));
  }
  return out;
}

/** "10/08까지 4일 · 10/10 10:00 계산 · 매일 10:00 갱신". */
export function metaLine(d) {
  return `${dayKo(d.through_day)}까지 ${fmt.int(d.days || 0)}일 · ${d.generated_ms ? fmt.kst(d.generated_ms) + " 계산" : "계산 시각 —"} · 매일 10:00 갱신`;
}

/** The job's texts as small notes (luck, parity, caution), in that order, plus the label. */
export function texts(d, keys = ["luck", "parity", "caution"]) {
  const t = d.texts_ko || {};
  return keys.filter((k) => t[k]).map((k) => h("p", {class: "note"}, t[k]));
}

// ---------------------------------------------------------------- one timeframe
function side(title, s, sub) {
  s = s || {};
  const n = s.trades || 0;
  return h("div", {class: "pl-side"},
    h("span", {class: "k"}, title),
    h("b", {class: ["num", fmt.tone(s.pnl)]}, n ? fmt.money(s.pnl, true) : "거래 없음"),
    h("span", {class: "s num"}, `거래 ${fmt.int(n)}건 · 승률 ${wr(s.win_rate)}`),
    sub || null,
    s.bust ? ui.pill("파산", "bad") : null);
}

function luckBit(l) {
  if (!l || l.small || l.ratio == null) return null;
  const w = Math.max(0, Math.min(1.5, l.ratio)) / 1.5;
  const words = `운 기준선 대비 ${fmt.num(l.ratio, 2)}배`;
  return h("span", {class: "pl-luck", title: `${words} (1배 = 이 칸에서 시험한 변형 수만큼 엄격하게 잡은 운 기준선, 넘어야 ★ 후보)`},
    h("span", {class: ["pl-lbar", l.ratio >= 1 ? "is-over" : ""], "aria-hidden": "true"}, h("i", {style: {"--w": (w * 100).toFixed(1) + "%"}})),
    h("span", {class: "pl-lw"}, words));
}

/** quiet: the cell's default itself is under the star floor (said once above the table, not on every row). */
function variantRow(v, minTrades, quiet) {
  const same = !!v.same_as_base;
  const small = !same && !quiet && v.luck && v.luck.small;
  const n = v.trades || 0;
  return h("div", {class: ["pl-row", same ? "is-same" : "", v.star ? "is-star" : ""], role: "row"},
    h("span", {class: "pl-nm", role: "cell"},
      h("span", {class: "pl-v"}, v.star ? h("b", {class: "pl-star", title: "★ = 거래 충분 · 운 기준선 위 · 앞뒤 절반 모두 기본값보다 많이 범 (참고, 판정 아님)"}, "★ ") : null,
        h("b", {class: "num"}, multKo(v.mult)), h("span", {class: "num"}, ` = ${valueKo(v.value)}`)),
      h("span", {class: "pl-tags"},
        same ? ui.pill("기본값과 신호 같음", "thin", "이 숫자로 바꿔도 v4 시작부터 신호가 하나도 달라지지 않았습니다") : null,
        small ? ui.pill("표본 적음", "thin", `거래 ${fmt.int(minTrades)}건 미만: 운 기준선을 계산하지 않았습니다`) : null,
        v.bust ? ui.pill("파산", "bad") : null,
        same ? null : luckBit(v.luck))),
    h("span", {class: "pl-tr num", role: "cell"}, `${fmt.int(n)}건`),
    h("span", {class: "pl-wr num", role: "cell"}, wr(v.win_rate)),
    h("span", {class: ["pl-pn num", same ? "" : fmt.tone(v.pnl)], role: "cell"}, fmt.money(v.pnl, true)),
    h("b", {class: ["pl-df num", same ? "" : fmt.tone(v.diff_pnl, fmt.money(v.diff_pnl))], role: "cell"}, same ? "같음" : fmt.money(v.diff_pnl, true)));
}

function table(c, minTrades) {
  const quiet = ((c.base || {}).trades || 0) < minTrades;
  const groups = (c.params || []).map((p) => ({p, rows: (c.variants || []).filter((v) => v.param === p.name)})).filter((g) => g.rows.length);
  return h("div", {class: "pl-list", role: "table", "aria-label": "숫자 하나만 바꾼 변형"},
    h("div", {class: "pl-row pl-head", role: "row"},
      h("span", {class: "pl-nm", role: "columnheader"}, "변형 = 값"), h("span", {class: "pl-tr", role: "columnheader"}, "거래"),
      h("span", {class: "pl-wr", role: "columnheader"}, "승률"), h("span", {class: "pl-pn", role: "columnheader"}, "손익"),
      h("span", {class: "pl-df", role: "columnheader"}, "기본값 대비")),
    groups.map((g) => [
      h("div", {class: "pl-group", role: "row"}, h("span", {role: "rowheader"},
        h("b", null, g.p.param_ko || g.p.name), h("span", {class: "muted"}, ` · 기본값 ${valueKo(g.p.default)}`),
        g.p.param_ko ? h("span", {class: "muted mono pl-code"}, ` ${g.p.name}`) : null)),
      g.rows.map((v) => variantRow(v, minTrades, quiet)),
    ]));
}

function tfBody(d, c) {
  if (!c) return [h("p", {class: "muted"}, "이 봉의 계산이 없습니다.")];
  const par = c.parity || {};
  const minT = d.min_trades || 20;
  const k = c.k || 0, n = (c.variants || []).length;
  const parWords = par.share == null ? "둘 다 아직 거래 없음"
    : `같은 진입 ${fmt.int(par.same || 0)}건 (재계산 ${fmt.int(par.base_trades || 0)}건 · 실제 ${fmt.int(par.real_trades || 0)}건)`;
  const b = c.base || {};
  return [
    h("div", {class: "pl-sides"},
      side("기본값(재계산)", b, b.open ? h("span", {class: "s muted"}, "지금 포지션 있음") : null),
      side("실제 계좌", c.real)),
    h("p", {class: "pl-par"}, h("b", null, "재계산 일치 "), h("b", {class: "num"}, par.share == null ? "—" : fmt.pct(par.share, 0, false)),
      h("span", {class: "muted"}, ` · ${parWords}`)),
    h("p", {class: "pl-sum"}, k
      ? [`신호가 달라진 변형 ${fmt.int(k)}개 중 기본값보다 번 것 `, h("b", {class: "num"}, `${fmt.int(c.better || 0)}개`), " · ★ ", h("b", {class: "num"}, fmt.int(c.stars || 0)),
        n > k ? h("span", {class: "muted"}, ` · 신호가 같은 변형 ${fmt.int(n - k)}개`) : null]
      : `이 봉에서는 숫자를 바꿔도 신호가 하나도 달라지지 않았습니다 (변형 ${fmt.int(n)}개 모두 기본값과 같음).`,
      (b.trades || 0) < minT ? [" ", ui.pill("표본 적음", "thin", `기본값(재계산) 거래 ${fmt.int(b.trades || 0)}건: ${fmt.int(minT)}건 미만이면 운 기준선도 ★도 없습니다`)] : null),
    table(c, minT),
  ];
}

/**
 * The card for one of the 36: right after 숫자(파라미터) 시험 결과 (strat-o7 like it). ``after``: the 5-year card the
 * detail places the parameter card after; this card goes after that one (both wait one microtask while the detail puts
 * its columns together). ``tf``: the detail's timeframe to open on. ``scope``: the detail's scope (a late answer after the
 * detail closed is dropped).
 */
export function paramliveCard(ctx, name, {after, scope, tf} = {}) {
  const body = h("div", {class: "stack tight pl-body"}, motion.shimmer(4));
  const card = ui.card({plate: "커스텀값 실시간 비교", sub: "v4 시작부터 · 숫자 하나만 바꾼 그림자 계좌 · 매일 10:00 갱신", cls: "strat-o7 strat-pl"}, body);
  const alive = () => (scope ? scope.alive() : ctx.alive());
  let cur = TFS.includes(tf) ? tf : "1h";
  let data = null;
  const slot = h("div", {class: "stack tight"});

  function drawTf(anim) {
    put(slot, ...tfBody(data, (data.cells || []).find((c) => c.tf === cur)));
    if (anim) motion.swap(slot);
  }
  function draw(d) {
    data = d;
    if (!d.available) {
      put(body, ...stateLines(d), h("p", {class: "pl-none"}, d.none_ko || "아직 첫 계산 전입니다"), d.about_ko ? h("p", {class: "note"}, d.about_ko) : null);
      return;
    }
    const tfs = TFS.filter((t) => (d.cells || []).some((c) => c.tf === t));
    if (!tfs.includes(cur)) cur = tfs.includes("1h") ? "1h" : tfs[0];
    const seg = ui.seg(tfs.map((t) => ({id: t, label: fmt.tfKo(t)})), cur, (id) => { cur = id; drawTf(true); }, {label: "봉"});
    put(body, ...stateLines(d), h("p", {class: "pl-meta"}, metaLine(d)), seg, slot,
      ...texts(d),
      ui.disclosure("기본값(재계산)이란", h("div", {class: "stack tight"}, texts(d, ["what", "base"]))),
      h("p", {class: "note"}, `${d.label_ko || "그림자 계좌 · 참고용 (판정 아님)"} · 손익 = 변형마다 따로 ${fmt.int((d.settings && d.settings.initial_equity) || 5000)} USDT에서 시작한 그림자 계좌, 닫힌 거래만`),
      ui.assume());
    drawTf(false);
  }
  async function load() {
    put(body, motion.shimmer(4));
    let d = null, err = null;
    try { d = await ctx.api(`/api/v4/paramlive/${encodeURIComponent(name)}`); } catch (e) { err = e; }
    if (!alive()) return;
    if (err && err.status === 404) { put(body, h("p", {class: "pl-none"}, "이 매매법은 커스텀값 그림자에 없습니다")); return; }
    if (!d) { put(body, ui.errorBox(err, load)); return; }
    draw(d);
    motion.swap(body);
  }
  // after the parameter card (placed after `after` in the microtask queued before this one), else right after `after`
  if (after) queueMicrotask(() => {
    if (!after.parentNode || card.parentNode) return;
    const nx = after.nextElementSibling;
    (nx && nx.classList.contains("strat-pm") ? nx : after).after(card);
  });
  load();
  return {el: card, load};
}
