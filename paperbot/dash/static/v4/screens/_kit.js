// #/_kit — the foundation's component sheet on REAL server data (not a tab). Builders read this file as the worked
// example of the screen contract: mount(el, ctx) builds with h()/ui.*, data comes from ctx.watch / ctx.api, money has
// its caption, comparisons are '참고', small samples say so, and the screen cleans up through ctx.
import {h, ui, fmt, derive, figure, clock, windowArt, consolePanel, TEAM_HUE, motion, stream, stratFigure, PHASE_KO} from "../core/pb.js";

export async function mount(el, ctx) {
  ctx.setTitle("부품 견본");
  el.append(ui.screenHead("부품 견본", "공통 부품을 실제 서버 자료로 보여 주는 화면 (메뉴에는 없음)"));
  // a builders' sheet: only with ?dev=1 in the address (the owners never land on it through a stray link)
  if (!/[?&]dev=1\b/.test(location.search)) { el.append(ui.empty("개발용 화면입니다. 주소에 ?dev=1을 붙여야 보입니다.")); return; }

  // ---------------------------------------------------------------- LED bar + group cards from the board
  const led = ui.ledBar({label: "모의 계좌 잔고"});
  const groupsEl = h("div", {class: "kit-groups"});
  el.append(led, groupsEl);
  let sel = "core";
  const list = ui.searchList({size: 8, placeholder: "매매법 이름 찾기",
    match: (a, q) => fmt.acctName(a).toLowerCase().includes(q) || String(a.account_id).toLowerCase().includes(q),
    row: (a, i) => h("div", {class: "lrow click", role: "listitem", onclick: () => ctx.go("account", a.account_id)},
      h("span", {class: "rk"}, String(i + 1)), h("span", {class: "lname", title: a.account_id}, fmt.acctName(a)),
      h("span", {class: ["ret", fmt.tone(a.ret)]}, fmt.pct(a.ret)),
      h("span", {class: "meta"}, h("span", null, fmt.tfKo(a.timeframe)), h("span", null, `거래 ${fmt.int(a.trades)}`),
        ui.smallSample(a.trades, 20), a.bust ? ui.pill("파산", "bad") : null))});
  el.append(ui.card({plate: "전체 목록", sub: "찾기 + 10개 미만씩 나눠 그림 (331개를 한 번에 그리지 않음)"}, list.el, ui.assume()));

  const renderGroups = (b) => {
    const gs = derive.groupStats(b);
    led.update({total: gs.total.wallet, initialTotal: gs.total.initial, live: stream.live(), curve: null,
      stats: [`계좌 ${fmt.int(gs.total.n)}개 합계`, `시작 ${fmt.money(gs.initial)} USDT씩`],
      right: fmt.GROUPS.filter((g) => gs.groups[g.id]).map((g) => ({k: g.ko, v: gs.groups[g.id].pnl}))});
    const cards = fmt.GROUPS.filter((g) => gs.groups[g.id]).map((g) => {
      const x = gs.groups[g.id];
      return h("button", {class: "kit-g", type: "button", "aria-pressed": String(g.id === sel), onclick: () => { sel = g.id; renderGroups(b); }},
        h("b", null, g.ko), h("small", {class: "muted"}, `${fmt.int(x.n)}계좌`),
        ui.liveNum(x.medRet, {format: "pct", tone: true, cls: "kit-med"}),
        h("small", {class: "ink2"}, g.id === "coin" ? `비교 기준 · 파산 ${x.bust}` : `동전 봇 중앙값보다 위 ${x.above}/${x.vsN} · 파산 ${x.bust}`));
    });
    el.querySelectorAll(".kit-groups").forEach((n) => n.replaceChildren(...cards));
    list.set(derive.ranked(b, sel));
  };
  ctx.watch("board", (b) => b && renderGroups(b));
  const s = await ctx.store.need("summary").catch(() => null);
  el.append(ui.refNote(s && s.next_checkpoint && s.next_checkpoint.ts));

  // ---------------------------------------------------------------- thin curves from two real accounts' equity
  const curveCard = ui.card({plate: "얇은 곡선", sub: "두 계좌의 실제 자본 기록 (/api/account)"}, motion.shimmer(3));
  el.append(curveCard);
  const b = await ctx.store.need("board", 60000).catch(() => null);
  const top = b && derive.ranked(b, "core")[0], flip = b && derive.ranked(b, "coin")[0];
  if (!top || !flip) curveCard.replaceChildren(ui.empty("계좌가 아직 없습니다"));
  else {
    const [ta, fa] = await Promise.all([ctx.api(`/api/account/${encodeURIComponent(top.account_id)}`), ctx.api(`/api/account/${encodeURIComponent(flip.account_id)}`)]);
    const pick = (eq) => eq.filter((_, i) => i % Math.max(1, Math.floor(eq.length / 60)) === 0).map((p) => p.v);
    curveCard.replaceChildren(h("div", {class: "card-h"}, ui.plate("얇은 곡선"), h("span", {class: "sub"}, "두 계좌의 실제 자본 기록")),
      ui.curves({series: [{values: pick(fa.equity), cls: "lc"}, {values: pick(ta.equity), cls: "ls"}], base: b.initial, xlabels: ["시작", "", "지금"]}),
      h("div", {class: "legend"}, h("div", null, h("span", {class: "sw"}), h("span", null, fmt.acctName(top)), h("b", null, fmt.money(top.wallet)), h("span", {class: fmt.tone(top.ret)}, fmt.pct(top.ret))),
        h("div", null, h("span", {class: "sw c"}), h("span", null, fmt.acctName(flip)), h("b", null, fmt.money(flip.wallet)), h("span", {class: fmt.tone(flip.ret)}, fmt.pct(flip.ret)))),
      ui.assume());
  }

  // ---------------------------------------------------------------- office bits: figures, bubble, clocks, console
  const figs = h("div", {class: "row wrap kit-figs"}, Object.entries(TEAM_HUE).map(([t], i) =>
    h("div", {class: "kit-fig"}, figure({team: t, kind: t === "specialist" ? "spec" : t === "owner" ? "owner" : "staff", size: 26, i, breathe: true}), h("span", {class: "nm"}, t))));
  const say = h("div", {class: "kit-say"});
  const con = consolePanel({title: "에이전트 콘솔", maxHeight: "320px", foot: "회의 시작 줄을 누르면 그 회의만 봅니다"});
  el.append(ui.card({plate: "픽셀 사람 · 말풍선 · 시계"}, figs, say, h("div", {class: "row wrap"}, windowArt(), clock("KST", "Asia/Seoul"), clock("UTC", "UTC"), clock("NYC", "America/New_York"))), con);
  // wave 2 ⑦ ⑧: the window's four Korea-time phases and the per-strategy characters (core/figure.js)
  el.append(ui.card({plate: "창문 (한국 시간) · 매매법 캐릭터"},
    h("div", {class: "row wrap"}, ["dawn", "day", "dusk", "night"].map((p) => h("div", {class: "kit-fig"}, windowArt(p), h("span", {class: "nm"}, PHASE_KO[p])))),
    h("div", {class: "row wrap"}, ["S5_DONCHIAN_MFI", "S1_SUPERTREND_EMA", "F3_BOS", "F15_OPEN0930", "REEL_H1", "RANDOM_1"].map((id) =>
      h("div", {class: "kit-fig"}, stratFigure({strategy: id, size: 34}), h("span", {class: "nm"}, fmt.stratKo(id)))))));
  ctx.watch("office", (o) => {
    if (!o) return;
    const m = (o.running || [])[0];
    const line = m && m.last_role && m.lines[m.last_role];
    say.replaceChildren(line ? ui.bubble({who: (o.roles[m.last_role] || {}).name || m.last_role, time: fmt.hm(line.ts), text: line.line, tail: "tl"})
      : ui.empty("지금 회의가 없어 말풍선이 없습니다"));
    const lines = [];
    for (const r of o.running || []) {
      lines.push({id: `start-${r.round_id}`, type: "ev", start: true, meeting: r.round_id, ts: r.started_ts, tabs: ["agent"], text: `[회의 시작] ${r.title} · ${r.trigger_ko}`});
      for (const t of r.turns) lines.push({id: `t-${r.round_id}-${t.role}-${t.ts}`, type: "st", meeting: r.round_id, ts: t.ts, tabs: ["agent"],
        who: (o.roles[t.role] || {}).name || t.role, text: t.line, onOpen: () => ctx.go("rooms", r.room_id)});
    }
    for (const r of o.recent || []) lines.push({id: `end-${r.round_id}`, type: "ev", meeting: r.round_id, ts: r.ended_ts || r.started_ts, tabs: ["agent"],
      text: `[${r.status === "done" ? "결정" : "행동 없음"}] ${r.title} · ${r.decision || ""}`});
    con.setLines(lines);
    if (!lines.length) con.showEmpty("오늘 회의 기록이 아직 없습니다");
  });
  ctx.on("trades", (ts) => ts.forEach((t) => con.push({id: `tr-${t.id}`, type: t.pnl < 0 ? "bad" : "ev", ts: t.exit_time, tabs: ["trade"],
    text: `[거래] ${fmt.idName(t.account_id)} ${fmt.coin(t.symbol)} ${fmt.reasonKo(t.exit_reason)} ${fmt.pct(t.roe)}`})));

  // ---------------------------------------------------------------- gauges, steps, pills
  const usage = await ctx.store.need("usage").catch(() => null);
  el.append(ui.card({plate: "계기판"}, h("div", {class: "grid2"},
    ui.gauge({name: "AI 호출 오늘", value: usage && usage.calls, cap: usage && usage.cap_calls, unit: "회", mean: "직원들이 AI를 부른 횟수"}),
    ui.gauge({name: "토큰 오늘", value: usage && usage.tokens, display: usage && fmt.compact(usage.tokens), cap: usage && usage.cap_tokens, capDisplay: usage && fmt.compact(usage.cap_tokens)}),
    ui.gauge({name: "CPU", value: null, mean: "서버가 아직 보내지 않는 값"}),
    ui.gauge({name: "디스크", value: null}))));
  el.append(ui.card({plate: "단계 띠 · 표시"},
    ui.stepStrip([{id: "analysis", label: "분석"}, {id: "challenge", label: "반론"}, {id: "revision", label: "최종안"}, {id: "verdict", label: "판정"}],
      {done: ["analysis", "challenge"], now: "revision"}),
    h("div", {class: "row wrap"}, ui.pill("기본"), ui.pill("좋음", "good"), ui.pill("나쁨", "bad"), ui.pill("주의", "warn"), ui.pill("강조", "accent"),
      ui.smallSample(3), ui.notYet(), ui.sideTag(1), ui.sideTag(-1)),
    ui.moreText("긴 글은 두 줄까지만 보이고, 더 보기를 누르면 펼쳐집니다. ".repeat(8)),
    ui.disclosure("펼치기 예시", h("p", {class: "ink2"}, "부드럽게 펼쳐지고 접힙니다.")), ui.assume("open")));
}

export function unmount() {}
