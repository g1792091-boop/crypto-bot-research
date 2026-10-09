// Shared pieces in the rule bot's v4 look (components.css class names): cards, plates, pills, stats, tabs, pagers,
// tables, the '준비 중' state. All take plain data and build DOM with h() (text is never parsed as HTML).
import {h, put} from "./dom.js";
import {num} from "./fmt.js";
import {CONFIRM_KO, CONFIRM_CLS, trendKo, volKo} from "./labels.js";
import {starBtn} from "./favs.js";

export const plate = (text) => h("span", {class: "plate"}, text);
export const pill = (text, cls = "", title) => h("span", {class: ["pp", cls], title}, text);
export const empty = (text) => h("p", {class: "empty"}, text);
export const note = (...kids) => h("p", {class: "note"}, ...kids);

/** The shared "마지막 갱신" stamp; app.js keeps its text, every screen head carries it. */
export const stamp = h("span", {class: "dl-upd", "aria-live": "off"}, "마지막 갱신 —");

/** The menu screen being shown ({id, ko}; null for a page reached from a row: 계좌 자세히, 거래 차트). app.js sets it. */
let PAGE = null;
export function setPage(p) { PAGE = p; }

/** Screen header: h1, the ☆ of a menu screen (favs.js), the one-line sub, the 마지막 갱신 stamp on the right. */
export function screenHead(title, sub) {
  return h("div", {class: "scr-head"}, h("h1", null, title),
    PAGE ? starBtn("page", PAGE.id, {label: PAGE.ko, cls: "dl-hstar"}) : null,
    sub ? h("span", {class: "sub"}, sub) : null,
    h("span", {class: "grow"}), stamp);
}

/** card({title, plate, sub, acts, cls, hero, id}, ...children) */
export function card(o = {}, ...kids) {
  const head = (o.title || o.plate || o.acts || o.sub) ? h("div", {class: "card-h"},
    o.plate ? plate(o.plate) : null, o.title ? h("h2", null, o.title) : null,
    o.sub ? h("span", {class: "sub"}, o.sub) : null,
    o.acts ? h("div", {class: "acts"}, o.acts) : null) : null;
  return h("section", {class: ["card", o.hero ? "hero" : "", o.cls], id: o.id, "aria-label": o.label || o.title || o.plate}, head, kids);
}

export function stat(k, v, sub, cls) {
  return h("div", {class: ["stat", cls]}, h("span", {class: "k"}, k), v instanceof Node ? v : h("b", null, v ?? "—"),
    sub != null ? (sub instanceof Node ? sub : h("span", {class: "s"}, sub)) : null);
}
export function kv(pairs) {
  return h("dl", {class: "kv"}, pairs.filter(Boolean).map(([k, v]) => h("div", null, h("dt", null, k), h("dd", null, v ?? "—"))));
}

/** The engine has not written this file yet. */
export function missing(what = "자료") {
  return h("div", {class: "dl-missing"}, h("b", null, "준비 중"),
    h("span", null, ` · ${what}가 아직 없습니다. 엔진이 첫 스냅샷을 쓰면 저절로 나타납니다.`));
}
/** A load that failed (the last good data, if any, stays on screen). */
export function errorBox(err, retry) {
  const why = err && err.status === 0 ? "서버에 닿지 못했습니다" : err && err.status === 400 ? "요청 값이 맞지 않습니다" : "불러오지 못했습니다";
  return h("div", {class: "errbox", role: "status"}, h("span", null, why),
    retry ? h("button", {class: "btn-line", type: "button", onclick: retry}, "다시 시도") : null);
}

/** seg([{id, label}], value, onChange, {label}) -> div.seg (tabs, arrow keys) with .set(id). */
export function seg(options, value, onChange, o = {}) {
  const el = h("div", {class: ["seg", o.cls], role: "tablist", "aria-label": o.label || "보기"});
  const btns = options.map((op) => h("button", {type: "button", role: "tab", "aria-selected": String(String(op.id) === String(value)),
    tabindex: String(op.id) === String(value) ? "0" : "-1", title: op.title, dataset: {id: op.id}}, op.label));
  const select = (b, focus) => {
    btns.forEach((x) => { const on = x === b; x.setAttribute("aria-selected", String(on)); x.tabIndex = on ? 0 : -1; });
    if (focus) b.focus();
  };
  btns.forEach((b) => {
    b.addEventListener("click", () => { select(b, false); if (onChange) onChange(b.dataset.id); });
    b.addEventListener("keydown", (e) => {
      const i = btns.indexOf(b);
      const n = e.key === "ArrowRight" ? btns[(i + 1) % btns.length] : e.key === "ArrowLeft" ? btns[(i - 1 + btns.length) % btns.length] : null;
      if (n) { e.preventDefault(); select(n, true); if (onChange) onChange(n.dataset.id); }
    });
  });
  el.append(...btns);
  el.set = (id) => { const b = btns.find((x) => x.dataset.id === String(id)); if (b) select(b, false); };
  return el;
}

/** A labelled control row: "매매법  [S2][N02][N04]". */
export const field = (label, control) => h("div", {class: "dl-field"}, h("span", {class: "dl-fk"}, label), control);

/** select([{id, label}], value, onChange, label) */
export function select(options, value, onChange, label) {
  const el = h("select", {class: "select", "aria-label": label},
    options.map((op) => h("option", {value: String(op.id), selected: String(op.id) === String(value)}, op.label)));
  el.addEventListener("change", () => onChange && onChange(el.value));
  return el;
}

/** A switch button (aria-pressed), e.g. "승률 60% 이상만". */
export function toggle(label, on, onChange, title) {
  const b = h("button", {type: "button", class: "dl-tog", "aria-pressed": String(!!on), title}, label);
  b.addEventListener("click", () => {
    const v = b.getAttribute("aria-pressed") !== "true";
    b.setAttribute("aria-pressed", String(v));
    if (onChange) onChange(v);
  });
  return b;
}

/** A disclosure: a button that opens / closes a region (kept open across refreshes: the node is not rebuilt). */
export function disclosure(label, content, open = false) {
  const region = h("div", {class: "dl-region", hidden: !open}, content);
  const btn = h("button", {class: "linkish", type: "button", "aria-expanded": String(open)}, label);
  btn.addEventListener("click", () => {
    const o = btn.getAttribute("aria-expanded") !== "true";
    btn.setAttribute("aria-expanded", String(o));
    region.hidden = !o;
  });
  return h("div", {class: "disclosure"}, btn, region);
}

/** pager({size, render: (items) => Node, empty}) -> {el, set(items, keepPage)}: one page at a time with 이전 / 다음. */
export function pager(o) {
  const st = {items: [], page: 0};
  const body = h("div", {class: "dl-pbody"});
  const info = h("span", {class: "pinfo"});
  const prev = h("button", {class: "btn-line", type: "button"}, "이전");
  const next = h("button", {class: "btn-line", type: "button"}, "다음");
  const bar = h("div", {class: "pager"}, prev, info, next);
  const size = o.size || 20;
  const render = () => {
    const pages = Math.max(1, Math.ceil(st.items.length / size));
    st.page = Math.min(st.page, pages - 1);
    const s0 = st.page * size, part = st.items.slice(s0, s0 + size);
    put(body, part.length ? o.render(part, s0) : empty(o.empty || "맞는 항목이 없습니다"));
    info.textContent = st.items.length ? `${num(s0 + 1, 0)}–${num(s0 + part.length, 0)} / ${num(st.items.length, 0)}` : "0 / 0";
    prev.disabled = st.page === 0; next.disabled = st.page >= pages - 1;
    bar.hidden = st.items.length <= size;
  };
  prev.addEventListener("click", () => { st.page--; render(); });
  next.addEventListener("click", () => { st.page++; render(); });
  return {el: h("div", {class: "stack tight dl-pager"}, body, bar), set(items, keepPage) { st.items = items || []; if (!keepPage) st.page = 0; render(); }};
}

/** A table in its own scrolling box. cols: [{label, l (left), cls, get(row) -> text|Node, title}] */
export function table(cols, rows, o = {}) {
  return h("div", {class: ["tbl-wrap", o.wrapCls]}, h("table", {class: ["tbl", o.cls]},
    o.caption ? h("caption", {class: "sr"}, o.caption) : null,
    h("thead", null, o.headTop || null, h("tr", null, cols.map((c) => h("th", {class: [c.l ? "l" : "", c.hcls], title: c.title, scope: "col"}, c.label)))),
    h("tbody", null, rows.map((r, i) => {
      const tr = h("tr", {class: [o.onRow ? "click" : "", o.rowCls ? o.rowCls(r) : ""]},
        cols.map((c) => { const v = c.get(r, i); return h("td", {class: [c.l ? "l" : "", c.cls ? (typeof c.cls === "function" ? c.cls(r) : c.cls) : ""]}, v instanceof Node ? v : v ?? "—"); }));
      if (o.onRow) {
        tr.tabIndex = 0;
        // a link or button inside the row does its own thing (the row's own action is for the rest of the row)
        tr.addEventListener("click", (e) => { if (!(e.target && e.target.closest && e.target.closest("a, button"))) o.onRow(r); });
        tr.addEventListener("keydown", (e) => { if (e.key === "Enter") o.onRow(r); });
      }
      return tr;
    }))));
}

/** ✓ / ✗ / — for a check (true / false / null). */
export function mark(ok, text) {
  if (ok == null) return h("span", {class: "dl-mk na", title: "해당 없음"}, "—", text ? ` ${text}` : null);
  return h("span", {class: ["dl-mk", ok ? "ok" : "no"]}, ok ? "✓" : "✗", text ? ` ${text}` : null);
}

/** A coloured number: span.num.up/down */
export const signed = (text, tone, tag = "span") => h(tag, {class: ["num", tone]}, text);

// ---------------------------------------------------------------- round 3 pieces (CONTRACT section 8)
/** The badge of a line's latest confirmation period ({status} or null -> nothing). */
export function confirmBadge(c, withNone) {
  if (!c || !c.status) return withNone ? h("span", {class: "muted"}, "—") : null;
  return pill(CONFIRM_KO[c.status] || String(c.status), CONFIRM_CLS[c.status] || "thin");
}

/** A progress bar 0..1 with its words (never colour alone). */
export function progress(frac, text, cls) {
  const v = Number.isFinite(Number(frac)) ? Math.max(0, Math.min(1, Number(frac))) : 0;
  return h("div", {class: ["dl-prog", cls]}, h("div", {class: "dl-progbar", role: "progressbar", "aria-valuemin": "0",
    "aria-valuemax": "100", "aria-valuenow": String(Math.round(v * 100)), "aria-label": text || "진행"},
  h("i", {style: {"--p": `${(v * 100).toFixed(1)}%`}})), text ? h("span", {class: "dl-progt"}, text) : null);
}

/** Trend and volatility chips ("상승 추세" / "변동 큼"); a missing label reads "기록 없음". */
export function regimeChips(trend, vol) {
  return h("span", {class: "dl-rgc"}, h("span", {class: ["dl-rg", "t-" + (trend || "none")]}, trendKo(trend)),
    h("span", {class: ["dl-rg", "v-" + (vol || "none")]}, volKo(vol)));
}

/** A big "준비 중" / "기록 없음" line for a missing part of a file. */
export const none = (text = "기록 없음") => h("p", {class: "empty"}, text);

/** A trade's measured entry cost (taker, CONTRACT 8.3) or its limit fill check (maker): "1.35bp" / "지정가 +4.2bp" /
 *  "닿기만" (the bar did not go 1 bp past the limit: it may not have filled). */
export function costCell(t) {
  if (t.through_bps != null) {
    return Number(t.through_bps) < 1 ? h("span", {class: "warn-t", title: "봉이 지정가를 1bp도 넘지 못함: 체결 안 됐을 수 있음"}, "닿기만")
      : h("span", {class: "muted", title: "지정가 진입: 봉이 지정가를 넘어간 거리"}, `지정가 +${num(t.through_bps, 1)}bp`);
  }
  if (t.cost_bps == null) return h("span", {class: "muted", title: "호가를 재기 전이거나 기록 없음"}, "—");
  return h("span", {class: ["num", Number(t.cost_bps) > 2 ? "warn-t" : ""], title: "실제 호가로 잰 진입 비용 (가정 2bp)"}, `${num(t.cost_bps, 2)}bp`);
}
