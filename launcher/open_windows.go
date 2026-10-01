//go:build windows

package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"unicode/utf8"
	"unsafe"

	"golang.org/x/text/encoding/korean"
)

// 앱처럼 보이도록 Edge/Chrome의 앱 창(--app)으로 열고, 없으면 기본 브라우저로 연다.
func openApp(url string) {
	candidates := []string{}
	for _, env := range []string{"ProgramFiles(x86)", "ProgramFiles", "LocalAppData"} {
		base := os.Getenv(env)
		if base == "" {
			continue
		}
		candidates = append(candidates,
			filepath.Join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
			filepath.Join(base, "Google", "Chrome", "Application", "chrome.exe"))
	}
	for _, exe := range candidates {
		if _, err := os.Stat(exe); err == nil {
			cmd := exec.Command(exe, "--app="+url, "--start-maximized")
			cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
			if cmd.Start() == nil {
				return
			}
		}
	}
	cmd := exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	cmd.Start()
}

func showError(title, msg string) {
	user32 := syscall.NewLazyDLL("user32.dll")
	box := user32.NewProc("MessageBoxW")
	t, _ := syscall.UTF16PtrFromString(title)
	m, _ := syscall.UTF16PtrFromString(msg)
	box.Call(0, uintptr(unsafe.Pointer(m)), uintptr(unsafe.Pointer(t)), 0x10)
}

// 예전 실행기(버전 확인 기능이 없는 것 포함)를 강제로 끈다. 자기 자신은 제외.
func killOthers() {
	self, _ := os.Executable()
	names := map[string]bool{"NuriAI.exe": true, "GHNano.exe": true, "ArchAI.exe": true, filepath.Base(self): true}
	for name := range names {
		cmd := exec.Command("taskkill", "/F", "/IM", name, "/FI", fmt.Sprintf("PID ne %d", os.Getpid()))
		cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
		cmd.Run()
	}
}

// 코드 모드: cmd로 명령 실행 (UTF-8 코드페이지, 콘솔 창 숨김)
func shellCmd(ctx context.Context, command string) *exec.Cmd {
	cmd := exec.CommandContext(ctx, "cmd", "/C", "chcp 65001>nul & "+command)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	return cmd
}

// 한글 윈도우 프로그램이 CP949로 출력해도 깨지지 않게 변환
func decodeOutput(b []byte) string {
	if utf8.Valid(b) {
		return string(b)
	}
	if s, err := korean.EUCKR.NewDecoder().Bytes(b); err == nil {
		return string(s)
	}
	return strings.ToValidUTF8(string(b), "?")
}

// 윈도우 폴더 선택 창을 띄워 경로를 받는다
func pickFolder() (string, error) {
	script := `[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; Add-Type -AssemblyName System.Windows.Forms; ` +
		`$o=New-Object System.Windows.Forms.Form -Property @{TopMost=$true}; $f=New-Object System.Windows.Forms.FolderBrowserDialog; ` +
		`$f.Description='누리 AI 코드 모드에서 작업할 폴더를 고르세요'; if($f.ShowDialog($o) -eq 'OK'){ $f.SelectedPath }`
	cmd := exec.Command("powershell", "-NoProfile", "-STA", "-Command", script)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	out, err := cmd.Output()
	if err != nil {
		return "", errors.New("폴더 선택 창을 열지 못했습니다. 경로를 직접 입력하세요")
	}
	p := strings.TrimSpace(string(out))
	if p == "" {
		return "", errors.New("폴더를 고르지 않았습니다")
	}
	return p, nil
}

// 폴더를 탐색기로 연다
func openDir(dir string) { exec.Command("explorer", dir).Start() }
