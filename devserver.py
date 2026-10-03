# GH Coin 개발 서버 — GHCoin.exe(런처) 없이도 외부 AI가 되게 하는 Python 프록시.
# 정적 파일을 서빙하면서 /__nuri/proxy/<회사>/... 요청을 서버가 대신 보내(CORS 우회) 응답을 그대로 흘려준다.
# 실행:  python devserver.py       → http://127.0.0.1:8777/gh-coin/
import http.server, urllib.request, urllib.error, os
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8777
UPSTREAMS = {
    "nvidia": "https://integrate.api.nvidia.com/v1", "nvgenai": "https://ai.api.nvidia.com/v1/genai",
    "groq": "https://api.groq.com/openai/v1", "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai", "cerebras": "https://api.cerebras.ai/v1",
    "hf": "https://router.huggingface.co/v1", "deepseek": "https://api.deepseek.com", "mistral": "https://api.mistral.ai/v1",
    "together": "https://api.together.xyz/v1", "sambanova": "https://api.sambanova.ai/v1", "anthropic": "https://api.anthropic.com/v1",
    "ollama": "http://127.0.0.1:11434", "tavily": "https://api.tavily.com", "brave": "https://api.search.brave.com/res/v1",
    "upbit": "https://api.upbit.com/v1", "binance": "https://api.binance.com/api/v3", "binancef": "https://fapi.binance.com",
    "binancef_test": "https://testnet.binancefuture.com",
}
FWD = ["Authorization", "Content-Type", "Accept", "X-Subscription-Token", "HTTP-Referer", "X-Title", "X-MBX-APIKEY"]


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def log_message(self, *a):
        pass

    def _raw(self, code, data=b"", ct="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    def _forward(self, target, method):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(target, data=body, method=method)
        for h in FWD:
            v = self.headers.get(h)
            if v:
                req.add_header(h, v)
        if "api.anthropic.com" in target:
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                req.add_header("x-api-key", auth[7:])
            req.add_header("anthropic-version", "2023-06-01")
        req.add_header("User-Agent", "GHCoinDev/1.0")
        try:
            r = urllib.request.urlopen(req, timeout=180)
        except urllib.error.HTTPError as e:
            self._raw(e.code, e.read(), e.headers.get("Content-Type", "application/json"))
            return
        except Exception as e:
            self._raw(502, ("upstream: " + str(e)).encode(), "text/plain")
            return
        self.send_response(getattr(r, "status", 200))
        self.send_header("Content-Type", r.headers.get("Content-Type", "application/json"))
        ra = r.headers.get("Retry-After")
        if ra:
            self.send_header("Retry-After", ra)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        while True:
            try:
                chunk = r.read(4096)
            except Exception:
                break
            if not chunk:
                break
            try:
                self.wfile.write(chunk)
                self.wfile.flush()
            except Exception:
                break

    def _nuri(self):
        p = self.path
        if p.startswith("/__nuri/ping"):
            self._raw(200, b"nuri"); return True
        if p.startswith("/__nuri/version"):
            self._raw(200, b"devserver"); return True
        if p.startswith("/__nuri/alive"):
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers(); return True
        if p.startswith("/__nuri/fetch"):
            url = (parse_qs(urlparse(p).query).get("url") or [""])[0]
            if not url.startswith("http"):
                self._raw(400, b"no url"); return True
            self._forward(url, "GET"); return True
        if p.startswith("/__nuri/proxy/"):
            rest = p[len("/__nuri/proxy/"):]
            name, _, tail = rest.partition("/")
            qs = ""
            if "?" in tail:
                tail, _, qs = tail.partition("?")
            base = UPSTREAMS.get(name)
            if name == "custom":
                b = self.headers.get("X-Nuri-Base", "")
                if b.startswith("http"):
                    base = b.rstrip("/")
            if not base:
                self._raw(404, b"unknown upstream"); return True
            target = base.rstrip("/") + "/" + tail + (("?" + qs) if qs else "")
            self._forward(target, self.command); return True
        if p.startswith("/__nuri/"):   # code/override/openfolder 등은 개발 서버에선 미지원 → 조용히 404
            self._raw(404, b"not supported in devserver"); return True
        return False

    def do_GET(self):
        if not self._nuri():
            super().do_GET()

    def do_POST(self):
        if not self._nuri():
            self._raw(404, b"not found")

    def do_DELETE(self):
        if not self._nuri():
            self._raw(404, b"not found")


if __name__ == "__main__":
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H)
    srv.daemon_threads = True
    print(f"GH Coin dev server (AI 프록시 포함) → http://127.0.0.1:{PORT}/gh-coin/")
    srv.serve_forever()
