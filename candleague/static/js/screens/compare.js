// #/compare 5계좌 비교: each pick's five accounts side by side (후보 · 1/4 크기 · 청산만 바꾼 기본값 · 기본값 · 동전), one
// row per pick, the best of the five marked, and what the comparisons say together (how many picks beat their own
// 기본값, 동전, 청산만; whether 1/4 size shook less). A cell opens that account. HONESTY: a mark is a comparison of means
// per trade over the same days, not a verdict; fewer than 30 trades says 적음.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {ROLES, ROLE_KO, ROLE_DESC, TFS, tfKo} from "../labels.js";
import * as WK from "../whykit.js";
import {ROLE_RULE} from "../rulekit.js";

export async function mount(el, ctx) {
  try { await ctx.meta(); } catch (e) { /* codes */ }
  const q = ctx.params.query || {};
  const st = {kind: q.kind || "all", tf: q.tf || "all", sort: q.sort || "name"};
  const save = () => ctx.setQuery(Object.fromEntries(Object.entries(st).filter(([k, v]) => !(v === "all" || (k === "sort" && v === "name")))));
  const sum = h("div"), grid = h("div");
  el.append(
    ui.screenHead("5계좌 비교", "같은 후보에서 갈라진 다섯 계좌를 같은 기간으로 나란히"),
    h("div", {class: "dl-fields"},
      ui.field("종류", ui.seg([{id: "all", label: "전체"}, {id: "core", label: "기존 36"}, {id: "ds", label: "딥시크"}], st.kind, (v) => { st.kind = v; save(); paint(); }, {label: "종류"})),
      ui.field("봉", ui.seg([{id: "all", label: "전체"}, ...TFS.map((t) => ({id: t, label: tfKo(t)}))], st.tf, (v) => { st.tf = v; save(); paint(); }, {label: "봉"})),
      ui.field("순서", ui.seg([{id: "name", label: "매매법"}, {id: "cand", label: "후보 평균"}, {id: "gap", label: "기본값과 차이"}], st.sort, (v) => { st.sort = v; save(); paint(); }, {label: "순서"}))),
    ui.card({plate: "한눈에", sub: "같은 기간 · 같은 시세 · 거래 한 번 평균으로 비교 (참고)"}, sum),
    ui.card({plate: "후보마다 5계좌", sub: "칸 = 거래 한 번 평균 · 거래 수 · 승률 · ★ = 같은 크기 넷(1/4 빼고) 중 가장 좋음 · 칸을 누르면 그 계좌 · 후보 아래 작은 줄 = 후보 계좌가 나간 이유 · 수수료·펀딩 · 최장 연패 (최근 200번까지)"}, grid),
    ui.card({plate: "계좌 5개가 뭔가요", acts: h("a", {class: "btn-line", href: "#/rules"}, "익절·손절·배수 →")}, h("dl", {class: "kv"}, ROLES.map((r) => h("div", null, h("dt", null, LK.roleChip(r)),
      h("dd", null, ROLE_DESC[r], h("br"), h("small", {class: "muted"}, `진입: ${ROLE_RULE[r].nums} · 익절·손절: ${ROLE_RULE[r].exit} · 크기: ${ROLE_RULE[r].size} · 방향: ${ROLE_RULE[r].dir}`)))))));

  let INS = null;
  function paint() {
    const d = LK.league();
    if (!d || !d.accounts) { put(grid, ui.none("준비 중")); return; }
    WK.loadInsight(ctx).then((x) => { if (x !== INS && ctx.alive()) { INS = x; paint(); } }).catch(() => { /* no short line */ });
    const ix = LK.index(d);
    let picks = ix.cands.filter((c) => (st.kind === "all" || c.kind === st.kind) && (st.tf === "all" || c.tf === st.tf));
    const gap = (c) => { const b = ix.sets[c.id].base; return c.mean_ret != null && b && b.mean_ret != null ? c.mean_ret - b.mean_ret : null; };
    if (st.sort === "cand") picks = [...picks].sort((a, b) => (b.mean_ret ?? -9) - (a.mean_ret ?? -9));
    else if (st.sort === "gap") picks = [...picks].sort((a, b) => (gap(b) ?? -9) - (gap(a) ?? -9));
    else picks = [...picks].sort((a, b) => LK.stratKo(a.name).localeCompare(LK.stratKo(b.name), "ko") || TFS.indexOf(a.tf) - TFS.indexOf(b.tf));
    const count = (role) => {
      const ok = picks.filter((c) => LK.better(c, ix.sets[c.id][role]) === true).length;
      const n = picks.filter((c) => LK.better(c, ix.sets[c.id][role]) != null).length;
      return [ok, n];
    };
    const [b1, b2] = count("base"), [f1, f2] = count("flip"), [x1, x2] = count("exitonly");
    const calmer = picks.filter((c) => { const qq = ix.sets[c.id].quarter; return qq && qq.max_dd != null && c.max_dd != null && c.trades; });
    const calm = calmer.filter((c) => ix.sets[c.id].quarter.max_dd < c.max_dd).length;
    put(sum, h("div", {class: "stats cl-stats4"},
      ui.stat("후보 > 기본값", `${fmt.int(b1)} / ${fmt.int(b2)}`, "커스텀값+커스텀 청산이 지금 규칙봇 방식보다 나은 후보"),
      ui.stat("후보 > 동전", `${fmt.int(f1)} / ${fmt.int(f2)}`, "같은 시각 방향만 동전인 계좌보다 나은 후보 (참고)"),
      ui.stat("후보 > 청산만", `${fmt.int(x1)} / ${fmt.int(x2)}`, "청산만 바꾼 것보다 나음 = 숫자(커스텀값) 덕"),
      ui.stat("1/4이 덜 흔들림", `${fmt.int(calm)} / ${fmt.int(calmer.length)}`, "1/4 크기의 최대 낙폭이 후보보다 작은 후보 (1/4은 증거금이 작아 한 번 평균의 크기가 달라서 평균으로는 비교하지 않음)")),
    h("p", {class: "note"}, "읽는 법: 후보 > 청산만이면 좋아진 몫은 숫자(커스텀값) 덕, 청산만 > 기본값이면 익절·손절 덕입니다. 동전보다 낫지 않으면 방향을 맞힌 게 아니라 운일 수 있습니다."));
    put(grid, h("div", {class: "tbl-wrap"}, h("table", {class: "tbl cl-cmp"},
      h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "후보"), ROLES.map((r) => h("th", {scope: "col"}, LK.roleChip(r))))),
      h("tbody", null, picks.map((c) => {
        const set = ix.sets[c.id];
        // the best of the full-size accounts: 1/4 크기 puts a quarter of the margin at risk (its leverage re-chosen by
        // the same rule), so its per-trade result is on another scale (a size check, never "the best")
        const means = ROLES.map((r) => (r !== "quarter" && set[r] && set[r].trades && set[r].mean_ret != null ? set[r].mean_ret : null));
        const real = means.filter((m) => m != null);
        const best = real.length >= 2 ? Math.max(...real) : null;           // a lone account is never "the best"
        return h("tr", null, h("td", {class: "l"}, h("a", {href: `#/account/${encodeURIComponent(c.id)}`, class: "cl-plain"}, LK.pickName(c)),
          h("div", {class: "cl-exit muted"}, h("a", {class: "cl-plain", href: `#/rules?pick=${encodeURIComponent(c.id)}`, title: "익절·손절·배수 자세히"}, c.exit_ko)),
          WK.whyShort(INS && INS.accounts ? INS.accounts[c.id] : null)),
        ROLES.map((r, i) => {
          const a = set[r];
          if (!a) return h("td", {class: "muted"}, "—");
          const star = best != null && means[i] === best && means.filter((m) => m === best).length === 1;
          return h("td", {class: ["cl-cell", star ? "best" : ""]}, h("a", {href: `#/account/${encodeURIComponent(a.id)}`, class: "cl-plain", title: `${ROLE_KO[r]} 계좌 자세히`},
            h("div", null, star ? h("span", {class: "cl-star", title: "1/4 뺀 같은 크기 넷 중 가장 좋음"}, "★ ") : null, LK.ret(a.mean_ret, {hiddenIf: LK.dsHidden(a)})),
            h("small", {class: "muted"}, `${fmt.int(a.trades)}번 · ${LK.winTxt(a)}${a.trades && a.trades < 30 ? " · 적음" : ""}${a.bust ? " · 파산" : ""}`)));
        }));
      })))));
  }
  ctx.onLeague(paint);
}
