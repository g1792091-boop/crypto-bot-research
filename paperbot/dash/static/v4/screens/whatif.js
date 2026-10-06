// 만약 실험실 (ana7b): #/whatif[?strategy=<one of the 36>][&tf=15m|30m|1h|4h][&set=<setting id>]. "규칙을 바꿨다면?" for
// the 36 (all of them or one, all timeframes or one), read only from what was really tested:
//   GET /api/v4/whatif        the controls (tested values only), the tested combinations (each names its 5-year arm and
//                             its nightly shadow), the 5-year side for the scope (research/levstop, research/exitstyle,
//                             research/paper_rules coin flips; dash/more/whatiflab.py)
//   GET /api/v4/whatif/paper  the nightly shadows of the scope and of the coin flips (background: {pending} -> again in 3 s)
// The sliders snap to tested values; a combination nobody tested says "이 조합은 시험한 적 없음" with the nearest tested
// ones as buttons. Today's locked rule is the reference column everywhere; the coin flips sit next to it (참고).
// HONESTY: a big caveat card first (picking the best after the fact overfits; the locked rules do not change); no
// verdict words or colours (the sign colours only say up / down); small samples say so with a filling bar; DeepSeek
// is never read here (its numbers live on its own screen).
import {h, put, ui, fmt, motion} from "../core/pb.js";
import {progressBar} from "./analysis-kit.js";

const DIMS = ["stop", "tp", "lock", "time", "lev"];
const DIM_KO = {stop: "손절 폭", tp: "익절 방식", lock: "첫 잠금", time: "시간 청산", lev: "레버리지·비중"};
const FIXED_TP = new Set(["tp1R", "tp1.5R", "tp2R", "tp3R"]);
const TFS = [{id: "", label: "모든 봉"}, {id: "15m", label: "15분"}, {id: "30m", label: "30분"}, {id: "1h", label: "1시간"}, {id: "4h", label: "4시간"}];
const LEV_ROWS = [["tiers", "지금 단계"], ["10", "10배·20%"], ["20", "20배·20%"], ["30", "30배·30%"], ["40", "40배·40%"], ["50", "50배·40%"]];
const STOP_COLS = [1.5, 2, 2.5, 3];
const TP_STRIP = [["ladder", "사다리"], ["tp1R", "1R"], ["tp1.5R", "1.5R"], ["tp2R", "2R"], ["tp3R", "3R"], ["ladder_tp2R", "사다리+2R"]];
const NO_FIVE_KO = {
  lock: "첫 잠금 15·20·30%는 5년 결과 파일이 없습니다 (5년 실험실 관문의 lock_start 시험으로만 확인하는 항목).",
  time: "시간 청산은 5년에 비교한 적이 없습니다 (매일 밤 그림자로만 봄).",
  lev: "증거금 = 배수만큼(50배·50%)은 5년에 없습니다. 가장 가까운 시험: 50배·40%.",
};
const STOP_KEY = {1.5: "1.5", 2: "2.0", 2.5: "2.5", 3: "3.0"};     // levstop's arm spelling ("<lev>|2.0")
const FIVE_MIN = 100;          // fewer 5-year trades in the scope: '표본 적음' (one strategy on 4h has a few dozen)
let current = null;            // the mounted screen's target setter (update() uses it)
const pctp = (x, d = 3) => (x == null ? "—" : `${fmt.num(x * 100, d, true)}%p`);
const pc = (x, d = 2) => (x == null ? "—" : fmt.pct(x, d));
const share = (a, b) => (b ? `${fmt.int(a)}/${fmt.int(b)}` : "—");

export async function mount(el, ctx) {
  ctx.setTitle("만약 실험실");
  const q = ctx.params.query || {};
  const st = {strategy: q.strategy || "", tf: q.tf || "", setId: q.set || null, D: null, P: null, sel: null, gen: 0, pgen: 0,
    verdictTs: null};

  const links = h("span", {class: "row wrap wi-links"},
    h("a", {class: "btn-line", href: ctx.href("analysis", "shadows")}, "분석 › 그림자 비교 →"));
  el.append(ui.screenHead("만약 실험실", "규칙을 바꿨다면? 시험한 설정만 고를 수 있습니다 · 설명용, 판정 아님", links));

  const caveatText = h("p", {class: "wi-cav-t"});
  const caveat = ui.card({plate: "먼저 읽어 주세요", cls: "wi-caveat"},
    h("p", {class: "wi-big"}, "고르고 견주어 보는 곳입니다. 30일 규칙은 바뀌지 않습니다."), caveatText);
  const targetBody = h("div", {class: "wi-target"});
  const target = ui.card({plate: "대상", sub: "기존 36만 (딥시크는 딥시크 화면에서)"}, targetBody);
  const ctrlBody = h("div", {class: "wi-ctrls"});
  const status = h("div", {class: "wi-status", role: "status", "aria-live": "polite"});
  const ruleLine = h("p", {class: "wi-rule"});
  const resetBtn = h("button", {type: "button", class: "btn-line", onclick: () => { st.sel = {...st.D.current}; paintControls(); paintResults(true); }}, "지금 규칙으로 되돌리기");
  const ctrl = ui.card({plate: "설정 고르기", sub: "시험한 값에만 멈춥니다", acts: [resetBtn]}, ruleLine, ctrlBody, status);
  const fiveBody = h("div", {class: "wi-res"});
  const fiveCard = ui.card({plate: "5년 결과", sub: "과거 5년 · 코드 계산"}, fiveBody);
  const paperBody = h("div", {class: "wi-res"});
  const paperCard = ui.card({plate: "이번 실험", sub: "모의 계좌 · 밤 점검 그림자"}, paperBody);
  const coinBody = h("div", {class: "wi-res"});
  const coinCard = ui.card({plate: "동전 봇과 견주기", sub: "참고"}, coinBody);
  const grid = h("div", {class: "wi-grid"}, h("div", {class: "wi-col"}, target, ctrl), h("div", {class: "wi-col"}, fiveCard, paperCard, coinCard));
  const body = h("div", {class: "stack wi-page"}, motion.shimmer(5, true));
  el.append(body);

  // ---------------------------------------------------------------- data
  const qs = () => {
    const p = new URLSearchParams();
    if (st.strategy) p.set("strategy", st.strategy);
    if (st.tf) p.set("tf", st.tf);
    const s = p.toString();
    return s ? `?${s}` : "";
  };
  function remember() {
    const cur = st.D && matchSetting(st.sel);
    const query = {strategy: st.strategy || null, tf: st.tf || null, set: cur && cur.paper !== "base" ? cur.id : null};
    try { window.history.replaceState(null, "", ctx.href("whatif", null, query)); } catch { /* keep the hash */ }
  }
  async function load() {
    const g = ++st.gen;
    let D;
    try { D = await ctx.api(`/api/v4/whatif${qs()}`); } catch (e) {
      if (!ctx.alive() || g !== st.gen) return;
      if (e && e.status === 400 && (st.strategy || st.tf)) { st.strategy = ""; st.tf = ""; remember(); load(); return; }
      put(body, ui.errorBox(e, () => load()));
      return;
    }
    if (!ctx.alive() || g !== st.gen) return;
    const first = !st.D;
    st.D = D;
    if (first) {
      st.sel = {...D.current};
      const pre = st.setId && (D.settings || []).find((x) => x.id === st.setId);
      if (pre) for (const k of DIMS) st.sel[k] = pre[k] == null ? st.sel[k] : pre[k];
      put(body, caveat, grid);
      caveatText.textContent = D.caveat_ko || "";
      ruleLine.textContent = D.rule_ko || "";
    }
    paintTarget();
    paintControls();
    paintResults(!first);
    loadPaper();
  }
  async function loadPaper() {
    const g = ++st.pgen;
    st.P = null;
    paintPaper();
    let P;
    try { P = await ctx.api(`/api/v4/whatif/paper${qs()}`); } catch (e) {
      if (!ctx.alive() || g !== st.pgen) return;
      st.P = {ready: false, why: "그림자 기록을 불러오지 못했습니다", err: true};
      paintPaper(); paintCoin();
      return;
    }
    if (!ctx.alive() || g !== st.pgen) return;
    if (P && P.pending) { st.P = {pending: true}; paintPaper(); ctx.timeout(() => { if (g === st.pgen) loadPaper(); }, 3000); return; }
    st.P = P;
    paintPaper(); paintCoin();
  }

  // ---------------------------------------------------------------- 대상
  function paintTarget() {
    const D = st.D;
    const pick = h("select", {class: "select wi-pick", "aria-label": "매매법 고르기"},
      h("option", {value: ""}, "기존 36 전체"),
      (D.strategies || []).map((s) => h("option", {value: s.id}, `${s.ko} (${s.id})`)));
    pick.value = st.strategy || "";
    pick.addEventListener("change", () => { st.strategy = pick.value; remember(); load(); });
    const tfSeg = ui.seg(TFS, st.tf || "", (id) => { st.tf = id; remember(); load(); }, {label: "봉 고르기"});
    const sc = D.scope || {};
    put(targetBody, h("label", {class: "wi-lab"}, h("span", null, "매매법"), pick), h("div", {class: "wi-lab"}, h("span", null, "봉"), tfSeg),
      h("p", {class: "note"}, `5년 칸: ${(D.five_year || {}).cells_ko || "—"}`),
      sc.strategy ? h("a", {class: "btn-line wi-strat", href: ctx.href("strategies", sc.strategy)}, `${sc.name_ko} 매매법 페이지 →`) : null);
  }

  // ---------------------------------------------------------------- the controls (tested values only)
  function slider(dim, opts) {
    const i0 = Math.max(0, opts.findIndex((o) => o.v === st.sel[dim]));
    const disabled = dim === "lock" && FIXED_TP.has(st.sel.tp);
    const val = h("b", {class: "wi-val"}, disabled ? "없음" : opts[i0].ko);
    const inp = h("input", {type: "range", class: "wi-range", min: "0", max: String(opts.length - 1), step: "1", value: String(i0),
      disabled: disabled || null, "aria-label": DIM_KO[dim], "aria-valuetext": opts[i0].ko});
    inp.addEventListener("input", () => {
      const o = opts[Number(inp.value)] || opts[0];
      st.sel[dim] = o.v;
      val.textContent = o.ko;
      inp.setAttribute("aria-valuetext", o.ko);
      paintTicks();
      paintResults(true);
    });
    const ticks = h("div", {class: "wi-ticks", style: {"--n": String(opts.length)}});
    const paintTicks = () => put(ticks, opts.map((o, i) => h("button", {type: "button", class: ["wi-tick", o.v === st.sel[dim] && !disabled ? "on" : "", o.now ? "now" : ""],
      disabled: disabled || null, title: o.d || o.ko, onclick: () => { inp.value = String(i); inp.dispatchEvent(new Event("input")); }},
      h("span", null, o.ko), o.now ? h("i", null, "지금") : null)));
    paintTicks();
    return h("div", {class: ["wi-ctl", disabled ? "off" : ""]},
      h("div", {class: "wi-ctl-h"}, h("span", {class: "wi-k"}, DIM_KO[dim]), val),
      inp, ticks,
      disabled ? h("p", {class: "note"}, "고정 익절에는 계단 잠금이 없어 첫 잠금을 고를 수 없습니다.") : null,
      dim === "lev" ? h("p", {class: "note"}, "지금 규칙 = 좋은 자리 50배·50% → 40배·40%, 보통 30배·30% → 20배·20%. 나머지는 모든 거래를 그 배수·증거금으로.") : null);
  }
  function segCtl(dim, opts) {
    const cur = opts.find((o) => o.v === st.sel[dim]) || opts[0];
    const seg = ui.seg(opts.map((o) => ({id: String(o.v), label: o.now ? `${o.ko} · 지금` : o.ko, title: o.d})), String(cur.v), (id) => {
      const o = opts.find((x) => String(x.v) === id);
      if (!o) return;
      st.sel[dim] = o.v;
      if (dim === "tp" && !FIXED_TP.has(o.v) && st.sel.lock == null) st.sel.lock = st.D.current.lock;
      paintControls();
      paintResults(true);
    }, {label: DIM_KO[dim]});
    return h("div", {class: "wi-ctl"}, h("div", {class: "wi-ctl-h"}, h("span", {class: "wi-k"}, DIM_KO[dim]), h("b", {class: "wi-val"}, cur.ko)),
      seg, cur.d ? h("p", {class: "note"}, cur.d) : null);
  }
  function paintControls() {
    const C = st.D.controls || {};
    put(ctrlBody, slider("stop", C.stop || []), segCtl("tp", C.tp || []), slider("lock", C.lock || []), segCtl("time", C.time || []),
      slider("lev", C.lev || []));
  }

  // ---------------------------------------------------------------- matching the chosen values to a tested setting
  function sameVal(a, b) { return a === b || (typeof a === "number" && typeof b === "number" && Math.abs(a - b) < 1e-9); }
  function matchSetting(sel) {
    const fixed = FIXED_TP.has(sel.tp);
    return (st.D.settings || []).find((s) => sameVal(s.stop, sel.stop) && s.tp === sel.tp && (fixed ? s.lock == null : sameVal(s.lock, sel.lock))
      && s.time === sel.time && s.lev === sel.lev) || null;
  }
  function changed(sel) {
    const C = st.D.controls || {}, cur = st.D.current;
    return DIMS.filter((k) => !(k === "lock" && FIXED_TP.has(sel.tp)) && !sameVal(sel[k], cur[k]))
      .map((k) => `${DIM_KO[k]} ${((C[k] || []).find((o) => sameVal(o.v, sel[k])) || {}).ko || sel[k]}`);
  }
  function nearest(sel) {
    const dist = (s) => DIMS.filter((k) => !(k === "lock" && (s.lock == null || FIXED_TP.has(sel.tp))) && !sameVal(s[k], sel[k])).length;
    // fewest controls apart first; among equals, one with both a 5-year result and a nightly shadow first
    const score = (s) => dist(s) * 10 - (s.five ? 1 : 0) - (s.paper ? 1 : 0);
    const all = (st.D.settings || []).filter((s) => s.paper !== "base").sort((a, b) => score(a) - score(b));
    const best = all.length ? dist(all[0]) : 0;
    return all.filter((s) => dist(s) === best).slice(0, 3);          // only the closest ones (one control apart, usually)
  }
  function apply(s) {
    for (const k of DIMS) st.sel[k] = s[k] == null ? st.sel[k] : s[k];
    paintControls();
    paintResults(true);
  }

  // ---------------------------------------------------------------- results
  function paintResults(anim) {
    const s = matchSetting(st.sel);
    const ch = changed(st.sel);
    if (!s) {
      const near = nearest(st.sel);
      put(status, h("p", {class: "wi-untested"}, ui.pill("이 조합은 시험한 적 없음", "warn"), " ", `바꾼 것: ${ch.join(" · ")}`),
        h("p", {class: "note"}, "5년 표는 레버리지 × 손절 폭만 같이 바꿔 봤고, 밤 그림자는 한 번에 하나만 바꿉니다. 가까운 시험 설정:"),
        h("div", {class: "row wrap wi-near"}, near.map((x) => h("button", {type: "button", class: "btn-line", onclick: () => apply(x)},
          x.ko, h("span", {class: "muted"}, ` (${[x.five ? "5년" : null, x.paper ? "그림자" : null].filter(Boolean).join("·")})`)))));
    } else {
      put(status, h("p", {class: "wi-chosen"}, s.paper === "base" ? ui.pill("지금 규칙", "accent") : ui.pill("시험한 설정", "thin"), " ",
        s.paper === "base" ? "아래는 지금 규칙의 숫자입니다. 하나를 바꾸면 옆에 나란히 나옵니다." : `바꾼 것: ${ch.join(" · ")}`,
        " ", h("span", {class: "muted"}, `(${[s.five ? "5년 결과 있음" : "5년 없음", s.paper ? "밤 그림자 있음" : "밤 그림자 없음"].join(" · ")})`)));
    }
    paintFive(s);
    paintPaper();
    paintCoin();
    if (anim) { motion.swap(fiveBody); motion.swap(paperBody); motion.swap(coinBody); }
    remember();
  }

  // the comparison table: a label and one column (지금 규칙 alone) or three (지금 · 이 설정 · 차이; phones put the label on
  // its own line above the three numbers). A cell is text, a Node, or [text, tone].
  function cmpTable(heads, rows) {
    return h("div", {class: ["wi-cmp", `n${heads.length}`], role: "list"},
      h("div", {class: "wi-cmp-r wi-cmp-h", "aria-hidden": "true"}, h("span", null, ""), heads.map((x) => h("span", null, x))), rows);
  }
  function cmpRow(label, ...cells) {
    return h("div", {class: "wi-cmp-r", role: "listitem"}, h("span", {class: "wi-cmp-k"}, label),
      cells.map((c, i) => (c instanceof Node ? h("span", null, c) : h(i === 1 ? "b" : "span", {class: ["num", Array.isArray(c) ? c[1] || "" : ""]},
        Array.isArray(c) ? c[0] : c ?? ""))));
  }
  function armOf(key) {
    if (!key) return null;
    const i = key.indexOf(":");
    const src = key.slice(0, i), arm = key.slice(i + 1);
    const F = (st.D.five_year || {})[src] || {};
    return F.ready ? {src, arm, v: (F.arms || {})[arm] || null, F} : {src, arm, v: null, F};
  }
  function paintFive(s) {
    const FY = st.D.five_year || {};
    const ref = armOf(FY.ref);
    if (!ref || !ref.v) { put(fiveBody, h("p", {class: "muted"}, (ref && ref.F && ref.F.why) || "5년 결과 파일이 없습니다.")); return; }
    // today's rule over five years: levstop tiers|2.0, which is exitstyle's ladder number for number (its prereg checks
    // it); the exitstyle copy also carries the pooled period means, so it is used whenever it is there
    const ladder = armOf("exitstyle:ladder");
    const src = s && s.five ? s.five.split(":")[0] : null;
    const R = (src !== "levstop" || !s || s.five === FY.ref) && ladder && ladder.v ? ladder.v : ref.v;
    const kids = [];
    if (!s || !s.five) {
      const why = !s ? "이 조합은 5년에도, 밤 그림자에도 없습니다." : [!sameVal(st.sel.lock, st.D.current.lock) ? NO_FIVE_KO.lock : null,
        st.sel.time !== "none" ? NO_FIVE_KO.time : null, st.sel.lev === "50m50" ? NO_FIVE_KO.lev : null].filter(Boolean).join(" ");
      kids.push(h("p", {class: "wi-none"}, ui.pill("5년에 시험한 적 없음", "thin"), " ", why || "이 설정은 5년 결과가 없습니다."));
      kids.push(h("p", {class: "note"}, `지금 규칙의 5년 기준: 거래당 자금 대비 ${pc(R.mean_eq)} · 승률 ${fmt.pct(R.win_rate, 0, false)} · 파산 ${share(R.busts, R.accounts)}`));
    } else {
      const A = armOf(s.five);
      const V = A && A.v;
      const same = s.five === FY.ref;
      if (!V) {
        kids.push(h("p", {class: "muted"}, "이 설정의 5년 칸을 찾지 못했습니다."));
      } else {
        const d = (k) => (V[k] == null || R[k] == null ? null : V[k] - R[k]);
        // one metric: [label, today's text, this setting's text, the difference [text, tone] or ""]
        const M = [
          ["거래당 자금 대비", pc(R.mean_eq), pc(V.mean_eq), [pctp(d("mean_eq")), fmt.tone(d("mean_eq"))]],
          ["승률", fmt.pct(R.win_rate, 0, false), fmt.pct(V.win_rate, 0, false), [pctp(d("win_rate"), 0), ""]],
          // a cell with few 5-year trades (one strategy on one timeframe, often 4h): chance can explain it
          [["거래 수 ", ui.smallSample(Math.min(R.trades || 0, same ? Infinity : V.trades || 0), FIVE_MIN)], fmt.int(R.trades), fmt.int(V.trades), ""],
          ["파산한 계좌", share(R.busts, R.accounts), share(V.busts, V.accounts), ""],
          ["평균이 플러스인 칸", share(R.cells_pos, R.cells_traded), share(V.cells_pos, V.cells_traded), ""],
          ["두 기간 다 플러스인 칸", share(R.cells_both, R.cells_traded), share(V.cells_both, V.cells_traded), ""],
        ];
        if (R.mean_eq_p1 != null || V.mean_eq_p1 != null) M.push(["1기 거래당", pc(R.mean_eq_p1), pc(V.mean_eq_p1), ""], ["2기 거래당", pc(R.mean_eq_p2), pc(V.mean_eq_p2), ""]);
        if ((V.liq_share || 0) > 0 || (R.liq_share || 0) > 0) M.push(["강제청산 비율", fmt.pct(R.liq_share, 1, false), fmt.pct(V.liq_share, 1, false), ""]);
        if (A.src === "exitstyle" && !same) {
          M.push(["같은 신호에서 지금보다", "", pctp(V.diff), ["", ""]], ["익절로 끝난 비율", fmt.pct(R.tp_share ?? 0, 0, false), fmt.pct(V.tp_share, 0, false), ""]);
        }
        kids.push(same ? cmpTable(["지금 규칙"], M.map((r) => cmpRow(r[0], r[1])))
          : cmpTable(["지금 규칙", "이 설정", "차이"], M.map((r) => cmpRow(r[0], r[1], r[2], r[3]))));
        kids.push(bars5(R, V, same));
        if (A.src === "exitstyle" && !same) {
          kids.push(h("p", {class: "note"}, `같은 신호 비교: 1기 ${pctp(V.diff_p1)}, 2기 ${pctp(V.diff_p2)}. 미리 정한 판정(5년, 사전 등록): `,
            ((FY.exitstyle || {}).recommend === "ladder" ? "어느 고정 익절도 세 조건을 다 넘지 못해 사다리 유지." : "결과 파일의 권고를 보세요.")));
        }
      }
    }
    kids.push(ui.disclosure("5년 24가지 + 익절 6가지 한눈에", mapFive(s)));
    kids.push(h("p", {class: "note"}, `${FY.ref_ko || ""}. 칸 = 매매법 × 봉, 거래당 자금 대비 = ROE × 증거금 비율의 평균, 파산 = 칸·기간마다 $5,000 계좌 하나. ${FY.cells_ko || ""} · ${FY.label || "설명용, 판정 아님"}`));
    put(fiveBody, ...kids);
  }
  // two thin bars on one zero line: 지금 vs 이 설정 (the per-trade mean on equity)
  function bars5(R, V, same) {
    const xs = [R.mean_eq, same ? null : V.mean_eq].filter((x) => x != null);
    if (!xs.length) return null;
    const m = Math.max(...xs.map(Math.abs), 1e-9);
    const bar = (label, x, cls) => h("div", {class: "wi-bar"}, h("span", {class: "wi-bar-k"}, label),
      h("span", {class: "wi-bar-t"}, h("i", {class: [x < 0 ? "neg" : "pos", cls], style: {"--w": `${(Math.abs(x) / m * 50).toFixed(1)}%`}})),
      h("b", {class: ["num", fmt.tone(x)]}, pc(x)));
    return h("div", {class: "wi-bars", role: "img", "aria-label": "거래당 자금 대비 평균 비교"},
      bar("지금", R.mean_eq, "now"), same ? null : bar("이 설정", V.mean_eq, "alt"));
  }
  // the whole 5-year table at once (lev x stop with the ladder, and the take-profit strip): tap a cell to pick it
  function mapFive(s) {
    const FY = st.D.five_year || {};
    const L = ((FY.levstop || {}).arms) || {}, E = ((FY.exitstyle || {}).arms) || {};
    const vals = [...Object.values(L), ...Object.values(E)].map((v) => v && v.mean_eq).filter((x) => x != null);
    const m = Math.max(...vals.map(Math.abs), 1e-9);
    const cell = (v, key, pickSel, label) => {
      const on = s && s.five === key;
      const x = v ? v.mean_eq : null;
      return h("button", {type: "button", class: ["wi-mc", x == null ? "none" : x < 0 ? "neg" : "pos", on ? "on" : "", key === FY.ref ? "ref" : ""],
        style: {"--a": x == null ? "0" : (0.15 + 0.85 * Math.abs(x) / m).toFixed(2)}, title: `${label} · 거래당 자금 대비 ${pc(x)} · 파산 ${v ? share(v.busts, v.accounts) : "—"}`,
        "aria-label": `${label}: ${pc(x)}`, onclick: () => { const t = (st.D.settings || []).find((z) => z.five === key); if (t) apply(t); else apply(pickSel); }},
      h("span", {class: "num"}, x == null ? "—" : fmt.num(x * 100, 2, true)));
    };
    const head = h("div", {class: "wi-map-r wi-map-h"}, h("span", null, "레버리지 \\ 손절"), STOP_COLS.map((c) => h("span", null, `${c} ATR`)));
    const rows = LEV_ROWS.map(([lv, ko]) => h("div", {class: "wi-map-r"}, h("span", {class: "wi-map-k"}, ko),
      STOP_COLS.map((c) => cell(L[`${lv}|${STOP_KEY[c]}`], `levstop:${lv}|${STOP_KEY[c]}`,
        {stop: c, tp: "ladder", lock: 0.1, time: "none", lev: lv === "tiers" ? "rule" : lv}, `${ko} · 손절 ${c} ATR`))));
    const strip = h("div", {class: "wi-map-tp"}, TP_STRIP.map(([k, ko]) => h("div", {class: "wi-map-tpc"}, h("span", {class: "wi-map-k"}, ko),
      cell(E[k], k === "ladder" ? FY.ref : `exitstyle:${k}`, {stop: 2, tp: k, lock: FIXED_TP.has(k) ? null : 0.1, time: "none", lev: "rule"}, `익절 ${ko}`))));
    return h("div", {class: "stack tight wi-map"},
      h("p", {class: "note"}, "숫자 = 거래당 자금 대비 평균(%). 굵은 테두리 = 지금 규칙의 5년 기준, 밝은 테두리 = 고른 설정. 칸을 누르면 그 설정을 고릅니다."),
      h("div", {class: "wi-map-g"}, head, rows),
      h("p", {class: "wi-sub"}, "익절 방식 (손절 2 ATR · 지금 단계)"), strip,
      h("p", {class: "note"}, "가장 좋아 보이는 칸을 고르는 것은 선택 편향입니다. 플러스인 조합이 하나도 없다는 것이 이 표의 큰 그림입니다."));
  }

  function paintPaper() {
    if (!st.D) return;
    const s = matchSetting(st.sel);
    const P = st.P;
    if (!P || P.pending) { put(paperBody, h("p", {class: "muted"}, P && P.pending ? "서버가 그림자 기록을 모으는 중입니다. 곧 다시 불러옵니다." : "불러오는 중"), motion.shimmer(3)); return; }
    if (!P.ready) {
      put(paperBody, h("p", null, ui.pill("아직 없음", "thin"), " ", P.why || "밤 점검 기록이 없습니다."),
        progressBar("그림자 비교 · 같은 거래 10건부터 볼 만함", "밤 점검(매일 09:20)이 전날 끝난 거래를 규칙 하나만 바꿔 다시 돌린 뒤 채워집니다.", 0));
      return;
    }
    const base = P.base || {trades: 0};
    const kids = [];
    if (!s || !s.paper) {
      kids.push(h("p", {class: "wi-none"}, ui.pill("밤 그림자 없음", "thin"), " ",
        s ? "밤 그림자는 한 번에 규칙 하나만 바꿉니다. 이 설정은 둘 이상을 바꿔서 5년 표에만 있습니다." : "이 조합은 시험한 적이 없습니다."));
    } else if (s.paper === "base") {
      kids.push(base.trades
        ? h("p", null, `지금 규칙(base 그림자): ${fmt.int(base.trades)}건 · 거래당 자금 대비 `, h("b", {class: ["num", fmt.tone(base.mean_eq)]}, pc(base.mean_eq)), " ", ui.smallSample(base.trades, P.small_n || 10))
        : h("p", null, ui.pill("아직 0건", "thin"), " 지금 규칙의 그림자 거래가 아직 없습니다."));
      kids.push(progressFor(base.trades, P.small_n || 10, "지금 규칙"));
    } else {
      const c = (P.variants || {})[s.paper] || {trades: 0};
      const n = c.trades || 0;
      if (!n) {
        kids.push(h("p", null, ui.pill("아직 0건", "thin"), ` 이 그림자(${s.ko})에 같은 거래로 비교할 기록이 아직 없습니다.`,
          c.open ? ` 아직 안 끝남 ${fmt.int(c.open)}건.` : "", c.not_entered ? ` 진입 안 함 ${fmt.int(c.not_entered)}건.` : ""));
      } else {
        const rows = [
          cmpRow("거래당 자금 대비", pc(c.base_mean_eq), pc(c.mean_eq), [pctp(c.vs_base_eq), fmt.tone(c.vs_base_eq)]),
          cmpRow("같은 거래 수", fmt.int(n), fmt.int(n), ""),
          cmpRow("더 나음 / 더 나쁨", "", `${fmt.pct(c.better_share, 0, false)} / ${fmt.pct(c.worse_share, 0, false)}`, ""),
          cmpRow("강제청산", fmt.int(c.base_liq || 0), fmt.int(c.liq || 0), ""),
        ];
        if (c.tp) rows.push(cmpRow("익절로 끝남", "", fmt.int(c.tp), ""));
        kids.push(cmpTable(["지금 규칙", "이 설정", "차이"], rows));
        const extra = [c.not_entered ? `진입 안 함 ${fmt.int(c.not_entered)}건 (크기 조건에 막힘)` : null, c.open ? `아직 안 끝남 ${fmt.int(c.open)}건` : null].filter(Boolean);
        if (extra.length) kids.push(h("p", {class: "note"}, extra.join(" · ")));
        if (n < (P.small_n || 10)) kids.push(h("p", null, ui.pill("표본 적음", "thin"), ` ${fmt.int(n)}건 (${fmt.int(P.small_n || 10)}건 미만): 우연일 수 있어 결론을 내리지 않습니다.`));
      }
      kids.push(progressFor(n, P.small_n || 10, s.ko));
    }
    const rep = P.report ? `마지막 밤 점검 ${fmt.kst(P.report.ts)}` : "밤 점검 기록 아직 없음";
    kids.push(h("p", {class: "note"}, `${rep} · 시작 ${P.since ? fmt.mmdd(P.since) : "—"}부터 · ${P.note || ""}`));
    put(paperBody, ...kids);
  }
  function progressFor(n, need, what) {
    if (n >= need) return null;
    return progressBar(`같은 거래 ${fmt.int(need)}건 필요 · ${what}`, `지금 ${fmt.int(n)}건. 밤 점검(매일 09:20)이 전날 끝난 거래를 더할 때마다 찹니다.`, need ? n / need : 0);
  }

  function paintCoin() {
    if (!st.D) return;
    const s = matchSetting(st.sel);
    const P = st.P;
    const kids = [];
    // 이번 실험: the same shadow on the coin-flip accounts
    if (!P || P.pending) kids.push(h("p", {class: "muted"}, "그림자 기록을 불러오는 중"));
    else if (!P.ready) kids.push(h("p", {class: "muted"}, "동전 봇 그림자도 밤 점검이 돈 뒤에 나옵니다."));
    else if (s && s.paper) {
      const cb = (P.coin || {}).base || {trades: 0};
      const cv = s.paper === "base" ? null : ((P.coin || {}).variants || {})[s.paper] || {trades: 0};
      const sv = s.paper === "base" ? null : (P.variants || {})[s.paper] || {trades: 0};
      const sm = (n) => ui.smallSample(n || 0, P.small_n || 10) || "";
      kids.push(h("p", {class: "wi-sub"}, "이번 실험 · 밤 그림자"));
      if (s.paper === "base") {
        const sb = P.base || {trades: 0};
        kids.push(cmpTable(["거래", "거래당 자금 대비", ""], [
          cmpRow("매매법 (지금 규칙)", fmt.int(sb.trades || 0), [sb.trades ? pc(sb.mean_eq) : "—", fmt.tone(sb.mean_eq)], sm(sb.trades)),
          cmpRow("동전 봇 (지금 규칙)", fmt.int(cb.trades || 0), [cb.trades ? pc(cb.mean_eq) : "—", fmt.tone(cb.mean_eq)], sm(cb.trades))]));
      } else {
        kids.push(cmpTable(["거래", "지금 규칙과 차이", ""], [
          cmpRow("매매법", fmt.int(sv.trades || 0), [sv.trades ? pctp(sv.vs_base_eq) : "—", fmt.tone(sv.vs_base_eq)], sm(sv.trades)),
          cmpRow("동전 봇", fmt.int(cv.trades || 0), [cv.trades ? pctp(cv.vs_base_eq) : "—", fmt.tone(cv.vs_base_eq)], sm(cv.trades))]));
        kids.push(h("p", {class: "note"}, "차이 = 그 그림자 − 같은 거래의 지금 규칙. 동전 봇에서도 비슷하게 움직이면 매매법의 실력이 아니라 규칙 자체의 효과입니다."));
      }
    } else kids.push(h("p", {class: "muted"}, "이 설정은 밤 그림자가 없어 이번 실험의 동전 봇 비교도 없습니다."));
    // 5년: the coin flips under the same house rules (stop 1.5 / 2 ATR only)
    const C5 = ((st.D.five_year || {}).coin) || {};
    const k = s && s.tp === "ladder" && s.time === "none" && s.lev === "rule" && sameVal(s.lock, 0.1) && (sameVal(s.stop, 1.5) || sameVal(s.stop, 2)) ? (sameVal(s.stop, 2) ? "2.0" : "1.5") : null;
    if (!C5.ready) kids.push(h("p", {class: "muted"}, C5.why || "5년 동전 봇 결과가 없습니다."));
    else if (!k) kids.push(h("p", {class: "note"}, h("b", null, "5년 "), "동전 봇은 손절 1.5·2 ATR(지금 단계 레버리지, 사다리)로만 돌렸습니다. 이 설정의 5년 동전 봇 숫자는 없습니다."));
    else {
      const B = (C5.by_k || {})[k] || {};
      const f = B.flips || {}, c = B.core || {};
      kids.push(h("p", {class: "wi-sub"}, `5년 · 같은 규칙 · 손절 ${k === "2.0" ? "2" : k} ATR`),
        cmpTable(["거래", "거래당 (증거금 대비)", "파산한 계좌"], [["매매법", c], ["동전 봇", f]].map(([ko, x]) =>
          cmpRow(`${ko} · 승률 ${fmt.pct(x.win_rate, 0, false)}`, fmt.int(x.trades || 0), [pc(x.mean_r), fmt.tone(x.mean_r)], share(x.busts, x.accounts)))),
        h("p", {class: "note"}, C5.note || ""));
    }
    kids.push(ui.refNote(st.verdictTs));
    put(coinBody, ...kids);
  }

  // ---------------------------------------------------------------- go
  // same screen, another target (a strategy page's link while the lab is open): load it in place
  current = (params) => {
    const q2 = (params && params.query) || {};
    const pre = q2.set && st.D && (st.D.settings || []).find((x) => x.id === q2.set);
    if (pre) { for (const k of DIMS) st.sel[k] = pre[k] == null ? st.sel[k] : pre[k]; paintControls(); }
    if ((q2.strategy || "") !== st.strategy || (q2.tf || "") !== st.tf) { st.strategy = q2.strategy || ""; st.tf = q2.tf || ""; load(); }
    else if (pre) paintResults(true);
  };
  ctx.track(() => { current = null; });
  ctx.store.need("summary", 60000).then((sm) => {
    const r = (sm && sm.restart) || {};
    st.verdictTs = (r.ready && r.verdict_ts) || (sm && sm.next_checkpoint && sm.next_checkpoint.ts) || null;
    if (ctx.alive() && st.D) paintCoin();
  }).catch(() => {});
  await load();
  // a new nightly report changes the shadows: ask again every 10 minutes (the server caches per report)
  ctx.every(600000, () => loadPaper(), {now: false});
}

export function update(params) { if (current) current(params); }

export function unmount() { current = null; }
