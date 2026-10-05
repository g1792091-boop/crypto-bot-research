// 용어 사전 (다듬기 7-4): the number names the screens use, two plain lines each. Shown at the top of 자주 묻는 질문
// (#/faq?q=<term> opens that term), and as small "?" chips next to those names on the account screen (termChip /
// termify). Text only (h()); the lock numbers come from positions-kit's LADDER (config.py), never typed twice.
import {h, ui, motion, href} from "../core/pb.js";
import {LADDER} from "./positions-kit.js";

const pct = (x) => `${Math.round(x * 100)}%`;

/** The terms in reading order: {id, alias: [other names ?q= may carry], lines: [two short sentences]}. */
export const TERMS = [
  {id: "레버리지", alias: ["배수", "레버"], lines: [
    "증거금의 몇 배 크기로 거래하는지입니다. 30배면 증거금 100으로 3,000어치를 사고팝니다.",
    "배수가 클수록 같은 가격 움직임에 손익이 커지고 청산가도 가까워집니다."]},
  {id: "증거금", alias: ["마진"], lines: [
    "포지션을 열 때 맡겨 두는 돈입니다. 손실은 이 돈에서 빠집니다.",
    "격리 방식이라 한 포지션이 잃을 수 있는 돈은 그 포지션의 증거금까지입니다."]},
  {id: "청산가", alias: ["강제청산", "청산"], lines: [
    "손실이 증거금을 거의 다 먹는 가격입니다. 닿으면 거래소가 포지션을 강제로 닫습니다.",
    "모의 계좌도 같은 계산을 합니다. 보통은 손절선이 청산가보다 먼저 옵니다."]},
  {id: "손절·잠금", alias: ["손절", "잠금", "손절가", "잠금선", "익절 잠금"], lines: [
    "손절은 진입 때 정한 손실 자리에서 나가는 주문입니다. 잠금은 수익이 나면 손절선을 수익 쪽으로 올려 번 것을 지키는 것입니다.",
    `순 ROE +${pct(LADDER.first + LADDER.gap)}가 되면 +${pct(LADDER.first)}를 잠그고, 그 뒤 ${pct(LADDER.step)}씩 올리며 내리지 않습니다. 5분봉 단타는 잠금 없이 자기 규칙으로 나갑니다.`]},
  {id: "ROE", alias: ["ROI", "roe", "roi"], lines: [
    "증거금 대비 손익 비율입니다. 증거금 100으로 10을 벌면 ROE +10%입니다.",
    "30배면 가격이 1% 움직일 때 ROE는 약 30% 움직입니다. 열린 포지션의 ROI도 같은 뜻입니다."]},
  {id: "최대 낙폭", alias: ["낙폭", "MDD", "mdd"], lines: [
    "잔고가 가장 높았던 때부터 가장 많이 떨어진 비율입니다.",
    "얼마나 크게 흔들렸는지 보여 줍니다. 수익률이 같으면 낙폭이 작은 쪽이 덜 아픕니다."]},
  {id: "승률", alias: [], lines: [
    "닫힌 거래 중 수익으로 끝난 거래의 비율입니다.",
    "승률이 낮아도 이길 때 크게 벌면 수익일 수 있어서, 승률 하나로 좋고 나쁨을 정하지 않습니다."]},
  {id: "펀딩비", alias: ["펀딩"], lines: [
    "무기한 선물에서 보통 8시간마다 롱과 숏이 서로 주고받는 돈입니다. 비율이 +면 롱이 내고 숏이 받습니다.",
    "비율이 −면 반대로 숏이 내고 롱이 받습니다. 모의 계좌도 펀딩을 손익에 넣어 셉니다."]},
  {id: "중앙값", alias: ["median"], lines: [
    "줄을 세웠을 때 한가운데 값입니다. 계좌가 5개면 3번째 값입니다.",
    "평균과 달리 한두 계좌의 큰 수익·손실에 끌려가지 않아 묶음끼리 견줄 때 씁니다."]},
];

/** ?q= (any alias, any case, spaces ignored) -> the term id, or null. */
export function findTerm(q) {
  const k = String(q || "").replace(/\s+/g, "").toLowerCase();
  if (!k) return null;
  const norm = (x) => String(x).replace(/\s+/g, "").toLowerCase();
  const t = TERMS.find((x) => norm(x.id) === k || x.alias.some((a) => norm(a) === k));
  return t ? t.id : null;
}

/** The small "?" link next to a number name: #/faq?q=<term>. */
export function termChip(term) {
  const id = findTerm(term) || term;
  return h("a", {class: "ft-q", href: href("faq", null, {q: id}), title: `'${id}' 뜻 보기`, "aria-label": `${id} 뜻 보기`}, "?");
}

// which labels get a chip: the label's text (start) -> the term
const LABELS = [[/^최대 낙폭/, "최대 낙폭"], [/^승률/, "승률"], [/^청산가/, "청산가"], [/^증거금/, "증거금"],
  [/^(손절가|잠금선|익절 잠금)/, "손절·잠금"], [/^(ROI|ROE)$/, "ROE"], [/^왜 .*배$/, "레버리지"]];
/** Put a "?" chip after every known number name inside root (stat labels, kv names, the LED labels, the why plate).
 *  Safe to call again: a label that already has its chip is left alone. Returns the number of chips added. */
export function termify(root) {
  if (!root || !root.querySelectorAll) return 0;
  let n = 0;
  for (const el of root.querySelectorAll(".stat > .k, dl.kv dt, .pnl .k, .pos-why .plate")) {
    if (el.querySelector(".ft-q")) continue;
    const t = el.textContent.trim();
    const hit = LABELS.find(([re]) => re.test(t));
    if (!hit) continue;
    el.append(" ", termChip(hit[1]));
    n++;
  }
  return n;
}

/** The 용어 사전 card (top of the FAQ). want: the ?q= term to open and scroll to (null: all closed). */
export function termsCard(want) {
  const open = findTerm(want);
  let target = null;
  const rows = TERMS.map((t, i) => {
    const id = `ft-a${i}`, on = t.id === open;
    const region = h("div", {class: "ft-a", id, role: "region", hidden: !on}, t.lines.map((x) => h("p", null, x)));
    const btn = h("button", {class: "ft-t", type: "button", "aria-expanded": String(on), "aria-controls": id},
      h("b", null, t.id), h("span", {class: "ft-first"}, t.lines[0]), h("i", {class: "faq-car", "aria-hidden": "true"}));
    btn.addEventListener("click", () => {
      const o = btn.getAttribute("aria-expanded") !== "true";
      btn.setAttribute("aria-expanded", String(o));
      row.classList.toggle("open", o);
      motion.expand(region, o);
    });
    const row = h("div", {class: ["ft-row", on ? "open sel" : ""], dataset: {term: t.id}}, btn, region);
    if (on) target = row;
    return row;
  });
  const el = ui.card({plate: "용어 사전", sub: "숫자 이름의 뜻 · 두 줄씩", cls: "ft-card"}, h("div", {class: "ft-list"}, rows),
    ui.note("계좌 화면에서 숫자 이름 옆 ? 를 누르면 여기로 옵니다."));
  /** After the card is on the page: bring the asked term into view (a real arrival by link: one soft tint). */
  el.focusTerm = () => {
    if (!target || !target.isConnected) return;
    target.scrollIntoView({block: "center", behavior: motion.reduced() ? "auto" : "smooth"});
    motion.flash(target);
  };
  return el;
}
