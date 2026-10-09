// #/status 서버 상태: the engine's phase (warm / live), the last bar times, the next tick, data issues, errors, the
// process's memory and CPU, the database size, free disk, Telegram, and the run's facts. status.json every 30 s
// (the shell's own poll, shared with the header dot). 로그아웃 at the foot.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {PHASE_KO, tfKo} from "../labels.js";

const MEM_CAP_MB = 900;        // demobot-live.service MemoryMax (CONTRACT.md section 3)
const CPU_CAP_PCT = 30;        // demobot-live.service CPUQuota
const DISK_LOW_MB = 2048;

export async function mount(el, ctx) {
  ctx.setTitle("서버 상태");
  const top = h("section", {class: "card hero dl-stop", "aria-label": "엔진 상태"});
  const data = h("div", {class: "stack tight"}), procBox = h("div"), tg = h("div"), facts = h("div"), issues = h("div");
  const logout = h("form", {method: "post", action: "/logout", class: "row wrap dl-logout"},
    h("button", {class: "btn-line", type: "submit"}, "로그아웃"),
    h("span", {class: "muted"}, "로그아웃하면 다시 비밀번호를 넣어야 합니다."));
  el.append(ui.screenHead("서버 상태", "엔진이 제대로 도는지 (30초마다 새로 읽음)"), top,
    h("div", {class: "grid2"}, ui.card({plate: "시세 자료"}, data), ui.card({plate: "문제"}, issues)),
    h("div", {class: "grid2"}, ui.card({plate: "프로세스·디스크"}, procBox), ui.card({plate: "텔레그램"}, tg)),
    ui.card({plate: "실행 정보"}, facts), logout);

  let seen = null, last = null;
  const times = {};
  ctx.onStatus((st) => {
    const key = st ? `${st.generated_ms}|${st.last_tick_ms}` : "none";
    if (key === seen) { paintTimes(st); return; }
    seen = key;
    paint(st);
  });
  // the "~분 전" words follow the clock between two status reads
  ctx.every(30000, () => { if (last) paintTimes(last); });

  function paint(st) {
    last = st;
    if (!st || isMissing(st)) {
      put(top, h("p", {class: "dl-vbig warn"}, "준비 중"), ui.missing("엔진 상태 파일(status.json)"));
      for (const b of [data, procBox, tg, facts, issues]) put(b, ui.empty("—"));
      return;
    }
    const nowMs = Date.now();
    const stale = st.phase === "live" && st.last_tick_ms && nowMs - st.last_tick_ms > 40 * 60000;
    const bad = st.phase === "stopped" || (st.errors && st.errors.length) || stale;
    const warn = !bad && (st.phase === "warm" || st.data_ok === false || (st.data_issues && st.data_issues.length));
    times.tick = h("b", {class: "num"});
    times.next = h("b", {class: "num"});
    times.tickAgo = h("span", {class: "s"});
    times.nextIn = h("span", {class: "s"});
    times.secs = st.tick_seconds != null ? ` · 처리 ${fmt.num(st.tick_seconds, 1)}초` : "";
    put(top,
      h("div", {class: "card-h"}, ui.plate("엔진"), h("span", {class: "sub"}, st.version || "")),
      h("p", {class: ["dl-vbig", bad ? "no" : warn ? "warn" : "ok"]}, PHASE_KO[st.phase] || st.phase || "—"),
      h("p", {class: "dl-vline"}, bad ? (stale ? "마지막 처리가 오래됐습니다. 엔진을 확인하세요." : st.phase === "stopped" ? "엔진이 멈춰 있습니다." : "오류가 있습니다. 아래 '문제'를 보세요.")
        : st.phase === "warm" ? "과거 26주 자료를 채우는 중입니다 (처음 한 번, 약 10분)." : warn ? "돌고 있지만 자료 문제가 있습니다." : "정상으로 돌고 있습니다."),
      h("div", {class: "stats dl-s4"},
        ui.stat("마지막 처리", times.tick, times.tickAgo),
        ui.stat("다음 처리", times.next, times.nextIn),
        ui.stat("실시간 시작", st.live_start_ms ? fmt.kst(st.live_start_ms) : "—", st.live_start_ms ? fmt.ago(st.live_start_ms) : "아직 시작 전"),
        ui.stat("과거 자료 시작", st.history_start_ms ? fmt.mmdd(st.history_start_ms) : "—", "순위표 26주 창")));
    paintTimes(st);

    const lb = st.last_bar_ms || {};
    put(data, ui.table([
      {label: "봉", l: true, get: (r) => h("b", null, tfKo(r[0]))},
      {label: "마지막 봉 (한국 시간)", get: (r) => fmt.kst(r[1])},
      {label: "얼마 전", get: (r) => fmt.ago(r[1])},
    ], Object.entries(lb)), h("div", {class: "row wrap dl-pills"},
      st.data_ok === false ? ui.pill("자료 문제 있음", "bad") : ui.pill("자료 정상", "good"),
      ui.pill(`코인 ${fmt.int((st.coins || []).length)}개`, "thin"),
      ...(st.coins || []).map((c) => h("span", {class: "pp"}, fmt.coin(c)))));

    const iss = st.data_issues || [], errs = st.errors || [];
    put(issues, !iss.length && !errs.length ? ui.empty("문제 없음") : h("div", {class: "stack tight"},
      errs.length ? h("div", null, h("b", {class: "down"}, `오류 ${errs.length}건`), h("ul", {class: "dl-ul"}, errs.slice(0, 20).map((x) => h("li", null, String(x))))) : null,
      iss.length ? h("div", null, h("b", {class: "warn-t"}, `자료 문제 ${iss.length}건`), h("ul", {class: "dl-ul"}, iss.slice(0, 20).map((x) => h("li", null, String(x))))) : null));

    const p = st.proc || {};
    put(procBox, h("div", {class: "stack tight"},
      gauge("메모리 (엔진)", p.rss_mb, MEM_CAP_MB, fmt.mb(p.rss_mb), `한도 ${fmt.mb(MEM_CAP_MB)}`),
      p.cpu_pct == null && p.cpu_s != null
        ? h("div", {class: "stats"}, ui.stat("CPU (엔진)", fmt.dur(p.cpu_s), "시작부터 쓴 CPU 시간 (한도 30%)"))
        : gauge("CPU (엔진)", p.cpu_pct, CPU_CAP_PCT, fmt.pct(p.cpu_pct), `한도 ${CPU_CAP_PCT}%`),
      h("div", {class: "stats"},
        ui.stat("데이터베이스", fmt.mb(st.db_mb), "demo.db"),
        ui.stat("남은 디스크", fmt.mb(st.disk_free_mb), Number(st.disk_free_mb) < DISK_LOW_MB ? "모자람" : "여유",
          Number(st.disk_free_mb) < DISK_LOW_MB ? "dl-bad" : null))));

    const t = st.telegram || {};
    put(tg, ui.kv([
      ["설정", t.configured ? "됨" : "안 됨 (토큰·방 없음)"],
      ["보낼 것", t.queued != null ? `${fmt.int(t.queued)}개` : "—"],
      ["마지막 보냄", t.last_ok_ms ? `${fmt.kst(t.last_ok_ms)} (${fmt.ago(t.last_ok_ms)})` : "—"],
    ]), t.last_error ? h("p", {class: "errbox"}, `마지막 오류: ${t.last_error}`) : null);

    const c = st.counts || {}, cost = st.costs || {};
    put(facts, ui.kv([
      ["설정 수", fmt.int(c.settings)],
      ["선수 (설정 × 청산 …)", fmt.int(c.players)],
      ["열린 칸", c.cells_total ? `${fmt.int(c.cells_open)} / ${fmt.int(c.cells_total)}` : fmt.int(c.cells_open)],
      ["24시간 신호", fmt.int(c.signals_24h)],
      ["봉", (st.tfs || []).map(tfKo).join(" · ") || "—"],
      ["배수", (st.leverages || []).map((L) => `${L}배`).join(" · ") || "—"],
      ["시작 돈 (줄마다)", fmt.money(st.seed)],
      ["수수료 (한 번)", cost.taker != null ? fmt.ratio(cost.taker, 2) : "—"],
      ["슬리피지 (한 번)", cost.slippage != null ? fmt.ratio(cost.slippage, 2) : "—"],
      ["펀딩 (순위표)", cost.funding_8h_ranking != null ? `8시간마다 ${fmt.ratio(cost.funding_8h_ranking, 2)}` : "—"],
      ["펀딩 (계좌)", cost.funding_accounts === "real" ? "바이낸스 실제 값" : String(cost.funding_accounts ?? "—")],
      ["자료 시각", fmt.kst(st.generated_ms)],
    ]));
  }
  function paintTimes(st) {
    if (!st || isMissing(st) || !times.tick) return;
    times.tick.textContent = st.last_tick_ms ? fmt.kst(st.last_tick_ms) : "—";
    times.next.textContent = st.next_tick_ms ? fmt.kst(st.next_tick_ms) : "—";
    times.tickAgo.textContent = (st.last_tick_ms ? fmt.ago(st.last_tick_ms) : "아직 없음") + times.secs;
    times.nextIn.textContent = st.next_tick_ms ? `${fmt.ago(st.next_tick_ms)} · 15분봉이 닫힐 때마다` : "15분봉이 닫힐 때마다";
  }
}

function gauge(name, value, cap, shown, capKo) {
  const have = value != null && Number.isFinite(Number(value));
  const r = have ? Number(value) / cap : null;
  const st = !have ? "none" : r < 0.6 ? "ok" : r < 0.85 ? "warn" : "bad";
  const stKo = {ok: "여유", warn: "지켜볼 것", bad: "조치 필요", none: "자료 없음"}[st];
  return h("div", {class: ["gauge", st]},
    h("div", {class: "g-top"}, h("span", {class: "g-name"}, name), h("span", {class: "g-st"}, stKo),
      h("span", {class: "g-val"}, have ? shown : "—", h("small", null, ` · ${capKo}`))),
    r != null ? h("div", {class: "g-bar"}, h("i", {style: {"--v": Math.max(0, Math.min(1, r)) * 100 + "%"}})) : null);
}
