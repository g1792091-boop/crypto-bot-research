/* GH Coin 실시간 화면 (브라우저 쪽)
 * 봇 화면의 DOM 을 받아(rrweb Replayer, live 모드) 이 브라우저가 직접 그린다 — 그림 전송(원격화면)이 아니라서 선명하고 부드럽다.
 * 누르기 · 입력 · 선택 · 스크롤은 노드 번호로 봇에 보내고(/api/act), 봇이 바뀐 화면이 다시 이리로 온다.
 * 다시 그리는 화면(iframe)은 스크립트가 꺼진 샌드박스라 봇 화면 안의 무엇도 여기서 실행되지 않는다.
 */
(function () {
  "use strict";
  function $(id) { return document.getElementById(id); }
  var CSRF = (document.querySelector('meta[name="ghd-csrf"]') || {}).content || "";
  var stage = $("stage"), cover = $("cover"), coverMsg = $("coverMsg"), pill = $("pill"), pillTxt = $("pillTxt"), menu = $("menu");
  var M = window.__live = { batches: 0, bytes: 0, events: 0, resets: 0, lastBatchAt: 0, acts: 0, actFails: 0, lastActMs: null,
                            status: {}, connected: false, built: false, scale: 1, echoDropped: 0, trimmed: 0,
                            vid: "", clockOff: 0, lastEventAt: 0, evicted: false, staleReconnects: 0, pans: 0, font: "" };
  var replayer = null, fresh = true, focusedId = -1, es = null, everBuilt = false;
  var fitMode = "";                       // "" = 아직 안 고름: 화면이 작으면(휴대폰 세로) 실제 크기, 아니면 맞춤
  try { var fm = localStorage.getItem("ghd_fit"); fitMode = fm === "real" || fm === "fit" ? fm : ""; } catch (e) {}

  // ------------------------------------------------------------ 다시 그리기 (rrweb Replayer)
  function mk() {
    if (replayer) { try { replayer.destroy(); } catch (e) {} }
    stage.textContent = "";
    replayer = new rrwebReplay.Replayer([], {
      root: stage, liveMode: true,
      useVirtualDom: false,        // 실시간 이벤트를 바로 DOM 에
      pauseAnimation: false,       // 걷기 · 깜빡임 같은 CSS 애니메이션은 그대로
      mouseTail: false, triggerFocus: false, showWarning: false, UNSAFE_replayCanvas: false,
      insertStyleRules: []
    });
    // 기준 시각을 아주 먼 미래로: 도착한 이벤트가 모두 '이미 지난 것'이 되어 바로 그려진다 (시계 차이 · 타이머 없음)
    replayer.startLive(Number.MAX_SAFE_INTEGER / 2);
    replayer.enableInteract();
    replayer.on("resize", fit);
    replayer.on("fullsnapshot-rebuilded", onRebuilt);
    fresh = true;
    frameImg = {}; pendingFrames = {};
    M.resets++;
  }
  function onRebuilt() {
    hook();
    fonts();
    fit();
    M.built = true;
    cover.hidden = true;
    render();
    if (!everBuilt) {                       // 처음 그린 뒤: 키보드(Esc · Enter)가 바로 봇 화면으로 가게
      everBuilt = true;
      try { if (!document.activeElement || document.activeElement === document.body) replayer.iframe.focus(); } catch (e) {}
      portraitHint();
    }
  }

  // 봇 화면과 같은 글꼴: 서버의 봇이 사무실 · 채팅을 NanumGothicCoding 으로 그리면 이 브라우저도 같은 파일로 그린다
  // (Windows · 휴대폰 글꼴로 그리면 줄바꿈 · 높이가 달라져 채팅 스크롤 위치가 어긋남). 앱의 글꼴 목록에서 그 앞 이름(D2Coding)도 같은 파일로.
  var FONT_CSS = ["D2Coding", "NanumGothicCoding"].map(function (n) {
    return '@font-face{font-family:"' + n + '";src:url(/fonts/nanum-coding.ttf) format("truetype");font-weight:100 599;font-display:swap}' +
           '@font-face{font-family:"' + n + '";src:url(/fonts/nanum-coding-bold.ttf) format("truetype");font-weight:600 900;font-display:swap}';
  }).join("");
  function fonts() {
    var doc = replayer && replayer.iframe && replayer.iframe.contentDocument;
    if (!doc || !doc.head || M.font !== "nanum" || doc.getElementById("ghd-fonts")) return;
    var st = doc.createElement("style");
    st.id = "ghd-fonts";
    st.textContent = FONT_CSS;
    doc.head.appendChild(st);
  }

  // 화면 맞춤(기본): 봇 창 크기(1600×797 등)를 이 창에 맞게 CSS 로 축소/확대 — 글자는 벡터로 다시 그려져 선명함
  // 실제 크기: 1:1, 끌어서/스크롤해서 봄 (휴대폰)
  function fit() {
    if (!replayer || !replayer.iframe) return;
    var f = replayer.iframe, wrap = replayer.wrapper;
    var w = +f.getAttribute("width") || 1600, h = +f.getAttribute("height") || 900;
    var W = stage.clientWidth || innerWidth, H = stage.clientHeight || innerHeight;
    var s = Math.min(W / w, H / h);
    if ((fitMode || (s < 0.45 ? "real" : "fit")) === "real") {
      stage.classList.add("real");
      wrap.style.transform = ""; wrap.style.left = ""; wrap.style.top = "";
      M.scale = 1;
    } else {
      stage.classList.remove("real");
      wrap.style.transform = "scale(" + s + ")";
      wrap.style.left = Math.max(0, (W - w * s) / 2) + "px";
      wrap.style.top = Math.max(0, (H - h * s) / 2) + "px";
      M.scale = s;
    }
    $("fitBtn").textContent = stage.classList.contains("real") ? "🔲 화면에 맞추기 (전체 보기)" : "🔍 실제 크기로 보기";
  }
  addEventListener("resize", fit);

  // ------------------------------------------------------------ 받기 (SSE)
  function connect() {
    if (es) es.close();
    M.evicted = false; $("evicted").hidden = true;
    M.lastEventAt = Date.now();
    es = new EventSource("/api/live");
    var seen = function () { M.lastEventAt = Date.now(); };
    es.onopen = function () { M.connected = true; seen(); render(); };
    es.onerror = function () {
      M.connected = false; render();
      fetch("/api/live-stats", { cache: "no-store" }).then(function (r) { if (r.status === 401) location.href = "/login?next=/"; }).catch(function () {});
    };
    // hello: 이 연결 이름 + 서버 시각 (누른 때를 서버 시각으로 보내 늦게 도착한 조작은 서버가 버린다)
    es.addEventListener("hello", function (m) {
      seen();
      try { var h = JSON.parse(m.data); M.vid = String(h.vid || ""); if (typeof h.now === "number") M.clockOff = h.now - Date.now(); } catch (e) {}
      reportVisible();
    });
    es.addEventListener("ping", seen);
    es.addEventListener("bye", function () {            // 다른 창(탭)에서 실시간 화면을 열어 밀려남: 저절로 다시 붙지 않음 (서로 밀어내기 방지)
      es.close(); es = null; M.connected = false; M.evicted = true; render();
      $("evicted").hidden = false;
    });
    es.addEventListener("status", function (m) {
      seen();
      try { M.status = JSON.parse(m.data) || {}; } catch (e) { return; }
      if (M.status.font !== M.font) { M.font = M.status.font || ""; fonts(); }
      notice(M.status.notice);
      render(); dialog(M.status.dialog);
    });
    es.addEventListener("wait", function () { seen(); if (!M.built) coverMsg.textContent = "봇 화면 사진을 받는 중…"; });
    es.addEventListener("reset", function () { seen(); held = null; mk(); });
    es.addEventListener("m", function (m) {
      seen();
      var b;
      try { b = JSON.parse(m.data); } catch (e) { return; }
      M.bytes += m.data.length;
      if (held) { held.push(b); return; }                 // 스타일 파일을 받는 동안은 순서대로 모아 둠
      var need = cssNeeded(b);
      if (need.length) {
        held = [b];
        var mine = held;
        loadCss(need).then(function () { if (held !== mine) return; held = null; mine.forEach(apply); });
        return;
      }
      apply(b);
    });
    es.addEventListener("cv", function (m) { seen(); var f; try { f = JSON.parse(m.data); } catch (e) { return; } drawCanvas(f); });
  }
  // 연결이 소리 없이 죽음(와이파이 바뀜 · 패킷만 사라짐): 서버는 15초마다 ping 을 보내므로 35초 넘게 아무것도 없으면 다시 붙는다
  setInterval(function () {
    if (es && !M.evicted && Date.now() - M.lastEventAt > 35000) {
      M.staleReconnects++; M.connected = false; render();
      connect();
    }
  }, 5000);
  function reportVisible() {                            // 이 창이 보이는지 → 서버는 보이는 창이 있을 때만 차트 그림을 만든다
    if (!M.vid) return;
    post("/api/live-vis", { vid: M.vid, visible: !document.hidden }).catch(function () {});
  }

  function apply(b) {
    if (!replayer || (b.k === "r" && !fresh)) mk();
    M.batches++; M.lastBatchAt = Date.now();
    var ev = b.ev || [];
    for (var i = 0; i < ev.length; i++) {
      var e = ev[i];
      // 지금 입력 중인 칸에 봇이 돌려준 값은 무시 (내가 친 글자가 이김 · 가려진 **** 이 들어오지 않게)
      if (e.type === 3 && e.data && e.data.source === 5 && e.data.id === focusedId) { M.echoDropped++; continue; }
      if (e.type === 2) inlineCss(e);
      replayer.addEvent(e);
      M.events++;
      canvasTouched(e);
    }
    fresh = false;
    trim();
    if (hasPending) Promise.resolve().then(retryFrames);
  }

  // ------------------------------------------------------------ 앱 스타일 파일: 화면 사진을 그리기 전에 받아서 <style> 로 바로 넣는다
  // 봇은 <link> 주소만 보낸다 (Chrome 이 다시 풀어 쓴 CSS 는 var() 를 쓴 테두리가 빠짐). <link> 로 두면 그리는 순간엔 스타일이 없어서
  // 사진에 담긴 스크롤 위치(채팅 맨 아래 등)가 0 으로 잘리고 잠깐 맨 화면이 보인다 → 원본 파일(/app/…css)을 먼저 받아 그대로 넣는다.
  var cssCache = {}, held = null;
  function headLinks(e) {
    var out = [], doc = e.data && e.data.node, html = null, head = null, i;
    for (i = 0; doc && doc.childNodes && i < doc.childNodes.length; i++) if (doc.childNodes[i].tagName === "html") html = doc.childNodes[i];
    for (i = 0; html && html.childNodes && i < html.childNodes.length; i++) if (html.childNodes[i].tagName === "head") head = html.childNodes[i];
    for (i = 0; head && head.childNodes && i < head.childNodes.length; i++) {
      var n = head.childNodes[i], a = n.attributes || {};
      if (n.tagName === "link" && /(^|\s)stylesheet(\s|$)/i.test(a.rel || "") && /^\/app\/[^?#]+\.css([?#].*)?$/.test(a.href || "")) out.push(n);
    }
    return out;
  }
  function cssNeeded(b) {
    var need = [], ev = b.ev || [];
    for (var i = 0; i < ev.length; i++) if (ev[i].type === 2) {
      if (b.k === "r") cssCache = {};                     // 봇 페이지를 새로 읽음: 파일이 바뀌었을 수 있음 (브라우저 캐시 5분)
      headLinks(ev[i]).forEach(function (n) { var h = n.attributes.href; if (!(h in cssCache) && need.indexOf(h) < 0) need.push(h); });
    }
    return need;
  }
  function absCss(css, href) {                            // 파일 안의 상대 주소(url(img.png))를 /app/… 기준으로
    var base = location.origin + href;
    return css.replace(/url\(\s*(['"]?)([^'")]+)\1\s*\)/g, function (all, q, u) {
      if (/^(data:|https?:|\/|#)/i.test(u)) return all;
      try { var x = new URL(u, base); return "url(" + q + x.pathname + x.search + q + ")"; } catch (e) { return all; }
    });
  }
  function loadCss(hrefs) {
    return Promise.all(hrefs.map(function (h) {
      var ac = window.AbortController ? new AbortController() : null, t = ac ? setTimeout(function () { ac.abort(); }, 5000) : 0;
      return fetch(h, { credentials: "same-origin", signal: ac ? ac.signal : undefined })
        .then(function (r) { return r.ok ? r.text() : null; })
        .then(function (txt) { cssCache[h] = txt ? absCss(txt, h) : false; }, function () { cssCache[h] = false; })
        .then(function () { clearTimeout(t); });
    }));
  }
  function inlineCss(e) {                                 // 받은 파일이 있으면 <link> 를 같은 내용의 <style> 로 (rrweb: _cssText 가 있는 link → style)
    headLinks(e).forEach(function (n) {
      var txt = cssCache[n.attributes.href];
      if (txt) { n.attributes = { _cssText: txt }; M.cssInlined = (M.cssInlined || 0) + 1; }
    });
  }

  // live 모드는 받은 이벤트를 모두 쥐고 있다: 가끔 가운데를 잘라 메모리를 일정하게
  function trim() {
    var s = replayer && replayer.service, c = s && s.state && s.state.context;
    if (c && c.events && c.events.length > 3000) { M.trimmed += c.events.length - 1001; c.events.splice(1, c.events.length - 1001); }
  }

  // ------------------------------------------------------------ 차트 캔버스: 봇이 1초마다 보내는 그림을 캔버스 배경으로
  // (스크립트가 꺼진 샌드박스에서는 <canvas> 에 직접 그릴 수 없음)
  var pendingFrames = {}, frameImg = {}, hasPending = false;
  function paint(id) {
    var n = replayer && replayer.getMirror().getNode(id), fi = frameImg[id];
    if (!n || n.tagName !== "CANVAS" || !fi) return;
    n.style.setProperty("background", "url(" + fi + ") 0 0 / 100% 100% no-repeat", "important");
  }
  function drawCanvas(f) {
    if (!f || typeof f.url !== "string" || f.url.indexOf("data:image/") !== 0) return;
    var n = replayer && replayer.getMirror().getNode(f.id);
    if (!n || n.tagName !== "CANVAS") { pendingFrames[f.id] = f; hasPending = true; return; }
    delete pendingFrames[f.id];
    frameImg[f.id] = f.url;
    paint(f.id);
  }
  function canvasTouched(ev) {               // 봇이 캔버스 style 을 바꾸면 그림을 다시 얹음
    if (ev.type !== 3 || !ev.data || ev.data.source !== 0 || !ev.data.attributes) return;
    for (var i = 0; i < ev.data.attributes.length; i++) { var a = ev.data.attributes[i]; if (frameImg[a.id]) setTimeout(paint, 0, a.id); }
  }
  function retryFrames() { hasPending = false; for (var k in pendingFrames) drawCanvas(pendingFrames[k]); }

  // ------------------------------------------------------------ 보내기 (순서대로 하나씩)
  var chain = Promise.resolve(), inflight = 0;
  function post(url, body, ms) {
    // 6초 안에 답이 없으면 포기 (연결이 죽었을 때 누른 것이 나중에 한꺼번에 봇에 들어가지 않게 — 서버도 10초 지난 조작은 버림)
    var t0 = performance.now(), ac = window.AbortController ? new AbortController() : null;
    var tm = ac ? setTimeout(function () { ac.abort(); }, ms || 6000) : 0;
    return fetch(url, { method: "POST", credentials: "same-origin", cache: "no-store", signal: ac ? ac.signal : undefined,
                        headers: { "Content-Type": "application/json", "X-CSRF-Token": CSRF }, body: JSON.stringify(body || {}) })
      .then(function (r) {
        clearTimeout(tm);
        if (r.status === 401) { location.href = "/login?next=/"; throw new Error("login"); }
        return r.json().catch(function () { return {}; }).then(function (j) { j.status = r.status; j.rtt = performance.now() - t0; return j; });
      }, function (e) { clearTimeout(tm); throw e; });
  }
  var ERR = { gone: "화면이 바뀌었습니다 — 다시 눌러 주세요", hidden: "지금 봇 화면에 보이지 않는 곳입니다", disabled: "지금은 누를 수 없는 버튼입니다",
              option: "그 항목은 고를 수 없습니다", "no-recorder": "봇 화면을 다시 불러오는 중입니다" };
  function send(a) {
    if (inflight > 30) { toast("봇이 응답하지 않아 보내지 못했습니다"); return Promise.resolve(null); }
    inflight++;
    a.st = Date.now() + M.clockOff;                       // 누른 때 (서버 시각)
    var p = chain.then(function () { return post("/api/act", a); }).then(function (res) {
      M.acts++; M.lastActMs = res.rtt;
      if (!res.ok) {
        M.actFails++;
        if (res.status === 409 || res.status === 503 || res.status === 429) toast(res.err || "보내지 못했습니다");
        else if (ERR[res.err]) toast(ERR[res.err]);
      }
      return res;
    }).catch(function (e) { if (String(e && e.message) !== "login") toast("보내지 못했습니다 (연결 확인)"); return null; })
      .then(function (r) { inflight--; return r; });
    chain = p;
    return p;
  }

  // ------------------------------------------------------------ 입력 → 봇
  function idOf(n) {
    var m = replayer.getMirror();
    while (n) { var id = m.getId(n); if (id > 0) return id; n = n.parentNode; }
    return -1;
  }
  function elt(t) { return t && (t.nodeType === 1 ? t : t.parentElement); }
  function isText(t) {
    return !!t && ((t.tagName === "INPUT" && /^(text|search|url|tel|email|password|number|)$/i.test(t.getAttribute("type") || "")) || t.tagName === "TEXTAREA");
  }
  var pend = {}, pendT = 0, composing = false, masked = null;
  function flushInput(commit) {
    clearTimeout(pendT); pendT = 0;
    for (var id in pend) send({ kind: "input", id: +id, value: pend[id], commit: !!commit });
    pend = {};
  }
  function queueInput(t) {
    var id = idOf(t); if (id < 0) return;
    pend[id] = t.value;
    if (!pendT) pendT = setTimeout(function () { flushInput(false); }, 120);
  }
  var userScrollAt = 0, scrollT = {}, wheelAcc = null, wheelT = 0;
  function canScrollY(el, dy) {                // 이 화면에서 스스로 세로 스크롤되는 곳이면 휠은 보낼 필요 없음
    for (var n = el; n && n.nodeType === 1; n = n.parentElement) {
      var oy = getComputedStyle(n).overflowY;            // 이 창의 함수로 (샌드박스 창의 함수를 부르면 막힘)
      if ((oy === "auto" || oy === "scroll") && n.scrollHeight > n.clientHeight + 1) {
        if ((dy > 0 && n.scrollTop + n.clientHeight < n.scrollHeight - 1) || (dy < 0 && n.scrollTop > 0)) return true;
      }
    }
    return false;
  }
  function flushWheel() {
    clearTimeout(wheelT); wheelT = 0;
    if (wheelAcc && (Math.abs(wheelAcc.dx) + Math.abs(wheelAcc.dy) > 0)) send(wheelAcc);
    wheelAcc = null;
  }

  var enterAt = 0, dragFrom = null, dragToastAt = 0;
  var H = {
    click: function (e) {
      if (e.button !== 0) return;
      var t = elt(e.target); if (!t) return;
      // Enter 로 생긴 '가짜 클릭'(이 브라우저의 폼 보내기)은 보내지 않음 — Enter 는 키로 이미 봇에 감 (한글 조합 중 Enter 가 메시지를 보내던 문제)
      if (e.detail === 0 && Date.now() - enterAt < 300 && t.closest('button, input[type="submit"], input[type="image"]')) { e.preventDefault(); return; }
      var a = t.closest("a[href]");
      if (a) {
        var href = a.getAttribute("href") || "";
        if (/^https?:\/\//i.test(href) && href.indexOf(location.origin + "/") !== 0) {   // 바깥 링크는 이 브라우저에서 (서버에서 열지 않음)
          e.preventDefault(); window.open(href, "_blank", "noopener,noreferrer"); return;
        }
      }
      if (t.tagName === "SELECT" || t.tagName === "OPTION") return;     // 목록은 여기서 열고, 고르면 change 로 보냄
      if (!isText(t)) e.preventDefault();                                // 체크박스 · 라벨 · 링크는 봇이 정한다
      var id = idOf(t); if (id < 0) return;
      var r = t.getBoundingClientRect();
      send({ kind: "click", id: id, fx: r.width ? Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) : 0.5,
             fy: r.height ? Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) : 0.5 });
    },
    dblclick: function (e) { var t = elt(e.target); if (t && !isText(t)) { var id = idOf(t); if (id > 0) send({ kind: "dblclick", id: id }); } },
    compositionstart: function () { composing = true; },
    compositionend: function (e) { composing = false; if (isText(e.target)) queueInput(e.target); },   // 한글 조합이 끝난 글자
    input: function (e) {
      var t = e.target;
      if (!isText(t)) return;
      if (masked && masked.el === t) masked = null;                      // 새로 치기 시작함
      if (e.isComposing || composing) return;
      queueInput(t);
    },
    change: function (e) {
      var t = e.target, id = idOf(t);
      if (id < 0) return;
      if (t.tagName === "SELECT") send({ kind: "change", id: id, value: t.value });
      else if (t.tagName === "INPUT" && /^(range|color|date|time|month|week|datetime-local)$/i.test(t.type)) send({ kind: "change", id: id, value: t.value });
      else if (isText(t)) { pend[id] = t.value; flushInput(true); }
    },
    keydown: function (e) {
      var t = e.target, text = isText(t);
      if (e.key === "Enter") enterAt = Date.now();
      // 글자 칸의 Enter 는 이 브라우저에서 폼을 보내지 않게 (조합 중이어도) — 보내기는 봇이 키를 받아서 한다
      if (e.key === "Enter" && text && !(t.tagName === "TEXTAREA" && e.shiftKey)) e.preventDefault();
      if (e.isComposing || e.keyCode === 229 || composing) return;      // 한글 조합 중 Enter 는 보내지 않음
      if (text && !/^(Enter|Escape)$/.test(e.key)) return;              // 글자 · 지우기는 여기서 치고 값 전체를 보냄
      if (!/^(Enter|Escape|ArrowUp|ArrowDown|ArrowLeft|ArrowRight|PageUp|PageDown|Home|End|Delete|Backspace)$/.test(e.key)) return;
      if (e.key === "Enter" && t.tagName === "TEXTAREA" && e.shiftKey) return;
      if (/^(PageUp|PageDown|Home|End|ArrowUp|ArrowDown)$/.test(e.key)) userScrollAt = Date.now();
      var doc = replayer.iframe.contentDocument;
      // 글자 칸이 아니면 '문서'로 보낸다 → 봇에서 지금 포커스가 있는 곳(앱이 연 창 등)이 키를 받는다.
      // (여기서 마지막으로 누른 버튼으로 보내면 봇에서 그 버튼이 포커스를 빼앗아, 막 연 창의 Esc 가 안 듣는다)
      var target = text ? t : doc.documentElement;
      var id = idOf(target); if (id < 0) return;
      if (text) { pend[id] = t.value; flushInput(e.key === "Enter"); }
      send({ kind: "key", id: id, key: e.key, shift: e.shiftKey });
      if (e.key === "Enter" && text) e.preventDefault();
      if (e.key === "Backspace" && !text) e.preventDefault();
    },
    focusin: function (e) {
      var t = e.target;
      focusedId = isText(t) ? idOf(t) : -1;
      // 가려진 비밀 칸(****): 비워서 시작 → 새로 친 값이 봇의 값을 바꾼다 (별표를 보내지 않음)
      if (focusedId > 0 && /^\*+$/.test(t.value || "")) { masked = { el: t, v: t.value }; t.value = ""; }
    },
    focusout: function (e) {
      var t = e.target;
      if (isText(t)) { var id = idOf(t); if (pend[id] !== undefined) flushInput(true); }
      // 아무것도 안 치고 나가면 별표를 다시 보여 줌 (봇의 값은 그대로이므로)
      if (masked && masked.el === t && t.value === "") t.value = masked.v;
      masked = null;
      focusedId = -1;
    },
    wheel: function (e) {
      userScrollAt = Date.now();
      var t = elt(e.target); if (!t) return;
      var k = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1, dx = e.deltaX * k, dy = e.deltaY * k;
      if (e.ctrlKey || t.tagName === "CANVAS") e.preventDefault();       // 이 브라우저 확대 대신 앱의 확대(Ctrl+휠) · 차트는 봇이 확대
      else if (!dx && canScrollY(t, dy)) return;                          // 여기서 스크롤되는 곳: 스크롤 위치만 보냄
      var id = idOf(t); if (id < 0) return;
      if (wheelAcc && (wheelAcc.id !== id || wheelAcc.ctrl !== e.ctrlKey)) flushWheel();
      if (!wheelAcc) {
        var r = t.getBoundingClientRect();
        wheelAcc = { kind: "wheel", id: id, dx: 0, dy: 0, ctrl: e.ctrlKey,
                     fx: r.width ? Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) : 0.5, fy: r.height ? Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) : 0.5 };
      }
      wheelAcc.dx = Math.max(-1e4, Math.min(1e4, wheelAcc.dx + dx));
      wheelAcc.dy = Math.max(-1e4, Math.min(1e4, wheelAcc.dy + dy));
      if (!wheelT) wheelT = setTimeout(flushWheel, 60);
    },
    touchmove: function () { userScrollAt = Date.now(); },
    mousedown: function (e) { var t = elt(e.target); dragFrom = (e.button === 0 && t && t.tagName === "CANVAS") ? [e.clientX, e.clientY] : null; },
    mousemove: function (e) {
      if (!dragFrom) return;
      if (!(e.buttons & 1)) { dragFrom = null; return; }
      if (Math.abs(e.clientX - dragFrom[0]) + Math.abs(e.clientY - dragFrom[1]) < 10) return;
      dragFrom = null;
      if (Date.now() - dragToastAt > 30000) { dragToastAt = Date.now(); toast("차트 끌기 · 그리기는 아직 여기서 안 됩니다 — 휠 확대 · 클릭은 됩니다"); }
    },
    scroll: function (e) {
      if (Date.now() - userScrollAt > 400) return;                       // 내가 한 스크롤만 (봇에서 온 스크롤은 다시 안 보냄)
      var doc = replayer.iframe.contentDocument;
      var el = (e.target === doc) ? doc.documentElement : e.target, id = idOf(el);
      if (id < 0) return;
      clearTimeout(scrollT[id]);
      scrollT[id] = setTimeout(function () {
        var s = el === doc.documentElement ? (doc.scrollingElement || el) : el;
        send({ kind: "scroll", id: id, x: Math.max(0, Math.round(s.scrollLeft)), y: Math.max(0, Math.round(s.scrollTop)) });
      }, 90);
    },
    submit: function (e) { e.preventDefault(); }
  };
  function hook() {
    var doc = replayer.iframe.contentDocument;
    if (!doc) return;
    // 다시 그릴 때(document.open) 듣는 것이 사라지므로 매번 다시 단다 (같은 함수라 두 번 붙지 않음)
    for (var k in H) doc.addEventListener(k, H[k], { capture: true, passive: k === "touchmove" || k === "scroll" });
  }

  // ------------------------------------------------------------ 봇의 확인 창 (confirm · prompt · alert)
  var dlg = $("dlg"), dlgIn = $("dlgIn"), curDlg = null, dlgT = 0;
  function dialog(d) {
    if (!d) { curDlg = null; dlg.hidden = true; clearInterval(dlgT); return; }
    if (curDlg && curDlg.seq === d.seq) return;
    curDlg = d; d.shownAt = Date.now();
    $("dlgTtl").textContent = d.type === "prompt" ? "봇이 값을 묻습니다" : d.type === "alert" ? "봇 알림" : "봇이 확인을 묻습니다";
    $("dlgMsg").textContent = d.message || "";
    dlgIn.hidden = d.type !== "prompt"; dlgIn.value = d.default || "";
    $("dlgNo").hidden = d.type === "alert";
    dlg.hidden = false;
    (d.type === "prompt" ? dlgIn : $("dlgOk")).focus();
    clearInterval(dlgT);
    dlgT = setInterval(function () {
      var left = Math.max(0, 120 - Math.round((Date.now() - d.shownAt) / 1000));
      $("dlgLeft").textContent = left + "초 뒤 자동 취소";
    }, 1000);
    try { if (document.hidden && window.Notification && Notification.permission === "granted") new Notification("GH Coin: 봇이 확인을 묻습니다", { body: (d.message || "").slice(0, 120) }); } catch (e) {}
  }
  function answer(ok) {
    if (!curDlg) return;
    var d = curDlg;
    dlg.hidden = true;
    post("/api/dialog", { seq: d.seq, accept: ok, text: dlgIn.value }).then(function (r) { if (!r.ok && r.status !== 409) toast(r.err || "답하지 못했습니다"); })
      .catch(function () { toast("답하지 못했습니다"); });
  }
  $("dlgOk").onclick = function () { answer(true); };
  $("dlgNo").onclick = function () { answer(false); };
  dlg.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); answer(true); }
    if (e.key === "Escape") { e.preventDefault(); answer(curDlg && curDlg.type !== "alert" ? false : true); }
  });

  // ------------------------------------------------------------ 상태 표시 · 메뉴
  function render() {
    var s = M.status || {}, cls = "ok", txt = "연결됨";
    var bot = s.bot, mir = s.mirror;
    if (M.evicted) { cls = "warn"; txt = "다른 창에서 보는 중"; }
    else if (!M.connected) { cls = "warn"; txt = "다시 연결 중…"; }
    else if (mir === "crashed" || bot === "crashed" || bot === "stuck") { cls = "bad"; txt = "봇 멈춤"; }
    else if (mir === "no_chrome" || mir === "no_page" || bot === "no_chrome" || bot === "no_page") { cls = "bad"; txt = "봇 창 연결 끊김"; }
    else if (bot === "no_app") { cls = "bad"; txt = "봇 페이지 오류"; }
    else if (s.busy || mir === "busy" || bot === "slow") { cls = "warn"; txt = "봇 응답 지연"; }
    else if (!M.built) { cls = "warn"; txt = "화면 받는 중…"; }
    // 앱을 새로고침한 뒤 요약 수집기는 30초쯤 '켜지는 중'이지만, 실시간 화면은 이미 그려져 쓸 수 있다 → 초록 (메뉴에만 적음)
    else if (mir === "connecting" || mir === "starting" || (bot === "booting" && mir !== "live")) { cls = "warn"; txt = "봇 창 켜지는 중"; }
    pill.className = cls;
    pillTxt.textContent = txt;
    var detail = [];
    if (M.evicted) detail.push("다른 창(탭)에서 실시간 화면을 열어서 여기는 멈췄습니다");
    if (s.msg && mir !== "live") detail.push("화면: " + s.msg);
    if (s.botMsg && bot && bot !== "ok") detail.push("봇: " + s.botMsg);
    $("menuStatus").textContent = detail.join("\n") || (cls === "ok" ? "봇 화면을 실시간으로 보고 있습니다" : "");
    stage.classList.toggle("stale", !M.connected || cls === "bad");
    crashed = M.connected && (mir === "crashed" || bot === "crashed");
    // 확인 창이 이미 떠 있는 봇에 다시 붙으면 화면을 못 받는다 → '앱 새로고침'을 눈에 띄게
    // (그냥 무거운 작업으로 바쁜 것과는 구별: 그때 새로고침하면 하던 일이 끊김)
    unresponsive = M.connected && !!s.connectBusy;
    banner();
    if (!M.built) coverMsg.textContent = cls === "bad" ? txt + " — " + (s.botMsg || s.msg || "") : coverMsg.textContent;
    if (cls === "ok") { clearTimeout(render.t); render.t = setTimeout(function () { if (pill.className === "ok") pill.classList.add("min"); }, 4000); }
  }
  pill.onclick = function () { var open = menu.hidden; menu.hidden = !open; pill.setAttribute("aria-expanded", String(open)); };
  document.addEventListener("click", function (e) { if (!menu.hidden && !$("dock").contains(e.target)) { menu.hidden = true; pill.setAttribute("aria-expanded", "false"); } });
  $("fitBtn").onclick = function () {
    fitMode = stage.classList.contains("real") ? "fit" : "real";
    try { localStorage.setItem("ghd_fit", fitMode); } catch (e) {}
    fit(); menu.hidden = true;
  };
  function reloadApp() {
    if (!confirm("봇 앱(GH Coin 페이지)을 새로고침할까요?\n설정 · 기록 · 실거래 설정은 그대로이고, 화면이 30초쯤 뒤 다시 나옵니다.")) return;
    menu.hidden = true;
    post("/api/reload", {}).then(function (r) { toast(r.ok ? "새로고침했습니다 — 잠시 기다려 주세요" : (r.err || "새로고침하지 못했습니다")); });
  }
  $("reloadBtn").onclick = reloadApp;
  // 안내 띠의 '다시 열기'는 무엇이 일어날지 이미 적혀 있으므로 한 번 더 묻지 않는다
  $("officeReload").onclick = function () {
    $("officeReload").disabled = true; setTimeout(function () { $("officeReload").disabled = false; }, 5000);
    post("/api/reload", {}).then(function (r) { toast(r.ok ? "새로고침했습니다 — 잠시 기다려 주세요" : (r.err || "새로고침하지 못했습니다")); },
                                 function () { toast("보내지 못했습니다 (연결 확인)"); });
  };
  $("evictedBtn").onclick = function () { connect(); render(); };
  $("logoutBtn").onclick = function () { post("/logout", {}).then(function () { location.href = "/login"; }, function () { location.href = "/login"; }); };

  // 화면 위 안내 띠: 봇 탭이 죽었을 때 · 사무실이 닫혔을 때 (둘 다 '앱 새로고침'으로 돌아옴)
  var crashed = false, officeClosed = false, unresponsive = false;
  function banner() {
    var on = crashed || officeClosed || unresponsive;
    $("officeGone").hidden = !on;
    if (on) $("officeGoneTxt").textContent = crashed ? "봇 페이지(탭)가 죽었습니다 (3분 뒤 자동으로 다시 띄움)"
      : unresponsive ? "봇 페이지가 응답하지 않습니다 — 봇에 확인 창이 떠 있을 수 있습니다 (앱 새로고침으로 풀림)"
      : "사무실 화면이 닫혔습니다 (실거래 · 차트 터미널을 닫으면 앱이 사무실을 다시 열지 않음)";
  }

  var toastT = 0;
  function toast(msg, ms) {
    var t = $("toast"); t.textContent = msg; t.classList.add("on");
    clearTimeout(toastT); toastT = setTimeout(function () { t.classList.remove("on"); }, ms || 2600);
  }

  // 1초마다: 사무실이 닫혔는지 · 실거래 승인 창이 떴는지 (탭 제목으로도 알림)
  setInterval(function () {
    var doc = replayer && replayer.iframe && replayer.iframe.contentDocument;
    if (!doc || !M.built) return;
    var of = doc.getElementById("office"), other = doc.querySelector(".nt-root, .lv:not([hidden])");
    officeClosed = !!(of && of.hidden && !(other && other.getClientRects().length));
    banner();
    var appr = doc.querySelector(".lv-modal .lv-dlg"), apprOn = !!(appr && appr.getClientRects().length);
    var title = apprOn ? "🔔 주문 승인 대기 · GH Coin" : curDlg ? "❓ 확인 필요 · GH Coin" : "GH Coin";
    if (document.title !== title) document.title = title;
    // 실제 크기(휴대폰)에서는 봇 화면 가운데에 뜨는 창이 화면 밖이다 → 새로 뜬 창으로 옮겨 보여 줌 · 승인 창이면 띠도 띄움
    var real = stage.classList.contains("real"), boxes = doc.querySelectorAll(BOXES), now = [];
    for (var i = 0; i < boxes.length; i++) if (boxes[i].getClientRects().length) now.push(boxes[i]);
    if (real) for (var j = 0; j < now.length; j++) if (shownBoxes.indexOf(now[j]) < 0) { if (!inView(now[j])) panTo(now[j]); break; }
    shownBoxes = now;
    $("apprBar").hidden = !(apprOn && real && !inView(appr));
    apprBox = apprOn ? appr : null;
  }, 1000);
  var BOXES = ".lv-modal .lv-dlg, .gc-modal>*, .wl-modal>*, .of-docsbox, .of-presbox, #ofCard, [role=dialog][aria-modal=true]";
  var shownBoxes = [], apprBox = null;
  function boxRect(el) {                                  // 봇 화면 요소의 위치 (이 창 기준)
    var r = el.getBoundingClientRect(), f = replayer.iframe.getBoundingClientRect(), k = M.scale || 1;
    return { left: f.left + r.left * k, top: f.top + r.top * k, width: r.width * k, height: r.height * k };
  }
  function inView(el) {
    if (!el) return true;
    var r = boxRect(el);
    return r.left >= -4 && r.top >= -4 && r.left + r.width <= innerWidth + 4 && r.top + r.height <= innerHeight + 4;
  }
  function panTo(el) {
    if (!el || !replayer) return;
    var r = boxRect(el);
    M.pans++;
    stage.scrollTo({ left: Math.max(0, stage.scrollLeft + r.left + r.width / 2 - stage.clientWidth / 2),
                     top: Math.max(0, stage.scrollTop + r.top + Math.min(r.height, stage.clientHeight) / 2 - stage.clientHeight / 2), behavior: "smooth" });
  }
  $("apprBar").onclick = function () { panTo(apprBox); };

  // 봇이 서버에 파일을 내려받음: 앱은 '내려받았습니다'라고 하지만 파일은 서버(VPS)에 있다
  var noticeSeen = 0;
  function notice(n) {
    if (!n || !n.seq || n.seq <= noticeSeen) return;
    noticeSeen = n.seq;
    if (typeof n.t === "number" && Date.now() + M.clockOff - n.t > 20000) return;   // 이 화면을 열기 전의 알림은 넘김
    if (n.kind === "download") toast("봇이 파일을 서버에 저장했습니다: " + (n.name || ""), 6000);
  }
  function portraitHint() {
    if (stage.classList.contains("real") && innerHeight > innerWidth && !fitMode) toast("가로로 돌리면 봇 화면 전체가 보입니다 (메뉴 → 화면에 맞추기)", 5000);
  }

  // 다른 탭에 있어도 계속 받는다 (평소 1초에 수십 바이트 · 승인 창이 뜨면 탭 제목으로 알리려고).
  // 휴대폰이 탭을 잠재워서 연결이 끊겼으면, 다시 볼 때 새로 붙는다.
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && (!es || es.readyState === 2)) connect();
    else reportVisible();
  });

  mk();
  fit();
  render();
  connect();
})();
