// #/compare 5계좌 비교: each pick's five accounts side by side (후보 · 1/4 크기 · 청산만 바꾼 기본값 · 기본값 · 동전), one
// row per pick, the best of the five marked, and what the comparisons say together (how many picks beat their own
// 기본값, 동전, 청산만; whether 1/4 size shook less). A cell opens that account. HONESTY: a mark is a comparison of means
// per trade over the same days, not a verdict; fewer than 30 trades says 적음.
// The owner-exit league (owners 10/12, the snapshot's lineup: 지금 청산 · 이동평균 이탈 · 고정 익절 ROE 50% · 큰 수익 반납
// 보호 · 주말 쉬는 계좌, labels.js applyLineup) shows the same table with its own accounts: per pick its accounts on the same
// signals, the cell's big number the 잔고 수익률 (exits change how many trades there are, so the wallet is the fair
// comparison), with trades, win rate and median hold hours; per kind, how many picks it is ahead of 지금 청산 and the
// pooled numbers of each pool. DeepSeek money only as the snapshot allows (hidden: counts and hold hours only).
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {ROLES, ROLE_KO, ROLE_SHORT, ROLE_DESC, TFS, tfKo, lineupOn, compareKo, KIND_LONG} from "../labels.js";
import * as WK from "../whykit.js";
import {roleRule} from "../rulekit.js";

export async function mount(el, ctx) {
  try { await ctx.meta(); } catch (e) { /* codes */ }
  const q = ctx.params.query || {};
  const st = {kind: q.kind || "all", tf: q.tf || "all", sort: q.sort || "name"};
  const save = () => ctx.setQuery(Object.fromEntries(Object.entries(st).filter(([k, v]) => !(v === "all" || (k === "sort" && v === "name")))));
  const sum = h("div"), grid = h("div"), what = h("div"), sortBox = h("span"), head = h("div");
  const sumCard = ui.card({plate: "한눈에", sub: "같은 기간 · 같은 시세 · 거래 한 번 평균으로 비교 (참고)"}, sum);
  const gridCard = ui.card({plate: "후보마다 5계좌", sub: "칸 = 거래 한 번 평균 · 거래 수 · 승률 · ★ = 같은 크기 넷(1/4 빼고) 중 가장 좋음 · 칸을 누르면 그 계좌 · 후보 아래 작은 줄 = 후보 계좌가 나간 이유 · 수수료·펀딩 · 최장 연패 (최근 200번까지)"}, grid);
  const whatCard = ui.card({plate: "계좌 5개가 뭔가요", acts: h("a", {class: "btn-line", href: "#/rules"}, "익절·손절·배수 →")}, what);
  el.append(head,
    h("div", {class: "dl-fields"},
      ui.field("종류", ui.seg([{id: "all", label: "전체"}, {id: "core", label: "기존 36"}, {id: "ds", label: "딥시크"}], st.kind, (v) => { st.kind = v; save(); paint(); }, {label: "종류"})),
      ui.field("봉", ui.seg([{id: "all", label: "전체"}, ...TFS.map((t) => ({id: t, label: tfKo(t)}))], st.tf, (v) => { st.tf = v; save(); paint(); }, {label: "봉"})),
      ui.field("순서", sortBox, {label: "순서"})),
    sumCard, gridCard, whatCard);

  let INS = null, mode = null;
  function frame() {
    const owner = lineupOn();
    if (mode === owner) return;
    mode = owner;
    const n = ROLES.length;
    put(head, ui.screenHead(compareKo(), owner
      ? "같은 후보의 계좌들을 같은 신호 · 같은 기간으로 나란히 (청산 방법이 다릅니다)"
      : "같은 후보에서 갈라진 다섯 계좌를 같은 기간으로 나란히"));
    const sorts = owner ? [{id: "name", label: "매매법"}, {id: "cand", label: "지금 청산 잔고"}, {id: "gap", label: "가장 큰 차이"}]
      : [{id: "name", label: "매매법"}, {id: "cand", label: "후보 평균"}, {id: "gap", label: "기본값과 차이"}];
    if (!sorts.some((x) => x.id === st.sort)) st.sort = "name";
    put(sortBox, ui.seg(sorts, st.sort, (v) => { st.sort = v; save(); paint(); }, {label: "순서"}));
    setSub(sumCard, owner ? `같은 기간 · 같은 시세 · 계좌마다 ${LK.startUsd()}에서 시작 · 비교 기준은 ${ROLE_KO.cand} (참고)` : "같은 기간 · 같은 시세 · 거래 한 번 평균으로 비교 (참고)");
    setPlate(gridCard, owner ? `후보마다 계좌 (종류 ${n}가지)` : "후보마다 5계좌");
    setSub(gridCard, owner
      ? `칸 = 잔고 수익률 (${LK.startUsd()} 대비, 닫힌 거래까지) · 거래 수 · 승률 · 보유 시간 중앙값 · ★ = 그 후보 계좌들 중 잔고가 가장 많음 · 칸을 누르면 그 계좌`
      : "칸 = 거래 한 번 평균 · 거래 수 · 승률 · ★ = 같은 크기 넷(1/4 빼고) 중 가장 좋음 · 칸을 누르면 그 계좌 · 후보 아래 작은 줄 = 후보 계좌가 나간 이유 · 수수료·펀딩 · 최장 연패 (최근 200번까지)");
    setPlate(whatCard, owner ? `계좌 종류 ${n}가지가 뭔가요` : "계좌 5개가 뭔가요");
    put(what, h("dl", {class: ["kv", owner ? "kv-kinds" : ""]}, ROLES.map((r) => {
      const x = roleRule(r);
      return h("div", null, h("dt", null, LK.roleChip(r)), h("dd", null, ROLE_DESC[r], h("br"),
        h("small", {class: "muted"}, `진입: ${x.nums} · 익절·손절: ${x.exit} · 크기: ${x.size} · 방향: ${x.dir}`)));
    })), owner ? h("p", {class: "note"}, `${LK.OWNER_SAME_SIGNALS} ${LK.OWNER_SAME_RULE} ${LK.OWNER_STOP_DIFF}`) : null);
  }

  function paint() {
    const d = LK.league();
    frame();
    if (!d || !d.accounts) { put(grid, ui.none("준비 중")); return; }
    WK.loadInsight(ctx).then((x) => { if (x !== INS && ctx.alive()) { INS = x; paint(); } }).catch(() => { /* no short line */ });
    const ix = LK.index(d);
    let picks = ix.cands.filter((c) => (st.kind === "all" || c.kind === st.kind) && (st.tf === "all" || c.tf === st.tf));
    if (mode) { paintOwner(d, ix, picks); return; }
    const gap = (c) => { const b = ix.sets[c.id].base; return c.mean_ret != null && b && b.mean_ret != null ? c.mean_ret - b.mean_ret : null; };
    if (st.sort === "cand") picks = [...picks].sort((a, b) => (b.mean_ret ?? -9) - (a.mean_ret ?? -9));
    else if (st.sort === "gap") picks = [...picks].sort((a, b) => (gap(b) ?? -9) - (gap(a) ?? -9));
    else picks = byName(picks);
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
        return h("tr", null, pickCell(c),
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

  function pickCell(c) {
    return h("td", {class: "l"}, h("a", {href: `#/account/${encodeURIComponent(c.id)}`, class: "cl-plain"}, LK.pickName(c)),
      h("div", {class: "cl-exit muted"}, h("a", {class: "cl-plain", href: `#/rules?pick=${encodeURIComponent(c.id)}`, title: "익절·손절·배수 자세히"}, c.exit_ko)),
      WK.whyShort(INS && INS.accounts ? INS.accounts[c.id] : null));
  }

  /** The owner-exit league: per pick its accounts (ROLES from the lineup), the cell's big number the 잔고 수익률. */
  function paintOwner(d, ix, picks) {
    const others = ROLES.filter((r) => r !== "cand");
    const wr = (a) => (a && !LK.dsHidden(a) && a.wallet != null && Number.isFinite(Number(a.wallet)) ? LK.walletRet(a) : null);
    const spread = (c) => {
      const v = ROLES.map((r) => wr(ix.sets[c.id][r])).filter((x) => x != null);
      return v.length >= 2 ? Math.max(...v) - Math.min(...v) : null;
    };
    if (st.sort === "cand") picks = [...picks].sort((a, b) => (wr(b) ?? -9) - (wr(a) ?? -9));
    else if (st.sort === "gap") picks = [...picks].sort((a, b) => (spread(b) ?? -9) - (spread(a) ?? -9));
    else picks = byName(picks);
    // ahead of 지금 청산 on the wallet (both known, either with a closed trade; a tie counts as neither)
    const ahead = (r) => {
      let up = 0, n = 0;
      for (const c of picks) {
        const a = ix.sets[c.id][r], x = wr(a), y = wr(c);
        if (x == null || y == null || !((a && a.trades) || c.trades) || x === y) continue;
        n += 1; up += x > y ? 1 : 0;
      }
      return [up, n];
    };
    const hidden = picks.filter((c) => LK.dsHidden(c)).length;
    const pool = (kind) => {
      const p = (((d.watch || {}).pools) || {})[kind];
      if (!p || !p.picks) return null;
      return h("div", {class: "cl-cmppool"}, h("b", null, KIND_LONG[kind]),
        h("div", {class: "tbl-wrap"}, h("table", {class: "tbl"},
          h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "계좌"), h("th", {scope: "col"}, "거래"), h("th", {scope: "col"}, "승률"),
            h("th", {scope: "col"}, "한 번 평균"), h("th", {scope: "col"}, "보유 중앙"), h("th", {scope: "col"}, "8시간 넘게"))),
          h("tbody", null, ROLES.map((r) => {
            const x = (p.roles || {})[r] || {n: 0, wins: 0};
            const hd = (p.hold || {})[r] || {};
            return h("tr", null, h("td", {class: "l"}, LK.roleChip(r)), h("td", {class: "num"}, `${fmt.int(x.n)}번`),
              h("td", {class: "num muted"}, x.n ? fmt.pct((100 * x.wins) / x.n, false, 0) : "—"), h("td", null, LK.ret(x.mean, {hiddenIf: !p.money})),
              h("td", {class: "num"}, hd.median_h == null ? "—" : `${fmt.num(hd.median_h, 1)}시간`),
              h("td", {class: "num muted"}, hd.share_gt8 == null ? "—" : fmt.pct(hd.share_gt8 * 100, false, 0)));
          })))));
    };
    put(sum, h("div", {class: "stats cl-stats4"}, others.map((r) => {
      const [up, n] = ahead(r);
      return ui.stat(`${ROLE_SHORT[r]} > ${ROLE_SHORT.cand}`, `${fmt.int(up)} / ${fmt.int(n)}`, `${ROLE_KO[r]} 계좌의 잔고가 ${ROLE_KO.cand}보다 많은 후보`);
    })),
    pool("core"), pool("ds"),
    h("p", {class: "note"}, `읽는 법: 같은 후보의 계좌를 같은 신호로 나란히 돌립니다 (청산 방법이 다르고, 손절 거리도 다를 수 있습니다). 잔고가 ${ROLE_KO.cand}보다 많으면 그 청산이 이 기간에는 나았던 것이고, 보유 시간이 짧으면 포지션을 오래 들고 있지 않은 것입니다. 거래 수가 적은 동안은 운이 큽니다 (판정 아님).`,
      hidden ? ` 딥시크 후보 ${fmt.int(hidden)}개는 금액 숨김 설정이라 세지 않았습니다.` : ""));
    put(grid, h("div", {class: "tbl-wrap"}, h("table", {class: "tbl cl-cmp"},
      h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "후보"), ROLES.map((r) => h("th", {scope: "col"}, LK.roleChip(r))))),
      h("tbody", null, picks.map((c) => {
        const set = ix.sets[c.id];
        const vals = ROLES.map((r) => (set[r] && (set[r].trades || set[r].open) ? wr(set[r]) : null));
        const real = vals.filter((v) => v != null);
        const best = real.length >= 2 ? Math.max(...real) : null;
        return h("tr", null, pickCell(c), ROLES.map((r, i) => {
          const a = set[r];
          if (!a) return h("td", {class: "muted", title: r === "cand" ? null : "이 후보에는 이 종류 계좌가 없습니다 (그 매매법에 자체 구조 · 가격 코드가 없거나, 후보의 손절이 이미 같아 따로 두지 않음)"}, "—");
          const star = best != null && vals[i] === best && vals.filter((v) => v === best).length === 1;
          const w = wr(a);
          const t = w == null ? null : fmt.pct(w * 100, true, 1);
          const hold = a.hold && a.hold.median != null ? ` · 보유 ${fmt.num(a.hold.median, 1)}h` : "";
          return h("td", {class: ["cl-cell", star ? "best" : ""]}, h("a", {href: `#/account/${encodeURIComponent(a.id)}`, class: "cl-plain", title: `${ROLE_KO[r]} 계좌 자세히`},
            h("div", null, star ? h("span", {class: "cl-star", title: "이 후보 계좌들 중 잔고가 가장 많음"}, "★ ") : null,
              LK.dsHidden(a) ? h("span", {class: "muted", title: "딥시크 금액 숨김 (CANDLEAGUE_DS_MONEY=0)"}, "숨김")
                : t == null ? h("span", {class: "muted"}, "—") : h("span", {class: ["num", fmt.tone(w, t)]}, t)),
            h("small", {class: "muted"}, `${fmt.int(a.trades)}번 · ${LK.winTxt(a)}${hold}${a.trades && a.trades < 30 ? " · 적음" : ""}${a.open ? " · 보유 중" : ""}${a.bust ? " · 파산" : ""}`)));
        }));
      })))));
  }
  ctx.onLeague(paint);
}

const byName = (picks) => [...picks].sort((a, b) => LK.stratKo(a.name).localeCompare(LK.stratKo(b.name), "ko") || TFS.indexOf(a.tf) - TFS.indexOf(b.tf));
function setPlate(card, text) { const p = card.querySelector(".plate"); if (p) p.textContent = text; }
function setSub(card, text) { const p = card.querySelector(".sub"); if (p) p.textContent = text; }
