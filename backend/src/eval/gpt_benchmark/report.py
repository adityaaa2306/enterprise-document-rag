"""Generate a Markdown benchmark report suitable for project documentation."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _fmt(v: Any, digits: int = 3) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def _highlight_line(title: str, entry: Optional[Dict[str, Any]], unit: str = "") -> str:
    if not entry:
        return f"- **{title}:** —"
    u = f" {unit}" if unit else ""
    return f"- **{title}:** `{entry.get('model')}` ({_fmt(entry.get('value'))}{u})"


def render_markdown_report(
    *,
    campaign_id: str,
    config: Dict[str, Any],
    results_payload: Dict[str, Any],
    aggregates: Dict[str, Any],
    dashboard: Dict[str, Any],
) -> str:
    meta = results_payload.get("metadata") or {}
    summary = results_payload.get("summary") or {}
    per_model = aggregates.get("per_model") or {}
    highlights = dashboard.get("highlights") or {}
    models = list(meta.get("models") or per_model.keys())

    lines: List[str] = []
    workload = (
        meta.get("workload")
        or config.get("workload")
        or aggregates.get("metadata", {}).get("workload")
        or "interactive_rag"
    )
    is_summarization = workload == "document_summarization"

    lines.append(f"# GPT Benchmark Report — `{campaign_id}`")
    lines.append("")
    lines.append("## Campaign information")
    lines.append("")
    lines.append(f"- **Campaign ID:** `{campaign_id}`")
    lines.append(
        f"- **Workload:** `{'Document Summarization' if is_summarization else 'Interactive RAG'}`"
    )
    lines.append(f"- **Suite:** `{meta.get('suite')}`")
    lines.append(f"- **Document ID:** `{meta.get('document_id')}`")
    lines.append(f"- **Timestamp (UTC):** `{meta.get('timestamp_utc') or meta.get('timestamp')}`")
    lines.append(f"- **Finished (UTC):** `{meta.get('finished_utc')}`")
    lines.append(f"- **Dry run:** `{meta.get('dry_run')}`")
    lines.append(f"- **Max tokens:** `{config.get('max_tokens')}`")
    lines.append(f"- **Temperature:** `{config.get('temperature')}`")
    lines.append("")
    lines.append("## Models evaluated")
    lines.append("")
    for m in models:
        lines.append(f"- `{m}`")
    lines.append("")
    lines.append("## Benchmark methodology")
    lines.append("")
    if is_summarization:
        lines.append(
            "Document chunks are loaded **once** from storage (read-only). Parsed "
            "content, chunk boundaries, and the summarization prompt template are "
            "frozen (`context_hash`, `prompt_hash`) and validated before every "
            "participant call so all participants receive identical document text — "
            "including the same optional `reference_summary` for quality scoring. "
            "The Intelligent Router uses in-process NIM + the stored RoutingDecision; "
            "GPT participants use OpenAI Chat Completions. Production summarization "
            "HTTP / DAG pipelines are not invoked."
        )
    else:
        lines.append(
            "Each question retrieves context **once** via the production retrieval "
            "pipeline. The resulting context and prompt are frozen (`context_hash`, "
            "`prompt_hash`) and validated before every participant call so all "
            "participants (GPT models and the Intelligent Router) receive identical "
            "inputs — including the same optional `reference_answer` for quality scoring. "
            "Generation for GPT participants uses OpenAI Chat Completions (streaming) and "
            "is isolated from Interactive RAG / ResponseAgent."
        )
    lines.append("")
    lines.append(
        "### Quality evaluation"
    )
    lines.append("")
    lines.append(
        "When a reference answer is present, a pluggable `BenchmarkEvaluator` scores "
        "each candidate on correctness, completeness, groundedness, and conciseness "
        "(0–100) and derives an overall `quality_score`. The default "
        f"`{meta.get('quality_evaluator') or 'default_composite_v1'}` evaluator uses "
        "exact match, lexical similarity (stdlib SequenceMatcher + token F1), length "
        "alignment, and context grounding — **not** embedding cosine similarity and "
        "**not** an LLM-as-a-Judge. Quality is independent of latency/cost/CO₂e: "
        "efficiency metrics measure resource use; quality metrics measure answer "
        "fidelity and grounding. Lexical metrics undervalue valid paraphrases; "
        "future evaluators (LLM judge, RAGAS, DeepEval, human) can register without "
        "changing the campaign schema."
    )
    lines.append("")
    quality = aggregates.get("quality") or dashboard.get("quality") or {}
    if quality.get("insights"):
        lines.append("### Quality insights")
        lines.append("")
        for tip in quality.get("insights") or []:
            lines.append(f"- {tip}")
        lines.append("")
    lines.append("| Version field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Benchmark version | `{meta.get('benchmark_version')}` |")
    lines.append(f"| Retrieval version | `{meta.get('retrieval_version')}` |")
    lines.append(
        f"| Prompt version | `{meta.get('prompt_version') or meta.get('prompt_template_version')}` |"
    )
    lines.append(f"| Quality evaluator | `{meta.get('quality_evaluator') or '—'}` |")
    lines.append("")
    lines.append("## Overall statistics")
    lines.append("")
    lines.append(f"- **Questions:** {_fmt(summary.get('questions'), 0)}")
    lines.append(f"- **Models:** {_fmt(summary.get('models'), 0)}")
    lines.append(f"- **Total prompt tokens:** {_fmt(summary.get('total_prompt_tokens'), 0)}")
    lines.append(
        f"- **Total completion tokens:** {_fmt(summary.get('total_completion_tokens'), 0)}"
    )
    lines.append(f"- **Total tokens:** {_fmt(summary.get('total_tokens'), 0)}")
    lines.append(
        f"- **Total benchmark cost (USD):** ${_fmt(summary.get('total_api_cost_usd') or summary.get('estimated_api_cost_usd'), 6)}"
    )
    lines.append(
        f"- **Total benchmark runtime (s):** {_fmt(summary.get('total_runtime_sec'), 2)}"
    )
    lines.append(
        f"- **Avg quality score:** {_fmt(quality.get('avg_quality_score') or summary.get('avg_quality_score'), 2)}"
    )
    lines.append(
        f"- **Median quality score:** {_fmt(quality.get('median_quality_score') or summary.get('median_quality_score'), 2)}"
    )
    lines.append("")
    lines.append("## Per-model statistics")
    lines.append("")
    lines.append(
        "| Model | Avg latency (ms) | p50 | p95 | Avg TTFT (ms) | "
        "Avg tok/s | Avg prompt tok | Avg completion tok | "
        "Total cost (USD) | Avg energy (Wh) | Avg CO₂e (g) | Avg quality |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    from src.eval.gpt_benchmark.participants import display_name

    for m in models:
        s = per_model.get(m) or {}
        lines.append(
            "| `{model}` | {lat} | {p50} | {p95} | {ttft} | {tps} | {pt} | {ct} | {cost} | {en} | {co2} | {q} |".format(
                model=display_name(m),
                lat=_fmt(s.get("avg_latency_ms"), 2),
                p50=_fmt(s.get("p50_latency_ms"), 2),
                p95=_fmt(s.get("p95_latency_ms"), 2),
                ttft=_fmt(s.get("avg_ttft_ms"), 2),
                tps=_fmt(s.get("avg_tokens_per_sec"), 2),
                pt=_fmt(s.get("avg_prompt_tokens"), 1),
                ct=_fmt(s.get("avg_completion_tokens"), 1),
                cost=_fmt(s.get("total_estimated_api_cost_usd"), 6),
                en=_fmt(s.get("avg_estimated_energy_wh"), 4),
                co2=_fmt(s.get("avg_estimated_co2e_g"), 4),
                q=_fmt(s.get("avg_quality_score"), 2),
            )
        )
    lines.append("")
    lines.append("## Highlights")
    lines.append("")
    lines.append(
        _highlight_line("Fastest model (avg latency)", highlights.get("fastest_model"), "ms")
    )
    lines.append(
        _highlight_line(
            "Lowest estimated cost",
            highlights.get("lowest_estimated_cost"),
            "USD",
        )
    )
    lines.append(
        _highlight_line(
            "Lowest estimated CO₂e",
            highlights.get("lowest_estimated_co2e"),
            "g",
        )
    )
    lines.append(
        _highlight_line(
            "Best quality model",
            highlights.get("best_quality_model") or quality.get("best_quality_model"),
            "/100",
        )
    )
    lines.append(
        f"- **Total benchmark runtime:** {_fmt(summary.get('total_runtime_sec'), 2)} s"
    )
    lines.append(
        f"- **Total benchmark cost:** ${_fmt(summary.get('total_api_cost_usd') or summary.get('estimated_api_cost_usd'), 6)}"
    )
    lines.append("")
    lines.append("## Reproducibility anchors")
    lines.append("")
    lines.append(
        "Every question stores `document_id`, `context_hash`, and `prompt_hash`. "
        "Re-run the same campaign configuration against the same ingested document "
        "to reproduce identical inputs for all models."
    )
    lines.append("")
    lines.append("| Question | Context hash (12) | Prompt hash (12) | Chunks |")
    lines.append("|---|---|---|---:|")
    for q in results_payload.get("questions") or []:
        qtext = (q.get("question") or "").replace("|", "\\|")
        if len(qtext) > 60:
            qtext = qtext[:57] + "..."
        ch = (q.get("context_hash") or "")[:12]
        ph = (q.get("prompt_hash") or "")[:12]
        lines.append(
            f"| {qtext} | `{ch}` | `{ph}` | {_fmt(q.get('chunk_count'), 0)} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "*Generated automatically by `src.eval.gpt_benchmark` — offline evaluation only; "
        "not part of the production Interactive RAG path.*"
    )
    lines.append("")
    return "\n".join(lines)
