/* GH Coin 대시보드 수집기 (collector.js)
 *
 * ghcoin-dash 가 Chrome DevTools 의 Runtime.evaluate 로 GH Coin 앱 페이지 안에서 이 식(async 즉시 실행 함수) 하나를 실행한다.
 *
 * 규칙
 *  - 읽기 전용: 상태를 바꾸거나 주문·취소, 거래소 개인 API, AI 호출, 작업 실행을 하는 함수는 부르지 않는다.
 *    (쓰는 함수 목록: ask/cycle/work/observe/chatter/comboTick/comboScan/presentNow/setOffice/positionsFor/selfAIFor,
 *     live.status/dayPnl/positions/account/killSwitch, paper.step/addStrategy/setBookKey ... — 여기서는 전부 금지)
 *  - 앱 모듈은 앱과 똑같은 주소('/gh-coin/coin-office.js' 처럼 쿼리 없이)로만 import 한다 → 앱이 쓰는 같은 모듈 인스턴스.
 *  - 부팅 직후(30초)에는 아무 모듈도 건드리지 않는다 (paper.setBookKey 경쟁 상태 방지).
 *  - 비밀(키·토큰·지갑)은 절대 돌려주지 않는다. 마지막에 키 이름 필터 + 문자열 패턴 + '메모리 속 실제 비밀값' 대조로 한 번 더 지운다.
 *  - 모든 문자열은 LLM·뉴스·거래소에서 온 것일 수 있다 → 대시보드는 textContent 로만 그린다.
 *
 * 맨 끝의 /*OPT*\/{} 는 ghcoin-dash 가 {"slow":true,"reports":true} 처럼 바꿔 끼운다 (무거운 부분은 가끔만).
 * 오류가 나도 예외를 밖으로 던지지 않고 {ok:false, why} 로 돌려준다 (DevTools 쪽에 오류 객체가 쌓이지 않게).
 */
(async (OPT) => {
  "use strict";
  OPT = OPT || {};
  const now = Date.now(), up = Math.round(performance.now()), t0 = performance.now();
  const base = {version: 1, ts: now, uptimeMs: up};
  try {
  if (location.protocol === "chrome-error:") return {...base, ok: false, why: "error_page"};   // 실행기가 꺼져 있을 때 Chrome 이 띄운 오류 화면
  if (!/^\/gh-coin\//.test(location.pathname)) return {...base, ok: false, why: "not_gh_coin_page"};
  if (document.readyState !== "complete" || window.__ghReady !== true || up < 30000) return {...base, ok: false, booting: true};

  const errors = [], secs = [];
  const errMsg = e => String((e && e.message) || e || "오류").slice(0, 200);
  const run = async (name, ms, fn) => {
    secs.push(name);
    let tm = 0;
    try {
      return await Promise.race([Promise.resolve().then(fn), new Promise((_, rej) => { tm = setTimeout(() => rej(new Error(`시간 초과 (${ms}ms)`)), ms); })]);
    } catch (e) { errors.push({sec: name, msg: errMsg(e)}); return undefined; }
    finally { clearTimeout(tm); }
  };
  const mod = async u => { try { return await import(u); } catch (e) { errors.push({sec: "import", msg: u + ": " + errMsg(e)}); return null; } };
  const [O, P, L, E] = await Promise.all(["/gh-coin/coin-office.js", "/nuri-ai/paper.js", "/nuri-ai/live.js", "/nuri-ai/engine.js"].map(mod));
  if (!O || !P) return {...base, ok: false, why: "modules_unavailable", errors};

  /* ---------- 작은 도구 ---------- */
  const num = v => (v == null || v === "" || typeof v === "boolean" || !Number.isFinite(+v)) ? null : +v;
  const rnd = (v, d = 2) => { const n = num(v); return n == null ? null : Math.round(n * 10 ** d) / 10 ** d; };
  const px = v => { const n = num(v); return n == null ? null : +n.toPrecision(8); };
  const str = (v, n = 300) => { if (v == null) return ""; const s = String(v); return s.length > n ? s.slice(0, n) + "…" : s; };
  const lsJ = (k, d) => { try { const v = localStorage.getItem(k); if (!v) return d; const j = JSON.parse(v); return j == null ? d : j; } catch (e) { return d; } };
  const http = u => /^https?:\/\//i.test(String(u || "")) ? str(u, 300) : "";
  const agentOf = id => { try { return id ? O.agentById(id) || null : null; } catch (e) { return null; } };
  const teamOf = id => { try { return id ? O.teamById(id) || null : null; } catch (e) { return null; } };
  const who = id => { if (!id) return null; const a = agentOf(id), t = a ? teamOf(a.team) : null;
    return {id: str(id, 40), name: str(a ? a.name : id, 40), title: str(a ? a.title : "", 40), team: str(a ? a.team : "", 24), color: str(t ? t.color : "", 16)}; };
  const roomName = ch => str((teamOf(ch) || {}).name || ch, 40);
  const PLACE_KO = {meet: "대회의실", lounge: "라운지", stage: "발표 무대", board: "데모거래 현황판"};
  const placeName = p => p ? (PLACE_KO[p] || (teamOf(p) ? teamOf(p).name + " 구역" : str(p, 24))) : "";
  const compact = o => { for (const k of Object.keys(o)) if (o[k] === "" || o[k] === null || o[k] === undefined) delete o[k]; return o; };
  const grade = t => t == null ? "" : t >= 75 ? "A 매우 신뢰" : t >= 60 ? "B 신뢰" : t >= 45 ? "C 보통" : t >= 30 ? "D 주의" : "E 위험";
  const today = new Date(now).toLocaleDateString("sv-SE");
  const out = {};

  /* 실거래 설정 사본 (liveCfg 는 비밀키를 빼고 돌려준다; 그래도 여기서는 키 '있음/없음'만 꺼낸다) */
  let LC = {};
  try { LC = (L && L.liveCfg && L.liveCfg()) || {}; } catch (e) { errors.push({sec: "live", msg: errMsg(e)}); }
  const access = {};
  for (const [id, k] of Object.entries(LC.keys || {})) access[str(id, 24)] = !!(k && k.set);
  delete LC.keys;
  const linked = LC.linked && typeof LC.linked === "object" ? LC.linked : {};

  /* ---------- 1. 데모(모의투자) 장부: 전략 · 포지션 · 체결 ---------- */
  const book = await run("book", 2500, async () => {
    const bk = await P.loadBook(), all = Array.isArray(bk && bk.strategies) ? bk.strategies : [];
    const promo = lsJ("coinPromoted", {}) || {};
    const act = all.filter(s => s && s.status === "active"), old = all.filter(s => s && s.status !== "active");
    const winOf = t => (t.pnl ?? t.roe ?? 0) > 0;
    const strategies = act.map(s => {
      const tr = Array.isArray(s.trades) ? s.trades : [], n = tr.length, eqA = Array.isArray(s.equity) ? s.equity : [];
      const eq = num(P.equityOf(s)) ?? 10000, wins = tr.filter(winOf).length, ret = (eq / 10000 - 1) * 100, wr = n ? wins / n * 100 : 0;
      const oos = s.wf && s.wf.oos ? s.wf.oos : null;
      let trust = null; try { trust = num(O.trustScore({ret: +ret.toFixed(2), wr: +wr.toFixed(1), pf: oos ? oos.pf ?? null : null, n, robust: s.robust, crossCoin: s.crossCoin})); } catch (e) {}
      let gate = null;
      try { if (L && L.gateFor){ const g = L.gateFor(s, now); gate = {eligible: !!g.eligible, checks: (g.checks || []).map(c => ({id: str(c.id, 16), name: str(c.name, 40), ok: !!c.ok, text: str(c.text, 40), need: str(c.need, 40)}))}; } } catch (e) {}
      let peak = -Infinity, mdd = 0; for (const p of eqA){ const v = +p.v; if (!(v > 0)) continue; peak = Math.max(peak, v); mdd = Math.max(mdd, (1 - v / peak) * 100); }
      const k = Math.max(1, Math.ceil(eqA.length / 60));
      return compact({id: str(s.id, 40), name: str(s.name, 80), market: str(s.mname || s.market, 30), sym: str(s.market, 20), tf: str(s.tf, 6), lane: s.lane === "custom" ? "custom" : "std",
        author: str(s.author, 30), created: num(s.created), days: s.created ? Math.floor((now - s.created) / 864e5) : null,
        lev: num(s.spec && s.spec.risk && s.spec.risk.leverage), equity: rnd(eq), retPct: rnd(ret), pnl: rnd(eq - 10000), cash: rnd(s.cash),
        trades: n, wins, winRate: n ? rnd(wr, 1) : null, mdd: rnd(mdd, 1), trust, grade: grade(trust), live: !!(linked[s.id] && linked[s.id].on), cand: !!promo[s.id], gate,
        oos: oos ? compact({ret: rnd(oos.ret), dd: rnd(oos.dd), win: rnd(oos.win), pf: rnd(oos.pf), n: num(oos.n)}) : null,
        holding: s.pos ? (s.pos.side === "short" ? "short" : "long") : "",
        lastSig: s.lastSignal ? compact({action: str(s.lastSignal.action, 16), why: str(s.lastSignal.why, 200), t: num(s.lastSignal.t)}) : null,
        curve: eqA.filter((_, i) => i % k === 0 || i === eqA.length - 1).map(p => [num(p.t), rnd(p.v)])});
    }).sort((a, b) => (b.retPct ?? 0) - (a.retPct ?? 0));
    const positions = act.filter(s => s.pos).map(s => {
      const p = s.pos, mk = s.mark || {}, unreal = num(mk.unreal), margin = num(p.margin);
      return compact({sid: str(s.id, 40), name: str(s.name, 80), market: str(s.mname || s.market, 30), sym: str(s.market, 20), tf: str(s.tf, 6),
        side: p.side === "short" ? "short" : "long", entry: px(p.entry), mark: px(mk.price), markT: num(mk.t), unreal: rnd(unreal),
        roe: unreal != null && margin ? rnd(unreal / margin * 100) : null, margin: rnd(margin), notional: rnd(p.notional), lev: num(p.lev),
        sl: px(p.sl), tp: px(p.tp), liq: px(p.liq), trail: px(p.trail), t: num(p.t)});
    });
    const trades = act.flatMap(s => (Array.isArray(s.trades) ? s.trades : []).slice(-30).map(x => compact({sid: str(s.id, 40), name: str(s.name, 80), market: str(s.mname || s.market, 30),
      side: x.side === "short" ? "short" : "long", entryT: num(x.entryT), entryP: px(x.entryP), exitT: num(x.exitT), exitP: px(x.exitP), pnl: rnd(x.pnl), roe: rnd(x.roe), reason: str(x.reason, 30)})))
      .sort((a, b) => (b.exitT || 0) - (a.exitT || 0)).slice(0, 40);
    const retired = old.slice(-20).reverse().map(s => { const eq = num(P.equityOf(s)) ?? 10000;
      return compact({id: str(s.id, 40), name: str(s.name, 80), market: str(s.mname || s.market, 30), tf: str(s.tf, 6), lane: s.lane === "custom" ? "custom" : "std",
        retPct: rnd((eq / 10000 - 1) * 100), trades: Array.isArray(s.trades) ? s.trades.length : 0, why: str(s.retiredWhy, 80), created: num(s.created)}); });
    const allTr = act.flatMap(s => Array.isArray(s.trades) ? s.trades : []), totPnl = strategies.reduce((a, s) => a + (s.pnl || 0), 0);
    const demo = {nActive: act.length, nRetired: old.length, updated: num(bk && bk.updated), totalEquity: rnd(strategies.reduce((a, s) => a + (s.equity || 0), 0)),
      totalPnl: rnd(totPnl), totalRetPct: act.length ? rnd(totPnl / (act.length * 10000) * 100) : 0, trades: allTr.length,
      winRate: allTr.length ? rnd(allTr.filter(winOf).length / allTr.length * 100, 1) : null, open: positions.length,
      longs: positions.filter(p => p.side === "long").length, shorts: positions.filter(p => p.side === "short").length,
      unreal: rnd(positions.reduce((a, p) => a + (p.unreal || 0), 0)),
      best: strategies[0] ? {name: strategies[0].name, retPct: strategies[0].retPct} : null,
      worst: strategies.length ? {name: strategies.at(-1).name, retPct: strategies.at(-1).retPct} : null,
      cand: strategies.filter(s => s.cand && !s.live).length, live: strategies.filter(s => s.live).length};
    return {strategies, positions, trades, retired, demo, marks: Object.fromEntries(act.filter(s => s.mark).map(s => [s.id, px(s.mark.price)]))};
  });

  /* ---------- 2. 사무실: 지금 상태 · 회의 · 말하는 사람 ---------- */
  out.office = await run("office", 1500, async () => {
    const s = O.officeState(), m = s.running, cs = O.cycleState(), c = O.officeCfg(), u = O.officeUsage() || {};
    const log = await O.loadLog();
    let cur = null;
    if (m) for (let i = log.length - 1; i >= 0; i--){ const e = log[i]; if (e.meeting === m.id && e.kind === "agent"){ cur = e; break; } }
    const st = cur && Array.isArray(cur.steps) && cur.steps.length ? cur.steps.at(-1) : null;
    const q = sel => { const el = document.querySelector(sel); return el ? str(el.textContent.replace(/\s+/g, " ").trim(), 300) : ""; };
    const jobNow = [...document.querySelectorAll("#ofStatus .of-jobnow")].map(el => el.textContent.trim()).join(" · ");
    const AG = O.AGENDA || [], ai = AG.length ? (+localStorage.getItem("coinAgenda") || 0) % AG.length : 0, na = AG[ai];
    // 남은 시간 대신 '그 시각'을 보낸다 → 읽을 때마다 값이 바뀌지 않아 대시보드가 다시 그리지 않음 (0 = 이미 지남/곧)
    const at = ms => { const n = num(ms); return n == null ? null : n > 0 ? Math.round((Date.now() + n) / 1000) * 1000 : 0; };
    return {
      mode: m ? "meeting" : c.auto ? "auto" : "idle", modeKo: m ? "회의 중" : c.auto ? "자동 운영" : "대기",
      meeting: m ? {id: str(m.id, 40), name: str(m.name, 60), room: str(m.room, 24), roomName: roomName(m.room), trigger: str(m.trigger, 10), topic: str(m.topic, 300),
        place: placeName(m.place || "meet"), t: num(m.t), deadline: num(m.deadline),
        order: (m.order || []).map(id => ({...who(id), done: (m.done || []).includes(id)})), done: (m.done || []).length, total: (m.order || []).length} : null,
      speaker: cur ? {...who(cur.agent), live: !!cur.live, text: str(String(cur.text || "").slice(-400), 400), tool: str(st && st.act, 60), toolStatus: str(st && st.status, 10)} : null,
      queued: num(s.queued) || 0, cycling: !!cs.cycling, lastJob: str(cs.lastJob, 24), jobNow: str(jobNow, 200), chatting: !!O.isChatting(),
      nextCycleAt: at(O.nextCycleIn()), nextAutoAt: at(O.nextAutoIn()), nextChatAt: at(O.nextChatIn()), pausedUntil: at(O.officePaused()),
      nextAgenda: na ? {id: str(na.id, 24), title: str(na.title, 60), room: str(na.room, 24), roomName: roomName(na.room)} : null,
      usage: {day: str(u.day, 12), meetings: num(u.meetings) || 0, auto: num(u.auto) || 0, calls: num(u.calls) || 0, chats: num(u.chats) || 0, trained: num(u.trained) || 0},
      cfg: {auto: !!c.auto, every: num(c.every), dailyMax: num(c.dailyMax), chat: c.chat !== false, chatEvery: num(c.chatEvery), chatMax: num(c.chatMax),
        cycle: c.cycle !== false, cycleMin: num(c.cycleMin), callMax: num(c.callMax), combo: c.combo !== false, claudeMode: str(O.claudeMode(), 8)},
      ui: {title: q("#ofTitle")}
    };
  });

  /* ---------- 3. 직원 활동 (사무실 화면의 말풍선·위치를 읽기만) ---------- */
  out.staff = await run("staff", 1500, () => {
    const Lay = window.__officeUI && window.__officeUI.layout, Z = Lay && Lay.ZONES ? Object.entries(Lay.ZONES) : [], HOME = (Lay && Lay.HOME) || {};
    const zoneAt = (x, y) => { for (const [id, z] of Z) if (x >= z.x && x <= z.x + z.w && y >= z.y && y <= z.y + z.h) return id; return ""; };
    const els = document.querySelectorAll("#office .of-ag"), list = [];
    for (const el of els){
      const id = el.dataset.ag, b = el.querySelector(".of-bub"), x = parseFloat(el.style.left), y = parseFloat(el.style.top), h = HOME[id];
      const bubble = b && !b.hidden ? b.textContent.replace(/\s+/g, " ").trim() : "", sn = ((O.seen && O.seen[id]) || [])[0] || null;
      const atDesk = h && Number.isFinite(x) ? Math.hypot(x - h.x, y - h.y) < 4 : true, talking = el.classList.contains("talk"), walking = el.classList.contains("walk");
      const fresh = sn && now - (+sn.t || 0) < 600e3;
      if (!bubble && atDesk && !talking && !walking && !fresh) continue;
      const zone = Number.isFinite(x) ? zoneAt(x, y) : "";
      list.push(compact({...who(id), bubble: str(bubble, 160), talking, walking, atDesk, zone: str(zone, 24), zoneName: placeName(zone),
        seen: fresh ? compact({icon: str(sn.icon, 8), kind: str(sn.kind, 12), text: str(sn.text, 160), src: str(sn.src, 60), url: http(sn.url), t: num(sn.t)}) : null}));
    }
    const rank = a => (a.talking ? 0 : a.bubble ? 1 : a.walking ? 2 : 3);
    list.sort((a, b) => rank(a) - rank(b));
    const by = {}; for (const a of list) if (a.zone) by[a.zone] = (by[a.zone] || 0) + 1;
    const off = document.querySelector("#office");
    return {total: (O.AGENTS || []).length, teams: (O.TEAMS || []).length, onScreen: els.length, officeVisible: !!off && !off.hidden,
      counts: {active: list.length, talking: list.filter(a => a.talking).length, walking: list.filter(a => a.walking).length, bubbles: list.filter(a => a.bubble).length,
        meet: by.meet || 0, lounge: by.lounge || 0, stage: by.stage || 0},
      zones: Object.entries(by).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([z, n]) => ({zone: str(z, 24), name: placeName(z), n})),
      active: list.slice(0, 60)};
  });

  /* ---------- 4. 회의록 · 활동 피드 (최근 40개, 최신 먼저) ---------- */
  out.feed = await run("feed", 1500, async () => {
    const log = await O.loadLog(), N = Math.min(120, Math.max(10, num(OPT.feedN) || 40));
    return log.slice(-N).reverse().map(e => {
      const a = e.kind === "user" ? null : who(e.agent), ch = e.ch || "hq";
      const x = compact({id: str(e.id, 40), t: num(e.t), room: str(ch, 24), roomName: roomName(ch), kind: str(e.kind, 16),
        author: e.kind === "user" ? "나" : a ? a.name : "", authorTitle: a ? a.title : "", color: a ? a.color : "",
        chat: e.chat ? true : null, live: e.live ? true : null, meeting: e.meeting ? true : null,
        text: str(e.text, 400), head: str(e.title || e.name, 160), icon: str(e.icon, 8), model: e.model ? str(String(e.model).split("/").pop(), 40) : "",
        tool: Array.isArray(e.steps) && e.steps.length ? str(e.steps.at(-1).act, 60) : "", url: http(e.url), src: str(e.src, 60),
        status: str(e.status, 12), level: str(e.level, 8), market: str(e.mname || e.market, 30), tf: str(e.tf, 6), note: str(e.note, 200)});
      if (e.pass != null) x.ok = !!e.pass;
      if (e.oos && typeof e.oos === "object") x.oos = compact({ret: rnd(e.oos.ret), dd: rnd(e.oos.dd), win: rnd(e.oos.win), pf: rnd(e.oos.pf), n: num(e.oos.n)});
      if (Array.isArray(e.cols) && Array.isArray(e.rows)) x.table = {cols: e.cols.slice(0, 6).map(c => str(c, 30)),
        rows: e.rows.slice(0, 6).map(r => (Array.isArray(r) ? r : []).slice(0, 6).map(c => str(c, 60))), more: Math.max(0, e.rows.length - 6)};
      return x;
    });
  });

  /* ---------- 5. 실시간 종합 지표 타점판 (앱의 60초 루프가 만든 결과만 읽음) ---------- */
  const combo = await run("combo", 1500, () => {
    const B = O.comboBoard() || {}, coinsMap = B.coins || {}, f3 = v => rnd(v, 3);
    const lv = x => x ? {price: px(x.price), names: (x.names || []).slice(0, 3).map(n => str(n, 40))} : null;
    const coins = (O.COINS || []).map(c => coinsMap[c.id]).filter(Boolean).map(x => { const p = x.plan || {};
      return {id: str(x.id, 8), ko: str(x.ko, 20), sym: str(x.sym, 20), t: num(x.t), n: num(x.n), syncWarn: !!(x.sync && x.sync.warn),
        plan: compact({state: str(p.state, 12), side: num(p.side), why: str(p.why, 160), conf: num(p.conf), price: px(p.price), entry: px(p.entry), sl: px(p.sl), tp1: px(p.tp1), tp2: px(p.tp2),
          rr: rnd(p.rr), big: f3(p.big), small: f3(p.small), regime: str(p.regime && p.regime.label, 20), sup: lv(p.sup), res: lv(p.res)}),
        tf: Object.fromEntries(Object.entries(x.tf || {}).map(([k, v]) => [str(k, 4), {score: f3(v.score), up: num(v.up), dn: num(v.dn), flat: num(v.flat), regime: str(v.regime, 20),
          fresh: (v.fresh || []).slice(0, 4).map(q => ({name: str(q.name, 30), dir: num(q.dir)}))}])),
        tv: Object.fromEntries(Object.entries(x.tv || {}).map(([k, v]) => [str(k, 4), {label: str(v.label, 12), all: f3(v.all)}]))}; });
    const all = Array.isArray(B.calls) ? B.calls : [], done = all.filter(c => c.result), win = done.filter(c => (c.r || 0) > 0).length;
    const calls = all.slice(-40).reverse().map(c => compact({id: str(c.id, 40), coin: str(c.coin, 8), ko: str(c.ko, 20), side: num(c.side), entry: px(c.entry), sl: px(c.sl), tp1: px(c.tp1), tp2: px(c.tp2),
      conf: num(c.conf), why: str(c.why, 120), t: num(c.t), result: str(c.result, 8), r: rnd(c.r), end: num(c.end)}));
    return {coins, info: {t: num(B.t), running: !!B.running, err: str(B.err, 200)}, calls,
      stats: {n: all.length, open: all.length - done.length, done: done.length, win, rate: done.length ? Math.round(win / done.length * 100) : null, sumR: rnd(done.reduce((s, c) => s + (+c.r || 0), 0))}};
  });

  /* ---------- 6. 실거래 (설정·하루 손익·포지션 기록·승인 대기 창) — 거래소에 묻지 않고 저장된 값만 ---------- */
  out.live = await run("live", 1500, () => {
    const lim = LC.limits || {}, h = LC.halted || null;
    const dr = lsJ("nuri:live:day", null), d = dr && dr.day === today ? dr : {day: today, usdt: 0, krw: 0, exUsdt: null};
    const local = num(d.usdt) || 0, ex = num(d.exUsdt), dayUsdt = ex == null ? local : Math.min(local, ex), dayKrw = num(d.krw) || 0;
    const marks = (book && book.marks) || {};
    const pos = lsJ("nuri:live:pos", {}) || {};
    const positions = Object.entries(pos).filter(([, p]) => p && typeof p === "object").map(([sid, p]) => compact({sid: str(sid, 40), name: str(p.name, 80), ex: str(p.ex, 16), env: str(p.env, 10),
      symbol: str(p.symbol, 24), side: p.side === "short" ? "short" : "long", qty: num(p.qty), entry: px(p.entry), lev: num(p.lev), sl: px(p.sl), tp: px(p.tp), krw: num(p.krw), t: num(p.t), paperMark: marks[sid] ?? null}));
    const FIELDS = ["전략", "거래소", "종목", "방향", "수량", "현재가", "주문 금액", "레버리지", "손절", "익절", "미실현 손익", "전략의 근거", "주의"];
    const items = [...document.querySelectorAll(".lv-modal > .lv-dlg:not(.lv-guide-dlg)")].filter(dl => dl.querySelector("table.lv-kv")).map(dl => {
      const f = [];
      dl.querySelectorAll("table.lv-kv tr").forEach(tr => { const k = tr.querySelector("th"), v = tr.querySelector("td"), kt = k ? k.textContent.trim() : "";
        if (FIELDS.includes(kt)) f.push([kt, str(v ? v.textContent.replace(/\s+/g, " ").trim() : "", 200)]); });
      const bar = dl.querySelector(".lv-cd i");
      return {title: str((dl.querySelector(".lv-dlg-h b") || {}).textContent, 40), mainnet: dl.classList.contains("real"),
        countdown: str((dl.querySelector(".lv-left") || {}).textContent, 40), remainingPct: bar ? rnd(parseFloat(bar.style.width) || 0, 0) : null, fields: f};
    });
    const dailyLoss = num(lim.dailyLoss) ?? 20, krwDailyLoss = num(lim.krwDailyLoss) ?? 30000;
    const state = h ? "HALTED" : (-dayUsdt >= dailyLoss || -dayKrw >= krwDailyLoss) ? "REDUCING" : "ACTIVE";
    return {enabled: LC.enabled === true, env: LC.env === "mainnet" ? "mainnet" : "testnet", mode: LC.mode === "auto" ? "auto" : "approve",
      marginType: LC.marginType === "CROSSED" ? "CROSSED" : "ISOLATED", state, halted: h ? {why: str(h.why, 200), t: num(h.t)} : null,
      dayPnl: {day: str(d.day, 12), usdt: rnd(dayUsdt), krw: rnd(dayKrw, 0), local: rnd(local), exchange: rnd(ex)},
      limits: {orderNotional: num(lim.orderNotional), maxNotional: num(lim.maxNotional), maxTotalNotional: num(lim.maxTotalNotional), maxLeverage: num(lim.maxLeverage),
        maxPositions: num(lim.maxPositions), dailyLoss, krwOrderNotional: num(lim.krwOrderNotional), krwMaxNotional: num(lim.krwMaxNotional), krwDailyLoss,
        symbols: Array.isArray(lim.symbols) ? lim.symbols.slice(0, 20).map(s => str(s, 20)) : []},
      exchangeAccess: access,
      linked: Object.entries(linked).filter(([, v]) => v && v.on).map(([sid, v]) => compact({sid: str(sid, 40), name: str(v.name, 80), market: str(v.market, 24), exchange: str(v.exchange, 16), t: num(v.t), notional: num(v.notional)})),
      positions, pendingApprovals: {count: items.length, items}};
  });

  out.sentiment = await run("sentiment", 500, () => { const s = O.marketSentiment(); return s ? {score: num(s.score), verdict: str(s.verdict, 20), n: num(s.n), t: num(s.t)} : null; });

  /* ---------- 가끔만 (무거운 것): 감사 기록 · 파이프라인 · 예측 적중률 · 투자위원회 · 성장 과제 · 모델 · 팀 목록 ---------- */
  if (OPT.slow){
    out.audit = await run("audit", 2500, () => {
      if (!L || !L.auditLog) return null;
      const A = L.auditLog() || [], dayStart = new Date(new Date(now).toDateString()).getTime(), td = A.filter(e => (+e.t || 0) >= dayStart);
      const cnt = k => td.filter(e => e.kind === k).length;
      const proj = e => compact({t: num(e.t), kind: str(e.kind, 12), env: str(e.env, 10), sname: str(e.sname, 80), ex: str(e.ex, 16), symbol: str(e.symbol, 24), side: str(e.side, 8),
        qty: e.qty == null ? "" : str(e.qty, 24), price: px(e.price), notional: rnd(e.notional), lev: num(e.lev), status: str(e.status, 16), msg: str(e.msg, 300)});
      let kill = null; for (let i = A.length - 1; i >= 0; i--) if (A[i].kind === "kill"){ kill = proj(A[i]); break; }
      return {total: A.length, today: {all: td.length, order: cnt("order"), block: cnt("block"), approval: cnt("approval"), error: cnt("error"), decision: cnt("decision")},
        lastKill: kill, items: A.slice(-40).reverse().map(proj)};
    });
    out.pipeline = await run("pipeline", 2000, async () => {
      const p = await O.pipeline(), lane = x => x ? {dev: num(x.dev) || 0, ok: num(x.pass) || 0, fail: num(x.fail) || 0, demo: Array.isArray(x.demo) ? x.demo.length : 0,
        cand: num(x.cand) || 0, live: num(x.live) || 0, retired: num(x.retired) || 0,
        recent: (x.recent || []).slice(0, 6).map(r => compact({name: str(r.name, 60), market: str(r.mname || r.market, 24), tf: str(r.tf, 6), ok: !!r.pass, oos: rnd(r.oos), t: num(r.t)}))} : null;
      return {std: lane(p && p.std), custom: lane(p && p.custom)};
    });
    out.predict = await run("predict", 2000, async () => {
      const T = await import("/gh-coin/lib/track.js");
      const ro = {get: (k, d) => lsJ(k, d), set: () => {}};          // set 은 아무것도 안 함 → 절대 쓰지 않음
      const tr = T.makeTracker(ro), st = tr.stats() || {};
      return {n: num(st.n) || 0, hits: num(st.hits) || 0, winRate: num(st.winRate), open: num(st.open) || 0, avgEdge: num(st.avgEdge),
        bands: (st.bands || []).map(b => ({band: str(b.band, 12), n: num(b.n) || 0, rate: num(b.rate), avgConf: num(b.avgConf)})),
        bySource: (tr.bySource() || []).slice(0, 8).map(s => ({source: str(s.source, 16), n: num(s.n), winRate: num(s.winRate)})),
        recent: tr.recent(10).map(d => compact({source: str(d.source, 16), ko: str(d.ko || d.coin, 20), dir: num(d.dir), confidence: num(d.confidence), move: rnd(d.move), hit: !!d.hit, t: num(d.t)}))};
    });
    out.ic = await run("ic", 1500, () => {
      const Lg = O.icLedger() || [], res = Lg.filter(d => d.status === "resolved"), hits = res.filter(d => d.hit).length;
      return {n: Lg.length, pending: Lg.filter(d => d.status === "pending").length, resolved: res.length, hits, hitRate: res.length ? Math.round(hits / res.length * 100) : null,
        avgAlpha: res.length ? rnd(res.reduce((s, d) => s + (+d.alpha || 0), 0) / res.length) : null,
        recent: Lg.slice(-8).reverse().map(d => compact({ko: str(d.ko || d.coin, 20), t: num(d.t), due: num(d.due), rating: str(d.rating, 12), rmRating: str(d.rmRating, 12),
          entry: px(d.entry), stop: px(d.stop), status: str(d.status, 10), hit: d.hit == null ? null : !!d.hit, raw: rnd(d.raw), alpha: rnd(d.alpha), why: str(d.why, 300)}))};
    });
    out.growth = await run("growth", 2500, async () => {
      const bl = O.backlog() || [];
      const notes = [], NT = lsJ("coinNotes", {}) || {};          // O.teamNotes(id) 와 같은 값 (한 번만 읽음)
      for (const t of (O.TEAMS || [])) for (const n of (Array.isArray(NT[t.id]) ? NT[t.id] : []).slice(-3)) notes.push(compact({team: str(t.id, 24), teamName: str(t.name, 40), t: num(n.t), text: str(n.text, 200), src: str(n.src, 20)}));
      notes.sort((a, b) => (b.t || 0) - (a.t || 0));
      let skills = [], board = [];
      try { skills = (await O.learnedSkills(8)).map(x => compact({text: str(x.text, 200), job: str(x.job, 16), uses: num(x.uses), conf: rnd(x.conf), t: num(x.t)})); } catch (e) {}
      try { board = (await O.researchBoard(8)).map(f => compact({t: num(f.t), job: str(f.job, 16), target: str(f.targetName, 30), kind: str(f.kind, 8), text: str(f.text, 200)})); } catch (e) {}
      return {counts: {todo: bl.filter(x => x.status === "todo").length, doing: bl.filter(x => x.status === "doing").length, done: bl.filter(x => x.status === "done").length},
        backlog: bl.slice(-15).reverse().map(x => compact({team: str(x.team, 24), teamName: roomName(x.team), title: str(x.title, 120), why: str(x.why, 160), status: str(x.status, 8),
          owner: (who(x.owner) || {}).name || "", t: num(x.t), done: num(x.done), result: str(x.result, 200)})),
        notes: notes.slice(0, 10), skills, board};
    });
    out.models = await run("models", 500, () => Object.entries(O.modelHealth() || {}).slice(0, 30).map(([m, v]) => ({model: str(m, 60), ok: num(v.ok) || 0, slow: num(v.slow) || 0, fail: num(v.fail) || 0, t: num(v.t)})));
    out.teams = await run("teams", 500, () => (O.TEAMS || []).map(t => ({id: str(t.id, 24), name: str(t.name, 40), color: str(t.color, 16)})));
  }
  if (OPT.reports){
    out.report = await run("report", 4000, async () => {
      // O.listReports() 는 지금까지의 발표를 전부 읽는다(지우지 않으므로 계속 늘어남) → 최신 3개와 개수만 직접 읽기 (읽기 전용 트랜잭션)
      // 키 = "coinreport:" + Date.now().toString(36) + … 이라 키 순서 = 시간 순서
      if (!indexedDB.databases || !(await indexedDB.databases()).some(d => d.name === "nuri-ai")) return {count: 0, latest: null};   // 앱 DB 를 새로 만들지 않음
      const db = await new Promise((res, rej) => { const r = indexedDB.open("nuri-ai"); r.onupgradeneeded = () => r.transaction.abort(); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); r.onblocked = () => rej(new Error("blocked")); });
      let count = 0, R = [];
      try {
        if (!db.objectStoreNames.contains("kv")) return {count: 0, latest: null};
        const os = db.transaction("kv", "readonly").objectStore("kv"), rg = IDBKeyRange.bound("coinreport:", "coinreport:\uffff");
        const cq = os.count(rg);
        const cur = new Promise((res, rej) => { const c = os.openCursor(rg, "prev"); c.onsuccess = () => { const x = c.result; if (x && R.length < 3){ R.push(x.value); x.continue(); } else res(); }; c.onerror = () => rej(c.error); });
        count = await new Promise((res, rej) => { cq.onsuccess = () => res(cq.result); cq.onerror = () => rej(cq.error); });
        await cur;
      } finally { db.close(); }
      const x = R.filter(v => v && typeof v === "object").sort((a, b) => (+b.t || 0) - (+a.t || 0))[0];
      return {count, latest: x ? {t: num(x.t), since: num(x.since), title: str(x.title, 80), text: str(x.text, 2500),
        sections: (x.sections || []).slice(0, 12).map(s => ({name: str(s.name, 40), lead: str(s.lead, 20), items: (s.items || []).slice(0, 6).map(i => str(i, 160)), next: (s.next || []).slice(0, 3).map(i => str(i, 120))}))} : null};
    });
  }

  /* ---------- 요약 ---------- */
  const lv = out.live || {}, of = out.office || {}, cb = combo || {};
  const snap = {
    ...base, ok: true, slow: !!OPT.slow,
    page: {url: str(location.origin + location.pathname, 80), title: str(document.title, 40), visibility: document.visibilityState},
    summary: {
      demo: book ? book.demo : null,
      office: {mode: of.mode || "", modeKo: of.modeKo || "", meeting: of.meeting ? `#${of.meeting.name} · ${of.meeting.done}/${of.meeting.total} 발언` : "",
        jobNow: of.jobNow || "", lastJob: of.lastJob || "", pausedUntil: of.pausedUntil || 0, usage: of.usage || null},
      live: {enabled: !!lv.enabled, env: lv.env || "", mode: lv.mode || "", state: lv.state || "", halted: !!lv.halted, dayUsdt: lv.dayPnl ? lv.dayPnl.usdt : null,
        dailyLoss: lv.limits ? lv.limits.dailyLoss : null, pending: lv.pendingApprovals ? lv.pendingApprovals.count : 0, positions: (lv.positions || []).length, linked: (lv.linked || []).length},
      combo: cb.stats || null, sentiment: out.sentiment || null
    },
    positions: book ? book.positions : [], trades: book ? book.trades : [], strategies: book ? book.strategies : [], retired: book ? book.retired : [],
    signals: cb.coins || [], combo: cb.coins ? {...cb.info, stats: cb.stats, calls: cb.calls} : null,
    ...out
  };

  /* ---------- 비밀 지우기 (마지막 안전장치) ---------- */
  // 1) 메모리 속 실제 비밀값 목록 (돌려주지 않고, 결과에 섞여 있으면 지우는 데만 씀)
  const SECRETS = [];
  const addS = v => { if (typeof v === "string"){ const s = v.trim(); if (s.length >= 8){ SECRETS.push(s); if (s.length >= 20){ SECRETS.push(s.slice(0, 12), s.slice(-12)); } } } };
  try { const S = (E && E.settings) || {};
    for (const v of Object.values(S.keys || {})) addS(v);
    addS(S.nvKey); addS(S.customApi && S.customApi.key);
    for (const k of Object.values((S.live && S.live.keys) || {})) if (k && typeof k === "object") for (const v of Object.values(k)) addS(v);
  } catch (e) {}
  try { addS(window.__NURI_TOKEN); } catch (e) {}
  const SEC_PAT = [
    [/…[A-Za-z0-9_\-]{2,8}/g, "…****"],
    [/\b(?:nvapi-|sk-(?:ant-|or-|proj-)?|gsk_|tvly-|csk-|xai-|hf_|pplx-|AIza|ghp_|github_pat_|glpat-|BSA)[A-Za-z0-9_\-]{8,}/g, "[가림]"],
    [/eyJ[\w-]{6,}\.[\w-]{6,}\.[\w-]{6,}/g, "[가림]"],
    [/\bBearer\s+[\w\-.~+\/=]{8,}/gi, "Bearer [가림]"],
    [/\b(?:0x)?[0-9a-fA-F]{40,}\b/g, "[가림]"],
    [/[A-Za-z0-9_\-+\/=]{32,}/g, m => (/[A-Z]/.test(m) && /[a-z]/.test(m) && /[0-9]/.test(m)) ? "[가림]" : m]
  ];
  let red = 0;
  const cleanS = s => { let o = s; for (const x of SECRETS) if (o.includes(x)){ o = o.split(x).join("[가림]"); red++; }
    for (const [re, to] of SEC_PAT){ const n = o.replace(re, to); if (n !== o){ o = n; red++; } } return o; };
  const BAD = /key|secret|token|pass|jwt|sign|seed|mnemonic|private/i, ALLOW0 = new Set(["signals"]);
  const scrub = (v, d) => {
    if (d > 14) return null;
    if (typeof v === "string") return cleanS(v);
    if (typeof v === "number") return Number.isFinite(v) ? v : null;
    if (v == null || typeof v !== "object") return v === undefined ? null : v;
    if (Array.isArray(v)) return v.map(x => scrub(x, d + 1));
    const o = {};
    for (const [k, x] of Object.entries(v)){ if (BAD.test(k) && !(d === 0 && ALLOW0.has(k))){ red++; continue; } o[k] = scrub(x, d + 1); }
    return o;
  };
  snap.errors = errors; snap.secs = secs; snap.tookMs = Math.round(performance.now() - t0);
  const clean = scrub(snap, 0);
  clean.redactions = red;
  return clean;
  } catch (e) {
    return {...base, ok: false, why: "collector: " + String((e && e.name) || "Error").slice(0, 30) + ": " + String((e && e.message) || e).slice(0, 160)};
  }
})(/*OPT*/{});
