// 조합 성과 › 전체 상관 지도 (/api/v4/combo/corr): the 36 x 36 correlation of the strategies' daily P&L (each strategy =
// its 4 timeframe accounts summed), or of one timeframe's 36 accounts; the hourly change as the early basis. Tapping a
// cell names the pair and offers "이 둘로 조합 만들기". Under it: the pairs that moved together most, the most opposite
// (hedging) pairs, and the 계좌 겹침 pairs.top table (correlation, same-time share, common days) with its real
// thresholds as filling bars while no pair is there yet. State in the address (?level=&tf=&basis=). 설명용, 판정 아님.
import {h, s, put, ui, fmt, motion, local} from "../core/pb.js";
import {corrStyle, corrWords, verdictTs} from "./combo-kit.js";
import {progressBar} from "./analysis-kit.js";

const TFS = ["15m", "30m", "1h", "4h"];

export function mapTab(env) {
  const {ctx} = env;
  const q0 = env.query();
  const st = {level: q0.level === "account" ? "account" : local.get("combo-maplevel", "strategy"),
    tf: TFS.includes(q0.tf) ? q0.tf : local.get("combo-maptf", "1h"), basis: q0.basis === "hour" ? "hour" : local.get("combo-mapbasis", "day"),
    gen: 0, sel: null, auto: false};
  // nobody chose a basis (no ?basis=, nothing remembered): while the daily one has too few days, show the hourly one and
  // say so (the first days would otherwise be an empty grey map)
  st.chosen = q0.basis === "hour" || local.get("combo-mapbasis", null) != null;
  if (st.level !== "account" && st.level !== "strategy") st.level = "strategy";
  const ctl = h("div", {class: "cb-ctl"});
  const body = h("div", {class: "stack"});
  const el = h("div", {class: "stack cb-map"}, ctl, body);

  function controls() {
    put(ctl,
      h("div", {class: "cb-mrow"}, h("span", {class: "cb-k"}, "단위"), ui.seg([{id: "strategy", label: "매매법 (봉 4개 합)"}, {id: "account", label: "봉 하나씩"}], st.level,
        (id) => { st.level = id; local.set("combo-maplevel", id); load(); }, {label: "단위"})),
      st.level === "account" ? h("div", {class: "cb-mrow"}, h("span", {class: "cb-k"}, "봉"), ui.seg(TFS.map((t) => ({id: t, label: fmt.tfKo(t)})), st.tf,
        (id) => { st.tf = id; local.set("combo-maptf", id); load(); }, {label: "봉 고르기"})) : null,
      h("div", {class: "cb-mrow"}, h("span", {class: "cb-k"}, "기준"), ui.seg([{id: "day", label: "하루 손익"}, {id: "hour", label: "1시간 변화 (초반 참고)"}], st.basis,
        (id) => { st.basis = id; st.chosen = true; st.auto = false; local.set("combo-mapbasis", id); load(); }, {label: "상관 기준"})));
  }

  async function load() {
    const g = ++st.gen;
    st.sel = null;
    controls();
    env.setQuery({level: st.level === "account" ? "account" : null, tf: st.level === "account" ? st.tf : null, basis: st.basis === "hour" && !st.auto ? "hour" : null});
    put(body, ui.card({plate: "전체 상관 지도", sub: "계산 중"}, motion.shimmer(5)));
    const qs = new URLSearchParams({level: st.level, basis: st.basis});
    if (st.level === "account") qs.set("tf", st.tf);
    let d;
    try { d = await ctx.api(`/api/v4/combo/corr?${qs.toString()}`); } catch (e) {
      if (g !== st.gen || !ctx.alive()) return;
      put(body, ui.card({plate: "전체 상관 지도"}, ui.errorBox(e, () => load())));
      return;
    }
    if (g !== st.gen || !ctx.alive()) return;
    if (d && d.pending) {
      put(body, ui.card({plate: "전체 상관 지도", sub: "계산 중"}, h("p", {class: "muted"}, d.note || "서버가 계산하는 중입니다."), motion.shimmer(4)));
      ctx.timeout(() => { if (g === st.gen) load(); }, 2500);
      return;
    }
    if (d && d.error) { put(body, ui.card({plate: "전체 상관 지도"}, h("p", {class: "muted"}, String(d.error)))); return; }
    if (!st.chosen && !st.auto && d.basis === "day" && !d.ready) { st.auto = true; st.basis = "hour"; load(); return; }
    paint(d);
  }

  function paint(d) {
    const units = d.units || [];
    const detail = h("div", {class: "cb-hsel", "aria-live": "polite"}, h("p", {class: "muted"}, "칸을 누르면 두 매매법과 상관이 여기 나옵니다."));
    const head = ui.card({plate: "전체 상관 지도", sub: `${d.level === "account" ? fmt.tfKo(d.tf) + "봉 계좌 36개" : "매매법 36개 (봉 4개 합)"} · ${d.basis === "day" ? "하루 손익" : "1시간 변화"}`},
      st.auto && d.basis === "hour" ? h("p", {class: "an-warn"}, "하루 손익 상관은 기록 3일부터라, 지금은 1시간마다의 자본 변화로 보여 드립니다 (초반 참고용 · 위 '기준'에서 바꿀 수 있음).") : null,
      d.ready ? null : h("p", {class: "cb-small"}, ui.pill("표본 적음", "thin"),
        ` ${d.basis === "day" ? `하루 손익 상관은 ${fmt.int(d.need)}일 기록부터 계산합니다 (지금 ${fmt.int(d.n)}일). 그 전에는 칸이 비어 있습니다.`
          : `1시간 상관은 ${fmt.int(d.need)}시간 기록부터 (지금 ${fmt.int(d.n)}시간).`}`),
      d.ready ? null : progressBar(d.basis === "day" ? `하루 손익 ${fmt.int(d.need)}일까지` : `1시간 기록 ${fmt.int(d.need)}개까지`,
        `지금 ${fmt.int(d.n)}${d.basis === "day" ? "일" : "시간"} · ${fmt.num(d.run_days, 1)}일째`, Math.min(1, (d.n || 0) / (d.need || 1))),
      heat(d, units, detail), detail,
      h("div", {class: "cb-hleg"}, h("span", null, h("i", {class: "cb-hl pos"}), "같이 움직임 (+)"), h("span", null, h("i", {class: "cb-hl neg"}), "반대로 움직임 (−)"),
        h("span", null, h("i", {class: "cb-hl none"}), "아직 계산 전 / 움직임 없음"), h("span", {class: "muted"}, "진할수록 강함")),
      h("p", {class: "an-note"}, `${d.basis_ko} · ${fmt.int(d.n)}${d.basis === "day" ? "일" : "시간"} 기록 · 번호 = 아래 목록 순서 (이름 순, 순위 아님)`),
      nameList(units));
    put(body, head, pairsCard(d, units), overlapCard(d));
    motion.swap(body);
  }

  function heat(d, units, detail) {
    // cells of 14-22 px: as big as the card allows on a PC; on a phone the map keeps 14 px cells (12 px axis numbers)
    // and scrolls inside its own box, never the page
    const k = units.length, pad = 26, avail = (body.clientWidth || 360) - 40;
    const c = Math.max(14, Math.min(22, Math.floor((avail - pad) / Math.max(1, k))));
    const W = pad + k * c + 2, H = pad + k * c + 2;
    const kids = [];
    for (let j = 0; j < k; j++) {
      if (j % 5 === 0 || j === k - 1) {
        kids.push(s("text", {class: "cb-hax", x: pad + j * c + c / 2, y: pad - 6, "text-anchor": "middle"}, String(j + 1)));
        kids.push(s("text", {class: "cb-hax", x: pad - 4, y: pad + j * c + c / 2 + 4, "text-anchor": "end"}, String(j + 1)));
      }
    }
    for (let i = 0; i < k; i++) {
      for (let j = 0; j < k; j++) {
        const r = i === j ? null : ((d.m || [])[i] || [])[j];
        kids.push(s("rect", {class: ["cb-hc", i === j ? "diag" : ""], x: pad + j * c, y: pad + i * c, width: c - 1, height: c - 1, rx: 2,
          style: i === j ? {fill: "var(--line-2)"} : corrStyle(r), dataset: {i, j}, tabindex: i < j ? "0" : null,
          "aria-label": i === j ? null : `${units[i].name_ko} · ${units[j].name_ko}: ${r == null ? "계산 전" : fmt.num(r, 2)}`}));
      }
    }
    const svg = s("svg", {class: "cb-heat", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": "상관 지도"}, kids);
    const pick = (e) => {
      const t = e.target.closest ? e.target.closest("rect.cb-hc") : null;
      if (!t || t.classList.contains("diag")) return;
      const i = Number(t.dataset.i), j = Number(t.dataset.j);
      svg.querySelectorAll("rect.sel").forEach((x) => x.classList.remove("sel"));
      t.classList.add("sel");
      const r = ((d.m || [])[i] || [])[j];
      const a = units[i], b = units[j];
      put(detail, h("p", null, h("b", null, `${i + 1}. ${a.name_ko}`), " · ", h("b", null, `${j + 1}. ${b.name_ko}`), `: 상관 ${r == null ? "—" : fmt.num(r, 2)} (${corrWords(r)})`,
        h("span", {class: "muted"}, ` · 거래 ${fmt.int(a.trades)}건 · ${fmt.int(b.trades)}건`)),
        h("a", {class: "btn-line", href: ctx.href("combo", "build", {u: `${a.key},${b.key}`})}, "이 둘로 조합 만들기 →"));
    };
    svg.addEventListener("click", pick);
    svg.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(e); } });
    return h("div", {class: "cb-heatw", "data-noswipe": ""}, svg);
  }

  function nameList(units) {
    return ui.disclosure(`번호별 이름 보기 (${fmt.int(units.length)}개)`, h("ol", {class: "cb-names"}, units.map((u) => h("li", null, u.name_ko))));
  }

  function pairList(list, units, empty) {
    const name = Object.fromEntries(units.map((u, i) => [u.key, `${i + 1}. ${u.name_ko}`]));
    if (!list.length) return h("p", {class: "muted"}, empty);
    return h("div", {class: "cb-plist", role: "list"}, list.map((p) => h("a", {class: "lrow click an-row", role: "listitem",
      href: ctx.href("combo", "build", {u: `${p.a},${p.b}`}), title: "이 둘로 조합 만들기"},
    h("span", {class: "rk num"}, fmt.num(p.r, 2)), h("span", {class: "lname an-wrap"}, name[p.a] || p.a, h("span", {class: "muted"}, " · "), name[p.b] || p.b),
    h("span", {class: "ret"}, "→"), h("span", {class: "meta"}, h("span", null, corrWords(p.r))))));
  }
  function pairsCard(d, units) {
    const wait = d.ready ? null : "기록이 쌓이면 보여 드립니다 (지금은 비교할 날이 모자랍니다).";
    return ui.card({plate: "같이 · 반대로 움직인 쌍", sub: "누르면 그 둘로 조합 만들기"},
      h("div", {class: "cb-two"},
        h("div", null, h("p", {class: "cb-k"}, "가장 같이 움직인 쌍"), pairList(d.top || [], units, wait || "상관을 잴 수 있는 쌍이 없습니다.")),
        h("div", null, h("p", {class: "cb-k"}, "가장 반대로 움직인 쌍 (헤지)"), pairList(d.hedge || [], units, wait || "반대로 움직인 쌍이 없습니다 (모두 0 이상)."))),
      h("p", {class: "an-note"}, "같이 움직이는 둘은 합쳐도 위험이 덜 나뉘고, 반대로 움직이는 둘은 서로의 손실을 메워 줄 수 있습니다. 앞으로도 그렇다는 뜻은 아닙니다."),
      ui.refNote(verdictTs()));
  }

  function overlapCard(d) {
    const ov = d.overlap || {};
    const top = ov.top || [];
    const bars = [];
    if (!top.length) {
      bars.push(progressBar(`같이 쌓인 기록 ${fmt.num(ov.min_days || 7, 0)}일`, `지금 가장 긴 계좌 ${fmt.num(ov.max_days || 0, 1)}일`, Math.min(1, (ov.max_days || 0) / (ov.min_days || 7))));
      bars.push(progressBar(`계좌마다 거래 ${fmt.int(ov.min_trades || 20)}건 (지난 ${fmt.int(ov.window_days || 7)}일)`, `지금 가장 많은 계좌 ${fmt.int(ov.max_trades || 0)}건`,
        Math.min(1, (ov.max_trades || 0) / (ov.min_trades || 20))));
    }
    const tbl = top.length ? ui.table([
      {label: "계좌 A", l: true, get: (p) => fmt.idName(p.a)},
      {label: "계좌 B", l: true, get: (p) => fmt.idName(p.b)},
      {label: "1시간 상관", get: (p) => fmt.num(p.corr, 2)},
      {label: "같은 시각 같은 베팅", get: (p) => fmt.pct(p.same_time, 0, false)},
      {label: "포지션 있을 때", get: (p) => fmt.pct(p.same_of_busy, 0, false)},
      {label: "같이 쌓인 날", get: (p) => `${fmt.num(p.common_days, 1)}일`}], top.slice(0, 20),
    (p) => ctx.go("combo", "build", {u: `${p.a},${p.b}`})) : null;
    return ui.card({plate: "같은 베팅 쌍", sub: `계좌 겹침 기준 · 지난 ${fmt.int(ov.window_days || 7)}일`},
      tbl || h("div", null, h("p", {class: "muted"}, "아직 기준을 넘은 계좌 쌍이 없습니다. 기준은 계좌 겹침 화면과 같습니다:"), ...bars),
      h("p", {class: "an-note"}, `같은 시각 같은 베팅 = 5분마다 둘이 같은 코인·같은 방향을 들고 있던 비율 (전체 시간 중). 포지션 있을 때 = 둘 중 하나라도 들고 있던 시간 중. `,
        top.length ? `기준을 넘은 쌍 ${fmt.int(ov.sufficient || 0)}/${fmt.int(ov.pairs || 0)}개 중 상관 높은 순 20개. 줄을 누르면 그 둘로 조합 만들기.` : ""));
  }

  load();
  return {
    el,
    update(q) {
      st.level = q.level === "account" ? "account" : "strategy";
      if (TFS.includes(q.tf)) st.tf = q.tf;
      st.basis = q.basis === "hour" ? "hour" : "day";
      st.chosen = true;
      st.auto = false;
      load();
    },
    dispose() { st.gen++; },
  };
}
