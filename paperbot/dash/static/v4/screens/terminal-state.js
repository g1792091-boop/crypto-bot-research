// 터미널 panels: the three states of a load, kept apart (review 10/06, "못 불러온 것을 '없음'으로 보여 줌"):
//   불러오는 중     a shimmer (motion.shimmer): a request really is in flight
//   불러오지 못함   words + the age of the last good data when there is one + a retry button, and an automatic retry that
//                   REALLY runs (retrier: 5 · 15 · 30 · 60 s, then every 60 s) — the words never promise what no timer does
//   진짜 없음       the panel's own empty sentence ("열린 포지션이 없습니다") — only after a load that succeeded
// A failed load must never read as "없음", as a flat line or as 0.
import {h, fmt, serverNow} from "../core/pb.js";

/** A failed-load note: "불러오지 못함 · 순위 자료 · 받은 자료 없음 [다시 시도]". since: when the last good data was read (ms) or null. */
export function failNote(what, {retry = null, since = null, retrying = true} = {}) {
  return h("div", {class: "term-fail", role: "status"},
    h("b", null, "불러오지 못함"), h("span", null, ` · ${what} · ${since ? `${fmt.ago(since, serverNow())} 자료` : "받은 자료 없음"}`),
    retrying ? h("span", {class: "muted"}, " · 자동으로 다시 시도 중") : null,
    retry ? h("button", {type: "button", class: "term-retry", onclick: retry}, "다시 시도") : null);
}

/**
 * retrier(ctx, run, delays) -> {fail(), ok(), stop(), failing()}: after a failed load call fail(); it runs ``run`` again after
 * the next delay (5, 15, 30, 60 s, then every 60 s) while the screen lives; ok() resets the ladder. One timer at a time.
 */
export function retrier(ctx, run, delays = [5000, 15000, 30000, 60000]) {
  let i = 0, t = null, failing = false;
  const stop = () => { clearTimeout(t); t = null; };
  ctx.track(stop);
  function arm(ms) {
    stop();
    t = setTimeout(() => {
      t = null;
      if (!ctx.alive()) return;
      if (document.hidden) { arm(ms); return; }               // a hidden page asks nothing: the same wait again, the ladder stays
      run();
    }, ms);
  }
  return {
    fail() { failing = true; arm(delays[Math.min(i++, delays.length - 1)]); },
    ok() { failing = false; i = 0; stop(); },
    stop,
    failing: () => failing,
  };
}
