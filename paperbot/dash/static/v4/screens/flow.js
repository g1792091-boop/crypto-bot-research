// #/flow — 흐름 (홈 › 흐름): how the four groups moved over the run.
//   1. 묶음 레이스: each group's median balance over time (기존 36 · 딥시크 44 · 5분봉 · 동전 봇), the coin flips drawn
//      as the baseline (their middle 50 % as a band + their median dashed), the road ahead to the verdict with its flag,
//      labels at the right edge in the current order; a replay from day 1 to now (D+n counter, labels change places
//      as the order changes); drag / hover to read any hour.
//   2. 지금 묶음별: median now, above / below the same-timeframe coin-flip median (the board's rule), busts.
//   3. 수익 달력 (flow-cal.js).
// Data: /api/v4/flow/race and /api/v4/flow/calendar (dash/more/flow.py), the shared board (derive.groupStats, so the
// numbers agree with 홈 and 순위표) and the summary (verdict time).
// HONESTY: everything here is '참고' until the verdict (refNote); no winner words; the replay runs only when pressed,
// never under prefers-reduced-motion, and pauses when the page is hidden; money captions via ui.assume().
import {h, put, ui, fmt, derive, motion, local} from "../core/pb.js";
import {RACE_API, LANES, SHORT, raceChart, laneLegend, prep, dayN, laneKo} from "./flow-kit.js";
import {calendar} from "./flow-cal.js";

const STEP_KO = (ms) => (ms >= 86400000 ? "하루" : ms >= 14400000 ? "4시간" : ms >= 3600000 ? "1시간" : ms >= 900000 ? "15분" : "5분");

export async function mount(el, ctx) {
  ctx.setTitle("흐름");
  const st = {m: null, board: null, verdictTs: null, state: "idle"};

  // ---------------------------------------------------------------- 1. the race
  const dBig = h("b", {class: "fl-dn"}, "D+—");
  const dWhen = h("span", {class: "fl-when num"}, "");
  const playBtn = h("button", {type: "button", class: "btn-y fl-play", onclick: () => toggle()}, "▶ 처음부터 다시 보기");
  const reducedNote = h("span", {class: "muted fl-rm", hidden: true}, "움직임 줄이기 설정: 그래프를 눌러 날짜를 고르세요");
  const fullBtn = h("button", {type: "button", class: "btn-line fl-full", hidden: true, "aria-pressed": "false",
    onclick: () => { st.full = !st.full; chart.full(st.full); }}, "전체 범위");
  const clipNote = h("p", {class: "fl-clip", hidden: true});
  // the x axis: the viewer's own choice if they made one, else "auto" (flow-kit: the 30-day road from day 10 on)
  const saved = local.get("flow-race-mode");
  const mode0 = saved === "now" || saved === "road" ? saved : "auto";
  const chart = raceChart({onTime, onState, onClip, mode: mode0});
  const modeSeg = ui.seg([{id: "road", label: "30일 길"}, {id: "now", label: "지금까지 크게"}], mode0 === "auto" ? "now" : mode0,
    (id) => { local.set("flow-race-mode", id); chart.mode(id); }, {label: "가로축"});
  chart.classList.add("fl-chart");
  const legend = laneLegend({onPick: (id) => chart.focus(id)});
  const stepNote = h("span");
  const refRace = h("div", null, ui.refNote(null));
  const raceCard = ui.card({hero: true, cls: "fl-race", label: "묶음 레이스"},
    h("div", {class: "fl-rhead"}, h("div", {class: "fl-rtitle"}, h("div", {class: "row"}, ui.plate("묶음 레이스"), ui.pill("", "ref")),
      h("h2", null, "네 묶음이 ", h("em", null, "30일"), " 동안 어떻게 움직였나")),
    h("div", {class: "fl-dbox"}, dBig, dWhen)),
    h("div", {class: "fl-chartwrap"}, chart),
    clipNote,
    h("div", {class: "fl-ctl"}, legend, h("span", {class: "grow"}), modeSeg, fullBtn, playBtn, reducedNote),
    ui.note("선 = 묶음마다 계좌 잔고의 중앙값 (시작 대비 %) · 회색 띠 = 동전 봇 가운데 50% · 빨간 눈금 = 파산 · 그래프를 누르면 그때 순서"),
    ui.disclosure("어떻게 셌나", ui.note(h("span", null, "중앙값 = 묶음 안 계좌를 잔고 순으로 세웠을 때 가운데 계좌의 잔고. "), stepNote,
      ". 잔고는 봇이 5분마다 기록한 평가 잔고(열린 포지션은 그 시각 시세로)이고, 기록이 없는 시간은 바로 앞 값을 이어 씁니다. 점선 = 동전 봇 15개 중앙값, 띠 = 그중 가운데 50%. ",
      "5분봉을 고르면 5분봉 동전 3개의 중앙값(점선)도 보입니다. 오른쪽 순서는 중간 기록일 뿐 판정이 아닙니다.")),
    refRace, ui.assume());

  // ---------------------------------------------------------------- 2. each group now (the board's numbers)
  const nowBody = h("div", {class: "fl-now", role: "table", "aria-label": "지금 묶음별"}, motion.shimmer(4));
  const refNow = h("div", null, ui.refNote(null));
  const nowCard = ui.card({plate: "지금 묶음별", cls: "fl-nowcard", acts: [h("a", {class: "btn-line", href: ctx.href("board")}, "순위표 →")]},
    h("div", {class: "fl-nhead", "aria-hidden": "true"}, h("span", null, "묶음"), h("span", null, "중앙값"), h("span", null, "같은 봉 동전 봇보다"), h("span", null, "파산")),
    nowBody,
    ui.note("지금 = 닫힌 거래 기준 잔고 (홈·순위표와 같은 값) · 위·아래 = 같은 봉 동전 봇 중앙값보다 위·아래인 계좌 수"),
    refNow, ui.assume());
  const rows = new Map();

  // ---------------------------------------------------------------- 3. the calendar
  const cal = calendar(ctx);

  el.append(ui.screenHead("흐름", "묶음끼리 30일 동안 어떻게 움직였나"),
    h("div", {class: "fl-top"}, raceCard, nowCard), cal.el);

  if (motion.reduced()) { playBtn.hidden = true; reducedNote.hidden = false; }

  // ================================================================ behaviour
  function onTime(t) {
    const m = st.m;
    if (!m) return;
    dBig.textContent = `D+${dayN(t, m.start)}`;
    dWhen.textContent = t >= m.now - 1000 && st.state !== "playing" ? `지금 · ${fmt.mmdd(t)} ${fmt.hm(t)}` : `${fmt.mmdd(t)} ${fmt.hm(t)}`;
  }
  function onState(s) {
    st.state = s;
    raceCard.classList.toggle("playing", s === "playing");
    playBtn.textContent = s === "playing" ? "❚❚ 멈춤" : s === "paused" ? "▶ 이어 보기" : "▶ 처음부터 다시 보기";
    playBtn.setAttribute("aria-pressed", String(s === "playing"));
    if (s === "idle" && st.pending !== undefined) { const m = st.pending; st.pending = undefined; apply(m); }
  }
  function onClip(far, clipped) {
    fullBtn.hidden = !far.length;
    fullBtn.textContent = st.full ? "가까이 보기" : "전체 범위";
    fullBtn.setAttribute("aria-pressed", String(!!st.full));
    clipNote.hidden = !clipped.length;
    if (clipped.length) put(clipNote, h("b", null, clipped.map(laneKo).join(", ")), "은 1계좌라 크게 흔들려 그래프 밖으로 나갑니다 (↑·↓, 숫자는 실제 값) · '전체 범위'로 다 보기");
  }
  function toggle() {
    if (!st.m) return;
    if (chart.playing()) chart.pause(); else chart.play();
  }
  // the replay stops with the page: hidden tab -> paused; leaving the screen -> stopped
  ctx.listen(document, "visibilitychange", () => { if (document.visibilityState === "hidden") chart.pause(); });
  ctx.track(() => chart.pause());

  function apply(m) {
    st.m = m;
    chart.set(m);
    legend.set(m);
    playBtn.disabled = !m;
    playBtn.hidden = !m || motion.reduced();
    modeSeg.hidden = !m;
    stepNote.textContent = m ? `선은 ${STEP_KO(m.step)}마다 한 점` : "";
    if (m) modeSeg.set(chart.resolvedMode());
    if (m) onTime(m.now);
  }
  async function loadRace() {
    let d;
    try { d = await ctx.api(RACE_API + "?step=auto"); } catch (e) {
      if (!st.m) put(chart.querySelector(".fk-svg"), ui.errorBox(e, loadRace));
      return;
    }
    if (!ctx.alive()) return;
    const m = prep(d);
    if (chart.playing()) { st.pending = m; return; }      // never swap the data under a running replay
    apply(m);
    if (!m) { dBig.textContent = d && d.start ? `D+${dayN(d.now || Date.now(), d.start)}` : "D+—"; dWhen.textContent = "곡선 수집 전"; }
  }

  function renderNow() {
    const b = st.board;
    if (!b) return;
    const gs = derive.groupStats(b);
    const flips5 = (b.accounts || []).filter(fmt.isFlip5).length;
    const kids = [];
    for (const l of LANES) {
      const x = gs.groups[l.id];
      if (!x) continue;
      let r = rows.get(l.id);
      if (!r) {
        r = {med: ui.liveNum(null, {format: "pct", tone: true, tag: "b", cls: "fl-med"}), wal: h("span", {class: "muted num"}),
          vs: h("span", {class: "fl-vs"}), bust: h("b", {class: "num"}), n: h("small")};
        r.el = h("div", {class: ["fl-nrow", l.id]},
          h("span", {class: "fl-ng"}, h("i", {class: ["fk-sw", l.id === "coin" ? "band" : l.id]}), h("span", {class: "fl-name"}, SHORT[l.id], r.n)),
          h("span", {class: "fl-nm"}, r.med, r.wal), r.vs, h("span", {class: "fl-nb"}, r.bust));
        rows.set(l.id, r);
      }
      r.n.textContent = `${fmt.int(x.n)}계좌`;
      r.med.update(x.medRet);
      r.wal.textContent = fmt.money(x.medWallet);
      r.bust.textContent = fmt.int(x.bust);
      r.bust.className = "num " + (x.bust ? "down" : "muted");
      if (l.id === "coin") put(r.vs, h("span", {class: "fl-base"}, "비교 기준"));
      else {
        const tot = x.above + x.below;
        const w = tot ? x.above / tot * 100 : 0;
        put(r.vs, h("span", {class: "fl-wl", role: "img", "aria-label": `위 ${x.above}, 아래 ${x.below}`}, h("i", {style: {"--w": w.toFixed(1) + "%"}})),
          h("span", {class: "fl-wlt"}, "위 ", h("b", {class: "num up"}, fmt.int(x.above)), " · 아래 ", h("b", {class: "num down"}, fmt.int(x.below)),
            l.id === "m5" ? h("small", null, ` · 동전 ${fmt.int(flips5)}개와`) : null, l.id === "ds" ? ui.pill("", "ref") : null));
      }
      kids.push(r.el);
    }
    if (kids.some((k, i) => nowBody.children[i] !== k) || nowBody.children.length !== kids.length) put(nowBody, kids);
  }

  ctx.watch("board", (b) => { if (!b) return; st.board = b; renderNow(); cal.setBoard(b); });
  ctx.watch("summary", (s) => {
    const rs = (s && s.restart) || {};
    const ts = rs.ready ? rs.verdict_ts : (s && s.next_checkpoint && s.next_checkpoint.ts) || null;
    chart.events(s && s.events);
    if (ts === st.verdictTs) return;
    st.verdictTs = ts;
    put(refRace, ui.refNote(ts)); put(refNow, ui.refNote(ts));
    cal.setVerdict(ts);
  });
  ctx.every(300000, loadRace, {now: false});
  ctx.every(300000, cal.load);
  await loadRace();
}

export function unmount() {}
