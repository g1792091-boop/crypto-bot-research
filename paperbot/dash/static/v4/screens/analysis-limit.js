// 분석 › 그림자 비교 › 지정가 진입 (ana8B): /api/analysis/shadows .limit_entry (dash/more/shadowplus.py).
// Per group (기존 36 / 딥시크 / 5분 단타) since the run start: signals, fill rate, the filled limit shadows' mean net ROE
// next to the same signals' market entry (base), and the signals a limit order would have missed (share, their result).
// HONESTY: ROE (%) and counts only, every group (DeepSeek is never priced); descriptive, no verdict; small samples say so.
import {h, ui, fmt} from "../core/pb.js";

const NEED = 10;                      // paired signals before the comparison means much (riskreward.SMALL_N)
const roe = (x) => (x == null ? "—" : fmt.pct(x, 1));

function row(g, c, ko) {
  const n = c.signals || 0;
  if (!n) return h("div", {class: "lrow an-row", role: "listitem"}, h("span", {class: "rk"}, ko), h("span", {class: "lname muted"}, "아직 없음 · 밤 점검이 신호를 쌓으면 나옴 (짝 10쌍부터 볼 만함)"));
  return h("div", {class: "lrow an-row", role: "listitem"},
    h("span", {class: "rk"}, ko),
    h("span", {class: "lname"}, `신호 ${fmt.int(n)}개 · 체결 ${fmt.pct(c.fill_rate, 0, false)}`),
    h("span", {class: ["ret num", fmt.tone(c.paired_diff_roe)], title: "체결된 지정가 − 같은 신호의 시장가 (ROE)"}, c.paired ? roe(c.paired_diff_roe) : "—"),
    h("span", {class: "meta"},
      h("span", null, `체결 평균 ${roe(c.filled_mean_roe)}`),
      c.paired ? h("span", null, `같은 신호 지정가 ${roe(c.paired_limit_roe)} · 시장가 ${roe(c.paired_base_roe)} (${fmt.int(c.paired)}쌍)`) : h("span", null, "시장가와 짝지은 신호 없음"),
      h("span", null, `놓침 ${fmt.pct(c.missed_share, 0, false)}`, c.missed_traded ? ` · 그 신호의 시장가 ${roe(c.missed_base_roe)}, 이긴 비율 ${fmt.pct(c.missed_base_win_share, 0, false)}` : ""),
      c.open ? h("span", null, `아직 안 끝남 ${fmt.int(c.open)}`) : null,
      ui.smallSample(c.paired || 0, NEED)));
}

/** The card (null when the server sent no block: an older server). */
export function limitEntry(d) {
  const L = d && d.limit_entry;
  if (!L) return null;
  const gs = L.groups || {}, ko = L.group_ko || {};
  const order = L.order || Object.keys(gs);
  return ui.card({plate: "지정가 진입", sub: "그림자 · 설명용"},
    h("p", {class: "an-read"}, h("b", null, "읽는 법 "), "시장가 대신 0.25 ATR 유리한 지정가를 한 봉 동안 걸었다면. 오른쪽 숫자 = 체결된 신호에서 지정가 − 시장가 (ROE). 놓침 = 지정가가 닿지 않아 못 들어간 신호."),
    L.error ? h("p", {class: "an-warn"}, String(L.error)) : null,
    h("div", {class: "plist", role: "list"}, order.map((g) => row(g, gs[g] || {}, ko[g] || g))),
    h("p", {class: "an-note"}, "ROE와 개수만 봅니다 (딥시크도 돈으로 보지 않음). ", L.note || ""));
}
