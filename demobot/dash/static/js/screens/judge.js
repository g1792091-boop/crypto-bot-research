// #/judge 판정: the verdict line on top (candidates first), the note on judging many lines at once, the "실전 후보"
// cards (a line that passed and then its 4-week confirmation: window, measured cost, stop-rule result), the
// confirmation periods with their progress (CONTRACT 8.1), the three rule sets side by side ("우리 기준" / "친구 기준" /
// "정지 규칙", 8.2), then per account and leverage every check with ✓ / ✗ and its value, the line's confirmation
// badge and its stop-rule twin (P&L, drawdown, "우리 기준" on the twin). judge.json every 60 s.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {LEVS, KINDS, kindOfId} from "../labels.js";

const DAY = 86400000;

export async function mount(el, ctx) {
  ctx.setTitle("판정");
  const saved = local.get("judge", {}) || {};
  const f = {lev: saved.lev || "20", kind: saved.kind || "all", only: !!saved.only};
  const keep = () => local.set("judge", f);
  const verdict = h("section", {class: "card hero dl-verdict", "aria-label": "판정"});
  const candBox = h("div", {class: "stack"});
  const confBox = h("div");
  const rules = h("div", {class: "grid3"});
  const levSeg = ui.seg([...LEVS.map((L) => ({id: String(L), label: `${L}배`})), {id: "all", label: "전체"}], f.lev,
    (v) => { f.lev = v; keep(); paintTable(); }, {label: "배수"});
  const kindSeg = ui.seg([{id: "all", label: "전체"}, ...KINDS.map((k) => ({id: k.id, label: k.ko}))], f.kind,
    (v) => { f.kind = v; keep(); paintTable(); }, {label: "계좌 종류"});
  const only = ui.toggle("통과·확인 중인 것만", f.only, (v) => { f.only = v; keep(); paintTable(); }, "우리 기준·친구 기준을 통과했거나 확인 기간이 있는 줄만");
  let build = null;                                   // (rows) -> table, set by paintTable for the current columns
  const pg = ui.pager({size: 48, empty: "맞는 줄이 없습니다", render: (part) => (build ? build(part) : ui.empty("—"))});
  el.append(ui.screenHead("판정", "실전에 써도 되는지 두 가지 기준으로 봅니다"), verdict, candBox,
    ui.card({plate: "확인 기간", sub: "기준을 처음 넘은 줄: 그 뒤 4주 (거래 20건 이상)를 다시 봅니다"}, confBox),
    rules,
    ui.card({plate: "계좌 × 배수", cls: "dl-controls"},
      h("div", {class: "dl-fields"}, ui.field("배수", levSeg), ui.field("계좌 종류", kindSeg)),
      h("div", {class: "row wrap dl-togs"}, only), pg.el),
    ui.note("✓ 통과 · ✗ 못 미침 · — 해당 없음. 기준을 모두 넘어야 그 기준의 \"통과\"입니다. 정지 규칙 칸은 같은 줄을 정지 규칙으로 돌렸다면의 결과입니다."));

  let data = null, seen = null;
  async function load() {
    let d;
    try { d = await ctx.api("/api/judge"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!data) put(verdict, ui.errorBox(e, load));
      return;
    }
    if (d && d.generated_ms != null && d.generated_ms === seen) return;
    seen = d ? d.generated_ms : null;
    data = d;
    if (isMissing(d)) {
      put(verdict, h("p", {class: "dl-vbig no"}, "실전 금지"), ui.missing("판정 자료"));
      put(rules); put(candBox); put(confBox, ui.none("준비 중")); pg.set([]);
      return;
    }
    const rowsAll = d.rows || [];
    const nOurs = rowsAll.filter((r) => r.ours && r.ours.pass).length;
    const nFr = rowsAll.filter((r) => r.friend && r.friend.pass).length;
    const conf = Array.isArray(d.confirm) ? d.confirm : null;
    const cands = Array.isArray(d.candidates) ? d.candidates : [];
    const nConf = conf ? conf.filter((c) => c.status === "confirming").length : null;
    put(verdict,
      h("div", {class: "card-h"}, ui.plate("오늘의 판정"), d.generated_ms ? h("span", {class: "sub"}, `${fmt.kst(d.generated_ms)} 기준`) : null),
      cands.length ? h("p", {class: "dl-vbig ok"}, `실전 후보 ${fmt.int(cands.length)}줄`)
        : nConf ? h("p", {class: "dl-vbig warn"}, `확인 기간 ${fmt.int(nConf)}줄`)
          : nOurs > 0 ? h("p", {class: "dl-vbig ok"}, `통과 ${fmt.int(nOurs)}줄`) : h("p", {class: "dl-vbig no"}, "실전 금지"),
      h("p", {class: "dl-vline"}, d.verdict_ko || "—"),
      d.multi_note_ko ? h("p", {class: "refnote"}, h("b", null, "여러 줄을 한꺼번에 보면: "), d.multi_note_ko) : null,
      h("div", {class: "stats dl-s4"},
        ui.stat("우리 기준 통과", `${fmt.int(nOurs)}줄`, `전체 ${fmt.int(d.lines_judged ?? rowsAll.length)}줄 중`, nOurs ? "dl-good" : null),
        ui.stat("친구 기준 통과", `${fmt.int(nFr)}줄`, `전체 ${fmt.int(d.lines_judged ?? rowsAll.length)}줄 중`, nFr ? "dl-good" : null),
        ui.stat("확인 기간", nConf == null ? "준비 중" : `${fmt.int(nConf)}줄`, "4주 확인 중"),
        ui.stat("실전 후보", `${fmt.int(cands.length)}줄`, "두 분이 정할 차례", cands.length ? "dl-good" : null)));
    paintCands(cands);
    paintConfirm(conf);
    const rk = d.rules_ko || {};
    put(rules,
      ui.card({plate: "우리 기준", sub: "모두 넘어야 통과"}, ruleList(rk.ours)),
      ui.card({plate: "친구 기준", sub: "모두 넘어야 통과"}, ruleList(rk.friend)),
      ui.card({plate: "정지 규칙", sub: "실제 돈에 쓸 멈춤 규칙 · 새 진입만 막음"}, ruleList(d.stop_rules_ko, "정지 규칙 문구가 아직 없습니다")));
    paintTable(true);
  }

  function paintCands(cands) {
    if (!cands.length) { put(candBox); return; }
    put(candBox, h("h2", {class: "dl-h2"}, "실전 후보"), h("div", {class: "grid2"}, cands.map((c) => {
      const w = c.window || {}, co = c.costs || {}, sp = c.stops || null;
      const pT = fmt.pct(w.pnl_pct, true);
      return ui.card({hero: true, cls: "dl-cand", plate: "실전 후보", sub: c.decided_ms ? `${fmt.kst(c.decided_ms)} 확인 끝` : ""},
        h("p", {class: "dl-candn"}, h("a", {href: ctx.href("account", c.id)}, c.name || c.id), " ", h("span", {class: "pp good"}, fmt.lev(c.L))),
        h("div", {class: "stats dl-s4"},
          ui.stat("확인 기간 손익", ui.signed(pT, fmt.tone(w.pnl_pct, pT), "b"), `거래 ${fmt.int(w.n)}건`),
          ui.stat("평균 R", fmt.r(w.mean_R), "수수료 뺀 뒤"),
          ui.stat("최대 낙폭", fmt.ratio(w.max_dd), "확인 기간 안"),
          ui.stat("정지 규칙이면", sp ? fmt.pct(sp.pnl_pct, true) : "기록 없음", sp ? `낙폭 ${fmt.ratio(sp.max_dd)} · 전체 기간` : "준비 중")),
        h("p", {class: "note"}, "실제 비용: ",
          co.entry_bps == null ? "기록 없음 (호가를 잰 진입이 없음: 지정가 진입이거나 기록 전)" : `진입 한 번 ${fmt.num(co.entry_bps, 2)}bp (가정 2bp)`,
          co.roundtrip_pct_of_pnl == null ? "" : ` · 가정보다 더 든 왕복 비용 = 번 돈의 ${fmt.pct(co.roundtrip_pct_of_pnl, false, 1)}`),
        h("p", {class: "note"}, "실제 돈을 쓸지는 두 분이 정합니다. 정하기 전까지는 실전 금지입니다."));
    })));
  }

  function paintConfirm(conf) {
    if (conf == null) { put(confBox, ui.none("준비 중 (엔진이 아직 확인 기간을 쓰지 않습니다)")); return; }
    if (!conf.length) { put(confBox, ui.none("아직 확인 기간에 들어간 줄이 없습니다")); return; }
    const now = Date.now();
    put(confBox, h("div", {class: "dl-confl"}, conf.map((c) => {
      const left = c.status === "confirming" && c.min_end_ms ? Math.max(0, (c.min_end_ms - now) / DAY) : null;
      const pT = fmt.pct(c.pnl_pct, true);
      return h("div", {class: ["dl-conf", "st-" + c.status]},
        h("div", {class: "dl-evt"}, ui.confirmBadge(c), h("a", {href: ctx.href("account", c.id)}, `${c.name || c.id} ${fmt.lev(c.L)}`),
          h("span", {class: "muted num"}, `${fmt.mmdd(c.start_ms)} 시작`),
          c.decided_ms ? h("span", {class: "muted num"}, `${fmt.mmdd(c.decided_ms)} 끝`) : null),
        c.status === "confirming"
          ? ui.progress(c.progress, `${fmt.ratio(c.progress, 0)} · 거래 ${fmt.int(c.n)} / ${fmt.int(c.need_n ?? 20)}건 · `
            + (left == null ? "" : left > 0 ? `${fmt.num(left, 1)}일 남음` : "28일 지남"))
          : ui.progress(1, `거래 ${fmt.int(c.n)}건`, c.status === "failed" ? "bad" : "ok"),
        h("div", {class: "dl-confs"},
          h("span", null, h("span", {class: "muted"}, "손익 "), ui.signed(pT, fmt.tone(c.pnl_pct, pT))),
          h("span", null, h("span", {class: "muted"}, "평균 "), fmt.r(c.mean_R)),
          h("span", null, h("span", {class: "muted"}, "낙폭 "), fmt.ratio(c.max_dd)),
          Number(c.liqs) ? h("span", {class: "down"}, `강제청산 ${fmt.int(c.liqs)}`) : null,
          Number(c.ruins) ? h("span", {class: "down"}, `파산 ${fmt.int(c.ruins)}`) : null),
        c.why_ko ? h("p", {class: "note"}, c.why_ko) : null);
    })), ui.note("확인 기간: 처음 통과한 때부터 들어간 거래만 셉니다. 28일이 지나고 거래가 20건 이상이면 끝 (모자라면 20건이 될 때, 길어도 56일). "
      + "끝날 때 거래 20건 이상 · 평균 R > 0 · 손익 + · 낙폭 30% 미만 · 파산·강제청산 없음이면 실전 후보, 아니면 실패입니다."));
  }

  function paintTable(keepPage) {
    if (!data || isMissing(data)) { pg.set([]); return; }
    let rows = data.rows || [];
    if (f.lev !== "all") rows = rows.filter((r) => String(r.L) === f.lev);
    if (f.kind !== "all") rows = rows.filter((r) => kindOfId(r.id) === f.kind);
    if (f.only) rows = rows.filter((r) => (r.ours && r.ours.pass) || (r.friend && r.friend.pass) || (r.confirm && r.confirm.status));
    const names = (side) => {
      const out = [];
      for (const r of data.rows || []) for (const c of (r[side] && r[side].checks) || []) if (!out.includes(c.name_ko)) out.push(c.name_ko);
      return out;
    };
    const ours = names("ours"), friend = names("friend");
    const hasStops = (data.rows || []).some((r) => r.stops);
    const cellOf = (r, side, name) => {
      const c = ((r[side] && r[side].checks) || []).find((x) => x.name_ko === name);
      return c ? h("span", {class: "dl-chk"}, ui.mark(c.ok), h("small", {class: "muted"}, c.value_ko || "")) : h("span", {class: "muted"}, "—");
    };
    const verdictCell = (v) => (v == null ? h("span", {class: "muted"}, "해당 없음") : v ? ui.pill("통과", "good") : ui.pill("미통과", "bad"));
    const confCell = (r) => (r.confirm && r.confirm.status ? h("span", {class: "dl-kn"}, ui.confirmBadge(r.confirm),
      h("small", {class: "muted"}, `${fmt.mmdd(r.confirm.start_ms)}~${fmt.mmdd(r.confirm.end_ms)}`)) : h("span", {class: "muted"}, "—"));
    const stopCells = (r) => {
      const sp = r.stops;
      if (!sp) return [h("td", {class: "dl-jg muted"}, "준비 중"), h("td", {class: "muted"}, "—"), h("td", {class: "muted"}, "—")];
      const pT = fmt.pct(sp.pnl_pct, true);
      return [h("td", {class: "dl-jg"}, ui.signed(pT, fmt.tone(sp.pnl_pct, pT))), h("td", null, fmt.ratio(sp.max_dd)),
        h("td", null, ui.mark(sp.ours_pass == null ? null : !!sp.ours_pass))];
    };
    const head2 = [h("th", {class: "l dl-c2", scope: "col"}, "계좌"), h("th", {scope: "col"}, "배수"),
      h("th", {scope: "col", title: "가장 최근 확인 기간"}, "확인"),
      h("th", {class: "dl-jg", scope: "col"}, "결과"), ...ours.map((n) => h("th", {scope: "col", title: n}, n)),
      h("th", {class: "dl-jg", scope: "col"}, "결과"), ...friend.map((n) => h("th", {scope: "col", title: n}, n)),
      ...(hasStops ? [h("th", {class: "dl-jg", scope: "col"}, "손익"), h("th", {scope: "col"}, "최대 낙폭"), h("th", {scope: "col"}, "우리 기준")] : [])];
    const head1 = h("tr", {class: "dl-htop"}, h("th", {colspan: "3", class: "l dl-c2"}, ""),
      h("th", {colspan: String(ours.length + 1), class: "dl-jg dl-jgh"}, "우리 기준"),
      h("th", {colspan: String(friend.length + 1), class: "dl-jg dl-jgh"}, "친구 기준"),
      hasStops ? h("th", {colspan: "3", class: "dl-jg dl-jgh"}, "정지 규칙 적용 시") : null);
    build = (part) => h("div", {class: "tbl-wrap"}, h("table", {class: "tbl dl-judge"},
      h("thead", null, head1, h("tr", null, head2)), h("tbody", null, part.map((r) => h("tr", {class: (r.ours && r.ours.pass) || (r.friend && r.friend.pass) ? "dl-passrow" : ""},
      h("td", {class: "l dl-c2"}, h("a", {href: ctx.href("account", r.id)}, r.name || r.id)),
      h("td", null, fmt.lev(r.L)),
      h("td", null, confCell(r)),
      h("td", {class: "dl-jg"}, verdictCell(r.ours ? r.ours.pass : null)),
      ...ours.map((n) => h("td", null, cellOf(r, "ours", n))),
      h("td", {class: "dl-jg"}, verdictCell(r.friend ? r.friend.pass : null)),
      ...friend.map((n) => h("td", null, cellOf(r, "friend", n))),
      ...(hasStops ? stopCells(r) : []))))));
    pg.set(rows, keepPage);
  }

  await load();
  ctx.every(60000, load);
}

function ruleList(items, empty = "기준 문구가 아직 없습니다") {
  if (!items || !items.length) return ui.empty(empty);
  return h("ol", {class: "dl-rules"}, items.map((x) => h("li", null, x)));
}

