// 에이전트 방 · 회의 '근거' in plain words (review fix: "loss_cards[0].tags 같은 내부 경로가 그대로 보임"). A staff
// claim cites PACKET PATHS (paperbot/agents/prompts3/rooms_common.md: `losses.tag_stats.0.losses`,
// `board.today.trades`); the page names each one in Korean ("손실 › 태그 통계 1번 › 손실 수"), shows a value only when
// the stored item carries one, and never prints JSON. A part with no Korean name reads "세부 항목" (the raw path stays
// in a data attribute for whoever debugs, never as visible text). The claims and their own paths come from the stored
// answer (data.answer.findings / objections); a message without them lists its flat evidence.
import {h, fmt} from "../core/pb.js";

// whole packet keys (top level and the common sections inside them)
const KEY_KO = {
  losses: "손실", loss_cards: "손실 카드", recent_losses: "최근 손실", tag_stats: "태그 통계", tags: "태그", tag: "태그",
  specialist: "전담 자료", by_strategy: "봉별", by_tf: "봉별", by_timeframe: "봉별", by_coin: "코인별", by_side: "방향별",
  by_session: "시간대별", by_reason: "나간 이유별", by_definition: "정의별", board: "순위 자료", today: "오늘", trades: "거래 수",
  trials: "시험 장부", rules: "규칙", meeting: "회의 정보", code_result: "코드 계산 결과", result: "결과", periods: "기간",
  baseline: "지금 규칙", variant: "바꾼 규칙", extra_accounts: "추가 계좌", lab_accounts: "새 매매법 계좌", tf_split: "봉 비교",
  ranking: "순위 검토", market_move: "시장 급변", cost: "비용", combo: "조합", coins: "코인", learning: "배운 점",
  event: "경제지표", committee: "위원회", group_accounts: "묶음 계좌", owner_messages: "두 분 글", room_messages: "방 대화",
  this_round: "이번 회의 발언", notes: "메모", meta: "기본 정보", research_prior: "5년 연구 기록", league: "리그",
  pass_check: "판정 진행", execution: "체결", exits: "청산", groups: "묶음", checkpoint: "30일 판정", levrule: "레버리지 규칙",
  hypotheses: "가설", scorecard: "가설 채점", lessons: "배운 점", profile: "5년 프로필", performance: "성적",
  open_positions: "열린 포지션", signals: "신호", wins: "이긴 거래", win_rate: "승률", mean_roe: "거래당 평균 ROE",
  roe: "ROE", pnl: "손익", net_pnl: "순손익", net_pnl_24h: "24시간 순손익", wallet: "잔고", median_wallet: "잔고 중앙값",
  leverage: "배수", margin: "증거금", fees: "수수료", fees_total: "수수료 합계", funding: "펀딩", funding_total: "펀딩 합계",
  exit_reason: "나간 이유", exit_reasons: "나간 이유", reason: "이유", side: "방향", symbol: "코인", timeframe: "봉",
  tf: "봉", n: "개수", count: "개수", total: "합계", losses_n: "손실 수", touched_first_lock: "첫 잠금 닿은 거래",
  first_lock: "첫 잠금", lock_levels: "잠금 단계", stop_whatif: "손절 가정", stop_whatif_24h: "24시간 손절 가정",
  vs_coinflip: "동전 봇 대비", vs_coinflip_p: "동전 봇 대비 p", coin_flip_wallets: "동전 봇 잔고", strategy_accounts: "매매법 계좌",
  diff: "차이", p: "p값", trades_24h: "24시간 거래 수", wins_24h: "24시간 이긴 거래", busts: "파산", bust: "파산",
  regime: "장세", htf_regime: "큰 봉 장세", adx: "ADX", entry: "진입", exit: "청산", hold_min: "보유 시간(분)",
  support_resistance: "지지·저항", entry_strength: "진입 세기", data_gaps: "자료 빈 곳", gate: "코드 관문",
  gate_reasons: "관문 근거", n_trials: "시험 수", tests: "시험", proposals: "제안", approvals: "승인", summary: "요약",
  summary_ko: "요약", name_ko: "이름", label_ko: "이름", headline: "한 줄 요약", findings: "발견", claim: "주장",
  evidence: "근거", accounts: "계좌", account_id: "계좌", strategy: "매매법", strategies: "매매법", family: "계열",
  ds200: "딥시크", reel: "릴스 5분", core: "기존 36", flip: "동전 봇", random: "동전 봇", extra: "추가 계좌",
  long: "롱", short: "숏", upnl: "평가 손익", exposure: "노출", near_liq: "청산 가까움", window: "기간", week: "주간",
  day: "하루", hour: "시간", recent: "최근", history: "기록", candidates: "후보", ideas: "아이디어", spec: "규칙 내용",
  similar_tested: "비슷한 시험", research: "연구", research_tests: "연구 시험", news_calendar: "경제 일정", upcoming: "다가오는 일정",
  run_restarted: "다시 시작한 날", observation: "관찰 기간", money_note: "돈 숫자 안내", worst_roe: "가장 나쁜 ROE",
  win_loss: "이긴·진 거래", win_share: "이긴 비율", loss_share: "손실 비율", mean_roe_by_reason: "나간 이유별 평균 ROE",
  new_loss_tags: "새 손실 태그", loss_tags_24h: "24시간 손실 태그", macro_corr: "경제지표 관계", exec_cost: "체결 비용",
  slow: "느린 쪽", fast: "빠른 쪽", period1: "1기간", period2: "2기간", period3: "3기간", available: "자료 있음",
};
// words of a snake_case key that has no whole name ("mean_roe_long" -> "거래당 평균 ROE 롱")
const WORD_KO = {
  mean: "평균", median: "중앙값", max: "최대", min: "최소", sum: "합계", total: "합계", share: "비율", rate: "비율",
  n: "개수", count: "개수", roe: "ROE", pnl: "손익", wins: "이긴 거래", win: "이긴", loss: "손실", losses: "손실", trades: "거래",
  trade: "거래", fees: "수수료", fee: "수수료", funding: "펀딩", long: "롱", short: "숏", stop: "손절", lock: "잠금", liq: "강제청산",
  lev: "배수", leverage: "배수", margin: "증거금", equity: "자금", notional: "명목금액", ret: "수익률", hold: "보유", bars: "봉",
  h: "시간", ms: "", days: "일", day: "일", week: "주", hour: "시간", recent: "최근", last: "마지막", first: "첫", new: "새",
  tag: "태그", tags: "태그", coin: "코인", coins: "코인", side: "방향", entry: "진입", exit: "청산", signal: "신호", signals: "신호",
  best: "좋은 자리", normal: "보통 자리", tier: "자리", score: "점수", p: "p값", diff: "차이", reason: "이유", reasons: "이유",
  by: "", per: "", of: "", vs: "대비", coinflip: "동전 봇", flip: "동전 봇", strategy: "매매법", account: "계좌", accounts: "계좌",
  wallet: "잔고", busts: "파산", bust: "파산", open: "열린", closed: "닫힌", price: "가격", move: "움직임", time: "시각",
  ts: "시각", "24h": "24시간", "7d": "7일", tf: "봉", timeframe: "봉", session: "시간대", regime: "장세", trend: "추세", ref: "기준",
};

/** "loss_cards[0].tags" -> ["loss_cards", 0, "tags"] (dots, [n] and plain digits; never fails). */
export function pathParts(path) {
  const out = [];
  for (const raw of String(path || "").split(".")) {
    const m = raw.match(/^([^[\]]*)((?:\[\d+\])*)$/);
    if (!m) { if (raw) out.push(raw); continue; }
    if (m[1]) out.push(/^\d+$/.test(m[1]) ? Number(m[1]) : m[1]);
    for (const k of m[2].match(/\d+/g) || []) out.push(Number(k));
  }
  return out;
}

function keyKo(k) {
  if (typeof k === "number") return null;
  const key = String(k);
  if (KEY_KO[key]) return KEY_KO[key];
  if (/^\d+[mh]$/.test(key)) return `${fmt.tfKo(key)}봉`;               // by_strategy.15m
  if (/^[A-Z0-9]+USDT$/.test(key)) return fmt.coin(key);                  // by_coin.BTCUSDT
  const words = key.split("_").filter(Boolean);
  if (!words.length) return null;
  const ko = words.map((w) => (w in WORD_KO ? WORD_KO[w] : null));
  if (ko.some((w) => w == null)) return null;
  const s = ko.filter(Boolean).join(" ");
  return s || null;
}

/** A packet path in plain Korean: "손실 카드 1번 › 태그"; an unknown part is "세부 항목" (never the raw key). */
export function pathKo(path) {
  const parts = pathParts(path);
  if (!parts.length) return "세부 항목";
  const out = [];
  let prev = null;
  for (const p of parts) {
    const after = prev;
    prev = p;
    if (typeof p === "number" && after === "periods") { out[out.length - 1] = `${fmt.int(p)}기간`; continue; }   // a period id, not an index
    if (typeof p === "number") {
      if (out.length) out[out.length - 1] += ` ${fmt.int(p + 1)}번`;
      else out.push(`${fmt.int(p + 1)}번`);
      continue;
    }
    const ko = keyKo(p);
    const name = ko || "세부 항목";
    if (out[out.length - 1] !== name) out.push(name);                      // never "세부 항목 › 세부 항목"
  }
  return out.join(" › ");
}

/** A stored value next to its name: a number, a short text or a list of short texts; null for anything else (never
 *  JSON). */
export function valueKo(v) {
  if (v == null || v === "") return null;
  if (typeof v === "number") return Number.isFinite(v) ? fmt.num(v, Math.abs(v) >= 100 || Number.isInteger(v) ? 0 : Math.abs(v) >= 1 ? 2 : 4) : null;
  if (typeof v === "boolean") return v ? "예" : "아니오";
  if (typeof v === "string") return v.length > 80 ? v.slice(0, 79) + "…" : v;
  if (Array.isArray(v) && v.length && v.every((x) => typeof x === "string" || typeof x === "number")) {
    const s = v.slice(0, 5).map((x) => valueKo(x)).filter(Boolean).join(", ");
    return v.length > 5 ? `${s} 외 ${fmt.int(v.length - 5)}개` : s;
  }
  return null;
}

/** One evidence item (a path string, or an object the store kept) -> {name, value, path}. An object is read for its
 *  path / value; its other keys are named one by one (key: value), never printed as JSON. */
export function evidenceItem(x) {
  if (typeof x === "string" || typeof x === "number") return {name: pathKo(String(x)), value: null, path: String(x)};
  if (x && typeof x === "object" && !Array.isArray(x)) {
    const path = typeof x.path === "string" ? x.path : typeof x.key === "string" ? x.key : null;
    if (path) return {name: pathKo(path), value: valueKo(x.value), path};
    const kv = Object.entries(x).slice(0, 4).map(([k, v]) => {
      const vv = valueKo(v);
      return vv == null ? null : `${keyKo(k) || "세부 항목"} ${vv}`;
    }).filter(Boolean);
    return {name: kv.length ? kv.join(" · ") : "세부 자료", value: null, path: null};
  }
  return {name: "세부 자료", value: null, path: null};
}

/** The 근거 list of a staff message: per claim (the stored answer's findings / objections) its plain-named paths;
 *  else the message's flat evidence. [{claim: string|null, items: [{name, value, path}]}] */
export function evidenceGroups(m, answer) {
  const a = answer && typeof answer === "object" ? answer : {};
  const claims = [].concat(Array.isArray(a.findings) ? a.findings : [], Array.isArray(a.objections) ? a.objections : [])
    .filter((f) => f && typeof f === "object" && Array.isArray(f.evidence) && f.evidence.length);
  if (claims.length) return claims.map((f) => ({claim: typeof f.claim === "string" ? f.claim : null, items: f.evidence.map(evidenceItem)}));
  const ev = Array.isArray(m && m.evidence) ? m.evidence : m && m.evidence ? [m.evidence] : [];
  return ev.length ? [{claim: null, items: ev.map(evidenceItem)}] : [];
}

/** The folded list's body: claims with their sources, each source in plain words (and its value when kept). */
export function evidenceList(groups) {
  const item = (it) => h("li", {dataset: it.path ? {path: it.path} : null}, it.name, it.value != null ? h("b", {class: "num"}, ` ${it.value}`) : null);
  return h("div", {class: "rm-evs"}, groups.map((g) => g.claim
    ? h("div", {class: "rm-evg"}, h("p", {class: "rm-evc"}, g.claim), h("ul", {class: "rm-ev"}, g.items.map(item)))
    : h("ul", {class: "rm-ev"}, g.items.map(item))),
  h("p", {class: "rm-evn"}, "근거 = 직원이 본 자료의 이름 (코드가 만든 자료에 실제로 있는 칸만 남깁니다)"));
}

/** How many different sources a message cites (for the "근거 n곳" label; a path two claims share counts once). */
export const evidenceCount = (groups) => new Set(groups.flatMap((g) => g.items.map((it) => it.path || it.name))).size;
