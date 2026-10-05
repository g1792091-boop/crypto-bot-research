// #/story[/YYYY-MM-DD] — 오늘의 하이라이트: one Korea-time day of the run in seven full-screen pages, story style.
// Progress bars at the top; tap the right side (or swipe left, →) for the next page, the left side (swipe right, ←)
// for the one before; each page moves on by itself after about 6 s, which stops while a finger (or the mouse) holds
// the page, while the day picker is open, while the page is hidden and when 멈춤 is pressed. Under
// prefers-reduced-motion nothing moves by itself. The day picker lists the run's days (seen ones dim: per viewer).
// Data: GET /api/v4/story?day= (dash/more/story.py). The stage is a dialog over the whole app (in <body>, so the
// router's screen fade never moves it); it leaves with the screen. Closing goes back to where it was opened from.
import {h, ui, fmt, motion} from "../core/pb.js";
import {PAGES, nav, markSeen, isSeen, ringSvg, dayWord, pixIcon} from "./story-kit.js";
import {PAGE_LIST} from "./story-pages.js";

let inst = null;            // the mounted story (update() of a new #/story/<day> reaches it); null when left

export async function mount(el, ctx) {
  ctx.setTitle("오늘의 하이라이트");
  el.append(ui.screenHead("오늘의 하이라이트", "하루를 일곱 장으로"));
  const auto = !motion.reduced();
  const st = {day: ctx.params.arg || null, d: null, i: 0, user: false, held: false, hidden: document.hidden, picker: false,
    done: false, req: 0, down: null, eatUntil: 0};

  // ---------------------------------------------------------------- the stage
  const bars = h("div", {class: "st-bars", "aria-hidden": "true"}, Array.from({length: PAGES}, () => h("i", null, h("b"))));
  const dayEl = h("span", {class: "st-day"}, "불러오는 중");
  const pauseBtn = h("button", {class: "st-ib st-pause", type: "button", "aria-label": "멈춤", hidden: !auto, onclick: () => { st.user = !st.user; applyPause(); }},
    h("span", {class: "st-pz", "aria-hidden": "true"}));
  const pickBtn = h("button", {class: "st-ib st-pickb", type: "button", "aria-label": "다른 날 고르기", "aria-expanded": "false", onclick: () => togglePicker()},
    pixIcon("cal", 16), h("span", {class: "st-ibt"}, "날짜"));
  const closeBtn = h("button", {class: "st-ib st-x", type: "button", "aria-label": "닫기", onclick: () => close()}, h("span", {"aria-hidden": "true"}, "✕"));
  const avNum = h("b");
  const head = h("div", {class: "st-head"}, h("span", {class: "st-av sk-ava"}, ringSvg({size: 36}), h("span", {class: "sk-in"}, avNum)),
    h("div", {class: "st-ht"}, h("b", null, "오늘의 하이라이트"), dayEl), h("span", {class: "grow"}), pickBtn, pauseBtn, closeBtn);
  const body = h("div", {class: "st-body"});
  const count = h("span", {class: "st-count num"});
  const live = h("p", {class: "st-live", "aria-live": "polite"});
  const foot = h("div", {class: "st-foot"}, ui.assume(), count);
  const prevBtn = h("button", {class: "st-nav prev", type: "button", "aria-label": "이전 장", onclick: () => go(st.i - 1)}, "‹");
  const nextBtn = h("button", {class: "st-nav next", type: "button", "aria-label": "다음 장", onclick: () => go(st.i + 1)}, "›");
  const pickList = h("div", {class: "st-days", role: "list"});
  const picker = h("div", {class: "st-pick bsheet", hidden: true, role: "dialog", "aria-label": "날짜 고르기"},
    h("div", {class: "st-pick-h"}, h("b", null, "다른 날 보기"), h("span", {class: "muted"}, "실험의 하루하루 · 본 날은 흐리게"),
      h("span", {class: "grow"}), h("button", {class: "st-ib", type: "button", "aria-label": "날짜 고르기 닫기", onclick: () => togglePicker(false)}, "✕")),
    pickList);
  const frame = h("div", {class: "st-frame"}, bars, head, body, foot, live, picker);
  const stage = h("div", {class: ["st-stage", auto ? "" : "still"], role: "dialog", "aria-modal": "true", "aria-label": "오늘의 하이라이트", tabindex: "-1"},
    h("div", {class: "st-scrim", onclick: () => close()}), frame, prevBtn, nextBtn);
  document.body.append(stage);
  document.documentElement.classList.add("st-open");
  inst = {stage, update: (p) => { st.day = p.arg || null; togglePicker(false); load(); }};
  ctx.track(() => {
    stage.remove();
    document.documentElement.classList.remove("st-open");
    if (inst && inst.stage === stage) inst = null;
    nav.from = null;
  });
  requestAnimationFrame(() => { if (ctx.alive()) stage.focus({preventScroll: true}); });

  // ---------------------------------------------------------------- pages and the timer
  const env = {ctx, openPicker: () => togglePicker(true), go: (i) => go(i)};
  const paused = () => st.user || st.held || st.hidden || st.picker || !st.d;
  function applyPause() {
    stage.classList.toggle("paused", paused());
    stage.classList.toggle("held", st.held);
    pauseBtn.setAttribute("aria-label", st.user ? "다시 넘기기" : "멈춤");
    pauseBtn.classList.toggle("on", st.user);
  }
  function paintBars() {
    [...bars.children].forEach((seg, k) => {
      const fresh = h("b");
      seg.replaceChildren(fresh);
      const run = k === st.i && auto && !st.done;
      seg.className = k < st.i || (k === st.i && st.done) ? "done" : k === st.i ? (run ? "cur run" : "cur") : "";
      if (run) fresh.addEventListener("animationend", () => { if (ctx.alive() && seg.classList.contains("run")) timeUp(); });
    });
  }
  function timeUp() {
    if (st.i < PAGES - 1) go(st.i + 1);
    else { st.done = true; paintBars(); }          // the last page stays (nothing closes by itself)
  }
  function go(i) {
    if (!st.d) return;
    if (i < 0) i = 0;
    if (i > PAGES - 1) { st.done = true; paintBars(); return; }
    st.i = i;
    st.done = false;
    const pg = PAGE_LIST[i];
    let node;
    try { node = pg.build(st.d, env); } catch (e) { console.error(e); node = ui.errorBox(e); }
    body.replaceChildren(node);
    body.scrollTop = 0;
    motion.swap(node);
    count.textContent = `${i + 1} / ${PAGES}`;
    live.textContent = `${i + 1} / ${PAGES} · ${pg.title}`;
    prevBtn.disabled = i === 0;
    nextBtn.disabled = i === PAGES - 1;
    paintBars();
    applyPause();
  }

  // ---------------------------------------------------------------- loading a day
  async function load() {
    const req = ++st.req;
    st.d = null;
    st.i = 0;
    paintBars();
    applyPause();
    body.replaceChildren(h("div", {class: "st-wait"}, motion.shimmer(5, true)));
    dayEl.textContent = st.day ? fmt.date(Date.parse(`${st.day}T12:00:00+09:00`)) : "오늘";
    try {
      const d = await ctx.api("/api/v4/story" + (st.day ? "?day=" + encodeURIComponent(st.day) : ""));
      if (!ctx.alive() || req !== st.req) return;
      if (!d || !d.ready) {
        body.replaceChildren(h("div", {class: "sp-empty"}, pixIcon("sprout", 54), h("b", null, "아직 이야기가 없습니다"),
          h("span", null, "봇이 첫 계좌를 만들면 그날부터 하루씩 쌓입니다.")));
        return;
      }
      st.d = d;
      dayEl.textContent = `${d.today ? "오늘" : fmt.date(d.t0 + 12 * 3600000)} · D+${d.dn}`;
      avNum.textContent = String(d.dn);
      markSeen(d.day);
      renderPicker();
      go(0);
    } catch (e) {
      if (!ctx.alive() || req !== st.req || (e && e.name === "AbortError")) return;
      body.replaceChildren(h("div", {class: "st-err"}, ui.errorBox(e, () => load())));
    }
  }

  // ---------------------------------------------------------------- the day picker
  function renderPicker() {
    const days = [...((st.d && st.d.days) || [])].reverse();
    pickList.replaceChildren(...days.map((x) => {
      const cur = !!st.d && x.day === st.d.day;
      const seen = isSeen(x.day) && !cur;
      return h("button", {class: ["st-dayb", cur ? "cur" : "", seen ? "seen" : ""], type: "button", role: "listitem",
        "aria-current": cur ? "true" : null, "aria-label": `${dayWord(x.day)} · D+${x.dn}`, onclick: () => pickDay(x.day)},
      h("span", {class: "sk-ava"}, ringSvg({seen, cur, size: 52}), h("span", {class: "sk-in"}, h("small", null, "D+"), h("b", null, String(x.dn)))),
      h("span", {class: "st-dayl"}, dayWord(x.day)));
    }));
  }
  function togglePicker(open = !st.picker) {
    if (open === st.picker) return;
    st.picker = open;
    pickBtn.setAttribute("aria-expanded", String(open));
    if (open) renderPicker();
    motion.expand(picker, open);
    stage.classList.toggle("picking", open);
    applyPause();
    if (open) requestAnimationFrame(() => { const b = picker.querySelector(".st-dayb.cur") || picker.querySelector(".st-dayb"); if (b) b.focus(); });
    else pickBtn.focus({preventScroll: true});
  }
  function pickDay(day) {
    const days = (st.d && st.d.days) || [];
    const today = days.length ? days[days.length - 1].day : null;
    location.replace(ctx.href("story", day === today ? null : day));     // no history entry per day: 닫기 goes back once
  }

  // ---------------------------------------------------------------- closing
  function close() {
    if (nav.from) { nav.from = null; history.back(); }
    else ctx.go("home");
  }

  // ---------------------------------------------------------------- touch, mouse and keys
  // the click that follows a swipe or a long press is not a tap (it may never come when the page was swapped: a time
  // window, not a flag, so a later real tap is never eaten)
  const eat = () => { st.eatUntil = performance.now() + 350; };
  ctx.listen(frame, "pointerdown", (e) => {
    if (!st.d || e.button > 0 || (e.target.closest && e.target.closest(".st-head, .st-pick"))) return;
    st.down = {x: e.clientX, y: e.clientY, t: performance.now(), link: !!(e.target.closest && e.target.closest("a, button"))};
    st.held = true;
    applyPause();
  });
  const release = (e, cancel) => {
    const d0 = st.down;
    st.down = null;
    if (st.held) { st.held = false; applyPause(); }
    if (!d0 || cancel || !st.d) return;
    const dx = e.clientX - d0.x, dy = e.clientY - d0.y, dt = performance.now() - d0.t;
    if (Math.abs(dx) > 48 && Math.abs(dx) > Math.abs(dy) * 1.3) { eat(); go(st.i + (dx < 0 ? 1 : -1)); return; }
    if (dt >= 450) { eat(); return; }                      // a long press only paused: no tap, no link
    if (d0.link) return;                                   // a tap on a link or button inside the page: its own click
    if (Math.abs(dx) < 12 && Math.abs(dy) < 12 && dt < 450) {
      const r = frame.getBoundingClientRect();
      go(st.i + (e.clientX - r.left < r.width * 0.32 ? -1 : 1));
    }
  };
  ctx.listen(frame, "pointerup", (e) => release(e, false));
  ctx.listen(frame, "pointercancel", (e) => release(e, true));
  ctx.listen(frame, "click", (e) => { if (performance.now() < st.eatUntil) { e.preventDefault(); e.stopPropagation(); st.eatUntil = 0; } }, true);
  ctx.listen(frame, "contextmenu", (e) => { if (st.held) e.preventDefault(); });
  ctx.listen(document, "keydown", (e) => {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.key === "Escape") { e.preventDefault(); if (st.picker) togglePicker(false); else close(); return; }
    if (st.picker) return;
    if (e.key === "ArrowRight") { e.preventDefault(); go(st.i + 1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); go(st.i - 1); }
    else if (e.key === " " && auto && !(e.target && e.target.closest && e.target.closest("button, a"))) { e.preventDefault(); st.user = !st.user; applyPause(); }
  });
  ctx.listen(document, "visibilitychange", () => { st.hidden = document.hidden; applyPause(); });

  await load();
}

export function update(params) { if (inst) inst.update(params); }
export function unmount() { inst = null; }
