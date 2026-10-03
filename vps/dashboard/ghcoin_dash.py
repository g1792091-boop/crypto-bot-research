#!/usr/bin/env python3
"""ghcoin-dash: GH Coin 실시간 화면 + 요약 대시보드 (:8080, Tailscale 로만 · 로그인 필요).

GH Coin 은 Chrome 페이지 안에서 돌아가는 봇이다. 이 서비스는 앱 코드를 전혀 바꾸지 않고
Chrome DevTools(127.0.0.1:9222, 서버 안 · ghcoin 계정만)로 그 페이지에 붙어서 두 가지를 한다.

  1. 실시간 화면 ( / ):  봇 화면의 DOM 을 그대로 옮겨 사용자 브라우저가 직접 그리게 한다 (mirror.py + recorder.js + live.*)
     → 원격화면(noVNC, 그림 전송)과 달리 선명하고 부드럽다. 누르기 · 입력 · 선택 · 스크롤 · 확인 창 답하기를 봇에 그대로 전달.
  2. 요약 ( /summary ):  몇 초마다 collector.js 로 '읽기만' 한 숫자를 표 · 카드로 (예전 대시보드, 휴대폰용)
     /healthz 의 봇 상태(감시 ghcoin-watchdog 가 읽음)도 이 수집기가 정한다.

실시간 화면은 봇을 조작할 수 있으므로(실거래 승인 포함) 비밀번호 로그인이 필요하다 (auth.py).
  - /login, /healthz 만 로그인 없이 열린다. 세션 쿠키는 HttpOnly · SameSite=Strict, 모든 POST 는 같은 출처 + CSRF 토큰.
  - 조작 API(/api/act)는 화면에 보이는 노드에 사람이 하는 것과 같은 입력만 한다 (임의 JS · DevTools 명령 전달 없음).
  - /app/… 는 앱의 정적 파일(css · svg · 글꼴 · 그림)만 GET 으로 중계한다 (/__nuri 는 절대 안 됨).
비밀값: 요약은 collector.js + 여기서 두 번 지운다. 실시간 화면은 비밀번호 · 키 칸의 값을 ****** 로만 보낸다 (recorder.js).
접속 기록 · 입력 값은 로그에 남기지 않는다.

필요한 것: Python 3.10+ 표준 라이브러리 + websocket-client (우분투 패키지 python3-websocket).

환경 변수
  GHCOIN_DASH_PORT      (8080)            대시보드 포트
  GHCOIN_DASH_BIND      (0.0.0.0)         대시보드 주소
  GHCOIN_DASH_INTERVAL  (5)               요약 수집 간격(초), 2~60
  GHCOIN_DASH_SLOW      (30)              무거운 항목(감사 기록·파이프라인·적중률 등) 간격(초)
  GHCOIN_DASH_REPORTS   (300)             시간별 발표 간격(초)
  GHCOIN_DASH_HOSTS     ()                Host 헤더로 더 허용할 이름(쉼표 구분). IP·점 없는 이름·*.ts.net·localhost 는 기본 허용
  GHCOIN_DASH_NETS      ()                접속을 더 허용할 주소 대역(쉼표 구분, 예: 192.168.0.0/24). 기본은 이 서버 안 + Tailscale 만
  GHCOIN_DASH_PWFILE    (/etc/ghcoin/dash-password.hash)  비밀번호 파일 (auth.py 참고)
  GHCOIN_DASH_MIRROR    (1)               0 이면 실시간 화면을 끈다 (요약만)
  GHCOIN_CDP            (http://127.0.0.1:9222)  Chrome DevTools 주소 (반드시 이 서버 안: 127.0.0.1/localhost/::1)
  GHCOIN_DASH_FONTDIR   (/usr/share/fonts/truetype/nanum)  봇 화면과 같은 고정폭 글꼴(NanumGothicCoding)을 보는 쪽에도 보내려고 읽는 곳

비밀번호 파일 만들기:  printf '%s\n' '<비밀번호>' | python3 ghcoin_dash.py --make-password-hash > /etc/ghcoin/dash-password.hash
"""
import base64
import gzip
import hashlib
import html
import http.client
import io
import ipaddress
import json
import os
import re
import signal
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import websocket  # python3-websocket (websocket-client)
except ImportError:  # pragma: no cover
    sys.stderr.write("python3-websocket 이 필요합니다:  sudo apt-get install -y python3-websocket\n")
    sys.exit(2)

# 요청 머리글 크기 제한: 기본값(100줄 × 64KB)이면 연결 하나가 6MB 넘게 잡을 수 있다
http.client._MAXHEADERS = 32
http.client._MAXLINE = 8192

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "2.0"
sys.path.insert(0, HERE)
import auth as authmod      # noqa: E402  (같은 폴더)
import mirror as mirrormod  # noqa: E402


def _env_num(name, default, lo, hi, cast=float):
    try:
        v = cast(os.environ.get(name, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


PORT = _env_num("GHCOIN_DASH_PORT", 8080, 1, 65535, int)
BIND = os.environ.get("GHCOIN_DASH_BIND", "0.0.0.0").strip() or "0.0.0.0"
INTERVAL = _env_num("GHCOIN_DASH_INTERVAL", 5, 2, 60)
SLOW_EVERY = _env_num("GHCOIN_DASH_SLOW", 30, 5, 3600)
REPORT_EVERY = _env_num("GHCOIN_DASH_REPORTS", 300, 30, 86400)
CDP_BASE = os.environ.get("GHCOIN_CDP", "http://127.0.0.1:9222").rstrip("/")
EXTRA_HOSTS = {h.strip().lower() for h in os.environ.get("GHCOIN_DASH_HOSTS", "").split(",") if h.strip()}
EVAL_WAIT = min(20.0, INTERVAL)          # 한 번에 답을 기다리는 시간 (못 받으면 다음 차례에 이어서 기다림, 새로 보내지 않음)
SLOW_AFTER = 20.0                       # 이만큼 답이 없으면 '응답 지연'
STUCK_AFTER = 120.0                     # 이만큼 답이 없으면 '봇 멈춤' (확인 창 · 죽은 탭)
STALE_AFTER = max(3 * INTERVAL, 20.0)   # 이보다 오래된 자료는 '오래됨' 표시
RETRY_MAX = 5.0                         # Chrome 에 다시 붙는 간격 상한 (이 서버 안 호출이라 가벼움)
WATCHDOG_S = max(120.0, 3 * INTERVAL + 60)  # 수집기가 이만큼 멈추면 서비스를 끝내 systemd 가 다시 켜게 함
MAX_SSE = 16                            # 동시에 열린 실시간 연결 수 (넘으면 가장 오래된 것을 끊음)
MAX_CONN = 64                           # 동시에 처리하는 HTTP 연결 수 (넘으면 바로 끊음)
MAX_CONN_PER_IP = 16                    # 주소 하나가 잡을 수 있는 연결 수 (느리게 보내는 연결로 자리를 다 채우지 못하게)
MAX_CONN_LOCAL = 32                     # 이 서버 안(127.0.0.1 · tailscale serve 를 거친 접속은 모두 이 주소)
HEADER_DEADLINE = 20.0                  # 요청 머리글(+본문)을 다 받기까지 전체 시간 (한 바이트씩 천천히 보내는 연결 끊기)
MAX_SNAPSHOT_BYTES = 768 * 1024         # 상태 사진 크기 상한 (넘으면 목록을 더 줄인다)
CHROME_UNIT = "/etc/systemd/system/ghcoin-chrome.service"
TARGET_RE = re.compile(r"^http://(127\.0\.0\.1|localhost):1786[0-9]/gh-coin/(index\.html)?([?#].*)?$")  # 앱 창 (실행기는 17860~17869 중 빈 포트)
OPT_MARK = "/*OPT*/{}"

# 접속 허용 주소: 이 서버 안(loopback) + Tailscale (100.64.0.0/10, fd7a:115c:a1e0::/48)
ALLOWED_NETS = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "::1/128", "100.64.0.0/10", "fd7a:115c:a1e0::/48")]
for _n in os.environ.get("GHCOIN_DASH_NETS", "").split(","):
    if _n.strip():
        try:
            ALLOWED_NETS.append(ipaddress.ip_network(_n.strip(), strict=False))
        except ValueError:
            sys.stderr.write(f"GHCOIN_DASH_NETS 무시: {_n.strip()}\n")


def addr_ok(a):
    try:
        ip = ipaddress.ip_address(str(a).split("%", 1)[0])
    except ValueError:
        return False
    ip = getattr(ip, "ipv4_mapped", None) or ip
    return any(ip in n for n in ALLOWED_NETS if n.version == ip.version)


# ---------------------------------------------------------------- 비밀 지우기 (collector.js 다음의 두 번째 안전장치: 키 이름·형식만)
BAD_KEY = re.compile(r"key|secret|token|pass|jwt|sign|seed|mnemonic|private", re.I)
ALLOW_TOP = {"signals"}  # 최상위 '타점 신호' 목록 이름만 예외 (정확히 이 이름만)
_LONG = re.compile(r"[A-Za-z0-9_\-+/=]{32,}")
SECRET_PATTERNS = [
    (re.compile("…[A-Za-z0-9_\\-]{2,8}"), "…****"),
    (re.compile(r"\b(?:nvapi-|sk-(?:ant-|or-|proj-)?|gsk_|tvly-|csk-|xai-|hf_|pplx-|AIza|ghp_|github_pat_|glpat-|BSA)[A-Za-z0-9_\-]{8,}"), "[가림]"),
    (re.compile(r"eyJ[\w-]{6,}\.[\w-]{6,}\.[\w-]{6,}"), "[가림]"),
    (re.compile(r"\bBearer\s+[\w\-.~+/=]{8,}", re.I), "Bearer [가림]"),
    (re.compile(r"\b(?:0x)?[0-9a-fA-F]{40,}\b"), "[가림]"),
]


def _long_sub(m):
    s = m.group(0)
    if re.search(r"[A-Z]", s) and re.search(r"[a-z]", s) and re.search(r"[0-9]", s):
        return "[가림]"
    return s


def scrub_str(s):
    for rx, to in SECRET_PATTERNS:
        s = rx.sub(to, s)
    return _LONG.sub(_long_sub, s)


def scrub(v, depth=0):
    if depth > 16:
        return None
    if isinstance(v, str):
        return scrub_str(v)
    if isinstance(v, list):
        return [scrub(x, depth + 1) for x in v]
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            k = str(k)
            if BAD_KEY.search(k) and not (depth == 0 and k in ALLOW_TOP):
                continue
            out[k] = scrub(x, depth + 1)
        return out
    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
        return None
    return v


def jdump(v):
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


# ---------------------------------------------------------------- Chrome DevTools 연결
class NoTarget(Exception):
    pass


class JSError(Exception):
    pass


class Busy(Exception):
    """보낸 읽기에 아직 답이 없음 (페이지가 바쁨 · 확인 창 · 죽은 탭). 연결은 그대로 두고 다음 차례에 이어서 기다린다."""

    def __init__(self, waited):
        super().__init__(f"{waited:.0f}초째 답 없음")
        self.waited = waited


class PageCrashed(ConnectionError):
    pass


def _check_local(url):
    host = urllib.parse.urlsplit(url).hostname or ""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(f"DevTools 주소는 이 서버 안이어야 합니다: {url}")


_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # http_proxy 설정을 따르지 않음


class CDP:
    """GH Coin 페이지 하나에 대한 DevTools 웹소켓 (Runtime.evaluate 만 보냄, 한 번에 하나만)."""

    def __init__(self, base):
        _check_local(base)
        self.base = base
        self.ws = None
        self.ws_url = ""
        self.tid = ""             # 페이지(탭) id
        self.target = None        # 화면에 보여 줄 페이지 정보 (주소는 경로까지만)
        self.multi = 0
        self.browser = ""
        self.seq = 0
        self.pending = None       # (id, 보낸 시각, opt) — 답을 기다리는 읽기
        self.crashed = set()      # Chrome 이 '죽었다'고 알린 탭 id

    def _get(self, path):
        with _NO_PROXY.open(self.base + path, timeout=3) as r:
            return json.loads(r.read(4 << 20).decode("utf-8", "replace"))

    def pages(self):
        try:
            lst = self._get("/json/list")
        except Exception as e:
            raise ConnectionError(f"Chrome DevTools({self.base}) 에 연결할 수 없음: {e}") from None
        return [t for t in lst if isinstance(t, dict) and t.get("type") == "page" and TARGET_RE.match(str(t.get("url", "")))]

    def connect(self):
        self.close()
        pages = self.pages()
        if not pages:
            raise NoTarget("GH Coin 페이지가 아직 없음 (Chrome 이 켜지는 중일 수 있음)")
        t = pages[0]
        ws_url = str(t.get("webSocketDebuggerUrl") or "")
        if not ws_url.startswith("ws://"):
            raise NoTarget("페이지에 이미 다른 DevTools 가 붙어 있어 주소가 없음")
        _check_local(ws_url.replace("ws://", "http://", 1))
        try:
            self.browser = str(self._get("/json/version").get("Browser", ""))[:60]
        except Exception:
            self.browser = ""
        # Chrome 111+ 는 Origin 헤더가 있는 웹소켓을 거절한다 → Origin 을 보내지 않는다 (--remote-allow-origins 불필요)
        self.ws = websocket.create_connection(ws_url, timeout=10, suppress_origin=True, enable_multithread=False)
        self.ws_url = ws_url
        self.tid = str(t.get("id", ""))[:64]
        u = urllib.parse.urlsplit(str(t.get("url", "")))
        self.target = {"id": self.tid[:12], "url": f"{u.scheme}://{u.netloc}{u.path}"[:120], "title": scrub_str(str(t.get("title", ""))[:60])}
        self.multi = len(pages)
        self.pending = None

    def evaluate(self, expression, opt, wait):
        """읽기 하나. 이미 보낸 것이 답을 기다리고 있으면 새로 보내지 않고 그 답을 기다린다.
        돌려주는 값: (결과, 그 읽기의 opt, 보낸 뒤 걸린 초)."""
        if not self.ws:
            raise ConnectionError("연결 안 됨")
        if self.pending is None:
            self.seq += 1
            self.ws.settimeout(10)
            self.ws.send(jdump({"id": self.seq, "method": "Runtime.evaluate", "params": {
                "expression": expression, "awaitPromise": True, "returnByValue": True, "silent": True,
                "userGesture": False, "includeCommandLineAPI": False, "generatePreview": False, "replMode": False}}))
            self.pending = (self.seq, time.monotonic(), opt)
        mid, sent, popt = self.pending
        deadline = time.monotonic() + wait
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise Busy(time.monotonic() - sent)
            self.ws.settimeout(left)
            try:
                raw = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                raise Busy(time.monotonic() - sent) from None
            if not raw:
                raise ConnectionError("DevTools 연결이 닫힘")
            msg = json.loads(raw)
            meth = msg.get("method")
            if meth == "Inspector.targetCrashed":
                self.crashed.add(self.tid)
                raise PageCrashed("봇 페이지(탭)가 죽음")
            if meth == "Inspector.detached":
                raise ConnectionError("DevTools 연결이 떨어짐: " + str((msg.get("params") or {}).get("reason", ""))[:60])
            if msg.get("id") != mid:
                continue
            self.pending = None
            took = time.monotonic() - sent
            if "error" in msg:
                raise JSError(str(msg["error"].get("message", msg["error"]))[:300])
            res = msg.get("result", {})
            if res.get("exceptionDetails"):
                d = res["exceptionDetails"]
                desc = (d.get("exception") or {}).get("description") or d.get("text") or "JS 오류"
                raise JSError(str(desc).splitlines()[0][:300])
            return (res.get("result") or {}).get("value"), popt, took

    def needs_reconnect(self):
        """오래 답이 없을 때 확인: 탭이 바뀌었거나, 다른 연결로 보낸 아주 작은 식("1")에 페이지가 바로 답하면
        (= 우리가 기다리던 답만 사라진 것) True. 페이지가 정말 바쁘거나 멈췄으면 False."""
        try:
            if not any(str(t.get("id", ""))[:64] == self.tid for t in self.pages()):
                return True
        except ConnectionError:
            return True
        try:
            ws = websocket.create_connection(self.ws_url, timeout=3, suppress_origin=True, enable_multithread=False)
        except Exception:
            return False
        try:
            ws.send(jdump({"id": 1, "method": "Runtime.evaluate", "params": {"expression": "1", "returnByValue": True, "silent": True}}))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                ws.settimeout(max(0.1, deadline - time.monotonic()))
                msg = json.loads(ws.recv())
                if msg.get("id") == 1:
                    return "result" in msg
        except Exception:
            return False
        finally:
            try:
                ws.close()
            except Exception:
                pass
        return False

    def close(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        self.ws = None
        self.pending = None


# ---------------------------------------------------------------- 서버 상태 (호스트 · 이 서비스)
def _meminfo():
    out = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, rest = line.partition(":")
                if k in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
                    out[k] = int(rest.split()[0]) // 1024
    except OSError:
        pass
    return out


def _rss_mb(pid="self"):
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def _chrome_rss_mb():
    total, n = 0.0, 0
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/comm") as f:
                comm = f.read().strip()
        except OSError:
            continue
        if comm in ("chrome", "chromium", "chrome_crashpad", "chrome_crashpad_handler"):
            total += _rss_mb(pid)
            n += 1
    return round(total), n


def _unit_lacks_cdp():
    """install-ghcoin.sh 를 다시 실행해서 앱 창 설정에서 읽기 통로(--remote-debugging-port)가 빠졌는지."""
    try:
        with open(CHROME_UNIT, encoding="utf-8", errors="replace") as f:
            return "--remote-debugging-port=" not in f.read()
    except OSError:
        return False


class Stats:
    def __init__(self):
        self.started = time.time()
        self.polls = 0
        self.ok = 0
        self.errors = 0
        self.reconnects = 0
        self.last_ok = 0.0
        self.last_error = None
        self.last_eval_ms = None
        self.avg_eval_ms = None
        self.page_took_ms = None
        self.snapshot_bytes = 0
        self.status = "starting"
        self.message = "시작하는 중"
        self.down_since = None        # Chrome 에 못 붙기 시작한 때 (monotonic)
        self._cpu = (time.monotonic(), sum(os.times()[:2]))
        self.cpu_pct = 0.0
        self._chrome = (0, 0)
        self._chrome_t = 0.0

    def set(self, status, message, err=None):
        if status != self.status and status not in ("ok", "booting", "starting"):
            self.errors += 1
        self.status, self.message = status, message
        if err is not None:
            self.last_error = {"t": int(time.time() * 1000), "msg": scrub_str(str(err))[:300]}

    def sample(self):
        now_m, cpu = time.monotonic(), sum(os.times()[:2])
        dt = now_m - self._cpu[0]
        if dt >= 1:
            self.cpu_pct = round((cpu - self._cpu[1]) / dt * 100, 2)
            self._cpu = (now_m, cpu)
        if now_m - self._chrome_t > 30:
            self._chrome = _chrome_rss_mb()
            self._chrome_t = now_m

    def server(self, sse_clients, cdp):
        mi = _meminfo()
        try:
            la = [round(x, 2) for x in os.getloadavg()]
        except OSError:
            la = []
        try:
            st = os.statvfs("/")
            disk = {"totalGb": round(st.f_blocks * st.f_frsize / 2**30, 1), "freeGb": round(st.f_bavail * st.f_frsize / 2**30, 1)}
        except OSError:
            disk = {}
        try:
            with open("/proc/uptime") as f:
                host_up = int(float(f.read().split()[0]))
        except (OSError, ValueError):
            host_up = None
        return {
            "version": VERSION, "now": int(time.time() * 1000), "startedAt": int(self.started * 1000), "uptimeS": int(time.time() - self.started),
            "intervalS": INTERVAL, "slowS": SLOW_EVERY, "polls": self.polls, "okPolls": self.ok, "errorCount": self.errors, "reconnects": self.reconnects,
            "lastOk": int(self.last_ok * 1000) if self.last_ok else None, "lastError": self.last_error,
            "lastEvalMs": self.last_eval_ms, "avgEvalMs": self.avg_eval_ms, "pageTookMs": self.page_took_ms, "snapshotBytes": self.snapshot_bytes,
            "rssMb": round(_rss_mb(), 1), "cpuPct": self.cpu_pct, "sseClients": sse_clients,
            "chrome": {"connected": bool(cdp.ws), "target": cdp.target, "pages": cdp.multi, "browser": cdp.browser,
                       "waitingS": round(time.monotonic() - cdp.pending[1], 1) if cdp.pending else None,
                       "rssMb": self._chrome[0], "procs": self._chrome[1]},
            "host": {"name": socket.gethostname()[:40], "cpus": os.cpu_count(), "load": la, "uptimeS": host_up,
                     "memTotalMb": mi.get("MemTotal"), "memAvailMb": mi.get("MemAvailable"), "swapTotalMb": mi.get("SwapTotal"), "swapFreeMb": mi.get("SwapFree"),
                     "disk": disk},
        }


# ---------------------------------------------------------------- 상태 저장 + 실시간(SSE) 배포
class Hub:
    def __init__(self):
        self.cond = threading.Condition()
        self.version = 0
        self.sections = {}        # 이름 -> JSON 문자열 (비밀 지운 뒤)
        self.sec_ver = {}         # 이름 -> 바뀐 버전
        self.raw_cache = {}       # 이름 -> 지우기 전 JSON (안 바뀐 부분은 다시 지우지 않음)
        self.sec_errors = {}      # 수집 항목 -> {msg, t}
        self.meta = {}
        self.server = {}
        self.streams = []         # 열린 실시간 연결 (오래된 것부터)
        self.sse = 0

    def merge(self, snap):
        with self.cond:
            changed = self._merge(snap)
            self._shrink()
            return changed

    def _merge(self, snap):
        changed = []
        for k, v in snap.items():
            if k in ("secs", "errors"):
                continue
            raw = jdump(v)
            if self.raw_cache.get(k) == raw:
                continue
            self.raw_cache[k] = raw
            clean = scrub({k: v})            # 최상위 이름 규칙(ALLOW_TOP) 도 그대로 적용
            if k not in clean:
                continue
            self.sections[k] = jdump(clean[k])
            changed.append(k)
        t = int(time.time() * 1000)
        failed = {e.get("sec"): e.get("msg") for e in (snap.get("errors") or []) if isinstance(e, dict)}
        for s in snap.get("secs") or []:
            if s in failed:
                self.sec_errors[s] = {"msg": scrub_str(str(failed[s]))[:200], "t": t}
            else:
                self.sec_errors.pop(s, None)
        if "import" in failed:
            self.sec_errors["import"] = {"msg": scrub_str(str(failed["import"]))[:200], "t": t}
        return changed

    def _shrink(self):
        """상태 사진이 너무 크면 긴 목록부터 줄인다 (보통은 일어나지 않음)."""
        for name, keep in (("feed", 20), ("trades", 20), ("strategies", 12)):
            if sum(len(s) for s in self.sections.values()) <= MAX_SNAPSHOT_BYTES:
                return
            try:
                lst = json.loads(self.sections.get(name, "[]"))
                if isinstance(lst, list) and len(lst) > keep:
                    self.sections[name] = jdump(lst[:keep])
            except ValueError:
                pass

    def publish(self, changed, meta, server):
        meta, server = scrub(meta), scrub(server)
        with self.cond:
            self.version += 1
            for k in changed:
                self.sec_ver[k] = self.version
            self.meta = meta
            self.server = server
            self.cond.notify_all()

    def body(self, since=0):
        """since 이후 바뀐 부분 + meta/server 를 JSON 문자열로."""
        with self.cond:
            parts = [f'"{k}":{s}' for k, s in self.sections.items() if self.sec_ver.get(k, 0) > since]
            meta = dict(self.meta)
            parts.append('"errors":' + jdump([{"sec": k, **v} for k, v in sorted(self.sec_errors.items())]))
            parts.append('"meta":' + jdump(meta))
            parts.append('"server":' + jdump(self.server))
            if since == 0:
                parts.append(f'"stale":{"true" if meta.get("stale") else "false"}')
                parts.append(f'"age_s":{jdump(meta.get("ageS"))}')
            return "{" + ",".join(parts) + "}", self.version

    def join_stream(self, sock):
        """실시간 연결 등록. 자리가 없으면 가장 오래된 연결(대개 잠든 휴대폰 탭)을 끊고 새 연결을 받는다."""
        me = {"sock": sock, "gone": False}
        victims = []
        with self.cond:
            while len(self.streams) >= MAX_SSE:
                v = self.streams.pop(0)
                v["gone"] = True
                victims.append(v)
            self.streams.append(me)
            self.sse = len(self.streams)
            if victims:
                self.cond.notify_all()
        for v in victims:                      # 소켓 정리는 잠금 밖에서
            try:
                v["sock"].shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        return me

    def leave_stream(self, me):
        with self.cond:
            self.streams = [s for s in self.streams if s is not me]
            self.sse = len(self.streams)


HUB = Hub()
STATS = Stats()
STOP = threading.Event()
LAST_TICK = time.monotonic()
COLLECTOR = None


def build_meta(cdp):
    age = (time.time() - STATS.last_ok) if STATS.last_ok else None
    stale = age is None or age > STALE_AFTER or STATS.status != "ok"
    down = round(time.monotonic() - STATS.down_since) if STATS.down_since else None
    return {"status": STATS.status, "message": STATS.message, "stale": stale, "ageS": None if age is None else round(age, 1),
            "lastOk": int(STATS.last_ok * 1000) if STATS.last_ok else None, "now": int(time.time() * 1000),
            "connected": bool(cdp.ws), "pages": cdp.multi, "intervalS": INTERVAL, "downS": down}


def load_collector():
    with open(os.path.join(HERE, "collector.js"), encoding="utf-8") as f:
        src = f.read()
    if src.count(OPT_MARK) != 1:
        raise ValueError("collector.js 의 /*OPT*/{} 표시가 정확히 한 번 있어야 합니다")
    return src


MSG_CRASHED = "봇 페이지(탭)가 죽었습니다 — 실시간 화면 메뉴의 '앱 새로고침' 또는  sudo systemctl restart ghcoin-chrome (3분 뒤 감시가 자동으로 다시 띄움)"
MSG_NO_APP = "봇 페이지가 열리지 않음 (Chrome 오류 화면) —  sudo systemctl restart ghcoin-server ghcoin-chrome"


def poll_once(cdp, src, st):
    """한 번 읽기. st = {tid, last_slow, last_rep} (무거운 항목 시각). 바뀐 부분 이름 목록을 돌려준다."""
    if not cdp.ws:
        cdp.connect()
        STATS.reconnects += 1
        STATS.down_since = None
        if STATS.status in ("starting", "no_chrome", "no_page"):
            STATS.set("booting", "봇 창에 연결됨 — 첫 자료를 기다리는 중")
        if cdp.tid != st.get("tid"):           # 다른 탭이면 무거운 항목도 바로 한 번 (오류 뒤 다시 붙은 것만으로는 안 함)
            st["tid"] = cdp.tid
            st["last_slow"] = st["last_rep"] = 0.0
    expr = opt = None
    if cdp.pending is None:
        now = time.monotonic()
        opt = {"slow": not st["last_slow"] or now - st["last_slow"] >= SLOW_EVERY, "reports": not st["last_rep"] or now - st["last_rep"] >= REPORT_EVERY}
        expr = src.replace(OPT_MARK, "/*OPT*/" + jdump(opt))
        STATS.polls += 1
    val, popt, took = cdp.evaluate(expr, opt, EVAL_WAIT)
    cdp.crashed.discard(cdp.tid)
    ms = round(took * 1000, 1)
    STATS.last_eval_ms = ms
    STATS.avg_eval_ms = ms if STATS.avg_eval_ms is None else round(STATS.avg_eval_ms * 0.9 + ms * 0.1, 1)
    if not isinstance(val, dict):
        raise JSError("수집 결과가 비어 있음")
    if val.get("ok"):
        now = time.monotonic()
        STATS.ok += 1
        STATS.last_ok = time.time()
        STATS.set("ok", "실시간")
        STATS.page_took_ms = val.get("tookMs")
        if (popt or {}).get("slow"):
            st["last_slow"] = now
        if (popt or {}).get("reports"):
            st["last_rep"] = now
        changed = HUB.merge(val)
        STATS.snapshot_bytes = sum(len(s) for s in HUB.sections.values())
        return changed
    why = str(val.get("why", "알 수 없음"))
    if val.get("booting"):
        STATS.set("booting", "봇 창이 켜지는 중 (켜진 뒤 30초 기다림)")
        st["last_slow"] = st["last_rep"] = 0.0
    elif why in ("error_page", "not_gh_coin_page"):
        STATS.set("no_app", MSG_NO_APP, why)
    else:
        STATS.set("error", f"수집 불가: {why[:120]}", why)
    return []


def collector_loop(src):
    global LAST_TICK
    cdp = CDP(CDP_BASE)
    st = {"tid": None, "last_slow": 0.0, "last_rep": 0.0, "check_t": 0.0}
    backoff, next_try = 1.0, 0.0
    HUB.publish([], build_meta(cdp), STATS.server(HUB.sse, cdp))     # 첫 읽기 전에도 '시작 중' 상태를 알림
    while not STOP.is_set():
        t_tick = LAST_TICK = time.monotonic()
        changed = []
        if cdp.ws or t_tick >= next_try:
            fail = False
            try:
                changed = poll_once(cdp, src, st)
                backoff = 1.0
            except Busy as e:
                # 연결은 그대로 둔다: 새로 보내지 않고 다음 차례에 같은 답을 이어서 기다림 (평가를 쌓지 않음)
                mins = int(e.waited // 60)
                if cdp.tid in cdp.crashed:
                    STATS.set("crashed", MSG_CRASHED, e)
                elif e.waited >= STUCK_AFTER:
                    STATS.set("stuck", f"봇 페이지가 {mins}분째 응답 없음 — 실시간 화면에서 확인 창이 떠 있는지 확인 (탭이 죽었으면 3분 뒤 자동으로 다시 띄움)", e)
                elif e.waited >= SLOW_AFTER:
                    STATS.set("slow", "봇이 무거운 작업 중이라 응답이 늦음 — 답을 기다리는 중", e)
                if (cdp.tid in cdp.crashed or e.waited >= STUCK_AFTER) and e.waited >= 60 and t_tick - st["check_t"] >= 60:
                    st["check_t"] = t_tick
                    if cdp.needs_reconnect():           # 페이지는 멀쩡한데 기다리던 답만 사라짐 → 새로 붙음
                        STATS.last_error = {"t": int(time.time() * 1000), "msg": "기다리던 답이 사라져 다시 연결"}
                        fail = True
            except PageCrashed as e:
                STATS.set("crashed", MSG_CRASHED, e)
                fail = True
            except NoTarget as e:
                STATS.set("no_page", str(e), e)
                fail = True
            except JSError as e:
                # 오류 객체가 이 연결에 쌓이지 않게 연결을 닫고 다시 붙는다
                STATS.set("error", "페이지 오류", e)
                fail = True
            except (websocket.WebSocketException, ConnectionError, OSError, ValueError) as e:
                if STATS.down_since is None:
                    STATS.down_since = time.monotonic()
                down = time.monotonic() - STATS.down_since
                msg = "Chrome(봇 창)에 연결할 수 없음 — 다시 붙는 중"
                if down > 120:
                    msg = (f"Chrome(봇 창)에 {int(down // 60)}분째 연결할 수 없음 — " +
                           ("앱 창 설정에서 읽기 통로(9222)가 빠졌습니다 (install-ghcoin.sh 를 다시 실행했나요?). " if _unit_lacks_cdp() else "") +
                           "sudo bash add-dashboard.sh 다시 실행")
                STATS.set("no_chrome", msg, f"{type(e).__name__}: {e}")
                fail = True
            except Exception as e:  # 예상 못 한 오류에도 수집은 계속
                STATS.set("error", "수집기 내부 오류", f"{type(e).__name__}: {e}")
                sys.stderr.write(f"collector: {type(e).__name__}: {e}\n")
                fail = True
            if fail:
                cdp.close()
                next_try = time.monotonic() + backoff   # 1→2→4→5초 간격으로 다시 시도
                backoff = min(backoff * 2, RETRY_MAX)
        try:
            STATS.sample()
            HUB.publish(changed, build_meta(cdp), STATS.server(HUB.sse, cdp))   # 끊겨 있어도 상태(오래됨)는 계속 알림
        except Exception as e:
            sys.stderr.write(f"publish: {type(e).__name__}: {e}\n")
        STOP.wait(max(0.2, INTERVAL - (time.monotonic() - t_tick)))
    cdp.close()


# ---------------------------------------------------------------- HTTP
AUTH = authmod.Auth()
ACT_LIMIT = authmod.Bucket(rate=25.0, burst=60.0)     # 세션별 조작 속도 (클릭 · 입력 · 휠)
MIRROR = None
MIRROR_THREAD = None
MAX_BODY = 64 * 1024
LIVE_CHECK_S = 60                                    # 실시간 연결 중에도 이 간격으로 로그인 유효한지 다시 확인

CSP_LIVE = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; "
            "connect-src 'self'; frame-src 'self'; child-src 'self'; media-src 'none'; object-src 'none'; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'")
CSP_LOGIN = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
CSP_STATIC = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"

# 로그인한 사람만 받는 이 폴더의 파일 (주소 -> (파일, 종류))
FILES = {
    "/live.js": ("live.js", "text/javascript; charset=utf-8"),
    "/live.css": ("live.css", "text/css; charset=utf-8"),
    "/vendor/rrweb-replay.min.js": ("vendor/rrweb-replay.min.js", "text/javascript; charset=utf-8"),
    "/vendor/rrweb-replay.css": ("vendor/rrweb-replay.css", "text/css; charset=utf-8"),
}
PAGES = {"/": "live", "/index.html": "live", "/summary": "summary", "/summary.html": "summary"}
# 봇 화면과 같은 글꼴 파일 (사무실 · 채팅은 고정폭 'D2Coding, NanumGothicCoding, …' → 서버에는 NanumGothicCoding).
# 보는 쪽(Windows · 휴대폰)이 다른 글꼴로 그리면 줄바꿈 · 높이가 달라져 채팅 스크롤 위치가 어긋난다 → 같은 파일을 쓰게 한다.
FONT_DIR = os.environ.get("GHCOIN_DASH_FONTDIR", "/usr/share/fonts/truetype/nanum")
FONTS = {"/fonts/nanum-coding.ttf": "NanumGothicCoding.ttf", "/fonts/nanum-coding-bold.ttf": "NanumGothicCodingBold.ttf"}
ACT_MAX_AGE_MS = 10000                               # 이보다 늦게 도착한 조작은 버림 (끊겼던 연결이 돌아오며 한꺼번에 들어오는 클릭)


class Files:
    """이 폴더의 파일을 메모리에 (바뀌면 다시 읽음). gzip 본 · ETag · 인라인 스크립트 해시(CSP)."""

    def __init__(self):
        self.cache = {}
        self.lock = threading.Lock()

    def get(self, name):
        path = os.path.join(HERE, name)
        try:
            st = os.stat(path)
        except OSError:
            return None
        key = (st.st_mtime_ns, st.st_size)
        with self.lock:
            e = self.cache.get(name)
            if e and e["key"] == key:
                return e
        with open(path, "rb") as f:
            body = f.read()
        e = {"key": key, "body": body, "gz": gzip.compress(body, 9) if len(body) > 2048 else None,
             "etag": '"' + hashlib.sha256(body).hexdigest()[:20] + '"'}
        if name.endswith(".html"):
            hashes = ["'sha256-" + base64.b64encode(hashlib.sha256(x.encode("utf-8")).digest()).decode() + "'"
                      for x in re.findall(r"<script>(.*?)</script>", body.decode("utf-8"), re.S)]
            e["csp"] = ("default-src 'none'; script-src " + (" ".join(hashes) or "'none'") +
                        "; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        with self.lock:
            self.cache[name] = e
        return e


FILECACHE = Files()


def host_ok(host_header):
    host = (host_header or "").strip().lower()
    if not host:
        return False
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    if host in EXTRA_HOSTS or host == "localhost" or host.endswith(".ts.net") or host.endswith(".localhost"):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    return "." not in host and re.fullmatch(r"[a-z0-9-]{1,63}", host) is not None


def bot_status():
    m = HUB.meta or {}
    return {"status": m.get("status", STATS.status), "message": m.get("message", STATS.message)}


class _DeadlineIO(io.RawIOBase):
    """요청을 읽는 동안 '전체' 시간 제한 (handler._deadline). 읽기 한 번의 제한(10초)만으로는
    한 바이트씩 천천히 보내는 연결이 자리를 끝없이 잡을 수 있다."""

    def __init__(self, handler):
        super().__init__()
        self.h = handler

    def readable(self):
        return True

    def readinto(self, b):
        h = self.h
        d = h._deadline
        if d is not None:
            left = d - time.monotonic()
            if left <= 0:
                raise TimeoutError("요청을 너무 천천히 보냄")
            h.connection.settimeout(min(h.timeout, max(0.5, left)))
        return h.connection.recv_into(b)


class Handler(BaseHTTPRequestHandler):
    server_version = "ghcoin-dash"
    protocol_version = "HTTP/1.1"
    timeout = 10              # 읽기 한 번 기다리는 시간 (느리게 보내는 연결이 자리를 오래 잡지 못하게)
    _deadline = None

    def version_string(self):
        return self.server_version

    def log_message(self, fmt, *args):  # 접속 기록은 남기지 않는다 (journald 절약 · 입력 값 보호)
        pass

    def setup(self):
        super().setup()
        orig, self.rfile = self.rfile, io.BufferedReader(_DeadlineIO(self), 65536)
        orig.close()

    def handle_one_request(self):
        self._deadline = time.monotonic() + HEADER_DEADLINE     # 요청 줄 + 머리글 (keep-alive 로 기다리는 시간 포함)
        try:
            super().handle_one_request()
        finally:
            self._deadline = None

    def parse_request(self):
        ok = super().parse_request()
        self._deadline = None                                   # 머리글을 다 받음 (본문은 _body 가 따로)
        try:
            self.connection.settimeout(self.timeout)
        except OSError:
            return False
        if not ok:
            return False
        # 방화벽(ufw)이 꺼져도: 보낸 쪽과 받은 주소가 모두 이 서버 안 · Tailscale 일 때만 받는다
        try:
            local = self.connection.getsockname()[0]
        except OSError:
            return False
        if not (addr_ok(self.client_address[0]) and addr_ok(local)):
            self._send(403, "text/plain; charset=utf-8", "Tailscale 로만 접속할 수 있습니다\n", {"Connection": "close"})
            return False
        if self.headers.get("Transfer-Encoding"):               # 본문 길이를 두 가지로 말하는 요청 (tailscale serve 뒤에서 요청 밀반입 방지)
            self.close_connection = True
            self._send(400, "text/plain; charset=utf-8", "Transfer-Encoding 은 받지 않습니다\n", {"Connection": "close"})
            return False
        return True

    # ------------------------------------------------------------ 보내기
    def _head(self, code, ctype, length=None, extra=None, cache="no-store"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        for k, v in (extra or {}).items():
            if isinstance(v, list):
                for x in v:
                    self.send_header(k, x)
            else:
                self.send_header(k, v)
        self.end_headers()

    def _send(self, code, ctype, body, extra=None, cache="no-store"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self._head(code, ctype, len(body), extra, cache)
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj, extra=None):
        self._send(code, "application/json; charset=utf-8", jdump(obj), extra)

    def _redirect(self, to, extra=None):
        self._send(303, "text/plain; charset=utf-8", "", dict({"Location": to}, **(extra or {})))

    def _file(self, name, ctype, extra=None, cache="private, no-cache"):
        e = FILECACHE.get(name)
        if not e:
            return self._send(404, "text/plain; charset=utf-8", "없는 파일입니다\n")
        if self.headers.get("If-None-Match") == e["etag"]:
            return self._send(304, ctype, b"", {"ETag": e["etag"]}, cache=cache)
        hdr = dict({"ETag": e["etag"], "Vary": "Accept-Encoding"}, **(extra or {}))
        body = e["body"]
        if e["gz"] and "gzip" in (self.headers.get("Accept-Encoding") or ""):
            body = e["gz"]
            hdr["Content-Encoding"] = "gzip"
        self._send(200, ctype, body, hdr, cache=cache)

    def _event_stream_ok(self):
        """SSE 주소는 EventSource(fetch) 로만: 화면에 섞여 온 <video poster="/api/live"> · <img> 같은 것이
        로그인된 내 브라우저로 실시간 연결을 몰래 여러 개 열어 진짜 연결을 밀어내지 못하게."""
        return ("text/event-stream" in (self.headers.get("Accept") or "") and
                self.headers.get("Sec-Fetch-Dest") in (None, "empty"))

    # ------------------------------------------------------------ 로그인 확인
    def _cookies(self):
        out = {}
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k and k not in out:
                out[k] = v.strip()
        return out

    def _session(self):
        return AUTH.session(self._cookies().get(authmod.COOKIE))

    def _secure(self):
        # tailscale serve(HTTPS) 뒤에서만 Secure 쿠키 (그냥 http://100.x:8080 은 Tailscale 이 암호화하지만 브라우저는 http 로 봄)
        return self.headers.get("X-Forwarded-Proto", "").lower() == "https" and self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def _same_origin(self):
        origin, host = self.headers.get("Origin"), self.headers.get("Host")
        if not origin or not host:
            return False
        u = urllib.parse.urlsplit(origin)
        if u.scheme not in ("http", "https") or u.netloc.lower() != host.strip().lower():
            return False
        return self.headers.get("Sec-Fetch-Site") in (None, "same-origin")

    def _need_login(self, path, query):
        if path in PAGES:
            nxt = "/summary" if PAGES[path] == "summary" else "/"
            # 다른 앱의 링크로 열면 SameSite=Strict 쿠키가 안 실린다 → 로그인한 적 있으면 같은 사이트에서 한 번 더 열어 본다
            if self._cookies().get(authmod.MARK_COOKIE) == "1" and "r=1" not in query:
                return self._send(200, "text/html; charset=utf-8",
                                  f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url={nxt}?r=1"><title>GH Coin</title>',
                                  {"Content-Security-Policy": "default-src 'none'"})
            return self._redirect("/login?next=" + urllib.parse.quote(nxt))
        return self._json(401, {"ok": False, "err": "로그인이 필요합니다"})

    # ------------------------------------------------------------ GET
    def _route(self):
        if not host_ok(self.headers.get("Host")):
            return self._send(403, "text/plain; charset=utf-8", "허용되지 않은 주소입니다 (GHCOIN_DASH_HOSTS 참고)\n")
        u = urllib.parse.urlsplit(self.path)
        path = u.path
        if path == "/healthz":
            m = HUB.meta or {}
            return self._json(200, {"ok": True, "status": m.get("status", STATS.status), "chrome": bool(m.get("connected")), "stale": m.get("stale", True),
                                    "age_s": m.get("ageS"), "uptime_s": int(time.time() - STATS.started),
                                    "mirror": MIRROR.state if MIRROR else "off"})
        if path == "/login":
            nxt = (urllib.parse.parse_qs(u.query).get("next") or ["/"])[0]
            nxt = nxt if nxt in ("/", "/summary") else "/"
            if self._session():
                return self._redirect(nxt)
            return self._login_page("", nxt=nxt)
        nonce = self._session()
        if not nonce:
            return self._need_login(path, u.query)
        if path in PAGES:
            if PAGES[path] == "summary":
                e = FILECACHE.get("summary.html")
                if not e:
                    return self._send(500, "text/plain; charset=utf-8", "summary.html 이 없습니다\n")
                return self._send(200, "text/html; charset=utf-8", e["body"], {"Content-Security-Policy": e["csp"]})
            e = FILECACHE.get("live.html")
            if not e or not MIRROR:
                return self._redirect("/summary")
            body = e["body"].replace(b"__CSRF__", AUTH.csrf(nonce).encode())
            return self._send(200, "text/html; charset=utf-8", body, {"Content-Security-Policy": CSP_LIVE})
        if path in FILES:
            return self._file(*FILES[path])
        if path in FONTS:
            return self._file(os.path.join(FONT_DIR, FONTS[path]), "font/ttf", cache="private, max-age=604800")
        if path == "/api/state":
            body, _ = HUB.body(0)
            return self._send(200, "application/json; charset=utf-8", body)
        if path in ("/api/stream", "/api/live") and not self._event_stream_ok():
            return self._json(400, {"ok": False, "err": "EventSource 로만 엽니다"})
        if path == "/api/stream":
            return self._stream()
        if path == "/api/live":
            return self._live()
        if path == "/api/live-stats":
            st = MIRROR.stats() if MIRROR else {"state": "off"}
            st["service"] = {"rssMb": round(_rss_mb(), 1), "cpuPct": STATS.cpu_pct, "threads": threading.active_count(), "version": VERSION}
            return self._json(200, st)
        if path.startswith("/app/"):
            return self._static(urllib.parse.unquote(path[5:]))
        return self._send(404, "text/plain; charset=utf-8", "없는 주소입니다\n")

    def _login_page(self, msg, code=200, nxt="/"):
        e = FILECACHE.get("login.html")
        body = (e["body"] if e else b"<h1>login.html missing</h1>").decode("utf-8")
        if not AUTH.ready():
            msg = msg or AUTH.error
        body = body.replace("{{MSG}}", html.escape(msg)).replace("{{NEXT}}", html.escape(nxt if nxt in ("/", "/summary") else "/"))
        self._send(code, "text/html; charset=utf-8", body, {"Content-Security-Policy": CSP_LOGIN})

    def _static(self, rel):
        if self.command not in ("GET", "HEAD") or not MIRROR:
            return self._send(405, "text/plain; charset=utf-8", "GET 만 됩니다\n")
        r = MIRROR.static(rel)
        if not r:
            return self._send(404, "text/plain; charset=utf-8", "허용되지 않은 파일입니다\n")
        data, ctype = r
        self._send(200, ctype, data, {"Content-Security-Policy": CSP_STATIC}, cache="private, max-age=300")

    def _stream(self):
        if self.command == "HEAD":
            return self._head(200, "text/event-stream")
        sock = self.connection
        try:
            # 읽지 않는 상대(잠든 휴대폰 탭)가 자리를 오래 잡지 못하게: 보낼 버퍼를 작게, 답(ACK) 없는 데이터는 60초 뒤 끊김
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024)
            if hasattr(socket, "TCP_USER_TIMEOUT"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, 60000)
        except OSError:
            pass
        self.close_connection = True
        me = HUB.join_stream(sock)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            sock.settimeout(30)
            body, seen = HUB.body(0)
            self.wfile.write(b"retry: 3000\nevent: full\ndata: " + body.encode("utf-8") + b"\n\n")
            self.wfile.flush()
            last_write = time.monotonic()
            while not STOP.is_set():
                with HUB.cond:
                    HUB.cond.wait_for(lambda: HUB.version > seen or STOP.is_set() or me["gone"], timeout=15)
                    newer = HUB.version > seen
                if me["gone"] or STOP.is_set():
                    break
                if newer:
                    body, seen = HUB.body(seen)
                    self.wfile.write(b"event: patch\ndata: " + body.encode("utf-8") + b"\n\n")
                    last_write = time.monotonic()
                elif time.monotonic() - last_write >= 14:
                    self.wfile.write(b": ping\n\n")
                    last_write = time.monotonic()
                self.wfile.flush()
        except (OSError, ValueError):   # 끊김 · 시간 초과 · 닫힌 소켓
            pass
        finally:
            HUB.leave_stream(me)

    def _live(self):
        """실시간 화면 SSE: status · wait · reset · m(DOM 묶음) · cv(캔버스 그림). gzip 으로 약 15배 작게."""
        if not MIRROR:
            return self._json(404, {"ok": False, "err": "실시간 화면이 꺼져 있습니다"})
        if self.command == "HEAD":
            return self._head(200, "text/event-stream")
        cookie = self._cookies().get(authmod.COOKIE)
        gz = "gzip" in (self.headers.get("Accept-Encoding") or "")
        sock = self.connection
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 512 * 1024)
            if hasattr(socket, "TCP_USER_TIMEOUT"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, 60000)
        except OSError:
            pass
        self.close_connection = True
        v = MIRROR.join(sock)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Accel-Buffering", "no")
            if gz:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Connection", "close")
            self.end_headers()
            sock.settimeout(30)
            z = zlib.compressobj(6, zlib.DEFLATED, 31) if gz else None

            def out(*chunks):
                # 큰 사진(수 MB)을 한 덩어리로 합치지 않고 조각마다 압축해서 보낸다 (메모리 봉우리를 낮게)
                parts = []
                for c in chunks:
                    v.raw += len(c)
                    if z:
                        c = z.compress(c)
                    if c:
                        parts.append(c)
                if z:
                    parts.append(z.flush(zlib.Z_SYNC_FLUSH))
                for c in parts:
                    v.wire += len(c)
                    self.wfile.write(c)
                self.wfile.flush()

            # hello: 이 연결 이름(보이는지 알릴 때) + 서버 시각 (누른 것이 늦게 도착하면 서버가 버리도록 시각을 맞춤)
            out(b"retry: 2000\nevent: hello\ndata: " + jdump({"vid": v.vid, "now": int(time.time() * 1000)}).encode() + b"\n\n")
            checked = time.monotonic()
            while not STOP.is_set():
                items = MIRROR.next_items(v, 15.0)
                if items is None:
                    if v.evicted:                                    # 다른 창이 들어와 밀려남: 브라우저가 저절로 다시 붙지 않게
                        out(b"event: bye\ndata: {}\n\n")
                    break
                if time.monotonic() - checked > LIVE_CHECK_S:       # 로그아웃 · 비밀번호 바뀜 → 끊음
                    checked = time.monotonic()
                    if not AUTH.session(cookie):
                        break
                if not items:
                    # 보이는 이벤트로 (주석 핑은 브라우저 JS 가 못 봄): 35초 넘게 아무것도 안 오면 live.js 가 끊김으로 보고 다시 붙는다
                    out(b"event: ping\ndata: {}\n\n")
                    continue
                chunks = []
                for ev, data in items:
                    chunks += (b"event: " + ev.encode() + b"\ndata: ", data.encode("utf-8"), b"\n\n")
                out(*chunks)
        except (OSError, ValueError):
            pass
        finally:
            MIRROR.leave(v)

    # ------------------------------------------------------------ POST
    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY:
            self.close_connection = True
            self._json(413, {"ok": False, "err": "너무 큽니다"})
            return None
        if not n:
            return b""
        self._deadline = time.monotonic() + HEADER_DEADLINE
        try:
            raw = self.rfile.read(n)
        finally:
            self._deadline = None
            self.connection.settimeout(self.timeout)
        if len(raw) != n:                                     # 덜 보내고 끊음
            self.close_connection = True
            self._json(400, {"ok": False, "err": "본문이 잘림"})
            return None
        return raw

    def do_POST(self):
        if not host_ok(self.headers.get("Host")):
            return self._send(403, "text/plain; charset=utf-8", "허용되지 않은 주소입니다\n")
        path = urllib.parse.urlsplit(self.path).path
        raw = self._body()
        if raw is None:
            return
        if path == "/login":
            return self._login(raw)
        nonce = self._session()
        if not nonce:
            return self._json(401, {"ok": False, "err": "로그인이 필요합니다"})
        # 다른 사이트에서 몰래 보내는 요청 막기: 같은 출처(Origin) + 세션별 토큰 + JSON 만
        if not self._same_origin() or not AUTH.check_csrf(nonce, self.headers.get("X-CSRF-Token")):
            return self._json(403, {"ok": False, "err": "요청 확인 실패 (페이지를 새로고침하세요)"})
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return self._json(415, {"ok": False, "err": "JSON 만 받습니다"})
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeError):
            return self._json(400, {"ok": False, "err": "잘못된 요청"})
        if path == "/logout":
            AUTH.revoke(self._cookies().get(authmod.COOKIE))
            return self._json(200, {"ok": True}, {"Set-Cookie": [
                f"{authmod.COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict", f"{authmod.MARK_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"]})
        if not MIRROR:
            return self._json(404, {"ok": False, "err": "실시간 화면이 꺼져 있습니다"})
        try:
            if path == "/api/act":
                if not ACT_LIMIT.take(nonce):
                    return self._json(429, {"ok": False, "err": "너무 빠르게 누르고 있습니다"})
                try:
                    a = mirrormod.validate(body)
                except ValueError as e:
                    return self._json(400, {"ok": False, "err": f"잘못된 조작 ({e})"})
                st = body.get("st")                          # 누른 때 (live.js 가 서버 시각으로 맞춰 보냄)
                if isinstance(st, (int, float)) and not isinstance(st, bool) and abs(time.time() * 1000 - st) > ACT_MAX_AGE_MS:
                    MIRROR.st["acts_stale"] += 1
                    return self._json(409, {"ok": False, "err": "늦게 도착한 조작이라 버렸습니다 (연결 확인 후 다시 눌러 주세요)", "stale": True})
                return self._json(200, MIRROR.act(a))
            if path == "/api/live-vis":                      # 이 창이 보이는지/숨었는지 (차트 그림을 만들지 정함)
                vid = body.get("vid") if isinstance(body, dict) else None
                if not isinstance(vid, str) or len(vid) > 40:
                    return self._json(400, {"ok": False, "err": "잘못된 요청"})
                return self._json(200, {"ok": MIRROR.set_visible(vid, bool(body.get("visible")))})
            if path == "/api/dialog":
                seq = body.get("seq") if isinstance(body, dict) else None
                if not isinstance(seq, int) or isinstance(seq, bool):
                    return self._json(400, {"ok": False, "err": "잘못된 요청"})
                MIRROR.answer_dialog(seq, bool(body.get("accept")), body.get("text"))
                return self._json(200, {"ok": True})
            if path == "/api/reload":
                if not ACT_LIMIT.take(nonce):
                    return self._json(429, {"ok": False, "err": "너무 빠르게 누르고 있습니다"})
                MIRROR.reload()
                sys.stderr.write("ghcoin-dash: 실시간 화면에서 앱 새로고침\n")
                return self._json(200, {"ok": True})
        except mirrormod.Conflict as e:
            return self._json(409, {"ok": False, "err": str(e)})
        except (mirrormod.Unavailable, ConnectionError, OSError, websocket.WebSocketException) as e:
            return self._json(503, {"ok": False, "err": str(e) if isinstance(e, mirrormod.Unavailable) else "봇 화면에 연결할 수 없습니다"})
        return self._json(404, {"ok": False, "err": "없는 주소입니다"})

    def _login(self, raw):
        ip = str(self.client_address[0])
        origin = self.headers.get("Origin")
        if origin and origin != "null" and not self._same_origin():
            return self._login_page("다른 사이트에서 보낸 로그인은 받지 않습니다", 403)
        try:
            form = urllib.parse.parse_qs(raw.decode("utf-8"), max_num_fields=4)
        except (ValueError, UnicodeError):
            form = {}
        nxt = (form.get("next") or ["/"])[0]
        nxt = nxt if nxt in ("/", "/summary") else "/"
        if not AUTH.ready():
            return self._login_page(AUTH.error, 503, nxt)
        if not AUTH.allow_attempt(ip):
            return self._login_page("시도가 너무 많습니다 — 1분 뒤에 다시 해 보세요", 429, nxt)
        if not AUTH.check_password((form.get("password") or [""])[0]):
            time.sleep(0.4)                                   # (틀린 시도는 allow_attempt 가 이미 셌음)
            return self._login_page("비밀번호가 틀렸습니다", 401, nxt)
        AUTH.succeeded(ip)
        token = AUTH.new_session()
        sec = "; Secure" if self._secure() else ""
        age = authmod.SESSION_DAYS * 86400
        return self._redirect(nxt, {"Set-Cookie": [f"{authmod.COOKIE}={token}; Path=/; Max-Age={age}; HttpOnly; SameSite=Strict{sec}",
                                                   f"{authmod.MARK_COOKIE}=1; Path=/; Max-Age={age}; HttpOnly; SameSite=Lax{sec}"]})

    def do_GET(self):
        self._route()

    def do_HEAD(self):
        self._route()

    def _deny(self):
        self._send(405, "text/plain; charset=utf-8", "지원하지 않는 요청입니다\n", {"Allow": "GET, HEAD, POST"})

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _deny


class Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False        # 끝낼 때 느린 연결을 기다리지 않음
    allow_reuse_address = True
    request_queue_size = 32

    def __init__(self, addr, handler):
        self._slots = threading.BoundedSemaphore(MAX_CONN)
        self._per_ip = {}
        self._ip_lock = threading.Lock()
        if ":" in addr[0]:
            self.address_family = socket.AF_INET6
        super().__init__(addr, handler)

    def _ip_take(self, ip):
        try:
            loop = ipaddress.ip_address(str(ip).split("%", 1)[0])
            loop = (getattr(loop, "ipv4_mapped", None) or loop).is_loopback
        except ValueError:
            loop = False
        with self._ip_lock:
            n = self._per_ip.get(ip, 0)
            if n >= (MAX_CONN_LOCAL if loop else MAX_CONN_PER_IP):
                return False
            self._per_ip[ip] = n + 1
            return True

    def _ip_give(self, ip):
        with self._ip_lock:
            n = self._per_ip.get(ip, 0) - 1
            if n > 0:
                self._per_ip[ip] = n
            else:
                self._per_ip.pop(ip, None)

    def process_request(self, request, client_address):
        ip = client_address[0]
        if not self._ip_take(ip):                       # 주소 하나가 자리를 다 채우지 못하게
            self.shutdown_request(request)
            return
        if not self._slots.acquire(blocking=False):     # 자리가 없으면 바로 끊음 (스레드·메모리를 더 쓰지 않음)
            self._ip_give(ip)
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            self._ip_give(ip)
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()
            self._ip_give(client_address[0])

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError, socket.timeout)):
            return  # 상대가 먼저 끊은 것 — 기록하지 않음
        super().handle_error(request, client_address)

    def service_actions(self):
        # 수집기 · 실시간 중계 스레드가 죽거나 멈추면 서비스를 끝낸다 → systemd(Restart=always)가 다시 켬
        th = COLLECTOR
        if th is None or STOP.is_set():
            return
        dead = not th.is_alive() or time.monotonic() - LAST_TICK > WATCHDOG_S or (MIRROR_THREAD is not None and not MIRROR_THREAD.is_alive())
        if dead:
            sys.stderr.write("ghcoin-dash: 수집기/중계가 멈춰서 종료합니다 (systemd 가 다시 켬)\n")
            sys.stderr.flush()
            os._exit(1)


def main():
    global COLLECTOR, MIRROR, MIRROR_THREAD
    if len(sys.argv) > 1 and sys.argv[1] == "--make-password-hash":
        pw = sys.stdin.readline().rstrip("\r\n")
        try:
            print(authmod.make_hash(pw))
        except ValueError as e:
            sys.stderr.write(f"{e}\n")
            return 2
        return 0
    try:
        src = load_collector()
        _check_local(CDP_BASE)
        if os.environ.get("GHCOIN_DASH_MIRROR", "1") != "0":
            MIRROR = mirrormod.Mirror(CDP_BASE, TARGET_RE, os.path.join(HERE, "recorder.js"),
                                      os.path.join(HERE, "vendor", "rrweb-record.min.js"), status_fn=bot_status)
    except (OSError, ValueError) as e:
        sys.stderr.write(f"시작할 수 없습니다: {e}\n")
        return 2
    if not AUTH.ready():
        sys.stderr.write(f"주의: {AUTH.error} (로그인할 수 없음)\n")
    for i in range(20):                       # 다시 켤 때 예전 프로세스가 아직 포트를 쥐고 있으면 잠깐 기다림
        try:
            srv = Server((BIND, PORT), Handler)
            break
        except OSError as e:
            if e.errno != 98 or i == 19:
                raise
            time.sleep(0.5)
    COLLECTOR = threading.Thread(target=collector_loop, args=(src,), name="collector", daemon=True)
    COLLECTOR.start()
    if MIRROR:
        MIRROR_THREAD = threading.Thread(target=MIRROR.run, name="mirror", daemon=True)
        MIRROR_THREAD.start()

    def bye(*_):
        STOP.set()
        if MIRROR:
            MIRROR.stop.set()
            with MIRROR.cond:
                MIRROR.cond.notify_all()
        with HUB.cond:
            HUB.cond.notify_all()
        threading.Thread(target=srv.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    print(f"ghcoin-dash {VERSION}: http://{BIND}:{PORT}/  (DevTools {CDP_BASE}, 요약 {INTERVAL:g}초 간격, 실시간 화면 "
          f"{'기록기 ' + MIRROR.version if MIRROR else '꺼짐'})", flush=True)
    try:
        srv.serve_forever(poll_interval=0.5)
    finally:
        STOP.set()
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
