// 조합 성과 › 합친 규칙 실험 (/api/v4/combo/rules): a merged rule measured as ONE rule on the recorded paper entries.
//   같이 신호 줄 때만 (both)  A's trades where B gave the same coin + side within A's bar length before A went in
//   B를 거르개로 (filter)      A's trades only when B's latest signal on that coin was the same side
//   N개 중 K개 (vote)          members' trades when at least K members agreed (each one's signal lives one of its bars)
//   봉 합의 (tf)               a strategy's shorter-timeframe trades when its longer timeframe's latest signal agreed
// Each row: trades, win rate, mean net ROE, P&L on the members' own exits, next to A alone, the trades it dropped and the
// coin flips (alone and with the same filter, 참고). The approximation is said in plain words: each member keeps its own
// exits and only recorded entries are filtered; B's side reads the signal log (signals an account skipped while busy
// count); A's skipped signals that the rule would have wanted have no exit and are only counted. State in the address.
import {h, put, ui, fmt, motion, local} from "../core/pb.js";
import {loadUnits, unitIndex, verdictTs} from "./combo-kit.js";

const KINDS = [
  {id: "both", label: "같이 신호 줄 때만", q: "A와 B가 같이 신호 줄 때만 들어갔다면"},
  {id: "filter", label: "B를 거르개로", q: "A에 B를 거르개로 붙였다면"},
  {id: "vote", label: "N개 중 K개", q: "여러 매매법 중 K개 이상 같은 방향일 때만 들어갔다면"},
  {id: "tf", label: "같은 매매법 봉 합의", q: "짧은 봉 거래를 긴 봉이 같은 방향일 때만 했다면"},
];
const TFS = ["15m", "30m", "1h", "4h"];
const okKind = (k) => (KINDS.some((x) => x.id === k) ? k : "both");

export function rulesTab(env) {
  const {ctx} = env;
  const saved = local.get("combo-rules", {});
  const q0 = env.query();
  const st = {kind: okKind(q0.kind || saved.kind), a: q0.a || saved.a, b: q0.b || saved.b, m: q0.m || saved.m,
    k: Number(q0.k || saved.k || 2), s: q0.s || saved.s || "all", lo: q0.lo || saved.lo || "1h", hi: q0.hi || saved.hi || "4h", gen: 0, idx: null, strats: []};
  const ctl = h("div", {class: "stack tight"});
  const body = h("div", {class: "stack"});
  const el = h("div", {class: "stack cb-rules"}, ctl, body);

  const stratSel = (val, onChange, o = {}) => {
    const sel = h("select", {class: "select", "aria-label": o.label || "매매법"},
      o.all ? h("option", {value: "all"}, "36개 전부 더해서") : null,
      st.strats.map((x) => h("option", {value: x.id}, x.name_ko)));
    sel.value = val;
    sel.addEventListener("change", () => onChange(sel.value));
    return sel;
  };
  const tfSel = (val, onChange, o = {}) => {
    const sel = h("select", {class: "select", "aria-label": o.label || "봉"}, o.any ? h("option", {value: ""}, "봉 4개 전부") : null,
      (o.tfs || TFS).map((t) => h("option", {value: t}, `${fmt.tfKo(t)}봉`)));
    sel.value = val || "";
    sel.addEventListener("change", () => onChange(sel.value));
    return sel;
  };
  const split = (key) => { const i = String(key || "").lastIndexOf("@"); return i < 0 ? [key, ""] : [key.slice(0, i), key.slice(i + 1)]; };

  function defaults() {
    const ids = st.strats.map((x) => x.id);
    const ok = (k) => { const [s0] = split(k); return ids.includes(s0); };
    if (!ok(st.a) || !split(st.a)[1]) st.a = `${ids[0]}@1h`;
    if (!ok(st.b)) st.b = ids[1] || ids[0];
    const ms = String(st.m || "").split(",").filter(ok);
    st.m = (ms.length >= 2 ? ms : ids.slice(0, 3).map((x) => `${x}@1h`)).slice(0, 6).join(",");
    if (st.s !== "all" && !ids.includes(st.s)) st.s = "all";
    if (!TFS.includes(st.lo)) st.lo = "1h";
    if (!TFS.includes(st.hi) || TFS.indexOf(st.hi) <= TFS.indexOf(st.lo)) st.hi = TFS[Math.min(3, TFS.indexOf(st.lo) + 1)];
    const n = st.m.split(",").length;
    st.k = Math.max(1, Math.min(n, st.k || 2));
  }

  function controls() {
    const kseg = ui.seg(KINDS.map((k) => ({id: k.id, label: k.label})), st.kind, (id) => { st.kind = id; changed(); }, {label: "규칙 고르기", scroll: true});
    const rows = [];
    if (st.kind === "both" || st.kind === "filter") {
      const [as, at] = split(st.a), [bs, bt] = split(st.b);
      rows.push(h("div", {class: "cb-mrow"}, h("span", {class: "cb-k"}, "A"), stratSel(as, (v) => { st.a = `${v}@${at || "1h"}`; changed(); }, {label: "A 매매법"}),
        tfSel(at, (v) => { st.a = `${as}@${v}`; changed(); }, {label: "A 봉"}), h("span", {class: "muted"}, "의 진입을")));
      rows.push(h("div", {class: "cb-mrow"}, h("span", {class: "cb-k"}, "B"), stratSel(bs, (v) => { st.b = bt ? `${v}@${bt}` : v; changed(); }, {label: "B 매매법"}),
        tfSel(bt, (v) => { st.b = v ? `${bs}@${v}` : bs; changed(); }, {label: "B 봉", any: true}),
        h("span", {class: "muted"}, st.kind === "both" ? "의 신호로 거름" : "의 최근 신호 방향으로 거름")));
    } else if (st.kind === "vote") {
      const ms = st.m.split(",");
      ms.forEach((key, i) => {
        const [ss, tt] = split(key);
        rows.push(h("div", {class: "cb-mrow"}, h("span", {class: "cb-k"}, `${i + 1}`),
          stratSel(ss, (v) => { ms[i] = `${v}@${tt || "1h"}`; st.m = ms.join(","); changed(); }, {label: `구성원 ${i + 1} 매매법`}),
          tfSel(tt, (v) => { ms[i] = `${ss}@${v}`; st.m = ms.join(","); changed(); }, {label: `구성원 ${i + 1} 봉`}),
          ms.length > 2 ? h("button", {class: "cb-x", type: "button", "aria-label": `구성원 ${i + 1} 빼기`, onclick: () => { ms.splice(i, 1); st.m = ms.join(","); st.k = Math.min(st.k, ms.length); changed(); }}, "✕") : null));
      });
      const ksel = h("select", {class: "select", "aria-label": "K"}, ms.map((_x, i) => h("option", {value: String(i + 1)}, `${i + 1}개 이상`)));
      ksel.value = String(st.k);
      ksel.addEventListener("change", () => { st.k = Number(ksel.value); changed(); });
      rows.push(h("div", {class: "cb-mrow"}, h("span", {class: "cb-k"}, "K"), ksel, h("span", {class: "muted"}, `같은 방향일 때 (${fmt.int(ms.length)}개 중)`),
        ms.length < 6 ? h("button", {class: "btn-line", type: "button", onclick: () => { const ids = st.strats.map((x) => x.id); const next = ids.find((x) => !ms.some((m) => m.startsWith(x + "@"))) || ids[0]; ms.push(`${next}@1h`); st.m = ms.join(","); changed(); }}, "+ 구성원") : null));
    } else {
      rows.push(h("div", {class: "cb-mrow"}, h("span", {class: "cb-k"}, "매매법"), stratSel(st.s, (v) => { st.s = v; changed(); }, {label: "매매법", all: true})));
      rows.push(h("div", {class: "cb-mrow"}, h("span", {class: "cb-k"}, "봉"), tfSel(st.lo, (v) => { st.lo = v; changed(); }, {label: "짧은 봉", tfs: TFS.slice(0, 3)}),
        h("span", {class: "muted"}, "거래를"), tfSel(st.hi, (v) => { st.hi = v; changed(); }, {label: "긴 봉", tfs: TFS.slice(TFS.indexOf(st.lo) + 1)}),
        h("span", {class: "muted"}, "신호 방향으로 거름")));
    }
    put(ctl, ui.card({plate: "합친 규칙 실험", sub: "기록된 진입으로 계산한 근사 · 설명용, 판정 아님"}, kseg, ...rows));
  }

  function query() {
    const q = {kind: st.kind};
    if (st.kind === "both" || st.kind === "filter") Object.assign(q, {a: st.a, b: st.b});
    else if (st.kind === "vote") Object.assign(q, {m: st.m, k: String(st.k)});
    else Object.assign(q, {s: st.s, lo: st.lo, hi: st.hi});
    return q;
  }
  function changed() {
    defaults();
    local.set("combo-rules", {kind: st.kind, a: st.a, b: st.b, m: st.m, k: st.k, s: st.s, lo: st.lo, hi: st.hi});
    env.setQuery(query());
    controls();
    load();
  }

  async function load() {
    const g = ++st.gen;
    put(body, ui.card({plate: "결과", sub: "계산 중"}, motion.shimmer(4)));
    let d;
    try { d = await ctx.api(`/api/v4/combo/rules?${new URLSearchParams(query()).toString()}`); } catch (e) {
      if (g !== st.gen || !ctx.alive()) return;
      put(body, ui.card({plate: "결과"}, e && e.detail ? h("p", {class: "an-warn"}, String(e.detail)) : ui.errorBox(e, () => load())));
      return;
    }
    if (g !== st.gen || !ctx.alive()) return;
    if (d && d.pending) {
      put(body, ui.card({plate: "결과", sub: "계산 중"}, h("p", {class: "muted"}, d.note || "서버가 계산하는 중입니다."), motion.shimmer(3)));
      ctx.timeout(() => { if (g === st.gen) load(); }, 2000);
      return;
    }
    if (d && d.error) { put(body, ui.card({plate: "결과"}, h("p", {class: "muted"}, String(d.error)))); return; }
    paint(d);
  }

  const ROW_HELP = {rule: "규칙이 남긴 거래", alone: "거르기 전 전부", dropped: "규칙이 뺀 거래", flip_rule: "동전 봇 진입에 같은 거르개 (참고)", flip_all: "같은 봉 동전 봇 전부 (참고)"};
  function paint(d) {
    const rows = d.rows || [];
    const rule = rows.find((r) => r.id === "rule") || {};
    const head = KINDS.find((k) => k.id === d.kind) || KINDS[0];
    const early = (rule.trades || 0) < (d.small_n || 20);
    const list = h("div", {class: "cb-rrows", role: "table", "aria-label": "규칙 결과"},
      h("div", {class: "cb-rr cb-rrh", role: "row"}, ["", "거래", "승률", "평균 순 ROE", "손익 합"].map((x) => h("span", {role: "columnheader"}, x))),
      rows.map((r) => h("div", {class: ["cb-rr", r.id], role: "row"},
        h("span", {class: "cb-rn", role: "cell"}, h("b", null, r.label_ko), h("small", null, ROW_HELP[r.id] || "")),
        h("span", {class: "num", role: "cell"}, h("i", null, "거래 "), `${fmt.int(r.trades)}건`, r.small && r.trades ? [" ", ui.pill("표본 적음", "thin")] : null),
        h("span", {class: "num", role: "cell"}, h("i", null, "승률 "), r.win_rate == null ? "—" : fmt.pct(r.win_rate, 0, false)),
        h("span", {class: ["num", fmt.tone(r.mean_roe, fmt.pct(r.mean_roe, 1))], role: "cell"}, h("i", null, "평균 순 ROE "), r.mean_roe == null ? "—" : fmt.pct(r.mean_roe, 1)),
        h("span", {class: ["num", r.pnl == null ? "muted" : fmt.tone(r.pnl, fmt.money(r.pnl))], role: "cell"}, h("i", null, "손익 합 "),
          r.trades && r.pnl != null ? fmt.money(r.pnl, true) : "—"))));
    const out = [ui.card({plate: head.label, sub: d.kind_ko && d.kind_ko !== head.label ? d.kind_ko : null},
      h("h2", {class: "an-q"}, head.q),
      h("p", {class: "an-read"}, h("b", null, "규칙 "), d.window_ko || ""),
      early ? h("p", {class: "cb-small"}, ui.pill("표본 적음", "thin"), ` 규칙이 남긴 거래 ${fmt.int(rule.trades || 0)}건 · 아직 판단하기 이릅니다`) : null,
      list,
      h("p", {class: "an-note"}, "평균 순 ROE = 거래마다 증거금 대비 손익(수수료·펀딩 뺀 뒤)의 평균. 손익 합 = 그 거래들의 실제 모의 손익을 그대로 더한 것 (각자 자기 청산). ",
        d.flip_money_ko || ""),
      ui.assume(), ui.refNote(verdictTs()))];
    const notes = [h("p", null, h("b", null, "근사입니다. "), d.approx_ko || ""), h("p", null, d.signals_ko || "")];
    if (d.busy_passed != null) notes.push(h("p", null, `A가 다른 거래 중이었거나 늦어 들어가지 못한 신호 중 이 규칙을 통과한 것 ${fmt.int(d.busy_passed)}건은 청산 기록이 없어 위 숫자에 없습니다.`));
    if (d.duplicates) notes.push(h("p", null, `같은 코인·같은 방향이 이미 열려 있던 겹친 진입 ${fmt.int(d.duplicates)}건은 하나로 셌습니다.`));
    notes.push(h("p", {class: "muted"}, `지금 ${fmt.num(d.run_days, 1)}일째 · 신호 기록 ${fmt.int(d.signal_rows || 0)}줄 (기존 36·동전 봇·릴스)`));
    out.push(ui.card({plate: "어떻게 셌나"}, h("div", {class: "cb-how"}, notes)));
    if (d.per_strategy) out.push(perCard(d));
    put(body, ...out);
    motion.swap(body);
  }

  function perCard(d) {
    const pg = ui.pager({size: 8, row: (p) => h("div", {class: "lrow an-row", role: "listitem"},
      h("span", {class: "rk"}, fmt.tfKo(d.lo)), h("span", {class: "lname an-wrap"}, p.name_ko),
      h("span", {class: "ret num"}, `${fmt.int(p.rule.trades)}/${fmt.int(p.alone.trades)}건`),
      h("span", {class: "meta"}, h("span", null, `합의 승률 ${p.rule.win_rate == null ? "—" : fmt.pct(p.rule.win_rate, 0, false)}`),
        h("span", null, `혼자 승률 ${p.alone.win_rate == null ? "—" : fmt.pct(p.alone.win_rate, 0, false)}`),
        h("span", {class: fmt.tone(p.rule.mean_roe, fmt.pct(p.rule.mean_roe, 1))}, `합의 평균 ROE ${p.rule.mean_roe == null ? "—" : fmt.pct(p.rule.mean_roe, 1)}`),
        !p.alone.trades ? h("span", null, "거래 없음") : p.rule.small ? ui.pill("표본 적음", "thin") : null))});
    pg.set(d.per_strategy);
    return ui.card({plate: "매매법마다", sub: `${fmt.tfKo(d.lo)} 거래 중 ${fmt.tfKo(d.hi)}와 같은 방향이던 것 / 전부 · 이름 순 (순위 아님)`}, pg.el);
  }

  (async () => {
    put(ctl, ui.card({plate: "합친 규칙 실험"}, motion.shimmer(2)));
    let d;
    try { d = await loadUnits(ctx); } catch (e) {
      if (!ctx.alive()) return;
      put(ctl, ui.card({plate: "합친 규칙 실험"}, ui.errorBox(e, () => location.reload())));
      return;
    }
    if (!ctx.alive()) return;
    st.idx = unitIndex(d);
    st.strats = (d.strategies || []).map((x) => ({id: x.id, name_ko: x.name_ko || fmt.stratKo(x.id)}));
    if (!st.strats.length) { put(ctl, ui.card({plate: "합친 규칙 실험"}, ui.empty("아직 매매법 계좌가 없습니다."))); return; }
    changed();
  })();

  return {
    el,
    update(q) {
      if (!st.strats.length) return;
      Object.assign(st, {kind: okKind(q.kind), a: q.a || st.a, b: q.b || st.b, m: q.m || st.m, k: Number(q.k || st.k), s: q.s || st.s, lo: q.lo || st.lo, hi: q.hi || st.hi});
      changed();
    },
    dispose() { st.gen++; },
  };
}
