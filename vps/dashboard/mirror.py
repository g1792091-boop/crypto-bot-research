"""실시간 화면 중계 (live DOM mirror): 봇 페이지 → Chrome DevTools → 이 서비스 → 사용자 브라우저 (SSE).

  봇 페이지(Chrome, 가상 화면)  ──recorder.js(rrweb record) · Runtime.addBinding──▶  Mirror (이 파일)
        ▲                                                                              │ SSE (gzip)
        └──── Runtime.callFunctionOn(고정 함수 → recorder 의 act) ◀── POST /api/act ◀── live.js (rrweb Replayer)

- 기록기는 Page.addScriptToEvaluateOnNewDocument(새로고침 · 05:15 재시작 뒤에도 자동) + Runtime.evaluate(이미 열린 페이지) 로 넣는다.
- 버퍼: '마지막 사진(full snapshot) + 그 뒤 바뀐 것' 을 늦게 들어온 사람용으로 둔다 (BASE_LIMIT 넘으면 버리고, 다음 접속 때 새 사진을 부탁).
- 보는 사람마다 보낼 줄이 CLIENT_CAP 를 넘으면 (느린 휴대폰) 줄을 비우고 새 사진부터 다시 보낸다 (메모리가 끝없이 늘지 않게).
- 입력은 recorder 의 act() 만 부른다: 함수 본문은 고정, 사용자가 보낸 것은 검사한 값(인자)뿐. 임의 JS · DevTools 명령 전달 없음.
- JS 확인 창(alert/confirm/prompt)은 상태로 알리고 Page.handleJavaScriptDialog 로 답한다. 2분 넘게 답이 없으면 '취소' (봇이 멈춰 있지 않게).
"""
import collections
import hashlib
import http.client
import json
import re
import secrets
import sys
import threading
import time
import urllib.parse
import urllib.request

import websocket

BINDING = "__ghMirror"
LEASE_EVERY = 10.0           # 기록기 임대 갱신 간격 (초)
LEASE_MS = 45000             # 이만큼 갱신이 없으면 페이지 안 기록기가 스스로 멈춤
DIALOG_TIMEOUT = 120.0       # JS 확인 창 자동 취소
BASE_LIMIT = 6 << 20         # 늦게 들어온 사람용 버퍼 상한 (글자 수, 새로고침 직후 사무실 2.5MB 가 들어갈 만큼)
CLIENT_CAP = 8 << 20         # 한 사람 앞에 쌓인 미전송 상한 (넘으면 새 사진부터)
MAX_PAYLOAD = 24 << 20       # 페이지에서 온 한 묶음 상한
MAX_VIEWERS = 4              # 동시에 보는 실시간 화면 수 (넘으면 가장 오래된 것을 끊음)
ACT_TIMEOUT = 5.0
CALL_TIMEOUT = 10.0
RESYNC_EVERY = 60.0          # 깨진 묶음이 오면 새 사진을 부탁 (이 간격보다 자주는 아님)
BUSY_RELOAD_AFTER = 150.0    # 붙지 못하고 '응답 없음'이 이만큼 이어지고 봇 상태도 '멈춤'이면 앱 새로고침 (확인 창이 떠 있던 경우)
BUSY_RELOAD_GAP = 600.0      # 위 자동 새로고침은 10분에 한 번까지
MAX_STATIC = 4 << 20
# 보는 창 크기에 봇 화면을 맞춤 (확대 없이 1:1 — 1600×900 을 큰 모니터에 늘려 보이던 것 해결)
SIZE_MIN_W = 1024            # 이보다 좁은 창(휴대폰 등)은 봇 크기를 바꾸지 않고 줄여서 보여 줌 (앱이 데스크톱용)
SIZE_MIN_H = 600
SIZE_MAX_W = 3840
SIZE_MAX_H = 2400
STATIC_RE = re.compile(r"^(gh-coin|nuri-ai)/[A-Za-z0-9._\-/]{1,200}\.(svg|png|jpe?g|gif|webp|ico|css|woff2?|ttf|otf)$")
STATIC_TYPES = {"svg": "image/svg+xml", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
                "webp": "image/webp", "ico": "image/x-icon", "css": "text/css; charset=utf-8", "woff": "font/woff",
                "woff2": "font/woff2", "ttf": "font/ttf", "otf": "font/otf"}
HEAD_RE = re.compile(r'^\{"k":"([ricv])","n":(\d{1,7}),"e":(\d{1,9}),')
# 화면 글자에 섞여 나온 API 키 형식은 한 번 더 가린다 (입력 칸 값은 recorder.js 가 이미 ****)
# JSON 글자 그대로 검사하므로 줄바꿈 바로 뒤(\n · \t · \u00xx 다음)에서 시작하는 키도 잡는다 (n · t 가 '글자 뒤'로 보이지 않게)
SECRET_RE = re.compile(r"(?:(?<=\\[nrtbf])|(?<=\\u00[0-9a-fA-F]{2})|(?<![A-Za-z0-9_\-]))"
                       r"(?:nvapi-|sk-(?:ant-|or-|proj-)?|gsk_|tvly-|csk-|xai-|hf_|pplx-|AIza|ghp_|github_pat_|glpat-)[A-Za-z0-9_\-]{16,}")
ACT_FN = "function(a){var c=window.__ghMirrorCtl;return c?c.act(a):{ok:false,err:'no-recorder'}}"
KEYS = {"Enter", "Escape", "Tab", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Backspace", "Delete",
        "Home", "End", "PageUp", "PageDown", " "}
KINDS = {"click", "dblclick", "input", "change", "key", "scroll", "wheel", "focus"}

_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def jdump(v):
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def log(msg):
    sys.stderr.write(f"mirror: {msg}\n")
    sys.stderr.flush()


class Unavailable(Exception):
    """봇 화면에 지금 보낼 수 없음 (503)."""


class Conflict(Exception):
    """지금 상태와 맞지 않음 (409)."""


def validate(a):
    """실시간 화면에서 온 조작을 검사해서 recorder 의 act() 에 넘길 값만 남긴다. 틀리면 ValueError."""
    if not isinstance(a, dict) or a.get("kind") not in KINDS:
        raise ValueError("kind")
    i = a.get("id")
    if not isinstance(i, int) or isinstance(i, bool) or not (0 < i < 100_000_000):
        raise ValueError("id")
    k = a["kind"]
    out = {"kind": k, "id": i}
    for f in ("fx", "fy"):
        v = a.get(f)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1:
            out[f] = float(v)
    if k in ("input", "change"):
        v = a.get("value")
        if not isinstance(v, str) or len(v) > (20000 if k == "input" else 2000):
            raise ValueError("value")
        out["value"] = v
        out["commit"] = bool(a.get("commit"))
    elif k == "key":
        if a.get("key") not in KEYS:
            raise ValueError("key")
        out["key"] = a["key"]
        out["shift"] = bool(a.get("shift"))
    elif k == "scroll":
        for f in ("x", "y"):
            v = a.get(f, 0)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 <= v <= 1e7):
                raise ValueError(f)
            out[f] = round(float(v), 1)
    elif k == "wheel":
        for f in ("dx", "dy"):
            v = a.get(f, 0)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not (-1e4 <= v <= 1e4):
                raise ValueError(f)
            out[f] = round(float(v), 2)
        out["ctrl"] = bool(a.get("ctrl"))
    return out


# ---------------------------------------------------------------- DevTools 세션 (읽는 스레드 하나 + 응답 대기)
class Session:
    def __init__(self, ws, on_event):
        self.ws = ws
        self.on_event = on_event
        self.seq = 0
        self.waiters = {}            # id -> [Event, msg] 또는 콜백
        self.lock = threading.Lock()
        self.alive = True
        self.reader = threading.Thread(target=self._read, name="mirror-cdp", daemon=True)

    def start(self):
        self.reader.start()

    def _read(self):
        try:
            while self.alive:
                raw = self.ws.recv()
                if not raw:
                    break
                msg = json.loads(raw)
                mid = msg.get("id")
                if mid is not None:
                    with self.lock:
                        w = self.waiters.pop(mid, None)
                    if callable(w):
                        try:
                            w(msg)
                        except Exception as e:  # 콜백 오류가 읽기를 멈추지 않게
                            log(f"callback {type(e).__name__}: {e}")
                    elif w:
                        w[1] = msg
                        w[0].set()
                else:
                    try:
                        self.on_event(self, msg.get("method"), msg.get("params") or {})
                    except Exception as e:
                        log(f"event {msg.get('method')} {type(e).__name__}: {e}")
        except (websocket.WebSocketException, OSError, ValueError) as e:
            if self.alive:
                log(f"DevTools 연결 끊김: {type(e).__name__}")
        self.alive = False
        with self.lock:
            ws = list(self.waiters.values())
            self.waiters.clear()
        for w in ws:
            if callable(w):
                try:
                    w({"error": {"message": "closed"}})
                except Exception:
                    pass
            else:
                w[0].set()

    def send(self, method, params=None, cb=None):
        """응답을 기다리지 않고 보냄. cb(msg) 는 읽는 스레드에서 불림."""
        if not self.alive:
            raise ConnectionError("not connected")
        with self.lock:
            self.seq += 1
            mid = self.seq
            if cb:
                self.waiters[mid] = cb
            self.ws.send(jdump({"id": mid, "method": method, "params": params or {}}))
        return mid

    def call(self, method, params=None, timeout=CALL_TIMEOUT):
        if not self.alive:
            raise ConnectionError("not connected")
        w = [threading.Event(), None]
        with self.lock:
            self.seq += 1
            mid = self.seq
            self.waiters[mid] = w
            try:
                self.ws.send(jdump({"id": mid, "method": method, "params": params or {}}))
            except Exception:
                self.waiters.pop(mid, None)
                raise
        if not w[0].wait(timeout):
            with self.lock:
                self.waiters.pop(mid, None)
            raise TimeoutError(method)
        msg = w[1]
        if msg is None:
            raise ConnectionError("closed")
        if "error" in msg:
            raise RuntimeError(f"{method}: {str(msg['error'].get('message'))[:120]}")
        return msg.get("result", {})

    def close(self):
        self.alive = False
        try:
            self.ws.close()
        except Exception:
            pass


def _local_ws(target):
    """DevTools 목록의 웹소켓 주소 — 이 서버 안(127.0.0.1 · localhost · ::1)이 아니면 거부."""
    ws_url = str(target.get("webSocketDebuggerUrl") or "")
    host = urllib.parse.urlsplit(ws_url.replace("ws://", "http://", 1)).hostname or ""
    if not ws_url.startswith("ws://") or host not in ("127.0.0.1", "localhost", "::1"):
        raise ConnectionError("DevTools 주소가 이상함")
    return ws_url


def _quiet_shutdown(sock):
    try:
        sock.shutdown(2)
    except OSError:
        pass


class Viewer:
    __slots__ = ("q", "qbytes", "need_reset", "waiting", "gone", "status_seen", "raw", "wire", "joined", "sock", "resets",
                 "evicted", "vid", "visible")

    def __init__(self, sock):
        self.q = collections.deque()
        self.qbytes = 0
        self.need_reset = True       # 처음엔 사진부터
        self.waiting = False         # 새 사진을 기다리는 중
        self.gone = False
        self.status_seen = -1
        self.raw = 0
        self.wire = 0
        self.joined = time.time()
        self.sock = sock
        self.resets = 0
        self.evicted = False         # 다른 창이 들어와서 밀려남 → 'bye' 를 보내고 끊음 (브라우저가 저절로 다시 붙어 서로 밀어내지 않게)
        self.vid = secrets.token_urlsafe(12)   # 이 연결 이름 (보이는지 알릴 때)
        self.visible = True          # 이 창(탭)이 지금 화면에 보이는지 (차트 그림은 보이는 사람이 있을 때만 만든다)


class Mirror:
    def __init__(self, cdp_base, target_re, recorder_path, record_lib_path, status_fn=None):
        self.cdp_base = cdp_base
        self.target_re = target_re
        self.status_fn = status_fn or (lambda: {})
        with open(record_lib_path, encoding="utf-8") as f:
            lib = "\n".join(line for line in f.read().splitlines() if not line.startswith("//# sourceMappingURL="))
        with open(recorder_path, encoding="utf-8") as f:
            tpl = f.read()
        for mark, times in (("__RRWEB_RECORD_SRC__", 1), ("__BINDING__", 1), ("__VERSION__", 1)):
            if tpl.count(mark) != times:
                raise ValueError(f"recorder.js 에 {mark} 자리가 정확히 {times}번 있어야 합니다")
        self.version = hashlib.sha256((tpl + lib).encode("utf-8")).hexdigest()[:12]
        self.boot = tpl.replace("__BINDING__", BINDING).replace("__VERSION__", self.version).replace("__RRWEB_RECORD_SRC__", lib)
        self.stop = threading.Event()
        self.cond = threading.Condition()
        self.sess = None
        self.ctx = None                  # 봇 페이지의 JS 실행 공간 id (바인딩 호출에서 얻음)
        self.main_frame = None           # 봇 페이지 맨 위 프레임 id
        self.contexts = {}               # 실행 공간 id -> (frame id, 기본 공간인지, origin) — 맨 위 GH Coin 문서의 기본 공간에서 온 것만 받는다
        self.origin = ""                 # http://127.0.0.1:17860
        self.state = "starting"          # starting · connecting · live · no_page · no_chrome · crashed · busy · error
        self.state_msg = "시작하는 중"
        self.base = []                   # 마지막 사진 + 그 뒤 묶음 (문자열 JSON)
        self.base_bytes = 0
        self.base_valid = False
        self.frames = {}                 # 캔버스 id -> 마지막 그림 묶음
        self.viewers = []
        self.checkout_at = 0.0           # 새 사진을 부탁한 시각 (0 = 부탁 안 함)
        self.dialog = None
        self.dialog_seq = 0
        self.status_json = "{}"
        self.status_ver = 0
        self.lease_sent = 0.0
        self.lease_ok = 0.0
        self.lease_rtt = None
        self.page_stats = None
        self.last_batch = 0.0
        self.st = collections.Counter()   # 숫자 통계
        self.resync_at = 0.0             # 깨진 묶음 때문에 새 사진을 부탁한 시각
        self.busy_since = 0.0            # 붙기가 '응답 없음'으로 계속 실패하기 시작한 때 (확인 창이 떠 있을 때 생김)
        self.busy_reload_at = 0.0
        self.lease_now = False           # 보이는 사람 수가 바뀜 → 임대를 바로 갱신 (차트 그림 켜기/끄기)
        self.view_size = None            # (너비, 높이, 화면 배율) — 마지막으로 크기를 알린 넓은 창. 봇 화면을 이 크기로 그린다
        self.font = ""                   # 봇 화면이 쓰는 고정폭 글꼴 ("nanum" = NanumGothicCoding → 보는 쪽도 같은 글꼴 파일로)
        self.notice = None               # 보는 사람에게 한 번 알릴 것 (봇이 서버에 파일을 내려받음 등)
        self.notice_seq = 0
        self.downloads = {}              # guid -> 파일 이름 (내려받기 알림용)
        self.act_ms = collections.deque(maxlen=50)
        self.static_cache = collections.OrderedDict()
        self.static_lock = threading.Lock()

    # ------------------------------------------------------------ 상태
    def _set_state(self, state, msg):
        self.state, self.state_msg = state, msg
        self.refresh_status()

    def refresh_status(self):
        bot = {}
        try:
            bot = self.status_fn() or {}
        except Exception:
            pass
        d = self.dialog
        s = jdump({"mirror": self.state, "msg": self.state_msg, "bot": bot.get("status"), "botMsg": bot.get("message"),
                   "dialog": {k: d[k] for k in ("seq", "type", "message", "default")} if d else None,
                   "busy": bool(self.lease_sent and time.monotonic() - self.lease_sent > 20),
                   "font": self.font, "notice": self.notice, "connectBusy": bool(self.busy_since)})
        with self.cond:
            if s != self.status_json:
                self.status_json = s
                self.status_ver += 1
                self.cond.notify_all()

    # ------------------------------------------------------------ 보는 사람 (SSE)
    def join(self, sock):
        v = Viewer(sock)
        victims = []
        with self.cond:
            while len(self.viewers) >= MAX_VIEWERS:
                old = self.viewers.pop(0)
                old.gone = old.evicted = True
                victims.append(old)
            self.viewers.append(v)
            self.cond.notify_all()
        for o in victims:                                 # 'bye' 를 쓸 시간을 준 뒤, 막혀 있으면 소켓을 닫음
            self.st["evictions"] += 1
            t = threading.Timer(3.0, _quiet_shutdown, (o.sock,))
            t.daemon = True
            t.start()
        self.st["joins"] += 1
        self.lease_now = True
        return v

    def set_visible(self, vid, visible):
        """보는 창이 보이는지/숨었는지 (live.js 가 알림). 차트 그림은 보이는 창이 있을 때만 만든다. 모르는 vid 면 False."""
        with self.cond:
            for v in self.viewers:
                if v.vid == vid:
                    if v.visible != visible:
                        v.visible = visible
                        self.lease_now = True
                    return True
        return False

    def set_size(self, vid, w, h, dpr):
        """보는 창 크기 (live.js 가 알림). 봇 화면을 이 크기로 그리게 해서 늘리지 않고 1:1 로 보이게 한다.
        좁은 창(너비 1024 미만, 휴대폰 등)은 봇 크기를 바꾸지 않는다 — 앱이 데스크톱용이라 그 창은 줄여서 보여 준다.
        여러 창이면 마지막으로 알린(크기를 바꾸거나 다시 본) 창을 따른다. 모르는 vid 면 False."""
        with self.cond:
            if not any(v.vid == vid and not v.gone for v in self.viewers):
                return False
        if w < SIZE_MIN_W or h < 480:
            return True
        size = (int(min(w, SIZE_MAX_W)), int(max(SIZE_MIN_H, min(h, SIZE_MAX_H))), max(1.0, min(2.0, round(float(dpr) * 4) / 4)))
        if size != self.view_size:
            self.view_size = size
            sess = self.sess
            if sess:
                self._apply_size(sess, wait=False)
        return True

    def _apply_size(self, sess, wait):
        w, h, d = self.view_size
        p = {"width": w, "height": h, "deviceScaleFactor": d, "mobile": False, "screenWidth": w, "screenHeight": h}
        if wait:
            sess.call("Emulation.setDeviceMetricsOverride", p)
        else:
            sess.send("Emulation.setDeviceMetricsOverride", p, cb=lambda m: None)
        log(f"봇 화면 크기를 보는 창에 맞춤: {w}×{h} (배율 {d})")

    def leave(self, v):
        with self.cond:
            v.gone = True
            self.viewers = [x for x in self.viewers if x is not v]
            self.st["sse_raw"] += v.raw
            self.st["sse_wire"] += v.wire

    def next_items(self, v, timeout=15.0):
        """보낼 것 목록 [(event, data)]. 빈 목록 = 시간 초과(핑). None = 끝."""
        want_checkout = False
        with self.cond:
            self.cond.wait_for(lambda: v.q or v.need_reset or v.gone or self.stop.is_set() or v.status_seen != self.status_ver, timeout)
            if v.gone or self.stop.is_set():
                return None
            out = []
            if v.status_seen != self.status_ver:
                v.status_seen = self.status_ver
                out.append(("status", self.status_json))
            if v.need_reset:
                v.need_reset = False
                v.q.clear()
                v.qbytes = 0
                if self.base_valid and self.base:
                    v.resets += 1
                    out.append(("reset", "{}"))
                    out.extend(("m", b) for b in self.base)
                    out.extend(("cv", f) for f in self.frames.values())
                else:
                    v.waiting = True
                    want_checkout = True
                    out.append(("wait", "{}"))
            elif v.q:
                out.extend(v.q)
                v.q.clear()
                v.qbytes = 0
        if want_checkout:
            self.request_checkout()
        return out

    def _push(self, ev, data):
        """(self.cond 안에서) 지금 보는 사람들 줄에 넣는다."""
        n = len(data)
        for v in self.viewers:
            if v.waiting or v.need_reset:
                continue
            if v.qbytes + n > CLIENT_CAP:               # 못 따라오는 사람: 줄을 비우고 새 사진부터
                v.q.clear()
                v.qbytes = 0
                v.need_reset = True
                self.st["slow_resets"] += 1
                continue
            v.q.append((ev, data))
            v.qbytes += n
        self.cond.notify_all()

    def request_checkout(self):
        s = self.sess
        if not s or not s.alive:
            return                                        # 다시 붙으면 넣으면서 새 사진이 옴
        with self.cond:
            if self.checkout_at and time.monotonic() - self.checkout_at < 15:
                return
            self.checkout_at = time.monotonic()
        self.st["checkouts"] += 1
        try:
            s.send("Runtime.evaluate", {"expression": "window.__ghMirrorCtl && window.__ghMirrorCtl.checkout()", "returnByValue": True, "silent": True},
                   cb=lambda m: None)
        except Exception:
            self.checkout_at = 0.0

    def resync(self, why):
        """모두에게 새 사진(r)을 부탁 (깨진 묶음 등으로 보는 화면이 어긋났을 때). RESYNC_EVERY 에 한 번까지."""
        s = self.sess
        now = time.monotonic()
        if not s or not s.alive or now - self.resync_at < RESYNC_EVERY:
            return
        self.resync_at = now
        self.st["resyncs"] += 1
        try:
            s.send("Runtime.evaluate", {"expression": "window.__ghMirrorCtl && window.__ghMirrorCtl.resync(%s)" % jdump(str(why)[:20]),
                                        "silent": True}, cb=lambda m: None)
        except Exception:
            pass

    # ------------------------------------------------------------ 페이지에서 온 것
    def _on_event(self, sess, method, p):
        if sess is not self.sess:
            return
        if method == "Runtime.bindingCalled":
            if p.get("name") == BINDING:
                cid = p.get("executionContextId")
                fr = self.contexts.get(cid)
                # 맨 위 GH Coin 문서(앱 주소)의 기본 실행 공간에서 온 것만: 페이지 안 다른 프레임이나, 봇 탭이 다른 사이트로 넘어간 뒤의
                # 문서가 바인딩을 불러 조작 대상을 바꾸거나 사용자가 치는 글자를 받아 가지 못하게
                if not fr or not fr[1] or fr[0] != self.main_frame or not self.origin or fr[2] != self.origin:
                    self.st["foreign_binding_calls"] += 1
                    return
                self.ctx = cid
                self._on_batch(p.get("payload") or "")
        elif method == "Runtime.executionContextCreated":
            c = p.get("context") or {}
            aux = c.get("auxData") or {}
            self.contexts[c.get("id")] = (aux.get("frameId"), bool(aux.get("isDefault")), str(c.get("origin") or ""))
            while len(self.contexts) > 200:
                self.contexts.pop(next(iter(self.contexts)))
        elif method == "Runtime.executionContextsCleared":
            self.ctx = None
            self.contexts = {}
        elif method == "Runtime.executionContextDestroyed":
            self.contexts.pop(p.get("executionContextId"), None)
            if p.get("executionContextId") == self.ctx:
                self.ctx = None
        elif method == "Page.frameNavigated":
            f = p.get("frame") or {}
            if not f.get("parentId") and f.get("id"):
                self.main_frame = f["id"]
                url = str(f.get("url", ""))
                if self.target_re.match(url):              # 실행기 포트가 바뀌었을 수 있음 (17860~17869)
                    u = urllib.parse.urlsplit(url)
                    self.origin = f"{u.scheme}://{u.netloc}"
                else:                                      # 봇 탭이 앱이 아닌 곳으로 감: 그 문서는 믿지 않고 연결을 끊는다
                    self.ctx = None
                    self.st["left_app"] += 1
                    self._set_state("no_page", "봇 탭이 GH Coin 이 아닌 페이지로 바뀌었습니다 — 메뉴의 '앱 새로고침'으로 돌아옵니다")
                    sess.close()
        elif method == "Page.javascriptDialogOpening":
            self.dialog_seq += 1
            self.dialog = {"seq": self.dialog_seq, "type": str(p.get("type", "alert"))[:20],
                           "message": SECRET_RE.sub("[가림]", str(p.get("message", ""))[:2000]),
                           "default": SECRET_RE.sub("[가림]", str(p.get("defaultPrompt", ""))[:500]), "t": time.monotonic()}
            self.st["dialogs"] += 1
            self.refresh_status()
        elif method == "Page.javascriptDialogClosed":
            self.dialog = None
            self.refresh_status()
        elif method == "Page.downloadWillBegin":           # 봇이 파일을 내려받음 → 서버에 저장된다는 것을 보는 사람에게 알림
            name = SECRET_RE.sub("[가림]", str(p.get("suggestedFilename") or "파일"))[:80]
            self.downloads[str(p.get("guid"))[:64]] = name
            while len(self.downloads) > 20:
                self.downloads.pop(next(iter(self.downloads)))
        elif method == "Page.downloadProgress":
            if p.get("state") in ("completed", "canceled"):
                name = self.downloads.pop(str(p.get("guid"))[:64], None)
                if name and p.get("state") == "completed":
                    self.st["downloads"] += 1
                    self.notice_seq += 1
                    self.notice = {"seq": self.notice_seq, "kind": "download", "name": name, "t": int(time.time() * 1000)}
                    self.refresh_status()
        elif method == "Inspector.targetCrashed":
            self.ctx = None
            self.dialog = None
            self._set_state("crashed", "봇 페이지(탭)가 죽었습니다")
        elif method == "Inspector.targetReloadedAfterCrash":
            self._set_state("connecting", "봇 페이지를 다시 여는 중")
        elif method == "Inspector.detached":
            sess.close()

    def _on_batch(self, payload):
        m = HEAD_RE.match(payload[:48])
        # JSON.stringify 결과에는 날것의 줄바꿈이 없다: 있으면 SSE 틀(event:/data:)을 깨려는 것 → 버림
        if not m or len(payload) > MAX_PAYLOAD or "\n" in payload or "\r" in payload:
            self.st["bad_batches"] += 1
            if m and m.group(1) != "v":                   # 정상 머리의 묶음을 버림 → 보는 화면이 어긋남: 새 사진을 부탁 (1분에 한 번까지)
                self.resync("bad-batch")
            return
        kind, n = m.group(1), int(m.group(2))
        now = time.monotonic()
        self.last_batch = now
        if self.state in ("connecting", "busy", "starting") and kind != "v":
            self._set_state("live", "실시간")
        if kind == "v":                                   # 캔버스 그림: 캔버스마다 마지막 것만
            try:
                cid = int(json.loads(payload)["id"])
            except (ValueError, KeyError, TypeError):
                return
            self.st["canvas_frames"] += 1
            self.st["canvas_bytes"] += len(payload)
            with self.cond:
                self.frames[cid] = payload
                while len(self.frames) > 16:
                    self.frames.pop(next(iter(self.frames)))
                self._push("cv", payload)
            return
        if self.origin:
            payload = payload.replace(self.origin + "/", "/app/")   # 앱 파일 주소 → 이 서비스의 정적 파일 중계
        payload = SECRET_RE.sub("[가림]", payload)
        size = len(payload)
        self.st["batches"] += 1
        self.st["events"] += n
        self.st["bytes_in"] += size
        if kind in ("r", "c"):
            self.st["snapshots_" + kind] += 1
            self.st["last_snapshot_bytes"] = size
        with self.cond:
            if kind == "r":                               # 새로고침 · 다시 넣음: 모두 새 사진부터
                self.base, self.base_bytes, self.base_valid = [payload], size, True
                self.frames = {}
                self.checkout_at = 0.0
                for v in self.viewers:
                    v.q.clear()
                    v.qbytes = 0
                    v.waiting = False
                    v.need_reset = True
                self.cond.notify_all()
            elif kind == "c":                             # 늦게 들어온 사람용 (지금 보는 사람은 그대로)
                self.base, self.base_bytes, self.base_valid = [payload], size, True
                self.checkout_at = 0.0
                for v in self.viewers:
                    if v.waiting:
                        v.waiting = False
                        v.need_reset = True
                self.cond.notify_all()
            else:
                if self.base_valid:
                    self.base.append(payload)
                    self.base_bytes += size
                    if self.base_bytes > BASE_LIMIT:      # 메모리 상한: 버리고 다음 접속 때 새 사진
                        self.base, self.base_bytes, self.base_valid = [], 0, False
                        self.st["base_drops"] += 1
                self._push("m", payload)

    # ------------------------------------------------------------ 연결 · 넣기 · 임대
    def _pages(self):
        with _NO_PROXY.open(self.cdp_base + "/json/list", timeout=3) as r:
            lst = json.loads(r.read(4 << 20).decode("utf-8", "replace"))
        return [t for t in lst if isinstance(t, dict) and t.get("type") == "page" and self.target_re.match(str(t.get("url", "")))]

    def _connect(self):
        try:
            pages = self._pages()
        except Exception as e:
            raise ConnectionError(f"DevTools 연결 불가: {type(e).__name__}") from None
        if not pages:
            self.busy_since = 0.0
            if self.state != "no_page":                   # '앱 밖으로 넘어감' 같은 더 자세한 안내는 그대로 둔다
                self._set_state("no_page", "봇 페이지가 아직 없음 (Chrome 이 켜지는 중일 수 있음)")
            return None
        t = pages[0]
        ws_url = _local_ws(t)
        u = urllib.parse.urlsplit(str(t.get("url", "")))
        self.origin = f"{u.scheme}://{u.netloc}"
        if not self.busy_since:                           # '응답 없음'(확인 창) 안내는 다시 붙는 동안에도 그대로 둔다 (깜빡이지 않게)
            self._set_state("connecting", "봇 화면에 붙는 중")
        ws = websocket.create_connection(ws_url, timeout=10, suppress_origin=True, enable_multithread=True)
        ws.settimeout(None)
        sess = Session(ws, self._on_event)
        self.sess = sess
        self.ctx = None
        sess.start()
        try:
            return self._setup(sess)
        except BaseException:
            # 넣는 도중 실패(확인 창 · 바쁜 페이지로 시간 초과 등): 이 연결을 반드시 닫는다.
            # 안 닫으면 시도할 때마다 DevTools 세션 · 소켓 · 읽는 스레드가 하나씩 남아 TasksMax 를 다 쓰고 :8080 이 멈춘다.
            sess.close()
            if self.sess is sess:
                self.sess = None
            raise

    def _setup(self, sess):
        t0 = time.monotonic()
        self.contexts = {}
        sess.call("Page.enable")
        self.main_frame = ((sess.call("Page.getFrameTree").get("frameTree") or {}).get("frame") or {}).get("id")
        sess.call("Runtime.enable")      # 새로고침 뒤에도 바인딩이 새 문서에 들어가려면 필요 (기존 실행 공간 목록도 이때 옴)
        sess.call("Runtime.addBinding", {"name": BINDING})
        if self.view_size:               # 다시 붙을 때(Chrome 재시작 · 05:15) 마지막 보는 창 크기를 다시 적용 (사진 찍기 전에)
            self._apply_size(sess, wait=True)
        sess.call("Page.addScriptToEvaluateOnNewDocument", {"source": self.boot})
        r = sess.call("Runtime.evaluate", {"expression": self.boot + "\n;void 0", "returnByValue": True, "silent": True}, 30)
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            log(f"기록기 넣기 오류: {str((d.get('exception') or {}).get('description') or d.get('text'))[:200]}")
        self.st["injects"] += 1
        self.st["inject_ms"] = round((time.monotonic() - t0) * 1000)
        log(f"봇 화면에 붙음 (기록기 {self.version}, {self.st['inject_ms']}ms)")
        self.lease_ok = time.monotonic()
        self.lease_sent = 0.0
        self.busy_since = 0.0
        return sess

    def _lease(self, sess):
        if self.lease_sent:                               # 지난 갱신에 아직 답이 없음 (페이지가 바쁨 · 확인 창)
            return
        self.lease_sent = time.monotonic()
        with self.cond:
            n = sum(1 for v in self.viewers if not v.gone and v.visible)   # 차트 그림은 '보이는' 창이 있을 때만
        expr = (f"(function(c){{if(!c)return null;var r=c.lease({LEASE_MS},{n});r.stats=c.stats();return r}})(window.__ghMirrorCtl)")

        def done(msg):
            sent = self.lease_sent
            self.lease_sent = 0.0
            if "error" in msg or sess is not self.sess:
                return
            now = time.monotonic()
            self.lease_ok = now
            self.lease_rtt = round((now - sent) * 1000, 1) if sent else None
            res = msg.get("result") or {}
            if res.get("exceptionDetails"):
                return
            val = (res.get("result") or {}).get("value")
            if val is None:                               # 기록기가 없음 (다른 문서) → 다시 넣기
                self.st["reinjects"] += 1
                sess.send("Runtime.evaluate", {"expression": self.boot + "\n;void 0", "silent": True, "returnByValue": True}, cb=lambda m: None)
                return
            self.page_stats = val.get("stats")
            font = str(val.get("font") or "")[:12]
            if font != self.font:
                self.font = font
                self.refresh_status()
            if not val.get("rec"):                        # 임대가 끝나 멈춰 있었음 → 새로 시작
                self.st["restarts"] += 1
                sess.send("Runtime.evaluate", {"expression": "window.__ghMirrorCtl && window.__ghMirrorCtl.resync('lease')", "silent": True}, cb=lambda m: None)
            if self.state == "busy":
                self._set_state("live", "실시간")
        sess.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "silent": True}, cb=done)

    def run(self):
        backoff = 1.0
        while not self.stop.is_set():
            sess = None
            try:
                sess = self._connect()
                if sess:
                    backoff = 1.0
                    self._watch(sess)
            except (TimeoutError, RuntimeError) as e:      # TimeoutError 는 OSError 의 하위 → 먼저 잡아야 '응답 없음'으로 보임
                first = not self.busy_since
                if first:
                    self.busy_since = time.monotonic()
                if self.state != "crashed":
                    self._set_state("busy", "봇 페이지가 응답하지 않음 (확인 창이 떠 있을 수 있음) — 메뉴의 '앱 새로고침'으로 풀 수 있음")
                self.st["connect_timeouts"] += 1
                if first or self.st["connect_timeouts"] % 20 == 0:   # 확인 창이 오래 떠 있어도 기록이 넘치지 않게
                    log(f"넣기 실패: {type(e).__name__}: {str(e)[:120]} (연속 {int(time.monotonic() - self.busy_since)}초)")
                self._busy_reload()
            except (ConnectionError, OSError, websocket.WebSocketException) as e:
                self.busy_since = 0.0
                if self.state != "crashed":
                    self._set_state("no_chrome", "Chrome(봇 창)에 연결할 수 없음 — 다시 붙는 중")
                if "DevTools 연결 불가" not in str(e):
                    log(f"연결 실패: {type(e).__name__}: {str(e)[:120]}")
            except Exception as e:
                self._set_state("error", "실시간 화면 내부 오류")
                log(f"내부 오류: {type(e).__name__}: {e}")
            finally:
                if sess:
                    sess.close()
                if self.sess is sess:
                    self.sess = None
                self.ctx = None
                if self.dialog:
                    self.dialog = None
                    self.refresh_status()
            self.stop.wait(backoff)
            backoff = min(backoff * 2, 5.0)

    def _busy_reload(self):
        """붙는 동안 확인 창(confirm · prompt)이 이미 떠 있으면 Page.enable 이 막혀서 그 창을 보지도, 2분 뒤 취소하지도 못한다.
        붙기가 BUSY_RELOAD_AFTER 넘게 '응답 없음'이고 봇 상태(요약 수집기)도 '멈춤'이면 앱을 새로고침해서 푼다
        (메뉴의 '앱 새로고침'과 같음 · 10분에 한 번까지 · 그대로 두면 감시가 3분 뒤 Chrome 전체를 다시 띄움)."""
        now = time.monotonic()
        if not self.busy_since or now - self.busy_since < BUSY_RELOAD_AFTER or now - self.busy_reload_at < BUSY_RELOAD_GAP:
            return
        try:
            bot = (self.status_fn() or {}).get("status")
        except Exception:
            bot = None
        if bot != "stuck":
            return
        self.busy_reload_at = now
        self.st["busy_reloads"] += 1
        log(f"봇 페이지가 {int(now - self.busy_since)}초째 응답하지 않아 (확인 창이 떠 있던 것으로 봄) 앱을 새로고침합니다")
        try:
            self.reload()
        except Exception as e:
            log(f"자동 새로고침 실패: {type(e).__name__}")

    def _watch(self, sess):
        next_lease = 0.0
        next_discard = time.monotonic() + 60
        while sess.alive and not self.stop.is_set():
            now = time.monotonic()
            if now >= next_lease or (self.lease_now and not self.lease_sent):
                self.lease_now = False
                next_lease = now + LEASE_EVERY
                self._lease(sess)
            if self.lease_sent and now - self.lease_sent > 20 and self.state == "live":
                self._set_state("busy", "봇 페이지가 바쁨 (응답 대기)")
            if now >= next_discard:                       # 콘솔 기록이 DevTools 쪽에 쌓이지 않게
                next_discard = now + 60
                try:
                    sess.send("Runtime.discardConsoleEntries", cb=lambda m: None)
                except Exception:
                    pass
            d = self.dialog
            if d and now - d["t"] > DIALOG_TIMEOUT:
                log("확인 창에 2분 동안 답이 없어 '취소'로 닫음")
                self.st["dialog_timeouts"] += 1
                try:
                    sess.send("Page.handleJavaScriptDialog", {"accept": False}, cb=lambda m: None)
                except Exception:
                    pass
                d["t"] = now                              # 다음 시도는 다시 2분 뒤
            with self.cond:
                waiting = any(v.waiting for v in self.viewers)
                stale = self.checkout_at and now - self.checkout_at > 15
            if stale:
                self.checkout_at = 0.0
            if waiting and not self.checkout_at:
                self.request_checkout()
            self.refresh_status()
            self.stop.wait(0.5)
        if self.state not in ("crashed", "no_page"):         # (봇 탭이 앱 밖으로 감 · 죽음 안내는 그대로)
            self._set_state("connecting", "봇 화면 연결이 끊김 — 다시 붙는 중")

    # ------------------------------------------------------------ 사용자 조작
    def act(self, a):
        s, ctx = self.sess, self.ctx
        if not s or not s.alive or not ctx:
            raise Unavailable("봇 화면에 연결되어 있지 않습니다")
        if self.dialog:
            raise Conflict("봇에 확인 창이 떠 있습니다 — 먼저 답하세요")
        t0 = time.perf_counter()
        try:
            r = s.call("Runtime.callFunctionOn", {"functionDeclaration": ACT_FN, "arguments": [{"value": a}], "executionContextId": ctx,
                                                  "returnByValue": True, "userGesture": True, "awaitPromise": False, "silent": True}, ACT_TIMEOUT)
        except TimeoutError:
            raise Unavailable("봇 페이지가 응답하지 않습니다 (바쁨 · 확인 창)") from None
        except (ConnectionError, RuntimeError) as e:
            raise Unavailable("봇 화면 연결이 바뀌었습니다 — 다시 시도하세요") from e
        ms = round((time.perf_counter() - t0) * 1000, 1)
        self.act_ms.append(ms)
        self.st["acts"] += 1
        out = (r.get("result") or {}).get("value")
        if not isinstance(out, dict):
            out = {"ok": False, "err": "exception"}
        out = {"ok": bool(out.get("ok")), "err": str(out.get("err", ""))[:30] or None, "pageMs": out.get("ms"), "ms": ms}
        if not out["ok"]:
            self.st["acts_refused"] += 1
        return out

    def answer_dialog(self, seq, accept, text):
        d, s = self.dialog, self.sess
        if not d or d["seq"] != seq:
            raise Conflict("그 확인 창은 이미 닫혔습니다")
        if not s or not s.alive:
            raise Unavailable("봇 화면에 연결되어 있지 않습니다")
        params = {"accept": bool(accept)}
        if d["type"] == "prompt" and accept and isinstance(text, str):
            params["promptText"] = text[:2000]
        try:
            s.call("Page.handleJavaScriptDialog", params, 5)
        except (TimeoutError, RuntimeError, ConnectionError) as e:
            raise Unavailable("확인 창에 답하지 못했습니다") from e
        self.st["dialog_answers"] += 1

    def reload(self):
        """봇 페이지 새로고침 (F5 와 같음). 사무실을 닫았거나 탭이 죽었을 때."""
        s = self.sess
        self.st["reloads"] += 1
        if s and s.alive:
            try:
                s.call("Page.reload", {"ignoreCache": False}, 5)
                return
            except (TimeoutError, RuntimeError, ConnectionError):
                pass
        try:                                              # 잠깐 따로 붙어서
            pages = self._pages()
        except Exception:
            raise Unavailable("Chrome(봇 창)에 연결할 수 없습니다") from None
        method, params = "Page.reload", {}
        if not pages:
            # 봇 탭이 앱이 아닌 곳으로 넘어갔으면: 마지막으로 본 앱 주소로 되돌린다 (앱 주소 형식이 맞을 때만)
            home = (self.origin + "/gh-coin/") if self.origin else ""
            others = []
            if home and self.target_re.match(home):
                with _NO_PROXY.open(self.cdp_base + "/json/list", timeout=3) as r:
                    others = [t for t in json.loads(r.read(4 << 20).decode("utf-8", "replace")) if isinstance(t, dict) and t.get("type") == "page"]
            if len(others) != 1:
                raise Unavailable("봇 페이지가 없습니다")
            pages, method, params = others, "Page.navigate", {"url": home}
            log("봇 탭이 앱 밖에 있어 앱 주소로 되돌립니다")
        ws = websocket.create_connection(_local_ws(pages[0]), timeout=5, suppress_origin=True)
        try:
            ws.send(jdump({"id": 1, "method": method, "params": params}))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                ws.settimeout(max(0.1, deadline - time.monotonic()))
                if json.loads(ws.recv()).get("id") == 1:
                    return
        finally:
            ws.close()

    # ------------------------------------------------------------ 앱 정적 파일 중계 (/app/…)
    def static(self, rel):
        """GET 만 · 정해진 폴더와 확장자만 · /__nuri 는 절대 안 됨. (bytes, content-type) 또는 None."""
        if not isinstance(rel, str) or ".." in rel or "//" in rel or "__nuri" in rel or "\\" in rel or not STATIC_RE.match(rel):
            return None
        now = time.monotonic()
        with self.static_lock:
            hit = self.static_cache.get(rel)
            if hit and now - hit[2] < 300:
                return hit[0], hit[1]
        u = urllib.parse.urlsplit(self.origin or "http://127.0.0.1:17860")
        if u.hostname not in ("127.0.0.1", "localhost") or not (u.port and 17860 <= u.port <= 17869):
            return None
        conn = http.client.HTTPConnection("127.0.0.1", u.port, timeout=5)
        try:
            conn.request("GET", "/" + rel, headers={"Host": f"127.0.0.1:{u.port}", "Accept": "*/*"})
            r = conn.getresponse()                        # 다른 주소로 넘기기(redirect)는 따라가지 않음
            if r.status != 200:
                return None
            data = r.read(MAX_STATIC + 1)
        except (OSError, http.client.HTTPException):
            return None
        finally:
            conn.close()
        if len(data) > MAX_STATIC:
            return None
        ctype = STATIC_TYPES[rel.rsplit(".", 1)[1].lower()]
        with self.static_lock:
            self.static_cache[rel] = (data, ctype, now)
            while sum(len(x[0]) for x in self.static_cache.values()) > 8 << 20:
                self.static_cache.popitem(last=False)
        return data, ctype

    # ------------------------------------------------------------ 숫자
    def stats(self):
        with self.cond:
            viewers = [{"sec": round(time.time() - v.joined), "raw": v.raw, "wire": v.wire, "queued": v.qbytes, "resets": v.resets,
                        "waiting": v.waiting, "visible": v.visible} for v in self.viewers]
            base = {"valid": self.base_valid, "batches": len(self.base), "bytes": self.base_bytes}
        acts = sorted(self.act_ms)
        return {"version": self.version, "state": self.state, "message": self.state_msg, "connected": bool(self.sess and self.sess.alive),
                "contextReady": bool(self.ctx), "viewers": viewers, "base": base, "counters": dict(self.st),
                "lastBatchAgoS": round(time.monotonic() - self.last_batch, 1) if self.last_batch else None,
                "leaseRttMs": self.lease_rtt, "page": self.page_stats, "dialogOpen": bool(self.dialog),
                "actMs": {"n": len(acts), "p50": acts[len(acts) // 2] if acts else None, "max": acts[-1] if acts else None}}
