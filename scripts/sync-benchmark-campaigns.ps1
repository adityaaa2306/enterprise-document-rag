# Sync offline benchmark campaign artifacts into the Next.js public folder.
# Read-only copy — does not run benchmarks or call LLMs.
#
# Usage (repo root):
#   .\scripts\sync-benchmark-campaigns.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Src = Join-Path $Root "benchmark_results\campaigns"
$Dst = Join-Path $Root "frontend\public\benchmark-campaigns"

if (-not (Test-Path $Src)) {
  Write-Error "No campaigns found at $Src"
}

New-Item -ItemType Directory -Force -Path $Dst | Out-Null
$index = @()

Get-ChildItem $Src -Directory | Where-Object { $_.Name -like "campaign_*" } | ForEach-Object {
  $id = $_.Name
  $out = Join-Path $Dst $id
  New-Item -ItemType Directory -Force -Path $out | Out-Null

  foreach ($f in @("config.json", "metadata.json", "dashboard.json", "summary.json", "REPORT.md")) {
    $p = Join-Path $_.FullName $f
    if (Test-Path $p) { Copy-Item $p (Join-Path $out $f) -Force }
  }

  $results = Join-Path $_.FullName "results.json"
  if (Test-Path $results) {
    $py = @"
import json
from pathlib import Path
src = Path(r'$($results.Replace('\','/'))')
dst = Path(r'$($out.Replace('\','/'))') / 'questions.json'
data = json.loads(src.read_text(encoding='utf-8'))
slim = []
for q in data.get('questions') or []:
    runs = []
    for r in q.get('model_runs') or []:
        runs.append({
            'model': r.get('model') or r.get('model_requested'),
            'model_returned': r.get('model_returned'),
            'ok': r.get('ok'),
            'error': r.get('error'),
            'answer': r.get('answer') or r.get('summary') or '',
            'summary': r.get('summary') or r.get('answer') or '',
            'summary_length': r.get('summary_length'),
            'summary_chars': r.get('summary_chars'),
            'summary_words': r.get('summary_words'),
            'latency_ms': r.get('latency_ms'),
            'ttft_ms': r.get('ttft_ms'),
            'tokens_per_sec': r.get('tokens_per_sec'),
            'prompt_tokens': r.get('prompt_tokens'),
            'completion_tokens': r.get('completion_tokens'),
            'total_tokens': r.get('total_tokens'),
            'estimated_api_cost_usd': r.get('estimated_api_cost_usd'),
            'estimated_energy_wh': r.get('estimated_energy_wh'),
            'estimated_co2e_g': r.get('estimated_co2e_g'),
            'finish_reason': r.get('finish_reason'),
            'participant_kind': r.get('participant_kind'),
            'routing': r.get('routing') or {},
            'quality': r.get('quality') or {},
            'quality_score': r.get('quality_score'),
            'correctness': r.get('correctness'),
            'completeness': r.get('completeness'),
            'groundedness': r.get('groundedness'),
            'conciseness': r.get('conciseness'),
        })
    slim.append({
        'question': q.get('question'),
        'task': q.get('task'),
        'ok': q.get('ok'),
        'document_id': q.get('document_id'),
        'context_hash': q.get('context_hash'),
        'prompt_hash': q.get('prompt_hash'),
        'chunk_count': q.get('chunk_count'),
        'reference_answer': q.get('reference_answer') or q.get('reference_summary'),
        'reference_summary': q.get('reference_summary') or q.get('reference_answer'),
        'model_runs': runs,
    })
workload = (data.get('metadata') or {}).get('workload') or 'interactive_rag'
dst.write_text(json.dumps({'workload': workload, 'questions': slim}, indent=2), encoding='utf-8')
print(dst)
"@
    python -c $py | Out-Null
  }

  $metaPath = Join-Path $_.FullName "metadata.json"
  $cfgPath = Join-Path $_.FullName "config.json"
  $meta = if (Test-Path $metaPath) { Get-Content $metaPath -Raw | ConvertFrom-Json } else { $null }
  $cfg = if (Test-Path $cfgPath) { Get-Content $cfgPath -Raw | ConvertFrom-Json } else { $null }

  $label = $id
  if ($id -match '_v[\d.]+_(.+)$') { $label = $Matches[1] }

  $docName = $cfg.filename
  if (-not $docName -and $id -match 'attendance') { $docName = "Student Attendance App.pdf" }

  $status = "ok"
  if (($meta.total_api_cost_usd -eq 0) -and (-not $meta.dry_run)) { $status = "failed" }

  $workload = $meta.workload
  if (-not $workload) { $workload = $cfg.workload }
  if (-not $workload) {
    if ($meta.suite -like 'summarization*' -or $meta.suite -like 'summarize*') {
      $workload = 'document_summarization'
    } else {
      $workload = 'interactive_rag'
    }
  }

  $index += [ordered]@{
    campaign_id         = $id
    label               = $label
    benchmark_version   = $meta.benchmark_version
    workload            = $workload
    suite               = $meta.suite
    document_id         = $meta.document_id
    document_name       = $docName
    timestamp_utc       = $meta.timestamp_utc
    models              = $meta.models
    dry_run             = $meta.dry_run
    total_api_cost_usd  = $meta.total_api_cost_usd
    total_runtime_sec   = $meta.total_runtime_sec
    status              = $status
  }
}

$sorted = $index | Sort-Object { $_.timestamp_utc } -Descending
($sorted | ConvertTo-Json -Depth 6) | Set-Content (Join-Path $Dst "index.json") -Encoding UTF8
Write-Host "Synced $($sorted.Count) campaign(s) → $Dst"
