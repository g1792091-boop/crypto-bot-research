"""접속 비밀번호 — 서버(클라우드)에 올려 24시간 돌릴 때 다른 사람이 들어오지 못하게.

APP_PASSWORD 가 설정돼 있으면 모든 요청에 비밀번호를 요구한다 (브라우저가 아이디/비밀번호 창을 띄움 · 아이디는 아무거나).
- /healthz 는 비밀번호 없이 (서버가 살아 있는지 확인용 · 내용 없음)
- 같은 IP 에서 10분 안에 10번 틀리면 10분 동안 막는다.
- 비밀번호는 암호화되지 않은 http 로는 그대로 오가므로, 인터넷에 바로 열 때는 Tailscale · Cloudflare Tunnel 같은 암호화 통로를 권장.
"""
from __future__ import annotations

import base64
import os
import secrets
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

OPEN_PATHS = ("/healthz",)
MAX_FAILS, WINDOW = 10, 600
_fails: dict[str, list[float]] = {}


def password() -> str:
    return os.environ.get("APP_PASSWORD", "").strip()


def _client(req: Request) -> str:
    host = req.client.host if req.client else "?"
    if host in ("127.0.0.1", "::1"):              # 같은 서버의 터널(Cloudflare 등)을 거쳐 온 요청이면 실제 IP
        return req.headers.get("cf-connecting-ip") or req.headers.get("x-forwarded-for", host).split(",")[0].strip()
    return host


def _check(header: str | None) -> bool:
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        user_pw = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8", "replace")
    except (ValueError, IndexError):
        return False
    pw = user_pw.split(":", 1)[1] if ":" in user_pw else user_pw
    return secrets.compare_digest(pw.encode(), password().encode())


class PasswordMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not password() or request.url.path in OPEN_PATHS:
            return await call_next(request)
        ip, now = _client(request), time.time()
        recent = [t for t in _fails.get(ip, []) if now - t < WINDOW]
        _fails[ip] = recent
        if len(recent) >= MAX_FAILS:
            return PlainTextResponse("비밀번호를 여러 번 틀려 10분 동안 막혔습니다.", status_code=429)
        if _check(request.headers.get("authorization")):
            _fails.pop(ip, None)
            return await call_next(request)
        if request.headers.get("authorization"):
            recent.append(now)
        return PlainTextResponse("GH Quant — 비밀번호가 필요합니다 (아이디는 아무거나, 비밀번호는 settings.txt 의 APP_PASSWORD).",
                                 status_code=401, headers={"WWW-Authenticate": 'Basic realm="GH Quant", charset="UTF-8"'})
