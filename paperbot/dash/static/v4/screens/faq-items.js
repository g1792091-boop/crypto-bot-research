// 자주 묻는 질문 (builder E): the questions, in the 두 분 voice, short. `a(f, ctx)` returns the answer's nodes; f = live
// facts {verdict (ms), usage, debate}. Every fact here was checked against the code (config.py v4, checkpoint.py
// the verdict's method from the server (ui.botsKo / ui.methodKo: N_BOTS and the per-group error budget), deploy/*.env.example for what costs money).
import {h, ui, fmt} from "../core/pb.js";

const P = (...kids) => h("p", null, ...kids);
const go = (ctx, name, label) => h("a", {class: "btn-line", href: ctx.href(name)}, label);

export const FAQ = [
  {group: "기본", items: [
    {q: "이 돈은 진짜인가요?", a: () => [
      P("아니요. 모든 계좌는 모의(가상 돈)입니다. 실제 시세로 계산하고 수수료·펀딩·슬리피지를 빼서 진짜에 가깝게 셈하지만, 거래소에 주문을 보내지 않습니다."),
      P("이 대시보드에는 주문 버튼이 없습니다.")]},
    {q: "AI 회의 구조는 어디서 왔고, 한계는요?", a: () => [
      P("TradingAgents 논문(분석가 → 낙관·비관 토론 → 리스크 → 판정) 구조를 참고했습니다. 논문의 시험은 몇 달, 몇 종목뿐이고 동전 던지기 비교가 없어 돈을 번다는 증거가 아닙니다."),
      P("그래서 AI 판정은 기록·채점만 하고, 동전 던지기와 함께 보여 드립니다."),
      h("a", {class: "btn-line", href: "/api/doc/tradingagents-limits", target: "_blank", rel: "noopener"}, "한계 정리 (한 장)")]},
    {q: "AI가 사고파나요?", a: (f, ctx) => [
      P("아니요. 사고파는 것은 정해 둔 코드(매매법)뿐입니다. AI 직원은 회의하고 기록만 하며, 주문·규칙·계좌를 바꾸지 못합니다."),
      P("관찰 기간이 끝나면 새 계좌를 제안할 수 있지만, 두 분이 승인해야만 시작합니다."), go(ctx, "office", "회의실 보기")]},
    {q: "동전 봇은 왜 있나요?", a: () => [
      P("실력인지 운인지 가리는 비교 기준입니다. 같은 봉에서 같은 청산 규칙으로, 들어가는 자리만 무작위로 고릅니다."),
      P("동전 봇보다 꾸준히 나아야 실력이라고 볼 수 있습니다. 동전 봇 자신은 판정하지 않습니다.")]},
    {q: "결론은 언제 나오나요?", a: (f, ctx) => [
      P(`${f.verdict ? `${fmt.date(f.verdict)} 09:00` : "30일째 아침 09:00"}에 코드가 판정합니다. 계좌마다 ${ui.botsKo()}와 비교하고, 여러 계좌를 함께 보므로 묶음마다 보정합니다 (${ui.methodKo()}).`),
      P("거래가 30건이 안 된 계좌는 '보류', 4시간봉 계좌는 관찰용입니다. 그 전의 모든 비교는 '참고'입니다."), go(ctx, "checkpoint", "판정 화면")]},
    {q: "계좌 그룹은 무엇인가요?", a: (f, ctx) => [
      P("기존 36(검증해 둔 매매법), 딥시크 44(딥시크가 고른 정의), 5분봉(5분봉 단타 1개, 같은 청산 규칙의 5분봉 동전 봇 3개를 비교로 함께 보여 줌), 동전 봇(비교 기준, 5분봉 3개 포함)입니다."),
      go(ctx, "howto", "어떻게 돌아가나")]},
  ]},
  {group: "숫자 읽는 법", items: [
    {q: "'참고'는 무슨 뜻인가요?", a: (f) => [
      P(ui.pill("동전 봇보다 위", "ref"), " 처럼 붙습니다. 판정 날 전의 비교라 합격·불합격을 뜻하지 않습니다."),
      ui.refNote(f.verdict)]},
    {q: "'표본 적음'은요?", a: () => [
      P(ui.pill("표본 적음", "thin"), " 거래가 30건보다 적은 계좌에 붙습니다. 몇 번 안 되는 거래는 운만으로도 크게 이기거나 질 수 있어 숫자를 믿기 이릅니다.")]},
    {q: "'수집 전'은요?", a: (f, ctx) => [
      P(ui.notYet(), " 서버가 아직 보내지 않는 숫자입니다. 빈칸을 채우려고 숫자를 지어내지 않습니다."),
      P("지금은 CPU·메모리·디스크, 데이터베이스 크기, 텔레그램 보낸 수, 중앙값 곡선이 그렇습니다."), go(ctx, "server", "서버·비용")]},
    {q: "돈 숫자 밑의 작은 글씨는요?", a: () => [
      ui.assume(), P("모의 계좌의 숫자라는 뜻과, 실제 시세에 수수료·펀딩·슬리피지를 넣어 셈했다는 뜻입니다."),
      P("열린 포지션의 손익은 마크 가격 기준이고, 나갈 때 내는 수수료를 빼기 전 값입니다.")]},
    {q: "딥시크 계좌에는 왜 계좌별 비교가 없나요?", a: () => [
      P("계좌가 171개나 되어 몇 개는 운만으로도 동전 봇보다 잘 나옵니다. 그래서 계좌 하나하나에는 '참고' 표시만 하고, 그룹 전체의 중앙값만 보여 드립니다."),
      P("판정은 이 점을 보정해서 합니다.")]},
  ]},
  {group: "화면", items: [
    {q: "오른쪽 위 점의 색은요?", a: (f, ctx) => [
      P(h("b", {class: "up"}, "초록"), " 정상 · ", h("b", {class: "warn-t"}, "주황"), " 확인할 것 있음 · ", h("b", {class: "down"}, "빨강"), " 무언가 멈춤."),
      P("파산, 15분 안의 강제청산 3건 이상, 시세·봇 신호 끊김은 맨 위에 빨간 띠로도 나옵니다. 점을 누르면 서버 화면으로 갑니다."), go(ctx, "server", "서버·비용")]},
    {q: "'연결 끊김'이라고 나와요", a: () => [
      P("실시간 연결이 끊기면 화면이 스스로 다시 연결합니다. 몇 분 넘게 계속되면 휴대폰이나 PC의 Tailscale이 켜져 있는지 확인해 주세요."),
      P("봇은 화면과 상관없이 서버에서 계속 돕니다.")]},
    {q: "알림은 어디서 다시 보나요?", a: (f, ctx) => [
      P("서버에 남은 경고·밤 점검·작업 기록은 '알림 기록'에 있습니다. 텔레그램으로 보낸 글의 원문은 서버에 따로 저장되지 않습니다."), go(ctx, "alerts", "알림 기록")]},
  ]},
];

/** What costs money (owners' table). Live parts come from /api/agents/usage and /api/debate. */
export function costRows(f) {
  const u = f.usage, d = f.debate, sp = d && d.spend;
  const usd = fmt.usd;
  return [
    {tag: "무료", cls: "good", what: "모의 봇, 이 대시보드, 바이낸스 공개 시세, 텔레그램 알림, Tailscale (개인용 무료 요금제)"},
    {tag: "Max 구독", cls: "accent", what: "AI 직원 회의. 두 분의 Claude Max 월 구독 안에서 쓰고, 하루·주간 한도를 둡니다. 호출마다 돈이 더 나가지 않습니다.",
      now: u ? `오늘 ${fmt.int(u.calls)}${u.cap_calls ? ` / ${fmt.int(u.cap_calls)}` : ""}회${u.week ? ` · 7일 ${fmt.int(u.week.calls)}${u.week.cap_calls ? ` / ${fmt.int(u.week.cap_calls)}` : ""}회` : ""}` : null},
    {tag: "유료 API", cls: "warn", what: "24시간 토론방. 따로 만든 API 키로 쓴 만큼 돈이 나가고, 월 한도에 닿으면 그달은 멈춥니다.",
      now: !f.debateOn ? "지금 꺼짐 · 쓴 돈 0" : sp ? `이번 달 ${usd(sp.month)}${sp.cap ? ` / 한도 ${usd(sp.cap)}` : ""} (실제 돈)` : `상태: ${(d && d.state_ko) || "읽는 중"}`},
    {tag: "서버 임대", cls: "thin", what: "Vultr 서버. 매달 고정 요금이며 금액은 Vultr 청구서에 나옵니다."},
  ];
}
