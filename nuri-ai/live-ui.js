// 실거래 (내 계좌) 화면 + 주문 승인 창
// - openLive(ctx): 전체 화면 패널 (환경 · 키 · 한도 · 모드 · 승격된 전략 연결 · 계좌/포지션 · 긴급 정지 · 감사 기록)
// - 이 파일을 불러오기만 해도 승인 창(setApprover)이 등록된다. 승인 모드에서 승인 창이 없으면 주문이 나가지 않는다.
import * as Live from "./live.js";

let ctx = {toast: m => console.log(m), esc: null, md: null};
let root = null, unsub = null, timer = null, acct = null, acctBusy = false;
const esc = s => ctx.esc ? ctx.esc(s) : String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const toast = m => { try { ctx.toast(m); } catch(e){ console.log(m); } };
const fmt = (n, d = 2) => n == null || !Number.isFinite(+n) ? "-" : Number(n).toLocaleString("ko-KR", {maximumFractionDigits: d});
const sideKo = (side, kind) => kind === "close" ? (side === "long" ? "롱 청산 (매도)" : "숏 청산 (매수)") : side === "long" ? "롱 (매수)" : "숏 (매도)";
const envKo = env => env === "mainnet" ? "실거래(메인넷)" : "테스트넷";

function cssOnce(){
  if (typeof document === "undefined" || document.querySelector("link[data-live-css]")) return;
  const l = document.createElement("link"); l.rel = "stylesheet"; l.href = new URL("./live.css", import.meta.url).href; l.dataset.liveCss = "1";
  document.head.appendChild(l);
}
// 앱 시작 때 한 번 불러 두면(패널을 열지 않아도) 승인 창이 준비된다
export function initLive(c){ if (c) ctx = {...ctx, ...c}; cssOnce(); Live.setApprover(approveDialog); }
if (typeof document !== "undefined") initLive();

/* ============ 주문 승인 창 (60초 후 자동 취소) ============ */
export function approveDialog(p, {signal, ms = Live.APPROVAL_MS} = {}){
  cssOnce();
  return new Promise(resolve => {
    const quote = p.quote || "USDT", end = Date.now() + ms;
    const m = document.createElement("div");
    m.className = "lv-modal"; m.setAttribute("role", "dialog"); m.setAttribute("aria-modal", "true");
    const row = (k, v, cls = "") => v == null || v === "" ? "" : `<tr${cls ? ` class="${cls}"` : ""}><th>${k}</th><td>${v}</td></tr>`;
    m.innerHTML = `<div class="lv-dlg ${p.env === "mainnet" ? "real" : ""}">
      <div class="lv-dlg-h"><b>${p.kind === "close" ? "실거래 청산 승인" : "실거래 주문 승인"}</b><span class="lv-pill ${p.env === "mainnet" ? "bad" : "ok"}">${envKo(p.env)}</span></div>
      <table class="lv-kv">
        ${row("전략", esc(p.strategy))}
        ${row("거래소", esc(p.exName || p.ex))}
        ${row("종목", `<b>${esc(p.symbol)}</b>`)}
        ${row("방향", `<b class="${p.side === "long" ? "up" : "dn"}">${sideKo(p.side, p.kind)}</b>${p.reduceOnly ? " · reduce-only" : ""}`)}
        ${row("수량", esc(p.qty))}
        ${row("현재가", fmt(p.price, 8))}
        ${row("주문 금액", `<b>${fmt(p.notional)} ${quote}</b>`)}
        ${p.ex === "binancef" ? row("레버리지", `${esc(p.lev)}배${p.margin ? ` · 증거금 약 ${fmt(p.margin)} USDT` : ""}${p.marginType ? ` · ${p.marginType === "ISOLATED" ? "격리" : "교차"}` : ""}`) : ""}
        ${p.kind === "open" ? row("손절", p.sl ? fmt(p.sl, 8) : "<i>없음</i>") : ""}
        ${p.kind === "open" ? row("익절", p.tp ? fmt(p.tp, 8) : "<i>없음</i>") : ""}
        ${p.upnl != null ? row("미실현 손익", `${fmt(p.upnl)} USDT`) : ""}
        ${row("전략의 근거", esc(p.why || "-"), "why")}
        ${p.warn ? row("주의", esc(p.warn), "warn") : ""}
      </table>
      <div class="lv-cd"><i></i></div>
      <div class="lv-dlg-f"><span class="lv-left"></span><button class="lv-btn" data-a="no">거절</button><button class="lv-btn ${p.env === "mainnet" ? "danger" : "primary"}" data-a="yes">승인</button></div>
    </div>`;
    document.body.appendChild(m);
    const bar = m.querySelector(".lv-cd i"), left = m.querySelector(".lv-left");
    let done = false;
    const finish = v => { if (done) return; done = true; clearInterval(iv); signal?.removeEventListener?.("abort", onAbort); document.removeEventListener("keydown", onKey); m.remove(); resolve(v); };
    const tick = () => { const s = Math.max(0, end - Date.now()); left.textContent = `${Math.ceil(s / 1000)}초 뒤 자동 취소`; bar.style.width = (s / ms * 100) + "%"; if (s <= 0) finish(false); };
    const onAbort = () => { finish(false); toast("주문 승인 시간이 지나 취소했습니다"); };
    const onKey = e => { if (e.key === "Escape") finish(false); };
    const iv = setInterval(tick, 250); tick();
    signal?.addEventListener?.("abort", onAbort);
    document.addEventListener("keydown", onKey);
    m.querySelector('[data-a="no"]').onclick = () => finish(false);
    m.querySelector('[data-a="yes"]').onclick = () => finish(true);
    m.querySelector('[data-a="no"]').focus();     // 실수로 Enter를 눌러도 거절
    try { if (document.hidden && "Notification" in window && Notification.permission === "granted") new Notification("실거래 주문 승인 요청", {body: `${p.strategy} · ${p.symbol} ${sideKo(p.side, p.kind)} · ${fmt(p.notional)} ${quote}`}); } catch(e){}
  });
}

/* ============ 실전 연결 안내 (단계별 가이드) ============ */
const GUIDE_STEPS = [
  {t: "1. 먼저 테스트넷에서 (가짜 돈)", d: "환경은 기본이 테스트넷입니다. testnet.binancefuture.com 에서 로그인해 API 키를 받으면 가짜 USDT로 똑같이 연습할 수 있습니다. 실거래는 테스트넷에서 충분히 돌려 본 뒤에만 켜세요."},
  {t: "2. 거래 전용 API 키 만들기", d: "거래소 API 관리에서 <b>'선물 거래' 권한만</b> 켜고 <b>출금 권한은 반드시 끄세요</b>. 가능하면 <b>IP 제한(화이트리스트)</b>을 걸고, 실거래 전용 <b>하위(서브) 계정</b>에 쓸 만큼만 넣어 두길 권합니다. 키는 이 브라우저에만 저장되고 비밀키는 서명에만 쓰여 어디로도 전송·기록되지 않습니다. 공용 PC에서는 쓰지 마세요."},
  {t: "3. 전략을 관문에 통과시키기", d: `아무 전략이나 실거래로 못 나갑니다. 모의투자에서 <b>${Live.GATE.days}일 이상 · 청산 거래 ${Live.GATE.trades}회 이상 · 손익비 ${Live.GATE.pf} 이상 · 수익률 0% 초과 · 최대 낙폭 ${Live.GATE.mdd}% 미만</b>을 스스로 증명한 전략만 '5. 승격' 목록에서 연결됩니다.`},
  {t: "4. 한도·레버리지·마진 정하기", d: "'3. 한도'에서 1회 주문 금액·1회 최대 금액·최대 레버리지·동시 포지션 수·하루 손실 한도·허용 종목을 정합니다. <b>레버리지는 낮을수록 안전</b>하고(반대로 조금만 움직여도 청산), 마진은 <b>격리</b>를 권합니다(손실이 그 포지션 증거금으로 한정). 이 한도를 넘는 주문은 모두 막고 기록합니다."},
  {t: "5. 관문 통과 전략을 연결", d: "'5. 모의투자 → 실거래 승격'에서 통과한 전략의 스위치를 켜면 그 전략의 모의투자 신호가 실제 주문 후보가 됩니다. 시장은 바이낸스 USDT-M 선물·업비트 KRW 현물만 지원합니다."},
  {t: "6. 실거래 켜기 — 승인 모드부터", d: "맨 위 스위치로 실거래를 켭니다. 기본은 <b>승인 모드</b>: 주문마다 종목·방향·수량·금액·레버리지·손절/익절·근거를 보여 주는 창이 뜨고, <b>60초 안에 승인</b>하지 않으면 자동 취소됩니다. 익숙해지기 전엔 자동 모드를 켜지 마세요."},
  {t: "7. 실거래(메인넷)로 전환할 때", d: `진짜 돈으로 바꾸려면 환경을 메인넷으로 바꾸며 확인 문구 '<b>${Live.MAINNET_PHRASE}</b>'를 직접 입력해야 합니다. 환경을 바꾸면 실거래가 꺼지고 승인 모드로 되돌아갑니다. <b>처음엔 가장 작은 금액</b>으로 시작하세요.`},
  {t: "8. 문제가 생기면 — 모두 정지·청산", d: "오른쪽 위 <b>'모두 정지·청산'</b>은 미체결 주문을 취소하고 모든 포지션을 시장가(reduce-only)로 닫은 뒤 실거래를 끕니다. 하루 실현 손실 한도에 닿으면 그날은 새 진입이 자동으로 멈춥니다. 모든 판단·주문은 감사 기록에 남고 CSV로 내보낼 수 있습니다."}
];
export function guideDialog(){
  cssOnce();
  const m = document.createElement("div");
  m.className = "lv-modal"; m.setAttribute("role", "dialog"); m.setAttribute("aria-modal", "true");
  m.innerHTML = `<div class="lv-dlg lv-guide-dlg">
    <div class="lv-dlg-h"><b>📘 실전 연결 안내</b><span class="lv-pill">테스트넷 → 실거래 순서</span></div>
    <p class="lv-dim">실제 돈을 넣기 전에 이 순서대로 하세요. 손실은 모두 본인 책임이고, 과거 성과가 미래 수익을 보장하지 않습니다.</p>
    <ol class="lv-steps">${GUIDE_STEPS.map(s => `<li><b>${esc(s.t)}</b><p>${s.d}</p></li>`).join("")}</ol>
    <div class="lv-dlg-f"><span class="lv-left"></span><button class="lv-btn primary" data-a="ok">알겠습니다</button></div></div>`;
  document.body.appendChild(m);
  const finish = () => { document.removeEventListener("keydown", onKey); m.remove(); };
  const onKey = e => { if (e.key === "Escape") finish(); };
  m.addEventListener("click", e => { if (e.target === m || e.target.closest('[data-a="ok"]')) finish(); });
  document.addEventListener("keydown", onKey);
  m.querySelector('[data-a="ok"]').focus();
}

/* ============ 패널 ============ */
export function openLive(c){
  initLive(c);
  if (!root){
    root = document.createElement("div"); root.className = "lv"; root.setAttribute("role", "dialog"); root.setAttribute("aria-label", "실거래 (내 계좌)");
    document.body.appendChild(root);
    root.addEventListener("click", onClick); root.addEventListener("change", onChange); root.addEventListener("input", onInput);
  }
  root.hidden = false; document.body.classList.add("lv-open");
  render();
  unsub?.(); unsub = Live.onLiveChange(() => { clearTimeout(timer); timer = setTimeout(() => { renderStatus(); renderLog(); renderStrategies(); }, 150); });
  refreshAccount();
}
export function closeLive(){ if (root) root.hidden = true; document.body.classList.remove("lv-open"); unsub?.(); unsub = null; }
export const liveOpen = () => !!root && !root.hidden;
const $ = sel => root.querySelector(sel);

function render(){
  const c = Live.liveCfg();
  root.innerHTML = `<header class="lv-top">
      <b class="lv-title">실거래 <small>(내 계좌)</small></b><span id="lvPills" class="lv-pills"></span><span class="lv-sp"></span>
      <button class="lv-btn" data-act="guide" title="테스트넷부터 실거래까지, 순서대로 안내">📘 실전 연결 안내</button>
      <button class="lv-btn danger" data-act="kill" title="미체결 주문 취소 + 모든 포지션 시장가 청산 + 실거래 끄기">모두 정지·청산</button>
      <button class="lv-x" data-act="close" aria-label="닫기">✕</button></header>
    <div class="lv-body">
      <section class="lv-card lv-wide lv-warnbox">
        <div class="lv-row"><label class="lv-switch"><input type="checkbox" id="lvOn" ${c.enabled ? "checked" : ""}><span></span></label>
          <div><b>실거래 ${c.enabled ? "켜짐" : "꺼짐"}</b><div class="lv-dim" id="lvSummary"></div></div></div>
        <details ${c.enabled ? "" : "open"}><summary>원칙 — 꼭 읽어 주세요</summary><ol class="lv-rules">${Live.PRINCIPLES.map(p => `<li>${esc(p)}</li>`).join("")}</ol></details>
      </section>
      <section class="lv-card"><h3>1. 환경</h3><div id="lvEnv"></div></section>
      <section class="lv-card"><h3>2. API 키 <small>이 브라우저에만 저장</small></h3><div id="lvKeys"></div></section>
      <section class="lv-card"><h3>3. 한도</h3><div id="lvLimits"></div></section>
      <section class="lv-card"><h3>4. 모드</h3><div id="lvMode"></div></section>
      <section class="lv-card lv-wide"><h3>5. 모의투자 → 실거래 승격 <small>관문을 통과한 전략만 연결</small></h3><div id="lvStrats" class="lv-strats"><div class="lv-dim">불러오는 중…</div></div></section>
      <section class="lv-card lv-wide"><h3>계좌 · 포지션 <button class="lv-btn sm" data-act="refresh">새로고침</button></h3><div id="lvAcct" class="lv-dim">-</div></section>
      <section class="lv-card lv-wide"><h3>감사 기록 <button class="lv-btn sm" data-act="csv">CSV 내보내기</button></h3><div id="lvLog" class="lv-logwrap"></div></section>
    </div>`;
  renderStatus(); renderEnv(); renderKeys(); renderLimits(); renderMode(); renderStrategies(); renderLog();
}

function renderStatus(){
  if (!root) return;
  const st = Live.status(), c = Live.liveCfg(), d = st.day;
  $("#lvPills").innerHTML = `<span class="lv-pill ${st.enabled ? (st.env === "mainnet" ? "bad" : "ok") : ""}">${st.enabled ? "켜짐" : "꺼짐"}</span>
    <span class="lv-pill ${st.env === "mainnet" ? "bad" : "ok"}">${envKo(st.env)}</span><span class="lv-pill ${st.mode === "auto" ? "warn" : ""}">${st.mode === "auto" ? "자동 모드" : "승인 모드"}</span>
    ${st.halted ? `<span class="lv-pill bad" title="${esc(st.halted.why)}">오늘 정지</span>` : ""}`;
  const on = $("#lvOn"); if (on) on.checked = st.enabled;
  const L = c.limits;
  $("#lvSummary").innerHTML = `연결된 전략 ${st.linked}개 · 1회 ${fmt(L.orderNotional)} USDT(최대 ${fmt(L.maxNotional)}) · 레버리지 ≤ ${L.maxLeverage}배 · 포지션 ≤ ${L.maxPositions}개 · 오늘 실현 ${fmt(d.usdt)} USDT${d.krw ? ` / ${fmt(d.krw, 0)}원` : ""} (한도 -${fmt(L.dailyLoss)})
    ${st.halted ? `<br><b class="bad">자동 정지: ${esc(st.halted.why)}</b>` : ""}${st.lastError ? `<br><span class="bad">최근 오류: ${esc(st.lastError.msg)}</span>` : ""}
    ${!st.launcher ? `<br><span class="warn">웹 버전에서는 브라우저 보안정책(CORS) 때문에 거래소 연결이 막힐 수 있습니다. GHNano.exe로 실행하면 안전하게 중계합니다.</span>` : ""}`;
}

function renderEnv(){
  const c = Live.liveCfg();
  $("#lvEnv").innerHTML = `<div class="lv-seg"><label><input type="radio" name="lvEnv" value="testnet" ${c.env === "testnet" ? "checked" : ""}> 테스트넷 <small>가짜 돈 · 기본</small></label>
      <label><input type="radio" name="lvEnv" value="mainnet" ${c.env === "mainnet" ? "checked" : ""}> 실거래(메인넷) <small>진짜 돈</small></label></div>
    <div id="lvEnvConfirm" class="lv-confirm" hidden><p>실제 돈으로 주문합니다. 손실은 모두 본인 책임입니다. 계속하려면 아래 문구를 그대로 입력하세요:<br><b>${esc(Live.MAINNET_PHRASE)}</b></p>
      <input id="lvEnvPhrase" autocomplete="off" placeholder="${esc(Live.MAINNET_PHRASE)}"><button class="lv-btn danger" data-act="env-main">실거래로 전환</button> <button class="lv-btn" data-act="env-cancel">취소</button></div>
    <p class="lv-dim">바이낸스 USDT-M 선물: ${c.env === "mainnet" ? "fapi.binance.com" : "testnet.binancefuture.com"} · 업비트 KRW 현물은 테스트넷이 없어 실거래 환경에서만 주문합니다(롱만).<br>환경을 바꾸면 실거래가 꺼지고 승인 모드로 돌아갑니다.</p>`;
}

function keyRow(id, label, hintHtml){
  const k = Live.liveCfg().keys[id], up = id === "upbit";
  return `<div class="lv-key" data-key="${id}"><div class="lv-key-h"><b>${label}</b>${k?.set ? `<span class="lv-pill ok">저장됨 ${esc(k.hint)}</span> <button class="lv-btn sm" data-act="key-del" data-id="${id}">삭제</button>` : `<span class="lv-pill">없음</span>`}</div>
    ${k?.set ? "" : `<div class="lv-grid2"><input data-f="key" placeholder="${up ? "Access key" : "API Key"}" autocomplete="off" spellcheck="false"><input data-f="secret" type="password" placeholder="${up ? "Secret key" : "Secret Key"}" autocomplete="new-password" spellcheck="false"></div>
    <button class="lv-btn sm primary" data-act="key-save" data-id="${id}">저장</button> <small class="lv-dim">${hintHtml}</small>`}</div>`;
}
function renderKeys(){
  $("#lvKeys").innerHTML = `${keyRow("binancef_test", "바이낸스 선물 테스트넷", `testnet.binancefuture.com에서 로그인 → API Key 발급 (가짜 USDT가 들어 있음)`)}
    ${keyRow("binancef", "바이낸스 선물 실거래", "API 관리 → '선물 거래' 권한만 켜고 출금은 끄기, IP 제한 걸기")}
    ${keyRow("upbit", "업비트 (선택)", "Open API 관리 → '자산 조회 · 주문하기'만, 출금 권한 끄기, 허용 IP 등록")}
    <ul class="lv-guide"><li><b>출금 권한 없는 거래 전용 키</b>를 만드세요. 이 앱은 출금 기능이 없지만, 키가 새면 출금 권한이 가장 위험합니다.</li>
      <li><b>IP 제한(화이트리스트)</b>을 거세요. GHNano.exe 중계를 써도 요청은 이 PC의 공인 IP에서 나갑니다.</li>
      <li>실거래 전용 <b>하위 계정(서브 계정)</b>에 쓸 만큼만 넣어 두는 것을 권합니다. 긴급 정지는 그 계정의 모든 선물 포지션을 닫습니다.</li>
      <li>키는 이 브라우저(앱 설정, localStorage)에만 저장됩니다. 비밀키는 브라우저 안에서 서명(WebCrypto HMAC)에만 쓰이고 서버·AI·기록으로 보내지 않습니다. <b>공용 PC에서는 쓰지 마세요.</b></li></ul>
    <button class="lv-btn sm" data-act="test">연결 확인 (잔고 조회)</button>`;
}

// 레버리지 ↔ 청산까지 대략적인 역방향 거리(%) : 격리, 유지증거금 약 0.5% 어림
const liqMovePct = lev => lev >= 1 ? Math.max(0, (1 / lev - 0.005) * 100) : 0;
function levHintText(lev){
  const d = liqMovePct(lev);
  return `레버리지 ${lev}배 → 반대로 약 ${d.toFixed(d < 1 ? 2 : 1)}%만 움직여도 청산 근처 · 손익이 ${lev}배로 커집니다`;
}
function renderLimits(){
  const c = Live.liveCfg(), L = c.limits, mt = c.marginType === "CROSSED" ? "CROSSED" : "ISOLATED";
  const f = (k, label, step = "any", note = "") => `<label class="lv-f"><span>${label}</span><input type="number" data-lim="${k}" value="${esc(L[k])}" step="${step}" min="0">${note ? `<small>${note}</small>` : ""}</label>`;
  $("#lvLimits").innerHTML = `<div class="lv-grid2">
      ${f("orderNotional", "1회 주문 금액 (USDT)")}${f("maxNotional", "1회 최대 금액 (USDT)")}
      <label class="lv-f"><span>최대 레버리지 (배)</span><input type="number" id="lvLevInput" data-lim="maxLeverage" value="${esc(L.maxLeverage)}" step="1" min="1" max="125"><small id="lvLevHint" class="${L.maxLeverage > 5 ? "warn" : ""}">${esc(levHintText(L.maxLeverage))}</small></label>
      ${f("maxPositions", "동시 포지션 수", 1)}
      ${f("dailyLoss", "하루 실현 손실 한도 (USDT)", "any", "닿으면 그날 신규 진입 정지")}${f("krwDailyLoss", "업비트 하루 손실 한도 (원)", 1000)}
      ${f("krwOrderNotional", "업비트 1회 주문 (원)", 1000)}${f("krwMaxNotional", "업비트 1회 최대 (원)", 1000)}</div>
    <div class="lv-f"><span>마진 방식 <small>바이낸스 선물</small></span>
      <div class="lv-seg lv-margin"><label><input type="radio" name="lvMargin" value="ISOLATED" ${mt === "ISOLATED" ? "checked" : ""}> 격리 <small>이 포지션 증거금만 잃음 · 권장</small></label>
        <label><input type="radio" name="lvMargin" value="CROSSED" ${mt === "CROSSED" ? "checked" : ""}> 교차 <small>계좌 잔고 전체가 증거금 · 위험</small></label></div></div>
    <label class="lv-f"><span>허용 종목 (쉼표로 구분)</span><input data-lim="symbols" value="${esc(L.symbols.join(", "))}" spellcheck="false"></label>
    <button class="lv-btn sm primary" data-act="limits">한도 저장</button>
    <p class="lv-dim">전략마다 정한 레버리지가 이 '최대 레버리지'보다 크면 주문을 막습니다. 레버리지는 낮을수록 안전하고, 격리 마진은 손실을 그 포지션 증거금으로 한정합니다. 거래소 최소 주문 단위 때문에 1회 최대 금액을 넘게 되면(예: BTCUSDT 최소 100 USDT) 주문을 막습니다. 한도를 넘는 주문은 모두 막고 기록합니다.</p>`;
}

function renderMode(){
  const c = Live.liveCfg();
  $("#lvMode").innerHTML = `<div class="lv-seg"><label><input type="radio" name="lvMode" value="approve" ${c.mode === "approve" ? "checked" : ""}> 승인 모드 <small>기본 · 주문마다 확인</small></label>
      <label><input type="radio" name="lvMode" value="auto" ${c.mode === "auto" ? "checked" : ""}> 자동 모드 <small>확인 없이 실행</small></label></div>
    <div id="lvModeConfirm" class="lv-confirm" hidden><p>자동 모드에서는 승인 창 없이 전략 신호대로 주문합니다(한도는 그대로 지킴). 아래 문구를 그대로 입력하세요:<br><b>${esc(Live.AUTO_PHRASE)}</b></p>
      <input id="lvModePhrase" autocomplete="off" placeholder="${esc(Live.AUTO_PHRASE)}"><button class="lv-btn danger" data-act="mode-auto">자동 모드 켜기</button> <button class="lv-btn" data-act="mode-cancel">취소</button></div>
    <p class="lv-dim">승인 창은 종목·방향·수량·금액·레버리지·손절/익절·전략의 근거를 보여 주고, 60초 안에 승인하지 않으면 취소합니다. 승인하지 않은 진입은 나가지 않고, 승인하지 않은 청산은 거래소에 걸어 둔 손절·익절 주문이 대신 지킵니다.</p>`;
}

let stratBusy = false;
async function renderStrategies(){
  if (!root || stratBusy) return; stratBusy = true;
  try {
    const P = await import("./paper.js"), book = await P.loadBook(), c = Live.liveCfg(), st = Live.status(), L = c.limits;
    const list = [...(book.strategies || [])].sort((a, b) => (b.status === "active") - (a.status === "active") || Live.gateFor(b).checks.filter(x => x.ok).length - Live.gateFor(a).checks.filter(x => x.ok).length);
    const el = $("#lvStrats"); if (!el) return;
    if (!list.length){ el.innerHTML = `<div class="lv-dim">모의투자 중인 전략이 없습니다. 퀀트 연구소가 검증한 전략이 모의투자에서 ${Live.GATE.days}일 이상 성과를 내면 여기서 연결할 수 있습니다.</div>`; return; }
    el.innerHTML = list.map(s => {
      const g = Live.gateFor(s), linked = !!c.linked[s.id]?.on, sup = !!Live.SUPPORTED[s.exchange], lev = +s.spec?.risk?.leverage || 3, lp = st.livePositions[s.id];
      const warns = [];
      if (!sup) warns.push("이 시장은 실거래 미지원 (바이낸스 선물·업비트만)");
      if (s.exchange === "binancef" && lev > L.maxLeverage) warns.push(`전략 레버리지 ${lev}배 > 한도 ${L.maxLeverage}배 → 주문이 막힘`);
      if (sup && !L.symbols.includes(s.market)) warns.push(`${s.market}이(가) 허용 종목에 없음`);
      if (s.exchange === "upbit" && c.env !== "mainnet") warns.push("업비트는 실거래 환경에서만 주문");
      const can = g.eligible && sup;
      return `<div class="lv-strat ${g.eligible ? "ok" : ""} ${linked ? "linked" : ""}">
        <div class="lv-strat-h"><b>${esc(s.name)}</b><small>${esc(s.mname || s.market)} · ${esc(Live.SUPPORTED[s.exchange] || s.exchange)} · ${esc(s.tf)} · ${lev}배</small>
          <label class="lv-switch sm" title="${can ? "실거래 연결" : "관문을 통과해야 연결할 수 있습니다"}"><input type="checkbox" data-link="${esc(s.id)}" ${linked ? "checked" : ""} ${can || linked ? "" : "disabled"}><span></span></label></div>
        <ul class="lv-gate">${g.checks.map(x => `<li class="${x.ok ? "ok" : "no"}"><i>${x.ok ? "✓" : "✗"}</i>${esc(x.name)} <b>${esc(x.text)}</b> <small>(${esc(x.need)})</small></li>`).join("")}</ul>
        ${warns.length ? `<div class="lv-w">${warns.map(esc).join("<br>")}</div>` : ""}
        ${lp ? `<div class="lv-lp">실거래 포지션: ${esc(lp.symbol)} ${lp.side === "long" ? "롱" : "숏"} ${fmt(lp.qty, 8)} @ ${fmt(lp.entry, 8)}${lp.sl ? ` · 손절 ${fmt(lp.sl, 8)}` : ""}${lp.tp ? ` · 익절 ${fmt(lp.tp, 8)}` : ""}</div>` : ""}
      </div>`;
    }).join("");
  } catch(e){ const el = $("#lvStrats"); if (el) el.innerHTML = `<div class="bad">모의투자 장부를 읽지 못했습니다: ${esc(e.message)}</div>`; }
  finally { stratBusy = false; }
}

async function refreshAccount(){
  if (!root || acctBusy) return; acctBusy = true;
  const el = $("#lvAcct"); el.textContent = "불러오는 중…";
  try {
    const st = Live.status();
    if (!st.keys.binancef_test && !st.keys.binancef && !st.keys.upbit){ el.textContent = "API 키를 넣으면 잔고와 포지션을 보여 줍니다."; return; }
    const [a, ps] = await Promise.all([Live.account(), Live.positions().catch(e => ({error: e.message}))]);
    acct = a;
    const bn = a.binance ? (a.binance.error ? `<span class="bad">바이낸스: ${esc(a.binance.error)}</span>` : `바이낸스 ${envKo(a.env)} · 지갑 <b>${fmt(a.binance.balance)}</b> USDT · 주문 가능 ${fmt(a.binance.available)} · 미실현 ${fmt(a.binance.unrealized)}`) : `<span class="lv-dim">${envKo(a.env)} 바이낸스 키 없음</span>`;
    const up = a.upbit ? (a.upbit.error ? `<br><span class="bad">업비트: ${esc(a.upbit.error)}</span>` : `<br>업비트 · ${a.upbit.filter(x => x.balance + x.locked > 0).slice(0, 8).map(x => `${esc(x.currency)} ${fmt(x.balance + x.locked, 8)}`).join(" · ")}`) : "";
    const rows = Array.isArray(ps) ? ps : [];
    el.classList.remove("lv-dim");
    el.innerHTML = `<p>${bn}${up}</p>${ps.error ? `<p class="bad">포지션 조회 실패: ${esc(ps.error)}</p>` : ""}
      ${rows.length ? `<div class="lv-tbl"><table><thead><tr><th>거래소</th><th>종목</th><th>방향</th><th>수량</th><th>진입가</th><th>현재가</th><th>미실현</th><th>레버리지</th><th>청산가</th><th>전략</th></tr></thead><tbody>
        ${rows.map(p => `<tr><td>${p.ex === "upbit" ? "업비트" : "바이낸스"}</td><td>${esc(p.symbol)}</td><td class="${p.side === "long" ? "up" : "dn"}">${p.side === "long" ? "롱" : "숏"}</td><td>${fmt(p.qty, 8)}</td><td>${fmt(p.entry, 8)}</td><td>${fmt(p.mark, 8)}</td><td class="${p.upnl >= 0 ? "up" : "dn"}">${fmt(p.upnl)}</td><td>${p.lev ? p.lev + "배" : "-"}</td><td>${fmt(p.liq, 8)}</td><td>${esc(p.strategy || "직접/기타")}</td></tr>`).join("")}</tbody></table></div>` : `<p class="lv-dim">열린 포지션 없음</p>`}`;
  } catch(e){ el.innerHTML = `<span class="bad">${esc(e.message)}</span>`; }
  finally { acctBusy = false; }
}

const KIND_KO = {decision: "판단", order: "주문", response: "응답", block: "막음", approval: "승인", config: "설정", error: "오류", warn: "주의", info: "정보", halt: "자동정지", kill: "긴급정지"};
function renderLog(){
  if (!root) return;
  const el = $("#lvLog"); if (!el) return;
  const rows = Live.auditLog(300).reverse();
  el.innerHTML = rows.length ? `<div class="lv-tbl"><table class="lv-log"><thead><tr><th>시각</th><th>구분</th><th>환경</th><th>전략</th><th>종목</th><th>방향</th><th>수량</th><th>금액</th><th>내용</th></tr></thead><tbody>
    ${rows.map(e => `<tr class="k-${esc(e.kind)}"><td>${new Date(e.t).toLocaleString("ko-KR", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit"})}</td><td><span class="lv-tag">${KIND_KO[e.kind] || esc(e.kind)}</span></td><td>${e.env === "mainnet" ? "실거래" : "테스트넷"}</td>
      <td>${esc(e.sname || "")}</td><td>${esc(e.symbol || "")}</td><td>${e.side ? (e.side === "long" ? "롱" : e.side === "short" ? "숏" : esc(e.side)) : ""}</td><td>${e.qty != null ? esc(e.qty) : ""}</td><td>${e.notional != null ? fmt(e.notional) : ""}</td><td>${esc(e.msg || "")}${e.status ? ` <small>[${esc(e.status)}]</small>` : ""}</td></tr>`).join("")}</tbody></table></div>` : `<div class="lv-dim">아직 기록이 없습니다.</div>`;
}

/* ============ 이벤트 ============ */
const guard = async (fn, ok) => { try { const r = await fn(); if (ok) toast(typeof ok === "function" ? ok(r) : ok); return r; } catch(e){ toast(e.message); return null; } };
async function onClick(e){
  const b = e.target.closest("[data-act]"); if (!b) return;
  const act = b.dataset.act;
  if (act === "close") return closeLive();
  if (act === "guide") return guideDialog();
  if (act === "kill"){
    const c = Live.liveCfg();
    if (!confirm(`모두 정지·청산\n\n${envKo(c.env)} 바이낸스 선물 계정의 미체결 주문을 모두 취소하고, 모든 포지션을 시장가(reduce-only)로 청산한 뒤 실거래를 끕니다.\n업비트는 이 앱이 산 수량만 팝니다.\n\n진행할까요?`)) return;
    b.disabled = true; b.textContent = "정지·청산 중…";
    const r = await guard(() => Live.killSwitch());
    b.disabled = false; b.textContent = "모두 정지·청산";
    if (r) toast(r.ok ? `긴급 정지 완료: 취소 ${r.cancelled.length}개 종목, 청산 ${r.closed.length}건` : `일부 실패 ${r.errors.length}건 — 거래소에서 직접 확인하세요`);
    render(); refreshAccount(); return;
  }
  if (act === "env-main"){ const ok = await guard(() => Live.setLive({env: "mainnet", confirm: $("#lvEnvPhrase").value}), "실거래(메인넷)로 바꿨습니다. 실거래는 꺼져 있으니 다시 켜세요"); if (ok) render(); return; }
  if (act === "env-cancel"){ renderEnv(); return; }
  if (act === "mode-auto"){ const ok = await guard(() => Live.setLive({mode: "auto", confirm: $("#lvModePhrase").value}), "자동 모드를 켰습니다"); if (ok) { renderMode(); renderStatus(); } return; }
  if (act === "mode-cancel"){ renderMode(); return; }
  if (act === "key-save"){
    const box = b.closest("[data-key]"), id = b.dataset.id, key = box.querySelector('[data-f="key"]').value, secret = box.querySelector('[data-f="secret"]').value;
    const ok = await guard(() => Live.setLive({keys: {[id]: {key, secret}}}), "키를 이 브라우저에 저장했습니다");
    if (ok){ renderKeys(); renderStatus(); refreshAccount(); }
    return;
  }
  if (act === "key-del"){ if (!confirm("이 키를 이 브라우저에서 지울까요?")) return; await guard(() => Live.setLive({keys: {[b.dataset.id]: null}}), "키를 지웠습니다"); renderKeys(); renderStatus(); return; }
  if (act === "limits"){
    const lim = {}; root.querySelectorAll("[data-lim]").forEach(i => { lim[i.dataset.lim] = i.dataset.lim === "symbols" ? i.value : +i.value; });
    if (lim.maxLeverage > 3 && !confirm(`최대 레버리지를 ${lim.maxLeverage}배로 올립니다. 손실이 그만큼 빨리 커집니다. 계속할까요?`)) return;
    const ok = await guard(() => Live.setLive({limits: lim}), "한도를 저장했습니다");
    if (ok){ renderLimits(); renderStatus(); renderStrategies(); }
    return;
  }
  if (act === "refresh" || act === "test"){ await refreshAccount(); if (act === "test") toast(acct?.binance?.error || acct?.upbit?.error || (acct?.binance || acct?.upbit ? "연결 확인 완료" : "확인할 키가 없습니다")); return; }
  if (act === "csv"){
    const blob = new Blob([Live.exportCSV()], {type: "text/csv;charset=utf-8"}), a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `live-audit-${new Date().toISOString().slice(0, 10)}.csv`; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000); return;
  }
}
// 레버리지 숫자를 바꾸는 동안 청산 거리 안내를 즉시 갱신
function onInput(e){
  if (e.target.id === "lvLevInput"){
    const lev = Math.max(1, Math.round(+e.target.value || 1)), h = $("#lvLevHint");
    if (h){ h.textContent = levHintText(lev); h.classList.toggle("warn", lev > 5); }
  }
}
async function onChange(e){
  const t = e.target;
  if (t.name === "lvMargin"){
    const ok = await guard(() => Live.setLive({marginType: t.value}), t.value === "CROSSED" ? "교차 마진으로 바꿨습니다 (위험 ↑)" : "격리 마진으로 바꿨습니다");
    if (!ok) renderLimits();
    return;
  }
  if (t.id === "lvOn"){
    if (t.checked){
      const c = Live.liveCfg(), L = c.limits;
      if (!confirm(`실거래를 켭니다 (${envKo(c.env)} · ${c.mode === "auto" ? "자동 모드" : "승인 모드"})\n\n연결한 전략의 모의투자 신호가 실제 주문이 됩니다.\n1회 ${L.orderNotional} USDT(최대 ${L.maxNotional}) · 레버리지 ≤ ${L.maxLeverage}배 · 포지션 ≤ ${L.maxPositions}개 · 하루 손실 한도 ${L.dailyLoss} USDT\n\n계속할까요?`)){ t.checked = false; return; }
      if ("Notification" in window && Notification.permission === "default") try { Notification.requestPermission(); } catch(x){}
    }
    const ok = await guard(() => Live.setLive({enabled: t.checked}), t.checked ? "실거래를 켰습니다" : "실거래를 껐습니다 (열린 포지션은 그대로)");
    if (!ok) t.checked = !t.checked;
    render(); return;
  }
  if (t.name === "lvEnv"){
    const c = Live.liveCfg();
    if (t.value === "mainnet" && c.env !== "mainnet"){ $("#lvEnvConfirm").hidden = false; $("#lvEnvPhrase").focus(); return; }
    if (t.value === "testnet" && c.env !== "testnet"){ await guard(() => Live.setLive({env: "testnet"}), "테스트넷으로 바꿨습니다 (실거래 꺼짐)"); render(); }
    return;
  }
  if (t.name === "lvMode"){
    const c = Live.liveCfg();
    if (t.value === "auto" && c.mode !== "auto"){ $("#lvModeConfirm").hidden = false; $("#lvModePhrase").focus(); return; }
    if (t.value === "approve" && c.mode !== "approve"){ await guard(() => Live.setLive({mode: "approve"}), "승인 모드로 바꿨습니다"); renderMode(); renderStatus(); }
    return;
  }
  if (t.dataset.link){
    const id = t.dataset.link, on = t.checked;
    const ok = await guard(() => Live.linkStrategy(id, on), on ? "실거래에 연결했습니다" : "연결을 끊었습니다 (열린 실거래 포지션은 그대로)");
    if (ok === null && on) t.checked = false;
    renderStrategies(); renderStatus(); return;
  }
}
