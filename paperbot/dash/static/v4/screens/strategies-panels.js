// 매매법 상세의 부품 (builder C): the rule card, the live condition checklist, the 5-year card and the loss cards /
// loss patterns. Every server string goes in as text (h()). Old strat.js renderConds / lastMarks / renderProfile /
// renderSSide / lossCard, rebuilt on the shared components.
import {h, ui, fmt} from "../core/pb.js";
import {DS_DEFS, FAMILY, DS_COMMON, EXITS, LEVERAGE, REEL, STATUS_KO} from "./strategies-defs.js";
import {DS_RAW, DS_COMMON_RAW, REEL_RAW} from "./strategies-raw.js";

const MARKS_NOTE = "가격선·강도 숫자는 진입 연구에서 수익과 관계없다고 나온 설명용 표시입니다.";

const ul = (lines, cls) => h("ul", {class: ["strat-lines", cls]}, lines.map((t) => h("li", null, t)));
const raw = (label, text) => ui.disclosure(label, h("pre", {class: "strat-raw"}, text));

// ---------------------------------------------------------------- rule card
/** The rule in plain words. kind: strategy | ds200 | reel. view: the chart view (36: its condition names). */
export function ruleBody(name, kind, meta, view) {
  const out = [];
  if (kind === "ds200" && DS_DEFS[name]) {
    const d = DS_DEFS[name], f = FAMILY[d.fam];
    out.push(h("p", {class: "ink2 strat-famline"}, `${f.ko} 계열: ${f.desc}`));
    out.push(ul(d.lines));
    out.push(ui.disclosure("딥시크 44개 공통 약속", h("div", {class: "stack tight"}, ul(DS_COMMON, "small"), raw("공통 약속 원문 보기", DS_COMMON_RAW))));
  } else if (kind === "reel") {
    out.push(h("p", {class: "ink2"}, REEL.desc));
    out.push(ul(REEL.lines));
  } else {
    const c = view && view.conditions;
    if (meta && (meta.style || meta.hold)) out.push(h("p", {class: "ink2"}, [meta.style, meta.hold].filter(Boolean).join(" · ")));
    if (c && ((c.long || []).length || (c.short || []).length)) {
      const side = (ko, list) => (list && list.length ? h("li", null, h("b", null, `${ko}: `), list.map((x) => x.name).join(" · "), h("span", {class: "muted"}, " (모두 켜지면 신호)")) : null);
      out.push(h("ul", {class: "strat-lines"}, side("롱", c.long), side("숏", c.short)));
    } else {
      out.push(h("p", {class: "muted"}, view === undefined ? "조건 문장을 불러오는 중입니다" : "조건 문장은 이 매매법의 차트 보기에서 옵니다: ", view === null ? ui.notYet("준비 전") : null));
    }
  }
  out.push(ui.disclosure("나가는 법 · 레버리지", h("div", {class: "strat-exits"},
    ul([...(kind === "reel" ? EXITS.reel : EXITS.house), LEVERAGE[kind] || LEVERAGE.strategy], "small"))));
  if (kind === "ds200" && DS_RAW[name]) out.push(raw("원문 보기 (사전 등록 문서 그대로)", DS_RAW[name]));
  if (kind === "reel") out.push(raw("원문 보기 (사전 등록 문서 그대로)", REEL_RAW));
  return out;
}

// ---------------------------------------------------------------- live condition checklist
function sideList(ko, list) {
  if (!list || !list.length) return null;
  const on = list.filter((c) => c.on).length;
  return h("div", {class: "strat-cside"},
    h("div", {class: "strat-chead"}, h("b", null, `${ko} 조건`), h("span", {class: "muted num"}, `${on}/${list.length} 켜짐`)),
    h("div", {class: "prog", "aria-hidden": "true"}, h("i", {style: {"--p": (list.length ? on / list.length * 100 : 0) + "%"}})),
    h("ul", {class: "strat-conds"}, list.map((c) => h("li", {class: c.on ? "on" : ""},
      h("span", {class: "strat-dot", "aria-hidden": "true"}), h("span", {class: "nm2"}, c.name), h("span", {class: "st"}, c.on ? "켜짐" : "꺼짐")))));
}
function srLine(sr) {
  if (!sr) return null;
  const d = (v, ko) => (v == null ? "—" : `${v >= 10 ? "10+" : fmt.num(v, 1)} ATR${ko ? ` (${ko})` : ""}`);
  return `가는 쪽 가장 가까운 선 ${d(sr.room, sr.room_ko)} · 뒤쪽 가장 가까운 선 ${d(sr.floor, sr.floor_ko)}`;
}
function strengthLine(fs) {
  if (!fs || !fs.length) return null;
  return fs.map((f) => `${f.label_ko} ${fmt.num(f.value, f.value != null && Math.abs(f.value) >= 100 ? 0 : 2)} ${f.unit_ko || f.unit || ""}${f.higher_is_stronger ? "" : " (작을수록 강함)"}`).join(" · ");
}
function lastMarks(ls) {
  if (!ls) return h("p", {class: "muted"}, "최근 30일 이 코인·봉에서 이 매매법의 신호가 없습니다.");
  const st = ls.strength && ls.strength.features ? strengthLine(ls.strength.features) : ls.strength && ls.strength.error ? "강도 계산 실패" : null;
  const sr = ls.sr && !ls.sr.error ? srLine(ls.sr) : ls.sr && ls.sr.error ? "가격선 계산 실패" : null;
  return h("div", {class: "strat-marks"},
    h("p", null, h("span", {class: "muted"}, `최근 신호 ${fmt.kst(ls.bar_close)} · `), ui.sideTag(ls.side), " ",
      h("span", {class: "muted"}, STATUS_KO[ls.status] || String(ls.status || ""))),
    st ? h("p", null, "진입 강도: ", st) : null, sr ? h("p", null, sr) : null,
    !st && !sr ? h("p", {class: "muted"}, ls.error ? "표시 계산 실패" : "이 신호에는 기록이 없습니다") : null,
    h("p", {class: "muted small"}, MARKS_NOTE));
}
/** The last closed bar's entry conditions, what the bot itself signalled on that bar, and the last signal's marks. */
export function condBody(view, sigs, tf) {
  if (!view) return [h("p", {class: "muted"}, "이 매매법의 조건표는 서버에 아직 없습니다. "), ui.notYet("준비 전")];
  const c = view.conditions || {};
  const left = (l) => (l && l.length ? l.length - l.filter((x) => x.on).length : null);
  const ns = [left(c.long), left(c.short)].filter((x) => x != null);
  const near = ns.length ? Math.min(...ns) : null;
  const bot = (sigs || []).find((r) => r.bar_close === view.bar_close);
  return [
    h("p", {class: "muted strat-condhead"}, `방금 마감한 ${fmt.tfKo(tf)}봉 · ${fmt.kst(view.bar_close)} · 봇 신호: `,
      bot ? [ui.sideTag(bot.side), " ", STATUS_KO[bot.status] || String(bot.status || "")] : "없음"),
    h("div", {class: "strat-cgrid"}, sideList("롱", c.long), sideList("숏", c.short)),
    near === 0 ? h("p", {class: "strat-near accent"}, "이 봉에서 한쪽 조건이 모두 켜졌습니다")
      : near != null ? h("p", {class: "strat-near"}, `신호까지 조건 ${fmt.int(near)}개 남음`) : null,
    lastMarks(view.last_signal),
  ];
}

// ---------------------------------------------------------------- 5-year card
export function profileBody(p, tf) {
  if (!p) return [h("p", {class: "muted"}, "과거 5년 자료가 없습니다.")];
  const pc = (x) => (x == null ? "—" : fmt.pct(x, 0, false));
  const acct = (w, b) => (w == null ? "—" : h("span", {class: b ? "down" : ""}, fmt.money(w)));
  const rows = (p.rows || []).map((r) => ({...r, sel: r.tf === tf}));
  const cols = [
    {label: "봉", l: true, get: (r) => h("span", {class: r.sel ? "accent" : ""}, fmt.tfKo(r.tf), r.tf === "5m" ? h("span", {class: "muted"}, " (기록)") : null)},
    {label: "하루 신호", get: (r) => fmt.num(r.signals_per_day, 1)},
    {label: "거래당 ROE", get: (r) => (r.mean_roe == null ? "신호 적음" : h("span", {class: fmt.tone(r.mean_roe)}, fmt.pct(r.mean_roe)))},
    {label: "승률", get: (r) => pc(r.win_rate)},
    {label: "보유", get: (r) => (r.median_hold_hours == null ? "—" : `${fmt.num(r.median_hold_hours, 1)}시간`)},
    {label: "잠금 청산", get: (r) => pc(r.lock_share)},
    {label: "16봉 더", get: (r) => (r.hold_more_16 == null ? "—" : `${fmt.num(r.hold_more_16 * 100, 1, true)}%p`)},
    {label: "5년 계좌 (앞 → 뒤)", get: (r) => h("span", {class: "num"}, acct(r.account_is, r.bust_is), " → ", acct(r.account_cf, r.bust_cf))},
  ];
  const src = p.data_source === "binance_futures" ? "바이낸스 선물" : "여러 거래소 합산 현물";
  return [
    h("p", null, h("b", null, p.style || "신호 부족"), p.hold ? ` · ${p.hold}` : "",
      p.least_bad_tf ? [" · 가장 덜 나쁜 봉 ", h("b", null, fmt.tfKo(p.least_bad_tf))] : null,
      p.rare ? [" ", ui.pill("신호가 너무 드묾", "warn")] : null),
    ui.table(cols, rows),
    h("p", {class: "muted small"}, "16봉 더 = 이익 잠금으로 나간 거래를 16봉 더 들고 있었다면 거래당 ROE가 몇 %p 달라졌는지. ",
      "5년 계좌 = 1,000에서 시작한 계좌 하나로 굴린 기간 끝 금액 (10 근처면 파산)."),
    p.note_5m ? h("p", {class: "muted small"}, p.note_5m) : null,
    h("p", {class: "muted small"}, "거래당 ROE와 잠금 청산 비율은 레버리지에 따라 달라집니다. v4 보통 자리는 30배부터라, 지금 계좌와 견줄 때는 거래당 순손익을 1배 가격 %(ROE ÷ 레버리지)로 맞춰 보세요 (릴스 1:3 대결처럼)."),
    h("p", {class: "assume"}, `과거 5년 시험 (${src} 자료) · v3 크기 규칙 (모든 신호 50배부터) · 수수료·슬리피지 포함 · 성격 설명이지 실력 증거가 아닙니다. 거래당 ROE가 비용(40배 왕복 약 −5.6%) 근처면 방향을 맞히는 힘이 0에 가깝다는 뜻입니다.`),
  ];
}

/** The 5-year research card of a DeepSeek definition or the reel (/api/profile -> paperbot/ds_profiles.py profile): per
 *  timeframe and period, trades per day, net per trade (price %, no leverage, research costs in), win rate, hold.
 *  DeepSeek: the research exit closest to the live one first (X5_TRAIL2), the other behind a disclosure; the research
 *  exits are NOT the live house exits, and the card says so. */
export function researchBody(p, tf) {
  if (!p || !(p.rows || []).length) return [h("p", {class: "muted"}, "과거 5년 연구 자료가 없습니다.")];
  const ko = Object.fromEntries((p.periods || []).map((x) => [x.key, x.ko]));
  const cols = [
    {label: "봉", l: true, get: (r) => h("span", {class: r.tf === tf ? "accent" : ""}, r.first ? fmt.tfKo(r.tf) : "")},
    {label: "기간", l: true, get: (r) => ko[r.period] || r.period},
    {label: "하루 거래", get: (r) => (r.b.per_day == null ? "—" : fmt.num(r.b.per_day, r.b.per_day < 10 ? 2 : 1))},
    {label: "거래당 순손익", get: (r) => (r.b.net_pct == null ? "거래 없음" : h("span", {class: fmt.tone(r.b.net_pct)}, `${fmt.num(r.b.net_pct, 3)}%`))},
    {label: "승률", get: (r) => (r.b.win_pct == null ? "—" : `${fmt.num(r.b.win_pct, 0)}%`)},
    {label: "보유", get: (r) => (r.b.hold_hours == null ? "—" : `${fmt.num(r.b.hold_hours, 1)}시간`)},
    {label: "거래", get: (r) => [fmt.int(r.b.n), r.b.small ? h("span", {class: "muted"}, " (적음)") : null]},
  ];
  const flat = (exit) => (p.rows || []).filter((r) => r.exit === exit).flatMap((r) =>
    (p.periods || []).map((x, i) => ({tf: r.tf, period: x.key, first: i === 0, b: r.periods[x.key] || {}})));
  const ex = p.exits || {};
  const res = ex.research || [];
  const main = res[0], rest = res.slice(1);
  return [
    p.research && p.research.conclusion_ko ? h("p", null, h("b", null, p.research.conclusion_ko)) : null,
    main ? h("p", {class: "muted small"}, `연구 청산${ex.same_as_live ? " (라이브 계좌와 같음)" : ""}: ${main.ko}`) : null,
    ui.table(cols, flat(main ? main.id : null)),
    ...rest.map((x) => ui.disclosure(`다른 연구 청산으로 본 숫자: ${x.ko}`, ui.table(cols, flat(x.id)))),
    h("p", {class: "muted small"}, p.note_ko || ""),
    ex.live && !ex.same_as_live ? h("p", {class: "muted small"}, `라이브 계좌 청산: ${ex.live.ko}`) : null,
    p.cost_note_ko ? h("p", {class: "muted small"}, p.cost_note_ko) : null,
    h("p", {class: "muted small"}, Object.values(p.units_ko || {}).join(" · ")),
    h("p", {class: "assume"}, `과거 5년 연구 (바이낸스 선물 자료) · 수수료·슬리피지·펀딩 포함 · ${p.descriptive_ko || ""}`),
  ];
}

// ---------------------------------------------------------------- loss cards and loss patterns (the 36)
export function lossCard(c) {
  const ctxLine = [c.regime_ko && `이 봉 ${c.regime_ko}`, c.htf_regime_ko && `상위 봉 ${c.htf_regime_ko}`,
    c.ctx && c.ctx.adx != null && `ADX ${fmt.num(c.ctx.adx, 0)}`].filter(Boolean).join(" · ");
  const ifs = Object.entries(c.if_stop || {});
  const hold = c.hold_min == null ? "—" : fmt.dur(c.hold_min * 60);
  return h("article", {class: "strat-lcard", role: "listitem"},
    h("div", {class: "strat-lhead"}, h("b", null, `${fmt.coin(c.symbol)} ${fmt.tfKo(c.timeframe)}`), ui.sideTag(c.side), h("span", {class: "muted"}, fmt.lev(c.leverage)),
      h("span", {class: "grow"}), h("b", {class: "down num"}, `${c.reason_ko || fmt.reasonKo(c.reason)} ${fmt.pct(c.roe, 0)}`)),
    h("p", null, `${fmt.kst(c.entry_time)} 진입 · ${hold} 보유 · 진입 뒤 최고 `, h("span", {class: fmt.tone(c.best_roe)}, fmt.pct(c.best_roe, 0)),
      c.touched_first_lock ? " (잠금선 닿음)" : ""),
    ctxLine ? h("p", {class: "muted"}, ctxLine) : null,
    c.strength && c.strength.length ? h("p", {class: "muted"}, "진입 강도: ", strengthLine(c.strength)) : null,
    c.sr ? h("p", {class: "muted"}, srLine(c.sr)) : null,
    // own-exit cards (the reel and the 5m coin flips, paperbot/cards.py own_exits): their exit rule and their own stop;
    // the house stop what-ifs (1.5 / 2.5 / 3 ATR) do not apply to them, so that line is left out
    c.exits_ko ? h("p", {class: "muted"}, c.exits_ko) : null,
    c.stop_ko ? h("p", {class: "muted"}, c.stop_ko) : null,
    c.exits === "reel" ? null : h("p", {class: "muted"}, "손절 거리를 바꿨다면: ", ifs.length ? ifs.map(([k, v], i) => [i ? " · " : "", `${k} ATR `,
      h("span", {class: fmt.tone(v.roe)}, v.roe == null ? "진입 안 됨" : fmt.pct(v.roe, 0))]) : "밤 점검 뒤 표시"),
    (c.tags || []).length ? h("div", {class: "row wrap strat-tags"}, c.tags.map((t) => ui.pill(t, "thin"))) : null);
}
export function tagRows(st) {
  if (!st || !st.trades) return [ui.empty("최근 30일 끝난 거래가 없습니다")];
  const bar = (share, cls) => h("span", {class: ["strat-bar", cls]}, h("i", {style: {"--w": Math.round((share || 0) * 100) + "%"}}));
  return [
    h("p", {class: "muted small"}, `최근 30일 거래 ${fmt.int(st.trades)}건 (손실 ${fmt.int(st.losses)} · 이익 ${fmt.int(st.wins)}). 손실에서 이익보다 훨씬 자주 보이는 상황이 먼저 볼 곳입니다. 건수가 적으면 우연일 수 있습니다.`),
    h("div", {class: "strat-tagrows", role: "list"}, (st.tags || []).filter((t) => t.losses || t.wins).map((t) => h("div", {class: "strat-tagrow", role: "listitem"},
      h("div", {class: "nm2"}, t.tag), t.note ? ui.moreText(t.note, 1, "muted small") : null,
      h("div", {class: "strat-tagbars"}, h("span", {class: "k"}, "손실"), bar(t.loss_share, "down"), h("span", {class: "num"}, t.loss_share == null ? "—" : fmt.pct(t.loss_share, 0, false)),
        h("span", {class: "k"}, "이익"), bar(t.win_share, "up"), h("span", {class: "num"}, t.win_share == null ? "—" : fmt.pct(t.win_share, 0, false)))))),
    h("p", {class: "muted small"}, MARKS_NOTE),
  ];
}
