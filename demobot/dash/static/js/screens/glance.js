// #/glance 한눈 지도 (CONTRACT 9.8; round 5 stage 2: the rule bot's v4 한눈 지도 look, grid.js / grid-kit.css): every
// account (rows, grouped by kind, each with its pixel figure and timeframe chip) × the four leverage lines (20 · 30 · 40 ·
// 50배) as heat cells in nine steps. Colour by: P&L % (accounts.json lines; the account's own money: up / down),
// "우리 기준" checks passed 0-5 (judge.json rows), the confirmation status (judge rows' confirm) or the stop-rule line's
// P&L % (lines.stops). A cell opens the account. PC: the summary, the legend and the notes beside the map (sticky); a
// phone: one column, the name column narrows. A ruined line has a dashed edge and says 파산 (colour is never the only
// sign: every cell also carries its number or word). accounts.json + judge.json every 60 s. Read-only; a missing file
// shows "준비 중".
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {LEVS, CONFIRM_KO} from "../labels.js";
import {byKind} from "../g4.js";

const MODES = [
  {id: "pnl", label: "손익 %", title: "시작 $1,000 대비 손익"},
  {id: "checks", label: "기준 통과 수", title: "우리 기준 5개 중 몇 개를 넘었나 (판정)"},
  {id: "confirm", label: "확인 기간", title: "통과 뒤 4주 확인 기간의 상태"},
  {id: "stops", label: "정지 규칙 손익", title: "정지 규칙(계좌 −20% · 하루 −5% · 5연패)을 걸었다면의 손익 %"},
];
const CONF_SHORT = {confirming: "확인 중", confirmed: "후보", failed: "실패"};
/** The colour step −4..4 of a signed value against the scale's end (0 for a value that shows as zero). */
const stepOf = (v, max) => {
  if (v == null || !Number.isFinite(Number(v)) || !(max > 0)) return null;
  const x = Number(v);
  if (Math.abs(x) < 0.05) return 0;
  return Math.sign(x) * Math.max(1, Math.min(4, Math.ceil(Math.abs(x) / max * 4)));
};

export async function mount(el, ctx) {
  ctx.setTitle("한눈 지도");
  let mode = MODES.some((m) => m.id === ctx.params.query.color) ? ctx.params.query.color : local.get("glance-mode", "pnl");
  if (!MODES.some((m) => m.id === mode)) mode = "pnl";
  const sum = h("div");
  const grid = h("div", {class: "s2a-gwrap"});
  const legend = h("div");
  const modeSeg = ui.seg(MODES.map((m) => ({id: m.id, label: m.label, title: m.title})), mode,
    (v) => { mode = v; local.set("glance-mode", v); ctx.setQuery(v === "pnl" ? {} : {color: v}); paint(); K4.swap(grid); }, {label: "색", cls: "scroll"});
  const count = h("span", {class: "s2a-count"});
  el.append(ui.screenHead("한눈 지도", "모든 계좌 × 배수 4줄을 한 장에"),
    h("div", {class: "s2a-bar"}, h("span", {class: "s2a-barg"}, h("span", {class: "k4-k"}, "색 기준"), modeSeg)),
    h("div", {class: "s2a-gcols"},
      ui.card({plate: "지도", sub: "칸을 누르면 그 계좌로 갑니다", cls: "s2a-gcard", acts: [count]}, grid),
      h("div", {class: "s2a-gside"},
        ui.card({plate: "요약", cls: "s2a-gsum"}, sum),
        ui.card({plate: "읽는 법"}, legend,
          h("p", {class: "note"}, "한 줄 = 계좌 하나, 칸 하나 = 그 계좌의 배수 한 줄 ($1,000에서 시작). 점선 테두리 칸은 잔고가 $100 아래로 떨어진 적이 있는(파산) 줄입니다. "
            + "색은 늘 숫자나 글자와 함께 나옵니다.")))));

  let accts = null, judge = null, seen = null;
  async function load() {
    let a, j;
    try { [a, j] = await Promise.all([ctx.api("/api/accounts"), ctx.api("/api/judge").catch(() => null)]); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!accts) put(grid, ui.errorBox(e, load));
      return;
    }
    const key = `${a && a.generated_ms}|${j && j.generated_ms}`;
    if (key === seen) return;
    seen = key;
    accts = a;
    judge = j && !isMissing(j) ? j : null;
    paint();
  }

  function cellOf(a, L, rows, vmax) {
    const x = (a.lines || {})[String(L)];
    const r = rows.get(`${a.id}|${L}`);
    if (mode === "pnl" || mode === "stops") {
      const v = mode === "pnl" ? (x ? x.pnl_pct : null) : x && x.stops ? x.stops.pnl_pct : null;
      if (v == null) return {cls: "none", text: "—", v: null, b: null};
      return {cls: "own", text: fmt.pct(v, true, Math.abs(v) >= 100 ? 0 : 1), v: Number(v), b: stepOf(v, vmax)};
    }
    if (mode === "checks") {
      if (!r) return {cls: "none", text: "—", v: null, b: null};
      const ok = ((r.ours && r.ours.checks) || []).filter((c) => c.ok).length, of = ((r.ours && r.ours.checks) || []).length || 5;
      return {cls: ok >= of ? "pass" : "seq", text: `${ok}/${of}`, v: ok / of, b: ok >= of ? null : Math.min(4, ok)};
    }
    const st = r && r.confirm ? r.confirm.status : null;
    return {cls: st ? `cf-${st}` : "none", text: st ? CONF_SHORT[st] || st : "—", v: null, b: null};
  }

  function paint() {
    if (!accts || isMissing(accts)) { put(sum); put(legend); put(grid, ui.missing("계좌 목록")); count.textContent = ""; return; }
    const list = accts.accounts || [];
    const rows = new Map(((judge && judge.rows) || []).map((r) => [`${r.id}|${r.L}`, r]));
    let vmax = 0;
    if (mode === "pnl" || mode === "stops") {
      for (const a of list) for (const L of LEVS) {
        const x = (a.lines || {})[String(L)];
        const v = mode === "pnl" ? (x ? x.pnl_pct : null) : x && x.stops ? x.stops.pnl_pct : null;
        if (v != null && Number.isFinite(Number(v))) vmax = Math.max(vmax, Math.abs(Number(v)));
      }
      vmax = Math.min(Math.max(vmax, 5), 100);                     // ±100% and beyond share the strongest colour
    }
    // the summary over every line for the chosen colour
    const cells = list.flatMap((a) => LEVS.map((L) => cellOf(a, L, rows, vmax)));
    const num = cells.filter((c) => c.v != null);
    count.textContent = `계좌 ${fmt.int(list.length)}개 × 4줄`;
    if (mode === "pnl" || mode === "stops") {
      put(sum, h("div", {class: "stats"},
        K4.stat("줄", fmt.int(cells.length), `계좌 ${fmt.int(list.length)}개 × 4`),
        K4.stat("이익 중", fmt.int(num.filter((c) => c.v > 0).length), null, "dl-good"),
        K4.stat("손실 중", fmt.int(num.filter((c) => c.v < 0).length), null, "dl-bad"),
        K4.stat("가운데 값", num.length ? fmt.pct(K4.median(num.map((c) => c.v)), true) : "—", "줄의 중앙값")),
      winLoss(num.filter((c) => c.v > 0).length, num.filter((c) => c.v < 0).length));
    } else if (mode === "checks") {
      const by = [0, 1, 2, 3, 4, 5].map((k) => num.filter((c) => Math.round(c.v * 5) === k).length);
      put(sum, h("div", {class: "stats"}, K4.stat("5개 모두", fmt.int(by[5]), "우리 기준 통과", by[5] ? "dl-good" : null),
        K4.stat("4개", fmt.int(by[4]), "하나만 더"), K4.stat("3개", fmt.int(by[3])), K4.stat("2개 이하", fmt.int(by[0] + by[1] + by[2]))));
    } else {
      const n = (s) => cells.filter((c) => c.cls === `cf-${s}`).length;
      put(sum, h("div", {class: "stats"}, K4.stat("실전 후보", fmt.int(n("confirmed")), null, n("confirmed") ? "dl-good" : null),
        K4.stat("확인 중", fmt.int(n("confirming"))), K4.stat("확인 실패", fmt.int(n("failed")), null, n("failed") ? "dl-bad" : null),
        K4.stat("아직 없음", fmt.int(cells.filter((c) => c.cls === "none").length))));
    }
    put(legend, legendOf(mode, vmax));
    const label = MODES.find((m) => m.id === mode).label;
    const head = h("div", {class: "s2a-grow s2a-ghead", role: "row"}, h("span", {class: "s2a-gn", role: "columnheader"}, "계좌"),
      LEVS.map((L) => h("span", {class: "s2a-gth", role: "columnheader"}, h("span", {class: "dl-levtag", dataset: {lev: L}}, `${L}배`))));
    const body = byKind(list).flatMap((k) => {
      const kv = (mode === "pnl" || mode === "stops") ? K4.median(k.rows.flatMap((a) => LEVS.map((L) => cellOf(a, L, rows, vmax).v)).filter((v) => v != null)) : null;
      return [
        h("div", {class: "s2a-gsec", role: "row", dataset: {kind: k.id}}, h("span", {role: "rowheader", class: "s2a-gsecn"}, h("i", {class: "k4-sw", "aria-hidden": "true"}),
          h("b", null, k.ko), h("span", {class: "muted"}, ` ${k.rows.length}개`)),
        kv != null ? h("span", {class: ["s2a-gsecm", "num", fmt.tone(kv, fmt.pct(kv, true))]}, `가운데 ${fmt.pct(kv, true)}`) : null),
        ...k.rows.map((a) => h("div", {class: "s2a-grow", role: "row"},
          h("a", {class: "s2a-gn", role: "rowheader", href: ctx.href("account", a.id), title: `${a.name || a.id}${a.rule_ko ? `\n${a.rule_ko}` : ""}`},
            K4.acctFig(a, 18), K4.acctName(a)),
          LEVS.map((L) => {
            const c = cellOf(a, L, rows, vmax);
            const x = (a.lines || {})[String(L)];
            const title = `${a.name || a.id} ${L}배 · ${label}: ${c.text}`
              + (x ? ` · 손익 ${fmt.pct(x.pnl_pct, true)} · 거래 ${fmt.int(x.trades)}` : "") + (x && x.ruins ? ` · 파산 ${x.ruins}번` : "");
            return h("a", {class: ["s2a-gc", c.cls, x && x.ruined ? "ruined" : ""], role: "cell", href: ctx.href("account", a.id), title, "aria-label": title,
              dataset: c.b != null ? {b: String(c.b)} : null}, h("b", null, c.text), x && x.ruined ? h("small", null, "파산") : c.cls === "pass" ? h("small", null, "통과") : null);
          })))];
    });
    put(grid, h("div", {class: ["s2a-gmap", mode], role: "table", "aria-label": "계좌 × 배수 지도"}, head, body));
  }

  await load();
  ctx.every(60000, load);
}

/** The win / loss bar under the summary (v4 wl-bar: the lines in profit against those in loss). */
function winLoss(up, down) {
  const tot = up + down;
  return h("div", {class: "s2a-wl"}, h("div", {class: "wl-bar", role: "img", "aria-label": `이익 ${up}줄 · 손실 ${down}줄`},
    h("i", {style: {"--w": `${tot ? (up / tot * 100).toFixed(1) : 0}%`}})),
  h("span", {class: "muted s2a-small"}, `이익 ${fmt.int(up)} · 손실 ${fmt.int(down)}`));
}

function legendOf(mode, vmax) {
  const ruin = h("span", {class: "s2a-lgi"}, h("i", {class: "s2a-gc ruined s2a-sw", "aria-hidden": "true"}), "파산한 적 있는 줄 (점선)");
  if (mode === "pnl" || mode === "stops") {
    return h("div", {class: "s2a-legend"},
      h("div", {class: "s2a-scale", "aria-hidden": "true"}, [-4, -3, -2, -1, 0, 1, 2, 3, 4].map((b) => h("i", {class: "s2a-gc own s2a-sw", dataset: {b: String(b)}}))),
      h("div", {class: "s2a-scalek"}, h("span", {class: "num"}, fmt.pct(-vmax, true, 0)), h("span", {class: "muted"}, "0"), h("span", {class: "num"}, fmt.pct(vmax, true, 0))),
      h("p", {class: "note"}, "초록 = 이익, 빨강 = 손실, 진할수록 큼 (9단계 · 끝 칸은 ±", fmt.pct(vmax, false, 0), " 이상)"), ruin);
  }
  if (mode === "checks") {
    return h("div", {class: "s2a-legend"}, h("div", {class: "s2a-lgrow"}, [0, 1, 2, 3, 4].map((k) => h("span", {class: "s2a-lgi"},
      h("i", {class: "s2a-gc seq s2a-sw", dataset: {b: String(k)}, "aria-hidden": "true"}), `${k}/5`)),
    h("span", {class: "s2a-lgi"}, h("i", {class: "s2a-gc pass s2a-sw", "aria-hidden": "true"}), "5/5 = 우리 기준 통과")), ruin);
  }
  return h("div", {class: "s2a-legend"}, h("div", {class: "s2a-lgrow"}, ["confirming", "confirmed", "failed"].map((s) => h("span", {class: "s2a-lgi"},
    h("i", {class: ["s2a-gc", "s2a-sw", `cf-${s}`], "aria-hidden": "true"}), CONFIRM_KO[s])),
  h("span", {class: "s2a-lgi"}, h("i", {class: "s2a-gc none s2a-sw", "aria-hidden": "true"}), "확인 기간 없음")), ruin);
}
