// #/status 서버 상태: the engine (how far it has processed, how late, the catch-up from 10/01, the last pass's time),
// the machine (load against its CPUs, the engine's memory), the live price feed of the terminal, the settings that
// matter (DeepSeek money shown or hidden) and the engine's notes. Data: the shared snapshot + /api/live.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";

export async function mount(el, ctx) {
  const tiles = h("div"), machine = h("div"), notes = h("div"), feed = h("div");
  el.append(
    ui.screenHead("서버 상태", "후보 리그 엔진 · 서버 · 시세"),
    ui.card({plate: "엔진"}, tiles),
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
        ui.stat("10/01부터", `${fmt.int(LK.leagueDay(d))}일째`, d.started_ms ? `설치 ${fmt.kst(d.started_ms)}` : null)),
      LK.catchingUp(d) ? ui.progress(Math.min(1, (d.done_ms - d.start_ms) / Math.max(1, d.started_ms - d.start_ms)),
        `10/01부터 따라잡는 중 (설치 시각까지 ${fmt.pct(Math.min(100, 100 * (d.done_ms - d.start_ms) / Math.max(1, d.started_ms - d.start_ms)), false, 0)})`) : null,
      h("dl", {class: "kv"},
        h("div", null, h("dt", null, "계좌"), h("dd", null, `${fmt.int(d.accounts.length)}개 (후보 ${fmt.int(d.accounts.filter((a) => a.role === "cand").length)}개 × 5종류, 기본값은 칸마다 1개)`)),
        h("div", null, h("dt", null, "딥시크 금액"), h("dd", null, d.ds_money ? "보임 (두 분 요청 2026-10-11)" : "숨김 (CANDLEAGUE_DS_MONEY=0)")),
        h("div", null, h("dt", null, "점검 날짜"), h("dd", null, ((d.watch && d.watch.checkpoints) || []).map((c) => `${c.ko} ${fmt.mmdd(c.ms)}`).join(" · ") || "—")))));
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
