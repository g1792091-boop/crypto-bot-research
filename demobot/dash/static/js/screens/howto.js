// #/howto 어떻게 돌아가나: a plain Korean explanation of the demo lab (demobot/CONTRACT.md): what runs, the 48
// accounts, the exits, the costs, the two judgment rules, that it never places orders, how it differs from the rule bot.
// The settings' numbers come from /api/grid and the rules' words from /api/judge when they are there.
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
];

export async function mount(el, ctx) {
  ctx.setTitle("어떻게 돌아가나");
  const setBox = h("div", {class: "stack tight"}), exitBox = h("div", {class: "stack tight"}), ruleBox = h("div", {class: "grid2"});
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
    ui.card({plate: "청산 13가지"}, exitBox),
    ui.card({plate: "계좌 48개", sub: "계좌마다 배수 4줄 (20 · 30 · 40 · 50배), 줄마다 $1,000"},
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
    h("div", {class: "grid2"},
      ui.card({plate: "주문은 없습니다"}, h("ul", {class: "dl-ul"},
        h("li", null, "주문 코드도, 거래소 키도 없습니다. 바이낸스 공개 시세(fapi.binance.com)만 읽습니다."),
        h("li", null, "실전에 쓰려면 판정을 통과한 뒤에도 두 분이 따로 정합니다."))),
      ui.card({plate: "규칙봇과 다른 점"}, h("ul", {class: "dl-ul"},
        h("li", null, "완전히 따로 돕니다: 코드 사본, 사용자, 데이터베이스, 서비스, 텔레그램 방, 대시보드(8090 포트)가 모두 다릅니다."),
        h("li", null, "규칙봇의 파일(/var/lib/paperbot, /etc/paperbot)은 읽지도 쓰지도 않습니다."),
        h("li", null, "규칙봇은 정해 둔 매매법들을 모의로 돌립니다. 데모 랩은 설정 고르는 방법 자체를 시험합니다."),
        h("li", null, "이 화면 위쪽의 \"데모 랩\" 표시로 구분하세요.")))));

  paintExits(exitBox, null);
  paintRules(ruleBox, null);
  try {
    const [grid, judge] = await Promise.all([ctx.api("/api/grid"), ctx.api("/api/judge").catch(() => null)]);
    paintExits(exitBox, grid);
    paintSettings(setBox, grid);
    paintRules(ruleBox, judge);
  } catch (e) { /* the static words stay */ }
}

function paintExits(box, grid) {
  const exits = grid ? grid.exits : null;
  put(box,
    h("p", null, "0번은 규칙봇과 같은 ", h("b", null, "사다리"), ": 2 ATR 손절로 시작해 이익이 나면 손절을 계단처럼 올립니다. 나머지 12개는 고정 익절 × 고정 손절입니다: 익절 1 · 1.5 · 2 · 3R × 손절 1.5 · 2 · 3 ATR."),
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
