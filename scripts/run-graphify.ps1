# Load GEMINI_API_KEY from backend/.env and run graphify.
# Graphify only reads process env vars; it does not load backend/.env itself.
#
# Usage (from repo root):
#   .\scripts\run-graphify.ps1
#   .\scripts\run-graphify.ps1 .
#   .\scripts\run-graphify.ps1 extract . --backend gemini --max-concurrency 1
#   .\scripts\run-graphify.ps1 extract . --code-only

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $RepoRoot "backend\.env"
if (-not (Test-Path $EnvFile)) {
  $RepoRoot = (Get-Location).Path
  $EnvFile = Join-Path $RepoRoot "backend\.env"
}
if (-not (Test-Path $EnvFile)) {
  Write-Error "Missing backend/.env - add GEMINI_API_KEY there first."
}

Get-Content $EnvFile | ForEach-Object {
  $line = $_.Trim()
  if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
  $i = $line.IndexOf("=")
  $name = $line.Substring(0, $i).Trim()
  $value = $line.Substring($i + 1).Trim().Trim('"').Trim("'")
  $wanted = @(
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GRAPHIFY_GEMINI_MODEL",
    "GEMINI_BASE_URL"
  )
  if ($wanted -contains $name) {
    Set-Item -Path ("Env:" + $name) -Value $value
  }
}

if (-not $env:GEMINI_API_KEY -and -not $env:GOOGLE_API_KEY) {
  Write-Error "GEMINI_API_KEY / GOOGLE_API_KEY not found in backend/.env"
}

if (-not $env:GRAPHIFY_GEMINI_MODEL) {
  $env:GRAPHIFY_GEMINI_MODEL = "gemini-flash-lite-latest"
}
# Do NOT set GRAPHIFY_DISABLE_THINKING for Gemini (Google rejects that payload).
Remove-Item Env:GRAPHIFY_DISABLE_THINKING -ErrorAction SilentlyContinue

Write-Host ("GEMINI_API_KEY loaded (len={0})" -f $env:GEMINI_API_KEY.Length)
Write-Host ("GRAPHIFY_GEMINI_MODEL={0}" -f $env:GRAPHIFY_GEMINI_MODEL)

Set-Location $RepoRoot

$GraphifyArgs = @($args)
if (-not $GraphifyArgs -or $GraphifyArgs.Count -eq 0) {
  $GraphifyArgs = @(
    "extract", ".", "--backend", "gemini",
    "--max-concurrency", "1", "--token-budget", "12000"
  )
} elseif ($GraphifyArgs[0] -eq "." -or (Test-Path -LiteralPath $GraphifyArgs[0])) {
  $GraphifyArgs = @("extract") + $GraphifyArgs
  if ($GraphifyArgs -notcontains "--backend") {
    $GraphifyArgs += @("--backend", "gemini")
  }
}

# Route through cmd so PowerShell does not steal flags like --out / --model
$argLine = ($GraphifyArgs | ForEach-Object {
  if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
}) -join " "

Write-Host ("Running: graphify {0}" -f $argLine)
cmd /c "graphify $argLine"
exit $LASTEXITCODE
