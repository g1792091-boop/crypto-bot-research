// 서버·비용 (builder E): the health summary behind the health dot and the health tiles. Reads /api/analysis/health
// (store "health"), the live stream's heartbeat and connection state; the same stale rule as the dot and the red
// banner (core/alerts.js criticalLines), so this screen never disagrees with the dot.
import {h, ui, fmt, stream, serverNow, criticalLines, put} from "../core/pb.js";
import {states, tile, note} from "./server-kit.js";

const TITLE = {ok: "모두 정상입니다", warn: "확인할 것이 있습니다", bad: "고칠 것이 있습니다", unknown: "확인하는 중입니다"};
const ago = (s) => (s == null ? "기록 없음" : `${fmt.dur(s)} 전`);

/** Problems / warnings / level with the live stream folded in (the dot's own rule). */
export function healthState(hl) {
  const now = serverNow();
  const problems = [...((hl && hl.problems) || [])];
  const warnings = [...((hl && hl.warnings) || [])];
  const stale = criticalLines({health: hl, alerts: [], trades: [], hb: stream.heartbeat, streamOk: stream.state === "open", now})
    .filter((l) => l.kind === "stale");
  // the stream's fresher heartbeat says the same as the dot; health's own line wins when it already says it
  if (stale.length && !problems.some((p) => /생존|1분봉/.test(p))) problems.unshift(stale[0].text);
  if (stream.state === "error") warnings.unshift("이 기기의 실시간 연결이 끊겨 다시 연결하는 중입니다");
  const level = problems.length ? "bad" : warnings.length ? "warn" : hl ? "ok" : "unknown";
  return {problems, warnings, level};
}

export function summaryCard(ctx) {
  const dot = h("i");
  const title = h("b", {class: "server-sumt"});
  const at = h("span", {class: "muted server-at"});
  const lines = h("ul", {class: "server-lines"});
  const card = ui.card({plate: "지금 상태", cls: "server-sum", hero: true},
    h("div", {class: "server-dotline"}, dot, h("div", {class: "stack tight"}, title, at)), lines, states(),
    h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: ctx.href("alerts")}, "알림 기록"),
      h("a", {class: "btn-line", href: ctx.href("signals")}, "신호 지연"), h("a", {class: "btn-line", href: ctx.href("faq")}, "점 색의 뜻")));
  let sig = "";
  card.update = (hl, err) => {
    const s = healthState(hl);
    const lv = s.level;
    card.dataset.level = lv;
    card.querySelector(".server-dotline").className = `server-dotline ${lv === "unknown" ? "none" : lv}`;
    title.textContent = lv === "bad" ? `${TITLE.bad} (${fmt.int(s.problems.length)}개)` : lv === "warn" ? `${TITLE.warn} (${fmt.int(s.warnings.length)}개)` : TITLE[lv];
    at.textContent = hl ? `${fmt.kst(hl.computed_at || hl.now)} 기준 · 1분마다 다시 읽음` : err ? "건강 점검을 읽지 못했습니다. 잠시 뒤 다시 읽습니다." : "읽는 중";
    const key = JSON.stringify([s.problems, s.warnings]);
    if (key === sig) return;
    sig = key;
    put(lines, s.problems.map((p) => h("li", {class: "bad"}, p)), s.warnings.map((w) => h("li", {class: "warn"}, w)));
    lines.hidden = !(s.problems.length || s.warnings.length);
  };
  return card;
}

/** Every part of the health card as its own tile (one missing part never hides the rest). */
export function tiles(hl, o = {}) {
  const now = serverNow();
  const out = [];
  const b = (hl && hl.bot) || {};
  const hbTs = stream.heartbeat ? Number(stream.heartbeat[0]) : b.heartbeat_ts;
  const lastBar = stream.heartbeat && stream.heartbeat[1] && stream.heartbeat[1].last_step ? Number(stream.heartbeat[1].last_step) : b.last_bar_ts;
  const hbAge = hbTs ? Math.max(0, (now - hbTs) / 1000) : null;
  const dataAge = lastBar ? Math.max(0, (now - lastBar) / 1000) : null;
  if (hl && !b.ready) out.push(tile({k: "봇 생존 신호", v: "없음", s: "paper3.db를 열지 못함", st: "bad"}));
  else {
    out.push(tile({k: "봇 생존 신호", v: hbAge == null ? "기록 없음" : hbAge < 90 ? "정상" : "멈춤", s: `마지막 ${ago(hbAge)}`,
      st: hbAge == null ? "none" : hbAge < 90 ? "ok" : "bad"}));
    out.push(tile({k: "1분봉 시세", v: dataAge == null ? "기록 없음" : dataAge < 300 ? "들어옴" : "끊김", s: `마지막 봉 ${ago(dataAge)}`,
      st: dataAge == null ? "none" : dataAge < 300 ? "ok" : "bad"}));
  }
  const live = stream.live();
  out.push(tile({k: "실시간 연결 (이 기기)", v: stream.state === "open" ? (live ? "연결됨" : "연결됨 · 봇 조용") : stream.state === "error" ? "다시 연결 중" : "연결 준비",
    s: stream.lastEventAt ? `마지막 소식 ${ago((Date.now() - stream.lastEventAt) / 1000)}` : "아직 소식 없음",
    st: stream.state === "open" ? (live ? "ok" : "warn") : stream.state === "error" ? "warn" : "none"}));
  if (b.ready) {
    out.push(tile({k: "신호 (24시간)", v: `${fmt.int(b.signals_24h)}개`,
      s: `늦음 ${fmt.int(b.signals_late_24h || 0)}개 · 평균 지연 ${b.avg_delay_s == null ? "—" : fmt.num(b.avg_delay_s, 1) + "초"}`,
      st: b.signals_late_24h ? "warn" : "ok"}));
    const al = b.alerts_24h || {};
    out.push(tile({k: "경고 (24시간)", v: `긴급 ${fmt.int(al.CRITICAL || 0)} · 주의 ${fmt.int(al.WARN || 0)}`, s: "원문은 알림 기록",
      st: al.CRITICAL ? "bad" : al.WARN ? "warn" : "ok"}));
  }
  const ag = (hl && hl.agents) || {};
  if (hl) {
    if (!ag.configured) out.push(tile({k: "에이전트", v: "설정 안 됨", s: "agents3.db 경로 없음", st: "none"}));
    else {
      const stop = ag.tick_age_s != null && ag.tick_age_s > 2700, fail = ag.last_tick && ag.last_tick.ok === false;
      const aiFail = ag.ai && ag.ai.failed;
      out.push(tile({k: "에이전트", v: ag.tick_age_s == null ? "기록 없음" : stop ? "멈춤" : fail ? "실패" : "도는 중",
        s: `마지막 점검 ${ago(ag.tick_age_s)}${aiFail ? ` · AI 연속 실패 ${fmt.int(aiFail)}번` : " · AI 응답 정상"}`,
        st: ag.tick_age_s == null ? "none" : stop || fail || aiFail ? "bad" : "ok"}));
    }
  }
  const n = (hl && hl.nightly) || {};
  if (n.ready && n.start_day && (n.parity || {}).accounts == null) {
    // the run's start day: no 00:00 snapshot by design, so nothing to recompute (normal, not a warning)
    out.push(tile({k: `밤 점검 (${String(n.day || "").slice(5).replace("-", "/")})`, v: "시작한 날",
      s: "재계산 없음 (정상, 첫 재계산 내일 09:20)", st: "none"}));
  } else if (n.ready) {
    const p = n.parity || {};
    const okN = p.accounts != null ? p.accounts - (p.mismatched_accounts || 0) - (p.crash_gaps || 0) - (p.early_kline || 0) : null;
    const bits = [p.mismatched_accounts ? `불일치 ${fmt.int(p.mismatched_accounts)}` : "재계산 일치",
      p.early_kline ? `확정 전 1분봉(early_kline) ${fmt.int(p.early_kline)}: 계산 오류 아님` : null,
      p.crash_gaps ? `재시작 공백 ${fmt.int(p.crash_gaps)}` : null, n.missing_bars ? `빠진 1분봉 ${fmt.int(n.missing_bars)}` : null].filter(Boolean);
    out.push(tile({k: `밤 점검 (${String(n.day || "").slice(5).replace("-", "/")})`, v: p.accounts != null ? `${fmt.int(okN)}/${fmt.int(p.accounts)} 일치` : "재계산 못 함",
      s: bits.join(" · "), st: p.mismatched_accounts ? "bad" : p.accounts == null || p.early_kline || n.missing_bars ? "warn" : "ok"}));
  } else if (hl) out.push(tile({k: "밤 점검", v: "기록 없음", s: n.why || "아직 밤 점검 전", st: "none"}));
  const cp = (hl && hl.checkpoint) || {};
  if (hl) {
    // the verdict-day clock (summary next_checkpoint, dash/more/verdictday.py): a passed checkpoint stays 'due' until
    // its verdict is stored; days left in words, never 'D-' (review 10/06 fix 1, change 13)
    const nx = cp.next;
    const due = !!(nx && nx.due), bad = due && (nx.state === "failed" || nx.state === "unknown" || !!nx.late);
    const ended = !!(nx && nx.state === "ended");          // past day 180: no verdict left (never '시작 전')
    out.push(tile({k: "30일 판정", v: ended ? "판정 끝" : due ? (bad ? "확인 필요" : "계산 중") : cp.ready && !nx ? `${cp.date} 판정 끝`
      : nx && nx.ts ? `${fmt.int(Math.max(0, Math.ceil((nx.ts - now) / 864e5)))}일 남음` : "시작 전",
      s: ended ? `180일 실험이 끝나 더 이상 판정이 없습니다${cp.ready ? ` · 마지막 ${cp.date}` : ""}`
        : due ? `${fmt.int(nx.day)}일 판정 날 · 결과 저장 전 (판정 화면에서 진행 확인)`
        : nx && nx.ts ? `${(nx.k || 1) > 1 ? `${fmt.int(nx.k)}번째` : "첫"} 판정 ${fmt.kst(nx.ts)} (${fmt.int(nx.day)}일째)${cp.ready ? ` · ${cp.date} 판정 끝` : ""}`
        : "봇이 아직 첫 계좌를 만들지 않음", st: bad ? "bad" : due ? "warn" : "none"}));
  }
  if (hl && hl.liq_recorder) {
    const lq = hl.liq_recorder;
    out.push(tile({k: "강제청산 기록기", v: lq.age_s == null ? "기록 없음" : lq.age_s < 3600 ? "도는 중" : "조용함", s: `마지막 기록 ${ago(lq.age_s)}`,
      st: lq.age_s == null ? "none" : lq.age_s < 3600 ? "ok" : "warn"}));
  }
  if (hl) {
    const recent = (hl.job_failures || []).filter((f) => now - f.ts < 864e5);
    const jf = recent.filter((f) => !f.recovered_ts), fixed = recent.filter((f) => f.recovered_ts);   // re-run and succeeded
    out.push(tile({k: "예약 작업", v: jf.length ? `실패 경고 ${fmt.int(jf.length)}` : "실패 경고 없음",
      s: jf.length ? jf.map((f) => f.job_ko).join(", ") : fixed.length ? `${fixed.map((f) => f.job_ko).join(", ")}: 다시 돌려서 성공` : "지난 24시간",
      st: jf.length ? "warn" : "ok"}));
  }
  return out;
}

export function tilesCard() {
  const grid = h("div", {class: "server-tiles"});
  const card = ui.card({plate: "봇 · 시세 · 에이전트", sub: "부분마다 따로 읽음: 하나가 없어도 나머지는 보입니다"}, grid,
    note("경고 원문은 '알림 기록'에 있습니다."));
  card.update = (hl, o) => put(grid, tiles(hl, o));
  return card;
}
