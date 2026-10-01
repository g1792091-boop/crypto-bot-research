//go:build !windows

package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"
)

func openApp(url string) {
	if os.Getenv("NURI_NO_BROWSER") != "" {
		fmt.Println("open:", url)
		return
	}
	name := "xdg-open"
	if runtime.GOOS == "darwin" {
		name = "open"
	}
	exec.Command(name, url).Start()
}

func showError(title, msg string) { fmt.Fprintln(os.Stderr, title+": "+msg) }

func killOthers() {}

func shellCmd(ctx context.Context, command string) *exec.Cmd {
	return exec.CommandContext(ctx, "sh", "-c", command)
}

func decodeOutput(b []byte) string { return strings.ToValidUTF8(string(b), "?") }

func pickFolder() (string, error) {
	if p := os.Getenv("NURI_PICK"); p != "" { // 테스트용
		return p, nil
	}
	return "", errors.New("이 운영체제에서는 폴더 선택 창을 지원하지 않습니다. 경로를 직접 입력하세요")
}

// 폴더를 파일 관리자로 연다
func openDir(dir string) {
	if runtime.GOOS == "darwin" {
		exec.Command("open", dir).Start()
		return
	}
	exec.Command("xdg-open", dir).Start()
}
