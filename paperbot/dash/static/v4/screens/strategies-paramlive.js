// 커스텀값 실시간 비교 (매매법 상세 #/strategies/<id>, the 36 only; owners' "2번" 2026-10-10). GET
// /api/v4/paramlive/<id> (dash/more/paramlive.py) reads what the nightly custom-value shadow (paperbot/paramshadow.py,
// 10:00 KST) wrote: per timeframe the default recomputed the same way (기본값(재계산)) next to the real account, the share
// of entries both have (재계산 일치), and every one-number variant (×0.5 · ×0.75 · ×1.25 · ×1.5 of one parameter) with
// its trades, win rate, money and its difference from the recomputed default, grouped by parameter.
// At a glance (second round, 10/10): each timeframe opens with the server's one-line reading (summary_ko: too early /
// ★ 지켜볼 후보 / no signal changed / more made more but none beyond the luck line / most did worse; accent only for a ★),
// and each parameter shows its five numbers as bars (×0.5 · ×0.75 · 기본 · ×1.25 · ×1.5, the money each made since the v4
// start on one shared scale, up above / down below the zero line, the default outlined in its highlighted column) above
// its rows. The luck test reads as a percentage of the luck line ("운 기준선까지 37%", the bar's line = 100%).
// Two numbers at once (the job's version 2, combo "pair", parts [{param, mult, value, default, param_ko}]): one more
// group after the parameters, 두 숫자 함께 바꾸기, its rows named by both changes ("슈퍼트렌드 ATR 길이 10→8 + 슈퍼트렌드
// 배수 6→7.5", the whole label on its own line on a phone), the most money over the default first, PAIR_TOP of them and
// the rest behind 전체 보기 (N개). A version-1 file (no pairs) shows the parameter groups only.
// HONESTY: a shadow and a reference, never a verdict (no pass / fail words). ★ is the job's own luck-corrected mark
// (enough trades, above the luck line for the number of variants tested, better in both halves) in the neutral accent;
// "거래 부족" where the job could not test, "기본값과 신호 같음" where the changed number never changed a signal; the
// money difference keeps the up / down colours (money made or lost against the default, a fact). The job's own texts
// (luck, parity, caution) come through the server. Rows: variant | trades over win rate | difference over money on a
// phone, the five numbers in one line where the card is wide (a container query), so nothing scrolls sideways at 390 px.
import {h, s, put, ui, fmt, motion} from "../core/pb.js";

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

/** A value that may be a list ("15·22·30·45"): a line may break after each dot where the room is narrow. */
export function valueEl(v) {
  if (!Array.isArray(v)) return valueKo(v);
  return v.flatMap((x, i) => (i ? ["·", h("wbr")] : []).concat(valueKo(x)));
}

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

/** "10/08까지 4일 · 10/10 10:00 계산" (the card's sub line says 매일 10:00 갱신). */
export function metaLine(d) {
  return `${dayKo(d.through_day)}까지 ${fmt.int(d.days || 0)}일 · ${d.generated_ms ? fmt.kst(d.generated_ms) + " 계산" : "계산 시각 —"}`;
}

/** The job's texts as small notes (luck, parity, caution), in that order, plus the label. */
export function texts(d, keys = ["luck", "parity", "caution"]) {
  const t = d.texts_ko || {};
  return keys.filter((k) => t[k]).map((k) => h("p", {class: "note"}, t[k]));
}

// ---------------------------------------------------------------- the luck line, as a percentage
/** luck.ratio (the job's z over its luck line) as the share of the line reached, whole percent; below the default: 0. */
export function luckPct(ratio) {
  return ratio == null || !Number.isFinite(Number(ratio)) ? null : Math.round(Math.max(0, Number(ratio)) * 100);
}

/** The small luck bar: filled to min(ratio, 1.5) / 1.5; its line (the luck line itself, 100%) sits at two thirds. */
export function luckBar(ratio) {
  const w = Math.max(0, Math.min(1.5, Number(ratio) || 0)) / 1.5;
  return h("span", {class: ["pl-lbar", ratio >= 1 ? "is-over" : ""], "aria-hidden": "true"}, h("i", {style: {"--w": (w * 100).toFixed(1) + "%"}}));
}

/** "운 기준선까지 37%" with its bar; "거래 부족" where the job could not test (too few trades on either side). */
export function luckBit(l, minTrades) {
  if (!l) return null;
  if (l.small || l.ratio == null) {
    return h("span", {class: "pl-luck is-small", title: `거래 ${fmt.int(minTrades)}건 미만 (이 변형이나 기본값): 운 기준선을 계산하지 않았습니다`}, "거래 부족");
  }
  const words = `운 기준선까지 ${fmt.int(luckPct(l.ratio))}%`;
  return h("span", {class: "pl-luck", title: `${words} (100% = 이 칸에서 시험한 변형 수만큼 엄격하게 잡은 운 기준선, 넘어야 ★ 후보)`},
    luckBar(l.ratio), h("span", {class: "pl-lw"}, words));
}

// ---------------------------------------------------------------- one timeframe
function side(title, st, sub) {
  st = st || {};
  const n = st.trades || 0;
  return h("div", {class: "pl-side"},
    h("span", {class: "k"}, title),
    h("b", {class: ["num", fmt.tone(st.pnl)]}, n ? fmt.money(st.pnl, true) : "거래 없음"),
    h("span", {class: "s num"}, `거래 ${fmt.int(n)}건 · 승률 ${wr(st.win_rate)}`),
    sub || null,
    st.bust ? ui.pill("파산", "bad") : null);
}

// ---------------------------------------------------------------- one number or two (the job's version 2: combo, parts)
/** A pair changes two numbers at once (each ×0.75 or ×1.25); a row of a version-1 file is always one number. */
export const isPair = (v) => !!v && (v.combo === "pair" || (Array.isArray(v.parts) && v.parts.length > 1));

/** A variant's change in words: "슈퍼트렌드 배수 6→3", a pair "슈퍼트렌드 배수 6→4.5 + ROC 길이 9→11". */
export function changeKo(parts) {
  return (parts || []).filter((p) => p && p.param).map((p) => `${p.param_ko || p.param} ${valueKo(p.default)}→${valueKo(p.value)}`).join(" + ");
}

export const PAIR_TOP = 8;            // pair rows shown before 전체 보기
/** The pair rows of a cell, the most money over the default first: {top: the first `top`, rest: the others, n}. */
export function pairRows(variants, top = PAIR_TOP) {
  const rows = (variants || []).filter(isPair).sort((a, b) => (Number(b.diff_pnl) || 0) - (Number(a.diff_pnl) || 0));
  return {top: rows.slice(0, top), rest: rows.slice(top), n: rows.length};
}

const STAR_TIP = "★ = 거래 충분 · 운 기준선 위 · 앞뒤 절반 모두 기본값보다 많이 범 (참고, 판정 아님)";

/** A pair's label: each change kept whole where it fits ("슈퍼트렌드 ATR 길이 10→8" + "슈퍼트렌드 배수 6→7.5"). */
function pairLabel(v) {
  const parts = (v.parts || []).filter((p) => p && p.param);
  return parts.map((p, i) => [i ? h("span", {class: "pl-plus"}, " + ") : null,
    h("span", {class: "pl-part"}, `${p.param_ko || p.param} `, h("span", {class: "num"}, valueEl(p.default), "→", valueEl(p.value)))]);
}

/** quiet: the cell's default itself is under the star floor (said once in the one-line reading, not on every row). */
function variantRow(v, minTrades, quiet) {
  const same = !!v.same_as_base;
  const n = v.trades || 0;
  const pair = isPair(v);
  const tags = h("span", {class: "pl-tags"},
    same ? ui.pill("기본값과 신호 같음", "thin", "이 숫자로 바꿔도 v4 시작부터 신호가 하나도 달라지지 않았습니다") : null,
    v.bust ? ui.pill("파산", "bad") : null,
    same || quiet ? null : luckBit(v.luck, minTrades));
  const star = v.star ? h("b", {class: "pl-star", title: STAR_TIP}, "★ ") : null;
  const name = pair
    ? h("span", {class: "pl-v", title: (v.parts || []).map((p) => `${p.param_ko || p.param} ${multKo(p.mult)}`).join(" · ")}, star, pairLabel(v))
    : h("span", {class: "pl-v"}, star, h("b", {class: "num"}, multKo(v.mult)), h("span", {class: "num"}, " = ", valueEl(v.value)));
  return h("div", {class: ["pl-row", pair ? "is-pair" : "", same ? "is-same" : "", v.star ? "is-star" : ""], role: "row"},
    h("span", {class: "pl-nm", role: "cell"}, name, pair ? null : tags),
    pair ? h("span", {class: "pl-tg", role: "cell"}, tags) : null,
    h("span", {class: "pl-tr num", role: "cell"}, `${fmt.int(n)}건`),
    h("span", {class: "pl-wr num", role: "cell"}, wr(v.win_rate)),
    h("span", {class: ["pl-pn num", same ? "" : fmt.tone(v.pnl)], role: "cell"}, fmt.money(v.pnl, true)),
    h("b", {class: ["pl-df num", same ? "" : fmt.tone(v.diff_pnl, fmt.money(v.diff_pnl))], role: "cell"}, same ? "같음" : fmt.money(v.diff_pnl, true)));
}

// ---------------------------------------------------------------- 숫자를 바꾸면: five bars per parameter
/** One parameter's bars in order: the smaller numbers, the default (the cell's recomputed base), the bigger numbers. */
export function chartSlots(p, rows, base) {
  const vs = (rows || []).slice().sort((a, b) => a.mult - b.mult);
  const b = base || {};
  const slot = (v) => ({mult: v.mult, value: v.value, pnl: Number(v.pnl) || 0, trades: v.trades || 0, same: !!v.same_as_base, star: !!v.star, base: false});
  return [...vs.filter((v) => v.mult < 1).map(slot),
    {mult: 1, value: p.default, pnl: Number(b.pnl) || 0, trades: b.trades || 0, same: false, star: false, base: true},
    ...vs.filter((v) => v.mult > 1).map(slot)];
}

const CH_H = 56, CH_PAD = 3;          // the bar area in viewBox units (the css gives it the same height in px)

/** The shared scale of one parameter's bars: zero inside [lowest, highest], each bar's height proportional to |P&L|. */
export function chartScale(vals) {
  const top = Math.max(0, ...vals), bot = Math.min(0, ...vals), span = top - bot || 1;
  return (v) => CH_PAD + (CH_H - 2 * CH_PAD) * (top - v) / span;
}

function paramChart(p, rows, base) {
  const slots = chartSlots(p, rows, base);
  if (!slots.some((x) => x.trades)) return h("p", {class: "pl-ch-none"}, "아직 거래가 없어 막대가 없습니다");
  const n = slots.length, cw = 100 / n, bi = slots.findIndex((x) => x.base);
  const Y = chartScale(slots.map((x) => x.pnl));
  const amount = (x) => (x.same ? "같음" : fmt.num(x.pnl, 0, true));
  const label = `${p.param_ko || p.name}, v4 시작부터 번 돈: ` +
    slots.map((x) => `${x.base ? "기본 " : multKo(x.mult) + " "}${valueKo(x.value)} ${amount(x)}${x.star ? " ★" : ""}`).join(" · ");
  const bars = slots.map((x, i) => {
    const y0 = Y(Math.max(0, x.pnl)), y1 = Y(Math.min(0, x.pnl));
    return s("rect", {class: ["pl-ch-bar", x.pnl > 0 ? "up" : x.pnl < 0 ? "down" : "zero", x.base ? "is-base" : "", x.same ? "is-same" : ""],
      x: (i * cw + cw * 0.22).toFixed(1), width: (cw * 0.56).toFixed(1), y: y0.toFixed(1), height: Math.max(1, y1 - y0).toFixed(1),
      "vector-effect": "non-scaling-stroke"});
  });
  const at = (i, row) => ({gridColumn: String(i + 1), gridRow: String(row)});
  return h("div", {class: "pl-ch", style: {gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))`}},
    h("span", {class: "pl-ch-hl", style: {gridColumn: String(bi + 1), gridRow: "1 / 5"}, "aria-hidden": "true"}),
    slots.map((x, i) => h("span", {class: ["pl-ch-amt num", x.same ? "is-same" : fmt.tone(x.pnl, amount(x))], style: at(i, 1), "aria-hidden": "true"},
      x.star ? h("b", {class: "pl-ch-star"}, "★") : null, amount(x))),
    s("svg", {class: "pl-ch-svg", viewBox: `0 0 100 ${CH_H}`, preserveAspectRatio: "none", role: "img", "aria-label": label,
      style: {gridColumn: "1 / -1", gridRow: "2"}},
    s("line", {class: "pl-ch-zero", x1: 0, x2: 100, y1: Y(0).toFixed(1), y2: Y(0).toFixed(1), "vector-effect": "non-scaling-stroke"}), bars),
    slots.map((x, i) => h("b", {class: "pl-ch-v num", style: at(i, 3), "aria-hidden": "true"}, valueEl(x.value))),
    slots.map((x, i) => h("span", {class: ["pl-ch-m", x.base ? "is-base" : ""], style: at(i, 4), "aria-hidden": "true"}, x.base ? "기본" : multKo(x.mult))));
}

function headRow(first = "변형 = 값") {
  return h("div", {class: "pl-row pl-head", role: "row"},
    h("span", {class: "pl-nm", role: "columnheader"}, first), h("span", {class: "pl-tr", role: "columnheader"}, "거래"),
    h("span", {class: "pl-wr", role: "columnheader"}, "승률"), h("span", {class: "pl-pn", role: "columnheader"}, "손익"),
    h("span", {class: "pl-df", role: "columnheader"}, "기본값 대비"));
}

/** Per parameter (one number changed): its name and default, its five bars, then its own small table of variants. */
function groups(c, minTrades) {
  const quiet = ((c.base || {}).trades || 0) < minTrades;
  const singles = (c.variants || []).filter((v) => !isPair(v));
  const gs = (c.params || []).map((p) => ({p, rows: singles.filter((v) => v.param === p.name)})).filter((g) => g.rows.length);
  return gs.map((g) => h("section", {class: "pl-pg", "aria-label": g.p.param_ko || g.p.name},
    h("div", {class: "pl-group"},
      h("b", null, g.p.param_ko || g.p.name), h("span", {class: "muted"}, " · 기본값 ", valueEl(g.p.default)),
      g.p.param_ko ? h("span", {class: "muted mono pl-code"}, ` ${g.p.name}`) : null),
    paramChart(g.p, g.rows, c.base),
    h("div", {class: "pl-list", role: "table", "aria-label": `${g.p.param_ko || g.p.name}: 숫자 하나만 바꾼 변형`},
      headRow(), g.rows.map((v) => variantRow(v, minTrades, quiet)))));
}

/** 두 숫자 함께 바꾸기: every pair (each number ×0.75 or ×1.25), the most money over the default first; the first
 *  PAIR_TOP rows, the rest behind 전체 보기. Nothing when the file has no pairs (a version-1 summary). */
function pairSection(c, minTrades) {
  const quiet = ((c.base || {}).trades || 0) < minTrades;
  const {top, rest, n} = pairRows(c.variants);
  if (!n) return null;
  const list = (rows, label) => h("div", {class: "pl-list", role: "table", "aria-label": label}, headRow("바꾼 두 숫자"), rows.map((v) => variantRow(v, minTrades, quiet)));
  return h("section", {class: "pl-pg pl-pairs", "aria-label": "두 숫자 함께 바꾸기"},
    h("div", {class: "pl-chhead"},
      h("b", null, "두 숫자 함께 바꾸기"),
      h("span", {class: "pl-hint"}, `두 숫자를 각각 ×0.75 또는 ×1.25로 함께 바꾼 ${fmt.int(n)}개 · 기본값보다 많이 번 순`)),
    list(top, `두 숫자 함께 바꾼 변형 (위 ${fmt.int(top.length)}개)`),
    rest.length ? ui.disclosure(`전체 보기 (${fmt.int(n)}개)`, list(rest, `두 숫자 함께 바꾼 변형 (나머지 ${fmt.int(rest.length)}개)`)) : null);
}

/** The timeframe's one-line reading (the server's summary_ko): the accent for a ★, muted otherwise. */
function sayLine(c) {
  if (!c.summary_ko) return null;
  const star = c.summary_rule === "star";
  return h("p", {class: ["pl-say", star ? "is-star" : ""], role: "note"},
    h("span", {class: "pl-say-k"}, `${fmt.tfKo(c.tf)} 한 줄 요약`), h("span", {class: "pl-say-t"}, c.summary_ko));
}

function tfBody(d, c) {
  if (!c) return [h("p", {class: "muted"}, "이 봉의 계산이 없습니다.")];
  const par = c.parity || {};
  const minT = d.min_trades || 20;
  const k = c.k || 0, n = (c.variants || []).length;
  const b = c.base || {};
  const quiet = (b.trades || 0) < minT;
  // k split into one number / two numbers (the variants whose signals differ from the default's), when pairs exist
  const kp = (c.variants || []).filter((v) => isPair(v) && !v.same_as_base).length;
  const split = kp ? h("span", {class: "muted"}, ` (하나씩 ${fmt.int(k - kp)} · 두 숫자 함께 ${fmt.int(kp)})`) : null;
  const parWords = par.share == null ? "둘 다 아직 거래 없음"
    : `같은 진입 ${fmt.int(par.same || 0)}건 (재계산 ${fmt.int(par.base_trades || 0)}건 · 실제 ${fmt.int(par.real_trades || 0)}건)`;
  return [
    sayLine(c),
    h("div", {class: "pl-sides"},
      side("기본값(재계산)", b, b.open ? h("span", {class: "s muted"}, "지금 포지션 있음") : null),
      side("실제 계좌", c.real)),
    h("p", {class: "pl-par"}, h("b", null, "재계산 일치 "), h("b", {class: "num"}, par.share == null ? "—" : fmt.pct(par.share, 0, false)),
      h("span", {class: "muted"}, ` · ${parWords}`)),
    h("p", {class: "pl-sum"}, k
      ? [`신호가 달라진 변형 ${fmt.int(k)}개`, split, " 중 기본값보다 번 것 ", h("b", {class: "num"}, `${fmt.int(c.better || 0)}개`), " · ★ ", h("b", {class: "num"}, fmt.int(c.stars || 0)),
        n > k ? h("span", {class: "muted"}, ` · 신호가 같은 변형 ${fmt.int(n - k)}개`) : null]
      : `이 봉에서는 숫자를 바꿔도 신호가 하나도 달라지지 않았습니다 (변형 ${fmt.int(n)}개 모두 기본값과 같음).`),
    h("div", {class: "pl-chhead"},
      h("b", null, "숫자 하나만 바꾸면"),
      h("span", {class: "pl-hint"}, "가운데가 지금 숫자, 왼쪽은 작게 · 오른쪽은 크게 (막대 = v4 시작부터의 손익)"),
      quiet ? null : h("span", {class: "pl-hint pl-hint-luck"}, luckBar(1),
        h("span", null, "운 기준선까지 NN% (막대의 세로줄 = 100%) · 100%를 넘고 기간 앞·뒤 모두 나아야 ★"))),
    groups(c, minT),
    pairSection(c, minT),
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
  const card = ui.card({plate: "커스텀값 실시간 비교", sub: "v4 시작부터 · 숫자를 바꾼 그림자 계좌 · 매일 10:00 갱신", cls: "strat-o7 strat-pl"}, body);
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
