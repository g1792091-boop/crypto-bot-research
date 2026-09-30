//go:build !windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"runtime"
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
