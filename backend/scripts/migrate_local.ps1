# Run Alembic migrations for local development (SQLite or Postgres via DATABASE_URL)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (Test-Path ".env") {
  Get-Content ".env" | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
    $name, $value = $_.Split('=', 2)
    if ($name -and $value) {
      [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), "Process")
    }
  }
}

if (-not $env:DATABASE_URL) {
  $env:DATABASE_URL = "sqlite:///./agentic_db.sqlite"
}

Write-Host "Migrating: $($env:DATABASE_URL)"
python -m alembic upgrade head
Write-Host "Done."
