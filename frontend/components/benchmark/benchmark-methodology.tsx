"use client"

import { Card } from "@/components/ui/card"
import type { BenchmarkWorkload } from "@/lib/benchmark-types"

const RAG_POINTS = [
  {
    title: "Retrieve once per question",
    body: "The offline evaluation framework executes the production retrieval pipeline exactly once for each benchmark question. Context is then frozen before any model is called.",
  },
  {
    title: "Identical frozen inputs",
    body: "Every participant — including the Intelligent Router and GPT models — receives the same frozen system prompt, user prompt, retrieved context, and (when present) the same reference answer. A consistency gate aborts the campaign if hashes or chunk counts diverge.",
  },
  {
    title: "Intelligent Router participant",
    body: "The system runner loads the document’s stored RoutingDecision and invokes NIM generation in-process (no production HTTP). Routing metadata (selected model, chain, tier) is recorded alongside latency, tokens, cost, estimated CO₂e, and quality scores.",
  },
  {
    title: "How quality is measured",
    body: "When a reference answer is available, a pluggable BenchmarkEvaluator scores each candidate on correctness, completeness, groundedness, and conciseness (0–100), then derives an overall quality_score. The default evaluator uses exact match, lexical similarity (SequenceMatcher + token F1), length alignment, and context grounding — no embedding models and no extra LLM judge calls.",
  },
  {
    title: "Why multiple quality metrics",
    body: "A single score can hide trade-offs: an answer may be concise but incomplete, or fluent but poorly grounded. Reporting correctness, completeness, groundedness, and conciseness separately makes those failure modes visible while quality_score remains a weighted summary for ranking.",
  },
  {
    title: "Quality vs latency metrics",
    body: "Latency, TTFT, tokens/sec, cost, and CO₂e measure efficiency of generation. Quality metrics measure answer fidelity to a reference and grounding in frozen context. They are independent axes — a fast model can score poorly on quality, and a high-quality model can be expensive or slow.",
  },
  {
    title: "Quality limitations",
    body: "Lexical metrics undervalue paraphrases that are semantically correct. Groundedness is overlap-based, not a full citation auditor. Scores are skipped when no reference_answer exists. Future evaluators (LLM-as-a-Judge, RAGAS, DeepEval, human labels) can register without changing the campaign schema.",
  },
  {
    title: "Prompt & context hashes",
    body: "Each question stores deterministic SHA-256 context_hash and prompt_hash values so any future run can prove that models were evaluated on identical inputs.",
  },
  {
    title: "Estimated carbon accounting",
    body: "Energy and CO₂e figures are estimates derived from the project’s existing Boundary-A helpers (token × J/token × PUE × grid intensity). They are not live meter readings.",
  },
  {
    title: "Versioned, immutable campaigns",
    body: "Each campaign writes a new append-only directory (config, metadata, results, summary, dashboard, report, log). Older campaigns are never overwritten.",
  },
  {
    title: "Read-only dashboard",
    body: "This page loads stored benchmark artifacts only. It does not call OpenAI, does not run retrieval, and does not trigger Interactive RAG or document processing.",
  },
]

const SUMMARIZATION_POINTS = [
  {
    title: "Freeze document once",
    body: "Already-ingested chunks are loaded read-only, ordered by chunk index, and clipped by the suite window. Document text, chunk boundaries, and the summarization prompt template are frozen before any participant runs.",
  },
  {
    title: "Identical frozen inputs",
    body: "Every participant — Intelligent Router, GPT-5 nano, GPT-5 mini, and GPT-5.5 — receives the same frozen document text and prompt. Optional reference summaries are shared identically for quality scoring.",
  },
  {
    title: "Intelligent Router participant",
    body: "Uses the stored RoutingDecision and in-process NIM generation with the frozen summarization messages (no production /summarize HTTP or DAG). Routing metadata is recorded with the other efficiency metrics.",
  },
  {
    title: "How quality is measured",
    body: "The same BenchmarkEvaluator framework scores summaries against an optional reference_summary for correctness, completeness, groundedness, conciseness, and composite quality_score (0–100).",
  },
  {
    title: "Quality vs efficiency",
    body: "Latency, tokens, cost, energy, and CO₂e measure summarization efficiency. Quality scores measure fidelity to the reference and grounding in the frozen document. Insights are generated only from stored aggregates.",
  },
  {
    title: "Suites",
    body: "summarization-smoke, summarization-standard, and summarization-large vary the frozen document window and completion budget — never per-participant inputs.",
  },
  {
    title: "Limitations",
    body: "This workload benchmarks end-to-end summarization of a frozen document window, not the full production map-reduce/DAG pipeline. Lexical quality metrics have the same paraphrase limitations as Interactive RAG.",
  },
  {
    title: "Versioned, immutable campaigns",
    body: "Summarization campaigns reuse the same append-only artifact layout as Interactive RAG and remain fully backward compatible in the dashboard.",
  },
  {
    title: "Read-only dashboard",
    body: "Workload switching only filters stored artifacts. It does not re-run summarization, call OpenAI, or modify production document processing.",
  },
]

export function BenchmarkMethodology({
  workload = "interactive_rag",
}: {
  workload?: BenchmarkWorkload | string
}) {
  const isSum = workload === "document_summarization"
  const points = isSum ? SUMMARIZATION_POINTS : RAG_POINTS
  return (
    <Card className="p-6 md:p-8 bg-gradient-to-br from-card to-card/50 border-border/50">
      <div className="mb-6 max-w-3xl">
        <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-emerald-400/90 mb-2">
          Research methodology
        </p>
        <h3 className="text-xl font-semibold tracking-tight">How benchmarks are generated</h3>
        <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
          {isSum
            ? "Document Summarization campaigns freeze parsed chunks and a shared prompt, then measure Intelligent Router vs GPT baselines on identical inputs."
            : "Interactive RAG campaigns freeze retrieval and prompts once per question, then measure Intelligent Router vs GPT baselines on identical inputs."}{" "}
          Each campaign persists an auditable artifact bundle.
        </p>
      </div>

      <ol className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {points.map((p, i) => (
          <li
            key={p.title}
            className="rounded-lg border border-border/50 bg-black/20 p-4"
          >
            <div className="flex items-baseline gap-3 mb-2">
              <span className="font-mono text-[11px] text-muted-foreground">
                {String(i + 1).padStart(2, "0")}
              </span>
              <h4 className="text-sm font-semibold text-foreground">{p.title}</h4>
            </div>
            <p className="text-sm text-muted-foreground leading-relaxed pl-8">{p.body}</p>
          </li>
        ))}
      </ol>
    </Card>
  )
}
