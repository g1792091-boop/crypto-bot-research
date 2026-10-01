// 코드 모드: 사용자가 고른 작업 폴더 안에서만 파일을 읽고·쓰고·찾고, 명령을 실행한다.
// 이 페이지(같은 출처)에서 세션 토큰을 붙인 요청만 받는다.
package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

var (
	sessionToken = newToken()
	wsMu         sync.Mutex
	workspace    string
)

var skipDirs = map[string]bool{".git": true, "node_modules": true, "__pycache__": true, ".venv": true, "venv": true, ".idea": true, ".vs": true, ".next": true, "target": true}

func newToken() string {
	b := make([]byte, 18)
	rand.Read(b)
	return hex.EncodeToString(b)
}

type obj = map[string]any

func codeHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method", http.StatusMethodNotAllowed)
		return
	}
	if site := r.Header.Get("Sec-Fetch-Site"); site != "" && site != "same-origin" {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}
	if r.Header.Get("X-Nuri-Token") != sessionToken {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}
	var in obj
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 20<<20)).Decode(&in); err != nil {
		in = obj{}
	}
	action := strings.TrimPrefix(r.URL.Path, "/__nuri/code/")
	out, err := runCode(r.Context(), action, in)
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	if err != nil {
		json.NewEncoder(w).Encode(obj{"ok": false, "error": err.Error()})
		return
	}
	out["ok"] = true
	json.NewEncoder(w).Encode(out)
}

func str(in obj, k string) string {
	if v, ok := in[k].(string); ok {
		return v
	}
	return ""
}

func num(in obj, k string, d int) int {
	if v, ok := in[k].(float64); ok {
		return int(v)
	}
	return d
}

func currentWS() (string, error) {
	wsMu.Lock()
	defer wsMu.Unlock()
	if workspace == "" {
		return "", errors.New("작업 폴더가 열려 있지 않습니다. 먼저 폴더를 여세요")
	}
	return workspace, nil
}

// 작업 폴더 밖으로 나가는 경로는 거부한다
func resolve(p string) (string, error) {
	ws, err := currentWS()
	if err != nil {
		return "", err
	}
	if p == "" {
		p = "."
	}
	var abs string
	if filepath.IsAbs(p) {
		abs = filepath.Clean(p)
	} else {
		abs = filepath.Join(ws, filepath.FromSlash(p))
	}
	rel, err := filepath.Rel(ws, abs)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("작업 폴더 밖의 경로는 쓸 수 없습니다: %s", p)
	}
	return abs, nil
}

func relOf(abs string) string {
	ws, _ := currentWS()
	r, err := filepath.Rel(ws, abs)
	if err != nil {
		return abs
	}
	return filepath.ToSlash(r)
}

func isBinary(b []byte) bool {
	n := len(b)
	if n > 8000 {
		n = 8000
	}
	return bytes.IndexByte(b[:n], 0) >= 0
}

func runCode(ctx context.Context, action string, in obj) (obj, error) {
	switch action {
	case "pick":
		p, err := pickFolder()
		if err != nil {
			return nil, err
		}
		return obj{"path": p}, nil

	case "open":
		p := filepath.Clean(str(in, "path"))
		st, err := os.Stat(p)
		if err != nil || !st.IsDir() {
			return nil, fmt.Errorf("폴더를 찾을 수 없습니다: %s", str(in, "path"))
		}
		abs, _ := filepath.Abs(p)
		wsMu.Lock()
		workspace = abs
		wsMu.Unlock()
		return obj{"path": abs, "name": filepath.Base(abs)}, nil

	case "ls":
		root, err := resolve(str(in, "path"))
		if err != nil {
			return nil, err
		}
		depth := num(in, "depth", 2)
		if depth < 1 {
			depth = 1
		}
		if depth > 5 {
			depth = 5
		}
		var lines []string
		base := strings.Count(root, string(filepath.Separator))
		filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
			if err != nil || p == root {
				return nil
			}
			if d.IsDir() && skipDirs[d.Name()] {
				lines = append(lines, relOf(p)+"/ (생략)")
				return filepath.SkipDir
			}
			if strings.Count(p, string(filepath.Separator))-base > depth {
				if d.IsDir() {
					return filepath.SkipDir
				}
				return nil
			}
			if len(lines) >= 400 {
				return filepath.SkipAll
			}
			if d.IsDir() {
				lines = append(lines, relOf(p)+"/")
			} else if info, e := d.Info(); e == nil {
				lines = append(lines, fmt.Sprintf("%s (%s)", relOf(p), human(info.Size())))
			}
			return nil
		})
		return obj{"entries": lines, "truncated": len(lines) >= 400}, nil

	case "read":
		p, err := resolve(str(in, "path"))
		if err != nil {
			return nil, err
		}
		st, err := os.Stat(p)
		if err != nil {
			return nil, fmt.Errorf("파일이 없습니다: %s", str(in, "path"))
		}
		if st.IsDir() {
			return nil, errors.New("폴더입니다. list_files를 쓰세요")
		}
		if st.Size() > 4<<20 {
			return nil, errors.New("4MB가 넘는 파일은 읽을 수 없습니다")
		}
		b, _ := os.ReadFile(p)
		if isBinary(b) {
			return nil, errors.New("바이너리 파일이라 읽을 수 없습니다")
		}
		all := strings.Split(strings.ReplaceAll(string(b), "\r\n", "\n"), "\n")
		off := num(in, "offset", 1)
		if off < 1 {
			off = 1
		}
		lim := num(in, "limit", 1500)
		var sb strings.Builder
		end := off - 1 + lim
		if end > len(all) {
			end = len(all)
		}
		for i := off - 1; i < end; i++ {
			line := all[i]
			if len(line) > 2000 {
				line = line[:2000] + "…"
			}
			fmt.Fprintf(&sb, "%6d\t%s\n", i+1, line)
		}
		return obj{"content": sb.String(), "total_lines": len(all), "from": off, "to": end}, nil

	case "raw":
		p, err := resolve(str(in, "path"))
		if err != nil {
			return nil, err
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return obj{"exists": false, "content": ""}, nil
		}
		if len(b) > 1<<20 || isBinary(b) {
			return obj{"exists": true, "content": "", "skipped": true}, nil
		}
		return obj{"exists": true, "content": string(b)}, nil

	case "write":
		p, err := resolve(str(in, "path"))
		if err != nil {
			return nil, err
		}
		old, rerr := os.ReadFile(p)
		os.MkdirAll(filepath.Dir(p), 0o755)
		content := str(in, "content")
		if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
			return nil, err
		}
		return obj{"path": relOf(p), "created": rerr != nil, "bytes": len(content), "old": clip(string(old), 400000)}, nil

	case "edit":
		p, err := resolve(str(in, "path"))
		if err != nil {
			return nil, err
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return nil, fmt.Errorf("파일이 없습니다: %s", str(in, "path"))
		}
		src := string(b)
		crlf := strings.Contains(src, "\r\n")
		work := src
		oldS, newS := str(in, "old_string"), str(in, "new_string")
		if crlf {
			work = strings.ReplaceAll(src, "\r\n", "\n")
			oldS = strings.ReplaceAll(oldS, "\r\n", "\n")
			newS = strings.ReplaceAll(newS, "\r\n", "\n")
		}
		if oldS == "" {
			return nil, errors.New("old_string이 비어 있습니다")
		}
		n := strings.Count(work, oldS)
		if n == 0 {
			return nil, errors.New("바꿀 문자열을 파일에서 찾지 못했습니다. read_file로 정확한 내용을 확인하세요")
		}
		all, _ := in["replace_all"].(bool)
		if n > 1 && !all {
			return nil, fmt.Errorf("같은 문자열이 %d곳에 있습니다. 앞뒤 내용을 더 넣어 하나로 특정하거나 replace_all을 쓰세요", n)
		}
		var res string
		if all {
			res = strings.ReplaceAll(work, oldS, newS)
		} else {
			res = strings.Replace(work, oldS, newS, 1)
		}
		if crlf {
			res = strings.ReplaceAll(res, "\n", "\r\n")
		}
		if err := os.WriteFile(p, []byte(res), 0o644); err != nil {
			return nil, err
		}
		line := strings.Count(work[:strings.Index(work, oldS)], "\n") + 1
		return obj{"path": relOf(p), "replaced": map[bool]int{true: n, false: 1}[all], "line": line}, nil

	case "glob":
		ws, err := currentWS()
		if err != nil {
			return nil, err
		}
		re, err := globRegex(str(in, "pattern"))
		if err != nil {
			return nil, err
		}
		var hits []string
		filepath.WalkDir(ws, func(p string, d fs.DirEntry, err error) error {
			if err != nil {
				return nil
			}
			if d.IsDir() {
				if skipDirs[d.Name()] {
					return filepath.SkipDir
				}
				return nil
			}
			if r := relOf(p); re.MatchString(r) {
				hits = append(hits, r)
			}
			if len(hits) >= 500 {
				return filepath.SkipAll
			}
			return nil
		})
		sort.Strings(hits)
		return obj{"files": hits, "truncated": len(hits) >= 500}, nil

	case "grep":
		ws, err := currentWS()
		if err != nil {
			return nil, err
		}
		re, err := regexp.Compile(str(in, "pattern"))
		if err != nil {
			return nil, fmt.Errorf("정규식 오류: %v", err)
		}
		var gre *regexp.Regexp
		if g := str(in, "glob"); g != "" {
			if !strings.Contains(g, "/") {
				g = "**/" + g
			}
			gre, _ = globRegex(g)
		}
		var hits []string
		filepath.WalkDir(ws, func(p string, d fs.DirEntry, err error) error {
			if err != nil {
				return nil
			}
			if d.IsDir() {
				if skipDirs[d.Name()] {
					return filepath.SkipDir
				}
				return nil
			}
			r := relOf(p)
			if gre != nil && !gre.MatchString(r) {
				return nil
			}
			if info, e := d.Info(); e != nil || info.Size() > 1<<20 {
				return nil
			}
			b, e := os.ReadFile(p)
			if e != nil || isBinary(b) {
				return nil
			}
			sc := bufio.NewScanner(bytes.NewReader(b))
			sc.Buffer(make([]byte, 64*1024), 1<<20)
			ln := 0
			for sc.Scan() {
				ln++
				if re.MatchString(sc.Text()) {
					t := strings.TrimSpace(sc.Text())
					if len(t) > 240 {
						t = t[:240] + "…"
					}
					hits = append(hits, fmt.Sprintf("%s:%d: %s", r, ln, t))
					if len(hits) >= 300 {
						return filepath.SkipAll
					}
				}
			}
			return nil
		})
		return obj{"matches": hits, "truncated": len(hits) >= 300}, nil

	case "exec":
		ws, err := currentWS()
		if err != nil {
			return nil, err
		}
		cmdline := str(in, "command")
		if strings.TrimSpace(cmdline) == "" {
			return nil, errors.New("명령이 비어 있습니다")
		}
		t := num(in, "timeout", 120)
		if t < 1 {
			t = 1
		}
		if t > 600 {
			t = 600
		}
		cctx, cancel := context.WithTimeout(ctx, time.Duration(t)*time.Second)
		defer cancel()
		cmd := shellCmd(cctx, cmdline)
		cmd.Dir = ws
		start := time.Now()
		outb, err := cmd.CombinedOutput()
		code := 0
		if cmd.ProcessState != nil {
			code = cmd.ProcessState.ExitCode()
		}
		timedOut := errors.Is(cctx.Err(), context.DeadlineExceeded)
		if err != nil && cmd.ProcessState == nil {
			return nil, fmt.Errorf("명령을 실행하지 못했습니다: %v", err)
		}
		return obj{"exit_code": code, "output": clipMiddle(decodeOutput(outb), 30000), "timed_out": timedOut, "ms": time.Since(start).Milliseconds()}, nil
	}
	return nil, fmt.Errorf("알 수 없는 동작: %s", action)
}

func globRegex(g string) (*regexp.Regexp, error) {
	if g == "" {
		return nil, errors.New("패턴이 비어 있습니다")
	}
	g = filepath.ToSlash(g)
	var sb strings.Builder
	sb.WriteString("^")
	for i := 0; i < len(g); i++ {
		c := g[i]
		switch {
		case strings.HasPrefix(g[i:], "**/"):
			sb.WriteString("(?:.*/)?")
			i += 2
		case strings.HasPrefix(g[i:], "**"):
			sb.WriteString(".*")
			i++
		case c == '*':
			sb.WriteString("[^/]*")
		case c == '?':
			sb.WriteString("[^/]")
		case c == '{':
			sb.WriteString("(?:")
		case c == '}':
			sb.WriteString(")")
		case c == ',':
			sb.WriteString("|")
		default:
			sb.WriteString(regexp.QuoteMeta(string(c)))
		}
	}
	sb.WriteString("$")
	return regexp.Compile(sb.String())
}

func human(n int64) string {
	switch {
	case n >= 1<<20:
		return fmt.Sprintf("%.1fMB", float64(n)/(1<<20))
	case n >= 1<<10:
		return fmt.Sprintf("%.1fKB", float64(n)/(1<<10))
	}
	return fmt.Sprintf("%dB", n)
}

func clip(s string, n int) string {
	if len(s) > n {
		return s[:n]
	}
	return s
}

func clipMiddle(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n/2] + fmt.Sprintf("\n… (%d자 생략) …\n", len(s)-n) + s[len(s)-n/2:]
}
