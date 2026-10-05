// 매매법 목록 #/strategies[?g=core|ds|m5] (builder C): three groups (기존 36 / 딥시크 44 / 5분봉). The 36: style filter,
// sort, search, 10 per page, each with its live record (sum of its timeframe accounts). DeepSeek: by family (17), each
// definition with its plain-Korean rule lines and the pre-registered text behind '원문 보기'. 5분봉: the reel's own card.
// HONESTY: no pass / fail hints here (no coin-flip comparison at all on this list); money has assume(); 표본 적음.
import {h, put, ui, fmt, motion, local} from "../core/pb.js";
import {DS_FAMILIES, FAMILY, DS_DEFS, DS_COMMON, EXITS, LEVERAGE, REEL} from "./strategies-defs.js";
import {DS_RAW, REEL_RAW} from "./strategies-raw.js";
import {strategyIndex} from "./strategies-calc.js";

const GROUPS = [
  {id: "core", ko: "기존 36", intro: "잠긴 매매법 36개를 15분·30분·1시간·4시간봉 계좌로 돌립니다. 기록은 그 봉 계좌들을 더한 값입니다."},
  {id: "ds", ko: "딥시크 44", intro: "딥시크 답변 200개에서 시험할 수 있는 것을 정의 44개(17계열)로 만들었습니다. 39개는 봉 4개, 세션 정의 5개는 봉 3개입니다."},
  {id: "m5", ko: "5분봉", intro: "5분봉 매매법 하나가 자기만의 청산 규칙으로 돕니다. 계단 잠금을 쓰지 않습니다."},
];
const STYLES = [{id: "", label: "전체"}, {id: "추세 따라가기", label: "추세"}, {id: "되돌림 노리기", label: "되돌림"}, {id: "섞임", label: "섞임"}];
const SORTS = [["", "기본 순서"], ["pnl", "손익 높은 순"], ["pnl-", "손익 낮은 순"], ["trades", "거래 많은 순"]];

/** One line of a record: "12승 9패 · 승률 57%" + P&L, or "거래 없음". */
function recLine(r) {
  return r.trades ? `${fmt.int(r.wins)}승 ${fmt.int(r.losses)}패 · 승률 ${fmt.pct(r.rate, 0, false)}` : "거래 없음";
}

export function listView(ctx, st) {
  const v = {g: ["core", "ds", "m5"].includes((ctx.params.query || {}).g) ? ctx.params.query.g : local.get("strat-group", "core"),
    style: local.get("strat-style", ""), sort: local.get("strat-sort", ""), fam: local.get("strat-fam", "F1"), idx: []};
  if (!GROUPS.some((g) => g.id === v.g)) v.g = "core";
  if (v.fam !== "" && !FAMILY[v.fam]) v.fam = "F1";

  const gseg = h("div");
  const intro = h("p", {class: "ink2 strat-intro"});
  const filters = h("div", {class: "stack tight"});
  const body = h("div", {class: "stack"});
  const el = h("div", {class: "stack"}, ui.card({plate: "묶음", cls: "strat-groupcard"}, gseg, intro, filters), body);

  // ---------------------------------------------------------------- the 36: searchable list
  const row = (s) => h("a", {class: "lrow click strat-row", role: "listitem", href: ctx.href("strategies", s.id)},
    h("span", {class: "rk"}, s.id.split("_")[0]),
    h("span", {class: "lname"}, s.ko),
    h("span", {class: ["ret num", fmt.tone(s.rec.pnl)]}, s.rec.trades ? fmt.money(s.rec.pnl, true) : "—"),
    h("span", {class: "meta"}, s.style ? ui.pill(s.style.replace(" 따라가기", "").replace(" 노리기", ""), "thin") : null,
      h("span", null, recLine(s.rec)), ui.smallSample(s.rec.trades), s.rec.open ? h("span", {class: "accent"}, `포지션 ${fmt.int(s.rec.open)}`) : null,
      s.rec.bust ? ui.pill(`파산 ${fmt.int(s.rec.bust)}`, "bad") : null, s.rare ? ui.pill("신호 드묾", "warn") : null));
  const coreList = ui.searchList({size: 10, row, placeholder: "매매법 이름 찾기 (예: 일목, MACD)",
    match: (s, qq) => s.ko.toLowerCase().includes(qq) || s.id.toLowerCase().includes(qq)});

  // ---------------------------------------------------------------- DeepSeek: one family at a time
  const dsRow = (s) => h("a", {class: "lrow click strat-row", role: "listitem", href: ctx.href("strategies", s.id)},
    h("span", {class: "rk"}, s.fam), h("span", {class: "lname"}, s.ko),
    h("span", {class: ["ret num", fmt.tone(s.rec.pnl)]}, s.rec.trades ? fmt.money(s.rec.pnl, true) : "—"),
    h("span", {class: "meta"}, h("span", {class: "strat-rule1"}, DS_DEFS[s.id].lines[0]), h("span", null, recLine(s.rec)), ui.smallSample(s.rec.trades)));
  const dsList = ui.searchList({size: 10, row: dsRow, placeholder: "정의 이름 찾기 (예: FVG, 피보나치)",
    match: (s, qq) => s.ko.toLowerCase().includes(qq) || s.id.toLowerCase().includes(qq) || FAMILY[s.fam].ko.toLowerCase().includes(qq)});

  // the record line of one definition card (re-filled in place when the board changes: open disclosures stay open)
  const recEls = new Map();
  function fillRec(el, s, ref) {
    put(el, ref ? h("span", {class: "pp ref"}) : null, ref ? " " : null, recLine(s.rec), " · 손익 ",
      h("b", {class: ["num", fmt.tone(s.rec.pnl)]}, s.rec.trades ? fmt.money(s.rec.pnl, true) : "—"), " ", ui.smallSample(s.rec.trades));
  }
  function recEl(s, ref) {
    const el = h("p", {class: "strat-recline"});
    fillRec(el, s, ref);
    recEls.set(s.id, {el, ref});
    return el;
  }
  function defCard(s) {
    const d = DS_DEFS[s.id];
    return ui.card({title: d.ko, sub: `${s.id} · ${s.tfs.map(fmt.tfKo).join("·") || "계좌 없음"}`, h: "h3", cls: "strat-defcard",
      acts: [h("a", {class: "btn-line", href: ctx.href("strategies", s.id)}, "자세히")]},
    h("ul", {class: "strat-lines"}, d.lines.map((t) => h("li", null, t))),
    recEl(s, true),
    ui.disclosure("원문 보기", h("pre", {class: "strat-raw"}, DS_RAW[s.id] || "")));
  }
  const dsNote = () => h("p", {class: "refnote"}, h("b", null, "참고"), " · 딥시크는 계좌마다 동전 봇과 비교하지 않습니다. 정의별 숫자는 봉 계좌를 더한 기록일 뿐 판정이 아닙니다.");

  // persistent cards: a board refresh never rebuilds them (the search text, the page and open disclosures stay)
  const coreSub = h("span", {class: "sub"});
  const coreCard = ui.card({plate: "매매법"}, coreList.el,
    h("p", {class: "muted small"}, "기록 = 봉 계좌 4개를 더한 닫힌 거래. 성격(추세·되돌림)은 과거 5년 시험에서 본 진입 방향입니다."),
    ui.assume(null, "손익은 닫힌 거래 기준"));
  coreCard.querySelector(".card-h").append(coreSub);
  const dsAllCard = ui.card({plate: "딥시크 정의 44개", sub: "계열을 고르면 규칙을 한눈에"}, dsList.el, dsNote(), ui.assume(null, "손익은 닫힌 거래 기준"));

  // ---------------------------------------------------------------- render
  function renderGroups() {
    const n = (g) => v.idx.filter((s) => s.group === g).length;
    put(gseg, ui.seg(GROUPS.map((g) => ({id: g.id, label: g.ko, title: `${fmt.int(n(g.id))}개`})), v.g, (id) => {
      v.g = id; local.set("strat-group", id);
      try { window.history.replaceState(null, "", ctx.href("strategies", null, {g: id})); } catch { /* keep the hash */ }
      render(true);
    }, {label: "묶음"}));
  }

  function renderFilters() {
    if (v.g === "core") {
      const sortSel = h("select", {class: "select", "aria-label": "순서"}, SORTS.map(([id, ko]) => h("option", {value: id}, ko)));
      sortSel.value = v.sort;
      sortSel.addEventListener("change", () => { v.sort = sortSel.value; local.set("strat-sort", v.sort); fillCore(false); });
      put(filters, h("div", {class: "row wrap strat-filters"},
        ui.seg(STYLES, v.style, (id) => { v.style = id; local.set("strat-style", id); fillCore(false); }, {label: "성격"}), h("span", {class: "grow"}), sortSel));
    } else if (v.g === "ds") {
      put(filters, ui.seg([{id: "", label: "전체"}, ...DS_FAMILIES.map((f) => ({id: f.id, label: `${f.id} ${f.ko}`}))], v.fam,
        (id) => { v.fam = id; local.set("strat-fam", id); renderBody(true); }, {label: "계열", scroll: true}));
      filters.firstChild.classList.add("strat-famseg");
    } else put(filters);
  }

  function fillCore(keep) {
    let list = v.idx.filter((s) => s.group === "core" && (!v.style || s.style === v.style));
    if (v.sort === "pnl") list = [...list].sort((a, b) => b.rec.pnl - a.rec.pnl);
    else if (v.sort === "pnl-") list = [...list].sort((a, b) => a.rec.pnl - b.rec.pnl);
    else if (v.sort === "trades") list = [...list].sort((a, b) => b.rec.trades - a.rec.trades);
    coreList.set(list, keep);
    coreSub.textContent = `${fmt.int(list.length)}개 · 누르면 차트와 조건`;
  }

  function renderBody(animate) {
    const rows = v.idx.filter((s) => s.group === v.g);
    recEls.clear();
    let kids;
    if (v.g === "core") {
      fillCore(!animate);
      kids = [coreCard];
    } else if (v.g === "ds" && !v.fam) {
      dsList.set(rows, !animate);
      kids = [dsAllCard];
    } else if (v.g === "ds") {
      const f = FAMILY[v.fam], mine = rows.filter((s) => s.fam === v.fam);
      kids = [ui.card({plate: `${f.id} ${f.ko}`, sub: `정의 ${fmt.int(mine.length)}개`}, h("p", {class: "ink2"}, f.desc)),
        h("div", {class: "strat-defs"}, mine.map(defCard)),
        ui.card({cls: "flat strat-dsfoot"}, dsNote(), ui.disclosure("딥시크 44개 공통 약속", h("ul", {class: "strat-lines small"}, DS_COMMON.map((t) => h("li", null, t)))),
          ui.assume(null, "손익은 닫힌 거래 기준"))];
    } else {
      const s = rows.find((x) => x.id === REEL.id) || {id: REEL.id, tfs: ["5m"], rec: {trades: 0, pnl: 0}};
      kids = [ui.card({title: REEL.ko, sub: `${REEL.id} · 5분`, cls: "strat-defcard strat-reel", acts: [h("a", {class: "btn-y", href: ctx.href("strategies", REEL.id)}, "자세히")]},
        h("p", {class: "ink2"}, REEL.desc),
        h("ul", {class: "strat-lines"}, REEL.lines.map((t) => h("li", null, t))),
        h("div", {class: "strat-exits"}, h("b", null, "나가는 법"), h("ul", {class: "strat-lines small"}, [...EXITS.reel, LEVERAGE.reel].map((t) => h("li", null, t)))),
        recEl(s, false),
        h("p", {class: "muted small"}, REEL.flips, " ", h("a", {href: ctx.href("board", null, {g: "m5"})}, "순위표에서 보기")),
        ui.disclosure("원문 보기", h("pre", {class: "strat-raw"}, REEL_RAW)),
        ui.assume(null, "손익은 닫힌 거래 기준"))];
    }
    put(body, ...kids);
    if (animate) motion.swap(body);
  }

  function render(animate) {
    intro.textContent = (GROUPS.find((g) => g.id === v.g) || GROUPS[0]).intro;
    renderGroups(); renderFilters(); renderBody(animate);
  }

  return {
    el,
    set() { v.idx = strategyIndex(st.board, st.list36); render(false); },
    /** A new board: records change in place (no re-animation, the search text and page stay). */
    refresh() {
      v.idx = strategyIndex(st.board, st.list36);
      if (v.g === "core") fillCore(true);
      else if (v.g === "ds" && !v.fam) dsList.set(v.idx.filter((s) => s.group === "ds"), true);
      for (const [id, x] of recEls) { const s = v.idx.find((y) => y.id === id); if (s) fillRec(x.el, s, x.ref); }
      renderGroups();
    },
    setGroup(g) { if (GROUPS.some((x) => x.id === g) && g !== v.g) { v.g = g; local.set("strat-group", g); render(true); } },
    dispose() {},
  };
}
