// The v4 strategy names the server does not send yet (NEEDS SERVER #1: /api/board should carry accounts.data name_ko /
// family / group). One table for every screen: fmt.stratKo / fmt.acctName / fmt.idName read it, and the 매매법 rule
// lines (screens/strategies-defs.js) take their names from here. Family names follow paperbot/groups.py DS_FAMILY_KO;
// the 44 short names were written from research/deepseek200/PREREG_DEEPSEEK200.md section 5.

/** The 17 DeepSeek families. */
export const DS_FAMILY_KO = {
  F1: "다이버전스",
  F2: "디마크 피벗",
  F3: "구조 돌파·공급수요",
  F4: "EMA 눌림·정렬",
  F5: "박스권",
  F6: "VWAP",
  F7: "Range Filter 3중 일치",
  F8: "Virgin Wick POI",
  F9: "FVG·오더 블록",
  F10: "ICT 모델",
  F11: "유동성 스윕",
  F12: "구조 전환 MSS",
  F13: "프리미엄/디스카운트",
  F14: "SMT 다이버전스",
  F15: "세션 레인지·시가 편향",
  F16: "피보나치 되돌림",
  F17: "Z-score 평균회귀",
};

/** The 44 DeepSeek definitions (config.DS200_DEFS order): a short Korean name each. */
export const DS_NAME_KO = {
  F1_RSI_DIV: "RSI 다이버전스",
  F1_MOM_DIV: "모멘텀 다이버전스",
  F1_PVT_DIV: "PVT 다이버전스",
  F2_DEMARK: "디마크 지지·저항",
  F3_BOS: "구조 이어짐 돌파 (BOS)",
  F3_BOS_ZONE: "돌파 뒤 수요·공급 존",
  F3_HHHL: "고점·저점 높이기 (HH·HL)",
  F4_PULL: "EMA 정렬 눌림",
  F4_PULL_RSI: "EMA 눌림 + RSI",
  F4_FAN: "EMA 부채 정렬",
  F5_BOX: "박스 바닥·천장",
  F5_BOX_RSI: "박스 + RSI",
  F5_BOX_HTF: "박스 + 상위 봉 확인",
  F6_VWAP_CROSS: "VWAP 돌파",
  F6_VWAP_FAIL: "VWAP 복귀 실패",
  F7_RF_TRIPLE: "레인지 필터 3중 일치",
  F7_RF_ONLY: "레인지 필터만",
  F8_VWICK: "큰 봉 꼬리 끝",
  F9_FVG: "FVG 되돌림",
  F9_IFVG: "뒤집힌 FVG",
  F9_OB: "오더 블록",
  F9_BREAKER: "브레이커 블록",
  F10_M2022: "ICT 2022 모델",
  F10_OTE: "최적 진입 구간 (OTE)",
  F11_TSOUP: "터틀 수프",
  F11_RAID: "유동성 레이드",
  F11_PO3: "파워 오브 3",
  F12_MSS: "구조 전환 (MSS)",
  F12_MSS_DISP: "큰 몸통 구조 전환",
  F13_FVG_PD: "FVG + 싼·비싼 구간",
  F13_RAID_PD: "레이드 + 싼·비싼 구간",
  F14_SMT: "BTC와 엇갈림 (SMT)",
  F15_ASIA_BRK: "아시아 범위 돌파",
  F15_ASIA_SWEEP: "아시아 범위 찌르기",
  F15_LON_BRK: "런던 범위 돌파",
  F15_OPEN0930: "뉴욕 개장 1시간 방향",
  F15_OPEN0000: "뉴욕 자정 1시간 방향",
  F15_ORB: "시가 범위 돌파 (ORB)",
  F16_FIB382: "피보나치 38.2% 되돌림",
  F16_FIB500: "피보나치 50% 되돌림",
  F16_FIB618: "피보나치 61.8% 되돌림",
  F16_FIB764: "피보나치 76.4% 되돌림",
  F17_Z: "Z-score 평균회귀",
  F17_Z_HL: "Z-score + 되돌림 속도",
};

/** The 5m reel (config.REEL_NAME). */
export const REEL = {id: "REEL_H1", short: "릴스 5분 단타", ko: "릴스 5분 단타 (볼린저 20·2 + 200선)"};

/** "F3" for "F3_BOS" (the id prefix is the family), else null. */
export const dsFamilyOf = (code) => { const f = String(code ?? "").split("_")[0]; return DS_FAMILY_KO[f] ? f : null; };
