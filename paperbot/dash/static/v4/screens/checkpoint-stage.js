// 30일 판정 › 판정 무대 (wave 2 part B, ranked #4). Three pieces for checkpoint.js:
//   seatsCard()  좌석표: every judged account is one seat, filled by closed trades / 30 (neutral accent, never a pass or
//                a fail). From day 3 the part the account would add by the verdict at today's pace is drawn lighter, and
//                a seat that would reach 30 at that pace gets a dashed edge. Head: "판정 날 30건 넘을 것 약 N~M개" (the
//                pace ± one Poisson sigma). Seats are sorted by trades inside each group; DeepSeek seats carry no name
//                (counts only, CONTRACT rule 3).
//   powerCard()  30일 판정으로 알 수 있는 것: /api/v4/power (research/power/out/power.json) per timeframe: if an account
//                really earned +0 / 1 / 2 / 5 / 10 % per trade, its chance to pass by day 30 / 60 / 90.
//   stamp(v), luckDots(v)  only after /api/checkpoint says ready: the stamp on the result and the 'luck' picture.
import {h, ui, fmt, motion, local} from "../core/pb.js";
import {judgedTfs, MIN_TRADES} from "./home-shared.js";

const DAY = 86400000;
const SEAT_GROUPS = [{kind: "strategy", ko: "기존 36", named: true}, {kind: "ds200", ko: "딥시크", named: false},
  {kind: "reel", ko: "5분봉 단타", named: true}];

/** The pace numbers: elapsed share of the run and whether a projection is shown yet (from day 3). */
export function pace(summary, verdictTs, now = Date.now()) {
  const start = summary && summary.start;
  if (!start || !verdictTs || verdictTs <= start) return null;
  const el = Math.max(0, now - start), tot = verdictTs - start;
  return {elapsed: el, total: tot, factor: el > 0 ? tot / el : null, show: el >= 2 * DAY && now < verdictTs};
}

/** For trades n at pace factor f: the projection and its low / high (± sqrt(n), a Poisson count's one sigma). */
export function project(n, f) {
  if (!f) return {mid: n, lo: n, hi: n};
  const sd = Math.sqrt(Math.max(0, n));
  return {mid: n * f, lo: Math.max(n, (n - sd) * f), hi: (n + sd) * f};
}

export function seatsCard() {
  const head = h("p", {class: "ck-seat-head"});
  const blocks = h("div", {class: "ck-seat-blocks"});
  const legend = h("div", {class: "ck-seat-legend", "aria-hidden": "true"},
    h("span", null, h("i", {class: "ck-seat", style: {"--f": "60%", "--p": "60%"}}), "채운 만큼 = 거래 수 / 30"),
    h("span", null, h("i", {class: "ck-seat", style: {"--f": "35%", "--p": "80%"}}), "옅은 부분 = 지금 속도로 판정 날까지"),
    h("span", null, h("i", {class: "ck-seat proj", style: {"--f": "45%", "--p": "100%"}}), "점선 = 지금 속도면 30건"),
    h("span", null, h("i", {class: "ck-seat full", style: {"--f": "100%", "--p": "100%"}}), "꽉 참 = 30건 넘음"),
    h("span", null, "파산한 계좌는 거래가 더 늘지 않아 미리 그리지 않음"));
  const card = ui.card({plate: "판정 무대", sub: "좌석표 · 진행 상황, 판정 아님"}, head, blocks, legend,
    h("p", {class: "muted home-small"}, `한 칸 = 판정받는 계좌 하나. 거래 ${MIN_TRADES}건을 채워야 판정을 받고, 못 채우면 '보류'입니다. 칸 색은 거래 수일 뿐 잘하고 못함이 아닙니다. 지금 속도는 바뀔 수 있어 범위로만 씁니다.`));
  const prevFull = new Set();
  let painted = false;
  card.update = (board, summary, verdictTs) => {
    if (!board) return;
    const p = pace(summary, verdictTs);
    const rows = board.accounts || [];
    let reach = {lo: 0, hi: 0, now: 0, n: 0};
    const kids = [];
    for (const g of SEAT_GROUPS) {
      const tfs = judgedTfs(board, g.kind);
      const mine = rows.filter((a) => a.kind === g.kind && tfs.includes(a.timeframe))
        .sort((x, y) => (y.trades || 0) - (x.trades || 0) || String(x.account_id).localeCompare(String(y.account_id)));
      if (!mine.length) continue;
      let full = 0;
      const seats = mine.map((a) => {
        const n = a.trades || 0;
        // a bust account trades no more: its count stays where it is (no pace projection)
        const pr = p && p.show && !a.bust ? project(n, p.factor) : {mid: n, lo: n, hi: n};
        if (n >= MIN_TRADES) full += 1;
        reach.now += n >= MIN_TRADES ? 1 : 0;
        reach.lo += pr.lo >= MIN_TRADES ? 1 : 0;
        reach.hi += pr.hi >= MIN_TRADES ? 1 : 0;
        reach.n += 1;
        const f = Math.min(1, n / MIN_TRADES), pp = Math.min(1, Math.max(f, pr.mid / MIN_TRADES));
        const cls = ["ck-seat", n >= MIN_TRADES ? "full" : p && p.show && pr.mid >= MIN_TRADES ? "proj" : ""];
        const el = h("i", {class: cls, style: {"--f": `${Math.round(f * 100)}%`, "--p": `${Math.round(pp * 100)}%`},
          title: g.named ? `${fmt.acctName(a)} · 거래 ${fmt.int(n)}건` : null});
        if (painted && n >= MIN_TRADES && !prevFull.has(a.account_id)) motion.flash(el);
        if (n >= MIN_TRADES) prevFull.add(a.account_id);
        return el;
      });
      kids.push(h("div", {class: "ck-seat-grp"},
        h("div", {class: "ck-seat-gh"}, h("b", null, g.ko), h("span", {class: "muted"},
          `${tfs.map(fmt.tfKo).join("·")} · ${fmt.int(mine.length)}석 · 30건 넘음 ${fmt.int(full)}`)),
        h("div", {class: "ck-seats", role: "img", "aria-label": `${g.ko} ${mine.length}개 중 거래 30건 넘은 계좌 ${full}개`}, seats)));
    }
    blocks.replaceChildren(...kids);
    if (!reach.n) head.replaceChildren(ui.empty("판정받을 계좌가 아직 없습니다"));
    else if (p && p.show) {
      head.replaceChildren(h("span", null, "지금 속도라면 판정 날 거래 30건을 넘을 계좌 "),
        h("b", {class: "num"}, reach.lo === reach.hi ? `약 ${fmt.int(reach.lo)}개` : `약 ${fmt.int(reach.lo)}~${fmt.int(reach.hi)}개`),
        h("span", {class: "muted"}, ` / ${fmt.int(reach.n)}개 (지금 ${fmt.int(reach.now)}개 · 참고)`));
    } else {
      head.replaceChildren(h("span", null, "지금 거래 30건을 넘은 계좌 "), h("b", {class: "num"}, `${fmt.int(reach.now)}개`),
        h("span", {class: "muted"}, ` / ${fmt.int(reach.n)}개 · 판정 날까지의 속도는 3일째부터 그립니다`));
    }
    painted = true;
  };
  return card;
}

// ---------------------------------------------------------------- what a 30-day verdict can tell
const TF_LABEL = {"15m": "15분", "30m": "30분", "1h": "1시간", "5m": "5분봉 단타"};
/** A probability in words: "0%", "1% 미만" (0 < p < 0.5 %), "14%". */
const pctTxt = (v) => (v == null ? "—" : v > 0 && v < 0.005 ? "1% 미만" : fmt.pct(v, 0, false));

export function powerCard(ctx) {
  const lead = h("p", {class: "ck-pw-lead"});
  const segSlot = h("div");
  const grid = h("div", {class: "ck-pw"});
  const foot = h("div", {class: "stack tight"});
  const card = ui.card({plate: "30일 판정으로 알 수 있는 것", sub: "판정 규칙이 얼마나 엄격한가 · 코드 계산"}, lead, segSlot, grid, foot);
  let d = null, tf = local.get("ck-pw-tf", "15m");
  const paint = () => {
    if (!d || !d.ready) {
      lead.replaceChildren(ui.notYet(d ? "계산 파일 없음" : "수집 전", d && d.note));
      segSlot.replaceChildren(); grid.replaceChildren(); foot.replaceChildren(h("p", {class: "muted home-small"}, (d && d.note) || "읽는 중"));
      return;
    }
    const tfs = Object.keys(d.tfs || {}).filter((k) => TF_LABEL[k]);
    if (!tfs.includes(tf)) tf = tfs[0];
    segSlot.replaceChildren(ui.seg(tfs.map((k) => ({id: k, label: TF_LABEL[k]})), tf, (id) => { tf = id; local.set("ck-pw-tf", id); paint(); },
      {label: "봉 고르기", scroll: true}));
    const x = d.tfs[tf];
    const r5 = x.rows.find((r) => Math.abs(r.edge - 0.05) < 1e-9);
    const r1 = x.rows.find((r) => Math.abs(r.edge - 0.01) < 1e-9);
    const sch = x.reel ? d.reel : d.core;
    lead.replaceChildren(
      h("span", null, `${TF_LABEL[tf]} 계좌가 정말로 같은 봉 동전 봇보다 거래마다 +5%씩 더 벌어도 30일에 1차 합격할 확률은 `),
      h("b", {class: "num"}, r5 ? pctTxt(r5.d30) : "—"),
      h("span", null, r1 ? `, +1%라면 ${pctTxt(r1.d30)}입니다.` : "입니다."));
    const head = h("div", {class: "ck-pw-row ck-pw-h", "aria-hidden": "true"}, h("span", null, "진짜 실력 (동전 봇보다, 거래당)"),
      ...[30, 60, 90].map((k) => h("span", null, `${k}일까지`)));
    const bar = (v) => h("span", {class: "ck-pw-c"}, h("i", {style: {"--w": `${Math.round(Math.max(0, Math.min(1, v || 0)) * 100)}%`}}),
      h("b", {class: "num"}, pctTxt(v)));
    grid.replaceChildren(head, ...x.rows.map((r) => h("div", {class: "ck-pw-row", role: "listitem"},
      h("span", {class: "ck-pw-k"}, r.edge === 0 ? "실력 없음 (+0%)" : `+${fmt.num(r.edge * 100, 0)}%`), bar(r.d30), bar(r.d60), bar(r.d90))));
    grid.setAttribute("role", "list");
    foot.replaceChildren(
      h("p", {class: "muted home-small"}, `${TF_LABEL[tf]}: 한 달 거래 약 ${fmt.int(x.trades_per_30d)}건 · 같은 봉 동전 봇의 거래당 평균 ${fmt.pct(x.coin_flip_mean_roe, 1)} (수수료 포함).`
        + (sch && sch.alpha != null ? ` 판정 묶음 ${fmt.int(sch.family)}개 · 오류 한도 ${fmt.pct(sch.alpha, 1, false)} · 동전 봇 ${fmt.int(sch.n_bots)}개.` : "")),
      d.deepseek ? h("p", {class: "muted home-small"}, String(d.deepseek)) : null,
      h("p", {class: "muted home-small"}, "확률이 낮다는 것 = 30일 판정에서 '합격 0개'가 나와도 '좋은 매매법이 없다'는 증거가 되지 못한다는 뜻입니다. 판정이 아니라 규칙의 엄격함입니다."),
      ui.disclosure("계산 가정 보기", h("ul", {class: "ck-out"}, (d.assumptions || []).map((t) => h("li", null, String(t))),
        h("li", null, String(d.note || "")))));
  };
  card.load = async () => {
    try { d = await ctx.api("/api/v4/power"); } catch (e) {
      if (e && e.name === "AbortError") return;
      d = {ready: false, note: e && e.status === 404 ? "서버가 아직 이 계산을 보내지 않습니다" : "읽지 못했습니다"};
    }
    if (ctx.alive()) paint();
  };
  paint();
  return card;
}

// ---------------------------------------------------------------- after the verdict only
/** The stamp on the result card (only once /api/checkpoint is ready). */
export function stamp(v) {
  return h("span", {class: "ck-stamp", role: "img", "aria-label": "판정 완료"}, h("b", null, "판정"), h("small", null, `${v.day ?? 30}일째`));
}

/** '운으로 붙는 수': one dot per account that passed the luck test; the first ⌈lucky_expected⌉ drawn hollow (dashed). */
export function luckDots(v) {
  const n = Math.max(0, Math.min(400, Number(v.luck_passed) || 0));
  const lucky = Math.max(0, Math.min(n, Math.ceil(Number(v.lucky_expected) || 0)));
  if (!n) return h("p", {class: "muted home-small"}, "운 시험을 통과한 계좌가 없습니다.");
  return h("div", {class: "stack tight"},
    h("div", {class: "ck-luck", role: "img", "aria-label": `운 시험 통과 ${n}개 중 운만으로 통과했을 수 있는 수 많아야 ${lucky}개`},
      Array.from({length: n}, (_, i) => h("i", {class: i < lucky ? "lucky" : ""}))),
    h("p", {class: "muted home-small"}, `점 하나 = 운 시험을 통과한 계좌 하나 (${fmt.int(n)}개). 점선 점 ${fmt.int(lucky)}개 = 이 가운데 실력 없이 운만으로 통과했을 수 있는 수 (많아야 ${fmt.num(Number(v.lucky_expected) || 0, 1)}개, 올림). 어느 계좌가 그 운인지는 알 수 없습니다.`));
}
