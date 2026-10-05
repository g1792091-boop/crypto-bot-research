// First-visit guided tour: 7 short steps that walk through the real screens (홈 → 거래 → 에이전트 → 서버), skippable,
// remembered in localStorage (local.* has the try/catch: a private window simply sees it again). FAQ and 홈 have a
// button that starts it again. Each step names the screen it shows (`go`) and its targets in priority order: the
// screen's own data-tour element first, then a shell element that always exists, so a step never waits forever on a
// screen that has nothing to show yet (no open position, no meeting). At the end (or 건너뛰기) the page goes back to
// where the tour started. Only real elements are pointed at; nothing is drawn or made up for the tour.
import {h, local} from "./dom.js";
import {href, parseHash} from "./routes.js";
import {reduced} from "./motion.js";

export const STEPS = [
  {go: "home", sel: ["#dchip"], t: "실험 며칠째인가요",
    p: "D+며칠/30과 판정 날짜가 한 줄에 있습니다 (PC는 관찰 기간까지). 누르면 관찰 기간과 규칙이 펼쳐집니다."},
  {go: "home", sel: ["#hdot"], t: "건강 점 하나",
    p: "초록은 정상, 주황은 확인할 것, 빨강은 무언가 멈춘 것입니다. 누르면 서버 화면으로 갑니다. 파산·강제청산 몰림·시세 끊김은 맨 위 빨간 띠로도 나옵니다."},
  {go: "home", sel: ['[data-tour="headline"]', '[data-group="home"]'], t: "홈 · 첫 카드",
    p: "매매법 계좌들의 중앙값과 동전 봇 중앙값을 나란히 봅니다. 30일째 판정 전까지 이 비교는 '참고'이고, 합격·불합격이 아닙니다."},
  {go: "home", sel: ['[data-tour="groups"]', '[data-group="home"]'], t: "묶음 카드",
    p: "기존 36 · 딥시크 44 · 5분봉 · 동전 봇. 누르면 아래 상위·하위 5개와 전체 목록이 그 묶음으로 바뀝니다. 돈 숫자 밑 작은 글씨는 '모의 · 실제 시세 · 수수료 포함'이라는 뜻입니다."},
  {go: "positions", sel: ['.pos-card.open .pos-why', '[data-tour="positions"]', '[data-group="trade"]'], t: "거래 · 포지션",
    p: "지금 열린 모의 포지션입니다. '왜 ○○배' 줄에 자리 등급, 증거금, 진입 때 청산까지 거리가 있습니다. 주문 버튼은 없습니다."},
  {go: "office", sel: ['[data-tour="office"]', '[data-group="agents"]'], t: "에이전트 · 회의실",
    p: "픽셀 회의실과 콘솔입니다. AI 직원은 회의와 기록만 하고 거래하지 않습니다. 말풍선과 콘솔 줄은 저장된 실제 발언만 나옵니다."},
  {go: "server", sel: ['.subtabs .oldui', '[data-group="server"]'], t: "서버와 도움말",
    p: "서버 상태와 비용, '어떻게 돌아가나', 자주 묻는 질문이 이 묶음에 있습니다. 맨 끝 '예전 화면'은 지금까지 쓰던 대시보드입니다. 이 안내는 자주 묻는 질문에서 다시 볼 수 있습니다."},
];

function visible(el) {
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && (el.offsetParent !== null || getComputedStyle(el).position === "fixed");
}
/** The first visible match of the selectors, in order (prefer = how many of the first selectors may be used). */
function find(sels, upto = sels.length) {
  for (const sel of sels.slice(0, upto)) {
    for (const el of document.querySelectorAll(sel)) if (visible(el)) return el;
  }
  return null;
}
const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));
const barH = () => { const b = document.getElementById("botbar"); return b && visible(b) ? b.getBoundingClientRect().height : 0; };
const topH = () => { const t = document.querySelector(".shell-top"); return t ? t.getBoundingClientRect().height : 0; };

let active = null;
export function startTour() {
  if (active) return;
  const startHash = location.hash || href("home");
  let i = 0, gen = 0, el = null;
  const ring = h("div", {class: "tour-ring", "aria-hidden": "true", hidden: true});
  const tn = h("span", {class: "tn"}), tt = h("h3", {id: "tour-t"}), tp = h("p");
  const back = h("button", {type: "button"}, "이전"), next = h("button", {type: "button", class: "go"}, "다음");
  const skip = h("button", {type: "button", class: "skipb"}, "건너뛰기");
  const card = h("div", {class: "tour-card", role: "dialog", "aria-modal": "false", "aria-labelledby": "tour-t", "aria-live": "polite"},
    tn, tt, tp, h("div", {class: "acts"}, skip, h("span", {class: "grow"}), back, next));
  document.body.append(ring, card);

  // place the ring on the target and the card next to it (above the phone's bottom bar, below the sticky top)
  function place() {
    const vw = window.innerWidth, vh = window.innerHeight, bottom = vh - barH() - 12;
    const cw = card.offsetWidth, ch = card.offsetHeight;
    if (!el || !el.isConnected || !visible(el)) {
      ring.hidden = true;
      card.style.left = `${Math.max(16, (vw - cw) / 2)}px`; card.style.top = `${Math.max(16, (bottom - ch) / 2)}px`;
      return;
    }
    const r = el.getBoundingClientRect(), pad = 6;
    const top = Math.max(r.top - pad, 4), bot = Math.min(r.bottom + pad, bottom + 8);
    ring.hidden = false;
    Object.assign(ring.style, {left: `${r.left - pad}px`, top: `${top}px`, width: `${r.width + pad * 2}px`, height: `${Math.max(24, bot - top)}px`});
    const left = Math.min(Math.max(16, r.left + r.width / 2 - cw / 2), vw - cw - 16);
    let y = bot + 12;                                   // below the target
    if (y + ch > bottom) y = top - ch - 12;             // else above it
    if (y < 16 || bot - top > vh * 0.55) y = bottom - ch;   // a tall target: the card sits at the bottom
    card.style.left = `${left}px`; card.style.top = `${Math.max(16, y)}px`;
  }
  let raf = 0;
  const follow = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; place(); }); };

  async function show(k) {
    const my = ++gen;
    i = k;
    const s = STEPS[i];
    tn.textContent = `${i + 1} / ${STEPS.length}`; tt.textContent = s.t; tp.textContent = s.p;
    back.disabled = i === 0; next.textContent = i === STEPS.length - 1 ? "끝" : "다음";
    if (parseHash(location.hash).name !== s.go) location.hash = href(s.go);
    // wait for the screen's own element (up to 2.5 s), then accept a shell fallback (up to 6 s in all)
    el = null; ring.hidden = true; place();
    const t0 = Date.now();
    while (my === gen && Date.now() - t0 < 6000) {
      el = find(s.sel, Date.now() - t0 < 2500 ? 1 : s.sel.length);
      if (el) break;
      await sleep(120);
    }
    if (my !== gen) return;
    if (el) {
      const rx = el.getBoundingClientRect();
      if (rx.left < 0 || rx.right > window.innerWidth) {     // inside a sideways-scrolling row (the phone's sub tabs)
        el.scrollIntoView({block: "nearest", inline: "center", behavior: "auto"});
      }
      const r = el.getBoundingClientRect();
      const inView = r.top >= topH() && r.bottom <= window.innerHeight - barH();
      if (!inView && getComputedStyle(el).position !== "fixed" && !el.closest(".shell-top, .botbar")) {
        const y = window.scrollY + r.top - topH() - (r.height < window.innerHeight * 0.4 ? (window.innerHeight - barH() - topH() - r.height) / 3 : 12);
        window.scrollTo({top: Math.max(0, y), behavior: reduced() ? "auto" : "smooth"});
        await sleep(reduced() ? 30 : 380);
        if (my !== gen) return;
      }
    }
    place();
    next.focus({preventScroll: true});
  }
  const done = () => {
    gen++;
    local.set("tour-done", 1);
    ring.remove(); card.remove(); active = null;
    window.removeEventListener("resize", follow); window.removeEventListener("scroll", follow, true);
    document.removeEventListener("keydown", key);
    if (location.hash !== startHash) location.hash = startHash;
  };
  const key = (e) => {
    if (e.key === "Escape") done();
    else if (e.key === "ArrowRight") next.click();
    else if (e.key === "ArrowLeft" && i > 0) back.click();
  };
  back.onclick = () => { if (i > 0) show(i - 1); };
  next.onclick = () => { if (i >= STEPS.length - 1) done(); else show(i + 1); };
  skip.onclick = done;
  window.addEventListener("resize", follow);
  window.addEventListener("scroll", follow, true);
  document.addEventListener("keydown", key);
  active = {done};
  requestAnimationFrame(() => show(0));
}

/** First visit: starts only when the page opened on 홈 or on the landing screen (an empty hash: the 터미널 on a wide
 *  PC; the tour's first step walks to 홈). A shared deep link such as #/board is shown as it is. */
const landed = () => !location.hash || location.hash === "#" || location.hash === "#/";
export function maybeStartTour() {
  if (local.get("tour-done", 0)) return;
  if (parseHash(location.hash).name !== "home" && !landed()) return;
  const was = landed();
  setTimeout(() => { if (!local.get("tour-done", 0) && (parseHash(location.hash).name === "home" || (was && landed()))) startTour(); }, 1200);
}
