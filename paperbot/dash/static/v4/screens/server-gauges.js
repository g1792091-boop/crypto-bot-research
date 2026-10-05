// 서버·비용 (builder E): the gauges of mockup screen 08. Real sources only:
//   signal time  /api/status signals_24h (+ limits)        AI calls / tokens  /api/agents/usage
//   debate spend /api/debate spend (only once it has run)  CPU, memory, disk, DB size, Telegram: NOT sent yet -> 수집 전
// Each gauge keeps its DOM (server-kit liveGauge): the bar slides and the number counts only when a real value changes.
import {h, ui, fmt} from "../core/pb.js";
import {liveGauge, secHead, sigByTf, limitsOf, limitFor} from "./server-kit.js";

// NEEDS SERVER #4 (CONTRACT.md §6): GET /api/v4/server. server.js probes it once per visit (a 404 stops the polling)
// and the gauges below read {cpu: {pct, cores}, mem: {used_mb, total_mb}, disk: {used_gb, total_gb}, db: {paper3_mb,
// agents3_mb, daily3_mb, growth_mb_day}, signal_time: [{tf, bar_close, max_delay_ms, limit_ms}], telegram: {today,
// week}}. Until the route answers every one of these shows 수집 전.

const usd = fmt.usd;
const gb = (v) => `${fmt.num(v, 1)} GB`;

function section(title, sub) {
  const box = h("div", {class: "server-gauges"});
  const el = h("section", {class: "server-gsec", "aria-label": title}, secHead(title, sub), box);
  const map = new Map();
  /** get-or-create the gauge `key` (named `name`), in the order given by `order` keys when present. */
  el.g = (key, name) => {
    let g = map.get(key);
    if (!g) { g = liveGauge(name); map.set(key, g); box.append(g); }
    return g;
  };
  el.keep = (keys) => {
    for (const [k, g] of map) if (!keys.includes(k)) { g.remove(); map.delete(k); }
    for (const k of keys) if (map.has(k)) box.append(map.get(k));      // keep the given order (moves, never rebuilds)
  };
  el.box = box;
  return el;
}

export function gaugeBoard(ctx) {
  const srv = section("서버");
  const sig = section("신호 계산", "봉이 닫힌 뒤 신호를 다 계산하기까지");
  const db = section("데이터베이스");
  const ai = section("AI와 비용");
  const tg = section("알림");
  for (const [k, n] of [["calls", "AI 호출 오늘"], ["tokens", "토큰 오늘"], ["week", "AI 호출 7일"], ["debate", "24시간 토론방 이번 달"]]) ai.g(k, n);
  const classes = h("div", {class: "server-gauges"});
  const classesWrap = ui.disclosure("AI 쓰임새 종류별로 보기", classes);
  ai.append(classesWrap);
  const el = h("div", {class: "server-gboard"}, srv, sig, db, ai, tg,
    h("p", {class: "assume server-gcap"}, "막대의 가는 선은 60%와 85% 경계 · 수집 전 = 서버가 아직 보내지 않는 값 (만든 숫자를 넣지 않음)"));

  // ---------------------------------------------------------------- server machine (NEEDS SERVER #4)
  const setServer = (v) => {
    const cpu = v && v.cpu, mem = v && v.mem, disk = v && v.disk;
    srv.g("cpu", "CPU").set({value: cpu ? cpu.pct : null, ratio: cpu ? cpu.pct / 100 : null, fmt: (x) => `${fmt.num(x, 0)}%`,
      capText: cpu && cpu.cores ? `· ${fmt.int(cpu.cores)}코어` : "", mean: "서버 계산 능력을 얼마나 쓰는지입니다. 봉이 닫히는 순간에 잠깐 오릅니다."});
    srv.g("mem", "메모리").set({value: mem ? mem.used_mb / 1024 : null, cap: mem ? mem.total_mb / 1024 : null, fmt: (x) => fmt.num(x, 1),
      capText: mem ? `/ ${fmt.num(mem.total_mb / 1024, 1)} GB` : "", mean: "봇·대시보드·에이전트가 함께 쓰는 메모리입니다. 85%를 넘으면 빨강입니다."});
    srv.g("disk", "디스크").set({value: disk ? disk.used_gb : null, cap: disk ? disk.total_gb : null, fmt: (x) => fmt.num(x, 0),
      capText: disk ? `/ ${gb(disk.total_gb)}` : "", mean: "데이터베이스와 백업이 차지하는 공간입니다."});
    const d = v && v.db;
    const total = d ? (d.paper3_mb || 0) + (d.agents3_mb || 0) + (d.daily3_mb || 0) : null;
    db.g("size", "크기").set({value: total != null ? total / 1024 : null, fmt: (x) => `${fmt.num(x, 2)} GB`, state: "ok",
      capText: d && d.growth_mb_day != null ? `· 하루 +${fmt.num(d.growth_mb_day, 0)} MB` : "", mean: "거래·신호·회의 기록이 쌓이는 파일 크기와 하루 증가량입니다."});
    const t = v && v.telegram;
    tg.g("tg", "텔레그램 오늘").set({value: t ? t.today : null, fmt: (x) => `${fmt.int(x)}건`, state: "ok",
      capText: t && t.week != null ? `· 7일 ${fmt.int(t.week)}건` : "", mean: "두 분께 보낸 메시지 수입니다. 서버에 보낸 횟수 기록이 아직 없습니다."});
  };
  setServer(null);

  // ---------------------------------------------------------------- signal time per timeframe vs its limit
  const setSignals = (status, v) => {
    const lim = limitsOf(status);
    const rows = sigByTf(status && status.signals_24h);
    const keys = [];
    for (const r of rows) {
      const cap = limitFor(r.tf, lim);
      keys.push(r.tf);
      sig.g(r.tf, `${fmt.tfKo(r.tf)}봉 · 평균`).set({value: r.avg == null ? null : r.avg / 1000, cap: cap / 1000, fmt: (x) => `${fmt.num(x, 1)}초`,
        capText: `/ 한도 ${fmt.int(cap / 1000)}초`,
        mean: [`지난 24시간 신호 ${fmt.int(r.n)}개`, r.late ? h("span", {class: "warn-t"}, ` · 한도를 넘겨 들어가지 않은 신호 ${fmt.int(r.late)}개`) : " · 늦은 신호 없음"]});
    }
    // the worst boundary per timeframe: only /api/v4/server sends it (NEEDS SERVER #4)
    const worst = (v && v.signal_time) || [];
    for (const w of worst) {
      keys.push("max-" + w.tf);
      sig.g("max-" + w.tf, `${fmt.tfKo(w.tf)}봉 · 가장 늦은 마감`).set({value: w.max_delay_ms / 1000, cap: w.limit_ms / 1000,
        fmt: (x) => `${fmt.num(x, 1)}초`, capText: `/ 한도 ${fmt.int(w.limit_ms / 1000)}초`, mean: `${fmt.kst(w.bar_close)} 마감`});
    }
    if (!worst.length) {
      keys.push("max");
      sig.g("max", "마감별 가장 늦은 신호").set({value: null, mean: "마감마다 가장 늦게 끝난 신호 시간은 서버가 아직 보내지 않습니다. 위 평균은 24시간 기록에서 셉니다."});
    }
    if (!rows.length && status) {
      keys.unshift("none");
      sig.g("none", "최근 24시간").set({value: null, mean: "지난 24시간 동안 신호가 없었습니다."});
    }
    sig.keep(keys);
  };

  // ---------------------------------------------------------------- AI calls and tokens vs the caps (agents3.db)
  const setUsage = (u) => {
    if (!u) return;
    ai.g("calls", "AI 호출 오늘").set({value: u.calls, cap: u.cap_calls, fmt: (x) => fmt.int(x), capText: u.cap_calls ? `/ ${fmt.int(u.cap_calls)}회` : "회",
      mean: "직원들이 AI를 부른 횟수입니다. 한도에 닿으면 그날 회의는 멈춥니다."});
    ai.g("tokens", "토큰 오늘").set({value: u.tokens, cap: u.cap_tokens, fmt: (x) => fmt.compact(x), capText: u.cap_tokens ? `/ ${fmt.compact(u.cap_tokens)}` : "",
      mean: "AI가 읽고 쓴 글의 양입니다."});
    const w = u.week;
    if (w) ai.g("week", "AI 호출 7일").set({value: w.calls, cap: w.cap_calls, fmt: (x) => fmt.int(x),
      capText: `${w.cap_calls ? `/ ${fmt.int(w.cap_calls)}회` : "회"} · 토큰 ${fmt.compact(w.tokens)}${w.cap_tokens ? ` / ${fmt.compact(w.cap_tokens)}` : ""}`,
      mean: `${w.since ? `${w.since.slice(5).replace("-", "/")}부터 ` : ""}한 주 한도입니다. 두 분의 Claude Max 구독 안에서 쓰므로 호출마다 돈이 더 나가지 않습니다.`});
    const cl = (u.classes || []).filter((c) => c && typeof c === "object");
    const have = new Set();
    for (const c of cl) {
      have.add(c.class);
      let g = classes.querySelector(`[data-k="${CSS.escape(String(c.class))}"]`);
      if (!g) { g = liveGauge(c.name_ko || c.class); g.dataset.k = String(c.class); classes.append(g); }
      g.set({value: c.calls, cap: c.cap_calls, fmt: (x) => fmt.int(x), capText: c.cap_calls ? `/ ${fmt.int(c.cap_calls)}회` : "회",
        mean: `토큰 ${fmt.compact(c.tokens)}${c.cap_tokens ? ` / ${fmt.compact(c.cap_tokens)}` : ""}${c.failed ? ` · 답을 못 받은 호출 ${fmt.int(c.failed)}번` : ""}`});
    }
    for (const g of [...classes.children]) if (!have.has(g.dataset.k)) g.remove();
    classesWrap.hidden = !cl.length;
    if (u.caps_source === "defaults") classesWrap.title = "한도는 기본값입니다 (agents.env에 따로 정하지 않음)";
  };

  // ---------------------------------------------------------------- 24-hour debate room: real money (paid API)
  const setDebate = (d, on) => {
    const g = ai.g("debate", "24시간 토론방 이번 달");
    const sp = d && d.spend;
    if (!on) g.set({value: 0, off: "꺼짐", fmt: () => "0", mean: "토론방이 아직 돌아간 적이 없어 쓴 돈이 없습니다. 켜지면 이번 달 쓴 돈과 한도가 여기 나옵니다."});
    else if (!sp) g.set({value: null, mean: `토론방 상태: ${d && d.state_ko ? d.state_ko : "읽는 중"}`});
    else g.set({value: sp.month, cap: sp.cap, fmt: usd, capText: sp.cap ? `/ ${usd(sp.cap)}` : "",
      mean: [`실제 돈 (유료 API, 모의 돈과 별개)${sp.day != null ? ` · 오늘 ${usd(sp.day)}` : ""}`, d.state_ko ? ` · 지금 ${d.state_ko}` : "",
        ". 한도에 닿으면 그달은 멈춥니다."]});
  };

  el.setServer = setServer;
  el.setSignals = setSignals;
  el.setUsage = setUsage;
  el.setDebate = setDebate;
  return el;
}
