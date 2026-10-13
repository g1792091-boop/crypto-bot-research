// #/status 서버 상태: the engine (its start, how far it has processed, how late, a catch-up's progress, the last pass's time),
// the machine (load against its CPUs, the engine's memory), the live price feed of the terminal, the settings that
// matter (DeepSeek money shown or hidden) and the engine's notes. Data: the shared snapshot + /api/live.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {freshLine, staleBanner} from "../poskit.js";
import {lineupOn} from "../labels.js";

/** How much of the span from the start to the time the record was written the engine has processed (a catch-up). */
const catchShare = (d) => Math.max(0, Math.min(1, (d.done_ms - d.start_ms) / Math.max(1, d.generated_ms - d.start_ms)));

/** "14일째 첫 확인 10/09 · 28일째 판정 10/23" (the owner-exit league's road; lk.js road). */
const roadText = (d) => {
  const r = LK.road(d);
  return r ? `${r.observe}일째 첫 확인 ${fmt.mmdd(r.observe_ms)} · ${r.decide}일째 판정 ${fmt.mmdd(r.decide_ms)}` : "—";
};

export async function mount(el, ctx) {
  const tiles = h("div"), machine = h("div"), notes = h("div"), feed = h("div"), pos = h("div"), banner = h("div");
  const fresh = freshLine(null);
  el.append(
    ui.screenHead("서버 상태", "후보 리그 엔진 · 서버 · 시세"),
    fresh, banner,
    ui.card({plate: "엔진"}, tiles),
    ui.card({plate: "열린 포지션 기록", sub: "포지션 · 터미널 · 순위표가 읽는 것 (스냅샷의 열린 포지션 + 증거금·청산가 다시 계산)"}, pos),
    ui.card({plate: "서버", sub: "규칙봇과 같은 서버 · 후보 리그는 CPU 30% · 메모리 1.3 GB까지만 쓰도록 묶여 있습니다"}, machine),
    ui.card({plate: "터미널 시세", sub: "대시보드 서버가 바이낸스 공개 자료를 받아 잠깐 저장해 둔 것 (키 없음)"}, feed),
    ui.card({plate: "엔진 메모", sub: "신호 계산 중 생긴 일 (최근 20개)"}, notes));
  ctx.onLeague((d) => {
    const H = LK.health(d);
    if (!d.accounts) { put(tiles, h("p", null, ui.pill(H.ko, "warn"))); return; }
    const lagMin = Math.max(0, (Date.now() - d.done_ms) / 60000);
    put(tiles, h("div", {class: "stack tight"},
      h("p", null, ui.pill(H.ko, H.lv === "ok" ? "good" : H.lv === "warn" ? "warn" : "bad")),
      h("div", {class: "stats cl-stats4"},
        ui.stat("처리한 시각", `${fmt.kst(d.done_ms)}`, "KST · 이 시각까지의 1분봉을 계산함"),
        ui.stat("늦음", lagMin < 60 ? `${fmt.int(lagMin)}분` : fmt.dur(lagMin * 60), "5분봉이 확정되는 대로 (보통 10분 안)"),
        ui.stat("기록 쓴 시각", fmt.kst(d.generated_ms), fmt.ago(d.generated_ms)),
        ui.stat("시작부터", `${fmt.int(LK.leagueDay(d))}일째`, LK.replayedBefore(d) ? `${LK.startKo(d)} 시작 · 설치 ${fmt.kst(d.started_ms)}`
          : `${LK.startKo(d)} 시작 (설치한 때)`)),
      LK.catchingUp(d) ? ui.progress(catchShare(d), `따라잡는 중 (시작부터 기록 쓴 시각까지의 ${fmt.pct(100 * catchShare(d), false, 0)} 계산함)`) : null,
      h("dl", {class: "kv"},
        h("div", null, h("dt", null, "계좌"), h("dd", null, lineupOn() ? `${fmt.int(d.accounts.length)}개 (후보 ${fmt.int(LK.leagueCounts(d).picks)}개 × 계좌 종류 ${fmt.int(LK.leagueCounts(d).kinds)}가지 · 후보에 따라 없는 종류가 있음)`
          : `${fmt.int(d.accounts.length)}개 (후보 ${fmt.int(d.accounts.filter((a) => a.role === "cand").length)}개 × 5종류, 기본값은 칸마다 1개)`)),
        h("div", null, h("dt", null, "딥시크 금액"), h("dd", null, d.ds_money ? "보임 (두 분 요청 2026-10-11)" : "숨김 (CANDLEAGUE_DS_MONEY=0)")),
        lineupOn() ? h("div", null, h("dt", null, "판정 일정"), h("dd", null, roadText(d)))
          : h("div", null, h("dt", null, "점검 날짜"), h("dd", null, ((d.watch && d.watch.checkpoints) || []).map((c) => `${c.ko} ${fmt.mmdd(c.ms)}`).join(" · ") || "—")))));
    const s = d.server || {};
    const load1 = s.load ? s.load[0] : null;
    put(machine, h("div", {class: "stats cl-stats4"},
      ui.stat("부하 (1분 · 5분 · 15분)", s.load ? s.load.map((x) => fmt.num(x, 2)).join(" · ") : "—",
        s.cpus ? `CPU ${s.cpus}개 · ${load1 != null && load1 > s.cpus ? "바쁨" : "여유"}` : null, load1 != null && s.cpus && load1 > s.cpus ? "warn" : ""),
      ui.stat("엔진 메모리 (최대)", s.rss_mb != null ? `${fmt.num(s.rss_mb, 0)} MB` : "—", "한도 1,300 MB"),
      ui.stat("한 번 처리 시간", s.pass_s != null ? `${fmt.num(s.pass_s, 1)}초` : "—", "5분마다 · 봉이 닫히는 때는 길어짐"),
      ui.stat("서버 CPU", s.cpus ? `${s.cpus}개` : "—", "규칙봇이 먼저: 후보 리그는 우선순위 낮음 (Nice 10)")),
    h("p", {class: "note"}, "부하는 서버 전체(규칙봇 포함)입니다. CPU 개수보다 계속 크면 새 서버로 옮기는 것을 생각해 보세요."));
    put(notes, (d.notes || []).length ? h("ul", {class: "cl-notes"}, d.notes.map((n) => h("li", null, n))) : ui.empty("메모 없음"));
  });
  ctx.onPositions((p) => {
    fresh.update(p);
    put(banner, staleBanner(p));
    if (!p || p.status || !p.counts) { put(pos, ui.empty("준비 중")); return; }
    const c = p.counts;
    put(pos, h("div", {class: "stack tight"}, h("div", {class: "stats cl-stats4"},
      ui.stat("열린 포지션", `${fmt.int(c.open)}개`, `롱 ${fmt.int(c.long)} · 숏 ${fmt.int(c.short)}`),
      ui.stat("금액 숨김", `${fmt.int(c.hidden)}개`, p.ds_money ? "딥시크 금액 보임" : "딥시크는 개수·방향만"),
      ui.stat("기록 나이", p.snap_age_s == null ? "—" : fmt.dur(p.snap_age_s), p.old ? "15분 넘음: 엔진 확인" : "5분마다 새로 씀", p.old ? "warn" : ""),
      ui.stat("증거금·청산가", p.exact ? "엔진 값 그대로" : "잔고·배수로 다시 계산", p.brackets || "거래소 표 없음: 청산가 빈칸")),
    h("p", {class: "note"}, "증거금·크기·청산가는 진입 때 기준입니다 (그 뒤 펀딩으로 조금 달라질 수 있음). 손익은 화면이 실시간 마크 가격으로 계산합니다.")));
  });
  ctx.onLive(() => fresh.update());
  async function pollFeed() {
    let lv;
    try { lv = await ctx.api("/api/live"); } catch (e) { put(feed, ui.errorBox(e, pollFeed)); return; }
    put(feed, h("dl", {class: "kv"},
      h("div", null, h("dt", null, "상태"), h("dd", null, lv.off ? "꺼짐 (CANDLEAGUE_DASH_LIVE=off)" : lv.unavailable ? "바이낸스 연결 안 됨" : lv.source === "fake" ? "연습용 가짜 시세" : lv.stale ? "지난 값 (잠시 연결 안 됨)" : "정상")),
      h("div", null, h("dt", null, "받은 시각"), h("dd", null, lv.generated_ms ? `${fmt.hms(lv.generated_ms)} KST` : "—")),
      h("div", null, h("dt", null, "코인"), h("dd", null, (lv.coins || []).map((c) => c.coin.replace(/USD$/, "")).join(" · ") || "—"))));
  }
  await pollFeed();
  ctx.every(15000, pollFeed);
}
