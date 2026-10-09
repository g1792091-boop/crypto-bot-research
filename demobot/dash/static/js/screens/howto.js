// #/howto 어떻게 돌아가나: a plain Korean explanation of the demo lab (demobot/CONTRACT.md): what runs, the 48
// accounts, the exits, the costs, the two judgment rules, that it never places orders, how it differs from the rule bot.
// The settings' numbers come from /api/grid and the rules' words from /api/judge when they are there.
// Round 3 (CONTRACT 8): the confirmation period, the stop rules, the 12/31 goal line, and one short card per new screen
// (거래 차트, 시장 국면, 실제 비용, 비교, 설정 지도, 코인별, 주간 회의록, 알림 기록, 서버 상태의 새 카드).
import {h, put} from "../dom.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {STRAT_KO} from "../labels.js";

const ACCOUNTS = [
  ["고정 · 기본값", "fx-def-매매법-봉", 6, "매매법 기본값을 그대로 돌립니다"],
  ["고정 · 친구 값", "fx-fr-매매법-봉", 4, "친구가 쓰는 값을 그대로 (S2, N04만)"],
  ["고정 · 5년 1등 값", "fx-pk-매매법-봉", 6, "5년 연구에서 1등으로 뽑힌 값을 그대로"],
  ["자동 · 5거래마다(26주)", "ad-r26-매매법-봉", 6, "닫힌 거래 5건마다, 최근 26주 순위표에서 주변 평균 1등 설정으로 바꿈 (코인 모두 함께)"],
  ["자동 · 5거래마다(4주)", "ad-r4-매매법-봉", 6, "같은 방식인데 최근 4주만 봄"],
  ["자동 · 코인별(26주)", "ad-r26c-매매법-봉", 6, "같은 방식인데 코인마다 그 코인의 거래로 따로 1등을 고름"],
  ["자동 · 매주", "ad-wk-매매법-봉", 6, "매주 월요일 09:00(한국 시간), 최근 26주 1등 설정으로 바꿈"],
  ["친구 규칙", "fr-매매법-봉", 6, "매주 월요일, 코인·배수마다 지난 26주에 돈을 번 (설정 × 청산) 가운데 낙폭이 가장 작은 것을 일주일 돌림"],
  ["동전 던지기", "cf-15m, cf-30m", 2, "아무 봉에서 아무 방향으로 들어가고 사다리로 나감: 운과 비교하는 기준"],
  ["비공개 매매법", "pv-…", "서버에 따라", "서버에만 있는 매매법 (공개 저장소에 없음). 같은 배수 4줄·같은 진입 검사, 판정은 같은 봉 동전 던지기와 비교"],
];

export async function mount(el, ctx) {
  ctx.setTitle("어떻게 돌아가나");
  const exitCard = ui.card({plate: "청산"});
  const setBox = h("div", {class: "stack tight"}), exitBox = h("div", {class: "stack tight"}), ruleBox = h("div", {class: "grid2"});
  const stopBox = h("div");
  el.append(ui.screenHead("어떻게 돌아가나", "데모 랩이 하는 일을 짧게"),
    ui.card({hero: true, plate: "한 줄로"},
      h("p", {class: "dl-lead"}, "5년 연구의 매매법 3개를 ", h("em", null, "모든 설정"), "으로 동시에 돌려 실시간 순위를 매기고, 48개 연습 계좌로 \"어떤 고르는 방법이 실제로 통하나\"를 봅니다."),
      h("p", {class: "dl-lead"}, h("b", null, "주문은 넣지 않습니다."), " 바이낸스 공개 시세만 읽고, 거래소 키도 없습니다. 모든 돈은 가상입니다.")),
    h("div", {class: "grid2"},
      ui.card({plate: "무엇을 돌리나"}, h("ul", {class: "dl-ul"},
        h("li", null, "매매법 3개: S2 (", STRAT_KO.S2, "), N02 (", STRAT_KO.N02, "), N04 (", STRAT_KO.N04, ")."),
        h("li", null, "설정은 5년 연구와 같은 격자: S2 343개, N02 735개, N04 588개 (모두 1,666개)."),
        h("li", null, "코인 7개 (BTC ETH SOL DOGE LTC BCH XRP), 봉 2개 (15분, 30분). 30분봉은 15분봉을 합쳐 만듭니다."),
        h("li", null, "신호가 난 봉이 닫히는 순간(다음 15분봉 시작)에 들어갑니다."),
        h("li", null, "15분마다 새 봉을 받아 모든 설정의 신호·거래를 계산하고 순위표와 계좌를 새로 씁니다."))),
      ui.card({plate: "비용"}, h("ul", {class: "dl-ul"},
        h("li", null, "수수료 0.05% + 슬리피지 0.02%를 들어갈 때와 나갈 때 각각 뺍니다."),
        h("li", null, "순위표: 펀딩을 8시간마다 0.01%로 셉니다 (5년 연구와 같게)."),
        h("li", null, "계좌: 바이낸스의 실제 펀딩을 씁니다."),
        h("li", null, "R = 손절 폭을 1로 본 손익. +0.1R이면 거래마다 손절 폭의 10%를 번 셈입니다.")))),
    exitCard,
    ui.card({plate: "계좌", sub: "기본 48개 + 비공개 매매법 · 계좌마다 배수 4줄 (20 · 30 · 40 · 50배), 줄마다 $1,000"},
      ui.table([
        {label: "종류", l: true, get: (r) => h("b", null, r[0])},
        {label: "이름", l: true, get: (r) => h("span", {class: "mono muted"}, r[1])},
        {label: "개수", get: (r) => String(r[2])},
        {label: "규칙", l: true, cls: "dl-wrap", get: (r) => r[3]},
      ], ACCOUNTS),
      setBox,
      h("ul", {class: "dl-ul"},
        h("li", null, "매매법 3개 × 봉 2개 = 6쌍. 계좌 이름의 매매법은 S2 / N02 / N04, 봉은 15m / 30m."),
        h("li", null, "증거금 = 지갑의 배수% (20배면 지갑의 20%), 코인마다 포지션 하나."),
        h("li", null, "규칙봇과 같은 진입 검사: 손절이 강제청산 가격보다 안쪽이어야 하고, 거래소 최대 배수를 넘지 않아야 합니다. 못 넘으면 건너뜁니다."),
        h("li", null, "잔고가 $100(10%) 아래로 떨어지면 그 줄은 파산으로 멈춥니다."))),
    ui.card({plate: "순위표 읽기"}, h("ul", {class: "dl-ul"},
      h("li", null, "기간 3개: 실시간 (실시간 시작부터), 최근 26주 (처음에 과거 자료로 채움), 최근 4주."),
      h("li", null, "점수 = 주변 평균: 그 설정과 바로 옆 설정들의 평균 R을 평균한 값. 한 설정만 운 좋게 튀는 것을 걸러 냅니다."),
      h("li", null, "운 기준선: 설정 수만큼 무작위로 들어가는 선수를 세웠을 때, 그 1등이 낼 법한 평균 R의 95% 값. 이 선 위라야 운이 아닐 가능성이 큽니다."),
      h("li", null, "흔들림: 신호 뒤 3봉 안에 반대 신호가 나온 비율. 높으면 시끄러운 설정입니다."))),
    h("h2", {class: "dl-h2"}, "판정 기준 두 가지"), ruleBox,
    ui.note("통과하기 전까지는 \"실전 금지\"입니다. 판정 화면에서 계좌·배수마다 어떤 항목을 넘었는지 볼 수 있습니다."),
    h("div", {class: "grid3"},
      ui.card({plate: "확인 기간", sub: "통과한 뒤 한 번 더"}, h("ul", {class: "dl-ul"},
        h("li", null, "줄이 200개가 넘으면, 실력이 없어도 몇 줄은 운으로 기준을 넘습니다. 그래서 처음 넘은 줄은 그때부터 다시 4주를 봅니다."),
        h("li", null, "그 4주(거래 20건 이상, 길어도 8주) 동안 새로 들어간 거래만 셉니다: 평균 R > 0, 손익 +, 낙폭 30% 미만, 파산·강제청산 없음."),
        h("li", null, "모두 넘으면 \"실전 후보\", 못 넘으면 \"확인 실패\"입니다. 실패한 줄도 다시 통과하면 새로 확인합니다."),
        h("li", null, "실전 후보가 나와도 실제 돈을 쓸지는 두 분이 정합니다."))),
      ui.card({plate: "정지 규칙", sub: "실제 돈에 쓸 멈춤 장치"}, stopBox),
      ui.card({plate: "12/31 목표", sub: "홈 맨 위"}, h("ul", {class: "dl-ul"},
        h("li", null, "단계 다섯: 설치 → 데모 진행 → 우리 기준 통과 → 확인 기간 → 실전 후보."),
        h("li", null, "홈에는 남은 날, 지금 단계, 그리고 기준에 가장 가까운 줄과 그 줄이 아직 못 넘은 항목이 나옵니다."),
        h("li", null, "목표는 12/31 자정(한국 시간)까지 실전 후보가 나오는지 보는 것입니다.")))),
    h("h2", {class: "dl-h2"}, "화면 안내 (새로 생긴 것)"),
    h("div", {class: "grid2 dl-guide"}, GUIDE.map(([id, name, items]) => ui.card({plate: name,
      acts: id ? h("a", {class: "btn-line", href: `#/${id}`}, "열기") : null}, h("ul", {class: "dl-ul"}, items.map((x) => h("li", null, x)))))),
    h("div", {class: "grid2"},
      ui.card({plate: "관점 기록장"}, h("ul", {class: "dl-ul"},
        h("li", null, "두 분이 데모 랩 텔레그램 방에 관점을 한 줄로 적으면 (예: ", h("span", {class: "mono"}, "관점 BTC 숏 A 84750-84840 손절 85600"),
          ") 봇이 받아 적고 시세를 따라갑니다."),
        h("li", null, "4시간 · 24시간 · 48시간 뒤 방향이 맞았는지, 구간에 닿았는지, 그리고 \"구간 바로 진입\"과 \"15분 종가 확인 진입\" 두 방식으로 따라 했으면 몇 R이었는지 셉니다."),
        h("li", null, "끝난 관점이 30개가 되기 전에는 \"표본 부족\"입니다. 자세한 것은 관점 기록 화면에 있습니다."))),
      ui.card({plate: "주문은 없습니다"}, h("ul", {class: "dl-ul"},
        h("li", null, "주문 코드도, 거래소 키도 없습니다. 바이낸스 공개 시세(fapi.binance.com)만 읽습니다."),
        h("li", null, "실전에 쓰려면 판정을 통과한 뒤에도 두 분이 따로 정합니다."))),
      ui.card({plate: "규칙봇과 다른 점"}, h("ul", {class: "dl-ul"},
        h("li", null, "완전히 따로 돕니다: 코드 사본, 사용자, 데이터베이스, 서비스, 텔레그램 방, 대시보드(8090 포트)가 모두 다릅니다."),
        h("li", null, "규칙봇의 파일(/var/lib/paperbot, /etc/paperbot)은 읽지도 쓰지도 않습니다."),
        h("li", null, "규칙봇은 정해 둔 매매법들을 모의로 돌립니다. 데모 랩은 설정 고르는 방법 자체를 시험합니다."),
        h("li", null, "이 화면 위쪽의 \"데모 랩\" 표시로 구분하세요.")))));

  exitCard.append(exitBox);
  paintExits(exitBox, null, exitCard);
  paintRules(ruleBox, null);
  paintStops(stopBox, null);
  try {
    const [grid, judge] = await Promise.all([ctx.api("/api/grid"), ctx.api("/api/judge").catch(() => null)]);
    paintExits(exitBox, grid, exitCard);
    paintSettings(setBox, grid);
    paintRules(ruleBox, judge);
    paintStops(stopBox, judge);
  } catch (e) { /* the static words stay */ }
}

const STOP_DEFAULT = ["계좌 −20%: 새 진입 영구 정지", "하루 −5%: 그날 새 진입 정지", "5연패: 24시간 새 진입 쉼"];
function paintStops(box, judge) {
  const items = judge && !isMissing(judge) && Array.isArray(judge.stop_rules_ko) && judge.stop_rules_ko.length ? judge.stop_rules_ko : STOP_DEFAULT;
  put(box, h("ol", {class: "dl-rules"}, items.map((x) => h("li", null, x))),
    h("ul", {class: "dl-ul"},
      h("li", null, "모든 줄을 한 번 더, 이 규칙을 걸고 돌립니다 (진입·크기는 같고, 규칙은 새 진입만 막음)."),
      h("li", null, "계좌·판정·비교 화면의 \"정지 규칙 적용 시\"가 그 결과입니다. 덜 잃었는지, 번 것을 놓쳤는지 봅니다.")));
}

// one card per new screen: [route, name, plain words]
const GUIDE = [
  ["trades", "거래 차트", ["계좌나 거래 기록에서 거래 한 줄을 누르면 열립니다.",
    "그 코인의 실제 봉 위에 들어간 곳·손절·(고정 익절이면) 목표·나간 곳을 그립니다. 들어가기 3일 전부터 나온 뒤 1일까지 보입니다.",
    "옆에는 진입가, 손절, 이유, R, 배수마다 손익, 실제 비용, 그때 시장이 나옵니다."]],
  ["regime", "시장 국면", ["코인마다 지금 상승 추세·하락 추세·횡보인지, 변동이 큰지 작은지, 언제부터인지.",
    "아래 띠는 지난 기간 국면이 바뀐 흐름입니다.",
    "국면별 성적: 같은 계좌가 상승장·하락장·횡보장에서 각각 얼마나 벌었나 (어떤 장에서만 되는 방법인지 보입니다)."]],
  ["costs", "실제 비용", ["봇은 주문 한 번에 2bp(0.02%) 불리하게 체결된다고 가정합니다.",
    "실제 바이낸스 호가창을 15분마다 읽어, 주문 크기별로 정말 얼마가 들었을지 잽니다. 크기가 클수록 비쌉니다.",
    "줄마다 그 차이를 넣은 손익, 그리고 지정가가 \"닿기만\" 해서 체결이 의심스러운 거래도 봅니다."]],
  ["compare", "비교", ["계좌 2~4개를 고르고 배수 하나를 고르면, 잔고 흐름을 한 차트에 겹쳐 그립니다.",
    "아래 표에 손익, 거래, 승률, 평균 R, 낙폭, 정지 규칙 적용 시 손익, 확인 기간 상태가 나란히 나옵니다.",
    "주소를 저장해 두면 같은 비교를 다시 열 수 있습니다."]],
  ["map", "설정 지도", ["매매법의 설정 두 개(예: ST 기간 × ST 배수)를 가로·세로로 놓고, 칸마다 성적을 색으로 칠합니다.",
    "나머지 설정은 평균을 내거나 값을 고정합니다. 회색 칸은 거래가 너무 적어 믿기 어려운 칸입니다.",
    "한 칸만 튀는 곳보다 넓게 좋은 곳이 운이 아닐 가능성이 큽니다."]],
  ["coins", "코인별", ["코인 하나를 고르면, 모든 계좌·배수가 그 코인에서 거래 몇 번에 얼마를 벌고 잃었는지 줄 세웁니다.",
    "위 표는 일곱 코인을 한눈에 비교합니다.",
    "계좌 파일이 최근 600건만 남겨서, 거래가 많은 계좌는 † 표시가 붙고 그 날짜 뒤만 셉니다."]],
  ["review", "주간 회의록", ["한 주(월요일 0시~일요일 24시)를 숫자로 정리한 회의록입니다. 사람이 아니라 코드가 씁니다.",
    "맨 위에 두 분이 정할 것, 그 아래 요약 문장, 잘 된 줄·안 된 줄, 판정 변화, 정지 규칙, 실제 비용, 시장이 나옵니다.",
    "진행 중인 주는 지금까지의 숫자입니다. 지난주 회의록은 월요일 09:00에 텔레그램으로도 갑니다."]],
  ["telegram", "알림 기록", ["데모 랩 텔레그램 방에 보낸 글을 보낸 그대로 모아 둡니다 (최근 300개).",
    "종류(거래 알림, 하루 요약, 경고 …)와 상태(보냄, 보낼 차례, 실패)로 거를 수 있습니다."]],
  ["status", "서버 상태의 새 카드", ["서버 같이 쓰기: 규칙봇과 같은 서버라서, 남은 메모리와 부하, 규칙봇 서비스 상태를 봅니다. \"여유가 줄었음\"이면 화면을 개발자에게 보내 주세요.",
    "백업: 매일 새벽 다시 만들 수 없는 기록만 텔레그램으로 보냅니다. 바깥 감시: 10분마다 엔진·순위표·백업을 확인합니다.",
    "살아 있음 신호: 서버가 통째로 멈추면 바깥 서비스(healthchecks.io)가 두 분께 알립니다."]],
];

function paintExits(box, grid, card) {
  const exits = grid ? grid.exits : null;
  const half = exits ? exits.find((x) => x.name === "half1R_be_1.5R") : null;
  if (card && exits) { const pl = card.querySelector(".plate"); if (pl) pl.textContent = `청산 ${exits.length}가지`; }
  put(box,
    h("p", null, "0번은 규칙봇과 같은 ", h("b", null, "사다리"), ": 2 ATR 손절로 시작해 이익이 나면 손절을 계단처럼 올립니다. 1~12번은 고정 익절 × 고정 손절입니다: 익절 1 · 1.5 · 2 · 3R × 손절 1.5 · 2 · 3 ATR."),
    half ? h("p", null, `${half.i}번 `, h("b", null, "반익반본"), ": 2 ATR 손절, 1R에서 절반 익절하고 손절을 본전으로 옮긴 뒤 나머지는 1.5R에서 익절합니다.") : null,
    exits ? h("div", {class: "row wrap dl-pills"}, exits.map((x) => h("span", {class: "pp"}, `${x.i}. ${x.ko}`))) : null);
}

function paintSettings(box, grid) {
  if (!grid) return;
  put(box, h("p", {class: "dl-fk2"}, "고정 계좌가 쓰는 값"), ui.table([
    {label: "매매법", l: true, get: (s) => h("b", null, s.short)},
    {label: "기본값", l: true, get: (s) => h("span", {class: "mono"}, s.default || "—")},
    {label: "친구 값", l: true, get: (s) => h("span", {class: "mono"}, s.friend || "없음")},
    {label: "5년 1등 (15분 / 30분)", l: true, get: (s) => h("span", {class: "mono"}, `${s.pick["15m"]} / ${s.pick["30m"]}`)},
  ], grid.strategies, {cls: "dl-sets"}));
}

function paintRules(box, judge) {
  const rk = judge && !isMissing(judge) ? judge.rules_ko || {} : {};
  const list = (items, fallback) => (items && items.length ? h("ol", {class: "dl-rules"}, items.map((x) => h("li", null, x))) : ui.note(fallback));
  put(box,
    ui.card({plate: "우리 기준"}, h("p", null, "실시간 거래만으로 봅니다. 아래를 모두 넘어야 통과입니다."),
      list(rk.ours, "판정 자료가 나오면 기준 문구가 여기 나옵니다.")),
    ui.card({plate: "친구 기준"}, h("p", null, "친구 방식: 지난 26주에 돈을 벌면서 낙폭이 가장 작은 설정을 일주일 돌려 봅니다."),
      list(rk.friend, "판정 자료가 나오면 기준 문구가 여기 나옵니다.")),
  );
}
