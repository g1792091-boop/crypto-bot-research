// 실거래 › 그림자 and 설정 (#/livebots/shadows, #/livebots/settings).
//   그림자  screens/livebots-shadow.js (re-exported here): the 추세판단 봇's three shadows next to the live paper, each from
//           its own start, by trade and net ROE; the old bots' shadows folded under 예전 봇 비교용.
//   설정    the combined bot's fixed rules (BTC 40x / alts 30x, margin, one position, the ladder, no KST weekend entries,
//           none ±30 min around US macro releases, the loss cap per stop), each executor's light and limits, and every
//           setting grouped by strategy (timeframe, custom numbers, stop, entry mode, conditions, switched-off buckets),
//           from the config the bot really runs (/api/v4/livebots/settings); folded, 10 strategies a page.
//           추세판단 봇 (the server's ``trend``, owners 10/21): first a card 추세 판단 규칙: 쉬기 없음 · 하루 손실 한도 없음,
//           the 2-week rule freeze from its start, its rules exactly as the bot wrote them (state trend rules: TrendRules.
//           describe, each line split at its " / "), and its members by role (눌림 · 자리 · 돌파 · 횡보 · 추세) with their
//           entry bar (30분 진입 = the closed 1h bar's trend, 1시간 진입 = the 4h bar's, 4시간 진입 = the daily bar's, 10/22);
//           every setting row carries its role and its entry (바로 진입 / 되돌림 진입: the config's trend.pullback_wait).
//           A second paper bot (owners 10/23: the 'VWAP 개선판', the server's ``bots``): its own card after the trend bot's,
//           its fixed rules from its own config with its entry gates and hold limit in the owners' words (the server's
//           rules.gates), its settings, who follows it; each executor's card says which paper bot it follows.
import {h, put, ui, fmt, motion} from "../core/pb.js";
import {josa, sourceState} from "./livebots-kit.js";
export {shadowsView, twoLines} from "./livebots-shadow.js";

const REFRESH_MS = 60 * 1000;

function loader(ctx, path, st, stateSlot, draw, every = REFRESH_MS) {
  async function load() {
    try { st.d = await ctx.api(path); st.okAt = Date.now(); put(stateSlot); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      throw e;
    }
    if (ctx.alive()) draw();
  }
  draw();
  load().catch(() => {});
  ctx.every(every, () => load().catch(() => {}), {now: false});
}

// ---------------------------------------------------------------- 설정
const pctOf = (x) => (x == null ? "—" : fmt.pct(x, 0, false));

/** The ladder in the owners' words (paperbot/ladder2.py ComboLadder.describe): the rule bot's form (lock first_lock at
 *  first_lock + trigger_gap, then one step more per step) or the two-part one (next_trigger / next_gap: 11 % -> 10 %,
 *  15 % -> 12 %, 20 % -> 17 %, then every 5 % the reached net ROE minus 3 %). "—" without the numbers. */
export function ladderKo(lad) {
  const l = lad || {};
  if (l.first_lock == null || l.trigger_gap == null) return "—";
  const first = `순ROE ${pctOf(l.first_lock + l.trigger_gap)}에서 ${pctOf(l.first_lock)} 잠금`;
  if (l.next_trigger == null || l.next_gap == null) return `${first}, 그 뒤 ${pctOf(l.step)}씩 올림`;
  const t2 = l.next_trigger, l2 = l.next_trigger - l.next_gap, st = l.step;
  return `${first}, ${pctOf(t2)}에서 ${pctOf(l2)}` + (st != null ? `, ${pctOf(t2 + st)}에서 ${pctOf(l2 + st)}, 그 뒤 ${pctOf(st)}마다` : ", 그 뒤")
    + ` (닿은 순ROE - ${pctOf(l.next_gap)})`;
}

/** The fixed rules in the owners' words, from the config's own numbers (a bot with entry gates, the 'VWAP 개선판': its
 *  gates and hold limit too, the server's rules.gates words; it has no trend judgment that keeps going in a pause). */
export function rulesList(r) {
  const gates = Array.isArray(r.gates) && r.gates.length ? r.gates : null;
  const entryGates = gates ? gates.filter((g) => g.id !== "max_hold") : [];
  const hold = gates ? gates.find((g) => g.id === "max_hold") : null;
  const out = [
    ["배수", `BTC ${r.leverage_btc ?? "—"}배 · 나머지 ${r.leverage_alt ?? "—"}배 (고정)`],
    ["증거금", typeof r.margin === "number" ? `잔고의 ${pctOf(r.margin)}` : r.margin === "leverage" ? "배수와 같은 %" : "—"],
    ["포지션", "한 번에 하나"],
    ["계단 잠금", ladderKo(r.ladder)],
    ["손절 한 번", r.max_loss_frac != null ? `잔고의 최대 ${pctOf(r.max_loss_frac)} (넘으면 크기를 줄임)` : "—"],
    ["주말", r.no_weekend ? "한국 시간 토·일에는 새로 진입하지 않음 (열린 포지션은 그대로)" : "주말에도 진입"],
    ["경제 발표", r.macro_blackout_min ? `미국 경제 발표 앞뒤 ${r.macro_blackout_min}분은 진입하지 않음` : "제한 없음"],
    r.us_open_pause_min || r.us_open_pre_min ? ["나스닥 개장", `미국 주식시장 개장 ${[r.us_open_pre_min ? `앞 ${r.us_open_pre_min}분` : "",
      r.us_open_pause_min ? `뒤 ${r.us_open_pause_min}분` : ""].filter(Boolean).join("·")}은 진입하지 않음 (${gates ? "열린 포지션 청산은 계속" : "추세 판단·청산은 계속"})`] : null,
    ["기본 손절", r.stop ? r.stop.ko : "—"],
    ["빠른 청산", r.early_exit ? (r.early_exit === "own" ? "같은 매매법의 반대 신호에 바로 청산" : "아무 매매법의 반대 신호에 바로 청산")
      : hold ? "없음 (손절 · 계단 잠금 · 보유 한도만)" : "없음 (손절과 계단 잠금만)"],
  ];
  if (!gates) return out;
  return [...out,
    entryGates.length ? ["진입 조건", h("ul", {class: "lb-limits"}, entryGates.map((g) => h("li", null, g.ko)))] : null,
    hold ? ["보유 한도", hold.ko] : null].filter(Boolean);
}

/** One rule line of the bot ("추세 판단: A / B / C") as {head, parts}: the words before the first ": " and the rest split
 *  at " / " (the bot's own separator); a line without ": " is all parts. */
export function ruleParts(line) {
  const t = String(line || "");
  const i = t.indexOf(": ");
  const head = i > 0 ? t.slice(0, i) : "";
  const rest = i > 0 ? t.slice(i + 2) : t;
  return {head, parts: rest.split(" / ").map((x) => x.trim()).filter(Boolean)};
}

/** 고정 규칙's subtitle: the bot by its name (tr: the server's trend, the 추세판단 봇's), else the combined bot as before. */
export const rulesSub = (tr) => `${tr ? tr.name || "추세판단 봇" : "합친 봇"}의 모든 설정이 같이 쓰는 규칙`;

/** The trend bot's members grouped by role, in the owners' order: [{id, sub, members: [{strategy, tf, tf_ko, htf_ko, side_only}]}]. */
export function roleGroups(tr) {
  const ms = (tr && tr.members) || [];
  const roles = (tr && tr.roles) || [];
  const out = roles.map((r) => ({id: r.id, sub: r.sub_ko || "", members: ms.filter((m) => m.role === r.id)})).filter((g) => g.members.length);
  const rest = ms.filter((m) => !roles.some((r) => r.id === m.role));
  if (rest.length) out.push({id: "그 밖", sub: "역할이 정해지지 않은 매매법", members: rest});
  return out;
}

/** A setting's entry in words: the combined bot's (즉시 · 돌파 확인); the trend bot's (tr: the server's trend) by its config:
 *  바로 진입 (trend.pullback_wait false, the owners' since 10/22) or 되돌림 진입. */
export const entryKo = (m, tr) => (tr ? (tr.pullback_wait === false ? "바로 진입" : "되돌림 진입") : m.entry_ko);

/** settingsView(ctx) -> {el, set()} */
export function settingsView(ctx) {
  const st = {d: null, okAt: 0, q: ""};
  const stateSlot = h("div", {class: "lb-slot"});
  const rules = h("div", {class: "lb-rules"});
  const trendBox = h("div", {class: "lb-trendrules stack"});
  const trendCard = ui.card({title: "추세 판단 규칙", sub: "추세판단 봇이 지금 쓰는 규칙 · 봇이 남긴 글 그대로", cls: "lb-trendcard"}, trendBox);
  const trendSlot = h("div", {class: "lb-slot stack"});   // the trend bot only (draw)
  const lights = h("div", {class: "lb-lgrid"});
  const head = h("p", {class: "lb-ghead"});
  const list = ui.searchList({size: 10, placeholder: "매매법 찾기", row: (g) => groupRow(g), match: (g, q) => `${g.strategy} ${fmt.stratKo(g.strategy)}`.toLowerCase().includes(q)});
  const ruleCard = ui.card({title: "고정 규칙", sub: rulesSub(null), cls: "lb-rulecard"}, rules);
  const botsSlot = h("div", {class: "lb-slot stack"});   // a second paper bot's card (draw)
  const el = h("div", {class: "lb-settings stack"}, stateSlot, trendSlot,
    ruleCard, botsSlot,
    ui.card({title: "실행기 신호등과 한도", sub: "실행기 설정 파일 그대로 (적힌 것만)", cls: "lb-execcard"}, lights),
    ui.card({title: "매매법과 설정", sub: "매매법마다 접어 두었어요 · 10개씩", cls: "lb-grpcard"}, head, list.el));
  function memberRow(m, tr = st.d && st.d.trend) {
    return h("div", {class: "lb-mem", role: "listitem"},
      h("div", {class: "lb-memh"}, h("b", null, `${m.order}번`), h("span", {class: "pp thin"}, m.tf_ko), m.role ? ui.pill(`역할 ${m.role}`, "thin", "추세판단 봇에서 이 매매법의 역할") : null,
        h("span", null, entryKo(m, tr)), m.invert ? ui.pill("반대 방향", "warn") : null,
        m.no_chase ? ui.pill("추격 진입 막기", "thin", m.no_chase_ko || "") : null, h("span", {class: "muted"}, `손절 ${m.stop.ko}`)),
      m.numbers ? h("div", {class: "lb-nums"}, Object.entries(m.numbers).map(([k, v]) => h("span", {class: "pp thin num"}, `${k} ${Array.isArray(v) ? v.join("/") : v}`)))
        : h("p", {class: "note"}, "기본 숫자 (규칙봇과 같은 신호)"),
      m.filter.length ? h("p", {class: "note"}, `조건: ${m.filter.map((f) => f.ko).join(" · ")}`) : null,
      m.disp ? h("p", {class: "note"}, `신호봉: ${m.disp}`) : null,
      m.off.length ? ui.disclosure(`끄는 구간 ${fmt.int(m.off.length)}개`, h("p", {class: "note"}, m.off.map((o) => o.ko).join(" · "))) : null);
  }
  function groupRow(g, tr) {
    return h("div", {class: "lb-grp", role: "listitem"},
      ui.disclosure(`${fmt.stratKo(g.strategy)} · 설정 ${fmt.int(g.n)}개 · ${g.tfs.map((t) => fmt.tfKo(t)).join("/")}`,
        h("div", {class: "lb-mems"}, g.members.map((m) => memberRow(m, tr === undefined ? st.d && st.d.trend : tr)))),
      h("span", {class: "muted lb-gcode"}, g.strategy));
  }
  /** A second paper bot's card (owners 10/23): its rules, gates and hold limit, its settings (never the trend bot's roles). */
  function botCard(b) {
    const who = (b.followers || []).length ? `${josa(b.followers.join(" · "), "이", "가")} 따라가요` : "따라가는 실행기 없음";
    const c = b.combo || {};
    return ui.card({title: `${b.short_ko || "두 번째 페이퍼 봇"} 규칙`, sub: `두 번째 페이퍼(연습) 봇 · ${who}`, cls: "lb-rulecard lb-botcard"},
      c.state !== "ok" ? sourceState(c, `${b.short_ko || "두 번째"} 봇 설정`) : [
        h("div", {class: "lb-rules"}, ui.kv(rulesList(b.rules || {}))),
        ui.note(c.source === "db" ? `봇이 지금 쓰는 설정 (봇 DB의 시작 기록, ${fmt.kst(c.since_ms)})` : `설정 파일 ${c.path || "—"} (봇이 아직 시작 기록을 남기기 전)`),
        h("p", {class: "lb-ghead"}, `매매법 ${fmt.int(b.n_strategies || 0)}개 · 설정 ${fmt.int(b.n_settings || 0)}개`),
        h("div", {class: "lb-mems", role: "list"}, (b.groups || []).map((g) => groupRow(g, null))),
        ui.note("자세한 것은 docs/vwap-bot-ko.md 2장 (설정 파일 deploy/combo.vwap.json 그대로)")]);
  }
  function drawTrend(tr) {
    if (!tr) { put(trendSlot); return; }
    if (trendCard.parentNode !== trendSlot) put(trendSlot, trendCard);
    const pills = [tr.no_pause_ko ? ui.pill(tr.no_pause_ko, "good", "손실 뒤 매매법 쉬기 · 코인 쉬기 · 하루 손실 한도를 모두 뺐어요 (10/21 두 분 결정)") : null,
      tr.since != null ? ui.pill(`규칙 고정 ${fmt.kst(tr.since)} ~ ${fmt.kst(tr.freeze_until)}`, "thin", `시작부터 ${fmt.int(tr.freeze_days || 14)}일은 규칙을 바꾸지 않고 그 뒤 검토해요`) : null,
      ui.pill("백테스트 기준 없음", "thin", "새 규칙이라 비교할 백테스트 기준이 없어요 · 2주 뒤 검토")];
    const lines = (tr.rules || []).map(ruleParts);
    const groups = roleGroups(tr);
    put(trendBox,
      h("div", {class: "lb-nums"}, ...pills),
      lines.length ? h("div", {class: "lb-rules"}, ui.kv(lines.map((x) => [x.head || "규칙", h("ul", {class: "lb-limits"}, x.parts.map((p) => h("li", null, p)))])))
        : ui.note(tr.rules_ko || "봇이 아직 규칙을 기록하지 않았어요"),
      groups.length ? h("div", {class: "lb-lgrid"}, groups.map((g) => h("div", {class: "lb-light"},
        h("b", null, `${g.id} · ${fmt.int(g.members.length)}개`), h("p", {class: "note"}, g.sub),
        h("ul", {class: "lb-limits"}, g.members.map((m) => h("li", {title: m.htf_ko || ""}, h("b", null, fmt.stratKo(m.strategy)),
          ` · ${m.tf_ko || fmt.tfKo(m.tf)}`, m.side_only ? ` · ${m.side_only === "short" ? "숏만" : "롱만"}` : "",
          m.htf_ko ? h("span", {class: "muted"}, ` (${m.htf_ko})`) : null)))))) : null,
      ui.note(`진입 매매법은 신호만 내고, 들어갈지는 ${tr.pullback_wait === false ? "추세 판단 · 진입 전 검사가 정해요 (통과하면 그 분에 바로 진입)"
        : "추세 판단 · 진입 전 검사 · 되돌림이 정해요"}. 더 자세한 것은 관제 탭의 '규칙'과 docs/trend-bot-ko.md`));
  }
  function draw() {
    const d = st.d;
    if (!d) { put(rules, motion.shimmer(3)); return; }
    drawTrend(d.trend);
    put(botsSlot, (d.bots || []).map(botCard));
    const sub = ruleCard.firstChild && Array.from(ruleCard.firstChild.childNodes).find((n) => String(n.className || "") === "sub");
    if (sub && sub.textContent !== rulesSub(d.trend)) sub.textContent = rulesSub(d.trend);
    if (!d.combo || d.combo.state !== "ok") { put(rules, sourceState(d.combo, "합친 봇 설정")); list.set([]); }
    else {
      put(rules, ui.kv(rulesList(d.rules)), ui.note(d.combo.source === "db" ? `봇이 지금 쓰는 설정 (봇 DB의 시작 기록, ${fmt.kst(d.combo.since_ms)})` : `설정 파일 ${d.combo.path} (봇이 아직 시작 기록을 남기기 전)`));
      put(head, `매매법 ${fmt.int(d.n_strategies)}개 · 설정 ${fmt.int(d.n_settings)}개`, d.rules && d.rules.name ? h("span", {class: "muted"}, ` · ${d.rules.name}`) : null);
      list.set(d.groups || []);
    }
    put(lights, (d.execs || []).map((x) => {
      const c = x.config || {};
      if (c.state !== "ok") return h("div", {class: "lb-light"}, h("b", null, x.name_ko), sourceState(c, "실행기 설정"));
      return h("div", {class: "lb-light"}, h("b", null, x.name_ko),
        x.follows_ko ? h("p", {class: "note"}, `따라가는 페이퍼 봇: ${x.follows_ko}`) : null,
        h("p", {class: "lb-lline"}, c.signal_light_n ? `신호등: 페이퍼 최근 ${fmt.int(c.signal_light_n)}번 중 ${pctOf(c.signal_light_min_win)} 이상 이겼을 때만 새 진입을 따라감` : "신호등 꺼짐: 모든 진입을 따라감"),
        h("p", {class: "note"}, `크기 비율 ×${c.qty_scale == null ? "—" : fmt.num(c.qty_scale, 2)} (페이퍼 수량 × 이 비율)`),
        c.limits && c.limits.length ? h("ul", {class: "lb-limits"}, c.limits.map((l) => h("li", {title: l.what_ko}, h("b", null, l.ko)))) : ui.note("적힌 위험 한도 없음"));
    }));
  }
  loader(ctx, "/api/v4/livebots/settings", st, stateSlot, draw, 5 * 60 * 1000);
  return {el, set() {}};
}
