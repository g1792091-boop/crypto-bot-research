// #/status 서버 상태: the engine's phase (warm / live), the last bar times, the next tick, data issues, errors, the
// process's memory and CPU, the database size, free disk, Telegram, and the run's facts. status.json every 30 s
// (the shell's own poll, shared with the header dot). CONTRACT 8.8: the nightly backup (backup.json), the outside
// watch (watch.json) and the dead-man ping (status.deadman), each with a plain ok / problem line; 8.13: the shared
// server (status.server: memory, load, the rule bot's services) and whether the rule bot still has room.
// 로그아웃 at the foot.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {PHASE_KO, tfKo, WATCH_KO} from "../labels.js";

const MEM_CAP_MB = 1200;       // demobot-live.service MemoryMax (CONTRACT.md section 3)
const CPU_CAP_PCT = 30;        // demobot-live.service CPUQuota
const DISK_LOW_MB = 2048;
const BACKUP_OK_H = 36;        // CONTRACT 8.8: no good backup for 36 h = a problem
const WATCH_OK_MIN = 30;       // the watch runs every 10 minutes
const DEAD_OK_MIN = 45;        // a ping after every tick with new bars (15 min)
const ROOM_MB = 1.5 * 1024;    // 8.13: the rule bot has room with >= 1.5 GB available ...
const ROOM_LOAD = 0.7;         // ... and a load under 0.7 x the CPUs
const UNKNOWN = "알 수 없음";

export async function mount(el, ctx) {
  ctx.setTitle("서버 상태");
  const top = h("section", {class: "card hero dl-stop", "aria-label": "엔진 상태"});
  const data = h("div", {class: "stack tight"}), procBox = h("div"), tg = h("div"), facts = h("div"), issues = h("div");
  const logout = h("form", {method: "post", action: "/logout", class: "row wrap dl-logout"},
    h("button", {class: "btn-line", type: "submit"}, "로그아웃"),
    h("span", {class: "muted"}, "로그아웃하면 다시 비밀번호를 넣어야 합니다."));
  const backupBox = h("div"), watchBox = h("div"), deadBox = h("div"), serverBox = h("div");
  el.append(ui.screenHead("서버 상태", "엔진이 제대로 도는지 (30초마다 새로 읽음)"), top,
    ui.card({plate: "서버 같이 쓰기 (규칙봇과 같은 서버)", sub: "데모 랩이 규칙봇의 자리를 빼앗지 않는지"}, serverBox),
    h("div", {class: "grid3"},
      ui.card({plate: "백업", sub: "매일 04:40 · 다시 만들 수 없는 기록만"}, backupBox),
      ui.card({plate: "바깥 감시", sub: "10분마다 따로 도는 감시"}, watchBox),
      ui.card({plate: "살아 있음 신호", sub: "서버가 통째로 멈춰도 밖에서 알림"}, deadBox)),
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
  // the backup and the outside watch: their own files (written by their own timers)
  async function loadSide() {
    let b, w;
    try { [b, w] = await Promise.all([ctx.api("/api/backup"), ctx.api("/api/watch")]); } catch (e) {
      if (e && e.name === "AbortError") return;
      put(backupBox, ui.errorBox(e, loadSide));
      return;
    }
    paintBackup(backupBox, b);
    paintWatch(watchBox, w);
  }
  loadSide();
  ctx.every(60000, loadSide);

  function paint(st) {
    last = st;
    if (!st || isMissing(st)) {
      put(top, h("p", {class: "dl-vbig warn"}, "준비 중"), ui.missing("엔진 상태 파일(status.json)"));
      for (const b of [data, procBox, tg, facts, issues, deadBox, serverBox]) put(b, ui.empty("준비 중"));
      return;
    }
    paintDead(deadBox, st.deadman);
    paintServer(serverBox, st.server);
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
        ui.stat("과거 자료 시작", st.history_start_ms ? fmt.mmdd(st.history_start_ms) : "—", "설정 순위 26주 창")));
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
      ["펀딩 (설정 순위)", cost.funding_8h_ranking != null ? `8시간마다 ${fmt.ratio(cost.funding_8h_ranking, 2)}` : "—"],
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

/** The one plain line of a side card: ok (green) or a problem (red), never colour alone. */
const verdictLine = (ok, text) => h("p", {class: ["dl-okline", ok == null ? "na" : ok ? "ok" : "bad"]},
  h("span", {class: "dl-okmk", "aria-hidden": "true"}, ok == null ? "?" : ok ? "✓" : "!"), text);
const kb = (bytes) => (fmt.bad(bytes) ? UNKNOWN : Number(bytes) >= 1048576 ? `${fmt.num(bytes / 1048576, 1)} MB` : `${fmt.num(bytes / 1024, 0)} KB`);
const hrsAgo = (ms) => (Date.now() - Number(ms)) / 3.6e6;

function paintBackup(box, b) {
  if (!b || isMissing(b)) { put(box, verdictLine(null, "준비 중: 아직 백업 기록(backup.json)이 없습니다."), ui.note("백업은 매일 새벽 04:40에 한 번 돕니다.")); return; }
  const fresh = b.last_ok_ms && hrsAgo(b.last_ok_ms) <= BACKUP_OK_H;
  const ok = !!fresh && !b.error_ko;
  const tables = b.tables && typeof b.tables === "object" ? Object.entries(b.tables) : [];
  put(box,
    verdictLine(ok, ok ? "백업 잘 되고 있음: 텔레그램으로 파일이 갔습니다."
      : b.error_ko ? `백업 문제: ${b.error_ko}` : b.last_ok_ms ? `백업 문제: ${BACKUP_OK_H}시간 넘게 성공한 백업이 없습니다.` : "백업 문제: 성공한 백업이 아직 없습니다."),
    ui.kv([
      ["마지막 성공", b.last_ok_ms ? `${fmt.kst(b.last_ok_ms)} (${fmt.ago(b.last_ok_ms)})` : "기록 없음"],
      ["마지막 시도", b.last_try_ms ? fmt.kst(b.last_try_ms) : "기록 없음"],
      ["크기", kb(b.bytes)],
      ["암호", b.encrypted == null ? UNKNOWN : b.encrypted ? "걸려 있음" : "안 걸림"],
    ]),
    tables.length ? h("p", {class: "note"}, "담은 것: " + tables.map(([k, n]) => `${k} ${fmt.int(n)}`).join(" · ")) : null);
}

function paintWatch(box, w) {
  if (!w || isMissing(w)) { put(box, verdictLine(null, "준비 중: 바깥 감시 기록(watch.json)이 아직 없습니다.")); return; }
  const stale = !w.checked_ms || (Date.now() - Number(w.checked_ms)) / 60000 > WATCH_OK_MIN;
  const items = Array.isArray(w.items) ? w.items : [];
  const bad = items.filter((x) => x && x.ok === false);
  const ok = !stale && w.ok !== false && !bad.length;
  put(box,
    verdictLine(ok, ok ? "바깥 감시: 모두 정상입니다."
      : stale ? `바깥 감시 문제: ${WATCH_OK_MIN}분 넘게 감시가 돌지 않았습니다 (마지막 ${w.checked_ms ? fmt.ago(w.checked_ms) : "기록 없음"}).`
        : `바깥 감시가 문제를 봤습니다: ${bad.map((x) => WATCH_KO[x.what] || x.what).join(", ") || "자세한 것 없음"}`),
    items.length ? h("div", {class: "dl-list"}, items.map((x) => h("div", {class: "dl-ev"},
      h("div", {class: "dl-evt"}, ui.mark(x.ok == null ? null : !!x.ok), h("b", null, WATCH_KO[x.what] || String(x.what ?? "—"))),
      x.detail_ko ? h("div", {class: "dl-evb muted"}, x.detail_ko) : null))) : ui.none(),
    h("p", {class: "note"}, w.checked_ms ? `마지막 감시 ${fmt.kst(w.checked_ms)} (${fmt.ago(w.checked_ms)})` : "마지막 감시: 기록 없음"));
}

function paintDead(box, d) {
  if (!d) { put(box, verdictLine(null, "준비 중: 엔진이 아직 이 정보를 쓰지 않습니다.")); return; }
  const fresh = d.last_ok_ms && (Date.now() - Number(d.last_ok_ms)) / 60000 <= DEAD_OK_MIN;
  const ok = d.configured ? !!fresh && !d.last_error : null;
  put(box,
    verdictLine(ok, d.configured === false ? "설정 안 됨: 서버가 통째로 멈추면 밖에서 알려 줄 장치가 없습니다."
      : ok ? "정상: 엔진이 15분마다 밖(healthchecks.io)에 \"살아 있음\"을 보내고 있습니다."
        : d.last_error ? `문제: 마지막 신호가 실패했습니다 (${d.last_error}).` : `문제: ${DEAD_OK_MIN}분 넘게 신호가 나가지 않았습니다.`),
    ui.kv([
      ["설정", d.configured == null ? UNKNOWN : d.configured ? "됨" : "안 됨"],
      ["마지막 신호", d.last_ok_ms ? `${fmt.kst(d.last_ok_ms)} (${fmt.ago(d.last_ok_ms)})` : "기록 없음"],
    ]),
    ui.note("신호가 끊기면 healthchecks.io가 두 분께 직접 알립니다 (이 서버가 꺼져 있어도)."));
}

const ACTIVE_KO = {active: "켜짐", inactive: "꺼짐", failed: "실패", activating: "켜는 중", deactivating: "끄는 중", reloading: "다시 읽는 중"};

function paintServer(box, sv) {
  if (!sv) { put(box, verdictLine(null, "준비 중: 엔진이 아직 서버 정보를 쓰지 않습니다.")); return; }
  const num = (x) => (x == null || !Number.isFinite(Number(x)) ? null : Number(x));
  const tot = num(sv.mem_total_mb), avail = num(sv.mem_avail_mb), cpus = num(sv.cpus);
  const loads = Array.isArray(sv.load) ? sv.load.map(num) : [];
  const load = loads[1] != null ? loads[1] : loads[0] != null ? loads[0] : null;      // the 5-minute average first
  const memOk = avail == null ? null : avail >= ROOM_MB;
  const loadOk = load == null || cpus == null || cpus <= 0 ? null : load < cpus * ROOM_LOAD;
  const room = memOk == null || loadOk == null ? null : memOk && loadOk;
  const bar = (frac, cls, label) => h("div", {class: ["dl-sbar", cls]}, h("div", {class: "g-bar"}, frac == null ? null
    : h("i", {style: {"--v": `${Math.max(0, Math.min(1, frac)) * 100}%`}})), h("span", {class: "muted"}, label));
  const units = Array.isArray(sv.rule_bot) ? sv.rule_bot : [];
  put(box,
    verdictLine(room, room == null ? `${UNKNOWN}: 메모리나 부하 값이 없습니다.` : room ? "규칙봇 여유 있음" : "여유가 줄었음: 개발자에게 화면 보내기"),
    h("div", {class: "grid2"},
      h("div", {class: ["gauge", memOk == null ? "none" : memOk ? "ok" : "bad"]},
        h("div", {class: "g-top"}, h("span", {class: "g-name"}, "남은 메모리"),
          h("span", {class: "g-st"}, memOk == null ? UNKNOWN : memOk ? "여유" : "모자람"),
          h("span", {class: "g-val"}, avail == null ? UNKNOWN : fmt.mb(avail), h("small", null, ` / 전체 ${tot == null ? UNKNOWN : fmt.mb(tot)}`))),
        bar(avail != null && tot ? avail / tot : null, "", `기준: 1.5 GB 이상 남아야 함${sv.swap_used_mb != null ? ` · 스왑 사용 ${fmt.mb(sv.swap_used_mb)}` : ""}`)),
      h("div", {class: ["gauge", loadOk == null ? "none" : loadOk ? "ok" : "bad"]},
        h("div", {class: "g-top"}, h("span", {class: "g-name"}, "부하 (5분 평균)"),
          h("span", {class: "g-st"}, loadOk == null ? UNKNOWN : loadOk ? "여유" : "바쁨"),
          h("span", {class: "g-val"}, load == null ? UNKNOWN : fmt.num(load, 2), h("small", null, ` / CPU ${cpus == null ? UNKNOWN : `${fmt.int(cpus)}개`}`))),
        bar(load != null && cpus ? load / cpus : null, "", `기준: CPU 수 × 0.7 미만 · 1·5·15분 ${loads.length ? loads.map((x) => (x == null ? "?" : fmt.num(x, 2))).join(" · ") : UNKNOWN}`))),
    h("p", {class: "dl-fk2"}, "규칙봇 서비스"),
    units.length ? ui.table([
      {label: "서비스", l: true, get: (u) => h("span", {class: "mono", title: String(u.unit ?? "")}, u.unit == null ? UNKNOWN : String(u.unit).replace(/\.service$/, ""))},
      {label: "상태", get: (u) => (u.active == null ? h("span", {class: "muted"}, UNKNOWN)
        : ui.pill(ACTIVE_KO[u.active] || String(u.active), u.active === "active" ? "good" : u.active === "failed" ? "bad" : "thin"))},
      {label: "메모리", get: (u) => (u.mem_mb == null ? h("span", {class: "muted"}, UNKNOWN) : fmt.mb(u.mem_mb))},
    ], units) : ui.none(`규칙봇 서비스: ${UNKNOWN}`),
    ui.note("데모 랩은 규칙봇과 같은 서버에서 돕니다. 남은 메모리가 1.5 GB 아래로 내려가거나 부하가 CPU 수의 70%를 넘으면 규칙봇이 느려질 수 있으니, 이 카드를 찍어 개발자에게 보내 주세요."));
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
