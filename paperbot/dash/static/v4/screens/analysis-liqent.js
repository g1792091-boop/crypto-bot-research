// 분석 › 강제청산 직후 (ana7a): GET /api/v4/liqentry?group= (dash/more/liqentry.py). Per group (the 묶음 switch):
// entries that came 5 / 15 / 60 minutes after a large liquidation burst on the same coin, split into SAME way as the
// liquidated positions (long right after longs were liquidated) and OPPOSITE way, next to every other entry and to the
// group's coin flips split the same way. The recorder's first row is always shown (기록 시작): it was silent until the
// 10/06 fix. Before enough covered entries: one filling bar. HONESTY: DeepSeek counts and shares only; coin flips 참고.
import {h, put, ui, fmt, motion} from "../core/pb.js";
import {viewHead, groupWords, dimSeg, waitCard} from "./analysis-kit.js";
import {cellLine, cmpRows, pc, when, noMoneyLine} from "./analysis-a7kit.js";

const ROWS = [
  {k: "same", ko: "청산당한 쪽과 같은 방향", sub: "예: 롱이 크게 청산된 직후 롱"},
  {k: "opposite", ko: "청산당한 쪽과 반대 방향", sub: "예: 롱이 크게 청산된 직후 숏"},
  {k: "none", ko: "그 밖의 진입", sub: "그 시간 안에 큰 강제청산 없음"},
];

export function liqentry(d, env) {
  const grp = d.group || env.group || "core", W = groupWords(grp), money = !d.no_money && W.money;
  const out = [viewHead({plate: "강제청산 직후", q: "큰 강제청산이 터진 직후에 들어간 거래는 어땠나",
    meta: [`기록 시작: ${when(d.first_ts)}`, d.rows != null ? `강제청산 기록 ${fmt.int(d.rows)}줄` : null,
      d.trades != null ? `${W.who} 끝난 거래 ${fmt.int(d.trades)}건 · ${W.flips} ${fmt.int(d.flip_trades || 0)}건` : null].filter(Boolean).join(" · "),
    at: d.computed_at, stale: d.stale,
    read: `한 코인에서 1분 동안 강제청산이 크게 몰린 때(그 코인의 지금까지 기록 전체에서 상위 ${fmt.int((1 - (d.burst_pct || 0.95)) * 100)}%, 기록이 쌓이면 기준도 바뀜)를 '큰 강제청산'으로 봅니다. 그 뒤 5·15·60분 안에 같은 코인에 들어간 진입을 청산당한 쪽과 같은 방향 / 반대 방향으로 나눠, 그 밖의 진입과 ${W.flips}과 나란히 봅니다.`,
    warn: [!money ? noMoneyLine() : null,
      d.ready === false ? null : h("p", {class: "an-read"}, ui.pill("기록 시작", "accent"), ` 강제청산 기록기는 ${when(d.first_ts)}부터 기록했습니다 (그 전에는 바이낸스 주소 문제로 조용했음). 기록 전 진입은 뺍니다.`),
      d.stale ? h("p", {class: "an-warn"}, `마지막 기록이 ${when(d.last_ts)}입니다. 기록기가 멈췄을 수 있어요 (0건은 '없음'이 아니라 '모름').`) : null]})];
  if (d.error) { out.push(ui.card({plate: "강제청산 직후"}, h("p", {class: "muted"}, String(d.error)))); return out; }
  if (d.ready === false) {
    out.push(ui.card({plate: "강제청산 직후"}, h("p", {class: "muted"}, d.why || "강제청산 기록이 아직 없습니다."),
      h("p", {class: "an-note"}, "기록기가 돌기 시작하면 여기에 채워집니다.")));
    return out;
  }
  const need = d.min_covered || 20;
  if (d.waiting) {
    out.push(waitCard("강제청산 직후", [{label: `기록 시작 뒤 ${W.short} 진입 ${fmt.int(need)}건 필요`, share: Math.min(1, (d.covered || 0) / need),
      words: `지금 ${fmt.int(d.covered || 0)}건 (기록 전이거나 그 코인 기록이 아직 적어 뺀 진입 ${fmt.int(Math.max(0, (d.trades || 0) - (d.covered || 0)))}건)`}], null));
    out.push(coinCard(d));
    out.push(h("p", {class: "an-note an-foot"}, `강제청산 직후: ${W.who} · ${d.label || "설명용, 판정 아님"}`));
    return out;
  }
  const wins = (d.per_window || []).map((x) => x.minutes);
  const seg = dimSeg("liqw", wins.map((m) => ({id: String(m), label: `${m}분 안`})), "15", () => paint(true), false);
  const body = h("div");
  function paint(anim) {
    const pw = (d.per_window || []).find((x) => String(x.minutes) === seg.get()) || (d.per_window || [])[0] || {};
    const g = pw.group || {}, f = pw.coin_flips || {};
    const after = ((g.same || {}).n || 0) + ((g.opposite || {}).n || 0);
    put(body,
      cmpRows(ROWS.map((r) => ({label: r.ko, sub: r.sub, a: cellLine(g[r.k], !money), b: cellLine(f[r.k], !money)})),
        {k: `${pw.minutes}분 안`, a: W.short, b: `${W.flips} (참고)`}),
      h("p", {class: "a7-say"}, `큰 강제청산 뒤 ${pw.minutes}분 안에 들어간 진입 ${fmt.int(after)}건: 같은 방향 ${fmt.int((g.same || {}).n || 0)}건 (이긴 비율 ${pc((g.same || {}).wr)}), 반대 방향 ${fmt.int((g.opposite || {}).n || 0)}건 (${pc((g.opposite || {}).wr)}). 그 밖의 진입은 ${pc((g.none || {}).wr)}.`),
      g.uncovered ? h("p", {class: "an-note"}, `기록 전이거나 그 코인 기록이 아직 적어 뺀 진입 ${fmt.int(g.uncovered)}건.`) : null);
    if (anim) motion.swap(body);
  }
  paint(false);
  out.push(ui.card({plate: "직후 진입 vs 그 밖", sub: `${W.short} vs ${W.flips}`}, seg.el, body,
    h("p", {class: "an-note"}, money ? "ROE = 증거금 대비 손익 (수수료·펀딩 뺀 순). 이긴 = 순손익이 플러스." : "이긴 = 순손익이 플러스.",
      " 한 진입이 여러 시간 창에 같이 들어갑니다 (5분 안이면 15분·60분 안에도 셈)."),
    ui.refNote(env.verdictTs), money ? ui.assume() : null));
  out.push(coinCard(d));
  out.push(h("p", {class: "an-note an-foot"}, `강제청산 직후: ${W.who} · 실험 시작부터 끝난 거래 · ${d.label || "설명용, 판정 아님"}`));
  return out;
}

/** Per coin: what counts as a large burst so far (market data, not account money). */
function coinCard(d) {
  const coins = Object.entries(d.coins || {});
  if (!coins.length) return null;
  const rows = coins.map(([s, c]) => h("div", {class: "lrow a7-coin", role: "listitem"},
    h("span", {class: "lname"}, fmt.coin(s)),
    h("span", {class: "meta"},
      h("span", null, c.threshold_usd ? `1분에 $${fmt.compact(c.threshold_usd)} 이상이면 큰 강제청산` : `기준 아직 없음 (강제청산이 있었던 분 ${fmt.int(d.min_minutes || 30)}개 필요)`),
      h("span", null, `강제청산이 있었던 분 ${fmt.int(c.minutes || 0)}개 · 그중 큰 분 ${fmt.int(c.bursts || 0)}개`))));
  return ui.card({plate: "코인별 기준", sub: "시장 전체 강제청산 (바이낸스 공개 기록)"},
    ui.disclosure("코인마다 '큰 강제청산' 기준 보기", h("div", {class: "plist", role: "list"}, rows)),
    h("p", {class: "an-note"}, d.note_ko || "바이낸스는 코인마다 1초에 한 건만 알려 줘서, 몰릴 때는 실제보다 적게 잡힙니다."));
}
