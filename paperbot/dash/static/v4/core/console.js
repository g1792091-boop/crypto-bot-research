// The dark "◆ 에이전트 콘솔 ◆" terminal panel: yellow event lines, cyan staff lines, amber disagreement boxes; tabs
// 전체 / 에이전트 / 토론 (토론 only while the debate room really runs); tap a meeting-start line to see only that
// meeting; long lines clamp to two with 더 보기. New lines slide in ONLY when they are really new (a later update
// brought them); the first fill never animates. Every line's text is a text node.
import {h, clear} from "./dom.js";
import {hm} from "./fmt.js";
import {moreText, seg} from "./ui.js";
import {slideIn, swap} from "./motion.js";

/**
 * A console line: {id (unique, stable), type: "ev"|"st"|"dis"|"bad", tabs: ["agent","trade","debate"] (which tabs
 * show it besides 전체), meeting: key|null (lines of one meeting share it), ts, who (st), text, start: true (an ev line
 * that starts a meeting: tapping it filters to that meeting), onOpen: fn (optional "방 열기" on staff lines)}.
 */
export function consolePanel(o = {}) {
  const st = {tab: "all", meeting: null, lines: [], ids: new Set()};
  const tabs = (o.tabs || [{id: "all", label: "전체"}, {id: "agent", label: "에이전트"}]).filter((t) => !t.hidden);
  const tabEl = tabs.length > 1 ? seg(tabs, "all", (id) => { st.tab = id; apply(true); }, {label: "콘솔 보기"}) : null;
  if (tabEl) tabEl.className = "con-tabs";
  const fText = h("span");
  const fBar = h("div", {class: "con-filter", hidden: true}, fText,
    h("button", {type: "button", onclick: () => { st.meeting = null; apply(true); }}, "전체 보기"));
  const list = h("ol", {class: "con-list", "aria-live": "polite", style: o.maxHeight ? {maxHeight: o.maxHeight} : null});
  const foot = h("div", {class: "con-foot"}, o.foot || "");
  const el = h("section", {class: "console", "aria-label": o.title || "에이전트 콘솔"},
    h("div", {class: "con-head"}, h("span", {class: "con-title"}, o.title || "에이전트 콘솔"), h("span", {class: "grow"}), o.headRight || null),
    tabEl, fBar, list, foot);

  function lineNode(l) {
    const time = l.ts ? h("time", null, ` (${hm(l.ts)})`) : null;
    let li;
    if (l.type === "st") {
      li = h("li", {class: "cl st"}, h("span", {class: "who"}, `> ${l.who || ""}`), " · ", moreText(l.text || "", 2), time,
        l.onOpen ? h("button", {class: "more", type: "button", onclick: l.onOpen}, " 방 열기") : null);
    } else if (l.type === "dis") {
      li = h("li", {class: "cl dis"}, "◆ ", l.label || "갈린 의견", " · ", l.text || "");
    } else {
      const body = [h("span", {class: "bl"}, "▪ "), "> ", l.text || "", time];
      li = h("li", {class: ["cl", l.type === "bad" ? "bad" : "ev"]},
        l.start && l.meeting != null ? h("button", {class: "go", type: "button", title: "이 회의만 보기",
          onclick: () => { st.meeting = l.meeting; fText.textContent = "이 회의만 보는 중 · " + (l.text || ""); apply(true); }},
          h("span", {class: "lk"}, body)) : body);
    }
    li.dataset.id = l.id;
    li._line = l;
    return li;
  }
  function visible(l) {
    if (st.tab !== "all" && !(l.tabs || []).includes(st.tab)) return false;
    if (st.meeting != null && l.meeting !== st.meeting) return false;
    return true;
  }
  function apply(animate) {
    for (const li of list.children) li.hidden = !visible(li._line);
    fBar.hidden = st.meeting == null;
    if (animate) swap(list);
  }
  const nearBottom = () => list.scrollHeight - list.scrollTop - list.clientHeight < 60;

  /** Replace the lines (sorted by ts). Lines whose id was not there before slide in, unless this is the first fill. */
  function setLines(lines) {
    const first = st.ids.size === 0;
    const stick = nearBottom();
    const sorted = [...lines].sort((a, b) => (a.ts || 0) - (b.ts || 0)).slice(-(o.max || 120));
    const keep = new Set(sorted.map((l) => l.id));
    for (const li of [...list.children]) if (!keep.has(li.dataset.id)) li.remove();
    const have = new Map([...list.children].map((li) => [li.dataset.id, li]));
    let prev = null;
    for (const l of sorted) {
      let li = have.get(String(l.id));
      if (!li) {
        li = lineNode(l);
        if (prev) prev.after(li); else list.prepend(li);
        if (!first && !st.ids.has(String(l.id))) slideIn(li);
      }
      li.hidden = !visible(l);
      prev = li;
    }
    st.ids = new Set(sorted.map((l) => String(l.id)));
    st.lines = sorted;
    if (stick || first) list.scrollTop = list.scrollHeight;
  }
  el.setLines = setLines;
  el.push = (l) => setLines([...st.lines.filter((x) => x.id !== l.id), l]);
  el.setFoot = (t) => { foot.textContent = t || ""; };
  el.clearFilter = () => { st.meeting = null; apply(false); };
  el.isEmpty = () => st.lines.length === 0;
  el.showEmpty = (text) => {
    if (st.lines.length) return;
    clear(list);
    const li = h("li", {class: "cl", style: {color: "var(--muted)"}}, text);
    li.dataset.id = "_empty"; li._line = {id: "_empty", tabs: tabs.map((t) => t.id)};
    list.append(li); st.ids = new Set();
  };
  return el;
}
