// 흐름 · 수익 달력: one cell per Korea-time day of the season (Mon-Sun rows like a wall calendar), coloured by that day's
// change of the chosen group's MEDIAN balance (green up / red down, stronger = bigger, grey = no record); tapping a day
// opens that day's numbers: every group's median change (coin flips as the baseline), closed trades, busts, and the
// group's best and worst account of the day (links).
// Data: /api/v4/flow/calendar (dash/more/flow.py). HONESTY: a day without a single balance record is '기록 없음',
// never a zero; today is marked 진행 중; one day is mostly luck and the card says so; DeepSeek accounts carry 참고.
import {h, s, put, ui, fmt, motion, local} from "../core/pb.js";
import {LANES, SHORT} from "./flow-kit.js";
import {nav as storyNav} from "./story-kit.js";

export const CAL_API = "/api/v4/flow/calendar";
const WD = ["월", "화", "수", "목", "금", "토", "일"];
const keyOf = (id) => (LANES.find((l) => l.id === id) || {}).key;
const pctS = (v) => (v == null ? "—" : fmt.pct(v, Math.abs(v) < 0.01 ? 2 : 1));

/** calendar(ctx, {onLoad}) -> {el, set(cal), setBoard(board), setVerdict(ts), detailEl}; the season picker re-asks the server. */
export function calendar(ctx) {
  const st = {cal: null, board: null, verdictTs: null, sel: local.get("flow-cal-g") || "core", day: null, season: null};
  if (!SHORT[st.sel]) st.sel = "core";
  const picker = ui.seg(LANES.map((l) => ({id: l.id, label: SHORT[l.id]})), st.sel, (id) => {
    st.sel = id; local.set("flow-cal-g", id); render(true);
  }, {label: "묶음 고르기"});
  const seasonBox = h("div", {class: "flc-season"});
  const head = h("div", {class: "flc-wd", "aria-hidden": "true"}, WD.map((d, i) => h("span", {class: i >= 5 ? "we" : ""}, d)));
  const grid = h("div", {class: "flc-grid", role: "grid", "aria-label": "날마다 잔고 중앙값의 변화"});
  const legend = h("div", {class: "flc-legend"});
  const tally = h("div", {class: "flc-tally"});
  const detail = h("div", {class: "flc-detail", "aria-live": "polite"});
  const refBox = h("div", null, ui.refNote(null));
  const gridBox = h("div", {class: "flc-left"}, h("div", {class: "flc-pick"}, picker, seasonBox), head, grid, legend, tally);
  const el = ui.card({plate: "수익 달력", cls: "flc", label: "수익 달력", acts: [ui.pill("", "ref")]},
    h("div", {class: "flc-body"}, gridBox, detail),
    ui.note("칸 색 = 그날 끝 잔고 중앙값이 전날 끝보다 얼마나 변했나 (한국 시간 0시 기준) · 하루 성적은 운이 큽니다 · 열린 포지션은 그 시각 시세로 셈"),
    refBox);

  const rowOf = (id) => (st.board && st.board.accounts ? st.board.accounts.find((a) => a.account_id === id) : null);
  const nameOf = (id) => { const a = rowOf(id); return a ? ui.acctLabel(a) : h("span", {class: "an"}, h("span", {class: "an-n"}, fmt.idName(id))); };

  function scale(days, gk) {
    const xs = days.filter((d) => d.g && d.g[gk] && d.g[gk].chg != null).map((d) => Math.abs(d.g[gk].chg)).sort((a, b) => a - b);
    if (!xs.length) return 0.005;
    return Math.max(0.002, xs[Math.min(xs.length - 1, Math.floor(xs.length * 0.9))]);
  }

  function render(swap) {
    const c = st.cal;
    if (!c || !c.ready) {
      // designed empty state: the month's ghost cells under one line (no made-up colours)
      put(grid, Array.from({length: 28}, () => h("span", {class: "flc-c s-future", "aria-hidden": "true"})),
        h("div", {class: "flc-none"}, h("b", null, "달력 수집 전"), h("span", null, "봇이 잔고를 기록하기 시작하면 날마다 칸이 채워집니다")));
      legend.replaceChildren(); tally.hidden = true; detail.hidden = true;
      return;
    }
    tally.hidden = false; detail.hidden = false;
    const gk = keyOf(st.sel);
    const days = c.days || [];
    const sc = scale(days, gk);
    const cells = [];
    const lead = days.length ? days[0].dow : 0;
    for (let i = 0; i < lead; i++) cells.push(h("span", {class: "flc-c s-pad", "aria-hidden": "true"}));
    let lastMonth = null;
    for (const d of days) {
      const mo = d.d.slice(5, 7), dd = Number(d.d.slice(8, 10));
      const dn = lastMonth !== mo || dd === 1 ? `${Number(mo)}/${dd}` : String(dd);
      lastMonth = mo;
      const x = d.g && d.g[gk];
      const v = x ? x.chg : null;
      const shown = pctS(v);
      const zero = v == null || !/[1-9]/.test(shown);
      const tone = zero ? "flat" : v > 0 ? "up" : "down";
      const a = zero ? 0 : 0.16 + 0.64 * Math.min(1, Math.abs(v) / sc);
      const kids = [h("span", {class: "dn num"}, dn)];
      if (d.state === "done" || d.state === "today") {
        // phone: no % sign, one decimal from 0.1 % (the legend says the unit); wide: the full "+0.35%"
        const ph = v == null ? "—" : fmt.num(v * 100, Math.abs(v) >= 0.001 ? 1 : 2, true);
        kids.push(h("span", {class: "dv num"}, h("span", {class: "ph"}, ph), h("span", {class: "wd"}, shown)));
      }
      else if (d.state === "empty") kids.push(h("span", {class: "dv none"}, "—"));
      if (d.state === "today") kids.push(h("span", {class: "tag"}, "오늘"));
      if (d.verdict) kids.push(h("span", {class: "flc-flag", title: `판정 ${fmt.mmdd(d.verdict)} 09:00`, "aria-hidden": "true"}, h("i"), h("i"), h("i")));
      if (x && x.busts) kids.push(h("span", {class: "bust", title: `파산 ${x.busts}`}));
      const cls = ["flc-c", "s-" + d.state, d.state === "done" || d.state === "today" ? tone : "", d.verdict ? "verdict" : "", st.day === d.d ? "sel" : ""];
      const label = `${fmt.date(d.ts)} · ${d.state === "future" ? "아직 오지 않은 날" : d.state === "empty" ? "기록 없음" : `${SHORT[st.sel]} 중앙값 ${shown}`}`;
      const cell = d.state === "future"
        ? h("span", {class: cls, role: "gridcell", "aria-label": label, title: label, dataset: {d: d.d}}, kids)
        : h("button", {type: "button", class: cls, role: "gridcell", "aria-label": label, "aria-pressed": String(st.day === d.d), title: label,
          style: {"--a": a.toFixed(3)}, dataset: {d: d.d}, onclick: () => pick(d.d, true)}, kids);
      cells.push(cell);
    }
    put(grid, cells);
    if (swap) motion.swap(grid);
    // legend: the colour scale of this group in this season, no record, the verdict flag
    put(legend, h("span", {class: "lg"}, h("i", {class: "flc-sq down", style: {"--a": ".8"}}), h("i", {class: "flc-sq down", style: {"--a": ".35"}}),
      h("i", {class: "flc-sq flat"}), h("i", {class: "flc-sq up", style: {"--a": ".35"}}), h("i", {class: "flc-sq up", style: {"--a": ".8"}})),
    h("span", null, `칸 숫자 = % · 진한 칸 = ±${fmt.pct(sc, sc < 0.01 ? 2 : 1, false)} 넘게`), h("span", {class: "lg"}, h("i", {class: "flc-sq none"}), "기록 없음"),
    days.some((d) => d.verdict) ? h("span", {class: "lg"}, h("span", {class: "flc-flag sm", "aria-hidden": "true"}, h("i"), h("i"), h("i")), "판정") : null);
    // tally: up / down / no-record days of this group, next to the coin flips' own (the baseline)
    const count = (k) => {
      let up = 0, down = 0, none = 0;
      for (const d of days) {
        if (d.state === "empty") { none++; continue; }
        const y = d.g && d.g[k];
        if (!y || y.chg == null || d.state === "future") continue;
        const sh = pctS(y.chg);
        if (!/[1-9]/.test(sh)) continue;
        if (y.chg > 0) up++; else down++;
      }
      return {up, down, none};
    };
    const me = count(gk), cf = count("flip");
    // the 5분봉 compares with its own three 5m coin flips (their median, carried per day as f5)
    const f5 = {up: 0, down: 0};
    for (const d of days) { const y = d.f5; if (!y || y.chg == null || !/[1-9]/.test(pctS(y.chg))) continue; if (y.chg > 0) f5.up++; else f5.down++; }
    put(tally, h("div", {class: "row"}, h("i", {class: ["fk-sw", st.sel === "coin" ? "band" : st.sel]}), h("b", null, SHORT[st.sel]),
      h("span", null, "오른 날 ", h("b", {class: "num up"}, fmt.int(me.up)), " · 내린 날 ", h("b", {class: "num down"}, fmt.int(me.down)),
        me.none ? ` · 기록 없음 ${fmt.int(me.none)}` : "")),
    st.sel === "coin" ? null : st.sel === "m5" ? h("div", {class: "row base"}, h("i", {class: ["fk-sw", "band"]}), h("b", null, `5분봉 동전 ${fmt.int(c.n_flip5m || 3)}개`),
      h("span", null, `오른 날 ${fmt.int(f5.up)} · 내린 날 ${fmt.int(f5.down)}`), h("small", null, "비교 기준"))
      : h("div", {class: "row base"}, h("i", {class: ["fk-sw", "band"]}), h("b", null, "동전 봇"),
        h("span", null, `오른 날 ${fmt.int(cf.up)} · 내린 날 ${fmt.int(cf.down)}`), h("small", null, "비교 기준")));
    // the picked day (default: today, else the latest day with a record)
    if (!st.day || !days.some((d) => d.d === st.day && d.state !== "future")) {
      const has = days.filter((d) => d.state === "done" || d.state === "today");
      st.day = has.length ? has[has.length - 1].d : null;
      for (const b of grid.querySelectorAll(".flc-c")) { const on = b.dataset.d === st.day; b.classList.toggle("sel", on); if (b.tagName === "BUTTON") b.setAttribute("aria-pressed", String(on)); }
    }
    showDay(false);
  }

  function pick(day, user) {
    st.day = day;
    for (const b of grid.querySelectorAll(".flc-c")) {
      const on = b.dataset.d === day;
      b.classList.toggle("sel", on);
      if (b.tagName === "BUTTON") b.setAttribute("aria-pressed", String(on));
    }
    showDay(user);
  }

  function bars(d, gk) {
    // every group's median change that day on one centred scale (coin flips = the baseline row)
    const rows = LANES.filter((l) => d.g && d.g[l.key]).map((l) => ({id: l.id, ko: SHORT[l.id], v: d.g[l.key].chg}));
    if (st.sel === "m5" && d.f5) rows.splice(rows.findIndex((r) => r.id === "coin"), 0, {id: "m5", f5: true, ko: `5분봉 동전 ${fmt.int(d.f5.n)}개`, v: d.f5.chg});
    const mx = Math.max(0.001, ...rows.map((r) => Math.abs(r.v || 0)));
    return h("div", {class: "flc-bars", role: "list", "aria-label": "묶음마다 그날 중앙값 변화"}, rows.map((r) => {
      const w = r.v == null ? 0 : Math.abs(r.v) / mx * 50;
      const sh = pctS(r.v), zero = r.v == null || !/[1-9]/.test(sh);
      return h("div", {class: ["flc-bar", r.id, r.id === st.sel && !r.f5 ? "me" : "", r.f5 ? "f5" : "", r.id === "coin" ? "base" : ""], role: "listitem"},
        h("span", {class: "k"}, h("i", {class: ["fk-sw", r.id === "coin" ? "band" : r.id]}), r.ko, r.id === "coin" ? h("small", null, "기준") : null),
        h("span", {class: "track"}, h("i", {class: ["b", zero ? "" : r.v > 0 ? "up" : "down"], style: {"--w": w.toFixed(1) + "%"}})),
        h("b", {class: ["num", zero ? "" : r.v > 0 ? "up" : "down"]}, sh));
    }));
  }

  /** The picked day elsewhere: its highlight story (#/story/<YYYY-MM-DD>; closing the story comes back here) and its
   *  meeting conclusions (#/digest/day?d=<YYYY-MM-DD>). */
  function dayLinks(day) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(day || ""))) return null;
    return h("div", {class: "row wrap flc-links"},
      h("a", {class: "btn-line", href: ctx.href("story", day), onclick: () => { storyNav.from = location.hash || ctx.href("flow"); }}, "그날 하이라이트"),
      h("a", {class: "btn-line", href: ctx.href("digest", "day", {d: day})}, "그날 회의 결론"));
  }

  function showDay(user) {
    const c = st.cal;
    const d = c && (c.days || []).find((x) => x.d === st.day);
    if (!d) { put(detail, h("p", {class: "muted"}, "날을 누르면 그날 숫자가 여기에 나옵니다.")); return; }
    const gk = keyOf(st.sel);
    const x = d.g && d.g[gk];
    const when = h("div", {class: "flc-dh"}, h("b", null, fmt.date(d.ts)), h("span", {class: "muted"}, `${fmt.int(d.i + 1)}일째`),
      d.state === "today" ? ui.pill(`진행 중 · ${fmt.hm(c.now)}까지`, "accent") : null);
    if (!x) {
      put(detail, when, h("p", {class: "flc-nodata"}, d.state === "empty" ? "이날은 잔고 기록이 없습니다 (봇이 멈췄거나 기록 전). 0으로 채우지 않습니다." : "이 묶음은 이날 기록이 없습니다."),
        dayLinks(d.d));
      if (user) motion.swap(detail);
      return;
    }
    const best = x.best, worst = x.worst;
    const one = (c.n || {})[gk] === 1;
    const acct = (k, a) => a ? h("a", {class: "flc-acct", href: ctx.href("account", a.id)},
      h("span", {class: "k"}, k), nameOf(a.id), st.sel === "ds" ? ui.pill("", "ref") : null,
      h("b", {class: ["num", fmt.tone(a.chg, pctS(a.chg))]}, pctS(a.chg)), h("span", {class: "go", "aria-hidden": "true"}, "→")) : null;
    put(detail, when,
      h("div", {class: "flc-hero"}, h("i", {class: ["fk-sw", st.sel === "coin" ? "band" : st.sel]}),
        h("span", {class: "k"}, `${SHORT[st.sel]} 중앙값`),
        h("b", {class: ["num", "big", fmt.tone(x.chg, pctS(x.chg))]}, pctS(x.chg)),
        h("span", {class: "muted num"}, `끝 잔고 ${fmt.money(x.med)}`)),
      bars(d, gk),
      h("div", {class: "flc-stats"},
        ui.stat("닫힌 거래", fmt.int(x.trades), x.trades ? `이김 ${fmt.int(x.wins)} (${fmt.pct(x.wins / x.trades, 0, false)})` : null),
        ui.stat("오른 계좌", h("b", {class: "num up"}, fmt.int(x.up)), `내린 계좌 ${fmt.int(x.down)}`),
        ui.stat("강제청산", fmt.int(x.liq), x.busts ? h("span", {class: "s down"}, `파산 ${fmt.int(x.busts)}`) : h("span", {class: "s"}, "파산 0"))),
      one ? acct("그날 계좌", best) : h("div", {class: "flc-accts"}, acct("가장 많이 오른 계좌", best), acct("가장 많이 내린 계좌", worst)),
      h("p", {class: "flc-pnl"}, h("span", {class: "muted"}, "그날 닫힌 거래 손익 합"), h("b", {class: ["num", fmt.tone(x.pnl)]}, fmt.usdt(x.pnl, true))),
      ui.assume("closed", "계좌 변화 = 그날 끝 잔고 ÷ 전날 끝 잔고"),
      dayLinks(d.d));
    if (user) motion.swap(detail);
  }

  function seasons(c) {
    if (!c || !c.ready || (c.seasons || 0) < 2) { seasonBox.replaceChildren(); return; }
    const opts = Array.from({length: c.seasons}, (_, k) => ({id: String(k), label: `${k + 1}번째 30일`}));
    put(seasonBox, ui.seg(opts, String(c.season), (k) => { st.season = Number(k); load(true); }, {label: "30일 묶음 고르기", scroll: true}));
  }

  // user: the season picker (animate the swap); the 5-minute refresh redraws only when the answer changed
  async function load(user) {
    let c;
    try { c = await ctx.api(CAL_API + (st.season != null ? `?season=${st.season}` : "")); } catch (e) {
      if (!st.cal) put(grid, ui.errorBox(e, () => load(true)));
      return;
    }
    if (!ctx.alive()) return;
    const sig = JSON.stringify(c);
    if (sig === st.sig) return;
    st.sig = sig;
    st.cal = c;
    seasons(c);
    render(user === true);
  }

  return {el, load: () => load(false), detail,
    setBoard(b) { const first = !st.board; st.board = b; if (first && st.cal) showDay(false); },
    setVerdict(ts) { if (ts === st.verdictTs) return; st.verdictTs = ts; put(refBox, ui.refNote(ts)); }};
}
