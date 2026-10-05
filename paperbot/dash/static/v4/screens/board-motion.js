// 순위표 motion (v4 additions, 움직임 다듬기): decorates the ranking rows that home-shared.js draws (a.home-row, the
// account id in its title) without changing that file:
//   ▲2 / ▼1   the group's return rank now vs this viewer's last visit (ui.rankMemo, localStorage; a convenience: a
//             private window shows none). Shown only on rows whose shown rank IS that rank (sorted by 수익률, all
//             timeframes), so the arrow and the number always mean the same thing. Fades in when it appears or changes.
//   a small line  each account's equity over the run (GET /api/v4/replay/sparks for the rows on screen only, cached
//             5 min here and 2 min on the server; asked when rows appear, never on a timer).
//   a tint    on a return that REALLY changed in a board update (a closed trade), once, in the change's direction.
// HONESTY: DeepSeek rows get neither arrows nor lines (group numbers only, CONTRACT section 1.3); the caption says the
// arrows are rank moves since the last visit and that short-term ranks move with luck.
import {h, put, ui, fmt, derive, motion} from "../core/pb.js";

const SPARK_TTL = 5 * 60000;
const FLASH_WINDOW = 1500;          // rows drawn this soon after a board update are the update's rows

/** rowMotion(ctx, root, {sparks}) -> {update(board, sel), note(sel)}. sparks: false = no small lines (home on a phone,
 *  where they would cut the names); the caption then does not mention them. */
export function rowMotion(ctx, root, o = {}) {
  const memo = ui.rankMemo("board-ranks");
  const base = memo.base;           // {ts, v: {account_id: return}} of the last visit, or null
  const st = {board: null, sel: "core", byId: new Map(), rank: {}, groupRank: {}, baseRank: {}, prevRet: null, curRet: {}, updAt: 0,
    prevDelta: new Map(), sparksOff: o.sparks === false, initial: 5000};
  const sparks = new Map();         // id -> {at, vals}
  let want = new Set(), timer = 0;

  const skip = (a) => !a || a.kind === "ds200";

  function decorate(row) {
    if (row.dataset.mo === "1") return;
    row.dataset.mo = "1";
    const id = row.getAttribute("title");
    const a = st.byId.get(id);
    if (!a) return;
    const ret = row.querySelector(".ret");
    const rk = row.querySelector(".rk");
    const fresh = performance.now() - st.updAt < FLASH_WINDOW;
    // the tint: a return that changed in this update
    if (fresh && ret && st.prevRet && st.prevRet[id] != null && Math.abs(st.prevRet[id] - st.curRet[id]) > 1e-9) {
      motion.flashPrice(ret, st.curRet[id] > st.prevRet[id] ? "up" : "down");      // a teal / pink glow on a real change
      // wave 2 ⑦: the strategy's character hops (profit) or slumps (loss) once on that same real change
      const fig = row.querySelector(".row-fig");
      if (fig && !skip(a) && motion.visible()) motion.play(fig, st.curRet[id] > st.prevRet[id] ? "fig-hop" : "fig-slump");
    }
    if (skip(a)) return;
    // the rank arrow (only when the row's shown rank is the group's return rank)
    if (base && rk && Number(String(rk.textContent).replace(/[^\d]/g, "")) === st.groupRank[id] && st.baseRank[id] != null && st.rank[id] != null) {
      const d = st.baseRank[id] - st.rank[id];
      const was = st.prevDelta.get(id);
      const el = ui.rankDelta(d, {title: `지난번 방문 때 ${fmt.int(st.baseRank[id])}위 → 지금 ${fmt.int(st.rank[id])}위 (묶음 안 수익률 순위)`,
        fade: d !== 0 && (was === undefined || (was !== d && fresh))});
      if (el) row.append(h("span", {class: "board-rkd"}, el));
      st.prevDelta.set(id, d);
    }
    // the small equity line
    if (ret && !st.sparksOff) {
      const hit = sparks.get(id);
      const box = h("span", {class: "board-spark", dataset: {id}});
      box.append(hit ? line(hit.vals, false) : ui.miniSpark(null, {w: 56, h: 18}));
      ret.prepend(box);
      if (!hit || Date.now() - hit.at > SPARK_TTL) need(id);
    }
  }
  const line = (vals, draw) => ui.miniSpark(vals, {w: 56, h: 18, base: st.initial, draw, label: "시작부터 지금까지 평가금 흐름"});

  function need(id) {
    want.add(id);
    clearTimeout(timer);
    timer = setTimeout(fetchSparks, 80);
  }
  async function fetchSparks() {
    const ids = [...want].slice(0, 40);
    want = new Set([...want].slice(40));
    if (!ids.length || st.sparksOff) return;
    let v;
    try { v = await ctx.api(`/api/v4/replay/sparks?ids=${encodeURIComponent(ids.join(","))}`); }
    catch (e) {
      if (e && e.status === 404) { st.sparksOff = true; for (const b of root.querySelectorAll(".board-spark")) b.remove(); }
      return;
    }
    if (!ctx.alive()) return;
    if (v && v.initial) st.initial = v.initial;
    const now = Date.now();
    for (const [id, vals] of Object.entries((v && v.series) || {})) {
      sparks.set(id, {at: now, vals});
      for (const b of root.querySelectorAll(".board-spark")) if (b.dataset.id === id) put(b, line(vals, true));
    }
    if (want.size) timer = setTimeout(fetchSparks, 80);
  }

  const mo = new MutationObserver((muts) => {
    for (const m of muts) for (const n of m.addedNodes) {
      if (!(n instanceof Element)) continue;
      if (n.matches("a.home-row")) decorate(n);
      for (const r of n.querySelectorAll("a.home-row")) decorate(r);
    }
  });
  mo.observe(root, {childList: true, subtree: true});
  ctx.track(() => { mo.disconnect(); clearTimeout(timer); });

  return {
    /** Call before the board's rows are drawn for this board / group. */
    update(board, sel) {
      st.board = board; st.sel = sel;
      st.initial = (board && board.initial) || st.initial;
      st.byId = new Map(((board && board.accounts) || []).map((a) => [a.account_id, a]));
      const rows = derive.rankedOnly(board, sel).rows;        // the rank memo and arrows: ranked accounts only
      const ret = Object.fromEntries(rows.map((a) => [a.account_id, a.ret]));
      st.prevRet = Object.keys(st.curRet).length ? st.curRet : null;
      st.curRet = Object.fromEntries(derive.ranked(board, "all").concat(derive.ranked(board, "extra")).map((a) => [a.account_id, a.ret]));
      st.groupRank = Object.fromEntries(rows.map((a, i) => [a.account_id, i + 1]));      // the rank a row shows
      st.rank = {};
      if (base) {
        // both ranks among the accounts that existed both times (a new account does not push everyone down)
        const ids = rows.map((a) => a.account_id).filter((id) => base.v[id] != null);
        st.baseRank = ui.ranksOf(base.v, ids);
        st.rank = ui.ranksOf(ret, ids);
      }
      st.updAt = performance.now();
      memo.save(Object.fromEntries(Object.entries(st.curRet).filter(([id]) => !derive.unranked(st.byId.get(id)))));
    },
    /** The caption (and, with a baseline, how many of the top 10 are still there: ranks move with luck). */
    note(sel) {
      const rows = derive.ranked(st.board, sel).filter((a) => !skip(a));
      const parts = [];
      if (base && rows.length) {
        parts.push(`▲▼ = ${fmt.ago(base.ts)} 이 화면을 봤을 때보다 묶음 안 수익률 순위가 오르고 내린 칸 수`);
        if (rows.length >= 20) {
          const ids = rows.map((a) => a.account_id).filter((id) => base.v[id] != null);
          const was = Object.entries(ui.ranksOf(base.v, ids)).filter(([, r]) => r <= 10).map(([id]) => id);
          const now = new Set(rows.slice(0, 10).map((a) => a.account_id));
          parts.push(`그때 상위 10 중 지금도 상위 10: ${fmt.int(was.filter((id) => now.has(id)).length)}개`);
        }
      } else if (rows.length) parts.push("▲▼ 순위 변화는 다음 방문부터 보입니다 (이 기기에 지금 순위를 기억해 둡니다)");
      if (!st.sparksOff && rows.length) parts.push("작은 선 = 시작부터 지금까지 평가금 흐름 (5분마다 기록, 열린 포지션 포함)");
      if (sel === "ds") parts.push("딥시크는 계좌마다 선·순위 변화를 표시하지 않습니다 (묶음 숫자만)");
      if (!parts.length) return null;
      return h("p", {class: "note board-monote"}, parts.join(" · "), base ? " · 짧은 기간 순위는 운으로도 크게 움직입니다 (판정 아님)." : "");
    },
  };
}
