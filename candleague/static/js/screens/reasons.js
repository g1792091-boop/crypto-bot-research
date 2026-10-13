// #/reasons 청산 이유 (owners 10/13): how the closed trades of each account kind ended. Per kind a stacked bar of 손절 (SL) /
// 계단 잠금 (LOCK) / 규칙 청산 (RULE: 구조 · 스위칭 · 매매법 판단) / 익절 (TP) / 청산당함 (LIQ) with the counts and shares, under it
// the mean ROE of each reason (``reason_mean_roe``: how well that way of ending did). For a 메인 kind, when the snapshot's
// ``pairs`` has data for it, one sentence: the 규칙 청산 count and mean, what the 대조 did on the same signals, and the pair
// totals (better / worse / same). The 손절 좁힘 kind also names how many trades had their stop narrowed (``narrowed_n``). A
// legend says what each reason means in plain words. Data: the snapshot's ``kinds`` and ``pairs`` (versus.js gate).
// HONESTY: a count or mean the snapshot does not carry reads "—", never 0; a bar needs at least one closed trade.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {gate, gateNode, roleOf, totalTrades, val, pc, ppTxt, cnt, sampleNote, groupChip, GROUP_ORDER, GROUP_KO, GROUP_HELP, LIVE_ROLE} from "./versus.js";

export const css = "scr/kinds.css";

export const REASONS = [
  {key: "SL", ko: "손절", help: "가격이 반대로 가서 정해 둔 손절선에 닿아 나감. 손실로 끝나는 보통의 경우입니다."},
  {key: "LOCK", ko: "계단 잠금", help: "이익이 어느 선을 넘으면 손절선을 이익 쪽으로 올려 잠가 두는데, 되돌아와 그 잠금선에 닿아 나감. 이익 일부를 지킨 채 나갑니다."},
  {key: "RULE", ko: "규칙 청산", help: "손절선에 닿기 전에 규칙이 먼저 나가라고 한 경우: 구조가 무너짐 · 반대 신호(스위칭) · 매매법 자체 판단."},
  {key: "TP", ko: "익절", help: "목표 이익에 닿아 나감."},
  {key: "LIQ", ko: "청산당함", help: "증거금이 모자라 거래소가 강제로 닫음(강제청산). 가장 나쁜 경우라서 0건이어야 정상입니다."},
];

const count = (x) => (val(x) == null ? null : Math.max(0, Number(x)));
const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
const totalOf = (k) => REASONS.reduce((a, r) => a + (count(k.reasons && k.reasons[r.key]) || 0), 0);

/** The sentence(s) under a 메인 kind's bar from the snapshot's ``pairs`` (null when it has nothing for this kind). */
export function pairLines(k, d) {
  const pr = d && d.pairs && d.pairs.by_role && d.pairs.by_role[k.role];
  if (k.group !== "main" || !pr || !(Number(pr.n) > 0)) return null;
  const lines = [];
  const rule = count(k.reasons && k.reasons.RULE);
  const rm = val(k.reason_mean_roe && k.reason_mean_roe.RULE);
  if (rule === 0) {
    lines.push("규칙 청산은 아직 0건입니다 (규칙이 손절보다 먼저 나가라고 한 거래가 없습니다).");
  } else if (rule != null && rm != null) {
    const rec = ((d.pairs.recent) || []).filter((x) => x && x.role === k.role && x.a_reason === "RULE" && val(x.a_roe) != null && val(x.b_roe) != null);
    const bm = mean(rec.map((x) => Number(x.b_roe)));
    lines.push(`규칙 청산 ${fmt.int(rule)}건의 평균은 ${pc(rm, true)}${bm == null ? "" : `, 같은 신호의 대조는 ${pc(bm, true)} (최근 짝 ${fmt.int(rec.length)}건 기준)`}.`);
  }
  const shown = val(pr.n_shown) ?? Number(pr.n);
  if (shown > 0 && val(pr.mean_diff_roe) != null) {
    lines.push(`같은 신호끼리 짝지어 보면 (짝 ${fmt.int(shown)}건) 메인이 더 나은 거래 ${fmt.int(pr.better)}건 · 못한 거래 ${fmt.int(pr.worse)}건 · 같은 거래 ${fmt.int(pr.same)}건, 거래당 평균 차이는 ${ppTxt(pr.mean_diff_roe)}입니다.`);
  } else {
    lines.push(`같은 신호의 대조와 짝지은 거래는 ${fmt.int(pr.n)}건입니다 (딥시크 금액이 숨김이라 차이는 계산하지 않았습니다).`);
  }
  return lines;
}

function bar(k, total) {
  const segs = REASONS.map((r) => ({...r, n: count(k.reasons && k.reasons[r.key]) || 0})).filter((r) => r.n > 0);
  const label = segs.map((r) => `${r.ko} ${fmt.int(r.n)}건 (${Math.round((r.n / total) * 100)}%)`).join(", ");
  return h("div", {class: "kd-rbar", role: "img", "aria-label": `끝난 이유: ${label}`},
    segs.map((r) => {
      const share = (r.n / total) * 100;
      return h("span", {class: ["kd-seg", `kd-r-${r.key}`], style: {"--w": `${share.toFixed(2)}%`}, title: `${r.ko} ${fmt.int(r.n)}건 (${Math.round(share)}%)`},
        share >= 14 ? `${r.ko} ${fmt.int(r.n)}` : share >= 7 ? fmt.int(r.n) : null);
    }));
}
function legend(k, total) {
  return h("div", {class: "kd-rleg"}, REASONS.map((r) => {
    const n = count(k.reasons && k.reasons[r.key]);
    const m = val(k.reason_mean_roe && k.reason_mean_roe[r.key]);
    return h("div", {class: ["kd-rc", `kd-r-${r.key}`, n === 0 ? "zero" : ""], title: r.help},
      h("span", {class: "kd-rn"}, h("i", {class: "kd-sw", "aria-hidden": "true"}), r.ko),
      h("b", {class: "num"}, n == null ? "—" : cnt(n)),
      h("small", null, n == null || !total ? "—" : `${Math.round((n / total) * 100)}%`),
      h("span", {class: ["kd-rm", "num", m == null ? "" : fmt.tone(m)]}, n === 0 ? "평균 —" : `평균 ${pc(m, true)}`));
  }));
}
function block(k, d) {
  const total = totalOf(k);
  const lines = pairLines(k, d);
  const narrowed = val(k.narrowed_n);
  return h("article", {class: ["kd-rblock", k.role === LIVE_ROLE ? "kd-live" : ""], "aria-label": k.name, dataset: {role: k.role}},
    h("div", {class: "kd-rh"}, groupChip(k.group), k.role === LIVE_ROLE ? ui.pill("실전 후보", "accent") : null, h("b", null, k.name),
      h("small", null, `${k.suffix} · 끝난 거래 ${fmt.int(total)}건`)),
    total > 0 ? [bar(k, total), legend(k, total)] : ui.empty("아직 끝난 거래가 없습니다"),
    narrowed != null && (k.role === "tg" || narrowed > 0)
      ? h("p", {class: "kd-rtext"}, narrowed > 0 ? `손절을 중간에 좁힌 거래: ${fmt.int(narrowed)}건` : "손절을 중간에 좁힌 거래가 아직 0건입니다") : null,
    lines ? lines.map((t) => h("p", {class: "kd-rtext"}, t)) : null,
    total > 0 && total < 30 ? h("p", {class: "note"}, sampleNote(total)) : null);
}

function hero(kinds) {
  const live = roleOf(kinds, LIVE_ROLE);
  const base = live && totalOf(live) > 0 ? live : kinds.find((k) => k.group === "main" && totalOf(k) > 0) || null;
  let big;
  if (!base) {
    big = h("p", {class: "dl-vbig warn"}, totalTrades(kinds) === 0 ? "아직 거래가 없습니다" : "아직 끝난 이유를 센 거래가 없습니다");
  } else {
    const total = totalOf(base);
    const top = REASONS.map((r) => ({...r, n: count(base.reasons && base.reasons[r.key]) || 0})).sort((a, b) => b.n - a.n)[0];
    big = h("p", {class: "dl-vbig ok"}, `‘${base.name}’ 거래 ${fmt.int(total)}건 중 가장 많이 끝난 이유는 ${top.ko} `,
      h("small", {class: "kd-need"}, `(${cnt(top.n)}, ${Math.round((top.n / total) * 100)}%)`));
  }
  const liq = kinds.filter((k) => (count(k.reasons && k.reasons.LIQ) || 0) > 0);
  return h("section", {class: "card hero dl-verdict s2a-hero kd-hero", "aria-label": "한 줄 결론"},
    h("div", {class: "s2a-hrow"}, ui.plate(base && base.role === LIVE_ROLE ? "실전 후보" : "한 줄 결론")),
    big,
    liq.length ? h("p", {class: "kp-banner bad"}, h("b", null, "청산당함 있음"),
      h("span", null, ` ${liq.map((k) => `${k.name} ${cnt(count(k.reasons.LIQ))}`).join(" · ")} · 증거금이 모자라 강제로 닫힌 거래입니다. 가장 먼저 확인하세요.`)) : null,
    h("p", {class: "note"}, "손절 · 계단 잠금 · 규칙 청산 · 익절 · 청산당함 중 거래가 어떻게 끝났는지와, 끝난 이유마다 평균이 어땠는지를 종류별로 봅니다. 모의 거래 기록이며 앞날을 약속하지 않습니다."),
    h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: "#/versus"}, "메인 vs 대조"), h("a", {class: "btn-line", href: "#/goal"}, "목표 진척도"),
      h("a", {class: "btn-line", href: "#/pairs"}, "같은 신호 짝 비교"), h("a", {class: "btn-line", href: "#/events"}, "규칙이 한 일")));
}
function legendCard() {
  return ui.card({plate: "이유가 뭔가요", sub: "거래가 끝난 방법 다섯 가지", cls: "kd-lcard"},
    h("dl", {class: "kd-legend"}, REASONS.map((r) => h("div", {class: `kd-r-${r.key}`}, h("dt", null, h("i", {class: "kd-sw", "aria-hidden": "true"}), `${r.ko} (${r.key})`), h("dd", null, r.help)))),
    h("p", {class: "note"}, "막대 한 칸의 길이 = 그 이유로 끝난 거래 수. 칸 안의 글자가 안 보이면 아래 숫자 칸을 보세요. ‘평균’은 그 이유로 끝난 거래들의 ROE(증거금 대비) 평균입니다."));
}

export async function mount(el, ctx) {
  el.classList.add("kd");
  const root = h("div", {class: "kd-root"});
  el.append(ui.screenHead("청산 이유", "거래가 손절 · 계단 잠금 · 규칙 청산 · 익절 · 청산당함 중 어떻게 끝났나"), root);
  put(root, ui.missing("종류별 숫자"));

  function paint(d) {
    const g = gate(d);
    if (g.state !== "ok") { put(root, gateNode(g)); return; }
    const kinds = g.kinds;
    put(root, hero(kinds), legendCard(), GROUP_ORDER.map((grp) => {
      const ks = kinds.filter((k) => k.group === grp);
      if (!ks.length) return null;
      const list = h("div", {class: "kd-rlist"}, ks.map((k) => block(k, d)));
      return ui.card({plate: GROUP_KO[grp], sub: GROUP_HELP[grp], cls: "kd-rcard"}, grp === "research" ? ui.disclosure(`연구용 ${ks.length}개 보기`, list) : list);
    }),
    h("p", {class: "assume"}, "청산 이유는 엔진이 거래를 닫을 때 적어 둔 값입니다. 위 다섯 가지가 아닌 이유는 ‘끝난 거래’ 수에 들어가지 않습니다."));
  }
  ctx.onLeague(paint);
}
