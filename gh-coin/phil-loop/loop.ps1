# GH Coin 자기개선 루프 실행기 (Windows PowerShell) — bennyjo/phil 의 loop.sh 를 GH Coin 에 맞게.
#   사용법:  .\loop.ps1 1        (1 사이클)
#            .\loop.ps1 5 60     (5 사이클, 60분 간격)
#   필요: Claude Code(claude) · Node.js · git. GHCoin.exe 가 켜져 있어야 정책이 앱에 바로 반영됩니다.
#   안전: 실거래 옵션은 없습니다. 루프는 strategy/ · journal/ 만 고칠 수 있고, 보호 파일을 고치면 사이클 뒤 되돌립니다.
param([int]$Cycles = 1, [int]$SleepMinutes = 60)
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$lock = Join-Path $PSScriptRoot ".loop.pid"
if (Test-Path $lock) { $old = Get-Content $lock -ErrorAction SilentlyContinue; if ($old -and (Get-Process -Id $old -ErrorAction SilentlyContinue)) { Write-Host "이미 실행 중입니다(pid $old). 하나만 돌리세요."; exit 1 } }
$PID | Set-Content $lock
$protected = @("core", "CYCLE.md", "CLAUDE.md", "loop.ps1", "loop.sh", ".gitignore")
try {
  for ($i = 1; $i -le $Cycles; $i++) {
    Write-Host "=== 사이클 $i/$Cycles $(Get-Date -Format s) ==="
    $prompt = Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot "CYCLE.md")
    & claude -p $prompt --permission-mode acceptEdits --allowedTools "Read" "Glob" "Grep" "Edit" "Write" "Bash(node core/score.mjs*)" "Bash(node core/apply.mjs*)" "Bash(git add:*)" "Bash(git commit:*)" "Bash(git log:*)" "Bash(git diff:*)" "Bash(git status:*)" "Bash(git rev-parse:*)"
    if ($LASTEXITCODE -ne 0) { Write-Host "사이클 $i 실패 — 다음으로" }
    # 보호 파일을 건드렸으면 되돌린다(커밋 전 변경 · 커밋된 변경 모두 경고)
    git diff --quiet HEAD -- $protected; if ($LASTEXITCODE -ne 0) { Write-Host "경고: 루프가 보호 파일을 고쳤습니다 — 되돌립니다"; git checkout -- $protected }
    $hit = git log --oneline -3 --name-only | Select-String -Pattern '^(core/|CYCLE\.md|CLAUDE\.md|loop\.ps1|loop\.sh|\.gitignore)'
    if ($hit) { Write-Host "경고: 최근 커밋에 보호 파일 변경이 있습니다 — 직접 확인하세요(git log -3 --stat)" }
    Write-Host "--- 채점 ---"; node core/score.mjs | Select-Object -First 3
    if ($i -lt $Cycles) { Start-Sleep -Seconds ($SleepMinutes * 60) }
  }
} finally { Remove-Item $lock -ErrorAction SilentlyContinue }
