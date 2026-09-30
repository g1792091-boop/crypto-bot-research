// 누리 AI 실행기: 앱 파일을 내장한 작은 로컬 웹서버.
// 더블클릭하면 127.0.0.1에서 앱을 열고, 앱 창이 모두 닫히면 스스로 종료한다.
package main

import (
	"bytes"
	"embed"
	"fmt"
	"io"
	"io/fs"
	"mime"
	"net"
	"net/http"
	"os"
	"path"
	"strings"
	"sync"
	"time"
)

//go:embed all:site
var siteFS embed.FS

var (
	startPath = "/nuri-ai/" // 빌드 시 -X main.startPath=... 로 바꿈
	appName   = "누리 AI"
)

const basePort = 17860 // 고정 포트여야 브라우저에 저장된 대화·모델이 유지됨

const keepAlive = `<script>(function(){try{var s=new EventSource("/__nuri/alive");s.onerror=function(){};}catch(e){}})();</script>`

type tracker struct {
	mu       sync.Mutex
	active   int
	seen     bool
	lastZero time.Time
}

func (t *tracker) add(d int) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.active += d
	t.seen = true
	if t.active == 0 {
		t.lastZero = time.Now()
	}
}

func main() {
	idle := envDuration("NURI_IDLE_EXIT", 45*time.Second)      // 창이 모두 닫힌 뒤 종료까지
	firstWait := envDuration("NURI_FIRST_WAIT", 5*time.Minute) // 창이 한 번도 안 열렸을 때 종료까지

	// 이미 실행 중이면 창만 새로 연다
	for p := basePort; p < basePort+10; p++ {
		url := fmt.Sprintf("http://127.0.0.1:%d", p)
		if ping(url) {
			openApp(url + startPath)
			return
		}
	}

	var ln net.Listener
	var err error
	port := 0
	for p := basePort; p < basePort+10; p++ {
		ln, err = net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", p))
		if err == nil {
			port = p
			break
		}
	}
	if ln == nil {
		showError(appName, "실행에 필요한 포트(17860~17869)를 열 수 없습니다.\n다른 프로그램이 쓰고 있는지 확인한 뒤 다시 실행하세요.")
		os.Exit(1)
	}

	sub, _ := fs.Sub(siteFS, "site")
	tr := &tracker{lastZero: time.Now()}
	mux := http.NewServeMux()
	mux.HandleFunc("/__nuri/ping", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("nuri")) })
	mux.HandleFunc("/__nuri/alive", func(w http.ResponseWriter, r *http.Request) {
		fl, ok := w.(http.Flusher)
		if !ok {
			http.Error(w, "stream unsupported", 500)
			return
		}
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		tr.add(1)
		defer tr.add(-1)
		fmt.Fprint(w, ": ok\n\n")
		fl.Flush()
		tick := time.NewTicker(20 * time.Second)
		defer tick.Stop()
		for {
			select {
			case <-r.Context().Done():
				return
			case <-tick.C:
				fmt.Fprint(w, ": ping\n\n")
				fl.Flush()
			}
		}
	})
	mux.HandleFunc("/__nuri/proxy/", proxyHandler)
	mux.Handle("/", siteHandler(sub))

	srv := &http.Server{Handler: mux}
	go srv.Serve(ln)

	url := fmt.Sprintf("http://127.0.0.1:%d", port)
	openApp(url + startPath)

	started := time.Now()
	for range time.Tick(2 * time.Second) {
		tr.mu.Lock()
		active, seen, lastZero := tr.active, tr.seen, tr.lastZero
		tr.mu.Unlock()
		if !seen && time.Since(started) > firstWait {
			return
		}
		if seen && active == 0 && time.Since(lastZero) > idle {
			return
		}
	}
}

func siteHandler(root fs.FS) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		p := strings.TrimPrefix(path.Clean(r.URL.Path), "/")
		if p == "" || p == "." {
			p = "index.html"
		}
		if st, err := fs.Stat(root, p); err == nil && st.IsDir() {
			if !strings.HasSuffix(r.URL.Path, "/") {
				http.Redirect(w, r, r.URL.Path+"/", http.StatusMovedPermanently)
				return
			}
			p = path.Join(p, "index.html")
		}
		data, err := fs.ReadFile(root, p)
		if err != nil {
			http.NotFound(w, r)
			return
		}
		h := w.Header()
		// 멀티스레드 CPU 추론(SharedArrayBuffer)에 필요한 격리 헤더
		h.Set("Cross-Origin-Opener-Policy", "same-origin")
		h.Set("Cross-Origin-Embedder-Policy", "credentialless")
		h.Set("Cross-Origin-Resource-Policy", "same-origin")
		h.Set("X-Content-Type-Options", "nosniff")
		ext := strings.ToLower(path.Ext(p))
		ct := map[string]string{".wasm": "application/wasm", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
			".webmanifest": "application/manifest+json", ".svg": "image/svg+xml", ".html": "text/html; charset=utf-8", ".json": "application/json"}[ext]
		if ct == "" {
			ct = mime.TypeByExtension(ext)
		}
		if ct != "" {
			h.Set("Content-Type", ct)
		}
		if ext == ".html" {
			h.Set("Cache-Control", "no-cache")
			if i := bytes.LastIndex(data, []byte("</body>")); i >= 0 {
				data = append(append(append([]byte{}, data[:i]...), keepAlive...), data[i:]...)
			} else {
				data = append(append([]byte{}, data...), keepAlive...)
			}
		} else {
			h.Set("Cache-Control", "public, max-age=3600")
		}
		if r.Method == http.MethodHead {
			return
		}
		w.Write(data)
	})
}

func ping(base string) bool {
	c := http.Client{Timeout: 700 * time.Millisecond}
	res, err := c.Get(base + "/__nuri/ping")
	if err != nil {
		return false
	}
	defer res.Body.Close()
	buf := make([]byte, 4)
	n, _ := res.Body.Read(buf)
	return string(buf[:n]) == "nuri"
}

func envDuration(k string, d time.Duration) time.Duration {
	if v := os.Getenv(k); v != "" {
		if x, err := time.ParseDuration(v); err == nil {
			return x
		}
	}
	return d
}

// ---- 외부 API 중계 ----
// 브라우저는 보안정책(CORS) 때문에 거래소·AI API를 직접 부를 수 없는 경우가 많아,
// 이 실행기가 정해진 주소로만 요청을 대신 전달한다. (임의 주소 중계는 하지 않음)
var upstreams = map[string]string{
	"nvidia":  "https://integrate.api.nvidia.com/v1",
	"upbit":   "https://api.upbit.com/v1",
	"binance": "https://api.binance.com/api/v3",
	"ollama":  "http://127.0.0.1:11434",
}

var proxyClient = &http.Client{}

func proxyHandler(w http.ResponseWriter, r *http.Request) {
	// 다른 웹사이트가 이 중계를 쓰지 못하게 같은 출처 요청만 허용
	if site := r.Header.Get("Sec-Fetch-Site"); site != "" && site != "same-origin" {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}
	rest := strings.TrimPrefix(r.URL.Path, "/__nuri/proxy/")
	name, tail, _ := strings.Cut(rest, "/")
	base, ok := upstreams[name]
	if env := os.Getenv("NURI_UPSTREAM_" + strings.ToUpper(name)); env != "" && ok {
		base = env
	}
	if !ok {
		http.NotFound(w, r)
		return
	}
	target := strings.TrimRight(base, "/") + "/" + tail
	if r.URL.RawQuery != "" {
		target += "?" + r.URL.RawQuery
	}
	req, err := http.NewRequestWithContext(r.Context(), r.Method, target, r.Body)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	for _, h := range []string{"Authorization", "Content-Type", "Accept"} {
		if v := r.Header.Get(h); v != "" {
			req.Header.Set(h, v)
		}
	}
	req.Header.Set("User-Agent", "NuriAI/1.0")
	res, err := proxyClient.Do(req)
	if err != nil {
		http.Error(w, "upstream: "+err.Error(), http.StatusBadGateway)
		return
	}
	defer res.Body.Close()
	for _, h := range []string{"Content-Type", "Retry-After", "Remaining-Req"} {
		if v := res.Header.Get(h); v != "" {
			w.Header().Set(h, v)
		}
	}
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(res.StatusCode)
	fl, _ := w.(http.Flusher)
	buf := make([]byte, 16*1024)
	for {
		n, err := res.Body.Read(buf)
		if n > 0 {
			if _, werr := w.Write(buf[:n]); werr != nil {
				return
			}
			if fl != nil {
				fl.Flush() // 스트리밍 답변이 바로바로 보이도록
			}
		}
		if err == io.EOF || err != nil {
			return
		}
	}
}
