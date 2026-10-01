// 스스로 코드 고치기: AI 팀이 만든 수정안을 대표가 승인하면, 앱 파일을 사무실 폴더(app-patches)의 고친 파일로 바꿔서 내보낸다.
// 원본(exe 안의 파일)은 그대로 두고, 고친 파일만 덮어쓴다. DISABLED 파일이 있으면 전부 끈다(안전 모드).
// 실거래·키·안전장치 파일과 화면 틀(index.html)은 절대 바꿀 수 없다.
package main

import (
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"
)

var protectedFiles = map[string]bool{
	"nuri-ai/live.js": true, "nuri-ai/live-ui.js": true, "nuri-ai/live.css": true, "nuri-ai/sw.js": true,
	"nuri-ai/index.html": true, "nuri-ai/selfdev.js": true, "nuri-ai/engine.js": true,
}

func patchDir() (string, error) {
	ws, err := officeWS()
	if err != nil {
		return "", err
	}
	dir := filepath.Join(ws, "app-patches")
	return dir, os.MkdirAll(dir, 0o755)
}

// 덮어쓸 수 있는 경로인지: nuri-ai/ 아래 .js/.css, 상위 이동·보호 파일·vendor 금지
func overridable(p string) (string, error) {
	p = strings.TrimPrefix(path.Clean("/"+strings.ReplaceAll(p, "\\", "/")), "/")
	if strings.Contains(p, "..") || !strings.HasPrefix(p, "nuri-ai/") {
		return "", errors.New("nuri-ai/ 안의 파일만 고칠 수 있습니다")
	}
	if ext := path.Ext(p); ext != ".js" && ext != ".css" {
		return "", errors.New(".js · .css 파일만 고칠 수 있습니다")
	}
	if protectedFiles[p] || strings.HasPrefix(p, "nuri-ai/vendor/") {
		return "", errors.New("보호된 파일입니다 (실거래·키·안전장치·화면 틀)")
	}
	return p, nil
}

func overridesEnabled() bool {
	dir, err := patchDir()
	if err != nil {
		return false
	}
	_, err = os.Stat(filepath.Join(dir, "DISABLED"))
	return err != nil
}

// siteHandler 가 부른다: 승인된 고친 파일이 있으면 그 내용
func readOverride(p string) ([]byte, bool) {
	if _, err := overridable(p); err != nil || !overridesEnabled() {
		return nil, false
	}
	dir, _ := patchDir()
	b, err := os.ReadFile(filepath.Join(dir, filepath.FromSlash(p)))
	if err != nil {
		return nil, false
	}
	return b, true
}

func overrideHandler(w http.ResponseWriter, r *http.Request) {
	if site := r.Header.Get("Sec-Fetch-Site"); site != "" && site != "same-origin" {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}
	if r.Header.Get("X-Nuri-Token") != sessionToken {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}
	dir, err := patchDir()
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	reply := func(v any) { w.Header().Set("Content-Type", "application/json"); json.NewEncoder(w).Encode(v) }
	fail := func(msg string) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(400)
		json.NewEncoder(w).Encode(obj{"ok": false, "error": msg})
	}
	switch strings.TrimPrefix(r.URL.Path, "/__nuri/override") {
	case "/disable":
		os.WriteFile(filepath.Join(dir, "DISABLED"), []byte("안전 모드"), 0o644)
		reply(obj{"ok": true, "enabled": false})
		return
	case "/enable":
		os.Remove(filepath.Join(dir, "DISABLED"))
		reply(obj{"ok": true, "enabled": true})
		return
	case "", "/":
	default:
		http.NotFound(w, r)
		return
	}
	switch r.Method {
	case http.MethodGet:
		files := []obj{}
		filepath.WalkDir(dir, func(fp string, d os.DirEntry, err error) error {
			if err != nil || d.IsDir() {
				return nil
			}
			rel, _ := filepath.Rel(dir, fp)
			rel = filepath.ToSlash(rel)
			if _, e := overridable(rel); e != nil {
				return nil
			}
			if st, e := d.Info(); e == nil {
				files = append(files, obj{"path": rel, "size": st.Size(), "mtime": st.ModTime().UnixMilli()})
			}
			return nil
		})
		sort.Slice(files, func(i, j int) bool { return files[i]["path"].(string) < files[j]["path"].(string) })
		reply(obj{"ok": true, "enabled": overridesEnabled(), "dir": dir, "files": files})
	case http.MethodPost:
		var in struct{ Path, Content string }
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 3<<20)).Decode(&in); err != nil {
			fail("요청 형식 오류")
			return
		}
		p, err := overridable(in.Path)
		if err != nil {
			fail(err.Error())
			return
		}
		if len(in.Content) == 0 || len(in.Content) > 2<<20 {
			fail("파일 크기가 올바르지 않습니다")
			return
		}
		fp := filepath.Join(dir, filepath.FromSlash(p))
		os.MkdirAll(filepath.Dir(fp), 0o755)
		if err := os.WriteFile(fp, []byte(in.Content), 0o644); err != nil {
			fail(err.Error())
			return
		}
		reply(obj{"ok": true, "path": p})
	case http.MethodDelete:
		p, err := overridable(r.URL.Query().Get("path"))
		if err != nil {
			fail(err.Error())
			return
		}
		os.Remove(filepath.Join(dir, filepath.FromSlash(p)))
		reply(obj{"ok": true, "path": p})
	default:
		http.Error(w, "method", http.StatusMethodNotAllowed)
	}
}
