// 실거래 › 그림자 and 설정 (#/livebots/shadows, #/livebots/settings).
//   그림자  the shadow paper bots (other settings of the same combined bot: B 안정형, 끄는 구간 없음, 32개; their own databases,
//           the same shape) next to the live paper bot, each counted from the same start (/api/v4/livebots/shadows): trades,
//           win rate, P&L and both lines; 참고 and small samples say so. None there yet: 수집 전 and the one command that starts
//           them (the page itself starts nothing).
//   설정    the combined bot's fixed rules (BTC 40x / alts 30x, margin, one position, the ladder, no KST weekend entries,
//           none ±30 min around US macro releases, the loss cap per stop), each executor's light and limits, and every
//           setting grouped by strategy (timeframe, custom numbers, stop, entry mode, conditions, switched-off buckets),
//           from the config the bot really runs (/api/v4/livebots/settings); folded, 10 strategies a page.
//           추세판단 봇 (the server's ``trend``, owners 10/21): first a card 추세 판단 규칙: 쉬기 없음 · 하루 손실 한도 없음,
//           the 2-week rule freeze from its start, its rules exactly as the bot wrote them (state trend rules: TrendRules.
//           describe, each line split at its " / "), and its members by role (눌림 · 자리 · 돌파 · 횡보) with their entry
//           bar (30분 진입 = the closed 1h bar's trend, 1시간 진입 = the 4h bar's); every setting row carries its role.
import {h, s, put, ui, fmt, motion} from "../core/pb.js";
import {sourceState} from "./livebots-kit.js";
import {smallFloor} from "./livebots-calc.js";

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

/** Two cumulative P&L lines on one scale (real width W): the shadow (accent) and the live paper (muted). */
export function twoLines(a, b, W = 600) {
  const H = 120, pad = 6;
  const pts = [...(a || []), ...(b || [])];
  if (pts.length < 2) return null;
  const t0 = Math.min(...pts.map((p) => p[0])), t1 = Math.max(...pts.map((p) => p[0]));
  let lo = Math.min(0, ...pts.map((p) => p[1])), hi = Math.max(0, ...pts.map((p) => p[1]));
  if (hi === lo) hi = lo + 1;
  const X = (t) => pad + (t1 > t0 ? (t - t0) / (t1 - t0) : 1) * (W - 2 * pad), Y = (v) => pad + (1 - (v - lo) / (hi - lo)) * (H - 2 * pad);
  const path = (xs) => (xs || []).map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
  return s("svg", {class: "lb-two", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": "그림자와 실거래 페이퍼의 누적 손익"},
    s("line", {class: "zero", x1: 0, x2: W, y1: Y(0), y2: Y(0)}),
    b && b.length > 1 ? s("path", {class: "main", d: path(b)}) : null, a && a.length > 1 ? s("path", {class: "shadow", d: path(a)}) : null);
}

/** shadowsView(ctx) -> {el, set()} */
export function shadowsView(ctx) {
  const st = {d: null, okAt: 0};
  const stateSlot = h("div", {class: "lb-slot"});
  const body = h("div", {class: "lb-shadows"});
  const el = h("div", {class: "lb-shadowv stack"}, stateSlot, body,
    h("div", {class: "lb-foot"}, ui.assumeLine(["closed"], "그림자도 모의 · 참고")));
  const statLine = (x) => (x ? `${fmt.int(x.trades)}번 · 승률 ${x.win_rate == null ? "—" : fmt.pct(x.win_rate, 1, false)} · ${fmt.money(x.pnl, true)} USDT` : "—");
  function draw() {
    const d = st.d;
    if (!d) { put(body, motion.shimmer(3)); return; }
    const W = Math.max(260, Math.round((body.clientWidth || 600) - 40));
    const any = (d.shadows || []).some((x) => x.state === "ok");
    put(body,
      !any ? ui.card({title: "그림자 봇", sub: "아직 켜지 않았거나 기록 전", cls: "lb-shnone"},
        h("p", {class: "lb-flat"}, ui.notYet("수집 전"), " 그림자 봇의 기록이 아직 없어요. 켜는 명령 (서버에서, 한 번):"),
        h("code", {class: "lb-cmd"}, d.start_ko), ui.note(`찾는 곳: ${d.dir}`)) : null,
      (d.shadows || []).map((x) => {
        if (x.state !== "ok") return ui.card({title: x.name_ko, cls: "lb-shcard"}, sourceState(x, x.name_ko));
        const fl = smallFloor(x.stats.trades);
        const diff = x.main && x.main.stats ? x.stats.pnl - x.main.stats.pnl : null;
        return ui.card({title: x.name_ko, sub: `${fmt.kst(x.since_ms)}부터 같은 기간 · 모의`, cls: "lb-shcard", acts: [ui.pill("", "ref")]},
          h("div", {class: "lb-recs"},
            h("div", {class: "lb-rec"}, h("b", {class: "lb-shk"}, "그림자"), h("span", null, statLine(x.stats)), fl ? ui.smallSample(x.stats.trades, fl) : null),
            h("div", {class: "lb-rec"}, h("b", {class: "lb-mk"}, "실거래 페이퍼"), h("span", null, x.main ? statLine(x.main.stats) : "—"))),
          twoLines(x.curve, x.main && x.main.curve, W) || h("p", {class: "lb-flat"}, "닫힌 거래가 두 번 넘게 쌓이면 선이 그려져요"),
          diff != null ? ui.note(`같은 기간 손익 차이 (그림자 − 실거래 페이퍼): ${fmt.money(diff, true)} USDT · 거래가 적을 때는 우연일 수 있어요`) : null,
          x.stale ? ui.pill(`기록 멈춤 · ${fmt.ago(x.as_of_ms)}`, "warn") : null);
      }));
  }
  loader(ctx, "/api/v4/livebots/shadows", st, stateSlot, draw);
  return {el, set() {}};
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

/** The fixed rules in the owners' words, from the config's own numbers. */
export function rulesList(r) {
  return [
    ["배수", `BTC ${r.leverage_btc ?? "—"}배 · 나머지 ${r.leverage_alt ?? "—"}배 (고정)`],
    ["증거금", typeof r.margin === "number" ? `잔고의 ${pctOf(r.margin)}` : r.margin === "leverage" ? "배수와 같은 %" : "—"],
    ["포지션", "한 번에 하나"],
    ["계단 잠금", ladderKo(r.ladder)],
    ["손절 한 번", r.max_loss_frac != null ? `잔고의 최대 ${pctOf(r.max_loss_frac)} (넘으면 크기를 줄임)` : "—"],
    ["주말", r.no_weekend ? "한국 시간 토·일에는 새로 진입하지 않음 (열린 포지션은 그대로)" : "주말에도 진입"],
    ["경제 발표", r.macro_blackout_min ? `미국 경제 발표 앞뒤 ${r.macro_blackout_min}분은 진입하지 않음` : "제한 없음"],
    r.us_open_pause_min ? ["나스닥 개장", `미국 주식시장 개장 뒤 ${r.us_open_pause_min}분은 진입하지 않음`] : null,
    ["기본 손절", r.stop ? r.stop.ko : "—"],
    ["빠른 청산", r.early_exit ? (r.early_exit === "own" ? "같은 매매법의 반대 신호에 바로 청산" : "아무 매매법의 반대 신호에 바로 청산") : "없음 (손절과 계단 잠금만)"],
  ];
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

/** The trend bot's members grouped by role, in the owners' order: [{id, sub, members: [{strategy, tf, tf_ko, htf_ko, side_only}]}]. */
export function roleGroups(tr) {
  const ms = (tr && tr.members) || [];
  const roles = (tr && tr.roles) || [];
  const out = roles.map((r) => ({id: r.id, sub: r.sub_ko || "", members: ms.filter((m) => m.role === r.id)})).filter((g) => g.members.length);
  const rest = ms.filter((m) => !roles.some((r) => r.id === m.role));
  if (rest.length) out.push({id: "그 밖", sub: "역할이 정해지지 않은 매매법", members: rest});
  return out;
}

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
  const el = h("div", {class: "lb-settings stack"}, stateSlot, trendSlot,
    ui.card({title: "고정 규칙", sub: "합친 봇의 모든 설정이 같이 쓰는 규칙", cls: "lb-rulecard"}, rules),
    ui.card({title: "실행기 신호등과 한도", sub: "실행기 설정 파일 그대로 (적힌 것만)", cls: "lb-execcard"}, lights),
    ui.card({title: "매매법과 설정", sub: "매매법마다 접어 두었어요 · 10개씩", cls: "lb-grpcard"}, head, list.el));
  function memberRow(m) {
    return h("div", {class: "lb-mem", role: "listitem"},
      h("div", {class: "lb-memh"}, h("b", null, `${m.order}번`), h("span", {class: "pp thin"}, m.tf_ko), m.role ? ui.pill(`역할 ${m.role}`, "thin", "추세판단 봇에서 이 매매법의 역할") : null,
        h("span", null, m.entry_ko), m.invert ? ui.pill("반대 방향", "warn") : null,
        m.no_chase ? ui.pill("추격 진입 막기", "thin", m.no_chase_ko || "") : null, h("span", {class: "muted"}, `손절 ${m.stop.ko}`)),
      m.numbers ? h("div", {class: "lb-nums"}, Object.entries(m.numbers).map(([k, v]) => h("span", {class: "pp thin num"}, `${k} ${Array.isArray(v) ? v.join("/") : v}`)))
        : h("p", {class: "note"}, "기본 숫자 (규칙봇과 같은 신호)"),
      m.filter.length ? h("p", {class: "note"}, `조건: ${m.filter.map((f) => f.ko).join(" · ")}`) : null,
      m.disp ? h("p", {class: "note"}, `신호봉: ${m.disp}`) : null,
      m.off.length ? ui.disclosure(`끄는 구간 ${fmt.int(m.off.length)}개`, h("p", {class: "note"}, m.off.map((o) => o.ko).join(" · "))) : null);
  }
  function groupRow(g) {
    return h("div", {class: "lb-grp", role: "listitem"},
      ui.disclosure(`${fmt.stratKo(g.strategy)} · 설정 ${fmt.int(g.n)}개 · ${g.tfs.map((t) => fmt.tfKo(t)).join("/")}`, h("div", {class: "lb-mems"}, g.members.map(memberRow))),
      h("span", {class: "muted lb-gcode"}, g.strategy));
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
      ui.note("진입 매매법은 신호만 내고, 들어갈지는 추세 판단 · 진입 전 검사 · 되돌림이 정해요. 더 자세한 것은 관제 탭의 '규칙'과 docs/trend-bot-ko.md"));
  }
  function draw() {
    const d = st.d;
    if (!d) { put(rules, motion.shimmer(3)); return; }
    drawTrend(d.trend);
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
        h("p", {class: "lb-lline"}, c.signal_light_n ? `신호등: 페이퍼 최근 ${fmt.int(c.signal_light_n)}번 중 ${pctOf(c.signal_light_min_win)} 이상 이겼을 때만 새 진입을 따라감` : "신호등 꺼짐: 모든 진입을 따라감"),
        h("p", {class: "note"}, `크기 비율 ×${c.qty_scale == null ? "—" : fmt.num(c.qty_scale, 2)} (페이퍼 수량 × 이 비율)`),
        c.limits && c.limits.length ? h("ul", {class: "lb-limits"}, c.limits.map((l) => h("li", {title: l.what_ko}, h("b", null, l.ko)))) : ui.note("적힌 위험 한도 없음"));
    }));
  }
  loader(ctx, "/api/v4/livebots/settings", st, stateSlot, draw, 5 * 60 * 1000);
  return {el, set() {}};
}
