"""ghcoin-dash 로그인: 비밀번호(scrypt) · 세션 쿠키(HMAC 서명) · CSRF 토큰 · 로그인 시도 제한.

실시간 화면(:8080)은 봇을 그대로 조작할 수 있어서(실거래 승인 포함) Tailscale 안에서도 비밀번호가 필요하다.

비밀번호 파일 (/etc/ghcoin/dash-password.hash, root:ghcoin 640) — 한 줄:
    scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>$<세션 서명 키 b64>
  add-dashboard.sh 가 처음 설치할 때 만든다 (`python3 ghcoin_dash.py --make-password-hash` 에 비밀번호를 stdin 으로).
  비밀번호를 새로 만들면 서명 키도 바뀌어서 이전 로그인이 모두 풀린다. 파일이 바뀌면 서비스를 다시 켜지 않아도 바로 적용.

세션 쿠키: "v1.<만료 unix초>.<임의값>.<HMAC>" — 서버에 저장하지 않으니 서비스가 다시 켜져도 로그인 유지 (30일).
로그아웃한 쿠키는 이 서비스가 켜져 있는 동안 거부 목록에 남는다.
CSRF: 세션마다 HMAC 으로 만든 토큰을 화면에 넣어 두고, 모든 POST 가 X-CSRF-Token 헤더로 보내야 한다 (+ Origin 확인).
"""
import base64
import collections
import hashlib
import hmac
import os
import secrets
import threading
import time

PW_FILE = os.environ.get("GHCOIN_DASH_PWFILE", "/etc/ghcoin/dash-password.hash")
COOKIE = "ghd_session"
MARK_COOKIE = "ghd_seen"            # SameSite=Lax 표시 (다른 앱의 링크로 열었을 때 한 번 더 같은 사이트로 열어 세션 쿠키를 싣게)
SESSION_DAYS = 30
SCRYPT = (2 ** 14, 8, 1)            # 16MB · 약 50ms
LOGIN_PER_IP = 5                    # 1분에 IP 하나가 틀릴 수 있는 횟수
LOGIN_GLOBAL = 30                   # 1분에 전체 로그인 시도 (scrypt CPU 상한)
SCRYPT_SLOTS = threading.BoundedSemaphore(2)   # 동시에 도는 scrypt 수


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_hash(password):
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("비밀번호는 8자 이상")
    salt = secrets.token_bytes(16)
    n, r, p = SCRYPT
    h = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${_b64(salt)}${_b64(h)}${_b64(secrets.token_bytes(32))}"


class Auth:
    def __init__(self, path=PW_FILE):
        self.path = path
        self.lock = threading.Lock()
        self._mtime = None
        self._rec = None            # (n, r, p, salt, hash, key)
        self.error = ""
        self.revoked = collections.OrderedDict()   # 로그아웃한 세션 임의값 -> 만료
        self.fails = {}                             # ip -> deque[시각]
        self.attempts = collections.deque()         # 전체 시도 시각

    # ------------------------------------------------------------ 비밀번호 파일
    def _load(self):
        try:
            st = os.stat(self.path)
        except OSError:
            self._rec, self._mtime = None, None
            self.error = f"비밀번호 파일이 없습니다 ({self.path}) — sudo bash add-dashboard.sh 를 다시 실행하세요"
            return None
        if self._mtime == (st.st_mtime_ns, st.st_size) and self._rec:
            return self._rec
        try:
            with open(self.path, encoding="ascii") as f:
                parts = f.read().strip().split("$")
            if len(parts) != 7 or parts[0] != "scrypt":
                raise ValueError("형식")
            n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
            if not (2 ** 10 <= n <= 2 ** 20 and 1 <= r <= 32 and 1 <= p <= 4):
                raise ValueError("값")
            rec = (n, r, p, _unb64(parts[4]), _unb64(parts[5]), _unb64(parts[6]))
            if len(rec[4]) < 16 or len(rec[5]) < 32:
                raise ValueError("길이")
        except (OSError, ValueError, UnicodeError) as e:
            self._rec, self._mtime = None, None
            self.error = f"비밀번호 파일을 읽을 수 없습니다 ({type(e).__name__})"
            return None
        self._rec, self._mtime, self.error = rec, (st.st_mtime_ns, st.st_size), ""
        return rec

    def ready(self):
        with self.lock:
            return self._load() is not None

    def _key(self):
        with self.lock:
            rec = self._load()
        return rec[5] if rec else None

    # ------------------------------------------------------------ 로그인 시도 제한
    def allow_attempt(self, ip):
        """시도해도 되면 True. 시도는 여기서 바로 '틀림'으로 세고, 맞으면 succeeded() 가 하나 지운다
        (틀린 것을 확인 뒤에 세면 동시에 수십 개를 보내 IP 상한을 건너뛸 수 있음)."""
        now = time.monotonic()
        with self.lock:
            while self.attempts and now - self.attempts[0] > 60:
                self.attempts.popleft()
            dq = self.fails.setdefault(ip, collections.deque())
            while dq and now - dq[0] > 60:
                dq.popleft()
            if len(dq) >= LOGIN_PER_IP:                # IP 상한을 먼저: 주소 하나가 전체 상한을 다 써서 다른 사람을 막지 못하게
                return False
            if len(self.attempts) >= LOGIN_GLOBAL:
                return False
            dq.append(now)
            self.attempts.append(now)
            if len(self.fails) > 1000:                 # 오래된 IP 정리
                for k in [k for k, v in self.fails.items() if not v or now - v[-1] > 60]:
                    del self.fails[k]
            return True

    def succeeded(self, ip):
        """맞는 비밀번호: allow_attempt 가 미리 센 '틀림' 하나를 지운다."""
        with self.lock:
            dq = self.fails.get(ip)
            if dq:
                dq.pop()

    def check_password(self, password):
        with self.lock:
            rec = self._load()
        if not rec or not isinstance(password, str) or not password or len(password) > 256:
            return False
        n, r, p, salt, want, _ = rec
        if not SCRYPT_SLOTS.acquire(timeout=5):      # 동시에 2개까지 (하나에 16MB) — 몰려도 메모리 상한(256MB)을 넘지 않게
            return False
        try:
            got = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(want), maxmem=64 * 1024 * 1024)
        finally:
            SCRYPT_SLOTS.release()
        return hmac.compare_digest(got, want)

    # ------------------------------------------------------------ 세션 · CSRF
    def new_session(self):
        key = self._key()
        if not key:
            return None
        exp = int(time.time()) + SESSION_DAYS * 86400
        nonce = _b64(secrets.token_bytes(18))
        mac = _b64(hmac.new(key, f"sess:v1:{exp}:{nonce}".encode(), hashlib.sha256).digest())
        return f"v1.{exp}.{nonce}.{mac}"

    def session(self, cookie_value):
        """올바른 세션이면 임의값(nonce), 아니면 None."""
        if not cookie_value or len(cookie_value) > 200:
            return None
        parts = cookie_value.split(".")
        if len(parts) != 4 or parts[0] != "v1":
            return None
        key = self._key()
        if not key:
            return None
        _, exp, nonce, mac = parts
        want = _b64(hmac.new(key, f"sess:v1:{exp}:{nonce}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(want, mac):
            return None
        try:
            if int(exp) < time.time():
                return None
        except ValueError:
            return None
        with self.lock:
            if nonce in self.revoked:
                return None
        return nonce

    def revoke(self, cookie_value):
        nonce = self.session(cookie_value)
        if not nonce:
            return
        with self.lock:
            self.revoked[nonce] = int(cookie_value.split(".")[1])
            now = time.time()
            while self.revoked and (len(self.revoked) > 5000 or next(iter(self.revoked.values())) < now):
                self.revoked.popitem(last=False)

    def csrf(self, nonce):
        key = self._key()
        if not key or not nonce:
            return ""
        return hmac.new(key, f"csrf:v1:{nonce}".encode(), hashlib.sha256).hexdigest()[:40]

    def check_csrf(self, nonce, token):
        want = self.csrf(nonce)
        return bool(want) and isinstance(token, str) and hmac.compare_digest(want, token)


class Bucket:
    """세션별 조작 속도 제한 (토큰 버킷)."""

    def __init__(self, rate=25.0, burst=60.0):
        self.rate, self.burst = rate, burst
        self.state = {}
        self.lock = threading.Lock()

    def take(self, key):
        now = time.monotonic()
        with self.lock:
            tokens, t = self.state.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - t) * self.rate)
            if tokens < 1:
                self.state[key] = (tokens, now)
                return False
            self.state[key] = (tokens - 1, now)
            if len(self.state) > 500:
                for k in [k for k, (_, tt) in self.state.items() if now - tt > 600]:
                    del self.state[k]
            return True
