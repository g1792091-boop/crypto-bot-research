#!/usr/bin/env bash
# 윈도우용 실행 파일 빌드: ./build.sh  →  ../dist/NuriAI.exe, ../dist/ArchAI.exe
set -euo pipefail
cd "$(dirname "$0")"
rm -rf site && mkdir -p site ../dist
cp ../index.html site/
cp -r ../nuri-ai ../arch-ai site/
rm -f site/*/README.md
build() { # 이름 시작경로 아이콘
  cp "icons/$3.syso" rsrc_windows_amd64.syso
  GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags "-H=windowsgui -s -w -X main.startPath=$2 -X 'main.appName=$4'" -o "../dist/$1" .
  rm -f rsrc_windows_amd64.syso
}
build NuriAI.exe /nuri-ai/ nuri "누리 AI"
build ArchAI.exe /arch-ai/ arch "건축설계 AI"
rm -rf site
ls -la ../dist
