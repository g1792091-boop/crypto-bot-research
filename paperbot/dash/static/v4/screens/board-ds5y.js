// 순위표 › 딥시크 › 딥시크 5년 결과 (ana7b): GET /api/v4/ds5y (dash/more/ds5y.py: the 5-year test's own files,
// research/deepseek200/out/results.csv + summary.json; never recomputed). Shown ONLY while the board's DeepSeek group is
// chosen (the owners' D10 / D11: DeepSeek numbers live on the DeepSeek screen), fetched the first time it is shown.
// While the server job runs: N/342 and what will appear; absent: "서버에서 계산 중 / 아직 시작 안 함". Then per
// definition (44), for the chosen research exit and timeframe: 5-year trades, win rate, net per trade, sum, drawdown,
// before-cost result (the coin-flip yardstick: a random entry with the same exits is about zero before costs), how
// many of the three periods were positive, the gauntlet step it reached; sortable, 10 per page; next to it the live
// paper accounts of the definition (from the board: accounts, trades, win rate, median return, busts) and, as the
// baseline, the 15m-4h coin flips. HONESTY: research exits are not the live ones (the card says so); no pass words;
// small samples say so; the coin-flip line is 참고 with refNote; the paper return carries assume().
import {h, put, ui, fmt, motion, derive, local, DS_NAME_KO} from "../core/pb.js";

const TFS = [{id: "", label: "모든 봉"}, {id: "15m", label: "15분"}, {id: "30m", label: "30분"}, {id: "1h", label: "1시간"}, {id: "4h", label: "4시간"}];
const SORTS = [{id: "mean", label: "거래당 손익"}, {id: "agree", label: "세 기간 일치"}, {id: "n", label: "5년 거래 수"},
  {id: "win", label: "승률"}, {id: "paper", label: "모의 거래 수"}];
const PERIODS = ["is", "cf", "pre"];
const P_KO = {is: "1기", cf: "2기", pre: "3기"};
const C = {n: 0, win: 1, mean: 2, sum: 3, gross: 4, cost: 5, mdd: 6, ownx: 7};   // results.csv columns (ds5y.COLS)
const DS_TFS = ["15m", "30m", "1h", "4h"];
const SMALL5 = 100;          // fewer 5-year trades: '표본 적음' (rare definitions, PREREG section 2)
const SMALL_PAPER = 30;      // the verdict's own floor for an account's trades
const STAGE_KO = [["candidate", "후보"], ["stage3", "3단계까지"], ["stage2", "2단계까지"], ["stage1_top", "1단계 통과 (상위 30)"], ["stage1", "1단계 통과"]];
const pc3 = (x) => (x == null ? "—" : fmt.pct(x / 100, 3));             // research numbers are already in percent
const pc0 = (x) => (x == null ? "—" : fmt.pct(x / 100, 0));

/** One definition over the chosen exit and timeframe(s): trade-weighted means, the sums, the deepest drawdown, the
 *  periods with a positive pooled mean, the owners' 20x account's periods above 1x, and the furthest gauntlet step. */
export function aggregate(def, exit, tf) {
  const out = {n: 0, win: null, mean: null, sum: 0, gross: null, mdd: null, per: {}, pos: 0, seen: 0, ownUp: 0, ownN: 0, flags: new Set(), cfgs: 0};
  let w = 0, m = 0, g = 0;
  for (const p of PERIODS) out.per[p] = {n: 0, mean: null, _s: 0};
  for (const [key, cfg] of Object.entries(def.cfg || {})) {
    const [t, x] = key.split("|");
    if (x !== exit || (tf && t !== tf)) continue;
    out.cfgs++;
    for (const f of cfg.flags || []) out.flags.add(f);
    for (const p of PERIODS) {
      const r = (cfg.p || {})[p];
      if (!r || !r[C.n]) continue;
      const n = r[C.n];
      out.n += n;
      w += n * (r[C.win] || 0);
      m += n * (r[C.mean] || 0);
      g += n * (r[C.gross] || 0);
      out.sum += r[C.sum] || 0;
      if (r[C.mdd] != null) out.mdd = out.mdd == null ? r[C.mdd] : Math.min(out.mdd, r[C.mdd]);
      out.per[p].n += n;
      out.per[p]._s += n * (r[C.mean] || 0);
      if (r[C.ownx] != null) { out.ownN++; if (r[C.ownx] > 1) out.ownUp++; }
    }
  }
  if (out.n) { out.win = w / out.n; out.mean = m / out.n; out.gross = g / out.n; }
  for (const p of PERIODS) {
    const q = out.per[p];
    if (q.n) { q.mean = q._s / q.n; out.seen++; if (q.mean > 0) out.pos++; }
    delete q._s;
  }
  return out;
}

/** The live paper accounts of one definition (from the board), or of the coin flips: accounts, trades, wins, the
 *  median return (wallet / initial − 1, closed trades), busts. */
export function paperOf(board, pick, initial) {
  const rows = ((board && board.accounts) || []).filter(pick);
  const trades = rows.reduce((s, a) => s + (Number(a.trades) || 0), 0);
  const wins = rows.reduce((s, a) => s + (Number(a.wins) || 0), 0);
  const init = initial || 5000;
  return {accounts: rows.length, trades, wins, rate: trades ? wins / trades : null, bust: rows.filter((a) => a.bust).length,
    medRet: rows.length ? derive.median(rows.map((a) => (a.wallet ?? init) / init - 1)) : null};
}

function stageOf(flags) {
  for (const [k, ko] of STAGE_KO) if (flags.has(k)) return ko;
  return null;
}

/** ds5yCard(ctx) -> {el, update(board, gs, sel, verdictTs)}: hidden unless sel is the DeepSeek group. */
export function ds5yCard(ctx) {
  const st = {D: null, err: null, loading: false, exit: local.get("ds5-exit", "X5_TRAIL2"), tf: local.get("ds5-tf", ""),
    sort: local.get("ds5-sort", "mean"), board: null, gs: null, verdictTs: null, page: null};
  const body = h("div", {class: "ds5-body"}, motion.shimmer(4));
  const el = ui.card({plate: "딥시크 5년 결과", sub: "과거 5년 시험 · 정의 44개 · 설명용, 판정 아님", cls: "ds5-card"}, body);
  el.hidden = true;

  async function load() {
    if (st.loading || st.D) return;
    st.loading = true;
    try { st.D = await ctx.api("/api/v4/ds5y"); st.err = null; } catch (e) { st.err = e; }
    st.loading = false;
    if (ctx.alive()) { lastSig = sigOf(st.board); render(false); }
  }

  function progress(done, total, label, words) {
    const w = total ? Math.max(0, Math.min(1, done / total)) : 0;
    return h("div", {class: ["ds5-prog", w >= 1 ? "full" : ""]},
      h("div", {class: "ds5-prog-top"}, h("b", null, label), h("span", {class: "num"}, `${fmt.int(done)} / ${fmt.int(total)}`)),
      h("span", {class: "ds5-prog-t", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": String(total), "aria-valuenow": String(done), "aria-label": label},
        h("i", {style: {"--w": (w * 100).toFixed(1) + "%"}})),
      words ? h("p", {class: "note"}, words) : null);
  }

  function head(D) {
    const s = D.summary || {};
    if (D.state === "done") {
      return [progress(D.done, D.total, "5년 계산 끝", `결과 파일 ${D.source || ""}${D.file_ts ? ` · ${fmt.kst(D.file_ts)} 기록` : ""}`),
        h("p", {class: "ds5-gate"}, h("b", null, "미리 정한 관문: "),
          `설정 ${fmt.int(s.configs ?? D.done)}개 → 1단계 ${fmt.int(s.stage1 ?? 0)} → 2단계 ${fmt.int(s.stage2 ?? 0)} → 3단계 ${fmt.int(s.stage3 ?? 0)} · 전체 보정(BH) ${fmt.int(s.bh12_all ?? 0)} → 후보 ${fmt.int(s.candidate ?? 0)}개`,
          ". 세 기간 모두 플러스였던 설정 ", `${fmt.int(s.all_three_periods_positive ?? 0)}개 (342개면 우연으로도 몇 개는 나옴).`)];
    }
    const wait = D.state === "absent" ? "아직 시작 안 함 / 서버에서 계산 중" : "서버에서 계산 중";
    return [h("p", {class: "ds5-wait"}, ui.pill(wait, "warn")),
      progress(D.done || 0, D.total || 342, D.state === "absent" ? "결과 파일 없음" : "5년 계산 진행", D.absent_ko || ""),
      D.state === "absent" ? h("ul", {class: "ds5-will"},
        h("li", null, "정의 44개마다 5년(2020-01 ~ 2026-09, 세 기간) 거래 수 · 승률 · 거래당 손익 · 합계 · 낙폭"),
        h("li", null, "비용 전 손익: 동전 던지기(같은 청산으로 아무 때나 진입)와 견주는 기준"),
        h("li", null, "세 기간 중 플러스인 기간 수와 미리 정한 관문을 어디까지 갔는지"),
        h("li", null, "옆에 지금 모의 계좌의 거래 수 · 승률")) : null];
  }

  function controls() {
    const exits = (st.D.exits || []).map((x) => ({id: x.id, label: x.ko, title: x.d}));
    if (!exits.some((x) => x.id === st.exit)) st.exit = exits.length ? exits[0].id : "X5_TRAIL2";
    const ex = ui.seg(exits, st.exit, (id) => { st.exit = id; local.set("ds5-exit", id); render(true); }, {label: "연구 청산"});
    const tf = ui.seg(TFS, st.tf, (id) => { st.tf = id; local.set("ds5-tf", id); render(true); }, {label: "봉"});
    const so = h("select", {class: "select", "aria-label": "정렬"}, SORTS.map((o) => h("option", {value: o.id}, `${o.label} 순`)));
    so.value = st.sort;
    so.addEventListener("change", () => { st.sort = so.value; local.set("ds5-sort", so.value); render(true); });
    const exD = ((st.D.exits || []).find((x) => x.id === st.exit) || {}).d || "";
    return h("div", {class: "ds5-ctl"},
      h("div", {class: "ds5-lab"}, h("span", null, "연구 청산"), ex), h("div", {class: "ds5-lab"}, h("span", null, "봉"), tf),
      h("div", {class: "ds5-lab"}, h("span", null, "정렬"), so), h("p", {class: "note"}, exD));
  }

  function row(r) {
    const a = r.a, p = r.p;
    const stage = stageOf(a.flags);
    const dots = h("span", {class: "ds5-dots", title: "세 기간(1기 2021-08~2024-06 · 2기 2024-07~2026-09 · 3기 2020-01~2021-07) 중 거래당 평균이 플러스인 기간"},
      PERIODS.map((k) => h("i", {class: [a.per[k].n ? (a.per[k].mean > 0 ? "pos" : "neg") : "none"], title: `${P_KO[k]} ${a.per[k].n ? pc3(a.per[k].mean) : "거래 없음"}`})),
      h("span", null, `${fmt.int(a.pos)}/${fmt.int(a.seen)}`));
    const detail = ui.disclosure("기간·봉별 보기", detailTable(r.def));
    return h("div", {class: "ds5-row", role: "listitem"},
      h("div", {class: "ds5-name"}, h("b", null, DS_NAME_KO[r.def.id] || r.def.id), h("span", {class: "muted"}, ` ${r.def.id} · ${r.def.family_ko || r.def.family || ""}`),
        stage ? [" ", ui.pill(stage, "thin")] : null),
      h("div", {class: "ds5-5y"}, h("span", {class: "ds5-tag"}, "5년"),
        h("span", null, `${fmt.int(a.n)}건`), ui.smallSample(a.n, SMALL5),
        h("span", null, `승률 ${a.win == null ? "—" : fmt.pct(a.win / 100, 0, false)}`),
        h("span", null, "거래당 ", h("b", {class: ["num", fmt.tone(a.mean)]}, pc3(a.mean))),
        h("span", null, "비용 전 ", h("b", {class: ["num", fmt.tone(a.gross)]}, pc3(a.gross))),
        h("span", null, `합계 ${pc0(a.sum)}`), h("span", null, `낙폭 ${pc0(a.mdd)}`), dots),
      h("div", {class: "ds5-paper"}, h("span", {class: "ds5-tag"}, "모의"),
        p.accounts ? [h("span", null, `계좌 ${fmt.int(p.accounts)}`), h("span", null, `거래 ${fmt.int(p.trades)}건`),
          h("span", null, `승률 ${p.rate == null ? "—" : fmt.pct(p.rate, 0, false)}`),
          h("span", null, "수익률 중앙값 ", h("b", {class: ["num", fmt.tone(p.medRet)]}, fmt.pct(p.medRet, 2))),
          h("span", null, `파산 ${fmt.int(p.bust)}`), ui.smallSample(p.trades, SMALL_PAPER)]
          : h("span", {class: "muted"}, st.tf ? "이 봉의 모의 계좌 없음" : "모의 계좌 없음")),
      detail);
  }

  function detailTable(def) {
    const rows = [];
    for (const tf of DS_TFS) {
      if (st.tf && tf !== st.tf) continue;
      const cfg = (def.cfg || {})[`${tf}|${st.exit}`];
      if (!cfg) continue;
      rows.push({tf, cfg});
    }
    if (!rows.length) return h("p", {class: "muted"}, "이 봉에는 이 정의가 없습니다.");
    const cell = (cfg, p) => {
      const r = (cfg.p || {})[p];
      if (!r || !r[C.n]) return h("span", {class: "muted"}, "—");
      return h("span", null, h("b", {class: ["num", fmt.tone(r[C.mean])]}, pc3(r[C.mean])), h("span", {class: "muted"}, ` ${fmt.int(r[C.n])}건`));
    };
    return h("div", {class: "stack tight"},
      ui.table([{label: "봉", l: true, get: (x) => fmt.tfKo(x.tf)}, ...PERIODS.map((p) => ({label: `${P_KO[p]} 거래당`, get: (x) => cell(x.cfg, p)})),
        {label: "20배 계좌", get: (x) => { const ups = PERIODS.filter((p) => ((x.cfg.p || {})[p] || [])[C.ownx] > 1).length; return `${fmt.int(ups)}/3 이익`; }}], rows),
      h("p", {class: "note"}, "20배 계좌 = 두 분 방식(한 번에 1개, 증거금 20% × 20배)으로 기간마다 돌렸을 때 처음보다 불어난 기간 수."));
  }

  function render(anim) {
    if (el.hidden) return;
    if (st.err) { put(body, ui.errorBox(st.err, () => { st.err = null; st.D = null; load(); })); return; }
    const D = st.D;
    if (!D) { put(body, motion.shimmer(4)); return; }
    const kids = [h("p", {class: "ds5-intro ink2"}, D.note || ""), ...head(D)];
    if ((D.defs || []).length) {
      const init = (st.gs && st.gs.initial) || 5000;
      const tfOk = (a) => !st.tf || a.timeframe === st.tf;
      const rows = D.defs.map((def) => ({def, a: aggregate(def, st.exit, st.tf),
        p: paperOf(st.board, (x) => x.kind === "ds200" && x.strategy === def.id && tfOk(x), init)})).filter((r) => r.a.cfgs);
      const key = {mean: (r) => r.a.mean ?? -Infinity, agree: (r) => r.a.pos * 1e6 + (r.a.mean ?? -1e5), n: (r) => r.a.n,
        win: (r) => r.a.win ?? -Infinity, paper: (r) => r.p.trades}[st.sort] || ((r) => r.a.mean ?? -Infinity);
      rows.sort((x, y) => key(y) - key(x));
      // the scope's totals: every definition's trades together
      const N = rows.reduce((s, r) => s + r.a.n, 0);
      const wm = (f) => (N ? rows.reduce((s, r) => s + r.a.n * (r.a[f] || 0), 0) / N : null);
      const all3 = rows.filter((r) => r.a.seen === 3 && r.a.pos === 3).length;
      const flips = paperOf(st.board, (x) => x.kind === "random" && DS_TFS.includes(x.timeframe) && tfOk(x), init);
      const pg = ui.pager({size: 10, row: (r) => row(r), empty: "이 봉에는 정의가 없습니다"});
      pg.set(rows);
      kids.push(controls(),
        h("div", {class: "stats s4 ds5-stats"},
          ui.stat("정의", fmt.int(rows.length), `설정 ${fmt.int(rows.reduce((s, r) => s + r.a.cfgs, 0))}개`),
          ui.stat("5년 거래", fmt.int(N), "세 기간 합계"),
          ui.stat("거래당 손익", h("b", {class: ["num", fmt.tone(wm("mean"))]}, pc3(wm("mean"))), `비용 전 ${pc3(wm("gross"))}`),
          ui.stat("세 기간 모두 플러스", `${fmt.int(all3)} / ${fmt.int(rows.length)}`, "정의 수")),
        h("div", {class: "ds5-list", role: "list"}, pg.el),
        h("p", {class: "ds5-coin"}, h("b", null, "동전 봇 (모의, 참고) "),
          flips.accounts ? `${st.tf ? fmt.tfKo(st.tf) : "15분~4시간"} 동전 계좌 ${fmt.int(flips.accounts)}개 · 거래 ${fmt.int(flips.trades)}건 · 승률 ${flips.rate == null ? "—" : fmt.pct(flips.rate, 0, false)} · 수익률 중앙값 ${fmt.pct(flips.medRet, 2)}`
            : "동전 계좌 없음", " ", ui.smallSample(flips.trades, SMALL_PAPER)),
        h("p", {class: "note"}, D.coin_ko || ""),
        h("p", {class: "note"}, "5년 = 세 기간 합계(1기 2021-08~2024-06 고르기, 2기 2024-07~2026-09 확인, 3기 2020-01~2021-07 최종). 거래당·비용 전·합계는 레버리지 없이 진입가 대비 %. 낙폭 = 코인별 낙폭의 중앙값 중 가장 깊은 기간. 점 = 기간마다 거래당 평균이 플러스(채움)·마이너스(빈칸)."),
        ui.assume(null, "모의 칸의 수익률은 닫힌 거래 기준 (열린 포지션 손익 제외)"),
        ui.refNote(st.verdictTs, "딥시크는 계좌마다 비교하지 않고 정의·묶음 숫자만 참고로 봅니다."));
    }
    put(body, ...kids);
    if (anim) motion.swap(body);
  }

  // the board is refreshed often (polls and stream patches): repaint only when the DeepSeek / coin-flip accounts' own
  // numbers changed, so a page of the list or an open detail is not reset by an unrelated update
  const sigOf = (board) => ((board && board.accounts) || []).filter((a) => a.kind === "ds200" || a.kind === "random")
    .reduce((s, a) => s + (Number(a.trades) || 0) * 7 + (Number(a.wallet) || 0) + (a.bust ? 1e9 : 0), 0);
  let lastSig = null;
  return {
    el,
    update(board, gs, sel, verdictTs) {
      st.board = board; st.gs = gs; st.verdictTs = verdictTs || null;
      const show = sel === "ds";
      const was = !el.hidden;
      el.hidden = !show;
      if (!show) return;
      if (!st.D && !st.err) { load(); if (!was) put(body, motion.shimmer(4)); return; }
      const sig = sigOf(board);
      if (was && sig === lastSig) return;
      lastSig = sig;
      render(false);
    },
  };
}
