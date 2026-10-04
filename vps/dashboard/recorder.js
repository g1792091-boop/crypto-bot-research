/* GH Coin 실시간 화면 — 봇 페이지 안에서 도는 기록기 (ghcoin-dash 가 Chrome DevTools 로 넣는다. 앱 파일은 바꾸지 않음)
 *
 * 하는 일
 *   1. rrweb(record) 로 봇 화면의 DOM 을 사진(full snapshot) + 바뀐 부분(mutation)으로 기록해서
 *      DevTools 바인딩(window.__ghMirror) 으로 ghcoin-dash 에 보낸다 → 사용자 브라우저가 그대로 다시 그림
 *   2. 사용자가 실시간 화면에서 누른 것(클릭 · 입력 · 선택 · 키 · 스크롤 · 휠)을 같은 노드에 그대로 일으킨다 (act)
 *      - rrweb 이 붙인 노드 번호(id)로만 찾는다. 임의 코드 실행 없음
 *
 * 봇에 주는 부담 (측정): 평소(사무실 대기) 1초에 약 0.5KB · 기록기 JS 약 20ms/분 (한 코어의 0.04%).
 *   메모리: 봇 탭(렌더러) +45~50MB 한 번 (rrweb 노드 표 · 속성 객체, 그 뒤로 늘지 않음 · JS 힙만 보면 +6~7MB).
 *   사진 한 장(full snapshot)은 봇 화면을 0.17~0.21초 멈춘다: 접속할 때 · 새로고침 뒤 · 버퍼가 넘친 뒤 첫 접속에만.
 *   큰 화면을 열고 닫을 때(팀 구성 335명 등)도 기록 · 직렬화에 0.2~0.4초 정도 든다.
 * ghcoin-dash 가 10초마다 '임대(lease)'를 갱신한다. 45초 넘게 갱신이 없으면 (서비스가 꺼짐) 기록을 멈춘다.
 * 비밀: 비밀번호 칸과 키 · 비밀 칸의 값은 ****** 로만 나간다 (봇 안의 값은 그대로).
 *
 * ghcoin-dash(mirror.py)가 넣기 전에 밑줄 두 개로 둘러싼 자리 셋(버전 · 바인딩 이름 · vendor/rrweb-record.min.js 내용)을 채운다.
 */
(function () {
  "use strict";
  var V = "__VERSION__";
  if (window.top !== window) return;                                            // 맨 위 창만
  if (!/^http:\/\/(127\.0\.0\.1|localhost):1786\d\/gh-coin\//.test(location.href)) return;
  var CTL = "__ghMirrorCtl", BIND = "__BINDING__";
  var old = window[CTL];
  if (old) {
    if (old.v === V) { try { old.resync("reinject"); } catch (e) {} return; }   // 이미 있음: 새 사진만
    try { old.shutdown(); } catch (e) {}                                         // 예전 버전: 멈추고 바꿔 끼움
  }

  // rrweb UMD 를 전역 이름 없이 불러온다 (앱의 window 에 rrwebRecord 를 만들지 않음)
  var holder = {};
  (function (exports, module, define) {
__RRWEB_RECORD_SRC__
  }).call(holder, undefined, undefined, undefined);
  var record = holder.rrwebRecord.record;

  // ---------------------------------------------------------------- 비밀 칸 가리기
  var SECRET_RX = /key|secret|token|pass|pwd|mnemonic|seed|private|키|비밀/i;
  function isSecretInput(el) {
    if (!el || el.nodeType !== 1) return false;
    if ((el.getAttribute("type") || "").toLowerCase() === "password") return true;
    var s = [el.id, el.getAttribute("name"), el.getAttribute("placeholder"), el.getAttribute("data-f"),
             el.getAttribute("aria-label"), el.getAttribute("autocomplete")].join(" ");
    return SECRET_RX.test(s) && !/phrase/i.test(el.id || "");                   // 확인 문구 칸(#lvEnvPhrase 등)은 보임
  }
  function mask(text) { return text ? new Array(Math.min(String(text).length, 24) + 1).join("*") : text; }

  // ---------------------------------------------------------------- 보내기 (묶어서)
  var queue = [], timer = 0, stopFn = null, epoch = 0, sent = 0, dropped = 0, lastErr = "", pendingKind = null;
  var FLUSH_MS = 80, fastUntil = 0, viewers = 0, dropResyncAt = 0;
  function lost(n, why) {                                 // 묶음을 못 보냄 → 보는 화면이 어긋남: 잠시 뒤 새 사진 (1분에 한 번까지)
    dropped += n; lastErr = why;
    var now = Date.now();
    if (stopFn && now - dropResyncAt > 60000 && typeof window[BIND] === "function") {
      dropResyncAt = now;
      setTimeout(function () { try { ctl.resync("drop"); } catch (e) {} }, 1000);
    }
  }
  function flush() {
    if (timer) { clearTimeout(timer); timer = 0; }
    if (!queue.length) return;
    var batch = queue, kind = queue.kind || "i";
    queue = [];
    var payload;
    try { payload = '{"k":"' + kind + '","n":' + batch.length + ',"e":' + epoch + ',"ev":' + JSON.stringify(batch) + "}"; }
    catch (err) { lost(batch.length, "json " + err); return; }
    var fn = window[BIND];
    if (typeof fn !== "function") { dropped += batch.length; return; }   // 서비스가 없음 (다시 붙으면 새 사진부터)
    try { fn(payload); sent += payload.length; } catch (err) { lost(batch.length, "bind " + err); }
  }
  var lastFrame = {};
  function emit(ev, isCheckout) {
    if (ev.type === 4) {                                   // Meta: 새 사진의 시작 (r = 모두 새로, c = 늦게 온 사람용)
      if (queue.length) flush();
      queue.kind = pendingKind || (isCheckout ? "c" : "r");
      pendingKind = null;
      if (queue.kind === "r") { lastFrame = {}; lastSig = {}; }
    }
    queue.push(ev);
    if (ev.type === 2) { flush(); return; }               // 사진은 바로
    if (!timer) timer = setTimeout(flush, Date.now() < fastUntil ? 0 : FLUSH_MS);
  }

  var startPending = false, dead = false;
  function start() {
    if (dead || stopFn) return;                            // 이미 기록 중이면 두 번 켜지 않음 (기록기 둘 = 모든 변화가 두 번)
    if (document.readyState === "loading") {               // 문서를 만드는 중: DOMContentLoaded 에 한 번만
      if (!startPending) {
        startPending = true;
        document.addEventListener("DOMContentLoaded", function () { startPending = false; start(); }, { once: true });
      }
      return;
    }
    epoch++;
    pendingKind = "r";
    stopFn = record({
      emit: emit,
      recordCanvas: false,                                 // 차트 캔버스는 아래 1초 타이머로 (rrweb 것은 rAF 를 계속 돌림)
      sampling: { mousemove: false, mouseInteraction: false, scroll: 150, media: 800, input: "last" },
      // 앱의 스타일 파일(<link>)은 내용을 풀어 쓰지 않고 주소만 보낸다 → 보는 쪽(live.js)이 /app/ 중계로 원본 파일을 받아
      // 그리기 전에 <style> 로 넣는다. (풀어 쓰면 Chrome 이 var() 를 쓴 border 같은 줄임 속성을 빈 값으로 내보내 테두리가 사라짐 · 사진도 작아짐)
      inlineStylesheet: false,
      inlineImages: false,
      collectFonts: false,
      recordCrossOriginIframes: false,
      slimDOMOptions: { script: true, comment: true, headFavicon: false, headWhitespace: true, headMetaSocial: true,
                        headMetaRobots: true, headMetaHttpEquiv: true, headMetaVerification: true, headMetaAuthorship: true },
      maskAllInputs: false,
      maskInputOptions: { password: true, text: true, textarea: true, search: true, email: true, tel: true, url: true, number: false },
      maskInputFn: function (text, el) { return isSecretInput(el) ? mask(text) : text; },
      errorHandler: function (err) { lastErr = String((err && err.message) || err).slice(0, 200); return true; }
    });
  }
  function stop() {
    try { if (stopFn) stopFn(); } catch (e) {}
    stopFn = null; queue = []; if (timer) { clearTimeout(timer); timer = 0; }
  }

  // ---------------------------------------------------------------- 스크롤: 칸마다 마지막 위치를 꼭 보냄
  // rrweb 은 모든 칸의 스크롤을 150ms 하나로 묶어서, 두 칸이 같이 움직이면(채팅 맨 아래로 + 사무실 카메라 이동) 앞 칸의 마지막 위치가 빠진다.
  // → 칸마다 50ms 뒤 마지막 위치를 한 번 더 보낸다 (사무실 카메라 이동도 초당 ~15번으로 부드러워짐).
  var scrolled = new Set(), scrollT = 0;
  function sendScrolls() {
    scrollT = 0;
    if (!stopFn) { scrolled.clear(); return; }
    var now = Date.now();
    scrolled.forEach(function (el) {
      var isDoc = el === document, se = isDoc ? (document.scrollingElement || document.documentElement) : el;
      var id = record.mirror.getId(el);
      if (id > 0 && (isDoc || el.isConnected)) emit({ type: 3, data: { source: 3, id: id, x: se.scrollLeft, y: se.scrollTop }, timestamp: now });
    });
    scrolled.clear();
  }
  document.addEventListener("scroll", function (e) {
    if (!stopFn) return;
    var t = e.target;
    if (t !== document && (!t || t.nodeType !== 1)) return;
    scrolled.add(t);
    if (!scrollT) scrollT = setTimeout(sendScrolls, 50);
  }, { capture: true, passive: true });

  // ---------------------------------------------------------------- 글꼴: 봇 화면의 고정폭 글꼴이 NanumGothicCoding 인지
  // (사무실 · 채팅 글꼴 'D2Coding, NanumGothicCoding, …'. 서버에 fonts-nanum 이 있으면 NanumGothicCoding →
  //  ghcoin-dash 가 같은 파일을 보는 쪽에 보내 줄바꿈 · 높이가 똑같아진다)
  var fontKind = null;
  function detectFont() {
    if (fontKind !== null) return fontKind;
    try {
      var cx = document.createElement("canvas").getContext("2d"), txt = "가나다라 GH Coin 0123 mmmWWWiii 한글채팅";
      var w = function (f) { cx.font = "16px " + f; return cx.measureText(txt).width; };
      var base = w("monospace"), d2 = w('"D2Coding", monospace'), nanum = w('"NanumGothicCoding", monospace');
      fontKind = (d2 === base && nanum !== base) ? "nanum" : "";
    } catch (e) { fontKind = ""; }
    return fontKind;
  }

  // ---------------------------------------------------------------- 임대: 서비스가 사라지면 아무도 안 보는 기록을 멈춤
  var leaseUntil = Date.now() + 60000, lastTick = Date.now(), timers = [];
  timers.push(setInterval(function () {
    var now = Date.now(), gap = now - lastTick;
    lastTick = now;
    if (gap > 15000) leaseUntil += gap;                   // 페이지 자신이 멈춰 있었음(확인 창 · 긴 작업): 서비스 탓이 아님
    if (stopFn && now > leaseUntil) { stop(); viewers = 0; lastErr = "lease expired"; }
  }, 5000));

  var ctl = {
    v: V,
    lease: function (ms, n) {
      leaseUntil = Date.now() + Math.max(15000, Math.min(+ms || 45000, 120000));
      viewers = Math.max(0, Math.min(+n || 0, 99));
      return { ok: true, rec: !!stopFn || startPending, epoch: epoch, v: V, font: detectFont() };
    },
    // 서비스가 다시 붙음 / 새 사진이 필요함: 노드 번호를 유지하는 takeFullSnapshot (stop+record 는 rrweb 안에서 약 4MB 씩 샘)
    resync: function (why) {
      leaseUntil = Date.now() + 60000;
      if (!stopFn) { start(); return { ok: true, epoch: epoch, restarted: true }; }
      flush();
      pendingKind = "r";
      record.takeFullSnapshot(true);
      return { ok: true, epoch: epoch };
    },
    checkout: function () {                                // 늦게 들어온 사람용 새 사진 (지금 보는 사람에게는 안 감)
      if (!stopFn) return ctl.resync("checkout");
      flush();
      pendingKind = "c";
      record.takeFullSnapshot(true);
      return { ok: true, epoch: epoch };
    },
    restart: function () { leaseUntil = Date.now() + 60000; stop(); start(); return { ok: true, epoch: epoch }; },
    shutdown: function () { dead = true; stop(); timers.forEach(clearInterval); timers = []; return { ok: true }; },
    stats: function () {
      var m = performance.memory || {};
      return { v: V, rec: !!stopFn, epoch: epoch, sent: sent, dropped: dropped, lastErr: lastErr, viewers: viewers,
               heapMb: Math.round((m.usedJSHeapSize || 0) / 1048576 * 10) / 10 };
    },
    act: function (a) { try { return act(a); } catch (e) { return { ok: false, err: "exception" }; } }
  };

  // ---------------------------------------------------------------- 실시간 화면에서 온 입력
  function elOf(id) {
    var n = record.mirror.getNode(id);
    if (!n || !n.isConnected) return null;
    if (n.nodeType === 9) return n.documentElement;
    return n.nodeType === 1 ? n : n.parentElement;
  }
  function pt(el, fx, fy) {
    var r = el.getBoundingClientRect();
    fx = (typeof fx === "number" && fx >= 0 && fx <= 1) ? fx : 0.5;
    fy = (typeof fy === "number" && fy >= 0 && fy <= 1) ? fy : 0.5;
    return { x: r.left + r.width * fx, y: r.top + r.height * fy };
  }
  function mouse(el, type, p, extra) {
    var init = { bubbles: true, cancelable: true, composed: true, view: window, clientX: p.x, clientY: p.y,
                 screenX: p.x, screenY: p.y, button: 0, buttons: /down/.test(type) ? 1 : 0, detail: 1 };
    for (var k in extra || {}) init[k] = extra[k];
    var E = MouseEvent;
    if (/^pointer/.test(type)) { E = PointerEvent; init.pointerId = 1; init.pointerType = "mouse"; init.isPrimary = true; }
    return el.dispatchEvent(new E(type, init));
  }
  var proto = { INPUT: HTMLInputElement.prototype, TEXTAREA: HTMLTextAreaElement.prototype, SELECT: HTMLSelectElement.prototype };
  var nativeValue = {};                                   // rrweb 이 value setter 를 감싸기 전의 원래 것
  for (var t in proto) nativeValue[t] = Object.getOwnPropertyDescriptor(proto[t], "value").set;
  var TEXT_TYPES = /^(text|search|url|tel|email|password|number)$/i;
  var IMPLICIT = /^(text|search|url|tel|email|password|date|month|week|time|datetime-local|number)$/i;
  function visible(el) { return el === document.documentElement || el.getClientRects().length > 0; }
  // Escape 를 아무것도 안 열린 사무실에 보내면 앱이 사무실을 닫는다 (다시 열려면 새로고침). 실시간 화면에서는 그 경우만 막는다.
  function officeWouldClose() {
    var of = document.getElementById("office");
    if (!of || of.hidden) return false;
    var ids = ["ofZoom", "ofPres", "ofCard"];
    for (var i = 0; i < ids.length; i++) { var e = document.getElementById(ids[i]); if (e && !e.hidden) return false; }
    var menus = of.querySelectorAll(".of-menu");
    for (var j = 0; j < menus.length; j++) if (!menus[j].hidden) return false;
    return true;
  }
  function implicitSubmit(el) {                           // HTML 표준의 'Enter 로 보내기' 와 같게
    var f = el.form;
    if (!f || el.tagName !== "INPUT" || !IMPLICIT.test(el.type)) return;
    var btn = null, els = f.elements, blocking = 0;
    for (var i = 0; i < els.length; i++) {
      var x = els[i];
      if (!btn && ((x.tagName === "BUTTON" && (x.type || "submit") === "submit") || (x.tagName === "INPUT" && /^(submit|image)$/i.test(x.type)))) btn = x;
      if (x.tagName === "INPUT" && IMPLICIT.test(x.type)) blocking++;
    }
    if (btn) { if (!btn.disabled) btn.click(); }
    else if (blocking === 1 && f.requestSubmit) f.requestSubmit();
  }
  function act(a) {
    var t0 = performance.now();
    fastUntil = Date.now() + 1500;                        // 누른 결과를 바로 보내서 빠르게 보이게
    var el = elOf(a.id);
    if (!el) return { ok: false, err: "gone" };
    if (a.kind !== "scroll" && a.kind !== "wheel" && el.closest && el.closest("[inert]")) return { ok: false, err: "inert" };
    switch (a.kind) {
      case "click":
      case "dblclick": {
        if (!visible(el)) return { ok: false, err: "hidden" };
        if (el.closest && el.closest(":disabled")) return { ok: false, err: "disabled" };
        var p = pt(el, a.fx, a.fy);
        if (a.kind === "dblclick") { mouse(el, "dblclick", p, { detail: 2 }); break; }
        mouse(el, "pointerover", p); mouse(el, "mouseover", p);
        mouse(el, "pointerdown", p);
        var go = mouse(el, "mousedown", p);
        var f = el.closest && el.closest("input,textarea,select,button,a[href],[tabindex],[contenteditable]");
        if (go && f && f.focus) f.focus({ preventScroll: true });
        else if (go && !f && document.activeElement && document.activeElement !== document.body && document.activeElement.blur) document.activeElement.blur();   // 진짜 마우스처럼: 빈 곳을 누르면 포커스가 빠짐
        mouse(el, "pointerup", p); mouse(el, "mouseup", p);
        mouse(el, "click", p);                             // 체크박스 · 라벨 · 링크의 기본 동작도 그대로 일어남
        break;
      }
      case "input": {                                      // 입력 칸의 값 전체 (한 글자씩이 아니라)
        if (!(el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && TEXT_TYPES.test(el.type)))) return { ok: false, err: "not-text" };
        if (el.disabled || el.readOnly) return { ok: false, err: "disabled" };
        if (document.activeElement !== el && el.focus) el.focus({ preventScroll: true });
        nativeValue[el.tagName].call(el, String(a.value));
        el.dispatchEvent(new InputEvent("input", { bubbles: true, composed: true, inputType: "insertReplacementText", data: null }));
        if (a.commit) el.dispatchEvent(new Event("change", { bubbles: true }));
        break;
      }
      case "change": {                                     // <select> · range · color · 날짜 칸
        if (el.disabled) return { ok: false, err: "disabled" };
        if (el.tagName === "SELECT") {
          var okv = false;
          for (var i = 0; i < el.options.length; i++) if (el.options[i].value === String(a.value) && !el.options[i].disabled) okv = true;
          if (!okv) return { ok: false, err: "option" };
          nativeValue.SELECT.call(el, String(a.value));
        } else if (el.tagName === "INPUT" && /^(range|color|date|time|month|week|datetime-local)$/i.test(el.type)) {
          nativeValue.INPUT.call(el, String(a.value));
        } else return { ok: false, err: "not-select" };
        el.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        break;
      }
      case "key": {
        var ki = { key: a.key, code: a.key === " " ? "Space" : a.key, bubbles: true, cancelable: true, composed: true, shiftKey: !!a.shift };
        var tgt = el;
        // 실시간 화면은 글자 칸에서 친 키만 그 칸 번호로 보낸다. 그 밖(문서)이면 봇에서 지금 포커스가 있는 곳에 — 앱이 연 창이
        // 스스로 잡은 포커스를 빼앗지 않아야 그 창의 Esc · Enter 가 듣는다 (AI 연결 · 지갑 · 코인 AI 창)
        var textEl = el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && TEXT_TYPES.test(el.type));
        if (textEl && document.activeElement !== el && el.focus) el.focus({ preventScroll: true });
        if (!textEl) tgt = (document.activeElement && document.activeElement !== document.body) ? document.activeElement : (el === document.documentElement ? document.body : el);
        var guard = null, swallowed = false;
        if (a.key === "Escape") {
          guard = function (e) { if (officeWouldClose()) { e.stopPropagation(); swallowed = true; } };
          document.documentElement.addEventListener("keydown", guard);
        }
        try {
          var go2 = tgt.dispatchEvent(new KeyboardEvent("keydown", ki));
          if (go2 && a.key === "Enter") {
            tgt.dispatchEvent(new KeyboardEvent("keypress", ki));
            implicitSubmit(tgt);
          }
          tgt.dispatchEvent(new KeyboardEvent("keyup", ki));
        } finally {
          if (guard) document.documentElement.removeEventListener("keydown", guard);
        }
        // 막은 Esc 가 실거래 승인 창 · 안내 창 위였다면: 앱의 Esc 처럼 '거절'('알겠습니다')을 누른다 (사무실은 닫지 않음)
        if (swallowed) {
          var mb = document.querySelector('.lv-modal [data-a="no"]') || document.querySelector('.lv-modal [data-a="ok"]');
          if (mb && visible(mb)) mb.click();
        }
        break;
      }
      case "scroll": {
        var s = (el === document.documentElement || el === document.body) ? document.scrollingElement : el;
        s.scrollTo({ left: +a.x || 0, top: +a.y || 0, behavior: "instant" });
        break;
      }
      case "wheel": {                                      // 앱의 휠 처리(가로 스크롤 · Ctrl+휠 확대 · 차트 확대)용
        var q = pt(el, a.fx, a.fy);
        el.dispatchEvent(new WheelEvent("wheel", { bubbles: true, cancelable: true, composed: true, view: window, clientX: q.x, clientY: q.y,
          deltaX: +a.dx || 0, deltaY: +a.dy || 0, deltaMode: 0, ctrlKey: !!a.ctrl }));
        break;
      }
      case "focus": { if (el.focus) el.focus({ preventScroll: true }); break; }
      default: return { ok: false, err: "kind" };
    }
    return { ok: true, ms: Math.round((performance.now() - t0) * 100) / 100 };
  }

  // ---------------------------------------------------------------- 차트 캔버스 (화면에 '보이는' 실시간 창이 있고, 보이는 캔버스가 있을 때만 1초에 한 번)
  // 바뀐 그림만 webp 로 보낸다: 먼저 작은 사본(≤256×160)의 지문을 보고, 그대로면 인코딩을 건너뛴다 (그대로인 차트 7개: +7.7% → +0.2% CPU).
  // 사진 버퍼에는 안 쌓이고 캔버스마다 마지막 것만 남는다.
  var canvases = document.getElementsByTagName("canvas"), canvasBusy = false, lastSig = {}, fpC = null, fpX = null;
  function sig(c) {
    try {
      var w = Math.min(256, Math.max(1, c.width >> 2)), h = Math.min(160, Math.max(1, c.height >> 2));
      if (!fpC) { fpC = document.createElement("canvas"); fpX = fpC.getContext("2d", { willReadFrequently: true }); }
      if (fpC.width !== w || fpC.height !== h) { fpC.width = w; fpC.height = h; } else fpX.clearRect(0, 0, w, h);
      fpX.drawImage(c, 0, 0, w, h);
      var d = new Int32Array(fpX.getImageData(0, 0, w, h).data.buffer), x = 2166136261;
      for (var i = 0; i < d.length; i++) x = Math.imul(x ^ d[i], 16777619);
      return (x >>> 0) + ":" + c.width + "x" + c.height;
    } catch (e) { return null; }
  }
  timers.push(setInterval(function () {
    if (!stopFn || !viewers || canvasBusy || !canvases.length || document.hidden || typeof window[BIND] !== "function") return;
    var list = [];
    for (var i = 0; i < canvases.length && list.length < 8; i++) {
      var c = canvases[i], id = record.mirror.getId(c);
      if (id > 0 && c.width > 1 && c.height > 1 && c.width * c.height <= 4e6 && c.offsetParent !== null) list.push([c, id]);
    }
    if (!list.length) return;
    canvasBusy = true;
    var left = list.length, done = function () { if (--left === 0) canvasBusy = false; };
    list.forEach(function (x) {
      var c = x[0], id = x[1];
      try {
        var sg = sig(c);
        if (sg !== null && lastSig[id] === sg) return done();       // 그림이 그대로: 인코딩 안 함
        lastSig[id] = sg;
        c.toBlob(function (blob) {
          if (!blob) return done();
          var fr = new FileReader();
          fr.onload = function () {
            var url = fr.result, h = "";
            if (typeof url === "string") { var x2 = 2166136261; for (var k = 0; k < url.length; k++) x2 = Math.imul(x2 ^ url.charCodeAt(k), 16777619); h = url.length + ":" + (x2 >>> 0); }
            if (lastFrame[id] !== h && typeof url === "string" && url.indexOf("data:image/") === 0) {
              lastFrame[id] = h;                                       // 그림 전체가 아니라 짧은 표시만 기억 (봇 메모리)
              try { window[BIND]('{"k":"v","n":1,"e":' + epoch + ',"id":' + id + ',"w":' + c.width + ',"h":' + c.height + ',"url":' + JSON.stringify(url) + "}"); sent += url.length; } catch (e) {}
            }
            done();
          };
          fr.onerror = done;
          fr.readAsDataURL(blob);
        }, "image/webp", 0.7);
      } catch (e) { lastErr = "canvas " + e; done(); }
    });
  }, 1000));

  try {
    if (old) delete window[CTL];
    Object.defineProperty(window, CTL, { value: ctl, enumerable: false, configurable: true, writable: false });
  } catch (e) {                                            // 바꿀 수 없는 예전 것: 그것을 계속 쓴다
    ctl.shutdown();
    try { old && old.resync && old.resync("fallback"); } catch (e2) {}
    return;
  }
  start();
})();
