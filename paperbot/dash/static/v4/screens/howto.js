// #/howto — 어떻게 돌아가나 (builder E, mockup screen 04). Six step tabs 01 신호 → 06 판정, each two or three sentences
// and a console-style 예시 box; #/howto/<1-6> opens a step (update() swaps it in place). Below: who trades (the four
// groups, counted from the board), what the AI staff do (counted from /api/agents/roster) and that everything is 모의.
import {h, ui, fmt, derive, motion, local, put, joinedTabs} from "../core/pb.js";
import {limitsOf} from "./server-kit.js";
import {STEPS} from "./howto-steps.js";

const two = (i) => String(i + 1).padStart(2, "0");
let api = null;           // this mount's step switcher (update() uses it)

export async function mount(el, ctx) {
  ctx.setTitle("어떻게 돌아가나");
  const facts = {fee: null, lim: limitsOf(null), verdict: null};
  const start = (() => { const a = Number(ctx.params.arg); return a >= 1 && a <= STEPS.length ? a - 1 : Number(local.get("howto-step", 0)) || 0; })();
  let cur = Math.min(Math.max(0, start), STEPS.length - 1);

  // ---------------------------------------------------------------- the step strip + panel
  const tabs = STEPS.map((s, i) => h("button", {class: "howto-tab", type: "button", role: "tab", id: `howto-t${i}`, "aria-controls": "howto-panel",
    "aria-selected": String(i === cur), tabindex: i === cur ? "0" : "-1", onclick: () => show(i, true)},
    h("span", {class: "sn"}, two(i)), s.k));
  const strip = h("div", {class: "howto-strip", role: "tablist", "aria-label": "한 거래가 지나가는 단계"}, tabs);
  strip.addEventListener("keydown", (e) => {
    const n = e.key === "ArrowRight" ? cur + 1 : e.key === "ArrowLeft" ? cur - 1 : e.key === "Home" ? 0 : e.key === "End" ? STEPS.length - 1 : null;
    if (n == null) return;
    e.preventDefault(); show((n + STEPS.length) % STEPS.length, true); tabs[cur].focus();
  });
  const panel = h("section", {class: "howto-panel", role: "tabpanel", id: "howto-panel", tabindex: "0"});
  const prev = h("button", {class: "btn-line", type: "button", onclick: () => show(cur - 1, true)}, "← 이전 단계");
  const next = h("button", {class: "btn-y", type: "button", onclick: () => show(cur + 1, true)}, "다음 단계 →");
  function paint() {
    const s = STEPS[cur];
    panel.setAttribute("aria-labelledby", `howto-t${cur}`);
    put(panel, h("p", {class: "howto-eye"}, `${two(cur)} · ${s.k}`), h("h2", {class: "howto-h"}, s.h), h("p", {class: "howto-p"}, s.p(facts)),
      s.ex.map((x) => h("div", {class: "server-term"}, h("span", {class: "th"}, `◆ ${x.h} ◆`), x.lines.map((l) => h("span", {class: "tl"}, l)))),
      h("div", {class: "row wrap howto-acts"}, h("a", {class: "btn-line", href: ctx.href(s.screen)}, s.go)));
    prev.disabled = cur === 0; next.disabled = cur === STEPS.length - 1;
    next.textContent = cur === STEPS.length - 1 ? "마지막 단계" : `다음: ${STEPS[cur + 1].k} →`;
  }
  function show(i, animate) {
    if (i < 0 || i >= STEPS.length) return;
    cur = i; local.set("howto-step", i);
    tabs.forEach((t, k) => { t.setAttribute("aria-selected", String(k === i)); t.tabIndex = k === i ? 0 : -1; });
    paint();
    if (animate) motion.swap(panel);
  }
  api = show;
  // a phone: swipe the panel left / right to change step (a short, mostly sideways swipe only)
  let sx = null, sy = null;
  panel.addEventListener("touchstart", (e) => { const t = e.touches[0]; sx = t.clientX; sy = t.clientY; }, {passive: true});
  panel.addEventListener("touchend", (e) => {
    if (sx == null) return;
    const t = e.changedTouches[0], dx = t.clientX - sx, dy = t.clientY - sy;
    sx = null;
    if (Math.abs(dx) > 60 && Math.abs(dx) > 2 * Math.abs(dy)) show(cur + (dx < 0 ? 1 : -1), true);
  }, {passive: true});

  el.append(ui.screenHead("어떻게 돌아가나", "한 거래가 신호에서 판정까지 지나가는 여섯 단계"), joinedTabs("howto"),
    ui.card({cls: "howto-hero", hero: true, label: "작동 방식"}, h("p", {class: "howto-kicker"}, "작동 방식"),
      h("h2", {class: "howto-title"}, "신호에서 ", h("em", null, "판정"), "까지"), strip, panel,
      h("div", {class: "row howto-nav"}, prev, h("span", {class: "grow"}), next),
      ui.assume("closed", "예시 숫자이며 실제 계좌가 아닙니다")));
  paint();

  // ---------------------------------------------------------------- who trades / what the AI does / all paper
  const groupsBox = h("div", {class: "howto-groups"});
  const staffBox = h("div", {class: "stack tight"});
  el.append(h("div", {class: "howto-cols"},
    ui.card({plate: "누가 거래하나", sub: "모두 같은 시각, 같은 시세로"}, groupsBox),
    ui.card({plate: "AI 직원은 무엇을 하나"}, staffBox),
    ui.card({plate: "모두 모의입니다", cls: "howto-paper"},
      h("p", {class: "ink2"}, "모든 계좌는 가상 돈입니다. 실제 시세로 계산하고 수수료·펀딩·슬리피지를 빼지만, 거래소에 보내는 주문은 하나도 없습니다. 이 대시보드에는 주문 버튼이 없습니다."),
      h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: ctx.href("faq")}, "자주 묻는 질문"), h("a", {class: "btn-line", href: ctx.href("checkpoint")}, "30일 판정")))));

  const DESC = {
    core: "검증해 둔 36개 매매법 × 15분·30분·1시간·4시간. 좋은 자리면 높은 배수.",
    ds: "딥시크가 고른 44개 정의 (39개는 봉 4개, 5개는 봉 3개). 레버리지는 언제나 보통 자리.",
    m5: "5분봉 단타 1개. 계단 잠금 대신 자기 청산 규칙. 비교 기준은 같은 청산 규칙으로 롱만 무작위로 들어가는 5분봉 동전 봇 3개(동전 봇 묶음에서 셈).",
    coin: "봉마다 동전 던지기로 들어가는 봇 (5분봉 3개 포함). 같은 청산 규칙을 쓰는 비교 기준이라 판정하지 않습니다.",
    extra: "에이전트 제안을 두 분이 승인해 나중에 시작한 계좌. 따로 셉니다.",
  };
  const paintGroups = (b) => {
    const gs = b ? derive.groupStats(b) : null;
    put(groupsBox, fmt.GROUPS.filter((g) => g.id !== "extra" || (gs && gs.groups.extra)).map((g) =>
      h("div", {class: "howto-g"}, h("b", null, g.ko), h("span", {class: "howto-n"}, gs && gs.groups[g.id] ? `${fmt.int(gs.groups[g.id].n)}계좌` : "—"),
        h("p", null, DESC[g.id] || g.desc))),
    h("p", {class: "server-note"}, "4시간봉 계좌는 관찰용이라 판정하지 않습니다. 동전 봇과의 비교는 판정 전까지 '참고'입니다."));
  };
  ctx.watch("board", (b) => b && paintGroups(b));
  paintGroups(null);

  const paintStaff = (r) => {
    const teams = r && Array.isArray(r.teams) ? r.teams.length : null;
    const roles = r && Array.isArray(r.roles) ? r.roles : [];
    const spec = roles.filter((x) => x && x.team === "specialist").length;
    put(staffBox,
      h("p", {class: "ink2"}, "AI 직원은 회의하고 기록만 합니다. 주문을 내거나 규칙·계좌를 바꾸지 못합니다. 말풍선과 콘솔에는 저장된 실제 발언만 나옵니다."),
      r ? h("div", {class: "server-counts"}, h("span", null, "팀 ", h("b", null, fmt.int(teams))), h("span", null, "직원 ", h("b", null, fmt.int(roles.length))),
        spec ? h("span", null, "그중 매매법 전담 ", h("b", null, fmt.int(spec))) : null) : null,
      h("p", {class: "ink2"}, "관찰 기간이 끝나면 새 계좌를 제안할 수 있지만, 두 분이 승인해야만 시작합니다."),
      h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: ctx.href("office")}, "회의실 보기")));
  };
  paintStaff(null);
  const [st, sm, ro] = await Promise.all([ctx.store.need("status", 60000).catch(() => null), ctx.store.need("summary", 60000).catch(() => null),
    ctx.api("/api/agents/roster").catch(() => null)]);
  if (!ctx.alive()) return;
  const run = st && st.run && st.run[1];
  facts.fee = run && run.taker_fee != null ? run.taker_fee : null;
  facts.lim = limitsOf(st);
  facts.verdict = sm && sm.restart && sm.restart.ready ? sm.restart.verdict_ts : sm && sm.next_checkpoint ? sm.next_checkpoint.ts : null;
  paint();
  paintStaff(ro);
}

export function update(params) {
  const a = Number(params && params.arg);
  if (api && a >= 1 && a <= STEPS.length) api(a - 1, true);
}

export function unmount() { api = null; }
