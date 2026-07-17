/** Types for offline benchmark campaign artifacts (read-only). */

export type BenchmarkWorkload = "interactive_rag" | "document_summarization"

export type CampaignIndexEntry = {
  campaign_id: string
  label: string
  benchmark_version: string
  workload?: BenchmarkWorkload | string
  suite: string
  document_id: string
  document_name?: string | null
  timestamp_utc: string
  models: string[]
  dry_run?: boolean
  total_api_cost_usd?: number
  total_runtime_sec?: number
  status?: "ok" | "failed" | string
}

export type ModelChartRow = {
  model: string
  avg_latency_ms?: number | null
  p50_latency_ms?: number | null
  p95_latency_ms?: number | null
  avg_ttft_ms?: number | null
  avg_tokens_per_sec?: number | null
  avg_prompt_tokens?: number | null
  avg_completion_tokens?: number | null
  avg_estimated_api_cost_usd?: number | null
  total_estimated_api_cost_usd?: number | null
  avg_estimated_energy_wh?: number | null
  total_estimated_energy_wh?: number | null
  avg_estimated_co2e_g?: number | null
  total_estimated_co2e_g?: number | null
  avg_quality_score?: number | null
  median_quality_score?: number | null
  avg_correctness?: number | null
  avg_completeness?: number | null
  avg_groundedness?: number | null
  avg_conciseness?: number | null
  n_ok?: number
  n_failed?: number
  n_runs?: number
  n_quality_scored?: number
}

export type Highlight = {
  model: string
  value: number
  metric: string
} | null

export type DashboardPayload = {
  schema_version: string
  campaign_id: string
  generated_at_utc: string
  workload?: BenchmarkWorkload | string
  models: string[]
  charts: {
    latency_comparison: { unit: string; labels: string[]; series: ModelChartRow[] }
    ttft_comparison: { unit: string; labels: string[]; series: ModelChartRow[] }
    tokens_per_sec: { unit: string; labels: string[]; series: ModelChartRow[] }
    prompt_vs_completion_tokens: {
      unit: string
      labels: string[]
      series: ModelChartRow[]
    }
    estimated_cost: { unit: string; labels: string[]; series: ModelChartRow[] }
    estimated_energy: { unit: string; labels: string[]; series: ModelChartRow[] }
    estimated_co2e: { unit: string; labels: string[]; series: ModelChartRow[] }
    quality_overview?: {
      unit: string
      labels: string[]
      series: ModelChartRow[]
    }
    quality_distribution?: Record<string, number | null | undefined>
    quality_vs_latency?: {
      unit: string
      points: Array<{
        model?: string
        quality?: number | null
        latency_ms?: number | null
      }>
    }
    quality_vs_cost?: {
      unit: string
      points: Array<{
        model?: string
        quality?: number | null
        cost_usd?: number | null
      }>
    }
    quality_vs_co2e?: {
      unit: string
      points: Array<{
        model?: string
        quality?: number | null
        co2e_g?: number | null
      }>
    }
    quality_vs_throughput?: {
      unit: string
      points: Array<{
        model?: string
        quality?: number | null
        tokens_per_sec?: number | null
      }>
    }
  }
  table: { per_model: ModelChartRow[] }
  highlights: {
    fastest_model: Highlight
    highest_tokens_per_sec: Highlight
    lowest_estimated_cost: Highlight
    lowest_estimated_co2e: Highlight
    best_quality_model?: Highlight
  }
  quality?: {
    avg_quality_score?: number | null
    median_quality_score?: number | null
    best_quality_model?: Highlight
    n_scored?: number
    distribution?: Record<string, number | null | undefined>
    insights?: string[]
    evaluator?: string | null
  }
  totals: {
    total_api_cost_usd?: number
    total_runtime_sec?: number
    total_prompt_tokens?: number
    total_completion_tokens?: number
    total_tokens?: number
    questions?: number
    avg_quality_score?: number
    median_quality_score?: number
  }
  reproducibility: {
    benchmark_version?: string
    retrieval_version?: string
    prompt_version?: string
    document_id?: string
    timestamp_utc?: string
    suite?: string
    questions?: Array<{
      question?: string
      document_id?: string
      context_hash?: string
      prompt_hash?: string
      chunk_count?: number
    }>
  }
}

export type CampaignConfig = {
  campaign_id: string
  benchmark_version: string
  workload?: BenchmarkWorkload | string
  retrieval_version?: string
  document_freeze_version?: string
  prompt_version: string
  suite: string
  document_id?: string | null
  filename?: string | null
  models: string[]
  questions: string[]
  question_count: number
  dry_run?: boolean
}

export type CampaignMetadata = {
  campaign_id: string
  benchmark_version: string
  workload?: BenchmarkWorkload | string
  retrieval_version?: string
  document_freeze_version?: string
  prompt_version: string
  document_id: string
  timestamp_utc: string
  finished_utc?: string
  suite: string
  models: string[]
  dry_run?: boolean
  total_runtime_sec?: number
  total_api_cost_usd?: number
  context_and_prompt_hashes?: Array<{
    question?: string
    document_id?: string
    context_hash?: string
    prompt_hash?: string
    chunk_count?: number
  }>
}

export type QuestionRun = {
  model?: string
  model_returned?: string | null
  ok?: boolean
  error?: string | null
  answer?: string
  summary?: string
  summary_length?: number | null
  summary_chars?: number | null
  summary_words?: number | null
  latency_ms?: number | null
  ttft_ms?: number | null
  tokens_per_sec?: number | null
  prompt_tokens?: number | null
  completion_tokens?: number | null
  total_tokens?: number | null
  estimated_api_cost_usd?: number | null
  estimated_energy_wh?: number | null
  estimated_co2e_g?: number | null
  finish_reason?: string | null
  participant_kind?: string | null
  routing?: {
    selected_model?: string | null
    model_used?: string | null
    model_chain?: string[]
    tier?: string | null
    mode?: string | null
    reason_summary?: string | null
    execution_path?: string | null
    [key: string]: unknown
  } | null
  quality?: {
    quality_score?: number | null
    correctness?: number | null
    completeness?: number | null
    groundedness?: number | null
    conciseness?: number | null
    notes?: string[]
    skipped?: boolean
    skip_reason?: string | null
    [key: string]: unknown
  } | null
  quality_score?: number | null
  correctness?: number | null
  completeness?: number | null
  groundedness?: number | null
  conciseness?: number | null
}

export type QuestionExplorerItem = {
  question: string
  task?: string | null
  ok?: boolean
  document_id?: string
  context_hash?: string
  prompt_hash?: string
  chunk_count?: number
  reference_answer?: string | null
  reference_summary?: string | null
  model_runs: QuestionRun[]
}

export type CampaignBundle = {
  index: CampaignIndexEntry
  config: CampaignConfig
  metadata: CampaignMetadata
  dashboard: DashboardPayload
  summary: Record<string, unknown>
  questions: QuestionExplorerItem[]
}
