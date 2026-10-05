// 오늘의 하이라이트: the seven pages of one day's story, each one big picture and one or two lines, built from
// /api/v4/story (dash/more/story.py). HONESTY: every comparison with the coin flips is 참고 (refNote) and carries the
// same-bar flips as its yardstick; the day's best / worst account (core / reel / extra only: DeepSeek and coin flips are
// never named with money, D11) comes with "하루 성적은 운이 큽니다"; DeepSeek is
// shown at count level only (no account numbers, 참고); the meeting bubble is the stored conclusion line as it was
// written (text node); the money caption sits in the story frame's footer. Nothing here is invented: an empty part
// says so in a designed empty state.
import {h, s, ui, fmt, figure} from "../core/pb.js";
import {pixIcon} from "./story-kit.js";

const KO = {core: "기존 36", ds200: "딥시크 44", reel: "5분봉", flip: "동전 봇", extra: "추가 계좌", other: "기타"};
export const gKo = (g) => KO[g] || g;
const chip = (g) => h("span", {class: "sp-chip", dataset: {g}}, gKo(g));
const pct2 = (x) => fmt.pct(x, 2);
const tone = (x) => fmt.tone(x, pct2(x));
const kick = (n, t) => h("div", {class: "sp-kick"}, h("span", {class: "sp-n"}, String(n).padStart(2, "0")), h("span", null, t));
const line = (...k) => h("p", {class: "sp-line"}, ...k);
const note = (...k) => h("p", {class: "sp-note"}, ...k);
const dayIs = (d) => (d.today ? "오늘" : fmt.date(d.t0 + 12 * 3600000));

/** The story's pages: [{id, title, build(d, env) -> Node}] (env: {ctx, openPicker, go}). */
export const PAGE_LIST = [
  {id: "sum", title: "한 줄 요약", build: pSummary},
  {id: "movers", title: "가장 많이 번·잃은 계좌", build: pMovers},
  {id: "reel", title: "5분봉 영상 매매법", build: pReel},
  {id: "ds", title: "딥시크", build: pDeepSeek},
  {id: "busts", title: "강제청산·파산", build: pBusts},
  {id: "meet", title: "AI 회의 결론", build: pMeetings},
  {id: "dday", title: "판정까지", build: pDday},
];

// ---------------------------------------------------------------- 01 한 줄 요약
function pSummary(d, env) {
  const G = d.groups || {};
  const T = d.trades || {total: 0, groups: {}};
  const order = ["core", "ds200", "reel", "flip", "extra"].filter((g) => G[g]);
  const row = (g) => {
    const st = G[g];
    const seg = (cls, n, label) => h("i", {class: cls, style: {flexGrow: n, minWidth: n ? "3px" : "0"}, title: `${label} ${fmt.int(n)}`});
    return h("div", {class: ["sp-grow", g === "flip" ? "base" : "", g === "reel" ? "own" : ""], dataset: {g}, role: "listitem"},
      h("div", {class: "sp-gname"}, h("b", null, gKo(g)), h("small", null, `${fmt.int(st.n)}개`)),
      h("div", {class: "sp-split", role: "img", "aria-label": `오른 계좌 ${st.up}, 그대로 ${st.flat}, 내린 계좌 ${st.down}`},
        seg("u", st.up, "오른 계좌"), seg("f", st.flat, "그대로"), seg("d", st.down, "내린 계좌")),
      h("b", {class: ["sp-gmed", "num", tone(st.median_active)]}, st.active ? pct2(st.median_active) : "—"),
      h("div", {class: "sp-gcnt"}, h("span", {class: "up"}, `▲${fmt.int(st.up)}`), h("span", null, `■${fmt.int(st.flat)}`),
        h("span", {class: "down"}, `▼${fmt.int(st.down)}`), h("span", {class: "muted"}, `거래 ${fmt.int(st.trades)}`)));
  };
  const core = G.core, same = G.flip_same;
  let cmp = null;
  if (core && same && core.median_active != null && same.median_active != null) {
    const a = core.median_active, b = same.median_active;
    const w = pct2(a) === pct2(b) ? "같음" : a > b ? "위" : "아래";
    cmp = line(h("b", null, "기존 36"), ` ${pct2(a)} · 같은 봉 동전 봇 ${fmt.int(same.n)}개 ${pct2(b)} → `,
      h("b", null, w === "같음" ? "비슷함" : `동전 봇보다 ${w}`), ui.pill("", "ref"));
  }
  return h("div", {class: "sp sp-sum"},
    kick(1, `${dayIs(d)} 한 줄 요약`),
    h("div", {class: "sp-hero"}, h("span", {class: "sp-led num"}, fmt.int(T.total)), h("span", {class: "sp-unit"}, "건"),
      h("span", {class: "sp-herot"}, d.today ? "오늘 닫힌 거래" : "그날 닫힌 거래", h("small", null, "모든 묶음 · 한국 시각 00시부터"))),
    h("div", {class: "sp-groups", role: "list", "aria-label": "묶음별 하루 변화"}, order.map(row)),
    h("div", {class: "sp-legend"}, h("span", null, h("i", {class: "u"}), "오른 계좌"), h("span", null, h("i", {class: "f"}), "그대로"),
      h("span", null, h("i", {class: "d"}), "내린 계좌"), h("span", {class: "muted"}, "숫자 = 거래한 계좌의 하루 변화 중앙값")),
    cmp, ui.refNote(d.verdict_ts, "하루 비교는 운이 큽니다."));
}

// ---------------------------------------------------------------- 02 가장 많이 번 / 잃은 계좌
function pMovers(d, env) {
  const card = (a, kind) => {
    if (!a) {
      return h("div", {class: ["sp-mover", kind, "none"]}, pixIcon(kind === "best" ? "up" : "down", 26),
        h("span", null, kind === "best" ? `${dayIs(d)} 번 계좌가 없습니다` : `${dayIs(d)} 잃은 계좌가 없습니다`));
    }
    return h("div", {class: ["sp-mover", kind]},
      h("div", {class: "sp-mv-top"}, pixIcon(kind === "best" ? "crown" : "down", 28),
        h("span", {class: "sp-mv-k"}, kind === "best" ? "가장 많이 번 계좌" : "가장 많이 잃은 계좌"),
        h("span", {class: "grow"}), chip(a.group)),
      h("div", {class: "sp-mv-name"}, ui.acctLabel(a)),
      h("div", {class: ["sp-mv-num", "num", tone(a.pnl)]}, fmt.money(a.pnl, true), h("small", null, " USDT")),
      h("div", {class: "sp-mv-sub"}, h("span", {class: tone(a.change)}, pct2(a.change)), ` · 거래 ${fmt.int(a.trades)}건 · ${fmt.int(a.wins)}번 이김`,
        h("a", {class: "sp-mv-go", href: env.ctx.href("account", a.account_id)}, "계좌 보기 →")));
  };
  // core / reel / extra only (the server picks them): DeepSeek and the coin flips are never named with money per
  // account (CONTRACT rule 3, owners' D11); their day is on pages 1 and 4 as counts and medians
  return h("div", {class: "sp sp-movers"},
    kick(2, `${dayIs(d)} 가장 많이 번·잃은 계좌`),
    h("div", {class: "sp-mvs"}, card(d.best, "best"), card(d.worst, "worst")),
    note(h("b", null, "하루 성적은 운이 큽니다. "), "같은 계좌도 다음 날엔 순위가 또 섞입니다. 30일 판정만 실력을 봅니다."),
    note("기존 36 · 5분봉 · 추가 계좌 중에서 골랐습니다. 딥시크와 동전 봇은 계좌마다 돈으로 보여 주지 않고 묶음 숫자로만 봅니다."));
}

// ---------------------------------------------------------------- 03 5분봉 영상 매매법
function pReel(d, env) {
  const R = d.reel || {accounts: [], flips: []};
  const reel = R.accounts[0];
  if (!reel) {
    return h("div", {class: "sp sp-reel"}, kick(3, "5분봉 영상 매매법"),
      h("div", {class: "sp-empty"}, pixIcon("sprout", 54), h("b", null, "5분봉 계좌가 아직 없습니다"), h("span", null, "봇이 계좌를 만들면 여기 나옵니다.")));
  }
  const cols = [{label: "영상 매매법", v: reel.change, own: true, n: reel.trades},
    ...R.flips.map((f) => ({label: `동전 ${String(f.strategy || "").replace("RANDOM_", "")}`, v: f.change, n: f.trades}))];
  // the zero line sits where the biggest gain and the biggest loss leave it (all gains: near the bottom)
  const P = Math.max(0, ...cols.map((c) => c.v || 0)), N = Math.max(0, ...cols.map((c) => -(c.v || 0)));
  const span = P + N || 1, USE = 62;
  const zero = P + N ? 22 + USE * P / span : 62;
  const col = (c) => {
    const v = c.v || 0, hgt = Math.abs(v) / span * USE, up = v >= 0;
    return h("div", {class: ["sp-col", c.own ? "own" : ""], role: "listitem", "aria-label": `${c.label} ${pct2(c.v)} · 거래 ${c.n}건`},
      h("div", {class: "sp-cbox", style: {"--z": zero.toFixed(1) + "%"}},
        h("i", {class: ["sp-cbar", up ? "up" : "down", v ? "" : "zero"], style: {"--h": hgt.toFixed(1) + "%"}}),
        h("span", {class: ["sp-cval", "num", tone(c.v), up ? "top" : "bot"], style: {"--h": hgt.toFixed(1) + "%"}}, pct2(c.v))),
      h("span", {class: "sp-clab"}, c.label), h("small", {class: "sp-cn"}, `거래 ${fmt.int(c.n)}`));
  };
  const pips = reel.pips || [];
  const flipsTraded = R.flips.filter((f) => f.trades).length;
  return h("div", {class: "sp sp-reel"},
    kick(3, `5분봉 영상 매매법 ${dayIs(d)}`),
    h("div", {class: "sp-duel", role: "list", "aria-label": "영상 매매법과 5분봉 동전 봇 3개의 하루 변화"}, cols.map(col)),
    h("div", {class: "sp-pipsw"}, h("span", {class: "muted"}, pips.length ? `거래 ${fmt.int(reel.trades)}건` : "거래 없음"),
      pips.length ? h("div", {class: "sp-pips", role: "img", "aria-label": `이긴 거래 ${reel.wins}, 진 거래 ${reel.trades - reel.wins}`},
        pips.map((p) => h("i", {class: p > 0 ? "w" : p < 0 ? "l" : "z"}))) : null),
    line(h("b", null, "영상 매매법 "), h("span", {class: tone(reel.pnl)}, `${fmt.money(reel.pnl, true)} USDT`), ` (${pct2(reel.change)}) · `,
      flipsTraded ? `5분봉 동전 봇 ${R.flips.length}개 중 거래한 ${flipsTraded}개 중앙값 ${pct2(R.flips_median_active)}`
        : `5분봉 동전 봇 ${R.flips.length}개는 ${d.today ? "오늘" : "그날"} 거래 없음`),
    note("비교 상대는 같은 청산 규칙으로 롱만 하는 5분봉 동전 봇 3개입니다 (동전 봇 묶음에서 셉니다)."),
    ui.refNote(d.verdict_ts));
}

// ---------------------------------------------------------------- 04 딥시크
function pDeepSeek(d, env) {
  const D = d.ds || {n: 0};
  if (!D.n) {
    return h("div", {class: "sp sp-ds"}, kick(4, "딥시크 44"),
      h("div", {class: "sp-empty"}, pixIcon("sprout", 54), h("b", null, "딥시크 계좌가 아직 없습니다")));
  }
  const cols = Math.min(19, Math.max(8, Math.ceil(Math.sqrt(D.n * 2.1))));
  const cells = [];
  const push = (cls, k) => { for (let i = 0; i < k; i++) cells.push(h("i", {class: cls, style: {"--i": cells.length}})); };
  push("u", D.up); push("f", D.flat); push("d", D.down);
  const bf = D.best_family;
  return h("div", {class: "sp sp-ds"},
    kick(4, `딥시크 44 ${dayIs(d)}`),
    h("div", {class: "sp-waffle", style: {"--cols": cols}, role: "img",
      "aria-label": `딥시크 ${D.n}개 계좌 중 오른 계좌 ${D.up}, 그대로 ${D.flat}, 내린 계좌 ${D.down}`}, cells),
    h("div", {class: "sp-wcount"},
      h("div", {class: "up"}, h("b", {class: "num"}, fmt.int(D.up)), h("span", null, "오른 계좌")),
      h("div", null, h("b", {class: "num"}, fmt.int(D.flat)), h("span", null, "그대로")),
      h("div", {class: "down"}, h("b", {class: "num"}, fmt.int(D.down)), h("span", null, "내린 계좌"))),
    line(`거래한 ${fmt.int(D.active)}개 계좌의 하루 변화 중앙값 `, h("b", {class: tone(D.median_active)}, D.active ? pct2(D.median_active) : "—"),
      ` · 거래 ${fmt.int(D.trades)}건`),
    bf ? h("div", {class: "sp-fam"}, h("span", {class: "sp-fam-k"}, "가장 나은 계열"), h("b", null, bf.ko),
      h("span", {class: "muted"}, `${fmt.int(bf.n)}개 계좌 · 거래한 ${fmt.int(bf.active)}개 중앙값 `), h("b", {class: tone(bf.median_active)}, pct2(bf.median_active)),
      ui.pill("", "ref")) : null,
    note("딥시크는 계좌 하나하나가 아니라 묶음으로만 봅니다. 칸 하나가 계좌 하나, 오른 것부터 줄 세웠습니다."),
    ui.refNote(d.verdict_ts));
}

// ---------------------------------------------------------------- 05 강제청산·파산
function pBusts(d, env) {
  const B = d.busts || {liquidations: 0, busts: 0, named: []};
  if (!B.liquidations && !B.busts) {
    return h("div", {class: "sp sp-busts calm"}, kick(5, "강제청산·파산"),
      h("div", {class: "sp-calm"}, h("div", {class: "sp-calm-art"}, pixIcon("shield", 84)),
        h("span", {class: "sp-calm-k"}, `${dayIs(d)} 파산`), h("b", {class: "sp-calm-big num"}, "0"),
        h("span", null, "강제청산도 0건 · 조용한 하루였습니다")));
  }
  const groups = [...new Set([...Object.keys(B.liq_by_group || {}), ...Object.keys(B.bust_by_group || {})])];
  return h("div", {class: "sp sp-busts"}, kick(5, `${dayIs(d)} 강제청산·파산`),
    h("div", {class: "sp-bhero"}, pixIcon("bolt", 56),
      h("div", {class: "sp-bnums"},
        h("div", null, h("b", {class: "num"}, fmt.int(B.liquidations)), h("span", null, "강제청산")),
        h("div", null, h("b", {class: "num"}, fmt.int(B.busts)), h("span", null, "파산한 계좌")))),
    groups.length ? h("div", {class: "sp-bgroups"}, groups.map((g) => h("span", {class: "sp-bg"}, chip(g),
      (B.liq_by_group || {})[g] ? ` 강제청산 ${fmt.int(B.liq_by_group[g])}` : "", (B.bust_by_group || {})[g] ? ` · 파산 ${fmt.int(B.bust_by_group[g])}` : ""))) : null,
    (B.named || []).length ? h("div", {class: "sp-blist", role: "list"}, B.named.slice(0, 3).map((a) =>
      h("a", {class: "sp-brow", role: "listitem", href: env.ctx.href("account", a.account_id)}, ui.acctLabel(a), h("span", {class: "grow"}),
        h("time", null, fmt.hm(a.ts)), ui.pill("파산", "bad")))) : null,
    note("파산 = 잔고 10 USDT 미만으로 계좌 정지. 딥시크·동전 봇은 숫자로만 셉니다."));
}

// ---------------------------------------------------------------- 06 AI 회의 결론
function pMeetings(d, env) {
  const M = d.meetings || {n: 0, lines: []};
  const scene = (text, who) => h("div", {class: "sp-scene"},
    text ? ui.bubble({who, text, tail: "tl", cls: "sp-say"}) : null,
    h("div", {class: "sp-room"},
      h("div", {class: "sp-ppl"}, figure({team: "lead", size: 26}), figure({team: "risk", size: 26}), figure({kind: "spec", size: 26}), figure({team: "review", size: 26})),
      h("div", {class: "sp-table"})));
  const first = (M.lines || [])[0];
  if (!first) {
    return h("div", {class: "sp sp-meet"}, kick(6, "AI 회의 결론"), scene(null),
      h("div", {class: "sp-empty small"}, h("b", null, M.running ? "회의가 아직 진행 중입니다" : `${dayIs(d)} 끝난 회의가 없습니다`),
        h("span", null, M.error ? "회의 기록을 읽지 못했습니다." : "회의가 끝나면 결론이 여기 나옵니다.")));
  }
  const more = (M.lines || [])[1];
  return h("div", {class: "sp sp-meet"}, kick(6, `${dayIs(d)} AI 회의 결론`),
    scene(first.line, `${first.title} · ${fmt.hm(first.ts)}`),
    more ? h("div", {class: "sp-quote"}, h("span", {class: "muted"}, `${more.title} · ${fmt.hm(more.ts)}`), h("span", null, more.line)) : null,
    line(`회의 ${fmt.int(M.n)}번 · 끝난 회의 ${fmt.int(M.finished)}번 · 결정 ${fmt.int(M.decided)}번`,
      M.running ? ` · 진행 중 ${fmt.int(M.running)}` : ""),
    h("div", {class: "sp-acts"}, h("a", {class: "btn-line", href: env.ctx.href("digest", "day", d.today ? null : {d: d.day})}, "회의 요약 보기 →")),
    note("말풍선은 회의 기록에 저장된 결론 그대로입니다. AI는 회의만 하고 주문하지 않습니다."));
}

// ---------------------------------------------------------------- 07 판정까지
function pDday(d, env) {
  const of = d.of || 30;
  const now = Math.min(of, d.dn_now || 0), at = Math.min(of, d.dn || 0);
  const left = d.days_left;
  // one cell per day D+0 .. D+(of-1); the flag is D+of, the verdict day
  const cells = Array.from({length: of}, (_, i) => h("i", {class: [i < now ? "done" : "", i === now ? "now" : "", !d.today && i === at ? "at" : ""]}));
  return h("div", {class: "sp sp-dday"}, kick(7, "판정까지"),
    h("div", {class: "sp-dbig"}, h("span", {class: "sp-led num"}, left == null ? "—" : left > 0 ? `D-${left}` : "D-DAY"),
      h("span", {class: "sp-dsub"}, d.verdict_ts ? `첫 판정 ${fmt.date(d.verdict_ts)} 09:00` : "판정 날짜 확인 중")),
    h("div", {class: "sp-road", role: "img", "aria-label": `${of}일 중 ${now}일 지남`},
      h("div", {class: "sp-cells", style: {"--of": of}}, cells), h("span", {class: "sp-flag"}, pixIcon("flag", 30))),
    h("div", {class: "sp-roadl"}, h("span", null, "D+0"), h("span", null, d.today ? `지금 D+${d.dn_now}` : `이날 D+${d.dn} · 지금 D+${d.dn_now}`), h("span", null, `D+${of} 판정`)),
    line(`그날 계좌마다 ${ui.botsKo()}와 비교해서 합격·불합격을 정합니다. 그 전의 모든 비교는 참고이고, 거래 30건이 안 된 계좌는 '보류'입니다.`),
    h("div", {class: "sp-acts"},
      h("button", {class: "btn-line", type: "button", onclick: () => env.openPicker()}, "다른 날 보기"),
      h("button", {class: "btn-line", type: "button", onclick: () => env.go(0)}, "처음부터"),
      h("a", {class: "btn-y", href: env.ctx.href("checkpoint")}, "판정 화면")));
}
