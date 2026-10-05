// 매매법 (builder C): what each rule says, in plain Korean for the owners. The server sends rule text only for the 36
// (their chart view's condition names, /api/strategy/<name>); for the 44 DeepSeek definitions and the 5m reel it sends
// nothing yet, so the lines below were written from the pre-registrations (research/deepseek200/PREREG_DEEPSEEK200.md
// section 5, research/reel5m/PREREG_REEL5M.md section 5 and its appendix). The exact pre-registered text is in
// strategies-raw.js and shows only behind '원문 보기'. Family names follow paperbot/groups.py DS_FAMILY_KO.
// NEEDS SERVER: /api/strategies should send these (name_ko, family, rule lines, raw) so the page stops carrying them.
import {DS_FAMILY_KO, DS_NAME_KO, REEL as REEL_NAME} from "../core/names.js";

/** The 17 DeepSeek families: id, Korean name (groups.DS_FAMILY_KO), one plain line. */
export const DS_FAMILIES = [
  {id: "F1", desc: "가격은 새 고점(저점)을 찍었는데 지표가 따라가지 못하면, 힘이 빠졌다고 보고 반대로 들어갑니다."},
  {id: "F2", desc: "어제 가격으로 오늘의 지지선·저항선을 그리고, 찍었다가 돌아오는 봉에 들어갑니다."},
  {id: "F3", desc: "스윙 고점·저점을 종가로 넘는 구조 돌파와, 돌파 뒤 되돌아오는 구간을 봅니다."},
  {id: "F4", desc: "이동평균선이 차례로 정렬된 추세에서 잠깐 눌린 자리를 삽니다."},
  {id: "F5", desc: "추세가 약한 박스권(ADX 20 미만)에서 바닥 근처는 사고 천장 근처는 팝니다."},
  {id: "F6", desc: "하루 거래량 가중 평균가(VWAP)를 넘는지, 지키는지를 봅니다."},
  {id: "F7", desc: "레인지 필터 방향과 하이킨아시 봉 색이 같은 쪽을 가리킬 때 따라갑니다."},
  {id: "F8", desc: "큰 봉의 꼬리 끝에 가격이 처음 돌아올 때를 노립니다."},
  {id: "F9", desc: "세 봉 사이의 가격 빈틈(FVG)이나 오더 블록 구간에 되돌아올 때 들어갑니다."},
  {id: "F10", desc: "유동성 사냥 → 구조 전환 → 되돌림 구간 진입의 ICT 방식입니다."},
  {id: "F11", desc: "고점·저점을 살짝 깼다가 바로 돌아오는 속임수 이탈을 노립니다."},
  {id: "F12", desc: "구조가 오름 ↔ 내림으로 바뀌는 첫 돌파에 들어갑니다."},
  {id: "F13", desc: "스윙 범위의 싼 쪽에서만 사고 비싼 쪽에서만 파는 거름망을 다른 신호에 씌웁니다."},
  {id: "F14", desc: "BTC와 다른 코인이 엇갈릴 때 약한 쪽을 따라갑니다."},
  {id: "F15", desc: "아시아·런던·뉴욕 장 시간의 가격 범위와 시가를 기준으로 삼습니다."},
  {id: "F16", desc: "큰 움직임 뒤 피보나치 되돌림 선에서 원래 방향으로 들어갑니다."},
  {id: "F17", desc: "가격이 평균에서 너무 멀어지면 돌아온다고 보고 반대로 들어갑니다."},
];
for (const f of DS_FAMILIES) f.ko = DS_FAMILY_KO[f.id];            // names: core/names.js (one table for every screen)
export const FAMILY = Object.fromEntries(DS_FAMILIES.map((f) => [f.id, f]));

const fib = (p) => ({lines: ["큰 움직임(ATR 3배 이상, 30봉 안) 뒤", `${p} 되돌림 선에 처음 닿고 종가가 그 선을 지키면 원래 방향으로 진입`, "선에 닿기 전에 움직임의 끝(고점·저점)을 넘어가면 그 자리는 버림"]});

/** The 44 definitions (config.DS200_DEFS order): family, a short Korean name, two or three plain lines. */
export const DS_DEFS = {
  F1_RSI_DIV: {fam: "F1", lines: ["가격 고점은 높아졌는데 RSI(14)는 낮아지면 숏", "가격 저점은 낮아졌는데 RSI는 높아지면 롱", "두 고점(저점)은 60봉 안, 두 번째 것이 3봉 뒤 확인될 때 신호"]},
  F1_MOM_DIV: {fam: "F1", lines: ["모멘텀 = 지금 종가 − 10봉 전 종가", "가격 고점은 높아졌는데 모멘텀은 낮아지면 숏, 저점은 반대로 롱", "두 번째 고점(저점)이 3봉 뒤 확인될 때 신호"]},
  F1_PVT_DIV: {fam: "F1", lines: ["PVT = 거래량을 곱해 쌓은 가격 추세", "가격 고점은 높아졌는데 PVT는 낮아지면 숏, 저점은 반대로 롱", "두 번째 고점(저점)이 3봉 뒤 확인될 때 신호"]},
  F2_DEMARK: {fam: "F2", lines: ["어제 시가·고가·저가·종가로 오늘의 지지선과 저항선을 계산", "저가가 지지선을 찍고 종가는 위로 돌아오면 롱", "고가가 저항선을 찍고 종가는 아래로 돌아오면 숏"]},
  F3_BOS: {fam: "F3", lines: ["오름 구조에서 마지막 스윙 고점을 종가로 넘으면 롱", "내림 구조에서 마지막 스윙 저점을 종가로 깨면 숏", "돌파한 그 봉에서 바로 신호"]},
  F3_BOS_ZONE: {fam: "F3", lines: ["위로 구조 돌파가 나면 직전 스윙 저점 봉을 '수요 존'으로 표시", "50봉 안에 존에 돌아와 반전 양봉(앞 봉 고가 위, 200 EMA 위 종가)이 나오면 롱", "종가가 존 아래로 닫히면 존을 버림 · 숏은 반대"]},
  F3_HHHL: {fam: "F3", lines: ["고점이 높아지고 새 저점도 앞 저점보다 높으면 롱", "고점이 낮아지고 저점도 낮아지면 숏", "새 스윙이 확인되는 봉에서 신호"]},
  F4_PULL: {fam: "F4", lines: ["EMA 9 > 50 > 200으로 정렬된 오름세에서", "가격이 50 EMA까지 눌렸다가 같은 봉에 위로 닫히면 롱", "숏은 반대 정렬에서 50 EMA까지 반등했다 아래로 닫힐 때"]},
  F4_PULL_RSI: {fam: "F4", lines: ["20 EMA가 50 EMA 위이고 종가도 50 EMA 위일 때", "RSI(14)가 40을 아래에서 위로 넘으면 롱", "숏: 20 EMA < 50 EMA, 종가 < 50 EMA, RSI가 60을 위에서 아래로"]},
  F4_FAN: {fam: "F4", lines: ["EMA 8·13·21·34·55가 위에서부터 차례로 정렬되는 첫 봉에 롱", "반대 순서로 정렬되는 첫 봉에 숏"]},
  F5_BOX: {fam: "F5", lines: ["박스 = 직전 48봉의 최고·최저 (ADX 20 미만, 폭 ATR 3배 이상일 때만)", "박스 아래 15% 안에서 양봉이면 롱", "위 15% 안에서 음봉이면 숏, 박스 밖이면 신호 없음"]},
  F5_BOX_RSI: {fam: "F5", lines: ["같은 박스에서", "아래 15% 안이고 RSI(14) 30 미만이면 롱", "위 15% 안이고 RSI 70 초과면 숏"]},
  F5_BOX_HTF: {fam: "F5", lines: ["박스 바닥·천장 신호 중", "한 단계 위 봉(15분 → 1시간 등)도 ADX 20 미만일 때만"]},
  F6_VWAP_CROSS: {fam: "F6", lines: ["VWAP = 그날(UTC 0시부터) 거래량 가중 평균가", "종가가 아래에서 위로 넘으면 롱, 위에서 아래로 내려가면 숏", "그날 첫 봉에서는 신호 없음"]},
  F6_VWAP_FAIL: {fam: "F6", lines: ["종가가 VWAP 아래로 빠진 뒤 10봉 안에", "VWAP까지 올라왔다가 음봉으로 다시 아래에서 닫히면 숏", "롱은 반대 (위로 올라선 뒤 VWAP까지 내려왔다가 양봉으로 다시 위에서 닫힐 때)"]},
  F7_RF_TRIPLE: {fam: "F7", lines: ["레인지 필터 방향 위 + 하이킨아시 양봉 + 상위 봉 하이킨아시 양봉", "세 가지가 처음 모두 맞는 봉에 롱", "모두 아래를 가리키면 숏"]},
  F7_RF_ONLY: {fam: "F7", lines: ["레인지 필터 방향이 아래 → 위로 바뀌는 봉에 롱", "위 → 아래로 바뀌는 봉에 숏"]},
  F8_VWICK: {fam: "F8", lines: ["몸통이 크고(봉 길이 70% 이상, ATR 1.3배 이상) 양봉이면 그 저가를 표시", "50봉 안에 처음 그 저가에 닿고 종가가 위에 남으면 롱", "음봉이면 고가로 반대 (숏)"]},
  F9_FVG: {fam: "F9", lines: ["세 봉 사이에 생긴 가격 빈틈(갭, ATR 절반 이상)을 표시", "50봉 안에 처음 갭에 닿고 종가가 갭 절반 위면 롱", "아래 방향 갭은 반대로 숏"]},
  F9_IFVG: {fam: "F9", lines: ["위 방향 갭이 종가로 깨지면 그 갭을 저항으로 바꿈", "다시 올라와 닿고 종가가 갭 절반 아래면 숏", "아래 방향 갭이 뚫리면 반대로 롱"]},
  F9_OB: {fam: "F9", lines: ["음봉 다음에 그 고가를 크게 넘는 상승(빈틈을 남김)이 나오면 그 음봉을 구간으로 표시", "50봉 안에 처음 닿고 종가가 구간 절반 위면 롱", "숏은 반대"]},
  F9_BREAKER: {fam: "F9", lines: ["오더 블록이 종가로 뚫리면 방향을 뒤집어 표시", "되돌아와 닿고 종가가 절반 아래면 숏", "아래 방향 블록이 뚫리면 반대로 롱"]},
  F10_M2022: {fam: "F10", lines: ["① 스윙 저점을 찔렀다 회복 (유동성 사냥)", "② 20봉 안에 큰 몸통으로 구조 전환", "③ 그때 생긴 빈틈(FVG)에 되돌아오면 롱 · 숏은 반대"]},
  F10_OTE: {fam: "F10", lines: ["큰 움직임(ATR 3배 이상) 뒤 62~79% 되돌림 구간에 닿고", "종가가 79% 선을 지키면 원래 방향으로 진입"]},
  F11_TSOUP: {fam: "F11", lines: ["20봉 최저가(4봉 이상 지난 것)를 새로 깨고", "같은 봉 종가가 그 위로 돌아오면 롱 (속임수 이탈)", "고가 쪽은 반대로 숏"]},
  F11_RAID: {fam: "F11", lines: ["마지막 스윙 저점을 저가로 처음 깨고 종가는 위로 돌아오면 롱", "스윙 고점을 찔렀다 종가가 아래로 돌아오면 숏"]},
  F11_PO3: {fam: "F11", lines: ["UTC 0~8시 범위를 만든 뒤 (축적)", "8~20시에 한쪽 끝만 넘었다가 (조작)", "3봉 안에 종가가 범위 안으로 돌아오면 반대 방향으로 진입 (분배), 하루 1번"]},
  F12_MSS: {fam: "F12", lines: ["내림 구조에서 스윙 고점을 종가로 넘으면 롱 (전환)", "오름 구조에서 스윙 저점을 종가로 깨면 숏"]},
  F12_MSS_DISP: {fam: "F12", lines: ["구조 전환 신호 중", "돌파 봉 몸통이 ATR 1.2배 이상일 때만"]},
  F13_FVG_PD: {fam: "F13", lines: ["FVG 되돌림 신호 중", "롱은 스윙 범위 아래 절반(싼 쪽), 숏은 위 절반(비싼 쪽)에서만"]},
  F13_RAID_PD: {fam: "F13", lines: ["유동성 레이드 신호 중", "롱은 스윙 범위 아래 절반, 숏은 위 절반에서만"]},
  F14_SMT: {fam: "F14", lines: ["BTC는 20봉 고가를 새로 넘었는데 이 코인은 못 넘으면 이 코인 숏", "BTC는 20봉 저가를 깼는데 이 코인은 못 깨면 롱", "BTC 자신은 거래하지 않음"]},
  F15_ASIA_BRK: {fam: "F15", lines: ["뉴욕 시간 전날 20~24시(아시아장) 가격 범위", "다음 날 0~8시에 종가가 처음 범위 위면 롱, 아래면 숏 (하루 1번)", "15분·30분·1시간봉만"]},
  F15_ASIA_SWEEP: {fam: "F15", lines: ["같은 아시아 범위를", "고가가 넘었다가 종가가 안으로 돌아오면 숏, 저가 쪽은 롱 (하루 1번)", "15분·30분·1시간봉만"]},
  F15_LON_BRK: {fam: "F15", lines: ["뉴욕 시간 2~5시(런던 개장) 가격 범위", "5~12시에 종가가 처음 범위 밖으로 나간 방향으로 진입 (하루 1번)", "15분·30분·1시간봉만"]},
  F15_OPEN0930: {fam: "F15", lines: ["뉴욕 09:30 봉의 시가를 기준으로", "1시간 뒤 첫 봉 종가가 더 높으면 롱, 낮으면 숏 (하루 1번)", "15분·30분·1시간봉만"]},
  F15_OPEN0000: {fam: "F15", lines: ["뉴욕 00:00 시가를 기준으로", "1시간 뒤 첫 봉 종가가 더 높으면 롱, 낮으면 숏 (하루 1번)", "15분·30분·1시간봉만"]},
  F15_ORB: {fam: "F15", lines: ["UTC 하루 첫 두 봉의 고가·저가가 범위", "그 뒤 종가가 처음 범위 위면 롱, 아래면 숏 (하루 1번)"]},
  F16_FIB382: {fam: "F16", ...fib("38.2%")},
  F16_FIB500: {fam: "F16", ...fib("50%")},
  F16_FIB618: {fam: "F16", ...fib("61.8%")},
  F16_FIB764: {fam: "F16", ...fib("76.4%")},
  F17_Z: {fam: "F17", lines: ["종가가 20봉 평균에서 표준편차 2배 넘게 아래로 처음 내려가면 롱", "위로 2배 넘게 처음 올라가면 숏"]},
  F17_Z_HL: {fam: "F17", lines: ["Z-score 신호 중", "최근 100봉으로 잰 '평균으로 돌아오는 속도'가 빠를 때(반감기 20봉 이하)만"]},
};
for (const [k, d] of Object.entries(DS_DEFS)) d.ko = DS_NAME_KO[k];
export const DS_IDS = Object.keys(DS_DEFS);

/** Shared by all 44 (PREREG section 4), in plain words. */
export const DS_COMMON = [
  "신호는 봉이 닫힌 뒤에만 판단하고, 다음 봉 시가에 들어갑니다.",
  "같은 봉에서 롱과 숏이 같이 나면 둘 다 버립니다.",
  "스윙 고점(저점) = 앞뒤 3봉보다 높은(낮은) 봉. 3봉이 지나야 확인됩니다.",
  "구간(존)은 생긴 뒤 50봉 동안만 기다리고, 처음 닿는 봉 하나로 결정합니다.",
];

/** The exits and leverage, per group (config.V4_EXITS / v4_exits, ladder.py, levrule). */
export const EXITS = {
  house: ["손절: 진입가에서 ATR 2배 거리", "이익 잠금: 수익(ROE)이 +12%에 닿으면 +10%를 잠그고, 그 뒤 5%씩 계단처럼 올림 · 정해 둔 익절 목표는 없음"],
  reel: ["손절: 밴드 밖으로 떨어진 봉부터 신호 봉까지 가장 낮은 저가에서 ATR 0.05배 아래 (고정)",
    "익절: 직전 봉 볼린저 윗밴드에 걸어 두고 봉마다 옮김", "시간 청산: 96봉(5분봉 8시간)이 지나면 시장가로 나감 · 계단 잠금 없음"],
};
export const LEVERAGE = {
  strategy: "레버리지: 좋은 자리는 50배·증거금 50%부터, 보통 자리는 30배·30%부터 시도하고 안전 조건에 막히면 한 단계씩 내림",
  ds200: "레버리지: 언제나 '보통 자리'로 30배·증거금 30%부터 시도 (막히면 20배·20%)",
  reel: "레버리지: 언제나 '보통 자리'로 30배·증거금 30%부터 시도 (막히면 20배·20%)",
};

/** The 5m reel (REEL_H1): its own rules and exits (PREREG_REEL5M.md section 5 and its appendix). */
export const REEL = {
  id: REEL_NAME.id,
  ko: REEL_NAME.ko,
  short: REEL_NAME.short,
  desc: "인스타그램 릴스 영상의 '5분봉 단타, 선 두 개로 끝내는 법'을 그대로 따라 합니다. 사기(롱)만 합니다.",
  lines: ["밴드 가운데 선(20봉 평균)이 200봉 평균선보다 위일 때만 봅니다",
    "봉이 밴드 아래에서 끝나면 준비, 그 봉에서는 사지 않고 참습니다",
    "12봉 안에 밴드 안에서 끝나는 양봉이 나오면 다음 봉 시가에 롱",
    "그 사이 가운데 선이 200선 아래로 내려가면 준비 취소"],
  flips: "같은 청산 규칙으로 롱만 무작위로 들어가는 5분봉 동전 봇 3개가 비교 기준으로 같이 돕니다 (동전 봇 묶음에서 셈).",
};

/** Signal status words (signal_log.status, old app.js STATUS_KO). */
export const STATUS_KO = {SUBMITTED: "진입 요청", RECORD: "기록만", LATE: "늦음 (진입 안 함)", NO_PRICE: "가격 없음", NO_ATR: "ATR 없음"};

/** The kinds this screen treats as strategies (copies carry their parent's name but follow another rule). */
export const OWN_KINDS = new Set(["strategy", "ds200", "reel"]);
