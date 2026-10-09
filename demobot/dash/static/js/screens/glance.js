// #/glance 한눈 지도 (CONTRACT 9.8): every account (rows, grouped by kind) × the four leverage lines (20 · 30 · 40 · 50배)
// in one coloured grid. Colour by: P&L % (accounts.json lines), "우리 기준" checks passed 0-5 (judge.json rows), the
// confirmation status (judge rows' confirm) or the stop-rule line's P&L % (lines.stops). A cell opens the account. The
// grid scrolls sideways inside its own box on a phone; a ruined line has a dashed edge (colour is never the only sign:
// every cell also carries its number or word). accounts.json + judge.json every 60 s.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {LEVS, CONFIRM_KO} from "../labels.js";
import {byKind, mixOf} from "../g4.js";

const MODES = [
  {id: "pnl", label: "손익 %", title: "시작 $1,000 대비 손익"},
  {id: "checks", label: "기준 통과 수", title: "우리 기준 5개 중 몇 개를 넘었나 (판정)"},
  {id: "confirm", label: "확인 기간", title: "통과 뒤 4주 확인 기간의 상태"},
  {id: "stops", label: "정지 규칙 손익", title: "정지 규칙(계좌 −20% · 하루 −5% · 5연패)을 걸었다면의 손익 %"},
];
const CONF_SHORT = {confirming: "확인 중", confirmed: "후보", failed: "실패"};

export async function mount(el, ctx) {
  ctx.setTitle("한눈 지도");
  let mode = MODES.some((m) => m.id === ctx.params.query.color) ? ctx.params.query.color : local.get("glance-mode", "pnl");
  if (!MODES.some((m) => m.id === mode)) mode = "pnl";
  const sum = h("div");
  const grid = h("div", {class: "g4-gwrap"});
  const legend = h("div");
  const modeSeg = ui.seg(MODES.map((m) => ({id: m.id, label: m.label, title: m.title})), mode,
    (v) => { mode = v; local.set("glance-mode", v); ctx.setQuery(v === "pnl" ? {} : {color: v}); paint(); }, {label: "색"});
  el.append(ui.screenHead("한눈 지도", "모든 계좌 × 배수 4줄을 한 장에"),
    ui.card({plate: "색", cls: "dl-controls"}, ui.field("색 기준", modeSeg)),
    sum,
    ui.card({plate: "지도", sub: "칸을 누르면 그 계좌로 갑니다"}, legend, grid),
    ui.note("한 줄 = 계좌 하나, 칸 하나 = 그 계좌의 배수 한 줄 ($1,000에서 시작). 점선 테두리 칸은 잔고가 $100 아래로 떨어진 적이 있는(파산) 줄입니다. "
      + "색은 늘 숫자나 글자와 함께 나옵니다."));

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

  function cellOf(a, L, rows) {
    const x = (a.lines || {})[String(L)];
    const r = rows.get(`${a.id}|${L}`);
    if (mode === "pnl" || mode === "stops") {
      const v = mode === "pnl" ? (x ? x.pnl_pct : null) : x && x.stops ? x.stops.pnl_pct : null;
      if (v == null) return {cls: "na", text: "—", v: null};
      return {cls: Number(v) >= 0 ? "pos" : "neg", text: fmt.pct(v, true, Math.abs(v) >= 100 ? 0 : 1), v: Number(v)};
    }
    if (mode === "checks") {
      if (!r) return {cls: "na", text: "—", v: null};
      const ok = ((r.ours && r.ours.checks) || []).filter((c) => c.ok).length, of = ((r.ours && r.ours.checks) || []).length || 5;
      return {cls: ok >= of ? "pass" : "seq", text: `${ok}/${of}`, v: ok / of};
    }
    const st = r && r.confirm ? r.confirm.status : null;
    return {cls: st ? `cf-${st}` : "na", text: st ? CONF_SHORT[st] || st : "—", v: null};
  }

  function paint() {
    if (!accts || isMissing(accts)) { put(sum); put(legend); put(grid, ui.missing("계좌 목록")); return; }
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
    const cells = list.flatMap((a) => LEVS.map((L) => cellOf(a, L, rows)));
    const num = cells.filter((c) => c.v != null);
    if (mode === "pnl" || mode === "stops") {
      put(sum, h("div", {class: "stats dl-s4"},
        ui.stat("줄", fmt.int(cells.length), `계좌 ${fmt.int(list.length)}개 × 4`),
        ui.stat("이익 중", fmt.int(num.filter((c) => c.v > 0).length), null, "dl-good"),
        ui.stat("손실 중", fmt.int(num.filter((c) => c.v < 0).length), null, "dl-bad"),
        ui.stat("가운데 값", num.length ? fmt.pct(median(num.map((c) => c.v)), true) : "—", "줄의 중앙값")));
    } else if (mode === "checks") {
      const by = [0, 1, 2, 3, 4, 5].map((k) => num.filter((c) => Math.round(c.v * 5) === k).length);
      put(sum, h("div", {class: "stats dl-s4"}, ui.stat("5개 모두", fmt.int(by[5]), "우리 기준 통과", by[5] ? "dl-good" : null),
        ui.stat("4개", fmt.int(by[4]), "하나만 더"), ui.stat("3개", fmt.int(by[3])), ui.stat("2개 이하", fmt.int(by[0] + by[1] + by[2]))));
    } else {
      const n = (s) => cells.filter((c) => c.cls === `cf-${s}`).length;
      put(sum, h("div", {class: "stats dl-s4"}, ui.stat("실전 후보", fmt.int(n("confirmed")), null, n("confirmed") ? "dl-good" : null),
        ui.stat("확인 중", fmt.int(n("confirming"))), ui.stat("확인 실패", fmt.int(n("failed")), null, n("failed") ? "dl-bad" : null),
        ui.stat("아직 없음", fmt.int(cells.filter((c) => c.cls === "na").length))));
    }
    put(legend, legendOf(mode, vmax));
    const head = h("div", {class: "g4-grow g4-ghead", role: "row"}, h("span", {class: "g4-gn", role: "columnheader"}, "계좌"),
      LEVS.map((L) => h("span", {class: "g4-gl", role: "columnheader"}, h("span", {class: "dl-levtag", dataset: {lev: L}}, `${L}배`))));
    const body = byKind(list).flatMap((k) => [
      h("div", {class: "g4-gk", role: "row"}, h("span", {role: "rowheader"}, h("b", null, k.ko), h("span", {class: "muted"}, ` ${k.rows.length}개`))),
      ...k.rows.map((a) => h("div", {class: "g4-grow", role: "row"},
        h("a", {class: "g4-gn", role: "rowheader", href: ctx.href("account", a.id), title: `${a.name || a.id}${a.rule_ko ? `\n${a.rule_ko}` : ""}`},
          h("b", null, a.name || a.id)),
        LEVS.map((L) => {
          const c = cellOf(a, L, rows);
          const x = (a.lines || {})[String(L)];
          const mix = c.v != null ? (mode === "checks" ? Math.round(10 + 60 * c.v) : mixOf(c.v, vmax)) : 0;
          const title = `${a.name || a.id} ${L}배 · ${MODES.find((m) => m.id === mode).label}: ${c.text}`
            + (x ? ` · 손익 ${fmt.pct(x.pnl_pct, true)} · 거래 ${fmt.int(x.trades)}` : "") + (x && x.ruins ? ` · 파산 ${x.ruins}번` : "");
          return h("a", {class: ["g4-c", c.cls, mix >= 58 && c.cls !== "seq" ? "hi" : "", x && x.ruined ? "ruined" : ""], role: "cell",
            href: ctx.href("account", a.id), title, "aria-label": title, style: mix ? {"--mix": `${mix}%`} : null}, c.text);
        })))]);
    put(grid, h("div", {class: "g4-grid", role: "table", "aria-label": "계좌 × 배수 지도"}, head, body));
  }

  await load();
  ctx.every(60000, load);
}

function median(xs) {
  const a = [...xs].sort((x, y) => x - y);
  return a.length ? (a.length % 2 ? a[(a.length - 1) / 2] : (a[a.length / 2 - 1] + a[a.length / 2]) / 2) : null;
}

function legendOf(mode, vmax) {
  const ruin = h("span", {class: "dl-lg"}, h("i", {class: "g4-sw ruined"}), "파산한 적 있는 줄 (점선)");
  if (mode === "pnl" || mode === "stops") {
    return h("div", {class: "hm-legend"}, h("span", {class: "hm-scale"}, h("span", {class: "num"}, fmt.pct(-vmax, true, 0)), h("i", {class: "hm-grad"}),
      h("span", {class: "num"}, fmt.pct(vmax, true, 0))), h("span", {class: "muted"}, "초록 = 이익, 빨강 = 손실, 진할수록 큼"), ruin);
  }
  if (mode === "checks") {
    return h("div", {class: "hm-legend"}, [0, 1, 2, 3, 4].map((k) => h("span", {class: "dl-lg"},
      h("i", {class: "g4-sw seq", style: {"--mix": `${Math.round(10 + 60 * k / 5)}%`}}), `${k}/5`)),
    h("span", {class: "dl-lg"}, h("i", {class: "g4-sw pass"}), "5/5 = 우리 기준 통과"), ruin);
  }
  return h("div", {class: "hm-legend"}, ["confirming", "confirmed", "failed"].map((s) => h("span", {class: "dl-lg"},
    h("i", {class: ["g4-sw", `cf-${s}`]}), CONFIRM_KO[s])), h("span", {class: "dl-lg"}, h("i", {class: "g4-sw na"}), "확인 기간 없음"), ruin);
}
