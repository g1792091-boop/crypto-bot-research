// #/costs 실제 비용: what fees, slippage and funding took out of the profit, per account kind (실전 후보, 대조 and their coin-flip twins, and the four together).
// EVERY figure is an estimate and says so: the stored trade has its prices, leverage, P&L and ROE but not its costs, so the server rebuilds them from the league's
// rules (taker fee 0.05% + slippage 0.02%, in and out = 0.14% of the position) and from the stored prices (candleague/costview.py). A number that cannot be derived
// is "—" (or "확인 못 함" next to its reason), never a guess. Data: the snapshot's ``costs``. Counts and money only; no advice.
import {h} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {cnt, hero, kindView, legend, mountBlock, num, pctx, strs} from "./kit4.js";

export const css = ["scr/kinds.css", "scr/s4.css"];
/** The rules as the server writes them (candleague/costview.cost_rules_ko, same order and words); used when the snapshot has none. */
export const RULES_DEFAULT = [
  "무엇을 보여 주나: 수수료 · 미끄러짐(슬리피지) · 펀딩비가 수익을 얼마나 깎았는지 보여 줍니다. 모두 추정이고 무엇을 하라는 말은 없습니다.",
  "저장되지 않은 값: 거래 기록에는 수수료 · 미끄러짐 · 펀딩비가 따로 저장돼 있지 않아서, 저장된 가격 · 배수 · 손익으로 되짚거나 규칙에서 계산했습니다.",
  "규칙 기준 왕복 비용: 시장가 수수료 0.05% + 미끄러짐 0.02%, 들어갈 때와 나갈 때 모두 해서 포지션 크기의 0.14%입니다. 배수가 클수록 증거금 대비로는 더 크게 느껴집니다 (0.14% × 배수).",
  "되짚은 비용: 가격이 움직인 만큼의 수익률에서 실제 수익률을 빼면 수수료와 펀딩비가 남습니다. 저장된 체결가에는 미끄러짐이 이미 들어 있어서, 미끄러짐은 규칙으로 더했습니다.",
  "강제청산 거래는 증거금을 잃은 것이라 비용 계산에서 뺐습니다.",
];
const money = (x) => (num(x) == null ? "—" : fmt.money(x));

export function normCosts(d) {
  const x = d && d.costs;
  if (!x || typeof x !== "object" || Array.isArray(x) || !Array.isArray(x.kinds) || !x.kinds.length) return null;
  return {headline: typeof x.headline_ko === "string" ? x.headline_ko : "", rules: strs(x.rules_ko).length ? strs(x.rules_ko) : null, notes: strs(x.note_ko), dsIn: x.ds_in_stats === true,
    kinds: x.kinds.filter((k) => k && typeof k === "object")};
}
/** The five cells of a kind (also what the table and the cards show): [{key, label, help, cell}]. */
export const COLS = [
  {key: "rt", label: "왕복 비용 · 증거금 대비 (추정)", help: "규칙 기준: 시장가 수수료 + 미끄러짐을 들어갈 때와 나갈 때 합친 0.14% × 배수",
    cell: (k) => ({v: pctx(k.rt_roe, 1), sub: num(k.lev_mean) == null ? "" : `배수 평균 ${fmt.num(k.lev_mean, 1)}배 · 0.14% × 배수 · 거래 ${cnt(k.lev_n, "건")}`})},
  {key: "cost", label: "비용 합계 (추정)", help: "되짚은 수수료 + 펀딩비에 규칙의 미끄러짐을 더한 달러 합계",
    cell: (k) => ({v: money(k.cost), sub: num(k.cost) == null ? "" : `수수료 · 펀딩 ${money(k.fee_funding)} + 미끄러짐 ${money(k.slip)}`})},
  {key: "share", label: "총손익 대비 비용 (추정)", help: "비용 합계 ÷ (순손익 + 비용). 총손익이 0 이하이면 비율이 의미 없어 확인 못 함",
    cell: (k) => (num(k.share) != null ? {v: pctx(k.share, 1), sub: `총손익 ${money(k.gross)} · 순손익 ${money(k.net)}`}
      : num(k.cost) != null ? {v: "확인 못 함", sub: `총손익 ${money(k.gross)}이라 비율이 의미 없음`} : {v: "—", sub: ""})},
  {key: "per", label: "거래 한 번 비용 vs 평균 순 ROE (추정)", help: "거래 한 번에 평균 증거금의 몇 %가 비용이었는지, 같은 거래들의 평균 순 수익률과 나란히",
    cell: (k) => (num(k.cost_roe) == null ? {v: "—", sub: ""}
      : {v: `${pctx(k.cost_roe, 2)} vs ${pctx(k.net_roe, 2, true)}`, sub: num(k.ratio) != null ? `비용이 평균 순 ROE의 ${pctx(k.ratio, 0)}` : "평균 순 ROE가 0 이하라 비교 안 함 (확인 못 함)"})},
  {key: "n", label: "계산에 쓴 거래", help: "비용을 되짚을 수 있었던 닫힌 거래 수 (강제청산 · 가격이나 배수가 없는 거래는 뺌)",
    cell: (k) => ({v: `${cnt(k.cost_n, "건")} / ${cnt(k.trades, "건")}`, sub: (num(k.liq) || 0) > 0 ? `강제청산 ${cnt(k.liq, "건")} 뺌` : (num(k.cost_n) === 0 ? "확인 못 함" : "")})},
];

export async function mount(el, ctx) {
  return mountBlock(el, ctx, {
    id: "costs", title: "실제 비용", sub: "수수료 · 미끄러짐 · 펀딩비가 수익을 얼마나 깎았나 (모두 추정)", rules: RULES_DEFAULT, norm: normCosts, seg: true, viewKey: "costs-view",
    what: "실제 비용 화면은 아직 없습니다.", prep: ["비용 기록은 아직 없습니다. 위 규칙은 그대로 적용됩니다.", "엔진이 기록을 쓰면 (5분마다) 저절로 나타납니다. 닫힌 거래가 있어야 숫자가 생깁니다."],
    hero: (B) => hero(B.headline || "비용을 계산 중입니다", `보는 종류 ${fmt.int(B.kinds.length)}개 · 모든 숫자는 추정입니다 (거래소 명세서가 아닙니다)`, "추정입니다. 앞으로를 약속하는 숫자가 아니고, 어떤 행동도 권하지 않습니다."),
    body: (B, view) => ui.card({plate: "비용이 깎은 몫", sub: "종류별 · 닫힌 거래 기준 · 모두 추정", cls: "kd-tcard s4-card", id: "cs-main"},
      h("p", {class: "note"}, "‘총손익’은 순손익에 비용을 다시 더한 값입니다. 총손익이 0 이하이면 비용 비율은 확인 못 함으로 둡니다."), kindView(B.kinds, COLS, view, "계좌 종류별 추정 비용")),
    words: () => legend([
      ["수수료", "거래소에 내는 돈입니다. 들어갈 때와 나갈 때 한 번씩, 시장가는 포지션 크기의 0.05%입니다."],
      ["미끄러짐(슬리피지)", "주문한 가격과 실제로 체결된 가격의 차이입니다. 이 리그는 불리한 쪽으로 0.02%를 가정합니다."],
      ["펀딩비", "선물 거래에서 롱과 숏이 8시간마다 주고받는 돈입니다. 포지션을 오래 들고 있으면 쌓입니다."],
      ["증거금 대비", "포지션 크기가 아니라 내가 건 증거금을 기준으로 본 비율입니다. 배수가 크면 같은 비용도 증거금 대비로는 몇 배 커집니다."],
      ["총손익", "비용을 빼기 전의 손익입니다. 순손익에 비용을 더해 구했습니다."],
      ["추정", "저장된 값이 아니라 규칙과 가격에서 다시 계산한 값입니다. 실제와 조금 다를 수 있습니다."]]),
  });
}
