// #/telegram 알림 기록: the last 50 Telegram messages the league sent (time in Korea time, the first line, the kind: 요약 / 시작 / 파산 / 경고). The notifier writes them
// into telegram.json when it sends (candleague/notify.py record_sent) and the snapshot carries them as ``telegram`` (a text can be opened in full). The league's texts are
// public numbers only; the server strips control characters and caps a message at 4000 characters, and this screen does it once more. A message that failed to send is not
// in the list. Every string goes in as a text node.
import {h} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {cnt, hero, mountBlock, num} from "./kit4.js";

export const css = ["scr/kinds.css", "scr/s4.css"];
export const RULES_DEFAULT = [
  "무엇을 보여 주나: 후보 리그가 텔레그램으로 보낸 알림을 최근 50개까지 시간순으로 보여 줍니다. 보기만 하는 화면입니다.",
  "종류: 요약은 매일 한국 시각 오전 9시, 시작은 리그를 새로 시작했을 때, 파산은 계좌 잔고가 바닥났을 때, 경고는 경고등이 켜졌을 때입니다.",
  "보내지 못한 알림은 목록에 없습니다. 목록은 5분마다 갱신되므로 방금 보낸 알림은 조금 뒤에 나타납니다.",
];
export const NOTES = [
  "알림 글에는 공개해도 되는 숫자만 들어 있습니다. 화면은 제어 문자를 지우고 한 글을 4,000자까지만 보여 줍니다.",
  "텔레그램 연결이 꺼져 있으면 아무것도 보내지 않으므로 목록은 비어 있습니다.",
];
export const KIND_KO = {summary: "요약", start: "시작", bust: "파산", alert: "경고"};
const KIND_TONE = {summary: "accent", start: "thin", bust: "bad", alert: "warn"};
const CTRL = /[\u0000-\u0009\u000b-\u001f\u007f-\u009f]/g;
export const clean = (t) => String(t == null ? "" : t).replace(/\r/g, "").replace(CTRL, "").slice(0, 4000);

export function normTelegram(d) {
  const x = d && d.telegram;
  if (!x || typeof x !== "object" || Array.isArray(x) || !Array.isArray(x.messages)) return null;
  const msgs = x.messages.filter((m) => m && typeof m === "object" && num(m.ms) != null).map((m) => {
    const text = clean(m.text), title = clean(m.title) || text.split("\n")[0];
    return {ms: Number(m.ms), kind: KIND_KO[m.kind] ? m.kind : "alert", title, text};
  });
  return {headline: "", rules: null, notes: NOTES, cap: num(x.cap) || 50, msgs};
}
function headline(B) {
  const n = B.msgs.length;
  if (!n) return "아직 보낸 알림 기록이 없습니다";
  const by = (k) => B.msgs.filter((m) => m.kind === k).length;
  return `최근 알림 ${fmt.int(n)}개 · 요약 ${fmt.int(by("summary"))} · 시작 ${fmt.int(by("start"))} · 파산 ${fmt.int(by("bust"))} · 경고 ${fmt.int(by("alert"))}`;
}
function row(m) {
  return h("article", {class: "tg-msg", dataset: {kind: m.kind}, "aria-label": `${fmt.kst(m.ms)} ${KIND_KO[m.kind]}`},
    h("div", {class: "tg-h"}, h("span", {class: "num tg-t"}, `${fmt.kst(m.ms)} KST`), ui.pill(KIND_KO[m.kind], KIND_TONE[m.kind] || "thin"), h("b", {class: "tg-title"}, m.title || "—")),
    m.text && m.text !== m.title ? ui.disclosure("전체 보기", h("p", {class: "tg-body"}, m.text)) : null);
}

export async function mount(el, ctx) {
  return mountBlock(el, ctx, {
    id: "telegram", title: "알림 기록", sub: "텔레그램으로 보낸 알림 (최근 50개)", rules: RULES_DEFAULT, norm: normTelegram, seg: false,
    what: "알림 기록 화면은 아직 없습니다.", prep: ["보낸 알림 기록은 아직 없습니다. 위 설명은 그대로 적용됩니다.", "첫 알림(매일 한국 시각 오전 9시 요약 등)이 나가면 저절로 나타납니다. 텔레그램 연결이 꺼져 있으면 계속 비어 있습니다."],
    hero: (B) => hero(headline(B), B.msgs.length ? `가장 최근: ${fmt.kst(B.msgs[0].ms)} KST · ${KIND_KO[B.msgs[0].kind]}` : "", "기록만 보여 줍니다. 어떤 행동도 권하지 않습니다."),
    body: (B) => ui.card({plate: "보낸 알림", sub: `최근 ${cnt(B.cap, "개")}까지 · 새것이 위`, cls: "kd-tcard s4-card", id: "tg-list"},
      B.msgs.length ? h("div", {class: "tg-list"}, B.msgs.map(row)) : ui.empty("아직 보낸 알림이 없습니다.")),
    words: null,
  });
}
