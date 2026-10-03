#!/usr/bin/env python3
"""ghcoin-dash: GH Coin 읽기 전용 웹 대시보드.

GH Coin 은 Chrome 페이지 안에서 돌아가는 봇이라 상태가 전부 그 페이지 메모리·브라우저 저장소에 있다.
이 서비스는 앱 코드를 전혀 바꾸지 않고,

  1. Chrome DevTools(127.0.0.1:9222, 서버 안에서만)에 붙어 GH Coin 페이지를 찾고
  2. 몇 초마다 collector.js 하나를 Runtime.evaluate 로 실행해 '읽기만' 한 상태 사진(snapshot)을 받아
  3. 0.0.0.0:8080 에서 대시보드 화면(index.html)과 JSON/SSE 로 보여 준다 (방화벽상 Tailscale 로만 열림).

읽기 전용: GET/HEAD 만 받는다. 요청 내용이 페이지로 전달되는 길은 없다 (페이지에 보내는 것은 고정된 collector.js 뿐).
비밀값(키·토큰)은 collector.js 가 지우고, 여기서 한 번 더 키 이름·문자열 패턴으로 지운다.

필요한 것: Python 3.10+ 표준 라이브러리 + websocket-client (우분투 패키지 python3-websocket).

환경 변수
  GHCOIN_DASH_PORT      (8080)            대시보드 포트
  GHCOIN_DASH_BIND      (0.0.0.0)         대시보드 주소
  GHCOIN_DASH_INTERVAL  (5)               수집 간격(초), 2~60
  GHCOIN_DASH_SLOW      (30)              무거운 항목(감사 기록·파이프라인·적중률 등) 간격(초)
  GHCOIN_DASH_REPORTS   (300)             시간별 발표 목록 간격(초)
  GHCOIN_DASH_HOSTS     ()                Host 헤더로 더 허용할 이름(쉼표 구분). IP·점 없는 이름·*.ts.net·localhost 는 기본 허용
  GHCOIN_CDP            (http://127.0.0.1:9222)  Chrome DevTools 주소 (반드시 이 서버 안: 127.0.0.1/localhost/::1)
"""
import base64
import hashlib
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import websocket  # python3-websocket (websocket-client)
except ImportError:  # pragma: no cover
    sys.stderr.write("python3-websocket 이 필요합니다:  sudo apt-get install -y python3-websocket\n")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "1.0"


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
EVAL_TIMEOUT = 20.0                     # 페이지가 무거운 작업(백테스트) 중이면 평가가 늦어질 수 있다
STALE_AFTER = max(3 * INTERVAL, 20.0)   # 이보다 오래된 자료는 '오래됨' 표시
MAX_SSE = 16                            # 동시에 열린 실시간 연결 수 제한
MAX_SNAPSHOT_BYTES = 768 * 1024         # 상태 사진 크기 상한 (넘으면 목록을 더 줄인다)
TARGET_RE = re.compile(r"^http://(127\.0\.0\.1|localhost):1786[0-9]/gh-coin/")
OPT_MARK = "/*OPT*/{}"

# ---------------------------------------------------------------- 비밀 지우기 (collector.js 다음의 두 번째 안전장치)
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


def _check_local(url):
    host = urllib.parse.urlsplit(url).hostname or ""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(f"DevTools 주소는 이 서버 안이어야 합니다: {url}")


class CDP:
    """GH Coin 페이지 하나에 대한 DevTools 웹소켓 (Runtime.evaluate 만 보냄)."""

    def __init__(self, base):
        _check_local(base)
        self.base = base
        self.ws = None
        self.target = None
        self.multi = 0
        self.browser = ""
        self.seq = 0

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=3) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def connect(self):
        self.close()
        try:
            lst = self._get("/json/list")
        except Exception as e:
            raise ConnectionError(f"Chrome DevTools({self.base}) 에 연결할 수 없음: {e}") from None
        pages = [t for t in lst if t.get("type") == "page" and TARGET_RE.match(t.get("url", ""))]
        if not pages:
            raise NoTarget("GH Coin 페이지가 아직 없음 (Chrome 이 켜지는 중일 수 있음)")
        t = pages[0]
        ws_url = t.get("webSocketDebuggerUrl") or ""
        if not ws_url.startswith("ws://"):
            raise NoTarget("페이지에 이미 다른 DevTools 가 붙어 있어 주소가 없음")
        _check_local(ws_url.replace("ws://", "http://", 1))
        try:
            self.browser = str(self._get("/json/version").get("Browser", ""))[:60]
        except Exception:
            self.browser = ""
        # Chrome 111+ 는 Origin 헤더가 있는 웹소켓을 거절한다 → Origin 을 보내지 않는다 (--remote-allow-origins 불필요)
        self.ws = websocket.create_connection(ws_url, timeout=EVAL_TIMEOUT, suppress_origin=True, enable_multithread=False)
        self.target = {"id": str(t.get("id", ""))[:12], "url": str(t.get("url", ""))[:120], "title": str(t.get("title", ""))[:60]}
        self.multi = len(pages)

    def evaluate(self, expression):
        if not self.ws:
            raise ConnectionError("연결 안 됨")
        self.seq += 1
        mid = self.seq
        self.ws.send(jdump({"id": mid, "method": "Runtime.evaluate", "params": {
            "expression": expression, "awaitPromise": True, "returnByValue": True, "silent": True,
            "userGesture": False, "includeCommandLineAPI": False, "generatePreview": False, "replMode": False}}))
        deadline = time.monotonic() + EVAL_TIMEOUT
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError("페이지 응답 시간 초과")
            raw = self.ws.recv()
            if not raw:
                raise ConnectionError("DevTools 연결이 닫힘")
            msg = json.loads(raw)
            if msg.get("method") in ("Inspector.detached", "Inspector.targetCrashed"):
                raise ConnectionError(msg.get("method"))
            if msg.get("id") != mid:
                continue  # 이전에 시간 초과로 버린 응답 등
            if "error" in msg:
                raise JSError(str(msg["error"].get("message", msg["error"]))[:300])
            res = msg.get("result", {})
            if res.get("exceptionDetails"):
                d = res["exceptionDetails"]
                desc = (d.get("exception") or {}).get("description") or d.get("text") or "JS 오류"
                raise JSError(str(desc).splitlines()[0][:300])
            return (res.get("result") or {}).get("value")

    def close(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        self.ws = None


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
        self._cpu = (time.monotonic(), sum(os.times()[:2]))
        self.cpu_pct = 0.0
        self._chrome = (0, 0)
        self._chrome_t = 0.0

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
        for name, keep in (("feed", 40), ("trades", 20), ("strategies", 12)):
            if sum(len(s) for s in self.sections.values()) <= MAX_SNAPSHOT_BYTES:
                return
            try:
                lst = json.loads(self.sections.get(name, "[]"))
                if isinstance(lst, list) and len(lst) > keep:
                    self.sections[name] = jdump(lst[:keep])
            except ValueError:
                pass

    def publish(self, changed, meta, server):
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


HUB = Hub()
STATS = Stats()
STOP = threading.Event()


def build_meta(cdp):
    age = (time.time() - STATS.last_ok) if STATS.last_ok else None
    stale = age is None or age > STALE_AFTER or STATS.status != "ok"
    return {"status": STATS.status, "message": STATS.message, "stale": stale, "ageS": None if age is None else round(age, 1),
            "lastOk": int(STATS.last_ok * 1000) if STATS.last_ok else None, "now": int(time.time() * 1000),
            "connected": bool(cdp.ws), "pages": cdp.multi, "intervalS": INTERVAL}


def load_collector():
    with open(os.path.join(HERE, "collector.js"), encoding="utf-8") as f:
        src = f.read()
    if src.count(OPT_MARK) != 1:
        raise ValueError("collector.js 의 /*OPT*/{} 표시가 정확히 한 번 있어야 합니다")
    return src


def poll_once(cdp, src, st):
    """한 번 읽기. st = {last_slow, last_rep} (무거운 항목 시각). 바뀐 부분 이름 목록을 돌려준다."""
    if not cdp.ws:
        cdp.connect()
        STATS.reconnects += 1
        st["last_slow"] = st["last_rep"] = 0.0   # 새 연결이면 무거운 항목도 바로 한 번
    now = time.monotonic()
    opt = {"slow": not st["last_slow"] or now - st["last_slow"] >= SLOW_EVERY, "reports": not st["last_rep"] or now - st["last_rep"] >= REPORT_EVERY}
    expr = src.replace(OPT_MARK, "/*OPT*/" + jdump(opt))
    STATS.polls += 1
    t0 = time.monotonic()
    val = cdp.evaluate(expr)
    ms = round((time.monotonic() - t0) * 1000, 1)
    STATS.last_eval_ms = ms
    STATS.avg_eval_ms = ms if STATS.avg_eval_ms is None else round(STATS.avg_eval_ms * 0.9 + ms * 0.1, 1)
    if not isinstance(val, dict):
        raise JSError("수집 결과가 비어 있음")
    if val.get("ok"):
        STATS.ok += 1
        STATS.last_ok = time.time()
        STATS.status, STATS.message = "ok", "실시간"
        STATS.page_took_ms = val.get("tookMs")
        if opt["slow"]:
            st["last_slow"] = now
        if opt["reports"]:
            st["last_rep"] = now
        changed = HUB.merge(val)
        STATS.snapshot_bytes = sum(len(s) for s in HUB.sections.values())
        return changed
    if val.get("booting"):
        STATS.status, STATS.message = "booting", "봇 창이 켜지는 중 (켜진 뒤 30초 기다림)"
        st["last_slow"] = st["last_rep"] = 0.0
    else:
        STATS.status, STATS.message = "error", f"수집 불가: {str(val.get('why', '알 수 없음'))[:80]}"
        STATS.errors += 1
    return []


def collector_loop(src):
    cdp = CDP(CDP_BASE)
    st = {"last_slow": 0.0, "last_rep": 0.0}
    backoff, next_try = 1.0, 0.0
    while not STOP.is_set():
        t_tick = time.monotonic()
        changed = []
        if cdp.ws or t_tick >= next_try:
            fail = None
            try:
                changed = poll_once(cdp, src, st)
                backoff = 1.0
            except NoTarget as e:
                STATS.status, STATS.message = "no_page", str(e)
                fail = True
            except JSError as e:
                STATS.errors += 1
                STATS.status, STATS.message = "error", "페이지 오류"
                STATS.last_error = {"t": int(time.time() * 1000), "msg": scrub_str(str(e))[:300]}
                if "context" in str(e).lower() or "navigat" in str(e).lower():
                    st["last_slow"] = st["last_rep"] = 0.0
            except (websocket.WebSocketException, ConnectionError, OSError, TimeoutError, ValueError) as e:
                STATS.errors += 1
                STATS.status, STATS.message = "no_chrome", "Chrome(봇 창)에 연결할 수 없음 — 다시 붙는 중"
                STATS.last_error = {"t": int(time.time() * 1000), "msg": scrub_str(f"{type(e).__name__}: {e}")[:300]}
                fail = True
            except Exception as e:  # 예상 못 한 오류에도 수집은 계속
                STATS.errors += 1
                STATS.status, STATS.message = "error", "수집기 내부 오류"
                STATS.last_error = {"t": int(time.time() * 1000), "msg": scrub_str(f"{type(e).__name__}: {e}")[:300]}
                sys.stderr.write(f"collector: {type(e).__name__}: {e}\n")
                fail = True
            if fail:
                cdp.close()
                next_try = time.monotonic() + backoff   # Chrome 이 다시 켜질 때까지 1→2→4…최대 30초 간격으로 다시 시도
                backoff = min(backoff * 2, 30.0)
        STATS.sample()
        HUB.publish(changed, build_meta(cdp), STATS.server(HUB.sse, cdp))   # 끊겨 있어도 상태(오래됨)는 계속 알림
        STOP.wait(max(0.2, INTERVAL - (time.monotonic() - t_tick)))
    cdp.close()


# ---------------------------------------------------------------- HTTP
class Page:
    def __init__(self):
        self.path = os.path.join(HERE, "index.html")
        self.mtime = None
        self.body = b""
        self.csp = ""

    def get(self):
        try:
            m = os.stat(self.path).st_mtime
        except OSError:
            return b"<h1>index.html missing</h1>", "default-src 'none'"
        if m != self.mtime:
            with open(self.path, "rb") as f:
                body = f.read()
            text = body.decode("utf-8")
            hashes = []
            for s in re.findall(r"<script>(.*?)</script>", text, re.S):
                hashes.append("'sha256-" + base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode() + "'")
            self.csp = ("default-src 'none'; script-src " + (" ".join(hashes) or "'none'") +
                        "; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self.body, self.mtime = body, m
        return self.body, self.csp


PAGE = Page()


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


class Handler(BaseHTTPRequestHandler):
    server_version = "ghcoin-dash"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 30

    def log_message(self, fmt, *args):  # 접속 기록은 남기지 않는다 (journald 절약)
        pass

    def _head(self, code, ctype, length=None, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _send(self, code, ctype, body, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self._head(code, ctype, len(body), extra)
        if self.command != "HEAD":
            self.wfile.write(body)

    def _route(self):
        if not host_ok(self.headers.get("Host")):
            return self._send(403, "text/plain; charset=utf-8", "허용되지 않은 주소입니다 (GHCOIN_DASH_HOSTS 참고)\n")
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/index.html"):
            body, csp = PAGE.get()
            return self._send(200, "text/html; charset=utf-8", body, {"Content-Security-Policy": csp})
        if path == "/api/state":
            body, _ = HUB.body(0)
            return self._send(200, "application/json; charset=utf-8", body)
        if path == "/healthz":
            m = HUB.meta or {}
            return self._send(200, "application/json; charset=utf-8", jdump({
                "ok": True, "status": m.get("status", STATS.status), "chrome": bool(m.get("connected")), "stale": m.get("stale", True),
                "age_s": m.get("ageS"), "uptime_s": int(time.time() - STATS.started)}))
        if path == "/api/stream":
            return self._stream()
        return self._send(404, "text/plain; charset=utf-8", "없는 주소입니다\n")

    def _stream(self):
        if self.command == "HEAD":
            return self._head(200, "text/event-stream")
        with HUB.cond:
            if HUB.sse >= MAX_SSE:
                return self._send(503, "text/plain; charset=utf-8", "실시간 연결이 너무 많습니다\n", {"Retry-After": "10"})
            HUB.sse += 1
        try:
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            body, seen = HUB.body(0)
            self.wfile.write(b"retry: 3000\nevent: full\ndata: " + body.encode("utf-8") + b"\n\n")
            self.wfile.flush()
            last_write = time.monotonic()
            while not STOP.is_set():
                with HUB.cond:
                    HUB.cond.wait_for(lambda: HUB.version > seen or STOP.is_set(), timeout=15)
                    newer = HUB.version > seen
                if newer:
                    body, seen = HUB.body(seen)
                    self.wfile.write(b"event: patch\ndata: " + body.encode("utf-8") + b"\n\n")
                    last_write = time.monotonic()
                elif time.monotonic() - last_write >= 14:
                    self.wfile.write(b": ping\n\n")
                    last_write = time.monotonic()
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError):
            pass
        finally:
            with HUB.cond:
                HUB.sse -= 1

    def do_GET(self):
        self._route()

    def do_HEAD(self):
        self._route()

    def _deny(self):
        self._send(405, "text/plain; charset=utf-8", "보기 전용입니다 (GET 만 됩니다)\n", {"Allow": "GET, HEAD"})

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _deny


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def __init__(self, addr, handler):
        if ":" in addr[0]:
            self.address_family = socket.AF_INET6
        super().__init__(addr, handler)


def main():
    try:
        src = load_collector()
        _check_local(CDP_BASE)
    except (OSError, ValueError) as e:
        sys.stderr.write(f"시작할 수 없습니다: {e}\n")
        return 2
    srv = Server((BIND, PORT), Handler)
    th = threading.Thread(target=collector_loop, args=(src,), name="collector", daemon=True)
    th.start()

    def bye(*_):
        STOP.set()
        with HUB.cond:
            HUB.cond.notify_all()
        threading.Thread(target=srv.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    print(f"ghcoin-dash {VERSION}: http://{BIND}:{PORT}/  (DevTools {CDP_BASE}, {INTERVAL:g}초 간격)", flush=True)
    try:
        srv.serve_forever(poll_interval=0.5)
    finally:
        STOP.set()
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
