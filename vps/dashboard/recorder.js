/* GH Coin 실시간 화면 — 봇 페이지 안에서 도는 기록기 (ghcoin-dash 가 Chrome DevTools 로 넣는다. 앱 파일은 바꾸지 않음)
 *
 * 하는 일
 *   1. rrweb(record) 로 봇 화면의 DOM 을 사진(full snapshot) + 바뀐 부분(mutation)으로 기록해서
 *      DevTools 바인딩(window.__ghMirror) 으로 ghcoin-dash 에 보낸다 → 사용자 브라우저가 그대로 다시 그림
 *   2. 사용자가 실시간 화면에서 누른 것(클릭 · 입력 · 선택 · 키 · 스크롤 · 휠)을 같은 노드에 그대로 일으킨다 (act)
 *      - rrweb 이 붙인 노드 번호(id)로만 찾는다. 임의 코드 실행 없음
 *
 * 봇에 주는 부담: 평소(사무실 대기) 1초에 1KB 미만 · JS 몇 ms/분. 사진 한 장은 0.15~0.2초 (접속할 때 · 새로고침 뒤에만).
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
  var FLUSH_MS = 80, fastUntil = 0, viewers = 0;
  function flush() {
    if (timer) { clearTimeout(timer); timer = 0; }
    if (!queue.length) return;
    var batch = queue, kind = queue.kind || "i";
    queue = [];
    var payload;
    try { payload = '{"k":"' + kind + '","n":' + batch.length + ',"e":' + epoch + ',"ev":' + JSON.stringify(batch) + "}"; }
    catch (err) { lastErr = "json " + err; dropped += batch.length; return; }
    var fn = window[BIND];
    if (typeof fn !== "function") { dropped += batch.length; return; }
    try { fn(payload); sent += payload.length; } catch (err) { dropped += batch.length; lastErr = "bind " + err; }
  }
  var lastFrame = {};
  function emit(ev, isCheckout) {
    if (ev.type === 4) {                                   // Meta: 새 사진의 시작 (r = 모두 새로, c = 늦게 온 사람용)
      if (queue.length) flush();
      queue.kind = pendingKind || (isCheckout ? "c" : "r");
      pendingKind = null;
      if (queue.kind === "r") lastFrame = {};
    }
    queue.push(ev);
    if (ev.type === 2) { flush(); return; }               // 사진은 바로
    if (!timer) timer = setTimeout(flush, Date.now() < fastUntil ? 0 : FLUSH_MS);
  }

  function start() {
    epoch++;
    pendingKind = "r";
    stopFn = record({
      emit: emit,
      recordCanvas: false,                                 // 차트 캔버스는 아래 1초 타이머로 (rrweb 것은 rAF 를 계속 돌림)
      sampling: { mousemove: false, mouseInteraction: false, scroll: 150, media: 800, input: "last" },
      inlineStylesheet: true,
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
      return { ok: true, rec: !!stopFn, epoch: epoch, v: V };
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
    shutdown: function () { stop(); timers.forEach(clearInterval); timers = []; return { ok: true }; },
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
        if (document.activeElement !== el && el !== document.documentElement && el.focus) el.focus({ preventScroll: true });
        if (el === document.documentElement) tgt = document.activeElement || document.body;
        var guard = null;
        if (a.key === "Escape") {
          guard = function (e) { if (officeWouldClose()) e.stopPropagation(); };
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

  // ---------------------------------------------------------------- 차트 캔버스 (보는 사람이 있고, 보이는 캔버스가 있을 때만 1초에 한 번)
  // 바뀐 그림만 webp 로 보낸다. 사진 버퍼에는 안 쌓이고 캔버스마다 마지막 것만 남는다.
  var canvases = document.getElementsByTagName("canvas"), canvasBusy = false;
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
        c.toBlob(function (blob) {
          if (!blob) return done();
          var fr = new FileReader();
          fr.onload = function () {
            var url = fr.result;
            if (lastFrame[id] !== url && typeof url === "string" && url.indexOf("data:image/") === 0) {
              lastFrame[id] = url;
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
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
})();
