// #/judge 판정: the verdict line on top, the two rule sets side by side ("우리 기준" / "친구 기준"), then per account and
// leverage every check with ✓ / ✗ and its value (judge.json, every 60 s).
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {LEVS, KINDS, kindOfId} from "../labels.js";

export async function mount(el, ctx) {
  ctx.setTitle("판정");
  const saved = local.get("judge", {}) || {};
  const f = {lev: saved.lev || "20", kind: saved.kind || "all", only: !!saved.only};
  const keep = () => local.set("judge", f);
  const verdict = h("section", {class: "card hero dl-verdict", "aria-label": "판정"});
  const rules = h("div", {class: "grid2"});
  const levSeg = ui.seg([...LEVS.map((L) => ({id: String(L), label: `${L}배`})), {id: "all", label: "전체"}], f.lev,
    (v) => { f.lev = v; keep(); paintTable(); }, {label: "배수"});
  const kindSeg = ui.seg([{id: "all", label: "전체"}, ...KINDS.map((k) => ({id: k.id, label: k.ko}))], f.kind,
    (v) => { f.kind = v; keep(); paintTable(); }, {label: "계좌 종류"});
  const only = ui.toggle("통과한 것만", f.only, (v) => { f.only = v; keep(); paintTable(); }, "우리 기준이나 친구 기준을 통과한 줄만");
  let build = null;                                   // (rows) -> table, set by paintTable for the current columns
  const pg = ui.pager({size: 48, empty: "맞는 줄이 없습니다", render: (part) => (build ? build(part) : ui.empty("—"))});
  el.append(ui.screenHead("판정", "실전에 써도 되는지 두 가지 기준으로 봅니다"), verdict, rules,
    ui.card({plate: "계좌 × 배수", cls: "dl-controls"},
      h("div", {class: "dl-fields"}, ui.field("배수", levSeg), ui.field("계좌 종류", kindSeg)),
      h("div", {class: "row wrap dl-togs"}, only), pg.el),
    ui.note("✓ 통과 · ✗ 못 미침 · — 해당 없음. 기준을 모두 넘어야 그 기준의 \"통과\"입니다."));

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
      put(rules); pg.set([]);
      return;
    }
    const rowsAll = d.rows || [];
    const nOurs = rowsAll.filter((r) => r.ours && r.ours.pass).length;
    const nFr = rowsAll.filter((r) => r.friend && r.friend.pass).length;
    put(verdict,
      h("div", {class: "card-h"}, ui.plate("오늘의 판정"), d.generated_ms ? h("span", {class: "sub"}, `${fmt.kst(d.generated_ms)} 기준`) : null),
      nOurs > 0 ? h("p", {class: "dl-vbig ok"}, `통과 ${fmt.int(nOurs)}줄`) : h("p", {class: "dl-vbig no"}, "실전 금지"),
      h("p", {class: "dl-vline"}, d.verdict_ko || "—"),
      h("div", {class: "stats dl-s4"},
        ui.stat("우리 기준 통과", `${fmt.int(nOurs)}줄`, `전체 ${fmt.int(rowsAll.length)}줄 중`, nOurs ? "dl-good" : null),
        ui.stat("친구 기준 통과", `${fmt.int(nFr)}줄`, `전체 ${fmt.int(rowsAll.length)}줄 중`, nFr ? "dl-good" : null)));
    const rk = d.rules_ko || {};
    put(rules,
      ui.card({plate: "우리 기준", sub: "모두 넘어야 통과"}, ruleList(rk.ours)),
      ui.card({plate: "친구 기준", sub: "모두 넘어야 통과"}, ruleList(rk.friend)));
    paintTable(true);
  }

  function paintTable(keepPage) {
    if (!data || isMissing(data)) { pg.set([]); return; }
    let rows = data.rows || [];
    if (f.lev !== "all") rows = rows.filter((r) => String(r.L) === f.lev);
    if (f.kind !== "all") rows = rows.filter((r) => kindOfId(r.id) === f.kind);
    if (f.only) rows = rows.filter((r) => (r.ours && r.ours.pass) || (r.friend && r.friend.pass));
    const names = (side) => {
      const out = [];
      for (const r of data.rows || []) for (const c of (r[side] && r[side].checks) || []) if (!out.includes(c.name_ko)) out.push(c.name_ko);
      return out;
    };
    const ours = names("ours"), friend = names("friend");
    const cellOf = (r, side, name) => {
      const c = ((r[side] && r[side].checks) || []).find((x) => x.name_ko === name);
      return c ? h("span", {class: "dl-chk"}, ui.mark(c.ok), h("small", {class: "muted"}, c.value_ko || "")) : h("span", {class: "muted"}, "—");
    };
    const verdictCell = (v) => (v == null ? h("span", {class: "muted"}, "해당 없음") : v ? ui.pill("통과", "good") : ui.pill("미통과", "bad"));
    const head2 = [h("th", {class: "l dl-c2", scope: "col"}, "계좌"), h("th", {scope: "col"}, "배수"),
      h("th", {class: "dl-jg", scope: "col"}, "결과"), ...ours.map((n) => h("th", {scope: "col", title: n}, n)),
      h("th", {class: "dl-jg", scope: "col"}, "결과"), ...friend.map((n) => h("th", {scope: "col", title: n}, n))];
    const head1 = h("tr", {class: "dl-htop"}, h("th", {colspan: "2", class: "l dl-c2"}, ""),
      h("th", {colspan: String(ours.length + 1), class: "dl-jg dl-jgh"}, "우리 기준"),
      h("th", {colspan: String(friend.length + 1), class: "dl-jg dl-jgh"}, "친구 기준"));
    build = (part) => h("div", {class: "tbl-wrap"}, h("table", {class: "tbl dl-judge"},
      h("thead", null, head1, h("tr", null, head2)), h("tbody", null, part.map((r) => h("tr", {class: (r.ours && r.ours.pass) || (r.friend && r.friend.pass) ? "dl-passrow" : ""},
      h("td", {class: "l dl-c2"}, h("a", {href: ctx.href("account", r.id)}, r.name || r.id)),
      h("td", null, fmt.lev(r.L)),
      h("td", {class: "dl-jg"}, verdictCell(r.ours ? r.ours.pass : null)),
      ...ours.map((n) => h("td", null, cellOf(r, "ours", n))),
      h("td", {class: "dl-jg"}, verdictCell(r.friend ? r.friend.pass : null)),
      ...friend.map((n) => h("td", null, cellOf(r, "friend", n))))))));
    pg.set(rows, keepPage);
  }

  await load();
  ctx.every(60000, load);
}

function ruleList(items) {
  if (!items || !items.length) return ui.empty("기준 문구가 아직 없습니다");
  return h("ol", {class: "dl-rules"}, items.map((x) => h("li", null, x)));
}
