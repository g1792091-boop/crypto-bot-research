"""서버에서 24시간 돌릴 때: 접속 비밀번호 · 틀리면 막기 · 서버 모드는 비밀번호 없이 시작 안 함."""
import base64
import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app import auth
from app.main import app

c = TestClient(app)
hdr = lambda pw, user="me": {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


def test_no_password_means_open(monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    assert c.get("/api/status").status_code == 200


def test_password_required_and_lockout(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "비밀-123")
    auth._fails.clear()
    r = c.get("/")
    assert r.status_code == 401 and "Basic" in r.headers["www-authenticate"]
    assert c.get("/api/status", headers=hdr("틀림")).status_code == 401
    assert c.get("/api/status", headers=hdr("비밀-123")).status_code == 200            # 아이디는 아무거나
    assert c.get("/static/style.css", headers=hdr("비밀-123", "x")).status_code == 200
    assert c.get("/healthz").json() == {"ok": True}                                     # 살아 있는지 확인은 비밀번호 없이
    for _ in range(auth.MAX_FAILS):
        c.get("/api/status", headers=hdr("wrong"))
    assert c.get("/api/status", headers=hdr("비밀-123")).status_code == 429             # 여러 번 틀리면 잠시 막힘
    auth._fails.clear()


def test_server_mode_refuses_without_password(tmp_path):
    env = {**os.environ, "SETTINGS_FILE": str(tmp_path / "settings.txt"), "STATE_DIR": str(tmp_path / "state"), "APP_PASSWORD": "",
           "DATA_SOURCE": "synthetic"}
    r = subprocess.run([sys.executable, "launcher.py", "--server"], cwd=Path(__file__).resolve().parent.parent, env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "APP_PASSWORD" in r.stdout
    txt = (tmp_path / "settings.txt").read_text(encoding="utf-8")
    assert "APP_PASSWORD=" in txt and "HOST=0.0.0.0" in txt
