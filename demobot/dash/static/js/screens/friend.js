// #/friend 친구 계획 (CONTRACT 9.9): the friend's plan in one place, from existing files only: the plan's steps in plain
// Korean, the six friend-rule accounts (fr-*) side by side (P&L per leverage line, the friend rule's 7-day check from
// judge.json rows' "friend", this week's switches), one chosen account's current (setting × exit) per coin and leverage
// (acct/<id>.json settings_now) with this week's decisions, and the fixed accounts that run the friend's own values.
// Round 5 stage 2: no v4 counterpart, built from the kit in the same feel: the plan as numbered steps, one card per
// friend-rule account (pixel figure, timeframe chip, its 20x equity line, a row per leverage with the P&L and the friend
// check as a light; the card picks the account below), the combination table, this week's switches as calm rows (the
// rest behind 더 보기), the friend-value fixed accounts in the table style.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {LEVS, COINS, tfKo} from "../labels.js";

const levTag = (L) => (L ? h("span", {class: "dl-levtag", dataset: {lev: L}}, fmt.lev(L)) : null);
/** A check as a small light: the dot AND ✓ / ✗ / — (never colour alone). */
const light = (ok, text, title) => h("span", {class: ["s2a-lt", ok == null ? "na" : ok ? "ok" : "no"], title}, h("i", {"aria-hidden": "true"}),
  ok == null ? "—" : ok ? "✓" : "✗", text ? h("small", null, text) : null);
const SHOW = 8;

const HOUR = 3600000, DAY = 86400000;
/** This KST Monday 00:00 (ms). */
function weekStart(now = Date.now()) {
  const k = now + 9 * HOUR;
  const day = Math.floor(k / DAY);
  const wd = (day + 3) % 7;                 // Monday = 0 (1970-01-01 was a Thursday)
  return (day - wd) * DAY - 9 * HOUR;
}

export async function mount(el, ctx) {
  ctx.setTitle("친구 계획");
  let pick = ctx.params.query.id || local.get("friend-id", null);
  const overview = h("div");
  const pickBox = h("div");
  const plan = h("div");
  const fixedBox = h("div");
  const step = (i, ...kids) => h("li", null, h("span", {class: "s2a-n", "aria-hidden": "true"}, String(i).padStart(2, "0")), h("span", null, ...kids));
  el.append(ui.screenHead("친구 계획", "친구 방식이 이번 주에 무엇을 돌리나"),
    ui.card({plate: "계획 한눈에", hero: true, cls: "s2a-plan"}, h("ol", {class: "s2a-nlist"},
      step(1, h("b", null, "매주 월요일 09:00 (한국 시간)"), "에 지난 26주를 봅니다."),
      step(2, "코인마다, 배수마다 따로: (설정 × 청산) 조합 가운데 ", h("b", null, "그 배수로 돈을 번 것"), "만 남깁니다."),
      step(3, "그중 ", h("b", null, "최대 낙폭이 가장 작은 것"), " 하나를 고릅니다."),
      step(4, "그 조합으로 ", h("b", null, "일주일"), " 돌리고, 다음 월요일에 다시 고릅니다."),
      step(5, "친구 기준: 최근 7일(데모 일주일)에 수익이 나고, 그 7일 동안 강제청산·파산이 없어야 '통과'입니다.")),
    h("p", {class: "refnote"}, h("b", null, "참고"), " · 일주일 거래 수십 건으로는 운과 실력을 가리기 어렵습니다. 그래서 우리 기준(실시간 100건 이상, 운 기준선 위 …)과 따로 봅니다.")),
    h("section", {class: "k4-sec", "aria-label": "친구 규칙 계좌"}, K4.secRow("친구 규칙 계좌 6개", "배수마다 손익 · 친구 기준 7일 확인 · 이번 주 교체 · 카드를 누르면 아래에 그 계좌"), overview),
    pickBox, plan,
    ui.card({plate: "친구 값 그대로 돌리는 고정 계좌", sub: "친구가 쓰는 설정을 바꾸지 않고"}, fixedBox));

  let accts = null, judge = null, detail = null, seen = null;
  async function load() {
    let a, j;
    try { [a, j] = await Promise.all([ctx.api("/api/accounts"), ctx.api("/api/judge").catch(() => null)]); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!accts) put(overview, ui.errorBox(e, load));
      return;
    }
    const key = `${a && a.generated_ms}|${j && j.generated_ms}`;
    if (key !== seen) {
      seen = key;
      accts = a;
      judge = j && !isMissing(j) ? j : null;
      paintOverview();
    }
    await loadDetail();
  }
  const friends = () => (accts && !isMissing(accts) ? (accts.accounts || []).filter((x) => x.kind === "friend") : []);
  const rowsOf = (id) => ((judge && judge.rows) || []).filter((r) => r.id === id);

  function friendCell(r) {
    if (!r || !r.friend) return h("span", {class: "muted"}, "—");
    const f = r.friend;
    const text = f.pass === true ? "통과" : f.pass === false ? "못 넘음" : "거래 없음";
    return light(f.pass, text, (f.checks || []).map((c) => `${c.ok ? "✓" : "✗"} ${c.name_ko}: ${c.value_ko}`).join("\n"));
  }

  function paintOverview() {
    const list = friends();
    if (!accts || isMissing(accts)) { put(overview, ui.missing("계좌 목록")); return; }
    if (!list.length) { put(overview, ui.none("친구 규칙 계좌가 없습니다")); return; }
    if (!list.some((x) => x.id === pick)) pick = list[0].id;
    const wk = weekStart();
    put(overview, h("div", {class: "s2a-fcards"}, list.map((a) => {
      const jr = new Map(rowsOf(a.id).map((r) => [r.L, r]));
      const on = a.id === pick;
      const x20 = (a.lines || {})["20"] || {};
      const card = h("div", {class: ["s2a-fc", on ? "on" : ""], role: "button", tabindex: "0", "aria-pressed": String(on), dataset: {kind: a.kind},
        title: `${a.name || a.id} · 누르면 아래에 지금 돌리는 조합`},
      h("div", {class: "s2a-fch"}, h("span", {class: "s2a-nm"}, K4.acctFig(a, 22), K4.acctName(a)), h("span", {class: "grow"}),
        h("a", {class: "s2a-go s2a-small", href: ctx.href("account", a.id)}, "계좌 →")),
      h("span", {class: "s2a-fspark"}, K4.miniSpark(x20.spark, {fluid: true, h: 26, base: 1000, label: "20배 줄 잔고 흐름 (시작부터 지금까지)"})),
      h("div", {class: "s2a-flevs"}, LEVS.map((L) => {
        const x = (a.lines || {})[String(L)];
        const t = x ? fmt.pct(x.pnl_pct, true) : "—";
        return h("div", {class: "s2a-flev"}, levTag(L), h("b", {class: ["num", x ? fmt.tone(x.pnl_pct, t) : ""]}, t), friendCell(jr.get(L)));
      })),
      h("div", {class: "s2a-ffoot"}, h("span", {class: "muted"}, "이번 주 교체 "),
        a.last_switch_ms && a.last_switch_ms >= wk ? [h("b", null, "교체함"), h("span", {class: "s2a-t"}, ` ${fmt.kst(a.last_switch_ms)}`)]
          : h("span", {class: "muted"}, a.last_switch_ms ? `마지막 ${fmt.mmdd(a.last_switch_ms)}` : "아직 없음")));
      card.addEventListener("click", (e) => { if (!e.target.closest("a")) choose(a.id); });
      card.addEventListener("keydown", (e) => { if ((e.key === "Enter" || e.key === " ") && e.target === card) { e.preventDefault(); choose(a.id); } });
      return card;
    })),
    h("p", {class: "note"}, "카드를 누르면 아래에 그 계좌가 지금 돌리는 조합이 나옵니다. 배수마다 ✓/✗ = 친구 기준 (최근 7일). 작은 선 = 20배 줄 잔고 (시작부터 지금까지)."));
    const fx = (accts.accounts || []).filter((x) => x.kind === "fixed" && x.sub === "friend");
    put(fixedBox, fx.length ? ui.table([
      {label: "계좌", l: true, get: (a) => h("span", {class: "dl-kn"}, h("a", {class: "s2a-nm", href: ctx.href("account", a.id), title: a.id}, K4.acctFig(a, 18), K4.acctName(a)),
        h("small", {class: "mono muted"}, a.setting_ko || ""))},
      ...LEVS.map((L) => ({label: `${L}배`, get: (a) => {
        const x = (a.lines || {})[String(L)];
        const r = rowsOf(a.id).find((y) => y.L === L);
        return h("span", {class: "dl-kn"}, x ? ui.signed(fmt.pct(x.pnl_pct, true), fmt.tone(x.pnl_pct, fmt.pct(x.pnl_pct)), "b") : "—", friendCell(r));
      }})),
    ], fx, {cls: "s2a-tbl"}) : ui.none("친구 값 고정 계좌가 없습니다"));
  }

  function choose(id) {
    pick = id;
    local.set("friend-id", id);
    ctx.setQuery({id});
    detail = null;
    paintOverview();
    loadDetail();
  }

  async function loadDetail() {
    if (!pick) { put(pickBox); put(plan); return; }
    try {
      const d = await ctx.api(`/api/account/${encodeURIComponent(pick)}`);
      if (!ctx.alive()) return;
      if (detail && d && detail.generated_ms === d.generated_ms && detail.id === d.id) return;
      detail = d;
    } catch (e) {
      if (e && e.name === "AbortError") return;
      put(plan, ui.errorBox(e, loadDetail));
      return;
    }
    paintDetail();
  }

  function paintDetail() {
    const a = friends().find((x) => x.id === pick);
    const seg = ui.seg(friends().map((x) => ({id: x.id, label: `${x.short} · ${tfKo(x.tf)}`})), pick, (v) => choose(v), {label: "친구 규칙 계좌", cls: "scroll"});
    put(pickBox);
    if (!detail || isMissing(detail)) { put(plan, ui.card({plate: "지금 돌리는 조합"}, h("div", {class: "s2a-bar"}, seg), ui.missing("계좌 파일"))); return; }
    const now = detail.settings_now || [];
    const cell = (coin, L) => now.find((r) => r.coin === coin && Number(r.L) === L) || now.find((r) => r.coin === coin && r.L == null)
      || now.find((r) => r.coin === "ALL" && (r.L == null || Number(r.L) === L));
    const wk = weekStart();
    const dec = (detail.decisions || []).filter((d) => Number(d.t_ms) >= wk);
    const shown = dec.slice(0, 40);
    const decRow = (d) => h("div", {class: "s2a-ev", role: "listitem"},
      h("div", {class: "s2a-evh"}, h("span", {class: "s2a-t num"}, fmt.kst(d.t_ms)),
        h("span", {class: "pp thin"}, d.coin && d.coin !== "ALL" ? fmt.coin(d.coin) : "전체"), levTag(d.L)),
      h("div", {class: "s2a-evb"}, h("span", {class: "mono muted"}, d.from_ko || "—"), h("span", {class: "s2a-arrow", "aria-hidden": "true"}, " → "), h("b", {class: "mono"}, d.to_ko || "—")),
      d.why_ko ? h("div", {class: "s2a-why"}, d.why_ko) : null);
    const fig = a || {id: pick, name: detail.name, kind: detail.kind, tf: detail.tf, short: detail.short};
    put(plan, ui.card({plate: "지금 돌리는 조합", sub: "코인 × 배수마다 (설정 · 청산)", cls: "s2a-combo"},
      h("div", {class: "s2a-bar"}, h("span", {class: "s2a-nm s2a-big"}, K4.acctFig(fig, 26), K4.acctName(fig)), h("span", {class: "grow"}), seg),
      h("div", {class: "tbl-wrap"}, h("table", {class: "tbl g4-combo s2a-tbl"},
        h("thead", null, h("tr", null, h("th", {class: "l dl-c2", scope: "col"}, "코인"), LEVS.map((L) => h("th", {class: "l", scope: "col"}, levTag(L))))),
        h("tbody", null, COINS.map((c) => h("tr", null, h("th", {class: "l dl-c2", scope: "row"}, fmt.coin(c)), LEVS.map((L) => {
          const r = cell(c, L);
          return h("td", {class: "l"}, r ? h("span", {class: "dl-kn"}, h("b", {class: "mono"}, r.setting_ko || "—"), h("small", {class: "muted"}, r.exit_ko || "")) : h("span", {class: "muted"}, "—"));
        })))))),
      h("p", {class: "k4-k"}, `이번 주 교체 (${fmt.mmdd(wk)} 월요일부터) ${fmt.int(dec.length)}개`),
      dec.length ? [h("div", {class: "s2a-rows", role: "list"}, shown.slice(0, SHOW).map(decRow)),
        shown.length > SHOW ? ui.disclosure(`${fmt.int(shown.length - SHOW)}개 더 보기`, h("div", {class: "s2a-rows", role: "list"}, shown.slice(SHOW).map(decRow))) : null]
        : ui.none("이번 주에는 아직 교체가 없습니다 (월요일 09:00에 고릅니다)"),
      dec.length > 40 ? h("p", {class: "note"}, `처음 40개만 보입니다. 나머지는 계좌 화면의 교체 기록에 있습니다.`) : null));
  }

  await load();
  ctx.every(60000, load);
}
