// #/howto 읽는 법: what the 후보 리그 is, its five accounts per pick, how to read every number, the checks and their dates
// (WATCH_PREREG), the pick characters, what each screen shows, and the real-money rule. Static text (and the dates from
// the snapshot when it is there).
import {h} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {ROLES, ROLE_KO, ROLE_DESC, STYLE_KO, STYLE_DESC, lineupOn, compareKo} from "../labels.js";
import {lineupGroups, GROUP_HELP} from "./versus.js";
import {DEFAULTS as DECISION} from "./decision.js";

const SCREENS = [
  ["요약", "다음 점검까지 며칠, 묶음 두 개(기존 36 · 딥시크)의 지금, 후보 합계 잔고, 상위 · 하위 5, 최근 체결"],
  ["점검 진행", "11/11 · 12/11 · 1/11 기준을 오늘 숫자에 대어 본 것 (참고), 후보마다 기준, 운 vs 실력, 경고등, 후보마다 속도 · 연패, 매매법별 묶음"],
  ["순위표", "후보 38개를 줄 세운 표. 카드를 누르면 1/4 · 청산만 · 기본값 · 동전 계좌로 바뀜"],
  ["5계좌 비교", "후보마다 다섯 계좌를 한 줄에. 좋아진 게 숫자 덕인지 청산 덕인지, 운인지"],
  ["커스텀값", "후보마다 기본값에서 바뀐 숫자(한글 이름, 기본 → 커스텀, 배수), 익절 · 손절 · 배수 요약, 어디서 왔나, 5년 시험 속도, 성격"],
  ["익절·손절·배수", "후보마다 익절 · 손절을 어떻게 잡았나, 본전 승률, 배수(레버리지)와 증거금 규칙, 지금 코인별로 몇 배가 되나, 계좌 5개가 다른 점"],
  ["매매법", "16개 매매법의 진입 방식(롱 · 숏), 조절 숫자, 후보들, 묶음 성적"],
  ["흐름", "묶음 레이스(시간에 따른 후보 · 청산만 · 기본값 · 동전의 잔고 중앙값과 동전 계좌 가운데 50% 띠), 주마다 거래 수 · 승률 · 합계"],
  ["터미널", "거래소 화면처럼: 코인 6개, 캔들 차트에 고른 계좌의 진입 · 청산, 열린 포지션, 최근 체결"],
  ["진입 차트", "매매법마다 따로: 후보 하나에 차트 하나, 들어간 자리 ▲▼ · 나온 자리 ● · 진입가 · 열린 포지션의 손절 · 익절. ◀ ▶로 다른 진입"],
  ["포지션 · 체결 기록", "지금 열린 포지션 전부, 최근 닫힌 거래 300건"],
  ["서버 상태", "엔진이 어디까지 처리했나, 늦음, 서버 부하 · 메모리, 시세 연결"],
];

/** 화면 안내 of the owner-exit league: the screens as this league has them (the 판정 screen, the 메인 vs 대조 set, 계좌 비교). */
const SCREENS_OWNER = () => [
  ["요약", "계좌 종류 묶음, 판정까지 남은 날, 후보 합계 잔고, 상위 · 하위 5, 최근 체결"],
  ["판정", "미리 정한 규칙으로 승자 가리기: 같은 신호 짝 비교 · 우연 보정 · 14일째는 숫자만 보고 28일째에 한 번 판정, 하나도 통과 못 하면 ‘우위 없음’"],
  ["메인 vs 대조", "새 청산 방법(메인)이 원래 방식(대조)보다 나은지: 승률 · 손익비 · 거래당 순수익 · 낙폭 · 동전 던지기 확인 (참고)"],
  ["짝 비교", "같은 신호에서 메인 계좌와 대조 계좌의 결과를 한 쌍씩: 빠른 손절이 낫고 못했던 횟수"],
  ["청산 이유", "거래가 어떻게 끝났나 (손절 · 계단 잠금 · 규칙 청산 · 익절 · 강제청산)와 이유별 평균"],
  ["목표 진척도", "두 분의 목표(승률 · 하루 진입 수 · 거래당 순수익 · 한 달 환산 수익률 · 낙폭)가 지금 어디까지 왔나"],
  ["구조 기준", "매매법마다 ‘구조가 무너졌다’고 보는 조건: 빠른 손절 · 스위칭이 나가는 때"],
  ["발동 기록", "빠른 손절 · 손절 좁힘 · 스위칭이 일어날 때마다 쉬운 문장으로"],
  [compareKo(), "후보마다 계좌 종류별 잔고 수익률 · 거래 수 · 승률 · 보유 시간을 한 줄에 (참고)"],
  ["순위표", "후보와 모든 계좌를 줄 세운 표. 카드를 누르면 계좌 종류별로 바뀜"],
  ["점검 진행", "경고등(백테스트 예상 범위 아래인지) · 후보마다 속도 · 연패 (참고). 승자를 가리는 곳은 판정 화면"],
  ["커스텀값", "후보마다 기본값에서 바뀐 숫자(한글 이름, 기본 → 커스텀, 배수), 익절 · 손절 · 배수 요약, 어디서 왔나, 5년 시험 속도, 성격"],
  ["익절·손절·배수", "후보마다 익절 · 손절을 어떻게 잡았나, 본전 승률, 배수(레버리지)와 증거금 규칙, 지금 코인별로 몇 배가 되나, 계좌 종류가 다른 점"],
  ["매매법", "매매법의 진입 방식(롱 · 숏), 조절 숫자, 후보들, 묶음 성적"],
  ["흐름", "계좌 종류마다 시간에 따른 잔고 중앙값, 주마다 거래 수 · 승률 · 합계"],
  ["터미널", "거래소 화면처럼: 코인 6개, 캔들 차트에 고른 계좌의 진입 · 청산, 열린 포지션, 최근 체결"],
  ["진입 차트", "매매법마다 따로: 후보 하나에 차트 하나, 들어간 자리 ▲▼ · 나온 자리 ● · 진입가 · 열린 포지션의 손절 · 익절. ◀ ▶로 다른 진입"],
  ["포지션 · 체결 기록", "지금 열린 포지션 전부, 최근 닫힌 거래 300건"],
  ["서버 상태", "엔진이 어디까지 처리했나, 늦음, 서버 부하 · 메모리, 시세 연결"],
];

/** An entry whose meaning names the start wallet: [2] is a getter, read when the page is built, so it follows the snapshot's equity0. */
const lazy = (term, aliases, meaning) => { const e = [term, aliases, ""]; Object.defineProperty(e, 2, {get: meaning, enumerable: true}); return e; };

/** 용어 사전 (the rule bot's v4 FAQ glossary, in this league's words): [term, aliases for ?q=, meaning]. */
export const GLOSSARY = [
  ["ATR", ["ATR14", "평균 움직임"], "봉 하나가 보통 얼마나 움직이나: 최근 14개 봉의 (고가 − 저가, 갭 포함) 평균. 15분봉 ATR과 4시간봉 ATR은 크기가 다릅니다. 손절 ‘4 ATR’ = 그 봉 ATR의 4배 거리."],
  ["R", ["1R", "3R"], "진입가에서 처음 손절선까지의 거리 (그 거래의 위험 한 단위). ‘익절 3R’ = 손절 거리의 3배 가면 익절. 손익을 R로 세면 손절에 닿으면 −1R, 3R 익절이면 +3R."],
  ["익절 리밋", ["지정가 익절", "고정 익절"], "들어갈 때 미리 걸어 두는 지정가 익절 주문. 그 가격에 닿으면 바로 익절합니다 (지정가라 수수료가 0.02%로 쌈). 후보마다 어떤 익절을 쓰는지는 ‘익절·손절·배수’ 화면에 있습니다."],
  lazy("계단 잠금", ["잠금", "LOCK"], () => (lineupOn()
    ? "정해 둔 익절 대신, 수익이 어느 선에 닿으면 손절선을 올려 잠그고 5%씩 따라 올리는 방식. 규칙봇은 증거금 대비 순수익(수수료 뺀 ROE)이 +12%가 되면 +10% 자리에 잠그고, 이 리그의 대조 · 메인 계좌는 두 분이 정한 계단(+13% → +10%, +20% → +15% …)을 씁니다."
    : "정해 둔 익절 대신, 증거금 대비 순수익(수수료 뺀 ROE)이 +12%가 되면 손절선을 +10% 자리로 올려 잠그고 5%씩 따라 올리는 방식. 규칙봇과 기본값 계좌가 씁니다.")),
  ["본전 승률", ["손익분기 승률"], "이 비율만큼 이기면 본전. 3R 익절이면 이길 때 3, 질 때 1이라 4번 중 1번(25%)이면 본전 (수수료·슬리피지를 넣으면 조금 더 높음: 손절로 끝나면 왕복 0.14%, 지정가 익절로 끝나면 0.09%)."],
  lazy("배수", ["레버리지"], () => `포지션 크기 ÷ 증거금. 30배면 증거금 ${LK.usd0(LK.EQUITY * 0.3)}로 ${LK.usd0(LK.EQUITY * 9)}어치를 잡습니다. 가격이 1% 움직이면 증거금 대비 30% 움직입니다.`),
  lazy("증거금", ["마진"], () => `그 거래에 거는 돈. 후보 리그는 잔고 × 배수% (30배면 잔고의 30%).${lineupOn() ? "" : " 1/4 계좌는 그 1/4."}`),
  ["포지션 크기", ["노셔널"], "증거금 × 배수. 수수료는 이 크기에 붙습니다: 들어갈 때 0.05%, 손절로 나올 때 0.05%, 지정가 익절로 나올 때 0.02% (손절·시장가 체결에는 슬리피지 0.02%씩 더)."],
  lazy("청산가", ["강제청산"], () => `증거금을 거의 다 잃는 가격. 거래소가 포지션을 강제로 닫습니다. 배수가 높을수록 진입가에 가깝습니다 (BTC ${LK.levLadder().has20 ? "50배 약 1.6%, 20배 약 4.6%" : "50배 약 1.6%, 30배 약 2.9%"}).`),
  lazy("좋은 자리", ["best"], () => `기존 36 매매법에서 진입 강도 점수가 높은 자리 (5년 신호의 약 22%). 50배부터 시도하고, 안 되면 ${LK.levLadder().best.slice(1).map((v) => `${v}배`).join(" → ")}${LK.levLadder().on ? "까지만" : ""}. 딥시크 매매법과 진입 강도 기준이 없는 칸은 늘 보통 자리.`),
  lazy("보통 자리", ["normal"], () => (LK.levLadder().normal.length > 1 ? "좋은 자리가 아닌 모든 진입. 30배부터 시도하고, 안 되면 20배." : `좋은 자리가 아닌 모든 진입. ${LK.levLadder().normal[0]}배만 시도합니다.`)),
  // the LTC · BCH sentence is the exchange table at the $125,000 order of a $5,000 wallet; another wallet gets the general sentence
  lazy("거래소 한도", ["배수 한도", "브래킷"], () => `거래소(바이낸스)는 주문이 클수록 허용 배수를 낮춥니다. 예: 잔고 ${LK.usd0(LK.EQUITY)}에서 50배 주문은 ${LK.usd0(LK.EQUITY * 25)}어치${LK.EQUITY === 5000
    ? "인데, 지금 거래소 표로는 이 크기에서 LTC · BCH가 40배까지만 돼서 그 두 코인은 40배부터 시도합니다"
    : "입니다. 코인마다 거래소 표가 달라서, 이 크기에서 허용 배수가 모자란 코인은 그 아래 배수부터 시도합니다"}.${lineupOn() ? "" : " 1/4 계좌는 주문이 작아 덜 걸립니다."}`),
  ["청산 검사", ["청산 여유"], "배수를 고르는 안전 검사 하나: 손절선이 청산가보다 안쪽에 있고 그 사이가 1 ATR 이상(최소 진입가의 0.2%)이어야 그 배수로 들어갑니다. 손절에 닿기 전에 강제청산되는 일을 막습니다."],
  ["손실 검사", ["손실 한도"], "배수를 고르는 안전 검사 하나: 손절에 닿았을 때 잃는 돈(수수료·슬리피지 포함)이 잔고의 15% 이하여야 그 배수로 들어갑니다."],
  lazy("손절 거리 한도", ["손절 한도"], () => `손실 검사 때문에 배수마다 쓸 수 있는 가장 넓은 손절 거리 (진입가 대비): ${LK.levLadder().stopLimits}${lineupOn() ? "" : " (1/4 계좌는 약 4배 넓음)"}. 손절이 이보다 넓으면 그 배수는 건너뜁니다.${LK.levLadder().on ? ` 이 리그에는 ${LK.levLadder().low}배 아래가 없어서, 손절이 ${LK.levLadder().low}배 한도(진입가의 약 ${LK.levLadder().stopLimitLow})보다 넓은 신호는 들어가지 않습니다. 그래서 손절이 넓은 후보(1시간봉·4시간봉, 변동이 큰 코인)는 거래가 줄 수 있습니다.` : ""}`),
  ["증거금 대비", ["ROE", "ROI"], "그 거래에 건 증거금에 대한 손익 (배수가 곱해진 값). 30배에서 가격이 1% 오르면 약 +30%."],
  lazy("한 번 평균", ["평균"], () => `닫힌 거래마다 (손익 ÷ 그 직전 지갑)의 평균.${lineupOn() ? "" : " 점검도 이 단위로 합니다."}`),
  ["펀딩비", ["펀딩"], "선물 가격을 현물에 맞추려고 8시간마다 롱·숏 사이에 주고받는 돈. 열린 포지션에만 붙습니다."],
  ["연패", ["연속 손실"], "연달아 진 횟수. 이기는 비율이 30%대인 3R 후보는 6~10번 연패가 흔합니다."],
];
/** The glossary entry of a ?q= word (its term or an alias), or null. */
export const glossaryOf = (q) => {
  const k = String(q || "").trim().toLowerCase();
  return k ? GLOSSARY.find(([t, al]) => t.toLowerCase() === k || al.some((a) => a.toLowerCase() === k)) || null : null;
};

/** How many of the picks have each character (from /api/meta, when it is loaded): "추세 따라가기 N · 섞임 N · 되돌림 · 박스 N" or null. */
function styleCounts(d) {
  const meta = LK.metaNow();
  if (!d || !meta || !meta.picks) return null;
  const n = {};
  for (const c of LK.index(d).cands) { const st = (LK.pickMeta(c.id, meta) || {}).style; if (st) n[st] = (n[st] || 0) + 1; }
  const total = Object.values(n).reduce((a, b) => a + b, 0);
  return total ? {n, total} : null;
}

/** The page of the owner-exit league (49 picks, ~26 kinds of account, the decision on day 28): the counts come from the snapshot. */
function paintOwner(el, ctx, d, want) {
  const c = LK.leagueCounts(d);
  const R = LK.road(d);
  const obs = R ? R.observe : DECISION.observe_day, dec = R ? R.decide : DECISION.decide_day;
  const when = (ms) => (ms ? ` (${fmt.mmdd(ms)})` : "");
  const sc = styleCounts(d);
  const groups = lineupGroups(d);
  const kindList = (g) => h("dl", {class: "kv kv-kinds"}, ROLES.filter((r) => groups.some((x) => x.group === g && x.kinds.some((k) => k.role === r)))
    .map((r) => h("div", null, h("dt", null, LK.roleChip(r)), h("dd", null, ROLE_DESC[r]))));
  el.append(
    ui.screenHead("읽는 법", "후보 리그를 처음 보는 분을 위한 안내"),
    ui.card({plate: "후보 리그가 뭔가요"},
      h("p", null, `5년 백테스트에서 고른 커스텀값 후보 ${fmt.int(c.picks)}개(매매법 ${fmt.int(c.strategies)}개)를, 백테스트에 없던 앞으로의 시세로 종이 매매해 시험합니다. 돈이 된다는 증거가 아니라 모의로 지켜보려는 후보입니다.`),
      h("p", null, `이번 리그는 ‘익절 · 손절을 어떻게 하면 나은가’를 보려고, 후보마다 청산 방법이 다른 계좌 ${fmt.int(c.kinds)}가지 종류를 나란히 돌립니다 (후보에 따라 없는 종류가 있어 계좌는 모두 ${fmt.int(c.accounts)}개).`),
      h("p", null, `규칙봇과 같은 엔진 · 같은 크기 규칙(${LK.startUsd()} 시작, ${LK.levLadder().slash}, 수수료 · 슬리피지 · 펀딩 · 강제청산 · 파산 포함)으로 계산하고 주문은 넣지 않습니다. `,
        "배수와 익절 · 손절은 ", h("a", {href: "#/rules"}, "익절·손절·배수"), " 화면에 있습니다."),
      LK.levLadder().has20 ? null : h("p", null, `이 리그는 20배를 쓰지 않습니다 (규칙봇은 씀). 손절이 넓은 신호는 ${LK.levLadder().low}배에서도 안 맞으면 진입하지 않아 거래가 줄 수 있습니다.`),
      h("p", null, d && d.start_ms ? `규칙봇처럼 봇을 켠 때(설치 ${LK.startKo(d)})부터 시작했습니다: 모든 계좌가 그때 ${LK.startUsd()}이고, 거래 · 잔고 · 순위 · 날짜(시작한 날 = D+0)는 모두 그때부터입니다.`
        : `규칙봇처럼 봇을 켠 때(설치)부터 시작합니다: 모든 계좌가 그때 ${LK.startUsd()}이고, 거래 · 잔고 · 순위 · 날짜는 모두 그때부터입니다.`),
      h("p", {class: "note"}, "목록은 시작 전에 고정했습니다. 며칠, 2주 성적으로 바꾸지 않습니다. 짧은 기간 성적은 운이 큽니다.")),
    ui.card({plate: "판정은 어떻게 하나요 (미리 정함)"}, h("ul", {class: "cl-checks"},
      h("li", null, h("b", null, `${obs}일째${when(R && R.observe_ms)}`), h("span", null, " · 첫 확인: 숫자만 봅니다. 아무것도 바꾸지 않고 통과 · 실패도 말하지 않습니다.")),
      h("li", null, h("b", null, `${dec}일째${when(R && R.decide_ms)}`), h("span", null, " · 판정: 이날 이후 딱 한 번 판정합니다. ‘n일째’는 시작 시각부터 24시간씩 센 날입니다.")),
      h("li", null, h("b", null, "판정에 쓰는 비교는 4개뿐"), h("span", null, " · 빠른 손절 vs 대조, 빠른 손절 vs 동전 짝, 대조 vs 동전 짝, BTC 추세 필터가 남긴 신호 vs 버린 신호. 나머지 종류는 참고용(탐색)이라 통과 · 실패를 매기지 않습니다."))),
    h("p", null, `같은 신호로 들어간 거래를 한 쌍씩 비교하고, 4개를 함께 시험하는 것을 감안해 우연을 보정합니다. 통과하려면 쌍 ${fmt.int(DECISION.min_pairs)}개 이상 · 보정 후 p가 ${DECISION.alpha}보다 작음 · 평균 차이가 플러스 · 기간의 앞 절반과 뒤 절반 모두 플러스여야 합니다.`),
    h("p", {class: "note"}, "하나도 통과하지 못하면 ‘우위 없음’이 결론이고 새 구조는 실전에 쓰지 않습니다. 숫자를 본 뒤에 기준을 바꾸지 않습니다. ", h("a", {href: "#/decision"}, "판정 화면"), "에 규칙 전문과 지금 숫자가 있습니다.")),
    ui.card({plate: `후보마다 계좌 종류 ${fmt.int(c.kinds)}가지`}, groups.map((g) => h("div", {class: "stack tight"},
      h("h3", {class: "cl-h3"}, `${g.ko} ${fmt.int(g.kinds.length)}가지`, h("small", {class: "muted"}, ` · ${GROUP_HELP[g.group] || ""}`)),
      ui.disclosure(`${g.ko} 종류마다 자세히 보기`, kindList(g.group)))),
    h("p", {class: "note"}, `${LK.OWNER_SAME_SIGNALS} ${LK.OWNER_SAME_RULE} ${LK.OWNER_STOP_DIFF} 그래서 잔고만 나란히 보면 신호 · 손절 거리의 차이가 섞입니다. 정확한 비교는 같은 신호끼리 한 쌍씩 보는 판정 화면과 짝 비교입니다 (거래가 적으면 운).`)),
    ui.card({plate: "숫자 읽는 법"}, h("dl", {class: "kv"},
      h("div", null, h("dt", null, "한 번 평균"), h("dd", null, "닫힌 거래마다 (손익 ÷ 그 직전 지갑)의 평균. +0.10%면 거래 한 번에 지갑이 평균 0.1% 늘었다는 뜻.")),
      h("div", null, h("dt", null, "거래당 순수익"), h("dd", null, "거래 한 번이 증거금 대비 평균 얼마 남겼나 (수수료 뺀 뒤). 판정이 보는 숫자입니다.")),
      h("div", null, h("dt", null, "묶음 평균"), h("dd", null, "그 묶음 모든 계좌의 거래를 한데 모은 한 번 평균 (계좌 평균의 평균이 아님).")),
      h("div", null, h("dt", null, "잔고 · 최대 낙폭"), h("dd", null, "닫힌 거래까지의 지갑과, 가장 높았던 지갑에서 가장 많이 내려간 비율.")),
      h("div", null, h("dt", null, "증거금 대비"), h("dd", null, "그 거래에 건 증거금에 대한 손익 (레버리지가 곱해진 값).")),
      h("div", null, h("dt", null, "아직 (30번 전)"), h("dd", null, "닫힌 거래 30번 전에는 판단하지 않습니다. 몇 번은 운으로 얼마든지 좋거나 나쁠 수 있습니다.")),
      h("div", null, h("dt", null, "▲ ▼"), h("dd", null, "다른 계좌보다 높으면 ▲, 낮으면 ▼. 비교일 뿐 판정은 아닙니다.")),
      h("div", null, h("dt", null, "경고등"), h("dd", null, "기존 36 후보가 백테스트로 본 예상 범위의 하위 5%보다 낮으면 켜집니다. 20개 중 1개꼴(5%)은 운으로도 켜집니다. 알림일 뿐입니다.")))),
    ui.card({plate: "후보의 성격"}, h("dl", {class: "kv"}, Object.entries(STYLE_KO).map(([k, v]) => h("div", null, h("dt", null, LK.styleChip(k)), h("dd", null, STYLE_DESC[k])))),
      h("p", {class: "note"}, "추세 비율 = 들어간 방향이 직전 20봉 움직임과 같은 비율 (2021~2026-09, 그 후보의 숫자와 청산으로)." +
        (sc ? ` ${fmt.int(sc.total)}개 중 ${Object.entries(STYLE_KO).map(([k, v]) => `${v} ${fmt.int(sc.n[k] || 0)}`).join(" · ")}.` : ""))),
    ui.card({plate: "용어 사전", sub: "다른 화면의 밑줄 낱말을 누르면 여기로 옵니다", id: "glossary"}, h("dl", {class: "gl-list"},
      GLOSSARY.map(([t, , v]) => h("div", {id: `gl-${t}`, class: want && want[0] === t ? "on" : null}, h("dt", null, t), h("dd", null, v))))),
    ui.card({plate: "화면 안내"}, h("dl", {class: "kv"}, SCREENS_OWNER().map(([k, v]) => h("div", null, h("dt", null, k), h("dd", null, v))))),
    ui.card({plate: "실제 돈"}, h("p", null, "후보 리그는 모의 매매입니다 (가상 돈). 판정에서 통과하기 전에는 어떤 것도 실전에 쓰지 않습니다. 통과해도 모의 계좌의 28일 기록이라 실전에서 번다는 뜻은 아닙니다. 하나도 통과하지 못하면 ‘우위 없음’이 결론입니다.")));
  if (want && typeof requestAnimationFrame === "function") {
    requestAnimationFrame(() => { const t = document.getElementById(`gl-${want[0]}`); if (t && t.scrollIntoView) t.scrollIntoView({block: "center"}); });
  }
}

function paint(el, ctx) {
  const d = LK.league();
  const want = glossaryOf(((ctx && ctx.params && ctx.params.query) || {}).q);
  if (lineupOn() && d && d.accounts) { paintOwner(el, ctx, d, want); return; }
  const cps = (d && d.watch && d.watch.checkpoints) || [
    {ko: "1차 점검", date: "2026-11-11", after: "시작 후 한 달", what: "멈출지 보기"}, {ko: "2차 점검", date: "2026-12-11", after: "시작 후 두 달", what: "통과 보기"},
    {ko: "3차 점검", date: "2027-01-11", after: "시작 후 석 달", what: "2차에서 못 넘은 묶음만"}];
  el.append(
    ui.screenHead("읽는 법", "후보 리그를 처음 보는 분을 위한 안내"),
    ui.card({plate: "후보 리그가 뭔가요"},
      h("p", null, "5년 백테스트 전체 탐색에서 아깝게 떨어진 커스텀값 후보 38개(기존 36 매매법 23개 · 딥시크 15개)를, 백테스트(9월 30일까지)에 없던 앞으로의 시세로 종이 매매해 시험합니다. ",
        `규칙봇과 같은 엔진 · 같은 크기 규칙(${LK.startUsd()} 시작, ${LK.levLadder().slash}, 수수료 · 슬리피지 · 펀딩 · 강제청산 · 파산 포함)으로 계산하고 주문은 넣지 않습니다. `,
        "후보마다 익절·손절을 어떻게 잡았고 배수가 어떻게 정해지는지는 ", h("a", {href: "#/rules"}, "익절·손절·배수"), " 화면에 있습니다."),
      h("p", null, d && d.start_ms ? `규칙봇처럼 봇을 켠 때(설치 ${LK.startKo(d)})부터 시작했습니다: 모든 계좌가 그때 ${LK.startUsd()}이고, 거래 · 잔고 · 순위 · 날짜(시작한 날 = D+0)는 모두 그때부터입니다.`
        : `규칙봇처럼 봇을 켠 때(설치)부터 시작합니다: 모든 계좌가 그때 ${LK.startUsd()}이고, 거래 · 잔고 · 순위 · 날짜는 모두 그때부터입니다.`),
      h("p", {class: "note"}, "목록은 시작 전에 고정했습니다. 6일, 2주 성적으로 바꾸지 않습니다. 짧은 기간 성적은 운이 큽니다.")),
    ui.card({plate: lineupOn() ? `후보마다 계좌 ${ROLES.length}개 (청산 비교)` : "후보마다 계좌 5개"}, h("dl", {class: "kv"}, ROLES.map((r) => h("div", null, h("dt", null, LK.roleChip(r)), h("dd", null, ROLE_DESC[r])))),
      h("p", {class: "note"}, lineupOn()
        ? `모든 계좌가 같은 신호 · 같은 손절 · 같은 크기 · 같은 시세라 바로 비교됩니다. ${ROLE_KO.cand}보다 잔고가 많으면 그 청산이 이 기간에 나았던 것입니다 (거래가 적으면 운).`
        : "다섯 계좌는 같은 시세 · 같은 기간이라 바로 비교됩니다. 후보 > 청산만이면 숫자(커스텀값) 덕, 청산만 > 기본값이면 익절 · 손절 덕, 동전보다 못하면 방향을 맞힌 게 아닐 수 있습니다.")),
    ui.card({plate: "숫자 읽는 법"}, h("dl", {class: "kv"},
      h("div", null, h("dt", null, "한 번 평균"), h("dd", null, "닫힌 거래마다 (손익 ÷ 그 직전 지갑)의 평균. +0.10%면 거래 한 번에 지갑이 평균 0.1% 늘었다는 뜻. 점검도 이 단위로 합니다.")),
      h("div", null, h("dt", null, "묶음 평균"), h("dd", null, "그 묶음 모든 계좌의 거래를 한데 모은 한 번 평균 (계좌 평균의 평균이 아님).")),
      h("div", null, h("dt", null, "잔고 · 최대 낙폭"), h("dd", null, "닫힌 거래까지의 지갑과, 가장 높았던 지갑에서 가장 많이 내려간 비율.")),
      h("div", null, h("dt", null, "증거금 대비"), h("dd", null, "그 거래에 건 증거금에 대한 손익 (레버리지가 곱해진 값).")),
      h("div", null, h("dt", null, "아직 (30번 전)"), h("dd", null, "닫힌 거래 30번 전에는 판단하지 않습니다. 몇 번은 운으로 얼마든지 좋거나 나쁠 수 있습니다.")),
      h("div", null, h("dt", null, "▲ ▼"), h("dd", null, "같은 후보의 다른 계좌보다 한 번 평균이 높으면 ▲, 낮으면 ▼. 비교일 뿐 판정은 아닙니다.")),
      h("div", null, h("dt", null, "경고등"), h("dd", null, "기존 36 후보가 백테스트로 본 예상 범위의 하위 5%보다 낮으면 켜집니다. 23개 중 1개쯤은 운으로도 켜집니다. 알림일 뿐입니다.")))),
    ui.card({plate: "점검 (미리 고정)"}, h("ul", {class: "cl-checks"}, cps.map((c) => h("li", null, h("b", null, `${c.ko} ${c.date || ""}`), h("span", null, `${c.after ? ` (${c.after})` : ""} · ${c.what}`)))),
      h("p", null, "기존 36과 딥시크는 따로 점검합니다. 2차 통과 조건: 후보 평균 > 0이고 운 검사(주 단위로 섞어 2,000번 다시 뽑기) p < 0.05, 기본값보다 · 동전보다 나음, 후보 거래 300번 이상."),
      h("p", {class: "note"}, "점검 진행 화면의 ‘지금이면’은 참고입니다. 판정은 점검 날 정해 둔 계산으로 한 번 합니다.")),
    ui.card({plate: "후보의 성격"}, h("dl", {class: "kv"}, Object.entries(STYLE_KO).map(([k, v]) => h("div", null, h("dt", null, LK.styleChip(k)), h("dd", null, STYLE_DESC[k])))),
      h("p", {class: "note"}, "추세 비율 = 들어간 방향이 직전 20봉 움직임과 같은 비율 (2021~2026-09, 그 후보의 숫자와 청산으로). 38개 중 추세 따라가기 28 · 섞임 7 · 되돌림 · 박스 3.")),
    ui.card({plate: "용어 사전", sub: "다른 화면의 밑줄 낱말을 누르면 여기로 옵니다", id: "glossary"}, h("dl", {class: "gl-list"},
      GLOSSARY.map(([t, , v]) => h("div", {id: `gl-${t}`, class: want && want[0] === t ? "on" : null}, h("dt", null, t), h("dd", null, v))))),
    ui.card({plate: "화면 안내"}, h("dl", {class: "kv"}, SCREENS.map(([k, v]) => h("div", null, h("dt", null, k), h("dd", null, v))))),
    ui.card({plate: "실제 돈"}, h("p", null, "후보 리그는 모의 매매입니다 (가상 돈). 2차 점검에서 묶음이 통과하고, 그 매매법도 통과했을 때만 두 분이 실제 돈을 검토할 수 있습니다: 1/4 크기 이하, 잃어도 되는 금액, 실행기 한도 켜고, 테스트넷 연습을 마친 뒤. 2차를 두 번 못 넘은 묶음은 끝납니다.")));
  if (want && typeof requestAnimationFrame === "function") {
    requestAnimationFrame(() => { const t = document.getElementById(`gl-${want[0]}`); if (t && t.scrollIntoView) t.scrollIntoView({block: "center"}); });
  }
}

export async function mount(el, ctx) {
  const early = !LK.league();
  // the owner-exit league's 후보의 성격 counts read /api/meta: wait for it (the names fall back to nothing when it fails)
  const meta = async () => { if (lineupOn() && ctx && typeof ctx.meta === "function") { try { await ctx.meta(); } catch (e) { /* no counts */ } } };
  await meta();
  paint(el, ctx);
  // opened before the first snapshot: the start wallet (equity0) and the dates are not known yet, so paint once more when it arrives
  if (early && ctx && typeof ctx.onLeague === "function") {
    let again = true;
    ctx.onLeague(async () => { if (again && LK.league()) { again = false; await meta(); el.replaceChildren(); paint(el, ctx); } });
  }
}
