// #/telegram 알림 기록 (CONTRACT 8.11): the demo lab's Telegram messages exactly as they were sent (or are waiting /
// failed), newest first, filtered by kind and by state. The text is shown as plain text (line breaks kept), never
// parsed as markup. telegram.json every 60 s.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {tgKindKo, TG_STATUS_KO} from "../labels.js";

const ST_CLS = {sent: "thin", queued: "accent", error: "bad"};

export async function mount(el, ctx) {
  ctx.setTitle("알림 기록");
  const saved = local.get("telegram", {}) || {};
  const f = {kind: saved.kind || "all", st: saved.st || "all"};
  const keep = () => local.set("telegram", f);
  const kindBox = h("span");
  const stSeg = ui.seg([{id: "all", label: "전체"}, ...Object.entries(TG_STATUS_KO).map(([id, label]) => ({id, label}))], f.st,
    (v) => { f.st = v; keep(); apply(false); }, {label: "상태"});
  const count = h("p", {class: "note"});
  const pg = ui.pager({size: 15, empty: "맞는 알림이 없습니다", render: (part) => h("div", {class: "tg-list"}, part.map(item))});
  const top = h("div");
  el.append(ui.screenHead("알림 기록", "데모 랩 텔레그램 방에 보낸 글 그대로"), top,
    ui.card({plate: "알림", sub: "새것부터 (최근 300개까지)", cls: "dl-controls"},
      h("div", {class: "dl-fields"}, ui.field("종류", kindBox), ui.field("상태", stSeg)), count, pg.el),
    ui.note("보낼 차례 = 아직 큐에 있음 (1초에 하나씩 보냅니다). 보내기 실패는 텔레그램이 받지 않은 것이고, 다음에 다시 보내지 않습니다."));

  let items = null, seen = null;
  function apply(keepPage) {
    if (!items) return;
    const out = items.filter((x) => (f.kind === "all" || x.kind === f.kind) && (f.st === "all" || x.status === f.st));
    count.textContent = `알림 ${fmt.int(items.length)}개 중 ${fmt.int(out.length)}개`;
    pg.set(out, keepPage);
  }
  async function load() {
    let d;
    try { d = await ctx.api("/api/telegram"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!items) put(top, ui.errorBox(e, load));
      return;
    }
    if (d && d.generated_ms != null && d.generated_ms === seen) return;
    seen = d ? d.generated_ms : null;
    if (isMissing(d)) { items = null; put(top, ui.missing("알림 기록(telegram.json)")); put(kindBox); count.textContent = ""; pg.set([]); return; }
    put(top);
    const first = items == null;
    items = (d.items || []).filter((x) => x && typeof x === "object");
    const kinds = {};
    for (const x of items) kinds[x.kind] = (kinds[x.kind] || 0) + 1;
    if (f.kind !== "all" && !kinds[f.kind]) f.kind = "all";
    put(kindBox, ui.select([{id: "all", label: `전체 (${fmt.int(items.length)})`},
      ...Object.entries(kinds).sort((a, b) => b[1] - a[1]).map(([k, n]) => ({id: k, label: `${tgKindKo(k)} (${fmt.int(n)})`}))],
    f.kind, (v) => { f.kind = v; keep(); apply(false); }, "종류"));
    const err = items.filter((x) => x.status === "error").length, q = items.filter((x) => x.status === "queued").length;
    if (err || q) put(top, h("div", {class: "row wrap dl-pills"}, q ? ui.pill(`보낼 차례 ${fmt.int(q)}개`, "accent") : null,
      err ? ui.pill(`보내기 실패 ${fmt.int(err)}개`, "bad") : null));
    apply(!first);
  }
  await load();
  ctx.every(60000, load);
}

function item(x) {
  return h("article", {class: ["tg-item", x.status === "error" ? "tg-err" : ""]},
    h("div", {class: "tg-head"}, h("span", {class: "muted num"}, fmt.kst(x.ts_ms)), ui.pill(tgKindKo(x.kind), "thin"),
      ui.pill(TG_STATUS_KO[x.status] || String(x.status ?? "—"), ST_CLS[x.status] || "thin"),
      x.id != null ? h("span", {class: "muted tg-id"}, `#${x.id}`) : null),
    h("pre", {class: "tg-text"}, String(x.text ?? "")));
}
