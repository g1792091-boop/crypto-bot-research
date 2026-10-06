// 조합 성과 › 내 조합 만들기: pick 2-8 units and a weighting, see what running them together would have done in the
// paper v4 records (/api/v4/combo). The pick is in the address (?u=A,B@1h&w=eq|custom|invvol|rp&p=50,50: a link opens
// the same combination) and remembered per device (local "combo-pick"). Cards: the picker; the combined curve (each
// member thin, the same number of coin flips combined as the grey baseline, legend items hide / show a line); the
// numbers (one stated basis); 하루 기준·회복; each member's part and the combination without it; the correlation inside;
// 'same bet' pairs; the diversification ratio. Early days: the filling bars and "거래 N건 · 아직 판단하기 이릅니다".
import {h, put, ui, fmt, motion, local, makeChart, tok} from "../core/pb.js";
import {swatch, lineColor, loadUnits, unitIndex, unitName, corrGrid, corrWords, earlyCard, pctB, moneyB, verdictTs, shareWords} from "./combo-kit.js";

const KMIN = 2, KMAX = 8;
const METHODS = [
  {id: "eq", label: "똑같이", words: "구성원마다 합친 자금을 똑같이 나눕니다."},
  {id: "custom", label: "직접 %", words: "구성원마다 % 를 직접 넣습니다 (합이 100이 아니어도 비율대로 나눕니다)."},
  {id: "invvol", label: "변동 적은 쪽에 더", words: "1시간 자본 변화가 작았던 구성원에게 더 줍니다 (변동의 역수 비율)."},
  {id: "rp", label: "위험 똑같이", words: "구성원마다 합친 곡선의 흔들림에 보태는 몫이 같도록 나눕니다 (서로 같이 움직이는 정도까지 봄)."},
];
const okMethod = (w) => (METHODS.some((m) => m.id === w) ? w : "eq");
const daysKo = (d) => (d == null ? "—" : d < 1 ? fmt.dur(d * 86400) : `${fmt.num(d, 1)}일`);
/** n whole percents that add up to 100 (the first ones get the remainder): 3 -> [34, 33, 33]. */
const equalSplit = (n) => Array.from({length: n}, (_x, i) => Math.floor(100 / n) + (i < 100 % n ? 1 : 0));
const ratioB = (x) => h("b", {class: ["num", x == null ? "muted" : ""]}, x == null ? "—" : fmt.num(x, 2));

export function buildTab(env) {
  const {ctx} = env;
  const st = {idx: null, d: null, pick: [], w: "eq", p: [], gen: 0, hidden: new Set(), kind: local.get("combo-kind", "strategy"),
    corr: local.get("combo-corrbasis", null), timer: 0, disposers: []};
  const pickCard = h("div");
  const result = h("div", {class: "stack cb-result"});
  const el = h("div", {class: "stack cb-build"}, pickCard, result);
  let search = null;

  // ---------------------------------------------------------------- the pick and the address
  function fromQuery(q) {
    const keys = String(q.u || "").split(",").map((x) => x.trim()).filter(Boolean);
    const p = q.p ? String(q.p).split(",").map((x) => (String(x).trim() === "" ? NaN : Number(x))) : [];   // no p: an equal split
    return {keys, w: okMethod(q.w), p};
  }
  function apply(q) {
    const {keys, w, p} = fromQuery(q);
    const ok = [], dropped = [];
    for (const k of keys) {
      if (!st.idx[k]) { dropped.push(k); continue; }
      if (ok.length < KMAX && !clash(k, ok)) ok.push(k);
    }
    if (dropped.length) ctx.toast(`목록에 없는 구성원을 뺐습니다: ${dropped.join(", ")}`);
    st.pick = ok;
    st.w = w;
    const even = equalSplit(ok.length);
    st.p = ok.map((_k, i) => (Number.isFinite(p[i]) && p[i] >= 0 ? p[i] : even[i]));
  }
  function clash(key, list) {
    const u = st.idx[key];
    if (!u) return true;
    return list.some((k) => { const v = st.idx[k]; return v && v.accounts.some((a) => u.accounts.includes(a)); });
  }
  function save() {
    const q = {u: st.pick.join(","), w: st.w === "eq" ? null : st.w, p: st.w === "custom" ? st.p.map((x) => fmt.num(x, 0).replace(/,/g, "")).join(",") : null};
    env.setQuery(q);
    local.set("combo-pick", {u: q.u, w: q.w, p: q.p});
  }
  function example() {
    // first visit: three strategies in list order, said plainly to be an example (never a recommendation)
    return Object.values(st.idx).filter((u) => u.kind === "strategy").slice(0, 3).map((u) => u.key);
  }

  // ---------------------------------------------------------------- the picker card
  function renderPicker() {
    const n = st.pick.length;
    const chips = h("div", {class: "cb-chips", role: "list", "aria-label": "고른 구성원"},
      n ? st.pick.map((k, i) => chip(k, i)) : h("p", {class: "muted"}, "아직 고른 것이 없습니다. 아래에서 찾아 넣어 주세요."));
    const mseg = ui.seg(METHODS.map((m) => ({id: m.id, label: m.label})), st.w, (id) => {
      if (id === "custom" && st.w !== "custom") st.p = equalSplit(st.pick.length);   // 직접 % starts from an equal split
      st.w = id;
      changed();
    }, {label: "비중 나누는 법"});
    const mw = h("p", {class: "cb-mwords"}, METHODS.find((m) => m.id === st.w).words);
    st.sumEl = st.w === "custom" ? h("p", {class: "cb-mwords"}, sumWords()) : null;
    const acts = h("div", {class: "cb-acts"},
      h("button", {class: "btn-line", type: "button", onclick: copyLink, disabled: n < KMIN || null}, "이 조합 링크 복사"),
      n ? h("button", {class: "btn-line", type: "button", onclick: () => { st.pick = []; st.p = []; changed(); }}, "모두 빼기") : null);
    put(pickCard, ui.card({plate: "구성 고르기", sub: `${fmt.int(n)}개 고름 · ${KMIN}~${KMAX}개`, cls: "cb-pick"},
      chips,
      h("div", {class: "cb-mrow"}, h("span", {class: "cb-k"}, "비중"), mseg),
      mw,
      st.sumEl,
      finder(),
      acts));
  }
  function sumWords() {
    const sum = st.p.reduce((a, b) => a + (Number(b) || 0), 0);
    return `지금 합 ${fmt.num(sum, 0)}% · 합이 100이 아니면 비율대로 맞춰 계산합니다.`;
  }
  function chip(k, i) {
    const u = st.idx[k] || {name: k, sub: ""};
    const inp = st.w === "custom" ? h("input", {class: "cb-pct", type: "number", min: "0", max: "100", step: "5", inputmode: "numeric",
      value: String(st.p[i] ?? 0), "aria-label": `${unitName(k, st.idx)} 비중 %`,
      oninput: (e) => {
        st.p[i] = Math.max(0, Number(e.target.value) || 0);
        if (st.sumEl) st.sumEl.textContent = sumWords();      // the picker is not redrawn while typing (keeps the focus)
        clearTimeout(st.timer);
        st.timer = setTimeout(() => changed(true), 700);
      }}) : null;
    return h("div", {class: "cb-chip", role: "listitem"}, swatch(i),
      h("span", {class: "cb-cn"}, h("b", null, u.name), h("span", {class: "cb-cs"}, u.kind === "account" ? `${fmt.tfKo(u.tf)}봉 하나` : u.sub)),
      inp ? h("span", {class: "cb-pctw"}, inp, "%") : null,
      h("button", {class: "cb-x", type: "button", "aria-label": `${unitName(k, st.idx)} 빼기`, title: "빼기",
        onclick: () => { st.p.splice(i, 1); st.pick.splice(i, 1); changed(); }}, "✕"));
  }
  function finder() {
    const kseg = ui.seg([{id: "strategy", label: "매매법 (봉 4개 합)"}, {id: "account", label: "봉 계좌 하나"}], st.kind,
      (id) => { st.kind = id; local.set("combo-kind", id); search.set(items(), false); }, {label: "무엇을 고를지"});
    search = ui.searchList({items: items(), size: 6, placeholder: "매매법 이름이나 코드로 찾기 (예: 돈치안, S5)", filters: kseg,
      empty: "맞는 매매법이 없습니다",
      match: (u, q) => (u.name + " " + u.key + " " + (u.sub || "")).toLowerCase().includes(q),
      row: (u) => {
        const taken = st.pick.includes(u.key), conflict = !taken && clash(u.key, st.pick), full = st.pick.length >= KMAX;
        const why = taken ? "이미 넣음" : conflict ? "같은 계좌가 이미 들어 있음" : full ? `${KMAX}개까지` : null;
        return h("div", {class: "lrow cb-frow", role: "listitem"},
          h("span", {class: "rk"}, u.kind === "account" ? fmt.tfKo(u.tf) : u.reel ? "5분" : "4개"),
          h("span", {class: "lname"}, u.name, u.reel ? [" ", ui.pill("릴스 · 참고", "ref")] : null),
          h("button", {class: ["btn-line", "cb-add"], type: "button", disabled: why ? true : null, title: why || "넣기",
            "aria-label": `${unitName(u.key, st.idx)} ${why || "넣기"}`, onclick: () => add(u.key)}, why ? "—" : "+ 넣기"),
          h("span", {class: "meta"}, h("span", null, `거래 ${fmt.int(u.trades)}건`), u.ret != null ? h("span", {class: fmt.tone(u.ret, fmt.pct(u.ret, 1))}, `수익률 ${fmt.pct(u.ret, 1)}`) : null,
            h("span", null, u.kind === "account" ? "봉 계좌 하나" : u.sub), why ? h("span", null, why) : null));
      }});
    search.input.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || e.isComposing) return;
      const q = search.input.value.trim().toLowerCase();
      const first = items().find((u) => (u.name + " " + u.key).toLowerCase().includes(q) && !st.pick.includes(u.key) && !clash(u.key, st.pick));
      if (q && first) add(first.key);
    });
    return h("div", {class: "cb-find"}, h("p", {class: "cb-k"}, "찾아 넣기"), search.el,
      h("p", {class: "an-note"}, "목록은 이름 순서입니다 (순위 아님). 수익률은 닫힌 거래 기준 잔고, 매매법은 봉 계좌 4개를 더한 것."));
  }
  function items() {
    const all = Object.values(st.idx || {});
    return st.kind === "account" ? all.filter((u) => u.kind === "account") : all.filter((u) => u.kind !== "account");
  }
  function add(key) {
    if (st.pick.includes(key) || clash(key, st.pick) || st.pick.length >= KMAX) return;
    st.pick.push(key);
    st.p.push(Math.round(100 / st.pick.length));
    changed();
    ctx.toast(`${unitName(key, st.idx)} 넣음`);
  }
  async function copyLink() {
    const url = location.href;
    try { await navigator.clipboard.writeText(url); ctx.toast("이 조합의 링크를 복사했습니다"); } catch { ctx.toast(url); }
  }

  function changed(keepPicker) {
    st.hidden.clear();
    save();
    if (!keepPicker) {
      const q = search ? search.input.value : "";
      renderPicker();
      if (q) { search.input.value = q; search.input.dispatchEvent(new Event("input")); }
    }
    compute();
  }

  // ---------------------------------------------------------------- the numbers
  async function compute() {
    const g = ++st.gen;
    closeAll();
    if (st.pick.length < KMIN) {
      put(result, ui.card({plate: "합친 곡선"}, ui.empty(`${KMIN}개 이상 고르면 합친 곡선과 숫자가 나옵니다.`)));
      return;
    }
    put(result, ui.card({plate: "합친 곡선", sub: "계산 중"}, motion.shimmer(4)));
    const q = new URLSearchParams({u: st.pick.join(","), w: st.w});
    if (st.w === "custom") q.set("p", st.p.map((x) => String(Math.round(Number(x) || 0))).join(","));
    let d;
    try { d = await ctx.api(`/api/v4/combo?${q.toString()}`); } catch (e) {
      if (g !== st.gen || !ctx.alive()) return;
      put(result, ui.card({plate: "합친 곡선"}, e && e.detail ? h("p", {class: "an-warn"}, String(e.detail)) : ui.errorBox(e, () => compute())));
      return;
    }
    if (g !== st.gen || !ctx.alive()) return;
    if (d && d.pending) {
      put(result, ui.card({plate: "합친 곡선", sub: "계산 중"}, h("p", {class: "muted"}, d.note || "서버가 계산하는 중입니다. 잠시 뒤 다시 봅니다."), motion.shimmer(3)));
      ctx.timeout(() => { if (g === st.gen) compute(); }, 2000);
      return;
    }
    if (d && d.error) { put(result, ui.card({plate: "합친 곡선"}, h("p", {class: "muted"}, String(d.error)))); return; }
    st.d = d;
    paint(d);
  }

  function closeAll() { for (const f of st.disposers.splice(0)) { try { f(); } catch (e) { console.error(e); } } }

  function paint(d) {
    const names = d.units.map((u) => unitName(u.key, st.idx));
    put(result, earlyCard(d.small, names.join(" + ")), curveCard(d, names), numbersCard(d), dailyCard(d), membersCard(d, names),
      corrCard(d, names), sameBetCard(d, names), divCard(d, names));
    motion.swap(result);
  }

  // ---------------------------------------------------------------- 합친 곡선
  function curveCard(d, names) {
    const box = h("div", {class: "cb-chart", role: "img", "aria-label": "합친 곡선 (수익률 %)"});
    const cv = d.curve || {}, fl = d.flips || {};
    const lines = [{id: "comb", label: "합친 곡선", ret: d.stats.ret, cls: "comb"},
      ...d.units.map((u, i) => ({id: "m" + i, i, label: names[i], ret: (cv.members[i] || []).slice(-1)[0], cls: "mem"})),
      ...(cv.flips ? [{id: "flip", label: `동전 봇 ${fmt.int(fl.accounts)}개 합 (참고)`, ret: fl.ret, cls: "flip"}] : [])];
    const series = {};
    const legend = h("div", {class: "cb-legend", role: "group", "aria-label": "선 보이기 · 숨기기"}, lines.map((l) => {
      const on = !st.hidden.has(l.id);
      return h("button", {type: "button", class: ["cb-li", l.cls], "aria-pressed": String(on), title: on ? "눌러서 숨기기" : "눌러서 보이기",
        onclick: (e) => {
          const b = e.currentTarget, vis = st.hidden.has(l.id);
          if (vis) st.hidden.delete(l.id); else st.hidden.add(l.id);
          b.setAttribute("aria-pressed", String(vis));
          if (series[l.id]) series[l.id].applyOptions({visible: vis});
        }},
      l.cls === "mem" ? swatch(l.i) : h("i", {class: ["cb-sw", l.cls], "aria-hidden": "true"}),
      h("span", {class: "cb-ln"}, l.label), h("span", {class: ["num", fmt.tone(l.ret, fmt.pct(l.ret, 1))]}, fmt.pct(l.ret, 1)));
    }));
    const flipLine = cv.flips ? h("p", {class: "an-note"}, `회색 선 = 같은 봉의 동전 봇 ${fmt.int(fl.accounts)}개를 같은 비중으로 합친 것 (참고): 수익률 ${fmt.pct(fl.ret, 1)} · 최대 낙폭 ${fmt.pct(-(fl.mdd_pct || 0), 1)} · 거래 ${fmt.int(fl.trades)}건`,
      fl.note ? ` · ${fl.note}` : "") : h("p", {class: "an-note"}, fl.note || "동전 봇 비교선이 없습니다.");
    draw(box, d, series);
    return ui.card({plate: "합친 곡선", sub: `${names.length}개 · 비중 ${d.method.used_ko}`, cls: "cb-curve"},
      h("p", {class: "cb-title"}, names.map((n, i) => [i ? h("span", {class: "muted"}, " + ") : null, h("span", {class: "cb-tn"}, swatch(i), n)])),
      d.method.note ? h("p", {class: "an-warn"}, `${d.method.asked_ko}을(를) 골랐지만 ${d.method.note}`) : null,
      d.method.in_sample_ko ? h("p", {class: "cb-small"}, ui.pill("미리 안 셈", "thin"), ` ${d.method.in_sample_ko}`) : null,
      d.small.early ? h("p", {class: "cb-small"}, ui.pill("표본 적음", "thin"), ` ${d.small.words}`) : null,
      box, legend,
      h("p", {class: "an-note"}, `세로 = 시작 대비 수익률 % · ${d.basis_ko}`, cv.thinned && cv.step_min ? ` · 그림은 약 ${fmt.num(cv.step_min, 0)}분 간격으로 줄여 그림, 숫자는 기록 전체로 계산` : ""),
      flipLine, d.reel_note ? h("p", {class: "an-note"}, ui.pill("릴스", "ref"), " ", d.reel_note) : null, ui.refNote(verdictTs()));
  }
  async function draw(box, d, series) {
    const cv = d.curve || {};
    if (!(cv.t || []).length || cv.t.length < 2) { put(box, ui.notYet("곡선 기록 전")); return; }
    try {
      // no timeScale here: chartOptions' own keeps the Korea-time tick labels (an extra timeScale would replace it: UTC)
      const C = await makeChart(box, {rightPriceScale: {borderColor: tok("--line-2"), scaleMargins: {top: 0.12, bottom: 0.1}},
        handleScroll: {vertTouchDrag: false}});
      if (!ctx.alive() || !box.isConnected) { C.dispose(); return; }
      st.disposers.push(C.dispose);
      const T = cv.t.map((ms) => Math.floor(ms / 1000));
      const fmtPct = (v) => `${fmt.num(v, 1, true)}%`;
      const pf = {type: "custom", formatter: fmtPct, minMove: 0.01};
      const add = (id, vals, o) => {
        const ln = C.chart.addLineSeries({priceFormat: pf, lastValueVisible: false, priceLineVisible: false, crosshairMarkerRadius: 3, ...o,
          visible: !st.hidden.has(id)});
        const pts = [];
        let last = -1;
        T.forEach((t, k) => {
          const v = vals[k];
          if (v == null || !Number.isFinite(v)) return;
          if (t === last) pts[pts.length - 1] = {time: t, value: v * 100}; else pts.push({time: t, value: v * 100});
          last = t;
        });
        ln.setData(pts);
        series[id] = ln;
        return ln;
      };
      if (cv.flips) add("flip", cv.flips, {color: tok("--series-coin"), lineWidth: 1, lineStyle: 2, title: ""});
      (cv.members || []).forEach((vals, i) => add("m" + i, vals, {color: lineColor(i), lineWidth: 1, title: ""}));
      const comb = add("comb", cv.combined, {color: tok("--accent"), lineWidth: 3, title: ""});
      comb.createPriceLine({price: 0, color: tok("--muted"), lineStyle: 2, lineWidth: 1, axisLabelVisible: false, title: "시작"});
      C.chart.timeScale().fitContent();
    } catch (e) { console.error(e); put(box, ui.errorBox(null)); }
  }

  // ---------------------------------------------------------------- 합친 숫자
  function numbersCard(d) {
    const S = d.stats, wd = S.worst_day;
    const tiles = [
      ui.stat("수익률", pctB(S.ret, 2), `합친 자금 ${fmt.money(d.capital)} 대비`),
      ui.stat("손익", moneyB(S.pnl), d.basis === "mark" ? "비중 반영 · 열린 포지션은 지금 시세로 평가" : "비중 반영 · 닫힌 거래만"),
      ui.stat("최대 낙폭", pctB(S.mdd_pct ? -S.mdd_pct : 0, 1), S.mdd_trough_ts ? `${fmt.money(-S.mdd_usd)} · 바닥 ${fmt.kst(S.mdd_trough_ts)}` : "아직 고점 아래로 내려간 적 없음"),
      ui.stat("최악의 날", wd ? moneyB(wd.pnl) : h("b", {class: "num muted"}, "—"),
        wd ? `${wd.day.slice(5).replace("-", "/")} · ${fmt.pct(wd.ret, 1)}${wd.pnl >= 0 ? " · 잃은 날 없음 (가장 덜 번 날)" : ""}${S.partial_day && wd.day === S.partial_day ? " · 오늘 (아직 진행 중)" : ""}` : "날 기록 전"),
      ui.stat("거래 수", `${fmt.int(S.trades)}건`, ui.smallSample(S.trades, d.small.need) || "구성원 닫힌 거래의 합"),
      ui.stat("승률", S.win_rate == null ? "—" : fmt.pct(S.win_rate, 0, false), S.trades ? `${fmt.int(S.wins)}승 ${fmt.int(S.trades - S.wins)}패` : "거래 없음"),
      ui.stat("평균 거래", S.avg_trade == null ? h("b", {class: "num muted"}, "—") : moneyB(S.avg_trade), "한 건 평균 손익 (비중 반영)"),
      ui.stat("이익 합 ÷ 손실 합", ratioB(S.profit_factor), S.profit_factor == null ? "진 거래가 아직 없음" : "1보다 크면 번 돈이 잃은 돈보다 많음")];
    return ui.card({plate: "합친 숫자", sub: d.small.early ? d.small.words : `${d.label}`},
      h("div", {class: "stats s4"}, tiles),
      h("p", {class: "an-note"}, d.mdd_basis_ko, ". 수익률·손익은 구성원마다 비중만큼의 자금으로 같은 거래를 했다고 보고 더한 것 (리밸런싱 없음)."),
      ui.assume("closed", d.basis === "mark" ? "수익률·손익·낙폭은 열린 포지션을 마크 가격으로 평가 (나갈 때 수수료 전)" : null));
  }
  function dailyCard(d) {
    const S = d.stats, need = S.ratio_min_days || 5, few = (S.days || 0) < need;
    const wait = `기록 ${fmt.int(need)}일부터 (지금 ${fmt.int(S.days || 0)}일째)`;
    const tiles = [
      ui.stat("평균 이익 ÷ 평균 손실", ratioB(S.payoff), S.payoff == null ? "이긴 거래와 진 거래가 둘 다 있어야" : "한 번 이길 때 크기 ÷ 질 때 크기"),
      ui.stat("이긴 날", S.days ? `${fmt.int(S.win_days_n)}/${fmt.int(S.days)}일` : "—", S.days ? `${fmt.pct(S.win_days, 0, false)}${S.partial_last ? " · 오늘 포함 (진행 중)" : ""}` : "날 기록 전"),
      ui.stat("하루 변동", S.daily_vol == null ? h("b", {class: "num muted"}, "—") : h("b", {class: "num"}, fmt.pct(S.daily_vol, 2, false)), few ? wait : "하루 수익률의 표준편차"),
      ui.stat("샤프 비슷한 값", ratioB(S.sharpe_like), few ? wait : "하루 평균 ÷ 하루 변동 · 하루 기준, 연율화 안 함"),
      ui.stat("소르티노 비슷한 값", ratioB(S.sortino_like), few ? wait : S.sortino_like == null ? "내려간 날이 아직 없음" : "하루 평균 ÷ 내려간 날의 변동 · 하루 기준"),
      ui.stat("칼마 비슷한 값", ratioB(S.calmar_like), few ? wait : S.calmar_like == null ? "낙폭이 없어 나눌 수 없음" : "수익률 ÷ 최대 낙폭"),
      ui.stat("고점 아래 있던 시간", h("b", {class: "num"}, fmt.pct(S.under_water_share || 0, 0, false)), `가장 길게 ${daysKo(S.longest_under_water_days)}`),
      ui.stat("회복", h("b", {class: "num"}, S.recovered ? daysKo(S.recovery_days) : S.mdd_trough_ts ? "아직 전" : "—"),
        S.recovered ? "가장 깊은 바닥에서 예전 고점까지" : S.mdd_trough_ts ? `바닥 뒤 ${daysKo((d.now - S.mdd_trough_ts) / 86400000)} 지남` : "내려간 적 없음")];
    return ui.card({plate: "하루 기준 · 회복", sub: "설명용, 판정 아님"},
      h("div", {class: "stats s4"}, tiles),
      h("p", {class: "an-note"}, "하루 = 한국 시간 자정마다 끊은 합친 자본의 변화. 비슷한 값들은 하루 기준이고 1년으로 늘려 부풀리지 않았습니다."));
  }

  // ---------------------------------------------------------------- 구성원별
  function membersCard(d, names) {
    const tot = d.stats.pnl || 0;
    const maxAbs = Math.max(1e-9, ...d.units.map((u) => Math.abs(u.pnl || 0)));
    const loo = Object.fromEntries((d.loo || []).map((x) => [x.key, x]));
    const rows = d.units.map((u, i) => {
      const lo = loo[u.key] || {}, w = (u.pnl || 0) / maxAbs;
      const link = u.kind === "strategy" ? ctx.href("strategies", u.strategy) : ctx.href("account", u.accounts[0]);
      return h("div", {class: "cb-mem", role: "listitem"},
        h("div", {class: "cb-mem-h"}, swatch(i), h("a", {href: link, class: "cb-mem-n"}, names[i]),
          h("span", {class: "cb-mem-w num"}, `비중 ${fmt.pct(u.weight, 0, false)}`)),
        h("div", {class: "cb-mem-g"},
          h("span", null, h("i", null, "혼자 수익률"), " ", pctB(u.ret, 1)),
          h("span", null, h("i", null, "기여"), " ", moneyB(u.pnl), u.share != null ? h("small", {class: "muted"}, ` (${shareWords(u.share, tot, u.pnl)})`) : null),
          h("span", null, h("i", null, "거래"), " ", h("b", {class: "num"}, `${fmt.int(u.trades)}건`))),
        h("span", {class: ["cb-cbar", w >= 0 ? "pos" : "neg"], "aria-hidden": "true"}, h("i", {style: {"--w": `${Math.abs(w) * 50}%`}})),
        lo.key ? h("p", {class: "cb-loo"}, h("i", null, "이것 빼면"), ` 수익률 ${fmt.pct(lo.ret, 1)} (지금보다 ${fmt.pct(lo.d_ret, 1)}p) · 최대 낙폭 ${fmt.pct(-(lo.mdd_pct || 0), 1)} (지금보다 ${fmt.pct(-(lo.d_mdd || 0), 1)}p)`) : null);
    });
    return ui.card({plate: "구성원별", sub: "기여 = 비중만큼의 자금으로 한 손익"},
      h("div", {class: "cb-mems", role: "list"}, rows),
      h("p", {class: "an-note"}, Math.abs(tot) > 0.005 ? "괄호 = 합친 손익 중 그 구성원의 몫 (합친 손익과 반대 방향이면 깎았거나 메운 것. 100%가 넘으면 다른 구성원이 반대로 움직여 그만큼 메우거나 깎은 것). " : "합친 손익이 아직 0 근처라 몫(%)은 보이지 않습니다. ",
        "'이것 빼면' = 같은 나누는 법으로 나머지만 합친 결과. 괄호의 %p는 지금 조합과의 차이 (낙폭은 −면 더 깊어짐)."),
      ui.assume());
  }

  // ---------------------------------------------------------------- 구성원끼리 상관
  function corrCard(d, names) {
    const c = d.corr || {};
    const body = h("div");
    const ok = (b) => ((c[b] || {}).n || 0) >= ((c[b] || {}).min || 3);
    // nobody chose: the daily basis once it has its days, the hourly one before (said in a line)
    const basis = () => st.corr || (!ok("day") && ok("hour") ? "hour" : "day");
    const paint = () => {
      const b = basis();
      const x = c[b] || {}, ready = ok(b);
      put(body, st.corr == null && b === "hour" ? h("p", {class: "an-warn"}, `하루 손익 상관은 기록 ${fmt.int((c.day || {}).min || 3)}일부터라, 지금은 1시간마다의 자본 변화로 보여 드립니다 (초반 참고용).`) : null,
        corrGrid(x.m || [], names, {swatches: true, label: "구성원끼리 상관"}),
        h("p", {class: "an-note"}, ready ? `${b === "day" ? c.day_basis_ko : c.hour_basis_ko} · ${fmt.int(x.n)}${b === "day" ? "일" : "시간"} 기록`
          : `${b === "day" ? "하루 손익 상관은 " + fmt.int(x.min) + "일" : "1시간 상관은 " + fmt.int(x.min) + "시간"} 기록부터 계산합니다 (지금 ${fmt.int(x.n || 0)}${b === "day" ? "일" : "시간"}). '—' = 아직 계산 전이거나 그동안 한 번도 움직이지 않음.`),
        ready ? pairWords(x.m, names) : null);
    };
    const seg = ui.seg([{id: "day", label: `하루 손익 (${fmt.int((c.day || {}).n || 0)}일)`}, {id: "hour", label: `1시간 변화 (${fmt.int((c.hour || {}).n || 0)}시간)`}], basis(),
      (id) => { st.corr = id; local.set("combo-corrbasis", id); paint(); motion.swap(body); }, {label: "상관 기준"});
    paint();
    return ui.card({plate: "구성원끼리 상관", sub: "1 = 똑같이, 0 = 따로, −1 = 반대로"}, seg, body,
      h("p", {class: "an-note"}, "번호는 위 구성원 순서입니다. 같이 움직이는 구성원끼리는 합쳐도 위험이 덜 나뉩니다."));
  }
  function pairWords(m, names) {
    const out = [];
    for (let i = 0; i < names.length; i++) for (let j = i + 1; j < names.length; j++) if (m[i] && m[i][j] != null) out.push([m[i][j], i, j]);
    if (!out.length) return null;
    out.sort((a, b) => b[0] - a[0]);
    const hi = out[0], lo = out[out.length - 1];
    return h("p", {class: "cb-pw"}, `가장 같이: ${names[hi[1]]} · ${names[hi[2]]} ${fmt.num(hi[0], 2)} (${corrWords(hi[0])})`,
      out.length > 1 ? ` · 가장 따로: ${names[lo[1]]} · ${names[lo[2]]} ${fmt.num(lo[0], 2)} (${corrWords(lo[0])})` : "");
  }

  // ---------------------------------------------------------------- 같은 베팅
  function sameBetCard(d, names) {
    const sb = d.same_bet || {}, r = sb.rules || {};
    const keyIdx = Object.fromEntries(d.units.map((u, i) => [u.key, i]));
    const rows = (sb.pairs || []).map((p) => {
      const i = keyIdx[p.a], j = keyIdx[p.b];
      const head = h("span", {class: "cb-pair"}, h("span", null, swatch(i), names[i]), h("span", {class: "muted"}, "·"), h("span", null, swatch(j), names[j]));
      if (p.missing) return h("div", {class: "cb-sb", role: "listitem"}, head, h("p", {class: "muted"}, "릴스는 계좌 겹침 계산에 없습니다."));
      const why = (p.why || []).map((w) => (w === "days" ? `같이 쌓인 기록 ${fmt.num(r.min_days, 0)}일 전` : `계좌마다 거래 ${fmt.int(r.min_trades)}건 전`));
      return h("div", {class: "cb-sb", role: "listitem"}, head,
        h("p", {class: "cb-sbn"}, h("span", null, h("i", null, "포지션 있을 때 같은 코인·방향"), " ", h("b", {class: "num"}, p.same_of_busy == null ? "—" : fmt.pct(p.same_of_busy, 0, false))),
          h("span", null, h("i", null, "전체 시간 중"), " ", h("b", {class: "num"}, p.same_time == null ? "—" : fmt.pct(p.same_time, 0, false))),
          h("span", null, h("i", null, "1시간 상관"), " ", h("b", {class: "num"}, p.corr == null ? "—" : fmt.num(p.corr, 2))),
          h("span", null, h("i", null, "같이 쌓인 기록"), " ", h("b", {class: "num"}, `${fmt.num(p.common_days, 1)}일`))),
        h("p", {class: "an-note"}, `가장 많이 겹친 계좌 쌍: ${(p.accounts || []).map((a) => fmt.idName(a)).join(" · ")}`,
          p.sufficient ? "" : ` · 참고만 (${why.join(", ") || "기록 부족"})`));
    });
    return ui.card({plate: "같은 베팅", sub: `지난 ${fmt.int(sb.window_days || 7)}일 · 계좌 겹침과 같은 계산`},
      rows.length ? h("div", {class: "cb-sbs", role: "list"}, rows) : h("p", {class: "muted"}, sb.note || "아직 자본 기록이 없습니다."),
      h("p", {class: "an-note"}, "같은 코인을 같은 방향으로 같은 시간에 들고 있었다면 사실상 한 베팅을 두 번 한 것입니다. ",
        `계좌 겹침 기준(같이 쌓인 기록 ${fmt.num(r.min_days || 7, 0)}일, 계좌마다 거래 ${fmt.int(r.min_trades || 20)}건)을 넘기 전에는 참고만 하세요.`));
  }

  // ---------------------------------------------------------------- 분산 효과
  function divCard(d, names) {
    const x = d.div_ratio;
    const words = x == null ? d.div_note || "아직 계산할 낙폭이 없습니다" : x < 1.15 ? "위험이 거의 안 나뉨" : x < 1.6 ? "위험이 조금 나뉨" : x < 2.5 ? "위험이 꽤 나뉨" : "위험이 많이 나뉨";
    return ui.card({plate: "분산 효과", sub: "설명용, 판정 아님"},
      d.small.early && x != null ? h("p", {class: "cb-small"}, ui.pill("표본 적음", "thin"), ` ${d.small.words} · 낙폭이 몇 번 없어 이 배수는 쉽게 바뀝니다`) : null,
      h("div", {class: "cb-div"}, h("b", {class: "num cb-divn"}, x == null ? "—" : `${fmt.num(x, 2)}배`), h("span", {class: "cb-divw"}, words)),
      h("p", {class: "an-note"}, `${d.div_basis_ko}. 1이면 합쳐도 낙폭이 그대로, 2면 따로 겪을 낙폭의 절반만 겪은 것.`),
      h("div", {class: "cb-divl"}, d.units.map((u, i) => h("span", null, swatch(i), `${names[i]} ${fmt.money(-(u.mdd_usd_scaled || 0))}`)),
        h("span", {class: "cb-divsum"}, `합친 곡선 ${fmt.money(-(d.stats.mdd_usd || 0))}`)),
      ui.assume());
  }

  // ---------------------------------------------------------------- start
  (async () => {
    put(pickCard, ui.card({plate: "구성 고르기"}, motion.shimmer(3)));
    let d;
    try { d = await loadUnits(ctx); } catch (e) {
      if (!ctx.alive()) return;
      put(pickCard, ui.card({plate: "구성 고르기"}, ui.errorBox(e, () => location.reload())));
      return;
    }
    if (!ctx.alive()) return;
    st.idx = unitIndex(d);
    const q = env.query();
    const last = local.get("combo-pick", null);
    if (q.u) apply(q);
    else if (last && last.u) apply(last);
    else { apply({u: example().join(",")}); st.example = true; }
    save();
    renderPicker();
    if (st.example) pickCard.querySelector(".cb-pick").append(h("p", {class: "an-note cb-ex"}, ui.pill("예시", "ref"), " 처음이라 목록 앞의 매매법 3개를 넣어 두었습니다 (추천 아님). 빼고 원하는 것을 넣어 보세요."));
    compute();
  })();

  return {
    el,
    update(q) {
      if (!st.idx) return;
      const same = String(q.u || "") === st.pick.join(",") && okMethod(q.w) === st.w;
      if (same && st.w !== "custom") return;
      apply(q);
      save();
      renderPicker();
      compute();
    },
    dispose() { closeAll(); clearTimeout(st.timer); st.gen++; },
  };
}
