// #/telegram 알림 기록 (CONTRACT 8.11): the demo lab's Telegram messages exactly as they were sent (or are waiting /
// failed), newest first, filtered by kind and by state. The text is shown as plain text (line breaks kept), never
// parsed as markup. telegram.json every 60 s.
// Round 5 stage 2B (the rule bot's v4 알림 기록 look, alerts.js / alerts.css): four stat cards (all, sent, waiting,
// failed) that count to new values, the kind and the state in one filter bar, one v4 time-stamped row per message
// (time, kind, state, number; the text under it, a long one cut to six lines with 더 보기).
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {tgKindKo, TG_STATUS_KO} from "../labels.js";

const ST_CLS = {sent: "thin", queued: "accent", error: "bad"};
const grp = (label, ...kids) => h("span", {class: "k4-barg s2-g"}, h("span", {class: "k4-k"}, label), ...kids);

/** A block cut to `lines` lines with 더 보기 (v4 ui.moreText; components.css .clamp / .more). */
function clampBox(node, lines) {
  const body = h("div", {class: "clamp s2-tgclamp", style: {"--lines": lines}}, node);
  const btn = h("button", {class: "more", type: "button", hidden: true, "aria-expanded": "false"}, "더 보기");
  btn.addEventListener("click", () => {
    const open = btn.getAttribute("aria-expanded") !== "true";
    btn.setAttribute("aria-expanded", String(open));
    btn.textContent = open ? "접기" : "더 보기";
    body.style.setProperty("--full", K4.reduced() ? "none" : body.scrollHeight + "px");
    body.classList.toggle("open", open);
  });
  const check = () => { if (btn.getAttribute("aria-expanded") !== "true" && body.isConnected) btn.hidden = !(body.scrollHeight > body.clientHeight + 2); };
  requestAnimationFrame(check);
  return h("div", {class: "s2-moretext"}, body, btn);
}

export async function mount(el, ctx) {
  ctx.setTitle("알림 기록");
  const saved = local.get("telegram", {}) || {};
  const f = {kind: saved.kind || "all", st: saved.st || "all"};
  const keep = () => local.set("telegram", f);
  const kindBox = h("span", {class: "k4-barg s2-g"});
  const stSeg = ui.seg([{id: "all", label: "전체"}, ...Object.entries(TG_STATUS_KO).map(([id, label]) => ({id, label}))], f.st,
    (v) => { f.st = v; keep(); apply(false); }, {label: "상태"});
  const count = h("span", {class: "muted s2-count"});
  const pg = ui.pager({size: 15, empty: "맞는 알림이 없습니다", render: (part) => h("div", {class: "tg-list s2-trows"}, part.map(item))});
  const top = h("div");
  const nAll = K4.liveNum(null, {format: (v) => fmt.int(v), flash: "accent"});
  const nSent = K4.liveNum(null, {format: (v) => fmt.int(v), flash: "accent"});
  const nQ = K4.liveNum(null, {format: (v) => fmt.int(v), flash: "accent"});
  const nErr = K4.liveNum(null, {format: (v) => fmt.int(v), flash: "accent"});
  const lastSub = h("span", {class: "s"}, "—");
  const stats = h("div", {class: "stats s4 s2-stats"},
    K4.stat("알림", nAll, lastSub), K4.stat(TG_STATUS_KO.sent || "보냄", nSent, "텔레그램이 받은 것"),
    K4.stat(TG_STATUS_KO.queued || "보낼 차례", nQ, "아직 큐에 있음 (1초에 하나씩)", "warn"),
    K4.stat(TG_STATUS_KO.error || "보내기 실패", nErr, "다시 보내지 않습니다", "bad"));
  el.append(ui.screenHead("알림 기록", "데모 랩 텔레그램 방에 보낸 글 그대로"), top, stats,
    ui.card({plate: "알림", sub: "새것부터 (최근 300개까지)", cls: "s2-tgcard", acts: count},
      h("div", {class: "k4-bar s2-rgbar"}, kindBox, grp("상태", stSeg)), pg.el),
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
    if (isMissing(d)) {
      items = null; put(top, ui.missing("알림 기록(telegram.json)")); put(kindBox); count.textContent = ""; pg.set([]);
      for (const n of [nAll, nSent, nQ, nErr]) n.update(null);
      lastSub.textContent = "준비 중";
      return;
    }
    put(top);
    const first = items == null;
    items = (d.items || []).filter((x) => x && typeof x === "object");
    const kinds = {};
    for (const x of items) kinds[x.kind] = (kinds[x.kind] || 0) + 1;
    if (f.kind !== "all" && !kinds[f.kind]) f.kind = "all";
    put(kindBox, h("span", {class: "k4-k"}, "종류"), ui.select([{id: "all", label: `전체 (${fmt.int(items.length)})`},
      ...Object.entries(kinds).sort((a, b) => b[1] - a[1]).map(([k, n]) => ({id: k, label: `${tgKindKo(k)} (${fmt.int(n)})`}))],
    f.kind, (v) => { f.kind = v; keep(); apply(false); }, "종류"));
    const err = items.filter((x) => x.status === "error").length, q = items.filter((x) => x.status === "queued").length;
    nAll.update(items.length);
    nSent.update(items.filter((x) => x.status === "sent").length);
    nQ.update(q);
    nErr.update(err);
    const newest = items.reduce((m, x) => Math.max(m, Number(x.ts_ms) || 0), 0);
    lastSub.textContent = newest ? `가장 새것 ${fmt.kst(newest)} (${fmt.ago(newest)})` : "기록 없음";
    apply(!first);
  }
  await load();
  ctx.every(60000, load);
}

function item(x) {
  return h("article", {class: ["tg-item", "s2-trow", "s2-tgrow", x.status === "error" ? "tg-err" : ""]},
    h("div", {class: "tg-head meta"}, h("span", {class: "t num"}, fmt.kst(x.ts_ms)), ui.pill(tgKindKo(x.kind), "thin"),
      ui.pill(TG_STATUS_KO[x.status] || String(x.status ?? "—"), ST_CLS[x.status] || "thin")),
    h("span", {class: "side-r"}, x.id != null ? h("span", {class: "muted tg-id"}, `#${x.id}`) : null),
    h("div", {class: "body"}, clampBox(h("pre", {class: "tg-text"}, String(x.text ?? "")), 6)));
}
