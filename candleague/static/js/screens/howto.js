// #/howto 읽는 법: what the 후보 리그 is, its five accounts per pick, how to read every number, the checks and their dates
// (WATCH_PREREG), the pick characters, what each screen shows, and the real-money rule. Static text (and the dates from
// the snapshot when it is there).
import {h} from "../dom.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {ROLES, ROLE_DESC, STYLE_KO, STYLE_DESC} from "../labels.js";

const SCREENS = [
  ["요약", "다음 점검까지 며칠, 묶음 두 개(기존 36 · 딥시크)의 지금, 후보 합계 잔고, 상위 · 하위 5, 최근 체결"],
  ["점검 진행", "11/11 · 12/11 · 1/11 기준을 오늘 숫자에 대어 본 것 (참고), 후보마다 기준, 경고등, 매매법별 묶음"],
  ["순위표", "후보 38개를 줄 세운 표. 카드를 누르면 1/4 · 청산만 · 기본값 · 동전 계좌로 바뀜"],
  ["5계좌 비교", "후보마다 다섯 계좌를 한 줄에. 좋아진 게 숫자 덕인지 청산 덕인지, 운인지"],
  ["커스텀값", "후보마다 기본값에서 바뀐 숫자(한글 이름, 기본 → 커스텀, 배수), 익절 · 손절, 어디서 왔나, 성격"],
  ["매매법", "16개 매매법의 진입 방식(롱 · 숏), 조절 숫자, 후보들, 묶음 성적"],
  ["주간 흐름", "주마다 후보 · 기본값 · 동전의 거래 수 · 승률 · 합계 (2차 점검의 운 검사 단위)"],
  ["터미널", "거래소 화면처럼: 코인 6개, 캔들 차트에 고른 계좌의 진입 · 청산, 열린 포지션, 최근 체결"],
  ["진입 차트", "매매법마다 따로: 후보 하나에 차트 하나, 들어간 자리 ▲▼ · 나온 자리 ● · 진입가 · 열린 포지션의 손절 · 익절. ◀ ▶로 다른 진입"],
  ["포지션 · 체결 기록", "지금 열린 포지션 전부, 최근 닫힌 거래 300건"],
  ["서버 상태", "엔진이 어디까지 처리했나, 늦음, 서버 부하 · 메모리, 시세 연결"],
];

export async function mount(el) {
  const d = LK.league();
  const cps = (d && d.watch && d.watch.checkpoints) || [
    {ko: "1차 점검", date: "2026-11-11", what: "멈출지 보기"}, {ko: "2차 점검", date: "2026-12-11", what: "통과 보기"}, {ko: "3차 점검", date: "2027-01-11", what: "2차에서 못 넘은 묶음만"}];
  el.append(
    ui.screenHead("읽는 법", "후보 리그를 처음 보는 분을 위한 안내"),
    ui.card({plate: "후보 리그가 뭔가요"},
      h("p", null, "5년 백테스트 전체 탐색에서 아깝게 떨어진 커스텀값 후보 38개(기존 36 매매법 23개 · 딥시크 15개)를, 백테스트에 없던 10월 1일부터 종이 매매로 시험합니다. ",
        "규칙봇과 같은 엔진 · 같은 크기 규칙($5,000 시작, 좋은 자리 50/40배 · 보통 30/20배, 수수료 · 슬리피지 · 펀딩 · 강제청산 · 파산 포함)으로 계산하고 주문은 넣지 않습니다."),
      h("p", {class: "note"}, "목록은 시작 전에 고정했습니다. 6일, 2주 성적으로 바꾸지 않습니다. 짧은 기간 성적은 운이 큽니다.")),
    ui.card({plate: "후보마다 계좌 5개"}, h("dl", {class: "kv"}, ROLES.map((r) => h("div", null, h("dt", null, LK.roleChip(r)), h("dd", null, ROLE_DESC[r])))),
      h("p", {class: "note"}, "다섯 계좌는 같은 시세 · 같은 기간이라 바로 비교됩니다. 후보 > 청산만이면 숫자(커스텀값) 덕, 청산만 > 기본값이면 익절 · 손절 덕, 동전보다 못하면 방향을 맞힌 게 아닐 수 있습니다.")),
    ui.card({plate: "숫자 읽는 법"}, h("dl", {class: "kv"},
      h("div", null, h("dt", null, "한 번 평균"), h("dd", null, "닫힌 거래마다 (손익 ÷ 그 직전 지갑)의 평균. +0.10%면 거래 한 번에 지갑이 평균 0.1% 늘었다는 뜻. 점검도 이 단위로 합니다.")),
      h("div", null, h("dt", null, "묶음 평균"), h("dd", null, "그 묶음 모든 계좌의 거래를 한데 모은 한 번 평균 (계좌 평균의 평균이 아님).")),
      h("div", null, h("dt", null, "잔고 · 최대 낙폭"), h("dd", null, "닫힌 거래까지의 지갑과, 가장 높았던 지갑에서 가장 많이 내려간 비율.")),
      h("div", null, h("dt", null, "증거금 대비"), h("dd", null, "그 거래에 건 증거금에 대한 손익 (레버리지가 곱해진 값).")),
      h("div", null, h("dt", null, "아직 (30번 전)"), h("dd", null, "닫힌 거래 30번 전에는 판단하지 않습니다. 몇 번은 운으로 얼마든지 좋거나 나쁠 수 있습니다.")),
      h("div", null, h("dt", null, "▲ ▼"), h("dd", null, "같은 후보의 다른 계좌보다 한 번 평균이 높으면 ▲, 낮으면 ▼. 비교일 뿐 판정은 아닙니다.")),
      h("div", null, h("dt", null, "경고등"), h("dd", null, "기존 36 후보가 백테스트로 본 예상 범위의 하위 5%보다 낮으면 켜집니다. 23개 중 1개쯤은 운으로도 켜집니다. 알림일 뿐입니다.")))),
    ui.card({plate: "점검 (미리 고정)"}, h("ul", {class: "cl-checks"}, cps.map((c) => h("li", null, h("b", null, `${c.ko} ${c.date || ""}`), h("span", null, ` · ${c.what}`)))),
      h("p", null, "기존 36과 딥시크는 따로 점검합니다. 2차 통과 조건: 후보 평균 > 0이고 운 검사(주 단위로 섞어 2,000번 다시 뽑기) p < 0.05, 기본값보다 · 동전보다 나음, 후보 거래 300번 이상."),
      h("p", {class: "note"}, "점검 진행 화면의 ‘지금이면’은 참고입니다. 판정은 점검 날 정해 둔 계산으로 한 번 합니다.")),
    ui.card({plate: "후보의 성격"}, h("dl", {class: "kv"}, Object.entries(STYLE_KO).map(([k, v]) => h("div", null, h("dt", null, LK.styleChip(k)), h("dd", null, STYLE_DESC[k])))),
      h("p", {class: "note"}, "추세 비율 = 들어간 방향이 직전 20봉 움직임과 같은 비율 (2021~2026-09, 그 후보의 숫자와 청산으로). 38개 중 추세 따라가기 28 · 섞임 7 · 되돌림 · 박스 3.")),
    ui.card({plate: "화면 안내"}, h("dl", {class: "kv"}, SCREENS.map(([k, v]) => h("div", null, h("dt", null, k), h("dd", null, v))))),
    ui.card({plate: "실제 돈"}, h("p", null, "후보 리그는 종이 매매입니다. 2차 점검에서 묶음이 통과하고, 그 매매법도 통과했을 때만 두 분이 실제 돈을 검토할 수 있습니다: 1/4 크기 이하, 잃어도 되는 금액, 실행기 한도 켜고, 테스트넷 연습을 마친 뒤. 2차를 두 번 못 넘은 묶음은 끝납니다.")));
}
